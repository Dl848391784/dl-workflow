# plan:3 子4（可用性核验）成本优化设计

> 基线实例：p3_sub3_base 子4 段（2026-08-20，并行会话 p3-sub3-cost 基线臂
> 顺带跑过子4 后收段，免跑基线 #30）；B 轮实例：p3_sub4_ab（同种子
> ≤plan:3#3，worktree 码）。
> 数值口径：种子 problem_statement 保持 4824.5% 不改（runtime-audit #25：
> 答案注入法的种子须与 A 轮逐字一致）；amplitude 今日值 4929.2% 与种子
> 数值漂移属 #18，两轮同种子同漂移面（p2-sub1/p2-sub3 设计同口径）。
> 通用性约束（用户决议 2026-08-20）：条款全部机制/形态级，**避免 factor
> 化**——禁把测试实例的因子名/文件面/数值写进引擎条款。

## 0. 范围与前置

本设计只覆盖 **plan:3 子4（可用性核验与假设标注，非交互验证型工作步）**。
并行约束：feat/p3-sub3-cost 在飞（并行会话，步级断链第三例 ("plan:3",3)
+ 子3 strip 第十五例），本分支从 main（fd071a2）切出，逐文件改动面
（子4 Step / SKIP_STEPS 集 / 两个测试文件 / replay 载荷）与其错位，
SKIP_STEPS frozenset 行与 test_chain_skip_steps_constant /
test_p3_other_steps_no_step_strip 三处收口时并轨（union 语义）。
**plan:3 Node 工具白名单（五件）已在 main**——A/B 两臂同有，-14.3k
已在基线读数内，非本轮收益。

## 1. 基线（A = p3_sub3_base 子4 链内段，免跑基线）

免跑基线三查（#30）：①子4 代码两轮间零变更——A 轮跑的是 p3-sub2-cost
worktree launcher（=main fd071a2，子4 无人在改），B 轮前子4 唯一变更
=本设计落地件；②种子 evidence=p3_sub3_base 全量 trace 截 ≤plan:3#3
（B 轮种子与 A 轮子4 实际消费的前序 trace 同一份逐字相同=三查②最强
形态）；③段口径=A=链内段（resume 子3 会话 68288809）vs B=fresh 段——
口径差异即 L1 断链的测量面，写进混淆声明（p2-sub2-cost 同手法）。

| 指标 | A（p3_sub3_base 子4 段） |
|---|---|
| 首调 fresh | **190,802**（cr=1,024，链恒冷——子2+子3 transcript 冷重写） |
| 段 fresh 合计（inputTokens） | 193,388 |
| 段 cr 合计 | 1,446,016（15 轮 × ~96k/轮=携带税主导） |
| 段 out 合计 | 19,134 |
| 轮数（result 权威值） | **15** |
| 段 dur_api | 151s |
| 工具调用 | 14（Bash×11/Read×1[骨架]/Edit×1/append×1） |
| 门控 | **未判**（driver 收段死于 gate 前；①skill 存在性核验缺位
=基线自身不合规形态，若判大概率撞方框四漏绑定核验） |
| 成本等效（in+cr×0.1） | 337,990 |

### 基线浪费分解（11 Bash 逐条归因）

| 浪费类 | 实例 | 定性 |
|---|---|---|
| 携带税 | 首调 190,802 + 每轮 ~96k cr——子2+子3 transcript 随每调重读 | **主税**（#24 携带税，断链测量面） |
| 同面复探·新鲜度 | codegraph 新鲜度×4 命令（dl-cmd 查 + sqlite3 indexed_at + COUNT files + date 取值） | 纯税——同一事实单命令一次即止 |
| 同面复探·venv | venv python 版本 + pytest 可用性 + pyarrow/mypy/ruff module + venv bin entry points 四面重叠 | 半税——每绑定④单命令验存在即止 |
| 合法核心 | which codegraph、db 存在性、scaffold/Read 骨架/Edit/append | 保留——本步新核验职责面 |
| ①缺位 | skill 存在性核验零命令（不合规少做事，非节省） | 合规欠账——B 轮以引用形态零新命令补齐 |

## 2. 杠杆选型

