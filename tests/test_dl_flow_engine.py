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

    def test_minor_key_on_subphases(self):
        # understand 4 子阶段各持英文标识(首字母大写,evidence minor_stage 值)
        assert eng._NODES["understand:1"].minor_key == "ProblemContext"
        assert eng._NODES["understand:2"].minor_key == "GoalsAndValue"
        assert eng._NODES["understand:3"].minor_key == "ScopeAndConstraints"
        assert eng._NODES["understand:4"].minor_key == "SuccessCriteria"

    def test_minor_key_none_for_whole_phase(self):
        # 无子阶段节点(sub=0)无 minor_key
        assert eng._NODES["plan:0"].minor_key is None
        assert eng._NODES["execute:0"].minor_key is None

    def test_minor_key_map(self):
        # minor_key -> 中文 label(single source,viewer 英转中用)
        m = eng.minor_key_map()
        assert m["ProblemContext"] == "理解问题和背景"
        assert m["SuccessCriteria"] == "定义成功标准和验收方式"
        assert len(m) == 4


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
        # §orchestration v2 + 2026-07-26 重设计：understand:1 有 6 子步骤，越界 -> 报错暴露
        for bad in (0, 7):
            with pytest.raises(ValueError, match="越界"):
                eng.normalize_state(
                    {"phase": "understand", "sub_index": 1, "sub_step_index": bad}
                )

    def test_sub_step_index_in_range_ok(self):
        # 1..6 合法范围不报错
        for ok in (1, 2, 3, 4, 5, 6):
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
        # 未编排节点 sub_steps None（向后兼容）；understand:1 除外（有 6 子步骤）
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


class TestStep456Redesign:
    """2026-07-26 重设计（designs/step5-step6-statement-readback-redesign-design.md）：
    子4 加④处置问题集；子5 一句话陈述→归一化陈述（裁决传导）；子6→带证据读回确认。"""

    def _steps(self):
        node = eng.get_node("understand", 1)
        assert node.sub_steps is not None and len(node.sub_steps) == 6
        return node.sub_steps

    def test_step4_disposition_in_purpose_and_gate(self):
        s4 = self._steps()[3]
        assert "处置问题集" in s4.purpose
        assert "处置后问题集与 verdict 逐项一致" in s4.gate

    def test_step5_normalization_verdict_consistency(self):
        s5 = self._steps()[4]
        assert "归一化陈述" in s5.purpose
        assert s5.input == "step4.disposed_problem_set"
        # 裁决不传导判 block：陈述集与 verdict 一致性是质量判据
        assert "裁决不传导" in s5.gate
        assert "证伪项不得出现在" in s5.gate

    def test_step6_readback_with_evidence_gate_none(self):
        s6 = self._steps()[5]
        assert s6.gate is None  # 交互步不跑 judge（trace 存在即过）
        assert "证据指针" in s6.purpose
        assert "证据不足" in s6.purpose  # 不确定性须显式暴露给用户裁决

    def test_all_six_steps_record_true(self):
        # 末步 record=True 是 Stop 门控的完成触发信号（3a 潜在洞修复）
        assert all(s.record for s in self._steps())


