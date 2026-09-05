#!/usr/bin/env python3
"""cgx - codegraph 精确查询：置信度分层 + 召回兜底。

CLI `codegraph callers` 增强版（designs/precision_tiers_landing-design.md）：
- db `edges.metadata` confidence 分档：[resolved]>=0.85 / [inferred]0.5~0.85 / [weak]<0.5
- `unresolved_refs` 候选单列 [unresolved-candidate]（CLI 完全不看此表）
- grep 文本兜底 [textual]：db 静默丢边时仍能召回，标最低置信度提示需复核

用法：python3 ~/.dl-workflow/bin/cgx.py callers|impact <symbol> [--json] [--db PATH] [--no-textual]
退出码（H12）：0=正常（含零命中）；1=未预期错误（db 缺失/查询失败）。
"""

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path


DEFAULT_DB = Path(".codegraph") / "codegraph.db"
MAX_TARGETS = 10
MAX_TEXTUAL = 20
TIER_RESOLVED_MIN = 0.85
TIER_INFERRED_MIN = 0.5
CALL_EDGE_KINDS = ("calls", "references")
# 文本兜底只扫源码文件（.md/.log 是噪音）
SOURCE_GLOBS = ("*.py", "*.java", "*.go", "*.rs", "*.js", "*.ts", "*.c", "*.cc", "*.h", "*.rb")


def _tier(confidence: float) -> str:
    if confidence >= TIER_RESOLVED_MIN:
        return "resolved"
    if confidence >= TIER_INFERRED_MIN:
        return "inferred"
    return "weak"


def _open_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"codegraph db 不存在: {db_path}（先跑 codegraph index）")
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _find_targets(conn, symbol):
    return conn.execute(
        "SELECT id, name, kind, file_path, start_line FROM nodes WHERE name = ? AND kind != 'import' LIMIT ?",
        (symbol, MAX_TARGETS),
    ).fetchall()


def _edge_hits(conn, target_id, edge_kinds):
    """target 的反向边，附 confidence/resolvedBy/tier。"""
    placeholders = ",".join("?" for _ in edge_kinds)
    rows = conn.execute(
        f"SELECT n.name, n.kind, n.file_path, n.start_line, e.line, e.metadata "  # noqa: S608
        f"FROM edges e JOIN nodes n ON n.id = e.source "
        f"WHERE e.target = ? AND e.kind IN ({placeholders})",
        (target_id, *edge_kinds),
    ).fetchall()
    hits = []
    for name, kind, fpath, sline, call_line, metadata in rows:
        confidence, resolved_by = 0.5, "unknown"
        if metadata:
            md = json.loads(metadata)
            confidence = float(md.get("confidence", 0.5))
            resolved_by = str(md.get("resolvedBy", "unknown"))
        hits.append(
            {
                "name": name,
                "kind": kind,
                "file": fpath,
                "line": sline,
                "call_line": call_line,
                "confidence": confidence,
                "resolved_by": resolved_by,
                "tier": _tier(confidence),
            }
        )
    return hits


def _unresolved_candidates(conn, symbol):
    rows = conn.execute(
        "SELECT file_path, line, from_node_id FROM unresolved_refs WHERE reference_name = ?",
        (symbol,),
    ).fetchall()
    return [{"file": f, "line": ln, "from_node": src} for f, ln, src in rows]


def _textual_hits(symbol, known, root):
    """grep 文本兜底：匹配 `symbol(` 调用形态，排除已知命中/定义行/import 行。"""
    cmd = [
        "grep",
        "-rnE",
        "--exclude-dir=.git",
        "--exclude-dir=.codegraph",
        "--exclude-dir=__pycache__",
        "--exclude-dir=worktrees",
    ]
    for glob_pat in SOURCE_GLOBS:
        cmd.append(f"--include={glob_pat}")
    cmd += [rf"\b{re.escape(symbol)}\s*\(", str(root)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    hits = []
    for line in proc.stdout.splitlines():
        m = re.match(r"(.+?):(\d+):(.*)", line)
        if not m:
            continue
        fpath, lineno, text = m.group(1), int(m.group(2)), m.group(3)
        rel = str(Path(fpath).relative_to(root)) if Path(fpath).is_absolute() else fpath
        if (rel, lineno) in known or f"def {symbol}" in text or "import" in text:
            continue
        hits.append({"file": rel, "line": lineno})
        if len(hits) >= MAX_TEXTUAL:
            break
    return hits


def _query(conn, symbol, root, with_textual, with_imports):
    targets = _find_targets(conn, symbol)
    hits = []
    for tid, _name, _kind, _fpath, _sline in targets:
        hits.extend(_edge_hits(conn, tid, CALL_EDGE_KINDS))
        if with_imports:
            hits.extend(_edge_hits(conn, tid, ("imports",)))
    # 同名多 target（跨模块同符号）各自拉边导致重复行：按调用点去重，保留最高置信度
    dedup = {}
    for h in hits:
        key = (h["file"], h["call_line"], h["name"])
        if key not in dedup or h["confidence"] > dedup[key]["confidence"]:
            dedup[key] = h
    candidates = _unresolved_candidates(conn, symbol)
    result = {
        "symbol": symbol,
        "targets": [{"name": n, "kind": k, "file": f, "line": sl} for _id, n, k, f, sl in targets],
        "hits": sorted(dedup.values(), key=lambda h: -h["confidence"]),
        "candidates": candidates,
        "textual": [],
    }
    if with_textual:
        known = {(h["file"], h["call_line"]) for h in result["hits"]}
        known |= {(c["file"], c["line"]) for c in candidates}
        known |= {(t["file"], t["line"]) for t in result["targets"]}
        result["textual"] = _textual_hits(symbol, known, root)
    return result


def _format_text(result):
    lines = [f"target: {t['name']} ({t['kind']}) {t['file']}:{t['line']}" for t in result["targets"]]
    for h in result["hits"]:
        lines.append(
            f"[{h['tier']}] {h['name']} ({h['kind']}) {h['file']}:{h['line']}"
            f" call@{h['call_line']} conf={h['confidence']:.2f} {h['resolved_by']}"
        )
    lines += [f"[unresolved-candidate] {c['file']}:{c['line']}" for c in result["candidates"]]
    lines += [f"[textual] {t['file']}:{t['line']}" for t in result["textual"]]
    if len(lines) == len(result["targets"]):
        lines.append("(no callers found in any tier)")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="codegraph 精确查询（置信度分层 + 召回兜底）")
    parser.add_argument("command", choices=["callers", "impact"])
    parser.add_argument("symbol")
    parser.add_argument("--json", action="store_true", help="JSON 输出（供 agent/脚本消费）")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--no-textual", action="store_true", help="关闭 grep 文本兜底（只要图内证据）")
    args = parser.parse_args(argv)

    try:
        conn = _open_db(args.db)
    except (FileNotFoundError, sqlite3.OperationalError) as e:
        print(f"cgx: {e}", file=sys.stderr)
        return 1
    try:
        result = _query(
            conn,
            args.symbol,
            Path.cwd(),
            with_textual=not args.no_textual,
            with_imports=args.command == "impact",
        )
    except sqlite3.Error as e:
        print(f"cgx: 查询失败 symbol={args.symbol}: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_format_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
