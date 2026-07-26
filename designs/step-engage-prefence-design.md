# S15 参与前置围栏：零 trace 窗口的 PreToolUse 白名单

> 状态：**已实施**（2026-07-26；engine/hooks/注入/phase-rules/SKILL/tests 已同步）
> 父文档：`substep-gate-at-stop-design.md`（S10-S14 围栏体系）、`node-step-orchestration-design.md`（子步骤编排）

## 0. 动因：S13 在回合末才拦，用户看到模型抢答后才纠偏，太晚

实录（2026-07-26，session b01d6507，MiniMax-M3）：fresh 工作流首回合，用户问
「现在有多少个因子？」，模型完全无视编排——无横幅、无 TaskCreate、未 invoke
define-problem，直接 `ls`+grep Bash 探查回答。机制侧全部正常（hook 注入成功、
output-style 激活、state 正确）。

phase-rules 早已禁此行为（「子步骤1 横幅后立即、在其它任何动作之前 invoke，
探查一律不得在 invoke 之前」）——**文案=概率遵从，该模型遵从率为 0**。

现有 S13 参与围栏（Stop hook：零 trace 结束回合 → block_continue 强制续轮）
能兜住这个场景，但触发点在**回合末**：模型已经把整段答案输出给用户了，
纠偏发生在错误暴露之后。用户中途打断则 S13 连开火机会都没有
（中断不产生 Stop 事件）——本次实录正是如此。

**症状 P 元教训的推论**：围栏触发点越早，弱遵从模型的偏航成本越低。
把 S13 的判据（当前子步骤零 trace）前置到 PreToolUse：模型为「直接回答用户」
而发起的第一个工具调用即被 deny，deny 文案把它指回编排。

## 1. 设计：零 trace 窗口 = 白名单模式

### 1.1 触发条件（与 S13 同判据，单源在 engine）

当前节点有 `sub_steps` AND 当前子步骤 `latest_trace_sha1(...) is None`
（零 trace 窗口）AND `state.enforce_step_fence`（复用 S10 开关，
`/dl fence on|off` 统一切换）。

engine 新函数 `engagement_fence_state(project_root, name) -> tuple[int, Step] | None`：
窗口内返回（当前子步骤号， Step），否则 None。与 `pending_unjudged_step`
（S10 判据）互斥互补：

| 当前子步骤状态 | 机制 | 行为 |
|---|---|---|
| 零 trace | **S15（本设计）** | 白名单：仅编排工具可用 |
| 有 trace 未判决 | S10 | 全 deny：唯一出路 STEP_DONE + end_turn |
| 已判决 | — | 自由 |

### 1.2 白名单（窗口内放行）

**常驻集**（所有子步骤，编排原语 + 无害只读）：

- `AskUserQuestion` — 回合内问用户（S13 协议的合法交互通道）
- `Skill` — invoke 子步骤声明的 skill（kind=skill 步的入口）
- `TaskCreate/TaskUpdate/TaskGet/TaskList` — 常驻清单义务
- `Read/Grep/Glob` — 只读探查。放行理由：①子2 证据源含日志/数据文件；
  ②子4 红队子代理（Agent 子进程的工具调用同样过 PreToolUse）需要读证据；
  ③纯 text 抢答本就无法用工具围栏拦截，S13 在 Stop 兜底——Read 不构成新漏洞
- Write 系（Edit/Write/MultiEdit/NotebookEdit）仅目标为**本工作流 evidence 文件**
  （与 S14 覆盖守卫、S11 阶段白名单天然互补，两道检查独立通过才放行）
- Bash 仅三类编排命令（子串匹配）：
  1. `dl-cmd.sh`（/dl status 等状态查询）
  2. 命令含 evidence **绝对路径**（append 写 evidence；相对路径写 = 症状 L，
     恰好被此条件拦下并指回绝对路径）
  3. 含 `codegraph` 词（子2/3 的内部结构查证；H15 生态内工具）

**步骤声明扩展**：`Step.fence_allow: tuple[str, ...] = ()`（engine 单源，
冻结 dataclass 加默认值，向后兼容）。当前 understand:1 声明：

| 子步骤 | fence_allow | 理由 |
|---|---|---|
| 1 逼问定义 | () | 纯交互（skill + AskUserQuestion 已在常驻集） |
| 2 拆解深挖 | () | codegraph 在常驻 Bash 模式；日志/数据走 Read |
| 3 双向取证 | `("Bash", "WebFetch")` | curl 五层源 + 定点网页抓取 |
| 4 质检裁决 | `("Agent",)` | 条件触发红队子代理 |
| 5 归一化陈述 | () | 纯合成 |
| 6 读回确认 | () | AskUserQuestion 在常驻集 |

