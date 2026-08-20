# plan:4 子1（四源清点与追溯基线）耗时/token 优化设计——Step strip + Node 工具白名单 + 复用钉死③型（三源定点）

> 日期：2026-08-20 · 分支 feat/p4-sub1-cost · 状态：设计中
> 上游：designs/p3-sub1-cost-optimization-design.md（清点型首步优化范式，
>      本设计=该文档「遗留立项：plan:4 Node 工具白名单与子1 同型复用钉死
>      （清点型步同族）」的兑现）；cost-optimization #23/#25/#26/#29/#30/
>      #33/#35/#37/#38/#43。
> 触发 = 用户指令（2026-08-20）：「优化 plan:4 的 step1，耗时和 token 消耗
> 要大幅降低，能用前面步骤沉淀下来的 discovered 和 evidence 就尽量用，
> 避免 factor 化；跑测试工作流用 ac-deepseek1；amplitude 今日值 4929.2%」。
> 数值口径：种子 problem_statement 保持 4824.5% 不改（runtime-audit #25：
> 数值漂移属 #18 混淆面）；4929.2% = 今日实际值，若运行中被问以此作答。
> 避免 factor 化 = cost-optimization #2（全部杠杆为框架通用机制/通用措辞，
> 零项目语义耦合——禁把测试实例的因子名/文件面/数值写进引擎条款）。

## 0. 范围声明

本设计只覆盖 **plan:4 子1（四源清点与追溯基线，非交互 tool 步）**。
段链不动：子1 是跨节点链头恒 fresh spawn（_chain_resume_sid 要求
chain.node==当前节点且 last_step==cur-1；进入 plan:4#1 时链属 plan:3
恒失配——与 plan:2#1/plan:3#1 同型；p2_sub3_ab 基线实锤：子1 段新 sid
23e5b1c4、首调 cr=0），链税与子1 无关。plan:4 链内步（子2-4）的断链/
strip 重审属后续立项，不在本设计。
并行约束：feat/p3-sub5-cost 在飞（步级断链第五例 ("plan:3",5) + 子5
strip 第十七例），本分支从 main（2666dea）切出，逐文件改动面（plan:4
Node/子1 Step/两个测试文件）与其错位；收口并轨点=strip 例数注释（彼十七
此十八）+ cost-optimization 编号（收口时 git log 最大值+1）+
test_other_nodes_zero_change 豁免集（加 plan:4）。

## 1. 前置勘察（2026-08-20，已完成的只读审计）

- **免跑基线（#30，第五例）= p2_sub3_ab 实例 plan:4#1 段**（2026-08-20
  15:54 实跑，ac-deepseek1/deepseek-v4-flash headless，session 23e5b1c4
  链头 fresh spawn）。三查：
  ①目标步代码两轮间零变更——该轮 launcher=feat/p2-sub3-cost worktree
  （80de063），`git diff 80de063..main` 对 plan:4/EPC/四源/epc_ 关键词
  零命中（nodes.py 174 行变更全在 plan:3 域）、engine 26 行全为 plan:3
  SKIP_STEPS 注释与条目、dl_drive.py/phase-rules.md 零 diff——plan:4#1
  可见面（purpose/gate/mech/交接包装配/spawn 前缀）A 轮码与 main 逐字
  相同 ✓；
  ②种子 evidence——B 轮直接以 p2_sub3_ab 自身 evidence 裁 ≤plan:3#6
  confirm（40 条，剔 plan:4 两条 trace）为种子，前序 trace 与 A 轮子1
  实际消费的前序 trace 同一份逐字相同（三查②最强形态，#38 补）✓；
  ③段口径——A 段=跨节点链头 fresh spawn（新 sid、首调 cr=0 实锤），
  B 轮同形态 ✓。
- **置位现状**：plan:4 Node 零 segment_tools、子1 零 strip/pack——plan
  族四节点中 plan:4 是唯一仍无 Node 白名单的节点（plan:1/2/3 已置位）。
