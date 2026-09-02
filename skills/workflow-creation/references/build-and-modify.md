# 建工作流 / 改工作流

> workflow-creation skill 按需参考（自 SKILL.md §1.1–1.3 整体迁出，节号原样保留以兼容「§3.5 #9」式交叉引用）。
> 只在 SKILL.md 路由表命中时阅读。


### 1.1 新建一个工作流（用户侧）
两种入口（都拦 `--dl` 参数转交 launcher）：
```bash
dl <name>                 # 独立 dl 命令
ac-ark --dl <name>        # provider 函数（需在 ac-ark 里加 --dl 拦截，见 README）
# 通用参数
dl <name> --resume        # 续接
dl <name> --phase <p>     # 跳阶段
dl <name> --base <ref>    # 指定基线
dl list                   # 列举
dl <name> --done          # 归档（删 worktree+分支+元数据）
```
- `<name>` 仅小写字母/数字/连字符/下划线，≤64（`dl-lib.sh` 校验）。
- 必须在 git repo 内运行（launcher 用 `git rev-parse` 反查项目根）。
- provider env：launcher 永远 `exec claude`，env 由调用方 shell 继承。`ac-ark --dl` 因 ac-ark 已 export env 而走 ark；`dl` 用当前 shell env。不用 `@provider`（provider 是函数时 launcher 子进程 exec 不到）。

### 1.2 改工作流脚本/hook/command 后
- 改 `~/.dl-workflow/hooks/*.py` -> **无需 install.sh**（settings.json 直接引用源），下轮 hook 触发即最新版（无需重建 worktree）。
- 改 `dl_flow_engine.py` / `dl_flow_nodes.py` -> 同 hook：**对在跑实例即时生效**（hooks 运行时 import，区别于 phase-rules 的 launch 快照）——**改载荷契约/机械校验必须评估在跑实例兼容**（2026-08-02 v2.40 沉淀）：①**写侧硬拒新键**=自愈合——旧 purpose 指导下的模型不知新键，但报错文本指路，当轮补键重交即可；②**读历史 trace 的校验**（如 fetch_report_recorded 读子2 atomic_questions）必须对旧形态 trace 走 legacy 路径（无键→旧行为），否则在跑实例的旧 trace 永远过不了新校验=卡死。legacy 分支是版本兼容，不算 silent fallback（注释写明 + 测试 pinning）。
- 改 `~/.dl-workflow/output-styles/*.md` 或 `commands/*.md` 或 `skills/` -> 跑 `~/.dl-workflow/install.sh` copy 到 `~/.claude/`，再**重启会话**加载（output-style / slash command 在会话启动时载入）。
- 改 `~/.dl-workflow/scripts/workflow/*.sh` -> 无需 install（launcher 直接从 dl-workflow 内跑），下次 `dl <name> --resume` 或新建即最新。
- 改 `phase-rules.md`（append-system-prompt）-> 仅新开会话生效（append-system-prompt 是启动时载入）；已有会话不同步。**v2.12 起 phase-rules.md 是模板**：understand:1 的 6 条子步骤 purpose 段是 `<!-- BEGIN/END GENERATED sub_steps -->` 标记占位，launcher 每次启动调 `dl_flow_engine.py render-phase-rules` 渲染到 per-wf `phase-rules.rendered.md`（渲染失败中止启动）——**改 engine 的 Step.purpose 即自动同步双通道，新启动会话即生效，无需 install、无需手改 phase-rules**；phase-rules 静态部分（围栏/强制语义/完成标记）仍手维护。
- per-wf `settings.json`（在项目 `.claude/workflows/<name>/`，非快照）改了要重启会话加载。**生命周期与 phase-rules 相反（2026-07-30 审计踩坑）**：resume 只在 settings.json **缺失时**补写（dl-launch.sh `[ -f ... ] || wf_write_settings`）——改 `wf_write_settings` 模板（如 allowlist 扩展）后**存量工作流不自动跟进**，须在目标项目 repo 内手工刷新：`bash -c 'source ~/.dl-workflow/scripts/workflow/dl-lib.sh && wf_write_settings <name>'`（WF_META_ROOT 靠 cwd git 反查，勿在 dl-workflow 仓内跑）。对照：phase-rules.rendered.md 每次 launch/resume 重渲（改 engine purpose 即生效，见上条），无需手工。**v2.35 起有版本戳兜底**：engine `SETTINGS_TEMPLATE_VERSION` 单源，settings 盖章 `wf_settings_template_version`，workflow_phase 注入 + `/dl status` 双通道警告落后并指 `--resume`；**改 `wf_write_settings` 模板实质内容（allowlist/hooks/defaultMode）时必须 bump engine 常量**（唯一 bump 点），否则存量会话静默缴税无警告。

