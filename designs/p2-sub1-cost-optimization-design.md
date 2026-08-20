# plan:2 子1（设计包清点与追溯基线）耗时/token 优化设计——Step strip + Node 工具白名单 + 复用钉死 + 产物指针扩面

> 日期：2026-08-20 · 分支 feat/p2-sub1-cost · 状态：设计中
> 上游：designs/p1-sub1-cost-optimization-design.md（plan 族首步优化范式：
>      strip+白名单+复用钉死三杠杆）；designs/u4-sub3-cost-optimization-design.md
>      （免跑基线提取法/墙钟=out÷rate）；cost-optimization #16/#19/#23/#25/#29/#33。
> 触发 = 用户指令（2026-08-20）：「优化 plan:2 的 step1，耗时和 token 消耗要
> 大幅降低，能用前面步骤沉淀下来的 discovered 和 evidence 就尽量用，避免
> factor 化；跑测试工作流用 ac-deepseek1；amplitude 今日值 4929.2%」。
> 数值口径：种子 problem_statement 保持 4824.5% 不改（runtime-audit #25：
> 数值漂移属 #18 混淆面）；4929.2% = 今日实际值，若运行中被问以此作答。
> 避免 factor 化 = cost-optimization #2：全部杠杆为框架通用机制/通用措辞，
> 零项目语义耦合。

## 0. 范围声明

本设计只覆盖 **plan:2 子1（设计包清点与追溯基线）**。段链不动：子1 是
跨节点链头恒 fresh spawn（_chain_resume_sid 要求 chain.node==当前节点
且 last_step==cur-1；链属 plan:1，plan:2#1 恒失配——与 plan:1#1 同型），
链税与子1 无关。plan:2 链内步（子2-4）的断链/条款缺口属后续立项
（#30 断链暴露效应），不在本设计。

## 1. 前置勘察（2026-08-20，已完成的只读审计）

- **免跑基线三查（#30）**：近期 A/B 实例（p1_sub1..5_ab 系列）种子均裁到
  目标步前一条，无一带子2#1 段；interaction_amplitude 实例止于 plan:1#1；
  tail_volume 全轮（08-06）早于全局前缀变更（O1/O2），口径不可比
  → 无免跑基线，须跑 A 轮。
- **段链适用性**：plan:2#1 恒 fresh spawn（见 §0），断链杠杆对本步无收益面。
- **置位现状**：plan:2 节点零优化置位（无 Node segment_tools、子1 无
  strip/pack_self_contained）——plan 族四节点中 plan:2/3/4 均无 Node 白名单。
- **交接包冒烟（种子 p2_sub1_ab，30,043 字符）**：DesignSolution 子5
  statements 八键 fields **全文在包**（change_list/interface_sig/
  data_contract/callers/rejected/assumptions/acceptance_map/h9_units），
  u:4 子4 验收包六字段 statements 全文在包，子6 裁决 confirm trace 在包
  → 子1 的「设计包内容+验收包+假设」三清单材料 100% 可溯源包内。
- **产物指针缺口**：包尾「已装配产物」只列 .claude/ 下产物（understand.md），
  design.md（render-artifact 落 `<root>/designs/<slug>-design.md`，slug=
  工作流名 v2.62 约定）不在 _PHASE_ARTIFACT_DIRS 扫描面——子1 的第一输入
  文件无指针，模型须自行 locate（p1-sub1-cost B1「understand.md 翻找×4」
  同型褶皱的预设条件）。
- **种子**：p1_sub5_ab 完成态复制（evidence 22 条 ≤u:4#5 + DesignSolution
  子1-5 + 机械补 plan:1#6 confirm trace[write_confirm_trace，P3-1 确认级
  无模型会话] + render-artifact 生成 designs/p2_sub1_ab-design.md[39,953
  字符] + understands/p2_sub1_ab.md 改名 + state 四字段同步 plan:2#1 +
  段记录/链/stash 清零 + settings 名替换）。

## 1.5 基线实测（A = p2_sub1_ab，main HEAD 188c46e，ac-deepseek1 headless）

