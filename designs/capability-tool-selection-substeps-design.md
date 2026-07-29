# plan:3「选择能力与工具」子步骤编排设计（CapabilityToolSelection）

> 状态：**已实现（v2.20，2026-07-28）**——§6 checklist 全项落地：plan:3 Node（6 步）+ plan:2 advance phase→sub + phase-rules plan:3 段 + skill 摘要块（关键不对称第七种）+ 401 tests 全绿 + 注入三态/render 冒烟通过。机制走查④结论：`phase_done_channel_open` 对 advance="sub" 恒 False（engine:584），plan:2 改 sub 后 `artifact_on_release` 不被读取（不再显式声明）；plan:3 放行后第三态文案走 artifact_on_release=False 分支（「plan.md已在末子步骤装配完成」）冒烟验证正确。遗留：真实 TTY 全轮跑（隔离测试语义的第一轮实测）待用户发起 dl 实例验证。
> 确认史（2026-07-28 用户三连决议）：①会话确认 **6 步**结构；②**hold_for_gate 加**——隔离测试语义，同 understand:3/4、plan:1/2 先例，门栏变六处；③**gate_mech 保持 ARTIFACT_EXISTS**——补查发现 `gate_verdict_mech` 机械门**全类型未实现**（dl_flow_engine.py:409-418 一律 return None，「暂不实现文件查找，留 §8.3」），ARTIFACT_CONTAINS 无现成文件查找可挂，新机制路径连带 ARTIFACT_EXISTS 的 TODO 一起做属独立项；能力节落地 guard = 子5 judge 验五字段 + 禁二次创作 + 用户读回 + S13/S15 围栏，同 plan:2 风险 #8 论证
> 父文档：`node-step-orchestration-design.md`（子步骤编排机制）、`task-breakdown-substeps-design.md`（最近范式 + plan:2 产物即本节点输入）、`design-solution-substeps-design.md`（编程工作流定位 + 消费契约倒推锚点法）、`scope-and-constraints-substeps-design.md`（本地单层源压缩原则）、`workflow-creation` SKILL.md §3.5（rubric 方法论）/ §3.8（拆步方法论）
> 外部取证：本文 §4（Tavily 检索，2026-07-28，设计期调研——用户明示允许；与运行期 understand:1 子3「禁 tavily/WebSearch」约束无关）

## 0. 背景

plan 阶段当前两子阶段：plan:1 设计解决方案（6 步编排）→ plan:2 拆解任务与阶段（5 步编排，产物 plan.md）。**plan:3「选择能力与工具」是新增子阶段**：plan.md 里的执行单元已定，但「每个单元由什么能力执行」未定——executor 是 Claude Code，其能力面 = skill（superpowers 系/项目 skill）+ 内置工具 + CLI（codegraph）+ MCP server + 子代理策略 + 项目强制项（H15 codegraph 门禁、CLAUDE.md §2 路由表触发、§3 执行映射条目）。不配能力包，executor 逐步靠训练记忆临时决定 invoke 谁——这正是 LLM 工具选择失效研究（§4）证实的最高危区。

输入 = plan:2 拍板终态：`plan.md`（执行包五字段/阶段划分/追溯锚）+ evidence 里 minor_stage=TaskBreakdown 的 trace（子5 裁决原话）。
输出 = plan.md **追加「能力与工具」节**（子6 拍板后装配），供 execute:0 直接消费。

**编程工作流定位**（沿用 DesignSolution/TaskBreakdown 元约束）：产物不是通用「资源-角色分配表」，是**锚定本会话真实注册表 + 本仓强制规则的执行配置**——能力名逐字引用注册表（available-skills 列表/磁盘 skill 目录/MCP 配置/CLI），强制项逐任务核对。通用形态产不出「skill 名与注册表逐字一致」「H15 前置触发」这种可核验断言。

**消费契约锚点**（锚点法第五次使用）：能力包字段倒推自下游消费方，不是拍的——

