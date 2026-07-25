# Workflow System Design（understand -> plan -> execute -> review -> evolution）

> 状态：设计中（2026-07-22 起）。本文件为 H8 Design-First 产物，也是工作流子系统的真源。
> 对应实现：`scripts/workflow/`、`.claude/hooks/workflow_*.py`、`.claude/output-styles/workflow.md`、`.claude/commands/dl*.md`、`~/.bashrc` ac-ark。

## 0. 背景与目标

用户需求：在 `ac-ark`（`~/.bashrc` 中封装 claude 的 bash 函数）基础上，建立一套五阶段工作流
（understand / plan / execute / review / evolution），并要三个功能：

1. **ac-ark 参数进工作流**：`ac-ark` 在原有模型命令基础上增加参数，表示"进入工作流"。
2. **CLI 显示阶段、不显示思考**：终端展示当前处于哪个阶段，不展示模型的推理思考。
3. **文件隔离 + 分支隔离**：每个工作流以文件形式相互隔离，git 分支也隔离。

五阶段语义：
- **understand**：理解意图，理清"真实问题"（不是用户字面问题，是问题背后要解决的本质）。
- **plan**：根据真实问题制定计划。
- **execute**：执行计划。
- **review**：审核是否真的解决了真实问题。
- **evolution**：进化——把本次经验沉淀为可复用的 memory / skill / design 更新。

## 1. 关键事实（设计前已核实）

| 事实 | 来源 | 对设计的影响 |
|---|---|---|
| `ac-ark` 是 `~/.bashrc` 的 bash 函数（设 ark env + `claude --debug api,hooks ...`） | `~/.bashrc:52-60` | bashrc 只加瘦分支，重逻辑委派 repo 内 launcher（dotfile 不版本化，重逻辑进 repo） |
| claude 已有 `-w/--worktree`（per-session worktree）和 `--tmux` | `claude --help` | 工作流短参数**不能用 `-w`**（会与原生 worktree 冲突）；用长 `--workflow` |
| `--settings <file>` 可追加一份 per-workflow 配置 | `claude --help` | 文件隔离的落地抓手：per-workflow settings 启用 hook + output style |
| `--session-id <uuid>` 可钉死会话；`--resume <id>` 续 | `claude --help` | 可恢复工作流（阶段不丢） |
| 无 `--no-thinking` flag；`-p/--print` text 模式不渲染思考块，`stream-json` 含 thinking 事件可被渲染器丢弃 | `claude --help` | "不显示思考"的 caveat：原生 TUI 下思考块仍渲染（见 §3） |
| 现有 `codegraph_inject.py` 走 `additionalContext` 协议（UserPromptSubmit 注入可用） | `.claude/hooks/codegraph_inject.py` | `workflow_phase.py` 注入 hook 直接复用此范式 |
| Stop hook 标准接收 `session_id`/`transcript_path`/`cwd`（可读 JSONL transcript） | hook 协议（二进制无法 grep，按公开协议） | `workflow_advance.py` 可读 transcript 检测阶段完成标记；防御式（缺失则降级） |
| 已有 4 个项目 skill + superpowers/karpathy 插件 skill | `.claude/skills/` | 各阶段路由复用现有 skill，不重复造 |
| `settings.local.json` 把 4 个项目 skill 关了（`skillOverrides: off`） | `.claude/settings.local.json` | 工作流 settings 层需注意 merge 优先级（见 §风险） |
| `.codegraph/codegraph.db` 被 gitignored | `.gitignore:46-47` | worktree 内可能无 db，H15 gate 在 execute 阶段的 fallback 行为需确认（见 §风险） |

## 2. 架构总览