class TestSubStepHelpers:
    def test_sub_step_total_no_steps(self):
        assert eng.sub_step_total(eng.get_node("plan", 0)) == 0
        assert eng.sub_step_total(eng.get_node("understand", 2)) == 0  # 无编排节点
        # understand:1 有 6 子步骤（2026-07-26 重设计：验真拆双向取证+质检裁决）
        assert eng.sub_step_total(eng.get_node("understand", 1)) == 6

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
    """understand:1 纯子步骤门控（删过渡 gate_rubric，6 子步骤逐步 STEP_DONE gate）。

    2026-07-26 重设计（designs/step3-verify-redesign-design.md）：旧子3「验真」拆为
    子3 双向取证 + 子4 质检裁决（5 步 -> 6 步），原子4/5 顺移为子5/6。
    """

    def test_gate_rubric_none(self):
        # 子阶段级 rubric 删除（被 sub_steps 逐步门控取代，Q4=删）
        assert eng.get_node("understand", 1).gate_rubric is None

    def test_has_6_sub_steps(self):
        node = eng.get_node("understand", 1)
        assert node.sub_steps is not None
        assert len(node.sub_steps) == 6

    def test_sub_steps_kinds(self):
        node = eng.get_node("understand", 1)
        kinds = [s.kind for s in node.sub_steps]
        assert kinds == ["skill", "skill", "tool", "tool", "skill", "skill"]

    def test_step2_refs_causal_inference(self):
        # 子步骤2（拆解深挖）invoke causal-inference-root-cause（2026-07-25 设计决议）
        node = eng.get_node("understand", 1)
        assert node.sub_steps[1].ref == "causal-inference-root-cause"

    def test_last_step_gate_none_autopass(self):
        # 子步骤6（读回确认）gate=None 自动过（trace 存在即过，不跑 judge）
        node = eng.get_node("understand", 1)
        assert node.sub_steps[5].gate is None
        # §substep-gate-at-stop：record=True——Stop 门控以新 trace 为唯一完成触发，
        # record=False 的末步永无触发信号、子阶段卡死（3a 潜在洞）
        assert node.sub_steps[5].record is True

    def test_record_steps(self):
        # 子步骤1-6 全 record=True（子6 记用户确认，作完成触发 + 裁决留痕）
        node = eng.get_node("understand", 1)
        records = [s.record for s in node.sub_steps]
        assert records == [True, True, True, True, True, True]

    def test_first_step_no_input(self):
        node = eng.get_node("understand", 1)
        assert node.sub_steps[0].input is None  # 首步无依赖

    def test_step2_input_refs_step1(self):
        node = eng.get_node("understand", 1)
        assert node.sub_steps[1].input == "step1.real_problem"

    def test_step3_input_refs_step2(self):
        # 双向取证针对子2 拆出的原子问题清单
        node = eng.get_node("understand", 1)
        assert node.sub_steps[2].input == "step2.problem_list"

    def test_input_chain_after_redesign(self):
        # 2026-07-26 重设计输入链：子4 吃子3 取证记录，
        # 子5 归一化陈述只吃子4 处置后问题集（v2.8 收窄，原 step2+step4），子6 确认吃子5
        node = eng.get_node("understand", 1)
        assert node.sub_steps[3].input == "step3.traces"
        assert node.sub_steps[4].input == "step4.disposed_problem_set"
        assert node.sub_steps[5].input == "step5.statements"

    def test_step3_bidirectional_evidence(self):
        # 子3 双向取证（designs/step3-verify-redesign-design.md）：
        # 证伪优先 + 五层源 + 禁 tavily/WebSearch（用户硬约束）+ codegraph 新鲜度前置
        node = eng.get_node("understand", 1)
        s3 = node.sub_steps[2]
        assert s3.kind == "tool"
        for needle in (
            "证伪优先",
            "可检验化",
            "五层源",
            "新鲜度",
            "禁 tavily_search/WebSearch",
        ):
            assert needle in s3.purpose, f"子3 purpose 缺 {needle}"
        for needle in (
            "sub_step==3",
            "反证查询时序先于支持查询",
            "训练记忆冒充外部证据",
        ):
            assert needle in s3.gate, f"子3 gate 缺 {needle}"
        assert "tavily" not in s3.ref

    def test_step4_quality_verdict(self):
        # 子4 质检裁决：三关质检 + 条件触发红队（独立上下文）+ 四态 verdict（证据不足合法）
        node = eng.get_node("understand", 1)
        s4 = node.sub_steps[3]
        assert s4.kind == "tool"
        for needle in ("三关质检", "红队", "独立上下文", "四态", "证据不足"):
            assert needle in s4.purpose, f"子4 purpose 缺 {needle}"
        for needle in ("sub_step==4", "红队触发条件", "推理链"):
            assert needle in s4.gate, f"子4 gate 缺 {needle}"

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
    """understand:1 子步骤1-5 gate 含 evidence/ -> step_needs_evidence=True；子6 gate=None -> False。"""

    def test_record_steps_need_evidence(self):
        node = eng.get_node("understand", 1)
        # 子1/2/3/4/5 gate 含 "evidence/" -> True
        for i in range(5):
            assert eng.step_needs_evidence(node.sub_steps[i]) is True

    def test_last_step_no_evidence(self):
        node = eng.get_node("understand", 1)
        # 子6 gate=None -> False
        assert eng.step_needs_evidence(node.sub_steps[5]) is False


# ---------- §step-advance-on-submit：sub_step_has_trace + gate_and_advance_sub_step ----------


