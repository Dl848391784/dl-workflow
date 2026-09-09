"""bin/doctor.py 冒烟：裸仓库不崩、分节输出、退出码语义。对应远程接入诊断场景。"""

import importlib.util
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))


def _load():
    path = Path(__file__).resolve().parents[1] / "bin" / "doctor.py"
    spec = importlib.util.spec_from_file_location("doctor", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git_repo(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"],
                   cwd=repo, check=True)
    return repo


def test_doctor_bare_repo_reports_failures(tmp_path, capsys):
    doctor = _load()
    repo = _git_repo(tmp_path)
    assert doctor.main(["--project", str(repo), "--home", str(tmp_path / "no-home")]) == 1
    out = capsys.readouterr().out
    assert "1. 接线" in out and "2. codegraph" in out and "3. conventions" in out
    assert "4. inject" in out and "5. 环境" in out
    assert "❌" in out and "═══ 结束" in out


class TestCheckEngine:
    def test_claude_binary_present(self, monkeypatch):
        monkeypatch.delenv("DL_ENGINE", raising=False)
        from doctor import check_engine
        results = check_engine()
        # claude 已装环境应过；断言键存在即可（机差异不钉布尔值）
        assert any("claude" in msg for _, msg in results)

    def _fresh_dl_engine(self, monkeypatch):
        """dl_engine 重导入防 import 期冻结（config_root 读 QODER_CONFIG_DIR）。"""
        import sys as _sys

        old = _sys.modules.pop("dl_engine", None)
        return old

    def _restore_dl_engine(self, old):
        import sys as _sys

        if old is not None:
            _sys.modules["dl_engine"] = old
        else:
            _sys.modules.pop("dl_engine", None)

    def test_qoder_authenticated_models_ok(self, monkeypatch):
        """认证且能列模型 → ✅（BYOK/内置不问，2026-09-09 用户裁决）。"""
        monkeypatch.setenv("DL_ENGINE", "qodercli")
        old = self._fresh_dl_engine(monkeypatch)

        class FakeProc:
            returncode = 0
            stdout = "MODEL\nQwen3.8-Max\ndeepseek/deepseek-v4-flash-pg\n"

        try:
            monkeypatch.setattr("subprocess.run", lambda *a, **kw: FakeProc())
            from doctor import check_engine

            results = check_engine()
        finally:
            self._restore_dl_engine(old)
        auth = [ok for ok, msg in results if "认证" in msg]
        assert auth and auth[0] is True

    def test_qoder_unauthenticated_warns(self, monkeypatch):
        """--list-models 非零退出 → ❌ 提示登录（非 BYOK 文案）。"""
        monkeypatch.setenv("DL_ENGINE", "qodercli")
        old = self._fresh_dl_engine(monkeypatch)

        class FakeProc:
            returncode = 1
            stdout = ""

        try:
            monkeypatch.setattr("subprocess.run", lambda *a, **kw: FakeProc())
            from doctor import check_engine

            results = check_engine()
        finally:
            self._restore_dl_engine(old)
        auth = [ok for ok, msg in results if "认证" in msg]
        assert auth and auth[0] is False
        assert "login" in results[[i for i, (ok, m) in enumerate(results) if "认证" in m][0]][1]

    def test_unknown_engine_reported_not_crash(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("DL_ENGINE", "gemini")
        doctor = _load()
        repo = _git_repo(tmp_path)
        rc = doctor.main(["--project", str(repo), "--home", str(tmp_path / "no-home")])
        out = capsys.readouterr().out
        assert "未知引擎" in out  # 转为 ❌ 检查项，不穿透崩报告
        assert "2. codegraph" in out  # 后续节照常出——整份报告不丢
        assert rc == 1

    def test_doctor_main_includes_engine_check(self, tmp_path, capsys):
        doctor = _load()
        repo = _git_repo(tmp_path)
        doctor.main(["--project", str(repo), "--home", str(tmp_path / "no-home")])
        out = capsys.readouterr().out
        assert "引擎 binary" in out