- **交接包冒烟（p3_sub5_ab 同种子位形生产包渲染，38,948 字符）**：
  前序七节点「归一化+读回」trace 全文在包（含 plan:1 子5/子6、plan:2
  子4/子5、plan:3 子5/子6——input 契约的「evidence plan:1/2/3 末步
  trace」逐字在包）+「已装配产物」节列三个产物文件绝对路径指针
  （understands/<name>.md / plans/<name>.md / designs/<name>-design.md）。
  → 源④（evidence plan trace）材料 100% 在包；**三个产物文件 = 权威
  出处源**（gate 形式要件：源文件+行号 / 『原文』引用）在包外 → #38
  判别问句答案 = 条款第三型（定点一次），三文件变体。
- **A 轮门控**：evidence 无 block 记录、gate 过后直接推进子2（chain
  last_step=1）= 一次通过零 block。

## 1.5 基线实测（A = p2_sub3_ab plan:4#1 段，免跑基线）

| 指标 | A（p2_sub3_ab seg 23e5b1c4 首段） |
|---|---|
| 首调 fresh | 58,145（cr=0——fresh spawn 符合跨节点链头预期） |
| 段 fresh 合计（inputTokens，result modelUsage 权威口径） | 145,073 |
| 段 cr 合计 | 2,571,008 |
| 段 out 合计 | 36,693 |
| 轮数（result 权威值） | **31** |
| 段 dur_api | 252.8s |
| 工具调用 | 30（Bash×23/Read×5/Write×1/Edit×1） |
| 门控 | 一次通过（零 block）、append-trace 零 mech 拒 |
| 成本等效（fresh+cr×0.1） | 402,174 |

### 浪费分解（30 调用逐条归因，runtime-audit #26 三分诊）

| 浪费类 | 调用 | 定性 |
|---|---|---|
| 产物路径猎捕 | #1-13（ls/find/grep ×13 定位 design.md——`.claude/designs/` 不存在、grep evidence 找路径、全仓 find） | **纯税**——「已装配产物」节绝对路径指针就在交接包内，弱模型不信任指针先猎捕（#43 方差面=油水） |
| 三源文件 Read | #14-16（design/plan/understand 各一次） | **合法本步职责**（权威出处源取行号+原文，③型定点一次） |
| evidence 翻找 | #17-23（grep 计数×1+python 解析×5+ls/gate 状态×1） | **纯税**——plan:1/2/3 末步 trace 逐字在交接包（ref 旧通道「Bash(grep evidence plan:1/2/3 trace)」是诱因，p2-sub1/p3-sub1 同型） |
| 交付通道 | #24-28（scaffold/Read 骨架/Write/Edit/append） | 合法（Write+Edit=单轮方差，非 mech 拒） |
| 交付后徘徊 | #29-30（grep phase-rules 红队阈值+find writing-plans/executing-plans SKILL.md=预习子2） | **纯税**——交付即止（#37）+「为后续步预取材料」越界（#27 行为面变体：Bash 迂回形态）直击 |

**三层瓶颈分诊（#1/#20/#23）**：①段边界层：链头恒 fresh 无链税；
②前缀层（主税一）：首调 58,145 = 工具 schema 25 个 ~14.3k + 项目上下文
~11.9k 两个可裁分量未剥（plan:4 是 plan 族唯一无白名单节点）+ 交接包
~39k 字符 + harness/node-rules；
③步体层（主税二）：30 调用中 22 纯税/徘徊（路径猎捕 13+evidence 7+
徘徊 2），cr 2.57M = 31 轮 × 单调涨上下文。

## 2. 杠杆选型

