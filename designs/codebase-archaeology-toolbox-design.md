# 通用代码考古工具箱 + 项目工具注册设计

> 立项依据：`amplitude_annualized` 工作流 `understand:1 子步骤 2`（causal-inference-root-cause）实测用 **43 次工具调用**（Skill×1 + Bash×39 + Read×3）完成代码考古，其中大量 Bash 是 `grep -rn "def xxx"` / `git blame` / `git log -S` / `python -c 读 JSON` 的组合。这些查询可分两类：
> - **通用 70%**（符号定义/调用、字符串搜索、git 历史、文件发现）：codegraph / rg / git 是跨项目通用能力，可包成框架级高层命令。
> - **项目专属 30%**（回测结果 schema、report 数据流等数据契约）：本质不可框架化，需一个「项目自维护脚本 + 框架发现注入」机制。
>
> 目标：把弱模型在 step2 的「拼命令 → 读原始输出 → 自己解析」压成「调高层语义命令 → 直接消费结构化 JSON」，减少弱模型的命令拼写错误、字段解析错误、重复探索。

## 0. 现状与约束（2026-08-14 已核实）

- **S15 围栏白名单已含 `codegraph` 和 `dl-cmd`**（`dl_flow_engine.py` `engagement_fence_notice` 常驻集）——所以「新增 `dl-cmd` 子命令」不需要动围栏，模型本来就能调。
- **node-rules 生成单点**：`scripts/workflow/dl_drive.py:245 ensure_node_rules()` 生成 `node-rules.<nid>.md`，成为 headless 段 `--append-system-prompt-file`——项目工具注入的天然挂点。
- **engine 子命令**：`dl_flow_engine.py main()` 的 `choices=[...]` 列表（`append-trace`/`fetch-prompt`/`render-phase-rules` 等同层），新增 `codebase` 同层即可。
- **per-wf settings allowlist**：`wf_write_settings`（dl-lib.sh）管理前台 auto 权限税白名单——项目工具 command 头需并入，否则前台 TUI 段调用会缴税。
- **Bash 形态铁律**：`_bash_shape_rules()` 已把 `git -C <主仓>` / `env VAR=值` / 顶格 python 等形态钉死——新命令须沿用这些形态，避免触发 CC 安全守卫。

## 1. 方案总览

两个组件共用一条「**发现 → 注入 node-rules → 加白名单**」通道：

```
组件 A（框架通用，跨项目）          组件 B（项目专属，注册发现）
dl codebase query --symbol <sym>   <项目>/.claude/workflow-tools.yaml
dl codebase query --string <pat>     tools: [{name, command, description, arg_hint}]
dl codebase query --history <f>:<l>  → ensure_node_rules 注入「本项目工具」段
        ↓                            → command 头并入 S15 + settings 白名单
   输出结构化 JSON（带 file:line）
```

## 2. 组件 A：`dl codebase query`

实现为 engine 新子命令 `codebase`，`dl-cmd.sh` 加 case 分支路由（`dl-cmd` 已在 S15 白名单，零围栏改动）。

| 子命令 | 底层 | 输出 schema | 压掉的 Bash |
|---|---|---|---|
| `--symbol <sym>` | `codegraph def/callers/impact` | `{definition:{file,line}, callers:[{file,line}], impact:[...]}` | `grep -rn "def xxx"` + 手翻调用点 |
| `--string <pattern> [--type py]` | `rg -n --type` | `{matches:[{file,line,text}]}` | 多个 `grep -rn pattern` |
| `--history <file>:<line>` | `git blame` + `git log -S -p` | `{blame:{commit,author,date}, introduced_by:{...}, commits:[...]}` | `git blame` + `git log --oneline` + `git show` 组合 |

设计要点：
- **只封装「怎么找」，不封装「答案是什么」**——输出证据，因果判断仍归 step 模型。
- **codegraph 新鲜度前置**：`--symbol` 前查 `files.indexed_at`，>72h 提示先 `codegraph sync`（沿用 H15 口径）。
- **输出统一 JSON**（`--json` 默认；可选 `--text` 给人类可读），模型不再解析 grep 原始输出。
- 新增子命令 `list-tools`：打印当前项目注册的工具清单（组件 B 调试用，模型亦可自查）。

## 3. 组件 B：项目工具注册

### 3.1 注册文件

位置 **`<项目>/.claude/workflow-tools.yaml`**（与 `.claude/evidence`、`.claude/workflows` 同级；缺失 = 无工具，旧项目零影响）。

