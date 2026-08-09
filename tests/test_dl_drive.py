"""
scripts/workflow/dl_drive.py + drive 模式 hook 降级分支的单元测试（v3 headless driver）。

覆盖（designs/headless-driver-arch-design.md §3）：
- ensure_drive_settings：settings.json 派生——去 outputStyle/SessionStart，留其余；
- ensure_node_rules：节点级瘦版 system prompt（非 92KB 全量）；
- build_step_prompt：purpose/铁律/禁标记/返工段；
- engine.set_drive_mode + drive-mode CLI；
- workflow_advance drive_mode 早退（不门控不推进，防双 orchestrator）；
- workflow_step_fence drive_mode：S15/S10 跳过、S11 阶段写围栏保留。

fixture 约定同 test_workflow_advance.py（真 git repo + 真 worktree——
git rev-parse --git-common-dir 反查主仓的路径解析依赖真 worktree）。
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

DLWF_ROOT = Path(__file__).resolve().parents[1]
DRIVER = DLWF_ROOT / "scripts" / "workflow" / "dl_drive.py"
ADVANCE_HOOK = DLWF_ROOT / "hooks" / "workflow_advance.py"
FENCE_HOOK = DLWF_ROOT / "hooks" / "workflow_step_fence.py"

sys.path.insert(0, str(DLWF_ROOT))
import dl_flow_engine as engine  # noqa: E402


def _load(path: Path, alias: str):
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def wf_repo(tmp_path: Path):
    """真 git repo + 真 worktree(.claude/worktrees/t) + state + evidence 骨架。"""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "f").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "f"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / ".claude" / "workflows" / "t").mkdir(parents=True)
    (tmp_path / ".claude" / "evidence").mkdir(parents=True)
    subprocess.run(
        ["git", "worktree", "add", "-q", ".claude/worktrees/t", "-b", "wf/t"],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def _write_state(repo: Path, **over) -> dict:
    state = {
        "name": "t",
        "phase": "understand",
        "index": 1,
        "sub_index": 1,
        "sub_total": 4,
        "node": "understand:1",
        "sub_step_index": 1,
        "gate": "pending",
        "node_attempts": 0,
        "session_id": "s",
        "branch": "wf/t",
        "worktree_path": str(repo / ".claude" / "worktrees" / "t"),
        "created_at": "x",
        "updated_at": "x",
        "history": [],
    }
    state.update(over)
    (repo / ".claude" / "workflows" / "t" / "state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )
    return state


def _read_state(repo: Path) -> dict:
    return json.loads((repo / ".claude" / "workflows" / "t" / "state.json").read_text())


# ---------- ensure_drive_settings ----------


def test_drive_settings_strips_output_style_and_session_start(wf_repo):
    drv = _load(DRIVER, "drv_under_test")
    meta = wf_repo / ".claude" / "workflows" / "t"
    (meta / "settings.json").write_text(
        json.dumps(
            {
                "outputStyle": "workflow",
                "permissions": {"defaultMode": "acceptEdits", "allow": ["Write"]},
                "hooks": {
                    "SessionStart": [{"hooks": [{"type": "command", "command": "s"}]}],
                    "Stop": [{"hooks": [{"type": "command", "command": "a"}]}],
                    "PreToolUse": [{"hooks": [{"type": "command", "command": "f"}]}],
                },
            }
        ),
        encoding="utf-8",
    )
    out = drv.ensure_drive_settings(wf_repo, "t")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "outputStyle" not in data
    assert "SessionStart" not in data["hooks"]
    assert data["hooks"]["Stop"] and data["hooks"]["PreToolUse"]
    assert data["permissions"]["allow"] == ["Write"]
    # 幂等：内容不变不改 mtime
    mtime = out.stat().st_mtime
    drv.ensure_drive_settings(wf_repo, "t")
    assert out.stat().st_mtime == mtime


# ---------- ensure_node_rules ----------


def test_node_rules_is_node_scoped_not_full_template(wf_repo):
    drv = _load(DRIVER, "drv_under_test")
    node = engine.get_node("understand", 1)
    out = drv.ensure_node_rules(wf_repo, "t", node)
    text = out.read_text(encoding="utf-8")
    assert "子步骤" in text
    assert "禁输出 ### STEP_DONE" in text
    # 瘦版：只含本节点段落——本节点 GENERATED 段在、其它节点的段不在
    assert "sub_steps understand:1" in text
    assert "sub_steps plan:" not in text
    assert "sub_steps understand:2" not in text


# ---------- build_step_prompt ----------


def test_step_prompt_core_elements(wf_repo):
    drv = _load(DRIVER, "drv_under_test")
    state = _write_state(wf_repo)
    node = engine.get_node("understand", 1)
    step = engine.sub_step_at(node, 2)
    prompt = drv.build_step_prompt(wf_repo, "t", state, node, 2, step, rework=None)
    assert f"目的：{step.purpose}" in prompt
    assert "子步骤 2/" in prompt
    assert "append-trace --scaffold" in prompt
    assert "禁输出 ### STEP_DONE" in prompt
    assert "### NEED_USER" in prompt
    assert "返工" not in prompt  # 无 rework 不出返工段
    prompt2 = drv.build_step_prompt(
        wf_repo, "t", state, node, 2, step, rework="判词XYZ"
    )
    assert "返工上下文" in prompt2 and "判词XYZ" in prompt2
    # Bash 形态铁律进铁律块（headless + 非裸 TUI 共享通道）；无 venv 回退 python3
    assert "Bash 形态铁律" in prompt
    assert "`python3`" in prompt
    assert "禁 `$(...)`" in prompt


def test_bash_shape_rules_venv_absolute_form(wf_repo):
    """项目有 venv 时钉绝对路径形态（./ 前缀会让白名单前缀匹配落空）。"""
    drv = _load(DRIVER, "drv_under_test")
    py = wf_repo / "venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("#!x", encoding="utf-8")
    text = drv._bash_shape_rules(wf_repo)
    assert f"`{py}`" in text
    assert "env VAR=值" in text  # 裸赋值前缀破前缀匹配的替代写法也钉死


# ---------- Step.interactive 标注（v3） ----------


def test_interactive_annotation_set():
    """interactive 标记集合 = 声明枚举（防漏标/漂移，design §3.4）。

    两源核对：8 个读回步 == _ARTIFACT_RENDER_SOURCES decision_steps 枚举；
    其余 5 个（u:1#1 逼问 / u:2#1 u:3#1 u:4#1 引出 / plan:1#2 发散）为
    ref 含 AskUserQuestion 的交互步，硬编码钉死——漏标会让 headless 段
    撞 AskUserQuestion 不可用，多标会白起 TUI 段。
    """
    readback = {
        (minor, step)
        for spec in engine._ARTIFACT_RENDER_SOURCES.values()
        for minor, step in spec["decision_steps"]
    }
    expect = readback | {
        ("ProblemContext", 1),
        ("GoalsAndValue", 1),
        ("ScopeAndConstraints", 1),
        ("SuccessCriteria", 1),
        ("DesignSolution", 2),
    }
    got = set()
    for ph in ("understand", "plan"):
        for sub in range(1, 5):
            node = engine.get_node(ph, sub)
            for i, s in enumerate(node.sub_steps, 1):
                if s.interactive:
                    got.add((node.minor_key, i))
    assert got == expect, f"差集: {got ^ expect}"


def test_interactive_step_prompt_variant(wf_repo):
    drv = _load(DRIVER, "drv_under_test")
    state = _write_state(wf_repo)
    node = engine.get_node("understand", 2)
    step = engine.sub_step_at(node, 5)  # 读回确认（interactive）
    prompt = drv.build_step_prompt(
        wf_repo, "t", state, node, 5, step, rework=None, interactive=True
    )
    assert "AskUserQuestion（回合内完成）" in prompt
    # 自动收段续跑（tui-auto-continue-design）：落库后 driver 自动收段，/exit 依赖消失
    assert "无需 /exit" in prompt
    assert "请 /exit 退出" not in prompt
    assert "返回 driver" not in prompt
    assert "NEED_USER" not in prompt  # TUI 段无 NEED_USER 出口
    assert "交接包" not in prompt  # 交接包归 SessionStart hook，prompt 不带


# ---------- TUI 退 = 全退（tui-exit-quits-driver-design） ----------


class _DispStub:
    def __init__(self):
        self.lines = []

    def log(self, msg):
        self.lines.append(msg)


def _fake_gate(action, reason=""):
    return lambda *a, **k: (action, reason, None)


def test_after_tui_exit_advanced(wf_repo, monkeypatch):
    drv = _load(DRIVER, "drv_under_test")
    _write_state(wf_repo)
    monkeypatch.setattr(engine, "gate_sub_step_at_stop", _fake_gate("advanced"))
    disp = _DispStub()
    rc = drv._after_tui_exit(
        wf_repo, "t", wf_repo / ".claude" / "worktrees" / "t", 1, disp
    )
    assert rc == 0
    assert "pending_rework" not in _read_state(wf_repo)
    assert any("已过门控" in line for line in disp.lines)


def test_after_tui_exit_block_persists_rework(wf_repo, monkeypatch):
    drv = _load(DRIVER, "drv_under_test")
    _write_state(wf_repo)
    monkeypatch.setattr(
        engine, "gate_sub_step_at_stop", _fake_gate("block", "判词原文XYZ")
    )
    disp = _DispStub()
    rc = drv._after_tui_exit(
        wf_repo, "t", wf_repo / ".claude" / "worktrees" / "t", 1, disp
    )
    assert rc == 0
    saved = _read_state(wf_repo)
    assert "判词原文XYZ" in saved["pending_rework"]  # 续跑恢复用，消费即清
    assert "append-trace" in saved["pending_rework"]


def test_after_tui_exit_escalate_and_none(wf_repo, monkeypatch):
    drv = _load(DRIVER, "drv_under_test")
    wt = wf_repo / ".claude" / "worktrees" / "t"
    for action in ("escalate", "none"):
        _write_state(wf_repo)
        monkeypatch.setattr(engine, "gate_sub_step_at_stop", _fake_gate(action, "r"))
        disp = _DispStub()
        rc = drv._after_tui_exit(wf_repo, "t", wt, 1, disp)
        assert rc == 0, action
        assert "pending_rework" not in _read_state(wf_repo), action
        assert any("续跑" in line for line in disp.lines), action


# ---------- PHASE_DONE 检测 ----------


def test_phase_done_re():
    drv = _load(DRIVER, "drv_under_test")
    assert (
        drv.PHASE_DONE_RE.search("bla\n### PHASE_DONE: execute\n").group(1) == "execute"
    )
    assert drv.PHASE_DONE_RE.search("### PHASE_DONE：execute") is None  # 中文冒号不算
    assert drv.PHASE_DONE_RE.search("## PHASE_DONE: plan") is None


# ---------- engine.set_drive_mode + CLI ----------


def test_set_drive_mode_function_and_cli(wf_repo):
    _write_state(wf_repo)
    ok, msg = engine.set_drive_mode(wf_repo, "t", True)
    assert ok and _read_state(wf_repo)["drive_mode"] is True
    r = subprocess.run(
        [
            sys.executable,
            str(DLWF_ROOT / "dl_flow_engine.py"),
            "drive-mode",
            "t",
            "off",
        ],
        cwd=wf_repo / ".claude" / "worktrees" / "t",
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert _read_state(wf_repo)["drive_mode"] is False


# ---------- workflow_advance drive_mode 早退 ----------


def _call_hook_main(mod, payload: dict) -> tuple[int, str]:
    old_stdin, old_stdout = sys.stdin, sys.stdout
    sys.stdin = io.StringIO(json.dumps(payload))
    sys.stdout = io.StringIO()
    try:
        rc = mod.main()
        return rc, sys.stdout.getvalue()
    finally:
        sys.stdin, sys.stdout = old_stdin, old_stdout


def test_advance_hook_drive_mode_skips_orchestration(wf_repo):
    _write_state(wf_repo, sub_step_index=2, drive_mode=True)
    mod = _load(ADVANCE_HOOK, "wa_drive_test")
    payload = {
        "cwd": str(wf_repo / ".claude" / "worktrees" / "t"),
        "session_id": "s",
        "transcript_path": "/nonexistent/x.jsonl",
    }
    rc, out = _call_hook_main(mod, payload)
    assert rc == 0
    assert out == ""  # 不注入续轮/门控指令
    # state 未被推进（防双 orchestrator 的核心断言）
    assert _read_state(wf_repo)["sub_step_index"] == 2


# ---------- workflow_step_fence drive_mode：S15/S10 跳过、S11 保留 ----------


def _fence_payload(wf_repo: Path, tool: str, tool_input: dict) -> dict:
    return {
        "cwd": str(wf_repo / ".claude" / "worktrees" / "t"),
        "tool_name": tool,
        "tool_input": tool_input,
    }


def test_fence_drive_mode_skips_s15(wf_repo):
    # 零 trace 窗口（S15 触发态）：drive_mode 下 WebFetch 放行，非 drive 下 deny
    _write_state(wf_repo, drive_mode=True)
    mod = _load(FENCE_HOOK, "fence_drive_on")
    rc, out = _call_hook_main(
        mod, _fence_payload(wf_repo, "WebFetch", {"url": "https://x"})
    )
    assert rc == 0 and "deny" not in out

    _write_state(wf_repo, drive_mode=False)
    mod2 = _load(FENCE_HOOK, "fence_drive_off")
    rc2, out2 = _call_hook_main(
        mod2, _fence_payload(wf_repo, "WebFetch", {"url": "https://x"})
    )
    assert rc2 == 0 and "deny" in out2  # S15 正常拦截（对照组）


def test_fence_drive_mode_keeps_s11_phase_write_fence(wf_repo):
    # understand 阶段禁写源码（S11）：drive_mode 下仍然拦截
    _write_state(wf_repo, drive_mode=True)
    mod = _load(FENCE_HOOK, "fence_drive_s11")
    target = wf_repo / ".claude" / "worktrees" / "t" / "src.py"
    rc, out = _call_hook_main(
        mod, _fence_payload(wf_repo, "Write", {"file_path": str(target)})
    )
    assert rc == 0 and "deny" in out
    assert "禁止写源码" in out


# ---------- 常驻进度区 + TUI TaskList 条款（drive-tasklist-render-design） ----------


def test_tui_rules_carry_opening_discipline(wf_repo):
    """§2.3 修订：开场纪律（TaskList/PHASE 横幅/裸开场顺序）单源 = TUI 段
    system prompt（ensure_tui_rules）——裸开场抽不走的通道（真机实证：条款住
    prompt 时裸开场零 TaskCreate/零横幅）；headless node-rules 不带本段。"""
    drv = _load(DRIVER, "drv_under_test")
    state = _write_state(wf_repo)
    node = engine.get_node("understand", 1)
    tui_rules = drv.ensure_tui_rules(wf_repo, "t", node, 1, state).read_text(
        encoding="utf-8"
    )
    assert "TUI 交互段开场纪律" in tui_rules
    assert "TaskCreate 一条消息批量建齐以下 19 项" in tui_rules  # 13+当前节点 6 子步骤
    assert "## PHASE: 理解和求证问题 [1/5]" in tui_rules
    assert "禁闷头连翻十几轮仓库零提问" in tui_rules
    assert "## 本节点子步骤清单" in tui_rules  # node-rules 本体仍在
    # Bash 形态铁律（2026-08-09 四类弹窗实证）——裸开场唯一通道，必须在这
    assert "Bash 形态铁律" in tui_rules
    assert "git -C" in tui_rules
    # headless 段 rules 不带 TUI 段（无 TUI 可透出）
    headless_rules = drv.ensure_node_rules(wf_repo, "t", node).read_text(
        encoding="utf-8"
    )
    assert "TUI 交互段开场纪律" not in headless_rules


def test_tui_rules_tasklist_same_source_as_driver(wf_repo):
    """清单内容同源（2026-08-09 用户裁决「内容同源，样式两制」）：TUI 段
    TaskCreate 的 subject+状态逐字渲染自 engine.progress_rows(state)
    （driver rich Live 同一数据源，**含当前节点子步骤维度**——只到
    minor_state 的粒度差是真机割裂实证）——两通道内容恒等，割裂只剩样式差。"""
    drv = _load(DRIVER, "drv_under_test")
    state = _write_state(wf_repo)  # 当前位置 understand:1 子1
    node = engine.get_node("understand", 1)
    text = drv.ensure_tui_rules(wf_repo, "t", node, 1, state).read_text(
        encoding="utf-8"
    )
    rows = engine.progress_rows(state)
    assert len(rows) == 19  # 13（5 阶段+u4 子+plan4 子）+ understand:1 展开 6 子步骤
    status_map = {"done": "completed", "current": "in_progress", "todo": "pending"}
    for r in rows:
        assert f'"{r["label"]}"（{status_map[r["status"]]}）' in text
    # 状态镜像抽样：当前子阶段/子步骤 in_progress、后续 pending
    assert '"1.1 理解问题和背景"（in_progress）' in text
    assert '"2. 生成执行计划"（pending）' in text
    # 子步骤维度：当前步 in_progress、后续步 pending（与 driver 进度区同粒度）
    assert '"1 逼问定义"（in_progress）' in text
    assert '"2 拆解深挖"（pending）' in text


def test_interactive_prompt_tasklist_clause(wf_repo):
    """§2.3 修订后：prompt 尾只留指针（开场纪律单源=ensure_tui_rules，防双份
    打架——症状 M 教训）；headless prompt 仍无任何 TaskList 内容。"""
    drv = _load(DRIVER, "drv_under_test")
    state = _write_state(wf_repo)
    node = engine.get_node("understand", 2)
    step = engine.sub_step_at(node, 5)  # 读回确认（interactive）
    prompt = drv.build_step_prompt(
        wf_repo, "t", state, node, 5, step, rework=None, interactive=True
    )
    assert "TUI 交互段开场纪律" in prompt  # 指针
    assert "TaskCreate 建齐 13 项" not in prompt  # 条款本体已搬走（单源化）
    # 非交互 prompt 不带（headless 段无 TUI，建了也无人可见）
    node2 = engine.get_node("understand", 1)
    step2 = engine.sub_step_at(node2, 2)
    prompt2 = drv.build_step_prompt(wf_repo, "t", state, node2, 2, step2, rework=None)
    assert "TaskCreate" not in prompt2


def test_live_progress_snapshot_lines(wf_repo):
    """§2.1：快照行 = 全清单 + ✓/▸/· + 当前行活动/耗时/最近动作。"""
    drv = _load(DRIVER, "drv_under_test")
    state = _write_state(wf_repo)
    disp = drv.LiveProgress(wf_repo, "t")
    disp.set_state(state)
    lines = disp._snapshot_lines()
    assert lines[0].startswith("══ 进度 ══ t")
    assert any(
        "▸ 1. 理解和求证问题" in line and "gate: pending" in line for line in lines
    )
    cur = [line for line in lines if "▸ 1 逼问定义" in line][0]
    assert "m0" not in cur  # 无活动（activity 空）→ 当前行不带耗时/活动
    disp.begin("子步骤 1/6 · 逼问定义")
    disp.set_action("Bash grep -rn foo")
    cur = [line for line in disp._snapshot_lines() if "▸ 1 逼问定义" in line][0]
    assert "子步骤 1/6 · 逼问定义" in cur and "Bash grep -rn foo" in cur


def test_live_progress_log_without_start(capsys, wf_repo):
    """log 事件上屏不依赖 Live 启动（降级路径/未 start 均安全）。"""
    drv = _load(DRIVER, "drv_under_test")
    disp = drv.LiveProgress(wf_repo, "t")
    disp.log("事件XYZ")
    assert "事件XYZ" in capsys.readouterr().out


def test_sub1_prompt_conversational_collect_clause(wf_repo):
    """§2.4 修订：开场问题陈述采集归 TUI 对话式——understand:1#1 prompt 钉死
    「建完清单立即对话式问用户问题陈述，拿到前禁探查」；其他交互步不带。"""
    drv = _load(DRIVER, "drv_under_test")
    state = _write_state(wf_repo)
    node = engine.get_node("understand", 1)
    step = engine.sub_step_at(node, 1)  # 逼问定义（interactive）
    prompt = drv.build_step_prompt(
        wf_repo, "t", state, node, 1, step, rework=None, interactive=True
    )
    assert "对话式问用户「本次要分析的问题是什么」" in prompt
    assert "禁任何仓库探查" in prompt
    # 其他交互步（u:2 读回）不带采集条款
    node2 = engine.get_node("understand", 2)
    step2 = engine.sub_step_at(node2, 5)
    prompt2 = drv.build_step_prompt(
        wf_repo, "t", state, node2, 5, step2, rework=None, interactive=True
    )
    assert "对话式问用户" not in prompt2


# ---------- 裸开场（drive-tasklist-render-design §2.4 修订2） ----------


def test_is_bare_open_only_fresh_u1s1():
    """裸开场只限 understand:1#1 且无返工；其余交互步/返工路径保持任务书驱动。"""
    drv = _load(DRIVER, "drv_under_test")
    u1 = engine.get_node("understand", 1)
    u2 = engine.get_node("understand", 2)
    assert drv._is_bare_open(u1, 1, None) is True
    assert drv._is_bare_open(u1, 2, None) is False  # u:1 子2
    assert drv._is_bare_open(u2, 1, None) is False  # 其他节点子1
    assert drv._is_bare_open(u1, 1, "返工判词") is False  # 返工=任务书兜底


