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
PHASE_HOOK = DLWF_ROOT / "hooks" / "workflow_phase.py"

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


def test_drive_settings_strips_statusline(wf_repo):
    """statusLine 是 TUI 件：headless claude -p 无 TUI，drive 派生剔除
    （与 outputStyle 同批，v4-statusline-progress-design §5.2）。"""
    drv = _load(DRIVER, "drv_under_test")
    meta = wf_repo / ".claude" / "workflows" / "t"
    (meta / "settings.json").write_text(
        json.dumps(
            {
                "statusLine": {
                    "type": "command",
                    "command": "x",
                    "refreshInterval": 10,
                },
                "permissions": {"defaultMode": "acceptEdits"},
            }
        ),
        encoding="utf-8",
    )
    out = drv.ensure_drive_settings(wf_repo, "t")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "statusLine" not in data


# ---------- ensure_node_rules ----------


def test_node_rules_is_node_scoped_not_full_template(wf_repo):
    drv = _load(DRIVER, "drv_under_test")
    node = engine.get_node("understand", 1)
    out = drv.ensure_node_rules(wf_repo, "t", node, 1)
    text = out.read_text(encoding="utf-8")
    assert "子步骤" in text
    assert "禁输出 ### STEP_DONE" in text
    assert "载荷格式以 --scaffold 骨架为准" in text  # 禁反向 grep engine 核对格式
    # 瘦版：只含本节点段落——本节点 GENERATED 段在、其它节点的段不在
    assert "sub_steps understand:1" in text
    assert "sub_steps plan:" not in text
    assert "sub_steps understand:2" not in text


def test_node_rules_injects_project_tools(wf_repo, monkeypatch):
    """注册工具后，node-rules 含「本项目工具」段（组件 B 注入）。"""
    drv = _load(DRIVER, "drv_under_test")
    from scripts.workflow import project_tools as pt

    monkeypatch.setattr(
        pt,
        "load_project_tools",
        lambda pr: [
            {
                "name": "inspect-backtest-result",
                "command": "scripts/inspect.py --factor {factor}",
                "description": "读回测",
                "arg_hint": "--factor <f>",
            }
        ],
    )
    node = engine.get_node("understand", 1)
    out = drv.ensure_node_rules(wf_repo, "t", node, 1)
    text = out.read_text(encoding="utf-8")
    assert "## 本项目工具" in text
    assert "inspect-backtest-result" in text  # name（设计意图「给模型看的名字」）
    assert "scripts/inspect.py --factor {factor}" in text  # command
    assert "--factor <f>" in text  # arg_hint
    assert "读回测" in text  # description


def test_node_rules_omits_project_tools_section_without_tools(wf_repo):
    """无工具（无 workflow-tools.yaml）时，node-rules 不含「本项目工具」段。"""
    drv = _load(DRIVER, "drv_under_test")
    node = engine.get_node("understand", 1)
    out = drv.ensure_node_rules(wf_repo, "t", node, 1)
    text = out.read_text(encoding="utf-8")
    assert "## 本项目工具" not in text
    assert "inspect-backtest-result" not in text


def test_node_rules_injection_handles_null_fields(wf_repo, monkeypatch):
    """注入对 None command/description/arg_hint 安全（不渲染字面 "None"）。"""
    drv = _load(DRIVER, "drv_under_test")
    from scripts.workflow import project_tools as pt

    monkeypatch.setattr(
        pt,
        "load_project_tools",
        lambda pr: [
            {
                "name": "flaky-tool",
                "command": None,
                "description": None,
                "arg_hint": None,
            }
        ],
    )
    node = engine.get_node("understand", 1)
    out = drv.ensure_node_rules(wf_repo, "t", node, 1)
    text = out.read_text(encoding="utf-8")
    assert "## 本项目工具" in text
    assert "None" not in text


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


def test_step_prompt_pack_self_contained_clause(wf_repo):
    """u2-sub2-cost：pack_self_contained 步的段 prompt 带材料边界条款
    （材料全在包内、禁 Read evidence 全量），未置位步不带。"""
    drv = _load(DRIVER, "drv_under_test")
    state = _write_state(wf_repo)
    node = engine.get_node("understand", 2)
    step2 = engine.sub_step_at(node, 2)
    assert step2.pack_self_contained is True  # u:2#2 置位（单源核对）
    prompt = drv.build_step_prompt(wf_repo, "t", state, node, 2, step2, rework=None)
    assert "材料边界" in prompt
    assert "禁 Read evidence 全量翻找" in prompt
    step3 = engine.sub_step_at(node, 3)
    prompt3 = drv.build_step_prompt(wf_repo, "t", state, node, 3, step3, rework=None)
    assert "材料边界" not in prompt3


def test_step_prompt_self_contained_clause_interactive(wf_repo):
    """u4-sub1-cost：交互步置位 pack_self_contained 时段 prompt 同样带材料
    边界条款——u:4#1 是首个置位的交互步（条款在非-prep else 分支，交互步
    同路径），钉死交互分支覆盖，防未来重构把交互步切出条款面。"""
    drv = _load(DRIVER, "drv_under_test")
    state = _write_state(wf_repo)
    node = engine.get_node("understand", 4)
    step1 = engine.sub_step_at(node, 1)
    assert step1.pack_self_contained is True  # u:4#1 置位（单源核对）
    assert step1.interactive is True
    prompt = drv.build_step_prompt(
        wf_repo, "t", state, node, 1, step1, interactive=True, rework=None
    )
    assert "材料边界" in prompt
    assert "禁 Read evidence 全量翻找" in prompt


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
    assert "TaskCreate 一条消息批量建齐以下 20 项" in tui_rules  # 13+当前节点 7 子步骤
    assert "## PHASE: 理解和求证问题 [1/5]" in tui_rules
    assert "禁闷头连翻十几轮仓库零提问" in tui_rules
    assert "## 本节点子步骤清单" in tui_rules  # node-rules 本体仍在
    # Bash 形态铁律（2026-08-09 四类弹窗实证）——裸开场唯一通道，必须在这
    assert "Bash 形态铁律" in tui_rules
    assert "git -C" in tui_rules
    # headless 段 rules 不带 TUI 段（无 TUI 可透出）
    headless_rules = drv.ensure_node_rules(wf_repo, "t", node, 1).read_text(
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
    assert len(rows) == 20  # 13（5 阶段+u4 子+plan4 子）+ understand:1 展开 7 子步骤
    status_map = {"done": "completed", "current": "in_progress", "todo": "pending"}
    for r in rows:
        assert f'"{r["label"]}"（{status_map[r["status"]]}）' in text
    # 状态镜像抽样：当前子阶段/子步骤 in_progress、后续 pending
    assert '"1.1 理解问题和背景"（in_progress）' in text
    assert '"2. 生成执行计划"（pending）' in text
    # 子步骤维度：当前步 in_progress、后续步 pending（与 driver 进度区同粒度）
    assert '"1 逼问定义"（in_progress）' in text
    assert '"2 规划拆解"（pending）' in text


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
    assert cmd_bare[-1] == drv.engine.NO_MCP_ARGS[-1]  # 末位是 flag，无 prompt 位置参数
    assert "sid-x" in cmd_bare
    cmd_full = drv._build_tui_cmd(
        "sid-x", tmp_path / "s.json", tmp_path / "rules.md", "任务书", False, meta
    )
    assert cmd_full[-1] == "任务书"
    # u3-sub1-cost：prompt 前必须有 `--` 分隔——--mcp-config 是 variadic，
    # 无分隔时 prompt 被吞作配置文件路径（ENAMETOOLONG rc=1 秒退实证）。
    assert cmd_full[-2] == "--"


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


# ---------- --segment 段执行器（front-tui-hybrid-design M1）----------
#
# 段语义：从 state 当前位置起连续跑非交互工作，撞「需要人或需要前台」的边界
# 按退出码收场（0 完成 / 10 交互步 / 11 门栏闸门 / 12 断点 / 13 NEED_USER / 1 异常），
# 断点去 stdin 化（breakpoint_loop 不可用——段无前台），结局落 segment_summary.json；
# front_segment.json 锁（pid+起跑位置）随退出清；drive_mode try/finally 恢复 off。

import os  # noqa: E402

SEG_META = ".claude/workflows/t"


def _seg_write_state(repo: Path, **over) -> dict:
    """段测试 state：补 per-wf settings.json（ensure_drive_settings 的派生源，
    真机由 launcher 保证存在）。"""
    (repo / SEG_META / "settings.json").write_text(
        json.dumps({"permissions": {}}), encoding="utf-8"
    )
    return _write_state(repo, **over)


def _summary(repo: Path) -> dict:
    return json.loads(
        (repo / SEG_META / "segment_summary.json").read_text(encoding="utf-8")
    )


def _run_session_stub(drv, monkeypatch, outs) -> list:
    """按序返回 (rc, out, sid)（Exception 实例则抛出），捕获逐次 prompt。"""
    calls = []
    it = iter(outs)

    def fake(prompt, **kw):
        calls.append(prompt)
        item = next(it)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(drv, "run_session", fake)
    return calls


def _gate_advancing(repo: Path):
    """假门控：advanced 并真实推进 state（子步 +1；越界则跨到 understand:2#1）。

    understand:1 共 6 子步骤（子1 交互/子2-6 非交互），understand:2#1 交互——
    段从 u:1 任一非交互步起跑，推进耗尽后必撞交互步退出 10。
    """

    def fake(project_root, name, cwd):
        st = _read_state(repo)
        node = engine.get_node(st["phase"], st["sub_index"])
        cur = st.get("sub_step_index", 1)
        if cur < len(node.sub_steps):
            st["sub_step_index"] = cur + 1
        else:
            st.update(sub_index=2, node="understand:2", sub_step_index=1)
        (repo / SEG_META / "state.json").write_text(json.dumps(st), encoding="utf-8")
        return ("advanced", "", None)

    return fake


def test_segment_interactive_step_prep_then_exit_13(wf_repo, monkeypatch):
    """交互步后台化（interactive-step-headless-prep §4.1）：当前步即交互步（u:2#1）
    不再停段——跑 prep 会话（L1 disallow_ask=True），NEED_USER + 问题载荷 →
    退出 13 + need_user.json 落盘 + summary 带载荷指针。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(wf_repo, sub_index=2, node="understand:2", sub_step_index=1)
    out = (
        "问题已备好\n### NEED_USER\n```json\n"
        '{"questions": [{"question": "q1", "header": "h", "multiSelect": false,'
        ' "options": []}]}\n```'
    )
    seen = {}

    def fake(prompt, **kw):
        seen["prompt"] = prompt
        seen["kw"] = kw
        return (0, out, "s")

    monkeypatch.setattr(drv, "run_session", fake)
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 13
    assert seen["kw"].get("disallow_ask") is True  # L1 工具封锁
    assert "预处理" in seen["prompt"]  # 变体 prompt
    data = json.loads((wf_repo / SEG_META / "need_user.json").read_text())
    assert data["questions"][0]["question"] == "q1"
    assert "need_user.json" in _summary(wf_repo)["message"]
    meta = wf_repo / SEG_META
    assert not (meta / "front_segment.json").exists()  # 锁随退出清
    assert _read_state(wf_repo)["drive_mode"] is False  # 编排权交回前台


def test_segment_bare_open_still_exits_10(wf_repo, monkeypatch):
    """裸开场（u:1#1 无返工）保 TUI 段退出 10——57a64e1 用户裁决不动。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(wf_repo, sub_step_index=1)
    calls = _run_session_stub(drv, monkeypatch, [])
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 10 and calls == []


def test_segment_prep_askuser_sniff_forces_13(wf_repo, monkeypatch):
    """L2 嗅探（§4.2）：prep 会话忘输出 NEED_USER 但 stream 里调了
    AskUserQuestion（denial 回执也是 tool_use 形态）→ 机械按 code 13 收场。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(wf_repo, sub_index=2, node="understand:2", sub_step_index=1)
    meta = wf_repo / SEG_META

    def fake(prompt, **kw):
        with open(meta / "drive-stream.jsonl", "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "session_id": "s",
                        "message": {
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "AskUserQuestion",
                                    "input": {},
                                }
                            ]
                        },
                    }
                )
                + "\n"
            )
        return (0, "（忘输出标记）", "s")

    monkeypatch.setattr(drv, "run_session", fake)
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 13


def test_segment_prep_no_exit_retries_then_12(wf_repo, monkeypatch):
    """L3（§4.2）：prep 会话既无标记也无工具嗅探 → none 计数重试，达限退 12。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(wf_repo, sub_index=2, node="understand:2", sub_step_index=1)
    calls = _run_session_stub(drv, monkeypatch, [(0, "", "s")] * drv.NONE_RETRY_LIMIT)
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 12 and len(calls) == drv.NONE_RETRY_LIMIT
    assert "NEED_USER" in _summary(wf_repo)["message"]


def test_session_called_ask_user_sniff(wf_repo):
    """L2 嗅探函数：按 session_id 匹配 AskUserQuestion tool_use；他会话/坏行不扰。"""
    drv = _load(DRIVER, "drv_seg")
    meta = wf_repo / SEG_META
    lines = [
        json.dumps(
            {
                "type": "assistant",
                "session_id": "other",
                "message": {
                    "content": [{"type": "tool_use", "name": "AskUserQuestion"}]
                },
            }
        ),
        "{bad json",
        json.dumps(
            {
                "type": "assistant",
                "session_id": "s",
                "message": {"content": [{"type": "tool_use", "name": "Read"}]},
            }
        ),
    ]
    (meta / "drive-stream.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert drv._session_called_ask_user(meta, "s") is False
    with open(meta / "drive-stream.jsonl", "a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "type": "assistant",
                    "session_id": "s",
                    "message": {
                        "content": [{"type": "tool_use", "name": "AskUserQuestion"}]
                    },
                }
            )
            + "\n"
        )
    assert drv._session_called_ask_user(meta, "s") is True


