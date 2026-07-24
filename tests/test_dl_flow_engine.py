"""
dl-flow-engine.py 的单元测试（dl-workflow v0.1+）。

对应 designs/tui-state-machine-design.md §8.1（骨架阶段）。
通过 import 纯库函数测节点树推导（不 subprocess,纯函数快）。
advance_state 用 tmp state.json 测读写 + 推进。

覆盖：
- 节点标识推导（phase+sub -> node_id / current_node_id）
- 节点表完整性（每 phase 首节点存在;末节点 advance 正确）
- 推进链（understand:1 -> ... -> evolution:0 终结）
- 子阶段推进 vs 阶段推进（advance="sub"/"phase"/"done"）
- next_phase / is_gated_after / phase_index
- state.json 读写 + normalize_state 旧 state 兼容 + 不一致报错
- advance_state：子阶段推进 / 阶段推进（含闸门 passed）/ 终结
- gate_verdict_mech：NONE 通过 / 其他暂降级
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DLWF_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DLWF_ROOT))

# dl-flow-engine.py 文件名带连字符无法直接 import,用 importlib 加载。
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "dl_flow_engine", DLWF_ROOT / "dl-flow-engine.py"
)
eng = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
# 注册进 sys.modules 再 exec：Python 3.11 dataclass 探测类型注解时要查此表（dynamically
# loaded module 未注册会触发 AttributeError 'NoneType'.__dict__）。load_state 内 import
# subprocess 也依赖模块在 sys.modules 中。
sys.modules["dl_flow_engine"] = eng
_spec.loader.exec_module(eng)  # type: ignore[union-attr]


# ---------- 节点标识推导 ----------


class TestNodeId:
    def test_sub_zero_is_whole_phase(self):
        assert eng.node_id("execute", 0) == "execute:0"

    def test_sub_n_is_subphase(self):
        assert eng.node_id("understand", 3) == "understand:3"

    def test_current_node_id_whole_phase(self):
        # 无子阶段 phase sub_index=0 -> 整阶段节点
        assert eng.current_node_id("plan", 0) == "plan:0"

    def test_current_node_id_subphase(self):
        assert eng.current_node_id("understand", 2) == "understand:2"

    def test_get_node_unknown_raises(self):
        # 守 no silent fallback：未知节点报错暴露,不返回 None 猜
        with pytest.raises(KeyError, match="未知节点"):
            eng.get_node("nope", 0)

    def test_get_node_unknown_sub_raises(self):
        with pytest.raises(KeyError, match="未知节点"):
            eng.get_node("understand", 9)  # 只有 1-4


# ---------- 节点表完整性 ----------


class TestNodeTable:
    def test_every_phase_has_first_node(self):
        # 每 phase 首节点存在（有子阶段=sub=1,无=sub=0）
        for phase in eng.PHASES:
            first_sub = 1 if eng.sub_total(phase) > 0 else 0
            node = eng.get_node(phase, first_sub)
            assert node.phase == phase

    def test_last_node_advance(self):
        # 末 phase(evolution) 整阶段 advance="done"
        node = eng.get_node("evolution", 0)
        assert node.advance == "done"

    def test_subphases_advance_sub_except_last(self):
        # understand 子 1-3 advance="sub",子 4 advance="phase"
        for sub in (1, 2, 3):
            assert eng.get_node("understand", sub).advance == "sub"
        assert eng.get_node("understand", 4).advance == "phase"

    def test_whole_phase_advance_phase(self):
        # plan/execute/review 整阶段 advance="phase"
        for phase in ("plan", "execute", "review"):
            assert eng.get_node(phase, 0).advance == "phase"

    def test_node_id_matches_phase_sub(self):
        # node_id 与 Node.phase/sub 一致（防表错配）
        for nid, node in eng._NODES.items():
            assert nid == eng.node_id(node.phase, node.sub)

    def test_subphase_labels(self):
        # 子阶段标签从 _NODES 推导（单源,收口 understand 4 子阶段）
        labels = eng.subphase_labels("understand")
        assert labels == [
            "理解问题和背景",
            "明确目标和价值",
            "确定范围与约束",
            "定义成功标准和验收方式",
        ]

    def test_subphase_labels_no_sub(self):
        # 无子阶段 phase -> []
        assert eng.subphase_labels("plan") == []
        assert eng.subphase_labels("execute") == []

    def test_sub_total_derived_from_nodes(self):
        # sub_total 从 _NODES 推导（不再 _SUB_TOTAL 副本）,与 subphase_labels 长度一致
        assert eng.sub_total("understand") == 4
        assert len(eng.subphase_labels("understand")) == 4
        assert eng.sub_total("plan") == 0


# ---------- 推进链 ----------


class TestNextNode:
    def test_sub_advance_within_phase(self):
        # understand:1 -> understand:2（同 phase, sub+1）
        assert eng.next_node_id("understand", 1) == ("understand", 2)

    def test_last_subphase_advances_to_next_phase(self):
        # understand:4 -> plan:0（下一 phase 首节点,plan 无子阶段=sub=0）
        assert eng.next_node_id("understand", 4) == ("plan", 0)

    def test_whole_phase_advances_to_next_phase(self):
        # plan:0 -> execute:0
        assert eng.next_node_id("plan", 0) == ("execute", 0)

    def test_done_returns_none(self):
        # evolution:0 -> None（终结）
        assert eng.next_node_id("evolution", 0) is None

    def test_full_chain_understand_to_evolution(self):
        # 完整推进链：从 understand:1 一路推进到终结,节点序列正确
        chain: list[str] = []
        phase, sub = "understand", 1
        for _ in range(20):  # 上限防爆
            chain.append(eng.node_id(phase, sub))
            nxt = eng.next_node_id(phase, sub)
            if nxt is None:
                break
            phase, sub = nxt
        assert chain == [
            "understand:1",
            "understand:2",
            "understand:3",
            "understand:4",
            "plan:0",
            "execute:0",
            "review:0",
            "evolution:0",
        ]


# ---------- 阶段辅助 ----------


class TestPhaseHelpers:
    def test_phase_index_one_based(self):
        assert eng.phase_index("understand") == 1
        assert eng.phase_index("evolution") == 5

    def test_phase_index_unknown_raises(self):
        with pytest.raises(KeyError):
            eng.phase_index("nope")

    def test_next_phase(self):
        assert eng.next_phase("understand") == "plan"
        assert eng.next_phase("evolution") is None

    def test_is_gated_after(self):
        # design §3：understand/plan 末节点完成需闸门
        assert eng.is_gated_after("understand") is True
        assert eng.is_gated_after("plan") is True
        assert eng.is_gated_after("execute") is False

    def test_sub_total(self):
        assert eng.sub_total("understand") == 4
        assert eng.sub_total("plan") == 0


# ---------- normalize_state（旧 state 兼容 + 不一致报错）----------


class TestNormalizeState:
    def test_old_state_gets_node_field(self):
        # 旧 state 无 node/node_attempts -> 补默认
        old = {"phase": "understand", "sub_index": 1, "sub_total": 4}
        norm = eng.normalize_state(dict(old))
        assert norm["node"] == "understand:1"
        assert norm["node_attempts"] == 0

    def test_whole_phase_old_state(self):
        old = {"phase": "execute", "sub_index": 0}
        norm = eng.normalize_state(dict(old))
        assert norm["node"] == "execute:0"

    def test_inconsistent_node_raises(self):
        # 显式 node 与 phase+sub 推导不一致 -> 暴露,不猜（守 no silent fallback）
        bad = {"phase": "understand", "sub_index": 1, "node": "execute:0"}
        with pytest.raises(ValueError, match="不一致"):
            eng.normalize_state(bad)

    def test_consistent_node_kept(self):
        ok = {"phase": "plan", "sub_index": 0, "node": "plan:0"}
        norm = eng.normalize_state(dict(ok))
        assert norm["node"] == "plan:0"

    def test_sub_step_index_defaults_zero_no_steps(self):
        # §orchestration v2：无 sub_steps 节点 -> sub_step_index 补 0
        old = {"phase": "understand", "sub_index": 2}  # understand:2 无 sub_steps
        norm = eng.normalize_state(dict(old))
        assert norm["sub_step_index"] == 0
        # 整阶段节点同
        norm2 = eng.normalize_state({"phase": "plan", "sub_index": 0})
        assert norm2["sub_step_index"] == 0

    def test_sub_step_index_defaults_one_with_steps(self):
        # §orchestration v2：understand:1 有 sub_steps -> sub_step_index 缺省补 1（首步起步）
        norm = eng.normalize_state({"phase": "understand", "sub_index": 1})
        assert norm["sub_step_index"] == 1

    def test_sub_step_index_out_of_range_raises(self):
        # §orchestration v2：understand:1 有 4 子步骤，sub_step_index 越界 -> 报错暴露
        for bad in (0, 5):
            with pytest.raises(ValueError, match="越界"):
                eng.normalize_state(
                    {"phase": "understand", "sub_index": 1, "sub_step_index": bad}
                )

    def test_sub_step_index_in_range_ok(self):
        # 1..4 合法范围不报错
        for ok in (1, 2, 3, 4):
            norm = eng.normalize_state(
                {"phase": "understand", "sub_index": 1, "sub_step_index": ok}
            )
            assert norm["sub_step_index"] == ok


# ---------- §orchestration v2：Step dataclass + Node.sub_steps schema ----------


class TestStepDataclass:
    def test_step_construct_frozen(self):
        s = eng.Step(
            kind="skill",
            ref="define-problem",
            purpose="逼问",
            input=None,
            record=True,
            gate="q 覆盖三类",
        )
        assert s.kind == "skill"
        assert s.record is True
        assert s.gate == "q 覆盖三类"

    def test_step_frozen_immutable(self):
        s = eng.Step(
            kind="skill", ref="x", purpose="p", input=None, record=True, gate=None
        )
        with pytest.raises((AttributeError, Exception)):
            s.kind = "tool"  # frozen -> 不可改


class TestNodeSubStepsField:
    def test_default_none(self):
        # 未编排节点 sub_steps None（向后兼容）；understand:1 除外（commit 4 有 4 子步骤）
        for phase in eng.PHASES:
            total = eng.sub_total(phase)
            first_sub = 1 if total > 0 else 0
            node = eng.get_node(phase, first_sub)
            if node.phase == "understand" and node.sub == 1:
                assert node.sub_steps is not None  # 编排节点
            else:
                assert node.sub_steps is None

    def test_sub_steps_can_be_set(self):
        # 构造带 sub_steps 的节点（验证 schema 可用，不落 _NODES）
        s1 = eng.Step(
            kind="skill", ref="x", purpose="p1", input=None, record=True, gate="g1"
        )
        s2 = eng.Step(
            kind="tool", ref="y", purpose="p2", input="step1", record=False, gate=None
        )
        n = eng.Node(
            label="t",
            phase="understand",
            sub=1,
            skill="x",
            artifact=None,
            gate_mech=eng.GateMech.NONE,
            gate_rubric=None,
            advance="sub",
            sub_steps=(s1, s2),
        )
        assert n.sub_steps == (s1, s2)
        assert len(n.sub_steps) == 2


class TestSubStepHelpers:
    def test_sub_step_total_no_steps(self):
        assert eng.sub_step_total(eng.get_node("plan", 0)) == 0
        assert eng.sub_step_total(eng.get_node("understand", 2)) == 0  # 无编排节点
        # understand:1 有 4 子步骤（commit 4 切换）
        assert eng.sub_step_total(eng.get_node("understand", 1)) == 4

    def test_sub_step_total_with_steps(self):
        s1 = eng.Step(
            kind="skill", ref="x", purpose="p", input=None, record=True, gate=None
        )
        n = eng.Node(
            label="t",
            phase="understand",
            sub=1,
            skill="x",
            artifact=None,
            gate_mech=eng.GateMech.NONE,
            gate_rubric=None,
            advance="sub",
            sub_steps=(s1, s1, s1),
        )
        assert eng.sub_step_total(n) == 3

    def test_sub_step_at_valid(self):
        s1 = eng.Step(
            kind="skill", ref="a", purpose="p1", input=None, record=True, gate=None
        )
        s2 = eng.Step(
            kind="tool", ref="b", purpose="p2", input="step1", record=True, gate=None
        )
        n = eng.Node(
            label="t",
            phase="understand",
            sub=1,
            skill="x",
            artifact=None,
            gate_mech=eng.GateMech.NONE,
            gate_rubric=None,
            advance="sub",
            sub_steps=(s1, s2),
        )
        assert eng.sub_step_at(n, 1) is s1
        assert eng.sub_step_at(n, 2) is s2

    def test_sub_step_at_out_of_range_none(self):
        n = eng.get_node("plan", 0)  # 无 sub_steps
        assert eng.sub_step_at(n, 1) is None
        s1 = eng.Step(
            kind="skill", ref="a", purpose="p", input=None, record=True, gate=None
        )
        n2 = eng.Node(
            label="t",
            phase="understand",
            sub=1,
            skill="x",
            artifact=None,
            gate_mech=eng.GateMech.NONE,
            gate_rubric=None,
            advance="sub",
            sub_steps=(s1,),
        )
        assert eng.sub_step_at(n2, 0) is None  # 0 非法（1-based）
        assert eng.sub_step_at(n2, 2) is None  # 越界

    def test_step_needs_evidence(self):
        # gate 文本含 evidence/ 或 skill-trace -> True
        se = eng.Step(
            kind="skill",
            ref="x",
            purpose="p",
            input=None,
            record=True,
            gate="evidence/<name>.jsonl 含 skill-trace",
        )
        assert eng.step_needs_evidence(se) is True
        # 不含 -> False
        sn = eng.Step(
            kind="tool",
            ref="x",
            purpose="p",
            input=None,
            record=True,
            gate="≥1 外部证据连回项目",
        )
        assert eng.step_needs_evidence(sn) is False
        # gate=None -> False
        snone = eng.Step(
            kind="skill", ref="x", purpose="p", input=None, record=False, gate=None
        )
        assert eng.step_needs_evidence(snone) is False


# ---------- advance_state（读写 state.json）----------


def _write_state(tmp_path: Path, name: str, phase: str, sub: int) -> Path:
    """在 tmp repo 内建一个最小 state.json。"""
    wf_dir = tmp_path / ".claude" / "workflows" / name
    wf_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "name": name,
        "phase": phase,
        "index": eng.phase_index(phase),
        "sub_index": sub,
        "sub_total": eng.sub_total(phase),
        "node": eng.current_node_id(phase, sub),
        "gate": "passed" if (sub == 0 and phase != "understand") else "pending",
        "node_attempts": 0,
        "session_id": "test-sid",
        "branch": f"wf/{name}",
        "worktree_path": str(tmp_path),
        "created_at": "2026-07-23T00:00:00",
        "updated_at": "2026-07-23T00:00:00",
        "history": [],
    }
    (wf_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return tmp_path


class TestAdvanceState:
    def test_sub_advance(self, tmp_path):
        _write_state(tmp_path, "t", "understand", 1)
        state = eng.advance_state(tmp_path, "t", via="test")
        assert state["phase"] == "understand"
        assert state["sub_index"] == 2
        assert state["node"] == "understand:2"
        assert state["node_attempts"] == 0  # 新节点归零
        assert state["sub_total"] == 4

    def test_phase_advance_from_last_subphase(self, tmp_path):
        # understand:4 -> plan:0,且因 understand in GATED_AFTER -> plan gate=passed
        _write_state(tmp_path, "t", "understand", 4)
        state = eng.advance_state(tmp_path, "t", via="test")
        assert state["phase"] == "plan"
        assert state["sub_index"] == 0
        assert state["node"] == "plan:0"
        assert state["gate"] == "passed"  # 跨闸门后新 phase gate=passed
        assert state["sub_total"] == 0

    def test_phase_advance_no_gate(self, tmp_path):
        # execute:0 -> review:0,execute 不在 GATED_AFTER -> review gate=pending
        _write_state(tmp_path, "t", "execute", 0)
        state = eng.advance_state(tmp_path, "t", via="test")
        assert state["phase"] == "review"
        assert state["gate"] == "pending"

    def test_done_terminates(self, tmp_path):
        _write_state(tmp_path, "t", "evolution", 0)
        state = eng.advance_state(tmp_path, "t", via="test")
        assert state["gate"] == "done"
        assert state["phase"] == "evolution"  # 不再推进

    def test_advance_persists_to_disk(self, tmp_path):
        _write_state(tmp_path, "t", "understand", 1)
        eng.advance_state(tmp_path, "t", via="test")
        # 重读确认落盘
        reread = eng.load_state(tmp_path, "t")
        assert reread is not None
        assert reread["node"] == "understand:2"

    def test_advance_missing_state_raises(self, tmp_path):
        # state 缺失 -> 报错,不静默建（守 no silent fallback）
        with pytest.raises(FileNotFoundError):
            eng.advance_state(tmp_path, "nonexistent", via="test")


# ---------- write_gate_verdict（§8.6：gate-pass 写裁决记录）----------


class TestWriteGateVerdict:
    def test_writes_gate_record(self, tmp_path):
        # gate pass -> 写一笔 kind=gate 记录到 evidence/<name>.jsonl
        node = eng.get_node("understand", 4)  # 有 rubric 的末子阶段
        ok = eng.write_gate_verdict(tmp_path, "t", node, attempts=1, cwd=str(tmp_path))
        assert ok is True
        ev = eng._evidence_path(tmp_path, "t")
        lines = ev.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["kind"] == "gate"
        assert rec["node"] == "understand:4"
        assert rec["gate"] == "passed"
        assert rec["rubric"] == node.gate_rubric
        assert rec["attempts"] == 1
        assert rec["gate_mech"] == "artifact_exists"
        assert "ts" in rec

    def test_rubric_none_for_mech_only_node(self, tmp_path):
        # rubric=None 的节点（understand 子 2-3）-> rubric 字段 None（仅机械过）
        # 注：understand:1 现有验真 rubric（§define-problem-verify-gate），用 understand:2 测无 rubric
        node = eng.get_node("understand", 2)
        ok = eng.write_gate_verdict(tmp_path, "t", node, attempts=0, cwd=str(tmp_path))
        assert ok is True
        rec = json.loads(
            eng._evidence_path(tmp_path, "t").read_text(encoding="utf-8").strip()
        )
        assert rec["rubric"] is None
        assert rec["gate_mech"] == "none"

    def test_appends_multiple_records(self, tmp_path):
        # 多次 pass -> 多行追加（不覆盖）
        node = eng.get_node("plan", 0)
        eng.write_gate_verdict(tmp_path, "t", node, attempts=1, cwd=str(tmp_path))
        eng.write_gate_verdict(tmp_path, "t", node, attempts=3, cwd=str(tmp_path))
        lines = (
            eng._evidence_path(tmp_path, "t")
            .read_text(encoding="utf-8")
            .strip()
            .splitlines()
        )
        assert len(lines) == 2
        assert json.loads(lines[0])["attempts"] == 1
        assert json.loads(lines[1])["attempts"] == 3

    def test_commit_sha_from_git_repo(self, tmp_path):
        # 在 git repo 内 -> commit_sha 非空（stamp_commit_sha 用 git rev-parse HEAD）
        import subprocess

        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
        (tmp_path / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
        node = eng.get_node("execute", 0)
        eng.write_gate_verdict(tmp_path, "t", node, attempts=1, cwd=str(tmp_path))
        rec = json.loads(
            eng._evidence_path(tmp_path, "t").read_text(encoding="utf-8").strip()
        )
        assert rec["commit_sha"] != ""  # git repo 有 HEAD
        assert len(rec["commit_sha"]) == 40  # SHA 长度

    def test_commit_sha_empty_non_git(self, tmp_path):
        # 非 git -> commit_sha 空串（不阻断,降级）
        node = eng.get_node("review", 0)
        eng.write_gate_verdict(tmp_path, "t", node, attempts=1, cwd=str(tmp_path))
        rec = json.loads(
            eng._evidence_path(tmp_path, "t").read_text(encoding="utf-8").strip()
        )
        assert rec["commit_sha"] == ""


# ---------- §orchestration v2：understand:1 子步骤编排（替代过渡「≥3 Q/A」） ----------


class TestUnderstand1Orchestration:
    """understand:1 纯子步骤门控（删过渡 gate_rubric，4 子步骤逐步 STEP_DONE gate）。"""

    def test_gate_rubric_none(self):
        # 子阶段级 rubric 删除（被 sub_steps 逐步门控取代，Q4=删）
        assert eng.get_node("understand", 1).gate_rubric is None

    def test_has_4_sub_steps(self):
        node = eng.get_node("understand", 1)
        assert node.sub_steps is not None
        assert len(node.sub_steps) == 4

    def test_sub_steps_kinds(self):
        node = eng.get_node("understand", 1)
        kinds = [s.kind for s in node.sub_steps]
        assert kinds == ["skill", "tool", "skill", "skill"]

    def test_last_step_gate_none_autopass(self):
        # 子步骤4（读回确认）gate=None 自动过（交互步）
        node = eng.get_node("understand", 1)
        assert node.sub_steps[3].gate is None
        assert node.sub_steps[3].record is False  # 噪声步不记

    def test_record_steps(self):
        # 子步骤1/2/3 record=True（关键步落 evidence），子4 record=False
        node = eng.get_node("understand", 1)
        records = [s.record for s in node.sub_steps]
        assert records == [True, True, True, False]

    def test_first_step_no_input(self):
        node = eng.get_node("understand", 1)
        assert node.sub_steps[0].input is None  # 首步无依赖

    def test_step2_input_refs_step1(self):
        node = eng.get_node("understand", 1)
        assert node.sub_steps[1].input == "step1.real_problem"

    def test_skill_still_define_problem(self):
        assert eng.get_node("understand", 1).skill == "define-problem"

    def test_advance_still_sub(self):
        assert eng.get_node("understand", 1).advance == "sub"

    def test_other_subphases_no_steps(self):
        # understand:2-3 无 sub_steps（行为不变）
        assert eng.get_node("understand", 2).sub_steps is None
        assert eng.get_node("understand", 3).sub_steps is None


class TestRubricNeedsEvidence:
    """rubric_needs_evidence：节点级 rubric（understand:1 现已 None -> False）。

    注：understand:1 的 evidence 读取改由子步骤级 step_needs_evidence 驱动（commit 3 _step_evidence_artifact）。
    """

    def test_understand1_rubric_none_false(self):
        # understand:1 gate_rubric=None -> rubric_needs_evidence=False（节点级不再读 evidence）
        assert eng.rubric_needs_evidence(eng.get_node("understand", 1)) is False

    def test_no_rubric_node_false(self):
        # understand:2-3 无 rubric -> False
        assert eng.rubric_needs_evidence(eng.get_node("understand", 2)) is False
        assert eng.rubric_needs_evidence(eng.get_node("understand", 3)) is False

    def test_rubric_without_evidence_keyword_false(self):
        # plan:0 / understand:4 有 rubric 但不依赖 evidence.jsonl -> False
        assert eng.rubric_needs_evidence(eng.get_node("plan", 0)) is False
        assert eng.rubric_needs_evidence(eng.get_node("understand", 4)) is False


class TestStepNeedsEvidenceForU1:
    """understand:1 子步骤1/2/3 gate 含 evidence/ -> step_needs_evidence=True；子4 gate=None -> False。"""

    def test_record_steps_need_evidence(self):
        node = eng.get_node("understand", 1)
        # 子1/2/3 gate 含 "evidence/" -> True
        assert eng.step_needs_evidence(node.sub_steps[0]) is True
        assert eng.step_needs_evidence(node.sub_steps[1]) is True
        assert eng.step_needs_evidence(node.sub_steps[2]) is True

    def test_last_step_no_evidence(self):
        node = eng.get_node("understand", 1)
        # 子4 gate=None -> False
        assert eng.step_needs_evidence(node.sub_steps[3]) is False


class TestReadEvidence:
    """read_evidence：读 evidence/<name>.jsonl 全文；缺失/失败返回 None。"""

    def test_missing_returns_none(self, tmp_path):
        # 文件不存在 -> None（judge 降级判 block，不默认放行）
        assert eng.read_evidence(tmp_path, "nope") is None

    def test_returns_file_content(self, tmp_path):
        # 文件存在 -> 返回全文（含模型写的 skill-trace/conclusion + gate 记录）
        p = eng._evidence_path(tmp_path, "t")
        p.parent.mkdir(parents=True, exist_ok=True)
        records = (
            '{"kind":"skill-trace","step":1,"q":"谁有这问题？","a":"..."}\n'
            '{"kind":"conclusion","problem_is_real":true,"reason":"..."}\n'
        )
        p.write_text(records, encoding="utf-8")
        assert eng.read_evidence(tmp_path, "t") == records

    def test_read_failure_returns_none(self, tmp_path):
        # 读失败（OSError）-> None（no silent fallback，不抛）
        # 让 evidence 路径是个目录 -> read_text 抛 IsADirectoryError(OSError 子类)
        p = eng._evidence_path(tmp_path, "t")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.mkdir()
        assert eng.read_evidence(tmp_path, "t") is None


# ---------- gate_verdict_mech（骨架阶段;仅 NONE 通过,其他降级）----------


class TestGateVerdictMech:
    def test_none_passes(self):
        node = eng.get_node("understand", 1)  # gate_mech=NONE
        assert eng.gate_verdict_mech(node, project_root=Path(".")) is None

    def test_no_project_root_degrades(self):
        # 无 project_root -> 机械项降级放行（宁纵勿枉,同 codegraph_gate 非 git）
        node = eng.get_node("understand", 4)  # ARTIFACT_EXISTS
        assert eng.gate_verdict_mech(node, project_root=None) is None

    def test_artifact_exists_not_yet_impl(self):
        # ARTIFACT_EXISTS 文件查找未实现（§8.3）-> 暂降级 None,不误 block
        node = eng.get_node("plan", 0)
        assert eng.gate_verdict_mech(node, project_root=Path(".")) is None


# ---------- _strip_json_fence / _extract_judge_result（judge 输出解析）----------


class TestJudgeParse:
    def test_strip_fence_json_block(self):
        assert eng._strip_json_fence('```json\n{"pass": true}\n```') == '{"pass": true}'

    def test_strip_fence_plain(self):
        assert eng._strip_json_fence('```\n{"pass": false}\n```') == '{"pass": false}'

    def test_strip_no_fence(self):
        assert eng._strip_json_fence('{"pass": true}') == '{"pass": true}'

    def test_extract_pass_with_reason(self):
        v = eng._extract_judge_result('{"pass": false, "reason": "缺边界"}')
        assert v == {"pass": False, "reason": "缺边界"}

    def test_extract_pass_no_reason_defaults_empty(self):
        v = eng._extract_judge_result('{"pass": true}')
        assert v == {"pass": True, "reason": ""}

    def test_extract_with_surrounding_text(self):
        # 模型前后带解释 -> 取 {...}
        v = eng._extract_judge_result('结论如下：\n{"pass": true}\n以上。')
        assert v == {"pass": True, "reason": ""}

    def test_extract_fenced(self):
        v = eng._extract_judge_result('```json\n{"pass": false, "reason": "x"}\n```')
        assert v == {"pass": False, "reason": "x"}

    def test_extract_no_json_returns_none(self):
        assert eng._extract_judge_result("没有JSON") is None

    def test_extract_no_pass_key_returns_none(self):
        assert eng._extract_judge_result('{"reason": "x"}') is None


# ---------- run_judge（mock subprocess.run;不真调 claude -p）----------


def _fake_run_factory(returncode: int, stdout: str):
    """造一个假的 subprocess.run 替换函数。stdout 末行应是 {\"is_error\":...,\"result\":\"...\"}。"""
    import types

    def _fake(cmd, **kw):
        r = types.SimpleNamespace()
        r.returncode = returncode
        r.stdout = stdout
        r.stderr = ""
        return r

    return _fake


def _result_line(result_text: str, is_error: bool = False) -> str:
    """造 claude -p --output-format json 的末行 result JSON。"""
    return json.dumps({"is_error": is_error, "result": result_text})


class TestRunJudge:
    def test_pass(self, monkeypatch):
        monkeypatch.setattr(
            eng.subprocess, "run", _fake_run_factory(0, _result_line('{"pass": true}'))
        )
        ok, reason = eng.run_judge("rubric", "节点", "模型输出")
        assert ok is True
        assert reason == ""

    def test_block_with_reason(self, monkeypatch):
        monkeypatch.setattr(
            eng.subprocess,
            "run",
            _fake_run_factory(
                0, _result_line('{"pass": false, "reason": "缺成功标准"}')
            ),
        )
        ok, reason = eng.run_judge("rubric", "节点", "模型输出")
        assert ok is False
        assert "缺成功标准" in reason

    def test_fenced_output(self, monkeypatch):
        # 模型把 JSON 包代码块
        monkeypatch.setattr(
            eng.subprocess,
            "run",
            _fake_run_factory(0, _result_line('```json\n{"pass": true}\n```')),
        )
        ok, _ = eng.run_judge("rubric", "节点", "模型输出")
        assert ok is True

    def test_non_json_result_blocks(self, monkeypatch):
        # result 不是合法 JSON -> 降级 block（no silent fallback,不默认放行）
        monkeypatch.setattr(
            eng.subprocess, "run", _fake_run_factory(0, _result_line("我看挺好的"))
        )
        ok, reason = eng.run_judge("rubric", "节点", "模型输出")
        assert ok is False
        assert "非合法 JSON" in reason

    def test_api_error_blocks(self, monkeypatch):
        # claude -p 退出非 0 -> block
        monkeypatch.setattr(eng.subprocess, "run", _fake_run_factory(2, "boom"))
        ok, reason = eng.run_judge("rubric", "节点", "模型输出")
        assert ok is False
        assert "退出码" in reason

    def test_no_result_line_blocks(self, monkeypatch):
        # stdout 无 result JSON 行 -> block
        monkeypatch.setattr(
            eng.subprocess, "run", _fake_run_factory(0, "乱七八糟没有json行")
        )
        ok, _ = eng.run_judge("rubric", "节点", "模型输出")
        assert ok is False

    def test_is_error_blocks(self, monkeypatch):
        # is_error=true -> block
        monkeypatch.setattr(
            eng.subprocess,
            "run",
            _fake_run_factory(0, _result_line("出错了", is_error=True)),
        )
        ok, reason = eng.run_judge("rubric", "节点", "模型输出")
        assert ok is False
        assert "出错" in reason

    def test_timeout_blocks(self, monkeypatch):
        import subprocess as sp

        def _raise(cmd, **kw):
            raise sp.TimeoutExpired(cmd=cmd, timeout=1)

        monkeypatch.setattr(eng.subprocess, "run", _raise)
        ok, reason = eng.run_judge("rubric", "节点", "模型输出")
        assert ok is False
        assert "TimeoutExpired" in reason

    def test_artifact_content_passed_to_prompt(self, monkeypatch):
        # 产物内容应进 prompt
        captured = {}
        fake_ok = _fake_run_factory(0, _result_line('{"pass": true}'))

        def _cap(cmd, **kw):
            captured["prompt"] = cmd
            return fake_ok(cmd, **kw)

        monkeypatch.setattr(eng.subprocess, "run", _cap)
        eng.run_judge("rubric", "节点", "模型输出", artifact_content="产物正文")
        assert "产物正文" in captured["prompt"][-1]


# ---------- run_gate（compound 短路）----------


class TestRunGate:
    def test_no_rubric_passes_without_judge(self, monkeypatch):
        # understand:2 无 rubric -> 不调 judge,机械项 NONE 过 -> pass
        # 用计数器证明 judge 没被调
        # 注：understand:1 现有验真 rubric 会调 judge，故用 understand:2 测无 rubric 路径
        called = {"n": 0}

        def _spy(cmd, **kw):
            called["n"] += 1
            return _fake_run_factory(0, _result_line('{"pass": true}'))(cmd, **kw)

        monkeypatch.setattr(eng.subprocess, "run", _spy)
        node = eng.get_node("understand", 2)
        ok, _ = eng.run_gate(node, "输出")
        assert ok is True
        assert called["n"] == 0  # judge 没被调

    def test_rubric_calls_judge_pass(self, monkeypatch):
        # plan:0 有 rubric,机械降级过 -> 跑 judge -> pass
        monkeypatch.setattr(
            eng.subprocess, "run", _fake_run_factory(0, _result_line('{"pass": true}'))
        )
        node = eng.get_node("plan", 0)
        ok, _ = eng.run_gate(node, "一份计划")
        assert ok is True

    def test_rubric_calls_judge_block(self, monkeypatch):
        monkeypatch.setattr(
            eng.subprocess,
            "run",
            _fake_run_factory(0, _result_line('{"pass": false, "reason": "没步骤"}')),
        )
        node = eng.get_node("plan", 0)
        ok, reason = eng.run_gate(node, "空话")
        assert ok is False
        assert "没步骤" in reason

    def test_mech_block_short_circuits_judge(self, monkeypatch):
        # 机械项不过 -> 短路,不跑 judge。当前机械项未实现文件查找,
        # 故用 mock 强制 gate_verdict_mech 返回 block 验证短路。
        called = {"n": 0}

        def _spy(cmd, **kw):
            called["n"] += 1
            return _fake_run_factory(0, _result_line('{"pass": true}'))(cmd, **kw)

        monkeypatch.setattr(eng.subprocess, "run", _spy)
        monkeypatch.setattr(
            eng, "gate_verdict_mech", lambda n, project_root=None: "产物缺失：plan.md"
        )
        node = eng.get_node("plan", 0)
        ok, reason = eng.run_gate(node, "输出")
        assert ok is False
        assert "产物缺失" in reason
        assert called["n"] == 0  # judge 没被调（短路）


# ---------- CLI 冒烟（status/current 输出合法）----------


def _init_git(tmp_path: Path) -> Path:
    """在 tmp_path 建最小 git repo,让 CLI 的 resolve_project_root 能反查到。

    同 test_codegraph_gate.py 做法。engine CLI 走 git rev-parse 反查主 repo 根,
    故 CLI 测试须有 git repo;直接传 project_root 的库测试（advance_state）不必。
    """
    import subprocess

    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    return tmp_path


class TestCLI:
    def test_current_outputs_valid_json(self, tmp_path, capsys):
        _init_git(tmp_path)
        _write_state(tmp_path, "t", "understand", 2)
        rc = eng.main(["current", "t", "--cwd", str(tmp_path)])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["node"] == "understand:2"
        assert out["label"] == "明确目标和价值"
        assert out["gate_rubric"] is None  # 子阶段无语义审

    def test_status_prints_label(self, tmp_path, capsys):
        _init_git(tmp_path)
        _write_state(tmp_path, "t", "plan", 0)
        rc = eng.main(["status", "t", "--cwd", str(tmp_path)])
        assert rc == 0
        assert "生成执行计划" in capsys.readouterr().out

    def test_meta_outputs_constants_json(self, capsys):
        # meta 不需 git repo/name（静态常量）;供 wf-lib.sh 缓存删 bash 副本
        rc = eng.main(["meta"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["phases"] == ["understand", "plan", "execute", "review", "evolution"]
        assert out["phase_labels"]["understand"] == "理解和求证问题"
        assert out["gated_after"] == ["understand", "plan"]  # 保序（tuple 定义顺序）
        assert out["subphases"]["understand"] == [
            "理解问题和背景",
            "明确目标和价值",
            "确定范围与约束",
            "定义成功标准和验收方式",
        ]
        assert out["subphases"]["plan"] == []
        assert out["sub_total"]["understand"] == 4
        assert out["sub_total"]["plan"] == 0