def test_build_tui_cmd_bare_omits_prompt(tmp_path):
    """bare=True → cmd 无位置参数（会话开了安静等用户打字）；有 prompt → 末位附带。"""
    drv = _load(DRIVER, "drv_under_test")
    meta = tmp_path / "meta"
    cmd_bare = drv._build_tui_cmd(
        "sid-x", tmp_path / "s.json", tmp_path / "rules.md", None, False, meta
    )
    assert cmd_bare[-1] == "acceptEdits"  # 末位是 flag，无 prompt 位置参数
    assert "sid-x" in cmd_bare
    cmd_full = drv._build_tui_cmd(
        "sid-x", tmp_path / "s.json", tmp_path / "rules.md", "任务书", False, meta
    )
    assert cmd_full[-1] == "任务书"


# ---------- Ctrl+C 中断语义（drive-tasklist-render-design §2.6） ----------


class _FakeProc:
    def __init__(self, raises: int):
        self.raises = raises
        self.killed = False

    def wait(self):
        if self.raises:
            self.raises -= 1
            raise KeyboardInterrupt
        return 0

    def kill(self):
        self.killed = True


def test_pwait_single_interrupt_calls_on_first_not_kill():
    """单击=中断语义（on_first 一次）继续等，不杀进程不退出。"""
    drv = _load(DRIVER, "drv_under_test")
    calls = []
    p = _FakeProc(1)
    rc = drv._pwait_interruptible(p, on_first=lambda: calls.append(1))
    assert rc == 0 and calls == [1] and not p.killed


