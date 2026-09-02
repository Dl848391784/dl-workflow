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
        "- 某改动项（execute；change_point=web_ui/templates/_macros.html:-:L57（改）："
        "改前={% set _ann_pct = _ann * 100 %}（对已百分比年化值再乘 100）→ "
        "改后=移除 ×100 直接消费已百分比值；interface=Consumes=a）\n"
        "- 另一项（change_point=web_ui/app.py:_render_report:L267（改）：改前=a → 改后=b\n"
        "test_cases/test_x.py:-（增@文件尾）：新增测试；Produces=out）\n",
        encoding="utf-8",
    )
    cps = load_change_points(proj, "demo")
    assert len(cps) == 3
    assert cps[0]["file"] == "web_ui/templates/_macros.html"
    assert cps[0]["line"] == "57" and cps[0]["action"] == "改"
    assert "_ann * 100" in cps[0]["before"]
    assert "移除 ×100" in cps[0]["after"]
    assert cps[1]["method"] == "_render_report" and cps[1]["line"] == "267"
    assert cps[2]["file"] == "test_cases/test_x.py" and cps[2]["action"] == "增"
    assert load_change_points(proj, "nonexistent") == []


def test_load_change_points_up_change_spec_gate_grammar(tmp_path):
    """2026-08-25 up-change-spec-gate 钦定语法（dl_flow_nodes._CHANGE_SPEC_RULE）：
    L<a>-<b> 行区间 + 改前/改后无等号。锚点行取自 web_ui_interaction_2 真实 plan.md
    （回归材料：旧 regex 只认 L57 单行 + 改前= 带等号 -> 6 条全漏、改动面空卡）。"""
    proj = _mk_project(tmp_path)
    plans = tmp_path / ".claude" / "plans"
    plans.mkdir(parents=True)
    (plans / "demo.md").write_text(
        "## 执行步骤\n"
        "- 步骤一（change_point=web_ui/templates/_macros.html:-:L57-57（改）："
        "改前 {% set _ann_pct = _ann * 100 %} → 改后 {% set _ann_pct = _ann %}（删 ×100，ann 已为百分数）\n"
        "web_ui/templates/_macros.html:-:L55-55（改）：改前契约注释「ann: 年化 decimal (0.2 = 20%)」"
        "→ 改后「ann: 年化百分数（49.2 = 49.2%，loader 已换算）」；interface=Consumes=a）\n"
        "- 步骤二（change_point=web_ui/templates/_section_compare.html:-:L61-61（改）："
        "改前 r.long_short_return_annual * 100 → 改后 r.long_short_return_annual（删 ×100）；Produces=out）\n",
        encoding="utf-8",
    )
    cps = load_change_points(proj, "demo")
    assert len(cps) == 3
    assert cps[0]["file"] == "web_ui/templates/_macros.html"
    assert cps[0]["line"] == "57" and cps[0]["action"] == "改"
    assert cps[0]["before"] == "{% set _ann_pct = _ann * 100 %}"
    assert cps[0]["after"].startswith("{% set _ann_pct = _ann %}")
    assert cps[1]["line"] == "55"
    assert "decimal (0.2 = 20%)" in cps[1]["before"]
    assert cps[2]["file"] == "web_ui/templates/_section_compare.html"
    assert cps[2]["before"] == "r.long_short_return_annual * 100"
    assert cps[2]["after"].startswith("r.long_short_return_annual")


def test_change_point_code_context_from_worktree(tmp_path):
    proj = _mk_project(tmp_path)
    plans = tmp_path / ".claude" / "plans"
    plans.mkdir(parents=True)
    (plans / "demo.md").write_text(
        "- 项（change_point=web_ui/app.py:_render_report:L3（改）：改前=a → 改后=b）\n",
        encoding="utf-8",
    )
    # worktree 实读：state.json 指到 tmp_path/wt，锚点文件 5 行
    wt = tmp_path / "wt"
    (wt / "web_ui").mkdir(parents=True)
    (wt / "web_ui" / "app.py").write_text(
        "l1\nl2\nOLD = x\nl4\nl5\n", encoding="utf-8")
    meta = tmp_path / ".claude" / "workflows" / "demo"
    meta.mkdir(parents=True)
    (meta / "state.json").write_text(
        json.dumps({"worktree_path": str(wt)}), encoding="utf-8")
    cps = load_change_points(proj, "demo")
    ctx = cps[0]["context"]
    assert ctx is not None
    assert ctx["anchor"] == 3 and ctx["start"] == 1
    assert ctx["lines"] == ["l1", "l2", "OLD = x", "l4", "l5"]


def test_artifact_status_and_content(tmp_path):
    proj = _mk_project(tmp_path)
    st = artifact_status(proj, "demo")
    assert st["understands"]["exists"] is False
    assert st["plans"]["exists"] is False
    assert st["plans"]["html_exists"] is False and st["plans"]["html_size"] == 0
    ud = tmp_path / ".claude" / "understands"
    ud.mkdir(parents=True)
    (ud / "demo.md").write_text("# understand 内容", encoding="utf-8")
    st = artifact_status(proj, "demo")
    assert st["understands"]["exists"] is True and st["understands"]["size"] > 0
    assert load_artifact(proj, "demo", "understands") == "# understand 内容"
    assert load_artifact(proj, "demo", "plans") is None
    # v0.3.0 html 伴随导出：html_exists/html_size 两态（dashboard 产物链接 md->html）
    assert st["understands"]["html_exists"] is False
    (ud / "demo.html").write_text("<html>渲染版</html>", encoding="utf-8")
    st = artifact_status(proj, "demo")
    assert st["understands"]["html_exists"] is True
    assert st["understands"]["html_size"] > 0


def test_load_artifact_kind_whitelist(tmp_path):
    proj = _mk_project(tmp_path)
    try:
        load_artifact(proj, "demo", "../../etc")
        raise AssertionError("应拒绝非法 kind")
    except ValueError:
        pass
