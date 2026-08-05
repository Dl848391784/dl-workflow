#!/usr/bin/env python3
"""plan:4#1 四源清点 gate 回归重放（v2.115 反转的回归资产，
designs/plan4-sub1-gate-framing-design.md）。

**plan:4（制定执行计划和检查点）首个反转节点**（泛化第三十二例）。命题性质=
保真转换（从 design.md + plan.md + understand.md + evidence 四源提取控制结构输入
五类清单到 control_baseline），主敌=「四源聚合失真与虚构/静默新增/漏源」--与
plan:2#1/plan:3#1 同构（同「从有到有时的失真与虚构」清点基线族），只是输入锚
从单/双源扩为四源聚合（首个四源聚合节点，execution-plan-checkpoints-substeps-
design §1.2 关键不对称第八种）。

判材边界（㊚② 跨阶段文件输入，绝对不可见）：
- design.md/plan.md/understand.md 主仓 .md 文件 + evidence plan:1/2/3 前序 trace
  judge 结构性读不到（evidence 只含 ExecutionPlanCheckpoints 段）-> 五类清单真伪/
  出处真实性/是否真在四源 = 存在性真值判不了；
- 判面重划=trace 内自洽+留痕形式（与 plan:2#1/plan:3#1 同范式：判据一(b) 静默新增
  改判 trace 内矛盾「新增候选：无」声明 vs 清单含新增措辞条目）；
- 「原文引用」合法形态=任一 q/a 答案中以『』引用四源原文片段即合规。

clean（四源五类清单齐备：①任务 DAG[plan.md T1->T2->T3 各附出处+原文『』+阶段分组]
②能力绑定[plan.md factor-development『原文』] ③验收包
[understand.md SC1.1/SC2.1 各附出处+原文『』+triggered 落点] ④假设汇总
[design.md H1『原文』+「其余假设无」声明] ⑤不可逆操作候选[plan.md git push『原文』
外发]；新增候选：显式『无』；只提取不创作）/
vio1 清单项无出处=编造（五类清单全裸，「按四源常规结构可知」凭印象，无任何
出处/原文引用）/
vio2 静默新增=二次创作（①②③④正常有出处+原文，⑤=「删除旧报告目录」裸无出处
无原文，a[1] 仍声明「新增候选：无」）/
vio3 改写失真=聚合失真（① T1 引 plan.md 原文『增加 FACTOR_CATEGORIES 分组键』却
自述成「重写 _aggregate_positive_ic 为独立分组引擎」--引文 vs 自述措辞冲突）/
vio4 原文未引用（五类清单只列条目+出处行号，无任何『』原文引用--judge 无从
核对保真度）/
vio5 漏源（五类清单缺③验收包整类，understand.md 在清单中无任何条目且无说明=
四源之一缺失漏源）。

vio 载荷保真度（#30 ㊷）：单概念越界，其余维度保持合规--vio1 只去 a[0] 的
出处/原文、其余不动；vio2 只换 a[0] 的⑤+a[1] 维持「新增候选：无」；vio3 只换
a[0] 的①T1 自述措辞；vio4 只去 a[0] 的『』引用；vio5 只删 a[0] 的③验收包整段。

artifact=子1 单条 trace（生产 read_evidence_for_step(1,"ExecutionPlanCheckpoints")
同形--本节点首步，minor_stage 过滤后无前序拼合；input=design.md/plan.md/
understand.md 主仓 .md 文件 + plan:1/2/3 前序 trace 均不在载荷内，四重不可见
与 plan:2#1/plan:3#1 同构）。

用法: python3 tests/replays/replay_plan4_sub1.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "制定执行计划和检查点 · 子步骤1"
STEP = sub_step("plan:4", 0)

# ---- 子1 clean：四源五类清单齐备 + 每条出处+原文 + 新增候选「无」----
S1_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "ExecutionPlanCheckpoints",
    "sub_step": 1,
    "skill": "Read(design.md / plan.md / understand.md) / Bash(grep evidence plan:1/2/3 trace)",
    "purpose": (
        "四源清点与追溯基线：控制结构输入五类清单齐备（①任务 DAG 与阶段边界/"
        "②能力绑定/③验收包/④假设清单汇总/⑤不可逆操作候选）；每条附源出处且"
        "四源原文引用进 trace 正文；新增候选（四源没有的对象）显式标注或显式"
        "「无」；只提取不创作（本步是全节点保真判定基线）。检出四源没有的对象"
        "=二次创作信号，显式列「新增候选」待子5 用户裁决（禁静默混入）。"
    ),
    "q": [
        "控制结构输入五类清单如何（任务 DAG/能力绑定/验收包/假设汇总/不可逆"
        "操作候选，每条附源出处且四源原文引用进 trace 正文）？",
        "新增候选（四源没有的对象）显式标注了吗？",
        "只提取不创作确认了吗（无静默新增）？",
    ],
    "a": [
        "控制结构输入五类清单齐备：①任务 DAG 与阶段边界（plan.md 执行步骤节）："
        "T1=U2 代码改动（`summary/generate_factor_summary_report.py` "
        "`_aggregate_positive_ic` 内增加 FACTOR_CATEGORIES 分组键，改 .py=H15 "
        "触发信号）--出处 plan.md:12，原文『U2: 在既有聚合统计函数内增加 "
        "FACTOR_CATEGORIES 维度分组键』；T2=U1 代码改动（`paths.py` 增加 "
        "CATEGORY_SUMMARY_RESULT 路径常量，依赖 T1）--出处 plan.md:11，原文"
        "『U1: 新增 CATEGORY_SUMMARY_RESULT 路径常量』；T3=报告断点验证--"
        "出处 plan.md:14，原文『断点验证：断言报告含八维度汇总区块』；阶段"
        "分组=实现阶段[T1,T2]+验证阶段[T3]；②能力绑定（plan.md 能力节）：T1/T2 "
        "代码改动->factor-development；T3 验证->内置工具足够--"
        "出处 plan.md:18，原文『必先 skill: factor-development（开发因子触发）』；"
        "③验收包（understand.md 六字段）：SC1.1=八维度汇总区块存在性（triggered "
        "项，落点=T3 断点验证）--出处 understand.md:22，原文『SC1.1: 报告含八"
        "维度汇总区块』；SC2.1=分组键覆盖全 34 因子（triggered 项，落点=T1 后"
        "核验）--出处 understand.md:22，原文『SC2.1: 分组键覆盖全部 34 项"
        "因子』；④假设清单汇总（design.md + plan.md + evidence plan:1 trace）："
        "H1=FACTOR_CATEGORIES 八维度对全 34 因子覆盖无遗漏（置信度中×影响中）"
        "--出处 design.md:25，原文『假设 H1: FACTOR_CATEGORIES 维度划分覆盖"
        "全部 34 项因子』；其余假设：plan.md/evidence plan:1 trace 无新增假设"
        "（显式『无』）；⑤不可逆操作候选（执行步骤含删改/外发/force 语义）："
        "T2 后 `git push` 推送主仓（外发）--出处 plan.md:15，原文『T2 完成后 "
        "git push 推送远端』。",
        "新增候选（四源没有的对象）：显式『无』--五类清单均提取自四源"
        "（design.md/plan.md/understand.md/evidence plan:1/2/3 trace），无超出"
        "四源的新增对象。",
        "只提取不创作确认：五类清单逐类与四源一一对应（①任务 DAG/②能力绑定/"
        "③验收包/④假设汇总/⑤不可逆操作候选均提取自四源原文，未混入四源之外"
        "的对象：无独立脚本新建、无外部 API 依赖新增、无任何四源未载的新增操作），"
        "新增候选=显式『无』，q/a 按序对齐。",
    ],
}

S1_CLEAN = copy.deepcopy(S1_BASE)

# ---- vio1：清单项无出处=编造--五类全裸，凭印象无出处/原文（不提具体 .py 文件名，mech 不触发）----
S1_VIO1 = copy.deepcopy(S1_BASE)
S1_VIO1["a"][0] = (
    "控制结构输入五类清单齐备：①任务 DAG 与阶段边界：T1 代码改动（聚合统计函数"
    "加分组键，改 .py=H15 信号）-> T2 代码改动（加路径常量，依赖 T1）-> T3 报告"
    "断点验证；②能力绑定：代码改动加载开发因子 skill + codegraph 留痕；③验收包："
    "汇总区块存在性 + 分组键覆盖；④假设汇总：维度覆盖无遗漏；⑤不可逆操作：推送"
    "远端。五类按四源常规结构可知，应该都在执行步骤节和能力节里，按常规路径可查。"
)

# ---- vio2：静默新增=二次创作--①②③④正常有出处+原文，⑤裸无出处无原文，a[1] 仍声明「新增候选：无」----
S1_VIO2 = copy.deepcopy(S1_BASE)
S1_VIO2["a"][0] = (
    "控制结构输入五类清单齐备：①任务 DAG 与阶段边界（plan.md 执行步骤节）："
    "T1=U2 代码改动（`summary/generate_factor_summary_report.py` "
    "`_aggregate_positive_ic` 内增加 FACTOR_CATEGORIES 分组键，改 .py=H15 "
    "触发信号）--出处 plan.md:12，原文『U2: 在既有聚合统计函数内增加 "
    "FACTOR_CATEGORIES 维度分组键』；T2=U1 代码改动（`paths.py` 增加 "
    "CATEGORY_SUMMARY_RESULT 路径常量，依赖 T1）--出处 plan.md:11，原文"
    "『U1: 新增 CATEGORY_SUMMARY_RESULT 路径常量』；T3=报告断点验证--"
    "出处 plan.md:14，原文『断点验证：断言报告含八维度汇总区块』；阶段"
    "分组=实现阶段[T1,T2]+验证阶段[T3]；②能力绑定（plan.md 能力节）：T1/T2 "
    "代码改动->factor-development；T3 验证->内置工具足够--"
    "出处 plan.md:18，原文『必先 skill: factor-development（开发因子触发）』；"
    "③验收包（understand.md 六字段）：SC1.1=八维度汇总区块存在性（triggered "
    "项，落点=T3 断点验证）--出处 understand.md:22，原文『SC1.1: 报告含八"
    "维度汇总区块』；SC2.1=分组键覆盖全 34 因子（triggered 项，落点=T1 后"
    "核验）--出处 understand.md:22，原文『SC2.1: 分组键覆盖全部 34 项"
    "因子』；④假设清单汇总（design.md + plan.md）：H1=FACTOR_CATEGORIES "
    "八维度对全 34 因子覆盖无遗漏（置信度中×影响中）--出处 design.md:25，"
    "原文『假设 H1: FACTOR_CATEGORIES 维度划分覆盖全部 34 项因子』；其余假设："
    "plan.md 无新增假设（显式『无』）；⑤不可逆操作候选：删除旧报告目录 "
    "`rm -rf IC_REPORT_DIR/default` 清理历史产物（force 删除）。"
)

# ---- vio3：改写失真=聚合失真--① T1 引原文『增加分组键』却自述成「重写为独立分组引擎」----
S1_VIO3 = copy.deepcopy(S1_BASE)
S1_VIO3["a"][0] = (
    "控制结构输入五类清单齐备：①任务 DAG 与阶段边界（plan.md 执行步骤节）："
    "T1=U2 代码改动（重写 `summary/generate_factor_summary_report.py` "
    "`_aggregate_positive_ic` 为独立分组引擎，改 .py=H15 触发信号）--出处 "
    "plan.md:12，原文『U2: 在既有聚合统计函数内增加 FACTOR_CATEGORIES 维度"
    "分组键』；T2=U1 代码改动（`paths.py` 增加 CATEGORY_SUMMARY_RESULT 路径"
    "常量，依赖 T1）--出处 plan.md:11，原文『U1: 新增 CATEGORY_SUMMARY_RESULT "
    "路径常量』；T3=报告断点验证--出处 plan.md:14，原文『断点验证：断言报告"
    "含八维度汇总区块』；阶段分组=实现阶段[T1,T2]+验证阶段[T3]；②能力绑定"
    "（plan.md 能力节）：T1/T2 代码改动->factor-development；T3 验证"
    "->内置工具足够--出处 plan.md:18，原文『必先 skill: factor-development"
    "（开发因子触发）』；③验收包（understand.md 六字段）：SC1.1=八维度汇总"
    "区块存在性（triggered 项，落点=T3 断点验证）--出处 understand.md:22，"
    "原文『SC1.1: 报告含八维度汇总区块』；SC2.1=分组键覆盖全 34 因子"
    "（triggered 项，落点=T1 后核验）--出处 understand.md:22，原文『SC2.1: "
    "分组键覆盖全部 34 项因子』；④假设清单汇总（design.md + plan.md）："
    "H1=FACTOR_CATEGORIES 八维度对全 34 因子覆盖无遗漏（置信度中×影响中）"
    "--出处 design.md:25，原文『假设 H1: FACTOR_CATEGORIES 维度划分覆盖全部 "
    "34 项因子』；其余假设：plan.md 无新增假设（显式『无』）；⑤不可逆操作"
    "候选（执行步骤含删改/外发/force 语义）：T2 后 `git push` 推送主仓（外发）"
    "--出处 plan.md:15，原文『T2 完成后 git push 推送远端』。"
)

# ---- vio4：原文未引用--只列条目+出处行号，无任何『』原文引用（含具体 .py 文件名=mech 触发面）----
S1_VIO4 = copy.deepcopy(S1_BASE)
S1_VIO4["a"][0] = (
    "控制结构输入五类清单齐备：①任务 DAG 与阶段边界（plan.md 执行步骤节）："
    "T1=U2 代码改动（`summary/generate_factor_summary_report.py` "
    "`_aggregate_positive_ic` 内增加 FACTOR_CATEGORIES 分组键，改 .py=H15 "
    "触发信号）--出处 plan.md:12；T2=U1 代码改动（`paths.py` 增加 "
    "CATEGORY_SUMMARY_RESULT 路径常量，依赖 T1）--出处 plan.md:11；T3=报告"
    "断点验证--出处 plan.md:14；阶段分组=实现阶段[T1,T2]+验证阶段[T3]；"
    "②能力绑定（plan.md 能力节）：T1/T2 代码改动->factor-development；"
    "T3 验证->内置工具"
    "足够--出处 plan.md:18；③验收包（understand.md 六字段）：SC1.1=八维度"
    "汇总区块存在性（triggered 项，落点=T3 断点验证）--出处 understand.md:22；"
    "SC2.1=分组键覆盖全 34 因子（triggered 项，落点=T1 后核验）--出处 "
    "understand.md:22；④假设清单汇总（design.md + plan.md）：H1=FACTOR_"
    "CATEGORIES 八维度对全 34 因子覆盖无遗漏（置信度中×影响中）--出处 "
    "design.md:25；其余假设：plan.md 无新增假设；⑤不可逆操作候选（执行步骤"
    "含删改/外发/force 语义）：T2 后 `git push` 推送主仓（外发）--出处 "
    "plan.md:15。"
)

# ---- vio5：漏源--五类清单缺③验收包整类，understand.md 在清单中无任何条目且无说明 ----
S1_VIO5 = copy.deepcopy(S1_BASE)
S1_VIO5["a"][0] = (
    "控制结构输入五类清单齐备：①任务 DAG 与阶段边界（plan.md 执行步骤节）："
    "T1=U2 代码改动（`summary/generate_factor_summary_report.py` "
    "`_aggregate_positive_ic` 内增加 FACTOR_CATEGORIES 分组键，改 .py=H15 "
    "触发信号）--出处 plan.md:12，原文『U2: 在既有聚合统计函数内增加 "
    "FACTOR_CATEGORIES 维度分组键』；T2=U1 代码改动（`paths.py` 增加 "
    "CATEGORY_SUMMARY_RESULT 路径常量，依赖 T1）--出处 plan.md:11，原文"
    "『U1: 新增 CATEGORY_SUMMARY_RESULT 路径常量』；T3=报告断点验证--"
    "出处 plan.md:14，原文『断点验证：断言报告含八维度汇总区块』；阶段"
    "分组=实现阶段[T1,T2]+验证阶段[T3]；②能力绑定（plan.md 能力节）：T1/T2 "
    "代码改动->factor-development；T3 验证->内置工具足够--"
    "出处 plan.md:18，原文『必先 skill: factor-development（开发因子触发）』；"
    "④假设清单汇总（design.md + plan.md）：H1=FACTOR_CATEGORIES 八维度对全 "
    "34 因子覆盖无遗漏（置信度中×影响中）--出处 design.md:25，原文『假设 H1: "
    "FACTOR_CATEGORIES 维度划分覆盖全部 34 项因子』；其余假设：plan.md 无新增"
    "假设（显式『无』）；⑤不可逆操作候选（执行步骤含删改/外发/force 语义）："
    "T2 后 `git push` 推送主仓（外发）--出处 plan.md:15，原文『T2 完成后 "
    "git push 推送远端』。"
)

CASES = {
    "clean": S1_CLEAN,
    "vio1_清单无出处编造": S1_VIO1,
    "vio2_静默新增二次创作": S1_VIO2,
    "vio3_改写失真聚合失真": S1_VIO3,
    "vio4_原文未引用": S1_VIO4,
    "vio5_漏源缺验收包": S1_VIO5,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {k: json.dumps(t, ensure_ascii=False) for k, t in CASES.items()}
    run_cases("plan:4#1 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
