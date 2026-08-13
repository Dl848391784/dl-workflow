# 段链合并设计（P2-4 实施：minor_state 粒度 --resume 同会话续跑）

> 立项依据：`v4-cost-latency-optimization-design.md` §2 P2-4（段合并 = deepseek 类 provider 摊薄冷启动次数的唯一途径；P1/P2-1/P3-1 已落地，P2-2 已审计关闭，本项为剩余最大杠杆）+ 2026-08-13 用户裁决：杠杆一（段合并）做；杠杆二（11 步去 judge）= P2-2 今日审计已关闭（35/35 gate 含语义判据，judge 实测 8.9s/次 ≈ 4% 账单），放弃；杠杆三（任务分级 fast lane）待本项落地 + 护栏数据后评估。
> 机制冒烟（2026-08-13 设计期实测）：`claude -p --resume <sid>` 跨进程续会话**通过**（kimi 端点，第二轮记得第一轮内容，session_id 一致）——核心机制成立；全旗标组合（--settings/--append-system-prompt-file/stream-json/stdin prompt/--resume）冒烟列实施步 0。

## 0. 与 v3.0 §2.2 否「批量段」的差异（为什么本次不撞旧否决）

v3.0 否决批量段的两个理由：**①append-trace state 驱动错挂步号；②弱模型多步指令跟随 = 一过率对立面**。

本方案 = **会话合并，非派发合并**：driver 仍逐步派发（每个 `claude -p` 调用只带当前一步的 purpose，步间 gate 照常跑），唯一变化是「下一步起新会话」改为「下一步 `--resume` 同会话续跑」。

- 理由①不触及：append-trace 挂步号由 state 驱动，state 由 driver 逐步推进——续链段里模型若「提前」写下步内容，挂到的仍是当前未推进的步号，被 gate 判内容不符 block，行为正确；
- 理由②不触及：`build_step_prompt` 不变，每个 prompt 仍是单步指令，弱模型指令跟随负担零增加。

## 1. 链粒度 = minor_state 的第一性原理（三条独立论证同指一个边界）

1. **node-rules system prompt 按节点生成**（`ensure_node_rules(project, name, node)`）——跨节点续跑则 `--append-system-prompt-file` 内容变化 = 前缀缓存失效。节点边界是天然缓存边界；
2. **handoff_pack 交接架构（v2.45）在 minor_state 边界重置上下文**——链不超边界则 v2 单会话 485k 零锯齿的平方膨胀不复发（v2 教训的边界 = 30+ 步无锯齿；链内 3-5 步，峰值估 ~150-250k，有界）；
3. **交互步/确认步天然断链**——交互步走 TUI 段、confirm 级读回步无模型会话（P3-1），链只含连续 headless-step 段。

各节点链形态（P3-1 后）：understand:1 = {子2-子5}（子1 交互、子6 confirm）；understand:2/3/4 = {子2-子4}（子1 交互、子5 confirm）；plan:1 = {子1} + {子3-子5}（子2 交互、子6 confirm）；plan:2 = {子1-子4}；plan:3 = {子1-子5}；plan:4 = {子1-子4}。8 条链替代 ~24 个独立段会话。

## 2. 成本模型与预期收益（provider 分流，§2.0b 矩阵）

| | deepseek 类（流式会话隔离缓存） | kimi 类（流式全局共享缓存） |
|---|---|---|
| fresh input | **-0.7~0.9M/run**（链内第 2..N 步首调 = 同会话续轮，前缀全热；P2-4 原估） | ≈0（新会话首调已全局命中，只付交接包 delta） |
| 段启动税 | -15~20 min/run（P2-4 原估，含在墙钟内） | ~10-15s × 省下段数 ≈ 4-5 min/run |
| cache_read | 链内续轮重读累计上下文（1 折价），净成本仍大降 | 微涨（同左但原价命中） |

架构层 provider 无关（§2.0b 已证「段隔离/交接包/逐步门控两 provider 通用，无需分叉」）；验收读数按 provider 分流对照。

## 3. 方案

### 3.1 链状态（state 新增字段）

`state["segment_chain"] = {"node": "<node_id>", "sid": "<session_id>", "last_step": <n>, "ts": <epoch>}`——字段缺失 = 无链（无 schema 破坏性变更，旧 state 自然兼容）。

### 3.2 run_session 增 resume 通道

`run_session(..., resume_sid: str | None = None)`：有值则命令行用 `--resume <sid>`（**不再生成新 `--session-id`**，二者互斥），无值则现状。返回值结构不变。

### 3.3 drive 主循环链维护（headless-step 分支，dl_drive.py:1513-1548 区域）

- **开链**：当前步为 headless-step 且（无链 或 链 node ≠ 当前节点）→ 新会话，落 `segment_chain`；
- **续链**：链 node == 当前节点 → `--resume` 链 sid。gate pass 后下一步续链；**gate block 返工也续链**（返工上下文 = 模型亲眼可见自己上轮产出 + 判词，v2 单会话语义回归，且缓存热——返工恰好是当前最大成本项「轮次 × 全量上下文」的减半点）；none 重试同续链；
- **断链**（清 `segment_chain`，下步必新会话）：节点推进 / TUI 段（交互步）/ confirm 步 / 门栏断点（held_for_gate）/ escalate 断点 / 用户中断（RC_INTERRUPTED）/ **state-reset · back · jump**（旧会话上下文含已作废工作，必断，防污染重做）/ step-pass（会话上下文与被跳步无关，断链从简）；
- **断链兜底**：`--resume` 段 rc 非零且 stream 零 assistant 事件（transcript 丢失/损坏/driver 重启后文件不在）→ 自动降级新会话重发一次，留痕 `chain_broken_fallback`（宁纵勿枉，不当错误甩给用户）；
- **driver 重启续跑**：`--resume` 恢复时从 state 读 `segment_chain`，先验 transcript 文件存在（`~/.claude/projects/<worktree 编码路径>/<sid>.jsonl`）再决定续链/开新链。

