"""
hooks/workflow_advance.py 子步骤 Stop 门控的单元测试。

核心防回归（2026-07-25 demo 实测事故）：Stop hook 的 stdout 必须能被
harness **整体按 JSON 解析**——pass 自动续轮路径若先 _emit 一行纯文本再写
JSON 指令，harness 解析失败会把 additionalContext 整段丢弃（模型收不到
续轮指令，停轮，表现为「子步骤 pass 后不动了」）。block 路径一直是纯 JSON
所以未暴露；pass 续轮（2026-07-25 引入）混入 _emit 后立即踩中。

调用方式：in-process import（importlib，文件名无连字符限制）+ monkeypatch
engine.run_judge（避免真起 claude -p judge 子进程）；路径解析用真 git worktree
（git rev-parse --git-common-dir 在真 worktree 内才返绝对路径，普通子目录返
相对路径会导致 state 解析到错误位置）。
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
HOOK = DLWF_ROOT / "hooks" / "workflow_advance.py"


def _load_hook():
    """每个测试独立加载 hook 模块（engine 隔离，monkeypatch 不串扰）。"""
    spec = importlib.util.spec_from_file_location("wa_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["wa_under_test"] = mod
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


def _write_state(repo: Path, sub_step: int, sub_index: int = 1) -> None:
    state = {
        "name": "t",
        "phase": "understand",
        "index": 1,
        "sub_index": sub_index,
        "sub_total": 4,
        "node": f"understand:{sub_index}",
        "sub_step_index": sub_step,
        "gate": "pending",
        "node_attempts": 0,
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


# sub_index -> evidence minor_stage（与 engine 节点表 minor_key 对齐）
_MINOR = {1: "ProblemContext", 2: "GoalsAndValue"}


def _write_trace(repo: Path, sub_step: int, sub_index: int = 1) -> None:
    trace = json.dumps(
        {
            "kind": "skill-trace",
            "major_stage": "Understand",
            "minor_stage": _MINOR[sub_index],
            "sub_step": sub_step,
            "skill": "x",
            "purpose": "p",
            "q": ["q"],
            "a": ["a"],
        },
        ensure_ascii=False,
    )
    (repo / ".claude" / "evidence" / "t.jsonl").write_text(
        trace + "\n", encoding="utf-8"
    )


def _run_hook(mod, repo: Path, monkeypatch, capsys, judge=(True, "")):
    """喂 Stop payload 跑 hook main()，返回 (stdout, stderr)。"""
    monkeypatch.setattr(mod.engine, "run_judge", lambda *a, **k: judge)
    payload = {
        "cwd": str(repo / ".claude" / "worktrees" / "t"),
        "transcript_path": "/dev/null",
        "session_id": "s",
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert mod.main() == 0
    captured = capsys.readouterr()
    return captured.out, captured.err


class TestStopStdoutPureJson:
    """Stop hook stdout 必须整体可按 JSON 解析（harness 契约）。"""

    def test_nonfinal_pass_stdout_is_pure_json(self, wf_repo, monkeypatch, capsys):
        # 非末步 pass -> 自动续轮：stdout 必须是纯 JSON（additionalContext 含下一步指令）
        _write_state(wf_repo, sub_step=1)
        _write_trace(wf_repo, sub_step=1)
        mod = _load_hook()
        out, err = _run_hook(mod, wf_repo, monkeypatch, capsys, judge=(True, ""))
        directive = json.loads(out.strip())  # 整体可解析 = 纯 JSON（核心防回归）
        ctx = directive["hookSpecificOutput"]["additionalContext"]
        assert "子步骤 2/6" in ctx
        assert "causal-inference-root-cause" in ctx
        assert "✓" not in out  # ✓ 行不许混进 stdout
        assert "自动续轮" in err  # ✓ 行走 stderr
        st = json.loads((wf_repo / ".claude/workflows/t/state.json").read_text())
        assert st["sub_step_index"] == 2  # 推进照常

    def test_final_pass_no_json_stops_turn(self, wf_repo, monkeypatch, capsys):
        # 末步 pass -> §subphase-hold-gate 门栏扣留停轮：stdout 无 JSON 指令（纯文本）
        # （门栏 2026-07-27 起在 understand:2 GoalsAndValue 末步=子5）
        _write_state(wf_repo, sub_step=5, sub_index=2)
        _write_trace(wf_repo, sub_step=5, sub_index=2)
        mod = _load_hook()
        out, _err = _run_hook(mod, wf_repo, monkeypatch, capsys)
        assert "hookSpecificOutput" not in out
        assert "门栏" in out
        assert "/dl gate" in out
        st = json.loads((wf_repo / ".claude/workflows/t/state.json").read_text())
        assert st["sub_index"] == 2  # 扣留：不推进
        assert st["held_for_gate"] is True

    def test_cross_subphase_auto_continue(self, wf_repo, monkeypatch, capsys):
        # 无门栏的子阶段边界不是检查点（2026-07-27 用户预期「跑到门栏再停」）：
        # understand:1 末步（子6）pass -> 自动续轮进 understand:2 子1（纯 JSON 指令）
        _write_state(wf_repo, sub_step=6, sub_index=1)
        _write_trace(wf_repo, sub_step=6, sub_index=1)
        mod = _load_hook()
        out, _err = _run_hook(mod, wf_repo, monkeypatch, capsys, judge=(True, ""))
        directive = json.loads(out.strip())  # 整体可解析 = 纯 JSON（症状 Q 契约）
        ctx = directive["hookSpecificOutput"]["additionalContext"]
        assert "子步骤 1/5" in ctx
        assert "明确目标和价值" in ctx  # 新子阶段名
        assert "目标引出" in ctx  # understand:2 子1 的 purpose/selfcheck 入场
        st = json.loads((wf_repo / ".claude/workflows/t/state.json").read_text())
        assert st["sub_index"] == 2
        assert st["sub_step_index"] == 1
        assert "held_for_gate" not in st

    def test_block_stdout_is_pure_json(self, wf_repo, monkeypatch, capsys):
        # block 返工路径同样纯 JSON（历史一直正常，防未来混入 _emit）
        _write_state(wf_repo, sub_step=1)
        _write_trace(wf_repo, sub_step=1)
        mod = _load_hook()
        out, _err = _run_hook(
            mod, wf_repo, monkeypatch, capsys, judge=(False, "缺出处")
        )
        directive = json.loads(out.strip())
        ctx = directive["hookSpecificOutput"]["additionalContext"]
        assert "WORKFLOW GATE 未通过" in ctx
        assert "缺出处" in ctx


class TestContinueCarriesFenceNotice:
    """§autocontinue-fence-notice：pass/block 续轮附当前步 S15 围栏提示（含
    fence_allow 豁免）——防模型只在子1 见过无豁免版提示，到后续步骤臆断
    工具被 deny（demo 121320fe：子4 未试先称 Agent 被 S15 拦）。"""

    def test_pass_to_step4_notice_declares_agent(self, wf_repo, monkeypatch, capsys):
        # 子3 pass -> 续轮子4：additionalContext 须含「额外放行：Agent」
        _write_state(wf_repo, sub_step=3)
        _write_trace(wf_repo, sub_step=3)
        mod = _load_hook()
        out, _err = _run_hook(mod, wf_repo, monkeypatch, capsys, judge=(True, ""))
        directive = json.loads(out.strip())  # 纯 JSON 回归不变
        ctx = directive["hookSpecificOutput"]["additionalContext"]
        assert "子步骤 4/6" in ctx
        assert "前置参与围栏" in ctx
        assert "额外放行：Agent" in ctx

    def test_block_at_step4_notice_declares_agent(self, wf_repo, monkeypatch, capsys):
        # 子4 block 返工：豁免文案纠正「Agent 被拦」假信念
        _write_state(wf_repo, sub_step=4)
        _write_trace(wf_repo, sub_step=4)
        mod = _load_hook()
        out, _err = _run_hook(
            mod, wf_repo, monkeypatch, capsys, judge=(False, "缺独立红队")
        )
        directive = json.loads(out.strip())
        ctx = directive["hookSpecificOutput"]["additionalContext"]
        assert "缺独立红队" in ctx
        assert "额外放行：Agent" in ctx

    def test_pass_to_step2_notice_has_no_exemption(self, wf_repo, monkeypatch, capsys):
        # 子2 fence_allow=() -> 提示在但无豁免行（文案与注入通道一致）
        _write_state(wf_repo, sub_step=1)
        _write_trace(wf_repo, sub_step=1)
        mod = _load_hook()
        out, _err = _run_hook(mod, wf_repo, monkeypatch, capsys, judge=(True, ""))
        ctx = json.loads(out.strip())["hookSpecificOutput"]["additionalContext"]
        assert "前置参与围栏" in ctx
        assert "额外放行" not in ctx

    def test_pass_continue_carries_selfcheck_hint(self, wf_repo, monkeypatch, capsys):
        # §step-selfcheck：pass 续轮带提交前自查提示（judge 抓前移为自查抓）
        _write_state(wf_repo, sub_step=1)
        _write_trace(wf_repo, sub_step=1)
        mod = _load_hook()
        out, _err = _run_hook(mod, wf_repo, monkeypatch, capsys, judge=(True, ""))
        ctx = json.loads(out.strip())["hookSpecificOutput"]["additionalContext"]
        assert "STEP_DONE 前自查" in ctx
        # 步级化：子1 pass 续轮带的是**下一子步骤（子2）**的 checklist
        assert "本步自查：" in ctx and "因果链" in ctx

    def test_block_continue_carries_selfcheck_hint(self, wf_repo, monkeypatch, capsys):
        # §step-selfcheck：block 返工同样带自查提示
        _write_state(wf_repo, sub_step=1)
        _write_trace(wf_repo, sub_step=1)
        mod = _load_hook()
        out, _err = _run_hook(
            mod, wf_repo, monkeypatch, capsys, judge=(False, "缺出处")
        )
        ctx = json.loads(out.strip())["hookSpecificOutput"]["additionalContext"]
        assert "STEP_DONE 前自查" in ctx
        # 步级化：子1 block 返工带的是**当前子步骤（子1）**的 checklist
        assert "本步自查：" in ctx and "who/pain/why-now" in ctx
