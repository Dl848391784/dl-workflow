#!/usr/bin/env python3
"""u:1#5 归一化陈述 gate 回归重放（v2.85 反转的回归资产，
designs/u1-sub5-gate-framing-design.md）。

clean(demo 真实子6 现代化：子5 处置后问题集→statements 归一化，四态传导齐备) /
vio1 证伪项混入陈述集 / vio2 部分成立项超出已证实边界 /
vio3 复合句（「和」连接两个独立痛点） / vio4 text 含实现侧名词/file:line。
artifact=子5+子6 最新 trace 拼合（生产 read_evidence_for_step(6) 同形——
判据「裁决不传导」的对照基准在子5 verdict/处置后问题集）。

用法: python3 tests/replays/replay_u1_sub5.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "理解问题和背景 · 子步骤6（归一化陈述）"
STEP = sub_step("understand:1", 5)

# ---- 子4 trace（生产 artifact 含前序各步最新 trace；verdict/处置后问题集是对照基准）----
S4_BASE = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "ProblemContext",
    "sub_step": 5,
    "skill": "推理(三关质检+四态合成) / Agent(红队子代理,条件触发)",
    "purpose": "质检裁决（不做新搜索，只审子3证据+下结论）。证据三关质检逐项。",
    "q": [
        "E1-E6 各证据的针对性、独立性、可追溯性分别是什么？",
        "红队是否按触发条件执行，结果是什么？",
        "P1 四态 verdict、推理链和置信度是什么？",
        "P2-P4 四态 verdict、推理链和置信度是什么？",
        "处置后的问题集是什么？",
    ],
    "a": [
        "E1=summary/result/default/factor_summary_report_2026-07-25.txt:9-22（72结果、截至2026-07-24），针对性通过/独立性通过/可追溯性通过。E2=同文件:31-104（72条IC均值及14个严格正值），针对性通过/独立性通过/可追溯性通过。E3=Bash Python复算parsed_rows=72 positive_ic_mean=14，针对性通过/独立性不通过（由E2派生）/可追溯性通过。E4=同文件:372-395（IC均值<0反向因子说明），针对性通过/独立性不通过（同一报告）/可追溯性通过。E5=OpenAlex/StackExchange API结果，针对性不通过/独立性通过/可追溯性通过（URL）。E6=WebFetch定点页面尝试，针对性不通过/独立性不适用/可追溯性通过（错误留痕）。",
        "是。因数量用于决定筛选门槛，触发条件成立；先由 engine redteam-prompt 生成提示，再由独立 Agent 点查，红队未发现推翻空间。",
        "P1=证实。E1确认72项当前范围，E2逐项直接计出14，E3复算一致，E4确认IC均值正负口径；置信度高，限制为报告截至2026-07-24。",
        "P2=证实/高（单一问题）；P3=证实/中高（因果链闭合）；P4=证实/高（H1排除）。",
        "仅保留P1，且收窄为default最新报告中严格IC均值>0的因子数量；P2-P4保留为背景链；无证伪项；外部不针对本仓数量的背景证据不进入问题集。",
    ],
}

# ---- 子5 clean（demo.jsonl 真实子5 trace 现代化：qa→statements，四态传导齐备）----
S5_CLEAN = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "ProblemContext",
    "sub_step": 6,
    "skill": "define-problem",
    "purpose": "归一化陈述：对子5处置后问题集产出归一化问题陈述。P1 归一化，P2-P4 背景链不进入陈述集。",
    "statements": [
        {
            "text": "统计 default 管线最新报告中严格 IC 均值大于 0 的因子数量",
            "type_label": "证实",
            "boundary": "default 管线；报告数据截至 2026-07-24；IC 口径为 IC 均值；严格大于 0",
            "fields": {"confidence": "高"},
        },
    ],
}

# ---- vio1：证伪项混入陈述集（裁决不传导）----
S5_VIO1 = copy.deepcopy(S5_CLEAN)
S5_VIO1["statements"].append(
    {
        "text": "外部 API 不直接支持本仓数量判断",
        "type_label": "证伪",
        "boundary": "E5 针对性不通过",
        "fields": {"confidence": "高"},
    }
)

# ---- vio2：部分成立项超出已证实边界（裁决不传导第二形态）----
# 载荷保真度（#30 ⑦）：初版用「，并评估…」被 judge 全判成复合句（与 vio3 撞车，
# 测不到目标判据）——本形态须**单目标**、只在断言强度上越界：子4 P1 收窄为
# 「default 管线 + 截至 2026-07-24 的报告快照」，陈述却抹掉快照限定改成
# 「全部管线/实时」的更强断言。
S5_VIO2 = copy.deepcopy(S5_CLEAN)
S5_VIO2["statements"] = [
    {
        "text": "统计全部管线当前实时严格 IC 均值大于 0 的因子数量",
        "type_label": "部分成立",
        "boundary": "已证实边界：default 管线；报告数据截至 2026-07-24",
        "fields": {"confidence": "中"},
    },
]

# ---- vio3：复合句（「和/以及/同时」连接多个独立痛点）----
S5_VIO3 = copy.deepcopy(S5_CLEAN)
S5_VIO3["statements"] = [
    {
        "text": "统计 default 管线中正 IC 因子数量，以及评估负 IC 因子取反后反向使用是否成立",
        "type_label": "证实",
        "boundary": "default 管线；数据截至 2026-07-24",
        "fields": {"confidence": "高"},
    },
]

# ---- vio4：text 含实现侧名词/file:line（未挪 boundary）----
S5_VIO4 = copy.deepcopy(S5_CLEAN)
S5_VIO4["statements"] = [
    {
        "text": "统计 factor_summary_report_2026-07-25.txt 第 31-104 行中严格 IC 均值大于 0 的因子数量",
        "type_label": "证实",
        "boundary": "default 管线；数据截至 2026-07-24",
        "fields": {"confidence": "高"},
    },
]

# (子4 trace, 子5 trace) 对——artifact=两行 JSON 拼接（生产 read_evidence_for_step 同形）
CASES = {
    "clean": (S4_BASE, S5_CLEAN),
    "vio1_证伪混入": (S4_BASE, S5_VIO1),
    "vio2_边界超出": (S4_BASE, S5_VIO2),
    "vio3_复合句": (S4_BASE, S5_VIO3),
    "vio4_实现名词": (S4_BASE, S5_VIO4),
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {
        k: json.dumps(s4, ensure_ascii=False)
        + "\n"
        + json.dumps(s5, ensure_ascii=False)
        for k, (s4, s5) in CASES.items()
    }
    run_cases("u:1#5 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
