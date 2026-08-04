#!/usr/bin/env python3
"""plan:1 子2 方案发散 gate 回归重放（v2.100 反转的回归资产，
designs/plan1-sub2-gate-framing-design.md）。

设计任务：摘要报告按因子经济维度分组统计正 IC 因子（锚定
factor_ic_analyzer 现实结构：summary/generate_factor_summary_report.py 既有
聚合统计、factor_definitions.py FACTOR_CATEGORIES 34 项因子→8 经济维度、
paths.py SUMMARY_RESULT、factor_ic/ic_*.py）。

clean（≥3 代码级候选[A 既有统计函数内加分组键 / B 新增独立脚本 /
C 计算层加 CATEGORY 列]，各锚定子1 事实，架构维度两两不重叠，
AskUserQuestion 已问用户无既有想法，无评估排序措辞，结论①）/
vio1 伪候选（三候选同=summary 既有统计函数内按 FACTOR_CATEGORIES 分组，
仅措辞变体，维度差异声明是假区分）/
vio2 凭空设计（候选B 引用子1 未勘察的 summary/render_lib.py
render_category_breakdown API）/
vio3 提前收敛排序（发散步混入「A 优于 B/C、最终选定 A」评估排序措辞）/
vio4 ②无逐维度论证（结论②设计空间唯一但无逐维度唯一性论证）。

vio 载荷保真度（#30 ㉖）：单变量越界，其余维度保持合规——
vio1 只换候选构成+维度声明、其余不动；vio2 只换候选B 引用、其余不动；
vio3 只换 a[2] 评估措辞、候选/维度不动；vio4 只换 ①→② 结论形态、
其余不动。

artifact=子1+子2 最新 trace 拼合（生产 read_evidence_for_step(2,
"DesignSolution") 同形——子1 terrain_map 是候选锚定参照，判「凭空设计」
须读子1 已勘察事实；跨节点输入不可见=判据钉「不判跨节点完整性」）。

用法: python3 tests/replays/replay_plan1_sub2.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "设计解决方案 · 子步骤2"
STEP = sub_step("plan:1", 1)

# ---- 子1 trace（现状勘察 terrain_map 四要素，压缩自真实项目结构）----
S1_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "DesignSolution",
    "sub_step": 1,
    "skill": "codegraph callers/impact / Read / Grep / Bash(新鲜度+数据契约)",
    "purpose": "代码现状勘察：现状地图四要素——①涉及模块与现有实现（codegraph 定位+Read 核实）；②可复用点与扩展点（禁凭印象）；③调用方与影响面（codegraph callers/impact）；④数据契约现状（paths.py/跨模块数据格式）。codegraph 新鲜度前置留痕（>72h 先 sync）；每条事实附 codegraph 原始输出或 file:line 出处；勘察不到的显式标「未知」。",
    "q": [
        "codegraph 新鲜度检查如何留痕？问题涉及的模块与现有实现有哪些？",
        "可复用点与扩展点有哪些？",
        "调用方与影响面如何？",
        "数据契约现状如何？勘察不到的有哪些？",
    ],
    "a": [
        "codegraph 新鲜度：Bash `SELECT datetime(MAX(indexed_at)/1000,'unixepoch','+8 hours') FROM files;` 返回 2026-08-03 22:10（<72h，无需 sync）。问题落在 summary/ 模块——摘要报告生成器 summary/generate_factor_summary_report.py 负责产出 summary.md（含正 IC 因子条数/占比统计）；factor_ic/ 模块负责 IC 计算与聚合输出 factor_ic_data.json.gz；因子定义统一源 factor_definitions.py 含 34 项因子定义与类型映射。",
        "可复用点：factor_definitions.py 的 FACTOR_CATEGORIES（34 项因子→8 经济维度映射，v1.6）与 CATEGORY_DIMENSIONS；paths.py:78 SUMMARY_RESULT 摘要报告落盘路径；generate_factor_summary_report.py 既有按管线聚合正 IC 因子的统计逻辑。",
        "调用方与影响面：codegraph callers 查得 run_pipeline.py:658 的 _plan_batches 经 pipeline_context 调度 summary 与 factor_ic 模块（pipeline 每阶段模块）；改动若在 summary 内部统计函数则无跨模块调用方，若下沉 factor_ic 聚合输出则影响 factor_ic_data.json.gz 的消费方（summary 报告生成）。",
        "数据契约：factor_ic 聚合输出 factor_ic_data.json.gz（列名映射在 factor_definitions.py FACTOR_NAME_TO_COL_MAP，34 项，权威列名）；summary 报告落 paths.py:78 SUMMARY_RESULT 按 PIPELINE_ALIAS 分目录；勘察不到项=无（范围内文件均已 Read）。",
    ],
}

# ---- 子2 clean：方案发散（≥3 代码级候选，锚定子1，维度差异，无评估排序）----
S2_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "DesignSolution",
    "sub_step": 2,
    "skill": "推理(架构维度变换) / AskUserQuestion(用户既有想法)",
    "purpose": "方案发散：基于子1 现状地图生成 ≥3 个代码级候选方案（每个=改哪个模块/哪个函数/新增什么文件/复用哪个现有实现，锚定子1 事实条目禁凭空 API）；候选间架构维度实质差异（换模块归属/换数据结构/复用 vs 新建/换执行时机/换数据流）；禁评估禁排序（评估是子4 的事）；用户既有想法平权入列不预设首选。双结论制：①多候选成立；②设计空间唯一（须逐维度论证）。",
    "q": [
        "基于子1 现状地图，代码级候选方案有哪些（每个=改哪个模块/函数/新增文件/复用哪个实现）？",
        "候选间架构维度差异如何声明？",
        "用户既有想法如何平权入列？发散过程有无评估/排序措辞？结论①还是②？",
    ],
    "a": [
        "候选方案 3 个：候选A=在 summary/generate_factor_summary_report.py 既有聚合统计函数内增加 FACTOR_CATEGORIES 维度分组键（复用 factor_definitions.py 的 FACTOR_CATEGORIES 映射做 group key，改动局限在既有统计函数内）；候选B=新增脚本 scripts/factor_category_summary.py 独立读取 factor_ic 输出并产出八维度汇总（不复用既有统计函数，新文件+新落盘）；候选C=在 factor_ic 聚合输出（factor_ic_data.json.gz 生成侧）增加 CATEGORY 维度列（数据契约变更，summary 消费新列分组）。三候选均锚定子1 事实：FACTOR_CATEGORIES 映射、generate_factor_summary_report.py 既有统计函数、factor_ic 聚合输出 factor_ic_data.json.gz、paths.py:78 SUMMARY_RESULT。",
        "架构维度差异声明：候选A=数据流不变、复用既有统计函数（复用 vs 新建=复用，归属=summary 模块既有函数）；候选B=新文件+数据流改道、不复用既有聚合（复用 vs 新建=新建，归属=scripts 独立脚本）；候选C=数据契约变更（factor_ic 输出加 CATEGORY 列）+消费方随 schema 迁移（换模块归属=下沉到计算层）。三候选在架构维度上两两不重叠。",
        "用户既有想法：经 AskUserQuestion 询问，用户暂无既有方案、授权模型从代码现实发散；发散过程只列候选不评价优劣，无「最佳/推荐/最优/优于」类评估排序措辞。结论①多候选成立。",
    ],
}

S2_CLEAN = copy.deepcopy(S2_BASE)

# ---- vio1：伪候选——三候选同=summary 既有统计函数内按 FACTOR_CATEGORIES 分组，仅措辞变体 ----
S2_VIO1 = copy.deepcopy(S2_BASE)
S2_VIO1["a"][0] = (
    "候选方案 3 个：候选A=在 summary/generate_factor_summary_report.py 的统计函数内按 "
    "FACTOR_CATEGORIES 分组统计正 IC 因子；候选B=在 summary/generate_factor_summary_report.py "
    "新增一个按 FACTOR_CATEGORIES 分组的统计函数（复用既有统计逻辑）；候选C=把 "
    "summary/generate_factor_summary_report.py 的统计函数改成按 FACTOR_CATEGORIES 分组输出。"
)
S2_VIO1["a"][1] = (
    "架构维度差异声明：候选A 用分组聚合、候选B 用独立函数、候选C 用改造既有函数，"
    "三者实现写法不同，架构维度各异。"
)

# ---- vio2：凭空设计——候选B 引用子1 未勘察的 summary/render_lib.py API ----
S2_VIO2 = copy.deepcopy(S2_BASE)
S2_VIO2["a"][0] = (
    "候选方案 3 个：候选A=在 summary/generate_factor_summary_report.py 既有聚合统计函数内"
    "增加 FACTOR_CATEGORIES 维度分组键（复用 factor_definitions.py 的 FACTOR_CATEGORIES 映射）；"
    "候选B=调用 summary/render_lib.py 的 render_category_breakdown API 产出八维度汇总区块"
    "（render_lib.py 提供现成的按维度分组渲染能力）；候选C=在 factor_ic 聚合输出"
    "（factor_ic_data.json.gz 生成侧）增加 CATEGORY 维度列（数据契约变更，summary 消费新列分组）。"
)

# ---- vio3：提前收敛排序——发散步混入评估排序措辞 ----
S2_VIO3 = copy.deepcopy(S2_BASE)
S2_VIO3["a"][2] = (
    "用户既有想法：经 AskUserQuestion 询问，用户暂无既有方案；发散过程比较了三候选——"
    "候选A 改动面最小、实现最简单，明显优于候选B 和候选C，最终选定候选A 作为方案，"
    "B/C 不再考虑。"
)

# ---- vio4：②无逐维度论证——结论②设计空间唯一但无逐维度唯一性论证 ----
S2_VIO4 = copy.deepcopy(S2_BASE)
S2_VIO4["a"][0] = (
    "候选方案：本任务约束已把设计维度全部钉死，只剩一条合理路径，故设计空间唯一，"
    "直接采用在 summary/generate_factor_summary_report.py 统计函数内按 FACTOR_CATEGORIES "
    "分组的方案。"
)
S2_VIO4["a"][1] = (
    "架构维度差异声明：无多候选，无需声明候选间维度差异。"
)
S2_VIO4["a"][2] = (
    "用户既有想法：经 AskUserQuestion 询问，用户暂无既有方案；发散过程只列唯一方案"
    "不评价优劣。结论②设计空间唯一。"
)

CASES = {
    "clean": S2_CLEAN,
    "vio1_伪候选_同方案措辞变体": S2_VIO1,
    "vio2_凭空设计_引用未勘察接口": S2_VIO2,
    "vio3_提前收敛排序": S2_VIO3,
    "vio4_无逐维度论证": S2_VIO4,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {
        k: "\n".join(
            json.dumps(t, ensure_ascii=False) for t in (S1_BASE, s2)
        )
        for k, s2 in CASES.items()
    }
    run_cases("plan:1#2 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