**窗口内一律 deny**：WebSearch / mcp__tavily_*（与子3「禁 tavily/WebSearch」
硬约束一致——此前只是文案，现在变物理）/ 未声明的 Bash / 未声明的 Agent /
WebFetch（子3 外）等。

### 1.3 deny 文案

指路型（§3.5 #5 判词要指路原则在围栏层的应用）：报当前子步骤号 + Step.ref +
purpose 摘要，列本步合法动作（invoke skill / AskUserQuestion / 写 evidence →
STEP_DONE → end_turn），注明 `/dl fence off` 出口。Bash 因 evidence 相对路径
被拦时，文案给出绝对路径。

## 2. 关键决策

### 2.1 白名单制而非黑名单制

黑名单（只拦「明显像回答用户任务」的工具）无法定义——`ls` 在子3 是合法探查、
在子1 是抢答。白名单按**步骤声明**放行，新增编排节点时强制显式思考
「本步需要什么工具」（fence_allow 与 ref/purpose 同处声明，单源）。

### 2.2 Read/Grep/Glob 常驻放行（接受 text 抢答不可工具拦截）

围栏的真实价值是**提前信号 + 堵工具辅助的偏航**（demo 的 Bash 探查），
不是也不可能阻止纯 text 抢答——那由 S13 在 Stop 兜底。把 Read 也拦了
并不能多拦任何一类违规（模型不 Read 也能编答案），却会误伤子2/子4 的
合法取证与红队子代理。两栏（S15 提前信号 + S13 回合末硬兜底）互补覆盖。

### 2.3 Bash 子串匹配的走私面（接受的限制）

`codegraph sync && <任意命令>` 这类复合命令会穿过 Bash 模式匹配。
威胁模型是**弱遵从模型**（不是对抗性攻击者）——它不会刻意构造走私命令，
只会「顺手跑个 ls」。同 S11 的 Bash 写盲区一致，文档明示即可。

### 2.4 复用 enforce_step_fence 开关，不加新开关

S15 与 S10 同属「子步骤围栏」族（dl-cmd fence on|off 注释已写「统一切换」）。
新增独立开关 = 多一个半状态组合，无对应使用场景。

### 2.5 judge / 子代理不受影响

- judge：`run_judge` 的 `claude -p` cwd=tempdir（非 git）→ hook 反查不到
  项目根，静默退出（症状 N 修复的既有行为）。
- 红队子代理（子4）：Agent 调用本身在子4 fence_allow 内；子代理进程的
  Read/Grep 在常驻集。子代理若需 Bash/WebFetch 会被拦——可接受
  （prompt 已带证据，职责是推理不是取证），如需放开在子4 fence_allow 追加。

## 3. 与现有机制的关系

| 机制 | 守什么 | 与 S15 关系 |
|---|---|---|
| S10 步骤围栏 | 写完 evidence 后等判决 | 状态互斥（零 trace vs 未判决 trace），接力覆盖 |
| S11 阶段写围栏 | understand/plan 禁写源码 | 叠加：S15 窗口内写工具仅 evidence 路径，S11 再验白名单 |
| S13 参与围栏（Stop） | 零 trace 结束回合 | 同判据后置兜底：S15 拦工具辅助偏航，S13 拦纯 text 抢答 |
| S14 evidence 覆盖守卫 | append 协议 | 叠加：S15 放行 evidence 写后 S14 再验内容不丢行 |

## 4. 实施 checklist（症状 M）

1. `dl-flow-engine.py`：Step.fence_allow + understand:1 六步声明 + `engagement_fence_state()`
2. `hooks/workflow_step_fence.py`：S15 白名单判定（S10 检查之前，两态互斥）
3. `hooks/workflow_phase.py` `_format_injection`：子步骤块加前置围栏提示行
4. `scripts/workflow/phase-rules.md`：硬围栏段补 S15 语义（system-prompt 通道）
5. `tests/test_workflow_step_fence.py`：新文件（in-process importlib 模式）——
   零 trace 窗口 allow/deny 用例 + fence off 放行 + 非窗口放行；
   `tests/test_dl_flow_engine.py`：engagement_fence_state 单测
6. `skills/workflow-creation/SKILL.md`：症状 O 加 S15 段落、症状 P 表「抢答」行补 S15
7. 冒烟：`dl demo --resume` 发无关问题，验证首个 Bash 被 deny 且文案指路
