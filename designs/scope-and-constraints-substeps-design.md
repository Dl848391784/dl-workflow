# understand:3「确定范围与约束」子步骤编排设计（ScopeAndConstraints）

> 状态：**已确认**（2026-07-27 用户三决议：5 步 / **加 hold_for_gate** / 先拆 engine 再加 sub_steps）
> 父文档：`node-step-orchestration-design.md`（子步骤编排机制）、`understand-subphases-design.md`（4 子阶段划分）、`goals-and-value-substeps-design.md`（GoalsAndValue 5 步范式 + obstacle analysis 划给本子阶段的接口约定）、`step3-verify-redesign-design.md` + `step5-step6-statement-readback-redesign-design.md`（ProblemContext 6 步范式）、`workflow-creation` SKILL.md §3.5（rubric 方法论）/ §3.7（四桶分工）
> 外部取证：本文 §4（Tavily 检索，2026-07-27，设计期调研——用户明示允许；与运行期 understand:1 子3「禁 tavily/WebSearch」约束无关）

## 0. 背景

understand:3（ScopeAndConstraints）当前无 `sub_steps` 编排——模型自由发挥「确定范围与约束」，无任何门控。ProblemContext 6 步、GoalsAndValue 5 步编排已验证有效（v2.6-v2.15），本文为 understand:3 设计同机制子步骤。

输入 = GoalsAndValue 终态：归一化目标陈述集（携带 must/nice 用户裁决 + verdict 边界 + 用户圈定本实例处理范围）。
输出 = understand.md「范围与约束」节（understand-subphases-design §0：sub3->范围与约束），供 understand:4 写成功标准直接消费。

## 1. 第一性原理

### 1.1 终态三属性（同构 ProblemContext / GoalsAndValue）

| 属性 | 在本子阶段的含义 | 承担步骤 |
|---|---|---|
| 内容正确 | 约束真实存在（非编造、非假设冒充事实）；范围与目标双向对齐（无孤儿范围/孤儿目标） | 子1-3 |
| 形式可移植 | 归一化范围/约束陈述（原子/去上下文/携带类型与假设标注），understand:4 可据此直接写成功标准 | 子4 |
| 用户认可 | 范围边界（in/out）是规范性裁决；假设的接受 = 风险承担，真值归用户 | 子5 |

### 1.2 关键不对称：本子阶段是**混合命题**（与前两阶段都不同）

| 子阶段 | 命题性质 | 编排后果 |
|---|---|---|
| ProblemContext | 纯事实性 | 五层外部源取证 + 质检裁决双步 |
| GoalsAndValue | 纯规范性 | 无取证步（外部证据无权证伪「我想要什么」） |
| **ScopeAndConstraints** | **混合**：约束=事实性，范围=规范性，假设=中间态 | 约束需取证但**只需本地单层源**；范围裁决权归用户 |

三类命题分开处理：

- **约束（constraint）= 事实性命题**：存在于代码库/数据/权限/环境/时间中，可被本地证据验证或证伪。但取证源是**项目内部事实**（Bash 验证文件/数据存在性、codegraph 验证结构约束、Read 验证接口），不是 ProblemContext 的五层外部源——发现与验证深度浅，可压缩为一步，不需要独立质检裁决步。
- **假设（assumption）= 中间态**：「未被证明但被当作真」（PMBOK：assumptions stated without proof；LUC：「预算是事实，预算够用是假设」）。必须显式标注 + 评估（置信度 × 错误时影响），**接受与否 = 风险承担，是规范裁决，归用户**——模型无权替用户接受一个「假设够用」。
- **范围（scope）= 规范性命题**：in/out 拍板归用户，模型只提案（从 must/nice 裁决 + 用户已圈定范围派生）。

### 1.3 失效模式分析

| # | 失效模式 | 外部出处（§4） |
|---|---|---|
| C1 | 约束遗漏：未发现的约束在 execute 期爆炸返工（「first-sketch goals too ideal」） | KAOS obstacle analysis（van Lamsweerde TSE 2000） |
| C2 | 假设冒充约束：未验证的信念当事实用 | PMBOK assumptions vs constraints 区分；LUC「impact of incorrect assumption」 |
| C3 | 编造约束：训练记忆冒充项目事实 | 同 ProblemContext 子3 专抓的编造模式 |
| C4 | 范围无显式 out-of-scope 清单 → scope creep | PMI 五大 scope creep 原因之首 = unclear scope；52% 项目经历 scope creep；scope statement 必须 in+out 双侧 |
| C5 | 范围-目标脱节：in-scope 无目标承接（镀金）/ must 目标无范围覆盖（漏） | 双向可追溯（同构 GoalsAndValue 子2） |
| C6 | 越权裁决：模型自定范围/替用户接受假设 | §3.5/四桶分工：认不认归用户 |
| C7 | 复合/模糊范围陈述，脱离上下文不可解 | INCOSE/BABOK atomic/singular |

