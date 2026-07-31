"""
dl_flow_engine.py 的单元测试（dl-workflow v0.1+）。

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
- gate_verdict_mech：NONE 通过 / 产物机械门（EXISTS + 新鲜度 + CONTAINS，§8.3）/ 降级
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

DLWF_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DLWF_ROOT))

import dl_flow_engine as eng  # noqa: E402


# ---------- 节点标识推导 ----------


class TestNodeId:
    def test_sub_zero_is_whole_phase(self):
        assert eng.node_id("execute", 0) == "execute:0"

    def test_sub_n_is_subphase(self):
        assert eng.node_id("understand", 3) == "understand:3"

    def test_current_node_id_whole_phase(self):
        # 无子阶段 phase sub_index=0 -> 整阶段节点
        assert eng.current_node_id("execute", 0) == "execute:0"

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
        # execute/review 整阶段 advance="phase"（plan 自 2026-07-27 拆子阶段，
        # 末子阶段 advance="phase" 由 TestPlan4Orchestration 覆盖）
        for phase in ("execute", "review"):
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
        # 无子阶段 phase -> []；plan 自 2026-07-28 拆四子阶段（v2.21 plan:4）
        assert eng.subphase_labels("plan") == [
            "设计解决方案",
            "拆解任务与阶段",
            "选择能力与工具",
            "制定执行计划和检查点",
        ]
        assert eng.subphase_labels("execute") == []

    def test_sub_total_derived_from_nodes(self):
        # sub_total 从 _NODES 推导（不再 _SUB_TOTAL 副本）,与 subphase_labels 长度一致
        assert eng.sub_total("understand") == 4
        assert len(eng.subphase_labels("understand")) == 4
        assert eng.sub_total("plan") == 4
        assert eng.sub_total("execute") == 0

    def test_minor_key_on_subphases(self):
        # understand 4 子阶段各持英文标识(首字母大写,evidence minor_stage 值)
        assert eng._NODES["understand:1"].minor_key == "ProblemContext"
        assert eng._NODES["understand:2"].minor_key == "GoalsAndValue"
        assert eng._NODES["understand:3"].minor_key == "ScopeAndConstraints"
        assert eng._NODES["understand:4"].minor_key == "SuccessCriteria"
        # plan 四子阶段同（plan:2 自 2026-07-28 起，plan:3 自 v2.20 起，plan:4 自 v2.21 起）
        assert eng._NODES["plan:1"].minor_key == "DesignSolution"
        assert eng._NODES["plan:2"].minor_key == "TaskBreakdown"
        assert eng._NODES["plan:3"].minor_key == "CapabilityToolSelection"
        assert eng._NODES["plan:4"].minor_key == "ExecutionPlanCheckpoints"

    def test_minor_key_none_for_whole_phase(self):
        # 无子阶段节点(sub=0)无 minor_key；plan:2 自 2026-07-28 有编排
        # （minor_key=TaskBreakdown，见 test_minor_key_on_subphases）
        assert eng._NODES["review:0"].minor_key is None
        assert eng._NODES["execute:0"].minor_key is None

    def test_minor_key_map(self):
        # minor_key -> 中文 label(single source,viewer 英转中用)
        m = eng.minor_key_map()
        assert m["ProblemContext"] == "理解问题和背景"
        assert m["SuccessCriteria"] == "定义成功标准和验收方式"
        assert m["DesignSolution"] == "设计解决方案"
        assert m["TaskBreakdown"] == "拆解任务与阶段"
        assert m["CapabilityToolSelection"] == "选择能力与工具"
        assert m["ExecutionPlanCheckpoints"] == "制定执行计划和检查点"
        assert len(m) == 8


# ---------- 推进链 ----------


class TestNextNode:
    def test_sub_advance_within_phase(self):
        # understand:1 -> understand:2（同 phase, sub+1）
        assert eng.next_node_id("understand", 1) == ("understand", 2)

    def test_last_subphase_advances_to_next_phase(self):
        # understand:4 -> plan:1（下一 phase 首子阶段,plan 拆两子阶段后 sub=1）
        assert eng.next_node_id("understand", 4) == ("plan", 1)

    def test_plan_subphase_chain(self):
        # plan:1 -> plan:2 -> plan:3 -> plan:4 -> execute:0（v2.21 plan:4 加入）
        assert eng.next_node_id("plan", 1) == ("plan", 2)
        assert eng.next_node_id("plan", 2) == ("plan", 3)
        assert eng.next_node_id("plan", 3) == ("plan", 4)
        assert eng.next_node_id("plan", 4) == ("execute", 0)

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
            "plan:1",
            "plan:2",
            "plan:3",
            "plan:4",
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
        # 2026-07-28 用户决议：围栏只设在 plan 完成——understand 移出 GATED_AFTER
        assert eng.is_gated_after("understand") is False
        assert eng.is_gated_after("plan") is True
        assert eng.is_gated_after("execute") is False

    def test_sub_total(self):
        assert eng.sub_total("understand") == 4
        assert eng.sub_total("plan") == 4


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
        ok = {"phase": "plan", "sub_index": 2, "node": "plan:2"}
        norm = eng.normalize_state(dict(ok))
        assert norm["node"] == "plan:2"

    def test_sub_step_index_defaults_zero_no_steps(self):
        # §orchestration v2：无 sub_steps 节点 -> sub_step_index 补 0
        old = {"phase": "review", "sub_index": 0}  # review:0 无 sub_steps
        norm = eng.normalize_state(dict(old))
        assert norm["sub_step_index"] == 0
        # 无编排整阶段节点同（execute:0）
        norm2 = eng.normalize_state({"phase": "execute", "sub_index": 0})
        assert norm2["sub_step_index"] == 0

    def test_sub_step_index_defaults_one_with_steps(self):
        # §orchestration v2：understand:1/2 有 sub_steps -> sub_step_index 缺省补 1（首步起步）
        norm = eng.normalize_state({"phase": "understand", "sub_index": 1})
        assert norm["sub_step_index"] == 1
        norm_g2 = eng.normalize_state({"phase": "understand", "sub_index": 2})
        assert norm_g2["sub_step_index"] == 1
        # plan:2 有编排（2026-07-28 起）-> 同补 1
        norm_tb = eng.normalize_state({"phase": "plan", "sub_index": 2})
        assert norm_tb["sub_step_index"] == 1

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
            short="s",
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
            kind="skill",
            ref="x",
            short="s",
            purpose="p",
            input=None,
            record=True,
            gate=None,
        )
        with pytest.raises((AttributeError, Exception)):
            s.kind = "tool"  # frozen -> 不可改


class TestNodeSubStepsField:
    def test_default_none(self):
        # 未编排节点 sub_steps None（向后兼容）；编排首节点例外：
        # understand:1 + plan:1（均 6 子步骤）
        for phase in eng.PHASES:
            total = eng.sub_total(phase)
            first_sub = 1 if total > 0 else 0
            node = eng.get_node(phase, first_sub)
            if (node.phase, node.sub) in (("understand", 1), ("plan", 1)):
                assert node.sub_steps is not None  # 编排节点
            else:
                assert node.sub_steps is None

    def test_sub_steps_can_be_set(self):
        # 构造带 sub_steps 的节点（验证 schema 可用，不落 _NODES）
        s1 = eng.Step(
            kind="skill",
            ref="x",
            short="s",
            purpose="p1",
            input=None,
            record=True,
            gate="g1",
        )
        s2 = eng.Step(
            kind="tool",
            ref="y",
            short="s",
            purpose="p2",
            input="step1",
            record=False,
            gate=None,
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


class TestHarnessPromptOptimization:
    """2026-07-26 harness 化优化（designs/harness-prompt-optimization-design.md）：
    Step.short 骨架短名（P0 注入瘦身）；purpose 清考古（P2，规则留、考古移注释）；
    render-phase-rules（P1 双通道单源）；rubric 判据关键词回归钉死。"""

    def _steps(self):
        node = eng.get_node("understand", 1)
        assert node.sub_steps is not None
        return node.sub_steps

    # ----- P0：short 字段 -----
    def test_six_steps_short_labels(self):
        shorts = [s.short for s in self._steps()]
        assert shorts == [
            "逼问定义",
            "拆解深挖",
            "双向取证",
            "质检裁决",
            "归一化陈述",
            "读回确认",
        ]

    # ----- P2：purpose/gate 不含考古（规则留下，考古移 engine 注释）-----
    def test_purpose_gate_no_demo_archaeology(self):
        for s in self._steps():
            assert "实录" not in s.purpose
            assert "demo " not in s.purpose
            if s.gate:
                assert "实录" not in s.gate
                assert "demo " not in s.gate

    # ----- rubric 判据关键词回归（防 P2 清理误删判据；逐条钉死）-----
    def test_rubric_keywords_regression(self):
        s = self._steps()
        # 子1：who 出处钉死 + 双结论制
        assert "who 类出处只认用户自述" in s[0].gate
        assert "「未提及」" in s[0].gate
        # 子2：反同义反复 + 反稻草人
        assert "同义反复判 block" in s[1].gate
        assert "竞争假设非稻草人" in s[1].gate
        # 子3：可追溯指针 + 反训练记忆冒充
        assert "可追溯指针" in s[2].gate
        assert "用训练记忆冒充外部证据 = 编造" in s[2].gate
        # 子4：三关质检 + 红队触发强制
        assert "三关质检记录" in s[3].gate
        assert "只给证据不给结论" in s[3].gate
        # 子5：裁决传导
        assert "裁决不传导判 block" in s[4].gate

    def test_purpose_keywords_regression(self):
        s = self._steps()
        # 子3：证伪优先时序 + 禁 tavily/WebSearch + 禁探查凭证（规则留存）
        assert "反证查询（先）→支持证据（后）" in s[2].purpose
        assert "禁 tavily_search/WebSearch" in s[2].purpose
        assert "禁止探查凭证" in s[2].purpose
        # 子4：红队触发条件 + redteam-prompt 生成器（纪律 a-d 已机械化进模板）
        for frag in (
            "条件触发对抗复核",
            "只给证据不给结论",
            "redteam-prompt",
            "触发条件写死",
        ):
            assert frag in s[3].purpose

    # ----- P1：render-phase-rules -----
    def test_render_substeps_section(self):
        out = eng.render_substeps_section("understand:1")
        assert out.startswith("<!-- BEGIN GENERATED sub_steps understand:1 -->")
        assert out.endswith("<!-- END GENERATED sub_steps understand:1 -->")
        # 渲染行含 ref + purpose 全文（与 engine 逐字同源）
        s1 = self._steps()[0]
        assert f"- **子步骤1 = {s1.ref}**：{s1.purpose}" in out
        # gate=None 标自动过
        assert "**子步骤6 = define-problem**（自动过）" in out

    def test_render_phase_rules_replaces_marker(self):
        tpl = (
            "前\n<!-- BEGIN GENERATED sub_steps understand:1 -->\n旧内容\n"
            "<!-- END GENERATED sub_steps understand:1 -->\n后"
        )
        out = eng.render_phase_rules(tpl)
        assert "旧内容" not in out
        assert "子步骤1 = define-problem" in out
        assert out.startswith("前") and out.endswith("后")

    def test_render_phase_rules_no_marker_passthrough(self):
        tpl = "纯静态模板\n无标记段\n"
        assert eng.render_phase_rules(tpl) == tpl

    def test_render_phase_rules_idempotent(self):
        tpl = "<!-- BEGIN GENERATED sub_steps understand:1 -->\nx\n<!-- END GENERATED sub_steps understand:1 -->"
        once = eng.render_phase_rules(tpl)
        assert eng.render_phase_rules(once) == once

    def test_render_substeps_no_steps_raises(self):
        with pytest.raises(ValueError, match="无 sub_steps"):
            eng.render_substeps_section("execute:0")

    def test_render_substeps_bad_id_raises(self):
        with pytest.raises(ValueError, match="节点 id 非法"):
            eng.render_substeps_section("understand")
        with pytest.raises(KeyError, match="未知节点"):
            eng.render_substeps_section("nope:1")


class TestSubStepHelpers:
    def test_sub_step_total_no_steps(self):
        assert eng.sub_step_total(eng.get_node("execute", 0)) == 0
        assert eng.sub_step_total(eng.get_node("review", 0)) == 0  # 无编排节点
        # understand:1 有 6 子步骤（2026-07-26 重设计：验真拆双向取证+质检裁决）
        assert eng.sub_step_total(eng.get_node("understand", 1)) == 6
        # understand:2 有 5 子步骤（2026-07-26 goals-and-value-substeps-design）
        assert eng.sub_step_total(eng.get_node("understand", 2)) == 5
        # understand:3/4 各 5 子步骤（2026-07-27 scope / success-criteria designs）
        assert eng.sub_step_total(eng.get_node("understand", 3)) == 5
        assert eng.sub_step_total(eng.get_node("understand", 4)) == 5
        # plan:1 有 6 子步骤（2026-07-27 design-solution-substeps-design）
        assert eng.sub_step_total(eng.get_node("plan", 1)) == 6

    def test_sub_step_total_with_steps(self):
        s1 = eng.Step(
            kind="skill",
            ref="x",
            short="s",
            purpose="p",
            input=None,
            record=True,
            gate=None,
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
            kind="skill",
            ref="a",
            short="s",
            purpose="p1",
            input=None,
            record=True,
            gate=None,
        )
        s2 = eng.Step(
            kind="tool",
            ref="b",
            short="s",
            purpose="p2",
            input="step1",
            record=True,
            gate=None,
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
        n = eng.get_node("execute", 0)  # 无 sub_steps
        assert eng.sub_step_at(n, 1) is None
        s1 = eng.Step(
            kind="skill",
            ref="a",
            short="s",
            purpose="p",
            input=None,
            record=True,
            gate=None,
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
            short="s",
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
            short="s",
            purpose="p",
            input=None,
            record=True,
            gate="≥1 外部证据连回项目",
        )
        assert eng.step_needs_evidence(sn) is False
        # gate=None -> False
        snone = eng.Step(
            kind="skill",
            ref="x",
            short="s",
            purpose="p",
            input=None,
            record=False,
            gate=None,
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
        # understand:4 -> plan:1（plan 首子阶段）；2026-07-28 起 understand 移出
        # GATED_AFTER（围栏只设在 plan 完成）-> plan gate=pending
        _write_state(tmp_path, "t", "understand", 4)
        state = eng.advance_state(tmp_path, "t", via="test")
        assert state["phase"] == "plan"
        assert state["sub_index"] == 1
        assert state["node"] == "plan:1"
        assert state["gate"] == "pending"  # understand 无闸门 -> 新 phase gate=pending
        assert state["sub_total"] == 4  # v2.21 plan 四子阶段

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
        node = eng.get_node("understand", 4)  # 末子阶段（artifact_exists 机械门）
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

    def test_record_carries_stage_fields(self, tmp_path):
        # 2026-07-26：gate 记录与 skill-trace 结构字段对齐——major_stage/minor_stage
        # 取值单源 = node.phase / node.minor_key（与编排阶段对齐）
        node = eng.get_node("understand", 2)  # GoalsAndValue
        ok = eng.write_gate_verdict(tmp_path, "t", node, attempts=0, cwd=str(tmp_path))
        assert ok is True
        rec = json.loads(
            eng._evidence_path(tmp_path, "t").read_text(encoding="utf-8").strip()
        )
        assert rec["major_stage"] == "Understand"
        assert rec["minor_stage"] == "GoalsAndValue"

    def test_record_minor_stage_none_for_whole_phase(self, tmp_path):
        # 整阶段节点（execute:0）minor_key=None -> minor_stage 显式 null（不猜）
        node = eng.get_node("execute", 0)
        ok = eng.write_gate_verdict(tmp_path, "t", node, attempts=0, cwd=str(tmp_path))
        assert ok is True
        rec = json.loads(
            eng._evidence_path(tmp_path, "t").read_text(encoding="utf-8").strip()
        )
        assert rec["major_stage"] == "Execute"
        assert rec["minor_stage"] is None

    def test_rubric_none_for_mech_only_node(self, tmp_path):
        # rubric=None 的节点（understand 子 3）-> rubric 字段 None（仅机械过）
        # 注：understand:1 现有验真 rubric（§define-problem-verify-gate），用 understand:3 测无 rubric
        node = eng.get_node("understand", 3)
        ok = eng.write_gate_verdict(tmp_path, "t", node, attempts=0, cwd=str(tmp_path))
        assert ok is True
        rec = json.loads(
            eng._evidence_path(tmp_path, "t").read_text(encoding="utf-8").strip()
        )
        assert rec["rubric"] is None
        assert rec["gate_mech"] == "none"

    def test_appends_multiple_records(self, tmp_path):
        # 多次 pass -> 多行追加（不覆盖）
        node = eng.get_node("plan", 2)
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

    def test_other_phases_no_steps(self):
        # understand 4 子阶段自 2026-07-27 起全部有编排（1=6 步，2/3/4=5 步）；
        # plan:1 自 2026-07-27 起有编排（6 步，design-solution-substeps-design）；
        # plan:2 自 2026-07-28 起有编排（5 步，task-breakdown-substeps-design）；
        # 无编排节点 = execute/review/evolution 整阶段节点
        assert eng.get_node("plan", 1).sub_steps is not None
        assert eng.get_node("plan", 2).sub_steps is not None
        for phase in ("execute", "review", "evolution"):
            assert eng.get_node(phase, 0).sub_steps is None, phase


class TestUnderstand2Orchestration:
    """understand:2 GoalsAndValue 5 子步骤编排（designs/goals-and-value-substeps-design.md）。

    关键不对称：问题是事实性命题（需外部取证+质检裁决），目标/价值是规范性命题
    （真值源只有用户）——故 5 步无取证/裁决双步；must/nice 分层模型只提案、
    用户子5 裁决；hold_for_gate=True（2026-07-27 用户决议，自 understand:1 移来）。
    """

    def _steps(self):
        node = eng.get_node("understand", 2)
        assert node.sub_steps is not None and len(node.sub_steps) == 5
        return node.sub_steps

    def test_gate_rubric_none(self):
        assert eng.get_node("understand", 2).gate_rubric is None

    def test_hold_for_gate_enabled(self):
        # 2026-07-28 用户决议：围栏只设在 plan 完成——understand 全部无门栏
        assert eng.get_node("understand", 2).hold_for_gate is False
        assert eng.get_node("understand", 1).hold_for_gate is False

    def test_problem_context_last_step_advances_without_hold(self, tmp_path):
        # 2026-07-27 决议：ProblemContext 末步（子6）过后**不扣留**，直接推进 understand:2
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=6)
        _write_evidence(tmp_path, "t", [_trace_line(6)])
        action, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert action == "advanced"
        st = eng.load_state(tmp_path, "t")
        assert st["sub_index"] == 2
        assert st["node"] == "understand:2"
        assert st["sub_step_index"] == 1  # 新节点首步
        assert "held_for_gate" not in st

    def test_shorts_order(self):
        shorts = [s.short for s in self._steps()]
        assert shorts == ["目标引出", "对齐质检", "价值论证", "归一化陈述", "读回确认"]

    def test_record_all_true(self):
        assert all(s.record for s in self._steps())

    def test_input_chain(self):
        steps = self._steps()
        assert steps[0].input == "ProblemContext.step5.statements"  # 跨节点吃子1 输出
        assert steps[1].input == "step1.goal_candidates"
        assert steps[2].input == "step2.aligned_goals"
        assert steps[3].input == "step3.valued_goals"
        assert steps[4].input == "step4.statements"

    def test_step1_dual_conclusion(self):
        # 双结论制（§3.5 #3）：「目标不成立」合法——防逼编造价值
        s1 = self._steps()[0]
        assert "目标不成立" in s1.purpose and "字面请求即全部" in s1.purpose
        assert "minor_stage=GoalsAndValue 且 sub_step==1" in s1.gate
        assert "AskUserQuestion" in s1.ref

    def test_step2_alignment_gate(self):
        s2 = self._steps()[1]
        for needle in ("双向追溯矩阵", "solutioneering", "冲突", "汇总声明不算记录"):
            assert needle in s2.purpose, f"子2 purpose 缺 {needle}"
        for needle in ("sub_step==2", "同义反复", "矩阵放水"):
            assert needle in s2.gate, f"子2 gate 缺 {needle}"

    def test_step3_value_and_fence(self):
        s3 = self._steps()[2]
        assert s3.fence_allow == ("Bash",)  # S15：条件性基线测量
        for needle in (
            "受益者",
            "价值链",
            "量化基线",
            "不可量化+原因",
            "禁止替用户拍板",
        ):
            assert needle in s3.purpose, f"子3 purpose 缺 {needle}"
        for needle in ("sub_step==3", "全 must", "拍脑袋数字"):
            assert needle in s3.gate, f"子3 gate 缺 {needle}"

    def test_step4_normalization(self):
        s4 = self._steps()[3]
        assert s4.kind == "skill" and s4.ref == "define-problem"
        for needle in ("原子", "去上下文", "must/nice", "solution-free"):
            assert needle in s4.purpose, f"子4 purpose 缺 {needle}"
        assert "sub_step==4" in s4.gate and "逐项一致" in s4.gate

    def test_step5_readback_gate_none(self):
        s5 = self._steps()[4]
        assert s5.gate is None  # 交互步，trace 存在即过
        assert s5.record is True
        assert "用户裁决 must/nice" in s5.purpose

    def test_selfcheck_no_quality_criteria_leak(self):
        # Goodhart 分层守卫（同 understand:1）：gate 黑盒措辞不得进 checklist
        for s in self._steps():
            if not s.selfcheck:
                continue
            for banned in ("从严裁量", "同义反复", "矩阵放水", "拍脑袋数字", "全 must"):
                assert banned not in s.selfcheck, f"{s.short} selfcheck 泄漏 {banned}"


class TestUnderstand3Orchestration:
    """understand:3 ScopeAndConstraints 5 子步骤编排
    （designs/scope-and-constraints-substeps-design.md，2026-07-27 用户确认）。

    混合命题不对称：约束=事实性（本地单层源验证，压缩 ProblemContext 取证+质检
    双步为子2 一步），范围=规范性（提案归模型、拍板归用户子5），假设=中间态
    （显式标注置信度×影响，接受归用户子5）；hold_for_gate=True（隔离测试语义）。
    """

    def _steps(self):
        node = eng.get_node("understand", 3)
        assert node.sub_steps is not None and len(node.sub_steps) == 5
        return node.sub_steps

    def test_gate_rubric_none(self):
        assert eng.get_node("understand", 3).gate_rubric is None

    def test_hold_for_gate_enabled(self):
        # 2026-07-28 用户决议：围栏只设在 plan 完成——understand 全部无门栏
        assert eng.get_node("understand", 3).hold_for_gate is False

    def test_shorts_order(self):
        shorts = [s.short for s in self._steps()]
        assert shorts == [
            "障碍分析引出",
            "约束验证标注",
            "范围界定",
            "归一化陈述",
            "读回确认",
        ]

    def test_record_all_true(self):
        assert all(s.record for s in self._steps())

    def test_input_chain(self):
        steps = self._steps()
        assert (
            steps[0].input == "GoalsAndValue.step4.statements"
        )  # 跨节点吃 must 目标集
        assert steps[1].input == "step1.constraint_candidates"
        assert "step2.verified_constraints" in steps[2].input
        assert "GoalsAndValue.step5" in steps[2].input
        assert steps[3].input == "step3.scope_proposal"
        assert steps[4].input == "step4.statements"

    def test_step1_obstacle_dual_conclusion(self):
        # 双结论制（§3.5 #3）：「无实质约束」合法——但须每 must 目标否定提问留痕
        s1 = self._steps()[0]
        assert "KAOS" in s1.purpose and "无实质约束" in s1.purpose
        assert "minor_stage=ScopeAndConstraints 且 sub_step==1" in s1.gate
        assert "AskUserQuestion" in s1.ref

    def test_step2_verify_three_states_and_fence(self):
        s2 = self._steps()[1]
        assert s2.fence_allow == ("Bash",)  # S15：本地验证
        for needle in ("三态", "已验证", "假设", "置信度", "证伪"):
            assert needle in s2.purpose, f"子2 purpose 缺 {needle}"
        for needle in ("sub_step==2", "假设未标注", "工具"):
            assert needle in s2.gate, f"子2 gate 缺 {needle}"

    def test_step3_scope_two_sided(self):
        s3 = self._steps()[2]
        for needle in ("in-scope", "out-of-scope", "双向追溯", "汇总声明不算记录"):
            assert needle in s3.purpose, f"子3 purpose 缺 {needle}"
        for needle in ("sub_step==3", "矩阵放水", "拍板"):
            assert needle in s3.gate, f"子3 gate 缺 {needle}"

    def test_step4_normalization(self):
        s4 = self._steps()[3]
        assert s4.kind == "skill" and s4.ref == "define-problem"
        for needle in ("原子", "去上下文", "类型标签", "solution-free"):
            assert needle in s4.purpose, f"子4 purpose 缺 {needle}"
        assert "sub_step==4" in s4.gate and "逐项一致" in s4.gate

    def test_step5_readback_gate_none(self):
        s5 = self._steps()[4]
        assert s5.gate is None  # 交互步，trace 存在即过
        assert s5.record is True
        assert "假设的接受" in s5.purpose  # 第二规范裁决点

    def test_selfcheck_no_quality_criteria_leak(self):
        # Goodhart 分层守卫（同 understand:1/2）：gate 黑盒措辞不得进 checklist
        for s in self._steps():
            if not s.selfcheck:
                continue
            for banned in ("从严裁量", "矩阵放水", "形式主义", "偷懒"):
                assert banned not in s.selfcheck, f"{s.short} selfcheck 泄漏 {banned}"


class TestMinorStageFilter:
    """v2.15：多编排节点共用 evidence，trace 匹配层按 minor_stage 过滤防跨节点串号。

    无过滤时 ProblemContext 子1 的 trace 会被 GoalsAndValue 子1 的门控/围栏误读。
    minor_stage=None 不过滤（向后兼容）。
    """

    def _g2_trace(self, sub_step: int, marker: str = "g") -> str:
        return _g2_trace_line(sub_step, marker)

    def test_has_trace_scoped(self, tmp_path):
        _write_evidence(tmp_path, "t", [_trace_line(1)])  # ProblemContext 子1
        assert eng.sub_step_has_trace(tmp_path, "t", 1, "GoalsAndValue") is False
        assert eng.sub_step_has_trace(tmp_path, "t", 1, "ProblemContext") is True
        assert eng.sub_step_has_trace(tmp_path, "t", 1) is True  # None=不过滤（兼容）

    def test_latest_sha1_scoped(self, tmp_path):
        _write_evidence(tmp_path, "t", [_trace_line(1), self._g2_trace(1)])
        sha_pc = eng.latest_trace_sha1(tmp_path, "t", 1, "ProblemContext")
        sha_g2 = eng.latest_trace_sha1(tmp_path, "t", 1, "GoalsAndValue")
        assert sha_pc is not None and sha_g2 is not None and sha_pc != sha_g2

    def test_read_evidence_for_step_scoped(self, tmp_path):
        _write_evidence(tmp_path, "t", [_trace_line(1), self._g2_trace(1)])
        out = eng.read_evidence_for_step(tmp_path, "t", 1, "GoalsAndValue")
        assert (
            out is not None and "GoalsAndValue" in out and "ProblemContext" not in out
        )

    def test_mentions_scoped_line_level(self, tmp_path):
        _write_evidence(tmp_path, "t", [_trace_line(2)])  # ProblemContext 子2
        assert (
            eng.evidence_mentions_sub_step(tmp_path, "t", 2, "GoalsAndValue") is False
        )
        assert (
            eng.evidence_mentions_sub_step(tmp_path, "t", 2, "ProblemContext") is True
        )

    def test_corrupt_skips_other_node_lines(self, tmp_path):
        # 他节点（ProblemContext）的损坏行不归 GoalsAndValue 判
        corrupt_pc = '{"kind":"skill-trace","minor_stage":"ProblemContext","sub_step":1,"q":["截断'
        _write_evidence(tmp_path, "t", [self._g2_trace(1), corrupt_pc])
        assert (
            eng.corrupt_trace_after_latest(tmp_path, "t", 1, "GoalsAndValue") is False
        )

    def test_corrupt_counts_unattributed_fragment(self, tmp_path):
        # 无 minor_stage 字段的截断碎片无法归属 -> 按本节点候选处理（防卡死回退）
        corrupt = '{"kind":"skill-trace","sub_step":1,"q":["截断'
        _write_evidence(tmp_path, "t", [self._g2_trace(1), corrupt])
        assert eng.corrupt_trace_after_latest(tmp_path, "t", 1, "GoalsAndValue") is True

    def test_reset_deletes_only_own_node(self, tmp_path):
        # GoalsAndValue step-reset 不得删 ProblemContext 留痕（v2.15 前会误删）
        _write_state_full(tmp_path, "t", "understand", 2, sub_step=1)
        _write_evidence(
            tmp_path,
            "t",
            [
                _trace_line(1),  # ProblemContext 子1
                _trace_line(2),  # ProblemContext 子2
                self._g2_trace(1),  # GoalsAndValue 子1
            ],
        )
        ok, _ = eng.reset_state(tmp_path, "t", "1")
        assert ok is True
        text = eng._evidence_path(tmp_path, "t").read_text(encoding="utf-8")
        assert "ProblemContext" in text  # 他节点留痕保留
        assert "GoalsAndValue" not in text  # 本节点 sub_step>=1 已删

    def test_gate_at_stop_ignores_other_node_trace(self, tmp_path, monkeypatch):
        # GoalsAndValue 子1 零 trace 窗口：ProblemContext 子1 trace 不得被误读为本节点的
        _write_state_full(tmp_path, "t", "understand", 2, sub_step=1)
        _write_evidence(tmp_path, "t", [_trace_line(1)])
        action, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert action == "none"  # 本节点无 trace -> 静默放行（非误判推进）
        assert eng.engagement_fence_state(tmp_path, "t") is not None  # S15 窗口仍开


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
        # execute:0 有 rubric（无 evidence 关键词）/ understand:4 rubric=None
        # （被子步骤门控取代），均不依赖 evidence.jsonl -> False
        assert eng.rubric_needs_evidence(eng.get_node("execute", 0)) is False
        assert eng.rubric_needs_evidence(eng.get_node("understand", 4)) is False

    def test_plan2_node_rubric_none_step_gates_need_evidence(self):
        # plan:2 自 2026-07-28 有编排：节点级 rubric=None（understand:4 先例，
        # 语义下沉逐步 gate）-> 节点级 False；子1-4 gate 含 "evidence/" ->
        # step_needs_evidence=True（judge 经 evidence 判一致性，子5 gate=None）
        node = eng.get_node("plan", 2)
        assert eng.rubric_needs_evidence(node) is False
        for i in range(4):
            assert eng.step_needs_evidence(node.sub_steps[i]) is True
        assert node.sub_steps[4].gate is None


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


def _write_artifact(
    tmp_path: Path, phase_dir: str, name: str, content: str = "# 产物\n"
) -> Path:
    """写阶段产物到规范位置（主仓 .claude/<dir>/<name>.md，§8.3 机械门）。"""
    p = tmp_path / ".claude" / phase_dir / f"{name}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
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
        # 子5 gate=None 自动过，不调 judge；末步 -> 无门栏（2026-07-28 起）自动推进 understand:3
        _write_state_full(tmp_path, "t", "understand", 2, sub_step=5)
        called = {"n": 0}

        def _spy(*a, **k):
            called["n"] += 1
            return (True, "")

        monkeypatch.setattr(eng, "run_judge", _spy)
        node = eng.get_node("understand", 2)
        advanced, reason, new_state = eng.gate_and_advance_sub_step(
            tmp_path, "t", node, 5
        )
        assert advanced is True
        assert called["n"] == 0  # gate=None 没调 judge
        reread = eng.load_state(tmp_path, "t")
        assert reread["sub_index"] == 3  # 无门栏：自动推进 understand:3
        assert "held_for_gate" not in reread

    def test_no_evidence_blocks(self, tmp_path, monkeypatch):
        # evidence 缺 -> judge 拿 None artifact -> 判 block（no silent fallback）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        # run_judge 收到 artifact=None 时应判 block；用真实 run_judge 行为模拟
        captured = {}

        def _spy(rubric, label, output, artifact_content=None, prior_verdicts=None):
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

        def _spy(rubric, label, output, artifact_content=None, prior_verdicts=None):
            captured["artifact"] = artifact_content
            return (True, "")

        monkeypatch.setattr(eng, "run_judge", _spy)
        node = eng.get_node("understand", 1)
        eng.gate_and_advance_sub_step(tmp_path, "t", node, 1)
        assert captured["artifact"] is not None
        assert "skill-trace" in captured["artifact"]

    def test_last_step_mech_blocks_missing_artifact(self, tmp_path):
        # §8.3 产物机械门：understand:4 末步子5 gate=None 自动过，
        # 但 understand.md 未写盘 -> 机械门 block（装配义务不落空）
        _write_state_full(tmp_path, "t", "understand", 4, sub_step=5)
        node = eng.get_node("understand", 4)
        advanced, reason, new_state = eng.gate_and_advance_sub_step(
            tmp_path, "t", node, 5
        )
        assert advanced is False
        assert "产物未落地" in reason
        assert new_state["node_attempts"] == 1
        assert eng.load_state(tmp_path, "t")["sub_index"] == 4  # 未推进

    def test_last_step_mech_passes_with_artifact(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 4, sub_step=5)
        _write_artifact(tmp_path, "understands", "t")
        node = eng.get_node("understand", 4)
        advanced, _, new_state = eng.gate_and_advance_sub_step(tmp_path, "t", node, 5)
        assert advanced is True
        assert (new_state["phase"], new_state["sub_index"]) == ("plan", 1)

    def test_last_step_stale_artifact_blocks(self, tmp_path):
        # 新鲜度：产物 mtime 早于本节点 entered_at（预写/残留）-> block
        _write_state_full(tmp_path, "t", "understand", 4, sub_step=5)
        _write_artifact(tmp_path, "understands", "t")
        st = eng.load_state(tmp_path, "t")
        st["history"] = [
            {
                "phase": "understand",
                "sub": 4,
                "entered_at": "2099-01-01T00:00:00",
                "exited_at": None,
                "via": "test",
            }
        ]
        eng.save_state(tmp_path, "t", st)
        node = eng.get_node("understand", 4)
        advanced, reason, _ = eng.gate_and_advance_sub_step(tmp_path, "t", node, 5)
        assert advanced is False
        assert "陈旧" in reason


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

    def test_force_pass_last_step_held_by_subgate(self, tmp_path):
        # §subphase-hold-gate：step-pass 末步放行 ≠ 子阶段放行——门栏扣留，/dl gate 才推进
        # （门栏唯一处 = plan:4，2026-07-28 用户决议）
        _write_state_full(tmp_path, "t", "plan", 4, sub_step=5)
        ok, msg = eng.force_pass_sub_step(tmp_path, "t", str(tmp_path))
        assert ok is True
        assert "门栏" in msg
        reread = eng.load_state(tmp_path, "t")
        assert reread["sub_index"] == 4  # 扣留：不推进
        assert reread["held_for_gate"] is True

    def test_force_pass_rejects_node_without_sub_steps(self, tmp_path):
        _write_state_full(tmp_path, "t", "execute", 0)  # execute:0 无 sub_steps
        ok, msg = eng.force_pass_sub_step(tmp_path, "t", str(tmp_path))
        assert ok is False
        assert "无子步骤" in msg


class TestUnderstand4Orchestration:
    """understand:4 SuccessCriteria 5 子步骤编排
    （designs/success-criteria-substeps-design.md，2026-07-27 用户确认 5 步 + hold）。

    关键不对称（第四种）：混合命题，轴心 = 规范性目标的可检验化转换——
    对齐=结构性，可检验化=技术转换（Volere fit criterion），验收可行性=事实性
    （本地单层源），阈值/验收取舍=规范性（拍板归用户子5）；
    hold_for_gate=True（隔离测试语义，首个 advance="phase" 的 hold 节点）。
    """

    def _steps(self):
        node = eng.get_node("understand", 4)
        assert node.sub_steps is not None and len(node.sub_steps) == 5
        return node.sub_steps

    def test_gate_rubric_none_mech_kept(self):
        node = eng.get_node("understand", 4)
        assert node.gate_rubric is None  # 子阶段级 rubric 被子步骤门控取代
        assert (
            node.gate_mech == eng.GateMech.ARTIFACT_EXISTS
        )  # understand.md 机械门保留
        assert node.artifact == "understand.md"
        assert node.advance == "phase"
        assert node.minor_key == "SuccessCriteria"

    def test_hold_for_gate_enabled(self):
        # 2026-07-28 用户决议：围栏只设在 plan 完成——understand 全部无门栏
        assert eng.get_node("understand", 4).hold_for_gate is False

    def test_shorts_order(self):
        shorts = [s.short for s in self._steps()]
        assert shorts == [
            "成功标准引出",
            "可检验化",
            "验收方式设计",
            "归一化陈述",
            "读回确认",
        ]

    def test_record_all_true(self):
        assert all(s.record for s in self._steps())

    def test_input_chain(self):
        steps = self._steps()
        assert "GoalsAndValue.step4.statements" in steps[0].input  # 跨节点吃上游输出
        assert "ScopeAndConstraints.step4.statements" in steps[0].input
        assert steps[1].input == "step1.criteria_candidates"
        assert steps[2].input == "step2.testable_criteria"
        assert steps[3].input == "step3.criteria_with_acceptance"
        assert steps[4].input == "step4.statements"

    def test_step1_elicit_dual_conclusion(self):
        # 双结论制（§3.5 #3）：「只能定性验收」合法——防硬编量化指标
        s1 = self._steps()[0]
        assert "怎么知道它达成了" in s1.purpose and "双向追溯" in s1.purpose
        assert "纯定性目标" in s1.purpose and "AskUserQuestion" in s1.ref
        assert "minor_stage=SuccessCriteria 且 sub_step==1" in s1.gate
        assert "追溯放水" in s1.gate and "偷懒" in s1.gate

    def test_step2_fit_criterion_fence(self):
        s2 = self._steps()[1]
        assert s2.fence_allow == ("Bash",)  # S15：条件性基线测量
        for needle in ("fit criterion", "模糊词", "基线", "阈值提案", "退回", "假指标"):
            assert needle in s2.purpose, f"子2 purpose 缺 {needle}"
        for needle in ("sub_step==2", "拍脑袋", "假指标", "拍板"):
            assert needle in s2.gate, f"子2 gate 缺 {needle}"

    def test_step3_acceptance_fence(self):
        s3 = self._steps()[2]
        assert s3.fence_allow == ("Bash",)  # S15：手段存在性本地验证
        for needle in (
            "INCOSE",
            "三态",
            "验收手段待建",
            "triggered",
            "continuous",
            "证据形式",
        ):
            assert needle in s3.purpose, f"子3 purpose 缺 {needle}"
        for needle in ("sub_step==3", "编造", "事后验证未标注"):
            assert needle in s3.gate, f"子3 gate 缺 {needle}"

    def test_step4_normalization(self):
        s4 = self._steps()[3]
        assert s4.kind == "skill" and s4.ref == "define-problem"
        for needle in ("原子", "去上下文", "验收包", "solution-free"):
            assert needle in s4.purpose, f"子4 purpose 缺 {needle}"
        assert "sub_step==4" in s4.gate and "不传导" in s4.gate

    def test_step5_readback_gate_none(self):
        s5 = self._steps()[4]
        assert s5.gate is None  # 交互步，trace 存在即过
        assert s5.record is True
        assert "阈值拍板" in s5.purpose and "验收方式认可" in s5.purpose

    def test_selfcheck_no_quality_criteria_leak(self):
        # Goodhart 分层守卫（同前三个节点）：gate 黑盒措辞不得进 checklist
        for s in self._steps():
            if not s.selfcheck:
                continue
            for banned in ("从严裁量", "追溯放水", "拍脑袋", "假指标", "编造"):
                assert banned not in s.selfcheck, f"{s.short} selfcheck 泄漏 {banned}"

    def test_u4_last_step_advances_to_plan1(self, tmp_path):
        # 2026-07-28 围栏只设 plan 完成：understand:4 末步（子5）pass ->
        # 无门栏无闸门，直接推进 plan:1（跨阶段自动续轮路径）
        # §8.3：推进前置 = understand.md 已装配写盘（机械门）
        _write_state_full(tmp_path, "t", "understand", 4, sub_step=5)
        _write_evidence(tmp_path, "t", [_sc_trace_line(5)])
        _write_artifact(tmp_path, "understands", "t")
        action, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert action == "advanced"
        st = eng.load_state(tmp_path, "t")
        assert st["phase"] == "plan"
        assert st["sub_index"] == 1
        assert st["node"] == "plan:1"
        assert st["sub_step_index"] == 1  # 新节点首步
        assert "held_for_gate" not in st

    def test_u4_last_step_blocks_without_artifact(self, tmp_path):
        # §8.3 产物机械门：子5 trace 合格但 understand.md 未写盘 -> block
        # （装配义务不被 trace 存在骗过；understand->plan 无人工闸门后的硬兜底）
        _write_state_full(tmp_path, "t", "understand", 4, sub_step=5)
        _write_evidence(tmp_path, "t", [_sc_trace_line(5)])
        action, reason, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert action == "block"
        assert "产物未落地" in reason
        st = eng.load_state(tmp_path, "t")
        assert st["sub_index"] == 4  # 未推进
        assert st["node_attempts"] == 1


class TestPlan1Orchestration:
    """plan:1 DesignSolution 6 子步骤编排
    （designs/design-solution-substeps-design.md，2026-07-27 用户确认 6 步 + hold）。

    关键不对称（第五种）：创造性生成×代码接地双轴心——首个创造性生成节点
    （发散防 design fixation）且解必须锚定本仓代码现实（勘察防凭空设计）；
    hold_for_gate=True（隔离测试语义，advance="sub" hold 与 understand:2/3 同构）。
    """

    def _steps(self):
        node = eng.get_node("plan", 1)
        assert node.sub_steps is not None and len(node.sub_steps) == 6
        return node.sub_steps

    def test_node_fields(self):
        node = eng.get_node("plan", 1)
        assert node.label == "设计解决方案"
        assert node.gate_rubric is None  # 子阶段级 rubric 被子步骤门控取代
        assert node.gate_mech == eng.GateMech.NONE  # design.md 动态文件名无机械门
        assert node.artifact is None  # 产物强制三层兜底（design §3）
        assert node.advance == "sub"
        assert node.minor_key == "DesignSolution"
        assert node.skill is None

    def test_hold_for_gate_enabled(self):
        # 2026-07-28 用户决议：围栏只设在 plan 完成——plan:1/2/3 无门栏
        assert eng.get_node("plan", 1).hold_for_gate is False

    def test_shorts_order(self):
        shorts = [s.short for s in self._steps()]
        assert shorts == [
            "现状勘察",
            "方案发散",
            "可行性验证",
            "评估提案",
            "归一化陈述",
            "读回确认",
        ]

    def test_record_all_true(self):
        assert all(s.record for s in self._steps())

    def test_input_chain(self):
        steps = self._steps()
        assert "understand.md" in steps[0].input  # 跨阶段吃 understand 终态
        assert steps[1].input == "step1.terrain_map"
        assert steps[2].input == "step2.candidates + step1.terrain_map"
        assert steps[3].input == "step3.feasibility_verdicts"
        assert steps[4].input == "step4.recommendation"
        assert steps[5].input == "step5.design_statements"

    def test_step1_terrain_fence(self):
        s1 = self._steps()[0]
        assert s1.fence_allow == ("Bash",)  # S15：codegraph/新鲜度/数据契约核实
        for needle in ("现状地图四要素", "新鲜度", "file:line", "接地"):
            assert needle in s1.purpose, f"子1 purpose 缺 {needle}"
        for needle in ("sub_step==1", "编造", "漫游", "训练记忆"):
            assert needle in s1.gate, f"子1 gate 缺 {needle}"

    def test_step2_diverge_dual_conclusion(self):
        s2 = self._steps()[1]
        for needle in ("≥3", "禁评估", "双结论", "平权", "设计空间唯一"):
            assert needle in s2.purpose, f"子2 purpose 缺 {needle}"
        for needle in ("sub_step==2", "伪候选", "凭空设计", "偷懒"):
            assert needle in s2.gate, f"子2 gate 缺 {needle}"

    def test_step3_feasibility_fence(self):
        s3 = self._steps()[2]
        assert s3.fence_allow == ("Bash",)  # S15：存在性/影响面本地核验
        for needle in ("重复造轮子", "影响面", "三态", "H9", "可测试性", "H1"):
            assert needle in s3.purpose, f"子3 purpose 缺 {needle}"
        for needle in ("sub_step==3", "编造", "漏检", "拍脑袋"):
            assert needle in s3.gate, f"子3 gate 缺 {needle}"

    def test_step4_pugh_redteam(self):
        s4 = self._steps()[3]
        assert s4.fence_allow == ("Agent",)  # S15：条件红队
        for needle in ("Pugh", "双向追溯", "条件红队", "只提案不拍板"):
            assert needle in s4.purpose, f"子4 purpose 缺 {needle}"
        for needle in ("sub_step==4", "拍板", "凑结论", "追溯漏项"):
            assert needle in s4.gate, f"子4 gate 缺 {needle}"

    def test_step5_normalization(self):
        s5 = self._steps()[4]
        assert s5.kind == "skill" and s5.ref == "define-problem"
        for needle in ("原子", "去上下文", "改动清单", "验收包映射", "被否方案"):
            assert needle in s5.purpose, f"子5 purpose 缺 {needle}"
        assert "sub_step==5" in s5.gate and "不传导" in s5.gate

    def test_step6_readback_gate_none(self):
        s6 = self._steps()[5]
        assert s6.gate is None  # 交互步，trace 存在即过
        assert s6.record is True
        for needle in ("选型拍板", "权重", "假设接受", "design.md", "禁二次创作"):
            assert needle in s6.purpose, f"子6 purpose 缺 {needle}"

    def test_selfcheck_no_quality_criteria_leak(self):
        # Goodhart 分层守卫（同前四个节点）：gate 黑盒措辞不得进 checklist
        for s in self._steps():
            if not s.selfcheck:
                continue
            for banned in (
                "从严裁量",
                "拍脑袋",
                "编造",
                "伪候选",
                "漫游",
                "漏检",
                "凑结论",
            ):
                assert banned not in s.selfcheck, f"{s.short} selfcheck 泄漏 {banned}"

    def test_plan1_last_step_advances_to_plan2(self, tmp_path):
        # 2026-07-28 围栏只设 plan 完成：plan:1 末步（子6）pass ->
        # 无门栏自动推进 plan:2，跨节点 sub_step_index 重置
        _write_state_full(tmp_path, "t", "plan", 1, sub_step=6)
        _write_evidence(tmp_path, "t", [_ds_trace_line(6)])
        action, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert action == "advanced"
        st = eng.load_state(tmp_path, "t")
        assert st["phase"] == "plan"
        assert st["sub_index"] == 2
        assert st["node"] == "plan:2"
        assert st["sub_step_index"] == 1  # plan:2 有编排 -> 重置为首步
        assert "held_for_gate" not in st
        assert st["gate"] == "pending"  # plan->execute 大闸门不叠加


class TestPlan2Orchestration:
    """plan:2 TaskBreakdown 5 子步骤编排
    （designs/task-breakdown-substeps-design.md，2026-07-28 用户确认 5 步 + hold +
    label 改名「拆解任务与阶段」）。

    关键不对称（第六种）：保真转换 × 执行接地——输入对象已存在且已拍板
    （无发散步；清点基线使「一致性」可判）；hold_for_gate=True。
    v2.20（plan:3 加入）：advance 由 "phase" 改 "sub"——不再是 plan 末子阶段，
    hold 语义转为与 understand:2/3 同构（放行后推进 plan:3，无 PHASE_DONE 通道）。
    """

    def _steps(self):
        node = eng.get_node("plan", 2)
        assert node.sub_steps is not None and len(node.sub_steps) == 5
        return node.sub_steps

    def test_node_fields(self):
        node = eng.get_node("plan", 2)
        assert node.label == "拆解任务与阶段"
        assert (
            node.gate_rubric is None
        )  # 子阶段级 rubric 被子步骤门控取代（understand:4 先例）
        assert (
            node.gate_mech == eng.GateMech.ARTIFACT_EXISTS
        )  # plan.md 静态路径，机械门保留
        assert node.artifact == "plan.md"
        assert node.advance == "sub"  # v2.20 plan:3 加入后不再是末子阶段
        assert node.minor_key == "TaskBreakdown"
        assert node.skill is None  # 编排节点 skill 走 Step ref（同 plan:1）
        # artifact_on_release 不再显式声明（字段仅 advance="phase" 编排末节点
        # 注入第三态读取；sub 节点 phase_done_channel_open 恒 False）

    def test_artifact_on_release_default_true(self):
        # False 两处：understand:4（2026-07-28 无门栏，产物子5 内装配）与
        # plan:4（v2.21，产物节子5 内装配，hold 前落地）；
        # plan:3 自 v2.21 起 advance="sub"（字段不被读取，不再纳入断言）
        assert eng.get_node("understand", 4).artifact_on_release is False
        assert eng.get_node("plan", 4).artifact_on_release is False
        for nid, n in eng._NODES.items():
            if nid not in ("understand:4", "plan:3", "plan:4"):
                assert n.artifact_on_release is True, nid

    def test_hold_for_gate_enabled(self):
        # 2026-07-28 用户决议：围栏只设在 plan 完成——plan:1/2/3 无门栏
        assert eng.get_node("plan", 2).hold_for_gate is False

    def test_shorts_order(self):
        shorts = [s.short for s in self._steps()]
        assert shorts == [
            "清点基线",
            "切分排序",
            "锚点核验",
            "归一化步骤",
            "读回装配",
        ]

    def test_record_all_true(self):
        assert all(s.record for s in self._steps())

    def test_input_chain(self):
        steps = self._steps()
        assert "DesignSolution" in steps[0].input  # 跨节点吃 plan:1 设计包
        assert steps[1].input == "step1.element_baseline"
        assert steps[2].input == "step2.task_units + step1.element_baseline"
        assert steps[3].input == "step3.verified_units"
        assert steps[4].input == "step4.execution_steps"

    def test_step1_baseline_fence(self):
        s1 = self._steps()[0]
        assert s1.fence_allow == ("Bash",)  # S15：grep evidence 设计包 trace
        for needle in ("原子改动要素清单", "要素 ID", "出处", "只提取不创作", "原文"):
            assert needle in s1.purpose, f"子1 purpose 缺 {needle}"
        for needle in ("sub_step==1", "二次创作", "编造", "失真"):
            assert needle in s1.gate, f"子1 gate 缺 {needle}"

    def test_step2_decompose_dual_conclusion(self):
        s2 = self._steps()[1]
        assert s2.fence_allow == ("Bash",)  # S15：codegraph 依赖取证
        assert "writing-plans" in s2.ref  # 粒度与切片原则真源
        for needle in (
            "纵向切片",
            "H9 预算",
            "拓扑排序",
            "TDD",
            "只提案不拍板",
            "单阶段不可拆",
        ):
            assert needle in s2.purpose, f"子2 purpose 缺 {needle}"
        for needle in ("sub_step==2", "横向", "违反依赖", "丢要素", "偷懒"):
            assert needle in s2.gate, f"子2 gate 缺 {needle}"

    def test_step3_anchor_fence(self):
        s3 = self._steps()[2]
        assert s3.fence_allow == ("Bash",)  # S15：锚点本地核验
        for needle in ("测试接缝", "No Placeholders", "三态", "零上下文"):
            assert needle in s3.purpose, f"子3 purpose 缺 {needle}"
        for needle in ("sub_step==3", "编造", "没真核验", "placeholder"):
            assert needle in s3.gate, f"子3 gate 缺 {needle}"

    def test_step4_normalization(self):
        s4 = self._steps()[3]
        assert s4.kind == "skill"
        assert "define-problem" in s4.ref
        for needle in (
            "原子",
            "去上下文",
            "Consumes",
            "验收包映射",
            "追溯锚",
            "可执行验证",
        ):
            assert needle in s4.purpose, f"子4 purpose 缺 {needle}"
        for needle in ("sub_step==4", "不一致", "复合句", "漏项"):
            assert needle in s4.gate, f"子4 gate 缺 {needle}"

    def test_step5_readback_gate_none(self):
        s5 = self._steps()[4]
        assert s5.gate is None  # 交互步，trace 存在即过
        assert s5.record is True
        for needle in ("阶段/粒度拍板", "假设接受", "plan.md", "禁二次创作"):
            assert needle in s5.purpose, f"子5 purpose 缺 {needle}"

    def test_selfcheck_no_quality_criteria_leak(self):
        # Goodhart 分层守卫（同前五个节点）：gate 黑盒措辞不得进 checklist
        for s in self._steps():
            if not s.selfcheck:
                continue
            for banned in (
                "从严裁量",
                "编造",
                "偷懒",
                "失真",
                "没真核验",
                "二次创作判",
            ):
                assert banned not in s.selfcheck, f"{s.short} selfcheck 泄漏 {banned}"

    def test_plan2_last_step_advances_to_plan3(self, tmp_path):
        # 2026-07-28 围栏只设 plan 完成：plan:2 末步（子5）pass ->
        # 无门栏自动推进 plan:3，跨节点 sub_step_index 重置
        _write_state_full(tmp_path, "t", "plan", 2, sub_step=5)
        _write_evidence(tmp_path, "t", [_tb_trace_line(5)])
        _write_artifact(tmp_path, "plans", "t")  # §8.3 机械门：plan.md 已装配
        action, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert action == "advanced"
        st = eng.load_state(tmp_path, "t")
        assert st["phase"] == "plan"
        assert st["sub_index"] == 3
        assert st["node"] == "plan:3"
        assert st["sub_step_index"] == 1  # plan:3 有编排 -> 重置为首步
        assert "held_for_gate" not in st
        assert st["gate"] == "pending"  # plan->execute 大闸门不叠加


class TestPlan3Orchestration:
    """plan:3 CapabilityToolSelection 6 子步骤编排
    （designs/capability-tool-selection-substeps-design.md，2026-07-28 用户确认
    6 步 + hold + gate_mech 保持 ARTIFACT_EXISTS）。

    关键不对称（第七种）：有限枚举 × 配置接地——能力空间=可枚举注册表非生成
    空间（无发散步）；主敌=幽灵能力/能力错配/tool overload/漏配强制项。
    v2.21（plan:4 加入）：advance 由 "phase" 改 "sub"——不再是 plan 末子阶段，
    hold 语义转为与 understand:2/3、plan:2(v2.20) 同构（放行后推进 plan:4，
    无 PHASE_DONE 通道）。
    """

    def _steps(self):
        node = eng.get_node("plan", 3)
        assert node.sub_steps is not None and len(node.sub_steps) == 6
        return node.sub_steps

    def test_node_fields(self):
        node = eng.get_node("plan", 3)
        assert node.label == "选择能力与工具"
        assert (
            node.gate_rubric is None
        )  # 子阶段级 rubric 被子步骤门控取代（understand:4/plan:2 先例）
        assert (
            node.gate_mech == eng.GateMech.ARTIFACT_EXISTS
        )  # 声明式（机械门未实现，design §5 #9）
        assert node.artifact == "plan.md"
        assert node.advance == "sub"  # v2.21 plan:4 加入后不再是末子阶段
        assert node.minor_key == "CapabilityToolSelection"
        assert node.skill is None  # 编排节点 skill 走 Step ref（同 plan:1/2）
        # artifact_on_release 不再显式声明（字段仅 advance="phase" 编排末节点
        # 注入第三态读取；sub 节点 phase_done_channel_open 恒 False）

    def test_hold_for_gate_enabled(self):
        # 2026-07-28 用户决议：围栏只设在 plan 完成——plan:1/2/3 无门栏
        assert eng.get_node("plan", 3).hold_for_gate is False

    def test_shorts_order(self):
        shorts = [s.short for s in self._steps()]
        assert shorts == [
            "需求清点",
            "能力盘点",
            "匹配选型",
            "可用性核验",
            "归一化能力包",
            "读回装配",
        ]

    def test_record_all_true(self):
        assert all(s.record for s in self._steps())

    def test_input_chain(self):
        steps = self._steps()
        assert "TaskBreakdown" in steps[0].input  # 跨节点吃 plan:2 执行包
        assert steps[1].input == "step1.need_baseline"
        assert steps[2].input == "step2.capability_registry + step1.need_baseline"
        assert steps[3].input == "step3.binding_proposals"
        assert steps[4].input == "step4.verified_bindings"
        assert steps[5].input == "step5.capability_packages"

    def test_step1_baseline_fence(self):
        s1 = self._steps()[0]
        assert s1.fence_allow == ("Bash",)  # S15：grep evidence 执行包 trace
        for needle in ("操作类型", "任务 ID", "出处", "只提取不创作", "原文"):
            assert needle in s1.purpose, f"子1 purpose 缺 {needle}"
        for needle in ("sub_step==1", "二次创作", "编造", "失真"):
            assert needle in s1.gate, f"子1 gate 缺 {needle}"

    def test_step2_registry_dual_conclusion(self):
        s2 = self._steps()[1]
        assert s2.fence_allow == ("Bash",)  # S15：注册表枚举 + CLI/MCP 核对
        for needle in ("逐字引用", "注册表", "强制路由", "H15", "内置工具足够"):
            assert needle in s2.purpose, f"子2 purpose 缺 {needle}"
        for needle in ("sub_step==2", "幽灵能力", "漏配", "凭记忆编造", "偷懒"):
            assert needle in s2.gate, f"子2 gate 缺 {needle}"

    def test_step3_matching_redteam_fence(self):
        s3 = self._steps()[2]
        assert s3.fence_allow == ("Agent",)  # S15：条件红队（同 DesignSolution 子4）
        for needle in (
            "最小集",
            "无绑定=不加载",
            "成本相称",
            "强制项优先",
            "双向追溯",
            "只提案不拍板",
        ):
            assert needle in s3.purpose, f"子3 purpose 缺 {needle}"
        for needle in ("sub_step==3", "过载", "凭名字猜", "替代", "拍板"):
            assert needle in s3.gate, f"子3 gate 缺 {needle}"

    def test_step4_availability_fence(self):
        s4 = self._steps()[3]
        assert s4.fence_allow == ("Bash",)  # S15：可用性本地实测
        for needle in ("三态", "MCP", "环境前提", "只标注不裁决"):
            assert needle in s4.purpose, f"子4 purpose 缺 {needle}"
        for needle in ("sub_step==4", "编造", "没真核验"):
            assert needle in s4.gate, f"子4 gate 缺 {needle}"

    def test_step5_normalization(self):
        s5 = self._steps()[4]
        assert s5.kind == "skill"
        assert "define-problem" in s5.ref
        for needle in (
            "原子",
            "去上下文",
            "必先 skill",
            "强制门禁对齐",
            "子代理策略",
            "不加载清单",
            "假设传导",
        ):
            assert needle in s5.purpose, f"子5 purpose 缺 {needle}"
        for needle in ("sub_step==5", "不一致", "复合句", "幽灵回潮"):
            assert needle in s5.gate, f"子5 gate 缺 {needle}"

    def test_step6_readback_gate_none(self):
        s6 = self._steps()[5]
        assert s6.gate is None  # 交互步，trace 存在即过
        assert s6.record is True
        for needle in ("映射拍板", "假设接受", "plan.md", "禁二次创作"):
            assert needle in s6.purpose, f"子6 purpose 缺 {needle}"

    def test_selfcheck_no_quality_criteria_leak(self):
        # Goodhart 分层守卫（同前六个节点）：gate 黑盒措辞不得进 checklist
        for s in self._steps():
            if not s.selfcheck:
                continue
            for banned in (
                "从严裁量",
                "编造判",
                "偷懒",
                "失真判",
                "没真核验",
                "二次创作判",
                "幽灵能力判",
                "过载判",
            ):
                assert banned not in s.selfcheck, f"{s.short} selfcheck 泄漏 {banned}"

    def test_plan3_last_step_advances_to_plan4(self, tmp_path):
        # 2026-07-28 围栏只设 plan 完成：plan:3 末步（子6）pass ->
        # 无门栏自动推进 plan:4，跨节点 sub_step_index 重置
        _write_state_full(tmp_path, "t", "plan", 3, sub_step=6)
        _write_evidence(tmp_path, "t", [_cts_trace_line(6)])
        _write_artifact(tmp_path, "plans", "t")  # §8.3 机械门：plan.md 已装配
        action, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert action == "advanced"
        st = eng.load_state(tmp_path, "t")
        assert st["phase"] == "plan"
        assert st["sub_index"] == 4
        assert st["node"] == "plan:4"
        assert st["sub_step_index"] == 1  # plan:4 有编排 -> 重置为首步
        assert "held_for_gate" not in st
        assert st["gate"] == "pending"  # plan->execute 大闸门不叠加


class TestPlan4Orchestration:
    """plan:4 ExecutionPlanCheckpoints 5 子步骤编排
    （designs/execution-plan-checkpoints-substeps-design.md，2026-07-28 用户确认
    5 步 + hold + gate_mech=NONE[有意偏离 plan:2/3 的 ARTIFACT_EXISTS——
    对 plan.md 语义恒真，保留=虚假防线暗示]）。

    关键不对称（第八种）：时序控制 × 风险配平——首个运行时控制结构设计节点
    （对象不是内容是控制流）+ 首个四源聚合节点；主敌=检查点虚设/误差复利/
    密度失配/失败处置缺失/并行冲突/返回物无验收/聚合失真。
    advance="phase" hold 与 understand:4/plan:3(v2.20) 同构，无新机制路径。
    """

    def _steps(self):
        node = eng.get_node("plan", 4)
        assert node.sub_steps is not None and len(node.sub_steps) == 5
        return node.sub_steps

    def test_node_fields(self):
        node = eng.get_node("plan", 4)
        assert node.label == "制定执行计划和检查点"
        assert (
            node.gate_rubric is None
        )  # 子阶段级 rubric 被子步骤门控取代（understand:4/plan:2/3 先例第四次）
        # §8.3（2026-07-31）：ARTIFACT_EXISTS 对 plan.md 语义恒真 -> 节存在检查
        assert node.gate_mech == eng.GateMech.ARTIFACT_CONTAINS
        assert node.artifact_contains == ("执行计划与检查点",)
        assert node.artifact == "plan.md"
        assert node.advance == "phase"  # plan 末子阶段 -> 推进 execute
        assert node.minor_key == "ExecutionPlanCheckpoints"
        assert node.skill is None  # 编排节点 skill 走 Step ref（同 plan:1/2/3）
        assert node.artifact_on_release is False  # 产物节子5 内装配（hold 前落地）

    def test_hold_for_gate_enabled(self):
        # 全工作流唯一门栏（2026-07-28 用户决议：围栏只设在 plan 完成）
        assert eng.get_node("plan", 4).hold_for_gate is True

    def test_shorts_order(self):
        shorts = [s.short for s in self._steps()]
        assert shorts == [
            "四源清点",
            "调度与检查点",
            "锚点核验",
            "归一化计划包",
            "读回装配",
        ]

    def test_record_all_true(self):
        assert all(s.record for s in self._steps())

    def test_input_chain(self):
        steps = self._steps()
        assert (
            "design.md" in steps[0].input
        )  # 四源聚合：design+plan+understand+evidence
        assert "understand.md" in steps[0].input
        assert steps[1].input == "step1.control_baseline"
        assert steps[2].input == "step2.control_proposals"
        assert steps[3].input == "step3.verified_controls"
        assert steps[4].input == "step4.execution_plan_packages"

    def test_step1_baseline_fence(self):
        s1 = self._steps()[0]
        assert s1.fence_allow == ("Bash",)  # S15：grep evidence plan:1/2/3 trace
        for needle in (
            "任务 DAG",
            "验收包",
            "triggered",
            "出处",
            "只提取不创作",
            "原文",
        ):
            assert needle in s1.purpose, f"子1 purpose 缺 {needle}"
        for needle in ("sub_step==1", "二次创作", "编造", "漏源"):
            assert needle in s1.gate, f"子1 gate 缺 {needle}"

    def test_step2_scheduling_redteam_fence(self):
        s2 = self._steps()[1]
        assert s2.fence_allow == ("Agent",)  # S15：条件红队（同 plan:1 子4/plan:3 子3）
        for needle in (
            "并行分组",
            "文件互斥面",
            "返回契约",
            "失败路由",
            "零判断词",
            "goal anchoring",
            "可逆性",
            "只提案不拍板",
            "零用户检查点",
        ):
            assert needle in s2.purpose, f"子2 purpose 缺 {needle}"
        for needle in ("sub_step==2", "虚设", "视情况", "拍脑袋", "越权"):
            assert needle in s2.gate, f"子2 gate 缺 {needle}"

    def test_step3_anchor_fence(self):
        s3 = self._steps()[2]
        assert s3.fence_allow == ("Bash",)  # S15：dry-run + 交集实算 + 锚点本地核验
        for needle in ("dry-run", "交集", "三态", "只标注不裁决"):
            assert needle in s3.purpose, f"子3 purpose 缺 {needle}"
        for needle in ("sub_step==3", "实算", "没真核验", "编造"):
            assert needle in s3.gate, f"子3 gate 缺 {needle}"

    def test_step4_normalization(self):
        s4 = self._steps()[3]
        assert s4.kind == "skill"
        assert "define-problem" in s4.ref
        for needle in (
            "原子",
            "去上下文",
            "并行分组",
            "返回契约",
            "通过判据",
            "失败路由",
            "验收包映射",
            "goal anchoring",
            "假设传导",
        ):
            assert needle in s4.purpose, f"子4 purpose 缺 {needle}"
        for needle in ("sub_step==4", "不一致", "复合句", "判断词回潮", "漏配"):
            assert needle in s4.gate, f"子4 gate 缺 {needle}"

    def test_step5_readback_gate_none(self):
        s5 = self._steps()[4]
        assert s5.gate is None  # 交互步，trace 存在即过
        assert s5.record is True
        for needle in (
            "密度与类型拍板",
            "假设接受",
            "冻结策略",
            "plan.md",
            "禁二次创作",
        ):
            assert needle in s5.purpose, f"子5 purpose 缺 {needle}"

    def test_selfcheck_no_quality_criteria_leak(self):
        # Goodhart 分层守卫（同前七个节点）：gate 黑盒措辞不得进 checklist
        for s in self._steps():
            if not s.selfcheck:
                continue
            for banned in (
                "从严裁量",
                "编造判",
                "偷懒",
                "没真核验",
                "二次创作判",
                "虚设判",
                "越权判",
            ):
                assert banned not in s.selfcheck, f"{s.short} selfcheck 泄漏 {banned}"

    def test_plan4_last_step_held_not_advanced(self, tmp_path):
        # pinning（症状 M #7）：plan:4 末步（子5）pass -> 扣留不推进
        _write_state_full(tmp_path, "t", "plan", 4, sub_step=5)
        _write_evidence(tmp_path, "t", [_epc_trace_line(5)])
        # §8.3 机械门（ARTIFACT_CONTAINS）：「执行计划与检查点」节已装配
        _write_artifact(tmp_path, "plans", "t", "# 执行步骤\n\n## 执行计划与检查点\n")
        action, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert action == "advanced"
        st = eng.load_state(tmp_path, "t")
        assert st["phase"] == "plan"
        assert st["sub_index"] == 4  # 扣留：不推进
        assert st["held_for_gate"] is True

    def test_plan4_release_subgate_no_advance(self, tmp_path):
        # pinning（advance="phase" 的 hold 节点，与 understand:4/plan:3(v2.20) 同构）：
        # plan:4 门栏放行**只放行不推进**——plan->execute 大闸门不被
        # subgate-pass 静默吸收（execution-plan-checkpoints-substeps-design §2）
        _write_state_full(tmp_path, "t", "plan", 4, sub_step=5)
        st = eng.load_state(tmp_path, "t")
        st["held_for_gate"] = True
        eng.save_state(tmp_path, "t", st)
        ok, msg = eng.release_subgate(tmp_path, "t", str(tmp_path))
        assert ok is True
        assert "PHASE_DONE" in msg  # 指引模型 PHASE_DONE 撞大闸门
        reread = eng.load_state(tmp_path, "t")
        assert reread["phase"] == "plan"  # 不推进
        assert reread["sub_index"] == 4
        assert "held_for_gate" not in reread
        rec = json.loads(eng.read_evidence(tmp_path, "t").strip().splitlines()[-1])
        assert rec["via"] == "manual-subgate-pass"
        assert rec["sub_step"] == 5

    def test_plan4_full_path_release_then_phase_advance(self, tmp_path):
        # pinning 全路径：末步扣留 -> /dl gate（subgate-pass，不推进）
        # -> phase 闸门放行后 advance_state -> execute（gate=passed）
        _write_state_full(tmp_path, "t", "plan", 4, sub_step=5)
        st = eng.load_state(tmp_path, "t")
        st["held_for_gate"] = True
        eng.save_state(tmp_path, "t", st)
        ok, _ = eng.release_subgate(tmp_path, "t", str(tmp_path))
        assert ok is True
        assert eng.load_state(tmp_path, "t")["phase"] == "plan"
        # phase 大闸门放行（/dl gate 第二次）后的推进
        st2 = eng.load_state(tmp_path, "t")
        st2["gate"] = "passed"
        eng.save_state(tmp_path, "t", st2)
        new_state = eng.advance_state(tmp_path, "t", via="test")
        assert new_state["phase"] == "execute"
        assert new_state["node"] == "execute:0"
        assert new_state["sub_index"] == 0
        assert new_state["sub_step_index"] == 0  # execute:0 无编排 -> 0
        assert new_state["gate"] == "passed"  # plan in GATED_AFTER


class TestPhaseDoneChannelOpen:
    """phase_done_channel_open（understand:4 专属）：PHASE_DONE 通道打开判据。

    单源判据，workflow_advance（Stop fall-through）与 workflow_phase（注入第三态）
    两处引用。仅 advance="phase" 编排末节点 + 末步已判过 + 门栏未扣留 -> True。
    """

    def _judged_u4_state(self, tmp_path, held=False):
        _write_state_full(tmp_path, "t", "understand", 4, sub_step=5)
        _write_evidence(tmp_path, "t", [_sc_trace_line(5)])
        st = eng.load_state(tmp_path, "t")
        sha = eng.latest_trace_sha1(tmp_path, "t", 5, "SuccessCriteria")
        st["last_judged_trace"] = {"understand:4#5": sha}
        if held:
            st["held_for_gate"] = True
        eng.save_state(tmp_path, "t", st)
        return eng.load_state(tmp_path, "t")

    def test_open_when_final_judged_and_released(self, tmp_path):
        st = self._judged_u4_state(tmp_path)
        node = eng.get_node("understand", 4)
        assert eng.phase_done_channel_open(tmp_path, "t", st, node) is True

    def test_closed_when_held(self, tmp_path):
        # 门栏扣留中 PHASE_DONE 无效，唯一出口 /dl gate
        st = self._judged_u4_state(tmp_path, held=True)
        node = eng.get_node("understand", 4)
        assert eng.phase_done_channel_open(tmp_path, "t", st, node) is False

    def test_closed_when_trace_unjudged(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 4, sub_step=5)
        _write_evidence(tmp_path, "t", [_sc_trace_line(5)])
        st = eng.load_state(tmp_path, "t")  # 无 last_judged_trace
        node = eng.get_node("understand", 4)
        assert eng.phase_done_channel_open(tmp_path, "t", st, node) is False

    def test_closed_when_not_final_step(self, tmp_path):
        st = self._judged_u4_state(tmp_path)
        st["sub_step_index"] = 4  # 非末步
        node = eng.get_node("understand", 4)
        assert eng.phase_done_channel_open(tmp_path, "t", st, node) is False

    def test_closed_for_sub_advance_node(self, tmp_path):
        # advance="sub" 编排节点（understand:2）无 PHASE_DONE 通道
        _write_state_full(tmp_path, "t", "understand", 2, sub_step=5)
        _write_evidence(tmp_path, "t", [_g2_trace_line(5)])
        st = eng.load_state(tmp_path, "t")
        sha = eng.latest_trace_sha1(tmp_path, "t", 5, "GoalsAndValue")
        st["last_judged_trace"] = {"understand:2#5": sha}
        node = eng.get_node("understand", 2)
        assert eng.phase_done_channel_open(tmp_path, "t", st, node) is False


class TestSubphaseHoldGate:
    """§subphase-hold-gate：hold_for_gate 节点末步过门控后无条件扣留，
    /dl gate（engine subgate-pass）放行。"""

    def test_hold_field_only_on_gate_nodes(self):
        # 门栏唯一处（2026-07-28 用户决议：围栏只设在 plan 完成）：
        # plan:4（ExecutionPlanCheckpoints，advance="phase" hold），
        # 其余节点全 False（全量遍历 _NODES，禁抽样——症状 M #7）
        for nid, node in eng._NODES.items():
            if nid == "plan:4":
                assert node.hold_for_gate is True, nid
            else:
                assert node.hold_for_gate is False, nid

    def test_scope_last_step_advances_without_hold(self, tmp_path):
        # 2026-07-28：understand:3 无门栏——末步 pass 直接推进 understand:4
        _write_state_full(tmp_path, "t", "understand", 3, sub_step=5)
        state = eng.normalize_state(eng.load_state(tmp_path, "t"))
        node = eng.get_node("understand", 3)
        new_state = eng._advance_sub_step(tmp_path, "t", state, node, 5, via="test")
        assert new_state["sub_index"] == 4
        assert new_state["node"] == "understand:4"
        assert "held_for_gate" not in new_state

    def test_plan4_last_step_held_not_advanced(self, tmp_path):
        # 门栏唯一处 pinning：plan:4 末步 pass -> 扣留
        _write_state_full(tmp_path, "t", "plan", 4, sub_step=5)
        state = eng.normalize_state(eng.load_state(tmp_path, "t"))
        node = eng.get_node("plan", 4)
        new_state = eng._advance_sub_step(tmp_path, "t", state, node, 5, via="test")
        assert new_state["sub_index"] == 4  # 扣留：sub_index 不翻
        assert new_state["held_for_gate"] is True
        assert eng.load_state(tmp_path, "t")["held_for_gate"] is True  # 已落盘

    def test_last_step_advances_without_hold(self, tmp_path):
        # 2026-07-28：understand:2 无门栏——末步 pass 直接推进 understand:3
        _write_state_full(tmp_path, "t", "understand", 2, sub_step=5)
        state = eng.normalize_state(eng.load_state(tmp_path, "t"))
        node = eng.get_node("understand", 2)
        new_state = eng._advance_sub_step(tmp_path, "t", state, node, 5, via="test")
        assert new_state["sub_index"] == 3
        assert new_state["node"] == "understand:3"
        assert "held_for_gate" not in new_state

    def test_hold_unconditional_ignores_gate_passed(self, tmp_path):
        # 泄漏防护（design §2）：中途 /dl gate 预放行 phase 闸门（gate=passed）不得穿栏
        _write_state_full(tmp_path, "t", "plan", 4, sub_step=5)
        st = eng.load_state(tmp_path, "t")
        st["gate"] = "passed"
        eng.save_state(tmp_path, "t", st)
        state = eng.normalize_state(eng.load_state(tmp_path, "t"))
        node = eng.get_node("plan", 4)
        new_state = eng._advance_sub_step(tmp_path, "t", state, node, 5, via="test")
        assert new_state["sub_index"] == 4
        assert new_state["held_for_gate"] is True

    def test_plan4_release_subgate_no_advance(self, tmp_path):
        # pinning（门栏唯一处，advance="phase" hold）：plan:4 门栏放行
        # **只放行不推进**——大闸门不被 subgate-pass 静默吸收
        _write_state_full(tmp_path, "t", "plan", 4, sub_step=5)
        st = eng.load_state(tmp_path, "t")
        st["held_for_gate"] = True
        eng.save_state(tmp_path, "t", st)
        ok, msg = eng.release_subgate(tmp_path, "t", str(tmp_path))
        assert ok is True
        assert "PHASE_DONE" in msg  # 指引模型 PHASE_DONE 撞大闸门
        reread = eng.load_state(tmp_path, "t")
        assert reread["phase"] == "plan"  # 不推进
        assert reread["sub_index"] == 4
        assert "held_for_gate" not in reread
        rec = json.loads(eng.read_evidence(tmp_path, "t").strip().splitlines()[-1])
        assert rec["via"] == "manual-subgate-pass"
        assert rec["sub_step"] == 5

    def test_plan4_full_path_release_then_phase_advance(self, tmp_path):
        # pinning 全路径：末步扣留 -> /dl gate（subgate-pass，不推进）
        # -> phase 闸门放行后 advance_state -> execute（gate=passed）
        _write_state_full(tmp_path, "t", "plan", 4, sub_step=5)
        st = eng.load_state(tmp_path, "t")
        st["held_for_gate"] = True
        eng.save_state(tmp_path, "t", st)
        ok, _ = eng.release_subgate(tmp_path, "t", str(tmp_path))
        assert ok is True
        assert eng.load_state(tmp_path, "t")["phase"] == "plan"
        # phase 大闸门放行（/dl gate 第二次）后的推进
        st2 = eng.load_state(tmp_path, "t")
        st2["gate"] = "passed"
        eng.save_state(tmp_path, "t", st2)
        new_state = eng.advance_state(tmp_path, "t", via="test")
        assert new_state["phase"] == "execute"
        assert new_state["node"] == "execute:0"
        assert new_state["gate"] == "passed"  # plan in GATED_AFTER

    def test_release_without_held_errors(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=3)
        ok, msg = eng.release_subgate(tmp_path, "t", str(tmp_path))
        assert ok is False
        assert "不在门栏扣留状态" in msg

    def test_reset_clears_held_marker(self, tmp_path):
        _write_state_full(tmp_path, "t", "plan", 4, sub_step=5)
        st = eng.load_state(tmp_path, "t")
        st["held_for_gate"] = True
        eng.save_state(tmp_path, "t", st)
        ok, _ = eng.reset_state(tmp_path, "t", "3")
        assert ok is True
        reread = eng.load_state(tmp_path, "t")
        assert "held_for_gate" not in reread
        assert reread["sub_step_index"] == 3


class TestStateReset:
    """reset_state（/dl state-reset，designs/state-reset-command-design.md）。

    目标 T=(phase, minor, step n) 含 n 作废：删 T 节点 sub_step>=n 与所有后续
    节点的 evidence（trace+gate 纯硬删，含 T 自身节点级裁决行），删 T.phase
    及之后的阶段产物，state 指针/游标/history 回到「n-1 已完成」。
    """

    def test_within_node_clears_state_and_evidence(self, tmp_path):
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
                '{"kind":"gate","node":"understand:1","phase":"understand","sub":1,"gate":"passed","via":"manual-step-pass","sub_step":2}',
                # 节点级裁决（无 sub_step）：回退到本节点中段后旧「已过」已失效 -> 也删
                '{"kind":"gate","node":"understand:1","phase":"understand","sub":1,"gate":"passed"}',
            ],
        )
        ok, msg = eng.reset_state(tmp_path, "t", "2")
        assert ok is True
        st = eng.load_state(tmp_path, "t")
        assert st["sub_step_index"] == 2
        assert st["node_attempts"] == 0
        assert st["last_judged_trace"] == {"understand:1#1": "a"}
        # evidence：sub_step>=2 的 trace 删（子1 保留）；本节点 gate 行（含节点级）全删
        lines = [
            json.loads(line)
            for line in eng.read_evidence(tmp_path, "t").strip().splitlines()
        ]
        assert [r.get("sub_step") for r in lines if r["kind"] == "skill-trace"] == [1]
        assert [r for r in lines if r["kind"] == "gate"] == []

    def test_reset_clears_cursor_so_new_trace_retriggers(self, tmp_path):
        # 回退后游标已清：模型再写同内容 trace 也会被判「有新产出」，不静默跳过
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=2)
        st = eng.load_state(tmp_path, "t")
        st["last_judged_trace"] = {"understand:1#2": "old-hash"}
        eng.save_state(tmp_path, "t", st)
        ok, _ = eng.reset_state(tmp_path, "t", "2")
        assert ok is True
        assert eng.load_state(tmp_path, "t")["last_judged_trace"] == {}

    def test_reset_rejects_node_without_sub_steps(self, tmp_path):
        _write_state_full(tmp_path, "t", "execute", 0)
        ok, msg = eng.reset_state(tmp_path, "t", "2")
        assert ok is False
        assert "无子步骤" in msg

    def test_reset_rejects_out_of_range(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        for bad in ("0", "7"):
            ok, msg = eng.reset_state(tmp_path, "t", bad)
            assert ok is False
            assert "越界" in msg

    def test_reset_bad_line_preserved(self, tmp_path):
        # 坏行不属于任何子步骤，原样保留（暴露而非吞掉）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=2)
        _write_evidence(tmp_path, "t", [_trace_line(1), "not-json{bad", _trace_line(2)])
        ok, _ = eng.reset_state(tmp_path, "t", "2")
        assert ok is True
        assert "not-json{bad" in eng.read_evidence(tmp_path, "t")

    # ---------- 跨节点（phase:minor[:step] 三段/两段寻址）----------

    def test_cross_subphase_rolls_back_state_and_evidence(self, tmp_path):
        # 当前 understand:2 子2，reset 回 understand:1 子4（含 4 作废）
        _write_state_full(tmp_path, "t", "understand", 2, sub_step=2)
        st = eng.load_state(tmp_path, "t")
        st["last_judged_trace"] = {
            "understand:1#3": "keep",
            "understand:1#4": "drop",
            "understand:2#1": "drop",
        }
        eng.save_state(tmp_path, "t", st)
        _write_evidence(
            tmp_path,
            "t",
            [
                _trace_line(1),
                _trace_line(3),
                _trace_line(4),  # ProblemContext 子4 -> 删
                _g2_trace_line(1),  # GoalsAndValue（后续节点）-> 删
                '{"kind":"gate","node":"understand:2","phase":"understand","sub":2,"gate":"passed"}',  # 后续节点裁决 -> 删
            ],
        )
        ok, msg = eng.reset_state(tmp_path, "t", "understand:ProblemContext:4")
        assert ok is True, msg
        st = eng.load_state(tmp_path, "t")
        assert st["phase"] == "understand"
        assert st["sub_index"] == 1
        assert st["node"] == "understand:1"
        assert st["sub_step_index"] == 4
        assert st["last_judged_trace"] == {"understand:1#3": "keep"}
        lines = [
            json.loads(line)
            for line in eng.read_evidence(tmp_path, "t").strip().splitlines()
        ]
        assert [r["sub_step"] for r in lines if r["kind"] == "skill-trace"] == [1, 3]
        assert [r for r in lines if r["kind"] == "gate"] == []

    def test_cross_phase_deletes_artifacts_and_truncates_history(self, tmp_path):
        # 当前 plan:1，reset 回 understand:4 子5：
        # T.phase=understand -> understand/plan 产物全删；history 截掉 plan:1；
        # plan 节点 gate 裁决行删；gate 字段重算（understand 无前驱 -> pending）
        _write_state_full(tmp_path, "t", "plan", 1, sub_step=1)
        st = eng.load_state(tmp_path, "t")
        st["gate"] = "passed"
        st["history"] = [
            {
                "phase": "understand",
                "sub": i,
                "entered_at": "x",
                "exited_at": "y",
                "via": "auto",
            }
            for i in (1, 2, 3, 4)
        ] + [
            {
                "phase": "plan",
                "sub": 1,
                "entered_at": "z",
                "exited_at": None,
                "via": "auto",
            },
        ]
        wt = tmp_path / "wt"
        wt.mkdir()
        st["worktree_path"] = str(wt)
        eng.save_state(tmp_path, "t", st)
        # 产物四处落点：主仓规范位 + worktree 根 legacy
        for p in (
            tmp_path / ".claude" / "understands" / "t.md",
            tmp_path / ".claude" / "plans" / "t.md",
            wt / "understand.md",
            wt / "plan.md",
        ):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x", encoding="utf-8")
        _write_evidence(
            tmp_path,
            "t",
            [
                '{"kind":"gate","node":"understand:4","phase":"understand","sub":4,"gate":"passed"}',
                '{"kind":"gate","node":"plan:4","phase":"plan","sub":4,"gate":"passed"}',  # plan->execute 闸门裁决 -> 删
            ],
        )
        ok, msg = eng.reset_state(tmp_path, "t", "understand:SuccessCriteria:5")
        assert ok is True, msg
        st = eng.load_state(tmp_path, "t")
        assert (st["phase"], st["sub_index"], st["sub_step_index"]) == (
            "understand",
            4,
            5,
        )
        assert st["gate"] == "pending"
        assert [(h["phase"], h["sub"]) for h in st["history"]] == [
            ("understand", i) for i in (1, 2, 3, 4)
        ]
        assert st["history"][-1]["exited_at"] is None  # T 条目重开
        for p in (
            tmp_path / ".claude" / "understands" / "t.md",
            tmp_path / ".claude" / "plans" / "t.md",
            wt / "understand.md",
            wt / "plan.md",
        ):
            assert not p.exists(), f"产物未删: {p}"
        assert "plan:4" not in eng.read_evidence(tmp_path, "t")
        assert "understand:4" not in eng.read_evidence(
            tmp_path, "t"
        )  # T 节点级裁决也删

    def test_reset_rejects_forward_target(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        ok, msg = eng.reset_state(tmp_path, "t", "plan:DesignSolution:2")
        assert ok is False
        assert "前向" in msg

    def test_reset_rejects_unknown_minor(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        ok, msg = eng.reset_state(tmp_path, "t", "plan:NoSuch:2")
        assert ok is False
        assert "DesignSolution" in msg  # 报错列合法子阶段（no silent fallback：不猜）

    def test_reset_rejects_unknown_phase(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        ok, msg = eng.reset_state(tmp_path, "t", "undrstand:1:2")
        assert ok is False
        assert "understand" in msg  # 报错列合法 phase

    def test_two_part_address_defaults_to_step1(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 4, sub_step=3)
        ok, msg = eng.reset_state(tmp_path, "t", "understand:GoalsAndValue")
        assert ok is True, msg
        st = eng.load_state(tmp_path, "t")
        assert (st["sub_index"], st["sub_step_index"]) == (2, 1)

    def test_minor_by_index_and_case_insensitive(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 4, sub_step=3)
        ok, msg = eng.reset_state(tmp_path, "t", "UNDERSTAND:2:3")
        assert ok is True, msg
        st = eng.load_state(tmp_path, "t")
        assert (st["phase"], st["sub_index"], st["sub_step_index"]) == (
            "understand",
            2,
            3,
        )

    def test_node_without_sub_steps_two_part_only(self, tmp_path):
        # 无子步骤节点两段式可用（sub_step_index=0），三段式报错
        _write_state_full(tmp_path, "t", "evolution", 0)
        ok, msg = eng.reset_state(tmp_path, "t", "review:0:2")
        assert ok is False
        assert "无子步骤" in msg
        ok, msg = eng.reset_state(tmp_path, "t", "review:0")
        assert ok is True, msg
        st = eng.load_state(tmp_path, "t")
        assert (st["phase"], st["sub_index"], st["sub_step_index"]) == ("review", 0, 0)

    def test_reset_same_position_is_within_node(self, tmp_path):
        # T == 当前位置 -> 退化为节点内回退（等价旧 step-reset）
        _write_state_full(tmp_path, "t", "plan", 4, sub_step=5)
        ok, msg = eng.reset_state(tmp_path, "t", "plan:ExecutionPlanCheckpoints:3")
        assert ok is True, msg
        st = eng.load_state(tmp_path, "t")
        assert (st["phase"], st["sub_index"], st["sub_step_index"]) == ("plan", 4, 3)

    def test_unknown_minor_stage_line_preserved(self, tmp_path):
        # minor_stage 反查不到节点的 trace 行归属不明 -> 保留（暴露而非吞掉）
        _write_state_full(tmp_path, "t", "understand", 2, sub_step=1)
        orphan = '{"kind":"skill-trace","minor_stage":"Ghost","sub_step":9,"q":["x"],"a":["y"]}'
        _write_evidence(tmp_path, "t", [orphan, _g2_trace_line(1)])
        ok, _ = eng.reset_state(tmp_path, "t", "understand:ProblemContext:6")
        assert ok is True
        assert "Ghost" in eng.read_evidence(tmp_path, "t")


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


def _g2_trace_line(sub_step: int, marker: str = "g") -> str:
    """GoalsAndValue（understand:2）的 skill-trace 行。"""
    return json.dumps(
        {
            "kind": "skill-trace",
            "major_stage": "Understand",
            "minor_stage": "GoalsAndValue",
            "sub_step": sub_step,
            "skill": "define-problem",
            "purpose": "p",
            "q": [f"q-{marker}"],
            "a": [f"a-{marker}"],
        },
        ensure_ascii=False,
    )


def _sc_trace_line(sub_step: int, marker: str = "s") -> str:
    """SuccessCriteria（understand:4）的 skill-trace 行。"""
    return json.dumps(
        {
            "kind": "skill-trace",
            "major_stage": "Understand",
            "minor_stage": "SuccessCriteria",
            "sub_step": sub_step,
            "skill": "define-problem",
            "purpose": "p",
            "q": [f"q-{marker}"],
            "a": [f"a-{marker}"],
        },
        ensure_ascii=False,
    )


def _ds_trace_line(sub_step: int, marker: str = "d") -> str:
    """DesignSolution（plan:1）的 skill-trace 行。"""
    return json.dumps(
        {
            "kind": "skill-trace",
            "major_stage": "Plan",
            "minor_stage": "DesignSolution",
            "sub_step": sub_step,
            "skill": "define-problem",
            "purpose": "p",
            "q": [f"q-{marker}"],
            "a": [f"a-{marker}"],
        },
        ensure_ascii=False,
    )


def _tb_trace_line(sub_step: int, marker: str = "t") -> str:
    """TaskBreakdown（plan:2）的 skill-trace 行。"""
    return json.dumps(
        {
            "kind": "skill-trace",
            "major_stage": "Plan",
            "minor_stage": "TaskBreakdown",
            "sub_step": sub_step,
            "skill": "superpowers:writing-plans",
            "purpose": "p",
            "q": [f"q-{marker}"],
            "a": [f"a-{marker}"],
        },
        ensure_ascii=False,
    )


def _cts_trace_line(sub_step: int, marker: str = "t") -> str:
    """CapabilityToolSelection（plan:3）的 skill-trace 行。"""
    return json.dumps(
        {
            "kind": "skill-trace",
            "major_stage": "Plan",
            "minor_stage": "CapabilityToolSelection",
            "sub_step": sub_step,
            "skill": "define-problem",
            "purpose": "p",
            "q": [f"q-{marker}"],
            "a": [f"a-{marker}"],
        },
        ensure_ascii=False,
    )


def _epc_trace_line(sub_step: int, marker: str = "t") -> str:
    """ExecutionPlanCheckpoints（plan:4）的 skill-trace 行。"""
    return json.dumps(
        {
            "kind": "skill-trace",
            "major_stage": "Plan",
            "minor_stage": "ExecutionPlanCheckpoints",
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
        _write_state_full(tmp_path, "t", "execute", 0)
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
        # 末步（gate=None 自动过）：游标须落盘（防下次 Stop 重判同一 trace）；
        # 2026-07-28 起 understand:2 无门栏：末步过门控直接推进 understand:3
        _write_state_full(tmp_path, "t", "understand", 2, sub_step=5)
        _write_evidence(tmp_path, "t", [_g2_trace_line(5)])
        action, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert action == "advanced"
        st = eng.load_state(tmp_path, "t")
        assert st["sub_index"] == 3  # 无门栏：自动推进
        assert "held_for_gate" not in st
        assert "understand:2#5" in st["last_judged_trace"]


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
        # 超时重试一次后仍失败：judge_error + judge_retried 双标记
        assert eng.LAST_JUDGE_META == {
            "judge_error": "TimeoutExpired",
            "judge_retried": 1,
        }

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
        assert eng.LAST_JUDGE_META == {
            "judge_error": "TimeoutExpired",
            "judge_retried": 1,
        }

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


class TestRunJudgeRetry:
    """judge 失败重试策略（2026-07-26 决议）：bad_verdict_json（输出格式抖动）与
    TimeoutExpired（时延抖动；递归爆炸根因已被 cwd=tempdir 修掉）各重试一次，
    重试仍失败才降级 block。API 错/exit 非零/OSError 不重试（重试无意义）。"""

    BAD = '{"is_error":false,"usage":{"input_tokens":10,"output_tokens":2},"result":"我不是 JSON"}\n'
    GOOD = (
        '{"is_error":false,"usage":{"input_tokens":20,"output_tokens":3},'
        '"result":"{\\"pass\\": true, \\"reason\\": \\"\\"}"}\n'
    )

    def _mock_seq(self, monkeypatch, stdouts):
        calls = {"n": 0, "prompts": []}

        def _run(cmd, **kw):
            i = calls["n"]
            calls["n"] += 1
            calls["prompts"].append(cmd[-1])

            class _Res:
                returncode = 0

            _Res.stdout = stdouts[min(i, len(stdouts) - 1)]
            return _Res()

        monkeypatch.setattr(eng.subprocess, "run", _run)
        return calls

    def test_retry_success_after_bad_verdict(self, monkeypatch):
        calls = self._mock_seq(monkeypatch, [self.BAD, self.GOOD])
        ok, _ = eng.run_judge("rubric", "label", "out")
        assert ok is True
        assert calls["n"] == 2  # 重试了一次
        assert "合法 JSON" in calls["prompts"][1]  # 重试带格式提醒后缀
        m = eng.LAST_JUDGE_META
        assert m.get("judge_retried") == 1
        assert "judge_error" not in m  # 成功路径清掉首次失败标记
        assert m["judge_input_tokens"] == 30  # 两次尝试成本累加
        assert m["judge_output_tokens"] == 5

    def test_retry_exhausted_degrades_to_block(self, monkeypatch):
        calls = self._mock_seq(monkeypatch, [self.BAD, self.BAD])
        ok, reason = eng.run_judge("rubric", "label", "out")
        assert ok is False
        assert calls["n"] == 2  # 只重试一次，不无限循环
        assert "非合法 JSON" in reason
        assert eng.LAST_JUDGE_META["judge_error"] == "bad_verdict_json"
        assert eng.LAST_JUDGE_META.get("judge_retried") == 1

    def test_timeout_retried_once_then_pass(self, monkeypatch):
        # TimeoutExpired 重试一次（2026-07-26 决议）：递归爆炸根因已被
        # cwd=tempdir 修掉；超时降级 block 会让模型白返工一轮（demo fbdb6ebd 子2）。
        calls = {"n": 0, "prompts": []}

        def _run(cmd, **kw):
            calls["n"] += 1
            calls["prompts"].append(cmd[-1])
            if calls["n"] == 1:
                raise eng.subprocess.TimeoutExpired(cmd="claude", timeout=1)

            class _Res:
                returncode = 0

            _Res.stdout = self.GOOD
            return _Res()

        monkeypatch.setattr(eng.subprocess, "run", _run)
        ok, _ = eng.run_judge("rubric", "label", "out")
        assert ok is True
        assert calls["n"] == 2  # 重试了一次
        # 超时重试原样重发（不加 bad_verdict_json 的 JSON 格式提醒后缀）
        assert calls["prompts"][0] == calls["prompts"][1]
        m = eng.LAST_JUDGE_META
        assert m.get("judge_retried") == 1
        assert "judge_error" not in m  # 成功路径清掉首次失败标记

    def test_double_timeout_degrades_to_block(self, monkeypatch):
        calls = {"n": 0}

        def _run(cmd, **kw):
            calls["n"] += 1
            raise eng.subprocess.TimeoutExpired(cmd="claude", timeout=1)

        monkeypatch.setattr(eng.subprocess, "run", _run)
        ok, reason = eng.run_judge("rubric", "label", "out")
        assert not ok
        assert calls["n"] == 2  # 只重试一次，不无限循环
        assert "TimeoutExpired" in reason
        assert eng.LAST_JUDGE_META["judge_error"] == "TimeoutExpired"
        assert eng.LAST_JUDGE_META.get("judge_retried") == 1

    def test_oserror_not_retried(self, monkeypatch):
        # OSError（二进制缺失/资源耗尽类）重试无意义，仍直接降级
        calls = {"n": 0}

        def _run(cmd, **kw):
            calls["n"] += 1
            raise OSError("boom")

        monkeypatch.setattr(eng.subprocess, "run", _run)
        ok, _ = eng.run_judge("rubric", "label", "out")
        assert not ok
        assert calls["n"] == 1
        assert "judge_retried" not in eng.LAST_JUDGE_META

    def test_clean_pass_not_retried(self, monkeypatch):
        calls = self._mock_seq(monkeypatch, [self.GOOD])
        ok, _ = eng.run_judge("rubric", "label", "out")
        assert ok is True
        assert calls["n"] == 1
        assert "judge_retried" not in eng.LAST_JUDGE_META


class TestPendingUnjudgedStep:
    """§S10：PreToolUse 围栏的关闭条件（与门控共用 last_judged_trace 游标）。"""

    def test_no_state_none(self, tmp_path):
        assert eng.pending_unjudged_step(tmp_path, "t") is None

    def test_no_sub_steps_none(self, tmp_path):
        _write_state_full(tmp_path, "t", "execute", 0)
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


class TestEngagementFenceState:
    """§step-engage-prefence S15：零 trace 窗口判据（与 S13 同判据，单源）。"""

    def test_no_state_none(self, tmp_path):
        assert eng.engagement_fence_state(tmp_path, "t") is None

    def test_no_sub_steps_none(self, tmp_path):
        _write_state_full(tmp_path, "t", "execute", 0)
        assert eng.engagement_fence_state(tmp_path, "t") is None

    def test_zero_trace_returns_step(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        got = eng.engagement_fence_state(tmp_path, "t")
        assert got is not None
        n, step = got
        assert n == 1
        assert step.ref == "define-problem"
        assert step.fence_allow == ()

    def test_step3_declares_bash_webfetch(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=3)
        got = eng.engagement_fence_state(tmp_path, "t")
        assert got is not None
        n, step = got
        assert n == 3
        assert step.fence_allow == ("Bash", "WebFetch")

    def test_step4_declares_agent(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=4)
        got = eng.engagement_fence_state(tmp_path, "t")
        assert got is not None
        assert got[1].fence_allow == ("Agent",)

    def test_window_closed_with_trace(self, tmp_path):
        # 有 trace（未判决）-> 归 S10，非本围栏窗口（两态互斥）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        _write_evidence(tmp_path, "t", [_trace_line(1)])
        assert eng.engagement_fence_state(tmp_path, "t") is None

    def test_fence_off_none(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        st = eng.normalize_state(eng.load_state(tmp_path, "t"))
        st["enforce_step_fence"] = False
        eng.save_state(tmp_path, "t", st)
        assert eng.engagement_fence_state(tmp_path, "t") is None


class TestEngagementFenceNotice:
    """§autocontinue-fence-notice：围栏提示文本单源（注入与 pass/block 续轮共用）。"""

    def test_step_without_fence_allow_no_exemption_line(self):
        step = eng.sub_step_at(eng.get_node("understand", 1), 1)
        notice = eng.engagement_fence_notice(step)
        assert "前置参与围栏" in notice
        assert "额外放行" not in notice  # 子1 fence_allow=() -> 无豁免行

    def test_step4_notice_declares_agent(self):
        step = eng.sub_step_at(eng.get_node("understand", 1), 4)
        notice = eng.engagement_fence_notice(step)
        assert "额外放行：Agent" in notice

    def test_step3_notice_declares_bash_webfetch(self):
        step = eng.sub_step_at(eng.get_node("understand", 1), 3)
        notice = eng.engagement_fence_notice(step)
        assert "额外放行：Bash / WebFetch" in notice

    def test_step4_purpose_guides_redteam_prompt_tools(self):
        # v2.14：红队纪律 a-d 从 purpose 机械化进 redteam_prompt() 模板
        # （demo 121320fe 子代理 104 报错根因链：Glob 不存在(11) + Bash 空拒(21)
        # + 盲猜路径(61 Read 全空)——现场拼 prompt 的事故类，脚本组 prompt 根治）。
        # purpose 只留触发条件 + 调用方式（判断归模型，prompt 内容归脚本）。
        step = eng.sub_step_at(eng.get_node("understand", 1), 4)
        assert "redteam-prompt" in step.purpose  # 生成器调用
        assert "禁止手拼" in step.purpose
        assert "只给证据不给结论" in step.purpose  # 独立上下文契约（gate 判）
        assert "触发条件写死" in step.purpose
        # 披露缺口修复（demo block#5）：「10/10 pass」式汇总声明被判 block——
        # 逐项可验证是形式要件，应披露进 purpose（§3.5 #2）
        assert "逐项可验证" in step.purpose
        assert "汇总声明不算记录" in step.purpose

    def test_step_selfcheck_hint_single_source(self):
        # §step-selfcheck：自查提示单源常量（pass 续轮/block 返工/注入三通道共用）
        assert "STEP_DONE 前自查" in eng.STEP_SELFCHECK_HINT
        assert "汇总声明不算" in eng.STEP_SELFCHECK_HINT

    def test_step3_purpose_forbids_credential_exploration(self):
        # demo 121320fe：GitHub API 401 后模型扫 env 找 token 被安全分类器拦
        # （Credential Exploration）——purpose 须 preempt：认证失败直接标
        # 未取证（合法留痕），禁止探查凭证
        step = eng.sub_step_at(eng.get_node("understand", 1), 3)
        assert "禁止探查凭证" in step.purpose
        assert "未取证+未认证" in step.purpose


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
        assert self._deny(tmp_path, "plan", 2, "/repo/plan.md") is None
        assert self._deny(tmp_path, "plan", 2, "/repo/main.py") is not None

    def test_plan_allows_plans_dir(self, tmp_path):
        # plan.md 规范位置=主仓 .claude/plans/<name>.md（2026-07-28 用户决议：
        # 与 evidence 同级——worktree 归档删除时分支上产物一起丢，
        # 主仓 .claude/ 才存活）。basename=<name>.md 不在白名单，须路径规则放行
        assert self._deny(tmp_path, "plan", 2, "/repo/.claude/plans/t.md") is None
        assert self._deny(tmp_path, "plan", 4, "/repo/.claude/plans/t.md") is None

    def test_other_phases_deny_plans_dir(self, tmp_path):
        # plans 目录是 plan 阶段专属写域（防它阶段误写/覆盖合同）
        assert (
            self._deny(tmp_path, "understand", 1, "/repo/.claude/plans/t.md")
            is not None
        )
        assert self._deny(tmp_path, "review", 0, "/repo/.claude/plans/t.md") is not None

    def test_phase_artifact_dirs_scoped(self, tmp_path):
        # understand/review/evolution 产物同法迁移主仓（2026-07-28 用户决议，
        # 与 plan.md 同模式）：各阶段只放行自己的产物目录，跨阶段 deny
        assert (
            self._deny(tmp_path, "understand", 1, "/repo/.claude/understands/t.md")
            is None
        )
        assert (
            self._deny(tmp_path, "understand", 1, "/repo/.claude/reviews/t.md")
            is not None
        )
        assert self._deny(tmp_path, "review", 0, "/repo/.claude/reviews/t.md") is None
        assert (
            self._deny(tmp_path, "review", 0, "/repo/.claude/understands/t.md")
            is not None
        )
        assert (
            self._deny(tmp_path, "evolution", 0, "/repo/.claude/evolutions/t.md")
            is None
        )
        # evolution 例外：既有语义放行整个 .claude/（skills 更新职责所需，
        # 先于本迁移存在）——不为本次迁移收窄（surgical change）；
        # understand/review/plan 各阶段跨目录仍 deny（上方断言已覆盖）
        assert (
            self._deny(tmp_path, "evolution", 0, "/repo/.claude/reviews/t.md") is None
        )

    def test_plan_allows_design_md(self, tmp_path):
        # plan:1 子6 装配 design.md（H8 产物）——designs/*.md 全阶段放行
        assert self._deny(tmp_path, "plan", 1, "/repo/designs/x-design.md") is None

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


# ---------- gate_verdict_mech（§8.3 产物机械门，designs/artifact-mech-gate-design.md）----------


class TestGateVerdictMech:
    def test_none_passes(self):
        node = eng.get_node("understand", 1)  # gate_mech=NONE
        assert eng.gate_verdict_mech(node, project_root=Path("."), name="t") is None

    def test_no_project_root_degrades(self):
        # 无 project_root -> 机械项降级放行（宁纵勿枉,同 codegraph_gate 非 git）
        node = eng.get_node("understand", 4)  # ARTIFACT_EXISTS
        assert eng.gate_verdict_mech(node, project_root=None, name="t") is None

    def test_no_name_degrades(self, tmp_path):
        # 无 name 无法定位 <name>.md -> 降级放行（宁纵勿枉）
        node = eng.get_node("understand", 4)
        assert eng.gate_verdict_mech(node, project_root=tmp_path, name=None) is None

    def test_descriptive_artifact_degrades(self, tmp_path):
        # 描述性产物（含 "+"）机械无法判 -> 交语义 judge
        node = eng.get_node("execute", 0)  # artifact="代码+commit+测试通过"
        assert eng.gate_verdict_mech(node, project_root=tmp_path, name="t") is None

    def test_artifact_missing_blocks(self, tmp_path):
        node = eng.get_node("understand", 4)  # ARTIFACT_EXISTS -> understands/t.md
        reason = eng.gate_verdict_mech(node, project_root=tmp_path, name="t")
        assert reason is not None
        assert "产物未落地" in reason
        assert ".claude/understands/t.md" in reason

    def test_artifact_exists_passes(self, tmp_path):
        _write_artifact(tmp_path, "understands", "t")
        node = eng.get_node("understand", 4)
        assert eng.gate_verdict_mech(node, project_root=tmp_path, name="t") is None

    def test_stale_artifact_blocks(self, tmp_path):
        # mtime 早于 not_before（本节点进入时间）-> 预写/残留 -> block
        p = _write_artifact(tmp_path, "understands", "t")
        old = time.time() - 3600
        os.utime(p, (old, old))
        node = eng.get_node("understand", 4)
        reason = eng.gate_verdict_mech(
            node, project_root=tmp_path, name="t", not_before=time.time()
        )
        assert reason is not None
        assert "陈旧" in reason

    def test_fresh_artifact_passes(self, tmp_path):
        _write_artifact(tmp_path, "understands", "t")
        node = eng.get_node("understand", 4)
        assert (
            eng.gate_verdict_mech(
                node, project_root=tmp_path, name="t", not_before=time.time() - 60
            )
            is None
        )

    def test_contains_missing_file_blocks(self, tmp_path):
        node = eng.get_node("plan", 4)  # ARTIFACT_CONTAINS -> plans/t.md
        reason = eng.gate_verdict_mech(node, project_root=tmp_path, name="t")
        assert reason is not None
        assert "产物未落地" in reason

    def test_contains_missing_section_blocks(self, tmp_path):
        _write_artifact(tmp_path, "plans", "t", "# 执行步骤\nfoo\n")
        node = eng.get_node("plan", 4)
        reason = eng.gate_verdict_mech(node, project_root=tmp_path, name="t")
        assert reason is not None
        assert "缺节" in reason
        assert "执行计划与检查点" in reason

    def test_contains_passes(self, tmp_path):
        _write_artifact(
            tmp_path, "plans", "t", "# 执行步骤\nfoo\n## 执行计划与检查点\nbar\n"
        )
        node = eng.get_node("plan", 4)
        assert eng.gate_verdict_mech(node, project_root=tmp_path, name="t") is None


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
        # understand:3 无 rubric -> 不调 judge,机械项 NONE 过 -> pass
        # 用计数器证明 judge 没被调
        # 注：understand:1 现有验真 rubric 会调 judge，故用 understand:3 测无 rubric 路径
        called = {"n": 0}

        def _spy(cmd, **kw):
            called["n"] += 1
            return _fake_run_factory(0, _result_line('{"pass": true}'))(cmd, **kw)

        monkeypatch.setattr(eng.subprocess, "run", _spy)
        node = eng.get_node("understand", 3)
        ok, _ = eng.run_gate(node, "输出")
        assert ok is True
        assert called["n"] == 0  # judge 没被调

    def test_rubric_calls_judge_pass(self, monkeypatch):
        # review:0 有 rubric,机械降级过 -> 跑 judge -> pass
        monkeypatch.setattr(
            eng.subprocess, "run", _fake_run_factory(0, _result_line('{"pass": true}'))
        )
        node = eng.get_node("review", 0)
        ok, _ = eng.run_gate(node, "一份计划")
        assert ok is True

    def test_rubric_calls_judge_block(self, monkeypatch):
        monkeypatch.setattr(
            eng.subprocess,
            "run",
            _fake_run_factory(0, _result_line('{"pass": false, "reason": "没步骤"}')),
        )
        node = eng.get_node("review", 0)
        ok, reason = eng.run_gate(node, "空话")
        assert ok is False
        assert "没步骤" in reason

    def test_mech_block_short_circuits_judge(self, monkeypatch):
        # 机械项不过 -> 短路,不跑 judge。用 mock 强制 gate_verdict_mech
        # 返回 block 验证短路（真实机械门覆盖见 TestGateVerdictMech）。
        called = {"n": 0}

        def _spy(cmd, **kw):
            called["n"] += 1
            return _fake_run_factory(0, _result_line('{"pass": true}'))(cmd, **kw)

        monkeypatch.setattr(eng.subprocess, "run", _spy)
        monkeypatch.setattr(
            eng, "gate_verdict_mech", lambda *a, **k: "产物缺失：review.md"
        )
        node = eng.get_node("review", 0)
        ok, reason = eng.run_gate(node, "输出")
        assert ok is False
        assert "产物缺失" in reason
        assert called["n"] == 0  # judge 没被调（短路）

    def test_mech_enforced_when_name_given(self, tmp_path, monkeypatch):
        # §8.3：hook 传 name + project_root 后 review:0 的 ARTIFACT_EXISTS 真实生效——
        # 缺 .claude/reviews/t.md -> 机械门短路 block（不调 judge）
        called = {"n": 0}

        def _spy(cmd, **kw):
            called["n"] += 1
            return _fake_run_factory(0, _result_line('{"pass": true}'))(cmd, **kw)

        monkeypatch.setattr(eng.subprocess, "run", _spy)
        node = eng.get_node("review", 0)
        ok, reason = eng.run_gate(node, "输出", project_root=tmp_path, name="t")
        assert ok is False
        assert "产物未落地" in reason
        assert ".claude/reviews/t.md" in reason
        assert called["n"] == 0  # judge 没被调（短路）

    def test_mech_pass_then_judge_runs(self, tmp_path, monkeypatch):
        # 产物已写盘 -> 机械门过 -> 继续跑 judge
        _write_artifact(tmp_path, "reviews", "t")
        monkeypatch.setattr(
            eng.subprocess, "run", _fake_run_factory(0, _result_line('{"pass": true}'))
        )
        node = eng.get_node("review", 0)
        ok, _ = eng.run_gate(node, "输出", project_root=tmp_path, name="t")
        assert ok is True


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
        _write_state(tmp_path, "t", "plan", 2)
        rc = eng.main(["status", "t", "--cwd", str(tmp_path)])
        assert rc == 0
        assert "拆解任务与阶段" in capsys.readouterr().out

    def test_meta_outputs_constants_json(self, capsys):
        # meta 不需 git repo/name（静态常量）;供 dl-lib.sh 缓存删 bash 副本
        rc = eng.main(["meta"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["phases"] == ["understand", "plan", "execute", "review", "evolution"]
        assert out["phase_labels"]["understand"] == "理解和求证问题"
        assert out["gated_after"] == ["plan"]  # 2026-07-28 起围栏只设在 plan 完成
        assert out["subphases"]["understand"] == [
            "理解问题和背景",
            "明确目标和价值",
            "确定范围与约束",
            "定义成功标准和验收方式",
        ]
        assert out["subphases"]["plan"] == [
            "设计解决方案",
            "拆解任务与阶段",
            "选择能力与工具",
            "制定执行计划和检查点",
        ]
        assert out["sub_total"]["understand"] == 4
        assert out["sub_total"]["plan"] == 4


class TestReadEvidenceForStep:
    """read_evidence_for_step：judge 输入 scope 化（2026-07-26）。

    子步骤 gate 原先喂 evidence 全文，judge 输入随步数线性膨胀（demo fbdb6ebd
    实测 3.1k -> 14.9k，总量 O(n²)）。裁剪 = 当前步 + 前序各步最新 trace。
    """

    def test_no_file_none(self, tmp_path):
        assert eng.read_evidence_for_step(tmp_path, "t", 1) is None

    def test_excludes_later_steps(self, tmp_path):
        _write_evidence(tmp_path, "t", [_trace_line(1), _trace_line(2), _trace_line(3)])
        out = eng.read_evidence_for_step(tmp_path, "t", 2)
        assert "q-m" in out
        assert '"sub_step": 3' not in out

    def test_only_latest_trace_per_step(self, tmp_path):
        # 返工历史不喂 judge：同一步多条只留最新一条
        _write_evidence(
            tmp_path,
            "t",
            [_trace_line(1, "old"), _trace_line(1, "new"), _trace_line(2)],
        )
        out = eng.read_evidence_for_step(tmp_path, "t", 2)
        assert "a-new" in out
        assert "a-old" not in out

    def test_gate_records_excluded(self, tmp_path):
        gate_rec = json.dumps(
            {"kind": "gate", "node": "understand:1", "sub_step": 1, "gate": "passed"}
        )
        _write_evidence(tmp_path, "t", [_trace_line(1), gate_rec])
        out = eng.read_evidence_for_step(tmp_path, "t", 1)
        assert '"kind": "gate"' not in out
        assert "q-m" in out

    def test_no_matching_trace_none(self, tmp_path):
        # 只有更晚步骤的 trace -> 当前步视角无证据 -> None（判 block，不静默放行）
        _write_evidence(tmp_path, "t", [_trace_line(3)])
        assert eng.read_evidence_for_step(tmp_path, "t", 1) is None

    def test_stop_gate_feeds_scoped_artifact(self, tmp_path, monkeypatch):
        # gate_sub_step_at_stop 喂 judge 的是裁剪版：返工历史不进 prompt
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=2)
        _write_evidence(
            tmp_path,
            "t",
            [_trace_line(1, "old"), _trace_line(1, "new"), _trace_line(2)],
        )
        captured = {}

        def _spy(rubric, label, output, artifact_content=None, prior_verdicts=None):
            captured["artifact"] = artifact_content
            return (True, "")

        monkeypatch.setattr(eng, "run_judge", _spy)
        action, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert action == "advanced"
        art = captured["artifact"]
        assert "a-new" in art and "a-old" not in art


class TestStep3FalsificationOrderDisclosure:
    """子3 purpose 披露反证时序留痕形式要件（2026-07-26，demo fbdb6ebd 子3 实录：
    模型执行了反证但留痕看不出先后被判 block；形式要件进 purpose 降形式性返工，
    §3.5 #2——质量判据仍只在 gate 黑盒）。"""

    def test_step3_purpose_discloses_order_requirement(self):
        node = eng.get_node("understand", 1)
        step3 = eng.sub_step_at(node, 3)
        assert "反证查询（先）" in step3.purpose
        assert "时序" in step3.purpose


