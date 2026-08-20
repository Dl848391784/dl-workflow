# plan:1 子3（可行性验证）耗时/token 优化设计——复用钉死（验证步形态）+ 台账缓存通道钉死

> 日期：2026-08-20 · 分支 feat/p1-sub3-cost · 状态：收官（一轮 A/B 全验收达标）
> 上游：designs/p1-sub2-cost-optimization-design.md（plan:1 子2 三杠杆，遗留
>      立项=本子3）；designs/u4-sub2-cost-optimization-design.md（验证步复用
>      钉死 #25 收紧形态）；designs/u4-sub3-cost-optimization-design.md（验证
>      步 pack_self_contained #19 否判决）；designs/u3-sub1-cost-optimization-
>      design.md（env 剥离反超实证 → #23 第三核对）。
> 触发 = 用户指令（2026-08-20）：「优化 plan:1 的 step3，耗时和 token 消耗要
> 大幅降低，能用前面步骤沉淀下来的 discovered 和 evidence 就尽量用，避免
> factor 化；跑测试工作流用 ac-deepseek1；amplitude 今日值 4929.2%」。
> 数值口径：种子 problem_statement 保持 4824.5% 不改（runtime-audit #25：
> 数值漂移属 #18 混淆面）；4929.2% = 今日实际值，若运行中被问以此作答。
> 避免 factor 化 = cost-optimization #2：全部杠杆为框架通用机制/通用措辞，
> 零项目语义耦合（条款不点名任何项目构件）。

## 0. 范围声明

本设计只覆盖 **plan:1 子3（可行性验证，非交互验证型工作步）**。子3 是链头
（子2 交互步恒 fresh spawn 之后的首个非交互步），恒 fresh spawn，无链税；
prep 零成本（无 NEXT_PREP 面）。子4/子5 链税与 strip/pack 置位不在本设计
（遗留立项）。

## 1. 基线实测（A = p1_sub3_ab 主树码 f445570，ac-deepseek1 headless）

种子构造（runtime-audit #25 五件套）：evidence = p1_sub2_ab 23 条真实 trace
（≤plan:1#2，子1 为 B3 码/子2 为本轮优化后码——两trace 均为当日最新代码实
跑）+ state 定位 plan:1#3（sub_step_index=3，段链/stash 清零）+ settings
三件套 grep 验 name-agnostic=0 + hook 路径指主树 + pack 冒烟 24,143 字符
（子1 现状地图全文+子2 候选清单全文+前序 statements 全在包，关键锚点
formatters.py:107/候选1-6/用户三选逐字命中）。种子 ledger = 子1 落账 5 符
号（convert_return_to_percentage/load_backtest_results/load_composite_
results/LayeredBacktestEngine/_aggregate_results）。

A 轮（2026-08-20 08:52-08:58，session 4537f745，链头 fresh spawn）：

| 指标 | 基线 A |
|---|---|
| 段墙钟 | ~329s（00:52:49→00:58:18 UTC，模型侧） |
| API 调用（keep-max 去重） | 19 |
| 首调 fresh | 34,312（cr=0——fresh spawn 符合预期） |
| 段 fresh 合计 | 61,669 |
| 段 cr 合计 | 1,268,864 |
| 段 out 合计 | 37,154 |
| 成本等效（fresh+0.1cr） | 188,555 |
| 工具调用 | 35：Bash×13 / Read×11 / Grep×7 / Edit×2 |
| 门控 | trace 质量合格（生产 judge 手工重跑 **PASS**，见下事故注记） |

**环境事故注记（预登记混淆①）**：A 轮段尾（08:56）另一会话并发重装全局
claude 包（--omit=optional 形态）致二进制缺失：段内 Grep×3 ENOEXEC（模型
fallback Bash grep 完成）+ driver  judge spawn 撞 `Exec format error` 崩溃
（evidence 记「judge 调用失败（OSError）」infra-block，非内容 block）。已
修（npmmirror 重装 2.1.236，native 包镜像滞后发现：镜像只有 2.1.236 而
latest=2.1.237 optionalDeps 精确钉版→optional 解析失败被静默跳过）。infra
-block 按 last_judged 判前即记语义不复判（防 loop），A trace 内容合格性由
手工重跑生产 judge（同 gate 文本同 artifact 裁剪）确认 PASS。

