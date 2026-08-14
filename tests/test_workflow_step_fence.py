"""
hooks/workflow_step_fence.py S15 前置参与围栏的单元测试。

§step-engage-prefence：当前子步骤「零 trace 窗口」内仅编排工具可用（常驻集 +
Step.fence_allow），为用户任务探查的工具调用在第一次调用即被 deny 指回编排
（2026-07-26 demo b01d6507：MiniMax-M3 首回合 Bash 探查抢答，S13 因用户
中断没机会开火——判据前置到 PreToolUse）。

调用方式：in-process import（importlib）+ monkeypatch stdin 喂 PreToolUse
payload；真 git worktree（--git-common-dir 在真 worktree 内才返绝对路径）。
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
HOOK = DLWF_ROOT / "hooks" / "workflow_step_fence.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location("wsf_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["wsf_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def wf_repo(tmp_path: Path):
    """真 git repo + 真 worktree(.claude/worktrees/t) + state/evidence 目录。"""
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


def _write_state(repo: Path, sub_step: int = 1, enforce: bool = True) -> None:
    state = {
        "name": "t",
        "phase": "understand",
        "index": 1,
        "sub_index": 1,
        "sub_total": 4,
        "sub_step_index": sub_step,
        "gate": "pending",
        "node_attempts": 0,
        "enforce_step_fence": enforce,
        "session_id": "s",
        "branch": "wf/t",
        "worktree_path": str(repo / ".claude" / "worktrees" / "t"),
        "created_at": "x",
        "updated_at": "x",
        "history": [],
    }
    (repo / ".claude" / "workflows" / "t" / "state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )


def _write_trace(repo: Path, sub_step: int) -> None:
    trace = json.dumps(
        {
            "kind": "skill-trace",
            "major_stage": "Understand",
            "minor_stage": "ProblemContext",
            "sub_step": sub_step,
            "skill": "x",
            "purpose": "p",
            "q": ["q"],
            "a": ["a"],
        },
        ensure_ascii=False,
    )
    with (repo / ".claude" / "evidence" / "t.jsonl").open("a", encoding="utf-8") as f:
        f.write(trace + "\n")


def _run_hook(
    mod,
    repo: Path,
    monkeypatch,
    capsys,
    tool: str,
    tool_input: dict,
    session_id: str = "s",
):
    """喂 PreToolUse payload 跑 hook main()，返回 (decision|None, reason)。"""
    payload = {
        "cwd": str(repo / ".claude" / "worktrees" / "t"),
        "session_id": session_id,
        "tool_name": tool,
        "tool_input": tool_input,
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert mod.main() == 0
    out = capsys.readouterr().out.strip()
    if not out:
        return None, ""
    directive = json.loads(out)
    spec = directive["hookSpecificOutput"]
    return spec.get("permissionDecision"), spec.get("permissionDecisionReason", "")


class TestS15EngagePreFence:
    """零 trace 窗口：白名单模式。"""

    def test_bash_user_task_denied(self, wf_repo, monkeypatch, capsys):
        # 核心防回归：demo b01d6507 场景——子1 零 trace 时为用户问题跑探查抢答。
        # v2.53 边界修正：只读发现命令（ls/grep/find）不再 deny（harness 隐藏
        # Glob/Grep 后它是唯一合法发现通道，deny 它只制造盲 Read 猜路径）——
        # 抢答防御回到 S13（纯 text 抢答在 Stop 兜底）；写/执行类命令仍 deny。
        _write_state(wf_repo, sub_step=1)
        mod = _load_hook()
        decision, reason = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Bash",
            {"command": "python3 run_analysis.py"},
        )
        assert decision == "deny"
        assert "子步骤 1" in reason
        assert "define-problem" in reason

    def test_websearch_denied(self, wf_repo, monkeypatch, capsys):
        _write_state(wf_repo, sub_step=1)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod, wf_repo, monkeypatch, capsys, "WebSearch", {"query": "x"}
        )
        assert decision == "deny"

    def test_ask_user_question_allowed(self, wf_repo, monkeypatch, capsys):
        _write_state(wf_repo, sub_step=1)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod, wf_repo, monkeypatch, capsys, "AskUserQuestion", {"questions": []}
        )
        assert decision is None  # 放行（无 stdout）

    def test_skill_invoke_allowed(self, wf_repo, monkeypatch, capsys):
        _write_state(wf_repo, sub_step=1)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod, wf_repo, monkeypatch, capsys, "Skill", {"skill": "define-problem"}
        )
        assert decision is None

    def test_read_allowed(self, wf_repo, monkeypatch, capsys):
        _write_state(wf_repo, sub_step=1)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod, wf_repo, monkeypatch, capsys, "Read", {"file_path": "/etc/hosts"}
        )
        assert decision is None

    def test_bash_codegraph_allowed(self, wf_repo, monkeypatch, capsys):
        _write_state(wf_repo, sub_step=1)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Bash",
            {"command": "codegraph impact foo"},
        )
        assert decision is None

    def test_bash_dl_cmd_allowed(self, wf_repo, monkeypatch, capsys):
        _write_state(wf_repo, sub_step=1)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Bash",
            {"command": "bash ~/.dl-workflow/scripts/workflow/dl-cmd.sh status"},
        )
        assert decision is None

    def test_bash_evidence_abs_path_allowed(self, wf_repo, monkeypatch, capsys):
        _write_state(wf_repo, sub_step=1)
        ev = wf_repo / ".claude" / "evidence" / "t.jsonl"
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Bash",
            {"command": f"printf '%s\\n' '{{}}' >> {ev}"},
        )
        assert decision is None

    def test_bash_evidence_rel_path_denied_with_append_trace_pointer(
        self, wf_repo, monkeypatch, capsys
    ):
        # 症状 L 前置拦截（v2.14）：相对路径写 evidence -> deny 且文案指 append-trace
        _write_state(wf_repo, sub_step=1)
        mod = _load_hook()
        decision, reason = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Bash",
            {"command": "printf '%s\\n' '{}' >> .claude/evidence/t.jsonl"},
        )
        assert decision == "deny"
        assert "append-trace" in reason  # v2.14：文案指 append-trace（脚本管路径）

    def test_write_payload_allowed(self, wf_repo, monkeypatch, capsys):
        # v2.14：evidence 目录下载荷文件（.trace-payload-*.json）Write 放行
        _write_state(wf_repo, sub_step=1)
        payload = wf_repo / ".claude" / "evidence" / ".trace-payload-t.json"
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Write",
            {"file_path": str(payload), "content": "{}\n"},
        )
        assert decision is None

    def test_write_evidence_jsonl_denied_to_append_trace(
        self, wf_repo, monkeypatch, capsys
    ):
        # v2.14 S14 收编：直写 evidence jsonl 本体一律 deny，指回 append-trace
        _write_state(wf_repo, sub_step=1)
        ev = wf_repo / ".claude" / "evidence" / "t.jsonl"
        mod = _load_hook()
        decision, reason = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Write",
            {"file_path": str(ev), "content": "{}\n"},
        )
        assert decision == "deny"
        assert "append-trace" in reason

    def test_write_md_payload_denied_to_scaffold(self, wf_repo, monkeypatch, capsys):
        # v2.66：手写 Write .md 载荷（标头粘内容=手写格式）deny，指回 --scaffold；
        # 格式归脚本（四桶），模型只 Edit 「待填」填内容。tail_volume u:1 子1
        # 绕过 scaffold 手写粘头载荷致解析失败+字节 hunt 死循环 8 报错。
        _write_state(wf_repo, sub_step=1)
        payload = wf_repo / ".claude" / "worktrees" / "t" / ".trace-payload-t.md"
        mod = _load_hook()
        decision, reason = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Write",
            {"file_path": str(payload), "content": "【purpose】x\n"},
        )
        assert decision == "deny"
        assert "scaffold" in reason

    def test_edit_md_payload_allowed(self, wf_repo, monkeypatch, capsys):
        # v2.66：Edit 载荷（填「待填」）合法放行——scaffold 生成骨架后模型只
        # Edit 填内容，这是唯一合法的载荷修改方式。
        _write_state(wf_repo, sub_step=1)
        payload = wf_repo / ".claude" / "worktrees" / "t" / ".trace-payload-t.md"
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Edit",
            {
                "file_path": str(payload),
                "old_string": "待填",
                "new_string": "内容",
            },
        )
        assert decision is None

    def test_bash_append_trace_allowed(self, wf_repo, monkeypatch, capsys):
        # v2.14：零 trace 窗口内 append-trace / redteam-prompt 属编排命令
        # v2.38：fetch-prompt 同列（子3 取证子代理 prompt 组装）
        _write_state(wf_repo, sub_step=1)
        mod = _load_hook()
        for cmd in (
            "python3 ~/.dl-workflow/dl_flow_engine.py append-trace --from-file /tmp/p.json",
            "python3 ~/.dl-workflow/dl_flow_engine.py redteam-prompt",
            "python3 ~/.dl-workflow/dl_flow_engine.py fetch-prompt",
        ):
            decision, _ = _run_hook(
                mod, wf_repo, monkeypatch, capsys, "Bash", {"command": cmd}
            )
            assert decision is None, cmd

    def test_bash_engine_readonly_queries_allowed(self, wf_repo, monkeypatch, capsys):
        # v2.67：引擎只读子命令 status/current/progress 与 dl-cmd.sh status
        # 语义等价（dl-cmd 本就包装引擎 status），路径技术性 deny 白烧一轮
        # ——2026-08-03 tail_volume_acceleration_annualized u:1 实证。
        _write_state(wf_repo, sub_step=1)
        mod = _load_hook()
        for cmd in (
            "python3 ~/.dl-workflow/dl_flow_engine.py status some_wf",
            "python3 ~/.dl-workflow/dl_flow_engine.py current some_wf",
            "python3 ~/.dl-workflow/dl_flow_engine.py progress some_wf 2>&1 | head -30",
        ):
            decision, _ = _run_hook(
                mod, wf_repo, monkeypatch, capsys, "Bash", {"command": cmd}
            )
            assert decision is None, cmd

    def test_bash_engine_mutating_still_denied(self, wf_repo, monkeypatch, capsys):
        # 写状态子命令（step-pass/state-reset/fence）仍只走 /dl，直调引擎 deny
        _write_state(wf_repo, sub_step=1)
        mod = _load_hook()
        for cmd in (
            "python3 ~/.dl-workflow/dl_flow_engine.py step-pass some_wf",
            "python3 ~/.dl-workflow/dl_flow_engine.py state-reset some_wf understand:1",
            "python3 ~/.dl-workflow/dl_flow_engine.py fence some_wf off",
        ):
            decision, _ = _run_hook(
                mod, wf_repo, monkeypatch, capsys, "Bash", {"command": cmd}
            )
            assert decision == "deny", cmd

    def test_write_source_denied(self, wf_repo, monkeypatch, capsys):
        # 写非 evidence 文件：S11（阶段白名单）或 S15 必有一拦
        _write_state(wf_repo, sub_step=1)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Write",
            {"file_path": str(wf_repo / "x.py"), "content": "x"},
        )
        assert decision == "deny"

    def test_step4_fence_allow_bash_agent(self, wf_repo, monkeypatch, capsys):
        # v2.38：子4（双向取证）fence_allow=("Bash","Agent")——内部仓库层 Bash + 取证子代理放行
        _write_state(wf_repo, sub_step=4)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Bash",
            {"command": "curl -s https://api.openalex.org/works?search=x"},
        )
        assert decision is None
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Agent",
            {"prompt": "外部取证"},
        )
        assert decision is None
        # v2.xx：TaskOutput 放行--模型派后台 agent 后用它阻塞等结果（tail_volume
        # u:1 子3 实证：12:54:50 TaskOutput 被 S15 误拦 -> 无法等 agent -> end_turn
        # 假性 GATE block「无 trace」）。TaskOutput=harness 原生等后台 agent 机制。
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "TaskOutput",
            {"task_id": "call_x"},
        )
        assert decision is None, "子4 TaskOutput 应放行（等后台 agent 结果）"

    def test_step4_taskoutput_allowed(self, wf_repo, monkeypatch, capsys):
        # 显式：子4（双向取证）零 trace 窗口内 TaskOutput 放行（与 Agent 配套）
        _write_state(wf_repo, sub_step=4)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "TaskOutput",
            {"task_id": "call_1", "block": True},
        )
        assert decision is None

    def test_step5_taskoutput_allowed(self, wf_repo, monkeypatch, capsys):
        # 子5（质检裁决）红队 Agent 同样需要 TaskOutput 等结果
        _write_state(wf_repo, sub_step=5)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "TaskOutput",
            {"task_id": "call_1"},
        )
        assert decision is None

    def test_step2_taskoutput_denied(self, wf_repo, monkeypatch, capsys):
        # 非 Agent 子步骤（子2 因果推理）不放行 TaskOutput--无后台 agent 可等
        _write_state(wf_repo, sub_step=2)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "TaskOutput",
            {"task_id": "call_1"},
        )
        assert decision == "deny"

    def test_step4_webfetch_denied(self, wf_repo, monkeypatch, capsys):
        # v2.38：WebFetch 环境性弃用（域验证全挂）移出子4（双向取证）fence_allow，窗口内拦
        _write_state(wf_repo, sub_step=4)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "WebFetch",
            {"url": "https://x", "prompt": "y"},
        )
        assert decision == "deny"

    def test_step5_agent_allowed(self, wf_repo, monkeypatch, capsys):
        _write_state(wf_repo, sub_step=5)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod, wf_repo, monkeypatch, capsys, "Agent", {"prompt": "红队"}
        )
        assert decision is None

    def test_window_closed_after_trace(self, wf_repo, monkeypatch, capsys):
        # 有未判决 trace -> S15 窗口关闭，归 S10（全 deny 含 Read）
        _write_state(wf_repo, sub_step=1)
        _write_trace(wf_repo, sub_step=1)
        mod = _load_hook()
        decision, reason = _run_hook(
            mod, wf_repo, monkeypatch, capsys, "Read", {"file_path": "/etc/hosts"}
        )
        assert decision == "deny"
        assert "STEP_DONE" in reason  # S10 文案，非 S15

    def test_task_tools_exempt_in_s10_window(self, wf_repo, monkeypatch, capsys):
        # S10 Task* 豁免（2026-07-27，demo 907fee09）：Task* 是 output-style 强制
        # 每轮维护的清单记账工具，无法用于下一子步骤探查——deny 它不防违规，
        # 只制造「同步 TaskList 被 deny -> 重试 9 次」的报错刷屏。
        _write_state(wf_repo, sub_step=1)
        _write_trace(wf_repo, sub_step=1)  # 未判决 trace -> S10 窗口
        mod = _load_hook()
        for task_tool in ("TaskCreate", "TaskUpdate", "TaskList", "TaskGet"):
            decision, _ = _run_hook(mod, wf_repo, monkeypatch, capsys, task_tool, {})
            assert decision is None, f"{task_tool} 应在 S10 窗口豁免"
        # 探查工具仍 deny——豁免不削弱 S10 的防御目的
        decision, reason = _run_hook(
            mod, wf_repo, monkeypatch, capsys, "Bash", {"command": "ls"}
        )
        assert decision == "deny"
        assert "STEP_DONE" in reason

    def test_fence_off_allows_all(self, wf_repo, monkeypatch, capsys):
        _write_state(wf_repo, sub_step=1, enforce=False)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod, wf_repo, monkeypatch, capsys, "Bash", {"command": "ls"}
        )
        assert decision is None


class TestS15ReadonlyDiscovery:
    """v2.53：S15 零 trace 窗口放开 Bash 只读发现通道。

    实证（2026-08-02 tail_volume_acceleration_annualized u:1）：harness 默认
    隐藏 Glob/Grep 并指路 Bash find/grep，S15 却只放行 Read——判据要求
    file:line 证据指针而发现通道全关（25 次盲 Read miss + 6 次 find/ls/
    git log 被 deny）。只读发现是围栏设计内「无害只读」的补齐，不是扩权。
    """

    def test_find_allowed(self, wf_repo, monkeypatch, capsys):
        _write_state(wf_repo, sub_step=1)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Bash",
            {"command": "find /x -maxdepth 4 -name '*.py' | grep -iE 'report'"},
        )
        assert decision is None

    def test_ls_gitlog_allowed(self, wf_repo, monkeypatch, capsys):
        _write_state(wf_repo, sub_step=1)
        mod = _load_hook()
        for cmd in ("ls /x 2>/dev/null", "git log --oneline -20", "cat a | head -20"):
            decision, _ = _run_hook(
                mod, wf_repo, monkeypatch, capsys, "Bash", {"command": cmd}
            )
            assert decision is None, f"{cmd} 应放行"

    def test_write_intent_denied(self, wf_repo, monkeypatch, capsys):
        _write_state(wf_repo, sub_step=1)
        mod = _load_hook()
        for cmd in (
            "find /x -name '*.py' > /tmp/out",  # 输出重定向
            "find /x -name '*.py' | xargs rm",  # xargs 走私
            "echo $(cat /etc/passwd)",  # 命令替换
            "ls /x && rm -rf /x",  # 复合写命令
            "python3 -c \"open('/tmp/x','w').write('y')\"",  # python3 写意图
        ):
            decision, reason = _run_hook(
                mod, wf_repo, monkeypatch, capsys, "Bash", {"command": cmd}
            )
            assert decision == "deny", f"{cmd} 应 deny"
            assert "S15" in reason

    def test_python_readonly_data_allowed(self, wf_repo, monkeypatch, capsys):
        # v2.xx：S15 放行 python3 -c 只读数据（读 JSON/parquet 字段）--
        # 子2 因果链每环要 file:line 证据指针，CLAUDE.md §3 推荐 python3 读
        # 数据，零 trace 窗口禁 python3 = 合法取证通道被关（tail_volume u:1
        # 子2 实证 40 次 S15 deny）。威胁模型=强模型非对抗，写信号一票否决。
        _write_state(wf_repo, sub_step=1)
        mod = _load_hook()
        for cmd in (
            'python3 -c \'import json;print(json.load(open("x"))["y"])\'',
            "python3 -c \"import json; d=json.load(open('x')); print(d)\"",
            "python3 -c 'print(1)'",
            "python3 -c 'import pandas as pd; print(pd.read_parquet(\"x\"))'",
        ):
            decision, _ = _run_hook(
                mod, wf_repo, monkeypatch, capsys, "Bash", {"command": cmd}
            )
            assert decision is None, f"{cmd} 应放行（python3 -c 只读）"

    def test_python_write_intent_denied(self, wf_repo, monkeypatch, capsys):
        _write_state(wf_repo, sub_step=1)
        mod = _load_hook()
        for cmd in (
            "python3 -c \"open('y','w').write('z')\"",  # open write
            "python3 -c 'import os; os.system(\"rm x\")'",  # os.system
            'python3 -c \'import subprocess; subprocess.run(["rm","x"])\'',
            'python3 -c \'__import__("os").system("x")\'',
            "python3 script.py",  # 非 -c（外部脚本不可判定）
            'python3 -c \'open("a","a").write("b")\'',  # append 模式
        ):
            decision, reason = _run_hook(
                mod, wf_repo, monkeypatch, capsys, "Bash", {"command": cmd}
            )
            assert decision == "deny", f"{cmd} 应 deny"
            assert "S15" in reason

    def test_unit_matcher(self):
        mod = _load_hook()
        ok = mod._s15_bash_readonly_discovery
        assert ok("find . -name '*.py'")
        assert ok("git show HEAD~1 --stat")
        assert ok("grep -rn 'x' . 2>/dev/null | head -5")
        assert ok("python3 -c 'import json;print(json.load(open(\"x\")))'")
        assert not ok("ls > out")
        assert not ok("cat `which ls`")
        assert not ok("find . | tee out")
        assert not ok("echo hi; rm x")
        assert not ok("python3 -c \"open('x','w').write('y')\"")
        assert not ok("python3 script.py")

    def test_byte_viewers_allowed(self):
        # v2.65：od/hexdump/xxd 纯只读字节查看器放行（诊断 BOM/编码；
        # > 已被一票否决挡住写意图）。python3 -c 只读放行（见 test_python_*）。
        mod = _load_hook()
        ok = mod._s15_bash_readonly_discovery
        assert ok("head -c 30 f.md | xxd")
        assert ok("od -An -c f.md | head -3")
        assert ok("hexdump -C f.md")
        assert ok("python3 -c 'print(1)'")  # 只读放行（v2.xx）
        assert not ok("python3 -c \"open('x','w').write('y')\"")  # 写信号拒
        assert not ok("xxd -r f.md > out")  # -r 反向写但 > 已挡

    def test_single_amp_background_denied(self, wf_repo, monkeypatch, capsys):
        # 拆段器共享（_s15_bash_readonly_discovery 同用 _split_shell_segments）：
        # `grep x & rm` 原整段以 grep 头命中放行 + rm 后台跑——单 & 拆段后
        # 破坏段被拦（审计 Important #2 同根因，只读发现通道同样受影响）。
        _write_state(wf_repo, sub_step=1)
        mod = _load_hook()
        for cmd in (
            "grep -rn 'x' . & rm -rf /tmp/y",
            "ls /x & git clean -f",
        ):
            decision, reason = _run_hook(
                mod, wf_repo, monkeypatch, capsys, "Bash", {"command": cmd}
            )
            assert decision == "deny", f"{cmd} 应 deny（单& 后台走私）"
            assert "S15" in reason


class TestSkeletonWriteFallback:
    """Q1a：模型 Write/Edit fetch-prompt-skeleton.md -> deny + 副作用 --out 刷新。

    tail_volume u:1 子3 实证：模型 4 次 Write 骨架文件被 S11 deny，但骨架本该
    引擎 --out 独占写。hook 识别后副作用调 fetch_prompt 刷新骨架为引擎版本，
    deny 指路 Read 取用（PreToolUse 不能转换工具，用 deny+副作用等价）。
    """

    def test_write_skeleton_auto_refreshed(self, wf_repo, monkeypatch, capsys):
        _write_state(wf_repo, sub_step=3)
        mod = _load_hook()
        monkeypatch.setattr(mod.engine, "fetch_prompt", lambda pr, n: "SKELETON_BODY")
        skel = wf_repo / ".claude" / "workflows" / "t" / "fetch-prompt-skeleton.md"
        decision, reason = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Write",
            {"file_path": str(skel), "content": "model hand-written"},
        )
        assert decision == "deny"
        assert "--out" in reason or "已自动" in reason or "Read" in reason
        # 副作用：骨架被刷新为引擎版本，非模型手写内容
        assert skel.read_text(encoding="utf-8").startswith("SKELETON_BODY")
        assert "model hand-written" not in skel.read_text(encoding="utf-8")

    def test_write_skeleton_no_sub2_trace(self, wf_repo, monkeypatch, capsys):
        # fetch_prompt 返 None（无子2 trace）-> deny 指回补子2，不写文件
        _write_state(wf_repo, sub_step=3)
        mod = _load_hook()
        monkeypatch.setattr(mod.engine, "fetch_prompt", lambda pr, n: None)
        skel = wf_repo / ".claude" / "workflows" / "t" / "fetch-prompt-skeleton.md"
        decision, reason = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Write",
            {"file_path": str(skel), "content": "x"},
        )
        assert decision == "deny"
        assert "子2" in reason or "trace" in reason
        assert not skel.exists()

    def test_edit_skeleton_also_redirected(self, wf_repo, monkeypatch, capsys):
        # Edit 骨架同样兜底（模型可能 Edit 改骨架 claim 区）
        _write_state(wf_repo, sub_step=3)
        mod = _load_hook()
        monkeypatch.setattr(mod.engine, "fetch_prompt", lambda pr, n: "SKELETON_BODY")
        skel = wf_repo / ".claude" / "workflows" / "t" / "fetch-prompt-skeleton.md"
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Edit",
            {
                "file_path": str(skel),
                "old_string": "a",
                "new_string": "b",
            },
        )
        assert decision == "deny"
        assert skel.read_text(encoding="utf-8").startswith("SKELETON_BODY")


def _write_front_state(
    repo: Path, *, drive_mode: bool, front_mode: bool, session_id: str = "s"
) -> None:
    """写带 front_mode/drive_mode 的 state（session_id 可变，模拟前台 vs 段工人）。"""
    state = {
        "name": "t",
        "phase": "understand",
        "index": 1,
        "sub_index": 1,
        "sub_total": 4,
        "sub_step_index": 1,
        "gate": "pending",
        "node_attempts": 0,
        "enforce_step_fence": True,
        "session_id": session_id,
        "drive_mode": drive_mode,
        "front_mode": front_mode,
        "branch": "wf/t",
        "worktree_path": str(repo / ".claude" / "worktrees" / "t"),
        "created_at": "x",
        "updated_at": "x",
        "history": [],
    }
    (repo / ".claude" / "workflows" / "t" / "state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )


class TestFrontSegmentRunFence:
    """段跑期间（drive_mode=on + front_mode=on）前台会话白名单收紧。

    触发 = 2026-08-13 amplitude_annualized 抢活实证：段工人跑 understand:1 时，
    前台会话并行 grep/Read 源码。修法 = drive_mode 早退区分前台(session_id==
    state.session_id) vs 段工人(session_id≠)，前台收紧为「只交互+记账+/dl」。
    """

    def test_front_grep_denied(self, wf_repo, monkeypatch, capsys):
        _write_front_state(wf_repo, drive_mode=True, front_mode=True)
        mod = _load_hook()
        decision, reason = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Bash",
            {"command": "grep -rn annual --include=*.py ."},
        )
        assert decision == "deny"
        assert "后台" in reason or "段" in reason

    def test_front_read_source_denied(self, wf_repo, monkeypatch, capsys):
        _write_front_state(wf_repo, drive_mode=True, front_mode=True)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Read",
            {"file_path": str(wf_repo / "f")},
        )
        assert decision == "deny"

    def test_front_skill_denied(self, wf_repo, monkeypatch, capsys):
        _write_front_state(wf_repo, drive_mode=True, front_mode=True)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod, wf_repo, monkeypatch, capsys, "Skill", {"skill": "define-problem"}
        )
        assert decision == "deny"

    def test_front_agent_denied(self, wf_repo, monkeypatch, capsys):
        _write_front_state(wf_repo, drive_mode=True, front_mode=True)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Agent",
            {"description": "x", "prompt": "y"},
        )
        assert decision == "deny"

    def test_front_ask_user_allowed(self, wf_repo, monkeypatch, capsys):
        _write_front_state(wf_repo, drive_mode=True, front_mode=True)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "AskUserQuestion",
            {"questions": []},
        )
        assert decision is None  # 放行：无 deny 输出

    def test_front_task_allowed(self, wf_repo, monkeypatch, capsys):
        _write_front_state(wf_repo, drive_mode=True, front_mode=True)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod, wf_repo, monkeypatch, capsys, "TaskCreate", {"subject": "x"}
        )
        assert decision is None

    def test_front_slash_dl_allowed(self, wf_repo, monkeypatch, capsys):
        _write_front_state(wf_repo, drive_mode=True, front_mode=True)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod, wf_repo, monkeypatch, capsys, "SlashCommand", {"command": "/dl status"}
        )
        assert decision is None

    def test_segment_worker_full_access(self, wf_repo, monkeypatch, capsys):
        # 段工人 session_id != state.session_id -> 全放行（return 0，无 deny）
        _write_front_state(wf_repo, drive_mode=True, front_mode=True, session_id="s")
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Bash",
            {"command": "grep -rn annual --include=*.py ."},
            session_id="seg-worker",
        )
        assert decision is None

    def test_segment_worker_session_id_missing_defensive(
        self, wf_repo, monkeypatch, capsys
    ):
        # state.session_id 空 -> 不收紧（防误伤段工人）
        _write_front_state(wf_repo, drive_mode=True, front_mode=True, session_id="")
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Bash",
            {"command": "grep -rn annual --include=*.py ."},
            session_id="",
        )
        assert decision is None

    def test_v3_drive_no_front_allow_all(self, wf_repo, monkeypatch, capsys):
        # v3 headless：front_mode=False，drive_mode 早退照旧全放行
        _write_front_state(wf_repo, drive_mode=True, front_mode=False)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Bash",
            {"command": "grep -rn annual --include=*.py ."},
            session_id="s",
        )
        assert decision is None


class TestS15ProjectToolAllow:
    """组件 B：注册项目工具 command 头进 S15 白名单。

    codebase-archaeology-toolbox-design §3.3：工具 command 头并入 S15 Bash 白名单，
    但只放行只读发现类——破坏性命令头（rm/dd/sudo）不进白名单（弱模型幻觉刹车）；
    工具 + shell 写走私（重定向/命令替换/复合破坏段）一票否决；未注册命令不因
    白名单存在而放行。注册工具本身安全由项目自担（脚本在项目仓、走 code review）。
    """

    _YAML = (
        "tools:\n"
        "  - name: inspect-backtest-result\n"
        "    command: scripts/inspect_backtest_result.py --factor {factor}\n"
        "    description: 读回测结果元数据\n"
    )

    def _register(self, wf_repo: Path, text: str) -> None:
        (wf_repo / ".claude" / "workflow-tools.yaml").write_text(text, encoding="utf-8")

    def test_registered_project_tool_allowed(self, wf_repo, monkeypatch, capsys):
        _write_state(wf_repo, sub_step=1)
        self._register(wf_repo, self._YAML)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Bash",
            {"command": "scripts/inspect_backtest_result.py --factor momentum"},
        )
        assert decision is None  # 放行：无 deny 输出

    def test_project_tool_with_pipe_allowed(self, wf_repo, monkeypatch, capsys):
        _write_state(wf_repo, sub_step=1)
        self._register(wf_repo, self._YAML)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Bash",
            {
                "command": "scripts/inspect_backtest_result.py --factor momentum | head -20"
            },
        )
        assert decision is None

    def test_project_tool_write_intent_denied(self, wf_repo, monkeypatch, capsys):
        _write_state(wf_repo, sub_step=1)
        self._register(wf_repo, self._YAML)
        mod = _load_hook()
        for cmd in (
            "scripts/inspect_backtest_result.py --factor x > /tmp/out",  # 输出重定向
            "scripts/inspect_backtest_result.py --factor $(rm -rf /)",  # 命令替换走私
            "scripts/inspect_backtest_result.py --factor x; rm -rf /tmp/x",  # 复合破坏段
        ):
            decision, reason = _run_hook(
                mod, wf_repo, monkeypatch, capsys, "Bash", {"command": cmd}
            )
            assert decision == "deny", f"{cmd} 应 deny"
            assert "S15" in reason

    def test_destructive_tool_head_not_whitelisted(self, wf_repo, monkeypatch, capsys):
        # 注册破坏性命令头（rm）不进白名单——弱模型幻觉刹车保留
        _write_state(wf_repo, sub_step=1)
        self._register(wf_repo, "tools:\n  - name: wipe\n    command: rm -rf /tmp/x\n")
        mod = _load_hook()
        decision, _ = _run_hook(
            mod, wf_repo, monkeypatch, capsys, "Bash", {"command": "rm -rf /tmp/x"}
        )
        assert decision == "deny"

    def test_unregistered_command_still_denied(self, wf_repo, monkeypatch, capsys):
        # 白名单只放行注册头；未注册的其它脚本仍 deny
        _write_state(wf_repo, sub_step=1)
        self._register(wf_repo, self._YAML)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Bash",
            {"command": "scripts/other.py --x 1"},
        )
        assert decision == "deny"

    def test_interpreter_head_not_whitelisted(self, wf_repo, monkeypatch, capsys):
        # 通用解释器头（python3/bash）不当工具头——否则注册「python3 脚本」后
        # 任意 python3 命令都命中头白名单放行（含 -c 内联写），白名单降级为
        # 全放行，弱模型幻觉刹车失效。工具头须是项目脚本路径，非解释器。
        _write_state(wf_repo, sub_step=1)
        self._register(
            wf_repo, "tools:\n  - name: run\n    command: python3 scripts/inspect.py\n"
        )
        mod = _load_hook()
        for cmd in (
            "python3 scripts/inspect.py --factor x",  # 注册形态本身不进白名单
            "python3 -c \"import os; os.system('rm -rf /')\"",  # 解释器走私
            "bash scripts/inspect.py",  # 另一解释器同理
        ):
            decision, reason = _run_hook(
                mod, wf_repo, monkeypatch, capsys, "Bash", {"command": cmd}
            )
            assert decision == "deny", f"{cmd} 应 deny"
            assert "S15" in reason

    def test_git_head_not_whitelisted(self, wf_repo, monkeypatch, capsys):
        # 审计 Critical：注册只读工具 `git log` 头是 git，而头匹配短路在
        # _S15_GIT_READONLY_RE 之前——git reset --hard / clean -f / push 全过
        # 围栏。git 进破坏性头黑名单（写能力通用二进制），只读 git log 仍经
        # _S15_GIT_READONLY_RE 放行（不误伤）。
        _write_state(wf_repo, sub_step=1)
        self._register(
            wf_repo, "tools:\n  - name: glog\n    command: git log --oneline -20\n"
        )
        mod = _load_hook()
        for cmd in (
            "git reset --hard HEAD~1",
            "git clean -f",
            "git push origin main",
        ):
            decision, reason = _run_hook(
                mod, wf_repo, monkeypatch, capsys, "Bash", {"command": cmd}
            )
            assert decision == "deny", f"{cmd} 应 deny（git 头不进白名单）"
            assert "S15" in reason
        # 只读 git log 仍放行（走 readonly 正则，非工具头）
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Bash",
            {"command": "git log --oneline -20"},
        )
        assert decision is None

    def test_project_tool_stdout_redirect_denied(self, wf_repo, monkeypatch, capsys):
        # 审计 Important #1：旧 lookbehind (?<![0-9>])> 豁免任意 fd 前缀——
        # `1> file` 是完整 stdout→文件写却被放行。只 2>（stderr）豁免。
        _write_state(wf_repo, sub_step=1)
        self._register(wf_repo, self._YAML)
        mod = _load_hook()
        for cmd in (
            "scripts/inspect_backtest_result.py --factor x 1> /tmp/out",
            "scripts/inspect_backtest_result.py --factor x 1>> /tmp/out",
            "scripts/inspect_backtest_result.py --factor x 3> /tmp/out",
        ):
            decision, reason = _run_hook(
                mod, wf_repo, monkeypatch, capsys, "Bash", {"command": cmd}
            )
            assert decision == "deny", f"{cmd} 应 deny（stdout 重定向=写）"
            assert "S15" in reason
        # stderr 重定向仍豁免（2>/dev/null 不写文件）
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Bash",
            {"command": "scripts/inspect_backtest_result.py --factor x 2>/dev/null"},
        )
        assert decision is None

    def test_project_tool_single_amp_background_denied(
        self, wf_repo, monkeypatch, capsys
    ):
        # 审计 Important #2：拆段器不拆单 &，`tool & rm -rf /` 一整段、头匹配
        # 放行 + rm 后台跑。单 & 是命令分隔符，须拆段后每段校验。
        _write_state(wf_repo, sub_step=1)
        self._register(wf_repo, self._YAML)
        mod = _load_hook()
        for cmd in (
            "scripts/inspect_backtest_result.py --factor x & rm -rf /tmp/x",
            "scripts/inspect_backtest_result.py --factor x & git reset --hard",
        ):
            decision, reason = _run_hook(
                mod, wf_repo, monkeypatch, capsys, "Bash", {"command": cmd}
            )
            assert decision == "deny", f"{cmd} 应 deny（单& 拆段后破坏段被拦）"
            assert "S15" in reason


class TestS15ProjectToolBypassVectors:
    """审计三向量的单元级 matcher 测试（拆段器 / 重定向豁免）。

    task-6 安全审查三个绕过向量的机械层验证：git 头、1> 重定向、单 & 后台。
    直接打 matcher，不经 hook 全链路，便于精确定位。
    """

    def test_splitter_single_amp(self):
        mod = _load_hook()
        split = mod._split_shell_segments
        assert split("a && b") == ["a ", " b"]  # && 仍是单段分隔（不误伤）
        assert split("a & b") == ["a ", " b"]  # 单 & 拆段
        assert split("a & rm -rf /") == ["a ", " rm -rf /"]
        assert split("echo 'a&b' & echo c") == ["echo 'a&b' ", " echo c"]  # 引号保护
        assert split("git log --oneline & grep x") == ["git log --oneline ", " grep x"]

    def test_redirect_helper_only_2_exempt(self):
        mod = _load_hook()
        h = mod._has_write_redirect
        assert not h("cmd 2>/dev/null")  # stderr 豁免
        assert not h("cmd 2>>err.log")  # stderr append 豁免
        assert not h("cmd 2>&1")  # stderr→stdout 不写文件，豁免
        assert h("cmd 1> out")  # stdout→文件 = 写信号
        assert h("cmd 1>> out")
        assert h("cmd > out")
        assert h("cmd >> out")
        assert h("cmd 3> out")  # 任意非 2 fd 写重定向 = 写信号


def test_deny_readonly_narrows_grep():
    """per-step deny_readonly 从只读发现通道窄化 grep/rg（堵入口，§3.5 #39）。"""
    mod = _load_hook()
    ok = mod._s15_bash_readonly_discovery
    # 默认（无 deny_readonly）grep 放行
    assert ok("grep -rn 'x' .")
    # deny grep/rg 后 grep/rg 拒，ls / git log 仍放行
    deny = ("grep", "rg")
    assert not ok("grep -rn 'x' .", deny_readonly=deny)
    assert not ok("rg -n 'x' .", deny_readonly=deny)
    assert ok("ls -la", deny_readonly=deny)
    assert ok("git log --oneline", deny_readonly=deny)


