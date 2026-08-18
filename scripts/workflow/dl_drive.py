#!/usr/bin/env python3
"""dl_drive.py - headless driver：外部编排器（v3，designs/headless-driver-arch-design.md）。

替代「一个长 TUI 会话 + Stop hook 推进」：每个子步骤/阶段一个全新 `claude -p`
短会话（上下文 = 交接包 + 当前步目的，按构造最小），门控/推进由本进程直调
dl_flow_engine（state.json + evidence.jsonl 磁盘真源，天然会话无关）。

动机（2026-08-08 tail_volume 审计）：单会话上下文 244k→485k 零锯齿、cache_read
318.7M（成本=轮次×上下文的平方膨胀）；边界 /clear 提示 15 次注入 0 次上屏
（attachment 进模型不被转达，且 /clear 无程序化入口）。

交互子步骤（Step.interactive，读回步等 AskUserQuestion 场景）后台化预处理
（interactive-step-headless-prep §4.1）：headless 备问题清单 → NEED_USER 转 TUI
纯问答；裸开场（u:1#1 无返工）除外，保 TUI 原生开场（57a64e1 用户裁决）。
门栏/闸门 = 本进程前台断点，stdin 收 gate/back/state-reset 等（转发 dl-cmd.sh，
外部终端 /dl 并发也兼容——每轮循环重读 state.json）。

被 dl-launch.sh 派发（ac-deepseek1 --dl <name> [--debug]）；WF_TUI=1 回旧 TUI 路径。
--segment = 段模式（v4 前台混合，front-tui-hybrid-design §2.2）：从 state 当前位置
连续跑非交互工作（交互步先 headless 预处理备问题，NEED_USER 转前台纯问答），
撞裸开场/门栏/闸门/断点按退出码收场（无 stdin 断点）。
"""

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

_DLWF_ROOT = Path(__file__).resolve().parents[2]  # ~/.dl-workflow/
sys.path.insert(0, str(_DLWF_ROOT))
import dl_flow_engine as engine  # noqa: E402
from scripts.workflow import project_tools  # noqa: E402

try:  # 常驻进度区依赖（drive-tasklist-render-design §2.1）；缺失时降级事件打印
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.text import Text

    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

LIB_DIR = Path(__file__).resolve().parent  # scripts/workflow/
DL_CMD = LIB_DIR / "dl-cmd.sh"
PHASE_RULES_TEMPLATE = LIB_DIR / "phase-rules.md"

PHASE_DONE_RE = re.compile(r"###\s*PHASE_DONE:\s*([a-z_]+)")
NEED_USER_RE = re.compile(r"###\s*NEED_USER")

# 无新 trace 重发上限：headless 会话结束但门控读不到产出（模型没落库），
# 尖锐重发 N 次仍无 -> 断点等用户（防无限白烧，对齐 escalate 语义）。
NONE_RETRY_LIMIT = 3

# Ctrl+C 语义（drive-tasklist-render-design §2.6，2026-08-09 用户裁决）：
# 单击=中断当前活动（TUI 原生中断生成 / headless 杀子会话进断点），
# 双击=退出这个会话包括子任务（driver 退 130）。
RC_INTERRUPTED = -2  # run_session 返回哨兵：单击已中断子会话（drive 进断点裁决）


def _pwait_interruptible(
    proc: "subprocess.Popen", on_first, already_interrupted: bool = False
) -> int:
    """等子进程退出；单击 Ctrl+C 调 on_first()（中断语义）后继续等，
    双击 Ctrl+C 杀子进程并 SystemExit(130)——退出这个会话包括子任务。
    already_interrupted=True：调用方已计过单击（读循环里捕过），本次即双击。
    """
    interrupted = already_interrupted
    while True:
        try:
            return proc.wait()
        except KeyboardInterrupt:
            if interrupted:
                proc.kill()
                print(
                    "\n✗ 用户中断（双击）——已退出。state 在磁盘，`dl <name>` 随时续。"
                )
                raise SystemExit(130)
            interrupted = True
            on_first()


# ---------- 基础设施 ----------


def _meta_root(project_root: Path, name: str) -> Path:
    return project_root / ".claude" / "workflows" / name


def _load(project_root: Path, name: str) -> dict:
    state = engine.load_state(project_root, name)
    if state is None:
        raise SystemExit(f"✗ 工作流 {name} 的 state.json 缺失")
    return engine.normalize_state(state)


def _record_segment(
    project_root: Path, name: str, *, session_id: str, kind: str, note: str
) -> None:
    """段会话留痕（审计用）：session id + 类型 + 当时节点指针。上限 200 条防膨胀。"""
    state = _load(project_root, name)
    segs = state.setdefault("segment_sessions", [])
    segs.append(
        {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "session_id": session_id,
            "kind": kind,
            "node": state.get("node"),
            "sub_step": state.get("sub_step_index"),
            "note": note,
        }
    )
    del segs[:-200]
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    engine.save_state(project_root, name, state)


# ---------- P2-4 段链合并（designs/segment-chain-resume-design.md） ----------
# 会话合并非派发合并：逐步派发 + 步间 gate 不变，仅「下一步新会话」改
# 「--resume 同会话续跑」。链粒度 = minor_state。


# ---------- u1-sub5-cost 修3：红队 driver 预派发 ----------
# （designs/u1-sub5-cost-optimization-design.md）：红队输入只依赖 ≤子4 trace
# （redteam-prompt 机械保证不含子5 结论），子4 gate 一过即具备派发条件。
# 实测红队跑 158-235s 而主会话有效并行 ≤1min（轮2 零并行干等 2.7min）——
# 把派发从「子5 段内模型动作」前移为「driver 派段动作」，红队运行与子5
# 主会话工作（①③④ ≈2-3min）重叠。收录侧 = engine --ingest-redteam。


