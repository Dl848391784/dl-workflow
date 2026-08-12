# v4 成本/耗时优化设计（fresh input 冷启动税 + 墙钟系统税 + 读回分级）

> 立项依据：2026-08-12 `interaction_turnover__ret3d_abs_annualized` 全程实测审计（factor_ic_analyzer 仓，front 模式首次完整 dogfood 中段：u:1 → plan:2#子4，31 步）。
> 对比基线：v2 TUI 单会话同区间干净跑（tail_volume，2026-08-08 14:22→15:48，86 min）——注意该基线为修六周判据后的**重跑**，首跑真实耗时为数天，只作架构对照不作目标值。

## 0. 审计数据基线（全部实测，口径已校验）

### 0.1 耗时分解（156 min / 31 步）

| 构成 | 时长 | 占比 | 性质 |
|---|---|---|---|
| 段内模型干活 | ~104 min | 67% | 产出 873k output token 的生成时间 |
| 系统税（judge ~36s×31 + 段启动 ~10-15s×31 + driver 派发） | ~29 min | 19% | 纯机械开销 |
| 等用户（17 次 AskUserQuestion，实测 trace 间隔求和） | 16.8 min | 11% | 用户思考时间，11 次 <1min 秒点，2 次 3-5min 长问均在子阶段边界读回 |

### 0.2 token 分解（同口径对比）

| | v2（tail_volume u:1→plan:4，86min） | v4（本轮 u:1→plan:2#子4，156min） |
|---|---|---|
| cache_read | 130.8M（去重实算） | ~60M（segments 34.5M + 交互步 ~5M + TUI 常驻 20.7M） |
| fresh input | 306k | ~2.1M（≈7×） |
| output | 230k | ~873k |
| 单会话上下文峰值 | 485k 零锯齿单调涨 | 段内独立 ≤~150k，TUI ~172k |
| 成本 | ~$100 级（cache_read 为主项） | $56.7 实记 + TUI ~$10 |

口径纪律两条（后续审计复用）：
- **transcript usage 按行求和虚高 ~2.4-3×**（同 message id 重复记录）。正确口径 = 按 `message.id` 去重求和；已用 result 事件 `modelUsage` 逐字验证（95f69a19：去重 4,996,096 == modelUsage 4,996,096）。
- v3.0 设计文档的 v2 基线「318.7M cache_read / 874k in / 648k out / 1034 次调用」即重复计数口径，去重后真实值 **130.8M / 306k / 230k / 413 条消息**。引用旧文档数字时须先换算。

### 0.3 fresh input 冷启动税（本设计的核心实测发现）

- 22 个段会话**首次 API 调用 cache_read 全为 0**——同节点段共享同一份 node-rules system prompt（`--append-system-prompt-file`），跨会话前缀共享零命中。首调 fresh 合计 1.14M（占全部 fresh 大头）。
- 段内后续调用缓存正常（34.5M cache_read 全在段内）→ 网关缓存本身工作，问题在**跨段**。
- **首调负载随步数单调涨**：u:1#子2 47.7k → plan:2#子4 73.3k。交接包每步叠加最新 trace，v2.12 只修了 judge 侧的 `read_evidence_for_step` 裁剪，**交接包侧同款膨胀未修**。
- 候选机制（待 P0 实验判定）：①网关按会话隔离缓存；②缓存 TTL 短于段间隔（2-6 min）；③交接包动态内容位置靠前污染前缀。

### 0.4 边界税归因修正

子阶段边界 10-15 min 间隔 × 6，实测其中**约一半是用户读回时间**（u:1→u:2 的 18.7 min 间隔内含 8 min 两连问等待）。系统侧边界税（装配段 2-4min + judge + 派发）约 5-8 min/边界。

## 1. 目标与护栏

| 指标 | 基线 | 目标 | 性质 |
|---|---|---|---|
| 全 run 墙钟 | ~4.5-5h（推算） | ~3-3.5h | 优化 |
| fresh input | 2.1M | ~1.2M | 优化 |
| cache_read | 60M | ~45M | 优化 |
| 等用户时间 | 16.8 min/31 步 | ~8 min | 优化 |
| **一次通过率** | 本轮基线 | **不降** | 护栏 |
| **judge 牙齿**（真违规拦截率+判词引对条款） | 35 gate 默认-PASS 重放基线 | **不降** | 护栏 |

## 2. 方案

### P0 诊断：网关跨会话缓存实验（半天，零风险）

