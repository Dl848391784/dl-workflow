"""setup_project.py 单元测试：post-commit 幂等补丁 / 项目 settings 合并 / 接线报告。

对应 designs/setup-installer-design.md §setup 脚本结构。fixture=tmp git repo + 假 home。
"""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


def _load():
    path = Path(__file__).resolve().parents[1] / "scripts" / "setup" / "setup_project.py"
    spec = importlib.util.spec_from_file_location("setup_project", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git_repo(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"], cwd=repo, check=True)
    return repo


def test_patch_post_commit_idempotent(tmp_path):
    sp = _load()
    repo = _git_repo(tmp_path)
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.write_text("#!/bin/sh\ncodegraph sync >/dev/null 2>&1 &\nexit 0\n")
    status = sp.patch_post_commit(repo, tmp_path / "home")
    text = hook.read_text()
    assert "mine_conventions.py" in text and "codegraph sync" in text and status == "patched"
    status2 = sp.patch_post_commit(repo, tmp_path / "home")
    assert text == hook.read_text() and status2 == "already-ok"


def test_patch_post_commit_creates_missing(tmp_path):
    sp = _load()
    repo = _git_repo(tmp_path)
    hook = repo / ".git" / "hooks" / "post-commit"
    if hook.exists():
        hook.unlink()
    assert sp.patch_post_commit(repo, tmp_path / "home") == "created"
    assert "mine_conventions.py" in hook.read_text()


def test_patch_post_commit_upgrades_stale_home(tmp_path):
    """home 变化（worktree -> ~/.dl-workflow 收口）时 mark 在但内嵌路径已死 -> 原地升级。"""
    sp = _load()
    repo = _git_repo(tmp_path)
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.write_text(
        '#!/bin/sh\ncodegraph sync >/dev/null 2>&1 &\n'
        'python3 "/old/home/bin/mine_conventions.py" >/dev/null 2>&1 &\nexit 0\n'
    )
    status = sp.patch_post_commit(repo, tmp_path / "home")
    text = hook.read_text()
    assert status == "upgraded"
    assert "/old/home" not in text and str(tmp_path / "home") in text


def test_merge_project_settings_appends_and_idempotent(tmp_path):
    sp = _load()
    repo = _git_repo(tmp_path)
    home = tmp_path / "dlwf"
    (home / "hooks").mkdir(parents=True)
    for name in ("codegraph_inject.py", "conventions_inject.py"):
        (home / "hooks" / name).write_text("# stub\n")
    before = sp.merge_project_settings(repo, home)
    settings = json.loads((repo / ".claude" / "settings.json").read_text())
    cmds = [h["command"] for g in settings["hooks"]["UserPromptSubmit"] for h in g["hooks"]]
    assert any("codegraph_inject.py" in c for c in cmds)
    assert any("conventions_inject.py" in c for c in cmds)
    assert all(str(home) in c for c in cmds)
    after = sp.merge_project_settings(repo, home)
    assert before["added"] == 2 and after["added"] == 0 and after["kept"] == 2


def test_merge_project_settings_upgrades_stale_home(tmp_path):
    """旧 home 注册（精确串判重永不匹配）按 basename 命中 -> 原地替换为 canonical。"""
    sp = _load()
    repo = _git_repo(tmp_path)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [
            {"type": "command", "command": 'python3 "/old/home/hooks/codegraph_inject.py"'}]}]}})
    )
    home = tmp_path / "dlwf"
    (home / "hooks").mkdir(parents=True)
    for name in ("codegraph_inject.py", "conventions_inject.py"):
        (home / "hooks" / name).write_text("# stub\n")
    result = sp.merge_project_settings(repo, home)
    settings = json.loads((repo / ".claude" / "settings.json").read_text())
    cmds = [h["command"] for g in settings["hooks"]["UserPromptSubmit"] for h in g["hooks"]]
    assert not any("/old/home" in c for c in cmds)
    assert f'python3 "{home}/hooks/codegraph_inject.py"' in cmds
    assert f'python3 "{home}/hooks/conventions_inject.py"' in cmds
    assert result["upgraded"] >= 1


def test_merge_project_settings_preserves_existing(tmp_path):
    sp = _load()
    repo = _git_repo(tmp_path)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [
            {"type": "command", "command": "echo existing"}]}]}})
    )
    home = tmp_path / "dlwf"
    (home / "hooks").mkdir(parents=True)
    for name in ("codegraph_inject.py", "conventions_inject.py"):
        (home / "hooks" / name).write_text("# stub\n")
    sp.merge_project_settings(repo, home)
    settings = json.loads((repo / ".claude" / "settings.json").read_text())
    cmds = [h["command"] for g in settings["hooks"]["UserPromptSubmit"] for h in g["hooks"]]
    assert "echo existing" in cmds


def test_merge_project_settings_empty_event_list(tmp_path):
    """strip 后 UserPromptSubmit=[]（键在但组摘空，factor 仓自举实爆 IndexError）。"""
    sp = _load()
    repo = _git_repo(tmp_path)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"UserPromptSubmit": []}})
    )
    home = tmp_path / "dlwf"
    (home / "hooks").mkdir(parents=True)
    for name in ("codegraph_inject.py", "conventions_inject.py"):
        (home / "hooks" / name).write_text("# stub\n")
    merged = sp.merge_project_settings(repo, home)
    settings = json.loads((repo / ".claude" / "settings.json").read_text())
    cmds = [h["command"] for g in settings["hooks"]["UserPromptSubmit"] for h in g["hooks"]]
    assert len(cmds) == 2 and merged["added"] == 2


