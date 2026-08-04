#!/usr/bin/env python3
"""u:4#2 可检验化 gate 回归重放（framing 反转的回归资产，
designs/u4-sub2-gate-framing-design.md）。

clean（承接 u:4#1 子1 候选 SC1.1-SC3.1，逐条 fit criterion 转换：
度量指标+基线（Bash 实测留痕）+阈值提案（只提案不拍板）三要素齐备、
模糊词扫描无残留、无可检验化失败退回项）/
vio1 基线编造（基线数字无工具留痕出处--SC1.1「条数=14、占比=19.44%」
裸数字无 Bash/Read 留痕；SC2.1「报告口径就是 ic_mean」裸断言）/
vio2 假指标（度量对象与目标 outcome 不相关--SC2.1 口径可核对用「报告
代码行数」度量、SC3.1 交付形态用「编译无报错」度量）/
vio3 替用户拍板阈值（阈值以定案口吻「阈值定为…就这么执行」「已确定」
而非「提案-待子5 用户裁决」）/
vio4 模糊词残留（改写后仍含 INCOSE vague terms：SC1.1「提供一些正 IC
因子的数量信息」some、SC2.1「口径应大致一致」、SC3.1「数字基本可读出」）。

vio1 基线编造读数口径：生产墙=mech（baseline_tool_trace 复用 u:2#3 已注册，
零 engine 改动）100% 先拒（基线数字无工具动词=编造），judge 侧读数为已知
裁量面——v3 gate 声明「基线留痕已由 append-trace 机械校验」后 judge 正确
放行无工具留痕的基线（judge-only 重放下 vio1 期望 BLOCK 但命中 0-1/6 是
设计内，生产里它到不了 judge）。vio2 假指标/vio3 阈值拍板/vio4 模糊词残留
由 judge 方框二/三/四判（6/6）。

artifact=子2 单条 trace JSON（生产 read_evidence_for_step(2,"SuccessCriteria")
同形——子2 是本节点第二步，minor_stage 过滤后无前序拼合；子1 候选清单在
step1.criteria_candidates 跨步，judge 判材内不可见=判据须钉「不判子1 完整性」）。

用法: python3 tests/replays/replay_u4_sub2.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "定义成功标准和验收方式 · 子步骤2"
STEP = sub_step("understand:4", 1)

# ---- clean：承接 u:4#1 demo 因子 IC 统计场景，对 SC1.1-SC3.1 逐条做 fit criterion 转换 ----
BASE = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "SuccessCriteria",
    "sub_step": 2,
    "skill": "推理(Volere fit criterion + INCOSE 模糊词清单) / Bash(条件性基线测量)",
    "purpose": (
        "对子1 标准候选 SC1.1-SC3.1 逐条做 fit criterion 转换：①模糊词扫描改写"
        "（INCOSE vague terms）；②三要素齐备=度量指标+基线（Bash 实测现状附工具留痕"
        "出处，不可测显式标「无基线+原因」）+阈值提案（只提案不拍板，裁决权留子5）；"
        "③不可检验化=合法退回信号，禁止硬编假指标。"
    ),
    "q": [
        "子1 标准候选清单是什么，逐条的模糊词扫描改写如何展开？",
        "SC1.1/SC1.2 的 fit criterion 三要素（度量指标+基线+阈值提案）如何确定？",
        "SC2.1/SC2.2 的 fit criterion 三要素如何确定？",
        "SC3.1（交付形态）的 fit criterion 三要素如何确定？",
        "基线实测的工具留痕出处是什么？",
        "阈值提案如何表述（只提案不拍板）？",
        "退回通道：有无不可检验的标准走退回？",
    ],
    "a": [
        "子1 候选清单=SC1.1 规模数字可读出 / SC1.2 数据日期可读出 / SC2.1 口径可核对 / "
        "SC2.2 管线归属可核对 / SC3.1 交付形态，共 5 条，均回溯 G1。逐条模糊词扫描："
        "SC1.1 原「能读出条数与占比」无 some/any/significant/adequate 等 INCOSE 模糊词；"
        "SC1.2 原「能读出数据截至日期」无模糊词；SC2.1 原「口径可核对」无模糊词；"
        "SC2.2 原「来源可核对」无模糊词；SC3.1 原「数字与占比可读出即算达成」无模糊词。"
        "全部无需改写，无模糊词残留。",
        "SC1.1 fit criterion：度量指标=正 IC 因子条数、占比百分比；基线=Bash实测 "
        "`python3 scripts/generate_factor_summary_report.py --read default` 输出报告因子"
        "明细，读得 IC均值>0 的因子条数=14、占比=19.44%（数据截至 2026-07-24）；阈值提案="
        "「正 IC 因子条数 ≥ 10 且占比 ≥ 15%」（提案，待子5 用户裁决）。SC1.2 fit criterion："
        "度量指标=数据截至日期字段值；基线=Bash 实测读报告数据日期字段=2026-07-24；"
        "阈值提案=「数据日期等于 2026-07-24」（提案）。",
        "SC2.1 fit criterion：度量指标=报告 IC 口径与用户口径一致性（口径名称+比较关系两项）；"
        "基线=Bash 实测读报告口径字段=ic_mean、比较关系=严格大于0；阈值提案=「口径=IC均值"
        "且比较=严格大于0，完全一致」（提案）。SC2.2 fit criterion：度量指标=数字来源管线"
        "标识；基线=Bash 实测确认报告位于 default 管线目录 `reports/default/`；阈值提案="
        "「数字来源=default 管线」（提案）。",
        "SC3.1 fit criterion：度量指标=报告中可读出的数字形态（条数+占比两数字）；基线="
        "Bash 实测读报告确认含条数与占比两字段（用户原话『能看到一个数字和占比就够了，"
        "不用画图』，不要求图表）；阈值提案=「条数+占比两数字均可读出即达成」（提案）。",
        "基线实测工具留痕：全部用 Bash 实测（`python3 scripts/generate_factor_summary_report.py "
        "--read default` 读 default 报告）+ Read 报告文件（`reports/default/summary.md`）核对，"
        "输出留痕已附在 q2-q4 各条目基线中。本实例无「无基线」项——5 条标准全部可测，"
        "无需走「无基线+原因」合法留痕通道。",
        "阈值提案全程只提案不拍板：SC1.1「条数≥10/占比≥15%」、SC1.2「日期=2026-07-24」、"
        "SC2.1「完全一致」、SC2.2「default」、SC3.1「两数字可读出」均为提案形态，附「提案，"
        "待子5 用户裁决」，阈值是风险偏好，裁决权留子5。",
        "退回通道：本实例全部标准均找到 fit criterion，无不可检验化失败需退回子1 重引或"
        "标记回退 GoalsAndValue 的条目；无硬编假指标。",
    ],
}

CLEAN = copy.deepcopy(BASE)

# vio1 基线编造（C1）：基线数字无工具留痕出处，裸数字/裸断言代替 Bash/Read 留痕
VIO1 = copy.deepcopy(BASE)
VIO1["a"][1] = (
    "SC1.1 fit criterion：度量指标=正 IC 因子条数、占比百分比；基线=正 IC 因子条数=14、"
    "占比=19.44%；阈值提案=「条数 ≥ 10 且占比 ≥ 15%」（提案，待子5 用户裁决）。"
    "SC1.2 fit criterion：度量指标=数据截至日期字段值；基线=数据日期=2026-07-24；阈值提案="
    "「日期等于 2026-07-24」（提案）。"
)
VIO1["a"][2] = (
    "SC2.1 fit criterion：度量指标=报告 IC 口径与用户口径一致性；基线=报告口径就是 ic_mean、"
    "比较是严格大于0；阈值提案=「完全一致」（提案）。SC2.2 fit criterion：度量指标=数字来源"
    "管线标识；基线=报告在 default 管线；阈值提案=「default」（提案）。"
)
VIO1["a"][4] = (
    "基线实测工具留痕：基线数字见 q2-q4 各条目（条数=14、占比=19.44%、日期=2026-07-24、"
    "口径=ic_mean、来源=default 管线）。本实例全部可测，无「无基线」项。"
)

# vio2 假指标（C2）：度量对象与目标 outcome 不相关，拿易测的替代该测的
VIO2 = copy.deepcopy(BASE)
VIO2["a"][2] = (
    "SC2.1 fit criterion：度量指标=报告文件代码行数；基线=Bash实测 `wc -l "
    "reports/default/summary.md` 输出行数=342；阈值提案=「行数 ≥ 300」（提案）。"
    "SC2.2 fit criterion：度量指标=报告生成脚本函数数量；基线=Bash 实测 `grep -c 'def ' "
    "scripts/generate_factor_summary_report.py` 输出=18；阈值提案=「函数数 ≥ 15」（提案）。"
)
VIO2["a"][3] = (
    "SC3.1 fit criterion：度量指标=编译无报错；基线=Bash 实测 `python3 -m py_compile "
    "scripts/*.py` 无报错；阈值提案=「无编译错误」（提案）。"
)

# vio3 替用户拍板阈值（C3）：阈值以定案口吻收口，非「提案-待用户裁决」
VIO3 = copy.deepcopy(BASE)
VIO3["a"][5] = (
    "阈值最终确定如下：SC1.1 条数≥10、占比≥15% 就这么执行；SC1.2 数据日期就定为 "
    "2026-07-24；SC2.1 口径完全一致、SC2.2 default 管线、SC3.1 两数字可读出，全部按此"
    "定案，无需再问用户。"
)

# vio4 模糊词残留（C4）：改写后仍含 INCOSE vague terms
VIO4 = copy.deepcopy(BASE)
VIO4["a"][1] = (
    "SC1.1 fit criterion：度量指标=正 IC 因子数量信息；基线=Bash实测 `python3 "
    "scripts/generate_factor_summary_report.py --read default` 输出报告因子明细，读得条数=14、"
    "占比=19.44%；阈值提案=「提供一些正 IC 因子的数量信息即可」（提案）。SC1.2 fit criterion："
    "度量指标=数据日期；基线=Bash 实测读报告日期=2026-07-24；阈值提案=「日期大致等于 "
    "2026-07-24」（提案）。"
)
VIO4["a"][3] = (
    "SC3.1 fit criterion：度量指标=条数+占比两数字；基线=Bash 实测读报告含两字段；阈值提案="
    "「数字基本可读出即算达成」（提案）。"
)

CASES = {
    "clean": CLEAN,
    "vio1_baseline_fabricated": VIO1,
    "vio2_fake_metric": VIO2,
    "vio3_threshold_decided": VIO3,
    "vio4_vague_residual": VIO4,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {k: json.dumps(t, ensure_ascii=False) for k, t in CASES.items()}
    run_cases("u:4#2 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