| 杠杆 | 置位？ | 依据 |
|---|---|---|
| **L1 步级断链**（SEGMENT_CHAIN_SKIP_STEPS += ("plan:3",4)，步级第四例） | **置位** | #20 判据：deepseek 会话隔离缓存下链首调恒冷（A 首调 190,802 cr=1,024 实锤）+#24 携带税主导（段 cr 1.45M/15 轮）。前置=交接包材料完备性逐字段核对：子4 input=step3.binding_proposals，本节点前序 trace 全文通道在包（子1/2/3 最新 trace，v2.12 裁剪规则）——起跑前 handoff_pack 冒烟核验（五件套⑤）。残留链记录下次查名单自然失配无需迁移。#30 断链暴露效应核对：后续步子5 resume 子4 fresh 会话=携带量**变小**（子4 一段 vs 子2+3+4 三段），无 fresh 化暴露面；子5 载荷格式要件/mech 五键校验/scaffold 三通道在册（v2.33/v2.117），非链携带格式上下文依赖型。暴露面预登记（#20 补）：B 轮顺带跑子5 时登记其首调/轮数，子5 轮数上限 ≤A 轮链内形态 |
| **L2 Step strip**（segment_strip_project_context，第十六例——p3-sub3-cost 在飞占第十五） | **置位** | #23 第三核对「env 剥离边界」：交付物=四类核验留痕+三态标注，**正文零引用 CLAUDE.md/auto-memory 内容**——①出处=子2 留痕逐字引用（在交接包）；②which/版本冒烟命令名来自子3 绑定提案（包内）；③MCP 配置定点 Read（路径来自子2 留痕）；④存在性命令。gate 形式要件/合法正例无一条要求引 CLAUDE.md 条号。核验步置位先例=u4-sub3（第五例）/plan:2#3（第十二例）。风险登记：strip 后 CLAUDE.md §3 codegraph 新鲜度 SQL 不在场——L3 深度钉死把 ② 收窄为 which+版本单命令，新鲜度 SQL 非形式要件（gate 合法形态=which 返回路径即合规） |
| **L3 复用钉死（#39 核验步形态：出处生产时间前移+深度钉死清单）** | **置位** | 用户决议「能用前序沉淀的 discovered/evidence 就尽量用」。①skill 条目存在性=子2 注册表清点留痕（available-skills 列表行/磁盘枚举/SKILL.md frontmatter 读取记录）逐字在交接包，引用零重验（禁重复 ls/Read 子2 已核实同一路径）；枚举例外=绑定对象子2 零出处（子3 新引入）单点补一次。②③④=本步新核验职责，深度钉死：每绑定每类单命令验存在即止，禁同面复探（基线新鲜度×4/venv×4 同面），禁数据结构全文读，四类以外零取证。材料前提（#33）：复用材料=子2/子3 trace 全文通道在包，不经 boundary 截断面 ✓ |
| **L4 交付即止（#37）+ 格式真源（#26）补款** | **置位** | 平移条款，防落库后徘徊与格式猎捕（基线无此两族=方差防守，p2-sub4 #40 同定位） |
| **L5 gate 对照组重放→双侧（条件置位）** | **先重放后定** | L3 的引用形态（「引用子2 留痕：…」）是否落在现 gate 判据一合法形态（「注册表列表行引用」）内=判据×条款接口核对。程序（#39）：新增 clean2_引用子2留痕载荷跑**改前 gate**——误 block 实锤才改文本（判据一合法形态补引用形态+判材边界钉句，负判定零改动），随后 replay 双侧回归（clean2 PASS + vio1-4 牙齿不塌）；若改前 gate 对 clean2 全放行=gate 零变更（三查①mech assumption_completeness_trace 不涉引用形态②方框一已列列表行引用③引用形态不命中任何 block 条件） |
| pack_self_contained | 不置位 | #19 验证型步——②③④产出新事实（环境真值），包外单点验证=合法职责面；p1-sub3/p2-sub2/p2-sub3 三重否决先例 |
| pack_full_prior_boundary | 不置位 | 复用材料=本节点前序 trace 全文通道（不经 boundary 截断面），p2-sub3 同判 |
| MERGED 段内续步 | 不置位 | 步体=核验型非极小搬运；plan:1 链峰值前科；u:2 MERGED 重审已登记独立项 |
| Node 工具白名单 | 不动 | main 已置位（五件），两臂同有 |

