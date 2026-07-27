#!/usr/bin/env python3
"""
dl-flow-engine - 工作流编排内核（唯一真源）。

对应 designs/tui-state-machine-design.md §3。
定义节点树（大节点 + 子节点）+ skill 映射 + gate 判据 + 推进逻辑。
被 hooks（workflow_phase.py / workflow_advance.py）在事件点咨询,不当主进程。

定位（design §2 命名澄清）：TUI 是执行者,engine 是编排者。
- engine 编排：节点树 / 每节点 skill / gate 判据 / 何时推进（定义流程 + 决定流转）。
- engine 不进程驱动：不开 `while: claude -p(...)` 主动调主流程模型轮次。
  主流程回合由 TUI + Stop 事件驱动。
- engine 在两时刻被咨询：UserPromptSubmit（载哪个 skill）、Stop（过 gate 否）。

本阶段（§8.1）= 纯库骨架：节点树 + current_node + run_gate(机械项) + advance + CLI。
judge（语义 gate）在 §8.2 接入；hook 接入在 §8.3。

CLI（供 dl-cmd.sh / 手动覆盖调用）：
  python3 dl-flow-engine.py status  <name>   查当前节点
  python3 dl-flow-engine.py current <name>   输出当前节点定义（json）
  python3 dl-flow-engine.py advance <name>    推进到下一节点（写 state.json）
"""

from __future__ import annotations

import argparse
import enum
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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

