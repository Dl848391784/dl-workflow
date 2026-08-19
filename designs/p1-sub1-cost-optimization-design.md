# plan:1 子1（现状勘察）耗时/token 优化设计——Step strip + Node 工具白名单 + 复用钉死（前序留痕出处零重验 + dl codebase 台账引导）

> 日期：2026-08-19 · 分支 feat/p1-sub1-cost · 状态：设计中
> 上游：designs/u4-sub3-cost-optimization-design.md（断链+strip+复用钉死三杠杆范式）；
>      designs/u4-sub2-cost-optimization-design.md（#29 复用钉死下探出处粒度）；
>      designs/u2-residual-cost-optimization-design.md（段前缀外科剥离探针口径）；
>      designs/u4-sub1-cost-optimization-design.md（Node 工具白名单逐步核对程序）。
> 触发 = 用户指令（2026-08-19）：「优化 plan:1 的 step1，耗时和 token 消耗要大幅
> 降低，能用前面步骤沉淀下来的 discovered 和 evidence 就尽量用，避免 factor 化；
> 跑测试工作流用 ac-deepseek1；amplitude 今日值 4947.7%」。
> 数值口径：种子 problem_statement 保持 4824.5% 不改（runtime-audit #25：
> 数值漂移属 #18 混淆面）；4947.7% = 今日实际值，若运行中被问以此作答。
> 避免 factor 化 = cost-optimization #2：全部杠杆为框架通用机制/通用措辞，
> 零项目语义耦合（条款不点名 pytest/report/因子等任何项目构件）。

## 0. 范围声明

本设计只覆盖 **plan:1 子1（现状勘察）**。plan 族段链（plan:1-4 在
SEGMENT_CHAIN_NODES）不动：子1 是链头恒 fresh spawn（_chain_resume_sid
last_step==cur-1 恒不成立），链税与子1 无关；链内步（子3/子4）的断链
收益与断链暴露效应（cost-optimization #30：先补格式钉死/材料边界条款缺口）
属后续立项，不在本设计。

## 1. 基线实测（A = p1_sub1_ab 同种子起跑，main HEAD 310c5c9，ac-deepseek1 headless）

**种子**：u4_sub3_ab 完成态复制（evidence 22 条 ≤u:4#5 + state plan:1
sub_step_index=1 + 段记录/链/stash 清零 + 名替换零残留）；种子当日值口径
4824.5%（与 u4_sub2/3/4_ab 同种子族）。交接包冒烟 11,257 字符：问题陈述
原话 + 前序四节点归一化+读回摘要（ProblemContext statements 已含
file:line 级出处——复用面在场实证）。

| 指标 | A（p1_sub1_ab，main 310c5c9） |
|---|---|
| 首调 fresh | 44,040（cr=0——fresh spawn 符合链头预期） |
| 段 fresh 合计 | 86,601 |
| 段 cr 合计 | 2,670,464 |
| 段 out 合计 | 35,278 |
| 轮数（result 权威值） | 71 |
| 段 dur_api | 292.4s |
| 成本 | $2.650 |
| 工具序列 | Bash×50 + Read×17 + Edit×2 + Write×1 |
| 门控 | 一次通过，零 block |

### 成本归因（工具序列逐条核对，runtime-audit #26 三分诊）

对照交接包材料（问题陈述原话 + 前序四节点归一化/读回摘要 11,257 字符，
ProblemContext/ScopeAndConstraints statements 已含 file:line 级出处与
json 字段实测值逐字在包）：

