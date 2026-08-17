# understand:1 子4（双向取证）耗时/token 优化设计

> 立项：2026-08-17 用户 goal「优化 understand:1 step4，耗时和 token 大幅降低」。
> 前置：子2a/子2b 已于前会话优化（plan-first 拆步 + v2.44 探索预算）。
> 审计口径：runtime-audit #17（message.id 去重）/ #18（耗时三桶）+ cost-optimization #1（瓶颈分层）。

## 1. 诊断数据（amplitude_annualized 两轮实测）

step4 段边界 = segment_sessions 完成时刻差（#18①）。

| 轮次 | 会话 | step4 墙钟 | 轮数 | fresh in | cache_read | 备注 |
|---|---|---|---|---|---|---|
| D（08-17 00:57 链） | 200fb21a | 8.4min | 34 | 200k | 6.87M | 链续跑全冷 |
| F（08-17 09:20 链） | 188d1472 | 8.0min | 17 | 25k | 3.10M | 链续跑暖 |

### 瓶颈分三层定位（cost-optimization #1）

1. **机制 bug 层（~12 轮 + 1.5-2min 白烧，两轮均中）**：
   - **Bug B 标题 off-by-one**：`ingest_agent_report` 标题映射 `cur==3→蒸馏报告 / cur==4→红队输出`
     是 plan-first 拆步重编号（6→7 步）前的旧映射；重编号后双向取证=子4、质检裁决=子5，
     子4 ingest 落「红队输出原文收录」标题 → `_check_fetch_report_recorded`（数「蒸馏报告」标题项）
     找 0 项 → append-trace 拒 → 模型 `--help`+Edit 改标题重试（D 轮 10 轮调试、F 轮 2-3 轮）。
     重编号漏网：`dl_flow_nodes.py` 子4/子5 mech_checks 与 engine 两个 check 的 docstring
     都已按新编号更新，独漏 ingest 标题映射；既有测试 `test_ingest_redteam_happy(sub_step=4)`
     钉的是旧编号错误行为（测试没跟着重编号走 = 缺陷对测试隐形，runtime-audit #13 同族）。
   - **Bug A 防重误报**：`if task_id in text` 全载荷子串匹配——模型在 qa 留痕里写
     「原子D→Agent task-id=a13ec…」（task-id 出场=已派发，正是 mech 台账要求的信号）即误报
     「已收录过」→ D 轮 10 轮读源码调试死循环。
2. **上下文膨胀层（token 大头）**：段链（P2-4）在 deepseek-v4-flash 上跨进程 --resume
   前缀缓存**时灵时不灵**——D 轮链内 step2→5 首调 fresh 44k→109k→166k→241k 单调涨
   （cache hit 0.9-4% = 全冷），F 轮 step4 首调 cache_read 158k（暖）。链会话峰值
   **324k > 250k 护栏阈值**（D 轮 17:21:49 实测）——`segment-chain-resume-design.md`
   2026-08-14 修订的扩 u:1 裁决自带回滚条件「链峰值突破则回滚」，**已触发**。
   即便暖轮（F），链续跑每轮重读继承上下文 ~160-180k/轮，仍比 fresh 段（~45k 起步）
   贵 ~2 倍；冷轮（D）贵 ~5 倍。thinking 块占继承上下文 ~50%（162k/335k chars）。
3. **墙钟地板层**：fetch 子代理运行 4-8min 是最长杆（设计内，v2.39 已钉先派发后内查）；
   light 档参数（≤2 层源 ≤4 curl）已在 v2.40/v2.118 定死，本项不动。

### 预期收益（step4 单步）

- 轮数 34 → ~15（bug 修复 −12 轮，其余为生产性调用）；
- fresh in 200k → ~45-50k（断链后 fresh 段首调口径，-75%）；
- cache_read 6.87M → ~1.0-1.5M（轮数 × 上下文双降，-78%）；
- 墙钟 8.4min → ~5-6min（地板 = 子代理运行时长，主会话白烧清零）。

## 2. 方案（三修，全在 engine 单文件 + 测试）

### 修 1（Bug B）：ingest 标题从「当前步 mech_checks」派生，消灭硬编码步号

`ingest_agent_report` 标题映射改为读当前 Step.mech_checks：
`fetch_report_recorded` 在列 → 「蒸馏报告原文收录」；`redteam_report_recorded` 在列 →
「红队输出原文收录」；否则 → 「子代理报告原文收录」。结构对齐消费方（两个 mech check
正是标题的读者），重编号免疫。state→node→sub_step_at 查 Step 的范式照抄
`scaffold_payload` 既有代码。

### 修 2（Bug A）：防重收窄到「收录项标题精确形态」

`if task_id in text` → `if f"原文收录（task-id {task_id}）" in text`——只认脚本自己
写出的标题形态（`{title}（task-id {task_id}）`，title 恒以「原文收录」结尾），模型
派发留痕里的 `task-id=xxx` 不再误触。方向 = 宁纵勿枉（重复收录代价 << 误报调试死循环）。

### 修 3（链回滚）：understand:1 移出 SEGMENT_CHAIN_NODES

执行 2026-08-14 用户裁决的预授权回滚条件（链峰值 324k > 250k 已触发；
deepseek 跨进程 resume 缓存时灵时不灵 = 链在 deepseek 上的成本模型前提不成立）。
u:2/3/4 与 plan 族不动（surgical；它们的链峰值未实测突破）。
driver 侧 `_chain_resume_sid`/`_chain_update` 零改动（白名单查 membership 即生效）；
在飞实例兼容：链 state 残留无害（membership 失配自然断链开新会话）。

## 3. 验证

1. TDD：先改既有两测试到新编号（sub_step=4→蒸馏报告 / sub_step=5→红队）+
   新增防重误报回归（载荷含 `task-id=xxx` 派发留痕时 ingest 不拒）→ 红 → 修 → 绿；
2. 全量 pytest + ruff；
3. live 验证：在飞 amplitude_annualized 实例（state 停于 sub_step_index=4）续跑，
   step4 应见：fresh 段首调 ~45k、无「蒸馏报告收录项不足」拒、无「已收录过」误报、
   轮数 ~15 量级。读数口径 = segment_sessions ts + drive-stream result modelUsage（#17）。
4. 断链回归：`_chain_resume_sid` 对 understand:1 返回 None（既有链测试断言白名单
   行为，若钉死 u:1 在列需同步改）。

## 4. 不做的事

- 不动 light/full 档参数与子代理运行时长（v2.40/v2.118 已钉，质量风险大于墙钟收益）；
- 不动段链架构本身（u:2/3/4/plan 族保留；deepseek 暖轮时链仍有 fresh 微省）；
- 不动 judge 侧（v2.77-79 framing 已稳，本项纯写侧/编排侧）；
- 不给段工人加 MAX_THINKING_TOKENS=0（thinking 占继承上下文 50% 是 chain 症状，
  断链后自然消失；对工人关思考链有质量风险，judge 侧先例不外推）。
