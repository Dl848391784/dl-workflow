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
    repo.mkdir()
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