| 类别 | 调用 | 判定 |
|---|---|---|
| 新鲜度链（B01 sqlite 手搓 / B05 codegraph sync / B06 重查） | 3 | **合法本步职责**——sync 为条件触发（索引 674h 过期）；SQL 手搓自项目 CLAUDE.md §3=strip 后通道缺口，由 L1 的 `dl codebase freshness` 补位 |
| codegraph 勘察核心（B13-B18 去重后 query/callers/impact） | ~6 | **合法本步职责**（①②③要素出处） |
| codegraph 用法重试（B10-B12 带路径参数报错重跑） | 3 | **纯税**——参数形态无统一入口（`dl codebase query --symbol` 固定形态可灭） |
| 环境摸索（B02 ls 根 / B03 codegraph --help / B04 ls .codegraph / B07 status / B46 ls 台账） | 5 | **纯税**——工具箱可见性不足（B46 查台账=台账已知，正面） |
| Read 掘进 ×17（data_loaders×2/formatters/constants×2/_macros/三个 _section/app.py/layered_backtest×3/runner/paths/test_app） | ~12 | **纯税/半税**——超出地形粒度的内部结构掘进；data_loaders 双×100 链 file:line 前序留痕逐字在包仍全文重读 |
| grep/sed/python 链路与数据契约重验（B19-B45 内 ~27 调用的大头） | ~15-18 | **纯税**——前序留痕已载事实重验：amplitude_layered_backtest.json 字段（ProblemContext 陈述已载 long_short_return_annual/n_days/coverage 逐字）被 B40/B44/B47 三次重读、双×100 链 grep 多轮、模板/路径存在性 |
| 交付通道（B49 scaffold / B50 落库 / Read 骨架 / Edit×2 / Write×1） | 6 | 合法（Write 覆盖 scaffold 1 次=褶皱，S14 既有面非本轮） |

**三层瓶颈分诊（cost-optimization #1/#20/#23）**：
①**段边界层**：子1 链头恒 fresh spawn，无链税——首调 44,040 即 fresh 段
前缀全量（harness+node-rules+交接包+step prompt+项目上下文 ~11.9k+
工具 schema 22 个 ~14.3k）。
②**前缀层（主税一）**：项目上下文 11.9k 未剥 + 工具 schema 未裁
（plan:1 是仅剩的无 strip/无白名单编排节点族）。
③**步体层（主税二）**：50 Bash 中 ~35 纯税/半税（重验前序已载出处 +
掘进 + 环境摸索 + 重试褶皱）= 轮数 71 的主驱动；cr 2.67M = 71 轮 ×
单调涨上下文的平方膨胀。

## 2. 方案（三杠杆；机制为主、文案为辅，零 factor 化）

### L1 Step 级 segment_strip_project_context 置位 plan:1 子1（机制，第七例）

置位前置核对（cost-optimization #23 两核对 + u3-sub1 第三核对「env 剥离边界」）：
- **交付物正文不引用自动加载文档**：子1 交付 = 四要素现状事实（①涉及模块/
  ②可复用点/③调用方/④数据契约）+ codegraph 新鲜度判定——出处形态 =
  codegraph/dl codebase 输出、file:line、Bash 实测、复用引用（L3），无点名
  项目硬规则条号职责（与 u:3#1 反优化不同型；与 u:4#1/#2/#3 同型）。
- **codegraph 新鲜度检查通道**（本步特有核对——新鲜度 SQL 此前只存在于
  项目 CLAUDE.md §3，剥 env 后模型无现成通道）：新增
  `dl codebase freshness` 子命令（dl_codebase.py，通用机制）——读
  .codegraph/codegraph.db 的 MAX(indexed_at)，输出时间戳+距今时长+>72h
  判定；node-rules 发现台账段同步一句。零项目语义（codegraph 是工作流
  系统既有词汇，step ref 已点名）。
- **逐步工具需求**：Bash（dl codebase/codegraph/scaffold/落库）+ Read
  （骨架/文件）+ Edit（骨架）——全在 L2 白名单内。
- **gate 判材**：judge 读 read_evidence_for_step 裁剪的 trace，不读项目
  上下文——剥 env 不影响判侧。
- 链内续跑段外部性：子1 链头恒 fresh spawn；子2-6 不置位（逐步核对未做），
  零行为变化。

### L2 Node 级 segment_tools 白名单（机制，plan:1 首例）

逐步工具需求核对（六步）：
- 子1：Bash + Read + Edit（+Grep——ref 明写 Grep；Bash grep 可替代但
  弱模型照 ref 行事，留 Grep 防褶皱）。
- 子2（interactive）：TUI 段 = 白名单 + TUI 交互三件套（既有机制）；
  prep 段只 Read 材料 + 文本输出。
