#!/usr/bin/env python3
"""
PreToolUse(Edit|Write|MultiEdit) 门禁：本会话改第 2 个及以上不同 .py 源码
文件前，须先写过 designs/*.md（H8 design-first 用户级跨项目机械闸门）。

动机：[[troubleshoot-fix-flow]]——排查/修复应走「确认根因方案 → design.md
→ 动手」，但 prompt 级规则（superpowers/CLAUDE.md）是软约束，模型会跳过
（2026-08-03 v2.64-66 连改 dl_flow_engine/nodes/fence 多个 .py 无 design.md、
未确认方案）。正治=堵入口（弱模型优先原则：prompt 软、围栏硬）。

判定逻辑（镜像 codegraph_gate.py H15 模式）：
- 目标：改**已存在的 .py 源码文件**（白名单同 H15：非 .py / test_*.py /
  新建文件 / scripts/check_*.py / designs/ 一律放行）。
- 放行：本会话已写过 designs/*.md；或改的是本会话第 1 个源码文件；或改的是
  本会话已改过的同一文件（单文件迭代）。
- 阻断：本会话已改过 >=1 个不同源码文件、未写过 design.md，现又改另一个
  不同源码文件 -> exit 2 指回「先写 designs/<topic>.md」。

退出码语义（Claude Code hooks 约定）：exit 0 放行；exit 2 阻断（stderr 反馈）。

宁纵勿枉：非 git 项目 / 非 .py / 新建文件 / 留痕缺失 -> 放行。
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def _resolve_file_project_root(file_path: str, cwd: str) -> Path | None:
    """从**被编辑文件**的目录反查 git 项目根（不是会话 cwd）——design.md 应落在
    文件所属仓的 designs/。从主会话改 dl-workflow 文件时 cwd 是主项目，
    用 cwd 会错查主项目 designs/（2026-08-03 用户决议：dl-workflow repo
    本身要拦，design.md 放 ~/.dl-workflow/designs/）。
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
    _fallback.log，历史 DESIGN 记录放行后续所有会话（2026-08-03 v2.67 漏网
    实证，designs/gate-session-isolation-fix-design.md）。"""
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


def _is_existing_source_py(file_path: str, project_root: Path) -> bool:
    """判定是否为需要门禁的目标：已存在的 .py 源码（白名单同 H15）。"""
    p = Path(file_path)
    if p.suffix != ".py":
        return False
    name = p.name
    if name.startswith("test_") or name.endswith("_test.py"):
        return False
    if name.startswith("check_") and "scripts" in p.parts:
        return False
    abs_p = p if p.is_absolute() else (project_root / p)
    try:
        return abs_p.exists()
    except OSError:
        return False


def _session_edits(audit_dir: Path, payload: dict) -> tuple[set[str], bool]:
    """读本会话 audit log，返回 (已编辑的源码文件集合, 是否已写 design.md)。"""
    log = audit_dir / f"{_session_id(payload)}.log"
    srcs: set[str] = set()
    has_design = False
    if not log.exists():
        return srcs, has_design
    try:
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            _, kind, fp = parts
            if kind == "SRC":
                srcs.add(fp)
            elif kind == "DESIGN":
                has_design = True
    except OSError:
        pass
    return srcs, has_design


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0  # 解析失败不阻断（宁纵勿枉业务编辑）

    file_path = (payload.get("tool_input") or {}).get("file_path", "")
    if not file_path:
        return 0

    # 工作流会话（dl <name> worktree）跳过——工作流有自己的 design 流程
    # （plan:1 render-artifact 产 design.md + 门控），且其 design.md 由脚本
    # 写（非 Edit/Write 工具），本门禁的 audit 看不到，会误拦 execute 阶段。
    if _workflow_name(_payload_cwd(payload)) is not None:
        return 0

    project_root = _resolve_file_project_root(file_path, _payload_cwd(payload))
    if project_root is None:
        return 0  # 非 git 项目 -> 放行

    if not _is_existing_source_py(file_path, project_root):
        return 0  # 白名单跳过（非 .py / test / 新建文件 / check_*.py）

    audit_dir = project_root / ".claude" / ".design_audit"
    srcs, has_design = _session_edits(audit_dir, payload)

    if has_design:
        return 0  # 本会话已写 design.md -> 多文件改动已解锁
    if file_path in srcs:
        return 0  # 同一文件迭代 -> 单文件工作，放行
    if len(srcs) < 1:
        return 0  # 本会话第 1 个源码文件 -> 放行（H8 只管 2+ 文件）

    # 阻断：本会话第 2 个及以上不同源码文件，且无 design.md
    hint = (
        f"[design-first gate] 阻断：本会话已改过源码 {sorted(srcs)}，现又改 "
        f"{file_path}——多文件改动须先写设计文档（H8 / [[troubleshoot-fix-flow]]）。\n"
        f"  流程：确认根因方案（AskUserQuestion/用户拍板）-> 写 "
        f"{project_root}/designs/<topic>.md -> 再动手改代码。\n"
        f"  若本轮工作已有 design.md：在其中补一行当前改动范围即可留痕解锁。\n"
        f"  单文件修改不受此门禁影响（改回同一文件即放行）。"
    )
    sys.stderr.write(hint + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