| 下游 | 其 rubric/职责 | 倒推出的能力包字段 |
|---|---|---|
| execute:0 gate | 「对照 plan 步骤逐条核，偏离需有理由」 | ①必先 skill + ②工具/CLI 清单（每步该用什么有据可核） |
| superpowers:using-superpowers | 「任何响应前先 invoke 相关 skill」（superpowers 铁律，SessionStart 每会话注入） | ①必先 skill + 触发依据引用（executor 逐步知道先 invoke 谁、为什么） |
| 项目 H15 hook / CLAUDE.md §3 执行映射 | 改 .py 前 codegraph 留痕（PreToolUse 阻断）；长 pipeline 后台禁 pipe 等 | ③强制门禁对齐项（executor 行为约束随任务携带） |
| Agent 工具使用决策 | 扇出/subagent/模型选择有成本，须预先拍板不临时起意 | ④子代理策略（无则显式「单线程」） |
| tool overload 防线（§4 实证：准确率随工具数坍塌） | 最小集承诺——不加载什么与加载什么同等重要 | ⑤显式不加载清单 |

## 1. 第一性原理

### 1.1 终态三属性（同构前六个节点）

| 属性 | 在本子阶段的含义 | 承担步骤 |
|---|---|---|
| 内容正确 | 需求清单保真于 plan.md（无镀金无丢失）；候选能力**真实存在于注册表**且强制路由无漏核；绑定理由有据（trigger 原文）；可用性真实（环境可跑）；假设显式化 | 子1-4 |
| 形式可移植 | 归一化能力包携带五字段，execute:0/using-superpowers 可直接消费；装配为 plan.md「能力与工具」节 | 子5-6 |
| 用户认可 | 映射拍板（含换绑/卸载）、假设接受 = 规范裁决，归用户 | 子6 |

### 1.2 关键不对称（第七种）：有限枚举 × 配置接地

| 子阶段 | 命题性质 | 编排后果 |
|---|---|---|
| ProblemContext | 纯事实性 | 五层外部源取证 + 质检裁决双步 |
| GoalsAndValue | 纯规范性 | 无取证步 |
| ScopeAndConstraints | 混合：约束=事实性，范围=规范性，假设=中间态 | 约束本地单层源压缩验证一步 |
| SuccessCriteria | 混合，轴心=规范性目标的可检验化转换 | 新增可检验化独立步 |
| DesignSolution | 混合，轴心=创造性生成 × 代码接地 | 新增现状勘察 + 方案发散双独立步 |
| TaskBreakdown | 混合，轴心=保真转换 × 执行接地 | 无发散步；新增清点基线 + 锚点核验步 |
| **CapabilityToolSelection** | **混合，成分又换**：「skill X 覆盖操作 Y」=事实性（本地单层源：Read 注册表/SKILL.md）；「工具 X 环境可用」=事实性（本地单层源：Bash 实测）；「选 X 弃 Y」=规范性提案（用户拍板）；假设=中间态 | **无发散步**（能力空间=有限可枚举注册表，非生成空间——发散=逼编造伪候选，与 TaskBreakdown 同理）；**无独立质检裁决步**（本地单层源第五次压缩）；新增**注册表盘点步**（前六个节点都不需要——它们的对象是会话内容/代码事实，本节点的对象是**模型训练记忆与真实注册表最容易打架的能力面**，幽灵能力防御须先立注册表基线）+ **匹配选型步**（本节点存在的理由，独立 gate） |

与前两节点的镜像关系：plan:1 主敌是「无中生有」的固化与凭空；plan:2 主敌是「从有到有」的失真与虚构；**plan:3 主敌是「从有选有」的幽灵与错配**——两侧对象（任务/能力）都已存在，失效发生在**二者之间的映射**上：模型凭训练记忆引用注册表里没有的能力名（ghost invocation，§4 形式化 f̂∉F）、凭名字猜功能绑错对象（distractor tool）、或「以防万一」全挂上致选择准确率坍塌（tool overload 实证 95%→71%）。

### 1.3 失效模式分析

| # | 失效模式 | 外部出处（§4） |
|---|---|---|
| C1 | 幽灵能力：凭训练记忆引用注册表没有的 skill/工具/MCP 名 | ghost tool invocation；SimpleToolHalluBench NTA 模式；arXiv 2601.05214 f̂∉F 形式化 |
| C2 | 能力错配：能力存在但不覆盖需求（凭名字猜功能，未读 trigger/description 原文） | distractor-tool 模式；ToolBH MNT/LFT 场景 |
| C3 | 漏配强制项：项目强制路由（CLAUDE.md §2 触发词、H15、TDD/karpathy 触发）未逐任务核对 | 项目内部真源（编程域一等约束源，understand:3 先例） |
| C4 | 过度配置：无绑定能力「以防万一」挂上 → 选择准确率坍塌 + context bloat | tool overload 实测（95%→71%）；RAG-MCP（13.62%→43.13%）；lost-in-the-middle |
| C5 | 环境不可用：注册表有条目 ≠ 运行环境可用（CLI 不在 PATH/MCP 未连/key 缺失） | solvability awareness（agent hallucination survey）；本地实证族（understand:3 先例） |
| C6 | 需求失真：绑定不追溯到 plan.md 任务 ID（转换失真族） | Agent Drift / goal anchoring（TaskBreakdown 先例沿用） |
| C7 | 重型手段滥用：Workflow/多 agent 扇出/长 pipeline 与任务复杂度不相称 | tool overload 成本实证（latency/cost/reliability 同步恶化） |
| C8 | 复合/去上下文不可移植：零上下文执行者拿到能力包不知道先 invoke 谁 | zero-context engineer（executing-plans，TaskBreakdown 沿用） |
| C9 | 模型越权拍板映射/代答假设（规范裁决被代答） | 四桶分工（认不认归用户） |

