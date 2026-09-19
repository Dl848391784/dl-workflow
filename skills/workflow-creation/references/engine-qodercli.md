# qodercli 引擎作战手册（dl @qoder / DL_ENGINE / BYOK / wedge 诊断）

> workflow-creation skill 按需参考。dl-workflow 双引擎（claude 默认 | qodercli）的引擎差异、适配点、qoder 专属症状与诊断。真源：`designs/qodercli-engine-profile-design.md`（§3 P0 实测差异、§5 E2E 验收）+ `dl_engine.py`（差异单源）。2026-09-09 全轨道收口（main 3bc14a3）。

## 1. 架构一句话

`DL_ENGINE` env（`dl @qoder` 入口子 shell 置位）→ `dl_engine.get_engine()` 返回 EngineProfile（binary/配置根/权限拼写/flag 差异/transcript 根/计量语义）→ 全部 spawn（drive 4 处/judge/dashboard/launcher）、settings 写出 3 处、hooks 契约面（env 链/Stop 输出/agentId regex）按 profile 或 DL_ENGINE 分路。**claude 未设 DL_ENGINE = 逐位不变**（golden 测试锁死）。

## 1.5 引擎选择三层（per-instance-engine，2026-09-10 落地，designs/per-instance-engine-design.md）

**优先级**：显式 `DL_ENGINE` env（bashrc @qoder/调用方）> 实例 `state.json.engine`（sticky）> claude 默认。
- **建实例**：dashboard 创建表单卡片选择（`/api/engines` 探测渲染，禁下拉，单引擎机器单卡；qoder 选中时 provider 下拉禁用）或 `dl @qoder`——落 `state.engine`。
- **drive**（单实例进程）：main 启动读 state.engine 归一写回 env（`_apply_instance_engine`）——段/judge/hooks 全链跟随，**与拉起方的 server/shell env 解耦**（旧实例无字段=不动 env=现状，已知局限见设计 §6）。
- **dashboard inject**（多实例进程）：`get_engine(override)` 直传实例引擎，**禁 env 竞态**。
- **resume sticky**：无 env `dl <name> --resume` 从 state 读回（state.json 损坏=fail loud 报错，旧实例无字段=claude 兜底）；`dl-launch` 引擎校验在 wf_state_init 之前（garbage 不落盘）。
- **排障先对三处**：state.json 的 engine 值 → 段进程 argv 首元素（qodercli|claude）→ dashboard server env 的 DL_ENGINE（v1 遗留语义，仅影响「未归一」路径）。

## 2. 差异速查（P0 实测 D1-D12）与适配点映射

| # | qodercli 实测事实 | 适配落点 |
|---|---|---|
| D1 | 无 `--verbose`（exit 1） | `EngineProfile.verbose_args()` |
| D2 | 无 `--debug-file`；日志自动落 `~/.qoder/logs/sessions/<proj>/<sid>/segments/*.jsonl`（结构化，比 claude 更优——**排障直接读这里**） | `debug_args()` / dl-launch DEBUG_ARGS |
| D3 | 无驼峰 `--disallowedTools`，仅 `--disallowed-tools` | `disallow_ask_args()` |
| D4 | 无 AskUserQuestion 工具（Monitor/Workflow/Goal 替代系）——交互走 prep→need_user.json→注入通道，不受影响 | `disallow_ask_args()` 返回空（工具不存在=结构堵死） |
| D5 | **Stop hook 只认 `decision:block`+`reason`（注入为 user msg）；`hookSpecificOutput.additionalContext` 被忽略** | `workflow_advance._stop_continue` 按 DL_ENGINE 分路 |
| D6 | BYOK 模型 usage/cost 全零（stream+transcript 均无）——segment_stats 显 $0.000 是**预期**不是故障 | profile `usage_metered=False` |
| D7 | 后台 agentId 格式 `a<type>-<hex16>` | `_AGENT_LAUNCH/DONE_ID_RE` 加可选前缀（advance 单源+fence 同步） |
| D8 | **BYOK 调用经 Qoder 云端代理**；必须 TUI `/model` Custom 向导注册一次（手写 settings 只过本地解析、云端拒建 pool）；凭据落 `~/.qoder/.auth`，settings 只留 `model.name="provider/model"` | install --engine 提示文案；doctor 判据=model.name 含 `/` |
| D9 | AGENTS.md 排除=`agentsMdExcludes` setting（glob 实测生效）；auto-memory 默认关（`QODER_MEMORY=1` opt-in） | v1 段前缀剥离未做（留后续轨道） |
| D10 | Trusted Workspace 门：不受信目录不加载项目级 settings/hooks/AGENTS.md（`--settings` 外置文件不受限） | 新项目首跑需 TUI 确认信任 |
| D11 | `QODER_SITE=GLOBAL`/国内站 qoderclicn 独立配置根 `~/.qoder-cn` | profile 字段预留 |
| D12 | hook 协议版本独立于 CLI 版本（QODER_HOOK_VERSION） | doctor 探测口径 |

