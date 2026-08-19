# understand:4 子3（验收方式设计）耗时/token 优化设计——断链 + Step 级 strip + 复用钉死（前序留痕出处零重验）

> 日期：2026-08-19 · 分支 feat/u4-sub3-cost · 状态：设计中
> 上游：designs/u4-sub2-cost-optimization-design.md（u:4#2 strip+复用钉死，
>      遗留立项=本设计）；designs/u2-sub3-cost-optimization-design.md（#20 断链）；
>      designs/u3-sub2-cost-optimization-design.md（#24 续步 vs 断链抉择口径）；
>      designs/u3-sub3-cost-optimization-design.md（#25 复用条款收紧形态）。
> 触发 = 用户指令（2026-08-19）：「优化 understand:4 的 step3，耗时和 token
> 消耗要大幅降低，能用前面步骤沉淀下来的 discovered 和 evidence 就尽量用，
> 避免 factor 化；跑测试工作流用 ac-deepseek1；amplitude 今日值 4947.7%」。
> 数值口径：种子 problem_statement 保持 4824.5% 不改（runtime-audit #25：
> 数值漂移属 #18 混淆面）；4947.7% = 今日实际值，若运行中被问以此作答。
> 避免 factor 化 = cost-optimization #2：全部杠杆为框架通用机制/通用措辞，
> 零项目语义耦合（条款不点名 pytest/report/因子等任何项目构件）。

## 1. 基线实测（免跑基线——u4_sub2_ab B 轮 seg#4 即同种子同码基线）

**基线来源声明**：u4_sub2_ab B 轮（2026-08-19 15:19-15:22，HEAD 83bdf8f=
当前 main）的 step3 段（drive-stream seg#4，session 417f0a2a 链内续跑）——
step3 代码当日零变更（u4-sub2-cost 只动 step2），B 轮 step2 trace 与本设计
种子 evidence 内的 SC#2 trace 是同一条 = 同种子同码基线，零成本复用。
u:4#3 是链内步（u:4 在 SEGMENT_CHAIN_NODES），基线形态 = 链续跑段。

| 指标 | 基线 A（seg#4） |
|---|---|
| 段墙钟 | ~96s（duration_api 95,813ms + gate judge 段外） |
| 轮数（result 权威值） | 18 |
| 段 input（fresh） | 53,555 |
| 段 cache_read | 504,576 |
| 段 output | 12,356 |
| 首调 fresh | 44,747（**cr=0——链边界恒冷铁证**） |
| 成本 | $0.829 |
| 工具序列 | Bash×13 探索 + scaffold→Read→Edit→append（17 调用） |
| 门控 | 一次通过，零 block |

### 成本归因（工具序列逐条核对，runtime-audit #26 三分诊）

13 个探索 Bash 逐条分类（对照交接包材料：SC#1/SC#2 trace 全文 + 前序三节点
归一化 statements，包冒烟 13,315 字符实证全文在包）：

| 类别 | 调用 | 判定 |
|---|---|---|
| 测试框架存在性（pytest --version、ls test_cases+grep testpaths） | 2 | **合法本步职责**（u4-sub2-cost 把手段存在性勘察从子2 推给子3=本步职责；前序留痕零提及测试框架） |
| 报告渲染路径定位（find report.html / find ob_quality 目录 / ls summary|backtest 结果目录 ×5） | ~6 | **纯税或半税**——落盘 JSON 值存在性=SC#1/SC#2 Bash 实测已证（包内逐字）；模板文件=u:1#6 statements 双乘机制 file:line 已证（包内）；渲染报告页存在=用户问题陈述自述「report/latest 页面显示 4824.5%」一手证实 |
| web_ui 路由/模板勘察（grep app.py ×2、ls web_ui/templates、ls web_ui） | 4 | **半税**——模板存在性包内已证；路由存在性同被用户自述覆盖；app.py 内部结构勘察超出「手段存在性」所需粒度 |
| evidence 翻找 | 0 | 包尾「按需 Read」邀请未被利用（正面） |

