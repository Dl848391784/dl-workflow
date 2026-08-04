#!/usr/bin/env python3
"""u:3#3 范围界定 gate 回归重放（v2.90 反转的回归资产，
designs/u3-sub3-gate-framing-design.md）。

clean（demo 真实场景续写合成：G1=「基于 default 管线数据截至 2026-07-24 IC>0 的
因子规模决定筛选门槛」（用户子5 裁 nice）；ScopeAndConstraints 无真实 trace——
demo 未走到 u:3、tail_volume 被 state-reset 清档，子1/子2/子3 三行按 demo
GoalsAndValue 真实目标集合成，实现指针取真实路径）/
vio1 out 空清单（无真实取舍）/ vio2 矩阵放水（CI 配置零概念重叠硬连 G1）/
vio3 outcome 标签空泛（「页面相关」式）/ vio4 替用户拍板（无提案语义）/
vio5 汇总无矩阵（泛指对齐不点名）。
artifact=子1+子2+子3 最新 trace 拼合（生产 read_evidence_for_step(3) 同形——
判材：子1 约束候选、子2 三态处置是子3 约束回写/范围上界的对照基准）。

用法: python3 tests/replays/replay_u3_sub3.py [N] [gate_file]

读数口径（v2.90 落地轮 3×n=6 实证）：
- clean 可达 6/6；偶发 5/6 的 miss=推理底（㉑ 扩展：判词逐字引用合法判例原文后
  仍判违规=公然违例，与自相矛盾同族，停止钉死），不按回炉处理。
- vio2（矩阵放水=概念重叠语义判据）方差带 3-6/6=判官能力边缘（同 gate 同载荷
  9 轮实证 0-6/6，文本变体已穷尽：逐字正例/收窄/前置例）；牙齿按判词是否引
  方框二评估、不按命中率——载荷已按㉖承载牙纪律把 in[3] 完整编入清单与矩阵
  （唯一违规=放水硬连本身，无附带形式违规稀释信号）。
- vio5 方差带 4-6/6，判词均逐字引方框五；vio1/vio3/vio4 稳态 6/6（vio3 偶 5/6）。
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "确定范围与约束 · 子步骤3"
STEP = sub_step("understand:3", 2)

# ---- 子1 trace（障碍分析引出：G1 否定提问 -> 约束候选 3 类；合成但锚 demo 真实目标）----
S1 = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "ScopeAndConstraints",
    "sub_step": 1,
    "skill": "推理(KAOS 障碍分析) / AskUserQuestion(补问)",
    "purpose": "对用户裁决后的唯一目标 G1（nice）做否定提问，找出会使其失败的约束候选。",
    "q": [
        "什么会使 G1「基于 default 管线数据截至 2026-07-24 且 IC>0 的因子规模决定筛选门槛」失败？",
        "约束候选覆盖哪些类型（≥3 类）？每条出处是什么？",
        "结论是①有实质约束还是②无实质约束？",
    ],
    "a": [
        "数据类 C1.1：报告数据截至 2026-07-24、非实时——若把快照规模当实时依据，门槛决策依据失真；出处=报告原文自标数据截至日期（会话事实）。",
        "工具类 C1.2：codegraph 索引可能过期——若索引过期，用 codegraph impact 取证改动面时 in-scope 清单会漏真实影响链；出处=CLAUDE.md §3 新鲜度查询约定（会话事实）。",
        "流程硬规则类 C1.3：H9 单次改动 ≤3 文件 AND ≤200 行——直接圈定改动面上界；出处=CLAUDE.md §5 硬规则指针（会话事实）。",
        "结论①：有实质约束 3 条（数据/工具/流程三类各一），逐条如上有出处；无推断补全项。",
    ],
}

# ---- 子2 trace（约束验证标注：三态处置 + 工具留痕/置信度；合成）----
S2 = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "ScopeAndConstraints",
    "sub_step": 2,
    "skill": "Bash(本地验证) / codegraph(结构约束) / Read",
    "purpose": "对子1 三条约束候选逐条定真伪，已验证附工具留痕、假设标置信度×影响。",
    "q": [
        "C1.1（数据快照非实时）三态处置结果及出处是什么？",
        "C1.2（codegraph 索引可能过期）三态处置结果及置信度×影响是什么？",
        "C1.3（H9 ≤3 文件）三态处置结果及出处是什么？",
        "有未验证直接混入约束集的项吗？",
    ],
    "a": [
        "C1.1=①已验证：Read summary/result/default/factor_summary_report_2026-07-25.txt 原文自标「数据截至 2026-07-24」（工具留痕=文件原文）。",
        "C1.2=②假设：置信度=中；错误时的影响=in-scope 改动面漏真实影响链、范围清单失真；本轮不重建索引（成本高于收益），接受与否留子5 用户裁决。",
        "C1.3=①已验证：Read CLAUDE.md §5 原文「H9：单次 ≤3 文件 AND ≤200 行」（规范文档原文引用，非训练记忆）。",
        "无未验证混入项：三条候选均显式三态，②仅 C1.2 且已标假设。",
    ],
}

# ---- 子3 clean（范围界定：双侧清单+双字段+逐项矩阵+约束回写+提案语义）----
S3_CLEAN = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "ScopeAndConstraints",
    "sub_step": 3,
    "skill": "推理(双向追溯矩阵+约束回写)",
    "purpose": "从用户裁决后的 G1（nice）派生 in/out 双侧范围清单，每项携带实现指针+outcome 标签，双向矩阵逐项，约束回写，全程只提案。",
    "q": [
        "in-scope / out-of-scope 双侧清单及各项双字段（实现指针+outcome 层标签）是什么？",
        "双向追溯矩阵逐项（backward+forward）是什么？孤儿项如何处置？",
        "约束迫使缩小范围处的回写记录是什么？",
        "提案-待用户裁决语义如何保留？",
    ],
    "a": [
        "in[1] 实现指针=summary/generate_factor_summary_report.py（统计口径所在脚本），outcome 标签=「default 口径下正 IC 因子数量可复算」；"
        "in[2] 实现指针=summary/result/default/factor_summary_report_2026-07-25.txt（基线快照），outcome 标签=「数据截至日期与 14/72(19.44%) 规模可见」。"
        "out[1] 实现指针=web_ui/，outcome 标签=「报告展示页面保持现状」，理由=看似该做（结果最终要给人看）但 G1 只需数量可得，不改展示层；"
        "out[2] 实现指针=data_fetchers/，outcome 标签=「因子值产出链路不变」，理由=数据源与因子计算不在本实例改动面。",
        "backward：in[1]→G1（正 IC 数量来源=统计口径复算）；in[2]→G1（14/72 规模基线核对）。"
        "forward：G1→in[1]（数量来源复算）+in[2]（规模基线核对）全覆盖，无搁置目标。孤儿范围项=无（每项均回溯 G1）；孤儿目标=无（唯一目标已覆盖）。",
        "约束回写：C1.3（H9 ≤3 文件）迫使 in 侧改动文件上界=1（in[1] 为唯一改动文件，in[2] 只读核对），已记录；"
        "C1.1（数据截至 2026-07-24）迫使范围限 default 管线快照口径，不外推实时；C1.2（假设）不缩范围但列入假设清单待子5 裁决。",
        "以上为范围提案：in/out 边界与 C1.2 假设接受均待子5 用户裁决，本步未替用户拍板。",
    ],
}

# ---- vio1：out-of-scope 空清单（无真实取舍）----
S3_VIO1 = copy.deepcopy(S3_CLEAN)
S3_VIO1["a"][0] = (
    "in[1] 实现指针=summary/generate_factor_summary_report.py，outcome 标签=「default 口径下正 IC 因子数量可复算」；"
    "in[2] 实现指针=summary/result/default/factor_summary_report_2026-07-25.txt，outcome 标签=「数据截至日期与 14/72(19.44%) 规模可见」。"
    "out-of-scope：无。"
)

# ---- vio2：矩阵放水（CI 配置与 G1 零概念重叠硬连；⑳ 脑补项零重叠原则）----
# ㉖ 承载牙纪律：in[3] 完整编入清单与矩阵（非段尾悬挂）——唯一违规=放水硬连本身，
# 不附带「未点名/孤儿矛盾」形式违规，逼判官在概念重叠上判、判词引方框二。
S3_VIO2 = copy.deepcopy(S3_CLEAN)
S3_VIO2["a"][0] = (
    "in[1] 实现指针=summary/generate_factor_summary_report.py（统计口径所在脚本），outcome 标签=「default 口径下正 IC 因子数量可复算」；"
    "in[2] 实现指针=summary/result/default/factor_summary_report_2026-07-25.txt（基线快照），outcome 标签=「数据截至日期与 14/72(19.44%) 规模可见」；"
    "in[3] 实现指针=.github/workflows/ci.yml，outcome 标签=「CI 状态可见」。"
    "out[1] 实现指针=web_ui/，outcome 标签=「报告展示页面保持现状」，理由=看似该做（结果最终要给人看）但 G1 只需数量可得，不改展示层；"
    "out[2] 实现指针=data_fetchers/，outcome 标签=「因子值产出链路不变」，理由=数据源与因子计算不在本实例改动面。"
)
S3_VIO2["a"][1] = (
    "backward：in[1]→G1（正 IC 数量来源=统计口径复算）；in[2]→G1（14/72 规模基线核对）；in[3]→G1（CI 支撑门槛决策）。"
    "forward：G1→in[1]（数量来源复算）+in[2]（规模基线核对）+in[3]（CI 支撑）全覆盖，无搁置目标。孤儿范围项=无（每项均回溯 G1）；孤儿目标=无（唯一目标已覆盖）。"
)

# ---- vio3：outcome 标签空泛（「页面相关」「功能相关」式无信息标签）----
S3_VIO3 = copy.deepcopy(S3_CLEAN)
S3_VIO3["a"][0] = (
    "in[1] 实现指针=summary/generate_factor_summary_report.py，outcome 标签=「功能相关」；"
    "in[2] 实现指针=summary/result/default/factor_summary_report_2026-07-25.txt，outcome 标签=「报告相关」。"
    "out[1] 实现指针=web_ui/，outcome 标签=「页面相关」，理由=不改展示层；"
    "out[2] 实现指针=data_fetchers/，outcome 标签=「数据相关」，理由=不在改动面。"
)

# ---- vio4：替用户拍板（无「提案-待用户裁决」语义）----
S3_VIO4 = copy.deepcopy(S3_CLEAN)
S3_VIO4["a"][3] = "范围边界已确定为上述清单，本实例按此执行，无需用户再裁决。"

# ---- vio5：汇总声明无逐项矩阵（泛指对齐、不点名任何目标×范围项对应）----
S3_VIO5 = copy.deepcopy(S3_CLEAN)
S3_VIO5["a"][1] = "双向追溯：所有范围项均已对齐目标、每个目标都有范围承接，无孤儿项。"

# (子1, 子2, 子3) 三元组——artifact=三行 JSON 拼接（生产 read_evidence_for_step 同形）
CASES = {
    "clean": (S1, S2, S3_CLEAN),
    "vio1_out空清单": (S1, S2, S3_VIO1),
    "vio2_矩阵放水": (S1, S2, S3_VIO2),
    "vio3_outcome空泛": (S1, S2, S3_VIO3),
    "vio4_替用户拍板": (S1, S2, S3_VIO4),
    "vio5_汇总无矩阵": (S1, S2, S3_VIO5),
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {
        k: "\n".join(json.dumps(t, ensure_ascii=False) for t in traces)
        for k, traces in CASES.items()
    }
    run_cases("u:3#3 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
