"""dl_dashboard.actions：写操作封装（mock 子进程与 engine）。"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dl_dashboard import actions
from dl_dashboard.scanner import meta_root


def _mk_state(project: Path, name: str, segs) -> Path:
    meta = meta_root(project, name)
    meta.mkdir(parents=True)
    state = {
        "name": name, "phase": "plan", "sub_index": 4, "sub_step_index": 2,
        "node": "plan:4", "gate": "pending", "held_for_gate": True,
        "worktree_path": str(project / ".claude" / "worktrees" / name),
        "segment_sessions": segs,
    }
    (meta / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return meta


def test_create_success_when_instance_on_disk(tmp_path):
    def fake_run(cmd, **kw):
        # launcher 跑完实例已落盘
        (tmp_path / ".claude" / "workflows" / "demo").mkdir(parents=True)
        (tmp_path / ".claude" / "workflows" / "demo" / "state.json").write_text(
            '{"worktree_path": "/wt"}', encoding="utf-8")
        return MagicMock(returncode=0, stdout="ok", stderr="")
    mgr = MagicMock()
    with patch.object(actions.subprocess, "run", side_effect=fake_run), \
         patch.object(actions.engine, "set_problem_statement") as sps:
        ok, msg = actions.create_workflow(tmp_path, "demo", "问题X", mgr)
    assert ok, msg
    sps.assert_called_once()
    mgr.start.assert_called_once()


def test_create_failure_when_no_instance(tmp_path):
    with patch.object(actions.subprocess, "run",
                      return_value=MagicMock(returncode=1, stdout="", stderr="boom")):
        ok, msg = actions.create_workflow(tmp_path, "demo", "问题X", MagicMock())
    assert not ok and "boom" in msg


def test_inject_targets_needuser_segment_only(tmp_path):
    segs = [
        {"ts": "t1", "session_id": "sid-old", "kind": "tui-step-needuser",
         "node": "plan:4", "sub_step": 1, "note": "rc=0"},
        {"ts": "t2", "session_id": "sid-cur", "kind": "tui-step-needuser",
         "node": "plan:4", "sub_step": 2, "note": "rc=1"},
    ]
    meta = _mk_state(tmp_path, "demo", segs)
    (meta / "settings.drive-tui.json").write_text("{}", encoding="utf-8")
    (meta / "tui-rules.plan:4.md").write_text("rules", encoding="utf-8")
    with patch.object(actions.subprocess, "run",
                      return_value=MagicMock(returncode=0, stdout="", stderr="")) as run:
        ok, msg = actions.inject_answer(tmp_path, "demo", "选A")
    assert ok, msg
    cmd = run.call_args[0][0]
    assert cmd[cmd.index("--resume") + 1] == "sid-cur"  # 当前步段，禁回落旧段
    assert cmd[cmd.index("-p") + 1] == "选A"


def test_inject_aborts_without_needuser_segment(tmp_path):
    _mk_state(tmp_path, "demo", [
        {"ts": "t", "session_id": "sid-x", "kind": "headless-step",
         "node": "plan:4", "sub_step": 2, "note": "rc=0"}])
    ok, msg = actions.inject_answer(tmp_path, "demo", "选A")
    assert not ok and "无 tui-step-needuser" in msg  # wf_ctl 同语义中止


def test_gate_release_runs_engine_cli(tmp_path):
    _mk_state(tmp_path, "demo", [])
    with patch.object(actions.subprocess, "run",
                      return_value=MagicMock(returncode=0, stdout="✓ 已放行", stderr="")) as run:
        ok, msg = actions.gate_release(tmp_path, "demo")
    assert ok
    cmd = run.call_args[0][0]
    assert "subgate-pass" in cmd and "demo" in cmd


def test_dl_command_rejects_unknown_cmd(tmp_path):
    ok, msg = actions.dl_command(tmp_path, "demo", "rm-rf")
    assert not ok and "不支持" in msg