**与 v1.x 项目内嵌版本对比**：v1.x 里 hook 在 `<项目>/.claude/hooks/` 是 git 快照，改后必须 commit + 重建 worktree；本版本 hook 在 `~/.dl-workflow/hooks/` 直接引用（不 copy），无此约束。

**worktree 异位承载分支的自引用检查（2026-08-23 force-tacet 承载两连坑：961d86d + 1576686）**：把分支检出进独立 worktree 跑 launch 链路（worktree-per-session 协议的常规操作）前，必查三件：
- **grep 全部主树绝对路径自引用**：分支代码硬编码 `~/.dl-workflow` 的每一处（engine 派发命令 / dl-lib.sh hooks+statusline+白名单 / prompt 文案里的 CLI 指路），全部改按 `__file__`/`WF_LIB_DIR` 解析。**编排面断链 = tacet 整轨静默跑错形态而非报错**（state force_tacet=True 但段工人派到主树 driver，evidence 零 tacet 记录）。
- **hooks 路径逐层数清**：hooks 在**仓库根**，`$WF_LIB_DIR`（=scripts/workflow）到它是 `../../hooks`--差一层解析成不存在的 `scripts/hooks/`，UserPromptSubmit 全灭（用户每输一句话都被 hook 拦死）。
- **冒烟必须真执行，打印命令字符串逮不住路径错**：改后冒烟 = 逐 hook 真跑 `rc=0` + 测试断言每条 hook/statusline 命令 `Path.resolve().exists()`（只打印不验存在性 = 上述两坑双漏）。

- 多 commit 拆分提交时**每个 commit 前跑 `ruff format --check`**（2026-08-13 P2-4 实例）：只在一批改动全完成后查一次，format drift 会落进已提交的 commit，事后修补再叠 stash 操作即出冲突链（stash → format 改到 stash 涉及的文件 → pop 冲突）。拆 commit 的粒度纪律要与 format 检查的粒度一致。

**hook 协议能力边界**（2026-08-05 围栏兜底三修实证，设计新 hook/围栏前必读）：
- **PreToolUse 只能 allow/deny，不能转换/重写工具调用**：协议没有「把 Write 改写成 Bash」的语义。要等价实现「模型调错工具 -> 自动用正确工具」-> **deny + 副作用**：hook 识别到目标工具调用 -> 在 hook 进程内 `subprocess` 跑正确命令（如 `fetch_prompt --out`）-> 返回 deny 文案指路正确产物（「已自动生成，Read 取用」）。模型被 deny 但正确产物已落盘。实例：骨架 Write 兜底（workflow_step_fence.py，模型 Write 骨架 -> hook 副作用调 `--out` 刷新 -> deny 指 Read）。
- **Stop hook stdin payload 不带后台 agent / pending task 状态**：payload 只有 `cwd/transcript_path/session_id` 等。要检测「有无未归的后台 agent」须**读 transcript JSONL**（Agent tool_use 的 id 集合 − 已配对 tool_result 的 tool_use_id 集合 = pending 数）。实例：`_pending_background_agent_count`（workflow_advance.py）。**Stop hook 是同步阻塞子进程**--不要在里头 sleep 轮询等 agent（agent handback 能否在 hook 阻塞期间写 transcript 未验证，可能死锁）；让模型用 TaskOutput 原生等更安全。
- **PreToolUse 的一票否决 vs 步骤放行**：围栏白名单按段/按工具判定，写意图信号（输出重定向/命令替换/`open(,'w')`/`os.system` 等）一票否决。新增「看似只读但能执行任意代码」的工具（如 `python3 -c`）放行时，必须扫内联代码的写信号，且接受「非对抗威胁模型下扫描非完备」的口径（同 S11 Bash 盲区）。

