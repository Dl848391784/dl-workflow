# plan:3 子1（需求清点与追溯基线）耗时/token 优化设计——Step strip + Node 工具白名单 + 复用钉死③型

> 日期：2026-08-20 · 分支 feat/p3-sub1-cost · 状态：设计中
> 上游：designs/p2-sub1-cost-optimization-design.md（清点型首步优化范式，
>      本设计=该文档「遗留立项：plan:3/plan:4 Node 工具白名单与子1 同型
>      复用钉死（清点型步同族）」的兑现）；cost-optimization #23/#25/#26/
>      #29/#30/#33/#37/#38。
> 触发 = 用户指令（2026-08-20）：「优化 plan:3 的 step1，耗时和 token 消耗
> 要大幅降低，能用前面步骤沉淀下来的 discovered 和 evidence 就尽量用，
> 避免 factor 化；跑测试工作流用 ac-deepseek1；amplitude 今日值 4929.2%」。
> 数值口径：种子 problem_statement 保持 4824.5% 不改（runtime-audit #25：
> 数值漂移属 #18 混淆面）；4929.2% = 今日实际值，若运行中被问以此作答。
> 避免 factor 化 = cost-optimization #2（全部杠杆为框架通用机制/通用措辞，
> 零项目语义耦合）+ 每杠杆过各自判别问句（§2 逐条），非模板盲套。

## 0. 范围声明

本设计只覆盖 **plan:3 子1（需求清点与追溯基线）**。段链不动：子1 是
跨节点链头恒 fresh spawn（_chain_resume_sid 要求 chain.node==当前节点
且 last_step==cur-1；进入 plan:3#1 时链属 plan:2 恒失配——与 plan:2#1
同型；plan:2 且已出 SEGMENT_CHAIN_NODES），链税与子1 无关。plan:3 链内步
（子2-5）的断链重审属后续立项（基线同实例实测链内首调 104k/144k/185k/
**225k**，子5 已逼近 250k 护栏——见 §6 遗留），不在本设计。

## 1. 前置勘察（2026-08-20，已完成的只读审计）

- **免跑基线（#30）= p2_sub3_ab 实例 plan:3#1 段**（2026-08-20 15:5x 实跑，
  ac-deepseek1 headless，session c5da3a1f 链头 fresh spawn）。三查：
  ①目标步代码两轮间零变更——该轮 launcher=feat/p2-sub3-cost worktree，
  plan:3#1 Step 代码在 cbdf8ff/93029fa/80de063 三批全部零触碰（均 plan:2
  域），与本 worktree HEAD（80de063）逐字相同 ✓；②种子 evidence——B 轮
  直接以 p2_sub3_ab 自身 evidence（裁 ≤plan:2 子5）为种子，前序 trace 与
  A 轮逐字同源 ✓；③段口径——A 段=跨节点链头 fresh spawn（session 首段，
  首调 cr=0 实锤），B 轮同形态 ✓。
- **置位现状**：plan:3 Node 零 segment_tools、子1 零 strip/pack——plan 族
  四节点中 plan:3/plan:4 仍无 Node 白名单（plan:1/plan:2 已置位）。
- **交接包冒烟（p2_sub3_ab 生产实跑包，32,468 字符，transcript 直取）**：
  TaskBreakdown 子4 归一化 statements 五键（change_point/interface/verify/
  acceptance_map/trace_anchor）**全文在包** + 子5 confirm trace 在包 +
  「已装配产物」含 `.claude/plans/<name>.md` 指针（plans/ 本就在
  _PHASE_ARTIFACT_DIRS 扫描面，p2-sub1 的 L4 缺口本节点不存在）。
  → 子1 的「任务集+TaskBreakdown 留痕」材料 100% 可溯源包内；
  **plan.md = 权威出处源**（gate 形式要件：任务 ID+plan.md 行号 /
  『原文』引用）在包外 → #38 判别问句答案 = 条款第三型（定点一次）。
- **段链税背景（仅登记）**：同实例 plan:3 链内段子2-5 首调 fresh
  104,483/143,992/184,727/224,925（cr≈0 恒冷），单调涨携带税——子1
  是链头不受影响。

## 1.5 基线实测（A = p2_sub3_ab plan:3#1 段，免跑基线 #30）