（A 轮跑完后填：首调 fresh / 段 fresh / cr / out / 轮数 / dur_api / 成本 /
工具序列 / 门控 + 成本归因表）

## 2. 方案（机制为主、文案为辅，零 factor 化）

### L1 Step 级 segment_strip_project_context 置位 plan:2 子1（第十例）

置位前置核对（#23 两核对 + u3-sub1 第三核对「env 剥离边界」）：
- **交付物正文不引用自动加载文档**：子1 交付 = 三清单（原子改动要素带 ID/
  验收包/假设）+ 出处（design.md 行号/原文引用）——要素来源 = design.md
  文件 + 交接包前序留痕，无点名项目硬规则条号职责（硬规则核验归 plan:1#3；
  本节点锚点核验归子3=文件/symbol 存在性，不引规范文档正文；H9 预算归子2
  粒度裁定——均非子1 判面）。
- **逐步工具需求**：Read（design.md/scaffold 骨架）+ Bash（scaffold/落库）
  + Edit（骨架）——全在 L2 白名单内。
- **gate 判材**：judge 读 read_evidence_for_step 裁剪的 trace，不读项目
  上下文——剥 env 不影响判侧。
- 链内续跑段外部性：子1 链头恒 fresh spawn；子2-5 不置位（逐步核对未做），
  零行为变化。

### L2 Node 级 segment_tools 白名单（plan:2 首例）

逐步工具需求核对（五步）：
- 子1：Bash（scaffold/append-trace）+ Read（design.md/骨架）+ Edit（骨架）。
- 子2：Skill（writing-plans）+ Bash（codegraph CLI/scaffold/落库）+ Read
  + Edit。
- 子3：Bash（codegraph/test -f/命令干跑/scaffold/落库）+ Read + Edit。
- 子4：Skill（define-problem/writing-plans）+ Bash（scaffold/落库）+ Read
  + Edit。
- 子5：tier=confirm（P3-1）——无模型会话，无工具需求。
→ 白名单 = ("Bash", "Read", "Edit", "Skill")。无 Agent（本节点无红队步——
条件红队在 plan:1#4/plan:3#3）；无 Grep（ref 未点名，u:4 节点白名单同款
先例）。载荷通道：--scaffold + Edit，零合法 Write（u2-residual-cost 先例）；
MCP 由 NO_MCP_ARGS 结构封死（既有）。

### L3 复用钉死条款进 purpose/selfcheck（#25/#29 收紧形态）

purpose 末追加（通用措辞，零项目语义）：

> 材料边界（复用钉死）：交接包已载前序节点归一化留痕全文——设计包内容
> （前一节点末步归一化 statements 各字段）与验收包/假设清单逐字在包，
> 直接引用即合法（「复用 <节点>子N 留痕：<出处逐字>」形态），零 evidence
> 全量翻找（前序 trace 已在包内，grep evidence 通道退役）、零 understand.md
> 读取（验收包经包内留痕 + design.md 验收映射节双通道在场）。
> design.md = 本步权威出处源：定点 Read 一次取行号与『原文』引用，
> 读后零重读。枚举例外（逐条二值判定）：包内留痕与 design.md 内容不一致
> 时以 design.md 为准（拍板后产物），该不一致项单点核对一次即止。

selfcheck 追加：「设计包内容/验收包/假设从交接包留痕直接引用了吗？
design.md 只定点 Read 一次吗？零 evidence 翻找/零 understand.md 读取吗？」

**条款形态核对（#25/#29）**：默认零重验 + 枚举例外（「包内留痕与
design.md 不一致」=逐条二值判定）+ 单点配额（每不一致项 ≤1 次）+
「读后零重读」。测量型取舍（#29）：本步无现状测量职责（清点对象是
已拍板产物，非环境现状），新鲜度类时效例外不适用。

**gate 零变更前置核对三件套（#29 程序）**：
①mech 词表：element_quote_trace 扫『』原文引用存在性——复用引用形态
（出处标记+『原文』）天然满足；不新增命中面。✓（待实现时逐字核）
②judge 方框一合法形态已含「evidence 指针」为出处在场——复用引用
（「复用 <节点>子N 留痕」+出处逐字）即 evidence 指针形态；判材边界段
已钉「不得以未见 design.md 原文/无法核对出处真实性为由 block」。✓
③复用引用形态不命中任何现存 block 条件：方框一(a) 裸清单无出处——
复用引用有明确出处标记，形态对立。✓
→ gate 文本零变更，零重放回归负担。