def test_understand1_sub3_deny_readonly():
    """understand:1 子3（因果链挖掘，plan-first 拆步前旧子2）声明 deny_readonly=("grep","rg")。"""
    import dl_flow_engine as eng

    node = eng.get_node("understand", 1)
    step = node.sub_steps[2]  # 子3 = causal-inference-root-cause
    assert step.deny_readonly == ("grep", "rg")


def test_drive_mode_denies_grep_sub3(wf_repo, monkeypatch, capsys):
    """drive_mode 段工人：子3（因果链挖掘）的 deny_readonly 独立生效（S15 跳过不豁免 grep）。"""
    _write_state(wf_repo, sub_step=3)
    sp = wf_repo / ".claude" / "workflows" / "t" / "state.json"
    s = json.loads(sp.read_text(encoding="utf-8"))
    s["drive_mode"] = True
    sp.write_text(json.dumps(s), encoding="utf-8")

    mod = _load_hook()
    # 段工人 session_id != state.session_id（"worker" vs "s"）→ 走段工人分支
    decision, reason = _run_hook(
        mod, wf_repo, monkeypatch, capsys,
        "Bash", {"command": "grep -rn 'x' ."}, session_id="worker",
    )
    assert decision == "deny"
    assert "dl codebase" in reason

    # rg 同拒
    decision, _ = _run_hook(
        mod, wf_repo, monkeypatch, capsys,
        "Bash", {"command": "rg -n 'x' ."}, session_id="worker",
    )
    assert decision == "deny"

    # 非 deny 命令（append-trace 编排 / Edit）仍放行
    decision, _ = _run_hook(
        mod, wf_repo, monkeypatch, capsys,
        "Bash", {"command": "python3 ~/.dl-workflow/dl_flow_engine.py append-trace --scaffold"},
        session_id="worker",
    )
    assert decision != "deny"


def test_drive_mode_grep_allowed_other_substep(wf_repo, monkeypatch, capsys):
    """非子3（如子4）无 deny_readonly，drive_mode 段工人 grep 放行。"""
    _write_state(wf_repo, sub_step=4)
    sp = wf_repo / ".claude" / "workflows" / "t" / "state.json"
    s = json.loads(sp.read_text(encoding="utf-8"))
    s["drive_mode"] = True
    sp.write_text(json.dumps(s), encoding="utf-8")

    mod = _load_hook()
    decision, _ = _run_hook(
        mod, wf_repo, monkeypatch, capsys,
        "Bash", {"command": "grep -rn 'x' ."}, session_id="worker",
    )
    assert decision != "deny"
