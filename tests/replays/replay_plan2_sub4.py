#!/usr/bin/env python3
"""plan:2#4 归一化步骤 gate 回归重放（反转的回归资产，
designs/plan2-sub4-gate-framing-design.md）。

**plan:2（拆解任务与阶段）第四个反转节点**（前三=plan:2#1/#2 已入库 + plan:2#3
并行在飞）。命题性质=执行步骤归一化（从 step2 任务单元+step3 锚点核验推导
statements 五字段执行包），主敌=「长链转换失真与未原子化」--input=step3.
verified_units + step1.element_baseline（子1/子2/子3 trace 载荷内可见，
read_evidence_for_step(4,"TaskBreakdown") 拼合，判材边界与 plan:2#1 不同：
跨步字段一致性+验收包映射均可判，design.md 跨阶段文件结构性读不到但子1
已提取为载荷内验收包清单）。

record_format=statements -> 原 mech_checks 循环不执行（#30 ⑰）；v2.109 落地
statements 侧首个 mech sc_coverage_trace（u:2#4 预留独立项的解），承接跨步判据
「验收包映射漏项」（子1 验收包 SC ID vs 子4 acceptance_map 差集）--该判据
default-PASS 下 judge 措辞判不稳且与 clean 误伤跷跷板（⑤ 实锤：v4-v8 迭代
vio4 在 2-6/6 摆、clean 因「双向覆盖」措辞被发明映射归属要件误伤），下沉生产墙。

读数口径（#30 ⑦）：clean/vio1/vio2/vio3 走 judge（期望 clean 全 PASS + vio1-3
≥5/6 BLOCK）；**vio4 验收包映射漏项=mech 生产墙托**（设计内委托，同 plan:2#2
vio4/vio5 范式）--judge 被告知「已由 sc_coverage_trace 机械校验」故放行
（judge 读数 0-1/6 是设计内、非回归），覆盖漏项由 mech 单元测试
test_p2s4_sc_coverage_trace_block_pass_skip 零方差证拒。别把 vio4 judge 读数当回归。

clean（承接 plan:2#2 U1/U2/U3 纵向切片 + plan:2#3 锚点核验：三 statements
各带五字段 change_point/interface/verify/acceptance_map/trace_anchor，忠实
提取子2 单元定义+子3 验证命令，验收包 SC1.1/SC2.1/SC3.1 全映射，要素
E1/E2/E3 全承接，假设 H1 原样携带）/
vio1 字段篡改（U2 change_point 由子2「增加分组键」篡改为「重写为独立八维度
聚合器，输出全新数据结构」，与子2 单元定义语义冲突）/
vio2 复合句（U2 text「增加 FACTOR_CATEGORIES 分组键，以及新增独立的分组
校验脚本」--以及连接两个可独立提交的交付物）/
vio3 验证方法不可执行且无辩护（U3 verify「人工看一下报告里八维度区块对不对」
不可执行无辩护）/
vio4 验收包映射漏项（SC1.1/SC2.1/SC3.1 全无承接--三项 acceptance_map 均「无直接验收包
承接」，子1 验收包清单三 SC ID 全未在子4 出现）。

vio 载荷保真度（#30 ㊷）：单概念越界，其余维度保持合规--vio1 只换 U2 的
change_point 字段（text/interface/verify 不动，其余项不动）；vio2 只换 U2
的 text（五字段不动）；vio3 只换 U3 的 verify 字段；vio4 只换 U1/U3 的
acceptance_map 去掉 SC3.1（U2 的 SC1.1/SC2.1 不动）。

artifact=子1+子2+子3+子4 最新 trace 拼合（生产 read_evidence_for_step(4,
"TaskBreakdown") 同形--本 gate 判据涉字段一致性对照[子2 单元定义/子3 验证
命令]+验收包映射对照[子1 验收包清单]，前序 trace 是判材非纯组成事实）。

用法: python3 tests/replays/replay_plan2_sub4.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "拆解任务与阶段 · 子步骤4"
STEP = sub_step("plan:2", 3)

# ---- 子1 trace（元素基线：E1/E2/E3+验收包 SC1.1/SC2.1/SC3.1+假设 H1，压缩自 replay_plan2_sub1.py clean）----
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

# ---- 子2 trace（切分排序 clean：U1->U2->U3 纵向切片+DAG+TDD+单阶段②论证+提案语义，压缩自 replay_plan2_sub2.py clean）----
S2_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "TaskBreakdown",
    "sub_step": 2,
    "skill": "superpowers:writing-plans(粒度与切片原则) / codegraph callers/impact / 推理(拓扑排序)",
    "purpose": (
        "任务切分与依赖排序：执行单元切分（纵向切片优先）；每单元附 H9 预算+"
        "承接要素 ID+依赖出处；依赖 DAG 拓扑排序留痕（被依赖者先行）；TDD 序"
        "内嵌；阶段划分附断点验证方法或②单阶段不可拆论证；要素 ID 覆盖无漏；"
        "只提案不拍板。"
    ),
    "q": [
        "执行单元切分如何（每单元 H9 预算+承接要素 ID+依赖出处）？纵向切片优先吗？",
        "依赖 DAG 拓扑排序留痕如何？TDD 序内嵌如何？",
        "阶段划分与断点验证方法如何？",
        "要素 ID 覆盖核对？只提案不拍板确认了吗？",
    ],
    "a": [
        "执行单元切分（纵向切片优先）：U1=`paths.py` 增加 "
        "`CATEGORY_SUMMARY_RESULT` 路径常量（承接 E3，改）--H9 预算 1 文件 "
        "~5 行，无依赖（基础）；U2=`summary/generate_factor_summary_report.py` "
        "`_aggregate_positive_ic` 增加 FACTOR_CATEGORIES 分组键（承接 E1，改）"
        "--H9 预算 1 文件 ~30 行，依赖 U1（消费 CATEGORY_SUMMARY_RESULT 做分组"
        "输出路径）；U3=`summary/report/sections.py` `_generate_ic_section` 增加"
        "八维度汇总区块渲染（承接 E2，改）--H9 预算 1 文件 ~40 行，依赖 U2"
        "（消费聚合后的分组数据）。三单元均纵向切片。",
        "依赖 DAG 拓扑排序留痕（被依赖者先行）：U1->U2->U3。codegraph callers "
        "取证：`codegraph callers _aggregate_positive_ic` 确认 U2 改动点被依赖方"
        "无遗漏。TDD 序内嵌：每单元 failing test 先行。",
        "阶段划分：单阶段（三单元同属一个纵向切片）。②单阶段不可拆论证：三单元"
        "合计 3 文件 ~75 行，H9 内一次可完。断点验证方法（提案）：阶段末跑 "
        "`python3 scripts/generate_factor_summary_report.py --read default` + "
        "断言报告含八维度汇总区块（待子5 用户裁决）。",
        "要素 ID 覆盖核对：E1->U2、E2->U3、E3->U1，三要素全覆盖无漏。只提案"
        "不拍板：断点位置/阶段粒度均为提案，待子5 用户裁决，q/a 按序对齐。",
    ],
}

# ---- 子3 trace（锚点核验：逐单元四类核验+三态标注，假设 H1 传导）----
S3_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "TaskBreakdown",
    "sub_step": 3,
    "skill": "codegraph / Bash(test -f / pytest --collect-only) / Read",
    "purpose": (
        "锚点核验与假设标注：逐单元核验四类（目标文件/symbol 存在、测试接缝"
        "存在、验证命令可运行、No Placeholders）；三态逐单元标注（已验证附"
        "出处/假设含置信度+影响/证伪附理由）；只标注不裁决。"
    ),
    "q": [
        "U1/U2/U3 各单元四类核验如何（文件/symbol/测试接缝/命令/placeholder）？",
        "三态逐单元标注如何？假设项处置如何？",
    ],
    "a": [
        "U1：①paths.py 存在（Read 核实）；②测试接缝 tests/test_paths.py 存在"
        "（pytest --collect-only 留痕）；③验证命令 pytest tests/test_paths.py "
        "可运行；④No Placeholders 无。U2：①generate_factor_summary_report.py:"
        "_aggregate_positive_ic 存在（codegraph callers 留痕）；②tests/test_"
        "generate_factor_summary_report.py 存在；③pytest 可运行；④无 placeholder。"
        "U3：①sections.py:_generate_ic_section 存在；②tests/test_sections.py "
        "存在；③pytest 可运行；④无 placeholder。",
        "三态标注：U1/U2/U3 四类核验均=已验证（附上文出处）。假设 H1="
        "FACTOR_CATEGORIES 八维度对全 34 项因子覆盖无遗漏（置信度中×影响中，"
        "原样转录 design.md:25）原样携带--错误时影响=分组遗漏某维度因子，"
        "不裁决接受与否（留子5 用户裁决），q/a 按序对齐。",
    ],
}

# ---- 子4 clean：三 statements 归一化 U1/U2/U3，五字段忠实提取子2/子3，验收包全映射，假设 H1 传导 ----
_S4_BASE_STMTS = [
    {
        "text": "paths.py 新增 CATEGORY_SUMMARY_RESULT 路径常量",
        "type_label": "单阶段",
        "boundary": "假设 H1 传导：FACTOR_CATEGORIES 八维度对全 34 项因子覆盖无遗漏"
        "（置信度中×影响中，原样转录 design.md:25）",
        "fields": {
            "change_point": "paths.py:+CATEGORY_SUMMARY_RESULT（增）",
            "interface": "Consumes: 无（基础）；Produces: CATEGORY_SUMMARY_RESULT 路径常量",
            "verify": "failing test test_category_summary_result_exists 断言常量存在；"
            "命令 pytest tests/test_paths.py::test_category_summary_result_exists；"
            "期望失败->通过",
            "acceptance_map": "（无直接验收包承接，为 U2/U3 提供输出路径基础）",
            "trace_anchor": "E3（paths.py 增加 CATEGORY_SUMMARY_RESULT 路径常量）",
        },
    },
    {
        "text": "generate_factor_summary_report.py _aggregate_positive_ic 增加 FACTOR_CATEGORIES 分组键",
        "type_label": "单阶段",
        "boundary": "假设 H1 传导：FACTOR_CATEGORIES 八维度对全 34 项因子覆盖无遗漏"
        "（置信度中×影响中，原样转录 design.md:25）",
        "fields": {
            "change_point": "summary/generate_factor_summary_report.py:_aggregate_positive_ic "
            "增加 FACTOR_CATEGORIES 分组键（改）",
            "interface": "Consumes: CATEGORY_SUMMARY_RESULT（U1）、factor_definitions.py 映射；"
            "Produces: 按 FACTOR_CATEGORIES 分组的聚合数据结构",
            "verify": "failing test test_aggregate_groups_by_category 断言分组输出结构；"
            "命令 pytest tests/test_generate_factor_summary_report.py::test_aggregate_groups_by_category；"
            "期望失败->通过",
            "acceptance_map": "SC1.1（八维度条数+占比可读出）、SC2.1（分组口径与映射一致）",
            "trace_anchor": "E1（_aggregate_positive_ic 增加 FACTOR_CATEGORIES 分组键）",
        },
    },
    {
        "text": "report/sections.py _generate_ic_section 增加八维度汇总区块渲染",
        "type_label": "单阶段",
        "boundary": "假设 H1 传导：FACTOR_CATEGORIES 八维度对全 34 项因子覆盖无遗漏"
        "（置信度中×影响中，原样转录 design.md:25）",
        "fields": {
            "change_point": "summary/report/sections.py:_generate_ic_section 增加"
            "八维度汇总区块渲染（改）",
            "interface": "Consumes: 按 FACTOR_CATEGORIES 分组的聚合数据（U2）；"
            "Produces: 报告八维度汇总区块",
            "verify": "failing test test_ic_section_renders_category_block 断言区块渲染；"
            "命令 pytest tests/test_sections.py::test_ic_section_renders_category_block；"
            "期望失败->通过",
            "acceptance_map": "SC3.1（交付形态=报告新增八维度汇总区块）",
            "trace_anchor": "E2（_generate_ic_section 增加八维度汇总区块渲染）",
        },
    },
]


def _s4(stmts):
    return {
        "kind": "skill-trace",
        "major_stage": "Plan",
        "minor_stage": "TaskBreakdown",
        "sub_step": 4,
        "skill": "define-problem(归一化) / superpowers:writing-plans(Task Structure)",
        "purpose": (
            "归一化执行步骤：每项=1 个可独立验证/提交的交付物（原子+去上下文+"
            "五字段执行包）；验收包与要素双向覆盖；假设 H1 原样携带不丢不淡化。"
        ),
        "statements": stmts,
    }


S4_CLEAN = _s4(copy.deepcopy(_S4_BASE_STMTS))

# ---- vio1：字段篡改--U2 change_point 由子2「增加分组键」篡改为「重写为独立聚合器」 ----
S4_VIO1 = _s4(copy.deepcopy(_S4_BASE_STMTS))
S4_VIO1["statements"][1]["fields"]["change_point"] = (
    "summary/generate_factor_summary_report.py:_aggregate_positive_ic 重写为"
    "独立八维度聚合器，输出全新数据结构（改）"
)

# ---- vio2：复合句--U2 text「以及」连接两个可独立提交的交付物 ----
S4_VIO2 = _s4(copy.deepcopy(_S4_BASE_STMTS))
S4_VIO2["statements"][1]["text"] = (
    "generate_factor_summary_report.py _aggregate_positive_ic 增加 FACTOR_CATEGORIES "
    "分组键，以及新增独立的分组校验脚本"
)

# ---- vio3：验证方法不可执行且无辩护--U3 verify「人工看一下」 ----
S4_VIO3 = _s4(copy.deepcopy(_S4_BASE_STMTS))
S4_VIO3["statements"][2]["fields"]["verify"] = "人工看一下报告里八维度区块对不对"

# ---- vio4：验收包映射漏项--SC1.1/SC2.1/SC3.1 全无承接（三项 acceptance_map 均「无」） ----
S4_VIO4 = _s4(copy.deepcopy(_S4_BASE_STMTS))
S4_VIO4["statements"][0]["fields"]["acceptance_map"] = "（无直接验收包承接）"
S4_VIO4["statements"][1]["fields"]["acceptance_map"] = "（无直接验收包承接）"
S4_VIO4["statements"][2]["fields"]["acceptance_map"] = "（无直接验收包承接）"

CASES = {
    "clean": S4_CLEAN,
    "vio1_字段篡改": S4_VIO1,
    "vio2_复合句": S4_VIO2,
    "vio3_验证不可执行无辩护": S4_VIO3,
    "vio4_验收包映射漏项": S4_VIO4,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {
        k: "\n".join(
            json.dumps(t, ensure_ascii=False) for t in (S1_BASE, S2_BASE, S3_BASE, s4)
        )
        for k, s4 in CASES.items()
    }
    run_cases("plan:2#4 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
