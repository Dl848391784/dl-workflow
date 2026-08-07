#!/usr/bin/env python3
"""
UserPromptSubmit hook：工作流阶段注入。

对应设计 designs/workflow-system-design.md §3。
每轮用户提问时，读当前工作流 state.json，注入「当前阶段 + 允许/禁止动作 + 完成标记格式」。

仿 codegraph_inject.py 范式：
- additionalContext 协议注入（裸 stdout 不被投递）。
- 容错：stdin 解析失败 / state.json 缺失 / cwd 不在 worktree -> exit 0 静默不注入。
- UserPromptSubmit 永不阻断（exit 0 only）。
- 异常留痕 <project>/.claude/.wf_phase.log（观测性，仿 .cg_inject.log）。

**dl-workflow 版本**：hook 装到 ~/.claude/hooks/（用户级），不再假设
`__file__.parents[2]` 是项目根。改用 `git rev-parse --git-common-dir`
从 payload cwd（worktree 内）反查主仓库根。state.json / .wf_phase.log
都存到主仓库 .claude/ 下（与旧版兼容）。
"""

import json
import subprocess
import sys
import time
from pathlib import Path

# ---------- 加载 engine（§8.4：PHASES/PHASE_LABELS/SUBPHASES 委托 engine 单源）----------
# repo 根不在 sys.path（hook 由 Claude Code 以脚本方式执行），先补再 import。
_DLWF_ROOT = Path(__file__).resolve().parents[1]  # ~/.dl-workflow/
sys.path.insert(0, str(_DLWF_ROOT))
import dl_flow_engine as engine  # noqa: E402

# 5 阶段顺序 / 标签 / 子阶段标签：委托 engine（§8.4 删三处副本,单源）。
PHASES = list(engine.PHASES)
PHASE_LABELS = engine.PHASE_LABELS


def _subphases(phase: str) -> list[str]:
    """phase -> 子阶段标签列表（委托 engine.subphase_labels,单源）。"""
    return engine.subphase_labels(phase)


# 各阶段规则（注入给模型的"允许/禁止/产物/推进"四要素）
# §8.4：goal/allow/deny 是行为约束文本（design §0.4 不收口文本规则）,留此处;
# PHASES/PHASE_LABELS/SUBPHASES 已委托 engine（上面）,不再各持副本。
PHASE_RULES = {
    "understand": {
        "goal": "理清真实问题（问题背后要解决的本质，非字面请求）",
        "allow": "Read/Bash 只读发现（find/ls/grep 等）/codegraph 查证/AskUserQuestion 澄清",
        "deny": "Edit/Write 任何源码",
        "artifact": f"understand.md（{engine.SECTIONS_TEXT['understand.md']}）",
        "advance": "自动推进到 plan（无闸门——2026-07-28 起围栏只设在 plan 完成）",
    },
    "plan": {
        "goal": "针对真实问题设计实现方案",
        "allow": "understand 的工具 + 起草 design.md(H8)",
        "deny": "改源码",
        "artifact": f"plan.md（{engine.SECTIONS_TEXT['plan.md']}）",
        "advance": "闸门：完成后需用户 /dl gate 放行才进 execute",
    },
    "execute": {
        "goal": "按计划改代码（守 H9/H11/H15/no silent fallback）",
        "allow": "全工具集；改已有 .py 前先 codegraph impact（H15）",
        "deny": "—",
        "artifact": "代码 + commit + 测试通过",
        "advance": "自动推进到 review（无闸门）",
    },
    "review": {
        "goal": "对照真实问题判定 solved/partial/not（证据 file:line / 测试输出）",
        "allow": "评审 subagent(Agent)/codegraph impact/跑测试",
        "deny": "改实现",
        "artifact": f"review.md（{engine.SECTIONS_TEXT['review.md']}）",
        "advance": "自动推进到 evolution（无闸门）",
    },
    "evolution": {
        "goal": "沉淀经验（写 memory 事实/更新 skill/补 design）",
        "allow": "写 memory/调 skill/补 design",
        "deny": "—",
        "artifact": f"evolution.md（{engine.SECTIONS_TEXT['evolution.md']} + memory 写入）",
        "advance": "终结（输出 PHASE_DONE: evolution 后工作流结束）",
    },
}


