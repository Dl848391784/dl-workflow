#!/usr/bin/env python3
"""u:2#1 目标引出 gate 回归重放（framing 反转的回归资产，
designs/u2-sub1-gate-framing-design.md）。

clean(demo.jsonl 真实子1 trace：结论①、每条答案有用户原话出处) /
clean2 合法结论②（补问原话佐证，①/②【关键】条款②侧保护载荷） /
vio1 孤儿目标候选（G2 对应不上 ProblemContext 存活问题=脑补） /
vio2 空泛复述（答案复述提问本身、无原话无会话事实） /
vio3 ②偷懒（结论②目标不成立但无任何原话佐证） /
vio4 ②未问先引（「用户未提及」冒充佐证，从未补问） /
vio6 张冠李戴（who 项引「原始请求」标注，与类目不对口）。

vio1/vio2/vio6 读数口径：生产墙=mech（goal_candidate_traceability_alignment /
answer_source_marker 含 who×原始请求不对口词形）100% 先拒，judge 侧读数为
已知裁量面（同 u12 vio2 口径）。
硬连对应（声称承接但明显不成立）不入本集——归 u:2 子2 对齐质检 gate 判
（其判据含「矩阵放水/脑补目标挂到无关问题判 block」且完整矩阵在判材），
v3 实证弱 judge 对承接真实性仅 1/6=该判据的最有利位置在子2 不在子1；
u:2#2 replay 须含硬连载荷（见 designs/u2-sub1-gate-framing-design.md §3.4）。

artifact=子1 单条 trace（生产 read_evidence_for_step(1,"GoalsAndValue")
同形——子1 是本节点首步，无前序步 trace 拼合；ProblemContext 引用以
payload 内引述呈现，与生产一致）。

用法: python3 tests/replays/replay_u2_sub1.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "明确目标和价值 · 子步骤1"
STEP = sub_step("understand:2", 0)

# ---- 子1 clean（demo.jsonl 真实 GoalsAndValue 子1 trace，2026-07-27 生产通过）----
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

CLEAN = copy.deepcopy(S1_BASE)

# clean2：合法结论②——本步补问原话佐证「字面请求即全部」（①/②【关键】条款的
# ②侧保护载荷：合法②不得被①的「每存活问题≥1候选」要求误伤）
CLEAN2 = copy.deepcopy(S1_BASE)
CLEAN2["purpose"] = (
    "从ProblemContext唯一存活问题尝试引出目标，覆盖who/outcome/初步价值；"
    "经本步 AskUserQuestion 补问，用户声明字面请求即全部，结论选择②目标不成立。"
)
CLEAN2["a"][3] = "无目标候选：用户声明字面请求即全部（见结论补问原话佐证）。"
CLEAN2["a"][4] = (
    "结论②目标不成立：本步 AskUserQuestion 补问「除了统计正IC因子数量，"
    "是否还有进一步目标或诉求？」，用户回答原话：'没有了，就这个。'"
    "——字面请求即全部，无进一步诉求。"
)

VIO1 = copy.deepcopy(S1_BASE)  # 孤儿目标候选：G2 对应不上存活问题=脑补
VIO1["q"].insert(4, "除 G1 外还有其他目标候选吗？")
VIO1["a"].insert(4, "G2：为当前提问者做一个因子 IC 分布可视化看板，方便日常浏览。")
VIO1["a"][5] = (
    "结论①目标成立；唯一存活问题已有目标候选G1，全部事实均有用户原话"
    "或已确认ProblemContext出处。"
)

VIO2 = copy.deepcopy(S1_BASE)  # 空泛复述：答案复述提问本身，无原话无会话事实
VIO2["a"][0] = "受益者是想了解正IC因子数量的人。"
VIO2["a"][1] = "达成统计出IC均值严格大于0的因子数量的状态。"
VIO2["a"][2] = "价值是知道了正IC因子的数量，有助于后续筛选工作。"

VIO3 = copy.deepcopy(S1_BASE)  # ②偷懒：结论②但无任何原话佐证
VIO3["purpose"] = (
    "从ProblemContext唯一存活问题尝试引出目标，覆盖who/outcome/初步价值；"
    "用户字面请求即全部，结论选择②目标不成立。"
)
VIO3["a"][3] = "无目标候选。"
VIO3["a"][4] = "结论②目标不成立：用户字面请求即全部，没有进一步诉求。"

VIO4 = copy.deepcopy(S1_BASE)  # ②未问先引：「未提及」冒充佐证（本步未做任何补问）
VIO4["purpose"] = VIO3["purpose"]
VIO4["a"][3] = "无目标候选。"
VIO4["a"][4] = "结论②目标不成立：用户未提及任何进一步目标或价值诉求。"

VIO6 = copy.deepcopy(S1_BASE)  # 张冠李戴：who 项引「原始请求」标注（who×原始请求
VIO6["a"][0] = "原始请求：'现在有多少个因子的IC为正？'"  # 不对口词形=生产墙）
VIO6["a"][1] = "用户原话：'我自己'。"

# artifact=单行 JSON（生产 read_evidence_for_step(1,"GoalsAndValue") 同形）
CASES = {
    "clean": CLEAN,
    "clean2_legit_no_goal": CLEAN2,
    "vio1_orphan_goal": VIO1,
    "vio2_empty_restate": VIO2,
    "vio3_lazy_no_evidence": VIO3,
    "vio4_unasked_absence": VIO4,
    "vio6_misplaced_quote": VIO6,
}
EXPECT = {
    "clean": True,
    "clean2_legit_no_goal": True,
    **{k: False for k in CASES if not k.startswith("clean")},
}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {k: json.dumps(t, ensure_ascii=False) for k, t in CASES.items()}
    run_cases("u:2#1 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
