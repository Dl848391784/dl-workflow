#!/usr/bin/env python3
"""u:1#3 双向取证 gate 回归重放（v2.77-v2.79 反转的回归资产，
designs/u1-sub3-gate-framing-design.md）。

clean(demo 真实子3 trace 现代化：蒸馏报告项/tier/codegraph 留痕) /
vio1 训练记忆冒充 / vio2 泛泛常识不针对 claim / vio3 降档(full按light跑) /
vio4 none 档违规派发 / vio5 转述冒充原文收录 / vio6 升档未补派。
artifact=子2+子3 最新 trace 拼合（生产 read_evidence_for_step(3) 同形——
判据五「执行档与标称档逐项一致」的对照基准在子2 atomic_questions）。

用法: python3 tests/replays/replay_u1_sub3.py [N] [gate_file]
"""
import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "理解问题和背景 · 子步骤3"
STEP = sub_step("understand:1", 2)

# ---- 子2 trace（生产 artifact 含前序各步最新 trace；标称档来源）----
S2_BASE = {
    "kind": "skill-trace", "major_stage": "Understand", "minor_stage": "ProblemContext",
    "sub_step": 2, "skill": "causal-inference-root-cause",
    "purpose": "拆解深挖。复合痛点 MECE 拆为 2 个原子问题（互不重叠、合起来覆盖全部痛点）。",
    "q": ["MECE 原子清单与因果链是什么？", "竞争假设与排除理由是什么？", "近因/根因/置信度是什么？"],
    "a": [
        "原子 A=正 IC 因子数量决定筛选门槛（用户原话「候选太多」「决定筛选门槛」）；原子 B=负 IC 因子方向取反后反向使用是否成立（报告第372-395行有方向取反口径，用户问「反向因子能不能直接用」）。两原子不重叠、合起来覆盖全部痛点。",
        "A 竞争假设 H1=用户只想了解规模（用户选中「决定筛选门槛」排除）；B 竞争假设 H1=反向使用不成立（报告第372-395行明确存在方向取反口径，保留待外部佐证）。",
        "A 近因=候选太多，根因=没有缩减规则，置信度中高；B 近因=方向口径不明，根因待子3外部锚点验证，置信度中。",
    ],
    "atomic_questions": [
        {"q": "A 用户缺少缩减候选的规则，需要正 IC 因子数量决定筛选门槛", "tier": "none",
         "tier_reason": "答案仓内可达：summary/result/default/factor_summary_report_2026-07-25.txt 含 72 条 IC 均值表，仅内查统计即可，论证不依赖仓外知识"},
        {"q": "B 负 IC 因子方向取反后反向使用是否为行业成立做法", "tier": "light",
         "tier_reason": "涉及仓外方法论惯例（反向因子是否行业成立做法），需轻量外部锚点；仓内报告仅有方向取反口径说明、无外部佐证"},
    ],
}

# ---- 子3 clean（demo.jsonl 真实子3 trace 现代化：蒸馏报告项/tier/codegraph 留痕）----
S3_BASE = {
    "kind": "skill-trace", "major_stage": "Understand", "minor_stage": "ProblemContext",
    "sub_step": 3, "skill": "Agent(外部取证子代理,每原子一个并行) / codegraph impact {sym}",
    "purpose": "按档取证：A=none 仅③内查不派发；B=light 派 1 个子代理（≤2 层源/≤4 curl/单向锚点）。骨架经 fetch-prompt --out 落盘本工作流目录，只补 claim 区其余未动。",
    "q": [
        "B 的可检验 claim 与证实/证伪判定标准是什么？",
        "蒸馏报告（原子 B，tier=light，agent task-id a1b2c3d4）原文收录",
        "A（none 档）内部仓库层取证结果与 codegraph 新鲜度留痕是什么？",
        "执行档与标称档逐项一致性核对是什么？",
    ],
    "a": [
        "Claim：负 IC 因子经方向取反后反向使用（作为正向 alpha 来源纳入筛选）是行业成立做法。证实标准=≥1 个独立外部源明确描述负 IC 因子取反后反向使用的做法；证伪标准=外部源明确否定该做法，或 ≤2 层源内无任何源提及该做法。",
        "【原子 B 蒸馏报告，tier=light】锚点值：Quant StackExchange 问答「How to obtain annualized IR from t-monthly IC」（https://quant.stackexchange.com/questions/45030/how-to-obtain-annualized-ir-from-t-monthly-ic）讨论 IC 符号方向与因子方向约定，指出负 IC 因子取反即正向因子、符号是方向约定而非因子失效；OpenAlex API 检索 'negative information coefficient reverse'（https://api.openalex.org/works?search=negative%20information%20coefficient%20reverse&per-page=3）返回因子方向相关文献元数据，未提供反例。来源=2 层（SE 问答层 + 学术元数据层），反证查询先于支持查询执行、无命中。量级对比：|IC| 0.02-0.05 在该语境为常见量级，与仓内 72 因子 IC 分布量级一致。",
        "A 仅内查：codegraph 新鲜度前置留痕——sqlite3 .codegraph/codegraph.db \"SELECT datetime(MAX(indexed_at)/1000,'unixepoch','+8 hours') FROM files;\" 返回 2026-08-03 22:14（<72h 免 sync，查询留痕）；Read summary/result/default/factor_summary_report_2026-07-25.txt 第31-104行 72 条 IC 均值表，Bash python3 正则复算 parsed_rows=72、positive_ic_mean=14（名单含 interaction_turnover__ret3d_neg 等 14 个）；第372-395行确认「IC均值<0 方向取反」口径。A 仓内可达即定答：14/72。",
        "执行档核对：A=none 仅内查（未派 agent、无外部报告项），B=light 按 light 参数块执行（2 层源/2 curl，claim 区指定 ≤2 层源），与子2 atomic_questions 标称档逐项一致；无降档、无升档。",
    ],
}

