"""workflow_phase.py _format_injection 的证据标记注入测试。

对应 designs/evidence-chain-design.md §4.1/§9 step4（方案1：扩展注入）。
live smoke 排查发现：无渠道告诉模型发 ### EVIDENCE:{json} 标记 -> no_markers。
本测验证 _format_injection 返回的注入文本含证据格式提示块。

范围：仅验证据注入提示存在 + 格式正确；阶段规则/子阶段/TaskList 不在此测
（_format_injection 现有行为保持，本测只断言新增块）。
"""

from __future__ import annotations

import sys
from pathlib import Path

DLWF_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DLWF_ROOT / "hooks"))
import workflow_phase as wp  # noqa: E402


def _state(phase: str, index: int = 1, **kw) -> dict:
    """构造最小 state（_format_injection 所需字段）。"""
    s = {
        "name": "t",
        "phase": phase,
        "index": index,
        "gate": "pending",
        "sub_index": 0,
        "sub_total": 0,
    }
    s.update(kw)
    return s


def test_injection_contains_evidence_format_block() -> None:
    """注入文本含 ### EVIDENCE: 标记格式提示。"""
    txt = wp._format_injection(_state("execute", index=3))
    assert "### EVIDENCE:" in txt
    assert "claim" in txt
    assert "depends_on" in txt
    assert "claim_type" in txt


def test_injection_explains_when_to_output() -> None:
    """提示何时输出（结论/中间结论/前提）。"""
    txt = wp._format_injection(_state("execute", index=3))
    # 含 claim_type 的语义说明（conclusion/intermediate/premise 之一）
    assert "conclusion" in txt
    assert "intermediate" in txt or "premise" in txt


def test_injection_explains_local_handle() -> None:
    """提示 depends_on 用本地句柄 step<N>（不预知 canonical id）。"""
    txt = wp._format_injection(_state("execute", index=3))
    assert "step" in txt  # 句柄格式说明（step1/step<N> 之类）


def test_injection_present_in_understand_with_subphases() -> None:
    """understand 阶段（有子阶段）也注入证据提示。

    live smoke 缺口即 understand 子阶段 1 无证据提示 -> 修复后须含。
    """
    txt = wp._format_injection(_state("understand", index=1, sub_index=1, sub_total=4))
    assert "### EVIDENCE:" in txt


def test_injection_present_in_all_phases() -> None:
    """5 阶段都注入证据提示（证据链跨阶段，任一阶段都可能产出可证据化结论）。"""
    for phase, idx in [
        ("understand", 1),
        ("plan", 2),
        ("execute", 3),
        ("review", 4),
        ("evolution", 5),
    ]:
        txt = wp._format_injection(_state(phase, index=idx))
        assert "### EVIDENCE:" in txt, f"phase={phase} 缺证据提示"


def test_injection_evidence_block_is_separate_from_phase_done() -> None:
    """证据提示与 PHASE_DONE/SUB_DONE 标记提示并存（不互相覆盖）。"""
    txt = wp._format_injection(_state("understand", index=1, sub_index=1, sub_total=4))
    assert "### SUB_DONE:" in txt or "### PHASE_DONE:" in txt
    assert "### EVIDENCE:" in txt
