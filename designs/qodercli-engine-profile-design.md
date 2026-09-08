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

## 3. P0 行为对账结果（2026-09-08 实测，qodercli 1.1.46，BYOK=DeepSeek-V4-Flash 经向导注册）

探针：/tmp/qoder-probe（cwd=/tmp，不带 workflow settings）。以下全部为**实测结论**，非 bundle 字符串推断。

### 3a. 零改动兼容（实测通过）

- **hooks 5 事件 payload 全字段一致**：`session_id`/`transcript_path`/`cwd`/`hook_event_name`/`permission_mode`/`tool_name`/`tool_input`/`tool_response`(Post)/`prompt`(UPS)/`source`(SessionStart)/`stop_hook_active`/`last_assistant_message`(Stop)
- `permission_mode` payload 值 = **`acceptEdits`**（camelCase，仅 CLI flag 收下划线 `accept_edits`）
- **PreToolUse deny 契约**：`hookSpecificOutput.permissionDecision=deny` 阻断工具，reason 以 tool_result error 喂模型
- **Stop 续轮语义**：`{"decision":"block","reason":"..."}` 强制续轮，二次触发 `stop_hook_active=true`——workflow_advance 承重墙成立
- **注入契约**：UPS/SessionStart stdout 文本以 `attachment` 事件进 transcript（同 claude 的 hook_additional_context 形态）
- **stream-json schema**：`system/init`（tools/skills/slash_commands/model/cwd）、`assistant.message.usage` 字段结构、`result.{num_turns,total_cost_usd}`、hook 生命周期事件（hook_started/progress/response）
- **`--input-format stream-json` NDJSON 多轮注入**（MergedSession 段内续步依赖）✅
- **transcript 布局**：`~/.qoder/projects/<enc>/<sid>.jsonl`，编码规则相同；**subagents** `<sid>/subagents/agent-<id>.jsonl`（+`.meta.json`），dl 的 glob 兼容
- **Agent 工具**：同步 + `run_in_background` 均可用；返回文本含 "Async agent launched successfully"+"agentId:"，完成自动通知
- **env**：`QODER_PROJECT_DIR`/`QODER_SESSION_ID` 注入，且 **`CLAUDE_PROJECT_DIR` 兼容别名真实注入**（dl hooks 读取链零改动概率高）
- `--settings`/`--append-system-prompt-file`/`--resume`（SessionStart source=resume）/`--session-id`/`--list-models`/`--disallowed-tools`
- AGENTS.md 默认加载；`--permission-mode accept_edits` 生效

### 3b. 差异清单（P1 适配层输入，实测确认）

| # | 差异 | 影响面 | 适配 |
|---|---|---|---|
| D1 | 无 `--verbose` flag（exit 1） | dl_drive 段命令 | cmd 构造按引擎裁剪 |
| D2 | 无 `--debug-file`；debug 日志自动落 `~/.qoder/logs/sessions/<proj>/<sid>/segments/*.jsonl`（结构化 jsonl） | dl-launch `--debug-file` | qoder 引擎省 flag，日志路径进 profile |
| D3 | `--disallowedTools` 驼峰不支持，仅 `--disallowed-tools` | dl_drive AskUserQuestion 封禁 | flag 名按引擎 + qoder 本无此工具可省略 |
| D4 | **无 AskUserQuestion 工具**（tools 列表确认；有 Monitor/Workflow/Goal 替代系） | dl_flow_nodes 交互步 | 交互步在 qoder 引擎需走 alternate 通道（TBD：TUI 原生提问/降级文本问答） |
| D5 | **Stop hook：`reason` 是唯一续轮指令通道；`hookSpecificOutput.additionalContext` 被忽略**（实测：reason 文本注入为 user msg，additionalContext 未达模型） | workflow_advance.py:296-310 | 续轮指令双写 reason（claude 同样认 reason，可统一） |
| D6 | **BYOK 模型 usage 全零**（stream+transcript 均无 token 数），`total_cost_usd`=0 | 成本对账子系统 | qoder+BYOK 引擎关闭成本对账/标记 N/A；内置模型待验（账号无额度未测） |
| D7 | 后台 `agentId` 格式 = `a<type>-<hex16>`（如 `ageneral-purpose-104997bfb6f1884a`） | workflow_step_fence/advance 的 regex `agentId:\s*([0-9a-f]{16,17})` 匹配不上 | regex 放宽为 `agentId:\s*(\S+)` 再取尾段 |
| D8 | **BYOK 调用经 Qoder 云端代理**（server 建 custom pool，BAD_REQUEST 100400 实证）；且必须 TUI 向导注册一次（服务端校验），手写 `modelConfigs.customModels` 仅过本地解析（模型出现在列表但调用被拒） | 隐私/路由语义；安装流程 | install 文档化「首次需 TUI 向导注册 BYOK」；settings schema 已逆出（provider/apiKey/model/baseURL/format，必填前三项） |
| D9 | AGENTS.md 排除 = `agentsMdExcludes` setting（无 `CLAUDE_CODE_DISABLE_CLAUDE_MDS` 等价 env）；auto-memory 默认关（`QODER_MEMORY=1` opt-in） | 段前缀剥离（dl_flow_nodes.py:181-184） | qoder 引擎用 agentsMdExcludes 配 settings |
| D10 | **Trusted Workspace 门**：不受信目录不加载项目级 settings/hooks/MCP/AGENTS.md（`--settings` 外置文件不受限） | 自动化跑新项目 | install/setup 流程需预置信任或文档化首次 TUI 确认 |
| D11 | 站点：`QODER_SITE=GLOBAL`（本账号=国际站 qoder.com，内置仅 Qwen3.8/3.7 系）；国内站 qoderclicn 独立配置根 `~/.qoder-cn` | profile | site 作为 profile 字段 |
| D12 | QODER_HOOK_VERSION=1.1.47（hook 协议版本独立于 CLI 版本号） | doctor 能力探测 | 版本探测读 hook 协议版本 |

