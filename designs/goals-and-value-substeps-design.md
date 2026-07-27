# understand:2「明确目标和价值」子步骤编排设计（GoalsAndValue）

> 状态：**已实施**（2026-07-26；engine/phase-rules/SKILL/tests 已同步，312 tests 全绿；设计已与用户确认：5 步 / 不加 hold_for_gate / 先写本文档）
> 实施期增量发现：多编排节点共用 evidence 且 sub_step 都从 1 起——trace 匹配层（_iter_trace_segments 一族 + reset_sub_step + redteam_prompt + workflow_advance S13）原只按 sub_step 匹配会**跨节点串号**（ProblemContext 子1 trace 被 GoalsAndValue 门控误读），已加 minor_stage 过滤（None=不过滤向后兼容；corrupt 检测保留无 minor_stage 截断碎片防卡死回退）。
> 父文档：`node-step-orchestration-design.md`（子步骤编排机制）、`understand-subphases-design.md`（4 子阶段划分，sub2 goal=「明确本次达成什么、为谁解决什么、价值；分 must/nice」）、`step3-verify-redesign-design.md` + `step5-step6-statement-readback-redesign-design.md`（ProblemContext 6 步范式）、`workflow-creation` SKILL.md §3.5（rubric 方法论）/ §3.7（四桶分工）
> 外部取证：本文 §4（Tavily 检索，2026-07-26，设计期调研——用户明示允许；与运行期 understand:1 子3「禁 tavily/WebSearch」约束无关）

## 0. 背景

understand:2（GoalsAndValue）当前无 `sub_steps` 编排——模型自由发挥「明确目标和价值」，无任何门控。ProblemContext（understand:1）6 步编排已验证有效（v2.6-v2.14），本文为 understand:2 设计同机制子步骤。

输入 = ProblemContext 终态：归一化问题陈述集（携带四态 verdict + 置信度 + 用户选定本实例处理项）。
输出 = understand.md「目标价值」节（understand-subphases-design §0：sub2->目标价值）。

## 1. 第一性原理

### 1.1 终态三属性（同构 ProblemContext）

| 属性 | 在本子阶段的含义 | 承担步骤 |
|---|---|---|
| 内容正确 | 目标真承接已验证问题（无孤儿目标/孤儿问题）；价值论证有依据非空泛；must/nice 反映真实取舍 | 子1-3 |
| 形式可移植 | 归一化目标陈述（原子/去上下文/携带分层与 verdict 边界），understand:4 可据此直接写成功标准 | 子4 |
| 用户认可 | 目标与价值是**规范性命题**，用户是唯一 ground truth | 子5 |

### 1.2 关键不对称：为什么不能照抄 ProblemContext 6 步

ProblemContext 的两个重步——子3 双向取证（五层源）+ 子4 质检裁决（三关质检+红队+四态 verdict）——存在理由是「问题是**事实性命题**，可被外部证据证实/证伪」。

目标与价值是**规范性命题**：
- 「这个目标值得做」无法被 OpenAlex/GitHub 证伪——五层源取证对规范命题无对象；
- judge 判得了「价值论证结构是否完整」，判不了「价值高不高」（§3.5 #1 三层分工）；
- 分层（must/nice）是规范裁决，模型只能**提案附理由**，裁决权必须在用户手里（四桶分工：写什么=模型，认不认=用户）。

→ 取证/裁决双步在本子阶段无对应物，砍掉。步数由目标定义**自己的失效模式族**决定。

### 1.3 失效模式分析

| # | 失效模式 | 外部出处（§4） |
|---|---|---|
| G1 | 目标-问题脱节：脑补目标（孤儿目标=gold-plating）/ 已验证问题无目标承接（孤儿问题） | 双向可追溯文献：forward 查覆盖、backward 查镀金 |
| G2 | 手段-目的倒置：目标写成方案（「做一个X工具」），plan 被锁死在实现上 | INCOSE/BABOK「implementation-free」；KAOS WHY 问向父目标剥离 |
| G3 | 分层失真：全标 Must（无真实取舍）/ 分层无理由 / 模型越权替用户裁决 | MoSCoW 三大批评 |
| G4 | 价值断言无据：无受益者、无痛点链接、「提升效率」式模糊词无量化基线 | INCOSE R7 模糊词禁令；Wiegers「unverifiable = wish」 |
| G5 | 目标间冲突未检 / 目标过于理想化 | KAOS conflict & obstacle analysis |
| G6 | 复合/模糊目标：一句多目标、脱离上下文不可解 | BABOK/INCOSE：atomic、singular、unambiguous |
| G7 | 用户未认可：模型自定目标自 high | §3.5：认可度归用户 |

