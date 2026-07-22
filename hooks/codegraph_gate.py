#!/usr/bin/env python3
"""
PreToolUse(Edit|Write) 门禁：改已有 .py 源码前强制先查 codegraph。

对应设计 designs/codegraph_enforcement_gate_design.md（H15）。
判定逻辑见 design §How。档 3 核心机制。

退出码语义（Claude Code hooks 约定）：
- exit 0：放行；stdout 可注入提示/影响面上下文
- exit 2：阻断；stderr 反馈给 agent

弱门禁边界（design §判定取舍）：
- 挡"零 codegraph 查询就改源码"
- 不挡"查错 symbol"（靠档 1 证据约定 + 档 2 commit 取证补缝）

**dl-workflow 版本**：hook 装到 ~/.claude/hooks/（用户级），不再假设
`__file__.parents[2]` 是项目根。改用 payload 里的 cwd -> git 反查项目根。
无项目根 -> exit 0 放行（宁纵勿枉，非 git 项目也别卡）。
"""

import json
import os
import subprocess
import sys
from pathlib import Path


CODEGRAPH_CLI = "/home/admin/.npm-global/bin/codegraph"

# 留痕的有效 codegraph 子命令（audit.py 写，gate.py 读）
TRACKED_SUBCOMMANDS = ("callers", "callees", "impact", "affected", "context", "query")

# 新鲜度阈值（小时）；超期只警告不阻断，避免卡死
STALE_HOURS = 72


def _resolve_project_root(payload: dict) -> Path | None:
    """从 hook payload 的 cwd（或进程 cwd）反查 git 项目根。"""
    cwd = ""
    for key in ("cwd", "working_dir", "current_dir"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            cwd = val
            break
    if not cwd:
        cwd = str(Path.cwd())
    try:
        res = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            return Path(res.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def _session_id() -> str:
    """会话标识：优先环境变量，回退固定文件（仍能记录本进程序列）。"""
    sid = os.environ.get("CLAUDE_SESSION_ID", "").strip()
    return sid or "_fallback"


def _has_query_this_session(audit_dir: Path) -> bool:
    """本会话是否已留痕过任何 codegraph 结构查询。"""
    log = audit_dir / f"{_session_id()}.log"
    if not log.exists():
        return False
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(f"|{sc}|" in text for sc in TRACKED_SUBCOMMANDS)


def _is_existing_source_py(file_path: str, project_root: Path) -> bool:
    """判定是否为需要门禁的目标：已存在的 .py 源码。

    白名单跳过（design §How 步骤 1）：
    - 非 .py
    - test_*.py / *_test.py（测试，非业务源码）
    - 新建文件（仓库无此 path）
    - scripts/check_*.py（检查器自身，改动频繁且非业务符号）
    """
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


def _freshness_warning(codegraph_db: Path) -> str:
    """索引新鲜度检查（design §How 步骤 2）；超 72h 返回警告行，否则空。"""
    if not codegraph_db.exists():
        return "[codegraph] 警告：.codegraph/codegraph.db 不存在，结构查询不可用"
    try:
        res = subprocess.run(
            [
                "sqlite3",
                str(codegraph_db),
                "SELECT MAX(indexed_at) FROM files;",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode != 0 or not res.stdout.strip():
            return ""
        max_ts_ms = int(res.stdout.strip())
        res2 = subprocess.run(
            ["date", "+%s"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        now_s = int(res2.stdout.strip())
        age_h = (now_s - max_ts_ms / 1000) / 3600
        if age_h > STALE_HOURS:
            return (
                f"[codegraph] 警告：索引 {age_h:.0f}h 前更新（> {STALE_HOURS}h），"
                f"结构可能过期。改前建议 `codegraph sync` 刷新。"
            )
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return ""
    return ""


def _affected_context(file_path: str, project_root: Path) -> str:
    """查过则跑 `codegraph affected <file>` 注入影响面（补"自动注入"缺失）。"""
    try:
        res = subprocess.run(
            [CODEGRAPH_CLI, "affected", "-q", file_path],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(project_root),
        )
        out = res.stdout.strip()
        if res.returncode == 0 and out:
            return f"[codegraph] 改 {file_path} 可能影响测试：\n{out}"
    except (subprocess.TimeoutExpired, OSError):
        pass
    return ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0  # 解析失败不阻断（宁纵勿枉业务编辑）

    file_path = (payload.get("tool_input") or {}).get("file_path", "")
    if not file_path:
        return 0

    project_root = _resolve_project_root(payload)
    if project_root is None:
        return 0  # 非 git 项目 -> 放行（无项目 = 无 codegraph db = 无门禁意义）

    if not _is_existing_source_py(file_path, project_root):
        return 0  # 白名单跳过

    audit_dir = project_root / ".claude" / ".cg_audit"
    codegraph_db = project_root / ".codegraph" / "codegraph.db"

    warns = []
    fw = _freshness_warning(codegraph_db)
    if fw:
        warns.append(fw)

    if _has_query_this_session(audit_dir):
        # 放行：本会话已查过结构。注入影响面（若有）。
        ctx = _affected_context(file_path, project_root)
        out_parts = warns + ([ctx] if ctx else [])
        if out_parts:
            sys.stdout.write("\n".join(out_parts) + "\n")
        return 0

    # 阻断：零查询就改源码
    hint = (
        f"[codegraph gate] 阻断：改已有源码 {file_path} 前需先查 codegraph（H15）。\n"
        f"  跑一次：`codegraph impact <symbol>` 或 `codegraph callers <symbol>` "
        f"或 `codegraph affected {file_path}`，审计留痕后即可放行。\n"
        f"  纯注释/格式改动：跑一次上述命令即可（不查结构不许改是设计目的）。\n"
        f"  {fw or '索引新鲜度正常。'}"
    )
    sys.stderr.write(hint + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
