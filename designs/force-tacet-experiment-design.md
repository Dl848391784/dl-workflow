# 强制 TACET 实验设计（任务复杂度分档 · 第一期）

> 日期：2026-08-21 · 状态：待用户评审 · 本文件取代同日前两版（上午 step-intensity-tiering d3fe0ac「44 步仅 1 步可 TACET」/ 下午 force-tacet 6fba018+d4c3bd1 两稿立场均错，均已废弃）。
> 命名（用户 2026-08-21 选定，音乐记谱法）：**TACET=简单任务的最小轨道 / PIANO=轻奏 / FORTE=强奏（=main 现状全量编排）**。

## 1. 用户意图与不可动约束（裁决前提，勿再曲解）

- **分档本质 = 工作流按任务复杂度伸缩**。main 的 44 步全编排是为复杂任务（设计新模块、跨模块改造）建的；**有些问题就是纯 bug**，不需要那么重的 u/p。
- **阶段语义不可动（用户 2026-08-21 钦定）**：理解和拆解、制定计划 = u/p 的职责；**execute = 纯执行**，只拿 evidence 和 discovered 去实现，不做分析。因此 TACET 轨道**不能整体沉默 u/p**--execute 必须拿到合法的 u/p 产物才能开工。
- **档位划分机制（怎么判断任务走哪档）本期不实现**；先做「**强制走 TACET**」开关，拿真实小 bug 验证最小轨道够不够用。

## 2. TACET 轨道 = 六步脊柱（用户 2026-08-21 选定；2026-08-23 补 u:1#2）

execute 需要的四样输入--问题、根因、证据、修法+施工图--由五个脊柱步供给：

| 脊柱步 | 供给 | 形态 |
|---|---|---|
| u:1#1 逼问定义 | 问题陈述 | **交互**（TUI 段，用户陈述 bug） |
| u:1#3 因果链挖掘 | 根因 | 正常跑（根因=修 bug 的核心理解） |
| u:1#4 双向取证 | discovered 证据 | 正常跑（per-atom 三档已内建，简单 bug 自然走 light/none） |
| plan:1#2 方案发散 | 修法 | **交互**（用户拍板修法方向） |
| plan:4#4 归一化计划包 | 施工图 | 正常跑（装配 plan.md「执行计划与检查点」节，gate 照常可过） |

**其余 39 步（44−5）全部 TACET 沉默**：不派段、零 token、不跑 judge、不交互--含规划拆解/质检裁决/归一化陈述×4/目标障碍成功标准引出三连/读回确认×8/任务切分/能力选型等重仪式步。

**门栏与闸门**（2026-08-23 用户修订：「到 p 默认停止，与 main 一致」）：plan:4 门栏 force_tacet 下**不再自动放行**--plan 完成 held_for_gate 停等，用户 `/dl gate` 放行后才继续（原首版自动放行导致直接跑进 execute/review/evolution，已废除）。

```
u:1#1(交互) → [39步 TACET 沉默，其中 u:1#3、u:1#4、plan:1#2(交互)、plan:4#4 在位] → 门栏/闸门自动放行 → execute(纯执行) → review → evolution
```

TACET 沉默步集 = engine 机械推导：44 子步 − 六步脊柱。

> 2026-08-23 修订：u:1#2（拆解深挖/原子分档）补入脊柱。首跑实证其被沉默后
> u:1#4 的 fetch-prompt 骨架硬断供（报错「无子2 拆解深挖 trace」），模型即兴
> 拼原子清单污染脊柱步对比面。沉默集 39 -> 38。**模型无权选择/自封 TACET**（跳步决策只存在于 engine 机械层 + 用户开关）。

## 3. 实验目标与成功标准

拿一个**真实小 bug**（一两个文件可修）从 TACET 轨道走完：

1. **修对没有**（主验收轴）：review 结论 + 人工验 diff。
2. **成本账**：token/墙钟 vs 全量轨道基线。预期：understand+plan 段成本 ≈ 5 步脊柱（其中 2 步交互、取证自带轻档），全程成本由 execute/review 主导。
3. **观察点**：五步脊柱供给的材料对 bug 级任务是否够 execute 纯执行（不需要段内自行分析）；39 步沉默有没有埋下隐性返工。

跑通标准：不卡死跑到 plan:4 门栏停等（到 p 默认停止；继续 execute 由用户 /dl gate 决定）。

## 4. TACET 步语义

- **不派段、零 token、不跑 judge、跳过交互回屏**（交互步在 force_tacet 下同样沉默）。engine 写一行 tacet-record 到 `evidence/<name>.jsonl`（写方只能是 engine）：
  `{"kind":"tacet","node":"understand:2","sub_step":1,"trigger":"force_tacet","via":"driver","ts":...}`
- 推进复用 gate-pass 的 advance 路径。

