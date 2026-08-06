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


def _resolve_main_root(d: Path) -> tuple[Path | None, bool]:
    """d 所属 git 仓的**主树**根 + 是否 linked worktree（v2.120，与
    codegraph_gate.py 同构）——audit 落账与 gate 读取必须同一根：开发
    worktree 会话的查询留痕落主树，gate 读主树才读得到。"""
    try:
        top = subprocess.run(
            ["git", "-C", str(d), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if top.returncode != 0 or not top.stdout.strip():
            return None, False
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
            return toplevel, False
        common_p = Path(common.stdout.strip())
        if not common_p.is_absolute():
            common_p = (d / common_p).resolve()
        if common_p == (toplevel / ".git").resolve():
            return toplevel, False
        return common_p.parent, True
    except (subprocess.TimeoutExpired, OSError):
        return None, False


def _payload_cwd(payload: dict) -> str:
    for key in ("cwd", "working_dir", "current_dir"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            return val
    return str(Path.cwd())


_CD_RE = re.compile(r"(?:^|&&|\|\||;)\s*cd\s+([^&;|]+)")


def _cd_target(command: str, codegraph_pos: int, cwd: str) -> Path:
    """codegraph 子命令前最后一个 `cd <dir>` 的目标（v2.120）。

    hook 看不到命令内 cd 的效果，但 `cd X && codegraph ...` 是解锁指路
    的固定写法（gate 阻断文案即此形）——查询实际打在 X 的 db 上，留痕
    须归 X 所在仓（跨仓会话：会话开在 A 仓、`cd ~/.dl-workflow && codegraph`
    解锁 dl-workflow 编辑）。解析失败/非绝对路径 -> 回落会话 cwd
    （宁纵勿枉，不发明路径）。
    """
    target = None
    for m in _CD_RE.finditer(command[:codegraph_pos]):
        target = m.group(1).strip().strip("'\"")
    if not target or not target.startswith("/"):
        return Path(cwd)
    p = Path(target)
    return p if p.is_dir() else Path(cwd)


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

    # v2.120：归属 = codegraph 前导 cd 目标（解锁指路的固定写法）或会话
    # cwd，再解析到**主树**——开发 worktree 会话的留痕落主树，gate 读主树
    # 才读得到（gate/audit 必须同一根，否则变相死锁）。
    rest = _CMD_RE.search(command or "")
    base = _cd_target(command, rest.start() if rest else 0, _payload_cwd(payload))
    project_root, _ = _resolve_main_root(base)
    if project_root is None:
        return 0  # 非 git 项目 -> 不留痕（无处可留）

    audit_dir = project_root / ".claude" / ".cg_audit"

    # 子命令后的首个 token 作"symbol/args"近似（够审计用，不追求精确解析）
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
