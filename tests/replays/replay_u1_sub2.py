#!/usr/bin/env python3
"""u:1#2b 因果链挖掘 gate 回归重放（v2.72-v2.75 反转的回归资产，
plan-first 拆步后归子2b，sub_step=3；none 档漏取证牙齿已随拆步迁子2a
replay_u1_sub2a.py）。

clean(demo 真实合规现代化) / vio1 同义反复 / vio2 稻草人。
artifact=子1+子2b 最新 trace 拼合（生产 read_evidence_for_step(3) 同形——
fixture 保真度第四实例：harness 注声明产物组成后，fixture 必须匹配，§3.5 #30 ⑨）。
vio2 读数口径：生产墙=mech（hypothesis_exclude_no_absence）100% 先拒，
judge 侧 3-6/6 均为已知裁量面。

用法: python3 tests/replays/replay_u1_sub2.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "理解问题和背景 · 子步骤3（因果链挖掘）"
STEP = sub_step("understand:1", 2)

# 子1 trace（生产形态 fixture 的前序锚点）
S1 = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "ProblemContext",
    "sub_step": 1,
    "skill": "define-problem",
    "purpose": "逼问问题定义。",
    "q": ["who：你的角色？", "pain：候选太多 downstream 影响？", "why-now：何时发现？"],
    "a": [
        "因子池维护者（AskUserQuestion 选中）。",
        "候选太多导致无法决定筛选门槛，无法继续筛选（用户原话「候选太多」「决定筛选门槛」）。",
        "刚才整理因子池时发现（AskUserQuestion 选中）。",
    ],
    "结论": "①问题成立：维护者（AskUserQuestion 选中）整理因子池时发现候选太多，没有缩减规则导致无法决定筛选门槛（用户原话），若不解决则无法继续筛选。",
}

BASE = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "ProblemContext",
    "sub_step": 3,
    "skill": "causal-inference-root-cause",
    "purpose": "拆解深挖。单一/复合判定：单一问题，无复合；理由是用户的「候选太多」「没有缩减规则」「决定筛选门槛」共同描述同一个筛选决策瓶颈，没有第二个独立痛点。",
    "q": [
        "单一/复合判定及原子问题是什么？",
        "因果链第1环：为什么候选太多会妨碍继续筛选？",
        "因果链第2环：当前近因如何表现？",
        "因果链第3环：知道数量后如何产生后续动作？",
        "竞争假设是什么，为什么排除或保留？",
        "近因、根因和置信度分别是什么？",
    ],
    "a": [
        "单一，无复合。用户原话「候选太多」「没有缩减规则」「决定筛选门槛」共同指向一个筛选决策瓶颈；P1=缺少缩减候选的规则，需要正 IC 因子数量来决定筛选门槛。",
        "用户对该问题原话回答「没有缩减规则」，支持「没有缩减规则 → 候选太多妨碍筛选」。",
        "用户原话「候选太多」，并明确提问「现在有多少个因子的IC为正？」，支持「候选太多 → 查询正 IC 因子数量」这一当前行动链。",
        "用户原话「决定筛选门槛」和「继续筛选」，支持「数量 → 决定门槛 → 继续筛选」。",
        "H1=只想了解规模且数量不影响筛选。用户未选择「只想了解规模」和「数量并不帮助」，而选择「没有缩减规则」与「决定筛选门槛」（AskUserQuestion 选中留痕），故当前排除 H1。",
        "近因=「候选太多」；根因=「没有缩减规则」；置信度=中高，依据均为用户自述，候选规模与 IC 分布待子3用仓内报告数据验证。",
    ],
    "atomic_questions": [
        {
            "q": "P1 用户缺少缩减候选的规则，需要正 IC 因子数量决定筛选门槛",
            "tier": "none",
            "tier_reason": "答案仓内可达：正 IC 因子数量可由仓内最新报告产物统计得出（backtest/result/default/ 目录），仅内查即可，论证不依赖仓外知识",
        }
    ],
}

CLEAN = copy.deepcopy(BASE)

VIO1 = copy.deepcopy(BASE)  # 同义反复：根因=症状换说法
VIO1["purpose"] = "拆解深挖。单一问题，无复合。P1=报告中年化率显示 +9529.8% 异常。"
VIO1["a"][1] = (
    "年化率显示异常是因为年化计算结果过大（summary_report.json 中 ann_return=95.298 字段值，读出即事实）。"
)
VIO1["a"][2] = (
    "年化计算结果过大是因为年化数值异常偏高（同一字段值 95.298 远大于 1，读出即事实）。"
)
VIO1["a"][3] = "年化数值异常偏高导致报告展示异常数字（报告页面显示 +9529.8%）。"
VIO1["a"][5] = (
    "近因=「年化计算结果过大」；根因=「年化数值异常偏高」；置信度=高，每环均有数据值背书。"
)
VIO1["atomic_questions"] = [
    {
        "q": "P1 报告年化率显示 +9529.8% 异常",
        "tier": "none",
        "tier_reason": "答案仓内可达：异常字段在仓内报告产物 backtest/result/default/summary_report.json，仅内查即可",
    }
]

VIO2 = copy.deepcopy(BASE)  # 稻草人竞争假设（生产墙=mech 缺席断言扫描先拒）
VIO2["a"][4] = (
    "H1=用户其实想删除整个因子池、以后不再需要任何因子。排除理由：用户没有表达过这个意思，故排除 H1。"
)

CASES = {
    "clean": CLEAN,
    "vio1_tautology": VIO1,
    "vio2_strawman": VIO2,
}
EXPECT = {
    "clean": True,
    "vio1_tautology": False,
    "vio2_strawman": False,
}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    s1 = json.dumps(S1, ensure_ascii=False)
    arts = {k: s1 + "\n" + json.dumps(v, ensure_ascii=False) for k, v in CASES.items()}
    run_cases("u:1#2b replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