def _write_state_full(
    tmp_path: Path, name: str, phase: str, sub: int, sub_step: int = 0
) -> Path:
    """建含 sub_step_index 的完整 state（供推进测试）。"""
    wf_dir = tmp_path / ".claude" / "workflows" / name
    wf_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "name": name,
        "phase": phase,
        "index": eng.phase_index(phase),
        "sub_index": sub,
        "sub_total": eng.sub_total(phase),
        "node": eng.current_node_id(phase, sub),
        "sub_step_index": sub_step,
        "gate": "pending",
        "node_attempts": 0,
        "session_id": "s",
        "branch": f"wf/{name}",
        "worktree_path": str(tmp_path),
        "created_at": "x",
        "updated_at": "x",
        "history": [],
    }
    (wf_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return tmp_path


def _write_evidence(tmp_path: Path, name: str, records: list[str]) -> Path:
    """写 evidence.jsonl（每条一行 JSON 字符串）。"""
    p = eng._evidence_path(tmp_path, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(records) + "\n", encoding="utf-8")
    return p


class TestSubStepHasTrace:
    """sub_step_has_trace：evidence 含 sub_step==N 的 skill-trace 即 True。"""

    def test_no_file_false(self, tmp_path):
        assert eng.sub_step_has_trace(tmp_path, "t", 1) is False

    def test_has_matching_trace(self, tmp_path):
        _write_evidence(
            tmp_path,
            "t",
            [
                '{"kind":"skill-trace","major_stage":"Understand","minor_stage":"ProblemContext","sub_step":1,"purpose":"p","q":["q"],"a":["a"]}',
            ],
        )
        assert eng.sub_step_has_trace(tmp_path, "t", 1) is True

    def test_no_matching_sub_step(self, tmp_path):
        # 有 sub_step=1 的 trace，查 sub_step=2 -> False
        _write_evidence(
            tmp_path,
            "t",
            [
                '{"kind":"skill-trace","major_stage":"Understand","minor_stage":"ProblemContext","sub_step":1,"purpose":"p","q":["q"],"a":["a"]}',
            ],
        )
        assert eng.sub_step_has_trace(tmp_path, "t", 2) is False

    def test_ignores_non_skill_trace(self, tmp_path):
        # kind=gate / kind=conclusion 不算
        _write_evidence(
            tmp_path,
            "t",
            [
                '{"kind":"gate","sub_step":1}',
                '{"kind":"conclusion","sub_step":1}',
            ],
        )
        assert eng.sub_step_has_trace(tmp_path, "t", 1) is False

    def test_old_step_field_ignored(self, tmp_path):
        # 旧字段 step（非 sub_step）不算（E4 统一 sub_step）
        _write_evidence(
            tmp_path,
            "t",
            [
                '{"kind":"skill-trace","step":1,"q":"q","a":"a"}',
            ],
        )
        assert eng.sub_step_has_trace(tmp_path, "t", 1) is False


class TestGateAndAdvanceSubStep:
    """gate_and_advance_sub_step：gate+推进合一（3a）。"""

    def test_gate_pass_advances_sub_step(self, tmp_path, monkeypatch):
        # 非末步 gate pass -> sub_step_index++
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        monkeypatch.setattr(eng, "run_judge", lambda *a, **k: (True, ""))
        node = eng.get_node("understand", 1)
        advanced, reason, new_state = eng.gate_and_advance_sub_step(
            tmp_path, "t", node, 1
        )
        assert advanced is True
        assert reason == ""
        reread = eng.load_state(tmp_path, "t")
        assert reread["sub_step_index"] == 2
        assert reread["phase"] == "understand"  # 未推进子阶段

    def test_gate_block_no_advance(self, tmp_path, monkeypatch):
        # gate block -> 不推进，返回 reason
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        monkeypatch.setattr(eng, "run_judge", lambda *a, **k: (False, "没搜到证据"))
        node = eng.get_node("understand", 1)
        advanced, reason, new_state = eng.gate_and_advance_sub_step(
            tmp_path, "t", node, 2
        )
        assert advanced is False
        assert "没搜到证据" in reason
        reread = eng.load_state(tmp_path, "t")
        assert reread["sub_step_index"] == 1  # 未变

    def test_gate_none_passes_without_judge(self, tmp_path, monkeypatch):
        # 子6 gate=None 自动过，不调 judge；末步 -> 推进子阶段
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=6)
        called = {"n": 0}

        def _spy(*a, **k):
            called["n"] += 1
            return (True, "")

        monkeypatch.setattr(eng, "run_judge", _spy)
        node = eng.get_node("understand", 1)
        advanced, reason, new_state = eng.gate_and_advance_sub_step(
            tmp_path, "t", node, 6
        )
        assert advanced is True
        assert called["n"] == 0  # gate=None 没调 judge
        reread = eng.load_state(tmp_path, "t")
        assert reread["sub_index"] == 2  # 推进到 understand:2
        assert reread["node"] == "understand:2"

    def test_no_evidence_blocks(self, tmp_path, monkeypatch):
        # evidence 缺 -> judge 拿 None artifact -> 判 block（no silent fallback）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        # run_judge 收到 artifact=None 时应判 block；用真实 run_judge 行为模拟
        captured = {}

        def _spy(rubric, label, output, artifact_content=None):
            captured["artifact"] = artifact_content
            return (False, "evidence 缺失")

        monkeypatch.setattr(eng, "run_judge", _spy)
        node = eng.get_node("understand", 1)
        advanced, reason, _ = eng.gate_and_advance_sub_step(tmp_path, "t", node, 1)
        assert advanced is False
        assert captured["artifact"] is None  # evidence 缺传 None
        assert "evidence 缺失" in reason

    def test_passes_evidence_to_judge(self, tmp_path, monkeypatch):
        # gate 跑 judge 时 artifact_content = evidence 全文
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        _write_evidence(
            tmp_path,
            "t",
            [
                '{"kind":"skill-trace","major_stage":"Understand","minor_stage":"ProblemContext","sub_step":1,"purpose":"p","q":["q"],"a":["a"]}',
            ],
        )
        captured = {}

        def _spy(rubric, label, output, artifact_content=None):
            captured["artifact"] = artifact_content
            return (True, "")

        monkeypatch.setattr(eng, "run_judge", _spy)
        node = eng.get_node("understand", 1)
        eng.gate_and_advance_sub_step(tmp_path, "t", node, 1)
        assert captured["artifact"] is not None
        assert "skill-trace" in captured["artifact"]