## 5. 机制设计（落点均为已核实函数）

- **开关**：`dl <name> --force-tacet` -> dl-launch.sh 写 `state.force_tacet=true`（sticky，resume 保持）。**front（默认）与 `--headless` 均支持**--tacet 判定在 dl_drive.py 主循环，而段工人（front 的 `--segment`）与 headless driver 共用该循环单源（front-tui-hybrid §2.2），天然生效；WF_TUI=1 旧 TUI 路径无共享循环 -> launch fail loud。
- **跳步**：dl_drive.py 段循环派段前查 `state.force_tacet and step in TACET_SET` -> 新 engine 函数 `apply_tacet_skip()`（写 tacet-record + advance）-> 不派段继续。
- **门栏不豁免（2026-08-23 修订）**：`_advance_sub_step` 对 hold_for_gate（全系统唯一处 = plan:4）不再检测 `state.force_tacet`--tacet 与 main 同路径停等 `/dl gate`，到 p 默认停止。
- **产物**：脊柱步在位，plan.md 由 plan:4#4 正常装配（「执行计划与检查点」节真实存在，ARTIFACT_CONTAINS 门合法通过）；understand.md 各节来源步大多沉默 -> render_artifact（engine:1186）对来源全沉默的节装配 `**[TACET 沉默：本节来源步未执行]**` 占位（防下游路径断 + 诚实可见）。
- **交接包**（handoff_pack，engine:1714）：execute 拿到 = u:1#1 问题陈述 + u:1#3 根因 + u:1#4 证据 trace + plan:1#2 修法 + plan:4#4 计划包 + 「其余步 TACET 沉默」说明。
- **脊柱步 gate 照常**：u:1#3 因果链 mech 检查、u:1#4 取证档位台账、plan:4#4 ARTIFACT_CONTAINS 均正常执行（它们是质量的底线，不因 TACET 放水）。
- **judge/读回**：沉默步无 Stop 无 trace，gate 天然不触发；tacet-record 不进任何 judge 输入（read_evidence_for_step 对 kind=tacet 跳过）。
- **进度显示**：progress_rows 对 TACET 步标「tacet」，LiveProgress 透出；driver 打事件日志。
- **front 轨道告知**：hooks 检测 force_tacet -> 注入轨道状态注（材料薄是设计内状态/禁自行补做已沉默步）；front 会话是合法宿主（脊柱交互步照常回前台弹卡片）。

## 6. 实验规程

1. `dl <实验名> --force-tacet`（默认 front 交互面；加 `--headless` 走 v3 driver），选一个真实小 bug。
2. 用户参与两次交互：u:1#1 陈述 bug、plan:1#2 拍板修法。其余全程零交互。
3. 跑完汇总：修对没有 / 成本对比 / execute 是否纯执行（无段内分析越界）。
4. 产出 = TACET 轨道可用性结论，作为第二期「档位划分机制」的输入。

## 7. 测试与影响面

- **测试**：TACET_SET=39 且恰为「44 子步 − 五步脊柱」/ launch flag->state sticky / apply_tacet_skip 写 record+推进 / 门栏+闸门 force_tacet 自动放行+记录 / render_artifact 沉默节占位 / 脊柱步 gate 不放水（含 plan:4#4 CONTAINS 正常判）/ 交互步在 force 下也被跳（脊柱交互步除外）/ tacet 步零 judge / progress_rows tacet 标记 / 段模式（front）同样跳静默步（--segment 共用主循环）/ 零 force 全行为不变（回归）。
- **文件**：dl-launch.sh / dl_flow_nodes.py（TACET_SET 推导）/ dl_flow_engine.py（apply_tacet_skip + 门栏闸门放行 + render_artifact 占位 + read_evidence_for_step + handoff_pack + progress_rows）/ dl_drive.py（跳派段）/ hooks/workflow_phase.py（front 防御）/ tests。
- **H9 预算**：拆 commit--①engine 核心 ②driver+launch ③门栏闸门放行+artifact 占位 ④测试。实现按 worktree-per-session 协议（feat/force-tacet）。

## 8. 显式不做

- **不做档位划分机制**（判断任务简单/复杂）--第二期，输入=本实验结论。
- **不做 PIANO**（轻奏中间档）--本期只有 TACET/全量两态。
- **不做 WF_TUI=1 旧 TUI 路径支持**（无共享主循环，launch fail loud）；**不改 execute/review/evolution 行为**；**不给 execute 注入勘察指令**（观察它是否纯执行）。
- **不动阶段语义**：u/p 仍产出理解与计划，e 仍纯执行--TACET 只裁剪 u/p 内部的步骤数，不重定义职责边界。
- **脊柱步 gate 不放水**：五步的质量门原样保留，TACET 省的是仪式步不是质量步。