```
dl <name>  ──►  scripts/workflow/dl-launch.sh  (repo 内, 版本化)
                                  │  1. resolve repo root (git rev-parse --show-toplevel)
                                  │  2. git worktree add .claude/worktrees/<name> -b wf/<name>
                                  │  3. 写 .claude/workflows/<name>/{state.json, settings.json}
                                  │  4. cd worktree; exec claude \
                                  │       --settings <wf-settings.json> \
                                  │       --session-id <uuid>  (可恢复)
                                  │       --append-system-prompt-file <phase-rules>
                                  ▼
   原生 claude TUI (在隔离 worktree 内)
     ├─ UserPromptSubmit hook  workflow_phase.py    -> 每轮注入「当前阶段 + 规则 + 完成标记格式」
     ├─ output style          workflow.md           -> 渲染阶段横幅 + 压制推理叙述 + 路由 skill
     ├─ Stop hook             workflow_advance.py  -> 检测 ###PHASE_DONE 标记 -> 推进 state + 闸门判定 + 打印阶段切换
     └─ slash commands        /dl next|back|jump|status|gate|done  -> 手动覆盖 + 闸门放行
```

### 三需求 -> 落地映射

| 需求 | 落地组件 | 文件 |
|---|---|---|
| ① ac-ark 参数进工作流 | bashrc 瘦分支 + repo launcher | `~/.bashrc`、`scripts/workflow/dl-launch.sh` |
| ② 显示阶段、不显示思考 | output style + 双 hook + slash | `.claude/output-styles/workflow.md`、`workflow_phase.py`、`workflow_advance.py`、`/dl*` |
| ③ 文件隔离 + 分支隔离 | git worktree + 独立元数据目录 + 钉 session | `dl-launch.sh`、`.claude/workflows/<name>/`、`.claude/worktrees/<name>/` |

## 3. Feature 2 - 显示层（原生 TUI + output style + 双 hook + slash）

四件套在原生交互会话内配合（无外挂 wrapper 进程）：

| 组件 | 文件 | 职责 |
|---|---|---|
| output style | `.claude/output-styles/workflow.md` | 每条响应首行输出 `## PHASE: <phase> [n/5]`；保持简洁；不在可见文本写推理叙述；按阶段路由到现有 skill |
| 注入 hook | `.claude/hooks/workflow_phase.py` (UserPromptSubmit) | 读 state.json -> 注入当前阶段名 + 该阶段允许/禁止动作 + 完成标记格式；**仿 `codegraph_inject.py`**：exit 0 永不阻断 |
| 推进 hook | `.claude/hooks/workflow_advance.py` (Stop) | 读 `transcript_path` JSONL -> 取上一条 assistant 文本 -> 检 `### PHASE_DONE: <phase>` -> 闸门判定 -> 写 state.json -> 打印阶段切换横幅；**防御式**：拿不到 transcript 则降级为提示用户敲 `/dl next` |
| slash 命令 | `.claude/commands/dl*.md` | `/dl next` `/dl back` `/dl jump <p>` `/dl status` `/dl gate`(闸门放行) `/dl done`；命令体跑 bash 读写 state.json |

### 闸门机制（用户选择：自动 + 闸门）

- **闸门位置**：`understand->plan`、`plan->execute` 两处必须用户 `/dl gate` 放行才进。
  - 理由：理解清楚才设计、设计批准才动手——这两步是"认知/决策"关口，不应自动跳过。
- **自动推进**：`execute->review`、`review->evolution` 检到 `### PHASE_DONE` 标记即自动推进。
- **手动覆盖**：用户随时可 `/dl jump <phase>` 强制跳转到任意阶段（含回退）。

### ⚠️ 思考隐藏 caveat（用户已知悉并选择）

用户在方案确认阶段选择了"原生 TUI + output style"方案，知悉以下取舍：

- output style 能渲染阶段横幅、压制模型在**可见文本**里的推理叙述。
- 但**无法隐藏思考块本身**——思考块由 TUI 独立渲染，claude 无 `--no-thinking` flag。
- **架构上把显示层做成可替换**：
  - 默认 = 原生 TUI + output style（用户选择，UX 最佳，流式/工具审批照常）。
  - 可替换为"stream 渲染器"：`claude -p --output-format stream-json` + 渲染脚本丢弃 thinking 事件，严格隐藏思考。
  - 切换只换显示层，phase / hook / 隔离层不变。

## 4. Feature 3 - 文件隔离 + 分支隔离

每个 workflow `<name>`：