**接口约定**（goals-and-value-substeps-design §1.3 已划界）：目标间冲突归 GoalsAndValue 子2；**目标的外部障碍归本子阶段**——障碍的来源就是约束，obstacle analysis 在这里做（KAOS：obstacle = N=1 的退化 conflict，与冲突分析同源）。

## 2. 设计：5 步

```
子1 障碍分析与约束引出 → 子2 约束验证与假设标注 → 子3 范围界定 → 子4 归一化陈述 → 子5 读回确认
```

judge 调用 4 次（子5 gate=None）。按失效模式族拆步：子1=发现族（C1），子2=真伪族（C2+C3），子3=边界对齐族（C4+C5），子4=形式族（C7），子5=认可族（C6）。异族拆开（judge 分步可判），同族合并（省 judge）。

### 子1 障碍分析与约束引出（kind=tool）

- **ref**：`推理(KAOS 障碍分析) / AskUserQuestion(补问)`
- **purpose**：对每个 must 目标做否定提问「什么会使它失败」（obstacle = goal 的对偶，KAOS）引出约束候选；覆盖类型 ≥3 类（数据/环境/权限/时间/资源/外部依赖）；用户侧约束（deadline/人力/权限）缺口走 AskUserQuestion 事实性补问（沿用 ProblemContext 子1 取证纪律：优先上下文已有原话，禁重问已答内容）。**双结论制**：①约束成立=每 must 目标 ≥1 约束候选或显式「无约束+理由」；②「除已列外无实质约束」是合法结论，但须每个 must 目标都做过否定提问留痕——「未做过否定提问的『无约束』」= 懒得想，不算（防双结论制被滥用为偷懒出口，同 ProblemContext 子1）。
- **input**：`GoalsAndValue.step4.statements`（跨节点引用：读 evidence 里 minor_stage=GoalsAndValue 最新归一化目标陈述 trace，取 must 目标集）
- **record**：True；**fence_allow**：无（AskUserQuestion 在常驻集）
- **gate**：trace 存在；形式要件（must 目标全覆盖否定提问；覆盖类型 ≥3 类；q/a 对齐；补问原话出处）；质量判据黑盒（约束候选非空泛复述——「数据可能不准」无具体对象判 block；否定提问形式主义——每目标同一句套话判 block）。

### 子2 约束验证与假设标注（kind=tool）

- **ref**：`Bash(本地验证) / codegraph(结构约束) / Read`
- **purpose**：对子1 约束候选逐条定真伪，**三态输出**：①已验证约束（项目内部事实用工具验证——数据文件存在性/新鲜度、接口签名、权限、环境配置，附工具留痕出处）；②假设（无法低成本验证 → 显式标注「假设+置信度+错误时的影响」，LUC 的 impact-of-incorrect-assumption 分析）；③证伪剔除（附证据）。不可验证又不标假设 = 静默兜底（no silent fallback 同构）。本步是 ProblemContext 子3+子4 的**压缩版**——取证源是本地单层、真伪判断浅，一步完成，无独立质检裁决步。
- **input**：`step1.constraint_candidates`
- **record**：True；**fence_allow**：`("Bash",)`（本地验证；codegraph/Read 在常驻集）
- **gate**：trace 存在；形式要件（子1 候选逐条三态处置；已验证项附工具出处；假设项含置信度+影响）；质量判据黑盒（已验证项无工具出处=编造判 block；「未验证」直接进约束集（假设未标注）判 block；训练记忆冒充项目事实判 block）。

### 子3 范围界定（kind=tool）

- **ref**：`推理(双向追溯矩阵+约束回写)`
- **purpose**：从 must/nice 裁决 + GoalsAndValue 子5 用户圈定范围派生 **in-scope / out-of-scope 双侧清单**（PMI：只有 in 侧 = scope creep 温床；out 侧显式列举「看似该做但不做」的项）；双向追溯：每个 in-scope 项回溯 ≥1 must 目标（backward，防镀金），每个 must 目标有范围覆盖或显式搁置+理由（forward，防漏）；**约束回写**：已验证约束/已标注假设迫使缩小范围处显式记录（obstacle resolution = alternative scope，KAOS）。**只提案不拍板**（裁决权留子5）。trace 须含完整矩阵（目标×范围项逐项），汇总声明不算记录。
- **input**：`step2.verified_constraints` + `GoalsAndValue.step5.user_decisions`
- **record**：True；**fence_allow**：无（纯推理 + 读 evidence，Read 在常驻集）
- **gate**：trace 存在；形式要件（in/out 双侧清单；双向矩阵完备；孤儿项显式处置；约束回写已记录）；质量判据黑盒（out-of-scope 空清单=无真实取舍从严裁量；矩阵放水——明显无关联的目标-范围硬连判 block；替用户拍板范围（无「提案-待用户裁决」语义）判 block）。