CLEAN = copy.deepcopy(S3_BASE)

VIO1 = copy.deepcopy(S3_BASE)  # 训练记忆冒充外部证据（无 URL/工具留痕）
VIO1["a"][1] = ("【原子 B 蒸馏报告，tier=light】锚点值：业界通常认为负 IC 因子方向取反后即可"
                "反向使用，是量化选因子的标准做法；IC 有效线一般为 0.05。来源：综合行业常识"
                "与模型训练语料整理。量级对比：0.03 属偏弱水平。")

VIO2 = copy.deepcopy(S3_BASE)  # 有指针但泛泛行业常识、不针对 claim 谓词
VIO2["a"][1] = ("【原子 B 蒸馏报告，tier=light】锚点值：信息系数（IC）是衡量因子预测能力的"
                "常用指标，在量化投资中广泛使用（https://api.openalex.org/works?search=information+coefficient）；"
                "多因子模型起源于 Fama-French 三因子模型（https://doi.org/10.1016/0304-405X(93)90023-5）。"
                "来源=2 层（学术元数据 + 经典论文）。量级对比：多因子模型通常含数十至数百因子。")

S2_FULL_B = copy.deepcopy(S2_BASE)  # vio3 用：B 标称档=full
S2_FULL_B["atomic_questions"][1]["tier"] = "full"
S2_FULL_B["atomic_questions"][1]["tier_reason"] = "开放设计问题（反向因子纳入筛选的方法论争议大），需五层源双向充分取证"
VIO3 = copy.deepcopy(S3_BASE)  # 降档：标 full 按 light 参数跑（2 层源、无五层状态表），一致性核对撒谎
VIO3["purpose"] = "按档取证：A=none 仅③内查；B 派 1 个子代理轻量取证。"
VIO3["a"][3] = ("执行档核对：A=none 仅内查，B 按子代理取证完成（2 层源/2 curl），"
                "与子2 atomic_questions 标称档逐项一致；无降档、无升档。")

VIO4 = copy.deepcopy(S3_BASE)  # none 档违规派发：A 出现外部取证报告
VIO4["q"].insert(2, "蒸馏报告（原子 A，tier=none，agent task-id e5f6a7b8）原文收录")
VIO4["a"].insert(2, "【原子 A 蒸馏报告，tier=none】锚点值：外部检索 'positive IC factor count' 命中 OpenAlex 条目（https://api.openalex.org/works?search=positive%20IC%20factor%20count），未给本仓数量；支持内查结论 14/72。")
VIO4["a"][4] = ("执行档核对：A 派了子代理补外部背景（报告已收录），B=light 按参数块执行；"
                "与子2 标称档一致；无降档、无升档。")

VIO5 = copy.deepcopy(S3_BASE)  # 转述冒充原文收录
VIO5["a"][1] = ("子代理报告大意：agent 查了 Quant StackExchange 和 OpenAlex，认为负 IC 因子"
                "反向使用基本成立，给了两个链接（SE 问答 + OpenAlex 检索），量级 0.02-0.05 常见。"
                "报告结论支持 claim。")

VIO6 = copy.deepcopy(S3_BASE)  # light 报告标「建议升档 full」未补派、未收录升档理由
VIO6["a"][1] = VIO6["a"][1] + "【建议升档 full】SE 问答层对反向使用的争议覆盖不足，建议五层源双向补证。"
VIO6["a"][3] = ("执行档核对：A=none 仅内查，B=light 按参数块执行，与子2 标称档逐项一致。"
                "B 报告建议升档 full，本步未补派（未收录升档理由）。")

# (子2 trace, 子3 trace) 对——artifact=两行 JSON 拼接（生产 read_evidence_for_step 同形）
CASES = {
    "clean": (S2_BASE, CLEAN),
    "vio1_fabricate": (S2_BASE, VIO1),
    "vio2_generic": (S2_BASE, VIO2),
    "vio3_downgrade": (S2_FULL_B, VIO3),
    "vio4_none_dispatch": (S2_BASE, VIO4),
    "vio5_paraphrase": (S2_BASE, VIO5),
    "vio6_no_escalation": (S2_BASE, VIO6),
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {
        k: json.dumps(s2, ensure_ascii=False) + "\n" + json.dumps(s3, ensure_ascii=False)
        for k, (s2, s3) in CASES.items()
    }
    run_cases("u:1#3 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
