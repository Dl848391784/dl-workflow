# plan:2 子3（锚点核验）成本优化设计

> 基线实例：p2_sub2_ab B 轮子3 段（2026-08-20，并行会话 p2-sub2-cost 验证轮
> 顺带跑过，免跑基线 #30）；B 轮实例：p2_sub3_ab（同种子 ≤plan:2#2，worktree 码）。
> 数值口径：种子 problem_statement 保持 4824.5% 不改（runtime-audit #25：
> 答案注入法的种子须与 A 轮逐字一致）；amplitude 今日值 4929.2% 与种子数值
> 漂移属 #18，两轮同种子同漂移面（p2-sub1 设计 §5 同口径）。
> 通用性约束（用户决议 2026-08-20）：条款全部机制/形态级，**避免 factor 化**——
> 禁把测试实例的因子名/文件面/数值写进引擎条款。

## 0. 范围与前置

本设计只覆盖 **plan:2 子3（锚点核验与假设标注，非交互验证型工作步）**。
子3 是断链后 fresh 段（p2-sub2-cost 节点级断链第六例已落地），无链税面；
子4 strip/pack 置位不在本设计（登记遗留）。并行约束：feat/p2-sub2-cost
未 merge（并行会话在飞），本分支从其 HEAD 切出，A/B 两轮同基（600bfb8），
main（p2-sub1-cost 三件：Node 工具白名单/子1 strip/#38）收口时合入——
**Node 白名单 -14.3k 不在本 A/B 读数内**，merge 后叠加生效。

## 1. 基线（A = p2_sub2_ab 子3 fresh 段，免跑基线）

免跑基线三查（#30）：①子3 代码两轮间零变更——A 轮跑的是 600bfb8（p2-sub2
L5 补款后），本分支=同 HEAD，B 轮前子3 唯一变更=本设计落地件，改前读数即
基线；②种子 evidence= p1_sub3_ab 全 29 条+本实例子1/子2 trace，B 轮种子=
p2_sub2_ab evidence 截 ≤plan:2#2（同一份子1/子2 trace 逐字相同=三查②
最强形态）；③段口径=fresh 段（断链后形态），两轮一致。

| 指标 | A（p2_sub2_ab 子3 段，600bfb8） |
|---|---|
| 首调 fresh | **61,141**（cr=0，fresh 段） |
| 段 fresh 合计（inputTokens） | 112,092 |
| 段 cr 合计 | 1,713,536 |
| 段 out 合计 | 51,065 |
| 轮数（result 权威值） | **53** |
| 段 dur_api | 367.6s |
| 工具调用 | 52（Bash×48/Read×1/Edit×3） |
| append-trace mech 拒 | **2**（④留痕贴扫描正则字面，占位词撞占位符扫描） |
| 门控 | 一次通过，零 block |
| 成本等效（cr×0.1 折 fresh） | 283,445 |

### 基线浪费分解（52 调用逐条归因）

| 浪费类 | 实例 | 定性 |
|---|---|---|
| 命令形态不兼容守卫 | `for f in ...` 循环 ×1 被安全守卫拦（simple_expansion），改 `ls -1` 重跑 | 纯税（#33②命令白名单兼容形态同族） |
| 双路径核验 | 主仓 8 文件 ls + **worktree 同 8 文件再 ls** | 纯税——锚点核验以主仓为真源，worktree 路径零判据价值 |
| transcript 翻找 | grep 会话 transcript jsonl 查 test_cases 路径 ×1 | 纯税（#16 元探查形态） |
| 锚点未命中宽搜掘进 | design 载 `web_ui/report.html` 未命中 → find 宽搜 ×4 + `report/latest/` 追查 ×2 替前步纠错定位 | 半税——检出偏差=三态标注职责；宽搜定位替代锚点=越界纠错 |
| 四类以外掘进 | amplitude 主 JSON meta/long_short 结构读 ×2 + daily gz 结构读 ×1 + A13 配对集合运算 ×1 + obq 计数 ×1（数据结构全文核验不在四类内） | 半税——数据前提存在性=ls 即止，结构分析归 execute |
| 接缝核验过度 | conftest.py/test_app.py/_section_compare.html(100 行)/_section_backtest.html 全文读 ×4 + U5 既有测试覆盖 grep ×1 | 半税——接缝=collect-only+存在性 grep 即止 |
| 占位符留痕自伤 | ④留痕贴扫描正则字面（含「待补/TODO」词形）撞 append-trace 占位符扫描，mech 拒 ×2 + Edit 修 ×2 + append ×3 | 返工褶皱（留痕形态缺口） |
| 合法核心 | 批量 ls ×1、sed 锚点行核实 ×4、grep 锚点/命名冲突 ×4、pytest --collect-only ×3、placeholder 扫描 ×2、目录 ls ×2、scaffold/Read/Edit/append 落库面 ~7 | 保留——executor 接地职责 |