### 子4 归一化陈述（kind=skill）

- **ref**：`define-problem`（claim normalization 职能第三次复用——ProblemContext 子5 / GoalsAndValue 子4 同构）
- **purpose**：对子3 范围与约束集逐项产出归一化陈述——①原子（单句 ≤1 个独立范围项/约束，「和/以及/同时」连接多项=复合未拆净，回子3）；②去上下文（主语+动词+约束自包含）；③携带类型标签（约束=已验证 or 假设+置信度；范围=in or out）与 verdict 边界（部分成立目标的范围只覆盖已证实边界——裁决传导）；④solution-free 复核（范围项含方案名词=GoalsAndValue 子2 剥离不净残留）。放不进一句=未定义完。
- **input**：`step3.scope_proposal`
- **record**：True；**fence_allow**：无
- **gate**：trace 存在；形式要件（每项 ≤1 句且含主语+动词+约束；携带类型标签与边界）；质量判据黑盒（陈述集与子3 逐项一致——类型标注/边界不传导判 block；单句含多项并列=复合未拆净判 block）。

### 子5 读回确认（kind=skill）

- **ref**：`define-problem / AskUserQuestion`
- **purpose**：带证据的读回确认：向用户呈现 归一化范围双侧清单+约束集（已验证附出处）+假设清单（置信度+影响）+不确定性；**用户裁决两件事**：①范围边界（in/out 拍板——本子阶段第一规范裁决点）；②假设的接受（风险承担是规范裁决，模型无权替用户接受——第二规范裁决点）；用户认/否/调整记入 trace；多约束/假设时用户圈定本实例处理项，其余落 evidence + understand.md（供后续 dl 实例接续，不丢弃）。
- **input**：`step4.statements`
- **record**：True；**fence_allow**：无
- **gate**：None（交互步，trace 存在即过）

### hold_for_gate：**加**（2026-07-27 用户决议）

GoalsAndValue 完成后自动进入本子阶段（无门栏边界自动续轮）；**本子阶段末子步骤过门控后无条件扣留**（state.held_for_gate），唯一出口 `/dl gate`。语义 = **隔离测试**：新编排阶段跑完后被围栏围住不继续进 understand:4，直到用户测试验证没问题。门栏位置现状：understand:1=无，understand:2=有，understand:3=有（本设计新增）。

## 3. 门控设计要点（§3.5 对齐）

- **双结论制**（#3）：子1 接受「无实质约束」为合法结论——但须每 must 目标做过否定提问留痕，区分「诚实无约束」vs「懒得想」（同 ProblemContext 子1「未提及不算」判据）。
- **Goodhart 分层**（#2）：形式要件（覆盖度/三态处置/双侧清单/矩阵/单句）披露进 purpose；质量判据（非空泛/非编造/非放水/非越权）只留 gate 黑盒。
- **四桶分工**：约束候选/验证/范围提案 = 模型（写什么）；trace 落库 = append-trace 脚本（怎么写）；结构完整性 = judge（过不过）；范围拍板/假设接受 = 用户（认不认）。
- **judge 不判约束「重不重要」**——只判「三态处置形式完整 + 已验证有出处 + 假设有标注」。约束的接受与范围的取舍，真值源只有用户（子5）。
- **判据合法获取路径**（#7）：子2 要求「工具留痕出处」的合法路径 = fence_allow=("Bash",) + 常驻集 codegraph/Read——判据要求的佐证形式存在低成本合法获取路径，不逼编造。

## 4. 外部实证出处（2026-07-27 Tavily 取证留痕）

- **KAOS obstacle analysis**（van Lamsweerde & Letier, TSE 2000「Handling Obstacles in Goal-Oriented RE」）：「first-sketch specifications of goals, requirements and assumptions tend to be too ideal」——obstacle analysis 的目标就是导出更完备现实的目标与假设；obstacle = goal 的对偶（否定目标找 what-could-go-wrong），可系统性从目标陈述生成；obstacle 是 N=1 的退化 conflict；resolution = alternative requirements/scope——子1 否定提问法 + 子3 约束回写的直接依据。
- **scope creep 成因**（PMI「Top Five Causes of Scope Creep」；BQE：52% 项目经历 scope creep、48% 不能按期交付）：首要成因 = unclear/undecomposed scope；scope statement **必须含 features in AND out of scope**——子3 双侧清单的出处。
- **assumptions vs constraints**（PMBOK/MPUG/InLoox/LUC PMO）：assumption = believed true without proof，constraint = true limiting factor；「预算已分配 = 事实，预算够用 = 假设」；假设必须 assess（置信度 × impact-of-incorrect-assumption）+ document + monitor——子2 三态处置（已验证/假设/证伪）与假设标注字段的出处。
- **需求质量准则**（INCOSE/BABOK，同 GoalsAndValue §4）：atomic/singular/unambiguous——子4 归一化判据出处（第三次复用 define-problem 的 normalization 职能）。

