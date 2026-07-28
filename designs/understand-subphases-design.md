# understand 阶段子阶段（Design-First，H8）

> 状态：已实现（2026-07-23）。本文件为 H8 Design-First 产物。
> **变更（2026-07-28 用户决议）**：understand->plan 闸门撤除（围栏只设在 plan 完成）——understand:4 末步过门控自动进 plan:1，无 `### PHASE_DONE: understand` 通道；understand.md 改在 understand:4 子5 内装配。本文 §24/45/57 的 PHASE_DONE: understand + 闸门描述已被该决议取代。
> 真源父文档：`designs/workflow-system-design.md`。本文件记录「understand 拆 4 子阶段」这一增量，子阶段推进机制与大阶段同构。

## 0. 背景

用户需求：工作流第一阶段 understand（理解和求证问题）拆成 4 个**子阶段**，依次执行；子阶段的执行/推进/展示方式**与大阶段保持一致**（标记 -> Stop hook -> state -> 清单镜像），并在 understand 下展示成可勾选清单（执行完=选中/completed 状态）。

4 个子阶段（顺序）：

| n | 子阶段 | goal |
|---|---|---|
| 1 | 理解问题和背景 | 理清字面请求 + 背景上下文 + 问题背后要解决的本质（真实问题） |
| 2 | 明确目标和价值 | 明确本次达成什么、为谁解决什么、价值；分 must/nice |
| 3 | 确定范围与约束 | in/out-scope + 技术/数据/资源/铁律约束（H1/H7/H9/H11 等） |
| 4 | 定义成功标准和验收方式 | 可验证成功标准（量化/可观测）+ 验收方式（测试/证据/file:line/数据契约）；汇总写 understand.md |

understand.md 结构不变（真实问题重述 + 边界 + 成功标准），4 子阶段是它的分步生产：sub1->真实问题重述、sub2->目标价值、sub3->边界（范围+约束）、sub4->成功标准+验收。

## 1. 设计决策（已与用户确认）

- **推进机制 = hook 强制**（非模型自驱）：state.json 加 `sub_index`/`sub_total`；模型输出 `### SUB_DONE: <n>` 标记；Stop hook 检测后推进 `sub_index`；hook 注入子阶段目标状态，模型镜像成 TaskList 子任务。与大阶段完全同构，可强制依次执行。
- **子阶段间无闸门**：sub1->sub2->sub3->sub4 自动推进（与 execute->review->evolution 一致）。understand->plan 闸门**不变**，在第 4 子阶段完成、`### PHASE_DONE: understand` 时触发。共 1 个闸门，与现有阶段闸门数一致。
- **机制通用化**：子阶段按 phase 配置（`SUBPHASES` dict），目前仅 understand 有 4 个，其他阶段 0。plan 等阶段以后可扩展，无需重设计。

## 2. state.json schema 变更

```json
{
  "name": "...", "phase": "understand", "index": 1,
  "sub_index": 1,   // NEW：当前子阶段（1-based）；阶段无子阶段时=0
  "sub_total": 4,   // NEW：当前阶段子阶段数；无子阶段时=0
  "gate": "pending", ...
}
```

- `wf_state_init`：新工作流起于 understand -> `sub_index=1, sub_total=4`。
- `wf_state_set_phase`：设阶段时按 `wf_sub_total(phase)` 重置 `sub_total`、`sub_index`（有子阶段=1，否则=0）；gate 重置 pending。
- **向后兼容**：旧 state.json 无此二字段 -> hook 默认 `sub_total=0` -> 无子阶段 -> 行为同今（旧 understand 工作流续接仍可直接 `PHASE_DONE: understand`，不强制子阶段）。

## 3. 标记规则（核心，自纠错）

- 子阶段 **1..(N-1)** 完成 -> 输出 `### SUB_DONE: <n>` -> Stop hook 推进 `sub_index`（n->n+1），打印子阶段切换横幅。
- 末子阶段 **N** 完成 -> 写 understand.md + 输出 `### PHASE_DONE: understand`（**不**输出 `SUB_DONE:N`）-> 触发 understand->plan 闸门。
- **守卫**（Stop hook 在 `PHASE_DONE:understand` 检测后、闸门判定前）：若 `sub_total>0 且 sub_index<sub_total` -> **阻断**，提示"还有子阶段未完成，先依次 SUB_DONE 再 PHASE_DONE"。强制依次执行。
- **防御**：若模型对末子阶段误输出 `SUB_DONE:N` -> 忽略（`sub_done_last_ignored`，no-op），下轮注入仍显示末子阶段，模型自纠输出 PHASE_DONE。
- SUB_DONE 优先于 PHASE_DONE 检测（同轮只会有其一：子 1-3 轮出 SUB_DONE，子 4 轮出 PHASE_DONE）。

### 推进时序（正常路径）

```
sub1 工作 -> ### SUB_DONE: 1  (Stop: sub_index 1->2)
sub2 工作 -> ### SUB_DONE: 2  (Stop: sub_index 2->3)
sub3 工作 -> ### SUB_DONE: 3  (Stop: sub_index 3->4)
sub4 工作 + 写 understand.md -> ### PHASE_DONE: understand
  (Stop: 守卫 sub_index==4==sub_total 通过 -> 闸门 understand->plan 待放行)
用户 /dl gate -> /dl next -> plan
```

### 守卫阻断（模型提前 PHASE_DONE）

```
[在 sub2] 模型误输出 ### PHASE_DONE: understand
  -> Stop: 守卫 sub_index(2) < sub_total(4) -> 阻断
  -> 提示"先依次完成子阶段 2/3/4（SUB_DONE）再 PHASE_DONE"
```

