# tests/test_project_inject_hooks.py
"""集中版 inject hooks 单元测试：payload.cwd 项目根解析 + 注入协议 + 永不阻断。

对应 designs/setup-installer-design.md。fixture=tmp git repo（.codegraph/.conventions db 手造），
hook 经 subprocess 喂 stdin payload（端到端，同 test_codegraph_gate.py 风格）。
"""

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1] / "hooks"


def _load(name, rel):
    path = Path(__file__).resolve().parents[1] / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git_repo(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "x.py").write_text("def foo():\n    pass\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=repo,
        check=True,
    )
    return repo


def _payload(repo, prompt="看下 foo"):
    return json.dumps({"prompt": prompt, "cwd": str(repo)})


def _run_hook(script, repo, payload):
    return subprocess.run(
        [sys.executable, str(HOOKS / script)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=repo,
    )


def _mk_codegraph_db(repo):
    db = repo / ".codegraph" / "codegraph.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE files (path TEXT, indexed_at INTEGER)")
    conn.execute(
        "CREATE TABLE nodes (name TEXT, kind TEXT, file_path TEXT, start_line INTEGER)"
    )
    conn.execute("INSERT INTO files VALUES ('x.py', 1757059200000)")
    conn.execute("INSERT INTO nodes VALUES ('foo', 'function', 'x.py', 1)")
    conn.commit()
    conn.close()


def _mk_conventions_db(repo, drift=1):
    db = repo / ".conventions" / "conventions.db"
    db.parent.mkdir(parents=True)
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
    conn.execute(
        "INSERT INTO conventions (dimension, subject, statement, source, sample_size,"
        " compliance, drift, evidence, generated_at, commit_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "d3_style",
            "H11 日志风格",
            "f-string 1 处",
            "doc_declared",
            942,
            1.0,
            drift,
            "[]",
            "2026-09-05T00:00:00",
            "abc",
        ),
    )
    conn.execute(
        "INSERT INTO conventions (dimension, subject, statement, source, sample_size,"
        " compliance, drift, evidence, generated_at, commit_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "inferred",
            "inferred:util_graph:common.loader",
            "候选规范：公共工具引用集中于 common.loader（4 个模块引用）——新代码应优先复用而非新造",
            "inferred",
            4,
            None,
            0,
            "[]",
            "2026-09-05T00:00:00",
            "abc",
        ),
    )
    conn.execute("INSERT INTO meta VALUES ('commit_hash', 'abc')")
    conn.commit()
    conn.close()


def test_project_root_prefers_payload_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # 进程 cwd 与 payload cwd 不同
    hooks = _load("cginject", "hooks/codegraph_inject.py")
    repo = _git_repo(tmp_path)
    assert hooks._project_root({"cwd": str(repo)}) == repo


def test_codegraph_inject_uses_project_db(tmp_path):
    repo = _git_repo(tmp_path)
    _mk_codegraph_db(repo)
    proc = _run_hook("codegraph_inject.py", repo, _payload(repo, "foo 是谁"))
    assert proc.returncode == 0
    ctx = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "foo" in ctx and "x.py" in ctx


def test_conventions_inject_drifts_and_never_blocks(tmp_path):
    repo = _git_repo(tmp_path)
    _mk_conventions_db(repo, drift=1)
    proc = _run_hook("conventions_inject.py", repo, _payload(repo))
    assert proc.returncode == 0
    ctx = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "H11 日志风格" in ctx
    assert "inferred:util_graph:common.loader" in ctx  # inferred 候选出 🔍 区
    assert "候选规范" in ctx


def test_conventions_inject_candidates_trigger_without_drift(tmp_path):
    """无漂移且无 stale（commit_hash 'abc' 无法 rev-list）时，inferred 候选单独触发注入。"""
    repo = _git_repo(tmp_path)
    _mk_conventions_db(repo, drift=0)
    proc = _run_hook("conventions_inject.py", repo, _payload(repo))
    assert proc.returncode == 0
    ctx = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "🔍" in ctx and "inferred:util_graph:common.loader" in ctx
    assert "H11 日志风格" not in ctx  # drift=0 不进漂移区


def test_conventions_inject_silent_without_db(tmp_path):
    repo = _git_repo(tmp_path)
    proc = _run_hook("conventions_inject.py", repo, _payload(repo))
    assert proc.returncode == 0 and proc.stdout == ""


def test_conventions_inject_silent_on_bad_stdin(tmp_path):
    repo = _git_repo(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(HOOKS / "conventions_inject.py")],
        input=b"\x00\xff not json",
        capture_output=True,
        text=False,
        cwd=repo,
    )
    assert proc.returncode == 0
    assert proc.stdout == b""
    assert b"Traceback" not in proc.stderr


def test_project_root_maps_worktree_to_main(tmp_path):
    import subprocess as sp

    hooks = _load("cginject", "hooks/codegraph_inject.py")
    repo = _git_repo(tmp_path)
    _mk_codegraph_db(repo)                      # 主仓有 db
    wt = tmp_path / "wt"
    sp.run(["git", "worktree", "add", str(wt), "-b", "feat-x"], cwd=repo, check=True,
           capture_output=True)
    assert hooks._project_root({"cwd": str(wt)}) == repo


def test_project_root_keeps_worktree_without_main_db(tmp_path):
    import subprocess as sp

    hooks = _load("cvinject", "hooks/conventions_inject.py")
    repo = _git_repo(tmp_path)                   # 主仓无 .conventions db
    wt = tmp_path / "wt2"
    sp.run(["git", "worktree", "add", str(wt), "-b", "feat-y"], cwd=repo, check=True,
           capture_output=True)
    assert hooks._project_root({"cwd": str(wt)}) == Path(str(wt)).resolve()
