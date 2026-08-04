#!/usr/bin/env python3
"""u:3#4 归一化陈述 gate 回归重放（v2.92 反转的回归资产，
designs/u3-sub4-gate-framing-design.md）。

clean(demo 真实场景续写合成：子3 范围与约束集→statements 归一化，
类型标注+边界传导齐备；G1=「基于 default 管线数据截至 2026-07-24 IC>0 的
因子规模决定筛选门槛」同 u3-sub1/sub3 载荷集；约束经约束回写折叠进 in[1]
边界口径，不单列约束陈述=u:2#4 单目标同构的干净面) /
vio1 类型标注不传导（子3 提案 in、陈述标 out） / vio2 边界不传导
（抹掉 2026-07-24 快照限定，断言全部管线当前实时） /
vio3 复合句（「以及」连接 in[1] 查看与 out[1] 排除两个独立范围项） /
vio4 方案动作残留（text 主语=「开发脚本统计…」实现动作）。
artifact=子3+子4 最新 trace 拼合（生产 read_evidence_for_step(4) 同形——
判据「与子3 逐项一致/传导」的对照基准在子3 范围与约束集；
子1 约束候选/子2 三态处置不涉本 gate 判据，不拼入=u:2#4 同构）。

用法: python3 tests/replays/replay_u3_sub4.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "确定范围与约束 · 子步骤4"
STEP = sub_step("understand:3", 3)

# ---- 子3 trace（范围界定：in/out 双侧清单+双字段+双向追溯+约束回写；合成但锚 demo 场景）----
S3_BASE = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "ScopeAndConstraints",
    "sub_step": 3,
    "skill": "推理(双向追溯矩阵+约束回写)",
    "purpose": "从 must/nice 裁决 + GoalsAndValue 子5 用户圈定范围派生 in/out 双侧清单，每项双字段（outcome 标签+实现指针），双向追溯 + 约束回写；只提案不拍板。",
    "q": [
        "in-scope 清单及每项双字段（outcome 标签+实现指针）？",
        "out-of-scope 显式列举哪些（看似该做但不做）？",
        "双向追溯矩阵（in 项←must 目标 + 每个 must 目标有范围覆盖/显式搁置）？",
        "约束回写：已验证约束/已标注假设迫使缩小范围处？",
    ],
    "a": [
        "in[1] 正 IC 因子规模：outcome 标签=用户可查看 default 管线中数据截至 2026-07-24 的正 IC 因子数量；实现指针=本地报告产物与因子集（子2 已验证）。",
        "out[1] 因子策略回测系统：看似该做（决定门槛后需验证）但超出本实例统计目标，显式搁置。",
        "in[1]←G1：决定门槛需先知因子规模（backward 防镀金）；G1→in[1] 有范围覆盖（forward 防漏）；out[1] 显式搁置+理由。",
        "约束回写：无独立约束条目——子2 约束验证后的口径限定已直接体现于范围项边界（in[1] 限 default 管线、数据截至 2026-07-24），本子阶段范围与约束集仅含 in/out 范围项。",
    ],
}

# ---- 子4 clean（demo 场景续写：范围项 in[1]/out[1] 归一化，传导齐备；约束已折叠进边界）----
S4_CLEAN = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "ScopeAndConstraints",
    "sub_step": 4,
    "skill": "define-problem",
    "purpose": "对子3 范围与约束集逐项装配归一化陈述：text 取 outcome 标签、实现指针进 boundary，solution-free 复核。",
    "statements": [
        {
            "text": "用户能够查看 default 管线中数据截至 2026-07-24 的正 IC 因子数量",
            "type_label": "in",
            "boundary": "in[1]",
        },
        {
            "text": "因子策略回测系统不纳入本实例范围",
            "type_label": "out",
            "boundary": "out[1]；显式搁置：超出本实例统计目标、用户未确认",
        },
    ],
}

# ---- vio1：类型标注不传导（子3 提案 in，陈述标 out）----
S4_VIO1 = copy.deepcopy(S4_CLEAN)
S4_VIO1["statements"][0]["type_label"] = "out"

# ---- vio2：边界不传导（抹掉 2026-07-24 快照限定，断言超出已证实边界）----
# 载荷保真度（#30 ⑦，u:1#5 vio2 / u:2#4 vio2 同构）：单目标、只在断言强度上越界——
# 子3 in[1] 限 default 管线+快照，陈述抹掉限定改成「全部管线当前实时」。
S4_VIO2 = copy.deepcopy(S4_CLEAN)
S4_VIO2["statements"][0] = {
    "text": "用户能够查看全部管线当前实时的正 IC 因子数量",
    "type_label": "in",
    "boundary": "in[1]",
}

# ---- vio3：复合句（「以及」连接两个独立范围项 in[1] 查看 + out[1] 排除）----
S4_VIO3 = copy.deepcopy(S4_CLEAN)
S4_VIO3["statements"] = [
    {
        "text": "用户能够查看 default 管线中数据截至 2026-07-24 的正 IC 因子数量，以及因子策略回测系统不纳入本实例范围",
        "type_label": "in",
        "boundary": "in[1]",
    },
    S4_CLEAN["statements"][1],  # out[1] 不变，保留逐项一致基准
]

# ---- vio4：方案动作残留（text 主语=实现动作，未剥到 outcome）----
S4_VIO4 = copy.deepcopy(S4_CLEAN)
S4_VIO4["statements"][0] = {
    "text": "开发脚本统计 default 管线中数据截至 2026-07-24 的正 IC 因子数量，使用户能够查看",
    "type_label": "in",
    "boundary": "in[1]",
}

# (子3 trace, 子4 trace) 对——artifact=两行 JSON 拼接（生产 read_evidence_for_step 同形）
CASES = {
    "clean": (S3_BASE, S4_CLEAN),
    "vio1_类型标注不传导": (S3_BASE, S4_VIO1),
    "vio2_边界不传导": (S3_BASE, S4_VIO2),
    "vio3_复合句": (S3_BASE, S4_VIO3),
    "vio4_方案动作残留": (S3_BASE, S4_VIO4),
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
    run_cases("u:3#4 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
