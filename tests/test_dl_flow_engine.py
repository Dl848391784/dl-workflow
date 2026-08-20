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
import subprocess
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
        # §orchestration v2 + 2026-07-26 重设计：understand:1 有 7 子步骤，越界 -> 报错暴露
        for bad in (0, 8):
            with pytest.raises(ValueError, match="越界"):
                eng.normalize_state(
                    {"phase": "understand", "sub_index": 1, "sub_step_index": bad}
                )

    def test_sub_step_index_in_range_ok(self):
        # 1..7 合法范围不报错
        for ok in (1, 2, 3, 4, 5, 6, 7):
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
    子4 加④处置问题集；子5 一句话陈述→归一化陈述（裁决传导）；子6→带证据读回确认。
    plan-first 拆步（2026-08-14）：子2 一拆二后全重编号，原子4/5/6 顺延为子5/6/7。"""

    def _steps(self):
        node = eng.get_node("understand", 1)
        assert node.sub_steps is not None and len(node.sub_steps) == 7
        return node.sub_steps

    def test_step5_disposition_in_purpose_and_gate(self):
        s5 = self._steps()[4]
        assert "处置问题集" in s5.purpose
        assert "处置后问题集与 verdict 逐项一致" in s5.gate

    def test_step6_normalization_verdict_consistency(self):
        s6 = self._steps()[5]
        assert "归一化陈述" in s6.purpose
        assert s6.input == "step5.disposed_problem_set"
        # 裁决不传导判 block：陈述集与 verdict 一致性是质量判据
        assert "裁决不传导" in s6.gate
        assert "证伪项不得出现在" in s6.gate

    def test_step6_no_grammatical_subject_requirement_all_layers(self):
        """v2.85 #29 跨层同向：「主语+动词+约束」词形是 clean 1/6 的最高频误伤源
        （judge 照字面索取语法主语，判中文合法动宾短语「统计 X 的数量」缺主语）。
        修文本而非站队（#23），且 purpose/selfcheck/gate 三层齐改——只改 gate
        则 judge 放行而模型仍被 purpose 指使去凑主语，一次通过率不升。"""
        s6 = self._steps()[5]
        for layer in (s6.purpose, s6.selfcheck):
            assert "主语+动词+约束" not in layer, "旧词形回潮：judge/模型会索取语法主语"
            assert "省略主语合法" in layer, "缺「省略主语合法」钉死"
        assert "对象+动作+约束自包含" in s6.gate
        assert "不得判「缺主语/非陈述式/祈使短语」" in s6.gate

    def test_step7_readback_with_evidence_gate_none(self):
        s7 = self._steps()[6]
        assert s7.gate is None  # 交互步不跑 judge（trace 存在即过）
        assert s7.tier == "confirm"  # P3-1 读回降确认级（2026-08-13 用户裁决）
        assert "静默通过" in s7.purpose and "state-reset" in s7.purpose
        # 原「证据指针/证据不足呈现」归 render-readback 机械装配（见该函数测试）

    def test_all_six_steps_record_true(self):
        # 末步 record=True 是 Stop 门控的完成触发信号（3a 潜在洞修复）
        assert all(s.record for s in self._steps())


class TestEvidenceTierRedesign:
    """2026-08-13 取证深度档与取证策略重设计
    （designs/evidence-gathering-tier-redesign-design.md）：sub3 审计实证 light+full
    两 agent 17 curl 仅 4 次有效（24%）。A1 light 例错删；A2 值不值得取证判据；
    B1/B2 权威源注册表定点抓 + 术语翻译 + 泛搜兜底。
    （A3 tier 前置已回退——真实 sub2 从 55 轮爆炸到 152 轮：定「none 仓内可达」
    本身依赖因果链的探索，前置导致双倍探索。）"""

    def _steps(self):
        node = eng.get_node("understand", 1)
        assert node.sub_steps is not None and len(node.sub_steps) == 7
        return node.sub_steps

    def test_sub2a_tier_rule_value_check(self):
        p2 = self._steps()[1].purpose  # sub2a 规划拆解
        # A2：值不值得取证判据（外部取证是否改变结论方向）
        assert "值不值得" in p2 or "是否改变「问题是否成立」" in p2
        # A1：light 旧例子「年化量级合理性」移除、换成「有具体公认一次即得」
        assert "（如年化量级合理性判断）" not in p2
        assert "有具体、公认、一次即得" in p2

    def test_sub4_authority_registry_and_targeted_fetch(self):
        p4 = self._steps()[3].purpose  # sub4 双向取证
        # B1：权威源注册表（按 claim 类型定点抓）
        assert "权威源注册表" in p4
        # B2：定点抓权威源 + 术语翻译 + 泛搜兜底
        assert "定点抓" in p4
        assert "业界术语" in p4


class TestHarnessPromptOptimization:
    """2026-07-26 harness 化优化（designs/harness-prompt-optimization-design.md）：
    Step.short 骨架短名（P0 注入瘦身）；purpose 清考古（P2，规则留、考古移注释）；
    render-phase-rules（P1 双通道单源）；rubric 判据关键词回归钉死。"""

    def _steps(self):
        node = eng.get_node("understand", 1)
        assert node.sub_steps is not None
        return node.sub_steps

    # ----- P0：short 字段 -----
    def test_seven_steps_short_labels(self):
        shorts = [s.short for s in self._steps()]
        assert shorts == [
            "逼问定义",
            "规划拆解",
            "因果链挖掘",
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
        # 子1：v2.71 framing 收口--who 出处下沉 mech，gate 不再逐字"who 类出处只认
        # 用户自述"；②偷懒「未提及」仍在 gate。who 接口钉死改查 purpose + mech
        assert "「未提及」" in s[0].gate
        assert "角色类选项" in s[0].purpose
        assert "who_no_repo_fact" in s[0].mech_checks
        # 子2b：反同义反复 + 反稻草人（原子2 方框一/二/三顺延）
        assert "同义反复判 block" in s[2].gate
        assert "竞争假设非稻草人" in s[2].gate
        # 子4：可追溯指针 + 反训练记忆冒充
        assert "可追溯指针" in s[3].gate
        assert "用训练记忆冒充外部证据 = 编造" in s[3].gate
        # 子5：三关质检 + 红队触发强制
        assert "三关质检记录" in s[4].gate
        assert "只给证据不给结论" in s[4].gate
        # 子6：裁决传导
        assert "裁决不传导判 block" in s[5].gate

    def test_purpose_keywords_regression(self):
        s = self._steps()
        # 子4（v2.38 子代理化）：禁 tavily/WebSearch/WebFetch + fetch-prompt 骨架 +
        # 反证先/支持后时序披露（证伪优先纪律移入子代理返回契约，禁探查凭证同移）
        assert "反证先/支持后" in s[3].purpose
        assert "禁 tavily_search/WebSearch/WebFetch" in s[3].purpose
        assert "fetch-prompt" in s[3].purpose
        # 子5：红队触发条件 + redteam-prompt 生成器（纪律 a-d 已机械化进模板）
        for frag in (
            "条件触发对抗复核",
            "只给证据不给结论",
            "redteam-prompt",
            "触发条件写死",
        ):
            assert frag in s[4].purpose

    # ----- P1：render-phase-rules -----
    def test_render_substeps_section(self):
        out = eng.render_substeps_section("understand:1")
        assert out.startswith("<!-- BEGIN GENERATED sub_steps understand:1 -->")
        assert out.endswith("<!-- END GENERATED sub_steps understand:1 -->")
        # 渲染行含 ref + purpose 全文（与 engine 逐字同源）
        s1 = self._steps()[0]
        assert f"- **子步骤1 = {s1.ref}**：{s1.purpose}" in out
        # gate=None 标自动过
        assert "**子步骤7 = define-problem**（自动过）" in out

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
        # understand:1 有 7 子步骤（2026-07-26 重设计：验真拆双向取证+质检裁决；
        # 2026-08-14 plan-first：子2 一拆二规划+执行）
        assert eng.sub_step_total(eng.get_node("understand", 1)) == 7
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
        node = eng.get_node("understand", 4)  # 末子阶段（artifact_contains 机械门）
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
        assert rec["gate_mech"] == "artifact_contains"
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


class TestSubagentRetryStats:
    """v2.39：子代理空响应重试统计随 gate 裁决记录落 evidence。

    实证出处：tail_volume u:1 子3 Q4 取证 agent 26 次空响应重试烧 1.19M
    input（占 90%），无台账只能靠手工挖 transcript 发现。
    """

    def _mk_subagents(self, tmp_path, monkeypatch, agents: dict[str, list[dict]]):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        enc = "".join(c if c.isalnum() else "-" for c in str(tmp_path))
        d = home / ".claude" / "projects" / enc / "s" / "subagents"
        d.mkdir(parents=True)
        for fname, msgs in agents.items():
            with (d / fname).open("w", encoding="utf-8") as f:
                for m in msgs:
                    f.write(json.dumps(m) + "\n")
        return d

    def test_counts_empty_responses(self, tmp_path, monkeypatch):
        self._mk_subagents(
            tmp_path,
            monkeypatch,
            {
                "agent-a1.jsonl": [
                    {"type": "user", "message": {}},
                    {
                        "type": "assistant",
                        "message": {
                            "usage": {"input_tokens": 5000, "output_tokens": 0}
                        },
                    },
                    {
                        "type": "assistant",
                        "message": {
                            "usage": {"input_tokens": 6000, "output_tokens": 0}
                        },
                    },
                    {
                        "type": "assistant",
                        "message": {
                            "usage": {"input_tokens": 3000, "output_tokens": 120}
                        },
                    },
                ],
                "agent-a2.jsonl": [
                    {
                        "type": "assistant",
                        "message": {
                            "usage": {"input_tokens": 2000, "output_tokens": 50}
                        },
                    },
                ],
            },
        )
        stats = eng._subagent_retry_stats(tmp_path, "t")
        assert stats == {
            "agents": 2,
            "empty_responses": 2,
            "burned_input_tokens": 11000,
            "per_agent": [
                {"tiers": [], "curl_calls": 0},
                {"tiers": [], "curl_calls": 0},
            ],
            "light_tier_violations": 0,
        }

    def test_attached_to_gate_record(self, tmp_path, monkeypatch):
        self._mk_subagents(
            tmp_path,
            monkeypatch,
            {
                "agent-a1.jsonl": [
                    {
                        "type": "assistant",
                        "message": {
                            "usage": {"input_tokens": 4000, "output_tokens": 0}
                        },
                    },
                ],
            },
        )
        node = eng.get_node("understand", 3)
        ok = eng.write_gate_verdict(tmp_path, "t", node, attempts=0, cwd=str(tmp_path))
        assert ok is True
        rec = json.loads(
            eng._evidence_path(tmp_path, "t").read_text(encoding="utf-8").strip()
        )
        assert rec["subagent_retry"]["empty_responses"] == 1
        assert rec["subagent_retry"]["burned_input_tokens"] == 4000

    def test_per_agent_tier_and_curl_counted(self, tmp_path, monkeypatch):
        # v2.40：[tier=X] 标记归属 + curl 轮次计数 + light 档 >4 违例
        curl_msg = {
            "type": "assistant",
            "message": {
                "usage": {"input_tokens": 100, "output_tokens": 10},
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {
                            "command": "curl -sS -m 25 https://api.openalex.org/x"
                        },
                    }
                ],
            },
        }
        self._mk_subagents(
            tmp_path,
            monkeypatch,
            {
                "agent-light.jsonl": [
                    {
                        "type": "user",
                        "message": {"content": "骨架…原子2 [tier=light]：年化量级…"},
                    },
                    *[curl_msg for _ in range(5)],
                ],
                "agent-full.jsonl": [
                    {
                        "type": "user",
                        "message": {"content": "骨架…原子3 [tier=full]：系统设计…"},
                    },
                    *[curl_msg for _ in range(9)],
                ],
            },
        )
        stats = eng._subagent_retry_stats(tmp_path, "t")
        assert stats["per_agent"][0] == {"tiers": ["full"], "curl_calls": 9}
        assert stats["per_agent"][1] == {"tiers": ["light"], "curl_calls": 5}
        # light 档 5 > 4 违例；full 档 9 ≤ 12 不违例
        assert stats["light_tier_violations"] == 1

    def test_mixed_tier_markers_not_counted_as_light(self, tmp_path, monkeypatch):
        # claim 区未按纪律裁剪（多原子行同进一个 prompt）-> tiers 记全部，
        # 归属不唯一不算纯 light，违例判定保守不计
        curl_msg = {
            "type": "assistant",
            "message": {
                "usage": {"input_tokens": 100, "output_tokens": 10},
                "content": [
                    {"type": "tool_use", "name": "Bash", "input": {"command": "curl x"}}
                ],
            },
        }
        self._mk_subagents(
            tmp_path,
            monkeypatch,
            {
                "agent-mix.jsonl": [
                    {
                        "type": "user",
                        "message": {
                            "content": "原子1 [tier=full]：…\n原子2 [tier=light]：…"
                        },
                    },
                    *[curl_msg for _ in range(6)],
                ],
            },
        )
        stats = eng._subagent_retry_stats(tmp_path, "t")
        assert stats["per_agent"][0]["tiers"] == ["full", "light"]
        assert stats["light_tier_violations"] == 0

    def test_none_without_state_or_dir(self, tmp_path):
        # 无 state -> None（字段省略）；有 state 无 subagents 目录 -> None
        assert eng._subagent_retry_stats(tmp_path, "t") is None
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        assert eng._subagent_retry_stats(tmp_path, "t") is None
        # 字段省略不污染裁决记录
        node = eng.get_node("understand", 3)
        eng.write_gate_verdict(tmp_path, "t", node, attempts=0, cwd=str(tmp_path))
        rec = json.loads(
            eng._evidence_path(tmp_path, "t").read_text(encoding="utf-8").strip()
        )
        assert "subagent_retry" not in rec

    def test_finds_segment_worker_dir(self, tmp_path, monkeypatch):
        # v4 前台混合回归：agent 由段工人派发，transcript 在段工人 session 目录
        # （非 state.session_id="s" 的前台会话）。glob 定位须命中段工人目录
        # （2026-08-13 amplitude_annualized 实证：state.session_id 恒指前台，
        # 台账在 driver 模式静默返 None）。
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        enc = "".join(c if c.isalnum() else "-" for c in str(tmp_path))
        d = home / ".claude" / "projects" / enc / "seg-sid" / "subagents"
        d.mkdir(parents=True)
        with (d / "agent-a1.jsonl").open("w", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "usage": {"input_tokens": 5000, "output_tokens": 0}
                        },
                    }
                )
                + "\n"
            )
        stats = eng._subagent_retry_stats(tmp_path, "t")
        assert stats is not None
        assert stats["agents"] == 1
        assert stats["empty_responses"] == 1

    def test_retry_stats_uses_newest_dir(self, tmp_path, monkeypatch):
        # round-2 修 A 第二面：多会话目录时代「本会话」= 最新 agent 文件所在目录
        # （transcript 写入时间锚，不受目录被 touch/拷贝残留污染；段顺序执行
        # 当前段的 agent 恒最新写入）——旧实现取字典序第一个，台账扫旧会话
        # agent 错位（amplitude_annualized 14 个 subagents 目录实测）。
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        enc = "".join(c if c.isalnum() else "-" for c in str(tmp_path))
        base = home / ".claude" / "projects" / enc
        old_d = base / "aaa-old" / "subagents"
        old_d.mkdir(parents=True)
        old_fp = old_d / "agent-old.jsonl"
        old_fp.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"usage": {"input_tokens": 999, "output_tokens": 0}},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        cur_d = base / "zzz-cur" / "subagents"
        cur_d.mkdir(parents=True)
        cur_fp = cur_d / "agent-new.jsonl"
        cur_fp.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"usage": {"input_tokens": 100, "output_tokens": 50}},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        # 目录 mtime 反向污染（旧目录被 touch 成最新）也不影响文件锚判定
        os.utime(old_fp, (1000000000, 1000000000))
        os.utime(cur_fp, (1000000050, 1000000050))
        os.utime(old_d, (1000000100, 1000000100))
        os.utime(cur_d, (1000000000, 1000000000))
        stats = eng._subagent_retry_stats(tmp_path, "t")
        assert stats is not None
        assert stats["agents"] == 1 and stats["empty_responses"] == 0


# ---------- §orchestration v2：understand:1 子步骤编排（替代过渡「≥3 Q/A」） ----------


class TestUnderstand1Orchestration:
    """understand:1 纯子步骤门控（删过渡 gate_rubric，7 子步骤逐步 STEP_DONE gate）。

    2026-07-26 重设计（designs/step3-verify-redesign-design.md）：旧子3「验真」拆为
    子3 双向取证 + 子4 质检裁决（5 步 -> 6 步），原子4/5 顺移为子5/6。
    2026-08-14 plan-first 拆步：子2 一拆二（子2a 规划拆解 + 子2b 因果链挖掘），
    全重编号 2..7（6 步 -> 7 步），原子3/4/5/6 顺延为子4/5/6/7。
    """

    def test_gate_rubric_none(self):
        # 子阶段级 rubric 删除（被 sub_steps 逐步门控取代，Q4=删）
        assert eng.get_node("understand", 1).gate_rubric is None

    def test_has_7_sub_steps(self):
        node = eng.get_node("understand", 1)
        assert node.sub_steps is not None
        assert len(node.sub_steps) == 7

    def test_sub_steps_kinds(self):
        node = eng.get_node("understand", 1)
        kinds = [s.kind for s in node.sub_steps]
        assert kinds == ["skill", "skill", "skill", "tool", "tool", "skill", "skill"]

    def test_step2a_step2b_refs_causal_inference(self):
        # 子步骤2a（规划拆解）/子2b（因果链挖掘）invoke causal-inference-root-cause
        node = eng.get_node("understand", 1)
        assert node.sub_steps[1].ref == "causal-inference-root-cause"
        assert node.sub_steps[2].ref == "causal-inference-root-cause"

    def test_last_step_gate_none_autopass(self):
        # 子步骤7（读回确认）gate=None 自动过（trace 存在即过，不跑 judge）
        node = eng.get_node("understand", 1)
        assert node.sub_steps[6].gate is None
        # §substep-gate-at-stop：record=True——Stop 门控以新 trace 为唯一完成触发，
        # record=False 的末步永无触发信号、子阶段卡死（3a 潜在洞）
        assert node.sub_steps[6].record is True

    def test_record_steps(self):
        # 子步骤1-7 全 record=True（子7 记用户确认，作完成触发 + 裁决留痕）
        node = eng.get_node("understand", 1)
        records = [s.record for s in node.sub_steps]
        assert records == [True, True, True, True, True, True, True]

    def test_first_step_no_input(self):
        node = eng.get_node("understand", 1)
        assert node.sub_steps[0].input is None  # 首步无依赖

    def test_step2a_input_refs_step1(self):
        node = eng.get_node("understand", 1)
        assert node.sub_steps[1].input == "step1.real_problem"

    def test_step4_input_refs_step2(self):
        # 双向取证针对子2a 拆出的原子问题清单
        node = eng.get_node("understand", 1)
        assert node.sub_steps[3].input == "step2.problem_list"

    def test_input_chain_after_redesign(self):
        # 2026-07-26 重设计输入链（plan-first 拆步后子5 质检/子6 归一化/子7 读回）：
        # 子5 吃子4 取证记录，子6 归一化陈述只吃子5 处置后问题集（v2.8 收窄，
        # 原 step2+step4），子7 确认吃子6
        node = eng.get_node("understand", 1)
        assert node.sub_steps[4].input == "step4.traces"
        assert node.sub_steps[5].input == "step5.disposed_problem_set"
        assert node.sub_steps[6].input == "step6.statements"

    def test_step4_bidirectional_evidence(self):
        # 子4 双向取证（v2.38 子代理化，designs/step3-fetch-subagent-design.md）：
        # 外部层卸 fetch-prompt 子代理（蒸馏报告原文收录）+ 内部仓库层主会话自查
        # + 禁 tavily/WebSearch/WebFetch（2026-08-01 用户复核维持禁令）
        # v2.40 分档（designs/fetch-depth-tiering-design.md）：标称档来自子2a
        # atomic_questions——none 禁派发 / 禁降档 / 升档留痕 / [tier=X] 归属标记。
        node = eng.get_node("understand", 1)
        s4 = node.sub_steps[3]
        assert s4.kind == "tool"
        for needle in (
            "可检验化",
            "五层源",
            "新鲜度",
            "禁 tavily_search/WebSearch/WebFetch",
            "fetch-prompt",
            "原文收录",
            "禁降档",
            "[tier=X]",
            "建议升档 full",
            "none 档原子禁派发",
        ):
            assert needle in s4.purpose, f"子4 purpose 缺 {needle}"
        for needle in (
            "sub_step==4",
            "反证查询（先）→支持证据（后）分段",
            "训练记忆冒充外部证据",
            "蒸馏报告原文收录",
            "禁降档",
            "建议升档 full",
            "none 档",
        ):
            assert needle in s4.gate, f"子4 gate 缺 {needle}"
        assert "tavily" not in s4.ref

    def test_step5_quality_verdict(self):
        # 子5 质检裁决：三关质检 + 条件触发红队（独立上下文）+ 四态 verdict（证据不足合法）
        node = eng.get_node("understand", 1)
        s5 = node.sub_steps[4]
        assert s5.kind == "tool"
        for needle in ("三关质检", "红队", "独立上下文", "四态", "证据不足"):
            assert needle in s5.purpose, f"子5 purpose 缺 {needle}"
        for needle in ("sub_step==5", "红队触发条件", "推理链"):
            assert needle in s5.gate, f"子5 gate 缺 {needle}"

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
        # 2026-07-27 决议：ProblemContext 末步（子7）过后**不扣留**，直接推进 understand:2
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=7)
        _write_evidence(tmp_path, "t", [_trace_line(7)])
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
        assert steps[0].input == "ProblemContext.step6.statements"  # 跨节点吃子1 输出
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
        assert s5.tier == "confirm"  # P3-1 读回降确认级（2026-08-13 用户裁决）
        assert "静默通过" in s5.purpose and "state-reset" in s5.purpose

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
        assert s5.tier == "confirm"  # P3-1 读回降确认级（2026-08-13 用户裁决）
        assert "静默通过" in s5.purpose and "state-reset" in s5.purpose

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
    """understand:1 子步骤1-6 gate 含 evidence/ -> step_needs_evidence=True；子7 gate=None -> False。"""

    def test_record_steps_need_evidence(self):
        node = eng.get_node("understand", 1)
        # 子1/2a/2b/4/5/6 gate 含 "evidence/" -> True
        for i in range(6):
            assert eng.step_needs_evidence(node.sub_steps[i]) is True

    def test_last_step_no_evidence(self):
        node = eng.get_node("understand", 1)
        # 子7 gate=None -> False
        assert eng.step_needs_evidence(node.sub_steps[6]) is False


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
    tmp_path: Path, phase_dir: str, name: str, content: str | None = None
) -> Path:
    """写阶段产物到规范位置（主仓 .claude/<dir>/<name>.md，§8.3 机械门）。

    默认内容含全部单源节名（ARTIFACT_SECTIONS 并集）——机制类测试（推进/
    block/新鲜度）不关心节内容，CONTAINS 一律过；节行为测试显式传 content。
    """
    if content is None:
        secs = (s for v in eng.ARTIFACT_SECTIONS.values() for s in v)
        content = "# 产物\n\n" + "\n\n".join(f"## {s}" for s in secs) + "\n"
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

        def _spy(
            rubric, label, output, artifact_content=None, prior_verdicts=None, **_
        ):
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

        def _spy(
            rubric, label, output, artifact_content=None, prior_verdicts=None, **_
        ):
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
        # 2026-08-02 升 CONTAINS（artifact-handoff-hardening-design）：四节全查
        assert node.gate_mech == eng.GateMech.ARTIFACT_CONTAINS
        assert node.artifact_contains == (
            "真实问题重述",
            "目标价值",
            "范围约束",
            "成功标准验收包",
        )
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
        # v2.97 framing 反转（u4-sub3-gate-framing-design.md）：「编造」黑盒词撤出，
        # pin 改钉方框一压缩条款（钉死意图不丢，#30 ①）
        for needle in ("sub_step==3", "手段声称存在无工具出处", "事后验证未标注"):
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
        assert s5.tier == "confirm"  # P3-1 读回降确认级（2026-08-13 用户裁决）
        assert "静默通过" in s5.purpose and "state-reset" in s5.purpose

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
        # v2.99 framing 反转（designs/p1-sub1-gate-framing-design.md）：
        # 「编造」黑盒词撤出，pin 改钉方框压缩条款（钉死意图不丢，#30 ①）；
        # 存在性真值归子3 的判材边界须钉死（㉚② 跨阶段变体）。
        for needle in ("sub_step==1", "内部矛盾", "漫游", "判材边界", "归 plan:1 子3"):
            assert needle in s1.gate, f"子1 gate 缺 {needle}"
        assert s1.mech_checks == ("terrain_tool_trace",), (
            "子1 缺 terrain_tool_trace mech（v2.99 留痕投影下沉，design §3）"
        )

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
        assert s3.mech_checks == ("feasibility_verification_trace",), (
            "子3 缺 feasibility_verification_trace mech（v2.103 负判定词形子项下沉，"
            "designs/plan1-sub3-gate-framing-design.md §3）"
        )

    def test_step4_pugh_redteam(self):
        s4 = self._steps()[3]
        assert s4.fence_allow == ("Agent",)  # S15：条件红队
        for needle in ("Pugh", "双向追溯", "条件红队", "只提案不拍板"):
            assert needle in s4.purpose, f"子4 purpose 缺 {needle}"
        for needle in ("sub_step==4", "拍板", "凑结论", "追溯漏项"):
            assert needle in s4.gate, f"子4 gate 缺 {needle}"
        # v2.103 framing 反转（designs/p1-sub4-gate-framing-design.md §3）：
        # 跨项聚合类判定（算术核对/集合差）默认-pass 下 judge 系统性不做
        # （vio3 0-1/6、vio4 1/6），两项下沉零方差生产墙，judge 只留语义侧。
        assert s4.mech_checks == (
            "pugh_traceability_forward_coverage",
            "pugh_net_score_consistency",
        ), "子4 缺跨项聚合 mech（v2.103 算术+集合差下沉，design §3.2）"

    def test_step5_normalization(self):
        s5 = self._steps()[4]
        assert s5.kind == "skill" and s5.ref == "define-problem"
        for needle in ("原子", "去上下文", "改动清单", "验收包映射", "被否方案"):
            assert needle in s5.purpose, f"子5 purpose 缺 {needle}"
        assert "sub_step==5" in s5.gate
        # v2.116 framing 反转：原 pin 钉「不传导」（从严版「设计包字段不传导」
        # 判词）——反转后该判据拆成方框一（字段与子3/子4 已定内容不一致）+
        # 方框四（假设淡化）+ 方框五（ADR 理由传导，已下沉 mech）。改钉三条
        # 精化条款，钉死意图（字段传导judge 侧有判面）不丢（#30 ① 同范式）。
        for needle in (
            "与子3/子4 已定内容不一致",
            "假设淡化",
            "rejected_rationale_trace",
        ):
            assert needle in s5.gate, f"子5 gate 缺字段传导判面「{needle}」"
        assert s5.mech_checks == ("rejected_rationale_trace",), (
            "子5 缺 ADR 理由传导 mech（v2.116 缺席型负判定下沉，design §3）"
        )

    def test_step6_readback_gate_none(self):
        s6 = self._steps()[5]
        assert s6.gate is None  # 交互步，trace 存在即过
        assert s6.record is True
        assert s6.tier == "confirm"  # P3-1 读回降确认级（2026-08-13 用户裁决）
        assert "静默通过" in s6.purpose and "state-reset" in s6.purpose
        # design.md 装配映射归 engine.confirm_artifact pin（test_dl_drive）

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
        # 2026-08-02 升 CONTAINS（artifact-handoff-hardening-design）：本节点装「执行步骤」节
        assert node.gate_mech == eng.GateMech.ARTIFACT_CONTAINS
        assert node.artifact_contains == ("执行步骤",)
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
        for needle in (
            "sub_step==2",
            "默认 pass",
            "横向",
            "违反依赖",
            "覆盖有漏",
            "单阶段无论证",
        ):
            assert needle in s2.gate, f"子2 gate 缺 {needle}"

    def test_step3_anchor_fence(self):
        s3 = self._steps()[2]
        assert s3.fence_allow == ("Bash",)  # S15：锚点本地核验
        # v2.105 framing 反转 + assumption_completeness_trace mech 承托
        assert s3.mech_checks == ("assumption_completeness_trace",)
        for needle in ("测试接缝", "No Placeholders", "三态", "零上下文"):
            assert needle in s3.purpose, f"子3 purpose 缺 {needle}"
        for needle in (
            "sub_step==3",
            "默认 pass",
            "编造",
            "没真核验",
            "placeholder",
            "漏单元核验",
            "assumption_completeness_trace",
        ):
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
        assert s5.tier == "confirm"  # P3-1 读回降确认级（2026-08-13 用户裁决）
        assert "静默通过" in s5.purpose and "state-reset" in s5.purpose

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
    6 步 + hold；2026-08-02 gate_mech 升 ARTIFACT_CONTAINS——
    artifact-handoff-hardening-design）。

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
        # 2026-08-02 升 CONTAINS（artifact-handoff-hardening-design）：本节点装「能力与工具」节
        assert node.gate_mech == eng.GateMech.ARTIFACT_CONTAINS
        assert node.artifact_contains == ("能力与工具",)
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
        # v2.105 gate framing 反转（plan3-sub2-gate-framing-design）：「偷懒」
        # 词形撤出 gate（方框四改用「②无逐任务说明」措辞），pin 改钉压缩条款
        # ——钉死意图（②偷懒出口封堵）不丢。selfcheck 侧「偷懒」禁词守卫见
        # test_selfcheck_no_quality_criteria_leak（未动）。
        for needle in (
            "sub_step==2",
            "幽灵能力",
            "漏配",
            "凭记忆编造",
            "②无逐任务说明",
            "默认 pass",
        ):
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
        # v2.110 gate framing 反转（plan3-sub3-gate-framing-design）：「过载」
        # 词形撤出 gate（方框一改 mech-托声明），pin 改钉压缩条款+framing 标记
        # +mech 注册。钉死意图（五类映射错配出口封堵）不丢。
        assert s3.mech_checks == ("binding_residue_trace",), (
            "子3 无绑定残留须下沉 binding_residue_trace mech"
        )
        for needle in (
            "sub_step==3",
            "默认 pass",
            "无绑定能力残留",
            "绑定理由无出处",
            "强制项被非强制项替代",
            "重型手段",
            "替用户拍板",
        ):
            assert needle in s3.gate, f"子3 gate 缺 {needle}"

    def test_step4_availability_fence(self):
        s4 = self._steps()[3]
        assert s4.fence_allow == ("Bash",)  # S15：可用性本地实测
        # v2.112 framing 反转（plan3-sub4-gate-framing-design）：
        # assumption_completeness_trace 跨节点复用（plan:2 子3 同款，三态形式
        # 契约同构）承托「假设缺置信度或影响」——judge 侧 v1 崩 2/6。
        assert s4.mech_checks == ("assumption_completeness_trace",)
        for needle in ("三态", "MCP", "环境前提", "只标注不裁决"):
            assert needle in s4.purpose, f"子4 purpose 缺 {needle}"
        # pin 改钉（#30 ①/㉔）：「从严裁量」撤出，「假设项缺置信度或影响」的
        # block 面下沉 mech（gate 侧改 mech-托声明）——压缩条款 + framing 标记
        # 「默认 pass」（run_judge 单源读它切 verdict_rule）钉死意图不丢。
        for needle in (
            "sub_step==4",
            "默认 pass",
            "编造",
            "没真核验",
            "漏绑定核验",
            "assumption_completeness_trace",
        ):
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

    def test_step5_normalization_gate_framing(self):
        # v2.117 framing 反转（plan3-sub5-gate-framing-design）：不加载清单丢失 +
        # 假设传导丢失/淡化下沉跨步 mech（出席型负判定，⑭ 注意力方差），gate
        # 方框四/五改 mech-托声明。
        s5 = self._steps()[4]
        assert s5.mech_checks == ("no_load_trace", "assumption_propagation_trace"), (
            "子5 缺跨步 mech（不加载清单丢失 + 假设传导丢失/淡化，v2.117）"
        )
        for needle in (
            "默认 pass",
            "幽灵回潮",
            "逐字对照每个能力名",  # 方框三 needle-in-haystack 检测指令
            "no_load_trace",  # 方框四 mech-托声明
            "assumption_propagation_trace",  # 方框五 mech-托声明
        ):
            assert needle in s5.gate, f"子5 gate 缺 {needle}"
        # 「从严裁量」撤出 gate（pin 改钉压缩条款+framing 标记，#30 ① 同范式）
        assert "从严裁量" not in s5.gate, "子5 gate 残留从严标记"

    def test_step6_readback_gate_none(self):
        s6 = self._steps()[5]
        assert s6.gate is None  # 交互步，trace 存在即过
        assert s6.record is True
        assert s6.tier == "confirm"  # P3-1 读回降确认级（2026-08-13 用户裁决）
        assert "静默通过" in s6.purpose and "state-reset" in s6.purpose

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
        # 2026-08-02 扩为全三节（artifact-handoff-hardening-design）：装配终点
        # + 唯一门栏，查 plan:2/3 节被跨节点删改
        assert node.gate_mech == eng.GateMech.ARTIFACT_CONTAINS
        assert node.artifact_contains == ("执行步骤", "能力与工具", "执行计划与检查点")
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
        # v2.112 framing 反转 + assumption_completeness_trace mech 承托（同 plan:2#3）
        assert s3.mech_checks == ("assumption_completeness_trace",)
        for needle in ("dry-run", "交集", "三态", "只标注不裁决"):
            assert needle in s3.purpose, f"子3 purpose 缺 {needle}"
        for needle in (
            "sub_step==3",
            "默认 pass",
            "实算",
            "没真核验",
            "编造",
            "漏对象核验",
            "assumption_completeness_trace",
        ):
            assert needle in s3.gate, f"子3 gate 缺 {needle}"

    def test_step4_normalization(self):
        s4 = self._steps()[3]
        assert s4.kind == "skill"
        assert "define-problem" in s4.ref
        # v2.119：补 v2.33 迁移漏网第九处——qa 残留致 render-artifact
        # 结构性跳节（只读 statements）、门栏 ARTIFACT_CONTAINS 不可通过
        # （2026-08-06 tail_volume live 全轮首达 plan:4#5 实爆）。
        assert s4.record_format == "statements"
        assert s4.statement_fields == (
            "parallel_group",
            "mutex_surface",
            "worker_map",
            "return_contract",
            "cp_position",
            "cp_criterion",
            "cp_failure_route",
            "cp_type",
            "cp_acceptance_map",
            "cp_goal_anchor",
        )
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
            "statements",
            "fields 十键",
            "cp_criterion",
        ):
            assert needle in s4.purpose, f"子4 purpose 缺 {needle}"
        for needle in (
            "sub_step==4",
            "不一致",
            "复合句",
            "判断词回潮",
            "漏配",
            "record_format=statements",
            "机械校验",
            "提取 statements 每项 text",
        ):
            assert needle in s4.gate, f"子4 gate 缺 {needle}"

    def test_step5_readback_gate_none(self):
        s5 = self._steps()[4]
        assert s5.gate is None  # 交互步，trace 存在即过
        assert s5.record is True
        assert s5.tier == "confirm"  # P3-1 读回降确认级（2026-08-13 用户裁决）
        assert "静默通过" in s5.purpose and "state-reset" in s5.purpose

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
        # §8.3 机械门（ARTIFACT_CONTAINS）：三节已装配
        _write_artifact(
            tmp_path,
            "plans",
            "t",
            "# 执行步骤\n\n## 能力与工具\n\n## 执行计划与检查点\n",
        )
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

    def test_reset_clears_next_prep_stash(self, tmp_path):
        """u2-sub1-cost 修C：回滚作废陈旧 prep 载荷——跨节点 stash 后用户异议
        回退 u:1 重跑场景，旧 need_user.json（key=understand:2#1）不得直达前台。"""
        _write_state_full(tmp_path, "t", "understand", 2, sub_step=1)
        st = eng.load_state(tmp_path, "t")
        st["next_prep_stashed"] = "understand:2#1"
        eng.save_state(tmp_path, "t", st)
        nu = tmp_path / ".claude" / "workflows" / "t" / "need_user.json"
        nu.write_text('{"questions": []}', encoding="utf-8")
        ok, _ = eng.reset_state(tmp_path, "t", "understand:1:6")
        assert ok is True
        assert "next_prep_stashed" not in eng.load_state(tmp_path, "t")
        assert not nu.exists()

    def test_reset_to_bare_open_clears_problem_statement(self, tmp_path):
        # 回滚到 u:1#1（裸开场步）= 问题陈述同步作废（interactive-step-headless-prep
        # §8：陈述在 = step1 走后台 prep，不清则旧陈述污染重跑）；回滚到 #2 保留。
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=3)
        st = eng.load_state(tmp_path, "t")
        st["problem_statement"] = "旧陈述"
        eng.save_state(tmp_path, "t", st)
        ok, _ = eng.reset_state(tmp_path, "t", "2")
        assert ok is True
        assert eng.load_state(tmp_path, "t")["problem_statement"] == "旧陈述"
        ok, _ = eng.reset_state(tmp_path, "t", "1")
        assert ok is True
        assert "problem_statement" not in eng.load_state(tmp_path, "t")

    def test_reset_rejects_node_without_sub_steps(self, tmp_path):
        _write_state_full(tmp_path, "t", "execute", 0)
        ok, msg = eng.reset_state(tmp_path, "t", "2")
        assert ok is False
        assert "无子步骤" in msg

    def test_reset_rejects_out_of_range(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        for bad in ("0", "8"):
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

    def test_judge_prompt_pins_cross_step_anchor(self, monkeypatch):
        # v2.78/2.79（u:1#3 重放实证）：产物=当前步+前序各步最新 trace 拼合
        # （生产常态），judge 曾发明「跨子步串号」要件/把前序当禁看——prompt
        # 钉死 artifact 组成：判对象只是当前步；前序=一致性对照基准（判据
        # 要求一致时必须对照后判）；其存在与组成形式不作 block 依据。
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
        assert "一致性对照基准" in prompt
        assert "必须取前序记录对照后判" in prompt

    def test_judge_prompt_pins_artifact_existence(self, monkeypatch):
        # v2.34 att3 幻觉防线（tail_volume plan:1 子5：engine 是先有 trace hash
        # 才调 judge，judge 却判「缺 trace 记录」——可证伪为假）：prompt 钉死
        # 产物出处=evidence 落库记录，存在性勿再判
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
        assert "记录存在性已由机械层校验" in prompt
        assert "无法证明已写入" in prompt


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

    def test_judge_invocation_disables_thinking(self, monkeypatch):
        # v2.44：judge 子进程 MAX_THINKING_TOKENS=0。MiniMax-M3 实测 thinking
        # 占 judge 输出 92%（3529->278 tok、39.2s->6.3s，同载荷判决方向一致）。
        captured = {}

        class _Res:
            returncode = 0
            stdout = '{"is_error":false,"result":"{\\"pass\\": true, \\"reason\\": \\"\\"}"}\n'

        def _run(cmd, **kw):
            captured["env"] = kw.get("env") or {}
            return _Res()

        monkeypatch.setattr(eng.subprocess, "run", _run)
        eng.run_judge("rubric", "label", "out")
        assert captured["env"].get("MAX_THINKING_TOKENS") == "0"

    def test_judge_invocation_disables_mcp(self, monkeypatch):
        # O1（u1-overall-cost）：judge 本就不调工具（--tools ""），MCP schema
        # （实测 2.5k tok/调用）是纯税——strict-mcp-config + 空表结构封死；
        # 判决载荷仍须是最后一个位置参数（准确性契约不动）。
        captured = self._capture(monkeypatch)
        eng.run_judge("rubric", "label", "out")
        cmd = captured["cmd"]
        assert "--strict-mcp-config" in cmd
        assert cmd[cmd.index("--mcp-config") + 1] == '{"mcpServers":{}}'


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


class TestJudgeFramingDualMode:
    """v2.76 framing 双态同向（designs/judge-framing-dual-mode-design.md）：
    gate 文本的「默认 pass」字面标记=framing 单源——含标记的 gate 配默认放行
    指令行，不含（从严 gate）配严格判定指令行；此前指令行恒为「严格判定」，
    与 v2.71/v2.75 两个默认-PASS gate 直接矛盾（弱 judge 偏向 system 侧）。"""

    def _capture_prompt(self, monkeypatch):
        captured = {}

        def _fake_once(p):
            captured["prompt"] = p
            return True, "", False

        monkeypatch.setattr(eng, "_run_judge_once", _fake_once)
        return captured

    def test_default_pass_gate_gets_soft_line(self, monkeypatch):
        captured = self._capture_prompt(monkeypatch)
        eng.run_judge(
            "判据 X。默认 pass--仅当以下成立才判 block：一、…", "label", "out"
        )
        assert "默认放行" in captured["prompt"]
        assert "严格判定" not in captured["prompt"]
        assert "不得发明判据外要件" in captured["prompt"]

    def test_strict_gate_keeps_strict_line(self, monkeypatch):
        captured = self._capture_prompt(monkeypatch)
        eng.run_judge("质量判据（从严裁量）：证据非编造。", "label", "out")
        assert "严格判定：判据任一条不满足" in captured["prompt"]
        assert "默认放行" not in captured["prompt"]

    def test_default_pass_marker_pinned_in_gates(self):
        # 「默认 pass」字面标记=framing 单源，已反转 gate 必须含标记
        # （删掉标记=静默退回严格判定指令，framing 矛盾复现）
        import dl_flow_nodes as nodes

        s = nodes._NODES["understand:1"].sub_steps
        assert "默认 pass" in s[0].gate, "u:1#1 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in s[1].gate, "u:1#2 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in s[2].gate, "u:1#3 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in s[3].gate, "u:1#4 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in s[4].gate, "u:1#5 gate 缺「默认 pass」framing 标记"
        s2 = nodes._NODES["understand:2"].sub_steps
        assert "默认 pass" in s2[0].gate, "u:2#1 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in s2[1].gate, "u:2#2 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in s2[2].gate, "u:2#3 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in s2[3].gate, "u:2#4 gate 缺「默认 pass」framing 标记"
        s3 = nodes._NODES["understand:3"].sub_steps
        assert "默认 pass" in s3[0].gate, "u:3#1 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in s3[1].gate, "u:3#2 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in s3[2].gate, "u:3#3 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in s3[3].gate, "u:3#4 gate 缺「默认 pass」framing 标记"
        s4 = nodes._NODES["understand:4"].sub_steps
        assert "默认 pass" in s4[0].gate, "u:4#1 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in s4[1].gate, "u:4#2 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in s4[2].gate, "u:4#3 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in s4[3].gate, "u:4#4 gate 缺「默认 pass」framing 标记"
        p1 = nodes._NODES["plan:1"].sub_steps
        assert "默认 pass" in p1[0].gate, "plan:1#1 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in p1[1].gate, "plan:1#2 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in p1[2].gate, "plan:1#3 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in p1[3].gate, "plan:1#4 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in p1[4].gate, "plan:1#5 gate 缺「默认 pass」framing 标记"
        p2 = nodes._NODES["plan:2"].sub_steps
        assert "默认 pass" in p2[0].gate, "plan:2#1 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in p2[1].gate, "plan:2#2 gate 缺「默认 pass」framing 标记"
        # plan:2#3（锚点核验）由并行会话负责反转，p2[2] 标记 pin 留待其落地/收口批补
        assert "默认 pass" in p2[3].gate, "plan:2#4 gate 缺「默认 pass」framing 标记"
        p3 = nodes._NODES["plan:3"].sub_steps
        assert "默认 pass" in p3[0].gate, "plan:3#1 gate 缺「默认 pass」framing 标记"
        p4 = nodes._NODES["plan:4"].sub_steps
        assert "默认 pass" in p4[0].gate, "plan:4#1 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in p4[1].gate, "plan:4#2 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in p4[2].gate, "plan:4#3 gate 缺「默认 pass」framing 标记"
        assert "默认 pass" in p4[3].gate, "plan:4#4 gate 缺「默认 pass」framing 标记"


class TestEmptyBlockReasonRetry:
    """v2.76 block 空判词重试一次：判词消费者是返工模型（v2.36 前提=reason
    是指路），pass=false + reason 空=judge 输出完整性违规，与 bad_verdict_json
    同族——重试时追加「reason 不得为空」提醒，仍空才降级 block。"""

    EMPTY_BLOCK = (
        '{"is_error":false,"usage":{"input_tokens":10,"output_tokens":2},'
        '"result":"{\\"pass\\": false, \\"reason\\": \\"\\"}"}\n'
    )
    GOOD_BLOCK = (
        '{"is_error":false,"usage":{"input_tokens":20,"output_tokens":3},'
        '"result":"{\\"pass\\": false, \\"reason\\": \\"缺条款二\\"}"}\n'
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

    def test_empty_reason_retried_with_reminder(self, monkeypatch):
        calls = self._mock_seq(monkeypatch, [self.EMPTY_BLOCK, self.GOOD_BLOCK])
        ok, reason = eng.run_judge("rubric", "label", "out")
        assert ok is False and reason == "缺条款二"
        assert calls["n"] == 2  # 重试了一次
        assert "reason 不得为空" in calls["prompts"][1]  # 重试带空判词提醒
        m = eng.LAST_JUDGE_META
        assert m.get("judge_retried") == 1
        assert "judge_error" not in m  # 成功路径清掉首次失败标记

    def test_empty_reason_exhausted_degrades(self, monkeypatch):
        calls = self._mock_seq(monkeypatch, [self.EMPTY_BLOCK, self.EMPTY_BLOCK])
        ok, reason = eng.run_judge("rubric", "label", "out")
        assert ok is False
        assert calls["n"] == 2  # 只重试一次
        assert "未写原因" in reason
        assert eng.LAST_JUDGE_META["judge_error"] == "empty_block_reason"


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

    def test_step4_declares_bash_agent(self, tmp_path):
        # v2.38：子4 fence_allow=("Bash","Agent")——内部仓库层 + 取证子代理；
        # WebFetch 环境性弃用移出声明
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=4)
        got = eng.engagement_fence_state(tmp_path, "t")
        assert got is not None
        n, step = got
        assert n == 4
        assert step.fence_allow == ("Bash", "Agent", "TaskOutput")

    def test_step5_declares_agent(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=5)
        got = eng.engagement_fence_state(tmp_path, "t")
        assert got is not None
        assert got[1].fence_allow == ("Agent", "TaskOutput")

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

    def test_step5_notice_declares_agent(self):
        step = eng.sub_step_at(eng.get_node("understand", 1), 5)
        notice = eng.engagement_fence_notice(step)
        assert "额外放行：Agent" in notice

    def test_step4_notice_declares_bash_agent(self):
        step = eng.sub_step_at(eng.get_node("understand", 1), 4)
        notice = eng.engagement_fence_notice(step)
        assert "额外放行：Bash / Agent" in notice

    def test_step5_purpose_guides_redteam_prompt_tools(self):
        # v2.14：红队纪律 a-d 从 purpose 机械化进 redteam_prompt() 模板
        # （demo 121320fe 子代理 104 报错根因链：Glob 不存在(11) + Bash 空拒(21)
        # + 盲猜路径(61 Read 全空)——现场拼 prompt 的事故类，脚本组 prompt 根治）。
        # purpose 只留触发条件 + 调用方式（判断归模型，prompt 内容归脚本）。
        step = eng.sub_step_at(eng.get_node("understand", 1), 5)
        assert "redteam-prompt" in step.purpose  # 生成器调用
        assert "禁止手拼" in step.purpose
        assert "只给证据不给结论" in step.purpose  # 独立上下文契约（gate 判）
        assert "触发条件写死" in step.purpose
        # 披露缺口修复（demo block#5）：「10/10 pass」式汇总声明被判 block——
        # 逐项可验证是形式要件，应披露进 purpose（§3.5 #2）
        assert "逐项可验证" in step.purpose
        assert "汇总声明不算记录" in step.purpose

    def test_step5_redteam_disambiguation_nailed(self):
        # v2.36（2026-08-01 tail_volume_acceleration_annualized 子4 三连 block
        # 复盘，§3.5 #4/#12 裁量点双侧钉死）：judge 把「只给证据不给结论」
        # 裁量到红队**输出**方向，与 redteam_prompt 纪律 4（输出必含四态
        # verdict）自相矛盾——照模板执行必被 block，判据无通过路径。
        # 钉死：输入方向约束（机械保证不重复判）+ 输出含 verdict 合规 +
        # 红队输出须原文收录进子5 trace（提及/转述不算记录）。
        step = eng.sub_step_at(eng.get_node("understand", 1), 5)
        assert "红队**输入**" in step.purpose
        assert "属合规非违规" in step.purpose
        assert "原文收录" in step.purpose
        assert "转述不算记录" in step.selfcheck
        assert "属合规非违规" in step.gate
        assert "不重复判" in step.gate
        assert "未原文收录其输出判 block" in step.gate

    def test_step2b_causal_chain_evidence_rule_nailed(self):
        # v2.36（2026-08-01 tail_volume_acceleration_annualized 子2 两连 block
        # 复盘，§3.5 #9 第三形态=操作化分歧）：模型主链每环标【evidence：未实测】
        # 并答自查「是」——把取证状态标注当合法出处；且被 engage 围栏 deny 一次
        # Bash 后错误泛化为「本步禁取证」（.wf_fence.log 实锤）。判型=操作化
        # 分歧非注意力失败（trace 里该项自查真被执行过）——钉操作化定义双侧：
        # 主链每环实际证据指针 + 「未实测」只允许竞争假设分支 + Read 合法通道。
        # v2.72（2026-08-04 framing 反转）：_CAUSAL_CHAIN_EVIDENCE_RULE 撤出
        # gate（长度是弱 judge 独立变量，基线 clean 0/6 误伤的弹药文本），
        # 模型侧 purpose/selfcheck verbatim 不变；judge 侧改钉压缩判据——
        # 方框一（编造/虚构指针）+ 合法正例（原话=合法环指针）+ 方框三
        # （稻草人）；「未实测不算出处」由 causal_ring_no_untested 机械层
        # 当场拒（比 judge 裁量更硬）。
        # plan-first 拆步（2026-08-14）：因果链证据规则随挖链归子2b（原子2 方框一/二/三）。
        step = eng.sub_step_at(eng.get_node("understand", 1), 3)
        for frag in ("实际证据指针", "不算证据出处", "竞争假设"):
            assert frag in step.purpose, f"purpose 缺「{frag}」（模型侧未钉死）"
            assert frag in step.selfcheck
        assert "模型虚构" in step.gate, "gate 方框一缺编造判据"
        assert "合法环证据指针" in step.gate, "gate 缺原话合法正例"
        assert "竞争假设非稻草人" in step.gate
        assert "causal_ring_no_untested" in step.mech_checks

    def test_step_selfcheck_hint_single_source(self):
        # §step-selfcheck：自查提示单源常量（pass 续轮/block 返工/注入三通道共用）
        assert "STEP_DONE 前自查" in eng.STEP_SELFCHECK_HINT
        assert "汇总声明不算" in eng.STEP_SELFCHECK_HINT

    def test_step3_forbids_credential_exploration(self, tmp_path):
        # demo 121320fe：GitHub API 401 后模型扫 env 找 token 被安全分类器拦
        # （Credential Exploration）——红线 preempt。v2.38 起外部调用全在取证
        # 子代理进程，规则落点随 actor 移到 fetch-prompt 纪律（主会话不再直连外部源）
        rec = json.dumps(
            {
                "kind": "skill-trace",
                "major_stage": "Understand",
                "minor_stage": "ProblemContext",
                "sub_step": 2,
                "skill": "s",
                "purpose": "p",
                "q": ["q"],
                "a": ["原子A"],
            },
            ensure_ascii=False,
        )
        _write_evidence(tmp_path, "t", [rec])
        prompt = eng.fetch_prompt(tmp_path, "t")
        assert "禁止探查凭证" in prompt
        assert "未取证+未认证" in prompt


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
        node = eng.get_node("understand", 4)  # ARTIFACT_CONTAINS
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
        node = eng.get_node("understand", 4)  # ARTIFACT_CONTAINS -> understands/t.md
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
        # 2026-08-02 起 plan:4 查全三节：两节同缺，文案都点名
        assert "能力与工具" in reason
        assert "执行计划与检查点" in reason

    def test_contains_passes(self, tmp_path):
        _write_artifact(
            tmp_path,
            "plans",
            "t",
            "# 执行步骤\nfoo\n## 能力与工具\nx\n## 执行计划与检查点\nbar\n",
        )
        node = eng.get_node("plan", 4)
        assert eng.gate_verdict_mech(node, project_root=tmp_path, name="t") is None

    # ---- 2026-08-02 CONTAINS 扩面（artifact-handoff-hardening-design）----

    def test_u4_contains_missing_section_blocks(self, tmp_path):
        # understand.md 缺「成功标准验收包」节 -> block 且点名缺节
        _write_artifact(
            tmp_path,
            "understands",
            "t",
            "# 真实问题重述\na\n## 目标价值\nb\n## 范围约束\nc\n",
        )
        node = eng.get_node("understand", 4)
        reason = eng.gate_verdict_mech(node, project_root=tmp_path, name="t")
        assert reason is not None
        assert "缺节" in reason
        assert "成功标准验收包" in reason

    def test_u4_contains_passes(self, tmp_path):
        _write_artifact(
            tmp_path,
            "understands",
            "t",
            "# 真实问题重述\na\n## 目标价值\nb\n## 范围约束\nc\n## 成功标准验收包\nd\n",
        )
        node = eng.get_node("understand", 4)
        assert eng.gate_verdict_mech(node, project_root=tmp_path, name="t") is None

    def test_review_contains_missing_section_blocks(self, tmp_path):
        _write_artifact(tmp_path, "reviews", "t", "# 结论\nsolved\n")
        node = eng.get_node("review", 0)
        reason = eng.gate_verdict_mech(node, project_root=tmp_path, name="t")
        assert reason is not None
        assert "缺节" in reason
        assert "证据" in reason

    def test_evolution_contains_passes(self, tmp_path):
        _write_artifact(tmp_path, "evolutions", "t", "# 经验\na\n## 落地\nb\n")
        node = eng.get_node("evolution", 0)
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
    def test_prior_verdicts_quote_requirement_in_prompt(self, monkeypatch):
        # v2.52 抗「已修还判」：prior_verdicts 非空时 prompt 钉「判 block 引用
        # 的违规内容须是本轮产物原文短语，引不出不得作依据」——8/2 晚 u:1 子1
        # att2 judge 照前轮判词描述 block 已修问题（payload 里根本没有该字面）
        captured = {}

        def _fake(cmd, **kw):
            captured["prompt"] = cmd[-1]
            import types

            r = types.SimpleNamespace()
            r.returncode = 0
            r.stdout = _result_line('{"pass": true}')
            r.stderr = ""
            return r

        monkeypatch.setattr(eng.subprocess, "run", _fake)
        eng.run_judge("rubric", "节点", "输出", prior_verdicts=["上轮缺 X"])
        assert "原文" in captured["prompt"] and "本轮" in captured["prompt"]

    def test_mech_scope_pinned_in_prompt(self, monkeypatch):
        # v2.52：mech_scope 非空时 prompt 钉「写侧机械校验已过，形式要件勿
        # 重复判」（v2.34 存在性钉死同范式——rubric 内嵌句被 prior_verdicts
        # 压制过一轮，提为独立钉句）
        captured = {}

        def _fake(cmd, **kw):
            captured["prompt"] = cmd[-1]
            import types

            r = types.SimpleNamespace()
            r.returncode = 0
            r.stdout = _result_line('{"pass": true}')
            r.stderr = ""
            return r

        monkeypatch.setattr(eng.subprocess, "run", _fake)
        eng.run_judge("rubric", "节点", "输出", mech_scope="user_quote_channel")
        assert (
            "机械校验" in captured["prompt"]
            and "user_quote_channel" in captured["prompt"]
        )
        # 重放逮住初版过度抑制（scope 含「结论前缀」被 judge 泛化成
        # 「结论全免判」，结论推断被放过）——钉句双侧：非枚举项照判不误
        assert "照判" in captured["prompt"]

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
        # §8.3：hook 传 name + project_root 后 review:0 的机械门真实生效——
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

    def test_meta_includes_settings_template_version(self, capsys):
        # v2.35 防静默权限税（症状 R）：版本戳单源在 engine，dl-lib.sh 盖章、
        # workflow_phase 比对都经 meta/常量取——改模板只 bump 一处。
        rc = eng.main(["meta"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["settings_template_version"] == eng.SETTINGS_TEMPLATE_VERSION >= 1
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

        def _spy(
            rubric, label, output, artifact_content=None, prior_verdicts=None, **_
        ):
            captured["artifact"] = artifact_content
            return (True, "")

        monkeypatch.setattr(eng, "run_judge", _spy)
        action, _, _ = eng.gate_sub_step_at_stop(tmp_path, "t", str(tmp_path))
        assert action == "advanced"
        art = captured["artifact"]
        assert "a-new" in art and "a-old" not in art


class TestStep3FalsificationOrderDisclosure:
    """子4 purpose 披露反证时序留痕形式要件（2026-07-26，demo fbdb6ebd 子3 实录：
    模型执行了反证但留痕看不出先后被判 block；形式要件进 purpose 降形式性返工，
    §3.5 #2——质量判据仍只在 gate 黑盒）。plan-first 拆步后旧子3 顺延为子4。"""

    def test_step4_purpose_discloses_order_requirement(self):
        # v2.38：时序要求经子代理返回契约结构保证，purpose 披露该机制
        node = eng.get_node("understand", 1)
        step4 = eng.sub_step_at(node, 4)
        assert "反证先/支持后" in step4.purpose
        assert "时序" in step4.purpose


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
        recs = [
            json.loads(line) for line in ev.read_text(encoding="utf-8").splitlines()
        ]
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
            ("understand", 1, 6),
            ("understand", 2, 4),
            ("understand", 3, 4),
            ("understand", 4, 4),
        ):
            stp = eng.get_node(phase, sub).sub_steps[step_no - 1]
            assert stp.record_format == "statements", f"{phase}:{sub} 子{step_no}"
        # v2.36：understand:1 子6（旧子5，plan-first 拆步后顺延）是 v2.33
        # 迁移漏网（当时只迁 plan 三步，而 understand:2/3/4 在 v2.27 已迁）——
        # qa 格式导致方案名词机械扫描空转（tail_volume_acceleration_annualized
        # 子5 实测：陈述1/2 含 _section_backtest.html/layered_backtest.py 连过
        # 通过轮都未被拦）。
        st6 = eng.get_node("understand", 1).sub_steps[5]
        assert st6.statement_fields == ("confidence",)
        assert "机械扫描" in st6.purpose
        assert "未挪 boundary" in st6.gate

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

    # v2.23 同构族原 5 步：understand:2 子2/子4、understand:3 子4、understand:4 子1/子4。
    # v2.88 起 u:2 子4、v2.92 起 u:3 子4、v2.93 起 u:4 子1、v2.97 起 u:4 子4 撤出逐字引用族
    # （见 test_u2_sub4_refined_rule_pin / test_u3_sub4_refined_rule_pin /
    # test_u4_sub1_refined_rule_pin / test_u4_sub4_refined_rule_pin）：逐字规则列
    # 「管线名/字段名」为禁用与各节点「口径限定词合法」直接矛盾（#23 修文本不站队，
    # designs/u4-sub1-gate-framing-design.md §1.1 聚类 1）。
    _FIVE_STEPS = [
        ("understand", 2, 2),
    ]

    def test_subject_rule_cited_in_all_five_gates(self):
        for phase, sub, step_no in self._FIVE_STEPS:
            gate = eng.get_node(phase, sub).sub_steps[step_no - 1].gate
            assert gate, f"{phase}:{sub} 子{step_no} 无 gate"
            assert "主语只许 outcome-level" in gate, (
                f"{phase}:{sub} 子{step_no} gate 未引用 _SOLUTION_FREE_SUBJECT_RULE"
                "（judge 侧裁量点未钉死）"
            )

    def test_u2_sub4_refined_rule_pin(self):
        # v2.88：u:2 子4 judge 侧裁量点钉死改用精化版（方框四）——钉死意图不丢，
        # 禁回潮成黑盒判词「含方案名词判 block」
        gate = eng.get_node("understand", 2).sub_steps[3].gate
        assert "方案动作残留" in gate and "实现机制名词" in gate, (
            "u:2 子4 gate 方框四精化钉死缺失（judge 侧裁量点回潮黑盒）"
        )
        assert "数据口径限定词" in gate, (
            "u:2 子4 gate 方框四缺口径限定词合法形态（#23 矛盾复现：管线名误伤族）"
        )

    def test_u3_sub4_refined_rule_pin(self):
        # v2.92：u:3 子4 judge 侧裁量点钉死改用精化版（方框四）——钉死意图不丢，
        # 禁回潮成黑盒判词「含方案名词判 block」
        gate = eng.get_node("understand", 3).sub_steps[3].gate
        assert "方案动作残留" in gate and "实现机制名词" in gate, (
            "u:3 子4 gate 方框四精化钉死缺失（judge 侧裁量点回潮黑盒）"
        )
        assert "数据口径限定词" in gate, (
            "u:3 子4 gate 方框四缺口径限定词合法形态（#23 矛盾复现：管线名误伤族）"
        )
        assert "不得因 boundary 有任何实现细节而判 block" in gate, (
            "u:3 子4 gate 方框四缺 boundary 硬排除（boundary 实现指针误伤族）"
        )

    def test_u4_sub1_refined_rule_pin(self):
        # v2.93：u:4 子1 judge 侧裁量点钉死改用精化版（方框四）——钉死意图不丢，
        # 禁回潮成黑盒判词「含方案名词判 block」。基线 clean 6/6 全轮主引
        # 「default 管线=实现侧名词」误伤（designs/u4-sub1-gate-framing-design.md
        # §1.1 聚类 1）：逐字规则列「管线名/字段名」为禁用，与 must 目标自带的
        # 已确认口径限定词必然入候选主语直接矛盾。
        gate = eng.get_node("understand", 4).sub_steps[0].gate
        assert "solutioneering 残留" in gate and "项目源码构件标识" in gate, (
            "u:4 子1 gate 方框四精化钉死缺失（judge 侧裁量点回潮黑盒）"
        )
        assert "数据口径限定词与交付载体不是实现侧名词" in gate, (
            "u:4 子1 gate 方框四缺口径限定词合法形态（#23 矛盾复现：管线名误伤族）"
        )
        assert "指向项目源码里的某个构件" in gate, (
            "u:4 子1 gate 方框四缺判别线（源码构件 vs 用户可见口径）"
        )

    def test_u4_sub4_refined_rule_pin(self):
        # v2.97：u:4 子4 judge 侧裁量点钉死改用精化版（方框四）--钉死意图不丢，
        # 禁回潮成黑盒判词「含方案名词判 block」。基线 clean 6/6 全轮主引
        # 「default 管线/报告/因子明细=实现侧名词」「打开/读出=实现动词」误伤
        # （designs/u4-sub4-gate-framing-design.md §1.1 聚类 1/4）：逐字规则列
        # 「管线名/字段名」为禁用与 must 目标自带口径限定词必然入 text 矛盾。
        gate = eng.get_node("understand", 4).sub_steps[3].gate
        assert "方案动作残留" in gate and "项目源码构件标识" in gate, (
            "u:4 子4 gate 方框四精化钉死缺失（judge 侧裁量点回潮黑盒）"
        )
        assert "验收事件描述性动词" in gate, (
            "u:4 子4 gate 方框四缺验收事件动词合法形态（验收行为 vs 代码实现动作误伤族）"
        )
        assert "不得因 boundary 有任何实现细节而判 block" in gate, (
            "u:4 子4 gate 方框四缺 boundary 硬排除（boundary 实现指针误伤族）"
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


class TestPainObservabilityRule:
    """v2.64 痛点可观察性裁量点钉死双侧化（2026-08-03
    tail_volume_acceleration_annualized u:1 子1 两连 block 复盘）：
    att2 痛点已含用户确认的可观察后果，judge 发明「每条列举后果都须可观察」
    要件按前轮判词描述 block——混合后果处理规则从未写进判据文本（§3.5 #4
    裁量留白=方差 + #23 判词与规则文本矛盾修文本）。_PAIN_OBSERVABILITY_RULE
    单源，purpose/selfcheck（模型侧，含正面退路）与 gate（judge 侧）双侧
    引用不回归。"""

    def test_rule_cited_in_gate(self):
        gate = eng.get_node("understand", 1).sub_steps[0].gate
        assert gate, "understand:1 子1 无 gate"
        assert "痛点可观察性按主痛点判" in gate, (
            "gate 未引用 _PAIN_OBSERVABILITY_RULE（judge 侧裁量点未钉死）"
        )
        # 牙齿不丢：纯认知痛点仍须 block
        assert "只有认知判断/信任陈述" in gate

    def test_rule_disclosed_to_model(self):
        step = eng.get_node("understand", 1).sub_steps[0]
        assert "痛点可观察性按主痛点判" in step.purpose
        # 正面退路披露（§3.5 #16：禁 prohibition-only）
        assert "模型侧退路" in step.purpose
        assert "可观察后果作本体" in step.selfcheck


class TestWhoSelectedRoleRule:
    """v2.70 who「选中角色选项算不算自述身份」接口钉死双侧化
    （2026-08-03 tail_volume_acceleration_annualized u:1 子1 att2 复盘）：
    who 写法（「因子池/项目维护者（AskUserQuestion 选中）」）与 att1 逐字
    相同、att1 未判 who，att2 judge 却发明「选中选项只能证明行为/会话事实，
    不能证明提问者身份」要件--轮间「放过又判」（§3.5 #14）+ 发明要件
    （§3.5 #23），且按该判词 who 只剩打字自述一条路（用户全程只点选项=
    无合法获取路径，§3.5 #7）。「选中角色选项算 who 自述」的接口两条规则
    都未写死=裁量留白（§3.5 #4）。_USER_QUOTE_FORMS_RULE 单源扩面，
    purpose/selfcheck（模型侧）与 gate（judge 侧）双侧引用不回归。"""

    def test_rule_cited_in_gate(self):
        gate = eng.get_node("understand", 1).sub_steps[0].gate
        assert gate, "understand:1 子1 无 gate"
        # v2.71：who 出处合法性下沉 mech（who_no_repo_fact），gate 不再判 who
        # 出处类别--改查 mech_checks 注册 + purpose 仍含角色选项接口
        step = eng.get_node("understand", 1).sub_steps[0]
        assert "who_no_repo_fact" in step.mech_checks, (
            "who 出处合法性未下沉机械层（v2.71 framing 收口：gate 不判 who 出处）"
        )
        assert "角色类选项" in step.purpose, (
            "purpose 未钉死 who 选中角色选项=自述（模型侧裁量点未钉死）"
        )
        # 牙齿不丢：仓库事实冒充身份仍须拦（mech 层）
        assert "仓库事实" in step.purpose

    def test_rule_disclosed_to_model(self):
        step = eng.get_node("understand", 1).sub_steps[0]
        assert "角色类选项" in step.purpose, (
            "purpose 未披露 who 选中角色选项=自述（模型侧裁量点未钉死）"
        )

    def test_method_guidance_names_selected_role(self):
        # _STEP1_METHOD_GUIDANCE 同步点名（防「只认自述」被读成「只认打字」）
        import dl_flow_nodes as nodes

        assert "选中角色类选项同为自述" in nodes._STEP1_METHOD_GUIDANCE


class TestWhoNoRepoFact:
    """v2.71 who 仓库事实冒充身份下沉机械层（2026-08-03 judge 误伤根治）：
    6 变体重放实证 judge 对 who 项最高频误判之一=把「AskUserQuestion 选中
    角色选项」当「仓库事实冒充身份」。who 出处合法性属形式要件（关键词可判），
    下沉 _check_who_no_repo_fact=append-trace 当场拒，judge 不再判 who 出处
    （§3.5 #13 词形判据下沉机械层 + #17 形式要件机械化）。"""

    def test_registered_and_declared(self):
        assert "who_no_repo_fact" in eng._MECH_QA_CHECKS, (
            "who_no_repo_fact 未注册 _MECH_QA_CHECKS（engine/nodes 漂移）"
        )
        step = eng.get_node("understand", 1).sub_steps[0]
        assert "who_no_repo_fact" in step.mech_checks

    def test_repo_fact_blocked(self):
        fn = eng._MECH_QA_CHECKS["who_no_repo_fact"]
        # CLAUDE.md 冒充身份出处 -> 拒
        for bad in (
            "项目维护者（CLAUDE.md §6 声明唯一维护者）",
            "维护者（git config user.name=张三）",
            "开发者（分支命名 feat/codegraph 暗示）",
        ):
            err = fn([{"q": "who: 你的角色？", "a": bad}])
            assert err and "仓库事实" in err, f"应拦仓库事实冒充：{bad}"

    def test_selected_role_not_blocked(self):
        fn = eng._MECH_QA_CHECKS["who_no_repo_fact"]
        # 选中角色选项 / 未自述标注 -> 不拦（宁纵勿枉）
        for ok in (
            "因子池/项目维护者（AskUserQuestion 选中）。",
            "未自述身份（who=未自述）。",
            "用户未自述身份（会话事实）。",
        ):
            assert fn([{"q": "who: 你的角色？", "a": ok}]) is None, (
                f"不应拦合法 who 形态：{ok}"
            )

    def test_non_who_item_not_scanned(self):
        fn = eng._MECH_QA_CHECKS["who_no_repo_fact"]
        # 非 who 项含 CLAUDE.md（如痛点项引用项目事实）-> 不拦
        assert fn([{"q": "pain: 后果？", "a": "T+1 持仓（CLAUDE.md 声明）"}]) is None


class TestHypothesisExcludeNoAbsence:
    """v2.75 竞争假设排除理由缺席断言下沉机械层（2026-08-04 u:1 子2 vio2 根治）：
    v2.73/v2.74 重放实证 judge 对「排除理由无证据指针」双向抖动（v2.73 把
    「用户没有表达过这个意思」当留痕放过 vio2 牙齿掉 4/6；v2.74 钉死后反伤
    clean 1/6）。缺席断言词形可判，下沉机械层零方差（§3.5 #13）。"""

    def test_registered_and_declared(self):
        assert "hypothesis_exclude_no_absence" in eng._MECH_QA_CHECKS, (
            "hypothesis_exclude_no_absence 未注册 _MECH_QA_CHECKS（engine/nodes 漂移）"
        )
        step = eng.get_node("understand", 1).sub_steps[2]
        assert "hypothesis_exclude_no_absence" in step.mech_checks

    def test_absence_assertion_blocked(self):
        fn = eng._MECH_QA_CHECKS["hypothesis_exclude_no_absence"]
        # vio2 真实载荷逐字 -> 拒
        for bad in (
            "H1=用户其实想删除整个因子池。排除理由：用户没有表达过这个意思，故排除 H1。",
            "排除 H2：用户没说过要保留旧流程。",
            "该假设排除，因用户未提及其他筛选维度。",
        ):
            err = fn([{"q": "竞争假设？", "a": bad}])
            assert err and "缺席断言" in err, f"应拦缺席断言排除：{bad}"

    def test_specific_record_not_blocked(self):
        fn = eng._MECH_QA_CHECKS["hypothesis_exclude_no_absence"]
        # 具体选择记录/原话引用 -> 不拦（宁纵勿枉）
        for ok in (
            "用户未选择「只想了解规模」和「数量并不帮助」，而选择「没有缩减规则」与「决定筛选门槛」（AskUserQuestion 选中留痕），故当前排除 H1。",
            "排除 H1：用户原话「继续筛选」直接否定该假设（第3轮原话）。",
            "H1 标保留/待子3取证：证据不足不排除。",
        ):
            assert fn([{"q": "竞争假设？", "a": ok}]) is None, (
                f"不应拦合法排除形态：{ok}"
            )


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


class TestStatementFieldsMigration:
    """v2.33 三归一化步迁 statements+statement_fields
    （designs/plan-normalization-statements-migration-design.md）：
    plan:1 子5 / plan:2 子4 / plan:3 子5——字段齐备从 judge 判词变
    JSON 校验；text 只留单句，实现指针进 fields/boundary。"""

    _MIGRATED = [
        (
            "plan",
            1,
            5,
            (
                "change_list",
                "interface_sig",
                "data_contract",
                "callers",
                "rejected",
                "assumptions",
                "acceptance_map",
                "h9_units",
            ),
        ),
        (
            "plan",
            2,
            4,
            ("change_point", "interface", "verify", "acceptance_map", "trace_anchor"),
        ),
        (
            "plan",
            3,
            5,
            ("skill_first", "tools", "enforce_align", "subagent_policy", "no_load"),
        ),
    ]

    def _setup(self, tmp_path, phase, sub, step_no):
        _write_state_full(tmp_path, "t", phase, sub, sub_step=step_no)
        return tmp_path / "payload.json"

    def _payload(self, fields):
        item = {
            "text": "在因子卡片渲染层内部取消二次放大",
            "type_label": "推荐",
            "boundary": "边界：仅指当前产物渲染链路",
        }
        if fields is not None:
            item["fields"] = fields
        return {"purpose": "p", "statements": [item]}

    def _full_fields(self, keys):
        return {k: f"{k} 内容" for k in keys}

    def test_three_steps_declare_statements_and_fields(self):
        for phase, sub, step_no, keys in self._MIGRATED:
            stp = eng.get_node(phase, sub).sub_steps[step_no - 1]
            assert stp.record_format == "statements", f"{phase}:{sub} 子{step_no}"
            assert stp.statement_fields == keys, f"{phase}:{sub} 子{step_no}"

    def test_missing_fields_object_rejected(self, tmp_path):
        payload = self._setup(tmp_path, "plan", 1, 5)
        (tmp_path / "payload.json").write_text(
            json.dumps(self._payload(None), ensure_ascii=False), encoding="utf-8"
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert not ok and "fields" in msg and "change_list" in msg

    def test_missing_single_key_rejected_and_named(self, tmp_path):
        payload = self._setup(tmp_path, "plan", 1, 5)
        fields = self._full_fields(self._MIGRATED[0][3])
        del fields["h9_units"]
        (tmp_path / "payload.json").write_text(
            json.dumps(self._payload(fields), ensure_ascii=False), encoding="utf-8"
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert not ok and "h9_units" in msg

    def test_empty_field_value_rejected(self, tmp_path):
        payload = self._setup(tmp_path, "plan", 2, 4)
        fields = self._full_fields(self._MIGRATED[1][3])
        fields["verify"] = "  "
        (tmp_path / "payload.json").write_text(
            json.dumps(self._payload(fields), ensure_ascii=False), encoding="utf-8"
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert not ok and "verify" in msg

    def test_happy_path_all_keys_accepted(self, tmp_path):
        payload = self._setup(tmp_path, "plan", 1, 5)
        (tmp_path / "payload.json").write_text(
            json.dumps(
                self._payload(self._full_fields(self._MIGRATED[0][3])),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert ok, msg
        rec = json.loads(
            (tmp_path / ".claude" / "evidence" / "t.jsonl")
            .read_text(encoding="utf-8")
            .strip()
        )
        assert rec["statements"][0]["fields"]["h9_units"]

    def test_id_re_extended_patterns(self):
        text = "RC-A 红队 T1 目标 SC4.1 标准 #1a 候选 #1b1 拆分 U3 任务 H1.1 规则"
        found = set(eng._ID_RE.findall(text))
        for want in ("RC-A", "T1", "SC4.1", "#1a", "#1b1", "U3", "H1.1"):
            assert want in found, f"_ID_RE 未捕获 {want}"

    def test_replay_att1_noun_in_text_blocked(self, tmp_path):
        # 重放 tail_volume plan:1 子5 att1 形态：实现指针塞 text（原 qa 自由文本
        # judge 判，现 statements 机械拦）——att1 第一轮 judge 不再发生
        import subprocess as sp

        _write_state_full(tmp_path, "t", "plan", 1, sub_step=5)
        sp.run(["git", "init"], cwd=tmp_path, capture_output=True)
        f = tmp_path / "web_ui" / "templates" / "_macros.html"
        f.parent.mkdir(parents=True)
        f.write_text("x", encoding="utf-8")
        sp.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        item = {
            "text": "在 _macros.html 的渲染层内部取消二次放大",
            "type_label": "推荐",
            "boundary": "无",
            "fields": self._full_fields(self._MIGRATED[0][3]),
        }
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "statements": [item]}, ensure_ascii=False),
            encoding="utf-8",
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "_macros.html" in msg and "boundary" in msg

    def test_replay_att2_legal_shape_passes(self, tmp_path):
        # 重放 att2 形态（v2.32 已判合法）：text 单句决策 + fields 键值枚举携带
        # ——字段枚举不触发复合句判定，append 直接通过
        _write_state_full(tmp_path, "t", "plan", 1, sub_step=5)
        item = {
            "text": "在因子卡片渲染层内部取消二次放大",
            "type_label": "推荐",
            "boundary": "边界：仅指当前产物渲染链路",
            "fields": {
                "change_list": "1 处内部计算式（改/增/删=改）",
                "interface_sig": "现有宏签名不变",
                "data_contract": "caller 传入与现状一致",
                "callers": "被 6 处 import 引用的因子卡片宏 + 4 模板 8 处散落点另列",
                "rejected": "候选 2（Pugh 净分劣） + 候选 3（H1.1 证伪）",
                "assumptions": "1 条（置信度中）",
                "acceptance_map": "T1+T2 修复，T3 另列任务项",
                "h9_units": "1 阶段 1 文件",
            },
        }
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "statements": [item]}, ensure_ascii=False),
            encoding="utf-8",
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert ok, msg

    def test_id_conduction_scans_fields_values(self, tmp_path):
        # 源步 ID 可经 fields 值传导（八字段含 ID 是常态）
        _write_state_full(tmp_path, "t", "plan", 1, sub_step=5)
        ev = eng._evidence_path(tmp_path, "t")
        ev.parent.mkdir(parents=True, exist_ok=True)
        src = json.dumps(
            {
                "kind": "skill-trace",
                "major_stage": "Plan",
                "minor_stage": "DesignSolution",
                "sub_step": 4,
                "skill": "define-problem",
                "purpose": "Pugh 评估",
                "q": ["矩阵？"],
                "a": ["#1a 净分优 #1b 净分劣 #1c 被 H1.1 剔除"],
            },
            ensure_ascii=False,
        )
        ev.write_text(src + "\n", encoding="utf-8")
        fields = self._full_fields(self._MIGRATED[0][3])
        fields["rejected"] = "#1b 净分劣 + #1c 被 H1.1 剔除"  # #1b/#1c 经 fields 传导
        item = {
            "text": "#1a 在因子卡片渲染层内部取消二次放大",
            "type_label": "推荐",
            "boundary": "边界：仅指当前产物渲染链路",
            "fields": fields,
        }
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "statements": [item]}, ensure_ascii=False),
            encoding="utf-8",
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert ok, msg
        # 对照：删掉 fields 里的 #1b -> 缺传被拒并点名
        fields["rejected"] = "#1c 被 H1.1 剔除"
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "statements": [item]}, ensure_ascii=False),
            encoding="utf-8",
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "#1b" in msg


class TestPlan4Sub4StatementsMigration:
    """v2.119 plan:4#4 归一化计划包迁 statements+statement_fields 十键
    （designs/plan4-sub4-statements-migration-design.md）——v2.33 迁移漏网
    第九处补齐：qa 残留致 render-artifact 结构性跳节（只读 statements）、
    门栏 ARTIFACT_CONTAINS 不可通过（2026-08-06 tail_volume live 全轮首达
    plan:4#5 实爆）。"""

    _KEYS = (
        "parallel_group",
        "mutex_surface",
        "worker_map",
        "return_contract",
        "cp_position",
        "cp_criterion",
        "cp_failure_route",
        "cp_type",
        "cp_acceptance_map",
        "cp_goal_anchor",
    )

    def _payload(self, items):
        return {"purpose": "归一化", "statements": items}

    def _schedule_item(self, fields):
        return {
            "text": "W1 与 W2 并行承接 T1/T2，组内互斥面交集为空",
            "type_label": "调度",
            "boundary": "假设传导：子3 无假设项需传导",
            "fields": fields,
        }

    def _full_fields(self):
        return {
            "parallel_group": "DAG 层1：T1/T2 并行",
            "mutex_surface": "交集=∅（子3 已实算）",
            "worker_map": "W1->T1，W2->T2",
            "return_contract": "pytest 输出+commit hash",
            "cp_position": "T1 提交后",
            "cp_criterion": "pytest tests/test_x.py -x 退出码 0",
            "cp_failure_route": "回滚重试",
            "cp_type": "自动",
            "cp_acceptance_map": "SC1（追溯锚 T1）",
            "cp_goal_anchor": "原目标：X；当前位置：T1 完成待验证",
        }

    def test_missing_single_key_rejected_and_named(self, tmp_path):
        _write_state_full(tmp_path, "t", "plan", 4, sub_step=4)
        fields = self._full_fields()
        del fields["cp_goal_anchor"]
        (tmp_path / "payload.json").write_text(
            json.dumps(self._payload([self._schedule_item(fields)])),
            encoding="utf-8",
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "cp_goal_anchor" in msg

    def test_schedule_item_with_none_cp_keys_accepted(self, tmp_path):
        # 调度项 cp_* 六键填显式「无」= 合法形态（plan:3#5「无内容键填
        # 显式『无』」同规）——十键逐键非空机械校验不为难类型化条目
        _write_state_full(tmp_path, "t", "plan", 4, sub_step=4)
        fields = self._full_fields()
        for k in self._KEYS[4:]:
            fields[k] = "无"
        (tmp_path / "payload.json").write_text(
            json.dumps(self._payload([self._schedule_item(fields)])),
            encoding="utf-8",
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert ok, msg
        rec = json.loads(
            (tmp_path / ".claude" / "evidence" / "t.jsonl")
            .read_text(encoding="utf-8")
            .strip()
        )
        assert rec["minor_stage"] == "ExecutionPlanCheckpoints"
        assert rec["statements"][0]["fields"]["worker_map"] == "W1->T1，W2->T2"

    def test_checkpoint_item_with_none_schedule_keys_accepted(self, tmp_path):
        _write_state_full(tmp_path, "t", "plan", 4, sub_step=4)
        fields = self._full_fields()
        for k in self._KEYS[:4]:
            fields[k] = "无"
        item = {
            "text": "CP1 在 T1 提交后自动核验分类维度汇总断言",
            "type_label": "检查点",
            "boundary": "出处：子2 调度提案",
            "fields": fields,
        }
        (tmp_path / "payload.json").write_text(
            json.dumps(self._payload([item])), encoding="utf-8"
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert ok, msg


class TestAppendTrace:
    """v2.14 append-trace（「AI 定写什么，脚本定怎么写」A 级）：
    载荷 purpose/q/a + state 结构字段 -> 校验 -> 单行 append。fail loud 即时暴露。"""

    def _setup(self, tmp_path, sub_step=5):
        # plan-first 拆步后质检裁决顺延为子5（plain qa 可过的步作通用测试底）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=sub_step)
        payload = tmp_path / "payload.json"
        return payload

    def _write_payload(self, payload, obj):
        payload.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    def test_happy_path_fills_struct_fields(self, tmp_path):
        payload = self._setup(tmp_path)
        self._write_payload(
            payload,
            {
                "purpose": "质检裁决",
                "qa": [{"q": "q1", "a": "a1"}, {"q": "q2", "a": "a2"}],
            },
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
        assert rec["sub_step"] == 5
        node = eng.get_node("understand", 1)
        assert rec["skill"] == node.sub_steps[4].ref  # 从 state 当前步推导，非模型给
        assert rec["q"] == ["q1", "q2"] and rec["a"] == ["a1", "a2"]
        assert not payload.exists()  # 落库后删载荷防重复 append

    def test_gate_sees_appended_trace(self, tmp_path):
        # 与门控集成：append-trace 落库后 latest_trace_sha1 变化（Stop 门控可触发）
        payload = self._setup(tmp_path)
        assert eng.latest_trace_sha1(tmp_path, "t", 5) is None
        self._write_payload(payload, {"purpose": "p", "qa": [{"q": "q", "a": "a"}]})
        ok, _ = eng.append_trace(tmp_path, "t", str(payload))
        assert ok
        assert eng.latest_trace_sha1(tmp_path, "t", 5) is not None

    def test_struct_fields_leak_rejected(self, tmp_path):
        payload = self._setup(tmp_path)
        self._write_payload(
            payload, {"purpose": "p", "qa": [{"q": "q", "a": "a"}], "sub_step": 99}
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert not ok and "结构字段" in msg
        assert payload.exists()  # 失败保留载荷供原地修

    def test_legacy_parallel_arrays_hard_rejected(self, tmp_path):
        # v2.35 写侧收编：q/a 平行数组不再接受（v2.24 过渡桥拆除）——
        # 对齐正确的旧格式也硬拒并指路 qa 配对（漂移习惯第一次就矫正，
        # 不再「写对被默许、偶尔不齐白烧一轮」）。
        payload = self._setup(tmp_path)
        self._write_payload(payload, {"purpose": "p", "q": ["q1"], "a": ["a1"]})
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert not ok and "qa 配对" in msg
        assert not (tmp_path / ".claude" / "evidence" / "t.jsonl").exists()

    def test_legacy_mismatch_also_gets_format_pointer(self, tmp_path):
        # 长度不齐的旧格式同样只给格式指路（不再给无配对项索引——
        # 修格式和修对齐是同一轮重写，不再分两档报错）。
        payload = self._setup(tmp_path)
        self._write_payload(
            payload, {"purpose": "p", "q": ["q1-身份", "q2-无主"], "a": ["a1"]}
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert not ok and "qa 配对" in msg and "长度不齐" not in msg

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

    def test_legacy_empty_arrays_get_format_pointer(self, tmp_path):
        payload = self._setup(tmp_path)
        self._write_payload(payload, {"purpose": "p", "q": [], "a": []})
        ok, msg = eng.append_trace(tmp_path, "t", str(payload))
        assert not ok and "qa 配对" in msg

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
        _write_evidence(tmp_path, "t", [_trace_line(4, "ev4")])
        prompt = eng.redteam_prompt(tmp_path, "t")
        assert prompt is not None
        assert "q-ev4" in prompt  # 子4 证据嵌入（只给证据不给结论）
        assert "单层" in prompt and "禁止再 spawn 子代理" in prompt  # b
        assert "Read 工具为主" in prompt  # c
        assert "证据不足" in prompt  # d
        assert "四态 verdict" in prompt or "证实/证伪/部分成立/证据不足" in prompt

    def test_no_step3_trace_returns_none(self, tmp_path):
        _write_evidence(tmp_path, "t", [_trace_line(1)])
        assert eng.redteam_prompt(tmp_path, "t") is None

    def test_output_pins_literal_labels(self, tmp_path):
        # u1-sub5-cost 修2 模板侧：输出节钉逐字标签（200fb21a 轮红队把
        # 「置信度」简写成「置信 95%」撞 mech 字面扫——模板先钉，mech 再宽）
        _write_evidence(tmp_path, "t", [_trace_line(4, "ev4")])
        prompt = eng.redteam_prompt(tmp_path, "t")
        assert prompt is not None
        assert "置信度" in prompt and "逐字" in prompt

    def test_main_repo_path_hint_pinned(self, tmp_path):
        # u1-time-opt 修A：worker cwd=实例 worktree（干净检出），interaction
        # run 实证它对主树在场的生成文件（backtest/result/*.json、
        # data_fetchers/result/*.parquet）两处声明「不存在/无法复核」，把数值
        # 复核推给子5 主段。提示=主仓库根绝对路径在场+worktree 检出说明。
        _write_evidence(tmp_path, "t", [_trace_line(4, "ev4")])
        prompt = eng.redteam_prompt(tmp_path, "t")
        assert prompt is not None
        assert str(tmp_path) in prompt
        assert "worktree" in prompt and "只在主仓库检出" in prompt


class TestV237FirstPassRate:
    """v2.37 understand:1 一次通过率三连修（2026-08-01 tail_volume 审计）。

    动机：v2.36 钉死判据后 20:19 relaunch 子2 仍同症两连 block——钉死保 judge
    判对，不保模型写对；词形/结构形式要件下沉 append-trace 写侧机械层。
    载荷形态取自 .claude/evidence/tail_volume_acceleration_annualized.jsonl
    真实记录（精简保形，违规字面逐字保留）。
    """

    # ---- 子2 链环禁词（causal_ring_no_untested）----

    def test_replay_u1s2_att1_maybe_magnitude_blocked(self, tmp_path):
        # att1 真实形态：Why4「过滤 NaN 后可能剩 1-5 天」推断量级带 file:line 背书
        # plan-first 拆步：因果链禁词归子2b（sub_step=3）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=3)
        qa = [
            {"q": "单一/复合判定", "a": "复合：量级 + 精度两条 pain，MECE 拆为原子A/B"},
            {
                "q": "原子 A=数值正确性 → 5Whys 因果链（主链每环须=file:line/数据值）",
                "a": (
                    "Why1 量级 +9963%（用户原话+实测值）；Why2 layered_backtest.py:655 "
                    "`annual_return = daily_mean * 252`；Why3 :651 cumprod 与 :655 "
                    "简单乘法语义不一致；Why4 窗口 n 极小时简单乘法年化被错误放大"
                    "（过滤 NaN 后可能剩 1-5 天；layered_backtest.py:630-647）；"
                    "Why5 web_ui/app.py:267 读 parquet 不实时跑回测"
                ),
            },
            {
                "q": "竞争假设（每个原子 ≥1）与排除/保留理由",
                "a": "H_A1=年化公式错（保留：:655）；H_A2=窗口过短（两种可能留子3）",
            },
        ]
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "qa": qa}, ensure_ascii=False), encoding="utf-8"
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "可能" in msg and "竞争假设" in msg

    def test_chain_detected_by_content_not_title_blocked(self, tmp_path):
        # v2.46：2026-08-02 真实形态——模型用「Q4=…」式标题、链写进 a（Why/→），
        # 旧标题锚定空转禁词漏到 judge。链识别 = 标题或 a 结构标记。
        # plan-first 拆步：因果链禁词归子2b（sub_step=3）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=3)
        qa = [
            {
                "q": "Q0=单一/复合判定？",
                "a": "单一（数字 +9529.8% 反常），MECE 拆 5 轴",
            },
            {
                "q": "Q4=因子计算是否有 silent fallback？（因子算子层）",
                "a": (
                    "Why1 因子值 0 占位（ic_tail.py:111）；Why2 无过滤逻辑 → "
                    "percentile 分层可能将 0 值股票集中到某一层 → 极端年化"
                ),
            },
        ]
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "qa": qa}, ensure_ascii=False), encoding="utf-8"
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "可能" in msg

    def test_bu_keneng_negation_not_banned(self, tmp_path):
        # 「不可能」是否定式合法断言，不命中禁词（真实载荷 Q1 含「不可能」）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=2)
        qa = [
            {
                "q": "Q1=字段溯源 → 因果链",
                "a": "Why3 A 股单日涨跌幅 ±10%（PROJECT.md），+37.8%/日单股不可能——"
                "必有口径错位（:655）",
            },
        ]
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "qa": qa}, ensure_ascii=False), encoding="utf-8"
        )
        # 仅测禁词扫描本函数（atomic_questions 等其它校验是正交前置）
        err = eng._check_causal_ring_no_untested(qa)
        assert err is None

    def test_hypothesis_item_exempt(self, tmp_path):
        # 「假设」标题项豁免：竞争假设分支携带可能/未实测合法（待子3取证）
        qa = [
            {"q": "原子 A → 因果链", "a": "Why1 实测值（:655）"},
            {"q": "竞争假设与排除理由", "a": "H1=窗口过短（可能，待子3取证）"},
        ]
        assert eng._check_causal_ring_no_untested(qa) is None

    def test_replay_u1s2_att2_untested_label_blocked(self, tmp_path):
        # att2 真实形态：Why5 贴「未实测/推断」标签当出处
        # plan-first 拆步：因果链禁词归子2b（sub_step=3）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=3)
        qa = [
            {
                "q": "原子 B=展示精度 → 5Whys 因果链（主链每环=file:line）",
                "a": (
                    "Why1 用户原话「展示精度奇怪」+ 实测「+9963.0%」；Why2 "
                    "layered_backtest.py:901 `_format_pct(annual_ret, decimals=2)`；"
                    "Why5 app.py:266-270 读 summary 结果，模板细节=未实测/推断"
                ),
            },
        ]
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "qa": qa}, ensure_ascii=False), encoding="utf-8"
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "未实测" in msg and "竞争假设" in msg

    def test_replay_u1s2_need_action_bridge_blocked(self, tmp_path):
        # v2.49 att1 逐字：待办形态桥接「需 pyarrow…sort 看 top10」当主链终点
        qa = [
            {
                "q": "AQ2 (数据契约层) 主链 5 Whys？",
                "a": (
                    "Why5=数据源列含极端值需 pyarrow.read_parquet(path) + sort 看 top10"
                    " — 该层为主链终点，子3 主会话内查（仓内路径：paths.py "
                    "FACTOR_IC_DATA_MASTER）。"
                ),
            },
        ]
        err = eng._check_causal_ring_no_untested(qa)
        assert err is not None and "需" in err

    def test_replay_u1s2_if_then_form_blocked(self, tmp_path):
        # v2.49 att3 逐字：「若…则」假设形态链环（file:line 背书的是代码文本，
        # 若…则 推出的行为是推断）
        qa = [
            {
                "q": "AQ2 (数据契约层) 主链 5 Whys？",
                "a": (
                    "Why5=极端值溯源点：data_loaders.py:166 convert_return_to_percentage"
                    " 调 formatters.convert_return_to_percentage（summary/report/"
                    "formatters.py convert_return_to_percentage 已 Read）——"
                    "若 convert 函数对极端值未做截断/钳制则异常值无抑制地传到上层显示。"
                ),
            },
        ]
        err = eng._check_causal_ring_no_untested(qa)
        assert err is not None and "若…则" in err

    def test_replay_u1s2_wide_span_blocked(self, tmp_path):
        # v2.49 att2 逐字：:565-771 跨 206 行充精确指针（合法跨度 ≤17，阈值 50）
        qa = [
            {
                "q": "AQ3 (因子层) 主链 5 Whys？",
                "a": (
                    "Why5=因子值进 pd.rank 分层（layered_backtest.py:371）+"
                    "逐日 layer 记录进 daily_records（:319-332）后 _aggregate_results"
                    " 计算 per-layer annual_return 与 long_short_return_annual（:565-771）"
                ),
            },
        ]
        err = eng._check_causal_ring_no_untested(qa)
        assert err is not None and "精确指针" in err and ":565-771" in err

    def test_replay_u1s2_exclude_inference_blocked(self, tmp_path):
        # v2.49 att3 逐字：竞争假设「排除」句含 未实测/推测——排除=断言为假
        # 须证据指针；豁免只留给「保留」句。H2 排除干净、H1/H4 保留合法，
        # 整项只有 H5 一句违规也应拒（逐字保留 att3 假设项全文）
        qa = [
            {
                "q": "竞争假设与排除/保留？",
                "a": (
                    "H1: 个别股票 forward_return_1d 含极端值 (>100%/日) ⇒ 拉高 ls_mean"
                    " (层均值差) — 保留 (AQ1/AQ2 主链终点，子3 parquet sort 取证)。"
                    "H2: forward_return 列错配 (5d 当 1d) — 排除 (layered_backtest_runner.py:609"
                    " 硬编码 1d + :349 元组同时存在 3 列，H2 代码证伪)。"
                    "H4: 因子分母为 0 致 inf/NaN 致分组偏差 — 保留 (AQ3 Why4 降格分支标"
                    "『待子3 取证』，子3 factor_generator.py + parquet sort 取证 + "
                    "pandas pd.notna(inf) 行为文档查证)。"
                    "H5: web_ui 数字格式 bug (乘错/漏零) — 排除 (sections.py:168 + "
                    "formatters.py convert_return_to_percentage + data_loaders.py:166"
                    " 链路 Read 验证：txt 显示经 format_percentage 包装 = "
                    '`f"{val * 100:.{decimals}f}%"` (formatters.py 假设实现，未实测 '
                    "formatters.py 内部代码；推测：链路过长且标准库 f-string 不易引入"
                    "乘错/漏零，H5 假设不成立)。"
                ),
            },
        ]
        err = eng._check_causal_ring_no_untested(qa)
        assert err is not None and "排除" in err

    def test_hypothesis_keep_clean_exclude_accepted(self, tmp_path):
        # v2.49 豁免收窄的 FP 守卫：保留句带「可能」合法 + 排除句干净 → 通过
        qa = [
            {"q": "原子 A → 因果链", "a": "Why1 实测值（:655）"},
            {
                "q": "竞争假设与排除/保留理由",
                "a": "H1=窗口过短（保留：可能，待子3取证）。"
                "H2=列错配（排除：runner.py:609 硬编码 1d 证伪）",
            },
        ]
        assert eng._check_causal_ring_no_untested(qa) is None

    def test_need_action_negations_not_banned(self, tmp_path):
        # v2.49 FP 守卫：无需/所需/必需/按需是否定·限定式合法断言，不命中
        qa = [
            {
                "q": "原子 A → 因果链",
                "a": "Why2 过滤逻辑无需外部调用（:484 valid_returns.mean()）；"
                "Why3 所需列在 :431 `read_cols` 元组；Why4 按需查看是注释原文（:112）",
            },
        ]
        assert eng._check_causal_ring_no_untested(qa) is None

    # ---- v2.50：「待子3取证/降格」独占 Why 环（占环位）+ 原子标签对齐 ----
    # 2026-08-02 tail_volume_acceleration_annualized u:1 子2 三连 block 复盘：
    # v2.49 词表修完上一家族，本轮换家族照样三连——att1「待子3取证/降格」
    # 声明独占主链环位（规则早有反例但词形未下沉）+ atomic_questions 5 项
    # vs 声明 3 原子口径不一致（judge 判两轮，其中一轮判词搬旧数字失真）。

    def test_replay_u1s2_0802_att1_demote_occupies_ring_blocked(self):
        # att1 逐字形态：Why4 整环=「待子3取证」待办、Why5 整环=「降格进
        # 竞争假设」声明——环内无 file:line 指针 = 占环位（声明占环位=未降格）
        qa = [
            {
                "q": "原子 B (回测端) 5Whys 因果链主链 + 每环 file:line？",
                "a": (
                    "Why1: 分层模式 percentile 5 层（layered_backtest.py:10）；"
                    "Why4: 计算公式具体内容 (复利期数/单复利/单位) 在 backtest/ 下文件, "
                    "待子3取证; Why5: 主链到「数据契约+加载路径」实测层终止 — "
                    "公式内容降格进竞争假设待子3验证"
                ),
            },
        ]
        err = eng._check_causal_ring_no_untested(qa)
        assert err is not None and "占环位" in err

    def test_demote_tail_pointer_with_evidence_accepted(self):
        # 同日 att3 形态（judge 已接受 B 链）：环终止于实测层（含 :N 指针），
        # 尾部「降格进竞争假设分支待子 3 验证」是去向指针非占位——不拒
        qa = [
            {
                "q": "原子 B (回测端) 5Whys 因果链主链？",
                "a": (
                    "Why5: 主链终止于 — schema 字段语义未显式标注 (PROJECT.md:1200 "
                    "schema 路径锁定但内容未 Read), 公式层 raw 0-1 语义与项目惯例 "
                    "_format_pct 一致 (layered_backtest.py:41-61), ls_mean=0.3781 "
                    "的物理解释降格进竞争假设分支待子 3 验证"
                ),
            },
        ]
        assert eng._check_causal_ring_no_untested(qa) is None

    def test_demote_in_non_ring_item_not_scanned(self):
        # 自查/元描述项（无 WhyN: 环段）汇报降格去向 = 合法，宁纵勿枉
        qa = [
            {
                "q": "主链每个环是否都停在实测层 + 是否悬空/占主环位?",
                "a": (
                    "原子 B 主链 4 环 (Why1-Why4) 全部 file:line 实测, Why5 物理解释 "
                    "降格进竞争假设分支 B_root H3, 标待子3取证, 不悬空、不占主环位"
                ),
            },
        ]
        assert eng._check_causal_ring_no_untested(qa) is None

    def test_demote_negation_not_banned(self):
        # 「未降格」是否定式合法陈述（规则文本自用词），不命中
        qa = [
            {
                "q": "原子 A → 因果链",
                "a": "Why5: 主链挖到实测层即终止，无未降格占位环",
            },
        ]
        assert eng._check_causal_ring_no_untested(qa) is None

    def test_replay_u1s2_0802_att1_extra_atom_labels_blocked(self):
        # att1 真实形态：声明 MECE 三原子（A/B/C）但 atomic_questions 实列
        # 5 项（A./B./C./D./E.）——D/E 未声明 = 口径不一致机械拒
        qa = [
            {
                "q": "单一/复合判定?",
                "a": "复合痛点, MECE 三原子互不重叠: A=因子端, B=回测端, C=展示端",
            },
            {"q": "原子 A (因子端) 5Whys 主链?", "a": "Why1: 实测（:115）"},
            {"q": "原子 B (回测端) 5Whys 主链?", "a": "Why1: 实测（:10）"},
            {"q": "原子 C (展示端) 5Whys 主链?", "a": "Why1: 实测（:38）"},
        ]
        aq = [
            {"q": "A. 因子值域", "tier": "none", "tier_reason": "x.py:1"},
            {"q": "B. 回测公式", "tier": "none", "tier_reason": "x.py:1"},
            {"q": "C. 渲染逻辑", "tier": "none", "tier_reason": "x.py:1"},
            {"q": "D. 模板注册", "tier": "none", "tier_reason": "x.py:1"},
            {"q": "E. 其它因子对照", "tier": "light", "tier_reason": "外部对照"},
        ]
        err = eng._check_atomic_mece_alignment(aq, qa)
        assert err is not None and "D" in err and "E" in err

    def test_atomic_alignment_root_suffix_labels_accepted(self):
        # 同日 att2/att3 通过形态：aq 用「A_root 验证:…」标签 = 声明原子的
        # 根因验证项，标签集合一致无重复 → 过
        qa = [
            {"q": "原子 A (因子端) 5Whys 主链?", "a": "Why1: 实测（:115）"},
            {"q": "原子 B (回测端) 5Whys 主链?", "a": "Why1: 实测（:10）"},
            {"q": "原子 C (展示端) 5Whys 主链?", "a": "Why1: 实测（:38）"},
        ]
        aq = [
            {"q": "A_root 验证: 因子值域", "tier": "none", "tier_reason": "x.py:1"},
            {"q": "B_root 验证: 回测公式", "tier": "none", "tier_reason": "x.py:1"},
            {"q": "C_root 验证: 渲染逻辑", "tier": "none", "tier_reason": "x.py:1"},
        ]
        assert eng._check_atomic_mece_alignment(aq, qa) is None

    def test_atomic_alignment_unlabeled_skipped(self):
        # 历史通过 fixture 形态：aq 无字母标签（「数值正确性」「展示精度」）——
        # 无标签属 judge 裁量，机械宁纵勿枉不拒（FP 守卫）
        qa = [
            {"q": "原子 A=数值正确性 → 5Whys 因果链", "a": "Why1 实测（:655）"},
            {"q": "原子 B=展示精度 → 5Whys 因果链", "a": "Why1 实测（:901）"},
        ]
        aq = [
            {"q": "数值正确性", "tier": "none", "tier_reason": "x.py:655"},
            {"q": "展示精度", "tier": "none", "tier_reason": "x.py:901"},
        ]
        assert eng._check_atomic_mece_alignment(aq, qa) is None

    # ---- v2.55：全局否定断言（「没有/缺失 X」跨文件存在性命题）----
    # 2026-08-02 tail_volume_acceleration_annualized u:1 子2 第三 episode：
    # att1/att2 同一 Why4「没有显式契约约定…且无 unit test 钉住…」「根因是
    # 层契约缺失」——模型把「读了文件没看到 X」当读出事实。读出的是
    # 「有什么」不是「没有什么」；全局否定断言的合法出处只有全域扫描零
    # 命中留痕，否则降格进竞争假设分支。初版锚 WhyN 分段空转（真实载荷
    # Why1=/Why4（根因层）= 形态不匹配 `Why\d+[:：]`）——改项级扫描。

    def test_replay_u1s2_0802c_att2_absence_claim_blocked(self):
        # att2 逐字（Why4 根因层 + 尾段「根因是层契约缺失」）
        qa = [
            {
                "q": "原子问题 Q1 = +9529.8% 如何形成（主因果链）？",
                "a": (
                    "Why1=模板 _ann_pct = (_ann * 100)（web_ui/templates/"
                    "_section_backtest.html:69 原文 set _ann_pct = (_ann * 100) "
                    "if _ann is not none else 0），读出即事实。\n\n"
                    "Why4（根因层）= 数据层完成小数到百分比 *100 转换后，模板层"
                    "没有显式契约约定接收方不应再 *100，两个 *100 分别由 "
                    "data_loaders 与 _section_backtest.html 各承担一次 ——环内容="
                    "层边界语义所有权不清晰，且无 unit test 钉住 display_value "
                    "与 raw_value 的比例契约。指针 + 因果机制。\n\n"
                    "主链终止于实测层（Why4 含 file:line 指针 + 内容）；根因是"
                    "层契约缺失而非魔法值、除零、NaN 等其他机制。"
                ),
            },
        ]
        err = eng._check_causal_ring_no_untested(qa)
        assert err is not None and "全局否定断言" in err

    def test_absence_with_exhaustive_grep_accepted(self):
        # 合法出口①：全域扫描零命中留痕（grep 命令原文+零命中）
        qa = [
            {
                "q": "原子 A → 因果链",
                "a": "Why3=无显式契约（grep -rn 'annual_contract' . 扫描全仓"
                "零命中，0 结果原文留痕）；Why4=主链终止（:69 原文）。",
            },
        ]
        assert eng._check_causal_ring_no_untested(qa) is None

    def test_absence_demoted_tail_accepted(self):
        # 合法出口②：主链终止于实测层 + 尾部降格去向声明（v2.50 钉的合法
        # 形态）——「契约缺失」后 16 字符内接降格，跳过
        qa = [
            {
                "q": "原子 A → 因果链",
                "a": "Why1=模板再乘 100（_section_backtest.html:69 原文 "
                "_ann_pct=(_ann*100)，读出即事实）。主链终止于实测层；"
                "契约缺失降格至竞争假设分支标待子3取证。",
            },
        ]
        assert eng._check_causal_ring_no_untested(qa) is None

    def test_local_negation_not_absence_claim(self):
        # FP 守卫：局部可读否定（v2.50 正例「未做单位判断」+该行原文）不收
        qa = [
            {
                "q": "原子 A → 因果链",
                "a": "Why1=web_ui 取字段原值=95.298 未做单位判断"
                "（_section_backtest.html:69 原文 _ann_pct=(_ann*100)，读出即事实）",
            },
        ]
        assert eng._check_causal_ring_no_untested(qa) is None

    def test_atomic_alignment_duplicate_label_blocked(self):
        # 一原子多条 = 非一一对应（att1 判词「A 2 项」形态）
        qa = [
            {"q": "原子 A (因子端) 5Whys?", "a": "Why1: 实测（:115）"},
            {"q": "原子 B (回测端) 5Whys?", "a": "Why1: 实测（:10）"},
        ]
        aq = [
            {"q": "A. 值域", "tier": "none", "tier_reason": "x.py:1"},
            {"q": "A. 实现细节", "tier": "none", "tier_reason": "x.py:2"},
            {"q": "B. 公式", "tier": "none", "tier_reason": "x.py:3"},
        ]
        err = eng._check_atomic_mece_alignment(aq, qa)
        assert err is not None and "重复" in err

    def test_atomic_alignment_single_atom_skipped(self):
        # 单一痛点（无「原子 X」声明）→ 无对齐基准，交 judge，不拒
        qa = [{"q": "单一/复合判定?", "a": "单一（无复合理由：痛点只有一项）"}]
        aq = [{"q": "A. 唯一问题", "tier": "none", "tier_reason": "x.py:1"}]
        assert eng._check_atomic_mece_alignment(aq, qa) is None

    def test_atomic_alignment_no_qa_skipped(self):
        # statements 格式步 qa=None → 跳过（调用管道签名兼容守卫）
        aq = [{"q": "A. x", "tier": "none", "tier_reason": "x.py:1"}]
        assert eng._check_atomic_mece_alignment(aq, None) is None

    def test_append_trace_atomic_alignment_integration(self, tmp_path):
        # 管道集成：extra_payload_keys 逐项校验须拿到 qa（声明侧）——
        # att1 形态全载荷经 append_trace 拒（chains 先过禁词扫描）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=2)
        qa = [
            {
                "q": "单一/复合判定?",
                "a": "复合痛点, MECE 三原子: A=因子端, B=回测端, C=展示端",
            },
            {"q": "原子 A (因子端) 5Whys 主链?", "a": "Why1: 实测（:115）"},
            {"q": "原子 B (回测端) 5Whys 主链?", "a": "Why1: 实测（:10）"},
            {"q": "原子 C (展示端) 5Whys 主链?", "a": "Why1: 实测（:38）"},
        ]
        aq = [
            {
                "q": "A. 因子值域",
                "tier": "none",
                "tier_reason": "factor_definitions.py:115 仓内可证伪",
            },
            {
                "q": "B. 回测公式",
                "tier": "none",
                "tier_reason": "layered_backtest.py:713 仓内可证伪",
            },
            {
                "q": "C. 渲染逻辑",
                "tier": "none",
                "tier_reason": "_section_backtest.html:38 仓内可证伪",
            },
            {
                "q": "D. 模板注册",
                "tier": "none",
                "tier_reason": "run_pipeline.py:80 仓内可证伪",
            },
            {
                "q": "E. 其它因子对照",
                "tier": "light",
                "tier_reason": "同页其它因子量级外部对照",
            },
        ]
        (tmp_path / "payload.json").write_text(
            json.dumps(
                {"purpose": "p", "qa": qa, "atomic_questions": aq}, ensure_ascii=False
            ),
            encoding="utf-8",
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "D" in msg and "声明" in msg

    def test_replay_u1s2_att3_real_pass_accepted(self, tmp_path):
        # att3 真实通过版：主链每环实测（含模板 :38 Jinja 片段），零禁词
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=2)
        qa = [
            {"q": "单一/复合判定", "a": "复合：原子A=数值正确性，原子B=展示精度"},
            {
                "q": "原子 A=数值正确性 → 5Whys 因果链（每环须=file:line/数据值）",
                "a": (
                    "Why1 量级 +9963%（用户原话+实测值）；Why2 layered_backtest.py:655 "
                    "简单乘法年化；Why3 :651 cumprod 与 :655 语义不一致；Why4 :659-660 "
                    "sharpe_ratio 直接依赖 :655 错误年化被级联；Why5 :675-686 "
                    "annual_return 写入 layer_stats 供 summary 读取"
                ),
            },
            {
                "q": "原子 B=展示精度 → 5Whys 因果链（每环须=file:line）",
                "a": (
                    "Why1 用户原话+实测「+9963.0%」整百带 .0；Why2 layered_backtest.py:901 "
                    "decimals=2 输出「9963.00%」；Why5 web_ui/templates/_section_backtest.html:38 "
                    '`"%+.1f%%" | format(_best_ann * 100)` KPI 卡 1 位小数渲染出「+9963.0%」'
                ),
            },
            {
                "q": "竞争假设（每个原子 ≥1）+ 排除/保留理由",
                "a": "H_A1=年化公式错（保留：:651/:655）；H_A2=窗口过短（两种可能留子3）",
            },
            {
                "q": "近因 vs 根因 + 置信度",
                "a": "近因=:655 直接产生数值；根因候选 R1（置信度中高）",
            },
        ]
        # v2.40：同版内容补分档键——旧内容在新校验下仍应通过（回归）
        aq = [
            {
                "q": "数值正确性",
                "tier": "none",
                "tier_reason": "年化公式 layered_backtest.py:655 仓内可证伪",
            },
            {
                "q": "展示精度",
                "tier": "none",
                "tier_reason": "渲染链 _section_backtest.html:38 仓内可证伪",
            },
        ]
        (tmp_path / "payload.json").write_text(
            json.dumps(
                {"purpose": "p", "qa": qa, "atomic_questions": aq}, ensure_ascii=False
            ),
            encoding="utf-8",
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert ok, msg

    def test_replay_u1s2_legacy_payload_without_tier_key_rejected(self, tmp_path):
        # v2.40：旧形态（无 atomic_questions 键）写侧机械拒——分档是必填形式要件
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=2)
        qa = [
            {"q": "原子 A → 5Whys 因果链", "a": "Why1 实测值（:655）"},
        ]
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "qa": qa}, ensure_ascii=False), encoding="utf-8"
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "atomic_questions" in msg and "非空数组" in msg

    def test_causal_scan_scope_excludes_hypothesis_items(self, tmp_path):
        # 禁词只扫 q 含「因果链」的项——竞争假设项携带「可能/未实测」合法（留子3 消化）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=2)
        qa = [
            {
                "q": "原子 A → 5Whys 因果链",
                "a": "Why1 实测值（:655）；Why2 :651 不一致（file:line）",
            },
            {
                "q": "竞争假设（每个原子 ≥1）+ 排除/保留理由",
                "a": "H1=X（待子3取证，两种可能）；H2=Y（未实测，保留理由：…）",
            },
        ]
        aq = [{"q": "原子 A", "tier": "full", "tier_reason": "开放问题需五层源双向"}]
        (tmp_path / "payload.json").write_text(
            json.dumps(
                {"purpose": "p", "qa": qa, "atomic_questions": aq}, ensure_ascii=False
            ),
            encoding="utf-8",
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert ok, msg

    # ---- u:2 子1 价值/结论推断词形（value_no_unsourced_inference，v2.48）----

    def test_replay_u2s1_att1_unsourced_inference_blocked(self, tmp_path):
        # att1 真实形态（2026-08-02 tail_volume_acceleration_annualized）：
        # V1「隐含价值」/ V2「长期使用意味着会基于显示值做决策」——judge 当年
        # 拦对但烧了一轮返工；词形下沉后 append-trace 当场拒
        _write_state_full(tmp_path, "t", "understand", 2, sub_step=1)
        qa = [
            {
                "q": "who（受益者）",
                "a": "W1 = 项目维护者（用户自述「我是项目维护者/贡献者」）",
            },
            {
                "q": "初步价值（why 值得做）",
                "a": (
                    "V1 = 报告数据可信（用户自述「排查代码确认是不是 bug」=真痛点）"
                    "——价值锚点=用户自述「是不是有问题」（隐含「如果有问题则修复，"
                    "避免基于错误数据做决策」）。V2 = 不再因显示错误误判"
                    "（用户自述「一直用 web_ui 翻报告」——长期使用意味着会基于"
                    "显示值做决策，错误显示会导致误判后续选股/调仓）"
                ),
            },
            {"q": "结论 = ① 目标成立？", "a": "①目标成立——S1→O2、S2→O1"},
        ]
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "qa": qa}, ensure_ascii=False), encoding="utf-8"
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "隐含" in msg and "推测" in msg

    def test_replay_u2s1_att2_real_pass_accepted(self, tmp_path):
        # att2 真实通过版：V1 干净 + V2* 标「推测」另列（推测豁免生效）
        _write_state_full(tmp_path, "t", "understand", 2, sub_step=1)
        qa = [
            {
                "q": "who（受益者）",
                "a": "W1 = 项目维护者（用户自述「我是项目维护者/贡献者」）",
            },
            {
                "q": "初步价值（why 值得做，surgical 改）",
                "a": (
                    "V1 = 字面诉求=修复 bug（用户自述「排查代码确认是不是 bug」"
                    "两处原话直接引用，无推断补全）。\n\n[推测另列，不纳入结论]\n\n"
                    "V2* = 推测（无用户原话佐证）：用户可能基于显示值做后续决策，"
                    "但用户未明确陈述此类下游用途。标「推测」不纳入 V1 结论。"
                ),
            },
            {
                "q": "结论 = ① 目标成立？",
                "a": "①目标成立——S1→O2、S2→O1；V2* 标「推测」另列不纳入结论",
            },
        ]
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "qa": qa}, ensure_ascii=False), encoding="utf-8"
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert ok, msg

    def test_value_scan_maybe_blocked_and_negation_exempt(self, tmp_path):
        # 「可能」命中；「不可能」否定式合法断言不命中（复用 _MAYBE_RE 口径）
        qa = [{"q": "初步价值", "a": "V1 = 用户可能会据此调仓"}]
        err = eng._check_value_no_unsourced_inference(qa)
        assert err and "可能" in err
        qa2 = [{"q": "初步价值", "a": "V1 = 单日 ±10% 限制下不可能出现真值 +9529%"}]
        assert eng._check_value_no_unsourced_inference(qa2) is None

    def test_value_scan_scope_only_value_and_conclusion(self, tmp_path):
        # who/outcome 项不受扫描（词形只锚价值/结论项——who 项含「意味着」类
        # 表述不违规，扫描面收窄防 FP）
        qa = [
            {"q": "who（受益者）", "a": "长期使用意味着粘性高（会话事实归集）"},
            {"q": "outcome（达成什么状态）", "a": "O1 = 页面显示正确"},
        ]
        assert eng._check_value_no_unsourced_inference(qa) is None

    # ---- u:2 子1 framing 反转配套 mech（v2.87，候选标签↔追溯对齐 + 出处标注，
    # designs/u2-sub1-gate-framing-design.md）----

    def test_u2s1_orphan_candidate_blocked(self, tmp_path):
        # vio1 形态：G2 只在候选项出现、追溯项只提 G1——生产墙零方差当场拒
        _write_state_full(tmp_path, "t", "understand", 2, sub_step=1)
        qa = [
            {"q": "who=受益者", "a": "用户原话：'我自己'。"},
            {
                "q": "目标候选如何追溯到ProblemContext存活问题？",
                "a": "G1'得到正IC因子数量'直接承接唯一存活问题'统计IC均值>0的因子数量'。",
            },
            {
                "q": "除 G1 外还有其他目标候选吗？",
                "a": "G2：做一个因子 IC 分布可视化看板。",
            },
        ]
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "qa": qa}, ensure_ascii=False), encoding="utf-8"
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "G2" in msg and "追溯" in msg

    def test_u2s1_traceability_aligned_pass(self):
        qa = [
            {
                "q": "目标候选如何追溯？",
                "a": "G1 承接存活问题 P1；G2 承接存活问题 P2。",
            },
            {"q": "除 G1 外？", "a": "G2：用数量决定门槛后的清单复核。"},
        ]
        assert eng._check_goal_candidate_traceability_alignment(qa) is None

    def test_u2s1_traceability_skip_no_labels_or_no_item(self):
        # ②无候选（无 G 标签）/ 无追溯项 -> 跳过交 judge（宁纵勿枉）
        assert (
            eng._check_goal_candidate_traceability_alignment(
                [{"q": "结论", "a": "结论②目标不成立（用户原话'就这个'）"}]
            )
            is None
        )
        assert (
            eng._check_goal_candidate_traceability_alignment(
                [{"q": "目标候选", "a": "G1：得到正 IC 因子数量"}]
            )
            is None
        )

    def test_u2s1_source_marker_blocked(self):
        # vio2 形态：who/outcome/价值项无出处标注——生产墙当场拒
        qa = [
            {"q": "who=受益者", "a": "想了解正IC因子数量的人。"},
            {"q": "outcome=达成状态", "a": "统计出IC均值>0的因子数量。"},
            {"q": "初步价值", "a": "有助于后续筛选。"},
        ]
        err = eng._check_answer_source_marker(qa)
        assert err and "出处标注" in err and "who" in err

    def test_u2s1_source_marker_pass_forms(self):
        # 合法标注形态全过：用户原话/原始请求/会话事实/选中/自述
        # （标某项=outcome——who×「原始请求」不对口词形另测，不在此例）
        for marker in (
            "用户原话：'我自己'",
            "原始请求：'有多少个'",
            "会话事实：T+1 机制",
            "（AskUserQuestion 选中）",
            "用户自述「我是维护者」",
        ):
            qa = [{"q": "outcome=达成状态", "a": marker}]
            assert eng._check_answer_source_marker(qa) is None, marker
        # 结论/追溯项不扫描（扫描面收窄防 FP）
        assert (
            eng._check_answer_source_marker(
                [{"q": "结论=①目标成立？", "a": "①目标成立——S1→O2"}]
            )
            is None
        )

    def test_u2s1_who_cites_original_request_blocked(self):
        # vio6 形态：who 项引「原始请求」标注=张冠李戴不对口词形，零方差拒；
        # outcome/价值项引「原始请求」合法（请求原文指向状态/价值）
        err = eng._check_answer_source_marker(
            [{"q": "who=受益者", "a": "原始请求：'现在有多少个因子的IC为正？'"}]
        )
        assert err and "原始请求" in err and "受益者" in err
        assert (
            eng._check_answer_source_marker(
                [
                    {
                        "q": "outcome=达成状态",
                        "a": "原始请求：'现在有多少个因子的IC为正？'",
                    }
                ]
            )
            is None
        )

    # ---- u:2 子3 framing 反转配套 mech（v2.89，基线工具留痕扫描，
    # designs/u2-sub3-gate-framing-design.md）----

    def test_u2s3_baseline_no_tool_trace_blocked(self):
        # vio2 形态：基线数字在场但无工具动词（「根据最近报告数据」=拍脑袋数字）——
        # 生产墙零方差当场拒
        qa = [
            {
                "q": "G1当前可量化基线是什么？",
                "a": "根据最近报告数据，baseline_total=72，positive_ic_mean=14，"
                "positive_share=19.44%，report_date=2026-07-25。",
            }
        ]
        err = eng._check_baseline_tool_trace(qa)
        assert err and "工具留痕" in err and "编造" in err

    def test_u2s3_baseline_tool_trace_pass_forms(self):
        # 合法形态全过：Bash实测声明 / Bash命令+python3+输出 / 不可量化+原因
        pass_forms = [
            "Bash实测最新default报告：baseline_total=72，positive_ic_mean=14。",
            "Bash命令原文：python3 -c \"import re; p='/home/admin/...'; ...\"。输入路径="
            "/home/admin/...。Bash原始输出：path=... rows=72 positive=14。",
            "该状态不可量化，原因是用户后续人工裁决，仓库无完成记录；不以推测值替代。",
        ]
        for form in pass_forms:
            qa = [{"q": "G1当前可量化基线是什么？", "a": form}]
            assert eng._check_baseline_tool_trace(qa) is None, form

    def test_u2s3_baseline_skip_rules(self):
        # 宁纵勿枉：非基线题 / 无数字基线（交 judge 空泛复述兜底）跳过
        assert (
            eng._check_baseline_tool_trace(
                [{"q": "G1的价值链是什么？", "a": "→承接痛点'候选太多'→决策支持"}]
            )
            is None
        )
        assert (
            eng._check_baseline_tool_trace(
                [{"q": "G1当前可量化基线是什么？", "a": "当前效率不高，改进后更快。"}]
            )
            is None
        )

    # ---- u:3 子2 framing 反转配套 mech（v2.92，已验证项工具留痕扫描，
    # designs/u3-sub2-gate-framing-design.md）----

    def test_u3s2_constraint_no_tool_trace_blocked(self):
        # vio1/vio3 形态：已验证项无工具动词（裸结论 / 通常-一般来说训练记忆）--
        # 生产墙零方差当场拒
        qa1 = [
            {
                "q": "C2.1/C2.2 如何处置？",
                "a": "C2.1 已验证：报告 IC 字段口径为 ic_mean。"
                "C2.2 已验证：报告数据日期满足口径。",
            }
        ]
        err = eng._check_constraint_verification_tool_trace(qa1)
        assert err and "工具留痕" in err and "编造" in err
        qa3 = [
            {
                "q": "C1.1/C1.2 如何处置？",
                "a": "C1.1 已验证：通常这类项目都用 paths.py 管理路径。"
                "C1.2 已验证：一般来说 web_ui 都是只读的。",
            }
        ]
        err3 = eng._check_constraint_verification_tool_trace(qa3)
        assert err3 and "工具留痕" in err3

    def test_u3s2_constraint_tool_trace_pass_forms(self):
        # 合法形态全过：Read 原文 / Bash 实测 / AskUserQuestion 原话
        pass_forms = [
            "C1.1 已验证：Read CLAUDE.md §5 原文「H7：路径只能 from paths import」。",
            "C2.1 已验证：Bash 实测 `python3 -c import pyarrow` 输出 True。",
            "C4.1 已验证：AskUserQuestion 选中原话'没有时间压力'。",
        ]
        for form in pass_forms:
            qa = [{"q": "处置？", "a": form}]
            assert eng._check_constraint_verification_tool_trace(qa) is None, form

    def test_u3s2_constraint_skip_rules(self):
        # 宁纵勿枉：假设/证伪项不扫（假设本不要求工具留痕）；汇总「八条已验证」跳过
        assert (
            eng._check_constraint_verification_tool_trace(
                [
                    {
                        "q": "推测项如何处置？",
                        "a": "假设：标「假设·置信度:中·错误时影响:…」留子5。",
                    }
                ]
            )
            is None
        )
        assert (
            eng._check_constraint_verification_tool_trace(
                [
                    {
                        "q": "三态处置有无遗漏？",
                        "a": "三态处置无遗漏：C1.1-C4.2 八条已验证、推测项一条假设。",
                    }
                ]
            )
            is None
        )

    # ---- plan:1 子1 framing 反转配套 mech（v2.99，现状勘察符号引用工具留痕扫描，
    # designs/p1-sub1-gate-framing-design.md §3）----

    def test_p1s1_terrain_tool_trace_block_forms(self):
        # vio1/vio2 形态：裸符号引用（.py/函数名）无 file:line 无工具动词 = 生产墙当场拒
        qa1 = [
            {
                "q": "②可复用点如何？",
                "a": "一般这类项目都有 utils.py 放通用统计函数。",
            }
        ]
        err = eng._check_terrain_tool_trace(qa1)
        assert err and "工具留痕" in err
        qa2 = [
            {
                "q": "①涉及模块如何？",
                "a": "已有现成实现在 summary/report/ic_stats.py 的 count_positive_ic() 函数。",
            }
        ]
        err2 = eng._check_terrain_tool_trace(qa2)
        assert err2 and "工具留痕" in err2

    def test_p1s1_terrain_tool_trace_pass_forms(self):
        # 合法形态全过：file:line 定位（形式要件 or 分支）/ codegraph / Bash / Read
        pass_forms = [
            "报告 IC 区块生成在 summary/report/sections.py:32 _generate_ic_section。",
            "codegraph 输出 function _generate_ic_section summary/report/sections.py:32。",
            "Bash 实测 `python3 -c import pyarrow` 输出 True。",
            "IC 结果路径 paths.py:75 FACTOR_IC_RESULT（Read paths.py 72-79 原文确认）。",
        ]
        for form in pass_forms:
            qa = [{"q": "勘察？", "a": form}]
            assert eng._check_terrain_tool_trace(qa) is None, form

    def test_p1s1_terrain_skip_rules(self):
        # 宁纵勿枉：未知标注不扫；无符号引用不扫
        assert (
            eng._check_terrain_tool_trace(
                [
                    {
                        "q": "勘察不到？",
                        "a": "**未知**：_generate_ic_section 内过滤逻辑 codegraph 无法给出。",
                    }
                ]
            )
            is None
        )
        assert (
            eng._check_terrain_tool_trace(
                [{"q": "范围？", "a": "只勘察报告展示链路，未勘察因子计算。"}]
            )
            is None
        )

    # ---- plan:2 子1 framing 反转配套 mech（v2.103，要素清单原文引用留痕扫描，
    # designs/plan2-sub1-gate-framing-design.md §3）----

    def test_p2s1_element_quote_trace_block_forms(self):
        # vio1/vio4 形态：要素条目引用代码符号形（.py）却无任何『』原文引用/原文
        # 字样 = 生产墙当场拒（全清单裸=编造 / 有出处行号无原文=原文未引用）
        qa1 = [
            {
                "q": "①原子改动要素清单如何？",
                "a": "E1=在 summary/generate_factor_summary_report.py 的 "
                "_aggregate_positive_ic 统计函数内增加 FACTOR_CATEGORIES 分组键（改）。",
            }
        ]
        err = eng._check_element_quote_trace(qa1)
        assert err and "原文" in err, "裸符号引用无原文引用应拒"
        qa2 = [
            {
                "q": "①原子改动要素清单如何？",
                "a": "E1=`summary/generate_factor_summary_report.py` "
                "`_aggregate_positive_ic` 增加分组键（改，design.md:12）。",
            }
        ]
        err2 = eng._check_element_quote_trace(qa2)
        assert err2 and "原文" in err2, "有出处行号但无原文引用应拒"

    def test_p2s1_element_quote_trace_pass_forms(self):
        # 合法形态全过：任一要素带『』原文引用 / 含「原文」字样
        pass_forms = [
            "E1=`summary/generate_factor_summary_report.py` `_aggregate_positive_ic` "
            "增加分组键（改）——出处 design.md:12，原文『在既有聚合统计函数内增加 "
            "FACTOR_CATEGORIES 维度分组键，复用 factor_definitions.py 映射做 group key』。",
            "E2=`summary/report/sections.py` `_generate_ic_section` 增加八维度汇总区块"
            "（改）——出处 design.md:14，原文『_generate_ic_section 内新增八维度汇总区块』。",
        ]
        for form in pass_forms:
            qa = [{"q": "要素清单？", "a": form}]
            assert eng._check_element_quote_trace(qa) is None, form

    def test_p2s1_element_quote_skip_rules(self):
        # 宁纵勿枉：验收包/假设无 .py 不扫；整条答案任一要素有原文引用即放过
        # （vio2 的 E4 裸但 E1-E3 有原文引用→交 judge 判静默新增）
        assert (
            eng._check_element_quote_trace(
                [
                    {
                        "q": "②验收包清单如何？",
                        "a": "SC1.1『报告展示八维度条数+占比可读出』（design.md:20）。",
                    }
                ]
            )
            is None
        )
        assert (
            eng._check_element_quote_trace(
                [
                    {
                        "q": "①要素清单如何？",
                        "a": "E1=`summary/...py` 加分组键（改）——出处 design.md:12，原文"
                        "『分组键』；E4=`scripts/category_summary.py` 新增独立脚本。",
                    }
                ]
            )
            is None
        )

    # ---- plan:3 子4 framing 反转配套 mech（v2.112，assumption_completeness_trace
    # 跨节点复用，designs/plan3-sub4-gate-framing-design.md §3）----

    def test_p3s4_assumption_completeness_reuse_on_binding_forms(self):
        # 跨节点复用有效性（第二十四例① 三问）：同一 mech 对 plan:3#4 的能力
        # 绑定三态载荷形态同样精确——触发面/放过面/扫描粒度均与 plan:2#3 同构，
        # 差异只在被核验对象（执行单元 vs 能力绑定），不落 mech 触发面。
        # vio3 形态：B3 假设标签在场却无置信度×错误时影响
        qa_bad = [
            {
                "q": "B2/B3 四类核验留痕如何？三态标注？",
                "a": "B3 `karpathy-guidelines` 核验：①条目存在--列表行；"
                "②CLI 不适用--显式声明。三态：一项假设--该 plugin skill 磁盘 "
                "SKILL.md 路径未逐一 ls 核实，仅凭列表行在册推定可加载。",
            }
        ]
        err = eng._check_assumption_completeness_trace(qa_bad)
        assert err and "置信度" in err, "绑定假设缺置信度+影响应拒"
        # 合法形态：定性置信度（高/中/低）+ 错误时影响在场即过（不索数值化）
        qa_ok = [
            {
                "q": "B2/B3 四类核验留痕如何？三态标注？",
                "a": "B3 核验：①条目存在--列表行。三态：一项假设--磁盘 SKILL.md "
                "路径未逐一核实（置信度高×影响低：错误时 Skill 调用当场报错、"
                "可即时改走内联行为约束，不影响 B1/B2/B4 绑定）。",
            }
        ]
        assert eng._check_assumption_completeness_trace(qa_ok) is None, (
            "定性置信度+影响在场应过（禁索数值化）"
        )
        # 宁纵勿枉：「假设项」提及形（假设后接「项」非结构化标点）不扫
        qa_skip = [
            {
                "q": "假设项/证伪项汇总？",
                "a": "假设项汇总：一条（B3 plugin 路径未逐一核实，见 a2）。"
                "证伪项：无。",
            }
        ]
        assert eng._check_assumption_completeness_trace(qa_skip) is None, (
            "「假设项」提及形应放过交 judge"
        )

    # ---- plan:3 子1 framing 反转配套 mech（v2.106，需求清单原文引用留痕扫描，
    # designs/plan3-sub1-gate-framing-design.md §3）----

    def test_p3s1_need_quote_trace_block_forms(self):
        # vio1/vio4 形态：需求条目引用代码符号形（.py）却无任何『』原文引用/原文
        # 字样 = 生产墙当场拒（全清单裸=编造 / 有出处行号无原文=原文未引用）
        qa1 = [
            {
                "q": "逐任务操作类型清单如何？",
                "a": "N1=U2 代码改动（summary/generate_factor_summary_report.py "
                "聚合统计函数加分组键，改 .py=H15 信号）。",
            }
        ]
        err = eng._check_need_quote_trace(qa1)
        assert err and "原文" in err, "裸符号引用无原文引用应拒"
        qa2 = [
            {
                "q": "逐任务操作类型清单如何？",
                "a": "N1=U2 代码改动（`summary/generate_factor_summary_report.py` "
                "`_aggregate_positive_ic` 加分组键，改 .py=H15 信号，plan.md:12）。",
            }
        ]
        err2 = eng._check_need_quote_trace(qa2)
        assert err2 and "原文" in err2, "有出处行号但无原文引用应拒"

    def test_p3s1_need_quote_trace_pass_forms(self):
        # 合法形态全过：任一需求带『』原文引用 / 含「原文」字样
        pass_forms = [
            "N1=U2 代码改动（`summary/generate_factor_summary_report.py` "
            "`_aggregate_positive_ic` 加分组键，改 .py=H15 信号）--出处 plan.md:12，"
            "原文『在既有聚合统计函数内增加 FACTOR_CATEGORIES 维度分组键』。",
            "N2=U1 代码改动（`paths.py` 增加 CATEGORY_SUMMARY_RESULT 路径常量，"
            "改 .py=H15 信号）--出处 plan.md:10，原文『新增 CATEGORY_SUMMARY_RESULT "
            "路径常量』。",
        ]
        for form in pass_forms:
            qa = [{"q": "逐任务操作类型清单如何？", "a": form}]
            assert eng._check_need_quote_trace(qa) is None, form

    def test_p3s1_need_quote_trace_skip_rules(self):
        # 宁纵勿枉：无 .py 的答案不扫（纯数据读取需求条目交 judge 判残留判面）；
        # 整条答案任一需求有原文引用即放过（vio2 的 N3 裸但 N1/N2 有原文引用
        # →交 judge 判静默新增）
        assert (
            eng._check_need_quote_trace(
                [
                    {
                        "q": "新增候选标注了吗？",
                        "a": "新增候选（plan.md 没有的需求）：显式『无』。",
                    }
                ]
            )
            is None
        )
        assert (
            eng._check_need_quote_trace(
                [
                    {
                        "q": "逐任务操作类型清单如何？",
                        "a": "N1=U2 代码改动（`summary/...py` 加分组键，plan.md:12，"
                        "原文『分组键』）；N3=跑 fresh 检查验证 PRICE_VOLUME 全量落库。",
                    }
                ]
            )
            is None
        )

    # ---- plan:4 子1 framing 反转配套 mech（v2.115，控制结构输入清单原文引用留痕
    # 扫描，designs/plan4-sub1-gate-framing-design.md §3）----

    def test_p4s1_epc_quote_trace_block_forms(self):
        # vio1/vio4 形态：清单条目引用代码符号形（.py）却无任何『』原文引用/原文
        # 字样 = 生产墙当场拒（全清单裸=编造 / 有出处行号无原文=原文未引用）
        qa1 = [
            {
                "q": "控制结构输入五类清单如何？",
                "a": "①任务 DAG：T1=U2 代码改动（summary/generate_factor_summary_report.py "
                "_aggregate_positive_ic 内增加分组键，改 .py=H15 信号）。",
            }
        ]
        err = eng._check_epc_quote_trace(qa1)
        assert err and "原文" in err, "裸符号引用无原文引用应拒"
        qa2 = [
            {
                "q": "控制结构输入五类清单如何？",
                "a": "①任务 DAG：T1=U2 代码改动（`summary/generate_factor_summary_report.py` "
                "`_aggregate_positive_ic` 内增加分组键，改 .py=H15 信号，plan.md:12）。",
            }
        ]
        err2 = eng._check_epc_quote_trace(qa2)
        assert err2 and "原文" in err2, "有出处行号但无原文引用应拒"

    def test_p4s1_epc_quote_trace_pass_forms(self):
        # 合法形态全过：任一清单条目带『』原文引用 / 含「原文」字样
        pass_forms = [
            "①任务 DAG：T1=U2 代码改动（`summary/generate_factor_summary_report.py` "
            "`_aggregate_positive_ic` 内增加分组键，改 .py=H15 信号）--出处 plan.md:12，"
            "原文『U2: 在既有聚合统计函数内增加 FACTOR_CATEGORIES 维度分组键』。",
            "⑤不可逆操作候选：T2 后 `git push` 推送主仓（外发）--出处 plan.md:15，"
            "原文『T2 完成后 git push 推送远端』；①任务 DAG：`paths.py` 加路径常量，"
            "plan.md:11，原文『U1: 新增 CATEGORY_SUMMARY_RESULT 路径常量』。",
        ]
        for form in pass_forms:
            qa = [{"q": "控制结构输入五类清单如何？", "a": form}]
            assert eng._check_epc_quote_trace(qa) is None, form

    def test_p4s1_epc_quote_trace_skip_rules(self):
        # 宁纵勿枉：无 .py 的答案不扫（纯验收包 SC ID/假设 H1 条目交 judge 判残留
        # 判面）；整条答案任一清单项有原文引用即放过（vio2 的 ⑤ 裸但 ①-④ 有原文
        # 引用→交 judge 判静默新增）
        assert (
            eng._check_epc_quote_trace(
                [
                    {
                        "q": "③验收包如何？",
                        "a": "SC1.1『报告含八维度汇总区块』（understand.md:22）。",
                    }
                ]
            )
            is None
        )
        assert (
            eng._check_epc_quote_trace(
                [
                    {
                        "q": "控制结构输入五类清单如何？",
                        "a": "①任务 DAG：T1=U2 代码改动（`summary/...py` 加分组键，"
                        "plan.md:12，原文『分组键』）；⑤不可逆操作：删除旧报告目录。",
                    }
                ]
            )
            is None
        )

    # ---- plan:2 子2 framing 反转配套 mech（v2.102，切分排序三 mech，
    # designs/plan2-sub2-gate-framing-design.md §3）----

    def test_p2s2_dependency_order_trace_block_pass_skip(self):
        # vio2 形态：声明 U3 依赖 U2、U2 依赖 U1，拓扑序 U3->U2->U1（被依赖者排后）
        qa_rev = [
            {
                "q": "依赖 DAG 拓扑排序如何？",
                "a": (
                    "U3（依赖 U2）-> U2（依赖 U1）-> U1（无依赖），拓扑序 U3->U2->U1。"
                ),
            }
        ]
        err = eng._check_dependency_order_trace(qa_rev)
        assert err and "被依赖者排后" in err, "拓扑序反向应拒"
        # 合法形态：被依赖者先行
        qa_ok = [
            {
                "q": "依赖 DAG 拓扑排序如何？",
                "a": (
                    "U1（无依赖）-> U2（依赖 U1）-> U3（依赖 U2），拓扑序 U1->U2->U3。"
                ),
            }
        ]
        assert eng._check_dependency_order_trace(qa_ok) is None, "正向应过"
        # 宁纵勿枉：无拓扑序 / 无依赖声明 -> 过
        assert (
            eng._check_dependency_order_trace(
                [{"q": "切分如何？", "a": "U1=常量，U2=分组键，无拓扑序表述。"}]
            )
            is None
        ), "无拓扑序应过"
        assert (
            eng._check_dependency_order_trace(
                [{"q": "排序如何？", "a": "拓扑序 U1->U2->U3，未声明依赖关系。"}]
            )
            is None
        ), "无依赖声明应过"

    def test_p2s2_element_coverage_trace_block_pass_skip(self, tmp_path):
        # S1 元素基线（子1 trace，含 E1/E2/E3）
        import json as _json

        s1 = _json.dumps(
            {
                "kind": "skill-trace",
                "major_stage": "Plan",
                "minor_stage": "TaskBreakdown",
                "sub_step": 1,
                "q": ["要素清单？"],
                "a": [
                    "E1=`summary/generate_factor_summary_report.py` 加分组键；"
                    "E2=`summary/report/sections.py` 加区块；E3=`paths.py` 加常量。"
                ],
            },
            ensure_ascii=False,
        )
        _write_evidence(tmp_path, "t", [s1])
        # vio4 形态：S2 只承接 E1/E2，丢 E3
        qa_miss = [
            {"q": "要素 ID 覆盖核对？", "a": ("E1->U2、E2->U3，两要素全覆盖无漏。")}
        ]
        err = eng._check_element_coverage_trace(qa_miss, tmp_path, "t")
        assert err and "E3" in err and "覆盖有漏" in err, "丢 E3 应拒"
        # 合法形态：三要素全覆盖
        qa_ok = [
            {
                "q": "要素 ID 覆盖核对？",
                "a": ("E1->U2、E2->U3、E3->U1，三要素全覆盖无漏。"),
            }
        ]
        assert eng._check_element_coverage_trace(qa_ok, tmp_path, "t") is None, (
            "全覆盖应过"
        )
        # 宁纵勿枉：无 S1 -> 过（交 judge）
        assert (
            eng._check_element_coverage_trace(qa_miss, tmp_path, "no_such") is None
        ), "无 S1 应过"

    def test_p2s2_single_phase_argument_block_pass_skip(self):
        # vio5 形态：声明单阶段却同段无 H9 量化（文件数+行数）
        qa_bare = [
            {
                "q": "阶段划分如何？",
                "a": (
                    "阶段划分：单阶段（U1+U2+U3 同属一纵向切片，可整体验证+提交+回滚）。"
                    "断点验证方法（提案）：阶段末跑脚本+断言区块。"
                ),
            }
        ]
        err = eng._check_single_phase_argument(qa_bare)
        assert err and "量化论证" in err, "单阶段无量化应拒"
        # 合法形态：单阶段附 H9 量化（文件数+行数）
        qa_ok = [
            {
                "q": "阶段划分如何？",
                "a": (
                    "阶段划分：单阶段。②单阶段不可拆论证：三单元合计 3 文件 ~75 行，"
                    "H9 内（≤3 文件 ≤200 行）一次可完。"
                ),
            }
        ]
        assert eng._check_single_phase_argument(qa_ok) is None, "附量化应过"
        # 宁纵勿枉：多阶段划分（无单阶段/不可拆声明）不触发
        qa_multi = [
            {
                "q": "阶段划分如何？",
                "a": (
                    "阶段划分：两阶段--阶段一=U1+U2，阶段二=U3。断点验证方法（提案）："
                    "阶段一末跑 U2 断言分组结构。"
                ),
            }
        ]
        assert eng._check_single_phase_argument(qa_multi) is None, "多阶段应过"
        # 全量扫描误放过防御：单阶段在 a[2]、单元预算「1 文件 ~30 行」在 a[0]
        # （vio5 真实形态）--逐答案扫描须拒 a[2]，不被 a[0] 的单元预算误判放过
        qa_split = [
            {"q": "单元切分如何？", "a": "U2 H9 预算 1 文件 ~30 行。"},
            {
                "q": "阶段划分如何？",
                "a": "阶段划分：单阶段（同属纵向切片）。断点验证方法：阶段末跑脚本。",
            },
        ]
        err2 = eng._check_single_phase_argument(qa_split)
        assert err2 and "量化论证" in err2, "逐答案扫描须拒（不被他段单元预算放过）"

    # ---- plan:2 子4 framing 反转配套 mech（v2.109，验收包映射漏项跨步差集，
    # designs/plan2-sub4-gate-framing-design.md §3）----

    def test_p2s4_sc_coverage_trace_block_pass_skip(self, tmp_path):
        import json as _json

        # 子1 验收包清单（sub1 trace，含 SC1.1/SC2.1/SC3.1）
        s1 = _json.dumps(
            {
                "kind": "skill-trace",
                "major_stage": "Plan",
                "minor_stage": "TaskBreakdown",
                "sub_step": 1,
                "q": ["②验收包清单如何？"],
                "a": [
                    "②验收包三条：SC1.1『报告展示八维度条数+占比可读出』（design.md:20）；"
                    "SC2.1『分组口径与 FACTOR_CATEGORIES 映射一致可核对』（design.md:21）；"
                    "SC3.1『交付形态=报告新增八维度汇总区块』（design.md:22）。"
                ],
            },
            ensure_ascii=False,
        )
        _write_evidence(tmp_path, "t", [s1])

        def stmt(am):
            return {
                "text": "t",
                "type_label": "单阶段",
                "boundary": "b",
                "fields": {
                    "change_point": "c",
                    "interface": "i",
                    "verify": "v",
                    "acceptance_map": am,
                    "trace_anchor": "E1",
                },
            }

        # vio4 形态：三项 acceptance_map 全「无直接验收包承接」，三 SC 全漏
        stmts_miss = [
            stmt("（无直接验收包承接）"),
            stmt("（无直接验收包承接）"),
            stmt("（无直接验收包承接）"),
        ]
        err = eng._check_sc_coverage_trace(stmts_miss, tmp_path, "t")
        assert err and "SC1.1" in err and "漏项" in err, "三 SC 全漏应拒"
        # vio4 部分漏：只缺 SC3.1
        stmts_partial = [
            stmt("（无直接验收包承接，为 U2/U3 提供输出路径基础）"),
            stmt("SC1.1（八维度条数+占比可读出）、SC2.1（分组口径与映射一致）"),
            stmt("（无直接验收包承接）"),
        ]
        err_p = eng._check_sc_coverage_trace(stmts_partial, tmp_path, "t")
        assert err_p and "SC3.1" in err_p and "漏项" in err_p, "缺 SC3.1 应拒"
        # 合法形态：每 SC ≥1 项承接（U1「无」合法，只判全局覆盖）
        stmts_ok = [
            stmt("（无直接验收包承接，为 U2/U3 提供输出路径基础）"),
            stmt("SC1.1（八维度条数+占比可读出）、SC2.1（分组口径与映射一致）"),
            stmt("SC3.1（交付形态=报告新增八维度汇总区块）"),
        ]
        assert eng._check_sc_coverage_trace(stmts_ok, tmp_path, "t") is None, (
            "全覆盖应过"
        )
        # 宁纵勿枉：无子1 -> 过（交 judge）
        assert eng._check_sc_coverage_trace(stmts_miss, tmp_path, "no_such") is None, (
            "无子1 应过"
        )

    # ---- plan:1 子5 framing 反转配套 mech（v2.116，ADR 否决理由缺席型负判定，
    # designs/plan1-sub5-gate-framing-design.md §3）----

    def test_p1s5_rejected_rationale_block_pass_skip(self):
        def stmt(rej):
            return {
                "text": "t",
                "type_label": "推荐",
                "boundary": "b",
                "fields": {
                    "change_list": "c",
                    "interface_sig": "i",
                    "data_contract": "d",
                    "callers": "cl",
                    "rejected": rej,
                    "assumptions": "无",
                    "acceptance_map": "SC1.1",
                    "h9_units": "U1=1 文件约 30 行",
                },
            }

        fn = eng._check_rejected_rationale_trace
        # vio5 形态：只列被否名单无任何解释
        for bad in (
            "候选B、候选C 已被否",
            "候选B 被否；候选C 被否",
            "被否形态=新增独立图表",
            "被否路径=自行实现百分比格式化",
        ):
            err = fn([stmt(bad)], None, None)
            assert err and "ADR 丢失" in err, f"只列名单应拒：{bad}"
        # 合法形态：理由源不限、粒度不限（gate 方框五「列举是示例不是封闭清单」对偶）
        for ok in (
            "候选B 被否——理由=子3 核验其跨 2 文件触发 H8 且不复用既有实现，子4 净分 −2",
            "候选C 被否：影响面 impact 7 符号跨两模块、需 schema 迁移",
            "被否形态=新增独立图表——子4 backward 追溯回溯不到 must 目标=镀金项",
            "被否路径=自行实现百分比格式化，因为子3 重复造轮子检查确认既有实现已在册",
            "候选B 被否（复用度低、可测试性成本高）",
        ):
            assert fn([stmt(ok)], None, None) is None, f"附理由应过：{ok}"
        # 宁纵勿枉：rejected 显式「无」/空/缺键/无被否标签 -> 过（交 judge）
        assert fn([stmt("无")], None, None) is None, "显式「无」应过"
        assert fn([stmt("   ")], None, None) is None, "空白应过"
        assert (
            fn([{"text": "t", "type_label": "推荐", "boundary": "b"}], None, None)
            is None
        ), "无 fields 应过（宁纵勿枉）"
        assert fn(["not a dict"], None, None) is None, "非 dict 项应跳过"
        # 逐项扫描：第 2 项违规也须拒（非只看首项）
        err_second = fn(
            [stmt("候选B 被否——理由=净分 −2"), stmt("候选C 已被否")], None, None
        )
        assert err_second and "statements[1]" in err_second, "逐项扫描须拒第 2 项"

    # ---- plan:3 子3 framing 反转配套 mech（v2.110，无绑定能力残留跨步差集，
    # designs/plan3-sub3-gate-framing-design.md §3）----

    def test_p3s3_binding_residue_block_pass_skip(self, tmp_path):
        # S2 注册表①（子2 trace：反引号+（列表行）标注能力名 + 内置工具集/路径
        # 反引号 token 不得被误当注册表能力）
        import json as _json

        s2 = _json.dumps(
            {
                "kind": "skill-trace",
                "major_stage": "Plan",
                "minor_stage": "CapabilityToolSelection",
                "sub_step": 2,
                "q": ["能力注册表三通道清单如何？"],
                "a": [
                    "①skill 注册表：`factor-development`（列表行）、`factor-ic-"
                    "analyzer-workflow`（列表行）、`superpowers:test-driven-"
                    "development`（列表行）、`superpowers:systematic-debugging`"
                    "（列表行）、`andrej-karpathy-skills:karpathy-guidelines`"
                    "（列表行）、`workflow-creation`（列表行）。②工具/CLI/MCP="
                    "内置工具集（`Bash`/`Read`/`Edit`/`Write`）、codegraph CLI"
                    "（/home/admin/.npm-global/bin/codegraph）、MCP server"
                    "（tavily-search）。"
                ],
            },
            ensure_ascii=False,
        )
        _write_evidence(tmp_path, "t", [s2])
        # vio1 形态：绑定+不加载覆盖了除 factor-ic-analyzer-workflow 外全部
        qa_residue = [
            {
                "q": "最小集与双向追溯矩阵如何？",
                "a": (
                    "`factor-development`/`superpowers:test-driven-development`/"
                    "`andrej-karpathy-skills:karpathy-guidelines`/codegraph CLI "
                    "绑定需求；`superpowers:systematic-debugging`/`workflow-"
                    "creation`/MCP tavily-search 显式不加载。"
                ),
            }
        ]
        err = eng._check_binding_residue_trace(qa_residue, tmp_path, "t")
        assert err and "factor-ic-analyzer-workflow" in err and "残留" in err, (
            "丢 factor-ic-analyzer-workflow 应拒"
        )
        # 合法形态：全部覆盖（绑定或不加载）
        qa_ok = [
            {
                "q": "最小集与双向追溯矩阵如何？",
                "a": (
                    "`factor-development`/`superpowers:test-driven-development`/"
                    "`andrej-karpathy-skills:karpathy-guidelines`/codegraph CLI "
                    "绑定需求；`factor-ic-analyzer-workflow`/`superpowers:"
                    "systematic-debugging`/`workflow-creation`/MCP tavily-search "
                    "显式不加载。"
                ),
            }
        ]
        assert eng._check_binding_residue_trace(qa_ok, tmp_path, "t") is None, (
            "全覆盖应过"
        )
        # 宁纵勿枉：无 S2 -> 过（交 judge）
        assert (
            eng._check_binding_residue_trace(qa_residue, tmp_path, "no_such") is None
        ), "无 S2 应过"
        # 宁纵勿枉：S2 无反引号（列表行）标注能力名（提取不出集）-> 过
        s2_noann = _json.dumps(
            {
                "kind": "skill-trace",
                "major_stage": "Plan",
                "minor_stage": "CapabilityToolSelection",
                "sub_step": 2,
                "q": ["能力注册表如何？"],
                "a": ["①skill 注册表：factor-development（列表行）。"],
            },
            ensure_ascii=False,
        )
        _write_evidence(tmp_path, "t2", [s2_noann])
        assert eng._check_binding_residue_trace(qa_residue, tmp_path, "t2") is None, (
            "S2 无反引号（列表行）能力名应过"
        )

    # ---- plan:3 子5 framing 反转配套 mech（v2.117，不加载清单丢失 + 假设传导
    # 丢失/淡化，出席型跨步负判定，designs/plan3-sub5-gate-framing-design.md §3）----

    def test_p3s5_no_load_trace_block_pass_skip(self, tmp_path):
        import json as _json

        # 子3 trace（最小集显式不加载清单 4 条）
        s3 = _json.dumps(
            {
                "kind": "skill-trace",
                "major_stage": "Plan",
                "minor_stage": "CapabilityToolSelection",
                "sub_step": 3,
                "q": ["最小集与显式不加载清单如何？"],
                "a": [
                    "最小集：显式不加载清单=`factor-ic-analyzer-workflow`"
                    "（无 pipeline 落库需求）、`workflow-creation`（不建工作流）、"
                    "`superpowers:systematic-debugging`（条件触发）、MCP "
                    "`tavily-search`（无外部检索需求）。"
                ],
            },
            ensure_ascii=False,
        )
        _write_evidence(tmp_path, "t", [s3])

        def stmt(text, no_load="无"):
            return {
                "text": text,
                "type_label": "skill",
                "boundary": "b",
                "fields": {
                    "skill_first": text,
                    "tools": "无",
                    "enforce_align": "无",
                    "subagent_policy": "无",
                    "no_load": no_load,
                },
            }

        # vio4 形态：删不加载项，全包无任一不加载清单条目名
        stmts_miss = [stmt("必先 invoke `factor-development` skill")]
        err = eng._check_no_load_trace(stmts_miss, tmp_path, "t")
        assert (
            err and "不加载清单丢失" in err and "factor-ic-analyzer-workflow" in err
        ), "清单全丢应拒"
        # 部分丢：只缺 workflow-creation
        stmts_partial = [
            stmt(
                "不加载 `factor-ic-analyzer-workflow`、"
                "`superpowers:systematic-debugging`、MCP `tavily-search`"
            )
        ]
        err_p = eng._check_no_load_trace(stmts_partial, tmp_path, "t")
        assert err_p and "workflow-creation" in err_p, "缺 workflow-creation 应拒"
        # 合法形态：清单在 text 出现（合并一条）
        stmts_ok = [
            stmt(
                "不加载 `factor-ic-analyzer-workflow`、`workflow-creation`、"
                "`superpowers:systematic-debugging`、MCP `tavily-search`"
            )
        ]
        assert eng._check_no_load_trace(stmts_ok, tmp_path, "t") is None, (
            "全条目在 text 应过"
        )
        # 合法形态：清单在 no_load 字段
        stmts_field = [
            stmt(
                "t",
                no_load="`factor-ic-analyzer-workflow`、`workflow-creation`、"
                "`superpowers:systematic-debugging`、MCP `tavily-search`",
            )
        ]
        assert eng._check_no_load_trace(stmts_field, tmp_path, "t") is None, (
            "全条目在 no_load 字段应过"
        )
        # 宁纵勿枉：无子3 -> 过（交 judge）
        assert eng._check_no_load_trace(stmts_miss, tmp_path, "no_such") is None, (
            "无子3 应过"
        )
        # 宁纵勿枉：子3 无「不加载清单」字样（确无清单）-> 过
        s3_nolist = _json.dumps(
            {
                "kind": "skill-trace",
                "major_stage": "Plan",
                "minor_stage": "CapabilityToolSelection",
                "sub_step": 3,
                "q": ["最小集如何？"],
                "a": ["最小集：全部绑定，无不加载项。"],
            },
            ensure_ascii=False,
        )
        _write_evidence(tmp_path, "t2", [s3_nolist])
        assert eng._check_no_load_trace(stmts_miss, tmp_path, "t2") is None, (
            "子3 无清单字样应过"
        )

    def test_p3s5_assumption_propagation_block_pass_skip(self, tmp_path):
        import json as _json

        # 子4 trace（B3 假设项：置信度高×影响低）
        s4 = _json.dumps(
            {
                "kind": "skill-trace",
                "major_stage": "Plan",
                "minor_stage": "CapabilityToolSelection",
                "sub_step": 4,
                "q": ["B3 核验留痕？三态标注？", "假设项汇总？"],
                "a": [
                    "B3 `andrej-karpathy-skills:karpathy-guidelines` 核验：①条目存在"
                    "--列表行在册。三态：一项假设--该 plugin skill 磁盘 SKILL.md 路径"
                    "未逐一 ls 核实（置信度高×影响低：错误时 Skill 调用当场报错）。",
                    "假设项汇总：一条（B3 plugin skill 磁盘路径未逐一核实，置信度高"
                    "×影响低，见 a1）。证伪项：无。",
                ],
            },
            ensure_ascii=False,
        )
        _write_evidence(tmp_path, "t", [s4])

        def stmt(boundary):
            return {
                "text": "遵循 karpathy-guidelines 行为约束",
                "type_label": "skill",
                "boundary": boundary,
                "fields": {
                    "skill_first": "`andrej-karpathy-skills:karpathy-guidelines`",
                    "tools": "无",
                    "enforce_align": "无",
                    "subagent_policy": "无",
                    "no_load": "无",
                },
            }

        # vio5 形态：假设淡化成「已确认无风险」（无置信度/影响词形）
        err = eng._check_assumption_propagation_trace(
            [stmt("该 skill 可用性已确认无风险")], tmp_path, "t"
        )
        assert err and "假设传导丢失" in err, "淡化成已确认无风险应拒"
        # 合法形态：boundary 原样携带置信度×影响
        assert (
            eng._check_assumption_propagation_trace(
                [stmt("假设传导=磁盘 SKILL.md 未逐一核实（置信度高×影响低）")],
                tmp_path,
                "t",
            )
            is None
        ), "原样携带置信度×影响应过"
        # 合法形态：语义等价转述仍含「影响」词形
        assert (
            eng._check_assumption_propagation_trace(
                [stmt("假设：磁盘路径未核实，影响低")], tmp_path, "t"
            )
            is None
        ), "含「影响」词形应过"
        # 宁纵勿枉：无子4 -> 过
        assert (
            eng._check_assumption_propagation_trace(
                [stmt("已确认无风险")], tmp_path, "no_such"
            )
            is None
        ), "无子4 应过"
        # 宁纵勿枉：子4 无假设标签（确无假设）-> 过
        s4_noasm = _json.dumps(
            {
                "kind": "skill-trace",
                "major_stage": "Plan",
                "minor_stage": "CapabilityToolSelection",
                "sub_step": 4,
                "q": ["B3 核验？"],
                "a": ["B3 核验：全部已验证，无假设项。"],
            },
            ensure_ascii=False,
        )
        _write_evidence(tmp_path, "t2", [s4_noasm])
        assert (
            eng._check_assumption_propagation_trace(
                [stmt("已确认无风险")], tmp_path, "t2"
            )
            is None
        ), "子4 无假设标签应过"

    # ---- plan:1 子3 framing 反转配套 mech（v2.103，可行性验证五项核验留痕扫描，
    # designs/plan1-sub3-gate-framing-design.md §3）----

    def test_p1s3_feasibility_block_forms(self):
        # vio5 缺⑤ / vio1 ①段裸存在断言 / vio4 ②段无查询「需新建」——词形取
        # replay_plan1_sub3 真实载荷逐字，生产墙零方差当场拒
        qa_missing = [
            {
                "q": "候选B 的五项核验结果与三态标注如何？",
                "a": "①存在性——新文件无需存在性核实；依赖 paths.py:78 SUMMARY_RESULT "
                "经 Read 核实在场。②重复造轮子——codegraph 查询 scripts/ 下同功能脚本，"
                "返回 7 个无一做八维度分组汇总，无重复。③影响面——codegraph impact "
                "不适用（新文件无 callers），影响面=新增读侧。④硬规则——符合 H1/H7/H9。"
                "三态标注：假设（置信度：中——注册机制未核实；错误时影响：需手工触发）。",
            }
        ]
        err = eng._check_feasibility_verification_trace(qa_missing)
        assert err and "缺项" in err and "可测试性" in err
        # p1-sub3-cost 修1：报错文案携带组织形态指引（报错即返工指令——
        # B1 轮模型按核验项拆 q 七连拒实证）。
        assert "每候选一对" in err
        qa_bare_exist = [
            {
                "q": "候选A 的五项核验结果与三态标注如何？",
                "a": "①存在性——经核实，generate_factor_summary_report.py 的聚合统计函数"
                "与 FACTOR_CATEGORIES 映射均存在，可直接复用，SUMMARY_RESULT 落盘路径也在场。"
                "②重复造轮子——codegraph 查询「category 分组统计」返回 0 个同功能实现，无重复。"
                "③影响面——codegraph impact 返回 callers 2 个（a.py:203、b.py:658）。"
                "④硬规则——符合 H1/H7/H9。⑤可测试性——tests/test_x.py:35 有夹具。"
                "三态标注：可行。",
            }
        ]
        err2 = eng._check_feasibility_verification_trace(qa_bare_exist)
        assert err2 and "编造" in err2
        qa_no_query = [
            {
                "q": "候选B 的五项核验结果与三态标注如何？",
                "a": "①存在性——新文件无需存在性核实。②重复造轮子——摘要统计需求特殊，"
                "仓库里不会有现成的同功能实现，需新建脚本。③影响面——codegraph impact "
                "不适用（新文件无 callers）。④硬规则——符合 H1/H8/H9。"
                "⑤可测试性——可挂 tests/test_y.py 新夹具。三态标注：可行。",
            }
        ]
        err3 = eng._check_feasibility_verification_trace(qa_no_query)
        assert err3 and "漏检" in err3

    def test_p1s3_feasibility_pass_forms(self):
        # 合法形态全过（词形取 replay clean 载荷）：file:line+工具动词 /
        # 新文件无需存在性核实 / 空结果查询留痕 / 「不适用+原因」替代
        pass_forms = [
            "①存在性——codegraph nodes 查得聚合统计函数于 summary/generate_factor_summary_report.py:112，"
            "Read 核实 112-158 行。②重复造轮子——codegraph 查询「category 分组统计」同功能实现，"
            "返回 0 个，无重复。③影响面——codegraph impact 返回受影响 callers 2 个"
            "（generate_factor_summary_report.py:203、run_pipeline.py:658），不改签名时调用方零改动。"
            "④硬规则——符合 H1/H7/H9，H11-H13 不触及。⑤可测试性——tests/test_x.py:35 有夹具。"
            "三态标注：可行（出处如上）。",
            "①存在性——新文件无需存在性核实；其依赖 factor_definitions.py:41 FACTOR_CATEGORIES "
            "经 Read 核实在场。②重复造轮子——codegraph 查询 scripts/ 下同功能脚本，返回 7 个"
            "无一做八维度分组汇总，无重复。③影响面——codegraph impact 不适用（新文件无 callers），"
            "影响面=新增消费 factor_ic_data.json.gz 的读侧。④硬规则——符合 H1/H8/H9。"
            "⑤可测试性——可挂 tests/test_y.py 新夹具。"
            "三态标注：假设（置信度：中——注册机制未核实；错误时影响：需手工触发）。",
            "①存在性——不适用（纯配置项调整，无既有符号引用）。②重复造轮子——Grep 搜索 "
            "「分组统计」返回 0 个同功能实现，无重复。③影响面——codegraph callers 返回 0 个调用方。"
            "④硬规则——符合 H9。⑤可测试性——接缝在 tests/test_z.py:12。三态标注：可行。",
        ]
        for form in pass_forms:
            qa = [{"q": "候选X 的五项核验结果与三态标注如何？", "a": form}]
            assert eng._check_feasibility_verification_trace(qa) is None, form[:40]

    def test_p1s3_feasibility_skip_rules(self):
        # 宁纵勿枉：无圈码结构的散述不扫（交 judge 方框兜底）；
        # ①段无断言词（全部新增）不拦
        assert (
            eng._check_feasibility_verification_trace(
                [{"q": "总结？", "a": "三候选均完成五项核验，影响面各异。"}]
            )
            is None
        )
        assert (
            eng._check_feasibility_verification_trace(
                [
                    {
                        "q": "候选D 的五项核验结果与三态标注如何？",
                        "a": "①存在性——本候选不引用既有符号，全部新增。②重复造轮子——"
                        "codegraph 查询「维度分组」返回 0 个同功能实现，无重复。"
                        "③影响面——codegraph impact 返回 callers 0 个。④硬规则——符合 H9。"
                        "⑤可测试性——可挂新夹具。三态标注：可行。",
                    }
                ]
            )
            is None
        )

    # ---- plan:1 子4 framing 反转配套 mech（v2.103，跨项聚合下沉，
    # designs/p1-sub4-gate-framing-design.md §3.2）----

    def test_p1s4_forward_coverage_block_form(self):
        # vio4 形态：自述 must={G1,G2}，forward 只给 G1 承接 = 生产墙当场拒
        qa = [
            {
                "q": "双向追溯两向逐项结果如何？",
                "a": "backward——要素「条数聚合」→G1；要素「区块呈现」→G1。"
                "forward——G1←「条数聚合」+「区块呈现」两要素承接。"
                "自述 must 目标集={G1,G2}。",
            }
        ]
        err = eng._check_pugh_traceability_forward_coverage(qa)
        assert err and "G2" in err and "承接" in err

    def test_p1s4_forward_coverage_pass_forms(self):
        # 合法形态全过：承接词形四变体（←/<-/由/承接），且与段落顺序无关
        pass_forms = [
            "forward——G1←要素一承接；G2←要素三承接。自述 must={G1,G2}。",
            "自述 must={G1,G2}。forward——G1 由要素一承接；G2 由要素三承接。",
            "forward——G1<-要素一；G2<-要素三。",
            "forward——G1 与 G2 各由一个要素承接：G1 承接自要素一，G2 承接自要素三。",
        ]
        for form in pass_forms:
            qa = [{"q": "双向追溯结果？", "a": form}]
            assert eng._check_pugh_traceability_forward_coverage(qa) is None, form

    def test_p1s4_forward_coverage_skip_rules(self):
        # 宁纵勿枉：无追溯题不扫；无 G 标签（②式无目标标签表述）不扫
        assert (
            eng._check_pugh_traceability_forward_coverage(
                [{"q": "矩阵逐格评分如何？", "a": "候选B：改动面 −（2 文件 60 行）。"}]
            )
            is None
        )
        assert (
            eng._check_pugh_traceability_forward_coverage(
                [{"q": "双向追溯结果？", "a": "两向逐项均无漏，要素与目标一一对应。"}]
            )
            is None
        )

    def test_p1s4_net_score_block_form(self):
        # vio5 形态：候选B 逐格 1+/3−/2S 却声明净分 +3 = 生产墙当场拒
        qa = [
            {
                "q": "Pugh 矩阵逐格评分与理由？",
                "a": "候选B：验收包承接度 S（无差异）；改动面 −（2 文件 60 行）；"
                "影响面 S（同 3 符号）；复用度 −（不复用既有）；"
                "可测试性 +（纯函数）；硬规则兼容 −（触发 H8）。净分 +3。",
            }
        ]
        err = eng._check_pugh_net_score_consistency(qa)
        assert err and "候选B" in err and "净分" in err

    def test_p1s4_net_score_pass_and_skip(self):
        # 合法形态：计数与净分自洽（S 计 0 不进净分）；datum 无净分数值 -> 跳过
        qa_ok = [
            {
                "q": "Pugh 矩阵逐格评分与理由？",
                "a": "候选B：验收包承接度 S（无差异）；改动面 −（2 文件 60 行）；"
                "影响面 S（同 3 符号）；复用度 −（不复用既有）；"
                "可测试性 +（纯函数）；硬规则兼容 −（触发 H8）。净分 −2。",
            }
        ]
        assert eng._check_pugh_net_score_consistency(qa_ok) is None
        assert (
            eng._check_pugh_net_score_consistency(
                [{"q": "矩阵？", "a": "候选A=datum 全 S，其余候选与其对照。"}]
            )
            is None
        )

    # ---- 占位符全局机械拒 ----

    def test_replay_u1s4_placeholder_in_purpose_blocked(self, tmp_path):
        # 子4 att1 真实形态：红队未归先提交，purpose 含「进行中」
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=4)
        qa = [{"q": "三关质检", "a": "E1 针对/独立/可追溯 全过（formatters.py:92）"}]
        (tmp_path / "payload.json").write_text(
            json.dumps(
                {
                    "purpose": "子步骤4=质检裁决（进行中：先做三关质检逐条，红队到达后追加原文）",
                    "qa": qa,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "进行中" in msg and "完成记录" in msg

    def test_placeholder_scan_covers_qa_content(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=3)
        qa = [{"q": "五层源留痕", "a": "GitHub API 结果待补"}]
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "qa": qa}, ensure_ascii=False), encoding="utf-8"
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "待补" in msg

    def test_placeholder_scan_covers_statements(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=5)
        item = {
            "text": "web_ui 分层回测页默认参数下年化显示 +9963.0%",
            "type_label": "证实",
            "boundary": "TODO",
            "fields": {"confidence": "高"},
        }
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "statements": [item]}, ensure_ascii=False),
            encoding="utf-8",
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "TODO" in msg

    # ---- 子1 结论字段化 ----

    def test_u1s1_missing_conclusion_blocked(self, tmp_path):
        # 子1 att1 真实形态：产物仅 q/a，无结论二选一
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        qa = [
            {
                "q": "who=当前提问者身份？",
                "a": "用户原话：「项目维护者」（本会话回答选项）",
            },
            {"q": "pain 具体观察=？", "a": "用户原话：「分层回测页 + 默认参数」"},
        ]
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "qa": qa}, ensure_ascii=False), encoding="utf-8"
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "结论" in msg and "①" in msg

    def test_u1s1_conclusion_bad_prefix_blocked(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        (tmp_path / "payload.json").write_text(
            json.dumps(
                {
                    "purpose": "p",
                    "qa": [{"q": "who", "a": "用户原话：「项目维护者」"}],
                    "结论": "问题成立：主语=项目维护者",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "①" in msg and "②" in msg

    def test_u1s1_conclusion_accepted_into_record(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        (tmp_path / "payload.json").write_text(
            json.dumps(
                {
                    "purpose": "p",
                    "qa": [{"q": "who", "a": "用户原话：「项目维护者」"}],
                    "结论": "①问题成立：主语=项目维护者；可观察痛点=年化显示 9963.0%（用户原话）",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert ok, msg
        rec = json.loads(
            (tmp_path / ".claude" / "evidence" / "t.jsonl")
            .read_text(encoding="utf-8")
            .strip()
        )
        assert rec["结论"].startswith("①")

    # ---- v2.54：结论禁推测形态（conclusion_no_speculation，u:1 子1）----
    # 2026-08-02 tail_volume_acceleration_annualized u:1 子1 att1：who 项
    # 写得合规（模型知道「仓库事实不能证明提问者身份」），顶层结论却写
    # 「具体主语 = 项目维护者（推测，来源未自述身份 + CLAUDE.md §6 +
    # 分支命名佐证）」——规则钉在 q/a 项，结论字段成漏网面。词形取 att1
    # 逐字，重放两侧：att1 拒 / att2 放行。

    def test_replay_u1s1_att1_conclusion_speculation_rejected(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        (tmp_path / "payload.json").write_text(
            json.dumps(
                {
                    "purpose": "p",
                    "qa": [{"q": "who=当前提问者身份？", "a": "未自述身份。"}],
                    "结论": "①问题成立（可证伪定义）。具体主语 = 项目维护者"
                    "（推测，来源未自述身份 + CLAUDE.md §6 + 当前分支命名佐证）。",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "推测" in msg and "未自述身份" in msg

    def test_replay_u1s1_att2_conclusion_clean_accepted(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        (tmp_path / "payload.json").write_text(
            json.dumps(
                {
                    "purpose": "p",
                    "qa": [{"q": "who=当前提问者身份？", "a": "未自述身份。"}],
                    "结论": "①问题成立（可证伪定义）。具体主语 = 未自述身份"
                    "（who=未自述）。",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert ok, msg

    def test_conclusion_no_speculation_unit(self):
        fn = eng._MECH_EXTRA_STR_CHECKS["conclusion_no_speculation"]
        assert fn("①问题成立。具体主语 = 项目维护者（推测，来源…）。") is not None
        assert fn("①问题成立。具体主语 = 未自述身份（who=未自述）。") is None
        # q/a 项里「推测另列」是合法形态——本校验只锚结论字段，不扫 qa
        assert fn("②问题不成立（用户声明无真实痛点，原话佐证）。") is None

    def test_extra_keys_leak_check_not_triggered(self, tmp_path):
        # extra_payload_keys 声明的键不是结构字段泄漏（kind/sub_step 等仍拒）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        (tmp_path / "payload.json").write_text(
            json.dumps(
                {
                    "purpose": "p",
                    "qa": [{"q": "who", "a": "用户原话"}],
                    "结论": "①问题成立：X",
                    "sub_step": 1,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "结构字段" in msg

    # ---- v2.51：原话标注通道（user_quote_channel，u:1 子1）----
    # 2026-08-02 tail_volume_acceleration_annualized u:1 子1 三连 block：
    # 用户全程只点选项（transcript 实证零打字原话），judge 按「who 只认
    # 用户自述」临场发明「原话全文引用」要件——模型被要求引用物理不
    # 存在的东西（§3.5 #7 佐证无合法获取路径 + #4 裁量点未钉死）。
    # 三轮真实违规字面：att1「（本会话 AskUserQuestion 回答）」、att2
    # 「第一轮回答」、att3「用户回答原话全文引用，怀疑点 Q 选项 A」——
    # 共同形态=「原话」声称 + AskUserQuestion 出处 + 无通道标注；
    # 选项标签标「原话」=标注失真（声称的佐证等级高于实际）。

    def test_replay_u1s1_att1_bare_askq_annotation_blocked(self):
        # att1 逐字：「原话」声称 + AskUserQuestion 出处，无通道标注
        qa = [
            {
                "q": "who=当前提问者身份？",
                "a": "用户原话：「我是项目唯一维护者」（本会话 AskUserQuestion 回答）。"
                "仓库事实 git user=Dl848391784 仅证明仓库由谁维护，不证明当前提问者"
                "就是那个人——本步仅认用户自述。",
            },
        ]
        err = eng._check_user_quote_channel(qa)
        assert err is not None and "通道" in err

    def test_replay_u1s1_att3_option_labeled_as_quote_blocked(self):
        # att3 逐字：选项标签标成「用户回答原话全文引用」（含 Q 选项 A 自披露）
        qa = [
            {
                "q": "pain-1=用户怀疑点 1（量级）？",
                "a": "用户原话全文：「数字量级本身不合理」（本会话 AskUserQuestion "
                "第一轮用户回答原话全文引用，怀疑点 Q 选项 A）。",
            },
        ]
        err = eng._check_user_quote_channel(qa)
        assert err is not None and "通道" in err

    def test_quote_claim_with_selected_mislabel_blocked(self):
        # 标注失真：选中标签标成「原话」——声称的佐证等级高于实际
        qa = [
            {
                "q": "who=当前提问者身份？",
                "a": "用户原话：「我是项目唯一维护者」（AskUserQuestion 选中）。",
            },
        ]
        err = eng._check_user_quote_channel(qa)
        assert err is not None and "失真" in err

    def test_option_label_with_selected_annotation_accepted(self):
        # 合法形态②：选中标签全文+「（AskUserQuestion 选中）」=会话事实级
        # 自述（不声称「原话」）
        qa = [
            {
                "q": "who=当前提问者身份？",
                "a": "「我是项目唯一维护者」（AskUserQuestion 选中）。",
            },
        ]
        assert eng._check_user_quote_channel(qa) is None

    def test_quote_with_free_input_accepted(self):
        # 合法形态①：打字原话标自由输入（真值归 judge/用户，mech 只判标注形态）
        qa = [
            {
                "q": "who=当前提问者身份？",
                "a": "用户原话：「这个项目就我一个人维护」（AskUserQuestion 自由输入）。",
            },
        ]
        assert eng._check_user_quote_channel(qa) is None

    def test_direct_dialogue_quote_accepted(self):
        # 直接对话原话（无 AskUserQuestion 出处声称）不涉通道——不拦
        qa = [
            {
                "q": "who=当前提问者身份？",
                "a": "用户原话：「这项目就我一个人在维护」（首轮对话）。",
            },
        ]
        assert eng._check_user_quote_channel(qa) is None

    def test_bare_askq_without_quote_claim_accepted(self):
        # 无「原话」声称的 AskUserQuestion 引用——未声称不判（宁纵勿枉）
        qa = [
            {
                "q": "why-now=产出？",
                "a": "答案：修代码（本会话 AskUserQuestion 回答）。",
            },
        ]
        assert eng._check_user_quote_channel(qa) is None

    def test_append_trace_u1s1_quote_channel_integration(self, tmp_path):
        # 管道集成：u:1 子1 mech_checks 挂载生效（att1 形态全载荷当场拒）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        (tmp_path / "payload.json").write_text(
            json.dumps(
                {
                    "purpose": "p",
                    "qa": [
                        {
                            "q": "who=当前提问者身份？",
                            "a": "用户原话：「我是项目唯一维护者」"
                            "（本会话 AskUserQuestion 回答）。",
                        }
                    ],
                    "结论": "①问题成立：主语=项目维护者",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "通道" in msg

    # ---- v2.52：claim 词扩面（自述）+ 标签锚定 + judge 抗已修还判 ----
    # 2026-08-02 晚第二集：模型换「自述」绕开 v2.51 的「原话」词表（新 att1
    # 「用户自述「项目维护者」（AskUserQuestion 选中选项标签全文）」），judge
    # 按失真判对（但规则文本自己把选中叫「合法自述」=判词与文本矛盾，§3.5
    # #23 修文本撤词）；新 att2 按 att1 判词范例改干净后 judge 仍照 att1
    # 判词描述 block（「已修还判」第二实例——判词描述的文本本轮已不存在）。

    def test_replay_u1s1_0802b_att1_zishu_mislabel_blocked(self):
        # 新 att1 逐字：「自述」前缀 + 选中标签 = 换词版标注失真
        qa = [
            {
                "q": "who=你和这个项目的关系是？",
                "a": "用户自述「项目维护者」（AskUserQuestion 选中选项标签全文，"
                "属会话事实级佐证）。事实并非来自仓库事实。",
            },
        ]
        err = eng._check_user_quote_channel(qa)
        assert err is not None and "失真" in err

    def test_zishu_meta_discussion_not_claim_accepted(self):
        # FP 守卫：「自述」出现在元讨论（非标签+引用形态）不拦——
        # 「本步仅认用户自述。」的自述后无引用冒号/引号
        qa = [
            {
                "q": "who=当前提问者身份？",
                "a": "「我是项目唯一维护者」（AskUserQuestion 选中）。"
                "仓库事实仅证明归属——本步仅认用户自述。",
            },
        ]
        assert eng._check_user_quote_channel(qa) is None

    def test_replay_u1s1_0802b_att2_clean_selected_accepted(self):
        # 新 att2 逐字：按判词范例改干净的形态（无前缀词，选中标注）——
        # mech 必须放行（judge 已修还判是判侧问题，写侧不能跟着错）
        qa = [
            {
                "q": "who=你和这个项目的关系是？",
                "a": "项目维护者（AskUserQuestion 选中选项标签全文，AskUserQuestion 选中）",
            },
            {
                "q": "trigger=什么时候注意到的？",
                "a": "今天刚打开 web_ui 看到（AskUserQuestion 选中选项标签全文，"
                "AskUserQuestion 选中）",
            },
        ]
        assert eng._check_user_quote_channel(qa) is None

    def test_append_trace_u1s1_zishu_integration(self, tmp_path):
        # 管道集成：「自述」换词形态经 append-trace 当场拒
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        (tmp_path / "payload.json").write_text(
            json.dumps(
                {
                    "purpose": "p",
                    "qa": [
                        {
                            "q": "who=你和这个项目的关系是？",
                            "a": "用户自述「项目维护者」（AskUserQuestion "
                            "选中选项标签全文，属会话事实级佐证）。",
                        }
                    ],
                    "结论": "①问题成立：主语=项目维护者",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "失真" in msg

    # ---- FP 面：无 mech_checks 声明的步不受链环扫描影响 ----

    def test_causal_scan_only_where_declared(self, tmp_path):
        # 子5 未声明 causal_ring_no_untested——含「未实测/可能」字样不受禁词扫描
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=5)
        qa = [
            {
                "q": "原子 A 四态裁决",
                "a": "部分成立：证据 Q76007 支持但未实测全窗口，置信度中",
            }
        ]
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "qa": qa}, ensure_ascii=False), encoding="utf-8"
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert ok, msg


class TestFetchPrompt:
    """v2.38 fetch-prompt：外部取证卸子代理，主会话只收蒸馏报告。

    对齐 redteam-prompt 模式（证据+纪律归脚本，Agent 调用归模型）；
    命令模板逐字来自 2026-08-01 本机诊断（arXiv https+UA / GitHub 认证头 /
    SE withbody 替页面 / WebFetch 环境性弃用）。
    """

    def _write_step2_trace(self, tmp_path):
        rec = json.dumps(
            {
                "kind": "skill-trace",
                "major_stage": "Understand",
                "minor_stage": "ProblemContext",
                "sub_step": 2,
                "skill": "causal-inference-root-cause",
                "purpose": "p",
                "q": ["原子问题清单"],
                "a": ["原子A=数值正确性（年化 9963%）；原子B=展示精度（整百带 .0）"],
            },
            ensure_ascii=False,
        )
        _write_evidence(tmp_path, "t", [rec])

    def test_contains_atoms_templates_contract(self, tmp_path):
        self._write_step2_trace(tmp_path)
        prompt = eng.fetch_prompt(tmp_path, "t")
        assert prompt is not None
        # 原子清单嵌入
        assert "原子A=数值正确性" in prompt
        # 命令模板（本机验证过的逐字要点）
        assert "https://export.arxiv.org/api/query" in prompt
        assert "Mozilla/5.0 (research)" in prompt
        assert "Authorization: Bearer $GITHUB_TOKEN" in prompt
        assert "filter=withbody" in prompt
        assert "-m 25" in prompt
        # 纪律
        assert "禁 WebFetch" in prompt
        assert "单层" in prompt and "不写 evidence" in prompt
        assert "不裁决" in prompt
        assert "未取证+原因" in prompt
        # 返回契约（蒸馏 + 反证先支持后）
        assert "反证查询（先）" in prompt and "支持证据（后）" in prompt
        assert "五层状态表" in prompt
        assert "≤120 行" in prompt
        # claim 补充区
        assert "claim 补充区" in prompt

    def test_no_step2_trace_returns_none(self, tmp_path):
        _write_evidence(tmp_path, "t", [_trace_line(1)])
        assert eng.fetch_prompt(tmp_path, "t") is None

    def test_goals_and_value_step2_not_counted(self, tmp_path):
        # minor_stage 限定 ProblemContext（跨节点串号防御，同 redteam_prompt）
        rec = json.dumps(
            {
                "kind": "skill-trace",
                "major_stage": "Understand",
                "minor_stage": "GoalsAndValue",
                "sub_step": 2,
                "skill": "s",
                "purpose": "p",
                "q": ["q"],
                "a": ["a"],
            },
            ensure_ascii=False,
        )
        _write_evidence(tmp_path, "t", [rec])
        assert eng.fetch_prompt(tmp_path, "t") is None


class TestFetchPromptOut:
    """v2.42 fetch-prompt --out：骨架落盘 per-workflow 目录，归属钉死。

    此前 engine 只输出 stdout，落盘路径由模型自选——tail_volume 实例选了
    共享 .claude/evidence/fetch-prompt-skeleton.md：文件名无工作流归属、
    下一个工作流覆盖上一轮的留痕、残留旧 trace 误导后续会话。--out 让
    engine 把骨架写到 .claude/workflows/<name>/（与 state.json/cc_debug.log
    同目录同生命周期）并打印路径，路径不再由模型决定。
    """

    def _write_step2_trace(self, tmp_path):
        rec = json.dumps(
            {
                "kind": "skill-trace",
                "major_stage": "Understand",
                "minor_stage": "ProblemContext",
                "sub_step": 2,
                "skill": "causal-inference-root-cause",
                "purpose": "p",
                "q": ["原子问题清单"],
                "a": ["原子A=数值正确性"],
            },
            ensure_ascii=False,
        )
        _write_evidence(tmp_path, "t", [rec])

    def _out_path(self, tmp_path) -> Path:
        return tmp_path / ".claude" / "workflows" / "t" / "fetch-prompt-skeleton.md"

    def test_out_writes_skeleton_to_workflow_dir(self, tmp_path, capsys):
        _init_git(tmp_path)
        self._write_step2_trace(tmp_path)
        rc = eng.main(["fetch-prompt", "t", "--out", "--cwd", str(tmp_path)])
        assert rc == 0
        out_path = self._out_path(tmp_path)
        assert str(out_path) in capsys.readouterr().out
        text = out_path.read_text(encoding="utf-8")
        assert "原子A=数值正确性" in text
        assert "五层状态表" in text
        assert "claim 补充区" in text

    def test_out_no_step2_trace_returns_1_and_no_file(self, tmp_path, capsys):
        _init_git(tmp_path)
        _write_evidence(tmp_path, "t", [_trace_line(1)])
        rc = eng.main(["fetch-prompt", "t", "--out", "--cwd", str(tmp_path)])
        assert rc == 1
        assert not self._out_path(tmp_path).exists()

    def test_no_out_keeps_stdout_and_writes_no_file(self, tmp_path, capsys):
        _init_git(tmp_path)
        self._write_step2_trace(tmp_path)
        rc = eng.main(["fetch-prompt", "t", "--cwd", str(tmp_path)])
        assert rc == 0
        assert "五层状态表" in capsys.readouterr().out
        assert not self._out_path(tmp_path).exists()


class TestFetchSkeletonOut:
    """v2.43 fetch_skeleton_out：子4 骨架 --out 落盘机械核验（EXISTS+新鲜度）。

    v2.42 把路径钉死 per-workflow 目录，但「模型是否真的用了 --out」仍靠
    文案——模型重定向 stdout 自选路径则形同虚设。下沉机械层（§8.3 产物门
    同范式）：骨架文件须存在于 .claude/workflows/<name>/ 且 mtime 不早于
    本节点 entered_at（残留防御；entered_at 不可考 -> 降级仅存在性，
    宁纵勿枉）。全 none 档短路消息同样经 --out 落盘，检查口径一致。
    plan-first 拆步后双向取证顺延为子4。
    """

    def _setup_sub4(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=4)
        qa = [
            {"q": "原子 A 可检验 claim", "a": "claim：X；证实：Y；证伪：Z"},
            {
                "q": "原子 A 子代理蒸馏报告（原文收录）",
                "a": "反证查询（先）：…；支持证据（后）：…；五层状态表：…",
            },
        ]
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "qa": qa}, ensure_ascii=False), encoding="utf-8"
        )

    def _skeleton_path(self, tmp_path) -> Path:
        return tmp_path / ".claude" / "workflows" / "t" / "fetch-prompt-skeleton.md"

    def test_missing_skeleton_blocked(self, tmp_path):
        self._setup_sub4(tmp_path)
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "骨架未落盘" in msg and "fetch-prompt --out" in msg

    def test_fresh_skeleton_passes(self, tmp_path):
        self._setup_sub4(tmp_path)
        self._skeleton_path(tmp_path).write_text("骨架", encoding="utf-8")
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert ok, msg

    def test_stale_skeleton_blocked(self, tmp_path):
        self._setup_sub4(tmp_path)
        self._skeleton_path(tmp_path).write_text("骨架", encoding="utf-8")
        st = eng.load_state(tmp_path, "t")
        st["history"] = [
            {
                "phase": "understand",
                "sub": 1,
                "entered_at": "2099-01-01T00:00:00",
                "exited_at": None,
                "via": "test",
            }
        ]
        eng.save_state(tmp_path, "t", st)
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "骨架陈旧" in msg

    def test_no_entered_at_degrades_to_existence(self, tmp_path):
        # 降级纪律（宁纵勿枉）：history 无 entered_at -> 仅存在性检查
        self._setup_sub4(tmp_path)
        self._skeleton_path(tmp_path).write_text("骨架", encoding="utf-8")
        st = eng.load_state(tmp_path, "t")
        assert not st["history"]  # _write_state_full 默认空 history
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert ok, msg


class TestFetchReportRecorded:
    """v2.38 fetch_report_recorded：子4 报告收录形式要件机械化。

    实证依据：v2.38 落地验证时 judge 重放旧形态（无报告项）被判 PASS——
    「报告原文收录」形式要件被 judge 裁量放过，故下沉机械层。
    plan-first 拆步后双向取证顺延为子4。
    """

    def test_missing_report_item_blocked(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=4)
        qa = [
            {"q": "原子 A 可检验 claim", "a": "claim：X；证实：Y；证伪：Z"},
            {"q": "原子 A 反证查询（先）", "a": "SE 0 items；HN 未取证+无相关"},
            {"q": "原子 A 支持证据（后）", "a": "Q76007（URL）直接针对谓词"},
        ]
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "qa": qa}, ensure_ascii=False), encoding="utf-8"
        )
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert not ok and "蒸馏报告" in msg and "fetch-prompt" in msg

    def test_report_item_present_accepted(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=4)
        qa = [
            {"q": "原子 A 可检验 claim", "a": "claim：X；证实：Y；证伪：Z"},
            {
                "q": "原子 A 子代理蒸馏报告（原文收录）",
                "a": "反证查询（先）：…；支持证据（后）：Q76007（URL）；五层状态表：…",
            },
            {"q": "codegraph 新鲜度", "a": "2026-07-22（>72h 已 sync）"},
        ]
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "qa": qa}, ensure_ascii=False), encoding="utf-8"
        )
        # v2.43 起子4 append-trace 前置：骨架 --out 落盘（本测试报告收录，
        # 骨架存在性是正交前置）
        (
            tmp_path / ".claude" / "workflows" / "t" / "fetch-prompt-skeleton.md"
        ).write_text("骨架", encoding="utf-8")
        ok, msg = eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))
        assert ok, msg


class TestRedteamReportRecorded:
    """v2.44 redteam_report_recorded：子5 红队输出原文收录机械核验（u:1 子5 专属）。

    实证（2026-08-02 tail_volume u:1 子4）：模型先撞占位符扫描（「待补」机械拒、
    判词已指路「等红队归位再提交」），改写措辞绕开扫描（「未归/仍在跑中」）
    仍提前提交 -> judge block（3.5min + 1 次 judge 白烧）。词表打地鼠无效，
    结构信号分隔度经全量历史 trace 重放验证（7 条真实子4 trace）：
    「task-id 出现 = 已派发」×「收录项标题含「红队」「原文收录」」——
    被 block 载荷 = 有 task-id 无收录项；通过载荷 = 两者皆有；
    未触发/未派发 = 无 task-id 放行交 judge（宁纵勿枉）。
    plan-first 拆步后质检裁决顺延为子5。
    """

    def _append_s5(self, tmp_path, qa):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=5)
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "qa": qa}, ensure_ascii=False), encoding="utf-8"
        )
        return eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))

    _DISPATCH_A = (
        "触发条件判定：verdict 决定大方向（指向 layered_backtest.py:655）"
        "——触发条件满足。红队派发：redteam-prompt 生成，Agent 工具单发起"
        "（task-id a5ca6ea271e5e937e）。"
    )

    def test_dispatched_not_recorded_blocked(self, tmp_path):
        # 真实被 block 载荷形态：已派发（含 task-id）无收录项
        qa = [
            {"q": "① 三关质检", "a": "E1 针对性 pass / 独立性 pass / 可追溯 pass"},
            {
                "q": "② 条件触发对抗复核（红队子代理）",
                "a": self._DISPATCH_A + "红队归位状态：未归。",
            },
            {"q": "③ 四态结论合成", "a": "初步 verdict：Q1 部分成立"},
        ]
        ok, msg = self._append_s5(tmp_path, qa)
        assert not ok and "红队" in msg and "原文收录" in msg

    def test_dispatched_and_recorded_accepted(self, tmp_path):
        # 真实通过载荷形态：收录项标题含「红队」「原文收录」
        qa = [
            {"q": "① 三关质检", "a": "E1 针对性 pass / 独立性 pass / 可追溯 pass"},
            {
                "q": "② 条件触发对抗复核（红队子代理）",
                "a": self._DISPATCH_A + "红队归位状态：已归位。",
            },
            {
                "q": "②.5 红队蒸馏报告原文收录（task-id a5ca6ea271e5e937e）",
                "a": "=== 红队蒸馏报告原文开始 ===\n总判断：…\nQ1 部分成立；推理链：E1 证实->收窄边界；置信度：中",
            },
            {"q": "③ 四态结论合成", "a": "按红队修订：Q1 部分成立"},
        ]
        ok, msg = self._append_s5(tmp_path, qa)
        assert ok, msg

    def test_not_triggered_accepted(self, tmp_path):
        # 合法双结论分支：未触发声明（无 task-id 可引）-> 交 judge 判真值
        qa = [
            {"q": "① 三关质检", "a": "E1 针对性 pass / 独立性 pass / 可追溯 pass"},
            {
                "q": "② 条件触发对抗复核（红队子代理）",
                "a": "触发条件判定：verdict 不影响大方向——触发条件不满足，未起红队。",
            },
            {"q": "③ 四态结论合成", "a": "Q1 部分成立，推理链…"},
        ]
        ok, msg = self._append_s5(tmp_path, qa)
        assert ok, msg

    def test_predispatch_worker_unrecorded_blocked(self, tmp_path):
        # u1-sub5-cost 修3 闭环：driver 预派发通道无 task-id 可引——
        # redteam_worker.json 在位 = 红队已派，无收录项提交 = 提前提交，当场拒
        # （否则 judge 被告知「形式要件已机械拦截」而放行 = 对抗复核缺席的洞）。
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=5)
        meta = tmp_path / ".claude" / "workflows" / "t"
        (meta / "redteam_worker.json").write_text(
            json.dumps({"pid": 999999, "started_at": "x", "prompt_sha1": "s"}),
            encoding="utf-8",
        )
        qa = [
            {"q": "① 三关质检", "a": "E1 针对性 pass"},
            {"q": "② 对抗复核", "a": "红队由 driver 预派发，与本步并行。"},
            {"q": "③ 四态结论合成", "a": "Q1 部分成立"},
        ]
        ok, msg = self._append_s5(tmp_path, qa)
        assert not ok and "预派发" in msg and "ingest-redteam" in msg

    def test_predispatch_recorded_accepted(self, tmp_path):
        # 预派发通道合法形态：worker.json 在位 + 收录项标题（无 task-id）→ 过
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=5)
        meta = tmp_path / ".claude" / "workflows" / "t"
        (meta / "redteam_worker.json").write_text(
            json.dumps({"pid": 999999, "started_at": "x", "prompt_sha1": "s"}),
            encoding="utf-8",
        )
        qa = [
            {"q": "① 三关质检", "a": "E1 针对性 pass"},
            {
                "q": "②.5 红队输出原文收录（driver 预派发）",
                "a": "verdict: 部分成立\n推理链：E1→收窄\n置信度：高",
            },
            {"q": "③ 四态结论合成", "a": "Q1 部分成立"},
        ]
        ok, msg = self._append_s5(tmp_path, qa)
        assert ok, msg


class TestRedteamThreePiece:
    """v2.83 redteam_three_piece：子5 红队收录项三件套完整性（verdict/推理链/置信度）。

    #4 vio1（红队转述冒充原文收录）在默认-PASS framing 下 judge 漏判（转述 vs
    原文语义判据方差大）；三件套缺失是词形可判部分，下沉 mech 零方差（#2 缺席
    断言同范式，§3.5 #13）。收录项 a 须含「推理链」「置信度」关键词；缺任一->拒。
    plan-first 拆步后质检裁决顺延为子5。
    """

    def _append_s5(self, tmp_path, qa):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=5)
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "qa": qa}, ensure_ascii=False), encoding="utf-8"
        )
        return eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))

    def test_three_piece_present_accepted(self, tmp_path):
        # 三件套齐全（verdict+推理链+置信度）-> 通过
        qa = [
            {"q": "① 三关质检", "a": "E1 针对性 pass"},
            {
                "q": "②.5 红队原文收录（task-id a5ca6ea271e5e937e）",
                "a": "verdict=部分成立；推理链：E1 证实->收窄边界；置信度：中",
            },
            {"q": "③ 四态结论合成", "a": "Q1 部分成立"},
        ]
        ok, msg = self._append_s5(tmp_path, qa)
        assert ok, msg

    def test_missing_piece_blocked(self, tmp_path):
        # 缺推理链/置信度（vio1 形态：概括转述冒充收录）-> 拒
        qa = [
            {"q": "① 三关质检", "a": "E1 针对性 pass"},
            {
                "q": "②.5 红队原文收录（task-id a5ca6ea271e5e937e）",
                "a": "红队复核后认同部分成立，建议收窄到方向取反口径边界，认为现有证据不足以证实行业成立做法",
            },
            {"q": "③ 四态结论合成", "a": "Q1 部分成立"},
        ]
        ok, msg = self._append_s5(tmp_path, qa)
        assert not ok and "推理链" in msg and "置信度" in msg

    def test_confidence_shorthand_accepted(self, tmp_path):
        # u1-sub5-cost 修2（200fb21a 轮真实被 block 载荷词形）：红队原文写
        # 「置信 95%」（模板未钉逐字标签时弱模型的自然简写）→ 不应再被字面
        # 「置信度」拦。词形取真实载荷逐字（v2.49 同范式）；转述冒充（双缺）
        # 维持 BLOCK 见 test_missing_piece_blocked。
        qa = [
            {"q": "① 三关质检", "a": "E1 针对性 pass"},
            {
                "q": "②.5 红队输出原文收录（task-id a538a700d0d5e496d）",
                "a": "## 原子A：部分成立\n**推理链（逐行点查证实双转结构）**"
                "……结构证实，置信 95%。",
            },
            {"q": "③ 四态结论合成", "a": "Q1 部分成立"},
        ]
        ok, msg = self._append_s5(tmp_path, qa)
        assert ok, msg

    def test_no_redteam_accepted(self, tmp_path):
        # 无红队收录项（未派发无 task-id）-> 交 judge 判真值（宁纵勿枉）
        qa = [
            {"q": "① 三关质检", "a": "E1 针对性 pass"},
            {"q": "② 对抗复核", "a": "触发条件不满足，未起红队"},
        ]
        ok, msg = self._append_s5(tmp_path, qa)
        assert ok, msg


class TestUserDecisionRecorded:
    """v2.45 user_decision_recorded：读回确认步的用户裁决记录机械校验。

    交接架构（designs/context-handoff-design.md §4）正确性前提：8 个读回步
    全部 gate=None（trace 存在即过，无 judge），用户裁决此前只承诺进对话
    ——/clear 换会话后新上下文只能从 trace 读裁决，漏记 = 重问用户或编造。
    分隔度：真实 u:1 子7（旧子6，裁决项 a=699 字）/u:2 子5（543 字）通过；
    「用户已确认」式空记录（<50 字）与无裁决项两形态拦截——margin 两个
    数量级，非调参数式阈值（§3.5 #15）。plan-first 拆步后读回顺延为子7。
    """

    def _append_readback(self, tmp_path, qa):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=7)
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "qa": qa}, ensure_ascii=False), encoding="utf-8"
        )
        return eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))

    def test_decision_item_present_accepted(self, tmp_path):
        # 真实 u:1 子7 形态：标题含「裁决」+ 逐项拍板内容
        qa = [
            {
                "q": "快答轮结果（用户对各 statement 认可）",
                "a": "S1 = 接受（用户原话已通过 AskUserQuestion 回答记录）；S2 = 接受",
            },
            {
                "q": "硬核裁决轮结果（用户选定本实例处理范围）",
                "a": "本实例拍板处理 = S1 + S2（验证 raw + 修展示层）。具体处理路径："
                "S1 直接读取分层回测 json 复核 raw 数值归因；S2 修展示层重复乘 100。",
            },
        ]
        ok, msg = self._append_readback(tmp_path, qa)
        assert ok, msg

    def test_missing_decision_item_blocked(self, tmp_path):
        qa = [
            {"q": "快答轮结果", "a": "S1 接受；S2 接受"},
            {"q": "本实例处理范围", "a": "S1 + S2，路径：读 json 复核 + 修展示层"},
        ]
        ok, msg = self._append_readback(tmp_path, qa)
        assert not ok and "裁决" in msg and "读回" in msg

    def test_empty_decision_record_blocked(self, tmp_path):
        # 标题在但内容空——「用户已确认」式记录交接后无法还原拍板内容
        qa = [
            {"q": "用户裁决", "a": "用户已确认。"},
            {"q": "快答轮结果", "a": "S1 接受；S2 接受"},
        ]
        ok, msg = self._append_readback(tmp_path, qa)
        assert not ok and "空记录" in msg


class TestHandoffPack:
    """v2.45 handoff_pack：/clear 交接包机械装配（context-handoff-design §3）。

    交接包 = 当前位置 + 当前节点已完成步最新 trace + 前序节点归一化/读回步
    最新 trace + 当前步最新 block 判词 + 产物清单（指针）。无任何 trace ->
    None（首次启动不注入）。
    """

    def _write_evidence(self, tmp_path, records):
        ev = tmp_path / ".claude" / "evidence"
        ev.mkdir(parents=True, exist_ok=True)
        with open(ev / "t.jsonl", "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def _trace(self, minor, step, marker):
        return {
            "kind": "skill-trace",
            "major_stage": "Understand",
            "minor_stage": minor,
            "sub_step": step,
            "skill": "s",
            "purpose": "p",
            "q": [f"q{marker}"],
            "a": [f"a{marker}"],
        }

    def test_first_launch_returns_none(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        assert eng.handoff_pack(tmp_path, "t") is None

    def test_pack_contents_and_trimming(self, tmp_path):
        # u:1 全 7 步 + u:2 子1-2（各含返工历史一条），当前 u:2 子3
        recs = []
        for step in range(1, 8):
            recs.append(self._trace("ProblemContext", step, f"_u1s{step}_old"))
            recs.append(self._trace("ProblemContext", step, f"_u1s{step}_new"))
        for step in (1, 2):
            recs.append(self._trace("GoalsAndValue", step, f"_u2s{step}"))
        recs.append(
            {
                "kind": "gate",
                "node": "understand:2",
                "phase": "understand",
                "sub": 2,
                "sub_step": 3,
                "gate": "blocked",
                "reason": "缺 X 条款",
                "ts": "2026-08-02T15:00:00",
            }
        )
        self._write_evidence(tmp_path, recs)
        _write_state_full(tmp_path, "t", "understand", 2, sub_step=3)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None
        # 当前位置
        assert "understand:2" in pack and "子步骤 3" in pack
        # 当前节点已完成步最新 trace（不含返工历史）
        assert "_u2s1" in pack and "_u2s2" in pack
        # 前序节点只带归一化（子6）+读回（子7）的最新 trace
        assert "_u1s6_new" in pack and "_u1s7_new" in pack
        assert "_u1s6_old" not in pack and "_u1s7_old" not in pack
        # 前序节点的中间步（子1-5）不进交接包
        for step in range(1, 6):
            assert f"_u1s{step}_new" not in pack
        # 当前步最新 block 判词
        assert "缺 X 条款" in pack


class TestHandoffPackSlim:
    """v4 P1-1 交接包瘦身（v4-cost-latency-optimization-design §2）：
    机械字段全剥（本节点+前序）；前序节点 q/boundary 截断、用户裁决 a 保全文；
    附 evidence 指针。真源 trace 不动（证据不丢，只压包内呈现）。"""

    def _write_evidence(self, tmp_path, records):
        ev = tmp_path / ".claude" / "evidence"
        ev.mkdir(parents=True, exist_ok=True)
        with open(ev / "t.jsonl", "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def test_slim_behavior(self, tmp_path):
        long_boundary = "B" * 300
        long_q = "读回标题" + "Q" * 200
        recs = [
            # 前序节点 u:1 归一化步（statements 带长 boundary）+ 读回步（长 q + 裁决 a）
            {
                "kind": "skill-trace",
                "major_stage": "Understand",
                "minor_stage": "ProblemContext",
                "sub_step": 6,
                "skill": "s_marker",
                "purpose": "purpose_marker",
                "statements": [
                    {"text": "结论甲", "type_label": "must", "boundary": long_boundary}
                ],
            },
            {
                "kind": "skill-trace",
                "major_stage": "Understand",
                "minor_stage": "ProblemContext",
                "sub_step": 7,
                "skill": "s",
                "purpose": "p",
                "q": [long_q],
                "a": ["用户裁决原话保留"],
            },
            # 本节点 u:2 子1（长 a 不截断——本节点保内容全文）
            {
                "kind": "skill-trace",
                "major_stage": "Understand",
                "minor_stage": "GoalsAndValue",
                "sub_step": 1,
                "skill": "s",
                "purpose": "p",
                "q": ["qn"],
                "a": ["A" * 300],
            },
        ]
        self._write_evidence(tmp_path, recs)
        # 注：sub_step 取 3（非 pack_self_contained 步）——u2-sub2-cost 起 u:2#2
        # 的包尾改「材料已在包内」不含 evidence 指针，通用尾行由本测试钉守。
        _write_state_full(tmp_path, "t", "understand", 2, sub_step=3)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None
        # 机械字段剥除（本节点+前序都不带）
        assert "purpose_marker" not in pack and "s_marker" not in pack
        # 前序 boundary 截断（100 + …），本节点长 a 全文保留
        assert "B" * 200 not in pack and "B" * 100 + "…" in pack
        assert "A" * 300 in pack
        # 前序长 q 截断（80 + …），用户裁决 a 保全文
        assert "Q" * 100 not in pack
        assert "用户裁决原话保留" in pack
        # 摘要指引 + evidence 指针
        assert "结论摘要" in pack and ".claude" in pack and "evidence" in pack

    def test_full_prior_boundary_step_opt_in(self, tmp_path):
        # p1-sub1-cost 修1（Step.pack_full_prior_boundary）：复用钉死条款要求
        # 前序出处逐字引用——置位步（plan:1#1）包内前序 boundary 保全文；
        # 未置位步（plan:1#2）维持 100 字符截断（P1-1 行为不变=回滚面）。
        long_boundary = "file:line 出处链 " + "B" * 300
        recs = [
            {
                "kind": "skill-trace",
                "major_stage": "Understand",
                "minor_stage": "ProblemContext",
                "sub_step": 6,
                "skill": "s",
                "purpose": "p",
                "statements": [
                    {"text": "结论甲", "type_label": "must", "boundary": long_boundary}
                ],
            },
            {
                "kind": "skill-trace",
                "major_stage": "Understand",
                "minor_stage": "ProblemContext",
                "sub_step": 7,
                "skill": "s",
                "purpose": "p",
                "q": ["读回"],
                "a": ["用户裁决原话保留"],
            },
        ]
        self._write_evidence(tmp_path, recs)
        _write_state_full(tmp_path, "t", "plan", 1, sub_step=1)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None
        assert long_boundary in pack  # 置位步：boundary 全文在包
        _write_state_full(tmp_path, "t", "plan", 1, sub_step=2)
        pack2 = eng.handoff_pack(tmp_path, "t")
        assert pack2 is not None
        assert long_boundary not in pack2  # 未置位步：维持截断
        assert (
            long_boundary[:100] + "…" in pack2
        )  # 100 字符截断形（_PACK_PRIOR_BOUNDARY_MAX）


class TestHandoffEvents:
    """v2.122 handoff 留痕（minor-boundary-handoff-prompt-design §2.2）。

    write_handoff_prompt：发提示即记，上次未决先补记 declined；
    write_handoff_resolution：仅当存在未决 prompt 才记（无未决=无操作非失败）。
    """

    def _node(self):
        return eng.get_node("understand", 1)

    def _kinds(self, tmp_path):
        p = tmp_path / ".claude" / "evidence" / "t.jsonl"
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text().splitlines()]

    def test_tier_bands(self):
        assert eng.handoff_tier(None) == "unknown"
        assert eng.handoff_tier(eng.HANDOFF_PROMPT_T1 - 1) == "ok"
        assert eng.handoff_tier(eng.HANDOFF_PROMPT_T1) == "suggest"
        assert eng.handoff_tier(eng.HANDOFF_PROMPT_T2 - 1) == "suggest"
        assert eng.handoff_tier(eng.HANDOFF_PROMPT_T2) == "strong"

    def test_prompt_record_fields(self, tmp_path):
        ok = eng.write_handoff_prompt(
            tmp_path, "t", self._node(), est=220_000, tier="suggest"
        )
        assert ok
        (rec,) = self._kinds(tmp_path)
        assert rec["kind"] == "handoff_prompt"
        assert rec["node"] == "understand:1"
        assert rec["major_stage"] == "Understand"
        assert rec["minor_stage"] == "ProblemContext"
        assert rec["est"] == 220_000 and rec["tier"] == "suggest" and rec["ts"]

    def test_unresolved_prompt_backfilled_declined(self, tmp_path):
        eng.write_handoff_prompt(tmp_path, "t", self._node(), est=1, tier="ok")
        eng.write_handoff_prompt(tmp_path, "t", self._node(), est=2, tier="ok")
        recs = self._kinds(tmp_path)
        assert [r["kind"] for r in recs] == [
            "handoff_prompt",
            "handoff_resolution",
            "handoff_prompt",
        ]
        assert recs[1]["choice"] == "declined" and recs[1]["node"] == "understand:1"

    def test_resolution_after_prompt_records_cleared(self, tmp_path):
        eng.write_handoff_prompt(tmp_path, "t", self._node(), est=1, tier="ok")
        assert eng.write_handoff_resolution(tmp_path, "t", choice="cleared")
        recs = self._kinds(tmp_path)
        assert [r["kind"] for r in recs] == ["handoff_prompt", "handoff_resolution"]
        assert recs[1]["choice"] == "cleared"

    def test_resolution_without_pending_is_noop(self, tmp_path):
        # 无 evidence 文件 / 无未决 prompt -> 无记录、返回 True（无操作非失败）
        assert eng.write_handoff_resolution(tmp_path, "t", choice="cleared")
        assert self._kinds(tmp_path) == []
        eng.write_handoff_prompt(tmp_path, "t", self._node(), est=1, tier="ok")
        eng.write_handoff_resolution(tmp_path, "t", choice="cleared")
        # 已有 resolution（无未决）-> 再次 clear 不再记
        assert eng.write_handoff_resolution(tmp_path, "t", choice="cleared")
        assert len(self._kinds(tmp_path)) == 2

    def test_last_handoff_event_ignores_other_kinds(self, tmp_path):
        eng.write_handoff_prompt(tmp_path, "t", self._node(), est=1, tier="ok")
        with open(
            tmp_path / ".claude" / "evidence" / "t.jsonl", "a", encoding="utf-8"
        ) as f:
            f.write(json.dumps({"kind": "skill-trace", "q": [], "a": []}) + "\n")
        last = eng._last_handoff_event(tmp_path, "t")
        assert last is not None and last["kind"] == "handoff_prompt"


class TestEstimateContextTokens:
    """v2.45 estimate_context_tokens：transcript 尾部 usage 估算（宁纵勿枉）。"""

    def test_reads_last_usage(self, tmp_path):
        tp = tmp_path / "s.jsonl"
        lines = [
            {
                "type": "assistant",
                "message": {
                    "usage": {
                        "input_tokens": 100,
                        "cache_read_input_tokens": 50000,
                        "cache_creation_input_tokens": 0,
                    }
                },
            },
            {"type": "user", "message": {"content": "x"}},
            {
                "type": "assistant",
                "message": {
                    "usage": {
                        "input_tokens": 200,
                        "cache_read_input_tokens": 160000,
                        "cache_creation_input_tokens": 3000,
                    }
                },
            },
        ]
        tp.write_text("\n".join(json.dumps(r) for r in lines), encoding="utf-8")
        assert eng.estimate_context_tokens(tp) == 163200

    def test_missing_file_returns_none(self, tmp_path):
        assert eng.estimate_context_tokens(tmp_path / "nope.jsonl") is None

    def test_no_usage_returns_none(self, tmp_path):
        tp = tmp_path / "s.jsonl"
        tp.write_text('{"type":"user","message":{"content":"hi"}}\n', encoding="utf-8")
        assert eng.estimate_context_tokens(tp) is None


class TestFetchTier:
    """v2.40 取证深度分档（designs/fetch-depth-tiering-design.md）。

    子2 定档（atomic_questions 逐项校验）→ 子3 按档执行（fetch_prompt
    预填标称档 + fetch_report_recorded tier-aware 数报告项）→ 台账按
    [tier=X] 归属统计轮次。默认档 light；none 档理由须含仓内路径。
    """

    def _append_s2(self, tmp_path, aq):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=2)
        qa = [{"q": "原子 A → 5Whys 因果链", "a": "Why1 实测值（:655）"}]
        (tmp_path / "payload.json").write_text(
            json.dumps(
                {"purpose": "p", "qa": qa, "atomic_questions": aq}, ensure_ascii=False
            ),
            encoding="utf-8",
        )
        return eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))

    def test_tier_enum_invalid_rejected(self, tmp_path):
        ok, msg = self._append_s2(
            tmp_path, [{"q": "A", "tier": "deep", "tier_reason": "r"}]
        )
        assert not ok and "none/light/full" in msg and "拿不准标 light" in msg

    def test_external_knowledge_test_pinned_both_sides(self):
        # v2.56 双侧钉死（2026-08-02 u:1 子2 att1：模型 Why2 引 M19 年化公式
        # 判量级却标 none——外部知识依赖枚举原只在 gate 侧，模型侧无操作
        # 测试）：_FETCH_TIER_RULE 含操作测试文本，purpose/selfcheck/gate
        # 三面同源引用。live 重放：att1 真实载荷新 gate 仍 BLOCK（判词引
        # 「外部知识依赖」新条款）、surgical 修复版 PASS。
        # v2.72（2026-08-04 framing 反转）：常量撤出 gate（长度是弱 judge
        # 独立变量），judge 侧钉压缩条款（方框第四条），purpose 侧仍
        # verbatim 引用——双侧钉死意图不变。
        import dl_flow_nodes as nodes

        rule = nodes._FETCH_TIER_RULE
        assert "外部知识依赖操作测试" in rule and "不得标 none" in rule
        assert "valid_mean*252*coverage" in rule  # 反例取 att1 逐字
        step = eng.get_node("understand", 1).sub_steps[1]
        assert rule in step.purpose
        assert "外部知识依赖" in step.gate and "标 none" in step.gate
        assert "在仓外=含外部知识依赖" in step.selfcheck

    def test_tier_reason_empty_rejected(self, tmp_path):
        ok, msg = self._append_s2(
            tmp_path, [{"q": "A", "tier": "full", "tier_reason": " "}]
        )
        assert not ok and "tier_reason 须非空" in msg

    def test_none_tier_requires_repo_path(self, tmp_path):
        ok, msg = self._append_s2(
            tmp_path, [{"q": "A", "tier": "none", "tier_reason": "我觉得仓里有"}]
        )
        assert not ok and "仓内取证路径" in msg

    def test_item_not_dict_rejected(self, tmp_path):
        ok, msg = self._append_s2(tmp_path, ["原子A"])
        assert not ok and "须为对象" in msg

    def test_three_tier_mix_accepted(self, tmp_path):
        aq = [
            {
                "q": "仓内行为",
                "tier": "none",
                "tier_reason": "layered_backtest.py:655 可证伪",
            },
            {
                "q": "年化量级合理性",
                "tier": "light",
                "tier_reason": "数值 claim 有公开锚点",
            },
            {"q": "系统怎么设计", "tier": "full", "tier_reason": "开放方法论问题"},
        ]
        ok, msg = self._append_s2(tmp_path, aq)
        assert ok, msg

    # ---- fetch_report_recorded tier-aware（none 档豁免报告项）----

    def _write_step2_trace_with_aq(self, tmp_path, aq):
        rec = json.dumps(
            {
                "kind": "skill-trace",
                "major_stage": "Understand",
                "minor_stage": "ProblemContext",
                "sub_step": 2,
                "skill": "causal-inference-root-cause",
                "purpose": "p",
                "q": ["清单"],
                "a": ["…"],
                "atomic_questions": aq,
            },
            ensure_ascii=False,
        )
        _write_evidence(tmp_path, "t", [rec])

    def _append_s4_reports(self, tmp_path, n_reports):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=4)
        # v2.43 起双向取证（旧子3，plan-first 拆步后顺延为子4）append-trace
        # 前置：骨架 --out 落盘（本类测报告计数，骨架存在性是正交前置）
        (
            tmp_path / ".claude" / "workflows" / "t" / "fetch-prompt-skeleton.md"
        ).write_text("骨架", encoding="utf-8")
        qa = [
            {
                "q": f"原子{i} 子代理蒸馏报告（原文收录）",
                "a": "反证查询（先）：…；支持证据（后）：…",
            }
            for i in range(n_reports)
        ]
        (tmp_path / "payload.json").write_text(
            json.dumps({"purpose": "p", "qa": qa}, ensure_ascii=False), encoding="utf-8"
        )
        return eng.append_trace(tmp_path, "t", str(tmp_path / "payload.json"))

    def test_report_count_must_cover_non_none_atoms(self, tmp_path):
        self._write_step2_trace_with_aq(
            tmp_path,
            [
                {"q": "A", "tier": "full", "tier_reason": "r"},
                {"q": "B", "tier": "light", "tier_reason": "r"},
            ],
        )
        ok, msg = self._append_s4_reports(tmp_path, 1)
        assert not ok and "2 个" in msg and "仅 1 个" in msg

    def test_none_atom_exempt_from_report(self, tmp_path):
        self._write_step2_trace_with_aq(
            tmp_path,
            [
                {"q": "A", "tier": "none", "tier_reason": "x.py:1 仓内可证伪"},
                {"q": "B", "tier": "full", "tier_reason": "r"},
            ],
        )
        ok, msg = self._append_s4_reports(tmp_path, 1)
        assert ok, msg

    def test_reports_covering_non_none_accepted(self, tmp_path):
        self._write_step2_trace_with_aq(
            tmp_path,
            [
                {"q": "A", "tier": "full", "tier_reason": "r"},
                {"q": "B", "tier": "light", "tier_reason": "r"},
            ],
        )
        ok, msg = self._append_s4_reports(tmp_path, 2)
        assert ok, msg

    # ---- fetch_prompt 分档骨架 ----

    def test_fetch_prompt_prefills_tier_markers(self, tmp_path):
        self._write_step2_trace_with_aq(
            tmp_path,
            [
                {"q": "仓内行为", "tier": "none", "tier_reason": "x.py:1"},
                {"q": "年化量级", "tier": "light", "tier_reason": "数值锚点"},
                {"q": "系统设计", "tier": "full", "tier_reason": "开放问题"},
            ],
        )
        prompt = eng.fetch_prompt(tmp_path, "t")
        assert prompt is not None
        assert "[tier=light]" in prompt and "[tier=full]" in prompt
        assert "none 档原子（仅内查，禁为其派发取证 agent）" in prompt
        assert "仓内行为" in prompt  # none 档列入豁免说明
        # 分档执行参数块
        assert "分档执行参数" in prompt
        assert "≤4 curl" in prompt and "≤12 curl" in prompt
        assert "单向锚点" in prompt and "≤60 行" in prompt
        assert "建议升档 full" in prompt
        assert "禁降档" in prompt

    def test_fetch_prompt_all_none_short_circuits(self, tmp_path):
        self._write_step2_trace_with_aq(
            tmp_path,
            [{"q": "仓内行为", "tier": "none", "tier_reason": "x.py:1"}],
        )
        out = eng.fetch_prompt(tmp_path, "t")
        assert out is not None
        assert "全部原子问题为 none 档" in out
        assert "命令模板" not in out  # 不是骨架，是短路指引

    def test_fetch_prompt_legacy_trace_full_tier_unchanged(self, tmp_path):
        # 无 atomic_questions（v2.40 前实例）-> legacy：骨架无分档预填
        rec = json.dumps(
            {
                "kind": "skill-trace",
                "major_stage": "Understand",
                "minor_stage": "ProblemContext",
                "sub_step": 2,
                "skill": "s",
                "purpose": "p",
                "q": ["原子问题清单"],
                "a": ["原子A=数值正确性"],
            },
            ensure_ascii=False,
        )
        _write_evidence(tmp_path, "t", [rec])
        prompt = eng.fetch_prompt(tmp_path, "t")
        assert prompt is not None
        assert "已分档原子清单" not in prompt
        assert "分档执行参数" in prompt  # 参数块常驻（legacy 全按 full）


# ---------- ARTIFACT_SECTIONS 单源同步（2026-08-02，artifact-handoff-hardening P2）----------


class TestArtifactSectionsSync:
    """节标题单源 -> 门/模板/消费契约 不漂移：断链在此红，不在运行期爆。

    覆盖设计 §1.2 的五个静态断言（注入/output-style 侧在 test_workflow_phase.py）。
    """

    def test_plan_sections_equals_assembly_division(self):
        # #1：plan.md 三节 = plan:2/3/4 分工装配节之并（顺序 = 装配顺序）
        secs = eng.ARTIFACT_SECTIONS["plan.md"]
        assert eng.get_node("plan", 2).artifact_contains == secs[0:1]
        assert eng.get_node("plan", 3).artifact_contains == secs[1:2]
        assert eng.get_node("plan", 4).artifact_contains == secs  # 出口全量查

    def test_md_artifact_nodes_contains_subset_of_single_source(self):
        # #2：每个 .md 产物节点 = CONTAINS 门 + 节 ∈ 单源（禁游离节名）
        md_nodes = [
            (nid, n)
            for nid, n in eng._NODES.items()
            if n.artifact and n.artifact.endswith(".md")
        ]
        assert md_nodes, "节点表至少应有一个 .md 产物节点"
        for nid, node in md_nodes:
            assert node.gate_mech == eng.GateMech.ARTIFACT_CONTAINS, nid
            known = eng.ARTIFACT_SECTIONS[node.artifact]
            assert set(node.artifact_contains) <= set(known), nid

    def test_render_no_token_residue_and_all_sections_present(self):
        # #3：模板渲染后无 token 残留 + 全部单源节名在渲染产物里
        tpl_path = (
            Path(eng.__file__).resolve().parent
            / "scripts"
            / "workflow"
            / "phase-rules.md"
        )
        rendered = eng.render_phase_rules(tpl_path.read_text(encoding="utf-8"))
        assert "{{" not in rendered
        for secs in eng.ARTIFACT_SECTIONS.values():
            for s in secs:
                assert s in rendered

    def test_artifact_token_unknown_basename_raises(self):
        # token 产物名非法 -> fail loud（与 GENERATED 渲染同纪律）
        import pytest

        with pytest.raises(ValueError, match="产物名未知"):
            eng.render_phase_rules("{{artifact_sections:nope.md}}")

    def test_consumption_contract_anchors(self):
        # #5：消费契约锚点——下游读到的产物结构已被上游出口门保证
        # execute 首步读 plan.md 三节 -> plan 出口节点（plan:4）全量查
        assert (
            eng.get_node("plan", 4).artifact_contains
            == eng.ARTIFACT_SECTIONS["plan.md"]
        )
        # review 对照 understand.md -> understand 出口节点（understand:4）全量查
        assert (
            eng.get_node("understand", 4).artifact_contains
            == eng.ARTIFACT_SECTIONS["understand.md"]
        )
        # review/evolution 自身产物 = 最小两节（2026-08-02 用户决议）
        assert (
            eng.get_node("review", 0).artifact_contains
            == eng.ARTIFACT_SECTIONS["review.md"]
        )
        assert (
            eng.get_node("evolution", 0).artifact_contains
            == eng.ARTIFACT_SECTIONS["evolution.md"]
        )


class TestTraceMdParser:
    """v2.58 分节标记文本载荷（模型零接触 JSON，四桶分工正治）。

    v2.57 scaffold 是半吊子：Edit 填 JSON 仍会被内容里的 ASCII 双引号
    弄崩（真实 trace 含 f"{val*100:.2f}%" 类代码原文）。标记文本零转义，
    序列化全归脚本。
    """

    def _step(self, phase, sub, idx):
        return eng.get_node(phase, sub).sub_steps[idx]

    def test_qa_with_quotes_code_newlines(self):
        # 核心场景：内容带 ASCII 双引号/代码/多行——零转义原样进 dict
        step = self._step("understand", 1, 0)
        md = (
            "【purpose】\n逼问问题定义\n\n【qa】\n【q】\nwho=身份？\n【a】\n"
            '未自述。代码原文 f"{val * 100:.2f}%"（formatters.py:92）\n第二行'
            "依然属于同一字段\n【结论】\n①问题成立。主语=未自述身份。"
        )
        payload, err = eng._parse_trace_md(md, step)
        assert err is None
        assert payload["purpose"] == "逼问问题定义"
        assert payload["qa"] == [
            {
                "q": "who=身份？",
                "a": '未自述。代码原文 f"{val * 100:.2f}%"（formatters.py:92）\n第二行依然属于同一字段',
            }
        ]
        assert payload["结论"].startswith("①")

    def test_multi_items_and_tier_fields(self):
        step = self._step("understand", 1, 1)
        md = (
            "【purpose】\np\n【qa】\n【q】\nq1\n【a】\na1\n【q】\nq2\n【a】\na2\n"
            "【atomic_questions】\n【q】\nA. 问题\n【tier】\nlight\n"
            "【tier_reason】\n外部锚点\n【q】\nB. 问题2\n【tier】\nnone\n"
            "【tier_reason】\nx.py:1"
        )
        payload, err = eng._parse_trace_md(md, step)
        assert err is None
        assert [it["q"] for it in payload["qa"]] == ["q1", "q2"]
        assert [it["tier"] for it in payload["atomic_questions"]] == ["light", "none"]

    def test_statements_with_fields(self):
        step = self._step("understand", 3, 3)
        md = (
            "【purpose】\np\n【statements】\n【text】\n年化数字允许被更新\n"
            "【type_label】\nin\n【boundary】\n实现指针：_macros.html"
        )
        payload, err = eng._parse_trace_md(md, step)
        assert err is None
        assert payload["statements"][0]["text"] == "年化数字允许被更新"

    def test_unknown_header_rejected(self):
        step = self._step("understand", 1, 0)
        _, err = eng._parse_trace_md(
            "【purpose】\np\n【qa】\n【q】\nx\n【a】\ny\n【结伦】\n①", step
        )
        assert err and "未知标头" in err and "【结论】" in err  # 指路列出合法标头

    def test_preamble_rejected(self):
        step = self._step("understand", 1, 0)
        _, err = eng._parse_trace_md("垃圾前奏\n【purpose】\np", step)
        assert err and "首个标头" in err

    def test_field_header_outside_array_rejected(self):
        step = self._step("understand", 1, 0)
        _, err = eng._parse_trace_md("【purpose】\np\n【q】\nx", step)
        assert err and "字段标头" in err

    def test_scalar_repeat_rejected(self):
        step = self._step("understand", 1, 0)
        _, err = eng._parse_trace_md("【purpose】\np\n【purpose】\np2", step)
        assert err and "重复" in err

    def test_indented_bracket_line_is_content(self):
        # 逃生口：缩进的【行不算标头
        step = self._step("understand", 1, 0)
        md = "【purpose】\np\n【qa】\n【q】\nx\n【a】\n  【q】缩进后是内容"
        payload, err = eng._parse_trace_md(md, step)
        assert err is None and payload["qa"][0]["a"] == "【q】缩进后是内容"

    def test_glued_header_content_same_line(self):
        # v2.65：模型手写自然风格粘头（【key】内容 同行）须解析通过--
        # tail_volume u:1 子1 手写全粘头载荷被旧 \s*$ 误拒，报错与实况矛盾
        step = self._step("understand", 1, 0)
        md = (
            "【purpose】逼问问题定义\n\n"
            "【qa】\n"
            "【q】who--谁在问？\n"
            "【a】未自述身份\n\n"
            "【q】pain--痛点？\n"
            "【a】影响选因子决策\n"
            "【结论】①问题成立"
        )
        payload, err = eng._parse_trace_md(md, step)
        assert err is None, err
        assert payload["purpose"] == "逼问问题定义"
        assert payload["qa"][0]["q"] == "who--谁在问？"
        assert payload["qa"][1]["a"] == "影响选因子决策"
        assert payload["结论"] == "①问题成立"

    def test_bom_stripped(self):
        # v2.65：文件头 BOM 自动剥（Write/编辑器可能带）--
        # 旧版 BOM 使首行非顶格匹配，报「首个标头前有多余内容」误导字节 hunt
        step = self._step("understand", 1, 0)
        md = "﻿【purpose】\n逼问问题定义\n【结论】①问题成立"
        payload, err = eng._parse_trace_md(md, step)
        assert err is None, err
        assert payload["purpose"] == "逼问问题定义"

    def test_preamble_error_includes_repr(self):
        # v2.65：junk 报错带 repr 实际内容（BOM/散文一眼可见，免 xxd/od hunt）
        step = self._step("understand", 1, 0)
        _, err = eng._parse_trace_md("这是散言\n【purpose】\np", step)
        assert err and "首个标头" in err and "这是散言" in err

    def test_clean_scaffold_still_parses(self):
        # 向后兼容：标头独占行（scaffold 骨架格式）仍正常解析
        step = self._step("understand", 1, 0)
        md = "【purpose】\n逼问问题定义\n【qa】\n【q】\nQ1\n【a】\nA1\n【结论】\n①测试"
        payload, err = eng._parse_trace_md(md, step)
        assert err is None
        assert payload["qa"] == [{"q": "Q1", "a": "A1"}]
        assert payload["结论"] == "①测试"


class TestScaffoldPayload:
    """append-trace --scaffold 载荷骨架（v2.57 起；v2.58 换 .md 标记文本）。

    骨架占位符「待填」被 _placeholder_hit 全局扫描兜底，漏填不可提交。
    """

    def test_scaffold_qa_step_with_extra_keys(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        ok, msg = eng.scaffold_payload(tmp_path, "t")
        assert ok, msg
        out = tmp_path / ".trace-payload-t.md"
        text = out.read_text(encoding="utf-8")
        assert "【purpose】" in text and "【qa】" in text and "【结论】" in text
        # 骨架自身可被解析器读回（格式自洽）
        step = eng.get_node("understand", 1).sub_steps[0]
        payload, err = eng._parse_trace_md(text, step)
        assert err is None and payload["qa"][0]["q"].startswith("待填")

    def test_scaffold_tier_items_shape(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=2)
        ok, msg = eng.scaffold_payload(tmp_path, "t")
        assert ok, msg
        out = tmp_path / ".trace-payload-t.md"
        step = eng.get_node("understand", 1).sub_steps[1]
        payload, err = eng._parse_trace_md(out.read_text(encoding="utf-8"), step)
        assert err is None
        assert set(payload["atomic_questions"][0]) == {"q", "tier", "tier_reason"}

    def test_scaffold_statements_step_with_fields(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 3, sub_step=4)
        ok, msg = eng.scaffold_payload(tmp_path, "t")
        assert ok, msg
        out = tmp_path / ".trace-payload-t.md"
        step = eng.get_node("understand", 3).sub_steps[3]
        payload, err = eng._parse_trace_md(out.read_text(encoding="utf-8"), step)
        assert err is None
        assert {"text", "type_label", "boundary"} <= set(payload["statements"][0])

    def test_scaffold_statements_multi_item_hint(self, tmp_path):
        # u4-sub4-cost 修A：多条陈述形态写进骨架占位符括注（u4_sub4_ab B 轮
        # 实测——单条骨架未示多条形态，模型花 5 调用去 evidence/仓内找多条
        # 实际样例；格式信息归骨架表达，四桶分工）。钉死防静默丢失。
        _write_state_full(tmp_path, "t", "understand", 3, sub_step=4)
        ok, msg = eng.scaffold_payload(tmp_path, "t")
        assert ok, msg
        out = tmp_path / ".trace-payload-t.md"
        text = out.read_text(encoding="utf-8")
        assert "多条陈述 = 逐项重复本【statements】整段" in text
        # 骨架自身仍可被解析器读回（括注在待填占位符内=text 字段内容）
        step = eng.get_node("understand", 3).sub_steps[3]
        payload, err = eng._parse_trace_md(text, step)
        assert err is None

    def test_scaffold_refuses_overwrite(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        out = tmp_path / ".trace-payload-t.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("【purpose】\n在写工作\n", encoding="utf-8")
        ok, msg = eng.scaffold_payload(tmp_path, "t")
        assert not ok and "已存在" in msg
        assert "在写工作" in out.read_text(encoding="utf-8")

    @staticmethod
    def _patch_created_at(tmp_path, name, created_at):
        p = tmp_path / ".claude" / "workflows" / name / "state.json"
        st = json.loads(p.read_text(encoding="utf-8"))
        st["created_at"] = created_at
        p.write_text(json.dumps(st), encoding="utf-8")

    def test_scaffold_autocleans_stale_payload_from_previous_run(self, tmp_path):
        # v2.63（2026-08-03 tail_volume_acceleration_annualized u:1 子1 事故）：
        # 上轮放弃运行的 payload 点文件残留（手动清 evidence 漏点文件，launch
        # 不清 payload）挡住新一轮首个 --scaffold。机械判 stale：payload
        # mtime < state.created_at ⇒ 它诞生时本轮还不存在 ⇒ 定义性残留，
        # 自动清理重新生成，不拒。
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        self._patch_created_at(tmp_path, "t", "2099-01-01T00:00:00")
        out = tmp_path / ".trace-payload-t.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("【purpose】\n上轮残留\n", encoding="utf-8")
        ok, msg = eng.scaffold_payload(tmp_path, "t")
        assert ok, msg
        assert "残留" in msg
        text = out.read_text(encoding="utf-8")
        assert "上轮残留" not in text and "待填" in text

    def test_scaffold_refuses_fresh_payload_within_run(self, tmp_path):
        # mtime >= created_at ⇒ 可能是本轮在写工作 ⇒ 维持拒覆盖（防抹掉）。
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        self._patch_created_at(tmp_path, "t", "2000-01-01T00:00:00")
        out = tmp_path / ".trace-payload-t.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("【purpose】\n在写工作\n", encoding="utf-8")
        ok, msg = eng.scaffold_payload(tmp_path, "t")
        assert not ok and "已存在" in msg
        assert "在写工作" in out.read_text(encoding="utf-8")

    # created_at 缺失/畸形 ⇒ 宁纵勿枉维持拒覆盖（不误删）：由现有
    # test_scaffold_refuses_overwrite 覆盖（fixture created_at="x" 不可解析）。

    def test_scaffold_unfilled_rejected_by_placeholder_scan(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        ok, _ = eng.scaffold_payload(tmp_path, "t")
        assert ok
        out = tmp_path / ".trace-payload-t.md"
        ok, msg = eng.append_trace(tmp_path, "t", str(out))
        assert not ok and "待填" in msg and "占位" in msg

    def test_scaffold_fill_and_append_happy_path(self, tmp_path):
        # 端到端：骨架 -> Edit 填内容（含 ASCII 引号代码，JSON 时代会崩的形态）
        # -> append 成功
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        ok, _ = eng.scaffold_payload(tmp_path, "t")
        assert ok
        out = tmp_path / ".trace-payload-t.md"
        text = out.read_text(encoding="utf-8")
        text = text.replace("待填：本步目的/本轮做了什么（一句话）", "逼问问题定义")
        text = text.replace("待填：问题1", "who=当前提问者身份？")
        text = text.replace(
            "待填：答案1（用户原话/会话事实/证据指针 file:line）",
            '未自述身份。代码原文 f"{val * 100:.2f}%"（formatters.py:92）',
        )
        text = text.replace(
            "待填：①/② 开头+逐句出处",
            "①问题成立。具体主语 = 未自述身份（who=未自述）。",
        )
        out.write_text(text, encoding="utf-8")
        ok, msg = eng.append_trace(tmp_path, "t", str(out))
        assert ok, msg
        rec = json.loads(
            (tmp_path / ".claude" / "evidence" / "t.jsonl")
            .read_text(encoding="utf-8")
            .strip()
        )
        assert 'f"{val * 100:.2f}%"' in rec["a"][0]  # 引号零转义落库


class TestRenderArtifact:
    """v2.59 render-artifact：产物机械装配（四桶分工审计违规①根治）。

    产物装配原为模型手工转录（purpose 自写「直接装配、禁二次创作」），
    现从各节点最新 statements/裁决 trace 机械装配，模型零接触产物文件。
    """

    def _stmt_trace(self, minor, step, texts):
        return json.dumps(
            {
                "kind": "skill-trace",
                "minor_stage": minor,
                "sub_step": step,
                "statements": [
                    {
                        "text": t,
                        "type_label": "证实",
                        "boundary": f"证据指针 x.py:{i + 1}",
                        "fields": {"confidence": "高"},
                    }
                    for i, t in enumerate(texts)
                ],
            },
            ensure_ascii=False,
        )

    def _qa_trace(self, minor, step, items):
        return json.dumps(
            {
                "kind": "skill-trace",
                "minor_stage": minor,
                "sub_step": step,
                "q": [q for q, _ in items],
                "a": [a for _, a in items],
            },
            ensure_ascii=False,
        )

    def _full_understand_evidence(self, tmp_path):
        recs = [
            self._stmt_trace("ProblemContext", 6, ["年化显示 9529.8% 异常"]),
            self._stmt_trace("GoalsAndValue", 4, ["修正显示防误决策"]),
            self._stmt_trace("ScopeAndConstraints", 4, ["允许改模板层"]),
            self._stmt_trace("SuccessCriteria", 4, ["年化显示=95.3%"]),
            self._qa_trace("ProblemContext", 7, [("裁决：who 与目标", "用户认可")]),
            self._qa_trace("ProblemContext", 5, [("处置后问题集", "H3 剔除：无证据")]),
        ]
        _write_evidence(tmp_path, "t", recs)

    def test_understand_md_full_assembly(self, tmp_path):
        self._full_understand_evidence(tmp_path)
        ok, msg = eng.render_artifact(tmp_path, "t", "understand.md")
        assert ok, msg
        out = tmp_path / ".claude" / "understands" / "t.md"
        text = out.read_text(encoding="utf-8")
        for sec in ("真实问题重述", "目标价值", "范围约束", "成功标准验收包"):
            assert f"## {sec}" in text
        assert "年化显示 9529.8% 异常（证实；证据指针 x.py:1；confidence=高）" in text
        assert "## 裁决记录" in text and "用户认可" in text
        assert "## 未选定与接续" in text and "H3 剔除" in text
        # CONTAINS 机械门对象全满足（节名单源 ARTIFACT_SECTIONS）
        for sec in eng.ARTIFACT_SECTIONS["understand.md"]:
            assert sec in text

    def test_understand_md_missing_source_rejected(self, tmp_path):
        _write_evidence(tmp_path, "t", [self._stmt_trace("ProblemContext", 6, ["x"])])
        ok, msg = eng.render_artifact(tmp_path, "t", "understand.md")
        assert not ok and "GoalsAndValue" in msg and "装配源" in msg
        assert not (tmp_path / ".claude" / "understands" / "t.md").exists()

    def test_plan_md_partial_assembly_tolerated(self, tmp_path):
        # plan:2 装配时点后两节源不存在——渲染已有节并点名跳过（幂等覆盖）
        _write_evidence(
            tmp_path,
            "t",
            [
                self._stmt_trace("TaskBreakdown", 4, ["步骤1 修模板"]),
                self._qa_trace(
                    "TaskBreakdown", 5, [("裁决：阶段拍板", "用户拍板 3 阶段")]
                ),
            ],
        )
        ok, msg = eng.render_artifact(tmp_path, "t", "plan.md")
        assert ok, msg
        assert "跳过缺源节" in msg
        text = (tmp_path / ".claude" / "plans" / "t.md").read_text(encoding="utf-8")
        assert "## 执行步骤" in text and "步骤1 修模板" in text
        assert "## 能力与工具" not in text
        assert "用户拍板 3 阶段" in text

    def test_plan_md_idempotent_regrowth(self, tmp_path):
        # plan:3 再跑：两节齐备（幂等覆盖不丢前节）
        self.test_plan_md_partial_assembly_tolerated(tmp_path)
        ev = eng._evidence_path(tmp_path, "t")
        with ev.open("a", encoding="utf-8") as f:
            f.write(self._stmt_trace("CapabilityToolSelection", 5, ["能力包 X"]) + "\n")
        ok, _ = eng.render_artifact(tmp_path, "t", "plan.md")
        assert ok
        text = (tmp_path / ".claude" / "plans" / "t.md").read_text(encoding="utf-8")
        assert "## 执行步骤" in text and "## 能力与工具" in text

    def test_plan_md_checkpoints_section_from_statements(self, tmp_path):
        # v2.119 事故回归钉：plan:4#4 迁 statements 后，「执行计划与检查点」节
        # 从 ExecutionPlanCheckpoints 子4 trace 装出（2026-08-06 tail_volume
        # live 全轮 qa 残留致结构性跳节、门栏 CONTAINS 不可通过）
        _write_evidence(
            tmp_path,
            "t",
            [
                self._stmt_trace("TaskBreakdown", 4, ["步骤1 修模板"]),
                self._stmt_trace("CapabilityToolSelection", 5, ["能力包 X"]),
                self._stmt_trace(
                    "ExecutionPlanCheckpoints", 4, ["CP1 在 T1 提交后自动核验"]
                ),
            ],
        )
        ok, msg = eng.render_artifact(tmp_path, "t", "plan.md")
        assert ok, msg
        assert "跳过缺源节" not in msg
        text = (tmp_path / ".claude" / "plans" / "t.md").read_text(encoding="utf-8")
        assert "## 执行计划与检查点" in text
        assert "CP1 在 T1 提交后自动核验" in text
        for sec in eng.ARTIFACT_SECTIONS["plan.md"]:
            assert sec in text

    def test_plan_md_checkpoints_section_skipped_for_qa_trace(self, tmp_path):
        # 旧 bug 形态反钉：子4 是 qa trace（无 statements）时该节结构性跳节
        _write_evidence(
            tmp_path,
            "t",
            [
                self._qa_trace(
                    "ExecutionPlanCheckpoints", 4, [("计划包", "CP1 自动核验")]
                ),
            ],
        )
        ok, msg = eng.render_artifact(tmp_path, "t", "plan.md")
        assert ok, msg
        assert "跳过缺源节" in msg and "执行计划与检查点" in msg
        text = (tmp_path / ".claude" / "plans" / "t.md").read_text(encoding="utf-8")
        assert "## 执行计划与检查点" not in text

    def test_unsupported_basename_rejected(self, tmp_path):
        ok, msg = eng.render_artifact(tmp_path, "t", "review.md")
        assert not ok and "不支持" in msg

    def test_old_format_qa_readback_items_collected(self, tmp_path):
        # q/a 平行数组形态（append-trace 实际落库形态）的裁决项也能收
        self._full_understand_evidence(tmp_path)
        ok, _ = eng.render_artifact(tmp_path, "t", "understand.md")
        assert ok
        text = (tmp_path / ".claude" / "understands" / "t.md").read_text(
            encoding="utf-8"
        )
        assert "【裁决：who 与目标】用户认可" in text


class TestIngestAgentReport:
    """v2.60 append-trace --ingest-agent：子代理报告原文落载荷（审计违规②根治）。

    原「原文收录=完整粘贴」是手工转录+两层防偷懒检查；脚本按 task-id 定位
    agent-<task-id>.jsonl、提取最终报告文本、以规定标题形态插入载荷 qa 节——
    收录从需要检查变结构性保证。
    """

    def _mk(
        self, tmp_path, monkeypatch, sub_step=4, report="verdict: 部分成立\n推理链…"
    ):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=sub_step)
        home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        enc = "".join(c if c.isalnum() else "-" for c in str(tmp_path))
        d = home / ".claude" / "projects" / enc / "s" / "subagents"
        d.mkdir(parents=True)
        with (d / "agent-abc123.jsonl").open("w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "message": {}}) + "\n")
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [
                                {"type": "thinking", "thinking": "..."},
                                {"type": "text", "text": report},
                            ]
                        },
                    }
                )
                + "\n"
            )
        return d

    def _scaffold(self, tmp_path):
        ok, msg = eng.scaffold_payload(tmp_path, "t")
        assert ok, msg
        return tmp_path / ".trace-payload-t.md"

    def test_ingest_redteam_happy(self, tmp_path, monkeypatch):
        # plan-first 拆步重编号（6→7 步）后：质检裁决（红队）= 子5
        self._mk(tmp_path, monkeypatch, sub_step=5)
        self._scaffold(tmp_path)
        ok, msg = eng.ingest_agent_report(tmp_path, "t", "abc123")
        assert ok, msg
        text = (tmp_path / ".trace-payload-t.md").read_text(encoding="utf-8")
        assert "红队输出原文收录（task-id abc123）" in text
        assert "verdict: 部分成立" in text
        # 收录项插在 qa 节内（解析回读自洽：进 qa 不进别的节）
        step = eng.get_node("understand", 1).sub_steps[4]
        payload, err = eng._parse_trace_md(text, step)
        assert err is None
        titles = [it["q"] for it in payload["qa"]]
        assert any("红队" in q and "原文收录" in q for q in titles)

    def test_ingest_finds_transcript_in_later_dir(self, tmp_path, monkeypatch):
        # round-2 修 A bug 重现场（amplitude_annualized 2026-08-17 step4 实爆）：
        # 多会话目录各有 subagents/（该实例 14 个），字典序第一个（"aaa-old"）
        # 是旧会话，目标 transcript 在较后的 "zzz-cur"——旧实现按「第一个含
        # subagents/」定位必报「找不到」，致模型 15 轮调试死循环（ln/cp 被
        # 守卫拒、shutil 绕过）。修 = 按 task_id 定位含目标文件的目录。
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=5)
        home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        enc = "".join(c if c.isalnum() else "-" for c in str(tmp_path))
        base = home / ".claude" / "projects" / enc
        old_d = base / "aaa-old" / "subagents"
        old_d.mkdir(parents=True)
        (old_d / "agent-old999.jsonl").write_text(
            json.dumps({"type": "user", "message": {}}) + "\n", encoding="utf-8"
        )
        cur_d = base / "zzz-cur" / "subagents"
        cur_d.mkdir(parents=True)
        with (cur_d / "agent-abc123.jsonl").open("w", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [{"type": "text", "text": "红队报告正文"}]
                        },
                    }
                )
                + "\n"
            )
        self._scaffold(tmp_path)
        ok, msg = eng.ingest_agent_report(tmp_path, "t", "abc123")
        assert ok, msg
        text = (tmp_path / ".trace-payload-t.md").read_text(encoding="utf-8")
        assert "红队报告正文" in text

    def test_ingest_prefers_newest_on_duplicate(self, tmp_path, monkeypatch):
        # 同名 transcript 双份（模型手工拷贝残留的 workaround，本轮实见
        # 188d1472/e92ca5db 各一份）→ 取文件 mtime 最新者（当前段产出）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=5)
        home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        enc = "".join(c if c.isalnum() else "-" for c in str(tmp_path))
        base = home / ".claude" / "projects" / enc
        for dname, report, mtime in (
            ("aaa-old", "旧拷贝", 1000000000),
            ("zzz-cur", "新报告正文", 1000000100),
        ):
            d = base / dname / "subagents"
            d.mkdir(parents=True)
            fp = d / "agent-abc123.jsonl"
            fp.write_text(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {"content": [{"type": "text", "text": report}]},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            os.utime(fp, (mtime, mtime))
        self._scaffold(tmp_path)
        ok, msg = eng.ingest_agent_report(tmp_path, "t", "abc123")
        assert ok, msg
        text = (tmp_path / ".trace-payload-t.md").read_text(encoding="utf-8")
        assert "新报告正文" in text and "旧拷贝" not in text

    def test_ingest_fetch_title_step4(self, tmp_path, monkeypatch):
        # plan-first 拆步重编号后：双向取证 = 子4（旧子3 映射是重编号漏网，
        # amplitude_annualized D/F 两轮 step4 实爆「蒸馏报告收录项不足」）
        self._mk(tmp_path, monkeypatch, sub_step=4, report="蒸馏报告正文")
        self._scaffold(tmp_path)
        ok, _ = eng.ingest_agent_report(tmp_path, "t", "abc123")
        assert ok
        text = (tmp_path / ".trace-payload-t.md").read_text(encoding="utf-8")
        assert "蒸馏报告原文收录（task-id abc123）" in text

    def test_ingest_dispatch_note_not_duplicate(self, tmp_path, monkeypatch):
        # 防重不得误伤派发留痕：模型在 qa 写「原子D→Agent task-id=abc123」
        # （task-id 出场=已派发，正是 mech 台账信号）≠ 已收录——只有脚本写出的
        # 收录项标题形态「原文收录（task-id xxx）」才算重复
        # （amplitude_annualized D 轮 step4 实证：误报致 10 轮读源码调试死循环）。
        self._mk(tmp_path, monkeypatch, sub_step=4, report="蒸馏报告正文")
        payload = self._scaffold(tmp_path)
        text = payload.read_text(encoding="utf-8")
        text = text.replace("待填", "原子D（full）→ Agent task-id=abc123 已派发", 1)
        payload.write_text(text, encoding="utf-8")
        ok, msg = eng.ingest_agent_report(tmp_path, "t", "abc123")
        assert ok, msg
        # 真重复（脚本标题形态在场）仍拒
        ok, msg = eng.ingest_agent_report(tmp_path, "t", "abc123")
        assert not ok and "已收录" in msg

    def test_ingest_inserts_before_extra_keys_section(self, tmp_path, monkeypatch):
        # 子2 形态载荷（qa + atomic_questions 节）：收录项不得落进分档节
        self._mk(tmp_path, monkeypatch, sub_step=2)
        self._scaffold(tmp_path)
        ok, _ = eng.ingest_agent_report(tmp_path, "t", "abc123")
        assert ok
        text = (tmp_path / ".trace-payload-t.md").read_text(encoding="utf-8")
        step = eng.get_node("understand", 1).sub_steps[1]
        payload, err = eng._parse_trace_md(text, step)
        assert err is None
        assert len(payload["atomic_questions"]) == 1  # 没被误增
        assert any("task-id abc123" in it["q"] for it in payload["qa"])

    def test_ingest_duplicate_rejected(self, tmp_path, monkeypatch):
        self._mk(tmp_path, monkeypatch)
        self._scaffold(tmp_path)
        assert eng.ingest_agent_report(tmp_path, "t", "abc123")[0]
        ok, msg = eng.ingest_agent_report(tmp_path, "t", "abc123")
        assert not ok and "已收录" in msg

    def test_ingest_missing_payload_rejected(self, tmp_path, monkeypatch):
        self._mk(tmp_path, monkeypatch)
        ok, msg = eng.ingest_agent_report(tmp_path, "t", "abc123")
        assert not ok and "载荷不存在" in msg

    def test_ingest_unknown_task_id_rejected(self, tmp_path, monkeypatch):
        self._mk(tmp_path, monkeypatch)
        self._scaffold(tmp_path)
        ok, msg = eng.ingest_agent_report(tmp_path, "t", "zzz999")
        assert not ok and "找不到子代理 transcript" in msg

    def test_ingest_finds_segment_worker_transcript(self, tmp_path, monkeypatch):
        # v4 前台混合回归：agent 由段工人派发，transcript 在段工人 session 目录
        # （非 state.session_id="s" 的前台会话）。ingest 须 glob 找到
        # （2026-08-13 amplitude_annualized sub3 实证：62 轮逆向源码的根因）。
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=4)
        home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        enc = "".join(c if c.isalnum() else "-" for c in str(tmp_path))
        d = home / ".claude" / "projects" / enc / "seg-sid" / "subagents"
        d.mkdir(parents=True)
        with (d / "agent-abc123.jsonl").open("w", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [{"type": "text", "text": "蒸馏报告正文"}]
                        },
                    }
                )
                + "\n"
            )
        self._scaffold(tmp_path)
        ok, msg = eng.ingest_agent_report(tmp_path, "t", "abc123")
        assert ok, msg
        text = (tmp_path / ".trace-payload-t.md").read_text(encoding="utf-8")
        assert "蒸馏报告原文收录（task-id abc123）" in text


class TestTaskIdRe:
    """u1-sub5-cost 修1：_TASK_ID_RE 排除 float repr 误报。

    amplitude_annualized step5 三轮实测（轮1/2 共 4 次假阳性拒）：证据里的
    Python float repr 小数位 ≥16 位被 `\\b[0-9a-f]{16,17}\\b` 当 task-id →
    「已派发未收录」假阳性，模型为过关被迫改写合法证据数值。修复 = 候选须
    含 a-f 字母 + 前邻不得为 hex/`.`。误报 id 逐字取自真实 reject 消息。
    """

    def test_real_task_ids_match(self):
        for tid in ("a538a700d0d5e496d", "a9b273c9bd788e857", "a5ca6ea271e5e937e"):
            assert eng._TASK_ID_RE.findall(f"task-id {tid}") == [tid]
            assert eng._TASK_ID_RE.findall(f"task-id={tid}") == [tid]

    def test_float_fraction_reprs_excluded(self):
        # 轮1/2 真实误报 id 逐字（reject 消息原文）：全是证据数值的小数位段
        text = (
            "ob_quality raw = 0.49519773767901265 → 双转 4952%；"
            "coverage=0.9806949806949807；0.48244678899192833 无对应；"
            "残差 0.1194141004217242"
        )
        assert eng._TASK_ID_RE.findall(text) == []

    def test_pure_digit_runs_excluded(self):
        assert eng._TASK_ID_RE.findall("id 49519773767901265 缺收录") == []
        assert eng._TASK_ID_RE.findall("48244678899192833") == []

    def test_scientific_notation_excluded(self):
        # e 是 hex 字母——纯「含字母」规则会漏科学计数法，靠前邻 `.` 排除
        assert eng._TASK_ID_RE.findall("1.2345678901234567e-05") == []

    def test_pairing_unaffected_by_float_evidence(self):
        # 双向重放-放行侧：float 证据 + 真收录 → 无 missing（轮1/2 被拒载荷形态）
        qa = [
            {
                "q": "① 三关质检",
                "a": "E10 raw=0.49519773767901265 coverage=0.9806949806949807",
            },
            {
                "q": "②.5 红队输出原文收录（task-id a9b273c9bd788e857）",
                "a": "推理链：…；置信度：高",
            },
        ]
        assert eng._dispatched_vs_unrecorded_task_ids(qa) == []

    def test_pairing_missing_still_caught(self):
        # 双向重放-拦截侧（v2.118 牙齿保真）：真 task-id 无收录 → missing
        qa = [{"q": "② 派发", "a": "Agent task-id=a5ca6ea271e5e937e 已派发"}]
        assert eng._dispatched_vs_unrecorded_task_ids(qa) == ["a5ca6ea271e5e937e"]


class TestIngestRedteamPreDispatch:
    """u1-sub5-cost 修3：append-trace --ingest-redteam（driver 预派发报告收录）。

    红队改由 driver 在子4 gate 过后预派发（与子5 主会话并行），报告落
    meta/redteam_report.md；本命令阻塞等报告就绪（pid 死 + 报告非空）后
    以规定标题形态收录进载荷 qa 节。无预派发/无产出 → fail loud 指路回退
    会话内路径（redteam-prompt → Agent → --ingest-agent）。
    """

    _REPORT = "verdict: 部分成立\n推理链：E1→收窄边界\n置信度：高"

    def _mk(
        self,
        tmp_path,
        *,
        pid=None,
        report=_REPORT,
        worker_json=True,
        scaffold=True,
    ):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=5)
        meta = tmp_path / ".claude" / "workflows" / "t"
        if worker_json:
            (meta / "redteam_worker.json").write_text(
                json.dumps(
                    {
                        "pid": pid if pid is not None else 99999944,
                        "started_at": "x",
                        "prompt_sha1": "s",
                    }
                ),
                encoding="utf-8",
            )
        if report is not None:
            (meta / "redteam_report.md").write_text(report, encoding="utf-8")
        if scaffold:
            ok, msg = eng.scaffold_payload(tmp_path, "t")
            assert ok, msg
        return meta

    def test_happy(self, tmp_path):
        # pid 死（99999944 不存在）+ 报告非空 → 收录成功，标题含「红队」「原文收录」
        self._mk(tmp_path)
        ok, msg = eng.ingest_redteam_report(tmp_path, "t", timeout=1, interval=0.05)
        assert ok, msg
        text = (tmp_path / ".trace-payload-t.md").read_text(encoding="utf-8")
        assert "红队输出原文收录（driver 预派发）" in text
        assert "置信度：高" in text
        step = eng.get_node("understand", 1).sub_steps[4]
        payload, err = eng._parse_trace_md(text, step)
        assert err is None
        assert any("红队" in it["q"] and "原文收录" in it["q"] for it in payload["qa"])

    def test_no_worker_json_fallback(self, tmp_path):
        # v2 TUI / driver 未预派发 → 指路回退会话内路径
        self._mk(tmp_path, worker_json=False, report=None)
        ok, msg = eng.ingest_redteam_report(tmp_path, "t", timeout=1, interval=0.05)
        assert not ok and "ingest-agent" in msg and "redteam-prompt" in msg

    def test_dead_pid_empty_report_fallback(self, tmp_path):
        # worker 已死 + 报告空 → 预派发无产出，指路回退（不傻等）
        self._mk(tmp_path, report=None)
        ok, msg = eng.ingest_redteam_report(tmp_path, "t", timeout=5, interval=0.05)
        assert not ok and "无产出" in msg and "ingest-agent" in msg

    def test_delayed_report_succeeds(self, tmp_path):
        # 阻塞语义：报告在等待期间落盘（真实子进程 0.3s 后写并退出→pid 自然死）
        meta = self._mk(tmp_path, pid=None, report=None)
        report_path = meta / "redteam_report.md"
        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import time,sys;time.sleep(0.3);"
                "open(sys.argv[1],'w',encoding='utf-8').write(sys.argv[2])",
                str(report_path),
                self._REPORT,
            ]
        )
        (meta / "redteam_worker.json").write_text(
            json.dumps({"pid": proc.pid, "started_at": "x", "prompt_sha1": "s"}),
            encoding="utf-8",
        )
        ok, msg = eng.ingest_redteam_report(tmp_path, "t", timeout=5, interval=0.05)
        proc.wait(timeout=5)
        assert ok, msg

    def test_timeout_still_running(self, tmp_path):
        # pid 活（本进程）+ 报告空 → 等到超时，指路「继续①③④后重试」
        self._mk(tmp_path, pid=os.getpid(), report=None)
        ok, msg = eng.ingest_redteam_report(tmp_path, "t", timeout=0.3, interval=0.05)
        assert not ok and "未就绪" in msg

    def test_duplicate_rejected(self, tmp_path):
        self._mk(tmp_path)
        assert eng.ingest_redteam_report(tmp_path, "t", timeout=1, interval=0.05)[0]
        ok, msg = eng.ingest_redteam_report(tmp_path, "t", timeout=1, interval=0.05)
        assert not ok and "已收录" in msg

    def test_missing_payload_rejected(self, tmp_path):
        self._mk(tmp_path, scaffold=False)
        ok, msg = eng.ingest_redteam_report(tmp_path, "t", timeout=1, interval=0.05)
        assert not ok and "载荷不存在" in msg

    def test_json_wrapped_report_extracted(self, tmp_path):
        # --output-format json + ANTHROPIC_LOG 污染（rt_smoke 冒烟实测形态）：
        # 前文 [log_*] 请求转储，末行 result JSON——收录须只取 result 文本
        raw = (
            '[log_7484e5] sending request {\n  method: "POST",\n  body: {\n'
            '    model: "k3",\n  },\n}\n[log_7484e5] post https://… s\n'
            + json.dumps(
                {
                    "type": "result",
                    "is_error": False,
                    "result": self._REPORT,
                    "usage": {"input_tokens": 1},
                },
                ensure_ascii=False,
            )
        )
        self._mk(tmp_path, report=raw)
        ok, msg = eng.ingest_redteam_report(tmp_path, "t", timeout=1, interval=0.05)
        assert ok, msg
        text = (tmp_path / ".trace-payload-t.md").read_text(encoding="utf-8")
        assert "置信度：高" in text
        assert "[log_7484e5]" not in text

    def test_is_error_report_fallback(self, tmp_path):
        # result JSON is_error=true → 无产出，指路回退（不拿错误文本当报告收录）
        raw = json.dumps(
            {"type": "result", "is_error": True, "result": "provider error"},
            ensure_ascii=False,
        )
        self._mk(tmp_path, report=raw)
        ok, msg = eng.ingest_redteam_report(tmp_path, "t", timeout=1, interval=0.05)
        assert not ok and "无产出" in msg and "ingest-agent" in msg


class TestRenderReadback:
    """v2.61 render-readback：读回材料机械装配（审计违规③根治）。

    8 个读回步「完整呈现」= 无取舍 = 纯装配，原由模型手抄 traces——
    脚本装配打印（Bash 输出即呈现），模型只提问+记裁决。
    """

    def _seed(self, tmp_path, phase="understand", sub=1, step=6):
        _write_state_full(tmp_path, "t", phase, sub, sub_step=step)
        recs = [
            json.dumps(
                {
                    "kind": "skill-trace",
                    "minor_stage": "ProblemContext",
                    "sub_step": 4,
                    "q": ["处置后问题集", "不确定性"],
                    "a": ["H3 剔除：无证据", "覆盖率数据只到 6 月"],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "kind": "skill-trace",
                    "minor_stage": "ProblemContext",
                    "sub_step": 5,
                    "statements": [
                        {
                            "text": "年化显示 9529.8% 异常",
                            "type_label": "证实",
                            "boundary": "x.py:69",
                            "fields": {"confidence": "高"},
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        ]
        _write_evidence(tmp_path, "t", recs)

    def test_material_contains_statements_and_uncertainty(self, tmp_path):
        self._seed(tmp_path)
        ok, msg = eng.render_readback(tmp_path, "t")
        assert ok, msg
        assert "年化显示 9529.8% 异常（证实；x.py:69；confidence=高）" in msg
        assert "不确定性" in msg and "覆盖率数据只到 6 月" in msg
        assert "机械装配" in msg

    def test_other_node_traces_excluded(self, tmp_path):
        self._seed(tmp_path)
        ev = eng._evidence_path(tmp_path, "t")
        with ev.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "kind": "skill-trace",
                        "minor_stage": "GoalsAndValue",
                        "sub_step": 1,
                        "q": ["不确定性"],
                        "a": ["别节点的不确定不进来"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        ok, msg = eng.render_readback(tmp_path, "t")
        assert ok and "别节点的不确定不进来" not in msg

    def test_no_trace_fail_loud(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 2, sub_step=5)
        _write_evidence(tmp_path, "t", [])  # 文件在但本节点零 trace
        ok, msg = eng.render_readback(tmp_path, "t")
        assert not ok and "还没有任何 trace" in msg

    def test_readback_purpose_points_to_script(self):
        # 8 个读回步 purpose 全部指向 render-readback（禁手抄）
        for phase, sub in (
            ("understand", 1),
            ("understand", 2),
            ("understand", 3),
            ("understand", 4),
            ("plan", 1),
            ("plan", 2),
            ("plan", 3),
            ("plan", 4),
        ):
            node = eng.get_node(phase, sub)
            last = node.sub_steps[-1]
            assert "render-readback" in last.purpose, f"{phase}:{sub} 末步"
            assert last.tier == "confirm", f"{phase}:{sub} 末步（P3-1 确认级）"


class TestRenderArtifactDesignMd:
    """v2.62：design.md 进 render-artifact（v2.59 遗留项清零）。

    动态文件名 designs/<slug>-design.md（repo 根 designs/，非 .claude/）——
    slug 命名留模型（--slug），装配归脚本；八键 fields 全键渲染；
    已存在拒覆盖（--force 放行 state-reset 重跑）。
    """

    def _seed(self, tmp_path):
        fields = {
            k: f"{k} 值"
            for k in (
                "change_list",
                "interface_sig",
                "data_contract",
                "callers",
                "rejected",
                "assumptions",
                "acceptance_map",
                "h9_units",
            )
        }
        recs = [
            json.dumps(
                {
                    "kind": "skill-trace",
                    "minor_stage": "DesignSolution",
                    "sub_step": 5,
                    "statements": [
                        {
                            "text": "模板层删一次 *100",
                            "type_label": "推荐",
                            "boundary": "已证实边界 x.html:69",
                            "fields": fields,
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "kind": "skill-trace",
                    "minor_stage": "DesignSolution",
                    "sub_step": 6,
                    "q": ["裁决：选型拍板"],
                    "a": ["用户拍板推荐方案"],
                },
                ensure_ascii=False,
            ),
        ]
        _write_evidence(tmp_path, "t", recs)

    def test_design_md_full_render(self, tmp_path):
        self._seed(tmp_path)
        ok, msg = eng.render_artifact(tmp_path, "t", "design.md", slug="fix-double-pct")
        assert ok, msg
        out = tmp_path / "designs" / "fix-double-pct-design.md"
        text = out.read_text(encoding="utf-8")
        assert "## 设计决策" in text
        assert "### 模板层删一次 *100（推荐）" in text
        assert "- change_list：change_list 值" in text  # 八键全键渲染
        assert "- h9_units：h9_units 值" in text
        assert "## 裁决记录" in text and "用户拍板推荐方案" in text

    def test_design_md_slug_required(self, tmp_path):
        self._seed(tmp_path)
        ok, msg = eng.render_artifact(tmp_path, "t", "design.md")
        assert not ok and "--slug" in msg

    def test_design_md_slug_traversal_rejected(self, tmp_path):
        self._seed(tmp_path)
        for bad in ("../escape", "a/b", ".."):
            ok, _ = eng.render_artifact(tmp_path, "t", "design.md", slug=bad)
            assert not ok, bad

    def test_design_md_overwrite_refused_then_force(self, tmp_path):
        self._seed(tmp_path)
        assert eng.render_artifact(tmp_path, "t", "design.md", slug="x")[0]
        ok, msg = eng.render_artifact(tmp_path, "t", "design.md", slug="x")
        assert not ok and "已存在" in msg and "--force" in msg
        ok, _ = eng.render_artifact(tmp_path, "t", "design.md", slug="x", force=True)
        assert ok

    def test_design_md_missing_evidence_rejected(self, tmp_path):
        _write_evidence(tmp_path, "t", [])
        ok, _ = eng.render_artifact(tmp_path, "t", "design.md", slug="x")
        assert not ok  # evidence 空 -> evidence 缺失分支


class TestCLIIntermixedArgs:
    """v2.67：optional 插在 cmd 与 name 之间的参数序必须可解析。

    根因：argparse 已知缺陷——nargs='?' 位置参数（name/value）前隔 optional
    时 parse_args 无法匹配（'A O A' 形态），报 unrecognized arguments。
    2026-08-03 tail_volume_acceleration_annualized u:1 实证：模型按系统文案
    `append-trace --scaffold` 补显式 name -> 必败。正治=parse_intermixed_args。
    """

    def test_scaffold_flag_before_name(self, tmp_path, capsys):
        _init_git(tmp_path)
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        # 本次报错的逐字形态：optional 在 name 前
        rc = eng.main(["append-trace", "--scaffold", "t", "--cwd", str(tmp_path)])
        assert rc == 0
        assert (tmp_path / ".trace-payload-t.md").exists()

    def test_from_file_value_before_name(self, tmp_path, capsys):
        _init_git(tmp_path)
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        bad = tmp_path / "bad.md"
        bad.write_text("不是合法载荷", encoding="utf-8")
        # 带值 optional 插在 name 前同样曾必败；解析应成功、业务校验失败(rc=1)
        rc = eng.main(
            ["append-trace", "--from-file", str(bad), "t", "--cwd", str(tmp_path)]
        )
        assert rc == 1
        assert "unrecognized" not in capsys.readouterr().err

    def test_value_commands_unaffected(self, tmp_path, capsys):
        # dispute/state-reset/fence 的 value 业务在 intermixed 解析下不回归
        _init_git(tmp_path)
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        rc = eng.main(["fence", "t", "off", "--cwd", str(tmp_path)])
        assert rc == 0
        rc = eng.main(["fence", "t", "on", "--cwd", str(tmp_path)])
        assert rc == 0


class TestAnswerNoReverseInference:
    """v2.68 反推占答案位词形下沉机械层。

    实证（2026-08-03 tail_volume_acceleration_annualized u:1 子1 att1）：
    模型第 4 类没问用户，a[3] 填「三项标签反推…本项为反推项」（诚实披露
    词形），judge 判对但白烧一轮——词形下沉机械层=秒拒+精确返工指路。
    设计：designs/understand1-sub1-reverse-inference-option-design-design.md
    """

    def test_att1_verbatim_blocked(self):
        # att1 a[3] 逐字（词形来源：反推/暗含/隐含）
        qa = [
            {
                "q": "子1 pain 可观察后果类：9529.8% 异常持续存在，未修复时下游损害是什么？",
                "a": "「报告被消费时数字被用于选因子决策 → 选错因子 → 选出的因子"
                '并不是真实有效超收益」（用户隐含动作链；通过"项目维护者自查"+'
                '"排查并修代码"+"验证报告是否可信"三项标签反推——选项"排查并修'
                '代码"暗含"修复了才有可信输出可被消费"；选项"验证报告是否可信"'
                '暗含"不可信状态持续影响下游决策"。本项为反推项，不注入新事实）。',
            }
        ]
        err = eng._check_answer_no_reverse_inference(qa)
        assert err is not None and "反推" in err and "补问" in err

    def test_att2_verbatim_passes_mech(self):
        # att2 a[3] 逐字无反推词形——「包装成可观察后果」内容质量归 judge，
        # 机械不拦（分工边界，design §2 分工边界）
        qa = [
            {
                "q": "子1 pain 可观察后果类（返工补问，本轮新增）：若 9529.8% 异常不修，下游哪个环节会产生不同动作？",
                "a": '"报告整体可信度受损"+"其他因子也会被一起质疑"'
                "（AskUserQuestion 选中标注——选项标签属会话事实级，2026-08-03 "
                "本会话本轮）。可观察后果=其他因子被一并质疑→需一并复核→增加维护成本。",
            }
        ]
        assert eng._check_answer_no_reverse_inference(qa) is None

    def test_clean_selected_label_passes(self):
        qa = [
            {
                "q": "子1 是谁类：用户以何身份看这个数字？",
                "a": '"项目维护者自查"（AskUserQuestion 选中标注——选项标签属会话事实级）。',
            }
        ]
        assert eng._check_answer_no_reverse_inference(qa) is None

    def test_speculation_labeled_item_exempt(self):
        # 「推断标推测另列」是合法形态（_STEP1_FORM_REQUIREMENTS），宁纵勿枉
        qa = [
            {
                "q": "子1 补充观察：",
                "a": "（推测另列）用户隐含的意思可能是报告整体失真，未确认。",
            }
        ]
        assert eng._check_answer_no_reverse_inference(qa) is None


class TestOptionDesignRule:
    """v2.68 选项设计裁量点双侧钉死（att2 结构性必 block 根因）。

    _OPTION_DESIGN_RULE 单源，purpose/selfcheck（模型侧）+ gate（judge 侧）
    三处引用 + mech_checks 声明不回归（对齐 TestPainObservabilityRule 先例）。
    """

    def test_rule_cited_in_gate(self):
        gate = eng.get_node("understand", 1).sub_steps[0].gate
        assert "选项设计违规" in gate, "gate 未引用 _OPTION_DESIGN_RULE"
        # v2.71：framing 收口，"判词指向选项设计"并入通用"附改写范例"要求
        assert "改写范例" in gate

    def test_rule_disclosed_to_model(self):
        step = eng.get_node("understand", 1).sub_steps[0]
        assert "选项设计违规" in step.purpose
        assert "动作类" in step.purpose  # 正面范例披露（§3.5 #16 禁 prohibition-only）
        assert "动作类" in step.selfcheck
        assert "answer_no_reverse_inference" in step.mech_checks


class TestTracePayloadPath:
    """v2.125：载荷路径单源——state 有 worktree_path 落 worktree 根（出 .claude
    写入保护目录；acceptEdits 下 Edit 旧落点必弹窗），缺失则兜底旧 evidence 路径。"""

    def test_worktree_path_present_lands_in_worktree_root(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        p = eng.trace_payload_path(tmp_path, "t")
        assert p == tmp_path / ".trace-payload-t.md"

    def test_missing_worktree_path_falls_back_to_evidence_dir(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        st = json.loads(
            (tmp_path / ".claude" / "workflows" / "t" / "state.json").read_text(
                encoding="utf-8"
            )
        )
        del st["worktree_path"]
        (tmp_path / ".claude" / "workflows" / "t" / "state.json").write_text(
            json.dumps(st), encoding="utf-8"
        )
        p = eng.trace_payload_path(tmp_path, "t")
        assert p == tmp_path / ".claude" / "evidence" / ".trace-payload-t.md"

    def test_s11_allows_payload_at_worktree_root(self, tmp_path):
        # S11 phase 写围栏：understand 阶段写 worktree 根的载荷文件须放行
        # （旧白名单只认 .claude+evidence 路径段，新落点靠文件名豁免）。
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        fp = str(tmp_path / ".trace-payload-t.md")
        assert eng.phase_write_denial(tmp_path, "t", fp) is None


def _mem_state(phase, sub, sub_step=0, **extra):
    """内存 state（progress_rows 等纯函数测用，不落盘）。"""
    st = {
        "name": "t",
        "phase": phase,
        "index": eng.phase_index(phase),
        "sub_index": sub,
        "sub_total": eng.sub_total(phase),
        "node": eng.current_node_id(phase, sub),
        "sub_step_index": sub_step,
        "gate": "pending",
    }
    st.update(extra)
    return st


class TestProgressRows:
    """drive-tasklist-render-design §2.2：progress_rows 结构化行进数据（driver
    rich Live 渲染数据源；状态映射：节点线性序 < 当前=done / ==current / >todo，
    子步骤按 sub_step_index 同理；仅当前节点展开子步骤）。"""

    def _by_label(self, rows, label):
        (row,) = [r for r in rows if r["label"] == label]
        return row

    def test_initial_state_expands_only_current_node(self):
        rows = eng.progress_rows(_mem_state("understand", 1, 1))
        # 5 阶段 + understand 4 子阶段 + plan 4 子阶段 + 当前节点 7 子步骤
        assert len(rows) == 5 + 4 + 4 + 7
        p1 = self._by_label(rows, "1. 理解和求证问题")
        assert p1["depth"] == 0 and p1["status"] == "current"
        assert p1["extra"] == "gate: pending"
        assert self._by_label(rows, "1.1 理解问题和背景")["status"] == "current"
        assert self._by_label(rows, "1.2 明确目标和价值")["status"] == "todo"
        assert self._by_label(rows, "1 逼问定义")["status"] == "current"
        assert self._by_label(rows, "2 规划拆解")["status"] == "todo"
        assert self._by_label(rows, "7 读回确认")["status"] == "todo"
        assert self._by_label(rows, "2. 生成执行计划")["status"] == "todo"
        assert self._by_label(rows, "2.1 设计解决方案")["status"] == "todo"
        assert self._by_label(rows, "5. 进化")["status"] == "todo"

    def test_mid_node_substep_progress(self):
        rows = eng.progress_rows(_mem_state("understand", 1, 3))
        assert self._by_label(rows, "1 逼问定义")["status"] == "done"
        assert self._by_label(rows, "2 规划拆解")["status"] == "done"
        assert self._by_label(rows, "3 因果链挖掘")["status"] == "current"
        assert self._by_label(rows, "4 双向取证")["status"] == "todo"

    def test_later_node_collapses_prior_substeps(self):
        rows = eng.progress_rows(_mem_state("understand", 3, 2))
        # 5 + 4 + 4 + 当前节点 5 子步骤 = 18（前序节点子步骤不展开）
        assert len(rows) == 18
        assert self._by_label(rows, "1.1 理解问题和背景")["status"] == "done"
        assert self._by_label(rows, "1.2 明确目标和价值")["status"] == "done"
        assert self._by_label(rows, "1.3 确定范围与约束")["status"] == "current"
        assert self._by_label(rows, "1.4 定义成功标准和验收方式")["status"] == "todo"
        assert self._by_label(rows, "2 约束验证标注")["status"] == "current"

    def test_plan_node(self):
        rows = eng.progress_rows(_mem_state("plan", 2, 4))
        assert self._by_label(rows, "1. 理解和求证问题")["status"] == "done"
        assert self._by_label(rows, "1.1 理解问题和背景")["status"] == "done"
        assert self._by_label(rows, "2.1 设计解决方案")["status"] == "done"
        cur = self._by_label(rows, "2.2 拆解任务与阶段")
        assert cur["status"] == "current"
        assert self._by_label(rows, "4 归一化步骤")["status"] == "current"
        assert self._by_label(rows, "3. 执行")["status"] == "todo"

    def test_whole_phase_node_no_substep_rows(self):
        rows = eng.progress_rows(_mem_state("execute", 0, 0))
        # 整阶段节点无子步骤：仅 13 行（5 阶段 + 8 子阶段），无 depth=2
        assert len(rows) == 13
        assert not [r for r in rows if r["depth"] == 2]
        assert self._by_label(rows, "1. 理解和求证问题")["status"] == "done"
        assert self._by_label(rows, "2. 生成执行计划")["status"] == "done"
        p3 = self._by_label(rows, "3. 执行")
        assert p3["status"] == "current" and p3["extra"] == "gate: pending"
        assert self._by_label(rows, "5. 进化")["status"] == "todo"

    def test_gate_passed_shown_on_current_phase(self):
        rows = eng.progress_rows(_mem_state("plan", 4, 5, gate="passed"))
        assert self._by_label(rows, "2. 生成执行计划")["extra"] == "gate: passed"


class TestProblemStatement:
    """drive-tasklist-render-design §2.4：开场问题陈述入 state + handoff_pack
    顶部收录（恢复 v2.0「首条用户消息」语义——子1 模型开场即有用户原话）。"""

    def test_set_problem_statement_roundtrip(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        eng.set_problem_statement(tmp_path, "t", "annualized 显示 95% 不合常理")
        st = eng.load_state(tmp_path, "t")
        assert st["problem_statement"] == "annualized 显示 95% 不合常理"

    def test_pack_with_statement_but_no_traces(self, tmp_path):
        # 首次启动（零 trace）但有用户陈述 -> 交接包仍生成（陈述是唯一前序上下文）
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        eng.set_problem_statement(tmp_path, "t", "annualized 显示 95% 不合常理")
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None and "annualized 显示 95% 不合常理" in pack

    def test_pack_statement_before_traces(self, tmp_path):
        rec = {
            "kind": "skill-trace",
            "major_stage": "Understand",
            "minor_stage": "ProblemContext",
            "sub_step": 1,
            "skill": "s",
            "purpose": "p",
            "q": ["q_marker"],
            "a": ["a_marker"],
        }
        ev = tmp_path / ".claude" / "evidence"
        ev.mkdir(parents=True, exist_ok=True)
        (ev / "t.jsonl").write_text(
            json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=2)
        eng.set_problem_statement(tmp_path, "t", "annualized 显示 95% 不合常理")
        pack = eng.handoff_pack(tmp_path, "t")
        # 陈述在 trace 留痕之前（顶部收录）
        assert pack.index("annualized 显示 95% 不合常理") < pack.index("a_marker")

    def test_first_launch_without_statement_still_none(self, tmp_path):
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=1)
        assert eng.handoff_pack(tmp_path, "t") is None


class TestListTools:
    """组件 B：`dl list-tools` 打印当前项目注册的工具清单。

    codebase-archaeology-toolbox-design §3.2：发现层读
    <项目>/.claude/workflow-tools.yaml；list-tools 需 git repo（反查 project_root）
    但不需工作流 worktree（dl-cmd.sh 早路由，无 state 依赖）。
    """

    def test_prints_registered_tools(self, tmp_path, capsys):
        _init_git(tmp_path)
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "workflow-tools.yaml").write_text(
            "tools:\n"
            "  - name: inspect-backtest-result\n"
            "    command: scripts/inspect_backtest_result.py --factor {factor}\n"
            "    description: 读回测结果元数据\n",
            encoding="utf-8",
        )
        rc = eng.main(["list-tools", "--cwd", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "inspect-backtest-result" in out
        assert "scripts/inspect_backtest_result.py" in out

    def test_no_tools_prints_notice(self, tmp_path, capsys):
        _init_git(tmp_path)
        rc = eng.main(["list-tools", "--cwd", str(tmp_path)])
        assert rc == 0
        assert "无注册工具" in capsys.readouterr().out


def test_clear_workflow_discoveries(tmp_path):
    """state-reset 清账：删除 discoveries.jsonl；缺失非错误。"""
    meta = tmp_path / ".claude" / "workflows" / "t"
    meta.mkdir(parents=True)
    disc = meta / "discoveries.jsonl"
    disc.write_text('{"key":"symbol:x","kind":"symbol"}\n', encoding="utf-8")
    eng._clear_workflow_discoveries(tmp_path, "t")
    assert not disc.exists()
    eng._clear_workflow_discoveries(tmp_path, "t")  # 缺失时也非错误


# ---------- u1-overall-cost O1/O2/O3（designs/u1-overall-cost-optimization-design.md）----------


class TestNoMcpArgs:
    """O1：driver/engine spawn 的 claude 一律禁 MCP。编排全程禁 tavily（子4 purpose
    明文禁），但 MCP schema 照加载——探针实测（同端点裸 claude -p A/B）tavily
    schema = 2,504 tok/调用前缀，u:1 单轮 ~115 调用 = ~0.3M cache_read 纯税；
    且 --tools 限不住 MCP（红队 worker 经 MCP 调 tavily_extract 两次实证）——
    strict-mcp-config + 空表 = 结构封死。"""

    def test_no_mcp_args_shape(self):
        assert eng.NO_MCP_ARGS[0] == "--strict-mcp-config"
        assert eng.NO_MCP_ARGS[1] == "--mcp-config"
        cfg = json.loads(eng.NO_MCP_ARGS[2])
        assert cfg == {"mcpServers": {}}


class TestRenderSubstepsBrief:
    """O2：node-rules 清单瘦渲染——titles-only（map 骨架）+ 当前步标注。
    当前步完整目的双通道已在（段 prompt「目的：{step.purpose}」逐字携带 +
    TUI 每轮注入 primacy 置顶），其余步 purpose 全文是每调用重付的死重
    （node-rules.understand:1.md 实测 25,005 字符，其中 7 步 purpose 清单 ~15k）。
    与 workflow_phase 注入的既有形态一致（hooks/workflow_phase.py:385：
    当前步 purpose 全文置顶、其余只留骨架短名链）。"""

    def test_titles_only_plus_current_marker(self):
        text = eng.render_substeps_brief("understand:1", 3)
        # map 骨架：全部 7 步 short 在
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
        # 当前步标注
        assert "子步骤3" in text and "当前步" in text
        # 任何步的 purpose 全文都不在（当前步的由段 prompt 携带）
        assert "占环位" not in text  # 子3 purpose 独有词形
        assert "权威源注册表" not in text  # 子4
        assert "去上下文" not in text  # 子6
        # BEGIN/END 标记与全量渲染同形态（幂等/防漂移断言锚）
        assert "<!-- BEGIN GENERATED sub_steps understand:1 -->" in text
        assert "<!-- END GENERATED sub_steps understand:1 -->" in text

    def test_invalid_nid_raises(self):
        with pytest.raises(ValueError):
            eng.render_substeps_brief("not-a-node", 1)

    def test_node_without_substeps_raises(self):
        with pytest.raises(ValueError):
            eng.render_substeps_brief("execute:0", 1)


class TestPackStripReports:
    """O3：交接包「原文收录」隔步剥离。收录原文（fetch/红队报告全文）的唯一消费者
    是 u:1 子5（三关质检，Step.pack_full_reports=True）；其余步的包内收录项
    截断到 200 字符 + evidence 指针（真源 trace 不动，证据不丢）。"""

    def _write_evidence(self, tmp_path, records):
        ev = tmp_path / ".claude" / "evidence"
        ev.mkdir(parents=True, exist_ok=True)
        with open(ev / "t.jsonl", "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def _trace_with_report(
        self, step, body, title="蒸馏报告原文收录（task-id abc123）"
    ):
        return {
            "kind": "skill-trace",
            "major_stage": "Understand",
            "minor_stage": "ProblemContext",
            "sub_step": step,
            "skill": "s",
            "purpose": "p",
            "q": ["本步①工作项", title],
            "a": ["短答", body],
        }

    def test_u1_step5_is_sole_consumer(self):
        node = eng.get_node("understand", 1)
        flags = [bool(s.pack_full_reports) for s in node.sub_steps]
        assert flags == [False, False, False, False, True, False, False]

    def test_consumer_step_keeps_full_report(self, tmp_path):
        body = "R" * 500
        self._write_evidence(tmp_path, [self._trace_with_report(4, body)])
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=5)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None
        assert body in pack  # 子5=消费步：子4 收录全文保留

    def test_non_consumer_step_strips_report(self, tmp_path):
        body_r = "R" * 500
        body_t = "T" * 500
        self._write_evidence(
            tmp_path,
            [
                self._trace_with_report(4, body_r),
                self._trace_with_report(
                    5, body_t, title="红队输出原文收录（driver 预派发）"
                ),
            ],
        )
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=6)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None
        # 两份收录全文都剥离；截断到 200 + 指针
        assert body_r not in pack and body_t not in pack
        assert "R" * 200 in pack
        assert "evidence" in pack
        # 非收录项全文保留（子5 的处置问题集是子6 输入）
        assert "短答" in pack

    def test_malformed_trace_passthrough(self, tmp_path):
        # q/a 非列表 / 长度不齐：不崩、原样保留（宁纵勿枉）
        rec = {
            "kind": "skill-trace",
            "major_stage": "Understand",
            "minor_stage": "ProblemContext",
            "sub_step": 4,
            "skill": "s",
            "purpose": "p",
            "q": "not-a-list",
            "a": ["x"],
        }
        self._write_evidence(tmp_path, [rec])
        _write_state_full(tmp_path, "t", "understand", 1, sub_step=6)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None and "not-a-list" in pack


class TestPackSelfContained:
    """u2-sub2-cost（designs/u2-sub2-cost-optimization-design.md）：
    pack_self_contained 步的交接包尾行条件化 + 材料完备性装配不变量。

    u:2#2（对齐质检）矩阵输入 = 子1 目标候选（本节点前序留痕全文）
    + ProblemContext 存活问题陈述（前序节点结论摘要 statements 全文）
    ——全部在包内。通用尾行「以上为摘要；按需 Read evidence」对该步是
    反指邀请（u2_sub1_ab 实测：模型保险性全量读 68KB evidence = +19.6k
    fresh/+43s 零信息增量，且驻留污染链式下游冷启动各 +19.6k）。
    """

    def _write_evidence(self, tmp_path, records):
        ev = tmp_path / ".claude" / "evidence"
        ev.mkdir(parents=True, exist_ok=True)
        with open(ev / "t.jsonl", "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    @staticmethod
    def _pc_traces():
        return [
            {
                "kind": "skill-trace",
                "major_stage": "Understand",
                "minor_stage": "ProblemContext",
                "sub_step": 6,
                "skill": "s",
                "purpose": "p",
                "statements": [
                    {
                        "text": "存活问题陈述甲UNIQUEPC6",
                        "type_label": "证实",
                        "boundary": "b",
                        "fields": {"confidence": "高"},
                    }
                ],
            },
            {
                "kind": "skill-trace",
                "major_stage": "Understand",
                "minor_stage": "ProblemContext",
                "sub_step": 7,
                "skill": "s",
                "purpose": "p",
                "q": ["读回"],
                "a": ["确认级静默通过"],
            },
        ]

    @staticmethod
    def _gav_step1_trace():
        return {
            "kind": "skill-trace",
            "major_stage": "Understand",
            "minor_stage": "GoalsAndValue",
            "sub_step": 1,
            "skill": "s",
            "purpose": "p",
            "q": ["outcome 问"],
            "a": ["目标候选UNIQUEG1附出处"],
        }

    def test_u2_step2_flag_single_source(self):
        node = eng.get_node("understand", 2)
        flags = [bool(s.pack_self_contained) for s in node.sub_steps]
        assert flags == [False, True, False, False, False]

    def test_tail_line_replaced_for_self_contained_step(self, tmp_path):
        self._write_evidence(tmp_path, self._pc_traces() + [self._gav_step1_trace()])
        _write_state_full(tmp_path, "t", "understand", 2, sub_step=2)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None
        assert "本步所需材料已全部在包内" in pack
        assert "以上为摘要" not in pack

    def test_tail_line_default_for_other_steps(self, tmp_path):
        self._write_evidence(tmp_path, self._pc_traces() + [self._gav_step1_trace()])
        _write_state_full(tmp_path, "t", "understand", 2, sub_step=3)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None
        assert "以上为摘要；前序细节按需 Read" in pack
        assert "本步所需材料已全部在包内" not in pack

    def test_materials_complete_invariant(self, tmp_path):
        """装配不变量：u:2#2 的包须含子1 trace 内容 + PC 子6 statement 全文——
        防未来 P1-1 类交接包修剪把材料修没了、「禁读」条款变错。"""
        self._write_evidence(tmp_path, self._pc_traces() + [self._gav_step1_trace()])
        _write_state_full(tmp_path, "t", "understand", 2, sub_step=2)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None
        assert "存活问题陈述甲UNIQUEPC6" in pack  # PC 子6 存活问题全文
        assert "目标候选UNIQUEG1附出处" in pack  # 子1 目标候选+出处全文

    @staticmethod
    def _sc_traces():
        return [
            {
                "kind": "skill-trace",
                "major_stage": "Understand",
                "minor_stage": "ScopeAndConstraints",
                "sub_step": 1,
                "skill": "s",
                "purpose": "p",
                "q": ["否定提问"],
                "a": ["约束候选UNIQUESC1"],
            },
            {
                "kind": "skill-trace",
                "major_stage": "Understand",
                "minor_stage": "ScopeAndConstraints",
                "sub_step": 2,
                "skill": "s",
                "purpose": "p",
                "q": ["三态处置"],
                "a": ["已验证留痕UNIQUESC2附fileline"],
            },
        ]

    def test_u3_pack_self_contained_flags(self):
        # u3-sub3-cost：u:3#3 置位（消费型步——材料=子2 验证留痕全文+GAV 裁决，
        # 均在包内）；u3-sub4-cost：u:3#4 同型置位（材料=子3 范围与约束集全文，
        # 在本节点留痕节）；兄弟步不置位（子1/子2 须规范文档在场，B1 决议不
        # 下放；子5 交互读回补用户裁决非纯消费）。
        node = eng.get_node("understand", 3)
        flags = [bool(s.pack_self_contained) for s in node.sub_steps]
        assert flags == [False, False, True, True, False]

    @staticmethod
    def _gav_decision_traces():
        return [
            {
                "kind": "skill-trace",
                "major_stage": "Understand",
                "minor_stage": "GoalsAndValue",
                "sub_step": 4,
                "skill": "s",
                "purpose": "p",
                "statements": [
                    {
                        "text": "归一化目标UNIQUEG4",
                        "type_label": "must",
                        "boundary": "b",
                        "fields": {},
                    }
                ],
            },
            {
                "kind": "skill-trace",
                "major_stage": "Understand",
                "minor_stage": "GoalsAndValue",
                "sub_step": 5,
                "skill": "s",
                "purpose": "p",
                "q": ["读回"],
                "a": ["用户裁决UNIQUEG5拍板must"],
            },
        ]

    def test_u3_step3_tail_line_replaced(self, tmp_path):
        self._write_evidence(
            tmp_path,
            self._pc_traces() + self._gav_decision_traces() + self._sc_traces(),
        )
        _write_state_full(tmp_path, "t", "understand", 3, sub_step=3)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None
        assert "本步所需材料已全部在包内" in pack
        assert "以上为摘要" not in pack

    def test_u3_step3_materials_complete_invariant(self, tmp_path):
        """装配不变量：u:3#3 的包须含子2 验证留痕全文（本节点留痕节）+
        GAV 归一化陈述与用户裁决（前序摘要节）——复用优先条款（L1）的材料前提。"""
        self._write_evidence(
            tmp_path,
            self._pc_traces() + self._gav_decision_traces() + self._sc_traces(),
        )
        _write_state_full(tmp_path, "t", "understand", 3, sub_step=3)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None
        assert "已验证留痕UNIQUESC2附fileline" in pack  # 子2 留痕全文（复用源）
        assert "约束候选UNIQUESC1" in pack  # 子1 候选（本节点留痕节）
        assert "归一化目标UNIQUEG4" in pack  # GAV 归一化（前序摘要节）
        assert "用户裁决UNIQUEG5拍板must" in pack  # GAV 用户裁决（前序摘要节）

    @staticmethod
    def _sc_step3_trace():
        return {
            "kind": "skill-trace",
            "major_stage": "Understand",
            "minor_stage": "ScopeAndConstraints",
            "sub_step": 3,
            "skill": "s",
            "purpose": "p",
            "q": ["范围界定"],
            "a": ["范围提案UNIQUESC3双侧清单双字段"],
        }

    def test_u3_step4_tail_line_replaced(self, tmp_path):
        # u3-sub4-cost：u:3#4（归一化陈述）置位——包尾「按需 Read」通用邀请
        # 对该步是反指（基线 6 次 evidence 元探查实证，#16 第三例）。
        self._write_evidence(
            tmp_path,
            self._pc_traces()
            + self._gav_decision_traces()
            + self._sc_traces()
            + [self._sc_step3_trace()],
        )
        _write_state_full(tmp_path, "t", "understand", 3, sub_step=4)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None
        assert "本步所需材料已全部在包内" in pack
        assert "以上为摘要" not in pack

    def test_u3_step4_materials_complete_invariant(self, tmp_path):
        """装配不变量：u:3#4 的包须含子3 范围与约束集全文（本节点留痕节）——
        输入契约 step3.scope_proposal 的唯一材料来源；防未来交接包修剪把
        材料修没了、「禁读」条款变错。"""
        self._write_evidence(
            tmp_path,
            self._pc_traces()
            + self._gav_decision_traces()
            + self._sc_traces()
            + [self._sc_step3_trace()],
        )
        _write_state_full(tmp_path, "t", "understand", 3, sub_step=4)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None
        assert "范围提案UNIQUESC3双侧清单双字段" in pack  # 子3 留痕全文（装配材料）
        assert "已验证留痕UNIQUESC2附fileline" in pack  # 子2 留痕（类型标签溯源）

    @staticmethod
    def _sc_decision_traces():
        return [
            {
                "kind": "skill-trace",
                "major_stage": "Understand",
                "minor_stage": "ScopeAndConstraints",
                "sub_step": 4,
                "skill": "s",
                "purpose": "p",
                "statements": [
                    {
                        "text": "归一化范围约束UNIQUESC4含inout双侧",
                        "type_label": "in",
                        "boundary": "b",
                    }
                ],
            },
            {
                "kind": "skill-trace",
                "major_stage": "Understand",
                "minor_stage": "ScopeAndConstraints",
                "sub_step": 5,
                "skill": "s",
                "purpose": "p",
                "q": ["读回"],
                "a": ["确认级静默通过"],
            },
        ]

    def test_u4_pack_self_contained_flags(self):
        # u4-sub1-cost（designs/u4-sub1-cost-optimization-design.md L3）：
        # u:4#1 置位（交互步置位首例——声明输入 = GAV/SC 两节点 step4
        # statements，均在包内前序摘要节）；u4-sub4-cost：u:4#4 置位（第五例——
        # 消费装配步，输入契约 = 子3 标准集全文，在本节点留痕节逐字在场，
        # 基线 A1/A2 evidence 元探查零信息增量实证）；兄弟步不置位
        # （#2/#3 验证/测量步要跑 Bash 取证，非纯消费；#5 确认级无会话）。
        node = eng.get_node("understand", 4)
        flags = [bool(s.pack_self_contained) for s in node.sub_steps]
        assert flags == [True, False, False, True, False]

    def test_u4_step1_tail_line_replaced(self, tmp_path):
        self._write_evidence(
            tmp_path,
            self._gav_decision_traces() + self._sc_decision_traces(),
        )
        _write_state_full(tmp_path, "t", "understand", 4, sub_step=1)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None
        assert "本步所需材料已全部在包内" in pack
        assert "以上为摘要" not in pack

    def test_u4_step1_materials_complete_invariant(self, tmp_path):
        """装配不变量：u:4#1 的包须含 GAV step4 + SC step4 statements 全文
        （声明输入的两项唯一材料来源）——防未来交接包修剪把材料修没了、
        「禁读」条款变错。"""
        self._write_evidence(
            tmp_path,
            self._gav_decision_traces() + self._sc_decision_traces(),
        )
        _write_state_full(tmp_path, "t", "understand", 4, sub_step=1)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None
        assert "归一化目标UNIQUEG4" in pack  # GAV step4 statements 全文
        assert "归一化范围约束UNIQUESC4含inout双侧" in pack  # SC step4 同上

    @staticmethod
    def _success_criteria_step3_trace():
        return {
            "kind": "skill-trace",
            "major_stage": "Understand",
            "minor_stage": "SuccessCriteria",
            "sub_step": 3,
            "skill": "s",
            "purpose": "p",
            "q": ["验收方式设计"],
            "a": ["四法三态UNIQUESC43验收包六字段传导链"],
        }

    def test_u4_step4_tail_line_replaced(self, tmp_path):
        # u4-sub4-cost：u:4#4（归一化陈述）置位——包尾「按需 Read」通用邀请
        # 对该步是反指（基线 A1/A2 evidence 元探查实证，#16 第五例）。
        self._write_evidence(
            tmp_path,
            self._gav_decision_traces()
            + self._sc_decision_traces()
            + [self._success_criteria_step3_trace()],
        )
        _write_state_full(tmp_path, "t", "understand", 4, sub_step=4)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None
        assert "本步所需材料已全部在包内" in pack
        assert "以上为摘要" not in pack

    def test_u4_step4_materials_complete_invariant(self, tmp_path):
        """装配不变量：u:4#4 的包须含子3 标准集全文（本节点留痕节）——
        输入契约 step3.criteria_with_acceptance 的唯一材料来源；防未来
        交接包修剪把材料修没了、「禁读」条款变错。"""
        self._write_evidence(
            tmp_path,
            self._gav_decision_traces()
            + self._sc_decision_traces()
            + [self._success_criteria_step3_trace()],
        )
        _write_state_full(tmp_path, "t", "understand", 4, sub_step=4)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None
        assert (
            "四法三态UNIQUESC43验收包六字段传导链" in pack
        )  # 子3 留痕全文（装配材料）

    @staticmethod
    def _ds_step1_trace():
        return {
            "kind": "skill-trace",
            "major_stage": "Plan",
            "minor_stage": "DesignSolution",
            "sub_step": 1,
            "skill": "s",
            "purpose": "p",
            "q": ["现状勘察"],
            "a": ["现状地图UNIQUEDS1四要素齐备附fileline"],
        }

    def test_p1_step2_pack_self_contained_flags(self):
        # p1-sub2-cost L3（designs/p1-sub2-cost-optimization-design.md）：
        # plan:1#2 置位（交互步第二例）——输入契约 step1.terrain_map 经
        # 本节点前序留痕全文通道在包（ab2 真迹四步核对：零包外取证、gate
        # 凭空设计判据使包外材料结构性不可用=#19 判别意图不命中）；
        # 兄弟步不置位（#1 勘察步/#3 验证步要跑 Bash 取证，#6 确认级；
        # #5 于 p1-sub5-cost 置位）。
        # p1-sub4-cost：#4 置位（非交互步第三例）——输入契约（子2 候选+
        # 子3 三态核验+must 目标集+验收包）全在包（生产真迹四步核对：
        # 引文跨度 4/9 精确命中+5 条同源转写、事实项全命中，见设计 §2）。
        node = eng.get_node("plan", 1)
        flags = [bool(s.pack_self_contained) for s in node.sub_steps]
        assert flags == [False, True, False, True, True, False]

    def test_p1_step2_tail_line_replaced(self, tmp_path):
        # 尾行条件化挂在 prior_sections 非空分支——须带前序节点（understand
        # 族）末两步留痕，同 u4 测试写法。
        self._write_evidence(tmp_path, self._pc_traces() + [self._ds_step1_trace()])
        _write_state_full(tmp_path, "t", "plan", 1, sub_step=2)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None
        assert "本步所需材料已全部在包内" in pack
        assert "以上为摘要" not in pack

    def test_p1_step2_materials_complete_invariant(self, tmp_path):
        """装配不变量：plan:1#2 的包须含子1 现状勘察留痕全文（本节点留痕
        节）——输入契约 step1.terrain_map 的唯一材料来源；防未来交接包
        修剪把材料修没了、「禁读」条款变错。"""
        self._write_evidence(tmp_path, self._pc_traces() + [self._ds_step1_trace()])
        _write_state_full(tmp_path, "t", "plan", 1, sub_step=2)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None
        assert "现状地图UNIQUEDS1四要素齐备附fileline" in pack  # 子1 留痕全文

    @staticmethod
    def _ds_traces_thru4():
        # p1-sub5-cost 子5 装配不变量夹具：子1-子4 留痕各带 UNIQUE 标记。
        base = {
            "kind": "skill-trace",
            "major_stage": "Plan",
            "minor_stage": "DesignSolution",
            "skill": "s",
            "purpose": "p",
        }
        return [
            {**base, "sub_step": 1, "q": ["现状勘察"], "a": ["现状地图UNIQUEDS1"]},
            {**base, "sub_step": 2, "q": ["方案发散"], "a": ["候选集UNIQUEDS2"]},
            {**base, "sub_step": 3, "q": ["可行性验证"], "a": ["三态核验UNIQUEDS3"]},
            {**base, "sub_step": 4, "q": ["评估提案"], "a": ["推荐结论UNIQUEDS4"]},
        ]

    def test_p1_step5_tail_line_replaced(self, tmp_path):
        # p1-sub5-cost L2：plan:1#5 置位（非交互步第四例）——归一化材料=
        # 子1-子4 留痕全文+前序节点摘要，全在包内；通用「按需 Read」邀请
        # 对断链后 fresh 口径是 evidence 翻找反指（u:4#4 前车）。
        self._write_evidence(tmp_path, self._pc_traces() + self._ds_traces_thru4())
        _write_state_full(tmp_path, "t", "plan", 1, sub_step=5)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None
        assert "本步所需材料已全部在包内" in pack
        assert "以上为摘要" not in pack

    def test_p1_step5_materials_complete_invariant(self, tmp_path):
        """装配不变量：plan:1#5 的包须含子1-子4 各步留痕全文（本节点留痕
        节）——归一化八键的唯一材料来源（L1 复用钉死「无取证例外」的材料
        前提）；防未来交接包修剪把材料修没了、「禁读」条款变错。"""
        self._write_evidence(tmp_path, self._pc_traces() + self._ds_traces_thru4())
        _write_state_full(tmp_path, "t", "plan", 1, sub_step=5)
        pack = eng.handoff_pack(tmp_path, "t")
        assert pack is not None
        for marker in ("UNIQUEDS1", "UNIQUEDS2", "UNIQUEDS3", "UNIQUEDS4"):
            assert marker in pack, marker  # 子1-子4 留痕全文


class TestSegmentSpawnOverrides:
    """u2-residual-cost（designs/u2-residual-cost-optimization-design.md）：
    段前缀外科剥离——Node 声明式字段（segment_strip_project_context /
    segment_tools）→ spawn 覆盖单源。探针实证（2026-08-18，2.1.234）：
    DISABLE 对 -11.9k（hooks 照常触发）、--tools 白名单再 -14.3k；
    CLAUDE_CODE_SIMPLE=1 fresh 更低但 hooks 全灭（S11/S14 丢失）禁用。"""

    def test_u2_strip_and_tools(self):
        ov = eng.segment_spawn_overrides(eng._NODES["understand:2"])
        assert ov["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
        assert ov["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
        assert ov["tools"] == ("Bash", "Read", "Edit", "Skill")

    def test_u1_strip_and_tools_with_agent(self):
        # u1-prefix-strip：u:1 置位（白名单含 Agent——子4 双向取证派发依赖，
        # 探针 J 实证可派发）；红队预派发 worker 同步剥 env。
        ov = eng.segment_spawn_overrides(eng._NODES["understand:1"])
        assert ov["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
        assert ov["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
        assert ov["tools"] == ("Bash", "Read", "Edit", "Skill", "Agent")

    def test_u1_step6_format_clause_pinned(self):
        # u1-time-opt 修B：L4 格式真源钉死平移第三例（u:3#4 同文——本步有
        # 条目传导机械核对，保留「编号传导」）。interaction run u1#6 实证：
        # 条目传导被拒（缺 factor[D]，报错文案已指路）后模型不修文案反而
        # evidence 元探查 10 调用 + Read/grep 引擎源码反推校验实现（2.3min
        # 格式猎捕）。关键词钉死防未来编辑静默改丢。
        step6 = eng._NODES["understand:1"].sub_steps[5]
        assert "载荷格式与编号传导的唯一真源" in step6.purpose
        assert "--scaffold 骨架" in step6.purpose
        assert "禁读引擎/测试源码反推校验实现" in step6.purpose
        assert "格式照 scaffold 骨架填了吗" in step6.selfcheck

    def test_u3_tools_only_no_env_strip(self):
        # u3-sub1-cost：u:3 置位 tools-only（#23 泛化第三例，TUI 交互段管线同
        # 机制受益）。env 剥离刻意不置位——u3_sub1_ab 实证：约束分类把「项目
        # 硬规则」列为一等约束源，自动加载的 CLAUDE.md 是任务功能材料，剥掉
        # 诱发重读（+40k 驻留 + 87k 冷重付），总账反超。
        ov = eng.segment_spawn_overrides(eng._NODES["understand:3"])
        assert ov["env"] == {}
        assert ov["tools"] == ("Bash", "Read", "Edit", "Skill")

    def test_other_nodes_zero_change(self):
        # 白名单外节点零行为变化（字段默认 False/None）——回滚面即字段翻转
        for key, node in eng._NODES.items():
            if key in ("understand:1", "understand:2", "understand:3"):
                continue
            ov = eng.segment_spawn_overrides(node)
            assert ov["env"] == {}, key
            if key in ("understand:4", "plan:1"):
                continue  # u4-sub1-cost / p1-sub1-cost：tools-only 置位（env 仍空）
            assert ov["tools"] is None, key

    def test_u4_tools_only_no_env_strip(self):
        # u4-sub1-cost（designs/u4-sub1-cost-optimization-design.md L1）：
        # u:4 置位 tools-only（同 u:3 型——env 剥离不下放节点级，逐步见子1）。
        # Agent 不在单 = 机制堵「为后续步预取证据」步骤越界（u3_sub4_ab
        # 基线：子1 段派发 2 个 Explore 为子3 预取 file:line 纯税）。
        ov = eng.segment_spawn_overrides(eng._NODES["understand:4"])
        assert ov["env"] == {}
        assert ov["tools"] == ("Bash", "Read", "Edit", "Skill")

    def test_u4_step1_step_level_strip(self):
        # u4-sub1-cost L2：u:4#1 Step 级 strip（第三例——交互步置位首例：
        # 交付物正文不引用自动加载文档，材料经交接包/prep 载荷逐字在场）。
        node = eng._NODES["understand:4"]
        step1 = node.sub_steps[0]
        ov = eng.segment_spawn_overrides(node, step1)
        assert ov["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
        assert ov["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
        assert ov["tools"] == ("Bash", "Read", "Edit", "Skill")

    def test_u4_step2_step_level_strip(self):
        # u4-sub2-cost L1（designs/u4-sub2-cost-optimization-design.md）：
        # u:4#2 Step 级 strip（第四例，u:4 内第二例）——交付物=fit criterion
        # 三要素，正文不点名项目硬规则条号（与 u:3#1 反型不同型）；工具需求
        # Bash/Read/Edit 全在 Node 白名单内。
        node = eng._NODES["understand:4"]
        step2 = node.sub_steps[1]
        ov = eng.segment_spawn_overrides(node, step2)
        assert ov["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
        assert ov["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
        assert ov["tools"] == ("Bash", "Read", "Edit", "Skill")

    def test_u4_step2_reuse_clause_pinned(self):
        # u4-sub2-cost L2：purpose/selfcheck 复用钉死条款（#25 收紧形态）
        # 关键词钉死——防未来编辑把条款静默改丢（条款是本步成本主杠杆：
        # 基线 12 探索 Bash 中 ~10 纯税=重复核验+子3 越界勘察）。
        step2 = eng._NODES["understand:4"].sub_steps[1]
        assert "零重复核验" in step2.purpose
        assert "本步零勘察" in step2.purpose and "归子3" in step2.purpose
        assert "每条候选最多一次" in step2.purpose
        assert "本步零勘察" in step2.selfcheck

    def test_u4_step3_step_level_strip(self):
        # u4-sub3-cost L2（designs/u4-sub3-cost-optimization-design.md）：
        # u:4#3 Step 级 strip（第五例，u:4 内第三例）——交付物=四法选择+三态
        # 处置+时机+证据形式，正文不点名项目硬规则条号（与 u:4#1/#2 同型：
        # 材料经交接包逐字在场）；工具需求 Bash/Read/Edit 全在 Node 白名单内。
        node = eng._NODES["understand:4"]
        step3 = node.sub_steps[2]
        ov = eng.segment_spawn_overrides(node, step3)
        assert ov["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
        assert ov["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
        assert ov["tools"] == ("Bash", "Read", "Edit", "Skill")

    def test_u4_step3_reuse_clause_pinned(self):
        # u4-sub3-cost L3：purpose/selfcheck 复用钉死条款（#25 收紧形态——
        # 默认零重验+枚举例外+按条配额）关键词钉死——防未来编辑把条款静默
        # 改丢（条款是本步步体主杠杆：基线 13 探索 Bash 中 ~8-10 纯税/半税
        # =重复验证包内已证存在性+超出存在性粒度的掘进）。
        step3 = eng._NODES["understand:4"].sub_steps[2]
        assert "零重跑重验" in step3.purpose
        assert "复用 <节点>子N 留痕" in step3.purpose
        assert "每条标准最多一次" in step3.purpose
        assert "验存在即止" in step3.purpose
        assert "零 evidence 全量翻找" in step3.purpose
        assert "零重跑重验" in step3.selfcheck

    def test_u4_step4_step_level_strip(self):
        # u4-sub4-cost L1（designs/u4-sub4-cost-optimization-design.md）：
        # u:4#4 Step 级 strip（第六例，u:4 内第四例）——消费装配步：交付物
        # text 只许 outcome-level、规则内容经 purpose 常量逐字在场、方案名词
        # 扫描在 append-trace 脚本侧（与 u:3#4 同型）；工具需求 Bash/Read/Edit
        # 全在 Node 白名单内。
        node = eng._NODES["understand:4"]
        step4 = node.sub_steps[3]
        ov = eng.segment_spawn_overrides(node, step4)
        assert ov["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
        assert ov["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
        assert ov["tools"] == ("Bash", "Read", "Edit", "Skill")

    def test_u4_step4_format_clause_pinned(self):
        # u4-sub4-cost L3：purpose/selfcheck 格式真源钉死条款（#26 平移第二例）
        # 关键词钉死——防未来编辑把条款静默改丢（条款是格式猎捕主杠杆：
        # 基线 A2 grep designs/引擎源码反推载荷格式 5+ 调用）。
        step4 = eng._NODES["understand:4"].sub_steps[3]
        assert "载荷格式的唯一真源" in step4.purpose
        assert "--scaffold 骨架" in step4.purpose
        assert "禁读引擎/测试源码反推校验实现" in step4.purpose
        assert "格式照 scaffold 骨架填了吗" in step4.selfcheck

    def test_u4_other_steps_no_step_strip(self):
        # 逐步粒度不误伤兄弟步（#5 确认级无会话不置位；#1/#2/#3/#4 已置位
        # 见上四测试）。
        node = eng._NODES["understand:4"]
        for i, step in enumerate(node.sub_steps, start=1):
            if i in (1, 2, 3, 4):
                continue
            assert eng.segment_spawn_overrides(node, step)["env"] == {}, i

    def test_u3_step3_step_level_strip(self):
        # u3-sub3-cost（designs/u3-sub3-cost-optimization-design.md）：Step 级
        # segment_strip_project_context——B1 决议是节点级（子1/子2 须规则原文
        # 在场），子3 是消费步（规则内容经子2 trace 逐字在场）可单独置位。
        node = eng._NODES["understand:3"]
        step3 = node.sub_steps[2]
        ov = eng.segment_spawn_overrides(node, step3)
        assert ov["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
        assert ov["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
        assert ov["tools"] == ("Bash", "Read", "Edit", "Skill")

    def test_u3_step4_step_level_strip(self):
        # u3-sub4-cost（designs/u3-sub4-cost-optimization-design.md）：子4 同型
        # 置位——纯消费装配步（规则内容经 purpose 常量在场、方案名词扫描在
        # 脚本侧），B1 节点级决议不下放但逐步粒度覆盖本步。
        node = eng._NODES["understand:3"]
        step4 = node.sub_steps[3]
        ov = eng.segment_spawn_overrides(node, step4)
        assert ov["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
        assert ov["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
        assert ov["tools"] == ("Bash", "Read", "Edit", "Skill")

    def test_p1_tools_whitelist_no_env_strip(self):
        # p1-sub1-cost L2（designs/p1-sub1-cost-optimization-design.md）：
        # plan:1 置位 tools-only（plan 族首例）——逐步需求并集六件
        # （Bash/Read/Edit/Grep/Skill/Agent，子4 条件红队要 Agent、子5 要
        # Skill、子1 ref 明写 Grep）；env 剥离不下放节点级（子2-6 逐步
        # 核对未做），子1 逐步置位见下一测试。
        ov = eng.segment_spawn_overrides(eng._NODES["plan:1"])
        assert ov["env"] == {}
        assert ov["tools"] == ("Bash", "Read", "Edit", "Grep", "Skill", "Agent")

    def test_p1_step1_step_level_strip(self):
        # p1-sub1-cost L1：plan:1#1 Step 级 strip（第七例）——交付物=四要素
        # 现状事实+新鲜度判定，无点名项目硬规则条号职责；新鲜度通道由
        # dl codebase freshness 补位（原 SQL 只在项目 CLAUDE.md）。
        node = eng._NODES["plan:1"]
        step1 = node.sub_steps[0]
        ov = eng.segment_spawn_overrides(node, step1)
        assert ov["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
        assert ov["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
        assert ov["tools"] == ("Bash", "Read", "Edit", "Grep", "Skill", "Agent")

    def test_p1_other_steps_no_step_strip(self):
        # 逐步粒度不误伤兄弟步（子6 确认级逐步核对未做——钉死防未来误置位；
        # 子2 于 p1-sub2-cost 置位；子3 于 p1-sub3-cost 核对后结论=不置位：
        # ④硬规则核验须点名规则条号=一等材料，#23 第三核对不通过，u:3#1 反
        # 优化同型；子4 于 p1-sub4-cost 置位=消费步（H 条号经子3 留痕逐字
        # 在场）；子5 于 p1-sub5-cost 置位=消费步（H9 阈值经子3/子4 trace
        # 逐字在场非一等材料，与子3 验证步不同型））。
        node = eng._NODES["plan:1"]
        for i, step in enumerate(node.sub_steps, start=1):
            if i in (1, 2, 4, 5):
                continue
            assert eng.segment_spawn_overrides(node, step)["env"] == {}, i

    def test_p1_step5_step_level_strip(self):
        # p1-sub5-cost L3（designs/p1-sub5-cost-optimization-design.md）：
        # plan:1#5 Step 级 strip——消费步（交付物正文唯一规则内容=H9 阈值，
        # 经子3「≤3 文件」/子4「200 行」trace 逐字在包，非一等材料直引规范
        # 文档）；工具需求 Bash/Read/Edit/Skill 全在 Node 白名单既有面。
        node = eng._NODES["plan:1"]
        step5 = node.sub_steps[4]
        ov = eng.segment_spawn_overrides(node, step5)
        assert ov["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
        assert ov["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
        assert ov["tools"] == ("Bash", "Read", "Edit", "Grep", "Skill", "Agent")

    def test_p1_step4_step_level_strip(self):
        # p1-sub4-cost L1：plan:1#4 Step 级 strip（第九例）——交付物=矩阵
        # 评分+双向追溯+红队留痕（消费步，规则事实经子3 留痕逐字在场，
        # 不引自动加载文档为一等材料）；工具需求 Bash/Read/Edit/Agent
        # 全在 Node 白名单既有面。
        node = eng._NODES["plan:1"]
        step4 = node.sub_steps[3]
        ov = eng.segment_spawn_overrides(node, step4)
        assert ov["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
        assert ov["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
        assert ov["tools"] == ("Bash", "Read", "Edit", "Grep", "Skill", "Agent")

    def test_p1_step4_reuse_and_redteam_clause_pinned(self):
        # p1-sub4-cost L3/L4/L5（designs/p1-sub4-cost-optimization-design.md）：
        # 复用钉死（消费步形态）+格式真源钉死+红队材料包钉死关键词——
        # 防未来编辑静默改丢（红队条款是本步主杠杆：基线红队侧等效占
        # 子4 总账 ~73%=agent 零材料 prompt 致独立重勘 25-58 调用/agent）。
        step4 = eng._NODES["plan:1"].sub_steps[3]
        assert "本步零新取证" in step4.purpose
        assert "零 evidence 全量翻找" in step4.purpose
        assert "唯一取证面=条件红队派发" in step4.purpose
        assert "格式与传导核对细节的唯一真源=--scaffold 骨架" in step4.purpose
        assert "逐字携带攻击对象材料" in step4.purpose
        assert "禁重跑 codegraph/grep 全仓勘察" in step4.purpose
        assert "攻击对象=排序第一候选一次" in step4.purpose
        assert "材料全部引自交接包" in step4.selfcheck
        assert "红队只基于材料攻击、零重勘" in step4.selfcheck

    def test_p1_step3_reuse_clause_pinned(self):
        # p1-sub3-cost L1（designs/p1-sub3-cost-optimization-design.md）：
        # plan:1#3 purpose/selfcheck 复用钉死条款（#25 收紧形态——默认零重验+
        # 枚举例外+按条配额+台账缓存通道钉死）关键词钉死——防未来编辑静默
        # 改丢（条款是本步步体主杠杆：基线 35 调用中 ~15 纯税/半税=重验子1
        # 已载出处+规范文档重读+掘进）。
        step3 = eng._NODES["plan:1"].sub_steps[2]
        assert "零重验零重跑" in step3.purpose
        assert "复用 子1 留痕" in step3.purpose
        assert "每符号最多一次" in step3.purpose
        assert "验存在即止" in step3.purpose
        assert "每功能域 ≤1 次查询" in step3.purpose
        assert "零规范文档重读" in step3.purpose
        assert "零 evidence 全量翻找" in step3.purpose
        assert "不重跑 freshness" in step3.purpose
        assert "零重验" in step3.selfcheck
        assert "零规范文档重读" in step3.selfcheck

    def test_p1_step3_payload_org_clause_pinned(self):
        # p1-sub3-cost 修1（B1 轮实证）：载荷组织钉死条款——条款逐项枚举被
        # 弱模型镜像成「按核验项拆 q」散列组织，撞 mech 逐 a 圈码齐备扫描
        # 7 连拒（35 Edit 返工褶皱）；组织形态+格式真源钉死防复发。
        step3 = eng._NODES["plan:1"].sub_steps[2]
        assert "每候选一对 q/a" in step3.purpose
        assert "按核验项拆 q" in step3.purpose
        assert "格式真源=--scaffold 骨架+报错文案" in step3.purpose

    def test_p1_step2_step_level_strip(self):
        # p1-sub2-cost L1（designs/p1-sub2-cost-optimization-design.md）：
        # plan:1#2 Step 级 strip（第八例，交互步第二例）——交付物=候选+
        # 维度声明+用户想法入列，gate 零规则引据要求（硬规则兼容=子3
        # 五项核验④职责，复用条款钉死缺引不违规防剥后重读规范文档）。
        node = eng._NODES["plan:1"]
        step2 = node.sub_steps[1]
        ov = eng.segment_spawn_overrides(node, step2)
        assert ov["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
        assert ov["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
        assert ov["tools"] == ("Bash", "Read", "Edit", "Grep", "Skill", "Agent")

    def test_p1_step2_reuse_clause_pinned(self):
        # p1-sub2-cost L2：purpose/selfcheck 复用钉死+职责边界条款（#25
        # 收紧形态最强版——默认零新查询+无取证例外，例外缺口的合法性由
        # gate 凭空设计判据结构性保证）关键词钉死——防未来编辑静默改丢。
        step2 = eng._NODES["plan:1"].sub_steps[1]
        assert "零新取证" in step2.purpose
        assert "无取证例外" in step2.purpose
        assert "子1 未列出的事实不得进候选" in step2.purpose
        assert "硬规则兼容核验归子3" in step2.purpose
        assert "为后续步预取材料=越界" in step2.purpose
        assert "零 evidence 全量翻找" in step2.purpose
        assert "零为后续步预取" in step2.selfcheck

    def test_p1_step1_reuse_clause_pinned(self):
        # p1-sub1-cost L3：purpose/selfcheck 复用钉死条款（#25/#29 收紧形态
        # ——默认零重验+枚举例外+按条配额+时间敏感项[新鲜度]排除出复用面）
        # 关键词钉死——防未来编辑把条款静默改丢（条款是本步步体主杠杆：
        # 基线 50 Bash 中 ~35 纯税/半税=前序已载出处重验+掘进+环境摸索）。
        step1 = eng._NODES["plan:1"].sub_steps[0]
        assert "零重跑重验" in step1.purpose
        assert "复用 <节点>子N 留痕" in step1.purpose
        assert "每条事实最多一次" in step1.purpose
        assert "验存在即止" in step1.purpose
        assert "dl codebase freshness" in step1.purpose
        assert "零 evidence 全量翻找" in step1.purpose
        assert "零重验" in step1.selfcheck

    def test_p1_step1_pack_full_prior_boundary_pinned(self):
        # p1-sub1-cost 修1：plan:1#1 置位 pack_full_prior_boundary（复用钉死
        # 的逐字引用材料=前序 boundary，截断 100 字符恰切在 file:line 处）；
        # 兄弟步不置位（钉死防静默扩面/丢失）。
        node = eng._NODES["plan:1"]
        assert node.sub_steps[0].pack_full_prior_boundary is True
        for i, step in enumerate(node.sub_steps[1:], start=2):
            assert step.pack_full_prior_boundary is False, i

    def test_step_level_strip_backward_compat(self):
        # step=None（MergedSession 段内续步管线不传 step）维持节点级语义——
        # u:3 节点级 False 时 env 仍空（B1 决议不破）。
        node = eng._NODES["understand:3"]
        assert eng.segment_spawn_overrides(node)["env"] == {}
        # 节点级已置位时 step 未置位不剥回（单调只增）
        u2 = eng._NODES["understand:2"]
        ov = eng.segment_spawn_overrides(u2, u2.sub_steps[0])
        assert ov["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"

    def test_step_level_strip_other_steps_unaffected(self):
        # u:3 其余步（子1/2/5）未置位——逐步粒度不误伤兄弟步。
        node = eng._NODES["understand:3"]
        for i, step in enumerate(node.sub_steps, start=1):
            if i in (3, 4):
                continue
            assert eng.segment_spawn_overrides(node, step)["env"] == {}, i
