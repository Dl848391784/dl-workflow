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


# 5 阶段顺序（与 wf-lib.sh WF_PHASES 一致；hook 独立持有，避免 source bash）
PHASES = ["understand", "plan", "execute", "review", "evolution"]

# 阶段中文显示名（仅显示用；逻辑层 state/PHASE_DONE 标记/jump 参数仍用英文标识）
PHASE_LABELS = {
    "understand": "理解和求证问题",
    "plan": "生成执行计划",
    "execute": "执行",
    "review": "审核结果",
    "evolution": "进化",
}

# 各阶段规则（注入给模型的"允许/禁止/产物/推进"四要素）
PHASE_RULES = {
    "understand": {
        "goal": "理清真实问题（问题背后要解决的本质，非字面请求）",
        "allow": "Read/Grep/Glob/codegraph 查证/AskUserQuestion 澄清",
        "deny": "Edit/Write 任何源码",
        "artifact": "understand.md（真实问题重述 + 边界 + 成功标准）",
        "advance": "闸门：完成后需用户 /wf gate 放行才进 plan",
    },
    "plan": {
        "goal": "针对真实问题设计实现方案",
        "allow": "understand 的工具 + 起草 design.md(H8)",
        "deny": "改源码",
        "artifact": "plan.md（方案 + 步骤 + 验证方法）",
        "advance": "闸门：完成后需用户 /wf gate 放行才进 execute",
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
        "artifact": "review.md（结论 + 证据）",
        "advance": "自动推进到 evolution（无闸门）",
    },
    "evolution": {
        "goal": "沉淀经验（写 memory 事实/更新 skill/补 design）",
        "allow": "写 memory/调 skill/补 design",
        "deny": "—",
        "artifact": "evolution.md + memory 写入",
        "advance": "终结（输出 PHASE_DONE: evolution 后工作流结束）",
    },
}


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
) -> None:
    """留痕 UserPromptSubmit 触发（观测性）。失败静默。

    project_root 缺失时不留痕（无处写；此时 hook 也已 return，无害）。
    """
    if project_root is None:
        return
    log = project_root / ".claude" / ".wf_phase.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"{ts}|{status}|wf={name}|phase={phase}|prompt_len={prompt_len}\n")
    except OSError:
        pass


def _format_injection(state: dict) -> str:
    """格式化阶段注入文本（当前阶段 + 规则四要素 + 完成标记格式）。"""
    name = state.get("name", "?")
    phase = state.get("phase", "understand")
    idx = state.get("index", 1)
    gate = state.get("gate", "pending")
    rules = PHASE_RULES.get(phase, {})
    try:
        total = len(PHASES)
    except Exception:
        total = 5
    # 任务清单目标状态（镜像 state.json 当前 index；供模型同步原生 TaskList）
    task_rows = []
    for i, p in enumerate(PHASES, 1):
        lbl = PHASE_LABELS.get(p, p)
        st = "completed" if i < idx else ("in_progress" if i == idx else "pending")
        task_rows.append(f"  {i}. {lbl} -> {st}")

    lines = [
        "## WORKFLOW 当前阶段",
        f"工作流: {name} | 阶段: **{PHASE_LABELS.get(phase, phase)}** [{idx}/{total}] | gate: {gate}",
        f"- 目标: {rules.get('goal', '')}",
        f"- 允许: {rules.get('allow', '')}",
        f"- 禁止: {rules.get('deny', '')}",
        f"- 阶段产物: {rules.get('artifact', '')}",
        f"- 推进: {rules.get('advance', '')}",
        "- 任务清单(原生 TaskList, 置顶常驻): 维护 5 个阶段任务作常驻进度清单, 状态须镜像当前 index:",
        *task_rows,
        "  首轮或续接后缺失时 TaskCreate 建齐 5 个(subject=各阶段中文名)并按上设状态;",
        "  其后每轮若 in_progress 任务与当前阶段不符则 TaskUpdate 对齐(旧->completed, 当前->in_progress);",
        "  5 个阶段任务全程保留勿删; execute 阶段工作子任务可追加在下方, 勿动这 5 个。",
        "完成本阶段后，回复末尾单独一行输出: `### PHASE_DONE: " + phase + "`",
        "（仅当阶段目标真正达成时输出；闸门阶段不会自动推进，需 /wf gate 放行）",
    ]
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

    state = _load_state(project_root, name)
    if not state:
        _log_invocation(project_root, "no_state", name=name, prompt_len=len(prompt))
        return 0  # state 缺失 -> 不注入（可能未走 launcher）

    context = _format_injection(state)
    out = json.dumps(
        {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}},
        ensure_ascii=False,
    )
    sys.stdout.write(out)
    _log_invocation(project_root, "injected", name=name, phase=state.get("phase", ""), prompt_len=len(prompt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
