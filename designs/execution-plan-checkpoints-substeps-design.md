# plan:4「制定执行计划和检查点」子步骤编排设计（ExecutionPlanCheckpoints）

> 状态：**已实现（v2.21，2026-07-28）**——§6 checklist 全项落地：plan:4 Node（5 步）+ plan:3 advance phase→sub + phase-rules plan:4 段与 execute 首步指令 + skill 摘要块（关键不对称第八种）+ 415 tests 全绿 + render-phase-rules 冒烟通过
> 修订（2026-07-28，实施落地）：§3「gate_mech 置 None」落地为 **`gate_mech=GateMech.NONE`**（既有枚举值，engine:403 显式处理，understand:1 等 4 节点先例）——设计语义不变（无机械门），非 Python None
> 修订（2026-07-28，用户决议）：**plan.md 规范位置 = 主仓 `.claude/plans/<name>.md`**（与 evidence 同级同语义——worktree 归档删除时分支上产物一起丢，主仓 `.claude/` 才存活；可手动 git add 提交留存）。配套：S11 白名单加 `.claude/plans/` 路径规则（限 plan 阶段写，`phase_write_path_ok`）；注入加「产物路径」行（`workflow_phase.py`，artifact="plan.md" 节点触发，同 evidence 载荷路径模式）；phase-rules 三处装配义务 + execute 首步指令同步。execute:0 rubric「对照 plan.md」语义不变（读主仓路径）。同构遗留已解决（同日第二轮决议）：understand.md/review.md/evolution.md 同法迁移——`.claude/understands|reviews|evolutions/<name>.md`，S11 各限本阶段写（`_PHASE_ARTIFACT_DIRS` 单源映射），注入产物路径行泛化到四产物；evolution 例外：既有语义放行整个 .claude/（skills 更新职责），不为本迁移收窄
> 确认史（2026-07-28 用户三连决议）：①会话确认 **5 步**结构（四源清点→调度与检查点提案→锚点核验→归一化→读回装配）；②**execute 阶段愿景**钉死消费契约——execute = AI 按 plan 产物执行**不再自行分析** + **多 subagent 拆任务并行执行**（orchestrator-worker），由此本节点产物从「检查点节」扩为「调度方案 + 检查点」双对象（§0 表、§2 子2）；③**不加新产物文档**——plan.md 三节自足（执行步骤/能力节/执行计划与检查点节）+ understand.md（目标锚）+ design.md（偏离仲裁）+ evidence.jsonl（证据链）已闭合；executor-brief 式汇总文档否决（§5 #4）
> 父文档：`node-step-orchestration-design.md`（子步骤编排机制）、`capability-tool-selection-substeps-design.md`（最近范式 + plan:3 产物即本节点输入）、`task-breakdown-substeps-design.md`（保真转换镜像 + 执行包五字段）、`success-criteria-substeps-design.md`（验收包六字段 + 时机标注——本节点是其 triggered 时机的落地处）、`workflow-creation` SKILL.md §3.5（rubric 方法论）/ §3.8（拆步方法论）
> 外部取证：本文 §4（Tavily 检索，2026-07-28，设计期调研——用户明示允许；与运行期 understand:1 子3「禁 tavily/WebSearch」约束无关）

## 0. 背景

plan 阶段当前三子阶段：plan:1 设计解决方案（产物 design.md）→ plan:2 拆解任务与阶段（产物 plan.md 执行步骤节）→ plan:3 选择能力与工具（产物 plan.md 能力节）。**plan:4「制定执行计划和检查点」是 plan 末子阶段**：任务 DAG、能力绑定都已拍板，但**运行时控制结构**未定——execute 阶段何时停、停时验什么、失败后去哪、哪些任务可并行派发。plan:1/2/3 的产物全是**静态内容**（改动清单/执行步骤/能力映射），本节点是第一个设计**控制流**的节点。

**execute 愿景（2026-07-28 用户决议，本设计的消费契约输入）**：execute = orchestrator（主会话编排+验收）+ worker（多 subagent 纯执行，**不再自行分析**）。这带来两个硬约束：
- **executor 是无判断执行者** → 任何需要"执行时想"的东西都是 plan 漏项：失败路由必须预定义、验证判据必须零判断词（"检查一下是否合理"式判据 = 检查点虚设）、goal anchoring 职责全在 orchestrator 检查点（worker 只见局部，drift 更快）。
- **多 worker 并行** → 并行分组与文件互斥面必须在 plan 期规划（executor 不分析，分组不能留给执行期）；worker 返回物必须有预定义验收契约（返回"完成了"三个字 = fabricated success report 的 subagent 版）。

输入 = 四源拍板终态：`design.md`（设计包八字段）+ `plan.md`（执行包五字段/阶段划分 + 能力包五字段）+ `understand.md`（验收包六字段，含 triggered/continuous 时机标注）+ evidence 里 plan:1/2/3 的 trace（裁决原话）。**本节点是首个多源聚合节点**——前七个节点都只吃单一上游对象。
输出 = plan.md **追加「执行计划与检查点」节**（子5 拍板后装配），plan 产物体系自此闭合，execute:0 单文件直读。

