#!/usr/bin/env python3
"""u:1#1 逼问定义 gate 回归重放（v2.71 反转/v2.76 双态的回归资产）。

clean(合成纯净) / real_borderline(tail_volume 真实载荷,软依赖) /
vio_fixreq(纯修复诉求) / vio_fabricate(好奇心编造)。
real_borderline 读数口径（v2.76 定论）：1/6 PASS = 设计内 block
（pain 选项=修复诉求本体，「修复前不启用」派生包装不改本质）——
不是误伤，别把设计内 block 当回归（§3.5 #30 ⑦）。

用法: python3 tests/replays/replay_u1_sub1.py [N] [gate_file]
"""
import json
import sys
from pathlib import Path

from _common import run_cases, setup_env, sub_step

LABEL = "理解问题和背景 · 子步骤1"
STEP = sub_step("understand:1", 0)

CLEAN = {
    "kind": "skill-trace", "major_stage": "Understand", "minor_stage": "ProblemContext",
    "sub_step": 1, "skill": "define-problem", "purpose": "逼问问题定义。",
    "q": ["who：你的角色？", "pain-下游动作：若X错值，你下游会做什么不同动作？", "why-now：何时发现？"],
    "a": ["因子池维护者（AskUserQuestion 选中）。",
          "把该因子标注可疑并停用，不纳入本次筛选依据（AskUserQuestion 选中）。",
          "刚才做月度因子复盘时看到（AskUserQuestion 选中）。"],
    "结论": "①问题成立：维护者（AskUserQuestion 选中）月度复盘时看到因子X年化率显示+9529.8%（AskUserQuestion 选中），若错值留存会把该因子误纳入因子池筛选依据导致选错因子（AskUserQuestion 选中=用户确认的下游不同动作）。",
}

VIO_FIXREQ = {
    "kind": "skill-trace", "major_stage": "Understand", "minor_stage": "ProblemContext",
    "sub_step": 1, "skill": "define-problem", "purpose": "逼问问题定义。",
    "q": ["who：你的角色？", "pain：痛点是什么？", "why-now：何时发现？"],
    "a": ["因子池维护者（AskUserQuestion 选中）。",
          "用户要求定位 +9529.8% 的根因并修复计算代码（AskUserQuestion 选中「回查计算逻辑/修根因」）。",
          "刚才看报告时发现（AskUserQuestion 选中）。"],
    "结论": "①问题成立：痛点=需要修复这个年化率计算错误，用户要求定位根因并修代码（AskUserQuestion 选中）。",
}

VIO_FABRICATE = {
    "kind": "skill-trace", "major_stage": "Understand", "minor_stage": "ProblemContext",
    "sub_step": 1, "skill": "define-problem", "purpose": "逼问问题定义。",
    "q": ["who：你的角色？", "pain：痛点是什么？", "why-now：何时发现？"],
    "a": ["因子池维护者（AskUserQuestion 选中）。",
          "用户对 +9529.8% 感到好奇，无法判断该因子好坏（AskUserQuestion 选中）。",
          "刚才看报告时发现（AskUserQuestion 选中）。"],
    "结论": "①问题成立：痛点=用户好奇心缺口，看到异常数字想知道为什么，且无法判断因子有效性（AskUserQuestion 选中）。",
}


def _real_borderline():
    """tail_volume 子1 真实 trace（软依赖——state-reset 会删记录，§3.5 #30 ②）。"""
    f = Path("/home/admin/projects/factor_ic_analyzer/.claude/evidence/"
             "tail_volume_acceleration_annualized.jsonl")
    if not f.is_file():
        return None
    try:
        rec = json.loads(f.read_text().splitlines()[0])
    except (json.JSONDecodeError, IndexError):
        return None
    return rec if rec.get("sub_step") == 1 else None


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    cases = {"clean": CLEAN}
    expect = {"clean": True}
    real = _real_borderline()
    if real is not None:
        print("real 结论[:80]:", str(real.get("结论", ""))[:80], "\n")
        cases["real_borderline"] = real
        expect["real_borderline"] = True  # 读数口径见模块 docstring（1/6=设计内）
    else:
        print("real_borderline 跳过：tail_volume evidence 不存在或首行非子1 trace\n")
    cases.update({"vio_fixreq": VIO_FIXREQ, "vio_fabricate": VIO_FABRICATE})
    expect.update({"vio_fixreq": False, "vio_fabricate": False})
    arts = {k: json.dumps(v, ensure_ascii=False) for k, v in cases.items()}
    run_cases("u:1#1 replay", STEP, LABEL, arts, expect, n=n, gate=gate)


if __name__ == "__main__":
    main()
