# understand:4「定义成功标准与验收方式」子步骤编排设计（SuccessCriteria）

> 状态：**已确认**（2026-07-27 用户两决议：5 步 / **加 hold_for_gate**）
> **修订（2026-07-27，用户决议）**：本工作流定位 = **编程专用工作流**（非通用工作流）。骨架不动（5 步/门控/四成分划分领域无关），修订三处领域参数：①子1 双结论制口径收紧——编程域代码行为几乎总是可执行验证，「只能定性验收」从合法结论降为**须更强理由的稀有结论**（合法剩余 ≈ UX/可读性/架构审美）；②子2 可检验化的规范形式 = **可执行验收**（failing test/脚本断言/命令+退出码，specification by example，接 TDD）；③子3 INCOSE 四法给编程映射表。失效模式表补两条编程实例。
> 父文档：`node-step-orchestration-design.md`（子步骤编排机制）、`understand-subphases-design.md`（4 子阶段划分 + sub4->成功标准+验收+汇总 understand.md 接口约定）、`goals-and-value-substeps-design.md`（GoalsAndValue 5 步范式）、`scope-and-constraints-substeps-design.md`（ScopeAndConstraints 5 步范式 + 本地单层源压缩原则）、`step3-verify-redesign-design.md` + `step5-step6-statement-readback-redesign-design.md`（ProblemContext 6 步范式）、`workflow-creation` SKILL.md §3.5（rubric 方法论）/ §3.8（拆步方法论）
> 外部取证：本文 §4（Tavily 检索，2026-07-27，设计期调研——用户明示允许；与运行期 understand:1 子3「禁 tavily/WebSearch」约束无关）

## 0. 背景

understand:4（SuccessCriteria）当前无 `sub_steps` 编排——模型自由发挥「定义成功标准与验收方式」，仅有子阶段级 rubric（「①重述真实问题 ②边界 ③可验证成功标准」）在 understand->plan 大闸门跑一次 judge，无逐步门控。ProblemContext 6 步、GoalsAndValue 5 步、ScopeAndConstraints 5 步编排已验证有效（v2.6-v2.16），本文为 understand:4 设计同机制子步骤——understand 阶段最后一个无编排节点的补齐。

输入 = ScopeAndConstraints 终态：归一化范围双侧清单 + 约束集（已验证附出处 / 假设+置信度+影响）+ 用户裁决（范围拍板 + 假设接受）；上游 GoalsAndValue 终态：归一化目标陈述集（must/nice 用户裁决）。
输出 = understand.md「成功标准 + 验收方式」节（understand-subphases-design §0：sub4->成功标准+验收，且 sub4 负责汇总写 understand.md），供 plan 设计与 **review:0 gate 判定**直接消费。

**消费契约锚点**（本节点独有的第一性原理锚点）：成功标准的下游消费方是 review 阶段的 gate——`dl_flow_nodes.py` review:0 rubric = 「对照 understand.md 真实问题 + 成功标准，判定 solved/partial/not，附 file:line 证据」。因此：可检验化不是形式洁癖，是 review 可判性的前置条件；验收方式 = review 判定时的取证路径。本子步骤设计倒推自这个消费契约（验收包必须携带 review 判定时需要的全部字段）。

## 1. 第一性原理

### 1.1 终态三属性（同构前三个节点）

| 属性 | 在本子阶段的含义 | 承担步骤 |
|---|---|---|
| 内容正确 | 标准真实承接目标（无孤儿/无漏）；每条可检验；验收方式存在且可行 | 子1-3 |
| 形式可移植 | 归一化成功标准陈述（原子/去上下文/携带完整验收包），review/plan 可直接消费 | 子4 |
| 用户认可 | 阈值 = 风险偏好、验收方式取舍（含「验收手段待建」是否接受为任务项）= 规范裁决，归用户 | 子5 |

### 1.2 关键不对称：混合命题，但轴心是「规范性目标的可检验化转换」