## 4. 显示（"在 understand 下展示，执行完选中状态"）

- **注入块**（每轮，模型必读通道）：`workflow_phase.py` 在 `## WORKFLOW 当前阶段` 块加「子阶段 [n/N]: **当前子阶段名**」+ 4 子阶段目标状态行（completed/in_progress/pending）+ 末子阶段标记指引。
- **原生 TaskList**（主显示）：understand 阶段清单 = `1.理解和求证问题` -> `1.1理解问题和背景`~`1.4定义成功标准和验收方式` -> `2.生成执行计划`~`5.进化`（共 9 项，1.1-1.4 紧跟任务 1）。首轮按注入顺序建齐 9 项并设状态；每轮镜像注入目标（完成的子阶段 -> completed 勾选 = "选中状态"）。1.1-1.4 全程保留（understand 完成后保持 completed）。
  - 顺序靠**创建顺序**保证（首轮建：1, 1.1-1.4, 2-5）。旧工作流续接建子任务会落底部（边角，已知）。
- **文本锚点**：`## PHASE: 理解和求证问题 [1/5] · 子阶段 [1/4] 理解问题和背景`。

## 5. 受影响文件

| 文件 | 改动 | 生效方式 |
|---|---|---|
| `scripts/workflow/dl-lib.sh` | `WF_SUBPHASES_UNDERSTAND` 数组 + `wf_sub_total()`/`wf_sub_label()`；`wf_state_init` 加 sub_index/sub_total=1/4；`wf_state_set_phase` 按阶段重置二字段 | 下次 `dl`/`/dl` 即最新（直接跑源） |
| `hooks/workflow_advance.py` | `SUBPHASES` dict + `SUB_DONE_RE`；main() 先查 SUB_DONE->推进 sub_index+横幅；PHASE_DONE 后插子阶段守卫 | 下轮 hook 触发即最新（settings.json 引用源，无需 install） |
| `hooks/workflow_phase.py` | `SUBPHASES` dict；`_format_injection` 加子阶段行+目标状态块+末子阶段标记指引；任务清单块扩展 | 同上，无需 install |
| `scripts/workflow/dl-cmd.sh` | `status` 增 `子阶段: <label> [sub_idx/sub_total]` 行（sub_total>0 时） | 直接跑源，无需 install |
| `scripts/workflow/phase-rules.md` | understand 段重写为 4 子阶段（各 goal+标记）；加通用「阶段可有子阶段」规则 | install.sh + 重启会话 |
| `output-styles/workflow.md` | `## PHASE:` 头加 `· 子阶段 [n/N] <名>`；TaskList 规则扩展（understand 首轮建 1+1.1-1.4+2-5）；PHASE_DONE 规则区分末子阶段 | install.sh + 重启会话 |
| `skills/workflow-creation/SKILL.md` | 同步「understand 含 4 子阶段」一句 | install.sh + 重启 |

> 子阶段定义按现有「每运行时一份」范式在 bash（`dl-lib.sh`）+ python（两个 hook）三处各持一份（与 `PHASES`/`PHASE_LABELS` 重复持有一致，避免跨语言 source，见 chinese-labels 设计 §4）。

## 6. 实施步骤（6 个小 commit，每 ≤3 文件）

1. `designs/understand-subphases-design.md`（本文档，H8）
2. `scripts/workflow/dl-lib.sh`（子阶段定义 + state schema）
3. `hooks/workflow_advance.py`（SUB_DONE 推进 + 守卫）← 改前先 `codegraph affected` 留痕解锁 H15
4. `hooks/workflow_phase.py`（子阶段注入）← 同上解锁
5. `scripts/workflow/dl-cmd.sh` + `phase-rules.md` + `output-styles/workflow.md`（显示/规则层）
6. `skills/workflow-creation/SKILL.md` 同步 + `install.sh` + 重启会话 + smoke test

## 7. 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| 1 | Stop hook transcript 读取脆弱性（-p transcript 空、ark 收不到 attachment） | 与现有 PHASE_DONE 同路径，无新增脆弱类；沿用既有兜底（交互 TTY + 模型 `dl-cmd.sh status` 自取）。验证禁 -p/管道 |
| 2 | TaskList 顺序：1.1-1.4 须紧跟任务 1 | 靠创建顺序（首轮建 1,1.1-1.4,2-5）；旧工作流续接建子任务落底部（边角，已知） |
| 3 | 模型合规：子 1-3 须出 SUB_DONE、子 4 出 PHASE_DONE | 注入 + phase-rules 明示；守卫兜底（早出 PHASE_DONE 被阻） |
| 4 | H15 跨 repo：编辑 dl-workflow 两个 .py 触发本项目门禁 | 先跑一次 `codegraph affected <file>` 留痕解锁（弱门禁：挡零查询，不挡查错 symbol） |

## 8. 验证（smoke，真实交互 TTY）

`dl subphase-smoke`：
- 首轮建 9 项清单（1=in_progress、1.1=in_progress、1.2-1.4=pending、2-5=pending）；`.wf_phase.log` 见 `injected` 含子阶段信息。
- 子 1 工作 -> `### SUB_DONE: 1` -> `.wf_advance.log` 见 `sub_advanced`、sub_index 1->2；下轮注入显示子阶段 2。
- 重复至子 3 -> sub_index=4。
- 子 4 写 understand.md + `### PHASE_DONE: understand` -> 守卫过（sub_index==4）-> 闸门待放行横幅。
- **反向测**：子 2 时提前输出 `### PHASE_DONE: understand` -> 应被守卫阻断（`phase_done_subphases_incomplete`）。
