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


def test_scan_workflow_need_user_flag(tmp_path):
    meta = _mk_workflow(tmp_path, "demo", BASE_STATE)
    assert scan_workflow(tmp_path, "demo").need_user is False
    (meta / "need_user.json").write_text('{"questions": []}', encoding="utf-8")
    assert scan_workflow(tmp_path, "demo").need_user is True


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
