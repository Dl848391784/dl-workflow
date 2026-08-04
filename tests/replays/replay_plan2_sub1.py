#!/usr/bin/env python3
"""plan:2#1 清点基线 gate 回归重放（v2.102 反转的回归资产，
designs/plan2-sub1-gate-framing-design.md）。

**plan:2（拆解任务与阶段）首个反转节点**。命题性质=保真转换（从 design.md
提取要素/验收包/假设到 element_baseline，input=跨阶段文件 design.md+证据指针），
主敌=「从有到有时的失真与虚构」（无发散步）——与 plan:1 镜像（plan:1 主敌是
无中生有时的固化）。

clean（承接 demo「统计 default 管线正 IC 因子数量并在报告展示」场景，设计包=
plan:1#2 选定候选A：summary 统计函数内加 FACTOR_CATEGORIES 分组键——三清单齐备，
每条附 design.md 行号出处+要素原文引用进 trace 正文，新增候选/矛盾显式「无」，
只提取不创作）/
vio1 要素无出处（E1 凭印象写「应该都在 design.md 里」，无 design.md 行号/
evidence 指针/原文引用）/
vio2 静默新增=二次创作（E1-E3 正常有出处+原文，唯独 E4=`scripts/category_summary.py`
新增独立脚本裸引用无出处无原文，a[3] 仍声明「新增候选：无」——设计包没有的
要素未标新增候选）/
vio3 改写失真（E1 引 design.md 原文『在既有聚合统计函数内增加分组键』却把要素
自述成「重写为独立八维度聚合器」——trace 内引文 vs 自述措辞语义冲突）/
vio4 要素原文未引用（要素只列 file→function+出处行号，无任何『』原文引用）。

vio 载荷保真度（#30 ㉖）：单变量越界——vio1 只换 a[0] 出处留痕、其余不动；
vio2 只加 E4 且改 a[3] 声明、其余不动；vio3 只换 a[0] 措辞、其余不动；
vio4 只换 a[0]/a[1]/a[2] 去原文引用、其余不动。

vio1/vio4 读数口径（设计内委托，同 p1-sub1）：生产墙=mech（element_quote_trace）
100% 先拒（要素清单条目引用代码符号形 .py 却无任何『』原文引用/原文字样=裸条目，
v2.102 挂本节点），judge 侧读数为已知裁量面——v2.102 gate 声明「原文未引用已被
机械校验、你不得以此 block」，judge 正确放行无原文引用的要素条目（judge-only
重放下 vio1/vio4 期望 BLOCK 但命中 0-5/6 是设计内委托，生产里它们到不了 judge）。
vio2 静默新增由 judge 方框一(b) 判、vio3 改写失真由 judge 方框二判（必须 ≥5/6，
判词须引「静默新增/新增候选」与「改写失真/语义冲突」条款）。

artifact=子1 单条 trace（生产 read_evidence_for_step(1,"TaskBreakdown") 同形——
本节点首步，minor_stage 过滤后无前序拼合）。**判材边界特殊性**：Step.input=
「designs/<主题>-design.md + evidence(DesignSolution 子5/6 trace)」——design.md
是**跨阶段主仓 .md 文件**（render-artifact 装配，同 understand.md/plan.md 族），
judge 结构性读不到（evidence 只含 TaskBreakdown 段）；DesignSolution 前步 trace
亦被 minor_stage 过滤。判据须钉「不得以『未见 design.md 原文/无法核对出处行号
真实性』block」（#30 ㉚② 跨阶段变体，p1-sub1 同族）。

用法: python3 tests/replays/replay_plan2_sub1.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "拆解任务与阶段 · 子步骤1"
STEP = sub_step("plan:2", 0)

# ---- clean：三清单齐备，每条附 design.md 行号出处+原文引用 ----
BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "TaskBreakdown",
    "sub_step": 1,
    "skill": "Read(design.md / understand.md) / Bash(grep evidence 设计包 trace)",
    "purpose": (
        "设计包清点与追溯基线：三清单齐备（①原子改动要素清单 file→function→改动"
        "类型逐条赋要素 ID E1/E2/...；②验收包清单逐条 SuccessCriteria 附 ID；"
        "③假设清单含置信度×影响原样转录）；每条附出处（design.md 行号或 evidence "
        "指针）且要素原文引用进 trace 正文；新增候选/设计包内部矛盾显式标注或显式"
        "「无」，q/a 按序对齐；只提取不创作（本步是全节点保真判定基线）。"
    ),
    "q": [
        "①原子改动要素清单（file→function→改动类型，逐条赋 ID）如何？每条附出处与原文吗？",
        "②验收包清单（逐条 SuccessCriteria 附 ID）如何？",
        "③假设清单（置信度×影响，原样转录）如何？",
        "新增候选/设计包内部矛盾标注了吗？只提取不创作确认了吗？",
    ],
    "a": [
        "①要素清单三条：E1=`summary/generate_factor_summary_report.py` "
        "`_aggregate_positive_ic` 统计函数内增加 FACTOR_CATEGORIES 维度分组键"
        "（改）——出处 design.md:12，原文『在既有聚合统计函数内增加 "
        "FACTOR_CATEGORIES 维度分组键，复用 factor_definitions.py 映射做 group "
        "key』；E2=`summary/report/sections.py` `_generate_ic_section` 内增加"
        "八维度汇总区块渲染（改）——出处 design.md:14，原文『_generate_ic_section "
        "内新增八维度汇总区块』；E3=`paths.py` 增加 `CATEGORY_SUMMARY_RESULT` "
        "路径常量（增）——出处 design.md:16，原文『新增 CATEGORY_SUMMARY_RESULT "
        "路径常量』。",
        "②验收包三条：SC1.1『报告展示八维度条数+占比可读出』（design.md:20）；"
        "SC2.1『分组口径与 FACTOR_CATEGORIES 映射一致可核对』（design.md:21）；"
        "SC3.1『交付形态=报告新增八维度汇总区块』（design.md:22）。",
        "③假设一条：H1=FACTOR_CATEGORIES 八维度对全 34 项因子覆盖无遗漏"
        "（置信度中×影响中，原样转录 design.md:25）。",
        "新增候选：显式『无』——三要素均提取自 design.md；设计包内部矛盾：显式"
        "『无』；只提取不创作，未混入 design.md 之外的要素，q/a 按序对齐。",
    ],
}

CLEAN = copy.deepcopy(BASE)

# vio1 要素无出处：E1 凭印象写，无 design.md 行号/evidence 指针/原文引用
VIO1 = copy.deepcopy(BASE)
VIO1["a"][0] = (
    "①要素清单三条：E1=在 summary/generate_factor_summary_report.py 的 "
    "_aggregate_positive_ic 统计函数内增加 FACTOR_CATEGORIES 分组键（改）；"
    "E2=在 summary/report/sections.py 的 _generate_ic_section 内增加八维度汇总"
    "区块渲染（改）；E3=在 paths.py 增加一个汇总结果路径常量（增）。出处应该"
    "都在 design.md 里，按常规路径可查。"
)

# vio2 静默新增=二次创作：E1-E3 正常（有出处+原文），唯独 E4 裸（无出处
# 无原文）且未标「新增候选」——静默混入设计包没有的要素（区别于 vio1 全裸）
VIO2 = copy.deepcopy(BASE)
VIO2["a"][0] = (
    "①要素清单四条：E1=`summary/generate_factor_summary_report.py` "
    "`_aggregate_positive_ic` 统计函数内增加 FACTOR_CATEGORIES 维度分组键"
    "（改）——出处 design.md:12，原文『在既有聚合统计函数内增加 "
    "FACTOR_CATEGORIES 维度分组键，复用 factor_definitions.py 映射做 group "
    "key』；E2=`summary/report/sections.py` `_generate_ic_section` 内增加"
    "八维度汇总区块渲染（改）——出处 design.md:14，原文『_generate_ic_section "
    "内新增八维度汇总区块』；E3=`paths.py` 增加 `CATEGORY_SUMMARY_RESULT` "
    "路径常量（增）——出处 design.md:16，原文『新增 CATEGORY_SUMMARY_RESULT "
    "路径常量』；E4=`scripts/category_summary.py` 新增独立脚本单独输出八维度"
    "汇总到独立文件。"
)
VIO2["a"][3] = (
    "新增候选：显式『无』；设计包内部矛盾：显式『无』；只提取不创作，q/a 按序对齐。"
)

# vio3 改写失真：引用了 design.md 原文「在既有聚合统计函数内增加分组键」却把
# 要素措辞改写成「重写为独立八维度聚合器」——trace 内引文与自述措辞明显冲突
VIO3 = copy.deepcopy(BASE)
VIO3["a"][0] = (
    "①要素清单三条：E1=重写 `summary/generate_factor_summary_report.py` 的 "
    "`_aggregate_positive_ic` 统计函数，将其改造为独立的八维度聚合器，输出全新"
    "的分组统计数据结构（改）——出处 design.md:12，原文『在既有聚合统计函数内"
    "增加 FACTOR_CATEGORIES 维度分组键，复用 factor_definitions.py 映射做 "
    "group key』；E2=`summary/report/sections.py` `_generate_ic_section` 内"
    "增加八维度汇总区块渲染（改）——出处 design.md:14，原文『_generate_ic_section "
    "内新增八维度汇总区块』；E3=`paths.py` 增加 `CATEGORY_SUMMARY_RESULT` 路径"
    "常量（增）——出处 design.md:16，原文『新增 CATEGORY_SUMMARY_RESULT 路径"
    "常量』。"
)

# vio4 要素原文未引用：要素只列 file→function+出处行号，未把 design.md 原文引用进正文
VIO4 = copy.deepcopy(BASE)
VIO4["a"][0] = (
    "①要素清单三条：E1=`summary/generate_factor_summary_report.py` "
    "`_aggregate_positive_ic` 增加 FACTOR_CATEGORIES 分组键（改，design.md:12）；"
    "E2=`summary/report/sections.py` `_generate_ic_section` 增加八维度汇总区块"
    "（改，design.md:14）；E3=`paths.py` 增加 `CATEGORY_SUMMARY_RESULT`（增，"
    "design.md:16）。"
)

CASES = {
    "clean": CLEAN,
    "vio1_要素无出处": VIO1,
    "vio2_静默新增二次创作": VIO2,
    "vio3_改写失真": VIO3,
    "vio4_要素原文未引用": VIO4,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {k: json.dumps(t, ensure_ascii=False) for k, t in CASES.items()}
    run_cases("plan:2#1 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
