# 子阶段门栏设计：hold_for_gate（编排子阶段完成扣留，/dl gate 放行）

> 状态：**已实施**（2026-07-26；engine/hooks/dl-cmd/phase-rules/SKILL/tests 已同步）
> **适用节点变更（2026-07-27 用户决议）**：门栏自 understand:1（ProblemContext）**移至 understand:2（GoalsAndValue）**——「问题+目标价值」作为地基组一轮跑完再扣留；ProblemContext 不再单独扣留（子6 读回已守「陈述的认可」，两个相邻裁决点冗余）。机制本身不变（Node.hold_for_gate 是声明式开关）。
> **适用节点变更（2026-07-28 用户决议）**：围栏只设在 plan 完成——understand:2/3/4、plan:1/2/3 门栏全部撤除（末步过门控自动续轮进下一节点），**唯一门栏 = plan:4**（advance="phase" hold：放行 ≠ 推进，放行后 PHASE_DONE: plan 撞 plan->execute 大闸门，两次 /dl gate）。配套：understand 移出 GATED_AFTER（understand->plan 无闸门，understand:4 末步过门控直接自动进 plan:1，无 PHASE_DONE: understand 通道）；understand:4 的 understand.md 改子5 内装配（artifact_on_release=False，同 plan:2/3/4 产物节模式）。机制（hold_for_gate/release_subgate/phase_done_channel_open/注入三态）全部保留，仅服务 plan:4。
> 父文档：`node-step-orchestration-design.md`（子步骤编排）、`substep-gate-at-stop-design.md`（Stop 门控）、`tui-state-machine-design.md`（GATED_AFTER 阶段闸门）

## 0. 动因：子6 读回确认守住「陈述的认可」，没守住「进不进下一子阶段」

现行为：`gate_sub_step_at_stop` 末步 pass → `_advance_sub_step` 直接 `advance_state` 推进 understand:1→2。末步虽停轮（子阶段边界检查点），但 **sub_index 已翻过去**——用户下一条消息，注入直接给 understand:2，模型自动开做。读回确认（子6）让用户认可了问题陈述，但「是否进入明确目标和价值」这个决定被机制替用户做了。

ProblemContext 是整个 dl 实例的地基：问题定义错，understand:2-4 / plan / execute 全部白做。地基完成点应该是**显式用户裁决点**，与 phase 闸门（understand→plan、plan→execute 需 /dl gate）同构。

## 1. 设计：Node.hold_for_gate 硬扣留

**症状 P 元教训**：文案=建议（概率遵从），hook=物理。门栏必须是机械的，不是 phase-rules 里写一句「等用户确认」。

### 1.1 机制

1. **Node 加字段** `hold_for_gate: bool = False`（冻结 dataclass 加默认值，向后兼容；仅 understand:1 置 True）。
2. **扣留点**在 `_advance_sub_step` 末步分支：`node.hold_for_gate` → **无条件不推进**（不读 state.gate，见 §2 泄漏分析），写显式标记 `state["held_for_gate"]=True` 落盘。覆盖所有末步路径：judge pass（step-stop）/ step-submit / **force_pass_sub_step（/dl step-pass 末步同样被扣）**——步的放行和子阶段的放行是两个独立的用户决定。
3. **放行**：engine 新函数 `release_subgate`——校验 held 标记 → `write_gate_verdict(via="manual-subgate-pass", sub_step=末步)`（手动放行必留痕，同 step-pass 原则）→ 清标记 → `advance_state(via="manual-subgate-pass")`。CLI 暴露 `subgate-pass` 子命令。
4. **`/dl gate` 路由**：dl-cmd.sh gate 分支先查 held 标记，有则转 `subgate-pass`；无则走现有 phase 闸门逻辑（行为不变）。
5. **扣留期注入**（workflow_phase.py）：held 状态下注入「⛔ 门栏：本子阶段已完成，等 /dl gate 放行，不要做下一子阶段的事」替代子步骤编排块。
6. **扣留期 Stop**：workflow_advance.py 末步 advanced 分支先查 held 标记 → `_emit` 用户可见门栏文案 + return 0 停轮（非 JSON 指令路径，不受症状 Q 纯 JSON 约束）。S13 参与围栏不误伤：sub_step=末步已有 trace。

### 1.2 清理路径

- `reset_sub_step`：清 held 标记（回退重测时门栏状态同步失效）。
- `/dl back` / `/dl jump`：重写 state，held 标记有效性条件 = 标记存在 AND `sub_step_index == len(sub_steps)` AND `node.hold_for_gate`（防御性三重判定，标记残留不误导）。

## 2. 关键决策：扣留不读 state.gate（防泄漏）

候选方案 A：held 条件 = `node.hold_for_gate and state.gate != "passed"`——复用 phase 闸门字段。**否决**：`/dl gate` 在 understand:1 中途（未 held）是合法的 phase 闸门预放行，会把 gate 置 passed；若扣留读该字段，末步会静默穿过门栏——一次放行泄漏成两次。

决策：扣留**无条件**（只认 hold_for_gate），唯一出口 `release_subgate`（或 back/step-reset/jump）。state.gate 保持纯 phase 闸门语义。附带好处：`advance_state` 子阶段推进把 gate 归 pending 的现有行为天然保证 understand:4 阶段闸门仍需独立放行，无语义叠加。

## 3. 与现有机制的关系

| 机制 | 守什么 | 关系 |
|---|---|---|
| 子6 读回确认（gate=None 交互步） | 用户认可问题陈述 | 门栏的前置——先有认可，门栏才有意义 |
| 末步 pass 停轮 | 回合边界检查点 | 保留；门栏把「停轮」升级为「停推进」 |
| phase 闸门（GATED_AFTER） | 跨大阶段（understand→plan） | 同构扩展：同一 /dl gate 命令，按 state 路由 |
| step-pass / step-reset / back | 步级用户裁决 | 步级放行不等于子阶段放行（step-pass 末步仍被扣） |

## 4. 实施 checklist（症状 M）

1. `dl_flow_engine.py`：Node.hold_for_gate + understand:1 置 True + `_advance_sub_step` 末步扣留 + `release_subgate` + CLI subgate-pass + `reset_sub_step` 清标记
2. `hooks/workflow_advance.py`：末步 advanced 分支 held 检测 + 门栏文案
3. `hooks/workflow_phase.py` `_format_injection`：held 注入块
4. `scripts/workflow/dl-cmd.sh`：gate 分支 held 路由
5. `scripts/workflow/phase-rules.md`：门栏语义（system-prompt 通道）
6. `skills/workflow-creation/SKILL.md`：§0 编排段补 v2.9 一句
7. `tests/test_dl_flow_engine.py`：字段默认/扣留/放行/泄漏防护（中途 gate=passed 不穿栏）/step-pass 末步被扣/reset 清标记
8. 本文档状态行翻「已实施」
