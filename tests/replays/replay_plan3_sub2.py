#!/usr/bin/env python3
"""plan:3#2 能力盘点 gate 回归重放（designs/plan3-sub2-gate-framing-design.md）。

**plan:3（选择能力与工具）第二个反转节点**。命题性质=能力盘点与强制路由
核对（枚举本会话真实注册表三通道：skill 注册表/工具·CLI·MCP/强制路由核对），
主敌=「幽灵与漏配」--input=step1.need_baseline（S1 trace 在载荷内可见，
判材边界与 plan:2#2 同构：任务集跨步对照可判，注册表真值不可判只判留痕）。

clean（承接 plan:3#1 需求清点 T1-T4：T1/T2/T3 代码改动[改 .py=H15 信号]+
T4 测试执行；三通道清单齐备、能力名逐字引用注册表出处、强制路由逐任务核对、
②「内置工具足够/零 skill」逐任务说明）/
vio1 幽灵能力（a3 路由 T1 加载 `factor-pool-optimizer`，a2 出处清单无此名
——能力名凭空，与注册表不符）/
vio2 强制路由漏核（a3 只核对 T2/T3/T4，T1 代码改动漏 H15 codegraph 留痕
+superpowers TDD 触发，a3 明说「T1 无路由核对」）/
vio3 凭记忆编造（a1 给 `factor-development` 加功能描述「自动执行 IC 计算与
分层回测」，无 SKILL.md/listing 出处引用）/
vio4 ②无逐任务说明（a4 全局「所有任务内置工具足够零 skill 绑定」，无逐
任务说明，与 _CTS_STEP2_FORM_REQUIREMENTS「须逐任务说明」相悖）。

vio 载荷保真度（#30 ㊷）：单概念越界，其余维度保持合规--vio1 只换 a1 ①
清单添加幽灵名+a3 路由；vio2 只换 a3 路由表；vio3 只换 a1 加功能描述；
vio4 只换 a4 ②说明。

artifact=子1+子2 最新 trace 拼合（生产 read_evidence_for_step(2,
"CapabilityToolSelection") 同形--本 gate 判据涉任务集覆盖对照[跨步一致性，
S1 在载荷内可见]，前序 trace 是判材不是纯组成事实；注册表真值不可见=判据
钉「只判留痕在场不核真实注册表」）。

用法: python3 tests/replays/replay_plan3_sub2.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "选择能力与工具 · 子步骤2"
STEP = sub_step("plan:3", 1)

# ---- 子1 trace（需求清点：T1-T4 操作类型+出处+新增候选，压缩自本节点子1 clean）----
S1_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "CapabilityToolSelection",
    "sub_step": 1,
    "skill": "Read(plan.md) / Bash(grep evidence TaskBreakdown trace)",
    "purpose": (
        "需求清点与追溯基线：逐任务操作类型需求清单齐备；每条附任务 ID 出处"
        "且 plan.md 原文引用进 trace 正文；新增候选显式标注或显式「无」；"
        "只提取不创作。"
    ),
    "q": [
        "逐任务操作类型需求清单如何（代码改动/测试/长 pipeline/检索/数据读取/子代理/装配，无遗漏）？",
        "每条附任务 ID 出处且 plan.md 原文引用进 trace 正文了吗？",
        "新增候选显式标注或显式「无」了吗？",
        "只提取不创作确认了吗（有静默新增 plan 没有的需求吗）？",
    ],
    "a": [
        "需求清单四条：T1=`summary/generate_factor_summary_report.py` "
        "`_aggregate_positive_ic` 增加 FACTOR_CATEGORIES 分组键（代码改动，"
        "改 .py）--出处 plan.md 执行步骤节 U2，原文『_aggregate_positive_ic "
        "内增加 FACTOR_CATEGORIES 维度分组键』；T2=`summary/report/sections."
        "py` `_generate_ic_section` 增加八维度汇总区块渲染（代码改动，改 .py）"
        "--出处 plan.md 执行步骤节 U3，原文『_generate_ic_section 内新增八"
        "维度汇总区块』；T3=`paths.py` 增加 `CATEGORY_SUMMARY_RESULT` 路径"
        "常量（代码改动，改 .py）--出处 plan.md 执行步骤节 U1，原文『新增 "
        "CATEGORY_SUMMARY_RESULT 路径常量』；T4=跑 pytest 验证（测试执行）"
        "--出处 plan.md 执行步骤节 TDD 序，原文『每单元 failing test 先行"
        "+通过验证』。操作类型覆盖代码改动×3+测试执行，无长 pipeline/外部"
        "检索/数据读取/子代理/装配任务（本需求集未含）。",
        "每条均附任务 ID 出处（T1->U2、T2->U3、T3->U1、T4->TDD 序）且 plan.md "
        "原文引用进正文，见上。",
        "新增候选：显式『无』——四任务均提取自 plan.md，无 plan 之外的需求。",
        "只提取不创作：未混入 plan.md 之外的需求，q/a 按序对齐。",
    ],
}

# ---- 子2 clean：三通道清单齐备+能力名逐字出处+强制路由逐任务+②逐任务说明 ----
S2_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "CapabilityToolSelection",
    "sub_step": 2,
    "skill": (
        "Read(CLAUDE.md §2/§3 / 相关 SKILL.md frontmatter) / "
        "Bash(ls ~/.claude/skills + .claude/skills、MCP 配置、which codegraph)"
    ),
    "purpose": (
        "能力盘点与强制路由核对：枚举本会话真实注册表三通道（skill 注册表/"
        "工具·CLI·MCP/强制路由核对）；能力名逐字引用注册表出处；强制路由"
        "逐任务核对留痕；②逐任务说明或显式 skill 候选。"
    ),
    "q": [
        "能力注册表三通道清单如何（①skill 注册表 ②工具/CLI/MCP ③强制路由核对）？",
        "能力名逐字引用注册表出处了吗（禁凭训练记忆）？",
        "强制路由逐任务核对留痕了吗（§2 触发词/H15/superpowers 触发）？",
        "②「内置工具足够、零 skill」逐任务说明或显式 skill 候选如何？",
    ],
    "a": [
        "三通道清单：①skill 注册表=会话 available-skills 列表+磁盘目录："
        "`factor-development`（列表行）、`factor-ic-analyzer-workflow`（列表行）、"
        "`superpowers:test-driven-development`（列表行）、`superpowers:"
        "systematic-debugging`（列表行）、`andrej-karpathy-skills:karpathy-"
        "guidelines`（列表行）、`workflow-creation`（列表行）；磁盘用户级 "
        "`~/.claude/skills/` 目录、项目级 `.claude/skills/` 目录（factor-"
        "development 等四个项目 skill）。②工具/CLI/MCP=内置工具集（Bash/Read/"
        "Edit/Write/Agent/AskUserQuestion/Glob/Grep）、codegraph CLI（/home/"
        "admin/.npm-global/bin/codegraph，db .codegraph/codegraph.db）、MCP "
        "server（tavily-search，配置于 MCP 配置文件）。③强制路由核对见 a3。",
        "能力名逐字引用注册表出处：`factor-development`=available-skills 列表"
        "『factor-development』行；`factor-ic-analyzer-workflow`=列表行"
        "『factor-ic-analyzer-workflow』；`superpowers:test-driven-development`="
        "列表行『superpowers:test-driven-development』；`superpowers:systematic-"
        "debugging`=列表行『superpowers:systematic-debugging』；`andrej-"
        "karpathy-skills:karpathy-guidelines`=列表行；`workflow-creation`=列表行"
        "『workflow-creation』；codegraph CLI=路径 `/home/admin/.npm-global/bin/"
        "codegraph`；MCP tavily-search=配置文件 server 名『tavily-search』。"
        "所有能力名均能从注册表列表行/路径溯源，无凭训练记忆写的名字。",
        "强制路由逐任务核对：T1/T2/T3 均改 .py 代码改动任务→ CLAUDE.md §2 "
        "触发词『开发因子/新增因子/IC脚本』命中（T2/T3 同为 IC 报告功能改动）"
        "→ 加载 `factor-development`；H15 改 .py 前 codegraph 留痕→ T1/T2/T3 "
        "均需先 `codegraph impact` 查询留痕；superpowers 触发→ 写代码前 TDD "
        "加载 `superpowers:test-driven-development`、任何编码加载 `andrej-"
        "karpathy-skills:karpathy-guidelines`；T4（测试执行跑 pytest）→ 无 "
        "§2 触发命中、无改 .py，内置工具足够（Bash 跑 pytest），零 skill 绑定。",
        "②逐任务说明：T1/T2/T3 代码改动有触发命中→绑定 factor-development/"
        "test-driven-development/karpathy-guidelines 三 skill，另有 codegraph "
        "CLI 承担 H15 留痕；T4 测试执行无触发命中→内置工具足够（Bash 跑 pytest "
        "+ 读输出即完成），零 skill 绑定；每条任务均有归属说明，无『以防万一』"
        "全挂上的过载绑定。q/a 按序对齐。",
    ],
}

S2_CLEAN = copy.deepcopy(S2_BASE)

# ---- vio1：幽灵能力--a3 路由 T1 加载 `factor-pool-optimizer`，a2 出处无此名 ----
S2_VIO1 = copy.deepcopy(S2_BASE)
S2_VIO1["a"][2] = (
    "强制路由逐任务核对：T1（改 .py `_aggregate_positive_ic`）→ 加载 "
    "`factor-pool-optimizer`（因子池优化）；H15 改 .py 前 codegraph 留痕→ "
    "T1/T2/T3 改 .py 均需先 `codegraph impact` 查询留痕；superpowers 触发→ "
    "写代码前 TDD（T1/T2/T3）加载 `superpowers:test-driven-development`；T4"
    "（测试执行跑 pytest）→ 无 §2 触发命中，内置工具足够。"
)

# ---- vio2：强制路由漏核--a3 只核对 T2/T3/T4，T1 代码改动漏 H15+superpowers ----
S2_VIO2 = copy.deepcopy(S2_BASE)
S2_VIO2["a"][2] = (
    "强制路由逐任务核对：T2（改 .py `_generate_ic_section`）→ H15 改 .py 前 "
    "codegraph 留痕（`codegraph impact` 查询）；T3（改 .py `paths.py`）→ H15 "
    "codegraph 留痕；T4（测试执行跑 pytest）→ 无 §2 触发命中，内置工具足够。"
    "T1（改 .py `_aggregate_positive_ic`）：无路由核对——T1 为代码改动但未"
    "列 H15 codegraph 留痕、未列 superpowers TDD 触发。"
)

# ---- vio3：凭记忆编造--a1 给 `factor-development` 加功能描述，无 SKILL.md/listing 出处 ----
S2_VIO3 = copy.deepcopy(S2_BASE)
S2_VIO3["a"][0] = (
    "三通道清单：①skill 注册表=会话 available-skills 列表+磁盘目录："
    "`factor-development`（列表行，功能：自动执行因子 IC 计算、分层回测与"
    "权重选股）、`factor-ic-analyzer-workflow`（列表行，功能：pipeline 数据"
    "流编排）、`superpowers:test-driven-development`（列表行）、`superpowers:"
    "systematic-debugging`（列表行）、`andrej-karpathy-skills:karpathy-"
    "guidelines`（列表行）、`workflow-creation`（列表行）；磁盘用户级 "
    "`~/.claude/skills/` 目录、项目级 `.claude/skills/` 目录（factor-"
    "development 等四个项目 skill）。②工具/CLI/MCP=内置工具集（Bash/Read/"
    "Edit/Write/Agent/AskUserQuestion/Glob/Grep）、codegraph CLI（/home/"
    "admin/.npm-global/bin/codegraph，db .codegraph/codegraph.db）、MCP "
    "server（tavily-search，配置于 MCP 配置文件）。③强制路由核对见 a3。"
)

# ---- vio4：②无逐任务说明--a4 全局「零 skill 内置工具足够」，无逐任务说明 ----
S2_VIO4 = copy.deepcopy(S2_BASE)
S2_VIO4["a"][3] = "②所有任务内置工具足够，零 skill 绑定，无需逐任务说明。q/a 按序对齐。"

CASES = {
    "clean": S2_CLEAN,
    "vio1_幽灵能力": S2_VIO1,
    "vio2_强制路由漏核": S2_VIO2,
    "vio3_凭记忆编造": S2_VIO3,
    "vio4_②无逐任务说明": S2_VIO4,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {
        k: "\n".join(json.dumps(t, ensure_ascii=False) for t in (S1_BASE, s2))
        for k, s2 in CASES.items()
    }
    run_cases("plan:3#2 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
