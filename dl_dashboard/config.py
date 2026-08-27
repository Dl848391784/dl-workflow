"""dashboard 配置：~/.dl-workflow/dashboard.toml（项目根清单 + 监听地址）。"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG = Path.home() / ".dl-workflow" / "dashboard.toml"


@dataclass(frozen=True)
class DashboardConfig:
    projects: tuple[Path, ...]
    host: str = "0.0.0.0"
    port: int = 9000


def load_config(path: Path | None = None) -> DashboardConfig:
    p = path or DEFAULT_CONFIG
    if not p.exists():
        return DashboardConfig(projects=())
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    projects = tuple(Path(x).expanduser() for x in data.get("projects", []))
    return DashboardConfig(
        projects=projects,
        host=str(data.get("host", "0.0.0.0")),
        port=int(data.get("port", 9000)),
    )