def test_stash_need_user_payload(wf_repo):
    """问题载荷提取（§4.4）：合法 → need_user.json 落盘；非法/缺失 → 清陈旧文件。"""
    drv = _load(DRIVER, "drv_seg")
    meta = wf_repo / SEG_META
    good = 'x\n### NEED_USER\n```json\n{"questions": [{"question": "q1"}]}\n```'
    assert drv._stash_need_user_payload(meta, good) is True
    data = json.loads((meta / "need_user.json").read_text())
    assert data["questions"][0]["question"] == "q1" and data["ts"]
    # 非法载荷：清掉上一轮的合法文件（防陈旧载荷被当下轮的用）
    assert drv._stash_need_user_payload(meta, "x\n### NEED_USER\n没给json") is False
    assert not (meta / "need_user.json").exists()
    assert (
        drv._stash_need_user_payload(meta, "### NEED_USER\n```json\n{bad}\n```")
        is False
    )


def test_step_prompt_prep_variant(wf_repo):
    """prep 变体 prompt（§4.3）：交付=NEED_USER+问题载荷；禁 AskUserQuestion/
    禁落 trace/禁编造答复；无 append-trace 指引（prep 不交 trace）。"""
    drv = _load(DRIVER, "drv_under_test")
    state = _write_state(wf_repo, sub_index=2, node="understand:2")
    node = engine.get_node("understand", 2)
    step = engine.sub_step_at(node, 1)
    assert step.interactive  # u:2#1 引出步（防节点数据漂移误选非交互步）
    prompt = drv.build_step_prompt(
        wf_repo, "t", state, node, 1, step, rework=None, prep=True
    )
    assert "预处理" in prompt
    assert "### NEED_USER" in prompt
    assert '"questions"' in prompt  # 载荷契约
    assert "禁调 AskUserQuestion" in prompt
    assert "禁编造用户答复" in prompt
    assert "append-trace" not in prompt  # prep 不落 trace（归前台问答段）


def test_segment_runs_headless_steps_then_prep_exits_13(wf_repo, monkeypatch):
    """u:1#2 起跑：子2-6 各一个 headless 会话，子7（读回=交互步）跑 prep 后退出 13。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(wf_repo, sub_step_index=2)
    need_out = 'ok\n### NEED_USER\n```json\n{"questions": [{"question": "q"}]}\n```'
    calls = _run_session_stub(
        drv, monkeypatch, [(0, "", "s")] * 5 + [(0, need_out, "s")]
    )
    monkeypatch.setattr(engine, "gate_sub_step_at_stop", _gate_advancing(wf_repo))
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 13
    # u:1 子2..6 headless + u:2#1 prep（P3-1：子7 读回降确认级，无 prep 段直通）
    assert len(calls) == 6
    st = _read_state(wf_repo)
    assert st["node"] == "understand:2" and st["sub_step_index"] == 1


def test_segment_lock_live_during_run(wf_repo, monkeypatch):
    """段运行期间 front_segment.json 锁活（pid=本进程+起跑位置），退出即删。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(wf_repo, sub_step_index=5)  # 只跑一步（#5→推进到交互步 #6 prep）
    meta = wf_repo / SEG_META
    seen = {}
    need_out = 'ok\n### NEED_USER\n```json\n{"questions": [{"question": "q"}]}\n```'
    outs = iter([(0, "", "s"), (0, need_out, "s")])

    def fake(prompt, **kw):
        seen["lock"] = json.loads(
            (meta / "front_segment.json").read_text(encoding="utf-8")
        )
        return next(outs)

    monkeypatch.setattr(drv, "run_session", fake)
    monkeypatch.setattr(engine, "gate_sub_step_at_stop", _gate_advancing(wf_repo))
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 13
    assert seen["lock"]["pid"] == os.getpid()
    assert seen["lock"]["sub_step"] == 5  # 起跑位置
    assert seen["lock"]["started_at"]
    assert not (meta / "front_segment.json").exists()


def test_segment_exits_11_on_held_for_gate(wf_repo, monkeypatch):
    """门栏扣留 → 退出 11（等用户 /dl gate），不起子会话。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(wf_repo, held_for_gate=True)
    calls = _run_session_stub(drv, monkeypatch, [])
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 11 and calls == []
    assert "门栏" in _summary(wf_repo)["message"]


def test_segment_exits_11_on_phase_gate(wf_repo, monkeypatch):
    """PHASE_DONE 通道开 + 阶段闸门未放行 → 退出 11。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(
        wf_repo,
        phase="plan",
        sub_index=4,
        node="plan:4",
        sub_step_index=5,
        gate="pending",
    )
    monkeypatch.setattr(engine, "phase_done_channel_open", lambda *a: True)
    monkeypatch.setattr(engine, "is_gated_after", lambda ph: True)
    calls = _run_session_stub(drv, monkeypatch, [])
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 11 and calls == []
    assert "闸门" in _summary(wf_repo)["message"]


def test_segment_exits_12_on_escalate(wf_repo, monkeypatch):
    """门控 escalate（连续 block 达阈值）→ 退出 12，判词进 summary。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(wf_repo, sub_step_index=2)
    calls = _run_session_stub(drv, monkeypatch, [(0, "", "s")])
    monkeypatch.setattr(
        engine, "gate_sub_step_at_stop", _fake_gate("escalate", "判词Q")
    )
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 12 and len(calls) == 1
    assert "判词Q" in _summary(wf_repo)["message"]


def test_segment_exits_12_on_none_retry_limit(wf_repo, monkeypatch):
    """连续 NONE_RETRY_LIMIT 次会话未落 trace → 退出 12（防无限白烧）。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(wf_repo, sub_step_index=2)
    calls = _run_session_stub(drv, monkeypatch, [(0, "", "s")] * drv.NONE_RETRY_LIMIT)
    monkeypatch.setattr(engine, "gate_sub_step_at_stop", _fake_gate("none"))
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 12 and len(calls) == drv.NONE_RETRY_LIMIT


def test_segment_exits_13_on_need_user(wf_repo, monkeypatch):
    """headless 会话输出 ### NEED_USER → 退出 13（动态重分类为交互，回前台处理）。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(wf_repo, sub_step_index=2)
    calls = _run_session_stub(
        drv, monkeypatch, [(0, "结果\n### NEED_USER\n问题清单", "s")]
    )
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 13 and len(calls) == 1


def test_segment_exits_0_when_workflow_done(wf_repo):
    """gate=done（五阶段终结）→ 退出 0。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(wf_repo, gate="done")
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 0
    assert _summary(wf_repo)["code"] == 0


def test_segment_block_feeds_rework_into_next_prompt(wf_repo, monkeypatch):
    """段内 block 不出段：判词装配返工上下文重发本步（v3 语义原样）。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(wf_repo, sub_step_index=5)  # block 重跑本步后推进到 #6 交互 prep
    need_out = 'ok\n### NEED_USER\n```json\n{"questions": [{"question": "q"}]}\n```'
    calls = _run_session_stub(
        drv, monkeypatch, [(0, "", "s"), (0, "", "s"), (0, need_out, "s")]
    )
    advancing = _gate_advancing(wf_repo)
    seq = [("block", "判词Z", None)]

    def fake_gate(*a):
        return seq.pop(0) if seq else advancing(*a)

    monkeypatch.setattr(engine, "gate_sub_step_at_stop", fake_gate)
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 13  # #6 交互步 prep 后 NEED_USER 收场
    assert len(calls) == 3
    assert "判词Z" in calls[1]  # 返工上下文进重发 prompt


def test_segment_exception_restores_drive_mode(wf_repo, monkeypatch):
    """段内异常（API 挂等）→ 退出 1；drive_mode 恢复 off、锁清、summary 落盘。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(wf_repo, sub_step_index=2)
    _run_session_stub(drv, monkeypatch, [RuntimeError("api炸")])
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 1
    assert "api炸" in _summary(wf_repo)["message"]
    assert _read_state(wf_repo)["drive_mode"] is False
    assert not (wf_repo / SEG_META / "front_segment.json").exists()


def test_main_routes_segment_flag(wf_repo, monkeypatch):
    """--segment flag 路由到 run_segment（全程 driver 路径不受影响）。"""
    drv = _load(DRIVER, "drv_seg")
    monkeypatch.chdir(wf_repo / ".claude" / "worktrees" / "t")
    seen = {}

    def fake_segment(project_root, name, debug=False):
        seen.update(project_root=project_root, name=name)
        return 10

    monkeypatch.setattr(drv, "run_segment", fake_segment)
    rc = drv.main(["t", "--segment"])
    assert rc == 10 and seen["name"] == "t"


# ---------- front_mode 前台混合（front-tui-hybrid-design §2.3，M2）----------
#
# 三分支：phase 注入派发块（当前步非交互且段不在跑）/ advance stall 兜底重提示
# （3 次计数闸）/ fence 非交互步白名单（防前台模型抢干活=上下文胀回 v2.x 病灶）。
# 段在跑 = drive_mode on（hooks 既有早退分支覆盖）；交互步 / NEED_USER 动态
# 重分类（summary code 13 咬合当前位置）= 落 v2 既有路径一行不改。


def _phase_injection(repo: Path, **over) -> str:
    _write_state(repo, **over)
    mod = _load(PHASE_HOOK, "wp_front_test")
    payload = {
        "cwd": str(repo / ".claude" / "worktrees" / "t"),
        "session_id": "s",
        "prompt": "继续",
    }
    _rc, out = _call_hook_main(mod, payload)
    data = json.loads(out)
    return data["hookSpecificOutput"]["additionalContext"]


def _advance_front(repo: Path, **over) -> tuple[int, str]:
    _write_state(repo, **over)
    mod = _load(ADVANCE_HOOK, "wa_front_test")
    payload = {
        "cwd": str(repo / ".claude" / "worktrees" / "t"),
        "session_id": "s",
        "transcript_path": "/nonexistent/x.jsonl",
    }
    return _call_hook_main(mod, payload)


def _write_summary(repo: Path, code: int, node="understand:1", sub_step=2) -> None:
    (repo / SEG_META / "segment_summary.json").write_text(
        json.dumps(
            {
                "code": code,
                "message": "m",
                "ts": "t",
                "node": node,
                "sub_step": sub_step,
            }
        ),
        encoding="utf-8",
    )


def _write_lock(repo: Path, pid: int) -> None:
    (repo / SEG_META / "front_segment.json").write_text(
        json.dumps(
            {"pid": pid, "started_at": "t", "node": "understand:1", "sub_step": 2}
        ),
        encoding="utf-8",
    )


# ---- engine 单源 ----