- 子3：Bash + Read + Edit（fence_allow Bash；codegraph/Bash/Read）。
- 子4：Agent（条件红队）+ Read + Edit（fence_allow Agent）。
- 子5：Skill（define-problem）+ Read + Edit（statements 载荷骨架）。
- 子6（interactive）：Bash（render-readback/render-artifact）+ Read。
→ 白名单 = ("Bash", "Read", "Edit", "Grep", "Skill", "Agent")。
载荷通道核对：载荷走 --scaffold + Edit，零合法 Write（u2-residual-cost
先例）；MCP 由 NO_MCP_ARGS 结构封死（u1-overall-cost O1，既有）。

### L3 复用钉死条款进 purpose/selfcheck（文案，#25/#29 收紧形态）

purpose 末追加（通用措辞，零项目语义）：

> 材料边界（复用钉死）：交接包前序各节点归一化陈述与读回裁决所载出处
> （file:line/实测命令与输出/机制结论/数据契约字段）逐字直接引用即合法
> （「复用 <节点>子N 留痕：<出处逐字>」形态），零重跑重验（前序已定位的
> file:line 不重修、已实测的字段存在性不重测、已查过的符号不重查——符号
> 查询走 `dl codebase query --symbol`，前步已查符号自动返台账缓存）。
> 枚举例外（逐条可判定的二值条件）：①codegraph 新鲜度判定 = 时间敏感，
> 本步实测一次（`dl codebase freshness`，禁复用前序判定）；②四要素某条
> 事实在前序留痕中**从未出现**（符号/字段/模块名零提及）→ 该事实单点
> 验证一次（每条事实最多一次，验存在即止，禁顺手掘进内部结构）。
> 零 evidence 全量翻找（前序结论已在交接包）。

selfcheck 追加：「前序已载出处逐字引用零重验了吗？新鲜度本步实测了吗？
前序零提及的事实每条 ≤1 次单点验证、验存在即止吗？零 evidence 全量
翻找吗？」

**条款形态核对（#25/#29）**：默认零重验 + 枚举例外（「前序留痕零提及」=
逐条二值判定）+ 按条配额（每条事实 ≤1 次，#14 上限≠配额）+「验存在即止
禁掘进」+ 时间敏感项（新鲜度）显式排除出复用面（#29 测量型取舍的
「精确现状值进阈值判据须时效核对」同族——新鲜度判定是时间函数，复用
前序判定不合法，故列为本步实测义务）。

**gate 零变更前置核对三件套（#29 程序）**：
①mech 词表：terrain_tool_trace 认 file:line 为出处在场（_TERRAIN_FILELINE_RE
分支）——复用引用带 file:line 即过机械层；非代码符号的实测结论（命令+
输出形）不被 _TERRAIN_SYMBOL_RE 扫描。✓
②judge 方框一已钉「不得以无工具出处/留痕不可核验/缺 file:line/引用不存在
接口为由 block」；判材边界段明示 understand 段不在判材、不得判「无法核实」。
✓
③复用引用形态（出处标记+file:line/命令逐字）不命中任何现存 block 条件：
方框一(a) 训练记忆冒充判「一般/通常」式无出处常识断言——复用引用有明确
出处标记+具体定位，形态对立。✓
→ gate 文本零变更，零重放回归负担（v2.99 framing 反转成果不动）。

### L4 discoveries 台账引导（机制既有，文案点名）

node-rules 发现台账段已有「`dl codebase query --symbol/--history` 自动落账
去重」。L3 条款点名符号查询走 `dl codebase query --symbol`——子1 查过的
符号（定义+callers+impact 三连）自动落账，子3 可行性验证重查同符号返缓存
（source=discovery-ledger），全轮口径的跨步去重收益（本 A/B 两臂台账均空，
子1 段无差；收益在 子3，登记不进验收面）。

### 不做的事（关闭项登记）

- **pack_self_contained 不置位**（#19 判别）：子1 是生产/勘察型步——产出
  新事实（现状地图），包外单点验证是合法职责面（枚举例外内），与 u:4#3
  同结论。包尾通用「按需 Read」邀请由 L3 条款点名「零 evidence 全量翻找」
  对冲。
- **plan 族段链不动**：子1 链头无链税；链内步断链需先补条款缺口（#30
  断链暴露效应），登记后续立项。
