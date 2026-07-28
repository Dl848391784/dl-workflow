# plan:1「设计解决方案」子步骤编排设计（DesignSolution）

> 状态：**已确认**（2026-07-27 用户两连决议：①初版 5 步（理论方案空间）被批评「编程工作流不能只理论，要结合项目代码做代码设计方案」→ 重分析失效模式，加独立现状勘察步，定稿 **6 步（代码级）**；②**加 hold_for_gate**（隔离测试语义，同 understand:3/4 先例）；③红队**条件触发**；④撤销子2 放开 WebSearch 的待决项——候选从代码地形生长后外部模式刺激价值大降，且设计正典是项目硬规则而非业界实践）
> 父文档：`node-step-orchestration-design.md`（子步骤编排机制）、`understand-subphases-design.md`（子阶段机制，「plan 等阶段以后可扩展，无需重设计」的兑现）、`success-criteria-substeps-design.md`（最近范式 + 消费契约倒推锚点法）、`scope-and-constraints-substeps-design.md`（本地单层源压缩原则）、`step3-verify-redesign-design.md`（codegraph 新鲜度前置机制）、`workflow-creation` SKILL.md §3.5（rubric 方法论）/ §3.8（拆步方法论）
> 外部取证：本文 §4（Tavily 检索，2026-07-27，设计期调研——用户明示允许；与运行期 understand:1 子3「禁 tavily/WebSearch」约束无关）

## 0. 背景

plan 阶段当前是单节点 `plan:0`「生成执行计划」（无子阶段、无编排，仅节点级 rubric「①步骤可执行 ②验证方法明确 ③守 H8/H9」在 plan->execute 大闸门跑一次 judge）。本设计把 plan 拆为两个子阶段：**plan:1 设计解决方案**（本文，6 步编排）+ **plan:2 生成执行计划**（原 plan:0 重编号，机制不变）——plan 阶段第一个编排节点，也是全工作流**首个创造性生成节点**。

