# understand:1 整体成本优化：段前缀三修（MCP 剥除 / node-rules 瘦身 / 收录原文隔步剥离）+ provider A/B

> 立项：2026-08-17 用户 goal「step5 优化后再跑整个 understand:1 并整体优化，耗时和 token 大幅降低」。
> 前置：子2a/2b（plan-first + 探索预算）、子4（两轮）、子5（红队预派发）已逐步优化；
> 本设计是首个**全节点整体**基线 + 优化（此前无全优后整轮数据）。

## 1. 整体基线（u1_overall_ab，2026-08-17 21:05-22:00，deepseek-v4-flash，同 amplitude 问题）

新实例全跑 u:1（子1 prep → 用户问答 → 子2-7 连续段），**全程零机械拒、零 judge block（一次通过）**。
口径：段界=segment_sessions ts；token=transcript 按 message.id 去重（runtime-audit #17）。

| 步 | calls | 段内墙钟 | fresh | 首调 fresh | cache_read | out |
|---|---|---|---|---|---|---|
| 子1 prep | 3 | 42s | ~45k | ~45k | 小 | 小 |
| 子2a | 17 | 211s | 72.1k | 44.5k | 1.07M | 24.2k |
| 子2b | 30 | 256s | 87.3k | 49.9k | 2.20M | 29.8k |
| 子4 | 24 | 410s | 88.6k | 50.1k | 1.93M | 34.2k |
| 子5 | 9 | 306s | 84.9k | 54.8k | 0.61M | 25.6k |
| 子6 | 7 | 79s | 66.6k | 60.2k | 0.40M | 9.8k |
| 子7 | 0（confirm 机械） | — | 0 | 0 | 0 | 0 |
| fetch 子代理×2 | 22 | — | 44k | — | 0.76M | — |
| 红队 worker | 5 | ~150s | 35.7k | — | 0.14M | 19.2k |

合计（u:1 系统侧）：**主段 87 calls / 段内墙钟 1263s（21min）/ fresh 399k / cache_read 6.2M**；
含子代理 ≈ 119 calls / fresh ~500k / cache_read ~7.1M。u:1 全程墙钟 ~25min（含 judge×6+派发税）。

### 瓶颈分层结论（cost-optimization #1）

1. **首调冷启动层（fresh 65%）**：6 段首调全冷（deepseek 流式会话隔离，P0 已证无解），
   首调 fresh 随步数单调涨 44.5k→60.2k。**逐调用前缀里有两块死重**：
   - **MCP schema 税**：探针实测（同端点裸 `claude -p` A/B）tavily MCP schema =
     **2,504 tok/调用前缀**；编排全程禁 tavily（子4 purpose 明文禁、红队纪律 Read 为主）
     但 schema 照加载——且红队 worker 两次经 MCP 调 tavily_extract 绕过 `--tools Read`
     （已知洞，v2.40 起观察项）。
   - **node-rules 全步 purpose 税**：node-rules.understand:1.md = **25,005 字符**，
     其中 7 步 purpose 全文清单 ~15k 字符；而当前步 purpose 已由段 prompt 逐字携带
     （build_step_prompt「目的：{step.purpose}」）——清单里其余 6 步全文是每调用重付的死重。
2. **交接包单调涨层**：包字符数 子2 1.1k → 子4 8.5k → 子5 19.5k → 子6 31.6k。
   增长大头 = 子4 fetch 报告 + 子5 红队报告的「原文收录」qa 项全文（~23k 字符）。
   消费步只有子5（三关质检）；子6（归一化）只需 verdict/处置问题集，报告正文是死重。
3. **工作层（不动）**：子2b 30 calls / 子4 24 calls 逐调用时间线全绿——无调试循环、
   零干等（子4 派 agent 后内查再收，141s 等待 = agent 运行地板）、先派发后内查遵守。
   子代理协议（v2.40）与红队运行时长（质量护栏）按既有裁决不动。
4. **judge / 段启动税（不动）**：judge 实测 ~9s×6（P2-2 已关闭跳过项）；段启动 ~12s×6。
   段链回滚（c384738）在 deepseek 上是定论，不复活。

### 预期收益（单轮 u:1，deepseek）

| 修 | 省 cache_read | 省 fresh | 机制 |
|---|---|---|---|
| O1 段会话/红队/judge 禁 MCP | ~0.3M（~115 调用×2.5k） | ~37k（~15 会话首调） | --strict-mcp-config --mcp-config 空表 |
| O2 node-rules 瘦到当前步 | ~0.5M（~90 调用×~5.5k tok） | ~40k（6 段首调） | 清单渲染 titles-only |
| O3 收录原文隔步剥离 | ~42k（子6 段 7 调用×6k） | ~6k | 包内「原文收录」a 项截断+指针 |
| 合计 | **~0.85M（-12%）** | **~83k（-17% fresh）** | 另：prefill 缩小→每调用略快，墙钟 -1~2min |

