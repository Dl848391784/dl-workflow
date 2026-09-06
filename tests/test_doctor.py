"""bin/doctor.py 冒烟：裸仓库不崩、分节输出、退出码语义。对应远程接入诊断场景。"""

import importlib.util
import subprocess
from pathlib import Path


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
    assert "❌" in out and "═══ 结束" in out