**步数推导**（§3.8 #4，按失效模式族）：需求族（C6）→ 子1；盘点族（C1 清单面+C3）→ 子2；匹配族（C2+C4+C7，同族=映射决策）→ 子3；核验族（C1 核验面+C5，同族=本地单层源事实核验）→ 子4；形式族（C8）→ 子5；认可族（C9）→ 子6。**6 族 = 6 步**。C1 跨族说明：盘点面防「清单里混入幽灵」（枚举时逐字引用注册表），核验面防「条目在列表但环境不可用」（Bash 实测）——同一失效模式的两个防御面分属不同族，同构 plan:1 子1 勘察/子3 可行性核验的分工。步数 6 与 ProblemContext/DesignSolution 相同纯属巧合——各自按族独立推导。

## 2. 设计：6 步

```
子1 需求清点与追溯基线 → 子2 能力盘点与强制路由核对 → 子3 匹配选型提案 → 子4 可用性核验与假设标注 → 子5 归一化能力包 → 子6 读回确认与 plan.md 装配
```

judge 调用 5 次（子6 gate=None）。

### 子1 需求清点与追溯基线（kind=tool）

- **ref**：`Read(plan.md) / Bash(grep evidence TaskBreakdown trace)`
- **purpose**：从 plan.md + evidence 里 minor_stage=TaskBreakdown 的 trace **无损提取**任务操作需求清单——逐任务/阶段标注操作类型：代码改动（改 .py = H15 触发信号）/ 测试执行 / 长 pipeline（后台禁 pipe 信号）/ 外部检索 / 数据读取（parquet 等）/ 子代理扇出 / 文档装配，每条附**任务 ID 出处 + plan.md 原文引用进 trace 正文**（judge 读不到 plan.md 文件——TaskBreakdown 子1 同款教训）。**只提取不创作**——检出 plan.md 没有的需求 = 二次创作信号，显式列「新增候选」待子6 用户裁决（禁静默混入）。
- **input**：`plan.md + evidence(TaskBreakdown 子4/子5 trace)`
- **record**：True；**fence_allow**：`("Bash",)`（grep evidence jsonl；Read 在常驻集）
- **gate**：trace 存在；形式要件（逐任务操作类型清单齐备；每条附任务 ID 出处；plan.md 原文引用进 trace 正文；新增候选显式标注或显式「无」）；质量判据黑盒（需求无出处 = 编造判 block；静默新增 plan 没有的需求 = 二次创作判 block；大段改写致语义偏移 = 失真判 block）。

### 子2 能力盘点与强制路由核对（kind=tool）

- **ref**：`Read(CLAUDE.md §2/§3 / 相关 SKILL.md frontmatter) / Bash(注册表枚举：ls ~/.claude/skills + .claude/skills、MCP 配置、which codegraph)`
- **purpose**：枚举**本会话真实注册表**三通道——①skill 注册表（会话注入的 available-skills 列表 + 磁盘用户级/项目级 skill 目录，**名称逐字引用注册表，禁凭训练记忆**）；②工具/CLI/MCP（内置工具集 + codegraph CLI + MCP server 列表）；③**强制路由核对**（编程域一等约束源：CLAUDE.md §2 触发词逐任务匹配——开发因子→factor-development 等；H15 改 .py 前 codegraph 留痕；superpowers 铁律——写代码前 TDD、测试失败 systematic-debugging、任何编码 karpathy-guidelines）。每条候选附**注册表出处**（列表行/文件路径）。**双结论制**：「内置工具足够、零 skill」是合法结论（小改动无触发命中），但须逐任务说明——防逼编造 skill 绑定凑数（同 TaskBreakdown 子2「单阶段不可拆」机制）。
- **input**：`step1.need_baseline`
- **record**：True；**fence_allow**：`("Bash",)`
- **gate**：trace 存在；形式要件（三通道清单齐备；能力名逐字引用注册表出处；强制路由逐任务核对留痕；②逐任务说明或显式 skill 候选）；质量判据黑盒（能力名与注册表出处不符 = 幽灵能力判 block；强制路由漏核 = 漏配判 block；功能描述无 SKILL.md/listing 出处 = 凭记忆编造判 block；②无逐任务说明 = 偷懒判 block）。

