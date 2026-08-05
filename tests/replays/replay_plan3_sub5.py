#!/usr/bin/env python3
"""plan:3#5 归一化能力包 gate 回归重放（designs/plan3-sub5-gate-framing-design.md）。

**plan:3（选择能力与工具）第五个反转节点=35 gate 收官**。设计任务承接
plan:3#1-#4 同一场景链：T1-T4（T1/T2/T3 代码改动 + T4 测试执行）-> B1-B5
绑定（factor-development / superpowers TDD / karpathy-guidelines / codegraph
CLI / 内置工具足够）-> 子4 逐绑定四类核验（B3 一条假设：plugin skill 磁盘
SKILL.md 未逐一核实，置信度高×影响低）-> 子5 归一化能力包五字段。

命题性质=**配置断言归一化**（从子3 绑定提案+子4 可用性核验推导 statements
五字段能力包），主敌=「长链转换失真」：字段篡改/复合未拆/幽灵回潮/不加载
清单丢失/假设丢失五类。record_format=statements（statement_fields 五键
skill_first/tools/enforce_align/subagent_policy/no_load 由 append-trace 逐键
JSON 校验非空——无内容键填显式「无」）。type_label 域=skill/工具/门禁/
子代理/不加载 **五值**（#30 ㉜ 多值域=归一化族高迭代预期信号）。

clean（七 statements 五类 type_label 全覆盖：三 skill 绑定逐字注册表名+
触发依据引用、codegraph CLI 附子4 已验证出处、内置 Bash+pytest 8.3.2 附
子4 出处、H15 门禁对齐+长 pipeline 后台禁 pipe、单线程显式声明、四件不
加载清单承子3 原样；B3 假设置信度高×影响低原样携带进 stmt3 boundary）/
vio1 字段篡改（stmt1 绑定名由子3 B1 的 `factor-development` 换成其被否替代
`factor-summary-reporting`——与子3 绑定提案语义冲突）/
vio2 复合句（stmt1 text「并且」连接两个可独立执行的配置断言：skill 绑定 +
测试时机策略）/
vio3 幽灵回潮（stmt2 能力名写 `superpowers:tdd`——子2 注册表无此名，凭记忆
缩略 `superpowers:test-driven-development`）/
vio4 不加载清单丢失（删 stmt8 不加载声明，其余各项 no_load 全「无」且无
「本包无不加载项」声明——子3 四件显式不加载清单静默丢失）/
vio5 假设丢失（stmt3 boundary 的子4 假设传导被抹成「可用性已确认无风险」，
全包无任何假设携带也无声明——置信度高×影响低丢失）。

vio 载荷保真度（#30 ㊷ 单点越界）：vio1 只换 stmt1 绑定名（text+field 一致
地错，其余六项不动）；vio2 只换 stmt1 的 text；vio3 只换 stmt2 能力名；
vio4 只删 stmt8（其余七项不动）；vio5 只换 stmt3 的 boundary。

**本节点读数口径（#30 ⑦/㊗，别把设计内读数当回归）**：vio4 与 vio5 的生产墙
是 **mech**（`no_load_trace` + `assumption_propagation_trace`，append-trace 写侧
当场拒；mech 单测 test_p3s5_no_load_trace_block_pass_skip /
test_p3s5_assumption_propagation_block_pass_skip 零方差证拒，只在 vio4/vio5 触发、
clean 与 vio1-3 全静默）；gate 方框四/五已声明「已由 X 机械校验、不会到你这里、
不得以此 block」+ mech_scope 双重注入，故 **judge 侧 vio4/vio5 PASS（0-2/6 BLOCK）
是设计内委托**，不是崩牙。judge 侧达标线只看 clean ≥5/6 + vio1-3 ≥5/6 **且判词
引对条款**（㉖）。

artifact=子1+子2+子3+子4+子5 最新 trace 拼合（生产 read_evidence_for_step(5,
"CapabilityToolSelection") 同形——本 gate 判据涉字段传导对照[子2 注册表名、
子3 绑定/不加载清单、子4 可用性状态与假设]，前序 trace 是判材非纯组成事实，
#30 ⑧/⑨）。S1-S4 压缩内嵌（同 replay_plan3_sub4.py 场景链，⑨ 禁 import
兄弟 replay）。

用法: python3 tests/replays/replay_plan3_sub5.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "选择能力与工具 · 子步骤5"
STEP = sub_step("plan:3", 4)

# ---- 子1 trace（需求清点：T1-T4 操作类型+出处，压缩内嵌）----
S1 = {
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

# ---- 子2 trace（能力盘点：三通道清单+逐字出处，压缩内嵌）----
S2 = {
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

# ---- 子3 trace（匹配选型：B1-B5 绑定+最小集+不加载清单，压缩内嵌）----
S3 = {
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

# ---- 子4 trace（可用性核验：B1-B5 四类核验+三态，压缩内嵌自 replay_plan3_sub4）----
S4 = {
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
        "skills && echo OK` 返回 OK。三态：已验证（出处=上述 Bash 命令返回）。",
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

# ---- 子5 clean：七 statements 五类 type_label 全覆盖，五字段忠实传导 ----
_BASE_STMTS = [
    {
        "text": "改动 T1/T2/T3 涉及的 .py 源码前，必先 invoke "
        "`factor-development` skill",
        "type_label": "skill",
        "boundary": "出处=子2 注册表清单（列表行逐字）+子3 B1 绑定提案；"
        "无假设（B1 子4 已验证）",
        "fields": {
            "skill_first": "`factor-development`--触发依据=CLAUDE.md §2 路由表"
            "『开发因子/新增因子/IC脚本』命中 T1/T2/T3（子2 ③ 强制路由"
            "核对留痕；能力名逐字取 available-skills 列表行；子3 B1 绑定）",
            "tools": "无",
            "enforce_align": "无",
            "subagent_policy": "无",
            "no_load": "无",
        },
    },
    {
        "text": "为 T1/T2/T3 写实现代码前，必先 invoke "
        "`superpowers:test-driven-development`（failing test 先行）",
        "type_label": "skill",
        "boundary": "出处=子2 ③ superpowers 强制项+子3 B2 绑定提案；"
        "无假设（B2 子4 已验证）",
        "fields": {
            "skill_first": "`superpowers:test-driven-development`--触发依据="
            "§2 superpowers 强制项『新增函数/脚本(写代码前)』（子2 ③ 核对留痕；"
            "强制项不可替代，子3 B2；能力名逐字取 available-skills 列表行）",
            "tools": "无",
            "enforce_align": "无",
            "subagent_policy": "无",
            "no_load": "无",
        },
    },
    {
        "text": "execute 阶段全部编码行为遵循 "
        "`andrej-karpathy-skills:karpathy-guidelines` 行为约束",
        "type_label": "skill",
        "boundary": "出处=子2 ③『任何编码任务(行为约束)』强制项+子3 B3 绑定"
        "提案；假设传导（子4 a2 原样）=该 plugin skill 磁盘 SKILL.md 路径未逐一"
        " ls 核实、仅凭 available-skills 列表行在册推定可加载（置信度高×影响低："
        "错误时 Skill 调用当场报错、可即时改走内联行为约束，不影响 B1/B2/B4 "
        "绑定）",
        "fields": {
            "skill_first": "`andrej-karpathy-skills:karpathy-guidelines`--触发"
            "依据=§2 路由表『任何编码任务(行为约束)』（子2 ③ 核对留痕，子3 B3；"
            "能力名逐字取 available-skills 列表行）",
            "tools": "无",
            "enforce_align": "无",
            "subagent_policy": "无",
            "no_load": "无",
        },
    },
    {
        "text": "T1/T2/T3 改 .py 前的 callers/impact 查询用 codegraph CLI 完成",
        "type_label": "工具",
        "boundary": "出处=子3 B4 绑定提案+子4 B4 已验证；无假设",
        "fields": {
            "skill_first": "无",
            "tools": "codegraph CLI=`/home/admin/.npm-global/bin/codegraph`"
            "（子4 已验证：`which codegraph` 返回该路径；新鲜度冒烟 sqlite3 查 "
            "indexed_at 返回 2026-08-05 当日；db `.codegraph/codegraph.db` 存在"
            "性 `test -f` 返回 EXISTS）",
            "enforce_align": "无",
            "subagent_policy": "无",
            "no_load": "无",
        },
    },
    {
        "text": "T4 测试执行用内置 Bash 跑 pytest，零 skill 绑定",
        "type_label": "工具",
        "boundary": "出处=子3 B5 绑定提案+子4 B5 已验证；无假设",
        "fields": {
            "skill_first": "无",
            "tools": "内置 Bash + pytest（子4 已验证：`python3 -m pytest "
            "--version` 返回 pytest 8.3.2）",
            "enforce_align": "无",
            "subagent_policy": "无",
            "no_load": "无",
        },
    },
    {
        "text": "execute 全程遵守 H15 门禁与长 pipeline 执行映射约束",
        "type_label": "门禁",
        "boundary": "出处=子2 ③ 强制路由（H15）+CLAUDE.md §3 执行映射；无假设",
        "fields": {
            "skill_first": "无",
            "tools": "无",
            "enforce_align": "H15 codegraph 前置--改已有 .py 源码前先跑 "
            "`codegraph impact <symbol>` 留痕（audit log 无记录则 PreToolUse "
            "阻断，子2 ③+§3）；长 pipeline 后台运行禁 pipe--本执行包 T1-T4 无"
            "长 pipeline 任务，条目保留为执行映射常驻约束（§3）",
            "subagent_policy": "无",
            "no_load": "无",
        },
    },
    {
        "text": "execute 阶段单线程执行，不派发子代理扇出",
        "type_label": "子代理",
        "boundary": "出处=子3 a3（红队条件未触发声明+无重型手段绑定）；无假设",
        "fields": {
            "skill_first": "无",
            "tools": "无",
            "enforce_align": "无",
            "subagent_policy": "单线程--子3 无 Workflow 多 agent/子代理扇出/"
            "长 pipeline 绑定，红队条件未触发（绑定数 4 未超阈值且无高成本项）",
            "no_load": "无",
        },
    },
    {
        "text": "`factor-ic-analyzer-workflow`、`workflow-creation`、"
        "`superpowers:systematic-debugging`、MCP `tavily-search` 本执行包不加载",
        "type_label": "不加载",
        "boundary": "出处=子3 a2 最小集显式不加载清单原样；无假设",
        "fields": {
            "skill_first": "无",
            "tools": "无",
            "enforce_align": "无",
            "subagent_policy": "无",
            "no_load": "`factor-ic-analyzer-workflow`（无 pipeline 落库/silent "
            "fallback 类需求）、`workflow-creation`（不建工作流）、"
            "`superpowers:systematic-debugging`（条件触发，非常驻绑定）、MCP "
            "`tavily-search`（无外部检索需求）--子3 最小集原样",
        },
    },
]


def _s5(stmts):
    return {
        "kind": "skill-trace",
        "major_stage": "Plan",
        "minor_stage": "CapabilityToolSelection",
        "sub_step": 5,
        "skill": "define-problem(归一化)",
        "purpose": (
            "归一化能力包：每项=1 个可独立执行的配置断言（原子+去上下文+"
            "五字段能力包）；字段忠实传导子2 注册表名/子3 绑定与最小集/子4 "
            "可用性状态；假设原样携带置信度×影响。"
        ),
        "statements": stmts,
    }


S5_CLEAN = _s5(copy.deepcopy(_BASE_STMTS))

# ---- vio1：字段篡改--stmt1 绑定名换成子3 B1 的被否替代 ----
S5_VIO1 = _s5(copy.deepcopy(_BASE_STMTS))
S5_VIO1["statements"][0]["text"] = (
    "改动 T1/T2/T3 涉及的 .py 源码前，必先 invoke `factor-summary-reporting` skill"
)
S5_VIO1["statements"][0]["fields"]["skill_first"] = (
    "`factor-summary-reporting`--触发依据=CLAUDE.md §2 路由表『开发因子/新增因子"
    "/IC脚本/分层回测』命中 T1/T2/T3（能力名逐字取 available-skills 列表行）"
)

# ---- vio2：复合句--stmt1 text「并且」连接两个可独立执行的配置断言 ----
S5_VIO2 = _s5(copy.deepcopy(_BASE_STMTS))
S5_VIO2["statements"][0]["text"] = (
    "改动 T1/T2/T3 涉及的 .py 源码前必先 invoke `factor-development` skill，"
    "并且每完成一个任务的改动后立即运行该任务的 pytest 全量验证"
)

# ---- vio3：幽灵回潮--stmt2 能力名凭记忆缩略，注册表无此名 ----
S5_VIO3 = _s5(copy.deepcopy(_BASE_STMTS))
S5_VIO3["statements"][1]["text"] = (
    "为 T1/T2/T3 写实现代码前，必先 invoke `superpowers:tdd`（failing test 先行）"
)
S5_VIO3["statements"][1]["fields"]["skill_first"] = (
    "`superpowers:tdd`--触发依据=§2 superpowers 强制项『新增函数/脚本(写代码前)』"
    "（强制项不可替代，子3 B2）"
)

# ---- vio4：不加载清单丢失--删不加载声明项，全包无「无不加载项」声明 ----
S5_VIO4 = _s5(copy.deepcopy(_BASE_STMTS))
S5_VIO4["statements"] = S5_VIO4["statements"][:7]

# ---- vio5：假设丢失--stmt3 假设传导被抹成「已确认无风险」 ----
S5_VIO5 = _s5(copy.deepcopy(_BASE_STMTS))
S5_VIO5["statements"][2]["boundary"] = (
    "出处=子2 ③『任何编码任务(行为约束)』强制项+子3 B3 绑定提案；"
    "该 skill 可用性已确认无风险"
)

CASES = {
    "clean": S5_CLEAN,
    "vio1_字段篡改": S5_VIO1,
    "vio2_复合句": S5_VIO2,
    "vio3_幽灵回潮": S5_VIO3,
    "vio4_不加载清单丢失": S5_VIO4,
    "vio5_假设丢失": S5_VIO5,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {
        k: "\n".join(json.dumps(t, ensure_ascii=False) for t in (S1, S2, S3, S4, s5))
        for k, s5 in CASES.items()
    }
    run_cases("plan:3#5 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
