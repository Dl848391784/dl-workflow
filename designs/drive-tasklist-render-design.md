# drive 模式进度透出与开场采集设计（v3.0 dogfood 缺口修复）

> 状态：已定稿（2026-08-09 用户裁决后开工）。缘起：v3.0 headless driver（headless-driver-arch-design.md）首次 dogfood（interaction_turnover__ret3d_abs_annualized）实测两缺口。
> 用户裁决链（本设计的前提，勿推翻）：①v3.0 的 TaskList 透出要和 v2.0 一样——总步数/当前步/下一步可见、钉在底部常驻、有动态效果；②编排循环必须保持 Python driver 确定性执行，「靠模型执行步骤」不可接受（v3.1 主会话调度方案当场否决）；③子会话进度不用展示。

## 1. 问题

**缺口 1：TaskList 没透出。** v2.0 常驻清单 = output-style 强制模型 TaskCreate 13 项 + TUI TaskList 组件常驻展示，依附「单长会话 TUI」。v3.0 后：(a) headless 段（`claude -p`）无 TUI，原生组件物理不存在，用户主观察面 = driver stdout（当时只有单行进度 + 子会话输出流尾随）；(b) TUI 交互段 outputStyle=workflow 义务仍在，但瘦版 node-rules 稀释（「只做当前一个子步骤」与「建 13 项清单」观感冲突），dogfood transcript 实证零 TaskCreate；(c) v3.0 设计文档对透出零约定 = 设计缺口非实现 bug。

**缺口 2：用户问题未采集就开始分析。** v2.0 用户首条 TUI 消息 = 问题陈述；v3.0 `dl <name>` 直接起 driver 派子步骤，用户唯一输入 = 工作流名 slug。understand:1 子1 purpose 的前提假设「上下文已有用户原话」在 v3.0 下不成立，模型面对 slug 自力更生翻仓库（transcript 实锤：20+ 轮工具调用翻 sibling evidence/backtest，零 AskUserQuestion），用户等不到提问中断会话。

**硬约束（方案边界）**：原生 TaskList 是 TUI 会话私有组件，只能被该会话内模型 TaskCreate/TaskUpdate 驱动；Claude Code 无外部进程向运行中 TUI 会话推事件的通道。故「Python driver 跑循环 + 原生组件全程在屏」不可造，按段落各用最优面。

## 2. 方案

### 2.1 driver stdout 升级为 rich Live 常驻渲染区（headless 段主面）

「钉不住」的根因不是重印，是子会话输出流尾随冲刷屏幕；用户明示子会话进度不用展示 → 关尾随，底部常驻区成立。

- **渲染**：`rich.live.Live`（环境已验证可用，零新增依赖）底部常驻区，~4fps 原地重绘：
  - 全 13 项（5 阶段 + understand/plan 各 4 子阶段）+ **当前节点展开子步骤**（Step.short 短名）；
  - 状态标记：✓ 已完成 / ▸+spinner 当前 / · 待办；当前行带耗时（秒级跳动）与「最近动作」一行（尾随解析 drive-stream.jsonl 取最后一条工具调用简报——「不展示进度」（不刷全文）与「知道它没死」（活跃信号）兼得）；
  - 数据 100% 机械读 state.json（磁盘真源）+ engine 节点树（单源）——✓ 翻转瞬间 = gate pass 落盘瞬间，比原生组件（靠模型自觉 TaskUpdate）更准；
  - 阶段行尾标 gate: pending/passed。
- **关尾随**：run_session 不再 print assistant text（仍全量落 drive-stream.jsonl 审计；`--verbose` flag 可恢复旧行为）。
- **让位**：TUI 交互段与 stdin 断点（breakpoint_loop/开场采集）期间 Live 暂停，交还终端，结束后恢复。

### 2.2 engine 新增 progress_rows(state) 纯函数（渲染数据单源）

- 签名 `progress_rows(state: dict) -> list[dict]`，每行 `{depth, label, status, extra}`（status ∈ done/current/todo）；节点线性序 = `_NODES` 声明序；子步骤状态按 `state["sub_step_index"]`。
- engine 不依赖 rich——结构化数据进 engine（可测），rich 渲染归 driver。

### 2.3 TUI 交互段恢复原生 TaskList（v2.0 体验原位保留）

