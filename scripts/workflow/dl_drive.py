#!/usr/bin/env python3
"""dl_drive.py - headless driver：外部编排器（v3，designs/headless-driver-arch-design.md）。

替代「一个长 TUI 会话 + Stop hook 推进」：每个子步骤/阶段一个全新 `claude -p`
短会话（上下文 = 交接包 + 当前步目的，按构造最小），门控/推进由本进程直调
dl_flow_engine（state.json + evidence.jsonl 磁盘真源，天然会话无关）。

动机（2026-08-08 tail_volume 审计）：单会话上下文 244k→485k 零锯齿、cache_read
318.7M（成本=轮次×上下文的平方膨胀）；边界 /clear 提示 15 次注入 0 次上屏
（attachment 进模型不被转达，且 /clear 无程序化入口）。

交互子步骤（Step.interactive，读回步等 AskUserQuestion 场景）回 TUI 段（M2）。
门栏/闸门 = 本进程前台断点，stdin 收 gate/back/state-reset 等（转发 dl-cmd.sh，
外部终端 /dl 并发也兼容——每轮循环重读 state.json）。

被 dl-launch.sh 派发（ac-deepseek1 --dl <name> [--debug]）；WF_TUI=1 回旧 TUI 路径。
"""

import argparse
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

_DLWF_ROOT = Path(__file__).resolve().parents[2]  # ~/.dl-workflow/
sys.path.insert(0, str(_DLWF_ROOT))
import dl_flow_engine as engine  # noqa: E402

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
    与 SessionStart hook（交接包由 driver prompt 注入，防双份）。
    workflow_advance / step_fence / phase 保留（hook 内 drive_mode 分支降级/收窄）。
    内容变化才重写（per-wf settings.json 是真源，版本戳机制天然覆盖模板升级）。
    """
    meta = _meta_root(project_root, name)
    src = meta / "settings.json"
    dst = meta / "settings.drive.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    data.pop("outputStyle", None)
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


def ensure_node_rules(project_root: Path, name: str, node: "engine.Node") -> Path:
    """节点级 system prompt（瘦版）：只含本节点子步骤段落——92KB 全量税按构造消失。"""
    meta = _meta_root(project_root, name)
    nid = engine.node_id(node.phase, node.sub)
    out = meta / f"node-rules.{nid}.md"
    section = engine.render_substeps_section(nid)
    phase_label = engine.PHASE_LABELS.get(node.phase, node.phase)
    text = (
        f"# WORKFLOW 节点规则（driver 装配瘦版——全量 phase-rules 不注入）\n\n"
        f"你在外部 driver 编排的工作流会话中执行子步骤。**每个会话只做当前一个子步骤**；"
        f"后续步骤由 driver 另起全新会话，与你无关。门控只认 evidence trace"
        f"（append-trace 落库），不认可完成标记。\n\n"
        f"## 通用纪律\n"
        f"- 完成后必须 append-trace 落库（--scaffold 生成骨架 → Edit 填「待填」→ --from-file）\n"
        f"- 禁输出 ### STEP_DONE / ### PHASE_DONE 标记（外部编排，标记无效）\n"
        f"- 当前阶段「{phase_label}」的写权限由 S11 硬约束执行（禁写范围见 phase-rules）\n"
        f"- 禁静默兜底：捕获异常必 log，默认值必标记，缺数据必暴露\n\n"
        f"## 本节点子步骤清单\n\n"
        f"{section}\n"
    )
    if not out.exists() or out.read_text(encoding="utf-8") != text:
        out.write_text(text, encoding="utf-8")
    return out


# ---------- 会话执行（stream-json 实时尾随） ----------


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
) -> tuple[int, str, str]:
    """一次 headless `claude -p` 会话。返回 (rc, assistant 全文, session_id)。

    stream-json 逐行解析：原始流全量落 drive-stream.jsonl（审计/PHASE_DONE 检测
    的数据源）。verbose=False（默认，drive-tasklist-render-design §2.1——用户裁决
    子会话进度不用展示）：assistant text 不上屏（防冲刷常驻进度区），tool_use
    简报喂常驻区「最近动作」行；verbose=True 恢复旧尾随行为（text + ⚙ 行上屏）。
    """
    sid = str(uuid.uuid4())
    cmd = [
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "acceptEdits",
        "--settings",
        str(settings),
        "--append-system-prompt-file",
        str(sys_prompt_file),
        "--session-id",
        sid,
    ]
    if debug:
        cmd += [
            "--debug",
            "api,hooks",
            "--debug-file",
            str(meta / f"cc_debug.{sid[:8]}.log"),
        ]
    cmd.append(prompt)
    meta.mkdir(parents=True, exist_ok=True)
    texts: list[str] = []
    with (
        open(meta / "drive-stream.jsonl", "a", encoding="utf-8") as log_f,
        open(meta / "cc_sdk.log", "a", encoding="utf-8") as err_f,
    ):
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=err_f,
            text=True,
            bufsize=1,
        )
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
        except KeyboardInterrupt:
            proc.terminate()
            print("\n✗ 用户中断（段会话已终止）。state 在磁盘，重跑 `dl <name>` 续。")
            raise SystemExit(130)
        rc = proc.wait()
    return rc, "\n".join(texts), sid


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
) -> str:
    """子步骤会话 prompt = 交接包 + 当前步目的 + append-trace 指引 + 铁律（+返工判词）。

    复用 _stop_continue 的指令骨架（workflow_advance.py），差异：
    禁完成标记（外部编排）+ 只做本步（会话粒度=子步骤）。
    interactive=True（TUI 段）：交接包由 SessionStart hook 注入（全量 settings），
    prompt 不带防双份；交互指引替换 NEED_USER 出口。
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
        tail = (
            # TaskList 硬条款（drive-tasklist-render-design §2.3）：output-style
            # 的建清单义务被瘦版 node-rules 稀释（首次 dogfood 实证零 TaskCreate），
            # prompt 显著性兜底——TUI 段用户看到的就是 v2.0 原生 TaskList。
            "- 会话开场第一件事：按 output-style 用 TaskCreate 建齐 13 项阶段清单"
            "（subject 带编号 1./1.1…/5.，一条消息批量建齐），状态镜像当前进度"
            "（当前子阶段 in_progress、之前 completed、之后 pending），再做本子步\n"
            "- 需要用户输入时用 AskUserQuestion（回合内完成），用户就在终端前\n"
            "- 完成并落库后，用文本告诉用户「交互步已完成，请 /exit 返回 driver」"
            "并结束本轮"
        )
    else:
        tail = (
            "- 非预期需要用户输入时：输出 `### NEED_USER` + 问题清单后结束"
            "（driver 会接管为交互会话），禁编造用户答复"
        )
    parts.append(
        f"## WORKFLOW 当前任务（外部 driver 编排）\n"
        f"工作流 {name} · {phase_label} [{state['index']}/5] · "
        f"子阶段「{node.label}」· 子步骤 {cur}/{total}（{step.kind}: {step.ref}）\n\n"
        f"目的：{step.purpose}\n\n"
        f"{how}；完成后落 evidence（本步的硬性交付，门控只认它）：\n"
        f"1. Bash `python3 ~/.dl-workflow/dl_flow_engine.py append-trace --scaffold`"
        f" 生成载荷骨架（打印路径）\n"
        f"2. Read 骨架文件，Edit 把每个「待填」换成实际内容\n"
        f"3. Bash `python3 ~/.dl-workflow/dl_flow_engine.py append-trace "
        f"--from-file <骨架路径>` 落库\n\n"
        f"铁律：\n"
        f"- 只做这一个子步骤——后续步骤由 driver 另起会话，与你无关\n"
        f"- 禁输出 ### STEP_DONE / ### PHASE_DONE 标记（外部编排，标记无效）\n"
        f"{tail}\n" + engine.selfcheck_hint(step)
    )
    if rework:
        parts.append(f"\n## 返工上下文\n{rework}")
    return "\n".join(parts)


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
) -> tuple[int, str]:
    """交互子步骤 TUI 段：起原生 claude TUI（全量 per-wf settings——SessionStart
    注入交接包 / phase 注入 / output-style 横幅齐备），用户交互 + /exit 回收。

    返回 (rc, session_id)。drive_mode 下 advance hook 不推进（state 由 driver
    在回收后统一门控）；fence 仅 S11/S14 硬约束生效。
    """
    sid = str(uuid.uuid4())
    settings = ensure_tui_settings(project_root, name)  # 全量模板+hook 路径同仓化
    rules = ensure_node_rules(project_root, name, node)
    prompt = build_step_prompt(
        project_root, name, state, node, cur, step, rework=rework, interactive=True
    )
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
    if debug:
        cmd += [
            "--debug",
            "api,hooks",
            "--debug-file",
            str(meta / f"cc_debug.{sid[:8]}.log"),
        ]
    cmd.append(prompt)
    print(
        f"\n▸ 交互子步骤 {cur}/{len(node.sub_steps or ())} —— 起 TUI 会话"
        f"（回答模型提问；模型报告完成后输入 /exit 返回 driver）"
    )
    if disp is not None:
        disp.stop()  # 终端交还 TUI 会话
    try:
        with open(meta / "cc_sdk.log", "a", encoding="utf-8") as err_f:
            rc = subprocess.run(cmd, cwd=str(wt), stderr=err_f, check=False).returncode
    finally:
        if disp is not None:
            disp.start()
    print(f"—— TUI 段会话结束（{engine.node_id(node.phase, node.sub)}#{cur}，rc={rc}）")
    return rc, sid


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


