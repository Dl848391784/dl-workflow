#!/usr/bin/env python3
"""plan:2#2 切分排序 gate 回归重放（v2.102 反转的回归资产，
designs/plan2-sub2-gate-framing-design.md）。

**plan:2（拆解任务与阶段）第二个反转节点**。命题性质=纵向切片+依赖排序+
阶段划分（从 step1 元素基线推导执行单元与拓扑序），主敌=「切分失序与替
用户拍板」--input=step1.element_baseline（S1 trace 在载荷内可见，判材边界
与 plan:2#1 不同：跨步要素覆盖可判，codegraph 真值不可判只判留痕）。

clean（承接 plan:2#1 元素基线 E1/E2/E3：U1=E3 paths.py 常量[基础无依赖] ->
U2=E1 统计函数加分组键[依赖 U1] -> U3=E2 渲染区块[依赖 U2]，纵向切片每单元
H9 预算+TDD failing test 先行，单阶段附②H9 论证+断点验证方法，要素全覆盖，
断点/粒度均「提案-待子5裁决」语义）/
vio1 横向按层切无显式辩护（单元按数据层/逻辑层/表现层切，无纵向切片推理
亦无横向切辩护）/
vio2 排序违反依赖（拓扑序写 U3->U2->U1，被依赖者排后，与 a1 声明依赖矛盾）/
vio3 单元超 H9 预算无继续拆（U2 估 4 文件 ~280 行，超 ≤3 文件 ≤200 行，
无继续拆表述）/
vio4 要素 ID 覆盖有漏=丢要素（只切 U2=E1/U3=E2，E3 无单元承接，a4 自称
「两要素全覆盖」）/
vio5 ②无论证=偷懒（a3 称「单阶段」却无 H9 内一次可完论证）/
vio6 替用户拍板断点（a3「断点设在 U2 后」+a4「已确定」，无「提案-待裁决」
语义）。

vio 载荷保真度（#30 ㊷）：单概念越界，其余维度保持合规--vio1 只换 a1 切分
叙述、a2/a3/a4 不动；vio2 只换 a2 拓扑序、a1 声明依赖不动（矛盾即信号）；
vio3 只换 a1 的 U2 H9 预算行；vio4 只删 U1 改 a1/a2/a4 一致丢 E3（排序仍
U2->U3 合规、H9/纵向切片不动）；vio5 只换 a3 阶段段去②论证；vio6 只换 a3
断点措辞+a4 确认句为拍板口吻。

artifact=子1+子2 最新 trace 拼合（生产 read_evidence_for_step(2,
"TaskBreakdown") 同形--本 gate 判据涉要素 ID 覆盖对照[跨步一致性，S1 在
载荷内可见]，前序 trace 是判材不是纯组成事实；codegraph 真值不可见=判据
钉「只判留痕在场不核 db」）。

用法: python3 tests/replays/replay_plan2_sub2.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "拆解任务与阶段 · 子步骤2"
STEP = sub_step("plan:2", 1)

# ---- 子1 trace（元素基线：E1/E2/E3+验收包+假设，压缩自 replay_plan2_sub1.py clean）----
S1_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "TaskBreakdown",
    "sub_step": 1,
    "skill": "Read(design.md / understand.md) / Bash(grep evidence 设计包 trace)",
    "purpose": (
        "设计包清点与追溯基线：三清单齐备（要素/验收包/假设）；每条附出处"
        "且要素原文引用进 trace 正文；新增候选/矛盾显式「无」；只提取不创作。"
    ),
    "q": [
        "①原子改动要素清单（file->function->改动类型，逐条赋 ID）如何？每条附出处与原文吗？",
        "②验收包清单（逐条 SuccessCriteria 附 ID）如何？",
        "③假设清单（置信度×影响，原样转录）如何？",
        "新增候选/设计包内部矛盾标注了吗？只提取不创作确认了吗？",
    ],
    "a": [
        "①要素清单三条：E1=`summary/generate_factor_summary_report.py` "
        "`_aggregate_positive_ic` 统计函数内增加 FACTOR_CATEGORIES 维度分组键"
        "（改）--出处 design.md:12，原文『在既有聚合统计函数内增加 "
        "FACTOR_CATEGORIES 维度分组键，复用 factor_definitions.py 映射做 group "
        "key』；E2=`summary/report/sections.py` `_generate_ic_section` 内增加"
        "八维度汇总区块渲染（改）--出处 design.md:14，原文『_generate_ic_section "
        "内新增八维度汇总区块』；E3=`paths.py` 增加 `CATEGORY_SUMMARY_RESULT` "
        "路径常量（增）--出处 design.md:16，原文『新增 CATEGORY_SUMMARY_RESULT "
        "路径常量』。",
        "②验收包三条：SC1.1『报告展示八维度条数+占比可读出』（design.md:20）；"
        "SC2.1『分组口径与 FACTOR_CATEGORIES 映射一致可核对』（design.md:21）；"
        "SC3.1『交付形态=报告新增八维度汇总区块』（design.md:22）。",
        "③假设一条：H1=FACTOR_CATEGORIES 八维度对全 34 项因子覆盖无遗漏"
        "（置信度中×影响中，原样转录 design.md:25）。",
        "新增候选：显式『无』--三要素均提取自 design.md；设计包内部矛盾：显式"
        "『无』；只提取不创作，未混入 design.md 之外的要素，q/a 按序对齐。",
    ],
}

# ---- 子2 clean：纵向切片 U1->U2->U3 + DAG 留痕 + TDD + 单阶段②论证 + 提案语义 ----
S2_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "TaskBreakdown",
    "sub_step": 2,
    "skill": "superpowers:writing-plans(粒度与切片原则) / codegraph callers/impact / 推理(拓扑排序)",
    "purpose": (
        "任务切分与依赖排序：执行单元切分（纵向切片优先，每单元自带完整测试"
        "周期且值得 reviewer 门禁）；每单元附 H9 预算+承接要素 ID+依赖出处；"
        "依赖 DAG 拓扑排序留痕（被依赖者先行，codegraph 取证）；TDD 序内嵌"
        "（每单元 failing test 先行）；阶段划分附断点验证方法或②单阶段不可拆"
        "论证；要素 ID 覆盖无漏；只提案不拍板（断点位置是用户风险偏好，子5 裁决）。"
    ),
    "q": [
        "执行单元切分如何（每单元 H9 预算+承接要素 ID+依赖出处）？纵向切片优先吗？",
        "依赖 DAG 拓扑排序留痕如何（被依赖者先行，codegraph 取证）？TDD 序内嵌如何？",
        "阶段划分与断点验证方法如何（或②单阶段不可拆论证）？",
        "要素 ID 覆盖核对？只提案不拍板确认了吗？",
    ],
    "a": [
        "执行单元切分（纵向切片优先，每单元自带完整测试周期且值得 reviewer "
        "门禁）：U1=`paths.py` 增加 `CATEGORY_SUMMARY_RESULT` 路径常量（承接 "
        "E3，改）--H9 预算 1 文件 ~5 行，无依赖（基础）；U2=`summary/"
        "generate_factor_summary_report.py` `_aggregate_positive_ic` 增加 "
        "FACTOR_CATEGORIES 分组键（承接 E1，改）--H9 预算 1 文件 ~30 行，依赖 "
        "U1（消费 CATEGORY_SUMMARY_RESULT 做分组输出路径）；U3=`summary/report/"
        "sections.py` `_generate_ic_section` 增加八维度汇总区块渲染（承接 E2，"
        "改）--H9 预算 1 文件 ~40 行，依赖 U2（消费聚合后的分组数据）。三单元"
        "均纵向切片，非横向按层切。",
        "依赖 DAG 拓扑排序留痕（被依赖者先行）：U1（无依赖，基础）-> U2"
        "（依赖 U1）-> U3（依赖 U2），拓扑序 U1->U2->U3。codegraph "
        "callers 取证：`codegraph callers _aggregate_positive_ic` 确认 U2 改动"
        "点被依赖方无遗漏；`codegraph impact CATEGORY_SUMMARY_RESULT` 确认 U1 "
        "新常量消费方。TDD 序内嵌：每单元 failing test 先行--U1 先写断言常量"
        "存在的失败测试，U2 先写断言分组输出结构的失败测试，U3 先写断言区块"
        "渲染的失败测试。",
        "阶段划分：单阶段（U1+U2+U3 同属一个纵向切片，可整体验证+整体提交+"
        "可回滚）。②单阶段不可拆论证：三单元合计 3 文件 ~75 行，H9 内（≤3 "
        "文件 ≤200 行）一次可完，无需拆多阶段。断点验证方法（提案）：阶段末"
        "跑 `python3 scripts/generate_factor_summary_report.py --read default` "
        "+ 断言报告含八维度汇总区块（待子5 用户裁决是否在此设断点）。",
        "要素 ID 覆盖核对：E1->U2、E2->U3、E3->U1，三要素全覆盖无漏。只提案"
        "不拍板：断点位置/阶段粒度均为提案，待子5 用户裁决（断点位置是用户"
        "风险偏好），q/a 按序对齐。",
    ],
}

S2_CLEAN = copy.deepcopy(S2_BASE)

# ---- vio1：横向按层切无显式辩护--单元按架构层切，无纵向切片推理亦无横向辩护 ----
S2_VIO1 = copy.deepcopy(S2_BASE)
S2_VIO1["a"][0] = (
    "执行单元切分：U1=数据层（`paths.py` 增加路径常量，承接 E3，改）--H9 预算 "
    "1 文件 ~5 行；U2=逻辑层（`summary/generate_factor_summary_report.py` "
    "`_aggregate_positive_ic` 增加分组键，承接 E1，改）--H9 预算 1 文件 ~30 行，"
    "依赖 U1；U3=表现层（`summary/report/sections.py` `_generate_ic_section` "
    "增加区块渲染，承接 E2，改）--H9 预算 1 文件 ~40 行，依赖 U2。三单元按"
    "架构层切分。"
)

# ---- vio2：排序违反依赖--拓扑序写 U3->U2->U1，被依赖者排后 ----
S2_VIO2 = copy.deepcopy(S2_BASE)
S2_VIO2["a"][1] = (
    "依赖 DAG 拓扑排序留痕：U3（依赖 U2）-> U2（依赖 U1）-> U1（无依赖），"
    "拓扑序 U3->U2->U1。codegraph callers 取证：`codegraph callers "
    "_aggregate_positive_ic` 确认 U2 改动点被依赖方无遗漏；`codegraph impact "
    "CATEGORY_SUMMARY_RESULT` 确认 U1 新常量消费方。TDD 序内嵌：每单元 failing "
    "test 先行--U3 先写断言区块渲染的失败测试，U2 先写断言分组输出结构的失败"
    "测试，U1 先写断言常量存在的失败测试。"
)

# ---- vio3：单元超 H9 预算无继续拆--U2 估 4 文件 ~280 行，超限不拆 ----
S2_VIO3 = copy.deepcopy(S2_BASE)
S2_VIO3["a"][0] = (
    "执行单元切分（纵向切片优先，每单元自带完整测试周期且值得 reviewer "
    "门禁）：U1=`paths.py` 增加 `CATEGORY_SUMMARY_RESULT` 路径常量（承接 "
    "E3，改）--H9 预算 1 文件 ~5 行，无依赖（基础）；U2=`summary/"
    "generate_factor_summary_report.py` `_aggregate_positive_ic` 增加 "
    "FACTOR_CATEGORIES 分组键 + 配套测试 + 数据适配层 + 配置项（承接 E1，改）"
    "--H9 预算 4 文件 ~280 行，依赖 U1（消费 CATEGORY_SUMMARY_RESULT 做分组"
    "输出路径）；U3=`summary/report/sections.py` `_generate_ic_section` 增加"
    "八维度汇总区块渲染（承接 E2，改）--H9 预算 1 文件 ~40 行，依赖 U2（消费"
    "聚合后的分组数据）。三单元均纵向切片，非横向按层切。"
)

# ---- vio4：要素 ID 覆盖有漏=丢要素--只切 U2=E1/U3=E2，E3 无单元承接 ----
S2_VIO4 = copy.deepcopy(S2_BASE)
S2_VIO4["a"][0] = (
    "执行单元切分（纵向切片优先，每单元自带完整测试周期且值得 reviewer "
    "门禁）：U2=`summary/generate_factor_summary_report.py` "
    "`_aggregate_positive_ic` 增加 FACTOR_CATEGORIES 分组键（承接 E1，改）--"
    "H9 预算 1 文件 ~30 行，无依赖；U3=`summary/report/sections.py` "
    "`_generate_ic_section` 增加八维度汇总区块渲染（承接 E2，改）--H9 预算 "
    "1 文件 ~40 行，依赖 U2（消费聚合后的分组数据）。两单元均纵向切片，非"
    "横向按层切。"
)
S2_VIO4["a"][1] = (
    "依赖 DAG 拓扑排序留痕（被依赖者先行）：U2（无依赖，基础）-> U3"
    "（依赖 U2），拓扑序 U2->U3。codegraph callers 取证：`codegraph callers "
    "_aggregate_positive_ic` 确认 U2 改动点被依赖方无遗漏。TDD 序内嵌：每"
    "单元 failing test 先行--U2 先写断言分组输出结构的失败测试，U3 先写断言"
    "区块渲染的失败测试。"
)
S2_VIO4["a"][3] = (
    "要素 ID 覆盖核对：E1->U2、E2->U3，两要素全覆盖无漏。只提案不拍板："
    "断点位置/阶段粒度均为提案，待子5 用户裁决（断点位置是用户风险偏好），"
    "q/a 按序对齐。"
)

# ---- vio5：②无论证=偷懒--a3 称「单阶段」却无 H9 内一次可完论证 ----
S2_VIO5 = copy.deepcopy(S2_BASE)
S2_VIO5["a"][2] = (
    "阶段划分：单阶段（U1+U2+U3 同属一个纵向切片，可整体验证+整体提交+"
    "可回滚）。断点验证方法（提案）：阶段末跑 `python3 scripts/"
    "generate_factor_summary_report.py --read default` + 断言报告含八维度汇总"
    "区块（待子5 用户裁决是否在此设断点）。"
)

# ---- vio6：替用户拍板断点--a3「断点设在 U2 后」+a4「已确定」，无提案语义 ----
S2_VIO6 = copy.deepcopy(S2_BASE)
S2_VIO6["a"][2] = (
    "阶段划分：两阶段--阶段一=U1+U2（可独立验证：跑 U2 分组输出断言分组结构），"
    "阶段二=U3（渲染区块）。断点设在 U2 后：阶段一交付分组数据、阶段二交付"
    "报告区块，两阶段各自可整体提交+可回滚。断点验证方法：阶段一末跑 U2 "
    "断言分组结构、阶段二末跑 `python3 scripts/generate_factor_summary_report."
    "py --read default` + 断言报告含八维度汇总区块。"
)
S2_VIO6["a"][3] = (
    "要素 ID 覆盖核对：E1->U2、E2->U3、E3->U1，三要素全覆盖无漏。断点位置"
    "已确定在 U2 后，阶段粒度已定两阶段，q/a 按序对齐。"
)

CASES = {
    "clean": S2_CLEAN,
    "vio1_横向按层切无辩护": S2_VIO1,
    "vio2_排序违反依赖": S2_VIO2,
    "vio3_超H9预算无继续拆": S2_VIO3,
    "vio4_丢要素E3": S2_VIO4,
    "vio5_单阶段无论证": S2_VIO5,
    "vio6_替用户拍板断点": S2_VIO6,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {
        k: "\n".join(json.dumps(t, ensure_ascii=False) for t in (S1_BASE, s2))
        for k, s2 in CASES.items()
    }
    run_cases("plan:2#2 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
