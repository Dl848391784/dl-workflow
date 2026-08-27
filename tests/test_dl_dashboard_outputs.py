"""dl_dashboard.outputs：证据链 / 改动面 / 产物文档。"""
from __future__ import annotations

import json
from pathlib import Path

from dl_dashboard.outputs import (
    artifact_status,
    load_artifact,
    load_change_points,
    load_evidence,
)


def _mk_project(tmp_path: Path) -> Path:
    ev_dir = tmp_path / ".claude" / "evidence"
    ev_dir.mkdir(parents=True)
    entries = [
        {"kind": "skill-trace", "major_stage": "Understand", "minor_stage": "ProblemContext",
         "sub_step": 1, "skill": "define-problem", "purpose": "逼问问题定义",
         "q": ["问题是什么？", "who？"], "a": ["分析 X", "开发者"], "结论": "①问题成立"},
        {"kind": "gate", "major_stage": "Plan", "minor_stage": "", "sub_step": None,
         "purpose": "plan 闸门", "结论": "passed"},
        "{损坏行",
    ]
    with open(ev_dir / "demo.jsonl", "w", encoding="utf-8") as fh:
        for e in entries:
            if isinstance(e, dict):
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
            else:
                fh.write(e + "\n")
    return tmp_path


def test_load_evidence_parses_entries_and_skips_corrupt(tmp_path):
    proj = _mk_project(tmp_path)
    ev = load_evidence(proj, "demo")
    assert len(ev) == 2  # 损坏行跳过且记 log，不拖垮
    assert ev[0]["conclusion"] == "①问题成立"
    assert ev[0]["q"] == ["问题是什么？", "who？"]
    assert ev[1]["kind"] == "gate"
    assert load_evidence(proj, "nonexistent") == []


def test_load_change_points_extracts_anchors(tmp_path):
    proj = _mk_project(tmp_path)
    plans = tmp_path / ".claude" / "plans"
    plans.mkdir(parents=True)
    (plans / "demo.md").write_text(
        "## 执行步骤\n"
        "- 某改动项（execute；change_point=web_ui/templates/_macros.html:-:L57（改）：改前=x → 改后=y；interface=Consumes=a）\n"
        "- 另一项（change_point=web_ui/app.py:_render_report:L267（改）：改前=a → 改后=b\n"
        "test_cases/test_x.py:-（增@文件尾）：新增测试；Produces=out）\n",
        encoding="utf-8",
    )
    cps = load_change_points(proj, "demo")
    assert len(cps) == 3
    assert cps[0] == {"file": "web_ui/templates/_macros.html", "method": "-",
                      "line": "57", "action": "改"}
    assert cps[1] == {"file": "web_ui/app.py", "method": "_render_report",
                      "line": "267", "action": "改"}
    assert cps[2]["file"] == "test_cases/test_x.py" and cps[2]["action"] == "增"
    assert load_change_points(proj, "nonexistent") == []


def test_artifact_status_and_content(tmp_path):
    proj = _mk_project(tmp_path)
    st = artifact_status(proj, "demo")
    assert st["understands"]["exists"] is False
    assert st["plans"]["exists"] is False
    ud = tmp_path / ".claude" / "understands"
    ud.mkdir(parents=True)
    (ud / "demo.md").write_text("# understand 内容", encoding="utf-8")
    st = artifact_status(proj, "demo")
    assert st["understands"]["exists"] is True and st["understands"]["size"] > 0
    assert load_artifact(proj, "demo", "understands") == "# understand 内容"
    assert load_artifact(proj, "demo", "plans") is None


def test_load_artifact_kind_whitelist(tmp_path):
    proj = _mk_project(tmp_path)
    try:
        load_artifact(proj, "demo", "../../etc")
        raise AssertionError("应拒绝非法 kind")
    except ValueError:
        pass