附带收益：O1 把「禁 tavily」从文案纪律升为结构保证（红队 tavily 旁路洞关闭）。

**provider A/B（复跑验证阶段做）**：同问题同仓在 kimi k3 复跑整轮——k3 流式缓存全局共享
（P0 实测新会话首调 100% 命中），首调 cold-start 税 ~260k fresh 预期基本归零
（fresh -60~70%）；墙钟取决于 k3 单调用速度，实测。这是「大幅降低」的主杠杆，
v4-cost-latency-design §2.0b 已留此决策通道（本 A/B 即其前置数据）。

## 2. 方案（三修，dl_drive.py + dl_flow_engine.py + 测试）

### O1：driver/engine spawn 的 claude 一律禁 MCP

四处 spawn 统一加 `--strict-mcp-config --mcp-config {"mcpServers":{}}`（探针已验证旗标形态）：
- `run_headless_session`（段会话，dl_drive.py）；
- 红队预派发 worker（dl_drive.py）——同时把「Read 为主」纪律的 MCP 旁路结构封死；
- `_build_tui_cmd`（TUI 交互段）；
- `engine.run_judge`（judge）——judge 本就不调工具（--tools ""），MCP schema 纯死重；
  判决 prompt 逐字不动，判据/输入面零变化（不重跑 35 gate 重放的依据）。
单源：`_NO_MCP_ARGS` 常量（dl_drive 与 engine 各持一份？——engine 不 import driver，
hooks import engine；常量定义在 engine，driver import 复用，禁拷贝分叉）。
例外：front 常驻 TUI（dl-launch 起的用户会话）不动——用户自由对话可能合法用 MCP。

### O2：node-rules 清单瘦身为 titles-only

- `engine.render_substeps_section` 不动（phase-rules 全量渲染路径 = v2/front TUI 用，需全量）。
- 新增 `engine.render_substeps_brief(nid, cur)`：每步一行「子步骤N = ref：short」，
  当前步加标注「← 当前步（完整目的见任务 prompt）」。
- `ensure_node_rules(project_root, name, node, cur)` 加 cur 参数（调用点 1687/1771 均已知 cur；
  ensure_tui_rules 复用同一内容——TUI 段同为单步会话，一致瘦）。
- u:1 atomic_questions 注入收窄到 cur ∈ {3,4}（子2b 挖链 + 子4 按档取证的消费步；
  子5+ 的 claim/tier 上下文已在包内 trace 全文）。
- nodes-index.md 摘要块不变（purpose 内容未改，只改渲染形态）；SKILL 真源节注明渲染面变化。

### O3：交接包「原文收录」隔步剥离

`_slim_trace_for_pack(seg, prior=False)` 增补：qa 项标题含「原文收录」的 a 项，
当当前步 > 该 trace 所在步 + 1 时截断为 标题 + 前 200 字符 + 「（全文见 evidence 指针）」。
相邻步保全文（子5 消费子4 收录 = 相邻，不受影响）；隔步剥离（子6 起）。
实现：handoff_pack 已按 (minor_stage, sub_step) 持有 trace 与 cur_step，截断判定在
循环处传入 trace_step 计算。宁纵勿枉：parse 失败/无标题匹配原样保留。

### 不做的事

- 子代理（fetch/红队）运行时长与协议（v2.40/质量护栏，既有裁决）；
- judge 跳过/合并（P2-2 已关闭：35/35 含语义判据 + judge 仅 ~4% 账单）；
- 段链复活（deepseek 缓存隔离定论）/段合并（弱模型多步指令跟随=一过率对立面）；
- 子2b/子4 轮数压降（逐调用时间线无脂肪，方差带内——#40：单次离群不立优化项）；
- front 常驻 TUI 的 MCP（用户自由会话面）；
- execute/review/evolution 阶段的段会话 MCP 剥除——本次只验 understand 族+plan 族段；
  若 execute 段合法需要 MCP 的场景出现，按实例再开（当前编排全程禁 tavily，无合法消费者）。

## 3. 验证

1. TDD：
   - O1：四处 spawn 的 cmd 断言含 _NO_MCP_ARGS（mock Popen 钉旗标）；judge cmd 同断言；
   - O2：brief 渲染含全部步 titles + 当前步标注、不含他步 purpose 全文关键词
     （取 u:1 子2b purpose 独有词形如「占环位」做负例断言）；ensure_node_rules 传 cur 后
     文件体积 < 阈值（如 8k 字符）且当前步 purpose 仍由段 prompt 携带（断言 build_step_prompt
     含 step.purpose 既有测试回归）；
   - O3：构造含「原文收录」qa 项的两步 trace——相邻步包内全文保留 / 隔步截断带指针；
     无标题匹配原样；parse 失败原样；
