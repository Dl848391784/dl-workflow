"""dl_dashboard.actions：写操作封装（mock 子进程与 engine）。"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from dl_dashboard import actions
from dl_dashboard.scanner import meta_root


def _mk_state(project: Path, name: str, segs, *, worktree_path: str | None = None) -> Path:
    meta = meta_root(project, name)
    meta.mkdir(parents=True)
    state = {
        "name": name, "phase": "plan", "sub_index": 4, "sub_step_index": 2,
        "node": "plan:4", "gate": "pending", "held_for_gate": True,
        "segment_sessions": segs,
    }
    if worktree_path is not None:
        state["worktree_path"] = worktree_path
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
    meta = _mk_state(tmp_path, "demo", segs, worktree_path=str(tmp_path / "wt"))
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
         "node": "plan:4", "sub_step": 2, "note": "rc=0"}], worktree_path=str(tmp_path / "wt"))
    ok, msg = actions.inject_answer(tmp_path, "demo", "选A")
    assert not ok and "无 tui-step-needuser" in msg  # wf_ctl 同语义中止


def test_inject_returns_false_when_state_missing(tmp_path):
    ok, msg = actions.inject_answer(tmp_path, "demo", "选A")
    assert not ok and "state.json 缺失" in msg


def test_inject_returns_false_when_state_lacks_worktree_path(tmp_path):
    _mk_state(tmp_path, "demo", [], worktree_path=None)
    ok, msg = actions.inject_answer(tmp_path, "demo", "选A")
    assert not ok and "state.json 缺 worktree_path" in msg


def test_gate_release_runs_engine_cli(tmp_path):
    _mk_state(tmp_path, "demo", [], worktree_path=str(tmp_path / "wt"))
    with patch.object(actions.subprocess, "run",
                      return_value=MagicMock(returncode=0, stdout="✓ 已放行", stderr="")) as run:
        ok, msg = actions.gate_release(tmp_path, "demo")
    assert ok
    cmd = run.call_args[0][0]
    assert "subgate-pass" in cmd and "demo" in cmd


def test_gate_release_returns_false_when_state_missing(tmp_path):
    ok, msg = actions.gate_release(tmp_path, "demo")
    assert not ok and "state.json 缺失" in msg


def test_gate_release_returns_false_when_state_lacks_worktree_path(tmp_path):
    _mk_state(tmp_path, "demo", [], worktree_path=None)
    ok, msg = actions.gate_release(tmp_path, "demo")
    assert not ok and "state.json 缺 worktree_path" in msg


def test_dl_command_rejects_unknown_cmd(tmp_path):
    _mk_state(tmp_path, "demo", [], worktree_path=str(tmp_path / "wt"))
    ok, msg = actions.dl_command(tmp_path, "demo", "rm-rf")
    assert not ok and "不支持" in msg


def test_dl_command_next_routes_via_shell_script(tmp_path):
    _mk_state(tmp_path, "demo", [], worktree_path=str(tmp_path / "wt"))
    wt = tmp_path / "wt"
    wt.mkdir(parents=True)
    with patch.object(actions.subprocess, "run",
                      return_value=MagicMock(returncode=0, stdout="ok", stderr="")) as run:
        ok, msg = actions.dl_command(tmp_path, "demo", "next")
    assert ok
    cmd, kwargs = run.call_args[0][0], run.call_args[1]
    assert cmd[0] == "bash" and "dl-cmd.sh" in cmd[1] and "next" in cmd
    assert kwargs["cwd"] == str(wt)


def test_dl_command_back_routes_via_shell_script(tmp_path):
    _mk_state(tmp_path, "demo", [], worktree_path=str(tmp_path / "wt"))
    wt = tmp_path / "wt"
    wt.mkdir(parents=True)
    with patch.object(actions.subprocess, "run",
                      return_value=MagicMock(returncode=0, stdout="ok", stderr="")) as run:
        ok, msg = actions.dl_command(tmp_path, "demo", "back")
    assert ok
    cmd = run.call_args[0][0]
    assert cmd[0] == "bash" and "dl-cmd.sh" in cmd[1] and "back" in cmd


def test_dl_command_jump_routes_via_shell_script(tmp_path):
    _mk_state(tmp_path, "demo", [], worktree_path=str(tmp_path / "wt"))
    wt = tmp_path / "wt"
    wt.mkdir(parents=True)
    with patch.object(actions.subprocess, "run",
                      return_value=MagicMock(returncode=0, stdout="ok", stderr="")) as run:
        ok, msg = actions.dl_command(tmp_path, "demo", "jump", "execute")
    assert ok
    cmd = run.call_args[0][0]
    assert cmd[0] == "bash" and "dl-cmd.sh" in cmd[1] and "jump" in cmd and "execute" in cmd


def test_dl_command_jump_without_value_rejected(tmp_path):
    _mk_state(tmp_path, "demo", [], worktree_path=str(tmp_path / "wt"))
    ok, msg = actions.dl_command(tmp_path, "demo", "jump")
    assert not ok and "jump 需要参数" in msg


def test_dl_command_returns_false_when_state_missing(tmp_path):
    ok, msg = actions.dl_command(tmp_path, "demo", "advance")
    assert not ok and "state.json 缺失" in msg


def test_dl_command_returns_false_when_state_lacks_worktree_path(tmp_path):
    _mk_state(tmp_path, "demo", [], worktree_path=None)
    ok, msg = actions.dl_command(tmp_path, "demo", "advance")
    assert not ok and "state.json 缺 worktree_path" in msg


def test_restart_drive_returns_false_when_state_missing(tmp_path):
    mgr = MagicMock()
    mgr.alive.return_value = None
    ok, msg = actions.restart_drive(tmp_path, "demo", mgr)
    assert not ok and "state.json 缺失" in msg
    mgr.start.assert_not_called()


def test_restart_drive_returns_false_when_state_lacks_worktree_path(tmp_path):
    _mk_state(tmp_path, "demo", [], worktree_path=None)
    mgr = MagicMock()
    mgr.alive.return_value = None
    ok, msg = actions.restart_drive(tmp_path, "demo", mgr)
    assert not ok and "state.json 缺 worktree_path" in msg
    mgr.start.assert_not_called()


def test_delete_stops_driver_and_runs_done(tmp_path):
    meta = _mk_state(tmp_path, "demo", [])
    mgr = MagicMock()
    mgr.alive.return_value = 4242

    def fake_run(cmd, **kw):
        assert "--delete" in cmd and "demo" in cmd
        shutil.rmtree(meta)  # launcher 成功 = 元数据删除
        return MagicMock(returncode=0, stdout="已删除", stderr="")
    with patch.object(actions.subprocess, "run", side_effect=fake_run):
        ok, msg = actions.delete_workflow(tmp_path, "demo", mgr)
    assert ok, msg
    mgr.stop.assert_called_once_with(tmp_path, "demo")


def test_delete_failure_when_meta_remains(tmp_path):
    _mk_state(tmp_path, "demo", [])
    mgr = MagicMock()
    mgr.alive.return_value = None
    with patch.object(actions.subprocess, "run",
                      return_value=MagicMock(returncode=1, stdout="", stderr="boom")):
        ok, msg = actions.delete_workflow(tmp_path, "demo", mgr)
    assert not ok and "boom" in msg
    mgr.stop.assert_not_called()


def test_pause_stops_running_driver(tmp_path):
    mgr = MagicMock()
    mgr.alive.return_value = 4242
    ok, msg = actions.pause_workflow(tmp_path, "demo", mgr)
    assert ok
    mgr.stop.assert_called_once_with(tmp_path, "demo")


def test_pause_noop_when_driver_dead(tmp_path):
    mgr = MagicMock()
    mgr.alive.return_value = None
    ok, msg = actions.pause_workflow(tmp_path, "demo", mgr)
    assert not ok and "无需暂停" in msg
    mgr.stop.assert_not_called()


def test_create_passes_scope_and_tacet_flags(tmp_path):
    def fake_run(cmd, **kw):
        (tmp_path / ".claude" / "workflows" / "demo").mkdir(parents=True)
        (tmp_path / ".claude" / "workflows" / "demo" / "state.json").write_text(
            '{"worktree_path": "/wt"}', encoding="utf-8")
        return MagicMock(returncode=0, stdout="ok", stderr="")
    with patch.object(actions.subprocess, "run", side_effect=fake_run) as run, \
         patch.object(actions.engine, "set_problem_statement"):
        ok, _ = actions.create_workflow(
            tmp_path, "demo", "Q", MagicMock(), scope="forte", tacet=True)
    assert ok
    argv = run.call_args[0][0]
    assert "--forte" in argv and "--force-tacet" in argv  # 两维正交共存


def test_create_standard_track_has_no_tacet_flag(tmp_path):
    def fake_run(cmd, **kw):
        (tmp_path / ".claude" / "workflows" / "demo").mkdir(parents=True)
        (tmp_path / ".claude" / "workflows" / "demo" / "state.json").write_text(
            '{"worktree_path": "/wt"}', encoding="utf-8")
        return MagicMock(returncode=0, stdout="ok", stderr="")
    with patch.object(actions.subprocess, "run", side_effect=fake_run) as run, \
         patch.object(actions.engine, "set_problem_statement"):
        ok, _ = actions.create_workflow(tmp_path, "demo", "Q", MagicMock())
    assert ok
    argv = run.call_args[0][0]
    assert "--fermate" in argv and "--force-tacet" not in argv


def test_create_rejects_unknown_scope(tmp_path):
    ok, msg = actions.create_workflow(tmp_path, "demo", "Q", MagicMock(), scope="xyz")
    assert not ok and "未知范围" in msg


def test_restart_drive_refuses_when_held_for_gate(tmp_path):
    _mk_state(tmp_path, "demo", [], worktree_path="/wt")  # held_for_gate=True
    ok, msg = actions.restart_drive(tmp_path, "demo", MagicMock(**{"alive.return_value": None}))
    assert not ok and "gate 放行" in msg


def test_delete_also_removes_artifacts_and_cache(tmp_path):
    _mk_state(tmp_path, "demo", [])
    for rel in (".claude/plans/demo.md", ".claude/understands/demo.md",
                ".claude/evidence/demo.jsonl"):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", encoding="utf-8")
    mgr = MagicMock()
    mgr.alive.return_value = None

    def fake_run(cmd, **kw):
        shutil.rmtree(tmp_path / ".claude" / "workflows" / "demo")
        return MagicMock(returncode=0, stdout="", stderr="")
    with patch.object(actions.subprocess, "run", side_effect=fake_run):
        ok, msg = actions.delete_workflow(tmp_path, "demo", mgr)
    assert ok and "产物" in msg
    assert not (tmp_path / ".claude/plans/demo.md").exists()
    assert not (tmp_path / ".claude/understands/demo.md").exists()
    assert not (tmp_path / ".claude/evidence/demo.jsonl").exists()