def test_set_front_mode_function_and_cli(wf_repo):
    _write_state(wf_repo)
    ok, _msg = engine.set_front_mode(wf_repo, "t", True)
    assert ok and _read_state(wf_repo)["front_mode"] is True
    r = subprocess.run(
        [
            sys.executable,
            str(DLWF_ROOT / "dl_flow_engine.py"),
            "front-mode",
            "t",
            "off",
        ],
        cwd=wf_repo / ".claude" / "worktrees" / "t",
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert _read_state(wf_repo)["front_mode"] is False


def test_front_segment_alive_pid_liveness(wf_repo):
    _write_state(wf_repo)
    assert engine.front_segment_alive(wf_repo, "t") is False  # 无锁
    _write_lock(wf_repo, 99999999)  # 死 pid = stale 锁
    assert engine.front_segment_alive(wf_repo, "t") is False
    _write_lock(wf_repo, os.getpid())  # 活 pid
    assert engine.front_segment_alive(wf_repo, "t") is True


def test_front_dynamic_interactive_summary_13咬合(wf_repo):
    st = _write_state(wf_repo, sub_step_index=2)
    assert engine.front_dynamic_interactive(wf_repo, "t", st) is False  # 无 summary
    _write_summary(wf_repo, 13)
    assert engine.front_dynamic_interactive(wf_repo, "t", st) is True
    _write_summary(wf_repo, 10)  # 非 13
    assert engine.front_dynamic_interactive(wf_repo, "t", st) is False
    _write_summary(wf_repo, 13, sub_step=3)  # 位置不咬合 = 陈旧 summary
    assert engine.front_dynamic_interactive(wf_repo, "t", st) is False


def test_front_segment_command_single_source():
    cmd = engine.front_segment_command("my-wf")
    assert "dl_drive.py my-wf --segment" in cmd
    assert cmd.startswith("python3 ")


# ---- workflow_phase：派发块注入 ----


def test_phase_front_needuser_payload_pointer(wf_repo):
    """code 13 咬合 + need_user.json 在场 → 注入「逐字照抄」提问指针（§4.4 前者裁决）。"""
    _write_summary(wf_repo, 13, node="understand:1", sub_step=2)
    (wf_repo / SEG_META / "need_user.json").write_text(
        json.dumps({"questions": [{"question": "q1"}]}), encoding="utf-8"
    )
    text = _phase_injection(wf_repo, front_mode=True, sub_step_index=2)
    assert "need_user.json" in text
    assert "逐字照抄" in text


def test_phase_front_needuser_pointer_requires_fresh_13(wf_repo):
    """陈旧 need_user.json（无 code 13 咬合 summary）→ 不给指针（防旧载荷误用）。"""
    (wf_repo / SEG_META / "need_user.json").write_text(
        json.dumps({"questions": [{"question": "q1"}]}), encoding="utf-8"
    )
    text = _phase_injection(wf_repo, front_mode=True, sub_step_index=2)
    assert "need_user.json" not in text


# ---- 裸开场收窄：陈述机械捕获 + step1 后台化（interactive-step-headless-prep §8）----


def _phase_injection_prompt(repo: Path, prompt: str, **over) -> str:
    """带自定义 prompt 的 phase 注入（_phase_injection 固定「继续」的泛化）。"""
    _write_state(repo, **over)
    mod = _load(PHASE_HOOK, "wp_front_test")
    payload = {
        "cwd": str(repo / ".claude" / "worktrees" / "t"),
        "session_id": "s",
        "prompt": prompt,
    }
    _rc, out = _call_hook_main(mod, payload)
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_phase_capture_statement_at_bare_open(wf_repo):
    """裸开场位置首条 prompt = 问题陈述：机械捕获 + 当轮即派段（step1 也后台）。"""
    text = _phase_injection_prompt(wf_repo, "帮我分析5348.7%是否异常", front_mode=True)
    st = _read_state(wf_repo)
    assert st["problem_statement"] == "帮我分析5348.7%是否异常"
    assert "已记录" in text
    assert "活归后台工人" in text  # 捕获当轮路由即翻转（有陈述 ≠ 裸开场）


def test_phase_capture_skips_command_and_short(wf_repo):
    """防误捕：斜杠命令与 <3 字符的 prompt 不当陈述。"""
    _phase_injection_prompt(wf_repo, "/dl status", front_mode=True)
    assert "problem_statement" not in _read_state(wf_repo)
    _phase_injection_prompt(wf_repo, "继续", front_mode=True)
    assert "problem_statement" not in _read_state(wf_repo)


def test_phase_capture_no_overwrite(wf_repo):
    """已有陈述不覆盖（重开/续跑场景）。"""
    text = _phase_injection_prompt(
        wf_repo, "想换个问题分析", front_mode=True, problem_statement="旧陈述"
    )
    assert _read_state(wf_repo)["problem_statement"] == "旧陈述"
    assert "已记录" not in text


def test_phase_capture_only_at_bare_open(wf_repo):
    """非 u:1#1 位置不捕获。"""
    _phase_injection_prompt(
        wf_repo, "这不是问题陈述哦", front_mode=True, sub_step_index=2
    )
    assert "problem_statement" not in _read_state(wf_repo)


def test_phase_capture_v2_mode_keeps_work_here(wf_repo):
    """v2 模式（无 front_mode）：捕获照做但路由不变——step1 仍前台干（无段概念）。"""
    text = _phase_injection_prompt(wf_repo, "我的问题是X123")
    assert _read_state(wf_repo)["problem_statement"] == "我的问题是X123"
    assert "当前子步骤 1/7" in text
    assert "活归后台工人" not in text


def test_segment_bare_open_with_statement_runs_prep(wf_repo, monkeypatch):
    """有陈述的 u:1#1 = 非裸开场：段内走 prep（§8）——退 13 不退 10。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(wf_repo, sub_step_index=1, problem_statement="分析X是否异常")
    need_out = 'ok\n### NEED_USER\n```json\n{"questions": [{"question": "q"}]}\n```'
    calls = _run_session_stub(drv, monkeypatch, [(0, need_out, "s")])
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 13 and len(calls) == 1
    assert "预处理" in calls[0]


def test_is_bare_open_has_statement():
    """_is_bare_open §8 新条件：有陈述 = 非裸开场。"""
    drv = _load(DRIVER, "drv_seg")
    node = engine.get_node("understand", 1)
    assert drv._is_bare_open(node, 1, None, has_statement=False) is True
    assert drv._is_bare_open(node, 1, None, has_statement=True) is False


def test_run_session_disallow_ask_flag_order(wf_repo, monkeypatch):
    """--disallowedTools 是变长参数（<tools...>）：其后必须跟旗标而非位置参数
    prompt——2026-08-12 实爆：prompt 被吞成工具名，claude 秒退 rc=1
    「Input must be provided」，prep 3 连空转退 12。"""
    drv = _load(DRIVER, "drv_rs")
    captured = {}

    class _FakeProc:
        stdout = iter([])
        stdin = io.StringIO()

        def wait(self):
            return 0

        def terminate(self):
            pass

        def kill(self):
            pass

    def fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr(drv.subprocess, "Popen", fake_popen)
    meta = wf_repo / SEG_META
    drv.run_session(
        "提示词正文",
        cwd=wf_repo,
        settings=meta / "settings.json",
        sys_prompt_file=meta / "rules.md",
        meta=meta,
        debug=False,
        note="t",
        disallow_ask=True,
    )
    cmd = captured["cmd"]
    # prompt 已改走 stdin（ARG_MAX 修复）——断言旗标语义：--disallowedTools
    # 变长参数后必跟旗标（不再有 prompt 位置参数，吞名风险按构造消失）
    assert "提示词正文" not in cmd
    i = cmd.index("--disallowedTools")
    assert cmd[i + 1] == "AskUserQuestion"
    assert cmd[i + 2].startswith("--")


def test_phase_front_dispatch_block_on_noninteractive_step(wf_repo):
    text = _phase_injection(wf_repo, front_mode=True, sub_step_index=2)  # u:1#2 非交互
    assert "活归后台工人" in text
    assert "dl_drive.py t --segment" in text
    assert "run_in_background" in text
    # 干活指令块不下发（防前台模型误以为活是自己的）
    assert "落库后输出 `### STEP_DONE" not in text
    # 段会连续推进多步：位置是起跑快照不是「当前」（dogfood 文案 bug 修复），
    # 段内实时进度指路底部状态栏
    assert "起跑位置" in text
    assert "状态栏" in text


def test_phase_front_no_dispatch_on_interactive_step(wf_repo):
    text = _phase_injection(wf_repo, front_mode=True, sub_step_index=1)  # u:1#1 交互
    assert "活归后台工人" not in text
    assert "当前子步骤 1/7" in text  # v2 干活块照常


def test_phase_front_segment_alive_announces_no_dispatch(wf_repo):
    _write_lock(wf_repo, os.getpid())
    text = _phase_injection(wf_repo, front_mode=True, sub_step_index=2)
    assert "段在跑" in text
    assert "活归后台工人" not in text  # 不催派发（段已在跑）


def test_phase_front_held_gate_no_dispatch(wf_repo):
    text = _phase_injection(
        wf_repo,
        front_mode=True,
        phase="plan",
        sub_index=4,
        node="plan:4",
        sub_step_index=5,
        held_for_gate=True,
    )
    assert "门栏" in text
    assert "活归后台工人" not in text  # 等 /dl gate，不催派发


# ---- workflow_advance：stall 兜底 + v2 路径保留 ----


def test_advance_front_silent_when_segment_alive(wf_repo):
    _write_lock(wf_repo, os.getpid())
    rc, out = _advance_front(wf_repo, front_mode=True, sub_step_index=2)
    assert rc == 0 and out == ""
    assert _read_state(wf_repo)["sub_step_index"] == 2  # 不推进（编排归段）


def test_advance_front_stall_reprompt_then_silent(wf_repo):
    """无段在跑的非交互步：Stop 兜底重提示派发（牙齿），3 次后停轮等用户。"""
    _write_state(wf_repo, front_mode=True, sub_step_index=2)  # state 只写一次
    mod = _load(ADVANCE_HOOK, "wa_front_test")
    payload = {
        "cwd": str(wf_repo / ".claude" / "worktrees" / "t"),
        "session_id": "s",
        "transcript_path": "/nonexistent/x.jsonl",
    }
    for expect_count in (1, 2, 3):
        rc, out = _call_hook_main(mod, payload)
        assert rc == 0
        data = json.loads(out)
        ctx = data["hookSpecificOutput"]["additionalContext"]
        assert "dl_drive.py t --segment" in ctx
        assert "run_in_background" in ctx
        assert _read_state(wf_repo)["front_stall"]["count"] == expect_count
    # 第 4 次：停轮等用户（计数闸，防死循环）
    rc, out = _call_hook_main(mod, payload)
    assert rc == 0 and out == ""


def test_advance_front_silent_when_gate_held(wf_repo, monkeypatch):
    """门栏扣留（plan:4 末步=交互读回步已判过）：落 v2 路径无新 trace 静默——
    不催派发、不返工（等用户 /dl gate）。"""
    _write_state(
        wf_repo,
        front_mode=True,
        phase="plan",
        sub_index=4,
        node="plan:4",
        sub_step_index=5,
        held_for_gate=True,
    )
    # 末步已判过的现场：本步 trace 存在（过 S13），门控无新 trace 返回 none
    node = engine.get_node("plan", 4)
    ev = wf_repo / ".claude" / "evidence" / "t.jsonl"
    ev.write_text(
        json.dumps(
            {
                "kind": "skill-trace",
                "minor_stage": node.minor_key,
                "sub_step": 5,
                "payload": "x",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(engine, "gate_sub_step_at_stop", _fake_gate("none"))
    mod = _load(ADVANCE_HOOK, "wa_front_held")
    payload = {
        "cwd": str(wf_repo / ".claude" / "worktrees" / "t"),
        "session_id": "s",
        "transcript_path": "/nonexistent/x.jsonl",
    }
    rc, out = _call_hook_main(mod, payload)
    assert rc == 0 and out == ""  # 等用户 /dl gate，不催派发


def test_advance_front_interactive_step_falls_to_v2(wf_repo):
    """交互步落 v2 既有路径：零 trace 停轮 = S13 强制参与 block（一行未改）。"""
    rc, out = _advance_front(wf_repo, front_mode=True, sub_step_index=1)  # u:1#1 交互
    data = json.loads(out)
    assert "尚未执行" in data["hookSpecificOutput"]["additionalContext"]


def test_advance_front_dynamic13_falls_to_v2(wf_repo):
    """summary code 13 咬合当前位置 = 动态重分类交互：零 trace 同样吃 S13。"""
    _write_summary(wf_repo, 13)
    rc, out = _advance_front(wf_repo, front_mode=True, sub_step_index=2)
    data = json.loads(out)
    assert "尚未执行" in data["hookSpecificOutput"]["additionalContext"]


def test_advance_front_pass_continues_with_dispatch(wf_repo, monkeypatch):
    """交互步过门控后新步非交互：续轮文案 = 派发指令（非「现在立即执行子步骤 N」）。"""
    _write_state(wf_repo, front_mode=True, sub_step_index=1)
    # 给 S13 前置检查一条本步 trace（latest_trace_sha1 非 None 才进门控调用）
    ev = wf_repo / ".claude" / "evidence" / "t.jsonl"
    ev.write_text(
        json.dumps(
            {
                "kind": "skill-trace",
                "minor_stage": "ProblemContext",
                "sub_step": 1,
                "payload": "x",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        engine,
        "gate_sub_step_at_stop",
        lambda *a: ("advanced", "", {"sub_step_index": 2, "sub_index": 1}),
    )
    mod = _load(ADVANCE_HOOK, "wa_front_pass")
    payload = {
        "cwd": str(wf_repo / ".claude" / "worktrees" / "t"),
        "session_id": "s",
        "transcript_path": "/nonexistent/x.jsonl",
    }
    rc, out = _call_hook_main(mod, payload)
    data = json.loads(out)
    ctx = data["hookSpecificOutput"]["additionalContext"]
    assert "dl_drive.py t --segment" in ctx
    assert "现在立即执行" not in ctx  # v2 干活续轮文案不下发


# ---- workflow_step_fence：非交互步白名单 ----


def _fence_front(repo: Path, tool: str, tool_input: dict, **over) -> str:
    _write_state(repo, **over)
    mod = _load(FENCE_HOOK, "fence_front_test")
    _rc, out = _call_hook_main(mod, _fence_payload(repo, tool, tool_input))
    return out


def test_fence_front_whitelist_on_noninteractive_step(wf_repo):
    over = dict(front_mode=True, sub_step_index=2)
    # 放行：派发命令（逐字）/ /dl 状态管理 / 记账 / Read / AskUserQuestion
    assert "deny" not in _fence_front(
        wf_repo, "Bash", {"command": engine.front_segment_command("t")}, **over
    )
    assert "deny" not in _fence_front(
        wf_repo,
        "Bash",
        {"command": "bash ~/.dl-workflow/scripts/workflow/dl-cmd.sh status"},
        **over,
    )
    assert "deny" not in _fence_front(wf_repo, "Read", {"file_path": "/x"}, **over)
    assert "deny" not in _fence_front(
        wf_repo, "AskUserQuestion", {"questions": []}, **over
    )
    assert "deny" not in _fence_front(
        wf_repo, "TaskCreate", {"subject": "s", "description": "d"}, **over
    )
    # 拦截：干活工具（活归后台工人，前台干=上下文胀回 v2.x 病灶）
    assert "deny" in _fence_front(wf_repo, "Write", {"file_path": "/tmp/x"}, **over)
    assert "deny" in _fence_front(wf_repo, "WebFetch", {"url": "https://x"}, **over)
    assert "deny" in _fence_front(wf_repo, "Bash", {"command": "ls"}, **over)


def test_fence_front_interactive_step_keeps_v2_discipline(wf_repo):
    # 交互步零 trace 窗口：S15 照常（WebFetch deny）——front_mode 不放松交互步纪律
    out = _fence_front(
        wf_repo, "WebFetch", {"url": "https://x"}, front_mode=True, sub_step_index=1
    )
    assert "deny" in out


def test_fence_front_dynamic13_keeps_v2_discipline(wf_repo):
    # NEED_USER 重分类（code 13 咬合）→ 落 v2 路径：零 trace 窗口 S15 照常
    _write_summary(wf_repo, 13)
    out = _fence_front(
        wf_repo, "WebFetch", {"url": "https://x"}, front_mode=True, sub_step_index=2
    )
    assert "deny" in out


def test_fence_front_bare_open_with_statement_allows_dispatch(wf_repo):
    """§8 缺口修复（2026-08-12 真机实爆）：有陈述的 u:1#1 路由已翻转为派段，
    fence 判定必须同源——派发命令放行（否则模型被 S15 deny 后误读「交回本会话」
    在 TUI 自行干活）；干活工具仍拦。"""
    over = dict(front_mode=True, sub_step_index=1, problem_statement="分析X")
    assert "deny" not in _fence_front(
        wf_repo, "Bash", {"command": engine.front_segment_command("t")}, **over
    )
    assert "deny" in _fence_front(wf_repo, "Write", {"file_path": "/tmp/x"}, **over)


def test_fence_front_bare_open_no_statement_keeps_v2_discipline(wf_repo):
    """真·裸开场（无陈述）：前台亲自收陈述，派发命令仍被 S15 拦（不派段）。"""
    out = _fence_front(
        wf_repo,
        "Bash",
        {"command": engine.front_segment_command("t")},
        front_mode=True,
        sub_step_index=1,
    )
    assert "deny" in out


def test_front_interactive_work_here_single_source(wf_repo):
    """engine 单源判定两态：裸开场无陈述 / code 13 咬合 = True；有陈述 = False。"""
    st = _write_state(wf_repo, front_mode=True, sub_step_index=1)
    assert engine.front_interactive_work_here(wf_repo, "t", st) is True  # 裸开场
    st["problem_statement"] = "分析X"
    assert engine.front_interactive_work_here(wf_repo, "t", st) is False  # §8 派段
    st2 = _write_state(wf_repo, front_mode=True, sub_step_index=2)
    _write_summary(wf_repo, 13)
    assert engine.front_interactive_work_here(wf_repo, "t", st2) is True  # 13 咬合


# ---------- dl-launch.sh --front 接线（front-tui-hybrid-design §4 M3）----------


def _fake_claude_env(tmp_path: Path) -> dict:
    """PATH 前置假 claude（打印参数即退）——不起真会话验证 launcher 接线。"""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "claude"
    fake.write_text('#!/bin/bash\necho "FAKE_CLAUDE $*"\n', encoding="utf-8")
    fake.chmod(0o755)
    return dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")


def test_launcher_default_enters_tui_with_front_mode(wf_repo, tmp_path):
    """默认（无 flag）= v4 front：走 TUI 路径 + front_mode on + drive_mode off
    （2026-08-11 用户裁决默认翻转；--headless = v3 全程 driver 逃生门）。"""
    r = subprocess.run(
        [
            "bash",
            str(DLWF_ROOT / "scripts" / "workflow" / "dl-launch.sh"),
            "--workflow",
            "t",
        ],
        cwd=wf_repo,
        env=_fake_claude_env(tmp_path),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "FAKE_CLAUDE" in r.stdout  # 起 TUI（非 driver）
    assert "--session-id" in r.stdout  # TUI 钉 session（driver 路径无此参数）
    st = _read_state(wf_repo)
    assert st["front_mode"] is True
    assert st["drive_mode"] is False


def test_launcher_tui_path_clears_front_mode(wf_repo, tmp_path):
    """WF_TUI=1（v2 回滚面）：front_mode 显式 off——模式由入口唯一决定。"""
    env = _fake_claude_env(tmp_path)
    env["WF_TUI"] = "1"
    r = subprocess.run(
        [
            "bash",
            str(DLWF_ROOT / "scripts" / "workflow" / "dl-launch.sh"),
            "--workflow",
            "t",
        ],
        cwd=wf_repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "FAKE_CLAUDE" in r.stdout
    assert _read_state(wf_repo).get("front_mode") is False


def test_settings_allowlist_covers_segment_dispatch(wf_repo):
    """front 派发命令进 per-wf settings 白名单（否则模型每次派发都弹窗）+
    版本戳 = engine 单源常量（v2.35：改模板实质内容必 bump）。"""
    r = subprocess.run(
        [
            "bash",
            "-c",
            f"source {DLWF_ROOT}/scripts/workflow/dl-lib.sh && wf_write_settings t",
        ],
        cwd=wf_repo,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads((wf_repo / SEG_META / "settings.json").read_text())
    allow = data["permissions"]["allow"]
    assert "Bash(python3 ~/.dl-workflow/scripts/workflow/dl_drive.py:*)" in allow
    assert data["wf_settings_template_version"] == engine.SETTINGS_TEMPLATE_VERSION


def test_settings_allowlist_covers_project_tool_heads(wf_repo):
    """组件 B：注册项目工具 command 头并入 per-wf settings allowlist
    （codebase-archaeology-toolbox-design §3.2 action 3 / §4 row 5）——否则前台
    TUI 段调用缴 auto 权限税。破坏性/解释器头不放行（与 S15 围栏同口径）。"""
    (wf_repo / ".claude" / "workflow-tools.yaml").write_text(
        "tools:\n"
        "  - name: inspect-backtest-result\n"
        "    command: scripts/inspect_backtest_result.py --factor {factor}\n"
        "  - name: wipe\n    command: rm -rf /tmp/x\n"
        "  - name: run-sh\n    command: bash scripts/inspect.py\n",
        encoding="utf-8",
    )
    r = subprocess.run(
        [
            "bash",
            "-c",
            f"source {DLWF_ROOT}/scripts/workflow/dl-lib.sh && wf_write_settings t",
        ],
        cwd=wf_repo,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads((wf_repo / SEG_META / "settings.json").read_text())
    allow = data["permissions"]["allow"]
    # 只读发现类工具头并入
    assert "Bash(scripts/inspect_backtest_result.py:*)" in allow
    # 破坏性（rm）/解释器（bash）头不放行（与 S15 围栏同口径）
    assert "Bash(rm:*)" not in allow
    assert "Bash(bash:*)" not in allow


def test_settings_template_contains_statusline(wf_repo):
    """v4 statusLine 进度栏入 per-wf settings 模板（v4-statusline-progress-design
    §5.2）：命令烧死 --project/--name，refreshInterval=10（空闲也刷新）。"""
    r = subprocess.run(
        [
            "bash",
            "-c",
            f"source {DLWF_ROOT}/scripts/workflow/dl-lib.sh && wf_write_settings t",
        ],
        cwd=wf_repo,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads((wf_repo / SEG_META / "settings.json").read_text())
    sl = data["statusLine"]
    assert sl["type"] == "command"
    assert "dl_statusline.py" in sl["command"]
    assert f"--project {wf_repo}" in sl["command"]
    assert "--name t" in sl["command"]
    assert sl["refreshInterval"] == 10


def test_launcher_headless_flag_goes_driver(wf_repo, tmp_path):
    """--headless = v3 全程 driver：front_mode off，stdout 见 driver 接管
    （假 claude 下 TUI 段起即退、门控 none、driver 安全收场）。"""
    r = subprocess.run(
        [
            "bash",
            str(DLWF_ROOT / "scripts" / "workflow" / "dl-launch.sh"),
            "--workflow",
            "t",
            "--headless",
        ],
        cwd=wf_repo,
        env=_fake_claude_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "driver 接管工作流" in r.stdout
    st = _read_state(wf_repo)
    assert st.get("front_mode") is False
    assert st.get("drive_mode") is True


# ---------- P1-2 首调 fresh 监控（v4-cost-latency-optimization-design §2） ----------


def test_first_call_fresh_extraction():
    drv = _load(DRIVER, "drv_fresh")
    ev = {"type": "assistant", "message": {"usage": {"input_tokens": 47676}}}
    assert drv._first_call_fresh(ev) == 47676
    assert drv._first_call_fresh({"type": "assistant", "message": {}}) is None
    assert drv._first_call_fresh({"type": "assistant"}) is None
    assert drv._first_call_fresh({"message": {"usage": {"input_tokens": "x"}}}) is None


def test_fresh_warn_line_threshold():
    drv = _load(DRIVER, "drv_fresh")
    # 宁纵勿枉：无数据/未超阈值不告警
    assert drv._fresh_warn_line(None, "n") is None
    assert drv._fresh_warn_line(drv.SEG_FIRST_FRESH_WARN, "n") is None
    w = drv._fresh_warn_line(drv.SEG_FIRST_FRESH_WARN + 1, "node#子3")
    assert w is not None and "交接包" in w and "node#子3" in w


# ---------- P2-1 读回 prep 并入前序工作段（v4-cost-latency-optimization-design §2） ----------


def test_next_prep_prompt_block():
    """prep_next 注入：带下一交互步目的 + NEXT_PREP 契约；不带则无。"""
    drv = _load(DRIVER, "drv_np")
    node = engine.get_node("understand", 1)
    st = {"index": 1}
    p = drv.build_step_prompt(
        Path("/x"),
        "t",
        st,
        node,
        5,
        node.sub_steps[4],
        rework=None,
        prep_next=node.sub_steps[5],
    )
    assert "### NEXT_PREP" in p and '"questions"' in p
    assert node.sub_steps[5].purpose in p  # 下一步目的进 prompt（问题设计依据）
    assert "禁混用" in p  # NEXT_PREP 与 NEED_USER 分通道声明
    p2 = drv.build_step_prompt(
        Path("/x"), "t", st, node, 5, node.sub_steps[4], rework=None
    )
    assert "NEXT_PREP" not in p2


def test_next_prep_marker_roundtrip(wf_repo):
    """标记精确匹配才消费；不匹配不动（宁纵勿枉走原 prep 段）。"""
    drv = _load(DRIVER, "drv_np")
    _seg_write_state(wf_repo, sub_step_index=5)
    drv._mark_next_prep(wf_repo, "t", "understand:1#6")
    assert drv._consume_next_prep(wf_repo, "t", "understand:1#5") is False  # 错位不消费
    assert drv._consume_next_prep(wf_repo, "t", "understand:1#6") is True
    assert drv._consume_next_prep(wf_repo, "t", "understand:1#6") is False  # 一次性


def _gate_advancing_plan1(repo: Path):
    """plan:1 内推进假门控（P3-1 后 NEXT_PREP 仅存场景=plan:1#1→#2 方案发散）。"""

    def fake(project_root, name, cwd):
        st = _read_state(repo)
        st["sub_step_index"] = st.get("sub_step_index", 1) + 1
        (repo / SEG_META / "state.json").write_text(json.dumps(st), encoding="utf-8")
        return ("advanced", "", None)

    return fake


def test_segment_next_prep_skips_prep_session(wf_repo, monkeypatch):
    """工作段输出 NEXT_PREP → 门控通过后落标记 → 子2（decision 级交互）直接退 13。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(
        wf_repo, phase="plan", index=2, sub_index=1, node="plan:1", sub_step_index=1
    )
    next_prep_out = (
        '落库完成\n### NEXT_PREP\n```json\n{"questions": [{"question": "q"}]}\n```'
    )
    calls = _run_session_stub(drv, monkeypatch, [(0, next_prep_out, "s")])
    monkeypatch.setattr(engine, "gate_sub_step_at_stop", _gate_advancing_plan1(wf_repo))
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 13
    assert len(calls) == 1  # 只有子1 工作段，无子2 prep 段
    assert "### NEXT_PREP" in calls[0]  # prompt 带了顺带交付指令
    data = json.loads((wf_repo / SEG_META / "need_user.json").read_text())
    assert data["questions"][0]["question"] == "q"
    assert _read_state(wf_repo)["sub_step_index"] == 2


def test_segment_block_content_questions_not_stashed(wf_repo, monkeypatch):
    """被 block 的内容备的 NEXT_PREP 不落标记（门控通过才 stash）——
    防「按不合格内容备的问题」转前台。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(
        wf_repo, phase="plan", index=2, sub_index=1, node="plan:1", sub_step_index=1
    )
    next_prep_out = 'x\n### NEXT_PREP\n```json\n{"questions": [{"question": "q"}]}\n```'
    # 两轮：第一轮 block（带 NEXT_PREP），第二轮 advanced（不带）
    prep_out = 'ok\n### NEED_USER\n```json\n{"questions": [{"question": "q2"}]}\n```'
    calls = _run_session_stub(
        drv, monkeypatch, [(0, next_prep_out, "s"), (0, "", "s"), (0, prep_out, "s")]
    )
    acts = iter([("block", "缺 X", None), ("advanced", "", None)])

    def fake_gate(project_root, name, cwd):
        a = next(acts)
        if a[0] == "advanced":
            st = _read_state(wf_repo)
            st["sub_step_index"] = 2
            (wf_repo / SEG_META / "state.json").write_text(json.dumps(st))
        return a

    monkeypatch.setattr(engine, "gate_sub_step_at_stop", fake_gate)
    rc = drv.run_segment(wf_repo, "t")
    # 第二轮未输出 NEXT_PREP -> 无标记 -> 子2 走原 prep 段（第三次调用）后退 13
    assert rc == 13
    assert len(calls) == 3


# ---------- P3-1 确认级读回（v4-cost-latency-optimization-design §2 P3，2026-08-13 用户裁决） ----------


def _read_evidence_recs(repo: Path) -> list:
    p = repo / ".claude" / "evidence" / "t.jsonl"
    if not p.exists():
        return []
    return [
        json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()
    ]


def test_confirm_artifact_mapping():
    node = engine.get_node("understand", 4)
    assert engine.confirm_artifact(node) == ("understand.md", None)
    assert engine.confirm_artifact(engine.get_node("plan", 2)) == ("plan.md", None)
    assert engine.confirm_artifact(engine.get_node("plan", 3)) == ("plan.md", None)
    assert engine.confirm_artifact(engine.get_node("plan", 4)) == ("plan.md", None)
    assert engine.confirm_artifact(engine.get_node("plan", 1)) == (
        "design.md",
        "USE_WORKFLOW_NAME",
    )
    assert engine.confirm_artifact(engine.get_node("understand", 1)) is None


def test_write_confirm_trace_shape(wf_repo):
    node = engine.get_node("understand", 1)
    engine.write_confirm_trace(wf_repo, "t", node, 7)
    recs = _read_evidence_recs(wf_repo)
    assert len(recs) == 1
    r = recs[0]
    assert r["kind"] == "skill-trace" and r["sub_step"] == 7
    assert r["minor_stage"] == node.minor_key
    # user_decision_recorded 同形：q 含「读回」+ a ≥50 字（交接后可还原拍板语义）
    assert "读回" in r["q"][0] and len(r["a"][0]) >= 50
    assert "state-reset" in r["a"][0]  # 异议通道入 trace


def test_segment_confirm_readback_no_session(wf_repo, monkeypatch):
    """确认级读回（u:1#7）：不起任何模型段——机械展示+落 trace+推进，
    直通 u:2#1（decision 级）prep 退 13。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(wf_repo, sub_step_index=7)
    rb_calls = []

    def fake_rb(project_root, name):
        rb_calls.append(1)
        return True, "归一化内容展示"

    monkeypatch.setattr(engine, "render_readback", fake_rb)
    calls = _run_session_stub(
        drv,
        monkeypatch,
        [(0, 'ok\n### NEED_USER\n```json\n{"questions": []}\n```', "s")],
    )
    monkeypatch.setattr(engine, "gate_sub_step_at_stop", _gate_advancing(wf_repo))
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 13
    assert rb_calls == [1]  # 机械展示被调
    assert len(calls) == 1  # 只有 u:2#1 的 prep 段——读回步零会话
    recs = _read_evidence_recs(wf_repo)
    assert any(
        r.get("skill") == "confirm-readback" and r.get("sub_step") == 7 for r in recs
    )


def test_segment_confirm_readback_assembles_artifact(wf_repo, monkeypatch):
    """plan:2#5 确认级：render_artifact 以 plan.md 被调；装配后落 trace 推进。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(
        wf_repo, phase="plan", index=2, sub_index=2, node="plan:2", sub_step_index=5
    )
    art_calls = []

    def fake_art(project_root, name, basename, slug=None, force=False):
        art_calls.append((basename, slug))
        return True, "assembled"

    monkeypatch.setattr(engine, "render_artifact", fake_art)
    monkeypatch.setattr(engine, "render_readback", lambda *a: (True, "展示"))

    def fake_gate(project_root, name, cwd):
        st = _read_state(wf_repo)
        st.update(sub_index=3, node="plan:3", sub_step_index=1, held_for_gate=True)
        (wf_repo / SEG_META / "state.json").write_text(json.dumps(st), encoding="utf-8")
        return ("advanced", "", None)

    monkeypatch.setattr(engine, "gate_sub_step_at_stop", fake_gate)
    calls = _run_session_stub(drv, monkeypatch, [])
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 11  # 推进后撞 held_for_gate 退 11
    assert art_calls == [("plan.md", None)]
    assert calls == []  # 全程零模型会话
    recs = _read_evidence_recs(wf_repo)
    assert any(r.get("skill") == "confirm-readback" for r in recs)