## 3. 改法（dl_flow_engine.py / dl_flow_nodes.py / tests / replay）

### L1 机制

`SEGMENT_CHAIN_SKIP_STEPS = frozenset({("plan:1", 5), ("plan:3", 2), ("plan:3", 4)})`
+ 注释（步级第四例，判据 #20/#24 + 材料核对结论）。

### L2 机制

子4 Step 加 `segment_strip_project_context=True`（第十六例）。

### L3/L4 条款（purpose 追加；selfcheck 补一条）

复用与深度钉死（核验步形态）：
- ①skill 条目存在性的出处生产时间已前移到子2——子2 注册表清点留痕
  （available-skills 列表行/磁盘目录枚举/SKILL.md frontmatter 读取）
  逐字在交接包，直接引用即合法（「引用子2 留痕：<出处逐字>」形态），
  零重验——禁重复 ls/Read 子2 已核实的同一路径。
- 枚举例外（逐条二值判定）：绑定对象在子2 留痕零出处（子3 新引入
  能力）时该条单点核验一次（ls/test -f/列表行引用任一形态）即止。
- ②CLI 可用/③MCP 连接/④环境前提=本步新核验职责，深度钉死：
  每绑定每类单命令验存在即止（which X / X --version / test -f /
  配置定点 Read 一次四形态）；禁同面复探（同一事实多命令多角度
  重复核验）；禁读文件全文/数据结构全文；四类以外零取证（功能
  正确性/性能/数据契约归 execute）。
- 交付即止：落库成功（✓ 已落库）即结束本轮——禁 locate 产物/读
  state/grep evidence 确认落库/预习下一步，推进与门控由外部 driver
  判定。
- 格式真源：载荷格式唯一真源=--scaffold 骨架+append-trace 报错文案
  ——禁读引擎/测试源码/历史 trace 反推格式；被拒按报错文案逐字修。

selfcheck 补：「①存在性出处引用子2 留痕零重验了吗（例外按条配额）？
②③④每绑定每类单命令验存在即止了吗（零同面复探/零四类以外取证）？」

### L5 replay fixture（先对照组后定 gate）

tests/replays/replay_plan3_sub4.py 增 clean2_引用子2留痕载荷（五绑定
①全部「引用子2 留痕：<列表行/磁盘出处逐字>」形态+②③④单命令留痕），
EXPECT=PASS。**先跑改前 gate**：误 block 才改判据一/判材边界文本
（负判定零改动）+双侧回归；全放行则 gate 零变更（三查结论写收官）。

### 同步件

- tests/test_dl_drive.py：test_chain_skip_steps_constant 补 ("plan:3",4)
  断言；行为测试补 plan:3#4 豁免+兄弟步（子3）零行为变化。
- tests/test_dl_flow_engine.py：test_p3_other_steps_no_step_strip 豁免
  子4；新增 test_p3_step4_step_level_strip（env 双开关+白名单继承）+
  test_p3_step4_reuse_clause_pinned（条款关键词 pin）。
- skills/workflow-creation/references/nodes-index.md plan:3 行子4 摘要。
- skills/workflow-creation/references/cost-optimization.md：收口沉淀
  （编号取收口时 git log 最大值+1，防并行抢占）。

## 4. 预登记（B vs A，验收口径）

| 指标 | A 基线 | B 预登记 | 判别 |
|---|---|---|---|
| 首调 fresh | 190,802（链恒冷） | **≤48,000**（-75%——三分量报价：交接包子1/2/3 trace 全文 ~25-30k + 剥后 harness ~4.8k + 白名单工具 schema ~3-4k + node-rules/step prompt ~2k + 条款回补；#23 预登记口径） | 机制读数（L1+L2） |
| 段 cr 合计 | 1,446,016 | **-60% 起**（携带税灭+轮数持平） | L1 主驱动 |
| 成本等效 | 337,990 | **-45% 起** | 主验收轴 |
| 轮数 | 15 | ≤15（A 是①缺位的不合规形态，B 合规下限=②③④单命令×绑定数+落库面；不以轮数大降为验收） | 口径声明 |
| 工具调用 | 14 | ≤12（同面复探 ~4-6 消灭；①引用形态零新命令补齐合规欠账） | L3 |
| 段 out | 19,134 | ≤37k（#33 复用钉死 thinking 放大 1.9× 报价） | 双轴登记 |
| 段 dur_api | 151s | out÷rate 拟合归因，与 token 轴分开登记（#30） | 双轴登记 |
| 门控 | 未判 | **零 block** | 硬约束 |

