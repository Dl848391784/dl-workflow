#!/usr/bin/env python3
"""u:4#1 成功标准引出 gate 回归重放（v2.93 反转的回归资产，
designs/u4-sub1-gate-framing-design.md）。

clean（INCOSE 验收视角提问逐目标具体化 + 候选带度量对象 + 双向追溯逐项 +
结论①逐句出处 + 推测另列）/
vio1 空泛复述（「统计更准确」「体验更好」无度量对象）/
vio2 追溯放水（脑补候选挂零概念重叠目标——README 文档结构评分挂 IC 统计目标）/
vio3 ②偷懒（申报「只能定性验收」但缺逐目标理由/理由未说明为何不可执行验证）/
vio4 solutioneering 残留（候选主语=实现侧名词「新增的 factor_ic_summary.py 脚本」）/
vio5 结论无出处推断（推断混入结论正文、未标「推测」另列）。

artifact=子1 单条 trace JSON（生产 read_evidence_for_step(1,"SuccessCriteria") 同形——
子1 是本节点首步，minor_stage 过滤后无前序拼合，无跨子步串号面；
must 目标集在 GoalsAndValue.step4 + 范围约束在 ScopeAndConstraints.step4，
**两个 minor_stage 均跨节点**、judge 判材内不可见=判据须钉「不判完整性」）。

用法: python3 tests/replays/replay_u4_sub1.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "定义成功标准和验收方式 · 子步骤1"
STEP = sub_step("understand:4", 0)

# ---- clean：承接 demo 因子 IC 统计场景（must 目标集={G1}），验收视角逐目标具体化 ----
BASE = {
    "kind": "skill-trace",
    "major_stage": "Understand",
    "minor_stage": "SuccessCriteria",
    "sub_step": 1,
    "skill": "推理(验收视角提问) / AskUserQuestion(补问)",
    "purpose": "对 GoalsAndValue 子4 归一化 must 目标集逐目标做 INCOSE 验收视角提问「怎么知道它达成了」引出成功标准候选，双向追溯逐项列出；用户侧期望缺口经 AskUserQuestion 补问。结论选择①标准候选成立。",
    "q": [
        "must 目标集与范围边界是什么，逐目标的验收视角提问如何提出？",
        "G1 验收视角提问「怎么知道它达成了」的答案（规模数字类候选）是什么？",
        "G1 验收视角提问的答案（口径可核对类候选）是什么？",
        "用户侧期望（「什么结果你会满意」）缺口如何补问？",
        "双向追溯如何逐项列出（目标→候选、候选→目标）？",
        "孤儿候选如何处置？",
        "结论①标准候选成立还是②目标只能定性验收？",
    ],
    "a": [
        "GoalsAndValue 子4 归一化陈述给出的 must 目标集={G1「当前提问者能够基于 default 管线中数据截至2026-07-24 且 IC均值严格大于0 的因子规模，决定因子筛选门槛」}，共 1 个 must 目标；ScopeAndConstraints 子4 陈述给出 in 侧=既有报告只读核对、out 侧=不改后端聚合逻辑。对 G1 做验收视角提问：「验收当天我坐下来，拿什么看就知道『提问者已能基于该口径因子规模决定门槛』达成了？」逐类展开见下两条。",
        "SC1.1 规模数字可读出：验收事件=打开 default 管线最新报告，能读出「IC均值严格大于0 的因子条数」与「占全部因子的百分比」两个数字，且两数字与报告内因子明细逐条计数一致。度量对象=正 IC 因子条数、占比百分比。出处=用户已确认问题陈述「想知道有多少因子 IC 是正的」+ 会话事实（报告含因子明细表）。SC1.2 数据日期可读出：同一报告页面能读出该批数字对应的数据截至日期，验收时可确认其等于 2026-07-24。度量对象=数据截至日期字段值。出处=用户已确认口径「数据截至2026-07-24」。",
        "SC2.1 口径可核对：验收事件=拿报告 IC 口径与用户口述口径对照，能确认所用 IC 是「IC均值」而非单期 IC 或 IR，且比较关系是严格大于 0（不含等于 0）。度量对象=IC 口径名称与比较关系两项与用户口径的一致性。出处=用户已确认问题陈述「IC均值严格大于0」。SC2.2 管线归属可核对：验收事件=能确认数字取自 default 管线而非其它管线目录。度量对象=数字来源管线标识与 default 的一致性。出处=用户已确认口径「default 管线」。",
        "用户侧期望缺口=「什么结果你会满意」在上下文无原话。经 AskUserQuestion 补问「拿到什么形态的结果你会认为这件事做完了」，用户原话（AskUserQuestion 选中）：'能看到一个数字和占比就够了，不用画图'。据此 SC1.1 保留「条数+占比」两数字为验收对象，并记 SC3.1 交付形态：验收不要求图表呈现，数字与占比可读出即算达成。出处=上述用户原话。",
        "双向追溯逐项：backward（每候选回溯目标）——SC1.1→G1（提供 G1 所需的『因子规模』数字本体）；SC1.2→G1（承接 G1 的数据截至日期口径）；SC2.1→G1（承接 G1 的 IC均值严格大于0 口径）；SC2.2→G1（承接 G1 的 default 管线口径）；SC3.1→G1（承接 G1 的『据此决定门槛』所需最小交付形态，来自用户原话）。forward（每 must 目标 ≥1 候选）——G1→SC1.1+SC1.2+SC2.1+SC2.2+SC3.1，共 5 条候选覆盖，无需走「纯定性目标+理由」通道。",
        "孤儿候选=无：上述 5 条均回溯到 G1，无候选悬空。曾考虑「报告页面加载耗时 < 2s」一条，因回溯不到任何 must 目标（G1 不含性能诉求、ScopeAndConstraints out 侧亦排除改后端）已当场剔除，不进候选清单。",
        "结论①标准候选成立：唯一 must 目标 G1 已做验收视角提问并引出 5 条标准候选（SC1.1/SC1.2/SC2.1/SC2.2/SC3.1），每条含度量对象，双向追溯逐项列出且无孤儿。逐句出处：规模与日期类出处=用户已确认问题陈述口径；口径核对类出处=用户已确认口径原文；交付形态类出处=AskUserQuestion 选中原话'能看到一个数字和占比就够了，不用画图'。推测（另列，不纳入候选清单）：用户可能还希望看到按行业分组的正 IC 因子分布——本条无用户原话支撑，标「推测」留子5 读回时由用户裁决是否补为标准。",
    ],
}

CLEAN = copy.deepcopy(BASE)

# vio1 空泛复述（C1）：候选无度量对象，「统计更准确」「体验更好」式
VIO1 = copy.deepcopy(BASE)
VIO1["a"][1] = (
    "SC1.1 统计更准确：验收时能看出统计结果比以前准确。SC1.2 数据更新：数据是新的。"
)
VIO1["a"][2] = "SC2.1 口径对：IC 口径用得对。SC2.2 体验好：看报告的体验更好、更顺畅。"
# 追溯/孤儿处置保持合规（单变量：只在「度量对象缺失」上越界，#30 ㉖ 保真度前移）
VIO1["a"][4] = (
    "双向追溯逐项：backward——SC1.1→G1（提供 G1 所需的统计结果本体）；SC1.2→G1（承接 G1 的"
    "数据新鲜度口径）；SC2.1→G1（承接 G1 的 IC 口径）；SC2.2→G1（承接 G1 的报告使用体验）；"
    "SC3.1→G1（承接 G1 所需最小交付形态，来自用户原话）。"
    "forward——G1→SC1.1+SC1.2+SC2.1+SC2.2+SC3.1，共 5 条候选覆盖。"
)
VIO1["a"][5] = (
    "孤儿候选=无：上述 5 条均回溯到 G1，无候选悬空。曾考虑「报告页面加载耗时 < 2s」一条，"
    "因回溯不到任何 must 目标已当场剔除，不进候选清单。"
)
VIO1["a"][6] = (
    "结论①标准候选成立：G1 已做验收视角提问并引出 5 条标准候选（统计更准确/数据更新/"
    "口径对/体验好/交付形态），双向追溯逐项列出且无孤儿。逐句出处：前四条出处=用户已确认"
    "问题陈述；交付形态类出处=AskUserQuestion 选中原话'能看到一个数字和占比就够了，不用画图'。"
)

# vio2 追溯放水（C2）：脑补候选挂零概念重叠目标（README 文档结构评分 vs IC 统计）
VIO2 = copy.deepcopy(BASE)
VIO2["a"][2] = (
    "SC2.1 仓库 README 文档结构清晰度评分 ≥ 4/5：验收事件=按可读性 checklist 逐项打分，"
    "README 章节层级得分不低于 4 分。度量对象=README 结构清晰度评分。"
    "SC2.2 代码注释覆盖率 ≥ 60%：验收事件=统计注释行占比。度量对象=注释行占比百分比。"
)
VIO2["a"][4] = (
    "双向追溯逐项：backward——SC1.1→G1（提供因子规模数字）；SC1.2→G1（承接数据日期口径）；"
    "SC2.1→G1（README 结构清晰有助于提问者理解因子规模，支撑其决定门槛）；"
    "SC2.2→G1（注释覆盖率高使因子规模口径更可信，支撑门槛决策）；SC3.1→G1（交付形态）。"
    "forward——G1→SC1.1+SC1.2+SC2.1+SC2.2+SC3.1，共 5 条候选覆盖。"
)
VIO2["a"][6] = (
    "结论①标准候选成立：唯一 must 目标 G1 已做验收视角提问并引出 5 条标准候选，"
    "每条含度量对象，双向追溯逐项列出且无孤儿。逐句出处：规模与日期类出处=用户已确认"
    "问题陈述口径；README 与注释类出处=会话事实（仓库现状）；交付形态类出处="
    "AskUserQuestion 选中原话'能看到一个数字和占比就够了，不用画图'。"
)

# vio3 ②偷懒（C3）：申报「只能定性验收」但缺逐目标理由/理由未说明为何不可执行验证
VIO3 = copy.deepcopy(BASE)
VIO3["q"] = [
    "must 目标集是什么，逐目标的验收视角提问如何提出？",
    "标准候选清单是什么？",
    "结论①标准候选成立还是②目标只能定性验收？",
]
VIO3["a"] = [
    "must 目标集={G1「当前提问者能够基于 default 管线中数据截至2026-07-24 且 "
    "IC均值严格大于0 的因子规模，决定因子筛选门槛」}，共 1 个 must 目标。",
    "标准候选清单=空。G1 讲的是「提问者能决定门槛」，这是人的主观判断，没法定量。",
    "结论②目标只能定性验收：G1 属于主观感受类目标，只能定性验收——"
    "由提问者自己觉得够用即算达成。",
]
VIO3["purpose"] = "对 must 目标集引出成功标准候选。结论选择②目标只能定性验收。"

# vio4 solutioneering 残留（C4）：候选主语=实现侧名词
VIO4 = copy.deepcopy(BASE)
VIO4["a"][1] = (
    "SC1.1 新增的 factor_ic_summary.py 脚本能输出正 IC 因子条数：验收事件=运行该脚本，"
    "stdout 打印条数与占比。度量对象=脚本 stdout 的条数字段。"
    "SC1.2 IcStatsRenderer 类的 render_summary() 方法返回数据截至日期："
    "验收事件=调用该方法看返回值。度量对象=方法返回的日期字段。"
)
VIO4["a"][2] = (
    "SC2.1 web_ui/templates/_macros.html 的 ic_badge 宏渲染出 IC均值口径标签："
    "验收事件=打开页面看该宏输出。度量对象=宏渲染出的口径标签文本。"
    "SC2.2 data_fetchers/factor_generator.py:412 的 pipeline 参数固定为 default："
    "验收事件=Read 该行确认取值。度量对象=该行参数字面值。"
)
VIO4["a"][4] = (
    "双向追溯逐项：backward——SC1.1→G1（脚本输出因子规模数字）；SC1.2→G1（方法返回日期口径）；"
    "SC2.1→G1（宏渲染口径标签）；SC2.2→G1（参数固定 default 管线）；SC3.1→G1（交付形态）。"
    "forward——G1→SC1.1+SC1.2+SC2.1+SC2.2+SC3.1，共 5 条候选覆盖。"
)

# vio5 结论无出处推断（C5）：推断混入结论正文、未标「推测」另列
VIO5 = copy.deepcopy(BASE)
VIO5["a"][6] = (
    "结论①标准候选成立：唯一 must 目标 G1 已做验收视角提问并引出 5 条标准候选，"
    "双向追溯逐项列出且无孤儿。另外，用户既然关心正 IC 因子规模，"
    "说明他打算按 IC 正负做第一层筛选，因此标准里必须包含「筛选后因子池规模不低于 30」"
    "这一条；用户长期用 web_ui 翻报告，隐含其对新增页面接受度低，"
    "所以交付形态类标准优先级最高、其余可后置。"
)

CASES = {
    "clean": CLEAN,
    "vio1_vague_criteria": VIO1,
    "vio2_traceability_laundering": VIO2,
    "vio3_lazy_qualitative": VIO3,
    "vio4_solution_noun": VIO4,
    "vio5_unsourced_inference": VIO5,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {k: json.dumps(t, ensure_ascii=False) for k, t in CASES.items()}
    run_cases("u:4#1 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
