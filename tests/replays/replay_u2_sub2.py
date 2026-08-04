#!/usr/bin/env python3
"""u:2#2 对齐质检 gate 回归重放（framing 反转的回归资产，
designs/u2-sub2-gate-framing-design.md）。

clean(demo 真实子2 trace：双向矩阵逐项+孤儿处置+方案剥离非同义反复+冲突声明) /
vio1 同义反复（剥离后 outcome=做X为了能做X，未剥到真实 outcome） /
vio2 矩阵放水（脑补目标 G2「降低管线耗时」硬连到 P1「统计正IC数量」=无关联） /
vio3 汇总声明无逐项矩阵（「全部对齐」式汇总无问题×目标逐项矩阵）。

artifact=子1+子2 最新 trace 拼合（生产 read_evidence_for_step(2,"GoalsAndValue")
同形--子1 goal_candidates 是子2 对齐的判对象，作前序锚点）。

用法: python3 tests/replays/replay_u2_sub2.py [N] [gate_file]
"""
import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "明确目标和价值 · 子步骤2"
STEP = sub_step("understand:2", 1)  # sub_steps[1] = 子2 对齐质检

# ---- 子1 trace（生产 artifact 含前序各步最新 trace；goal_candidates 来源）----
S1_BASE = {
    "kind": "skill-trace", "major_stage": "Understand", "minor_stage": "GoalsAndValue",
    "sub_step": 1, "skill": "推理(KAOS WHY/HOW 问) / AskUserQuestion(补问)",
    "purpose": "从ProblemContext唯一存活问题引出目标，覆盖who/outcome/初步价值，并据会话原话形成目标候选。结论选择①目标成立。ProblemContext问题：'在 default 管线生成的、数据截至2026-07-24的最新报告中，统计 IC均值严格大于0的因子数量。'目标候选G1：当前提问者得到该口径下的正IC因子数量，用它决定筛选门槛。初步价值：继续筛选。出处分别为用户原话'我自己'、原始请求'现在有多少个因子的IC为正？'、用户原话'决定筛选门槛'和'继续筛选'；无出处推断：无。",
    "q": [
        "who=该目标的受益者是谁？",
        "outcome=解决已确认问题后要达成什么状态？",
        "初步价值=达成该状态后有什么直接价值？",
        "目标候选如何追溯到ProblemContext存活问题？",
        "目标成立还是不成立？",
    ],
    "a": [
        "用户原话：'我自己'。",
        "用户原话：'决定筛选门槛'；其所需结果来自原始请求'现在有多少个因子的IC为正？'。",
        "用户原话：'继续筛选'。",
        "G1'得到该口径下的正IC因子数量，用它决定筛选门槛'直接承接唯一存活问题'统计IC均值严格大于0的因子数量'。",
        "结论①目标成立；唯一存活问题已有目标候选G1，全部事实均有用户原话或已确认ProblemContext出处。",
    ],
}

# ---- 子2 clean（真实对齐质检 trace：矩阵逐项+剥离非同义反复+冲突声明）----
S2_BASE = {
    "kind": "skill-trace", "major_stage": "Understand", "minor_stage": "GoalsAndValue",
    "sub_step": 2, "skill": "推理(双向追溯矩阵+方案剥离+冲突检测)",
    "purpose": "对齐质检（只审子1目标集对齐质量）：①双向追溯矩阵（forward查覆盖/backward查镀金）；②solutioneering剥离；③目标间冲突检测。",
    "q": [
        "双向追溯矩阵（问题×目标逐项）是什么？",
        "孤儿目标/孤儿问题如何处置？",
        "含方案名词/实现动词的目标剥到 outcome 了吗？",
        "目标间冲突检测结果是什么？",
    ],
    "a": [
        "双向追溯矩阵（逐项，非汇总）：backward：G1「得到该口径下的正IC因子数量，用它决定筛选门槛」回溯≥1个已验证问题=P1「统计IC均值严格大于0的因子数量」（G1承接P1，非镀金）；forward：P1「统计IC均值严格大于0的因子数量」-> G1「得到该口径下的正IC因子数量」（每个存活问题有承接目标，未漏）。",
        "孤儿处置：backward无孤儿目标（G1回溯P1成立）；forward无孤儿问题（P1由G1承接）。无须剔除/退回子1补问/搁置。",
        "方案剥离：G1主语「得到正IC因子数量」「决定筛选门槛」均为outcome-level状态（用户可见的数字/决策动作），无模板文件名/类名/函数名/管线名等实现侧名词；WHY追问「为什么要得到数量」答「用来决定筛选门槛」=真实outcome，非同义反复，无须再剥。",
        "冲突检测：仅一个目标G1，无目标间冲突，显式声明无冲突。",
    ],
}

