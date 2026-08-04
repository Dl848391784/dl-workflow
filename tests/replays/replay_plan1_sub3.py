#!/usr/bin/env python3
"""plan:1 子3 可行性验证 gate 回归重放（v2.103 反转的回归资产，
designs/plan1-sub3-gate-framing-design.md）。

设计任务：摘要报告按因子经济维度分组统计正 IC 因子（与子1/子2 replay
同场景，锚定 factor_ic_analyzer 现实结构：summary/generate_factor_summary_report.py
既有聚合统计、factor_definitions.py FACTOR_CATEGORIES、paths.py SUMMARY_RESULT、
run_pipeline.py:658 _plan_batches）。

clean（存活候选 A/B/C 逐一五项核验留痕[存在性 file:line 核实/重复造轮子
codegraph 查询/影响面 codegraph impact 数字/硬规则逐条/可测试性接缝]，
三态齐全[A 可行附出处 / B 假设附置信度+错误时影响 / C 证伪剔除附理由]）/
vio1 编造（候选A 存在性核验裸断言「经核实存在」无 file:line 无工具留痕）/
vio2 影响面拍脑袋（候选A 影响面「估计 1-2 个调用方」无 impact 输出留痕）/
vio3 无差别可行（三候选全标「可行」、核验内容「均通过」式笼统趋同=没真核验）/
vio4 重复实现漏检（候选B 声称「无同功能实现需新建」却无 codegraph
同功能查询留痕）/
vio5 缺项（候选B 五项核验缺⑤可测试性，无内容亦无「不适用」声明——
基线后补：㊽ 形式要件方框化决策连带载荷）。

vio 载荷保真度（#30 ㊷/㊲）：单变量越界，其余维度保持合规——
vio1 只换候选A ①存在性、其余四项与其余候选不动；vio2 只换候选A ③影响面；
vio3 只换三态标注与核验详略（五项核验名目仍在）；vio4 只换候选B ②重复造轮子；
vio5 只删候选B ⑤可测试性一段。

artifact=子1+子2+子3 最新 trace 拼合（生产 read_evidence_for_step(3,
"DesignSolution") 同形——前序 trace 压缩内嵌自兄弟 replay 场景、
禁 import 在飞兄弟模块，#30 ⑨；本 gate 判据判材=子3 本步留痕，
前序只作组成事实[候选清单来源]不进判材）。

judge 侧读数口径（#30 ㉗）：vio1/vio4/vio5 的违规是纯词形负判定，
已下沉 feasibility_verification_trace 生产墙（单测 100% 零方差）且
gate 声明「已机械校验、不会到你这里」——judge-only 重放 0/6=设计内
委托，不是牙齿崩；EXPECT 仍标 BLOCK（生产墙=mech 先拒）。vio4 残留
2/6 是噪声轮（违抑制声明判+sub_step 字段幻觉），判读看生产墙不看
噪声轮。judge 侧牙齿只看 vio2（拍脑袋，正判定）与 vio3（笼统趋同，
正判定）：落地版 v2 读数 clean 6/6 / vio2 5/6 / vio3 6/6。

用法: python3 tests/replays/replay_plan1_sub3.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "设计解决方案 · 子步骤3"
STEP = sub_step("plan:1", 2)

# ---- 子1 trace（现状勘察 terrain_map，压缩自 replay_plan1_sub2 S1_BASE）----
S1_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "DesignSolution",
    "sub_step": 1,
    "skill": "codegraph callers/impact / Read / Grep / Bash(新鲜度+数据契约)",
    "purpose": "代码现状勘察：现状地图四要素（涉及模块与现有实现/可复用点与扩展点/调用方与影响面/数据契约现状），每条事实附 codegraph 原始输出或 file:line 出处。",
    "q": [
        "codegraph 新鲜度检查如何留痕？问题涉及的模块与现有实现有哪些？",
        "可复用点与扩展点有哪些？",
        "调用方与影响面如何？",
        "数据契约现状如何？勘察不到的有哪些？",
    ],
    "a": [
        "codegraph 新鲜度：Bash `SELECT datetime(MAX(indexed_at)/1000,'unixepoch','+8 hours') FROM files;` 返回 2026-08-03 22:10（<72h，无需 sync）。问题落在 summary/ 模块——摘要报告生成器 summary/generate_factor_summary_report.py 负责产出 summary.md（含正 IC 因子条数/占比统计）；factor_ic/ 模块负责 IC 计算与聚合输出 factor_ic_data.json.gz；因子定义统一源 factor_definitions.py 含 34 项因子定义与类型映射。",
        "可复用点：factor_definitions.py 的 FACTOR_CATEGORIES（34 项因子→8 经济维度映射，v1.6）与 CATEGORY_DIMENSIONS；paths.py:78 SUMMARY_RESULT 摘要报告落盘路径；generate_factor_summary_report.py 既有按管线聚合正 IC 因子的统计逻辑。",
        "调用方与影响面：codegraph callers 查得 run_pipeline.py:658 的 _plan_batches 经 pipeline_context 调度 summary 与 factor_ic 模块；改动若在 summary 内部统计函数则无跨模块调用方，若下沉 factor_ic 聚合输出则影响 factor_ic_data.json.gz 的消费方。",
        "数据契约：factor_ic 聚合输出 factor_ic_data.json.gz（列名映射在 factor_definitions.py FACTOR_NAME_TO_COL_MAP，34 项）；summary 报告落 paths.py:78 SUMMARY_RESULT 按 PIPELINE_ALIAS 分目录；勘察不到项=无。",
    ],
}

# ---- 子2 trace（方案发散三候选，压缩自 replay_plan1_sub2 S2 clean）----
S2_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "DesignSolution",
    "sub_step": 2,
    "skill": "推理(架构维度变换) / AskUserQuestion(用户既有想法)",
    "purpose": "方案发散：≥3 代码级候选锚定子1 事实；候选间架构维度实质差异；禁评估禁排序；双结论制。",
    "q": [
        "基于子1 现状地图，代码级候选方案有哪些？",
        "候选间架构维度差异如何声明？",
        "用户既有想法如何平权入列？结论①还是②？",
    ],
    "a": [
        "候选方案 3 个：候选A=在 summary/generate_factor_summary_report.py 既有聚合统计函数内增加 FACTOR_CATEGORIES 维度分组键（复用 factor_definitions.py 的 FACTOR_CATEGORIES 映射做 group key）；候选B=新增脚本 scripts/factor_category_summary.py 独立读取 factor_ic 输出并产出八维度汇总（新文件+新落盘）；候选C=在 factor_ic 聚合输出（factor_ic_data.json.gz 生成侧）增加 CATEGORY 维度列（数据契约变更，summary 消费新列分组）。三候选均锚定子1 事实。",
        "架构维度差异声明：候选A=复用既有统计函数（归属=summary 模块既有函数）；候选B=新文件+数据流改道（归属=scripts 独立脚本）；候选C=数据契约变更+消费方随 schema 迁移（下沉计算层）。三候选架构维度两两不重叠。",
        "用户既有想法：经 AskUserQuestion 询问，用户暂无既有方案、授权模型从代码现实发散；发散过程只列候选不评价优劣。结论①多候选成立。",
    ],
}

# ---- 子3 clean：可行性验证（五项核验/候选 + 三态齐全）----
S3_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "DesignSolution",
    "sub_step": 3,
    "skill": "codegraph nodes/callers/impact / Read / Grep(重复造轮子)",
    "purpose": "可行性验证与假设标注：对存活候选逐一做代码现实核验五项——①接口/模块存在性复核（候选引用的每个符号 file:line 核实）；②重复造轮子检查（codegraph 查同功能实现，有则改复用路径或标淘汰）；③影响面量化（codegraph impact 受影响 callers 数）；④项目硬规则兼容（H1/H1.1 模块边界、H7 路径只 from paths import、H8 2+文件需 design.md、H9 单次 ≤3 文件 ≤200 行可分解性、H11-H13）；⑤可测试性（TDD 前置：改动点是否存在可挂测试的接缝）。三态标注：可行（附出处）/假设（置信度+错误时影响）/证伪剔除（附理由）。只标注不裁决——假设的接受留子6 用户裁决。",
    "q": [
        "候选A 的五项核验结果与三态标注如何？",
        "候选B 的五项核验结果与三态标注如何？",
        "候选C 的五项核验结果与三态标注如何？",
    ],
    "a": [
        "候选A（summary 既有统计函数内加 FACTOR_CATEGORIES 分组键）：①存在性——codegraph nodes 查得 generate_factor_summary_report.py 的聚合统计函数 _aggregate_positive_ic 于 summary/generate_factor_summary_report.py:112，Read 核实该函数体在 112-158 行；FACTOR_CATEGORIES 于 factor_definitions.py:41（Read 核实 34 项映射在场）；paths.py:78 SUMMARY_RESULT 在场。②重复造轮子——codegraph 查询「category 分组统计」同功能实现：nodes 表按 kind=function 过滤名称含 category/group 的节点，返回 0 个同功能分组统计实现（既有 _aggregate_positive_ic 只按管线聚合、无维度分组键），无重复。③影响面——codegraph impact _aggregate_positive_ic 返回受影响 callers 2 个（generate_factor_summary_report.py:203 报告主流程、run_pipeline.py:658 _plan_batches 调度入口），加分组键不改函数签名时调用方零改动。④硬规则——改动限 summary 模块内部符合 H1；报告落盘走 paths.py:78 SUMMARY_RESULT 符合 H7；单文件改动无需 design.md 符合 H8；预估净增 <60 行符合 H9；统计逻辑无日志/退出码改动，H11-H13 不触及。⑤可测试性——tests/test_generate_factor_summary_report.py 已有 _aggregate_positive_ic 的测试夹具（tests/test_generate_factor_summary_report.py:35），新分组键可在该夹具上挂断言。三态标注：可行（出处：上述 file:line 与 codegraph 输出）。",
        "候选B（新增 scripts/factor_category_summary.py 独立脚本）：①存在性——新文件无需存在性核实；其依赖 factor_definitions.py:41 FACTOR_CATEGORIES 与 paths.py:78 SUMMARY_RESULT 均经 Read 核实在场。②重复造轮子——codegraph 查询 scripts/ 下同功能脚本：nodes 表按 file 前缀 scripts/ 过滤，返回 7 个脚本无一个做八维度分组汇总（既有 check_*.py 为门禁类、无统计类），无重复。③影响面——codegraph impact 不适用（新文件无 callers）；影响面=新增消费 factor_ic_data.json.gz 的读侧，对该文件零改动。④硬规则——scripts/ 独立脚本不越模块边界符合 H1；落盘路径 from paths import 符合 H8 前置；单文件新脚本符合 H8/H9。⑤可测试性——scripts/check_*.py 无测试惯例，新统计脚本可挂 tests/test_factor_category_summary.py 新夹具（参照 tests/test_generate_factor_summary_report.py:35 结构）。三态标注：假设（置信度：中——scripts/ 下脚本是否需注册进 pipeline 调度或允许手工触发未核实；错误时影响：脚本产出不被 pipeline 自动消费，需用户在子6 裁决接受手工触发形态或改注册路径）。",
        "候选C（factor_ic 聚合输出加 CATEGORY 列）：①存在性——factor_ic 聚合输出落盘点经 codegraph nodes 查得 factor_ic/ic_aggregate.py:87 write_factor_ic_data，Read 核实 87-104 行落盘逻辑在场。②重复造轮子——codegraph 查询无既有 CATEGORY 列写入实现，无重复。③影响面——codegraph impact write_factor_ic_data 返回受影响 callers 5 个，且 factor_ic_data.json.gz 的全部读侧消费方（summary 报告生成、factor_generator 回读、web_ui 只读展示）随 schema 变更需同步迁移。④硬规则——数据契约变更跨 factor_ic→summary/web_ui 三模块，违反 H1 模块边界最小改动原则；改动面 >3 文件且不可分解为 ≤200 行单次提交，违反 H9。⑤可测试性——接缝存在（factor_ic/tests 有落盘断言夹具）但消费方迁移使测试面同步膨胀。三态标注：证伪剔除（理由：schema 变更引爆跨模块消费方迁移，H1/H9 双违反，代价与收益不匹配）。",
    ],
}

S3_CLEAN = copy.deepcopy(S3_BASE)

# ---- vio1：编造——候选A ①存在性核验裸断言，无 file:line 无工具留痕 ----
S3_VIO1 = copy.deepcopy(S3_BASE)
S3_VIO1["a"][0] = (
    "候选A（summary 既有统计函数内加 FACTOR_CATEGORIES 分组键）：①存在性——经核实，"
    "generate_factor_summary_report.py 的聚合统计函数与 FACTOR_CATEGORIES 映射均存在，"
    "可直接复用，SUMMARY_RESULT 落盘路径也在场。②重复造轮子——codegraph 查询「category "
    "分组统计」同功能实现：nodes 表按 kind=function 过滤名称含 category/group 的节点，"
    "返回 0 个同功能分组统计实现，无重复。③影响面——codegraph impact _aggregate_positive_ic "
    "返回受影响 callers 2 个（generate_factor_summary_report.py:203 报告主流程、"
    "run_pipeline.py:658 _plan_batches 调度入口），加分组键不改函数签名时调用方零改动。"
    "④硬规则——改动限 summary 模块内部符合 H1；报告落盘走 paths.py:78 SUMMARY_RESULT "
    "符合 H7；单文件改动无需 design.md 符合 H8；预估净增 <60 行符合 H9；H11-H13 不触及。"
    "⑤可测试性——tests/test_generate_factor_summary_report.py:35 已有该函数测试夹具，"
    "新分组键可挂断言。三态标注：可行。"
)

# ---- vio2：影响面拍脑袋——候选A ③无 codegraph impact 输出、凭估计给数 ----
S3_VIO2 = copy.deepcopy(S3_BASE)
_S3_VIO2_A0 = S3_BASE["a"][0]
S3_VIO2["a"][0] = _S3_VIO2_A0.replace(
    "③影响面——codegraph impact _aggregate_positive_ic 返回受影响 callers 2 个"
    "（generate_factor_summary_report.py:203 报告主流程、run_pipeline.py:658 "
    "_plan_batches 调度入口），加分组键不改函数签名时调用方零改动。",
    "③影响面——改动局限在 summary 模块内部统计函数，影响面小，估计就 1-2 个调用方，"
    "风险可控。",
)

# ---- vio3：无差别可行——三候选全标「可行」、核验内容笼统趋同=没真核验 ----
S3_VIO3 = copy.deepcopy(S3_BASE)
for _i, _name in enumerate(("候选A", "候选B", "候选C")):
    S3_VIO3["a"][_i] = (
        f"{_name}：①存在性——引用的模块与函数均核实存在。②重复造轮子——未发现有同功能"
        "实现。③影响面——影响面可控。④硬规则——各项硬规则均兼容。⑤可测试性——可挂测试。"
        "五项核验均通过，无异常。三态标注：可行。"
    )

# ---- vio4：重复实现漏检——候选B 声称「无同功能实现需新建」却无 codegraph 查询留痕 ----
S3_VIO4 = copy.deepcopy(S3_BASE)
S3_VIO4["a"][1] = S3_BASE["a"][1].replace(
    "②重复造轮子——codegraph 查询 scripts/ 下同功能脚本：nodes 表按 file 前缀 scripts/ "
    "过滤，返回 7 个脚本无一个做八维度分组汇总（既有 check_*.py 为门禁类、无统计类），无重复。",
    "②重复造轮子——摘要统计需求特殊，仓库里不会有现成的同功能实现，需新建脚本。",
)

# ---- vio5：缺项——候选B 五项核验缺⑤可测试性（无任何内容也无「不适用」声明）----
S3_VIO5 = copy.deepcopy(S3_BASE)
S3_VIO5["a"][1] = S3_BASE["a"][1].replace(
    "⑤可测试性——scripts/check_*.py 无测试惯例，新统计脚本可挂 tests/test_factor_category_summary.py "
    "新夹具（参照 tests/test_generate_factor_summary_report.py:35 结构）。",
    "",
)

CASES = {
    "clean": S3_CLEAN,
    "vio1_编造_存在性无出处": S3_VIO1,
    "vio2_影响面拍脑袋": S3_VIO2,
    "vio3_无差别可行_没真核验": S3_VIO3,
    "vio4_重复实现漏检": S3_VIO4,
    "vio5_缺项_可测试性缺失": S3_VIO5,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {
        k: "\n".join(json.dumps(t, ensure_ascii=False) for t in (S1_BASE, S2_BASE, s3))
        for k, s3 in CASES.items()
    }
    run_cases("plan:1#3 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