**三层瓶颈分诊（cost-optimization #1/#20/#23）**：
①**段边界层（主税）**：首调 44,747 = 链税（继承 step2 段 transcript 跨进程
--resume 全量重写，deepseek 会话隔离缓存下 cr=0 恒冷——#20 断链判据三要素
全中：provider 会话隔离 + 链首调 cr=0 + fresh 段恒定地板存在）。
②**前缀层**：项目上下文 ~11.9k 未剥（u:4#3 是节点内仅剩的未置位 strip
工作步——#1/#2 已置位）。
③**步体层**：13 探索 Bash 中 ~8-10 纯税/半税（重复验证包内已证存在性 +
超出存在性粒度的掘进）= 轮数 18 的主驱动。

**续步（MERGED）否决**（#24 抉择口径）：步体 13+ 调用非「极小搬运型」，
deepseek 续步暖率彩票（u:3 实测 1/4、u:1 D 轮全冷）——断链收益确定，
续步 EV 两节点已证伪，不立项。

## 2. 方案（三杠杆：断链 + strip + 复用钉死；零新机制、零 factor 化）

### L1 u:4 移出 SEGMENT_CHAIN_NODES（机制，断链第五例：u:1/u:2/u:3 后）

前置核对（#20 断链判据 + 交接包材料完备性逐字段核对）：
- **provider 缓存语义**：ac-deepseek1/deepseek-v4-flash = 会话隔离缓存
  （P0 实证 [[deepseek-stream-cache-session-scoped]]），基线首调 cr=0 = 链
  恒冷铁证（与 u:2 两轮 cr=0、u:3 71.9k/106.8k 同形态）。
- **材料完备性**：u:4 各步输入契约逐字段核对——#2 input=step1 候选（SC#1
  trace 全文在包 ✓）；#3 input=step2 三要素（SC#2 trace 全文在包 ✓，本种子
  冒烟实证）；#4 input=step3 验收方式（SC#3 trace 全文在包 ✓）；#1/#5 交互
  步不走链。断链后交接包通道完整覆盖，零材料缺口。
- **链税读数**：基线 #3 首调 44,747（cr=0）；u4_sub2_ab 同流 #4 首调
  74,227（cr=512≈冷）——两段合计 119k 链税。断链后各步 fresh 段恒定地板
  （#2 实证 13,658 已置位 strip；#3 本设计 L2 后 ~14k；#4 ~25k 未 strip）。
- **作用面声明**：白名单是节点级——#3 断链必然连带 #4 断链（#4 同为受益
  方：74.2k→~25k，正向外部性，不进本设计验收面）；#2 是链头恒 fresh
  spawn 零变化；gate/judge 零变更；残留链（在飞实例 segment_chain state）
  下次查询名单自然失配=优雅降级（机制内行为，u:2/u:3 断链同路径）。
- engine 注释「u:4 与 plan 族链峰值未突破且无降本指令，保留（surgical）」
  的前提（无降本指令）已被本次用户指令推翻；plan 族仍无降本指令，保留。

### L2 Step 级 segment_strip_project_context 置位 u:4#3（机制，第五例/u:4 内第三例）

置位前置核对（#23 两核对 + u3-sub1 第三核对「env 剥离边界」）：
- **交付物正文不引用自动加载文档**：子3 交付 = 四法选择+理由 / 可行性三态
  +出处 / 时机标注 / 证据形式——材料 = 交接包内 SC#1/SC#2 trace 全文 +
  用户问题陈述 + Bash 单点验证结果，无点名项目硬规则条号职责（与 u:3#1
  「约束分类须点名规则条号=一等材料」反优化**不同型**；与 u:4#1/#2 同型）。
- **逐步工具需求**：Bash（存在性单点验证/codegraph/scaffold/落库）+ Read
  （骨架）+ Edit（骨架）——全在 Node 白名单（u4-sub1-cost L1 已置位）内。
- **gate 判材**：judge 读 read_evidence_for_step 裁剪的 trace，不读项目
  上下文——剥 env 不影响判侧。
- MergedSession 不适用（u:4 出链后各步恒 fresh spawn，不入 MERGED——
  §1 续步否决）。