### 子3 匹配选型提案（kind=skill）

- **ref**：`推理(需求×能力映射) / Agent(条件红队)`
- **purpose**：需求×能力映射，四判据——①**覆盖**（能力 trigger/description 原文覆盖任务操作类型，引用子2 出处，禁凭名字猜）；②**最小集**（每能力必须绑定 ≥1 需求，**无绑定 = 不加载**——tool overload 防线，§4 实证选择准确率随工具数坍塌）；③**成本相称**（重型手段——Workflow 多 agent/子代理扇出/长 pipeline——须任务复杂度相称辩护，防 C7）；④**强制优先**（项目强制项不可被「更顺手」的非强制项替代）。每条绑定附理由 + 被否替代；**双向追溯矩阵**（每需求有绑定或显式「内置足够」；每能力绑定到需求——双向无漏，PMI 式，understand:3 子3 沿用）；条件红队（绑定数超阈值或含高成本项时触发，独立上下文反驳映射）；**只提案不拍板**——映射取舍是用户偏好（子6 裁决）。
- **input**：`step2.capability_registry + step1.need_baseline`
- **record**：True；**fence_allow**：`("Agent",)`（条件红队，同 DesignSolution 子4）
- **gate**：trace 存在；形式要件（双向追溯矩阵齐备；每条绑定附理由+子2 出处；被否替代留痕；红队留痕或条件未触发声明；提案-待裁决语义）；质量判据黑盒（无绑定能力残留 = 过载判 block；绑定理由无出处 = 凭名字猜判 block；强制项被非强制项替代且无辩护判 block；重型手段无成本辩护判 block；拍板语气 = 越权判 block）。

### 子4 可用性核验与假设标注（kind=tool）

- **ref**：`Bash(which/版本冒烟/MCP 连接确认/venv 依赖) / Read`
- **purpose**：逐绑定核验可用性（本地单层源，沿用 ScopeAndConstraints 压缩原则——第五次否决取证+质检双步，只标注不裁决）：①skill 条目真实存在（注册表列表行/磁盘路径）；②CLI 可用（`which codegraph` + 新鲜度/版本冒烟）；③MCP server 实际连接（配置 + 会话工具面）；④环境前提（venv/依赖/key **存在性**——只验存在不验密值）。三态标注：**已验证（附出处）/ 假设（置信度×错误时影响）/ 证伪（回子3 换绑，附理由）**。
- **input**：`step3.binding_proposals`
- **record**：True；**fence_allow**：`("Bash",)`
- **gate**：trace 存在；形式要件（每绑定四类核验留痕；三态逐绑定标注；出处/置信度×影响/理由齐备）；质量判据黑盒（声称可用无出处 = 编造判 block；全绑定无差别「已验证」= 没真核验判 block；假设项缺置信度或影响判 block）。

### 子5 归一化能力包（kind=skill）

- **ref**：`define-problem(归一化职能第八次复用)`
- **purpose**：对每任务产出归一化能力包——①原子（单句 ≤1 个独立配置断言）；②**去上下文**（零上下文执行者照做：能力名逐字+触发依据自包含，禁「同上」「类似任务 N」）；③携带**能力包五字段**（消费契约锚点，§0 表）：必先 skill（名+触发依据引用）/ 工具与 CLI 清单（含子4 可用性状态）/ 强制门禁对齐项（H15 codegraph 前置、长 pipeline 后台禁 pipe 等执行映射条目）/ 子代理策略（扇出/模型/隔离，无则显式「单线程」）/ **显式不加载清单**（抗 overload 承诺）；④假设传导（子4 假设项原样携带，不丢不淡化）。放不进一句 = 未定义完。
- **input**：`step4.verified_bindings`
- **record**：True；**fence_allow**：无
- **gate**：trace 存在；形式要件（每任务五字段齐备；与需求双向覆盖无漏；不加载清单显式或显式「无」；假设传导）；质量判据黑盒（字段与子3/子4 已定内容不一致 = 丢失/篡改/新增判 block；复合句判 block；能力名与子2 注册表出处不符 = 幽灵回潮判 block；不加载清单缺失且无声明判 block）。