# ---------- u2-sub1-cost：NEXT_PREP 跨节点 + sources 出处包 ----------
# （designs/u2-sub1-cost-optimization-design.md——u:1#6 顺带备 u:2#1，
# 灭独立 prep 段 + Q&A 会话免重读 evidence 全量）


def test_next_decision_interactive_lookahead():
    """修A lookahead：撞工作步停 / 跳 confirm 跨节点命中 / 同节点既有行为不变。"""
    # 撞非交互工作步即停（u:1#5 的下一步 u:1#6 是工作步——不抢，该段自己备）
    assert engine.next_decision_interactive_step("understand", 1, 5) is None
    # 跨 confirm 跨节点：u:1#6 →（u:1#7 confirm 跳过）→ u:2#1
    hit = engine.next_decision_interactive_step("understand", 1, 6)
    assert hit is not None
    node, no, _step = hit
    assert engine.node_id(node.phase, node.sub) == "understand:2" and no == 1
    # 同节点既有行为（plan:1#1 → plan:1#2 方案发散，P2-1 原场景）
    hit = engine.next_decision_interactive_step("plan", 1, 1)
    assert hit is not None
    assert engine.node_id(hit[0].phase, hit[0].sub) == "plan:1" and hit[1] == 2
    # u:2#4 → u:3#1（同构 confirm 挡路场景连带生效）
    hit = engine.next_decision_interactive_step("understand", 2, 4)
    assert hit is not None
    assert engine.node_id(hit[0].phase, hit[0].sub) == "understand:3" and hit[1] == 1
    # u:4#4 →（u:4#5 confirm 跳过）→ plan:1#1 是工作步 → None
    assert engine.next_decision_interactive_step("understand", 4, 4) is None
    # plan:4 末工作步 →（confirm 跳过）→ execute 无子步骤编排 → None
    assert engine.next_decision_interactive_step("plan", 4, 4) is None


