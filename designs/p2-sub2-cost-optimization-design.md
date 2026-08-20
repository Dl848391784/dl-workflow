# plan:2 子2（切分排序）耗时/token 优化设计——节点级断链（250k 护栏预授权回滚）+ Step strip + pack_self_contained + 复用钉死枚举例外形态

> 日期：2026-08-20 · 分支 feat/p2-sub2-cost · 状态：设计定稿（A 轮基线已实测）
> 上游：designs/p1-sub5-cost-optimization-design.md（步级断链先例+模板）、
>      designs/p1-sub3-cost-optimization-design.md（复用钉死验证步形态）、
>      designs/u2-sub3-cost-optimization-design.md（断链判据 #20）。
> 触发 = 用户指令（2026-08-20）：「优化 plan:2 的 step2，耗时和 token 消耗要
> 大幅降低，能用前面步骤沉淀下来的 discovered 和 evidence 就尽量用，避免
> factor 化；跑测试工作流用 ac-deepseek1；amplitude 今日值 4929.2%」。
> 数值口径：种子 problem_statement 保持 4824.5% 不改（runtime-audit #25：
> 数值漂移属 #18 混淆面）；4929.2% = 今日实际值，若运行中被问以此作答。
> 避免 factor 化 = cost-optimization #2：全部杠杆为框架通用机制/通用措辞，
> 零项目语义耦合（条款不点名任何项目构件）。

## 0. 范围声明

本设计只覆盖 **plan:2 子2（切分排序，非交互 skill 步）** 的成本优化。
例外面：L1 断链按 **250k 护栏预授权回滚协议**（cost-optimization #9 配套范式
「突破即执行回滚无需再裁决」，u:1 峰值 324k 回滚先例）执行为**节点级**摘除
（plan:2 出 SEGMENT_CHAIN_NODES），影响子2/子3/子4 段形态（链→fresh）——
链内后续步暴露面审计见 §2 L1。子1（链头恒 fresh spawn，零变化）、子5
（读回确认，P3-1 确认级零成本，#22 关闭清单）不受影响。

## 1. 基线实测（A 轮真跑——无免跑基线可用）

免跑基线三查（#30）：全部历史实例无一跑过 plan:2#2 段（p1_sub3_ab 停在
plan:2#2 入口=种子位；tail_volume 有 plan:2 全段但 7 月旧码，v2.102/v2.104
framing 反转后非同码）→ 免跑不成立，A 轮真跑。

