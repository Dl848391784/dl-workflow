#!/usr/bin/env python3
"""u:1#2a 规划拆解 gate 回归重放（plan-first 拆步 2026-08-14 新增回归资产）。

子2a gate 承接原原子2 gate 的方框一（MECE 互斥穷尽）+ 方框二（none 档漏取证）；
方框一/二/三（因果链证据）归子2b gate（replay_u1_sub2.py，sub_step=3）。
本脚本钉子2a 判据：MECE 互斥穷尽（方框一）+ none 档漏取证（方框二）。

artifact=子1+子2a 最新 trace 拼合（生产 read_evidence_for_step(2) 同形——
fixture 保真度第四实例：harness 注声明产物组成后，fixture 必须匹配，§3.5 #30 ⑨）。
MECE 判据在 judge 侧（方框一）；atomic_mece_alignment 机械层只校验「MECE 声明
标签 ↔ aq 首字母标签」集合对齐（声明了几原子就交几条），漏项/重叠是 judge 裁量面
——本脚本的漏项/重叠 vio 都要先满足机械层（声明与提交条数一致），逼 judge 判真值。
none 档漏取证在 judge 侧（方框二）；fetch_tier_items 机械层只校验 tier_reason
含仓内路径指针，不判真假——vio3_tier_none 的 a[1] 用「IC>0.05 行业有效线」
（行业常识）判断有效性却标 none，逼 judge 按方框二判。

用法: python3 tests/replays/replay_u1_sub2a.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "理解问题和背景 · 子步骤2（规划拆解）"
STEP = sub_step("understand:1", 1)

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
    "sub_step": 2,
    "skill": "causal-inference-root-cause",
    "purpose": "拆解深挖·规划。单一/复合判定：单一问题，无复合；理由是用户的「候选太多」「没有缩减规则」「决定筛选门槛」共同描述同一个筛选决策瓶颈，没有第二个独立痛点。",
    "q": [
        "单一/复合判定及原子问题是什么？",
        "每个原子问题的取证深度档？",
    ],
    "a": [
        "单一，无复合。用户原话「候选太多」「没有缩减规则」「决定筛选门槛」共同指向一个筛选决策瓶颈；P1=缺少缩减候选的规则，需要正 IC 因子数量来决定筛选门槛。",
        "P1 标 none 档：答案仓内可达，无需外部取证。",
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

VIO_OMIT = copy.deepcopy(BASE)  # MECE 穷尽失败：三个独立痛点只拆了两个原子
VIO_OMIT["purpose"] = (
    "拆解深挖·规划。复合：三个独立痛点——①候选太多无法继续筛选；"
    "②不知道现在有多少正 IC 因子；③无法决定筛选门槛。"
    "拆成原子 1 = ①、原子 2 = ③。"
)
VIO_OMIT["a"][0] = (
    "复合，三个独立痛点：①候选太多无法继续筛选；②不知道现在有多少正 IC 因子；"
    "③无法决定筛选门槛。拆成原子 1 = ①、原子 2 = ③。"
)
VIO_OMIT["a"][1] = "原子1 标 none、原子2 标 none：均仓内可达，无需外部取证。"
VIO_OMIT["atomic_questions"] = [
    {
        "q": "原子1 候选太多无法继续筛选",
        "tier": "none",
        "tier_reason": "仓内可达：候选数量可由仓内报告统计得出（backtest/result/default/），仅内查即可",
    },
    {
        "q": "原子2 无法决定筛选门槛",
        "tier": "none",
        "tier_reason": "仓内可达：筛选门槛决策依赖仓内正 IC 因子数量（backtest/result/default/），仅内查即可",
    },
]

VIO_OVERLAP = copy.deepcopy(BASE)  # MECE 互斥失败：两个原子都指向同一个痛点
VIO_OVERLAP["purpose"] = (
    "拆解深挖·规划。复合：两个独立痛点——①候选太多导致无法决定筛选门槛；"
    "②缺少缩减候选的规则。拆成原子 1 = 缺少规则导致候选堆积、原子 2 = 候选太多导致无法决定筛选门槛。"
)
VIO_OVERLAP["a"][0] = (
    "复合，两个独立痛点：①候选太多导致无法决定筛选门槛；②缺少缩减候选的规则。"
    "拆成原子 1 = 缺少规则导致候选堆积、原子 2 = 候选太多导致无法决定筛选门槛。"
)
VIO_OVERLAP["a"][1] = "原子1 标 none、原子2 标 none：均仓内可达，无需外部取证。"
VIO_OVERLAP["atomic_questions"] = [
    {
        "q": "原子1 缺少缩减候选的规则导致候选堆积",
        "tier": "none",
        "tier_reason": "仓内可达：规则存在性可由仓内代码/报告核实（paths.py + summary_report.json），仅内查即可",
    },
    {
        "q": "原子2 候选太多且缺少缩减规则导致无法决定筛选门槛",
        "tier": "none",
        "tier_reason": "仓内可达：候选数量与门槛决策依赖仓内报告（backtest/result/default/），仅内查即可",
    },
]

VIO3_TIER_NONE = copy.deepcopy(BASE)  # none 档漏取证：判「IC 有效水平」用行业常识却标 none
VIO3_TIER_NONE["purpose"] = (
    "拆解深挖·规划。单一问题，无复合。P1=IC 均值 0.03 的因子是否达到有效水平、值得纳入筛选。"
)
VIO3_TIER_NONE["a"][0] = (
    "单一，无复合。P1=IC 均值 0.03 的因子是否达到有效水平、值得纳入筛选。"
)
VIO3_TIER_NONE["a"][1] = (
    "P1 标 none 档：量化行业一般认为 IC 均值 >0.05 才算有效因子（行业常识），"
    "0.03 低于该水平，故不值得纳入筛选；IC 数值仓内报告可得，无需外部取证。"
)
VIO3_TIER_NONE["atomic_questions"] = [
    {
        "q": "P1 IC 均值 0.03 的因子是否达到有效水平",
        "tier": "none",
        "tier_reason": "答案仓内可达：IC 数值在仓内报告产物 backtest/result/default/summary_report.json，仅内查即可",
    }
]

CASES = {
    "clean": CLEAN,
    "vio_missing_atom": VIO_OMIT,
    "vio_overlap": VIO_OVERLAP,
    "vio3_tier_none": VIO3_TIER_NONE,
}
EXPECT = {
    "clean": True,
    "vio_missing_atom": False,
    "vio_overlap": False,
    "vio3_tier_none": False,
}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    s1 = json.dumps(S1, ensure_ascii=False)
    arts = {k: s1 + "\n" + json.dumps(v, ensure_ascii=False) for k, v in CASES.items()}
    run_cases("u:1#2a replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
