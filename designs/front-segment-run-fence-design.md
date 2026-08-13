# 前台段跑期间 fence 收紧设计（v4 front 抢活根治）

> 状态：待评审。触发 = 2026-08-13 `amplitude_annualized` 真机实证：段工人后台执行
> understand:1 的同时，前台 TUI 会话自己在 grep/Read 源码做同一份活（抢活）。
> 一句话：**段跑期间（drive_mode=on）前台会话不再裸奔，收紧为「只交互 + 记账 + /dl」。**

## 1. 问题与实证

用户观察：「在执行段工人的同时 TUI 也竟然在分析问题？TUI 的职责应该只是调度和交互吧」。

transcript 实锤（`~/.claude/projects/-...-worktrees-amplitude-annualized/3323...jsonl`，前端会话）：

| 时间(UTC) | 前端会话动作 | 说明 |
|---|---|---|
| 10:15:06 | 想自己 `grep annual` | fence **deny**（段还没派，`_front_fence_verdict` 白名单收紧）✓ |
| 10:15:07 | 派发 `dl_drive.py --segment`（run_in_background） | 段工人起跑，`drive_mode=on` |
| **10:15:17–10:16:13** | **连做 20+ 条 `grep`/`Read`/`ls` 代码探查**（Read layered_backtest.py 等） | **抢活：与段工人并行，fence 已跳过** |
| 10:16:06 | 段工人 hit NEED_USER 退 code 13，`drive_mode=off` | |

对照段工人会话（`4a09e602...`）：10:15:52 只 `invoke define-problem` 就转去生成问题卡片——**代码探查那 20+ 条全是前台会话干的，段工人根本没做**。

## 2. 根因

`workflow_step_fence.py` 当前的执行序（main 内）：

```
S14（evidence 收编）→ S11（阶段写围栏）→
if drive_mode: return 0            # ← 段跑期间，前台 + 段工人全裸奔
if front_mode and not front_interactive_work_here:
    return _front_fence_verdict()  # ← 只拦「段不在跑」时的抢活
```

`drive_mode` 是全局 state 标志，段跑期间**前台会话与段工人自己的 headless 会话同时为 on**，
而 `return 0` 不区分两者——段工人需要全放行（干活），前台会话也被误放行。

这正是 `front-tui-hybrid-design.md` §2.5 明示「接受」的残余风险：「模型此时无围栏
（fence 在 drive_mode 下跳 S15/S10）……接受」+ 注入文案「等待期间可与用户自由交流」
被弱模型误读成「可以继续自己往下查」。§3.2 残余风险表把「模型抢干非交互步的活」标
「低」，但那条对策写的是「fence 白名单硬拦（§2.3）」，**漏记了「白名单只在段不在跑
时生效」这个前提**——dogfood 实证它发生了。

## 3. 方案：段跑期间前台会话收紧白名单

### 3.1 区分信号：session_id

- `state.session_id` 由 `dl-lib.sh` 建流时钉死 = 前台 TUI 会话 id；`dl-launch.sh`
  用 `--session-id "$SESSION_ID"` 恢复/起跑前台，**invariant：state.session_id 恒等于
  前台会话**。
- 段工人由 `dl_drive.py` 起 `claude -p`，自带全新 `--session-id`（或 `--resume`
  续链 sid），恒 ≠ state.session_id。
- 复用既有的 `_session_id(payload)` 三源回退（payload.session_id → transcript_path
  stem → env CLAUDE_SESSION_ID，见 design_gate/codegraph_gate 同款，v2.69）。
- **防御**：仅当 `state.session_id` 非空 且 `_session_id(payload) == state.session_id`
  才收紧；session_id 缺失/空 → 维持现状放行（不误伤段工人）。

v3 headless（`front_mode=False`）不受影响；WF_TUI=1 v2（`front_mode=False`、
`drive_mode=False`）不受影响。段工人自己的会话（session_id ≠ state.session_id）
照旧 `return 0` 全放行。

### 3.2 收紧后的白名单（段跑期间，前台会话）