def test_merge_project_settings_aborts_on_bad_json(tmp_path):
    sp = _load()
    repo = _git_repo(tmp_path)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text("{not json")
    home = tmp_path / "dlwf"
    (home / "hooks").mkdir(parents=True)
    with pytest.raises(SystemExit):
        sp.merge_project_settings(repo, home)


def test_ensure_conventions_yaml_creates_and_idempotent(tmp_path):
    sp = _load()
    repo = _git_repo(tmp_path)
    assert sp.ensure_conventions_yaml(repo) == "created"
    text = (repo / "conventions.yaml").read_text(encoding="utf-8")
    assert "rules:" in text and "path_literal_scan" in text and "#" in text
    assert sp.ensure_conventions_yaml(repo) == "already-ok"
    assert (repo / "conventions.yaml").read_text(encoding="utf-8") == text


def _fake_home(tmp_path):
    home = tmp_path / "dlwf"
    (home / "hooks").mkdir(parents=True)
    for name in ("codegraph_inject.py", "conventions_inject.py"):
        (home / "hooks" / name).write_text(
            "import json,sys\n"
            "json.load(sys.stdin)\n"
            "print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit',"
            " 'additionalContext': 'stub'}}))\n")
    return home


def _fake_dbs(repo):
    import sqlite3

    (repo / ".conventions").mkdir(exist_ok=True)
    conn = sqlite3.connect(repo / ".conventions" / "conventions.db")
    conn.execute("CREATE TABLE conventions (id INTEGER)")
    conn.execute("INSERT INTO conventions VALUES (1)")
    conn.commit()
    conn.close()
    (repo / ".codegraph").mkdir(exist_ok=True)
    conn = sqlite3.connect(repo / ".codegraph" / "codegraph.db")
    conn.execute("CREATE TABLE nodes (id TEXT)")
    conn.execute("INSERT INTO nodes VALUES ('n1')")
    conn.commit()
    conn.close()


def test_verify_project_all_ok(tmp_path):
    sp = _load()
    repo = _git_repo(tmp_path)
    home = _fake_home(tmp_path)
    sp.patch_post_commit(repo, home)
    sp.merge_project_settings(repo, home)
    _fake_dbs(repo)
    checks = sp.verify_project(repo, home)
    assert all(ok for _, ok, _ in checks), checks
    names = [n for n, _, _ in checks]
    assert any("settings.json" in n for n in names)
    assert any("post-commit" in n for n in names)
    assert any("codegraph_inject" in n for n in names)
    assert any("conventions_inject" in n for n in names)


def test_verify_project_reports_failures(tmp_path):
    sp = _load()
    repo = _git_repo(tmp_path)
    home = _fake_home(tmp_path)
    # 什么都不接线 → 全部 ❌（6 项），不抛异常
    checks = sp.verify_project(repo, home)
    assert not any(ok for _, ok, _ in checks)
    assert len(checks) == 6


def test_main_verify_mode_exit_codes(tmp_path, capsys):
    sp = _load()
    repo = _git_repo(tmp_path)
    home = _fake_home(tmp_path)
    sp.patch_post_commit(repo, home)
    sp.merge_project_settings(repo, home)
    assert sp.main(["--project", str(repo), "--home", str(home), "--verify",
                    "--skip-index", "--skip-distill"]) == 0
    capsys.readouterr()
    assert sp.main(["--project", str(_git_repo(tmp_path / "other")), "--home", str(home),
                    "--verify", "--skip-index", "--skip-distill"]) == 1
    out = capsys.readouterr().out
    assert "❌" in out


def test_verify_project_smoke_timeout_marks_fail_not_raise(tmp_path, monkeypatch):
    """冒烟 subprocess 超时/OSError -> 记 ❌ 不 traceback，其余检查照常跑（best-effort 语义）。"""
    sp = _load()
    repo = _git_repo(tmp_path)
    home = _fake_home(tmp_path)
    sp.patch_post_commit(repo, home)
    sp.merge_project_settings(repo, home)
    _fake_dbs(repo)

    def _boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd=a[0] if a else "hook", timeout=15)

    monkeypatch.setattr(sp.subprocess, "run", _boom)
    checks = sp.verify_project(repo, home)
    assert len(checks) == 6
    smoke = [(n, ok, d) for n, ok, d in checks if "inject 冒烟" in n]
    assert len(smoke) == 2 and all(not ok for _, ok, _ in smoke)
    assert all("无法执行: TimeoutExpired" in d for _, _, d in smoke)
    rest = [(n, ok) for n, ok, _ in checks if "inject 冒烟" not in n]
    assert all(ok for _, ok in rest), rest


def test_filter_skipped_flag_combos():
    """skip 标志过滤为纯函数，verify/接线两路共用同一谓词。"""
    sp = _load()
    checks = [
        ("settings.json inject 注册", True, "ok"),
        ("post-commit 双后台任务", True, "ok"),
        ("inject 冒烟 codegraph_inject.py", True, "ok"),
        ("inject 冒烟 conventions_inject.py", True, "ok"),
        ("conventions db 可读", False, "db 缺失"),
        ("codegraph db 已索引", False, "db 缺失"),
    ]
    assert len(sp._filter_skipped(checks, False, False)) == 6
    skip_index = sp._filter_skipped(checks, True, False)
    assert len(skip_index) == 5 and all("codegraph db" not in n for n, _, _ in skip_index)
    skip_distill = sp._filter_skipped(checks, False, True)
    assert len(skip_distill) == 5 and all("conventions db" not in n for n, _, _ in skip_distill)
    both = sp._filter_skipped(checks, True, True)
    assert len(both) == 4
    assert all(ok for _, ok, _ in both)  # 两个 db ❌ 被滤掉后 verdict 不再误报
