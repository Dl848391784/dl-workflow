"""driver 进程托管：spawn(setsid) / PID 文件 / 后端重启认领 / killpg 停止。

保活语义（dashboard-design §5）：工作流真实状态全落盘，driver 死 = 标红可
一键重驱，不是数据丢失。认领校验 /proc/<pid>/cmdline 防 pid 复用误认。
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import typing
from pathlib import Path

log = logging.getLogger("dl_dashboard.driver_mgr")


class DriverManager:
    def __init__(self, dlwf: Path, runtime_dir: Path):
        self.dlwf = Path(dlwf)
        self.runtime_dir = Path(runtime_dir)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._drivers: dict[str, subprocess.Popen] = {}
        self._logs: dict[str, typing.IO] = {}

    @staticmethod
    def slug(project, name: str) -> str:
        return f"{str(project).replace('/', '_')}--{name}"

    def _pid_path(self, slug: str) -> Path:
        return self.runtime_dir / f"{slug}.pid"

    def log_path(self, slug: str) -> Path:
        return self.runtime_dir / f"{slug}.log"

    def _cleanup(self, slug: str) -> None:
        """关闭日志、清内存表、删 pid 文件（幂等）。"""
        self._drivers.pop(slug, None)
        log_f = self._logs.pop(slug, None)
        if log_f is not None and not log_f.closed:
            log_f.close()
        self._pid_path(slug).unlink(missing_ok=True)

    def start(self, project, name: str, worktree, env: dict | None = None) -> int:
        """env：provider env 覆盖（ANTHROPIC_* 等），None = 继承 server 进程环境。"""
        slug = self.slug(project, name)
        log_f = open(self.log_path(slug), "ab")
        proc = subprocess.Popen(
            ["python3", str(self.dlwf / "scripts" / "workflow" / "dl_drive.py"), name],
            cwd=str(worktree),
            stdin=subprocess.DEVNULL,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # setsid：后端死/终端信号不波及 driver
            env=({**os.environ, **env} if env else None),
        )
        self._drivers[slug] = proc
        self._logs[slug] = log_f
        self._pid_path(slug).write_text(str(proc.pid), encoding="utf-8")
        log.info("driver started slug=%s pid=%s", slug, proc.pid)
        return proc.pid

    def alive(self, project, name: str) -> int | None:
        slug = self.slug(project, name)
        proc = self._drivers.get(slug)
        if proc is not None:
            if proc.poll() is None:
                return proc.pid
            self._cleanup(slug)
            return None
        # 后端重启后认领：pid 文件 + /proc cmdline 双重校验（防 pid 复用）
        p = self._pid_path(slug)
        if not p.exists():
            # pid 文件缺失：扫 /proc 认领「野生」driver（server 重启丢 pid
            # 文件、外部 `dl` 启动等场景）——不认领则 restart_drive 会起重复
            # driver（双执行体并行事故面）。argv 级匹配：dl_drive.py 与 name
            # 各自独立成参（防子串误配）。
            for proc_dir in Path("/proc").iterdir():
                if not proc_dir.name.isdigit():
                    continue
                try:
                    raw = proc_dir.joinpath("cmdline").read_bytes()
                except OSError:
                    continue
                if b"dl_drive.py" not in raw:
                    continue
                argv = raw.split(b"\x00")
                if (any(a.endswith(b"dl_drive.py") for a in argv)
                        and name.encode() in argv):
                    pid = int(proc_dir.name)
                    p.write_text(str(pid), encoding="utf-8")  # 认领并补登 pid 文件
                    log.info("认领野生 driver slug=%s pid=%s", slug, pid)
                    return pid
            return None
        try:
            pid = int(p.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
        except (ValueError, OSError):
            self._cleanup(slug)
            return None
        if b"dl_drive.py" in cmdline and name.encode() in cmdline:
            return pid
        self._cleanup(slug)
        return None

    def stop(self, project, name: str) -> bool:
        slug = self.slug(project, name)
        pid = self.alive(project, name)
        if pid is None:
            return False
        try:
            os.killpg(pid, signal.SIGTERM)  # 进程组整体停（driver + 段子进程）
        except OSError:
            log.warning("killpg 失败 slug=%s pid=%s", slug, pid, exc_info=True)
            return False
        self._cleanup(slug)
        log.info("driver stopped slug=%s pid=%s", slug, pid)
        return True

    def running(self) -> list[str]:
        return [s for s, p in self._drivers.items() if p.poll() is None]
