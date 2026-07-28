# plan:2「拆解任务与阶段」子步骤编排设计（TaskBreakdown）

> 状态：**已确认**（2026-07-28 用户两连决议：①定稿 **5 步**——无发散步[对象已存在]、无独立质检裁决步[本地单层源]；②**加 hold_for_gate**（隔离测试语义，同 understand:3/4、plan:1 先例，门栏变五处）；③label「生成执行计划」→「**拆解任务与阶段**」（用户心智模型：任务=执行单元，阶段=断点组））
> 父文档：`node-step-orchestration-design.md`（子步骤编排机制）、`design-solution-substeps-design.md`（最近范式 + 消费契约倒推锚点法 + 编程工作流定位）、`success-criteria-substeps-design.md`（**首个 advance="phase" hold 节点**——本节点复用其机制路径）、`scope-and-constraints-substeps-design.md`（本地单层源压缩原则）、`workflow-creation` SKILL.md §3.5（rubric 方法论）/ §3.8（拆步方法论）
> 外部取证：本文 §4（Tavily 检索，2026-07-28，设计期调研——用户明示允许；与运行期 understand:1 子3「禁 tavily/WebSearch」约束无关）
> 讨论稿订正（2026-07-28）：讨论阶段曾主张「节点级 gate_rubric 保留（与 plan:1 不同）」——**查 understand:4 先例后订正为置 None**：阶段出口编排节点的大闸门只跑机械门（ARTIFACT_EXISTS），语义一致性由逐步门控承担（understand:4 即如此，gate_rubric=None + artifact 保留）。本设计 §3 给出订正后方案。
> 修订（2026-07-28，实施期机制走查沉淀）：注入第三态文案发现 understand:4 隐含假设——「放行后写产物」窗口不适用于本节点（plan.md 在子5 内装配，hold 前已落地），原文案「汇总写 plan.md（4 子阶段归一化陈述直接装配）」对本节点是错指令。修正：Node 新增 `artifact_on_release` 字段（True=放行后写产物[understand:4]；False=末步内已装配[plan:2，本节点]），注入第三态按字段分支文案。**机制走查（§3.8 #6）又兑现一次：设计文档写「复用 understand:4 路径无新机制」只覆盖了 engine 推进路径，没覆盖注入文案路径**。

## 0. 背景

plan:2「生成执行计划」当前是**无编排节点**：节点级 rubric「①步骤可执行 ②验证方法明确 ③守 H8/H9 ④与 DesignSolution 设计包一致」在 plan->execute 大闸门跑一次 judge，ARTIFACT_EXISTS 机械门查 plan.md。问题：plan.md 是 execute 的直接输入、全工作流「设计→执行」的保真关口，却是**唯一没有过程门控的产物**——脱节/空步骤/锚点编造只能在大闸门一次性判，返工代价 = 整份 plan 重写。本设计给 plan:2 加 **5 步编排**，label 同步改名「拆解任务与阶段」。