### 子6 读回确认与 plan.md 装配（kind=skill）

- **ref**：`AskUserQuestion / Bash(plan.md 追加「能力与工具」节)`
- **purpose**：带证据读回：呈现映射摘要+可用性状态+假设清单+不加载清单+新增候选（子1 检出若有）+不确定性；**用户两裁决**：①**映射拍板**（本节点唯一规范裁决点——含要求换绑/卸载/补绑的合法权利）；②**假设接受**（风险承担，同构前六个节点）；拍板后**装配 plan.md「能力与工具」节**（内容 = 子5 归一化能力包 + 子6 裁决记录的直接装配，**禁二次创作**——同 understand.md/design.md/plan.md 装配原则）；写 trace 记裁决原话 → STEP_DONE。
- **input**：`step5.capability_packages`
- **record**：True；**fence_allow**：无
- **gate**：None（交互步，trace 存在即过）

### 末子步骤过后：hold_for_gate 扣留（用户决议 2026-07-28）

子6 过门控后**无条件扣留**（state.held_for_gate），唯一出口 `/dl gate`——与 understand:3/4、plan:1/2 同款**隔离测试**语义（门栏变六处：understand:2/3/4 + plan:1/2/3）。放行后模型输出 `### PHASE_DONE: plan` 撞 plan->execute 大闸门（第二次 `/dl gate`）——门栏放行 ≠ 阶段推进（同 understand:4/plan:2）。

**机制路径说明**：本节点是 `advance="phase"` 的 hold 节点，与 plan:2 **同构**——能力节在子6 内装配（hold 前已落地），无「放行后写产物」窗口 → `artifact_on_release=False`（plan:2 先例第二次使用）。**本设计最大机制变更不在 plan:3 而在 plan:2**：plan:2 从 plan 末子阶段变为中间子阶段，`advance` 须由 `"phase"` 改 `"sub"`——其 hold 语义随之从 understand:4 同构变为 understand:2/3 同构（advance="sub" hold，机制已 pin），放行后走**跨子阶段自动续轮**进 plan:3 子1（2026-07-27 起既有机制）。无新机制路径，但须按 §6 走查清单逐项验证。

## 3. 门控设计要点（§3.5 对齐）

- **双结论制**（#3）：子2 接受「内置工具足够、零 skill」为合法结论（须逐任务说明）——否则逼模型编造 skill 绑定凑数。区分「诚实零绑定」vs「懒得盘点」的判据是逐任务说明留痕。
- **Goodhart 分层**（#2）：形式要件（清单/逐字出处/双向追溯/三态/五字段/不加载清单）披露进 purpose；质量判据（幽灵/错配/过载/漏配/越权/篡改）只留 gate 黑盒。
- **四桶分工**：清点/盘点/匹配/核验/归一化 = 模型（写什么）；trace 落库 = append-trace 脚本（怎么写）；结构完整性 = judge（过不过）；映射拍板/假设接受 = 用户（认不认）。
- **judge 不判「选得更好」**——只判「追溯真实 + 出处真实 + 最小集 + 可用性核验真做 + 只提案未拍板」。选型优劣的真值源只有用户（子6）。
- **判据合法获取路径**（#7）：子1/2/4 fence_allow=("Bash",) + 常驻集 Read/codegraph；子3 fence_allow=("Agent",)（红队合法通道）——每条判据要求的佐证都存在低成本合法获取路径，不逼编造。
- **消费契约倒推**（锚点法第五次使用）：能力包五字段倒推自 execute:0/using-superpowers/H15+执行映射/Agent 成本决策/overload 防线五方需求（§0 表）——缺任一字段，下游就得临时找补（缺① executor 靠训练记忆选 skill = C1 温床；缺③ 执行映射条目到不了任务现场；缺⑤ 过载防线失守）。
- **plan.md 机械门**（同 plan:2）：静态路径 ARTIFACT_EXISTS 保留（声明式兜底）；**注意机械门当前全类型未实现**（`gate_verdict_mech` dl_flow_engine.py:409-418 一律 return None，文件查找留 §8.3）——实际 guard = 子5 judge 验五字段（装配无新增内容可错）+ 子6 禁二次创作 + 用户读回 + S13/S15 围栏（同 plan:2 风险 #8 论证）；ARTIFACT_CONTAINS（节存在检查）已否决，见 §5 #9。**gate_rubric 置 None**（understand:4/plan:2 先例第三次）：语义全部下沉逐步 gate，大闸门只跑机械门。
- **judge 输入面**（#11）：子1 gate 的佐证走 evidence 路径——plan.md 文件 judge 读不到，需求原文必须引用进子1 trace 正文；rubric 文本含 `evidence/` 关键词触发 `rubric_needs_evidence`（plan:1 §3 实现注同款教训）。