# 子阶段标签：委托 engine.subphase_labels（§8.4 删此处 SUBPHASES 副本,单源）。
# 详见 designs/understand-subphases-design.md。


def _payload_cwd(payload: dict) -> str:
    """从 hook payload 取 cwd（字段名容错），缺失回退进程 cwd。"""
    for key in ("cwd", "working_dir", "current_dir"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            return val
    return str(Path.cwd())


def _resolve_project_root(cwd: str) -> Path | None:
    """从 cwd（通常是 worktree 内）反查主仓库根。

    worktree 内 `git rev-parse --show-toplevel` 返回 worktree 根（错），
    须用 `--git-common-dir` -> 主仓库 .git 绝对路径，其 dirname 才是主 repo 根。
    主仓库内 --git-common-dir 返回 '.git' 相对 -> 回退 --show-toplevel。
    """
    try:
        res = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            common = res.stdout.strip()
            if common != ".git":
                # worktree 内：--git-common-dir 是绝对路径，dirname 即主 repo 根
                return Path(common).parent
        # fallback：主仓库内
        res2 = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res2.returncode == 0 and res2.stdout.strip():
            return Path(res2.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def _extract_prompt(payload: dict) -> str:
    """从 hook stdin payload 取提问文本（容错：试多个字段名）。"""
    for key in ("prompt", "prompt_text", "user_prompt", "message"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val
    nested = payload.get("user_prompt", {})
    if isinstance(nested, dict):
        for key in ("prompt", "text", "content"):
            val = nested.get(key)
            if isinstance(val, str) and val.strip():
                return val
    return ""


def _resolve_workflow_name(cwd: str) -> str | None:
    """从 cwd（worktree 路径）反查工作流名。

    worktree 路径形如 <repo>/.claude/worktrees/<name>。
    """
    parts = Path(cwd).parts
    if "worktrees" in parts:
        i = parts.index("worktrees")
        if i + 1 < len(parts):
            return parts[i + 1]
    return None


def _load_state(project_root: Path, name: str) -> dict | None:
    """读 <project>/.claude/workflows/<name>/state.json，缺失/损坏返回 None。"""
    f = project_root / ".claude" / "workflows" / name / "state.json"
    if not f.exists():
        return None
    try:
        with open(f, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def _log_invocation(
    project_root: Path | None,
    status: str,
    name: str = "",
    phase: str = "",
    prompt_len: int = 0,
    **fields: object,
) -> None:
    """留痕 UserPromptSubmit 触发（观测性）。失败静默。

    project_root 缺失时不留痕（无处写；此时 hook 也已 return，无害）。
    **fields 追加 k=v 到行尾（如 pm=default）；调用方传未知 kwarg 不得 crash
    （2026-07-25 事故：pm= 撞上固定签名 -> TypeError -> 注入已发但日志缺失）。
    """
    if project_root is None:
        return
    log = project_root / ".claude" / ".wf_phase.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        extra = "".join(f"|{k}={v}" for k, v in sorted(fields.items()))
        with open(log, "a", encoding="utf-8") as f:
            f.write(
                f"{ts}|{status}|wf={name}|phase={phase}|prompt_len={prompt_len}{extra}\n"
            )
    except OSError:
        pass


def _settings_staleness_notice(project_root: Path, name: str) -> str:
    """per-wf settings 模板版本落后时返警告文案，否则空串（v2.35，症状 R）。

    settings resume 不刷新——模板变更前创建的会话会静默缴 auto 权限税
    （tail_volume plan:3 实测 ~6.4min/20min）。这里把「静默缴税」变「可见可行动」。
    文件缺失/JSON 损坏不警告（那是症状 A1 的另一类问题，不误报；本通道永不因此炸）；
    版本字段缺失计 v0 = 落后（版本戳前的存量 settings 全命中，--resume 补写自愈）。
    """
    settings_file = project_root / ".claude" / "workflows" / name / "settings.json"
    try:
        data = json.loads(settings_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    cur = data.get("wf_settings_template_version", 0)
    latest = engine.SETTINGS_TEMPLATE_VERSION
    if not isinstance(cur, int) or cur >= latest:
        return ""
    return (
        f"## ⚠️ per-wf settings 模板版本落后（v{cur} < v{latest}）\n"
        "本会话 settings 由旧模板写成，权限白名单等可能缺新条目——"
        "Write/Bash 每次过 auto 裁决端点缴权限税（实测中位 Write 17s / Bash 14s）。\n"
        f"请用文本告知用户：跑 `dl {name} --resume` 刷新 settings"
        "（launcher 会用新模板补写），然后继续当前子步骤。\n\n"
    )


def _format_injection(state: dict, project_root: Path | None) -> str:
    """格式化阶段注入文本（当前阶段 + 规则四要素 + 子阶段 + 完成标记格式）。

    project_root：主仓库根（main() 已反查），用于拼 evidence.jsonl 绝对路径给模型写。
    """
    name = state.get("name", "?")
    phase = state.get("phase", "understand")
    idx = state.get("index", 1)
    gate = state.get("gate", "pending")
    sub_index = state.get("sub_index", 0)
    sub_total = state.get("sub_total", 0)
    rules = PHASE_RULES.get(phase, {})
    try:
        total = len(PHASES)
    except Exception:
        total = 5

    subs = _subphases(phase)
    has_sub = sub_total > 0 and bool(subs)
    cur_sub_label = (
        subs[sub_index - 1] if has_sub and 1 <= sub_index <= len(subs) else ""
    )

    # 任务清单目标状态（镜像 state.json 当前 index/sub_index；供模型同步原生 TaskList）
    # 阶段有子阶段时，紧跟该阶段任务后插入子任务 1.1..1.N（全程保留，已完成的也显示 completed）
    task_rows = []
    for i, p in enumerate(PHASES, 1):
        lbl = PHASE_LABELS.get(p, p)
        st = "completed" if i < idx else ("in_progress" if i == idx else "pending")
        task_rows.append(f"  {i}. {lbl} -> {st}")
        for j, slabel in enumerate(_subphases(p), 1):
            if i < idx:
                sst = "completed"
            elif i == idx:
                sst = (
                    "completed"
                    if j < sub_index
                    else ("in_progress" if j == sub_index else "pending")
                )
            else:
                sst = "pending"
            task_rows.append(f"    {i}.{j} {slabel} -> {sst}")

    header = f"工作流: {name} | 阶段: **{PHASE_LABELS.get(phase, phase)}** [{idx}/{total}] | gate: {gate}"
    if has_sub:
        header += f" | 子阶段: **{cur_sub_label}** [{sub_index}/{sub_total}]"

    lines = [
        "## WORKFLOW 当前阶段",
        header,
        f"- 目标: {rules.get('goal', '')}",
        f"- 允许: {rules.get('allow', '')}",
        f"- 禁止: {rules.get('deny', '')}",
        f"- 阶段产物: {rules.get('artifact', '')}",
        f"- 推进: {rules.get('advance', '')}",
    ]
    # 通用 skill 注入（§7 #1 落地，designs/skill-injection-link-design.md §3）：
    # 节点声明 skill 则提示模型 invoke；engine.NODES.skill 之前是死字段（_format_injection 不读）
    node = None
    try:
        node = engine.get_node(phase, sub_index)
    except (KeyError, Exception):
        pass  # get_node 非法节点 raise（engine 守 no silent fallback）；注入侧降级不阻断
    if node and node.skill:
        lines.append(
            f"- 技能: 当前节点应载 skill `{node.skill}`，请用 Skill 工具 invoke 它（已载则继续遵循）"
        )
    # 阶段产物规范位置（2026-07-28 用户决议）：主仓 .claude/<dir>/<name>.md，
    # 与 evidence 同级——worktree 归档删除时分支上产物一起丢，主仓 .claude/ 才存活。
    # 注入给绝对路径（同 evidence 载荷路径模式），防模型写 worktree 位置分裂。
    _ARTIFACT_DIRS = {
        "plan.md": "plans",
        "understand.md": "understands",
        "review.md": "reviews",
        "evolution.md": "evolutions",
    }
    if node and node.artifact in _ARTIFACT_DIRS and project_root is not None:
        extra = "；execute 首步也从这里读" if node.artifact == "plan.md" else ""
        lines.append(
            f"- 产物路径: `{project_root}/.claude/"
            f"{_ARTIFACT_DIRS[node.artifact]}/{state.get('name', '')}.md`"
            f"（写主仓此绝对路径——worktree 删除即丢，禁写 worktree 内{extra}）"
        )
    # §orchestration v2 D6 + §substep-gate-at-stop：节点有 sub_steps 时，注入子步骤清单 +
    # 逐步 purpose + STEP_DONE 格式 + evidence 写法（修复 commit4 遗漏：understand:1 现靠
    # sub_steps 清单块给 evidence 格式，旧 rubric_needs_evidence 触发的 trace 块已删）。
    # 子步骤=门控单位；gate+推进在 Stop hook（evidence 新 trace hash 触发）。
    # §subphase-hold-gate：门栏扣留状态 -> 注入等放行，不给子步骤编排块
    # （有效性三重判定：标记 + hold_for_gate + sub_step_index==末步，防 jump/back 后标记残留误导）。
    held_for_gate = bool(
        node
        and node.sub_steps
        and node.hold_for_gate
        and state.get("held_for_gate")
        and state.get("sub_step_index", 1) == len(node.sub_steps)
    )
    if held_for_gate:
        lines.append(
            "- ⛔ 子阶段门栏：本子阶段全部子步骤已通过门控，**推进被扣留**——"
            "等用户 `/dl gate` 放行（用户也可 /dl back 回退、/dl state-reset <n> 重测）。"
            "**不要做下一子阶段的事**；用户放行前，回答仅限本子阶段收尾/答疑。"
        )
    # §success-criteria-orchestration：advance="phase" 编排末节点（understand:4）
    # 编排完成 + 门栏已放行（判据单源 engine.phase_done_channel_open）->
    # 第三态：不给子步骤编排块，改提示写产物 + PHASE_DONE 撞阶段大闸门。
    phase_done_open = bool(
        node
        and project_root is not None
        and engine.phase_done_channel_open(project_root, name, state, node)
    )
    if phase_done_open:
        if node.artifact_on_release:
            lines.append(
                f"- ✓ 本子阶段全部子步骤已通过门控，门栏已放行——**汇总写 "
                f"{node.artifact or '阶段产物'}（各子阶段归一化陈述直接装配，禁二次创作）"
                f"+ 输出 `### PHASE_DONE: {node.phase}`** 触发阶段大闸门"
                "（仍需用户 `/dl gate` 放行才进下一阶段）。不要重做已通过的子步骤。"
            )
        else:
            # 产物已在末子步骤内装配（plan:4 plan.md「执行计划与检查点」节）——
            # 放行后只差完成信号
            lines.append(
                f"- ✓ 本子阶段全部子步骤已通过门控，门栏已放行——"
                f"{node.artifact or '阶段产物'}已在末子步骤装配完成，"
                f"**输出 `### PHASE_DONE: {node.phase}`** 触发阶段大闸门"
                "（仍需用户 `/dl gate` 放行才进下一阶段）。不要重做已通过的子步骤。"
            )
    if node and node.sub_steps and not held_for_gate and not phase_done_open:
        cur_step = state.get("sub_step_index", 1)
        total_steps = len(node.sub_steps)
        cur = (
            engine.sub_step_at(node, cur_step) if 1 <= cur_step <= total_steps else None
        )
        # P0 注入瘦身（designs/harness-prompt-optimization-design.md §2）：
        # 当前步 purpose 全文置顶（primacy）；其余 5 步只留骨架短名链。
        # 非当前步完整 purpose 在 phase-rules（system-prompt 通道，launcher 渲染同源），
        # 信息无丢失；与 ark fallback（dl-cmd status 只输出当前步 purpose）口径一致。
        if cur is not None:
            inp = f"输入：{cur.input}" if cur.input else "输入：无（首步）"
            rec = "记录：是（落 evidence skill-trace）" if cur.record else "记录：否"
            gate_tag = "" if cur.gate else " ｜自动过"
            lines.append(
                f"- ▶ 当前子步骤 {cur_step}/{total_steps} [{cur.kind}:{cur.ref}]\n"
                f"  目的：{cur.purpose}\n"
                f"  {inp} ｜{rec}{gate_tag}"
            )
            # v2.123：装配步硬提醒——装配义务埋在末步长 purpose 中段被 4/4 首忘
            # （tail_volume 2026-08-06：u:4#5/plan:2#5/plan:3#6/plan:4#5 全吃机械
            # block 各白返工一轮）。末步且挂 ARTIFACT 机械门时单列一行钉在 ▶ 块后。
            if cur_step == total_steps:
                hint = engine.assembly_obligation_hint(
                    node, project_root, state.get("name")
                )
                if hint:
                    lines.append(hint)
        chain_parts = []
        for i, stp in enumerate(node.sub_steps, 1):
            if i < cur_step:
                chain_parts.append(f"{i}.{stp.short} ✓")
            elif i == cur_step:
                chain_parts.append(f"{i}.{stp.short}【当前】")
            else:
                chain_parts.append(f"{i}.{stp.short}")
        lines.append("- 子步骤链：" + " → ".join(chain_parts))
        lines.append(
            "  强制：未达上步 purpose 就进下步=违规（等同未建清单就干活）。"
            "skill 内部 Q/A 不门控，按需 record 落 evidence 即可。"
            "每步完成输出 `### STEP_DONE: <n>` 作自声明。"
        )
        # §step-selfcheck：提交前自查提示（与 pass/block 续轮同文，单源在 engine；
        # 步级化——带当前步 checklist）
        if cur is not None:
            lines.append("  " + engine.selfcheck_hint(cur))
        # §step-engage-prefence S15：前置参与围栏（PreToolUse）提示——零 trace
        # 窗口内非编排工具会被硬 deny，提前告诉模型免它撞墙后困惑。
        # §autocontinue-fence-notice：文案单源在 engine（pass/block 续轮共用）。
        if cur is not None:
            lines.append("  " + engine.engagement_fence_notice(cur))
        # evidence 写法（v2.14 append-trace：AI 定内容，脚本管格式/路径/结构字段；
        # v2.58 标记文本载荷——模型零接触 JSON）
        if project_root is not None:
            # v2.125：载荷路径单源 engine.trace_payload_path（=worktree 根，
            # 绕 .claude 写入保护目录——acceptEdits 下 Edit 旧落点必弹窗）
            payload_path = str(engine.trace_payload_path(project_root, name, state))
            fields_word = (
                getattr(cur, "record_format", "qa") if cur is not None else "qa"
            )
            lines.append(
                "  evidence 记录（record 步必写，两动作——你定内容，脚本管格式）："
            )
            lines.append(
                f"   ① 写载荷到 `{payload_path}`（分节标记文本，只含 purpose 与 "
                f"{fields_word} 内容字段；"
                "kind/major_stage/minor_stage/sub_step/skill 由脚本从 state 自动填，不要写）："
            )
            # v2.27：示例按当前步 record_format 渲染（qa 配对 / statements 陈述集）
            if cur is not None:
                lines.extend(engine.payload_format_hint(cur))
            else:
                lines.extend(engine.payload_format_hint(None))
            lines.append(
                "   ② Bash 落库：`python3 ~/.dl-workflow/dl_flow_engine.py append-trace "
                f"--from-file {payload_path}`"
                "（校验失败当场报错，按报错改载荷重跑。**禁止绕过它手写 evidence jsonl**——"
                "手写 JSON 跨行/转义出错 = trace 隐形，且会被围栏 deny 指回这里）"
            )
            lines.append(
                "   确认/裁决留痕由 /dl 命令自动写（kind=gate），不用手写其它 kind 的记录。"
            )
            lines.append(
                "  落库后输出 `### STEP_DONE: <n>`。gate 校验（end_turn 时 Stop hook 读 evidence 立即判）："
                "当前子步骤需有 sub_step==N 的 skill-trace 且内容达 purpose；"
                "过则推进，block 则当轮返工（返工重新走①②落新行）。"
            )
        if cur_step < total_steps:
            lines.append(
                f"  当前子步骤 {cur_step} 完成时，回复末尾单独一行输出：`### STEP_DONE: {cur_step}`"
            )
        elif node.hold_for_gate:
            # §subphase-hold-gate：末步过门控后推进被扣留，等 /dl gate
            lines.append(
                f"  末子步骤({total_steps})完成时（gate={'自动过' if not node.sub_steps[-1].gate else '校验'}），"
                f"回复末尾单独一行输出：`### STEP_DONE: {total_steps}`"
                "（Stop hook 门控通过后**子阶段门栏扣留**——等用户 /dl gate 放行进下一子阶段，勿输出 SUB_DONE）"
            )
        else:
            lines.append(
                f"  末子步骤({total_steps})完成时（gate={'自动过' if not node.sub_steps[-1].gate else '校验'}），"
                f"回复末尾单独一行输出：`### STEP_DONE: {total_steps}`（Stop hook 推进到下一子阶段，勿输出 SUB_DONE）"
            )
        lines.append(
            "（仅当当前子步骤 purpose 真正达成 + evidence 已写时输出 STEP_DONE；未达成绝不输出）"
        )
    # 子阶段块（仅当前阶段有子阶段时注入）
    if has_sub:
        lines.append(f"- 子阶段(共 {sub_total} 个, 依次完成, 各自动推进到下一子阶段):")
        for j, slabel in enumerate(subs, 1):
            sst = (
                "completed"
                if j < sub_index
                else ("in_progress" if j == sub_index else "pending")
            )
            lines.append(f"  {j}. {slabel} -> {sst}")
        # §orchestration v2：节点有 sub_steps 时用 STEP_DONE（子步骤块已给指令），
        # 不再注入 SUB_DONE/PHASE_DONE 提示（互斥，design §10 风险8）。
        node_has_steps = bool(node and node.sub_steps)
        if not node_has_steps:
            lines.append(
                f"  完成子阶段 1..{sub_total - 1} 各输出: `### SUB_DONE: <n>` (Stop hook 自动推进 sub_index);"
            )
            lines.append(
                f"  末子阶段({sub_total})完成 -> 写阶段产物 + 输出 `### PHASE_DONE: {phase}` (触发该阶段闸门/推进);"
            )
            lines.append(
                "  未走完子阶段直接输出 PHASE_DONE 会被 Stop hook 守卫阻断(强制依次)."
            )

    lines.extend(
        [
            # P0：只留 per-turn 状态数据；建齐/对齐/subject 编号等稳定规则在
            # output-style + phase-rules 双 system-prompt 通道（措辞已统一，commit 5215b63），
            # 此处删指令散文（跨通道重复）。
            "- 任务清单目标状态（镜像同步原生 TaskList；建齐/对齐规则见 output-style 与 phase-rules）:",
            *task_rows,
        ]
    )
    # 完成标记：无子阶段->PHASE_DONE；有子阶段->子1..N-1 用 SUB_DONE，末子阶段(N)用 PHASE_DONE
    # §orchestration v2：有 sub_steps 的节点用 STEP_DONE（子步骤块已给指令），跳过此处。
    if has_sub and not (node and node.sub_steps):
        if sub_index < sub_total:
            lines.append(
                f"当前子阶段 {sub_index}({cur_sub_label})完成时, 回复末尾单独一行输出: `### SUB_DONE: {sub_index}`"
            )
        else:
            lines.append(
                f"末子阶段({sub_total})完成时(写完阶段产物 {rules.get('artifact', '')}), "
                f"回复末尾单独一行输出: `### PHASE_DONE: {phase}`"
            )
        lines.append("（仅当当前子阶段目标真正达成时输出对应标记；未达成绝不输出）")
    elif not has_sub:
        lines.append(f"完成本阶段后，回复末尾单独一行输出: `### PHASE_DONE: {phase}`")
        lines.append(
            "（仅当阶段目标真正达成时输出；闸门阶段不会自动推进，需 /dl gate 放行）"
        )

    # §8.6b：旧的 ### EVIDENCE 推理溯源注入块已移除（用户决策：弃用模型自发记 claim/依赖的溯源系统,
    # 改由 engine.write_gate_verdict 在 gate-pass 写裁决记录,见 dl_flow_engine.py）。
    return "\n".join(lines) + "\n"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        _log_invocation(None, "malformed_stdin")
        return 0
    if not isinstance(payload, dict):
        _log_invocation(None, "non_dict")
        return 0

    cwd = _payload_cwd(payload)
    project_root = _resolve_project_root(cwd)
    prompt = _extract_prompt(payload)

    name = _resolve_workflow_name(cwd)
    if not name:
        _log_invocation(project_root, "no_worktree_cwd", prompt_len=len(prompt))
        return 0  # 不在 worktree 内（普通会话）-> 不注入

    if project_root is None:
        _log_invocation(None, "no_project_root", name=name, prompt_len=len(prompt))
        return 0  # 非 git 项目 -> 不注入

    # plan mode 互斥：拒掉提问本身（exit 2，stderr 给用户看）。
    # 用户是唯一能切模式的人；放进会话只会让模型在 plan mode 里被围栏连环 deny
    # 空转（demo 61482dbe 实录）。fence hook 的 pm=plan 硬拦作 mid-turn 兜底。
    if payload.get("permission_mode") == "plan":
        _log_invocation(
            project_root, "plan_mode_block", name=name, prompt_len=len(prompt)
        )
        sys.stderr.write(
            f"⚠️ 工作流 '{name}' 与 plan mode 互斥（编排协议会被只读探查语义挤掉）。\n"
            "请 shift+tab 切回 default 模式后重新提问。\n"
        )
        return 2

    state = _load_state(project_root, name)
    if not state:
        _log_invocation(project_root, "no_state", name=name, prompt_len=len(prompt))
        return 0  # state 缺失 -> 不注入（可能未走 launcher）
    state = engine.normalize_state(state)

    # §substep-gate-at-stop：子步骤 gate+推进已收口到 Stop hook（evidence hash 触发），
    # 本 hook 只注入当前状态（含推进后的最新 sub_step_index），不再跑 gate。

    # plan mode 互斥警告（demo bf91ca0f：plan mode 只读探查语义挤掉编排协议）。
    # 主防线是上方 exit 2 拒提问；本警告兜底 mid-turn 切换的场景。
    # payload 无 permission_mode 字段 -> None -> 不加警告（防御：不误报）。
    plan_warn = ""
    if payload.get("permission_mode") == "plan":
        plan_warn = (
            "## ⚠️ 当前处于 plan mode\n"
            "plan mode 与工作流编排互斥。不要调用任何工具（会被围栏拒绝）；"
            "直接用文本告知用户：请 shift+tab 切回 default 模式后重新提问，"
            "然后 end_turn 等待。\n\n"
        )

    context = _format_injection(state, project_root)
    if plan_warn:
        context = plan_warn + context
    # v2.35：settings 模板版本落后警告（防静默权限税，症状 R）置注入最前。
    staleness = _settings_staleness_notice(project_root, name)
    if staleness:
        context = staleness + context
    out = json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context,
            }
        },
        ensure_ascii=False,
    )
    sys.stdout.write(out)
    _log_invocation(
        project_root,
        "injected",
        name=name,
        phase=state.get("phase", ""),
        pm=str(payload.get("permission_mode")),  # 观测：payload 是否带 permission_mode
        prompt_len=len(prompt),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
