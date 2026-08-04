#!/usr/bin/env python3
"""u:2#4 归一化陈述 gate 回归重放（v2.88 反转的回归资产，
designs/u2-sub4-gate-framing-design.md）。

clean(demo 真实子4 现代化：子3 价值论证后目标集→statements 归一化，分层+边界传导齐备) /
vio1 分层不传导（子3 提案 must、陈述标 nice） / vio2 边界不传导（抹掉 default 管线+快照限定，
断言超出已证实边界） / vio3 复合句（「以及」连接两个独立目标） /
vio4 方案名词/实现动词残留（text 主语=「开发脚本…」方案动作）。
artifact=子3+子4 最新 trace 拼合（生产 read_evidence_for_step(4) 同形——
判据「与子3 逐项一致/传导」的对照基准在子3 分层提案+边界）。

用法: python3 tests/replays/replay_u2_sub4.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "明确目标和价值 · 子步骤4"
STEP = sub_step("understand:2", 3)

# ---- 子3 trace（demo 真实子3 返工补齐版=最新；分层提案+边界是对照基准）----
S3_BASE = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "GoalsAndValue",
    "sub_step": 3,
    "skill": "推理(价值链+分层理由) / Bash(条件性基线测量)",
    "purpose": "返工补齐G1价值链痛点出处与量化基线的可核验工具留痕；保留must/nice为待用户裁决提案。",
    "q": [
        "G1受益者及出处是什么？",
        "价值链每一节点及出处是什么？",
        "基线测量使用的具体命令、输入路径和原始输出是什么？",
        "哪些目标状态不可量化及原因是什么？",
        "must/nice提案及理由是什么？",
    ],
    "a": [
        "受益者=当前提问者本人；出处为用户在'这次查询结果主要是谁在使用？'中原话选择'我自己'。",
        "G1'能够决定因子筛选门槛'（出处：用户原话'决定筛选门槛'）→承接痛点A'候选太多'→根因痛点B'没有缩减规则'→直接价值'继续筛选'→价值类型=决策支持/筛选效率。",
        "Bash实测最新default报告：path=summary/result/default/factor_summary_report_2026-07-25.txt rows=72 positive=14 share=19.44%。报告自身:9-22给数据截至2026-07-24及72个结果。",
        "'用户是否已经决定具体筛选门槛'不可量化+原因：这是用户后续人工裁决状态，当前仓库报告和会话没有具体门槛值或完成记录；不以推测值替代。",
        "提案G1=must：本实例确认的问题是得到正IC因子数量以决定门槛，若不给出边界明确且可复核的数量，本实例即失败；最终分层裁决留给子5用户。nice提案=无：名单、阈值建议、自动筛选均未被用户确认为目标，添加会镀金；此处仍是提案，未替用户拍板。",
    ],
}

# ---- 子4 clean（demo 真实子4 qa trace 现代化：qa→statements，分层+边界传导齐备）----
S4_CLEAN = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "GoalsAndValue",
    "sub_step": 4,
    "skill": "define-problem",
    "purpose": "将子3论证后的唯一目标G1归一化为原子、自包含、solution-free的目标陈述，并携带must提案和已证实问题边界。",
    "statements": [
        {
            "text": "当前提问者能够基于 default 管线中数据截至 2026-07-24 且 IC 均值严格大于 0 的因子规模，决定因子筛选门槛",
            "type_label": "must",
            "boundary": "P1 证实、高置信度；仅覆盖 default 管线、数据截至 2026-07-24、IC 口径=IC 均值且严格大于 0；must 为提案，最终裁决在子5",
        },
    ],
}

# ---- vio1：分层不传导（子3 提案 must，陈述标 nice）----
S4_VIO1 = copy.deepcopy(S4_CLEAN)
S4_VIO1["statements"][0]["type_label"] = "nice"

# ---- vio2：边界不传导（抹掉 default 管线+快照限定，断言超出已证实边界）----
# 载荷保真度（#30 ⑦，u:1#5 vio2 同构）：单目标、只在断言强度上越界——
# 子3 基线限 default 管线+截至 2026-07-24 快照，陈述抹掉限定改成「全部管线/实时」。
S4_VIO2 = copy.deepcopy(S4_CLEAN)
S4_VIO2["statements"] = [
    {
        "text": "当前提问者能够基于全部管线当前实时 IC 均值大于 0 的因子规模，决定因子筛选门槛",
        "type_label": "must",
        "boundary": "P1 证实",
    },
]

# ---- vio3：复合句（「以及」连接两个独立目标）----
S4_VIO3 = copy.deepcopy(S4_CLEAN)
S4_VIO3["statements"] = [
    {
        "text": "当前提问者能够基于 default 管线中数据截至 2026-07-24 且 IC 均值严格大于 0 的因子规模，决定因子筛选门槛，以及掌握正 IC 因子的 IC 分布形态",
        "type_label": "must",
        "boundary": "P1 证实、高置信度；仅覆盖 default 管线、数据截至 2026-07-24",
    },
]

# ---- vio4：方案名词/实现动词残留（text 主语=方案动作，未剥到 outcome）----
S4_VIO4 = copy.deepcopy(S4_CLEAN)
S4_VIO4["statements"] = [
    {
        "text": "开发脚本统计 default 管线中数据截至 2026-07-24 且 IC 均值严格大于 0 的因子数量，使当前提问者能够决定因子筛选门槛",
        "type_label": "must",
        "boundary": "P1 证实、高置信度；仅覆盖 default 管线、数据截至 2026-07-24",
    },
]

# (子3 trace, 子4 trace) 对——artifact=两行 JSON 拼接（生产 read_evidence_for_step 同形）
CASES = {
    "clean": (S3_BASE, S4_CLEAN),
    "vio1_分层不传导": (S3_BASE, S4_VIO1),
    "vio2_边界不传导": (S3_BASE, S4_VIO2),
    "vio3_复合句": (S3_BASE, S4_VIO3),
    "vio4_方案名词残留": (S3_BASE, S4_VIO4),
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {
        k: json.dumps(s3, ensure_ascii=False)
        + "\n"
        + json.dumps(s4, ensure_ascii=False)
        for k, (s3, s4) in CASES.items()
    }
    run_cases("u:2#4 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
