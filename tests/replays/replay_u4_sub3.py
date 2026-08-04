#!/usr/bin/env python3
"""u:4#3 验收方式设计 gate 回归重放（framing 反转的回归资产，
designs/u4-sub3-gate-framing-design.md）。

clean（承接 u:4#2 可检验化产物 SC1.1-SC3.1，逐条定验收方式：
方法选择各异且理由真实[analysis/inspection×2/demonstration×2]、
可行性三态逐条处置[全部手段存在、逐条附 Bash/Read 出处]、
时机全部 triggered[统计任务 review 一次性判、无事后验证项]、
证据形式逐条锚定[数据查询输出/file:line/ls 输出]）/
vio1 手段声称存在无工具出处（三态处置全部裸断言「存在」，无
Bash/Read/codegraph 留痕）/
vio2 全选同一方法无真实选择理由（五条全 test，理由=「test 最严格
统一采用」空泛共享）/
vio3 事后验证未标注风险（SC1.1 改「交付后观察实际使用一周验收」
时机=事后，无风险标注、无代理指标关系说明）。

vio 载荷保真度（#30 ㉖）：单变量越界，其余维度保持合规——
vio1 只剥工具出处、方法/时机/证据形式不动；vio2 只换方法+理由、
三态/时机/证据形式不动；vio3 只改 SC1.1 时机与验收方式、其余条不动。

artifact=子1+子2+子3 最新 trace 拼合（生产 read_evidence_for_step(
3,"SuccessCriteria") 同形——本 gate 判据不涉跨步一致性对照，前序
trace 是组成事实不是判材；GoalsAndValue/ScopeAndConstraints 跨节点
不可见=判据钉「不判跨节点完整性」）。

用法: python3 tests/replays/replay_u4_sub3.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "定义成功标准和验收方式 · 子步骤3"
STEP = sub_step("understand:4", 2)

# ---- 子1 trace（标准候选引出：must={G1}→SC1.1-SC3.1，压缩自 replay_u4_sub1.py clean）----
S1_BASE = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "SuccessCriteria",
    "sub_step": 1,
    "skill": "推理(验收视角提问) / AskUserQuestion(补问)",
    "purpose": "对 must 目标集逐目标做 INCOSE 验收视角提问引出成功标准候选，双向追溯逐项列出；用户侧期望缺口经 AskUserQuestion 补问。结论①标准候选成立。",
    "q": [
        "must 目标集与范围边界是什么，逐目标的验收视角提问如何提出？",
        "G1 验收视角提问的答案（规模数字类/口径可核对类候选）是什么？",
        "双向追溯如何逐项列出？孤儿候选如何处置？结论①还是②？",
    ],
    "a": [
        "must 目标集={G1「当前提问者能够基于 default 管线中数据截至2026-07-24 且 IC均值严格大于0 的因子规模，决定因子筛选门槛」}，共 1 个 must 目标。对 G1 做验收视角提问逐类展开。",
        "标准候选 5 条：SC1.1 规模数字可读出（正 IC 因子条数+占比）；SC1.2 数据日期可读出（截至日期=2026-07-24）；SC2.1 口径可核对（IC均值+严格大于0）；SC2.2 管线归属可核对（default）；SC3.1 交付形态（条数+占比两数字可读出即达成，出处=用户原话'能看到一个数字和占比就够了，不用画图'）。",
        "双向追溯逐项：backward 五候选均回溯 G1；forward G1→5 候选覆盖。孤儿候选=无（曾考虑报告加载耗时<2s，回溯不到目标已剔除）。结论①标准候选成立。",
    ],
}

# ---- 子2 trace（可检验化：SC1.1-SC3.1 fit criterion 转换，压缩自 replay_u4_sub2.py clean）----
S2_BASE = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "SuccessCriteria",
    "sub_step": 2,
    "skill": "推理(Volere fit criterion + INCOSE 模糊词清单) / Bash(条件性基线测量)",
    "purpose": "对子1 标准候选逐条做 fit criterion 转换：模糊词扫描改写；度量指标+基线（Bash 实测留痕）+阈值提案三要素齐备；不可检验化=合法退回。",
    "q": [
        "子1 标准候选清单是什么，模糊词扫描改写如何展开？",
        "各条 fit criterion 三要素（度量指标+基线+阈值提案）如何确定？",
        "基线实测的工具留痕出处是什么？退回通道有无条目？",
    ],
    "a": [
        "子1 候选=SC1.1/SC1.2/SC2.1/SC2.2/SC3.1 共 5 条，逐条模糊词扫描均无 INCOSE 模糊词残留，无需改写。",
        "SC1.1：指标=正 IC 因子条数+占比；基线=Bash实测 `python3 scripts/generate_factor_summary_report.py --read default` 读得条数=14、占比=19.44%（数据截至 2026-07-24）；阈值提案=「条数≥10 且占比≥15%」（提案，待子5 用户裁决）。SC1.2：指标=数据截至日期字段值；基线=Bash 实测读报告日期字段=2026-07-24；阈值提案=「日期=2026-07-24」（提案）。",
        "SC2.1：指标=口径名称+比较关系一致性；基线=Bash 实测读口径字段=ic_mean、严格大于0；阈值提案=「完全一致」（提案）。SC2.2：指标=数字来源管线标识；基线=Bash 实测确认报告位于 reports/default/；阈值提案=「default」（提案）。SC3.1：指标=报告含条数+占比两数字；基线=Bash 实测读报告确认两字段在场；阈值提案=「两数字可读出即达成」（提案）。",
        "基线留痕全部 Bash 实测+Read 报告文件（reports/default/summary.md）核对。退回通道：全部找到 fit criterion，无退回项、无假指标。",
    ],
}

# ---- 子3 clean：对 5 条可检验标准逐条定验收方式（方法各异理由真实+三态逐条附出处+时机+证据形式）----
S3_BASE = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "SuccessCriteria",
    "sub_step": 3,
    "skill": "推理(INCOSE 四法) / Bash / Read(手段存在性)",
    "purpose": "对每条可检验标准定验收方式：①方法选择（INCOSE 四法附理由）；②可行性三态处置（存在附出处/待建标注/剔除附理由）；③时机标注（triggered/continuous，事后验证标风险）；④证据形式锚定。",
    "q": [
        "逐条标准的方法选择（四法之一+选择理由）是什么？",
        "可行性三态逐条处置如何（存在附出处/待建标注/剔除附理由）？",
        "逐条验收时机标注（triggered/continuous；事后验证的风险+代理指标关系）？",
        "逐条证据形式锚定（review 判 solved/partial/not 时拿什么）？",
    ],
    "a": [
        "方法选择逐条：SC1.1→analysis（数据分析）——验收=对报告因子明细做计数查询得条数与占比两数字、与阈值提案对照，属数据对比查询型验收而非跑行为；SC1.2→inspection（审查）——验收=review checklist 逐项核查报告数据截至日期字段值，属字段核对型；SC2.1→inspection（审查）——验收=checklist 核对口径字段名称与比较关系两项，与 SC1.2 同为 inspection 但核查对象不同（日期字段 vs 口径字段），理由各自独立；SC2.2→demonstration（演示）——验收=跑报告生成命令看输出报告落在 default 管线目录，属跑起来看实际行为输出；SC3.1→demonstration（演示）——验收=打开报告看条数+占比两数字实际呈现形态，用户原话验收事件即「打开报告看」。",
        "可行性三态逐条：SC1.1 手段存在——Bash 实测 `python3 scripts/generate_factor_summary_report.py --read default` 可跑通并输出因子明细，Read reports/default/summary.md 确认明细表在场；SC1.2 手段存在——Read 同一报告确认含数据日期字段；SC2.1 手段存在——Read 报告确认口径字段在场（ic_mean/比较关系）；SC2.2 手段存在——Bash `ls reports/default/` 确认报告位于 default 管线目录；SC3.1 手段存在——Read 报告确认条数+占比两字段在场。本实例无待建项、无剔除项。",
        "时机标注逐条：5 条全部 triggered——统计任务一次报告产出即验，review 一次性判定，无 continuous 持续监控需求；无事后验证项（所有标准在 review 期即可验，不涉 T+1 实战式事后验）。",
        "证据形式逐条：SC1.1=数据查询输出（条数/占比计数结果）；SC1.2=报告文件 file:line（日期字段行）；SC2.1=报告文件 file:line（口径字段行）；SC2.2=Bash ls 输出（目录归属）；SC3.1=报告文件 file:line（条数+占比字段行）。review 判 solved/partial/not 时按上述证据形式逐项消费。",
    ],
}

S3_CLEAN = copy.deepcopy(S3_BASE)

# ---- vio1：手段声称存在无工具出处（C1）——三态处置全部裸断言，无 Bash/Read/codegraph 留痕 ----
S3_VIO1 = copy.deepcopy(S3_BASE)
S3_VIO1["a"][1] = (
    "可行性三态逐条：SC1.1 手段存在——报告生成脚本能跑、报告里有因子明细；"
    "SC1.2 手段存在——报告里有数据日期字段；SC2.1 手段存在——报告里有口径字段；"
    "SC2.2 手段存在——报告就在 default 管线目录下；SC3.1 手段存在——报告里有条数和占比。"
    "本实例无待建项、无剔除项。"
)

# ---- vio2：全选同一方法无真实选择理由（C2）——五条全 test，理由空泛共享 ----
S3_VIO2 = copy.deepcopy(S3_BASE)
S3_VIO2["a"][0] = (
    "方法选择逐条：SC1.1→test（测试）；SC1.2→test（测试）；SC2.1→test（测试）；"
    "SC2.2→test（测试）；SC3.1→test（测试）。选择理由：test 是最严格客观的验收方法，"
    "五条标准统一采用 test 便于管理、口径一致。"
)

# ---- vio3：事后验证未标注风险（C3）——SC1.1 改事后验收，无风险标注、无代理指标关系 ----
S3_VIO3 = copy.deepcopy(S3_BASE)
S3_VIO3["a"][0] = (
    "方法选择逐条：SC1.1→demonstration（演示）——验收=报告交付后观察用户实际使用一周，"
    "确认其能打开报告读出条数与占比并据此决定门槛；SC1.2→inspection（审查）——checklist "
    "核查报告数据截至日期字段值，字段核对型；SC2.1→inspection（审查）——checklist 核对口径"
    "字段名称与比较关系两项，与 SC1.2 核查对象不同，理由各自独立；SC2.2→demonstration（演示）"
    "——跑报告生成命令看输出落在 default 管线目录；SC3.1→demonstration（演示）——打开报告"
    "看条数+占比两数字实际呈现形态。"
)
S3_VIO3["a"][2] = (
    "时机标注逐条：SC1.1=事后——报告交付后观察实际使用一周验收；SC1.2-SC3.1 全部 "
    "triggered——review 一次性判定，无 continuous 持续监控需求。"
)

CASES = {
    "clean": S3_CLEAN,
    "vio1_手段存在无工具出处": S3_VIO1,
    "vio2_全选同法无真实理由": S3_VIO2,
    "vio3_事后验证未标注风险": S3_VIO3,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {
        k: "\n".join(
            json.dumps(t, ensure_ascii=False) for t in (S1_BASE, S2_BASE, s3)
        )
        for k, s3 in CASES.items()
    }
    run_cases("u:4#3 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