| 杠杆 | 置位？ | 依据 |
|---|---|---|
| **L1 Step 级 segment_strip_project_context 置位 plan:4 子1**（第十八例——p3-sub5-cost 在飞占第十七，merge 复核） | **置位** | #23 两核对+u3-sub1 第三核对：①交付物=五类清单+源出处+四源原文引用——五类清单逐字在 _EPC_STEP1_FORM_REQUIREMENTS 自给，「改 .py=H15 触发信号」是 gate 合法正例内标签非规则正文引用职责，交付物正文零引用 CLAUDE.md/auto-memory 内容；②逐步工具需求=Bash（scaffold/落库）+Read（三源文件/骨架）+Edit（骨架）——全在 L2 白名单内；③gate 判材=judge 读裁剪 trace 不读项目上下文。Node 级 env 剥离不下放（子2-4 逐步核对未做，p3-sub1 同处置） |
| **L2 Node 级 segment_tools 白名单（plan:4 首例）** | **置位** | 逐步核对（五步）：子1=Bash+Read+Edit；子2=Skill（writing-plans/executing-plans 对齐源 ref 在册）+Agent（条件红队 fence_allow 在册）+Bash+Read+Edit；子3=Bash（dry-run/交集实算/codegraph）+Read+Edit；子4=Skill（define-problem 归一化）+Bash+Read+Edit；子5=tier=confirm（P3-1）无模型会话。→ ("Bash","Read","Edit","Skill","Agent")，无 Grep（ref 未点名，plan:3 同款先例）。顺带机制堵 #27 预取越界的 Agent 通道形态（A 轮徘徊是 Bash 迂回形态，由 L3 条款收口） |
| **L3 复用钉死条款进 purpose/selfcheck/ref（#38 第三型「定点一次」三源变体）** | **置位** | 用户决议「能用前序沉淀的 discovered/evidence 就尽量用」。形态判别（#38 判别问句）：gate 出处要件钉死包外三文件行号/原文 → ③型。测量型取舍（#29）：清点对象是已拍板产物文件非环境现状，无新鲜度例外。ref 改（旧通道 grep evidence 是翻找诱因）：`Read(三产物文件定点各一次，指针直达) / 交接包前序留痕（免 evidence 翻找）` |
| **L4 交付即止（#37）+ 格式真源（#26）补款** | **置位** | 平移条款——A 轮交付后徘徊 2 调用实锤（非纯方差防守），格式猎捕本步基线未见=方差防守（p3-sub1 同定位） |
| pack_self_contained | 不置位 | #38 判别：权威出处源=三个包外产物文件，行号/原文引用须各 Read 一次——材料非 100% 在包（p3-sub1 同判） |
| 段链/断链 | 不动 | 子1 跨节点链头恒 fresh spawn，无链税（§0） |
| Node 级 env strip | 不置 | 子2-4 逐步核对未做（p3-sub1 同处置） |
| MERGED 段内续步 | 不立项 | 步体非极小搬运型+deepseek 续步暖率彩票两节点 EV 证伪（#24，p1-sub1/p2-sub1/p3-sub1 同结论） |
| gate 文本 | 零变更 | 见 §2.1 三查 |

### 2.1 gate 零变更前置核对三件套（#29 程序）

①mech 词表：epc_quote_trace 扫「引用代码符号形（.py）却无『』/『原文』」
——复用钉死后三源文件仍各 Read 一次取『原文』引用、交接包留痕引用
携带『…』逐字片段，引用形态不变化，不新增命中面。✓
②judge 方框一合法形态=「源文件+行号 / 『原文』引用 任一在场」、判材
边界已钉「evidence 是一个源…引用了 evidence 任一 plan trace 即合规」
——复用引用形态（「复用 <节点>子N 留痕：<出处逐字>」携带『…』原文）
落在合法形态内；判材边界段已钉「不得以未见四源原文/无法核对出处行号
真实性为由 block」。✓
③复用引用形态不命中任何现存 block 条件：方框一(a) 全清单裸=无出处无
原文——复用引用有明确出处标记+原文片段，形态对立。✓
→ gate 文本零变更，零重放回归负担（p3-sub1 同结论同程序）。

## 3. 改法（dl_flow_nodes.py / tests / 同步件）

### L1 机制

plan:4 子1 Step 加 `segment_strip_project_context=True`（第十八例）。

### L2 机制

plan:4 Node 加 `segment_tools=("Bash", "Read", "Edit", "Skill", "Agent")`
（plan:4 首例，注释登记逐步核对结论）。

### L3/L4 条款（purpose 追加；selfcheck 补一条；ref 改）

purpose 末追加（通用措辞，零项目语义；镜像 plan:3 子1 条款 s/plan.md/
三产物文件/）：

