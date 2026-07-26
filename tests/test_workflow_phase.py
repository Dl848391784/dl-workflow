"""
hooks/workflow_phase.py 的单元测试（2026-07-26，harness-prompt-optimization P0/P2）。

对应 designs/harness-prompt-optimization-design.md §2/§4。
仿 test_dl_flow_engine.py 的 importlib 加载（hook 自带 engine 加载，parents[1]=dl-workflow 根）。

覆盖 _format_injection 的注入结构契约：
- P0：当前步 purpose 全文置顶（在骨架链之前）；非当前步 purpose 全文不出现
- P0：骨架链含 6 个 short 短名 + 【当前】标记在当前步
- P0：TaskList 块只留状态数据，指令散文已删
- P2：evidence 块含 ✓ 正例 / ✗ 反例 + 当前值模板；散文警告行已删
- held_for_gate 分支不回归（门栏提示在、子步骤块不在）
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

DLWF_ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "workflow_phase", DLWF_ROOT / "hooks" / "workflow_phase.py"
)
wp = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["workflow_phase"] = wp
_spec.loader.exec_module(wp)  # type: ignore[union-attr]

PROJECT_ROOT = Path("/home/admin/projects/factor_ic_analyzer")


def _state(sub_step_index: int, **overrides) -> dict:
    st = {
        "name": "demo",
        "phase": "understand",
        "index": 1,
        "gate": "pending",
        "sub_index": 1,
        "sub_total": 4,
        "sub_step_index": sub_step_index,
        "node": "understand:1",
    }
    st.update(overrides)
    return st


class TestCurrentStepFirst:
    """P0：当前步全文置顶 + 其余步骨架（design §2.1）。"""

    def test_current_step_block_before_chain(self):
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        i_cur = ctx.index("▶ 当前子步骤 3/6")
        i_chain = ctx.index("子步骤链")
        assert i_cur < i_chain

    def test_current_step_full_purpose_present(self):
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        node = wp.engine.get_node("understand", 1)
        assert node.sub_steps[2].purpose in ctx  # 子3 purpose 全文

    def test_non_current_step_purpose_absent(self):
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        node = wp.engine.get_node("understand", 1)
        # 非当前步（子1/子4）purpose 全文不出现——瘦身的核心断言
        assert node.sub_steps[0].purpose not in ctx
        assert node.sub_steps[3].purpose not in ctx

    def test_chain_has_all_short_labels_and_current_mark(self):
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        chain_line = next(line for line in ctx.splitlines() if "子步骤链" in line)
        for short in (
            "逼问定义",
            "拆解深挖",
            "双向取证",
            "质检裁决",
            "归一化陈述",
            "读回确认",
        ):
            assert short in chain_line
        assert "3.双向取证【当前】" in chain_line
        assert "1.逼问定义 ✓" in chain_line  # 已完成步标 ✓

    def test_tasklist_instruction_prose_removed(self):
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        # 指令散文删（在 output-style/phase-rules），状态数据留
        assert "TaskCreate 建齐" not in ctx
        assert "1. 理解和求证问题 -> in_progress" in ctx


class TestEvidenceBlockExamples:
    """P2：正反例替代散文警告（design §4.1）。"""

    def test_good_bad_examples_present(self):
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        assert "✓ 正例" in ctx
        assert "✗ 反例（必 block）" in ctx

    def test_payload_schema_and_append_trace_command(self):
        # v2.14：载荷只含 purpose/q/a；结构字段脚本从 state 填（不再注入给模型照抄）
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        assert '"purpose":"<该步目的>"' in ctx
        assert ".trace-payload-demo.json" in ctx
        assert "append-trace" in ctx
        assert "脚本从 state 自动填" in ctx

    def test_handwritten_jsonl_template_removed(self):
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        assert '"kind":"skill-trace"' not in ctx  # 手写整行 JSON 模板已删
        assert "字段：major_stage=phase 英文首字母大写" not in ctx  # 字段散文解释行
        assert "⚠️" not in ctx  # 占位符警告行


class TestHeldForGateUnchanged:
    """门栏扣留分支不回归（§subphase-hold-gate）。"""

    def test_held_state_shows_gate_hold_not_steps(self):
        node = wp.engine.get_node("understand", 1)
        ctx = wp._format_injection(_state(6, held_for_gate=True), PROJECT_ROOT)
        assert node.hold_for_gate  # fixture 前提
        assert "子阶段门栏" in ctx
        assert "▶ 当前子步骤" not in ctx
        assert "子步骤链" not in ctx


class TestLastStepInstruction:
    def test_step_done_marker_matches_current_step(self):
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        assert "### STEP_DONE: 3`" in ctx

    def test_last_step_mentions_hold_gate(self):
        ctx = wp._format_injection(_state(6), PROJECT_ROOT)
        assert "### STEP_DONE: 6`" in ctx
        assert "门栏" in ctx  # hold_for_gate 末步提示等 /dl gate


class TestSelfcheckStepSpecific:
    """步级自查提示进注入（与 pass/block 续轮同文，engine.selfcheck_hint 单源）。"""

    def test_step1_injection_carries_step1_checklist(self):
        ctx = wp._format_injection(_state(1), PROJECT_ROOT)
        assert "本步自查：" in ctx
        assert "who/pain/why-now ≥3 类都覆盖了吗" in ctx

    def test_step3_injection_carries_step3_not_step1(self):
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        assert "五层源各 ≥1 次尝试" in ctx
        assert "who/pain/why-now ≥3 类都覆盖了吗" not in ctx  # 不带别步 checklist


class TestCorruptFormatRedline:
    """§corrupt-rework-detect C 侧：注入 ✗ 格式红线（单行合法 JSON）。"""

    def test_no_bypass_warning_present(self):
        # v2.14：手写 JSON 的事故警示收编进「禁止绕过 append-trace」
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        assert "禁止绕过" in ctx
        assert "trace 隐形" in ctx