## 4. 外部实证出处（2026-07-28 Tavily 取证留痕）

- **Ghost tool invocation / tool-use hallucination 分类**（salmanq.com「Why Agents Hallucinate Tool Calls」——模型调未注册工具是预训练概率不为零的直接后果，「tool list doesn't match the patterns it learned」；emergentmind tool-use hallucination 综述——SimpleToolHalluBench（Yin 2025）两失效模式：NTA（无可用工具仍调用）+ DT（只有干扰项时调用干扰项或发明工具）；arXiv 2601.05214 形式化 f̂∉F = function selection error）：——子2「名称逐字引用注册表出处」+ gate「幽灵能力判 block」的直接依据。
- **ToolBH（Zhang 2024）**：missing necessary tools（MNT）/ limited functionality tools（LFT）场景——工具存在但功能不覆盖需求是独立失效类：——子3「覆盖判据须引用 trigger 原文、禁凭名字猜」的直接依据。
- **Tool overload 实证**（dev.to thedailyagent——代表性任务集上工具选择准确率从聚焦工具集 ~95% 掉到全量 GitHub MCP ~71%，「24-point accuracy gap caused purely by context bloat」；RAG-MCP arXiv 2505.03275——工具数增长时 baseline 选择成功率显著坍塌，检索式按需加载 13.62%→43.13%；machinelearningmastery——lost-in-the-middle + 工具幻觉随相似工具数恶化；jenova/promptforward——50+ MCP 工具定义 ~72k token，200k 窗未开工已占 ~40%）：——子3「最小集判据：无绑定 = 不加载」+ 子5「显式不加载清单」的直接依据。
- **Agent hallucination survey（arXiv 2509.18970）**：tool solvability——「agent mistakenly assumes that the plan is solvable and proceeds with unjustified confidence」，可用工具集 ≠ 假设可执行：——子4「注册表有条目 ≠ 环境可用」三态核验的直接依据。
- **Agent Drift / goal anchoring**（沿用 `task-breakdown-substeps-design.md` §4）：——子1 需求基线 + 任务 ID 追溯锚的直接依据。
- **zero-context engineer**（superpowers executing-plans，沿用）：——子5 去上下文 + 必先 skill 字段的直接依据。
- **本地单层源压缩原则**（沿用 `scope-and-constraints-substeps-design.md`）：可用性核验 = 本机事实，Bash/Read 单层可验，无「五层源过程质量」可判——子4 一步压缩、无独立质检裁决步（第五次否决同构双步方案）。

## 5. 否决的替代方案（对抗性审视留痕）