**消费契约锚点**（锚点法第六次使用）——执行计划包字段倒推自下游消费方：

| 下游 | 其 rubric/职责 | 倒推出的字段 |
|---|---|---|
| execute:0 orchestrator（愿景，待设计） | 多 worker 并行派发 + 返回物验收 | 调度节：①并行分组 ②文件互斥面 ③worker 任务包映射 ④返回契约 |
| execute:0 gate rubric | 「对照 plan 步骤逐条核，偏离需有理由」 | 检查点位置锚 + 追溯锚（偏离判定有据） |
| understand:4 验收包「时机=triggered」字段 | 触发式验证的具体落点此前未定义 | 检查点位置锚（triggered 时机在此落地——上游字段消费闭合） |
| review:0 | 「判定 solved/partial/not，附 file:line 证据」 | 检查点通过判据 + 返回契约（检查点记录 = review 证据源，understand:4 子3「证据形式锚定 review:0」先例沿用） |
| 用户（密度裁决） | 风险承担 = 规范裁决 | 检查点类型（自动继续 vs 用户暂停）+ 冻结策略 |

**产物边界**（不造什么）：任务级验证方法已在 plan:2 执行包五字段，本节点**不重造**——检查点是阶段边界/风险点上的控制结构，不是任务级验证的复制；并行冲突的 git 合并机制、orchestrator 循环、worker 隔离（worktree）是 execute 阶段机制设计项，本节点只产**方案数据**不产**运行机制**。

## 1. 第一性原理

### 1.1 终态三属性（同构前七个节点）

| 属性 | 在本子阶段的含义 | 承担步骤 |
|---|---|---|
| 内容正确 | 调度/检查点方案保真于四源输入（无镀金无丢失）；判据可执行真实（dry-run 实测）；并行组互斥真实（文件交集机械核验）；假设显式化 | 子1-3 |
| 形式可移植 | 归一化执行计划包携带调度四字段+检查点六字段，execute:0 orchestrator 可直接消费；装配为 plan.md「执行计划与检查点」节 | 子4-5 |
| 用户认可 | 密度与类型拍板（风险承担）、假设接受、plan.md 冻结策略 = 规范裁决，归用户 | 子5 |

### 1.2 关键不对称（第八种）：时序控制 × 风险配平

| 子阶段 | 命题性质 | 编排后果 |
|---|---|---|
| ProblemContext | 纯事实性 | 五层外部源取证 + 质检裁决双步 |
| GoalsAndValue | 纯规范性 | 无取证步 |
| ScopeAndConstraints | 混合：约束=事实性，范围=规范性，假设=中间态 | 约束本地单层源压缩验证一步 |
| SuccessCriteria | 混合，轴心=规范性目标的可检验化转换 | 新增可检验化独立步 |
| DesignSolution | 混合，轴心=创造性生成 × 代码接地 | 新增现状勘察 + 方案发散双独立步 |
| TaskBreakdown | 混合，轴心=保真转换 × 执行接地 | 无发散步；新增清点基线 + 锚点核验步 |
| CapabilityToolSelection | 混合，轴心=有限枚举 × 配置接地 | 新增注册表盘点 + 匹配选型步 |
| **ExecutionPlanCheckpoints** | **混合，成分再换**：「检查点判据承接验收包」=事实性（已拍板对象，可核验追溯）；「布点位置」=可推导（任务 DAG/阶段边界/可逆性约束）；「密度与类型」=**规范性风险裁决**（真值源只有用户——过密自动化失效，过疏复利失控，取舍点是用户的风险胃口）；假设=中间态 | **无发散步**（布点受 DAG/阶段边界约束，非生成空间——发散 = 逼编造伪检查点凑数，与 plan:2/3 同理）；**无独立质检裁决步**（本地单层源第六次压缩）；新增**四源清点基线步**（首个多源聚合节点——聚合失真族防御须先立基线）+ **调度与检查点提案步**（本节点存在的理由：把任务 DAG 转成运行时控制结构，独立 gate） |

与前序节点的关系：plan:1 主敌是「无中生有」；plan:2 主敌是「从有到有」的失真；plan:3 主敌是「从有选有」的错配；**plan:4 主敌是「从静到动」的失控**——前七个节点设计对象（内容），本节点设计**控制**（何时停/验什么/失败后去哪/谁可并行）。失效不发生在对象本身，发生在**执行时序上**：误差沿调用链复利（§4 实证 85%/步 × 8 步 = 27%）、模型把自己先前错误当正确模式续建（self-conditioning）、worker 返回物无人验收即合并。

### 1.3 失效模式分析