def test_next_prep_prompt_block_names_target():
    """跨节点顺带交付：prompt 指名目标步 id + sources 出处包收录指引。"""
    drv = _load(DRIVER, "drv_npx")
    n1 = engine.get_node("understand", 1)
    n2 = engine.get_node("understand", 2)
    st = {"index": 1}
    p = drv.build_step_prompt(
        Path("/x"),
        "t",
        st,
        n1,
        6,
        n1.sub_steps[5],
        rework=None,
        prep_next=n2.sub_steps[0],
        prep_next_key="understand:2#1",
    )
    assert "understand:2#1" in p  # 目标步指名（跨节点不指名模型会误解给同节点）
    assert n2.sub_steps[0].purpose in p
    assert "sources" in p and "### NEXT_PREP" in p


def test_questions_contract_has_sources():
    """修B：载荷契约带 sources 出处包字段。"""
    drv = _load(DRIVER, "drv_qc")
    assert '"sources"' in drv._QUESTIONS_CONTRACT


def test_needuser_tail_sources_clause(wf_repo):
    """needuser 尾条款：sources 直接引用 + 已覆盖处禁重读 evidence 全量。"""
    drv = _load(DRIVER, "drv_nu")
    node = engine.get_node("understand", 2)
    st = _write_state(wf_repo, sub_index=2, node="understand:2", sub_step_index=1)
    (wf_repo / SEG_META / "need_user.json").write_text(
        '{"questions": [], "sources": ["用户原话：x"]}', encoding="utf-8"
    )
    p = drv.build_step_prompt(
        wf_repo,
        "t",
        st,
        node,
        1,
        node.sub_steps[0],
        rework=None,
        interactive=True,
        needuser=True,
    )
    assert "sources" in p and "evidence 全量" in p