| 子阶段 | 命题性质 | 编排后果 |
|---|---|---|
| ProblemContext | 纯事实性 | 五层外部源取证 + 质检裁决双步 |
| GoalsAndValue | 纯规范性 | 无取证步 |
| ScopeAndConstraints | 混合：约束=事实性，范围=规范性，假设=中间态 | 约束本地单层源压缩验证一步 |
| **SuccessCriteria** | **混合，成分不同**：对齐=结构性，可检验化=技术转换，验收可行性=事实性（本地单层源），阈值/验收取舍=规范性 | 新增「可检验化」独立步（前三个节点都没有）；可行性验证沿用压缩原则 |

四类成分分开处理：

- **标准-目标对齐 = 结构性**：双向追溯（无孤儿标准/无漏目标），judge 可判（同构 GoalsAndValue 子2）。
- **可检验化 = 技术性转换**：Volere 核心判据——「找不到 fit criterion 的标准 = 模糊或理解不足」（If a fit criterion cannot be found for a requirement, then the requirement is either ambiguous or poorly understood）。这是本阶段的核心工作：**把规范性目标转成可检验命题**。不可检验化 = 合法退回信号（退回引出步或标记回退 GoalsAndValue），不是硬编假指标的理由。**编程域特化（2026-07-27 修订）**：代码行为几乎总是可执行验证的——fit criterion 的规范形式默认是**可执行验收**（failing test / 验证脚本断言 / 命令+退出码，即 specification by example，与 TDD 天然衔接：成功标准直接转成先写的失败测试）；「只能定性验收」因此从通用域的常见合法结论收紧为**须更强理由的稀有结论**——合法剩余基本只有 UX/可读性/架构审美这类不可执行验证项，「跑个测试就能验」的目标标定性 = 偷懒出口（judge 黑盒抓）。
- **验收方式可行性 = 事实性命题**：验收手段（测试框架/数据源/契约检查脚本）在本仓是否存在，**本地单层源**（Bash/codegraph/Read）可验——沿用 ScopeAndConstraints 子2 压缩原则，一步完成，无独立质检裁决步。
- **阈值/验收取舍 = 规范性命题**：「多高算够」是风险偏好，外部证据无权证伪「我满意的标准」；「验收手段待建」是否接受为本实例任务项 = 给 plan 埋任务，须用户知情拍板。真值源只有用户。

### 1.3 失效模式分析

| # | 失效模式 | 外部出处（§4） |
|---|---|---|
| S1 | 模糊不可检验标准（「系统变快」「体验好」）→ review 无法判定，验收流于叙事。**编程变体：「编译/运行无报错」冒充成功标准——无报错 ≠ 需求达成** | INCOSE 模糊词禁令（some/any/several/many/significant/adequate/efficient…）；Wiegers「unverifiable = wish」 |
| S2 | 标准-目标脱节：凭空标准（镀金）/ must 目标无标准承接（漏） | 双向可追溯（同构 GoalsAndValue 子2） |
| S3 | solutioneering 残留：标准写成「实现了 X 功能」而非 outcome 度量 | INCOSE implementation-free |
| S4 | 有方向无门槛（「IC 越高越好」）→ 达标线缺失；或模型自定阈值 = 越权裁决 | Volere：fit criterion 必须量化；四桶分工（认不认归用户） |
| S5 | 标准可检验但没说怎么验 → review 临时找证据，判定不可复现 | INCOSE A2：每条需求须声明主验证方法（test/analysis/inspection/demonstration 四法） |
| S6 | 验收方式纸面可行实际不可行（手段在本仓不存在/数据不可得）。**编程变体：验收测试只覆盖 happy path，边界/失败路径无验证** | INCOSE feasibility；fitness function「may not be implementable in software」（Neal Ford） |
| S7 | 验收时机错位：只能在事后（不可逆点后）验证的未标注；该 continuous 的只设 triggered | fitness functions triggered vs continuous（Neal Ford） |
| S8 | 复合/模糊陈述脱离上下文不可解 | INCOSE atomic/singular |

