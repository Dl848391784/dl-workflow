# 工作流五阶段中文显示名（Design-First，H8）

> 状态：已实现（2026-07-22）。本文件为 H8 Design-First 产物。
> 真源父文档：`designs/workflow-system-design.md`。本文件仅记录「中文显示名」这一增量。

## 0. 背景

用户需求：工作流五阶段在终端展示中文名（理解和求证问题 / 生成执行计划 / 执行 / 审核结果 / 进化），替代纯英文标识。

## 1. 核心铁律：显示=中文，逻辑=英文

英文标识（`understand`/`plan`/`execute`/`review`/`evolution`）是**逻辑层值**，必须保持不变：

| 逻辑层用途 | 为什么不能动 |
|---|---|
| `state.json` 的 `phase` 字段 | 已存在工作流的 state 兼容性 |
| `### PHASE_DONE: <phase>` 标记 | `workflow_advance.py` 的 `DONE_RE` 正则匹配 |
| `/wf jump <phase>` 参数 | `wf_phase_index` 按英文匹配 |
| `wf-lib.sh` `WF_PHASES` 数组 | 阶段顺序/闸门判定 |

中文名**仅用于给人看的显示**（横幅 / status / 注入段 / launcher / list / 阶段切换框）。英文标识仍可在 `/wf status` 的「阶段顺序」行查到（供 `/wf jump`）。

## 2. 阶段名映射（canonical）

| 英文标识 | 中文显示名 |
|---|---|
| understand | 理解和求证问题 |
| plan | 生成执行计划 |
| execute | 执行 |
| review | 审核结果 |
| evolution | 进化 |

## 3. 显示格式决策

经用户确认：**仅中文名**。横幅 `## PHASE: 理解和求证问题 [1/5]`，不并列英文。`/wf status` 的 `阶段顺序:` 行仍列英文标识（`/wf jump` 可用）。

## 4. 映射定义点（每运行时一份，沿用现有 PHASES 重复持有范式）

- **bash**：`scripts/workflow/wf-lib.sh` 定义 `WF_PHASE_LABELS`（assoc array）+ `wf_phase_label()`，`wf-cmd.sh`/`wf-launch.sh` source 后调用（单一定义点）。
- **python**：`.claude/hooks/workflow_phase.py` 与 `workflow_advance.py` 各持一份 `PHASE_LABELS` dict（与各自 `PHASES` 一致，避免跨语言 source）。

## 5. 受影响文件

| 文件 | 改动 |
|---|---|
| `.claude/hooks/workflow_phase.py` | `PHASE_LABELS` + 注入 `阶段:` 行用标签 + 注入「任务清单目标状态」块 |
| `.claude/hooks/workflow_advance.py` | `PHASE_LABELS` + 三处 `_emit` 横幅用标签；框简化为左侧边框（中文等宽对齐） |
| `.claude/output-styles/workflow.md` | 横幅格式中文 + 新增「常驻阶段任务清单」首要规则（TaskCreate/TaskUpdate 同步） |
| `scripts/workflow/wf-lib.sh` | `WF_PHASE_LABELS` + `wf_phase_label()` + `wf_list` |
| `scripts/workflow/wf-cmd.sh` | status/next/back/jump/gate 回显用标签 |
| `scripts/workflow/wf-launch.sh` | launcher 当前阶段/跳转回显用标签 |
| `scripts/workflow/phase-rules.md` | 5 阶段标题中文 + 总则加「常驻阶段清单」维护规则 |
| `.claude/skills/workflow-creation/SKILL.md` | 阶段描述中文同步 |

## 6. 常驻阶段清单（原生 TaskList，2026-07-22 增量）

用户需求：进入工作流后，5 阶段作**常驻进度清单**一直显示，已完成打勾、当前高亮，复用 Claude 原生置顶任务 UI（整轮不滚动）。

### 机制
- **源真值**仍是 hook 管的 `state.json`（`phase`/`index`）。任务清单**只做镜像**，不反向写 state。
- **模型驱动**：模型用 `TaskCreate`/`TaskUpdate` 维护 5 个阶段任务（subject=各阶段中文名）。
- **hook 预渲染目标状态**：`workflow_phase.py` 每轮注入「任务清单」块，给出每阶段应为何状态（按当前 index：< current=completed、=current=in_progress、>current=pending），模型直接对齐，无需自行计算。
- **轻量自愈**：首轮建齐 5 个并设状态；其后每轮仅当 in_progress 任务与当前阶段不符时 `TaskUpdate` 对齐（约每阶段一次）。续接后清单缺失则重建。

### 闸门与状态镜像
- 闸门阶段（understand/plan 完成但 gate 未放行）：state 未推进，当前阶段仍 in_progress（非 completed）--清单镜像 state，故该阶段保持 in_progress，准确反映「待放行」。gate 放行+推进后下一轮才标 completed。

### 取舍（已知，用户已确认选此方案）
- 原生 UI 整轮置顶不滚动 = 用户要的「一直展示」。
- 代价：模型每轮维护同步（注入强提醒 + 给出目标状态降低负担）；execute 工作子任务会并入同一清单（规则：追加在下方，勿动 5 个阶段任务）。

### 旧文本横幅 `## PHASE: <中文名> [n/5]`
保留为次要文本锚点（首行），与置顶清单互补；置顶清单是主显示。

## 7. 生效条件（worktree 快照铁律）

改 hook / output-style / 脚本后，worktree 内是 git checkout 快照，**需 commit + 重建 worktree** 才在运行中的工作流生效（见 workflow-creation skill 总根因）。本机制改了 `workflow_phase.py` + `workflow.md` + `phase-rules.md`，均需此步骤。

## 8. 验证

- `python3 -c "...import workflow_phase; print(_format_injection({'phase':'execute','index':3,...}))"` -> 注入含「任务清单」块，5 行目标状态正确，PHASE_DONE 行仍英文。
- `source scripts/workflow/wf-lib.sh; wf_phase_label understand` -> `理解和求证问题`。
- 实跑验证：`dl test` 新建工作流，确认首轮模型 TaskCreate 出 5 阶段任务（understand=in_progress），推进后清单逐个打勾。