**零改动兼容面**（P0 全绿）：hooks 5 事件 payload 全字段、`permission_mode` payload 值=acceptEdits（仅 CLI 拼写不同）、PreToolUse deny、Stop 续轮+stop_hook_active、UPS/SessionStart attachment 注入、stream-json schema、`--input-format stream-json` NDJSON 多轮、transcript 目录编码规则、subagents 布局、Agent 同步+后台+完成通知、`CLAUDE_PROJECT_DIR` 兼容别名、permissions allowlist（policy source 实证）。

## 3. D13：qodercli 长 merged 会话 wedge（核心诊断模式）

**识别特征**（E2E 冒烟 2 连发，特征完全一致）：
1. drive-stream.jsonl 纹丝不动 >5 min（段无新事件）
2. qoder 段日志（`~/.qoder/logs/sessions/.../segments/*.jsonl`）尾部 = `model.response.completed`(stop_reason=tool_use) + `hook.finished`(PreToolUse, success, exit 0)——**之后零事件**（无 permission.resolved / 无 tool.shell.started）
3. 进程在但 S 睡眠、无子进程、CPU 不涨

**鉴别**（三变量最小复现均阴性，勿误诊）：
- 非白名单外命令 → 正常 auto-deny 且模型自适应（健康路径，**不是 wedge**）
- 非多行命令 → 多行复合命令同样 auto-deny 正常
- 非 settings 内容 → 真 drive-tui settings 复现也不触发
→ 判定 qodercli 内部稳定性问题（长 SDK 会话随机），**不是适配层缺陷**。

**处置**：`kill -TERM <qodercli pid>`——driver 检「合并段进程异常退出」自动回主循环重派（state 在磁盘），韧性已实证。**注意 kill 的是 qodercli 进程不是外层 wrapper**（误杀 wrapper 会假报任务失败，实际 driver 存活）。
**待办**：qoder 引擎段无活动 watchdog（超时自动 SIGTERM=自动重派，把人工处置机械化）——未做，目前靠人工。

## 4. D14 类漏点与 EngineProfile 加字段教训

- **漏点模式**：引擎适配最易漏的是「路径字面量」——`dl_flow_trace.py` 的 `~/.claude/projects` transcript 根（D14：qoder 段 transcript 落 `~/.qoder/projects`，agent 报告召回会零命中；E2E 冒烟才暴露，单测全绿没拦住）。改引擎相关代码先 `grep -rn "\.claude" <涉及文件>` 排雷。
- **加 profile 字段必须用方法**（14 连跪实证）：字段值在 `dl_engine` import 期冻结（`Path.home()`/`QODER_CONFIG_DIR` 彼时求值）——既有测试 monkeypatch `Path.home` 注入 fixture 会静默全挂。`transcript_projects_root()` 做成方法调用期解析即解。同族：BYOK 测试要 `sys.modules.pop("dl_engine")` 强制重导入才能覆盖 QODER_CONFIG_DIR 分支（finally 恢复旧模块，防顺序污染）。

## 5. qoder 专属症状速查