### 3.4 监控与台账

- `_first_call_fresh`（P1-2）链内续跑应见 fresh 骤降——deepseek 上为首要看板（首调 fresh 从 50-73k 降到 prompt delta 量级）；阈值告警口径不变；
- `segment_sessions` 台账出现同 sid 多步（kind/note 区分）——**审计口径补注「1 sid ≠ 1 步」**（症状 Z runbook 与 token 审计口径需同步一句）；
- 链上下文峰值监控：链会话 result 事件 `modelUsage` 累计超 250k 告警（宁纵勿枉只告警），防链内膨胀静默复发（v2.12/P1-1 同款教训：膨胀都靠事后审计抓）。

### 3.5 试点纪律（P2-4 原定，不变）

首批只开 **understand:2/3/4** 三条链（交互步在子1，其后子2-子4 为连续 headless 轻步 = P2-4 原定候选），节点白名单开关（engine 常量单源）；dogfood 护栏（一次通过率不降 + block 判词抽读 + 链内上下文峰值）达标后扩 plan 族。不做全量铺开。

## 4. 机制走查（§3.8 #6 清单逐条）

- **SessionStart hook**：resume/compact 不注入交接包（已核实 `workflow_session.py:15,41-42`，`_HANDOFF_SOURCES=("clear","startup")`）——续链不会重复注入，零重复税 ✓；
- **步间 gate**：`engine.gate_sub_step_at_stop` 由 driver 直调（dl_drive.py:1584），trace hash 触发，与会话边界无关 ✓ 零改动；
- **NEXT_PREP（P2-1）**：工作段末顺带备下一交互步问题清单——走同一 prompt 通道，续链不影响 ✓；
- **注入通道存活**（症状 X 教训）：drive 模式段会话的步目的由 `build_step_prompt` 首 prompt 携带，不依赖 attachment——续链段每个 prompt 同样携带，通道不变；实施冒烟须确认 `--resume` 下 `--append-system-prompt-file` 仍生效（system prompt 通道）；
- **新鲜上下文依赖逐步审计**：35 步中唯一要求输入隔离的是红队（u:1 子4 条件触发）——红队 = 独立子代理（redteam-prompt 机械保证输入无子4 结论），天然在链外 ✓；judge = 独立进程 ✓；其余全部步在 v2 时代本就单会话串行跑过数月，无新鲜上下文假设；
- **evidence/产物路径**：不变（模型仍按注入绝对路径写主仓，S11 路径规则不动）；
- **`_session_called_ask_user(meta, sid)`**：仅 prep 段用（prep 不链化，独立会话），共享 sid 不影响 ✓；实现时全仓 grep 一遍「按 sid 唯一定位一步」的隐含假设（segment_sessions 消费方）；
- **fence hooks**：drive 模式白名单分支不变（逐工具调用触发，与会话边界无关）✓。

## 5. 验证方法

1. **实施步 0 冒烟**：全旗标组合（--settings + --append-system-prompt-file + stream-json + stdin prompt + --resume）两步链跑通（设计期已验最小组合，旗标全量为生产形态）；
2. **单测**：链状态机全分支（开/续/断各触发源、transcript 缺失降级、state-reset 作废、driver 重启恢复）、`--resume` 与 `--session-id` 互斥断言；
3. **dogfood A/B** 对照 2026-08-12 基线（156 min / 31 步 / fresh 2.1M，口径见 v4-cost 设计 §0）：每步墙钟 = state.history + segment_sessions ts；fresh/cache = drive-stream result `modelUsage`（按 message.id 去重纪律不变）；护栏 = 一次通过率 + block 判词抽读（引对条款）+ 链上下文峰值 <250k。

## 6. 实施面与纪律

- 主改 `scripts/workflow/dl_drive.py` 单文件（run_session + drive 循环链维护 + 台账），测试入既有 driver 测试文件；遵守 H9（单次 ≤3 文件 AND ≤200 行，超出则拆 commit）；
- hooks/engine 判据/节点树/purpose 零改动——node-design.md 第三通道无需同步；
- 本仓 worktree-per-session 协议；hook 直引源 `git pull` 即生效。

## 7. 回滚面

链开关单点（engine 常量 `SEGMENT_CHAIN_NODES` 白名单置空 = 全局现状：每步新会话）；`segment_chain` 字段缺失 = 无链，旧 state 兼容；无其他 schema 变更。

## 8. 不做的事

- **杠杆二（11 步去 judge）**——2026-08-13 P2-2 逐节点审计已关闭（35/35 gate 含语义判据方框，judge 实测 8.9s/次、35 次/run ≈ 5.3 min + $2.7 ≈ 4% 账单），用户同日裁决放弃；
- **杠杆三（任务分级 fast lane）**——本项落地 + 护栏数据后评估；
- **跨 minor_state 续链**——system prompt 边界 + handoff 交接边界双重否决（§1）；
- **节点/步合并**——失效模式族防线不动（§3.8：步数是失效模式族数出来的）；
- **prep 段链化 / TUI 段链化**——prep 独立会话（L1 工具封锁语义），TUI 是另一会话类型，均不在本设计面内。