def test_pwait_double_interrupt_kills_and_exit_130():
    """双击=杀子进程 + SystemExit(130)——退出这个会话包括子任务。"""
    drv = _load(DRIVER, "drv_under_test")
    p = _FakeProc(2)
    with pytest.raises(SystemExit) as exc:
        drv._pwait_interruptible(p, on_first=lambda: None)
    assert exc.value.code == 130 and p.killed


def test_pwait_already_interrupted_counts_as_double():
    """读循环已捕过单击（already_interrupted=True）——本次 Ctrl+C 即双击退出。"""
    drv = _load(DRIVER, "drv_under_test")
    p = _FakeProc(1)
    with pytest.raises(SystemExit) as exc:
        drv._pwait_interruptible(p, on_first=lambda: None, already_interrupted=True)
    assert exc.value.code == 130 and p.killed


# ---------- TUI 段自动收段续跑（tui-auto-continue-design，2026-08-09 用户裁决） ----------


class _FakeTuiProc:
    pid = 4321


def _run_tui_step_stubbed(drv, repo, monkeypatch, captured):
    """run_tui_step 打桩：Popen→假进程；fake wait 期间抓取段标记内容（收段后即删，
    只有 wait 窗口内可观测）。"""
    meta = repo / ".claude" / "workflows" / "t"
    _write_state(repo)
    (meta / "settings.json").write_text(
        json.dumps({"permissions": {}}), encoding="utf-8"
    )
    monkeypatch.setattr(drv.subprocess, "Popen", lambda *a, **k: _FakeTuiProc())

    def fake_wait(proc, on_first=None):
        captured["segment"] = json.loads(
            (meta / "tui_segment.json").read_text(encoding="utf-8")
        )
        return 0

    monkeypatch.setattr(drv, "_pwait_interruptible", fake_wait)
    monkeypatch.setattr(engine, "latest_trace_sha1", lambda *a, **k: "sha0")
    node = engine.get_node("understand", 2)
    step = engine.sub_step_at(node, 5)  # 读回确认（interactive）
    return drv.run_tui_step(
        repo,
        "t",
        _read_state(repo),
        node,
        5,
        step,
        meta,
        False,
        repo / ".claude" / "worktrees" / "t",
        rework=None,
    )