A = p2_sub2_base 实例（2026-08-20 13:37，ac-deepseek1/deepseek-v4-flash
headless，**主树码**，种子 = p1_sub3_ab evidence 全 29 条 [≤plan:2#1]
+ state 四字段同步 plan:2#2 入口 + segment_chain 留生产形态
{plan:2, sid c9a2643c, last_step=1} + 链 transcript 拷入新实例 transcript
目录使链续跑真实发生——driver 日志特征行「⟂ 段链续跑（plan:2 链，子2）」
实证链内生产形态）。

| 指标 | A（p2_sub2_base 子2 链内段，生产形态） |
|---|---|
| 首调 fresh | **175,890**（链冷重写——子1 链会话 transcript 1.0MB，cr=0 实锤恒冷） |
| 段 fresh 合计（inputTokens） | 191,363 |
| 段 cr 合计 | 1,687,040 |
| 段 out 合计 | 17,336 |
| 成本等效（fresh+0.1cr） | 360,067 |
| API 轮数 | 13 |
| 模型墙钟 | 144s（dur_api 137s） |
| 工具调用 | 12：Bash×9 + Read×2 + Edit×1 |
| mech 拒 | 0（append-trace 一次过） |
| 门控 | judge 一次通过，零 block |

### 成本归因（工具序列逐条核对，runtime-audit #26 三分诊）

| 类别 | 调用 | 判定 |
|---|---|---|
| 链税（段边界层） | 首调冷重写 175,890 fresh + 逐调 carry（cr 1.69M/13 轮 ≈ 130k/调） | **主税**——deepseek 会话隔离缓存下链恒冷（#9/#20），子1 transcript（design.md 全读+evidence grep）与本步材料（交接包 32k 字符）大面积冗余 |
| 重复取证（步体层） | codegraph callers ×4（convert_return_to_percentage/_aggregate_results/load_backtest_results/run_layered_backtest） | **纯税**——四符号调用面全部已在前序留痕：DS statements callers 字段逐字在包（「_aggregate_results caller=1（run，子3 codegraph）」「run_layered_backtest caller=factor_cli.py:213」「模板消费点 9 处」「convert/load_* callers 不变（子1 codegraph）」）——100% 重查前序已载出处（#29 出处零重查粒度违反），且未走台账通道（raw codegraph CLI，discoveries 去重面零利用） |
| 包内材料重读 | Read designs/p2_sub2_base-design.md + Bash python3 重读 evidence jsonl + Bash echo/ls 侦察 | **纯税**——子1 trace 已含 E1-E15 要素原文逐字引用（mech element_quote_trace 强制），design.md 零信息增量；包尾通用「按需 Read」邀请（#16） |
| 手搓 SQL | sqlite3 查 codegraph 索引新鲜度 ×1 | **纯税**——node-rules 台账节已钉「freshness 判定走 `dl codebase freshness`，禁手搓 SQL」，弱模型违规（文案约束失效实例，但本步可由复用钉死条款吸收：零新查询则新鲜度判定需求消失——留痕引用前序查询结果，新鲜度判定归查询发起步） |
| 交付通道 | scaffold + Read 骨架 + Edit + append-trace 落库 | 合法理想最小形态（四桶分工），一次过零返工 |
| 交付后徘徊 | 0 | 本样本未触发；断链后 fresh 口径暴露风险（#37），防守性补款见 L5 |

**三层瓶颈分诊（#1/#20/#23）**：①段边界层：链税 = 最大单一成分（首调
175,890 = 段 fresh 的 92%）；②前缀层：fresh 段口径项目上下文 ~11.9k 未剥
=可裁（L2 核对见下）；③步体层：重复取证/重读 7/12 调用，条款可灭。

**链护栏突破实锤（预授权回滚触发器）**：同轮子3 链内段首调 fresh 223,811、
链会话上下文 **250,669 > 250,000** 护栏（driver 日志「⚠ 链会话上下文
250,669 tok 超阈值」原文）——#9 配套范式「链峰值 250k 突破即执行回滚无需
再裁决」的机械触发条件成立（u:1 324k 突破回滚先例之后第二例）。

## 2. 方案（五杠杆；机制为主、文案为辅，零 factor 化）

### 杠杆选型核对表

| 杠杆 | 置位/落地 | 前置核对 | 预期 |
|---|---|---|---|
| L1 节点级断链（plan:2 出 SEGMENT_CHAIN_NODES） | ✓ engine 常量单行 | 250k 护栏突破预授权（§1）+ 断链判据 #20 三要素（deepseek 链恒冷 cr≈0 实锤/交接包材料完备性 §L3 逐字段核对/fresh 段恒定地板 ~30k<< 链首调 175.9k）+ #24（前序上下文 1MB 巨大→携带税主导，断链确定优）+ #30 暴露面审计（见下） | 灭链税：首调 175,890→~30k |
| L2 Step 级 segment_strip_project_context | ✓ Step 字段 | 见 L2（H9 阈值逐字在 purpose 形式要件=消费步同 p1-sub4 型） | 首调再 -11.9k（四处同口径实证值） |
| L3 pack_self_contained（非交互步第五例） | ✓ Step 字段 | 输入契约逐字段核对见下；装配不变量测试钉死 | 灭包内材料重读 3 调用+下游驻留 |
| L4 复用钉死（#25 枚举例外形态——#34 不适用，见下） | ✓ purpose/selfcheck 条款 | gate 零变更三查见下 | 重复取证 4→0 |
| L5 交付即止钉死（#37 平移）+ 格式真源钉死（#26 平移，子2/3/4 同批补款） | ✓ purpose 条款 | #30 断链暴露面审计的补款落地 | 防 fresh 口径徘徊/猎捕 |
| MERGED 续步 | ✗ 否决 | #24：前序 transcript 1.0MB，携带税主导；u:3 暖率彩票 1/4 前科 | — |
| pack_full_prior_boundary | ✗ 不置位 | 子1 要素基线走「本节点各步最新留痕」**全文通道**（非前序节点摘要节），无截断面；DS statements text 不截断（p1-sub2 同判决） | — |
| max_explore_calls | ✗ 不设 | 基线 12 调用零爆炸信号，条款先行（p1-sub1/sub2/sub5 同判决） | — |
| Node segment_tools | ✗ 不动 | 节点级共享面超单步范围；子2 无 Agent 需求但白名单是 Node 级（#27 程序是节点五步核对，超范围） | — |
| gate 文本 | ✗ 零变更 | 三查见 L4 | — |

### L1 节点级断链（机制，预授权回滚执行）

- `dl_flow_engine.py`：SEGMENT_CHAIN_NODES 摘除 "plan:2"（注释登记：
  p2_sub2_base A 轮链峰值 250,669>250k 护栏，#9 预授权回滚第二例，
  白名单即回滚面=重新入册即恢复链）。`_chain_resume_sid` 首条件
  「节点在白名单」即兜住——子2/3/4 全 fresh spawn，零 driver 改动；
  `_chain_update` 既有「出白名单节点清链记录」行为自动清理残留
  （test_chain_update_clears_on_non_whitelist_node 钉死在位）。
- 与步级豁免集的关系：SEGMENT_CHAIN_SKIP_STEPS {("plan:1",5)} 不动
  （plan:1 链峰值未破保留，surgical）。
- **#30 断链暴露面审计**（断链前置核对，链内后续步=子3/子4 转 fresh）：
  ①格式钉死缺口——子2/子3/子4 purpose 均无「格式真源=scaffold 骨架+报错
  文案」钉死条款（u:4#4 断链后格式猎捕 5+ 调用的同型缺口）→ 同批补款
  （L5）；②材料边界缺口——子3（锚点核验）职责=新取证步（codegraph/
  test -f/pytest --collect-only），pack_self_contained 不适用（验证步，
  p1-sub3 同型否决先例），其材料=子2 单元集在包全文通道 ✓ 无缺口；
  子4（归一化）payload 格式五键已在 purpose 全文+scaffold 占位符括注
  （#31 多条形态）+mech 五键校验报错即返工指令 ✓ 无缺口；③交付后徘徊
  缺口——#37 两通道打架全步存在，子3/子4 同批补款（各一句通用措辞）。

### L2 Step 级 segment_strip_project_context 置位子2（机制）

置位前置核对（#23 两核对 + u3-sub1 第三核对「env 剥离边界」）：
- **交付物正文不引用自动加载文档**：子2 交付=单元切分+DAG+预算+出处。
  H9 阈值（≤3 文件 ≤200 行）逐字在 purpose 形式要件
  （_TB_STEP2_FORM_REQUIREMENTS「每单元附 H9 预算估计（≤3 文件 ≤200 行）」）
  ——H 条号内容经 purpose 在场，非一等材料直引规范文档（消费步同
  p1-sub4-cost 子4 型，与 p1-sub3 验证步否决型不同型）；TDD 序/切片原则
  出处=writing-plans skill（Skill 工具通道，非项目上下文）；gate 判材
  边界已封死「codegraph db 不可见」判面。✓
- **逐步工具需求**：Bash（scaffold/落库/台账查询例外通道）+ Read（骨架）
  + Edit（骨架）+ Skill（writing-plans）——Step strip 只剥 env 不动
  tools。✓
- **gate 判材**：judge 读 read_evidence_for_step 裁剪 trace，不读项目
  上下文。✓

### L3 pack_self_contained 置位子2（机制，#16 三件套）

置位前置=输入契约逐字段核对（#16，冒烟实测包 32,290 字符）：

| 输入契约项 | 包内位置 | 核对 |
|---|---|---|
| step1.element_baseline（E1-E15 要素清单+出处+原文引用） | 「本节点各步最新留痕」节子1 trace **全文通道**（实测 8.5k 字符逐字在包） | ✓ |
| 依赖分析材料（符号调用面/消费点 file:line） | 前序节点「设计解决方案」摘要节 statements callers 字段（实测：_aggregate_results caller=1/run、模板消费点 9 处逐 file:line、load_backtest_results 等全在包） | ✓ |
| 验收包 SC ID 集（子2 不直接消费，子4 消费面） | 前序节点「定义成功标准」摘要节（statements.text 全文不截断，p1-sub2 B3 同口径实证） | ✓ |
| H9 阈值 | purpose 形式要件逐字 | ✓ |
| design.md 原文 | 不需要——子1 trace 含全部要素原文逐字引用（element_quote_trace 机械强制），gate 判材边界封死「无法核对是否真在设计包」判面 | ✓ |

生效面：包尾切换+段 prompt 材料边界条款均由 build_step_prompt 非交互
else 分支既有机制覆盖（零 driver 改动）；B 轮 settings hook 路径指
worktree → hook 侧包尾切换同可见（p1-sub2 修正登记先例）。装配不变量
测试钉死（包须含子1 留痕全文 + DS statements callers 字段）。

### L4 复用钉死条款进 purpose/selfcheck（文案，#25 枚举例外形态）

**形态选择**：#34「无取证例外」不适用——子2 gate 形式要件含「codegraph
callers 取证」留痕形态，新查询在判据内有合法出口（判材边界「依赖真实性
只判留痕在场」不封死新查询），退回 #25 枚举例外形态（给真缺口留单点
通道：要素对依赖前序未载时台账去重通道单点补一次）。

purpose 末追加（通用措辞，零项目语义）：

> 材料边界（复用钉死）：切分材料=交接包（本节点子1 要素基线全文 +
> 前序节点归一化结论摘要）——要素的 file/function/调用面/消费点事实
> 逐字引用前序留痕即合法形态（引用含原查询命令+返回概述，标注「复用」）。
> 默认零新查询：禁重跑前序已载的 codegraph/影响面查询（同符号重查=
> 重复付税，台账缓存命中亦然——缓存输出进上下文照付 token）；
> 禁 Read 设计文档/understand.md 重读（要素原文引用已在子1 留痕）；
> 禁 Read/grep evidence 翻找；索引新鲜度判定归查询发起步，本步零判定。
> 新查询=逐项例外：仅当两要素间依赖关系前序留痕未覆盖且无法从包内材料
> 推断时，对该要素对单点补一次 node-rules 台账节的 codebase query
> --symbol 通道（台账自动去重）。职责边界：符号存在性/可行性/影响面
> 核验归前序节点验证步（已留痕），锚点核验归子3（下一步），本步零复核；
> 为后续步预取锚点=越界。

selfcheck 追加：「依赖出处全部可溯包内前序留痕吗（零重复 codegraph 查询/
零设计文档重读/零 evidence 翻找/零手搓 SQL/零为后续步预取）？」

**条款形态核对（#25）**：默认零新查询+枚举例外（要素对依赖未覆盖→单点
一次）——例外是枚举谓词非开放谓词（「缺口/必要时」零出现）。

**gate 零变更前置核对三件套（#29 程序）**：
①mech 词表：dependency_order_trace（声明依赖 vs 拓扑序方向扫描）/
element_coverage_trace（E-ID 跨步覆盖）/single_phase_argument（单阶段
量化同段扫描）——三者全为 trace 文本结构扫描，与出处新旧零耦合；复用
引用保留「声明依赖+命令+返回概述」文本形态，扫描面不受影响。✓
②judge 方框：判材边界已钉「codegraph 留痕=查询命令+返回概述即合规，
不得索取输出原文」「不核 db 实际调用关系」——复用引用=命令+概述+复用
标注，同形；默认-PASS 方框六条（横切/排序/预算/覆盖/单阶段/拍板）无一
涉出处新旧。✓（p1-sub3-cost 验证步同款形态 B2 零 block 先例）
③复用引用形态不命中任何现存 block 条件：方框一-六均不涉出处时间性。✓
→ gate 文本零变更，零重放回归负担（v2.104 framing 反转成果不动）。

### L5 交付即止钉死 + 格式真源钉死（文案，#37/#26 平移，断链补款）

子2 purpose 末追加：

> 交付即止：落库成功（✓ 已落库）即结束本轮——禁 locate 产物/读 state/
> grep evidence 确认落库/预习下一步，推进与门控由外部 driver 判定。
> 载荷格式与编号传导的唯一真源 = --scaffold 骨架 + append-trace 报错
> 文案——禁读引擎/测试源码/历史 trace 反推格式；被拒按报错文案逐字修。

子3/子4 purpose 末各追加同款两句（断链暴露面补款，#30「断链与补款同批
落地」；子3/子4 本体职责条款不动=超范围零触碰）。

### 不做的事（关闭项登记）

- **子3/子4 步体优化**：超单步范围（断链补款仅暴露面防守，不触碰职责条款）；
  子3 A 轮副产物基线（29 轮/215s/首调 223,811）已留存 p2_sub2_base
  drive-stream 供未来 p2-sub3-cost 免跑基线。
- **pack_full_prior_boundary 不置位 / max_explore_calls 不设 /
  Node segment_tools 不动**：见杠杆表。
- **plan:1/3/4 链**：plan:1 峰值未破保留；plan:3/4 未实测，登记遗留
  （链峰值审计=独立项）。
- **gate 文本零变更**：见 L4 三查。
- **judge 成本不动**：判材裁剪（v2.12）已在。

## 3. 预期与验收（预登记，机制读数为主口径 #13/#23）

预期：首调 fresh ~30k±5k（fresh 段恒定地板：包 32.3k 字符≈20-22k tok
+ 剥后 harness ~4.8k + node-rules ~1.3k + step prompt ~2k；A=175,890，
**-83%**）；段 fresh ≤ 55k（A 191,363，**-71%**）；段 cr ≤ 400k
（A 1,687,040，**-76%**——断链灭 130k/调 carry + 复用钉死灭重复取证轮）；
成本等效 ≤ 95k（A 360,067，**-74%**）；工具调用 ≤ 8（理想最小形态
Skill→scaffold→Read 骨架→Edit→落库±台账例外查询）；API 轮数 ≤ 8（A 13）；
mech 拒 ≤1（A 0）；out 不挂硬线（引用厚度=质量形态 #30，预登记持平或
略升）；墙钟预登记 -30%~-50%（A 144s；轮数减半+零冷重写 TTFT，但 out
主导口径下引用厚度反噬风险登记 #30/#33）。

验收口径（A=§1 真跑基线，B=p2_sub2_ab 同种子族 worktree 码起跑）：

1. B 首调 fresh ≤ 35k（机制读数，确定性，不受 #40 步体方差影响）；
   段 fresh ≤ 55k；段 cr ≤ 400k；成本等效 ≤ 95k；
2. B 工具序列 ≤8 且零 codegraph 重查/零设计文档重读/零 evidence 翻找/
   零手搓 SQL/零交付后徘徊（合法=Skill/scaffold/Read 骨架/Edit/落库/
   台账节 codebase query 例外）；
3. mech 拒 ≤1 且 gate judge 零 block；
4. trace 质量逐条自查不降：E-ID 覆盖齐备/单元附 H9 预算+承接要素 ID+
   依赖出处/拓扑序被依赖者先行/TDD 序内嵌/阶段划分附断点验证或②量化
   论证/提案语义/零编造（依赖出处逐条可溯包内留痕）；
5. pytest 全绿（新增/更新测试见 §4）+ nodes-index 摘要同步；
6. 混淆声明（预登记）：①A=链内段（生产形态，含链税），B=fresh 段——
   段合计差含 L1 兑现，非混淆（p1-sub5 同口径先例）；链税估算口径=
   A 首调 175,890 单点冷重写+逐调 carry 均值 ~130k；②A/B 同种子
   （p1_sub3_ab evidence 全 29 条逐字相同=三查②最强形态）；③种子数值
   4824.5% vs 今日值 4929.2% 漂移属 #18——子2 无现状测量职责且 L4 禁
   重实测，若运行中被问以 4929.2% 作答；④B 轮模型侧 append-trace 走
   主树引擎（#31 第三路径）但子2 mech 本体零变更→无差；包尾切换/段
   prompt 条款=driver+hook 双侧均指 worktree，B 轮可见（p1-sub2 修正
   登记先例）；⑤段级总账受 #40 步体方差影响，主口径=首调 fresh+工具
   序列形态+mech 拒次数（#13/#23）。

## 4. 实现清单

- `dl_flow_engine.py`：SEGMENT_CHAIN_NODES 摘除 "plan:2"（注释：250,669
  护栏突破预授权回滚，#9 第二例，回滚面=重新入册）。
- `dl_flow_nodes.py`：plan:2 子2 Step += `segment_strip_project_context=True`
  + `pack_self_contained=True` + purpose 材料边界/复用钉死条款（L4）+
  交付即止/格式真源条款（L5）+ selfcheck 一条；子3/子4 purpose += 交付
  即止/格式真源两句（L5 断链补款）；注释登记置位来源=p2-sub2-cost。
- `tests/test_dl_flow_engine.py`：链白名单钉死（plan:2 ∉ SEGMENT_CHAIN_
  NODES + SKIP_STEPS 成员不变）+ 子2 flags 置位钉死（[F,T,F,F,F] 形态
  比照 test_p1_step2_pack_self_contained_flags）+ 装配不变量（plan:2#2
  位形包含子1 留痕全文+DS callers 字段）+ 尾行条件化（比照
  test_p1_step2_tail_line_replaced）。
- `tests/test_dl_drive.py`：_chain_resume_sid 对 plan:2 返 None（白名单
  摘除行为）+ 子2 段 prompt 材料边界条款钉死（若既有测试未覆盖则补例）。
- `skills/workflow-creation/references/nodes-index.md`：plan:2 条目子2
  摘要同步（purpose 实质内容变更）。
- 不改：gate 文本、Node segment_tools、SEGMENT_CHAIN_SKIP_STEPS、
  MERGED_RUN_NODES、engine mech 本体、子3/子4 职责条款。

## 5. 实测收官（2026-08-20，A=p2_sub2_base 链内段生产形态 / B=p2_sub2_ab worktree 码，ac-deepseek1 headless 同种子族）

B 轮驱动法：种子=p1_sub3_ab evidence 全 29 条（≤plan:2#1）+state 四字段
同步 plan:2#2 入口+segment_chain 留生产形态（断链 tripwire——B 轮日志
无「⟂ 段链续跑」特征行=fresh spawn 实证断链生效）+段记录清零+settings
名替换+hook 路径指 worktree+产物文件第七件+**链 transcript 拷入新实例
transcript 目录**（A 轮链内生产形态的关键手法——此前种子 A/B 链内段只能
免跑或 fresh 化，本法使链续跑真实发生：driver 日志「⟂ 段链续跑（plan:2
链，子2）」实证）→ `bash -ic` 内 AC_WORKFLOW_LAUNCHER=worktree launcher
`ac-deepseek1 --dl p2_sub2_ab --resume --headless`。一轮达标，无修轮。

| 指标（modelUsage 权威口径） | A（链内段） | B（fresh+杠杆） | Δ |
|---|---|---|---|
| 首调 fresh | 175,890 | 42,488 | **-75.8%**（机制读数钉死） |
| 段 fresh 合计 | 191,363 | 89,700 | **-53.1%** |
| 段 cr 合计 | 1,687,040 | 474,112 | **-71.9%** |
| 段 out 合计 | 17,336 | 29,471 | +70.0%（质量形态，见归因） |
| 成本等效（fresh+0.1cr） | 360,067 | 137,111 | **-61.9%** |
| API 轮数 | 13 | 9 | -31% |
| 工具调用 | 12（纯税 7） | 8（零纯税） | 形态理想最小化 |
| mech 拒 / 门控 | 0 / 一次过 | 0 / 一次过零 block | ✓ |
| 模型墙钟 | 144s | 226s | **+57% 反升（见归因）** |
| 成本（driver 计价） | $2.234 | $1.422 | **-36.4%** |

**验收逐条**：①首调 ≤35k **✗**（42,488，-75.8%）——预登记估算漏工具
schema 分量（plan:2 Node 未置 segment_tools 白名单，全量工具 schema
~14.3k 留存：42.5k ≈ 包 ~20k + 剥后 harness ~4.8k + 工具 schema ~14.3k +
node-rules/prompt ~3k 逐项拟合），**预登记口径失误非杠杆失效**（strip
-11.9k 与断链灭 175.9k 冷重写均机制钉死）；残余杠杆=plan:2 Node
segment_tools 白名单（-14.3k/首调，节点级五步核对超本设计范围，登记遗留）。
段 fresh ≤55k **✗**（-53.1%）/cr ≤400k **✗**（-71.9%）/等效 ≤95k **✗**
（-61.9%）——预登记未计 out +70% 对逐调上下文的回馈（p1-sub5 同型口径
失误第二例）；②工具序列 **✓**（8 调用=Skill→scaffold→Read 骨架→Write
载荷→Edit×3→落库；零 codegraph 重查/零设计文档重读/零 evidence 翻找/
零手搓 SQL/零交付后徘徊）；③mech 拒 0 ≤1 **✓** + judge 零 block **✓**；
④trace 质量逐条 **✓**：E1-E15 覆盖齐备/复用标注 17 处（逐字引用前序留痕
含原查询命令+返回概述）/拓扑序被依赖者先行/单元 H9 预算齐备/TDD 序内嵌/
提案语义在场/零新 codegraph 查询/零编造；⑤pytest 1181 全绿（新增 8 例）
+ nodes-index 同步 **✓**；⑥混淆声明按预登记处理——③数值漂移未触发
（L4 禁重实测，运行中未被问今值 4929.2%）。

**墙钟归因（#30 双轴口径）**：out÷rate 拟合双端成立（B 29.5k out≈227s
vs dur_api 226s；A 17.3k≈133s vs 137s，同端点 ~130 tok/s）→ 墙钟差=
输出量差。输出构成三分（#33）：thinking 50.2k vs A 27.3k（**1.84×**——
条款驱动逐事实 deliberation，p1-sub1 的 1.9× 再现=复用钉死条款的
thinking 放大系数双样本收敛 ~1.9×）+ tool_use 输入 20.6k vs 10.4k
（+98%=逐字引用载荷厚度，17 处复用引用=L4 条款直接兑现=质量形态）+
text 0.8k（反降）。褶皱成分=Write 后 Edit×3 精修（轻微）。**耗时轴未达
预登记（+57% 反升）=token 优化的墙钟反噬第四实例（#30）**；取舍登记：
逐字引用厚度是防编造的条款兑现，撤厚度=回到编造风险——不撤，留用户
裁决（同 p1-sub5 决议形态）。

**断链暴露面实证（#30 补实例）**：子3 转 fresh 后 29 轮→53 轮（调用面
扩大），但首调 223,811→61,141（-72.7%）、等效 811,611→283,446（-65.1%）
——暴露效应的轮数放大被断链收益覆盖仍有净赢，但「后续步 fresh 化轮数
看涨」写进暴露面审计的预登记项（本轮未预登记子3 轮数口径=审计缺口，
后续断链设计预登记补「后续步轮数上限」）。

**沉淀**（skills 同步）：①runtime-audit #25 补=种子 A/B 的链内段基线
构造手法（链 transcript 拷入新实例 transcript 目录使段链续跑真实发生——
此前链内基线只能免跑或 fresh 化）；②cost-optimization #30 补=墙钟反噬
第四实例+thinking 放大系数双样本收敛 ~1.9×；③#23 补=首调预登记按三分量
逐项报价教训（工具 schema 分量在 Node 未置白名单时留存，漏报即 ✗）；
④#20 补=断链暴露面预登记须含后续步轮数上限。

**merge 注（2026-08-20 收口）**：并行会话 p2-sub1-cost 同日先 merge——已置位
plan:2 Node 工具白名单（四件 Bash/Read/Edit/Skill，本设计遗留①残余杠杆
由其实现）+子1 Step strip（占「第十例」编号，本设计子2 顺移第十一例）+
交接包产物指针扩面补 design.md；冲突仅 nodes-index plan:2 行一处，双侧
保留收口；测试对齐三处（strips 断言/Node 白名单元组/兄弟步排除集，同名
测试去重一处理）。

**遗留立项**：①~~plan:2 Node segment_tools 白名单~~（p2-sub1-cost 已做）；②plan:2#3 步体优化（fresh 后 53 轮，复用钉死/
载荷组织钉死候选——B 轮 fresh 段基线已留存 p2_sub2_ab drive-stream）；
③plan:3/4 链峰值审计（plan 族断链收官项）；④子2 耗时轴=输出主导结构
（质量形态），如需墙钟再降只能动引用厚度条款——留用户裁决，不自行撤。
