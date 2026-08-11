# v4 前台模式 statusLine 进度栏 设计

> 日期：2026-08-11 · 分支 feat/v4-statusline-progress · 状态：设计待裁决
> 上游：designs/front-tui-hybrid-design.md（v4 架构）· 触发 = v4 默认翻转（af5af11）当天第一条 dogfood 发现

## 1. 背景与触发（dogfood 实证）

v4 默认翻转当天，`interaction_turnover__ret3d_abs_annualized` live 运行（front 模式），段工人后台连续跑 understand:1 子2→子3→子4 共 30+ 分钟，前台 TUI 全程只显示派发时刻的一句静态文案。用户三连追问（原话，dogfood 证据）：

1. 「在后台运行真的一点信息都显示不出来呀，而且执行了十几分钟，也不知道执行是否卡死了」
2. 「既然每一个 step 都是一个独立的进程，那么为啥每一个进程执行完不给前台 TUI 反馈呢？这样前台 TUI 不就可以输出哪个步骤已经执行完哪个步骤正在执行中么」
3. 「能不能前台 TUI 起定时任务查询进度的 json，然后显示出来，这样不就有进度了么」

### 诊断结论（机制按设计运转，非 bug）

- 段 = **单个**后台 Bash 任务（`dl_drive.py --segment`），段内步推进（每步一个 `claude -p` 短会话，state.json `segment_sessions` 台账铁证）只对 driver 可见；TUI 唯一唤醒通道 = 后台任务整体退出的原生通知（front-tui-hybrid-design §2.4 硬约束表：**外部进程无 IPC 推消息进运行中 TUI**）。
- 瑕疵①（小文案 bug）：phase 注入派发文案「当前位置（understand:1 子步骤 2）」（hooks/workflow_phase.py:495-497）是**派发时刻 state 快照**，段内推进后「当前」二字变误导。
- 瑕疵②（刻意留白）：段在跑注入分支（hooks/workflow_phase.py:488-493）只写「后台段在跑：无需动作」，刻意不带实时位置。
- `front_segment.json` 只存**起跑位置**（dl_drive.py:1351 设计内注释），段内推进不更新——用户能看到的唯一文件也是滞后的。

### 卡死判读口径（本设计活性判定的依据）

drive-stream.jsonl 的 mtime 被 thinking 心跳持续刷新；**mtime >3-5 分钟不动才疑似卡死**。本轮实证：段跑 30+ 分钟 mtime 全程新鲜，非卡死。

## 2. 问题定义

front 模式下，段工人在跑期间（可达数十分钟），**用户无任何零成本通道得知**：当前跑到哪一步 / 是否在推进 / 是否疑似卡死。诉求是**可见性**，不是推进——段内步推进全自动，不需要前台做任何事。

## 3. 方案空间与裁决

| 方案 | 机制 | 裁决 |
|---|---|---|
| A. 每步一个段、每步退出唤醒 TUI | 原生后台任务退出通知逐步触发 | ❌ 每次唤醒 = 一次完整 TUI 模型轮次 = 全量上下文 cache read（v3.0 拆短会话省下的税又吐回）+ 弱模型每步重派发「逐字照抄」可靠性税（v2.x「15 注入 0 上屏」教训） |
| B. 前台模型起 cron/wakeup 定时自查 | 会话空闲时周期 enqueue prompt | ❌ 同上：每跳一次 = 一次全量模型轮次，用模型轮次做心跳是拿金饭碗要饭 |
| C. **statusLine 进度栏**（用户提议的正解形态） | harness 原生：settings.json 配 shell 命令，周期执行，stdout 渲染 TUI 底部 | ✅ **零 token、零唤醒、不过模型、空闲也刷新**；拉模型（harness 主动执行命令读文件）天然绕开「无 IPC 推 TUI」约束 |

**用户裁决（2026-08-11）：按方案 C 实现。**

## 4. statusLine 机制事实（已核实，本机 claude 2.1.227 二进制 schema + changelog）

- 配置：`settings.json` → `statusLine: {type: "command", command: "<shell>", padding?, refreshInterval?, hideVimModeIndicator?}`。**无 timeout 字段**（社区资料有说是误传；内部默认 600s 上限）。
- **`refreshInterval: N`（秒，min 1）= 空闲也每 N 秒执行**（changelog v2.1.97：「re-run the status line command every N seconds in addition to event-driven updates」）——这是本方案成立的关键事实：TUI 挂机期间进度栏照样刷新。未配置时纯事件驱动（消息/权限切换等），空闲不刷。
- 事件驱动路径 300ms debounce；每次新刷新 **abort 上一次未完成的命令**——脚本必须快（目标 <100ms），慢命令永远显示不出。
- stdin 收 JSON（session_id/cwd/model/context_window/cost 等）——**本设计不依赖 stdin**，路径烧进命令行更稳。
- 输出：stdout trim 后按行渲染；**支持多行、支持 ANSI**；`COLUMNS`/`LINES` 环境变量可用于适配终端宽度。
- 旧版 CLI（<2.1.97）无 refreshInterval = 静默降级为事件驱动刷新（无害）。

## 5. 设计

### 5.1 新脚本 `scripts/workflow/dl_statusline.py`

纯只读、零依赖（stdlib）。调用形态（参数烧进 per-wf settings 命令行，不吃 stdin）：

```
python3 ~/.dl-workflow/scripts/workflow/dl_statusline.py --project <主仓根> --name <wf名>
```