def test_segment_next_prep_cross_node_skips_prep(wf_repo, monkeypatch):
    """修A 全链路：u:1#6 段输出 NEXT_PREP → stash key=understand:2#1 →
    u:1#7 confirm 不消费 → u:2#1 直转前台退 13（零 prep 段）。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(wf_repo, sub_step_index=6)
    monkeypatch.setattr(engine, "render_readback", lambda *a: (True, "展示"))
    out6 = (
        "落库完成\n### NEXT_PREP\n```json\n"
        '{"questions": [{"question": "q"}], "sources": ["用户原话：x"]}\n```'
    )
    calls = _run_session_stub(drv, monkeypatch, [(0, out6, "s")])
    monkeypatch.setattr(engine, "gate_sub_step_at_stop", _gate_advancing(wf_repo))
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 13
    assert len(calls) == 1  # 只有 u:1#6 一段——u:2#1 无 prep 段
    assert "understand:2#1" in calls[0]  # 顺带交付指名目标步
    data = json.loads((wf_repo / SEG_META / "need_user.json").read_text())
    assert data["questions"][0]["question"] == "q" and data["sources"]
    st = _read_state(wf_repo)
    assert st["node"] == "understand:2" and st["sub_step_index"] == 1
    assert "next_prep_stashed" not in st  # 一次性消费


def test_segment_u1_last_work_step_without_next_prep_output(wf_repo, monkeypatch):
    """u:1#6 未输出 NEXT_PREP（模型忘了）→ 无 stash → u:2#1 落回独立 prep 段
    （宁纵勿枉兜底不变）。"""
    drv = _load(DRIVER, "drv_seg")
    _seg_write_state(wf_repo, sub_step_index=6)
    monkeypatch.setattr(engine, "render_readback", lambda *a: (True, "展示"))
    prep_out = 'ok\n### NEED_USER\n```json\n{"questions": []}\n```'
    calls = _run_session_stub(
        drv, monkeypatch, [(0, "落库完成", "s"), (0, prep_out, "s")]
    )
    monkeypatch.setattr(engine, "gate_sub_step_at_stop", _gate_advancing(wf_repo))
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 13
    assert len(calls) == 2  # u:1#6 工作段 + u:2#1 独立 prep 段（现状兜底）


# ---------- ARG_MAX 修复（2026-08-12 interaction run plan:2#子5 E2BIG 实爆） ----------


class _NoCloseStringIO(io.StringIO):
    """close 后仍可 getvalue（生产侧 close 触发子进程 EOF，测试侧要回看内容）。"""

    def close(self):
        self._closed_marker = True


def test_run_session_prompt_via_stdin_not_argv(wf_repo, monkeypatch, tmp_path):
    """prompt 走 stdin（无 128KB 单参数上限），不进 argv（中文交接包放大实爆）。"""
    drv = _load(DRIVER, "drv_stdin")
    procs = []

    class _P:
        def __init__(self, cmd, **kw):
            self.cmd = cmd
            self.stdin = _NoCloseStringIO()
            self.stdout = io.StringIO(
                '{"type":"result","subtype":"success","session_id":"s1",'
                '"duration_ms":1,"num_turns":1,"total_cost_usd":0,"usage":{}}\n'
            )

        def wait(self):
            return 0

        def terminate(self):
            pass

        def kill(self):
            pass

    monkeypatch.setattr(
        drv.subprocess, "Popen", lambda cmd, **kw: procs.append(_P(cmd)) or procs[-1]
    )
    big = "交接包" * 50000  # 200k 字节级，argv 必 E2BIG 的量级
    rc, out, sid = drv.run_session(
        big,
        cwd=tmp_path,
        settings=tmp_path / "s.json",
        sys_prompt_file=tmp_path / "r.md",
        meta=tmp_path / "meta",
        debug=False,
        note="t",
    )
    assert rc == 0
    assert big not in " ".join(procs[0].cmd)  # prompt 不在 argv
    assert procs[0].stdin.getvalue() == big  # 全量走 stdin


# ---------- P2-4 段链合并（designs/segment-chain-resume-design.md） ----------
# 会话合并非派发合并：逐步派发+步间 gate 不变，仅「下一步新会话」改「--resume
# 同会话续跑」。链粒度=minor_state（node-rules system prompt 边界 + handoff
# 交接边界 + 交互/确认步天然断链）。续链不变式：白名单节点 + 链属当前节点 +
# last_step == cur-1（序列连续——state-reset/back/jump/TUI 段天然失配断链）。


def test_chain_resume_on_match(wf_repo):
    drv = _load(DRIVER, "drv_chain_match")
    state = _write_state(
        wf_repo,
        segment_chain={"node": "plan:1", "sid": "abc", "last_step": 2},
    )
    assert drv._chain_resume_sid(state, "plan:1", 3) == "abc"


def test_chain_resume_rejects_non_whitelist_node(wf_repo):
    """白名单外节点不续链（execute/review/evolution 无编排不重开；空名单=全局关（回滚面））。"""
    drv = _load(DRIVER, "drv_chain_wl")
    state = _write_state(
        wf_repo,
        segment_chain={"node": "execute:0", "sid": "abc", "last_step": 1},
    )
    assert drv._chain_resume_sid(state, "execute:0", 2) is None


def test_chain_resume_understand1_rolled_back(wf_repo):
    """2026-08-17 回滚（designs/u1-sub4-cost-optimization-design.md 修 3）：
    执行 2026-08-14 裁决的预授权回滚条件——amplitude_annualized D 轮链峰值
    324k > 250k 护栏 + deepseek 跨进程 resume 前缀缓存时灵时不灵
    （D 轮链内 step2→5 首调 fresh 44k→109k→166k→241k 全冷），
    u:1 移出 SEGMENT_CHAIN_NODES。
    2026-08-18 断链 u:2（designs/u2-sub3-cost-optimization-design.md，
    用户裁决覆盖 08-17「峰值未破保留」项）：u2_sub1_ab/u2_sub2_ab 两轮实测
    u:2#3/#4 段首调 cache_read=0——deepseek 会话隔离缓存下链恒冷=纯增税
    （#3 冷启动 60.3k=本步 fresh 73%、#4 94.1k=98%），fresh 段恒定 ~45k。
    u:2 移出 SEGMENT_CHAIN_NODES（u:3/4 与 plan 族保留——u:3/u:4 后续分别
    于 08-18/08-19 断链，见各自测试）。"""
    drv = _load(DRIVER, "drv_chain_u1")
    state = _write_state(
        wf_repo,
        segment_chain={"node": "understand:1", "sid": "abc", "last_step": 2},
    )
    assert drv._chain_resume_sid(state, "understand:1", 3) is None
    state2 = _write_state(
        wf_repo,
        segment_chain={"node": "understand:2", "sid": "abc", "last_step": 2},
    )
    assert drv._chain_resume_sid(state2, "understand:2", 3) is None


def test_chain_resume_understand3_broken(wf_repo):
    """2026-08-18 u:3 断链（designs/u3-sub2-cost-optimization-design.md §6）：
    u3_sub1_ab2 实测链税 #3 首调 71,862(cr=0)+#4 首调 106,780(cr=1,792)=178.6k
    纯增税；两轮 live A/B 实测段内续步边界暖率仅 1/4（deepseek 逐出激进），
    续步冷=全额重写继承 transcript（65-122k），EV 不如 fresh 段恒定地板
    （~28-31k/步）——u:3 移出 SEGMENT_CHAIN_NODES 且不入 MERGED_RUN_NODES
    （understand:4 与 plan 族保留 surgical——u:4 后于 08-19 断链，见下）。"""
    drv = _load(DRIVER, "drv_chain_u3")
    state = _write_state(
        wf_repo,
        segment_chain={"node": "understand:3", "sid": "abc", "last_step": 2},
    )
    assert drv._chain_resume_sid(state, "understand:3", 3) is None


def test_whitelist_u3_neither_chain_nor_merged():
    """u:3 断链归属（同 u3-sub2-cost 设计 §6）：CHAIN/MERGED 两名单都不含
    u:3（每步 fresh 段=断链语义）；两名单交集恒空（merged 路径不走
    _chain_resume_sid/_chain_update）。"""
    assert "understand:3" not in engine.SEGMENT_CHAIN_NODES
    assert "understand:3" not in engine.MERGED_RUN_NODES
    assert engine.SEGMENT_CHAIN_NODES.isdisjoint(engine.MERGED_RUN_NODES)


def test_chain_resume_understand4_broken(wf_repo):
    """2026-08-19 u:4 断链（designs/u4-sub3-cost-optimization-design.md L1，
    用户降本指令覆盖「峰值未破保留」防爆默认）：u4_sub2_ab B 轮实测 u:4#3
    首调 44,747(cr=0)+#4 首调 74,227(cr=512≈冷)=118,974 纯增税——deepseek
    会话隔离缓存下链恒冷（cost-optimization #20 三要素全中）；各步输入契约
    经交接包逐字段核对完备（#2←SC#1/#3←SC#2/#4←SC#3 trace 全文在包）。
    u:4 移出 SEGMENT_CHAIN_NODES 且不入 MERGED_RUN_NODES（步体非极小搬运型
    +续步暖率彩票 EV 两节点证伪，#24 口径）；plan 族保留（surgical，
    无降本指令）。"""
    drv = _load(DRIVER, "drv_chain_u4")
    state = _write_state(
        wf_repo,
        segment_chain={"node": "understand:4", "sid": "abc", "last_step": 2},
    )
    assert drv._chain_resume_sid(state, "understand:4", 3) is None


def test_whitelist_u4_neither_chain_nor_merged():
    """u:4 断链归属（同 u4-sub3-cost 设计 L1）：CHAIN/MERGED 两名单都不含
    u:4（每步 fresh 段=断链语义，u:3 同型）。"""
    assert "understand:4" not in engine.SEGMENT_CHAIN_NODES
    assert "understand:4" not in engine.MERGED_RUN_NODES
    assert engine.SEGMENT_CHAIN_NODES.isdisjoint(engine.MERGED_RUN_NODES)


def test_chain_resume_plan_nodes_whitelisted(wf_repo):
    """2026-08-13 扩面（试点护栏达标：22/22 一次过+链峰值<250k+零兜底）：
    plan:1-4 全族续链；plan:1 子2 交互步由 last_step 不变式天然断链。"""
    drv = _load(DRIVER, "drv_chain_plan")
    for nid in ("plan:1", "plan:2", "plan:3", "plan:4"):
        state = _write_state(
            wf_repo,
            segment_chain={"node": nid, "sid": f"s-{nid}", "last_step": 2},
        )
        assert drv._chain_resume_sid(state, nid, 3) == f"s-{nid}"


def test_chain_resume_rejects_step_gap(wf_repo):
    """last_step != cur-1 = 序列断（state-reset/back/jump/step-pass/TUI 段后）。"""
    drv = _load(DRIVER, "drv_chain_gap")
    state = _write_state(
        wf_repo,
        segment_chain={"node": "understand:3", "sid": "abc", "last_step": 4},
    )
    assert drv._chain_resume_sid(state, "understand:3", 3) is None


def test_chain_resume_rejects_node_mismatch(wf_repo):
    """跨节点不续链：node-rules system prompt 变 = 前缀缓存失效边界。"""
    drv = _load(DRIVER, "drv_chain_node")
    state = _write_state(
        wf_repo,
        segment_chain={"node": "plan:1", "sid": "abc", "last_step": 4},
    )
    assert drv._chain_resume_sid(state, "plan:2", 2) is None


def test_chain_resume_no_chain(wf_repo):
    drv = _load(DRIVER, "drv_chain_none")
    state = _write_state(wf_repo)
    assert drv._chain_resume_sid(state, "understand:3", 2) is None


def test_chain_update_on_whitelisted_node(wf_repo):
    drv = _load(DRIVER, "drv_chain_upd")
    _write_state(wf_repo)
    drv._chain_update(wf_repo, "t", "plan:1", 2, "sid-x")
    chain = _read_state(wf_repo)["segment_chain"]
    assert chain["node"] == "plan:1"
    assert chain["sid"] == "sid-x"
    assert chain["last_step"] == 2
    assert chain["ts"]


def test_chain_update_clears_on_non_whitelist_node(wf_repo):
    """推进出白名单节点 = 链作废（防陈旧链残留误导后续审计）。"""
    drv = _load(DRIVER, "drv_chain_upd2")
    _write_state(
        wf_repo,
        segment_chain={"node": "understand:2", "sid": "abc", "last_step": 4},
    )
    drv._chain_update(wf_repo, "t", "execute:0", 1, "sid-y")
    assert "segment_chain" not in _read_state(wf_repo)


def test_chain_clear(wf_repo):
    """显式断链（RC_INTERRUPTED 杀中段——transcript 尾可能半个 turn）。"""
    drv = _load(DRIVER, "drv_chain_clr")
    _write_state(
        wf_repo,
        segment_chain={"node": "understand:2", "sid": "abc", "last_step": 2},
    )
    drv._chain_clear(wf_repo, "t")
    assert "segment_chain" not in _read_state(wf_repo)


def test_run_session_resume_flag_replaces_session_id(wf_repo, monkeypatch):
    """--resume 与 --session-id 互斥：续链走 --resume，返回 sid = 链 sid。"""
    drv = _load(DRIVER, "drv_chain_rs")
    captured = {}

    class _FakeProc:
        stdout = iter([])
        stdin = io.StringIO()

        def wait(self):
            return 0

        def terminate(self):
            pass

        def kill(self):
            pass

    def fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr(drv.subprocess, "Popen", fake_popen)
    meta = wf_repo / SEG_META
    rc, _out, sid = drv.run_session(
        "提示词正文",
        cwd=wf_repo,
        settings=meta / "settings.json",
        sys_prompt_file=meta / "rules.md",
        meta=meta,
        debug=False,
        note="t",
        resume_sid="chain-sid-1",
    )
    cmd = captured["cmd"]
    assert cmd[cmd.index("--resume") + 1] == "chain-sid-1"
    assert "--session-id" not in cmd
    assert sid == "chain-sid-1"
    assert rc == 0


def test_run_session_fresh_uses_session_id_no_resume(wf_repo, monkeypatch):
    """现状不回归：无 resume_sid 走 --session-id 新会话，cmd 无 --resume。"""
    drv = _load(DRIVER, "drv_chain_fresh")
    captured = {}

    class _FakeProc:
        stdout = iter([])
        stdin = io.StringIO()

        def wait(self):
            return 0

        def terminate(self):
            pass

        def kill(self):
            pass

    def fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr(drv.subprocess, "Popen", fake_popen)
    meta = wf_repo / SEG_META
    _rc, _out, sid = drv.run_session(
        "提示词正文",
        cwd=wf_repo,
        settings=meta / "settings.json",
        sys_prompt_file=meta / "rules.md",
        meta=meta,
        debug=False,
        note="t",
    )
    cmd = captured["cmd"]
    assert "--resume" not in cmd
    assert cmd[cmd.index("--session-id") + 1] == sid


def test_chain_context_warn_line(wf_repo):
    """链上下文峰值监控（宁纵勿枉只告警）：超 250k 出告警行，未超/None 静默。"""
    drv = _load(DRIVER, "drv_chain_warn")
    assert drv._chain_warn_line(None, "n") is None
    assert drv._chain_warn_line(100_000, "n") is None
    line = drv._chain_warn_line(300_000, "u:2#3")
    assert "300,000" in line and "u:2#3" in line


def test_node_rules_injects_discovery_ledger_hint(wf_repo):
    """ensure_node_rules 含「发现台账」提示（工具级去重告知）。"""
    drv = _load(DRIVER, "drv_under_test")
    node = engine.get_node("understand", 1)
    out = drv.ensure_node_rules(wf_repo, "t", node, 1)
    text = out.read_text(encoding="utf-8")
    assert "## 发现台账" in text
    assert "discoveries.jsonl" in text


def test_node_rules_has_arch_route(wf_repo):
    """understand:1 子3（因果链挖掘）的通用取证路线（trace/string/history/Read）
    随当前步 purpose 逐字进段 prompt（O2 后 node-rules 只留 titles——
    取证路线的可见面从 rules 清单迁到段 prompt 的「目的」行，契约在此钉死）。"""
    drv = _load(DRIVER, "drv_under_test")
    node = engine.get_node("understand", 1)
    step = node.sub_steps[2]
    prompt = drv.build_step_prompt(
        wf_repo, "t", {"index": 1}, node, 3, step, rework=None
    )
    assert "dl-cmd.sh codebase trace" in prompt
    assert "取证路线" in prompt


# ---------- u1-sub5-cost 修3：红队 driver 预派发 ----------


class _FakeRTProc:
    """预派发 Popen 假身：记录 stdin，pid 固定（不真起 claude）。"""

    class _RecStdin:
        def __init__(self):
            self.buf = ""
            self.saved = ""

        def write(self, s):
            self.buf += s

        def close(self):
            self.saved = self.buf

    def __init__(self, cmd, **kw):
        self.cmd = cmd
        self.kw = kw
        self.pid = 888001
        self.stdin = self._RecStdin()


def _rt_step(pre_dispatch="redteam"):
    return engine.Step(
        kind="skill",
        ref="causal-inference-root-cause",
        short="质检裁决",
        purpose="p",
        input=None,
        record=True,
        gate=None,
        pre_dispatch=pre_dispatch,
    )


class TestRedteamPreDispatch:
    """driver 在 pre_dispatch=redteam 步派段前预起红队 worker（与子5 主会话并行）。

    实证（u1-sub5-cost-optimization-design §1）：红队子代理跑 158-235s，主会话
    有效利用 ≤1min（轮2 零并行干等 2.7min）——红队输入只依赖 ≤子4 trace，
    子4 gate 一过即具备派发条件。新鲜度按 prompt_sha1（state-reset 后子4
    证据变 → 旧报告作废重派）。
    """

    def _call(self, drv, wf_repo, monkeypatch, *, prompt="PROMPT", step=None):
        monkeypatch.setattr(drv.engine, "redteam_prompt", lambda *a, **k: prompt)
        spawned = []

        def _fake_popen(cmd, **kw):
            proc = _FakeRTProc(cmd, **kw)
            spawned.append(proc)
            return proc

        monkeypatch.setattr(drv.subprocess, "Popen", _fake_popen)
        meta = wf_repo / ".claude" / "workflows" / "t"
        wt = wf_repo / ".claude" / "worktrees" / "t"
        drv._maybe_predispatch_redteam(
            wf_repo,
            "t",
            step if step is not None else _rt_step(),
            wt=wt,
            settings=meta / "settings.drive.json",
            meta=meta,
        )
        return spawned, meta

    def test_spawn_on_predispatch_step(self, wf_repo, monkeypatch):
        drv = _load(DRIVER, "drv_rt_pd")
        spawned, meta = self._call(drv, wf_repo, monkeypatch)
        assert len(spawned) == 1
        proc = spawned[0]
        cmd = proc.cmd
        assert cmd[:2] == ["claude", "-p"]
        assert cmd[cmd.index("--tools") + 1] == "Read"
        # result-JSON 输出（ANTHROPIC_LOG 污染下末行可解析，judge 同款）
        assert cmd[cmd.index("--output-format") + 1] == "json"
        assert "--session-id" in cmd
        assert proc.kw.get("start_new_session") is True
        # prompt 走 stdin（E2BIG 纪律）；报告落 meta/redteam_report.md
        assert proc.stdin.saved == "PROMPT"
        wj = json.loads((meta / "redteam_worker.json").read_text())
        assert wj["pid"] == 888001 and wj["prompt_sha1"]

    def test_spawn_env_passthrough(self, wf_repo, monkeypatch):
        # u1-prefix-strip：spawn_env 覆盖进 worker Popen env（段前缀剥离
        # 同步到红队预派发——Read-only worker 零 CLAUDE.md 依赖）。
        drv = _load(DRIVER, "drv_rt_env")
        monkeypatch.setattr(drv.engine, "redteam_prompt", lambda *a, **k: "PROMPT")
        spawned = []

        def _fake_popen(cmd, **kw):
            proc = _FakeRTProc(cmd, **kw)
            spawned.append(proc)
            return proc

        monkeypatch.setattr(drv.subprocess, "Popen", _fake_popen)
        meta = wf_repo / ".claude" / "workflows" / "t"
        drv._maybe_predispatch_redteam(
            wf_repo,
            "t",
            _rt_step(),
            wt=wf_repo / ".claude" / "worktrees" / "t",
            settings=meta / "settings.drive.json",
            meta=meta,
            spawn_env={"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"},
        )
        assert spawned[0].kw["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"

    def test_skip_non_predispatch_step(self, wf_repo, monkeypatch):
        drv = _load(DRIVER, "drv_rt_pd")
        spawned, _ = self._call(drv, wf_repo, monkeypatch, step=_rt_step(""))
        assert spawned == []

    def test_skip_when_prompt_none(self, wf_repo, monkeypatch):
        # 无子4 trace（redteam_prompt=None）→ 不派，ingest 侧 fail loud 指路
        drv = _load(DRIVER, "drv_rt_pd")
        spawned, meta = self._call(drv, wf_repo, monkeypatch, prompt=None)
        assert spawned == []
        assert not (meta / "redteam_worker.json").exists()

    def test_no_respawn_when_running(self, wf_repo, monkeypatch):
        # sha 相同 + pid 活（本进程）→ 复用不重派
        drv = _load(DRIVER, "drv_rt_pd")
        spawned, meta = self._call(drv, wf_repo, monkeypatch)
        assert len(spawned) == 1
        import hashlib

        (meta / "redteam_worker.json").write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "started_at": "x",
                    "prompt_sha1": hashlib.sha1(b"PROMPT").hexdigest(),
                }
            )
        )
        spawned2, _ = self._call(drv, wf_repo, monkeypatch)
        assert spawned2 == []

    def test_no_respawn_when_report_ready(self, wf_repo, monkeypatch):
        # sha 相同 + 报告已非空（worker 已完工）→ 复用不重派
        drv = _load(DRIVER, "drv_rt_pd")
        spawned, meta = self._call(drv, wf_repo, monkeypatch)
        assert len(spawned) == 1
        import hashlib

        (meta / "redteam_worker.json").write_text(
            json.dumps(
                {
                    "pid": 99999944,
                    "started_at": "x",
                    "prompt_sha1": hashlib.sha1(b"PROMPT").hexdigest(),
                }
            )
        )
        (meta / "redteam_report.md").write_text("报告", encoding="utf-8")
        spawned2, _ = self._call(drv, wf_repo, monkeypatch)
        assert spawned2 == []

    def test_respawn_on_stale_sha(self, wf_repo, monkeypatch):
        # state-reset 后子4 证据变 → prompt sha 变 → 旧报告作废重派
        drv = _load(DRIVER, "drv_rt_pd")
        spawned, meta = self._call(drv, wf_repo, monkeypatch)
        assert len(spawned) == 1
        wj = json.loads((meta / "redteam_worker.json").read_text())
        assert wj["prompt_sha1"]
        wj["prompt_sha1"] = "stale-sha"
        wj["pid"] = 99999944  # 已死
        (meta / "redteam_worker.json").write_text(json.dumps(wj))
        spawned2, meta = self._call(drv, wf_repo, monkeypatch)
        assert len(spawned2) == 1
        wj2 = json.loads((meta / "redteam_worker.json").read_text())
        assert wj2["prompt_sha1"] != "stale-sha"


# ---------- u1-overall-cost O1/O2（designs/u1-overall-cost-optimization-design.md）----------


class _FakeSegProc:
    """run_session Popen 假身：记录 stdin/cmd，喂一行 result 事件即完工。"""

    def __init__(self, cmd, **kw):
        self.cmd = cmd
        self.kw = kw
        self.pid = 888002
        self.stdin = _FakeRTProc._RecStdin()
        self.stdout = iter(
            [
                '{"type":"result","subtype":"success","duration_ms":1000,'
                '"total_cost_usd":0.01,"num_turns":1}\n'
            ]
        )

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        pass

    def kill(self):
        pass


def test_run_session_disables_mcp(wf_repo, monkeypatch):
    """O1：段会话禁 MCP——编排全程禁 tavily（子4 purpose 明文），MCP schema
    （探针实测 2,504 tok/调用前缀）是纯税；--tools 限不住 MCP（红队经 MCP 调
    tavily_extract 实证）——strict-mcp-config + 空表 = 结构封死。"""
    drv = _load(DRIVER, "drv_no_mcp")
    spawned = []

    def _fake_popen(cmd, **kw):
        proc = _FakeSegProc(cmd, **kw)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(drv.subprocess, "Popen", _fake_popen)
    meta = wf_repo / ".claude" / "workflows" / "t"
    meta.mkdir(parents=True, exist_ok=True)
    settings = meta / "settings.drive.json"
    settings.write_text("{}", encoding="utf-8")
    rules = meta / "node-rules.md"
    rules.write_text("r", encoding="utf-8")
    rc, _out, _sid = drv.run_session(
        "PROMPT",
        cwd=wf_repo,
        settings=settings,
        sys_prompt_file=rules,
        meta=meta,
        debug=False,
        note="t#1",
    )
    assert rc == 0
    cmd = spawned[0].cmd
    assert "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--mcp-config") + 1] == '{"mcpServers":{}}'


def test_tui_cmd_disables_mcp(wf_repo):
    """O1：TUI 交互段同一税同一封法；prompt 位置参数仍在末尾（旗标顺序纪律）。"""
    drv = _load(DRIVER, "drv_no_mcp_tui")
    meta = wf_repo / ".claude" / "workflows" / "t"
    cmd = drv._build_tui_cmd("sid", Path("s"), Path("r"), "PROMPT", False, meta)
    assert "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--mcp-config") + 1] == '{"mcpServers":{}}'
    assert cmd[-1] == "PROMPT"
    # variadic --mcp-config 与位置参数 prompt 之间必须有 `--`，否则吞参
    assert cmd.index("--") > cmd.index("--mcp-config")


def test_tui_cmd_tools_before_no_mcp(tmp_path):
    """u3-sub1-cost：TUI 段 --tools 白名单须在 NO_MCP_ARGS 之前（--mcp-config
    variadic 吞尾随位置参数——同 `--` 修复的排序纪律）。"""
    drv = _load(DRIVER, "drv_tui_tools")
    cmd = drv._build_tui_cmd(
        "sid",
        Path("s"),
        Path("r"),
        "PROMPT",
        False,
        tmp_path,
        tools=("Bash", "Read", "AskUserQuestion"),
    )
    assert cmd[cmd.index("--tools") + 1] == "Bash,Read,AskUserQuestion"
    assert cmd.index("--tools") < cmd.index("--mcp-config")
    assert cmd[-2] == "--" and cmd[-1] == "PROMPT"
    # None = 全量工具（未置位节点零行为变化）
    cmd2 = drv._build_tui_cmd("sid", Path("s"), Path("r"), None, False, tmp_path)
    assert "--tools" not in cmd2


def test_tui_step_tools_constant():
    """TUI 交互三件套：问答卡片 + 开场纪律清单（v3.3.1）是交互段结构职能。"""
    drv = _load(DRIVER, "drv_tui_const")
    assert drv._TUI_STEP_TOOLS == ("AskUserQuestion", "TaskCreate", "TaskUpdate")


def test_questions_contract_sources_ledger_category():
    """u3-sub1-cost 修2：sources 合同扩类目——发现台账结构锚点合法化
    （框架级措辞，禁为凑数扩大收录面的刹车条款同驻）。"""
    drv = _load(DRIVER, "drv_contract")
    c = drv._QUESTIONS_CONTRACT
    assert "discoveries.jsonl" in c
    assert "结构锚点" in c
    assert "禁为凑数" in c


def test_node_rules_brief_titles_only(wf_repo):
    """O2：node-rules 清单 titles-only + 当前步标注；当前步完整目的由段 prompt
    逐字携带（双通道契约在此钉死）。瘦身前 node-rules.understand:1.md 实测
    25,005 字符（7 步 purpose 清单 ~15k 是每调用重付的死重）。"""
    drv = _load(DRIVER, "drv_brief")
    node = engine.get_node("understand", 1)
    text = drv.ensure_node_rules(wf_repo, "t", node, 3).read_text(encoding="utf-8")
    for short in (
        "逼问定义",
        "规划拆解",
        "因果链挖掘",
        "双向取证",
        "质检裁决",
        "归一化陈述",
        "读回确认",
    ):
        assert short in text
    assert "当前步" in text
    # 任何步 purpose 全文都不在 rules（当前步的在段 prompt——下方钉死）
    assert "占环位" not in text
    assert "权威源注册表" not in text
    assert "去上下文" not in text
    assert len(text) < 9000  # 瘦身硬阈值（25,005 -> <9k）
    # 双通道契约：段 prompt 逐字携带当前步完整目的
    step = node.sub_steps[2]
    prompt = drv.build_step_prompt(
        wf_repo, "t", {"index": 1}, node, 3, step, rework=None
    )
    assert step.purpose in prompt


def test_node_rules_aq_injection_consumer_steps_only(wf_repo):
    """O2 连带：atomic_questions 注入收窄到消费步（子2b/子4 = cur 3/4）——
    子5+ 的 claim/tier 上下文已在包内 trace 全文，注入是重复税。"""
    drv = _load(DRIVER, "drv_aq_gate")
    ev = wf_repo / ".claude" / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    rec = {
        "kind": "skill-trace",
        "major_stage": "Understand",
        "minor_stage": "ProblemContext",
        "sub_step": 2,
        "skill": "s",
        "purpose": "p",
        "q": ["q"],
        "a": ["a"],
        "atomic_questions": [
            {"q": "原子A", "tier": "none", "tier_reason": "仓内 paths.py:1"}
        ],
    }
    (ev / "t.jsonl").write_text(
        json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    node = engine.get_node("understand", 1)
    t3 = drv.ensure_node_rules(wf_repo, "t", node, 3).read_text(encoding="utf-8")
    t4 = drv.ensure_node_rules(wf_repo, "t", node, 4).read_text(encoding="utf-8")
    t5 = drv.ensure_node_rules(wf_repo, "t", node, 5).read_text(encoding="utf-8")
    assert "原子A" in t3
    assert "原子A" in t4
    assert "原子A" not in t5


class TestRedteamPreDispatchNoMcp:
    """O1 连带：红队预派发 worker 禁 MCP——「Read 为主」纪律从文案升结构
    （--tools Read 只限内置工具，worker 经 MCP 调 tavily_extract 两次实证）。"""

    def test_predispatch_cmd_disables_mcp(self, wf_repo, monkeypatch):
        drv = _load(DRIVER, "drv_rt_pd_nomcp")
        helper = TestRedteamPreDispatch()
        spawned, _meta = helper._call(drv, wf_repo, monkeypatch)
        cmd = spawned[0].cmd
        assert "--strict-mcp-config" in cmd
        assert cmd[cmd.index("--mcp-config") + 1] == '{"mcpServers":{}}'


# ---------- 段内续步（u2-sub4-cost §3：MERGED_RUN_NODES 白名单节点同进程多轮 stream-json） ----------


class _FakeMergedSession:
    """脚本化 MergedSession 替身：turns = [(text, info), ...]，捕获 send 序列。"""

    def __init__(self, turns):
        self._turns = list(turns)
        self.sends: list[str] = []
        self.sid = "merged-s"
        self.alive = True
        self.last_ctx = None
        self.rc = 0
        self.closed = False

    def send(self, prompt: str) -> None:
        self.sends.append(prompt)

    def read_turn(self):
        text, info = self._turns.pop(0)
        self.last_ctx = (info or {}).get("last_ctx", self.last_ctx)
        return text, (info or {})

    def close(self) -> int:
        self.closed = True
        return 0


def _merged_stub(drv, monkeypatch, turns_list) -> list:
    """MergedSession 替身工厂：每次 spawn 取下一组脚本 turns，收集全部实例。"""

    instances = []
    it = iter(turns_list)

    def factory(**kw):
        inst = _FakeMergedSession(next(it))
        instances.append(inst)
        return inst

    monkeypatch.setattr(drv, "MergedSession", factory)
    return instances


def _gate_scripted(repo: Path, actions):
    """假门控：按序返回 action；advanced 真实推进 state（u:2 #2→…→#5→u:3#1）。"""

    it = iter(actions)

    def fake(project_root, name, cwd):
        act = next(it)
        if act[0] == "advanced":
            st = _read_state(repo)
            cur = st.get("sub_step_index", 1)
            if st["sub_index"] == 2:
                if cur < 5:
                    st["sub_step_index"] = cur + 1
                else:
                    st.update(sub_index=3, node="understand:3", sub_step_index=1)
            (repo / SEG_META / "state.json").write_text(
                json.dumps(st), encoding="utf-8"
            )
            return ("advanced", "", None)
        return (act[0], act[1] if len(act) > 1 else "", None)

    return fake


