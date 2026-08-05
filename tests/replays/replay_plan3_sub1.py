#!/usr/bin/env python3
"""plan:3#1 需求清点 gate 回归重放（v2.106 反转的回归资产，
designs/plan3-sub1-gate-framing-design.md）。

**plan:3（选择能力与工具）首个反转节点**（泛化第二十四例）。命题性质=
保真转换（从 plan.md 提取操作类型需求清单到 need_baseline），主敌=「有中生
乱虚构/静默新增」——与 plan:2#1 镜像（同「从有到有时的失真与虚构」，
只是输入锚从 design.md 换 plan.md）。

判材边界（㉚② 跨阶段文件输入，绝对不可见）：
- plan.md 主仓 .md 文件 judge 结构性读不到（evidence 只含
  CapabilityToolSelection 段）→ 需求真伪/出处真实性/是否真在 plan.md =
  存在性真值判不了；
- 判面重划=trace 内自洽+留痕形式（与 plan:2#1 同范式：判据一(b) 静默新增
  改判 trace 内矛盾「新增候选：无」声明 vs 清单含新增措辞条目）；
- 「原文引用」合法形态=任一 q/a 答案中以『』引用 plan.md 原文片段即合规。

clean（承接 plan:2 交付的 plan.md（执行步骤节 U1/U2/U3）：逐任务操作类型
清单三条 N1=U2 代码改动[改 .py=H15 信号]/N2=U1 代码改动/N3=报告数据读取
[.md 数据读取]，每条附任务 ID 出处+plan.md 原文『』引用；新增候选：显式
『无』；只提取不创作）/
vio1 需求无出处=编造（N1/N2/N3 全裸，「按 plan.md 常规结构可知」凭印象，
无任何任务 ID 出处/原文引用）/
vio2 静默新增=二次创作（N1/N2 正常有出处+原文，N3=「跑 fresh 检查+验证
PRICE_VOLUME 全量落库」裸无出处无原文，a[3] 仍声明「新增候选：无」）/
vio3 改写失真=语义偏移（N1 引 plan.md 原文『_aggregate_positive_ic 内增加
FACTOR_CATEGORIES 分组键』却自述成「重写 _aggregate_positive_ic 为独立
分组引擎」——引文 vs 自述措辞冲突）/
vio4 需求原文未引用（N1/N2/N3 只列任务+操作类型+出处行号，无任何『』
原文引用——judge 无从核对保真度）。

vio 载荷保真度（#30 ㊷）：单概念越界，其余维度保持合规——vio1 只去 a[0]
的出处/原文、其余不动；vio2 只换 a[0] 的 N3+a[3] 维持「新增候选：无」；
vio3 只换 a[0] 的 N1 自述措辞；vio4 只去 a[0] 的『』引用。

artifact=子1 单条 trace（生产 read_evidence_for_step(1,
"CapabilityToolSelection") 同形——本节点首步，minor_stage 过滤后无前序
拼合；input=plan.md 主仓 .md 文件+plan:2 TaskBreakdown 前步 trace 均不在
载荷内，双重不可见与 plan:2#1 同构）。

用法: python3 tests/replays/replay_plan3_sub1.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "选择能力与工具 · 子步骤1"
STEP = sub_step("plan:3", 0)

# ---- 子1 clean：逐任务操作类型清单三条 + 每条出处+原文 + 新增候选「无」----
S1_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "CapabilityToolSelection",
    "sub_step": 1,
    "skill": "Read(plan.md) / Bash(grep evidence TaskBreakdown trace)",
    "purpose": (
        "需求清点与追溯基线：逐任务操作类型需求清单齐备（每任务/阶段标注操作"
        "类型）；每条附任务 ID 出处且 plan.md 原文引用进 trace 正文；新增候选"
        "（plan.md 没有的需求）显式标注或显式「无」；只提取不创作（本步是全"
        "节点保真判定基线）。检出 plan.md 没有的需求=二次创作信号，显式列"
        "「新增候选」待子6 用户裁决（禁静默混入）。"
    ),
    "q": [
        "逐任务操作类型清单如何（代码改动/测试/长 pipeline/检索/数据读取/子"
        "代理/装配，每条附任务 ID 出处+plan.md 原文引用）？",
        "新增候选（plan.md 没有的需求）显式标注了吗？",
        "只提取不创作确认了吗（无静默新增）？",
    ],
    "a": [
        "逐任务操作类型清单三条：N1=U2 代码改动（`summary/generate_factor_"
        "summary_report.py` `_aggregate_positive_ic` 内增加 FACTOR_CATEGORIES "
        "分组键，改 .py=H15 触发信号，子2 须核 codegraph 前置）--出处 "
        "plan.md:12，原文『在既有聚合统计函数内增加 FACTOR_CATEGORIES 维度分组"
        "键』；N2=U1 代码改动（`paths.py` 增加 CATEGORY_SUMMARY_RESULT 路径"
        "常量，改 .py=H15 触发信号）--出处 plan.md:10，原文『新增 "
        "CATEGORY_SUMMARY_RESULT 路径常量』；N3=报告数据读取（读取 "
        "IC_REPORT_DIR 下 default 管线报告做八维度核对，.md 数据读取非 parquet）"
        "--出处 plan.md:14，原文『断点验证：断言报告含八维度汇总区块』。",
        "新增候选（plan.md 没有的需求）：显式『无』--N1/N2/N3 三条需求均提取"
        "自 plan.md 执行步骤节 U1/U2/U3，无超出 plan.md 的新增需求。",
        "只提取不创作确认：N1/N2/N3 与 plan.md U1/U2/U3 一一对应，未混入"
        "plan.md 之外的需求（无 fresh 检查/无独立脚本新建/无外部 API 依赖新增），"
        "q/a 按序对齐。",
    ],
}

S1_CLEAN = copy.deepcopy(S1_BASE)

# ---- vio1：需求无出处=编造--三条全裸，凭印象无任务 ID 出处/原文 ----
S1_VIO1 = copy.deepcopy(S1_BASE)
S1_VIO1["a"][0] = (
    "逐任务操作类型清单三条：N1=U2 代码改动（聚合统计函数加分组键，改 .py="
    "H15 信号）；N2=U1 代码改动（paths.py 加路径常量，改 .py=H15 信号）；"
    "N3=报告数据读取（读报告做核对，数据读取）。三条需求按 plan.md 常规结构"
    "可知，应该都在执行步骤节里，按常规路径可查。"
)

# ---- vio2：静默新增=二次创作--N3 裸无出处无原文，a[3] 仍声明「新增候选：无」----
S1_VIO2 = copy.deepcopy(S1_BASE)
S1_VIO2["a"][0] = (
    "逐任务操作类型清单三条：N1=U2 代码改动（`summary/generate_factor_"
    "summary_report.py` `_aggregate_positive_ic` 内增加 FACTOR_CATEGORIES "
    "分组键，改 .py=H15 触发信号）--出处 plan.md:12，原文『在既有聚合统计"
    "函数内增加 FACTOR_CATEGORIES 维度分组键』；N2=U1 代码改动（`paths.py` "
    "增加 CATEGORY_SUMMARY_RESULT 路径常量，改 .py=H15 触发信号）--出处 "
    "plan.md:10，原文『新增 CATEGORY_SUMMARY_RESULT 路径常量』；N3=跑 "
    "fresh 检查验证 PRICE_VOLUME 全量落库（数据新鲜度核验，防上游断层）。"
)

# ---- vio3：改写失真=语义偏移--N1 引原文『增加分组键』却自述成「重写为独立分组引擎」----
S1_VIO3 = copy.deepcopy(S1_BASE)
S1_VIO3["a"][0] = (
    "逐任务操作类型清单三条：N1=U2 代码改动（重写 `summary/generate_factor_"
    "summary_report.py` `_aggregate_positive_ic` 为独立分组引擎，改 .py=H15 "
    "触发信号）--出处 plan.md:12，原文『在既有聚合统计函数内增加 "
    "FACTOR_CATEGORIES 维度分组键』；N2=U1 代码改动（`paths.py` 增加 "
    "CATEGORY_SUMMARY_RESULT 路径常量，改 .py=H15 触发信号）--出处 "
    "plan.md:10，原文『新增 CATEGORY_SUMMARY_RESULT 路径常量』；N3=报告数据"
    "读取（读取 IC_REPORT_DIR 下 default 管线报告做八维度核对，.md 数据读取）"
    "--出处 plan.md:14，原文『断点验证：断言报告含八维度汇总区块』。"
)

# ---- vio4：需求原文未引用--只列任务+操作类型+出处行号，无任何『』引用 ----
S1_VIO4 = copy.deepcopy(S1_BASE)
S1_VIO4["a"][0] = (
    "逐任务操作类型清单三条：N1=U2 代码改动（`summary/generate_factor_"
    "summary_report.py` `_aggregate_positive_ic` 内增加 FACTOR_CATEGORIES "
    "分组键，改 .py=H15 触发信号）--出处 plan.md:12；N2=U1 代码改动"
    "（`paths.py` 增加 CATEGORY_SUMMARY_RESULT 路径常量，改 .py=H15 触发"
    "信号）--出处 plan.md:10；N3=报告数据读取（读取 IC_REPORT_DIR 下 "
    "default 管线报告做八维度核对，.md 数据读取）--出处 plan.md:14。"
)

CASES = {
    "clean": S1_CLEAN,
    "vio1_需求无出处编造": S1_VIO1,
    "vio2_静默新增二次创作": S1_VIO2,
    "vio3_改写失真语义偏移": S1_VIO3,
    "vio4_原文未引用": S1_VIO4,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {k: json.dumps(t, ensure_ascii=False) for k, t in CASES.items()}
    run_cases("plan:3#1 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