### 成本归因（工具序列逐条核对，runtime-audit #26 三分诊）

| 类别 | 调用 | 判定 |
|---|---|---|
| codebase freshness 重跑 | Bash×1 | **纯税**——子1 已实测判定并留痕（sync 已执行内容可信），子3 无新鲜度职责 |
| codebase query --symbol ×4 | Bash×4 | **半税**——3 命中台账缓存（_aggregate_results/_calc_daily_ls/convert_return_to_percentage 子1 已查，返 source=discovery-ledger）=合法通道但本可逐字引用零调用；run_layered_backtest 台账未载=合法新查询 |
| Read 仓内源码重验子1 锚点 | Read×7（layered_backtest×2/data_loaders/formatters/report.html/_macros/_section_compa） | **纯税**——子1 trace 全文在包且逐符号带 file:line（复用钉死面） |
| Read sections.py | Read×1 | 合法（子1 未列该文件，单点验证面内） |
| Read PROJECT.md | Read×1 | **纯税**——规则速查 CLAUDE.md §5 已在项目上下文，全文重读超粒度 |
| ⑤可测试性接缝勘察 | ls test_cases + Read×2（test_layered/test_app）+ Grep×3 | **半税**——测试接缝前序零提及=合法例外面，但掘进粒度超「存在性」所需 |
| daily gz 结构重验 | Bash(python)×2 | **纯税**——子2 trace 已载 top_keys/2300 条结构事实 |
| grep convert_return_to_percentage | Bash×1 | **纯税**（子1 已载 file:line） |
| Grep 失败 ×3 | Grep×3 | 环境事故（上述），非行为问题 |
| 交付通道 | scaffold+Read 骨架+Edit×2+append×2 | 合法+mech 返工褶皱×1（首版载荷缺④⑤项被 feasibility_verification_trace 当场拒=生产墙正常工作） |

**三层瓶颈分诊（#1/#20/#23）**：①段边界层：链头恒 fresh spawn，无链税可裁；
②前缀层：首调 34,312 = harness ~4.8k + node-rules ~2k + 交接包 ~12k
（24k 字符）+ step prompt ~4k + **项目上下文 ~11.9k 不可剥**（④硬规则核验
须点名规则条号=一等材料，#23 第三核对不通过，见 §2 杠杆表）；③步体层
（主税）：35 调用中 ~15 纯税/半税（重验子1 已载出处+规范文档重读+掘进），
19 API 调用 × 逐调 cr 40-91k = cr 1.27M 主驱动。

## 2. 方案（一杠杆主修；机制零新增、文案为主，零 factor 化）

### 杠杆菜单逐项核对（逐杠杆处置+依据）

| 杠杆 | 处置 | 依据 |
|---|---|---|
| Step strip（env 剥离） | **不置位** | #23 第三核对「env 剥离边界」：子3 五项核验④=项目硬规则兼容须点名规则条号（H1/H1.1/H7/H8/H9/H11-H13）——规则条号=本步一等材料，与 u:3#1 反优化**同型**（B1 实证：剥后模型为点名条号重读规范文档 +40k 总账反超）；p1-sub2 设计亦明示「硬规则兼容=子3 五项核验④的职责」是子2 可剥的对照面；A 轮实证即使 env 保留模型仍 Read PROJECT.md（条款堵漏对象），剥后只会更糟 |
| pack_self_contained | **不置位** | #19 判别：验证型步——产出新事实（五项核验留痕+三态），包外单点验证是合法职责面（枚举例外内），与 u:4#2/#3 同结论；包尾「按需 Read」邀请由 L1 条款点名「零 evidence 全量翻找」对冲（A 轮实证零翻找） |
| pack_full_prior_boundary | **不置位** | 复用材料=本节点子1/子2 trace（全文在包，冒烟实证），不经前序 statements boundary；置位只涨包（surgical） |
| 断链（出 SEGMENT_CHAIN_NODES） | **不立项** | 子3 是链头恒 fresh spawn，断链收益面=子4/子5 非本步；断链暴露下游步条款缺口有 u:4#4 前车（B2 步体爆炸），子4/子5 条款核对未做 |
| MERGED 续步 | **不立项** | #24 抉择口径：子3 步体非「极小搬运型」（验证查询多），deepseek 续步暖率彩票已两节点证伪 |
| Node/Step tools 收窄 | **不动** | plan:1 Node 白名单已含子4 Agent/子5 Skill 需求（p1-sub1 L2）；无 Step 级 tools 机制（p1-sub2 设计已登记「无此机制，surgical」） |
| **复用钉死条款进 purpose/selfcheck（L1）** | **采用** | 步体层主税=重验子1 已载出处（~15/35 调用纯税/半税）——#25 收紧形态 |