# ---------- 主循环 ----------


def drive(project_root: Path, name: str, debug: bool, verbose: bool = False) -> int:
    meta = _meta_root(project_root, name)
    settings = ensure_drive_settings(project_root, name)
    engine.set_drive_mode(project_root, name, True)
    state = _load(project_root, name)
    wt = Path(state["worktree_path"])
    print(f"▸ driver 接管工作流 '{name}'（headless 编排，state 磁盘真源）")
    print(f"  worktree: {wt}  日志: {meta}/drive-stream.jsonl")

    # ---- 开场问题陈述采集（drive-tasklist-render-design §2.4）----
    # 恢复 v2.0「首条用户消息」语义：handoff_pack 顶部收录后，子1 模型开场即有
    # 用户原话可引，不再面对工作流名 slug 自力更生翻仓库。可空跳过（交互步追问兜底）。
    if not (state.get("problem_statement") or "").strip() and sys.stdin.isatty():
        print("══ 开场采集 ══ 本工作流全程围绕你描述的问题展开（交接包携带）。")
        try:
            ans = input(
                "请用一两句话描述本次要分析的问题（直接回车跳过，交互步会追问）："
            ).strip()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans:
            engine.set_problem_statement(project_root, name, ans)
            state = _load(project_root, name)
            print(f"  ✓ 已记录问题陈述（{len(ans)} 字）")

    disp = LiveProgress(project_root, name, verbose=verbose)
    disp.start()

    pending_rework: str | None = None  # block/none 后下次会话的返工上下文
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
                    breakpoint_loop(
                        project_root,
                        name,
                        wt,
                        f"⛔ 子阶段门栏：「{node.label}」全部子步骤已通过门控，"
                        f"进下一子阶段需用户裁决（gate 放行 / state-reset 重测）。",
                        disp=disp,
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
                            breakpoint_loop(
                                project_root,
                                name,
                                wt,
                                f"⛔ 阶段闸门：{engine.PHASE_LABELS.get(cur_phase, cur_phase)}"
                                f" 已完成（产物已装配），进下一阶段需 gate 放行。",
                                disp=disp,
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
                    if (
                        breakpoint_loop(project_root, name, wt, "state 越界", disp=disp)
                        == "quit"
                    ):
                        return 0
                    continue

                total = len(node.sub_steps)
                disp.begin(f"子步骤 {cur}/{total} · {step.short}")
                if getattr(step, "interactive", False):
                    rc, sid = run_tui_step(
                        project_root,
                        name,
                        state,
                        node,
                        cur,
                        step,
                        meta,
                        debug,
                        wt,
                        rework=pending_rework,
                        disp=disp,
                    )
                    seg_kind = "tui-step"
                else:
                    rules = ensure_node_rules(project_root, name, node)
                    prompt = build_step_prompt(
                        project_root,
                        name,
                        state,
                        node,
                        cur,
                        step,
                        rework=pending_rework,
                    )
                    rc, out, sid = run_session(
                        prompt,
                        cwd=wt,
                        settings=settings,
                        sys_prompt_file=rules,
                        meta=meta,
                        debug=debug,
                        note=f"{engine.node_id(node.phase, node.sub)}#{cur}",
                        verbose=verbose,
                        disp=disp,
                    )
                    seg_kind = "headless-step"
                    if NEED_USER_RE.search(out):
                        # 动态交互 fallback（§2.3）：模型非预期需要用户输入——
                        # 当场重分类为交互步，同轮起 TUI 段接管（不重发 headless）。
                        disp.log("  ⚑ 模型请求用户输入（NEED_USER）——接管为 TUI 段")
                        rc, sid = run_tui_step(
                            project_root,
                            name,
                            state,
                            node,
                            cur,
                            step,
                            meta,
                            debug,
                            wt,
                            rework=pending_rework,
                            disp=disp,
                        )
                        seg_kind = "tui-step-needuser"
                pending_rework = None
                _record_segment(
                    project_root, name, session_id=sid, kind=seg_kind, note=f"rc={rc}"
                )

                action, reason, _ns = engine.gate_sub_step_at_stop(
                    project_root, name, str(wt)
                )
                if action == "advanced":
                    none_retries = 0
                    disp.log(f"  ✓ 子步骤 {cur} 通过门控")
                    continue
                if action == "block":
                    none_retries = 0
                    disp.log(f"  ✗ 门控 block：{reason[:200]}")
                    pending_rework = (
                        f"上一轮门控未通过（判词原文）：\n{reason}\n\n"
                        f"按判词修正后重做本子步骤——修正方式 = append-trace 追加新 trace"
                        f"（禁覆盖/编辑旧行，judge 以最后一条为准）。"
                    )
                    continue
                if action == "escalate":
                    none_retries = 0
                    if (
                        breakpoint_loop(
                            project_root,
                            name,
                            wt,
                            f"⛔ 子步骤 {cur} 连续 block 达阈值（判词：{reason[:200]}）——"
                            f"用户裁决：step-pass 强制通过 / state-reset 回退 / q 退出。",
                            disp=disp,
                        )
                        == "quit"
                    ):
                        return 0
                    continue
                # none：会话结束但门控读不到新 trace（没落库 / 中途停了）
                none_retries += 1
                disp.log(f"  ⚠ 门控读不到新 trace（{none_retries}/{NONE_RETRY_LIMIT}）")
                if none_retries >= NONE_RETRY_LIMIT:
                    none_retries = 0
                    if (
                        breakpoint_loop(
                            project_root,
                            name,
                            wt,
                            f"⛔ 子步骤 {cur} 连续 {NONE_RETRY_LIMIT} 次会话未落 trace——"
                            f"step-pass 强制通过 / state-reset 回退 / 直接回车重试 / q 退出。",
                            disp=disp,
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
                            breakpoint_loop(
                                project_root,
                                name,
                                wt,
                                f"⛔ 阶段会话连续 {NONE_RETRY_LIMIT} 次未完成（未输出 "
                                f"### PHASE_DONE: {cur_phase}）——next 强制推进 / 直接回车重试 / q 退出。",
                                disp=disp,
                            )
                            == "quit"
                        ):
                            return 0
                    continue
            # PHASE_DONE 已确认 -> 闸门 -> 推进
            if engine.is_gated_after(cur_phase) and state.get("gate") != "passed":
                if (
                    breakpoint_loop(
                        project_root,
                        name,
                        wt,
                        f"⛔ 阶段闸门：{engine.PHASE_LABELS.get(cur_phase, cur_phase)}"
                        f" 已完成，进下一阶段需 gate 放行。",
                        disp=disp,
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
    finally:
        disp.stop()


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
    args = parser.parse_args(argv)

    project_root = engine.resolve_project_root(str(Path.cwd()))
    if project_root is None:
        print("✗ 不在 git 仓库内", file=sys.stderr)
        return 1
    return drive(project_root, args.name, args.debug, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