- **MERGED 不立项**：步体非极小搬运型 + deepseek 续步暖率彩票两节点 EV
  证伪（#24 口径）。
- **max_explore_calls 不设**：勘察步探索是职责面；L3 枚举例外+按条配额
  已收口，基线若未见爆炸不加机制（surgical）。
- **gate 文本零变更**：见 L3 三件套。
- **judge 成本不动**：判材裁剪（v2.12）已在。

## 3. 预期与验收（预登记，机制读数为主口径 #13/#23）

预期（探针预算，机制确定性部分）：首调 fresh 44,040 → ~18k（strip -11.9k
[三处同口径实证值] + 工具白名单 22→6 ~-13.5k [u2-residual-cost 探针 22→5
-14.3k 口径]）；探索 Bash 50 → ≤12（复用钉死灭前序已载出处重验 ~15-18 +
掘进 ~12 + 环境摸索/重试 ~8，新鲜度 1 调用 + codegraph 核心 ~6 + 单点验证
+交付通道 2）；轮数 71 → ~15-25；段 fresh/cr 随首调与轮数双降（cr 主降因
= 轮数降 × 每轮前缀降）。

验收口径（A = §1 基线，B = worktree 码同种子 p1_sub1_ab2 起跑）：

1. B 首调 fresh ≤ 20k（机制读数，确定性，不受 #40 步体方差影响）；
2. B 工具序列：探索 Bash ≤ 12；零前序已载出处的重跑重验（前序 file:line/
   实测命令/字段存在性）；前序零提及事实每条 ≤1 次单点验证、验存在即止；
   零 evidence 全量翻找；Read ≤ 6（scaffold 骨架+定点文件）；新鲜度经
   `dl codebase freshness` 留痕；
3. 段 fresh 合计降 ≥40%、cr 降 ≥45%、轮数 ≤30（单轮同口径参考，主口径是
   1/2 两条机制读数）；墙钟按 out÷rate 归因后登记（#30 双轴口径）；
4. 零 block；trace 质量不降（四要素齐备/出处逐条可溯源/新鲜度留痕——
   按 gate 方框逐条自查 B 轮 trace）；零编造；
5. pytest 全绿（新增/更新测试见 §4）+ nodes-index 摘要同步；
6. 混淆声明（预登记）：①A/B 均 fresh 段（子1 链头），无链形态差；②种子
   数值 4824.5% 与今日值 4947.7% 的漂移属 #18，两轮同种子同漂移面；
   ③总账单轮受步体方差（#40）影响，验收以首调 fresh + 工具序列形态为
   主口径（#13/#23）；④B 轮 子1 段携带 NEXT_PREP 附带交付（子2 交互步
   预处理并入）两臂同构；⑤**sync 触发面同构**：A 轮索引 674h 过期触发
   codegraph sync（B05+重查 B06）；实测 A 轮 sync 后 MAX(indexed_at) 未前进
   （sync 只重索引变更文件，全量未变时 MAX 不动——dl codebase freshness
   冒烟 674.6h 实证），B 轮面对同一 stale 判定、sync 触发面两臂同构，
   无环境态混淆；⑥`dl codebase freshness` 走模型 Bash 侧——node-rules
   台账段命令形 = `bash <_DLWF_ROOT>/scripts/workflow/dl-cmd.sh codebase
   freshness`（driver 同仓路径，_rewrite_hook_paths 同范式）：B 轮
   node-rules 冒烟已验路径指 worktree 树=新子命令当轮生效（验收面第三
   路径 #31 被机制覆盖，非 merge 后生效面）；purpose/selfcheck 只引
   命令名（「命令全文见 node-rules 发现台账段」），路径单源在 driver
   装配侧。

## 4. 实现清单（待实现时定稿）

- `dl_flow_nodes.py`：plan:1 Node += segment_tools 白名单；plan:1 子1 Step
  += segment_strip_project_context=True + purpose 材料边界条款 + selfcheck
  一条（注释登记第七例）。
- `scripts/workflow/dl_codebase.py`：新增 freshness 子命令（读
  .codegraph/codegraph.db MAX(indexed_at)，输出时间戳+距今+>72h 判定；
  无 db 时明示「无 codegraph 索引」非错误）。