输入 = understand.md 终态四件套：归一化问题陈述集（带 verdict 边界）+ 目标价值（must/nice 用户裁决）+ 范围双侧清单与约束集（已验证附出处/假设+置信度×影响）+ 成功标准验收包（指标/基线/阈值/方法/时机/证据形式）。
输出 = `designs/<主题>-design.md`（H8 产物：2+ 文件改动必须先有 design.md；`_phase_write_path_ok` 已放行 designs/*.md，S11 白名单无需改），供三个下游直接消费。

**消费契约锚点**（与 SuccessCriteria 同构的第一性原理锚点）：设计包字段倒推自三个下游消费方，不是拍的——

| 下游 | 其 rubric/职责 | 倒推出的设计包字段 |
|---|---|---|
| plan:2 生成执行计划 | 产出可执行步骤序列 | 改动清单（file→function→改动类型）+ H9 执行单元划分（每单元 ≤3 文件 ≤200 行）+ 被否方案（防重提） |
| execute:0 gate | 「对照 plan 步骤逐条核，偏离需有理由」 | 设计要素可追溯（每要素回溯 must 目标）+ 接口签名/数据契约变更（核对的基准） |
| review:0 gate | 「判定 solved/partial/not，附 file:line 证据」 | 验收包映射（每条 SuccessCriteria 验收包由哪个设计要素承接）+ 受影响 callers 清单（file:line 证据的锚点） |

**编程工作流定位**（用户 2026-07-27 批评沉淀，本设计的元约束）：候选方案不是问题空间的抽象路径（「用缓存 vs 用数据库」），是**解空间的代码设计**（「改 `dl_flow_nodes.py` 的 X 函数 vs 拆新模块 Y」）——必须从代码现实生长，产物必须是代码级改动清单。理论方案选型判不出「引用不存在的接口/无视现有实现重复造轮子」这种病，只有代码勘察能判。

## 1. 第一性原理

### 1.1 终态三属性（同构前四个节点）

| 属性 | 在本子阶段的含义 | 承担步骤 |
|---|---|---|
| 内容正确 | 方案锚定代码现实（接口存在/无重复造轮子/影响面已量化）；真实承接 must 目标；不违反已验证约束与项目硬规则；假设显式化 | 子1-4 |
| 形式可移植 | 归一化设计陈述携带代码设计包八字段，plan:2/execute/review 可直接消费；装配为 design.md（H8 产物） | 子5-6 |
| 用户认可 | 方案选型、评估权重、假设接受 = 规范裁决，归用户 | 子6 |

### 1.2 关键不对称（第五种）：创造性生成 × 代码接地**双轴心**

| 子阶段 | 命题性质 | 编排后果 |
|---|---|---|
| ProblemContext | 纯事实性 | 五层外部源取证 + 质检裁决双步 |
| GoalsAndValue | 纯规范性 | 无取证步 |
| ScopeAndConstraints | 混合：约束=事实性，范围=规范性，假设=中间态 | 约束本地单层源压缩验证一步 |
| SuccessCriteria | 混合，轴心=规范性目标的可检验化转换 | 新增可检验化独立步 |
| **DesignSolution** | **混合，成分全新**：方案生成=**创作**（对象不存在于任何状态）；可行性=事实性（**本仓代码事实**，本地单层源）；选型/权重=规范性；假设=中间态 | 新增**现状勘察**独立步（前四节点都没有——它们处理已存在的命题，本节点的对象须生成且须接地） |

双轴心的两个新失效源，前四节点都不面临：

- **创造性生成 → 设计固化（fixation）**：对象不存在，必须从「无」发散出「多」再收敛。LLM 首答即收敛正中实证最强的固化源（§4：对自己最初想法的固化比对外部示例的固化更严重）。防御 = 发散与收敛异族分步。
- **代码接地 → 凭空设计**：解必须锚定本仓现实。LLM 凭训练记忆描述代码结构是最强编造区（不存在的接口/凭印象的模块归属/漏检的重复实现）。防御 = 勘察独立步 + 出处强制。

### 1.3 失效模式分析

| # | 失效模式 | 外部出处（§4） |
|---|---|---|
| D1 | 凭空设计：不看代码就设计——引用不存在接口/无视现有实现重复造轮子/撞现有架构 | LLM 编程最强失效模式（本项目实证区）；「assumptions are not facts unless proven」 |
| D2 | 设计固化：只生成 1 个方案即承诺；或对约束钉死的任务硬编伪候选凑数 | Jansson & Smith 1991；Leahy et al.（自我固化更强）；Crilly 五因子之首「对最初想法的承诺」 |
| D3 | 方案-目标脱节：要素镀金 / must 目标无方案承接 | 双向可追溯（同构前四节点） |
| D4 | 不可行方案：撞已验证约束 / 违反 H1 模块边界 / H7 路径 / H9 可分解性 | INCOSE feasibility（沿用）；项目硬规则（PROJECT.md §硬规则） |
| D5 | 隐含假设：未记录未跟踪，事后才浮现 | 假设管理实证（Columbia 案例：决策「only emerge after system failure—we call them assumptions」）；Fairbanks 风险驱动模型 |
| D6 | 无依据收敛：不逐个对照判据比较就选定；单人设权重放大偏见 | Pugh concept selection（datum 相对比较）；权重偏见实证（weighted Pugh「amplifying individual bias if the weights are set by a single person」） |
| D7 | 决策理由丢失：被否方案+否决理由不记录 → execute/review 无法理解决策、decision thrash | ADR（Nygard/Fowler：alternatives considered + 否决理由；「make implicit knowledge explicit」「avoid decision thrash」） |
| D8 | 复合/去上下文不可移植陈述 | INCOSE atomic（沿用） |
| D9 | 模型越权拍板选型（规范裁决被代答） | 四桶分工（认不认归用户） |

**步数推导**（§3.8 #4，按失效模式族）：接地族（D1）→ 子1；发散族（D2）→ 子2；可行性+假设族（D4+D5，同族=本地单层源事实核验）→ 子3；收敛评估族（D3+D6）→ 子4；形式族（D7+D8）→ 子5；认可族（D9）→ 子6。**6 族 = 6 步**，异族拆开、同族合并。步数 6 与 ProblemContext 相同纯属巧合——ProblemContext 的 6 是外部五层源取证拆双步拆出来的，这里的 6 是「勘察（机械取证活）/发散（创造性活）」异族分离分出来的，各自独立推导。

## 2. 设计：6 步

```
子1 代码现状勘察 → 子2 方案发散 → 子3 可行性验证与假设标注 → 子4 评估收敛与选型提案 → 子5 归一化陈述 → 子6 读回确认与产物装配
```

judge 调用 5 次（子6 gate=None）。

### 子1 代码现状勘察（kind=tool）

- **ref**：`codegraph callers/impact / Read / Grep / Bash(新鲜度+数据契约)`
- **purpose**：建立**现状地图四要素**——①涉及模块与现有实现（问题落在哪些模块/函数，codegraph 定位 + Read 核实）；②可复用点与扩展点（已有可复用函数/类，禁凭印象）；③调用方与影响面（`codegraph callers/impact`）；④数据契约现状（paths.py/schema/跨模块数据格式，Bash/Read 核实）。**codegraph 新鲜度前置**（复用 ProblemContext 子3 机制）：`SELECT datetime(MAX(indexed_at)/1000,'unixepoch','+8 hours') FROM files;` >72h 先 `codegraph sync`。每条事实附 codegraph 原始输出或 file:line 出处；勘察不到的显式标「未知」，不编造。范围由 understand.md 问题陈述+范围清单框定，禁无界漫游。
- **input**：`understand.md（问题陈述+范围约束+成功标准）`
- **record**：True；**fence_allow**：`("Bash",)`（codegraph CLI/新鲜度查询/数据契约核实；Read/Grep 在常驻集）
- **gate**：trace 存在；形式要件（新鲜度检查留痕；四要素覆盖或显式「无+理由」；每条事实附出处；q/a 对齐）；质量判据黑盒（凭训练记忆描述代码结构无工具出处 = 编造判 block；引用不存在接口/模块判 block；勘察与 understand.md 范围明显脱节 = 漫游判 block）。

### 子2 方案发散（kind=tool）

- **ref**：`推理(架构维度变换) / AskUserQuestion(用户既有想法)`
- **purpose**：基于子1 现状地图生成 ≥3 个**代码级**候选方案——每个 = 具体技术路径（改哪个模块/哪个函数/新增什么文件/复用哪个现有实现，全部锚定子1 事实条目，禁凭空 API）；候选间须在**架构维度**上有实质差异（换模块归属/换数据结构/复用 vs 新建/换执行时机/换数据流），换皮不换骨 = 一个方案；**禁评估禁排序**（评估是子4 的事——混入 = 发散被收敛污染，fixation 防御核心）；用户既有想法走 AskUserQuestion 引出后**平权入列**（不预设首选——自我固化是最强固化源）。**双结论制**：①多候选成立；②「设计空间唯一」合法（约束钉死全部维度 = 只剩一个合理路径，如纯机械重命名），但须逐维度论证唯一性——防逼编造伪候选凑数（同 ProblemContext 子1 双结论制防编造痛点机制）。
- **input**：`step1.terrain_map`
- **record**：True；**fence_allow**：无（AskUserQuestion 在常驻集）
- **gate**：trace 存在；形式要件（≥3 候选或②逐维度唯一性论证；每候选锚定子1 事实条目；架构维度差异声明；无评估性措辞）；质量判据黑盒（伪候选 = 同一方案的措辞变体判 block；候选含子1 未证实的接口/模块 = 凭空设计判 block；提前收敛排序判 block；②无逐维度论证 = 偷懒判 block）。

### 子3 可行性验证与假设标注（kind=tool）

- **ref**：`codegraph / Bash / Read(接口存在性+影响面+重复实现)`
- **purpose**：对存活候选逐一做代码现实核验（本地单层源，沿用 ScopeAndConstraints 压缩原则，只标注不裁决）：①接口/模块存在性复核（候选引用的每个符号 file:line 核实）；②**重复造轮子检查**（codegraph 查同功能实现——有则候选改复用路径或标淘汰）；③影响面量化（`codegraph impact` 受影响 callers 数）；④项目硬规则兼容（H1/H1.1 模块边界、H7 路径只 `from paths import`、H8 2+文件需 design.md、H9 单次 ≤3 文件 ≤200 行可分解性、H11-H13）；⑤可测试性（TDD 前置：改动点是否存在可挂测试的接缝）。三态标注：**可行（附出处）/ 假设（置信度×错误时影响，如「该接口行为符合预期」未实测）/ 证伪剔除（附理由）**。
- **input**：`step2.candidates + step1.terrain_map`
- **record**：True；**fence_allow**：`("Bash",)`（codegraph/Read 在常驻集）
- **gate**：trace 存在；形式要件（每候选五项核验留痕；三态逐候选标注；出处/置信度×影响/理由齐备）；质量判据黑盒（声称存在无出处 = 编造判 block；影响面拍脑袋无 impact 输出判 block；全候选无差别「可行」= 没真核验判 block；重复实现漏检判 block）。

### 子4 评估收敛与选型提案（kind=tool）

- **ref**：`推理(Pugh 矩阵) / Agent(条件红队)`
- **purpose**：Pugh 矩阵收敛——判据 = 成功标准验收包指标承接度 + 改动面（文件数/行数估计，对 H9）+ 影响面（子3 callers 数）+ 复用度 + 可测试性 + 硬规则兼容，datum = 最小改动候选；逐格 +/S/− 附理由（理由须引用子3 核验事实，禁空泛）；**双向追溯**（每方案要素回溯 ≥1 must 目标防镀金；每 must 目标 ≥1 要素承接防漏）；**条件红队**（复用 ProblemContext 子4 机制，engine redteam-prompt 组装）：候选分差小或改动跨模块时，Agent 独立上下文攻击领先方案，触发/未触发均留痕；产出排序 + **推荐提案（只提案不拍板——权重与选型是用户风险偏好，Pugh 单人权重偏见实证）**。
- **input**：`step3.feasibility_verdicts`
- **record**：True；**fence_allow**：`("Agent",)`（同构 ProblemContext 子4）
- **gate**：trace 存在；形式要件（矩阵逐格评分+理由；理由引用子3 事实；双向追溯矩阵；红队触发/未触发留痕）；质量判据黑盒（评分理由空泛不引事实判 block；替用户拍板 = 无「提案-待裁决」语义判 block；矩阵结论与评分矛盾 = 凑结论判 block；追溯漏项判 block）。

### 子5 归一化陈述（kind=skill）

- **ref**：`define-problem`（claim normalization 职能第六次复用）
- **purpose**：对推荐方案产出归一化设计陈述——①原子（单句 ≤1 个独立设计决策）；②去上下文（主语+动词+约束自包含）；③携带**代码设计包八字段**：改动清单（file→function→改动类型：改/增/删）/ 接口签名 / 数据契约变更 / 受影响 callers 清单（codegraph 出处）/ 被否方案+逐项否决理由（ADR）/ 假设清单+置信度×影响 / 验收包映射（每条 SuccessCriteria 验收包由哪个设计要素承接）/ H9 执行单元划分；④携带 verdict 边界（部分成立目标只覆盖已证实边界——裁决传导）。放不进一句 = 未定义完。
- **input**：`step4.recommendation`
- **record**：True；**fence_allow**：无
- **gate**：trace 存在；形式要件（每项 ≤1 句且自包含；八字段齐备）；质量判据黑盒（设计包字段不传导——子3/子4 已定的出处/假设/否决理由在陈述中丢失或篡改判 block；复合句判 block；凭空新增子4 未评估的要素判 block）。

### 子6 读回确认与产物装配（kind=skill）

- **ref**：`define-problem / AskUserQuestion / Write(designs/*-design.md)`
- **purpose**：带证据读回：呈现推荐方案+设计包+被否方案+假设清单+不确定性；**用户三裁决**：①**选型拍板**（唯一规范裁决点——含复活被否方案的合法权利，矩阵只是输入）；②**评估权重认可**（Pugh 单人权重偏见防御）；③**假设接受**（风险承担，同构 ScopeAndConstraints 子5）；用户拍板后**装配 `designs/<主题>-design.md`**（H8 产物：内容 = 子5 归一化设计包 + 子6 裁决记录的直接装配，**禁二次创作**——同 understand.md 装配原则；S11 白名单已放行 designs/*.md）；写 trace 记裁决原话 → STEP_DONE。
- **input**：`step5.design_statements`
- **record**：True；**fence_allow**：无
- **gate**：None（交互步，trace 存在即过）

### 末子步骤过后：hold_for_gate 扣留（用户决议 2026-07-27）

子6 过门控后**无条件扣留**（state.held_for_gate），唯一出口 `/dl gate`——与 understand:2/3 同款**隔离测试**语义：plan 首个编排节点，跑完被围栏围住，用户验证编排本身没问题再放行进 plan:2。

**机制路径说明**：本节点是 `advance="sub"` 的 hold 节点，与 understand:2/3 完全同构——推进路径（末步 pass → 扣留 → subgate-pass → 推进 plan:2）已被 understand:2/3 的 pinning 测试覆盖，**无新机制路径**（不同于 SuccessCriteria 首个 `advance="phase"` hold 的新路径风险）。design.md 在子6 内装配完成（hold 前产物已落地），无 understand:4 的「放行后写产物」窗口依赖。

## 3. 门控设计要点（§3.5 对齐）

- **双结论制**（#3）：子2 接受「设计空间唯一」为合法结论（须逐维度论证）——否则逼模型编造伪候选凑数（同 ProblemContext 子1 逼编造痛点机制）。区分「诚实唯一解」vs「懒得发散」的判据是逐维度论证留痕。
- **Goodhart 分层**（#2）：形式要件（四要素覆盖/≥3 候选/五项核验/逐格评分/八字段/出处形式）披露进 purpose；质量判据（非编造/非伪候选/非空泛理由/非越权拍板/字段不传导）只留 gate 黑盒。
- **四桶分工**：现状勘察/方案生成/可行性核验/矩阵评估 = 模型（写什么）；trace 落库 = append-trace 脚本（怎么写）；结构完整性 = judge（过不过）；选型拍板/权重认可/假设接受 = 用户（认不认）。
- **judge 不判「哪个方案更好」**——只判「矩阵逐格有事实理由 + 只提案未拍板 + 追溯无漏」。方案优劣的真值源只有用户（子6）。
- **判据合法获取路径**（#7）：子1/子3 的出处要求有 fence_allow=("Bash",) + 常驻集 codegraph/Read——每条判据要求的佐证都存在低成本合法获取路径，不逼编造。
- **消费契约倒推**（本节点独有锚点）：设计包八字段倒推自 plan:2/execute:0/review:0 三个下游的 rubric 需求（§0 表）——缺任一字段，下游就得临时找补（plan:2 缺改动清单无法排步骤；execute 缺接口签名无核对基准；review 缺验收包映射无法判定）。
- **design.md 的产物强制路径**：ARTIFACT_EXISTS 机械门不支持含 `/` 的动态文件名（engine `run_gate` 对 `"/" in node.artifact` 报错），故本节点 gate_mech=NONE，产物强制走三层兜底——①子6 purpose 写死装配义务 + S13 参与围栏（无 trace 不许结束回合）；②子5 judge 已验设计包八字段（design.md 只是装配，无新增内容可错）；③plan->execute 大闸门 rubric 补④一致性检查（plan:2 节点 rubric 增强，见 §6 checklist #1）——**实现注（2026-07-27）**：④的措辞走 evidence 路径（「与 evidence/<name>.jsonl 里 minor_stage=DesignSolution 的设计包一致」），因为 `rubric_needs_evidence` 以 rubric 文本含 `evidence/` 或 `skill-trace` 为开关——含关键词 judge 才读得到设计包全文（design.md 文件本身 judge 读不到；§3.5 #7 判据合法性路径）。

## 4. 外部实证出处（2026-07-27 Tavily 取证留痕）

- **Design fixation**（Jansson & Smith, *Design Studies* 1991 开创性研究；Youmans & Arciszewski 2012 concept-based vs knowledge-based 二分；Crilly 访谈五因子——首因子「commitment to initially generated ideas」）：固化是工程设计普遍问题，表现为只考虑单一/极少想法。——子2 发散步独立存在的直接依据。
- **Fixation from self-generated ideas**（Leahy/Daly/McKilligan/Seifert, *Journal of Mechanical Design*）：「fixation from one's own initial idea may be an even bigger problem」——对**自己最初想法**的固化强于对外部示例的固化。LLM 首答即承诺正中此源——子2「禁评估禁排序」+ 用户既有想法「平权入列不预设首选」的直接依据。
- **Pugh concept selection**（Stuart Pugh，Total Design；Wikipedia/Burge Hughes Walsh 工具箱）：datum 基准相对比较（+/S/−）强制直接对比、降低绝对评分偏见；weighted 变体「amplifying individual bias if the weights are set by a single person」——子4 矩阵评估 + 权重裁决权归用户（子6 第二裁决点）的直接依据。
- **ADR**（Michael Nygard《Documenting Architecture Decisions》2011；martinfowler.com/bliki/ArchitectureDecisionRecord；adr.github.io）：决策记录四段式 Context/Decision/Consequences/**Alternatives Considered（含逐项否决理由）**；「make implicit knowledge explicit」「avoid decision thrash」——子5 设计包「被否方案+逐项否决理由」字段的直接依据。
- **假设管理**（Naz Delam, *The Danger of Assumptions in Software Architecture*）：Columbia 航天飞机案例——隐式决策「only emerge after system failure or inadequate performance. We call them, assumptions」；「Know that assumptions are not facts unless proven」——子3 假设三态标注 + 子6 假设接受裁决的直接依据。
- **风险驱动模型**（George Fairbanks, *Just Enough Software Architecture*）：设计投入应与项目风险相称——子4 红队**条件触发**（分差小/跨模块才烧 Agent）而非强制的直接依据。
- **本地单层源压缩原则**（沿用 `scope-and-constraints-substeps-design.md`）：可行性=本仓内部事实，codegraph/Bash/Read 单层可验，无「五层源过程质量」可判——子3 一步压缩、无独立质检裁决步。

## 5. 否决的替代方案（对抗性审视留痕）

1. **5 步版（无独立勘察步，初版方案）**——否（用户 2026-07-27 批评命中）：理论方案空间的候选判不出「引用不存在接口/重复造轮子」；勘察（机械取证活）与发散（创造性活）异族，合并稀释 judge 判力（同 SuccessCriteria 否决 4 步版逻辑）。本设计的 6 步就是对此批评的兑现。
2. **7 步版（子3 拆成取证+质检裁决双步，照抄 ProblemContext）**——否。本地单层源没有「五层源过程质量」可判，独立质检步判无可判 = 纯烧 judge（ScopeAndConstraints/SuccessCriteria 已两次否决同构方案）。
3. **子2 放开 WebSearch 作反固化刺激**——否（2026-07-27 用户决议撤销）：候选从代码地形生长后外部模式刺激价值大降；设计正典是项目硬规则（H/M 规则）而非业界实践；knowledge-based fixation（忽视其它领域知识）在本场景的风险远低于 concept-based fixation。
4. **红队强制每轮触发**——否。风险驱动模型：设计投入与风险相称。全量红队对「3 文件内小改动」类低风险设计是纯烧 Agent；条件触发判据（分差小/跨模块）写死进 purpose 披露。
5. **design.md 设 ARTIFACT_EXISTS 机械门**——否。文件名含主题词是动态的，机械门只支持固定文件名（engine `run_gate` 对含 `/` 的 artifact 报错）；改走 §3 三层兜底（purpose 义务 + 子5 judge 验八字段 + plan:2 大闸门 rubric 一致性检查）。
6. **hold_for_gate 不加**——否（2026-07-27 用户决议加）：与 understand:3/4 同款隔离测试语义；plan 首个编排节点，跑完扣留验证编排再放行。代价（多一次 /dl gate）已知情接受。

## 6. 实施 checklist（改编排必过，症状 M + §3.7）

1. `dl_flow_nodes.py`：新 `plan:1` Node（label="设计解决方案"，skill=None，artifact=None，gate_mech=NONE，gate_rubric=None，advance="sub"，minor_key="DesignSolution"，hold_for_gate=True，6 个 Step 定义含 short/purpose/input/record/gate/fence_allow/selfcheck）+ `_DS_STEP1_FORM_REQUIREMENTS` 等形式要件常量（单源：purpose 模型侧与 gate judge 侧都引用）；**原 `plan:0` 重编号为 `plan:2`**（label/artifact/gate_mech/advance 不变，gate_rubric 补「plan.md 步骤与 designs/*-design.md 设计包一致」）；sub_total("plan") 自动变 2（从 `_NODES` 推导，无需改函数）；minor_key_map/subphase_labels 自动收新节点。**存量工作流迁移**：在 plan 阶段且 sub_total=0 的旧 state 会因 `plan:0` 消失触发 get_node 报错暴露（no silent fallback 符合预期）——单人维护可接受，迁移 = `/dl jump plan` 重置或手改 state.json（sub_index∈{1,2}, sub_total=2）
2. `hooks/workflow_phase.py` `_format_injection`：**预期无需改**（子阶段标签/子步骤清单/minor_key 映射全部从 engine 推导）——冒烟验证注入含「子阶段: 设计解决方案 [1/2]」+ 6 步骨架链
3. `scripts/workflow/phase-rules.md`：plan 段加 plan:1 的 GENERATED 标记段（launcher 渲染自动同步 6 步 purpose）+ 静态强制语义（写 evidence 是 STEP_DONE 前置/输完即 end_turn/子6 装配 design.md 义务/门栏扣留等 /dl gate）
4. `skills/workflow-creation/SKILL.md`：§0 子步骤摘要（plan:1 6 步 + 门栏位置更新：understand:2/3/4 + plan:1 四门栏）+ §3.8 关键不对称表加第五行（DesignSolution=创造性生成×代码接地双轴心）+ §5 触发关键词速查补「设计方案/代码设计/方案发散」
5. `tests/test_dl_flow_engine.py`：新 Step 定义测例（6 步数/各 gate 含关键判据/子1+子3 fence_allow=("Bash",)/子4 fence_allow=("Agent",)/子6 gate=None/selfcheck 无质量判据泄漏钉死/hold_for_gate=True/minor_key=DesignSolution）；**fixture 迁移**——原「无编排节点」占位 plan:0 全量换 plan:2（症状 M #7：逐处 grep 别漏）；排他性/唯一性断言全量遍历 `_NODES`（禁抽样）；plan:1 hold 路径数据测例（机制已被 understand:2/3 pin 过，本节点只需 fixture 级覆盖）；plan:0→plan:2 重编号的全仓 grep（hooks/tests/docs 里对 "plan:0" 的引用）
6. 冒烟：真实 state 直调 `_format_injection` + `render-phase-rules`（§3 #10 法，不开会话）；真实 TTY 跑一轮验证——子1 codegraph 勘察留痕、子2 发散 ≥3 候选、子6 design.md 装配落地、门栏扣留 + /dl gate 放行、推进 plan:2 后注入正确显示「生成执行计划 [2/2]」

## 7. 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| 1 | 模型凭训练记忆编造代码结构（LLM 最强编造区：不存在的接口/凭印象的模块归属） | 子1 gate 黑盒「无 codegraph/file:line 出处判 block」+ 新鲜度前置 + selfcheck 逐项对照四要素 |
| 2 | 编造伪候选凑数（双结论②被回避，同一方案换措辞充 3 个） | 子2 双结论制 + judge 黑盒抓「措辞变体」；②唯一性须逐维度论证，论证留痕是合法佐证路径 |
| 3 | 子1 勘察变无界探查（漫游全仓烧 token） | purpose 写死「范围由 understand.md 框定」+ fence_allow 边界 + gate 黑盒「与范围脱节判 block」 |
| 4 | design.md 装配时二次创作（与归一化设计包脱节/丢字段） | 装配原则写死（禁二次创作，同 understand.md）；plan:2 大闸门 rubric 补一致性检查兜底 |
| 5 | plan:0→plan:2 重编号 breaking 存量工作流（get_node 报错） | 单人维护可接受 + get_node 报错暴露符合 no silent fallback + 迁移说明（§6 #1） |
| 6 | 红队滥用烧 Agent（每轮都触发） | 条件触发判据写死进 purpose（分差小/跨模块）；触发/未触发均留痕，judge 可核 |
| 7 | 子6 无 judge，design.md 缺漏无人拦 | 子5 judge 已验设计包八字段（装配无新增内容可错）；plan->execute 大闸门 rubric 兜底；用户读回确认本身就是质量门 |
| 8 | 弱遵从模型跳过勘察直接发散（症状 P 抢答模式在 plan 重演） | S15 前置参与围栏按 fence_allow 白名单物理拦截（子1 窗口只放行编排工具+Bash）；S13 兜底纯 text 抢答 |
