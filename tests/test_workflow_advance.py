"""workflow_advance.py 的 _handle_step_done 单测（编排 v2 commit 3）。

测子步骤逐步门控三条路径：pass 推进 sub_step_index / block 续轮 / 末步推进子阶段。
不真调 claude -p（monkeypatch engine.run_judge）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

DLWF_ROOT = Path("/home/admin/.dl-workflow")
ADV_PATH = DLWF_ROOT / "hooks" / "workflow_advance.py"

# workflow_advance.py 顶部 importlib 加载 engine；我们 spec 加载 hook 模块本身。
spec = importlib.util.spec_from_file_location("wf_advance", ADV_PATH)
adv = importlib.util.module_from_spec(spec)
sys.modules["wf_advance"] = adv
spec.loader.exec_module(adv)
eng = adv.engine  # hook 加载的 engine 模块


def _make_steps():
    """4 子步骤（mirror commit 4 understand:1）：1/2/3 gate 非 None，4 gate=None 自动过。"""
    return (
        eng.Step(
            kind="skill",
            ref="define-problem",
            purpose="逼问问题定义",
            input=None,
            record=True,
            gate="真实问题逼出",
        ),
        eng.Step(
            kind="tool",
            ref="codegraph/web",
            purpose="搜证据",
            input="step1.real_problem",
            record=True,
            gate="≥1 外部证据",
        ),
        eng.Step(
            kind="skill",
            ref="define-problem",
            purpose="一句话陈述",
            input="step1+step2",
            record=True,
            gate="≤1 句",
        ),
        eng.Step(
            kind="skill",
            ref="define-problem",
            purpose="读回确认",
            input="step3.statement",
            record=False,
            gate=None,
        ),
    )


def _patch_u1_with_steps(monkeypatch):
    """让 understand:1 返回带 sub_steps 的节点（commit 4 才真填，测试用 monkeypatch）。"""
    import dataclasses

    steps = _make_steps()
    orig = eng.get_node

    def fake(phase, sub):
        n = orig(phase, sub)
        if phase == "understand" and sub == 1:
            return dataclasses.replace(n, sub_steps=steps)
        return n

    monkeypatch.setattr(eng, "get_node", fake)
    return steps


def _write_state(tmp_path: Path, name: str, sub_step_index: int) -> Path:
    wf_dir = tmp_path / ".claude" / "workflows" / name
    wf_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "name": name,
        "phase": "understand",
        "index": 1,
        "sub_index": 1,
        "sub_total": 4,
        "node": "understand:1",
        "sub_step_index": sub_step_index,
        "gate": "pending",
        "node_attempts": 0,
        "session_id": "s",
        "branch": "wf/t",
        "worktree_path": str(tmp_path),
        "created_at": "x",
        "updated_at": "x",
        "history": [],
    }
    (wf_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return tmp_path


class _FakeMatch:
    """re.Match 替身，group(1) 返回 n 字符串。"""

    def __init__(self, n: int):
        self._n = n

    def group(self, i):
        return str(self._n) if i == 1 else None


class TestHandleStepDone:
    def test_pass_advances_sub_step_index(self, tmp_path, monkeypatch, capsys):
        # 非末步 gate pass -> sub_step_index 推进，不推进子阶段
        _patch_u1_with_steps(monkeypatch)
        _write_state(tmp_path, "t", sub_step_index=1)
        monkeypatch.setattr(eng, "run_judge", lambda *a, **k: (True, ""))
        state = eng.load_state(tmp_path, "t")
        rc = adv._handle_step_done(
            _FakeMatch(1), tmp_path, "t", state, "understand", 1, "输出", str(tmp_path)
        )
        assert rc == 0
        reread = eng.load_state(tmp_path, "t")
        assert reread["sub_step_index"] == 2
        assert reread["phase"] == "understand"  # 未推进子阶段
        assert reread["node_attempts"] == 0

    def test_block_continues_retry(self, tmp_path, monkeypatch, capsys):
        # gate block -> additionalContext 续轮，sub_step_index 不变，attempts++
        _patch_u1_with_steps(monkeypatch)
        _write_state(tmp_path, "t", sub_step_index=2)
        monkeypatch.setattr(eng, "run_judge", lambda *a, **k: (False, "没搜到证据"))
        state = eng.load_state(tmp_path, "t")
        rc = adv._handle_step_done(
            _FakeMatch(2), tmp_path, "t", state, "understand", 1, "输出", str(tmp_path)
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "WORKFLOW GATE 未通过" in out
        assert "子步骤 2" in out
        reread = eng.load_state(tmp_path, "t")
        assert reread["sub_step_index"] == 2  # 未推进
        assert reread["node_attempts"] == 1

    def test_last_step_advances_subphase(self, tmp_path, monkeypatch, capsys):
        # 末子步骤(4, gate=None 自动过) -> 推进子阶段 understand:1 -> understand:2
        _patch_u1_with_steps(monkeypatch)
        _write_state(tmp_path, "t", sub_step_index=4)
        # gate=None 不调 run_judge；但确保若调了不影响
        called = {"n": 0}
        monkeypatch.setattr(
            eng,
            "run_judge",
            lambda *a, **k: (called.__setitem__("n", called["n"] + 1), (True, ""))[1],
        )
        state = eng.load_state(tmp_path, "t")
        rc = adv._handle_step_done(
            _FakeMatch(4), tmp_path, "t", state, "understand", 1, "输出", str(tmp_path)
        )
        assert rc == 0
        reread = eng.load_state(tmp_path, "t")
        assert reread["phase"] == "understand"
        assert reread["sub_index"] == 2  # 子阶段推进
        assert reread["node"] == "understand:2"
        assert called["n"] == 0  # gate=None 没调 judge

    def test_mismatch_n_ignored(self, tmp_path, monkeypatch, capsys):
        # n != sub_step_index（跳步）-> 忽略不推进
        _patch_u1_with_steps(monkeypatch)
        _write_state(tmp_path, "t", sub_step_index=1)
        state = eng.load_state(tmp_path, "t")
        rc = adv._handle_step_done(
            _FakeMatch(3), tmp_path, "t", state, "understand", 1, "输出", str(tmp_path)
        )
        assert rc == 0
        reread = eng.load_state(tmp_path, "t")
        assert reread["sub_step_index"] == 1  # 未变

    def test_no_substeps_ignored(self, tmp_path, monkeypatch, capsys):
        # 节点无 sub_steps（understand:2）的 STEP_DONE 忽略
        # 不 patch（understand:2 原本无 sub_steps）
        _write_state(tmp_path, "t", sub_step_index=0)
        # 改 state 到 understand:2
        wf = tmp_path / ".claude" / "workflows" / "t" / "state.json"
        st = json.loads(wf.read_text())
        st["phase"] = "understand"
        st["sub_index"] = 2
        st["node"] = "understand:2"
        st["sub_step_index"] = 0
        wf.write_text(json.dumps(st), encoding="utf-8")
        state = eng.load_state(tmp_path, "t")
        state = eng.normalize_state(state)
        rc = adv._handle_step_done(
            _FakeMatch(1), tmp_path, "t", state, "understand", 2, "输出", str(tmp_path)
        )
        assert rc == 0
        # state 未变（sub_step_index 仍 0）
        reread = eng.load_state(tmp_path, "t")
        assert reread.get("sub_step_index", 0) == 0

    def test_gate_none_passes_without_judge(self, tmp_path, monkeypatch, capsys):
        # 子步骤 gate=None（自动过）不调 judge，非末步 -> sub_step_index++
        # 构造节点带一个 gate=None 的子步骤2，当前在步2
        import dataclasses

        steps = (
            eng.Step(
                kind="skill", ref="x", purpose="p1", input=None, record=True, gate="g1"
            ),
            eng.Step(
                kind="skill",
                ref="x",
                purpose="p2",
                input="step1",
                record=False,
                gate=None,
            ),
        )
        orig = eng.get_node

        def fake(phase, sub):
            n = orig(phase, sub)
            if phase == "understand" and sub == 1:
                return dataclasses.replace(n, sub_steps=steps)
            return n

        monkeypatch.setattr(eng, "get_node", fake)
        _write_state(tmp_path, "t", sub_step_index=2)
        called = {"n": 0}
        monkeypatch.setattr(
            eng,
            "run_judge",
            lambda *a, **k: (called.__setitem__("n", called["n"] + 1), (True, ""))[1],
        )
        state = eng.load_state(tmp_path, "t")
        rc = adv._handle_step_done(
            _FakeMatch(2), tmp_path, "t", state, "understand", 1, "输出", str(tmp_path)
        )
        assert rc == 0
        # 末步（2=总数）-> 推进子阶段
        reread = eng.load_state(tmp_path, "t")
        assert reread["sub_index"] == 2
        assert called["n"] == 0  # gate=None 没调 judge