def _maybe_predispatch_redteam(
    project_root: Path,
    name: str,
    step: "engine.Step",
    *,
    wt: Path,
    settings: Path,
    meta: Path,
    disp: "LiveProgress | None" = None,
) -> None:
    """pre_dispatch=redteam 步派段前预起红队 worker（幂等，freshness 按 prompt sha1）。

    - prompt = engine.redteam_prompt（子1-4 最新 trace；None=无子4 trace →
      跳过，ingest 侧 fail loud 指路回退会话内路径）；
    - worker.json（meta/redteam_worker.json）记 {pid, started_at, prompt_sha1,
      session_id}：sha 相同且（pid 活 或 报告非空）→ 复用不重派；
      sha 变（state-reset 后子4 证据变了）→ SIGTERM 旧进程、重派；
    - spawn 形态对齐段会话（drive settings + stdin prompt[E2BIG 纪律] +
      start_new_session），差异：`--tools Read` 把纪律1「Read 为主、其它
      不要试」从文案变结构（judge --tools "" 同范式）；stdout 重定向
      meta/redteam_report.md（文本输出=最终报告）；不解析 stream（无需
      进度透出——worker 完成信号 = pid 死 + 报告非空，ingest 侧判定）。
    """
    if getattr(step, "pre_dispatch", "") != "redteam":
        return
    prompt = engine.redteam_prompt(project_root, name)
    if prompt is None:
        return
    report = meta / "redteam_report.md"
    wj_path = meta / "redteam_worker.json"
    sha = hashlib.sha1(prompt.encode("utf-8")).hexdigest()
    if wj_path.exists():
        try:
            old = json.loads(wj_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            old = None
        if isinstance(old, dict) and old.get("prompt_sha1") == sha:
            if engine.pid_alive(old.get("pid")) or (
                report.exists() and report.stat().st_size > 0
            ):
                return  # 在跑或已完工——复用
        elif isinstance(old, dict):
            try:
                os.kill(int(old.get("pid")), signal.SIGTERM)
            except (ProcessLookupError, OverflowError, ValueError, TypeError):
                pass
    sid = str(uuid.uuid4())
    cmd = [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--tools",
        "Read",
        "--permission-mode",
        "acceptEdits",
        "--settings",
        str(settings),
        "--session-id",
        sid,
    ]
    # O1（u1-overall-cost）：--tools Read 只限内置工具、限不住 MCP（worker 经 MCP
    # 调 tavily_extract 实证）——strict-mcp-config 把「Read 为主」从文案升结构
    cmd += engine.NO_MCP_ARGS
    meta.mkdir(parents=True, exist_ok=True)
    with (
        open(report, "w", encoding="utf-8") as rep_f,
        open(meta / "cc_sdk.log", "a", encoding="utf-8") as err_f,
    ):
        proc = subprocess.Popen(
            cmd,
            cwd=str(wt),
            stdin=subprocess.PIPE,
            stdout=rep_f,
            stderr=err_f,
            text=True,
            start_new_session=True,
        )
        assert proc.stdin is not None
        proc.stdin.write(prompt)
        proc.stdin.close()
    wj_path.write_text(
        json.dumps(
            {
                "pid": proc.pid,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "prompt_sha1": sha,
                "session_id": sid,
            }
        ),
        encoding="utf-8",
    )
    if disp is not None:
        disp.log("  ⚑ 红队预派发（子4 证据已冻结）——与本步段并行跑")


def _chain_resume_sid(state: dict, node_id: str, cur: int) -> "str | None":
    """当前 headless-step 可续链则返回链 session_id，否则 None（新会话）。

    不变式三条件：节点在白名单（试点纪律，空名单 = 全局关 = 回滚面）+ 链属
    当前节点（node-rules system prompt 同节点恒定 = 缓存前缀保真）+
    last_step == cur-1（序列连续——state-reset/back/jump/step-pass/TUI 段
    天然失配断链，无需显式清）。
    """
    if node_id not in engine.SEGMENT_CHAIN_NODES:
        return None
    chain = state.get("segment_chain")
    if not isinstance(chain, dict):
        return None
    if chain.get("node") != node_id or chain.get("last_step") != cur - 1:
        return None
    sid = chain.get("sid")
    return sid if isinstance(sid, str) and sid else None


def _chain_update(
    project_root: Path, name: str, node_id: str, cur: int, sid: str
) -> None:
    """gate advanced 后落链；推进出白名单节点 = 链作废（防陈旧残留误导审计）。"""
    st = _load(project_root, name)
    if node_id in engine.SEGMENT_CHAIN_NODES:
        st["segment_chain"] = {
            "node": node_id,
            "sid": sid,
            "last_step": cur,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    else:
        st.pop("segment_chain", None)
    engine.save_state(project_root, name, st)


def _chain_clear(project_root: Path, name: str) -> None:
    """显式断链（RC_INTERRUPTED 杀中段——transcript 尾部可能残留半个 turn）。"""
    st = _load(project_root, name)
    if st.pop("segment_chain", None) is not None:
        engine.save_state(project_root, name, st)


def _chain_warn_line(last_ctx: "int | None", note: str) -> "str | None":
    """链上下文峰值告警行；未超/无数据返回 None（宁纵勿枉只告警）。"""
    if last_ctx is None or last_ctx <= CHAIN_CONTEXT_WARN:
        return None
    return (
        f"  ⚠ 链会话上下文 {last_ctx:,} tok 超阈值 {CHAIN_CONTEXT_WARN:,}"
        f"（{note}）——链内膨胀，查交接包/步产出体积"
    )


def _rewrite_hook_paths(data: dict) -> dict:
    """hook 命令路径重写到与 driver 同仓的 hooks/（版本一致性）。

    per-wf settings.json 硬编码 `~/.dl-workflow/hooks/*.py`（main 树）。生产环境
    （driver 合入 main）重写=恒等；worktree dogfood 时必须指向 worktree 版
    hooks——否则 drive_mode 降级分支不存在 = advance 与 driver 双 orchestrator。
    """
    hooks_dir = str(_DLWF_ROOT / "hooks") + "/"
    for event_hooks in (data.get("hooks") or {}).values():
        for entry in event_hooks:
            for h in entry.get("hooks") or []:
                cmd = h.get("command")
                if isinstance(cmd, str) and "~/.dl-workflow/hooks/" in cmd:
                    h["command"] = cmd.replace("~/.dl-workflow/hooks/", hooks_dir)
    return data


def ensure_drive_settings(project_root: Path, name: str) -> Path:
    """drive 版 settings：per-wf settings.json 派生——去 outputStyle（TUI 横幅引导）
    与 SessionStart hook（交接包由 driver prompt 注入，防双份）与 statusLine
    （TUI 底部进度栏，headless claude -p 无 TUI，v4-statusline-progress-design §5.2）。
    workflow_advance / step_fence / phase 保留（hook 内 drive_mode 分支降级/收窄）。
    内容变化才重写（per-wf settings.json 是真源，版本戳机制天然覆盖模板升级）。
    """
    meta = _meta_root(project_root, name)
    src = meta / "settings.json"
    dst = meta / "settings.drive.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    data.pop("outputStyle", None)
    data.pop("statusLine", None)
    hooks = data.get("hooks") or {}
    hooks.pop("SessionStart", None)
    if hooks:
        data["hooks"] = hooks
    else:
        data.pop("hooks", None)
    text = json.dumps(_rewrite_hook_paths(data), ensure_ascii=False, indent=2)
    if not dst.exists() or dst.read_text(encoding="utf-8") != text:
        dst.write_text(text, encoding="utf-8")
    return dst


def ensure_tui_settings(project_root: Path, name: str) -> Path:
    """TUI 段 settings：全量 settings.json + hook 路径重写（同 _rewrite_hook_paths
    的版本一致性动机；生产恒等，dogfood 指向 worktree 版 hooks）。"""
    meta = _meta_root(project_root, name)
    src = meta / "settings.json"
    dst = meta / "settings.drive-tui.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    text = json.dumps(_rewrite_hook_paths(data), ensure_ascii=False, indent=2)
    if not dst.exists() or dst.read_text(encoding="utf-8") != text:
        dst.write_text(text, encoding="utf-8")
    return dst


def ensure_phase_rules(project_root: Path, name: str) -> Path:
    """全量 phase-rules 渲染产物（无编排阶段 execute/review/evolution 的会话用）。"""
    meta = _meta_root(project_root, name)
    out = meta / "phase-rules.rendered.md"
    if out.exists():
        return out  # dl-launch 已渲染（模板每次 launch 重渲染，新鲜度随启动）
    text = engine.render_phase_rules(PHASE_RULES_TEMPLATE.read_text(encoding="utf-8"))
    out.write_text(text, encoding="utf-8")
    return out


def ensure_node_rules(
    project_root: Path, name: str, node: "engine.Node", cur: int
) -> Path:
    """节点级 system prompt（瘦版）：只含本节点子步骤段落——92KB 全量税按构造消失。

    O2（u1-overall-cost）：清单渲染 titles-only（render_substeps_brief）——当前步
    完整目的双通道已在（段 prompt 逐字携带 + TUI 每轮注入 primacy 置顶），其余步
    purpose 全文是每调用重付的死重（u:1 node-rules 实测 25k 字符，清单 ~15k）。
    """
    meta = _meta_root(project_root, name)
    nid = engine.node_id(node.phase, node.sub)
    out = meta / f"node-rules.{nid}.md"
    section = engine.render_substeps_brief(nid, cur)
    phase_label = engine.PHASE_LABELS.get(node.phase, node.phase)
    text = (
        f"# WORKFLOW 节点规则（driver 装配瘦版——全量 phase-rules 不注入）\n\n"
        f"你在外部 driver 编排的工作流会话中执行子步骤。**每次派发只做当前一个子步骤**；"
        f"后续步骤由 driver 另行派发，与你无关。门控只认 evidence trace"
        f"（append-trace 落库），不认可完成标记。\n\n"
        f"## 通用纪律\n"
        f"- 完成后必须 append-trace 落库（--scaffold 生成骨架 → Edit 填「待填」→ --from-file）\n"
        f"- 禁输出 ### STEP_DONE / ### PHASE_DONE 标记（外部编排，标记无效）\n"
        f"- 当前阶段「{phase_label}」的写权限由 S11 硬约束执行（禁写范围见 phase-rules）\n"
        f"- 禁静默兜底：捕获异常必 log，默认值必标记，缺数据必暴露\n"
        f"- 载荷格式以 --scaffold 骨架为准：字段标头（【purpose】【qa】【q】【a】【statements】"
        f"【text】【type_label】【boundary】【fields.*】）逐字照抄骨架，"
        f"禁反向 grep engine 源码（dl_flow_engine.py）核对格式/校验规则——"
        f"骨架 + 本节点 purpose 已含全部格式信息\n\n"
        f"## 本节点子步骤清单\n\n"
        f"{section}\n"
    )
    # 项目注册工具注入（组件 B）：只读发现类命令，可直接用 Bash 调用。
    # name 是「给模型看的名字」必须渲染；load_project_tools 只校验键存在不校验值
    # 类型——name/command/description 可能为 None，`or ''` 兜底防渲染出字面 "None"；
    # arg_hint 空/None 则不挂参数标注。
    tools = project_tools.load_project_tools(project_root)
    if tools:
        lines = [
            "## 本项目工具\n\n以下命令由项目注册（只读发现类），可直接用 Bash 调用：\n"
        ]
        for t in tools:
            hint = f"（参数：{t['arg_hint']}）" if t.get("arg_hint") else ""
            lines.append(
                f"- {t['name'] or ''}：`{t['command'] or ''}` {hint}"
                f" — {t.get('description') or ''}"
            )
        text += "\n".join(lines) + "\n"
    # 发现台账提示（discovery-ledger）：dl codebase query 工具级去重，模型无需手工查账
    ledger = project_root / ".claude" / "workflows" / name / "discoveries.jsonl"
    text += (
        f"\n## 发现台账\n"
        f"`dl codebase query --symbol/--history` 会自动落账去重到 {ledger}；"
        f"重查同一 symbol/history 返回缓存（source=discovery-ledger），无需手工查账。\n"
    )
    # u:1 子2b 注入子2a atomic_questions（「查什么」；designs/u1-sub2b-mechanical-
    # symbol-extraction-design.md v2）。v1 教训：string-files 全量命中注入 350 文件
    # 噪音（grep 命中面≠取证起点），且逼子2a 重探索（16→61 轮）。v2：只注入
    # atomic_questions（聚焦计划），不注入 grep 命中面；符号/文件让子2b 按 atomic
    # 现场用 trace/history 取（结构查询的 file:line 才是真实起点）。
    # O2（u1-overall-cost）：注入收窄到消费步（子2b 挖链 cur=3 / 子4 按档取证
    # cur=4）——子5+ 的 claim/tier 上下文已在包内 trace 全文，注入是重复税。
    if nid == "understand:1" and cur in (3, 4):
        aq = engine._load_atomic_questions(project_root, name)
        if aq:
            text += (
                "\n## 子2a atomic_questions（已自动注入，子2b/子4 必须按此清单执行）\n\n"
                "以下 JSON 是子2a 最新 trace 的 atomic_questions。子2b 启动时必须按此"
                "清单逐项挖因果链，不重新拆解问题、不重新定档。按每个原子的问题指向"
                "用 `dl codebase trace <symbol>` / `dl codebase query --history <file>:<line>`"
                " 定位因果环，不必再做 broad string search。\n\n"
                f"```json\n{json.dumps(aq, ensure_ascii=False, indent=2)}\n```\n"
            )
    if not out.exists() or out.read_text(encoding="utf-8") != text:
        out.write_text(text, encoding="utf-8")
    return out


def _bash_shape_rules(project_root: Path) -> str:
    """Bash 命令形态铁律（2026-08-09 interaction_turnover dogfood 四类弹窗/报错实证）。

    这些形态触发 Claude Code 安全守卫或解析器失败——白名单按命令头前缀收，
    守卫类（cd+git 信任检查 / 换行+# 校验绕过检查）甚至无视白名单照弹，
    唯一根治 = 从生成侧禁掉这些形态。单源：build_step_prompt 铁律块 +
    ensure_tui_rules（裸开场 TUI 唯一通道）双处注入。
    """
    py = project_root / "venv" / "bin" / "python"
    py_cmd = str(py) if py.exists() else "python3"
    return (
        "Bash 形态铁律（违反=触发 CC 安全守卫必弹窗或解析失败，加白名单也管不到）：\n"
        f"- 查主仓 git 一律 `git -C {project_root} ...`；禁 `cd <目录> && git`"
        "（cd+git 信任守卫必弹窗）\n"
        f"- 项目 Python 一律 `{py_cmd}`（白名单按前缀收此形态；禁 `./venv/...`"
        f" 相对形态、禁 `VAR=值 cmd` 裸赋值前缀——要环境变量用 `env VAR=值 {py_cmd}`"
        "，env: 已在白名单）\n"
        '- `python -c "` 代码体顶格（前导缩进=IndentationError），禁 `#` 注释'
        "（换行+`#` 触发校验绕过守卫必弹窗）——说明文字写在命令外的正文里\n"
        "- 禁 `$(...)` 命令替换内嵌（解析器 Parse error 直接失败）——拆两条命令："
        "先跑查值，再把字面量写进下一条"
    )


def ensure_tui_rules(
    project_root: Path, name: str, node: "engine.Node", cur: int, state: dict
) -> Path:
    """TUI 段 system prompt = node-rules + TUI 开场纪律段（单源：TUI 可见面契约）。

    动机（drive-tasklist-render-design §2.3 修订）：TaskList/横幅条款原住
    build_step_prompt——裸开场（§2.4 修订2）不喂 prompt，条款随通道一起消失，
    真机实证零 TaskCreate/零横幅/闷头探查被用户中断。搬进 system prompt
    （裸开场抽不走的最高优先级可见面）；headless 段仍用 ensure_node_rules
    （无 TUI 可透出，不带本段）。

    清单内容同源（2026-08-09 用户裁决「内容同源，样式两制」）：TaskCreate 的
    subject+状态逐字渲染自 engine.progress_rows(state)（driver rich Live
    同一数据源，**含当前节点展开的子步骤维度**——只到 minor_state 会与
    driver 进度区粒度不一致，真机割裂实证）——模型照抄不自行组织，TUI 段
    原生清单与 driver 进度区内容恒等，割裂收敛为纯样式差。
    """
    meta = _meta_root(project_root, name)
    nid = engine.node_id(node.phase, node.sub)
    base = ensure_node_rules(project_root, name, node, cur).read_text(encoding="utf-8")
    phase_label = engine.PHASE_LABELS.get(node.phase, node.phase)
    status_map = {"done": "completed", "current": "in_progress", "todo": "pending"}
    rows = engine.progress_rows(state)  # 全深度：阶段+子阶段+当前节点子步骤
    items = "\n".join(
        f'{"    " * r["depth"]}- "{r["label"]}"（{status_map[r["status"]]}）'
        for r in rows
    )
    section = (
        f"\n## TUI 交互段开场纪律（本段=用户面对面的交互会话，用户就在终端前）\n\n"
        f"1. **开场第一件事**：用 TaskCreate 一条消息批量建齐以下 {len(rows)} 项"
        f"阶段任务清单——subject 与状态**逐字照抄**（与 driver 底部进度区同源的"
        f"权威清单，禁自行改写/增删/换状态）：\n"
        f"{items}\n"
        f"   该清单是用户唯一可见的工作流结构，不建 = 用户眼里你根本没在跑工作流\n"
        f"2. **每轮响应首行**输出 `## PHASE: {phase_label} [{engine.phase_index(node.phase)}/5]`"
        f" 横幅（子步骤 {cur}/{len(node.sub_steps or ())}）\n"
        f"3. 用户先说话的场合（裸开场）：收到首条消息（问题陈述）后先完成 1+2，再"
        f" invoke skill 动手；探查不禁，但保持对用户可见的节奏——材料够问就用"
        f" AskUserQuestion 问，**禁闷头连翻十几轮仓库零提问**（真机实证：20+ 轮"
        f"零提问零清单被用户中断）\n"
        f"4. 完成并落库后，用文本简要汇报并结束本轮——driver 检测到落库会自动收掉"
        f"本会话并续跑下一步，无需 /exit（/exit = 退出整个工作流）\n\n"
        + _bash_shape_rules(project_root)
        + "\n"
    )
    # 插在「## 本节点子步骤清单」之前
    marker = "## 本节点子步骤清单"
    text = base.replace(marker, section + "\n" + marker, 1)
    out = meta / f"tui-rules.{nid}.md"
    if not out.exists() or out.read_text(encoding="utf-8") != text:
        out.write_text(text, encoding="utf-8")
    return out


# ---------- 会话执行（stream-json 实时尾随） ----------

# P1-2 首调 fresh 监控（v4-cost-latency-optimization-design §2）：段首调未缓存
# 输入超阈值告警（宁纵勿枉，只告不拦）——交接包静默膨胀的历史教训（v2.12
# judge 侧、2026-08-12 交接包侧均靠事后审计抓），把斜率钉成可观察信号。
# 阈值校准（2026-08-13，35k→50k）：地板实测 = harness ~22.5k（裸 claude -p）
# + node-rules ~2-3k，交接包本体 ~14k（分节实测）+ step prompt ~2k——正常首调
# 即 40-56k，35k 下告警每段都响 = 告警疲劳（症状 W：全响=没有）。告警对象 =
# 交接包膨胀斜率（47k→73k 类单调涨），不是正常水位。
SEG_FIRST_FRESH_WARN = 50_000

# P2-4 链上下文峰值告警阈值（segment-chain-resume-design §3.4）：链内续轮
# 上下文单调涨，超阈值告警（宁纵勿枉只告不拦）——v2 单会话 485k 零锯齿的
# 平方膨胀边界在 30+ 步，链内 3-5 步峰值估 150-250k，250k 起告。
CHAIN_CONTEXT_WARN = 250_000


def _ctx_size(ev: dict) -> "int | None":
    """assistant 事件的上下文体量代理 = input + cache_read + cache_creation。"""
    u = (ev.get("message") or {}).get("usage")
    if not isinstance(u, dict):
        return None
    vals = [
        u.get(k)
        for k in (
            "input_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
    ]
    vals = [v for v in vals if isinstance(v, int)]
    return sum(vals) if vals else None


def _first_call_fresh(ev: dict) -> "int | None":
    """assistant 事件的本次调用未缓存输入（fresh）；无 usage 返回 None。"""
    u = (ev.get("message") or {}).get("usage")
    if not isinstance(u, dict):
        return None
    v = u.get("input_tokens")
    return v if isinstance(v, int) else None


def _fresh_warn_line(first_fresh: "int | None", note: str) -> "str | None":
    """首调 fresh 超阈值告警行；未超/无数据返回 None（宁纵勿枉）。"""
    if first_fresh is None or first_fresh <= SEG_FIRST_FRESH_WARN:
        return None
    return (
        f"  ⚠ 首调 fresh {first_fresh:,} tok 超阈值 {SEG_FIRST_FRESH_WARN:,}"
        f"（{note}）——交接包疑似膨胀，查 handoff_pack 组成"
    )


def _brief_tool_input(blk: dict) -> str:
    ti = blk.get("input") or {}
    for k in ("command", "file_path", "pattern", "path", "prompt", "description"):
        v = ti.get(k)
        if isinstance(v, str) and v:
            return v.replace("\n", " ")[:100]
    return ""


def run_session(
    prompt: str,
    *,
    cwd: Path,
    settings: Path,
    sys_prompt_file: Path,
    meta: Path,
    debug: bool,
    note: str,
    verbose: bool = False,
    disp: "LiveProgress | None" = None,
    disallow_ask: bool = False,
    resume_sid: "str | None" = None,
) -> tuple[int, str, str]:
    """一次 headless `claude -p` 会话。返回 (rc, assistant 全文, session_id)。

    stream-json 逐行解析：原始流全量落 drive-stream.jsonl（审计/PHASE_DONE 检测
    的数据源）。verbose=False（默认，drive-tasklist-render-design §2.1——用户裁决
    子会话进度不用展示）：assistant text 不上屏（防冲刷常驻进度区），tool_use
    简报喂常驻区「最近动作」行；verbose=True 恢复旧尾随行为（text + ⚙ 行上屏）。
    Ctrl+C（§2.6）：子进程独立进程组（start_new_session）——终端 Ctrl+C 只打
    driver，单击=杀子会话返回 RC_INTERRUPTED（drive 进断点），双击=退出 130。
    disallow_ask=True（交互步 prep 会话）：--disallowedTools AskUserQuestion
    权限层堵入口（interactive-step-headless-prep §4.2 L1——调了必吃 denial，
    配合 _session_called_ask_user L2 嗅探，NEED_USER 标记不作承重墙）。
    resume_sid（P2-4 段链）：续链走 --resume（与 --session-id 互斥），返回
    sid = 链 sid；None = 新会话（现状）。
    """
    sid = resume_sid or str(uuid.uuid4())
    cmd = [
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    if disallow_ask:
        # --disallowedTools 是变长参数（<tools...>）：其后必须跟旗标——
        # 直接跟位置参数 prompt 会被吞成工具名（2026-08-12 实爆：claude 秒退
        # rc=1「Input must be provided」，prep 3 连空转退 12）
        cmd += ["--disallowedTools", "AskUserQuestion"]
    cmd += [
        "--permission-mode",
        "acceptEdits",
        "--settings",
        str(settings),
        "--append-system-prompt-file",
        str(sys_prompt_file),
    ]
    # O1（u1-overall-cost）：段会话禁 MCP——编排全程禁 tavily，schema 是纯税
    cmd += engine.NO_MCP_ARGS
    if resume_sid:
        # P2-4 续链：--resume 与 --session-id 互斥（设计期冒烟：全旗标组合
        # + --resume 跨进程续会话实测通过，记忆保留）
        cmd += ["--resume", resume_sid]
    else:
        cmd += ["--session-id", sid]
    if debug:
        cmd += [
            "--debug",
            "api,hooks",
            "--debug-file",
            str(meta / f"cc_debug.{sid[:8]}.log"),
        ]
    # prompt 走 stdin 不走 argv（2026-08-12 interaction run plan:2#子5 实爆）：
    # 交接包随步数增长 + 中文 1.68 bytes/char 放大，prompt 超 MAX_ARG_STRLEN
    # （131,072 bytes/单参数）→ Popen OSError E2BIG「Argument list too long」，
    # 段结构性卡死。stdin 无此上限（实测 stream-json+verbose+大 prompt 正常）。
    meta.mkdir(parents=True, exist_ok=True)
    texts: list[str] = []
    with (
        open(meta / "drive-stream.jsonl", "a", encoding="utf-8") as log_f,
        open(meta / "cc_sdk.log", "a", encoding="utf-8") as err_f,
    ):
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=err_f,
            text=True,
            bufsize=1,
            # 独立进程组：终端 Ctrl+C 只打 driver——中断/退出语义由 driver
            # 统一裁决（防 child 先收 SIGINT 自杀、driver 读 EOF 当正常收段的竞态）
            start_new_session=True,
        )
        assert proc.stdin is not None
        proc.stdin.write(prompt)
        proc.stdin.close()  # 关闭触发子进程读入（EOF），勿 flush 后留开（挂起）
        interrupted = False
        first_fresh: "int | None" = None
        last_ctx: "int | None" = None
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                log_f.write(line)
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                etype = ev.get("type")
                if etype == "assistant":
                    if first_fresh is None:
                        first_fresh = _first_call_fresh(ev)
                    last_ctx = _ctx_size(ev) or last_ctx
                    for blk in (ev.get("message") or {}).get("content") or []:
                        if not isinstance(blk, dict):
                            continue
                        if blk.get("type") == "text":
                            t = blk.get("text") or ""
                            if t:
                                texts.append(t)
                                if verbose:
                                    print(t)
                        elif blk.get("type") == "tool_use":
                            brief = f"{blk.get('name')} {_brief_tool_input(blk)}"
                            if verbose:
                                print(f"  ⚙ {brief}")
                            elif disp is not None:
                                disp.set_action(brief[:100])
                elif etype == "result":
                    dur = int(ev.get("duration_ms") or 0) // 1000
                    cost = ev.get("total_cost_usd") or 0.0
                    msg = (
                        f"—— 段会话结束（{note}）：{ev.get('subtype')} · "
                        f"{ev.get('num_turns')}轮 · {dur}s · ${cost:.3f}"
                    )
                    if disp is not None:
                        disp.log(msg)
                    else:
                        print(f"\n{msg}")
                    warn = _fresh_warn_line(first_fresh, note)
                    if warn:
                        if disp is not None:
                            disp.log(warn)
                        else:
                            print(warn)
                    cwarn = _chain_warn_line(last_ctx, note)
                    if cwarn:
                        if disp is not None:
                            disp.log(cwarn)
                        else:
                            print(cwarn)
        except KeyboardInterrupt:
            # 单击=中断子任务：杀子会话，段以「中断」收场（drive 进断点裁决；
            # 再按 Ctrl+C = 双击退出，由下方 _pwait_interruptible 处理）
            interrupted = True
            proc.terminate()
            if disp is not None:
                disp.log("  ⛔ 用户中断子会话（单击）——进断点裁决")
        rc = _pwait_interruptible(
            proc, on_first=lambda: None, already_interrupted=interrupted
        )
        if interrupted:
            return RC_INTERRUPTED, "\n".join(texts), sid
    return rc, "\n".join(texts), sid


# ---------- 交互步 prep 的机械保证（interactive-step-headless-prep §4.2/§4.4） ----------


def _session_called_ask_user(meta: Path, sid: str) -> bool:
    """L2 嗅探：本会话 stream 里出现过 AskUserQuestion tool_use（无论成败——
    L1 denial 回执同样是 tool_use 形态）。命中 = 「需要用户」的机械信号，
    不依赖模型记得输出 NEED_USER 标记。"""
    try:
        with open(meta / "drive-stream.jsonl", encoding="utf-8") as f:
            for line in f:
                if sid not in line or '"AskUserQuestion"' not in line:
                    continue  # 字符串预筛：26MB 级文件逐行 json.loads 太贵
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("session_id") != sid:
                    continue
                for blk in (ev.get("message") or {}).get("content") or []:
                    if (
                        isinstance(blk, dict)
                        and blk.get("type") == "tool_use"
                        and blk.get("name") == "AskUserQuestion"
                    ):
                        return True
    except OSError:
        pass
    return False


# NEED_USER 标记后的 ```json 围栏块（非贪婪到第一个闭围栏；嵌套花括号安全——
# 以围栏为界不以花括号配对为界）。
_NEED_USER_JSON_RE = re.compile(r"###\s*NEED_USER.*?```json\s*(\{.*?)```", re.DOTALL)
# NEXT_PREP（P2-1 读回 prep 并入前序工作段，v4-cost-latency-optimization-design §2）：
# 与 NEED_USER 严格分通道——工作段尾部的 NEXT_PREP =「为下一步备的问题」，
# 若复用 NEED_USER 会被动态交互 fallback（本步需要用户）误吞。
_NEXT_PREP_JSON_RE = re.compile(r"###\s*NEXT_PREP.*?```json\s*(\{.*?)```", re.DOTALL)


def _stash_need_user_payload(
    meta: Path, out: str, pattern: "re.Pattern" = _NEED_USER_JSON_RE
) -> bool:
    """从会话输出提取问题载荷落 need_user.json（§4.4 文件通道）。

    非法/缺失载荷 → 删除陈旧文件（防上一轮载荷被当下轮的用）并返回 False，
    TUI 侧退回自组织提问（宁纵勿枉）。pattern 参数 = NEXT_PREP/NEED_USER 双通道。
    """
    target = meta / "need_user.json"
    data: object = None
    m = pattern.search(out)
    if m:
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            data = None
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("questions"), list)
        or not data["questions"]
    ):
        target.unlink(missing_ok=True)
        return False
    payload: dict = {"questions": data["questions"]}
    # u2-sub1-cost 修B：sources 出处包透传（prep 逐字收录的前序用户原话——
    # 前台落 trace 直接引用，免重读 evidence 全量）；缺失不拒（宁纵勿枉，
    # 前台退回现状自重读，_warn_sources_missing 落可观察信号）。
    if isinstance(data.get("sources"), list) and data["sources"]:
        payload["sources"] = data["sources"]
    payload["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return True


def _warn_sources_missing(meta: Path, disp) -> None:
    """u2-sub1-cost 修B 观察性：载荷缺 sources 出处包 → 告警不阻断
    （前台退回自重读 evidence 全量 = 现状，宁纵勿枉）。"""
    try:
        data = json.loads((meta / "need_user.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(data, dict) and not data.get("sources"):
        disp.log(
            "  ⚠ 问题载荷缺 sources 出处包——前台将自重读 evidence"
            "（prep 应逐字收录前序用户原话进 sources 字段）"
        )


def _consume_next_prep(project_root: Path, name: str, key: str) -> bool:
    """P2-1 标记消费：前序工作段已为本交互步备好问题清单（need_user.json）。

    精确匹配 f"<node>#<cur>" 才生效——state-reset 回退后陈旧标记永不误配
    （不匹配 = 走原独立 prep 段，宁纵勿枉）。命中即 pop（一次性）。
    """
    st = _load(project_root, name)
    if st.get("next_prep_stashed") != key:
        return False
    st.pop("next_prep_stashed", None)
    engine.save_state(project_root, name, st)
    return True


def _mark_next_prep(project_root: Path, name: str, key: str) -> None:
    st = _load(project_root, name)
    st["next_prep_stashed"] = key
    engine.save_state(project_root, name, st)


# ---------- 常驻进度区（drive-tasklist-render-design §2.1） ----------


def _fmt_elapsed(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}m{s % 60:02d}s"


class LiveProgress:
    """driver stdout 底部常驻进度区：rich Live 原地重绘（spinner/耗时/✓ 实时翻转）。

    数据 100% 机械读 engine.progress_rows(state)——✓ 翻转瞬间 = gate 落盘瞬间，
    不靠模型 TaskUpdate。无 rich 环境降级为「状态变化时重印一次」（明示降级，
    非常驻）。TUI 段/stdin 断点期间 stop() 让位终端，结束后 start() 恢复。
    """

    def __init__(self, project_root: Path, name: str, *, verbose: bool = False):
        self.project_root = project_root
        self.name = name
        self.verbose = verbose
        self.state: dict | None = None
        self.activity = ""  # 当前段描述（空=无段在跑，不转 spinner）
        self.action = ""  # 最近动作一行（子会话最后工具调用简报）
        self._started = time.monotonic()
        # Live 直接吃 self（__rich_console__ 渲染当前字段）——refresh 重渲同一
        # renderable，字段突变即上屏；传 bound method 会 NotRenderableError（冒烟实证）。
        self._live = (
            Live(
                self,
                refresh_per_second=4,
                transient=False,
            )
            if _HAS_RICH
            else None
        )
        self._last_printed: str | None = None  # 降级模式：状态签名去重

    # ---- 生命周期 ----
    def start(self) -> None:
        if self._live is not None:
            self._live.start()

    def stop(self) -> None:
        if self._live is not None:
            self._live.stop()

    # ---- 数据更新 ----
    def set_state(self, state: dict) -> None:
        self.state = state
        if self._live is None:
            self._degraded_reprint()

    def begin(self, activity: str) -> None:
        """新段落开始：重置计时与最近动作。"""
        self.activity = activity
        self.action = ""
        self._started = time.monotonic()
        if self._live is None:
            self._degraded_reprint(force=True)

    def set_action(self, action: str) -> None:
        self.action = action

    def log(self, msg: str) -> None:
        """事件上屏：live 模式打在常驻区上方；降级=直接 print。"""
        if self._live is not None:
            self._live.console.print(msg)
        else:
            print(msg)

    # ---- 渲染 ----
    def _rows_with_focus(self) -> tuple[list[dict], int]:
        """progress_rows + 焦点行（活动/耗时/spinner 只挂最深 current 行——
        首次冒烟实证挂全部 current 行 = 阶段/子阶段/子步骤三连刷屏）。"""
        rows = engine.progress_rows(self.state)
        focus = max(
            (i for i, r in enumerate(rows) if r["status"] == "current"), default=-1
        )
        return rows, focus

    def _snapshot_lines(self) -> list[str]:
        """纯文本快照（降级模式与测试共用）。"""
        if self.state is None:
            return []
        out = [f"══ 进度 ══ {self.name}"]
        rows, focus = self._rows_with_focus()
        for i, r in enumerate(rows):
            mark = {"done": "✓", "current": "▸", "todo": "·"}[r["status"]]
            line = f"{'    ' * r['depth']}{mark} {r['label']}"
            if r["extra"]:
                line += f" ({r['extra']})"
            if i == focus and self.activity:
                line += f" — {self.activity} ({_fmt_elapsed(time.monotonic() - self._started)})"
                if self.action:
                    line += f" · {self.action}"
            out.append(line)
        return out

    def __rich_console__(self, console, options):  # rich 协议：Live 每帧重渲
        yield self._render()

    def _render(self):  # rich 模式 renderable 工厂（读当前字段，帧间突变即上屏）
        from rich.console import Group

        if self.state is None:
            return Text(f"══ 进度 ══ {self.name}（读 state 中…）")
        now = time.monotonic()
        parts: list[Text] = [Text(f"══ 进度 ══ {self.name}", style="bold")]
        spin = Spinner("dots").render(now) if self.activity else None
        rows, focus = self._rows_with_focus()
        for i, r in enumerate(rows):
            mark, style = {
                "done": ("✓", "green"),
                "current": ("▸", "cyan"),
                "todo": ("·", "dim"),
            }[r["status"]]
            line = Text(f"{'    ' * r['depth']}{mark} {r['label']}", style=style)
            if r["extra"]:
                line.append(f" ({r['extra']})", style="dim")
            if i == focus and self.activity:
                line.append(" ")
                line.append_text(spin)
                line.append(f" {self.activity} ({_fmt_elapsed(now - self._started)})")
                if self.action:
                    line.append(f" · {self.action}", style="dim")
            parts.append(line)
        return Group(*parts)

    def _degraded_reprint(self, *, force: bool = False) -> None:
        lines = self._snapshot_lines()
        sig = "\n".join(lines)
        if force or sig != self._last_printed:
            print(sig)
            self._last_printed = sig


# ---------- prompt 装配 ----------


# 问题载荷契约（prep 段与 NEXT_PREP 顺带交付共用同一形状——内容同源纪律）
# u2-sub1-cost 修B：+sources 出处包——prep 方逐字收录「问答后落 trace 要引用的
# 前序用户原话/会话事实」，前台零重读 evidence 全量。
_QUESTIONS_CONTRACT = (
    '{"questions": [{"question": "...", "header": "≤12字标签", '
    '"multiSelect": false, "options": [{"label": "...", "description": "..."}]}], '
    '"sources": ["出处材料逐字收录：前序用户原话/会话事实（含其出处类目）——'
    '前台落 trace 直接引用，禁编造、禁概括替换原话"]}'
)


def build_step_prompt(
    project_root: Path,
    name: str,
    state: dict,
    node: "engine.Node",
    cur: int,
    step: "engine.Step",
    *,
    rework: str | None,
    interactive: bool = False,
    prep: bool = False,
    needuser: bool = False,
    prep_next: "engine.Step | None" = None,
    prep_next_key: "str | None" = None,
) -> str:
    """子步骤会话 prompt = 交接包 + 当前步目的 + append-trace 指引 + 铁律（+返工判词）。

    复用 _stop_continue 的指令骨架（workflow_advance.py），差异：
    禁完成标记（外部编排）+ 只做本步（会话粒度=子步骤）。
    interactive=True（TUI 段）：交接包由 SessionStart hook 注入（全量 settings），
    prompt 不带防双份；交互指引替换 NEED_USER 出口。
    prep=True（交互步后台预处理，interactive-step-headless-prep §4.3）：
    交付从 append-trace 换成「备问题清单 + ### NEED_USER + ```json 载荷」，
    禁 AskUserQuestion/禁落 trace（本步 trace 归前台问答段）。
    """
    total = len(node.sub_steps or ())
    if step.kind == "skill":
        how = f"先用 Skill 工具 invoke `{step.ref}`，再按其引导执行"
    else:
        how = f"用工具 {step.ref} 执行"
    phase_label = engine.PHASE_LABELS.get(node.phase, node.phase)
    parts: list[str] = []
    if not interactive:
        pack = engine.handoff_pack(project_root, name)
        if pack:
            parts += [pack, ""]
    if interactive:
        # 开场纪律（TaskList/PHASE 横幅/裸开场顺序）单源 = ensure_tui_rules
        # （system prompt 通道，裸开场抽不走）——prompt 尾只留交互指引，防双份打架
        tail = (
            "- 开场纪律见 system prompt「TUI 交互段开场纪律」段（TaskList+横幅——"
            "不建清单=用户眼里你没在跑工作流）\n"
            "- 需要用户输入时用 AskUserQuestion（回合内完成），用户就在终端前\n"
            "- 完成并落库后，用文本简要汇报并结束本轮——driver 检测到落库会自动"
            "收掉本会话并续跑下一步，无需 /exit（/exit = 退出整个工作流）"
        )
        if node.phase == "understand" and node.sub == 1 and cur == 1:
            # 开场问题陈述对话式采集（drive-tasklist-render-design §2.4 修订——
            # 用户裁决：采集归 TUI 会话原生对话，driver input() 已撤）。
            # 仅 prompt 驱动的返工路径会走到（裸开场=用户先说话，本条款不适用）。
            tail += (
                "\n- 开场第二件事（建完清单立即做）：对话式问用户「本次要分析的问题"
                "是什么」——用户打字自由陈述 = 本步结论的首要「用户原话」出处；"
                "**拿到用户陈述前禁任何仓库探查/工具调用**（首次 dogfood 实证："
                "先自行探查 20+ 轮零提问被用户中断——先问，才问得出好问题）"
            )
        if needuser:
            _nu = project_root / ".claude" / "workflows" / name / "need_user.json"
            if _nu.exists():
                # prep 载荷指针（interactive-step-headless-prep §4.4 前者裁决：
                # 问题清单逐字照抄，TUI 零组织过程）
                # u2-sub1-cost 修B：sources 出处包直接引用，免重读 evidence 全量
                tail += (
                    f"\n- 本步问题清单已由后台预处理备好：Read `{_nu}`——"
                    "用 AskUserQuestion **逐字照抄**提问"
                    "（禁改写/增删/换序——内容同源纪律）；"
                    "载荷 sources 字段 = 本步落 trace 的出处材料"
                    "（前序用户原话逐字）——直接引用，已覆盖处禁再 Read "
                    "evidence 全量翻找（未覆盖才按指针补）"
                )
    else:
        tail = (
            "- 非预期需要用户输入时：输出 `### NEED_USER` + 问题清单后结束"
            "（driver 会接管为交互会话），禁编造用户答复"
        )
    if prep:
        if step.kind == "skill":
            how_prep = (
                f"0. 先用 Skill 工具 invoke `{step.ref}` 取问题设计指引"
                "（只准备，不执行问答）\n"
            )
        elif step.ref == "AskUserQuestion":
            how_prep = ""  # 问答工具本身在 prep 环境不可用，不指引
        else:
            how_prep = f"0. 可用工具 {step.ref} 查取证材料（只准备，不执行问答）\n"
        deliverable = (
            "任务性质：本步是**交互步的后台预处理**——问答本身由前台会话执行"
            "（用户只在终端前回答问题），你的唯一交付 = 备好问题清单：\n"
            f"{how_prep}"
            "1. 按本步目的准备要向用户提的问题（问题/选项设计纪律 = 上方目的条款）\n"
            "2. 把问答后落 trace 要引用的出处材料（你上下文中已有的前序用户原话/"
            "会话事实）逐字收录进载荷 sources 字段（禁编造、禁概括替换原话）\n"
            "3. 输出 `### NEED_USER`，紧跟一个 ```json 代码块（问题载荷契约）：\n"
            f"   {_QUESTIONS_CONTRACT}\n"
            "4. 输出完即结束本轮"
        )
        rules_block = (
            "铁律：\n"
            "- 只做这一个子步骤的预处理——问答由前台会话执行，与你无关\n"
            "- 禁调 AskUserQuestion（本环境无此工具，调了也不会有人答）\n"
            "- 禁编造用户答复；禁落 evidence trace（本步 trace 归前台问答段落）\n"
            "- 禁输出 ### STEP_DONE / ### PHASE_DONE 标记（外部编排，标记无效）\n"
            f"{_bash_shape_rules(project_root)}\n"
            "- 备齐问题清单后输出 `### NEED_USER` + 上述 json 载荷并结束"
        )
    else:
        deliverable = (
            f"{how}；完成后落 evidence（本步的硬性交付，门控只认它）：\n"
            f"1. Bash `python3 ~/.dl-workflow/dl_flow_engine.py append-trace --scaffold`"
            f" 生成载荷骨架（打印路径）\n"
            f"2. Read 骨架文件，Edit 把每个「待填」换成实际内容\n"
            f"3. Bash `python3 ~/.dl-workflow/dl_flow_engine.py append-trace "
            f"--from-file <骨架路径>` 落库"
        )
        rules_block = (
            "铁律：\n"
            "- 只做这一个子步骤——后续步骤由 driver 另行派发，与你无关\n"
            "- 禁输出 ### STEP_DONE / ### PHASE_DONE 标记（外部编排，标记无效）\n"
            f"{_bash_shape_rules(project_root)}\n"
            # u2-sub2-cost：pack_self_contained 步材料全在交接包内——灭弱模型
            # 保险性 evidence 全量重读（u:2#2 基线 +19.6k fresh/+43s 零增量）。
            + (
                "- 材料边界：本步所需材料已全部在上方交接包内（本节点前序留痕"
                "全文 + 前序节点结论摘要）——直接引用，禁 Read evidence 全量翻找；"
                "确有缺口才按指针定点补（宁纵勿枉）\n"
                if step.pack_self_contained
                else ""
            )
            + f"{tail}\n"
            + engine.selfcheck_hint(step)
        )
    parts.append(
        f"## WORKFLOW 当前任务（外部 driver 编排）\n"
        f"工作流 {name} · {phase_label} [{state['index']}/5] · "
        f"子阶段「{node.label}」· 子步骤 {cur}/{total}（{step.kind}: {step.ref}）\n\n"
        f"目的：{step.purpose}\n\n"
        f"{deliverable}\n\n"
        f"{rules_block}\n"
    )
    if prep_next is not None:
        # P2-1 读回 prep 并入前序工作段：本段顺带备下一交互步的问题清单——
        # 模型刚产出本步内容（在context里），转问题零重读；独立 prep 段全省。
        # u2-sub1-cost 修A：可跨节点（confirm 读回步横在中间不挡路），指名
        # 目标步 id 防模型误解为同节点下一步。
        _target = prep_next_key or "下一步"
        parts.append(
            f"\n## 附带交付：为下一交互步（{_target}）备问题清单（P2-1 合并段）\n"
            f"目标步目的：{prep_next.purpose}\n"
            "1. 先完成本步 append-trace 落库（硬性交付不变）\n"
            "2. 再按目标步目的设计要向用户提的问题（问题/选项设计纪律 = 上方目的条款）\n"
            "3. 把问答后落 trace 要引用的出处材料（你上下文中已有的前序用户原话/"
            "会话事实）逐字收录进载荷 sources 字段（禁编造、禁概括替换原话）\n"
            "4. 输出 `### NEXT_PREP`，紧跟一个 ```json 代码块（问题载荷契约）：\n"
            f"   {_QUESTIONS_CONTRACT}\n"
            "5. 输出完即结束本轮——问答由前台会话执行，与你无关；\n"
            "   `### NEXT_PREP` 是备料标记，与 `### NEED_USER`（本步需要用户）严格不同，禁混用"
        )
    if rework:
        parts.append(f"\n## 返工上下文\n{rework}")
    return "\n".join(parts)


def _build_tui_cmd(
    sid: str,
    settings: Path,
    rules: Path,
    prompt: "str | None",
    debug: bool,
    meta: Path,
) -> list[str]:
    """TUI 段命令行。prompt=None = 裸开场（无位置参数，会话开了安静等用户打字）。"""
    cmd = [
        "claude",
        "--session-id",
        sid,
        "--settings",
        str(settings),
        "--append-system-prompt-file",
        str(rules),
        "--permission-mode",
        "acceptEdits",
    ]
    # O1（u1-overall-cost）：TUI 交互段同一 MCP 税同一封法
    # （位置参数 prompt 必须仍在末尾——见下方 append 顺序）
    cmd += engine.NO_MCP_ARGS
    if debug:
        cmd += [
            "--debug",
            "api,hooks",
            "--debug-file",
            str(meta / f"cc_debug.{sid[:8]}.log"),
        ]
    if prompt is not None:
        cmd.append(prompt)
    return cmd


def _is_bare_open(
    node: "engine.Node",
    cur: int,
    pending_rework: "str | None",
    has_statement: bool = False,
) -> bool:
    """裸开场判定（drive-tasklist-render-design §2.4 修订2，用户裁决）：v2.0 原位
    开场——只限 understand:1#1（全工作流开场步）且无返工上下文时，TUI 不喂任务书
    prompt，会话开了安静等用户打字；用户陈述提交瞬间 node-rules（系统提示词含子1
    目的）+ phase 注入（任务清单目标状态）+ output-style 自然就位。裸开场万一未
    落 trace，none 重试自动换回完整任务书 prompt（主路裸开场、任务书返工兜底）。
    其余交互步（读回/裁决需模型先呈现材料）保持任务书驱动。
    §8 收窄（2026-08-12 用户裁决）：has_statement=True（陈述已被 phase hook
    机械捕获）即非裸开场——step1 与其余交互步同路径走 prep 后台化。
    """
    return (
        pending_rework is None
        and not has_statement
        and node.phase == "understand"
        and node.sub == 1
        and cur == 1
    )


def _tui_segment_file(meta: Path) -> Path:
    """TUI 段标记（tui-auto-continue-design §2）：driver 起 TUI 后写、收段后删——
    Stop hook 据此做「本段内落了新 trace」机械判定（程序通道，区分自动完成 vs
    手动退出）。只在 TUI 段存活期存在：headless 段/普通会话无此文件 = hook 不动作。"""
    return meta / "tui_segment.json"


def _tui_autodone_file(meta: Path) -> Path:
    """自动收段标记：Stop hook 发现新 trace 落库后写（并 SIGTERM 收 TUI）；
    driver 收段后消费（消费即删）。有此标记 = 走共享门控自动续跑，无需 /exit。"""
    return meta / "tui_autodone.json"


def _consume_tui_autodone(meta: Path) -> "dict | None":
    """消费自动收段标记（消费即删，防陈旧标记污染下一段）。无标记 -> None。"""
    f = _tui_autodone_file(meta)
    try:
        payload = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    f.unlink(missing_ok=True)
    return payload if isinstance(payload, dict) else {}


def run_tui_step(
    project_root: Path,
    name: str,
    state: dict,
    node: "engine.Node",
    cur: int,
    step: "engine.Step",
    meta: Path,
    debug: bool,
    wt: Path,
    *,
    rework: str | None,
    disp: "LiveProgress | None" = None,
    bare: bool = False,
    needuser: bool = False,
) -> tuple[int, str]:
    """交互子步骤 TUI 段：起原生 claude TUI（全量 per-wf settings——SessionStart
    注入交接包 / phase 注入 / output-style 横幅齐备），用户交互 + /exit 回收。

    返回 (rc, session_id)。drive_mode 下 advance hook 不推进（state 由 driver
    在回收后统一门控）；fence 仅 S11/S14 硬约束生效。
    bare=True（裸开场）：不喂任务书 prompt——会话安静等用户打字（v2.0 开场）。
    needuser=True（prep 后接管）：prompt 带 need_user.json 逐字照抄指针。
    """
    sid = str(uuid.uuid4())
    settings = ensure_tui_settings(project_root, name)  # 全量模板+hook 路径同仓化
    rules = ensure_tui_rules(
        project_root, name, node, cur, state
    )  # node-rules+TUI 开场纪律
    prompt = None
    if not bare:
        prompt = build_step_prompt(
            project_root,
            name,
            state,
            node,
            cur,
            step,
            rework=rework,
            interactive=True,
            needuser=needuser,
        )
    cmd = _build_tui_cmd(sid, settings, rules, prompt, debug, meta)
    if bare:
        print(
            f"\n▸ 交互子步骤 {cur}/{len(node.sub_steps or ())} —— TUI 会话已就绪："
            f"请直接输入你要分析的问题（模型在你提交后接管；落库后 driver 自动收段"
            f"续跑，无需 /exit；/exit = 退出整个工作流，续跑 = `dl {name}`）"
        )
    else:
        print(
            f"\n▸ 交互子步骤 {cur}/{len(node.sub_steps or ())} —— 起 TUI 会话"
            f"（回答模型提问；模型落库后 driver 自动收段续跑，无需 /exit；"
            f"/exit = 退出整个工作流，续跑 = `dl {name}`）"
        )
    print(
        "  （段内底部进度 = 会话内原生 TaskList，与上方进度区同源：含当前节点子步骤）"
    )
    if disp is not None:
        disp.stop()  # 终端交还 TUI 会话
    # 段标记（tui-auto-continue-design §2）：记本段启动前的最新 trace hash——
    # Stop hook 以 hash 变化机械判定「本段内落了新 trace」→ 自动收段续跑。
    # 清旧 autodone：防上一段的标记污染本段分流。
    pre_sha = engine.latest_trace_sha1(project_root, name, cur, node.minor_key)
    _tui_autodone_file(meta).unlink(missing_ok=True)
    try:
        with open(meta / "cc_sdk.log", "a", encoding="utf-8") as err_f:
            # TUI 处于 raw 模式时 Ctrl+C 只是输入字节，driver 收不到 SIGINT
            # （tui-exit-quits-driver-design §2 实证）——本计数仅兜底 cooked 窗口：
            # 双击=杀子会话退 130，与「TUI 退 = 全退」语义一致
            proc = subprocess.Popen(cmd, cwd=str(wt), stderr=err_f)
            _tui_segment_file(meta).write_text(
                json.dumps(
                    {
                        "pid": proc.pid,
                        "node": engine.node_id(node.phase, node.sub),
                        "sub_step": cur,
                        "minor_key": node.minor_key,
                        "pre_sha": pre_sha,
                        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    }
                ),
                encoding="utf-8",
            )
            try:
                rc = _pwait_interruptible(
                    proc,
                    on_first=lambda: print(
                        "\n（单击 Ctrl+C：TUI 已中断当前生成；快速再按一次 = 退出会话与 driver）"
                    ),
                )
            finally:
                _tui_segment_file(meta).unlink(missing_ok=True)  # 段已收，标记即失效
    finally:
        if disp is not None:
            disp.start()
    print(f"—— TUI 段会话结束（{engine.node_id(node.phase, node.sub)}#{cur}，rc={rc}）")
    return rc, sid


def _rework_text(reason: str) -> str:
    """门控 block 判词 → 返工上下文（注入下一轮会话 prompt / 落 state 持久化）。"""
    return (
        f"上一轮门控未通过（判词原文）：\n{reason}\n\n"
        f"按判词修正后重做本子步骤——修正方式 = append-trace 追加新 trace"
        f"（禁覆盖/编辑旧行，judge 以最后一条为准）。"
    )


def _after_tui_exit(project_root: Path, name: str, wt: Path, cur: int, disp) -> int:
    """TUI 退 = 全退（tui-exit-quits-driver-design，2026-08-09 用户裁决）。

    TUI 段一结束（任何方式——双击 Ctrl+C 与 /exit 在 claude 内部是同一路径，
    实测 rc=0 + SessionEnd prompt_input_exit 双通道撞车，driver 不可区分），
    先判本步门控（主循环入口无「先判未判决 trace」逻辑，不判则已落库 trace
    永不判决、续跑被当没干过重开），再按结果给续跑指引并退出 driver。
    """
    action, reason, _ns = engine.gate_sub_step_at_stop(project_root, name, str(wt))
    if action == "advanced":
        disp.log(f"  ✓ 子步骤 {cur} 通过门控")
        disp.log(
            f"▸ TUI 段结束，子步骤 {cur} 已过门控——driver 退出。"
            f"续跑：`dl {name}`（接着下一步往下走）。"
        )
        return 0
    if action == "block":
        disp.log(f"  ✗ 门控 block：{reason[:200]}")
        state = _load(project_root, name)
        state["pending_rework"] = _rework_text(reason)  # 续跑时恢复，消费即清
        engine.save_state(project_root, name, state)
        disp.log(
            f"▸ TUI 段结束，子步骤 {cur} 门控未通过（判词已落 evidence，"
            f"返工上下文已存 state）——driver 退出。续跑：`dl {name}`（带判词返工本步）。"
        )
        return 0
    if action == "escalate":
        disp.log(
            f"▸ TUI 段结束，子步骤 {cur} 连续 block 达阈值（判词：{reason[:200]}）"
            f"——driver 退出。续跑：`dl {name}` 重开本步；强制通过 = `/dl step-pass`。"
        )
        return 0
    # none：会话结束但门控读不到新 trace（未落库 / 中途退出）
    disp.log(
        f"▸ TUI 段结束，子步骤 {cur} 未见落库——driver 退出。"
        f"续跑：`dl {name}`（重开本步 TUI）。"
    )
    return 0


def _handle_tui_segment_end(
    project_root: Path, name: str, wt: Path, cur: int, meta: Path, disp
) -> "int | None":
    """TUI 段结束分流（tui-auto-continue-design §3，2026-08-09 用户裁决）。

    有 autodone 标记（Stop hook 机械判定本段落库 = 活已干完）→ 返回 None：
    主循环落共享门控——advanced 直接续跑下一步 / block 带判词自动重开 /
    escalate 断点，driver 不退出，/exit 依赖消失。
    无标记（手动 /exit / 双击 Ctrl+C）→ TUI 退 = 全退（裁决不变），返回退出码。
    """
    if _consume_tui_autodone(meta) is not None:
        disp.log("  ⚑ 模型已落库——driver 自动收段，判门控后续跑（无需 /exit）")
        return None
    return _after_tui_exit(project_root, name, wt, cur, disp)


def build_phase_prompt(project_root: Path, name: str, state: dict) -> str:
    """无编排阶段（execute/review/evolution）整阶段会话 prompt。"""
    phase = state["phase"]
    phase_label = engine.PHASE_LABELS.get(phase, phase)
    parts: list[str] = []
    pack = engine.handoff_pack(project_root, name)
    if pack:
        parts += [pack, ""]
    parts.append(
        f"## WORKFLOW 当前任务（外部 driver 编排）\n"
        f"工作流 {name} · {phase_label} [{state['index']}/5]"
        f"（本阶段无子步骤编排——整阶段一个会话）\n\n"
        f"按 system prompt（phase-rules 全量）的「{phase_label}」阶段规则完成本阶段"
        f"全部工作（产物规范位置：主仓 .claude/ 对应目录/<name>.md）。\n"
        f"全部完成后输出 `### PHASE_DONE: {phase}` 结束。\n\n"
        f"非预期需要用户输入时：输出 `### NEED_USER` + 问题清单后结束"
        f"（driver 会接管），禁编造用户答复。"
    )
    return "\n".join(parts)


# ---------- 断点（门栏/闸门/升级/异常） ----------


def _dl_cmd(args: list[str], wt: Path) -> None:
    """转发 dl-cmd.sh（/dl 语义真源）；输出直接上屏。"""
    subprocess.run(["bash", str(DL_CMD), *args], cwd=str(wt), check=False)


def breakpoint_loop(
    project_root: Path,
    name: str,
    wt: Path,
    header: str,
    disp: "LiveProgress | None" = None,
) -> str:
    """前台断点：打印 header，stdin 收命令。返回 "changed"（状态可能变了，重读续跑）
    或 "quit"（退出 driver）。gate/next/back/jump/state-reset/step-pass 后返回 changed；
    status/fence/dispute 留在断点内。常驻进度区在断点期间让位终端（stop/start）。
    """
    if disp is not None:
        disp.stop()
    try:
        return _breakpoint_body(project_root, name, wt, header)
    finally:
        if disp is not None:
            disp.start()


def _breakpoint_body(project_root: Path, name: str, wt: Path, header: str) -> str:
    print(f"\n{'─' * 60}\n{header}")
    print(
        "命令: gate | status | next | back | jump <phase> | step-pass | "
        "state-reset <目标> | fence on|off | dispute <论证> | q(退出)"
    )
    while True:
        try:
            line = input("driver> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n退出 driver（state 在磁盘，`dl <name>` 随时续）。")
            return "quit"
        if not line:
            continue
        cmd, *rest = line.split()
        if cmd in ("q", "quit", "exit"):
            print("退出 driver（state 在磁盘，`dl <name>` 随时续）。")
            return "quit"
        if cmd in (
            "gate",
            "status",
            "next",
            "back",
            "jump",
            "step-pass",
            "state-reset",
            "fence",
            "dispute",
        ):
            _dl_cmd([cmd, *rest], wt)
            if cmd in ("gate", "next", "back", "jump", "state-reset", "step-pass"):
                return "changed"
        else:
            print(
                f"未知命令 '{cmd}'（gate/status/next/back/jump/step-pass/state-reset/fence/dispute/q）"
            )


# ---------- --segment 段模式基础设施（front-tui-hybrid-design §2.2） ----------

# 段退出码：段结局分类，前台会话据此前进（0/1 沿用惯例，10+ 为段语义）。
SEG_DONE = 0  # 工作流全部 5 阶段完成
SEG_ERROR = 1  # 段内异常（API 挂等）——重跑同一命令即续
SEG_INTERACTIVE = 10  # 撞裸开场（u:1#1 无返工，57a64e1 裁决保 TUI）——回前台对话
SEG_GATE = 11  # 门栏 held_for_gate / 阶段闸门——等用户 /dl gate 裁决
SEG_BREAKPOINT = 12  # escalate / none 重试上限 / 中断 / state 越界——等用户处置
SEG_NEED_USER = 13  # headless 会话 ### NEED_USER——动态重分类为交互回前台


class _SegmentExit(Exception):
    """段边界信号：撞「需要人或需要前台」即抛出收场（--segment 无 stdin 断点）。"""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class _PrintDisp:
    """--segment 无终端：LiveProgress 的 print 替身（段输出走后台任务日志）。"""

    def set_state(self, state) -> None:
        pass

    def begin(self, activity: str) -> None:
        pass

    def set_action(self, action: str) -> None:
        pass

    def log(self, msg: str) -> None:
        print(msg)


# ---------- 主循环 ----------


def drive(project_root: Path, name: str, debug: bool, verbose: bool = False) -> int:
    """全程 driver（v3 默认入口）：断点 = 前台 stdin，交互步 = 原地 TUI 段。"""
    meta = _meta_root(project_root, name)
    settings = ensure_drive_settings(project_root, name)
    engine.set_drive_mode(project_root, name, True)
    state = _load(project_root, name)
    wt = Path(state["worktree_path"])
    print(f"▸ driver 接管工作流 '{name}'（headless 编排，state 磁盘真源）")
    print(f"  worktree: {wt}  日志: {meta}/drive-stream.jsonl")

    disp = LiveProgress(project_root, name, verbose=verbose)
    disp.start()

    def _breakpoint(header: str, _code: int) -> str:
        return breakpoint_loop(project_root, name, wt, header, disp=disp)

    def _interactive(st, node, cur, step, rework):
        rc, sid = run_tui_step(
            project_root,
            name,
            st,
            node,
            cur,
            step,
            meta,
            debug,
            wt,
            rework=rework,
            disp=disp,
            bare=_is_bare_open(
                node, cur, rework, has_statement=bool(st.get("problem_statement"))
            ),
        )
        return rc, sid, "tui-step"

    def _need_user(st, node, cur, step, rework):
        disp.log("  ⚑ 模型请求用户输入（NEED_USER）——接管为 TUI 段")
        rc, sid = run_tui_step(
            project_root,
            name,
            st,
            node,
            cur,
            step,
            meta,
            debug,
            wt,
            rework=rework,
            disp=disp,
            needuser=True,
        )
        return rc, sid, "tui-step-needuser"

    try:
        return _run_boundary_loop(
            project_root,
            name,
            wt,
            meta,
            settings,
            debug,
            verbose,
            disp,
            on_breakpoint=_breakpoint,
            on_interactive=_interactive,
            on_need_user=_need_user,
        )
    finally:
        disp.stop()


def _run_boundary_loop(
    project_root: Path,
    name: str,
    wt: Path,
    meta: Path,
    settings: Path,
    debug: bool,
    verbose: bool,
    disp,
    *,
    on_breakpoint,  # (header, seg_code) -> "changed"|"quit"；--segment 实现抛 _SegmentExit
    on_interactive,  # (state, node, cur, step, rework) -> (rc, sid, seg_kind)
    on_need_user,  # 签名同上；--segment 下两回调均抛 _SegmentExit（无 stdin 可等）
) -> int:
    """主循环单源（drive 全程模式与 --segment 段模式共用，front-tui-hybrid-design §2.2）。

    返回 0 = 完成 / 断点 quit（drive 语义）；130 = 双击中断。--segment 的边界全部
    经 _SegmentExit 抛出，不由本函数返回。
    """
    pending_rework: str | None = _load(project_root, name).get(
        "pending_rework"
    )  # TUI block 退出时落盘的返工上下文（消费即清）；block/none 后下次会话的返工上下文
    none_retries = 0
    phase_done_at: tuple[str, int] | None = None  # 已见 PHASE_DONE 的节点（防重跑会话）

    try:
        while True:
            state = _load(project_root, name)
            disp.set_state(state)
            if state.get("gate") == "done":
                disp.log(f"\n╔═ WORKFLOW · {name} · 已完成全部 5 阶段（进化终结）")
                return 0
            node = engine.get_node(state["phase"], state["sub_index"])
            cur_phase = state["phase"]

            # ---- 门栏断点（held_for_gate，唯一出口 release_subgate）----
            if state.get("held_for_gate"):
                if (
                    on_breakpoint(
                        f"⛔ 子阶段门栏：「{node.label}」全部子步骤已通过门控，"
                        f"进下一子阶段需用户裁决（gate 放行 / state-reset 重测）。",
                        SEG_GATE,
                    )
                    == "quit"
                ):
                    return 0
                continue

            if node.sub_steps:
                # ---- PHASE_DONE 通道（advance="phase" 编排末节点门栏放行后）----
                if engine.phase_done_channel_open(project_root, name, state, node):
                    if (
                        engine.is_gated_after(cur_phase)
                        and state.get("gate") != "passed"
                    ):
                        if (
                            on_breakpoint(
                                f"⛔ 阶段闸门：{engine.PHASE_LABELS.get(cur_phase, cur_phase)}"
                                f" 已完成（产物已装配），进下一阶段需 gate 放行。",
                                SEG_GATE,
                            )
                            == "quit"
                        ):
                            return 0
                        continue
                    new_state = engine.advance_state(project_root, name, via="driver")
                    disp.log(
                        f"\n╔═ 阶段切换：{engine.PHASE_LABELS.get(cur_phase, cur_phase)} ──► "
                        f"{engine.PHASE_LABELS.get(new_state['phase'], new_state['phase'])}"
                    )
                    phase_done_at = None
                    continue

                # ---- 子步骤会话（交互步 TUI 段 / 非交互步 headless 段，门控处理统一）----
                cur = state.get("sub_step_index", 1)
                step = engine.sub_step_at(node, cur)
                if step is None:
                    disp.log(f"✗ 子步骤 {cur} 不存在（state 越界）——断点等用户处置")
                    if on_breakpoint("state 越界", SEG_BREAKPOINT) == "quit":
                        return 0
                    continue

                total = len(node.sub_steps)
                disp.begin(f"子步骤 {cur}/{total} · {step.short}")
                bare_open = _is_bare_open(
                    node,
                    cur,
                    pending_rework,
                    has_statement=bool(state.get("problem_statement")),
                )
                prep_next = None  # P2-1：下一步为交互步时 = 该 Step（仅工作段赋值）
                out = ""
                confirm_readback = (
                    getattr(step, "interactive", False)
                    and getattr(step, "tier", "decision") == "confirm"
                )
                prep_done = (
                    getattr(step, "interactive", False)
                    and not confirm_readback
                    and not bare_open
                    and _consume_next_prep(
                        project_root,
                        name,
                        f"{engine.node_id(node.phase, node.sub)}#{cur}",
                    )
                )
                if confirm_readback:
                    # P3-1 确认级读回：无 prep/TUI 段——机械展示 + 装配 + 静默通过。
                    disp.log(f"  ≡ 读回确认级（{node.label}）——机械展示+静默通过")
                    ok_rb, text_rb = engine.render_readback(project_root, name)
                    if ok_rb:
                        for _ln in text_rb.splitlines():
                            disp.log(f"  {_ln}")
                    else:
                        # 展示降级不阻断（内容在 evidence/产物，宁纵勿枉）
                        disp.log(f"  ⚠ render-readback 降级：{text_rb[:120]}")
                    art = engine.confirm_artifact(node)
                    if art is not None:
                        _base, _slug = art
                        ok_a, msg_a = engine.render_artifact(
                            project_root,
                            name,
                            _base,
                            slug=(name if _slug == "USE_WORKFLOW_NAME" else _slug),
                        )
                        if ok_a:
                            disp.log(f"  ✓ 产物装配：{msg_a[:120]}")
                        else:
                            # fail loud：下游步骤读该产物——断点等裁决
                            if (
                                on_breakpoint(
                                    f"⛔ 确认级产物装配失败（{_base}）：{msg_a[:150]}——"
                                    f"回车重试 / step-pass / state-reset / q 退出。",
                                    SEG_BREAKPOINT,
                                )
                                == "quit"
                            ):
                                return 0
                            continue
                    engine.write_confirm_trace(project_root, name, node, cur)
                    rc, sid, seg_kind = 0, "confirm", "confirm-readback"
                elif prep_done:
                    # P2-1：问题清单已由前序工作段顺带备妥（need_user.json 在位）——
                    # 省独立 prep 段，直接转前台问答
                    disp.log("  ⚑ 问题清单前序段已备（P2-1 合并段）——转前台问答")
                    _warn_sources_missing(meta, disp)
                    rc, sid, seg_kind = on_need_user(
                        state, node, cur, step, pending_rework
                    )
                elif getattr(step, "interactive", False) and not bare_open:
                    # 交互步后台化预处理（interactive-step-headless-prep §4.1）：
                    # 不停段让 TUI——先 headless 备问题清单（L1 工具封锁+变体 prompt），
                    # 出口恒为 NEED_USER（显式标记 > L2 AskUserQuestion 嗅探）。
                    # 裸开场（u:1#1 无返工）除外——保 57a64e1 用户裁决的 TUI 原生开场。
                    rules = ensure_node_rules(project_root, name, node, cur)
                    prompt = build_step_prompt(
                        project_root,
                        name,
                        state,
                        node,
                        cur,
                        step,
                        rework=pending_rework,
                        prep=True,
                    )
                    rc, out, sid = run_session(
                        prompt,
                        cwd=wt,
                        settings=settings,
                        sys_prompt_file=rules,
                        meta=meta,
                        debug=debug,
                        note=f"{engine.node_id(node.phase, node.sub)}#{cur}-prep",
                        verbose=verbose,
                        disp=disp,
                        disallow_ask=True,
                    )
                    seg_kind = "headless-prep"
                    if rc != RC_INTERRUPTED:
                        need = bool(NEED_USER_RE.search(out)) or (
                            _session_called_ask_user(meta, sid)
                        )
                        if need:
                            _stash_need_user_payload(meta, out)
                            _warn_sources_missing(meta, disp)
                            # drive 当场重分类起 TUI 段；--segment 抛 _SegmentExit(13)
                            rc, sid, seg_kind = on_need_user(
                                state, node, cur, step, pending_rework
                            )
                        else:
                            # L3：prep 会话无出口——none 计数重试（不交门控：
                            # prep 无 trace 交付，trace 归前台问答段）
                            _record_segment(
                                project_root,
                                name,
                                session_id=sid,
                                kind=seg_kind,
                                note=f"rc={rc}",
                            )
                            none_retries += 1
                            disp.log(
                                f"  ⚠ 预处理会话未输出 NEED_USER"
                                f"（{none_retries}/{NONE_RETRY_LIMIT}）"
                            )
                            if none_retries >= NONE_RETRY_LIMIT:
                                none_retries = 0
                                if (
                                    on_breakpoint(
                                        f"⛔ 子步骤 {cur} 预处理连续 "
                                        f"{NONE_RETRY_LIMIT} 次未输出 NEED_USER——"
                                        f"回车重试 / step-pass / state-reset / q 退出。",
                                        SEG_BREAKPOINT,
                                    )
                                    == "quit"
                                ):
                                    return 0
                                continue
                            pending_rework = (
                                "上一轮你未输出 ### NEED_USER——本步唯一交付 = "
                                "备好问题清单后输出 ### NEED_USER + ```json 问题载荷。"
                                "禁落 trace、禁调 AskUserQuestion、禁编造用户答复。"
                            )
                            continue
                elif getattr(step, "interactive", False):
                    rc, sid, seg_kind = on_interactive(
                        state, node, cur, step, pending_rework
                    )
                else:
                    # u1-sub5-cost 修3：pre_dispatch 声明步（u:1#5 红队）——
                    # 派本步段前先预起后台 worker（红队运行与本步段并行）
                    _maybe_predispatch_redteam(
                        project_root,
                        name,
                        step,
                        wt=wt,
                        settings=settings,
                        meta=meta,
                        disp=disp,
                    )
                    rules = ensure_node_rules(project_root, name, node, cur)
                    # P2-1：下一 decision 级交互步 -> 本段顺带备其问题清单（NEXT_PREP
                    # 通道）；确认级读回步无问答（P3-1），不备。
                    # u2-sub1-cost 修A：lookahead 跨节点——confirm 步横在中间不再挡路
                    # （u:1#6 顺带备 u:2#1，独立 prep 段整段消失）；stash key =
                    # 目标步全 id（消费侧本就以被消费步自身 id 查，天然对齐）。
                    _nxt_info = engine.next_decision_interactive_step(
                        node.phase, node.sub, cur
                    )
                    prep_next = _nxt_info[2] if _nxt_info else None
                    prep_next_key = (
                        f"{engine.node_id(_nxt_info[0].phase, _nxt_info[0].sub)}"
                        f"#{_nxt_info[1]}"
                        if _nxt_info
                        else None
                    )
                    prompt = build_step_prompt(
                        project_root,
                        name,
                        state,
                        node,
                        cur,
                        step,
                        rework=pending_rework,
                        prep_next=prep_next,
                        prep_next_key=prep_next_key,
                    )
                    nid = engine.node_id(node.phase, node.sub)
                    resume_sid = _chain_resume_sid(state, nid, cur)
                    if resume_sid:
                        disp.log(f"  ⟂ 段链续跑（{nid} 链，子{cur}）——同会话 --resume")
                    rc, out, sid = run_session(
                        prompt,
                        cwd=wt,
                        settings=settings,
                        sys_prompt_file=rules,
                        meta=meta,
                        debug=debug,
                        note=f"{nid}#{cur}",
                        verbose=verbose,
                        disp=disp,
                        resume_sid=resume_sid,
                    )
                    seg_kind = "headless-step"
                    if (
                        resume_sid
                        and rc != RC_INTERRUPTED
                        and rc != 0
                        and not out.strip()
                    ):
                        # 续链失败兜底（transcript 缺失/损坏——设计期冒烟：坏 sid
                        # = rc 1 + 零 assistant 事件）：降级新会话重发，留痕
                        disp.log(
                            "  ⚠ 续链失败——降级新会话重发（chain_broken_fallback）"
                        )
                        _chain_clear(project_root, name)
                        rc, out, sid = run_session(
                            prompt,
                            cwd=wt,
                            settings=settings,
                            sys_prompt_file=rules,
                            meta=meta,
                            debug=debug,
                            note=f"{nid}#{cur}",
                            verbose=verbose,
                            disp=disp,
                        )
                    if NEED_USER_RE.search(out):
                        # 动态交互 fallback（§2.3）：模型非预期需要用户输入——
                        # drive 当场重分类起 TUI 段；--segment 抛 _SegmentExit(13)。
                        rc, sid, seg_kind = on_need_user(
                            state, node, cur, step, pending_rework
                        )
                if pending_rework is not None:
                    # 消费即清（TUI block 退出时落 state 的返工上下文，防陈旧污染）
                    st = _load(project_root, name)
                    if st.pop("pending_rework", None) is not None:
                        engine.save_state(project_root, name, st)
                pending_rework = None
                _record_segment(
                    project_root, name, session_id=sid, kind=seg_kind, note=f"rc={rc}"
                )
                if seg_kind.startswith("tui"):
                    seg_rc = _handle_tui_segment_end(
                        project_root, name, wt, cur, meta, disp
                    )
                    if seg_rc is not None:
                        return seg_rc  # 手动退出：TUI 退 = 全退
                    # autodone：落共享门控（advanced 续跑 / block 自动返工 / escalate 断点）
                if rc == RC_INTERRUPTED:
                    # 单击中断子会话（§2.6）——断点等裁决，不自动重发
                    _chain_clear(
                        project_root, name
                    )  # P2-4：杀中段 transcript 尾或残半 turn——断链
                    if (
                        on_breakpoint(
                            f"⛔ 子步骤 {cur} 子会话已被用户中断（单击）——"
                            f"回车重试本步 / step-pass / state-reset / q 退出。",
                            SEG_BREAKPOINT,
                        )
                        == "quit"
                    ):
                        return 0
                    continue

                action, reason, _ns = engine.gate_sub_step_at_stop(
                    project_root, name, str(wt)
                )
                if action == "advanced":
                    none_retries = 0
                    disp.log(f"  ✓ 子步骤 {cur} 通过门控")
                    if seg_kind == "headless-step":
                        # P2-4：落链（白名单外节点 = 链作废，见 _chain_update）；
                        # block/none 不落——last_step 停 cur-1，下轮自然续链返工
                        _chain_update(
                            project_root,
                            name,
                            engine.node_id(node.phase, node.sub),
                            cur,
                            sid,
                        )
                    if prep_next is not None and _NEXT_PREP_JSON_RE.search(out):
                        # P2-1：只在门控通过后落标记——被 block 的内容备的问题
                        # 不得转前台（返工段会重新输出，覆盖更新）
                        if _stash_need_user_payload(meta, out, _NEXT_PREP_JSON_RE):
                            _mark_next_prep(
                                project_root,
                                name,
                                prep_next_key,
                            )
                            _warn_sources_missing(meta, disp)
                    continue
                if action == "block":
                    none_retries = 0
                    disp.log(f"  ✗ 门控 block：{reason[:200]}")
                    pending_rework = _rework_text(reason)
                    continue
                if action == "escalate":
                    none_retries = 0
                    if (
                        on_breakpoint(
                            f"⛔ 子步骤 {cur} 连续 block 达阈值（判词：{reason[:200]}）——"
                            f"用户裁决：step-pass 强制通过 / state-reset 回退 / q 退出。",
                            SEG_BREAKPOINT,
                        )
                        == "quit"
                    ):
                        return 0
                    continue
                # none：会话结束但门控读不到新 trace（没落库 / 中途停了）
                if seg_kind.startswith("tui"):
                    # TUI 段未落库（双击 Ctrl+C 退出 / /exit 早退）——交互步靠用户
                    # 驱动，自动重开=「退出还继续流程」（§2.6 实证坑）；直接断点裁决
                    if (
                        on_breakpoint(
                            f"⛔ 子步骤 {cur} TUI 段已结束但未落库——"
                            f"回车重开 TUI / step-pass / state-reset / q 退出。",
                            SEG_BREAKPOINT,
                        )
                        == "quit"
                    ):
                        return 0
                    continue
                none_retries += 1
                disp.log(f"  ⚠ 门控读不到新 trace（{none_retries}/{NONE_RETRY_LIMIT}）")
                if none_retries >= NONE_RETRY_LIMIT:
                    none_retries = 0
                    if (
                        on_breakpoint(
                            f"⛔ 子步骤 {cur} 连续 {NONE_RETRY_LIMIT} 次会话未落 trace——"
                            f"step-pass 强制通过 / state-reset 回退 / 直接回车重试 / q 退出。",
                            SEG_BREAKPOINT,
                        )
                        == "quit"
                    ):
                        return 0
                    continue
                pending_rework = (
                    "上一轮会话结束后，门控在 evidence 里读不到本子步骤的新 trace——"
                    "你的产出等于没交。本步的硬性交付是 append-trace 落库："
                    "--scaffold 生成骨架 → Edit 填「待填」→ --from-file 落库。"
                    "若上次 append-trace 报错，按报错修载荷重跑，不要跳过。"
                )
                continue

            # ---- 无编排阶段（execute/review/evolution）：整阶段一个会话 ----
            if phase_done_at != (cur_phase, state["sub_index"]):
                disp.begin(
                    f"阶段「{engine.PHASE_LABELS.get(cur_phase, cur_phase)}」· 整阶段会话"
                )
                rules = ensure_phase_rules(project_root, name)
                prompt = build_phase_prompt(project_root, name, state)
                rc, out, sid = run_session(
                    prompt,
                    cwd=wt,
                    settings=settings,
                    sys_prompt_file=rules,
                    meta=meta,
                    debug=debug,
                    note=f"phase:{cur_phase}",
                    verbose=verbose,
                    disp=disp,
                )
                _record_segment(
                    project_root,
                    name,
                    session_id=sid,
                    kind="headless-phase",
                    note=f"rc={rc}",
                )
                if rc == RC_INTERRUPTED:
                    # 单击中断子会话（§2.6）——断点等裁决，不自动重发
                    if (
                        on_breakpoint(
                            "⛔ 阶段会话已被用户中断（单击）——"
                            "回车重试 / next 强制推进 / q 退出。",
                            SEG_BREAKPOINT,
                        )
                        == "quit"
                    ):
                        return 0
                    continue
                m = PHASE_DONE_RE.search(out)
                if m and m.group(1) == cur_phase:
                    phase_done_at = (cur_phase, state["sub_index"])
                    none_retries = 0
                else:
                    none_retries += 1
                    disp.log(
                        f"  ⚠ 阶段会话结束但未输出 PHASE_DONE（{none_retries}/{NONE_RETRY_LIMIT}）"
                    )
                    if none_retries >= NONE_RETRY_LIMIT:
                        none_retries = 0
                        if (
                            on_breakpoint(
                                f"⛔ 阶段会话连续 {NONE_RETRY_LIMIT} 次未完成（未输出 "
                                f"### PHASE_DONE: {cur_phase}）——next 强制推进 / 直接回车重试 / q 退出。",
                                SEG_BREAKPOINT,
                            )
                            == "quit"
                        ):
                            return 0
                    continue
            # PHASE_DONE 已确认 -> 闸门 -> 推进
            if engine.is_gated_after(cur_phase) and state.get("gate") != "passed":
                if (
                    on_breakpoint(
                        f"⛔ 阶段闸门：{engine.PHASE_LABELS.get(cur_phase, cur_phase)}"
                        f" 已完成，进下一阶段需 gate 放行。",
                        SEG_GATE,
                    )
                    == "quit"
                ):
                    return 0
                continue
            new_state = engine.advance_state(project_root, name, via="driver")
            disp.log(
                f"\n╔═ 阶段切换：{engine.PHASE_LABELS.get(cur_phase, cur_phase)} ──► "
                f"{engine.PHASE_LABELS.get(new_state['phase'], new_state['phase'])}"
            )
            phase_done_at = None
    except KeyboardInterrupt:
        # 信号落在 gate/judge/装配等未专门处理的角落（§2.6）——单击即退出
        print("\n✗ 用户中断——已退出。state 在磁盘，`dl <name>` 随时续。")
        return 130


def run_segment(project_root: Path, name: str, debug: bool = False) -> int:
    """--segment：从 state 当前位置连续跑非交互工作，撞边界按退出码收场。

    与 drive() 共用 _run_boundary_loop（单一逻辑真源，禁拷贝分叉）；两模式差异
    全在策略回调：交互步 / NEED_USER / 断点 = 抛 _SegmentExit（段无 stdin 可等）。
    结局落 segment_summary.json（code+message+位置，前台会话的判读便签——
    state.json 仍是唯一真源）；front_segment.json 锁（pid+起跑位置）随退出清。
    drive_mode try/finally 恢复 off（编排权交回前台会话）；段被 SIGKILL 时 finally
    不跑——锁残留由前台 hooks 以 pid 活性判 stale，drive_mode 残留由 launcher
    启动时显式 off 兜底（同 WF_TUI 路径既有做法）。
    """
    meta = _meta_root(project_root, name)
    settings = ensure_drive_settings(project_root, name)
    state = _load(project_root, name)
    wt = Path(state["worktree_path"])
    engine.set_drive_mode(project_root, name, True)
    (meta / "front_segment.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "node": state.get("node"),
                "sub_step": state.get("sub_step_index"),
            }
        ),
        encoding="utf-8",
    )

    def _breakpoint(header: str, code: int) -> str:
        raise _SegmentExit(code, header)

    def _interactive(st, node, cur, step, rework):
        # 仅剩裸开场路径（主循环里其余交互步已被 prep 分支截走）
        raise _SegmentExit(
            SEG_INTERACTIVE,
            f"撞裸开场 {engine.node_id(node.phase, node.sub)}#{cur}"
            f"（{step.short}）——回前台会话自由对话。",
        )

    def _need_user(st, node, cur, step, rework):
        payload_note = (
            "问题清单已备好：need_user.json。"
            if (meta / "need_user.json").exists()
            else ""
        )
        raise _SegmentExit(
            SEG_NEED_USER,
            f"子步骤 {cur} 的 headless 会话请求用户输入（### NEED_USER）"
            f"——回前台会话交互处理本步。{payload_note}",
        )

    code, message = SEG_DONE, "工作流全部 5 阶段已完成。"
    try:
        rc = _run_boundary_loop(
            project_root,
            name,
            wt,
            meta,
            settings,
            debug,
            False,
            _PrintDisp(),
            on_breakpoint=_breakpoint,
            on_interactive=_interactive,
            on_need_user=_need_user,
        )
        if rc != 0:  # KeyboardInterrupt 130 等：归断点（后台段无 tty 单击语义）
            code, message = SEG_BREAKPOINT, f"段被中断（rc={rc}）——重跑同一命令即续。"
    except _SegmentExit as e:
        code, message = e.code, e.message
    except Exception as e:  # 段异常必须落 summary——后台无人看 stderr
        code, message = SEG_ERROR, f"段异常：{type(e).__name__}: {e}"
    finally:
        (meta / "front_segment.json").unlink(missing_ok=True)
        engine.set_drive_mode(project_root, name, False)
    end_state = _load(project_root, name)
    (meta / "segment_summary.json").write_text(
        json.dumps(
            {
                "code": code,
                "message": message,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "node": end_state.get("node"),
                "sub_step": end_state.get("sub_step_index"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"—— 段结束（code={code}）：{message}")
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dl_drive", description="headless driver 编排器"
    )
    parser.add_argument("name", help="工作流名")
    parser.add_argument(
        "--debug", action="store_true", help="段会话 debug 落盘 per-wf 目录"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="子会话输出尾随上屏（默认静默——只落 drive-stream.jsonl，保常驻进度区）",
    )
    parser.add_argument(
        "--segment",
        action="store_true",
        help="段模式（v4 前台混合）：跑连续工作段（交互步先 prep 备问题）后按退出码收场，撞裸开场/门栏/NEED_USER 回前台",
    )
    args = parser.parse_args(argv)

    project_root = engine.resolve_project_root(str(Path.cwd()))
    if project_root is None:
        print("✗ 不在 git 仓库内", file=sys.stderr)
        return 1
    if args.segment:
        return run_segment(project_root, args.name, debug=args.debug)
    return drive(project_root, args.name, args.debug, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
