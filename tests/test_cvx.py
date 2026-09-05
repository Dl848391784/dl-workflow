"""scripts/cvx.py 单元测试。对应 designs/convention_mining_design.md §产出物形态。"""

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


cvx = _load("cvx", "bin/cvx.py")


def _fixture_db(tmp_path):
    db = tmp_path / "conventions.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE conventions (
          id INTEGER PRIMARY KEY, dimension TEXT NOT NULL, subject TEXT NOT NULL,
          statement TEXT NOT NULL, source TEXT NOT NULL, sample_size INTEGER NOT NULL,
          compliance REAL, drift INTEGER NOT NULL DEFAULT 0, evidence TEXT NOT NULL,
          generated_at TEXT NOT NULL, commit_hash TEXT);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        """
    )
    rows = [
        (
            "d3_style",
            "H11 日志风格",
            "f-string 7 处",
            "doc_declared",
            150,
            0.95,
            1,
            json.dumps([{"file": "web_ui/x.py", "line": 12}]),
            "2026-09-05T00:00:00",
            "abc",
        ),
        (
            "d1_shared_util",
            "paths.DATA_DIR",
            "被 20 处引用",
            "code_evidence",
            20,
            None,
            0,
            "[]",
            "2026-09-05T00:00:00",
            "abc",
        ),
    ]
    conn.executemany(
        "INSERT INTO conventions (dimension, subject, statement, source, sample_size,"
        " compliance, drift, evidence, generated_at, commit_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return db


def test_select_query_and_drift(tmp_path):
    db = _fixture_db(tmp_path)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    hits = cvx._select(conn, keyword="日志")
    assert len(hits) == 1 and hits[0]["subject"] == "H11 日志风格"
    drift = cvx._select(conn, drift_only=True)
    assert len(drift) == 1 and drift[0]["drift"] == 1
    assert cvx._select(conn, keyword="不存在的关键词") == []
    conn.close()


def test_format_shows_drift_and_evidence(tmp_path):
    db = _fixture_db(tmp_path)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    text = cvx._format(cvx._select(conn, drift_only=True))
    conn.close()
    assert "DRIFT" in text and "H11 日志风格" in text and "web_ui/x.py:12" in text


def test_main_exit_codes(tmp_path, capsys):
    db = _fixture_db(tmp_path)
    assert cvx.main(["query", "日志", "--db", str(db)]) == 0
    capsys.readouterr()  # 丢掉 query 的文本输出
    assert cvx.main(["drift", "--db", str(db), "--json"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)[0]["subject"] == "H11 日志风格"
    assert cvx.main(["query", "x", "--db", str(tmp_path / "nope.db")]) == 1