trace 质量逐条自查（防 Goodhart）：每绑定四类核验留痕齐备（不适用类附
显式声明）、三态逐绑定标注、已验证附出处（新核验命令+返回概述 或
引用子2 留痕逐字）、假设附置信度×影响、出处零编造——引用形态不得
稀释执行接地（绑定仍条条有出处，只是①出处生产时间前移到子2）。

混淆声明：①A=链内段 vs B=fresh 段——口径差异即 L1 测量面（断链收益
含携带税灭+冷重写灭）；②A 轮 ① 缺位=不合规少做事，B 轮以引用形态
零新命令补齐——轮数/调用数口径不按「≤A 大降」验收（主验收轴=首调/
等效）；③amplitude 今日值 4929.2% vs 种子叙事 4824.5% 漂移=#18 两轮
同漂移面，子4 核验不涉因子数值；④Node 白名单（-14.3k）两臂同有非
本轮收益；⑤judge replay 读数与 live 门控分开登记；⑥并行会话
p3-sub3-cost 在飞，A/B 期间其 skip 第三例未入 main=两臂链政策一致。

## 5. 实测收官（2026-08-20，A=p3_sub3_base 子4 链内段 / B=p3_sub4_ab 子4 fresh 段，同种子 evidence ≤plan:3#3，ac-deepseek1/deepseek-v4-flash headless）

| 指标 | A（链内段） | B（四杠杆） | B vs A | 预登记 | 验收 |
|---|---|---|---|---|---|
| 首调 fresh | 190,802（cr=1,024） | 33,258（cr=0） | **-82.6%** | ≤48,000 | ✓ 大幅超（三分量报价命中：包 ~20-24k+harness 4.8k+schema ~3.5k+rules/prompt ~2.5k≈31-35k） |
| 段 fresh 合计 | 193,388 | 77,889 | **-59.7%** | — | ✓ |
| 段 cr 合计 | 1,446,016 | 231,680 | **-84.0%** | -60% 起 | ✓ 超（携带税灭主驱动） |
| 成本等效（in+cr×0.1） | 337,990 | 101,057 | **-70.1%** | -45% 起 | ✓ 超，主验收轴 |
| 轮数（result 权威值） | 15 | 9 | **-40%** | ≤15 | ✓ |
| 工具调用 | 14（Bash×11） | 8（Bash×3 核验+scaffold/Read/Edit×2/append） | -42.9% | ≤12 | ✓ 近理想最小形态 |
| 段 out 合计 | 19,134 | 19,588 | +2.4% | ≤37k（1.9× 报价） | ✓ **无反噬**（见归因） |
| 段 dur_api | 151s | 147s | -2.6% | out÷rate 拟合登记 | ✓ 双轴同降（速率 A 127/B 133 tok/s 稳定，out 持平→墙钟持平） |
| append-trace mech 拒 | —（driver 死于 gate 前） | **0**（scaffold+一次落库） | | | ✓ |
| 门控 | 未判 | **零 block 一次通过**（last_judged plan:3#4 落账即推进） | | 零 block | ✓ |

**B 工具序列（近理想形态）**：which codegraph（单命令，禁同面复探自述）→
test -f venv python（单命令）→ pytest --version（单命令）→ scaffold →
Read 骨架 → Edit×2 → append 一次过。①skill 存在性零新命令（全部引用子2
留痕逐字：磁盘清单目录行+frontmatter 留痕）=L3 兑现；同面复探两族清零
（A 轮新鲜度×4/venv×4）=深度钉死兑现；零 evidence 翻找/零交付后徘徊。