2. 全量 pytest + ruff；
3. 真实 evidence 冒烟（runtime-audit #5）：对 u1_overall_ab 的 evidence 直接调
   handoff_pack 对比包大小（子6 应 31.6k→~15k 字符）；render 后的 node-rules 量字符数；
4. live 复跑（任务#4）：新实例 u1_overall_v2 同问题 deepseek 全跑（隔离 O1-O3 效果，
   预期 cache_read -10%+、fresh -15%+、零拒零 block 保持）+ u1_overall_k3 同问题 kimi 全跑
   （provider A/B，预期 fresh -60%+）。两轮与基线同口径对比落本设计 §5。

## 4. 风险与回滚

- O2 瘦身若伤一过率（模型迷失节点位置）——titles 保留 map 骨架 + 当前步 purpose 双通道
  （段 prompt + TUI 注入）仍在，风险低；live 复跑见 block 即回滚单修（git revert 单 commit）。
- O1 若某下游场景合法需要 MCP——编排全程禁 tavily 无合法消费者；execute 阶段自由会话
  不经 driver 段 spawn（build_phase_prompt 整阶段会话同样禁——见「不做的事」末条，
  若实爆需求按实例再开）。
- 三修各自独立 commit，可独立 revert。

## 5. 实施验证记录（2026-08-17/18，merge e61c982，1082 tests）

- TDD 红→绿 + 全量 1082 passed + ruff 绿；两处旧契约断言按新契约改写
  （bare TUI 末位 flag / 取证路线可见面迁段 prompt——意图保留）。
- **真实 evidence 冒烟**（u1_overall_ab 证据直接过优化后引擎）：子5（消费步）包
  19,533 字符不变；子6 包 31,579→23,508（-26%）；node-rules 真实渲染
  25,005→1,222 字符（-95%）。
- **live A/B 三方**（同问题同仓，新实例种子子1 trace 从子2 起跑，全程零 block、
  各步 judge 留痕齐全、node_attempts=0）：

| 指标（子2-6 主段） | 基线 u1_overall_ab（deepseek） | v2（deepseek+三修） | k3（+三修） |
|---|---|---|---|
| calls | 87 | 129（子3 方差爆 70；剔除后 59） | 86 |
| 段内墙钟 | 1263s | 1564s（剔除子3 差 ~1032s） | 2648s（+110%） |
| fresh | 399k | 397k（剔除子3 差 275k，-12%） | **231k（-42%）** |
| cache_read | 6.20M | 11.06M（剔除子3 差 3.90M，-3%） | **4.37M（-30%）** |
| out | 123k | 156k | **53k（-57%）** |
| 首调 fresh/段 | 44.5-60.2k | 37.5-52.3k（-13~16%） | **17.8-21.0k（-55~65%）** |

- 稳态收益（剔除方差）：**每调用前缀 -11.5k tok**（rules 瘦 ~9k + MCP 2.5k），
  折算全轮 cache_read -17%/fresh -11% 量级；本轮被子3 轮数方差（30→70 calls，
  ±5M cr 摆幅）淹没——#22 实证：单轮总账读数不能归因机制，逐调用口径才可以。
- O1 附带验收：v2/k3 全部会话（含红队 worker）**零 tavily 调用**（上轮红队
  tavily_extract×2 的旁路洞结构封死）；红队预派发两实例均正常落痕。
- **k3 provider A/B 结论**：token 三维全降（fresh -42%/cr -30%/out -57%，全局
  缓存首调命中 ~50% 前缀），但**墙钟 2.1×**（k3[1m] high-effort 段内 31s/call
  vs deepseek 14.5s/call，且随上下文涨：子6 70s/call）——耗时维度不合格。
  provider 取舍 = 用户决策（v4-cost §2.0b 通道），本 A/B 即其前置数据。
- 分档方差注意：三轮子2a tier 判定不同（2/3/1 个 tier≠none 原子）→ 子4 agent
  数 2/3/1——跨轮子4 总账不可直比，按原子对齐才有效。
- 测试账（隔离列报）：v2 被杀段 f511cf9a（24 calls/85k fresh/1.85M cr）+
  其 fetch agents——会话中断孤儿 kill 所致，非生产账。
- **未开杠杆（候选，需各自裁决/多轮验证）**：①段会话 --tools 白名单
  （harness 地板 22.3k 里内建工具 schema ~12k，裁到 8 件约再 -4~6k/调用——
  收益在方差带内，单轮 A/B 测不出，暂缓）；②k3 降 effort 收墙钟（质量/一过率
  未验证）；③deepseek 段 effort 调优（out 123k 含 thinking，未拆账）。