### 3c. 未验项（降级为后续）

- 内置 Qwen 模型的 usage/cost 字段（账号无额度，需开通后补测）
- AskUserQuestion 在 TUI 模式的形态（无 TUI 自动化手段，P2 人工验）
- SessionStart `source=clear`（/clear 语义，TUI 项）、PreCompact 事件
- BYOK 向导的 provider 目录全貌（用户向导注册 DeepSeek 成功；是否有 generic openai-compatible 任意 base_url 选项未逐项确认——settings 手写路径本地可解析，云端是否放行任意 base_url 待验）

## 4. 阶段设计

### P0：行为对账（~~改代码前置~~ ✅ 已完成 2026-09-08，结果见 §3）

~~前置条件：qodercli 登录~~ 已完成（PAT 登录 + DeepSeek BYOK 向导注册）。原 8 项验证矩阵全部执行，结论落 §3a/3b/3c；另补测 `--input-format stream-json` NDJSON 多轮注入（MergedSession 依赖）通过。**无架构级阻断项——4 条深耦合链全部实测成立，方案 A 维持。**

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

改造点（耦合清单薄层 + §3b 差异映射）：

- **spawn 7 处** cmd 构造统一走 profile：`dl-launch.sh:324/326`、`dl_drive.py`（`_spawn_redteam`/`run_session`/`MergedSession`/`_build_tui_cmd`）、`dl_flow_engine.py` judge、`dl_dashboard/actions.py`——裁剪 `--verbose`（D1）/`--debug-file`（D2）/`--disallowedTools` 驼峰（D3）
- **settings 写出 3 处**注册根按引擎切：install.sh `merge_settings`、dl-lib.sh `wf_write_settings`、setup_project.py `merge_project_settings`
- **hooks env fallback 链**加 `QODER_*` 前缀（P0 已证实 `CLAUDE_PROJECT_DIR` 别名真实注入，多数 hooks 零改动；前缀链作兜底）
- **workflow_advance Stop 续轮输出双写 `reason`**（D5——qoder 只认 reason；claude 同认，可统一不改语义）
- **fence/advance 的 agentId regex 放宽**（D7：`agentId:\s*(\S+)` 取尾段）
- **BYOK 引擎成本对账降级**（D6：usage/cost 全零，标记 N/A 而非报错）
- **段前缀剥离**（dl_flow_nodes.py:181-184）：qoder 引擎用 `agentsMdExcludes` setting 替代 `CLAUDE_CODE_DISABLE_CLAUDE_MDS`（D9）
- **接线 `DL_CLAUDE` 间接层**：bashrc 注释宣称「dl 不硬编码 claude」但 dl-launch.sh:324/326 为字面 `exec claude`——本次落地为 `DL_ENGINE` 真接线
- judge rubric 文本中 `~/.claude/skills` 注册表形态引用参数化（dl_flow_nodes.py:754/4015/4020/4174）
- **AskUserQuestion 交互步**（D4）：qoder 引擎的交互通道单独设计（P1 内裁决：TUI 原生 vs 降级文本问答），不动 claude 路径

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
