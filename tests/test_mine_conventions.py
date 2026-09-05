"""scripts/mine_conventions.py 单元测试（fixture db + 临时文件，不依赖真实仓）。

覆盖：schema 建表 / 原子写 / _top_module 映射 / 各维度 miner。对应 designs/convention_mining_design.md。
"""

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest


def _load(name, rel):
    path = Path(__file__).resolve().parents[1] / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mc = _load("mine_conventions", "bin/mine_conventions.py")


def _read_records(db_path):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT dimension, subject, statement, source, sample_size, compliance, drift, evidence,"
        " generated_at, commit_hash FROM conventions"
    ).fetchall()
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    conn.close()
    return rows, meta


def _record(**kw):
    base = {
        "dimension": "d4_skeleton",
        "subject": "s",
        "statement": "st",
        "source": "code_evidence",
        "sample_size": 3,
        "compliance": None,
        "drift": 0,
        "evidence": [{"file": "a.py", "line": 1}],
    }
    base.update(kw)
    return base


def test_top_module():
    assert mc._top_module("web_ui/app.py") == "web_ui"
    assert mc._top_module("scripts/sub/x.py") == "scripts"
    assert mc._top_module("paths.py") == "(root)"


def test_write_db_atomic_and_meta(tmp_path):
    out = tmp_path / "sub" / "conventions.db"
    mc._write_db(
        out, [_record(), _record(drift=1, source="doc_declared", compliance=0.5)], "2026-09-05T00:00:00", "abc123"
    )
    rows, meta = _read_records(out)
    assert len(rows) == 2
    assert rows[0][1] == "s" and json.loads(rows[0][7]) == [{"file": "a.py", "line": 1}]
    assert meta["generated_at"] == "2026-09-05T00:00:00"
    assert meta["commit_hash"] == "abc123"


CG_SCHEMA = """
CREATE TABLE nodes (id TEXT PRIMARY KEY, kind TEXT, name TEXT, file_path TEXT, start_line INTEGER);
CREATE TABLE edges (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, target TEXT,
                    kind TEXT, line INTEGER);
"""


def _fixture_cg(tmp_path):
    conn = sqlite3.connect(tmp_path / "cg.db")
    conn.executescript(CG_SCHEMA)
    nodes = [
        ("n_data", "variable", "DATA_DIR", "paths.py", 10),
        ("n_root", "variable", "PROJECT_ROOT", "paths.py", 5),
        ("n_caller1", "function", "load_page", "web_ui/app.py", 20),
        ("n_caller2", "function", "main", "scripts/foo.py", 30),
        ("n_caller3", "function", "main", "scripts/bar.py", 40),
        ("n_imp", "import", "paths", "web_ui/app.py", 1),
    ]
    conn.executemany("INSERT INTO nodes VALUES (?,?,?,?,?)", nodes)
    edges = [
        ("n_caller1", "n_data", "references", 21),
        ("n_caller2", "n_data", "references", 31),
        ("n_caller3", "n_data", "imports", 3),
        ("n_caller1", "n_root", "references", 22),
        ("n_imp", "n_data", "imports", 1),  # import 节点自身作 source：应被排除（self/import 噪音）
    ]
    conn.executemany("INSERT INTO edges (source, target, kind, line) VALUES (?,?,?,?)", edges)
    conn.commit()
    return conn


def test_d1_shared_utils(tmp_path):
    cg = _fixture_cg(tmp_path)
    recs = mc.mine_d1_shared_utils(cg, tmp_path, [])
    by_subject = {r["subject"]: r for r in recs}
    assert set(by_subject) == {"paths.DATA_DIR", "paths.PROJECT_ROOT"}
    d = by_subject["paths.DATA_DIR"]
    assert d["dimension"] == "d1_shared_util" and d["source"] == "code_evidence"
    assert d["sample_size"] == 3  # web_ui 1 处 + scripts 2 处（n_imp import 节点被排除）
    assert d["compliance"] is None and d["drift"] == 0
    assert "web_ui" in d["statement"] and "scripts" in d["statement"]
    p = by_subject["paths.PROJECT_ROOT"]
    assert p["sample_size"] == 1


def test_d1_path_literals(tmp_path):
    (tmp_path / "a.py").write_text("from paths import DATA_DIR\nx = DATA_DIR / 'f'\n")
    (tmp_path / "b.py").write_text("LOG = '/home/admin/logs/x.log'\n")
    (tmp_path / "paths.py").write_text("ROOT = '/home/admin/projects'\n")  # paths.py 豁免
    recs = mc.mine_d1_path_literals(None, tmp_path, ["a.py", "b.py", "paths.py"])
    assert len(recs) == 1
    r = recs[0]
    assert r["source"] == "doc_declared" and r["dimension"] == "d1_path_literal"
    assert r["sample_size"] == 3 and r["compliance"] == pytest.approx(2 / 3)
    assert r["drift"] == 1 and r["evidence"] == [{"file": "b.py", "line": 1}]
    assert "H7" in r["subject"]


