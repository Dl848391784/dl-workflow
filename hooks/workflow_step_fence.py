#!/usr/bin/env python3
"""
PreToolUse hook：子步骤围栏（§substep-gate-at-stop S10）。

把「写完 evidence 后必须 STEP_DONE + end_turn」从文案约束变硬约束：
当前子步骤有「已写 trace 但未经 Stop 门控判决」（latest_trace_sha1 ≠
last_judged_trace 游标）时，deny 一切工具调用——模型唯一出路是输出
### STEP_DONE 并 end_turn，等 Stop hook 判定（过→进下一步 / block→当轮返工）。

开关：state.enforce_step_fence（默认 true；/wf fence on|off，hook 实时读
state 无需重启）。围栏与门控共用游标，判完（pass/block 都记游标）即自动开。

容错：非 worktree / 无 state / 无 sub_steps / 无未判决 trace -> exit 0 静默放行。
deny 留痕 <project>/.claude/.wf_fence.log（观测性）。
"""

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

_DLWF_ROOT = Path(__file__).resolve().parents[1]  # ~/.dl-workflow/
_spec = importlib.util.spec_from_file_location(
    "dl_flow_engine", _DLWF_ROOT / "dl-flow-engine.py"
)
engine = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["dl_flow_engine"] = engine  # dataclass 探测类型注解要查此表
_spec.loader.exec_module(engine)  # type: ignore[union-attr]


def _resolve_project_root(cwd: str) -> Path | None:
    """worktree 内 cwd -> git --git-common-dir 反查主 repo 根（同 workflow_phase）。

    --git-common-dir 可能返回相对路径（如 ../../../.git 或 .git）——
    相对路径相对 `-C` 目录解析，不是相对 hook 进程 cwd。
    """
    try:
        r = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    p = Path(r.stdout.strip())
    if not p.is_absolute():
        p = (Path(cwd) / p).resolve()
    if p.name == ".git":
        return p.parent
    return None


def _workflow_name(cwd: str) -> str | None:
    """worktree 路径含 .claude/worktrees/<name> -> name；否则 None。"""
    parts = Path(cwd).parts
    for i, p in enumerate(parts):
        if p == "worktrees" and i + 1 < len(parts):
            return parts[i + 1]
    return None


def _log_deny(project_root: Path, name: str, step: int, tool: str) -> None:
    """deny 留痕（观测性）。失败静默。"""
    try:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        with (project_root / ".claude" / ".wf_fence.log").open(
            "a", encoding="utf-8"
        ) as f:
            f.write(f"{ts}|fence_deny|wf={name}|step={step}|tool={tool}\n")
    except OSError:
        pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    cwd = payload.get("cwd") or ""
    name = _workflow_name(cwd)
    if not name:
        return 0  # 非工作流会话 -> 放行
    project_root = _resolve_project_root(cwd)
    if project_root is None:
        return 0
    step = engine.pending_unjudged_step(project_root, name)
    if step is None:
        return 0  # 无未判决 trace（或围栏已 /wf fence off）-> 放行
    tool = str(payload.get("tool_name", "?"))
    _log_deny(project_root, name, step, tool)
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"子步骤 {step} 已写 evidence，正等待 Stop 门控判决。\n"
                "禁止继续工具调用（含为下一子步骤探查）。\n"
                f"唯一正确动作：输出 ### STEP_DONE: {step} 并 end_turn；"
                "门控判定后（过→进下一步 / block→当轮返工）再继续。\n"
                "（此硬约束可用 /wf fence off 关闭，回文案约束）"
            ),
        }
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