def test_run_tui_step_writes_segment_marker(wf_repo, monkeypatch):
    """段标记：起 TUI 后写（pid/node/sub_step/minor_key/pre_sha），收段后删——
    Stop hook 的「本段新 trace」机械判定只在本文件存活期内生效。"""
    drv = _load(DRIVER, "drv_under_test")
    captured = {}
    rc, _sid = _run_tui_step_stubbed(drv, wf_repo, monkeypatch, captured)
    assert rc == 0
    seg = captured["segment"]
    assert seg["pid"] == 4321
    assert seg["node"] == "understand:2"
    assert seg["sub_step"] == 5
    assert seg["minor_key"] == "GoalsAndValue"
    assert seg["pre_sha"] == "sha0"  # 段启动前的最新 trace hash（新鲜度基线）
    meta = wf_repo / ".claude" / "workflows" / "t"
    assert not (meta / "tui_segment.json").exists()  # 收段即删


def test_run_tui_step_clears_stale_autodone(wf_repo, monkeypatch):
    """起段前清旧 autodone——防上一段的标记污染本段分流。"""
    drv = _load(DRIVER, "drv_under_test")
    meta = wf_repo / ".claude" / "workflows" / "t"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "tui_autodone.json").write_text("{}", encoding="utf-8")
    _run_tui_step_stubbed(drv, wf_repo, monkeypatch, {})
    assert not (meta / "tui_autodone.json").exists()