> 材料边界（复用钉死）：交接包已载前序节点归一化留痕与读回 trace 全文
> ——evidence 第四源（plan:1/2/3 末步 trace）逐字在包，直接引用即合法
> （「复用 <节点>子N 留痕：<出处逐字>」形态），零 evidence 全量翻找
> （grep evidence 通道退役）。design.md/plan.md/understand.md 三个产物
> 文件 = 本步权威出处源：按交接包「已装配产物」节绝对路径指针定点
> Read 各一次取行号与『原文』引用，读后零重读——指针直达，禁 ls/find/
> grep locate 产物路径（路径已在包内）。枚举例外（逐条二值判定）：包内
> 留痕与产物文件内容不一致时以产物文件为准（拍板后产物），该不一致项
> 单点核对一次即止。
> 交付即止：落库成功（✓ 已落库）即结束本轮——禁 locate 产物/读 state/
> grep evidence 确认落库/预习下一步（含红队阈值/后续步 skill 查探），
> 推进与门控由外部 driver 判定。
> 载荷格式的唯一真源 = --scaffold 骨架+append-trace 报错文案——禁读引擎/
> 测试源码/历史 trace 反推格式；被拒按报错文案逐字修即可。

selfcheck 追加：「四源材料从交接包留痕/产物定点 Read 直接引用了吗？
三文件各只 Read 一次吗？零 evidence 翻找/零路径 locate 吗？」

**组织形态核对（#35）**：条款无圈码枚举（「枚举例外」是二值判定非
①-⑤ 列表），不会被镜像成载荷组织结构；epc_quote_trace 扫『』存在性，
条款不改变 q/a 组织。✓

### 同步件

- tests/test_dl_flow_engine.py：test_p4_node_tools_whitelist（白名单置位
  pin）+ test_p4_step1_step_level_strip（env 双开关+白名单继承）+
  test_p4_step1_reuse_clause_pinned（条款关键词 pin+ref 形态）+
  test_p4_other_steps_no_step_strip（兄弟步零行为变化）+
  test_other_nodes_zero_change 豁免集加 plan:4。
- skills/workflow-creation/references/nodes-index.md plan:4 行子1 摘要。
- skills/workflow-creation/references/cost-optimization.md：收口沉淀
  （编号取收口时 git log 最大值+1，防并行抢占）。

## 4. 预登记（B vs A，验收口径）

预期（机制确定性部分）：首调 fresh 58,145 → ~32-33k（strip -11.9k
[多处同口径实证值]+工具白名单 25→5 ~-13.5k [u2-residual-cost 探针口径]；
包同尺寸）;段 fresh/cr 主降因=轮数 31→~10 × 每轮前缀降+路径猎捕/
翻找/徘徊 22 调用清零。

| 指标 | A 基线 | B 预登记 | 判别 |
|---|---|---|---|
| 首调 fresh | 58,145 | **≤34,000**（-42% 起——机制读数） | L1+L2 |
| 段 cr 合计 | 2,571,008 | **-75% 起**（轮数 31→~10 × 前缀降+纯税调用清零） | 主驱动 |
| 成本等效 | 402,174 | **-60% 起** | 主验收轴 |
| 轮数 | 31 | **≤12**（理想最小形态：Read×3 源文件→scaffold→Read 骨架→Edit→append ≈ 7-10 调用） | L3+L4 |
| 工具调用 | 30 | ≤12（纯税 22 清零；合法核心 8 保留） | L3 |
| 段 out | 36,693 | ≤69.7k（#33 复用钉死 thinking 放大 1.9× 报价=上限非点估计；本步引用要件原已在形式要件内，预计放大有限——p3-sub1 实测 -18.2% 同族） | 双轴登记 |
| 段 dur_api | 252.8s | out÷rate 拟合归因，与 token 轴分开登记（#30） | 双轴登记 |
| 门控 | 一次通过零 block | **零 block** | 硬约束 |

trace 质量逐条自查（防 Goodhart）：五类清单齐备/每条附源出处+四源原文
『』引用/triggered 验收项显式标注/新增候选显式标注或显式「无」/q,a 按序
对齐/只提取不创作/零编造——按 gate 方框逐条自查 B 轮 trace。复用引用
不得稀释执行接地（清单条目仍条条有出处，只是 evidence 源出处生产时间
前移到交接包留痕）。

