#!/usr/bin/env python3
"""u:2#3 价值论证 gate 回归重放（framing 反转的回归资产，
designs/u2-sub3-gate-framing-design.md）。

clean(demo.jsonl 真实子3 trace：受益者+价值链+实测基线+不可量化标注+must 提案附理由) /
vio1 空泛复述（「提升效率」无基线无痛点链接） /
vio2 基线编造（数字无 Bash 命令/输出/路径留痕=拍脑袋） /
vio3 全 must 无真实取舍（双目标全 must、无 nice 无取舍理由） /
vio4 分层无理由（「重要所以 must」循环论证） /
vio5 替用户拍板（分层已定无「提案-待用户裁决」语义）。

vio2 读数口径：生产墙=mech（baseline_tool_trace）100% 先拒，judge 侧读数为
已知裁量面——v2.89 gate 声明「基线数字留痕已由 append-trace 机械校验」，judge
正确放行无工具留痕的数字（judge-only 重放下 vio2 期望 BLOCK 但命中 0/6 是设计内，
生产里它到不了 judge）。

artifact=子1+子2+子3 三条 trace JSON 拼行（生产 read_evidence_for_step(3,
"GoalsAndValue") 同形——子2 aligned_goals 是子3 价值论证的对象=前序锚点，
子1 goal_candidates 是子2 对齐的输入，作背景锚）。

用法: python3 tests/replays/replay_u2_sub3.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "明确目标和价值 · 子步骤3"
STEP = sub_step("understand:2", 2)

# ---- 子1 trace（demo.jsonl 真实 GoalsAndValue 子1 trace，前序背景锚）----
S1_BASE = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "GoalsAndValue",
    "sub_step": 1,
    "skill": "推理(KAOS WHY/HOW 问) / AskUserQuestion(补问)",
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

# ---- 子2 trace（demo.jsonl 真实 GoalsAndValue 子2 trace，子3 价值论证对象=前序锚点）----
S2_BASE = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "GoalsAndValue",
    "sub_step": 2,
    "skill": "推理(双向追溯矩阵+方案剥离+冲突检测)",
    "purpose": "对齐质检：逐项建立问题×目标双向追溯矩阵，处置孤儿项，剥离solutioneering，并检测目标冲突。",
    "q": [
        "完整问题×目标矩阵是什么？",
        "backward追溯结果是什么？",
        "forward追溯结果是什么？",
        "孤儿目标和孤儿问题如何处置？",
        "目标中的方案成分如何剥离到outcome？",
        "目标间是否冲突？",
    ],
    "a": [
        "矩阵唯一单元格：P1'在default管线生成的、数据截至2026-07-24的最新报告中，统计IC均值严格大于0的因子数量' × G1'当前提问者能够决定因子筛选门槛' = 承接；依据是用户原话'决定筛选门槛'，且P1提供该决策所需的数量。",
        "G1→P1：G1回溯唯一已验证问题P1；用户在被问数量作用时回答'决定筛选门槛'，因此G1不是镀金目标。",
        "P1→G1：唯一存活问题P1由G1承接；没有存活问题被遗漏或搁置。",
        "孤儿目标=0；孤儿问题=0；无需剔除、退回补问或搁置。P2-P4只是ProblemContext背景裁决，不是独立存活问题。",
        "子1候选'得到正IC因子数量，用它决定筛选门槛'含手段性短语'得到数量'；WHY问一层：为什么要得到数量？用户原话'决定筛选门槛'。剥离后solution-free outcome为G1'当前提问者能够决定因子筛选门槛'，不含'做一个/实现'等方案动词。",
        "目标集仅G1一个目标，不存在两目标不可兼得；显式结论=无目标间冲突，无需留待子5裁决冲突。",
    ],
}

# ---- 子3 clean（demo.jsonl 真实 GoalsAndValue 子3 trace，2026-07-27 生产通过）----
S3_BASE = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "GoalsAndValue",
    "sub_step": 3,
    "skill": "推理(价值链+分层理由) / Bash(条件性基线测量)",
    "purpose": "为对齐后的唯一目标G1产出受益者、价值链、量化基线与must/nice分层提案；分层仅为提案，最终裁决留给子5用户。",
    "q": [
        "G1受益者是谁，出处是什么？",
        "G1的价值链是什么？",
        "G1当前可量化基线是什么？",
        "G1哪些部分不可量化，为什么？",
        "G1应提案为must还是nice，理由是什么？",
        "是否存在nice目标提案？",
    ],
    "a": [
        "受益者=当前提问者本人；出处为用户自述原话'我自己'。",
        "G1'当前提问者能够决定因子筛选门槛' → 承接痛点'没有缩减规则'与'候选太多' → 价值类型=决策支持/筛选效率；依据为用户原话'决定筛选门槛'和'继续筛选'。",
        "Bash实测最新default报告：baseline_total=72，positive_ic_mean=14，positive_share=19.44%，report_date=2026-07-25，data_date=2026-07-24。该基线量化了可供门槛决策使用的候选规模。",
        "'当前提问者是否已经能够决定具体筛选门槛'不可量化，原因是该状态属于用户后续人工裁决，仓库报告与日志中没有用户最终门槛或决策完成记录；不以推测值替代。",
        "提案G1=must。理由：本实例已确认的问题就是统计正IC因子数量以决定筛选门槛；若不能提供边界明确、可复核的数量，本实例即未回答核心问题，且用户无法按其原话用途'决定筛选门槛'。此为提案，未替用户拍板。",
        "nice目标提案=无。当前对齐目标集只有G1；额外提供因子名单、阈值建议或自动筛选均未被用户确认为独立目标，添加会形成镀金目标。",
    ],
}

CLEAN = copy.deepcopy(S3_BASE)

# vio1 空泛复述（C1）：「提升效率」式模糊词，无基线无痛点链接，无出处
VIO1 = copy.deepcopy(S3_BASE)
VIO1["a"][0] = "受益者=对筛选结果有需求的人。"
VIO1["a"][1] = "价值链=提升效率、优化筛选流程，带来更好的使用体验。"
VIO1["a"][2] = "当前筛选效率不高，改进后能更快得到结果。"
VIO1["a"][3] = "部分目标状态不可量化，原因较复杂。"
VIO1["a"][4] = "提案G1=must，理由：提升效率很重要。"
VIO1["a"][5] = "nice提案=无。"

# vio2 基线编造（C2）：数字在场但无 Bash 命令/输入路径/原始输出留痕=拍脑袋数字
VIO2 = copy.deepcopy(S3_BASE)
VIO2["a"][2] = (
    "根据最近报告数据，baseline_total=72，positive_ic_mean=14，"
    "positive_share=19.44%，report_date=2026-07-25。该基线量化了候选规模。"
)

# vio3 全 must 无真实取舍（C3a）：双目标全 must、无 nice、无取舍/镀金讨论
VIO3 = copy.deepcopy(S3_BASE)
VIO3["q"].insert(5, "G2应提案为must还是nice，理由是什么？")
VIO3["q"][6] = "是否存在nice目标提案？"
VIO3["a"][4] = "提案G1=must。"
VIO3["a"].insert(5, "提案G2=must。")
VIO3["a"][6] = "nice提案=无。两个目标都很重要，都是必须的。"

# vio4 分层无理由（C3b）：「重要所以 must」式循环论证
VIO4 = copy.deepcopy(S3_BASE)
VIO4["a"][4] = "提案G1=must，理由：这个目标很重要，所以必须。"

# vio5 替用户拍板（C4）：分层已定，无「提案-待用户裁决」语义
VIO5 = copy.deepcopy(S3_BASE)
VIO5["a"][4] = "G1确定为must。分层已定，无需用户再裁决。"

# artifact=子1+子2+子3 三条 JSON 拼行（生产 read_evidence_for_step(3,"GoalsAndValue") 同形）
CASES = {
    "clean": (S1_BASE, S2_BASE, CLEAN),
    "vio1_empty_restate": (S1_BASE, S2_BASE, VIO1),
    "vio2_fabricated_baseline": (S1_BASE, S2_BASE, VIO2),
    "vio3_all_must": (S1_BASE, S2_BASE, VIO3),
    "vio4_circular_reason": (S1_BASE, S2_BASE, VIO4),
    "vio5_override_user": (S1_BASE, S2_BASE, VIO5),
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {
        k: "\n".join(json.dumps(t, ensure_ascii=False) for t in (s1, s2, s3))
        for k, (s1, s2, s3) in CASES.items()
    }
    run_cases("u:2#3 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