### L4 产物指针扩面（机制）：交接包「已装配产物」补 design.md

handoff_pack 产物清单现只扫 _PHASE_ARTIFACT_DIRS（.claude/ 下）。补：
`<root>/designs/<name>-design.md` 存在即入列（slug=工作流名约定 v2.62；
框架通用——render-artifact design.md 的落盘路径单源化检查，零项目语义）。
收益面 = 一切消费 design.md 的下游步（plan:2#1 首例），防 locate 翻找
褶皱（p1-sub1-cost B1 understand.md×4 同型）。

### 不做的事（关闭项登记）

- **pack_self_contained 不置位**（#19 判别）：子1 权威出处源 = design.md
  文件（包外），行号/原文引用须 Read 该文件一次——材料非 100% 在包，
  非搬运型纯消费步。
- **段链不动**：子1 链头恒 fresh spawn，无链税（§0）。
- **MERGED 不立项**：步体非极小搬运型 + deepseek 续步暖率彩票两节点 EV
  证伪（#24 口径，p1-sub1 同结论）。
- **max_explore_calls 不设**：清点步探索面已被 L3 条款收口；基线若未见
  爆炸不加机制（surgical）。
- **gate 文本零变更**：见 L3 三件套。
- **judge 成本不动**：判材裁剪（v2.12）已在。

## 3. 预期与验收（预登记，机制读数为主口径 #13/#23）

（A 轮基线读数后填预期数值）

验收口径（A = §1.5 基线，B = worktree 码同种子 p2_sub1_ab2 起跑）：

1. B 首调 fresh 降幅机制读数（strip -11.9k [四处同口径实证值] + 工具白名单
   ~-13.5k [u2-residual-cost 探针口径]，不受 #40 步体方差影响）；
2. B 工具序列：零 evidence 翻找、零 understand.md 读取、design.md 定点
   Read ≤2（含骨架外重读褶皱）、探索类调用收敛；
3. 段 fresh/cr/轮数降幅（单轮同口径参考，主口径是 1/2 机制读数）；
   墙钟按 out÷rate 归因后登记（#30 双轴口径；段 fresh/cr 合计目标计 out
   回馈，#33 教训）；
4. 零 block；trace 质量不降（三清单齐备/要素 ID 连续/出处逐条可溯源/
   原文『』引用在场/新增候选显式标注——按 gate 方框逐条自查 B 轮 trace）；
   零编造；
5. pytest 全绿（新增/更新测试见 §4）+ nodes-index 摘要同步；
6. 混淆声明（预登记）：①A/B 均 fresh 段（子1 链头），无链形态差；
   ②种子数值 4824.5% 与今日值 4929.2% 的漂移属 #18，两轮同种子同漂移面；
   ③总账单轮受步体方差（#40）影响，验收以首调 fresh + 工具序列形态为
   主口径；④L4 产物指针为包内容变化——首调 fresh 含指针一行增量
   （~60 字符，机制读数内）。

## 4. 实现清单（待实现时定稿）

- `dl_flow_nodes.py`：plan:2 Node += segment_tools 白名单；plan:2 子1 Step
  += segment_strip_project_context=True + purpose 材料边界条款 + selfcheck
  一条（注释登记第十例）。
- `dl_flow_engine.py`：handoff_pack 产物清单补 design.md 扫描
  （`<root>/designs/<name>-design.md`）。
- `tests/`：白名单/strip 置位/条款关键词钉死/产物指针扩面单测。
- `skills/workflow-creation/references/nodes-index.md`：plan:2 条目子1 摘要
  同步（purpose 实质内容变更）。
- 不改：SEGMENT_CHAIN_NODES、SEGMENT_CHAIN_SKIP_STEPS、MERGED_RUN_NODES、
  gate 文本、judge、pack_self_contained。

## 5. 实测收官

（A/B 跑完后填）
