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

    def test_qoder_byok_unregistered_warns(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DL_ENGINE", "qodercli")
        monkeypatch.setenv("QODER_CONFIG_DIR", str(tmp_path))  # 空目录=无 settings.json
        # config_root 在 dl_engine 模块导入时冻结——强制重导入使 env 生效；
        # 旧模块保存/恢复，避免残留冻结实例造成顺序依赖污染
        old = sys.modules.pop("dl_engine", None)
        try:
            from doctor import check_engine
            results = check_engine()
        finally:
            if old is not None:
                sys.modules["dl_engine"] = old
            else:
                sys.modules.pop("dl_engine", None)
        byok = [ok for ok, msg in results if "BYOK" in msg]
        assert byok and byok[0] is False  # 未注册 → False（warn 级由主流程定）

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
