# qodercli 引擎适配层（engine profile）设计

> 日期：2026-09-08 ｜ 状态：已批准（用户裁决=方案 A：单库+引擎适配层）｜ 分支：feat/qodercli-engine-profile
> 前置调研：dl-workflow↔claude 耦合清单（Explore 全仓扫描）+ qodercli 1.1.46 bundle 逆向实证 + 官方文档（docs.qoder.com/cli/custom-models、docs.qoder.cn/cli/model）

## 1. 背景与目标

qodercli（阿里，2025-10-16 发布）实证为 Claude Code 兼容 harness：5 类 hook 事件、hook JSON 契约键（`hookSpecificOutput`/`additionalContext`/`decision`/`reason`）、`-p`/`--output-format stream-json`/`--resume`/`--session-id`/transcript `projects/` 布局/subagents 目录、TaskCreate/TaskUpdate/AskUserQuestion/ExitPlanMode 内置工具、`QODER_*` 一一对应 `CLAUDE_*` 环境变量（bundle 内还留 `CLAUDE_PROJECT_DIR`/`CLAUDE_SESSION_ID` 兼容别名字符串）。

**目标**：dl-workflow 单库双引擎（`claude` | `qodercli`），`dl @qoder <name>` 起 qodercli 后端跑同一套 5 阶段工作流；44 节点状态机、judge 判据、交接包协议、evidence 链保持单真源。

**非目标（YAGNI）**：
- 不吃 qoder 独有能力（Quest Remote / `--remote` worker / Worktree Jobs）——后续轨道
- 不改 dl 自有状态布局：`<项目>/.claude/{workflows,worktrees,evidence}` 是 dl 自有协议（含 `.claude` 路径段围栏裁决），**不动**；只切 harness 面向的注册面（hooks/skills/commands/settings 注册根）

## 2. 方案裁决记录

| 方案 | 结论 |
|---|---|
| A：单库+引擎适配层 | ✅ 采纳。状态机/判据单真源，周级演进红利双引擎共享；qodercli 明牌克隆 claude 接口，适配层=耦合清单的 20% 薄层+行为对账 |
| B：fork 拆两个项目 | ❌。~640k 行 Python 双份维护，fork 漂移几乎必然；浪费 qodercli 的接口对齐 |
| C：PATH shim 参数翻译层 | ❌。variadic flag 翻译/settings 合并挤在 shim=silent fallback 温床；hooks 注册在 settings 文件里 shim 够不着 |

## 3. 已确认差异点（适配层输入）

| 差异 | claude | qodercli |
|---|---|---|
| binary | `claude` | `qodercli`（国内站 `qoderclicn`） |
| 用户配置根 | `~/.claude` | `~/.qoder` / `~/.qoder-cn`（`QODER_CONFIG_DIR` 可覆盖） |
| 项目资源目录 | `.claude` | `.qoder` |
| env 前缀 | `CLAUDE_*` | `QODER_*`（疑有 CLAUDE_* 兼容别名，P0 验） |
| permission-mode 值 | `acceptEdits` | `accept_edits` |
| `--debug-file` | 有 | 无（debug 日志走 `~/.qoder/logs`，P0 验路径） |
| 记忆文件禁用 | `CLAUDE_CODE_DISABLE_CLAUDE_MDS` | 未找到对应（AGENTS.md 开关，P0 验） |
| 模型配置 | env 钉 gateway（ac-k3 模式） | `-m modelID` + BYOK 向导（目录制，首次必须 TUI 配置；能否填任意 base_url 待验） |

## 4. 阶段设计

### P0：行为对账（改代码前置）

前置条件：qodercli 登录（`qodercli login` 或 PAT）。
方法：/tmp 独立探针项目（探针纪律：cwd=/tmp、不带 workflow settings，防状态机误推进），逐项实测：