_NEED_OUT = 'q\n### NEED_USER\n```json\n{"questions": []}\n```'


def test_merged_run_single_session_covers_u2_sub2_to_sub4(wf_repo, monkeypatch):
    """段内续步主路径：u:2#2 起跑——#2/#3/#4 同一 MergedSession 续跑（#2 全量
    prompt 带交接包；#3/#4 续步 prompt 剥交接包、带「同会话续步」头），#4 附带交付
    （NEXT_PREP u:3#1）照常落 stash；撞 #5（confirm 级交互）收段——主循环接管：
    确认级机械过后 u:3#1 消费已备问题清单直接转前台（退 13，零 prep 段）。"""
    drv = _load(DRIVER, "drv_merged_main")
    _seg_write_state(wf_repo, sub_index=2, node="understand:2", sub_step_index=2)
    next_prep_out = (
        "子4 完成\n### NEXT_PREP\n```json\n"
        '{"questions": [{"question": "q-u3", "header": "h", "multiSelect": false,'
        ' "options": []}]}\n```'
    )
    insts = _merged_stub(
        drv,
        monkeypatch,
        [[("子2 完成", {}), ("子3 完成", {}), (next_prep_out, {})]],
    )
    monkeypatch.setattr(
        drv.engine,
        "gate_sub_step_at_stop",
        _gate_scripted(
            wf_repo, [("advanced",), ("advanced",), ("advanced",), ("advanced",)]
        ),
    )
    calls = _run_session_stub(drv, monkeypatch, [])
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 13
    assert len(insts) == 1  # 单进程覆盖 #2-#4
    sess = insts[0]
    assert sess.closed
    assert len(sess.sends) == 3
    assert "交接包" in sess.sends[0]
    assert (
        "同会话续步" in sess.sends[1]
        and "## WORKFLOW 上下文交接包" not in sess.sends[1]
    )
    assert (
        "同会话续步" in sess.sends[2]
        and "## WORKFLOW 上下文交接包" not in sess.sends[2]
    )
    assert "附带交付" in sess.sends[2]
    assert calls == []  # prep_done 消费 stash——零 prep 段
    data = json.loads((wf_repo / SEG_META / "need_user.json").read_text())
    assert data["questions"][0]["question"] == "q-u3"


