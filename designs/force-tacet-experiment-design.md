# 强制 TACET 实验设计（任务复杂度分档 · 第一期）

> 日期：2026-08-21 · 状态：待用户评审 · 本文件取代同日两版前稿（上午 `step-intensity-tiering-design.md` d3fe0ac 已删；下午「承重墙」版 6fba018 立场亦错，本版覆盖）。
> 命名（用户 2026-08-21 选定，音乐记谱法）：**TACET=简单任务的最小轨道（沉默）/ PIANO=轻奏 / FORTE=强奏（=main 现状全量编排）**。

## 1. 用户意图（裁决前提，勿再曲解）

- main 的五阶段全编排（44 子步+13 交互）是为**复杂任务**（设计新模块、跨模块改造）建的。**有些问题就是纯 bug**，不需要那么重的 understand/plan。
- 分档的本质 = **整个工作流按任务复杂度伸缩**，不是在同一个复杂任务里逐步审视哪些步能省。
- TACET = 最低档 = 简单任务的最小轨道；其余一切与 main 一致。
- **档位划分机制（怎么判断一个任务该走哪档）本期不实现**；先做「**强制走 TACET**」开关，拿一个真实小 bug 跑一遍验证最小轨道够不够用。

## 2. TACET 轨道形态（核心裁决）

**用户交互面 = 仅 u:1#1 问题陈述**（用户 2026-08-21 选定）。纯 bug 的轨道：

```
u:1#1 逼问定义（TUI 交互，用户陈述问题）
   ↓  understand:1 子2-7 + understand:2/3/4 全部  → TACET 沉默（不派段、零 token、不跑 judge）
   ↓  plan:1-4 全部（含 plan:4#5 读回装配、引出发散）  → TACET 沉默
   ↓  plan:4 门栏 + plan->execute 闸门  → TACET 模式自动放行（不叫用户 /dl gate）
execute → review → evolution   正常跑（不进实验面）
```

| 类别 | 处置 | 理由 |
|---|---|---|
| u:1#1 逼问定义 | **正常跑**（唯一交互步） | 问题陈述是唯一必须的输入 |
| understand 其余 43 步中的全部子步（含 12 个交互步） | **TACET 沉默** | 纯 bug 不需要目标/障碍/成功标准三连问，也不需要 13 轮读回确认--这正是要摆脱的重 |
| plan:1-4 全部子步 | **TACET 沉默** | bug 的「计划」就是定位+改法，execute 段内自然完成 |
| plan:4 门栏 + plan->execute 闸门 | **自动放行** | 双重 /dl gate 是重任务的用户裁决点；TACET 轨道无 plan 可裁决 |
| execute / review / evolution | **正常跑** | 真正干活+验收的部分；review 兜底 bug 修复质量 |

TACET 步集 = engine 机械推导：understand/plan 44 子步中除 u:1#1 外全部（43 步，含交互步）。**模型无权选择/自封 TACET**（防滥用：跳步决策只存在于 engine 机械层 + 用户开关）。

## 3. 实验目标与成功标准

拿一个**真实小 bug**（因子项目里一两个文件可修的那种）从 TACET 轨道走完：

1. **够不够用**：bug 修对没有（review 结论 + 人工验 diff）--这是主验收轴。
2. **成本账**：token/墙钟 vs 同类 bug 走全量轨道（或按近期 A/B 基线推算）的对比。预期：understand+plan 段成本 ≈ 只剩 u:1#1 一步，全程成本 ≈ execute+review 主导。
3. **观察点**：execute 在「问题陈述 + 空 plan」交接包上的行为--是直接动手修，还是先自行勘察（勘察工作量从 plan:1#1 转移进了 execute 段，总成本的一部分只是换了地方花）。

跑通标准：不卡死走完全程（自动放行链路生效）。

## 4. TACET 步语义

- **不派段、零 token、不跑 judge**。engine 写一行 tacet-record 到 `evidence/<name>.jsonl`（写方只能是 engine）：
  `{"kind":"tacet","node":"understand:2","sub_step":1,"trigger":"force_tacet","via":"driver","ts":...}`