`build_step_prompt` interactive 分支尾部补硬条款：「会话开场第一件事 = 按 output-style 用 TaskCreate 建齐 13 项阶段清单（subject 带编号），状态镜像当前 state，再做本子步」——prompt 显著性兜底被稀释的 output-style 义务。用户答题时看到的就是 2.0 原生组件。

### 2.4 开场问题陈述采集（根治缺口 2）——**2026-08-09 修订2：裸开场（v2.0 原位）**

> **修订记录**（两轮迭代收敛）：初版 = driver stdin `input()` 断点采集（素终端提示）→ 用户质询「为啥不是 claude 那种对话式」→ 修订1 = 采集挪 sub1 TUI prompt 条款（对话式问），撤 driver input() → 用户再质询「为啥一进会话就喂一大堆任务书 prompt，我要 v2.0 那样什么也不加载、我问完问题才开始」→ **修订2 = 裸开场（本版定稿）**。
>
> **修订2 裁决**：understand:1#1（全工作流开场步）无返工时，TUI 启动**不喂任何 prompt**（`claude` 无位置参数 = 会话开了安静等用户打字）——v2.0 原位开场。任务书与系统提示词本就是**重复**的（node-rules 的「本节点子步骤清单」含子1 完整目的；build_step_prompt 为 headless 无注入通道设计，TUI 段复用属冗余）：用户提交陈述瞬间三通道自然就位——①node-rules 系统提示词（子1 目的+落库纪律）；②workflow_phase hook 提交时注入（当前阶段+任务清单目标状态，v2.0 老机制未坏）；③output-style（TaskList 义务）。
> **防波堤**：裸开场未落 trace → driver none 重试自动换回完整任务书 prompt（`_is_bare_open` 对 pending_rework 返 False）——**主路裸开场，任务书降级为返工兜底**。其余 12 个交互步（读回/裁决需模型先呈现材料再提问）保持任务书驱动。
> `state.problem_statement` 字段与 handoff_pack 收录通道保留（不再自动采集，留作手动注入通道）。

- 实现：`run_tui_step(bare=)` 省略位置参数（`_build_tui_cmd` prompt=None）；`_is_bare_open(node, cur, pending_rework)` 单源判定；
- 用户陈述经子1 trace 天然携带给后续步骤（handoff_pack 通道不变）；陈述丢失场景（裸开场没落库）= none 重试走任务书 prompt，其「对话式问问题陈述」条款重新采集。

### 2.5 不做

- 不改编排循环任何分支逻辑（Python driver 确定性原样）；不改 output-style/phase-rules 模板；headless 子会话本身不动；
- `/dl status` 共享 progress_rows 留作后续项；live 区配色/字形不追求 1:1 仿原生组件（硬约束：原生只在 TUI 内）。

## 3. 文件面

| 文件 | 改什么 |
|---|---|
| `dl_flow_engine.py` | `progress_rows(state)`；state `problem_statement` 字段（写入助手）；`handoff_pack` 顶部收录问题陈述 |
| `scripts/workflow/dl_drive.py` | rich Live 常驻渲染（含让位逻辑）；run_session 关尾随 + `--verbose`；interactive prompt TaskList 条款 + understand:1#1 对话式采集条款（§2.4 修订） |
| `tests/test_dl_flow_engine.py` | progress_rows 测例（各节点/子步骤位置 → 断言 status 落位与展开行为）；problem_statement 进 handoff_pack 测例 |

## 4. 验证

1. pytest 全绿（新测例 + 回归）+ ruff clean；
2. dogfood 真机：`dl interaction_turnover__ret3d_abs_annualized --resume`——sub1 TUI 段开场对话式问问题陈述（不再先探查）；headless 段底部 live 区 spinner/耗时/✓ 翻转可见、屏幕不被子会话输出冲刷；TUI 交互段原生 TaskList 建齐。

## 5. 关联

- 架构真源：designs/headless-driver-arch-design.md（本设计补其透出与采集缺口，M3 dogfood 反馈第一批）；
- 被否方案存档：v3.1 主会话调度（模型执行循环）——用户当场否决，理由「靠模型执行步骤接受不了」；driver stdout 静态重印——被「原生有动态效果」反馈超越，升级为 rich Live。