### L3 复用钉死条款进 purpose/selfcheck（文案，#25 收紧形态：默认零重验+枚举例外+按条配额）

purpose 末追加（通用措辞，零项目语义）：

> 材料边界（复用钉死）：前序留痕所载出处（实测命令/落盘文件/file:line/
> 机制结论）全部在交接包「本节点各步最新留痕」节与前序节点摘要节全文——
> 手段存在性出处逐字直接引用即合法（「复用 <节点>子N 留痕：<命令/路径/
> file:line>（出处逐字）」形态），零重跑重验（前序已跑通的命令不重跑、
> 已读过的文件不重读、已核的 file:line 不重修）；用户问题陈述自述可见/
> 可读的页面·数字·报告 = 存在性一手证据，零重验。枚举例外（逐条可判定
> 的二值条件）：某条标准的验收手段在前序留痕与用户自述中**从未出现**
> （命令/路径/工具名零提及）→ 该手段单点存在性验证一次（每条标准最多
> 一次，验存在即止，禁顺手掘进内部结构）。零 evidence 全量翻找（材料已
> 在交接包）。

selfcheck 追加：「存在性出处逐字引自交接包/用户自述吗（零重跑重验）？
前序未出现的手段每条标准 ≤1 次单点验证、验存在即止吗？零 evidence 全量
翻找吗？」

**条款形态核对（#25）**：默认零重验 + 枚举例外（「前序留痕零提及」=逐条
二值判定，非「缺口/必要时」开放谓词）+ 按条配额（#14 上限≠配额：每条
标准 ≤1 次，非总上限）+「验存在即止禁掘进」（基线 app.py 内部结构勘察
4 调用 = 超出存在性粒度的掘进形态，条款显式排除）。

**判侧已对齐、gate 文本零变更**（三重核对）：
①方框一 block 条件=「声称手段存在但未附任何命令/路径/文件级定位」——
复用形态含逐字命令/路径/file:line = 「附了具体命令或具体文件路径」合规
形态在场；②方框一已钉「不得要求『可核验』『实际执行留痕』式更强出处」
——复用引用不触发任何 block 条件；③合法正例「Bash 实测 `命令` 可跑通，
Read …确认在场」与复用引用同形态（命令+路径级出处），judge 判材边界
明示子1/子2 trace 在载荷内=复用出处可见可查。故不动 gate 文本 =
零重放回归负担（v2.9x framing 反转成果不动）。

### 不做的事（关闭项登记）

- **pack_self_contained 不置位**（#19 判别）：本步是验证型步——产出新事实
  （三态处置结果），包外单点验证是合法职责面（枚举例外内），与 u:4#2 同
  结论。包尾通用「按需 Read」邀请由 L3 条款点名「零 evidence 全量翻找」
  对冲（基线实证零翻找，风险面低）。
- **u:4#4 的 strip 不置位**：逐步核对未做（#4 是消费装配步，pack 完备性
  核对未做），留后续立项；#4 仅受 L1 断链正向外部性。
- **续步（MERGED_RUN_NODES）不立项**：§1 否决（#24）。
- **plan 族链不动**：无降本指令，链峰值未破，surgical。
- **gate 文本零变更**：见 L3 三重核对。
- **judge 成本不动**：判材裁剪（v2.12）已在。

## 3. 预期与验收（预登记，机制读数为主口径 #13/#23）

预期（探针预算，机制确定性部分）：首调 fresh 44,747 → ~14k（断链 → fresh
段恒定地板 ~25.5k [harness 4.8k + node-rules ~2k + 交接包 13.3k + step
prompt ~4k，u:4#2 实证 13,658 同型] + strip -11.9k env 剥离 [三处同口径
实证值]）；探索 Bash 13 → ≤4（测试框架等前序零提及手段的单点验证）；
轮数 18 → ~8；段 fresh/cr/墙钟随轮数与首调双降（cr 主降因 = 断链灭
119k 级单调涨继承重写）。

验收口径（A = §1 基线 seg#4，B = worktree 码同种子 u4_sub3_ab 起跑）：

