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

import dataclasses
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
    # S15 只读发现通道的 per-step 命令窄化（如子2 禁 grep/rg 逼走 dl codebase
    # trace——"堵入口"正治，rubric §3.5 #39 v2.66 三层之第二道硬围栏）。
    deny_readonly: tuple[str, ...] = ()
    # 探索预算（2026-08-17 u1-step2-explosion 诊断）：规划步被弱模型当执行步用——
    # iter4 子2a 跑 38 次 codebase/find 探索（56 轮、上下文胀到 114k、子2b --resume
    # 继承后首调 fresh 124k）。文案约束（「只规划不挖链」）对弱模型无效——它该做
    # 概念层 MECE+定档却去定位实现符号。机制杠杆：drive_mode 段工人对 Bash 的
    # codebase/find/python 探索命令计数，超本阈值一律 deny（堵入口，不是劝模型）。
    # 0 = 不限制（默认，向后兼容）。
    max_explore_calls: int = 0
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
    # v2.37 extra_payload_keys：载荷顶层额外必填内容键——（键名, spec）。
    # spec 为前缀元组 = 字符串值+前缀校验（u:1 子1 结论二选一）；
    # spec 为字符串 = engine._MECH_EXTRA_ITEM_CHECKS 注册名，值须非空数组
    # 过逐项校验（v2.40 u:1 子2 atomic_questions 分档清单）。
    # 结构形式要件从 judge 判词变 JSON 校验，值并入 record 顶层
    # （judge 读原始行自动可见）。
    extra_payload_keys: tuple[tuple[str, tuple[str, ...] | str], ...] = ()
    # v3 headless driver（designs/headless-driver-arch-design.md）：True=交互步
    # （读回/裁决/问询——需 AskUserQuestion）。v4.1 起（interactive-step-headless-prep
    # §4.1）语义=「用 prep 变体 prompt + AskUserQuestion 封锁跑后台预处理，
    # NEED_USER 转 TUI 纯问答」；仅裸开场（u:1#1 无返工）仍直路由 TUI 段。
    # False=非交互步，headless `claude -p` 段。声明式单源——禁从 purpose
    # 文本嗅探（词形漂移病根，症状 M 同型）。TUI hook 编排不读此字段。
    interactive: bool = False
    # P3-1 读回分级（v4-cost-latency-optimization-design §2 P3，2026-08-13
    # 用户裁决：8 个读回步全降确认级）：仅 interactive=True 时有意义——
    # "decision"（默认）= 弹卡片问用户；"confirm" = 确认级：driver 机械展示
    # （render-readback）+ 装配（render-artifact）+ 静默通过落 trace，不弹卡片；
    # 异议走 /dl state-reset 回上一步。TUI hook 编排（WF_TUI=1 回滚面）不读此字段。
    tier: str = "decision"
    # u1-sub5-cost 修3（designs/u1-sub5-cost-optimization-design.md）：driver 在
    # 派本步段前预派发的后台 worker 类型（""=不预派发；"redteam"=红队点查）。
    # 声明式单源（interactive/tier 同范式）——禁 driver 硬编码步号。预派发的
    # 输入在本步开始前已冻结（红队证据=子1-4 最新 trace），与本步段并行省等待；
    # 收录侧 = engine append-trace --ingest-redteam（无预派发时模型回退会话内路径）。
    pre_dispatch: str = ""
    # O3（u1-overall-cost）：本步是「原文收录」报告的消费步（三关质检要读报告
    # 全文）——交接包对本步保收录项全文；其余步（False）包内收录项截断+指针。
    # 声明式单源（pre_dispatch 同范式），禁 handoff_pack 硬编码步号。
    pack_full_reports: bool = False
    # u2-sub2-cost（designs/u2-sub2-cost-optimization-design.md）：本步所需材料
    # 已全部在交接包内（本节点前序留痕全文 + 前序节点结论摘要全文）——段 prompt
    # 加「材料边界」条款、包尾「按需 Read evidence」通用邀请改「材料已在包内」，
    # 灭弱模型保险性全量重读（u2_sub1_ab u:2#2 实测：68KB 零增量读 = +19.6k
    # fresh/+43s，且驻留污染链式下游冷启动各 +19.6k）。声明式单源
    # （pack_full_reports 同范式）；置位前置 = 逐字段核对「本步输入契约 ⊆
    # 包内内容」，未核对禁置位。
    pack_self_contained: bool = False
    # p1-sub1-cost 修1（designs/p1-sub1-cost-optimization-design.md §5 修1）：
    # 复用钉死条款要求前序留痕出处「逐字引用」，但 P1-1 摘要化把前序节点
    # statements.boundary 截断到 100 字符（_PACK_PRIOR_BOUNDARY_MAX）——
    # 截断处恰是 file:line/机制结论所在（双×100 链出处被切成「f…」实证），
    # 模型拿不到逐字出处只能翻 evidence/重验（B1 轮 evidence grep×6 +
    # 前序已载事实重验 ~10 调用）。置位 = 交接包前序节点摘要的 boundary
    # 不截断（q 截断不变）。声明式单源（pack_full_reports 同范式）；
    # 置位前置 = 本步复用条款点名逐字引用前序出处。
    pack_full_prior_boundary: bool = False
    # u3-sub3-cost（designs/u3-sub3-cost-optimization-design.md）：Step 级
    # segment_strip_project_context——Node 级字段（B1 决议粒度）之下再开逐步
    # 粒度：同节点内「消费型步」（规则/材料经前序 trace 逐字在场，如 u:3#3
    # 范围界定消费子2 验证留痕）可单独剥项目上下文，不误伤同节点的
    # 生成/验证步（u:3#1/#2 须 CLAUDE.md 在场点名规则条号）。生效 =
    # node 字段 OR step 字段（单调只增）；MergedSession 段内续步管线 env
    # 进程级固定，本字段在合并段不生效（u:3 已断链非合并）。声明式单源
    # （pack_self_contained 同范式），禁 driver 硬编码步号。
    segment_strip_project_context: bool = False


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
    # 仅 gate_mech=ARTIFACT_CONTAINS 时读取。取值必须引用 ARTIFACT_SECTIONS
    # 或其节常量（禁散写字面量，2026-08-02 节标题单源化）。
    artifact_contains: tuple[str, ...] = ()
    # u2-residual-cost（designs/u2-residual-cost-optimization-design.md）：段会话
    # 前缀外科剥离。True=段 spawn env 加 CLAUDE_CODE_DISABLE_CLAUDE_MDS /
    # CLAUDE_CODE_DISABLE_AUTO_MEMORY（探针实证 -11.9k/冷启动且 hooks 照常；
    # CLAUDE_CODE_SIMPLE=1 更狠但 hooks 全灭=S11/S14 结构保证丢失，禁用）。
    # 置位前置=本节点各步不依赖项目 CLAUDE.md/auto-memory 内容（材料全在
    # 交接包+node-rules+step prompt）。声明式单源（pre_dispatch 同范式）。
    segment_strip_project_context: bool = False
    # 非 None=段 spawn 加 --tools 白名单（逗号单串，探针实证再 -14.3k——工具
    # schema 占裸 harness 22.3k 的大头）。置位前置=逐步工具需求核对（Write
    # 不进单=载荷走 --scaffold+Edit，模型零合法 Write；附带灭 S14 撞栏褶皱）。
    segment_tools: tuple[str, ...] | None = None


# 节点表。<node_id> -> Node。node_id = f"{phase}:{sub}"。
# 闸门 GATED_AFTER：这些 phase 的末节点完成需用户 /dl gate 放行才进下一 phase。
#   继承现有 workflow_advance.py:39 GATED_AFTER 语义,收口到 engine 一份。
#   用 tuple 保序（显示用自然顺序）;is_gated_after 成员判定 O(n) 可接受（5 阶段）。
# 2026-07-28 用户决议：围栏只设在 plan 完成——understand 移出 GATED_AFTER
# （understand:4 末步过门控自动进 plan:1，无 understand->plan 大闸门）；
# 唯一用户裁决点 = plan:4 门栏 + plan->execute 大闸门。
GATED_AFTER: tuple[str, ...] = ("plan",)


# ---------- 产物节结构单源（2026-08-02，artifact-handoff-hardening-design）----------
# 各阶段产物「该带什么节」的唯一真源。三通道全部从此出：
#   ①engine CONTAINS 机械门（下方节点 artifact_contains 引用）；
#   ②phase-rules.md 装配行 {{artifact_sections:<basename>}} token（render 时替换）；
#   ③注入 hooks/workflow_phase.py _PHASE_META artifact 描述（动态构建）。
# 改节标题只改这里——静态同步测试（tests TestArtifactSectionsSync）钉三通道不漂移。
# plan.md 三节由 plan:2/3/4 分工装配，命名节常量供分工节点各引自己那节。
_S_EXEC_STEPS = "执行步骤"
_S_CAP_TOOLS = "能力与工具"
_S_CHECKPOINTS = "执行计划与检查点"
ARTIFACT_SECTIONS: dict[str, tuple[str, ...]] = {
    # understand:4 子5 装配（= 4 子阶段归一化陈述，phase-rules 装配行现行口径）。
    "understand.md": ("真实问题重述", "目标价值", "范围约束", "成功标准验收包"),
    # plan:2 装「执行步骤」/ plan:3 装「能力与工具」/ plan:4 装「执行计划与检查点」。
    "plan.md": (_S_EXEC_STEPS, _S_CAP_TOOLS, _S_CHECKPOINTS),
    # review.md 最小两节（2026-08-02 用户决议）：判决书无结论节即废品。
    "review.md": ("结论", "证据"),
    # evolution.md 最小两节（新增结构要求）：沉淀了什么 + 落到哪个 memory/skill/design。
    "evolution.md": ("经验", "落地"),
}
# 各产物节名的「 + 」连接文本（purpose/装配行插值用，免嵌套引号）。
SECTIONS_TEXT: dict[str, str] = {k: " + ".join(v) for k, v in ARTIFACT_SECTIONS.items()}


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

# 「用户自述/原话」合法形态枚举（v2.51，2026-08-02 u:1 子1 三连 block 复盘）：
# 用户全程只点 AskUserQuestion 选项（transcript 实证零打字原话），判据
# 「who 只认用户自述」与逐问原则（选项点击=快答常态）的接口从未定义——
# judge 三轮裁量发明「原话全文引用」要件，模型被要求引用物理不存在的
# 东西（§3.5 #7 佐证无合法获取路径 + #4 裁量点未钉死）。裁量点双侧钉死
# （purpose/selfcheck 模型侧 + gate judge 侧引用本常量）——合法三态与
# mech user_quote_channel 的两态通道标注一一对应；u:2 子3 等处
# 「纪律同 ProblemContext 子1」指针式引用自动跟随。
# v2.52 修文本（§3.5 #23 判词与规则文本矛盾修文本不站队）：v2.51 文本
# 把选中标签叫「合法自述」，judge 却按「自述=等级声称」判 block——模型
# 换「自述」词绕 mech（新 att1）被判对、改干净（新 att2）又被「已修还判」
# 误 block。词表钉死：「原话/自述」两词只许用于用户打字的文本，选中标签
# 记录形态=标签全文+「（AskUserQuestion 选中）」无前缀词。
_USER_QUOTE_FORMS_RULE = (
    "「用户自述/原话」合法形态（AskUserQuestion 时代）：「原话」「自述」"
    "两词只许用于用户打字的文本（自由输入/直接对话轮次）；AskUserQuestion "
    "选项被选中=用户主动声明行为、是合法佐证但属会话事实级——记录形态="
    "选项标签全文+标注「（AskUserQuestion 选中）」，不加「原话/自述」前缀词"
    "（带此前缀=标注失真=声称的佐证等级高于实际，判 block）；"
    "「未自述/未提及」如实标注合法（who 类）。"
    "禁止形态：纯指称无引用全文（「本会话 AskUserQuestion 回答」式）、"
    "选项标签带「原话/自述」前缀、仓库事实冒充身份出处。"
    "用户只点选项时按选中标注记录即合法——不为「原话」逼用户重复打字"
    "（补问可给 Other 自由输入机会，但不强制）。"
    # v2.70（2026-08-03 tail_volume_acceleration_annualized u:1 子1 第四集
    # att2）：who 写法（「因子池/项目维护者（AskUserQuestion 选中）」）与 att1
    # 逐字相同、att1 未判 who，att2 judge 却发明「选中选项只能证明行为/会话
    # 事实，不能证明提问者身份」要件——轮间「放过又判」（§3.5 #14）+ 发明
    # 要件（§3.5 #23），且按该判词 who 只剩打字自述一条路（用户全程只点
    # 选项=无合法获取路径，§3.5 #7）。「选中角色选项算不算 who 自述」的接口
    # 两条规则都未写死=裁量留白（§3.5 #4），双侧钉死：
    "who 类接口钉死：who 问题的角色类选项被用户选中=用户自述身份"
    "（合法 who 出处，与打字声明同效）——「会话事实级」是标注等级，"
    "不降低其对 who 的佐证效力；禁止把「选中角色选项」降格判为「未自述"
    "身份」，禁止要求身份必须打字声明（用户只点选项时该要求无合法满足"
    "路径）；who 类判 block 的形态=仓库事实/分支命名/他人身份冒充提问者"
    "（未自述时如实标「未自述身份」合法，不判 block）"
)

# 痛点可观察性的操作化（v2.64，2026-08-03 tail_volume_acceleration_annualized
# u:1 子1 两连 block 复盘）：att2 痛点已含用户确认的可观察后果（「会被当真实
# 收益用于选因子/调权重，导致选错因子」——att1 判词范例的逐字形态），judge
# 却发明「每条列举后果都须可观察」要件，把用户自选并列的认知类后果（「整份
# 报告失去可信度，我不再敲定数字」）判成「未真正修复」——按前轮判词描述判
# 本轮实况（§3.5 #14）+ 发明要件（§3.5 #23）。判据文本只写「痛点须可观察」，
# 混合后果（可观察+认知类同列）如何处理从未定义=裁量留白（§3.5 #4）；且用户
# 自己选中的答案就是痛点事实，再 block 只剩「丢弃用户原话」或「第三轮重问」
# 两条非法出路（§3.5 #7 佐证无合法获取路径）。双侧钉死（purpose/selfcheck
# 模型侧 + gate judge 侧引用本常量，对齐 _USER_QUOTE_FORMS_RULE 先例）：
_PAIN_OBSERVABILITY_RULE = (
    "痛点可观察性按主痛点判：含 1 条以上用户确认的可观察后果（问题不解决时"
    "持续造成的下游损害——错误输出被下游消费/决策被误导/状态被污染，须能"
    "指明「哪个下游环节因此做出什么不同动作」，如「错误数字被用于选因子"
    "导致选错」「维护者因此把该因子标注可疑并停用、不纳入筛选依据」"
    "）并以之为痛点本体即满足；用户因错值而改变的处理行为（停用/标注/"
    "不纳入/降权）是「下游不同动作」的合法形态--它是问题不解决时会持续"
    "发生的不同处理，区别于「要求定位根因/修代码」的修复诉求（诉求是"
    "要求修复、不是自己下游处理改变）；"
    "「用户要求定位根因/修代码」等后续动作是修复诉求、不是痛点后果，"
    "不能充当可观察后果；"
    "「数字被判不合常理/无法采信/不被当作可用输出」是认知/信任类陈述——"
    "自称「可观察痛点」也不算；"
    "认知/信任类感受（觉得不合常理、不敢再用、报告失信）同列声明是"
    "合法附带记录（建议标注「附带（认知类）」），其存在不构成违规、不作 "
    "block 依据；仅当痛点完全无可观察后果（只有认知判断/信任陈述/修复诉求）"
    "时才是「好奇心缺口」式伪痛点，判 block。"
    "模型侧退路：补问只拿到认知类答案时，追问一层「这会改变什么动作/决策」"
    "把痛点落到可观察后果再申报①；用户明确无下游影响时按②申报，禁止把"
    "认知感受包装成可观察痛点"
)

# 选项设计裁量点钉死（v2.68，2026-08-03 tail_volume_acceleration_annualized
# u:1 子1 att2 复盘）：模型补问「可观察后果」时选项全是认知/信任类
# （「报告整体可信度受损」「其他因子也会被一起质疑」），用户只点选项（v2.51
# 实证零打字原话）→ 只能点出认知类答案 → 结构性必 block——答案类别在选项
# 设计时刻已决定，规则却只判答案、从不规范选项设计（§3.5 #4 裁量留白 +
# #7 佐证无合法获取路径变体：选项全认知类时动作类答案物理不可获得）。
# 双侧钉死（purpose/selfcheck 模型侧 + gate judge 侧引用本常量，对齐
# _USER_QUOTE_FORMS_RULE/_PAIN_OBSERVABILITY_RULE 先例）：
_OPTION_DESIGN_RULE = (
    "AskUserQuestion 补问「可观察后果」类问题时，选项决定答案类别——选项"
    "必须是动作类（哪个环节因此做什么不同动作，如「拿它选因子/调权重/"
    "停用报告」），并至少含一个出口项（「不改变任何动作/只是看看」——"
    "用户选它=按②申报的合法佐证）；纯认知/信任类选项（失信/不敢用/"
    "觉得异常）=用户只能点出认知类答案=结构性必 block，属选项设计违规"
    "（返工方向=重新设计动作类选项重问），非用户答案违规；动作类与认知类"
    "混列时用户选了认知类=如实记录为附带（认知类），按痛点可观察性规则"
    "退路处理"
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
    "who 类出处只认【用户自述】（会话中用户明确声明身份，如「唯一维护者」；"
    "who 问题中用户选中角色类选项同为自述）；"
    "仓库事实（CLAUDE.md/git config 等）只证明「仓库由谁维护」，"
    "不能证明「当前提问者就是那个人」——无用户自述时显式问一句，"
    "或如实标注「未自述身份」，禁止拿仓库事实充当身份出处。"
    "①/② 由事实答案推导（触发/痛点/后续动作），"
    "禁止直接问用户「这是否构成真实问题」（投票与事实矛盾时以事实为准）；"
    "事实是「只是想知道/临时起意/无后续动作」→ 按②申报，"
    "禁止为凑①回填痛点（「无法判断X」=复述提问本身，必 block）。"
    "缺失维度在同一轮 AskUserQuestion 一次问完（单次最多 4 问=本步 4 类"
    "正好一轮；超过 4 问时连续多问几轮、问完再写 evidence——多问几轮"
    "不属返工，提交后被 block 才是返工）；禁止问一部分、反推剩余"
    "（反推占答案位=机械校验当场拒）"
)