**trace 质量逐条自查（防 Goodhart）**：9 能力绑定四类留痕齐备（①引用子2
留痕逐字/②which 单命令/③引用子2 配置留痕+会话工具面/④test -f+
--version 单命令，不适用类附显式声明）；三态逐绑定混合（已验证附出处+
假设 H-A/H-B 附置信度×影响）；只标注不裁决（接受留子6）；深度钉死自述
在 trace 正文——绑定条条有出处，执行接地零稀释 ✓。

**out 无反噬归因（#42 反例形态第二例）**：复用钉死的引用厚度替代的是
A 轮命令回显厚度（留痕义务总量不变），条款新增的引用义务为零时 out
不放大（p3-sub1-cost -18.2% 同族）；thinking 放大未现（B 核验思考量
随复探清零同步下降）。预登记 1.9× 报价未触发=报价口径的保守方向，
不改 #33 报价规则（报价=上限非点估计）。

**replay（L5 对照组程序收官）**：现 gate（2594 字符未改）n=6——
clean 6/6 / **clean2_引用子2留痕 6/6 全 PASS** / vio1 6/6 / vio2 6/6 /
vio4 5/6 / vio3 1/6。**对照组结论：引用形态误 block 不存在（6/6 放行）
→gate 零变更**（三查①mech assumption_completeness_trace 不涉引用形态
②方框一合法形态已列「注册表列表行引用」③引用形态不命中任何 block
条件）；clean2 入库=回归 fixture 防未来 gate 编辑误 block 引用形态。
vio3 1/6=设计内委托（判面已下沉 assumption_completeness_trace 生产墙，
v2.112 落地时 2/6 同族读数），非本轮改动面。

**子5 暴露面登记（#30 扩面）**：B 轮顺带跑子5（resume 子4 fresh 会话）——
首调 96,705（cr=0 恒冷）/7 轮/段合计 in=107,695 cr=536,448/out=19,620，
无 A 对照（基线收段未跑子5）。定性：携带量=子4 单段 transcript（~78k）
vs 断链前链内形态应为子2+3+4 三段（首调 190k 基础上再涨）——同向改善；
轮数 7 无爆炸（#20 补暴露面上限登记 ✓）。

**混淆声明复盘**：①A=链内段 vs B=fresh 段=L1 测量面（预登记已声明）；
②A 轮①缺位=不合规少做事形态，B 以引用形态零新命令补齐——轮数口径
按预登记不按「≤A 大降」验收（实际 -40% 仍降，纯税消灭+合规欠账补齐
同批）；③amplitude 今日值 4929.2% vs 种子 4824.5% 漂移=#18 未触发
（子4 核验不涉因子数值，B 轮零数据文件读取）；④Node 白名单两臂同有；
⑤judge replay（MiniMax）与 live 门控（deepseek）分开登记；⑥并行会话
p3-sub3-cost 在飞，两臂链政策一致（其 ("plan:3",3) 未入任何一臂）。

**pytest**：1202 全绿（新增 3 例：断链豁免行为[子4 豁免+兄弟步零变化]/
子4 strip 生效面/复用条款 pin；test_p3_other_steps_no_step_strip 豁免
子4；test_chain_skip_steps_constant 补 ("plan:3",4)）。

## 6. 遗留

- plan:3 子5（归一化能力包）成本优化立项候选（B 轮顺带段读数已登记：
  首调 96.7k 链内冷重写=断链/复用钉死面未覆盖；pack/strip 逐步核对）；
- 子6 读回步=零成本关闭清单核对（#22 先例，plan:3#6 在册 8 读回步）；
- 并行会话 p3-sub3-cost 收口并轨点：SEGMENT_CHAIN_SKIP_STEPS frozenset
  行（union ("plan:3",3)）/test_chain_skip_steps_constant 断言/
  test_p3_other_steps_no_step_strip 豁免集（加子3）/strip 例数（彼十五
  此十六）/cost-optimization 编号（收口时 git log 最大值+1）；
- vio3 1/6 牙齿=设计内委托登记（生产墙承托判面，judge 残留判面小）；
- 种子八件套族补件：worktree 跑 replay 必带 .token（README 已单源化，
  症状 V 第二形态）。
