"""dl_dashboard.config：dashboard.toml 读取。"""
from __future__ import annotations

from dl_dashboard.config import load_config


def test_missing_file_returns_empty_projects(tmp_path):
    cfg = load_config(tmp_path / "nonexistent.toml")
    assert cfg.projects == ()
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9000


def test_parse_projects_host_port(tmp_path):
    p = tmp_path / "dashboard.toml"
    p.write_text(
        'host = "127.0.0.1"\n'
        "port = 19000\n"
        'projects = ["/home/admin/projects/factor_ic_analyzer", "~/projects/other"]\n',
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 19000
    assert str(cfg.projects[0]) == "/home/admin/projects/factor_ic_analyzer"
    assert cfg.projects[1].is_absolute()  # ~ 已展开
    assert "~" not in str(cfg.projects[1])