CLEAN = copy.deepcopy(S2_BASE)

# ---- vio1 同义反复：剥离后 outcome=做X为了能做X ----
# S1 的 G1 改为含实现动词的方案表述；子2 剥离产出同义反复 outcome 且未修正
S1_VIO1 = copy.deepcopy(S1_BASE)
S1_VIO1["purpose"] = S1_VIO1["purpose"].replace(
    "目标候选G1：当前提问者得到该口径下的正IC因子数量，用它决定筛选门槛。",
    "目标候选G1：当前提问者开发一个正IC因子数量统计模块。",
)
S1_VIO1["a"][3] = "G1「开发一个正IC因子数量统计模块」直接承接唯一存活问题'统计IC均值严格大于0的因子数量'。"

VIO1 = copy.deepcopy(S2_BASE)
VIO1["a"][0] = ("双向追溯矩阵（逐项）：backward：G1「开发一个正IC因子数量统计模块」回溯P1"
                "「统计IC均值严格大于0的因子数量」（G1承接P1）；forward：P1「统计IC均值严格大于0的"
                "因子数量」-> G1「开发一个正IC因子数量统计模块」（每个存活问题有承接目标）。")
VIO1["a"][2] = ("方案剥离：G1原表述「开发一个正IC因子数量统计模块」含实现动词'开发'与实现侧名词'模块'，"
                "WHY追问'为什么要开发统计模块'-> outcome「能开发正IC因子数量统计模块」，"
                "做开发为了能开发，outcome同义反复（做X为了能做X），保留此 outcome 作为对齐结果。")

# ---- vio2 矩阵放水：脑补目标 G2 硬连到无关问题 P1 ----
S1_VIO2 = copy.deepcopy(S1_BASE)
S1_VIO2["q"].insert(4, "除 G1 外还有其他目标候选吗？")
S1_VIO2["a"].insert(4, "G2：掌握代码仓库的 README 文档结构现状。")
S1_VIO2["a"][5] = "结论①目标成立；存活问题已有目标候选G1与G2。"

VIO2 = copy.deepcopy(S2_BASE)
VIO2["a"][0] = ("双向追溯矩阵（逐项）：backward：G1「得到正IC因子数量，决定筛选门槛」回溯P1"
                "「统计IC均值严格大于0的因子数量」；G2「掌握代码仓库的 README 文档结构现状」回溯P1"
                "「统计IC均值严格大于0的因子数量」（G2承接P1）。forward：P1「统计IC均值严格大于0的"
                "因子数量」-> G1+G2（每个存活问题有承接目标）。")
VIO2["a"][1] = "孤儿处置：无孤儿目标（G1、G2均回溯P1）；无孤儿问题。"
VIO2["a"][2] = ("方案剥离：G1、G2主语均为outcome-level状态（数字/决策/认知掌握），"
                "无实现侧名词，无须剥。")
VIO2["a"][3] = "冲突检测：G1与G2无冲突，显式声明无冲突。"

# ---- vio3 汇总声明无逐项矩阵：「全部对齐」式汇总，无问题×目标逐项矩阵 ----
VIO3 = copy.deepcopy(S2_BASE)
VIO3["a"][0] = ("双向追溯已完成：所有目标均已对齐到存活问题，每个存活问题都有目标承接，"
                "backward与forward均无遗漏，矩阵全部对齐，无孤儿。")

# (子1 trace, 子2 trace) 对--artifact=两行 JSON 拼接（生产 read_evidence_for_step 同形）
CASES = {
    "clean": (S1_BASE, CLEAN),
    "vio1_tautology": (S1_VIO1, VIO1),
    "vio2_matrix_cheat": (S1_VIO2, VIO2),
    "vio3_summary_no_matrix": (S1_BASE, VIO3),
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {
        k: json.dumps(s1, ensure_ascii=False) + "\n" + json.dumps(s2, ensure_ascii=False)
        for k, (s1, s2) in CASES.items()
    }
    run_cases("u:2#2 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
