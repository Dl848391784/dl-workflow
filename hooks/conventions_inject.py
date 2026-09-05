#!/usr/bin/env python3
"""
UserPromptSubmit hook：注入项目约定蒸馏瘦档（designs/setup-installer-design.md）。

集中化版本：本文件由项目 settings.json 以绝对路径引用，一份服务任意项目；
项目根从 hook payload 解析（payload.cwd → CLAUDE_PROJECT_DIR → 进程 cwd）。

注入策略：仅在有活跃漂移点或索引过期（>5 commit）时注入——无漂移无仲裁需求，
完整约定深查走 scripts/cvx.py（避免每次 prompt 静态噪音）。
容错：db 缺失/查询失败/stdin 异常 -> exit 0 静默不注入，UserPromptSubmit 永不阻断。
"""

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


MAX_DRIFT = 5
STALE_COMMITS = 5


def _project_root(payload: dict) -> Path:
    """项目根解析：payload.cwd → CLAUDE_PROJECT_DIR → 进程 cwd，各自经 git rev-parse 反查。"""
    candidates = [
        payload.get("cwd"),
        os.environ.get("CLAUDE_PROJECT_DIR"),
        str(Path.cwd()),
    ]
    for cand in candidates:
        if not isinstance(cand, str) or not cand:
            continue
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=cand,
                capture_output=True,
                text=True,
            )
        except OSError:
            continue
        if proc.returncode == 0 and proc.stdout.strip():
            return Path(proc.stdout.strip())
    return Path.cwd()


def _log(log_path: Path, status: str) -> None:
    try:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{ts}|{status}\n")
    except OSError:
        pass


def _load(conn: sqlite3.Connection) -> tuple[list[tuple], int]:
    """返回 (漂移记录 ≤MAX_DRIFT, 约定总数)。"""
    total = conn.execute("SELECT COUNT(*) FROM conventions").fetchone()[0]
    drifts = conn.execute(
        "SELECT dimension, subject, statement, sample_size, compliance FROM conventions"
        " WHERE drift = 1 ORDER BY dimension, id LIMIT ?",
        (MAX_DRIFT,),
    ).fetchall()
    return drifts, total


def _commit_gap(root: Path, base_hash: str) -> int | None:
    """db 生成点落后 HEAD 多少 commit；无法判定返回 None。"""
    if not base_hash:
        return None
    try:
        proc = subprocess.run(
            ["git", "rev-list", "--count", f"{base_hash}..HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return int(proc.stdout.strip())
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        ValueError,
        OSError,
    ):
        return None


def _format(drifts: list[tuple], total: int, gap: int | None) -> str | None:
    """无漂移且未过期 -> None（不注入）；否则生成瘦档文本。"""
    stale = gap is not None and gap > STALE_COMMITS
    if not drifts and not stale:
        return None
    lines = [
        "## 项目约定蒸馏（瘦档；文档与实证漂移并列呈证，动手前确认权威，不擅自站队）"
    ]
    for dim, subject, statement, n, comp in drifts:
        comp_s = "?" if comp is None else f"{comp:.2f}"
        lines.append(f"- ⚠️ [{dim}] {subject} :: {statement}（n={n}, 合规率={comp_s}）")
    if stale:
        lines.append(
            f"[conventions] 索引落后 {gap} 个 commit（>{STALE_COMMITS}），约定可能过期。"
        )
    lines.append(
        f"[conventions] 共 {total} 条约定；深查：python3 scripts/cvx.py query <主题> | drift"
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            payload = {}
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        payload = {}  # 解析失败静默不注入（永不阻断；无 cwd 落到进程 cwd）

    root = _project_root(payload)
    conv_db = root / ".conventions" / "conventions.db"
    inject_log = root / ".claude" / ".cv_inject.log"

    if not conv_db.exists():
        _log(inject_log, "no_db")
        return 0
    try:
        conn = sqlite3.connect(f"file:{conv_db}?mode=ro", uri=True)
        drifts, total = _load(conn)
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'commit_hash'"
        ).fetchone()
        conn.close()
    except sqlite3.Error:
        _log(inject_log, "query_error")
        return 0
    gap = _commit_gap(root, row[0] if row else "")
    context = _format(drifts, total, gap)
    if context is None:
        _log(inject_log, "no_drift")
        return 0
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
    _log(inject_log, f"injected drifts={len(drifts)} gap={gap}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