class TestSubStepBlockEscalation:
    """§E7：sub_step block 计 node_attempts；连续 block 达阈值升级用户裁决。"""

    def test_block_increments_node_attempts(self, tmp_path, monkeypatch):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        monkeypatch.setattr(eng, "run_judge", lambda *a, **k: (False, "不达标"))
        node = eng.get_node("understand", 1)
        for expected in (1, 2, 3):
            advanced, reason, new_state = eng.gate_and_advance_sub_step(
                tmp_path, "t", node, 1
            )
            assert advanced is False
            assert new_state["node_attempts"] == expected  # 返回计数后 state
            assert eng.load_state(tmp_path, "t")["node_attempts"] == expected  # 已落盘
        assert expected == eng.SUB_STEP_BLOCK_ESCALATE  # 阈值语义锚定

    def test_pass_resets_node_attempts(self, tmp_path, monkeypatch):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        monkeypatch.setattr(eng, "run_judge", lambda *a, **k: (False, "x"))
        node = eng.get_node("understand", 1)
        eng.gate_and_advance_sub_step(tmp_path, "t", node, 1)
        monkeypatch.setattr(eng, "run_judge", lambda *a, **k: (True, ""))
        eng.gate_and_advance_sub_step(tmp_path, "t", node, 1)
        assert eng.load_state(tmp_path, "t")["node_attempts"] == 0

    def test_force_pass_advances_and_records(self, tmp_path):
        # /dl step-pass：写 manual-step-pass 裁决记录 + 按 pass 路径推进 + 计数归零
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        st = eng.load_state(tmp_path, "t")
        st["node_attempts"] = 3
        eng.save_state(tmp_path, "t", st)
        ok, msg = eng.force_pass_sub_step(tmp_path, "t", str(tmp_path))
        assert ok is True
        reread = eng.load_state(tmp_path, "t")
        assert reread["sub_step_index"] == 2
        assert reread["node_attempts"] == 0
        # 裁决记录落 evidence（via + sub_step + attempts 留痕）
        text = eng.read_evidence(tmp_path, "t")
        rec = json.loads(text.strip().splitlines()[-1])
        assert rec["kind"] == "gate"
        assert rec["via"] == "manual-step-pass"
        assert rec["sub_step"] == 1
        assert rec["attempts"] == 3

    def test_force_pass_last_step_advances_subphase(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=6)
        ok, msg = eng.force_pass_sub_step(tmp_path, "t", str(tmp_path))
        assert ok is True
        reread = eng.load_state(tmp_path, "t")
        assert reread["sub_index"] == 2
        assert reread["node"] == "understand:2"

    def test_force_pass_rejects_node_without_sub_steps(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 2)  # understand:2 无 sub_steps
        ok, msg = eng.force_pass_sub_step(tmp_path, "t", str(tmp_path))
        assert ok is False
        assert "无子步骤" in msg


