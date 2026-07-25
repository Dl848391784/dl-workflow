#!/usr/bin/env python3
"""
PreToolUse hook：子步骤围栏（S10）+ 阶段写权限围栏（S11）。

S10：把「写完 evidence 后必须 STEP_DONE + end_turn」从文案约束变硬约束：
当前子步骤有「已写 trace 但未经 Stop 门控判决」（latest_trace_sha1 ≠
last_judged_trace 游标）时，deny 一切工具调用——模型唯一出路是输出
### STEP_DONE 并 end_turn，等 Stop hook 判定（过→进下一步 / block→当轮返工）。

S11：把「understand/plan 禁改源码、review 禁改实现」从文案约束变硬约束：
Edit/Write/MultiEdit/NotebookEdit 目标路径不在该 phase 白名单
（engine.phase_write_denial 单源）时 deny。已知限制：Bash 写（重定向/
sed -i）无法可靠判定写意图，不在围栏内（phase-rules 文案仍禁）。

开关：state.enforce_step_fence / enforce_phase_fence（默认 true；
/wf fence on|off 统一切换，hook 实时读 state 无需重启）。

容错：非 worktree / 无 state -> exit 0 静默放行。
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


def _log_deny(project_root: Path, name: str, kind: str, detail: str) -> None:
    """deny 留痕（观测性）。失败静默。"""
    try:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        with (project_root / ".claude" / ".wf_fence.log").open(
            "a", encoding="utf-8"
        ) as f:
            f.write(f"{ts}|{kind}|wf={name}|{detail}\n")
    except OSError:
        pass


# S11：结构化写工具（Bash 写无法可靠判定写意图，不在围栏内——见设计文档 S11）
_WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def _deny(reason: str) -> int:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    return 0


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
    tool = str(payload.get("tool_name", "?"))

    # ---- plan mode 互斥硬拦：plan mode 与工作流编排冲突（只读探查语义挤掉编排协议，
    # demo 会话 bf91ca0f 实录）。plan mode 下 deny 一切工具调用（仅放行 ExitPlanMode），
    # 让 plan mode 在工作流会话里物理上没法干活 -> 模型只能退出。payload 无
    # permission_mode 字段时 get 返回 None -> 不拦（防御：字段缺失不误判）。
    if payload.get("permission_mode") == "plan" and tool != "ExitPlanMode":
        _log_deny(project_root, name, "plan_mode_deny", f"tool={tool}")
        return _deny(
            "当前处于 plan mode，与工作流编排互斥（plan mode 的只读探查语义会挤掉"
            "编排协议：横幅/TaskList/define-problem/子步骤）。\n"
            "唯一正确动作：调用 ExitPlanMode 退出 plan mode（或请用户 shift+tab "
            "切回 default），退出后按注入的子步骤清单重新开始编排。"
        )

    # ---- S11 phase 写权限围栏：写工具目标路径须在该 phase 白名单内 ----
    if tool in _WRITE_TOOLS:
        ti = payload.get("tool_input") or {}
        fp = ti.get("file_path") or ti.get("notebook_path") or ""
        if fp:
            if not Path(fp).is_absolute():
                fp = str((Path(cwd) / fp).resolve())
            reason = engine.phase_write_denial(project_root, name, fp)
            if reason:
                _log_deny(project_root, name, "phase_fence_deny", f"tool={tool}|path={fp}")
                return _deny(reason + "\n（此硬约束可用 /wf fence off 关闭，回文案约束）")

    # ---- S10 子步骤围栏：有未判决 trace -> 禁一切工具调用，逼 STEP_DONE+end_turn ----
    step = engine.pending_unjudged_step(project_root, name)
    if step is None:
        return 0  # 无未判决 trace（或围栏已 /wf fence off）-> 放行
    _log_deny(project_root, name, "fence_deny", f"step={step}|tool={tool}")
    return _deny(
        f"子步骤 {step} 已写 evidence，正等待 Stop 门控判决。\n"
        "禁止继续工具调用（含为下一子步骤探查）。\n"
        f"唯一正确动作：输出 ### STEP_DONE: {step} 并 end_turn；"
        "门控判定后（过→进下一步 / block→当轮返工）再继续。\n"
        "（此硬约束可用 /wf fence off 关闭，回文案约束）"
    )


if __name__ == "__main__":
    sys.exit(main())
