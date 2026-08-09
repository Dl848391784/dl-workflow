# TUI 退 = 全退 语义设计

> 2026-08-09 用户第二次裁决（同日推翻/细化 §2.6 第一次裁决）。修订对象：`designs/drive-tasklist-render-design.md` §2.6。

## 1. 缘起

v3.1 dogfood（`interaction_turnover__ret3d_abs_annualized`，factor_ic_analyzer，2026-08-09）：TUI 段模型卡在权限弹窗 13 分钟，用户双击 Ctrl+C 预期「退出一切」（§2.6 当日裁决语义），实际只退了 TUI、落在 driver，要按第三遍 Ctrl+C 才退出会话。

## 2. 排查实证链（两条独立通道证伪「可区分」）

1. **raw mode 铁证**：Claude TUI 单击 Ctrl+C = 中断生成但进程不死——若 TUI 真收 SIGINT，单击即整个退出。故 TUI 必然处于 raw 模式，Ctrl+C 只是输入字节 0x03，**不产生 SIGINT，同进程组的 driver 什么都收不到**。§2.6「同进程组：TUI 需自己收 SIGINT…driver 侧 _pwait_interruptible 计数」的假设被推翻；TUI 路径的双击计数是结构性死代码（实践中不可达）。
2. **pty 实测**（/tmp 冒烟，pty.fork 起 claude TUI 分别模拟两种退出）：
   - 双击 Ctrl+C：rc=0，SessionEnd reason=`prompt_input_exit`
   - `/exit`：rc=0，SessionEnd reason=`prompt_input_exit`
   - 退出码与 SessionEnd 载荷**双通道撞车**——claude 内部两者是同一个退出函数，driver 从外部无任何可观测信号区分「愤而双击」与「正常收工」。

理论残余通道只有 pty 中继嗅探按键（driver 当终端代理转发双向流），推翻「终端交还 TUI」架构，重且脆，否决。

## 3. 裁决

用户原话：「既然没有区别，那双击 Ctrl+C 就直接退出会话就行了」→ **TUI 退 = 全退**：TUI 段会话一结束（任何方式、任何 rc），driver 一并退出。`/exit` 的「返回 driver 原地续跑」语义随之退役；续跑 = 重新 `dl <name>`（state 磁盘真源，本就支持）。

## 4. 方案

### 4.1 退出前必须先判门控

drive 主循环入口**没有**「先判未判决 trace 再决定开会话」的逻辑——若 TUI 退出后 driver 直接退，已落库的 trace 永远不被判决，续跑时本步会被当没干过重开。故退出前必须跑一遍 `gate_sub_step_at_stop`，判完再走。判过则 state 已推进（advanced）或判词已落 evidence（block，kind=gate/gate=blocked 记录，engine:535），resume 路径零改动。

### 4.2 各门控结果的退出指引（一律退 0，无例外）

| gate 结果 | 退出前动作 | 打印指引 | 续跑 `dl <name>` 后 |
|---|---|---|---|
| advanced | 无 | ✓ 已过门控，续跑进下一步 | 直接进下一子步骤 |
| block | rework 文本落 `state["pending_rework"]`（§4.3） | 判词摘要 + 续跑返工本步 | 带返工上下文重开本步（与现状轮内返工等价） |
| escalate | 无 | 连续 block 达阈值；续跑重开本步，或 `/dl step-pass` 强制通过 | 重开本步；再次连续 block 达阈值会重新 escalate（已知轻微口径差：内存计数重置） |
| none（未落库） | 无 | 未见落库，续跑重开 TUI | 重开本步 TUI（等价现状断点选「回车重开」） |

`seg_kind` 为 `tui-step` / `tui-step-needuser` 均适用。headless 段（含整阶段会话）不受影响，§2.6 单击中断/断点语义不变。门栏/闸门断点（held_for_gate / phase 闸门）不变——那是推进裁决，不是退出语义。

### 4.3 pending_rework 持久化

现状 `pending_rework` 是 drive() 内存变量，driver 一退就丢——block 判词虽在 evidence，但下一步会话 prompt 里的返工上下文（判词原文 + 修正指引）会丢，模型不知道为什么被 block，易原样重犯。

- block 退出前：`state["pending_rework"] = <rework 文本>`，`engine.save_state` 落盘
- `drive()` 启动：`pending_rework = state.get("pending_rework")`
- 消费即清：会话带着 rework 启动后立刻从 state 删该字段并落盘（防陈旧 rework 污染后续启动）

### 4.4 文案更新（5 处）

- `dl_drive.py` build_step_prompt interactive 变体（2 处，:231/:544）：「交互步已完成，请 /exit 返回 driver」→「交互步已完成，请 /exit 退出——本会话与 driver 一并结束；续跑 = `dl <name>`」
- TUI 入口 print（2 处，:665/:670）：「完成后输入 /exit 返回 driver」→ 同上语义
- `_pwait_interruptible` TUI 路径 on_first hint：文案与新语义一致（双击=退出一切），保留——raw 模式下实践中不可达，但作为 cooked 窗口的兜底行为正确

### 4.5 实现形态

抽 `_after_tui_exit(project_root, name, wt, cur, disp) -> int`：跑门控 → 按 §4.2 打印 → 返回 0。drive 主循环在 `_record_segment` 后：

```python
if seg_kind.startswith("tui"):
    return _after_tui_exit(...)   # TUI 退 = 全退
if rc == RC_INTERRUPTED: ...      # headless 单击中断，现状不变
```

## 5. 影响面

| 文件 | 改动 |
|---|---|
| `scripts/workflow/dl_drive.py` | 主循环 TUI 分支、_after_tui_exit、pending_rework 持久化/恢复、4 处文案 |
| `designs/drive-tasklist-render-design.md` | §2.6 修订：记录 raw mode 实证 + 双通道撞车实测 + 新裁决，指向本文档 |
| `tests/test_dl_drive.py` | :205 文案断言更新；新增 _after_tui_exit 各 outcome 测试 |

`/dl` 命令、engine、hooks 零改动。运行中的 driver 实例（已加载旧码）不受影响，下次 `dl <name>` 起生效。

## 6. 测试与 dogfood

- 单测：_after_tui_exit 四 outcome（打桩 gate_sub_step_at_stop）+ pending_rework 落盘/恢复/消费即清 + 文案断言
- dogfood：下个工作流交互步实测——双击 Ctrl+C 应 driver 同退；`/exit` 应 driver 同退且 `dl <name>` 续跑接着过门控往下走
