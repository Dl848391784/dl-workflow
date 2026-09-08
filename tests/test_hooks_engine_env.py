"""hooks 双引擎 env fallback 链（P0：qoder 注入 QODER_* + CLAUDE_PROJECT_DIR 别名）。"""
import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"


def _load(name: str):
    """按路径加载 hook 模块（hooks 非 package，文件名即模块名）。"""
    spec = importlib.util.spec_from_file_location(name, HOOKS_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestSessionIdChain:
    def test_fence_prefers_qoder_env(self, monkeypatch):
        monkeypatch.setenv("QODER_SESSION_ID", "q-sid")
        monkeypatch.setenv("CLAUDE_SESSION_ID", "c-sid")
        fence = _load("workflow_step_fence")
        assert fence._session_id({}) == "q-sid"

    def test_fence_falls_back_to_claude_env(self, monkeypatch):
        monkeypatch.delenv("QODER_SESSION_ID", raising=False)
        monkeypatch.setenv("CLAUDE_SESSION_ID", "c-sid")
        fence = _load("workflow_step_fence")
        assert fence._session_id({}) == "c-sid"

    def test_payload_still_wins(self, monkeypatch):
        monkeypatch.setenv("QODER_SESSION_ID", "q-sid")
        fence = _load("workflow_step_fence")
        assert fence._session_id({"session_id": "p-sid"}) == "p-sid"


class TestProjectDirChain:
    """inject 两文件的 _project_root 为函数内读 env（非模块级常量），直接调函数断言。

    subprocess.run 被替换为记录 cwd 的 fake：payload {} 时首个候选即 env 链胜者，
    QODER_PROJECT_DIR 优先于 CLAUDE_PROJECT_DIR。
    """

    @staticmethod
    def _patch_subprocess(mod, monkeypatch, cwds):
        def fake_run(*args, **kwargs):
            cwds.append(kwargs.get("cwd"))
            if "--show-toplevel" in (args[0] if args else []):
                return types.SimpleNamespace(returncode=0, stdout="/fake-root\n")
            return types.SimpleNamespace(returncode=1, stdout="")

        monkeypatch.setattr(
            mod, "subprocess",
            types.SimpleNamespace(run=fake_run, TimeoutExpired=subprocess.TimeoutExpired),
        )

    @pytest.mark.parametrize("mod_name", ["codegraph_inject", "conventions_inject"])
    def test_prefers_qoder_project_dir(self, mod_name, monkeypatch):
        monkeypatch.setenv("QODER_PROJECT_DIR", "/qoder-dir")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/claude-dir")
        mod = _load(mod_name)
        cwds = []
        self._patch_subprocess(mod, monkeypatch, cwds)
        assert mod._project_root({}) == Path("/fake-root")
        assert cwds[0] == "/qoder-dir"

    @pytest.mark.parametrize("mod_name", ["codegraph_inject", "conventions_inject"])
    def test_falls_back_to_claude_project_dir(self, mod_name, monkeypatch):
        monkeypatch.delenv("QODER_PROJECT_DIR", raising=False)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/claude-dir")
        mod = _load(mod_name)
        cwds = []
        self._patch_subprocess(mod, monkeypatch, cwds)
        assert mod._project_root({}) == Path("/fake-root")
        assert cwds[0] == "/claude-dir"
