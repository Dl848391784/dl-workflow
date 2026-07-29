# 子5/子6 第一性原理重设计：归一化陈述 + 带证据读回确认

> 状态：**已实施**（2026-07-26；engine/phase-rules/SKILL/tests 已同步）
> 父文档：`step3-verify-redesign-design.md`（子3/子4 重设计）、`node-step-orchestration-design.md`（子步骤编排机制）、`workflow-creation` SKILL.md §3.5（rubric 方法论）
> 外部取证：本文 §3（Tavily 检索，2026-07-26）

## 0. 动因：质检裁决之后存在「裁决不传导」缺口

`step3-verify-redesign-design.md` 把 understand:1 重设计为 6 步后，子4「质检裁决」产出四态 verdict（证实/证伪/部分成立/证据不足）+ 推理链 + 置信度。但子5「一句话陈述」的契约（purpose/gate）只查「≤1 句、主语+动词+约束、无并列复合」——**没有任何机制约束陈述集与 verdict 一致**：

- 子4 判「证伪」→ 子5 照陈述不误（verdict 白判）
- 子4 判「部分成立」→ 子5 按原始问题全称陈述，已收窄的边界丢失
- 子4 判「证据不足」→ 子5 陈述得像已证实；子6 读回也不向用户暴露不确定性

同时子6「读回确认」只说「用户认这就是问题（集）」，未要求向用户呈现 verdict 与证据指针——用户在没有证据路标的情况下「认可」，认可本身不可复查。

## 1. 第一性原理：ProblemContext 终态的三属性

「理解问题和背景」达成 = 一个**共享的、经过验证的、有边界的问题定义**。拆为三属性：

| 属性 | 含义 | 承担步骤 |
|---|---|---|
| 内容正确 | 问题真实存在、根因不是症状 | 子1-4（逼问/拆解/取证/裁决） |
| 形式可移植 | 脱离本次对话上下文也能被下游（understand:2、plan、后续 dl 实例）独立理解 | **子5（本设计重定义）** |
| 用户认可 | 真值与认可度归用户（§3.5 三层分工）；模型验证 ≠ 用户认账 | **子6（本设计重定义）** |

子4 只交付属性 1。属性 2、3 是后两步各自独立的存在理由——不能被质检裁决吸收，也不能互相合并。

**三段分工**：内容（子4 含处置）→ 形式（子5 归一化）→ 认可（子6 读回）。

## 2. 重设计（步骤数不变，仍 6 步；只改子4/5/6 的 purpose/gate）

### 子4 质检裁决：加「④按 verdict 处置问题集」

处置是裁决的天然产物——judge 在子4 手里拿着 verdict，顺手可判「verdict ↔ 问题集」一致性；放到子5 判，judge 需跨两步对齐证据，判据变复杂。

- **purpose 加 ④**：按 verdict 处置问题集——证伪项剔除（留剔除理由）/ 部分成立项收窄到已证实边界 / 证据不足项带标记进入读回；**处置后问题集 = 子5 唯一输入**。
- **gate 加**：处置后问题集与 verdict 逐项一致（证伪项已剔除+理由、部分成立项已收窄、证据不足项已标记）。

### 子5 一句话陈述 → 归一化陈述（claim normalization）

职能重定位：不是「压缩话术」，是**归一化**——产出原子、去上下文、携带 verdict 边界的问题陈述。外部依据见 §3：claim normalization 是 fact-checking pipeline 的独立阶段（AVeriTeC 标注 P1）；文档级 claim 抽取文献定义可消费 claim 三属性 = atomic / decontextualized / check-worthy；RCA 方法论区分 problem statement（取证前，= 子1）与 root cause statement（证据检验后，= 子5），双陈述结构有外部依据。

- **purpose**：对子4 处置后问题集逐项产出归一化问题陈述——①原子（单句 ≤1 个独立痛点，「和/以及/同时」连接多痛点 = 复合未拆净，回子2 重拆）；②去上下文（脱离本会话可独立理解：主语+动词+约束自包含）；③携带 verdict 边界与置信度（部分成立项陈述只覆盖已证实边界）；放不进一句 = 未定义完。
- **gate**：形式要件保留原子性/单句检查；**质量判据加「陈述集与子4 verdict 逐项一致」**——证伪项不得出现在陈述集、部分成立项陈述不得超出已证实边界（裁决不传导判 block）。

### 子6 读回确认 → 带证据的读回确认