**步数推导**（§3.8 #4，按失效模式族）：引出族（S2+S3）-> 子1；可检验化族（S1+S4 前半）-> 子2；验收方式族（S5+S6+S7）-> 子3；形式族（S8）-> 子4；认可族（S4 后半+拍板）-> 子5。5 族 = 5 步，异族拆开、同族合并。步数不是照抄前节点模板对称出来的（6/5/5/5 各自独立推导）。

## 2. 设计：5 步

```
子1 成功标准引出 → 子2 可检验化 → 子3 验收方式设计与可行性验证 → 子4 归一化陈述 → 子5 读回确认
```

judge 调用 4 次（子5 gate=None）。

### 子1 成功标准引出（kind=tool）

- **ref**：`推理(验收视角提问) / AskUserQuestion(补问)`
- **purpose**：对每个 must 目标做验收视角提问「怎么知道它达成了」（INCOSE verification point-of-view：写标准时想象自己在执行验收事件，「How will I know if the requirement has been met?」）引出标准候选；双向追溯（每 must 目标 ≥1 标准候选或显式「纯定性目标+理由」；每候选回溯 ≥1 目标，孤儿候选剔除或退回补问）；solutioneering 剥离（标准含方案名词/实现动词 → 剥到 outcome 度量，纪律同 GoalsAndValue 子2）；用户侧期望（「什么结果你会满意」）缺口走 AskUserQuestion 补问（取证纪律同前：优先上下文已有原话，禁重问已答内容）。**双结论制（编程域收紧，2026-07-27 修订）**：①标准候选成立；②「目标只能定性验收」是**稀有**合法结论——编程域代码行为几乎总是可执行验证，②须逐目标留痕理由且理由须说明「为何不可执行验证」（合法剩余 ≈ UX/可读性/架构审美类）；「跑个测试/脚本就能验」的目标标定性 = 偷懒出口，judge 判 block。
- **input**：`GoalsAndValue.step4.statements`（must 目标集）+ `ScopeAndConstraints.step4.statements`（已验证约束过滤不可行的验收方向）
- **record**：True；**fence_allow**：无（AskUserQuestion 在常驻集）
- **gate**：trace 存在；形式要件（must 目标全覆盖验收视角提问；双向追溯逐项列出；q/a 对齐；补问原话出处）；质量判据黑盒（空泛标准无度量对象判 block；脑补标准挂无关目标判 block；②缺逐目标理由、或理由未说明「为何不可执行验证」= 偷懒判 block——编程域收紧，可执行验证的目标标定性判 block；方案名词残留判 block）。

### 子2 可检验化（kind=tool）

- **ref**：`推理(Volere fit criterion + INCOSE 模糊词清单) / Bash(条件性基线测量)`
- **purpose**：对子1 标准候选逐条做 fit criterion 转换——①模糊词扫描改写（INCOSE vague terms：some/any/several/many/a lot of/significant/adequate/efficient/effective/reasonable…，改写为量化表述）；②三要素齐备：**度量指标 + 基线**（Bash 实测现状——查数据/日志/耗时，附工具留痕出处；不可测显式标「无基线+原因」= 合法留痕）**+ 阈值提案**（只提案不拍板——阈值是风险偏好，裁决权留子5）；**编程域规范形式（2026-07-27 修订）：可执行验收优先——每条标准的 fit criterion 尽量落成 failing test / 验证脚本断言 / 命令+退出码**（specification by example；落成失败测试的标准直接与 TDD 衔接，review 判定可机械复现），落不成可执行形式的须说明原因；③**不可检验化 = 合法退回信号**（Volere：找不到 fit criterion → 标准模糊/目标理解不足 → 退回子1 重引或显式标记回退 GoalsAndValue；禁止硬编假指标——假指标 = 度量对象与目标 outcome 不相关，如拿「代码行数」度量「体验」、拿「编译无报错」度量「功能达成」）。
- **input**：`step1.criteria_candidates`
- **record**：True；**fence_allow**：`("Bash",)`（条件性基线测量）
- **gate**：trace 存在；形式要件（每条候选有指标+基线（或「无基线+原因」）+阈值提案；模糊词扫描留痕；退回项显式标注）；质量判据黑盒（基线数字无工具出处 = 拍脑袋编造判 block；假指标——度量对象与目标 outcome 不相关判 block；替用户拍板阈值——无「提案-待用户裁决」语义判 block；改写后仍含模糊词判 block）。