输入 = plan:1 拍板终态：`designs/<主题>-design.md`（H8 产物）+ evidence 里 minor_stage=DesignSolution 的设计包 trace（子5 归一化设计陈述八字段：改动清单/接口签名/数据契约/callers 清单/被否方案+理由/假设清单/验收包映射/**H9 执行单元划分**；子6 用户三裁决原话）。
输出 = `plan.md`（静态路径——与 plan:1 动态 design.md 不同，ARTIFACT_EXISTS 机械门可用），供 execute:0 直接消费。

**消费契约锚点**（同构 DesignSolution/SuccessCriteria 的第一性原理锚点）：执行步骤字段倒推自下游消费方，不是拍的——

| 下游 | 其 rubric/职责 | 倒推出的执行步骤字段 |
|---|---|---|
| execute:0 gate | 「对照 plan 步骤逐条核，偏离需有理由」+ TEST_PASS | ①改动点（file:line→改动类型——核对基准）+ ③验证方法（failing test 名+命令+期望输出——TEST_PASS 可判的前提） |
| superpowers:executing-plans / subagent-driven-development | 「follow plan steps exactly」「run verifications as specified」「assume engineer has zero context」 | ②前置接口（Consumes/Produces 签名——执行者只见自己任务）+ 步骤去上下文自包含 |
| review:0 gate | 「判定 solved/partial/not，附 file:line 证据」 | ④验收包映射（每条 SuccessCriteria 由哪些步骤承接） |
| 保真关口（本节点独有） | plan 不得与拍板设计包脱节 | ⑤追溯锚（每步骤承接哪个设计要素 ID——子1 基线使「一致性」可判） |

**编程工作流定位**（沿用 DesignSolution 元约束）：产物不是通用 WBS（阶段-里程碑-交付物），是**零上下文执行者可照做的代码级执行计划**——精确 file:line、精确命令+期望输出、TDD 周期内嵌（writing-plans bite-sized cycle：写失败测试→跑→实现→跑→commit）。通用项目管理形态产不出 file:line 与验证命令，判不出「步骤引用不存在接缝」这种病。

## 1. 第一性原理

### 1.1 终态三属性（同构前五个节点）

| 属性 | 在本子阶段的含义 | 承担步骤 |
|---|---|---|
| 内容正确 | 步骤**保真**于拍板设计包（无镀金无丢失无二次创作）；切分轴向正确（纵向可独立验证）；依赖拓扑序成立；锚点真实（文件/symbol/测试接缝/命令存在）；假设显式化 | 子1-3 |
| 形式可移植 | 归一化执行步骤携带执行包五字段，execute:0/executing-plans 可直接消费；装配为 plan.md | 子4-5 |
| 用户认可 | 阶段断点/粒度拍板、假设接受 = 规范裁决，归用户 | 子5 |

### 1.2 关键不对称（第六种）：保真转换 × 执行接地

| 子阶段 | 命题性质 | 编排后果 |
|---|---|---|
| ProblemContext | 纯事实性 | 五层外部源取证 + 质检裁决双步 |
| GoalsAndValue | 纯规范性 | 无取证步 |
| ScopeAndConstraints | 混合：约束=事实性，范围=规范性，假设=中间态 | 约束本地单层源压缩验证一步 |
| SuccessCriteria | 混合，轴心=规范性目标的可检验化转换 | 新增可检验化独立步 |
| DesignSolution | 混合，轴心=创造性生成 × 代码接地 | 新增现状勘察 + 方案发散双独立步 |
| **TaskBreakdown** | **混合，成分又换**：转换保真=受约束变换（设计包是唯一真源，**创作已在上游消费完**）；锚点核验=事实性（本仓代码事实，本地单层源）；阶段断点/粒度=规范性；假设=中间态 | **无发散步**（对象已存在，发散=逼编造伪候选）；新增**清点基线步**（前五个节点都不需要——它们的输入是陈述集，本节点的输入是要被**变换**的结构化对象，变换失真须先立基线才可判） |

与 DesignSolution 的镜像关系：plan:1 的主敌是「无中生有时的固化与凭空」，plan:2 的主敌是「**从有到有时**的失真与虚构」——

- **保真转换 → 转换失真（drift）**：长链转换中逐步偏离拍板内容（§4 Agent Drift：semantic drift 是 step-by-step agent 的主失效；防御 = goal anchoring + 执行前锁定 what-will-be-done）。设计包字段⑧ H9 执行单元划分已预选切片方案，本节点只做精化/排序/核验——**重切片 = 越权重设计**。防御 = 清点基线独立步 + 追溯锚传导。
- **执行接地 → 执行者视角虚构**：plan 的消费者是**零上下文执行者**（executing-plans：assume zero context），步骤引用不存在的文件/symbol/测试接缝/命令，执行者要么卡住要么把幻觉当事实继续（§4 hallucination amplification：planner 编造 → executor 消费为事实，沿链放大）。防御 = 锚点核验独立步 + 出处强制。

### 1.3 失效模式分析

| # | 失效模式 | 外部出处（§4） |
|---|---|---|
| T1 | 转换失真：步骤与拍板设计包脱节——镀金新增/要素丢失/装配二次创作 | Agent Drift（semantic drift + goal anchoring 防御）；OpenSpec/ADR「执行前锁定」 |
| T2 | 切分轴向错：横向按层切（先全部 schema 再全部逻辑再全部测试）→ 单元不可独立验证交付 | Vertical slicing 文献；INVEST（Independent + Testable） |
| T3 | 粒度失控：过粗（执行者须再设计 = 设计责任泄漏到 execute）/ 过细（机械噪声烧 token） | writing-plans Task Right-Sizing；CMU granularity calibration |
| T4 | 依赖顺序违反：被依赖者排后 / TDD 序倒置（先实现后测试） | 分解研究拓扑序约束（preconditions hold）；TDD bite-sized cycle |
| T5 | 接地失真：步骤引用不存在的文件/symbol/测试接缝/命令 | hallucination amplification；CMU「planning failures cascade without structural understanding」 |
| T6 | placeholder 空步骤：「加适当错误处理」「写上述的测试」式无内容步骤 | writing-plans No Placeholders（plan failures 清单） |
| T7 | 验证承接缺失：步骤无验证方法 → execute:0「逐条核」与 TEST_PASS 无可判 | specification by example；executing-plans「run verifications as specified」 |
| T8 | 复合/去上下文不可移植步骤（零上下文执行者做不了） | INCOSE atomic（沿用）；writing-plans zero-context engineer |
| T9 | 模型越权拍板阶段断点/粒度（规范裁决被代答） | 四桶分工（认不认归用户） |

**步数推导**（§3.8 #4，按失效模式族）：保真族（T1）→ 子1；切分族（T2+T3+T4，同族=单元结构决策）→ 子2；接地族（T5+T6，同族=本地单层源事实核验）→ 子3；形式族（T7+T8）→ 子4；认可族（T9）→ 子5。**5 族 = 5 步**。T7 并入子4 的理由：验证方法是步骤的**形式**属性（specification by example 即陈述格式），其内容真实性已被子3 覆盖（测试接缝/命令可运行性），judge 在子4 一步可判「五字段齐备+与子2/子3 一致」。步数 5 与 GoalsAndValue/ScopeAndConstraints/SuccessCriteria 相同纯属巧合——各自按族独立推导。

## 2. 设计：5 步

```
子1 设计包清点与追溯基线 → 子2 任务切分与依赖排序 → 子3 锚点核验与假设标注 → 子4 归一化执行步骤 → 子5 读回确认与 plan.md 装配
```

judge 调用 4 次（子5 gate=None）。

### 子1 设计包清点与追溯基线（kind=tool）

- **ref**：`Read(design.md / understand.md) / Bash(grep evidence 设计包 trace)`
- **purpose**：从拍板 design.md + evidence 里 minor_stage=DesignSolution 的子5/子6 trace **无损提取**三张清单——①**原子改动要素清单**（file→function→改动类型：改/增/删，逐条赋**要素 ID** E1/E2/...，每条附出处：design.md 行号或 evidence 指针）；②验收包清单（逐条 SuccessCriteria 附 ID）；③假设清单（含置信度×影响，原样转录）。**只提取不创作**——本步是全节点保真判定的基线：检出设计包没有的要素 = 二次创作信号，显式列「新增候选」待子5 用户裁决（禁静默混入）；发现设计包内部矛盾 = 合法退回信号（回 plan:1，同 SuccessCriteria 子2「不可检验=合法退回」机制）。**judge 输入面要求**（§3.5 #7）：design.md 文件 judge 读不到——要素原文须引用进 trace 正文，judge 从 evidence 判。
- **input**：`designs/<主题>-design.md + evidence(DesignSolution 子5/子6 trace)`
- **record**：True；**fence_allow**：`("Bash",)`（grep evidence jsonl；Read 在常驻集）
- **gate**：trace 存在；形式要件（三清单齐备；要素 ID 连续编号；每条附出处；新增候选/矛盾显式标注或显式「无」）；质量判据黑盒（要素无出处 = 编造判 block；静默新增设计包没有的要素 = 二次创作判 block；大段改写要素措辞致语义偏移 = 失真判 block）。

### 子2 任务切分与依赖排序（kind=skill）

- **ref**：`superpowers:writing-plans(粒度与切片原则真源) / codegraph callers/impact(依赖取证) / 推理(拓扑排序)`
- **purpose**：将要素清单切成执行单元并组织成阶段——①**切分**（writing-plans Task Right-Sizing：单元 = 自带完整测试周期且值得 reviewer 门禁的最小单位，setup/文档折叠进需要它的单元；**纵向切片优先**——每单元独立可测可交付，横向按层切须显式辩护；H9 预算：每单元 ≤3 文件 ≤200 行，超预算继续拆；设计包字段⑧已预选切片的，精化不重做）；②**排序**（codegraph callers 建依赖 DAG，拓扑排序——被依赖者先行；TDD 序内嵌：每单元内 failing test 先行）；③**阶段划分**（阶段 = 可整体验证 + 可整体提交 + 可回滚的单元组，每阶段附断点验证方法）。**双结论制**：②「单阶段不可拆」合法（小改动 H9 内一次可完），但须论证——防逼编造伪阶段凑数（同 DesignSolution 子2 机制）。只提案不拍板——断点位置是用户风险偏好（子5 裁决）。
- **input**：`step1.element_baseline`
- **record**：True；**fence_allow**：`("Bash",)`（codegraph CLI）
- **gate**：trace 存在；形式要件（每单元附 H9 预算估计 + 承接要素 ID + 依赖出处；DAG 排序留痕；阶段断点验证方法；②论证留痕或显式多阶段）；质量判据黑盒（横向按层切无显式辩护判 block；排序违反依赖 = 被依赖者排后判 block；单元超 H9 预算无继续拆判 block；要素 ID 覆盖有漏 = 丢要素判 block；②无论证 = 偷懒判 block）。

### 子3 锚点核验与假设标注（kind=tool）

- **ref**：`codegraph / Bash(test -f / pytest --collect-only / 命令干跑) / Read`
- **purpose**：逐单元核验锚点真实性（本地单层源，沿用 ScopeAndConstraints 压缩原则，只标注不裁决）：①目标文件/symbol 存在（改动清单每个 file:line 核实——新增文件查目录与命名冲突）；②**测试接缝存在**（每单元的验证测试有可挂位置：测试目录/fixture/可 import 的被测对象，`pytest --collect-only` 类手段留痕）；③**验证命令可运行**（pytest 路径/脚本/命令存在且参数合法）；④**No Placeholders 检出**（writing-plans plan failures 清单：「加适当错误处理」「处理边界情况」「写上述的测试」「类似任务 N」——检出则补具体内容或回子2 重切）。三态标注：**已验证（附出处）/ 假设（置信度×错误时影响）/ 证伪（回子2 重切，附理由）**。
- **input**：`step2.task_units + step1.element_baseline`
- **record**：True；**fence_allow**：`("Bash",)`
- **gate**：trace 存在；形式要件（每单元四类核验留痕；三态逐单元标注；出处/置信度×影响/理由齐备）；质量判据黑盒（声称存在无出处 = 编造判 block；全单元无差别「已验证」= 没真核验判 block；placeholder 模式残留判 block；假设项缺置信度或影响判 block）。

### 子4 归一化执行步骤（kind=skill）

- **ref**：`define-problem(归一化职能第七次复用) / superpowers:writing-plans(Task Structure 形式真源)`
- **purpose**：对每任务单元产出归一化执行步骤——①原子（单句 ≤1 个独立动作，bite-sized：写失败测试/跑验证它失败/最小实现/跑验证通过/提交）；②**去上下文**（零上下文执行者可做：步骤自包含，禁「同上」「类似任务 N」，跨任务接口走 Consumes/Produces 签名显式传递）；③携带**执行包五字段**（消费契约锚点，§0 表）：改动点（file:line→改动类型）/ 前置接口（Consumes+Produces 精确签名）/ 验证方法（failing test 名+命令+期望输出，或命令+期望退出码——**可执行验证优先**，specification by example 接 TDD；「人工看一下」式须显式辩护）/ 验收包映射（承接哪条 SuccessCriteria ID）/ 追溯锚（承接哪个要素 ID）；④假设传导（子3 假设项原样携带，不丢不淡化）。放不进一句 = 未定义完。
- **input**：`step3.verified_units`
- **record**：True；**fence_allow**：无
- **gate**：trace 存在；形式要件（每步骤 ≤1 句且自包含；五字段齐备；验收包与要素双向覆盖无漏）；质量判据黑盒（字段与子2/子3 已定内容不一致 = 丢失/篡改/新增判 block；复合句判 block；验证方法不可执行且无辩护判 block；验收包映射漏项判 block）。

### 子5 读回确认与 plan.md 装配（kind=skill）

- **ref**：`AskUserQuestion / Write(plan.md)`
- **purpose**：带证据读回：呈现阶段划分+任务序列+五字段摘要+假设清单+新增候选（子1 检出若有）+不确定性；**用户两裁决**：①**阶段/粒度拍板**（本节点唯一规范裁决点——断点位置与粒度偏好是用户风险偏好，含要求合并/拆细/重排阶段的合法权利）；②**假设接受**（风险承担，同构前五个节点）；拍板后**装配 plan.md**（内容 = 子4 归一化执行步骤 + 子5 裁决记录的直接装配，**禁二次创作**——同 understand.md/design.md 装配原则）；写 trace 记裁决原话 → STEP_DONE。
- **input**：`step4.execution_steps`
- **record**：True；**fence_allow**：无
- **gate**：None（交互步，trace 存在即过）

### 末子步骤过后：hold_for_gate 扣留（用户决议 2026-07-28）

子5 过门控后**无条件扣留**（state.held_for_gate），唯一出口 `/dl gate`——与 understand:3/4、plan:1 同款**隔离测试**语义：plan 第二个编排节点，跑完被围栏围住，用户验证编排本身没问题再放行。放行后模型输出 `### PHASE_DONE: plan` 撞 plan->execute 大闸门（第二次 `/dl gate`）——**门栏放行 ≠ 阶段推进**，两道门语义独立（同 understand:4）。

**机制路径说明**：本节点是 `advance="phase"` 的 hold 节点，与 understand:4 **完全同构**——扣留/放行不推进/PHASE_DONE fall-through（`phase_done_channel_open` 单源判据）已被 understand:4 的 pinning 测试覆盖，**无新机制路径**（不同于 understand:4 当时的新路径风险）。plan.md 在子5 内装配完成（hold 前产物已落地），无 understand:4 的「放行后写产物」窗口依赖——**实施期兑现**：注入第三态文案按 Node `artifact_on_release` 字段分支（本节点=False：放行后只提示 PHASE_DONE，不再提示「汇总写产物」，见头部 2026-07-28 修订行）。

## 3. 门控设计要点（§3.5 对齐）

- **双结论制**（#3）：子2 接受「单阶段不可拆」为合法结论（须论证 H9 内一次可完）——否则逼模型编造伪阶段凑数。区分「诚实单阶段」vs「懒得切分」的判据是论证留痕。
- **Goodhart 分层**（#2）：形式要件（三清单/要素 ID/H9 预算/四类核验/五字段/出处形式）披露进 purpose；质量判据（非二次创作/非横向惯性切/非编造锚点/非 placeholder/非越权拍板）只留 gate 黑盒。
- **四桶分工**：清点/切分/核验/归一化 = 模型（写什么）；trace 落库 = append-trace 脚本（怎么写）；结构完整性 = judge（过不过）；阶段断点/粒度拍板/假设接受 = 用户（认不认）。
- **judge 不判「怎么切更好」**——只判「覆盖无漏 + 出处真实 + 只提案未拍板 + 字段传导」。切分优劣的真值源只有用户（子5）。
- **判据合法获取路径**（#7）：子1-3 的出处要求有 fence_allow=("Bash",) + 常驻集 codegraph/Read——每条判据要求的佐证都存在低成本合法获取路径，不逼编造。
- **消费契约倒推**（锚点法第四次使用）：执行包五字段倒推自 execute:0/executing-plans/review:0 三方需求（§0 表）——缺任一字段，下游就得临时找补（缺验证方法 execute 无可判；缺前置接口执行者卡在命名猜测；缺验收包映射 review 无法判定；缺追溯锚「plan 与设计包一致」无从核）。
- **plan.md 的产物强制路径**（与 plan:1 三层兜底**不同**）：plan.md 是**静态路径**，ARTIFACT_EXISTS 机械门可用——产物强制 = ①子5 purpose 写死装配义务 + S13 参与围栏；②子4 judge 已验五字段（装配无新增内容可错）；③**gate_mech=ARTIFACT_EXISTS 保留**（机械兜底，零 judge 成本）。plan:1 弃用机械门是因为 design.md 动态文件名含 `/` 机械门不支持，该约束在此不存在。
- **节点级 gate_rubric 置 None**（讨论稿订正，understand:4 先例）：原节点级 rubric ①②③④的语义全部下沉到逐步 gate（①②③ → 子2/子3/子4 判据；④一致性 → 子1 基线 + 子4 传导判据 + 子5 禁二次创作）。大闸门只跑 ARTIFACT_EXISTS 机械门——语义在大闸门重跑 = 重复烧 judge（understand:4 已立此例：gate_rubric=None + artifact 保留）。
- **judge 输入面**（#11）：子1/子4 gate 的佐证走 evidence 路径——design.md 文件 judge 读不到，要素原文必须引用进子1 trace 正文；rubric 文本含 `evidence/` 关键词触发 `rubric_needs_evidence`，judge 才读得到 DesignSolution 设计包与子1 基线全文（plan:1 §3 实现注同款教训）。

## 4. 外部实证出处（2026-07-28 Tavily 取证留痕）

- **Agent Drift**（Rath 2026 arXiv 三型 drift 分类——semantic/coordination/behavioral；Shahnovsky & Dror 2026 POMDP 框架——「step-by-step agents are particularly exposed to drift due to weak long-horizon planning, while plan-ahead agents preserve goal alignment」；Vinay 2025 系统级失效分类——multi-step reasoning drift）：长链转换逐步偏离原意图是主失效；防御 = **goal anchoring**（每步重述原目标）+ **执行前锁定 what-will-be-done**（OpenSpec/ADR 模式）。——子1 清点基线（锁定源）+ 子4 追溯锚（每步骤锚回要素 ID = goal anchoring 机械化）的直接依据。
- **Vertical slicing / INVEST**（Bill Wake INVEST——Independent + Testable 为好单元；agile 文献共识：horizontal slices「provide intermediate work that does not directly provide stakeholder value」，按层切的单元不可独立验证交付）：——子2「纵向切片优先、横向须显式辩护」的直接依据。
- **writing-plans skill**（superpowers plugin，项目本地形式真源）：Task Right-Sizing（「the smallest unit that carries its own test cycle and is worth a fresh reviewer's gate」）；Bite-sized steps（写失败测试→跑→最小实现→跑→提交）；**No Placeholders**（plan failures 清单：TBD/「appropriate error handling」/「write tests for the above」/「similar to Task N」）；zero-context engineer 假设；Self-Review 三项（spec coverage/placeholder scan/type consistency）。——子2 粒度判据、子3 placeholder 检出清单、子4 步骤形式（Task Structure 五块）的直接依据。
- **分解拓扑序约束**（Preprints 202602.1841——consistency constraint 保证「the dependencies between subtasks satisfy the topological order」；arXiv 2510.07772 STRIPS 形式化——plan 合法 = 每动作 preconditions 在执行点成立）：——子2 依赖 DAG 拓扑排序 + judge「被依赖者排后判 block」的直接依据。
- **LLM 软件工程分解实证**（CMU-CS-25-132）：「granularity calibration」是分解关键挑战；「planning failures often cascade without effective structural understanding of the problem space」；arXiv 2508.13143 三层失效分类（planner/code generator/executor），planning errors 居首。——子3 锚点核验（structural understanding 接地）+ 本节点独立存在的直接依据。
- **coding agents on GitHub 实证**（emergentmind 综述）：「Plans are often supplied as expert-curated graphs to prevent LLM-induced drift and reduce per-step action space」；角色分离 planning/editing/verification + 严格序（acyclic transitions）。——四桶分工（模型/judge/用户分权）与 DAG 无环排序的直接依据。
- **本地单层源压缩原则**（沿用 `scope-and-constraints-substeps-design.md`）：锚点核验=本仓内部事实，codegraph/Bash/Read 单层可验，无「五层源过程质量」可判——子3 一步压缩、无独立质检裁决步（第四次否决同构双步方案）。

## 5. 否决的替代方案（对抗性审视留痕）

1. **6 步版（加发散步，照抄 plan:1「发散≥3 候选」）**——否（第一性原理）：plan:1 发散是因为对象不存在须从「无」生「多」（fixation 防御）；本节点输入对象**已存在**且已拍板，切片方案在设计包字段⑧已预选——再发散 = 越权重设计 + 逼编造伪候选凑数。关键不对称（§1.2）即此。
2. **4 步版（子1 清点并入子2 切分）**——否：提取（无损）与变换（重构）异族，judge 分步可判（「清点漏要素」vs「排序违反依赖」）；且没有要素 ID 基线，「plan 与设计包一致」在子4/子5/大闸门**根本无可判**——合并 = 拆掉保真关口的测量仪器（同构 DesignSolution 子1 勘察先立事实基线）。
3. **6 步版（子3 拆取证+质检裁决双步，照抄 ProblemContext）**——否。本地单层源没有「五层源过程质量」可判，独立质检步判无可判 = 纯烧 judge（ScopeAndConstraints/SuccessCriteria/DesignSolution 已三次否决同构方案）。
4. **节点级 gate_rubric 保留语义审据（讨论稿初案：「大闸门还要用，不能置 None」）**——否（2026-07-28 查 understand:4 先例后订正）：阶段出口编排节点的大闸门只跑机械门，语义一致性由逐步门控承担（understand:4 gate_rubric=None + artifact=understand.md 保留即此例）；大闸门重跑语义 = 重复烧 judge。
5. **gate_mech 也置 NONE（照抄 plan:1）**——否。plan:1 弃机械门是因为 design.md 动态文件名含 `/` 机械门不支持；plan.md 静态路径无此约束，ARTIFACT_EXISTS 零成本兜底「子5 无 judge、plan.md 未落地」风险。
6. **hold_for_gate 不加**——否（2026-07-28 用户决议加）：与 understand:3/4、plan:1 同款隔离测试语义；机制路径与 understand:4 完全同构（advance="phase" hold），无新机制风险。代价（多一次 /dl gate）已知情接受。
7. **通用 WBS 形态（阶段-里程碑-交付物，不锚代码）**——否（编程工作流定位，DesignSolution 元约束沿用）：通用形态产不出 file:line+验证命令，判不出「步骤引用不存在接缝」；消费方 execute:0 的 rubric「对照 plan 步骤逐条核」需要代码级核对基准。

## 6. 实施 checklist（改编排必过，症状 M + §3.7）

1. `dl_flow_nodes.py`：改 `plan:2` Node——label「生成执行计划」→「拆解任务与阶段」；skill="superpowers:using-superpowers"→None（编排节点 skill 走 Step ref，同 plan:1）；artifact="plan.md" 保留；gate_mech=ARTIFACT_EXISTS 保留；**gate_rubric→None**（语义下沉逐步 gate，§3）；advance="phase" 不变；加 `sub_steps`（5 个 Step 含 short/purpose/input/record/gate/fence_allow/selfcheck）+ `_TB_STEP1_FORM_REQUIREMENTS` 等形式要件常量（单源：purpose 模型侧与 gate judge 侧都引用）；`minor_key="TaskBreakdown"`；`hold_for_gate=True`。minor_key_map/subphase_labels 自动收新 minor_key。**存量工作流迁移**：在 plan:2 的旧 state 无 sub_step 字段 → 进注入/门控路径触发报错暴露（no silent fallback 符合预期）——单人维护可接受，迁移 = `/dl jump plan` 重置或手改 state.json
2. `hooks/workflow_phase.py` `_format_injection`：**预期无需改**（子阶段标签/子步骤清单/minor_key 映射全部从 engine 推导）——冒烟验证注入含「子阶段: 拆解任务与阶段 [2/2]」+ 5 步骨架链
3. `scripts/workflow/phase-rules.md`：plan 段加 plan:2 的 GENERATED 标记段（launcher 渲染自动同步 5 步 purpose）+ 静态强制语义（写 evidence 是 STEP_DONE 前置/输完即 end_turn/子5 装配 plan.md 义务/门栏扣留等 /dl gate + 放行后 PHASE_DONE 撞大闸门）
4. `skills/workflow-creation/SKILL.md` + `references/node-design.md`：§0 摘要块更新——门栏五处（understand:2/3/4 + plan:1/2）+ plan:2 5 步摘要段（含关键不对称第六种 + advance="phase" hold 同构 understand:4 说明）；§3.8 关键不对称表加第六行（TaskBreakdown=保真转换 × 执行接地）；「改 engine Step.purpose 实质内容后须手工同步摘要块」纪律适用
5. `tests/test_dl_flow_engine.py`：新 Step 定义测例（5 步数/各 gate 含关键判据/子1-3 fence_allow=("Bash",)/子5 gate=None/selfcheck 无质量判据泄漏钉死/hold_for_gate=True/minor_key=TaskBreakdown/gate_rubric=None/gate_mech=ARTIFACT_EXISTS 保留）；**fixture 迁移**——原「无编排节点」占位的 plan:2 全量换编排版（症状 M #7：逐处 grep 别漏）；排他性/唯一性断言全量遍历 `_NODES`；advance="phase" hold 路径数据测例（机制已被 understand:4 pin 过，本节点只需 fixture 级覆盖）；label 改名的全仓 grep（「生成执行计划」在 hooks/tests/docs/phase-rules 的引用）
6. 冒烟：真实 state 直调 `_format_injection` + `render-phase-rules`（§3 #10 法，不开会话）；真实 TTY 跑一轮验证——子1 三清单+要素 ID 留痕、子2 DAG 排序+阶段提案、子3 锚点出处、子5 plan.md 装配落地、门栏扣留 + /dl gate 放行 + PHASE_DONE 撞 plan->execute 大闸门、推进 execute:0 后注入正确显示

## 7. 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| 1 | 模型二次创作（步骤镀金/丢要素/装配时改写） | 子1 要素 ID 基线 + 子1/子4 gate 传导判据（新增判 block/不一致判 block）+ 子5 装配禁二次创作 + Agent Drift goal anchoring 机制化（追溯锚） |
| 2 | 重切片越权（无视设计包字段⑧重发明切片方案） | 子2 purpose 写死「已预选切片的精化不重做」；子2 gate 要素 ID 覆盖判据 |
| 3 | 横向切片惯性（按层切最顺手：先全部 schema 再全部逻辑） | 子2 纵向切片优先 + 横向须显式辩护（gate 黑盒）+ INVEST 判据进 purpose |
| 4 | 锚点编造（不存在的文件/symbol/测试命令——LLM 最强编造区） | 子3 出处强制 + fence_allow 合法获取路径 + gate 黑盒「无差别已验证判 block」 |
| 5 | placeholder 空步骤漏检（「加适当错误处理」混进 plan.md） | 子3 No Placeholders 检出清单写死进 purpose + gate 黑盒残留判 block |
| 6 | 验证方法缺位（execute:0 无可判 = 保真关口形同虚设） | 子4 五字段强制 + 可执行验证优先（「人工看一下」须辩护）+ 消费契约倒推锚点 |
| 7 | design.md judge 读不到 → 子1 一致性判据失效 | 要素原文引用进 trace 正文 + rubric 含 `evidence/` 关键词触发 rubric_needs_evidence（plan:1 §3 实现注同款） |
| 8 | 子5 无 judge，plan.md 缺漏无人拦 | 子4 judge 已验五字段（装配无新增内容可错）+ ARTIFACT_EXISTS 机械门（静态路径可用，不同于 plan:1）+ 用户读回确认本身即质量门 |
| 9 | 弱遵从模型跳过清点直接写 plan（症状 P 抢答模式重演） | S15 前置参与围栏按 fence_allow 白名单物理拦截（子1 窗口只放行编排工具+Bash）；S13 兜底纯 text 抢答 |
| 10 | 「单阶段不可拆」被滥用逃切分（双结论②被回避） | 子2 论证留痕是合法佐证路径；gate 黑盒「②无论证判 block」；用户子5 拍板兜底 |