class TestStepSelfcheck:
    """§step-selfcheck 步级化（2026-07-26，demo d59d05ea MiniMax-M3 子1 三连 block 复盘）：
    Step.selfcheck 声明本步 checklist；selfcheck_hint 拼通用段+步级段，三通道同文。
    红线：checklist 只含 purpose 已披露形式要件，质量判据（gate 黑盒）零泄漏。"""

    def _steps(self):
        node = eng.get_node("understand", 1)
        assert node.sub_steps is not None
        return node.sub_steps

    def test_all_six_steps_have_selfcheck(self):
        assert all(s.selfcheck for s in self._steps())

    def test_step1_selfcheck_covers_disclosed_form_requirements(self):
        sc = self._steps()[0].selfcheck
        assert "who/pain/why-now" in sc
        assert "原话" in sc
        assert "出处" in sc

    def test_selfcheck_no_quality_criteria_leak(self):
        # Goodhart 分层守卫：只出现在 gate 质量判据的措辞不得进 checklist
        for s in self._steps():
            for banned in ("从严裁量", "好奇心缺口", "稻草人", "同义反复"):
                assert banned not in s.selfcheck

    def test_selfcheck_hint_none_falls_back_generic(self):
        assert eng.selfcheck_hint(None) == eng.STEP_SELFCHECK_HINT

    def test_selfcheck_hint_stitches_step_checklist(self):
        s1 = self._steps()[0]
        hint = eng.selfcheck_hint(s1)
        assert hint.startswith(eng.STEP_SELFCHECK_HINT)
        assert "本步自查：" in hint
        assert s1.selfcheck in hint

    def test_selfcheck_hint_step_without_selfcheck_generic_only(self):
        s = eng.Step(
            kind="skill",
            ref="x",
            short="s",
            purpose="p",
            input=None,
            record=True,
            gate=None,
        )
        assert eng.selfcheck_hint(s) == eng.STEP_SELFCHECK_HINT


