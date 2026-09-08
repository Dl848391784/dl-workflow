"""dl_engine 引擎 profile 单源测试（designs/qodercli-engine-profile-design.md §P1）。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dl_engine  # noqa: E402


class TestGetEngine:
    def test_default_is_claude(self, monkeypatch):
        monkeypatch.delenv("DL_ENGINE", raising=False)
        eng = dl_engine.get_engine()
        assert eng.name == "claude"
        assert eng.binary == "claude"

    def test_qodercli_profile(self, monkeypatch):
        monkeypatch.setenv("DL_ENGINE", "qodercli")
        eng = dl_engine.get_engine()
        assert eng.name == "qodercli"
        assert eng.binary == "qodercli"
        assert eng.config_root == Path.home() / ".qoder"
        assert eng.project_resource_dir == ".qoder"
        assert eng.permission_cli_value == "accept_edits"
        assert eng.usage_metered is False

    def test_unknown_engine_hard_fails(self, monkeypatch):
        monkeypatch.setenv("DL_ENGINE", "gemini")
        with pytest.raises(SystemExit) as exc_info:
            dl_engine.get_engine()
        assert exc_info.value.code == 2

    def test_empty_env_is_claude(self, monkeypatch):
        monkeypatch.setenv("DL_ENGINE", "")
        assert dl_engine.get_engine().name == "claude"


class TestArgsComposition:
    """cmd 碎片 golden——claude 必须与现状逐位一致（回归承重墙）。"""

    def test_claude_golden(self, monkeypatch):
        monkeypatch.delenv("DL_ENGINE", raising=False)
        eng = dl_engine.get_engine()
        assert eng.permission_args() == ["--permission-mode", "acceptEdits"]
        assert eng.verbose_args() == ["--verbose"]
        assert eng.debug_args(Path("/tmp/x.log")) == [
            "--debug",
            "api,hooks",
            "--debug-file",
            "/tmp/x.log",
        ]
        assert eng.disallow_ask_args() == ["--disallowedTools", "AskUserQuestion"]

    def test_qoder_golden(self, monkeypatch):
        monkeypatch.setenv("DL_ENGINE", "qodercli")
        eng = dl_engine.get_engine()
        assert eng.permission_args() == ["--permission-mode", "accept_edits"]
        assert eng.verbose_args() == []  # P0 D1：无 --verbose
        assert eng.debug_args(Path("/tmp/x.log")) == [
            "--debug"
        ]  # P0 D2：无 --debug-file
        assert eng.disallow_ask_args() == []  # P0 D4：无 AskUserQuestion

    def test_skills_dir_display(self, monkeypatch):
        monkeypatch.delenv("DL_ENGINE", raising=False)
        assert dl_engine.get_engine().skills_dir_display == "~/.claude/skills"
        monkeypatch.setenv("DL_ENGINE", "qodercli")
        assert dl_engine.get_engine().skills_dir_display == "~/.qoder/skills"


class TestTranscriptProjectsRoot:
    """D14：transcript 根按引擎（E2E 冒烟实测 qoder 段 transcript 落 ~/.qoder/projects）。"""

    def test_claude_root(self, monkeypatch):
        monkeypatch.delenv("DL_ENGINE", raising=False)
        eng = dl_engine.get_engine()
        assert eng.transcript_projects_root() == Path.home() / ".claude" / "projects"

    def test_qoder_root(self, monkeypatch):
        monkeypatch.setenv("DL_ENGINE", "qodercli")
        eng = dl_engine.get_engine()
        assert eng.transcript_projects_root() == Path.home() / ".qoder" / "projects"
