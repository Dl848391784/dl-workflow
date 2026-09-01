"""dl_dashboard.scanner：state.json -> 节点状态模型。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dl_dashboard.scanner import (
    iter_workflow_names,
    meta_root,
    scan_all,
    scan_workflow,
)


def _mk_workflow(project: Path, name: str, state: dict) -> Path:
    meta = meta_root(project, name)
    meta.mkdir(parents=True)
    (meta / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return meta


BASE_STATE = {
    "name": "demo",
    "phase": "plan",
    "sub_index": 2,
    "sub_step_index": 1,
    "node": "plan:2",
    "gate": "pending",
    "held_for_gate": False,
    "updated_at": "2026-08-27T10:00:00",
    "problem_statement": "测试问题",
    "history": [
        {"phase": "understand", "sub": 1,
         "entered_at": "2026-08-27T08:00:00", "exited_at": "2026-08-27T08:30:00",
         "via": "step-stop"},
    ],
}


def test_meta_root(tmp_path):
    assert meta_root(tmp_path, "demo") == tmp_path / ".claude" / "workflows" / "demo"


def test_iter_workflow_names_skips_incomplete(tmp_path):
    _mk_workflow(tmp_path, "ok", BASE_STATE)
    (meta_root(tmp_path, "broken")).mkdir(parents=True)  # 无 state.json
    assert iter_workflow_names(tmp_path) == ["ok"]
    assert iter_workflow_names(tmp_path / "nonexistent") == []


def test_scan_workflow_node_statuses(tmp_path):
    _mk_workflow(tmp_path, "demo", BASE_STATE)
    info = scan_workflow(tmp_path, "demo")
    assert info.node == "plan:2" and info.gate == "pending"
    assert info.problem_statement == "测试问题"
    by_id = {n.node_id: n for n in info.nodes}
    assert by_id["understand:1"].status == "done"
    assert by_id["understand:1"].exited_at == "2026-08-27T08:30:00"
    assert by_id["plan:2"].status == "current"
    assert by_id["plan:3"].status == "pending"
    assert by_id["execute:0"].status == "pending"
    # 全节点覆盖 5 阶段
    assert {n.phase for n in info.nodes} == {
        "understand", "plan", "execute", "review", "evolution"}


def test_scan_workflow_fermate_node_visibility(tmp_path):
    """fermate 轨道可见集单源（dl_flow_nodes fermate_cut_node/fermate_phase_
    reachable）：plan:3/plan:4 裁剪 + execute/review/evolution 不可达——scanner
    下发即过滤，前端不再手写（web_ui_interaction 32/43=74% 幽灵进度防回归）。"""
    _mk_workflow(tmp_path, "demo", {**BASE_STATE, "force_fermate": True})
    info = scan_workflow(tmp_path, "demo")
    ids = {n.node_id for n in info.nodes}
    assert ids == {f"understand:{i}" for i in range(1, 5)} | {"plan:1", "plan:2"}
    # 过滤不影响既有状态标注
    by_id = {n.node_id: n for n in info.nodes}
    assert by_id["understand:1"].status == "done"
    assert by_id["plan:2"].status == "current"


def test_scan_workflow_need_user_flag(tmp_path):
    meta = _mk_workflow(tmp_path, "demo", BASE_STATE)
    assert scan_workflow(tmp_path, "demo").need_user is False
    (meta / "need_user.json").write_text('{"questions": []}', encoding="utf-8")
    assert scan_workflow(tmp_path, "demo").need_user is True


def test_scan_workflow_need_user_stale_filtered(tmp_path):
    """陈旧卡过滤单源（绑定 ≠ state 当前位置 → need_user=False，侧栏等待态
    与 detail 同口径）；legacy 无绑定 → True（放行）。"""
    meta = _mk_workflow(tmp_path, "demo", BASE_STATE)  # state plan:2#1
    (meta / "need_user.json").write_text(json.dumps({
        "questions": [{"question": "q"}], "ts": "T",
        "node": "plan:1", "sub_step": 3,
    }), encoding="utf-8")
    assert scan_workflow(tmp_path, "demo").need_user is False  # 陈旧
    (meta / "need_user.json").write_text(json.dumps({
        "questions": [{"question": "q"}], "ts": "T",
        "node": "plan:2", "sub_step": 1,
    }), encoding="utf-8")
    assert scan_workflow(tmp_path, "demo").need_user is True  # 当前步
    (meta / "need_user.json").write_text(json.dumps({
        "questions": [{"question": "q"}], "ts": "T",
    }), encoding="utf-8")
    assert scan_workflow(tmp_path, "demo").need_user is True  # legacy 无绑定


def test_gate_actionable_states(tmp_path):
    """gate_actionable = 门栏扣留 / 闸门后置阶段（plan）pending——
    understand 全程 pending 也不可点（gate 按钮可见性单源）。"""
    from dl_dashboard.scanner import gate_actionable_of
    assert gate_actionable_of({"held_for_gate": True, "gate": "pending",
                               "phase": "understand"}) is True
    assert gate_actionable_of({"gate": "pending", "phase": "plan"}) is True
    assert gate_actionable_of({"gate": "pending", "phase": "understand"}) is False
    assert gate_actionable_of({"gate": "passed", "phase": "plan"}) is False
    assert gate_actionable_of({"gate": "done", "phase": "plan"}) is False


def test_scan_workflow_gate_actionable_field(tmp_path):
    _mk_workflow(tmp_path, "demo", BASE_STATE)  # plan + pending → True
    assert scan_workflow(tmp_path, "demo").gate_actionable is True
    st = dict(BASE_STATE, phase="understand", node="understand:1", sub_index=1)
    _mk_workflow(tmp_path, "u", st)
    assert scan_workflow(tmp_path, "u").gate_actionable is False


def test_step_labels_from_step_short(tmp_path):
    """可见子步号 -> 中文短名（Step.short 单源）——时间轴按名展示替代 #n；
    无编排节点（无 sub_steps）回退 #1。"""
    _mk_workflow(tmp_path, "demo", BASE_STATE)
    info = scan_workflow(tmp_path, "demo")
    by_id = {n.node_id: n for n in info.nodes}
    u1 = by_id["understand:1"]
    assert u1.step_labels["1"] == "逼问定义"
    assert u1.step_labels["3"] == "因果链挖掘"
    assert u1.step_labels["7"] == "读回确认"
    assert by_id["execute:0"].step_labels == {"1": "#1"}