纯税 ~4 + 半税 ~16 + 褶皱 ~4 ≈ 24/52 调用（46%）。

## 2. 杠杆选型

| 杠杆 | 置位？ | 依据 |
|---|---|---|
| **L1 Step strip**（segment_strip_project_context，第十一例） | **置位** | #23 第三核对「env 剥离边界」：四类核验（①文件/symbol 存在②测试接缝③命令可运行④No Placeholders 文本扫描）全=本仓事实核验，**无硬规则条号点名**——p1-sub3 否决理由（④=硬规则兼容须点名 H 条号）在本步不存在；交付物=留痕+三态，不引用 CLAUDE.md/auto-memory 内容；u4-sub3 核验步置位先例（第五例）。风险登记：strip 后 codegraph CLI 路径知识（CLAUDE.md §3）不在场——L2 复用钉死使 codegraph 新查询不必要（callers 已载），新 symbol 存在性 grep 兜底 |
| **L2 复用钉死（#25 枚举例外形态）+ 深度钉死（验存在即止/四类边界）** | **置位** | 基线 46% 调用是纯税/半税；用户决议「能用前序沉淀的 discovered/evidence 就尽量用」。材料前提（#33）：DS statements callers 字段逐字在包（p2-sub2 设计 §2 实证）+本节点子1/子2 trace 全文通道在包 ✓ |
| **L3 ④留痕形态钉死** | **置位** | 基线 mech 拒 ×2=占位词字面自伤；gate 判据三早已声明「检出声明不须附扫描命令/逐模式回显」——声明式留痕与判据同向（#34），零判据风险 |
| **L4 gate 双侧修文本** | **置位** | L2 的引用形态须进判据合法形态（双侧钉死纪律——判据一/二/五+判材边界当前只认「命令+返回概述」新取证形态，引用本节点子1/子2 trace 已载出处不在列，judge 可判「无出处」）。负判定条件零改动；改后必跑 replay 回归（tests/replays/replay_plan2_sub3.py） |
| **L5 replay 双侧 fixture** | **置位** | 新增引用形态 clean 载荷证放行面；既有 clean/vio1-5 回归证牙齿不塌（#15 抑制类钉句必双侧+测两侧） |
| pack_self_contained | 不置位 | #19 验证型步——产出新事实（四类核验留痕+三态），包外单点验证=合法职责面（枚举例外内）；p1-sub3/p2-sub2 双重否决先例 |
| pack_full_prior_boundary | 不置位 | 复用材料=DS callers 字段（摘要通道不截断 fields，p2-sub2 实证）+本节点留痕全文通道，不经 boundary 截断面 |
| MERGED 段内续步 | 不置位 | 步体太重（53 轮基线），非极小搬运型；plan:1 链峰值前科 |
| Node 工具白名单 | 不动 | p2-sub1-cost 已在 main 置位（Bash/Read/Edit/Skill），merge 后叠加生效；本 A/B 两臂同基无白名单=口径一致 |

## 3. 改法（dl_flow_nodes.py 子3 Step + 重放 fixture + 同步件）

### L1 机制

子3 Step 加 `segment_strip_project_context=True`（第十一例）。

### L2/L3 条款（purpose 追加，交付即止/格式真源补款之后）

复用与深度钉死（枚举例外形态）：
- 调用面/callers=交接包 DS statements callers 字段逐字引用，零重验；
  要素 file:line/文件清单=本节点子1 要素基线 trace 逐字引用，零重验；
  单元定义=子2 trace 全文在包，零重读 evidence。