| 指标 | A（p2_sub3_ab seg0） |
|---|---|
| 首调 fresh | 55,077（cr=0——fresh spawn 符合跨节点链头预期；与 p2_sub1_ab 基线 55,015 双实例互证机制读数） |
| 段 fresh 合计 | 87,953（result modelUsage 权威口径） |
| 段 cr 合计 | 721,024 |
| 段 out 合计 | 18,792 |
| 轮数（result 权威值） | 12 |
| 段 dur_api | 143.6s |
| 成本 | $1.270 |
| 工具序列 | Read×2 + Bash×7 + Edit×2 = 11 调用（+scaffold 内 1 = 12 事件位） |
| 门控 | 一次通过（judge PASS），零 block、零 mech 拒 |

### 成本归因（工具序列逐条核对，runtime-audit #26 三分诊）

| 类别 | 调用 | 判定 |
|---|---|---|
| Read plan.md 全量 | 1 | **合法本步职责**（权威出处源，取行号+原文引用——③型定点一次） |
| evidence grep TaskBreakdown ×2 + python 解析 evidence ×2 | 4 | **纯税**——子4 五键 statements 全文+子5 留痕已在交接包（L3 直击；ref 旧通道「grep evidence TaskBreakdown trace」是诱因，p2-sub1 同型） |
| 交付通道（scaffold/Read 骨架/Edit×2/append-trace） | 5 | 合法（Edit×2 = 单轮方差，非 mech 拒） |
| 落库后 python 解析 evidence 验证 ×1 | 1 | **纯税**——交付后徘徊（#37 交付即止直击） |

**三层瓶颈分诊（#1/#20/#23）**：①段边界层：子1 跨节点链头恒 fresh
spawn，无链税；②前缀层（主税一）：首调 55,077 = harness ~22.3k + 工具
schema 25 个 ~14.3k + 项目上下文 ~11.9k + 交接包 32,468 字符（~11k）——
项目上下文与工具 schema 两个可裁分量未剥（plan:3 是 plan 族剩余无
strip/无白名单节点之一）；③步体层（主税二）：11 调用中 5 纯税/徘徊
（evidence×4+交付后验证×1），cr 721k = 12 轮 × 单调涨上下文。

## 2. 方案（机制为主、文案为辅，零 factor 化）

### L1 Step 级 segment_strip_project_context 置位 plan:3 子1（第十三例）

置位前置核对（#23 两核对 + u3-sub1 第三核对「env 剥离边界」）：
- **交付物正文不引用自动加载文档**：子1 交付 = 逐任务操作类型清单 +
  任务 ID 出处 + plan.md 原文引用——操作类型六类标签逐字在 purpose
  形式要件（_CTS_STEP1_FORM_REQUIREMENTS）内自给，「改 .py=H15 触发信号」
  是标签非规则正文引用；无点名项目硬规则条号职责（强制路由核对归子2
  判面——**子2 交付物正文引 CLAUDE.md §2 触发词，故本杠杆只置 Step 级
  子1，Node 级 strip 明确不置**，u3-sub1 反优化同型规避）。
- **逐步工具需求**：Read（plan.md/scaffold 骨架）+ Bash（scaffold/落库）
  + Edit（骨架）——全在 L2 白名单内。
- **gate 判材**：judge 读 read_evidence_for_step 裁剪的 trace，不读项目
  上下文——剥 env 不影响判侧。
- 链内续跑段外部性：子1 链头恒 fresh spawn；子2-6 不置位（逐步核对未做），
  零行为变化。

### L2 Node 级 segment_tools 白名单（plan:3 首例）

逐步工具需求核对（六步）：
- 子1：Bash（scaffold/append-trace）+ Read（plan.md/骨架）+ Edit（骨架）。
- 子2：Read（CLAUDE.md §2/SKILL.md frontmatter）+ Bash（ls 技能目录/
  which codegraph/MCP 配置/scaffold/落库）+ Edit。
- 子3：**Agent（条件红队，fence_allow=("Agent",) 在册）**+ Bash（scaffold/
  落库）+ Read + Edit。
- 子4：Bash（skill 存在/CLI 可用/MCP 连接/环境前提核验 + scaffold/落库）
  + Read + Edit。
- 子5：**Skill（define-problem 归一化，ref 在册）**+ Bash（scaffold/落库）
  + Read + Edit。
- 子6：tier=confirm（P3-1）——无模型会话，无工具需求。