```yaml
# <项目>/.claude/workflow-tools.yaml
tools:
  - name: inspect-backtest-result          # 给模型看的名字（唯一）
    command: scripts/inspect_backtest_result.py --factor {factor}
    description: 读某因子的回测结果元数据（factor_col/return_col/分层年化等）
    arg_hint: --factor <因子名>
  - name: trace-value-flow
    command: scripts/trace_value_flow.py --factor {factor} --metric {metric}
    description: 追踪某指标从数据源到 report 展示层的代码路径
    arg_hint: --factor <因子名> --metric <指标名>
```

字段约束：
- `name`：kebab-case，节点内唯一，注入后是模型可引用的语义名。
- `command`：可执行命令，含 `{factor}` 等占位符（注入时展示，模型自行替换成字面量）。
- `description`：一句话，告诉模型「什么场景用这个工具」。
- `arg_hint`：可选，参数形态提示。

### 3.2 三个动作（框架做，项目无感）

1. **发现**：`ensure_node_rules()` 时读 `<项目>/.claude/workflow-tools.yaml`；文件缺失/损坏 → 零工具（`list-tools` 报损坏原因，宁纵勿枉不阻断）。
2. **注入**：工具清单渲染进 `node-rules.<nid>.md` 的「## 本项目工具」段（在「本节点子步骤清单」之后），模型启动即见。
3. **加白名单**：每个工具 command 的头（首 token）并入：
   - S15 围栏 Bash 只读白名单（`engagement_fence_notice` 常驻集）；
   - per-wf settings allowlist（防前台 auto 权限税）。

### 3.3 安全边界

- 工具 command 头只加**只读发现类**（`find/ls/grep/cat/head/git log`/python 脚本）；破坏性命令（`rm/dd/写文件`）**不进白名单**，沿用「弱模型幻觉刹车」原则（症状 R 记录：正向名单可收敛，deny 反向名单是打地鼠）。
- 项目脚本本身的安全由项目自担（脚本在项目仓、走 code review）。

## 4. 集成点与围栏（逐层）

| 层 | 改动 |
|---|---|
| engine 子命令 | 新增 `codebase`（组件 A）+ `list-tools`（组件 B 发现入口） |
| `dl-cmd.sh` | case 分支加 `codebase` 路由（`dl-cmd codebase query ...`） |
| node-rules 生成 | `ensure_node_rules()` 追加「本项目工具」段（组件 B） |
| S15 白名单 | 项目工具 command 头动态并入（组件 B）；`dl codebase` 已在白名单（组件 A 零改） |
| per-wf settings | 项目工具 command 头并入 allowlist（组件 B） |

## 5. 测试

1. **组件 A 单测**：`codebase --symbol/--string/--history` 三子命令对真实小仓返回正确 file:line JSON；codegraph 过期提示触发；空结果/异常输出结构化错误而非裸栈。
2. **组件 B 单测**：`workflow-tools.yaml` 缺失/损坏/空 tools 三态 → 零工具不阻断；注入 node-rules 段内容正确；command 头并入 S15 + settings 白名单；`list-tools` 打印正确。
3. **围栏放行测**：注册工具在零 trace 窗口内被 S15 放行、破坏性命令仍被 deny。
4. **试点 A/B**：factor_ic_analyzer 写 1-2 个脚本（`inspect_backtest_result` / `trace_value_flow`），跑一轮 amplitude 工作流，对比 43 次工具调用能压到多少。

## 6. 落地顺序

1. 组件 A 先落（纯增量、`dl-cmd` 已在白名单、风险最低）。
2. 组件 B 再落（注册 schema + 发现/注入/白名单，需新测试）。
3. factor_ic_analyzer 试点脚本 + 跑轮验证。

## 7. 回滚面

- 组件 A：`codebase` 子命令是纯增量，不删即可；无 schema 变更。
- 组件 B：`workflow-tools.yaml` 缺失 = 无工具，旧项目/旧工作流零影响；白名单是正向合并，删除文件即回滚。

## 8. 不做的事

- **不做 MCP server**：弱模型 MCP 工具 schema 更重、冷启动更贵、需维护进程生命周期；node-rules 注入 + Bash 命令已够。
- **不做跨项目数据契约抽象**：项目专属 30% 不框架化，只给注册机制。
- **不做工具结果的 LLM 摘要**：`codebase` 输出原始证据 JSON，摘要/因果归 step 模型（防二次 LLM 成本 + 幻觉）。
- **不做破坏性命令白名单**：只放行只读发现类，写/删命令保留弹窗刹车。