### 子3 验收方式设计与可行性验证（kind=tool）

- **ref**：`推理(INCOSE 四法) / Bash / codegraph / Read(手段存在性)`
- **purpose**：对每条可检验标准定验收方式——①方法选择（INCOSE 四法：test 测试 / analysis 数据分析 / inspection 审查 / demonstration 演示，附选择理由——类型×方法有经典映射：功能→demonstration、性能→test、设计约束→inspection、质量属性→analysis；**编程域映射（2026-07-27 修订）：test→pytest/验证脚本，analysis→数据/log 对比查询，inspection→review checklist 逐项核查，demonstration→跑起来看实际行为输出**）；②**可行性三态处置**（同构 ScopeAndConstraints 子2 压缩版，本地单层源）：手段存在（测试框架/数据源/契约检查脚本在本仓存在，Bash/codegraph/Read 验证附出处）/ **验收手段待建**（不存在 → 显式标注 = 进 plan 的任务项，不静默略过；编程域实例 = 测试框架/fixture/验证脚本缺失）/ 不可行剔除（附理由）；③**验收时机标注**（triggered = review 一次性判 vs continuous = 持续监控，fitness function 概念；**只能在事后验证的显式标注风险**——如 T+1 实战效果只能事后验，review 期只能用回测代理指标，代理与真值的关系显式说明）；④**证据形式锚定**（review 判 solved/partial/not 时拿什么：file:line/测试输出/数据查询——直接对接 review:0 rubric「附 file:line 证据」）。
- **input**：`step2.testable_criteria`
- **record**：True；**fence_allow**：`("Bash",)`（手段存在性验证；codegraph/Read 在常驻集）
- **gate**：trace 存在；形式要件（每条标准有四法之一+选择理由；可行性三态处置（存在附出处/待建标注/剔除附理由）；时机标注；证据形式）；质量判据黑盒（手段声称存在无工具出处 = 编造判 block；全选同一方法无真实选择理由判 block；事后验证未标注风险判 block）。

### 子4 归一化陈述（kind=skill）

- **ref**：`define-problem`（claim normalization 职能第四次复用——ProblemContext 子5 / GoalsAndValue 子4 / ScopeAndConstraints 子4 同构）
- **purpose**：对子3 标准集逐项产出归一化成功标准陈述——①原子（单句 ≤1 个独立标准，「和/以及/同时」连接多项 = 复合未拆净，回子1）；②去上下文（主语+动词+约束自包含）；③携带**完整验收包**（指标+基线+阈值提案+验收方法+时机+证据形式）与 verdict 边界（部分成立目标的标准只覆盖已证实边界——裁决传导）；④solution-free 复核（含方案名词 = 子1 剥离不净残留）。放不进一句 = 未定义完。
- **input**：`step3.criteria_with_acceptance`
- **record**：True；**fence_allow**：无
- **gate**：trace 存在；形式要件（每项 ≤1 句且含主语+动词+约束；携带完整验收包六字段与边界）；质量判据黑盒（验收包字段不传导——子3 已定的方法/时机/证据形式在陈述中丢失或篡改判 block；单句含多项并列 = 复合未拆净判 block；方案名词残留判 block）。

