# force-tacet 首跑收口审计（interaction_amplitude__ret3d_abs_test_1）

> 日期：2026-08-27 · 审计人：Claude Code · 口径：skills/workflow-creation/references/runtime-audit.md #27（三通道段->步骤映射 + created_at 过滤同名旧实例）
> 对象：TACET 实验轨道唯一真实运行（2026-08-23 13:22:51 -> 14:10，deepseek-v4-flash，front 模式）。
> 对照组：interaction_turnover__ret3d_abs_test_1（2026-08-22，全量轨道，同类 ×100 显示 bug，跑完 u+p 共 37 段后停在 plan:4 门栏——恰好提供纯 u+p 全量基线）。
> 闭合 design：force-tacet-experiment-design.md §3 三个观察点（修对/成本账/execute 纯度+隐性返工）。

## 1. 修对没有（主验收轴）—— 已闭合 ✓

review 结论 solved：4 模板 9 处重复 ×100 删除，用户报告值 4964.0% -> 49.64% 精确复现验证，CP1/CP2 判据全过（详见项目 .claude/reviews/interaction_amplitude__ret3d_abs_test_1.md）。残留 2 条 stale fixture（测试契约漂移欠账，非回归）——见 §4。

## 2. 成本账（design 预期：u+p ≈ 5 步脊柱、全程由 execute/review 主导）

### u+p 段：TACET vs 全量基线（front 常驻会话单列，不计步骤账）

| 口径 | TACET（6 脊柱步） | 全量（37 段） | 降幅 |
|---|---|---|---|
| 输出 token | 591k | 2,679k | **-78%** |
| fresh input | 1,138k | 4,852k | -77% |
| cache_read | 18.7M | 57.6M | -68% |
| 段墙钟（求和） | 1,927s | 8,305s | **-77%** |
| u+p 跨度（含用户交互） | ~33 min | ~151 min | -78% |
| judge 次数 / 输出 | 2 次 / 6.4k tok | 5 次 / ~15k tok | 均为噪声级 |

front 常驻会话（dispatcher + u:1#1 交互嵌入，#27 盲区口径单列）：TACET 102k out / 全量 141k out。

### 但「全程成本由 execute/review 主导」预期不成立（预期修正）

TACET 非 front 工作分布：u+p 脊柱 591k out（63%）vs execute 117k + review 153k + evolution 段 83k（37%）。
原因：bug 级任务修复面极小（9 处删除），而脊柱的重步是 u:1#3 因果链（150k out）+ u:1#4 双向取证（169k，含 2 个取证子代理 30k）。
**修正后的预期**：TACET 全程成本由**脊柱步**主导（这正说明脊柱挑对了——省掉的 38 步确实是仪式步），execute/review 成本随修复面大小浮动，不作为轨道成本结构的设计假设。

## 3. execute 纯度复盘（86 次工具调用逐条过）—— 基本纯执行 ✓

- **零根因重做**：无 codegraph 调用、无因果链重建、无证据重取。开工先读 plan/understand/design 三件套 + 4 个目标模板（#11-17），随后 9 次 Edit 全部落在 worktree 副本（#57-65）。
- **探索块（#18-50）大多映射 plan 检查点而非越界分析**：防漏 grep（#46-50 -> CP1）、对照点核验（report.html/render 路径 #38-42 -> CP2③）、数值复算脚本（#72-76 -> CP2①）。
- **两处真实低效（共 ~11 调用，13%）**：
  1. **worktree/main 双树混淆**（#51-56、#66-67，~8 调用）：先 Read 主仓模板，diff 发现与 worktree 不一致，再重 Read worktree 版才敢 Edit；编辑后又在主仓 grep 验证（主仓未被编辑）。front 模式共性摩擦，非 tacet 特有——交接包/注入未强调「编辑目标 = worktree 路径」。
  2. **workflow state 元探查**（#43-45，3 调用 python3 读 .claude/ 下 json）——runtime-audit #26「license 有洞」同族的元探查。
- **38 步沉默无隐性返工实证**：execute 全程未需要任何沉默步产物；plan:4#4 装配的施工图 + u:1#4 证据足够支撑纯执行。

## 4. 新发现与历史问题确认

- **stale fixture 残留 = 脊柱材料的真实缺口样本**：u:1#4 原子 B 走 light 档取证，影响面分析覆盖生产路径但没覆盖「绕过 loader 的测试 fixture」这一消费方。execute 的 CP2 回归验证兜住了（发现而非漏网），归类为**测试欠账而非返工**——但它正是「中途升级启发式」要的那类信号样本（fixture 消费方漏检 -> 若修复面更大就可能变真返工）。
- **plan:4 门栏自动放行（via=tacet-subgate-autorelease）= 历史 bug 已修**：本跑 13:56 门栏被自动放行直跑 execute/review/evolution（首版语义）；当日已修为与 main 同路径停等 `/dl gate`（design §2 修订 + engine:1604 注释）。审计确认现语义，无需行动。
- **审计口径备注**：本实例目录混居同日更早同名旧实例 13 个 transcript（11:xx 时段），不过滤 created_at 会把成本高估 ~3 倍——#27 ② 坑在此实例实锤。

## 5. 结论与第二期输入

1. TACET 轨道对 bug 级任务**可用性成立**：修对 + u+p 成本 -78% + execute 纯执行 + 沉默步零返工。
2. 成本结构预期修正：主导项 = 脊柱步（尤其 u:1#3/#4），不是 execute/review。
3. 证据基数仍 n=1：档位划分机制（第二期）开工前建议再攒 2-3 单（含 1 单 dlt --fermate 组合轨道），用真实分布标定中途升级启发式阈值；stale fixture 样本已提示「测试消费方漏检」可作候选信号之一。
4. 机制侧 backlog（与轨道语义无关、本跑顺带实证）：execute 交接包宜明示「编辑目标 = worktree 路径」消除双树混淆（front 共性，~8 调用/轮的税）。
