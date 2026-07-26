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


def _run_hook(mod, repo: Path, monkeypatch, capsys, tool: str, tool_input: dict):
    """喂 PreToolUse payload 跑 hook main()，返回 (decision|None, reason)。"""
    payload = {
        "cwd": str(repo / ".claude" / "worktrees" / "t"),
        "session_id": "s",
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
        # 核心防回归：demo b01d6507 场景——子1 零 trace 时为用户问题跑 ls/grep
        _write_state(wf_repo, sub_step=1)
        mod = _load_hook()
        decision, reason = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Bash",
            {"command": "ls && grep -c def x.py"},
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

    def test_bash_evidence_rel_path_denied_with_abs_pointer(
        self, wf_repo, monkeypatch, capsys
    ):
        # 症状 L 前置拦截：相对路径写 evidence -> deny 且文案给绝对路径
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
        assert str(wf_repo / ".claude" / "evidence" / "t.jsonl") in reason

    def test_write_evidence_allowed(self, wf_repo, monkeypatch, capsys):
        _write_state(wf_repo, sub_step=1)
        ev = wf_repo / ".claude" / "evidence" / "t.jsonl"
        mod = _load_hook()
        decision, _ = _run_hook(
            mod,
            wf_repo,
            monkeypatch,
            capsys,
            "Write",
            {"file_path": str(ev), "content": "{}\n"},
        )
        assert decision is None

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

    def test_step3_fence_allow_bash_webfetch(self, wf_repo, monkeypatch, capsys):
        # 子3 fence_allow=("Bash","WebFetch")：curl 五层源放行
        _write_state(wf_repo, sub_step=3)
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
            "WebFetch",
            {"url": "https://x", "prompt": "y"},
        )
        assert decision is None

    def test_step3_agent_denied(self, wf_repo, monkeypatch, capsys):
        # Agent 只在子4 fence_allow，子3 窗口内仍拦
        _write_state(wf_repo, sub_step=3)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod, wf_repo, monkeypatch, capsys, "Agent", {"prompt": "x"}
        )
        assert decision == "deny"

    def test_step4_agent_allowed(self, wf_repo, monkeypatch, capsys):
        _write_state(wf_repo, sub_step=4)
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

    def test_fence_off_allows_all(self, wf_repo, monkeypatch, capsys):
        _write_state(wf_repo, sub_step=1, enforce=False)
        mod = _load_hook()
        decision, _ = _run_hook(
            mod, wf_repo, monkeypatch, capsys, "Bash", {"command": "ls"}
        )
        assert decision is None