**边界划分（与 understand:3 的接口）**：G5 拆两半——**目标间冲突**归本子阶段（judge 正看着目标集，顺手判）；**目标的外部障碍**（什么约束会阻碍达成）归 understand:3「确定范围与约束」——障碍的来源就是约束，obstacle analysis 在那里做更自然。

## 2. 设计：5 步

```
子1 目标引出 → 子2 对齐质检 → 子3 价值论证与分层提案 → 子4 归一化陈述 → 子5 读回确认
```

judge 调用 4 次（子5 gate=None）。按失效模式族拆步：子2=结构对齐族（G1+G2+G5a），子3=规范论证族（G3+G4），子4=形式可移植族（G6）——异族拆开（judge 分步可判），同族合并（省 judge）。

### 子1 目标引出（kind=tool）

- **ref**：`推理(KAOS WHY/HOW 问) / AskUserQuestion(补问)`
- **purpose**：从归一化问题陈述逐条问「解决它=达成什么状态」；覆盖 who（受益者）/outcome/初步价值 ≥3 类，q/a 按序对齐，答案引用用户原话或会话事实；缺口才 AskUserQuestion 事实性补问（沿用 ProblemContext 子1 取证纪律：优先上下文已有原话，禁重问已答内容）；结论逐句须有出处，无出处的推断只能标「推测」另列。**双结论制**：①目标成立=每个存活问题 ≥1 目标候选；②目标不成立=用户声明字面请求即全部/无进一步诉求+原话佐证（防逼编造价值，§3.5 #3）。
- **input**：`ProblemContext.step5.statements`（跨节点引用，实现时写明读 evidence 里 minor_stage=ProblemContext 最新归一化陈述 trace）
- **record**：True；**fence_allow**：无（AskUserQuestion 在常驻集）
- **gate**：trace 存在；形式要件（覆盖度/对齐/原话出处/双结论形式）；质量判据黑盒（答案非空泛复述；②的无目标声明须原话佐证——本步补问回答原话合法，从未问及的「未提及」不算）。

### 子2 对齐质检（kind=tool）

- **ref**：`推理(双向追溯矩阵+方案剥离+冲突检测)`
- **purpose**：不做新交互，只审子1 目标集对齐质量——①双向追溯矩阵：每个目标回溯 ≥1 已验证问题（backward，防镀金），每个存活问题有目标承接或显式搁置+理由（forward，防漏）；孤儿目标剔除或退回子1 补问；②solutioneering 剥离：目标陈述含方案名词/实现动词 → WHY 问一层（「为什么要 X」）剥到 outcome 状态；③目标间冲突检测：两目标不可兼得处显式标注（留子5 用户裁决）。trace 须含完整矩阵（问题×目标逐项），汇总声明不算记录。
- **input**：`step1.goal_candidates`
- **record**：True；**fence_allow**：无（纯推理+读 evidence，Read 在常驻集）
- **gate**：trace 存在；形式要件（双向矩阵完备；孤儿项显式处置；含方案陈述已改写 outcome；冲突已标注）；质量判据黑盒（剥离后 outcome 非同义反复——「做 X 为了能做 X」判 block；矩阵放水——明显无关联的问题-目标硬连判 block）。

### 子3 价值论证与分层提案（kind=tool）

- **ref**：`推理(价值链+分层理由) / Bash(条件性基线测量)`
- **purpose**：每目标产出：①受益者（为谁解决）；②价值链（目标→承接的痛点→价值类型）；③量化基线——可测处实测现状（如当前流程耗时/数据量/报错频率，Bash 查数据/日志）；**不可量化显式标注「不可量化+原因」=合法留痕**（no silent fallback 同构）；④must/nice **提案附理由**（MoSCoW 批评：无 rationale 的分层无效；裁决权留子5 用户，本步只提案）。禁模糊词无度量支撑（「提升效率」无基线=断言非论证）。
- **input**：`step2.aligned_goals`
- **record**：True；**fence_allow**：`("Bash",)`（基线测量；S15 白名单按步骤声明）
- **gate**：trace 存在；形式要件（受益者+痛点链接+基线或显式不可量化标注+分层理由，逐项齐全）；质量判据黑盒（价值论证非空泛复述；模糊词无度量支撑判 block；基线数字须有工具留痕出处，拍脑袋数字=编造判 block）。

