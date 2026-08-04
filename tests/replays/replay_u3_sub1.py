#!/usr/bin/env python3
"""u:3#1 障碍分析引出 gate 回归重放（framing 反转的回归资产，
designs/u3-sub1-gate-framing-design.md）。

clean（KAOS 否定提问逐目标具体化 + 约束类型 4 类 + 结论①逐句出处 + 推测另列）/
vio1 空泛约束（「数据可能不准」式无具体对象）/
vio2 否定提问套话（每目标同一句「可能会失败」，未针对目标内容具体化）/
vio3 类型不足（约束类型仅 2 类，形式要件要求 ≥3 类）/
vio4 ②偷懒（结论「无实质约束」但无任一 must 目标的否定提问留痕）/
vio5 结论无出处推断（推断混入结论、未标「推测」另列）。

artifact=子1 单条 trace JSON（生产 read_evidence_for_step(1,"ScopeAndConstraints")
同形——子1 是本节点首步，minor_stage 过滤后无前序拼合，无跨节点串号面；
must 目标集在 GoalsAndValue.step4 跨节点，judge 判材内不可见=判据须钉「不判完整性」）。

用法: python3 tests/replays/replay_u3_sub1.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "确定范围与约束 · 子步骤1"
STEP = sub_step("understand:3", 0)

# ---- clean：承接 demo 因子 IC 统计场景（must 目标集={G1}），KAOS 逐目标具体化 ----
BASE = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "ScopeAndConstraints",
    "sub_step": 1,
    "skill": "推理(KAOS 障碍分析) / AskUserQuestion(补问)",
    "purpose": "对 GoalsAndValue 子4 归一化 must 目标集逐目标做 KAOS 否定提问引出约束候选，覆盖 ≥3 类约束；用户侧约束缺口经 AskUserQuestion 补问。结论选择①约束成立。",
    "q": [
        "must 目标集是什么，逐目标的否定提问如何提出？",
        "G1 否定提问「什么会使它失败」的答案（代码库结构/项目硬规则类）是什么？",
        "G1 否定提问的答案（数据契约类）是什么？",
        "G1 否定提问的答案（环境工具链类）是什么？",
        "用户侧约束（deadline/人力/权限）缺口如何补问？",
        "约束候选清单与类型覆盖如何汇总？",
        "结论①约束成立还是②无实质约束？",
    ],
    "a": [
        "GoalsAndValue 子4 归一化陈述给出的 must 目标集={G1「当前提问者能够基于 default 管线中数据截至2026-07-24 且 IC均值严格大于0 的因子规模，决定因子筛选门槛」}，共 1 个 must 目标。对 G1 做否定提问：「什么会使『提问者拿到该口径因子规模并据此决定门槛』失败？」逐类展开见下三条。",
        "C1.1 项目硬规则：CLAUDE.md §5 H7 规定路径只能 `from paths import`——若统计脚本自行拼 report 目录字符串，报告定位会在路径迁移后静默失效，G1 的「default 管线最新报告」口径随之失真。出处=Read CLAUDE.md 原文「H7：路径只能 `from paths import`」。C1.2 代码库结构：CLAUDE.md §5 H1/H1.1 规定 web_ui 只读不改后端——若为取数改后端聚合逻辑即越界，G1 只能走既有报告读取通道。出处=Read CLAUDE.md 原文。",
        "C2.1 数据契约：报告 IC 字段口径为 ic_mean，且报告自带 data_date/report_date 两个日期字段——若统计混用 report_date 当数据日期，G1 的「数据截至2026-07-24」口径失败。出处=用户已确认问题陈述中的口径「数据截至2026-07-24」+ 报告字段名。C2.2 数据契约（freshness）：若 default 管线最新报告的 data_date 早于 2026-07-24，则不存在满足口径的报告，G1 无法达成。",
        "C3.1 环境工具链：读 parquet/报告需项目 venv 的 pyarrow（CLAUDE.md §3 执行映射「读 parquet: python3 -c import pyarrow，项目 venv 有 pyarrow」）——脱离项目 venv 执行则取数失败。C3.2 环境工具链：大 JSON 需流式 load_factor_values()，禁 json.load 全量（同 §3 表，OOM exit 137）——全量读会在因子值文件上被 OOM 杀死，G1 取不到规模数字。出处=Read CLAUDE.md §3 原文。",
        "用户侧约束缺口=deadline/人力/权限三项在上下文中均无原话。经 AskUserQuestion 补问「本次统计有时间或权限约束吗」，用户原话（AskUserQuestion 选中）：'没有时间压力，本地只读跑就行'。据此记 C4.1 时间资源：无 deadline 约束（用户明示）；C4.2 权限：限本地只读执行，不涉及线上写权限。",
        "约束候选清单=C1.1/C1.2（项目硬规则、代码库结构）、C2.1/C2.2（数据契约含 freshness）、C3.1/C3.2（环境工具链）、C4.1/C4.2（时间资源/权限）。类型覆盖 4 类：项目硬规则、代码库结构、数据契约、环境工具链（另含时间资源/权限用户侧两条）。q/a 按序对齐，每条候选均绑定具体对象（规则条号/字段名/工具名）。",
        "结论①约束成立：唯一 must 目标 G1 已做 KAOS 否定提问并引出 ≥1 约束候选（实际 8 条），类型覆盖 4 类 ≥3 类要求。逐句出处：硬规则类出处=Read CLAUDE.md §5 原文；工具链类出处=Read CLAUDE.md §3 执行映射原文；用户侧出处=AskUserQuestion 选中原话'没有时间压力，本地只读跑就行'；数据契约类出处=已确认问题陈述口径+报告字段名。推测（另列，不纳入约束集）：报告目录下可能存在历史归档报告干扰最新报告定位——本条未经工具验证，标「推测」留子2 定真伪。",
    ],
}

CLEAN = copy.deepcopy(BASE)

# vio1 空泛约束（C1）：候选无具体对象，「数据可能不准」式
VIO1 = copy.deepcopy(BASE)
VIO1["a"][1] = "可能有代码结构方面的问题，改动会有风险。"
VIO1["a"][2] = "数据可能不准，也可能不够新。"
VIO1["a"][3] = "环境可能有依赖问题，工具链也可能出错。"
VIO1["a"][5] = (
    "约束候选清单=代码结构风险、数据可能不准、环境依赖问题、时间可能不够。类型覆盖 4 类。"
)

# vio2 否定提问套话（C2）：双目标同一句套话，未针对目标内容具体化
VIO2 = copy.deepcopy(BASE)
VIO2["a"][0] = (
    "must 目标集={G1「当前提问者能够基于 default 管线中数据截至2026-07-24 且 IC均值严格大于0 "
    "的因子规模，决定因子筛选门槛」, G2「当前提问者能够按既有报告口径复核统计结果」}，"
    "共 2 个 must 目标。对 G1 的否定提问：「什么会使它失败？」；对 G2 的否定提问："
    "「什么会使它失败？」——两目标均用同一句提问，未针对目标内容具体化。"
)
VIO2["a"][6] = (
    "结论①约束成立：G1、G2 均已做否定提问「什么会使它失败」并引出约束候选，"
    "类型覆盖 4 类。逐句出处同上。"
)

# vio3 类型不足（C3）：仅 2 类（形式要件要求 ≥3 类）
VIO3 = copy.deepcopy(BASE)
VIO3["a"][2] = (
    "C2.1 数据契约：报告 IC 字段口径为 ic_mean，混用 report_date 当数据日期则口径失败。"
    "出处=已确认问题陈述口径+报告字段名。"
)
VIO3["a"][3] = (
    "C2.2 数据契约：若 default 管线最新报告 data_date 早于 2026-07-24，则无满足口径的报告。"
)
VIO3["a"][4] = "用户侧约束未补问，本轮不涉及。"
VIO3["a"][5] = (
    "约束候选清单=C1.1/C1.2（项目硬规则）、C2.1/C2.2（数据契约）。"
    "类型覆盖 2 类：项目硬规则、数据契约。"
)
VIO3["a"][6] = (
    "结论①约束成立：G1 已做否定提问并引出 4 条候选，类型覆盖 2 类。逐句出处同上。"
)

# vio4 ②偷懒（C4）：申报「无实质约束」但无任一 must 目标的否定提问留痕
VIO4 = copy.deepcopy(BASE)
VIO4["q"] = [
    "must 目标集是什么？",
    "约束候选清单是什么？",
    "结论①约束成立还是②无实质约束？",
]
VIO4["a"] = [
    "must 目标集={G1「当前提问者能够基于 default 管线中数据截至2026-07-24 且 "
    "IC均值严格大于0 的因子规模，决定因子筛选门槛」}，共 1 个 must 目标。",
    "约束候选清单=空。本任务只是读一个已有报告数字，没有什么会拦住它。",
    "结论②无实质约束：该目标是纯读取型任务，不存在实质约束。",
]
VIO4["purpose"] = "对 must 目标集引出约束候选。结论选择②无实质约束。"

# vio5 结论无出处推断（C5）：推断混入结论正文、未标「推测」另列
VIO5 = copy.deepcopy(BASE)
VIO5["a"][6] = (
    "结论①约束成立：唯一 must 目标 G1 已做 KAOS 否定提问并引出 8 条约束候选，"
    "类型覆盖 4 类。另外，报告目录下存在历史归档报告干扰最新报告定位，"
    "这意味着定位逻辑必须按 report_date 降序取首条；用户长期使用 web_ui 翻报告，"
    "隐含其对报告路径变更容忍度低，因此路径类约束优先级最高。"
)

CASES = {
    "clean": CLEAN,
    "vio1_vague_constraint": VIO1,
    "vio2_boilerplate_negation": VIO2,
    "vio3_types_insufficient": VIO3,
    "vio4_lazy_no_constraint": VIO4,
    "vio5_unsourced_inference": VIO5,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {k: json.dumps(t, ensure_ascii=False) for k, t in CASES.items()}
    run_cases("u:3#1 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