### 子5 读回确认（kind=skill）

- **ref**：`define-problem / AskUserQuestion`
- **purpose**：带证据的读回确认：向用户呈现 归一化标准+验收包+不可检验退回项+「验收手段待建」清单+不确定性；**用户裁决两件事**：①**阈值拍板**（风险偏好 = 规范裁决，本子阶段第一裁决点）；②**验收方式认可**（含「待建手段」是否接受为本实例任务项——等于给 plan 埋任务，须用户知情；第二裁决点）；不可检验退回项显式暴露由用户裁决（降低标准/回退目标定义/接受定性验收）；用户认/否/调整记入 trace。
- **input**：`step4.statements`
- **record**：True；**fence_allow**：无
- **gate**：None（交互步，trace 存在即过）

### 末子步骤过后：汇总 understand.md + hold_for_gate（**加**，2026-07-27 用户决议）

子5 过门控后**无条件扣留**（state.held_for_gate），唯一出口 `/dl gate`——与 understand:3 同款**隔离测试**语义：新编排阶段跑完被围栏围住，用户验证编排本身没问题再放行。放行后模型汇总 4 子阶段归一化陈述写 understand.md（真实问题重述+目标价值+范围约束+成功标准验收；`ARTIFACT_EXISTS` 机械门保留），再输出 `### PHASE_DONE: understand` 撞 understand->plan 大闸门（第二次 `/dl gate`——两次连拍是用户已接受的代价）。

**机制新路径**：hold_for_gate 此前仅用于 advance="sub" 节点（understand:2/3），本节点是首个 advance="phase" 的 hold 节点——末子步 pass -> 扣留 -> subgate-pass -> 推进 phase 的路径从未真正走过，**必须有 pinning 测试**（症状 M #7：新开通的推进路径是 latent bug 温床）。

> **实施期机制缺口修正（2026-07-27，v2.17 实现时发现）**：原机制下 `release_subgate` 无条件 `advance_state`——对 advance="phase" 节点会把 understand->plan **大闸门静默吸收**（一次 /dl gate 既放子闸门又穿大闸门，且 understand.md 失去写入窗口），与本节「放行后写产物 + PHASE_DONE + 第二次 /dl gate」的设计矛盾。修正三处：①engine `release_subgate` 对 advance="phase" 节点**只放行不推进**；②新增 engine `phase_done_channel_open` 单源判据（末步已判过 + 门栏未扣留 + advance="phase"），Stop hook 据此把 PHASE_DONE fall-through 到阶段大闸门分支（编排节点原本在子步骤门控分支即返回，PHASE_DONE 不可达）；③workflow_phase 注入加第三态（编排完成 + 门栏已放行 -> 提示写产物 + PHASE_DONE，防模型重做已判过的子5）。

## 3. 门控设计要点（§3.5 对齐）

- **双结论制 ×2（#3）**：子1 接受「只能定性验收」为合法结论（须逐目标理由；**编程域收紧——须说明为何不可执行验证，可执行验证的目标标定性 = 偷懒**，2026-07-27 修订）；子2 接受「不可检验化退回」为合法出口（Volere 退回信号）——否则逼模型硬编假指标（同 ProblemContext 子1 逼编造痛点机制）。
- **Goodhart 分层**（#2）：形式要件（覆盖度/双向追溯/三要素/三态处置/六字段验收包/单句）披露进 purpose；质量判据（非空泛/非编造/假指标/非放水/非越权拍板）只留 gate 黑盒。
- **四桶分工**：标准候选/可检验化/验收设计 = 模型（写什么）；trace 落库 = append-trace 脚本（怎么写）；结构完整性 = judge（过不过）；阈值拍板/验收方式认可/退回项处置 = 用户（认不认）。
- **judge 不判「阈值定多少合适」**——只判「三要素齐备 + 基线有出处 + 只提案未拍板」。阈值高低的真值源只有用户（子5）。
- **判据合法获取路径**（#7）：子2 基线实测有 fence_allow=("Bash",)；子3 手段验证有 fence_allow=("Bash",) + 常驻集 codegraph/Read——判据要求的佐证形式存在低成本合法获取路径，不逼编造。
- **消费契约倒推**（本节点独有）：验收包六字段（指标/基线/阈值/方法/时机/证据形式）不是拍的，是 review:0 rubric「判定 solved/partial/not 附 file:line 证据」的判定需求倒推的——缺任一字段 review 判定就得临时找补。