class TestCorruptReworkDetect:
    """§corrupt-rework-detect（2026-07-26，demo d59d05ea 子3 卡死）：
    模型返工把 trace 写碎（JSON 跨行/字面 \\"）-> 同 hash 分支不得再静默放行，
    改判 block 给格式修复指引。只数最新合法 trace 之后的损坏行（旧碎片是历史）。"""

    CORRUPT = '{"kind":"skill-trace","sub_step":3,"q":["跨行截断未完成'

    def test_corrupt_after_latest_true(self, tmp_path):
        _write_evidence(tmp_path, "t", [_trace_line(3), self.CORRUPT])
        assert eng.corrupt_trace_after_latest(tmp_path, "t", 3) is True

    def test_corrupt_before_latest_false(self, tmp_path):
        # 损坏行在最新合法 trace 之前 = 已处理历史（模型修好后旧碎片仍在）-> 不报警
        _write_evidence(tmp_path, "t", [self.CORRUPT, _trace_line(3)])
        assert eng.corrupt_trace_after_latest(tmp_path, "t", 3) is False

    def test_no_corrupt_false(self, tmp_path):
        _write_evidence(tmp_path, "t", [_trace_line(3)])
        assert eng.corrupt_trace_after_latest(tmp_path, "t", 3) is False

    def test_corrupt_other_step_false(self, tmp_path):
        _write_evidence(
            tmp_path,
            "t",
            [_trace_line(3), '{"kind":"skill-trace","sub_step":2,"q":["x'],
        )
        assert eng.corrupt_trace_after_latest(tmp_path, "t", 3) is False

    def test_gate_same_hash_with_corrupt_blocks(self, tmp_path, monkeypatch):
        # 复现 demo 卡死：block 后模型写碎 trace -> 同 hash 分支改判 block（修复指引）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=3)
        _write_evidence(tmp_path, "t", [_trace_line(3)])
        calls = {"n": 0}

        def _spy(*a, **k):
            calls["n"] += 1
            return (False, "内容不达标")

        monkeypatch.setattr(eng, "run_judge", _spy)
        a1, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert a1 == "block" and calls["n"] == 1  # 首次：judge 判内容 block
        # 模型返工但写碎（追加损坏行）
        _write_evidence(tmp_path, "t", [_trace_line(3), self.CORRUPT])
        a2, r2, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert a2 == "block"
        assert "写入损坏" in r2 and "单行" in r2
        assert calls["n"] == 1  # 损坏检测不跑 judge（省调用）
        assert eng.load_state(tmp_path, "t")["node_attempts"] == 2
        # 模型修好（append 合法 trace）-> 正常重判恢复
        _write_evidence(
            tmp_path, "t", [_trace_line(3), self.CORRUPT, _trace_line(3, "fixed")]
        )
        monkeypatch.setattr(eng, "run_judge", lambda *a, **k: (True, ""))
        a3, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert a3 == "advanced"

    def test_gate_same_hash_stale_corrupt_silent(self, tmp_path, monkeypatch):
        # 修好后（合法 trace 在碎片之后）同 hash 不再触发损坏报警 -> 静默放行防 loop
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=3)
        _write_evidence(tmp_path, "t", [self.CORRUPT, _trace_line(3)])
        monkeypatch.setattr(eng, "run_judge", lambda *a, **k: (False, "x"))
        a1, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert a1 == "block"
        a2, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert a2 == "none"  # 碎片在最新合法 trace 之前 = 历史，静默

    def test_corrupt_escalates_at_threshold(self, tmp_path, monkeypatch):
        # 连续损坏达阈值同样升级用户裁决（防无限返工环）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=3)
        _write_evidence(tmp_path, "t", [_trace_line(3)])
        monkeypatch.setattr(eng, "run_judge", lambda *a, **k: (False, "x"))
        eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))  # attempts=1
        _write_evidence(tmp_path, "t", [_trace_line(3), self.CORRUPT])
        eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))  # attempts=2
        a3, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))  # attempts=3
        assert a3 == "escalate"