| 维度 | 路径 | 说明 |
|---|---|---|
| **代码隔离** | `.claude/worktrees/<name>` (git worktree, 分支 `wf/<name>`) | launcher `cd` 进此目录再起 claude -> 所有 Edit 落在隔离分支，永不碰主 checkout。从当前 HEAD 分叉（可 `--base <ref>` 覆盖）。不用 claude 自带 `-w`（匿名 per-session，无法命名/恢复） |
| **元数据隔离** | `.claude/workflows/<name>/` | `state.json` + `settings.json` + `understand.md`/`plan.md`/`review.md`/`evolution.md`(各阶段产物) |
| **会话隔离** | state.json 内 `session_id` | `--resume` 用钉死的 session 续上，阶段不丢 |

### state.json 结构

```json
{
  "name": "fix-ic-turnover",
  "phase": "execute",
  "index": 3,
  "session_id": "<uuid>",
  "base_ref": "feat/codegraph-auto-inject",
  "branch": "wf/fix-ic-turnover",
  "worktree_path": "<repo>/.claude/worktrees/fix-ic-turnover",
  "gate": "passed",          // "pending" | "passed" | "denied"
  "created_at": "<iso8601>",
  "updated_at": "<iso8601>",
  "history": [
    {"phase": "understand", "entered_at": "...", "exited_at": "...", "via": "gate"},
    {"phase": "plan",        "entered_at": "...", "exited_at": "...", "via": "gate"}
  ]
}
```

- `list` 子命令枚举 `.claude/workflows/*/state.json`。
- worktrees / workflows 目录入 `.gitignore`（运行态不提交）。

## 5. 5 阶段状态机

| 阶段 | 目标 | 允许 | 禁止 | 产物 | 推进 |
|---|---|---|---|---|---|
| understand | 理清**真实问题** | Read/Grep/Glob/codegraph/AskUserQuestion | Edit/Write 源码 | `understand.md`（真实问题重述） | **闸门** |
| plan | 据真实问题设计 | + 起草 design.md（H8）；可选 `--permission-mode plan` | 改源码 | `plan.md` | **闸门** |
| execute | 执行 | 全工具集（守 H15 gate / H9 / 现有 skill） | — | 代码 + commit | 自动 |
| review | 审核是否解决真实问题 | 起评审 subagent（Agent）/ codegraph impact / 测试 | 改实现 | `review.md`（solved/partial/not + 证据） | 自动 |
| evolution | 进化/学习 | 写 memory 事实 / 调 skill / 补 design | — | `evolution.md` + memory 写入 | 终结 |

模型每阶段完成时按注入格式发 `### PHASE_DONE: <phase>`，Stop hook 推进。

## 6. 文件清单

```
~/.bashrc                              改：ac-ark 加 --workflow 瘦分支            [dotfile, 非仓库]
designs/workflow-system-design.md     新：本设计文档 (H8)                          [repo]
.gitignore                            改：加 .claude/workflows/  .claude/worktrees/ [repo]
scripts/workflow/dl-launch.sh         新：launcher（建/续 worktree + state + session）
scripts/workflow/dl-lib.sh            新：state 读写 / worktree / 阶段定义
.claude/hooks/workflow_phase.py       新：UserPromptSubmit 注入（仿 codegraph_inject）
.claude/hooks/workflow_advance.py     新：Stop 推进 + 闸门（防御式读 transcript）
.claude/output-styles/workflow.md     新：output style
.claude/commands/dl.md (+wf-*.md)     新：slash 命令
.claude/workflows/<name>/             运行态：state.json / settings.json / 阶段产物  [gitignored]
.claude/worktrees/<name>/             运行态：隔离工作树                          [gitignored]
```

## 7. 与项目铁律的关系

- **H8**（2+文件先 design.md）：本设计即 design，已先落本文档。
- **H9**（单次 ≤3 文件 AND ≤200 行）：分 5 个小 commit 增量实现（见 §8）。
- **H15**（codegraph 门禁）：workflow 脚本/hook 多为**新建文件**（codegraph gate 白名单跳过新建 + 非 .py）；若改已有 .py 则先 `codegraph impact`。execute 阶段继承现有 `codegraph_gate.py`，H15 在工作流内仍生效。
- **no silent fallback**：两 hook 均 exit 0 不阻断，但异常写 `.claude/.wf_*.log` 留痕（仿 `.cg_inject.log`）。
- **settings 叠加**：`--settings` 在 project settings 上**追加**（codegraph hook 仍在）；需验证 `settings.local.json` 的 `skillOverrides:off` 是否波及工作流（见 §风险）。

