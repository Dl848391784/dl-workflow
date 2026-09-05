#!/usr/bin/env python3
"""cvx - 项目约定深查 CLI（designs/convention_mining_design.md）。

瘦档注入只给漂移点摘要；动手前需要完整约定上下文时用本工具按需查。

用法：python3 ~/.dl-workflow/bin/cvx.py query <关键词> | drift [--json] [--db PATH]
退出码（H12）：0=正常（含零命中）；1=未预期错误（db 缺失/查询失败）。
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path


DEFAULT_DB = Path(".conventions") / "conventions.db"
MAX_ROWS = 30

COLUMNS = ("dimension", "subject", "statement", "source", "sample_size", "compliance", "drift", "evidence")


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
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    if args.command == "query" and not args.keyword:
        print("cvx: query 需要关键词", file=sys.stderr)
        return 1

    try:
        conn = _open_db(args.db)
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