数据源（全部小文件，**禁读 drive-stream.jsonl 内容**——26MB 级，只 stat mtime）：

| 源 | 用途 |
|---|---|
| `.claude/workflows/<name>/state.json` | 实时位置（node / sub_step_index / held_for_gate / gate） |
| `front_segment.json` | 段活性锁：pid + started_at（段已跑时长）+ 起跑位置 |
| `drive-stream.jsonl` 的 **mtime** | 活性心跳：>180s 未写 = 「⚠ 疑似卡住」（§1 判读口径取保守下界） |
| `segment_summary.json` | 段间态：上一段结局码（10 交互步/11 门栏/12 断点/13 NEED_USER/0 完成） |
| `/proc/<pid>` | 段 pid 存活性校验——front_segment.json 残留（工人 crash 未清锁）时不误判「段在跑」 |

渲染（单行，ANSI 上色，按 $COLUMNS 截断），状态机：

| 状态 | 行示例 |
|---|---|
| 段在跑·活跃 | `⏳ 理解问题和背景 子4/6 · 段工人 12min · 活跃` |
| 段在跑·疑似卡住 | `⏳ understand:1 子4/6 · 段工人 31min · ⚠ 4min 无输出` |
| 段外·非交互待派发 | `▸ understand:1 子5/6 · 待派发段` |
| 门栏扣留 | `⛔ plan:4 门栏 · 待 /dl gate` |
| 交互步（TUI 段） | `✋ understand:1 子1/6 · 本会话交互步` |
| 段刚结束有待读结局 | `📋 段结局 code 10 · Read segment_summary.json` |

节点标签渲染复用 engine 单源（PHASE_LABELS / subphase_labels / get_node），禁止脚本侧另持副本。

### 5.2 per-wf settings 模板接入（dl_flow_engine.py）

`wf_write_settings` 模板加：

```json
"statusLine": {
  "type": "command",
  "command": "python3 ~/.dl-workflow/scripts/workflow/dl_statusline.py --project <主仓根> --name <name>",
  "refreshInterval": 10
}
```

- **SETTINGS_TEMPLATE_VERSION v8→v9**（v2.35 纪律：改模板实质内容必 bump 常量 + 注释链补 v9 条目；存量 settings 由 --resume 补写自愈）。
- 路径引用沿用 hooks 同模式：settings 直接引用 `~/.dl-workflow/` 源（shell 展开 ~），**install.sh 不涉及、无副本同步面**。
- `settings.drive.json` 派生（headless `claude -p` 无 TUI）：statusLine 剔除（与 outputStyle/SessionStart 同批处理），保 drive 载荷干净。
- refreshInterval=10s：活性判读粒度足够（卡死阈值 180s），每 10s fork 一次 <100ms 的 python 开销可忽略。

### 5.3 文案 bug 顺手修（瑕疵①）

workflow_phase.py:495-497 派发文案「当前位置」→「起跑位置（段会连续推进多步，段内进度看底部状态栏）」。一处措辞改动，随本分支一并落地。

## 6. 影响面与兼容

- **front 模式**：主受益面，段在跑/段外/门栏全态覆盖。
- **v3 headless**：settings.drive.json 剔除 statusLine，零影响（rich Live 进度区已是其答案）。
- **TUI 交互段**：statusLine 同样在屏（per-wf settings.json 是全量 settings）——交互步显示「✋ 本会话交互步」，补位置感，无副作用。
- **多工作流并发**：per-wf settings 各烧各的 --name/--project，天然隔离。
- **H15/design gate**：本设计即 design.md；改 dl_flow_engine.py 前需 codegraph 查询留痕（v2.120：dl-workflow 仓拦截）。
- **在飞工作流**：dl_drive.py 不改（statusLine 是纯消费侧），运行中段不受影响；settings 自愈只对 --resume/新 wf 生效，在飞会话的 settings 不动 = 在飞会话无进度栏（下次 launch 自然获得）。**刻意不热更在飞会话**（改在飞 per-wf settings 需重启会话才加载，收益不抵打扰）。

## 7. 测试与验证

- **单测**（tests/ 新增 TestDlStatusline）：渲染函数纯函数化（注入 state dict / segment 文件 / mtime / pid 存活 mock），六态行全过；卡死阈值边界（179s/181s）；pid 残留锁误判防护；settings 模板含 statusLine + 版本戳 v9 断言（模板回归测试同 v8 既有模式）。
- **pty 冒烟**（troubleshooting #15 方法，三坑已沉淀）：起 TUI 会话带 per-wf settings → 底部出现进度行 → 模拟段推进 → 行内容变化；**重点实证「空闲刷新」**（无输入 30s 行内容随 refreshInterval 更新——二进制 schema 已证，端到端再验一次）。
- **lint**：ruff + mypy 全绿。
- **H9 预算**：dl_statusline.py（~120 行新文件）+ engine 模板（~10 行）+ phase 文案（~3 行）+ 测试（~100 行新文件）——拆两 commit：①脚本+测试 ②模板+文案+版本戳。

## 8. 显式不做

- 不做多行富进度（TaskList 式全清单）——v3.3.1 已裁决「内容同源样式两制」，进度栏定位是单行心跳，全清单渲染归 /dl status。
- 不做段内逐事件流（tail stream 上屏）——那是 --verbose 的活。
- 不动 driver 主循环 / hooks 编排逻辑（除瑕疵①一处文案）。
- 不热更在飞会话 settings（§6）。
