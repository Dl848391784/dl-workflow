#!/usr/bin/env python3
"""
UserPromptSubmit hook：注入项目约定蒸馏瘦档（designs/setup-installer-design.md）。

集中化版本：本文件由项目 settings.json 以绝对路径引用，一份服务任意项目；
项目根从 hook payload 解析（payload.cwd → CLAUDE_PROJECT_DIR → 进程 cwd）。

注入策略：仅在有活跃漂移点、inferred 候选规范或索引过期（>5 commit）时注入——
三者皆无则无仲裁需求，完整约定深查走 ~/.dl-workflow/bin/cvx.py（避免每次 prompt 静态噪音）。
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
CANDIDATE_CAP = 3

# worktree → 主仓映射标记：主仓存在本 hook 的 db 才替换 root
MARKER = Path(".conventions") / "conventions.db"


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
            return _resolve(Path(proc.stdout.strip()))
    return _resolve(Path.cwd())


def _map_worktree_to_main(root: Path, marker: Path) -> Path | None:
    """linked worktree → 主仓根：仅当主仓存在本 hook 的 db 标记时替换，否则 None（维持原 root）。

    判定：git-dir ≠ git-common-dir 即 linked worktree；主仓根 = common-dir 的 parent。
    任何失败（非 git/裸仓/命令缺失）返回 None——映射是增强，永不阻断。
    """
    try:
        run = subprocess.run(["git", "rev-parse", "--git-dir", "--git-common-dir"],
                             cwd=root, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if run.returncode != 0:
        return None
    lines = run.stdout.splitlines()
    if len(lines) < 2:
        return None
    git_dir, common = Path(lines[0]), Path(lines[1])
    if not git_dir.is_absolute():
        git_dir = (root / git_dir).resolve()
    if not common.is_absolute():
        common = (root / common).resolve()
    if git_dir == common:
        return None  # 主工作树
    main_root = common.parent
    if (main_root / marker).exists():
        return main_root
    return None


def _resolve(r: Path) -> Path:
    """候选 root 统一收口：worktree 场景映射为主仓根（有 db 才替换），否则原样。"""
    return _map_worktree_to_main(r, MARKER) or r


def _log(log_path: Path, status: str) -> None:
    try:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{ts}|{status}\n")
    except OSError:
        pass


def _load(conn: sqlite3.Connection) -> tuple[list[tuple], int, list[tuple]]:
    """返回 (漂移记录 ≤MAX_DRIFT, 约定总数, inferred 候选 ≤CANDIDATE_CAP)。

    候选 = source='inferred' 且非 drift（inferred 候选为分析产出不裁决，drift=1 走漂移区）。
    """
    total = conn.execute("SELECT COUNT(*) FROM conventions").fetchone()[0]
    drifts = conn.execute(
        "SELECT dimension, subject, statement, sample_size, compliance FROM conventions"
        " WHERE drift = 1 ORDER BY dimension, id LIMIT ?",
        (MAX_DRIFT,),
    ).fetchall()
    candidates = conn.execute(
        "SELECT dimension, subject, statement FROM conventions"
        " WHERE source = 'inferred' AND drift = 0 ORDER BY sample_size DESC LIMIT ?",
        (CANDIDATE_CAP,),
    ).fetchall()
    return drifts, total, candidates


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


def _format(drifts: list[tuple], total: int, gap: int | None,
            candidates: list[tuple]) -> str | None:
    """无漂移且无过期且无候选 -> None（不注入）；否则生成瘦档文本。"""
    stale = gap is not None and gap > STALE_COMMITS
    if not drifts and not stale and not candidates:
        return None
    lines = [
        "## 项目约定蒸馏（瘦档；文档与实证漂移并列呈证，动手前确认权威，不擅自站队）"
    ]
    for dim, subject, statement, n, comp in drifts:
        comp_s = "?" if comp is None else f"{comp:.2f}"
        lines.append(f"- ⚠️ [{dim}] {subject} :: {statement}（n={n}, 合规率={comp_s}）")
    if candidates:
        lines.append("🔍 候选规范（待人确认，认可后写入 conventions.yaml 转正）：")
        for _dim, subject, statement in candidates:
            lines.append(f"- 🔍 {subject} :: {statement}")
    if stale:
        lines.append(
            f"[conventions] 索引落后 {gap} 个 commit（>{STALE_COMMITS}），约定可能过期。"
        )
    lines.append(
        f"[conventions] 共 {total} 条约定；深查：python3 ~/.dl-workflow/bin/cvx.py query <主题> | drift"
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
        drifts, total, candidates = _load(conn)
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'commit_hash'"
        ).fetchone()
        conn.close()
    except sqlite3.Error:
        _log(inject_log, "query_error")
        return 0
    gap = _commit_gap(root, row[0] if row else "")
    context = _format(drifts, total, gap, candidates)
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
    _log(inject_log, f"injected drifts={len(drifts)} cands={len(candidates)} gap={gap}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