class TestResetSubStep:
    """reset_sub_step（/dl step-reset <n>）：回退到子步骤 n 反复重测。"""

    def test_reset_to_step2_clears_state_and_evidence(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=3)
        st = eng.load_state(tmp_path, "t")
        st["node_attempts"] = 2
        # 游标 #1 是前序留痕须保留，#2/#3 须清
        st["last_judged_trace"] = {
            "understand:1#1": "a",
            "understand:1#2": "b",
            "understand:1#3": "c",
        }
        eng.save_state(tmp_path, "t", st)
        _write_evidence(
            tmp_path,
            "t",
            [
                _trace_line(1),
                _trace_line(2, "old"),
                _trace_line(3),
                '{"kind":"gate","node":"understand:1","gate":"passed","via":"manual-step-pass","sub_step":2}',
                '{"kind":"gate","node":"understand:1","gate":"passed"}',  # 节点级无 sub_step -> 保留
            ],
        )
        ok, msg = eng.reset_sub_step(tmp_path, "t", 2)
        assert ok is True
        st = eng.load_state(tmp_path, "t")
        assert st["sub_step_index"] == 2
        assert st["node_attempts"] == 0
        assert st["last_judged_trace"] == {"understand:1#1": "a"}
        # evidence：sub_step>=2 的 trace/gate 行被删，前序与节点级裁决保留
        lines = [
            json.loads(line)
            for line in eng.read_evidence(tmp_path, "t").strip().splitlines()
        ]
        assert [r.get("sub_step") for r in lines if r["kind"] == "skill-trace"] == [1]
        gates = [r for r in lines if r["kind"] == "gate"]
        assert len(gates) == 1 and "sub_step" not in gates[0]

    def test_reset_clears_cursor_so_new_trace_retriggers(self, tmp_path):
        # 回退后游标已清：模型再写同内容 trace 也会被判「有新产出」，不静默跳过
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=2)
        st = eng.load_state(tmp_path, "t")
        st["last_judged_trace"] = {"understand:1#2": "old-hash"}
        eng.save_state(tmp_path, "t", st)
        ok, _ = eng.reset_sub_step(tmp_path, "t", 2)
        assert ok is True
        assert eng.load_state(tmp_path, "t")["last_judged_trace"] == {}

    def test_reset_rejects_node_without_sub_steps(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 2)
        ok, msg = eng.reset_sub_step(tmp_path, "t", 2)
        assert ok is False
        assert "无子步骤" in msg

    def test_reset_rejects_out_of_range(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        for bad in (0, 7):
            ok, msg = eng.reset_sub_step(tmp_path, "t", bad)
            assert ok is False
            assert "越界" in msg

    def test_reset_bad_line_preserved(self, tmp_path):
        # 坏行不属于任何子步骤，原样保留（暴露而非吞掉）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=2)
        _write_evidence(tmp_path, "t", [_trace_line(1), "not-json{bad", _trace_line(2)])
        ok, _ = eng.reset_sub_step(tmp_path, "t", 2)
        assert ok is True
        assert "not-json{bad" in eng.read_evidence(tmp_path, "t")


# ---------- §substep-gate-at-stop：latest_trace_sha1 + gate_sub_step_at_stop ----------


def _trace_line(sub_step: int, marker: str = "m") -> str:
    return json.dumps(
        {
            "kind": "skill-trace",
            "major_stage": "Understand",
            "minor_stage": "ProblemContext",
            "sub_step": sub_step,
            "skill": "define-problem",
            "purpose": "p",
            "q": [f"q-{marker}"],
            "a": [f"a-{marker}"],
        },
        ensure_ascii=False,
    )


class TestLatestTraceSha1:
    def test_no_file_none(self, tmp_path):
        assert eng.latest_trace_sha1(tmp_path, "t", 1) is None

    def test_no_matching_step_none(self, tmp_path):
        _write_evidence(tmp_path, "t", [_trace_line(1)])
        assert eng.latest_trace_sha1(tmp_path, "t", 2) is None

    def test_latest_line_wins(self, tmp_path):
        _write_evidence(tmp_path, "t", [_trace_line(1, "old"), _trace_line(1, "new")])
        sha = eng.latest_trace_sha1(tmp_path, "t", 1)
        assert (
            sha == eng.hashlib.sha1(_trace_line(1, "new").encode("utf-8")).hexdigest()
        )

    def test_merged_line_tolerated(self, tmp_path):
        # 合并行（Write 无尾换行 + printf 追加）：两个 JSON 粘一行，
        # raw_decode 循环须两个都看到，latest 取后者
        merged = _trace_line(1, "v1") + _trace_line(1, "v2")
        _write_evidence(tmp_path, "t", [merged])
        assert eng.sub_step_has_trace(tmp_path, "t", 1) is True
        assert (
            eng.latest_trace_sha1(tmp_path, "t", 1)
            == eng.hashlib.sha1(_trace_line(1, "v2").encode("utf-8")).hexdigest()
        )

    def test_merged_line_hash_changes_on_append(self, tmp_path):
        # 合并行存在时 append 第三条 -> latest 指向第三条（重判可触发）
        merged = _trace_line(1, "v1") + _trace_line(1, "v2")
        _write_evidence(tmp_path, "t", [merged, _trace_line(1, "v3")])
        assert (
            eng.latest_trace_sha1(tmp_path, "t", 1)
            == eng.hashlib.sha1(_trace_line(1, "v3").encode("utf-8")).hexdigest()
        )


class TestEvidenceMentionsSubStep:
    """§S13 分诊：真无 trace vs 有内容但 JSON 损坏。"""

    def test_no_file_false(self, tmp_path):
        assert eng.evidence_mentions_sub_step(tmp_path, "t", 1) is False

    def test_mentions_broken_json(self, tmp_path):
        # 损坏行（截断）含 sub_step 字样 -> True（走「修复格式」分支）
        _write_evidence(
            tmp_path, "t", ['{"kind":"skill-trace","sub_step":1,"q":["未完成']
        )
        assert eng.evidence_mentions_sub_step(tmp_path, "t", 1) is True
        # 但 latest_trace_sha1 解析不出 -> None（与 mentions 配合分诊）
        assert eng.latest_trace_sha1(tmp_path, "t", 1) is None

    def test_other_step_false(self, tmp_path):
        _write_evidence(tmp_path, "t", [_trace_line(2)])
        assert eng.evidence_mentions_sub_step(tmp_path, "t", 1) is False


class TestGateSubStepAtStop:
    def test_none_without_sub_steps(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 2)
        action, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert action == "none"

    def test_none_without_trace(self, tmp_path):
        # 中途暂停（无 evidence）-> 静默放行
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        action, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert action == "none"

    def test_pass_advances_and_records_cursor(self, tmp_path, monkeypatch):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        _write_evidence(tmp_path, "t", [_trace_line(1)])
        monkeypatch.setattr(eng, "run_judge", lambda *a, **k: (True, ""))
        action, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert action == "advanced"
        st = eng.load_state(tmp_path, "t")
        assert st["sub_step_index"] == 2
        assert st["node_attempts"] == 0
        assert st["last_judged_trace"]["understand:1#1"] == eng.latest_trace_sha1(
            tmp_path, "t", 1
        )

    def test_same_trace_not_rejudged(self, tmp_path, monkeypatch):
        # block 后模型未写新 trace 就 end_turn -> 不重判（防 loop）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        _write_evidence(tmp_path, "t", [_trace_line(1)])
        calls = {"n": 0}

        def _spy(*a, **k):
            calls["n"] += 1
            return (False, "不达标")

        monkeypatch.setattr(eng, "run_judge", _spy)
        a1, r1, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert a1 == "block" and calls["n"] == 1
        a2, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert a2 == "none" and calls["n"] == 1  # 同 trace 不重判
        assert eng.load_state(tmp_path, "t")["node_attempts"] == 1

    def test_new_trace_rejudged(self, tmp_path, monkeypatch):
        # block 后 append 新 trace -> 重判（返工有效）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        _write_evidence(tmp_path, "t", [_trace_line(1, "v1")])
        monkeypatch.setattr(eng, "run_judge", lambda *a, **k: (False, "x"))
        eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        _write_evidence(tmp_path, "t", [_trace_line(1, "v1"), _trace_line(1, "v2")])
        monkeypatch.setattr(eng, "run_judge", lambda *a, **k: (True, ""))
        action, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert action == "advanced"
        assert eng.load_state(tmp_path, "t")["node_attempts"] == 0

    def test_overwrite_retriggers(self, tmp_path, monkeypatch):
        # 违规覆盖写也产生新 hash -> 必判（hash 比对 vs 行数比对）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        _write_evidence(tmp_path, "t", [_trace_line(1, "v1")])
        monkeypatch.setattr(eng, "run_judge", lambda *a, **k: (False, "x"))
        eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        _write_evidence(tmp_path, "t", [_trace_line(1, "v2")])  # 覆盖，行数不变
        calls = {"n": 0}

        def _spy(*a, **k):
            calls["n"] += 1
            return (True, "")

        monkeypatch.setattr(eng, "run_judge", _spy)
        action, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert action == "advanced" and calls["n"] == 1

    def test_escalate_at_threshold(self, tmp_path, monkeypatch):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        monkeypatch.setattr(eng, "run_judge", lambda *a, **k: (False, "x"))
        for i in range(1, eng.SUB_STEP_BLOCK_ESCALATE + 1):
            _write_evidence(tmp_path, "t", [_trace_line(1, f"v{i}")])
            action, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert action == "escalate"
        assert (
            eng.load_state(tmp_path, "t")["node_attempts"]
            == eng.SUB_STEP_BLOCK_ESCALATE
        )

    def test_last_step_cursor_persisted(self, tmp_path):
        # 末步（gate=None 自动过）：advance_state 从磁盘重 load，游标须先落盘
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=6)
        _write_evidence(tmp_path, "t", [_trace_line(6)])
        action, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert action == "advanced"
        st = eng.load_state(tmp_path, "t")
        assert st["sub_index"] == 2  # 推进到 understand:2
        assert "understand:1#6" in st["last_judged_trace"]


