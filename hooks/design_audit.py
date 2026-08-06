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


def _resolve_roots(d: Path) -> tuple[Path | None, Path | None, bool]:
    """d 所属 git 仓的 (工作树顶, **主树**根, 是否 linked worktree)（v2.120，
    与 design_gate.py 同构）。kind 判定（designs/ 位置）用工作树顶——
    design.md 写在当前工作树随分支合并；audit 落账用主树根——gate 读
    主树，audit/gate 必须同一根否则串号/变相死锁。相对路径先对会话
    cwd 解析由调用方完成。"""
    try:
        top = subprocess.run(
            ["git", "-C", str(d), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if top.returncode != 0 or not top.stdout.strip():
            return None, None, False
        toplevel = Path(top.stdout.strip())
        # --path-format=absolute：relative 输出是相对 -C 目录的（如 ../.git），
        # 错相对基准会串号到仓外（2026-08-06 测试实测 /tmp/.git 事故）
        common = subprocess.run(
            [
                "git",
                "-C",
                str(d),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if common.returncode != 0 or not common.stdout.strip():
            return toplevel, toplevel, False
        common_p = Path(common.stdout.strip())
        if not common_p.is_absolute():
            common_p = (d / common_p).resolve()
        if common_p == (toplevel / ".git").resolve():
            return toplevel, toplevel, False
        return toplevel, common_p.parent, True
    except (subprocess.TimeoutExpired, OSError):
        return None, None, False


def _is_workflow_file(path: Path) -> bool:
    """路径含 .claude/worktrees/<name> 段 -> dl 工作流 worktree 内文件
    （v2.120 按被编辑文件判定，原按会话 cwd）——gate 侧同样跳过
    （工作流有自己的 design 流程），audit 不留痕避免污染主会话判断。"""
    parts = path.parts
    for i, p in enumerate(parts):
        if p == ".claude" and i + 1 < len(parts) and parts[i + 1] == "worktrees":
            return True
    return False


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

    # v2.120：跳过按被编辑文件（原按会话 cwd）；kind 判定用工作树顶
    # （design.md 写当前工作树 designs/ 随分支合并），audit 落主树根
    # （gate 读主树——audit/gate 同一根）。
    cwd = _payload_cwd(payload)
    fp = Path(file_path)
    if not fp.is_absolute():
        fp = Path(cwd) / fp
    if _is_workflow_file(fp):
        return 0
    toplevel, main_root, _ = _resolve_roots(fp if fp.is_dir() else fp.parent)
    if main_root is None:
        return 0

    kind = None
    if _is_design_md(file_path, toplevel):
        kind = "DESIGN"
    elif _is_source_py(file_path, toplevel):
        kind = "SRC"
    if kind is None:
        return 0  # 非源码/非设计文档，不留痕

    audit_dir = main_root / ".claude" / ".design_audit"
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