混淆声明（预登记）：①A/B 均 fresh 段（链头），无链形态差；②A=免跑
基线与 B 同种子 evidence 逐字同源，包差异=实例名替换（p2_sub3_ab→
p4_sub1_ab，逐字符等量）；③种子数值 4824.5% 与今日值 4929.2% 漂移
属 #18，两轮同种子同漂移面——子1 清点对象=已拍板产物文件非因子数值
现状，预计不触发（若模型被问以 4929.2% 作答）；④A 轮 launcher=p2-sub3
-cost worktree（80de063）与 B 轮码的 plan:4#1 可见面逐字差=本设计落地
件（三查① diff 零命中已核）；⑤Node 白名单（-13.5k）与 strip（-11.9k）
是本设计落地件，非外部漂移；⑥p3-sub5-cost 在飞：其 ("plan:3",5) skip
未入任何一臂=两臂链政策一致，且子1 链头不受链政策影响；⑦B 轮驱动只跑
子1 一段——gate 裁决落盘后看护器杀 driver+段进程（连带 pkill 段孤儿，
p1-sub5-cost 教训），子2 起链段不计入账面（登记为驱动工件）。

## 5. 实测收官（2026-08-20，A=p2_sub3_ab plan:4#1 链头段[免跑基线第五例] / B=p4_sub1_ab 同种子 evidence 裁 ≤plan:3#6[40 条]，ac-deepseek1/deepseek-v4-flash headless，一轮 A/B 全验收）

B 轮驱动法（runtime-audit #24/#25）：种子五件套（evidence 裁 ≤plan:3#6
confirm[40 条剔 plan:4 两条] + ljt 去 plan:4#1 键 + 段记录/链回滚
[chain={plan:3,c5da3a1f,last_step=5}=有机参照 p3_sub5_ab 同位形逐字段
对齐] + state 四字段 + settings/node-rules 名替换）+ 产物三件（plans/
understands/designs cp 改名）+ 实例 worktree wf/p4_sub1_ab → 包冒烟
37,061 字符（三产物指针改名在列/plan:3 归一化 statements 在包/零名泄漏）
→ `bash -ic` 内 `AC_WORKFLOW_LAUNCHER=<worktree>/scripts/workflow/
dl-launch.sh ac-deepseek1 --dl p4_sub1_ab --resume --headless` → plan:4#1
gate 通过后看护器杀 driver+段进程（子2 链段零 trace 落库即被杀——比
p3-sub1 干净的收段）。

| 指标 | A（免跑基线） | B（三杠杆） | B vs A | 预登记 | 验收 |
|---|---|---|---|---|---|
| 首调 fresh | 58,145（cr=0） | 27,953（cr=0） | **-51.9%** | ≤34,000 | ✓ 超（三分量命中：strip -11.9k+白名单 25→5 -13.5k≈-25.4k 实测 -30.2k，余=包差+方差） |
| 段 fresh 合计 | 145,073 | 94,088 | **-35.1%** | — | ✓ |
| 段 cr 合计 | 2,571,008 | 220,160 | **-91.4%** | -75% 起 | ✓ 超（纯税 22 调用清零主驱动） |
| 成本等效（fresh+cr×0.1） | 402,174 | 116,104 | **-71.1%** | -60% 起 | ✓ 超，主验收轴 |
| 轮数（result 权威值） | 31 | 8 | **-74.2%** | ≤12 | ✓ |
| 工具调用 | 30 | 7 | **-76.7%** | ≤12 | ✓ 理想最小形态 |
| 段 out 合计 | 36,693 | 18,884 | **-48.5%** | ≤69.7k（1.9× 报价） | ✓ **无反噬**（报价未触发=上限口径，#33 不改） |
| 段 dur_api | 252.8s | 124.5s | **-50.8%** | out÷rate 登记 | ✓ 双轴同降（速率 A 145/B 152 tok/s 稳定，out 降+轮数降叠加） |
| 成本 | $2.928 | $1.053 | **-64.0%** | — | ✓ |
| append-trace mech 拒 | 0 | **0**（scaffold+一次落库） | | | ✓ |
| 门控 | 一次通过零 block | **零 block 一次通过**（ljt plan:4#1 落账即推进） | | 零 block | ✓ |

