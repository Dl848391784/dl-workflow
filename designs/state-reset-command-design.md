# state-reset 命令设计（整体回滚到任意历史子步骤）

> 2026-07-28 立项。替代 `step-reset`（废弃）。用户拍板三决策：
> ①新命令 `state-reset`，旧 `step-reset` 废弃；②被重置 evidence 行**纯硬删**（与现 step-reset 一致，不留 reset 记录）；③重置点之后的阶段产物文件**直接删除**。

## 1. 背景与目标

现 `/dl step-reset <n>`（`dl-flow-engine.py reset_sub_step`）只能回退**当前节点内**的子步骤（明确「不改 phase/sub_index」），跨子阶段只有 `/dl back`——但 back 只挪指针，不清 evidence / 游标 / 产物，回溯重跑时旧证据残留会污染 judge 输入（`read_evidence_for_step` 喂前序 trace）与门控判定。

`state-reset` = 定位任意历史节点 + **整体回滚**：state 指针、evidence 证据链、阶段产物一并作废，工作流回到「目标子步骤前一步刚完成」的干净状态。

## 2. 寻址语法

```
/dl state-reset <n>                      当前节点内回退到子步骤 n（兼容旧 step-reset 语义）
/dl state-reset <phase>:<minor>:<step>   跨节点：回退到指定子阶段的子步骤 step
/dl state-reset <phase>:<minor>          跨节点：回退到指定子阶段的子步骤 1（整子阶段重做）
```

- `phase`：英文标识（understand/plan/execute/review/evolution），大小写不敏感。
- `minor`：**子阶段**定位，两种取值——子阶段序号（`plan:2` = plan 第二个子阶段，守两级命名约定）或 minor_key 英文标识大小写不敏感（`designsolution` = `DesignSolution`）。
- `step`：子步骤号，语义 = **含 step 作废**（删 sub_step >= step 的证据，游标清到 step）= 回到「step-1 已完成」重跑 step。与旧 step-reset 语义一致。
- 无子步骤节点（execute:0/review:0/evolution:0）：只允许两段式（step 无意义）。
- ⚠ 节点全表（`_NODES` 线性序）：understand:1 ProblemContext / understand:2 GoalsAndValue / understand:3 ScopeAndConstraints / understand:4 SuccessCriteria / plan:1 DesignSolution / plan:2 TaskBreakdown / plan:3 CapabilityToolSelection / plan:4 ExecutionPlanCheckpoints / execute:0 / review:0 / evolution:0。**ProblemContext 在 understand 不在 plan**（立项时用户示例 `plan:PrombleContext:4` 为非法地址，错误信息须列出合法值）。

## 3. 回滚语义（三件事，都落盘才算完成，无 silent fallback）

目标 T = (phase_t, sub_t, step n)，节点线性序 = `_NODES` keys 序。

### 3.1 evidence 纯硬删（`.claude/evidence/<name>.jsonl`）

逐行过滤，删：
- `kind=skill-trace`：按 `minor_stage` -> minor_key 反查归属节点。归属节点序 > T 序 → 删；== T 且 `sub_step >= n` → 删。
- `kind=gate`：按 `phase`+`sub` 字段定归属节点，同上规则（`sub_step >= n` 仅对带 sub_step 字段的行；节点级裁决行在「== T」时**也删**——回退到 T 中段，T 的节点级裁决（子阶段门栏/大闸门）已失效，留它会让 judge 看到「已过」假象）。
- 保留：坏行（JSONDecodeError）、归属不明行（skill-trace 缺 minor_stage / minor_stage 反查不到节点）、他 kind 行——**暴露而非吞掉**（与现 reset_sub_step 同原则）。

### 3.2 state.json 回滚