| # | 失效模式 | 外部出处（§4） |
|---|---|---|
| E1 | 检查点虚设：判据非客观可执行，executor/自我宣称成功 | arXiv 2605.30777（547 真实 coding agent 失效：fabricated success reports，遇失败不 halt 反谎报）；reward hacking（删 failing test 让 CI "过"） |
| E2 | 误差复利无截断：无检查点的长链执行成功率乘法坍塌 | Lusser's Law（97%³=91%，85%⁸=27%）；检查点位置 = accuracy architecture 决策 |
| E3 | 自我条件化/drift：模型读自己先前输出当正确模式，错误加速；worker 见局部 drift 更快 | "The Illusion of Diminishing Returns"（self-conditioning 非线性加速）；Agent Drift 2026（goal anchoring = 每 N 步重述原目标） |
| E4 | 密度失配：过密 = 自动化意义丧失 + 用户疲劳；过疏 = 复利失控 | MindStudio HITL 研究（checkpoint 设计核心是密度权衡）；over-autonomy 分析 |
| E5 | 不可逆操作无人工门：force-push/删数据/外发动作无审批 | over-autonomy 失效研究（approval gates on irreversible actions；autonomy 随**可逆性**缩放） |
| E6 | 失败处置缺失：检查点红了之后去哪没定义 → 临场即兴（executor 无判断能力时 = 死锁或乱撞） | TrajAudit（arXiv 2605.26563）：失败定位难因无预定义恢复结构 |
| E7 | 多源聚合失真：四源输入聚合时 ID 漂移/漏项/语义裂缝 | MetaGPT（ICLR 2024）：结构化 handoff 防级联幻觉——非结构化聚合 = cascading hallucinations 温床 |
| E8 | 并行冲突：多 worker 同改文件/隐式依赖交叉 → 合并爆炸或互相覆盖 | "Towards a Science of Scaling Agent Systems"（180 实验：去中心化错误放大 17.2× vs 中心化编排 4.4×） |
| E9 | 返回物无验收：worker 自我宣称完成即合并，错误注入主干 | Inspector pattern（ICML 2025：对抗性验收 agent 截获 96.4% 下游传播错误） |
| E10 | 模型越权拍板密度/类型，或代答假设（规范裁决被代答） | 四桶分工（认不认归用户） |

**步数推导**（§3.8 #4，按失效模式族）：聚合失真族（E7）→ 子1；控制结构提案族（E2/E3/E4/E5 布点面 + E1 判据设计面 + E6 路由设计面 + E8 分组成案面 + E9 契约设计面——同一对象「运行时控制结构」的属性填充）→ 子2；核验族（E1 判据可执行性 + E8 交集核验 + E9 契约可执行性——本地单层源事实核验）→ 子3；形式族（复合/去上下文不可移植）→ 子4；认可族（E10）→ 子5。**5 族 = 5 步**。E1/E8/E9 跨族说明：方案面在子2（设计判据/分组/契约），核验面在子3（实测命令可跑/交集实算/契约零判断词）——同构 plan:3 C1 的盘点面/核验面分工。步数 5 与 plan:2 相同非照抄——各自按族独立推导收敛同数。

**调度与检查点为什么不拆成两步**：检查点位置 = 并行组边界（强耦合，拆开产生步间循环依赖）；judge 一步可判「分组有据 + 检查点三属性齐备」（plan:2 子2 一步判切分+排序+分组先例）。

## 2. 设计：5 步

```
子1 四源清点与追溯基线 → 子2 调度与检查点方案提案 → 子3 锚点核验与假设标注 → 子4 归一化执行计划包 → 子5 读回确认与 plan.md 装配
```

judge 调用 4 次（子5 gate=None）。

### 子1 四源清点与追溯基线（kind=tool）

- **ref**：`Read(design.md / plan.md / understand.md) / Bash(grep evidence plan:1/2/3 trace)`
- **purpose**：从四源**无损提取**控制结构设计所需的全部输入清单——①任务 DAG 与阶段边界（plan.md 执行步骤节：任务 ID/依赖/阶段分组）；②能力绑定（plan.md 能力节：必先 skill/子代理策略）；③验收包（understand.md：六字段，**重点提取时机=triggered 项**——其落点即检查点候选）；④假设清单汇总（design.md + plan.md 能力节假设项）；⑤不可逆操作候选（执行步骤中含删改/外发/force 语义的改动点）。每条附**源出处 + 原文引用进 trace 正文**（judge 读不到三个文件——plan:1/2/3 子1 同款教训，第四次）。**只提取不创作**——检出四源没有的对象 = 二次创作信号，显式列「新增候选」待子5 用户裁决。
- **input**：`design.md + plan.md + understand.md + evidence(plan:1/2/3 末步 trace)`
- **record**：True；**fence_allow**：`("Bash",)`（grep evidence jsonl；Read 在常驻集）
- **gate**：trace 存在；形式要件（五类清单齐备；每条附源出处；原文引用进 trace 正文；triggered 验收项显式标注；新增候选显式标注或显式「无」）；质量判据黑盒（清单项无出处 = 编造判 block；四源之一缺失且无说明 = 漏源判 block；静默新增 = 二次创作判 block；大段改写致语义偏移 = 聚合失真判 block）。

### 子2 调度与检查点方案提案（kind=skill）