def test_step_labels_exclude_silent(tmp_path):
    """静默步（tacet 非脊柱）不进 step_labels——与 steps 过滤同口径。"""
    _mk_workflow(tmp_path, "demo", dict(BASE_STATE, force_tacet=True))
    info = scan_workflow(tmp_path, "demo")
    u1 = next(n for n in info.nodes if n.node_id == "understand:1")
    assert set(u1.step_labels) == set(map(str, u1.steps))
    assert set(u1.step_labels) <= {"1", "2", "3", "4"}  # tacet 脊柱 u:1#1-4


def test_scan_workflow_current_segment_passthrough(tmp_path):
    """在飞段标记透传（driver 起跑落盘）——总执行时间的在飞项数据源。"""
    st = dict(BASE_STATE, current_segment={
        "session_id": "s1", "node": "plan:2", "sub_step": 1, "started_at": "t"})
    _mk_workflow(tmp_path, "demo", st)
    cs = scan_workflow(tmp_path, "demo").current_segment
    assert cs["node"] == "plan:2" and cs["started_at"] == "t"


def test_scan_all_isolates_broken_workflow(tmp_path):
    _mk_workflow(tmp_path, "good", BASE_STATE)
    bad = meta_root(tmp_path, "bad")
    bad.mkdir(parents=True)
    (bad / "state.json").write_text("{损坏", encoding="utf-8")
    infos = {i.name: i for i in scan_all([tmp_path])}
    assert infos["good"].error is None
    assert infos["bad"].error is not None  # 坏实例如实暴露，不拖垮全局


def test_scan_workflow_corrupt_state_raises_value_error(tmp_path):
    bad = meta_root(tmp_path, "bad")
    bad.mkdir(parents=True)
    (bad / "state.json").write_text("{损坏", encoding="utf-8")
    with pytest.raises(ValueError, match="state.json 损坏"):
        scan_workflow(tmp_path, "bad")


def test_node_status_includes_sub_total(tmp_path):
    _mk_workflow(tmp_path, "demo", BASE_STATE)
    info = scan_workflow(tmp_path, "demo")
    by_id = {n.node_id: n for n in info.nodes}
    assert by_id["plan:2"].sub_total >= 1
    assert all(n.sub_total >= 1 for n in info.nodes)


def test_scan_workflow_mode_flags(tmp_path):
    _mk_workflow(tmp_path, "demo", BASE_STATE)
    _mk_workflow(tmp_path, "tacet", dict(BASE_STATE, force_tacet=True))
    _mk_workflow(tmp_path, "fermate", dict(BASE_STATE, force_fermate=True))
    assert scan_workflow(tmp_path, "tacet").force_tacet is True
    assert scan_workflow(tmp_path, "tacet").force_fermate is False
    assert scan_workflow(tmp_path, "fermate").force_fermate is True
    assert scan_workflow(tmp_path, "demo").force_tacet is False  # 老工作流无字段→False


def test_scan_all_sorted_by_created_at_desc(tmp_path):
    _mk_workflow(tmp_path, "old", dict(BASE_STATE, created_at="2026-08-25T10:00:00"))
    _mk_workflow(tmp_path, "new", dict(BASE_STATE, created_at="2026-08-27T10:00:00"))
    _mk_workflow(tmp_path, "mid", dict(BASE_STATE, created_at="2026-08-26T10:00:00"))
    _mk_workflow(tmp_path, "nots", BASE_STATE)  # 无 created_at -> 回退 updated_at
    names = [i.name for i in scan_all([tmp_path])]
    assert names.index("new") < names.index("mid") < names.index("old")


def test_steps_exclude_tacet_silent_and_fermate_cut(tmp_path):
    # tacet：只有脊柱步可见
    _mk_workflow(tmp_path, "tacet", dict(BASE_STATE, force_tacet=True))
    by_id = {n.node_id: n for n in scan_workflow(tmp_path, "tacet").nodes}
    assert set(by_id["understand:1"].steps) == {1, 2, 3, 4}  # 脊柱 4 步
    assert by_id["plan:2"].steps == ()  # plan:2 非脊柱节点整节点静默
    # fermate+tacet：脊柱换 fermate 版 + FERMATE_SILENT 裁剪
    _mk_workflow(tmp_path, "ft", dict(BASE_STATE, force_tacet=True, force_fermate=True))
    by_id = {n.node_id: n for n in scan_workflow(tmp_path, "ft").nodes}
    assert 3 not in by_id["understand:4"].steps  # u:4#3 被 fermate 裁剪
    # 普通工作流：全部步可见
    _mk_workflow(tmp_path, "full", BASE_STATE)
    by_id = {n.node_id: n for n in scan_workflow(tmp_path, "full").nodes}
    assert len(by_id["understand:1"].steps) == by_id["understand:1"].sub_total
