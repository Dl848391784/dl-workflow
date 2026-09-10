#!/usr/bin/env python3
"""cvx - 项目约定深查 CLI（designs/convention_mining_design.md）。

瘦档注入只给漂移点摘要；动手前需要完整约定上下文时用本工具按需查。

用法：python3 ~/.dl-workflow/bin/cvx.py query <关键词> | drift [--json] [--db PATH]
退出码（H12）：0=正常（含零命中）；1=未预期错误（db 缺失/查询失败）。
"""

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


DEFAULT_DB = Path(".conventions") / "conventions.db"
MAX_ROWS = 30

COLUMNS = ("dimension", "subject", "statement", "source", "sample_size", "compliance", "drift", "evidence")


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess | None:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc if proc.returncode == 0 else None


def _resolve_db(explicit: Path | None) -> Path:
    """默认 db 路径解析（2026-09-10 cvx-wt-root，E2E 实爆驱动）。

    --db 显式指定优先；否则 cwd 经 git 反查仓根取 <根>/.conventions/conventions.db；
    linked worktree（git-dir ≠ git-common-dir）且主仓有 db 时映射主仓——
    与 hooks/conventions_inject.py _map_worktree_to_main 同构（工作流段会话
    cwd=worktree 是 cvx 的主消费场景，相对路径解析在该场景报「无 db」=
    模型误信「无活跃漂移点」）。非 git/全程无 db 回退 cwd 相对路径
    （现状行为，缺失报错文案不变）。任何 git 探测失败静默回退，永不阻断。
    """
    if explicit is not None:
        return explicit
    cwd = Path.cwd()
    top = _git(["rev-parse", "--show-toplevel"], cwd)
    if top is not None:
        root = Path(top.stdout.strip())
        db = root / DEFAULT_DB
        if db.exists():
            return db
        both = _git(["rev-parse", "--git-dir", "--git-common-dir"], cwd)
        if both is not None:
            lines = both.stdout.splitlines()
            if len(lines) >= 2:
                git_dir, common = Path(lines[0]), Path(lines[1])
                if not git_dir.is_absolute():
                    git_dir = (root / git_dir).resolve()
                if not common.is_absolute():
                    common = (root / common).resolve()
                if git_dir != common:
                    main_db = common.parent / DEFAULT_DB
                    if main_db.exists():
                        return main_db
    return DEFAULT_DB


def _open_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"conventions db 不存在: {db_path}（先跑 ~/.dl-workflow/bin/mine_conventions.py）")
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _select(conn: sqlite3.Connection, keyword: str | None = None, drift_only: bool = False) -> list[dict]:
    base = f"SELECT {', '.join(COLUMNS)} FROM conventions"  # noqa: S608
    if drift_only:
        rows = conn.execute(base + " WHERE drift = 1 ORDER BY dimension, id LIMIT ?", (MAX_ROWS,)).fetchall()
    else:
        like = f"%{keyword}%"
        rows = conn.execute(
            base + " WHERE subject LIKE ? OR statement LIKE ? ORDER BY drift DESC, dimension, id LIMIT ?",
            (like, like, MAX_ROWS),
        ).fetchall()
    return [dict(zip(COLUMNS, r, strict=True)) for r in rows]


def _format(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        tag = " DRIFT" if r["drift"] else ""
        comp = "?" if r["compliance"] is None else f"{r['compliance']:.2f}"
        lines.append(
            f"[{r['dimension']}{tag}] {r['subject']} :: {r['statement']}"
            f" (n={r['sample_size']}, compliance={comp}, {r['source']})"
        )
        for ev in json.loads(r["evidence"]):
            lines.append(f"  evidence: {ev['file']}:{ev['line']}")
    return "\n".join(lines) if lines else "(no conventions matched)"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="项目约定深查（designs/convention_mining_design.md）")
    parser.add_argument("command", choices=["query", "drift"])
    parser.add_argument("keyword", nargs="?", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.command == "query" and not args.keyword:
        print("cvx: query 需要关键词", file=sys.stderr)
        return 1

    try:
        conn = _open_db(_resolve_db(args.db))
    except (FileNotFoundError, sqlite3.OperationalError) as e:
        print(f"cvx: {e}", file=sys.stderr)
        return 1
    try:
        rows = _select(conn, keyword=args.keyword, drift_only=args.command == "drift")
    except sqlite3.Error as e:
        print(f"cvx: 查询失败: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(_format(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