1. B 首调 fresh ≤ 15k（机制读数，确定性，不受 #40 步体方差影响）；
2. B 工具序列：探索 Bash ≤ 4；零包内已证出处的重跑重验（前序实测命令/
   落盘文件/file:line）；零 app.py 类内部结构掘进；Read 仅 scaffold 骨架；
3. 段 fresh 合计降 ≥45%、cr 降 ≥55%、墙钟降 ≥30%（单轮同口径参考，
   主口径是 1/2 两条机制读数）；
4. 零 block；trace 质量不降（四法+选择理由/三态处置+出处/时机标注/证据
   形式齐备——按 gate 方框逐条自查 B 轮 trace）；存在性出处 100% 可溯源
   （包内逐字引用或按条单点验证留痕），零编造；
5. pytest 全绿（新增/更新测试见 §4）+ nodes-index 摘要同步；
6. 混淆声明（预登记）：①A 是链续跑段（上下文形态=继承 transcript）、B
   是 fresh 段（上下文形态=交接包）——内容等价（包载 SC#1/SC#2 全文），
   首调差值按机制分解（链税 ~19k + env ~11.9k）不混入步体方差；②#4 段
   断链外部性两臂形态不同（A 链/B fresh），#4 读数只登记不验收；③种子
   数值 4824.5% 与今日值 4947.7% 的漂移属 #18，两轮同种子同漂移面；
   ④总账单轮受步体方差（#40）影响，验收以首调 fresh + 工具序列形态为
   主口径（#13/#23）。

## 4. 实现清单

- `dl_flow_engine.py`：SEGMENT_CHAIN_NODES 移除 "understand:4" + 注释更新
  （断链第五例，降本指令已到；plan 族保留）。
- `dl_flow_nodes.py`：u:4#3 Step += `segment_strip_project_context=True`
  （注释登记第五例）+ purpose 材料边界条款 + selfcheck 一条。
- `tests/test_dl_drive.py`：链测试更新——test_chain_resume_on_match 夹具
  节点 u:4→plan:1（u:4 出名单）；新增 u:4 断链测试（镜像 u:3 形态：出
  CHAIN 且不入 MERGED + 续链返 None）；相关注释同步。
- `tests/test_dl_flow_engine.py`：TestSegmentSpawnOverrides ——
  test_u4_other_steps_no_step_strip 更新（#3 翻转为置位，钉死 #4/#5 仍
  不置位）+ 新增 test_u4_step3_step_level_strip（env 双开关 + tools 白
  名单钉死）+ test_u4_step3_reuse_clause_pinned（purpose/selfcheck 条款
  关键词钉死防静默丢失）。
- `skills/workflow-creation/references/nodes-index.md`：u:4 条目子3 摘要
  同步（purpose 实质内容变更）。
- 不改：driver 机制代码（断链=白名单摘除零新机制）、gate 文本（§2 L3
  三重核对）、MERGED_RUN_NODES、plan 族链、judge。

## 5. 实测收官（2026-08-19，u4_sub3_ab 同种子起跑，ac-deepseek1 headless，worktree 码 4e7c084）

