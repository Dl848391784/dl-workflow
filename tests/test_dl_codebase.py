# tests/test_dl_codebase.py
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "workflow"))
import dl_codebase as cb  # noqa: E402


def test_query_symbol_shapes(monkeypatch):
    """query_symbol 返回三键：definition/callers/impact，各自含 ok 或 error。"""
    calls = {}

    def fake_run(cmd):
        calls[cmd[1]] = cmd
        if cmd[1] == "query":
            return subprocess.CompletedProcess(cmd, 0, json.dumps([{"node": {"name": "f", "filePath": "a.py", "startLine": 1}}]), "")
        if cmd[1] == "callers":
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"callers": [{"name": "g", "filePath": "b.py", "startLine": 2}]}), "")
        if cmd[1] == "impact":
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"affected": []}), "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(cb, "_run", fake_run)
    out = cb.query_symbol("convert_return_to_percentage")
    assert set(out) == {"symbol", "definition", "callers", "impact"}
    assert out["definition"]["ok"][0]["node"]["name"] == "f"
    assert out["callers"]["ok"]["callers"][0]["name"] == "g"