### 1.3 关键文件职责（改前必读）
| 位置 | 文件 | 职责 |
|---|---|---|
| `~/.dl-workflow/scripts/workflow/` | `dl-launch.sh` | 建/续 worktree+state+settings，起 claude |
| ↑ | `dl-lib.sh` | 阶段定义 + state 读写 + `wf_write_settings` + 路径反查 |
| ↑ | `dl-cmd.sh` | `/dl` 子命令逻辑 |
| ↑ | `phase-rules.md` | append-system-prompt，各阶段行为规则 |
| `~/.dl-workflow/hooks/`            | `workflow_phase.py` | UserPromptSubmit 注入当前阶段 |
| ↑ | `workflow_advance.py` | Stop 检 PHASE_DONE 推进 + sub_steps 门控（evidence hash 触发） |
| ↑ | `workflow_step_fence.py` | PreToolUse S15 前置参与围栏（零 trace 白名单）+ S10 步骤围栏（未判决 trace 时 deny） |
| ↑ | `workflow_session.py` | SessionStart 交接包注入（v2.45）：source=clear/startup 且工作流有 trace 时注入 engine.handoff_pack；resume/compact 不注入。架构事实：`/clear` 清对话但系统提示（phase-rules）随进程保留 |
| ↑ | `codegraph_gate.py` | PreToolUse H15 门禁（改已有 .py 前先查 codegraph） |
| ↑ | `codegraph_audit.py` | PostToolUse 记 codegraph 查询 |
| `~/.claude/output-styles/` | `workflow.md` | 横幅 + 常驻 TaskList 首要规则 |
| `~/.claude/commands/` | `dl.md` | `/dl` slash 命令入口（调 dl-workflow 内 dl-cmd.sh） |


### 1.4 增/改/废 `/dl` 子命令 checklist（2026-07-28 v2.22 state-reset 替代 step-reset 实证）

改「用户可见子命令」的完整改动面（比 §SKILL 不要做的事里的批量重命名 checklist 小一号，子命令级）：