class TestSubStepPriorVerdicts:
    """v2.26 judge 轮间一致性（tail_volume u:3 子4 五连 block 实证：judge 每轮
    全新调用无记忆 -> 同一 rubric 五轮五种解释，裁量逐轮收紧）：
    ①judge 内容性 block 的判词落 evidence（kind=gate/gate=blocked，含
    sub_step/minor_stage 归属）；②重判时前轮判词经 prior_verdicts 进 judge
    输入 + 一致性指令。返工历史不进 judge 的铁律不破——prior_verdicts 只取
    判词（kind=gate 记录），不取旧 trace。"""

    def _setup_u1_step1(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        _write_evidence(tmp_path, "t", [_trace_line(1, "ev1")])
        return eng._evidence_path(tmp_path, "t")

    def test_block_writes_gate_blocked_record(self, tmp_path, monkeypatch):
        ev = self._setup_u1_step1(tmp_path)
        monkeypatch.setattr(eng, "run_judge", lambda *a, **k: (False, "缺 X 条款"))
        action, reason, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert action == "block"
        recs = [json.loads(l) for l in ev.read_text(encoding="utf-8").splitlines()]
        blocked = [
            r for r in recs if r.get("kind") == "gate" and r.get("gate") == "blocked"
        ]
        assert len(blocked) == 1
        assert blocked[0]["reason"] == "缺 X 条款"
        assert blocked[0]["sub_step"] == 1
        assert blocked[0]["minor_stage"] == "ProblemContext"
        assert blocked[0]["attempts"] == 1

    def test_rejudge_receives_prior_verdicts(self, tmp_path, monkeypatch):
        ev = self._setup_u1_step1(tmp_path)
        captured = {}
        verdicts = iter([(False, "第一轮判词：缺 X"), (False, "第二轮判词")])

        def _spy(*a, **k):
            captured.update(k)
            return next(verdicts)

        monkeypatch.setattr(eng, "run_judge", _spy)
        eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))  # block 1
        with ev.open("a", encoding="utf-8") as f:
            f.write(_trace_line(1, "ev2") + "\n")
        eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))  # block 2
        assert captured["prior_verdicts"] == ["第一轮判词：缺 X"]

    def test_first_judgment_no_priors(self, tmp_path, monkeypatch):
        self._setup_u1_step1(tmp_path)
        captured = {}

        def _spy(*a, **k):
            captured.update(k)
            return (False, "x")

        monkeypatch.setattr(eng, "run_judge", _spy)
        eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert not captured.get("prior_verdicts")

    def test_prior_verdicts_scope_cap_and_truncation(self, tmp_path):
        # 只取本节点本步 blocked 判词（passed/它步/它节点排除）；最近 3 条；
        # 单条截断防判词膨胀 judge 输入
        self._setup_u1_step1(tmp_path)

        def _rec(sub_step, gate, reason, minor="ProblemContext"):
            return json.dumps(
                {
                    "kind": "gate",
                    "gate": gate,
                    "sub_step": sub_step,
                    "minor_stage": minor,
                    "reason": reason,
                },
                ensure_ascii=False,
            )

        ev = eng._evidence_path(tmp_path, "t")
        with ev.open("a", encoding="utf-8") as f:
            f.write(_rec(1, "blocked", "r1") + "\n")
            f.write(_rec(2, "blocked", "其他步") + "\n")
            f.write(_rec(1, "passed", "") + "\n")
            f.write(_rec(1, "blocked", "它节点", minor="GoalsAndValue") + "\n")
            f.write(_rec(1, "blocked", "长" * 500) + "\n")
            f.write(_rec(1, "blocked", "r3") + "\n")
            f.write(_rec(1, "blocked", "r4") + "\n")
        priors = eng.prior_block_reasons(tmp_path, "t", 1, "ProblemContext")
        assert len(priors) == 3
        assert priors[1:] == ["r3", "r4"]
        assert priors[0].startswith("长" * 100) and len(priors[0]) <= 410

    def test_prompt_consistency_section(self, monkeypatch):
        # prior_verdicts 非空 -> 判决 prompt 附一致性指令；空 -> 不加（首判口径不变）
        captured = {}

        class _Res:
            returncode = 0
            stdout = '{"is_error":false,"result":"{\\"pass\\": true, \\"reason\\": \\"\\"}"}\n'

        def _run(cmd, **kw):
            captured["cmd"] = cmd
            return _Res()

        monkeypatch.setattr(eng.subprocess, "run", _run)
        eng.run_judge("RUB", "LBL", "OUT", prior_verdicts=["前轮：缺 X"])
        prompt = captured["cmd"][-1]
        assert "前轮：缺 X" in prompt and "一致性" in prompt
        eng.run_judge("RUB", "LBL", "OUT")
        assert "一致性" not in captured["cmd"][-1]

    def test_rejudge_prompt_requires_rewrite_example(self, monkeypatch):
        # v2.29 #5：重判时判词须附正确改写范例——指模式不指实例
        # （u:3 子4 判词只点名实例位置，模型逐条打地鼠造新雷）
        captured = {}

        class _Res:
            returncode = 0
            stdout = '{"is_error":false,"result":"{\\"pass\\": true, \\"reason\\": \\"\\"}"}\n'

        def _run(cmd, **kw):
            captured["cmd"] = cmd
            return _Res()

        monkeypatch.setattr(eng.subprocess, "run", _run)
        eng.run_judge("RUB", "LBL", "OUT", prior_verdicts=["前轮：缺 X"])
        assert "范例" in captured["cmd"][-1]