1. **5 步版（子3 匹配并入子5 归一化，对齐 plan:2 步数）**——否（第一性原理）：匹配 = 决策族（提案-裁决语义，须独立 gate 核「理由有据+最小集」），归一化 = 形式族，异族 judge 分步可判；匹配无独立 gate = 本节点存在的理由（选型）无人核。plan:2 无匹配步是因为选型已被 plan:1 消费（关键不对称即此）。
2. **并入 plan:2（plan:2 加能力选择子步骤）**——否：plan:2 轴心 = 保真转换（失真/虚构族），能力选择 = 枚举配置（幽灵/错配/过载族），失效族不同 rubric 混排 judge 单步不可判；且 plan:2 已 5 步，加族超单节点步数预算。
3. **7 步版（子2 拆 skill 盘点 + 工具/CLI 盘点双步）**——否：同族（注册表枚举 + 逐字出处），judge 一步可判「清单+出处」；拆 = 纯烧 judge。
4. **7 步版（子4 拆取证 + 质检裁决双步，照抄 ProblemContext）**——否：本地单层源没有「五层源过程质量」可判，独立质检步判无可判 = 纯烧 judge（第五次否决同构方案）。
5. **加发散步（照抄 plan:1 发散 ≥3 能力组合）**——否：能力空间 = 有限可枚举注册表，非生成空间；发散 = 逼编造伪候选凑数（TaskBreakdown 否决方案 1 同理）。
6. **节点级 gate_rubric 保留语义审据**——否（understand:4/plan:2 先例第三次）：语义下沉逐步 gate，大闸门只跑 ARTIFACT_EXISTS 机械门。
7. **hold_for_gate 不加**——否（2026-07-28 用户决议加）：沿用 understand:3/4、plan:1/2 隔离测试语义先例，plan 第三个编排节点跑完被围栏围住。代价（多一次 /dl gate）已知情接受。门栏六处：understand:2/3/4 + plan:1/2/3。
8. **能力包写进独立文件（capabilities.md）而非追加 plan.md**——否：execute:0 消费契约 = 单 plan.md 直读；拆文件 = 执行者两处对齐，漂移温床（TaskBreakdown 消费契约倒推原则）。且独立文件若为动态名会复现 plan:1 机械门限制，无收益。
9. **新增 GateMech.ARTIFACT_CONTAINS（机械门检查「能力与工具」节存在）**——否（2026-07-28 用户决议）：补查发现 `gate_verdict_mech` 机械门**全类型未实现**（dl_flow_engine.py:409-418 一律 return None，「暂不实现文件查找，留 §8.3」）——ARTIFACT_CONTAINS 无现成文件查找可挂，等于连带实现 ARTIFACT_EXISTS 的 TODO，属独立项不在本设计范围；能力节落地 guard 链（子5 judge + 禁二次创作 + 用户读回 + 围栏）已覆盖该缺口（同 plan:2 风险 #8）。

## 6. 实施 checklist（改编排必过，症状 M + §3.7 + §3.8 #6 机制走查）

**机制适配走查六项**（设计期逐函数走查结论，实施时验证）：
①末步推进 `_advance_sub_step`：plan:3 advance="phase"（understand:4/plan:2 先例已 pin）；**plan:2 改 advance="sub"**（understand:2/3 先例已 pin）。②门栏放行 `release_subgate`：plan:2 改 sub 后，放行从「等 PHASE_DONE」变「自动续轮进 plan:3 子1」——advance="sub" hold 先例（understand:2/3）已覆盖。③完成信号通道：plan:3 末步后 PHASE_DONE 可达性 = plan:2 原路径（`phase_done_channel_open` 单源判据）；plan:2 提前 PHASE_DONE 被守卫阻断（既有）。④注入状态机**逐态文案**（plan:2 沉淀教训）：`artifact_on_release` 分支（workflow_phase.py:297）读取条件走查——plan:2 改 sub 后其 False 值不再被读（确认非死字段歧义）；plan:3=False（能力节子6 内装配，放行后只提示 PHASE_DONE）；冒烟必须覆盖 plan:2/plan:3 各自三态（编排中/扣留/放行后）。⑤/dl 命令路由：held 检测与 phase gate 次序不变。⑥judge 输入面：子1 rubric 含 `evidence/` 关键词触发 `rubric_needs_evidence`；plan.md judge 读不到 → 需求原文引用进 trace。