- 例外按条配额：前序零提及的锚点（子2 新引入文件名/测试路径/symbol）
  单点核验 ≤1 次/锚点，**验存在即止**（ls/test -f/存在性 grep/
  pytest --collect-only 四形态）。
- 深度钉死：禁读文件全文/JSON 结构全文；禁主仓+worktree 双路径核验
  （主仓单路径）；禁 transcript/会话日志翻找；锚点未命中=单点复核一次后
  按三态标注（证伪回子2/假设留子5），禁宽搜掘进替前步纠错；
  四类以外零取证（数据结构全文/生成物路径/覆盖率分析归 execute）；
  命令形态兼容守卫（禁 for 循环展开，用显式清单单命令）。
- ④留痕形态（L3）：声明式「逐单元扫描四模式零命中」即合规——
  禁贴扫描正则字面/模式词字面（占位词字面撞 append-trace 占位符扫描
  =自伤拒收）。

selfcheck 补一条：「前序已载出处逐字引用零重验了吗（例外按条配额、
验存在即止、四类以外零取证）？」

### L4 gate 双侧修文本（判据一/二/五+判材边界，负判定零改动）

判据一合法形态补：「引用本节点子1/子2 trace 或交接包 DS statements
已载出处（原命令+返回概述逐字引用，形如「caller=1（run，子3
codegraph）」）即合规」。判据二合法形态补引用形态差异化留痕合规。
判据五补「单元核验段=引用前序出处+新核验混合即合规」。判材边界补：
「前序留痕出处（子1/子2 trace 载荷内可见）的逐字引用=出处留痕在场」。

### L5 replay fixture

tests/replays/replay_plan2_sub3.py 增 clean2_引用前序出处载荷
（U1-U3 核验段全部引用 S1/S2 已载出处+单点新核验混合形态），
EXPECT=PASS；既有 clean/vio1-5 回归。

### 同步件

- tests/test_dl_flow_engine.py：plan:2 strip flags 断言更新（子3 置位）。
- skills/workflow-creation/references/nodes-index.md plan:2 行子3 摘要。
- skills/workflow-creation/references/cost-optimization.md：收口沉淀
  （编号取收口时 git log 最大值+1，防并行抢占）。

## 4. 预登记（B vs A，验收口径）

| 指标 | A 基线 | B 预登记 | 判别 |
|---|---|---|---|
| 首调 fresh | 61,141 | ≤49,500（strip -11.9k 探针口径，条款文本略回补） | 机制读数 |
| 轮数 | 53 | ≤22（-58%） | 主杠杆 |
| 工具调用 | 52 | ≤20 | 纯税/半税/褶皱消灭 |
| 段 fresh 合计 | 112,092 | -35% 起 | |
| 段 cr 合计 | 1,713,536 | -60% 起（轮数主驱动） | |
| 成本等效 | 283,445 | **-50% 起** | 主验收轴 |
| 段 out | 51,065 | ≤40k（质量形态[逐字引用厚度]保留，褶皱成分消灭） | #30 两成分口径 |
| 段 dur_api | 367.6s | ≤260s（out÷rate 拟合归因，双轴分开登记） | #30 墙钟口径 |
| append-trace mech 拒 | 2 | 0 | L3 兑现 |
| 门控 | 零 block | 零 block | 硬约束 |

trace 质量逐条自查（防 Goodhart）：每单元四类核验留痕齐备、三态按单元
标注、假设附置信度×影响、出处（新核验命令+返回概述 或 前序逐字引用）
在场、零编造——引用形态不得稀释执行接地（锚点仍条条有出处，只是出处
生产时间前移）。

混淆声明：①B 种子=p2_sub2_ab evidence 截 ≤plan:2#2+state 四字段同步
plan:2#3 入口+settings 名替换+段记录/链/stash 清零（种子八件套族，
无确认级补件——plan:2#3 前无读回步）；②amplitude 今日值 4929.2% vs
种子叙事 4824.5% 漂移=#18 两轮同漂移面，B 轮若对 amplitude 数据文件做
存在性核验命中真实值属合法，不剔出不误判；③A/B 两臂均无 Node 白名单
（main 未合入），首调读数不含 -14.3k 白名单收益；④judge replay 读数与
live 门控分开登记。

## 5. 实测收官（待 B 轮后补）

## 6. 遗留（待收官补）
