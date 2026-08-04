#!/usr/bin/env python3
"""u:4#4 归一化陈述 gate 回归重放（v2.98 反转的回归资产，
designs/u4-sub4-gate-framing-design.md）。

clean（demo 场景续写：子3 验收方式设计->statements 归一化，
验收包六字段+type_label(验收方法/时机)+verdict 边界传导齐备；
G1=「基于 default 管线数据截至 2026-07-24 IC均值严格大于0 的
因子规模决定筛选门槛」同 u4-sub1 载荷集）/
vio1 验收包字段不传导（子3 定方法=demonstration、陈述篡改为 analysis）/
vio2 边界不传导（抹掉 default 管线+数据截至 2026-07-24 已证实口径限定，
断言全部管线当前实时）/
vio3 复合句（「以及」连接 SC1.1 规模核对与 SC2.1 口径核对两个独立标准）/
vio4 方案动作残留（text 主语=「开发脚本统计…」实现动作，未剥到 outcome）。
artifact=子3+子4 最新 trace 拼合（生产 read_evidence_for_step(4,"SuccessCriteria")
同形--判据「与子3 逐项一致/传导」的对照基准在子3 验收方式设计；子1 候选/
子2 可检验化不涉本 gate 判据，不拼入=u:3#4 同构）。

用法: python3 tests/replays/replay_u4_sub4.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "定义成功标准和验收方式 · 子步骤4"
STEP = sub_step("understand:4", 3)

# ---- 子3 trace（验收方式设计：方法选择+可行性三态+时机+证据形式；合成但锚 demo 场景）----
S3_BASE = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "SuccessCriteria",
    "sub_step": 3,
    "skill": "推理(INCOSE 四法) / Bash / codegraph / Read(手段存在性)",
    "purpose": "对子2 可检验标准逐条定验收方式：方法选择(INCOSE 四法)+可行性三态+时机标注+证据形式锚定。",
    "q": [
        "每条标准的验收方法（INCOSE 四法）+选择理由？",
        "可行性三态处置（存在附出处/待建标注/剔除附理由）？",
        "验收时机标注（triggered/continuous；事后验证标风险+代理）？",
        "证据形式锚定（review 判 solved/partial/not 时拿什么）？",
    ],
    "a": [
        "SC1.1 方法=demonstration（跑起来看实际行为输出：打开 default 管线最新报告读正 IC 因子条数与占比），选择理由=规模数字类标准须实际跑出数字核对；SC2.1 方法=inspection（review checklist 逐项核查：报告 IC 口径与用户口述口径对照），选择理由=口径一致性类标准用审查核对而非跑测。",
        "可行性三态：SC1.1 验收手段存在（default 管线报告产物在本仓，Bash 实测确认报告含因子明细表与数据截至日期字段，附出处）；SC2.1 验收手段存在（报告含 IC 口径字段，Read 确认）；无待建手段；无剔除项。",
        "时机标注：SC1.1=triggered（review 一次性判--打开报告核对数字）；SC2.1=triggered（review 一次性判--口径对照）；无 continuous 持续监控项；无事后验证项（T+1 实战效果不涉本实例目标）。",
        "证据形式：SC1.1=报告页面读出的正 IC 因子条数与占全部因子的百分比数字；SC2.1=IC 口径名称与比较关系与用户口述对照结果。",
    ],
}

# ---- 子4 clean（demo 场景续写：SC1.1/SC2.1 归一化，验收包六字段+type_label+边界传导齐备）----
S4_CLEAN = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "SuccessCriteria",
    "sub_step": 4,
    "skill": "define-problem",
    "purpose": "对子3 标准集逐项产出归一化成功标准陈述：原子+去上下文+完整验收包六字段+verdict 边界+solution-free 复核。",
    "statements": [
        {
            "text": "验收时打开 default 管线最新报告，能读出正 IC 因子条数与占全部因子的百分比两个数字，且与报告内因子明细逐条计数一致",
            "type_label": "demonstration/triggered",
            "boundary": "SC1.1；G1 全量覆盖",
            "指标": "正 IC 因子条数、占全部因子的百分比",
            "基线": "报告内因子明细逐条计数",
            "阈值提案": "条数与占比与明细计数一致",
            "验收方法": "demonstration",
            "时机": "triggered",
            "证据形式": "报告页面读出的条数与占比数字",
        },
        {
            "text": "验收时拿报告 IC 口径与用户口述口径对照，能确认所用 IC 是 IC均值 且比较关系是严格大于 0",
            "type_label": "inspection/triggered",
            "boundary": "SC2.1；G1 全量覆盖",
            "指标": "IC 口径名称、比较关系",
            "基线": "用户口述口径（IC均值严格大于0）",
            "阈值提案": "口径名称与比较关系与用户口述一致",
            "验收方法": "inspection",
            "时机": "triggered",
            "证据形式": "口径名称与比较关系对照结果",
        },
    ],
}

# ---- vio1：验收包字段不传导（子3 定方法=demonstration，陈述篡改为 analysis）----
# 单变量：只改「验收方法」字段（type_label 跟随保持内部一致），其余六字段+边界不动。
S4_VIO1 = copy.deepcopy(S4_CLEAN)
S4_VIO1["statements"][0]["验收方法"] = "analysis"
S4_VIO1["statements"][0]["type_label"] = "analysis/triggered"

# ---- vio2：边界不传导（抹掉 default 管线+数据截至 2026-07-24 已证实口径限定，断言超出已证实边界）
# 载荷保真度（#30 ⑦，u:3#4 vio2 同构）：单目标、只在断言强度上越界--
# 子3 SC1.1 限 default 管线最新报告（含数据截至日期），陈述抹掉限定改成「全部管线当前实时」。
S4_VIO2 = copy.deepcopy(S4_CLEAN)
S4_VIO2["statements"][0]["text"] = (
    "验收时打开全部管线当前实时的报告，能读出正 IC 因子条数与占全部因子的百分比两个数字，"
    "且与报告内因子明细逐条计数一致"
)

# ---- vio3：复合句（「以及」连接 SC1.1 规模核对与 SC2.1 口径核对两个独立标准）----
S4_VIO3 = copy.deepcopy(S4_CLEAN)
S4_VIO3["statements"] = [
    {
        "text": (
            "验收时打开 default 管线最新报告，能读出正 IC 因子条数与占全部因子的百分比两个数字，"
            "且与报告内因子明细逐条计数一致，以及拿报告 IC 口径与用户口述口径对照，"
            "能确认所用 IC 是 IC均值 且比较关系是严格大于 0"
        ),
        "type_label": "demonstration/triggered",
        "boundary": "SC1.1",
        "指标": "正 IC 因子条数、占全部因子的百分比",
        "基线": "报告内因子明细逐条计数",
        "阈值提案": "条数与占比与明细计数一致",
        "验收方法": "demonstration",
        "时机": "triggered",
        "证据形式": "报告页面读出的条数与占比数字",
    },
    S4_CLEAN["statements"][1],  # SC2.1 不变，保留逐项一致基准
]

# ---- vio4：方案动作残留（text 主语=实现动作「开发脚本统计…」，未剥到 outcome）----
S4_VIO4 = copy.deepcopy(S4_CLEAN)
S4_VIO4["statements"][0]["text"] = (
    "开发脚本统计 default 管线中数据截至 2026-07-24 的正 IC 因子条数与占比，"
    "使验收时能读出这两个数字"
)

# (子3 trace, 子4 trace) 对--artifact=两行 JSON 拼接（生产 read_evidence_for_step 同形）
CASES = {
    "clean": (S3_BASE, S4_CLEAN),
    "vio1_验收包字段不传导": (S3_BASE, S4_VIO1),
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
    run_cases("u:4#4 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