def test_d1_path_literals_clean(tmp_path):
    (tmp_path / "a.py").write_text("from paths import DATA_DIR\n")
    recs = mc.mine_d1_path_literals(None, tmp_path, ["a.py"])
    assert recs[0]["drift"] == 0 and recs[0]["compliance"] == 1.0
    assert recs[0]["evidence"] == []


def test_d2_layering(tmp_path):
    conn = sqlite3.connect(tmp_path / "cg.db")
    conn.executescript(CG_SCHEMA)
    nodes = [
        ("a", "function", "f1", "web_ui/app.py", 1),
        ("b", "function", "f2", "factor_ic/calc.py", 1),
        ("c", "function", "f3", "web_ui/page.py", 1),
        ("d", "function", "f4", "web_ui/helper.py", 1),
        ("e", "function", "f5", "backtest/engine.py", 1),
    ]
    conn.executemany("INSERT INTO nodes VALUES (?,?,?,?,?)", nodes)
    edges = [
        ("a", "b", "imports", 2),  # web_ui -> factor_ui 正常方向
        ("c", "b", "imports", 2),  # web_ui -> factor_ic 第二处
        ("e", "d", "imports", 2),  # backtest -> web_ui：H1 子集违规（后端 import UI）
    ]
    conn.executemany("INSERT INTO edges (source, target, kind, line) VALUES (?,?,?,?)", edges)
    conn.commit()
    recs = mc.mine_d2_layering(conn, tmp_path, [])
    facts = [r for r in recs if r["source"] == "code_evidence"]
    h1 = [r for r in recs if r["source"] == "doc_declared"]
    pair = {(r["subject"]): r for r in facts}
    assert pair["web_ui->factor_ic"]["sample_size"] == 2
    assert len(h1) == 1 and h1[0]["drift"] == 1
    assert h1[0]["evidence"] == [{"file": "backtest/engine.py", "line": 2}]
    assert "H1" in h1[0]["subject"]


def test_d3_style(tmp_path):
    (tmp_path / "x.py").write_text(
        'logger.info("loaded %s rows", n)\nlogger.info(f"done {n}")\nlogger.error("fail %s", e)\n'
    )
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "s1.py").write_text("import sys\nsys.exit(0)\n")
    (tmp_path / "scripts" / "s2.py").write_text("def main():\n    return 1\n    return 3\n")
    recs = mc.mine_d3_style(None, tmp_path, ["x.py", "scripts/s1.py", "scripts/s2.py"])
    by = {r["subject"]: r for r in recs}
    h11 = by["H11 日志风格"]
    assert h11["source"] == "doc_declared" and h11["drift"] == 1
    assert h11["sample_size"] == 3 and h11["compliance"] == pytest.approx(2 / 3)
    assert h11["evidence"] == [{"file": "x.py", "line": 2}]
    ec = by["scripts/ 退出码分布"]
    assert ec["source"] == "code_evidence" and ec["drift"] == 0
    assert "0" in ec["statement"] and "1" in ec["statement"] and "3" in ec["statement"]


def test_d4_skeleton(tmp_path):
    (tmp_path / "scripts").mkdir(exist_ok=True)
    (tmp_path / "scripts" / "a.py").write_text(
        'import argparse\nfrom paths import DATA_DIR\ndef main():\n    pass\nif __name__ == "__main__":\n    main()\n'
    )
    (tmp_path / "scripts" / "b.py").write_text("print('hi')\n")
    (tmp_path / "scripts" / "test_z.py").write_text("def test_z():\n    pass\n")  # 排除
    recs = mc.mine_d4_skeleton(None, tmp_path, ["scripts/a.py", "scripts/b.py", "scripts/test_z.py"])
    by = {r["subject"]: r for r in recs}
    assert by["scripts/ 骨架：argparse"]["compliance"] == pytest.approx(0.5)
    assert by["scripts/ 骨架：argparse"]["sample_size"] == 2
    assert by["scripts/ 骨架：main 函数"]["compliance"] == pytest.approx(0.5)
    assert by["scripts/ 骨架：paths 导入"]["compliance"] == pytest.approx(0.5)
    assert by["scripts/ 骨架：__main__ 守卫"]["compliance"] == pytest.approx(0.5)
    assert all(r["drift"] == 0 and r["source"] == "code_evidence" for r in recs)