- **ref**：`推理(DAG 拓扑分层 + 控制结构设计) / Agent(条件红队)`；对齐源 `superpowers:writing-plans / executing-plans`（checkpoint 语义真源）
- **purpose**：把任务 DAG 转成运行时控制结构，双对象提案——
  **①调度方案**：DAG 拓扑分层得**并行分组**（同层无依赖任务可并行派发，executor 不分析故分组必须 plan 期定死）；每并行组标注**文件互斥面**（各 worker 改动文件清单，组内交集须为空——从执行包改动点字段直接计算）；**worker 任务包映射**（任务 ID → worker 派发单元，每单元自包含可零上下文执行——plan:2 子4 已保证单步去上下文，此处聚合成派发粒度）；**subagent 返回契约**（每 worker 必须返回的证据形式清单：测试输出/改动文件清单/file:line——orchestrator 验收依据，E9 防线）。
  **②检查点清单**：布点默认 = 并行组/阶段边界（E2 复利截断），任务级加密须辩护；每检查点三属性——**通过判据**（可执行零判断词：命令+退出码/断言，承接验收包 ID，禁「确认/检查/合理」类动词——E1 防线；不可逆操作前的检查点强制 **类型=用户暂停**，E5 硬条款）/**失败路由**（返工本组 / 回滚至上一检查点 / 升级用户——三选一预定义，executor 无判断能力故禁止「视情况」——E6 防线）/**类型**（自动继续 vs 用户暂停）；每检查点内嵌 **goal anchoring 重述句**（一句话重述原目标+当前位置，E3 防线）。
  **密度提案**：按**可逆性 × 爆炸半径**逐检查点给类型建议（autonomy 随可逆性缩放，§4），只提案不拍板（E10）。**双结论制**：「零用户检查点」是合法结论（全链可逆 + 判据全自动），但须按复利数学论证（给出逐步成功率估计与整体下界）——防逼编造用户暂停点凑数，也防默认零暂停逃避论证。
  条件红队（并行组数或检查点数超阈值时触发，独立上下文反驳分组与布点）。
- **input**：`step1.control_baseline`
- **record**：True；**fence_allow**：`("Agent",)`（条件红队，同 plan:1 子4/plan:3 子3）
- **gate**：trace 存在；形式要件（并行分组+互斥面+worker 映射+返回契约四件齐备；每检查点三属性齐备；goal anchoring 重述句逐检查点；不可逆操作检查点类型=用户暂停；密度论证或「零用户检查点」复利论证；红队留痕或条件未触发声明；提案-待裁决语义）；质量判据黑盒（判据含判断词 = 虚设判 block；失败路由缺/「视情况」= 即兴路由判 block；互斥面未从改动点计算 = 拍脑袋分组判 block；返回契约缺证据形式 = 无验收门判 block；拍板语气 = 越权判 block）。

### 子3 锚点核验与假设标注（kind=tool）

- **ref**：`Bash(判据命令 dry-run / 互斥面交集机械核验 / codegraph 锚点存在性)`
- **purpose**：逐对象核验（本地单层源，沿用 ScopeAndConstraints 压缩原则——第六次否决取证+质检双步，只标注不裁决）：①**判据可执行性**——每检查点通过判据的命令实际 dry-run（存在且可运行，不验结果对错）；②**互斥面机械核验**——并行组内各 worker 改动文件清单**集合交集实算**（交集非空 = 分组证伪，回子2）；③**锚点存在性**——检查点位置引用的任务 ID/阶段边界/验收包 ID 在四源中真实存在（codegraph/Read 出处）；④**验证手段有绑定**——检查点判据所需工具/skill 在能力包里有绑定且无「显式不加载」冲突。三态标注：**已验证（附出处）/ 假设（置信度×错误时影响）/ 证伪（回子2，附理由）**。
- **input**：`step2.control_proposals`
- **record**：True；**fence_allow**：`("Bash",)`
- **gate**：trace 存在；形式要件（四类核验逐对象留痕；互斥面交集实算结果（命令+输出）进 trace；三态逐对象标注；出处/置信度×影响/理由齐备）；质量判据黑盒（声称可执行无 dry-run 留痕 = 编造判 block；交集核验无实算输出 = 没真核验判 block；全对象无差别「已验证」= 偷懒判 block；假设项缺置信度或影响判 block）。

### 子4 归一化执行计划包（kind=skill）

- **ref**：`define-problem(归一化职能第九次复用)`
- **purpose**：产出归一化执行计划包——①原子（单句 ≤1 个独立控制断言）；②**去上下文**（零上下文 orchestrator 照做：任务 ID/文件清单/判据命令自包含，禁「同上」「如前所述」）；③携带**执行计划包十字段**（消费契约锚点，§0 表）——调度节四字段：并行分组（DAG 层）/ 文件互斥面（含交集=空核验状态）/ worker 任务包映射 / 返回契约（证据形式清单）；检查点节六字段（per checkpoint）：位置锚 / 通过判据（零判断词）/ 失败路由 / 类型 / 验收包映射（含任务 ID 追溯锚）/ goal anchoring 重述句；④假设传导（子3 假设项原样携带，不丢不淡化）。放不进一句 = 未定义完。
- **input**：`step3.verified_controls`
- **record**：True；**fence_allow**：无
- **gate**：trace 存在；形式要件（调度四字段+检查点六字段齐备；与四源双向覆盖无漏（每 triggered 验收项有检查点落点或显式「continuous 覆盖」声明）；假设传导）；质量判据黑盒（字段与子2/子3 已定内容不一致 = 丢失/篡改/新增判 block；复合句判 block；判据判断词回潮判 block；triggered 验收项无落点且无声明 = 漏配判 block）。

### 子5 读回确认与 plan.md 装配（kind=skill）

- **ref**：`AskUserQuestion / Edit(plan.md 追加「执行计划与检查点」节)`
- **purpose**：带证据读回：呈现并行分组+互斥面核验状态+检查点清单（位置/判据/路由/类型）+假设清单+新增候选（子1 检出若有）+不确定性；**用户三裁决**：①**密度与类型拍板**（本节点核心规范裁决——每个检查点自动继续 vs 用户暂停，风险承担归用户，含要求加密/减密的合法权利）；②**假设接受**（同构前七个节点）；③**plan.md 冻结策略拍板**（进 execute 前的制度裁决——默认方案：小偏离 = 留痕理由（commit message + execute 完成时偏离清单，execute:0 rubric「偏离需有理由」已允许），大改 = `/dl back` 回 plan 修订重过闸门；禁 execute 内直接改 plan.md——judge 逐条核的对象不能是执行期可随手改的）；拍板后**装配 plan.md「执行计划与检查点」节**（内容 = 子4 归一化执行计划包 + 子5 裁决记录的直接装配，**禁二次创作**）；写 trace 记裁决原话 → STEP_DONE。
- **input**：`step4.execution_plan_packages`
- **record**：True；**fence_allow**：无
- **gate**：None（交互步，trace 存在即过）

### 末子步骤过后：hold_for_gate 扣留

子5 过门控后**无条件扣留**（state.held_for_gate），唯一出口 `/dl gate`——隔离测试语义（门栏变七处：understand:2/3/4 + plan:1/2/3/4）。放行后模型输出 `### PHASE_DONE: plan` 撞 plan->execute 大闸门（第二次 `/dl gate`）——与 plan:3（v2.20）/understand:4 完全同构。

**机制路径说明**：本节点是 `advance="phase"` 的 hold 节点，与 plan:3 同构——产物节在子5 内装配（hold 前已落地），`artifact_on_release=False`（plan:2/3 先例第三次使用）。**最大机制变更在 plan:3**：plan:3 从 plan 末子阶段变为中间子阶段，`advance` 须由 `"phase"` 改 `"sub"`——其 hold 语义从 understand:4 同构变为 understand:2/3 同构（机制已 pin），放行后走**跨子阶段自动续轮**进 plan:4 子1（既有机制）。plan:2 在 v2.20 已走过同一变更，路径有 pin 覆盖。无新机制路径，但须按 §6 走查清单逐项验证。

## 3. 门控设计要点（§3.5 对齐）

- **双结论制**（#3）：子2 接受「零用户检查点」为合法结论（须复利数学论证：逐步成功率估计 + 整体下界 + 全链可逆声明）——否则逼模型编造用户暂停点凑数；同时防「默认零暂停」逃避论证。区分「诚实零暂停」vs「懒得布点」的判据是论证留痕。
- **Goodhart 分层**（#2）：形式要件（四件/三属性/六字段/交集实算/dry-run 留痕）披露进 purpose；质量判据（虚设/即兴/拍脑袋分组/无验收门/越权/篡改）只留 gate 黑盒。
- **四桶分工**：清点/提案/核验/归一化 = 模型（写什么）；trace 落库 = append-trace 脚本（怎么写）；结构完整性 = judge（过不过）；密度拍板/假设接受/冻结策略 = 用户（认不认）。
- **judge 不判「布点最优」**——只判「追溯真实 + 判据零判断词 + 互斥面实算 + 三态核验真做 + 只提案未拍板」。密度取舍的真值源只有用户（子5）。
- **判据合法获取路径**（#7）：子1/3 fence_allow=("Bash",)（dry-run/交集实算/grep 全是低成本合法路径）；子2 fence_allow=("Agent",)（红队合法通道）——每条判据要求的佐证都存在合法获取路径，不逼编造。
- **消费契约倒推**（锚点法第六次使用）：十字段倒推自 execute:0 orchestrator 愿景/execute:0 rubric/understand:4 时机字段/review:0 证据需求/用户密度裁决五方（§0 表）——缺① orchestrator 执行期自行分组 = 违背「不自行分析」愿景；缺④ worker 返回物无验收门 = E9 失守；缺⑥ 检查点 = 虚设（E1）。
- **gate_mech 置 None**（有意偏离 plan:2/3 先例）：ARTIFACT_EXISTS 对 plan.md 在本节点**语义恒真**（文件自 plan:2 起存在）——保留 = 虚假防线暗示，违背 H13 精神（不挂无功能配置）。且机械门当前全类型未实现（`gate_verdict_mech` dl_flow_engine.py:409-418 一律 return None，留 §8.3）。实际 guard 链 = 子4 judge 验十字段 + 子5 禁二次创作 + 用户读回 + S13/S15 围栏（同 plan:2 风险 #8 论证）。§8.3 实现时本节点的正解 = ARTIFACT_CONTAINS（「执行计划与检查点」节存在检查），属该独立项的连带工作。**gate_rubric 置 None**（understand:4/plan:2/plan:3 先例第四次）：语义全部下沉逐步 gate，大闸门只跑机械门（本节点机械门亦无）。
- **judge 输入面**（#11）：子1 gate 的佐证走 evidence 路径——design.md/plan.md/understand.md 三个文件 judge 都读不到，四源原文必须引用进子1 trace 正文；rubric 文本含 `evidence/` 关键词触发 `rubric_needs_evidence`（plan:1 §3 实现注同款教训）。

## 4. 外部实证出处（2026-07-28 Tavily 取证留痕）

- **误差复利 / Lusser's Law**（Towards Data Science「The Math That's Killing Your AI Agent」——85%/步 × 8 步 = 27% 整体成功率，「P(success) 低于 50% 时不可逆任务必须在每阶段边界设人工检查点」；LinkedIn Joshua Summers——97%³=91%，「where you place humans, and how often, directly determines your compounding error ceiling」；GUI agent 实证 90%⁵=59%/90%¹⁰=35%）：——子2「布点默认 = 并行组/阶段边界」+ 双结论制复利论证的直接依据。
- **Self-conditioning**（zartis.com 引 "The Illusion of Diminishing Returns"（MPI-INF/TU Kaiserslautern 2025）——模型上下文含自己先前错误时产错概率可测上升，退化非线性加速；closed-loop 对抗检查可中和 40%+ 复利故障）：——子2 goal anchoring 重述句 + 检查点截断的直接依据。
- **Agent Drift 2026 / goal anchoring**（ceaksan.com 综述——semantic/coordination/behavioral 三型 drift；检测信号 = 每 N 步让 agent 重述原目标，定义漂移即 drift 活跃；Shahnovsky & Dror 2026 POMDP 形式化——plan-ahead agent 保持目标对齐，step-by-step agent 易漂）：——子2 每检查点内嵌目标重述句的直接依据。
- **Fabricated success reports**（arXiv 2605.30777「What Breaks When LLMs Code?」——185 论文 + 16,586 GitHub issue 挖掘的 547 个真实失效：agent 遇失败不 halt 求助反而谎报成功；dev.to 综述 #18 reward hacking——删 failing test 让 CI "过"、硬编期望答案、迎合 judge）：——子2「判据零判断词、命令+退出码」+ gate「虚设判 block」的直接依据。
- **Over-autonomy / 可逆性缩放**（dev.to 综述 #13——「autonomy should scale with trust and reversibility, not with ambition」，approval gates on irreversible actions；MindStudio——检查点核心设计问题是密度权衡，「make the review task as easy as possible」）：——子2「不可逆操作强制用户暂停」硬条款 + 密度按可逆性×爆炸半径提案的直接依据。
- **多 agent 错误放大**（zartis.com 引 "Towards a Science of Scaling Agent Systems"（2025，180 受控实验 × 4 基准 × 3 模型族）——去中心化架构错误放大 17.2×，中心化 orchestrator 委派 4.4×；Inspector pattern（ICML 2025 "On the Resilience of LLM-Based Multi-Agent Collaboration"）——对抗性验收 agent 截获 96.4% 下游传播错误）：——execute 愿景（orchestrator-worker）的实证背书 + 子2 返回契约/文件互斥面的直接依据。
- **结构化 handoff**（MetaGPT ICLR 2024 Oral——结构化产物 handoff 防 naive 链式调用的 cascading hallucinations）：——子1 四源清点基线 + 子4 归一化（防聚合失真 E7）的直接依据。
- **失败恢复结构**（TrajAudit arXiv 2605.26563——agentic coding 失败诊断需定位最早错误步，无预定义恢复结构时失败定位与恢复都难）：——子2 失败路由三选一预定义的直接依据。
- **本地单层源压缩原则**（沿用 `scope-and-constraints-substeps-design.md`）：判据 dry-run/交集实算/锚点存在性 = 本机事实，Bash 单层可验——子3 一步压缩、无独立质检裁决步（第六次否决同构双步方案）。

## 5. 否决的替代方案（对抗性审视留痕）

1. **4 步版（子3 并入子2，提案即核验）**——否：提案 = 设计族（控制结构创作，须独立 gate 核「三属性+四件齐备」），核验 = 事实族（dry-run/交集实算），异族 judge 分步可判；合并则「判据含判断词」与「dry-run 无留痕」混排单步，judge 判不准（plan:3 否决方案 1 同构）。
2. **6 步版（子2 拆调度提案 + 检查点提案双步）**——否：检查点位置 = 并行组边界（强耦合，拆开产生步间循环依赖：布点依赖分组、分组粒度又受布点密度约束）；同族（同一「运行时控制结构」对象的属性填充），judge 一步可判（plan:2 子2 一步判切分+排序+分组先例）。
3. **检查点机械强制版（Stop hook 在检查点物理拦截续轮）**——否（首版）：检查点机械强制需要 execute 阶段编排化才有落点（当前 execute:0 无 sub_steps，Stop hook 无「当前检查点」状态可读）；首版消费方式 = plan.md 内容 + phase-rules 文案约束 + 用户读回，机械强制属 execute 编排化的独立项（同 §8.3 先例：不把未实现机制写进 guard 链当实际防线）。
4. **新增 executor-brief.md（面向 subagent 的执行简报独立文档）**——否（2026-07-28 用户决议）：plan.md 已按零上下文自足设计（plan:2 子4），再加汇总文档 = 两个真源必然漂移（单一真源原则）；subagent 场景从 plan.md 逐条摘任务包派发即可。understand.md/design.md 内容**不复制**进 plan.md——goal anchoring 是引用式一句话重述，不是内容复制。
5. **并行分组放 plan:2（任务切分时一并分组）**——否：plan:2 轴心 = 保真转换（失真/虚构族），调度分组 = 运行时控制族（冲突/放大族），失效族不同；且并行分组依赖能力包的子代理策略（plan:3 产物），时序上不可能先于 plan:3。
6. **密度默认值硬编码（如「全部用户暂停」或「全自动」写进 purpose）**——否：密度 = 风险承担，规范裁决真值源只有用户（E10）；硬编码任一端都是模型/设计者越权代答。双结论制 + 复利论证义务已是防线。
7. **gate_mech 保留 ARTIFACT_EXISTS（对齐 plan:2/3）**——否：对 plan.md 在本节点语义恒真（文件自 plan:2 存在），保留 = 虚假防线暗示；gate_mech=None + §8.3 实现时挂 ARTIFACT_CONTAINS 是正解（§3）。
8. **4 步版（砍子1，直接从三源读进子2）**——否：本节点是首个四源聚合节点，聚合失真（E7）是独立失效族，无基线步则「漏源/ID 漂移/静默新增」无 gate 可拦（plan:2/plan:3 子1 同款基线先例）。

## 6. 实施 checklist（改编排必过，症状 M + §3.7 + §3.8 #6 机制走查）

**机制适配走查六项**（设计期逐函数走查结论，实施时验证）：
①末步推进 `_advance_sub_step`：plan:4 advance="phase"（understand:4/plan:3 先例已 pin）；**plan:3 改 advance="sub"**（understand:2/3 + plan:2(v2.20) 先例已 pin——v2.20 对 plan:2 做过同一变更，路径有测试覆盖）。②门栏放行 `release_subgate`：plan:3 改 sub 后，放行从「等 PHASE_DONE」变「自动续轮进 plan:4 子1」——advance="sub" hold 先例已覆盖。③完成信号通道：plan:4 末步后 PHASE_DONE 可达性 = plan:3 原路径（`phase_done_channel_open` 单源判据）；plan:3 提前 PHASE_DONE 被守卫阻断（既有）。④注入状态机**逐态文案**（plan:2 沉淀教训）：`artifact_on_release` 分支读取条件走查——plan:3 改 sub 后其 False 值不再被读；plan:4=False（产物节子5 内装配，放行后只提示 PHASE_DONE）；冒烟必须覆盖 plan:3/plan:4 各自三态（编排中/扣留/放行后）。⑤/dl 命令路由：held 检测与 phase gate 次序不变。⑥judge 输入面：子1 rubric 含 `evidence/` 关键词触发 `rubric_needs_evidence`；三个产物文件 judge 读不到 → 四源原文引用进 trace。

1. `dl_flow_nodes.py`：**新增 `plan:4` Node**——label「制定执行计划和检查点」；skill=None（编排节点 skill 走 Step ref）；artifact="plan.md"；gate_mech=None（§3/§5 #7 论证——有意偏离 plan:2/3 的 ARTIFACT_EXISTS，实施时先验 Node 定义 gate_mech 可空）；gate_rubric=None；advance="phase"；`sub_steps`（5 个 Step）+ 形式要件常量（单源）；`minor_key="ExecutionPlanCheckpoints"`；hold_for_gate=True；artifact_on_release=False。**plan:3 改 advance="phase"→"sub"**——连锁检查其 hold 语义注释/测试断言。**存量工作流迁移**：advance 变更影响在途实例——单人维护可接受，迁移 = `/dl jump plan` 重置或手改 state.json
2. `hooks/workflow_phase.py` `_format_injection`：**预期无需改**（子阶段标签/子步骤清单从 engine 推导）——走查④：确认 artifact_on_release 分支对 advance="sub" 的 plan:3 不产出错文案；冒烟验证注入含「子阶段: 制定执行计划和检查点 [4/4]」+ 5 步骨架链
3. `scripts/workflow/phase-rules.md`：plan 段加 plan:4 的 GENERATED 标记段 + 静态强制语义（evidence 是 STEP_DONE 前置/输完即 end_turn/子5 装配 plan.md 节义务/门栏扣留等 /dl gate + 放行后 PHASE_DONE 撞大闸门）；**execute 节加一行硬指令**（消费路径闭合，2026-07-28 会话决议——非 execute 编排化，仅一行）：「首步 = 读 plan.md（执行步骤 + 能力节 + 执行计划与检查点节）；按检查点停，偏离需留痕理由」
4. `skills/workflow-creation/SKILL.md` + `references/node-design.md`：§0 摘要块更新——门栏七处（understand:2/3/4 + plan:1/2/3/4）+ plan:4 5 步摘要段（含关键不对称第八种 + plan:3 advance 变更说明）；§3.8 关键不对称表加第八行（ExecutionPlanCheckpoints=时序控制 × 风险配平）；「改 engine Step.purpose 实质内容后须手工同步摘要块」纪律适用
5. `tests/test_dl_flow_engine.py`：plan:4 新 Step 定义测例（5 步数/各 gate 含关键判据/子1/3 fence_allow=("Bash",)/子2 fence_allow=("Agent",)/子5 gate=None/selfcheck 无质量判据泄漏钉死/hold_for_gate=True/minor_key=ExecutionPlanCheckpoints/gate_mech=None/gate_rubric=None/artifact_on_release=False）；**plan:3 advance 改 sub 的连锁断言更新**（「末子阶段」假设全仓 grep：tests/hooks/docs/phase-rules）；排他性/唯一性断言全量遍历 `_NODES`
6. 冒烟：真实 state 直调 `_format_injection` + `render-phase-rules`（不开会话）；真实 TTY 跑一轮验证——plan:3 放行后自动续轮进 plan:4 子1、子1 四源原文引用留痕、子2 并行分组+互斥面+检查点三属性、子3 交集实算输出进 trace、子5 plan.md 节装配落地 + 三裁决（密度/假设/冻结策略）、门栏扣留 + /dl gate 放行 + PHASE_DONE 撞 plan->execute 大闸门、推进 execute:0 后注入正确显示；**plan:3/plan:4 各三态覆盖**（走查④）

## 7. 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| 1 | 检查点虚设（判据含判断词——executor 无判断能力时 = 无判据，E1 最高危） | 子2 零判断词义务进 purpose + gate 黑盒「虚设判 block」+ 子3 dry-run 实测 + 子4「判断词回潮判 block」双保险 |
| 2 | 密度失配（过密用户疲劳/过疏复利失控） | 密度只提案不拍板 + 可逆性×爆炸半径提案依据 + 双结论制复利论证 + 用户子5 拍板兜底 |
| 3 | 并行冲突（worker 同改文件合并爆炸，E8） | 子2 互斥面从改动点计算 + 子3 集合交集**实算**核验（命令+输出进 trace）+ gate「无实算输出判 block」 |
| 4 | 返回物无验收（worker 自我宣称完成即合并，E9） | 子2 返回契约证据形式清单 + 子4 契约进检查点判据 + Inspector pattern 96.4% 实证进 purpose |
| 5 | 多源聚合失真（四源 ID 漂移/漏项，E7——首个聚合节点新风险） | 子1 五类清单+原文引用进 trace（judge 输入面）+ gate「漏源判 block」+ 子4 双向覆盖（triggered 验收项全有落点） |
| 6 | 失败处置缺失（检查点红了 executor 死锁/乱撞，E6） | 子2 失败路由三选一预定义 + gate「『视情况』判 block」 |
| 7 | 执行期 plan.md 被改（judge 逐条核的对象在动，合同公信力失效） | 子5 第三裁决点冻结策略（默认：小偏离留痕/大改 /dl back）+ 拍板记录装配进 plan.md |
| 8 | 子5 无 judge，产物节缺漏无人拦（注意机械门=None，本节点连声明式兜底都没有） | 子4 judge 已验十字段（装配无新增内容可错）+ 子5 purpose 写死装配义务 + S13/S15 围栏 + 用户读回确认本身即质量门（plan:2 风险 #8 同构；ARTIFACT_CONTAINS 属 §8.3 独立项） |
| 9 | 弱遵从模型跳过清点直接写方案（症状 P 抢答模式重演） | S15 前置参与围栏按 fence_allow 白名单物理拦截；S13 兜底纯 text 抢答 |
| 10 | 「零用户检查点」被滥用逃布点（双结论被回避） | 复利论证留痕是合法佐证路径；gate 黑盒「无论证判 block」；用户子5 拍板兜底 |
| 11 | plan:3 advance 改 sub 引入回归（在途实例/fixture 假设） | v2.20 plan:2 已走过同一变更（路径有 pin）；fixture 全仓 grep「末子阶段」；存量迁移 = /dl jump plan 重置 |
| 12 | goal anchoring 重述句流于形式（每检查点复制同一句 = 新 drift） | 子2 purpose 要求重述句含「原目标 + 当前位置」两成分（位置变则句变）；子4 gate 复合句/拷贝判 block |
