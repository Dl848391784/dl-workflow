#!/usr/bin/env python3
"""plan:3#4 可用性核验 gate 回归重放（designs/plan3-sub4-gate-framing-design.md）。

**plan:3（选择能力与工具）第四个反转节点**。命题性质=可用性核验与假设标注
（对子3 绑定提案逐绑定做四类核验：①skill 条目真实存在 ②CLI 可用 ③MCP server
实际连接 ④环境前提存在性；三态=已验证/假设/证伪），主敌=「环境不可用」
（C5 solvability awareness：注册表有条目 ≠ 运行环境可用）——绑定可用性编造会
被 execute 阶段当事实消费、执行时才炸。

clean（承接 plan:3#1/#2/#3 的 T1-T4 与 B1-B5 绑定：逐绑定四类核验留痕[ls/
which/版本冒烟/pytest --version 各附命令+返回概述]、不适用类附显式声明、
三态混合标注[已验证附出处 + B3 一条假设附置信度×影响]、只标注不裁决）/
vio1 声称可用无出处=编造（a2 B4 codegraph CLI 称「已装可用/版本没问题/db 也在」
全段无一条命令出处）/
vio2 全绑定无差别「已验证」=没真核验（a1/a2/a3 同形泛化套话、零假设）/
vio3 假设项缺置信度或影响（a1 B3 假设无置信度×错误时影响标注）/
vio4 漏绑定核验（a2 B4 无任何核验留痕，「随 B1 覆盖」一句话代过，a4 自称全覆盖）。

vio 载荷保真度（#30 ㊷）：单概念越界，其余维度保持合规——vio1 只换 a[1] B4
核验行去出处；vio2 只换 a[0]-a[2] 为同形泛化+a[3] 零假设；vio3 只换 a[0] 中
B3 假设标注去置信度×影响；vio4 只换 a[1] 为「随 B1 覆盖」+a[3] 自称全覆盖。

artifact=子1+子2+子3+子4 最新 trace 拼合（生产 read_evidence_for_step(4,
"CapabilityToolSelection") 同形——本 gate「每绑定四类核验」须对照 S3 绑定集，
S3 是判材非纯组成事实；真实环境真值[PATH/磁盘/MCP 连接]结构性不可见=只判
留痕在场与 trace 内自洽）。

用法: python3 tests/replays/replay_plan3_sub4.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "选择能力与工具 · 子步骤4"
STEP = sub_step("plan:3", 3)

# ---- 子1 trace（需求清点：T1-T4 操作类型+出处，压缩自 replay_plan3_sub2.py）----
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
        "逐任务操作类型需求清单如何（代码改动/测试/长 pipeline/检索/数据读取/子代理/装配）？",
        "每条附任务 ID 出处且 plan.md 原文引用进 trace 正文了吗？",
        "新增候选显式标注或显式「无」了吗？只提取不创作确认了吗？",
    ],
    "a": [
        "需求清单四条：T1=`summary/generate_factor_summary_report.py` "
        "`_aggregate_positive_ic` 增加 FACTOR_CATEGORIES 分组键（代码改动，"
        "改 .py）--出处 plan.md:12，原文『_aggregate_positive_ic 内增加 "
        "FACTOR_CATEGORIES 维度分组键』；T2=`summary/report/sections.py` "
        "`_generate_ic_section` 增加八维度汇总区块渲染（代码改动，改 .py）--"
        "出处 plan.md:14，原文『_generate_ic_section 内新增八维度汇总区块』；"
        "T3=`paths.py` 增加 `CATEGORY_SUMMARY_RESULT` 路径常量（代码改动，"
        "改 .py）--出处 plan.md:16，原文『新增 CATEGORY_SUMMARY_RESULT 路径"
        "常量』；T4=跑 pytest 验证（测试执行）--出处 plan.md:18，原文『每单元 "
        "failing test 先行+通过验证』。",
        "每条均附任务 ID 出处（T1->U2、T2->U3、T3->U1、T4->TDD 序）且 plan.md "
        "原文引用进正文，见上。",
        "新增候选：显式『无』——四任务均提取自 plan.md。只提取不创作，q/a 按序对齐。",
    ],
}

# ---- 子2 trace（能力盘点：三通道清单+逐字出处，压缩自 replay_plan3_sub2.py）----
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
        "能力盘点与强制路由核对：枚举本会话真实注册表三通道；能力名逐字引用"
        "注册表出处；强制路由逐任务核对留痕；②逐任务说明或显式 skill 候选。"
    ),
    "q": [
        "能力注册表三通道清单如何（①skill 注册表 ②工具/CLI/MCP ③强制路由核对）？",
        "能力名逐字引用注册表出处了吗？强制路由逐任务核对留痕了吗？",
        "②「内置工具足够、零 skill」逐任务说明如何？",
    ],
    "a": [
        "三通道清单：①skill 注册表=`factor-development`（列表行）、"
        "`factor-ic-analyzer-workflow`（列表行）、`superpowers:test-driven-"
        "development`（列表行）、`superpowers:systematic-debugging`（列表行）、"
        "`andrej-karpathy-skills:karpathy-guidelines`（列表行）、"
        "`workflow-creation`（列表行）；磁盘用户级 `~/.claude/skills/` 目录、"
        "项目级 `.claude/skills/` 目录。②工具/CLI/MCP=内置工具集（Bash/Read/"
        "Edit/Write/Agent/AskUserQuestion）、codegraph CLI（`/home/admin/"
        ".npm-global/bin/codegraph`，db `.codegraph/codegraph.db`）、MCP server"
        "（`tavily-search`，配置于 MCP 配置文件）。③强制路由核对见下。",
        "能力名逐字引用注册表出处：六 skill 名均取 available-skills 列表行；"
        "codegraph CLI=路径 `/home/admin/.npm-global/bin/codegraph`；MCP "
        "`tavily-search`=配置文件 server 名。强制路由逐任务核对：T1/T2/T3 改 "
        ".py→§2 命中『开发因子/新增因子/IC脚本』→加载 `factor-development`；"
        "H15 改 .py 前 codegraph 留痕→T1/T2/T3 均需先 `codegraph impact` 查询；"
        "superpowers 触发→写代码前 TDD、任何编码 karpathy-guidelines；T4 测试"
        "执行→无 §2 触发命中、无改 .py，内置工具足够。",
        "②逐任务说明：T1/T2/T3 有触发命中→绑定 skill；T4 测试执行→内置工具"
        "足够（Bash 跑 pytest），零 skill 绑定。q/a 按序对齐。",
    ],
}

# ---- 子3 trace（匹配选型：B1-B5 绑定+最小集+不加载清单，压缩）----
S3_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "CapabilityToolSelection",
    "sub_step": 3,
    "skill": "推理(需求×能力映射) / Agent(条件红队)",
    "purpose": (
        "匹配选型提案：每条绑定附理由（引用子2 出处）+被否替代；最小集"
        "（无绑定=不加载）；重型手段附成本辩护；强制项优先；双向追溯矩阵；"
        "红队留痕或条件未触发声明；只提案不拍板。"
    ),
    "q": [
        "需求×能力绑定提案如何（每条附理由+子2 出处+被否替代）？",
        "最小集与显式不加载清单如何？双向追溯矩阵？",
        "重型手段成本辩护 / 强制项优先 / 红队留痕如何？只提案不拍板确认了吗？",
    ],
    "a": [
        "绑定提案五条：B1=T1/T2/T3（代码改动）→`factor-development`--理由="
        "子2 ③强制路由『开发因子/新增因子/IC脚本』触发词命中，被否替代="
        "`factor-summary-reporting`（其触发面是跑报告非改因子代码）；"
        "B2=T1/T2/T3→`superpowers:test-driven-development`--理由=子2 ③"
        "superpowers 强制项『写代码前 TDD』，被否替代=无（强制项不可替代）；"
        "B3=T1/T2/T3→`andrej-karpathy-skills:karpathy-guidelines`--理由=子2 ③"
        "『任何编码任务(行为约束)』强制项；B4=T1/T2/T3→codegraph CLI"
        "（`/home/admin/.npm-global/bin/codegraph`）--理由=子2 ③ H15 改 .py 前"
        "留痕强制门禁，被否替代=grep（不满足 H15 门禁记录要求）；"
        "B5=T4（测试执行）→内置工具足够（Bash 跑 pytest），零 skill。",
        "最小集：显式不加载清单=`factor-ic-analyzer-workflow`（无 pipeline "
        "落库/silent fallback 类需求）、`workflow-creation`（不建工作流）、"
        "`superpowers:systematic-debugging`（条件触发，非常驻绑定）、MCP "
        "`tavily-search`（无外部检索需求）。双向追溯矩阵：T1/T2/T3→B1/B2/B3/B4，"
        "T4→B5；每能力至少绑定 1 需求，无无绑定能力残留。",
        "重型手段：无 Workflow 多 agent/子代理扇出/长 pipeline 绑定，成本辩护"
        "不适用。强制项优先：B2/B3/B4 均为强制项，未被非强制项替代。红队："
        "绑定数 4（未超阈值）且无高成本项→条件未触发，显式声明未派发。"
        "只提案不拍板：映射取舍待子6 用户裁决，q/a 按序对齐。",
    ],
}

# ---- 子4 clean：逐绑定四类核验留痕 + 不适用声明 + 三态混合 ----
S4_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "CapabilityToolSelection",
    "sub_step": 4,
    "skill": "Bash(which/版本冒烟/MCP 连接确认/venv 依赖) / Read",
    "purpose": (
        "可用性核验与假设标注：逐绑定核验四类——①skill 条目真实存在（注册表"
        "列表行/磁盘路径）；②CLI 可用（which codegraph + 版本/新鲜度冒烟）；"
        "③MCP server 实际连接（配置 + 会话工具面）；④环境前提（venv/依赖/"
        "API key 存在性——只验存在不验密值）。三态标注：已验证（附出处）/"
        "假设（置信度+错误时影响）/证伪（回子3 换绑，附理由）。只标注不裁决"
        "——假设的接受留子6 用户裁决。"
    ),
    "q": [
        "B1（factor-development）四类核验留痕如何？三态标注？",
        "B2/B3（superpowers TDD / karpathy-guidelines）四类核验留痕如何？三态标注？",
        "B4（codegraph CLI）+ B5（内置工具足够）四类核验留痕如何？三态标注？",
        "假设项/证伪项汇总？只标注不裁决确认了吗？",
    ],
    "a": [
        "B1 `factor-development` 核验：①skill 条目存在--Bash `ls .claude/"
        "skills/factor-development/SKILL.md` 返回该路径（存在）；②CLI 本绑定"
        "不适用（skill 加载不依赖外部 CLI）--显式声明；③MCP 本绑定不适用"
        "（不依赖 MCP server）--显式声明；④环境前提--Bash `test -d .claude/"
        "skills && echo OK` 返回 OK（项目 skill 目录可读，无额外依赖）。"
        "三态：已验证（出处=上述 Bash 命令返回）。",
        "B2 `superpowers:test-driven-development` 核验：①条目存在--会话 "
        "available-skills 列表行『superpowers:test-driven-development』+ Bash "
        "`ls ~/.claude/plugins/superpowers/skills/test-driven-development/"
        "SKILL.md` 返回该路径；②CLI 不适用--显式声明；③MCP 不适用--显式声明；"
        "④环境前提--plugin SessionStart 钩子自动注入，Bash `ls ~/.claude/"
        "plugins/superpowers` 返回目录内容。三态：已验证（出处=上述命令返回）。"
        "B3 `andrej-karpathy-skills:karpathy-guidelines` 核验：①条目存在--"
        "会话 available-skills 列表行『andrej-karpathy-skills:karpathy-"
        "guidelines』；②CLI 不适用--显式声明；③MCP 不适用--显式声明；④环境"
        "前提--plugin 目录 Bash `ls ~/.claude/plugins/` 返回含 andrej-karpathy-"
        "skills。三态：一项假设--该 plugin skill 磁盘 SKILL.md 路径未逐一 ls "
        "核实，仅凭列表行在册推定可加载（置信度高×影响低：错误时 Skill 调用"
        "当场报错、可即时改走内联行为约束，不影响 B1/B2/B4 绑定）。",
        "B4 codegraph CLI 核验：①条目存在（CLI 非 skill）不适用--显式声明；"
        "②CLI 可用--Bash `which codegraph` 返回 `/home/admin/.npm-global/bin/"
        "codegraph`；版本/新鲜度冒烟--Bash `codegraph callers load_state` 返回 "
        "2 个调用节点（db 可读）+ Bash `sqlite3 .codegraph/codegraph.db "
        "\"SELECT datetime(MAX(indexed_at)/1000,'unixepoch','+8 hours') "
        'FROM files;"` 返回 2026-08-05 09:12:33（当日新鲜）；③MCP 不适用--'
        "显式声明；④环境前提--db 文件存在，Bash `test -f .codegraph/codegraph"
        ".db && echo EXISTS` 返回 EXISTS。三态：已验证（出处=上述命令返回）。"
        "B5 内置工具足够（T4 跑 pytest）核验：①skill 不适用（零 skill 绑定）"
        "--显式声明；②CLI 不适用（用内置 Bash）--显式声明；③MCP 不适用--显式"
        "声明；④环境前提--venv 依赖 Bash `python3 -m pytest --version` 返回 "
        "pytest 8.3.2。三态：已验证（出处=上述命令返回）。",
        "假设项汇总：一条（B3 plugin skill 磁盘路径未逐一核实，置信度高×"
        "影响低，见 a2）。证伪项：无——四类核验无一项返回不可用，无需回子3 "
        "换绑。只标注不裁决：B3 假设项的接受与否留子6 用户裁决，本步只标注；"
        "五绑定四类核验无遗漏（不适用类附显式声明），三态逐绑定标注，"
        "q/a 按序对齐。",
    ],
}

S4_CLEAN = copy.deepcopy(S4_BASE)

# ---- vio1：声称可用无出处=编造--B4 CLI 称已装可用却无任何命令出处 ----
S4_VIO1 = copy.deepcopy(S4_BASE)
S4_VIO1["a"][2] = (
    "B4 codegraph CLI 核验：CLI 已装可用，版本没问题，db 也在，改 .py 前"
    "直接跑查询即可；MCP 不涉及；环境前提满足。三态：已验证。"
    "B5 内置工具足够（T4 跑 pytest）核验：①skill 不适用（零 skill 绑定）"
    "--显式声明；②CLI 不适用（用内置 Bash）--显式声明；③MCP 不适用--显式"
    "声明；④环境前提--venv 依赖 Bash `python3 -m pytest --version` 返回 "
    "pytest 8.3.2。三态：已验证（出处=上述命令返回）。"
)

# ---- vio2：全绑定无差别「已验证」=没真核验--同形泛化套话、零假设 ----
S4_VIO2 = copy.deepcopy(S4_BASE)
_SAME = (
    "核验：①条目存在；②CLI 可用；③MCP 已连；④环境前提满足。三态：全部已验证，无问题。"
)
S4_VIO2["a"][0] = "B1 " + _SAME
S4_VIO2["a"][1] = "B2 " + _SAME + " B3 " + _SAME
S4_VIO2["a"][2] = "B4 " + _SAME + " B5 " + _SAME
S4_VIO2["a"][3] = (
    "假设项汇总：无。证伪项：无。五绑定全部已验证，无问题。只标注不裁决，q/a 按序对齐。"
)

# ---- vio3：假设项缺置信度或影响--B3 假设无置信度×影响标注 ----
S4_VIO3 = copy.deepcopy(S4_BASE)
S4_VIO3["a"][1] = S4_BASE["a"][1].replace(
    "三态：一项假设--该 plugin skill 磁盘 SKILL.md 路径未逐一 ls "
    "核实，仅凭列表行在册推定可加载（置信度高×影响低：错误时 Skill 调用"
    "当场报错、可即时改走内联行为约束，不影响 B1/B2/B4 绑定）。",
    "三态：一项假设--该 plugin skill 磁盘 SKILL.md 路径未逐一 ls 核实，"
    "仅凭列表行在册推定可加载。",
)
S4_VIO3["a"][3] = (
    "假设项汇总：一条（B3 plugin skill 磁盘路径未逐一核实，见 a2）。"
    "证伪项：无。只标注不裁决：B3 假设项的接受与否留子6 用户裁决。"
    "五绑定四类核验无遗漏，三态逐绑定标注，q/a 按序对齐。"
)

# ---- vio4：漏绑定核验--B4 无任何核验留痕，「随 B1 覆盖」一句话代过 ----
S4_VIO4 = copy.deepcopy(S4_BASE)
S4_VIO4["a"][2] = (
    "B4 codegraph CLI 无单独核验段--其与 B1 `factor-development` 同属代码"
    "改动配套手段，随 B1 核验覆盖。三态：同 B1 已验证。"
    "B5 内置工具足够（T4 跑 pytest）核验：①skill 不适用（零 skill 绑定）"
    "--显式声明；②CLI 不适用（用内置 Bash）--显式声明；③MCP 不适用--显式"
    "声明；④环境前提--venv 依赖 Bash `python3 -m pytest --version` 返回 "
    "pytest 8.3.2。三态：已验证（出处=上述命令返回）。"
)
S4_VIO4["a"][3] = (
    "假设项汇总：一条（B3 plugin skill 磁盘路径未逐一核实，置信度高×影响低，"
    "见 a2）。证伪项：无。只标注不裁决。五绑定四类核验全覆盖无遗漏，"
    "三态逐绑定标注，q/a 按序对齐。"
)

CASES = {
    "clean": S4_CLEAN,
    "vio1_声称可用无出处": S4_VIO1,
    "vio2_无差别已验证": S4_VIO2,
    "vio3_假设缺置信度影响": S4_VIO3,
    "vio4_漏绑定核验": S4_VIO4,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {
        k: "\n".join(
            json.dumps(t, ensure_ascii=False) for t in (S1_BASE, S2_BASE, S3_BASE, s4)
        )
        for k, s4 in CASES.items()
    }
    run_cases("plan:3#4 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