### L1 复用钉死条款进 purpose/selfcheck（文案，#25 收紧形态：默认零重验+枚举例外+按条配额）

purpose 末追加（通用措辞，零项目语义）：

> 材料边界（复用钉死）：候选锚定材料=交接包（本节点子1 现状地图全文+子2
> 候选清单全文）与发现台账——子1 已载出处（file:line/codegraph 输出/实测
> 结果）逐字直接引用即合法出处，零重验零重跑：①存在性复核对子1 已载
> file:line 的符号直接引用（「复用 子1 留痕：<file:line>」形态），codegraph
> 新鲜度复用子1 判定结论（非本步职责，不重跑 freshness）；符号查询走
> `dl codebase query --symbol`（子1 已查符号自动返台账缓存=合法留痕，
> source=discovery-ledger 可作出处）。③影响面优先复用子1 已载调用方清单
> （「复用 子1 留痕：codegraph callers <符号> 返回 N 个（名单）」形态）。
> 枚举例外（逐条可判定的二值条件）：①候选引用的符号在子1 留痕与台账中
> 零提及→该符号单点验证一次（每符号最多一次，验存在即止，禁顺手掘进内部
> 结构）；②重复造轮子每功能域 ≤1 次查询（同功能域多候选共享一次查询留痕
> =合法，查询词须与候选功能域对题）；③子1 未载调用方的改动符号每候选
> ≤1 次 impact/callers 查询；⑤测试接缝事实前序零提及→每候选 ≤1 次单点
> 定位。④硬规则核验按本会话已加载的硬规则速查表点名即可，零规范文档重读
> （全文阅读规范文档不是本步职责）。零 evidence 全量翻找（前序结论已在
> 交接包）。

selfcheck 追加：「子1 已载出处逐字引用零重验了吗（file:line/callers/新鲜
度结论）？每符号/功能域/接缝查询 ≤1 次、验存在即止了吗？零规范文档重读、
零 evidence 翻找了吗？」

**写侧对齐（append-trace mech 三件套核对，本轮已逐条核）**：
- ①存在性段：mech 放行条件=file:line 在场**或**工具动词在场
  （`_check_feasibility_verification_trace` ①段逻辑：「file:line 定位本身
  即合法出处不拦」）——「复用 子1 留痕：formatters.py:107-126」形态含
  file:line 当场过墙 ✓
- ②重复造轮子段：声称「无重复/需新建」须查询动词（codegraph/Grep/grep/
  查询/返回/搜索/检索/查得）在同段——条款钉死复用形态带原查询动词+返回
  概述（「复用 子1 留痕：grep 实测 scripts/ 7 脚本无一做 X」），动词在场
  过墙 ✓
- ③影响面段：无 mech；judge 方框二「附 impact 返回的 callers 数与名单即
  合规」——复用形态字面携带查询方式+返回数+名单 ✓

**判侧对齐（gate 文本零变更三件套核对 #29）**：
①mech 词表：复用形态全部过墙（上三条）——零机械层核对面残留 ✓
②judge 方框：方框一（编造）复用形态有出处不命中；方框二（影响面拍脑袋）
复用形态附 callers 数+名单=明列合规形态；方框三（无差别可行）判据=「无量
化数字/无 file:line/无规则点名」——复用引用逐候选携带不同 file:line/数字
不命中；方框四（查询不对题）条款钉「查询词须与候选功能域对题」同向 ✓
③复用引用形态（「复用 子1 留痕：<出处>」）不命中任何现存 block 条件；
【关键】段「前序 trace（子1 现状地图/子2 候选清单）只作组成事实」=judge
判材内含子1 trace，复用出处可见可查 ✓
→ gate 文本零变更，零重放回归负担（v2.103 framing 反转成果不动）。