# understand:2 子1 的形式要件（单源：purpose 模型侧与 gate judge 侧都引用）。
# 对齐原则同 _STEP1_FORM_REQUIREMENTS：形式要件披露降形式性返工，
# 质量判据（非脑补/非空泛/佐证合法性）只留 gate 黑盒。
# 双结论制（§3.5 #3）：「目标不成立」是合法结论——ProblemContext 可能已得出
# ②「字面请求即全部」，GoalsAndValue 必须能直通，否则逼模型编造价值。
_G2_STEP1_FORM_REQUIREMENTS = (
    "who（受益者）/outcome（达成什么状态）/初步价值三类均覆盖"
    "（每类 ≥1 条即达标，不要求单类多条），q/a 按序对齐，"
    "答案引用用户原话或会话事实；"
    "结论二选一：①目标成立=ProblemContext 每个存活问题 ≥1 目标候选；"
    "②目标不成立=用户声明字面请求即全部/无进一步诉求+原话佐证。"
    "结论逐句须有出处（用户原话/会话事实）：无出处的推断禁止写进结论，"
    "只能标注「推测」另列。"
    "读出即事实 vs 读出后推出范例（2026-08-02 att1 真实违规字面）："
    "「用户自述『一直用 web_ui 翻报告』」=原话引用（合法）；"
    "「长期使用意味着会据此做决策」「隐含价值」=推出（必标「推测」另列）"
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
# v2.49 补（同日 tail_volume_acceleration_annualized 子2 三连 block 复盘）：
# ①判据自相矛盾修复——旧文本「推断只允许出现在根因候选与排除理由分支」
# 允许推测式排除，judge att3 却按「排除理由须证据指针」block（模型按写出来
# 的规则做、被没写出来的规则 block）——裁量点双侧钉死：排除=断言为假须
# 证据指针，保留=挂起可标「待子3取证」；②降格操作化补反例——att3 把
# 「降格至竞争假设分支」声明写进主链环占位（声明≠降格）；③拼接产物路径
# （「实际产物路径 = …」）补反例；④行号跨度要件双侧化——att2 judge 临场
# 发明「:565-771 不算精确指针」，规则文本未写（正例跨度 ≤17，阈值钉 50）。
# v2.50 补（同日晚三连 block 第二 episode 复盘——v2.49 修完词形家族，
# 换家族照样三连）：①「待子3取证/降格」声明独占 Why 环（环内无指针）
# =占环位，词形下沉机械层（att1 逐字）；②「每环有 file:line」≠「每环是
# 因果环」——调用拓扑/schema 路径/数据契约描述满足全部已披露要件仍被
# judge 三连判（att3 自查逐项答「停在实测层」仍 block = 操作化分歧实锤，
# §3.5 #9 第三形态）——「异常数值如何形成」正反范例双侧钉死（正例取
# att3 judge 改写例、反例取 att2 真实违规字面）；③atomic_questions 与
# MECE 声明原子计数/标签对齐下沉机械层（att1 声明 3 交 5，att2 judge
# 判词搬旧计数失真——机械接管后 judge 不再碰计数）。
# v2.55 补（同日第三 episode，u:1 子2 att2）：全局否定断言「没有显式契约/
# 无 unit test/契约缺失」当主链根因——模型把「读了文件没看到 X」当读出
# 事实（操作化分歧往深一层：读出的是「有什么」不是「没有什么」）。合法
# 出处=全域扫描零命中留痕，否则降格；词形下沉 causal_ring_no_untested
# 环段扫描（豁免：扫描留痕/降格去向声明；局部「未做 X」不收——v2.50
# 正例形态，贪宽=FP）。
_CAUSAL_CHAIN_EVIDENCE_RULE = (
    "「证据出处」操作化：主因果链（5 Whys 各 Why 环）每环须为实际证据指针"
    "（file:line/数据值/日志原文/用户原话——Read 是本步合法且足够的取证通道）；"
    "「未实测/推断」是取证状态标注、不算证据出处，只允许出现在竞争假设分支的"
    "「保留」理由（标「待子3取证」留子3 消化）；「排除」=断言假设为假，"
    "排除理由须证据指针（file:line/读出事实），「推测/可能」式排除=无证据断言，"
    "判 block——证据不足时改标「保留」，不推测排除；把链环全写成候选假设"
    "形态=主链缺失，判 block；根因未定时候选根因按竞争假设分支处理，"
    "本步要求链条每环可追溯、不要求根因已证明（证明归子3/子4，要求已证明"
    "=判据无通过路径）；Bash 被 engage 围栏拦是设计内，不等于禁取证。"
    "「读出即事实」与「读出后推出」须分清——正例「Why2=format_percentage "
    "decimals=2（formatters.py:92-104）」读出即事实；反例「Why4=过滤 NaN 后"
    "可能剩 1-5 天（:630-647）」——file:line 背书的只是代码文本，量级是推断，"
    "不算出处；反例「实际产物路径 = backtest/result/default/x.json」——"
    "拼接产物路径是推断，指针须指向代码中定义/赋值/调用语句的 file:line+原文；"
    "行号指针跨度 ≥50 行不算精确指针（反例「:565-771」——收窄到具体语句行）。"
    "挖不动实测的深层：整体降格进竞争假设分支并标「待子3取证」——降格=把该环"
    "从主链移除、改写进竞争假设分支，链环文本写「此环降格/待子3取证」仍占"
    "主链环位=未降格（反例「Why5=…降格至竞争假设分支」：声明占环位，主链仍"
    "悬空）；主链挖到实测层即终止——不悬空、不贴「未实测/推断」充数（链环文本含"
    "「未实测/待实测/未验证/待验证/可能/需…验证类待办桥接/若…则假设形态/"
    "≥50 行行号跨度」append-trace 当场机械拒（「不可能」是否定式合法断言，除外）；"
    "「待子3取证/降格」声明独占某 Why 环且环内无 file:line 指针=占环位，"
    "append-trace 当场机械拒——环终止于实测层（环内有指针）、尾部带降格去向"
    "声明是合法形态）。"
    "「每环有 file:line 证据指针」不等于「每环是因果环」——每环须回答"
    "「异常数值/现象如何形成」，指针背书的是模块调用拓扑/schema 路径/"
    "数据契约描述则不算因果环：正例「Why1=web_ui 取字段原值=95.298 未做单位"
    "判断（_section_backtest.html:69 原文 _ann_pct=(_ann*100)，读出即事实）」"
    "——环内容=数值形成机制；反例「Why2=输出 schema="
    "layered_backtest_result.schema.json（PROJECT.md:1200，读出即事实）」"
    "——指针背书的只是产物路径/注册事实，不解释 95.298 如何产生，"
    "有指针仍判 block。"
    "「没有/缺失 X」全局否定断言（跨文件存在性命题：无显式契约/无 unit "
    "test/契约缺失）=「读出后推出」同族——读出的是「有什么」，不是"
    "「没有什么」；合法出处只有全域扫描零命中留痕（grep -rn 命令原文+"
    "零命中结果），否则主链终止于可直接读证的环、「没有 X」降格进竞争"
    "假设分支标「待子3取证」：正例「两处 *100 各有行号原文可直接读证，"
    "主链即终止；契约缺失降格」；反例「Why4=…没有显式契约…且无 unit "
    "test 钉住…」——无扫描留痕的全局否定断言，append-trace 当场机械拒"
    "（局部可读否定不算：「未做 X」有该行原文背书是合法环）"
)

# v2.40 取证深度分档规则（单源：子2 定档指引 purpose/selfcheck/gate 与
# 子3 执行面都引用；designs/fetch-depth-tiering-design.md）。
# 雏形考古：子2「挖不动的深层降格标『待子3取证』」本就是隐式二分类，
# v2.40 显式化并细分三档——动机是一刀切五层源对仓内可答问题纯烧 token。
# v2.56 补（2026-08-02 tail_volume_acceleration_annualized u:1 子2 att1）：
# 模型 Why2 论证引 M19 annual_return = valid_mean*252*coverage 仓外公式
# 判量级合理性，却把该原子标 none——「外部知识依赖」枚举只在 gate judge
# 侧，模型侧无操作测试（单侧钉死，§3.5 #12）。补操作测试：论证过程用到
# 仓外知识 = 问题含外部知识依赖。
_FETCH_TIER_RULE = (
    "取证深度三档（逐原子问题定档，拿不准标 light——默认档）。"
    "定档前先问「值不值得取证」：外部取证结论（无论证实还是证伪）"
    "是否会改变「问题是否成立」或「修复方向」？不会 → 该原子问题标 none"
    "（仓内佐证即可，不派外部 agent）。"
    "none=答案仓内可达（函数行为/数据契约/配置/日志），仅内查不派外部 "
    "agent，tier_reason 须指出仓内取证路径（文件/file:line）；"
    "light=有具体、公认、一次即得的单一事实/数值（如某因子历史年化的"
    "明确文献值），≤2 层源 ≤4 curl 单向点查即收；"
    "full=方法论/设计/量级合理性/开放问题（无单一权威、需综合——"
    "如「X 策略年化 48.7% 是否合理」这类量级合理性判断），五层源双向充分取证。"
    "外部知识依赖操作测试：问题本身或你的论证过程（因果链/tier_reason）"
    "用到仓外知识——行业常识/第三方库行为/方法论/数值合理性公式"
    "（如年化 = 均值×252）——即含外部知识依赖，不得标 none（至少 "
    "light）；反例「论证引 annual_return = valid_mean*252*coverage 公式"
    "判量级合理性，却标 none」= 漏取证，判 block"
)

# 取证权威源注册表（2026-08-13 amplitude_annualized sub3 审计：light+full 17 curl
# 仅 4 次有效（24%），其余泛搜索全空——「年化折算」是工程惯例非学术问题，权威在
# 业界标准库源码，不在 OpenAlex/arXiv 关键词索引。按 claim 类型定点抓，禁先泛搜。
_FETCH_AUTHORITY_REGISTRY = (
    "取证权威源注册表（按 claim 类型定点抓，禁先泛搜学术数据库）："
    "①年化折算/回测统计惯例 → empyrical / pyfolio / quantstats / vectorbt / zipline "
    "源码（raw.githubusercontent 直抓）；"
    "②因子收益量级/方法论 → Fama-French 数据库 / WRDS / 具体 SSRN 论文；"
    "③框架 API 语义 → 官方文档 / docstring；"
    "④单点数值 → 已知定点网页/文档。"
    "取证第一步 = 按 claim 类型查本表、定点抓权威源；"
    "查询词先翻译成业界术语（禁 repo 内部黑话，如 coverage → annualization with "
    "missing trading days）；泛搜索（OpenAlex/arXiv/SE/HN）只作「注册表无对应项」"
    "时的兜底。"
)

# 通用代码考古取证路线（杠杆 2，code-archaeology-three-levers-design §2）：
# 单层取证「决定下一步查哪」从开放式推理降级为模板跟随；本步 raw grep/rg 已被
# 围栏 deny（deny_readonly），symbol 关系只能走 codebase trace、字符串走 query --string。
# 注意：headless 段工人里裸 `dl codebase` 不可用（.bashrc shell function 未加载），
# 须用 `bash ~/.dl-workflow/scripts/workflow/dl-cmd.sh codebase ...`。
_CODE_ARCH_ROUTE = (
    "单个原子问题取证路线（按需跳步）："
    "1. symbol 关系查询**只能**走 "
    "`bash ~/.dl-workflow/scripts/workflow/dl-cmd.sh codebase trace <symbol>` "
    "（一次拿定义+调用者+被调+影响面+git 历史；本步 raw grep/rg 已被围栏禁，"
    "勿尝试 grep 定义/调用）；"
    "2. 字符串/正则定位走 "
    "`bash ~/.dl-workflow/scripts/workflow/dl-cmd.sh codebase query --string <pattern>` "
    "（本步唯一字符串搜索通道）；"
    "3. 某行何时引入走 "
    "`bash ~/.dl-workflow/scripts/workflow/dl-cmd.sh codebase query --history <file>:<line>`；"
    "4. 读关键文件正文用 Read。"
    "上述 `codebase` 命令会自动落账去重，重复查询零成本。"
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

# 读回确认步的「用户裁决记录」形式要件（v2.45，单源：8 个读回步 purpose 引用
# + engine _check_user_decision_recorded 同源校验）。交接架构
# （designs/context-handoff-design.md §4）正确性前提：读回步 gate=None 无
# judge，裁决只在对话里 = /clear 换会话即丢，新会话只能从 trace 还原拍板。
_USER_DECISION_RECORD_RULE = (
    "用户裁决逐项落 trace：标题带「裁决」或「读回」的 qa 项 + 各项认/否/拍板"
    "结果与答复要点（「用户已确认」式空记录不算，append-trace 机械校验——"
    "/clear 交接后新会话只能从 trace 还原拍板内容）"
)

# 「复合句」裁量点钉死（v2.32，2026-07-31 tail_volume plan:1 子5 / plan:2 子4
# 审计）：两处归一化步各三连 block + 用户强制放行——judge 按词形（「+」「然后」
# 连接、括号枚举、多项「、」罗列）判复合，与同项携带八字段/五字段的形式要件
# 自相矛盾（字段全带必产出枚举形态，枚举形态必被判复合，判到升级死路）；
# 且判词失真（att1 称「数十个『。』断句」，重放实际条目 ≤1 个「。」）。
# 通过的 ProblemContext 子6 trace 实证：合法形态本来就是「单句决策 + 字段
# 键值枚举」。原子性按独立性判、不按词形判（与 _SCOPE_VERB_RULE 同构）。
# 只适用 DesignSolution 子5 / TaskBreakdown 子4（字段携带型归一化步）：
# ProblemContext 子6 等痛点陈述步的「和/以及/同时」多痛点判据不动。
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
        advance="sub",  # 末子步骤 STEP_DONE:7 通过即推进 sub_index（_handle_step_done 调 advance_state）
        sub_steps=(
            Step(
                kind="skill",
                ref="define-problem",
                short="逼问定义",
                interactive=True,
                # purpose 含形式要件（模型可见，降形式性返工）；
                # 质量判据不进 purpose（防应试填表），只在下方 gate 给 judge。
                purpose=(
                    f"逼问问题定义：{_STEP1_FORM_REQUIREMENTS}。"
                    f"{_STEP1_METHOD_GUIDANCE}"
                    f"{_USER_QUOTE_FORMS_RULE}。"
                    f"{_PAIN_OBSERVABILITY_RULE}。"
                    f"{_OPTION_DESIGN_RULE}。"
                    "结论作为载荷顶层「结论」键提交（①或②开头——append-trace "
                    "机械校验存在性与前缀，缺键/前缀错当场拒，不进入 gate；"
                    "结论禁推测形态——逐句须有出处，推断标「推测」只能另列 "
                    "q/a 项，「结论」值含「推测」当场拒）"
                ),
                input=None,
                record=True,
                # 步级自查（全部已在上方 purpose 披露，无质量判据泄漏）
                selfcheck=(
                    "who/pain/why-now ≥3 类都覆盖了吗？每条 a 是用户原话/会话事实，"
                    "还是我推断补全的（推断只能标「推测」另列，禁止包装成原话或「真实回答」）？"
                    "每条 AskUserQuestion 出处标注通道了吗（「选中」=选项标签属会话"
                    "事实级、须去掉「原话/自述」前缀；「自由输入」=打字原话）？"
                    "痛点有可观察后果作本体吗（认知/信任类感受同列时标「附带」了吗，"
                    "纯认知感受作痛点=无通过路径，须追问到下游决策/行动变化或按②申报）？"
                    "可观察后果类补问的选项是动作类吗（纯认知/信任类选项=结构性必 block，"
                    "须重新设计动作类选项+出口项重问）？缺失维度一次问完再提交了吗"
                    "（连续多问几轮合法），还是留了维度靠反推（机械拒）？"
                    "结论选了①还是②、每句都有出处吗（载荷顶层「结论」键，①/② 开头）？"
                ),
                # 门控分工：子1 只管「定义质量」（结构可判项），真值判给子4/子5（验真+质检）+ 子7（用户认可）。
                # 双合法结论（demo 2026-07-25 行3）：问题成立要可证伪；问题不成立要原话佐证——
                # 否则诚实回答「没有痛点」永远过不了，逼模型编造痛点（行2「好奇心缺口」被 judge 识破）。
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace 且 sub_step==1 的记录。"
                    f"形式要件：{_STEP1_FORM_REQUIREMENTS}。"
                    "（结论①/②前缀/无推测形态/原话-选中通道标注/who 仓库事实冒充/"
                    "答案位反推 已由 append-trace 机械校验通过--你不得以这些形式要件"
                    "为由 block，只判下面两件事的真实性。）\n"
                    "默认 pass--仅当以下成立才判 block：\n"
                    "一、结论以①申报：痛点须是用户确认的真实、可观察的下游后果"
                    f"（{_PAIN_OBSERVABILITY_RULE}）。仅三种判 block："
                    "(a)编造伪痛点（好奇心/无法判断包装）；(b)空泛复述提问本身；"
                    "(c)修复诉求（用户要求定位根因/修代码=诉求非后果）。\n"
                    "二、结论以②申报：须有用户原话佐证（含补问原话；未被问及的"
                    "「未提及」不算=偷懒判 block）。\n"
                    "【关键】结论以①申报时，第二项（②原话佐证）不适用--不得以"
                    "「缺②的原话佐证/选中项不算原话」block ①的载荷；who 项用 "
                    "AskUserQuestion 选中的角色选项=合法自述，不得判为「未自述身份」。"
                    f"{_OPTION_DESIGN_RULE}。"
                    "【合法正例】痛点=用户在下游环节因此做的不同动作（如「把该因子"
                    "标注可疑并停用、不纳入筛选依据」=AskUserQuestion 选中）即合规可"
                    "观察后果，不要求痛点多严重；who=选中角色选项即合规；痛点/后果"
                    "可引用项目事实（如 T+1 机制）说明下游环节--仅 who 的「身份出处」"
                    "禁仓库事实（已机械校验），别处引用项目事实不违规。\n"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例"
                    "（指模式不指实例位置）。"
                ),
                # v2.37：结论二选一从判据惯例升级为载荷顶层必填键（存在性+①/②
                # 前缀机械校验）——tail_volume u:1 子1 att1 缺结论白烧一轮 judge。
                # v2.54：+conclusion_no_speculation——att1 模型 who 项合规却在
                # 结论写「项目维护者（推测…）」，字段漏网面词形下沉。
                extra_payload_keys=(("结论", ("①", "②"), "conclusion_no_speculation"),),
                # v2.51：原话标注通道（att1-3 三连 block——选项标签标「原话」
                # /通道未声明，词形下沉；选中即合法的正面退路见规则常量）。
                # v2.68：+answer_no_reverse_inference——att1 第 4 类没问用户、
                # a 填「三项标签反推」（诚实披露词形），judge 判对白烧一轮，
                # 词形下沉机械层=秒拒+精确返工指路。
                # v2.71：+who_no_repo_fact--who 出处合法性下沉机械层（judge 对
                # 选中角色选项的 who 裁量方差 ~2/6 误判，关键词扫描零方差）。
                mech_checks=(
                    "user_quote_channel",
                    "answer_no_reverse_inference",
                    "who_no_repo_fact",
                ),
            ),
            Step(
                kind="skill",
                ref="causal-inference-root-cause",
                short="规划拆解",
                # 拆解深挖·规划（2026-07-25 设计决议 + plan-first 拆步 2026-08-14）：
                # 逼问出的是「用户声称的问题」，须先横向拆（复合痛点 MECE 切分，防一捆
                # 问题混进后续）再纵向挖（因果链到根因，防拿症状当问题）。拆解必须在验真
                # 之前——拿一捆问题/症状去搜证据 = 白搜。复合问题的其余项不丢弃：带已
                # 验证陈述落 evidence，供后续 dl 实例接续。
                # plan-first：子2 一拆二——本步只规划（MECE 拆解 + 定档 → atomic_questions），
                # 无搜索（不设 deny_readonly）；因果链挖掘 + 取证路线归子2b。
                purpose=(
                    "拆解深挖·规划：①单一/复合判定——复合痛点按 MECE 拆成原子问题清单"
                    "（互不重叠、合起来覆盖全部痛点；单一则声明「无复合」理由）；"
                    "②每个原子问题定取证深度档——"
                    f"{_FETCH_TIER_RULE}。"
                    "本步**只规划不挖链**——因果链挖掘是子2b 的活。"
                    "原子问题清单连档作为载荷顶层 atomic_questions 键提交"
                    "（逐项 "
                    '{"q":<原子问题>, "tier":"none|light|full", "tier_reason":<分档理由>}，'
                    "与 MECE 清单一一对应——append-trace 逐项机械校验："
                    "tier 枚举/理由非空/none 档理由须含仓内路径，缺项当场拒；"
                    "首字母标签与 MECE 声明「原子 X」集合对齐"
                    "（未声明标签/同标签重复当场拒））。"
                    "输出走 evidence skill-trace（q/a 数组），不建单独 md。"
                ),
                input="step1.real_problem",
                record=True,
                selfcheck=(
                    "单一/复合判定了吗（复合→MECE 原子清单合起来覆盖全部痛点；"
                    "单一→附「无复合」理由）？"
                    "每个原子问题定档了吗（atomic_questions 逐项 q/tier/tier_reason，"
                    "拿不准标 light；none 档理由含仓内路径；你的论证用到的公式/"
                    "量级锚点都在仓内吗——在仓外=含外部知识依赖，不得标 none）？"
                    "atomic_questions 与 MECE 声明原子一一对应吗"
                    "（标签一致、一原子恰好一条）？"
                ),
                # 门控分工：子2a 只判「规划」结构完整性（MECE 互斥穷尽 + tier 档合理性），
                # 因果链证据真值归子2b，根因对不对归子4/子5 验真 + 子7 用户认可。
                # v2.72-v2.75（2026-08-04，designs/u1-sub2-gate-framing-design.md）：
                # §3.5 #28 泛化——framing 反转（从严→默认-PASS + 方框化真值判据）。
                # plan-first 拆步：原子2 gate 四方框按职责切分——方框四（none 档漏取证）
                # + MECE 原子清单结构归子2a gate；方框一/二/三（因果链证据）归子2b gate。
                # 两侧各保留「默认 pass」字面 + 合法正例段（§3.5 #28 牙齿不丢）。
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace 且 sub_step==2 的记录。"
                    "形式要件：①原子问题清单（≥1 个；单问题附「无复合」理由，"
                    "位置不限）；②每原子已定取证深度档。"
                    "（档枚举/理由非空/none 档仓内路径/MECE 标签对齐 已由 "
                    "append-trace 机械校验通过--你不得以这些形式要件为由 block，"
                    "只判下面两件事的真实性。）\n"
                    "默认 pass--仅当以下成立才判 block（每条附合法形态，"
                    "合法形态在场不得判）：\n"
                    "一、MECE 互斥穷尽：复合痛点拆出的原子清单互不重叠（互斥）、"
                    "合起来覆盖全部痛点（穷尽）——明显漏项或重叠=拆解未完成判 "
                    "block；单一痛点未附「无复合」理由判 block。单问题在 purpose "
                    "或 q/a 任一处附「无复合」理由即合规，不得要求拆成多原子或"
                    "指定理由位置。\n"
                    "二、none 档漏取证：论证含外部知识依赖（行业常识/第三方库"
                    "行为/方法论/数值合理性公式）却标 none 判 block；论证只用"
                    "仓内产物（仓内目录/报告/统计仓内数据得数量）=仓内可达，"
                    "问题用领域概念（如 IC/因子）提问但答案只是仓内计数/统计"
                    "同为仓内可达，标 none 合法不得判；该 full（开放设计问题）"
                    "标 light 且无升档空间论证判 block。\n"
                    "【合法正例】单问题在 purpose 或 q/a 任一处附「无复合」理由"
                    "即合规，不得要求拆成多原子或指定理由位置。方框以外一律不判。\n"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写"
                    "范例（指模式不指实例位置）。"
                ),
                # v2.40：原子问题分档清单（逐项 q/tier/tier_reason JSON 校验，
                # spec=engine._MECH_EXTRA_ITEM_CHECKS 注册名）——分类纠偏前置
                # 到规划步 gate（便宜环节），执行步子2b/子4 只执行不重新定档（禁降档）。
                # v2.50：+atomic_mece_alignment——aq 首字母标签与 MECE 声明
                # 「原子 X」集合对齐（att1 声明 3 原子交 5 条，judge 判两轮且
                # 判词搬旧计数失真；集合运算下沉后 judge 不再碰计数）。
                extra_payload_keys=(
                    ("atomic_questions", "fetch_tier_items"),
                    ("atomic_questions", "atomic_mece_alignment"),
                ),
                # 子2a 也禁 raw grep/rg：规划步的轻量侦察（定档需判"仓内可达"）走
                # dl codebase（结构化+落账去重），防"规划思考被搜索打断"重演。
                deny_readonly=("grep", "rg"),
                # 探索预算：规划步只做概念层 MECE+定档，定位实现符号是子2b 的活。
                # iter4 实证（2026-08-17）：子2a 跑 38 次 codebase/find 探索、56 轮、
                # 上下文胀到 114k——弱模型把执行冲动提前到规划步。机械堵入口：
                # codebase/find/python 探索命令超预算即 deny（见 Step.max_explore_calls）。
                max_explore_calls=8,
            ),
            Step(
                kind="skill",
                ref="causal-inference-root-cause",
                short="因果链挖掘",
                # 拆解深挖·执行（plan-first 拆步 2026-08-14）：子2a 产出 atomic_questions
                # 分档清单后，本步按档逐原子沿因果链挖到根因（原「拆解深挖」的纵向挖链
                # 部分）。只执行不重定档；发现子2a 漏原子/档错就地补并留痕，不回退 2a。
                purpose=(
                    "拆解深挖·执行：按子2a 的 atomic_questions 逐原子挖因果链到根因"
                    "（invoke causal-inference-root-cause，5 Whys/鱼骨/时序分析），"
                    "每环必须有可观察证据，禁纯叙事——"
                    f"{_CAUSAL_CHAIN_EVIDENCE_RULE}；"
                    "每个问题 ≥1 个竞争假设 + 排除/保留理由；区分近因与根因，标注置信度。"
                    "**按子2a 的档执行，不重定档**（发现子2a 漏原子/档错→就地补并在 "
                    "trace 标「执行期补规划」+原因，留痕即可，不回退子2a）。"
                    "输出走 evidence skill-trace（q/a 数组），不建单独 md。"
                    f"{_CODE_ARCH_ROUTE}"
                    "「待子3取证/待子3验证」标注是历史遗留词形——plan-first 拆步后"
                    "取证归子4 双向取证，该词形在置信度说明/竞争假设分支中仍作为合法"
                    "标注保留（引擎机械层按此词形豁免占环位判据），指代后续取证步消化。"
                ),
                input="step2.atomic_questions",
                record=True,
                selfcheck=(
                    "每个原子问题 ≥2 环因果链、"
                    "主链每环是实际证据指针吗（「未实测/推断」标注不算出处，"
                    "只允许出现在竞争假设分支——"
                    f"{_CAUSAL_CHAIN_EVIDENCE_RULE}）？"
                    "每环回答的是「异常数值如何形成」还是「谁调用谁/产物路径/"
                    "schema 描述」（后者有 file:line 也不算因果环）？"
                    "每个问题有 ≥1 竞争假设+排除/保留理由吗？近因/根因区分和置信度标了吗？"
                    "按子2a 的档执行、未重定档吗（就地补原子/改档须标「执行期补规划」+原因）？"
                ),
                # 门控分工：子2b 只判「因果链证据」质量（编造/同义反复/稻草人），
                # 根因对不对归子4/子5 验真 + 子7 用户认可（§3.5 三层分工）。
                # v2.72-v2.75 framing 反转（见子2a 注释）：本 gate 承接原原子2 gate
                # 方框一/二/三（证据编造/根因=症状换说法/竞争假设非稻草人），
                # 保留「默认 pass」字面 + 合法正例段（§3.5 #28 牙齿不丢）。
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace 且 sub_step==3 的记录。"
                    "形式要件：①每问题 ≥2 环因果链到根因；②每问题 ≥1 竞争"
                    "假设+排除/保留理由；③近因与根因区分+置信度。"
                    "（链环禁词/占环位/行号跨度/全局否定扫描留痕 已由 append-trace "
                    "机械校验通过--你不得以这些形式要件为由 block，只判下面三件事"
                    "的真实性。）\n"
                    "默认 pass--仅当以下成立才判 block（每条附合法形态，"
                    "合法形态在场不得判）：\n"
                    "一、证据编造或循环复述提问：指针/原话是模型虚构，或链环"
                    "只是换说法复述提问本身。\n"
                    "二、根因=症状换说法--根因与近因/症状是同一事实的换说法"
                    "（「X 慢因为 X 运行慢」式同义反复判 block）；根因比症状"
                    "深一层因果（如「候选太多 ← 没有缩减规则」：规则缺失导致"
                    "堆积=有因果推进）不算同义反复，不得判。\n"
                    "三、竞争假设非稻草人：假设明显不成立且排除理由无证据指针"
                    "=凑数判 block；排除理由引用具体原话或具体选择记录（如 "
                    "AskUserQuestion 选中项）=非凑数，不得以「假设本身看起来"
                    "不可能」单独判稻草人（「用户没有表达过/没说过」式缺席"
                    "断言已由 append-trace 机械拒，你不再判排除理由的指针形态）。\n"
                    "【合法正例】用户原话/会话事实是合法环证据指针（判据明文"
                    "枚举）--用户决策瓶颈类问题的因果环以用户原话为环合法，不得"
                    "发明「原话不是因果机制/必须 file:line」要件；「排除」以用户"
                    "选择/原话留痕为证据指针合法；置信度说明中「待子3验证」是"
                    "合法标注不算占环位；根因未证明不判--根因对不对归子4/子5 "
                    "验真与子7 用户认可，方框以外一律不判。\n"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写"
                    "范例（指模式不指实例位置）。"
                ),
                # v2.37：链环禁词（未实测/待实测/未验证/待验证/可能）写侧机械拒——
                # v2.36 钉死后 relaunch 仍两连 block，词形部分下沉机械层。
                # v2.75：+hypothesis_exclude_no_absence——v2.73/v2.74 重放实证
                # judge 对「排除理由无证据指针」双向抖动（v2.73 把缺席断言
                # 「用户没有表达过」当留痕放过 vio2 牙齿掉 4/6；v2.74 钉死后
                # 反伤 clean 1/6 + 自相矛盾判词）——缺席断言词形可判，下沉
                # 机械层零方差（§3.5 #13），judge 不再判排除理由指针形态。
                mech_checks=(
                    "causal_ring_no_untested",
                    "hypothesis_exclude_no_absence",
                ),
                # 执行步禁 raw grep/rg：symbol 关系查询只能走 dl codebase trace，
                # 字符串搜索走 dl codebase query --string（grep 的"堵入口"正治，
                # 弱模型无视软建议、只能硬围栏逼）。规划步子2a 无搜索不设。
                deny_readonly=("grep", "rg"),
            ),
            # 子4/子5（2026-07-26 重设计，designs/step3-verify-redesign-design.md）：
            # 旧单步「验真」对 F1 主张不可检验/F2 确认偏误/F5 证据不可追溯/F7 单视角
            # 四类失效无防御。按失效模式族拆两步：子4 管取证过程（双向+多源），
            # 子5 管判断质量（质检+对抗+裁决）。用户硬约束：禁 tavily/WebSearch。
            # plan-first 拆步（2026-08-14）：原子2 一拆二后全重编号，原子3/4/5/6
            # 顺延为子4/5/6/7；本步（双向取证）input 仍指 step2（子2a atomic_questions）。
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
                # v2.39（2026-08-01 tail_volume u:1 子3 复盘）：顺序钉死「先派发后内查」——
                # 实测主会话先做 3min 内部仓库层再派发 agent，之后空等 10min
                # （agent 4-8min 墙钟是最长杆），串行白烧 ~20% 步耗时；
                # ①→④ 编号即执行序，②末尾明示禁先内查后派发。
                # v2.40（designs/fetch-depth-tiering-design.md）：标称档来自子2
                # atomic_questions——none 禁派发（仅③内查）/ light 参数块 /
                # 禁降档（纠偏归子2 gate）/ light→full 升档留痕。
                # v2.42：fetch-prompt --out 落盘 per-workflow 目录——此前落盘
                # 路径由模型自选（tail_volume 实例选了共享 evidence/ 通用文件名：
                # 无归属、下一轮覆盖、残留旧 trace 误导），路径改由 engine 钉死。
                purpose=(
                    "按档取证（标称档 = 子2 atomic_questions，本步只执行不重定档；"
                    "外部层卸子代理，主会话只收蒸馏报告；"
                    f"{_FETCH_AUTHORITY_REGISTRY}"
                    "执行序钉死=①→②→③→④，禁调换）："
                    "①主张可检验化（主会话做）——每个 tier≠none 的原子问题 → "
                    "可证伪 claim + 事先写死「什么证据会证实/什么证据会证伪」；"
                    "不可检验的主张退回子2，不进入取证。"
                    "②立即派发外部取证子代理——`python3 ~/.dl-workflow/dl_flow_engine.py fetch-prompt --out` "
                    "落盘子代理 prompt 骨架到本工作流目录（stdout 打印路径，Read 该文件取骨架；"
                    "骨架自动携带子1-2 trace + 已分档原子清单 + "
                    "已验证命令模板 + 返回契约），只在末尾 claim 补充区逐原子填 claim"
                    "（骨架其余一字不动，禁手拼，禁自选落盘路径）；none 档原子禁派发（仅③内查）；"
                    "light 档原子按骨架【分档执行参数】light 参数块执行，claim 区"
                    "另指定 ≤2 层源；**禁降档**——标 full 的原子必须按 full 参数跑"
                    "（五层源双向；分档纠偏归子2 gate，不在本步）；每原子一个 Agent 子代理"
                    "**同一条消息并行单发**，且该 agent 的 claim 补充区只保留本原子的 "
                    "[tier=X] 行（其余原子行删除——台账按此标记归属统计轮次）；"
                    "**派发后才开始③——禁先内查后派发**（agent 运行 4-8min 是最长杆，"
                    "串行=白等，③与 agent 运行天然重叠）；"
                    "禁 tavily_search/WebSearch/WebFetch（WebFetch 本环境域验证全挂）。"
                    "③内部仓库层（agent 运行期间主会话自查）——codegraph 新鲜度前置"
                    "（`codegraph status <repo>` 看索引时间，>72h 才 `codegraph sync "
                    "<repo>`，查询结果留痕）+ Read/Grep/Bash 查数据，"
                    "证实/证伪问题在本仓存在 + 查已有解法；none 档原子在此全覆盖"
                    "（仓内可达即定答，无外部源）。"
                    "④收报告——子代理蒸馏报告**原文收录**进本步 trace：逐 agent 运行 "
                    "`python3 ~/.dl-workflow/dl_flow_engine.py append-trace "
                    "--ingest-agent <task-id>`（脚本按 task-id 提取报告原文落载荷 "
                    "qa 节——**禁手工复制粘贴**；提及/概括转述不算记录——"
                    "报告结构天然保证反证先/支持后时序可读）；报告未归不 append-trace"
                    "（占位符机械拒）；light 报告标「建议升档 full」时，对该原子补派 "
                    "full agent——原 light 报告与升档理由同样 ingest 收录（升档留痕）。"
                    "禁拿训练记忆冒充外部证据（无 URL/工具留痕的「业界通常」= 编造）。"
                ),
                input="step2.problem_list",
                record=True,
                selfcheck=(
                    "每个 tier≠none 的原子问题有可检验 claim（含证实/证伪判定标准）吗？"
                    "none 档原子未派发 agent（仅③内查）吗？"
                    "fetch-prompt 骨架经 --out 落盘到本工作流目录（未自选共享路径）、"
                    "只补了 claim 区、其余一字未动吗？"
                    "light 档按 light 参数块（≤2 层源/≤4 curl/单向锚点）执行、"
                    "claim 区指定了 ≤2 层源吗？标 full 的按 full 参数跑了吗（禁降档）？"
                    "每个 agent 的 claim 补充区只保留本原子 [tier=X] 行吗？"
                    "Agent 子代理先于内部仓库层派发了吗（先派发后内查，禁串行白等）？"
                    "每原子一个子代理并行单发、报告用 --ingest-agent 收录进载荷了吗"
                    "（禁手工粘贴；提及/转述不算记录）？标「建议升档 full」的原子补派 "
                    "full agent 并 ingest 收录升档理由了吗？内部仓库层 codegraph "
                    "新鲜度查询留痕了吗？"
                ),
                # S15 前置围栏：本步合法工具 = 内部仓库层（Bash）+ 取证子代理（Agent）；
                # 子代理进程内的 curl 经同一 PreToolUse 围栏、本步声明 Bash 故放行；
                # WebFetch 环境性弃用（2026-08-01 诊断）移出声明。
                # v2.xx：加 TaskOutput--模型派后台 agent 后用它阻塞等结果（tail_volume
                # u:1 子3 实证：TaskOutput 被 S15 误拦 -> 无法等 agent -> end_turn 假性
                # GATE block「无 trace」）。TaskOutput=harness 原生等后台 agent 机制，
                # 放行后模型主动等 agent 归来再写 trace，避免抢跑。
                fence_allow=("Bash", "Agent", "TaskOutput"),
                # v2.38：报告收录形式要件机械化——judge 重放实证旧形态（无报告项）
                # 也被判 PASS（内容丰富被当实质满足），形式核验下沉机械层。
                # v2.43：fetch_skeleton_out——骨架 --out 落盘机械核验
                # （EXISTS+entered_at 新鲜度，§8.3 同范式），「模型是否真的
                # 用了 --out」不再靠文案。
                mech_checks=("fetch_report_recorded", "fetch_skeleton_out"),
                # v2.77-v2.79（2026-08-04，designs/u1-sub3-gate-framing-design.md）：
                # §3.5 #28 泛化第三例——framing 反转（从严→默认-PASS）+ 方框化
                # 5 条真值判据 + 每条近端双侧钉死。基线 n=6：612 字从严版
                # clean 0/6 全误伤（短 gate 也 thrash——「长度=独立变量」之外
                # 从严 framing 本身即充分致病），vio1-6 牙齿 6/6。误判聚类→钉死位：
                # ①「原文收录」发明 raw_report/verbatim 要件→二合法形态钉死；
                # ②full 分段/五层表要件扩判 light→二/合法正例钉死；③真实 URL
                # 之外另索 curl 留痕+凭 URL 标题推断来源内容→三/四钉死（来源
                # 内容核验归子4）；④claim 要件扩判 none 档/证伪标准严格性→一钉死；
                # ⑤留痕索独立锚点/逐原子→合法正例钉死。v2.78 压跷跷板（clean 6/6
                # 但跨步牙齿塌）→v2.79 harness 注对照义务主句前置+四限定语。
                # 落地（n=6 三向）：clean 5/6、vio1-6 ≥5/6；残余=judge 对载明
                # 结论是否触及谓词的推理底分歧（判词自洽无发明要件），
                # prior_verdicts+escalate 兜底。
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace 且 sub_step==4 的记录。"
                    "形式要件：每个 tier≠none 的原子问题有可检验化 claim（含证实/"
                    "证伪判定标准）；light 档报告为锚点值+来源+量级对比；codegraph "
                    "新鲜度查询留痕。（报告收录项数按档核验/骨架 --out 落盘存在性与"
                    "新鲜度 已由 append-trace 机械校验通过——你不得以这些形式要件"
                    "为由 block，只判下面五件事的真实性。）\n"
                    "默认 pass--仅当以下成立才判 block（每条附合法形态，"
                    "合法形态在场不得判）：\n"
                    "一、claim 缺失：tier≠none 原子缺可检验化 claim 或证实/证伪"
                    "判定标准判 block；只判存在性、不判证伪标准的严格性（「无源"
                    "提及即证伪」式弱标准合法，标准质量归子5）；none 档原子无 "
                    "claim 要求（仓内可达仅内查），不得向 none 档索 claim 或判定"
                    "标准。\n"
                    "二、收录造假：蒸馏报告原文收录项实为提及/概括转述冒充（只有"
                    "「报告大意/结论如下」式转述、无报告自身结构）判 block；报告以"
                    "骨架规定形态呈现（light=锚点值+来源+量级对比，full=反证查询（先）"
                    "→支持证据（后）分段+五层状态表）即原文收录的合法形态，不得发明"
                    "「raw_report 字段/整段 verbatim/子代理原始输出文本」要件。\n"
                    "三、证据编造：声称外部证据无可追溯指针（真实 URL/工具调用留痕）"
                    "——用训练记忆冒充外部证据 = 编造，判 block；报告含真实 URL 即"
                    "满足可追溯指针（报告由子代理产出，curl 等执行留痕在子代理侧），"
                    "不得另索主会话 curl/工具调用留痕；URL 指向公开页面/检索/API 即"
                    "合法指针，不得判「未实际访问/无法核验 URL 内容」（来源内容核验"
                    "非本步判面）；「未取证+原因」合法标记不算冒充。\n"
                    "四、证据脱靶：外部证据不针对 claim 谓词、仅泛泛行业常识背景"
                    "（只解释概念/领域通史，不触及 claim 的证实/证伪）判 block；"
                    "报告载明来源针对 claim 的具体结论（「该页指出 X」式载明、触及 "
                    "claim 做法成立与否）即算针对、按载明采信，不得凭 URL 标题/来源"
                    "类型推断来源不支持 claim，不要求逐字回应谓词措辞或来源原文"
                    "摘录；只载明概念定义/领域通史类结论（如「IC 是常用指标」"
                    "「多因子模型起源」），未触及 claim 做法成立与否的，仍属脱靶。\n"
                    "五、档不一致：禁降档——标 full 的原子按 light 参数取证（无"
                    "五层状态表/仅 1-2 层源）判 block；light 报告标「建议升档 full」"
                    "而未补派 full agent（或未原文收录升档理由）判 block；none 档"
                    "原子出现外部取证报告 = 违规派发或子2 档标错，判 block；执行档"
                    "与标称档逐项一致（none 仅内查、light/full 各按其参数）即合规。\n"
                    "【合法正例】light 档报告单段「锚点值…（真实 URL）…来源=N 层…"
                    "量级对比…」即合规——不要求反证独立成段、不要求五层状态表、"
                    "不要求主会话 curl 留痕；none 档原子只有仓内内查结果（无 claim、"
                    "无报告项）即合规；新鲜度留痕步级一次即可、形式与位置不限"
                    "（sqlite 时间戳查询写在内查段内即合法），不得索「独立留痕锚点」、"
                    "不得要求逐原子留痕或指定 codegraph impact 查询形式。"
                    "方框以外一律不判。\n"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例"
                    "（指模式不指实例位置）。"
                ),
            ),
            Step(
                kind="tool",
                ref="推理(三关质检+四态合成) / 红队(driver预派发,回退Agent)",
                short="质检裁决",
                # 红队纪律 a-d 已机械化进 redteam_prompt()（v2.14「AI 定写什么，
                # 脚本定怎么写」）：a.携带子1-4 证据；b.单层；c.Read 为主；
                # d.证据不足下 verdict 不重取证。purpose 只留触发条件+调用方式。
                # 考古出处（P2 移自 purpose 原文）：a 无文件清单时嵌套层盲猜路径
                # 61 次 Read 全空；b 嵌套放大实录：3 嵌套 116k boot + 82 Read
                # 系统性重取证，且嵌套层出现问用户的角色错乱；c 实录 11 次
                # No such tool（Glob/Grep/codegraph 不存在）、Bash 21 次被 S15 空拒；
                # 「10/10 pass」式汇总声明 demo 实录被判 block。
                purpose=(
                    "质检裁决（不做新搜索，只审子4证据+下结论）："
                    "①证据三关质检——针对性(直接针对 claim 谓词)/独立性(来源互不转载)/"
                    "可追溯(URL、file:line 可复查)，三关不全过的证据不计数；"
                    "trace 须逐项可验证——每条计数证据逐条列出三关结果（E1…En × 三关），"
                    "「10/10 pass」式汇总声明不算记录；"
                    "②条件触发对抗复核——verdict 决定大方向/大改动、或证据相互冲突时，"
                    "需独立红队复核初步结论（独立上下文，触发条件写死，"
                    "不得自定义「不需要复核」豁免；"
                    "红队**输入**只给证据不给结论——不得把子5 初步结论喂给红队，"
                    "redteam-prompt 模板已机械保证；红队**输出**按纪律必含四态 "
                    "verdict，属合规非违规）。红队由 **driver 预派发**：子4 gate 通过后 "
                    "driver 已用 redteam-prompt（自动携带子1-4 证据+对抗纪律）后台起"
                    "独立红队会话，与本步并行——你**无需自己派发**，先做①三关质检与"
                    "③初步 verdict 草稿；收报告：运行 `python3 "
                    "~/.dl-workflow/dl_flow_engine.py append-trace --ingest-redteam`"
                    "（阻塞等报告就绪，脚本把红队报告原文落载荷 qa 节，标题自动含"
                    "「红队」「原文收录」——**禁手工复制粘贴**）；该命令报「无预派发/"
                    "无产出」时回退会话内路径：`python3 ~/.dl-workflow/dl_flow_engine.py "
                    "redteam-prompt` 生成红队 prompt，Agent 工具单发起（禁止手拼 "
                    "prompt），返回后 `append-trace --ingest-agent <task-id>` 收录；"
                    "「已发起红队」式提及或概括转述不算记录；"
                    "收录项标题须含「红队」「原文收录」（append-trace 机械校验：trace 含 task-id 或预派发 worker 在位 = 红队已派，无收录项 = 红队未归提前提交，当场拒——等归位收录后再提交，红队失败则重派/回退或升级用户裁决；红队未归位前禁输出 STEP_DONE——输出即提交、提交即拒）；"
                    "③四态结论合成——证实/证伪/部分成立/证据不足（证据不足是合法结论）"
                    "+ 推理链 + 置信度；"
                    "④按 verdict 处置问题集——证伪项剔除（留剔除理由）/部分成立项收窄到"
                    "已证实边界/证据不足项带标记进入读回；处置后问题集 = 子6 唯一输入。"
                ),
                input="step4.traces",
                record=True,
                selfcheck=(
                    "每条计数证据逐条列出三关质检结果了吗（E1…En × 三关，汇总声明不算记录）？"
                    "红队触发条件满足时确认红队已派了吗（driver 预派发；无预派发则 "
                    "redteam-prompt + Agent 回退，禁止手拼）？"
                    "红队输出已用 --ingest-redteam（或回退 --ingest-agent）收录进载荷了吗"
                    "（收录项标题含「红队」「原文收录」；已派未收录 = 提前提交，"
                    "append-trace 机械拒；禁手工粘贴、提及/概括转述不算记录）？"
                    "每个原子问题有四态 verdict+推理链+置信度吗？"
                    "处置后问题集与 verdict 逐项一致吗（证伪剔除+理由/部分收窄/不足标记）？"
                ),
                # S15 前置围栏：条件触发红队子代理（Agent 回退路径）；子代理进程内
                # Read/Grep 在常驻集，无需声明。主路径 = driver 预派发 +
                # --ingest-redteam（Bash 走引擎命令，常驻放行）。
                # v2.xx：加 TaskOutput--红队 agent 同为后台派发，模型需用它等结果
                # （同子4，防抢跑假性 block）。
                fence_allow=("Agent", "TaskOutput"),
                # v2.44：红队已派发（trace 含 task-id）而无「红队…原文收录」
                # 标题项 = 红队未归提前提交，append-trace 当场拒（词表扫描被
                # 措辞绕开的实证收口，信号分隔度见 engine 函数 docstring）。
                # u1-sub5-cost 修3：driver 预派发通道同牙齿（worker.json 在位
                # 而无收录项 = 提前提交）。
                mech_checks=("redteam_report_recorded", "redteam_three_piece"),
                # u1-sub5-cost 修3：红队改 driver 预派发（子4 证据冻结即具备输入），
                # 与本步段并行——实测红队跑 158-235s 而主会话有效并行 ≤1min。
                pre_dispatch="redteam",
                # O3（u1-overall-cost）：本步是收录原文唯一消费步（①三关质检逐条
                # 审子4 fetch 报告 + ②红队报告）——交接包对本步保收录项全文。
                pack_full_reports=True,
                # v2.80-v2.83（2026-08-04，designs/u1-sub4-gate-framing-design.md）：
                # §3.5 #28 泛化第四例--framing 反转 + 方框化 4 条真值判据 + 双侧钉死。
                # 基线 n=6：490 字从严版 clean 0/6 + vio1-4 牙齿 6/6。v2.80 反转后
                # clean 4/6 但 vio 牙齿崩（语义判据默认放行下漏判）。v2.81 把真违规
                # 明列为 block 条件：vio2 5/6、vio4 6/6 达标，clean 4/6（判据三 E2
                # 误伤）+ vio1 4/6。v2.82 判据三/四收紧反伤（clean 3/6）回退。v2.83：
                # vio1 三件套缺失词形可判->下沉 mech redteam_three_piece（生产墙 100%，
                # #2 缺席断言同范式）+ 判据一改「三件套已 mech 校验、judge 只判转述
                # vs 原文」+ 判据三钉死「触及 claim 方向（检索含 claim 关键词）即算
                # 针对、概念定义=脱靶」（治 clean#4 E2 误伤 + vio3 漏判，撤 v2.82 反伤）。
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace 且 sub_step==5 的记录。"
                    "形式要件：每条计数证据有三关质检记录（逐条列出针对性/独立性/"
                    "可追溯三关结果，✓标记即记录）；每个原子问题有四态 verdict"
                    "+ 推理链 + 置信度（四态=verdict 取值域，每问题给一个：证实/"
                    "证伪/部分成立/证据不足，非要求列出全部四种）；处置后问题集与 "
                    "verdict 逐项一致（证伪项已剔除+理由、部分成立项已收窄、"
                    "证据不足项已标记）。（红队已派发未收录的提前提交已由 "
                    "append-trace 机械层拦截--trace 含 task-id 或 driver 预派发 "
                    "worker 在位而无收录项不会到你这里；收录项存在性与三件套完整性"
                    "已机械校验，你不得以这些形式要件为由 block，只判下面四件事的真实性。）\n"
                    "默认 pass--仅当以下成立才判 block（每条附合法形态，"
                    "合法形态在场不得判）：\n"
                    "一、红队收录造假：红队触发条件满足时（trace 含 task-id 或收录项"
                    "标题含「driver 预派发」），仅提及/"
                    "概括转述红队而未原文收录其输出判 block。红队收录项三件套完整性"
                    "（verdict/推理链/置信度）已由 append-trace 机械校验通过（缺任一已"
                    "当场拒、不会到你这里）--你只判收录内容真实性：三件套齐全但实为"
                    "模型概括转述非红队输出判 block；收录项含三件套即原文收录的合法"
                    "形态（收录项由 append-trace 从子代理 transcript 提取，非手工概括），"
                    "不得以叙述形式/未贴子代理原始输出文本判概括转述，不得发明"
                    "「raw_report/Q 列表/外部源引用列表」要件。红队输出含 verdict 是"
                    "纪律 4 的要求、属合规非违规，只给证据不给结论仅约束红队**输入**"
                    "（不得含子5 初步结论，由 redteam-prompt 模板机械保证、不重复判）"
                    "--红队**输出**含「未推翻初步结论/建议收窄」是 verdict/推理链的"
                    "正常表述，不得以红队输出含初步结论引用判输入违规。\n"
                    "二、推理链跳跃：每个原子的 verdict 推理链须基于该原子自身证据"
                    "（该原子的仓内统计/外部源）；推理链出现另一原子的证据或 claim"
                    "=跨原子借用（如 A 的 verdict 推理链引用 B 的外部源、缺 A 谓词桥接），"
                    "判 block。\n"
                    "三、质检放水：明显不针对 claim 谓词的证据（只解释概念/领域通史、"
                    "不触及 claim 证实/证伪，如「IC 是常用指标」「多因子模型起源」式"
                    "概念定义、来源仅领域术语不含 claim 关键词）被计数判 block；证据"
                    "触及 claim 方向（来源/检索含 claim 关键词如「取反/reverse/方向」、"
                    "返回相关文献或未提供反例）即算针对，不要求载明具体结论。\n"
                    "四、处置不一致：看处置实质非声明--部分成立项须实际收窄到已证实"
                    "边界：保留已证实边界陈述+未证实部分标记为证据不足/待证（提及未证实主张并标记不足=合规、不删字样、不得要求移除已证实边界）；证伪项须剔除+理由，证据不足"
                    "项须标记；处置后问题集与 verdict 逐项一致即合规。部分成立项保留原"
                    "完整陈述（未收窄）判 block，不论载荷是否声称「逐项一致」。\n"
                    "【合法正例】每问题给一个四态之一 verdict 即合规（不要求四态全枚举）；"
                    "三关✓标记即三关质检记录（不要求逐关独立裁决字段/各关判定依据）；"
                    "红队输出三件套即原文收录（不要求 raw 任务输入/Q 列表/证据条目原文）；"
                    "E2 元数据层（真实 URL、载明来源、检索含 claim 关键词）属子4 light 档"
                    "合规证据、不判脱靶；部分成立项收窄=保留已证实边界+未证实标记（如「方向口径成立（已证实），行业做法充分性不足（标记待证）」=合规、不删字样、不移除已证实边界）；前序各步记录是一致性对照锚点（artifact=当前步+"
                    "前序各步最新 trace 拼合是生产常态），其存在与组成形式不作 block 依据。"
                    "方框以外一律不判。\n"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例"
                    "（指模式不指实例位置）。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem",
                short="归一化陈述",
                # 归一化陈述（2026-07-26 重设计，
                # designs/step5-step6-statement-readback-redesign-design.md）：
                # 职能 = claim normalization（原子+去上下文+verdict 传导），不是压缩话术。
                # RCA：problem statement 取证前写（子1），root cause statement 证据检验后写（子6）。
                purpose=(
                    "归一化陈述：对子5处置后问题集逐项产出归一化问题陈述——"
                    "①原子（单句≤1个独立痛点，「和/以及/同时」连接多痛点=复合未拆净，回子2重拆）；"
                    "②去上下文（脱离本会话可独立理解：对象+动作+约束自包含；"
                    "中文省略主语合法，动宾短语「统计 X 的数量」即合规，不必凑语法主语）；"
                    "③携带 verdict 边界与置信度（部分成立项陈述只覆盖已证实边界）；"
                    "放不进一句=未定义完。"
                    '载荷格式：statements 逐项 {"text":单句陈述,'
                    '"type_label":verdict（证实/部分成立/证据不足——证伪项已剔除不入集）,'
                    '"boundary":已证实边界+证据指针（实现指针/file:line/机制链都进这里）,'
                    '"fields":{"confidence":置信度}}——text 只许 outcome-level 概念，'
                    "实现侧名词/file:line 只能进 boundary（append-trace 机械扫描，命中即拒）。"
                    # u1-time-opt 修B（designs/u1-time-opt-design.md §2.3）：
                    # L4 格式真源钉死平移第三例（u:3#4 同文——本步有条目传导
                    # 机械核对 factor[X]，保留「编号传导」）。interaction run
                    # 实证：条目传导被拒（缺 factor[D]，报错文案已指路）后模型
                    # 不修文案反而 evidence 元探查 10 调用 + Read/grep 引擎源码
                    # 反推校验实现，2.3min 猎捕。
                    "载荷格式与编号传导的唯一真源 = --scaffold 骨架 + append-trace "
                    "报错文案（四桶分工：格式归脚本）——禁读引擎/测试源码反推校验"
                    "实现；被拒按报错文案逐字修即可。"
                ),
                input="step5.disposed_problem_set",
                record=True,
                record_format="statements",
                statement_fields=("confidence",),
                selfcheck=(
                    "每条陈述单句只含 1 个独立痛点吗（「和/以及/同时」连接多痛点=复合未拆净，"
                    "回子2重拆）？脱离本会话可独立理解吗（对象+动作+约束自包含；"
                    "中文省略主语合法，不必凑语法主语）？"
                    "type_label 逐项携带 verdict、fields.confidence 逐项携带置信度了吗？"
                    "证伪项不在陈述集里吧？"
                    "text 逐条无实现侧名词吧（文件名/类名/file:line 只进 boundary，"
                    "append-trace 机械扫描会拒）？"
                    "格式照 scaffold 骨架填了吗——没去翻引擎/测试源码反推校验"
                    "实现吧（被拒按报错文案修）？"
                ),
                # v2.85（2026-08-04，designs/u1-sub5-gate-framing-design.md）：
                # §3.5 #28 泛化第五例--framing 反转 + 方框化 4 条真值判据 + 双侧钉死。
                # 基线 n=6：326 字从严版（全 workflow 最短 gate）clean 1/6、vio1-3
                # 6/6、vio4 4/6——最短 gate 仍崩，进一步证伪「长度是主因」，从严
                # framing 本身即充分致病（#28 第五实证）。误判聚类→钉死位：
                # ①最高频「『统计…数量』是动宾短语缺主语/非陈述式」不是 judge 发明
                # 要件，是判据自己写的「含主语+动词+约束」被字面索取（中文省略主语
                # 合法，真实意图=self-contained）→按 #23 修文本不站队，且按 #29
                # 跨层同向 purpose/selfcheck/gate 三层齐改（只改 gate=judge 放行
                # 而模型照错写）；②句内定语当并列（无连接词也判）→条款三钉死
                # 「修饰成分/约束枚举不算并列」；③判 type_label 字段缺失（字段在场）
                # +④索 evidence 路径声明=v2.34 幻觉族→无条件 JSON 校验项声明已机械
                # 校验；⑤索数值化置信度→合法正例钉死。**不声明**实现侧名词扫描已
                # 机械校验：_implementation_nouns 是可降级预检（codegraph db 缺失
                # 即跳过，judge 是兜底层），声明=db 过期时两层同时失守。
                # 落地（n=6 三向）：clean 1/6→6/6、vio1 6/6、vio2 6/6、vio3 5/6、
                # vio4 4/6→6/6（从严多拦的全是噪声，#28）。无压跷跷板信号→不下沉
                # mech（亦避开 statements 分支不执行 mech_checks 的结构障碍）。
                gate=(
                    "evidence/<name>.jsonl 含本子步骤 skill-trace 记录。"
                    "形式要件：处置后问题集每个存活问题各 ≤1 句且去上下文"
                    "（对象+动作+约束自包含，中文省略主语合法）。"
                    "（statements 三字段非空、type_label 携带 verdict、"
                    "fields.confidence 携带置信度 已由 append-trace 逐项 JSON "
                    "机械校验通过——你不得以「缺 type_label/缺置信度/字段不齐/"
                    "未声明 evidence 路径」为由 block，这些字段在场是机械已知事实。）\n"
                    "默认 pass--仅当以下成立才判 block（每条附合法形态，"
                    "合法形态在场不得判）：\n"
                    "一、裁决不传导·证伪项混入：子5 判证伪的问题出现在陈述集"
                    "（证伪项不得出现在陈述集）判 block；子5 未判证伪的问题、"
                    "以及子5 标「证据不足」的问题进入陈述集是合法形态（证据不足是"
                    "子5 四态之一的合法 verdict，带标记进入读回由用户裁决），"
                    "不得以「结论不确定/未定义完」为由判。\n"
                    "二、裁决不传导·边界超出：部分成立项陈述超出子5 已证实边界"
                    "（抹掉子5 的口径限定、改成更强断言：如子5 限 default 管线/"
                    "报告快照而陈述称全部管线/实时）判 block（裁决不传导判 block）；"
                    "陈述以「在 X 口径下」收窄、或 text 概括而限定词写在 boundary "
                    "字段，都是传导正确的合法形态，不得索取比子5 更强的断言，"
                    "也不得要求 text 逐字复刻子5 措辞。\n"
                    "三、复合未拆：单句用「和/以及/同时/并」连接多个**独立**痛点"
                    "（各自可单独成为一个问题）判 block；同一目标的约束枚举、"
                    "修饰成分、定语（如「default 管线最新报告中」「严格大于 0 的」"
                    "「截至某日的」）不算并列——无上述连接词、或连接的成分服务"
                    "同一个目标时，不得判并列。\n"
                    "四、实现侧名词未挪 boundary：text 含文件名/类名/函数名/"
                    "file:line（如 xxx.py、SomeClass、「第 31-104 行」）判 block"
                    "（未挪 boundary）；boundary 字段含实现指针/file:line 是判据"
                    "规定的去处，不得因 boundary 有实现细节而判 text 违规。\n"
                    "【合法正例】text 为动宾短语、省略主语（「统计 X 的数量」"
                    "「确定 Y 的口径」）即合规——去上下文指脱离本会话可独立理解，"
                    "不要求语法主语，不得判「缺主语/非陈述式/祈使短语」；"
                    "type_label 取值用子5 四态词（证实/部分成立/证据不足）即合规，"
                    "不要求特定枚举命名或数值化置信度；产物含子5 记录是生产常态"
                    "（一致性对照基准），不得以「跨子步串号/字段混入/sub_step "
                    "自相矛盾」为由判。方框以外一律不判。\n"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例"
                    "（指模式不指实例位置）。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem",
                short="读回确认",
                interactive=True,
                # 带证据的读回确认（2026-07-26 重设计）：只给结论不给依据地「通知」用户
                # = 不信任甚至 backfire effect（Das et al. 2023）；fact-checker 三大解释
                # 需求 = 不确定性/证据指针/过程可解释（Show Me the Work, CHI 2025）。
                purpose=(
                    "带证据的读回确认：材料 = 运行 `python3 ~/.dl-workflow/dl_flow_engine.py render-readback` 机械装配逐字呈现（本节点归一化+假设/不确定性 traces，禁手抄；Bash 输出即呈现）。呈现内容 = 归一化陈述+四态 verdict+证据指针+置信度"
                    "（「证据不足」项显式暴露，由用户裁决继续/等恢复/放弃）；"
                    "用户认「这就是问题（集）」；多个问题时用户选定本实例处理哪一个，"
                    "其余带已验证陈述落 evidence + understand.md（供后续 dl 实例接续，不丢弃）；"
                    "用户对各项的认/否/搁置记入 trace（用户认可本身是裁决留痕）；"
                    f"{_INTERACTIVE_CHUNKING_RULE}。{_USER_DECISION_RECORD_RULE}"
                ),
                input="step6.statements",
                # §substep-gate-at-stop：record=True——Stop 门控以「新 trace」为唯一
                # 完成触发，record=False 的末步永无触发信号、子阶段永远卡住（3a 潜在洞）。
                # 确认内容本身也是裁决留痕（用户认可了问题陈述）。
                record=True,
                selfcheck=(
                    "向用户呈现含归一化陈述+四态 verdict+证据指针+置信度了吗？"
                    "「证据不足」项显式暴露了吗？用户对各项的认/否/搁置记入 trace 了吗？"
                    "多问题时用户选定本实例处理项、其余落 evidence+understand.md 了吗？"
                ),
                # v2.45 交接架构正确性前提：用户裁决必入 trace（gate=None 无 judge，
                # 机械校验是唯一防线）。
                mech_checks=("user_decision_recorded",),
                gate=None,  # 交互步，gate 不跑 judge（trace 存在即过）
            ),
        ),
        minor_key="ProblemContext",  # evidence minor_stage 值（结构标识,模型照抄注入给的当前值）
        # 无 hold_for_gate（用户决议 2026-07-28）：围栏只设在 plan 完成，
        # understand 全部子阶段末步过门控即自动推进，中途不停。
        # u1-prefix-strip 置位（designs/u1-prefix-strip-design.md §1 两核对已过）：
        # 逐步工具需求——子4 双向取证需 Agent（探针 J 实证白名单下可派发），
        # 故白名单 = u:2 四件 + Agent；CLAUDE.md 引用逐处过：全是「约束源/证据
        # 材料」的 Read 指针（模型按指针定向 Read，不依赖自动加载），codegraph
        # 命令模板 v2.38 起逐字在 purpose/fetch-prompt 内；auto-memory 按段 cwd
        # 编码目录本就为空。红队预派发 worker（子5）同步剥 env（dl_drive 接线）。
        # 不上 MERGED_RUN_NODES：段链 08-17 峰值 324k 破 250k 护栏回滚在先，
        # 步体重（17-30 调/段）合并必撞 ctx 护栏（#21 判据）。
        segment_strip_project_context=True,
        segment_tools=("Bash", "Read", "Edit", "Skill", "Agent"),
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
                interactive=True,
                # 形式要件披露进 purpose（降形式性返工）；质量判据只留 gate 黑盒。
                purpose=(
                    f"目标引出：{_G2_STEP1_FORM_REQUIREMENTS}。"
                    "方法：从 ProblemContext 归一化问题陈述（evidence 里 "
                    "minor_stage=ProblemContext 的最新子6 trace）逐条问"
                    "「解决了它 = 达成什么状态」（KAOS WHY/HOW 问）；"
                    "取证纪律同 ProblemContext 子1——优先引用上下文已有的用户原话"
                    "（会话事实可作佐证），禁止为凑字段重问用户已答过的内容；"
                    "真正缺失的维度才用 AskUserQuestion 事实性补问"
                    "（补问的回答原话是②的合法佐证）。"
                ),
                input="ProblemContext.step6.statements",
                record=True,
                # v2.48：价值/结论项推断词形写侧机械扫描（2026-08-02 att1：
                # 披露后仍写入「意味着/隐含」且自声明「无推断补全」——自声明
                # 不可信，词形下沉机械层，同 v2.37 u:1 子2 先例）。
                # v2.87：+answer_source_marker/goal_candidate_traceability_alignment
                # ——framing 反转（默认-PASS）后 vio1 孤儿候选/vio2 无出处标注
                # 在 judge 侧 1-4/6 裁量方差，词形可判子项（候选标签↔追溯项集合
                # 对齐、出处标注在场）切出下沉零方差生产墙，judge 只判声称对应
                # 真实性与引述对口性（#30 ⑤/⑭，designs/u2-sub1-gate-framing-design.md）。
                mech_checks=(
                    "value_no_unsourced_inference",
                    "answer_source_marker",
                    "goal_candidate_traceability_alignment",
                ),
                selfcheck=(
                    "who/outcome/初步价值三类都覆盖了吗（每类 ≥1 条即达标）？"
                    "每条 a 有出处标注吗（用户原话：'…'/原始请求：'…'/会话事实：…），"
                    "还是我推断补全的（推断只能标「推测」另列）？"
                    "结论选了①还是②、每句都有出处吗？①的每个目标候选都在追溯项"
                    "逐项对应到 ProblemContext 存活问题吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=GoalsAndValue 且 sub_step==1 的记录；"
                    f"形式要件：{_G2_STEP1_FORM_REQUIREMENTS}。"
                    "（q/a 配对对齐与各答案非空、who/outcome/初步价值项出处标注在场"
                    "与 who 项引述指向人、目标候选标签与追溯项逐项对齐、价值/结论项"
                    "推断词形【隐含/意味着/可能】已由 append-trace 机械校验通过——"
                    "你不得以这些形式要件为由 block，只判下面两件事的真实性。）\n"
                    "默认 pass——仅当以下成立才判 block（每条附合法形态，"
                    "合法形态在场不得判）：\n"
                    "一、结论以①申报时，仅一种判 block：\n"
                    "出处张冠李戴：答案有出处标注但引述与所答类目明显无关"
                    "（如 outcome 项引「用户原话：'我自己'」——人物自述不指向达成"
                    "状态）判 block；短答案带对口原话引用（who=「用户原话：'我自己'」、"
                    "outcome=「原始请求：'有多少个因子的 IC 为正'」）是合规形态——"
                    "答案简短、每类只答 1 条、价值与 outcome 措辞相近均不判。"
                    "候选与存活问题的承接真实性（硬连/脑补挂接）归子2 对齐质检步"
                    "带双向追溯矩阵判，本步不判。\n"
                    "二、结论以②申报时，仅三种判 block（佐证缺失族）：\n"
                    "(a) 无引述裸声明：仅写「字面请求即全部/没有进一步诉求」而无"
                    "「用户原话：'…'」式直接引述=无佐证判 block；\n"
                    "(b) 未问先引：以「用户未提及…」代替补问回答原话判 block"
                    "（须先问再引）；\n"
                    "(c) 佐证不对口：结论句援引的佐证须是直接回答「是否还有进一步"
                    "目标/诉求」的补问原话——只援引 who/outcome/初步价值项的原话"
                    "（如「我自己」「决定筛选门槛」）不算②的佐证判 block；"
                    "who/outcome/价值项自身的原话引用是其类目合法出处，不因此判"
                    "违规（本项只约束结论句的佐证来源）。\n"
                    "【关键】结论以①申报时第二项不适用，以②申报时第一项不适用——"
                    "不得以「缺②的原话佐证」block ①的载荷，不得以「缺目标候选」"
                    "block ②的载荷。答案内声明「用户原话：'…'」「原始请求：'…'」"
                    "即合法出处形态——judge 看不到会话原文，不得要求原话「可核验」"
                    "「与会话记录/前序印证」「更完整引用」，不得要求 evidence 体现 "
                    "AskUserQuestion 调用轨迹。结论末尾「全部事实均有出处」式自检"
                    "总括是合法元声明，不作「无出处推断」判。\n"
                    "【合法正例】who=「用户原话：'我自己'」三字答案合规；初步价值"
                    "只答 1 条（「用户原话：'继续筛选'」）合规（三类各 ≥1 条即达标）；"
                    "G1「得到该口径下正 IC 因子数量，用它决定筛选门槛」承接存活问题"
                    "「统计 IC 均值>0 的因子数量」合规——动作层延伸不算脑补；"
                    "结论②以补问原话「没有了，就这个」佐证合规。方框以外一律不判。\n"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例"
                    "（指模式不指实例位置）。"
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
                # pack_self_contained 置位核对（u2-sub2-cost §2，逐字段）：矩阵输入
                # =子1 目标候选+出处（包内本节点留痕全文 ✓）+PC 存活问题陈述
                # （包内前序节点摘要 statements 全文 ✓）；u2_sub1_ab 实测包外零引用。
                pack_self_contained=True,
                selfcheck=(
                    "双向矩阵逐项列出了吗（问题×目标，汇总声明不算）？"
                    "孤儿目标/孤儿问题都显式处置了吗（剔除/退回补问/搁置+理由）？"
                    f"含方案名词的目标剥到 outcome 了吗（{_SOLUTION_FREE_SUBJECT_RULE}）？"
                    "目标间冲突检测做了吗"
                    "（无冲突须显式声明）？"
                ),
                # v2.86（designs/u2-sub2-gate-framing-design.md）：从严 framing 反转为
                # 默认-PASS + 方框真值判据。基线 clean 2/6（发明「矩阵须表格形式」/
                # 「主语操作性核对」要件）；反转后 clean 6/6、vio1-3 全 6/6（n=6 MiniMax）。
                gate=(
                    "默认 pass--仅当以下成立才判 block。"
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=GoalsAndValue 且 sub_step==2 的记录；"
                    "形式要件：双向追溯矩阵逐项列出--backward（每个目标 ≥1 问题回溯）"
                    "+ forward（每个存活问题有承接目标或显式搁置+理由）各以具体问题/目标"
                    "点名列出即合规，不要求表格/M×N 形式，prose 逐项即算逐项列出；"
                    "孤儿项显式处置留痕；含方案名词/实现动词的目标已改写为 outcome"
                    f"（{_SOLUTION_FREE_SUBJECT_RULE}）；目标间冲突已标注（或显式声明无冲突）。"
                    "方框判据（仅以下判 block）：一、同义反复：剥离后 outcome 是"
                    "「做 X 为了能做 X」（outcome 复述方案动作本身、无真实状态转换）判 block；"
                    "outcome 指向用户可见状态/数字/信号即非同义反复，"
                    "不要求显式「非同义反复验证」声明。"
                    "二、矩阵放水：明显无关联的问题-目标硬连（脑补目标挂到无关问题上）判 block；"
                    "目标与问题有承接逻辑即非放水，不要求逐行展开明细。"
                    "三、汇总声明无逐项矩阵：矩阵的 backward/forward 对应关系仅以"
                    "「全部对齐/所有目标均已对齐/每个存活问题都有目标承接」式泛指呈现、"
                    "不点名任何具体问题与目标的对应判 block；"
                    "点名了具体问题×目标（标识或内容）即非汇总。"
                    "【合法正例】backward+forward 各以具体问题/目标点名列出即逐项"
                    "（prose 即可，不要求表格）；主语无实现侧名词即 outcome-level"
                    "（不要求「主语操作性核对」；「用于决定 X」「以 X 决策」=决策用途="
                    "outcome-level，非方案动作）；前序子1 trace（goal_candidates）"
                    "是锚点非判对象，其存在与组成不作 block 依据。方框以外一律不判。"
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
                # v2.89（designs/u2-sub3-gate-framing-design.md）：从严 framing 反转为
                # 默认-PASS + 方框真值判据。基线 clean 0/6 全误伤（受益者原话留痕/价值链
                # 痛点出处/基线完整命令 等发明要件）；反转后 clean 6/6、vio1/3/4/5 全 6/6。
                # 基线编造=词形可判子项（工具动词在场与否）下沉 baseline_tool_trace 生产墙
                # 100%（judge 侧 4-5/6 注意力方差，#30 ⑭），judge 只判留痕在场后的语义残项。
                mech_checks=("baseline_tool_trace",),
                selfcheck=(
                    "每个目标有受益者吗（who 只认用户自述）？价值链连到承接痛点了吗？"
                    "基线实测留痕（Bash 输出）或显式标「不可量化+原因」了吗？"
                    "must/nice 每条附理由了吗（只提案、未替用户拍板）？"
                ),
                # S15 前置围栏：本步合法工具 = Bash（条件性基线测量）。
                fence_allow=("Bash",),
                gate=(
                    "默认 pass--仅当以下成立才判 block。"
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=GoalsAndValue 且 sub_step==3 的记录；"
                    "形式要件：每个目标有受益者+价值链+基线（或显式「不可量化+原因」标注）"
                    "+must/nice 提案附理由，逐项齐全；各项合法形态=受益者「出处为用户自述"
                    "原话'我自己'」即合规（不要求原话转录/用户画像佐证）；价值链=点名具体"
                    "痛点+价值类型的一句话即合规（不要求中间环节展开/痛点逐项原话出处）；"
                    "基线=「Bash实测…」式声明+关键数字即合规（不要求命令转录/原始输出/"
                    "文件路径）；nice=无 附镀金/未确认独立目标理由即合规——「当前对齐目标集"
                    "只有G1；额外提供因子名单、阈值建议或自动筛选均未被用户确认为独立目标，"
                    "添加会形成镀金目标」即完整合规形态（「添加会形成镀金目标」这一句即"
                    "镀金理由，不要求再展开）。"
                    "方框判据（仅以下成立判 block，每条附合法形态、合法形态在场不得判）："
                    "一、空泛复述：无受益者、无基线、无痛点链接的「提升效率」式空断言判 block"
                    "——价值链点名痛点+价值类型即非空泛，一句话价值链即够。"
                    "二、基线编造：基线数字留痕（工具动词在场与否）已由 append-trace 机械校验"
                    "——无工具留痕的拍脑袋数字已被当场拒、不会到你这里，你不得以「基线留痕"
                    "缺失」为由 block；只判——留痕在场但数字与声明来源明显矛盾（如声明"
                    "「Bash实测」default 报告却给不出与报告时间线吻合的数字）判 block；"
                    "「Bash实测…」式声明+关键数字=合法留痕形态，不得要求命令转录/原始输出/"
                    "文件路径/可复现性。"
                    "三、全 must 无真实取舍：多目标全 must 且无任何 nice 讨论/取舍理由判 block"
                    "——单目标 must+「不达成即失败」理由=合规；nice=无 附镀金理由=合规"
                    "——「添加会形成镀金目标」这一句即镀金理由。"
                    "四、分层无理由：「重要所以 must」循环论证或无理由判 block——「若不能提供"
                    "…本实例即未回答核心问题」=「不达成即失败」等价表述=合法理由，非循环论证；"
                    "「有 workaround 可继续」=nice 试金石=合规。"
                    "五、替用户拍板：分层以定案口吻（「已定」「确定为 must」「无需用户裁决」）"
                    "判 block——「此为提案，未替用户拍板/最终裁决留给子5 用户」=合规形态。"
                    "【关键】nice=无 附理由不得以「未单列理由」block；不得以「缺 nice 提案」"
                    "block 单目标节点。前序子1/子2 trace 是锚点非判对象，其存在与组成、跨步"
                    "一致核对不作 block 依据——本步受益者与前序 who 出处一致即合规，不要求"
                    "本步重引/逐字印证。"
                    "【合法正例】受益者「出处为用户自述原话'我自己'」合规；价值链一句话"
                    "「G1'…决定因子筛选门槛' → 承接痛点'候选太多' → 价值类型=决策支持/"
                    "筛选效率」合规；基线「Bash实测最新default报告：baseline_total=72，"
                    "positive_ic_mean=14…」合规；「提案G1=must…此为提案，未替用户拍板」合规；"
                    "「nice目标提案=无。当前对齐目标集只有G1；额外提供因子名单、阈值建议或"
                    "自动筛选均未被用户确认为独立目标，添加会形成镀金目标」合规——「添加会"
                    "形成镀金目标」即镀金理由、无需再展开。方框以外一律不判。"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例"
                    "（指模式不指实例位置）。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem",
                short="归一化陈述",
                # claim normalization 职能同构 ProblemContext 子6（同一 skill 承担）；
                # 可消费陈述三属性 = atomic / decontextualized / check-worthy
                # （Deng et al. 2024，见 goals-and-value-substeps-design §4）。
                purpose=(
                    "归一化陈述：对子3 论证后目标集逐项产出归一化目标陈述——"
                    "①原子（单句≤1个独立目标，「和/以及/同时」连接多目标=复合未拆净，"
                    "回子1 重引）；"
                    "②去上下文（脱离本会话可独立理解：主语+动词+约束自包含）；"
                    "③携带 must/nice 提案与 verdict 边界（部分成立问题的目标只覆盖"
                    "已证实边界——裁决传导，同构 ProblemContext 子6）；"
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
                    "evidence/<name>.jsonl 含 kind=skill-trace、minor_stage=GoalsAndValue 且 sub_step==4 的记录。形式要件：子3 目标集每项各 1 条陈述（单句、去上下文=对象+动作+约束自包含）。（statements 三字段非空（text/type_label/boundary）已由 append-trace 逐项 JSON 机械校验通过——你不得以「缺 type_label/缺 boundary/字段不齐/未声明 evidence 路径」为由 block，这些字段在场是机械已知事实。）\n"
                    "默认 pass——仅当以下成立才判 block（每条附合法形态，合法形态在场不得判）：\n"
                    "一、传导断裂·分层不一致：type_label 与子3 分层提案不一致（如子3 提案 must 而陈述标 nice，或反之）判 block；type_label 与子3 提案一致、且陈述集与子3 目标集逐项一致（子3 目标集几项即几条陈述）即传导正确。\n"
                    "二、传导断裂·边界超出：陈述抹掉子3 已证实边界的口径限定、改成更强断言（如子3 基线限 default 管线+数据截至某快照日而陈述称全部管线/实时）判 block；陈述以子3 边界内口径表述、或 text 概括而限定词写在 boundary 字段，都是传导正确的合法形态——不得索取比子3 更强的断言，不得要求 text 逐字复刻子3 措辞，不得要求 boundary 含具体数值证据指针。\n"
                    "三、复合未拆：单句用「和/以及/同时/并」连接多个独立目标（各自可单独成为一个目标）判 block；同一目标的状语、约束枚举、修饰成分（「基于 X 的因子规模，决定 Y」的状语结构、「数据截至…的」「IC 均值…的」）不算并列——无上述连接词、或连接的成分服务同一个目标时，不得判并列。\n"
                    "四、方案动作残留：text 的主语/动作是实现动作或实现机制名词（「开发脚本」「实现 X」「做一个 X」、模板文件名/类名/函数名/file:line）判 block；数据口径限定词（管线名如「default 管线」、指标口径如「IC 均值」、数据日期、阈值）是已证实边界的合法约束成分、不算方案名词，不得因此判；boundary 字段含实现指针/file:line 是判据规定的去处，不得因 boundary 有实现细节而判 text 违规。\n"
                    "【合法正例】受益者（「当前提问者」「用户」）作主语合规——主语 outcome-level 指用户可见的状态/数字/信号，受益者即用户可见主体；「当前提问者能够基于 default 管线中数据截至 2026-07-24 且 IC 均值严格大于 0 的因子规模，决定因子筛选门槛」单句合规；子3 目标集只 1 个目标时陈述集 1 条即逐项一致——价值链/基线测量/不可量化项是子3 论证材料非目标，不要求拆出对应陈述；nice=无（空集）已在子3 留痕合规，不要求空 nice 陈述；artifact 含子3 记录是生产常态（逐项一致的对照基准），artifact 即全部判材——不得以「跨子步串号/字段混入/看不到 evidence 原文/无法核验」为由判。方框以外一律不判。\n"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例（指模式不指实例位置）。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem / AskUserQuestion",
                short="读回确认",
                interactive=True,
                # 带证据读回（同构 ProblemContext 子7）：只给结论不给依据地「通知」用户
                # = 不信任甚至 backfire effect；本步是本子阶段唯一规范裁决点
                # （must/nice 分层真值归用户，四桶分工）。
                purpose=(
                    "带证据的读回确认：材料 = 运行 `python3 ~/.dl-workflow/dl_flow_engine.py render-readback` 机械装配逐字呈现（本节点归一化+假设/不确定性 traces，禁手抄；Bash 输出即呈现）。呈现内容 = 归一化目标陈述+追溯链+价值论证+"
                    "must/nice 提案+不确定性（「不可量化」项显式暴露）；"
                    "用户裁决 must/nice 分层（本子阶段唯一规范裁决点）；"
                    "用户对各目标的认/否/调层记入 trace；"
                    "多目标时用户圈定本实例处理范围，其余落 evidence + understand.md"
                    "（供后续 dl 实例接续，不丢弃）；"
                    f"{_INTERACTIVE_CHUNKING_RULE}。{_USER_DECISION_RECORD_RULE}"
                ),
                input="step4.statements",
                record=True,
                selfcheck=(
                    "呈现了陈述+追溯链+价值论证+分层提案+不确定性吗？"
                    "「不可量化」项显式暴露了吗？用户对分层与各目标的裁决记入 trace 了吗？"
                    "多目标时用户圈定本实例范围、其余落 evidence+understand.md 了吗？"
                ),
                # v2.45 交接架构正确性前提：用户裁决必入 trace（gate=None 无 judge，
                # 机械校验是唯一防线）。
                mech_checks=("user_decision_recorded",),
                gate=None,  # 交互步，gate 不跑 judge（trace 存在即过）
            ),
        ),
        minor_key="GoalsAndValue",
        # 无 hold_for_gate（用户决议 2026-07-28）：围栏只设在 plan 完成，
        # 末步过门控自动续轮进 understand:3（同 understand:1 边界语义）。
        # u2-residual-cost 置位（逐字段核对见 design §3）：本节点五步零源码
        # 交互（规范性命题——目标/价值真值源是用户），材料全在交接包+node-rules，
        # 不依赖项目 CLAUDE.md/auto-memory；逐步工具需求：#1 prep=Read/Bash、
        # #2 矩阵推理=Bash(append-trace)、#3 基线测量=Bash/Read、
        # #4 归一化=Skill(define-problem)+Edit 骨架+Bash 落库——Write 零合法用途
        # （载荷 --scaffold+Edit），AskUserQuestion 由 prep --disallowedTools 封。
        segment_strip_project_context=True,
        segment_tools=("Bash", "Read", "Edit", "Skill"),
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
                interactive=True,
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
                # v2.91（designs/u3-sub1-gate-framing-design.md）：从严 framing 反转为
                # 默认-PASS + 方框真值判据。基线 clean 0/6 全误伤（659 字=短 gate thrash
                # 第七实证）——7 类误判 5 类是 judge 发明要件（q/a 一问一类映射/六类全覆盖/
                # 归类归属之争/出处可核验/must 集完整性无前序对照）、1 类判据措辞歧义
                # （用户侧三项被读成逐项必答）、1 类判据适用面错位（KAOS 反事实假想候选被
                # 当「无出处推断」判）。两个本节点独有结构段：【本步命题性质】（候选=假想句，
                # 真伪归子2 三态）+【判材边界】（must 集跨节点不在载荷内，judge 判不了完整性）。
                # 反转后 clean 6/6、vio1/3/4/5 全 6/6、vio2 5/6（注意力方差，5 轮逐字引条款三）。
                gate=(
                    "默认 pass——仅当以下明列的 block 条件成立才判 block（每条附合法形态，合法形态在场不得判）。"
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=ScopeAndConstraints 且 sub_step==1 的记录；"
                    f"形式要件：{_S3_STEP1_FORM_REQUIREMENTS}。"
                    "【本步命题性质】约束候选本身是「若 X 则目标失败」式反事实假想"
                    "（KAOS 障碍分析的产物）——候选的真伪验证是子2 的活（三态定真伪："
                    "已验证/假设/证伪）。候选写成假想句、未经工具验证、无事实出处，均不判 block；"
                    "「无出处推断」这一条只约束结论句（结论段对已完成工作的陈述），不约束候选句。"
                    "【判材边界】must 目标集在 GoalsAndValue 子4 跨节点，不在本载荷内——"
                    "不得以「无法确认 must 目标集完整」「未与前序 must 集对照」「自行界定目标数」"
                    "为由 block；trace 内自述的目标集与逐目标否定提问自洽即合规。答案内声明"
                    "「Read CLAUDE.md 原文『…』」「用户原话：'…'」「（AskUserQuestion 选中）'…'」"
                    "「会话事实：…」即合法出处形态——judge 看不到会话原文与文件内容，不得要求出处"
                    "「可核验」「贴行号」「更完整引用」「与前序印证」，不得要求 evidence 体现 "
                    "AskUserQuestion 调用轨迹。"
                    "方框判据（仅以下成立判 block）："
                    "一、类型覆盖不足：约束候选覆盖的类型 <3 类判 block——达到 ≥3 类即合规，"
                    "不得因未覆盖其余可选类（如缺「外部依赖」）而 block；类型按候选内容可归即算"
                    "覆盖，不要求逐条打分类标签，归类归属之争（同一条该归「项目硬规则」还是"
                    "「代码库结构」）不作 block 依据。本条在结论以②申报时不适用。"
                    "二、候选空泛：候选不绑定任何具体对象（「数据可能不准」「环境可能有依赖问题」"
                    "「代码结构方面的问题」式无对象断言）判 block——候选点名具体对象（规则条号/"
                    "字段名/文件或模块名/工具或依赖名/资源量）即非空泛，一句话候选即够。"
                    "三、否定提问形式主义：多个 must 目标共用同一句套话否定提问、未按各目标内容"
                    "具体化（如两目标都只写「什么会使它失败？」）判 block——单个 must 目标只写"
                    "一句否定提问是合规形态（无可比对象即无套话可言）；提问句复用「什么会使它失败」"
                    "这一 KAOS 句式但绑定了各自目标内容的，合规。"
                    "四、②偷懒：结论以②「无实质约束」申报，但缺任一 must 目标的否定提问留痕"
                    "（直接写「没什么会拦住它」「纯读取型任务不存在约束」而无提问过程）判 block"
                    "——②在每 must 目标均有否定提问留痕后仍无候选时是合法结论，不得以"
                    "「缺约束候选」本身 block ②。"
                    "五、结论无出处推断：结论段出现无出处的推断句且未标「推测」（如「这意味着…」"
                    "「隐含…因此…」式从事实推出的新断言直接写进结论）判 block——推断标「推测」"
                    "另列即合规；结论末尾「逐句出处：…」式出处汇总与自检总括是合法元声明，"
                    "不作「无出处」判。"
                    "【关键】①②互不适用：不得以「缺②的原话佐证」block ① 的载荷，不得以"
                    "「缺约束候选/类型覆盖不足」block ② 的载荷。用户侧三项（deadline/人力/权限）"
                    "是缺口检查清单非逐项必答——上下文已有原话或补问已覆盖的项即达标，"
                    "本任务不涉及的项无需强凑，不得以「未覆盖人力」式单项缺失 block。"
                    "q/a 按序对齐 = q 与 a 等长且顺序对应，不要求「一条 q 对应一个约束类型」的"
                    "映射关系。"
                    "【合法正例】单 must 目标 G1 一句具体化否定提问 + 4 类候选（项目硬规则/"
                    "代码库结构/数据契约/环境工具链）合规；候选「CLAUDE.md H7 规定路径只能 "
                    "from paths import——若自行拼路径则报告定位静默失效」合规（假想句 + 具体规则"
                    "条号）；候选「若最新报告 data_date 早于 2026-07-24 则不存在满足口径的报告」"
                    "合规（反事实假想，真伪留子2）；用户侧只补问到时间与权限、未提人力合规；"
                    "结论「推测（另列，不纳入约束集）：报告目录下可能存在历史归档干扰定位——"
                    "未经工具验证，留子2 定真伪」合规。方框以外一律不判。"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例"
                    "（指模式不指实例位置）。"
                ),
            ),
            Step(
                kind="tool",
                ref="Bash(本地验证) / codegraph(结构约束) / Read",
                short="约束验证标注",
                # ProblemContext 子4+子5 的压缩版：约束是项目内部事实（非外部五层源），
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
                mech_checks=("constraint_verification_tool_trace",),
                selfcheck=(
                    "子1 每条候选都做了三态处置吗（已验证/假设/证伪，无遗漏）？"
                    "已验证项都附工具留痕出处了吗？假设项都含置信度+错误时的影响吗？"
                    "有「未验证」直接混进约束集的（假设未标注）吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、minor_stage=ScopeAndConstraints 且 sub_step==2 的记录；形式要件：子1 候选逐条三态处置（已验证/假设/证伪，无遗漏）；已验证项附工具留痕出处；假设项含置信度+错误时影响。\n"
                    "默认 pass--仅当以下成立才判 block（每条附合法形态，合法形态在场不得判）：\n"
                    "一、编造/训练记忆冒充：已验证项的工具留痕（Read 规范原文/Bash 实测/codegraph/AskUserQuestion 原话/文件路径 等工具动词在场与否）已由 append-trace 机械校验--无工具留痕的已验证项（裸结论如「口径为 ic_mean」、或「通常/一般来说」式训练记忆断言）已被当场拒、不会到你这里，你不得以「无工具出处/留痕不可核验/缺 file:line/缺完整 stdout/缺 option ID/训练记忆冒充」为由 block。合法留痕形态=Read 规范文档（CLAUDE.md/PROJECT.md/MODULE.md）§X 原文引用即合规（硬规则类约束的合法验证源=Read 规范文档原文，不要求 Bash 实测）；Bash 实测 `命令` 输出值即合规（不要求完整 stdout/完整命令文本）；AskUserQuestion 选中原话『…』即合规（不要求工具调用记录/option ID/file:line，不要求工具匹配本步 fence_allow）；子2 处置子1 候选、引用子1 已取证来源即合规（不要求本步重跑/本步新工具留痕）。只判--留痕在场但与声明来源明显矛盾判 block。\n"
                    "二、未验证直接进约束集（假设未标注）：未经核实的候选以约束身份进入约束集（「纳入约束集/作为约束/列入约束」式行为规定）却未标「假设+置信度+错误时影响」、亦未附证据证伪判 block。合法形态=未低成本验证的候选标「假设·置信度·错误时影响」并留子5 用户裁决即合规；证伪项附证据剔除即合规；不要求三态都出现（每个候选各归一态、无遗漏即合规；无假设/无证伪候选时该态不出现=正常）。\n"
                    "【关键】不得以「留痕不可核验/缺 file:line/缺完整 stdout/缺 option ID」block 已附 Read 原文/Bash 实测/AskUserQuestion 原话的已验证项；不得以「子2 须新验证/工具不匹配子2 fence」block 引用子1 取证来源的已验证项；不得以「缺假设项/缺证伪项」block 无该态候选的 trace。子1 候选清单（step1.constraint_candidates）的存在与组成非判对象，judge 只判本步三态处置质量。\n"
                    "【合法正例】Read CLAUDE.md §5「H7：路径只能 from paths import」原文引用合规；Bash 实测 `python3 -c import pyarrow` 输出 True 合规；AskUserQuestion 选中原话『没有时间压力』合规；子1 推测项标「假设·置信度:中·错误时影响:…」留子5 用户裁决合规。方框以外一律不判。\n"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例（指模式不指实例位置）。"
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
                    "（改动面证据 = **子2 已验证留痕逐字引用**（标注来源「子2/Cx」"
                    "条目号）——子2 已 callers/grep/Read 过的符号与文件**本步零"
                    "重查**；仅当某 in 侧条目缺实现指针且子2 留痕无出处时，才对该"
                    "条目单点补一次查询（codegraph impact，CLI 路径见项目 "
                    "CLAUDE.md §3 执行映射，可定向 Read）——引用子2 是默认形态，"
                    "新查询是逐项例外、不是默认动作，禁为「本步留痕」重跑前序已"
                    "完成的相同查询），out-of-scope = "
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
                    "改动面证据默认全是子2 留痕逐字引用（标注来源）吗？新跑查询"
                    "是零或逐条目例外（缺指针才单点补一次）吗——没把「验证缺口」"
                    "当默认动作吧？"
                    "全程只提案、没替用户拍板吧？"
                ),
                # u3-sub3-cost（designs/u3-sub3-cost-optimization-design.md）：
                # 消费型步逐步剥离置位（Step 级字段首例）——规则内容（H15/H1/
                # H1.1/H9 原文）经子2 trace 逐字在场，CLAUDE.md 自动加载对本步
                # 是死重；B1 反优化结论限子1/子2（候选生成/验证须规则原文
                # 在场），不覆盖本步。
                segment_strip_project_context=True,
                # 同设计 L3：材料边界——输入契约（子2 验证留痕全文 + GAV 裁决 +
                # PC 结论）100% 在交接包内（ab 轮零 evidence 读取完成交付实证；
                # ab2 轮通用「按需 Read」尾行诱发 15 次 evidence/state 元探查，
                # #16 反指机制 u:3#3 复现）。缺口取证走 purpose 内指针定点补。
                pack_self_contained=True,
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、minor_stage=ScopeAndConstraints 且 sub_step==3 的记录；形式要件：in/out 双侧清单；每项携带双字段（具体实现指针+outcome 层标签）；双向矩阵逐项（backward 每个 in 项回溯目标+forward 每个目标有范围覆盖或显式搁置+理由——prose 逐项点名即合规，不要求表格/命中-未命中矩阵/结构化清单形式）；孤儿项显式处置；约束回写已记录（哪条约束迫使范围怎么缩有对应陈述即合规，不要求回写位置/字段级明细）。\n"
                    "默认 pass——仅当以下成立才判 block（每条附合法形态，合法形态在场不得判）：\n"
                    "一、out-of-scope 空清单：out 侧无任何显式排除项=无真实取舍判 block；out 侧 ≥1 项「看似该做但不做+理由」即合规，排除理由简略不判。\n"
                    "二、矩阵放水：明显无关联的目标-范围硬连判 block（与目标零概念重叠的范围项挂承接——如 CI 配置/无关工具链挂「支撑目标决策」，自称承接不免判）；范围项与目标有承接逻辑（数量来源/基线核对/口径验证等关系类别）即非放水——承接强弱、是否「直接」不审查，不要求展开机制描述或更紧的挂接依据。\n"
                    "三、outcome 标签空泛：「页面相关」「功能相关」「数据相关」式无对象无状态标签判 block；以下判例出现即不得判（同类同理）：「数据截至日期与 14/72(19.44%) 规模可见」「报告展示页面保持现状」「因子值产出链路不变」——具体对象+可观察状态/数字即非空泛，不要求标注 outcome 类型/层级（用户层/系统层/数据层），不要求正/负或目标/非目标双向对照，不要求指向用户价值/验收口径。\n"
                    "四、替用户拍板：以「范围已确定/按此执行/无需用户再裁决」式定案语气收口判 block；「以上为提案，in/out 边界与假设接受待子5 用户裁决」式提案语义在场即合规，措辞不必逐字。本方框只约束 in/out 范围边界的拍板——约束回写与假设处置的记录性陈述（「C1.3 迫使上界=1，已记录」「列入假设清单待子5 裁决」）是合法处置记录，不算定案语气。\n"
                    "五、汇总声明无逐项矩阵：双向追溯仅以「全部对齐/所有范围项均已对齐/每个目标都有范围承接」式泛指呈现、不点名任何具体目标×范围项对应判 block；点名了具体目标×范围项（标识或内容）即非汇总——「G1→in[1]（数量来源复算）+in[2]（规模基线核对）全覆盖」式点名标识+关系即合规。\n"
                    "【合法正例】in 侧含只读核对项（基线快照/规范文档）合法——实现指针不要求必须是待改文件；矩阵 prose 逐项（「in[1]→G1（数量来源）」）即逐项列出，out 项以「排除+理由」呈现即合规、不要求 out 项进矩阵行；「孤儿范围项=无（每项均回溯 G1）」一句即显式处置；改动面证据引用子2 已验证留痕（逐字 file:line/callers 输出 + 来源标注如「子2/C1」）即合规——不要求本步重跑 codegraph impact/重读前序已读文件，仅「in 侧改动面无出处（既无本步留痕也无前序引用）」才可归方框二放水判；前序子1/子2 trace（约束候选与三态处置）是锚点非判对象，其存在与组成不作 block 依据。方框以外一律不判。\n"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例（指模式不指实例位置）。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem",
                short="归一化陈述",
                # claim normalization 职能第三次复用（ProblemContext 子6 /
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
                    "裁决传导，同构 ProblemContext 子6）；"
                    f"④solution-free 复核（范围项含方案名词 = GoalsAndValue 子2 "
                    f"剥离不净残留；{_SOLUTION_FREE_SUBJECT_RULE}；{_SCOPE_VERB_RULE}）。"
                    "放不进一句=未定义完。"
                    '载荷格式：statements 逐项 {"text":单句陈述,"type_label":in/out/'
                    '已验证/假设：<置信度>,"boundary":verdict 边界+实现指针}——text 只许 '
                    "outcome-level（实现侧名词/file:line 只能进 boundary，机械扫描命中即拒）；"
                    "子3 条目编号（in[..]/out[..]/Cx.x）逐项传导，机械核对缺传即拒。"
                    "载荷格式与编号传导的唯一真源 = --scaffold 骨架 + append-trace "
                    "报错文案（四桶分工：格式归脚本）——禁读引擎/测试源码反推校验"
                    "实现；被拒按报错文案逐字修即可。"
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
                    "格式照 scaffold 骨架填了吗——没去翻引擎/测试源码反推校验"
                    "实现吧（被拒按报错文案修）？"
                ),
                # u3-sub4-cost（designs/u3-sub4-cost-optimization-design.md）：
                # 消费型装配步置位双字段（u:3#3 同型第二例）——规则内容
                # （_SOLUTION_FREE_SUBJECT_RULE/_SCOPE_VERB_RULE）经 purpose 常量
                # 逐字在场、方案名词扫描在 append-trace 脚本侧，CLAUDE.md/auto-memory
                # 对本步是死重；输入契约（子3 范围与约束集全文）在本节点留痕节
                # 逐字在场，包尾「按需 Read」通用邀请是反指（基线 6 次 evidence
                # 元探查+1 次 node-rules 全量重读实证）。
                segment_strip_project_context=True,
                pack_self_contained=True,
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、minor_stage=ScopeAndConstraints 且 sub_step==4 的记录。形式要件：子3 范围与约束集每项各 ≤1 句且自包含（原子+去上下文=对象+动作+约束，中文省略主语合法）；陈述携带类型标签（已验证/假设+置信度/in/out）与边界。（statements 三字段非空（text/type_label/boundary）已由 append-trace 逐项 JSON 机械校验通过——你不得以「缺 type_label/缺 boundary/字段不齐/未声明 evidence 路径」为由 block，这些字段在场是机械已知事实。）\n"
                    "默认 pass——仅当以下成立才判 block（每条附合法形态，合法形态在场不得判）：\n"
                    "一、传导断裂·类型标注不一致：type_label 与子3 条目编号（in[..]/out[..]/Cx.x）逐项对应不一致（如子3 提案 in 而陈述标 out、已验证约束标成假设，或反之）判 block；type_label 与陈述内容方向矛盾——in-scope 项内容表述纳入（可查看/可访问/纳入范围）而标 out、或 out-of-scope 项内容表述排除（不纳入/不做）而标 in 判 block；type_label 与 boundary 内条目编号前缀矛盾（boundary 含 in[1] 而 type_label 标 out）判 block。type_label 与子3 对应一致、内容方向与标注自洽即传导正确——in 项用「用户可查看/可访问/可基于 X 决定 Y」式 outcome 描述合法，不得对 in/out 项表述风格提额外要求。in/out 范围项的边界口径限定（default 管线、数据截至某快照日等已验证事实）是范围项已证实边界的一部分、不是独立约束条目——in 项标 in、out 项标 out 即类型标注正确，不得因边界含已验证口径改标「已验证」，不得要求口径限定单独成条陈述。假设条目须含置信度（「假设：中」）；in/out/已验证 无需置信度，不得索取。\n"
                    "二、传导断裂·边界超出：陈述抹掉子3 已证实边界的口径限定、改成更强断言（如子3 in 限 default 管线+数据截至某快照日而陈述称全部管线/实时）判 block；陈述以子3 边界内口径表述、或 text 概括而限定词写在 boundary 字段，都是传导正确的合法形态——不得索取比子3 更强的断言，不得要求 text 逐字复刻子3 措辞，不得要求 boundary 含具体数值证据指针。\n"
                    "三、复合未拆：单句用「和/以及/同时/并」连接多个独立条目（各自可单独成为一项）判 block；同一范围项/约束的状语、约束枚举、修饰成分（「基于 X 的规模，决定 Y」的状语结构、「数据截至…的」「IC 均值…的」）、同一项的内容列举（「数量与分布」）不算并列——无上述连接词、或连接的成分服务同一个条目时，不得判并列。约束条目（已验证/假设）独立成条陈述合法——约束内容与 in/out 项边界限定重叠（约束回写关系）不算重复条目、不算复合，不得判。\n"
                    "四、方案动作残留：text 的主语/动作是实现动作或实现机制名词（「开发脚本」「实现 X」「做一个 X」、模板文件名/类名/函数名/file:line）判 block；动词按指向判、不按词形判——in/out 范围陈述的构成性谓语「允许/禁止改动」、指向用户可见状态或范围赋予（展示/计算/覆盖/读取）合法，指向代码实现动作（改哪个文件/函数/模板/CSS 类）才违规；数据口径限定词（管线名如「default 管线」、指标口径如「IC 均值」、数据日期、阈值）是已证实边界的合法约束成分、不算方案名词，不得因此判；范围主体名词（「因子策略回测系统」等范围命题的对象）不是实现机制名词，不得判；boundary 字段内容不在本判据范围内——boundary 含实现指针/file:line/类名/方案名词是判据规定的去处，不得因 boundary 有任何实现细节而判 block。\n"
                    "【合法正例】「default 管线」「数据截至 2026-07-24」等口径限定词入 text 合规（已证实边界的一部分），「用户能够查看 default 管线中数据截至 2026-07-24 的正 IC 因子数量」标 in、快照口径写边界，合规——边界口径限定不构成独立约束条目，不得要求其单独成条或改标已验证；「允许改动 XX 模块、禁止改动 YY」=范围命题构成性谓语合法（不判实现动词）；省略主语的动宾短语（「统计正 IC 因子数量」）合规——不得判「缺主语/非陈述式/祈使短语」；子3 条目几项即几条陈述——逐项一致的核对=子3 条目编号（in[..]/out[..]/Cx.x）覆盖，双向追溯矩阵/约束回写/出处说明是子3 论证叙述非条目、编号出现在叙述里不增加条目数，不得按子3 trace 的 q/a 条数核对；已验证约束（如 C1.1 快照）独立成条陈述、与 in 项边界限定重叠是约束回写正常形态、不算重复；子3 范围与约束集仅含 in/out 范围项、约束已折叠进范围项边界口径时，陈述集只含 in/out 范围项即逐项一致——不得要求约束陈述；约束集为空的「无实质约束」已在子1/子3 留痕合规，不要求空约束陈述；artifact 含子3 记录是生产常态（逐项一致的对照基准），artifact 即全部判材——不得以「跨子步串号/字段混入/看不到 evidence 原文/无法核验」为由判。方框以外一律不判。\n"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例（指模式不指实例位置）。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem / AskUserQuestion",
                short="读回确认",
                interactive=True,
                # 带证据读回（同构 ProblemContext 子7 / GoalsAndValue 子5）。
                # 本子阶段两个规范裁决点都在此：范围边界拍板 + 假设接受（风险承担）。
                purpose=(
                    "带证据的读回确认：材料 = 运行 `python3 ~/.dl-workflow/dl_flow_engine.py render-readback` 机械装配逐字呈现（本节点归一化+假设/不确定性 traces，禁手抄；Bash 输出即呈现）。呈现内容 = 归一化范围双侧清单+约束集"
                    "（已验证附出处）+假设清单（置信度+影响）+不确定性；"
                    "用户裁决两件事：①范围边界（in/out 拍板——本子阶段第一规范"
                    "裁决点）；②假设的接受（风险承担是规范裁决，模型无权替用户"
                    "接受——第二规范裁决点）；用户认/否/调整记入 trace；"
                    "多约束/假设时用户圈定本实例处理项，其余落 evidence + "
                    "understand.md（供后续 dl 实例接续，不丢弃）；"
                    f"{_INTERACTIVE_CHUNKING_RULE}。{_USER_DECISION_RECORD_RULE}"
                ),
                input="step4.statements",
                record=True,
                selfcheck=(
                    "呈现了范围双侧清单+约束集（已验证附出处）+假设清单"
                    "（置信度+影响）+不确定性吗？用户对范围边界与假设接受的"
                    "两项裁决都记入 trace 了吗？多约束/假设时用户圈定本实例"
                    "范围、其余落 evidence+understand.md 了吗？"
                ),
                # v2.45 交接架构正确性前提：用户裁决必入 trace（gate=None 无 judge，
                # 机械校验是唯一防线）。
                mech_checks=("user_decision_recorded",),
                gate=None,  # 交互步，gate 不跑 judge（trace 存在即过）
            ),
        ),
        minor_key="ScopeAndConstraints",
        # 无 hold_for_gate（用户决议 2026-07-28）：围栏只设在 plan 完成，
        # 末步过门控自动续轮进 understand:4（同 understand:1 边界语义）。
        # u3-sub1-cost：段工具白名单置位（#23 泛化第三例，含 TUI 交互段管线）。
        # 逐字段核对：子2 本地验证=Bash+Read（codegraph 走 Bash CLI）；子3 推理
        # 型；子4 kind=skill define-problem→Skill；落库=scaffold+Edit 零合法
        # Write；子1 交互段三件套由 run_tui_step 自动附带；无 Agent 需求
        # （子2 本地单层源不派子代理，对照 u:1 子4 取证才含 Agent）。
        # **env 剥离（CLAUDE_MDS）不置位**（u3_sub1_ab 实证 2026-08-18）：
        # 本节点约束分类把「项目硬规则」列为一等约束源，自动加载的 CLAUDE.md
        # 是任务功能材料非死重——剥掉后模型为点名规则条号重读规范文档+代码
        # 文件（+40k 上下文驻留），冷重付 87k 一次 + 逐调 cr 多背 35k，
        # 总账反超标量（#23 置位前置核对补：任务内容本身引用自动加载文档的
        # 节点禁剥 env）。
        segment_tools=("Bash", "Read", "Edit", "Skill"),
    ),
    "understand:4": Node(
        label="定义成功标准和验收方式",
        phase="understand",
        sub=4,
        skill=None,
        artifact="understand.md",  # 末子阶段写产物
        # ARTIFACT_CONTAINS（2026-08-02 升，artifact-handoff-hardening-design）：
        # 四节全查——review:0 rubric「对照 understand.md」是消费契约锚点，
        # 缺节静默溜进 plan 的灾难在离起点最远的地方爆。
        gate_mech=GateMech.ARTIFACT_CONTAINS,
        artifact_contains=ARTIFACT_SECTIONS["understand.md"],
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
                interactive=True,
                purpose=(
                    f"成功标准引出：{_S4_STEP1_FORM_REQUIREMENTS}。"
                    "solutioneering 剥离：标准候选含方案名词/实现动词"
                    "（「做一个X」「实现Y」）→ 剥到 outcome 度量"
                    f"（纪律同 GoalsAndValue 子2；{_SOLUTION_FREE_SUBJECT_RULE}）。"
                    "消费契约锚点：成功标准是 review 阶段 gate 判定 "
                    "solved/partial/not 的依据——写每条候选时想象 review 时拿什么判它。"
                    # u4-sub1-cost（designs/u4-sub1-cost-optimization-design.md
                    # L4）：复用钉死（#25 收紧形态——默认零新查询+枚举例外，
                    # 非「缺口才新跑」开放谓词）。基线实证：模型派发 2 个
                    # Explore 子代理为子3 预取 file:line 证据（步骤越界 +
                    # 前序已沉淀锚点的重复取证），Agent 已出本节点 tools
                    # 白名单（机制堵入口），本条款防 Bash 迂回（双侧钉死）。
                    "材料边界（复用钉死）：must 目标集/范围约束/用户原话全部在"
                    "交接包（前序节点结论摘要节）与 prep 载荷 sources 字段——"
                    "逐字直接引用即出处；本步零新取证：不派发子代理、不跑 "
                    "codegraph/grep、不 Read evidence 全量翻找（验收手段的 "
                    "file:line 取证归子3——为后续步预取材料 = 越界，"
                    "「先查清楚再补问」不是本步职责）。"
                ),
                input="GoalsAndValue.step4.statements + ScopeAndConstraints.step4.statements",
                record=True,
                # u4-sub1-cost L2/L3（designs/u4-sub1-cost-optimization-design.md）：
                # Step 级 strip（u:3#3/#4 后第三例——交付物正文不引用自动加载
                # 文档，判材边界见 gate 结构段）+ pack_self_contained（第四例——
                # 声明输入 = 前序两节点 step4 statements，生产真包冒烟实证全文
                # 在包；交互步置位首例，条款分支已覆盖 interactive）。
                segment_strip_project_context=True,
                pack_self_contained=True,
                selfcheck=(
                    "每个 must 目标都做了验收视角提问「怎么知道它达成了」吗？"
                    "双向追溯逐项列出了吗（每目标 ≥1 候选或定性+理由；"
                    "每候选回溯 ≥1 目标）？"
                    f"含方案名词的候选剥到 outcome 了吗（{_SOLUTION_FREE_SUBJECT_RULE}）？"
                    "每条 a 是用户原话/会话事实，还是我推断补全的"
                    "（推断只能标「推测」另列）？结论选了①还是②、每句都有出处吗？"
                    "材料全部引自交接包/prep 载荷 sources 吗"
                    "（零新取证、零子代理、零 evidence 全量翻找）？"
                ),
                # v2.93 gate framing 反转（§3.5 #28 泛化第十一例，
                # designs/u4-sub1-gate-framing-design.md）：基线 784 字从严版
                # clean 0/6（短 gate thrash 第八实证），6/6 全轮主引
                # 「default 管线=实现侧名词」误伤——_SOLUTION_FREE_SUBJECT_RULE
                # 逐字列「管线名/字段名」为禁用，与 must 目标自带的已确认口径
                # 限定词必然入候选主语直接矛盾（#23 修文本不站队，u:2#4/u:3#4
                # 同族第三次）。改默认-PASS + 5 方框（空泛/放水/②偷懒/
                # solutioneering 重划线/结论无出处推断）+ 两结构段（#30 ㉚：
                # 本步命题性质=候选是提案，可检验化归子2、验收方式归子3、拍板
                # 归子5；判材边界=must 目标集与范围约束**两个** minor_stage
                # 跨节点不可见）+ 双结论守卫。方框四判别线=指向项目源码构件
                # （脚本/类/方法/模板/宏/file:line）才违规，指向用户可见的数字与
                # 口径（管线名/指标口径/数据日期/报告页面/字段值）合法。
                # 落地版三向全 6/6（clean 6/6，vio1-5 各 6/6，判词逐条引对条款）。
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=SuccessCriteria 且 sub_step==1 的记录；"
                    f"形式要件：{_S4_STEP1_FORM_REQUIREMENTS}。\n"
                    "默认 pass--仅当以下成立才判 block（每条附合法形态，合法形态在场不得判）：\n"
                    "一、候选空泛复述：标准候选不绑定任何度量对象（「系统变快」「体验好」「统计更准确」「数据是新的」「口径用得对」式无对象无信号表述）判 block。合法形态=候选点出可读出/可核对的对象（条数、占比百分比、日期字段值、口径名称与比较关系、来源标识的一致性）即非空泛--**度量对象在场即合规，不要求阈值数字/基线数值/可执行命令/测试断言**（阈值提案归子2、验收方法与证据形式归子3、阈值拍板归子5，本步只产候选）；不得以「缺阈值/缺基线/缺量化门限/未落成可执行验证/未给验收脚本」为由 block 已有度量对象的候选。\n"
                    "二、追溯放水：与 must 目标零概念重叠的候选硬挂该目标（如 README 文档结构评分/代码注释覆盖率/页面加载耗时 挂「因子规模决定门槛」类目标，自称承接不免判）判 block；孤儿候选（回溯不到任何目标）既不剔除也不退回补问判 block。合法形态=候选与目标有承接逻辑（提供目标所需数字本体/承接目标的口径限定/承接目标所需最小交付形态）即非放水--承接强弱、是否「直接」「必要输入」不审查，不要求展开机制描述；已当场剔除并写明剔除理由的候选=合法处置（剔除记录在场不得判孤儿）。\n"
                    "三、②偷懒（仅在结论申报②时适用）：申报「目标只能定性验收」却缺任一 must 目标的留痕理由、或理由未说明「为何不可执行验证」（只写「主观判断/主观感受类/没法定量」而不说明为何无法用可执行信号验收）判 block；理由所指目标其代码行为显然可执行验证（有可读出的数字/字段/输出）却标定性判 block。合法形态=逐目标写明「为何不可执行验证」（如 UX 观感/可读性/架构审美类无可执行信号）即合规。\n"
                    "四、solutioneering 残留：候选主语/度量对象是**项目源码构件标识**--脚本文件名（`xxx.py`）/类名/方法名/函数名/模板文件名/CSS 类名/宏名/file:line 判 block。合法形态（在场不得判）=**用户已确认的数据口径限定词与交付载体不是实现侧名词**：管线名（「default 管线」）、指标口径（「IC均值」「IR」）、数据日期（「数据截至2026-07-24」）、比较关系（「严格大于0」）、报告/页面/字段值 等口径与载体表述，是 must 目标自带的已证实边界成分，入候选主语或度量对象**合规**；「数字来源管线标识与 default 的一致性」「数据截至日期字段值」「IC 口径名称与比较关系」式度量对象合规。不得以「含管线名/含『报告』『页面』『字段值』/含数据日期/『交付形态』一词」为由判 solutioneering。判别线=指向项目源码里的某个构件（改哪个文件/类/函数/模板）才违规，指向用户可见的数字与口径不违规。\n"
                    "五、结论无出处推断：结论正文夹带无用户原话/会话事实支撑的推断并据此新增标准或定优先级（「用户既然关心 X，说明他打算 Y，因此标准必须包含 Z」式）、未标「推测」另列判 block。合法形态=推断标「推测」在结论外另列并声明「不纳入候选清单/留子5 裁决」即合规；「出处=用户已确认问题陈述口径」「出处=AskUserQuestion 选中原话『…』」「出处=会话事实（…）」即合法出处形态，不得要求可核验性/贴行号/工具调用记录/option ID/更完整引用。**补问记录形态**：trace 内自述「经 AskUserQuestion 补问『…』，用户原话（AskUserQuestion 选中）：'…'」即补问已执行且出处已给的合法记录形态（本步无独立工具调用记录通道，自述即唯一记录形态）--不得以「未提供该补问及回答出处/补问不可核验/未见问答过程」为由 block，亦不得据此判「用户侧期望缺口未补问」。\n"
                    "【本步命题性质】本步只做候选引出：候选是「验收当天拿什么看」的提案，其可检验化（度量指标+基线+阈值提案）在子2、验收方式与证据形式在子3、阈值与验收方式拍板在子5。不得以「候选未量化/无基线/无阈值/无验收方法/无证据形式/未说明怎么测」为由 block；不得代子2/子3/子5 的判据在本步执行。\n"
                    "【判材边界】must 目标集在 GoalsAndValue.step4、范围约束在 ScopeAndConstraints.step4--**两者均跨 minor_stage、结构性不在本载荷内**（read_evidence_for_step 按 minor_stage=SuccessCriteria 过滤）。不得以「无法确认 must 目标集完整/未与前序陈述对照/模型自行界定目标数/未见范围约束原文」为由 block；trace 内自述的目标集与逐目标提问自洽即合规。补问缺口的**选题**不作 block 依据：已就用户侧期望补问 ≥1 项（或引上下文已有原话）即达标，不得以「更该问的是 X 而没问」「该问分组分布却没问」式应问未问 block。\n"
                    "【双结论守卫】①与②互不适用：不得以「缺②的定性理由」block 申报①的 trace；不得以「候选清单为空」block 申报②的 trace（②本就无候选，方框一/二/四对②不适用）。\n"
                    "【合法正例】「打开 default 管线最新报告能读出正 IC 因子条数与占比两个数字」=口径限定词+可读出对象，合规（不判管线名）；「同一报告页面能读出数据截至日期，验收时确认等于 2026-07-24」合规（不判「报告页面」「字段值」）；「验收不要求图表呈现，数字与占比可读出即算达成」合规（「交付形态」不是实现名词）；「backward：SC1.1→G1（提供目标所需数字本体）…forward：G1→SC1.1+SC1.2+…」式 prose 逐项点名=双向追溯逐项列出（不要求表格/矩阵形式）；「孤儿候选=无」一句+已剔除项附理由=显式处置；q/a 按序等长即对齐（不要求一问一候选类映射，不要求每 q 只出一类候选）。方框以外一律不判。\n"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例（指模式不指实例位置）。"
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
                    # u4-sub2-cost（designs/u4-sub2-cost-optimization-design.md
                    # L2）：复用钉死（#25 收紧形态——默认零重查+枚举例外+按条
                    # 配额）。基线实证（u4_sub2_ab A 轮）：12 探索 Bash 中
                    # ~6 重复核验子1 trace 已载 file:line/机制出处（交接包全文
                    # 在场）、~4 验收手段存在性勘察=子3 职责越界（#27 Bash 迂回
                    # 变体）。
                    "材料边界（复用钉死）：子1 候选清单及其所载出处（实测值/"
                    "file:line/机制结论）全部在交接包「本节点各步最新留痕」节"
                    "全文——逐字直接引用即合法出处，零重复核验（候选已附的 "
                    "file:line/机制结论不重查、不重读验证；前序节点摘要节同理）。"
                    "基线 = 现状实测值：候选出处未含现状值时才 Bash 单点测量"
                    "（每条候选最多一次，测目标值即止，禁顺手勘察）；验收手段的"
                    "存在性勘察（测试框架/验证脚本/工具链是否在位）归子3——"
                    "本步零勘察。引用前序实测的形态「复用 <节点>子N 实测：<值>"
                    "（出处逐字）」= 合法工具留痕。"
                ),
                input="step1.criteria_candidates",
                record=True,
                fence_allow=("Bash",),
                # u4-sub2-cost L1（designs/u4-sub2-cost-optimization-design.md）：
                # Step 级 strip（第四例，u:4 内第二例）——交付物=fit criterion
                # 三要素，正文不点名项目硬规则条号（与 u:3#1 反型不同型，与
                # u:4#1 同型：材料经交接包逐字在场）；工具需求 Bash/Read/Edit
                # 全在 Node 白名单内；gate 判材只读 trace 不读项目上下文。
                segment_strip_project_context=True,
                selfcheck=(
                    "每条候选都做了模糊词扫描改写吗？每条有度量指标+基线"
                    "（Bash 留痕出处或「无基线+原因」）+阈值提案吗？"
                    "阈值全程只提案、没替用户拍板吧？"
                    "不可检验的候选走了退回通道（而非硬编指标）吗？"
                    "候选清单与出处逐字引自交接包吗（零重复核验）？"
                    "基线测量每条候选 ≤1 次单点取值吗？"
                    "验收手段存在性勘察留给子3了吗（本步零勘察）？"
                ),
                # v2.95（designs/u4-sub2-gate-framing-design.md）：从严 framing 反转为
                # 默认-PASS + 方框真值判据。基线 clean 0/6 全误伤（可核验完整留痕/数值化
                # metric/扫描过程留痕/evidence 落库声明/假指标误用/阈值区间容差 等发明要件）；
                # 反转+方框二/三 pin 后 clean 6/6、vio2/3/4 全 6/6。基线编造=词形可判子项
                # （工具动词在场与否）下沉 baseline_tool_trace 生产墙 100%（复用 u:2#3 已
                # 注册，零 engine 改动），judge 只判留痕在场后的语义残项（#30 ⑭）。
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、minor_stage=SuccessCriteria 且 sub_step==2 的记录；形式要件：子1 标准候选逐条做 fit criterion 转换（每条有度量指标+基线（或「无基线+原因」标注）+阈值提案）；模糊词扫描留痕；退回项显式标注。\n"
                    "\n"
                    "默认 pass--仅当以下成立才判 block（每条附合法形态，合法形态在场不得判）：\n"
                    "\n"
                    "一、基线编造：基线数字留痕（工具动词在场与否）已由 append-trace 机械校验——无工具留痕的拍脑袋数字已被当场拒、不会到你这里，你不得以「基线留痕缺失/无工具出处」为由 block；只判——留痕在场但数字与声明来源明显矛盾（如声明「Bash实测」default 报告却给不出与报告时间线吻合的数字）判 block；「Bash实测 `命令` 输出值」/Read 原文引用/「无基线+原因」标注=合法留痕形态，不得要求命令转录/原始输出/文件路径片段/可复现性。\n"
                    "\n"
                    "二、假指标：拿报告体量/脚本体量/编译状态等与验收对象无关的指标替代该测的（如 SC2.1「口径可核对」用报告代码行数度量、SC2.2「管线归属可核对」用脚本函数数量度量、SC3.1「交付形态」用编译无报错度量）判 block；度量对象与 outcome 有承接逻辑（数量来源/口径核对/基线验证/字段读取/直接=outcome 本体 等关系类别）即非假指标——「条数+占比可读出」「口径名称+比较关系一致性」直接承接 outcome 即合规，不要求度量指标数值化表达。\n"
                    "\n"
                    "三、替用户拍板阈值：阈值以定案口吻收口（「阈值定为/就这么执行/已确定/无需再问用户」）判 block；「（提案）」字样或「全程只提案不拍板…均为提案形态」式汇总声明任一在场即合规——提案语义不必每条阈值逐句复述「提案，待子5 用户裁决」全文，措辞不必逐字；只要无定案口吻即不得判替用户拍板；不要求阈值含区间/容差/数值范围/双阈值形态。\n"
                    "\n"
                    "四、模糊词残留：改写后仍含 INCOSE 模糊词（some/any/several/many/significant/adequate/efficient/effective/reasonable；中文等价：一些/任何/若干/许多/显著/足够/大致/基本/明显）判 block；逐条扫描声明（「逐条模糊词扫描：…无 INCOSE 模糊词」式）即扫描留痕，不要求扫描过程记录/清单命中检查。\n"
                    "\n"
                    "【关键】不得以「缺原始输出/缺命令完整文本/缺文件路径片段/未声明 evidence 落库/度量指标非数值化/阈值缺区间容差/缺扫描过程记录」block 已附 Bash 实测/Read 原文/逐条扫描声明/提案语义的 trace；不得以「缺基线」block 已标「无基线+原因」的标准；子1 候选清单（step1.criteria_candidates）的存在与组成非判对象，judge 只判本步 fit criterion 转换质量。\n"
                    "\n"
                    "【合法正例】「Bash实测 `python3 scripts/generate_factor_summary_report.py --read default` 输出条数=14、占比=19.44%」合规；「无基线+原因：…」合规；「阈值提案=条数≥10 且占比≥15%（提案，待子5 用户裁决）」与「…均为提案形态，附『提案，待子5 用户裁决』」汇总声明均合规；「逐条模糊词扫描：SC1.1 原…无 some/any/… 模糊词」合规；SC3.1「条数+占比两数字可读出」非假指标合规。方框以外一律不判。\n"
                    "\n"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例（指模式不指实例位置）。\n"
                ),
                mech_checks=("baseline_tool_trace",),
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
                    # u4-sub3-cost（designs/u4-sub3-cost-optimization-design.md
                    # L3）：复用钉死（#25 收紧形态——默认零重验+枚举例外+按条
                    # 配额）。基线实证（u4_sub2_ab B 轮 seg#4）：13 探索 Bash
                    # 中 ~8-10 纯税/半税=重复验证包内已证存在性（落盘文件=
                    # 子1/子2 实测已证、模板=u:1#6 file:line 已证、页面=用户
                    # 自述一手证据）+超出存在性粒度的内部结构掘进。
                    "材料边界（复用钉死）：前序留痕所载出处（实测命令/落盘"
                    "文件/file:line/机制结论）全部在交接包「本节点各步最新"
                    "留痕」节与前序节点摘要节全文——手段存在性出处逐字直接"
                    "引用即合法（「复用 <节点>子N 留痕：<命令/路径/file:line>"
                    "（出处逐字）」形态），零重跑重验（前序已跑通的命令不重跑、"
                    "已读过的文件不重读、已核的 file:line 不重修）；用户问题"
                    "陈述自述可见/可读的页面·数字·报告 = 存在性一手证据，"
                    "零重验。枚举例外（逐条可判定的二值条件）：某条标准的"
                    "验收手段在前序留痕与用户自述中从未出现（命令/路径/工具名"
                    "零提及）→ 该手段单点存在性验证一次（每条标准最多一次，"
                    "验存在即止，禁顺手掘进内部结构）。零 evidence 全量翻找"
                    "（材料已在交接包）。"
                ),
                input="step2.testable_criteria",
                record=True,
                fence_allow=("Bash",),
                # u4-sub3-cost L1（同设计）：Step 级 strip（第五例，u:4 内第
                # 三例）——交付物=四法选择+三态处置+时机+证据形式，正文不点名
                # 项目硬规则条号（与 u:4#1/#2 同型：材料经交接包逐字在场）；
                # 工具需求 Bash/Read/Edit 全在 Node 白名单内；gate 判材只读
                # trace 不读项目上下文。
                segment_strip_project_context=True,
                selfcheck=(
                    "每条标准有四法之一+选择理由吗？可行性三态逐条处置了吗"
                    "（存在附出处/待建标注/剔除附理由）？时机标注了吗"
                    "（triggered/continuous；事后验证的标了风险+代理指标关系）？"
                    "证据形式锚定到 review 判定可消费的形态了吗？"
                    "存在性出处逐字引自交接包/用户自述吗（零重跑重验）？"
                    "前序未出现的手段每条标准 ≤1 次单点验证、验存在即止吗？"
                    "零 evidence 全量翻找吗？"
                ),
                gate=(
                    "默认 pass——仅当以下明列的 block 条件成立才判 block（每条附合法形态，合法形态在场不得判）。evidence/<name>.jsonl 含 k"
                    "ind=skill-trace、minor_stage=SuccessCriteria 且 sub_step==3 的记录；形式要件：对每条可检验标准给出四法之"
                    "一（test/analysis/inspection/demonstration）+选择理由；可行性三态处置（存在附出处/待建标注/剔除附理由）；时机标注（tr"
                    "iggered/continuous）；证据形式锚定。【判材边界】本载荷含子1/子2/子3 最新 trace 拼合（生产 read_evidence_for_s"
                    "tep 同形），子1 候选清单与子2 三要素是组成事实不是本步判材——本步只判子3 的验收方式设计，不得以「与子1/子2 逐条对照不上」block；GoalsA"
                    "ndValue/ScopeAndConstraints 跨节点不在载荷内，不得以「无法与前序目标或约束对照」block。工具出处=答案内引用具体命令（含命令名与"
                    "参数）或具体文件路径/file:line 级定位即算出处——judge 看不到工具输出原文，不得要求粘贴命令输出全文、不得要求「可核验」「实际执行留痕」式更强出"
                    "处。方框判据（仅以下成立判 block）：一、手段声称存在无工具出处：声称「手段存在」但未附任何命令/路径/文件级定位（「报告生成脚本能跑」「报告里有日期字段」"
                    "式裸断言）判 block——附了具体命令或具体文件路径即算附出处，不得再索取输出全文或行号。二、全选同一方法无真实选择理由：所有标准选同一方法且理由空泛共享（「"
                    "test 最严格客观、统一采用便于管理」式一句套话覆盖全部条目）判 block——载荷中出现 ≥2 种方法本条即不成立；不同条目选同一方法、但各按条目内容给理由"
                    "（如「同为 inspection 但核查对象不同，理由各自独立」）是合法形态，不要求「为何选此法而非彼法」的跨法对比或排除式论证。三、事后验证未标注风险：某条标"
                    "准的验收只能在交付/上线后事后进行（如「交付后观察实际使用一段时间再验收」），却未标注事后验证风险、也未给 review 期代理指标及其与真值的关系，判 blo"
                    "ck——全部标准 triggered/continuous 且声明「无事后验证项」即合规，不要求逐条按事后/事中分类论证。【关键】三态处置=逐条给出处置结果即合"
                    "规，「全部手段存在、无待建/剔除项」式汇总声明合法，不要求逐条打「存在/待建/剔除」三态分类标签；时机标注同理，逐条标注或「全部 triggered」式汇总声明"
                    "均合规。【合法正例】「SC1.1 手段存在——Bash 实测 `python3 scripts/generate_factor_summary_report.p"
                    "y --read default` 可跑通，Read reports/default/summary.md 确认明细表在场」合规（命令+路径级出处）；「SC1."
                    "2→inspection（核查日期字段）、SC2.1→inspection（核查口径字段），核查对象不同、理由各自独立」合规（同法各自理由）；「5 条全部 tr"
                    "iggered——统计任务一次报告产出即验，无事后验证项」合规（汇总时机声明）。方框以外一律不判。judge 判 block 须在 reason 引用判据条款并"
                    "附 1 个正确改写范例（指模式不指实例位置）。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem",
                short="归一化陈述",
                # claim normalization 职能第四次复用（ProblemContext 子6 /
                # GoalsAndValue 子4 / ScopeAndConstraints 子4 同构）。
                purpose=(
                    "归一化陈述：对子3 标准集逐项产出归一化成功标准陈述——"
                    "①原子（单句 ≤1 个独立标准，「和/以及/同时」连接多项 = "
                    "复合未拆净，回子1）；"
                    "②去上下文（脱离本会话可独立理解：主语+动词+约束自包含）；"
                    "③携带完整验收包（指标+基线+阈值提案+验收方法+时机+证据形式）"
                    "与 verdict 边界（部分成立目标的标准只覆盖已证实边界——"
                    "裁决传导，同构 ProblemContext 子6）；"
                    f"④solution-free 复核（含方案名词 = 子1 剥离不净残留；"
                    f"{_SOLUTION_FREE_SUBJECT_RULE}）。"
                    "放不进一句 = 未定义完。"
                    '载荷格式：statements 逐项 {"text":单句陈述,"type_label":验收方法/'
                    '时机,"boundary":verdict 边界}，验收包六字段可作额外字段随项携带——'
                    "text 只许 outcome-level（实现侧名词/file:line 只能进 boundary，"
                    "机械扫描命中即拒）。"
                    # u4-sub4-cost（designs/u4-sub4-cost-optimization-design.md
                    # L3）：格式真源钉死（#26 平移第二例，u:3#4 同文删「编号传导」
                    # ——本步无条目编号传导机械核对）。基线实证（u4_sub3_ab B2）：
                    # 断链后 fresh 段零格式上下文，模型 grep designs/引擎测试源码
                    # 反推【text】/【statements】格式 5+ 调用（格式猎捕）。
                    "载荷格式的唯一真源 = --scaffold 骨架 + append-trace 报错文案"
                    "（四桶分工：格式归脚本）——禁读引擎/测试源码反推校验实现；"
                    "被拒按报错文案逐字修即可。"
                ),
                input="step3.criteria_with_acceptance",
                record=True,
                record_format="statements",
                # u4-sub4-cost L1/L2（同设计）：Step 级 strip（第六例，u:4 内
                # 第四例）+ pack_self_contained（第五例）——消费装配步（禁二次
                # 创作同构 u:3#4）：交付物 text 只许 outcome-level、规则内容经
                # purpose 常量逐字在场、方案名词扫描在 append-trace 脚本侧，
                # CLAUDE.md/auto-memory 对本步是死重；输入契约（子3 标准集全文
                # = SC#3 trace 及其携带的验收包六字段传导链）在本节点留痕节
                # 逐字在场，包尾「按需 Read」通用邀请是反指（基线 A1/A2 evidence
                # 元探查 grep/python3 读全量零信息增量实证）。
                segment_strip_project_context=True,
                pack_self_contained=True,
                selfcheck=(
                    "每条陈述单句只含 1 个独立标准吗（「和/以及/同时」连接多项 = "
                    "复合未拆净，回子1）？脱离本会话可独立理解吗"
                    "（主语+动词+约束自包含）？验收包六字段"
                    "（指标/基线/阈值提案/方法/时机/证据形式）都传导了吗？"
                    f"无方案名词残留吧（逐条看主语：{_SOLUTION_FREE_SUBJECT_RULE}）？"
                    "statements 载荷 text 逐条无实现侧名词吧（文件名/类名只进 boundary，"
                    "append-trace 机械扫描会拒）？"
                    "格式照 scaffold 骨架填了吗——没去翻引擎/测试源码反推校验"
                    "实现吧（被拒按报错文案修）？"
                ),
                # v2.98 gate framing 反转（§3.5 #28 泛化第十六例，
                # designs/u4-sub4-gate-framing-design.md）：基线 382 字从严版
                # clean 0/6（口径限定词误伤族第四次），6/6 全轮主引
                # 「default 管线/报告/因子明细=实现侧名词」「打开/读出=实现动词」
                # 误伤--_SOLUTION_FREE_SUBJECT_RULE 逐字列「管线名/字段名」为
                # 禁用与 must 目标自带口径限定词必然入 text 矛盾（#23 修文本不
                # 站队，u:2#4/u:3#4/u:4#1 同族第四次）。改默认-PASS + 4 方框
                # （验收包字段不传导/边界不传导/复合未拆/方案动作残留重划线）+
                # 两结构段（判材边界=子3+子4 拼合 artifact 即全部判材；本步命题
                # 性质=归一化，可行性/选择理由归子3 非本步字段）。方框四判别线=
                # 指向项目源码构件或写代码动作才违规，指向用户可见数字/口径/验收
                # 行为合法。落地版两轮达标三向全 6/6（clean 6/6，vio1-4 各 6/6，
                # 判词逐条引对条款）。
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、minor_stage=SuccessCriteria 且 sub_step==4 的记录。形式要件：子3 标准集每项各 ≤1 句且自包含（原子+去上下文=对象+动作+约束，中文省略主语合法）；陈述携带验收包六字段（指标/基线/阈值提案/验收方法/时机/证据形式）与 verdict 边界。（statements 三字段非空（text/type_label/boundary）已由 append-trace 逐项 JSON 机械校验通过--你不得以「缺 type_label/缺 boundary/字段不齐/未声明 evidence 路径」为由 block，这些字段在场是机械已知事实。）\n"
                    "默认 pass--仅当以下成立才判 block（每条附合法形态，合法形态在场不得判）：\n"
                    "一、验收包字段不传导·方法/时机/证据形式篡改或丢失：type_label（验收方法/时机）与子3 已定不一致（子3 定 demonstration 而陈述标 analysis、子3 定 triggered 而陈述标 continuous，或反之）判 block；验收包六字段中的验收方法/时机/证据形式与子3 对应项矛盾判 block。合法形态=陈述的验收方法/时机/证据形式与子3 对应一致即合规；六字段中的指标/基线/阈值提案是提案性内容、表述措辞不必逐字复刻子3。**六字段=指标/基线/阈值提案/验收方法/时机/证据形式**--可行性三态/选择理由/待建手段清单是子3 论证叙述、非验收包字段，不得以「缺可行性/缺选择理由/缺待建手段/缺时机风险标注」为由 block，不得索取子3 未定的字段。\n"
                    "二、边界不传导·口径限定抹掉改更强断言：陈述抹掉子3/前序已证实的口径限定（default 管线、数据截至2026-07-24、IC均值严格大于0）改成更强断言（如「全部管线当前实时」）判 block。合法形态=陈述以子3 边界内口径表述即合规，text 概括而限定写在六字段/boundary 都合法--不得索取比子3 更强断言，不得要求 text 逐字复刻子3 措辞。boundary 字段=verdict 边界（SC ID + 目标覆盖范围，如「SC1.1；G1 全量覆盖」），**不是实现指针**--不得以「boundary 缺 file:line/缺实现指针/缺出处」block。\n"
                    "三、复合未拆：单句用「和/以及/同时/并」连接多个独立验收标准（各自可单独成为一条、引入不同度量对象或验收事件，如规模数字核对 + 口径一致性核对）判 block；同一验收标准的度量列举（条数+占比是同一验收事件读出的两个数字）、验收条件（与明细计数一致）、修饰成分/约束枚举不算并列--无上述连接词、或连接的成分服务同一标准时，不得判并列。\n"
                    "四、方案动作残留：text 主语/动作是**项目源码构件标识**--脚本文件名/类名/方法名/函数名/模板/file:line，或**代码实现动作**（开发/实现/编写脚本/新增 X）判 block。合法形态（在场不得判）=**用户已确认的数据口径限定词与交付载体不是实现侧名词**：管线名（default 管线）、指标口径（IC均值）、数据日期（数据截至2026-07-24）、比较关系（严格大于0）、报告/页面/字段值/因子明细 等口径与载体表述，是 must 目标自带的已证实边界成分，入 text 合规；**验收事件描述性动词**（打开报告/读出数字/拿口径对照/确认）是验收行为描述非代码实现动作，合法。判别线=指向项目源码里的某个构件或写代码动作才违规，指向用户可见的数字/口径/验收行为不违规。boundary 字段内容不在本判据范围--boundary 含实现指针/file:line 是判据规定的去处，不得因 boundary 有任何实现细节而判 block。\n"
                    '【判材边界】artifact=子3（验收方式设计）+子4（归一化陈述）两行 JSON 拼合，生产 read_evidence_for_step(4,"SuccessCriteria") 同形。子3 trace 是逐项一致的对照基准（验收方法/时机/证据形式来源），artifact 即全部判材--不得以「缺 sub_step==4 独立记录/子3 子4 混在同一 kind=skill-trace 块/跨子步串号/看不到 evidence 原文」为由 block；两行 JSON 同 minor_stage 同 kind 是生产拼合常态。\n'
                    "【本步命题性质】本步做归一化陈述：把子3 验收方式设计逐项压成原子单句+完整验收包六字段+verdict 边界。阈值拍板归子5、验收方式认可归子5。不得以「缺可行性三态/缺选择理由/缺待建手段清单/缺时机风险标注」block（这些是子3 叙述非归一化字段）；不得代子3/子5 的判据在本步执行。\n"
                    "【合法正例】「验收时打开 default 管线最新报告，能读出正 IC 因子条数与占全部因子的百分比两个数字，且与报告内因子明细逐条计数一致」标 type_label=demonstration/triggered 合规（不判「default 管线/报告/因子明细」方案名词，不判「打开/读出」实现动词，不判「条数+占比」并列--同一验收事件的两个读数）；「验收时拿报告 IC 口径与用户口述口径对照，能确认所用 IC 是 IC均值 且比较关系是严格大于 0」标 type_label=inspection/triggered 合规（不判「口径名称+比较关系」并列--同一核对的两个对象）；子3 条目几项即几条陈述--逐项一致的核对=SC ID（SC1.1/SC2.1）覆盖，子3 的可行性三态/选择理由/时机风险是论证叙述非条目；boundary「SC1.1；G1 全量覆盖」=verdict 边界合规（不索 file:line）；省略主语的动宾短语（「验收时打开…能读出…」）合规--不得判「缺主语/非陈述式/祈使短语」。方框以外一律不判。\n"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例（指模式不指实例位置）。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem / AskUserQuestion",
                short="读回确认",
                interactive=True,
                # 带证据读回（同构前三个节点末步）。本子阶段两个规范裁决点：
                # 阈值拍板（风险偏好）+ 验收方式认可（含「待建手段」是否接受为任务项）。
                purpose=(
                    "带证据的读回确认：材料 = 运行 `python3 ~/.dl-workflow/dl_flow_engine.py render-readback` 机械装配逐字呈现（本节点归一化+假设/不确定性 traces，禁手抄；Bash 输出即呈现）。呈现内容 = 归一化标准+验收包+不可检验退回项"
                    "+「验收手段待建」清单+不确定性；"
                    "用户裁决两件事：①阈值拍板（风险偏好 = 规范裁决，"
                    "本子阶段第一裁决点）；②验收方式认可（含「待建手段」是否接受为"
                    "本实例任务项——等于给 plan 埋任务，须用户知情；第二裁决点）；"
                    "不可检验退回项显式暴露由用户裁决"
                    "（降低标准/回退目标定义/接受定性验收）；"
                    "用户认/否/调整记入 trace。"
                    "裁决完成后装配 understand.md = 运行 `python3 "
                    "~/.dl-workflow/dl_flow_engine.py render-artifact understand.md`"
                    "（脚本从 4 子阶段最新归一化陈述+裁决/未选定 trace 机械装配，"
                    "落主仓 .claude/understands/<name>.md；禁手写产物文件——"
                    "内容要改就改对应步 trace 后重渲染）；"
                    f"{_INTERACTIVE_CHUNKING_RULE}。{_USER_DECISION_RECORD_RULE}"
                ),
                input="step4.statements",
                record=True,
                selfcheck=(
                    "呈现了归一化标准+验收包+退回项+「验收手段待建」清单+不确定性吗？"
                    "用户对阈值拍板与验收方式认可的两项裁决都记入 trace 了吗？"
                    "退回项显式暴露了吗？"
                    "understand.md 已用 render-artifact 装配落主仓了吗（禁手写产物）？"
                ),
                # v2.45 交接架构正确性前提：用户裁决必入 trace（gate=None 无 judge，
                # 机械校验是唯一防线）。
                mech_checks=("user_decision_recorded",),
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
        # u4-sub1-cost（designs/u4-sub1-cost-optimization-design.md L1）：
        # tools-only 置位（u:3 同型——env 剥离不做节点级，逐步粒度见子1）。
        # 逐步工具需求核对（design §2 L1 表）：#1 Read(need_user)+Bash(落库)
        # +Edit(骨架)+TUI 三件套（自动并）/#2 Bash 基线测量/#3 Bash(codegraph)
        # +Read/#4 Skill(define-problem)/#5 无会话——全节点无一步合法需要
        # Agent。Agent 不在单 = 机制堵「为后续步预取证据」步骤越界
        # （u3_sub4_ab 基线：子1 段派发 2 个 Explore 为子3 预取 file:line，
        # 21.3k in/41.9k cr 纯税；#16 文案管不住，机制堵入口）。
        segment_tools=("Bash", "Read", "Edit", "Skill"),
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
        # p1-sub1-cost（designs/p1-sub1-cost-optimization-design.md L2）：
        # 工具白名单（plan 族首例）——逐步需求核对（设计 §2 L2）：六步需求
        # 并集 = Bash/Read/Edit/Grep/Skill/Agent；载荷走 --scaffold+Edit 零
        # 合法 Write；MCP 由 NO_MCP_ARGS 结构封死（既有）。env 剥离不下放
        # 节点级（子2-6 逐步核对未做），子1 逐步置位见下。
        segment_tools=("Bash", "Read", "Edit", "Grep", "Skill", "Agent"),
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
                    # p1-sub1-cost L3（复用钉死，cost-optimization #25/#29
                    # 收紧形态：默认零重验+枚举例外+按条配额+时间敏感项排除）：
                    "材料边界（复用钉死）：交接包前序各节点归一化陈述与读回"
                    "裁决所载出处（file:line/实测命令与输出/机制结论/数据契约"
                    "字段）逐字直接引用即合法（「复用 <节点>子N 留痕：<出处"
                    "逐字>」形态），零重跑重验（前序已定位的 file:line 不重修、"
                    "已实测的字段存在性不重测、已查过的符号不重查——符号查询"
                    "走 dl codebase query --symbol，前步已查符号自动返台账"
                    "缓存）。枚举例外（逐条可判定的二值条件）：①codegraph "
                    "新鲜度判定=时间敏感，本步实测一次（dl codebase freshness，"
                    "命令全文见 node-rules 发现台账段——禁复用前序判定）；"
                    "②四要素某条事实在前序留痕中从未出现（符号/字段/模块名"
                    "零提及）→ 该事实单点验证一次（每条事实最多一次，验存在"
                    "即止，禁顺手掘进内部结构）。零 evidence 全量翻找（前序"
                    "结论已在交接包）。"
                ),
                input="understand.md（问题陈述+范围约束+成功标准）",
                record=True,
                fence_allow=("Bash",),
                # p1-sub1-cost L1：Step 级 strip（第七例）——交付物=四要素
                # 现状事实+新鲜度判定，出处形态=codegraph/dl codebase 输出/
                # file:line/Bash 实测/复用引用，无点名项目硬规则条号职责
                # （与 u:4#1-#4 同型）；新鲜度通道由 dl codebase freshness
                # 补位（原 SQL 只在项目 CLAUDE.md §3，剥 env 后唯一通道）。
                segment_strip_project_context=True,
                # p1-sub1-cost 修1：复用钉死的逐字引用材料=前序 statements
                # boundary——P1-1 截断 100 字符恰切在 file:line 处（B1 轮
                # 模型翻 evidence×6+重验 ~10 调用实证），置位保全文。
                pack_full_prior_boundary=True,
                # v2.99 framing 反转（designs/p1-sub1-gate-framing-design.md §3）：
                # 留痕投影（引用代码符号形却无工具动词）下沉 mech 零方差生产墙，
                # 纯 token 扫描不读 db（⑯-safe）；存在性真值归子3 不在此。
                mech_checks=("terrain_tool_trace",),
                selfcheck=(
                    "codegraph 新鲜度检查留痕了吗（>72h 先 sync）？"
                    "四要素都覆盖了吗（或显式「无+理由」）？"
                    "每条事实都附 codegraph 原始输出或 file:line 了吗，"
                    "还是有凭训练记忆写的？勘察范围与 understand.md 对齐吗？"
                    # p1-sub1-cost L3：
                    "前序已载出处逐字引用零重验了吗？前序零提及的事实每条 "
                    "≤1 次单点验证、验存在即止吗？零 evidence 全量翻找吗？"
                ),
                gate=(
                    f"evidence/<name>.jsonl 含 kind=skill-trace、minor_stage=DesignSolution "
                    f"且 sub_step==1 的记录。形式要件：{_DS_STEP1_FORM_REQUIREMENTS}。\n"
                    "默认 pass——仅当以下成立才判 block（每条附合法形态，合法形态在场不得判）：\n"
                    "一、现状事实无出处（编造）：现状事实条目（①涉及模块/②可复用点/③调用方/④数据契约/新鲜度判定）声称已验证/已核实/已定位却无任何工具出处判 block。**引用代码符号形（`.py`/`function X file.py:N`）却无任何工具动词的现状事实已由 terrain_tool_trace 机械校验当场拒、不会到你这里**——你不得以「无工具出处/留痕不可核验/缺 file:line/引用不存在接口」为由 block。残留语义判面：(a)训练记忆冒充——「一般/通常/按惯例」式常识断言（未引用符号形）替代工具核实（如「一般这类项目都有 utils.py」）判 block；合法形态=「一般/通常」式断言不附任何具体符号仅作背景句不判，附了具体符号无出处由机械层拦。(b)引用具体符号的条目留痕在场但与声明来源明显矛盾（归方框二）。\n"
                    "二、内部矛盾：trace 内声称的 codegraph 输出/Read 核实/Bash 实测结果与自述内容明显矛盾（如声称「callers 输出 0 个调用方」却又列 3 个具名直接调用方）判 block。judge 只判 trace 内自洽，不判与真实代码库的一致性——本载荷内无 codegraph 索引，符号是否真实存在本仓由 plan:1 子3 可行性验证判，你不得以「该符号在仓内不存在/引用不存在接口/模块/无法核验符号真实性」为由 block。\n"
                    "三、漫游：勘察链路与 trace 内自述的问题陈述/任务零相关（勘察了与「报告展示正 IC 因子数量」零相关的日内择时/pipeline 内存治理链路）判 block。「范围对齐」判面=trace 内自述的勘察范围与自述的问题陈述自洽即合规。understand.md 是主仓 .md 文件、结构性不在本载荷内（evidence 只含 DesignSolution 段），你不得以「未见 understand.md 原文/未附其 file:line/无法核实范围对齐/无法确认问题陈述完整」为由 block。\n"
                    "四、新鲜度留痕缺失：声称「无需 sync」却无任何新鲜度判定依据（Bash 实测时间戳+判定结论）判 block。附时间戳+判定即合规（任一 q/a 内均可），不要求单独留痕条目/命令原文/多表核对。\n"
                    "五、口径断言无出处：数据契约字段/阈值断言（「ic_mean > 0」）声称已核实却无字段存在性出处（Bash 实测 schema names/Read paths.py 常量）判 block。字段存在性有出处后，口径/阈值判定本身不必单独出处。\n"
                    "【判材边界】本步 input=understand.md 是主仓 .md 文件，evidence 只含 DesignSolution 段——judge 结构性读不到 understand.md；存在性真值复核归 plan:1 子3（可行性验证的接口/模块存在性核验），本步不判「引用符号是否真实存在于本仓」。\n"
                    "【合法正例】「codegraph callers _generate_ic_section 输出 1 个调用方」简写引用合规；「summary/report/sections.py:32」file:line 定位合规；「Bash 实测 `sqlite3 …MAX(indexed_at)` 输出 2026-08-04 09:12 距今 <72h」合规（新鲜度判定不必单独条目）；「④字段口径 Bash 实测 schema names 含 ic_mean，正 IC 判定用 ic_mean > 0」合规（口径断言不必单独出处）；「勘察范围与 understand.md 对齐：只勘察报告展示链路」自述声明合规（不要求附 understand.md 原文）。方框以外一律不判。\n"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例（指模式不指实例位置）。"
                ),
            ),
            Step(
                kind="tool",
                ref="推理(架构维度变换) / AskUserQuestion(用户既有想法)",
                short="方案发散",
                interactive=True,
                purpose=(
                    f"方案发散：{_DS_STEP2_FORM_REQUIREMENTS}。"
                    "design fixation 防御核心：禁评估禁排序——混入评估=发散被"
                    "收敛污染；对自己最初想法的固化是最强固化源（Leahy et al.），"
                    "用户既有想法平权入列不预设首选。"
                    "双结论制：②「设计空间唯一」合法（约束钉死全部维度，"
                    "如纯机械重命名），但须逐维度论证——防逼编造伪候选凑数。"
                    # p1-sub2-cost L2（复用钉死+职责边界，cost-optimization
                    # #25 收紧形态——默认零新查询+无取证例外，例外缺口的合法性
                    # 由 gate 凭空设计判据结构性保证：候选引用面=子1 trace
                    # 已列事实，包外材料进候选即违规）：
                    "材料边界（复用钉死）：候选锚定材料=交接包（本节点子1 "
                    "现状地图全文+前序各节点结论摘要）与 prep 载荷 sources——"
                    "逐字直接引用即合法出处；本步零新取证：不跑 codegraph/"
                    "dl codebase/grep、不 Read 仓内代码文件重定位、不重验"
                    "前序已载出处、零 evidence 全量翻找。无取证例外——"
                    "子1 未列出的事实不得进候选（gate 凭空设计判据同义），"
                    "新取证在本步无判据出口。职责边界：存在性/重复实现/影响面/"
                    "硬规则兼容核验归子3（本步候选不逐条引规则条号，缺引不"
                    "违规）；评估排序归子4；为后续步预取材料=越界（「先查清楚"
                    "再发散」不是本步职责）。"
                ),
                input="step1.terrain_map",
                record=True,
                # p1-sub2-cost L1：Step 级 strip（第八例，交互步第二例）——
                # 交付物=候选+维度声明+用户想法入列，gate 零规则引据要求
                # （硬规则兼容=子3 五项核验④职责，L2 条款钉死缺引不违规防
                # 剥后重读规范文档——u3-sub1 反超教训的对策）；工具需求
                # Bash/Read/Edit+TUI 三件套全在 Node 白名单既有面内。
                segment_strip_project_context=True,
                # p1-sub2-cost L3：pack_self_contained（交互步第二例）——
                # 输入契约（step1.terrain_map+问题陈述+目标/约束摘要+prep
                # sources）逐字段核对 ⊆ 包内（ab2 真迹四步核对：零包外取证、
                # gate 凭空设计判据使包外材料结构性不可用=#19 判别意图不命中）。
                pack_self_contained=True,
                selfcheck=(
                    "≥3 个候选吗，还是走了②（走了②有逐维度论证吗）？"
                    "每个候选都锚定子1 事实条目了吗（有凭空 API 吗）？"
                    "候选间是架构维度实质差异还是措辞变体？"
                    "有评估/排序性措辞混入吗（评估是子4 的事）？"
                    # p1-sub2-cost L2：
                    "候选锚定材料全部引自交接包/prep 载荷 sources 吗（零 "
                    "codegraph/grep/仓文件重查、零 evidence 翻找、零为后续步"
                    "预取）？"
                ),
                gate=(
                    "默认 pass——仅当以下明列的 block 条件成立才判 block（每条附合法形态，"
                    "合法形态在场不得判）。evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=DesignSolution 且 sub_step==2 "
                    "的记录；"
                    f"形式要件：{_DS_STEP2_FORM_REQUIREMENTS}。"
                    "方框判据（仅以下成立判 block）：一、伪候选与候选不足：候选间无架构维度实质差异（"
                    "同模块同函数同改动点，仅换写法/换函数形态/换表述）判 block；候选数 <3 "
                    "且未走②逐维度唯一性论证判 block——候选在架构维度（换模块归属/换数据结构/复用 "
                    "vs 新建/换执行时机/换数据流）两两存在任一差异即非伪候选，不得因候选共享「分组统计」"
                    "类主题、或都涉及同一模块侧聚合、或维度声明未逐项展开而 collapse 为伪候选，"
                    "不得要求跨全部维度的骨架级差异；候选数 ≥3 即满足数量要求，不要求每候选达到某种详细度。"
                    "二、凭空设计：候选声称调用/复用/基于子1 未列出的既有文件/模块/函数/API "
                    "判 block——子1 trace 已列事实是该步勘察的穷尽范围，同一模块目录下子1 "
                    "未列出的具体文件/函数/API（如 summary 模块下子1 未列出的 render_lib.py "
                    "及其 render_category_breakdown）仍属未勘察引用，不得以「位于已知模块内/同模块既有实现/同 "
                    "summary 模块」推定锚定；候选新增/创建文件本身不判凭空（新增脚本/新文件是合法设计动作）"
                    "；候选引用的模块/文件/复用点/数据契约均能在子1 trace 找到对应条目即锚定合规，"
                    "不得要求每个候选逐条指名函数/file:line/代码级定位到符号（「在 generate_factor_summary_report.py "
                    "既有聚合统计函数内」=模块+文件+函数域已锚定合规）。判「凭空设计」须对照子1 "
                    "trace 已列事实逐候选核对每个文件/模块/API 引用是否在子1 列出。三、"
                    "提前收敛排序：发散过程混入评估/排序/选定措辞（「A 优于 B」「推荐 A」「最终选定 "
                    "A」「B/C 不再考虑」「最优方案是 A」等）判 block——发散过程只列候选不评价优劣、"
                    "或显式声明「评估归子4」即合规；候选间维度差异声明里的比较性描述（「两两不重叠」"
                    "「各候选架构维度不同」）是差异声明不是评估排序，不得判；「方案较多/待子4 评估」"
                    "类陈述是合法记录不是收敛。四、②无逐维度论证（偷懒）：结论②「设计空间唯一」仅以「约束钉死全部维度」"
                    "式一句概括、未逐维度（换模块归属/换数据结构/复用 vs 新建/换执行时机/换数据流）"
                    "给出无备选理由判 block——②对设计维度逐项给出无备选理由（简略即可）即合规；"
                    "结论①多候选成立时本条款不适用，不得以「候选不足/未逐维度」block 结论①的 "
                    "trace。【关键】不得以「用户既有想法未列为一等候选/未展示 AskUserQuestion "
                    "实际问询内容与用户原话/未说明平权入列为何不适用/无用户想法占位候选位」block——用户无既有想法时明确记录「经 "
                    "AskUserQuestion 询问用户无既有方案」即合规（不必编造或保留用户原话占位）"
                    "，用户有既有想法时该想法平权入列（与模型候选并列、不预设首选）即合规，不得以「用户应有既有想法」"
                    "推断 block。【合法正例】「经 AskUserQuestion 询问用户暂无既有方案、"
                    "授权模型从代码现实发散」合规；「在 summary/generate_factor_summary_report.py "
                    "既有聚合函数内加 FACTOR_CATEGORIES 分组键」「新增脚本 scripts/factor_category_summary.py "
                    "独立产出」「在 factor_ic 聚合输出增加 CATEGORY 列」三候选锚定子1 "
                    "事实且架构维度（复用 vs 新建/换模块归属/数据契约变更）不同=非伪候选合规；"
                    "「三候选在架构维度上两两不重叠」维度声明合规；「发散过程只列候选不评价优劣」合规。"
                    "方框以外一律不判。judge 判 block 须在 reason 引用判据条款并附 "
                    "1 个正确改写范例（指模式不指实例位置）。"
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
                    # p1-sub3-cost L1（复用钉死，cost-optimization #25 收紧形态：
                    # 默认零重验+枚举例外+按条配额——A 轮基线 35 调用中 ~15 纯税/
                    # 半税=重验子1 已载出处+规范文档重读+掘进）：
                    "材料边界（复用钉死）：候选锚定材料=交接包（本节点子1 "
                    "现状地图全文+子2 候选清单全文）与发现台账——子1 已载出处"
                    "（file:line/codegraph 输出/实测结果）逐字直接引用即合法出处，"
                    "零重验零重跑：①存在性复核对子1 已载 file:line 的符号直接"
                    "引用（「复用 子1 留痕：<file:line>」形态），codegraph 新鲜度"
                    "复用子1 判定结论（非本步职责，不重跑 freshness）；符号查询走 "
                    "dl codebase query --symbol（子1 已查符号自动返台账缓存=合法"
                    "留痕，source=discovery-ledger 可作出处）。③影响面优先复用"
                    "子1 已载调用方清单（「复用 子1 留痕：codegraph callers <符号> "
                    "返回 N 个（名单）」形态）。枚举例外（逐条可判定的二值条件）："
                    "①候选引用的符号在子1 留痕与台账中零提及→该符号单点验证一次"
                    "（每符号最多一次，验存在即止，禁顺手掘进内部结构）；"
                    "②重复造轮子每功能域 ≤1 次查询（同功能域多候选共享一次查询"
                    "留痕=合法，查询词须与候选功能域对题）；③子1 未载调用方的"
                    "改动符号每候选 ≤1 次 impact/callers 查询；⑤测试接缝事实"
                    "前序零提及→每候选 ≤1 次单点定位。④硬规则核验按本会话已"
                    "加载的硬规则速查表点名即可，零规范文档重读（全文阅读规范"
                    "文档不是本步职责）。零 evidence 全量翻找（前序结论已在"
                    "交接包）。"
                    # p1-sub3-cost 修1（B1 轮实证）：载荷组织钉死——B1 模型把
                    # 条款的逐项枚举镜像成「按核验项拆 q」的散列组织，撞 mech
                    # 逐 a 圈码齐备扫描 7 连拒（35 Edit 返工褶皱）；条款枚举是
                    # 例外面清单，不是载荷组织结构。
                    "载荷组织钉死：每候选一对 q/a（q=「候选X 五项核验+三态」"
                    "形态），a 内①-⑤圈码逐项齐备+三态标注——append-trace "
                    "机械校验逐 a 扫描圈码齐备性，按核验项拆 q（「①存在性…」"
                    "一项一个 q）的散列组织当场被拒。格式真源=--scaffold 骨架+"
                    "报错文案，禁翻历史 trace/evidence/引擎源码反推格式。"
                ),
                input="step2.candidates + step1.terrain_map",
                record=True,
                fence_allow=("Bash",),
                # v2.103 framing 反转（designs/plan1-sub3-gate-framing-design.md §3）：
                # 三条负判定判据（缺项/①段裸存在断言/②段无查询「无重复」）在默认-PASS
                # 下崩牙（㊳），词形可判子项下沉 mech 零方差生产墙，纯 token 扫描
                # 不读 db（⑯-safe）；语义残项留 judge。
                mech_checks=("feasibility_verification_trace",),
                selfcheck=(
                    "每个存活候选都做了五项核验吗（存在性/重复实现/影响面/"
                    "硬规则/可测试性，无遗漏）？三态逐候选标注了吗？"
                    "可行项附出处、假设项含置信度+错误时影响、剔除项附理由了吗？"
                    # p1-sub3-cost L1：
                    "子1 已载出处逐字引用零重验了吗（file:line/callers/新鲜度"
                    "结论）？每符号/功能域/接缝查询 ≤1 次、验存在即止了吗？"
                    "零规范文档重读、零 evidence 翻找了吗？"
                ),
                gate=(
                    "默认 pass——仅当以下明列的 block 条件成立才判 block（每条附合法形态，合法形态在场不得判）。"
                    "evidence/<name>.jsonl 含 kind=skill-trace、minor_stage=DesignSolution 且 sub_step==3 的记录；形式要件：对子2 存活候选逐一做五项核验留痕（①接口/模块存在性复核②重复造轮子检查③影响面量化④项目硬规则兼容⑤可测试性）；三态逐候选标注（可行附出处/假设附置信度+错误时影响/证伪剔除附理由）；q/a 按序对齐。"
                    "方框判据（仅以下成立判 block）：一、编造（声称存在无出处）：**①-⑤ 圈码结构的逐项齐备性（缺项/未标三态）、①存在性段的裸存在断言（声称存在/已核实/可复用却无 file:line 且无工具动词）、②段的「无重复/需新建」裸断言（无 codegraph/Grep 查询动词）已由 feasibility_verification_trace 机械校验当场拒、不会到你这里**——你不得以「缺某项/缺三态/存在性无 file:line/无 codegraph 输出留痕/未附查询语句」为由 block。"
                    "残留语义判面：(a)训练记忆冒充——未引具体符号的「一般/通常/按惯例」式常识断言替代核验（如「一般这类项目都有统计函数」）判 block；合法形态=「一般/通常」式断言不附具体符号仅作背景句不判。(b)留痕在场但与自述明显矛盾（如声称「codegraph 返回 0 个同功能实现」却又列具名同功能实现）判 block。"
                    "二、影响面拍脑袋：③影响面量化无 codegraph impact（或 callers 查询）返回留痕，仅凭估计给数字（「估计 1-2 个调用方」式）或「影响面小/可控/风险低」式笼统结论判 block——附 impact 返回的 callers 数与名单即合规；「callers N 个」与「不改函数签名则调用方零改动」并存合法、不是自相矛盾，不得裁量判矛盾；新增文件无 callers 时声明「impact 不适用」并说明影响面形态即合规，不得索取 callers 数字。"
                    "三、无差别可行（没真核验）：全部候选无差别标同一态且五项核验内容跨候选笼统趋同（「均通过/无异常/均兼容/可控」式无量化数字、无 file:line、无规则点名）判 block——核验内容随候选差异分化（不同 file:line/不同 callers 数/不同规则命中）即合规；三态是标注类目不是配额，核验后全部候选同落一态但各有具体留痕的合规，不得要求三态齐全或每态至少一例。"
                    "四、重复实现漏检（语义残项）：②查询留痕在场但查询方式与候选功能域明显不对题（候选做维度分组统计、查询词却是「内存优化」式零相关）判 block——查询留痕与候选功能域沾边即合规，不得核对代码库是否真实存在被漏检的重复实现（db 不在判材内）。"
                    "【判材边界】只判 trace 内留痕在场与自洽，不核 codegraph db 真值（db 不在判材内）；出处形态=file:line 或工具查询摘要（查询方式+返回概述）即合规，不得索取 codegraph 原始输出全文/节点 ID/命令完整回显。"
                    "【关键】三态是逐候选整体标注，不得要求①-⑤逐项各标三态；「可行」附出处即合规，不得对「可行」索取置信度（置信度+错误时影响只属「假设」态）；置信度给档位加一句理由即合规；证伪剔除附理由即合规（理由可引本步③的量化结果），不得索取独立 codegraph 原始输出；硬规则核验点名命中规则加声明其余不触及（如「H11-H13 不触及」）即合规，不得要求 H1-H13 逐条点名、不得核对规则条文引用准确性（规范全文不在判材内）；新增文件本身无需存在性核实，「新文件无需存在性核实」声明合法；某项核验以「不适用+原因」声明即合规不算缺项；前序 trace（子1 现状地图/子2 候选清单）只作组成事实，本步无跨步一致性判据，不得以「与子1/子2 不一致」block。"
                    "【合法正例】「codegraph impact _aggregate_positive_ic 返回受影响 callers 2 个（generate_factor_summary_report.py:203、run_pipeline.py:658），不改签名时调用方零改动」合规；「codegraph 查询 scripts/ 下同功能脚本，返回 7 个脚本无一做八维度分组汇总，无重复」合规；「假设（置信度：中——scripts/ 注册机制未核实；错误时影响：产出不被 pipeline 自动消费）」合规；「证伪剔除（理由：schema 变更跨三模块违反 H1/H9）」合规；「新文件无需存在性核实」合规；「H11-H13 不触及」合规。"
                    "方框以外一律不判。judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例（指模式不指实例位置）。"
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
                    # p1-sub4-cost L3（复用钉死，消费步形态——cost-optimization
                    # #25 收紧形态，默认零新查询，唯一例外=条件红队派发）：
                    "材料边界（复用钉死）：评分/追溯材料=交接包（本节点子1-3 "
                    "留痕全文+前序节点结论摘要）——逐字直接引用即合法出处；"
                    "本步零新取证：不跑 codegraph/dl codebase/grep、不 Read "
                    "仓内代码文件重验重定位、零 evidence 全量翻找（前序留痕"
                    "全文已在包内）；唯一取证面=条件红队派发（触发时）。"
                    # p1-sub4-cost L4（格式真源钉死，cost-optimization #26
                    # 平移——子4 有两个 append-trace mech，防反推校验实现）：
                    "载荷格式与传导核对细节的唯一真源=--scaffold 骨架+"
                    "append-trace 报错文案（格式归脚本）——禁读引擎/测试源码"
                    "反推校验实现，被拒按报错文案逐字修即可。"
                    # p1-sub4-cost L5（红队材料包钉死——基线实证：模型手写
                    # 极简 prompt 零材料，agent 把「独立上下文」读成独立重勘
                    # （重跑 codegraph/grep 全仓/python 重算数据文件，单 agent
                    # 25-58 调用），红队侧等效占本步总账 ~73%）：
                    "红队纪律（触发时）：派发 prompt 必须逐字携带攻击对象材料"
                    "包——该候选描述+子3 五项核验结论+本步矩阵逐格评分理由"
                    "（均在你本会话上下文，复制即可）；红队职责=基于材料的独立"
                    "判断攻击（设计逻辑/一致性/遗漏风险），存在性/影响面/数据"
                    "契约以子3 留痕为准零重验，禁重跑 codegraph/grep 全仓勘察/"
                    "重算数据文件，确需复核时 Read 单点文件定点核对（每攻击点"
                    "至多 1 次）；攻击对象=排序第一候选一次，多攻须逐条附理由。"
                ),
                input="step3.feasibility_verdicts",
                record=True,
                fence_allow=("Agent",),
                # p1-sub4-cost L1：Step 级 strip（第九例）——交付物=矩阵评分+
                # 追溯+红队留痕，H 条号/规则事实经子3 留痕逐字在场（消费步，
                # u3-sub3 同型），交付物正文不引自动加载文档为一等材料。
                segment_strip_project_context=True,
                # p1-sub4-cost L2：pack_self_contained（非交互步第三例）——
                # 输入契约（子2 候选+子3 三态核验+must 目标集+验收包）经本
                # 节点前序留痕全文通道+前序节点 statements 段全在包（置位
                # 前置=四步核对法对生产真迹：引文跨度 4/9 精确命中+5 条同源
                # 转写人工确认、事实项 G1/G3/候选名全命中，详见设计 §2）。
                pack_self_contained=True,
                selfcheck=(
                    "矩阵逐格评分都附理由了吗？理由都引用子3 核验事实了吗？"
                    "双向追溯两向都无漏吗？红队触发/未触发留痕了吗？"
                    "是「提案-待用户裁决」语义吗（没有替用户拍板）？"
                    # p1-sub4-cost L3/L5：
                    "材料全部引自交接包吗（零新查询/零仓文件重读/零 evidence "
                    "翻找）？红队 prompt 逐字携带材料包了吗（候选描述+子3 核验"
                    "+评分理由）？红队只基于材料攻击、零重勘吗？"
                ),
                # v2.103 framing 反转（designs/p1-sub4-gate-framing-design.md §2）：
                # 从严 216 字 clean 0/6 全误伤（datum 行/引原文出处/表格版式/Pugh 常规
                # 权衡被读成凑结论/红队加跑被读成留痕缺失/权重提案被读成拍板 6 类发明
                # 要件）。v1 反转治 clean 6/6 但 vio3/vio4 崩牙——**跨项聚合类判定**
                # （算术核对/集合差）默认-pass 下 judge 系统性不做（§3.1 校准 ㊳）：
                # forward 覆盖下沉 pugh_traceability_forward_coverage 零方差生产墙，
                # 净分自洽改「须动手数格」操作化措辞（格式自由度高，词形下沉脆弱）。
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、minor_stage=DesignSolution 且 sub_step==4 的记录；形式要件：Pugh 矩阵逐格评分（+/S/−）+理由；理由引用子3 核验事实；双向追溯两向逐项；条件红队触发/未触发留痕。\n"
                    "\n"
                    "默认 pass--仅当以下成立才判 block（每条附合法形态，合法形态在场不得判）：\n"
                    "\n"
                    "一、评分理由空泛不引事实：逐格理由只有形容词式断言（「差不多/复杂一些/没什么区别/风险高/不太好测/规矩上麻烦点」）而不含任何子3 已列的具体核验值判 block——判本条须逐格核对理由内有无子3 具体核验值（文件数与行数／codegraph impact 或 callers 符号数／函数名或 file:line／H 编号／测试接缝事实，任一在场即合规）；引用形式不挑：「（子3 实测 2 文件约 60 行 vs A 的 1 文件 30 行）」式转写引用即合规，不得要求引子3 原文、贴 file:line、标注子3 出处位置、或要求该评分维度在子3 有同名核验条目；datum 候选写「=datum 全 S」即合规，不得要求 datum 自身逐格展开评分与理由；S 格（与 datum 无差异）理由可以是「子3 未见该维度差异」式，不得因 S 格理由不含新事实而判空泛；双向追溯段与红队段不是评分格，不得以「追溯段未逐项引子3 事实」判本条。\n"
                    "\n"
                    "二、替用户拍板：结论以定案口吻收口（「最终选定／就这么执行／已确定／无需再问用户／直接剔除」）判 block——「推荐提案＋待子6 用户裁决」语义在场即合规；权重陈述（「本轮按改动面与影响面优先」）是权重提案、不是替用户行使裁量，不得以「预设权重／权重未经用户认可即使用／未给权重映射表」判 block；给出排序与推荐本身是本步产物（只提案不拍板 ≠ 不许推荐），不得以「已给出完整排序与推荐＝已拍板」判 block。\n"
                    "\n"
                    "三、矩阵结论与评分矛盾（凑结论）：**逐格 +／− 个数与自述净分数值的算术自洽已由 append-trace 机械校验——净分数值与逐格计数不符的 trace 已被当场拒、不会到你这里，你不得以「净分数值与逐格标注不符／未数格／S 项计入或未计入净分」为由 block**；本条残留判面=净分数值与排序或推荐的对应自相矛盾（某候选净分高于 datum 却被排在其后或不被推荐，且无任何理由）判 block。合法面：逐格 +/S/− 本身的权衡判断不是矛盾（同一候选既有 + 又有 −、S 格计 0 不进净分、datum 由改动面选出而其余维度全 S，均是 Pugh 常规），不得以「S 项未计入净分／扣分维度取舍不自洽／datum 起点与某维度评分矛盾／该候选在某维度也是 S 却总分为负」判凑结论；本条只核「净分数值 ↔ 排序 ↔ 推荐」三者对应是否自洽，不判评分本身给得对不对。\n"
                    "\n"
                    "四、双向追溯漏项：**forward 覆盖（自述 must 目标集的每个目标是否在 forward 段有要素承接）已由 append-trace 机械校验——forward 漏目标的 trace 已被当场拒、不会到你这里，你不得以「某 must 目标在 forward 段无承接／两向不闭合／防漏不全」为由 block**；本条残留判面=①backward 段有方案要素回溯不到任何目标（镀金）且未标注判 block；②forward 段声称的承接关系与该要素实际内容明显不符（如声称承接的要素在矩阵与候选描述里根本不存在）判 block。两向以散文逐项列出即合规，不得要求呈现表格／格表／矩阵版式（「双向追溯矩阵」指两向对应关系逐项齐备，不指版式）；多个要素回溯到同一目标合规，不得要求要素与目标一一对应或要求目标数与要素数相等。\n"
                    "\n"
                    "【关键】不得以「未呈现表格形式／datum 行未逐格展开／datum 行缺失／理由未引子3 原文或出处位置／未给权重映射表／红队既称未触发又跑了一次＝留痕不完整」block 已附逐格评分＋具体核验值＋两向逐项＋触发条件与实际取值的 trace。条件红队留痕＝写出触发条件与本轮实际取值（如「净分差=2、跨模块=否，故未触发」）即合规；在未触发前提下额外自愿对某候选跑一次红队并原文收录其输出，是加强不是留痕缺失，不得判 block。\n"
                    "\n"
                    "【判材边界】must 目标集与成功标准验收包属 GoalsAndValue／SuccessCriteria 节点，evidence 只含 DesignSolution 段——judge 结构性读不到它们，不得以「无法核实 must 目标集完整／未与验收包逐项对照／未附其出处」为由 block；双向追溯只判 trace 内自洽（自述 must 集与自述承接项是否对应）。本步只提案，选型／权重／假设的真伪与采纳归子6 用户裁决，不得以「该推荐是否正确／该假设是否该接受／该权重是否合理」判 block。\n"
                    "\n"
                    "【合法正例】「候选B 改动面 −（子3 实测 2 文件约 60 行 vs A 的 1 文件 30 行）」合规；「候选A＝datum 全 S」合规；「验收包承接度 S（子3 未见承接差异）」合规；「条件红队：净分差=2、跨模块=否，未触发」合规；「本排序与推荐均为提案，权重与选型待子6 用户裁决」合规；「forward：G1←要素一＋要素二承接；G2←要素三承接」散文形式合规。方框以外一律不判。\n"
                    "\n"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例（指模式不指实例位置）。\n"
                    "\n"
                ),
                mech_checks=(
                    "pugh_traceability_forward_coverage",
                    "pugh_net_score_consistency",
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem",
                short="归一化陈述",
                # claim normalization 职能第六次复用（ProblemContext 子6 /
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
                # v2.116 framing 反转（designs/plan1-sub5-gate-framing-design.md，
                # #30 泛化第三十三例）：基线 368 字从严 clean 0/6 + vio 全 6/6，但
                # vio5「否决理由丢失」零轮引对条款（全靠 clean 同源的复合句误伤
                # 词形接住=㉖「错理由拦对」教科书实例）。反转 + 五方框近端双侧
                # 钉死；vio5 卡 ㉗ 抖动带（v1 5/6 -> v2/v3 4/6）后按区分线下沉
                # rejected_rationale_trace mech（statements 侧第二个）。
                mech_checks=("rejected_rationale_trace",),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=DesignSolution 且 sub_step==5 的记录（产物含 "
                    "sub_step 1-5 五条记录是生产常态，判对象=sub_step==5 那条；"
                    "不得以「无 sub_step==5 记录/仅见 1-4」为由 block）。"
                    "形式要件：每项 = 1 个可独立拍板的设计决策（text 单句）；"
                    "fields 八键齐备（append-trace 已逐键 JSON 校验，勿再数字段）；"
                    "text 无实现侧名词（已机械扫描 codegraph 符号 + 仓内文件名）。\n"
                    "默认 pass——仅当以下成立才判 block（每条附合法形态，合法形态"
                    "在场不得判）：\n"
                    "一、字段与子3/子4 已定内容不一致（丢失/篡改/新增）：某项八字段"
                    "与子3 核验结果或子4 推荐/否决结论矛盾判 block——**子4 已否决"
                    "候选的改动方案被写进 type_label=推荐项的 change_list/"
                    "data_contract/interface_sig 即篡改，照判 block**（如子4 推荐"
                    "候选A「既有区块内聚合、数据契约不变」而 change_list 写候选C"
                    "「计算侧预聚合、parquet 加列」）。合法形态=对子3/子4 内容的"
                    "忠实提取/适度压缩/同义转述即合规，不要求逐字一致；callers "
                    "字段同时携带 codegraph callers 与 impact 两类输出合规——字段名"
                    "不要求与 codegraph 子命令一一对应，影响面符号数是 callers 清单"
                    "的合法内容；codegraph 输出的数字真伪不核（子1/子3 已留痕即"
                    "合规）。**这两条合法形态只约束 callers 字段内两类输出的收录"
                    "形式与 codegraph 数字真伪的核验——写成已否决候选方案的字段"
                    "篡改不在其豁免范围内。**\n"
                    "二、复合句（未原子化）：一项 text 合并 ≥2 个可独立拍板的设计"
                    "决策判 block（如「在既有区块内呈现，以及新增一个独立看板」"
                    "——既有区块与新增看板可分别拍板）。"
                    f"{_ATOMIC_ITEM_RULE}。合法形态=同一决策的多个输出数字/多个"
                    "呈现指标（「条数与占比」）= 一项的产出枚举，不算复合——**即便"
                    "二者对应不同输出维度、不同指标口径、不同 SC ID，仍属同一呈现"
                    "决策的产出枚举，不得据此判复合或要求拆项**；一项 text 内"
                    "「在何处呈现」（呈现位置/载体）与「呈现什么」（指标/数字）"
                    "是同一呈现决策的两个成分，**不得以「呈现位置决策与呈现指标"
                    "决策可分别拍板」为由判复合**；同一决策的范围正反"
                    "表述（「限定为既有区块内的两个数字，不新增图表或独立报告页」）"
                    "= 边界界定，不算复合；字段内枚举多个被否候选及各自理由 = "
                    "字段键值枚举，不算复合。**本方框只判单项 text 内部是否合并"
                    "多个决策——不同 statements 项之间的关系（两项是否可合并/是否"
                    "重复/是否应重新拆分）不在本方框判面内，不得以「项1 与项2 合并"
                    "了可独立拍板的决策/两项应拆为其它切法」为由 block。**\n"
                    "三、凭空新增子4 未评估的要素：某项引入子2 候选集/子3 核验/"
                    "子4 矩阵全程未出现的新要素（新模块/新依赖/新数据结构）判 "
                    "block。合法形态=排除性/否决性表述（「不新增 X」「被否形态=X」）"
                    "是边界与 ADR 记录、不是新增要素，不得以「『不新增图表』/"
                    "『被否形态=新增独立报告页』属凭空新增要素」为由 block；"
                    "rejected 字段可记录候选集之外的被否路径（如子3 重复造轮子"
                    "检查隐含的「自行实现」替代、子4 双向追溯判为镀金而排除的"
                    "形态），不得以「该被否路径在子3/子4 无对应候选记录/未做过"
                    "候选评估」为由 block。\n"
                    "四、假设淡化（置信度×影响丢失）：子3 三态标注的假设在本步 "
                    "assumptions 被抹去置信度或错误时影响后果判 block（「小风险，"
                    "可忽略」式定性淡化=淡化）。合法形态=置信度×影响原样携带或"
                    "语义等价转述即合规；假设随其所属候选被否而退出、并显式声明"
                    "「本方案无待接受假设」= 合法形态，不得要求为被否候选的假设"
                    "保留待裁状态——**子4 记「该假设是否接受留子6 裁决」是子4 的"
                    "待裁点声明，本步以「随候选被否退出/本方案无待接受假设」表述"
                    "即合规，不得以「属待裁悬挂态、本步不得声明其退出」为由 "
                    "block**；**某项 assumptions 写「无」并附已核实出处（如"
                    "「复用点经 codegraph + Read 双核实」）= 合法形态**——子3 标为"
                    "可行的内容不须被改写成假设，不得为已核验项虚构潜在风险、"
                    "不得以「未列出该项可能失败的情形/未列潜在风险」为由 block；"
                    "不要求假设逐字复刻子3 全文。\n"
                    "五、否决理由（ADR）传导已由 rejected_rationale_trace 机械"
                    "校验——rejected 字段只列被否候选名单/被否形态名而完全不含"
                    "任何「为何被否」说明的载荷已被 append-trace 当场拒、不会到"
                    "你这里；你不得以「rejected 只列名单/未附否决理由/理由缺失」"
                    "为由 block。残留判面=理由与子3/子4 已定结论矛盾（归方框一）。"
                    "理由来源与粒度均不限——引子3 核验事实、子4 Pugh 净分、硬规则"
                    "触发、影响面、复用度、双向追溯判为镀金、重复造轮子检查结论，"
                    "以上任一项或其它任何解释性说明均算理由，不得以「该理由不属"
                    "判据列举的合法理由源/理由不够详细/未附出处行号」为由 block；"
                    "rejected 显式「无」（本项无被否路径）即合规。\n"
                    "【判材边界】本步 input=step4.recommendation，子1-子4 trace "
                    "载荷内可见——字段传导可判。八字段非空已由 append-trace 逐键"
                    "校验，不得以「缺键/字段为空」为由 block。text 实现侧名词已由"
                    "机械扫描，不得以「text 含报告/区块/百分比/呈现形态类 outcome "
                    "载体名词」为由 block——载体名词是 outcome-level 的合法约束"
                    "成分。must 目标与验收包 SC ID 属 GoalsAndValue／SuccessCriteria "
                    "节点、结构性不在本载荷内，不判 acceptance_map 的 SC ID 真实性/"
                    "是否全覆盖——**不得以「该 SC ID 在本载荷别处未出现/编号不"
                    "连续/无法核实其存在/该 SC 应由其它项承接/某项承接关系不当」"
                    "为由 block**；acceptance_map 字段有内容即合规。"
                    "codegraph db 不可见，不核 callers/impact 数字真伪。"
                    "子4 条目 ID 传导覆盖与 rejected 否决理由在场性均已由 "
                    "append-trace 机械校验。boundary 字段含实现指针/file:line 是"
                    "判据规定的去处，不得因此判 text 违规。\n"
                    "【合法正例】「text: 正 IC 因子的条数与占比在既有摘要报告的 IC "
                    "区块内直接可读出」合规（同一决策的两个输出数字非复合，载体"
                    "名词合法）；「text: 呈现形态限定为既有报告区块内的两个数字，"
                    "不新增图表或独立报告页」合规（范围正反表述=边界界定，非复合"
                    "亦非新增要素）；「callers: codegraph callers 输出 1 个调用方 "
                    "X；codegraph impact 输出 3 个受影响符号」合规（两类输出同栏"
                    "携带）；「rejected: 候选B 被否——理由=子3 核验其跨 2 文件触发 "
                    "H8 且不复用既有实现，子4 净分 −2；候选C 被否——理由=impact 7 "
                    "符号跨两模块、需 schema 迁移，净分 −5」合规（逐候选附理由，"
                    "字段内枚举不算复合）；「rejected: 被否形态=新增独立图表或独立"
                    "报告页——理由=子4 backward 双向追溯该要素回溯不到 must 目标="
                    "镀金项」合规（ADR 记排除形态，非新增要素）；「assumptions: "
                    "候选C 的接缝为假设（置信度中×影响：改动面扩到 5+ 文件、H9 需"
                    "分解——子3 原样转录）；该假设随候选C 被否不进入本方案，本方案"
                    "无待接受假设」合规；「assumptions: 无（复用点经 codegraph + "
                    "Read 双核实，子1/子3 出处）」合规（已核实项无须虚构假设）；"
                    "「rejected: 被否路径=自行实现百分比格式化——理由=子3 重复造"
                    "轮子检查确认既有实现在册」合规（候选集外的被否路径可记）。"
                    "方框以外一律不判。judge 判 block 须在 reason 引用判据条款并附 "
                    "1 个正确改写范例（指模式不指实例位置）。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem / AskUserQuestion / render-artifact(design.md)",
                short="读回确认",
                interactive=True,
                # 带证据读回（同构 ProblemContext 子7）：只给结论不给依据地「通知」
                # 用户 = 无依据确认；design.md 装配 = render-artifact 脚本装配
                # （v2.62，同 understand.md/plan.md）。
                purpose=(
                    "带证据读回与产物装配：材料 = 运行 `python3 ~/.dl-workflow/dl_flow_engine.py render-readback` 机械装配逐字呈现（本节点归一化+假设/不确定性 traces，禁手抄；Bash 输出即呈现）。呈现内容 = 推荐方案+设计包+被否方案+假设清单"
                    "+不确定性；用户三裁决——①选型拍板（唯一规范裁决点，"
                    "含复活被否方案的合法权利，矩阵只是输入）；"
                    "②评估权重认可（Pugh 单人权重偏见防御）；"
                    "③假设接受（风险承担）；"
                    "拍板后装配 design.md = 运行 `python3 ~/.dl-workflow/dl_flow_engine.py "
                    "render-artifact design.md --slug <主题>`（脚本从子5 归一化设计包"
                    "statements+裁决 trace 机械装配，落主仓 designs/<主题>-design.md；"
                    "slug 命名归你（kebab 简洁主题名），装配归脚本——禁手写产物文件；"
                    "已存在拒覆盖，state-reset 重跑加 --force）；"
                    f"{_INTERACTIVE_CHUNKING_RULE}；"
                    f"{_USER_DECISION_RECORD_RULE}-> STEP_DONE。"
                ),
                input="step5.design_statements",
                record=True,
                selfcheck=(
                    "呈现了推荐方案+设计包+被否方案+假设清单+不确定性吗？"
                    "用户对选型/权重/假设三项裁决都记入 trace 了吗？"
                    "design.md 已用 render-artifact --slug 装配了吗（禁手写产物）？"
                ),
                # v2.45 交接架构正确性前提：用户裁决必入 trace（gate=None 无 judge，
                # 机械校验是唯一防线）。
                mech_checks=("user_decision_recorded",),
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
        # ARTIFACT_CONTAINS（2026-08-02 升，artifact-handoff-hardening-design）：
        # 本节点装配「执行步骤」节（phase-rules 装配行给逐字节名）——
        # 存在性+新鲜度之上补节存在检查，execute 首步读 plan.md 的消费契约锚点。
        gate_mech=GateMech.ARTIFACT_CONTAINS,
        artifact_contains=(_S_EXEC_STEPS,),
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
                # v2.102（designs/plan2-sub1-gate-framing-design.md）：要素原文
                # 引用留痕生产墙（v1 重放 vio4 2/6 掉牙——judge rubber-stamp
                # 放过无『』原文引用的要素）。纯 token 扫描，⑯-safe。
                mech_checks=("element_quote_trace",),
                selfcheck=(
                    "三清单都齐了吗（要素/验收包/假设）？要素 ID 连续编号了吗？"
                    "每条都附出处且要素原文引用进 trace 正文了吗"
                    "（judge 读不到 design.md 文件本身）？"
                    "新增候选/矛盾显式标注或显式「无」了吗？"
                    "有静默新增设计包没有的要素吗（那是二次创作）？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=TaskBreakdown 且 sub_step==1 的记录。"
                    f"形式要件：{_TB_STEP1_FORM_REQUIREMENTS}。\n"
                    "默认 pass——仅当以下成立才判 block（每条附合法形态，"
                    "合法形态在场不得判）：\n"
                    "一、要素来源自证不足（编造/静默新增）：要素清单条目"
                    "（file→function→改动类型形）声称提取自 design.md，却既无出处"
                    "（design.md 行号 / evidence 指针 / 原文『』引用）又未显式归入"
                    "「新增候选」区判 block。两种违规形态：(a) 全清单裸=编造"
                    "（「应该都在 design.md 里，按常规路径可查」类凭印象，无任何"
                    "出处/原文引用）判 block；(b) 个别条目裸且未标新增候选=静默"
                    "新增二次创作（a[3] 声明「新增候选：无」但清单含「新增/新建/"
                    "独立脚本」措辞条目，如 `scripts/category_summary.py` 新增独立"
                    "脚本）判 block。合法形态=design.md 行号 / evidence 指针 / "
                    "『原文』引用 任一在场即合规；「新增候选」区显式列出条目（含"
                    "待子5 用户裁决语义）即合规；改动类型「增」（新增路径常量/"
                    "分组键）不是新增候选信号——不得以「有『增』态条目」推断二次"
                    "创作。\n"
                    "二、改写失真（语义偏移）：要素自述措辞与 trace 内引用的 "
                    "design.md 原文『…』明显语义冲突判 block。判 block 须逐要素"
                    "对照——每条款引用了原文『…』的要素，把原文与自述措辞对比："
                    "改动范围（既有函数内/新增文件）、改动性质（增加分组键/重写"
                    "聚合器）、产出物（新增分组输出/全新数据结构）三者任一明显"
                    "变化=改写失真（原文「在既有聚合统计函数内增加分组键」vs 自述"
                    "「重写为独立八维度聚合器，输出全新数据结构」）判 block。合法"
                    "形态=措辞是对原文的忠实提取/适度压缩即合规，不要求逐字一致"
                    "（「增加分组键」转述为「加维度分组」类语义等价转述合法）——"
                    "细节省略/语序调整/同义替换不判，改动范围/性质/产出物未变化"
                    "不判。\n"
                    "三、要素原文未引用：已由 element_quote_trace 机械校验——要素"
                    "清单条目引用了代码符号形（.py）却无任何『』原文引用/『原文』"
                    "字样的答案已被 append-trace 当场拒、不会到你这里；你不得以"
                    "「要素原文未引用/无原文/无法核对原文」为由 block。残留判面="
                    "验收包/假设是否附出处行号（design.md:N 或「原样转录 design.md:N」"
                    "标注）——缺则 block；验收包/假设只需行号+简短描述即合规，"
                    "不得要求贴原文全文。\n"
                    "【判材边界】本步 input=designs/<主题>-design.md（主仓 .md "
                    "文件）+ DesignSolution 前步 trace——evidence 只含 TaskBreakdown "
                    "段，两者 judge 结构性读不到。不得以「未见 design.md 原文/无法"
                    "核对出处行号真实性/无法确认某要素是否真在设计包/无法核对验收"
                    "包假设与 design.md 一致」为由 block；本步只判 trace 内自洽 + "
                    "留痕形式。\n"
                    "【合法正例】「出处 design.md:12，原文『在既有聚合统计函数内"
                    "增加 FACTOR_CATEGORIES 维度分组键，复用 factor_definitions.py "
                    "映射做 group key』」合规（原文片段引用即可）；「SC1.1『报告展示"
                    "八维度条数+占比可读出』（design.md:20）」合规（验收包有行号+"
                    "简短描述即满足）；「H1=…（置信度中×影响中，原样转录 "
                    "design.md:25）」合规（假设原样转录+行号标注即满足）；「新增"
                    "候选：显式『无』」+ 清单无新增措辞条目合规。方框以外一律不判。"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例"
                    "（指模式不指实例位置）。"
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
                # v2.104（designs/plan2-sub2-gate-framing-design.md）：三 mech 承接
                # default-PASS judge 判不稳的判据--dependency_order_trace（排序跨参照
                # ㊻ 系统性放行）/ element_coverage_trace（要素跨步跷跷板⑤）/
                # single_phase_argument（②负判定缺席㊳）。纯 token 扫描，⑯-safe。
                mech_checks=(
                    "dependency_order_trace",
                    "element_coverage_trace",
                    "single_phase_argument",
                ),
                selfcheck=(
                    "每单元都附 H9 预算+承接要素 ID+依赖出处了吗？"
                    "DAG 排序留痕了吗（被依赖者先行）？TDD 序内嵌了吗？"
                    "每阶段附断点验证方法了吗（或②论证留痕）？"
                    "要素 ID 覆盖无漏吗？是「提案-待用户裁决」语义吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=TaskBreakdown 且 sub_step==2 的记录。"
                    f"形式要件：{_TB_STEP2_FORM_REQUIREMENTS}。\n"
                    "默认 pass--仅当以下成立才判 block（每条附合法形态，"
                    "合法形态在场不得判）：\n"
                    "一、横向按层切无显式辩护：单元按架构层（数据层/逻辑层/表现层/"
                    "数据适配层等）横向切分却无显式辩护（为何不纵向切片的论证）判 "
                    "block。合法形态=纵向切片（每单元端到端自带完整测试周期）即合规；"
                    "横向切分附显式辩护即合规；自述「纵向切片/非横向按层切」即合规--"
                    "不得以「单元分布在不同文件/不同模块=按层切」重新判定为横向"
                    "（单元分属不同文件是纵向依赖链的常态，非横向按层切的判据）。"
                    "不得索取「为何不能纵向切」的代码级证明。\n"
                    "二、排序违反依赖：声明的依赖关系与拓扑序方向矛盾判 block。检测："
                    "从答案提取所有「X 依赖 Y」声明，再读拓扑序排列，逐对核对--凡 X "
                    "依赖 Y，Y 须排在 X 前；若 Y 排在 X 后（被依赖者落后）判 block。"
                    "例：声明「U3 依赖 U2、U2 依赖 U1」却拓扑序「U3->U2->U1」=被依赖者"
                    "排后判 block。合法形态=被依赖者先行（U1->U2->U3）即合规。判面="
                    "trace 内声明依赖与拓扑序方向自洽，不核 db 实际依赖真实性"
                    "（判材边界）。\n"
                    "三、单元超 H9 预算无继续拆：单元自报 H9 预算超 ≤3 文件或 ≤200 行"
                    "且无继续拆表述判 block。合法形态=预算 ≤3 文件 ≤200 行即合规；超限"
                    "但附继续拆方案即合规。预算是模型估计值，judge 不复核预算是否含测试"
                    "行数/是否准确/是否该继续拆--不得以「30 行未含测试/应继续拆」为由"
                    " block。\n"
                    "四、要素 ID 覆盖有漏：S1 元素基线清单的某要素 ID 在 S2 无任何单元"
                    "承接判 block。逐项核对：从前序子1 要素清单取出每个要素 ID（如 "
                    "E1/E2/E3），确认其在 S2 出现（单元承接映射「E->U」或「承接 E」任一"
                    "形态）；S2 自称「全覆盖」不替代逐项核对--只列出部分要素 ID 却称全"
                    "覆盖判 block。合法形态=每个 S1 要素 ID 均在 S2 列出承接映射即合规"
                    "--「E1->U2、E2->U3、E3->U1」式覆盖清单（每个 S1 要素 ID 均列出）"
                    "即合规，不要求每单元行内重复「承接 E」标注、不要求覆盖核对单独"
                    "成段。\n"
                    "五、单阶段无论证：声明「单阶段/不可拆」却无「H9 内一次可完」量化"
                    "论证（含文件数与行数，≤ H9 上限）判 block。合法形态=多阶段划分附"
                    "断点验证方法即合规（走另一分支，不需②论证）；单阶段附 H9 量化论证"
                    "（文件数+行数）即合规。\n"
                    "六、替用户拍板断点：断点位置以定案口吻陈述（「断点设在/定在 X 后」"
                    "「已确定断点」）无「提案-待裁决」语义判 block。阶段粒度（单阶段/"
                    "多阶段/两阶段）是模型提案、用户子5 可要求合并/拆细/重排--自述"
                    "「单阶段」或「两阶段」作为划分提案不属拍板，不得以「单阶段未挂提案"
                    "标签」为由 block。合法形态=断点位置「提案/待子5裁决/候选」语义任一"
                    "在场即合规；断点验证方法具体即合规--不得以「断点方法太具体不算"
                    "提案」为由 block。\n"
                    "【判材边界】本步 input=step1.element_baseline（S1 trace，载荷内"
                    "可见）+ codegraph db 真值（结构性不可见）。S1 可见->要素 ID 覆盖"
                    "可判；codegraph db 不可见->依赖真实性只判留痕在场（声明依赖+查询"
                    "命令+返回概述），不核 db 实际调用关系，不得以「U2 实际不依赖 U1/"
                    "二者无实质依赖/依赖理由不成立」为由 block；H9 预算是模型估计->不"
                    "复核准确性/含测试行数；②单阶段不可拆论证=文件数+行数量化在场即"
                    "合规，judge 不复核论证是否充分/合计是否算论证/单阶段是否真不可拆；"
                    "完整测试周期=failing test 先行即合规（form 要件），不得要求「通过"
                    "测试+验证闭环」逐项展开；字段⑧是设计包内部字段（judge 读不到设计"
                    "包），不得以「未声明字段⑧精化不重做」为由 block；codegraph 留痕="
                    "查询命令+返回概述即合规，不得索取输出原文/节点 ID/命令完整回显。\n"
                    "【合法正例】「codegraph callers _aggregate_positive_ic 确认 U2 改动"
                    "点被依赖方无遗漏」合规（命令+概述即满足，不贴输出原文）；「U2 依赖 "
                    "U1（消费 CATEGORY_SUMMARY_RESULT）」合规（声明依赖即满足，不核 db "
                    "真实性）；「U2 H9 预算 1 文件 ~30 行」合规（估计值即满足，不索测试"
                    "行数）；「TDD：U1 先写断言常量存在的失败测试」合规（failing test "
                    "先行即满足）；「②单阶段不可拆论证：三单元合计 3 文件 ~75 行，H9 内"
                    "一次可完」合规（量化在场即满足，不核论证充分性）；「要素 ID 覆盖"
                    "核对：E1->U2、E2->U3、E3->U1」合规（每个要素 ID 列出映射即满足）；"
                    "「单阶段（三单元同属一纵向切片）」合规（阶段粒度提案即满足，不挂"
                    "提案标签亦合规）；「断点验证方法（提案）：阶段末跑...+断言...（待"
                    "子5 用户裁决）」合规（提案语义+具体方法即满足）。方框以外一律不判。"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例"
                    "（指模式不指实例位置）。"
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
                # v2.108（designs/plan2-sub3-gate-framing-design.md）：假设条目置信度+影响
                # 生产墙（v1-v3 judge 橡皮图章 1-5/6，⑭ 注意力方差，同 plan:2#1 vio4/plan:2#2 vio5
                # 型）。纯 token 扫描假设标签形，⑯-safe。
                mech_checks=("assumption_completeness_trace",),
                selfcheck=(
                    "每单元四类核验都做了吗（文件/symbol/测试接缝/命令/placeholder，"
                    "无遗漏）？三态逐单元标注了吗？"
                    "已验证附出处、假设含置信度+错误时影响、证伪附理由了吗？"
                ),
                gate=(
                    """evidence/<name>.jsonl 含 kind=skill-trace、minor_stage=TaskBreakdown 且 sub_step==3 的记录。
形式要件：每单元四类核验留痕（④No Placeholders 检出可逐单元或全局汇总声明，不须逐单元独立列出）；三态按单元标注（单元整体标已验证/假设/证伪覆盖该单元核验项，不须逐类别拆标、不须声明无假设/证伪）；出处/置信度+影响/理由齐备。
默认 pass——仅当以下成立才判 block（每条附合法形态，合法形态在场不得判）：
一、声称存在无出处=编造：单元声称目标文件/symbol 存在或验证命令可运行，却无任何出处留痕判 block。违规形态：(a) 口头声称「存在/可以直接改/可以加断言/可以跑」无任何命令出处（如「`_aggregate_positive_ic` 函数就在里面，可以直接改」全段无一条命令）；(b) 四类核验整段概括复述「文件/symbol 存在、测试接缝存在、命令可运行」无任何单元特定命令。合法形态=出处留痕在场即合规——Bash 命令+返回概述（`test -f X && echo EXISTS` 返回 EXISTS / `pytest --collect-only -q` 返回 N 个用例）、codegraph 查询命令+返回概述（`codegraph callers Y` 返回 N 个调用节点）、grep 命令+返回概述任一形态即合规；不得索取命令输出原文/完整回显/行号/节点 ID。
二、全单元无差别「已验证」=没真核验：所有单元三态全部标「已验证」且核验留痕同形泛化（各单元文本仅复述「存在/可运行/无问题」套话，无单元特定命令/路径/返回数字）判 block。合法形态=单元级差异化留痕（每单元各自的命令+返回概述）即合规；多数单元已验证+个别假设项即合规；全部单元已验证但每单元附各自命令出处即合规——不得以「没有假设/证伪项」本身判 block，无证伪项不须声明「无证伪」。三态按单元标注即合规（单元整体标「已验证」覆盖该单元全部核验项），不须逐类别/逐项拆标三态，不须声明「无假设/无证伪」即完整三态--已验证单元不因「未逐项拆标/未声明无假设证伪」判 block。
三、placeholder 模式残留：单元内容或步骤描述含「加适当错误处理」「处理边界情况」「写上述的测试」「类似任务 N」占位措辞判 block。合法形态=No Placeholders 检出声明（扫描四模式+零命中）即合规——检出声明不须附扫描命令/逐模式回显，不得以「零命中无扫描留痕」为由 block。④No Placeholders 检出可逐单元或全局汇总声明（「逐单元扫描四模式零命中」式总声明）即合规，不须逐单元独立列出④条--不得以「某单元段内无独立④留痕」为由 block。
四、假设项缺置信度或影响：已由 assumption_completeness_trace 机械校验--标注「假设」的条目（假设标签形：假设后接 --/：/（ 等结构化标点）无置信度或错误时影响已被 append-trace 当场拒、不会到你这里；你不得以「假设缺置信度/影响/影响面不具体/可回滚是恢复手段非影响面」为由 block。残留判面=假设标签形以外的假设提及（如「假设项」「无假设」）是否明显矛盾--只判明显矛盾，不主动索要素、不复核影响面具体化程度。
五、漏单元核验：子2 单元集中某单元在本步无任何四类核验留痕，被「随 X 覆盖/同 X 已验证」一句话代过判 block。合法形态=每单元独立核验段（四类各自留痕）即合规；某类核验对该单元不适用（如新增常量无既有 symbol 可查）附声明即合规。
【判材边界】本步 input=step2.task_units+step1.element_baseline（S1/S2 trace 在载荷内可见）+ codegraph db/文件系统真值（结构性不可见）。只判留痕在场与 trace 内自洽，不核真值——不得以「文件是否真存在/symbol 是否真在/命令是否真能跑/返回数字是否真实」为由 block；验证命令以 `--help`/collect-only/干跑留痕即合规，不得索取真跑单测/断言闭环/最小运行；新增常量/文件的命名冲突核验以 grep 命令+返回概述即合规，不得索取「先 grep 命名空间再声明存在」的特定顺序；三态=逐单元标注已验证/假设/证伪即合规，不得以「缺证伪分支/未声明无证伪」判 block；前步（子1/子2）的假设/断点验证方法在本步无重述义务，不得以「H1 未重述置信度/断点未复核」判 block；假设条目（三态标注中的假设态）的内容是假想陈述、非已验证事实，不须附出处/证据--不得以「假设内容断言无出处/假设描述无证据/『不破坏』类断言无核验」判 block（假设的置信度+影响字段已由 assumption_completeness_trace 机械校验）。
【合法正例】「①文件存在--Bash `test -f .../paths.py && echo EXISTS` 返回 EXISTS」合规（命令+返回概述即满足）；「symbol `_aggregate_positive_ic` 存在--Bash `codegraph callers _aggregate_positive_ic` 返回 3 个调用节点」合规（查询命令+概述即满足，不核 db 真值）；「②测试接缝存在--`pytest --collect-only -q` 返回 12 个用例」合规；「③验证命令可运行--`python3 scripts/x.py --help` 返回 0」合规（干跑留痕即满足，不索真跑）；「新增常量无既有 symbol 可查，命名冲突核验--`grep -n X paths.py` 返回空」合规（声明+grep 留痕即满足）；「假设--插入新区块不破坏既有布局（置信度高×影响低：错误时仅新区块缺失，可回滚）」合规（置信度+影响在场即满足）；「No Placeholders 检出：逐单元扫描四模式，零命中」合规（声明即满足，不索扫描回显）。方框以外一律不判。
judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例（指模式不指实例位置）。"""
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem(归一化) / superpowers:writing-plans(Task Structure 形式真源)",
                short="归一化步骤",
                # claim normalization 职能第七次复用（ProblemContext 子6 /
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
                # v2.109（designs/plan2-sub4-gate-framing-design.md）：sc_coverage_trace
                # 承接 default-PASS judge 判不稳且与 clean 误伤跷跷板的跨步判据
                # （验收包映射漏项=子1 验收包 SC ID vs 子4 acceptance_map 差集，
                # 强措辞伤 clean[judge 发明映射归属要件]/弱措辞漏判 vio4=⑤ 实锤）。
                # statements 侧首个 mech（u:2#4 预留独立项 #30 ⑰ 的解）。纯 token 扫描，⑯-safe。
                mech_checks=("sc_coverage_trace",),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=TaskBreakdown 且 sub_step==4 的记录。"
                    "形式要件：每项 = 1 个可独立验证/提交的交付物"
                    "（TDD 微循环「失败测试→最小实现→验证→提交」= 内含流程，不算复合）；"
                    "fields 五键齐备（append-trace 已机械校验，勿再数字段）；"
                    "验收包覆盖=子1 每个 SC ID 至少一项 acceptance_map 承接，"
                    "要素覆盖=每项 trace_anchor 至少一项承接。\n"
                    "默认 pass——仅当以下成立才判 block（每条附合法形态，"
                    "合法形态在场不得判）：\n"
                    "一、验收包映射已由 sc_coverage_trace 机械校验——子1 验收包 SC ID "
                    "在子4 无任何项 acceptance_map 承接的载荷已被 append-trace 当场拒、"
                    "不会到你这里；你不得以「验收包映射漏项/SC X 未承接/验收包覆盖不全」"
                    "为由 block。残留判面=无（覆盖已机械核验）；acceptance_map 归属/"
                    "语义合理性本就不判——同一 SC 被单单元或多单元承接均合规，"
                    "个别单元「无直接验收包承接」是合法形态（不要求每单元都映射 SC）。\n"
                    "二、字段与子2/子3 已定内容不一致（丢失/篡改/新增）：某项 "
                    "change_point/interface/verify 与子2 单元定义或子3 锚点核验结果"
                    "矛盾判 block。两种违规形态：(a) 篡改——措辞与子2/子3 已定内容"
                    "语义冲突（子2「增加分组键」vs 子4「重写为独立八维度聚合器，输出"
                    "全新数据结构」）判 block；(b) 丢失/新增——子2/子3 已定的改动点/"
                    "接口/验证命令在子4 缺失，或混入子2/子3 未定的内容判 block。"
                    "合法形态=对子2/子3 内容的忠实提取/适度压缩/同义转述即合规，"
                    "不要求逐字一致（「增加分组键」转述为「加维度分组」类语义等价"
                    "转述合法）——语序调整/同义替换/细节省略不判，改动范围/性质/"
                    "产出物未变化不判；子3 假设项原样携带（不丢不淡化，量化范围与"
                    "置信度×影响原样保留）即合规。\n"
                    "三、复合句（未原子化）：一项 text 合并 ≥2 个可独立成立/可分别提交"
                    "的交付物判 block。检测：提取 statements 每项 text，凡 text 以"
                    "「以及/同时/并且」等并列连接词连接两个可独立成立、可分别验证/提交"
                    f"的交付物（各自含独立动作与独立交付物）判 block。{_ATOMIC_ITEM_RULE}。"
                    "合法形态=TDD 微循环「失败测试→最小实现→验证→提交」=交付物内含"
                    "流程，不算复合；acceptance_map 列多个 SC ID / interface 列 "
                    "Consumes+Produces=字段键值枚举，不算复合。\n"
                    "四、验证方法不可执行且无辩护：verify 字段写「人工看一下/检查一下」"
                    "式不可执行验证且无显式辩护判 block。检测：逐项读 verify 字段，"
                    "凡 verify 只含「人工看/肉眼/检查一下/目测」类非机械验证且无显式"
                    "辩护（为何无法写成命令/断言）判 block。合法形态=failing test 名+"
                    "命令+期望输出（可执行验证优先）即合规；命令+期望退出码即合规；"
                    "不可执行验证附显式辩护即合规——不得以「验证不够详细/未含期望输出"
                    "全文」为由 block。\n"
                    "【判材边界】本步 input=step3.verified_units + step1.element_baseline"
                    "（子1/子2/子3 trace 载荷内可见）——字段一致性可判。fields 五键非空"
                    "已由 append-trace 机械校验，不得以「缺键/字段为空」为由 block。"
                    "TDD 微循环=failing test 先行即合规，不得要求通过测试闭环展开。"
                    "acceptance_map 列多个 SC ID/interface 列 Consumes+Produces=字段"
                    "枚举不算复合。verify 只判本单元交付物可执行验证，不得以「未覆盖"
                    "下游消费/验证范围不充分」为由 block。验收包映射已由 sc_coverage_trace "
                    "机械核验，不得以「映射错位/SC X 应由 U Y 承接/某单元未映射 SC」"
                    "为由 block。design.md 跨阶段文件结构性读不到但子1 已提取验收包/"
                    "要素为载荷内清单，不得以「无法核验收包与 design.md 一致/要素是否"
                    "真在设计包」为由 block。codegraph db 不可见，不得以「无法核实 "
                    "symbol 真实调用关系」为由 block（子3 已留痕即合规）。\n"
                    "【合法正例】「acceptance_map: SC1.1、SC2.1」合规（多 SC ID 枚举"
                    "不算合并）；「acceptance_map: SC3.1（直接渲染区块）」+另项"
                    "「（无直接验收包承接，为 U2/U3 提供输出路径基础）」合规（个别单元"
                    "「无」合法）；「change_point: paths.py:+CATEGORY_SUMMARY_RESULT（增）」"
                    "合规（忠实提取子2 单元定义）；「verify: failing test test_xxx "
                    "断言...；命令 pytest ...；期望失败->通过」合规（TDD 微循环内含流程"
                    "不算复合）；「trace_anchor: E1」合规（要素 ID 承接）；"
                    "「boundary: 假设 H1 传导：FACTOR_CATEGORIES 八维度对全 34 项因子"
                    "覆盖无遗漏（置信度中×影响中，原样转录 design.md:25）」合规"
                    "（假设原样携带，量化范围保留）。方框以外一律不判。"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例"
                    "（指模式不指实例位置）。"
                ),
            ),
            Step(
                kind="skill",
                ref="AskUserQuestion / Write(plan.md)",
                short="读回装配",
                interactive=True,
                # 带证据读回（同构 DesignSolution 子6）：只给结论不给依据地「通知」
                # 用户 = 无依据确认；plan.md 装配 = 子4 执行步骤+裁决记录的直接
                # 装配（禁二次创作，同 understand.md/design.md 装配原则）。
                purpose=(
                    "带证据读回与 plan.md 装配：材料 = 运行 `python3 ~/.dl-workflow/dl_flow_engine.py render-readback` 机械装配逐字呈现（本节点归一化+假设/不确定性 traces，禁手抄；Bash 输出即呈现）。呈现内容 = 阶段划分+任务序列+五字段摘要"
                    "+假设清单+新增候选（子1 检出若有）+不确定性；"
                    "用户两裁决——①阶段/粒度拍板（本节点唯一规范裁决点，"
                    "含要求合并/拆细/重排阶段的合法权利，断点位置是用户风险偏好）；"
                    "②假设接受（风险承担）；"
                    "拍板后装配 plan.md = 运行 `python3 "
                    "~/.dl-workflow/dl_flow_engine.py render-artifact plan.md`"
                    "（脚本从本节点归一化 statements+裁决 trace 机械装配本节，"
                    "落主仓 .claude/plans/<name>.md；禁手写产物文件——"
                    "内容要改就改对应步 trace 后重渲染）；"
                    f"{_INTERACTIVE_CHUNKING_RULE}；"
                    f"{_USER_DECISION_RECORD_RULE}-> STEP_DONE。"
                ),
                input="step4.execution_steps",
                record=True,
                selfcheck=(
                    "呈现了阶段划分+任务序列+假设清单+新增候选+不确定性吗？"
                    "用户对阶段粒度/假设两项裁决都记入 trace 了吗？"
                    "plan.md 是装配而非二次创作吗？"
                ),
                # v2.45 交接架构正确性前提：用户裁决必入 trace（gate=None 无 judge，
                # 机械校验是唯一防线）。
                mech_checks=("user_decision_recorded",),
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
        # ARTIFACT_CONTAINS（2026-08-02 升，artifact-handoff-hardening-design）：
        # 本节点装配「能力与工具」节。（2026-07-28「plan:4 是唯一 CONTAINS 节点」
        # 决议已被 2026-08-02 节标题单源化取代——当时否决理由是节名未单源
        # 会误 block，该前提已由 ARTIFACT_SECTIONS + 装配行逐字节名消除。）
        gate_mech=GateMech.ARTIFACT_CONTAINS,
        artifact_contains=(_S_CAP_TOOLS,),
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
                mech_checks=("need_quote_trace",),  # v2.106：方框三原文引用下沉生产墙
                selfcheck=(
                    "逐任务操作类型清单齐了吗（代码改动/测试/长 pipeline/检索/"
                    "数据读取/子代理/装配，无遗漏）？每条都附任务 ID 出处且 "
                    "plan.md 原文引用进 trace 正文了吗（judge 读不到 plan.md 文件本身）？"
                    "新增候选显式标注或显式「无」了吗？"
                    "有静默新增 plan 没有的需求吗（那是二次创作）？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、minor_stage=CapabilityToolSelection 且 sub_step==1 的记录。形式要件：逐任务操作类型需求清单齐备：每任务/阶段标注操作类型（代码改动[改 .py=H15 触发信号]/测试执行/长 pipeline[后台禁 pipe 信号]/外部检索/数据读取[parquet 等]/子代理扇出/文档装配）；每条附任务 ID 出处且 plan.md 原文引用进 trace 正文；新增候选（plan.md 没有的需求）显式标注或显式「无」，q/a 按序对齐；只提取不创作（本步是全节点保真判定基线）。\n"
                    "默认 pass——仅当以下成立才判 block（每条附合法形态，合法形态在场不得判）：\n"
                    "一、需求来源自证不足（编造/静默新增）：需求清单条目（任务 ID+操作类型形）声称提取自 plan.md，却既无出处（任务 ID+plan.md 行号 / 原文『』引用）又未显式归入「新增候选」区判 block。两种违规形态：(a) 全清单裸=编造（「按 plan.md 常规结构可知，应该都在执行步骤节里，按常规路径可查」类凭印象，无任何出处/原文引用）判 block；(b) 个别条目裸且未标新增候选=静默新增二次创作（「新增候选：无」声明下清单含无出处无原文引用的新增需求条目，如「跑 fresh 检查验证 PRICE_VOLUME 全量落库」类 plan.md 执行步骤节没有的需求）判 block。合法形态=任务 ID+plan.md 行号 / 『原文』引用 任一在场即合规；「新增候选」区显式列出条目（含待子6 用户裁决语义）即合规；「新增候选：无」声明+清单无新增需求条目即合规——不得以「无新增候选=可能漏检」为由 block。\n"
                    "二、改写失真（语义偏移）：需求自述措辞与 trace 内引用的 plan.md 原文『…』明显语义冲突判 block（N1 自述「重写 _aggregate_positive_ic 为独立分组引擎」vs 其引用的原文『在既有聚合统计函数内增加 FACTOR_CATEGORIES 维度分组键』= 操作对象从「既有函数内改动」变「独立重写」、操作性质从「增加分组键」变「重写引擎」、产出物从「修改既有函数」变「全新独立引擎」，三者任一明显变化=改写失真判 block）。判 block 须逐条对照——每条款引用了原文『…』的需求，把原文与自述措辞对比：操作对象（既有函数内改动/独立重写）、操作性质（增加分组键/重写引擎）、产出物（新增分组输出/全新模块）三者任一明显变化=改写失真判 block。合法形态=措辞是对原文的忠实提取/适度压缩/适度具体化即合规，不要求逐字一致（「增加分组键」转述为「加维度分组」类语义等价转述合法）——细节省略/语序调整/同义替换/适度具体化（原文「在既有聚合统计函数内…」自述点明函数名「`_aggregate_positive_ic` 内…」= 具体化非语义冲突）不判，操作对象/性质/产出物未变化不判。\n"
                    "三、需求原文未引用：已由 need_quote_trace 机械校验——需求清单条目引用了代码符号形（.py）却无任何『』原文引用/『原文』字样的答案已被 append-trace 当场拒、不会到你这里；你不得以「需求原文未引用/无原文/无法核对原文」为由 block。残留判面=无代码符号形的需求条目（如纯数据读取需求）是否附出处行号（plan.md:N 或「原样转录 plan.md:N」标注）或『』原文引用——缺则 block；『…』摘要包裹是合法引用形态（原文片段+省略号=引用非原文整体），不得以「『…』不是逐字完整引用」为由 block。\n"
                    "【判材边界】本步 input=plan.md（主仓 .md 文件）+ plan:2 TaskBreakdown 前步 trace——evidence 只含 CapabilityToolSelection 段，两者 judge 结构性读不到。不得以「未见 plan.md 原文/无法核对出处行号真实性/无法确认某需求是否真在 plan.md/无法核对操作类型分类正确」为由 block；本步只判 trace 内自洽 + 留痕形式。操作类型分类的语义正确性（如「报告数据读取」是否该归「测试执行」/「文档装配」）属子2 能力盘点判面——本步只判「操作类型标注在场」（每条需求有类型标注即合规），不得复核分类正确性/归属口径/标注粒度（「.md 数据读取」vs「数据读取[parquet 等]」类粒度差异不判）。操作类型清单=「每任务标注其实际涉及的操作类型」，不是「六类全谱系逐项有/无标注」——清单含 plan.md 任务实际涉及的类型即合规，plan.md 没有的类型（测试执行/长 pipeline/外部检索/子代理扇出/文档装配等）不要求显式「无」标注，不得以「缺测试执行类型标注/六类未全覆盖/其余类型未显式无」为由 block。\n"
                    "【合法正例】「N1=U2 代码改动（…增加 FACTOR_CATEGORIES 分组键，改 .py=H15 触发信号）--出处 plan.md:12，原文『在既有聚合统计函数内增加 FACTOR_CATEGORIES 维度分组键』」合规（任务 ID+行号+原文片段引用即满足，不要求整段）；「N3=报告数据读取（读取 IC_REPORT_DIR 下 default 管线报告做八维度核对，.md 数据读取）--出处 plan.md:14，原文『断点验证：断言报告含八维度汇总区块』」合规（数据读取需求引用断点验证段原文是合法出处——需求出处=plan.md 中承载该需求的段落，不限于同名字段；「.md 数据读取」粒度标注合规，不要求写成「数据读取[parquet 等]」标准形）；「新增候选：显式『无』」+ 清单无新增需求条目合规；清单只含代码改动/数据读取两类（plan.md 实际涉及的类型）合规，不要求六类全谱系逐项标注。方框以外一律不判。judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例（指模式不指实例位置）。"
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
                    # v2.105 gate framing 反转（§3.5 #30 泛化第二十二例，
                    # designs/plan3-sub2-gate-framing-design.md）：默认-PASS
                    # framing + 四方框近端双侧钉死（词形取基线 clean 1/6 的误判
                    # 判词逐字：逐任务四列表格/§2 触发词逐字原文/注册表逐项列
                    # 全表/codegraph 命令形/磁盘目录未点明条目）。v3 三向达标
                    # （clean 6/6、vio1/2 6/6、vio3/4 5/6），无 mech 下沉——方框三
                    # 负判定靠「检测：逐条检查」遍历指令救回（v1 仅给 block 面
                    # 描述崩 2/6）；v3 补「（列表行）是纯出处标注非功能描述」
                    # 与磁盘目录合法面（v2 生产复跑 clean 4/6 的两处误伤）。
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=CapabilityToolSelection 且 sub_step==2 的记录。"
                    f"形式要件：{_CTS_STEP2_FORM_REQUIREMENTS}。\n"
                    "默认 pass--仅当以下成立才判 block（每条附合法形态，合法形态在场不得判）：\n"
                    "一、幽灵能力：强制路由/绑定中引用的能力名（skill/工具/MCP）在 trace 自述注册表清单（①）或出处（②）中无对应条目判 block（例：路由加载 `factor-pool-optimizer` 但①清单与②出处均无此名）。合法形态=每个能力名附注册表出处（列表行/文件路径）即合规；注册表枚举可列主要条目+「等」表示即合规--不得以「未逐项列出会话 available-skills 全表/磁盘用户级·项目级目录逐文件清单/未逐字列出全部目录项/磁盘目录未点明具体有哪些条目」为由 block；磁盘目录只写目录路径（如 `~/.claude/skills/` 目录、`.claude/skills/` 目录）即合规，不要求列举目录内条目名。\n"
                    "二、强制路由漏核：代码改动任务（改 .py）的强制路由未列 H15 codegraph 留痕或 superpowers 触发（写代码前 TDD/任何编码 karpathy-guidelines 任一）判 block。任务集取前序子1（载荷内可见）逐任务核对路由覆盖，任务无路由行=漏配。合法形态=同类型任务合并说明（如「T1/T2/T3 代码改动→§2 命中加载 factor-development + H15 codegraph 留痕 + superpowers TDD/karpathy」+「T4 测试→无触发内置工具足够」）即合规--不得要求「任务→命中条款→留痕动作→加载skill」逐任务四列表格、不得要求逐任务逐条展开、不得要求 §2 触发词列表逐字引用原文。\n"
                    "三、凭记忆编造：能力功能描述出现却无 SKILL.md/listing 出处引用（只写功能不写出处）判 block。检测：逐条检查①清单中每个能力条目，凡条目含功能描述性短语（「功能：…」「自动执行…」「…编排」「…计算」等描述该能力做什么的语句），该描述须在条目内或紧邻段附 SKILL.md/listing 出处（路径/文件名/列表行）；描述在场而出处不在=判 block。合法形态=只列能力名+注册表出处（列表行/路径）不写功能描述即合规；每个功能描述附 SKILL.md/listing 出处即合规--功能描述简洁转述即合规，不得索取 SKILL.md 全文逐字引用/目录逐文件列举。关键区分：「`X`（列表行）」「`X`=available-skills 列表行『X』」是纯出处标注不是功能描述，不触发本方框--本方框只在条目出现「说该能力做什么」的描述句（如「功能：自动执行 IC 计算与分层回测」「pipeline 数据流编排」）时才适用；括号内仅写出处来源（列表行/路径/frontmatter）一律合规，不得以「列表行后未跟 SKILL.md 路径」为由 block。\n"
                    "四、②无逐任务说明：②结论声称「内置工具足够/零 skill」却无逐任务归属说明（哪些任务绑定 skill、哪些内置足够），或②结论与强制路由实际绑定矛盾判 block。合法形态=②逐任务归属说明在场且与路由一致（绑定项+内置足够项，同类型任务合并）即合规--条件触发（如测试失败才触发 systematic-debugging）不属常驻绑定，②归属说明覆盖常驻绑定即可；「零 skill」是合法结论只要逐任务说明在场；不得以「未展开每个任务为何不用 skill 的理由深度」为由 block。\n"
                    "【判材边界】真实注册表（available-skills 列表/磁盘目录/MCP 配置/CLAUDE.md §2 原文）结构性不可见--只判 trace 内留痕在场与内部自洽，不得以「无法核实该能力真在注册表/该触发词真在 §2/会话 available-skills 列表未逐字呈现」为由 block；codegraph 留痕=声明查询动作（命令名或「先 codegraph 留痕」）即合规，不得索取具体命令形/原始输出回显；任务类型=以 trace 自述为准，不得以「测试执行实质涵盖写代码前 TDD 环节应命中 TDD 触发」为由 block。\n"
                    "【合法正例】「T1/T2/T3 均改 .py→§2 命中『开发因子/新增因子/IC脚本』→加载 factor-development；H15 改 .py 前 codegraph 留痕；superpowers 写代码前 TDD」合规（同类型合并即满足，不要求逐任务四列表格/触发词逐字原文）；「`factor-development`=available-skills 列表行」合规（列表行/路径即满足，不要求逐项列全表/磁盘逐文件，亦不要求列表行后再跟 SKILL.md 路径）；「磁盘用户级 `~/.claude/skills/` 目录、项目级 `.claude/skills/` 目录（factor-development 等四个项目 skill）」合规（目录路径+「等」即满足，不要求逐条列举目录内条目）；「改 .py 前 codegraph impact 查询留痕」合规（声明查询动作即满足，不索取命令原文回显）；「T1/T2/T3 代码改动→绑定 factor-development/test-driven-development/karpathy-guidelines；T4 测试→内置工具足够零 skill」合规（归属说明在场即满足）；「只列能力名+注册表出处，不写功能描述」合规（无功能描述即不触发方框三）。方框以外一律不判。judge 判 block 须在 reason 引用判据条款（方框一/二/三/四）并附 1 个正确改写范例（指模式不指实例位置）。\n"
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
                # v2.110（designs/plan3-sub3-gate-framing-design.md）：无绑定能力
                # 残留=跨步差集（S2 注册表①枚举 vs S3 出现集），judge 判不了
                # （显式遍历指令 1/6），下沉 binding_residue_trace 生产墙。
                mech_checks=("binding_residue_trace",),
                selfcheck=(
                    "双向追溯矩阵齐了吗（每需求有绑定或显式「内置足够」；"
                    "每能力绑定到需求，无无绑定能力残留）？"
                    "每条绑定附理由+子2 出处+被否替代了吗？"
                    "重型手段附成本辩护了吗？红队留痕或条件未触发声明了吗？"
                    "是「提案-待用户裁决」语义吗？"
                ),
                gate=(
                    # v2.110 gate framing 反转（§3.5 #30 泛化第二十七例，
                    # designs/plan3-sub3-gate-framing-design.md）：默认-PASS
                    # framing + 五方框近端双侧钉死（词形取基线 clean 2/6 的
                    # 误判判词逐字：子2 trigger/description 须逐字/重型手段
                    # 枚举扩面/被否替代须出处）。v1 五方框 clean 6/6+vio2-5
                    # 全 6/6 但 vio1 残留 1/6（显式跨步遍历指令也判不了），
                    # 差集形下沉 binding_residue_trace mech（同 plan:2#4
                    # sc_coverage_trace 根因）；v2 落地 vio1 0/6=设计内委托。
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=CapabilityToolSelection 且 sub_step==3 的记录；"
                    f"形式要件：{_CTS_STEP3_FORM_REQUIREMENTS}。\n"
                    "默认 pass--仅当以下成立才判 block（每条附合法形态，合法形态在场不得判）：\n"
                    "一、无绑定能力残留：已由 binding_residue_trace 机械校验——S2（能力盘点）注册表①枚举的能力名在本步无绑定且无不加载声明的载荷已被 append-trace 当场拒、不会到你这里；你不得以「无绑定能力残留/能力未映射/某能力未绑定」为由 block。残留判面=无（覆盖已机械核验）；能力适配性（该能力是否真适合该需求）本就不判，不得以「factor-development 是否真适合 IC 报告」类能力适配性为由 block。\n"
                    "二、绑定理由无出处=凭名字猜：某条绑定理由未引用子2 trigger/description 出处（子2 ③出处/available-skills 列表行『X』/触发词引用任一）判 block（例：绑定 `factor-development` 理由只写「最合适，负责 IC 计算与报告功能开发」无任何子2 出处）。合法形态=理由含子2 出处引用（含触发词引用或「子2 ③出处」字样）即合规，不要求逐字复述子2 的 trigger/description 全文；同类型任务合并一条理由即合规，不得以「未逐任务逐条展开理由」为由 block；内置工具足够项非绑定、不需理由与被否替代，不得以「内置足够项缺理由/被否替代」为由 block；被否替代只需在场（「被否替代=无」是合法形态）且不需出处，不得以「被否替代未引子2 触发描述作出处」为由 block。\n"
                    "三、强制项被非强制项替代且无辩护：强制项（S2 ③强制路由核对留痕的 H15 改 .py 前 codegraph 留痕、superpowers 写代码前 TDD 等）被非强制项替代且无任何辩护判 block（例：a3 称「H15 codegraph 留痕改为 grep 全局搜索替代，grep 用起来更顺手」且无辩护）。合法形态=强制项按强制绑定保留即合规；强制项替代附「该替代满足原强制意图」式辩护（如「grep 不提供符号级调用图、不满足 H15 门禁」）即合规；同类型任务合并说明强制项覆盖即合规，不得以「未逐项证明每个强制项为何不可替代/未对强制项逐条留痕」为由 block。\n"
                    "四、重型手段无成本辩护：绑定中重型手段（Workflow 多 agent/子代理扇出/长 pipeline 三类固定枚举）在场却无成本相称辩护判 block（例：T4 绑定 Agent 子代理扇出，仅写「并行可提速」，无相对直接 Bash 跑的成本/收益权衡）。合法形态=重型手段附成本相称辩护（成本/收益论证或「协调成本高于收益故不启用」式权衡）即合规；未绑定重型手段时声明「无 Workflow 多 agent/子代理扇出/长 pipeline，条件未触发」即合规，不得以「3 个 skill 叠加成重型组合」「codegraph CLI 三处本地查询算重型手段」为由 block——重型手段仅限三类枚举；不得要求对每个能力逐项声明非重型。\n"
                    "五、替用户拍板映射=无「提案-待裁决」语义：映射以定案/决定/已采用/据此执行口吻呈现、无提案语义判 block（例：末段写「映射已权衡定案：…据此执行」）。合法形态=映射以提案口吻呈现（含「提案/拟绑定/待子6 用户裁决/待拍板」任一）即合规，不得以「未逐条附『提案』字样/未逐条复述待裁决全文」为由 block——整段一句提案声明即覆盖全部绑定；双向追溯矩阵的『无漏/无残留/每需求有绑定/每能力绑定』类陈述是矩阵事实描述、非映射拍板决定，不得据此判无提案语义。\n"
                    "【判材边界】S1/S2（需求清点/能力盘点）trace 在载荷内可见、跨步对照可判；真实注册表（available-skills 列表/磁盘目录/MCP 配置/CLAUDE.md §2 原文）结构性不可见，不得以「无法核实该能力真在注册表/该触发词真在 §2」为由 block——能力名以 S2 trace 自述注册表为准；绑定理由的语义正确性（该能力是否真适合该需求）不判；内置工具集（Bash/Read/Edit/Write 等常驻能力）不在绑定面、不要求出现在映射中。\n"
                    "【合法正例】「T1/T2/T3 代码改动→绑定 `factor-development`（子2 ③出处『§2 触发词『开发因子/新增因子/IC脚本』命中』）…被否替代=候选『直接手写 pandas 聚合』无报告聚合规范承接，被否」合规（理由引子2 出处+被否替代在场）；「`factor-ic-analyzer-workflow`/`workflow-creation` 无绑定→显式不加载」合规（声明合并一句即满足）；「本需求集无 Workflow 多 agent/子代理扇出/长 pipeline 绑定，条件未触发，无需成本辩护」合规；「映射为提案，待子6 读回装配时用户裁决拍板，非定案」合规；「双向追溯矩阵：需求侧=每需求有绑定或内置足够，能力侧=每能力绑定或显式不加载，双向无漏」合规（矩阵事实描述）。方框以外一律不判。judge 判 block 须在 reason 引用判据条款（方框二/三/四/五）并附 1 个正确改写范例（指模式不指实例位置）。\n"
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
                mech_checks=("assumption_completeness_trace",),  # v2.112：假设
                # 置信度×影响下沉（跨节点复用 plan:2 子3 同款，vio3 judge 2/6）
                record=True,
                fence_allow=("Bash",),
                selfcheck=(
                    "每绑定四类核验都做了吗（skill 存在/CLI 可用/MCP 连接/环境前提，"
                    "无遗漏）？三态逐绑定标注了吗？"
                    "已验证附出处、假设含置信度+错误时影响、证伪附理由了吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、minor_stage=CapabilityToolSelection 且 sub_step==4 的记录。\n"
                    "形式要件：每绑定四类核验留痕（①skill 条目存在 ②CLI 可用 ③MCP 连接 ④环境前提；某类对该绑定不适用时附显式「不适用」声明即算该类留痕）；三态按绑定标注（绑定整体标已验证/假设/证伪覆盖该绑定核验项，不须逐类别拆标、不须声明无证伪）；已验证态附出处，假设态附置信度+影响，证伪态附理由（置信度+影响只对假设态要求，已验证态不须）。\n"
                    "默认 pass——仅当以下成立才判 block（每条附合法形态，合法形态在场不得判）：\n"
                    "一、声称可用无出处=编造：绑定声称 skill 条目存在/CLI 可用/MCP 已连/环境前提满足，却无任何出处留痕判 block。违规形态：(a) 口头声称「已装可用/版本没问题/db 也在/直接跑即可」无任何命令出处（如 codegraph CLI 绑定全段无一条 which/ls/test 命令）；(b) 四类核验整段概括复述「条目存在、CLI 可用、MCP 已连、环境前提满足」无任何绑定特定命令。合法形态=出处留痕在场即合规——Bash 命令+返回概述（`which codegraph` 返回路径、`ls X/SKILL.md` 返回该路径、`test -f X && echo EXISTS` 返回 EXISTS、`python3 -m pytest --version` 返回 pytest 8.3.2）、注册表列表行引用（会话 available-skills 列表行『X』）、配置文件 server 名引用任一形态即合规；不得索取命令输出原文/完整回显/行号，不得以「只 ls 磁盘路径未核注册表列表行」或反之为由 block（两种出处形态任一即合规）。\n"
                    "二、全绑定无差别「已验证」=没真核验：所有绑定三态全部标「已验证」且核验留痕同形泛化（各绑定文本仅复述「条目存在/CLI 可用/MCP 已连/环境前提满足/无问题」套话，无绑定特定命令/路径/版本号/返回值）判 block。合法形态=绑定级差异化留痕（每绑定各自的命令+返回概述）即合规；多数绑定已验证+个别假设项即合规；全部绑定已验证但每绑定附各自命令出处即合规——不得以「没有假设/证伪项」本身判 block，无证伪项不须声明「无证伪」；三态按绑定标注即合规（绑定整体标「已验证」覆盖该绑定全部核验项），不须逐类别拆标三态。\n"
                    "三、假设项缺置信度或影响：已由 assumption_completeness_trace 机械校验——标注「假设」的三态条目（假设标签形：假设后接 --/：/（ 等结构化标点）无置信度或错误时影响的答案已被 append-trace 当场拒、不会到你这里；你不得以「假设缺置信度/影响/置信度未数值化（0.9/百分比/区间）/影响未量化范围/未给回退命令或降级步骤/未给返工成本」为由 block。残留判面=假设标签形以外的假设提及（如「假设项」「无假设」）是否明显矛盾——只判明显矛盾，不主动索要素、不复核置信度与影响的具体化程度。另：置信度+影响只对假设态要求，已验证/证伪态不须附——不得以「已验证项未附置信度/影响」为由 block。\n"
                    "四、漏绑定核验：子3 绑定集中某绑定在本步无任何四类核验留痕，被「随 X 覆盖/同 X 已验证」一句话代过判 block。合法形态=每绑定独立核验段（四类各自留痕，不适用类附显式声明）即合规。\n"
                    "【判材边界】本步 input=step3.binding_proposals（S1/S2/S3 trace 在载荷内可见）+ 真实环境真值（PATH/磁盘文件/MCP 连接状态/venv 依赖，结构性不可见）。只判留痕在场与 trace 内自洽，不核真值——不得以「该 skill 是否真在磁盘/CLI 是否真可跑/返回值是否真实/MCP 是否真连上」为由 block；某类核验对绑定不适用时附显式声明即合规（skill 类绑定无 CLI/MCP 依赖、CLI 类绑定无 skill 条目、零 skill 绑定四类多不适用），不得以「不适用声明无出处/无留痕/未给核验命令」为由 block；④环境前提以命令+返回概述留痕即合规，不得复核核验充分性/覆盖面（不得索取 SKILL.md frontmatter 依赖项核验/脚本可执行性/venv 路径/API key 存在性/编辑工具依赖/其余依赖包等未留痕项）；只标注不裁决=假设项接受留子6 用户裁决，不得以「未裁决假设是否接受」判 block。\n"
                    "【合法正例】「①skill 条目存在--`ls .claude/skills/factor-development/SKILL.md` 返回该路径」合规（命令+返回概述即满足）；「②CLI 本绑定不适用（skill 加载不依赖外部 CLI）--显式声明」合规（不适用声明即满足该类留痕，不索命令）；「②CLI 可用--`which codegraph` 返回 /home/admin/.npm-global/bin/codegraph；新鲜度冒烟--sqlite3 查 indexed_at 返回当日时间」合规；「①条目存在--会话 available-skills 列表行『superpowers:test-driven-development』」合规（列表行引用即满足，不要求另附磁盘 ls）；「三态：已验证（出处=上述 Bash 命令返回）」合规（概括回指同段已列命令即满足，不要求逐类别复述命令）；「三态：一项假设--磁盘 SKILL.md 未逐一核实（置信度高×影响低：错误时 Skill 调用当场报错、可即时改走内联约束）」合规（定性置信度+影响在场即满足）；「①skill 不适用（零 skill 绑定）--显式声明；④环境前提--`python3 -m pytest --version` 返回 pytest 8.3.2」合规（单条依赖命令即满足，不索其余依赖包）。方框以外一律不判。\n"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例（指模式不指实例位置）。"
                ),
            ),
            Step(
                kind="skill",
                ref="define-problem(归一化)",
                short="归一化能力包",
                # claim normalization 职能第八次复用（ProblemContext 子6 /
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
                # v2.117（designs/plan3-sub5-gate-framing-design.md）：不加载清单
                # 丢失 + 假设传导丢失/淡化下沉跨步 mech（出席型负判定，⑭ 注意力
                # 方差--judge 不做「列出前序条目->逐项检索」跨步扫描，v2/v3 仅
                # 1-3/6）。gate 方框四/五改 mech-托声明。
                mech_checks=(
                    "no_load_trace",
                    "assumption_propagation_trace",
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=CapabilityToolSelection 且 sub_step==5 的记录（产物含 "
                    "sub_step 1-5 五条记录是生产常态，判对象=sub_step==5 那条；本步 "
                    "record_format=statements--trace 正文是 statements 列表、无 q/a "
                    "字段是生产形态，不得以「无 sub_step==5 记录/缺 q/a 字段/缺 "
                    "kind·minor_stage 顶层键/未声明已落库 jsonl」为由 block）。"
                    "形式要件：每项 = 1 个可独立执行的配置断言（text 单句）；"
                    "fields 五键齐备（append-trace 已逐键 JSON 校验，缺键当场拒、"
                    "不会到你这里--勿再数字段，不得以「缺键/键名错/type_label 不在"
                    "五类」为由 block）；statement 顶层键=text/type_label/boundary/fields 四键（type_label 与 text 平级、非 fields 子键），不得以「fields 内无 type_label/缺 hypothesis_assumption/trace_meta 等未定义字段名/顶层键不全」为由 block（顶层键与 fields 五键均已机械校验）；与需求双向覆盖（每条 T 任务有能力项承接）；"
                    "假设传导在场。\n"
                    "默认 pass--仅当以下成立才判 block（每条附合法形态，合法形态"
                    "在场不得判）：\n"
                    "一、字段与子3/子4 已定内容不一致（丢失/篡改/新增）：某项字段"
                    "与子3 绑定提案/最小集或子4 可用性状态矛盾判 block--**子3 已否决"
                    "的替代被写进绑定字段即篡改**（如 B1 被否替代 `factor-summary-"
                    "reporting` 写进 skill_first），照判 block；子4 已验证状态被改标"
                    "（已验证改假设/假设改已验证）照判 block。合法形态=对子3/子4 "
                    "内容的忠实提取/适度压缩/同义转述即合规，不要求逐字一致--"
                    "**能力名除外（能力名逐字性归方框三判）**；enforce_align 含"
                    "「长 pipeline 后台禁 pipe」等 CLAUDE.md §3 执行映射常驻约束即"
                    "合规--门禁对齐项出处=§3 执行映射，不要求子3 有对应绑定，"
                    "**不得以「子3 未绑定长 pipeline/该约束子3 未提案=凭空新增」"
                    "为由 block**；subagent_policy 显式「单线程」（承子3 无扇出绑定/"
                    "红队未触发声明）即合规，**不得以「把子3 的未绑定扇出/红队未"
                    "触发改写为单线程」为由 block**。\n"
                    "二、复合句（未原子化）：一项 text 合并 ≥2 个可独立执行的配置"
                    "断言判 block（如「必先 invoke X skill，并且每完成一个任务后"
                    "立即跑 pytest 验证」--skill 绑定与测试时机分属不同字段族、"
                    "可分别拍板）。"
                    f"{_ATOMIC_ITEM_RULE}。合法形态=字段内枚举不算复合--"
                    "skill_first 含触发依据+注册表出处+绑定提案引用等多个子句、"
                    "enforce_align 枚举 H15 前置与长 pipeline 禁 pipe 等多个执行"
                    "映射条目、no_load 枚举多个能力名，均为字段键值枚举/清单枚举，"
                    "**不得以「字段内含多个子句/多个条目/多个能力名」为由判复合**；"
                    "text 概括指称其字段枚举的同族条目族（如「遵守 H15 门禁与长 "
                    "pipeline 执行映射约束」指 enforce_align 枚举的执行映射条目）"
                    "= 一条配置断言，不算复合；一条断言覆盖多个任务 ID（如 T1/T2/"
                    "T3）= 适用范围枚举，**不得以「多任务应拆为多条」为由 block**；"
                    "原子性只判 text 单句内部，不判字段内容、不判不同 statements "
                    "项之间的关系（两项是否应合并/重新拆分不在判面内，不得以"
                    "「项1 与项2 应合并/应重拆」为由 block）。\n"
                    "三、能力名与子2 注册表出处不符（幽灵回潮）：text 或字段中的"
                    "能力名与子2 注册表清单行不逐字一致判 block--凭记忆缩略/改名"
                    "（如 `superpowers:tdd`，注册表实为 `superpowers:test-driven-"
                    "development`）即幽灵回潮。**检测：逐字对照每个能力名与注册表"
                    "清单行--即便多数能力名逐字一致，也不得放过个别缩略/改名"
                    "条目**。合法形态=能力名逐字一致即合规；「内置工具足够」"
                    "「内置 Bash」「MCP `tavily-search`」类通道描述（子2 ②③ 通道"
                    "内容，非 skill 注册表条目）合规，不得以「非注册表 skill 名」"
                    "为由 block；触发依据/出处引用的措辞不核（同义转述合规，归"
                    "方框一）。\n"
                    "四、不加载清单缺失且无声明：已由 no_load_trace 机械校验--"
                    "子3 最小集不加载清单的每个条目名未在本步 statements 全文出现"
                    "、且无「本包无不加载项」声明的已被 append-trace 当场拒、不会"
                    "到你这里；你不得以「不加载清单丢失/清单条目缺席/未承载最小集"
                    "不加载项」为由 block。合法形态=条目名在 text 或 no_load 字段"
                    "任一处出现即合规--四件合并一条或逐项拆分均合规，**不得以"
                    "「未逐项拆成独立 statement/条目未独立承载/未放入 no_load 字段/"
                    "一条 text 含多个能力名」为由 block**；子3 确无清单时显式"
                    "「本包无不加载项」声明即合规。\n"
                    "五、假设传导丢失/淡化：已由 assumption_propagation_trace 机械"
                    "校验--子4 假设项（含置信度×影响）在本步 statements 全文无"
                    "「置信度」或「影响」词形痕迹的（含「已确认无风险」式定性句"
                    "改写）已被 append-trace 当场拒、不会到你这里；你不得以"
                    "「假设传导丢失/淡化/置信度×影响丢失/假设改写成已确认无风险」"
                    "为由 block。合法形态=假设在 boundary 或 fields 任一处原样"
                    "携带置信度×影响或语义等价转述（仍含置信度/影响词形）即合规；"
                    "无假设的项标「无假设」即合规--**不得索取字段层结构化「无假设」"
                    "键或置信度×影响结构，不得以「无假设项未附置信度×影响/假设"
                    "传导形式不完整」为由 block**。\n"
                    "【判材边界】子2 注册表清单/子3 绑定提案与最小集/子4 可用性"
                    "状态与假设=S2/S3/S4 trace 在载荷内可见（对照判材）；注册表"
                    "真实内容与磁盘真值（skill 是否真在册/真可加载）结构性不可见"
                    "--只判 trace 内自洽与传导忠实，不核真值；fields 五键与 "
                    "type_label 五值已由 append-trace 机械校验，不重复判。\n"
                    "【合法正例】「text=改动 T1/T2/T3 涉及的 .py 源码前必先 invoke "
                    "`factor-development` skill」合规（单断言+多任务适用范围枚举）；"
                    "「enforce_align=H15 codegraph 前置…；长 pipeline 后台禁 pipe…"
                    "（本包无长 pipeline 任务，常驻约束保留）」合规（字段枚举执行"
                    "映射条目族）；「subagent_policy=单线程（子3 无扇出绑定）」合规；"
                    "「no_load=`factor-ic-analyzer-workflow`、`workflow-creation`、"
                    "`superpowers:systematic-debugging`、MCP `tavily-search`（子3 "
                    "最小集原样）」合规（清单枚举多名）；「boundary=…假设传导=磁盘 "
                    "SKILL.md 未逐一核实（置信度高×影响低…）」合规（boundary 携带"
                    "假设即满足）。方框以外一律不判。\n"
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例"
                    "（指模式不指实例位置）。"
                ),
            ),
            Step(
                kind="skill",
                ref=f"AskUserQuestion / Bash(plan.md 追加「{_S_CAP_TOOLS}」节)",
                short="读回装配",
                interactive=True,
                # 带证据读回（同构 plan:2 子5）：只给结论不给依据地「通知」用户 =
                # 无依据确认；plan.md「能力与工具」节 = 子5 能力包+裁决记录的
                # 直接装配（禁二次创作）。
                purpose=(
                    "带证据读回与 plan.md 装配：材料 = 运行 `python3 ~/.dl-workflow/dl_flow_engine.py render-readback` 机械装配逐字呈现（本节点归一化+假设/不确定性 traces，禁手抄；Bash 输出即呈现）。呈现内容 = 映射摘要+可用性状态+假设清单"
                    "+不加载清单+新增候选（子1 检出若有）+不确定性；"
                    "用户两裁决——①映射拍板（本节点唯一规范裁决点，"
                    "含要求换绑/卸载/补绑的合法权利）；②假设接受（风险承担）；"
                    f"拍板后装配 plan.md「{_S_CAP_TOOLS}」节 = 运行 `python3 "
                    "~/.dl-workflow/dl_flow_engine.py render-artifact plan.md`"
                    "（脚本机械装配本节，落主仓 .claude/plans/<name>.md；"
                    "禁手写产物文件——内容要改就改对应步 trace 后重渲染）；"
                    f"{_INTERACTIVE_CHUNKING_RULE}；"
                    f"{_USER_DECISION_RECORD_RULE}-> STEP_DONE。"
                ),
                input="step5.capability_packages",
                record=True,
                selfcheck=(
                    "呈现了映射摘要+可用性状态+假设清单+不加载清单+新增候选吗？"
                    "用户对映射/假设两项裁决都记入 trace 了吗？"
                    f"plan.md「{_S_CAP_TOOLS}」节是装配而非二次创作吗？"
                ),
                # v2.45 交接架构正确性前提：用户裁决必入 trace（gate=None 无 judge，
                # 机械校验是唯一防线）。
                mech_checks=("user_decision_recorded",),
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
        # 2026-08-02 扩为全三节（artifact-handoff-hardening-design）：本节点是
        # 装配终点+唯一门栏，查 plan:2/3 节被跨节点删改的最便宜位置。
        gate_mech=GateMech.ARTIFACT_CONTAINS,
        artifact_contains=ARTIFACT_SECTIONS["plan.md"],
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
                mech_checks=("epc_quote_trace",),  # v2.115：方框四原文引用下沉生产墙
                selfcheck=(
                    "五类清单都齐了吗（任务 DAG/能力绑定/验收包/假设汇总/"
                    "不可逆操作候选，无遗漏）？每条都附源出处且四源原文引用进 "
                    "trace 正文了吗（judge 读不到三个文件本身）？"
                    "triggered 验收项显式标注了吗？"
                    "新增候选显式标注或显式「无」了吗？"
                    "有静默新增四源没有的对象吗（那是二次创作）？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、minor_stage=ExecutionPlanCheckpoints 且 sub_step==1 的记录。形式要件：控制结构输入五类清单齐备（①任务 DAG 与阶段边界/②能力绑定/③验收包/④假设清单汇总/⑤不可逆操作候选）；每条附源出处且四源原文引用进 trace 正文；新增候选（四源没有的对象）显式标注或显式「无」，q/a 按序对齐；只提取不创作（本步是全节点保真判定基线）。\n"
                    "默认 pass--仅当以下成立才判 block（每条附合法形态，合法形态在场不得判）：\n"
                    "一、清单来源自证不足（编造/静默新增）：五类清单条目声称提取自四源，却既无出处（源文件+行号 / 原文『』引用）又未显式归入「新增候选」区判 block。两种违规形态：(a) 全清单裸=编造（「按四源常规结构可知…按常规路径可查」类凭印象，无任何出处/原文引用）判 block；(b) 个别条目裸且未标新增候选=静默新增二次创作（「新增候选：无」声明下清单含无出处无原文引用的新增条目，如「删除旧报告目录」类四源没有的对象）判 block。**检测：逐条检查清单中无出处（源文件+行号）且无原文『…』引用的裸条目，并核对「新增候选」答案（a[1]）是否声明「无」--「新增候选：无」声明下任何此类裸条目（无论属哪一类，⑤不可逆操作候选中的「删除旧报告目录」也不例外）= 静默新增二次创作判 block**。合法形态=源文件+行号 / 『原文』引用 任一在场即合规；「新增候选」区显式列出条目（含待子5 用户裁决语义）即合规；「新增候选：无」声明+清单无新增条目即合规--不得以「无新增候选=可能漏检」为由 block；**②能力绑定中「内置工具足够」是合法 plan.md 能力节/§2 路由结论（非新增对象，其出处随②条目整体的 plan.md:18），不得以「内置工具足够无单独出处=静默新增」为由 block**。\n"
                    "二、改写失真（聚合失真/语义偏移）：清单自述措辞与 trace 内引用的四源原文『…』明显语义冲突判 block（T1 自述「重写 _aggregate_positive_ic 为独立分组引擎」vs 其引用的原文『在既有聚合统计函数内增加 FACTOR_CATEGORIES 维度分组键』= 操作对象从「既有函数内改动」变「独立重写」、操作性质从「增加分组键」变「重写引擎」、产出物从「修改既有函数」变「全新独立引擎」，三者任一明显变化=改写失真判 block）。**检测：逐条对照每个引用了原文『…』的清单条目（含①各任务 T1/T2/T3、③各 SC），把该条自述措辞与其引用的原文三维对比--哪怕多数条目忠实提取（T2/T3/SC/H1 合规），只要个别条目自述把原文操作对象/性质/产出物明显改变（T1 自述「重写为独立分组引擎」vs 原文「在既有函数内增加分组键」）即改写失真判 block，不得以「多数条目忠实提取/整体与四源一致」为由放过个别改写条目**。合法形态=措辞是对原文的忠实提取/适度压缩/适度具体化即合规，不要求逐字一致（「增加分组键」转述为「加维度分组」类语义等价转述合法）--细节省略/语序调整/同义替换/适度具体化（原文「在既有聚合统计函数内…」自述点明函数名「`_aggregate_positive_ic` 内…」= 具体化非语义冲突）不判，操作对象/性质/产出物未变化不判。\n"
                    "三、四源漏源（五类清单缺类）：五类清单缺少某一整类（①任务 DAG/②能力绑定/③验收包/④假设汇总/⑤不可逆操作候选任一缺失）且无「该类无相关内容」声明判 block（缺③验收包整类=understand.md 在清单中无任何条目=四源之一漏源）。合法形态=五类均有条目即合规；某类无对应内容时显式标注「该类无相关内容」即合规；**某类有至少一条条目即合规，不要求该类覆盖全部源/全部子项--④仅列 H1 且声明「其余假设：无」即合规，不得以「④未列全 plan.md/evidence 假设/某类条目少/未列全全部子项/未列齐四源所有假设」为由 block**；不得以「某类条目少/粒度粗/某源仅一条」为由 block。\n"
                    "四、原文未引用：已由 epc_quote_trace 机械校验--控制结构输入清单条目引用了代码符号形（.py）却无任何『』原文引用/『原文』字样的答案已被 append-trace 当场拒、不会到你这里；你不得以「四源原文未引用/无原文/无法核对原文/原文未引用进 trace 正文」为由 block。残留判面=无代码符号形的清单条目（如纯验收包 SC ID/假设 H1 条目）是否附出处行号或『』原文引用--缺则 block；『…』摘要包裹是合法引用形态（原文片段+省略号=引用非原文整体，不要求整段逐字粘贴），不得以「『…』是节选标签式短句/非逐字完整引用/未把原文整段嵌入」为由 block。\n"
                    "【判材边界】本步 input=design.md/plan.md/understand.md（主仓 .md 文件）+ evidence plan:1/2/3 前序 trace--evidence 只含 ExecutionPlanCheckpoints 段，四源 judge 结构性读不到。不得以「未见四源原文/无法核对出处行号真实性/无法确认某条目是否真在四源/无法核对操作类型分类正确」为由 block；本步只判 trace 内自洽 + 留痕形式。四源=design.md/plan.md/understand.md/evidence 四个源，**evidence 是一个源（plan:1/2/3 trace 的集合），清单条目引用了 evidence 任一 plan trace 即合规，不要求 plan:1/2/3 全引用/逐 trace 引用，不得以「evidence plan:2/3 trace 未引用/未声明无关联」为由 block**；五类清单=「四源实际涉及的控制结构输入对象」，不要求四源每个文件每段都引用--清单含四源承载控制结构输入的对象即合规，某源仅一条条目即合规，不要求每源条目数均衡；**不要求每子项每属性都附原文引用--每类附源出处（文件+行号）+ 至少一处『』原文片段即合规，不得以「②能力绑定未分别引用每个绑定对象/①阶段分组未引用原句/某属性无原文」为由 block**；**验收包（③）引用 understand.md 原文即合规，不要求六字段逐字全列/triggered 项逐个展开--列出 SC ID + 落点 + 原文片段即合规，不得以「六字段未全列/triggered 项未逐个标注」为由 block**；**出处行号与原文引用可集中或分散标注，不要求每子项单独附出处行号--同类多子项共享一处出处行号即合规（SC1.1/SC2.1 共享 understand.md:22、T1/T2/T3 各自或共享 plan.md 行号均合规），不得以「SC1.1 未单独附出处/出处写在类尾/出处与原文分离」为由 block**。\n"
                    "【合法正例】「①任务 DAG：T1=U2 代码改动（…增加 FACTOR_CATEGORIES 分组键，改 .py=H15 触发信号）--出处 plan.md:12，原文『U2: 在既有聚合统计函数内增加 FACTOR_CATEGORIES 维度分组键』」合规（源文件+行号+原文片段即满足，『…』片段合法）；「③验收包：SC1.1=八维度汇总区块存在性（triggered 项，落点=T3）--出处 understand.md:22，原文『SC1.1: 报告含八维度汇总区块』」合规（验收包引用 understand.md 原文即满足，不要求六字段全列）；「④假设汇总：H1=…（置信度中×影响中）--出处 design.md:25，原文『假设 H1: …』+ evidence plan:1 trace」合规（evidence 任一 plan trace 引用即满足，不要求 plan:1/2/3 全引用）；「⑤不可逆操作候选：显式『无』」合规（某类无对应内容显式标注）；「新增候选：显式『无』」合规。方框以外一律不判。judge 判 block 须在 reason 引用判据条款（方框一/二/三/四）并附 1 个正确改写范例（指模式不指实例位置）。"
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
                    f"形式要件：{_EPC_STEP2_FORM_REQUIREMENTS}。\n"
                    "默认 pass——仅当以下成立才判 block（每条附合法形态，合法形态在场不得判）：\n"
                    "一、虚设判据：任一检查点的通过判据以「确认/检查/合理/无问题/正常」类判断词为判定手段、无命令+退出码/输出断言可执行形判 block（「人工确认常量定义合理、检查导入无问题」类=判据不可机械执行=虚设）。合法形态=命令+退出码（可附输出断言标识，如「pytest … 退出码 0 且输出含八维度断言」）即合规——「输出含 X 断言/断言通过」是断言锚定形非判断词，不得以此判虚设；判断词禁令只约束通过判据行本身，goal anchoring 句/描述句中的「待验/确认」类词不判。\n"
                    "二、即兴路由：任一检查点失败路由整项缺失、或写「视情况/届时再定/按实际情况处理」类未预定义措辞判 block。合法形态=路由语义落返工本组/回滚至上一检查点/升级用户三类之一（可附执行细节，如「返工本组（W1 重做 T1）」「回滚至上一检查点（git checkout 工作区回 CP1 状态）」）即合规——不要求显式标注「三选一之 X」类别名，语义可归类即算预定义。\n"
                    "三、拍脑袋分组：声明并行分组却未列各 worker 改动文件清单、或列了清单但无组内交集核对结论（「交集=∅/无公共文件」类）判 block（「天然不冲突/方向不同不会冲突/无需逐一核对」类断言=未从改动点计算=拍脑袋分组）。合法形态=逐 worker 文件清单+交集核对结论在场即合规；清单粒度/路径写法差异不判（交集实算归子3）；纯串行 DAG 声明「无并行组、互斥面不适用」即合规。\n"
                    "四、无验收门：subagent 返回契约未列任何证据形式（测试输出/改动文件清单/file:line 证据清单），只写「返回执行结果与说明/写清做了什么」类判 block。合法形态=返回契约列证据形式清单（三类齐备或明确等价枚举）即合规，形式命名差异不判。\n"
                    "五、逃避论证：检查点密度与类型既未按可逆性×爆炸半径逐检查点论证、也未走「零用户检查点」复利论证（逐步成功率+整体下界+全链可逆声明）判 block（只裸列「CP1 自动继续、CP2 用户暂停」类结论+「够用了不再展开」类=逃避论证）。合法形态=两路径任一在场即合规：选可逆性×爆炸半径路径的，逐检查点附可逆性+爆炸半径两因子与类型建议即合规，不得再索复利论证的逐步成功率/整体下界数值；论证篇幅与深度不判。\n"
                    "六、越权拍板：把并行分组/检查点密度/类型写成已定案（「定为/确定为最终方案」「按此执行」「无需再等用户裁决」类拍板措辞）判 block。合法形态=「提案/建议/待子5 用户拍板/待用户裁决/本步不定案」类提案措辞即合规——方案内容写得具体完整不判，只判是否替用户定案。\n"
                    "【命题性质】本步产提案、子5 拍板、子3 锚点核验——方案内的命令/交集/任务 ID 是提案句：命令未实际 dry-run、交集未实算、任务 ID 未核验存在均不判（归子3）；并行分组与子1 DAG 的对照只判「有拓扑分层且附同层无依赖声明」，层划分正确性本身不判、不得自行重推 DAG 后判分组错误；worker 任务包映射给「任务 ID→派发单元+自包含要素（任务 ID/文件清单/判据命令）声明」即合规，不得要求逐字段样例展开或验证零上下文可执行。\n"
                    "【判材边界】plan.md/design.md/understand.md 四源文件 judge 结构性读不到（载荷只有本节点 trace）——出处行号/原文引用/验收包 ID 的真实性无法核对，不作 block 依据；只判 trace 内自洽+形式合规。红队条件未触发声明附计数（并行组数/检查点数）即合规，不得索阈值定义或触发论证。\n"
                    '【合法正例】「通过判据=`python3 -c "from paths import CATEGORY_SUMMARY_RESULT"` 退出码 0（承接 SC1）」合规（命令+退出码+承接 ID）；「失败路由=返工本组（W1 重做 T1）」合规（语义落三选一之一，无类别名标注也算预定义）；「T2 改动文件清单={…py}，T3 改动文件清单={…md}，组内交集=∅」合规；「CP1 处改动 git checkout 可回滚（可逆），爆炸半径=单模块导入面（小）→建议自动继续」合规（两因子+建议=密度论证成立，不要求数值推演）；「红队条件未触发声明：并行组数=2、检查点数=2，均未超触发阈值」合规；「均为提案，待子5 用户拍板后才生效，本步不定案」合规。\n'
                    "方框以外一律不判。judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例（指模式不指实例位置）。"
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
                    "evidence/<name>.jsonl 含 kind=skill-trace、minor_stage=ExecutionPlanCheckpoints 且 sub_step==3 的记录。\n"
                    "形式要件：四类核验逐对象留痕（判据可执行性=判据命令 dry-run 命令+输出概述、互斥面交集实算命令+输出进 trace、锚点存在性出处、验证手段绑定声明）；三态按对象标注（已验证附出处/假设含置信度+错误时影响/证伪附理由回子2，不须逐类拆标、不须声明无假设/证伪）；出处/置信度+影响/理由齐备。\n"
                    "默认 pass——仅当以下成立才判 block（每条附合法形态，合法形态在场不得判）：\n"
                    '一、声称可执行/存在/绑定无留痕=编造：检查点判据声称可执行、锚点声称存在、验证手段声称已绑定，却无任何留痕判 block。违规形态：(a) 只写「命令可运行/可以直接跑/命令存在/文件已存在/工具已绑定」类口头声称，无任何「Bash 命令执行+输出概述」伴生（光说『命令存在』『可以直接跑』不算留痕）；(b) 四类核验整段概括复述「判据均可运行、锚点均存在、交集为空、工具已绑定」无任何对象特定命令或出处。合法形态=留痕在场即合规——留痕指「Bash 命令执行+输出概述」：判据可执行性=判据命令本身 dry-run（`Bash <判据命令>` 退出码/收集输出概述，如 `Bash python3 -c "from paths import CATEGORY_SUMMARY_RESULT"` 退出码 0 / `Bash pytest --collect-only -q` 返回 N 用例）或命令存在性检查（`Bash which pytest` 返回路径 / `Bash pytest --version` 退出码 0——存在性检查也须以 Bash 命令形式实际执行）；锚点存在性=Read/codegraph 出处（命令/文件+行号或返回概述）；验证手段绑定=能力包绑定声明（含对象归属或全局声明，如『python3 在 plan:3 能力包有绑定』）即合规，附出处（如 Read plan:3 能力节/绑定清单）亦合规——声明与出处任一或兼有均合规，不得以『给了声明而没给出处』『给了出处而没给声明』『出处非行级』为由 block，不索 grep 命令。判据命令的反引号描述本身不构成留痕，须伴生 Bash 命令执行+输出概述；不索退出码原文/完整回显/结果真值；判据依赖未生成物件（如 TDD 先行测试文件）时该项标「假设」（附置信度+影响）即合规——假设项以命令存在性检查留痕即可（不索判据命令本体 dry-run），纯假设无任何命令留痕亦合规（假设不是声称可执行）。\n'
                    "二、互斥面交集核验无实算输出=没真核验：声明并行组交集为空却无实算命令+输出判 block。违规形态：「两个文件明显不同/天然不冲突/无需逐一核对」类口头断言代替实算。合法形态=并行组各 worker 改动文件清单集合交集实算（命令+输出，如 python 集合交集命令返回 set()）即合规——不要求逐 worker 清单单独实算、不索实算脚本原文；纯串行 DAG 声明「无并行组、互斥面不适用」即合规。\n"
                    "三、全对象无差别「已验证」=没真核验：核验对象三态全标「已验证」且留痕同形泛化（各对象仅复述「可运行/存在/为空」套话，无对象特定命令/出处/输出）判 block。合法形态=逐对象差异化留痕（各对象各自命令+出处/输出）即合规；三态混合（已验证为主+个别假设/证伪）即合规；无证伪项不须声明「无证伪」——不得以「没有假设/证伪项」本身判 block；三态按对象标注即合规，不须逐类拆标三态。\n"
                    "四、假设项缺置信度或影响：已由 assumption_completeness_trace 机械校验——标注「假设」的条目（假设标签形：假设后接 --/：/（ 等结构化标点）无置信度或错误时影响已被 append-trace 当场拒、不会到你这里；你不得以「假设缺置信度/影响/影响面不具体/可回滚是恢复手段非影响面」为由 block。残留判面=假设标签形以外的假设提及（如「假设项」「无假设」）是否明显矛盾——只判明显矛盾，不主动索要素、不复核影响面具体化程度。\n"
                    "五、漏对象核验：某核验对象四类之一缺留痕，被「随 X 覆盖/同 X 已验证」一句话代过判 block。合法形态=逐对象四类留痕（每对象各自命令+出处/输出）即合规；某类对该对象不适用（如串行组无并行交集、新增常量无既有锚点可查）附声明即合规。\n"
                    "【命题性质】本步只标注不裁决（假设接受留子5 用户裁决）——三态是标注不是裁决，不得以「标假设未标已验证/未裁决假设接受」为由 block；dry-run 验命令存在且可运行、不验结果对错——不得以「未验判据命令结果对错/命令 execute 期才真跑」为由 block；交集实算结果不核真（不重算分组正确性）。\n"
                    "【判材边界】plan.md/design.md/understand.md 四源文件与 codegraph db/文件系统真值结构性不可见——只判本步 trace 内留痕在场与自洽，不核「文件/命令/锚点/工具是否真存在真能跑」；前序子1/子2 trace 在载荷内（核验对象源自 S2 调度方案：CP1/CP2/并行组/验收包 ID），子1/子2 自身方案内容/假设不重核、不索显式对照前序声明的自洽申述。\n"
                    '【合法正例】「CP1 判据可执行性--Bash `python3 -c "from paths import CATEGORY_SUMMARY_RESULT"` 退出码 0」合规（判据命令本身 dry-run 即满足，不索退出码原文）；「CP2 判据可执行性=假设（Bash `pytest --version` 退出码 0，测试文件需 TDD 先行，置信度中×影响中）」合规（假设附置信度+影响即满足，存在性检查留痕即可，不索判据命令本体 dry-run）；「互斥面交集--Bash python 集合交集返回 set()（交集=∅）」合规（实算命令+输出即满足，不索逐 worker 清单实算）；「锚点 SC1 存在--Read understand.md:31 原文『路径常量可导入』」合规（出处留痕即满足）；「验证手段绑定=python3/pytest 在 plan:3 能力包有绑定」合规；「CP1 判据已验证、CP2 判据假设、互斥面已验证」三态混合合规，无证伪项不需声明。方框以外一律不判。\n'
                    "judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例（指模式不指实例位置）。\n"
                ),
                # v2.114 framing 反转（designs/plan4-sub3-gate-framing-design.md）：
                # 「假设缺置信度/影响」同 plan:2#3/plan:3#4 词形可判子项下沉 mech 承托
                # （⑭ 注意力方差型，default-PASS 下 judge 橡皮图章），gate 方框四
                # mech-托声明。触发面/放过面同构（假设标签形+置信度/影响），
                # 复用注册表同名函数（第三处跨节点复用）。
                mech_checks=("assumption_completeness_trace",),
            ),
            Step(
                kind="skill",
                ref="define-problem(归一化)",
                short="归一化计划包",
                # claim normalization 职能第九次复用（ProblemContext 子6 /
                # GoalsAndValue 子4 / ScopeAndConstraints 子4 / SuccessCriteria
                # 子4 / DesignSolution 子5 / TaskBreakdown 子4 /
                # CapabilityToolSelection 子5 同构）。
                # 执行计划包十字段（调度四+检查点六）倒推自消费契约（design
                # §0 表）：execute:0 orchestrator 愿景/rubric 逐条核/
                # understand:4 时机字段/review:0 证据需求/用户密度裁决五方。
                # v2.119 迁 statements+statement_fields（同 DesignSolution 子5）：
                # v2.33 迁移漏网第九处——qa 残留致 render-artifact 结构性跳节
                # （只读 statements）、门栏 ARTIFACT_CONTAINS 不可通过
                # （designs/plan4-sub4-statements-migration-design.md，
                # 2026-08-06 tail_volume live 全轮首达 plan:4#5 实爆）。
                # 十字段进 fields 逐键机械校验。
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
                    '载荷格式：statements 逐项 {"text":计划包断言单句，'
                    '"type_label":调度/检查点，"boundary":假设传导+出处指针，'
                    '"fields":{parallel_group/mutex_surface/worker_map/'
                    "return_contract/cp_position/cp_criterion/cp_failure_route/"
                    "cp_type/cp_acceptance_map/cp_goal_anchor}}——fields 十键"
                    "逐键非空（append-trace 机械校验，缺键即拒；调度项 cp_* "
                    "六键、检查点项调度四键填显式「无」）。text 只留单句——"
                    "改动文件/判据命令/签名进 fields（方案名词扫描同源纪律，"
                    "text 含实现侧名词当场拒）。"
                ),
                input="step3.verified_controls",
                record=True,
                record_format="statements",
                statement_fields=(
                    "parallel_group",
                    "mutex_surface",
                    "worker_map",
                    "return_contract",
                    "cp_position",
                    "cp_criterion",
                    "cp_failure_route",
                    "cp_type",
                    "cp_acceptance_map",
                    "cp_goal_anchor",
                ),
                selfcheck=(
                    "每断言 ≤1 句且自包含（零上下文 orchestrator 照做）吗？"
                    "fields 十键都填了吗（parallel_group/mutex_surface/worker_map/"
                    "return_contract/cp_position/cp_criterion/cp_failure_route/"
                    "cp_type/cp_acceptance_map/cp_goal_anchor——append-trace "
                    "机械校验，缺键即拒；无内容键填显式「无」）？"
                    "字段与子2/子3 已定内容一致吗（无丢失无篡改无新增）？"
                    "每 triggered 验收项有检查点落点（或显式「continuous 覆盖」"
                    "声明）吗？判据零判断词保持了吗？假设传导了吗？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、minor_stage=ExecutionPlanCheckpoints 且 sub_step==4 的记录。\n"
                    "形式要件：本步 record_format=statements——trace 正文是 statements 列表、无 q/a 字段是生产形态，不得以「缺 q/a 字段/缺 kind·minor_stage 顶层键」为由 block；fields 十键（调度四+检查点六）逐键非空已由 append-trace 机械校验，勿再数字段、不得以「缺键/字段为空/调度项 cp_* 填『无』」为由 block。triggered 验收项有检查点落点或显式「continuous 覆盖」声明；假设传导。\n"
                    "默认 pass--仅当以下成立才判 block（每条附合法形态，合法形态在场不得判）：\n"
                    "一、字段与子2/子3 已定内容不一致（丢失/篡改/新增）：某调度字段或检查点字段与子2 调度提案/子3 锚点核验结果语义冲突判 block。两种违规形态：(a) 篡改--措辞与子2/子3 已定内容语义冲突（子2「增加 FACTOR_CATEGORIES 分组键」vs 子4「重写为独立八维度聚合器，输出全新数据结构」类）判 block；(b) 丢失/新增--子2/子3 已定的改动点/判据命令/失败路由/类型在子4 缺失，或混入子2/子3 未定的内容判 block。合法形态=对子2/子3 内容的忠实提取/适度压缩/同义转述即合规，不要求逐字一致（「增加分组键」转述为「加维度分组」类语义等价转述合法）--语序调整/同义替换/细节省略不判，改动范围/性质/产出物未变化不判；子2/子3 用泛指（「判据命令」「改动 paths.py」）而子4 细化为具体命令/具体文件=细化即合规，不算新增/篡改；子3 假设项原样携带（不丢不淡化，量化范围与置信度×影响原样保留）即合规。本条只约束十字段（调度四+检查点六）字段内容+假设传导与子2/子3 一致；子2 的红队条件未触发声明/密度论证叙述/提案语义声明是子2 的过程留痕、非 sub4 归一化字段，不要求 sub4 携带，不得以「红队声明/密度论证未传导」为由 block。\n"
                    "二、复合句（未原子化）：一句合并 ≥2 个可独立成立/可分别提交的交付物判 block。检测：提取 statements 每项 text，凡 text 以「以及/同时/并且」等并列连接词连接两个可独立成立、可分别提交的交付物（各自含独立动作与独立交付物，如「W1 派发 T1 完成…，以及 W2 派发 T2 完成…」）判 block。合法形态=命令+退出码（可附输出断言标识，如「pytest … 退出码 0 且输出含八维度断言通过」）=单条可执行判据非复合句--「退出码 0 且输出含 X 断言」是断言锚定形非复合句；worker 任务包映射以逗号/分号分隔 W1/W2/W3 各自独立任务包（如「W1->T1（...），W2->T2（...），W3->T3（...）」）、返回契约列多种证据形式、验收包映射列多个 SC ID=字段枚举非复合句（逗号/分号分隔即枚举，「以及/并且/同时」将两个任务包并入一句即复合句）；goal anchoring「原目标…；当前位置…」两成分=字段结构非复合句。\n"
                    "三、判据判断词回潮：任一检查点通过判据以「确认/检查/合理/无问题/正常」类判断词为判定手段、无命令+退出码可执行形判 block（「人工确认 paths.py 常量定义合理、检查导入无问题」类=判据不可机械执行=判断词回潮）。合法形态=命令+退出码（可附输出断言标识）即合规--「输出含 X 断言/断言通过」是断言锚定形非判断词，不得以此判回潮；判断词禁令只约束通过判据行本身，goal anchoring 句/位置锚描述句中的「待验/完成待验证/确认」类状态词不判。\n"
                    "四、triggered 验收项漏配：任一 triggered 验收项（子1 验收包清单中时机=triggered 的 SC ID）在子4 检查点验收包映射中无任何落点、且无显式「continuous 覆盖」声明判 block。合法形态=每个 triggered SC 至少一个检查点验收包映射承接（如 SC1->CP1、SC2->CP2）即合规--不要求逐项标注 triggered 时机、不要求 continuous 覆盖声明（除非该 SC 真无落点）；验收包映射列多个 SC ID=枚举非复合句。\n"
                    "【命题性质】本步产归一化包（从子2 调度提案+子3 核验结果忠实提取，非提案非假想）--判据命令未实际 dry-run、互斥面交集未实算、任务 ID/验收包 ID 真实存在性均归子3 锚点核验，本步不判（归子3）；本步只判归一化文本形态齐备+字段忠实+形式合规，不判命令真实可跑/交集实算结果/锚点真值。\n"
                    '【判材边界】artifact=子1+子2+子3+子4 最新 skill-trace 拼合（生产 read_evidence_for_step(4,"ExecutionPlanCheckpoints") 同形）--sub_step==4 记录=末条，存在即满足形式要件，不得以「拼合/非独立条目/末条以子3 收尾」为由 block；前序 trace 是字段一致性对照面+验收包落点对照面（判材非纯组成事实）。plan.md/design.md/understand.md 主仓 .md 文件结构性读不到，但子1 已提取验收包 SC1/SC2 为载荷内清单--锚点存在性/出处行号/原文引用真实性不作 block 依据，只判 trace 内自洽+形式合规。子3 已留痕即合规，不得索 dry-run 通过结果或交集实算原始输出。\n'
                    "【合法正例】「worker_map: W2->T2（任务 ID T2+改动 generate_factor_summary_report.py _aggregate_positive_ic 增加 FACTOR_CATEGORIES 分组键+判据命令 pytest）」合规（忠实提取子2，fields 键值内容含实现侧名词合规——方案名词扫描只管 text；字段枚举非复合句）；「CP2 通过判据=`pytest tests/test_summary_categories.py -x` 退出码 0 且输出含八维度断言通过（承接 SC2）」合规（命令+退出码+输出断言=断言锚定形非复合句非判断词）；「验收包映射=SC2（任务 ID 追溯锚 T2/T3）」合规（triggered SC2 有 CP2 落点，无需 continuous 声明）；「goal anchoring=「原目标：分类维度汇总落地；当前位置：T2/T3 完成待验证后进入提交」」合规（两成分字段结构，「待验证」是状态词非判据判断词）；「假设传导：子3 无假设项需传导」合规。\n"
                    "方框以外一律不判。judge 判 block 须在 reason 引用判据条款并附 1 个正确改写范例（指模式不指实例位置）。"
                ),
            ),
            Step(
                kind="skill",
                ref=f"AskUserQuestion / Edit(plan.md 追加「{_S_CHECKPOINTS}」节)",
                short="读回装配",
                interactive=True,
                # 带证据读回（同构 plan:2 子5/plan:3 子6）。三裁决点的第三个
                # （冻结策略）是制度裁决：进 execute 前拍板 plan.md 的合同
                # 语义——judge 逐条核的对象不能是执行期可随手改的。
                purpose=(
                    "带证据读回与 plan.md 装配：材料 = 运行 `python3 ~/.dl-workflow/dl_flow_engine.py render-readback` 机械装配逐字呈现（本节点归一化+假设/不确定性 traces，禁手抄；Bash 输出即呈现）。呈现内容 = 并行分组+互斥面核验状态"
                    "+检查点清单（位置/判据/路由/类型）+假设清单+新增候选"
                    "（子1 检出若有）+不确定性；"
                    "用户三裁决——①密度与类型拍板（本节点核心规范裁决："
                    "每检查点自动继续 vs 用户暂停，风险承担归用户，"
                    "含要求加密/减密的合法权利）；②假设接受（风险承担）；"
                    "③plan.md 冻结策略拍板（默认：小偏离=留痕理由"
                    "[commit message+execute 完成时偏离清单]，大改=/dl back "
                    "回 plan 修订重过闸门；禁 execute 内直接改 plan.md——"
                    "judge 逐条核的对象不能是执行期可随手改的）；"
                    f"拍板后装配 plan.md「{_S_CHECKPOINTS}」节 = 运行 `python3 "
                    "~/.dl-workflow/dl_flow_engine.py render-artifact plan.md`"
                    "（脚本机械装配本节，落主仓 .claude/plans/<name>.md；"
                    "禁手写产物文件——内容要改就改对应步 trace 后重渲染）；"
                    f"{_INTERACTIVE_CHUNKING_RULE}；"
                    f"{_USER_DECISION_RECORD_RULE}-> STEP_DONE。"
                ),
                input="step4.execution_plan_packages",
                record=True,
                selfcheck=(
                    "呈现了分组+互斥面核验状态+检查点清单+假设清单+新增候选吗？"
                    "用户对密度与类型/假设/冻结策略三项裁决都记入 trace 了吗？"
                    f"plan.md「{_S_CHECKPOINTS}」节是装配而非二次创作吗？"
                ),
                # v2.45 交接架构正确性前提：用户裁决必入 trace（gate=None 无 judge，
                # 机械校验是唯一防线）。
                mech_checks=("user_decision_recorded",),
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
        # ARTIFACT_CONTAINS（2026-08-02 升，artifact-handoff-hardening-design）：
        # 最小两节（用户决议）——判决书无「结论」节即废品。
        gate_mech=GateMech.ARTIFACT_CONTAINS,
        artifact_contains=ARTIFACT_SECTIONS["review.md"],
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
        # ARTIFACT_CONTAINS（2026-08-02 升，artifact-handoff-hardening-design）：
        # 最小两节（新增结构要求：沉淀了什么 + 落到哪个 memory/skill/design）。
        gate_mech=GateMech.ARTIFACT_CONTAINS,
        artifact_contains=ARTIFACT_SECTIONS["evolution.md"],
        gate_rubric="是否沉淀非显然可复用经验（memory/skill/design）。",
        advance="done",
    ),
}


# ---------- P3-1 读回分级（2026-08-13 用户裁决，v4-cost-latency-optimization-design §2 P3）----------
#
# 8 个读回步（short=读回确认/读回装配 且 interactive=True）全降确认级：
# driver 机械展示（render-readback）+ 装配（render-artifact）+ 静默通过落 trace，
# 不弹卡片（实测 17 次提问 11 次 <1min 秒点——读回卡片的边际信息≈0，而每次
# 1-2min 交互延迟+前后段启动是真成本）；异议走 /dl state-reset 回上一步重做。
# 单点补丁而非逐 Step 改声明：原 purpose 是交互读回的长文案（逐问规则/裁决记录
# 规则），确认级语义一处单源，防 8 处文案漂移（改语义只改这里）。
_CONFIRM_READBACK_PURPOSE = (
    "确认级读回（P3-1 分级）：本步无模型会话——driver 机械展示本节点归一化内容"
    "（render-readback 装配）+ 装配产物（render-artifact）+ 以「确认级·静默通过」"
    "落 trace 后自动推进，不弹卡片问用户。用户异议走 /dl state-reset 回上一步重做。"
)


def _apply_confirm_readback_tier(nodes: "dict[str, Node]") -> None:
    for _key, _node in list(nodes.items()):
        if not _node.sub_steps:
            continue
        new_steps = tuple(
            dataclasses.replace(_s, tier="confirm", purpose=_CONFIRM_READBACK_PURPOSE)
            if (
                getattr(_s, "interactive", False)
                and _s.short in ("读回确认", "读回装配")
            )
            else _s
            for _s in _node.sub_steps
        )
        if new_steps != tuple(_node.sub_steps):
            nodes[_key] = dataclasses.replace(_node, sub_steps=new_steps)


_apply_confirm_readback_tier(_NODES)


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