1. `dl_flow_nodes.py`：**新增 `plan:3` Node**——label「选择能力与工具」；skill=None（编排节点 skill 走 Step ref）；artifact="plan.md"；gate_mech=ARTIFACT_EXISTS（声明式，机械门未实现现状见 §3/§5 #9）；gate_rubric=None；advance="phase"；`sub_steps`（6 个 Step）+ `_CTS_STEP1_FORM_REQUIREMENTS` 等形式要件常量（单源）；`minor_key="CapabilityToolSelection"`；hold_for_gate=True；artifact_on_release=False。**plan:2 改 advance="phase"→"sub"**（不再是 plan 末子阶段）——连锁检查其 hold 语义注释/测试断言。**存量工作流迁移**：旧 state 在 plan:2 无 sub_step 兼容问题（v2.19 已编排），但 advance 变更影响在途实例——单人维护可接受，迁移 = `/dl jump plan` 重置或手改 state.json
2. `hooks/workflow_phase.py` `_format_injection`：**预期无需改**（子阶段标签/子步骤清单从 engine 推导）——走查④：确认 artifact_on_release 分支对 advance="sub" 的 plan:2 不产出错文案；冒烟验证注入含「子阶段: 选择能力与工具 [3/3]」+ 6 步骨架链
3. `scripts/workflow/phase-rules.md`：plan 段加 plan:3 的 GENERATED 标记段 + 静态强制语义（evidence 是 STEP_DONE 前置/输完即 end_turn/子6 装配 plan.md 能力节义务/门栏扣留等 /dl gate + 放行后 PHASE_DONE 撞大闸门）
4. `skills/workflow-creation/SKILL.md` + `references/node-design.md`：§0 摘要块更新——门栏六处（understand:2/3/4 + plan:1/2/3）+ plan:3 6 步摘要段（含关键不对称第七种 + plan:2 advance 变更说明）；§3.8 关键不对称表加第七行（CapabilityToolSelection=有限枚举 × 配置接地）；「改 engine Step.purpose 实质内容后须手工同步摘要块」纪律适用
5. `tests/test_dl_flow_engine.py`：plan:3 新 Step 定义测例（6 步数/各 gate 含关键判据/子1/2/4 fence_allow=("Bash",)/子3 fence_allow=("Agent",)/子6 gate=None/selfcheck 无质量判据泄漏钉死/hold_for_gate=True/minor_key=CapabilityToolSelection/gate_rubric=None/artifact_on_release=False）；**plan:2 advance 改 sub 的连锁断言更新**（「末子阶段」假设全仓 grep：tests/hooks/docs/phase-rules）；排他性/唯一性断言全量遍历 `_NODES`
6. 冒烟：真实 state 直调 `_format_injection` + `render-phase-rules`（不开会话）；真实 TTY 跑一轮验证——plan:2 放行后自动续轮进 plan:3 子1、子2 注册表逐字出处留痕、子3 双向追溯矩阵+不加载清单、子4 三态标注、子6 plan.md 能力节装配落地、门栏扣留 + /dl gate 放行 + PHASE_DONE 撞 plan->execute 大闸门、推进 execute:0 后注入正确显示；**plan:2/plan:3 各三态覆盖**（走查④）

## 7. 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| 1 | 幽灵能力（训练记忆冒充注册表条目——本节点最高危失效） | 子2 逐字出处强制 + gate 黑盒「与出处不符判 block」+ 子5「幽灵回潮判 block」双保险 + §4 ghost invocation 实证进 purpose |
| 2 | 过度配置（「以防万一」全挂上——过载是准确率坍塌主因） | 子3 最小集判据「无绑定 = 不加载」+ 子5 显式不加载清单 + gate 黑盒「无绑定能力残留判 block」 |
| 3 | 漏配强制项（H15/TDD 触发未核对 → execute 期被 hook 阻断返工） | 子2 强制路由逐任务核对形式要件 + gate 黑盒漏配判 block |
| 4 | 凭名字猜功能绑定错对象（distractor tool 式错配） | 子3 覆盖判据须引用 trigger 原文 + gate 黑盒「绑定理由无出处判 block」 |
| 5 | 环境不可用（注册表有 ≠ 跑得动） | 子4 Bash 实测 + 三态标注 + gate 黑盒「无差别已验证判 block」 |
| 6 | 需求失真（绑定脱离 plan.md） | 子1 任务 ID 基线 + 原文引用进 trace（judge 输入面）+ 子3 双向追溯矩阵 |
| 7 | 重型手段滥用（Workflow/扇出不相称） | 子3 成本相称辩护 + fence_allow=("Agent",) 合法通道 + 用户子6 拍板兜底 |
| 8 | 子6 无 judge，能力节缺漏无人拦（注意机械门未实现，ARTIFACT_EXISTS 仅声明式） | 子5 judge 已验五字段（装配无新增内容可错）+ 子6 purpose 写死装配义务 + S13/S15 围栏 + 用户读回确认本身即质量门（plan:2 风险 #8 同构；机械门实现属 §8.3 独立项） |
| 9 | 弱遵从模型跳过盘点直接写映射（症状 P 抢答模式重演） | S15 前置参与围栏按 fence_allow 白名单物理拦截；S13 兜底纯 text 抢答 |
| 10 | 「内置工具足够」被滥用逃盘点（双结论被回避） | 子2 逐任务说明留痕是合法佐证路径；gate 黑盒「②无逐任务说明判 block」；用户子6 拍板兜底 |
| 11 | plan:2 advance 改 sub 引入回归（在途实例/fixture 假设） | 机制走查①②已确认先例覆盖；fixture 全仓 grep「末子阶段」；存量迁移 = /dl jump plan 重置 |