| 症状 | 真相 | 处置 |
|---|---|---|
| `✗ DL_ENGINE=xxx 未知引擎` exit 2 | no silent fallback 设计内（拼错/未支持引擎） | 改 `claude`/`qodercli` |
| qoder 下段会话权限全被问/不生效 | settings `permissions.defaultMode` 被 qoder 忽略（P0 实测两拼写 init=default）——**权限唯 CLI flag 承重**（dl-launch PERM_ARGS 已钉，设计内兼容） | 无需修；别试图用 settings 补 |
| doctor 报 BYOK 未注册（旧版判据） | **判据已废**（2026-09-09 用户裁决：BYOK 是用户行为非检查项）——新判据=`--list-models` 认证与模型可用性，BYOK/内置不问 | 升级到 ≥0.10.3 |
| 新项目目录 hook/AGENTS.md 不加载 | Trusted Workspace 门（D10） | TUI 进一次该目录确认信任 |
| segment_stats 全 $0.000/0 token | D6 BYOK 未计量，预期 | 审计成本时该引擎标记 N/A，不做对账 |
| `dl @qoder` 起的却是 claude | bashrc 段是旧 DL_CLAUDE 约（install.sh 升级路径 2026-09-09 已修，重跑 install.sh 自愈） | `bash ~/.dl-workflow/install.sh` |
| qoder TUI 在非 tty 秒退无痕迹 | TUI 必须有终端（claude 同）——headless 场景用 `--headless` driver 或 -p 注入 | 非引擎问题，无人值守用 wf_ctl 模式（runtime-audit #25） |

## 6. BYOK 机制要点（装/排障必读）

- 注册：`qodercli` TUI → `/model` → Custom → Add custom model（服务端校验建 pool）；之后 headless `-m <provider/modelID>` 直接用
- dl 侧模型选择：per-wf settings `model` 键（`DL_QODER_MODEL` env 注入，dl-lib.sh 写入）> 向导选中的账号默认
- **路由语义**：BYOK 也过 Qoder 云端（prompt/代码经其服务器转发第三方 provider）——与 claude 系 env 直连 gateway（ac-* 模式）路径完全不同，涉及代码出域评估时这是关键事实
- settings 手写 `modelConfigs.customModels`（schema 已逆出：provider/apiKey/model 必填 + baseURL/format/key/displayName/maxInputTokens）本地可解析进列表，但**云端未注册调用必拒**（BAD_REQUEST 100400 Failed to generate custom pool）——只能当探针不能当配置通道

## 7. 验证与证据指针

- E2E 冒烟（qoder+DeepSeek BYOK，fermate 全程 gate=done）：现场 `/tmp/dl-qoder-smoke`（state/evidence/drive-stream 全留）；方法与口径 → `runtime-audit.md` #28
- 验收记录：`designs/qodercli-engine-profile-design.md` §5；实施计划：`designs/qodercli-engine-profile-plan.md`（11 任务 D 编号映射）
- SDD 过程档案（任务报告/审查包/ledger）：`~/.dl-workflow/.superpowers/sdd-qodercli-engine-profile/`

## 8. 引擎能力接入方法论：探针实证先于假设——env 约定不跨 harness（2026-09-18）

给引擎加任何「能力假设」前（thinking 控制/输出格式/权限拼写），**先本机最小探针实证**：`--help` 看原生 flag + `cwd=/tmp` 裸跑一次性 `-p`（探针纪律：不带 workflow settings，防 Stop hook 推进状态机）。实例：假设 MAX_THINKING_TOKENS 在 qoder 生效 → 探针发现 qodercli 1.1.47 原生 `--thinking disabled|enabled|auto|adaptive` / `--thinking-budget N` / `--reasoning-effort`（显式 flag，优于 env）；**env 约定不跨 harness**——claude 的 MAX_* 系列 qodercli 不读，v2.44 judge 裁剪在 qoder 路径因此空转（实修 541e250：EngineProfile.thinking_off() 按引擎分源）。结论一律入 dl_engine.py profile 单源，禁散在调用点。