## 8. 实施步骤（5 个小 commit）

1. `designs/workflow-system-design.md`（本文档）+ `.gitignore` 条目
2. `scripts/workflow/dl-launch.sh` + `dl-lib.sh` + bashrc shim（隔离 + state + session）
3. `workflow_phase.py`（注入）+ `workflow.md`（output style）
4. `workflow_advance.py`（Stop 推进 + 闸门）+ `/dl*` slash 命令
5. per-workflow `settings.json` 模板 + `resume`/`list` + 冒烟（`ac-ark --workflow demo` 跑一遍 5 阶段）

## 9. 风险与待验证（实现时处理）

| # | 风险 | 缓解 |
|---|---|---|
| 1 | Stop hook 的 `transcript_path` 字段名/格式不确定（二进制无法 grep） | 防御式读取（试多个字段）；缺失则降级为手动 `/dl next`，绝不阻断。**实测**：交互式 transcript 格式为 `{type:assistant,message:{role:assistant,content:[{type:text,text}]}}`，`_last_assistant_text` 能正确解析；`-p` 模式 transcript 可能空（-p 特性），交互式正常 |
| 2 | `--settings` 与 `settings.local.json` 的 merge 优先级 | `--settings` 在 worktree 内实测可加载（Stop 探针触发）；per-wf settings 自含全部 hook，不依赖 project settings 叠加 |
| 3 | worktree 内 `.codegraph/codegraph.db` + `codegraph_gate.py`/`codegraph_audit.py` 缺失（gitignored / 未跟踪） | **已修复**：per-wf settings hook command 用主仓库绝对路径，引用主仓库内存在的文件（见 §10 根因修复） |
| 4 | 思考块在原生 TUI 仍显示 | §3 caveat，已留 stream 渲染器替换路径（用户已知悉） |
| 5 | bashrc dotfile 不在版本控制 | 瘦 shim 只 `exec` repo 内 launcher，重逻辑全在 repo；用户改机器只需保 shim |

## 10. 根因修复记录（2026-07-22, commit f017f91）

**症状**：`ac-ark --workflow demo` 开的会话不显示阶段横幅、不自动推进、注入 hook 没跑（`.wf_phase.log`/`.wf_advance.log` 无新增）。

**根因（systematic-debugging 定位）**：worktree 内的 hook 文件是 `git worktree add` 从 HEAD checkout 的**快照**。hook 脚本用 `PROJECT_ROOT = Path(__file__).resolve().parents[2]`，而 worktree 内 hook 文件路径是 `<repo>/.claude/worktrees/<name>/.claude/hooks/x.py`，`parents[2]` = **worktree 根**（非主仓库根）。state.json 在主仓库 `.claude/workflows/<name>/`，hook 在 worktree 根下找不到 -> `_load_state` 返回 None -> 走 `no_state` 分支不注入、不推进。日志写在 worktree 内（误导主仓库日志无新增）。

**修复**：per-wf settings.json 的 hook command 改用**主仓库绝对路径**（`$WF_REPO_ROOT/.claude/hooks/x.py`），在 `wf_write_settings`（`scripts/workflow/dl-lib.sh`）生成。三重收益：
1. hook 永远是主仓库最新版（改完即生效，无需 commit + 重建 worktree）。
2. `parents[2]` = 主仓库根，正确读到 state.json。
3. 引用主仓库内存在的 `codegraph_gate.py`/`codegraph_audit.py`（worktree 内缺，未跟踪）。

**验证**：注入 hook 真实会话 `injected` 日志、Stop hook 触发、`_last_assistant_text` 解析 transcript 正确、闸门阻断（understand gate=pending 不推进）。

**调试教训**：`printf | claude` 管道模拟交互会出 `Execution error`（管道 EOF 伪问题），真实 TTY 不受影响；勿被管道假象误导，验证用真实会话行为。