- 推进复用 gate-pass 的 advance 路径。

## 5. 机制设计（落点均为已核实函数）

- **开关**：`dl <name> --force-tacet` -> dl-launch.sh 写 `state.force_tacet=true`（sticky）。**隐含 `--headless`**（v1 只支持 headless driver，launch 强制并提示）。
- **跳步**：dl_drive.py 段循环派段前查 `state.force_tacet and step in TACET_SET` -> 新 engine 函数 `apply_tacet_skip()`（写 tacet-record + advance）-> 不派段继续。**交互步在 force_tacet 下同样被跳**（driver 本来要把交互步回 TUI 段，TACET 轨道直接跳过这个回屏）。
- **门栏/闸门自动放行**：`held_for_gate`（engine:1887-1976）与 plan->execute 闸门检测 `state.force_tacet` -> 写 `{"kind":"tacet_gate_autorelease"}` 记录 + 直接放行。
- **产物**：understand.md / plan.md **不装配**（render_artifact 对全 TACET 节点整体跳过，留一行「TACET 轨道：未装配」占位文件防下游路径断）。损伤记录机制不需要--TACET 轨道里「没有产物」是设计内状态，不是损伤。
- **交接包**（handoff_pack，engine:1714）：execute 拿到 = 问题陈述（u:1#1 trace）+ 「understand/plan 已 TACET 沉默」一行说明 + 仓库本身。execute 段的勘察在段内自然发生。
- **judge/读回**：跳过的步无 Stop 无 trace 判决，gate 机制天然不触发；tacet-record 不进任何 judge 输入（read_evidence_for_step 对 kind=tacet 跳过）。
- **进度显示**：progress_rows 对 TACET 步标「tacet」，LiveProgress 原样透出；driver 打事件日志。
- **front 防御**：hooks 检测 force_tacet + front 模式 -> 提示仅支持 --headless（launch 已拦，纵深）。

## 6. 实验规程

1. `dl <实验名> --force-tacet`（隐含 --headless），选一个真实小 bug。
2. 用户只做一件事：u:1#1 陈述问题。此后全程零交互直到 review 结果。
3. 跑完汇总：修对没有 / 成本对比 / execute 段内勘察行为的观察。
4. 产出 = TACET 轨道可用性结论，作为第二期「档位划分机制」的输入之一。

## 7. 测试与影响面

- **测试**：TACET_SET=43 且恰为「44 子步 − u:1#1」/ launch flag->state sticky / apply_tacet_skip 写 record+推进 / 门栏+闸门 force_tacet 自动放行 + 记录 / render_artifact 全 TACET 节点跳过+占位文件 / 交互步在 force 下也被跳 / tacet 步零 judge / progress_rows tacet 标记 / --force-tacet 隐含 --headless / 零 force 时全行为不变（回归）。
- **文件**：dl-launch.sh / dl_flow_nodes.py（TACET_SET 推导）/ dl_flow_engine.py（apply_tacet_skip + 门栏闸门放行 + render_artifact + read_evidence_for_step + handoff_pack + progress_rows）/ dl_drive.py（跳派段含交互步）/ hooks/workflow_phase.py（防御提示）/ tests。
- **H9 预算**：拆 commit--①engine 核心 ②driver+launch ③门栏闸门放行+artifact ④测试。实现按 worktree-per-session 协议（feat/force-tacet）。

## 8. 显式不做

- **不做档位划分机制**（判断任务简单/复杂）--第二期。
- **不做 PIANO**（轻奏中间档）--本期只有 TACET 全沉默与 FORTE 全量两态。
- **不做 front 模式支持**；**不改 execute/review/evolution 行为**。
- **不做损伤报告体系**（上一版的骨架直通/承重墙叙事整体废弃--那是「复杂任务砸墙」的立场，与「简单任务走轻轨」不是一回事）。
- **不给 execute 注入额外勘察指令**--观察它自然行为，不预设。
