#!/usr/bin/env python3
"""
PostToolUse(Edit|Write|MultiEdit) 留痕：记录本会话编辑过的 .py 源码文件 +
写过的 designs/*.md 到会话 audit log。

对应流程 [[troubleshoot-fix-flow]]（确认根因方案 → design.md → 动手）的
机械闸门（H8 design-first 用户级跨项目版）。gate.py 读本 log 判断
「本会话第 2 个不同源码文件前是否已写 design.md」。

只留痕，永不阻断（exit 0）。

镜像 codegraph_audit.py（H15）模式：hook 装到 ~/.claude/hooks/（用户级），
payload.cwd -> git 反查项目根；非 git 项目 -> 不留痕。
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _resolve_file_project_root(file_path: str, cwd: str) -> Path | None:
    """从**被编辑文件**的目录反查 git 项目根（不是会话 cwd）——audit 与 gate 必须
    同一 project_root，否则留痕落主项目、判断读 dl-workflow（或反之）串号。
    相对路径先对会话 cwd 解析（真实文件在 cwd/<rel>）。"""
    p = Path(file_path)
    if not p.is_absolute():
        p = Path(cwd) / p
    d = p if p.is_dir() else p.parent
    try:
        res = subprocess.run(
            ["git", "-C", str(d), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            return Path(res.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def _session_id(payload: dict) -> str:
    """会话标识（v2.69）：payload session_id（hooks 规范公共字段，真源）→
    transcript_path 文件名 stem（双保险）→ env CLAUDE_SESSION_ID（向后兼容）
    → "_fallback"。旧版只读 env，而 hook 环境从未注入该变量——所有会话塌缩
    _fallback.log 跨会话共享留痕（2026-08-03 v2.67 漏网实证，
    designs/gate-session-isolation-fix-design.md）。"""
    sid = str(payload.get("session_id") or "").strip()
    if sid:
        return sid
    tp = str(payload.get("transcript_path") or "").strip()
    if tp:
        stem = Path(tp).stem
        if stem:
            return stem
    sid = os.environ.get("CLAUDE_SESSION_ID", "").strip()
    return sid or "_fallback"


def _payload_cwd(payload: dict) -> str:
    for key in ("cwd", "working_dir", "current_dir"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            return val
    return str(Path.cwd())


def _workflow_name(cwd: str) -> str | None:
    """worktree 路径含 .claude/worktrees/<name> -> name；否则 None。"""
    parts = Path(cwd).parts
    for i, p in enumerate(parts):
        if p == "worktrees" and i + 1 < len(parts):
            return parts[i + 1]
    return None


def _is_source_py(file_path: str, project_root: Path) -> bool:
    """判定是否为需留痕的 .py 源码（白名单同 H15 gate，但含新建文件——
    audit 只负责记账，新建与否由 gate 侧另行判断）。"""
    p = Path(file_path)
    if p.suffix != ".py":
        return False
    name = p.name
    if name.startswith("test_") or name.endswith("_test.py"):
        return False
    if name.startswith("check_") and "scripts" in p.parts:
        return False
    return True


def _is_design_md(file_path: str, project_root: Path) -> bool:
    """判定是否为 designs/ 下的 .md（设计文档）。"""
    p = Path(file_path)
    if p.suffix != ".md":
        return False
    abs_p = p if p.is_absolute() else (project_root / p)
    try:
        abs_p = abs_p.resolve()
        return abs_p.parent == (project_root / "designs").resolve()
    except OSError:
        return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0

    file_path = (payload.get("tool_input") or {}).get("file_path", "")
    if not file_path:
        return 0

    # 工作流会话（dl <name> worktree）跳过——gate 侧同样跳过（工作流有自己的
    # design 流程），audit 不留痕避免污染主会话判断。
    if _workflow_name(_payload_cwd(payload)) is not None:
        return 0

    project_root = _resolve_file_project_root(file_path, _payload_cwd(payload))
    if project_root is None:
        return 0

    kind = None
    if _is_design_md(file_path, project_root):
        kind = "DESIGN"
    elif _is_source_py(file_path, project_root):
        kind = "SRC"
    if kind is None:
        return 0  # 非源码/非设计文档，不留痕

    audit_dir = project_root / ".claude" / ".design_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    log = audit_dir / f"{_session_id(payload)}.log"
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with log.open("a", encoding="utf-8") as f:
            f.write(f"{ts}|{kind}|{file_path}\n")
    except OSError:
        return 0  # 留痕失败不阻断业务编辑（宁纵勿枉）
    return 0


if __name__ == "__main__":
    sys.exit(main())