### 子4 归一化陈述（kind=skill）

- **ref**：`define-problem`（claim normalization 职能同构复用 ProblemContext 子5）
- **purpose**：对子3 论证后目标集逐项产出归一化目标陈述——①原子（单句 ≤1 个独立目标，「和/以及/同时」连接多目标=复合未拆净，回子1 重引）；②去上下文（主语+动词+约束自包含）；③携带 must/nice 提案 + verdict 边界（部分成立问题的目标只覆盖已证实边界——裁决传导，同构 ProblemContext 子5）；④solution-free 复核（归一化后仍含方案名词=子2 剥离不净，回子2）。
- **input**：`step3.valued_goals`
- **record**：True；**fence_allow**：无
- **gate**：trace 存在；形式要件（单句+主语+动词+约束；携带分层与置信度）；质量判据黑盒（陈述集与子3 逐项一致——分层/边界不传导判 block；单句多目标判 block；含方案名词判 block）。

### 子5 读回确认（kind=skill）

- **ref**：`define-problem / AskUserQuestion`
- **purpose**：向用户呈现 归一化目标陈述+追溯链+价值论证+must/nice 提案+不确定性（「不可量化」项显式暴露）；**用户裁决 must/nice**（本子阶段唯一规范裁决点——分层真值归用户）；用户对各目标认/否/调层记入 trace；多目标时用户圈定本实例范围，其余落 evidence + understand.md（供后续 dl 实例，不丢弃）。
- **input**：`step4.statements`
- **record**：True（确认内容是 Stop 门控完成触发 + 裁决留痕）；**fence_allow**：无
- **gate**：None（交互步，trace 存在即过）

### hold_for_gate：2026-07-27 起**加**（决议变更）

原决议（2026-07-26）不加：保持「子阶段间无闸门」、子5 读回已含用户裁决、understand→plan 大闸门兜底。
**变更（2026-07-27 用户决议）**：门栏自 understand:1 **移到** understand:2——「问题 + 目标价值」是 understand 的地基组，一轮完整跑 ProblemContext + GoalsAndValue 后在 GoalsAndValue 末步扣留等 `/dl gate`；ProblemContext 不再单独扣留（其子6 读回确认已守「陈述的认可」，无需两个相邻裁决点）。

## 3. 门控设计要点（§3.5 对齐）

- **双结论制**（#3）：子1 接受「目标不成立」为合法结论——ProblemContext 已可能得出②「字面请求即全部」，GoalsAndValue 必须能直通对应结论，否则逼模型编造价值。
- **Goodhart 分层**（#2）：形式要件（覆盖度/矩阵/逐项齐全/单句）披露进 purpose；质量判据（非空泛/非同义反复/非编造）只留 gate 黑盒。
- **四桶分工**：目标提案/价值论证/分层提案 = 模型（写什么）；trace 落库 = append-trace 脚本（怎么写，v2.14 机制直接继承）；结构完整性 = judge（过不过）；分层裁决/目标认可 = 用户（认不认）。
- **judge 不判价值高低**——只判「价值论证形式完整 + 非空泛非编造」。规范命题的真值源只有用户（子5）。

## 4. 外部实证出处（2026-07-26 Tavily 取证留痕）

