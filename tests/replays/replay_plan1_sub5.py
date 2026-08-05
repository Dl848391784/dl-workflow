#!/usr/bin/env python3
"""plan:1 子5 归一化设计陈述 gate 回归重放（反转的回归资产，
designs/plan1-sub5-gate-framing-design.md）。

**plan:1（设计解决方案）第五个反转节点**（前四=plan:1#1/#2/#3/#4 已入库）。
设计任务承接同一场景链：摘要报告展示 default 管线正 IC 因子条数+占比
（子1 勘察 summary/report 链路 -> 子2 三候选 -> 子3 五项核验三态 -> 子4 Pugh
评估提案推荐候选A -> 子5 归一化设计陈述八字段）。

命题性质=**代码设计包归一化**（从子4 推荐提案推导 statements 八字段设计包），
主敌=「长链转换失真」：字段篡改/假设淡化/ADR 理由丢失/复合未拆/凭空新增五类。
record_format=statements（statement_fields 八键 change_list/interface_sig/
data_contract/callers/rejected/assumptions/acceptance_map/h9_units 由
append-trace 逐键 JSON 校验非空 + text 实现侧名词机械扫描）。

artifact=子1+子2+子3+子4+子5 最新 trace 拼合（生产 read_evidence_for_step(5,
"DesignSolution") 同形——本 gate 判据涉字段传导对照[子3 核验事实/假设三态、
子4 否决理由与推荐]，前序 trace 是判材非纯组成事实，#30 ⑧/⑨）。
**must 目标/验收包 SC ID 属 GoalsAndValue／SuccessCriteria 节点，minor_stage
过滤后结构性不可见**（#30 ㉚②）=判据钉「不判验收包真实性/完整性」。

clean（三 statements 全 type_label=推荐，八字段忠实提取子3 核验事实+子4 否决
理由，候选C 假设原样携带置信度×影响，callers 附 codegraph 出处，H9 划分承接
子3 量化）/
vio1 字段篡改（statement1 change_list 由子4 推荐的候选A「sections.py 内增加聚合
分支」篡改为候选C 的「factor_ic 计算侧预聚合落成一列」——与子4 推荐语义冲突）/
vio2 复合句（statement1 text「以及」连接两个可独立拍板的设计决策）/
vio3 凭空新增子4 未评估要素（第 4 条 statement 引入子2/子3/子4 全程未出现的
「新增 Redis 缓存层缓存聚合结果」）/
vio4 假设淡化（候选C 假设的置信度×影响被抹成「小风险，可忽略」——子3 原样
转录的置信度中×影响（改动面扩到 5+ 文件 H9 需分解）丢失）/
vio5 否决理由丢失（rejected 字段只写「候选B、候选C 已被否」，子4 逐项 ADR
理由[H8 触发/净分 −2/impact 7 符号/schema 迁移]全丢）。

vio 载荷保真度（#30 ㉖/㊷ 单点越界）：vio1 只换 statement1 的 change_list
（其余七字段与其余两项不动）；vio2 只换 statement1 的 text；vio3 只追加一条
statement（原三项不动）；vio4 只换 statement1 的 assumptions；vio5 只换
statement1 的 rejected。

**本节点读数口径（#30 ⑦/㉗，别把设计内读数当回归）**：vio5 的生产墙是 **mech**
（`rejected_rationale_trace`，append-trace 写侧当场拒；对本载荷集 100% 精确=只在
vio5 触发、clean 与 vio1-4 全静默，单测 test_p1s5_rejected_rationale_block_pass_skip
零方差证拒）；gate 方框五已声明「已由 rejected_rationale_trace 机械校验、不得以
『rejected 只列名单/未附否决理由』block」，故 **judge 侧 vio5 2-4/6 是设计内委托**，
不是崩牙。judge 侧达标线只看 clean ≥5/6 + vio1-4 ≥5/6 **且判词引对条款**（㉖ 错理由
拦对不算牙——基线从严版 vio5 命中 6/6 却零轮引对条款，正是本例下沉 mech 的动因）。
落地版实测（n=6 × 2 轮）：clean 6/6 与 5/6、vio1 5/6 与 6/6、vio2 6/6+6/6、
vio3 6/6 与 5/6、vio4 6/6+6/6。clean 的偶发 block 为自相矛盾判词（逐条判「合规」后
仍 pass=false）=㉑ 推理底噪声轮，非回归信号。

用法: python3 tests/replays/replay_plan1_sub5.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "设计解决方案 · 子步骤5"
STEP = sub_step("plan:1", 4)

# ---- 子1 trace（现状勘察，压缩自 replay_p1_sub4.py S1）----
S1 = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "DesignSolution",
    "sub_step": 1,
    "skill": "codegraph callers/impact / Read / Grep / Bash(新鲜度+数据契约)",
    "purpose": "代码现状勘察：现状地图四要素，每条附 codegraph 原始输出或 file:line 出处。",
    "q": ["新鲜度与①涉及模块？", "②可复用点？", "③调用方与影响面？", "④数据契约？"],
    "a": [
        "Bash 实测 codegraph 新鲜度输出 2026-08-04 09:12（<72h 无需 sync）。①报告 IC "
        "区块生成在 `summary/report/sections.py:32` `_generate_ic_section`（codegraph "
        "输出 `function _generate_ic_section summary/report/sections.py:32`）；Read "
        "sections.py 32-133 全段确认现有实现只渲染 IC 明细表、无正 IC 计数聚合分支。",
        "②可复用点：`summary/report/formatters.py:129 format_float` 与 "
        "`formatters.py:92 format_percentage`（codegraph 输出在册）；扩展点="
        "`_generate_ic_section` 内部已持有 IC 明细数据结构。",
        "③`codegraph callers _generate_ic_section` 输出 1 个调用方 "
        "`generate_factor_summary_report`；`codegraph impact _generate_ic_section` "
        "输出 3 个受影响符号。计算侧 `codegraph impact FACTOR_IC_RESULT` 输出 7 个"
        "受影响符号（跨 factor_ic 与 summary 两模块）。",
        "④IC 结果路径 `paths.py:75 FACTOR_IC_RESULT`、汇总产物 `paths.py:78 "
        "SUMMARY_RESULT`（Read paths.py 72-79 原文确认）；字段口径 Bash 实测 parquet "
        "schema 含 `ic_mean`——正 IC 判定用 `ic_mean > 0`。",
    ],
}

# ---- 子2 trace（方案发散三候选）----
S2 = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "DesignSolution",
    "sub_step": 2,
    "skill": "推理(架构维度变换) / AskUserQuestion(用户既有想法)",
    "purpose": "方案发散：≥3 个代码级候选，锚定子1 事实，架构维度实质差异，禁评估禁排序。",
    "q": ["代码级候选有哪些？", "候选间架构维度差异？", "用户既有想法？结论①还是②？"],
    "a": [
        "候选 3 个：候选A=在 `summary/report/sections.py:32 _generate_ic_section` "
        "内部增加正 IC 计数聚合，复用 `formatters.py:92 format_percentage` 渲染占比；"
        "候选B=新增 `summary/report/ic_stats.py` 承担聚合，`_generate_ic_section` "
        "只消费其返回值（聚合与渲染分离）；候选C=在计算侧（`paths.py:75 "
        "FACTOR_IC_RESULT` 生成时）预聚合正 IC 计数落成一列，summary 直接读。"
        "三候选均锚定子1 已列事实。",
        "架构维度差异：A=复用既有函数、模块归属 summary/report、执行时机=报告渲染时；"
        "B=新建文件、数据流改为聚合层与渲染层分离；C=模块归属下沉计算层、数据契约变更"
        "（parquet 加列）、执行时机=IC 计算阶段。三者两两不重叠。",
        "经 AskUserQuestion 询问，用户暂无既有方案；发散过程只列候选不评价优劣。"
        "结论①多候选成立。",
    ],
}

# ---- 子3 trace（五项核验 + 三态标注）----
S3 = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "DesignSolution",
    "sub_step": 3,
    "skill": "codegraph / Bash / Read(接口存在性+影响面+重复实现)",
    "purpose": "可行性验证与假设标注：逐候选五项核验（存在性/重复造轮子/影响面/硬规则/可测试性）+ 三态标注。",
    "q": [
        "候选A 五项核验结果？",
        "候选B 五项核验结果？",
        "候选C 五项核验结果？",
        "三态标注与重复实现检查？",
    ],
    "a": [
        "候选A：①存在性=`_generate_ic_section`（sections.py:32）+`format_percentage`"
        "（formatters.py:92）经 Read 原文核实在册；②重复实现=`codegraph` 查无既有正 IC "
        "计数实现；③影响面=`codegraph impact _generate_ic_section` 输出 3 个受影响符号，"
        "仅报告生成链路单侧；④硬规则=改动限 summary 模块内（H1 合规）、路径经 "
        "`from paths import`（H7）、1 文件约 30 行（H9 单单元可完成）；⑤可测试性="
        "sections.py 已有测试接缝（Bash 实测 `ls tests/test_report_sections.py` 在册）。",
        "候选B：①存在性=新增文件无存在性风险，消费侧 `_generate_ic_section` 在册"
        "（Read 核实）；②重复实现=同上无既有实现；③影响面=3 个受影响符号 + 新模块无 "
        "callers；④硬规则=2 文件改动约 60 行（H9 内），跨 2 文件触发 H8 需 design.md；"
        "⑤可测试性=新模块纯函数最易挂测试（无 IO）。",
        "候选C：①存在性=`paths.py:75 FACTOR_IC_RESULT` 在册（Read 核实），但计算侧"
        "写侧是否有可插入聚合的接缝**未实测确认**；②重复实现=无；③影响面="
        "`codegraph impact FACTOR_IC_RESULT` 输出 7 个受影响符号，跨两模块；④硬规则="
        "数据契约变更需 schema 迁移、跨模块改动触发 H8，改动面估 3 文件约 120 行；"
        "⑤可测试性=需构造 parquet fixture，接缝成本高。",
        "三态标注：候选A=可行（出处见上，全部经 Read/codegraph/Bash 核实）；候选B=可行"
        "（同上）；候选C=**假设**（置信度中——写侧接缝未实测；错误时影响=若无接缝则须改"
        "计算写侧并做 schema 迁移，改动面从 3 文件扩到 5+ 文件、H9 需分解）。无证伪剔除项。"
        "重复造轮子检查三候选均已跑 codegraph，无同功能既有实现。",
    ],
}

# ---- 子4 trace（Pugh 评估提案，推荐候选A）----
S4 = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "DesignSolution",
    "sub_step": 4,
    "skill": "推理(Pugh 矩阵) / Agent(条件红队)",
    "purpose": "评估收敛与选型提案：Pugh 矩阵逐格 +/S/− 附理由且理由引子3 核验事实；双向追溯；条件红队；排序+推荐提案，只提案不拍板。",
    "q": [
        "Pugh 矩阵 datum 与六判据逐格评分及理由是什么？",
        "双向追溯两向逐项结果如何？",
        "条件红队触发了吗？",
        "排序与推荐提案是什么？",
    ],
    "a": [
        "datum=候选A（子3 核验其改动面最小：1 文件约 30 行）。候选B：验收包承接度 S；"
        "改动面 −（子3 实测 2 文件约 60 行 vs A 的 1 文件 30 行）；影响面 S；复用度 −"
        "（子3 记 A 复用 `formatters.py:92 format_percentage`，B 新建模块不复用）；"
        "可测试性 +（子3 记 B 新模块纯函数无 IO）；硬规则兼容 −（子3 记 B 跨 2 文件"
        "触发 H8 需 design.md）。净分 −2。候选C：验收包承接度 S；改动面 −（子3 估 "
        "3 文件约 120 行）；影响面 −（子3 impact 输出 7 个受影响符号、跨两模块 vs A "
        "的 3 符号单侧）；复用度 −；可测试性 −（子3 记需构造 parquet fixture）；"
        "硬规则兼容 −（子3 记数据契约变更需 schema 迁移 + 跨模块触发 H8）。净分 −5。",
        "双向追溯逐项：backward 要素「正 IC 条数聚合」→目标「基于正 IC 因子规模决定"
        "筛选门槛」；要素「占比渲染复用 format_percentage」→同目标；要素「既有报告"
        "区块内呈现」→目标「不新增图表、只在既有报告读到数字」。无镀金项。forward "
        "两个自述 must 目标各有要素承接，无漏项。",
        "条件红队：触发条件=候选分差小（净分差 ≤1）或领先方案改动跨模块。领先方案="
        "候选A，改动不跨模块且与次优净分差 2（>1）——**未触发**（触发条件与实际取值："
        "净分差=2、跨模块=否）。另对跨模块且带假设的候选C 单独跑一次独立上下文 Agent "
        "攻击并原文收录：「候选C 的『写侧有可插入接缝』假设若不成立，schema 迁移会"
        "波及计算侧全部消费方（impact 7 符号）；四态 verdict=成立。」",
        "排序（按净分）：候选A（0，datum）> 候选B（−2）> 候选C（−5）。**推荐提案**="
        "候选A，理由=子3 核验事实（改动面最小 1 文件 30 行、影响面 3 符号单侧、复用"
        "既有 format_percentage、无 H8 触发）。本排序与推荐均为提案，权重与选型待子6 "
        "用户裁决；候选C 的假设是否接受同留子6。",
    ],
}

# ---- 子5 clean：三 statements 八字段忠实传导 ----
_BASE_STMTS = [
    {
        "text": "正 IC 因子的条数与占比在既有摘要报告的 IC 区块内直接可读出",
        "type_label": "推荐",
        "boundary": "verdict 边界=default 管线、数据截至子1 勘察快照（codegraph "
        "indexed_at 2026-08-04 09:12）；实现指针 summary/report/sections.py:32 "
        "`_generate_ic_section`",
        "fields": {
            "change_list": "summary/report/sections.py -> `_generate_ic_section` "
            "内增加正 IC 计数聚合分支（改）——承接子4 推荐提案候选A",
            "interface_sig": "`_generate_ic_section(ic_records, ...)` 签名不变，"
            "内部新增聚合分支；无新增公开接口",
            "data_contract": "数据契约不变——消费 `paths.py:75 FACTOR_IC_RESULT` 的 "
            "`ic_mean` 字段（子1 Bash 实测 parquet schema 含 ic_mean，正 IC 判定 "
            "ic_mean > 0），parquet 不加列",
            "callers": "`codegraph callers _generate_ic_section` 输出 1 个调用方 "
            "`generate_factor_summary_report`；`codegraph impact _generate_ic_section` "
            "输出 3 个受影响符号（子1/子3 出处）",
            "rejected": "候选B（新增 `summary/report/ic_stats.py` 聚合与渲染分离）"
            "被否——理由=子3 核验其跨 2 文件触发 H8 需 design.md 且不复用既有 "
            "`format_percentage`，子4 Pugh 净分 −2；候选C（计算侧预聚合落成一列）"
            "被否——理由=子3 核验其 `codegraph impact FACTOR_IC_RESULT` 输出 7 个"
            "受影响符号跨两模块、数据契约变更需 schema 迁移，子4 Pugh 净分 −5",
            "assumptions": "候选C 的「计算写侧有可插入聚合接缝」为假设（置信度中×"
            "影响：若不成立则须改写侧并做 schema 迁移、改动面从 3 文件扩到 5+ 文件、"
            "H9 需分解——子3 原样转录）；该假设随候选C 被否不进入本方案，本方案"
            "（候选A）无待接受假设",
            "acceptance_map": "SC1.1（报告可读出正 IC 条数）由本要素承接",
            "h9_units": "执行单元 U1=1 文件约 30 行（子3 核验量化），H9 单单元内"
            "可完成、无需分解",
        },
    },
    {
        "text": "占比数字沿用报告既有的百分比呈现口径，不新建呈现路径",
        "type_label": "推荐",
        "boundary": "verdict 边界=复用点经 codegraph + Read 双核实（子1 出处）；"
        "实现指针 summary/report/formatters.py:92 `format_percentage`",
        "fields": {
            "change_list": "复用 `summary/report/formatters.py:92 format_percentage`"
            "（该文件不改动）——承接子4 Pugh 复用度判据 A 优于 B/C",
            "interface_sig": "调用既有 `format_percentage(value)` 签名，无签名变更",
            "data_contract": "无数据契约变更（纯格式化，不落盘）",
            "callers": "`codegraph` 输出 `format_percentage` 在册（子1 出处）；"
            "复用既有函数不新增 callers",
            "rejected": "被否路径=自行实现百分比格式化——理由=子3 重复造轮子检查"
            "确认既有实现在册（子4 Pugh 复用度格 B/C 均记 −）",
            "assumptions": "无（复用点经 codegraph + Read 双核实，子1/子3 出处）",
            "acceptance_map": "SC1.2（占比可读出）由本要素承接",
            "h9_units": "并入执行单元 U1（同文件同函数，不独立计入 H9 预算）",
        },
    },
    {
        "text": "呈现形态限定为既有报告区块内的两个数字，不新增图表或独立报告页",
        "type_label": "推荐",
        "boundary": "verdict 边界=子4 backward 追溯已确认该形态无镀金；实现指针 "
        "summary/report/sections.py:32 既有区块",
        "fields": {
            "change_list": "无新增文件（仅在 `sections.py` 既有 IC 区块内渲染两个数字）",
            "interface_sig": "无新增接口",
            "data_contract": "`paths.py:78 SUMMARY_RESULT` 产物结构不变（子1 Read 核实）",
            "callers": "`codegraph impact _generate_ic_section` 输出 3 个受影响符号，"
            "均在报告生成链路单侧（子3 出处）",
            "rejected": "被否形态=新增独立图表或独立报告页——理由=子4 backward 双向"
            "追溯该要素回溯不到 must 目标=镀金项",
            "assumptions": "无",
            "acceptance_map": "SC2.1（交付形态=既有报告区块内呈现、不新增图表）"
            "由本要素承接",
            "h9_units": "并入执行单元 U1（同文件同区块）",
        },
    },
]


def _s5(stmts):
    return {
        "kind": "skill-trace",
        "major_stage": "Plan",
        "minor_stage": "DesignSolution",
        "sub_step": 5,
        "skill": "define-problem(归一化)",
        "purpose": (
            "归一化设计陈述：每项=1 个可独立拍板的设计决策（原子+去上下文+"
            "八字段设计包）；字段忠实传导子3 核验事实与子4 否决理由；假设原样"
            "携带置信度×影响；携带 verdict 边界。"
        ),
        "statements": stmts,
    }


S5_CLEAN = _s5(copy.deepcopy(_BASE_STMTS))

# ---- vio1：字段篡改--statement1 change_list 换成子4 已否决的候选C 改动 ----
S5_VIO1 = _s5(copy.deepcopy(_BASE_STMTS))
S5_VIO1["statements"][0]["fields"]["change_list"] = (
    "计算侧 `factor_ic` 写侧预聚合正 IC 计数落成一列，`paths.py:75 "
    "FACTOR_IC_RESULT` parquet 加列，summary 直接读（改）"
)

# ---- vio2：复合句--statement1 text「以及」连接两个可独立拍板的设计决策 ----
S5_VIO2 = _s5(copy.deepcopy(_BASE_STMTS))
S5_VIO2["statements"][0]["text"] = (
    "正 IC 因子的条数与占比在既有摘要报告的 IC 区块内直接可读出，"
    "以及新增一个独立的因子分类占比看板供人工巡检"
)

# ---- vio3：凭空新增子4 未评估的要素（追加第 4 条，原三项不动）----
S5_VIO3 = _s5(copy.deepcopy(_BASE_STMTS))
S5_VIO3["statements"].append(
    {
        "text": "聚合结果被缓存以避免每次生成报告时重复计算",
        "type_label": "推荐",
        "boundary": "verdict 边界=缓存命中率未测；实现指针 summary/report/cache.py",
        "fields": {
            "change_list": "新增 `summary/report/cache.py` 引入 Redis 缓存层缓存"
            "正 IC 聚合结果（增）",
            "interface_sig": "新增 `get_cached_positive_ic(key) -> dict`",
            "data_contract": "新增 Redis key 命名约定 `ic:positive:<date>`",
            "callers": "新模块暂无 callers",
            "rejected": "无",
            "assumptions": "假设运行环境已部署 Redis（置信度低×影响高）",
            "acceptance_map": "SC1.1（间接——加速报告生成）",
            "h9_units": "执行单元 U2=1 文件约 50 行",
        },
    }
)

# ---- vio4：假设淡化--置信度×影响被抹成「小风险，可忽略」 ----
S5_VIO4 = _s5(copy.deepcopy(_BASE_STMTS))
S5_VIO4["statements"][0]["fields"]["assumptions"] = (
    "候选C 的写侧接缝问题是个小风险，可忽略；本方案（候选A）无待接受假设"
)

# ---- vio5：否决理由丢失--rejected 只列被否名单无逐项 ADR 理由 ----
S5_VIO5 = _s5(copy.deepcopy(_BASE_STMTS))
S5_VIO5["statements"][0]["fields"]["rejected"] = "候选B、候选C 已被否"

CASES = {
    "clean": S5_CLEAN,
    "vio1_字段篡改": S5_VIO1,
    "vio2_复合句": S5_VIO2,
    "vio3_凭空新增要素": S5_VIO3,
    "vio4_假设淡化": S5_VIO4,
    "vio5_否决理由丢失": S5_VIO5,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {
        k: "\n".join(json.dumps(t, ensure_ascii=False) for t in (S1, S2, S3, S4, s5))
        for k, s5 in CASES.items()
    }
    run_cases("plan:1#5 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
