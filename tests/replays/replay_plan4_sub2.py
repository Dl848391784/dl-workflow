#!/usr/bin/env python3
"""plan:4#2 调度与检查点方案 gate 回归重放（framing 反转的回归资产，
designs/plan4-sub2-gate-framing-design.md）。

**plan:4（制定执行计划和检查点）第二个反转节点**。命题性质=方案提案
（只提案不拍板，密度与类型归子5 用户裁决），主敌=「方案形式失守」——
虚设判据/即兴路由/拍脑袋分组/无验收门/逃避论证/越权拍板六族。

判面归位（㉒ 同族）：判据可执行性 dry-run / 互斥面交集实算 / 锚点存在性
核验归子3 锚点核验——本步只判方案文本形态齐备+形式合规，不判命令真实
可跑、不判交集实算结果、不判任务 ID 真实存在（四源文件 judge 结构性读
不到）。

clean（承接子1 四源清点 T1/T2/T3+SC1/SC2：调度四件齐[拓扑分层 L1={T1}
L2={T2,T3}+互斥面从改动点字段计算附文件清单交集=∅+worker 映射+返回契约
含测试输出/文件清单/file:line 证据形式]、两检查点三属性齐[零判断词判据
命令+退出码承接 SC ID/三选一预定义失败路由/类型含不可逆前用户暂停]、
goal anchoring 逐检查点两成分、密度论证按可逆性×爆炸半径逐检查点给类型
建议、红队条件未触发声明附计数、只提案不拍板）/
vio1 虚设判据（CP1 通过判据含「确认…合理」「检查…无问题」判断词）/
vio2 即兴路由（CP2 失败路由=「视情况处理」）/
vio3 拍脑袋分组（互斥面=「天然不冲突」断言，无改动点文件清单交集计算）/
vio4 无验收门（返回契约只「返回执行结果与说明」，缺证据形式清单）/
vio5 逃避论证（检查点类型裸列，无密度论证也无复利论证）/
vio6 越权拍板（「密度与类型定为上述方案按此执行」，替用户裁决）。

vio 载荷保真度（#30 ㊷）：单概念越界，其余维度保持合规——vio1 只换 CP1
判据行；vio2 只换 CP2 失败路由行；vio3 只换 a[0] 互斥面段；vio4 只换 a[0]
返回契约段；vio5 只换 a[2] 密度论证段；vio6 只换 a[4] 拍板声明确认为拍板。

artifact=子1+子2 最新 trace 拼合（生产 read_evidence_for_step(2,
"ExecutionPlanCheckpoints") 同形——子1 四源清点 trace 为组成事实+出处对照
面；plan.md/design.md/understand.md 主仓 .md 文件结构性读不到=只判 trace
内自洽不核四源真值）。

用法: python3 tests/replays/replay_plan4_sub2.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "制定执行计划和检查点 · 子步骤2"
STEP = sub_step("plan:4", 1)

# ---- 子1 trace（四源清点基线：T1/T2/T3 DAG+能力绑定+SC1/SC2+假设+不可逆候选，压缩）----
S1_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "ExecutionPlanCheckpoints",
    "sub_step": 1,
    "skill": "Read(plan.md / design.md / understand.md) / Bash(grep evidence plan:1/2/3 trace)",
    "purpose": (
        "四源清点与追溯基线：控制结构输入五类清单齐备（任务 DAG 与阶段边界/"
        "能力绑定/验收包/假设清单汇总/不可逆操作候选），每条附源出处且四源"
        "原文引用进 trace 正文；只提取不创作。"
    ),
    "q": [
        "任务 DAG 与阶段边界（任务 ID/依赖/阶段分组）如何？",
        "验收包（六字段，时机=triggered 项显式标注）如何？",
        "不可逆操作候选（删改/外发/force 语义改动点）如何？",
    ],
    "a": [
        "任务 DAG 三条：T1=paths.py 新增 CATEGORY_SUMMARY_RESULT 路径常量"
        "（改 .py，无依赖，出处 plan.md:10 原文『新增 CATEGORY_SUMMARY_RESULT "
        "路径常量』）；T2=summary/generate_factor_summary_report.py "
        "_aggregate_positive_ic 增加 FACTOR_CATEGORIES 分组键（改 .py，依赖 "
        "T1 常量，出处 plan.md:12）；T3=summary/MODULE.md 更新八维度汇总区块"
        "说明（文档改动，依赖 T1 不依赖 T2，出处 plan.md:14）。拓扑分层："
        "L1={T1}，L2={T2,T3}（同层无依赖可并行）。",
        "验收包两条：SC1=路径常量可导入（时机=triggered，落点=T1 完成后，"
        "understand.md:31）；SC2=报告含八维度汇总区块（时机=triggered，落点="
        "T2 完成后，understand.md:33）。",
        "不可逆操作候选一条：终态 git commit+push（外发语义，落点=全部任务"
        "完成后）；其余改动均为工作区文件改动可 git 回滚。假设清单：无新增"
        "（design.md/plan.md 假设项已在 plan:2 传导完毕）。",
    ],
}

# ---- 子2 clean：调度四件齐 + 检查点三属性齐 + goal anchoring + 密度论证 + 红队未触发 + 只提案 ----
S2_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "ExecutionPlanCheckpoints",
    "sub_step": 2,
    "skill": "Agent(条件红队——未触发，见 a[3])",
    "purpose": (
        "调度与检查点方案提案：调度四件（并行分组/文件互斥面/worker 任务包"
        "映射/返回契约）+ 检查点三属性（零判断词判据/三选一失败路由/类型）"
        "+ goal anchoring + 密度论证；只提案不拍板。"
    ),
    "q": [
        "调度四件（并行分组/文件互斥面/worker 任务包映射/subagent 返回契约）如何？",
        "检查点三属性（通过判据/失败路由/类型）与 goal anchoring 重述句如何？",
        "密度论证（可逆性×爆炸半径逐检查点类型建议）如何？",
        "红队留痕或条件未触发声明？",
        "只提案不拍板确认了吗（密度与类型待子5 用户裁决）？",
    ],
    "a": [
        "调度四件齐备：①并行分组——按子1 任务 DAG 拓扑分层：L1={T1} 先行，"
        "L2={T2,T3} 同层无依赖可并行派发；②文件互斥面——从执行包改动点字段"
        "计算：T2 改动文件清单={summary/generate_factor_summary_report.py}，"
        "T3 改动文件清单={summary/MODULE.md}，组内交集=∅（两清单无公共文件）；"
        "③worker 任务包映射——W1→T1（任务 ID T1+改动 paths.py+判据命令），"
        "W2→T2、W3→T3，每包零上下文可执行（任务 ID/文件清单/判据命令自包含）；"
        "④subagent 返回契约——每 worker 返回：pytest 等测试输出原文、实际改动"
        "文件清单、逐改动点 file:line 证据清单，三形式齐备才算交付。",
        "检查点两个，三属性齐备：CP1（T1 完成后，阶段边界）——通过判据="
        "`python3 -c \"from paths import CATEGORY_SUMMARY_RESULT\"` 退出码 0"
        "（承接 SC1）；失败路由=返工本组（W1 重做 T1）；类型=自动继续；goal "
        "anchoring=「原目标：分类维度汇总落地；当前位置：T1 路径常量完成待验」。"
        "CP2（T2/T3 完成后、git commit 前，不可逆操作前）——通过判据="
        "`pytest tests/test_summary_categories.py -x` 退出码 0 且输出含八维度"
        "断言通过（承接 SC2）；失败路由=回滚至上一检查点（git checkout 工作区"
        "回 CP1 状态）；类型=用户暂停（commit+push 不可逆前强制暂停）；goal "
        "anchoring=「原目标：分类维度汇总落地；当前位置：T2/T3 完成，待验证后"
        "进入提交」。",
        "密度论证（按可逆性×爆炸半径逐检查点给类型建议）：CP1 处改动=单文件"
        "工作区改动，git checkout 可回滚（可逆），爆炸半径=单模块导入面（小）"
        "→建议自动继续；CP2 后接 git commit+push（外发不可逆），爆炸半径=远端"
        "仓库历史（大）→建议用户暂停。全链除终态 commit 外均可逆，检查点密度"
        "=2/3 任务边界。",
        "红队条件未触发声明：并行组数=2、检查点数=2，均未超触发阈值（并行组"
        "≥4 或检查点≥5 才触发独立上下文红队），故本步无红队留痕，条件未触发"
        "声明如上。",
        "只提案不拍板确认：以上并行分组、检查点密度与类型（CP1 自动继续/CP2 "
        "用户暂停）均为提案——密度与类型是用户风险裁决项，待子5 用户拍板后"
        "才生效，本步不定案。q/a 按序对齐。",
    ],
}

S2_CLEAN = copy.deepcopy(S2_BASE)

# ---- vio1：虚设判据——CP1 通过判据含「确认…合理」「检查…无问题」判断词 ----
S2_VIO1 = copy.deepcopy(S2_BASE)
S2_VIO1["a"][1] = S2_BASE["a"][1].replace(
    "通过判据="
    "`python3 -c \"from paths import CATEGORY_SUMMARY_RESULT\"` 退出码 0"
    "（承接 SC1）",
    "通过判据=人工确认 paths.py 常量定义合理、检查导入无问题（承接 SC1）",
)

# ---- vio2：即兴路由——CP2 失败路由=「视情况处理」 ----
S2_VIO2 = copy.deepcopy(S2_BASE)
S2_VIO2["a"][1] = S2_BASE["a"][1].replace(
    "失败路由=回滚至上一检查点（git checkout 工作区回 CP1 状态）",
    "失败路由=视情况处理，届时再定返工还是回滚",
)

# ---- vio3：拍脑袋分组——互斥面=「天然不冲突」断言，无改动点文件清单交集计算 ----
S2_VIO3 = copy.deepcopy(S2_BASE)
S2_VIO3["a"][0] = S2_BASE["a"][0].replace(
    "②文件互斥面——从执行包改动点字段"
    "计算：T2 改动文件清单={summary/generate_factor_summary_report.py}，"
    "T3 改动文件清单={summary/MODULE.md}，组内交集=∅（两清单无公共文件）；",
    "②文件互斥面——T2 改报告脚本、T3 改文档，两个方向天然不冲突，无需"
    "逐一核对文件；",
)

# ---- vio4：无验收门——返回契约缺证据形式清单 ----
S2_VIO4 = copy.deepcopy(S2_BASE)
S2_VIO4["a"][0] = S2_BASE["a"][0].replace(
    "④subagent 返回契约——每 worker 返回：pytest 等测试输出原文、实际改动"
    "文件清单、逐改动点 file:line 证据清单，三形式齐备才算交付。",
    "④subagent 返回契约——每 worker 完成后返回执行结果与说明，写清做了"
    "什么即可。",
)

# ---- vio5：逃避论证——检查点类型裸列，无密度论证也无复利论证 ----
S2_VIO5 = copy.deepcopy(S2_BASE)
S2_VIO5["a"][2] = (
    "检查点类型安排：CP1=自动继续，CP2=用户暂停。密度方面两个检查点够用了，"
    "不再展开。"
)

# ---- vio6：越权拍板——替用户裁决密度与类型 ----
S2_VIO6 = copy.deepcopy(S2_BASE)
S2_VIO6["a"][4] = (
    "拍板确认：以上并行分组、检查点密度与类型（CP1 自动继续/CP2 用户暂停）"
    "定为最终方案，按此执行，无需再等用户裁决。q/a 按序对齐。"
)

CASES = {
    "clean": S2_CLEAN,
    "vio1_虚设判据": S2_VIO1,
    "vio2_即兴路由": S2_VIO2,
    "vio3_拍脑袋分组": S2_VIO3,
    "vio4_无验收门": S2_VIO4,
    "vio5_逃避论证": S2_VIO5,
    "vio6_越权拍板": S2_VIO6,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}

# replace anchor 未命中时 vio 静默等于 clean——模块加载即断言，防哑弹载荷
for _k, _v in CASES.items():
    if _k != "clean":
        assert _v != S2_CLEAN, f"{_k} 与 clean 无差异——replace anchor 未命中"


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {
        k: "\n".join(json.dumps(t, ensure_ascii=False) for t in (S1_BASE, s2))
        for k, s2 in CASES.items()
    }
    run_cases("plan:4#2 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