1. `dl_flow_engine.py`：业务函数 + argparse `choices` + `if args.cmd ==` 分发（**废命令 = 直接删 choices 项**，旧命令撞 argparse usage 错，不留别名）。
2. `scripts/workflow/dl-cmd.sh`：case 分支 + **头部用法注释** + 末尾「未知子命令」提示串（三处易漏后两处）。
3. `commands/dl.md`：frontmatter description 用法串（/dl 帮助页唯一入口）。
4. 文案引用面 grep：`grep -rn "<旧命令名>" hooks/ scripts/ skills/ --include="*.py" --include="*.sh" --include="*.md"`——门栏/错误提示里引导用户调旧命令的文案全要换（phase-rules.md、workflow_phase.py、workflow_advance.py 是重灾区；**历史 designs/*.md 不换**，保持决策当时记录）。
5. `tests/`：旧命令用例改新命令 + 新语义新用例。
6. `install.sh` + **重启会话**（commands/*.md copy 才能注册新用法串）；hooks 文案源直引即生效，无需 install。

**engine 数据形态注意**：`Node.sub_steps` 无编排节点是 **`None` 不是 `[]`**——`len(node.sub_steps)` 直接 TypeError（v2.22 TDD 红阶段抓到），遍历/计长前必须 `node.sub_steps or []` 或 `if not node.sub_steps` 先判。

### 1.5 改 dashboard 的验收纪律：pytest 绿 ≠ 工作，必过真实实例 E2E

> 2026-08-31 全天实爆沉淀。核心教训：**dashboard 的 bug 大多活在时序窗口、状态机联动和真实模型行为里——单元测试全绿照样三连爆**（已答标记 v1 单测 224 全绿，真实 E2E 一跑：标记 90s 失效 + 注入零落库两连）。

**必须跑真实 E2E 的改动面**（改这些不许只交 pytest）：inject/答题链路、段生命周期（spawn/收段/门控）、交互卡渲染（need_user/answered）、统计 join（segment_stats/metrics）、时间轴三肤、静态版本戳。

**sweep 驱动脚本模式**（`~/scripts/dl_dashboard_e2e.py`，用户决议脚本留本地不进仓）：
1. `POST /api/create` 建 throwaway 实例（provider 指定 ac-deepseek1）→ 每 15s 轮询 `/api/workflow`
2. `inject_ready=True` → 自动答题（选项逐字 + 痛点补充——define-problem 类 gate 要求 who/pain/why-now 可观察后果；读回类首选顶=确认语义）
3. **异常检测器**（判据可直接复用）：READY_WITHOUT_CARD（ready 但无卡）/ MARKER_NOT_HOLD（注后标记未覆盖）/ ANSWERED_BUT_DEAD（answered 覆盖中但 driver 死>3min=横幅说谎）/ STALL_NODRIVER（driver 死+非等人+非门栏+非终态=永久停摆）/ STALE_CARD_SHOWN（卡绑定≠state=server 漏滤）/ LIST_DETAIL_DIVERGE
4. 中段演习 pause/resume、撞门栏演习 /api/gate；终态核验 artifact/outputs/totals/evidence；`--keep` 可留实例
5. 全量轮询落 `/tmp/e2e-sweep-<name>.jsonl` 供事后归因

**复跑纪律**：修复后必须整轮复跑到零异常（不是只验证修复点）——本轮实锤：run1 抓 6 问题，修复后 run2 全生命周期零异常才算收口。

**E2E 抓得到、单测抓不到的三类设计判据**（写码时就按此设计，别等 E2E 抓）：
1. **保守分支的前提用通道物理属性判别**（stdin TTY = 有无真人键盘），不用状态标志位——新通道的写入路径会绕过标志位（症状 AK）
2. **判覆盖/判变更用内容 hash 不用 ts**——同一内容重落盘 ts 必变（症状 AI）
3. **join 型统计每个产出单位都要有台账锚点，多行同键保序配对**（症状 AO）

### 1.6 判据（purpose/mech/gate 文本）改动的 E2E 重放验证规程

> 2026-09-02 enum_replay_1 实证（pattern-enum-regression-guard-design §5）。§1.5 管 dashboard 改动、judge framing/判据变更走 n≥6 三向重放（§3.5 #28），本节的缺口补的是 **mech/purpose 类判据改动**：单测能证 mech 函数对错，证不了「真实模型在新 purpose 下的行为是否如设计」——弱模型对判据文本的解读是行为变量，必须真实工作流重放。

**精髓 = 镜像**：同一输入、两种判据，产出差异即判据效果。步骤：
1. `bash -c 'source ~/.bashrc; ac-<provider>; python3 ~/scripts/wf_ctl.py create <name>'`——provider 在 create 时钉死（建议弱模型，弱模型优先原则：判据是给弱模型读的）；`wf_ctl create` 不带 `--force-tacet`（默认仅 fermate），要组合轨道再 `python3 ~/.dl-workflow/dl_flow_engine.py force-tacet <name> on`
2. `wf_ctl.py statement <name> <与历史实例逐字相同的问题陈述>`——逐字镜像是对照有效性的前提（同一个 bug、同一触发，产出差才归得给判据）
3. drive/inject 循环：NEED_USER 断点读 need_user.json，**镜像历史实例的同维度答案**（选中项语义对齐即可，卡片选项不必逐字同）
4. 验收点 = trace 判据项 + 终态产物对照：新判据要求的留痕项在场且内容合格（本例 u:1#4「模式枚举」项含全仓 grep 命令+9/9 全量命中）、终态改动面与对照组逐项比（召回/精度/回归防护/成本四轴——本例修复前 7 条 vs 重放 10 条 vs 全量轨道 12 条，成本 26%）
5. **中断恢复**：后台 drive 被 Monitor/会话退出收割（exit 137）≠ 实例损坏——state/evidence 完好，`ps` 确认无残留 driver/段进程后直接再 `drive` 即续跑（本session实证：u:1#4 中途被割，重 drive 一步跑完）

**与 judge 重放的分工**：judge 判据/framing 变更 → n≥6 三向重放（§3.5 #28，裁决方向回归）；purpose/selfcheck/mech 变更 → 本节真实实例镜像重放（模型行为回归）。gate 文本双侧钉死类改动两轴都要。
