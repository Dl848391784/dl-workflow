#!/usr/bin/env python3
"""
dl_flow_nodes - 工作流节点树（声明式数据，唯一真源）。

自 dl-flow-engine.py 抽出（2026-07-27）：节点树（GateMech/Step/Node + _NODES +
PHASES）是声明式数据——加节点/改判据只改数据不改逻辑（design §0.2），且每个
编排节点 300-600 行 Step 定义、增长高频；机制逻辑（state/推进/gate/judge/
围栏/CLI）留在 dl-flow-engine.py，经 `from dl_flow_nodes import ...` 引用并
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
    ARTIFACT_EXISTS = "artifact_exists"  # 产物文件存在
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
    # 词表与 workflow-creation SKILL.md §0 的子步骤摘要一致。
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


# 节点表。<node_id> -> Node。node_id = f"{phase}:{sub}"。
# 闸门 GATED_AFTER：这些 phase 的末节点完成需用户 /dl gate 放行才进下一 phase。
#   继承现有 workflow_advance.py:39 GATED_AFTER 语义,收口到 engine 一份。
#   用 tuple 保序（显示用自然顺序 understand,plan）;is_gated_after 成员判定 O(n) 可接受（5 阶段）。
GATED_AFTER: tuple[str, ...] = ("understand", "plan")


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
                ),
                input=None,
                record=True,
                # 步级自查（全部已在上方 purpose 披露，无质量判据泄漏）
                selfcheck=(
                    "who/pain/why-now ≥3 类都覆盖了吗？每条 a 是用户原话/会话事实，"
                    "还是我推断补全的（推断只能标「推测」另列，禁止包装成原话或「真实回答」）？"
                    "结论选了①还是②、每句都有出处吗？"
                ),
                # 门控分工：子1 只管「定义质量」（结构可判项），真值判给子3（验真）+ 子5（用户认可）。
                # 双合法结论（demo 2026-07-25 行3）：问题成立要可证伪；问题不成立要原话佐证——
                # 否则诚实回答「没有痛点」永远过不了，逼模型编造痛点（行2「好奇心缺口」被 judge 识破）。
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace 且 sub_step==1 的记录；"
                    f"形式要件：{_STEP1_FORM_REQUIREMENTS}。"
                    "质量判据（从严裁量）：各答案非空泛复述；①的痛点须可观察、"
                    "非编造包装（「好奇心缺口」式伪痛点判 block）；②的无痛点声明"
                    "须以原话为证——本步 AskUserQuestion 事实性补问的回答原话"
                    "（含用户否认有痛点）是合法佐证；用户从未被问及时的「未提及」"
                    "不算佐证（须先问再引），无佐证=偷懒判 block；逼问不足 3 类判 block。"
                    "who 类出处只认用户自述（会话中用户明确声明身份）；"
                    "仓库事实（CLAUDE.md/git config 等）不能证明当前提问者身份，"
                    "作出处=无出处推断，判 block；「未自述身份」的如实标注可接受。"
                ),
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
                    "5 Whys/鱼骨/时序分析），每环必须有可观察证据"
                    "（用户原话/日志/codegraph 输出/数据），禁纯叙事；"
                    "③每个问题 ≥1 个竞争假设 + 排除理由（或当前假设为何最可能）；"
                    "④区分近因与根因，标注置信度。"
                    "输出走 evidence skill-trace（q/a 数组），不建单独 md。"
                ),
                input="step1.real_problem",
                record=True,
                selfcheck=(
                    "单一/复合判定了吗（复合→MECE 原子清单合起来覆盖全部痛点；"
                    "单一→附「无复合」理由）？每个原子问题 ≥2 环因果链、每环标注证据出处了吗？"
                    "每个问题有 ≥1 竞争假设+排除/保留理由吗？近因/根因区分和置信度标了吗？"
                ),
                # 门控分工：judge 只判结构完整性（清单/链/竞争假设/出处），
                # 根因对不对归子3验真 + 子5用户认可（§3.5 三层分工）。
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace 且 sub_step==2 的记录；"
                    "形式要件：①原子问题清单（≥1 个；单问题须附「无复合」理由）；"
                    "②每个问题 ≥2 环因果链到根因，每环标注证据出处（原话/日志/codegraph/数据）；"
                    "③每个问题 ≥1 竞争假设 + 排除/保留理由；④近因与根因区分明确。"
                    "质量判据（从严裁量）：证据非编造、非循环复述提问；"
                    "根因非症状换说法（「X 慢因为 X 运行慢」式同义反复判 block）；"
                    "竞争假设非稻草人（明显不成立拿来凑数判 block）。"
                ),
            ),
            # 子3/子4（2026-07-26 重设计，designs/step3-verify-redesign-design.md）：
            # 旧单步「验真」对 F1 主张不可检验/F2 确认偏误/F5 证据不可追溯/F7 单视角
            # 四类失效无防御。按失效模式族拆两步：子3 管取证过程（双向+多源），
            # 子4 管判断质量（质检+对抗+裁决）。用户硬约束：禁 tavily/WebSearch。
            Step(
                kind="tool",
                ref="curl(OpenAlex/arXiv/StackExchange/HN/GitHub API) / WebFetch / codegraph impact {sym}",
                short="双向取证",
                # 规则考古出处（harness-prompt-optimization P2：规则留 purpose 原文，
                # 考古只挪到注释）：反证时序留痕要求源自 demo fbdb6ebd 子3 block 实录
                # （形式要件披露，非松判据）；禁探查凭证源自 demo 121320fe
                # （扫 env/配置文件找 token 被安全分类器拦截）。
                purpose=(
                    "双向取证：对子2拆出的每个原子问题逐个取证（允许「部分成立」）。"
                    "①主张可检验化——每个原子问题 → 可证伪 claim + 事先写死「什么证据会证实/"
                    "什么证据会证伪」；不可检验的主张退回子2，不进入取证。"
                    "②证伪优先——先构造反证查询（X 已解决/是反模式/不成立）并留痕，再搜支持证据；"
                    "每个原子问题的留痕按「反证查询（先）→支持证据（后）」分段书写，"
                    "时序须从 trace 文本直接可读——执行了但留痕看不出先后 = 判 block。"
                    "③五层源各 ≥1 次尝试留痕：学术(OpenAlex/arXiv，curl 免费 API)、"
                    "社区(StackExchange/HN Algolia，curl)、开源(GitHub API，curl 带 "
                    "$GITHUB_TOKEN)、定点网页(WebFetch 抓上述层发现的 URL)、"
                    "内部仓库(codegraph+Read/Grep+Bash 查数据，证实/证伪问题在本仓存在+查已有解法)；"
                    "源层不可用显式标记「未取证+原因」是合法留痕；禁 tavily_search/WebSearch。"
                    "外部源认证失败（如 GitHub API 401）禁止探查凭证——"
                    "扫 env/配置文件找 token 是红线行为，必被安全分类器拦截；"
                    "直接标「未取证+未认证」即可，不扣分。"
                    "④codegraph 新鲜度前置——内部取证前查索引新鲜度（>72h 先 codegraph sync），"
                    "新鲜度查询结果留痕。"
                    "禁拿训练记忆冒充外部证据（无 URL/工具留痕的「业界通常」= 编造）。"
                ),
                input="step2.problem_list",
                record=True,
                selfcheck=(
                    "每个原子问题有可检验 claim（含证实/证伪判定标准）吗？"
                    "留痕按「反证查询（先）→支持证据（后）」分段、时序从文本直接可读吗？"
                    "五层源各 ≥1 次尝试（或标「未取证+原因」）吗？codegraph 新鲜度查询留痕了吗？"
                ),
                # S15 前置围栏：本步合法工具 = curl 五层源（Bash）+ 定点网页（WebFetch）；
                # codegraph 在常驻 Bash 模式内，无需声明。
                fence_allow=("Bash", "WebFetch"),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace 且 sub_step==3 的记录；"
                    "形式要件：每个原子问题有可检验化 claim（含证实/证伪判定标准）；"
                    "五层源各 ≥1 次尝试留痕（含合法的「未取证+原因」标记）；"
                    "反证查询时序先于支持查询；codegraph 新鲜度查询留痕。"
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
                    "起独立红队子代理尝试推翻初步结论（独立上下文，只给证据不给结论）："
                    "用 `python3 ~/.dl-workflow/dl-flow-engine.py redteam-prompt` 生成红队 "
                    "prompt（自动携带子1-3 证据+对抗纪律），Agent 工具单发起，"
                    "禁止手拼 prompt；触发条件写死，不得自定义「不需要复核」豁免；"
                    "③四态结论合成——证实/证伪/部分成立/证据不足（证据不足是合法结论）"
                    "+ 推理链 + 置信度；"
                    "④按 verdict 处置问题集——证伪项剔除（留剔除理由）/部分成立项收窄到"
                    "已证实边界/证据不足项带标记进入读回；处置后问题集 = 子5 唯一输入。"
                ),
                input="step3.traces",
                record=True,
                selfcheck=(
                    "每条计数证据逐条列出三关质检结果了吗（E1…En × 三关，汇总声明不算记录）？"
                    "红队触发条件满足时起了红队子代理吗（独立上下文、只给证据不给结论、四要求 a-d）？"
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
                    "质量判据（从严裁量）：红队触发条件满足时必须见红队 trace（独立上下文、"
                    "只给证据不给结论）；verdict 与证据间推理链非跳跃；"
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
                ),
                input="step4.disposed_problem_set",
                record=True,
                selfcheck=(
                    "每条陈述单句只含 1 个独立痛点吗（「和/以及/同时」连接多痛点=复合未拆净，"
                    "回子2重拆）？脱离本会话可独立理解吗（主语+动词+约束自包含）？"
                    "携带 verdict 边界与置信度了吗？证伪项不在陈述集里吧？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含本子步骤 skill-trace 记录；"
                    "形式要件：处置后问题集每个存活问题各 ≤1 句且含主语+动词+约束"
                    "（原子+去上下文）；陈述携带 verdict 与置信度。"
                    "质量判据（从严裁量）：陈述集与子4 verdict 逐项一致——证伪项不得出现在"
                    "陈述集、部分成立项陈述不得超出已证实边界（裁决不传导判 block）；"
                    "单句含多目标并列（「和/以及/同时」连接多个独立痛点）= 复合问题未拆解，判 block。"
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
                    "用户对各项的认/否/搁置记入 trace（用户认可本身是裁决留痕）"
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
        # 无 hold_for_gate（用户决议 2026-07-27）：门栏移到 understand:2——
        # 完整跑「开始 -> 明确目标和价值」中途不扣留；ProblemContext 子6 读回确认
        # 已守「陈述的认可」，子阶段边界不再是显式用户裁决点。
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
                    "②solutioneering 剥离——目标陈述含方案名词/实现动词"
                    "（「做一个X」「实现Y」）-> WHY 问一层（「为什么要 X」）剥到 outcome 状态；"
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
                    "含方案名词的目标剥到 outcome 了吗？目标间冲突检测做了吗"
                    "（无冲突须显式声明）？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=GoalsAndValue 且 sub_step==2 的记录；"
                    "形式要件：双向追溯矩阵逐项列出（每个目标 ≥1 问题回溯；"
                    "每个存活问题有承接目标或显式搁置+理由）；孤儿项显式处置留痕；"
                    "含方案名词/实现动词的目标已改写为 outcome；目标间冲突已标注"
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
                    "④solution-free 复核（归一化后仍含方案名词=子2 剥离不净，回子2）；"
                    "放不进一句=未定义完。"
                ),
                input="step3.valued_goals",
                record=True,
                selfcheck=(
                    "每条陈述单句只含 1 个独立目标吗（「和/以及/同时」连接多目标="
                    "复合未拆净，回子1 重引）？脱离本会话可独立理解吗"
                    "（主语+动词+约束自包含）？携带 must/nice 提案与 verdict 边界了吗？"
                    "无方案名词残留吧？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=GoalsAndValue 且 sub_step==4 的记录；"
                    "形式要件：子3 目标集每项各 ≤1 句且含主语+动词+约束（原子+去上下文）；"
                    "陈述携带 must/nice 提案与边界。"
                    "质量判据（从严裁量）：陈述集与子3 逐项一致——分层/边界不传导判 block；"
                    "单句含多目标并列=复合未拆净判 block；"
                    "含方案名词/实现动词=solutioneering 残留判 block。"
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
                    "（供后续 dl 实例接续，不丢弃）。"
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
        # §subphase-hold-gate（用户决议 2026-07-27，自 understand:1 移来）：
        # 门栏守住「进不进 understand:3」——「问题 + 目标价值」是 understand 的地基组，
        # 跑完GoalsAndValue = 显式用户裁决点（一轮完整跑 ProblemContext+GoalsAndValue
        # 后在此停，用户 /dl gate 放行才进范围与约束）。
        hold_for_gate=True,
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
                    "路径/模块级才机械可核查）；双向追溯：每个 in-scope 项回溯 ≥1 "
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
                    "全程只提案、没替用户拍板吧？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=ScopeAndConstraints 且 sub_step==3 的记录；"
                    "形式要件：in/out 双侧清单；双向矩阵完备（目标×范围项逐项）；"
                    "孤儿项显式处置；约束回写已记录。"
                    "质量判据（从严裁量）：out-of-scope 空清单 = 无真实取舍"
                    "从严裁量；矩阵放水（明显无关联的目标-范围硬连）判 block；"
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
                    "归一化陈述：对子3 范围与约束集逐项产出归一化陈述——"
                    "①原子（单句 ≤1 个独立范围项/约束，「和/以及/同时」连接多项="
                    "复合未拆净，回子3）；"
                    "②去上下文（脱离本会话可独立理解：主语+动词+约束自包含）；"
                    "③携带类型标签（约束=已验证 or 假设+置信度；范围=in or out）"
                    "与 verdict 边界（部分成立目标的范围只覆盖已证实边界——"
                    "裁决传导，同构 ProblemContext 子5）；"
                    "④solution-free 复核（范围项含方案名词 = GoalsAndValue 子2 "
                    "剥离不净残留）。放不进一句=未定义完。"
                ),
                input="step3.scope_proposal",
                record=True,
                selfcheck=(
                    "每条陈述单句只含 1 个独立范围项/约束吗（「和/以及/同时」连接"
                    "多项=复合未拆净，回子3）？脱离本会话可独立理解吗"
                    "（主语+动词+约束自包含）？携带类型标签（已验证/假设+置信度/"
                    "in/out）与 verdict 边界了吗？无方案名词残留吧？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=ScopeAndConstraints 且 sub_step==4 的记录；"
                    "形式要件：子3 范围与约束集每项各 ≤1 句且含主语+动词+约束"
                    "（原子+去上下文）；陈述携带类型标签（已验证/假设+置信度/"
                    "in/out）与边界。"
                    "质量判据（从严裁量）：陈述集与子3 逐项一致——类型标注/边界"
                    "不传导判 block；单句含多项并列=复合未拆净判 block；"
                    "含方案名词/实现动词=solutioneering 残留判 block。"
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
                    "understand.md（供后续 dl 实例接续，不丢弃）。"
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
        # §subphase-hold-gate（用户决议 2026-07-27）：新编排阶段隔离测试——
        # 本子阶段跑完扣留等 /dl gate，验证没问题再流入 understand:4。
        # 门栏位置现状：understand:1=无，understand:2=有，understand:3=有（本节点）。
        hold_for_gate=True,
    ),
    "understand:4": Node(
        label="定义成功标准和验收方式",
        phase="understand",
        sub=4,
        skill=None,
        artifact="understand.md",  # 末子阶段写产物
        gate_mech=GateMech.ARTIFACT_EXISTS,
        gate_rubric=None,  # 子阶段级 rubric 删除（被 sub_steps 逐步门控取代）
        advance="phase",  # 末子阶段 -> 推进到 plan（过 understand->plan 闸门）
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
                    "（纪律同 GoalsAndValue 子2）。"
                    "消费契约锚点：成功标准是 review 阶段 gate 判定 "
                    "solved/partial/not 的依据——写每条候选时想象 review 时拿什么判它。"
                ),
                input="GoalsAndValue.step4.statements + ScopeAndConstraints.step4.statements",
                record=True,
                selfcheck=(
                    "每个 must 目标都做了验收视角提问「怎么知道它达成了」吗？"
                    "双向追溯逐项列出了吗（每目标 ≥1 候选或定性+理由；"
                    "每候选回溯 ≥1 目标）？含方案名词的候选剥到 outcome 了吗？"
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
                    "方案名词/实现动词残留 = solutioneering 判 block。"
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
                    "④solution-free 复核（含方案名词 = 子1 剥离不净残留）。"
                    "放不进一句 = 未定义完。"
                ),
                input="step3.criteria_with_acceptance",
                record=True,
                selfcheck=(
                    "每条陈述单句只含 1 个独立标准吗（「和/以及/同时」连接多项 = "
                    "复合未拆净，回子1）？脱离本会话可独立理解吗"
                    "（主语+动词+约束自包含）？验收包六字段"
                    "（指标/基线/阈值提案/方法/时机/证据形式）都传导了吗？"
                    "无方案名词残留吧？"
                ),
                gate=(
                    "evidence/<name>.jsonl 含 kind=skill-trace、"
                    "minor_stage=SuccessCriteria 且 sub_step==4 的记录；"
                    "形式要件：子3 标准集每项各 ≤1 句且含主语+动词+约束"
                    "（原子+去上下文）；陈述携带完整验收包六字段与边界。"
                    "质量判据（从严裁量）：验收包字段不传导——子3 已定的"
                    "方法/时机/证据形式在陈述中丢失或篡改判 block；"
                    "单句含多项并列 = 复合未拆净判 block；"
                    "含方案名词/实现动词 = solutioneering 残留判 block。"
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
                ),
                input="step4.statements",
                record=True,
                selfcheck=(
                    "呈现了归一化标准+验收包+退回项+「验收手段待建」清单+不确定性吗？"
                    "用户对阈值拍板与验收方式认可的两项裁决都记入 trace 了吗？"
                    "退回项显式暴露了吗？"
                ),
                gate=None,  # 交互步，gate 不跑 judge（trace 存在即过）
            ),
        ),
        minor_key="SuccessCriteria",
        # §subphase-hold-gate（用户决议 2026-07-27）：新编排阶段隔离测试——
        # 末子步过后扣留等 /dl gate。**首个 advance="phase" 的 hold 节点**：
        # 门栏放行 ≠ 阶段推进（release_subgate 对 advance="phase" 节点只放行不推进），
        # 放行后模型写 understand.md + PHASE_DONE 撞 understand->plan 大闸门
        # （第二次 /dl gate，两次连拍是用户已接受的代价）。
        hold_for_gate=True,
    ),
    # ---------- plan ----------
    "plan:0": Node(
        label="生成执行计划",
        phase="plan",
        sub=0,
        skill="superpowers:using-superpowers",
        artifact="plan.md",
        gate_mech=GateMech.ARTIFACT_EXISTS,
        gate_rubric="plan 是否针对真实问题设计：①步骤可执行 ②验证方法明确 ③守 H8/H9。",
        advance="phase",  # -> execute（过 plan->execute 闸门）
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
