# understand:3 子5（读回确认）耗时/token 优化——证伪式结案：P3-1 已降至零成本

> 日期：2026-08-19 · 分支 feat/u3-sub5-cost · 状态：结案（机制不建，无代码变更）
> 上游：designs/v4-cost-latency-optimization-design.md §2 P3-1（读回分级，2026-08-13 用户裁决）；
>      designs/u2-sub5-cost-optimization-design.md（同型证伪结案先例，2026-08-18——
>      「u:2#5 及全部 8 个读回步的成本优化立项 = 永久关闭」）；
>      references/runtime-audit.md #19（「不做」也是合格收官）/ #11②（证伪式结案）/ #3（最小重测范围）
> 触发 = 用户指令（2026-08-19）：「优化 understand:3 的 step5，耗时和 token 消耗
> 要大幅降低，能用前面步骤沉淀下来的 discovered 和 evidence 就尽量用，避免
> factor 化；跑测试工作流用 ac-deepseek1；amplitude 今日值 4947.7%」
> （承 u:3 子1-4 优化系列之后）。

## 1. 审计结论：优化前提不成立——子5 自 P3-1（2026-08-13）起已是零模型成本

u:3#5（读回确认）在 P3-1 读回分级中已降确认级（用户本人 2026-08-13 裁决，
v4-cost-latency-optimization-design §2 P3-1 明列「u:2-4#5」在 8 步清单内，
u:3#5 即其中一员）：

- **机制**：`dl_flow_nodes.py` 末尾 `_apply_confirm_readback_tier` 单点补丁——
  8 个读回步（short=读回确认/读回装配 且 interactive=True；u:3#5 两个条件
  均满足）统一 `tier="confirm"` + purpose 换 `_CONFIRM_READBACK_PURPOSE`；
  `dl_drive.py` 主循环 confirm 分支：render-readback 机械展示 +
  render-artifact 机械装配 + write_confirm_trace 落库后自动推进——
  **无模型会话、无 prep 段、无 TUI 问答、gate=None 无 judge**。
- **「复用前序沉淀 evidence」在机制层已是唯一形态**：确认级读回的全部呈现
  材料 = render-readback 从本节点归一化+假设 traces 机械装配（逐字、禁手抄），
  不存在「重查/重取证」的模型面可优化——这正是用户指令「能用前面步骤沉淀
  下来的 discovered 和 evidence 就尽量用」的彻底兑现形态。
- **残留成本** = 纯本地 python（读 evidence + 装配 + 写一行 trace），亚秒级。

## 2. 生产实证（u3_sub4_ab，2026-08-19，当前 HEAD 800351a，ac-deepseek1/deepseek-v4-flash）

今日 u:3#4 优化 A/B 的生产轮正好覆盖 u:3#5，零新跑直接取证：

| 证据 | 读数 |
|---|---|
| state.segment_sessions | `{"ts":"2026-08-19T12:16:12","session_id":"confirm","kind":"confirm-readback","node":"understand:3","sub_step":5,"note":"rc=0"}`——**session_id 字面即 "confirm" = 零 claude 进程 = 0 token** |
| evidence u3_sub4_ab.jsonl | #5 trace（minor_stage=ScopeAndConstraints）purpose=「P3-1 确认级读回（机械落库，无模型会话）」，a=「确认级静默通过（P3-1 读回分级，2026-08-13 用户裁决）…」 |
| state.node_attempts | 0（零 block 零返工） |
| 段序列 | #4 headless 段 12:14:23 收 → #5 confirm 12:16:12 落 → u:4#1 12:17:19 |

段序列归因：#4 收（12:14:23）到 #5 落（12:16:12）的 109s = **#4 的 gate
judge 子进程耗时**（驱动主循环：段收 → run_gate → pass → advance → 才进
confirm 分支），非 #5 自身成本；#5 的 confirm 分支（render-readback +
render-artifact + write_confirm_trace）是纯本地 python 无 API 调用
（confirm 分支不 spawn 任何 claude 进程，session_id="confirm" 即铁证），
亚秒级。u2-sub5 生产实测同型读数 = 与邻段同秒完成、墙钟 <1s。

## 3. 为什么不跑新 live A/B（ac-deepseek1 / amplitude 4947.7% 不触发）

runtime-audit #3（最小重测范围）：无代码变更 → 无编排行为改动 → 不需要 live
整轮；u3_sub4_ab 即今日、即当前 HEAD、即 ac-deepseek1 生产同款环境的真实
数据，直接可作证据。为重测零成本步再烧一轮 seeded run 违反最小重测纪律
（u2-sub5 §3 同款判断）。用户指令的 ac-deepseek1 + amplitude 今日值 4947.7%
为「跑测试工作流时」的条件要求，本轮不触发（同 u2-sub5 对 4920.2% 的处置）。
「避免 factor 化」同理由机制保证：确认级步零模型会话，不存在任何领域
漂移/factor 化的载体。

## 4. 结论与防重复提案

- u:3#5 的「耗时和 token 大幅降低」已于 2026-08-13 由 P3-1 兑现（0 token /
  亚秒级），本审计验证该兑现在当前 HEAD（含今日 u:3 子2/3/4 三连优化）下
  仍然成立：成立。
- u2-sub5 §5 已宣告「全部 8 个读回步（u:1#6 / u:2-4#5 / plan:1#6 / plan:2#5 /
  plan:3#6 / plan:4#5）的成本优化立项 = 永久关闭」——u:3#5 在清单内，本文档
  仅按用户指令补一笔 u:3#5 的生产实证记录，不改结论。
- 未来审计若观察到 u:3#5 出现模型会话，那是 P3-1 机制回归（查
  `_apply_confirm_readback_tier` 是否被改丢 / dl_drive confirm 分支是否被
  绕过），按 bug 修，不立优化项。