仍放最后、gate=None 不变（交互步，trace 存在即过）。升级呈现内容：外部依据（§3）——只给结论不给依据地「通知」用户会导致不信任甚至 backfire effect；一线 fact-checker 的三大解释需求 = 解释不确定性、路标式证据指针、过程可解释。

- **purpose**：向用户呈现 **归一化陈述 + 四态 verdict + 证据指针 + 置信度**（「证据不足」项显式暴露，由用户裁决继续/等恢复/放弃）；用户认「这就是问题（集）」；多问题时用户选定本实例处理项，其余带已验证陈述落 evidence + understand.md（供后续 dl 实例接续，不丢弃）；用户对各项的认/否/搁置记入 trace（用户认可本身是裁决留痕）。
- **record=True 不变**：确认内容是 Stop 门控的完成触发信号 + 裁决留痕。

## 3. 外部实证出处（2026-07-26 Tavily 取证留痕）

- **AVeriTeC 标注管线**（arXiv:2410.23850；FEVER 2024/2025）：P1 = claim normalization（把 claim 改写至 context-independent），后续阶段才能脱离原文消费；verdict 阶段必须附 **justification**。
- **文档级 claim 抽取**（Deng et al. 2024；arXiv:2406.03239；DNDSCORE EMNLP 2025）：可消费 claim 三属性 = **atomic / decontextualized / check-worthy**——对应子5 的「无并列复合 / 主语+动词+约束自包含 / verdict 传导」。
- **ClaimNorm**（Findings of EMNLP 2023，aclanthology 2023.findings-emnlp.439）：claim normalization 是独立任务（需 check-worthiness 估计），不是摘要/呈现的副产品——支持「子5 不并入子6」。
- **RCA 方法论**（Sologic）：problem statement 在取证**之前**写；**root cause statement 在「证据收集完、因果逻辑被检验之后」才写**——子1 = 前者，子5 = 后者，双陈述非冗余。
- **Das et al. 2023 综述**（Information Processing & Management）：只给 verdict 不给 justification 会导致系统被无视/不信任，甚至 **backfire effect**；HITL 是落地刚需。
- **《Show Me the Work》**（CHI 2025，arXiv:2502.09083）：一线 fact-checker 三大解释需求 = **解释不确定性 / 路标式证据指针（signposting）/ 过程可解释**——子6 呈现内容的直接依据。

## 4. 否决的替代方案（对抗性审视留痕）

1. **子5 并入子4（处置输出直接就是陈述）**——否。子4 失效族 = 判断质量（证据/verdict 逻辑）；归一化失效族 = 形式可移植性。**异族拆开**（`step3-verify-redesign-design.md` §1 拆步粒度原则）；形式检查混进子4 gate 会稀释 judge 对证据质量的判力。
2. **删子5，用户直接在子6 读 verdict**——否。子6 是交互步（gate=None 不跑 judge）；归一化是结构可判的（原子性/单句/自包含 judge 可判），并入子6 = 放弃门控。ClaimNorm 文献：归一化是独立任务，不是呈现动作的副产品。
3. **子4 质检发现证据弱 → 回子3 补取证的回路**——维持 `step3-verify-redesign-design.md` §3 的拒绝：「证据不足」是合法 verdict，归用户子6 裁决；引入回路会破坏线性 sub_step 门控机械层。

## 5. 实施 checklist（改编排必过，症状 M；本次只改文案不动步骤数/机械层，风险低于子3/子4 拆步）

1. `dl_flow_engine.py`：子4 purpose+gate 加④处置；子5 purpose/gate 重写；子6 purpose 重写（gate=None、record=True 不动）
2. `hooks/workflow_phase.py` `_format_injection`：**无需改**——子步骤清单动态读 `Step.purpose`，engine 文案自动流入注入通道（本次无结构变更）
3. `scripts/workflow/phase-rules.md`：子步骤4 行加④处置；**补子步骤5/6 行**（上次拆步漏补，system-prompt 通道只有子1-4 描述）
4. `skills/workflow-creation/SKILL.md`：§0 子步骤清单更新子5/6 描述 + v2.8 标注；修「record 子步骤（子1/2/3）」残留（现 6 步全 record=True）
5. `tests/test_dl_flow_engine.py`：子4 gate 含「处置」/ 子5 gate 含 verdict 传导判据 / 子6 gate=None 的断言
6. 本设计文档状态行改「已实施」