同一 ~50k prompt 间隔 5 分钟发两次 curl，读第二次 cache_read，判定 §0.3 三候选：
- 会话隔离 → 死心，P2-3 不做；
- TTL 短于段间隔 → P2-3 = 段派发紧凑化；
- 前缀污染 → P2-3 = prompt 重排（稳定 system 内容全部前置，交接包挪后）。

### P1 token 侧（1-2 天，零一过率风险）

**P1-1 交接包瘦身（收益最大）**。`engine.handoff_pack` 前序各步 trace 只留 verdict 摘要 + 产物指针，不喂全文——v2.12 `read_evidence_for_step` 裁剪的同范式平移。预期首调 50-73k → ~30k，fresh -40%；连带每段上下文整体变小（cache_read 同步降）。
风险点：段内模型看不到前序细节。缓释：v2.12 已证明 judge 侧裁剪不判错；交接包保留「前序 verdict + 当前步目的 + 产物指针」三件套，细节可按指针 Read 自取（合法通道）。

**P1-2 增长斜率机械监控**。driver 段启动时记录首调 fresh（result 事件已有），超阈值（暂定 35k）告警——宁纵勿枉，只告警不阻断。防交接包再次静默膨胀（v2.12、本次均靠审计事后抓）。

### P2 时间侧·系统税（2-3 天）

**P2-1 边界装配步合并**。子5/子6 装配段（2-4 min + judge + 派发）并入前一工作步的段内完成，省系统侧 ~5-8 min × 6 边界 ≈ 8-10 min/run（注：不含用户读回那一半，见 §0.4）。
前置审查：装配步独立成段的门控理由（产物 CONTAINS 门栏挂在末步）——合并后门栏挂点随迁到合并段的 STEP_DONE。

**P2-2 mech 全覆盖步跳过 LLM judge**。判据已纯词形/结构化的步（归一化族 statements 校验等，framing 反转系列已下沉 10+ gate 的形式要件）改为：mech 全过 → 一票通过，judge 只在 mech 拒时介入。省 ~36s × 约 1/3 步数 ≈ 5-10 min/run。
前置审查（逐节点）：「这个 gate 还剩什么只有 judge 能判」——剩语义判据（同义反复/稻草人/概念重叠类）的步不动。每步跳过决定记入 design 附表。

**P2-3 段启动缓存对齐**（视 P0 结果三选一，见上）。

**P2-4 相邻轻步合段（暂缓，最后做）**。省 ~15-20 min + 0.7-0.9M fresh。v3.0 §2.2 否过批量段的两个理由仍成立：append-trace state 驱动错挂步号；弱模型多步指令跟随 = 一过率对立面。只在 P1/P2 落地且护栏有数据后，挑已证明稳的步对试点（候选：u:2-u:4 的轻量连续步），不做全量铺开。

### P3 交互侧（用户裁决项，UX 契约变更）

**P3-1 读回分级**。实测 17 次提问 11 次 <1 min 秒点。提案两级：
- **裁决级**（涉方案选择/取舍/方向）：维持弹卡片；
- **确认级**（机械读回、无非标内容）：静默通过 + trace 可查 + 事后 `/dl dispute` 兜底（通道已存在）。
省用户 ~8 min/run，消除边界两连问长间隔。分级标准（哪些步属确认级）需用户逐节点拍板，落定前不动。

## 3. 验证方法

下一真实任务全程 dogfood A/B 对照本基线，指标通道全部现成：
- 每步墙钟：state.json `history` + `segment_sessions` ts；
- 首调 fresh / 段内 cache：drive-stream.jsonl result 事件 `modelUsage`；
- TUI 侧：transcript 按 message.id 去重（§0.2 口径纪律）；
- 等用户时间：transcript AskUserQuestion tool_use → tool_result 间隔求和；
- 护栏：一次通过率（gate 首判 pass 比例）+ block 判词抽读（引对条款）。

## 4. 实施顺序与预期

P0（半天）→ P1（1-2 天，token -30~40%）→ P2-1/P2-2（2-3 天，墙钟 -15~20 min/run）→ P3-1（待分级标准）→ P2-4（试点）。
全部落地预期：全 run ~3-3.5h、fresh ~1.2M、cache ~45M、成本 -25~30%，一过率不降。

实施纪律：本仓 worktree-per-session 协议；每 Phase 独立分支独立收口；P1/P2 改动 hook/engine 后 `git pull` 即生效（hook 直引源），skill/output-style 改动需 install.sh 重 copy。