def test_merged_run_block_reworks_in_session(wf_repo, monkeypatch):
    """门控 block → 同会话暖返工（不起新进程、不重付冷启动）：续步 prompt 带返工判词。"""
    drv = _load(DRIVER, "drv_merged_block")
    _seg_write_state(wf_repo, sub_index=2, node="understand:2", sub_step_index=3)
    insts = _merged_stub(
        drv,
        monkeypatch,
        [[("子3 缺陷产出", {}), ("子3 返工完成", {}), ("子4 完成", {})]],
    )
    monkeypatch.setattr(
        drv.engine,
        "gate_sub_step_at_stop",
        _gate_scripted(
            wf_repo,
            [("block", "矩阵放水"), ("advanced",), ("advanced",), ("advanced",)],
        ),
    )
    _run_session_stub(drv, monkeypatch, [(0, _NEED_OUT, "s2")])
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 13
    assert len(insts) == 1
    sends = insts[0].sends
    assert len(sends) == 3
    assert "返工" in sends[1] and "矩阵放水" in sends[1]
    assert "同会话续步" in sends[2]


def test_merged_run_escalate_closes_and_breakpoints(wf_repo, monkeypatch):
    """连续 block 达阈值（escalate）→ 收段 + 断点（--segment 退 12）。"""
    drv = _load(DRIVER, "drv_merged_esc")
    _seg_write_state(wf_repo, sub_index=2, node="understand:2", sub_step_index=3)
    insts = _merged_stub(drv, monkeypatch, [[("缺陷产出", {})]])
    monkeypatch.setattr(
        drv.engine,
        "gate_sub_step_at_stop",
        _gate_scripted(wf_repo, [("escalate", "连续 block")]),
    )
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 12
    assert insts[0].closed


def test_merged_run_none_nudges_in_session_then_breakpoint(wf_repo, monkeypatch):
    """门控读不到新 trace（none）→ 会话内 nudge（≤NONE_RETRY_LIMIT）仍无 →
    收段断点（退 12）。"""
    drv = _load(DRIVER, "drv_merged_none")
    _seg_write_state(wf_repo, sub_index=2, node="understand:2", sub_step_index=3)
    insts = _merged_stub(
        drv,
        monkeypatch,
        [[("没落库", {})] * drv.NONE_RETRY_LIMIT],
    )
    monkeypatch.setattr(
        drv.engine,
        "gate_sub_step_at_stop",
        _gate_scripted(wf_repo, [("none",)] * drv.NONE_RETRY_LIMIT),
    )
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 12
    sess = insts[0]
    assert sess.closed
    assert len(sess.sends) == drv.NONE_RETRY_LIMIT  # 1 head + 2 nudge
    assert "落库" in sess.sends[1]


def test_merged_run_ctx_guard_breaks_run(wf_repo, monkeypatch):
    """上下文破 250k（链峰值同阈值 CHAIN_CONTEXT_WARN）→ 收段降级：下一步
    新起段（第二次 spawn，全量 prompt 带交接包）。"""
    drv = _load(DRIVER, "drv_merged_ctx")
    _seg_write_state(wf_repo, sub_index=2, node="understand:2", sub_step_index=2)
    insts = _merged_stub(
        drv,
        monkeypatch,
        [
            [("子2 完成", {"last_ctx": 300_000})],
            [("子3 完成", {}), ("子4 完成", {})],
        ],
    )
    monkeypatch.setattr(
        drv.engine,
        "gate_sub_step_at_stop",
        _gate_scripted(
            wf_repo,
            [("advanced",), ("advanced",), ("advanced",), ("advanced",)],
        ),
    )
    _run_session_stub(drv, monkeypatch, [(0, _NEED_OUT, "s3")])
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 13
    assert len(insts) == 2
    assert len(insts[0].sends) == 1  # #2 一轮后破线收段
    assert insts[0].closed
    assert len(insts[1].sends) == 2  # 第二段覆盖 #3/#4
    assert "同会话续步" not in insts[1].sends[0]  # fresh 段全量 prompt（含交接包通道）
    assert "同会话续步" in insts[1].sends[1]


def test_merged_run_need_user_falls_back_to_tui(wf_repo, monkeypatch):
    """段内模型非预期要用户输入（### NEED_USER）→ 收段 + 动态交互 fallback
    （--segment 退 13）。"""
    drv = _load(DRIVER, "drv_merged_nu")
    _seg_write_state(wf_repo, sub_index=2, node="understand:2", sub_step_index=3)
    insts = _merged_stub(drv, monkeypatch, [[("需要用户\n### NEED_USER\nq", {})]])
    rc = drv.run_segment(wf_repo, "t")
    assert rc == 13
    assert insts[0].closed


def test_merged_run_whitelist_excludes_other_nodes(wf_repo, monkeypatch):
    """白名单外节点（u:1）非交互步维持每步独立段（run_session 通道）——
    MergedSession 不 spawn。"""
    drv = _load(DRIVER, "drv_merged_wl")
    _seg_write_state(wf_repo, sub_step_index=2)  # u:1#2 非交互

    def boom(**kw):
        raise AssertionError("MergedSession 不应 spawn（白名单外）")

    monkeypatch.setattr(drv, "MergedSession", boom)
    monkeypatch.setattr(drv.engine, "gate_sub_step_at_stop", _gate_advancing(wf_repo))
    calls = _run_session_stub(drv, monkeypatch, [(0, "", "s")] * 20)
    rc = drv.run_segment(wf_repo, "t")
    assert rc in (10, 12, 13)
    assert len(calls) >= 2  # 多个独立段 = 每步独立进程未变


def test_build_step_prompt_continuation_strips_pack(wf_repo):
    """续步变体：剥交接包（会话内已有真迹）+ 「同会话续步」头 + 当前任务段原样。"""
    drv = _load(DRIVER, "drv_cont_prompt")
    _seg_write_state(wf_repo, sub_index=2, node="understand:2", sub_step_index=4)
    state = _read_state(wf_repo)
    node = engine.get_node("understand", 2)
    step = engine.sub_step_at(node, 4)
    p = drv.build_step_prompt(
        wf_repo, "t", state, node, 4, step, rework=None, continuation=True
    )
    assert "同会话续步" in p
    assert "## WORKFLOW 上下文交接包" not in p
    assert "当前任务" in p and step.purpose in p


def test_merged_session_cmd_and_wire_format(wf_repo, monkeypatch):
    """旗标组合（--input-format stream-json × --session-id × NO_MCP）+
    send NDJSON user 消息 + read_turn result 提取 + close 幂等。"""
    drv = _load(DRIVER, "drv_ms_wire")
    lines = [
        json.dumps({"type": "system", "subtype": "init", "session_id": "x"}),
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "干完了"}],
                    "usage": {"input_tokens": 10},
                },
            }
        ),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "num_turns": 1,
                "duration_ms": 1000,
            }
        ),
    ]
    captured = {}

    class _FakeProc:
        def __init__(self):
            self.stdout = iter(lines)
            self.stdin = io.StringIO()

        def wait(self):
            return 0

        def terminate(self):
            pass

        def kill(self):
            pass

    def fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr(drv.subprocess, "Popen", fake_popen)
    meta = wf_repo / SEG_META
    sess = drv.MergedSession(
        cwd=wf_repo,
        settings=meta / "settings.json",
        sys_prompt_file=meta / "rules.md",
        meta=meta,
        debug=False,
        note="t",
    )
    cmd = captured["cmd"]
    assert cmd[cmd.index("--input-format") + 1] == "stream-json"
    assert "--session-id" in cmd
    for flag in engine.NO_MCP_ARGS:
        assert flag in cmd
    sess.send("提示词")
    wire = json.loads(sess._proc.stdin.getvalue().strip())
    assert wire == {
        "type": "user",
        "message": {"role": "user", "content": "提示词"},
    }
    text, info = sess.read_turn()
    assert text == "干完了" and info["subtype"] == "success"
    sess.close()
    sess.close()  # 幂等


def test_run_session_spawn_overrides(wf_repo, monkeypatch):
    """u2-residual-cost：spawn_env/tools 覆盖进 cmd 与 Popen env；
    prompt 仍走 stdin（--tools 逗号单串，无变长参数吞 prompt 风险）。"""
    drv = _load(DRIVER, "drv_spawn_ov")
    captured = {}

    class _FakeProc:
        stdout = iter([])
        stdin = io.StringIO()

        def wait(self):
            return 0

        def terminate(self):
            pass

        def kill(self):
            pass

    def fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        captured["env"] = kw.get("env")
        return _FakeProc()

    monkeypatch.setattr(drv.subprocess, "Popen", fake_popen)
    meta = wf_repo / SEG_META
    rc, _out, _sid = drv.run_session(
        "提示词正文",
        cwd=wf_repo,
        settings=meta / "settings.json",
        sys_prompt_file=meta / "rules.md",
        meta=meta,
        debug=False,
        note="t",
        spawn_env={"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"},
        tools=("Bash", "Read", "Edit", "Skill"),
    )
    cmd = captured["cmd"]
    assert cmd[cmd.index("--tools") + 1] == "Bash,Read,Edit,Skill"
    assert captured["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
    assert rc == 0


def test_run_session_default_no_overrides(wf_repo, monkeypatch):
    """现状不回归：无覆盖时 cmd 无 --tools、Popen env=None（继承父进程）。"""
    drv = _load(DRIVER, "drv_spawn_default")
    captured = {}

    class _FakeProc:
        stdout = iter([])
        stdin = io.StringIO()

        def wait(self):
            return 0

        def terminate(self):
            pass

        def kill(self):
            pass

    def fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        captured["env"] = kw.get("env")
        return _FakeProc()

    monkeypatch.setattr(drv.subprocess, "Popen", fake_popen)
    meta = wf_repo / SEG_META
    drv.run_session(
        "提示词正文",
        cwd=wf_repo,
        settings=meta / "settings.json",
        sys_prompt_file=meta / "rules.md",
        meta=meta,
        debug=False,
        note="t",
    )
    assert "--tools" not in captured["cmd"]
    assert captured["env"] is None


def test_merged_session_spawn_overrides(wf_repo, monkeypatch):
    """u2-residual-cost：MergedSession 同管线——--tools 进 cmd、spawn_env 进 env。"""
    drv = _load(DRIVER, "drv_ms_ov")
    captured = {}

    class _FakeProc:
        def __init__(self):
            self.stdout = iter([])
            self.stdin = io.StringIO()

        def wait(self):
            return 0

        def terminate(self):
            pass

        def kill(self):
            pass

    def fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        captured["env"] = kw.get("env")
        return _FakeProc()

    monkeypatch.setattr(drv.subprocess, "Popen", fake_popen)
    meta = wf_repo / SEG_META
    sess = drv.MergedSession(
        cwd=wf_repo,
        settings=meta / "settings.json",
        sys_prompt_file=meta / "rules.md",
        meta=meta,
        debug=False,
        note="t",
        spawn_env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"},
        tools=("Bash", "Read", "Edit", "Skill"),
    )
    cmd = captured["cmd"]
    assert cmd[cmd.index("--tools") + 1] == "Bash,Read,Edit,Skill"
    assert captured["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    sess.close()