## 5. 否决的替代方案（对抗性审视留痕）

1. **4 步版（子1+子2 合并「约束发现与验证」）**——否。发现（障碍分析，创造性活）与验证（本地取证，机械活）异族，合并后 judge 一次判两件事稀释判力；且 fence_allow 按步骤声明，合并步会让「发现步就放开 Bash」扩大探查窗口。
2. **6 步全对称版（约束验证拆成取证+质检裁决双步，照抄 ProblemContext）**——否。本地单层取证没有「五层源过程质量」可判，独立质检步判无可判，纯多烧一次 judge。
3. **范围并入 GoalsAndValue（不建本子阶段）**——否。GoalsAndValue 设计已明确把 obstacle analysis 划给本子阶段（「障碍的来源就是约束」）；且范围界定依赖 must/nice 用户裁决完成，时序上必须在 GoalsAndValue 之后。
4. **假设验证加红队子代理**——否。ProblemContext 红队对抗外部事实性结论；本地约束验证的对立审查 = 「已验证项是否真有工具出处」已由子2 gate 黑盒覆盖；judge 成本不值。
5. **hold_for_gate 不加**——否（2026-07-27 用户决议加）：新编排阶段需隔离测试，跑完扣留等 `/dl gate`，验证没问题再流入 understand:4。

## 6. 实施 checklist（改编排必过，症状 M + §3.7）

**前置（用户决议：先拆再加）**：先把节点树（GateMech/Step/Node + NODES + PHASES/PHASE_LABELS）抽出为 `dl_flow_nodes.py`（零行为变化独立 commit，pytest 全绿验证），再把 5 个 Step 定义写进新文件——避免写进旧位置再搬一次。

1. `dl_flow_nodes.py`：`understand:3` Node 加 `sub_steps`（5 个 Step 定义，含 short/purpose/input/record/gate/fence_allow/selfcheck）+ `hold_for_gate=True`；**自查 checklist 只列已披露形式要件**（test_selfcheck_no_quality_criteria_leak 同构钉死）
2. `hooks/workflow_phase.py` `_format_injection`：**预期无需改**（子步骤清单动态读 Step.purpose；minor_key=ScopeAndConstraints 映射已存在）——冒烟验证
3. `scripts/workflow/phase-rules.md`：understand:3 段 GENERATED 标记段（launcher 渲染自动同步）+ 静态强制语义（写 evidence 是 STEP_DONE 前置/输完即 end_turn）
4. `skills/workflow-creation/SKILL.md`：§0 子步骤摘要（understand:3 5 步 + 门栏位置：understand:2/3 双门栏）+ 版本标注
5. `tests/test_dl_flow_engine.py`：新 Step 定义测例（5 步数/各 gate 含关键判据/子2 fence_allow/子5 gate=None/selfcheck 无质量判据泄漏/hold_for_gate=True）；fixture 检查——原「无编排节点」占位若用 understand:3 需换 understand:4（症状 M #7 fixture 迁移教训）
6. 冒烟：真实 state 直调 `_format_injection` + `render-phase-rules`（§3 #10 法，不开会话）；真实 TTY 跑一轮验证推进 + 门栏扣留

## 7. 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| 1 | 模型替用户接受假设（越权风险裁决） | 子2 purpose 写死「只标注不裁决」；子5 是假设接受唯一裁决点；judge 黑盒抓「假设未标注直接进约束集」 |
| 2 | 子2 本地验证变无界探查 | fence_allow=("Bash",) 白名单即边界；「假设+置信度+影响」是合法留痕防硬凑验证 |
| 3 | 跨节点 input 引用（子1 读 GoalsAndValue trace） | engine `read_evidence_for_step` 已支持跨步最新 trace 裁剪（v2.12）+ minor_stage 过滤（v2.15）；实现时验证 minor_stage=GoalsAndValue 可读 |
| 4 | 双结论制被滥用为偷懒出口（不做否定提问直接「无约束」） | 同 ProblemContext 子1：「无约束」须每 must 目标否定提问留痕，「未做过」不算（§3.5 #7 问→引路径已通） |
| 5 | out-of-scope 清单流于形式（随便写两条凑数） | gate 黑盒「空清单/无真实取舍从严裁量」+ 子5 用户读回时 out 侧显式呈现，用户自然会补 |