**B 工具序列（理想最小形态）**：Read understand.md（指针直达）→ Read
plan.md（指针直达）→ Read design.md（指针直达）→ scaffold → Read 骨架
→ Edit → append 一次过 = 7 调用。零 ls/find/grep locate（A 轮路径猎捕
13 调用清零）、零 evidence 翻找（A 轮 7 调用清零）、零交付后徘徊（A 轮
2 调用清零——工具序列止于落库，交付即止生效）。

**机制生效实证**：①init 事件 tools=['Task','Bash','Edit','Read','Skill']
= L2 白名单落地（Task=Agent 映射，u1-prefix-strip 口径）；②首调 -30.2k
≈ strip -11.9k + 工具 schema -13.5k + 包差/方差 = L1/L2 落地（B1/B2 双样
本首调同为 27,953±0=机制读数稳定）；③trace q6 自述「三文件各只 Read
一次/零 evidence 翻找/零路径 locate」+ q1-q5 「复用 TaskBreakdown 子4
留痕」「复用 CapabilityToolSelection 子5 留痕」形态在正文 = L3 条款落地。

**trace 质量逐条自查（防 Goodhart）**：五类清单齐备（①U1-U5 任务 DAG
附 plan.md:5-11 行号+原文/②能力绑定 10 条附 plan.md:13-24/③验收包
SC-G1/G2/G3 附 understand.md:53-57+triggered 显式标注×6/④假设 11 条附
design.md 行号+plan.md H-1/2/3 传导/⑤不可逆候选逐项二值判定）；行号
引用密度 plan.md×41+understand.md×13+design.md×11+『』原文×6；新增
候选显式「无」+枚举例外逐条判定；q,a 按序对齐（6 对）；只提取不创作、
零编造——执行接地零稀释（引用密度反升：A 轮猎捕噪音位置被出处引用
取代）✓。

**out 无反噬归因（#44 零触发形态第三例）**：复用钉死的引用义务替代的是
A 轮猎捕/翻找的命令回显与推理叙述厚度（留痕义务总量不变），条款净增量
≈0 时 out 不放大（p3-sub1 -18.2%/p3-sub4 +2.4% 同族）。

**B1 污染轮登记（驱动工件，不入账）**：首轮种子组装脚本 bug——
`open(p,'w').write(open(p).read().replace(...))` 求值顺序先截断后读，
plans/p4_sub1_ab.md 落 0 字节；B1 模型按枚举例外条款单点核对一次后回落
包内留痕（「以产物文件为准→产物为空→改引交接包留痕」），条款在对抗性
种子下行为正确（枚举例外通道顺带实证有效），门控一次通过；但 B1 trace
形态（①②类引留痕非 plan.md 行号）≠ 干净种子形态，读数剔出对比面，
种子重组装后 B2 为上表读数。**种子八件套族补件：产物文件改名必须
「先读后写」分两句**（open(p,'w') 先求值截断陷阱）。

**混淆声明复盘**：①A/B 均 fresh 段（链头 cr=0 双实锤）无链形态差；
②种子 evidence 逐字同源、包差异=实例名替换；③amplitude 今日值 4929.2%
vs 种子 4824.5% 漂移=#18 未触发（子1 清点对象=已拍板产物文件，B 轮零
因子数值询问）；④A 轮 launcher=80de063 与 main 的 plan:4#1 可见面逐字
相同（三查① diff 零命中）；⑤白名单/strip 是本设计落地件非外部漂移；
⑥p3-sub5-cost 在飞，两臂链政策一致且子1 链头不受链政策影响；⑦子2 链段
零 trace 落库即被杀=驱动工件不计账。

**pytest**：1211 全绿（新增 4 例：Node 白名单 pin/子1 strip 生效面/复用
条款 pin/兄弟步零行为变化；test_other_nodes_zero_change 豁免集加
plan:4）。

## 6. 遗留立项

- plan:4 链内步（子2-4）strip/断链重审（逐步核对未做；子2 红队步、子3
  锚点核验步、子4 归一化步形态各异，逐步过判别问句）；
- A 轮暴露的「产物路径指针不信任」形态（13 调用猎捕）——本设计 L3 条款
  直击，若 B 轮仍复发则升级机制面（指针进段 prompt 逐字渲染已在做，
  备选=形式要件内联路径）；
- 输出侧瘦身（观察项，与 p1-sub1/p2-sub1/p3-sub1 同处置）。
