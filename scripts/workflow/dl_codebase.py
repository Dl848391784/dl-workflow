#!/usr/bin/env python3
"""dl codebase query — 通用代码考古工具箱（组件 A）。

包装 codegraph / grep / git 为结构化 JSON，供工作流模型直接消费。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys


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


def query_symbol(symbol: str) -> dict:
    """符号三连：定义(query) + 调用者(callers) + 影响面(impact)。"""
    return {
        "symbol": symbol,
        "definition": _codegraph_json("query", symbol),
        "callers": _codegraph_json("callers", symbol),
        "impact": _codegraph_json("impact", symbol),
    }


_GREP_EXCLUDES = ["--exclude-dir=.git", "--exclude-dir=.claude", "--exclude-dir=__pycache__", "--exclude-dir=node_modules"]
_TYPE_INCLUDE = {"py": "*.py", "html": "*.html", "js": "*.js", "ts": "*.ts"}


def query_string(pattern: str, type_filter: str | None, max_count: int) -> dict:
    """字符串/正则搜索（grep -rn，带排除目录 + 可选 --include）。"""
    cmd = ["grep", "-rn", *_GREP_EXCLUDES]
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
    line = int(line_str)
    blame = _run(["git", "-C", ".", "blame", "-L", f"{line},{line}", "--", file_path])
    log = _run(["git", "-C", ".", "log", "--oneline", "--max-count", str(max_count), "--", file_path])
    return {
        "target": target,
        "blame": blame.stdout.strip() if blame.returncode == 0 else f"<blame 失败: {blame.stderr.strip()}>",
        "commits": log.stdout.strip().splitlines() if log.returncode == 0 else [],
    }


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError  # Task 3


if __name__ == "__main__":
    raise SystemExit(main())
