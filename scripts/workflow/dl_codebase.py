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
    return subprocess.run(cmd, capture_output=True, text=True)


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


def query_string(pattern: str, type_filter: str | None, max_count: int) -> dict:
    raise NotImplementedError  # Task 2


def query_history(target: str, max_count: int) -> dict:
    raise NotImplementedError  # Task 2


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError  # Task 3


if __name__ == "__main__":
    raise SystemExit(main())
