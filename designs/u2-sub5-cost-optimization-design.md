# understand:2 子5（读回确认）耗时/token 优化——证伪式结案：P3-1 已降至零成本

> 日期：2026-08-18 · 分支 feat/u2-sub5-cost · 状态：结案（机制不建，无代码变更）
> 上游：designs/v4-cost-latency-optimization-design.md §2 P3-1（读回分级，2026-08-13 用户裁决）
>      references/runtime-audit.md #19（「不做」也是合格收官）/ #11②（证伪式结案）/ #3（最小重测范围）
> 触发 = 用户指令（2026-08-18）：「优化 understand:2 的 step5，耗时和 token 消耗要大幅降低；
> 跑测试工作流用 ac-deepseek1；amplitude 今日值 4920.2%」（承 u:2 子1-4 优化系列之后）。

## 1. 审计结论：优化前提不成立——子5 自 P3-1（2026-08-13）起已是零模型成本

u:2#5（读回确认）在 P3-1 读回分级中已降确认级（用户本人 2026-08-13 裁决，
v4-cost-latency-optimization-design §2 P3-1 明列「u:2-4#5」在 8 步清单内）：

- **机制**：`dl_flow_nodes.py` 末尾 `_apply_confirm_readback_tier` 单点补丁——
  8 个读回步（short=读回确认/读回装配 且 interactive=True）统一
  `tier="confirm"` + purpose 换 `_CONFIRM_READBACK_PURPOSE`；
  `dl_drive.py` 主循环（drive 全程与 front `--segment` 共用单源）confirm 分支：
  render-readback 机械展示 + render-artifact 机械装配 + write_confirm_trace
  落库后自动推进——**无模型会话、无 prep 段、无 TUI 问答、gate=None 无 judge**。
- **残留成本** = 纯本地 python（读 evidence + 写一行 trace），毫秒级。

## 2. 生产实证（u2_sub4_ab，2026-08-18，当前 HEAD 00bb6c2，ac-deepseek1/deepseek-v4-flash）

| 证据 | 读数 |
|---|---|
| segment_sessions | `confirm-readback u:2#5 session_id="confirm" rc=0`，与 merged #3-#4 同秒完成（14:24:18），下一秒已进 u:3#1（14:24:19）——**墙钟 <1s** |
| transcript 目录 | 全程仅 271f1ea0 一个会话文件（merged #3-#4）——**#5  spawn 零个 claude 进程 = 0 token** |
| evidence u2_sub4_ab.jsonl | #5 trace purpose=「P3-1 确认级读回（机械落库，无模型会话）」 |
| node_attempts | 0（零 block 零返工） |

前后对照（P3-1 设计档实测动机）：降級前读回步 = decision 级交互（TUI 问答 +
模型呈现 + 手写 trace），「17 次提问 11 次 <1min 秒点、每次 1-2min 交互延迟 +
前后段启动」；降级后 0 token / <1s——**token -100%、墙钟从分钟级到亚秒**，
「大幅降低」五天前已由 P3-1 兑现。本审计的作用 = 验证该兑现对 u:2#5 在
当前代码（含今日 子3断链/子4段内续步）下仍然成立：成立。

## 3. 为什么不跑新 live A/B

runtime-audit #3（最小重测范围）：无代码变更 → 无编排行为改动 → 不需要 live
整轮；u2_sub4_ab 即今日、即当前 HEAD、即 ac-deepseek1 生产同款环境的真实数据，
直接可作证据。为重测零成本步再烧一轮 seeded run 违反最小重测纪律。
（用户指令的 ac-deepseek1 + amplitude 4920.2% 为「跑测试工作流时」的条件要求，
本轮不触发。）

## 4. u:2 全节点成本收官账（子1-5 系列优化后）

| 步 | 优化 | 现状 |
|---|---|---|
| #1 目标引出（交互） | u2-sub1-cost：NEXT_PREP 跨节点 + sources 出处包 | fresh -45~55% |
| #2 对齐质检 | u2-sub2-cost：pack_self_contained 三件套 | fresh -34%/墙钟 -66% |
| #3 价值论证 | u2-sub3-cost：断链（链恒冷纯增税） | 冷启动 -33% |
| #4 归一化陈述 | u2-sub4-cost：段内续步（MERGED_RUN_NODES） | 首调 -92%/墙钟 -43% |
| #5 读回确认 | **P3-1（08-13）确认级机械化，先于本系列** | **0 token / <1s** |

残余可优化面（非本立项范围，供未来立项参考）：#2 作为 run head 的冷启动地板
~40-45k（harness+node-rules+交接包，P1-1 水位恒定）；#3 测量型步体轮数方差
（#40 天然高方差）；#1 TUI 问答轮（decision 级交互是设计内成本）。

## 5. 关闭项（防重复提案，runtime-audit #19）

- **u:2#5 及全部 8 个读回步（u:1#6 / u:2-4#5 / plan:1#6 / plan:2#5 / plan:3#6 /
  plan:4#5）的成本优化立项 = 永久关闭**——P3-1 已零成本化，无模型面可降。
  未来审计若观察到读回步出现模型会话，那是 P3-1 机制回归（查
  `_apply_confirm_readback_tier` 是否被改丢），按 bug 修，不立优化项。
