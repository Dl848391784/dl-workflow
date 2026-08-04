#!/usr/bin/env python3
"""plan:1 子4 评估提案 gate 回归重放（v2.101 反转的回归资产，
designs/p1-sub4-gate-framing-design.md）。

设计任务：摘要报告展示 default 管线正 IC 因子条数+占比（承接
replay_p1_sub1.py / replay_plan1_sub2.py 同一场景链：子1 勘察 summary/report
链路 → 子2 三候选 → 子3 五项核验三态 → 子4 Pugh 评估提案）。

clean（Pugh 矩阵 datum=A 最小改动、六判据逐格 +/S/− 附理由且理由逐条引子3
核验事实、双向追溯两向逐项（backward 每要素回溯 must / forward 每 must 有
要素承接）、条件红队未触发留痕（触发条件+实际取值）并对 C 自愿加跑一次原文
收录、排序+推荐提案且「只提案待子6 用户裁决」语义）/
vio1 评分理由空泛不引子3 事实（逐格理由=「差不多/复杂一些/风险高」）/
vio2 替用户拍板（「最终选定 A、权重已确定、无需再问用户、直接剔除」定案口吻）/
vio3 推荐与净分矛盾（净分 A(0)>B(−2)>C(−5) 却推荐净分最低的 C 且无理由）/
vio4 双向追溯漏项（自述 must={G1,G2}，forward 只列 G1 承接）/
vio5 净分与逐格计数不符（B 逐格 1+/3−/2S 却声明净分 +3）。

**本节点读数口径（#30 ⑦/㉗，别把设计内读数当回归）**：vio4/vio5 的生产墙是
**mech**（pugh_traceability_forward_coverage / pugh_net_score_consistency，
append-trace 写侧当场拒，两者对本载荷集 100% 精确=各只在自己那条上触发）；
gate 已声明「该项已机械校验、不得以此 block」，故 **judge 侧 vio4 ~1/6、
vio5 0/6 是设计内委托**，不是崩牙。judge 侧达标线只看 clean 6/6 +
vio1/vio2/vio3 ≥5/6。落地版实测：clean 6/6、vio1 5/6、vio2 6/6、vio3 6/6。

vio 载荷保真度（#30 ㉖/㊷ 单点越界）：vio1 只换逐格理由（矩阵结论/追溯/
红队/提案语义不动）；vio2 只换结论段口吻；vio3 只换推荐的候选（净分与逐格
计数保持自洽——算术面归 vio5，不与 vio3 混）；vio4 只删 forward 的 G2 承接；
vio5 只改 B 的净分数值与随之的排序推荐。

artifact=子1+子2+子3+子4 最新 trace 拼合（生产 read_evidence_for_step(4,
"DesignSolution") 同形——子3 核验事实是本步「理由引事实」的对照基准，判材
在载荷内；**must 目标/验收包属 SuccessCriteria 与 GoalsAndValue 节点，
minor_stage 过滤后结构性不可见**=判据钉「不判跨节点完整性」，双向追溯只判
trace 内自洽，#30 ㉚②）。

用法: python3 tests/replays/replay_p1_sub4.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "设计解决方案 · 子步骤4"
STEP = sub_step("plan:1", 3)

# ---- 子1 trace（现状勘察，压缩自 replay_p1_sub1.py clean）----
S1 = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "DesignSolution",
    "sub_step": 1,
    "skill": "codegraph callers/impact / Read / Grep / Bash(新鲜度+数据契约)",
    "purpose": "代码现状勘察：现状地图四要素，每条附 codegraph 原始输出或 file:line 出处。",
    "q": ["新鲜度与①涉及模块？", "②可复用点？", "③调用方与影响面？", "④数据契约？"],
    "a": [
        "Bash 实测 `sqlite3 .codegraph/codegraph.db \"SELECT datetime(MAX(indexed_at)/1000,'unixepoch','+8 hours') FROM files;\"` 输出 2026-08-04 09:12（<72h 无需 sync）。①报告 IC 区块生成在 `summary/report/sections.py:32` `_generate_ic_section`（codegraph 输出 `function _generate_ic_section summary/report/sections.py:32`）；Read sections.py 32-133 全段确认现有实现只渲染 IC 明细表、无正 IC 计数聚合分支。",
        "②可复用点：`summary/report/formatters.py:129 format_float` 与 `formatters.py:92 format_percentage`（codegraph 输出在册）；扩展点=`_generate_ic_section` 内部已持有 IC 明细数据结构。",
        "③`codegraph callers _generate_ic_section` 输出 1 个调用方 `generate_factor_summary_report`；`codegraph impact _generate_ic_section` 输出 3 个受影响符号。factor_ic 计算侧 `codegraph impact FACTOR_IC_RESULT` 输出 7 个受影响符号（跨 factor_ic 与 summary 两模块）。",
        '④IC 结果路径 `paths.py:75 FACTOR_IC_RESULT`、汇总产物 `paths.py:78 SUMMARY_RESULT`（Read paths.py 72-79 原文确认）；字段口径 Bash 实测 `python3 -c "import pyarrow.parquet as pq; print(pq.read_schema(FACTOR_IC_RESULT).names)"` 输出含 `ic_mean`——正 IC 判定用 `ic_mean > 0`。',
    ],
}

# ---- 子2 trace（方案发散三候选，压缩自 replay_plan1_sub2.py clean 形态）----
S2 = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "DesignSolution",
    "sub_step": 2,
    "skill": "推理(架构维度变换) / AskUserQuestion(用户既有想法)",
    "purpose": "方案发散：≥3 个代码级候选，锚定子1 事实，架构维度实质差异，禁评估禁排序。",
    "q": ["代码级候选有哪些？", "候选间架构维度差异？", "用户既有想法？结论①还是②？"],
    "a": [
        "候选 3 个：候选A=在 `summary/report/sections.py:32 _generate_ic_section` 内部增加正 IC 计数聚合，复用 `formatters.py:92 format_percentage` 渲染占比；候选B=新增 `summary/report/ic_stats.py` 承担聚合，`_generate_ic_section` 只消费其返回值（聚合与渲染分离）；候选C=在 factor_ic 计算侧（`paths.py:75 FACTOR_IC_RESULT` 生成时）预聚合正 IC 计数落成一列，summary 直接读。三候选均锚定子1 已列事实。",
        "架构维度差异：A=复用既有函数、模块归属 summary/report、执行时机=报告渲染时；B=新建文件、数据流改为聚合层与渲染层分离；C=模块归属下沉计算层、数据契约变更（parquet 加列）、执行时机=IC 计算阶段。三者两两不重叠。",
        "经 AskUserQuestion 询问，用户暂无既有方案；发散过程只列候选不评价优劣。结论①多候选成立。",
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
        "候选A：①存在性=`_generate_ic_section`（sections.py:32）+`format_percentage`（formatters.py:92）经 Read 原文核实在册；②重复实现=`codegraph` 查无既有正 IC 计数实现；③影响面=`codegraph impact _generate_ic_section` 输出 3 个受影响符号，仅报告生成链路单侧；④硬规则=改动限 summary 模块内（H1 合规）、路径经 `from paths import`（H7）、1 文件约 30 行（H9 单单元可完成，无需 design.md）；⑤可测试性=sections.py 已有测试接缝（Bash 实测 `ls tests/test_report_sections.py` 在册），计数函数可直接挂断言。",
        "候选B：①存在性=新增文件无存在性风险，消费侧 `_generate_ic_section` 在册（Read 核实）；②重复实现=同上无既有实现；③影响面=`codegraph impact _generate_ic_section` 3 个受影响符号 + 新模块无 callers；④硬规则=2 文件改动约 60 行（H9 内），跨 2 文件触发 H8 需 design.md；⑤可测试性=新模块纯函数最易挂测试（无 IO）。",
        "候选C：①存在性=`paths.py:75 FACTOR_IC_RESULT` 在册（Read 核实），但 factor_ic 写侧是否有可插入聚合的接缝**未实测确认**；②重复实现=无；③影响面=`codegraph impact FACTOR_IC_RESULT` 输出 7 个受影响符号，跨 factor_ic 与 summary 两模块；④硬规则=数据契约变更需 schema 迁移、跨模块改动触发 H8，改动面估 3 文件约 120 行；⑤可测试性=需构造 parquet fixture，接缝成本高。",
        "三态标注：候选A=可行（出处见上，全部经 Read/codegraph/Bash 核实）；候选B=可行（同上）；候选C=**假设**（置信度中——写侧接缝未实测；错误时影响=若无接缝则须改 factor_ic 写侧并做 schema 迁移，改动面从 3 文件扩到 5+ 文件、H9 需分解）。无证伪剔除项。重复造轮子检查三候选均已跑 codegraph，无同功能既有实现。",
    ],
}

# ---- 子4 clean：Pugh 矩阵 + 双向追溯 + 条件红队 + 提案 ----
S4_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "DesignSolution",
    "sub_step": 4,
    "skill": "推理(Pugh 矩阵) / Agent(条件红队)",
    "purpose": "评估收敛与选型提案：Pugh 矩阵（判据=验收包承接度+改动面+影响面+复用度+可测试性+硬规则兼容，datum=最小改动候选），逐格 +/S/− 附理由且理由引子3 核验事实；双向追溯（每要素回溯 ≥1 must 目标防镀金、每 must 目标 ≥1 要素承接防漏）；条件红队（分差小或跨模块时触发）；产出排序+推荐提案，只提案不拍板留子6 裁决。",
    "q": [
        "Pugh 矩阵 datum 与六判据逐格评分及理由是什么？",
        "双向追溯两向逐项结果如何？",
        "条件红队触发了吗，输出如何留痕？",
        "排序与推荐提案是什么？",
    ],
    "a": [
        "datum=候选A（子3 核验其改动面最小：1 文件约 30 行）。逐格评分（A=datum 全 S）：\n"
        "候选B：验收包承接度 S（与 A 同样产出条数+占比两数字，子3 未见承接差异）；改动面 −（子3 实测 2 文件约 60 行 vs A 的 1 文件 30 行）；影响面 S（子3 `codegraph impact` 同为 3 个受影响符号，新模块无 callers）；复用度 −（子3 记 A 复用 `formatters.py:92 format_percentage`，B 新建模块不复用既有渲染函数）；可测试性 +（子3 记 B 新模块纯函数无 IO、最易挂测试；A 需在 sections.py 既有接缝上挂）；硬规则兼容 −（子3 记 B 跨 2 文件触发 H8 需 design.md，A 无需）。净分 −2。\n"
        "候选C：验收包承接度 S（同样产出两数字）；改动面 −（子3 估 3 文件约 120 行，假设不成立时扩到 5+ 文件）；影响面 −（子3 `codegraph impact FACTOR_IC_RESULT` 输出 7 个受影响符号、跨 factor_ic 与 summary 两模块 vs A 的 3 符号单侧）；复用度 −（不复用 `format_percentage`，须新写计算侧聚合）；可测试性 −（子3 记需构造 parquet fixture、接缝成本高）；硬规则兼容 −（子3 记数据契约变更需 schema 迁移 + 跨模块触发 H8，H9 需分解）。净分 −5。",
        "双向追溯逐项：backward（每方案要素回溯 must 目标，防镀金）——要素「正 IC 条数聚合」→G1（能基于正 IC 因子规模决定筛选门槛）；要素「占比渲染复用 format_percentage」→G1；要素「报告区块内呈现」→G2（不新增图表、只在既有报告读到数字）。无回溯不到目标的要素（无镀金项）。forward（每 must 目标 ≥1 要素承接，防漏）——G1←「正 IC 条数聚合」+「占比渲染」两要素承接；G2←「报告区块内呈现」要素承接。自述 must 目标集={G1,G2}，两向均无漏项。",
        "条件红队：触发条件写死=候选分差小（净分差 ≤1）或领先方案改动跨模块。本轮领先方案=候选A，改动不跨模块且与次优净分差 2（>1）——按触发条件**未触发**，留痕本条即为未触发记录（触发条件与实际取值：净分差=2、跨模块=否）。另因候选C 跨模块且带假设，对 C 单独跑了一次独立上下文 Agent 攻击并原文收录其输出：「攻击结论：候选C 的『写侧有可插入接缝』假设若不成立，schema 迁移会波及 factor_ic 全部消费方（impact 7 符号），且回滚需重跑 IC 计算；建议若选 C 须先实测接缝。四态 verdict=成立（该风险真实存在，非稻草人）。」",
        "排序（按净分）：候选A（0，datum）> 候选B（−2）> 候选C（−5）。**推荐提案**=候选A，理由=子3 核验事实（改动面最小 1 文件 30 行、影响面 3 符号单侧、复用既有 format_percentage、无 H8 触发）。本排序与推荐**均为提案**，权重（本轮按改动面与影响面优先）与选型待子6 用户裁决——Pugh 单人权重偏见须由用户认可，模型不替用户拍板；候选C 的假设是否接受同留子6。",
    ],
}

S4_CLEAN = copy.deepcopy(S4_BASE)

# ---- vio1：评分理由空泛不引子3 事实（单点越界：只换逐格理由）----
S4_VIO1 = copy.deepcopy(S4_BASE)
S4_VIO1["a"][0] = (
    "datum=候选A（改动最小）。逐格评分（A=datum 全 S）：\n"
    "候选B：验收包承接度 S（差不多）；改动面 −（比 A 复杂一些）；影响面 S（没什么区别）；"
    "复用度 −（复用得少）；可测试性 +（测起来更容易）；硬规则兼容 −（规矩上麻烦点）。净分 −2。\n"
    "候选C：验收包承接度 S（差不多）；改动面 −（改得比较多）；影响面 −（面比较大）；"
    "复用度 −（基本不复用）；可测试性 −（不太好测）；硬规则兼容 −（风险高）。净分 −5。"
)

# ---- vio2：替用户拍板（单点越界：只换结论段口吻）----
S4_VIO2 = copy.deepcopy(S4_BASE)
S4_VIO2["a"][3] = (
    "排序（按净分）：候选A（0，datum）> 候选B（−2）> 候选C（−5）。**最终选定候选A**，"
    "理由=子3 核验事实（改动面最小 1 文件 30 行、影响面 3 符号单侧、复用既有 format_percentage、"
    "无 H8 触发）。评估权重已确定为改动面与影响面优先，选型就这么执行、无需再问用户；"
    "候选C 的假设一并判定为不接受，直接剔除。"
)

# ---- vio3：推荐与净分矛盾=凑结论（judge 判面；单点越界：只换推荐的候选）----
# 净分与逐格计数保持自洽（算术面归 vio5 的 mech 墙）——本载荷只测残留语义面：
# 矩阵净分 A(0)>B(−2)>C(−5) 却推荐净分最低的 C 且无任何理由。
S4_VIO3 = copy.deepcopy(S4_BASE)
S4_VIO3["a"][3] = (
    "排序（按净分）：候选A（0，datum）> 候选B（−2）> 候选C（−5）。**推荐提案**=候选C。"
    "本排序与推荐均为提案，权重与选型待子6 用户裁决；候选C 的假设是否接受同留子6。"
)

# ---- vio4：双向追溯漏项（mech 生产墙；单点越界：只删 forward 的 G2 承接）----
S4_VIO4 = copy.deepcopy(S4_BASE)
S4_VIO4["a"][1] = (
    "双向追溯逐项：backward（每方案要素回溯 must 目标，防镀金）——要素「正 IC 条数聚合」→G1"
    "（能基于正 IC 因子规模决定筛选门槛）；要素「占比渲染复用 format_percentage」→G1；"
    "要素「报告区块内呈现」→G1。无回溯不到目标的要素（无镀金项）。"
    "forward（每 must 目标 ≥1 要素承接，防漏）——G1←「正 IC 条数聚合」+「占比渲染」"
    "+「报告区块内呈现」三要素承接。自述 must 目标集={G1,G2}。"
)

# ---- vio5：净分与逐格计数不符（mech 生产墙；单点越界：只改 B 的净分数值）----
S4_VIO5 = copy.deepcopy(S4_BASE)
S4_VIO5["a"][0] = S4_BASE["a"][0].replace("净分 −2。", "净分 +3。")
S4_VIO5["a"][3] = (
    "排序（按净分）：候选B（+3）> 候选A（0，datum）> 候选C（−5）。**推荐提案**=候选B，"
    "理由=净分最高。本排序与推荐均为提案，权重与选型待子6 用户裁决。"
)

CASES = {
    "clean": S4_CLEAN,
    "vio1_理由空泛不引事实": S4_VIO1,
    "vio2_替用户拍板": S4_VIO2,
    "vio3_推荐与净分矛盾": S4_VIO3,
    "vio4_追溯漏项_mech墙": S4_VIO4,
    "vio5_净分与计数不符_mech墙": S4_VIO5,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {
        k: "\n".join(json.dumps(t, ensure_ascii=False) for t in (S1, S2, S3, s4))
        for k, s4 in CASES.items()
    }
    run_cases("p:1#4 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