class TestRunJudgeIsolation:
    """judge 子进程环境隔离（2026-07-25 demo 递归爆炸事故防回归）。"""

    def test_judge_cwd_outside_git_repo(self, monkeypatch):
        # judge 会话继承 worktree cwd 时其 Stop/UserPromptSubmit 会触发 workflow
        # hooks -> 递归门控。cwd 必须是非 git 目录（tempdir），hooks 反查不到项目根。
        captured = {}

        class _Res:
            returncode = 0
            stdout = '{"is_error":false,"result":"{\\"pass\\": true, \\"reason\\": \\"\\"}"}\n'

        def _run(cmd, **kw):
            captured.update(kw)
            return _Res()

        monkeypatch.setattr(eng.subprocess, "run", _run)
        ok, _reason = eng.run_judge("rubric", "label", "out")
        assert ok is True
        assert captured.get("cwd") == eng.tempfile.gettempdir()

    def test_judge_prompt_marks_latest_trace_authoritative(self, monkeypatch):
        # append 返工协议下同一 sub_step 有多条 trace：prompt 须指示以最后一条为准，
        # 防 judge 拿返工前的旧行判 block（误报）
        captured = {}

        class _Res:
            returncode = 0
            stdout = '{"is_error":false,"result":"{\\"pass\\": true, \\"reason\\": \\"\\"}"}\n'

        def _run(cmd, **kw):
            captured["cmd"] = cmd
            return _Res()

        monkeypatch.setattr(eng.subprocess, "run", _run)
        eng.run_judge("rubric", "label", "out", artifact_content='{"sub_step":1}')
        prompt = captured["cmd"][-1]
        assert "以最后一条为准" in prompt
        assert "返工历史" in prompt