class TestScopeSub3DualField:
    """v2.28 子3 双字段倒推（消费契约倒推 §3.8：子4 判据要求应倒推成子3 产物
    字段）。tail_volume u:3 子4 审计：创造性抽象负担全压子4（弱模型最难的
    一次转换，只判一次）——正解=子3 范围界定每项带双字段（具体实现指针+
    outcome 层标签），抽象在有 codegraph 取证条件的子3 完成，子4 退化装配步。
    """

    def test_sub3_purpose_requires_dual_field(self):
        stp = eng.get_node("understand", 3).sub_steps[2]
        assert "outcome" in stp.purpose and "实现指针" in stp.purpose
        assert "outcome" in stp.selfcheck

    def test_sub3_gate_checks_dual_field(self):
        gate = eng.get_node("understand", 3).sub_steps[2].gate
        assert "双字段" in gate or ("实现指针" in gate and "outcome" in gate)

    def test_sub4_purpose_is_assembly_not_creation(self):
        purpose = eng.get_node("understand", 3).sub_steps[3].purpose
        assert "装配" in purpose and "二次创作" in purpose


class TestStatementsRecordFormat:
    """v2.27 产出型步结构化 record + 机械预检下沉（tail_volume u:3 子4 审计：
    q/a 问答模具与清单型产出语义错配——3 次长度不齐全在归一化步；判据的
    词形部分应下沉机械层，judge 只判真值/质量）。

    record_format="statements" 的步（u:2 子4 / u:3 子4 / u:4 子4，归一化+
    solution-free 族）载荷 {"purpose","statements":[{"text","type_label",
    "boundary"}]}；append-trace 机械预检：
    ①三字段非空 ②text 方案名词扫描（codegraph 类/函数名 + git 文件名真值，
    实现指针只能进 boundary 字段——对 text 扫描即判主语/陈述体）
    ③源步 ID 传导覆盖核对（in[1]/C1.1 缺传=拒，judge #1 的活）。u:1 子5
    无 solution-free 判据，留 qa 格式。"""

    def _setup_sc4(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 3, sub_step=4)
        return tmp_path / "payload.json"

    def _write_payload(self, payload, obj):
        payload.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    def _statements(self, *texts):
        return [{"text": t, "type_label": "in", "boundary": "无"} for t in texts]

    def test_three_normalization_steps_declare_statements(self):
        for phase, sub, step_no in (
            ("understand", 2, 4),
            ("understand", 3, 4),
            ("understand", 4, 4),
        ):
            stp = eng.get_node(phase, sub).sub_steps[step_no - 1]
            assert stp.record_format == "statements", f"{phase}:{sub} 子{step_no}"
        assert eng.get_node("understand", 1).sub_steps[4].record_format == "qa"

    def test_statements_happy_path(self, tmp_path):
        payload = self._setup_sc4(tmp_path)
        self._write_payload(
            payload,
            {
                "purpose": "归一化",
                "statements": self._statements(
                    "年化数字允许被更新", "覆盖率上限可配置"
                ),
            },
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert ok, msg
        rec = json.loads(
            (tmp_path / ".claude" / "evidence" / "t.jsonl")
            .read_text(encoding="utf-8")
            .strip()
        )
        assert len(rec["statements"]) == 2 and "q" not in rec and "a" not in rec

    def test_statements_missing_field_rejected(self, tmp_path):
        payload = self._setup_sc4(tmp_path)
        self._write_payload(
            payload,
            {"purpose": "p", "statements": [{"text": "x", "type_label": "in"}]},
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert not ok and "boundary" in msg

    def test_statements_mixed_with_qa_rejected(self, tmp_path):
        payload = self._setup_sc4(tmp_path)
        self._write_payload(
            payload,
            {
                "purpose": "p",
                "statements": self._statements("x"),
                "qa": [{"q": "q", "a": "a"}],
            },
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert not ok and "混用" in msg

    def _git_repo_with_file(self, tmp_path, name):
        import subprocess as sp

        sp.run(["git", "init"], cwd=tmp_path, capture_output=True)
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x", encoding="utf-8")
        sp.run(["git", "add", name], cwd=tmp_path, capture_output=True)

    def test_implementation_noun_in_text_rejected(self, tmp_path):
        self._setup_sc4(tmp_path)
        self._git_repo_with_file(tmp_path, "web_ui/templates/_macros.html")
        payload = tmp_path / "payload.json"
        self._write_payload(
            payload,
            {
                "purpose": "p",
                "statements": [
                    {
                        "text": "_macros.html 允许被调整",
                        "type_label": "in",
                        "boundary": "无",
                    }
                ],
            },
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert not ok and "_macros.html" in msg and "boundary" in msg

    def test_implementation_noun_in_boundary_allowed(self, tmp_path):
        self._setup_sc4(tmp_path)
        self._git_repo_with_file(tmp_path, "web_ui/templates/_macros.html")
        payload = tmp_path / "payload.json"
        self._write_payload(
            payload,
            {
                "purpose": "p",
                "statements": [
                    {
                        "text": "因子卡片模板允许被调整",
                        "type_label": "in",
                        "boundary": "实现指针：web_ui/templates/_macros.html",
                    }
                ],
            },
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert ok, msg

    def test_codegraph_class_name_in_text_rejected(self, tmp_path):
        import sqlite3

        self._setup_sc4(tmp_path)
        cg = tmp_path / ".codegraph"
        cg.mkdir(parents=True)
        con = sqlite3.connect(cg / "codegraph.db")
        con.execute("CREATE TABLE nodes (name TEXT, kind TEXT)")
        con.execute("INSERT INTO nodes VALUES ('LayerConfigBase', 'class')")
        con.commit()
        con.close()
        payload = tmp_path / "payload.json"
        self._write_payload(
            payload,
            {
                "purpose": "p",
                "statements": [
                    {
                        "text": "LayerConfigBase 的子类允许扩展",
                        "type_label": "in",
                        "boundary": "无",
                    }
                ],
            },
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert not ok and "LayerConfigBase" in msg

    def test_id_coverage_missing_rejected(self, tmp_path):
        self._setup_sc4(tmp_path)
        # 源步（子3）trace 用 in/out/C 编号；子4 缺传 in[2] -> 拒并点名
        ev = eng._evidence_path(tmp_path, "t")
        ev.parent.mkdir(parents=True, exist_ok=True)
        src = json.dumps(
            {
                "kind": "skill-trace",
                "major_stage": "Understand",
                "minor_stage": "ScopeAndConstraints",
                "sub_step": 3,
                "skill": "define-problem",
                "purpose": "范围界定",
                "q": ["in 侧？"],
                "a": ["in[1] 因子卡片 in[2] 分层表 out[A] 后端 C1.1 硬规则"],
            },
            ensure_ascii=False,
        )
        ev.write_text(src + "\n", encoding="utf-8")
        payload = tmp_path / "payload.json"
        self._write_payload(
            payload,
            {
                "purpose": "p",
                "statements": self._statements(
                    "in[1] 因子卡片允许改 out[A] 不动 C1.1 遵守"
                ),
            },
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert not ok and "in[2]" in msg

    def test_id_coverage_no_ids_in_source_passes(self, tmp_path):
        self._setup_sc4(tmp_path)
        payload = tmp_path / "payload.json"
        self._write_payload(
            payload,
            {"purpose": "p", "statements": self._statements("x 允许被改动")},
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert ok, msg


class TestRubricDispute:
    """v2.30 #7 判据申诉通道（tail_volume u:3 子4：模型第 4 轮已正确诊断
    「判据与 in-scope 命题矛盾」，但 escalate 只有重做/放行/回退三出口——
    诊断无通道，判据修订被迫跑到运行外）。第 4 出口：用户认可判据有缺陷 ->
    模型 dl-cmd.sh dispute 落 kind=rubric-dispute 记录。
    判据修订权归人：记录只留痕供修订检索，不自动改判据。"""

    def test_dispute_writes_record(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 3, sub_step=4)
        ok, msg = eng.write_rubric_dispute(tmp_path, "t", "判据与 in-scope 命题矛盾")
        assert ok, msg
        rec = json.loads(
            (tmp_path / ".claude" / "evidence" / "t.jsonl")
            .read_text(encoding="utf-8")
            .strip()
        )
        assert rec["kind"] == "rubric-dispute"
        assert rec["node"] == "understand:3"
        assert rec["sub_step"] == 4
        assert rec["minor_stage"] == "ScopeAndConstraints"
        assert "矛盾" in rec["reason"]
        assert "gate" not in rec  # 非门控裁决记录，不与 kind=gate 混淆

    def test_dispute_missing_state_rejected(self, tmp_path):
        ok, msg = eng.write_rubric_dispute(tmp_path, "t", "x")
        assert not ok and "state" in msg

    def test_dispute_cli(self, tmp_path, capsys):
        _init_git(tmp_path)
        _write_state_full(tmp_path, "t", "understand", 3, sub_step=4)
        rc = eng.main(["dispute", "t", "判据太宽", "--cwd", str(tmp_path)])
        assert rc == 0
        rec = json.loads(
            (tmp_path / ".claude" / "evidence" / "t.jsonl")
            .read_text(encoding="utf-8")
            .strip()
        )
        assert rec["reason"] == "判据太宽"


class TestSolutionFreeRuleInGates:
    """v2.24 裁量点钉死双侧化：操作化定义必须进 gate（judge 侧），不只进
    purpose/selfcheck（模型侧）。v2.23 只钉模型侧——judge 输入面仍只有一句
    黑盒判词「含方案名词/实现动词判 block」，解释轮间漂移（tail_volume
    understand:3 子4 五连 block：类名入主语→实现指针段→动词词形逐轮收紧，
    §3.5 #4 判据留白=方差）。本测试钉死双侧引用不回归。"""

    # v2.23 同构族 5 步：understand:2 子2/子4、understand:3 子4、understand:4 子1/子4
    _FIVE_STEPS = [
        ("understand", 2, 2),
        ("understand", 2, 4),
        ("understand", 3, 4),
        ("understand", 4, 1),
        ("understand", 4, 4),
    ]

    def test_subject_rule_cited_in_all_five_gates(self):
        for phase, sub, step_no in self._FIVE_STEPS:
            gate = eng.get_node(phase, sub).sub_steps[step_no - 1].gate
            assert gate, f"{phase}:{sub} 子{step_no} 无 gate"
            assert "主语只许 outcome-level" in gate, (
                f"{phase}:{sub} 子{step_no} gate 未引用 _SOLUTION_FREE_SUBJECT_RULE"
                "（judge 侧裁量点未钉死）"
            )

    def test_scope_verb_rule_in_understand3_sub4_gate(self):
        # 范围命题构成性谓语合法化：动词按指向判，「允许/禁止改动」不判违规
        gate = eng.get_node("understand", 3).sub_steps[3].gate
        assert "按指向判" in gate and "允许/禁止改动" in gate

    def test_scope_verb_rule_disclosed_to_model(self):
        # purpose/selfcheck 同步披露（形式要件双侧单源，对齐 _DS_STEP1 先例）
        step = eng.get_node("understand", 3).sub_steps[3]
        assert "按指向判" in step.purpose
        assert "按指向判" in step.selfcheck


class TestAtomicItemRule:
    """v2.32「复合句」裁量点钉死双侧化（2026-07-31 tail_volume 审计）：
    plan:1 子5 / plan:2 子4 各三连 block + 用户强制放行——judge 按词形
    （「+」「然后」/括号枚举）判复合，与字段携带形式要件自相矛盾。
    原子性按独立性判（_ATOMIC_ITEM_RULE 单源），purpose/selfcheck 与 gate
    双侧引用不回归。"""

    _TWO_STEPS = [("plan", 1, 5), ("plan", 2, 4)]

    def test_rule_cited_in_both_gates(self):
        for phase, sub, step_no in self._TWO_STEPS:
            gate = eng.get_node(phase, sub).sub_steps[step_no - 1].gate
            assert gate, f"{phase}:{sub} 子{step_no} 无 gate"
            assert "按独立性判" in gate, (
                f"{phase}:{sub} 子{step_no} gate 未引用 _ATOMIC_ITEM_RULE"
                "（judge 侧裁量点未钉死）"
            )

    def test_rule_disclosed_to_model(self):
        for phase, sub, step_no in self._TWO_STEPS:
            step = eng.get_node(phase, sub).sub_steps[step_no - 1]
            assert "按独立性判" in step.purpose, (
                f"{phase}:{sub} 子{step_no} purpose 未披露原子性规则"
            )

    def test_taskbreakdown_tdd_microcycle_legalized(self):
        # TDD 微循环 = 交付物内含流程不算复合（tail_volume plan:2 子4
        # 「写测试+实现+验证+commit」三连 block 的直接判据）
        gate = eng.get_node("plan", 2).sub_steps[3].gate
        assert "内含流程" in gate and "不算复合" in gate

    def test_compound_definition_is_independence_not_wording(self):
        # 复合句 = ≥2 个可独立成立的项（分别拍板/分别提交），词形不判
        for phase, sub, step_no in self._TWO_STEPS:
            gate = eng.get_node(phase, sub).sub_steps[step_no - 1].gate
            assert "复合句" in gate and "可独立成立" in gate


class TestAppendTrace:
    """v2.14 append-trace（「AI 定写什么，脚本定怎么写」A 级）：
    载荷 purpose/q/a + state 结构字段 -> 校验 -> 单行 append。fail loud 即时暴露。"""

    def _setup(self, tmp_path, sub_step=3):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=sub_step)
        payload = tmp_path / "payload.json"
        return payload

    def _write_payload(self, payload, obj):
        payload.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    def test_happy_path_fills_struct_fields(self, tmp_path):
        payload = self._setup(tmp_path)
        self._write_payload(
            payload, {"purpose": "双向取证", "q": ["q1", "q2"], "a": ["a1", "a2"]}
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert ok, msg
        line = (
            (tmp_path / ".claude" / "evidence" / "t.jsonl")
            .read_text(encoding="utf-8")
            .strip()
        )
        rec = json.loads(line)
        assert rec["kind"] == "skill-trace"
        assert rec["major_stage"] == "Understand"
        assert rec["minor_stage"] == "ProblemContext"
        assert rec["sub_step"] == 3
        node = eng.get_node("understand", 1)
        assert rec["skill"] == node.sub_steps[2].ref  # 从 state 当前步推导，非模型给
        assert rec["q"] == ["q1", "q2"] and rec["a"] == ["a1", "a2"]
        assert not payload.exists()  # 落库后删载荷防重复 append

    def test_gate_sees_appended_trace(self, tmp_path):
        # 与门控集成：append-trace 落库后 latest_trace_sha1 变化（Stop 门控可触发）
        payload = self._setup(tmp_path)
        assert eng.latest_trace_sha1(tmp_path, "t", 3) is None
        self._write_payload(payload, {"purpose": "p", "q": ["q"], "a": ["a"]})
        ok, _ = eng.append_trace(tmp_path, "t", str(payload))
        assert ok
        assert eng.latest_trace_sha1(tmp_path, "t", 3) is not None

    def test_struct_fields_leak_rejected(self, tmp_path):
        payload = self._setup(tmp_path)
        self._write_payload(
            payload, {"purpose": "p", "q": ["q"], "a": ["a"], "sub_step": 99}
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert not ok and "结构字段" in msg
        assert payload.exists()  # 失败保留载荷供原地修

    def test_qa_length_mismatch_rejected(self, tmp_path):
        payload = self._setup(tmp_path)
        self._write_payload(payload, {"purpose": "p", "q": ["q1", "q2"], "a": ["a1"]})
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert not ok and "长度不齐" in msg

    def test_legacy_mismatch_error_shows_unpaired_items(self, tmp_path):
        # v2.24 报错可操作化：给无配对项的索引+内容头，模型可 surgical 修
        # 不再整篇盲重写（tail_volume understand:3 子4 三次 q/a 不齐各白烧 ~3k out）
        payload = self._setup(tmp_path)
        self._write_payload(
            payload, {"purpose": "p", "q": ["q1-身份", "q2-无主"], "a": ["a1"]}
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert not ok and "长度不齐" in msg
        assert "q[1]" in msg and "q2-无主" in msg

    def test_qa_pairs_format_happy_path(self, tmp_path):
        # v2.24 qa 配对格式：一问一答成对象，不对齐在结构上不可表示。
        # evidence 记录 schema 不变（仍 q/a 平行数组，下游 read_evidence 不改）。
        payload = self._setup(tmp_path)
        self._write_payload(
            payload,
            {"purpose": "p", "qa": [{"q": "q1", "a": "a1"}, {"q": "q2", "a": "a2"}]},
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert ok, msg
        rec = json.loads(
            (tmp_path / ".claude" / "evidence" / "t.jsonl")
            .read_text(encoding="utf-8")
            .strip()
        )
        assert rec["q"] == ["q1", "q2"] and rec["a"] == ["a1", "a2"]

    def test_qa_pairs_item_missing_key_rejected(self, tmp_path):
        payload = self._setup(tmp_path)
        self._write_payload(
            payload, {"purpose": "p", "qa": [{"q": "q1"}, {"q": "q2", "a": "a2"}]}
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert not ok and "qa[0]" in msg

    def test_qa_mixed_with_parallel_arrays_rejected(self, tmp_path):
        payload = self._setup(tmp_path)
        self._write_payload(
            payload,
            {"purpose": "p", "qa": [{"q": "q", "a": "a"}], "q": ["q"], "a": ["a"]},
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert not ok and "混用" in msg

    def test_empty_q_rejected(self, tmp_path):
        payload = self._setup(tmp_path)
        self._write_payload(payload, {"purpose": "p", "q": [], "a": []})
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert not ok and "非空字符串数组" in msg

    def test_invalid_json_rejected(self, tmp_path):
        payload = self._setup(tmp_path)
        payload.write_text("{not json", encoding="utf-8")
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert not ok and "不是合法 JSON" in msg

    def test_missing_payload_rejected(self, tmp_path):
        self._setup(tmp_path)
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "nope.json"))
        assert not ok and "读载荷失败" in msg

    def test_node_without_substeps_rejected(self, tmp_path):
        _write_state_full(tmp_path, "t", "execute", 0)  # execute:0 无编排
        payload = tmp_path / "payload.json"
        self._write_payload(payload, {"purpose": "p", "q": ["q"], "a": ["a"]})
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert not ok and "无子步骤编排" in msg

    def test_success_message_guides_incremental_summary(self, tmp_path):
        # v2.25 轮末总结瘦身：tail_volume understand:3 子4 五轮返工各把 36-45 条
        # 陈述全文重述一遍（共 ~3.7k out）——judge 只读 evidence 不读正文，纯烧。
        # 成功消息在模型写正文前的决策点指路增量总结。
        payload = self._setup(tmp_path)
        self._write_payload(payload, {"purpose": "p", "qa": [{"q": "q", "a": "a"}]})
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert ok
        assert "增量总结" in msg and "全文重述" in msg


class TestRedteamPrompt:
    """v2.14 redteam-prompt（B 级）：证据+纪律归脚本，Agent 调用归模型。"""

    def test_contains_evidence_and_discipline(self, tmp_path):
        _write_evidence(tmp_path, "t", [_trace_line(3, "ev3")])
        prompt = eng.redteam_prompt(tmp_path, "t")
        assert prompt is not None
        assert "q-ev3" in prompt  # 子3 证据嵌入（只给证据不给结论）
        assert "单层" in prompt and "禁止再 spawn 子代理" in prompt  # b
        assert "Read 工具为主" in prompt  # c
        assert "证据不足" in prompt  # d
        assert "四态 verdict" in prompt or "证实/证伪/部分成立/证据不足" in prompt

    def test_no_step3_trace_returns_none(self, tmp_path):
        _write_evidence(tmp_path, "t", [_trace_line(1)])
        assert eng.redteam_prompt(tmp_path, "t") is None