→ 白名单 = ("Bash", "Read", "Edit", "Skill", "Agent")。与 plan:1 差异=
**无 Grep**（ref 未点名，u:4/plan:2 白名单同款先例）。载荷通道：
--scaffold + Edit，零合法 Write（u2-residual-cost 先例）；MCP 由
NO_MCP_ARGS 结构封死（既有）。

### L3 复用钉死条款进 purpose/selfcheck/ref（#38 第三型「定点一次」）

**条款形态判别（#38 判别问句）**：本步 gate 出处要求钉死了包外文件的
行号/原文（「任务 ID+plan.md 行号 / 『原文』引用」）→ ③型（定点一次），
非①型（pack_self_contained）非②型（勘察例外）。测量型取舍（#29）：本步
无现状测量职责（清点对象是已拍板 plan.md，非环境现状），新鲜度类时效
例外不适用。

ref 改（旧通道「grep evidence TaskBreakdown trace」是翻找诱因，p2-sub1
同型处置）：
`Read(plan.md 定点一次) / 交接包前序留痕（免 evidence 翻找）`

purpose 末追加（通用措辞，零项目语义；镜像 plan:2 子1 条款 s/design.md/
plan.md/）：

> 材料边界（复用钉死）：交接包已载前序节点归一化留痕全文——任务集
> （TaskBreakdown 子4 归一化 statements 各字段）与子5 确认留痕逐字在包，
> 直接引用即合法（「复用 <节点>子N 留痕：<出处逐字>」形态），零 evidence
> 全量翻找（前序 trace 已在包内，grep evidence 通道退役）。plan.md =
> 本步权威出处源：定点 Read 一次取行号与『原文』引用，读后零重读。
> 枚举例外（逐条二值判定）：包内留痕与 plan.md 内容不一致时以 plan.md
> 为准（拍板后产物），该不一致项单点核对一次即止。
> 交付即止：落库成功（✓ 已落库）即结束本轮——禁 locate 产物/读 state/
> grep evidence 确认落库/预习下一步，推进与门控由外部 driver 判定。
> 载荷格式的唯一真源 = --scaffold 骨架+append-trace 报错文案——禁读引擎/
> 测试源码/历史 trace 反推格式；被拒按报错文案逐字修即可。

selfcheck 追加：「任务集/操作类型判据从交接包留痕直接引用了吗？
plan.md 只定点 Read 一次吗？零 evidence 翻找吗？」

**组织形态核对（#35）**：条款无圈码枚举（「枚举例外」是二值判定非①-⑤
列表），不会被镜像成载荷组织结构；need_quote_trace 扫『』原文引用存在性，
条款不改变 q/a 组织。✓

**gate 零变更前置核对三件套（#29 程序）**：
①mech 词表：need_quote_trace 扫『』原文引用/『原文』字样——复用引用
形态（plan.md 定点 Read 后『原文』引用）天然满足；不新增命中面。✓
②judge 方框一合法形态=「任务 ID+plan.md 行号 / 『原文』引用 任一在场」
——复用钉死后出处仍逐条在场；判材边界段已钉「不得以未见 plan.md 原文/
无法核对出处行号真实性为由 block」。✓
③复用引用形态不命中任何现存 block 条件：方框一(a) 全清单裸=无出处——
复用引用有明确出处标记，形态对立。✓
→ gate 文本零变更，零重放回归负担。

### 不做的事（关闭项登记）

- **pack_self_contained 不置位**（#38 判别）：权威出处源 = plan.md 文件
  （包外），行号/原文引用须 Read 该文件一次——材料非 100% 在包。
- **段链不动**：子1 链头恒 fresh spawn，无链税（§0）。
- **Node 级 strip 不置**：子2 交付物正文引 CLAUDE.md §2 触发词（一等
  材料），u3-sub1 反优化同型——只置 Step 级子1。
- **MERGED 不立项**：步体非极小搬运型 + deepseek 续步暖率彩票两节点 EV
  证伪（#24 口径，p1-sub1/p2-sub1 同结论）。
- **max_explore_calls 不设**：清点步探索面已被 L3 条款收口；基线未见
  爆炸（11 调用）不加机制（surgical）。
- **gate 文本零变更**：见 L3 三件套。
- **judge 成本不动**：判材裁剪（v2.12）已在。
- **产物指针不动**：plans/<name>.md 已在 _PHASE_ARTIFACT_DIRS 扫描面
  （p2-sub1 L4 补的是 designs/，本节点无缺口）。