class TestRunJudgeHarnessTrim:
    """judge 调用裁剪 harness（2026-07-25 demo 实测：~20.7k 输入里 ~95% 是
    工具 schema/默认 system prompt 等 harness 开销，判决载荷仅 ~0.7k）。
    --tools "" + --system-prompt 只裁 harness、不动判决 prompt，
    settings/认证链零触碰（ac-ark env 与 settings.json env 用户都照常）。
    实证：同一真实 pass 案例重放，输入 20728 -> 3590（-83%），判决一致。
    """

    def _capture(self, monkeypatch):
        captured = {}

        class _Res:
            returncode = 0
            stdout = '{"is_error":false,"result":"{\\"pass\\": true, \\"reason\\": \\"\\"}"}\n'

        def _run(cmd, **kw):
            captured["cmd"] = cmd
            return _Res()

        monkeypatch.setattr(eng.subprocess, "run", _run)
        return captured

    def test_judge_invocation_disables_tools(self, monkeypatch):
        captured = self._capture(monkeypatch)
        eng.run_judge("rubric", "label", "out")
        cmd = captured["cmd"]
        assert "--tools" in cmd
        assert cmd[cmd.index("--tools") + 1] == ""

    def test_judge_invocation_replaces_system_prompt(self, monkeypatch):
        captured = self._capture(monkeypatch)
        eng.run_judge("rubric", "label", "out")
        cmd = captured["cmd"]
        assert "--system-prompt" in cmd
        sys_prompt = cmd[cmd.index("--system-prompt") + 1]
        assert "judge" in sys_prompt
        assert "JSON" in sys_prompt

    def test_judge_payload_prompt_unchanged_and_last(self, monkeypatch):
        # 判决载荷（判据+输出+产物）必须原样保留在最后一个参数——准确性靠它
        captured = self._capture(monkeypatch)
        eng.run_judge("RUBRIC_X", "LABEL_Y", "OUTPUT_Z", artifact_content="ART_W")
        prompt = captured["cmd"][-1]
        for needle in ("RUBRIC_X", "LABEL_Y", "OUTPUT_Z", "ART_W"):
            assert needle in prompt


class TestRunJudgeCostMeta:
    """judge 成本可见性（2026-07-26）：claude -p 返回 JSON 的 usage/duration/cost
    原被丢弃 -> judge 成本完全黑盒。run_judge 现采进 LAST_JUDGE_META 供 hook 写
    审计日志；签名保持 (pass, reason) 不变，失败路径记 judge_error。"""

    def _mock_run(self, monkeypatch, stdout=None, exc=None):
        def _run(cmd, **kw):
            if exc is not None:
                raise exc

            class _Res:
                returncode = 0

            _Res.stdout = stdout
            return _Res()

        monkeypatch.setattr(eng.subprocess, "run", _run)

    def test_success_captures_usage_and_duration(self, monkeypatch):
        self._mock_run(
            monkeypatch,
            stdout=(
                '{"is_error":false,"duration_ms":12345,"duration_api_ms":11000,'
                '"total_cost_usd":0.0123,'
                '"usage":{"input_tokens":100,"output_tokens":20,'
                '"cache_read_input_tokens":3000,"cache_creation_input_tokens":0},'
                '"result":"{\\"pass\\": true, \\"reason\\": \\"\\"}"}\n'
            ),
        )
        ok, _ = eng.run_judge("rubric", "label", "out")
        assert ok
        m = eng.LAST_JUDGE_META
        assert m["judge_input_tokens"] == 100
        assert m["judge_output_tokens"] == 20
        assert m["judge_cache_read_input_tokens"] == 3000
        assert m["judge_ms"] == 12345
        assert m["judge_api_ms"] == 11000
        assert m["judge_cost_usd"] == 0.0123
        assert "judge_error" not in m

    def test_missing_fields_omitted(self, monkeypatch):
        # provider 包装器可能只给部分字段：缺什么就不记什么（防御式取值）
        self._mock_run(
            monkeypatch,
            stdout=(
                '{"is_error":false,"usage":{"input_tokens":5},'
                '"result":"{\\"pass\\": true, \\"reason\\": \\"\\"}"}\n'
            ),
        )
        eng.run_judge("rubric", "label", "out")
        m = eng.LAST_JUDGE_META
        assert m == {"judge_input_tokens": 5}

    def test_timeout_marks_judge_error(self, monkeypatch):
        self._mock_run(
            monkeypatch, exc=eng.subprocess.TimeoutExpired(cmd="claude", timeout=1)
        )
        ok, reason = eng.run_judge("rubric", "label", "out")
        assert not ok
        assert eng.LAST_JUDGE_META == {"judge_error": "TimeoutExpired"}

    def test_meta_reset_between_calls(self, monkeypatch):
        # 上一次的成本字段不能漏到下一次失败调用里
        self._mock_run(
            monkeypatch,
            stdout=(
                '{"is_error":false,"usage":{"input_tokens":5},'
                '"result":"{\\"pass\\": true, \\"reason\\": \\"\\"}"}\n'
            ),
        )
        eng.run_judge("rubric", "label", "out")
        self._mock_run(
            monkeypatch, exc=eng.subprocess.TimeoutExpired(cmd="claude", timeout=1)
        )
        eng.run_judge("rubric", "label", "out")
        assert eng.LAST_JUDGE_META == {"judge_error": "TimeoutExpired"}

    def test_is_error_still_captures_usage(self, monkeypatch):
        # is_error 路径也有 usage 可对账（judge_error 与成本字段共存）
        self._mock_run(
            monkeypatch,
            stdout=(
                '{"is_error":true,"duration_ms":500,'
                '"usage":{"input_tokens":7,"output_tokens":1},'
                '"result":"api boom"}\n'
            ),
        )
        ok, _ = eng.run_judge("rubric", "label", "out")
        assert not ok
        m = eng.LAST_JUDGE_META
        assert m["judge_error"] == "is_error"
        assert m["judge_input_tokens"] == 7
        assert m["judge_ms"] == 500