B 轮驱动法（runtime-audit #24/#25）：种子五件套（evidence 19 条 ≤SC#2 +
state sub_step_index=3 + last_judged_trace 裁至 ≤u:4#2 + 段记录/链/stash
清零 + settings 三件套 grep 验 name-agnostic=0 + pack 冒烟 13,315 字符
SC#1/SC#2 全文在包）→ `bash -ic` 内 `AC_WORKFLOW_LAUNCHER=<worktree>/
scripts/workflow/dl-launch.sh ac-deepseek1 --dl u4_sub3_ab --resume
--headless`。代码路径核验：B 首调 fresh 15,309（A 44,747 的 -65.8%，
幅度 ≈ 链税 ~17.5k + env 剥离 ~11.9k 探针预算）+ 段 prompt 内条款关键词
「零重跑重验/验存在即止/每条标准最多一次」全命中 = 断链/strip/条款三杠杆
确由 worktree 码生效。

| 指标 | A（u4_sub2_ab seg#4，链） | B（u4_sub3_ab seg#0，断链+strip+复用） | Δ |
|---|---|---|---|
| 首调 fresh | 44,747（cr=0） | 15,309（cr=0） | **-65.8%** |
| 段 fresh 合计 | 53,555 | 22,494 | **-58.0%** |
| 段 cr 合计 | 504,576 | 231,808 | **-54.1%** |
| 段 out 合计 | 12,356 | 15,875 | +28.5% |
| 轮数（result 权威值） | 18 | 10 | -44% |
| 段 dur_api | 95.8s | 123.2s | +28.6% ⚠ |
| 成本 | $0.829 | $0.681 | -17.9% |
| 工具序列 | Bash×13 探索+落库 4 | scaffold→Read→**bs4 单点×1**→Edit→落库（9 调用） | 探索 Bash 13→**1** |
| 门控 | 一次通过 | 一次通过，零 block | ✓ |

成本等效（cr×0.1 折 fresh，#13/#24 口径）：A 104,013 → B 45,675 =
**-56.1%**。

验收逐条：①首调 ≤15k **边际超 2%**（15,309）——floor 探针预算 ~25.5k
低估 ~1.7k（step3 段 prompt 比 step2 长：purpose+gate 文本更大；step2
同机制实证 13,658）；机制分解幅度全确认（44,747-15,309=29,438 ≈ 链税
~17.5k+env ~11.9k），主口径=机制读数非整数值线；②探索 Bash 1 ≤4 ✓——
唯一例外 bs4 可用性单点验证（HTML 提取手段前序零提及=枚举例外合法），
零包内已证出处重验（pytest 框架存在性经复用 ScopeAndConstraints C7.2
逐字出处解决，基线的 pytest --version/ls test_cases/grep testpaths 3
调用全灭）、零 app.py 类掘进、Read 仅骨架 ✓；③fresh -58% ≥45% ✓、
cr -54.1%（预登记 ≥55% 边际差 0.9pt）、**墙钟未降反 +28.6%**（见下
归因）；④零 block ✓，trace 质量逐条自查全过：四法+选择理由（含「经典
映射功能→demonstration 不适用为主」排除式论证）、三态处置（存在附
逐字出处/待建=提取比对断言脚本进 plan）、时机 triggered 汇总声明、证据
形式锚定 review:0 消费形态；存在性出处 100% 可溯源（复用引用 6+ 处逐字
可回查包内 SC#1/SC#2/u:3 statements），零编造 ✓；⑤pytest 1139 全绿
（新增 4 例：u4 断链×2/u4#3 strip/条款钉死；链夹具 u:4→plan:1）+
nodes-index 同步 ✓；⑥混淆声明全部按预登记处理 ✓。

**墙钟归因（诚实登记，双轴验收 #13 的输出侧补丁）**：dur_api ≈ out/
rate——四个同端点样本生成速率稳定 121-129 tok/s（u4_sub2_ab A 16.5k/
136s≈121、B 8.2k/65s≈127、本 A 12.4k/96s≈129、本 B 15.9k/123s≈129），
墙钟差 +27s ≈ 输出差 +3.5k ÷ 129 tok/s，**段墙钟被输出量主导**。输出
增长两成分：①复用钉死的逐字引用形态（trace 证据本身是交付物，引用
更长=质量形态非浪费）；②scaffold 返工褶皱（3 Edit+1 grep 待填+1 重
Read=4/9 调用=格式迭代，步无关 scaffold 行为）。token 轴：out +3.5k
远小于 in+cr 节省（等效 -58.3k），成本 -17.9%；墙钟轴：生成主导下
输出量即墙钟，本轮墙钟目标未达——取舍明示：逐字引用条款不撤（质量
机制），墙钟的进一步杠杆在输出侧瘦身（trace 措辞密度），非本轮三杠杆
作用面，登记为观察项。

**#4 段外部性登记（不进验收面）**：断链连带 #4 fresh 段——首调 74,227
→30,443（-59%，无 strip 的纯断链读数）、in -43%、cr -49%；out 7.6k→
25.1k（3.3×，step4 purpose 未动+1 次 append 重试褶皱）、dur 60→187s
（同输出主导归因）。#5 确认级读回（P3-1）机械装配 0 token 符合既有
设计。**遗留立项**：u:4#4 strip 置位（逐步核对未做）；plan 族链重审
（无降本指令，保留）；墙钟输出侧瘦身（观察项）。amplitude 今日值
4947.7% 本轮未被触发（step3 无现状测量职责）。

## 6. B2 复测（2026-08-19 同种子第二轮，worktree 码 4fc87aa）——墙钟反转确认 + #4 外部性根因定案

B1 墙钟 +28.6% 是单样本，补 B2 验证「out÷rate 输出主导」归因。驱动法
同 §5（种子复原时补核一处：B1 后 state 已推进 plan:1，复原须 phase/
index/sub_index/node 四字段同步回 understand/1/4/understand:4——只改
node 撞 normalize_state 一致性校验 rc=1，种子复原六件套补此字段组）。

| 指标 | A（链基线） | B1 | B2 | B2 vs A |
|---|---|---|---|---|
| 首调 fresh | 44,747 | 15,309 | 15,349 | **-65.7%（双样本稳定，机制确定性读数）** |
| 段 fresh | 53,555 | 22,494 | 21,305 | -60.2% |
| 段 cr | 504,576 | 231,808 | 103,424 | **-79.5%** |
| 段 out | 12,356 | 15,875 | 11,795 | -4.5% |
| 轮数 | 18 | 10 | 6 | -66.7% |
| 段 dur_api | 95.8s | 123.2s | 93.0s | **-2.9%** |
| 成本 | $0.829 | $0.681 | $0.510 | **-38.5%** |
| 探索 Bash | 13 | 1 | 1 | -92% |
| 门控 | 一次通过 | 零 block | 零 block | ✓ |

**step3 结论（双样本定案）**：token 轴全部稳定复现（首调 15.3k 双样本
±0.3%=机制读数钉死）；墙钟 B2 91-93s ≤ 基线 96s——B1 的 123s 确为
scaffold 返工褶皱（3 Edit+grep 待填+重 Read=4/9 调用）+ 输出量离群
（15.9k vs B2 11.8k）叠加的单轮方差，out÷rate 归因成立（B2 out/rate
≈91 tok/s 段内含思考，总时长与输出量级拟合）。轮数 18→6-10、探索
13→1、成本 -18~-38% 双样本全达预登记主口径（①②条）。

**#4 外部性根因定案（双样本结构性，非方差）**：B2 step4 = 24 轮/253s/
$1.798/out 34,055/首调 30,525（cr=0）——与 B1（10 轮/187s/$1.110/
out 25,114/首调 30,443）同向离群，对照链内两样本（A 轮 11 轮/62.8s/
out 7,537、B 轮 11 轮/60.2s/out 7,609）结构性恶化。根因 = **断链暴露
u:4#4 的两个既有条款缺口**（链内时由前步会话携带格式上下文掩盖）：
①**格式猎捕**（cost-optimization #26）——B2 step4 工具序列 ls/grep
~/.dl-workflow/designs 反推【text】/【statements】载荷格式 5+ 调用
（u:3#4 已有「格式真源=scaffold 骨架+报错文案」钉死条款，u:4#4 没有）；
②**evidence 元探查**——grep evidence '"statements"'/python3 读 evidence
全量（包尾「按需 Read」邀请，pack_self_contained 未置位）。首调 token
两样本稳定 -59%（30.4-30.5k）= 断链对 #4 的前缀收益成立，但步体爆炸
吃掉总账（节点级 #3+#4：A $1.765/156s vs B2 $2.308/346s）。**处置**：
不回滚断链（#20 三要素全中的纯税机制，step3 双样本达标；回滚面=白名单
恢复一行），u:4#4 立项内容从「strip 置位」扩为「strip + 格式真源钉死
（#26 条款平移）+ pack_self_contained 核对（#16）」三件套——u:3#4 同
配方实测 22→5 调用/cr -86%，预期 #4 段回到 ~$0.3-0.4/60-90s。
