"""dl_dashboard.actions：写操作封装（mock 子进程与 engine）。"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from dl_dashboard import actions
from dl_dashboard.scanner import meta_root


def _mk_state(project: Path, name: str, segs, *, worktree_path: str | None = None,
              phase: str = "plan", sub_index: int = 4,
              engine: str | None = None) -> Path:
    meta = meta_root(project, name)
    meta.mkdir(parents=True)
    state = {
        "name": name, "phase": phase, "sub_index": sub_index, "sub_step_index": 2,
        "node": f"{phase}:{sub_index}", "gate": "pending", "held_for_gate": True,
        "segment_sessions": segs,
    }
    if worktree_path is not None:
        state["worktree_path"] = worktree_path
    if engine is not None:
        state["engine"] = engine  # per-instance-engine：实例引擎落 state（T2）
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
    assert "选A" in cmd[cmd.index("-p") + 1]  # 答案原文在一次性注入包装内


def _mk_injectable(tmp_path):
    """可注入实例夹具（needuser 台账 + tui settings/rules）。"""
    segs = [
        {"ts": "t2", "session_id": "sid-cur", "kind": "tui-step-needuser",
         "node": "plan:4", "sub_step": 2, "note": "rc=1"},
    ]
    meta = _mk_state(tmp_path, "demo", segs, worktree_path=str(tmp_path / "wt"))
    (meta / "settings.drive-tui.json").write_text("{}", encoding="utf-8")
    (meta / "tui-rules.plan:4.md").write_text("rules", encoding="utf-8")
    return meta


def test_inject_writes_and_clears_injecting_marker(tmp_path):
    """在飞标记（2026-09-18 实爆：提交后刷新页面表单复活——answered 要等
    模型轮跑完才写，在飞 1-3min 窗口无落盘标记）：起跑前写、结束删。"""
    meta = _mk_injectable(tmp_path)
    seen = {}

    def fake_run(cmd, **kw):
        # 子进程运行期间标记必须在场（=刷新页面可见「注入中」的时刻）
        seen["during"] = (meta / "injecting.json").exists()
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(actions.subprocess, "run", side_effect=fake_run):
        ok, _ = actions.inject_answer(tmp_path, "demo", "选A")
    assert ok
    assert seen["during"] is True
    assert not (meta / "injecting.json").exists()   # 成功后删除
    assert (meta / "answered.json").exists()        # answered 接续


def test_inject_failure_leaves_error_marker(tmp_path):
    """inject 失败转错误态（2026-09-18 异步化：POST 秒回后失败不再经 HTTP
    返回，标记错误态是唯一用户可见通道）；不算在飞、可重答。"""
    meta = _mk_injectable(tmp_path)
    with patch.object(actions.subprocess, "run",
                      return_value=MagicMock(returncode=1, stdout="", stderr="x")):
        ok, _ = actions.inject_answer(tmp_path, "demo", "选A")
    assert not ok
    m = json.loads((meta / "injecting.json").read_text(encoding="utf-8"))
    assert m["error"] and m["finished_at"]
    assert actions.injecting_since(tmp_path, "demo") is None  # 错误态非在飞
    assert actions.inject_error(tmp_path, "demo")             # 失败信息可读
    assert actions.inject_ready(tmp_path, "demo") is True     # 可重答
    assert not (meta / "answered.json").exists()              # 失败无 answered


def test_inject_error_cleared_on_step_advance(tmp_path):
    """错误标记陈旧自清（state 推进/换步后不误显）。"""
    meta = _mk_injectable(tmp_path)
    (meta / "injecting.json").write_text(json.dumps({
        "node": "plan:4", "sub_step": 2, "error": "boom"}), encoding="utf-8")
    st = json.loads((meta / "state.json").read_text(encoding="utf-8"))
    st["node"] = "plan:4"
    st["sub_step_index"] = 3  # 推进到下一步
    (meta / "state.json").write_text(json.dumps(st), encoding="utf-8")
    assert actions.inject_error(tmp_path, "demo") is None
    assert not (meta / "injecting.json").exists()


def test_inject_ready_false_while_injecting(tmp_path):
    """在飞期间 inject_ready=False（double-submit 防线提前到 inject 起跑）。"""
    meta = _mk_injectable(tmp_path)
    (meta / "injecting.json").write_text(
        '{"started_at": "t", "node": "plan:4", "sub_step": 2}', encoding="utf-8")
    assert actions.inject_ready(tmp_path, "demo") is False
    assert actions.injecting_since(tmp_path, "demo") is not None


def test_stale_injecting_marker_auto_cleaned(tmp_path):
    """server 崩溃残留：mtime > 30min 判 stale 自动清理，不永久堵重答。"""
    import os
    import time
    meta = _mk_injectable(tmp_path)
    p = meta / "injecting.json"
    p.write_text('{"started_at": "t"}', encoding="utf-8")
    old = time.time() - 31 * 60
    os.utime(p, (old, old))
    assert actions.injecting_since(tmp_path, "demo") is None
    assert not p.exists()


def test_inject_keeps_default_thinking(tmp_path):
    """inject 轮不在 disabled 档（2026-09-18 用户裁决：弱模型在答案映射上
    清零 thinking 有质量风险，不值得冒）——反向 pinning：env 不得带
    MAX_THINKING_TOKENS、cmd 不得带 --thinking。disabled 档=judge/呈现段。"""
    _mk_injectable(tmp_path)
    with patch.object(actions.subprocess, "run",
                      return_value=MagicMock(returncode=0, stdout="", stderr="")) as run:
        ok, _ = actions.inject_answer(tmp_path, "demo", "选A")
    assert ok
    assert "MAX_THINKING_TOKENS" not in run.call_args[1]["env"]
    assert "--thinking" not in run.call_args[0][0]


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


def test_gate_release_runs_dl_cmd_gate(tmp_path):
    """gate 放行 = /dl gate 同路由（dl-cmd.sh gate 单源：门栏 subgate-pass /
    阶段闸门置 passed 双分支）——原直调 engine subgate-pass 放不了阶段闸门。"""
    _mk_state(tmp_path, "demo", [], worktree_path=str(tmp_path / "wt"))
    with patch.object(actions.subprocess, "run",
                      return_value=MagicMock(returncode=0, stdout="✓ 已放行", stderr="")) as run:
        ok, msg = actions.gate_release(tmp_path, "demo")
    assert ok
    cmd = run.call_args[0][0]
    assert cmd[:2] == ["bash", str(actions.DLWF / "scripts" / "workflow" / "dl-cmd.sh")]
    assert cmd[2] == "gate"


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
    # 2026-09-17 qoder 新建弹窗长转实爆：launcher 必须 --setup-only（秒级
    # 建实例退出），禁 --headless（exec driver 全程跑首段，POST 被绑架数分钟）
    assert "--setup-only" in argv and "--headless" not in argv


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


def test_inject_ready_false_before_needuser_segment(tmp_path):
    _mk_state(tmp_path, "demo", [
        {"ts": "t", "session_id": "s1", "kind": "headless-step",
         "node": "plan:4", "sub_step": 2, "note": "rc=0"}])
    assert actions.inject_ready(tmp_path, "demo") is False


def test_inject_ready_true_when_segment_recorded(tmp_path):
    _mk_state(tmp_path, "demo", [
        {"ts": "t", "session_id": "s1", "kind": "tui-step-needuser",
         "node": "plan:4", "sub_step": 2, "note": "rc=0"}])
    assert actions.inject_ready(tmp_path, "demo") is True


# ---------- 已答标记（dashboard-answered-marker-design） ----------


def _needuser_seg():
    return [
        {"ts": "t", "session_id": "s1", "kind": "tui-step-needuser",
         "node": "plan:4", "sub_step": 2, "note": "rc=0"}
    ]


_QUESTIONS = [{"question": "q", "header": "h", "options": []}]


def _questions_sha(questions) -> str:
    import hashlib
    return hashlib.sha1(
        json.dumps(questions, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _mk_need_user(meta: Path, ts="T1", node="plan:4", sub_step=2, bind=True,
                  questions=None):
    payload: dict = {
        "questions": questions if questions is not None else _QUESTIONS,
        "ts": ts,
    }
    if bind:
        payload["node"] = node
        payload["sub_step"] = sub_step
    (meta / "need_user.json").write_text(json.dumps(payload), encoding="utf-8")


def _mk_answered(meta: Path, node="plan:4", sub_step=2, questions=None, at="A1"):
    qs = questions if questions is not None else _QUESTIONS
    (meta / "answered.json").write_text(
        json.dumps({
            "node": node, "sub_step": sub_step,
            "questions_sha": _questions_sha(qs), "answered_at": at,
        }),
        encoding="utf-8",
    )


def _mk_block_verdict(tmp_path, sub_step=2, minor_stage="ExecutionPlanCheckpoints",
                      ts="2026-08-31T16:00:00"):
    ev = tmp_path / ".claude" / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    with open(ev / "demo.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "kind": "gate", "gate": "blocked", "sub_step": sub_step,
            "minor_stage": minor_stage, "reason": "判词", "ts": ts,
        }) + "\n")


def test_inject_writes_answered_marker(tmp_path):
    meta = _mk_state(tmp_path, "demo", _needuser_seg(),
                     worktree_path=str(tmp_path / "wt"))
    (meta / "settings.drive-tui.json").write_text("{}", encoding="utf-8")
    (meta / "tui-rules.plan:4.md").write_text("rules", encoding="utf-8")
    _mk_need_user(meta, ts="T1")
    with patch.object(actions.subprocess, "run",
                      return_value=MagicMock(returncode=0, stdout="", stderr="")):
        ok, msg = actions.inject_answer(tmp_path, "demo", "选A")
    assert ok, msg
    marker = json.loads((meta / "answered.json").read_text(encoding="utf-8"))
    assert marker["node"] == "plan:4" and marker["sub_step"] == 2
    assert marker["questions_sha"] == _questions_sha(_QUESTIONS)
    assert marker["answered_at"]


def test_inject_wraps_answer_and_drops_ask_user_question(tmp_path):
    """一次性注入包装（E2）：答案原文进 -p 载荷 + 禁止重问指引 + STEP_DONE；
    -p 无真人可答，AskUserQuestion 不进 inject 会话（机制层堵死重问路）。"""
    meta = _mk_state(tmp_path, "demo", _needuser_seg(),
                     worktree_path=str(tmp_path / "wt"))
    (meta / "settings.drive-tui.json").write_text("{}", encoding="utf-8")
    (meta / "tui-rules.plan:4.md").write_text("rules", encoding="utf-8")
    _mk_need_user(meta)
    with patch.object(actions.subprocess, "run",
                      return_value=MagicMock(returncode=0, stdout="", stderr="")) as run:
        ok, _ = actions.inject_answer(tmp_path, "demo", "选A")
    assert ok
    cmd = run.call_args[0][0]
    payload = cmd[cmd.index("-p") + 1]
    assert "选A" in payload and "一次性注入" in payload and "STEP_DONE" in payload
    assert "AskUserQuestion" not in ",".join(cmd)


class TestCreateWorkflowEngine:
    """T5：create_workflow engine 参数——显式值经 launcher env 传 DL_ENGINE 落
    state.engine，并随 driver spawn env 携带；None=现状逐位一致（不传 env）。"""

    def _fake_launcher(self, tmp_path, name, captured):
        """launcher 假跑：写含 engine 的 state.json（成败判定=state.json 存在）。"""

        class FakeProc:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(argv, **kw):
            captured["env"] = kw.get("env")
            meta = meta_root(tmp_path, name)
            meta.mkdir(parents=True)
            (meta / "state.json").write_text(
                json.dumps({"worktree_path": "/wt", "engine": "qodercli"}),
                encoding="utf-8")
            return FakeProc()

        return fake_run

    def test_launcher_env_carries_engine(self, monkeypatch, tmp_path):
        captured: dict = {}
        started: dict = {}

        class FakeMgr:
            def start(self, project, name, worktree, env=None):
                started["env"] = env
                return 123

        monkeypatch.setattr(actions.subprocess, "run",
                            self._fake_launcher(tmp_path, "wf1", captured))
        with patch.object(actions.engine, "set_problem_statement"):
            ok, msg = actions.create_workflow(
                tmp_path, "wf1", "stmt", FakeMgr(), engine="qodercli")
        assert ok, msg
        assert captured["env"]["DL_ENGINE"] == "qodercli"  # launcher env 落 state
        assert started["env"]["DL_ENGINE"] == "qodercli"  # driver spawn env 携带

    def test_engine_none_keeps_current_behavior(self, monkeypatch, tmp_path):
        """engine=None：不传 env（launcher 继承调用方 env 现状），逐位一致。"""
        captured: dict = {}

        class FakeMgr:
            def start(self, project, name, worktree, env=None):
                return 123

        monkeypatch.setattr(actions.subprocess, "run",
                            self._fake_launcher(tmp_path, "wf1", captured))
        with patch.object(actions.engine, "set_problem_statement"):
            ok, _ = actions.create_workflow(tmp_path, "wf1", "stmt", FakeMgr())
        assert ok
        assert captured["env"] is None

    def test_drv_env_merges_provider_and_engine(self, monkeypatch, tmp_path):
        """provider_env 与 DL_ENGINE 合并携带（非覆盖）：provider env 创建登记
        通道与引擎选择正交。"""
        captured: dict = {}
        started: dict = {}

        class FakeMgr:
            def start(self, project, name, worktree, env=None):
                started["env"] = env
                return 123

        monkeypatch.setattr(actions.subprocess, "run",
                            self._fake_launcher(tmp_path, "wf1", captured))
        with patch.object(actions.engine, "set_problem_statement"):
            ok, _ = actions.create_workflow(
                tmp_path, "wf1", "stmt", FakeMgr(),
                provider_env={"ANTHROPIC_API_KEY": "k"}, engine="qodercli")
        assert ok
        assert started["env"]["ANTHROPIC_API_KEY"] == "k"
        assert started["env"]["DL_ENGINE"] == "qodercli"


class TestInjectCmdDualEngine:
    """T7：needuser 注入 cmd 的 binary/perm/disallow_ask 走 dl_engine profile。"""

    def _inject_cmd(self, tmp_path, monkeypatch, *, engine_name,
                    phase="plan", sub_index=4):
        """跑 inject_answer 到 cmd 构造为止，返回捕获的 cmd 列表。"""
        if engine_name is None:
            monkeypatch.delenv("DL_ENGINE", raising=False)
        else:
            monkeypatch.setenv("DL_ENGINE", engine_name)
        nid = f"{phase}:{sub_index}"
        meta = _mk_state(tmp_path, "demo", [
            {"ts": "t", "session_id": "s1", "kind": "tui-step-needuser",
             "node": nid, "sub_step": 2, "note": "rc=0"},
        ], worktree_path=str(tmp_path / "wt"), phase=phase, sub_index=sub_index)
        (meta / "settings.drive-tui.json").write_text("{}", encoding="utf-8")
        (meta / f"tui-rules.{nid}.md").write_text("rules", encoding="utf-8")
        _mk_need_user(meta, node=nid, sub_step=2)
        with patch.object(actions.subprocess, "run",
                          return_value=MagicMock(returncode=0, stdout="", stderr="")) as run:
            ok, msg = actions.inject_answer(tmp_path, "demo", "选A")
        assert ok, msg
        return run.call_args[0][0]

    def test_inject_cmd_qoder(self, tmp_path, monkeypatch):
        # plan:4 带 segment_tools → --tools 白名单分支
        cmd = self._inject_cmd(tmp_path, monkeypatch, engine_name="qodercli")
        assert cmd[0] == "qodercli"
        assert "accept_edits" in cmd
        assert "--disallowedTools" not in cmd
        assert "--tools" in cmd

    def test_inject_cmd_qoder_no_tools_node(self, tmp_path, monkeypatch):
        # execute:0 无 segment_tools → disallow_ask 分支（qoder = 空，结构堵死）
        cmd = self._inject_cmd(tmp_path, monkeypatch, engine_name="qodercli",
                               phase="execute", sub_index=0)
        assert cmd[0] == "qodercli"
        assert "accept_edits" in cmd
        assert "--disallowedTools" not in cmd
        assert "--tools" not in cmd

    def test_inject_cmd_claude_default(self, tmp_path, monkeypatch):
        # claude 默认（DL_ENGINE 未设）→ 与单引擎时代逐位一致
        cmd = self._inject_cmd(tmp_path, monkeypatch, engine_name=None)
        assert cmd[0] == "claude"
        assert "acceptEdits" in cmd
        assert "--disallowedTools" not in cmd  # plan:4 走 --tools 分支
        tools = cmd[cmd.index("--tools") + 1]
        assert "TaskCreate" in tools and "TaskUpdate" in tools

    def test_inject_cmd_claude_no_tools_node(self, tmp_path, monkeypatch):
        # execute:0 → claude disallow_ask 分支（qoder 对照 = 空）
        cmd = self._inject_cmd(tmp_path, monkeypatch, engine_name=None,
                               phase="execute", sub_index=0)
        assert cmd[0] == "claude"
        assert "acceptEdits" in cmd
        assert "--disallowedTools" in cmd
        assert "AskUserQuestion" in cmd


class TestInjectUsesInstanceEngine:
    """per-instance-engine：inject 引擎跟实例 state，不跟 server env（多实例进程禁 env 竞态）。"""

    def _inject_cmd_state_engine(self, tmp_path, monkeypatch, *,
                                 state_engine, env_engine):
        """脚手架照 TestInjectCmdDualEngine：state 带 engine 字段，跑
        inject_answer 捕获 cmd（env 由调用方决定，验证 state/env 优先级）。"""
        if env_engine is None:
            monkeypatch.delenv("DL_ENGINE", raising=False)
        else:
            monkeypatch.setenv("DL_ENGINE", env_engine)
        nid = "plan:4"
        meta = _mk_state(tmp_path, "demo", [
            {"ts": "t", "session_id": "s1", "kind": "tui-step-needuser",
             "node": nid, "sub_step": 2, "note": "rc=0"},
        ], worktree_path=str(tmp_path / "wt"), engine=state_engine)
        (meta / "settings.drive-tui.json").write_text("{}", encoding="utf-8")
        (meta / f"tui-rules.{nid}.md").write_text("rules", encoding="utf-8")
        _mk_need_user(meta, node=nid, sub_step=2)
        with patch.object(actions.subprocess, "run",
                          return_value=MagicMock(returncode=0, stdout="", stderr="")) as run:
            ok, msg = actions.inject_answer(tmp_path, "demo", "选A")
        assert ok, msg
        return run.call_args[0][0]

    def test_inject_reads_state_engine(self, tmp_path, monkeypatch):
        # server 无 env：state.engine=qodercli 直驱 cmd（override=None→env 兜底锚在 T7 用例）
        cmd = self._inject_cmd_state_engine(tmp_path, monkeypatch,
                                            state_engine="qodercli", env_engine=None)
        assert cmd[0] == "qodercli"
        assert "accept_edits" in cmd

    def test_inject_state_engine_beats_env(self, tmp_path, monkeypatch):
        # state.engine 优先于 server env：多实例同进程，env 是竞态源（本例 env 指另一引擎）
        cmd = self._inject_cmd_state_engine(tmp_path, monkeypatch,
                                            state_engine="qodercli", env_engine="claude")
        assert cmd[0] == "qodercli"

    def test_inject_missing_state_engine_falls_back_to_env(self, tmp_path, monkeypatch):
        # 旧实例无 engine 字段（state_engine=None 不落盘）→ override=None→env 兜底
        cmd = self._inject_cmd_state_engine(tmp_path, monkeypatch,
                                            state_engine=None, env_engine="qodercli")
        assert cmd[0] == "qodercli"


def test_inject_ready_false_when_answered(tmp_path):
    """已答窗口（inject 成功 → 门控推进前）：段台账仍在原位，但标记覆盖 →
    不可再注入（D1：按钮不再复活，防 double-inject）。"""
    meta = _mk_state(tmp_path, "demo", _needuser_seg())
    _mk_need_user(meta, ts="T1")
    _mk_answered(meta, at="2026-08-31T15:00:00")
    assert actions.inject_ready(tmp_path, "demo") is False
    assert actions.answered_at_if_covers(tmp_path, "demo") == "2026-08-31T15:00:00"


def test_answered_survives_identical_restash(tmp_path):
    """E1：none 重试循环对同一步同一批问题重 stash（ts 必变）——内容 hash
    不变 → 标记仍覆盖（v1 按 ts 判在此场景 ~90s 即失效，E2E 实爆）。"""
    meta = _mk_state(tmp_path, "demo", _needuser_seg())
    _mk_need_user(meta, ts="T2")  # 重 stash：ts 变、questions 一字不差
    _mk_answered(meta, at="2026-08-31T15:00:00")
    assert actions.inject_ready(tmp_path, "demo") is False
    assert actions.answered_at_if_covers(tmp_path, "demo") == "2026-08-31T15:00:00"


def test_inject_ready_true_when_new_questions(tmp_path):
    """问题内容真变了（rework 补问/新问）→ hash 变 → 标记失效，可重新答。"""
    meta = _mk_state(tmp_path, "demo", _needuser_seg())
    _mk_need_user(meta, ts="T2",
                  questions=[{"question": "q2", "header": "h2", "options": []}])
    _mk_answered(meta)
    assert actions.inject_ready(tmp_path, "demo") is True
    assert actions.answered_at_if_covers(tmp_path, "demo") is None


def test_block_verdict_invalidates_marker(tmp_path):
    """answered_at 之后本步撞 gate=blocked = 答案被判不足——重答是 rework
    正路，标记必须放行（否则 escalate 后永远无法重答 = 卡死）。"""
    meta = _mk_state(tmp_path, "demo", _needuser_seg())
    _mk_need_user(meta, ts="T1")
    _mk_answered(meta, at="2026-08-31T15:00:00")
    _mk_block_verdict(tmp_path, ts="2026-08-31T15:30:00")
    assert actions.inject_ready(tmp_path, "demo") is True
    assert actions.answered_at_if_covers(tmp_path, "demo") is None


def test_older_block_verdict_keeps_marker(tmp_path):
    """answered_at 之前的旧 block 裁决不影响覆盖（那是上一轮答案的判词）。"""
    meta = _mk_state(tmp_path, "demo", _needuser_seg())
    _mk_need_user(meta, ts="T1")
    _mk_answered(meta, at="2026-08-31T15:00:00")
    _mk_block_verdict(tmp_path, ts="2026-08-31T14:00:00")
    assert actions.inject_ready(tmp_path, "demo") is False


def test_inject_ready_true_after_state_advanced(tmp_path):
    """state 推进 → 标记位置错位 → 失效。"""
    meta = _mk_state(tmp_path, "demo", _needuser_seg())
    _mk_need_user(meta, ts="T1")
    _mk_answered(meta, sub_step=1)  # state 在 #2，标记在 #1
    assert actions.inject_ready(tmp_path, "demo") is True


def test_inject_aborts_when_answered(tmp_path):
    """server 侧双保险：已覆盖直接中止注入（防 double-inject）。"""
    meta = _mk_state(tmp_path, "demo", _needuser_seg(),
                     worktree_path=str(tmp_path / "wt"))
    (meta / "settings.drive-tui.json").write_text("{}", encoding="utf-8")
    (meta / "tui-rules.plan:4.md").write_text("rules", encoding="utf-8")
    _mk_need_user(meta, ts="T1")
    _mk_answered(meta)
    ok, msg = actions.inject_answer(tmp_path, "demo", "又选A")
    assert not ok and "已注入" in msg


def test_answered_not_covers_when_need_user_gone(tmp_path):
    """need_user.json 缺失 = 无卡可覆盖 → 不覆盖；台账语义不变。"""
    meta = _mk_state(tmp_path, "demo", _needuser_seg())
    _mk_answered(meta)
    assert actions.answered_at_if_covers(tmp_path, "demo") is None
    assert actions.inject_ready(tmp_path, "demo") is True
