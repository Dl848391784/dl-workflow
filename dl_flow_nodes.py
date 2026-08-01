#!/usr/bin/env python3
"""
dl_flow_nodes - 工作流节点树（声明式数据，唯一真源）。

自 dl_flow_engine.py 抽出（2026-07-27）：节点树（GateMech/Step/Node + _NODES +
PHASES）是声明式数据——加节点/改判据只改数据不改逻辑（design §0.2），且每个
编排节点 300-600 行 Step 定义、增长高频；机制逻辑（state/推进/gate/judge/
围栏/CLI）留在 dl_flow_engine.py，经 `from dl_flow_nodes import ...` 引用并
re-export（hooks/tests 经 engine.* 访问面不变）。

对应 designs/tui-state-machine-design.md §3。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

# ---------- 节点树定义（design §3） ----------
#
# 节点标识：<phase>:<sub_index>。sub_index=0 表示无子节点的整阶段。
# 例 "understand:1" = understand 大阶段第 1 子阶段；"execute:0" = execute 整阶段。
#
# 声明式：加节点/改审据只改数据不改逻辑。维护性兑现 design §0.2 诉求。


class GateMech(enum.Enum):
    """机械门类型（py 规则判定,快、便宜、无幻觉）。design §5。"""

    NONE = "none"  # 无机械门（子阶段间自动推进用）
    ARTIFACT_EXISTS = "artifact_exists"  # 产物文件存在（+新鲜度，§8.3 已实现）
    ARTIFACT_CONTAINS = "artifact_contains"  # 产物文件存在且含指定节（§8.3）
    TEST_PASS = "test_pass"  # pytest 通过


@dataclass(frozen=True)
class Step:
    """子阶段内一个有序子步骤（编排单位 + 门控单位）。

    §node-step-orchestration-design v2 D6：子步骤 = 门控单位（### STEP_DONE:<n> 触发 gate）；
    skill 内部 Q/A 是记录单位（不门控,只 record 落 evidence）。
    目的（purpose）engine 声明（D7），注入走 phase-rules + gate 兜底校验（D3/D4）。
    """

    kind: str  # "skill" | "tool"
    ref: (
        str  # skill 名（"define-problem"）或 工具+参数模板（"codegraph callers {sym}"）
    )
    # 骨架短名（注入「子步骤链」用，harness-prompt-optimization P0）。
    # 声明式数据：不采用「从 purpose 冒号前缀推导」（脆弱且隐式）。
    # 词表与 workflow-creation skill references/node-design.md 的子步骤摘要一致。
    short: str
    purpose: str  # 本子步骤目的（注入模型 + gate 校验依据）。声明式,单源在 engine。
    input: str | None  # 引用上子步骤产出（"step1.real_problem"）；None=无依赖（首步）
    record: bool  # 是否落 evidence（True=关键步；False=噪声如交互确认）
    gate: (
        str | None
    )  # 子步骤 rubric（judge 校验 purpose 达成否）；None=自动过（仅机械）
    # §step-engage-prefence S15：零 trace 窗口（PreToolUse 前置围栏）内，
    # 除常驻编排工具外本步额外放行的工具名（如 "Bash"/"WebFetch"/"Agent"）。
    fence_allow: tuple[str, ...] = ()
    # §step-selfcheck 步级化：提交前自查的本步 checklist（selfcheck_hint 拼接到通用段后）。
    # 只列 purpose 已披露的形式要件——质量判据仍只在 gate 黑盒（Goodhart 分层不破）。
    # None -> 仅用通用段。
    selfcheck: str | None = None
    # v2.27 载荷格式（append-trace 校验分流）：
    # "qa" = 问答配对（逼问/取证/交互步）；
    # "statements" = 结构化陈述集（归一化陈述等清单型产出步）——
    # {"text","type_label","boundary"} 逐项，触发机械预检（方案名词扫描/ID 传导）。
    record_format: str = "qa"
    # v2.33 statement_fields（仅 statements 格式有意义）：逐项 fields 对象里
    # 必备的字段键（如设计陈述八字段）——append-trace 逐键校验非空，
    # 「N 字段齐备」形式要件机械化（judge 不再数字段）。
    statement_fields: tuple[str, ...] = ()
    # v2.37 mech_checks：qa 格式步的写侧机械校验注册名（engine._MECH_QA_CHECKS
    # 查表）——词形判据下沉机械层，judge 不再为词形烧调用（v2.36 钉死保 judge
    # 判对但不保模型写对：tail_volume u:1 子2 钉死后 relaunch 仍同症两连 block）。
    mech_checks: tuple[str, ...] = ()
    # v2.37 extra_payload_keys：载荷顶层额外必填内容键——（键名, 合法前缀元组）。
    # 结构形式要件（如 u:1 子1 结论二选一）从 judge 判词变 JSON 校验，
    # 值并入 record 顶层（judge 读原始行自动可见）。
    extra_payload_keys: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class Node:
    """单个节点定义。"""

    label: str  # 显示名（中文）
    phase: str  # 所属大阶段（英文标识）
    sub: int  # 子阶段序号（0=整阶段无子节点）
    skill: (
        str | None
    )  # 该节点应载的 skill（None=靠行为约束）;engine 声明,hook 注入,模型 invoke
    artifact: str | None  # 产物标识（文件名或描述;None=无独立产物）
    gate_mech: GateMech  # 机械门类型
    gate_rubric: str | None  # 语义审据（judge prompt）;None=不跑 judge
    advance: str  # 推进方式："sub"=推进 sub_index, "phase"=推进 phase, "done"=终结
    sub_steps: tuple[Step, ...] | None = (
        None  # §orchestration v2：None=无编排(当前行为);非 None=启用子步骤注入/逐步门控
    )
    minor_key: str | None = (
        None  # 子阶段英文标识(首字母大写,evidence minor_stage 值;None=无子阶段)
    )
    # §subphase-hold-gate：True=末子步骤通过后扣留不推进（state.held_for_gate），
    # 唯一出口 release_subgate（/dl gate 路由）；与 phase 闸门 GATED_AFTER 同构。
    hold_for_gate: bool = False
    # 产物装配时机（仅 advance="phase" 编排末节点的注入第三态用）：
    # True=门栏放行后写产物（understand:4——4 子阶段陈述放行后才汇总装配）；
    # False=末子步骤内已装配（plan:3——plan.md「能力与工具」节在子6 拍板后装配，
    # hold 前已落地，放行后只需 PHASE_DONE）。advance="sub" 节点此字段不被读取。
    artifact_on_release: bool = True
    # §8.3 ARTIFACT_CONTAINS 的必含子串（节标题级，子串匹配宁宽勿窄）；
    # 仅 gate_mech=ARTIFACT_CONTAINS 时读取（plan:4 = 「执行计划与检查点」节）。
    artifact_contains: tuple[str, ...] = ()


# 节点表。<node_id> -> Node。node_id = f"{phase}:{sub}"。
# 闸门 GATED_AFTER：这些 phase 的末节点完成需用户 /dl gate 放行才进下一 phase。
#   继承现有 workflow_advance.py:39 GATED_AFTER 语义,收口到 engine 一份。
#   用 tuple 保序（显示用自然顺序）;is_gated_after 成员判定 O(n) 可接受（5 阶段）。
# 2026-07-28 用户决议：围栏只设在 plan 完成——understand 移出 GATED_AFTER
# （understand:4 末步过门控自动进 plan:1，无 understand->plan 大闸门）；
# 唯一用户裁决点 = plan:4 门栏 + plan->execute 大闸门。
GATED_AFTER: tuple[str, ...] = ("plan",)


# understand:1 子1 的形式要件（单源：purpose 模型侧与 gate judge 侧都引用）。
# 对齐原则（2026-07-25）：形式要件（覆盖度/对齐/原话/结论形式）提前告诉模型，
# 降形式性返工；质量判据（可观察/非编造/非空泛）只留在 gate 给 judge 裁量，
# 不进 purpose——防应试教育/Goodhart（模型照 checklist 填表，judge 分辨力丧失）。
# 2026-07-26 补「结论逐句出处」：demo 7ada3d8e 首轮 block 教训——模型把「报告失真/
# 需排查」式后果想象包装进结论。出处形式属形式要件（可机械核对），提前告诉模型
# 不泄质量判据；「痛点是否可观察/非空泛」仍只留 gate。
_STEP1_FORM_REQUIREMENTS = (
    "覆盖 who/pain/why-now ≥3 类，q/a 按序对齐，答案引用用户原话或会话事实；"
    "结论二选一：①问题成立=可证伪定义（具体主语+可观察痛点+场景约束）；"
    "②问题不成立=用户声明无真实痛点+原话佐证，记「字面请求即全部」。"
    "结论逐句须有出处（用户原话/会话事实）：无出处的推断禁止写进结论，"
    "只能标注「推测」另列"
)

# 子1 取证方法论（2026-07-25，demo bf2516ac/e84aee6d 教训）：
# ①模型返工时重问用户已答过的内容（「一直被要求重新确认」）——上下文已有原话可直接引用；
# ②模型把①/② 抛给用户投票，用户随手选①与事实答案矛盾 -> 硬造痛点被抓。
# 方法论指引只进 purpose（怎么取证），不进 gate（判什么）——不泄质量判据，防应试。
_STEP1_METHOD_GUIDANCE = (
    "取证方式：优先引用上下文已有的用户原话（会话事实可作佐证），"
    "禁止为凑字段重问用户已答过的内容；真正缺失的维度才用 AskUserQuestion 补问。"
    "材料不足以判①/②时，必须先 AskUserQuestion 事实性补问"
    "（问触发/痛点/后续动作等事实，如「这背后有没有要解决的实际问题？查了要做什么？」），"
    "禁止先推断凑数再被 block；补问的回答原话是②的合法佐证。"
    "who 类出处只认【用户自述】（会话中用户明确声明身份，如「唯一维护者」）；"
    "仓库事实（CLAUDE.md/git config 等）只证明「仓库由谁维护」，"
    "不能证明「当前提问者就是那个人」——无用户自述时显式问一句，"
    "或如实标注「未自述身份」，禁止拿仓库事实充当身份出处。"
    "①/② 由事实答案推导（触发/痛点/后续动作），"
    "禁止直接问用户「这是否构成真实问题」（投票与事实矛盾时以事实为准）；"
    "事实是「只是想知道/临时起意/无后续动作」→ 按②申报，"
    "禁止为凑①回填痛点（「无法判断X」=复述提问本身，必 block）"
)

# understand:2 子1 的形式要件（单源：purpose 模型侧与 gate judge 侧都引用）。
# 对齐原则同 _STEP1_FORM_REQUIREMENTS：形式要件披露降形式性返工，
# 质量判据（非脑补/非空泛/佐证合法性）只留 gate 黑盒。
# 双结论制（§3.5 #3）：「目标不成立」是合法结论——ProblemContext 可能已得出
# ②「字面请求即全部」，GoalsAndValue 必须能直通，否则逼模型编造价值。
_G2_STEP1_FORM_REQUIREMENTS = (
    "覆盖 who（受益者）/outcome（达成什么状态）/初步价值 ≥3 类，q/a 按序对齐，"
    "答案引用用户原话或会话事实；"
    "结论二选一：①目标成立=ProblemContext 每个存活问题 ≥1 目标候选；"
    "②目标不成立=用户声明字面请求即全部/无进一步诉求+原话佐证。"
    "结论逐句须有出处（用户原话/会话事实）：无出处的推断禁止写进结论，"
    "只能标注「推测」另列"
)

# understand:3 子1 的形式要件（单源：purpose 模型侧与 gate judge 侧都引用）。
# 对齐原则同 _STEP1_FORM_REQUIREMENTS：形式要件披露降形式性返工，
# 质量判据（非空泛/非形式主义/佐证合法性）只留 gate 黑盒。
# 双结论制（§3.5 #3）：「无实质约束」是合法结论——但须每个 must 目标做过
# KAOS 否定提问留痕，「未做过否定提问的无约束」= 懒得想，不算（防偷懒出口）。
_S3_STEP1_FORM_REQUIREMENTS = (
    "对 GoalsAndValue 每个 must 目标做否定提问「什么会使它失败」（KAOS 障碍分析）"
    "引出约束候选；约束类型覆盖 ≥3 类，分类按编程域（编程专用工作流，2026-07-27 修订）："
    "代码库结构（模块边界/数据契约/接口签名）/ 项目硬规则（CLAUDE.md/PROJECT.md/"
    "MODULE.md 的 H 规则与模块边界——编程工作流独有的一等约束源）/ "
    "数据契约（schema/字段/freshness）/ 环境工具链（venv/依赖/退出码语义）/ "
    "外部依赖 / 时间资源，"
    "q/a 按序对齐，用户侧约束（deadline/人力/权限）缺口用 AskUserQuestion 补问"
    "（优先上下文已有原话，禁重问已答内容）；"
    "结论二选一：①约束成立=每 must 目标 ≥1 约束候选或显式「无约束+理由」；"
    "②无实质约束=所有 must 目标均做过否定提问留痕后仍无候选。"
    "结论逐句须有出处（用户原话/会话事实/工具留痕）：无出处的推断禁止写进结论，"
    "只能标注「推测」另列"
)

# understand:4 子1 的形式要件（单源：purpose 模型侧与 gate judge 侧都引用）。
# 对齐原则同 _STEP1_FORM_REQUIREMENTS：形式要件披露降形式性返工，
# 质量判据（非空泛/非脑补/追溯放水）只留 gate 黑盒。
# 双结论制（§3.5 #3）编程域收紧（编程专用工作流，2026-07-27 修订）：
# 代码行为几乎总是可执行验证——「目标只能定性验收」是稀有合法结论，须逐目标
# 留痕理由且理由须说明「为何不可执行验证」（合法剩余 ≈ UX/可读性/架构审美类）；
# 可执行验证的目标标定性 = 偷懒出口（防双结论制被滥用）。
_S4_STEP1_FORM_REQUIREMENTS = (
    "对 GoalsAndValue 每个 must 目标做验收视角提问「怎么知道它达成了」"
    "（INCOSE verification point-of-view：想象自己在执行验收事件）引出成功标准候选；"
    "双向追溯逐项列出（每 must 目标 ≥1 标准候选或显式「纯定性目标+理由」；"
    "每候选回溯 ≥1 目标，孤儿候选剔除或退回补问），q/a 按序对齐，"
    "用户侧期望（「什么结果你会满意」）缺口用 AskUserQuestion 补问"
    "（优先上下文已有原话，禁重问已答内容）；"
    "结论二选一：①标准候选成立=每 must 目标 ≥1 候选或显式定性+理由；"
    "②目标只能定性验收=稀有合法结论（编程域代码行为几乎总是可执行验证），"
    "须逐目标留痕理由且理由须说明「为何不可执行验证」。"
    "结论逐句须有出处（用户原话/会话事实）：无出处的推断禁止写进结论，"
    "只能标注「推测」另列"
)

# 「方案名词」裁量点钉死（2026-07-30 tail_volume understand:2 子4 block 复盘）：
# 首判模型把 solution-free 核查落在谓语（「按真实数值判定=outcome」），judge 裁量
# 落在主语（_macros.html 等模板文件名入主语=违规）——同一判据两种读法
# （§3.5 #4 判据留白=方差）。操作化定义属形式要件（主语词性的结构检查），
# 披露进 purpose/selfcheck 不 Goodhart（§3.5 #2）。
# v2.24 修订（2026-07-30，tail_volume understand:3 子4 五连 block 复盘）：
# 只钉模型侧不够——judge 输入面仍只有黑盒判词，解释轮间漂移（类名入主语→
# 实现指针段→动词词形逐轮收紧）。双侧引用（purpose/selfcheck + gate），
# 对齐 _DS_STEP1_FORM_REQUIREMENTS 先例。
# 单源常量：claim normalization 同构族 5 个 Step 的 purpose/selfcheck/gate 引用。
_SOLUTION_FREE_SUBJECT_RULE = (
    "「方案名词」操作化：主语只许 outcome-level 概念（用户可见的状态/数字/信号），"
    "不得含模板文件名/类名/CSS 类/函数名/字段名/管线名/组件名等实现侧名词；"
    "file:line 与实现指针留在边界字段与 evidence，不进主语"
)

# 范围陈述的动词裁量点钉死（v2.24，2026-07-30 tail_volume understand:3 子4
# 五连 block 实证）：judge 按词形判「调整/创建/扩展/手改/格式化」=实现动词，
# 逐轮收紧到范围命题不可表述（in/out 的构成性谓语就是「允许/禁止改动」），
# 用户强制放行收场。动词按指向判不按词形判——方案性在指向实现层还是
# outcome 层，不在词本身（与主语规则同构）。
# 只适用 ScopeAndConstraints 子4：目标/标准陈述里「做一个X」仍是真
# solutioneering 信号（GoalsAndValue/SuccessCriteria 各 gate 不动动词判据）。
_SCOPE_VERB_RULE = (
    "动词按指向判、不按词形判：指向代码实现动作（改哪个文件/函数/模板/CSS 类）"
    "=实现动词违规；指向用户可见状态或范围赋予（允许/禁止被改动、展示、计算、"
    "覆盖、读取）=合法——in/out 范围陈述的构成性谓语「允许/禁止改动」合法，"
    "判它违规=把范围命题判成不可表述"
)

# 因果链「证据出处」裁量点钉死（v2.36，2026-08-01
# tail_volume_acceleration_annualized understand:1 子2 两连 block 复盘）：
# 模型主链每环标【evidence：未实测】并答自查「是」——它把「未实测/推断」
# 状态标注当合法出处形态（§3.5 #9 第三形态=操作化分歧，非注意力失败）；
# 且被 engage 围栏 deny 一次 Bash 后错误泛化为「本步禁取证」，把取证全推给
# 子3（.wf_fence.log 14:12:33 engage_fence_deny step=2 tool=Bash 实锤）。
# 操作化：主链每环必须实际证据指针（Read 可达，子2 合法且足够的通道）；
# 「未实测」只允许在竞争假设/排除理由分支（子3 取证消化）；Bash 被围栏拦
# 是设计内不等于禁取证。双侧引用（purpose/selfcheck + gate），
# 对齐 _SOLUTION_FREE_SUBJECT_RULE 先例。
# v2.37 补（同日晚 20:19 relaunch 复发复盘——v2.36 钉死保 judge 判对，
# 不保模型写对）：①「读出即事实」与「读出后推出」未分清——att1 Why4
# 「过滤 NaN 后可能剩 1-5 天（:630-647）」有 file:line 但量级是推断，
# 模型以为 Read 背书即合规；②挖不动时无正面动作——att2 只能给 Why5 贴
# 「未实测/推断」标签。补正反范例 + 降格句型，词形部分下沉
# mech_checks=causal_ring_no_untested（链环含禁词 append-trace 当场拒）。
_CAUSAL_CHAIN_EVIDENCE_RULE = (
    "「证据出处」操作化：主因果链（5 Whys 各 Why 环）每环须为实际证据指针"
    "（file:line/数据值/日志原文/用户原话——Read 是本步合法且足够的取证通道）；"
    "「未实测/推断」是取证状态标注、不算证据出处，只允许出现在根因候选"
    "（竞争假设）与排除理由分支（留子3 取证消化）——把链环全写成候选假设"
    "形态=主链缺失，判 block；根因未定时候选根因按竞争假设分支处理，"
    "本步要求链条每环可追溯、不要求根因已证明（证明归子3/子4，要求已证明"
    "=判据无通过路径）；Bash 被 engage 围栏拦是设计内，不等于禁取证。"
    "「读出即事实」与「读出后推出」须分清——正例「Why2=format_percentage "
    "decimals=2（formatters.py:92-104）」读出即事实；反例「Why4=过滤 NaN 后"
    "可能剩 1-5 天（:630-647）」——file:line 背书的只是代码文本，量级是推断，"
    "不算出处。挖不动实测的深层：整体降格进竞争假设分支并标「待子3取证」，"
    "主链挖到实测层即终止——不悬空、不贴「未实测/推断」充数（链环文本含"
    "「未实测/待实测/未验证/待验证/可能」append-trace 当场机械拒）"
)

# 交互读回步的提问拆分规则（2026-07-30 tail_volume understand:4 子5 审计）：
# 模型把 4 个裁决问题捆绑一轮 AskUserQuestion，回答时长由最难项决定
# （实测 370s > 300s prompt-cache TTL）——下一轮 255,670 token 上下文
# 全量非缓存重读（占整个 understand:4 窗口非缓存 input 的一半）。
# 拆分后快答轮落在 TTL 内走 cache read（0.1x），硬核裁决至多击穿一次，
# 实测口径省 60-70%。属提问编排形式要件，披露进 purpose 不 Goodhart；
# 不加进 selfcheck——问完才发现捆绑已晚，只能靠 purpose 前置披露。
# 单源常量：8 个读回确认/读回装配 Step 的 purpose 统一引用。
_INTERACTIVE_CHUNKING_RULE = (
    "逐问原则（防 cache TTL 击穿）：提问按预计用户思考时长分组——"
    "快答项（认同/接受/选定/无改）合并一轮先问；"
    "预计 >4 分钟思考的硬核裁决（拍板/圈定/冻结类规范裁决）单列一轮后问，"
    "禁与快答项捆绑（捆绑则由最难项决定总时长，>5 分钟未作答击穿 prompt cache，"
    "下一轮全量重读上下文）；读回材料在首轮提问前以文本完整呈现，"
    "让用户边读边答快答项"
)

# 「复合句」裁量点钉死（v2.32，2026-07-31 tail_volume plan:1 子5 / plan:2 子4
# 审计）：两处归一化步各三连 block + 用户强制放行——judge 按词形（「+」「然后」
# 连接、括号枚举、多项「、」罗列）判复合，与同项携带八字段/五字段的形式要件
# 自相矛盾（字段全带必产出枚举形态，枚举形态必被判复合，判到升级死路）；
# 且判词失真（att1 称「数十个『。』断句」，重放实际条目 ≤1 个「。」）。
# 通过的 ProblemContext 子5 trace 实证：合法形态本来就是「单句决策 + 字段
# 键值枚举」。原子性按独立性判、不按词形判（与 _SCOPE_VERB_RULE 同构）。
# 只适用 DesignSolution 子5 / TaskBreakdown 子4（字段携带型归一化步）：
# ProblemContext 子5 等痛点陈述步的「和/以及/同时」多痛点判据不动。
# 单源常量：两个 Step 的 purpose/selfcheck（模型侧）与 gate（judge 侧）引用。
_ATOMIC_ITEM_RULE = (
    "原子性按独立性判、不按词形判：字段键值枚举（「字段名=值」以「；」「+」"
    "「、」或括号携带）与一项的内含流程 = 结构化携带，不算复合；"
    "复合句 = 一项合并 ≥2 个可独立成立的项（可分别拍板/分别提交）"
)

# plan:1 子1 的形式要件（单源：purpose 模型侧与 gate judge 侧都引用）。
# 对齐原则同 _STEP1_FORM_REQUIREMENTS：形式要件披露降形式性返工，
# 质量判据（非编造/非漫游）只留 gate 黑盒。
_DS_STEP1_FORM_REQUIREMENTS = (
    "现状地图四要素：①涉及模块与现有实现（codegraph 定位+Read 核实）；"
    "②可复用点与扩展点（已有可复用函数/类，禁凭印象）；"
    "③调用方与影响面（codegraph callers/impact）；"
    "④数据契约现状（paths.py/schema/跨模块数据格式，Bash/Read 核实）；"
    "codegraph 新鲜度前置留痕（>72h 先 sync）；"
    "每条事实附 codegraph 原始输出或 file:line 出处，q/a 按序对齐；"
    "勘察不到的显式标「未知」，范围由 understand.md 问题陈述+范围清单框定"
)

# plan:1 子2 的形式要件（单源，对齐原则同上）。
# 双结论制（§3.5 #3）：「设计空间唯一」是合法结论——但须逐维度论证，
# 无论证的「唯一」= 懒得发散，不算（防偷懒出口，同 _S3_STEP1_FORM_REQUIREMENTS）。
_DS_STEP2_FORM_REQUIREMENTS = (
    "≥3 个代码级候选方案（每个=改哪个模块/哪个函数/新增什么文件/复用哪个"
    "现有实现），或②「设计空间唯一」的逐维度唯一性论证；"
    "每候选锚定子1 事实条目（禁凭空 API）；"
    "候选间架构维度实质差异声明（换模块归属/换数据结构/复用 vs 新建/"
    "换执行时机/换数据流——换皮不换骨=一个方案）；"
    "禁评估禁排序（评估是子4 的事），q/a 按序对齐；"
    "用户既有想法平权入列（不预设首选）"
)

# plan:2 子1 的形式要件（单源：purpose 模型侧与 gate judge 侧都引用）。
# 对齐原则同 _DS_STEP1_FORM_REQUIREMENTS：形式要件披露降形式性返工，
# 质量判据（非二次创作/非编造）只留 gate 黑盒。
# judge 输入面（§3.5 #11）：design.md 文件 judge 读不到——要素原文必须
# 引用进 trace 正文，judge 从 evidence 判一致性（plan:1 §3 实现注同款）。
_TB_STEP1_FORM_REQUIREMENTS = (
    "三清单齐备：①原子改动要素清单（file→function→改动类型：改/增/删，"
    "逐条赋要素 ID E1/E2/...）；②验收包清单（逐条 SuccessCriteria 附 ID）；"
    "③假设清单（含置信度×影响，原样转录）；"
    "每条附出处（design.md 行号或 evidence 指针）且要素原文引用进 trace 正文；"
    "新增候选（设计包没有的要素）/设计包内部矛盾显式标注或显式「无」，q/a 按序对齐；"
    "只提取不创作（本步是全节点保真判定基线）"
)

# plan:2 子2 的形式要件（单源，对齐原则同上）。
# 双结论制（§3.5 #3）：「单阶段不可拆」是合法结论——但须论证 H9 内一次可完，
# 无论证的「不可拆」= 懒得切分，不算（防偷懒出口，同 _DS_STEP2_FORM_REQUIREMENTS）。
_TB_STEP2_FORM_REQUIREMENTS = (
    "执行单元切分：每单元=自带完整测试周期且值得 reviewer 门禁的最小单位"
    "（setup/文档折叠进需要它的单元），纵向切片优先（横向按层切须显式辩护）；"
    "每单元附 H9 预算估计（≤3 文件 ≤200 行）+ 承接要素 ID + 依赖出处；"
    "依赖 DAG 拓扑排序留痕（被依赖者先行，codegraph callers 取证）；"
    "TDD 序内嵌（每单元 failing test 先行）；"
    "阶段划分：阶段=可整体验证+可整体提交+可回滚的单元组，每阶段附断点验证方法，"
    "或②「单阶段不可拆」的论证（H9 内一次可完）；"
    "设计包字段⑧已预选切片的精化不重做，q/a 按序对齐；"
    "只提案不拍板（断点位置是用户风险偏好，子5 裁决）"
)

# plan:3 子1 的形式要件（单源：purpose 模型侧与 gate judge 侧都引用）。
# 对齐原则同 _TB_STEP1_FORM_REQUIREMENTS：形式要件披露降形式性返工，
# 质量判据（非二次创作/非编造）只留 gate 黑盒。
# judge 输入面（§3.5 #11）：plan.md 文件 judge 读不到——需求原文必须
# 引用进 trace 正文，judge 从 evidence 判（plan:2 子1 同款）。
_CTS_STEP1_FORM_REQUIREMENTS = (
    "逐任务操作类型需求清单齐备：每任务/阶段标注操作类型"
    "（代码改动[改 .py=H15 触发信号]/测试执行/长 pipeline[后台禁 pipe 信号]/"
    "外部检索/数据读取[parquet 等]/子代理扇出/文档装配）；"
    "每条附任务 ID 出处且 plan.md 原文引用进 trace 正文；"
    "新增候选（plan.md 没有的需求）显式标注或显式「无」，q/a 按序对齐；"
    "只提取不创作（本步是全节点保真判定基线）"
)

# plan:3 子2 的形式要件（单源，对齐原则同上）。
# 双结论制（§3.5 #3）：「内置工具足够、零 skill」是合法结论——但须逐任务说明，
# 无说明的「零绑定」= 懒得盘点，不算（防偷懒出口，同 _TB_STEP2_FORM_REQUIREMENTS）。
# 幽灵能力防御（capability-tool-selection-substeps-design §1.3 C1）：
# 能力名必须逐字引用注册表出处——训练记忆里的名字不算数。
_CTS_STEP2_FORM_REQUIREMENTS = (
    "能力注册表三通道清单齐备：①skill 注册表（会话 available-skills 列表+"
    "磁盘用户级 ~/.claude/skills/项目级 .claude/skills/ 目录）；"
    "②工具/CLI/MCP（内置工具集+codegraph CLI+MCP server 列表）；"
    "③强制路由核对（CLAUDE.md §2 触发词逐任务匹配+H15 改 .py 前 codegraph 留痕+"
    "superpowers 触发[写代码前 TDD/测试失败 systematic-debugging/任何编码 "
    "karpathy-guidelines]）；"
    "能力名逐字引用注册表出处（列表行/文件路径），禁凭训练记忆；"
    "②「内置工具足够、零 skill」的逐任务说明或显式 skill 候选，q/a 按序对齐"
)

# plan:3 子3 的形式要件（单源，对齐原则同上）。
# tool overload 防线（design §4 实证：选择准确率随工具数坍塌 95%→71%）：
# 最小集判据——无绑定=不加载，不加载什么与加载什么同等重要。
_CTS_STEP3_FORM_REQUIREMENTS = (
    "需求×能力映射：每条绑定附理由（覆盖判据引用子2 trigger/description 出处，"
    "禁凭名字猜）+被否替代；"
    "最小集（每能力绑定 ≥1 需求，无绑定=不加载）；"
    "重型手段（Workflow 多 agent/子代理扇出/长 pipeline）附成本相称辩护；"
    "强制项优先（项目强制项不可被「更顺手」的非强制项替代）；"
    "双向追溯矩阵（每需求有绑定或显式「内置足够」；每能力绑定到需求，双向无漏）；"
    "红队留痕或条件未触发声明，q/a 按序对齐；"
    "只提案不拍板（映射取舍是用户偏好，子6 裁决）"
)

# plan:4 子1 的形式要件（单源，对齐原则同 _CTS_STEP1_FORM_REQUIREMENTS）。
# 本节点是首个四源聚合节点（execution-plan-checkpoints-substeps-design §1.2
# 关键不对称第八种）——聚合失真（E7）防御 = 五类清单基线 + 原文入 trace；
# judge 输入面（§3.5 #11）：design.md/plan.md/understand.md 三个文件 judge
# 都读不到——四源原文必须引用进 trace 正文，judge 从 evidence 判。
_EPC_STEP1_FORM_REQUIREMENTS = (
    "控制结构输入五类清单齐备：①任务 DAG 与阶段边界（plan.md 执行步骤节："
    "任务 ID/依赖/阶段分组）；②能力绑定（plan.md 能力节：必先 skill/子代理策略）；"
    "③验收包（understand.md 六字段，时机=triggered 项显式标注——"
    "其落点即检查点候选）；④假设清单汇总（design.md + plan.md 假设项）；"
    "⑤不可逆操作候选（执行步骤中含删改/外发/force 语义的改动点）；"
    "每条附源出处且四源原文引用进 trace 正文；"
    "新增候选（四源没有的对象）显式标注或显式「无」，q/a 按序对齐；"
    "只提取不创作（本步是全节点保真判定基线）"
)

# plan:4 子2 的形式要件（单源，对齐原则同上）。
# execute 愿景（2026-07-28 用户决议）：executor 不再自行分析 + 多 subagent
# 并行——任何需要"执行时想"的东西都是 plan 漏项：失败路由必须预定义、
# 判据必须零判断词（executor 无判断能力，「确认/检查/合理」式判据=检查点
# 虚设 E1）、并行分组与互斥面必须 plan 期定死。
_EPC_STEP2_FORM_REQUIREMENTS = (
    "调度与检查点方案：①调度四件——并行分组（任务 DAG 拓扑分层，同层无依赖"
    "可并行派发）/文件互斥面（各 worker 改动文件清单从执行包改动点字段计算，"
    "组内交集须为空）/worker 任务包映射（任务 ID→派发单元，零上下文可执行）/"
    "subagent 返回契约（测试输出/改动文件清单/file:line 证据形式清单）；"
    "②检查点三属性——通过判据（零判断词：命令+退出码/断言，承接验收包 ID，"
    "禁「确认/检查/合理」类动词）/失败路由（返工本组/回滚至上一检查点/"
    "升级用户，三选一预定义，禁「视情况」）/类型（自动继续 vs 用户暂停；"
    "不可逆操作前的检查点强制用户暂停）；"
    "③每检查点 goal anchoring 重述句（原目标+当前位置两成分）；"
    "④密度论证（按可逆性×爆炸半径逐检查点给类型建议）或「零用户检查点」"
    "复利论证（逐步成功率估计+整体下界+全链可逆声明）；"
    "红队留痕或条件未触发声明，q/a 按序对齐；"
    "只提案不拍板（密度与类型是用户风险裁决，子5 拍板）"
)

_NODES: dict[str, Node] = {
    # ---------- understand（含 4 子阶段;design §3 / workflow_advance.py:47 SUBPHASES 同源）----------
    "understand:1": Node(
        label="理解问题和背景",
        phase="understand",
        sub=1,
        skill="define-problem",  # §skill-injection-link:载 define-problem(逼问问题定义/验真/钉约束/搜证据),契合 sub1「验真问题是否真实」
        artifact=None,
        gate_mech=GateMech.NONE,
        # §orchestration v2 D6/D7：纯子步骤门控（删过渡「≥3 Q/A」rubric）。
        # 5 子步骤逐步 STEP_DONE gate；目的 engine 声明，注入 phase-rules + gate 兜底。
        # skill 内部 Q/A 不门控，record 步落 evidence（step_needs_evidence 读文件喂 judge）。
        gate_rubric=None,  # 子阶段级 rubric 删除（被 sub_steps 逐步门控取代）
        advance="sub",  # 末子步骤 STEP_DONE:6 通过即推进 sub_index（_handle_step_done 调 advance_state）
        sub_steps=(
            Step(
                kind="skill",
                ref="define-problem",
                short="逼问定义",
                # purpose 含形式要件（模型可见，降形式性返工）；
                # 质量判据不进 purpose（防应试填表），只在下方 gate 给 judge。
                purpose=(
                    f"逼问问题定义：{_STEP1_FORM_REQUIREMENTS}。"
                    f"{_STEP1_METHOD_GUIDANCE}"
                    "结论作为载荷顶层「结论」键提交（①或②开头——append-trace "
                    "机械校验存在性与前缀，缺键/前缀错当场拒，不进入 gate）"
                ),
                input=None,
                record=True,
                # 步级自查（全部已在上方 purpose 披露，无质量判据泄漏）
                selfcheck=(
                    "who/pain/why-now ≥3 类都覆盖了吗？每条 a 是用户原话/会话事实，"
                    "还是我推断补全的（推断只能标「推测」另列，禁止包装成原话或「真实回答」）？"
                    "结论选了①还是②、每句都有出处吗（载荷顶层「结论」键，①/② 开头）？"
                ),
                # 门控分工：子1 只管「定义质量」（结构可判项），真值判给子3（验真）+ 子5（用户认可）。
                # 双合法结论（demo 2026-07-25 行3）：问题成立要可证伪；问题不成立要原话佐证——
                # 否则诚实回答「没有痛点」永远过不了，逼模型编造痛点（行2「好奇心缺口」被 judge 识破）。
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace 且 sub_step==1 的记录；"
                    f"形式要件：{_STEP1_FORM_REQUIREMENTS}。"
                    "（结论的存在性与①/②前缀已由 append-trace 机械校验——"
                    "judge 不重复判缺结论，只判结论内容与出处质量。）"
                    "质量判据（从严裁量）：各答案非空泛复述；①的痛点须可观察、"
                    "非编造包装（「好奇心缺口」式伪痛点判 block）；②的无痛点声明"
                    "须以原话为证——本步 AskUserQuestion 事实性补问的回答原话"
                    "（含用户否认有痛点）是合法佐证；用户从未被问及时的「未提及」"
                    "不算佐证（须先问再引），无佐证=偷懒判 block；逼问不足 3 类判 block。"
                    "who 类出处只认用户自述（会话中用户明确声明身份）；"
                    "仓库事实（CLAUDE.md/git config 等）不能证明当前提问者身份，"
                    "作出处=无出处推断，判 block；「未自述身份」的如实标注可接受。"
                ),
                # v2.37：结论二选一从判据惯例升级为载荷顶层必填键（存在性+①/②
                # 前缀机械校验）——tail_volume u:1 子1 att1 缺结论白烧一轮 judge。
                extra_payload_keys=(("结论", ("①", "②")),),
            ),
            Step(
                kind="skill",
                ref="causal-inference-root-cause",
                short="拆解深挖",
                # 拆解深挖（2026-07-25 设计决议）：逼问出的是「用户声称的问题」，
                # 须先横向拆（复合痛点 MECE 切分，防一捆问题混进后续）再纵向挖（因果链到根因，
                # 防拿症状当问题）。拆解必须在验真之前——拿一捆问题/症状去搜证据 = 白搜。
                # 复合问题的其余项不丢弃：带已验证陈述落 evidence，供后续 dl 实例接续。
                purpose=(
                    "拆解深挖：①单一/复合判定——复合痛点按 MECE 拆成原子问题清单"
                    "（互不重叠、合起来覆盖全部痛点；单一则声明「无复合」理由）；"
                    "②每个原子问题沿因果链挖到根因（invoke causal-inference-root-cause，"
                    "5 Whys/鱼骨/时序分析），每环必须有可观察证据，禁纯叙事——"
                    f"{_CAUSAL_CHAIN_EVIDENCE_RULE}；"
                    "③每个问题 ≥1 个竞争假设 + 排除理由（或当前假设为何最可能）；"
                    "④区分近因与根因，标注置信度。"
                    "输出走 evidence skill-trace（q/a 数组），不建单独 md。"
                ),
                input="step1.real_problem",
                record=True,
                selfcheck=(
                    "单一/复合判定了吗（复合→MECE 原子清单合起来覆盖全部痛点；"
                    "单一→附「无复合」理由）？每个原子问题 ≥2 环因果链、"
                    "主链每环是实际证据指针吗（「未实测/推断」标注不算出处，"
                    "只允许出现在竞争假设分支——"
                    f"{_CAUSAL_CHAIN_EVIDENCE_RULE}）？"
                    "每个问题有 ≥1 竞争假设+排除/保留理由吗？近因/根因区分和置信度标了吗？"
                ),
                # 门控分工：judge 只判结构完整性（清单/链/竞争假设/出处），
                # 根因对不对归子3验真 + 子5用户认可（§3.5 三层分工）。
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace 且 sub_step==2 的记录；"
                    "形式要件：①原子问题清单（≥1 个；单问题须附「无复合」理由）；"
                    "②每个问题 ≥2 环因果链到根因，主链每环为实际证据指针"
                    f"（{_CAUSAL_CHAIN_EVIDENCE_RULE}）；"
                    "③每个问题 ≥1 竞争假设 + 排除/保留理由；④近因与根因区分明确。"
                    "质量判据（从严裁量）：证据非编造、非循环复述提问；"
                    "根因非症状换说法（「X 慢因为 X 运行慢」式同义反复判 block）；"
                    "竞争假设非稻草人（明显不成立拿来凑数判 block）。"
                ),
                # v2.37：链环禁词（未实测/待实测/未验证/待验证/可能）写侧机械拒——
                # v2.36 钉死后 relaunch 仍两连 block，词形部分下沉机械层。
                mech_checks=("causal_ring_no_untested",),
            ),
            # 子3/子4（2026-07-26 重设计，designs/step3-verify-redesign-design.md）：
            # 旧单步「验真」对 F1 主张不可检验/F2 确认偏误/F5 证据不可追溯/F7 单视角
            # 四类失效无防御。按失效模式族拆两步：子3 管取证过程（双向+多源），
            # 子4 管判断质量（质检+对抗+裁决）。用户硬约束：禁 tavily/WebSearch。
            Step(
                kind="tool",
                ref="Agent(外部取证子代理,每原子一个并行) / codegraph impact {sym}",
                short="双向取证",
                # v2.38（2026-08-01 tail_volume 子3 审计）：外部取证卸子代理——
                # 子3 原是主会话工具密度大户（46 msgs/26 tool calls/6.2M cache read，
                # curl 原始输出全堆主上下文），且外部源 ~40% 失败（arXiv http+无UA
                # 静默空/GitHub 401 没带认证头/WebFetch 域验证全挂/SE 页面 403）——
                # 命令模板逐字内置 fetch-prompt（当日诊断验证版）。主会话只做
                # claim 可检验化 + 并行派发 + 原文收录 + 内部仓库层。
                # 规则考古：反证时序留痕源自 demo fbdb6ebd 子3 block 实录；
                # 禁探查凭证源自 demo 121320fe（扫 env 找 token 被安全分类器拦截）；
                # 禁 tavily/WebSearch 是 2026-07-26 用户硬约束（额度低），
                # 2026-08-01 用户复核维持（curl 模板修复后不需要解禁）。
                purpose=(
                    "双向取证（外部层卸子代理，主会话只收蒸馏报告）："
                    "①主张可检验化（主会话做）——每个原子问题 → 可证伪 claim + "
                    "事先写死「什么证据会证实/什么证据会证伪」；不可检验的主张退回子2，"
                    "不进入取证。"
                    "②外部五层源卸子代理——`python3 ~/.dl-workflow/dl_flow_engine.py fetch-prompt` "
                    "生成子代理 prompt 骨架（自动携带子1-2 trace + 已验证命令模板 + 返回契约），"
                    "只在末尾 claim 补充区逐原子填 claim（骨架其余一字不动，禁手拼）；"
                    "每原子一个 Agent 子代理**同一条消息并行单发**；"
                    "子代理蒸馏报告**原文收录**进本步 trace（提及/概括转述不算记录——"
                    "报告结构天然保证反证先/支持后时序可读）；"
                    "禁 tavily_search/WebSearch/WebFetch（WebFetch 本环境域验证全挂）。"
                    "③内部仓库层（主会话自查）——codegraph 新鲜度前置（>72h 先 "
                    "codegraph sync，查询结果留痕）+ Read/Grep/Bash 查数据，"
                    "证实/证伪问题在本仓存在 + 查已有解法。"
                    "禁拿训练记忆冒充外部证据（无 URL/工具留痕的「业界通常」= 编造）。"
                ),
                input="step2.problem_list",
                record=True,
                selfcheck=(
                    "每个原子问题有可检验 claim（含证实/证伪判定标准）吗？"
                    "fetch-prompt 骨架只补了 claim 区、其余一字未动吗？"
                    "每原子一个子代理并行单发、蒸馏报告原文收录进 trace 了吗"
                    "（提及/转述不算记录）？内部仓库层 codegraph 新鲜度查询留痕了吗？"
                ),
                # S15 前置围栏：本步合法工具 = 内部仓库层（Bash）+ 取证子代理（Agent）；
                # 子代理进程内的 curl 经同一 PreToolUse 围栏、本步声明 Bash 故放行；
                # WebFetch 环境性弃用（2026-08-01 诊断）移出声明。
                fence_allow=("Bash", "Agent"),
                # v2.38：报告收录形式要件机械化——judge 重放实证旧形态（无报告项）
                # 也被判 PASS（内容丰富被当实质满足），形式核验下沉机械层。
                mech_checks=("fetch_report_recorded",),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace 且 sub_step==3 的记录；"
                    "形式要件：每个原子问题有可检验化 claim（含证实/证伪判定标准）；"
                    "子代理蒸馏报告原文收录——报告收录项的存在性已由 append-trace "
                    "机械校验，judge 不重复判缺失，只判收录真实性（提及/概括转述"
                    "冒充原文收录判 block）——报告含"
                    "反证查询（先）→支持证据（后）分段 + 五层状态表（每层指针或"
                    "「未取证+原因」合法标记）；codegraph 新鲜度查询留痕。"
                    "质量判据（从严裁量）：凡声称外部证据须带可追溯指针（真实 URL/工具调用留痕），"
                    "用训练记忆冒充外部证据 = 编造，判 block；"
                    "证据须直接针对 claim 谓词，非泛泛行业常识。"
                ),
            ),
            Step(
                kind="tool",
                ref="推理(三关质检+四态合成) / Agent(红队子代理,条件触发)",
                short="质检裁决",
                # 红队纪律 a-d 已机械化进 redteam_prompt()（v2.14「AI 定写什么，
                # 脚本定怎么写」）：a.携带子1-3 证据；b.单层；c.Read 为主；
                # d.证据不足下 verdict 不重取证。purpose 只留触发条件+调用方式。
                # 考古出处（P2 移自 purpose 原文）：a 无文件清单时嵌套层盲猜路径
                # 61 次 Read 全空；b 嵌套放大实录：3 嵌套 116k boot + 82 Read
                # 系统性重取证，且嵌套层出现问用户的角色错乱；c 实录 11 次
                # No such tool（Glob/Grep/codegraph 不存在）、Bash 21 次被 S15 空拒；
                # 「10/10 pass」式汇总声明 demo 实录被判 block。
                purpose=(
                    "质检裁决（不做新搜索，只审子3证据+下结论）："
                    "①证据三关质检——针对性(直接针对 claim 谓词)/独立性(来源互不转载)/"
                    "可追溯(URL、file:line 可复查)，三关不全过的证据不计数；"
                    "trace 须逐项可验证——每条计数证据逐条列出三关结果（E1…En × 三关），"
                    "「10/10 pass」式汇总声明不算记录；"
                    "②条件触发对抗复核——verdict 决定大方向/大改动、或证据相互冲突时，"
                    "起独立红队子代理尝试推翻初步结论（独立上下文，只给证据不给结论"
                    "——该约束指红队**输入**：不得把子4 初步结论喂给红队，"
                    "redteam-prompt 模板已机械保证；红队**输出**按纪律必含四态 "
                    "verdict，属合规非违规）："
                    "用 `python3 ~/.dl-workflow/dl_flow_engine.py redteam-prompt` 生成红队 "
                    "prompt（自动携带子1-3 证据+对抗纪律），Agent 工具单发起，"
                    "禁止手拼 prompt；触发条件写死，不得自定义「不需要复核」豁免；"
                    "红队输出须**原文收录**进本子步 trace（完整粘贴其 "
                    "verdict/推理链/置信度），「已发起红队」式提及或概括转述不算记录；"
                    "③四态结论合成——证实/证伪/部分成立/证据不足（证据不足是合法结论）"
                    "+ 推理链 + 置信度；"
                    "④按 verdict 处置问题集——证伪项剔除（留剔除理由）/部分成立项收窄到"
                    "已证实边界/证据不足项带标记进入读回；处置后问题集 = 子5 唯一输入。"
                ),
                input="step3.traces",
                record=True,
                selfcheck=(
                    "每条计数证据逐条列出三关质检结果了吗（E1…En × 三关，汇总声明不算记录）？"
                    "红队触发条件满足时起了红队子代理吗（redteam-prompt 生成、禁止手拼）？"
                    "红队输出已返回并原文收录进本子步 trace 了吗（提及/概括转述不算记录；"
                    "红队未归就先 append=占位，append-trace 机械拒）？"
                    "每个原子问题有四态 verdict+推理链+置信度吗？"
                    "处置后问题集与 verdict 逐项一致吗（证伪剔除+理由/部分收窄/不足标记）？"
                ),
                # S15 前置围栏：条件触发红队子代理（Agent）；子代理进程内
                # Read/Grep 在常驻集，无需声明。
                fence_allow=("Agent",),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace 且 sub_step==4 的记录；"
                    "形式要件：每条计数证据有三关质检记录；每个原子问题有四态 verdict"
                    "+ 推理链 + 置信度；处置后问题集与 verdict 逐项一致"
                    "（证伪项已剔除+理由、部分成立项已收窄、证据不足项已标记）。"
                    "质量判据（从严裁量）：红队触发条件满足时，本子步 trace 须原文收录"
                    "红队输出（四态 verdict+推理链+置信度）——红队输出含 verdict 是"
                    "纪律 4 的要求、属合规非违规；只给证据不给结论仅约束红队**输入**"
                    "（不得含子4 初步结论），由 redteam-prompt 模板机械保证、不重复判；"
                    "仅提及/概括转述红队而未原文收录其输出判 block；"
                    "verdict 与证据间推理链非跳跃；"
                    "质检放水（明显不针对 claim 的证据被计数）判 block。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem",
                short="归一化陈述",
                # 归一化陈述（2026-07-26 重设计，
                # designs/step5-step6-statement-readback-redesign-design.md）：
                # 职能 = claim normalization（原子+去上下文+verdict 传导），不是压缩话术。
                # RCA：problem statement 取证前写（子1），root cause statement 证据检验后写（子5）。
                purpose=(
                    "归一化陈述：对子4处置后问题集逐项产出归一化问题陈述——"
                    "①原子（单句≤1个独立痛点，「和/以及/同时」连接多痛点=复合未拆净，回子2重拆）；"
                    "②去上下文（脱离本会话可独立理解：主语+动词+约束自包含）；"
                    "③携带 verdict 边界与置信度（部分成立项陈述只覆盖已证实边界）；"
                    "放不进一句=未定义完。"
                    '载荷格式：statements 逐项 {"text":单句陈述,'
                    '"type_label":verdict（证实/部分成立/证据不足——证伪项已剔除不入集）,'
                    '"boundary":已证实边界+证据指针（实现指针/file:line/机制链都进这里）,'
                    '"fields":{"confidence":置信度}}——text 只许 outcome-level 概念，'
                    "实现侧名词/file:line 只能进 boundary（append-trace 机械扫描，命中即拒）。"
                ),
                input="step4.disposed_problem_set",
                record=True,
                record_format="statements",
                statement_fields=("confidence",),
                selfcheck=(
                    "每条陈述单句只含 1 个独立痛点吗（「和/以及/同时」连接多痛点=复合未拆净，"
                    "回子2重拆）？脱离本会话可独立理解吗（主语+动词+约束自包含）？"
                    "type_label 逐项携带 verdict、fields.confidence 逐项携带置信度了吗？"
                    "证伪项不在陈述集里吧？"
                    "text 逐条无实现侧名词吧（文件名/类名/file:line 只进 boundary，"
                    "append-trace 机械扫描会拒）？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含本子步骤 skill-trace 记录；"
                    "形式要件：处置后问题集每个存活问题各 ≤1 句且含主语+动词+约束"
                    "（原子+去上下文）；陈述携带 verdict（type_label）与置信度"
                    "（fields.confidence，append-trace 机械校验齐备）。"
                    "质量判据（从严裁量）：陈述集与子4 verdict 逐项一致——证伪项不得出现在"
                    "陈述集、部分成立项陈述不得超出已证实边界（裁决不传导判 block）；"
                    "单句含多目标并列（「和/以及/同时」连接多个独立痛点）= 复合问题未拆解，判 block；"
                    "text 含实现侧名词/file:line = 未挪 boundary（机械预检同源），判 block。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem",
                short="读回确认",
                # 带证据的读回确认（2026-07-26 重设计）：只给结论不给依据地「通知」用户
                # = 不信任甚至 backfire effect（Das et al. 2023）；fact-checker 三大解释
                # 需求 = 不确定性/证据指针/过程可解释（Show Me the Work, CHI 2025）。
                purpose=(
                    "带证据的读回确认：向用户呈现 归一化陈述+四态 verdict+证据指针+置信度"
                    "（「证据不足」项显式暴露，由用户裁决继续/等恢复/放弃）；"
                    "用户认「这就是问题（集）」；多个问题时用户选定本实例处理哪一个，"
                    "其余带已验证陈述落 evidence + understand.md（供后续 dl 实例接续，不丢弃）；"
                    "用户对各项的认/否/搁置记入 trace（用户认可本身是裁决留痕）；"
                    f"{_INTERACTIVE_CHUNKING_RULE}。"
                ),
                input="step5.statements",
                # §substep-gate-at-stop：record=True——Stop 门控以「新 trace」为唯一
                # 完成触发，record=False 的末步永无触发信号、子阶段永远卡住（3a 潜在洞）。
                # 确认内容本身也是裁决留痕（用户认可了问题陈述）。
                record=True,
                selfcheck=(
                    "向用户呈现含归一化陈述+四态 verdict+证据指针+置信度了吗？"
                    "「证据不足」项显式暴露了吗？用户对各项的认/否/搁置记入 trace 了吗？"
                    "多问题时用户选定本实例处理项、其余落 evidence+understand.md 了吗？"
                ),
                gate=None,  # 交互步，gate 不跑 judge（trace 存在即过）
            ),
        ),
        minor_key="ProblemContext",  # evidence minor_stage 值（结构标识,模型照抄注入给的当前值）
        # 无 hold_for_gate（用户决议 2026-07-28）：围栏只设在 plan 完成，
        # understand 全部子阶段末步过门控即自动推进，中途不停。
    ),
    "understand:2": Node(
        label="明确目标和价值",
        phase="understand",
        sub=2,
        skill=None,
        artifact=None,
        gate_mech=GateMech.NONE,
        gate_rubric=None,
        advance="sub",
        # goals-and-value-substeps-design（2026-07-26，用户确认 5 步/无 hold_for_gate）：
        # 与 ProblemContext 的关键不对称——问题是事实性命题（需外部取证+质检裁决），
        # 目标/价值是规范性命题（外部证据无权证伪「我想要什么」，真值源只有用户），
        # 故砍取证/裁决双步；步数由目标定义自身失效模式族（G1-G7）决定：
        # 子2=结构对齐族（G1 脱节/G2 手段目的倒置/G5a 目标间冲突），
        # 子3=规范论证族（G3 分层失真/G4 价值无据），子4=形式可移植族（G6）。
        sub_steps=(
            Step(
                kind="tool",
                ref="推理(KAOS WHY/HOW 问) / AskUserQuestion(补问)",
                short="目标引出",
                # 形式要件披露进 purpose（降形式性返工）；质量判据只留 gate 黑盒。
                purpose=(
                    f"目标引出：{_G2_STEP1_FORM_REQUIREMENTS}。"
                    "方法：从 ProblemContext 归一化问题陈述（evidence 里 "
                    "minor_stage=ProblemContext 的最新子5 trace）逐条问"
                    "「解决了它 = 达成什么状态」（KAOS WHY/HOW 问）；"
                    "取证纪律同 ProblemContext 子1——优先引用上下文已有的用户原话"
                    "（会话事实可作佐证），禁止为凑字段重问用户已答过的内容；"
                    "真正缺失的维度才用 AskUserQuestion 事实性补问"
                    "（补问的回答原话是②的合法佐证）。"
                ),
                input="ProblemContext.step5.statements",
                record=True,
                selfcheck=(
                    "who/outcome/初步价值 ≥3 类都覆盖了吗？每条 a 是用户原话/会话事实，"
                    "还是我推断补全的（推断只能标「推测」另列）？"
                    "结论选了①还是②、每句都有出处吗？①的每个目标候选都能对应到"
                    "ProblemContext 存活问题吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=GoalsAndValue 且 sub_step==1 的记录；"
                    f"形式要件：{_G2_STEP1_FORM_REQUIREMENTS}。"
                    "质量判据（从严裁量）：各答案非空泛复述；①的目标候选非凭空脑补"
                    "（每个候选须能对应到 ProblemContext 存活问题，对应不上=脑补判 block）；"
                    "②的无目标声明须以原话为证——本步 AskUserQuestion 事实性补问的"
                    "回答原话是合法佐证；用户从未被问及时的「未提及」不算佐证"
                    "（须先问再引），无佐证=偷懒判 block。"
                ),
            ),
            Step(
                kind="tool",
                ref="推理(双向追溯矩阵+方案剥离+冲突检测)",
                short="对齐质检",
                # 结构对齐族（G1+G2+G5a）：双向可追溯文献（forward 查覆盖/backward 查镀金）
                # + INCOSE/BABOK implementation-free + KAOS conflict analysis。
                purpose=(
                    "对齐质检（不做新交互，只审子1 目标集的对齐质量）："
                    "①双向追溯矩阵——每个目标回溯 ≥1 个 ProblemContext 已验证问题"
                    "（backward，防镀金目标），每个存活问题有目标承接或显式搁置+理由"
                    "（forward，防漏）；孤儿目标剔除或退回子1 补问；"
                    f"②solutioneering 剥离——目标陈述含方案名词/实现动词"
                    f"（「做一个X」「实现Y」）-> WHY 问一层（「为什么要 X」）剥到 outcome 状态"
                    f"（{_SOLUTION_FREE_SUBJECT_RULE}）；"
                    "③目标间冲突检测——两目标不可兼得处显式标注（无冲突须显式声明，"
                    "冲突留子5 用户裁决）。"
                    "trace 须含完整矩阵（问题×目标逐项列出），"
                    "「全部对齐」式汇总声明不算记录。"
                ),
                input="step1.goal_candidates",
                record=True,
                selfcheck=(
                    "双向矩阵逐项列出了吗（问题×目标，汇总声明不算）？"
                    "孤儿目标/孤儿问题都显式处置了吗（剔除/退回补问/搁置+理由）？"
                    f"含方案名词的目标剥到 outcome 了吗（{_SOLUTION_FREE_SUBJECT_RULE}）？"
                    "目标间冲突检测做了吗"
                    "（无冲突须显式声明）？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=GoalsAndValue 且 sub_step==2 的记录；"
                    "形式要件：双向追溯矩阵逐项列出（每个目标 ≥1 问题回溯；"
                    "每个存活问题有承接目标或显式搁置+理由）；孤儿项显式处置留痕；"
                    f"含方案名词/实现动词的目标已改写为 outcome（{_SOLUTION_FREE_SUBJECT_RULE}）；"
                    "目标间冲突已标注"
                    "（或显式声明无冲突）。"
                    "质量判据（从严裁量）：剥离后 outcome 非同义反复"
                    "（「做 X 为了能做 X」判 block）；矩阵放水（明显无关联的问题-目标"
                    "硬连、脑补目标挂到无关问题上）判 block；"
                    "「全部对齐」式汇总声明无逐项矩阵判 block。"
                ),
            ),
            Step(
                kind="tool",
                ref="推理(价值链+分层理由) / Bash(条件性基线测量)",
                short="价值论证",
                # 规范论证族（G3+G4）：MoSCoW 批评（无 rationale 分层无效/须 stakeholder
                # 拍板）+ INCOSE R7 模糊词禁令/Wiegers「unverifiable = wish」。
                # 四桶分工：分层提案归模型（写什么），分层裁决归用户（认不认，子5）。
                purpose=(
                    "价值论证与分层提案：对子2 对齐后目标集逐项产出——"
                    "①受益者（为谁解决；who 出处只认用户自述，纪律同 ProblemContext 子1）；"
                    "②价值链（目标 -> 承接的痛点 -> 价值类型）；"
                    "③量化基线——可测处实测现状（Bash 查数据/日志/耗时）；"
                    "不可量化显式标注「不可量化+原因」= 合法留痕；"
                    "④must/nice 提案附理由（每条写清「为什么是 must/nice」；试金石："
                    "「不达成它本实例就失败」-> must，有 workaround 可继续 -> nice）；"
                    "分层只提案，裁决权在子5 用户——禁止替用户拍板。"
                ),
                input="step2.aligned_goals",
                record=True,
                selfcheck=(
                    "每个目标有受益者吗（who 只认用户自述）？价值链连到承接痛点了吗？"
                    "基线实测留痕（Bash 输出）或显式标「不可量化+原因」了吗？"
                    "must/nice 每条附理由了吗（只提案、未替用户拍板）？"
                ),
                # S15 前置围栏：本步合法工具 = Bash（条件性基线测量）。
                fence_allow=("Bash",),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=GoalsAndValue 且 sub_step==3 的记录；"
                    "形式要件：每个目标有受益者+价值链+基线（或显式「不可量化+原因」标注）"
                    "+must/nice 提案附理由，逐项齐全。"
                    "质量判据（从严裁量）：价值论证非空泛复述（「提升效率」无基线无"
                    "痛点链接判 block）；基线数字须有工具留痕出处，拍脑袋数字=编造判 block；"
                    "全 must 无真实取舍、或分层无理由（「重要所以 must」式循环论证）判 block；"
                    "替用户拍板分层（无「提案-待用户裁决」语义）判 block。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem",
                short="归一化陈述",
                # claim normalization 职能同构 ProblemContext 子5（同一 skill 承担）；
                # 可消费陈述三属性 = atomic / decontextualized / check-worthy
                # （Deng et al. 2024，见 goals-and-value-substeps-design §4）。
                purpose=(
                    "归一化陈述：对子3 论证后目标集逐项产出归一化目标陈述——"
                    "①原子（单句≤1个独立目标，「和/以及/同时」连接多目标=复合未拆净，"
                    "回子1 重引）；"
                    "②去上下文（脱离本会话可独立理解：主语+动词+约束自包含）；"
                    "③携带 must/nice 提案与 verdict 边界（部分成立问题的目标只覆盖"
                    "已证实边界——裁决传导，同构 ProblemContext 子5）；"
                    f"④solution-free 复核（归一化后仍含方案名词=子2 剥离不净，回子2；"
                    f"{_SOLUTION_FREE_SUBJECT_RULE}）；"
                    "放不进一句=未定义完。"
                    '载荷格式：statements 逐项 {"text":单句陈述,"type_label":must 或 nice,'
                    '"boundary":verdict 边界}——text 只许 outcome-level 概念，'
                    "实现侧名词/file:line 只能进 boundary（append-trace 机械扫描，命中即拒）。"
                ),
                input="step3.valued_goals",
                record=True,
                record_format="statements",
                selfcheck=(
                    "每条陈述单句只含 1 个独立目标吗（「和/以及/同时」连接多目标="
                    "复合未拆净，回子1 重引）？脱离本会话可独立理解吗"
                    "（主语+动词+约束自包含）？携带 must/nice 提案与 verdict 边界了吗？"
                    f"无方案名词残留吧（逐条看主语：{_SOLUTION_FREE_SUBJECT_RULE}）？"
                    "statements 载荷 text 逐条无实现侧名词吧（文件名/类名只进 boundary，"
                    "append-trace 机械扫描会拒）？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=GoalsAndValue 且 sub_step==4 的记录；"
                    "形式要件：子3 目标集每项各 ≤1 句且含主语+动词+约束（原子+去上下文）；"
                    "陈述携带 must/nice 提案与边界。"
                    "质量判据（从严裁量）：陈述集与子3 逐项一致——分层/边界不传导判 block；"
                    "单句含多目标并列=复合未拆净判 block；"
                    f"含方案名词/实现动词=solutioneering 残留判 block（{_SOLUTION_FREE_SUBJECT_RULE}）。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem / AskUserQuestion",
                short="读回确认",
                # 带证据读回（同构 ProblemContext 子6）：只给结论不给依据地「通知」用户
                # = 不信任甚至 backfire effect；本步是本子阶段唯一规范裁决点
                # （must/nice 分层真值归用户，四桶分工）。
                purpose=(
                    "带证据的读回确认：向用户呈现 归一化目标陈述+追溯链+价值论证+"
                    "must/nice 提案+不确定性（「不可量化」项显式暴露）；"
                    "用户裁决 must/nice 分层（本子阶段唯一规范裁决点）；"
                    "用户对各目标的认/否/调层记入 trace；"
                    "多目标时用户圈定本实例处理范围，其余落 evidence + understand.md"
                    "（供后续 dl 实例接续，不丢弃）；"
                    f"{_INTERACTIVE_CHUNKING_RULE}。"
                ),
                input="step4.statements",
                record=True,
                selfcheck=(
                    "呈现了陈述+追溯链+价值论证+分层提案+不确定性吗？"
                    "「不可量化」项显式暴露了吗？用户对分层与各目标的裁决记入 trace 了吗？"
                    "多目标时用户圈定本实例范围、其余落 evidence+understand.md 了吗？"
                ),
                gate=None,  # 交互步，gate 不跑 judge（trace 存在即过）
            ),
        ),
        minor_key="GoalsAndValue",
        # 无 hold_for_gate（用户决议 2026-07-28）：围栏只设在 plan 完成，
        # 末步过门控自动续轮进 understand:3（同 understand:1 边界语义）。
    ),
    "understand:3": Node(
        label="确定范围与约束",
        phase="understand",
        sub=3,
        skill=None,
        artifact=None,
        gate_mech=GateMech.NONE,
        gate_rubric=None,  # 子阶段级 rubric 删除（被 sub_steps 逐步门控取代）
        advance="sub",
        # designs/scope-and-constraints-substeps-design.md（2026-07-27 用户确认 5 步）。
        # 混合命题不对称：约束=事实性（本地单层源验证，压缩 ProblemContext 取证+质检
        # 双步为子2 一步），范围=规范性（提案归模型、拍板归用户子5），
        # 假设=中间态（显式标注置信度×影响，接受归用户子5）。
        sub_steps=(
            Step(
                kind="tool",
                ref="推理(KAOS 障碍分析) / AskUserQuestion(补问)",
                short="障碍分析引出",
                purpose=(
                    f"障碍分析与约束引出：{_S3_STEP1_FORM_REQUIREMENTS}。"
                    "obstacle = goal 的对偶（KAOS，van Lamsweerde TSE 2000）："
                    "否定每个 must 目标找 what-could-go-wrong——"
                    "「first-sketch goals tend to be too ideal」，"
                    "未发现的约束会在 execute 期爆炸返工。"
                ),
                input="GoalsAndValue.step4.statements",
                record=True,
                selfcheck=(
                    "每个 must 目标都做了否定提问「什么会使它失败」并留痕吗？"
                    "约束类型 ≥3 类吗？"
                    "每条 a 是用户原话/会话事实/工具留痕，还是我推断补全的"
                    "（推断只能标「推测」另列）？结论选了①还是②、每句都有出处吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=ScopeAndConstraints 且 sub_step==1 的记录；"
                    f"形式要件：{_S3_STEP1_FORM_REQUIREMENTS}。"
                    "质量判据（从严裁量）：约束候选非空泛复述（「数据可能不准」"
                    "无具体对象判 block）；否定提问形式主义（每目标同一句套话，"
                    "未针对目标内容具体化）判 block；②的「无实质约束」缺任一"
                    "must 目标的否定提问留痕 = 偷懒判 block。"
                ),
            ),
            Step(
                kind="tool",
                ref="Bash(本地验证) / codegraph(结构约束) / Read",
                short="约束验证标注",
                # ProblemContext 子3+子4 的压缩版：约束是项目内部事实（非外部五层源），
                # 本地单层取证 + 真伪判断浅，一步完成，无独立质检裁决步。
                purpose=(
                    "约束验证与假设标注：对子1 约束候选逐条定真伪，三态输出——"
                    "①已验证约束（项目内部事实用工具验证：数据文件存在性/新鲜度、"
                    "接口签名、权限、环境配置，附工具留痕出处；"
                    "硬规则类约束的合法验证源 = Read 规范文档（CLAUDE.md/PROJECT.md/"
                    "MODULE.md）原文引用，禁拿训练记忆里的「项目惯例」冒充；"
                    "codegraph 断言前置新鲜度检查，索引过期先 sync）；"
                    "②假设（无法低成本验证 → 显式标注「假设+置信度+错误时的影响」，"
                    "PMBOK：assumption stated without proof；「预算是事实，"
                    "预算够用是假设」）；③证伪剔除（附证据）。"
                    "不可验证又不标假设 = 静默兜底（no silent fallback 同构）。"
                    "只标注不裁决——假设的接受是风险承担，留子5 用户裁决。"
                ),
                input="step1.constraint_candidates",
                record=True,
                fence_allow=("Bash",),
                selfcheck=(
                    "子1 每条候选都做了三态处置吗（已验证/假设/证伪，无遗漏）？"
                    "已验证项都附工具留痕出处了吗？假设项都含置信度+错误时的影响吗？"
                    "有「未验证」直接混进约束集的（假设未标注）吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=ScopeAndConstraints 且 sub_step==2 的记录；"
                    "形式要件：子1 候选逐条三态处置（已验证/假设/证伪，无遗漏）；"
                    "已验证项附工具留痕出处；假设项含置信度+错误时影响。"
                    "质量判据（从严裁量）：已验证项无工具出处=编造判 block；"
                    "「未验证」直接进约束集（假设未标注）判 block；"
                    "训练记忆冒充项目事实（「通常」「一般来说」式断言无本地留痕）"
                    "判 block。"
                ),
            ),
            Step(
                kind="tool",
                ref="推理(双向追溯矩阵+约束回写)",
                short="范围界定",
                purpose=(
                    "范围界定：从 must/nice 裁决 + GoalsAndValue 子5 用户圈定范围"
                    "派生 in-scope / out-of-scope 双侧清单（PMI：只有 in 侧 = "
                    "scope creep 温床，52% 项目经历 scope creep；out 侧显式列举"
                    "「看似该做但不做」的项）——编程域操作化（2026-07-27 修订）："
                    "in/out 落到改动面，in-scope = 允许改动的文件/模块/symbol 集合"
                    "（用 codegraph impact 取证改动面，附留痕），out-of-scope = "
                    "显式禁改的文件/模块清单（特性级条目可保留作注释，但尽量落到"
                    "路径/模块级才机械可核查）；**每项携带双字段（2026-07-30 v2.28 "
                    "消费契约倒推）**：①具体实现指针（路径/模块/symbol，机械可核查）"
                    "②outcome 层标签（用户可见的状态/数字/信号——子4 归一化陈述"
                    "的 text 直接取自它，抽象在本步有 codegraph 取证条件时完成，"
                    "不把创造性转换留给子4）；双向追溯：每个 in-scope 项回溯 ≥1 "
                    "must 目标（backward，防镀金），每个 must 目标有范围覆盖或"
                    "显式搁置+理由（forward，防漏）；约束回写：已验证约束/已标注"
                    "假设迫使缩小范围处显式记录（obstacle resolution = "
                    "alternative scope，KAOS——编程域实例：项目硬规则如"
                    "「单次改动 ≤3 文件」直接圈定 in 侧上界）。"
                    "只提案不拍板（裁决权留子5）。"
                    "trace 须含完整矩阵（目标×范围项逐项），汇总声明不算记录。"
                ),
                input="step2.verified_constraints + GoalsAndValue.step5.user_decisions",
                record=True,
                selfcheck=(
                    "in-scope 和 out-of-scope 双侧清单都有吗（out 侧是显式列举"
                    "「看似该做但不做」的项）？双向矩阵逐项完整吗（非汇总声明）？"
                    "孤儿范围项/孤儿目标都显式处置了吗？约束迫使缩范围处回写了吗？"
                    "每项都带双字段了吗（具体实现指针 + outcome 层标签——"
                    "outcome 标签=子4 陈述的 text 来源）？"
                    "全程只提案、没替用户拍板吧？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=ScopeAndConstraints 且 sub_step==3 的记录；"
                    "形式要件：in/out 双侧清单；每项携带双字段（具体实现指针+"
                    "outcome 层标签）；双向矩阵完备（目标×范围项逐项）；"
                    "孤儿项显式处置；约束回写已记录。"
                    "质量判据（从严裁量）：out-of-scope 空清单 = 无真实取舍"
                    "从严裁量；矩阵放水（明显无关联的目标-范围硬连）判 block；"
                    "outcome 标签空泛（「页面相关」「功能相关」式无信息标签）判 block；"
                    "替用户拍板范围（无「提案-待用户裁决」语义）判 block。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem",
                short="归一化陈述",
                # claim normalization 职能第三次复用（ProblemContext 子5 /
                # GoalsAndValue 子4 同构）。
                purpose=(
                    "归一化陈述：对子3 范围与约束集逐项装配归一化陈述"
                    "（2026-07-30 v2.28：子3 范围项已携带 outcome 层标签——"
                    "text 直接取自它，实现指针进 boundary；**禁二次创作**"
                    "（创造性抽象已在子3 完成，本步=形式装配+逐项核对））——"
                    "①原子（单句 ≤1 个独立范围项/约束，「和/以及/同时」连接多项="
                    "复合未拆净，回子3）；"
                    "②去上下文（脱离本会话可独立理解：主语+动词+约束自包含）；"
                    "③携带类型标签（约束=已验证 or 假设+置信度；范围=in or out）"
                    "与 verdict 边界（部分成立目标的范围只覆盖已证实边界——"
                    "裁决传导，同构 ProblemContext 子5）；"
                    f"④solution-free 复核（范围项含方案名词 = GoalsAndValue 子2 "
                    f"剥离不净残留；{_SOLUTION_FREE_SUBJECT_RULE}；{_SCOPE_VERB_RULE}）。"
                    "放不进一句=未定义完。"
                    '载荷格式：statements 逐项 {"text":单句陈述,"type_label":in/out/'
                    '已验证/假设：<置信度>,"boundary":verdict 边界+实现指针}——text 只许 '
                    "outcome-level（实现侧名词/file:line 只能进 boundary，机械扫描命中即拒）；"
                    "子3 条目编号（in[..]/out[..]/Cx.x）逐项传导，机械核对缺传即拒。"
                ),
                input="step3.scope_proposal",
                record=True,
                record_format="statements",
                selfcheck=(
                    "每条陈述单句只含 1 个独立范围项/约束吗（「和/以及/同时」连接"
                    "多项=复合未拆净，回子3）？脱离本会话可独立理解吗"
                    "（主语+动词+约束自包含）？携带类型标签（已验证/假设+置信度/"
                    f"in/out）与 verdict 边界了吗？"
                    f"无方案名词残留吧（逐条看主语：{_SOLUTION_FREE_SUBJECT_RULE}）？"
                    f"动词都指向 outcome/范围赋予、没指向代码实现动作吧（{_SCOPE_VERB_RULE}）？"
                    "statements 载荷 text 逐条无实现侧名词吧（只进 boundary，机械扫描会拒）？"
                    "子3 条目编号（in[..]/out[..]/Cx.x）逐项传导了吗（缺传机械拒）？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=ScopeAndConstraints 且 sub_step==4 的记录；"
                    "形式要件：子3 范围与约束集每项各 ≤1 句且含主语+动词+约束"
                    "（原子+去上下文）；陈述携带类型标签（已验证/假设+置信度/"
                    "in/out）与边界。"
                    "质量判据（从严裁量）：陈述集与子3 逐项一致——类型标注/边界"
                    "不传导判 block；单句含多项并列=复合未拆净判 block；"
                    f"含方案名词/实现动词=solutioneering 残留判 block"
                    f"（{_SOLUTION_FREE_SUBJECT_RULE}；{_SCOPE_VERB_RULE}）。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem / AskUserQuestion",
                short="读回确认",
                # 带证据读回（同构 ProblemContext 子6 / GoalsAndValue 子5）。
                # 本子阶段两个规范裁决点都在此：范围边界拍板 + 假设接受（风险承担）。
                purpose=(
                    "带证据的读回确认：向用户呈现 归一化范围双侧清单+约束集"
                    "（已验证附出处）+假设清单（置信度+影响）+不确定性；"
                    "用户裁决两件事：①范围边界（in/out 拍板——本子阶段第一规范"
                    "裁决点）；②假设的接受（风险承担是规范裁决，模型无权替用户"
                    "接受——第二规范裁决点）；用户认/否/调整记入 trace；"
                    "多约束/假设时用户圈定本实例处理项，其余落 evidence + "
                    "understand.md（供后续 dl 实例接续，不丢弃）；"
                    f"{_INTERACTIVE_CHUNKING_RULE}。"
                ),
                input="step4.statements",
                record=True,
                selfcheck=(
                    "呈现了范围双侧清单+约束集（已验证附出处）+假设清单"
                    "（置信度+影响）+不确定性吗？用户对范围边界与假设接受的"
                    "两项裁决都记入 trace 了吗？多约束/假设时用户圈定本实例"
                    "范围、其余落 evidence+understand.md 了吗？"
                ),
                gate=None,  # 交互步，gate 不跑 judge（trace 存在即过）
            ),
        ),
        minor_key="ScopeAndConstraints",
        # 无 hold_for_gate（用户决议 2026-07-28）：围栏只设在 plan 完成，
        # 末步过门控自动续轮进 understand:4（同 understand:1 边界语义）。
    ),
    "understand:4": Node(
        label="定义成功标准和验收方式",
        phase="understand",
        sub=4,
        skill=None,
        artifact="understand.md",  # 末子阶段写产物
        gate_mech=GateMech.ARTIFACT_EXISTS,
        gate_rubric=None,  # 子阶段级 rubric 删除（被 sub_steps 逐步门控取代）
        advance="phase",  # 末子阶段 -> 末步过门控自动推进 plan:1（understand 无闸门）
        # designs/success-criteria-substeps-design.md（2026-07-27 用户确认 5 步 + hold）。
        # 关键不对称（第四种）：混合命题，轴心 = 规范性目标的可检验化转换——
        # 对齐=结构性，可检验化=技术转换（Volere fit criterion），
        # 验收可行性=事实性（本地单层源，压缩原则同 ScopeAndConstraints 子2），
        # 阈值/验收取舍=规范性（拍板归用户子5）。
        # 消费契约锚点：验收包六字段倒推自 review:0 rubric
        # 「对照 understand.md 真实问题 + 成功标准，判定 solved/partial/not，附 file:line 证据」。
        sub_steps=(
            Step(
                kind="tool",
                ref="推理(验收视角提问) / AskUserQuestion(补问)",
                short="成功标准引出",
                purpose=(
                    f"成功标准引出：{_S4_STEP1_FORM_REQUIREMENTS}。"
                    "solutioneering 剥离：标准候选含方案名词/实现动词"
                    "（「做一个X」「实现Y」）→ 剥到 outcome 度量"
                    f"（纪律同 GoalsAndValue 子2；{_SOLUTION_FREE_SUBJECT_RULE}）。"
                    "消费契约锚点：成功标准是 review 阶段 gate 判定 "
                    "solved/partial/not 的依据——写每条候选时想象 review 时拿什么判它。"
                ),
                input="GoalsAndValue.step4.statements + ScopeAndConstraints.step4.statements",
                record=True,
                selfcheck=(
                    "每个 must 目标都做了验收视角提问「怎么知道它达成了」吗？"
                    "双向追溯逐项列出了吗（每目标 ≥1 候选或定性+理由；"
                    "每候选回溯 ≥1 目标）？"
                    f"含方案名词的候选剥到 outcome 了吗（{_SOLUTION_FREE_SUBJECT_RULE}）？"
                    "每条 a 是用户原话/会话事实，还是我推断补全的"
                    "（推断只能标「推测」另列）？结论选了①还是②、每句都有出处吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=SuccessCriteria 且 sub_step==1 的记录；"
                    f"形式要件：{_S4_STEP1_FORM_REQUIREMENTS}。"
                    "质量判据（从严裁量）：标准候选非空泛复述"
                    "（「系统变快」「体验好」无度量对象判 block）；"
                    "脑补候选挂无关目标（追溯放水——明显无关联的目标-标准硬连）判 block；"
                    "②的「只能定性验收」缺逐目标理由、或理由未说明「为何不可执行验证」"
                    " = 偷懒判 block（编程域收紧：可执行验证的目标标定性判 block）；"
                    f"方案名词/实现动词残留 = solutioneering 判 block（{_SOLUTION_FREE_SUBJECT_RULE}）。"
                ),
            ),
            Step(
                kind="tool",
                ref="推理(Volere fit criterion + INCOSE 模糊词清单) / Bash(条件性基线测量)",
                short="可检验化",
                # 本节点独有的核心步（前三个节点都没有）：规范性目标 → 可检验命题
                # 的技术转换。Volere 核心判据：找不到 fit criterion = 标准模糊或
                # 理解不足——是合法退回信号，不是硬编假指标的理由。
                purpose=(
                    "可检验化：对子1 标准候选逐条做 fit criterion 转换——"
                    "①模糊词扫描改写（INCOSE vague terms：some/any/several/many/"
                    "a lot of/significant/adequate/efficient/effective/reasonable 等，"
                    "改写为量化表述）；"
                    "②三要素齐备：度量指标 + 基线（Bash 实测现状——查数据/日志/耗时，"
                    "附工具留痕出处；不可测显式标「无基线+原因」= 合法留痕）"
                    "+ 阈值提案（只提案不拍板——阈值是风险偏好，裁决权留子5）；"
                    "编程域规范形式（2026-07-27 修订）：可执行验收优先——每条标准的 "
                    "fit criterion 尽量落成 failing test / 验证脚本断言 / 命令+退出码"
                    "（specification by example；落成失败测试的标准直接与 TDD 衔接，"
                    "review 判定可机械复现），落不成可执行形式的须说明原因；"
                    "③不可检验化 = 合法退回信号（Volere：找不到 fit criterion → "
                    "标准模糊/目标理解不足 → 退回子1 重引或显式标记回退 GoalsAndValue；"
                    "禁止硬编假指标——假指标 = 度量对象与目标 outcome 不相关，"
                    "如拿「代码行数」度量「体验」、拿「编译无报错」度量「功能达成」）。"
                ),
                input="step1.criteria_candidates",
                record=True,
                fence_allow=("Bash",),
                selfcheck=(
                    "每条候选都做了模糊词扫描改写吗？每条有度量指标+基线"
                    "（Bash 留痕出处或「无基线+原因」）+阈值提案吗？"
                    "阈值全程只提案、没替用户拍板吧？"
                    "不可检验的候选走了退回通道（而非硬编指标）吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=SuccessCriteria 且 sub_step==2 的记录；"
                    "形式要件：每条候选有度量指标+基线（或「无基线+原因」标注）"
                    "+阈值提案；模糊词扫描留痕；退回项显式标注。"
                    "质量判据（从严裁量）：基线数字无工具留痕出处 = 拍脑袋编造判 block；"
                    "假指标——度量对象与目标 outcome 不相关（拿易测的替代该测的）判 block；"
                    "替用户拍板阈值（无「提案-待用户裁决」语义）判 block；"
                    "改写后仍含模糊词（some/any/significant/adequate 等）判 block。"
                ),
            ),
            Step(
                kind="tool",
                ref="推理(INCOSE 四法) / Bash / codegraph / Read(手段存在性)",
                short="验收方式设计",
                # 可行性验证 = ScopeAndConstraints 子2 同构压缩版：验收手段存在性
                # 是项目内部事实，本地单层源一步完成，无独立质检裁决步。
                purpose=(
                    "验收方式设计与可行性验证：对每条可检验标准定验收方式——"
                    "①方法选择（INCOSE 四法：test 测试/analysis 数据分析/"
                    "inspection 审查/demonstration 演示，附选择理由——经典映射："
                    "功能→demonstration、性能→test、设计约束→inspection、"
                    "质量属性→analysis；编程域映射（2026-07-27 修订）："
                    "test→pytest/验证脚本，analysis→数据/log 对比查询，"
                    "inspection→review checklist 逐项核查，"
                    "demonstration→跑起来看实际行为输出）；"
                    "②可行性三态处置（本地单层源）：手段存在（测试框架/数据源/"
                    "契约检查脚本在本仓，Bash/codegraph/Read 验证附出处）/ "
                    "验收手段待建（不存在 → 显式标注 = 进 plan 的任务项，不静默略过；"
                    "编程域实例 = 测试框架/fixture/验证脚本缺失）/ "
                    "不可行剔除（附理由）；"
                    "③验收时机标注（triggered = review 一次性判 vs continuous = "
                    "持续监控，fitness function 概念；只能在事后验证的显式标注风险——"
                    "如 T+1 实战效果只能事后验，review 期只能用回测代理指标，"
                    "代理与真值的关系显式说明）；"
                    "④证据形式锚定（review 判 solved/partial/not 时拿什么："
                    "file:line/测试输出/数据查询）。"
                ),
                input="step2.testable_criteria",
                record=True,
                fence_allow=("Bash",),
                selfcheck=(
                    "每条标准有四法之一+选择理由吗？可行性三态逐条处置了吗"
                    "（存在附出处/待建标注/剔除附理由）？时机标注了吗"
                    "（triggered/continuous；事后验证的标了风险+代理指标关系）？"
                    "证据形式锚定到 review 判定可消费的形态了吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=SuccessCriteria 且 sub_step==3 的记录；"
                    "形式要件：每条标准有四法之一+选择理由；可行性三态处置"
                    "（存在附出处/待建标注/剔除附理由，无遗漏）；时机标注；证据形式。"
                    "质量判据（从严裁量）：手段声称存在无工具出处 = 编造判 block；"
                    "全选同一方法无真实选择理由判 block；"
                    "事后验证未标注风险判 block。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem",
                short="归一化陈述",
                # claim normalization 职能第四次复用（ProblemContext 子5 /
                # GoalsAndValue 子4 / ScopeAndConstraints 子4 同构）。
                purpose=(
                    "归一化陈述：对子3 标准集逐项产出归一化成功标准陈述——"
                    "①原子（单句 ≤1 个独立标准，「和/以及/同时」连接多项 = "
                    "复合未拆净，回子1）；"
                    "②去上下文（脱离本会话可独立理解：主语+动词+约束自包含）；"
                    "③携带完整验收包（指标+基线+阈值提案+验收方法+时机+证据形式）"
                    "与 verdict 边界（部分成立目标的标准只覆盖已证实边界——"
                    "裁决传导，同构 ProblemContext 子5）；"
                    f"④solution-free 复核（含方案名词 = 子1 剥离不净残留；"
                    f"{_SOLUTION_FREE_SUBJECT_RULE}）。"
                    "放不进一句 = 未定义完。"
                    '载荷格式：statements 逐项 {"text":单句陈述,"type_label":验收方法/'
                    '时机,"boundary":verdict 边界}，验收包六字段可作额外字段随项携带——'
                    "text 只许 outcome-level（实现侧名词/file:line 只能进 boundary，"
                    "机械扫描命中即拒）。"
                ),
                input="step3.criteria_with_acceptance",
                record=True,
                record_format="statements",
                selfcheck=(
                    "每条陈述单句只含 1 个独立标准吗（「和/以及/同时」连接多项 = "
                    "复合未拆净，回子1）？脱离本会话可独立理解吗"
                    "（主语+动词+约束自包含）？验收包六字段"
                    "（指标/基线/阈值提案/方法/时机/证据形式）都传导了吗？"
                    f"无方案名词残留吧（逐条看主语：{_SOLUTION_FREE_SUBJECT_RULE}）？"
                    "statements 载荷 text 逐条无实现侧名词吧（文件名/类名只进 boundary，"
                    "append-trace 机械扫描会拒）？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=SuccessCriteria 且 sub_step==4 的记录；"
                    "形式要件：子3 标准集每项各 ≤1 句且含主语+动词+约束"
                    "（原子+去上下文）；陈述携带完整验收包六字段与边界。"
                    "质量判据（从严裁量）：验收包字段不传导——子3 已定的"
                    "方法/时机/证据形式在陈述中丢失或篡改判 block；"
                    "单句含多项并列 = 复合未拆净判 block；"
                    f"含方案名词/实现动词 = solutioneering 残留判 block（{_SOLUTION_FREE_SUBJECT_RULE}）。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem / AskUserQuestion",
                short="读回确认",
                # 带证据读回（同构前三个节点末步）。本子阶段两个规范裁决点：
                # 阈值拍板（风险偏好）+ 验收方式认可（含「待建手段」是否接受为任务项）。
                purpose=(
                    "带证据的读回确认：向用户呈现 归一化标准+验收包+不可检验退回项"
                    "+「验收手段待建」清单+不确定性；"
                    "用户裁决两件事：①阈值拍板（风险偏好 = 规范裁决，"
                    "本子阶段第一裁决点）；②验收方式认可（含「待建手段」是否接受为"
                    "本实例任务项——等于给 plan 埋任务，须用户知情；第二裁决点）；"
                    "不可检验退回项显式暴露由用户裁决"
                    "（降低标准/回退目标定义/接受定性验收）；"
                    "用户认/否/调整记入 trace。"
                    "裁决完成后装配 understand.md（写主仓 "
                    ".claude/understands/<name>.md——产物落主仓，worktree 归档删除即丢）："
                    "4 子阶段归一化陈述+本轮裁决直接装配（真实问题重述 + 目标价值 + "
                    "范围约束 + 成功标准验收包；禁二次创作；"
                    "未被选定的问题/目标/约束及其一句话陈述也须写入，供后续 dl 实例接续）；"
                    f"{_INTERACTIVE_CHUNKING_RULE}。"
                ),
                input="step4.statements",
                record=True,
                selfcheck=(
                    "呈现了归一化标准+验收包+退回项+「验收手段待建」清单+不确定性吗？"
                    "用户对阈值拍板与验收方式认可的两项裁决都记入 trace 了吗？"
                    "退回项显式暴露了吗？"
                    "understand.md 已写主仓 .claude/understands/、是装配而非二次创作吗？"
                ),
                gate=None,  # 交互步，gate 不跑 judge（trace 存在即过）
            ),
        ),
        minor_key="SuccessCriteria",
        # 无 hold_for_gate（用户决议 2026-07-28）：围栏只设在 plan 完成——
        # understand 移出 GATED_AFTER，末子步过门控自动续轮进 plan:1
        # （跨阶段自动续轮，同构子阶段边界；无 PHASE_DONE: understand 通道）。
        # understand.md 在子5 内装配（hold 前已落地，同 plan:2/3/4 产物节模式），
        # 不再有「放行后写产物」窗口。
        artifact_on_release=False,  # 产物子5 内装配
    ),
    # ---------- plan ----------
    # designs/design-solution-substeps-design.md（2026-07-27 用户确认 6 步）。
    # 关键不对称（第五种）：创造性生成×代码接地双轴心——首个创造性生成节点
    # （对象不存在于任何状态，须发散，防 design fixation）且解必须锚定本仓
    # 代码现实（须勘察，防凭空设计）。混合命题：方案生成=创作，可行性=事实性
    # （本地单层源压缩），选型/权重=规范性（子6 用户裁决），假设=中间态。
    "plan:1": Node(
        label="设计解决方案",
        phase="plan",
        sub=1,
        skill=None,
        # design.md 文件名动态（designs/<主题>-design.md），ARTIFACT_EXISTS
        # 不支持含 "/" 路径（gate_verdict_mech）；产物强制三层兜底见 design §3。
        artifact=None,
        gate_mech=GateMech.NONE,
        gate_rubric=None,  # 子阶段级 rubric 删除（被 sub_steps 逐步门控取代）
        advance="sub",
        sub_steps=(
            Step(
                kind="tool",
                ref="codegraph callers/impact / Read / Grep / Bash(新鲜度+数据契约)",
                short="现状勘察",
                purpose=(
                    f"代码现状勘察：{_DS_STEP1_FORM_REQUIREMENTS}。"
                    "编程工作流定位（本节点元约束）：方案必须从代码现实生长——"
                    "LLM 凭训练记忆描述代码结构是最强编造区（不存在的接口/"
                    "凭印象的模块归属/漏检的重复实现），"
                    "接地是本节点双轴心之一。"
                ),
                input="understand.md（问题陈述+范围约束+成功标准）",
                record=True,
                fence_allow=("Bash",),
                selfcheck=(
                    "codegraph 新鲜度检查留痕了吗（>72h 先 sync）？"
                    "四要素都覆盖了吗（或显式「无+理由」）？"
                    "每条事实都附 codegraph 原始输出或 file:line 了吗，"
                    "还是有凭训练记忆写的？勘察范围与 understand.md 对齐吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=DesignSolution 且 sub_step==1 的记录；"
                    f"形式要件：{_DS_STEP1_FORM_REQUIREMENTS}。"
                    "质量判据（从严裁量）：凭训练记忆描述代码结构无工具出处"
                    "=编造判 block；引用不存在接口/模块判 block；"
                    "勘察与 understand.md 范围明显脱节=漫游判 block。"
                ),
            ),
            Step(
                kind="tool",
                ref="推理(架构维度变换) / AskUserQuestion(用户既有想法)",
                short="方案发散",
                purpose=(
                    f"方案发散：{_DS_STEP2_FORM_REQUIREMENTS}。"
                    "design fixation 防御核心：禁评估禁排序——混入评估=发散被"
                    "收敛污染；对自己最初想法的固化是最强固化源（Leahy et al.），"
                    "用户既有想法平权入列不预设首选。"
                    "双结论制：②「设计空间唯一」合法（约束钉死全部维度，"
                    "如纯机械重命名），但须逐维度论证——防逼编造伪候选凑数。"
                ),
                input="step1.terrain_map",
                record=True,
                selfcheck=(
                    "≥3 个候选吗，还是走了②（走了②有逐维度论证吗）？"
                    "每个候选都锚定子1 事实条目了吗（有凭空 API 吗）？"
                    "候选间是架构维度实质差异还是措辞变体？"
                    "有评估/排序性措辞混入吗（评估是子4 的事）？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=DesignSolution 且 sub_step==2 的记录；"
                    f"形式要件：{_DS_STEP2_FORM_REQUIREMENTS}。"
                    "质量判据（从严裁量）：伪候选=同一方案的措辞变体判 block；"
                    "候选含子1 未证实的接口/模块=凭空设计判 block；"
                    "提前收敛排序判 block；②无逐维度论证=偷懒判 block。"
                ),
            ),
            Step(
                kind="tool",
                ref="codegraph / Bash / Read(接口存在性+影响面+重复实现)",
                short="可行性验证",
                # 本地单层源压缩原则（同 ScopeAndConstraints 子2）：
                # 可行性=本仓内部事实，无独立质检裁决步。
                purpose=(
                    "可行性验证与假设标注：对存活候选逐一做代码现实核验五项——"
                    "①接口/模块存在性复核（候选引用的每个符号 file:line 核实）；"
                    "②重复造轮子检查（codegraph 查同功能实现，"
                    "有则改复用路径或标淘汰）；"
                    "③影响面量化（codegraph impact 受影响 callers 数）；"
                    "④项目硬规则兼容（H1/H1.1 模块边界、H7 路径只 from paths import、"
                    "H8 2+文件需 design.md、H9 单次 ≤3 文件 ≤200 行可分解性、"
                    "H11-H13）；⑤可测试性（TDD 前置：改动点是否存在可挂测试的接缝）。"
                    "三态标注：可行（附出处）/假设（置信度+错误时影响）/"
                    "证伪剔除（附理由）。只标注不裁决——假设的接受留子6 用户裁决。"
                ),
                input="step2.candidates + step1.terrain_map",
                record=True,
                fence_allow=("Bash",),
                selfcheck=(
                    "每个存活候选都做了五项核验吗（存在性/重复实现/影响面/"
                    "硬规则/可测试性，无遗漏）？三态逐候选标注了吗？"
                    "可行项附出处、假设项含置信度+错误时影响、剔除项附理由了吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=DesignSolution 且 sub_step==3 的记录；"
                    "形式要件：每候选五项核验留痕；三态逐候选标注；"
                    "出处/置信度+影响/理由齐备。"
                    "质量判据（从严裁量）：声称存在无出处=编造判 block；"
                    "影响面拍脑袋无 impact 输出判 block；"
                    "全候选无差别「可行」=没真核验判 block；重复实现漏检判 block。"
                ),
            ),
            Step(
                kind="tool",
                ref="推理(Pugh 矩阵) / Agent(条件红队)",
                short="评估提案",
                purpose=(
                    "评估收敛与选型提案：Pugh 矩阵——判据=成功标准验收包指标"
                    "承接度+改动面（文件数/行数估计，对 H9）+影响面（子3 callers 数）"
                    "+复用度+可测试性+硬规则兼容，datum=最小改动候选；"
                    "逐格 +/S/− 附理由，理由须引用子3 核验事实（禁空泛）；"
                    "双向追溯（每方案要素回溯 ≥1 must 目标防镀金；"
                    "每 must 目标 ≥1 要素承接防漏）；"
                    "条件红队：候选分差小或改动跨模块时 Agent 独立上下文攻击"
                    "领先方案，触发/未触发均留痕；"
                    "产出排序+推荐提案——只提案不拍板，权重与选型是用户风险偏好"
                    "（Pugh 单人权重偏见实证），留子6 裁决。"
                ),
                input="step3.feasibility_verdicts",
                record=True,
                fence_allow=("Agent",),
                selfcheck=(
                    "矩阵逐格评分都附理由了吗？理由都引用子3 核验事实了吗？"
                    "双向追溯两向都无漏吗？红队触发/未触发留痕了吗？"
                    "是「提案-待用户裁决」语义吗（没有替用户拍板）？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=DesignSolution 且 sub_step==4 的记录；"
                    "形式要件：矩阵逐格评分+理由；理由引用子3 事实；"
                    "双向追溯矩阵；红队触发/未触发留痕。"
                    "质量判据（从严裁量）：评分理由空泛不引事实判 block；"
                    "替用户拍板=无「提案-待裁决」语义判 block；"
                    "矩阵结论与评分矛盾=凑结论判 block；追溯漏项判 block。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem",
                short="归一化陈述",
                # claim normalization 职能第六次复用（ProblemContext 子5 /
                # GoalsAndValue 子4 / ScopeAndConstraints 子4 / SuccessCriteria 子4 同构）。
                # v2.33 迁 statements+statement_fields（tail_volume plan:1 子5 三连
                # block 审计，designs/plan-normalization-statements-migration-design.md）：
                # 八字段进 fields 逐键机械校验，text 只留单句决策——att1 式实现侧
                # 名词塞 text 由方案名词扫描当场拦（原 qa 自由文本无处机判）。
                purpose=(
                    "归一化设计陈述：①原子（每项 = 1 个可独立拍板的设计决策——"
                    f"{_ATOMIC_ITEM_RULE}）；"
                    "②去上下文（主语+动词+约束自包含）；"
                    "③携带代码设计包八字段——改动清单（file→function→改动类型："
                    "改/增/删）/接口签名/数据契约变更/受影响 callers 清单"
                    "（codegraph 出处）/被否方案+逐项否决理由（ADR）/"
                    "假设清单+置信度×影响/验收包映射（每条 SuccessCriteria "
                    "验收包由哪个设计要素承接）/H9 执行单元划分；"
                    "④携带 verdict 边界（部分成立目标只覆盖已证实边界——裁决传导）。"
                    "放不进一项=未定义完。"
                    '载荷格式：statements 逐项 {"text":单句决策（outcome-level），'
                    '"type_label":推荐/备选/被否,"boundary":verdict 边界+实现指针,'
                    '"fields":{change_list/interface_sig/data_contract/callers/'
                    "rejected/assumptions/acceptance_map/h9_units}}"
                    "——fields 八键逐键非空（append-trace 机械校验，缺键即拒）；"
                    "text 只许 outcome-level，实现侧名词/file:line 进 fields/boundary。"
                ),
                input="step4.recommendation",
                record=True,
                record_format="statements",
                statement_fields=(
                    "change_list",
                    "interface_sig",
                    "data_contract",
                    "callers",
                    "rejected",
                    "assumptions",
                    "acceptance_map",
                    "h9_units",
                ),
                selfcheck=(
                    "每项 = 1 个可独立拍板的设计决策且自包含（主语+动词+约束）吗？"
                    "fields 八键都填了吗（change_list/interface_sig/data_contract/"
                    "callers/rejected/assumptions/acceptance_map/h9_units——"
                    "append-trace 机械校验，缺键即拒）？"
                    "字段与子3/子4 已定内容一致吗（无丢失无篡改无新增）？"
                    "statements 载荷 text 逐条无实现侧名词吧（进 fields/boundary，"
                    "机械扫描会拒）？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=DesignSolution 且 sub_step==5 的记录；"
                    "形式要件：每项 = 1 个可独立拍板的设计决策（text 单句）；"
                    "fields 八键齐备（append-trace 已机械校验，勿再数字段）；"
                    "text 无实现侧名词（已机械扫描）。"
                    "质量判据（从严裁量）：设计包字段不传导——子3/子4 已定的"
                    "出处/假设/否决理由在陈述中丢失或篡改判 block；"
                    f"复合句判 block——{_ATOMIC_ITEM_RULE}；"
                    "凭空新增子4 未评估的要素判 block。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem / AskUserQuestion / Write(designs/*-design.md)",
                short="读回确认",
                # 带证据读回（同构 ProblemContext 子6）：只给结论不给依据地「通知」
                # 用户 = 无依据确认；design.md 装配 = 子5 设计包+裁决记录的直接
                # 装配（禁二次创作，同 understand.md 装配原则）。
                purpose=(
                    "带证据读回与产物装配：呈现推荐方案+设计包+被否方案+假设清单"
                    "+不确定性；用户三裁决——①选型拍板（唯一规范裁决点，"
                    "含复活被否方案的合法权利，矩阵只是输入）；"
                    "②评估权重认可（Pugh 单人权重偏见防御）；"
                    "③假设接受（风险承担）；"
                    "拍板后装配 designs/<主题>-design.md（H8 产物=子5 设计包+"
                    "裁决记录的直接装配，禁二次创作）；"
                    f"{_INTERACTIVE_CHUNKING_RULE}；"
                    "写 trace 记裁决原话 -> STEP_DONE。"
                ),
                input="step5.design_statements",
                record=True,
                selfcheck=(
                    "呈现了推荐方案+设计包+被否方案+假设清单+不确定性吗？"
                    "用户对选型/权重/假设三项裁决都记入 trace 了吗？"
                    "design.md 是装配而非二次创作吗？"
                ),
                gate=None,  # 交互步，gate 不跑 judge（trace 存在即过）
            ),
        ),
        minor_key="DesignSolution",
        # 无 hold_for_gate（用户决议 2026-07-28）：围栏只设在 plan 完成，
        # 末步过门控自动续轮进 plan:2（同 understand:1 边界语义）。
    ),
    # designs/task-breakdown-substeps-design.md（2026-07-28 用户确认 5 步 +
    # hold + label 改名「拆解任务与阶段」）。
    # 关键不对称（第六种）：保真转换 × 执行接地——与 plan:1 镜像：plan:1 主敌是
    # 「无中生有时的固化与凭空」（须发散），本节点主敌是「从有到有时的失真与虚构」
    # （输入对象已存在且已拍板——无发散步；须清点基线使「一致性」可判）。
    # 混合命题：转换保真=受约束变换（设计包是唯一真源）；锚点核验=事实性
    # （本地单层源压缩，同 ScopeAndConstraints 子2）；阶段断点/粒度=规范性
    # （子5 用户裁决）；假设=中间态。
    # 消费契约锚点：执行包五字段倒推自 execute:0（逐条核+TEST_PASS）/
    # executing-plans（zero-context）/review:0（验收包映射），见 design §0 表。
    "plan:2": Node(
        label="拆解任务与阶段",
        phase="plan",
        sub=2,
        skill=None,  # 编排节点 skill 走 Step ref（同 plan:1；writing-plans 在子2/子4 ref）
        artifact="plan.md",
        # 静态路径——无 plan:1 动态文件名含 "/" 的机械门限制，
        # ARTIFACT_EXISTS 零成本兜底子5 无 judge 的产物落地风险（design §3）。
        gate_mech=GateMech.ARTIFACT_EXISTS,
        # 节点级 rubric 置 None（understand:4 先例）：原 ①②③④语义全部下沉
        # 逐步 gate（①②③→子2/3/4 判据；④一致性→子1 基线+子4 传导+子5 禁二次
        # 创作）；plan->execute 大闸门只跑 ARTIFACT_EXISTS 机械门（design §3）。
        gate_rubric=None,  # 子阶段级 rubric 删除（被 sub_steps 逐步门控取代）
        # advance="sub"（v2.20 plan:3 加入后本节点不再是 plan 末子阶段）：
        # 末子步骤 STEP_DONE:5 通过即推进 sub_index 进 plan:3（跨子阶段自动续轮）。
        advance="sub",
        sub_steps=(
            Step(
                kind="tool",
                ref="Read(design.md / understand.md) / Bash(grep evidence 设计包 trace)",
                short="清点基线",
                purpose=(
                    f"设计包清点与追溯基线：{_TB_STEP1_FORM_REQUIREMENTS}。"
                    "保真转换防御核心（本节点双轴心之一）：长链转换逐步偏离拍板"
                    "内容（semantic drift）是主失效——要素 ID 基线是后续一切"
                    "「plan 与设计包一致」判定的测量仪器；检出设计包没有的要素"
                    "=二次创作信号，显式列「新增候选」待子5 用户裁决（禁静默混入）；"
                    "发现设计包内部矛盾=合法退回信号（回 plan:1）。"
                ),
                input="designs/<主题>-design.md + evidence(DesignSolution 子5/子6 trace)",
                record=True,
                fence_allow=("Bash",),  # grep evidence jsonl；Read 在常驻集
                selfcheck=(
                    "三清单都齐了吗（要素/验收包/假设）？要素 ID 连续编号了吗？"
                    "每条都附出处且要素原文引用进 trace 正文了吗"
                    "（judge 读不到 design.md 文件本身）？"
                    "新增候选/矛盾显式标注或显式「无」了吗？"
                    "有静默新增设计包没有的要素吗（那是二次创作）？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=TaskBreakdown 且 sub_step==1 的记录；"
                    f"形式要件：{_TB_STEP1_FORM_REQUIREMENTS}。"
                    "质量判据（从严裁量）：要素无出处=编造判 block；"
                    "静默新增设计包没有的要素=二次创作判 block；"
                    "大段改写要素措辞致语义偏移=失真判 block；"
                    "要素原文未引用进 trace 正文（judge 无从核对）判 block。"
                ),
            ),
            Step(
                kind="skill",
                ref="superpowers:writing-plans(粒度与切片原则真源) / codegraph callers/impact / 推理(拓扑排序)",
                short="切分排序",
                purpose=(
                    f"任务切分与依赖排序：{_TB_STEP2_FORM_REQUIREMENTS}。"
                    "writing-plans Task Right-Sizing：单元=自带完整测试周期且值得"
                    "reviewer 门禁的最小单位；纵向切片优先（INVEST：Independent+"
                    "Testable——横向按层切的单元不可独立验证交付）；"
                    "依赖拓扑序（被依赖者先行，违反=执行期必撞墙）。"
                ),
                input="step1.element_baseline",
                record=True,
                fence_allow=("Bash",),  # codegraph CLI
                selfcheck=(
                    "每单元都附 H9 预算+承接要素 ID+依赖出处了吗？"
                    "DAG 排序留痕了吗（被依赖者先行）？TDD 序内嵌了吗？"
                    "每阶段附断点验证方法了吗（或②论证留痕）？"
                    "要素 ID 覆盖无漏吗？是「提案-待用户裁决」语义吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=TaskBreakdown 且 sub_step==2 的记录；"
                    f"形式要件：{_TB_STEP2_FORM_REQUIREMENTS}。"
                    "质量判据（从严裁量）：横向按层切无显式辩护判 block；"
                    "排序违反依赖=被依赖者排后判 block；"
                    "单元超 H9 预算无继续拆判 block；"
                    "要素 ID 覆盖有漏=丢要素判 block；②无论证=偷懒判 block；"
                    "替用户拍板断点=无「提案-待裁决」语义判 block。"
                ),
            ),
            Step(
                kind="tool",
                ref="codegraph / Bash(test -f / pytest --collect-only / 命令干跑) / Read",
                short="锚点核验",
                # 本地单层源压缩原则（同 ScopeAndConstraints 子2）：
                # 锚点真实性=本仓内部事实，无独立质检裁决步。
                purpose=(
                    "锚点核验与假设标注：逐单元核验四类——"
                    "①目标文件/symbol 存在（改动清单每个 file:line 核实；"
                    "新增文件查目录与命名冲突）；"
                    "②测试接缝存在（每单元验证测试有可挂位置：测试目录/fixture/"
                    "可 import 的被测对象，pytest --collect-only 类手段留痕）；"
                    "③验证命令可运行（pytest 路径/脚本/命令存在且参数合法）；"
                    "④No Placeholders 检出（writing-plans plan failures 清单："
                    "「加适当错误处理」「处理边界情况」「写上述的测试」"
                    "「类似任务 N」——检出则补具体内容或回子2 重切）。"
                    "三态标注：已验证（附出处）/假设（置信度+错误时影响）/"
                    "证伪（回子2 重切，附理由）。只标注不裁决——"
                    "假设的接受留子5 用户裁决。"
                    "执行接地是本节点双轴心之一：plan 的消费者是零上下文执行者，"
                    "锚点编造会被 executor 当事实消费并沿链放大。"
                ),
                input="step2.task_units + step1.element_baseline",
                record=True,
                fence_allow=("Bash",),
                selfcheck=(
                    "每单元四类核验都做了吗（文件/symbol/测试接缝/命令/placeholder，"
                    "无遗漏）？三态逐单元标注了吗？"
                    "已验证附出处、假设含置信度+错误时影响、证伪附理由了吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=TaskBreakdown 且 sub_step==3 的记录；"
                    "形式要件：每单元四类核验留痕；三态逐单元标注；"
                    "出处/置信度+影响/理由齐备。"
                    "质量判据（从严裁量）：声称存在无出处=编造判 block；"
                    "全单元无差别「已验证」=没真核验判 block；"
                    "placeholder 模式残留判 block；假设项缺置信度或影响判 block。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem(归一化) / superpowers:writing-plans(Task Structure 形式真源)",
                short="归一化步骤",
                # claim normalization 职能第七次复用（ProblemContext 子5 /
                # GoalsAndValue 子4 / ScopeAndConstraints 子4 / SuccessCriteria 子4 /
                # DesignSolution 子5 同构）。
                # v2.33 迁 statements+statement_fields（同 DesignSolution 子5，
                # tail_volume plan:2 子4 三连 block 审计）：五字段进 fields 逐键
                # 机械校验；text 只留交付物单句，file:line/签名进 fields/boundary。
                purpose=(
                    "归一化执行步骤：①原子（每项 = 1 个可独立验证/提交的交付物——"
                    "bite-sized TDD 微循环「写失败测试/跑验证它失败/最小实现/"
                    "跑验证通过/提交」= 交付物内含流程，不算复合；"
                    f"{_ATOMIC_ITEM_RULE}）；"
                    "②去上下文（零上下文执行者可做：步骤自包含，禁「同上」"
                    "「类似任务 N」，跨任务接口走 Consumes/Produces 签名显式传递）；"
                    "③携带执行包五字段——改动点（file:line→改动类型）/"
                    "前置接口（Consumes+Produces 精确签名）/验证方法"
                    "（failing test 名+命令+期望输出，或命令+期望退出码——"
                    "可执行验证优先，specification by example 接 TDD；"
                    "「人工看一下」式须显式辩护）/验收包映射"
                    "（承接哪条 SuccessCriteria ID）/追溯锚（承接哪个要素 ID）；"
                    "④假设传导（子3 假设项原样携带，不丢不淡化）。"
                    "放不进一项=未定义完。"
                    '载荷格式：statements 逐项 {"text":交付物单句，'
                    '"type_label":所属阶段,"boundary":假设传导+补充指针,'
                    '"fields":{change_point/interface/verify/acceptance_map/'
                    "trace_anchor}}——fields 五键逐键非空"
                    "（append-trace 机械校验，缺键即拒）。"
                ),
                input="step3.verified_units",
                record=True,
                record_format="statements",
                statement_fields=(
                    "change_point",
                    "interface",
                    "verify",
                    "acceptance_map",
                    "trace_anchor",
                ),
                selfcheck=(
                    "每项 = 1 个可独立验证/提交的交付物且自包含"
                    "（零上下文执行者可做）吗？"
                    "fields 五键都填了吗（change_point/interface/verify/"
                    "acceptance_map/trace_anchor——append-trace 机械校验，缺键即拒）？"
                    "字段与子2/子3 已定内容一致吗（无丢失无篡改无新增）？"
                    "验收包与要素双向覆盖无漏吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=TaskBreakdown 且 sub_step==4 的记录；"
                    "形式要件：每项 = 1 个可独立验证/提交的交付物"
                    "（TDD 微循环「失败测试→最小实现→验证→提交」= 内含流程，"
                    "不算复合）；fields 五键齐备（append-trace 已机械校验，"
                    "勿再数字段）；验收包与要素双向覆盖无漏。"
                    "质量判据（从严裁量）：字段与子2/子3 已定内容不一致="
                    "丢失/篡改/新增判 block；"
                    f"复合句判 block——{_ATOMIC_ITEM_RULE}；"
                    "验证方法不可执行且无辩护判 block；验收包映射漏项判 block。"
                ),
            ),
            Step(
                kind="skill",
                ref="AskUserQuestion / Write(plan.md)",
                short="读回装配",
                # 带证据读回（同构 DesignSolution 子6）：只给结论不给依据地「通知」
                # 用户 = 无依据确认；plan.md 装配 = 子4 执行步骤+裁决记录的直接
                # 装配（禁二次创作，同 understand.md/design.md 装配原则）。
                purpose=(
                    "带证据读回与 plan.md 装配：呈现阶段划分+任务序列+五字段摘要"
                    "+假设清单+新增候选（子1 检出若有）+不确定性；"
                    "用户两裁决——①阶段/粒度拍板（本节点唯一规范裁决点，"
                    "含要求合并/拆细/重排阶段的合法权利，断点位置是用户风险偏好）；"
                    "②假设接受（风险承担）；"
                    "拍板后装配 plan.md（=子4 归一化执行步骤+裁决记录的直接装配，"
                    "禁二次创作）；"
                    f"{_INTERACTIVE_CHUNKING_RULE}；写 trace 记裁决原话 -> STEP_DONE。"
                ),
                input="step4.execution_steps",
                record=True,
                selfcheck=(
                    "呈现了阶段划分+任务序列+假设清单+新增候选+不确定性吗？"
                    "用户对阶段粒度/假设两项裁决都记入 trace 了吗？"
                    "plan.md 是装配而非二次创作吗？"
                ),
                gate=None,  # 交互步，gate 不跑 judge（trace 存在即过）
            ),
        ),
        minor_key="TaskBreakdown",
        # 无 hold_for_gate（用户决议 2026-07-28）：围栏只设在 plan 完成，
        # 末步过门控自动续轮进 plan:3（同 understand:1 边界语义）。
    ),
    # ---------- plan:3 选择能力与工具（v2.20，capability-tool-selection-substeps-design）----------
    "plan:3": Node(
        label="选择能力与工具",
        phase="plan",
        sub=3,
        skill=None,  # 编排节点 skill 走 Step ref（同 plan:1/2；define-problem 在子5 ref）
        artifact="plan.md",
        # 机械门（同 plan:2）：ARTIFACT_EXISTS + entered_at 新鲜度
        # （§8.3 已实现，2026-07-31 v2.31）——能力节落地 guard = 机械门存在性 +
        # 子5 judge 验五字段 + 子6 禁二次创作 + 用户读回 + S13/S15 围栏
        # （design §5 #9：CONTAINS 对本节点已否决，用户决议 2026-07-28——
        # plan:4 是唯一 CONTAINS 节点）。
        gate_mech=GateMech.ARTIFACT_EXISTS,
        # 节点级 rubric 置 None（understand:4/plan:2 先例第三次）：
        # 语义全部下沉逐步 gate，plan->execute 大闸门只跑机械门。
        gate_rubric=None,  # 子阶段级 rubric 删除（被 sub_steps 逐步门控取代）
        # advance="sub"（v2.21 plan:4 加入后本节点不再是 plan 末子阶段）：
        # hold 语义转为与 understand:2/3、plan:2(v2.20) 同构（advance="sub"
        # hold，机制已 pin）：放行后自动续轮进 plan:4 子1，不再有 PHASE_DONE
        # 通道（phase_done_channel_open 对 advance="sub" 恒 False）；
        # artifact_on_release 不再显式声明（字段仅 advance="phase" 编排末节点
        # 注入第三态读取，sub 节点不被读取）。
        advance="sub",
        sub_steps=(
            Step(
                kind="tool",
                ref="Read(plan.md) / Bash(grep evidence TaskBreakdown trace)",
                short="需求清点",
                # 保真基线（同构 plan:2 子1）：本节点输入是要被「映射」的结构化
                # 对象（plan.md 任务集）——需求失真（C6）防御 = 任务 ID 基线 +
                # 原文入 trace；检出 plan 没有的需求=二次创作信号。
                purpose=(
                    f"需求清点与追溯基线：{_CTS_STEP1_FORM_REQUIREMENTS}。"
                    "检出 plan.md 没有的需求=二次创作信号，显式列「新增候选」"
                    "待子6 用户裁决（禁静默混入）。"
                ),
                input="plan.md + evidence(TaskBreakdown 子4/子5 trace)",
                record=True,
                fence_allow=("Bash",),  # grep evidence jsonl；Read 在常驻集
                selfcheck=(
                    "逐任务操作类型清单齐了吗（代码改动/测试/长 pipeline/检索/"
                    "数据读取/子代理/装配，无遗漏）？每条都附任务 ID 出处且 "
                    "plan.md 原文引用进 trace 正文了吗（judge 读不到 plan.md 文件本身）？"
                    "新增候选显式标注或显式「无」了吗？"
                    "有静默新增 plan 没有的需求吗（那是二次创作）？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=CapabilityToolSelection 且 sub_step==1 的记录；"
                    f"形式要件：{_CTS_STEP1_FORM_REQUIREMENTS}。"
                    "质量判据（从严裁量）：需求无出处=编造判 block；"
                    "静默新增 plan 没有的需求=二次创作判 block；"
                    "大段改写需求措辞致语义偏移=失真判 block；"
                    "需求原文未引用进 trace 正文（judge 无从核对）判 block。"
                ),
            ),
            Step(
                kind="tool",
                ref="Read(CLAUDE.md §2/§3 / 相关 SKILL.md frontmatter) / "
                "Bash(ls ~/.claude/skills + .claude/skills、MCP 配置、which codegraph)",
                short="能力盘点",
                # 幽灵能力防御核心（本节点最高危失效 C1）：能力空间=有限可枚举
                # 注册表，非生成空间——名称逐字引用注册表出处，训练记忆不算数；
                # 强制路由核对=编程域一等约束源（understand:3 先例）。
                purpose=(
                    f"能力盘点与强制路由核对：{_CTS_STEP2_FORM_REQUIREMENTS}。"
                    "双结论制——「内置工具足够、零 skill」是合法结论"
                    "（小改动无触发命中），但须逐任务说明，防逼编造 skill 绑定凑数。"
                ),
                input="step1.need_baseline",
                record=True,
                fence_allow=("Bash",),
                selfcheck=(
                    "三通道清单都齐了吗（skill 注册表/工具·CLI·MCP/强制路由核对）？"
                    "能力名逐字引用注册表出处了吗（还是凭训练记忆写的）？"
                    "强制路由逐任务核对留痕了吗（§2 触发词/H15/superpowers 触发）？"
                    "②逐任务说明了吗（或给出了显式 skill 候选）？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=CapabilityToolSelection 且 sub_step==2 的记录；"
                    f"形式要件：{_CTS_STEP2_FORM_REQUIREMENTS}。"
                    "质量判据（从严裁量）：能力名与注册表出处不符=幽灵能力判 block；"
                    "强制路由漏核=漏配判 block；"
                    "功能描述无 SKILL.md/listing 出处=凭记忆编造判 block；"
                    "②无逐任务说明=偷懒判 block。"
                ),
            ),
            Step(
                kind="skill",
                ref="推理(需求×能力映射) / Agent(条件红队)",
                short="匹配选型",
                # 本节点存在的理由：映射决策独立 gate（design §5 #1——并入归一化
                # 步=选型理由无人核）。四判据：覆盖（引用 trigger 原文）/最小集
                # （无绑定=不加载，tool overload 防线）/成本相称（重型手段辩护）/
                # 强制优先（强制项不可替代）。
                purpose=(
                    f"匹配选型提案：{_CTS_STEP3_FORM_REQUIREMENTS}。"
                    "条件红队（绑定数超阈值或含高成本项时触发，独立上下文反驳映射）。"
                ),
                input="step2.capability_registry + step1.need_baseline",
                record=True,
                fence_allow=("Agent",),  # 条件红队，同 DesignSolution 子4
                selfcheck=(
                    "双向追溯矩阵齐了吗（每需求有绑定或显式「内置足够」；"
                    "每能力绑定到需求，无无绑定能力残留）？"
                    "每条绑定附理由+子2 出处+被否替代了吗？"
                    "重型手段附成本辩护了吗？红队留痕或条件未触发声明了吗？"
                    "是「提案-待用户裁决」语义吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=CapabilityToolSelection 且 sub_step==3 的记录；"
                    f"形式要件：{_CTS_STEP3_FORM_REQUIREMENTS}。"
                    "质量判据（从严裁量）：无绑定能力残留=过载判 block；"
                    "绑定理由无出处=凭名字猜判 block；"
                    "强制项被非强制项替代且无辩护判 block；"
                    "重型手段无成本辩护判 block；"
                    "替用户拍板映射=无「提案-待裁决」语义判 block。"
                ),
            ),
            Step(
                kind="tool",
                ref="Bash(which/版本冒烟/MCP 连接确认/venv 依赖) / Read",
                short="可用性核验",
                # 本地单层源压缩原则（第五次否决取证+质检双步）：注册表有条目
                # ≠ 环境可用（C5，solvability awareness）——Bash 单层可验，
                # 无「五层源过程质量」可判。只标注不裁决。
                purpose=(
                    "可用性核验与假设标注：逐绑定核验四类——"
                    "①skill 条目真实存在（注册表列表行/磁盘路径）；"
                    "②CLI 可用（which codegraph + 版本/新鲜度冒烟）；"
                    "③MCP server 实际连接（配置 + 会话工具面）；"
                    "④环境前提（venv/依赖/API key 存在性——只验存在不验密值）。"
                    "三态标注：已验证（附出处）/假设（置信度+错误时影响）/"
                    "证伪（回子3 换绑，附理由）。只标注不裁决——"
                    "假设的接受留子6 用户裁决。"
                ),
                input="step3.binding_proposals",
                record=True,
                fence_allow=("Bash",),
                selfcheck=(
                    "每绑定四类核验都做了吗（skill 存在/CLI 可用/MCP 连接/环境前提，"
                    "无遗漏）？三态逐绑定标注了吗？"
                    "已验证附出处、假设含置信度+错误时影响、证伪附理由了吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=CapabilityToolSelection 且 sub_step==4 的记录；"
                    "形式要件：每绑定四类核验留痕；三态逐绑定标注；"
                    "出处/置信度+影响/理由齐备。"
                    "质量判据（从严裁量）：声称可用无出处=编造判 block；"
                    "全绑定无差别「已验证」=没真核验判 block；"
                    "假设项缺置信度或影响判 block。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem(归一化)",
                short="归一化能力包",
                # claim normalization 职能第八次复用（ProblemContext 子5 /
                # GoalsAndValue 子4 / ScopeAndConstraints 子4 / SuccessCriteria 子4 /
                # DesignSolution 子5 / TaskBreakdown 子4 同构）。
                # 能力包五字段倒推自消费契约（design §0 表）：execute:0 逐条核 /
                # using-superpowers 必先 invoke / H15+执行映射 / Agent 成本决策 /
                # overload 防线。
                # v2.33 迁 statements+statement_fields（同 DesignSolution 子5）：
                # 五字段进 fields 逐键机械校验。
                purpose=(
                    "归一化能力包：①原子（每项 = 1 个可独立执行的配置断言——"
                    f"{_ATOMIC_ITEM_RULE}）；"
                    "②去上下文（零上下文执行者照做：能力名逐字+触发依据自包含，"
                    "禁「同上」「类似任务 N」）；"
                    "③携带能力包五字段——必先 skill（名+触发依据引用）/"
                    "工具与 CLI 清单（含子4 可用性状态）/强制门禁对齐项"
                    "（H15 codegraph 前置、长 pipeline 后台禁 pipe 等执行映射条目）/"
                    "子代理策略（扇出/模型/隔离，无则显式「单线程」）/"
                    "显式不加载清单（抗 overload 承诺）；"
                    "④假设传导（子4 假设项原样携带，不丢不淡化）。"
                    "放不进一项=未定义完。"
                    '载荷格式：statements 逐项 {"text":配置断言单句，'
                    '"type_label":skill/工具/门禁/子代理/不加载,'
                    '"boundary":假设传导+出处指针,'
                    '"fields":{skill_first/tools/enforce_align/subagent_policy/'
                    "no_load}}——fields 五键逐键非空"
                    "（append-trace 机械校验，缺键即拒；无内容键填显式「无」）。"
                ),
                input="step4.verified_bindings",
                record=True,
                record_format="statements",
                statement_fields=(
                    "skill_first",
                    "tools",
                    "enforce_align",
                    "subagent_policy",
                    "no_load",
                ),
                selfcheck=(
                    "每项 = 1 个可独立执行的配置断言且自包含"
                    "（零上下文执行者照做）吗？"
                    "fields 五键都填了吗（skill_first/tools/enforce_align/"
                    "subagent_policy/no_load——append-trace 机械校验，缺键即拒）？"
                    "字段与子3/子4 已定内容一致吗（无丢失无篡改无新增）？"
                    "能力名与子2 注册表出处逐字一致吗？假设传导了吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=CapabilityToolSelection 且 sub_step==5 的记录；"
                    "形式要件：fields 五键齐备（append-trace 已机械校验，勿再数字段）；"
                    "与需求双向覆盖无漏；"
                    "不加载清单显式或显式「无」；假设传导。"
                    "质量判据（从严裁量）：字段与子3/子4 已定内容不一致="
                    "丢失/篡改/新增判 block；"
                    f"复合句判 block——{_ATOMIC_ITEM_RULE}；"
                    "能力名与子2 注册表出处不符=幽灵回潮判 block；"
                    "不加载清单缺失且无声明判 block。"
                ),
            ),
            Step(
                kind="skill",
                ref="AskUserQuestion / Bash(plan.md 追加「能力与工具」节)",
                short="读回装配",
                # 带证据读回（同构 plan:2 子5）：只给结论不给依据地「通知」用户 =
                # 无依据确认；plan.md「能力与工具」节 = 子5 能力包+裁决记录的
                # 直接装配（禁二次创作）。
                purpose=(
                    "带证据读回与 plan.md 装配：呈现映射摘要+可用性状态+假设清单"
                    "+不加载清单+新增候选（子1 检出若有）+不确定性；"
                    "用户两裁决——①映射拍板（本节点唯一规范裁决点，"
                    "含要求换绑/卸载/补绑的合法权利）；②假设接受（风险承担）；"
                    "拍板后装配 plan.md「能力与工具」节（=子5 归一化能力包+裁决记录的"
                    "直接装配，禁二次创作）；"
                    f"{_INTERACTIVE_CHUNKING_RULE}；写 trace 记裁决原话 -> STEP_DONE。"
                ),
                input="step5.capability_packages",
                record=True,
                selfcheck=(
                    "呈现了映射摘要+可用性状态+假设清单+不加载清单+新增候选吗？"
                    "用户对映射/假设两项裁决都记入 trace 了吗？"
                    "plan.md「能力与工具」节是装配而非二次创作吗？"
                ),
                gate=None,  # 交互步，gate 不跑 judge（trace 存在即过）
            ),
        ),
        minor_key="CapabilityToolSelection",
        # 无 hold_for_gate（用户决议 2026-07-28）：围栏只设在 plan 完成，
        # 末步过门控自动续轮进 plan:4（同 understand:1 边界语义）。
    ),
    # ---------- plan:4 制定执行计划和检查点（ExecutionPlanCheckpoints）----------
    # 关键不对称（第八种）：时序控制 × 风险配平——首个运行时控制结构设计节点
    # （plan:1/2/3 产物全是静态内容，本节点设计控制流：何时停/验什么/失败后
    # 去哪/谁可并行）+ 首个四源聚合节点（design.md+plan.md+understand.md+
    # evidence）。主敌=检查点虚设（E1 fabricated success）/误差复利（E2
    # Lusser's Law）/密度失配（E4）/失败处置缺失（E6）/聚合失真（E7）/
    # 并行冲突（E8）/返回物无验收（E9）。design：execution-plan-checkpoints-
    # substeps-design.md（2026-07-28 用户确认 5 步 + execute 愿景双对象修订）。
    "plan:4": Node(
        label="制定执行计划和检查点",
        phase="plan",
        sub=4,
        skill=None,  # 编排节点 skill 走 Step ref（同 plan:1/2/3；define-problem 在子4 ref）
        artifact="plan.md",
        # ARTIFACT_CONTAINS（2026-07-31 §8.3 落地，artifact-mech-gate-design）：
        # ARTIFACT_EXISTS 对本节点语义恒真（文件自 plan:2 起存在）——正解 =
        # 节存在检查（execution-plan-checkpoints-substeps-design §5 #7 的预先裁决）。
        # 守「子5 trace 合格但节未装配」的落空（子5 gate=None 交互步）。
        gate_mech=GateMech.ARTIFACT_CONTAINS,
        artifact_contains=("执行计划与检查点",),
        # 节点级 rubric 置 None（understand:4/plan:2/plan:3 先例第四次）：
        # 语义全部下沉逐步 gate，plan->execute 大闸门只跑机械门（本节点亦无）。
        gate_rubric=None,
        advance="phase",  # plan 末子阶段 -> 推进到 execute（过 plan->execute 闸门）
        sub_steps=(
            Step(
                kind="tool",
                ref="Read(design.md / plan.md / understand.md) / "
                "Bash(grep evidence plan:1/2/3 trace)",
                short="四源清点",
                # 首个四源聚合节点的保真基线（同构 plan:2/3 子1）：聚合失真（E7）
                # 防御 = 五类清单 + 四源原文入 trace；triggered 验收项是检查点
                # 候选（understand:4 时机字段的消费闭合）。
                purpose=(
                    f"四源清点与追溯基线：{_EPC_STEP1_FORM_REQUIREMENTS}。"
                    "检出四源没有的对象=二次创作信号，显式列「新增候选」"
                    "待子5 用户裁决（禁静默混入）。"
                ),
                input="design.md + plan.md + understand.md + "
                "evidence(plan:1/2/3 末步 trace)",
                record=True,
                fence_allow=("Bash",),  # grep evidence jsonl；Read 在常驻集
                selfcheck=(
                    "五类清单都齐了吗（任务 DAG/能力绑定/验收包/假设汇总/"
                    "不可逆操作候选，无遗漏）？每条都附源出处且四源原文引用进 "
                    "trace 正文了吗（judge 读不到三个文件本身）？"
                    "triggered 验收项显式标注了吗？"
                    "新增候选显式标注或显式「无」了吗？"
                    "有静默新增四源没有的对象吗（那是二次创作）？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=ExecutionPlanCheckpoints 且 sub_step==1 的记录；"
                    f"形式要件：{_EPC_STEP1_FORM_REQUIREMENTS}。"
                    "质量判据（从严裁量）：清单项无出处=编造判 block；"
                    "四源之一缺失且无说明=漏源判 block；"
                    "静默新增=二次创作判 block；"
                    "大段改写致语义偏移=聚合失真判 block；"
                    "原文未引用进 trace 正文（judge 无从核对）判 block。"
                ),
            ),
            Step(
                kind="skill",
                ref="推理(DAG 拓扑分层 + 控制结构设计) / Agent(条件红队)；"
                "对齐源 superpowers:writing-plans / executing-plans（checkpoint 语义真源）",
                short="调度与检查点",
                # 本节点存在的理由：把任务 DAG 转成运行时控制结构（design §2）。
                # execute 愿景=无判断 executor——判据零判断词/失败路由预定义/
                # 并行分组 plan 期定死全是硬约束不是建议。布点默认=并行组/阶段
                # 边界（E2 复利截断）；不可逆操作强制用户暂停（E5 硬条款）。
                purpose=(
                    f"调度与检查点方案提案：{_EPC_STEP2_FORM_REQUIREMENTS}。"
                    "布点默认=并行组/阶段边界，任务级加密须辩护；"
                    "条件红队（并行组数或检查点数超阈值时触发，独立上下文"
                    "反驳分组与布点）。"
                ),
                input="step1.control_baseline",
                record=True,
                fence_allow=("Agent",),  # 条件红队，同 plan:1 子4/plan:3 子3
                selfcheck=(
                    "调度四件都齐了吗（并行分组/文件互斥面/worker 任务包映射/"
                    "返回契约）？互斥面是从执行包改动点计算的吗（还是拍脑袋分的）？"
                    "每检查点三属性都齐了吗（零判断词判据/三选一失败路由/类型）？"
                    "不可逆操作前的检查点类型=用户暂停了吗？"
                    "goal anchoring 重述句逐检查点都有了吗（含原目标+当前位置）？"
                    "密度论证或「零用户检查点」复利论证了吗？"
                    "红队留痕或条件未触发声明了吗？是「提案-待用户裁决」语义吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=ExecutionPlanCheckpoints 且 sub_step==2 的记录；"
                    f"形式要件：{_EPC_STEP2_FORM_REQUIREMENTS}。"
                    "质量判据（从严裁量）：判据含「确认/检查/合理」类判断词="
                    "虚设判 block；失败路由缺或「视情况」=即兴路由判 block；"
                    "互斥面未从改动点计算=拍脑袋分组判 block；"
                    "返回契约缺证据形式=无验收门判 block；"
                    "密度无论证=逃避论证判 block；"
                    "替用户拍板密度/类型=越权判 block。"
                ),
            ),
            Step(
                kind="tool",
                ref="Bash(判据命令 dry-run / 互斥面交集机械核验 / "
                "codegraph 锚点存在性)",
                short="锚点核验",
                # 本地单层源压缩原则（第六次否决取证+质检双步）：判据 dry-run/
                # 交集实算/锚点存在性全是本机事实，Bash 单层可验。只标注不裁决。
                purpose=(
                    "锚点核验与假设标注：逐对象核验四类——"
                    "①判据可执行性（每检查点通过判据的命令实际 dry-run——"
                    "存在且可运行，不验结果对错）；"
                    "②互斥面机械核验（并行组内各 worker 改动文件清单集合交集"
                    "实算——交集非空=分组证伪，回子2）；"
                    "③锚点存在性（检查点位置引用的任务 ID/阶段边界/验收包 ID "
                    "在四源中真实存在，codegraph/Read 出处）；"
                    "④验证手段有绑定（判据所需工具/skill 在能力包里有绑定且"
                    "无「显式不加载」冲突）。"
                    "三态标注：已验证（附出处）/假设（置信度+错误时影响）/"
                    "证伪（回子2，附理由）。只标注不裁决——"
                    "假设的接受留子5 用户裁决。"
                ),
                input="step2.control_proposals",
                record=True,
                fence_allow=("Bash",),
                selfcheck=(
                    "四类核验逐对象都做了吗（dry-run/交集实算/锚点存在/"
                    "验证手段绑定，无遗漏）？交集实算的命令+输出进 trace 了吗？"
                    "三态逐对象标注了吗？"
                    "已验证附出处、假设含置信度+错误时影响、证伪附理由了吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=ExecutionPlanCheckpoints 且 sub_step==3 的记录；"
                    "形式要件：四类核验逐对象留痕；互斥面交集实算结果"
                    "（命令+输出）进 trace；三态逐对象标注；"
                    "出处/置信度+影响/理由齐备。"
                    "质量判据（从严裁量）：声称可执行无 dry-run 留痕=编造判 block；"
                    "交集核验无实算输出=没真核验判 block；"
                    "全对象无差别「已验证」=没真核验判 block；"
                    "假设项缺置信度或影响判 block。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem(归一化)",
                short="归一化计划包",
                # claim normalization 职能第九次复用（ProblemContext 子5 /
                # GoalsAndValue 子4 / ScopeAndConstraints 子4 / SuccessCriteria
                # 子4 / DesignSolution 子5 / TaskBreakdown 子4 /
                # CapabilityToolSelection 子5 同构）。
                # 执行计划包十字段（调度四+检查点六）倒推自消费契约（design
                # §0 表）：execute:0 orchestrator 愿景/rubric 逐条核/
                # understand:4 时机字段/review:0 证据需求/用户密度裁决五方。
                purpose=(
                    "归一化执行计划包：①原子（单句 ≤1 个独立控制断言）；"
                    "②去上下文（零上下文 orchestrator 照做：任务 ID/文件清单/"
                    "判据命令自包含，禁「同上」「如前所述」）；"
                    "③携带执行计划包十字段——调度节四字段：并行分组（DAG 层）/"
                    "文件互斥面（含交集=空核验状态）/worker 任务包映射/"
                    "返回契约（证据形式清单）；检查点节六字段（per checkpoint）："
                    "位置锚/通过判据（零判断词）/失败路由/类型/验收包映射"
                    "（含任务 ID 追溯锚）/goal anchoring 重述句；"
                    "④假设传导（子3 假设项原样携带，不丢不淡化）。"
                    "放不进一句=未定义完。"
                ),
                input="step3.verified_controls",
                record=True,
                selfcheck=(
                    "每断言 ≤1 句且自包含（零上下文 orchestrator 照做）吗？"
                    "十字段都携带了吗（调度四+检查点六）？"
                    "字段与子2/子3 已定内容一致吗（无丢失无篡改无新增）？"
                    "每 triggered 验收项有检查点落点（或显式「continuous 覆盖」"
                    "声明）吗？判据零判断词保持了吗？假设传导了吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=ExecutionPlanCheckpoints 且 sub_step==4 的记录；"
                    "形式要件：调度四字段+检查点六字段齐备；与四源双向覆盖无漏"
                    "（每 triggered 验收项有检查点落点或显式「continuous 覆盖」"
                    "声明）；假设传导。"
                    "质量判据（从严裁量）：字段与子2/子3 已定内容不一致="
                    "丢失/篡改/新增判 block；复合句判 block；"
                    "判据判断词回潮判 block；"
                    "triggered 验收项无落点且无声明=漏配判 block。"
                ),
            ),
            Step(
                kind="skill",
                ref="AskUserQuestion / Edit(plan.md 追加「执行计划与检查点」节)",
                short="读回装配",
                # 带证据读回（同构 plan:2 子5/plan:3 子6）。三裁决点的第三个
                # （冻结策略）是制度裁决：进 execute 前拍板 plan.md 的合同
                # 语义——judge 逐条核的对象不能是执行期可随手改的。
                purpose=(
                    "带证据读回与 plan.md 装配：呈现并行分组+互斥面核验状态"
                    "+检查点清单（位置/判据/路由/类型）+假设清单+新增候选"
                    "（子1 检出若有）+不确定性；"
                    "用户三裁决——①密度与类型拍板（本节点核心规范裁决："
                    "每检查点自动继续 vs 用户暂停，风险承担归用户，"
                    "含要求加密/减密的合法权利）；②假设接受（风险承担）；"
                    "③plan.md 冻结策略拍板（默认：小偏离=留痕理由"
                    "[commit message+execute 完成时偏离清单]，大改=/dl back "
                    "回 plan 修订重过闸门；禁 execute 内直接改 plan.md——"
                    "judge 逐条核的对象不能是执行期可随手改的）；"
                    "拍板后装配 plan.md「执行计划与检查点」节（=子4 归一化"
                    "执行计划包+裁决记录的直接装配，禁二次创作）；"
                    f"{_INTERACTIVE_CHUNKING_RULE}；"
                    "写 trace 记裁决原话 -> STEP_DONE。"
                ),
                input="step4.execution_plan_packages",
                record=True,
                selfcheck=(
                    "呈现了分组+互斥面核验状态+检查点清单+假设清单+新增候选吗？"
                    "用户对密度与类型/假设/冻结策略三项裁决都记入 trace 了吗？"
                    "plan.md「执行计划与检查点」节是装配而非二次创作吗？"
                ),
                gate=None,  # 交互步，gate 不跑 judge（trace 存在即过）
            ),
        ),
        minor_key="ExecutionPlanCheckpoints",
        # §subphase-hold-gate（门栏唯一处，用户决议 2026-07-28：围栏只设在
        # plan 完成——understand:2/3/4、plan:1/2/3 门栏全部撤除，末步过门控
        # 自动推进）。本节点放行后模型 PHASE_DONE: plan 撞 plan->execute
        # 大闸门（第二次 /dl gate）。
        hold_for_gate=True,
        artifact_on_release=False,  # 产物节子5 内装配（hold 前已落地）
    ),
    # ---------- execute ----------
    "execute:0": Node(
        label="执行",
        phase="execute",
        sub=0,
        skill=None,
        artifact="代码+commit+测试通过",
        gate_mech=GateMech.TEST_PASS,
        gate_rubric="实现是否真正执行了 plan.md：对照 plan 步骤逐条核,偏离需有理由。",
        advance="phase",  # 自动到 review（无闸门）
    ),
    # ---------- review ----------
    "review:0": Node(
        label="审核结果",
        phase="review",
        sub=0,
        skill=None,
        artifact="review.md",
        gate_mech=GateMech.ARTIFACT_EXISTS,
        gate_rubric="对照 understand.md 真实问题 + 成功标准,判定 solved/partial/not,附 file:line 证据。",
        advance="phase",
    ),
    # ---------- evolution ----------
    "evolution:0": Node(
        label="进化",
        phase="evolution",
        sub=0,
        skill=None,
        artifact="evolution.md",
        gate_mech=GateMech.ARTIFACT_EXISTS,
        gate_rubric="是否沉淀非显然可复用经验（memory/skill/design）。",
        advance="done",
    ),
}


# 大阶段顺序（英文标识;与 dl-lib.sh:37 WF_PHASES 同源,收口到 engine 一份）。
PHASES = ("understand", "plan", "execute", "review", "evolution")

# 大阶段中文显示名（仅显示;逻辑层用英文标识）。
PHASE_LABELS: dict[str, str] = {
    "understand": "理解和求证问题",
    "plan": "生成执行计划",
    "execute": "执行",
    "review": "审核结果",
    "evolution": "进化",
}


# ---------- 节点推导（design §3 / §4 node 字段）----------


def node_id(phase: str, sub: int) -> str:
    """phase + sub -> node_id。sub=0 表示整阶段无子节点。"""
    return f"{phase}:{sub}"


def current_node_id(phase: str, sub_index: int) -> str:
    """phase + state.sub_index -> 当前 node_id。

    无子阶段 phase 的 sub_index=0 -> 整阶段节点 "<phase>:0"。
    """
    return node_id(phase, sub_index)


def get_node(phase: str, sub: int) -> Node:
    """取节点定义。非法 phase/sub 报错暴露（守 no silent fallback：不猜）。"""
    nid = node_id(phase, sub)
    if nid not in _NODES:
        raise KeyError(f"未知节点：{nid}（phase={phase} sub={sub}）")
    return _NODES[nid]


# 各 phase 子阶段数（0=无子节点）。从 _NODES 推导（单源,不再持 _SUB_TOTAL 副本）。
def sub_total(phase: str) -> int:
    """phase -> 子阶段数（0=无子节点）。"""
    n = 0
    while f"{phase}:{n + 1}" in _NODES:
        n += 1
    return n


def subphase_labels(phase: str) -> list[str]:
    """phase -> 子阶段标签列表（按 sub 序号;空 phase 返回 []）。

    从 _NODES 推导（单源）。收口 understand 4 子阶段标签,
    供 workflow_phase.py 注入子阶段块（不再各持 SUBPHASES 副本）。
    """
    labels: list[str] = []
    i = 1
    while f"{phase}:{i}" in _NODES:
        labels.append(_NODES[f"{phase}:{i}"].label)
        i += 1
    return labels


def minor_key_map() -> dict[str, str]:
    """minor_key -> 中文 label 映射（viewer 英转中用;single source）。

    遍历 _NODES 收有 minor_key 的节点。evidence 的 minor_stage 值（英文标识,
    如 ProblemContext）经此映射回中文展示（如 理解问题和背景）。
    """
    return {n.minor_key: n.label for n in _NODES.values() if n.minor_key}


def phase_index(phase: str) -> int:
    """phase -> 序号（1-based）。非法报错。"""
    if phase not in PHASES:
        raise KeyError(f"未知阶段：{phase}")
    return PHASES.index(phase) + 1


def next_phase(phase: str) -> str | None:
    """下一 phase（无下一=终结返回 None）。"""
    idx = PHASES.index(phase)
    if idx + 1 >= len(PHASES):
        return None
    return PHASES[idx + 1]


def is_gated_after(phase: str) -> bool:
    """该 phase 完成后进下一 phase 需用户 /dl gate 放行。"""
    return phase in GATED_AFTER