class TestPendingUnjudgedStep:
    """§S10：PreToolUse 围栏的关闭条件（与门控共用 last_judged_trace 游标）。"""

    def test_no_state_none(self, tmp_path):
        assert eng.pending_unjudged_step(tmp_path, "t") is None

    def test_no_sub_steps_none(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 2)
        assert eng.pending_unjudged_step(tmp_path, "t") is None

    def test_no_trace_none(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        assert eng.pending_unjudged_step(tmp_path, "t") is None

    def test_unjudged_trace_returns_step(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        _write_evidence(tmp_path, "t", [_trace_line(1)])
        assert eng.pending_unjudged_step(tmp_path, "t") == 1

    def test_judged_trace_none(self, tmp_path, monkeypatch):
        # judge 判过（游标 == 最新 hash）-> 围栏开
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        _write_evidence(tmp_path, "t", [_trace_line(1)])
        monkeypatch.setattr(eng, "run_judge", lambda *a, **k: (False, "x"))
        eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert eng.pending_unjudged_step(tmp_path, "t") is None

    def test_fence_off_none(self, tmp_path):
        # /dl fence off -> 围栏停用（回文案约束）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        _write_evidence(tmp_path, "t", [_trace_line(1)])
        st = eng.normalize_state(eng.load_state(tmp_path, "t"))
        assert st["enforce_step_fence"] is True  # normalize 默认开
        st["enforce_step_fence"] = False
        eng.save_state(tmp_path, "t", st)
        assert eng.pending_unjudged_step(tmp_path, "t") is None


class TestPhaseWriteDenial:
    """§S11：phase 写权限围栏（understand/plan/review 禁改源码硬化）。"""

    def _deny(self, tmp_path, phase, sub, path):
        step = (
            1 if eng.sub_total(phase) > 0 else 0
        )  # 有子阶段的节点 sub_step_index 须 1-based
        _write_state_full(tmp_path, "t", phase, sub, sub_step=step)
        return eng.phase_write_denial(tmp_path, "t", path)

    def test_understand_denies_source(self, tmp_path):
        r = self._deny(tmp_path, "understand", 1, "/repo/factors/rsi.py")
        assert r is not None and "rsi.py" in r

    def test_understand_allows_artifact_designs_evidence(self, tmp_path):
        assert self._deny(tmp_path, "understand", 1, "/repo/understand.md") is None
        assert self._deny(tmp_path, "understand", 1, "/repo/designs/x.md") is None
        assert (
            self._deny(tmp_path, "understand", 1, "/repo/.claude/evidence/t.jsonl")
            is None
        )

    def test_plan_allows_plan_md_denies_source(self, tmp_path):
        assert self._deny(tmp_path, "plan", 0, "/repo/plan.md") is None
        assert self._deny(tmp_path, "plan", 0, "/repo/main.py") is not None

    def test_execute_unrestricted(self, tmp_path):
        assert self._deny(tmp_path, "execute", 0, "/repo/main.py") is None

    def test_review_denies_impl_allows_review_md(self, tmp_path):
        assert self._deny(tmp_path, "review", 0, "/repo/main.py") is not None
        assert self._deny(tmp_path, "review", 0, "/repo/review.md") is None

    def test_evolution_allows_memory_and_skills(self, tmp_path):
        assert self._deny(tmp_path, "evolution", 0, "/repo/evolution.md") is None
        assert (
            self._deny(
                tmp_path, "evolution", 0, "/home/u/.claude/projects/p/memory/fact.md"
            )
            is None
        )
        assert (
            self._deny(tmp_path, "evolution", 0, "/repo/.claude/skills/s/SKILL.md")
            is None
        )
        assert self._deny(tmp_path, "evolution", 0, "/repo/main.py") is not None

    def test_no_state_allows(self, tmp_path):
        assert eng.phase_write_denial(tmp_path, "t", "/repo/main.py") is None

    def test_phase_fence_has_no_toggle(self, tmp_path):
        # S11 是系统硬约束（同 rubric，对用户黑盒）：state 无 enforce_phase_fence
        # 字段；即使手塞 False 也不生效
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        st = eng.normalize_state(eng.load_state(tmp_path, "t"))
        assert "enforce_phase_fence" not in st
        st["enforce_phase_fence"] = False
        eng.save_state(tmp_path, "t", st)
        assert eng.phase_write_denial(tmp_path, "t", "/repo/main.py") is not None


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
        # meta 不需 git repo/name（静态常量）;供 dl-lib.sh 缓存删 bash 副本
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
