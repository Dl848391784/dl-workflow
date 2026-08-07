# 装配步硬提醒设计（v2.123）

> 2026-08-07。触发：tail_volume_acceleration_annualized 2026-08-06 运行审计。

## 问题（实测定量）

一轮运行内 4/4 装配步首忘装配义务，全吃机械 gate block 各白返工一轮：

| 节点末步 | block 原因（.wf_advance.log） |
|---|---|
| understand:4 子5 | 产物未落地：understands/<name>.md 不存在 |
| plan:2 子5 | 产物未落地：plans/<name>.md 不存在 |
| plan:3 子6 | 产物缺节：缺「能力与工具」节 |
| plan:4 子5 | 产物缺节：缺「执行计划与检查点」节 |

## 根因

装配义务（跑 `render-artifact`）埋在末步长 purpose **中段**（如 understand:4 子5
purpose 先是大段交互读回裁决义务，装配命令在倒数第二句）。末步多是交互重步，
模型做完交互义务后目的-显著性已被稀释，直接 STEP_DONE。judge/判据侧无误判，
纯模型侧显著性问题——杠杆在注入通道（§3.5 rubric：判据钉死→schema→文案）。

## 方案

当前步=节点末步 且 节点挂 ARTIFACT 机械门（ARTIFACT_EXISTS/ARTIFACT_CONTAINS）时，
workflow_phase 注入在 ▶ 当前步块后单列一行硬提醒（命令 + 落点路径 + 忘跑后果）：

```
- ⚠ 本步有装配义务：STEP_DONE 前必须先跑 `python3 ~/.dl-workflow/dl_flow_engine.py
  render-artifact <artifact>`（机械装配落 `<绝对路径>`，禁手写产物）——
  忘跑 = gate 机械校验必 block，白返工一轮
```

- 文案/路径逻辑单源在 engine.assembly_obligation_hint（贴着 gate_verdict_mech，
  同降级口径：无机械门/name/project_root 缺失/产物标识非单文件 → None 不出提醒）。
- 只在正常编排态出（held_for_gate / phase_done_open 不渲染子步骤块，天然不出现）。
- 非末步不出（装配义务锚定末步，早出=噪音稀释）。

## 范围

- `dl_flow_engine.py`：+assembly_obligation_hint（新函数，不动既有行为）。
- `hooks/workflow_phase.py`：▶ 块后 +调用点（~10 行）。
- `tests/test_workflow_phase.py`：+TestAssemblyStepReminder 5 例
  （正例 understand:4/plan:2 末步；负例 非末步/无机械门节点/held_for_gate）。

## 验证

- 新测试 5 例 + 全量 pytest 回归。
- 下轮真实工作流运行：4 个装配步不再出现「产物未落地/缺节」block 即根治
  （对照组 = 本轮 4/4 命中）。

## 不做

- 不改 step purpose 原文（提醒与 purpose 重复是刻意的双通道：purpose 讲为什么，
  提醒行钉时机）；不改 gate 判据；不覆盖 design.md 装配（--slug 动态路径，
  非机械门，本轮无误判证据）。