- `scripts/workflow/dl_drive.py`：node-rules 发现台账段补 freshness 一句
  （若装配在该处）。
- `tests/`：白名单/strip 置位/条款关键词钉死/freshness 子命令单测。
- `skills/workflow-creation/references/nodes-index.md`：plan:1 条目子1 摘要
  同步（purpose 实质内容变更）。
- 不改：SEGMENT_CHAIN_NODES、MERGED_RUN_NODES、gate 文本、judge、
  pack_self_contained。

## 5. 实测收官（2026-08-19，A=p1_sub1_ab / B1=p1_sub1_ab2 / B2=p1_sub1_ab3 / B3=p1_sub1_ab4，同种子，ac-deepseek1 headless）

B 轮驱动法（runtime-audit #24/#25）：种子七件套（evidence 22 条 ≤u:4#5 +
state plan:1 sub_step_index=1 + last_judged_trace ≤u:4#5 + 段记录/链/stash
清零 + settings 名替换零残留 + **.claude/understands/<name>.md 产物文件**
[第七件，B1 轮发现缺失致模型 find/ls 翻 understand.md×4] + 包冒烟）→
`bash -ic` 内 `AC_WORKFLOW_LAUNCHER=<树>/scripts/workflow/dl-launch.sh
ac-deepseek1 --dl <name> --resume --headless`（A=主树，B=worktree 树）。
B3 种子 settings 补一条白名单 accommodate（worktree dl-cmd.sh 路径，见修3）。

| 指标 | A（main 310c5c9） | B1（三杠杆） | B2（+修1/修2） | B3（+修3+种子白名单） | B3 vs A |
|---|---|---|---|---|---|
| 首调 fresh | 44,040（cr=0） | 16,441（cr=0） | 19,453（cr=0） | 19,453（cr=0） | **-55.8%（B2/B3 逐字相同=机制读数钉死）** |
| 段 fresh 合计 | 86,601 | 73,284 | 75,428 | 71,318 | -17.7% |
| 段 cr 合计 | 2,670,464 | 2,090,368 | 1,637,120 | 1,003,776 | **-62.4%** |
| 段 out 合计 | 35,278 | 48,186 | 50,661 | 42,294 | +19.9% |
| 轮数（result 权威值） | 71 | 56 | 41 | 27 | **-62.0%** |
| 段 dur_api | 292.4s | 380.6s | 406.6s | 340.1s | +16.3% ⚠ |
| 成本 | $2.650 | $2.616 | $2.462 | $1.916 | **-27.7%** |
| Bash | 50 | 41 | 23 | 14 | **-72%** |
| 总工具调用 | 68 | 56 | 39 | 26 | -62% |
| 门控 | 一次通过 | 零 block | 零 block | 零 block | ✓ |

成本等效（cr×0.1 折 fresh，#13/#24 口径）：A 353,647 → B3 171,696 = **-51.4%**。

**修1/修2/修3 迭代链（B1→B2→B3 归因）**：
- **修1（机制，Step.pack_full_prior_boundary）**：B1 轮残余税根因一——P1-1
  把前序 statements.boundary 截断 100 字符，截断处恰是 file:line/机制结论
  （双×100 链出处被切成「f…」），复用钉死要求逐字引用→模型翻 evidence
  grep×6 + 前序已载事实重验 ~10 调用。置位后包内前序 boundary 保全文
  （包 11,257→17,147 字符），B2/B3 evidence 翻找**清零**、前序重验收敛到 ~3。
- **修2（文案，工具直用条款）**：B1 轮模型对 dl-cmd.sh/codegraph 元探查
  --help/ls/Read 脚本/which ~11 调用（新工具可见性税）。
