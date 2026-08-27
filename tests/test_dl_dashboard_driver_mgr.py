"""dl_dashboard.driver_mgr：driver 生命周期（mock subprocess）。"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from dl_dashboard.driver_mgr import DriverManager


def _mgr(tmp_path) -> DriverManager:
    return DriverManager(dlwf=tmp_path / "dlwf", runtime_dir=tmp_path / "run")


def test_start_spawns_setsid_and_writes_pid(tmp_path):
    mgr = _mgr(tmp_path)
    fake = MagicMock()
    fake.pid = 4242
    fake.poll.return_value = None
    with patch("dl_dashboard.driver_mgr.subprocess.Popen", return_value=fake) as pop:
        pid = mgr.start(Path("/p"), "demo", Path("/p/.claude/worktrees/demo"))
    assert pid == 4242
    args, kwargs = pop.call_args
    assert kwargs["start_new_session"] is True          # setsid 独立进程组
    assert kwargs["cwd"] == "/p/.claude/worktrees/demo"
    assert kwargs["stdin"] is not None                  # DEVNULL
    assert "dl_drive.py" in args[0][1]
    assert mgr._pid_path(mgr.slug("/p", "demo")).read_text().strip() == "4242"
    assert mgr.alive(Path("/p"), "demo") == 4242


def test_alive_returns_none_when_exited(tmp_path):
    mgr = _mgr(tmp_path)
    fake = MagicMock()
    fake.pid = 4242
    fake.poll.return_value = 1                          # 已退出
    with patch("dl_dashboard.driver_mgr.subprocess.Popen", return_value=fake):
        mgr.start(Path("/p"), "demo", Path("/wt"))
    assert mgr.alive(Path("/p"), "demo") is None


def test_alive_claims_pid_file_after_backend_restart(tmp_path):
    """后端重启（内存空）-> 读 pid 文件 + /proc cmdline 校验认领。"""
    mgr = _mgr(tmp_path)
    mgr._pid_path(mgr.slug("/p", "demo")).write_text(str(os.getpid()), encoding="utf-8")
    real = f"python3 /x/dl_drive.py demo".encode()
    with patch("dl_dashboard.driver_mgr.Path.read_bytes", return_value=real):
        assert mgr.alive(Path("/p"), "demo") == os.getpid()


def test_alive_rejects_recycled_pid(tmp_path):
    """pid 复用防护：cmdline 不含 dl_drive + 工作流名 -> 不认领。"""
    mgr = _mgr(tmp_path)
    mgr._pid_path(mgr.slug("/p", "demo")).write_text(str(os.getpid()), encoding="utf-8")
    with patch("dl_dashboard.driver_mgr.Path.read_bytes", return_value=b"/usr/bin/other"):
        assert mgr.alive(Path("/p"), "demo") is None


def test_stop_kills_process_group(tmp_path):
    mgr = _mgr(tmp_path)
    fake = MagicMock()
    fake.pid = 4242
    fake.poll.return_value = None
    with patch("dl_dashboard.driver_mgr.subprocess.Popen", return_value=fake):
        mgr.start(Path("/p"), "demo", Path("/wt"))
    with patch("dl_dashboard.driver_mgr.os.killpg") as killpg:
        assert mgr.stop(Path("/p"), "demo") is True
        killpg.assert_called_once()
    fake.poll.return_value = -15
    assert mgr.alive(Path("/p"), "demo") is None