## 4. 外部实证出处（2026-07-27 Tavily 取证留痕）

- **Volere fit criterion**（Robertson & Robertson，Volere Requirements Specification Template v16；ReqView/Modern Requirements 解读）：「You make a requirement testable by adding its fit criterion… **If a fit criterion cannot be found for a requirement, then the requirement is either ambiguous or poorly understood.** All requirements can be measured, and all should carry a fit criterion」；fit criterion = 量化目标即验收标准（acceptance criterion）；snow card 原子需求壳——子2 可检验化步 + 不可检验退回信号 + 子4 原子性的直接依据。
- **INCOSE Guide to Writing Requirements**（INCOSE-TP-2010-006）：C7 Verifiable 是首要特性（「verifiability should be addressed as the initial criterion」）；不可验证三大成因 = 行为/条件/状态未定义、可接受性能范围缺精度、模糊词；模糊词禁令（some/any/several/many/a lot of/significant/adequate/efficient/effective/reasonable… + escape clauses + open-ended clauses）；**A2 主验证方法属性**——每条需求须声明四法之一（test/demonstration/inspection/analysis）作为验收证明手段；**verification point-of-view**——「imagine yourself performing the verification event」「How will I know if the requirement has been met?」——子1 验收视角提问 + 子2 模糊词清单 + 子3 四法选择的直接依据。
- **INCOSE Enchantment（Hefner）需求类型×验证方法映射**：功能→demonstration、性能→test、设计约束→inspection、质量属性→analysis——子3 方法选择理由的参照系。
- **Fitness functions**（Neal Ford / Rebecca Parsons / Patrick Kua，《Building Evolutionary Architectures: Automated Software Governance》2nd ed.）：fitness function = 对架构特征的客观完整性度量机制；atomic vs holistic、**triggered vs continuous** 二分；「fitness functions may not be implementable in software (e.g., a required manual process)」——子3 时机标注（triggered/continuous）+ 可行性三态（手段未必可实现 → 待建标注）的直接依据。
- **Wiegers「unverifiable = wish」**（自 GoalsAndValue §4 沿用）——S1 失效模式的经典表述。

## 5. 否决的替代方案（对抗性审视留痕）

1. **4 步版（子2+子3 合并「可检验化与验收设计」）**——否。可检验化是创造性转换活（写什么指标），可行性验证是机械取证活（手段有没有），异族合并稀释 judge 判力；且 fence_allow 按步声明，合并会让转换步就放开 Bash 扩大探查窗口（同 ScopeAndConstraints 否决 4 步版逻辑）。
2. **6 步版（子3 拆成取证+质检裁决双步，照抄 ProblemContext）**——否。本地单层源没有「五层源过程质量」可判，独立质检步判无可判 = 纯烧 judge（ScopeAndConstraints 已用同理由否决过同构方案）。
3. **不设独立可检验化步，并入子1 引出**——否。Volere 的核心洞见是「找不到 fit criterion = 标准本身有问题」是**退回信号**；与引出混步会被「引出即定性」吞掉，假指标失效模式（S1/S4）失去专门判点。
4. **hold_for_gate 不加**——否（2026-07-27 用户决议加）：与 understand:3 同款隔离测试语义。不加的理由（大闸门紧邻已提供隔离点）成立但用户选择牺牲一次 /dl gate 换编排验证窗口，代价已知情接受。