- **KAOS/goal-oriented RE**（van Lamsweerde；TSE 2000「Handling Obstacles in Goal-Oriented RE」；guided tour 2001）：goal elaboration 靠 **WHY 问**（向父目标抽象——solutioneering 剥离的依据）与 **HOW 问**（向子目标求精）；**obstacle analysis** = 否定目标找 what-could-go-wrong，「first-sketch goals tend to be too ideal」；obstacle 是 N=1 的退化 conflict——目标间冲突检测与障碍分析同源（本设计把前者留本阶段、后者划给 understand:3）。
- **双向可追溯**（trace.space「How to Write Good Requirements」2024；SodiusWillert RTM 指南；Standish 2024：38% 项目失败追溯至需求不准）：forward（问题→目标，查覆盖/漏项）+ backward（目标→问题，查 gold-plating）缺一不可——子2 追溯矩阵双向完备的直接依据。
- **MoSCoW 批评**（Wikipedia；ProductPlan；Stoneseed；Agile Business Consortium/DSDM）：三大失效 = 一切皆 Must（无真实取舍）、无 rationale（「为什么 must 不 should」无记录）、缺有权取舍的 stakeholder 拍板——子3「提案附理由」+ 子5「用户裁决分层」的出处；「What happens if this isn't met → project fails」= Must 判定试金石。
- **需求质量准则**（INCOSE Guide to Writing Requirements 2023；BABOK v3；Wiegers「Writing Quality Requirements」1999）：atomic/singular（一句一条件）、unambiguous（R7：minimize/maximize/optimize 类模糊词不可接受，须可测阈值）、verifiable（「unverifiable 的陈述不是 requirement 是 wish」）、**implementation-free**（solution-free）、necessary+prioritized；集合级 consistent/nonredundant/complete——G2/G4/G6 判据的出处。

## 5. 否决的替代方案（对抗性审视留痕）

1. **6 步全对称版**（保留取证+质检裁决双步）——否。规范命题无外部事实可取；硬设取证步会逼模型拿「业界通常」式训练记忆冒充价值依据（恰是 ProblemContext 子3 gate 专抓的编造模式）。
2. **4 步合并版**（子2+子3 合为「目标质检」）——次优备选，被用户否决（2026-07-26 选定 5 步）。省 1 次 judge，但结构对齐（追溯矩阵）与规范论证（价值/分层）异族，合并稀释 judge 判力。
3. **子3 加红队子代理**——否。ProblemContext 红队对抗事实性结论；价值论证的对立审查=「找方案伪装的目标」已由子2 覆盖；judge 成本不值。
4. **must/nice 独立成步**——否。分层=规范裁决，模型侧只有「提案附理由」（并入子3），裁决在用户（并入子5）；独立步只多一轮空转。
5. **加 hold_for_gate**——原决议不加（2026-07-26）；**2026-07-27 决议变更：加，且 understand:1 的门栏同时移除**（门栏移到本子阶段，§2 末）。

## 6. 实施 checklist（改编排必过，症状 M + §3.7）

1. `dl-flow-engine.py`：`understand:2` Node 加 `sub_steps`（5 个 Step 定义，含 short/purpose/input/record/gate/fence_allow/selfcheck）；形式要件单源常量（`_STEP*_FORM_REQUIREMENTS` 同构）；**自查 checklist 只列已披露形式要件**（test_selfcheck_no_quality_criteria_leak 同构钉死）
2. `hooks/workflow_phase.py` `_format_injection`：**预期无需改**（子步骤清单动态读 Step.purpose）——冒烟验证
3. `scripts/workflow/phase-rules.md`：understand:2 段 GENERATED 标记段（launcher 渲染自动同步）+ 静态强制语义（写 evidence 是 STEP_DONE 前置/输完即 end_turn）
4. `skills/workflow-creation/SKILL.md`：§0 子步骤摘要（understand:2 5 步）+ 版本标注
5. `tests/test_dl_flow_engine.py`：新 Step 定义测例（5 步数/各 gate 含关键判据/子5 gate=None/selfcheck 无质量判据泄漏）
6. 冒烟：真实 state 直调 `_format_injection` + `render-phase-rules`（§3 #10 法，不开会话）；真实 TTY 跑一轮验证推进

## 7. 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| 1 | 模型替用户裁决分层（越权规范裁决） | 子3 purpose 写死「只提案附理由」；子5 是唯一裁决点；judge 黑盒抓「提案无理由/替用户拍板」 |
| 2 | 基线测量变无界探查 | fence_allow=("Bash",) 白名单即边界；「不可量化+原因」是合法留痕防硬凑数字 |
| 3 | 跨节点 input 引用（子1 读 ProblemContext trace） | engine `read_evidence_for_step` 已支持跨步最新 trace 裁剪（v2.12）；实现时验证 minor_stage=ProblemContext 可读 |
| 4 | 双结论制被滥用为偷懒出口（不引目标直接②） | 同 ProblemContext 子1：②须原话佐证，「未提及」不算（§3.5 #7 问→引路径已通） |