# 子步骤门控连续 block 升级阈值：达到后不再让模型盲目重做，
# 注入提示请用户裁决（补充信息 / /dl step-pass 强制放行 / /dl back 回退）。
# rubric 对用户是黑盒，升级出口是「用户裁决」而非「放宽判据」。
SUB_STEP_BLOCK_ESCALATE = 3

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
        # §subphase-hold-gate（2026-07-26）：子6 读回确认守住「陈述的认可」，
        # 门栏守住「进不进 understand:2」——ProblemContext 是地基，完成点=显式用户裁决点。
        hold_for_gate=True,
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
        # 无 hold_for_gate（用户决议 2026-07-26）：保持「子阶段间无闸门」原设计；
        # 子5 用户读回已含一层用户裁决，understand->plan 大闸门在 understand:4 后兜底。
    ),
    "understand:3": Node(
        label="确定范围与约束",
        phase="understand",
        sub=3,
        skill=None,
        artifact=None,
        gate_mech=GateMech.NONE,
        gate_rubric=None,
        advance="sub",
        minor_key="ScopeAndConstraints",
    ),
    "understand:4": Node(
        label="定义成功标准和验收方式",
        phase="understand",
        sub=4,
        skill=None,
        artifact="understand.md",  # 末子阶段写产物
        gate_mech=GateMech.ARTIFACT_EXISTS,
        gate_rubric="对照注入的真实问题：①是否重述真实问题(非字面) ②边界 in/out-scope ③可验证成功标准。缺任一 block。",
        advance="phase",  # 末子阶段 -> 推进到 plan（过 understand->plan 闸门）
        minor_key="SuccessCriteria",
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


# ---------- 推进（design §5.1 advance）----------


def next_node_id(cur_phase: str, cur_sub: int) -> tuple[str, int] | None:
    """当前节点的下一节点 (phase, sub)。终结返回 None。

    推进规则（design §3 Node.advance 字段）：
    - cur 节点 advance="sub"  -> 同 phase, sub+1（下一子阶段）
    - cur 节点 advance="phase" -> 下一 phase 首节点（下一 phase 有子阶段=sub=1, 无=sub=0）
    - cur 节点 advance="done"  -> None（终结）
    """
    node = get_node(cur_phase, cur_sub)
    if node.advance == "done":
        return None
    if node.advance == "sub":
        return cur_phase, cur_sub + 1
    # advance == "phase"：进下一 phase 首节点
    nxt = next_phase(cur_phase)
    if nxt is None:
        return None  # 末 phase 但 advance 非 done（数据不一致,不应发生）
    return nxt, (1 if sub_total(nxt) > 0 else 0)


# ---------- state.json 读写（design §4 schema 演进）----------
#
# schema：沿用现有 dl-lib.sh:142 结构 + 新增 node / node_attempts 字段。
# 旧 state（无新字段）向后兼容：读时缺则按 phase+sub 推导补默认。
# 主 repo 根反查沿用 workflow_phase.py:101 范式（git rev-parse --git-common-dir）。


def resolve_project_root(cwd: str) -> Path | None:
    """从 cwd（通常 worktree 内）反查主 repo 根。

    worktree 内 --git-common-dir 返回主 repo .git 绝对路径 -> parent = 主 repo 根。
    主 repo 内返回 ".git" 相对 -> 回退 --show-toplevel。
    """
    try:
        res = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            common = res.stdout.strip()
            if common != ".git":
                return Path(common).parent
        res2 = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res2.returncode == 0 and res2.stdout.strip():
            return Path(res2.stdout.strip())
    except (subprocess.SubprocessError, OSError):
        pass
    return None


def resolve_workflow_name(cwd: str) -> str | None:
    """从 cwd（worktree 路径）反查工作流名。路径含 .claude/worktrees/<name>。"""
    parts = Path(cwd).parts
    if "worktrees" in parts:
        i = parts.index("worktrees")
        if i + 1 < len(parts):
            return parts[i + 1]
    return None


def stamp_commit_sha(cwd: str) -> str:
    """取 worktree 内项目 repo 当前 HEAD SHA（防腐锚点,evidence-chain-design §6.1）。

    取不到（非 git / 无 commit）-> 空串（不阻断,事后回溯降级）。
    收口到 engine:evidence_append.py 旧 _stamp_commit_sha 范式迁此。
    """
    try:
        res = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass
    return ""


def state_path(project_root: Path, name: str) -> Path:
    return project_root / ".claude" / "workflows" / name / "state.json"


def load_state(project_root: Path, name: str) -> dict[str, Any] | None:
    f = state_path(project_root, name)
    if not f.exists():
        return None
    try:
        with f.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    """补齐新字段（node / node_attempts / sub_step_index）,旧 state 向后兼容。

    守 no silent fallback：node 字段缺失时按 phase+sub 推导补默认,不静默用错值。
    推导值与显式 node 不一致时**报错暴露**（防两者失同步）。
    §orchestration v2：sub_step_index 缺失按节点有无 sub_steps 补默认（1 / 0）；
    显式值与 sub_steps 总数不符（超出范围）-> 报错暴露。
    """
    phase = state.get("phase", "understand")
    sub = state.get("sub_index", 1 if sub_total(phase) > 0 else 0)
    derived = current_node_id(phase, sub)
    if "node" not in state:
        state["node"] = derived
    elif state["node"] != derived:
        # 显式 node 与 phase+sub 推导不一致 -> 暴露,不猜
        raise ValueError(
            f"state.node={state['node']!r} 与 phase+sub 推导={derived!r} 不一致"
        )
    state.setdefault("node_attempts", 0)
    # §substep-gate-at-stop S1：子步骤门控判定游标（key=<node>#<sub_step> -> 最新已判 trace 行 sha1）。
    state.setdefault("last_judged_trace", {})
    # §substep-gate-at-stop S10：PreToolUse 步骤围栏开关（/dl fence on|off）。
    state.setdefault("enforce_step_fence", True)
    # §orchestration v2：sub_step_index 补默认 + 范围校验
    node = get_node(phase, sub)
    if node.sub_steps:
        if "sub_step_index" not in state:
            state["sub_step_index"] = 1  # 有子步骤 -> 起于首步
        else:
            n = state["sub_step_index"]
            total = len(node.sub_steps)
            if not (1 <= n <= total):
                raise ValueError(
                    f"state.sub_step_index={n} 越界（节点 {derived} 有 {total} 子步骤）"
                )
    else:
        state.setdefault("sub_step_index", 0)  # 无子步骤 -> 0
    return state


def save_state(project_root: Path, name: str, state: dict[str, Any]) -> None:
    f = state_path(project_root, name)
    f.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _now()
    with f.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


# ---------- 推进写 state（design §5.1 advance）----------


def advance_state(project_root: Path, name: str, via: str = "auto") -> dict[str, Any]:
    """推进当前节点到下一节点,写 state.json。返回新 state。

    - 子阶段推进（advance="sub"）：sub_index++,node 更新,node_attempts 归零。
    - 阶段推进（advance="phase"）：phase 进下一,node/sub/gate 更新;若跨闸门需 gate=passed（调用方负责）。
    - 终结（advance="done"）：gate="done",不推进。
    """
    state = load_state(project_root, name)
    if state is None:
        raise FileNotFoundError(f"工作流 {name} 的 state.json 缺失")
    state = normalize_state(state)

    cur_phase = state["phase"]
    cur_sub = state["sub_index"]
    cur_node = get_node(cur_phase, cur_sub)
    now = _now()

    # 记 history exit
    hist = state.get("history", [])
    if hist and hist[-1].get("exited_at") is None:
        hist[-1]["exited_at"] = now
        hist[-1]["via"] = via

    nxt = next_node_id(cur_phase, cur_sub)
    if nxt is None:
        # 终结
        state["gate"] = "done"
        state["node_attempts"] = 0
        state["updated_at"] = now
        state["history"] = hist
        save_state(project_root, name, state)
        return state

    nxt_phase, nxt_sub = nxt
    hist.append(
        {
            "phase": nxt_phase,
            "sub": nxt_sub,
            "entered_at": now,
            "exited_at": None,
            "via": via,
        }
    )
    state["phase"] = nxt_phase
    state["index"] = phase_index(nxt_phase)
    state["sub_index"] = nxt_sub
    state["sub_total"] = sub_total(nxt_phase)
    state["node"] = node_id(nxt_phase, nxt_sub)
    # 阶段推进：进新 phase 的 gate。若新 phase 是闸门目标(cur in GATED_AFTER)
    #   则本次推进已是放行后,新 phase gate=passed;否则 pending。
    if cur_node.advance == "phase" and is_gated_after(cur_phase):
        state["gate"] = "passed"
    else:
        state["gate"] = "pending"
    state["node_attempts"] = 0  # 新节点重试计数归零
    state["history"] = hist
    save_state(project_root, name, state)
    return state


# ---------- gate 裁决记录（design §8.6：gate-pass 写证据,替代旧 ### EVIDENCE 溯源）----------
#
# design §8.6 + 用户决策（2026-07-23）：旧「模型每轮自发记 claim/依赖/证据」溯源系统弃用,
# 改为 gate 判定通过时记一笔「此节点输出经审核合格」的裁决记录。
# 落点沿用 <项目>/.claude/evidence/<name>.jsonl（per-workflow,与旧系统同文件,新记录 kind=gate）。
# 只在 gate pass 时写（block 不写;block 的重试计数在 state.node_attempts,pass 时一并记 attempts）。


def _evidence_path(project_root: Path, name: str) -> Path:
    return project_root / ".claude" / "evidence" / (name + ".jsonl")


def read_evidence(project_root: Path, name: str) -> str | None:
    """读 evidence/<name>.jsonl 全文，供 judge 作 artifact_content 校验。

    §define-problem-verify-gate：understand:1 的 rubric 依赖 evidence.jsonl，
    Stop hook 调本函数取文件文本喂 judge。缺失/读失败返回 None
    （no silent fallback：judge 拿不到证据 -> 按 rubric 判 block，不默认放行）。
    """
    p = _evidence_path(project_root, name)
    try:
        return p.read_text(encoding="utf-8") if p.exists() else None
    except OSError:
        return None


def write_gate_verdict(
    project_root: Path,
    name: str,
    node: Node,
    attempts: int,
    cwd: str,
    via: str = "auto-stop",
    sub_step: int | None = None,
) -> bool:
    """gate pass 时写一笔裁决记录到 evidence/<name>.jsonl。

    记录：节点 + gate=passed + rubric（审据;None=仅机械过）+ attempts（重试次数）+
    gate_mech（机械类型）+ ts + commit_sha（防腐锚点）+
    major_stage/minor_stage（2026-07-26：与 skill-trace 结构字段对齐——evidence
    里所有记录都携带编排阶段标识，取值单源 = node.phase / node.minor_key；
    整阶段节点 minor_key=None -> minor_stage 写 null，显式不猜）。
    sub_step 非 None 时记入（子步骤级裁决，如 /dl step-pass 手动放行，
    此时 via 标识裁决来源）。
    返回 True=写入成功;False=写失败（no silent fallback：失败留痕由调用方 log,不阻断）。
    """
    record = {
        "kind": "gate",
        "node": node_id(node.phase, node.sub),
        "phase": node.phase,
        "sub": node.sub,
        "label": node.label,
        "major_stage": node.phase.capitalize(),
        "minor_stage": node.minor_key,
        "gate": "passed",
        "gate_mech": node.gate_mech.value,
        "rubric": node.gate_rubric,  # None=仅机械过（无语义审）
        "attempts": attempts,
        "skill": node.skill,
        "via": via,
        "ts": _now(),
        "commit_sha": stamp_commit_sha(cwd),
    }
    if sub_step is not None:
        record["sub_step"] = sub_step
    path = _evidence_path(project_root, name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        return False
    return True


# ---------- gate（compound + 短路;design §5）----------
#
# design §5：机械项（py 规则）+ 语义项（judge）。
#   机械不过 -> 短路 block（不跑 judge,省一次模型调用）。
#   机械过 -> 跑 judge（stateless claude -p）判"符合预期吗"。
# judge 继承主会话 env（design §9 #2）;返回 {pass:bool, reason:str}。


# judge 的 claude -p 调用超时（秒）。judge 是判据非生成,给足但要防挂。
JUDGE_TIMEOUT = 120
# judge 调用失败（API 错/超时/解析失败）时的策略：
#   design §5.1 降级 = 不推进 + 返回 block（no silent fallback：失败必暴露,不默认放行）。

# judge 专属 system prompt（--system-prompt 全量替换默认 coding 助手人设）。
# 2026-07-25 demo 实测：judge 单次 ~20.7k 输入里 ~95% 是 harness 开销（全套工具
# schema + 默认 system prompt + skill 列表），判决载荷（判据+trace+输出）仅 ~0.7k。
# --tools "" + --system-prompt 只裁 harness、判决 prompt 逐字不动，settings/认证
# 链零触碰（ac-ark env 继承与 settings.json env 用户都照常）。实证：同一真实
# pass 案例重放，输入 20728 -> 3590（-83%），判决一致。
JUDGE_SYSTEM_PROMPT = (
    "你是工作流节点门控的评审 judge。"
    "严格按用户消息里的判据判定，只输出一个 JSON,不要多余文本。"
)


def gate_verdict_mech(node: Node, project_root: Path | None = None) -> str | None:
    """机械门判定。返回 None=通过,返回字符串=block 原因。

    project_root 用于产物文件存在检查（None 时机械项降级为只判 NONE）。
    """
    if node.gate_mech == GateMech.NONE:
        return None  # 无机械门,通过
    if project_root is None:
        # 无 project_root 无法判文件 -> 降级放行（宁纵勿枉,同 codegraph_gate 非 git 放行）
        # 语义 judge 兜底。
        return None
    if node.gate_mech == GateMech.ARTIFACT_EXISTS:
        if not node.artifact or "/" in node.artifact or node.artifact.endswith("+"):
            # 产物标识含描述性文本（如"代码+commit+测试通过"）非单文件 -> 机械无法判,交语义 judge
            return None
        # 产物文件路径：worktree/.claude/workflows/<name>/ 或约定根。
        # 暂以 worktree 根下查找（understand.md 等约定写在 worktree 根）。
        # TODO §8.3 确认产物落点后精确化。
        return None  # 暂不实现文件查找,留 §8.3 hook 接入时连同产物路径一起定
    if node.gate_mech == GateMech.TEST_PASS:
        return None  # 暂不实现,留 §8.2/§8.3
    return None


def rubric_needs_evidence(node: Node) -> bool:
    """节点的 gate_rubric 是否依赖 evidence.jsonl（决定 hook 要否读文件喂 judge）。

    §define-problem-verify-gate：rubric 文本含 "evidence/" 或 "skill-trace" 即视为依赖
    （rubric 自带关键词 -> 单源驱动 workflow_advance 读文件 + workflow_phase 注入 trace 写法）。
    无 rubric / 不含关键词 -> False（understand:2-3 等无语义审节点，行为不变）。
    """
    r = node.gate_rubric or ""
    return "evidence/" in r or "skill-trace" in r


def sub_step_total(node: Node) -> int:
    """节点子步骤数（0=无编排）。§orchestration v2 D2。"""
    return len(node.sub_steps) if node.sub_steps else 0


def sub_step_at(node: Node, n: int) -> Step | None:
    """取第 n 子步骤（1-based）；越界/无子步骤返回 None。"""
    if not node.sub_steps or not (1 <= n <= len(node.sub_steps)):
        return None
    return node.sub_steps[n - 1]


def step_needs_evidence(step: Step) -> bool:
    """子步骤是否需读 evidence.jsonl 喂 judge（与 rubric_needs_evidence 同关键词判定）。

    §orchestration v2：子步骤 gate 文本含 "evidence/" 或 "skill-trace" 即读 evidence。
    """
    r = step.gate or ""
    return "evidence/" in r or "skill-trace" in r


def _iter_trace_segments(
    text: str, sub_step_index: int, minor_stage: str | None = None
):
    """逐行扫描 evidence 文本，产出匹配 trace 的 (raw_segment, rec)。

    容错（2026-07-25，demo 74f82d93）：Write 无尾换行 + printf 追加会让两个
    JSON 对象粘在一行，按行 json.loads 会整行跳过 -> trace「隐形」
    （S13 误判无 trace 强制参与）。用 raw_decode 循环扫一行内多个 JSON 对象。
    匹配：kind=skill-trace + sub_step == sub_step_index。
    minor_stage（2026-07-26，goals-and-value-substeps-design）：多编排节点
    （understand:1 ProblemContext / understand:2 GoalsAndValue）共用一个
    evidence 文件且 sub_step 都从 1 起——不按 minor_stage 过滤，ProblemContext
    子1 的 trace 会被 GoalsAndValue 子1 的门控/围栏误读（跨节点串号）。
    None=不过滤（向后兼容）；指定时缺 minor_stage 字段的旧记录不匹配
    （显式不算数，no silent fallback）。
    """
    decoder = json.JSONDecoder()
    for line in text.splitlines():
        s = line.strip()
        idx = 0
        while idx < len(s):
            nxt = s.find("{", idx)
            if nxt == -1:
                break
            idx = nxt
            try:
                rec, end = decoder.raw_decode(s, idx)
            except json.JSONDecodeError:
                break  # 此行剩余部分不是合法 JSON（截断/损坏）-> 下一行
            if (
                isinstance(rec, dict)
                and rec.get("kind") == "skill-trace"
                and rec.get("sub_step") == sub_step_index
                and (minor_stage is None or rec.get("minor_stage") == minor_stage)
            ):
                yield s[idx:end], rec
            idx = end


def sub_step_has_trace(
    project_root: Path, name: str, sub_step_index: int, minor_stage: str | None = None
) -> bool:
    """evidence.jsonl 是否含 sub_step == sub_step_index 的 skill-trace 记录。

    §step-advance-on-submit E1：UserPromptSubmit 据此判断当前子步骤是否已写 evidence
    （避开 transcript flush 竞态；evidence 是上轮写、已落盘）。
    缺文件/读失败 -> False（gate 降级判 block，不默认放行）。
    匹配字段：kind=skill-trace + sub_step == sub_step_index（+ minor_stage，见
    _iter_trace_segments 的跨节点串号说明）。
    q/a 从字符串改为字符串数组（新格式兼容旧格式，单值 q/a 也匹配）。
    容一行多 JSON 对象（raw_decode 循环，见 _iter_trace_segments）。
    """
    text = read_evidence(project_root, name)
    if not text:
        return False
    return any(True for _ in _iter_trace_segments(text, sub_step_index, minor_stage))


def read_evidence_for_step(
    project_root: Path, name: str, sub_step_index: int, minor_stage: str | None = None
) -> str | None:
    """读 evidence 喂 judge 的子步骤裁剪版（2026-07-26，judge 输入 scope 化）。

    背景：子步骤 gate 原先把 evidence **全文**喂 judge，输入随步数线性膨胀
    （demo fbdb6ebd 实测 judge input 3.1k -> 14.9k，8 次累计 ~63k tokens，
    总量 O(n²)），大输入还拉高 judge 超时风险。子步骤 rubric 实际只需：
    当前步 trace（判对象）+ 前序各步**最新** trace（一致性锚点，
    如子5 rubric 要求与子4 verdict 逐项一致）。
    裁剪规则：
    - 只含 kind=skill-trace 且 sub_step ≤ sub_step_index 的记录；
    - 每个 sub_step 只留**最新一条**——返工历史不喂（judge 本就以最新为准，
      历史是纯 token 开销）；
    - kind=gate 裁决记录不喂（judge 判 trace 内容，不判裁决留痕）；
    - minor_stage 指定时只取该节点的 trace（跨节点串号见 _iter_trace_segments）。
    输出按 sub_step 升序拼行（append 协议下与原文顺序一致）。
    无文件/读失败/无匹配 -> None（与 read_evidence 同语义：judge 拿不到
    证据 -> 判 block，no silent fallback）。
    """
    text = read_evidence(project_root, name)
    if not text:
        return None
    latest: dict[int, str] = {}
    for k in range(1, sub_step_index + 1):
        for seg, _rec in _iter_trace_segments(text, k, minor_stage):
            latest[k] = seg
    if not latest:
        return None
    return "\n".join(latest[k] for k in sorted(latest))


def _advance_sub_step(
    project_root: Path, name: str, state: dict[str, Any], node: Node, cur: int, via: str
) -> dict[str, Any]:
    """子步骤推进共用段：非末步 sub_step_index++（attempts 归零）；末步 advance_state 推进子阶段。

    state 须已 normalize。返回推进后的 state。

    §subphase-hold-gate：node.hold_for_gate 的末步**无条件扣留**（不读 state.gate——
    中途 /dl gate 预放行 phase 闸门会把 gate 置 passed，读它会让门栏被静默穿过，
    见 designs/subphase-hold-gate-design.md §2）。扣留写显式标记 held_for_gate，
    唯一出口 release_subgate（/dl gate 路由）；step-pass 末步同被扣——
    步的放行与子阶段的放行是两个独立的用户决定。
    """
    if cur < len(node.sub_steps):
        state["sub_step_index"] = cur + 1
        state["node_attempts"] = 0
        state["updated_at"] = _now()
        save_state(project_root, name, state)
        return state
    if node.hold_for_gate:
        state["held_for_gate"] = True
        state["updated_at"] = _now()
        save_state(project_root, name, state)
        return state
    # 末步：推进子阶段（advance_state 含 normalize + save）
    return advance_state(project_root, name, via=via)


def release_subgate(project_root: Path, name: str, cwd: str) -> tuple[bool, str]:
    """子阶段门栏放行（/dl gate 在 held 状态下的路由出口，§subphase-hold-gate）。

    三件事（对齐 step-pass 的手动放行留痕原则）：
    1. 校验 held 标记（无标记=没在门栏前，报错暴露不猜）。
    2. write_gate_verdict(via="manual-subgate-pass", sub_step=末步)——手动放行必留痕。
    3. 清标记 + advance_state 推进子阶段（子阶段推进把 state.gate 归 pending，
       understand 末节点的 phase 闸门仍需独立 /dl gate，无语义叠加）。
    """
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    state = normalize_state(state)
    try:
        node = get_node(state["phase"], state["sub_index"])
    except KeyError:
        return False, f"节点 {state['phase']}:{state['sub_index']} 不存在"
    cur = state.get("sub_step_index", 1)
    held = (
        state.get("held_for_gate")
        and node.hold_for_gate
        and node.sub_steps
        and cur == len(node.sub_steps)
    )
    if not held:
        return False, f"节点 {node_id(node.phase, node.sub)} 不在门栏扣留状态"
    ok = write_gate_verdict(
        project_root,
        name,
        node,
        state.get("node_attempts", 0),
        cwd,
        via="manual-subgate-pass",
        sub_step=cur,
    )
    if not ok:
        return False, "裁决记录写 evidence 失败（未放行；见权限/磁盘）"
    state.pop("held_for_gate", None)
    state["updated_at"] = _now()
    save_state(project_root, name, state)
    advance_state(project_root, name, via="manual-subgate-pass")
    nxt_phase, nxt_sub = next_node_id(node.phase, node.sub)
    return (
        True,
        f"门栏放行：{node.label} 已批准 -> 推进 {node_id(nxt_phase, nxt_sub)}",
    )


def gate_and_advance_sub_step(
    project_root: Path, name: str, node: Node, sub_step_index: int
) -> tuple[bool, str, dict[str, Any]]:
    """gate 当前子步骤 + 推进。返回 (advanced, reason, new_state)。

    §step-advance-on-submit E2（3a）：gate+推进合一，供 UserPromptSubmit 调用。
    - gate=None 自动过；否则 run_judge（artifact_content = read_evidence_for_step 裁剪版）。
    - advanced=True：已推进（非末步 sub_step_index++ / 末步 advance_state 推进子阶段）。
    - advanced=False：block（未推进，返回 reason，模型需重做）。
      block 时累加 state.node_attempts 并落盘（sub_step 路径的重试计数，
      连续 block 达 SUB_STEP_BLOCK_ESCALATE 后 hook 升级为用户裁决）。
    new_state：推进后/计数后的 state（供注入取 sub_step_index/node_attempts）；
    前置校验失败（步骤不存在/state 缺失）时为 {}。
    """
    step = sub_step_at(node, sub_step_index)
    if step is None:
        return False, f"子步骤 {sub_step_index} 不存在", {}
    if step.gate is None:
        ok, reason = True, ""
    else:
        artifact = read_evidence_for_step(
            project_root, name, sub_step_index, node.minor_key
        )
        ok, reason = run_judge(
            step.gate,
            f"{node.label} · 子步骤{sub_step_index}",
            "",
            artifact_content=artifact,
        )
    if not ok:
        state = load_state(project_root, name)
        if state is not None:
            state = normalize_state(state)
            state["node_attempts"] = state.get("node_attempts", 0) + 1
            state["updated_at"] = _now()
            save_state(project_root, name, state)
            return False, reason or "judge 未给出原因", state
        return False, reason or "judge 未给出原因", {}
    # 推进
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失", {}
    state = normalize_state(state)
    return (
        True,
        "",
        _advance_sub_step(
            project_root, name, state, node, sub_step_index, via="step-submit"
        ),
    )


def force_pass_sub_step(project_root: Path, name: str, cwd: str) -> tuple[bool, str]:
    """用户裁决强制放行当前子步骤（/dl step-pass；连续 block 达阈值后的升级出口）。

    与 judge pass 同路径推进（非末步 sub_step_index++ / 末步推进子阶段），
    但先写 kind=gate 裁决记录（via=manual-step-pass + sub_step + attempts）——
    手动放行必须留痕，否则 evidence 里该子步骤无任何通过记录。
    返回 (ok, 消息)。rubric 是黑盒：此命令是用户裁决，不修改任何判据。
    """
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    state = normalize_state(state)
    try:
        node = get_node(state["phase"], state["sub_index"])
    except KeyError:
        return False, f"节点 {state['phase']}:{state['sub_index']} 不存在"
    if not node.sub_steps:
        return (
            False,
            f"节点 {node_id(node.phase, node.sub)} 无子步骤编排，step-pass 不适用",
        )
    cur = state.get("sub_step_index", 1)
    step = sub_step_at(node, cur)
    if step is None:
        return False, f"子步骤 {cur} 不存在"
    attempts = state.get("node_attempts", 0)
    ok = write_gate_verdict(
        project_root, name, node, attempts, cwd, via="manual-step-pass", sub_step=cur
    )
    if not ok:
        return False, "裁决记录写 evidence 失败（未推进；见权限/磁盘）"
    new_state = _advance_sub_step(
        project_root, name, state, node, cur, via="manual-step-pass"
    )
    if cur < len(node.sub_steps):
        return True, f"子步骤 {cur} 已手动放行 -> 子步骤 {cur + 1}"
    if new_state.get("held_for_gate"):
        # §subphase-hold-gate：步的放行 ≠ 子阶段的放行，门栏仍需 /dl gate
        return True, f"末子步骤 {cur} 已手动放行，子阶段推进被门栏扣留 — /dl gate 放行"
    return True, f"末子步骤 {cur} 已手动放行 -> 子阶段推进"


def reset_sub_step(project_root: Path, name: str, step: int) -> tuple[bool, str]:
    """回退到子步骤 step 重测（/dl step-reset <n>；反复测试某子步骤的出口）。

    三件事（都落盘才算完成，无 silent fallback）：
    1. evidence：删 sub_step >= step 的 skill-trace 行 + gate 裁决行（保留前序步骤留痕；
       无 sub_step 字段的 gate 行=节点级裁决，保留）。
    2. state：sub_step_index=step、node_attempts=0、last_judged_trace 清掉
       「<node>#<k>」(k>=step) 游标（不清会让同内容 trace 被判「无新产出」静默跳过）。
    3. 不改 phase/sub_index（只在本节点子步骤内回退，跨子阶段用 /dl back）。
    """
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    state = normalize_state(state)
    try:
        node = get_node(state["phase"], state["sub_index"])
    except KeyError:
        return False, f"节点 {state['phase']}:{state['sub_index']} 不存在"
    if not node.sub_steps:
        return (
            False,
            f"节点 {node_id(node.phase, node.sub)} 无子步骤编排，step-reset 不适用",
        )
    total = len(node.sub_steps)
    if not (1 <= step <= total):
        return False, f"子步骤 {step} 越界（本节点 1..{total}）"

    # 1. evidence 过滤（删 sub_step >= step 的 trace/gate 行；坏行原样保留不吞）
    # 多编排节点共用 evidence（goals-and-value-substeps-design）：只删**本节点**的行——
    # skill-trace 按 minor_stage、gate 按 node 归属判定；归属不明（缺字段）的行
    # 与坏行同原则保留（暴露而非吞掉），防 step-reset 误删他节点（如 ProblemContext）留痕。
    nid = node_id(node.phase, node.sub)
    removed = 0
    path = _evidence_path(project_root, name)
    if path.exists():
        kept: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                kept.append(line)  # 坏行不属于任何子步骤，保留（暴露而非吞掉）
                continue
            if not (isinstance(rec.get("sub_step"), int) and rec["sub_step"] >= step):
                kept.append(line)
                continue
            if (
                rec.get("kind") == "skill-trace"
                and rec.get("minor_stage") == node.minor_key
            ):
                removed += 1
                continue
            if rec.get("kind") == "gate" and rec.get("node") == nid:
                removed += 1
                continue
            kept.append(line)  # 他节点的行 / 归属不明的行：保留
        path.write_text("".join(line + "\n" for line in kept), encoding="utf-8")

    # 2. state 回退
    state["sub_step_index"] = step
    state["node_attempts"] = 0
    state.pop("held_for_gate", None)  # §subphase-hold-gate：回退重测时门栏状态同步失效
    judged = state.get("last_judged_trace", {})
    for k in list(judged):
        if not k.startswith(f"{nid}#"):
            continue
        try:
            n = int(k.rsplit("#", 1)[1])
        except ValueError:
            continue  # 畸形 key 不属于本节点子步骤游标，保留（暴露而非吞掉）
        if n >= step:
            del judged[k]
    state["updated_at"] = _now()
    save_state(project_root, name, state)
    return (
        True,
        f"已回退到子步骤 {step}/{total}（删 evidence 行 {removed} 条，游标/重试计数已清）",
    )


# ---------- 子步骤 Stop 门控（§substep-gate-at-stop）----------


def latest_trace_sha1(
    project_root: Path, name: str, sub_step_index: int, minor_stage: str | None = None
) -> str | None:
    """evidence.jsonl 里 sub_step == sub_step_index 的**最后一条** skill-trace 的 sha1。

    §substep-gate-at-stop S1：Stop hook 以此与 state.last_judged_trace 比对判定「有新产出」。
    用 hash 不用行数：模型违规覆盖写也产生新 hash -> 必判。无匹配/文件缺 -> None。
    容一行多 JSON 对象（raw_decode，取最后一个匹配段的 hash）。
    minor_stage 指定时只取该节点的 trace（跨节点串号见 _iter_trace_segments）。
    """
    text = read_evidence(project_root, name)
    if not text:
        return None
    latest: str | None = None
    for seg, _rec in _iter_trace_segments(text, sub_step_index, minor_stage):
        latest = seg
    if latest is None:
        return None
    return hashlib.sha1(latest.encode("utf-8")).hexdigest()


def evidence_mentions_sub_step(
    project_root: Path, name: str, sub_step_index: int, minor_stage: str | None = None
) -> bool:
    """evidence 原文是否提及 sub_step==N（raw 子串探测，不解析 JSON）。

    §S13 分诊用：latest_trace_sha1 为 None 时区分「真无 trace」（强制参与）
    vs「有内容但 JSON 损坏/被合并后仍无法解析」（提示修复格式）。
    minor_stage 指定时要求同一行同时含 sub_step 与 minor_stage 子串
    （跨节点串号见 _iter_trace_segments；行级探测防 ProblemContext 的
    同号子步骤被误判为本节点的损坏写入）。
    """
    text = read_evidence(project_root, name)
    if not text:
        return False
    needles = (
        f'"sub_step":{sub_step_index}',
        f'"sub_step": {sub_step_index}',
    )
    if minor_stage is None:
        return any(n in text for n in needles)
    mneedles = (
        f'"minor_stage":"{minor_stage}"',
        f'"minor_stage": "{minor_stage}"',
    )
    return any(
        any(n in line for n in needles) and any(m in line for m in mneedles)
        for line in text.splitlines()
    )


def corrupt_trace_after_latest(
    project_root: Path, name: str, sub_step_index: int, minor_stage: str | None = None
) -> bool:
    """最新合法 trace 之后是否存在「含 sub_step==N 子串但解析不出合法记录」的损坏行。

    §corrupt-rework-detect（2026-07-26，demo d59d05ea）：模型返工把 trace 写碎
    （shell 单引号内塞字面换行 -> JSON 跨两行；字面 \\" 原样落盘）->
    latest_trace_sha1 仍等于已判 hash -> 「同 hash 静默放行」把「写了但写坏了」
    误判为「没写新东西」-> 模型以为返工完成，工作流看似卡死（无任何日志）。
    只数**最新合法 trace 行之后**的损坏行：之前的损坏行是已处理历史（模型修好后
    旧碎片仍在文件里），不重复报警。append 协议下新写入必在最新合法行之后。
    minor_stage 指定时：合法行定位限定该节点；损坏行候选 = 含 sub_step 子串
    且【不含 minor_stage 字段（截断碎片无法归属，按本节点候选处理）或
    含本节点 minor_stage】——含**他节点** minor_stage 的行跳过（跨节点串号
    见 _iter_trace_segments）。截断碎片常丢 minor_stage 字段（demo d59d05ea
    的碎片就没有），若强制要求 minor_stage 子串会把真损坏放行回「卡死」。
    """
    text = read_evidence(project_root, name)
    if not text:
        return False
    lines = text.splitlines()
    last_valid_idx = -1
    for i, line in enumerate(lines):
        if any(True for _ in _iter_trace_segments(line, sub_step_index, minor_stage)):
            last_valid_idx = i
    needle = (
        f'"sub_step":{sub_step_index}',
        f'"sub_step": {sub_step_index}',
    )
    mneedle = (
        (f'"minor_stage":"{minor_stage}"', f'"minor_stage": "{minor_stage}"')
        if minor_stage is not None
        else None
    )
    for line in lines[last_valid_idx + 1 :]:
        if not any(n in line for n in needle):
            continue
        if (
            mneedle is not None
            and '"minor_stage"' in line
            and not any(m in line for m in mneedle)
        ):
            continue  # 明确归属他节点的行，不归本节点判
        if not any(
            True for _ in _iter_trace_segments(line, sub_step_index, minor_stage)
        ):
            return True
    return False


def _corrupt_trace_reason(sub_step_index: int) -> str:
    """损坏返工的 block 判词（§corrupt-rework-detect）：指路到格式修复，不判内容。"""
    return (
        f"evidence 写入损坏：文件里存在 sub_step=={sub_step_index} 的记录片段，"
        "但不是可解析的单行合法 JSON（手写 JSON 跨行/转义出错的典型后果）。"
        "门控读不到等同没写。返工：改用 append-trace 落库——Write 载荷 "
        '{"purpose":...,"q":[...],"a":[...]} 到 .claude/evidence/.trace-payload-*.json，'
        "再 Bash `python3 ~/.dl-workflow/dl-flow-engine.py append-trace --from-file <载荷>`"
        "（格式/路径/结构字段全归脚本，不会再写碎）。"
    )


def gate_sub_step_at_stop(
    project_root: Path, name: str, cwd: str
) -> tuple[str, str, dict[str, Any]]:
    """Stop 时刻的子步骤门控。返回 (action, reason, state)。

    §substep-gate-at-stop：触发 = 当前子步骤最新 trace hash 有变化（S1），
    区分「子步骤完成」与「中途暂停等用户」（无新 trace -> none 静默放行，S6）。
    action：
    - "none"     ：无 sub_steps / 无新 trace / state 缺失 -> hook 放行 stop
    - "advanced" ：gate pass（含 gate=None 自动过），已推进 + last_judged 已记（S3）
    - "block"    ：gate 未过（attempts < SUB_STEP_BLOCK_ESCALATE），hook 应 _block_continue 同轮返工（S4）
    - "escalate" ：连续 block 达阈值，hook 应给用户裁决文案（S7）
    block/escalate 时 last_judged 同样更新（防同一 trace 重复判 -> 天然防 loop）。
    """
    none = ("none", "", {})
    state = load_state(project_root, name)
    if state is None:
        return none
    state = normalize_state(state)
    try:
        node = get_node(state["phase"], state["sub_index"])
    except KeyError:
        return none
    if not node.sub_steps:
        return none
    cur = state.get("sub_step_index", 1)
    step = sub_step_at(node, cur)
    if step is None:
        return none
    mk = (
        node.minor_key
    )  # 跨节点串号防御：trace 匹配限定本节点（见 _iter_trace_segments）
    sha = latest_trace_sha1(project_root, name, cur, mk)
    if sha is None:
        return none  # 无 trace：中途暂停（或 evidence 路径错位,症状 L）-> 静默放行
    key = f"{node_id(node.phase, node.sub)}#{cur}"
    judged = state.setdefault("last_judged_trace", {})
    if judged.get(key) == sha:
        # §corrupt-rework-detect：同 hash 但最新合法 trace 之后有 sub_step==N 的
        # 损坏写入（JSON 跨行/字面 \"）-> 不是「没写」，是「写了门控读不到」。
        # 静默放行会让模型以为返工完成、流程看似卡死（demo d59d05ea 子3）。
        # 判 block 给格式修复指引；计 attempts（连续损坏达阈值同样升级用户裁决，
        # 防无限返工环）。游标不动：模型修好后 sha 变化 -> 走正常判定。
        if not corrupt_trace_after_latest(project_root, name, cur, mk):
            return none  # 已判过同一产出（上轮 block 后模型未写新 trace）-> 放行防 loop
        state["node_attempts"] = state.get("node_attempts", 0) + 1
        state["updated_at"] = _now()
        save_state(project_root, name, state)
        action = (
            "escalate" if state["node_attempts"] >= SUB_STEP_BLOCK_ESCALATE else "block"
        )
        return action, _corrupt_trace_reason(cur), state
    judged[key] = sha  # 判前即记：pass/block 都防重判
    if step.gate is None:
        ok, reason = True, ""
    else:
        artifact = read_evidence_for_step(project_root, name, cur, mk)
        ok, reason = run_judge(
            step.gate,
            f"{node.label} · 子步骤{cur}",
            "",
            artifact_content=artifact,
        )
    if ok:
        # 先落盘（含 last_judged[key]）：末步路径 advance_state 从磁盘重 load，
        # 不落盘会丢判定游标 -> 下次 Stop 重判同一 trace。
        save_state(project_root, name, state)
        new_state = _advance_sub_step(
            project_root, name, state, node, cur, via="step-stop"
        )
        return "advanced", "", new_state
    state["node_attempts"] = state.get("node_attempts", 0) + 1
    state["updated_at"] = _now()
    save_state(project_root, name, state)
    action = (
        "escalate" if state["node_attempts"] >= SUB_STEP_BLOCK_ESCALATE else "block"
    )
    return action, reason or "judge 未给出原因", state


# ---------- phase 写权限围栏（§substep-gate-at-stop S11）----------

# 各 phase 允许模型用结构化写工具（Edit/Write/MultiEdit/NotebookEdit）落盘的路径。
# 规则三类：basename 命中 / 路径含 designs 且 .md / 路径含 .claude/evidence。
# execute=None 表示不限制。真源对齐 phase-rules.md 各阶段「禁止」行。
_PHASE_WRITE_NAMES: dict[str, frozenset[str] | None] = {
    "understand": frozenset({"understand.md"}),
    "plan": frozenset({"plan.md", "understand.md"}),
    "execute": None,  # 不限制
    "review": frozenset({"review.md"}),
    # evolution 额外放行 .claude/(skills 更新) + memory/（沉淀），见 _phase_write_path_ok
    "evolution": frozenset({"evolution.md"}),
}


def _phase_write_path_ok(phase: str, file_path: str) -> bool:
    """路径是否命中该 phase 的写白名单（§S11）。"""
    names = _PHASE_WRITE_NAMES.get(phase)
    if names is None:
        return True  # execute（或未配置）不限制
    p = Path(file_path)
    if p.name in names:
        return True
    parts = p.parts
    if "designs" in parts and p.suffix == ".md":
        return True  # H8 design 文档各阶段可起草/补
    if ".claude" in parts and "evidence" in parts:
        return True  # evidence 任何阶段可写（子步骤编排/裁决留痕）
    if phase == "evolution":
        if ".claude" in parts:
            return True  # 更新 skill（.claude/skills/）
        if "memory" in parts and p.suffix == ".md":
            return True  # 沉淀 memory（~/.claude/projects/*/memory/）
    return False


def phase_write_denial(project_root: Path, name: str, file_path: str) -> str | None:
    """phase-fence 判定：该 phase 写 file_path 是否被拒。被拒 -> 返回 deny 原因；否则 None。

    §substep-gate-at-stop S11：把「understand/plan 禁改源码、review 禁改实现」
    从文案约束变硬约束。无 state / execute / 白名单命中 -> None（放行）。
    本围栏是系统级硬约束（同 rubric，对用户黑盒），无开关——/dl fence 只管 S10。
    """
    state = load_state(project_root, name)
    if state is None:
        return None
    state = normalize_state(state)
    phase = state.get("phase", "understand")
    if _phase_write_path_ok(phase, file_path):
        return None
    names = _PHASE_WRITE_NAMES.get(phase) or frozenset()
    allow = "、".join(sorted(names)) if names else "（无）"
    return (
        f"当前阶段「{PHASE_LABELS.get(phase, phase)}」禁止写源码/实现"
        f"（phase-rules 硬约束）。可写：{allow}、designs/*.md、.claude/evidence/。"
        f"被拒路径：{file_path}"
    )


def pending_unjudged_step(project_root: Path, name: str) -> int | None:
    """当前子步骤是否有「已写 trace 但未经门控判决」。有 -> 返回子步骤号；否则 None。

    §substep-gate-at-stop S10：PreToolUse 围栏（workflow_step_fence.py）的关闭条件。
    围栏与门控共用 last_judged_trace 游标——判完（pass/block 都记游标）即开。
    state.enforce_step_fence=False（/dl fence off）-> None（围栏停用，回文案约束）。
    """
    state = load_state(project_root, name)
    if state is None:
        return None
    state = normalize_state(state)
    if not state.get("enforce_step_fence", True):
        return None
    try:
        node = get_node(state["phase"], state["sub_index"])
    except KeyError:
        return None
    if not node.sub_steps:
        return None
    cur = state.get("sub_step_index", 1)
    if sub_step_at(node, cur) is None:
        return None
    sha = latest_trace_sha1(project_root, name, cur, node.minor_key)
    if sha is None:
        return None
    judged = state.get("last_judged_trace", {})
    if judged.get(f"{node_id(node.phase, node.sub)}#{cur}") == sha:
        return None
    return cur


def engagement_fence_state(project_root: Path, name: str) -> tuple[int, Step] | None:
    """当前子步骤处于「零 trace 窗口」-> 返回（子步骤号, Step）；否则 None。

    §step-engage-prefence S15：PreToolUse 前置参与围栏（workflow_step_fence.py）
    的触发判据——与 S13（Stop 参与围栏）同判据、单源在此。窗口内仅编排工具
    可用（常驻集 + Step.fence_allow），模型为「直接回答用户」发起的工具调用
    在第一次调用即被 deny 指回编排，不等回合末 S13 纠偏。
    与 pending_unjudged_step（S10）互斥互补：零 trace->S15 白名单；
    有未判决 trace->S10 全 deny；已判决->自由。
    state.enforce_step_fence=False（/dl fence off）-> None（围栏停用，回文案约束）。
    """
    state = load_state(project_root, name)
    if state is None:
        return None
    state = normalize_state(state)
    if not state.get("enforce_step_fence", True):
        return None
    try:
        node = get_node(state["phase"], state["sub_index"])
    except KeyError:
        return None
    if not node.sub_steps:
        return None
    cur = state.get("sub_step_index", 1)
    step = sub_step_at(node, cur)
    if step is None:
        return None
    if latest_trace_sha1(project_root, name, cur, node.minor_key) is not None:
        return None  # 有 trace（未判决/已判决）-> 归 S10/自由，非本围栏窗口
    return cur, step


# §step-selfcheck：提交前自查提示（pass 续轮与注入双通道共用，单源）。
# 动机（2026-07-26 demo 121320fe 复盘）：5 次真实 block 里 4 次违反的是已
# 逐字披露在 purpose 的形式要求——注意力失败非知识失败（被指后一轮修好）。
# 把「judge 抓」前移为「自查抓」：省 judge 调用 + 省一轮 Stop 返工往返。
STEP_SELFCHECK_HINT = (
    "STEP_DONE 前自查：逐条对照本步 purpose 的形式要件检查你的 trace——"
    "每项要求在 trace 里都须有对应记录（「我做了」式汇总声明不算），缺项先补再声明完成。"
)


def selfcheck_hint(step: Step | None) -> str:
    """提交前自查提示 = 通用段 + 按步声明的 checklist（Step.selfcheck）。

    §step-selfcheck 步级化（2026-07-26）：通用提示对弱遵从模型太抽象
    （demo d59d05ea：MiniMax-M3 子1 三连 block 全是已披露形式要件的注意力失败，
    被指后一轮即修好——§3.5 #9 注意力失败的最便宜解法是自查前移）。
    步级 checklist 只列 purpose 已披露的形式要件（Step.selfcheck 声明处已注释），
    质量判据仍只在 gate 黑盒（Goodhart 分层不破）。step=None/未声明 -> 仅通用段。
    三通道同文维持：注入（workflow_phase）+ pass 续轮 + block 返工（workflow_advance）
    都调本函数，单源在此。
    """
    if step is None or not step.selfcheck:
        return STEP_SELFCHECK_HINT
    return STEP_SELFCHECK_HINT + "\n本步自查：" + step.selfcheck


def engagement_fence_notice(step: Step) -> str:
    """S15 零 trace 窗口的围栏提示文本（含 Step.fence_allow 豁免行）。

    §autocontinue-fence-notice：单源——workflow_phase.py 注入
    （UserPromptSubmit）与 workflow_advance.py pass/block 续轮
    （Stop additionalContext）共用，防双通道文案漂移
    （demo 121320fe：模型只在子1 见过无豁免版提示，到子4 臆断 Agent
    被 deny，未试先放弃并在 evidence 编造「Agent blocked by S15 fence」）。
    纯格式化函数：入参 Step，不查 state。
    """
    extra = (
        f"；当前子步骤额外放行：{' / '.join(step.fence_allow)}"
        if step.fence_allow
        else ""
    )
    return (
        "🚧 前置参与围栏（S15，PreToolUse 硬约束）：当前子步骤写 evidence 前，"
        "仅编排工具可用（AskUserQuestion / Skill / Task* / Read / Grep / Glob / "
        f"codegraph / dl-cmd / 写 evidence{extra}）；"
        "为用户任务探查（Bash/WebFetch/WebSearch/Agent 等）会被 deny 指回本步——"
        "「先回答用户问题再走编排」不存在，当前子步骤就是你要做的事。"
    )


def _strip_json_fence(text: str) -> str:
    """剥 ```json ... ``` 代码块围栏（冒烟实测 judge 倾向包代码块）。"""
    s = text.strip()
    if s.startswith("```"):
        # 去首行围栏（```json 或 ```）
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1 :]
        # 去尾围栏
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


def _extract_judge_result(result_text: str) -> dict[str, Any] | None:
    """从 claude -p 的 result 文本提取 {pass, reason}。

    judge 被要求只回 JSON。容错：剥代码块围栏 -> 取首个 {...} -> json.loads。
    失败返回 None（调用方降级为 block）。
    """
    s = _strip_json_fence(result_text)
    # 取首个 { 到末个 }（防模型前后带解释文本）
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = json.loads(s[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or "pass" not in obj:
        return None
    obj.setdefault("reason", "")
    return obj


# run_judge 最近一次调用的成本元数据（judge_* tokens/ms/cost；失败路径带 judge_error），
# 供 hook 写 .wf_advance.log 审计行（2026-07-26：judge 成本原完全黑盒，无法对账）。
# 只读方 = hook 进程（一次性子进程，无并发）；run_judge 每次调用开头 clear，
# 签名保持 (pass, reason) 不变——mock run_judge 的测试全部不受影响。
LAST_JUDGE_META: dict[str, Any] = {}


def _capture_judge_meta(last_json: dict[str, Any]) -> None:
    """从 claude -p --output-format json 的末行 JSON 采成本字段进 LAST_JUDGE_META。

    防御式取值：provider 包装器（ac-ark 等）可能缺字段，缺什么就不记什么。
    数值字段**累加**（非覆盖）：bad_verdict_json 重试时两次尝试的成本都要入账。
    """
    u = last_json.get("usage") or {}
    for k in (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ):
        if isinstance(u.get(k), int):
            key = f"judge_{k}"
            LAST_JUDGE_META[key] = LAST_JUDGE_META.get(key, 0) + u[k]
    for src, dst in (
        ("duration_ms", "judge_ms"),
        ("duration_api_ms", "judge_api_ms"),
        ("total_cost_usd", "judge_cost_usd"),
    ):
        if last_json.get(src) is not None:
            LAST_JUDGE_META[dst] = LAST_JUDGE_META.get(dst, 0) + last_json[src]


def run_judge(
    rubric: str,
    node_label: str,
    model_output: str,
    artifact_content: str | None = None,
) -> tuple[bool, str]:
    """起 stateless claude -p 当评审 judge。返回 (pass, reason)。

    design §5.1：独立会话,不续主 session（防污染主上下文）。
    输入 = rubric（判据）+ 模型本轮输出 + 声明产物内容。
    输出 = {pass:bool, reason:str}（JSON 强约束）。
    judge 继承主会话 env（design §9 #2）：不另设 provider/model,跑在主会话已起的 provider 上。

    失败（API 错/超时/解析失败）-> (False, 失败原因)（design §5.1 降级：不默认放行）。
    例外一：**bad_verdict_json（判定 JSON 解析失败）重试一次**（2026-07-26 决议）——
    parse 失败多属 judge 输出格式抖动，直接降级会把 judge 本意的 pass 白烧一轮
    返工（demo 121320fe 子1 首次即 bad_verdict_json）；重试仍失败才降级 block。
    例外二：**TimeoutExpired 重试一次**（2026-07-26 决议）——当初「超时不重试」的
    理由是递归爆炸（症状 N），其根因（judge 继承 worktree cwd 触发 hooks）已被
    cwd=tempdir 修掉；而超时降级 block 会让模型误以为内容不合格、把无问题的
    trace 白重写一轮（demo fbdb6ebd 子2 实测），一次重试 ~3k tokens 远小于
    一轮模型返工。API 错/退出码非零/OSError 仍**不重试**（重试无意义的失败模式）。
    副作用：每次调用重置 LAST_JUDGE_META（成功=成本字段，失败=judge_error；
    重试时两次尝试成本累加 + judge_retried=1）供审计日志。
    """
    LAST_JUDGE_META.clear()
    prompt = (
        "你是工作流节点门控的评审 judge。判定模型本轮输出是否符合判据。\n"
        "严格判定：判据任一条不满足 -> pass=false 并在 reason 写缺什么。\n"
        "只回答一个 JSON,不要多余文本、不要调任何工具：\n"
        '{"pass": true/false, "reason": "不满足时写缺什么;满足时留空"}\n\n'
        f"【节点】{node_label}\n"
        f"【判据】{rubric}\n"
        f"【模型本轮输出】\n{model_output}\n"
    )
    if artifact_content:
        prompt += f"\n【声明产物内容】\n{artifact_content}\n"
        # 返工是 append 协议（§substep-gate-at-stop S5）：同一 sub_step 会积累多条
        # skill-trace。不指认最新行，judge 可能拿返工前的旧行判 block（误报）。
        prompt += (
            "\n（产物内容中同一 sub_step 若有多条 skill-trace 记录，"
            "以最后一条为准；此前同号记录是返工历史，仅作参考。）"
        )
    prompt += "\n只回上面的 JSON。"

    for attempt in range(2):
        # 重试时：bad_verdict_json 加格式提醒后缀（判决载荷逐字不动，只追加输出
        # 格式强调）；TimeoutExpired 原样重发（输出格式没问题，是时延抖动）。
        p = prompt + (
            "\n\n提醒：上次你的回答不是合法 JSON。只回一个 JSON 对象，不要任何其它文本。"
            if attempt and LAST_JUDGE_META.get("judge_error") == "bad_verdict_json"
            else ""
        )
        ok, reason, retryable = _run_judge_once(p)
        if not retryable:
            return ok, reason
        LAST_JUDGE_META["judge_retried"] = 1
    return ok, reason  # 重试仍失败 -> 降级 block


def _run_judge_once(prompt: str) -> tuple[bool, str, bool]:
    """run_judge 单次尝试。返回 (pass, reason, retryable)。

    retryable=True 仅两种值得重试的失败模式：
    - bad_verdict_json（判定 JSON 解析失败——输出格式抖动）；
    - TimeoutExpired（时延抖动——递归爆炸根因已被 cwd=tempdir 修掉，
      重试代价远小于超时误判 block 引发的模型返工，见 run_judge docstring）。
    其余失败（API 错/exit 非零/no_result_json/is_error/OSError）
    一律 False，调用方直接降级。
    """
    try:
        res = subprocess.run(
            # --tools ""：judge 明确不调工具，裁掉全套工具 schema（harness 开销大头）。
            # --system-prompt：judge 人设替换 coding 助手人设，减人设冲突干扰。
            # 两者都是命令行 flag：settings.json 加载链不动,认证（env 继承或
            # settings env 块）在任何机器上照常。
            [
                "claude",
                "-p",
                "--output-format",
                "json",
                "--tools",
                "",
                "--system-prompt",
                JUDGE_SYSTEM_PROMPT,
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=JUDGE_TIMEOUT,
            # judge 会话必须落在非 git 目录：继承 worktree cwd 时，judge 会话自身的
            # UserPromptSubmit/Stop 会触发 workflow hooks（用户级注册）-> 递归门控
            # （judge 的 Stop 又生 judge，2026-07-25 demo 实测链式爆炸 + 全员超时）。
            # 非 git 目录下 hooks 反查不到项目根，自然静默退出。
            cwd=tempfile.gettempdir(),
        )
    except subprocess.TimeoutExpired as e:
        LAST_JUDGE_META["judge_error"] = type(e).__name__
        return False, f"judge 调用失败（{type(e).__name__}）", True  # 重试一次
    except OSError as e:
        LAST_JUDGE_META["judge_error"] = type(e).__name__
        return False, f"judge 调用失败（{type(e).__name__}）", False
    if res.returncode != 0:
        LAST_JUDGE_META["judge_error"] = f"exit={res.returncode}"
        return False, f"judge claude -p 退出码 {res.returncode}", False

    # claude -p --output-format json：stdout 末尾一行是 {"is_error":...,"result":"..."}
    # （冒烟实测：ac-ark 包装器在前面混入调试日志,但 result JSON 在最后一行）。
    last_json = None
    for line in reversed(res.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and '"result"' in line:
            try:
                last_json = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if last_json is None:
        LAST_JUDGE_META["judge_error"] = "no_result_json"
        return False, "judge 输出无 result JSON 行", False
    # last_json 存在起：先采成本（is_error/判定解析失败的路径也有 usage 可对账）
    _capture_judge_meta(last_json)
    if last_json.get("is_error"):
        LAST_JUDGE_META["judge_error"] = "is_error"
        return False, f"judge 会话出错：{last_json.get('result', '')[:200]}", False

    result_text = last_json.get("result", "")
    verdict = _extract_judge_result(result_text)
    if verdict is None:
        LAST_JUDGE_META["judge_error"] = "bad_verdict_json"
        return False, f"judge 返回非合法 JSON 判定：{result_text[:200]}", True
    # 重试后成功：清掉首次失败留下的 judge_error（避免审计日志误判本次为失败）
    LAST_JUDGE_META.pop("judge_error", None)
    return bool(verdict["pass"]), str(verdict.get("reason", "")), False


def run_gate(
    node: Node,
    model_output: str,
    project_root: Path | None = None,
    artifact_content: str | None = None,
) -> tuple[bool, str]:
    """compound gate（机械 + 语义,短路）。返回 (pass, block_reason)。

    design §5：机械不过短路 block（不跑 judge）;机械过跑 judge。
    无 gate_rubric 的节点（如 understand 子阶段 1-3）只过机械项。
    机械项目前未实现文件查找（§8.3）,多数降级放行 -> 靠 judge 兜底。
    """
    # 1. 机械项（短路）
    mech_block = gate_verdict_mech(node, project_root)
    if mech_block is not None:
        return False, mech_block
    # 2. 语义项（judge）。无 rubric -> 直接过（子阶段间自动推进）。
    if not node.gate_rubric:
        return True, ""
    ok, reason = run_judge(node.gate_rubric, node.label, model_output, artifact_content)
    if not ok:
        return False, reason or "judge 未给出原因"
    return True, ""


# ---------- phase-rules 渲染（P1 双通道单源，designs/harness-prompt-optimization-design.md）----------
#
# phase-rules.md 是模板：子步骤 bullet 段用 BEGIN/END GENERATED 标记占位，
# dl-launch.sh 每次启动调 `render-phase-rules` 渲染到 per-wf 目录（渲染失败中止启动，
# fail loud）。purpose 唯一真源 = engine Step.purpose——消灭 engine/phase-rules
# 两份手维护异文（症状 M/F 的「两通道措辞漂移」病根）。


_GENERATED_RE = re.compile(
    r"<!-- BEGIN GENERATED sub_steps (\S+?) -->.*?<!-- END GENERATED sub_steps \1 -->",
    re.DOTALL,
)


def render_substeps_section(nid: str) -> str:
    """渲染节点 sub_steps 的 phase-rules 段落（含 BEGIN/END 标记行，幂等可重渲染）。

    每步一行：`- **子步骤N = <ref>**：<purpose 全文>`（gate=None 标「自动过」）。
    节点无 sub_steps / 节点不存在 -> 报错暴露（no silent fallback）。
    """
    phase, sep, sub_s = nid.partition(":")
    if not sep or not sub_s.isdigit():
        raise ValueError(
            f"GENERATED 标记的节点 id 非法：{nid!r}（应形如 understand:1）"
        )
    node = get_node(phase, int(sub_s))
    if not node.sub_steps:
        raise ValueError(f"节点 {nid} 无 sub_steps，无可渲染段落")
    lines = [f"<!-- BEGIN GENERATED sub_steps {nid} -->"]
    for i, stp in enumerate(node.sub_steps, 1):
        gate_tag = "" if stp.gate else "（自动过）"
        lines.append(f"     - **子步骤{i} = {stp.ref}**{gate_tag}：{stp.purpose}")
    lines.append(f"<!-- END GENERATED sub_steps {nid} -->")
    return "\n".join(lines)


def render_phase_rules(template_text: str) -> str:
    """把模板里所有 GENERATED sub_steps 标记段替换为 engine 渲染产物。

    无标记段 -> 原样返回（向后兼容）；标记的节点 id 非法 -> 抛错（调用方 fail loud）。
    """
    return _GENERATED_RE.sub(
        lambda m: render_substeps_section(m.group(1)), template_text
    )


# ---------- 机械化记录写入（「AI 定写什么，脚本定怎么写」，2026-07-26）----------
#
# 原则：内容的正确值无法从 state 推导（问了什么/答了什么）-> 归 AI；
# 结构字段/格式/路径的正确值都能从 state+engine 推导 -> 归脚本。
# append-trace 根治手写 JSONL 的 5 类事故（症状 P/L：相对路径/覆盖写/合并行/
# 写碎/结构字段抄错）；redteam-prompt 根治现场拼红队 prompt 的 4 类事故
# （嵌套 spawn/无清单盲查/乱试工具/角色错乱）。

# 载荷里禁止出现的结构字段（由 append_trace 从 state 推导填充）。
_TRACE_STRUCT_FIELDS = ("kind", "major_stage", "minor_stage", "sub_step", "skill")


def append_trace(project_root: Path, name: str, payload_file: str) -> tuple[bool, str]:
    """载荷（purpose/q/a）+ state 结构字段 -> 校验 -> 单行 skill-trace append。

    返回 (ok, 消息)。校验失败 (False, 原因)——fail loud：模型当轮按报错修载荷
    重跑，而不是写坏了到 gate 才暴露（甚至像 d59d05ea 那样静默卡死）。
    成功后删载荷文件（防重复落库；失败保留供模型原地修）。
    """
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    state = normalize_state(state)
    try:
        node = get_node(state["phase"], state["sub_index"])
    except KeyError:
        return False, f"节点 {state['phase']}:{state['sub_index']} 不存在"
    if not node.sub_steps:
        return (
            False,
            f"节点 {node_id(node.phase, node.sub)} 无子步骤编排，append-trace 不适用",
        )
    if not node.minor_key:
        return (
            False,
            f"节点 {node_id(node.phase, node.sub)} 无 minor_key，无法填结构字段",
        )
    cur = state.get("sub_step_index", 1)
    step = sub_step_at(node, cur)
    if step is None:
        return False, f"子步骤 {cur} 不存在"

    pf = Path(payload_file)
    try:
        raw = pf.read_text(encoding="utf-8")
    except OSError as e:
        return False, f"读载荷失败：{e}（先用 Write 写载荷文件再调 append-trace）"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        return False, f"载荷不是合法 JSON：{e}（载荷只需普通 JSON，Write 原样写即可）"
    if not isinstance(payload, dict):
        return False, '载荷须是 JSON 对象：{"purpose":..., "q":[...], "a":[...]}'
    leaked = [k for k in _TRACE_STRUCT_FIELDS if k in payload]
    if leaked:
        return False, (
            f"载荷含结构字段 {leaked}——这些由脚本从 state 自动填，载荷里不要写"
            "（只留 purpose/q/a 三个内容字段）"
        )
    purpose = payload.get("purpose")
    q, a = payload.get("q"), payload.get("a")
    if not isinstance(purpose, str) or not purpose.strip():
        return False, "purpose 须为非空字符串"
    for field, val in (("q", q), ("a", a)):
        if (
            not isinstance(val, list)
            or not val
            or not all(isinstance(x, str) and x.strip() for x in val)
        ):
            return False, f"{field} 须为非空字符串数组（单问单答也用数组包一层）"
    if len(q) != len(a):
        return False, f"q/a 长度不齐（q={len(q)} a={len(a)}）：一问一答按序对齐"

    record = {
        "kind": "skill-trace",
        "major_stage": state["phase"].capitalize(),
        "minor_stage": node.minor_key,
        "sub_step": cur,
        "skill": step.ref,
        "purpose": purpose,
        "q": q,
        "a": a,
    }
    path = _evidence_path(project_root, name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        return False, f"写 evidence 失败：{e}"
    try:
        pf.unlink()  # 已落库，删载荷防重复 append
    except OSError:
        pass
    return (
        True,
        f"✓ 已落库 sub_step={cur} -> {path}（可输出 ### STEP_DONE: {cur} 并 end_turn）",
    )


def redteam_prompt(project_root: Path, name: str) -> str | None:
    """组装子4 红队子代理 prompt（证据+纪律归脚本，Agent 调用归模型）。

    证据取 read_evidence_for_step(≤3)：含子1-3 最新 trace、**不含子4 结论**
    （只给证据不给结论）。无子3 trace -> None（调用方 exit 1 暴露：
    红队无证据可审，先回补子3）。
    minor_stage 限定 ProblemContext（本函数是 understand:1 子4 专属；
    不限定会读到 GoalsAndValue 的同号子步骤 trace——跨节点串号）。
    """
    pc_minor = _NODES["understand:1"].minor_key
    if not sub_step_has_trace(project_root, name, 3, pc_minor):
        return None
    evidence = read_evidence_for_step(project_root, name, 3, pc_minor)
    if evidence is None:
        return None
    return (
        "你是独立红队评审。一个工作流正在对若干原子问题做取证后裁决，"
        "你是独立第二视角——任务是对证据做点查并尝试找出推翻空间，"
        "不是附和既有方向。\n\n"
        "【证据（双向取证留痕，含 URL / file:line 指针）】\n"
        f"{evidence}\n\n"
        "【纪律】\n"
        "1. 点查以 Read 工具为主：证据里引用的文件路径用 Read 复查；"
        "你的会话里 Glob/Grep/codegraph 可能不存在、Bash 会被围栏拒绝，都不要试。\n"
        "2. 单层：禁止再 spawn 子代理。\n"
        "3. 不做系统性重新取证：只点查验证；证据不足时下「证据不足」verdict 并指明缺哪条。\n"
        "4. 对每个原子问题给四态 verdict（证实/证伪/部分成立/证据不足）"
        "+ 推理链（引用证据指针）+ 置信度。\n\n"
        "【输出】逐原子问题：verdict / 推理链 / 置信度。"
    )


# ---------- CLI（design §8.1;供 dl-cmd.sh / 手动覆盖调用）----------


def _cmd_status(project_root: Path, name: str) -> int:
    state = load_state(project_root, name)
    if state is None:
        print(f"✗ 工作流 {name} 的 state.json 缺失", file=sys.stderr)
        return 1
    state = normalize_state(state)
    phase = state["phase"]
    node = get_node(phase, state["sub_index"])
    st = state["sub_total"]
    sub_line = ""
    if st > 0:
        sub_line = f" | 子阶段: {node.label} [{state['sub_index']}/{st}]"
    print(f"═══ 工作流: {name} ═══")
    print(
        f"  阶段:  {PHASE_LABELS.get(phase, phase)} [{state['index']}/{len(PHASES)}]{sub_line}"
    )
    print(f"  节点:  {state['node']}")
    print(f"  闸门:  {state['gate']}")
    print(f"  技能:  {node.skill or '(靠行为约束)'}")
    print(f"  重试:  {state['node_attempts']}")
    print(f"  分支:  {state.get('branch', '?')}")
    return 0


def _cmd_current(project_root: Path, name: str) -> int:
    state = load_state(project_root, name)
    if state is None:
        print(f"✗ 工作流 {name} 的 state.json 缺失", file=sys.stderr)
        return 1
    state = normalize_state(state)
    node = get_node(state["phase"], state["sub_index"])
    out = {
        "node": state["node"],
        "label": node.label,
        "phase": node.phase,
        "sub": node.sub,
        "skill": node.skill,
        "artifact": node.artifact,
        "gate_mech": node.gate_mech.value,
        "gate_rubric": node.gate_rubric,
        "advance": node.advance,
        "sub_step_index": state.get("sub_step_index", 0),  # §orchestration v2
        "sub_steps": (
            [
                {
                    "n": i,
                    "kind": s.kind,
                    "ref": s.ref,
                    "short": s.short,
                    "purpose": s.purpose,
                    "input": s.input,
                    "record": s.record,
                    "gate": s.gate,
                }
                for i, s in enumerate(node.sub_steps, 1)
            ]
            if node.sub_steps
            else None
        ),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _cmd_progress(project_root: Path, name: str) -> int:
    """输出当前阶段真值（供 dl-cmd.sh status 贴给模型取数据，非展示）。

    §orchestration v2：进度树**展示**已弃用（phase-rules 行 14：只靠 TUI TaskList）。
    但模型需 status 取「现在在第几步」真值（state.json 权威源，TaskList 模型自维可能不准）。
    故本命令只输出当前阶段/子阶段/子步骤序号 + 当前子步骤 purpose 一行数据，
    不输出全 5 阶段树（树是展示，归 TaskList）。
    """
    state = load_state(project_root, name)
    if state is None:
        print(f"✗ 工作流 {name} 的 state.json 缺失", file=sys.stderr)
        return 1
    state = normalize_state(state)
    cur_phase = state["phase"]
    cur_idx = phase_index(cur_phase)
    cur_sub = state["sub_index"]
    cur_sub_total = sub_total(cur_phase)
    cur_step = state.get("sub_step_index", 0)

    line = f"当前: {PHASE_LABELS.get(cur_phase, cur_phase)} [{cur_idx}/{len(PHASES)}]"
    if cur_sub_total > 0:
        slabel = (
            subphase_labels(cur_phase)[cur_sub - 1]
            if 1 <= cur_sub <= cur_sub_total
            else "?"
        )
        line += f" | 子阶段: {slabel} [{cur_sub}/{cur_sub_total}]"
        node = get_node(cur_phase, cur_sub)
        if node.sub_steps and 1 <= cur_step <= len(node.sub_steps):
            stp = node.sub_steps[cur_step - 1]
            gate_tag = "" if stp.gate else "（自动过）"
            line += (
                f" | 子步骤: {cur_step}/{len(node.sub_steps)} "
                f"[{stp.kind}:{stp.ref}] {stp.purpose}{gate_tag}"
            )
    print(line)
    return 0


def _cmd_advance(project_root: Path, name: str) -> int:
    state = advance_state(project_root, name)
    node = get_node(state["phase"], state["sub_index"])
    print(f"▸ 推进到节点 {state['node']}")
    print(f"  {PHASE_LABELS.get(state['phase'], state['phase'])} · {node.label}")
    return 0


def _cmd_meta() -> int:
    """输出全部静态常量 JSON（供 dl-lib.sh 启动时缓存,删 bash 侧副本）。

    bash 侧不再各持 PHASES/GATED_AFTER/SUBPHASES 副本,source 本输出一次缓存。
    """
    out = {
        "phases": list(PHASES),
        "phase_labels": PHASE_LABELS,
        "gated_after": list(GATED_AFTER),
        "subphases": {p: subphase_labels(p) for p in PHASES},
        "sub_total": {p: sub_total(p) for p in PHASES},
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dl-flow-engine",
        description="工作流编排内核（被 hook 咨询;不当主进程）",
    )
    parser.add_argument(
        "cmd",
        choices=[
            "status",
            "current",
            "advance",
            "progress",
            "meta",
            "step-pass",
            "step-reset",
            "subgate-pass",
            "fence",
            "render-phase-rules",
            "append-trace",
            "redteam-prompt",
        ],
    )
    parser.add_argument(
        "name",
        nargs="?",
        help="工作流名（不填则从 cwd 反查）；render-phase-rules 时为 phase-rules 模板路径",
    )
    parser.add_argument(
        "value", nargs="?", help="fence 的值（on|off）/ step-reset 的子步骤号"
    )
    parser.add_argument("--cwd", help="覆盖 cwd（默认进程 cwd）")
    parser.add_argument(
        "--from-file", help="append-trace 的载荷文件路径（Write 写的 purpose/q/a JSON）"
    )
    args = parser.parse_args(argv)

    # meta 是静态常量,不需要 git repo / name。
    if args.cmd == "meta":
        return _cmd_meta()

    # render-phase-rules（P1）：渲染 phase-rules 模板的 GENERATED 段到 stdout。
    # 不需要 git repo / 工作流名（dl-launch.sh 启动时调用，渲染失败非零退出 = 中止启动）。
    if args.cmd == "render-phase-rules":
        if not args.name:
            print("✗ 用法: render-phase-rules <phase-rules 模板路径>", file=sys.stderr)
            return 1
        try:
            template_text = Path(args.name).read_text(encoding="utf-8")
        except OSError as e:
            print(f"✗ 读模板失败：{e}", file=sys.stderr)
            return 1
        try:
            sys.stdout.write(render_phase_rules(template_text))
        except (KeyError, ValueError) as e:
            print(f"✗ 渲染失败：{e}", file=sys.stderr)
            return 1
        return 0

    cwd = args.cwd or str(Path.cwd())
    project_root = resolve_project_root(cwd)
    if project_root is None:
        print("✗ 不在 git 仓库内", file=sys.stderr)
        return 1
    name = args.name or resolve_workflow_name(cwd)
    if not name:
        print(
            "✗ 不在工作流 worktree 内（cwd 不含 .claude/worktrees/<name>）,且未给 name",
            file=sys.stderr,
        )
        return 1

    if args.cmd == "append-trace":
        if not args.from_file:
            print("✗ 用法: append-trace [name] --from-file <载荷路径>", file=sys.stderr)
            return 1
        ok, msg = append_trace(project_root, name, args.from_file)
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if args.cmd == "redteam-prompt":
        prompt = redteam_prompt(project_root, name)
        if prompt is None:
            print(
                "✗ 无子3 双向取证 trace——红队无证据可审，先回补子3",
                file=sys.stderr,
            )
            return 1
        sys.stdout.write(prompt + "\n")
        return 0
    if args.cmd == "status":
        return _cmd_status(project_root, name)
    if args.cmd == "current":
        return _cmd_current(project_root, name)
    if args.cmd == "advance":
        return _cmd_advance(project_root, name)
    if args.cmd == "progress":
        return _cmd_progress(project_root, name)
    if args.cmd == "step-pass":
        ok, msg = force_pass_sub_step(project_root, name, cwd)
        print(("✓ " if ok else "✗ ") + msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if args.cmd == "subgate-pass":
        ok, msg = release_subgate(project_root, name, cwd)
        print(("✓ " if ok else "✗ ") + msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if args.cmd == "step-reset":
        try:
            n = int(args.value or "")
        except ValueError:
            print(
                "✗ 用法: step-reset <name> <n>（n=回退到的子步骤号）", file=sys.stderr
            )
            return 1
        ok, msg = reset_sub_step(project_root, name, n)
        print(("✓ " if ok else "✗ ") + msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if args.cmd == "fence":
        if args.value not in ("on", "off"):
            print("✗ 用法: fence <name> on|off", file=sys.stderr)
            return 1
        state = load_state(project_root, name)
        if state is None:
            print(f"✗ 工作流 {name} 的 state.json 缺失", file=sys.stderr)
            return 1
        state = normalize_state(state)
        state["enforce_step_fence"] = args.value == "on"
        save_state(project_root, name, state)
        print(
            f"✓ 子步骤围栏（S10）已{'开启' if args.value == 'on' else '关闭（回文案约束）'}"
            "（阶段写围栏 S11 是系统硬约束，不受此开关影响）"
        )
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