## 6. 实施 checklist（改编排必过，症状 M + §3.7）

1. `dl_flow_nodes.py`：`understand:4` Node 加 `sub_steps`（5 个 Step 定义，含 short/purpose/input/record/gate/fence_allow/selfcheck）+ `hold_for_gate=True`；**gate_rubric -> None**（子阶段级 rubric 被子步骤门控取代，同前三节点）；**gate_mech=ARTIFACT_EXISTS 保留**（understand.md 仍是大闸门机械门，artifact 字段不变）；新增 `_S4_STEP1_FORM_REQUIREMENTS` 常量（单源：purpose 模型侧与 gate judge 侧都引用）；自查 checklist 只列已披露形式要件（test_selfcheck_no_quality_criteria_leak 同构钉死）
2. `hooks/workflow_phase.py` `_format_injection`：**预期无需改**（子步骤清单动态读 Step.purpose；minor_key=SuccessCriteria 映射已存在）——冒烟验证
3. `scripts/workflow/phase-rules.md`：understand:4 段 GENERATED 标记段（launcher 渲染自动同步）+ 静态强制语义（写 evidence 是 STEP_DONE 前置/输完即 end_turn/末子步过后写 understand.md 再 PHASE_DONE）
4. `skills/workflow-creation/SKILL.md`：§0 子步骤摘要（understand:4 5 步 + 门栏位置：understand:2/3/4 三门栏）+ §3.8 关键不对称表加第四行（SuccessCriteria=规范性目标的可检验化转换）
5. `tests/test_dl_flow_engine.py`：新 Step 定义测例（5 步数/各 gate 含关键判据/子2+子3 fence_allow/子5 gate=None/selfcheck 无质量判据泄漏/hold_for_gate=True）；**fixture 迁移**——原「无编排节点」占位 understand:4 需换 plan:0（症状 M #7 fixture 迁移教训：ScopeAndConstraints 编排时迁了 9 处，逐处 grep 别漏）；**hold_for_gate 首个 advance="phase" 节点的 pinning 测试**（末子步 pass -> held -> /dl gate subgate-pass -> 推进 plan 全路径）；排他性/唯一性断言全量遍历 `_NODES`（禁抽样，症状 M #7）
6. 冒烟：真实 state 直调 `_format_injection` + `render-phase-rules`（§3 #10 法，不开会话）；真实 TTY 跑一轮验证推进 + 门栏扣留 + 放行后 understand.md + PHASE_DONE

## 7. 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| 1 | 模型替用户拍板阈值（越权风险裁决） | 子2 purpose 写死「只提案不拍板」；judge 黑盒抓「无提案-待裁决语义」；子5 是阈值唯一裁决点 |
| 2 | 假指标（指标与目标 outcome 不相关，拿可测的替代该测的） | 子2 gate 黑盒专判；Volere 退回通道是合法出口（不可检验 -> 退回，不硬编） |
| 3 | 子2 基线测量/子3 手段验证变无界探查 | fence_allow=("Bash",) 白名单即边界；「无基线+原因」「验收手段待建」是合法留痕防硬凑 |
| 4 | hold 首次用于 advance="phase" 节点（机制新路径 latent bug） | pinning 测试先行（症状 M #7）；实施时先在测试里走通全路径再冒烟 |
| 5 | 验收时机标注流于形式（全标 triggered 或无脑标 continuous） | 子3 gate 黑盒「事后验证未标注风险判 block」；purpose 内嵌本项目实例（T+1 实战只能事后验，review 期用回测代理）作锚 |
| 6 | understand.md 汇总与归一化陈述脱节（汇总时改写/丢失验收包字段） | understand.md 内容 = 4 子阶段归一化陈述的直接装配（禁二次创作）；大闸门 judge rubric 已含「可验证成功标准」检查兜底 |
