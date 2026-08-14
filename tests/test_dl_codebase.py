# tests/test_dl_codebase.py
import json
import subprocess
import sys
from pathlib import Path

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


def test_query_symbol_codegraph_missing(monkeypatch):
    """codegraph 缺失时 _run 捕获 OSError，返回结构化 error 而非裸栈。"""
    err = FileNotFoundError(2, "No such file or directory", "codegraph")

    def raise_not_found(cmd, **kwargs):
        raise err

    monkeypatch.setattr(cb.subprocess, "run", raise_not_found)
    out = cb.query_symbol("x")
    expected = {"error": f"codegraph 不存在或不可执行: {err}"}
    assert out["definition"] == expected
    assert out["callers"] == expected
    assert out["impact"] == expected


def test_query_string_parses_grep(monkeypatch):
    """grep -rn 输出解析成 matches:[{file,line,text}]，并带 exclude 参数。"""
    captured = {}

    def fake_run(cmd):
        captured["cmd"] = cmd
        out = "backtest/common/layered_backtest.py:624:    return_col=\"forward_return_1d\",\n"
        return subprocess.CompletedProcess(cmd, 0, out, "")

    monkeypatch.setattr(cb, "_run", fake_run)
    out = cb.query_string("forward_return_1d", None, 50)
    assert out["matches"] == [
        {"file": "backtest/common/layered_backtest.py", "line": 624, "text": '    return_col="forward_return_1d",'}
    ]
    # 关键：必须排除 .git / .claude
    assert "--exclude-dir=.git" in captured["cmd"]
    assert "--exclude-dir=.claude" in captured["cmd"]


def test_query_history_parses_blame(monkeypatch):
    """--history <file>:<line> 返回 blame + commits。"""
    def fake_run(cmd):
        if cmd[0] == "git" and cmd[1] == "-C" and cmd[3] == "blame":
            return subprocess.CompletedProcess(cmd, 0, "abc1234 (dev) line content", "")
        return subprocess.CompletedProcess(cmd, 0, "abc1234 fix\nabc0000 init\n", "")

    monkeypatch.setattr(cb, "_run", fake_run)
    out = cb.query_history("summary/report/data_loaders.py:120", 50)
    assert out["target"] == "summary/report/data_loaders.py:120"
    assert "abc1234" in out["blame"]
    assert out["commits"] == ["abc1234 fix", "abc0000 init"]


def test_query_history_bad_target():
    """缺 : 的目标报结构化 error，不抛异常。"""
    out = cb.query_history("noline", 50)
    assert "error" in out


def test_main_symbol_json(capsys, monkeypatch):
    monkeypatch.setattr(cb, "query_symbol", lambda s: {"symbol": s, "definition": {}, "callers": {}, "impact": {}})
    rc = cb.main(["query", "--symbol", "foo"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["symbol"] == "foo"


def test_main_no_flag_returns_2(capsys):
    rc = cb.main(["query"])
    assert rc == 2