def test_handle_tui_segment_end_autodone_goes_shared_gate(wf_repo):
    """有 autodone（模型落库 = 活已干完）→ None：主循环落共享门控自动续跑，
    driver 不退出（/exit 依赖消失）；标记消费即删。"""
    drv = _load(DRIVER, "drv_under_test")
    _write_state(wf_repo)
    meta = wf_repo / ".claude" / "workflows" / "t"
    (meta / "tui_autodone.json").write_text(
        json.dumps({"node": "understand:1", "sub_step": 1, "sha": "s"}),
        encoding="utf-8",
    )
    disp = _DispStub()
    rc = drv._handle_tui_segment_end(
        wf_repo, "t", wf_repo / ".claude" / "worktrees" / "t", 1, meta, disp
    )
    assert rc is None
    assert not (meta / "tui_autodone.json").exists()  # 消费即删
    assert any("自动收段" in line for line in disp.lines)


def test_handle_tui_segment_end_manual_exit_full_quit(wf_repo, monkeypatch):
    """无 autodone（手动 /exit / 双击 Ctrl+C）→ TUI 退 = 全退（裁决不变）。"""
    drv = _load(DRIVER, "drv_under_test")
    _write_state(wf_repo)
    monkeypatch.setattr(engine, "gate_sub_step_at_stop", _fake_gate("advanced"))
    disp = _DispStub()
    rc = drv._handle_tui_segment_end(
        wf_repo,
        "t",
        wf_repo / ".claude" / "worktrees" / "t",
        1,
        wf_repo / ".claude" / "workflows" / "t",
        disp,
    )
    assert rc == 0
    assert any("已过门控" in line for line in disp.lines)