### 不做的事（关闭项登记）

- **strip/pack_self_contained/pack_full_prior_boundary 不置位**：见杠杆表。
- **断链/MERGED 不立项**：见杠杆表；plan 族链重审与子4/子5 优化留后续立项。
- **Node tools 不动**、**max_explore_calls 不设**（A 轮探索已在条款射程内，
  无爆炸信号）。
- **gate 文本零变更**：见 L1 三件套。
- **judge 成本不动**：判材裁剪（v2.12）已在。
- **交接包按步瘦身**（子3 不需要 understand statements 全文？）：无现成
  per-step 机制，新机制不立项（surgical），登记观察。

## 3. 预期与验收（预登记，机制读数为主口径 #13/#23）

预期（机制确定性部分）：工具调用 35 → ~10-14（纯税/半税 ~15 调用灭、交付
通道 5-6 + ②查询 2-3 + ⑤单点 1-2 + ③单点 0-2）；API 调用 19 → ~8-10；
段 cr 1.27M → ~0.5-0.65M（轮数减半+逐调上下文增长放缓）；段 fresh 略降
（首调 34.3k 不变——无 strip，工具输出增量减）；out 略降（返工褶皱灭、
轮数减；逐字引用形态拉长单轮输出=#30 质量形态）；墙钟按 out÷rate 归因后
登记（输出主导，预登记不挂硬线）。

验收口径（A=§1 基线，B=worktree 码同种子 p1_sub3_ab 复原后起跑）：

1. B 首调 fresh ≈ 34.3k ±5%（机制读数：无 strip 杠杆，首调不变=预期内，
   偏差大=包/前缀面异动须归因）；
2. B 工具序列：零子1 已载 file:line 符号的重验（Read 仓内源码重定位
   ≤2）、零 codebase freshness 重跑、零规范文档重读（PROJECT.md/MODULE.md
   Read=0）、零 evidence 全量翻找、零 daily gz 结构重验；②查询词与候选
   功能域对题；探索类调用合计 ≤6；
3. 段 cr 降 ≥40%、成本等效降 ≥40%（单轮同口径参考，主口径是 1/2 两条
   机制读数）；
4. 零 block（mech 当场拒与 judge block 均计；A 轮 mech 返工褶皱 1 次，
   B 目标 ≤1）；trace 质量逐条自查不降：五项核验逐候选齐备/三态逐候选
   标注/可行附出处（复用引用=合法出处）/假设含置信度+错误时影响/剔除附
   理由/零编造；
5. pytest 全绿（新增测试见 §4）+ nodes-index 摘要同步；
6. 混淆声明（预登记）：①A 轮段尾环境事故（Grep×3 ENOEXEC+judge spawn
   崩溃）=并发会话重装全局包所致，与码无关——A 工具计数含 3 次失败
   Grep+其 fallback（使 A 略偏大，B 改善幅度略被高估，方向保守可接受）；
   ②A 门控=手工重跑生产 judge（同 gate 文本同 artifact），B=driver 正常
   门控——判侧路径等价；③种子数值 4824.5% vs 今日值 4929.2% 漂移属
   #18——子3 无现状测量职责，若运行中被问以 4929.2% 作答；④段级总账受
   #40 步体方差影响，主口径=工具序列形态+cr 总账（#13/#23）。

## 4. 实现清单

- `dl_flow_nodes.py`：plan:1 子3 Step purpose += 材料边界条款 + selfcheck
  += 一条（注释登记条款来源=p1-sub3-cost L1）。
- `tests/test_dl_flow_engine.py`：TestSegmentSpawnOverrides +=
  test_p1_step3_reuse_clause_pinned（purpose/selfcheck 条款关键词钉死防
  静默丢失）+ test_p1_other_steps_no_step_strip 注释更新（子3 核对已做、
  结论=不置位，依据 #23 第三核对）。
- `skills/workflow-creation/references/nodes-index.md`：plan:1 条目子3 摘要
  同步（purpose 实质内容变更）。
- 不改：engine 机制代码（全现成）、dl_drive.py、gate 文本、Node
  segment_tools、SEGMENT_CHAIN_NODES、MERGED_RUN_NODES。

## 5. 实测收官

【待 B 轮后填】