- `phase/sub_index/node/index/sub_total` = T 的节点值（index/sub_total 由 phase_index/sub_total 重算，不手写）。
- `sub_step_index` = n（两段式 = 1；无子步骤节点 = 0）。
- `node_attempts` = 0；`held_for_gate` 删除（回退重测时门栏状态同步失效，同现 step-reset）。
- `gate`：按 advance_state 同规则重算——T 的前驱节点 phase 在 GATED_AFTER 则 `passed`，否则 `pending`（T=understand:1 无前驱 -> `pending`）。
- `last_judged_trace`：删 key 属于「节点序 > T」的全部游标 + T 节点 `k >= n` 的游标（不清会让同内容 trace 被判「无新产出」静默跳过）。
- `history`：截断——删 entered 节点序 > T 的条目；T 条目 `exited_at=None`（重开），via 不改（保留原始进入路径留痕）。T 无条目时 append 一条（via=`state-reset`）。
- `enforce_step_fence`、`session_id` 等其余字段不动。

### 3.3 阶段产物直接删除

删 **T.phase 及之后所有 phase** 的产物（T.phase 自己的产物也删——回退到 phase 中段，其末段产物必为重写对象；understand.md 类前期产物不在范围内，因为目标在 plan 时 T.phase=plan）：

- 主仓规范位置：`<项目>/.claude/<dir>/<name>.md`（dir = understands/plans/reviews/evolutions，execute 无产物）。
- legacy worktree 根位置：`<项目>/.claude/worktrees/<name>/<artifact>.md`（understand.md/plan.md/review.md/evolution.md）。
- 文件不存在 = 正常（非错误）；删除结果逐个报告。
- **不动**：`designs/*.md`（git 可追踪的用户文档）、worktree 代码与 commit（跨 execute 回滚时代码原地保留，用户自行 git 处理——本命令只管编排状态与证据，不管源码）。

### 3.4 合法性校验（全部报错暴露，不猜）

- T 节点不存在 / minor 既非序号也非 minor_key → 报错 + 列该 phase 合法子阶段。
- step 越界（1..节点子步骤总数）→ 报错。
- T 严格在**当前位置之后**（前向重置）→ 报错（指针只能回退；想往前用 /dl next /dl jump）。
- T == 当前位置 → 退化为节点内回退（等价旧 step-reset <n>）。
- 当前在无子步骤节点且用一段式 `<n>` → 报错（同现 step-reset）。

## 4. 命令层改动（废弃 step-reset）

| 文件 | 改动 |
|---|---|
| `dl-flow-engine.py` | 新增 `reset_state()`；删 `reset_sub_step()`（逻辑被 reset_state 单节点分支吸收）；CLI `step-reset` 子命令改 `state-reset` |
| `scripts/workflow/dl-cmd.sh` | case `step-reset)` 改 `state-reset)`，注释/usage 同步 |
| `commands/dl.md` | description 用法串同步 |
| `scripts/workflow/phase-rules.md` | §117 门栏提示 `/dl step-reset <n>` -> `/dl state-reset <n>` |
| `hooks/workflow_advance.py` / `workflow_phase.py` | 门栏提示文案同步 |
| `tests/test_dl_flow_engine.py` | step-reset 用例改 state-reset + 新增跨节点用例 |
| skill references（diagnostics.md / node-design.md） | step-reset 提及处同步 |

install 面：hooks 直接引用源无需动；`commands/dl.md` + phase-rules.md 走 `install.sh` 重 copy，**重启会话**后 `/dl state-reset` 可用。

## 5. 测试点（TDD 先行）

1. 单节点回退（一段式）≈ 旧 step-reset 语义保留（删行数/游标/held_for_gate/重试计数）；**唯一行为差**：T 自身的节点级 gate 裁决行（无 sub_step 字段）现也删（§3.1 第 2 条理由：回退到 T 中段，旧「已过」裁决已失效，留着误导审计），旧 TestResetSubStep 对应用例同步改。
2. 跨子阶段：当前 understand:2，reset understand:ProblemContext:4 -> state 回 understand:1 子4；understand:2 的 trace/gate 行删，understand:1 子>=4 删、子1-3 保留。
3. 跨 phase：当前 plan:1，reset understand:4:5 -> plans/understands 产物按 §3.3 规则删；history 截断；gate 字段重算。
4. 节点级 gate 行在 T 上被删（§3.1 第 2 条）。
5. 前向重置 / 未知 minor / step 越界 / 无子步骤节点三段式 -> 各报错。
6. 坏行与他节点行保留（暴露而非吞掉）。
