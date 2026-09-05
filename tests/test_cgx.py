"""scripts/cgx.py 单元测试（fixture db，不依赖真实仓索引）。

覆盖：置信度分档 / 反向边查询附 tier / unresolved 候选 / 文本兜底排除已知命中 /
同名多 target 去重 / db 缺失退出码。对应 designs/precision_tiers_landing-design.md。
"""

import importlib.util
import json
import sqlite3
from pathlib import Path


def _load(name, rel):
    path = Path(__file__).resolve().parents[1] / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cgx = _load("cgx", "bin/cgx.py")


SCHEMA = """
CREATE TABLE nodes (id TEXT PRIMARY KEY, kind TEXT, name TEXT, qualified_name TEXT,
                    file_path TEXT, language TEXT, start_line INTEGER, end_line INTEGER,
                    start_column INTEGER, end_column INTEGER, docstring TEXT, signature TEXT,
                    visibility TEXT, is_exported INTEGER, is_async INTEGER, is_static INTEGER,
                    is_abstract INTEGER, decorators TEXT, type_parameters TEXT, updated_at INTEGER);
CREATE TABLE edges (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, target TEXT,
                    kind TEXT, metadata TEXT, line INTEGER, col INTEGER, provenance TEXT);
CREATE TABLE unresolved_refs (id INTEGER PRIMARY KEY AUTOINCREMENT, from_node_id TEXT,
                              reference_name TEXT, reference_kind TEXT, line INTEGER,
                              col INTEGER, candidates TEXT, file_path TEXT, language TEXT);
"""


def _node(nid, name, kind, fpath, line):
    return (nid, kind, name, name, fpath, "python", line, line + 5, 0, 0, None, None, None, 0, 0, 0, 0, None, None, 0)


def _fixture_db(tmp_path):
    db = tmp_path / "cg.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            _node("function:t1", "foo", "function", "mod/a.py", 10),
            _node("function:t2", "foo", "function", "mod2/a.py", 20),
            _node("function:c1", "caller_hi", "function", "app/x.py", 30),
            _node("function:c2", "caller_mid", "function", "app/y.py", 40),
            _node("function:c3", "caller_lo", "function", "app/z.py", 50),
        ],
    )
    conn.executemany(
        "INSERT INTO edges (source, target, kind, metadata, line) VALUES (?,?,?,?,?)",
        [
            ("function:c1", "function:t1", "calls", '{"confidence":0.9,"resolvedBy":"exact-match"}', 31),
            ("function:c2", "function:t1", "calls", '{"confidence":0.7,"resolvedBy":"instance-method"}', 41),
            ("function:c3", "function:t2", "calls", '{"confidence":0.4,"resolvedBy":"exact-match"}', 51),
            ("function:c3", "function:t1", "calls", '{"confidence":0.6,"resolvedBy":"exact-match"}', 51),
        ],
    )
    conn.execute(
        "INSERT INTO unresolved_refs (from_node_id, reference_name, reference_kind,"
        " line, col, candidates, file_path, language) VALUES (?,?,?,?,?,?,?,?)",
        ("function:c9", "foo", "call", 99, 0, None, "app/w.py", "python"),
    )
    conn.commit()
    conn.close()
    return db


def test_tier_boundaries():
    assert cgx._tier(0.85) == "resolved" and cgx._tier(0.95) == "resolved"
    assert cgx._tier(0.5) == "inferred" and cgx._tier(0.84) == "inferred"
    assert cgx._tier(0.49) == "weak"


def test_edge_hits_with_confidence(tmp_path):
    conn = sqlite3.connect(_fixture_db(tmp_path))
    hits = cgx._edge_hits(conn, "function:t1", ("calls",))
    assert len(hits) == 3  # c1, c2, c3(0.6 行)
    by_name = {h["name"]: h for h in hits}
    assert by_name["caller_hi"]["tier"] == "resolved"
    assert by_name["caller_mid"]["tier"] == "inferred"
    assert by_name["caller_lo"]["resolved_by"] == "exact-match"
    conn.close()


def test_unresolved_candidates(tmp_path):
    conn = sqlite3.connect(_fixture_db(tmp_path))
    cands = cgx._unresolved_candidates(conn, "foo")
    assert cands == [{"file": "app/w.py", "line": 99, "from_node": "function:c9"}]
    conn.close()


def test_query_dedup_same_name_targets(tmp_path):
    """c3 对 t1/t2 同名 target 各有一条边（同调用点）：去重后只剩最高置信度那条。"""
    conn = sqlite3.connect(_fixture_db(tmp_path))
    result = cgx._query(conn, "foo", tmp_path, with_textual=False, with_imports=False)
    lo_hits = [h for h in result["hits"] if h["name"] == "caller_lo"]
    assert len(lo_hits) == 1 and lo_hits[0]["confidence"] == 0.6
    assert len(result["targets"]) == 2
    conn.close()


def test_format_text_sections(tmp_path):
    conn = sqlite3.connect(_fixture_db(tmp_path))
    result = cgx._query(conn, "foo", tmp_path, with_textual=False, with_imports=False)
    text = cgx._format_text(result)
    assert "target: foo (function) mod/a.py:10" in text
    assert "[resolved] caller_hi" in text
    assert "[unresolved-candidate] app/w.py:99" in text
    conn.close()


def test_main_missing_db_returns_1(tmp_path, capsys):
    rc = cgx.main(["callers", "foo", "--db", str(tmp_path / "nope.db"), "--no-textual"])
    assert rc == 1
    assert "codegraph db 不存在" in capsys.readouterr().err


def test_main_json_output(tmp_path, capsys):
    rc = cgx.main(["callers", "foo", "--db", str(_fixture_db(tmp_path)), "--json", "--no-textual"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["symbol"] == "foo" and len(data["hits"]) == 3
