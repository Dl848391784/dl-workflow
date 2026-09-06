"""scripts/mine_conventions.py 单元测试（fixture db + 临时文件，不依赖真实仓）。

覆盖：schema 建表 / 原子写 / _top_module 映射 / 各规则 checker。对应 designs/convention_mining_design.md。
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


def _ctx(cg, root, files):
    return {"cg": cg, "root": root, "files": files}


def test_util_graph_checker(tmp_path):
    cg = _fixture_cg(tmp_path)
    rule = {"id": "util_graph", "type": "util_graph", "params": {"target_files": ["paths.py"]}}
    recs = mc.CHECKERS["util_graph"](rule, _ctx(cg, tmp_path, []))
    by_subject = {r["subject"]: r for r in recs}
    assert set(by_subject) == {"paths.DATA_DIR", "paths.PROJECT_ROOT"}
    assert by_subject["paths.DATA_DIR"]["sample_size"] == 3
    assert by_subject["paths.DATA_DIR"]["source"] == "code_evidence" and by_subject["paths.DATA_DIR"]["drift"] == 0


def test_path_literal_checker(tmp_path):
    (tmp_path / "a.py").write_text("from paths import DATA_DIR\n")
    (tmp_path / "b.py").write_text("LOG = '/home/admin/logs/x.log'\n")
    (tmp_path / "paths.py").write_text("ROOT = '/home/admin/projects'\n")
    rule = {"id": "H7", "type": "path_literal_scan", "statement": "路径只能 from paths import",
            "params": {"exempt_files": ["paths.py"], "preset": "abs_unix_path"}}
    recs = mc.CHECKERS["path_literal_scan"](rule, _ctx(None, tmp_path, ["a.py", "b.py", "paths.py"]))
    assert len(recs) == 1 and recs[0]["drift"] == 1 and recs[0]["source"] == "doc_declared"
    assert recs[0]["evidence"] == [{"file": "b.py", "line": 1}] and recs[0]["sample_size"] == 3
    rule2 = dict(rule, params={"exempt_files": [], "preset": "abs_unix_path"})
    recs2 = mc.CHECKERS["path_literal_scan"](rule2, _ctx(None, tmp_path, ["paths.py"]))
    assert recs2[0]["drift"] == 1  # 不豁免 paths.py


def test_logging_style_checker(tmp_path):
    (tmp_path / "x.py").write_text(
        'logger.info("loaded %s rows", n)\nlogger.info(f"done {n}")\nlogger.error("fail %s", e)\n')
    rule = {"id": "H11", "type": "logging_style", "statement": "日志 % 惰性禁 f-string",
            "params": {"fstring_regex": mc.FSTRING_LOG_RE.pattern, "lazy_regex": mc.LAZY_LOG_RE.pattern}}
    recs = mc.CHECKERS["logging_style"](rule, _ctx(None, tmp_path, ["x.py"]))
    assert len(recs) == 1 and recs[0]["drift"] == 1 and recs[0]["source"] == "doc_declared"
    assert recs[0]["sample_size"] == 3 and recs[0]["compliance"] == pytest.approx(2 / 3)
    assert recs[0]["evidence"] == [{"file": "x.py", "line": 2}]


def test_layering_checker_facts_and_doc(tmp_path):
    conn = sqlite3.connect(tmp_path / "cg.db")
    conn.executescript(CG_SCHEMA)
    conn.executemany("INSERT INTO nodes VALUES (?,?,?,?,?)", [
        ("a", "function", "f1", "web_ui/app.py", 1),
        ("b", "function", "f2", "factor_ic/calc.py", 1),
        ("c", "function", "f3", "web_ui/page.py", 1),
        ("d", "function", "f4", "web_ui/helper.py", 1),
        ("e", "function", "f5", "backtest/engine.py", 1),
    ])
    conn.executemany("INSERT INTO edges (source, target, kind, line) VALUES (?,?,?,?)", [
        ("a", "b", "imports", 2), ("c", "b", "imports", 2), ("e", "d", "imports", 2)])
    conn.commit()
    rule = {"id": "H1", "type": "layering", "statement": "模块边界：web_ui 只读后端",
            "params": {"forbidden": [{"from": "*", "to": "web_ui"}]}}
    recs = mc.CHECKERS["layering"](rule, _ctx(conn, tmp_path, []))
    facts = [r for r in recs if r["source"] == "code_evidence"]
    doc = [r for r in recs if r["source"] == "doc_declared"]
    pair = {r["subject"]: r for r in facts}
    assert pair["web_ui->factor_ic"]["sample_size"] == 2
    assert len(doc) == 1 and doc[0]["drift"] == 1
    assert doc[0]["evidence"] == [{"file": "backtest/engine.py", "line": 2}]
    # 空 forbidden → 纯事实，无 doc 记录
    rule2 = {"id": "import_graph", "type": "layering", "params": {"forbidden": []}}
    recs2 = mc.CHECKERS["layering"](rule2, _ctx(conn, tmp_path, []))
    assert all(r["source"] == "code_evidence" for r in recs2)


def test_skeleton_and_exit_codes_checkers(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "a.py").write_text(
        'import argparse\nfrom paths import DATA_DIR\ndef main():\n    pass\n'
        'if __name__ == "__main__":\n    main()\n')
    (tmp_path / "scripts" / "b.py").write_text("print('hi')\n")
    (tmp_path / "scripts" / "s1.py").write_text("import sys\nsys.exit(0)\n")
    files = ["scripts/a.py", "scripts/b.py", "scripts/s1.py"]
    sk = {"id": "skel", "type": "skeleton",
          "params": {"glob": "scripts/*.py", "exclude_name_prefix": ["test_"],
                     "traits": {"argparse": "import argparse", "main": "def main("}}}
    recs = mc.CHECKERS["skeleton"](sk, _ctx(None, tmp_path, files))
    by = {r["subject"]: r for r in recs}
    # 样本=a.py+b.py+s1.py 共 3 个；仅 a.py 含 argparse/main
    assert by["skel:argparse"]["sample_size"] == 3 and by["skel:argparse"]["compliance"] == pytest.approx(1 / 3)
    assert by["skel:main"]["compliance"] == pytest.approx(1 / 3)
    ec = {"id": "ec", "type": "exit_codes", "params": {"glob": "scripts/*.py"}}
    recs2 = mc.CHECKERS["exit_codes"](ec, _ctx(None, tmp_path, files))
    assert recs2[0]["source"] == "code_evidence" and "0×1" in recs2[0]["statement"]


def test_all_six_checkers_registered():
    assert set(mc.CHECKERS) == {"path_literal_scan", "logging_style", "layering", "skeleton", "util_graph", "exit_codes"}


def test_load_rules_parses_and_validates(tmp_path, capsys):
    import yaml as _yaml

    root = tmp_path / "proj"
    root.mkdir()
    rules = [{"id": "r1", "type": "layering", "statement": "s", "params": {"forbidden": []}},
             {"id": "r2", "type": "unknown_type", "params": {}},
             {"id": "r3"}]  # 缺 type
    (root / "conventions.yaml").write_text(_yaml.safe_dump({"rules": rules}), encoding="utf-8")
    got = mc.load_rules(root)
    assert [r["id"] for r in got] == ["r1"]
    err = capsys.readouterr().err
    assert "unknown_type" in err and "r3" in err


def test_load_rules_empty_and_missing(tmp_path):
    assert mc.load_rules(tmp_path / "nope") == []
    root = tmp_path / "p2"
    root.mkdir()
    (root / "conventions.yaml").write_text("rules: []\n", encoding="utf-8")
    assert mc.load_rules(root) == []


def test_load_rules_bad_yaml_aborts(tmp_path):
    root = tmp_path / "p3"
    root.mkdir()
    (root / "conventions.yaml").write_text("rules: [unclosed", encoding="utf-8")
    with pytest.raises(SystemExit):
        mc.load_rules(root)


def test_load_rules_non_dict_top_level(tmp_path, capsys):
    root = tmp_path / "p5"
    root.mkdir()
    (root / "conventions.yaml").write_text("- just\n- a\n", encoding="utf-8")
    assert mc.load_rules(root) == []
    assert "顶层非 mapping" in capsys.readouterr().err


def test_load_rules_rejects_missing_params(tmp_path, capsys):
    import yaml as _yaml

    root = tmp_path / "p6"
    root.mkdir()
    rules = [{"id": "H11", "type": "logging_style", "statement": "s",
              "params": {"fstring_regex": "x"}}]  # 缺 lazy_regex
    (root / "conventions.yaml").write_text(_yaml.safe_dump({"rules": rules}), encoding="utf-8")
    assert mc.load_rules(root) == []
    assert "H11" in capsys.readouterr().err


def test_load_rules_rejects_bad_preset_and_regex(tmp_path, capsys):
    import yaml as _yaml

    root = tmp_path / "p7"
    root.mkdir()
    rules = [{"id": "bad_preset", "type": "path_literal_scan", "params": {"preset": "abs_mac_path"}},
             {"id": "bad_regex", "type": "path_literal_scan", "params": {"regex": "("}}]
    (root / "conventions.yaml").write_text(_yaml.safe_dump({"rules": rules}), encoding="utf-8")
    assert mc.load_rules(root) == []
    err = capsys.readouterr().err
    assert "bad_preset" in err and "bad_regex" in err


def test_run_rules_fallback_import_graph(tmp_path):
    cg = _fixture_cg(tmp_path)
    repo = _git_repo(tmp_path)  # 无 conventions.yaml 的 git 仓库（cg.db 同目录不冲突）
    records = mc._run_rules(cg, repo, [])
    assert records and all(r["source"] == "code_evidence" for r in records)
    assert all("->" in r["subject"] for r in records)


def test_main_soft_degradation_stderr(tmp_path, capsys):
    out = tmp_path / "out.db"
    # 非 git 目录 + 无 codegraph db → 两条软降级警告，main 仍 exit 0
    assert mc.main(["--root", str(tmp_path / "notgit"), "--codegraph-db", str(tmp_path / "no.db"),
                    "--out", str(out)]) == 0
    err = capsys.readouterr().err
    assert "非 git" in err or "codegraph db 缺失" in err


def _git_repo(tmp_path):
    import subprocess

    repo = tmp_path / "p4"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"], cwd=repo, check=True)
    return repo


def test_main_dispatches_registered_checker(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path)
    (repo / "conventions.yaml").write_text(
        "rules:\n  - id: stub\n    type: stub_type\n    params: {}\n", encoding="utf-8")

    def stub_check(rule, ctx):
        return [_record(subject=rule["id"])]

    monkeypatch.setitem(mc.CHECKERS, "stub_type", stub_check)
    out = tmp_path / "out.db"
    # 无 codegraph db → 软降级 cg=None（P2 行为），stub checker 不依赖 cg
    assert mc.main(["--root", str(repo), "--out", str(out)]) == 0
    rows = sqlite3.connect(f"file:{out}?mode=ro", uri=True).execute(
        "SELECT subject FROM conventions").fetchall()
    assert rows == [("stub",)]


def _repo_with_commits(tmp_path, files_with_dates):
    """files_with_dates: {relpath: (content, days_ago)}——按日期倒序提交（git 允许 --date 历史）。"""
    import subprocess

    repo = tmp_path / "proj"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    import time

    for rel, (content, days_ago) in sorted(files_with_dates.items(), key=lambda kv: kv[1][1]):
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        date = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - days_ago * 86400))
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", rel,
                        "--date", date], cwd=repo, check=True)
    return repo


def test_file_ages_and_none_on_missing_git(tmp_path):
    repo = _repo_with_commits(tmp_path, {"a.py": ("x=1\n", 10), "sub/b.py": ("y=2\n", 400)})
    ages = mc._file_ages(repo, ["a.py", "sub/b.py", "gone.py"])
    assert ages["a.py"] is not None and ages["a.py"] > ages["sub/b.py"]
    assert ages["gone.py"] is None


def test_g1_logging_majority_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "MIN_SAMPLE", 2)  # fixture 样本量 3 < 默认 20
    monkeypatch.setattr(mc, "SUPPORT_MIN", 0.5)  # support 2/3=0.67 < 默认 0.90
    repo = _repo_with_commits(tmp_path, {
        "new1.py": ('logger.info("a %s", x)\n', 10),
        "new2.py": ('logger.info("b %s", y)\n', 20),
        "old.py": ('logger.info(f"c {z}")\n', 800),
    })
    cands = mc._g1_logging_majority(["new1.py", "new2.py", "old.py"], repo)
    assert len(cands) == 1
    c = cands[0]
    assert c["source"] == "inferred" and c["drift"] == 0
    assert c["subject"] == "inferred:logging:lazy_percent"
    assert c["compliance"] == pytest.approx(2 / 3)
    assert c["evidence"] == [{"file": "old.py", "line": 1}]  # 少数派侧证据
    assert "新近" in c["statement"] or "遗留" in c["statement"]


def test_g1_fstring_majority_has_evidence_and_recency(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "MIN_SAMPLE", 2)  # fixture 样本量 10 < 默认 20
    files = {f"f{i}.py": ('logger.info(f"x {v}")\n', 30) for i in range(9)}
    files["lazy.py"] = ('logger.info("y %s", v)\n', 800)
    repo = _repo_with_commits(tmp_path, files)
    cands = mc._g1_logging_majority(sorted(files), repo)
    assert len(cands) == 1
    c = cands[0]
    assert c["subject"] == "inferred:logging:fstring"
    assert c["evidence"] and c["evidence"][0]["file"] == "lazy.py"
    assert "更早 1 处" in c["statement"]
    assert c["compliance"] == pytest.approx(0.9)


def test_mine_candidates_suppressed_by_manual_rule_and_dismissed(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "MIN_SAMPLE", 1)  # fixture 样本量 1 < 默认 20（同 G1 测试口径）
    repo = _repo_with_commits(tmp_path, {"a.py": ('logger.info("x %s", v)\n', 5)})
    files = ["a.py"]
    manual = [{"id": "H11", "type": "logging_style",
               "params": {"fstring_regex": mc.FSTRING_LOG_RE.pattern, "lazy_regex": mc.LAZY_LOG_RE.pattern}}]
    assert mc.mine_candidates(None, repo, files, manual, []) == []
    cands = mc.mine_candidates(None, repo, files, [], [])
    assert cands and cands[0]["source"] == "inferred"
    assert mc.mine_candidates(None, repo, files, [], [cands[0]["subject"]]) == []


def test_g2_util_concentration(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "MIN_SAMPLE", 2)  # fixture 样本量 4 < 默认 20
    conn = sqlite3.connect(tmp_path / "cg.db")
    conn.executescript(CG_SCHEMA)
    nodes = [("u1", "function", "load", "common/loader.py", 1),
             ("m1", "function", "a", "web/app.py", 1), ("m2", "function", "b", "svc/b.py", 1),
             ("m3", "function", "c", "svc/c.py", 1), ("m4", "function", "d", "dao/d.py", 1)]
    conn.executemany("INSERT INTO nodes VALUES (?,?,?,?,?)", nodes)
    edges = [("m1", "u1", "references", 2), ("m2", "u1", "references", 3),
             ("m3", "u1", "references", 4), ("m4", "u1", "references", 5),
             ("m1", "m2", "references", 6)]  # 干扰边：非 common 目标
    conn.executemany("INSERT INTO edges (source, target, kind, line) VALUES (?,?,?,?)", edges)
    conn.commit()
    cands = mc._g2_util_concentration(conn, ["web/app.py", "svc/b.py", "svc/c.py", "dao/d.py"])
    assert len(cands) == 1
    c = cands[0]
    assert c["subject"].startswith("inferred:util_graph:")
    assert "common.loader" in c["subject"] and c["sample_size"] == 4
    assert c["source"] == "inferred" and c["drift"] == 0


def test_load_dismissed(tmp_path):
    (tmp_path / "conventions.yaml").write_text("dismissed:\n  - inferred:logging:lazy_percent\n", encoding="utf-8")
    assert mc.load_dismissed(tmp_path) == ["inferred:logging:lazy_percent"]
    assert mc.load_dismissed(tmp_path / "nope") == []


def test_load_dismissed_scalar_silently_inactive(tmp_path):
    (tmp_path / "conventions.yaml").write_text("dismissed: inferred:logging:lazy_percent\n", encoding="utf-8")
    assert mc.load_dismissed(tmp_path) == []  # 标量写法不生效（抑制静默失败）


def test_git_tracked_sources_includes_java(tmp_path):
    import subprocess

    repo = tmp_path / "proj"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "a.py").write_text("x = 1\n")
    (repo / "src").mkdir()
    (repo / "src" / "B.java").write_text("class B {}\n")
    (repo / "src" / "c.txt").write_text("noise\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"],
                   cwd=repo, check=True)
    files = mc._git_tracked_sources(repo)
    assert sorted(files) == ["a.py", "src/B.java"]