| 工具 | 放行 | 理由 |
|---|---|---|
| AskUserQuestion | ✓ | 交互（用户插话/闲聊） |
| TaskCreate/Update/List/Get | ✓ | output-style 强制清单记账，无分析能力 |
| SlashCommand `/dl*` | ✓ | 用户手敲 /dl status 等只读裁决通道 |
| Read / Bash / Skill / Grep / Glob / Agent / WebFetch / … | ✗ | 「分析问题」的全部通道，段跑期间前台无合法用途 |

**关键裁决：段跑期间前台禁 Read（含源码与元数据）。** 前台唯一需要读
`segment_summary.json` / `need_user.json` 的时刻在段**退出后**（`drive_mode=off`），
那时落到下方既有 `_front_fence_verdict`（含 Read）——段跑期间 Read 无任何合法场景。

### 3.3 文案收紧（放大器根治）

注入派发块（`workflow_phase.py:507`）与 advance 续轮/重提示文案
（`workflow_advance.py:410`）两处：

- 旧：`段跑完会自动回到本会话；等待期间可与用户自由交流。`
- 新：`段跑完会自动回到本会话；等待期间只回应用户，不要主动探查源码或调用工具（活归后台段工人）。`

deny 文案（新 `_front_segment_run_verdict`）：

```
段正在后台跑，本会话只等待与交互。
不要在本会话探查源码/调用工具（Read/grep/Skill 等）——活归后台段工人。
要与用户交流请直接对话（AskUserQuestion 可用）；看进度用 /dl status。
```

## 4. 改动文件

1. `hooks/workflow_step_fence.py`：
   - 新增 `_session_id(payload)` 三源回退 helper（照抄 design_gate 同款）。
   - 新增 `_FRONT_SEGMENT_RUN_TOOLS` 白名单集 + `_front_segment_run_verdict()`。
   - `main()` 内 drive_mode 早退改为：front_mode 且 session_id==state.session_id →
     走 `_front_segment_run_verdict`；否则 `return 0`。
2. `hooks/workflow_phase.py`：注入派发块文案「自由交流」→「只回应用户，不探查」。
3. `hooks/workflow_advance.py`：续轮/重提示文案同改（两处文本单源化，见 §5 注）。
4. `designs/front-tui-hybrid-design.md`：§2.5/§3.2 残余风险表更新（不再「接受」，改「已收紧」）。
5. 测试：`tests/` 下新增 fence 段跑期间白名单单测。

## 5. 注意与取舍

- **牺牲**：段跑期间前台不能再「顺手帮用户查别的」——这是用户拍板接受的代价
  （选项 2：收紧 fence 硬约束，牺牲 §2.5 卖点）。
- **文案两处已存在同义重复**（phase 注入 + advance 续轮），本次只改措辞不引入
  新的第三处；若后续再动该句应单源化（engine 常量），本次不做（超范围）。
- **drive_mode 早退的顺序**：S14/S11 仍在 drive_mode 早退**之前**（不变）——
  段跑期间前台写源码仍被 S11 拦；本设计只补上「读/探查」这一侧。
- **session_id 相等判定依赖 invariant**：state.session_id=前台会话。设计文档记录该
  依赖；若未来 dl_drive 改写 state.session_id 须同步回查此处。

## 6. 验证

1. 单测：段跑期间（drive_mode=on + front_mode=on + session_id==state.session_id）
   前台会话 grep/Read/Skill/Agent 全 deny、AskUserQuestion/Task*/SlashCommand /dl 放行；
   session_id ≠ state.session_id（段工人）全放行；session_id 缺失→放行（防御）；
   v3（front_mode=False）不受影响。
2. 真机 dogfood：重跑 `amplitude_annualized`（或新工作流），对照 transcript 确认
   段跑期间前台会话 0 条 grep/Read 源码工具调用；段退出后前台正常读
   segment_summary / 弹 need_user 卡片。
3. 回放：`cc_debug.log` 的 `front_segment_run_deny` 留痕应只在段跑期间出现，
   且不含误伤段工人的 deny。
