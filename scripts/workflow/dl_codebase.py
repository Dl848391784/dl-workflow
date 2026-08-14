#!/usr/bin/env python3
"""dl codebase query — 通用代码考古工具箱（组件 A）。

包装 codegraph / grep / git 为结构化 JSON，供工作流模型直接消费。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True)
    except OSError as e:
        return subprocess.CompletedProcess(cmd, 1, "", f"{cmd[0]} 不存在或不可执行: {e}")


def _codegraph_json(sub: str, symbol: str) -> dict:
    """codegraph <sub> <symbol> --json → {"ok": parsed} 或 {"error": msg}。"""
    r = _run(["codegraph", sub, symbol, "--json"])
    if r.returncode != 0:
        return {"error": r.stderr.strip() or f"codegraph {sub} 失败"}
    try:
        return {"ok": json.loads(r.stdout)}
    except json.JSONDecodeError:
        return {"error": "codegraph 输出非 JSON", "raw": r.stdout[:500]}


def _resolve_ledger_path() -> Path | None:
    """从 cwd 反查发现台账路径；cwd 不在 <project>/.claude/worktrees/<name> 内返回 None。

    worktree 内透明去重，worktree 外保持通用工具原行为。
    """
    cwd = Path.cwd()
    parts = cwd.parts
    if "worktrees" not in parts:
        return None
    idx = parts.index("worktrees")
    if idx + 1 >= len(parts):
        return None
    name = parts[idx + 1]
    wt_root = Path(*parts[: idx + 2])  # 重建 worktree 根绝对路径
    project = wt_root.parents[2]
    return project / ".claude" / "workflows" / name / "discoveries.jsonl"


def _load_ledger(path: Path) -> dict:
    """读台账 → {key: entry}；缺失/损坏返回 {}（宁纵勿枉）。"""
    if not path.exists():
        return {}
    ledger = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            if e.get("key"):
                ledger[e["key"]] = e
    except (OSError, json.JSONDecodeError):
        return {}
    return ledger


def _current_step(path: Path) -> str | None:
    """从同目录 state.json 读 node#sub_step_index；读不到返回 None。"""
    state_path = path.parent / "state.json"
    try:
        s = json.loads(state_path.read_text(encoding="utf-8"))
        return f"{s.get('node', '?')}#{s.get('sub_step_index', '?')}"
    except (OSError, json.JSONDecodeError):
        return None


def _ledger_get(path: Path, key: str) -> dict | None:
    return _load_ledger(path).get(key)


def _ledger_append(path: Path, key: str, kind: str, query: str, result: dict) -> None:
    entry = {"key": key, "kind": kind, "query": query, "result": result,
             "step": _current_step(path), "ts": int(time.time())}
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 落账失败不阻断取证


def query_symbol(symbol: str) -> dict:
    """符号三连：定义(query) + 调用者(callers) + 影响面(impact)。"""
    path = _resolve_ledger_path()
    if path is not None:
        cached = _ledger_get(path, f"symbol:{symbol}")
        if cached is not None:
            return {**cached["result"], "source": "discovery-ledger"}
    payload = {
        "symbol": symbol,
        "definition": _codegraph_json("query", symbol),
        "callers": _codegraph_json("callers", symbol),
        "impact": _codegraph_json("impact", symbol),
    }
    if path is not None:
        _ledger_append(path, f"symbol:{symbol}", "symbol", symbol, payload)
    return {**payload, "source": "fresh"}


_GREP_EXCLUDES = ["--exclude-dir=.git", "--exclude-dir=.claude", "--exclude-dir=__pycache__", "--exclude-dir=node_modules", "--exclude-dir=.superpowers"]
_TYPE_INCLUDE = {"py": "*.py", "html": "*.html", "js": "*.js", "ts": "*.ts"}


def query_string(pattern: str, type_filter: str | None, max_count: int) -> dict:
    """字符串/正则搜索（grep -rn，带排除目录 + 可选 --include）。"""
    cmd = ["grep", "-rHn", *_GREP_EXCLUDES]
    if type_filter and type_filter in _TYPE_INCLUDE:
        cmd += ["--include", _TYPE_INCLUDE[type_filter]]
    cmd += ["--max-count", str(max_count), pattern, "."]
    r = _run(cmd)
    matches = []
    for line in (r.stdout or "").splitlines():
        if ":" in line:
            path, lineno, text = line.split(":", 2)
            matches.append({"file": path, "line": int(lineno), "text": text})
    out = {"pattern": pattern, "matches": matches}
    if r.returncode != 0 and r.returncode != 1:  # 1 = 无匹配，正常
        out["error"] = r.stderr.strip()
    return out


def query_history(target: str, max_count: int) -> dict:
    """git 历史：blame 单行 + log 该文件最近提交。target 形如 <file>:<line>。"""
    file_path, _, line_str = target.rpartition(":")
    if not file_path or not line_str.isdigit():
        return {"error": f"用法: --history <file>:<line>，收到 {target!r}"}
    path = _resolve_ledger_path()
    if path is not None:
        cached = _ledger_get(path, f"history:{target}")
        if cached is not None:
            return {**cached["result"], "source": "discovery-ledger"}
    line = int(line_str)
    blame = _run(["git", "-C", ".", "blame", "-L", f"{line},{line}", "--", file_path])
    log = _run(["git", "-C", ".", "log", "--oneline", "--max-count", str(max_count), "--", file_path])
    payload = {
        "target": target,
        "blame": blame.stdout.strip() if blame.returncode == 0 else f"<blame 失败: {blame.stderr.strip()}>",
        "commits": log.stdout.strip().splitlines() if log.returncode == 0 else [],
    }
    if path is not None:
        _ledger_append(path, f"history:{target}", "history", target, payload)
    return {**payload, "source": "fresh"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="dl codebase", description="通用代码考古工具箱")
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("query", help="查符号/字符串/git 历史")
    q.add_argument("--symbol", help="符号名（codegraph query/callers/impact）")
    q.add_argument("--string", help="字符串/正则（grep -rn）")
    q.add_argument("--history", help="<file>:<line>（git blame + log）")
    q.add_argument("--type", help="grep --include 类型过滤（py/html/js/ts，仅 --string）")
    q.add_argument("--max-count", type=int, default=50)
    args = p.parse_args(argv)

    if args.symbol:
        out = query_symbol(args.symbol)
    elif args.string:
        out = query_string(args.string, args.type, args.max_count)
    elif args.history:
        out = query_history(args.history, args.max_count)
    else:
        print("✗ 需指定 --symbol / --string / --history 之一", file=sys.stderr)
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