- **修3（机制，命令路径按 driver 树分派）**：B2 轮残余税根因二——per-wf
  白名单规则 `Bash(bash ~/.dl-workflow/...:*)` 按**字面 ~** 前缀匹配，
  node-rules 发 _DLWF_ROOT 展开路径（worktree 绝对路径）不在任何白名单
  形态内，acceptEdits 下 freshness **3 连「requires approval」被拒**（B2
  trace q1 逐字实证）——模型转 settings 翻查×4/错误调用×2/手搓 mtime 判定，
  「freshness 困惑族」~12 调用的真根因是**权限墙**不是工具元探查。修3：
  生产发字面 ~（148d1e3 同形态），worktree 发 _DLWF_ROOT 绝对路径+种子侧
  settings 补白名单。B3 freshness 通道端到端兑现：B01 初判→B03 sync→
  B04 复判同命令（条款逐字形态）。**沉淀：#31 验收面第三路径的权限变体——
  worktree 路径不仅主树无新码，也不在 per-wf 白名单形态内。**

**B3 工具序列（理想最小形态逼近）**：freshness×2（初判+复判）→
understand.md 定点 Read×1 → sync×1 → dl codebase query×5（台账通道）→
Grep×7/Read×2（单点验证+有限掘进）→ 数据契约 3 → scaffold/落库 2。
零 evidence 翻找、零 understand.md 翻找、零 settings 翻查、零手写 SQL、
零错误调用（B02 `dl-cmd codebase sync` 误调 1 次=台账段已写明 sync 走
codegraph CLI，褶皱 1 调用登记不修）。

**验收逐条**：①首调 ≤20k **✓**（19,453，B2/B3 双样本逐字相同——包内容
确定则首调确定，机制读数钉死；-55.8%）；②工具序列 **✓**（Bash 14 vs A 50
[-72%]，探索类 ~12 边际达线；零 evidence 翻找/零 understand.md 翻找/
Read 4≤6/freshness 经 dl codebase freshness 留痕）；③段 fresh -17.7%
**未达预登记 ≥40%**（诚实归因：段 fresh 大头=工具输出增量逐轮进上下文，
杠杆作用在调用数 -62% 与前缀 -55.8%，大体积 codegraph/json 输出稀释合计
降幅——cr 才是上下文膨胀主口径）；cr -62.4% **✓**（≥45%）；轮数 27 **✓**
（≤30）；墙钟 +16.3% **未降**（见下归因）；④零 block ✓，trace 质量逐条
自查全过：四要素齐备（模块/可复用点/调用方/数据契约）、出处逐条可溯源
（前序复用标记 C4.2/C6/R1 逐字+codegraph 实测输出引用+Read 核实）、新鲜度
留痕全要素（时间戳+判定+sync+复判）、q6 材料边界自查枚举例外按条计数、
零编造；⑤pytest 1156 全绿（新增 14 例）+ nodes-index 同步 ✓；⑥混淆声明
全部按预登记处理，⑤修正定案：sync 只重索引变更文件、全量未变时
MAX(indexed_at) 不前进（B3 trace q1 实测 sync 后复判仍 stale=true），两臂
同面对无环境态混淆。

**墙钟归因（诚实登记，#30 双轴口径）**：dur_api ≈ out÷rate——A 35,278/
292.4s≈121 tok/s vs B3 42,294/340.1s≈124 tok/s，同端点速率稳定，墙钟差
+48s ≈ 输出差 +7.0k÷124 tok/s=+56s 拟合上=**输出量主导**。输出增长两成分
（输出构成三分归因法：thinking/text/tool_use）：①thinking 64,261→120,064
字符（1.9×）=条款驱动的逐事实 deliberation（复用 or 单点验证的逐条决策
开销）+逐字引用质量形态（复用钉死条款兑现，trace 证据更厚=质量形态）；
②tool_use 输入 31,628→12,873 字符（调用数 -62% 的直接兑现）。取舍明示：
逐字引用条款不撤（质量机制，u4-sub3/u4-sub4 同处置）；墙钟的进一步杠杆
在输出侧瘦身（thinking  deliberation 密度），非本轮杠杆作用面，登记观察项。

**遗留立项**：plan 族段链（plan:1-4 链内步 子3/子4 断链候选——须先补
条款缺口，#30 断链暴露效应）；plan:1 子2-6 strip 逐步核对；输出侧瘦身
（观察项）；段 fresh 合计降幅的工具输出体积稀释现象（#13 口径补注）。
amplitude 今日值 4947.7% 本轮未被触发（子1 无现状测量职责——勘察对象是
代码现状非因子数值）。