## 3. 预期与验收（预登记，机制读数为主口径 #13/#23）

预期（机制确定性部分）：首调 fresh 55,077 → ~29-30k（strip -11.9k
[多处同口径实证值] + 工具白名单 25→5 ~-13.5k [u2-residual-cost 探针
22→5 -14.3k 口径]；p2-sub1 B 轮同杠杆实测 23,895，本步包大 ~2.4k 字符
故上浮 ~1k）；段 fresh/cr 主降因 = 轮数 12→~6-7 × 每轮前缀降。

验收口径（A = §1.5 免跑基线，B = worktree 码同种子 evidence 新实例
p3_sub1_ab 起跑）：

1. B 首调 fresh ≤ 30,000（机制读数，不受 #40 步体方差影响）；
2. B 工具序列：零 evidence 翻找、plan.md 定点 Read ≤2（含骨架外重读
   褶皱）、落库后零徘徊——理想最小形态 = Read plan.md → scaffold →
   Read 骨架 → Edit → append-trace（5-6 调用）；
3. 段 fresh/cr/轮数降幅（单轮同口径参考，主口径是 1/2 机制读数）；
   out 增长预登记 ≤1.9×（复用钉死 thinking 放大系数双样本收敛值 #30，
   本步基线零 mech 拒、引用要件原已在形式要件内，预计放大有限）；
   墙钟按 out÷rate 归因后登记（#30 双轴口径）；
4. 零 block；trace 质量不降（逐任务操作类型清单齐备/任务 ID 出处逐条/
   plan.md 原文『』引用在场/新增候选显式标注/q,a 按序对齐——按 gate
   方框逐条自查 B 轮 trace）；零编造；
5. pytest 全绿（新增/更新测试见 §4）+ nodes-index 摘要同步；
6. 混淆声明（预登记）：①A/B 均 fresh 段（子1 跨节点链头），无链形态差；
   ②A=免跑基线与 B 同种子 evidence 逐字同源，包差异=实例名替换
   （p2_sub3_ab→p3_sub1_ab，逐字符等量）；③种子数值 4824.5% 与今日值
   4929.2% 的漂移属 #18，两轮同种子同漂移面；④总账单轮受步体方差
   （#40）影响，验收以首调 fresh + 工具序列形态为主口径；⑤B 轮驱动
   只跑子1 一段——gate 裁决落盘后看护器杀 driver+段进程，子2 起链段
   不计入账面（登记为驱动工件）。

## 4. 实现清单

- `dl_flow_nodes.py`：plan:3 Node += segment_tools 白名单（plan:3 首例，
  注释登记）；plan:3 子1 Step += segment_strip_project_context=True
  （第十三例）+ ref 改定点一次形态 + purpose 材料边界/交付即止/格式真源
  条款 + selfcheck 一条。
- `tests/`：白名单置位/strip 置位/条款关键词钉死/ref 形态单测（对齐
  plan:2 子1 既有测试形态）。
- `skills/workflow-creation/references/nodes-index.md`：plan:3 条目子1
  摘要同步（purpose 实质内容变更）。
- 不改：SEGMENT_CHAIN_NODES、SEGMENT_CHAIN_SKIP_STEPS、MERGED_RUN_NODES、
  gate 文本、judge、pack_self_contained、产物指针扫描面。

## 5. 实测收官（待填）

（A/B 后补：读数表/工具序列/机制生效实证/验收逐条/墙钟归因/遗留）

## 6. 遗留立项

- **plan:3 链内步（子2-5）断链重审**：基线同实例实测链内首调 104k/144k/
  185k/**225k**（cr≈0 恒冷，deepseek 会话隔离缓存 #20 判据链=纯税），
  子5 已逼近 250k 护栏预授权回滚线——断链前置=交接包材料完备性逐字段
  核对 + 链内后续步条款缺口审计（#30 断链暴露效应：子2 有 CLAUDE.md §2
  一等材料职责，暴露面需先补条款再断）。
- plan:4 Node 工具白名单与子1 同型复用钉死（清点型步同族，p2-sub1-cost
  遗留立项的剩余半）。
- 输出侧瘦身（观察项，与 p1-sub1/p2-sub1 同处置）。
