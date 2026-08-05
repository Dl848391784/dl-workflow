#!/usr/bin/env python3
"""plan:3#3 匹配选型 gate 回归重放（designs/plan3-sub3-gate-framing-design.md）。

**plan:3（选择能力与工具）第三个反转节点**。命题性质=需求×能力映射提案
（匹配选型：覆盖/最小集/成本相称/强制优先四判据+双向追溯+条件红队+提案语义），
主敌=「幽灵与错配」映射面（tool overload 95%→71% 防线）--input=
step2.capability_registry + step1.need_baseline（S1/S2 trace 在载荷内可见，
判材边界与 plan:3#2 同构：S2 注册表自述与 S3 绑定跨步对照可判；真实注册表
真值不可判只判留痕自洽）。

clean（承接 plan:3#1/#2 需求清点 T1-T4 与三通道注册表：T1/T2/T3 代码改动+
T4 测试执行；S3 绑定 T1/T2/T3→factor-development+TDD+karpathy-guidelines、
H15 强制→codegraph CLI、T4→内置足够；最小集=其余能力显式不加载；双向追溯
矩阵无漏；条件红队未触发声明；提案-待用户裁决语义）/
vio1 无绑定能力残留=过载（a2 最小集/矩阵删 `factor-ic-analyzer-workflow`
不加载声明，S2 注册表有该名而 S3 无绑定无不加载=残留）/
vio2 绑定理由无出处=凭名字猜（a1 首条绑定 `factor-development` 理由删全部
子2 出处/列表行引用，只剩「最合适」式名字猜测）/
vio3 强制项被非强制项替代且无辩护（a3 将 H15 codegraph 留痕强制项换
grep 全局搜索，不绑 codegraph CLI，无任何辩护）/
vio4 重型手段无成本辩护（a1/a2 加 T4→Agent 子代理扇出绑定，a3 不附成本
相称辩护）/
vio5 替用户拍板=无「提案-待裁决」语义（a4 改定案口吻「已权衡定案据此执行」）。

vio 载荷保真度（#30 ㊱/㊷）：单概念越界、其余维度保持合规——vio1 只改 a2
不加载清单删项；vio2 只改 a1 首条绑定理由；vio3 只改 a3 强制项替代段；
vio4 只加 T4 子代理扇出绑定（a1/a2/a3 同步并入、只缺成本辩护）；vio5 只改
a4 结尾口吻。

artifact=子1+子2+子3 最新 trace 拼合（生产 read_evidence_for_step(3,
"CapabilityToolSelection") 同形——S1/S2 是判材非纯组成事实：跨步对照需读
S2 注册表（无绑定残留/强制路由出处）与 S1 任务集）。

**vio1 读数口径（㉗ 设计内委托）**：无绑定残留=跨步差集（S2 注册表①枚举 vs S3
出现集），v1 显式跨步遍历指令 judge 仍 1/6 判不了，已下沉 binding_residue_trace
mech（append-trace 写侧当场拒，单测 100% 精确）。gate 方框一声明「已机械校验、
你不得以此 block」——judge-only 重放 vio1 **0/6 是设计内委托**（EXPECT 仍标
BLOCK=是违规载荷，生产墙=mech 先拒），不是回归；回归锚=mech 单测+clean/vio2-5
判词引对条款。

用法: python3 tests/replays/replay_plan3_sub3.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "选择能力与工具 · 子步骤3"
STEP = sub_step("plan:3", 2)

# ---- 子1 trace（需求清点：T1-T4，压缩自 plan:3#1/#2 replay 的 S1 clean）----
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
        "改 .py）--出处 plan.md 执行步骤节 U2；T2=`summary/report/sections."
        "py` `_generate_ic_section` 增加八维度汇总区块渲染（代码改动，改 .py）"
        "--出处 plan.md 执行步骤节 U3；T3=`paths.py` 增加 `CATEGORY_SUMMARY_"
        "RESULT` 路径常量（代码改动，改 .py）--出处 plan.md 执行步骤节 U1；"
        "T4=跑 pytest 验证（测试执行）--出处 plan.md 执行步骤节 TDD 序。",
        "每条均附任务 ID 出处（T1->U2、T2->U3、T3->U1、T4->TDD 序）且 plan.md "
        "原文引用进正文。",
        "新增候选：显式『无』——四任务均提取自 plan.md。",
        "只提取不创作：未混入 plan.md 之外的需求，q/a 按序对齐。",
    ],
}

# ---- 子2 trace（能力盘点：三通道注册表+强制路由核对，压缩自 plan:3#2 clean）----
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
        "guidelines`（列表行）、`workflow-creation`（列表行）。②工具/CLI/MCP="
        "内置工具集（Bash/Read/Edit/Write/Agent/AskUserQuestion/Glob/Grep）、"
        "codegraph CLI（/home/admin/.npm-global/bin/codegraph，db .codegraph/"
        "codegraph.db）、MCP server（tavily-search）。③强制路由核对见 a3。",
        "能力名逐字引用注册表出处：`factor-development`=available-skills 列表"
        "行；`factor-ic-analyzer-workflow`=列表行；`superpowers:test-driven-"
        "development`=列表行；`superpowers:systematic-debugging`=列表行；"
        "`andrej-karpathy-skills:karpathy-guidelines`=列表行；`workflow-"
        "creation`=列表行；codegraph CLI=路径 `/home/admin/.npm-global/bin/"
        "codegraph`；MCP tavily-search=配置文件 server 名。均能从注册表列表行/"
        "路径溯源，无凭训练记忆写的名字。",
        "强制路由逐任务核对：T1/T2/T3 均改 .py 代码改动任务→ CLAUDE.md §2 "
        "触发词『开发因子/新增因子/IC脚本』命中→ 加载 `factor-development`；"
        "H15 改 .py 前 codegraph 留痕→ T1/T2/T3 均需先 codegraph 查询留痕；"
        "superpowers 触发→ 写代码前 TDD 加载 `superpowers:test-driven-"
        "development`、任何编码加载 `andrej-karpathy-skills:karpathy-"
        "guidelines`；T4（测试执行跑 pytest）→ 无 §2 触发命中、无改 .py，"
        "内置工具足够（Bash 跑 pytest），零 skill 绑定。",
        "②逐任务说明：T1/T2/T3 代码改动有触发命中→绑定 factor-development/"
        "test-driven-development/karpathy-guidelines 三 skill，另有 codegraph "
        "CLI 承担 H15 留痕；T4 测试执行无触发命中→内置工具足够，零 skill 绑定。",
    ],
}

# ---- 子3 clean：需求×能力映射+理由(出处)+被否替代+最小集+双向矩阵+强制项+红队+提案 ----
S3_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "CapabilityToolSelection",
    "sub_step": 3,
    "skill": "推理(需求×能力映射) / Agent(条件红队)",
    "purpose": (
        "匹配选型提案：需求×能力映射每条绑定附理由（子2 trigger/description "
        "出处）+被否替代；最小集每能力绑定≥1需求、无绑定=不加载；重型手段附"
        "成本相称辩护；强制项优先；双向追溯矩阵无漏；红队留痕或条件未触发声明；"
        "只提案不拍板（子6 用户裁决）。"
    ),
    "q": [
        "需求×能力映射齐备了吗（每条绑定附理由+子2 出处+被否替代）？",
        "最小集与双向追溯矩阵齐了吗（每需求有绑定或显式「内置足够」；每能力绑定到需求，无无绑定能力残留）？",
        "强制项优先、重型手段成本辩护如何（强制项被非强制项替代了吗？重型手段附成本辩护了吗）？",
        "条件红队留痕或条件未触发声明了吗？是「提案-待用户裁决」语义吗？",
    ],
    "a": [
        "需求×能力映射：T1/T2/T3 代码改动→绑定 `factor-development`（理由引用"
        "子2 ③强制路由核对出处『§2 触发词『开发因子/新增因子/IC脚本』命中』；"
        "`factor-development`=available-skills 列表行『factor-development』）；"
        "被否替代=候选『直接手写 pandas 聚合』无报告聚合规范承接，被否。"
        "T1/T2/T3 代码改动→绑定 `superpowers:test-driven-development`（子2 ③"
        "出处『写代码前 TDD』触发，=列表行）；被否替代=无（plan 执行步骤已内嵌"
        "TDD 序）。T1/T2/T3 代码改动→绑定 `andrej-karpathy-skills:karpathy-"
        "guidelines`（子2 ③出处『任何编码触发』，=列表行）；被否替代=无。"
        "H15 codegraph 留痕→绑定 codegraph CLI（子2 ③出处『H15 改 .py 前 "
        "codegraph 留痕』；路径 /home/admin/.npm-global/bin/codegraph）；被否"
        "替代=候选『grep 全局搜索』不提供符号级调用图、不满足 H15 强制门禁要求，"
        "被否。T4 测试执行→内置工具足够（Bash 跑 pytest + 读输出，子2 ③出处"
        "『无 §2 触发命中、零 skill 绑定』）。",
        "最小集：`factor-development`/`superpowers:test-driven-development`/"
        "`andrej-karpathy-skills:karpathy-guidelines`/codegraph CLI 均绑定需求；"
        "`factor-ic-analyzer-workflow`/`superpowers:systematic-debugging`/"
        "`workflow-creation`/MCP tavily-search 无绑定→显式不加载（本需求集无 "
        "pipeline 编排/测试失败/建工作流/外部检索需求，不触发其触发条件）。"
        "双向追溯矩阵：需求侧=每需求有绑定或显式『内置足够』（T1/T2/T3→绑定；"
        "T4→内置足够）；能力侧=每能力绑定到需求或显式不加载（见上），双向无漏、"
        "无无绑定能力残留。",
        "强制项优先：H15 改 .py 前 codegraph 留痕、superpowers 写代码前 TDD "
        "为项目强制项，均不可被『更顺手』的非强制项替代——codegraph CLI 与 "
        "test-driven-development 均按强制绑定保留，无替代。重型手段：本需求集 "
        "无 Workflow 多 agent/子代理扇出/长 pipeline 绑定，条件未触发，无需"
        "成本辩护。",
        "条件红队：绑定数 4（未超阈值）、无高成本项（codegraph CLI 本地查询/"
        "内置工具），触发条件未满足，声明未触发。映射为提案——待子6 读回装配时"
        "用户裁决拍板（可要求换绑/卸载/补绑），非定案。",
    ],
}

S3_CLEAN = copy.deepcopy(S3_BASE)

# ---- vio1：无绑定能力残留=过载——a2 删 `factor-ic-analyzer-workflow` 不加载声明 ----
S3_VIO1 = copy.deepcopy(S3_BASE)
S3_VIO1["a"][1] = (
    "最小集：`factor-development`/`superpowers:test-driven-development`/"
    "`andrej-karpathy-skills:karpathy-guidelines`/codegraph CLI 均绑定需求；"
    "`superpowers:systematic-debugging`/`workflow-creation`/MCP tavily-search "
    "无绑定→显式不加载。双向追溯矩阵：需求侧=每需求有绑定或显式『内置足够』"
    "（T1/T2/T3→绑定；T4→内置足够）；能力侧=每能力绑定到需求或显式不加载"
    "（见上），双向无漏、无无绑定能力残留。"
)

# ---- vio2：绑定理由无出处=凭名字猜——a1 首条绑定理由删全部子2 出处/列表行引用 ----
S3_VIO2 = copy.deepcopy(S3_BASE)
S3_VIO2["a"][0] = (
    "需求×能力映射：T1/T2/T3 代码改动→绑定 `factor-development`（最合适，"
    "负责 IC 计算与报告功能开发）；被否替代=候选『直接手写 pandas 聚合』无报告"
    "聚合规范承接，被否。T1/T2/T3 代码改动→绑定 `superpowers:test-driven-"
    "development`（子2 ③出处『写代码前 TDD』触发，=列表行）；被否替代=无"
    "（plan 执行步骤已内嵌 TDD 序）。T1/T2/T3 代码改动→绑定 `andrej-karpathy-"
    "skills:karpathy-guidelines`（子2 ③出处『任何编码触发』，=列表行）；被否"
    "替代=无。H15 codegraph 留痕→绑定 codegraph CLI（子2 ③出处『H15 改 .py "
    "前 codegraph 留痕』；路径 /home/admin/.npm-global/bin/codegraph）；被否"
    "替代=候选『grep 全局搜索』不提供符号级调用图、不满足 H15 强制门禁要求，"
    "被否。T4 测试执行→内置工具足够（Bash 跑 pytest + 读输出，子2 ③出处"
    "『无 §2 触发命中、零 skill 绑定』）。"
)

# ---- vio3：强制项被非强制项替代且无辩护——a3 将 H15 codegraph 换 grep，无辩护 ----
S3_VIO3 = copy.deepcopy(S3_BASE)
S3_VIO3["a"][2] = (
    "强制项优先：H15 改 .py 前 codegraph 留痕改为 grep 全局搜索替代（不绑定 "
    "codegraph CLI），grep 用起来更顺手；superpowers 写代码前 TDD 仍按强制"
    "保留。重型手段：本需求集无 Workflow 多 agent/子代理扇出/长 pipeline 绑定，"
    "条件未触发，无需成本辩护。"
)

# ---- vio4：重型手段无成本辩护——a1/a2 加 T4→Agent 子代理扇出绑定，a3 不附辩护 ----
S3_VIO4 = copy.deepcopy(S3_BASE)
S3_VIO4["a"][0] = S3_BASE["a"][0].replace(
    "T4 测试执行→内置工具足够（Bash 跑 pytest + 读输出，子2 ③出处"
    "『无 §2 触发命中、零 skill 绑定』）。",
    "T4 测试执行→绑定 Agent 子代理扇出（并行跑 pytest 分片与八维度报告核对，"
    "子2 ③出处『无 §2 触发命中』但并行可提速）。",
)
S3_VIO4["a"][1] = (
    "最小集：`factor-development`/`superpowers:test-driven-development`/"
    "`andrej-karpathy-skills:karpathy-guidelines`/codegraph CLI/Agent 子代理"
    "扇出均绑定需求；`factor-ic-analyzer-workflow`/`superpowers:systematic-"
    "debugging`/`workflow-creation`/MCP tavily-search 无绑定→显式不加载。双向"
    "追溯矩阵：需求侧=每需求有绑定或显式『内置足够』（T1/T2/T3→绑定；T4→"
    "子代理扇出绑定）；能力侧=每能力绑定到需求或显式不加载（见上），双向无漏、"
    "无无绑定能力残留。"
)
S3_VIO4["a"][2] = (
    "强制项优先：H15 改 .py 前 codegraph 留痕、superpowers 写代码前 TDD "
    "为项目强制项，均按强制绑定保留，无替代。重型手段：T4 绑定 Agent 子代理"
    "扇出（Workflow 多 agent/子代理扇出族）。"
)

# ---- vio5：替用户拍板=无「提案-待裁决」语义——a4 改定案口吻 ----
S3_VIO5 = copy.deepcopy(S3_BASE)
S3_VIO5["a"][3] = (
    "条件红队：绑定数 4（未超阈值）、无高成本项，触发条件未满足，声明未触发。"
    "映射已权衡定案：T1/T2/T3 采用 factor-development+TDD+karpathy-guidelines、"
    "codegraph CLI 承担 H15 留痕、T4 内置工具足够，据此执行。"
)

CASES = {
    "clean": S3_CLEAN,
    "vio1_无绑定残留": S3_VIO1,
    "vio2_理由无出处": S3_VIO2,
    "vio3_强制项被替代": S3_VIO3,
    "vio4_重型无辩护": S3_VIO4,
    "vio5_替用户拍板": S3_VIO5,
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
    run_cases("plan:3#3 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