1. hooks 5 事件（PreToolUse/PostToolUse/UserPromptSubmit/Stop/SessionStart）stdin payload 字段（`session_id`/`transcript_path`/`cwd`/`tool_name`/`tool_input`/`permission_mode`/`prompt`）+ 输出契约（`hookSpecificOutput`/exit 2 阻断/Stop 续轮与 block cap 语义）
2. `CLAUDE_PROJECT_DIR`/`CLAUDE_SESSION_ID` 兼容别名是否真注入（决定 hooks 是否零改动）
3. `-p --output-format stream-json` 事件 schema：`message.usage.{input_tokens,output_tokens,cache_read_input_tokens,cache_creation_input_tokens}`、`result.{num_turns,total_cost_usd}`、末行 result JSON
4. transcript 布局（`~/.qoder/projects/<enc>/<sid>.jsonl` + `subagents/agent-*.jsonl`）+ Agent 工具 `<task-id>`/`agentId` 文本协议
5. AGENTS.md/记忆加载禁用开关（对应 `CLAUDE_CODE_DISABLE_CLAUDE_MDS`，段前缀剥离依赖）
6. `--settings` 合并语义、`--append-system-prompt-file`、`accept_edits` 权限行为、statusLine/outputStyle
7. BYOK：`/model` Custom 向导能否填任意 base_url（kimi gateway 类用法可行性）；`--list-models` 输出
8. `--debug` 日志落盘位置（无 `--debug-file` 的替代）

产出：差异清单回填本文档 §3 → 适配层接口定稿。若某项深耦合行为不成立（如 Stop 续轮语义缺失），升级回架构层重新裁决，不硬修。

### P1：engine profile 抽象

新增 `dl_engine.py`：单一 `EngineProfile`（dataclass）承载全部引擎差异——binary、config_root、项目资源目录、env 前缀、permission-mode 拼写、transcript root、flag 差异表、模型配置策略（claude=env gateway / qoder=`-m modelID`+BYOK）。引擎选择经 `DL_ENGINE` env 贯穿（`claude` 默认，行为与现状逐位一致）。

改造点（耦合清单薄层）：

- **spawn 7 处** cmd 构造统一走 profile：`dl-launch.sh:324/326`、`dl_drive.py`（`_spawn_redteam`/`run_session`/`MergedSession`/`_build_tui_cmd`）、`dl_flow_engine.py` judge、`dl_dashboard/actions.py`
- **settings 写出 3 处**注册根按引擎切：install.sh `merge_settings`、dl-lib.sh `wf_write_settings`、setup_project.py `merge_project_settings`
- **hooks env fallback 链**加 `QODER_*` 前缀（P0 若证实 CLAUDE_* 别名存在则零改动）
- **接线 `DL_CLAUDE` 间接层**：bashrc 注释宣称「dl 不硬编码 claude」但 dl-launch.sh:324/326 为字面 `exec claude`——本次落地为 `DL_ENGINE` 真接线
- judge rubric 文本中 `~/.claude/skills` 注册表形态引用参数化（dl_flow_nodes.py:754/4015/4020/4174）

### P2：安装/启动双引擎

- `install.sh --engine qodercli`：hooks/skills/commands/output-styles 装到 `~/.qoder`，settings 合并逻辑复用、根切换；国内站（`qoderclicn`/`~/.qoder-cn`/`QODER_SITE`）作为 profile 字段
- bashrc `dl @qoder <name>` 接通（`dl @<provider>` 扩展位本就预留）→ `DL_ENGINE=qodercli` 贯穿 launcher/drive/dashboard
- uninstall.sh 对称支持

## 5. 验收与测试

- P0 对账矩阵 = 测试基线，逐项留证据（hook payload 落盘样本、stream-json 原始流样本）
- 适配层 golden test：双引擎 cmd 构造快照对比
- 回归：claude 引擎下现有行为逐位不变（现有测试套件过）
- 最终验收：同一测试工作流双引擎各跑 u 阶段起步，evidence/transcript/成本字段逐条对账

## 6. 风险

| 风险 | 缓解 |
|---|---|
| bundle 有字符串 ≠ 行为一致（deepseek 流式缓存类隐性差异） | P0 实测矩阵先行，差异未定稿前不动 P1 |
| BYOK 目录制不支持任意 base_url，kimi gateway 模式不可行 | P0 第 7 项验证；不行则用内置模型（国内站已内置 Kimi-K2.7-Code/DeepSeek-V4 等） |
| qodercli 版本迭代破坏兼容 | profile 内集中差异表；doctor.py 加引擎能力探测 |
