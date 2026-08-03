#!/usr/bin/env python3
"""
PostToolUse(Bash) 留痕：记录每次 codegraph 结构查询到会话 audit log。

对应设计 designs/codegraph_enforcement_gate_design.md（H15）。
gate.py 读本 log 判断"本会话是否查过结构"。

只留痕，永不阻断（exit 0）。

**dl-workflow 版本**：hook 装到 ~/.claude/hooks/（用户级），不再假设
`__file__.parents[2]` 是项目根。改用 payload 里的 cwd -> git 反查项目根。
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


TRACKED_SUBCOMMANDS = ("callers", "callees", "impact", "affected", "context", "query")

# 匹配 `codegraph <subcmd> ...`（容忍前导路径/环境变量，如 /home/.../codegraph）
_CMD_RE = re.compile(
    r"(?:^|\s)(?:[\w/.-]+/)?codegraph\s+(" + "|".join(TRACKED_SUBCOMMANDS) + r")\b",
)


def _resolve_project_root(payload: dict) -> Path | None:
    """从 hook payload 的 cwd（或进程 cwd）反查 git 项目根。

    优先级：
    1. payload.cwd/working_dir/current_dir -> git rev-parse --show-toplevel
    2. Path.cwd() -> 同上
    3. 全失败返回 None
    """
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


def _session_id(payload: dict) -> str:
    """会话标识（v2.69）：payload session_id（真源）→ transcript_path 文件名
    stem → env CLAUDE_SESSION_ID（向后兼容）→ "_fallback"。旧版只读 env 而
    hook 环境从未注入——所有会话塌缩 _fallback.log（
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


def _parse_subcmd(command: str) -> str | None:
    """从命令字符串提取首个被留痕的 codegraph 子命令，无则 None。"""
    m = _CMD_RE.search(command or "")
    return m.group(1) if m else None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0

    command = (payload.get("tool_input") or {}).get("command", "")
    subcmd = _parse_subcmd(command)
    if not subcmd:
        return 0  # 非 codegraph 结构查询，不留痕

    project_root = _resolve_project_root(payload)
    if project_root is None:
        return 0  # 非 git 项目 -> 不留痕（无处可留）

    audit_dir = project_root / ".claude" / ".cg_audit"

    # 子命令后的首个 token 作"symbol/args"近似（够审计用，不追求精确解析）
    rest = _CMD_RE.search(command or "")
    tail = ""
    if rest:
        after = command[rest.end() :].strip()
        tail = after.split()[0] if after else ""

    audit_dir.mkdir(parents=True, exist_ok=True)
    log = audit_dir / f"{_session_id(payload)}.log"
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = f"{ts}|{subcmd}|{tail}\n"
    try:
        with log.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        return 0  # 留痕失败不阻断 Bash（宁纵勿枉业务命令）
    return 0


if __name__ == "__main__":
    sys.exit(main())
