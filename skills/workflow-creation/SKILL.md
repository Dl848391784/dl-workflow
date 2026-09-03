---
name: workflow-creation
description: 建工作流系统 + 运行诊断 + 运行审计。触发：新建/改工作流、dl 命令、阶段不推进、注入没生效、/dl 报错、hook 装错位置、模型否认收到注入、5 阶段不显示、gate 裁决记录(evidence)不落地、子步骤编排(sub_steps/STEP_DONE) 不推进、evidence 写到 worktree、审计一轮运行(可避免的 error/返工/耗时/token 优化)、tacet 实验轨道/dlt/force-tacet 行为、fermate/plan-only 轨道判读（跑没跑完/停在 plan:2）、dashboard 症状（提交按钮复活/陈旧卡/时间轴缺数据/总时间不对/修复没生效/时间轴挂永不执行的节点/进度不满100%）。
version: 2.9
---

# workflow-creation

> 建工作流 + 运行诊断手册的**瘦路由**。系统全景在本文件；重型参考拆在 `references/`，**命中下方路由表才 Read 对应文件，不预读全部**（base directory 即本目录）。真源 = `~/.dl-workflow/designs/workflow-system-design.md`。
> **dl-workflow 版本核心事实**：跨所有项目生效，装在**用户级**。两类 artifacts 装法不同：
> - **skill / output-style / command**：`install.sh` **copy** 到 `~/.claude/`（Claude Code 硬编码加载路径）。改后跑 `install.sh` 重 copy + 重启会话加载。
> - **hooks（5 个 .py）**：**不 copy**，`settings.json` 直接引用 `~/.dl-workflow/hooks/*.py` 源（shell 执行时展开 `~`）。改 hook 源后 `git pull` 即生效，**连 `install.sh` 都不用，更无需重建 worktree**——这是与 v1.x 项目内嵌版本的关键差别（v1.x 里 hook 是 worktree 内 git 快照，改后必须 commit + 重建 worktree）。

## 0. 系统全景（5 秒理解）

```
dl <name>  ─►  ~/.dl-workflow/scripts/workflow/dl-launch.sh
                                  │ 建 git worktree(<项目>/.claude/worktrees/<name>, 分支 wf/<name>)
                                  │ + state.json(<项目>/.claude/workflows/<name>/) + 钉 session
                                  │ 起 claude: --settings(per-wf) --append-system-prompt-file(phase-rules) --session-id
                                  ▼
   原生 claude TUI（worktree 内 cwd）
     ├─ ~/.dl-workflow/hooks/workflow_phase.py   (UserPromptSubmit) → 注入「## WORKFLOW 当前阶段」到 hook_additional_context attachment
     ├─ ~/.claude/output-styles/workflow.md  → 引导模型输出 ## PHASE: <中文名> [n/5] + 维护 TaskList 常驻清单
     │     ⚠ 注入走 attachment，部分模型（ark-code-latest）收不到；output-style 已加 fallback：看不到注入时模型用 Bash 跑 dl-cmd.sh status 自取阶段（allowlist 免提示）。见症状 D
     ├─ ~/.dl-workflow/hooks/workflow_advance.py (Stop) -> 委托 dl_flow_engine.run_gate（机械+judge）；检完成信号(### PHASE_DONE/SUB_DONE) -> pass 推进 / block 返 additionalContext 续轮(模型自动重试)；有 sub_steps 节点走 gate_sub_step_at_stop（evidence hash 触发，症状 J）
     ├─ ~/.dl-workflow/hooks/workflow_step_fence.py (PreToolUse) -> S15 前置参与围栏（零 trace 窗口白名单，为用户任务探查首调即 deny 指回编排，症状 O）+ S10 步骤围栏：当前子步骤有未判决 trace 时 deny 一切工具调用（逼模型 STEP_DONE+end_turn）；开关 state.enforce_step_fence（/dl fence on|off，实时生效）
     ├─ ~/.dl-workflow/hooks/workflow_session.py (SessionStart) -> /clear/startup 且工作流有 trace 时注入交接包（engine.handoff_pack：前序证据+用户裁决+产物指针；resume/compact 不注入）——上下文交接架构（designs/context-handoff-design.md，v2.45）：会话不重置则 token 成本=轮次×单调涨的上下文=平方膨胀；pass 续轮超 150k 阈值附 /clear nudge（纯建议）。正确性前置=读回步 user_decision_recorded 机械校验（裁决必入 trace）
     ├─ ~/.dl-workflow/dl_flow_engine.py (编排内核,被 hook 咨询) -> 节点树+gate判据+推进 唯一真源；gate-pass 时 write_gate_verdict 写 kind=gate 裁决记录到 evidence/<name>.jsonl（替代旧 ### EVIDENCE 溯源，§8.6c）
     └─ /dl status|next|back|jump|gate|done  → ~/.dl-workflow/scripts/workflow/dl-cmd.sh
   清理两命令语义拆正（2026-08-29 用户决议）：`dl <name> --delete`=删除（彻底丢弃：worktree+分支+元数据全删，dashboard 连带删产物 plans/understands/evidence）；`dl <name> --done`=归档（只删 worktree 释放磁盘，分支+元数据+产物全留可回看；暂不自动触发，执行完不自动归档）
```

**运行模式三态**（入口唯一决定，state 磁盘真源互通可续）：v4 默认 = `dl <name>` 常驻 TUI 前台 + 会话内派发 `dl_drive.py --segment` 后台段跑非交互步（designs/front-tui-hybrid-design.md，2026-08-11——hooks 走 front 分支：phase 注入派发块 / advance stall 兜底 3 次计数闸 / fence 非交互步白名单；**同日用户裁决默认翻转**）；v3 = `dl <name> --headless` 全程 headless driver（designs/headless-driver-arch-design.md）；WF_TUI=1 = v2 旧 TUI hook 编排（回滚面）。

**观测/控制面 dl_dashboard**（2026-08-28 起，`dl_dashboard/` + `python3 -m dl_dashboard.app`，0.0.0.0:9000）：dl 的第三个入口（前两个=终端 `dl`/`dlt`、wf_ctl 脚本）——Web 控制台：跨项目列表/三肤步骤时间轴/改动面审核卡片/证据链/产物阅读 + 创建/注入/gate/暂停恢复/删除全驱动。机制要点：driver 为 server 的 setsid 子进程 + PID 文件 + **/proc 野生认领**（diagnostics 症状 AH）；inject 守**时序铁律**（症状 AF 窗口/AG 误杀备题段）；可见步（tacet 脊柱/fermate 裁剪）一律取 `dl_flow_nodes.tacet_silent_steps()`/`FERMATE_SILENT_STEPS` 单源，消费方禁自猜；可见节点（fermate 轨道裁剪）同规取 `fermate_cut_node()`/`fermate_phase_reachable()`，scanner 组合下发、前端零手写过滤（症状 AS）；改 py 后端必重启 server 进程才生效（症状 AR，常驻内存旧码）；provider 选择 = server 启动时 `bash -c 'source ~/.bashrc; <ac-fn>; env'` 捕获 ANTHROPIC_*/CLAUDE_* 注入 driver spawn env（bashrc 函数不可被子进程 exec，症状 AC 同根）。模型实测判据 = drive-stream result 事件 `modelUsage.canonicalModel`。**2026-08-31 全链路加固**（全天 E2E 实爆驱动，designs/dashboard-{answered-marker,segment-autocontinue,notty-segment-and-entry-judge}-design.md）：no-TTY 判别 = stdin TTY（交互段一次性 `-p` + 结构性移除 AskUserQuestion；收段落共享门控自动续跑）；driver 接管**入口判决**（先判未判决 trace 再派活）；已答标记 `answered.json`（内容 hash + block 放行三态：准备中/表单/已提交横幅）；问题卡带步骤绑定（`need_user_stale` scanner 单源过滤）；`gate_actionable`（按钮可见性）/`step_labels`（中文步名）/`current_segment`（在飞段起点=总执行时间在飞项）scanner 统一下发；合并段逐 turn `merged-step` 台账 + sid 行序配对统计；静态版本戳 = mtime 动态注入。验收纪律见 build-and-modify §1.5（pytest 绿≠工作，改 dashboard 必过真实实例 E2E）。**2026-09-04 evolution-up 增量**（designs/evolution-up-design.md）：①SIGTERM 不死修复——SSE `/api/events` 生成器 `is_disconnected` 即退 + `timeout_graceful_shutdown=3`（旧版 while True 无出口，长连接在场优雅退出无限等，两次 kill -9 实爆）；②实例**自动审计区**（detail 页，`dl_dashboard/audit.py`）——一次通过率/block 分布/节点成本，**口径实查沉淀：子步骤级只有 block 落 kind=gate，pass 不留痕，「通过」由 traces>blocked 推导；读回步 gate=None 免判不计**（对账 amplitude_annualized 86.1% 与 v2.119 实测一致）；③**系统健康页** `/health`（`health.py`）——跨实例 gate thrash 榜/节点成本 p50-p90 榜/dispute 榜=改进队列数据化；④**插话通道**——detail 页输入框 → `steer.jsonl`（dl_flow_common，只经脚本写）→ driver `build_step_prompt` 起跑读 offset 未消费行注入段 prompt 尾（建议通道不豁免机械门）。

**TACET 实验轨道**（2026-08-23 收口合并 main，designs/force-tacet-experiment-design.md）：`dlt <name>` = 同一 launcher 自动附加 `--force-tacet`--六步脊柱（u:1#1/u:1#2/u:1#3/u:1#4/plan:1#2/plan:4#4）全额执行，其余 38 子步 engine 机械静默（零 token/零 judge），到 plan:4 门栏与 main 同路径停等。`force_tacet` 是 per-instance sticky state 开关（engine 全程 state.get 判定、默认 off），**模型无权自封**；普通 `dl` 永远全量 44 步。实例开关：`dl_flow_engine.py force-tacet <name> on|off`。**中途升级**（evolution-up P3，2026-09-04）：`/dl upgrade <phase>:<sub>#<step>` 把单步移出本实例静默集改全量（`state.tacet_upgraded` sticky，`tacet_silent_for` 单源派生，scanner/交接包/时间轴全链路跟随），按指引 `/dl state-reset` 重跑——沉默步欠账的补救通道，对齐 fermate off+state-reset 形态。**相似实例检索**（evolution-up P4）：`handoff_pack` 在 understand 阶段注入「相似历史实例」节——字符 bigram Jaccard 检索跨项目历史实例的 根因@ 行（项目池读 dashboard.toml），钉死「参考非证据=竞争假设候选，须本仓取证」。

**FERMATE（plan-only）轨道**（2026-08-26，designs/fermate-plan-only-design.md；**同日用户决议默认翻转：新实例默认 fermate，`--forte` 进完整模式**——默认落 launcher 层新建分支，在飞/续跑实例零迁移，WF_TUI=1 旧路径豁免默认）：第二正交开关——tacet 管步骤**密度**（44 步内 38 静默），fermate 管流程**深度**（plan 止于 plan:2，plan:3/plan:4 裁剪不存在：能力包/检查点消费方全在 execute，无执行=产物纯税）。`dl <name> --forte`=完整模式（可与 --force-tacet/dlt 组合，dlt 透传零改动；组合时脊柱重映射 plan:4#4->plan:2#4）——plan:2 末步过门控即实例完结（gate=done，fermate-auto-complete-design 2026-08-29：无门栏无 `/dl gate` 收货环节，人工确认点唯一 = `/dl done` 归档），plan.md 只有「执行步骤」一节=最终交付物。`force_fermate` per-instance sticky（模型无权自封）；实例开关：`dl_flow_engine.py fermate <name> on|off`。升级全量执行：fermate off + `/dl state-reset plan:2`。u:4#3（验收方式设计）v2 已裁剪（u4-sub3-fermate-cut-design：fermate 下整步机械静默，u:4#4 验收包三字段+占位声明×state 双向核验，gate 静态兜底零变体）——fermate 轨道=32 步。

**judge 成本基线**（2026-07-25 实测，commit 8f6eaee 起）：judge 单次新鲜输入曾 ~2.1-2.4 万 token，其中 ~95% 是 harness 开销（全套工具 schema + 默认 system prompt + skill 列表 attachment），判决载荷仅 ~0.5-0.9k。已用 `claude -p --tools "" --system-prompt <judge人设>` 裁剪（-84%~-91%，实测单次 ~2.2-3.3k），判决 prompt 逐字不动、settings/认证链不碰（env 继承与 settings.json env 块用户都照常）。**若审计发现 judge 又回到 ~2 万级，先查 run_judge 的这两个 flag 是否被改丢**。**v2.44 输出侧裁剪**：judge 子进程 `MAX_THINKING_TOKENS=0`（2026-08-02 tail_volume u:1 审计——推理模型 judge 两次离群 115s/99s、输出 10.8k/11.4k tok 而可见判词仅数百字，thinking 占输出 ~92%；MiniMax-M3 同一真实载荷 A/B：3529 tok/39.2s -> 278 tok/6.3s，真实被 block/通过载荷重放判决方向均一致；K3 端点忽略该 var 无副作用）。**judge 耗时/输出再离群，先查这个 env 是否被改丢**。准确性靠重放回归保证（同一真实案例新旧判决必须一致），见 tests TestRunJudgeHarnessTrim。~~caveat：judge 输入随 evidence.jsonl 线性增长~~ **已修（2026-07-26 v2.12）**：子步骤 gate 的 artifact 改由 `read_evidence_for_step` 裁剪——只喂当前步 + 前序各步**最新** trace（子5 跨步 verdict 上下文保留；返工历史/kind=gate 记录不喂），真实 demo evidence 冒烟：子1 -97%、子3 -65%。后期步骤 judge 输入仍随步数缓涨（每步一条 trace）是设计内现象。**judge 失败重试策略**：bad_verdict_json 与 TimeoutExpired 各重试一次（递归爆炸根因已被 cwd=tempdir 修掉；超时降级会让模型白返工一轮，demo fbdb6ebd 子2 实测），API 错/exit 非零/OSError 不重试。

**5 阶段**：understand 理解和求证问题（禁改源码）-> plan 生成执行计划（禁改源码）-> execute 执行 -> review 审核结果 -> evolution 进化。显示用中文名，逻辑层（state/PHASE_DONE/jump）用英文标识。
**understand 含 4 子阶段**（依次自动推进，无子阶段闸门无门栏）：1.理解问题和背景 / 2.明确目标和价值 / 3.确定范围与约束 / 4.定义成功标准和验收方式。**4 个子阶段全部有编排**（v2.17 起），走 STEP_DONE 逐步门控；末子阶段(4) 子5 内装配 understand.md，末步过门控自动进 plan:1（无 PHASE_DONE: understand——2026-07-28 起 understand->plan 无闸门）。详见 `designs/understand-subphases-design.md`。
**两级命名约定**：节点 id `<phase>:<sub_index>` 是**子阶段**（minor_state；sub_index=0 = 无子阶段的整阶段节点，如 execute:0）；子步骤是子阶段**内部**的「子N」（机制层 `sub_step_index` / evidence `sub_step` 字段），不用 `plan:N` 记号——「plan:2」= plan 的第二个子阶段，不是某子阶段的第 2 子步骤（2026-07-28 用户实测歧义一次，写死省澄清）。
**推进**：自动 + 闸门。**唯一用户裁决点 = plan 完成**（2026-07-28 用户决议：understand->plan 闸门与 understand:2/3/4、plan:1/2/3 门栏全部撤除）——`plan:4` 末步门栏扣留等 `/dl gate`（放行 ≠ 推进），放行后 PHASE_DONE: plan 撞 `plan->execute` 大闸门需第二次 `/dl gate`；其余全部自动推进。
**plan 含 4 子阶段**（v2.21 起全部有编排）：1.设计解决方案（6 步）/ 2.拆解任务与阶段（5 步）/ 3.选择能力与工具（6 步）/ 4.制定执行计划和检查点（5 步）；plan:1/2/3 末步过门控自动进下一子阶段，plan:4 门栏放行后输出 `### PHASE_DONE: plan` 撞 plan->execute 闸门。详见 `designs/execution-plan-checkpoints-substeps-design.md`。

**各编排节点子步骤索引**（understand:1 7 步 / understand:2-4 各 5 步 / plan:1 6 步 / plan:2 5 步 / plan:3 6 步 / plan:4 5 步；purpose 第三通道）→ `references/nodes-index.md`（纯结构索引）。**拆步方法论**（第一性原理推导链）→ `references/node-split-methodology.md`。改 engine Step.purpose 实质内容后须手工同步 nodes-index.md 摘要块。

## 路由表（触发 → Read 哪个 reference）

| 触发场景 | 文件 |
|---|---|
| 运行出症状：注入没生效 / 阶段不推进 / 模型否认注入 / 横幅清单不显示 / 子阶段·子步骤不推进 / evidence 不落地或写错位 / 围栏 deny / judge 递归爆炸 / judge 全量超时 / 模型违规模式 / 跑太慢 / 段卡死 / 前台抢活 | `references/diagnostics.md`（按症状字母 A–Z 查，文件内 §2 节号保留） |
| 通用排查方法论（日志三层分诊 / attachment 验真 / token 审计口径 / hook 冒烟法 / 卡住分诊 runbook） | `references/troubleshooting.md`（§3） |
| 改判据 / 改 rubric / 改 gate / judge 判得不对（判据怎么写：分工/披露/钉死/判词/framing） | `references/gate-rubric-design.md` |
| 词形/结构/存在性判据下沉机械层（append-trace 当场拒、写侧校验） | `references/mechanical-checks.md` |
| 弱模型约束（文案失效→机制堵入口、一次通过率、步骤越界） | `references/weak-model-mechanisms.md` |
| 审计一轮运行（可避免的 error/返工/token/耗时、成本归因、方差） | `references/runtime-audit.md` |
| 从严 gate → 默认-PASS framing 反转操作序列（逐节点 playbook） | `references/gate-framing-playbook.md` |
| 优化耗时/token（瓶颈分层、探索预算、上下文膨胀、提效杠杆） | `references/cost-optimization.md` |
| 写/改任何喂给模型的文案（注入块 / phase-rules / judge prompt / 让模型产出记录） | `references/prompt-engineering.md`（§3.7） |
| 设计新编排节点 / 拆子步骤（第一性原理/失效模式族/几步怎么定） | `references/node-split-methodology.md` |
| 查某节点有几步/每步干什么/关键不对称/消费契约 | `references/nodes-index.md`（节点结构索引） |
| 新建/改工作流脚本·hook·command、install 机制、关键文件职责 | `references/build-and-modify.md`（§1.1–1.4） |
| 另一会话在改同仓库 / 文件被外部修改 / 两批改动拆分 commit / 测试全红归因 | `references/collab.md`（§1.4+§3.9） |

## 4. 不要做的事

- ❌ **手改 hook 逻辑**：应直接改 `~/.dl-workflow/hooks/*.py`（git 跟踪），`git pull` 即生效，无副本同步。
- ❌ **改 `~/.claude/` 下的 skill/commands/output-styles 副本**：真源在 `~/.dl-workflow/`，副本是 install.sh copy——改副本造成双向漂移（2026-08-02 两实例：references 先改副本再回拷真源=**把真源领先的 v2.51 段回滚了**——副本可能落后真源（install.sh 未重跑），cp 副本→真源前必须 git diff 真源确认无损，正确顺序永远是改真源→同步副本）。动手前先确认路径在 `~/.dl-workflow/` 下。
- ❌ **用 `-p` 验证推进**：-p 下 transcript 可能空，Stop hook 读不到 PHASE_DONE。
- ❌ **在 user message 文本里找注入**：注入在 `hook_additional_context` attachment。
- ❌ **用 `printf | claude` 验证交互行为**：Execution error 伪问题。
- ❌ **同时在项目级和用户级注册同一 hook**：会双跑或路径解析错。删项目级注册，只留用户级（install.sh 装的）。
- ❌ **在主项目目录找 worktree 会话的 transcript**：worktree 会话 transcript 在独立目录 `~/.claude/projects/-...-worktrees-<name>/`，非主项目目录。按 state.json 的 session_id + worktree 路径编码找（症状 I）。
- ❌ **旧 `no_markers` 系统已弃用**（§8.6c）：新系统 gate 裁决记录看 `.wf_advance.log` 的 `gate_verdict_written`，不看 `.wf_evidence.log`/`no_markers`。
- ❌ **有 sub_steps 节点用 Bash 相对路径写 evidence**：worktree 内 `cat >> .claude/evidence/...` 会写到 worktree，hook 读主仓库读不到（症状 L）。必须用主仓库绝对路径（注入里给的 `<项目>/.claude/evidence/<name>.jsonl`）。
- ❌ **改编排只改 engine/hook 不改 phase-rules.md**：phase-rules（system-prompt）优先级高于 attachment 注入，漏改会打架（症状 M）。改编排必过 checklist：engine + workflow_phase 注入 + workflow_advance 检测 + **phase-rules 强制语义**。
- ❌ **批量重命名直接 sed 词边界**（2026-07-25 /wf→/dl 实测翻车）：`\>`/`\b` 的边界**包括连字符**——`s|/wf\>|/dl|g` 把 `wf-cmd.sh` 路径引用一起改成 `dl-cmd.sh`，被迫连脚本文件也改名（索性统一品牌才没回滚）。先 `grep -rn` 预览命中面，再决定「只改文案」还是「文案 + 文件名一起改」。改用户可见命令名的 checklist：`commands/*.md` git mv / 全仓文案（hooks 提示 + phase-rules + output-style + SKILL + designs）/ install + uninstall.sh / **.bashrc（install.sh 对已有段落跳过，必须手动改；当前 shell 还要 `exec bash` 清函数缓存）** / 旧 per-wf settings（`dl <name> --resume` 补写）/ 删 `~/.claude/commands/` 旧文件 / 重启会话注册新命令。
- ❌ **有 sub_steps 节点重做时覆盖写 evidence**：Stop 门控以「最新 trace 行 hash 变化」为返工信号；覆盖写虽也会触发（hash 变），但丢失尝试历史。协议是 **append 新行，勿覆盖**。也别期待"模型输 STEP_DONE 就无条件推进"——无新 trace（没写/内容一字不差）时 Stop 静默放行不推进（症状 J）。


## 5. 触发关键词速查

- "建工作流 / 新建工作流 / dl 命令" → references/build-and-modify.md
- "注入没生效 / 阶段没注入 / 模型说没注入" → references/diagnostics.md 症状 A/D
- "阶段不推进 / PHASE_DONE 没推进" → references/diagnostics.md 症状 B
- "/dl 报错 / state 缺失 / state.json not found" → references/diagnostics.md 症状 C
- "install.sh 后没生效 / hook 没触发" → references/diagnostics.md 症状 G
- "模型否认注入 / 不输出横幅 / 5 阶段不显示" → references/diagnostics.md 症状 D（ark 收不到 attachment）
- "阶段清单不显示 / TaskList 状态错 / 1.1-1.4 顺序错 / 编号时有时无 / subject 不对" → references/diagnostics.md 症状 F
- "子阶段 / SUB_DONE / understand 子阶段不推进 / 提前 PHASE_DONE 被阻断" → references/diagnostics.md 症状 H
- "Execution error / 管道测试" → references/diagnostics.md 症状 E
- "子步骤 / STEP_DONE 不推进 / evidence 有但不推进 / 自动续轮没生效 / 模型不写 evidence" → references/diagnostics.md 症状 J/Q/K
- "evidence 写到 worktree / 路径错位" → references/diagnostics.md 症状 L
- "改编排 / SUB_DONE STEP_DONE 打架 / phase-rules 与注入矛盾 / 改门控 checklist" → references/diagnostics.md 症状 M
- "工具被围栏拒绝 / PreToolUse deny / 围栏没拦" → references/diagnostics.md 症状 O
- "门栏 / 闸门 / 扣留 / 停在某阶段不走 / 改围栏位置（哪个围栏？先消歧：工具围栏=症状 O；推进围栏=门栏/闸门）" → references/diagnostics.md 症状 M「门栏/闸门位置变更专项」
- "跑太慢 / 耗时长 / token 消耗大 / 程序应该毫秒级 / 成本审计" → references/diagnostics.md 症状 R
- "上下文越来越大 / token 平方膨胀 / 交接 /clear / 会话重置接续" → designs/context-handoff-design.md（v2.45 交接架构）
- "工具调用挂起 / 会话卡死不动 / step-pass 没反应 / tool_use 无返回" → references/diagnostics.md 症状 S
- "按系统文案指路操作仍报错 / 文案里的命令照跑也报错 / unrecognized arguments" → references/diagnostics.md 症状 T
- "门禁该拦没拦 / design_gate 或 codegraph gate 形同虚设 / 没写 design.md 也能改多文件" → references/diagnostics.md 症状 U
- "judge 全量超时 / 连最小冒烟都 TimeoutExpired / 端点 curl 通但 judge 全挂 / 重放全超时" → references/diagnostics.md 症状 V
- "TUI 段没 TaskList / 没横幅像普通聊天 / 裸开场条款丢失 / 模型闷头探查不提问" → references/diagnostics.md 症状 X
- "Ctrl+C 不退出 / 退出还继续流程 / 连按好几下才退出" → references/diagnostics.md 症状 Y
- "段在跑没动静 / 是否卡死 / headless 秒退 rc=1 / Input must be provided / 前台模型非交互位置自行干活抢活" → references/diagnostics.md 症状 Z
- "Argument list too long / E2BIG / 段异常起不来 / fence off 了仍被拦 / 段工人故障接管" → references/diagnostics.md 症状 AA + 症状 Z 末条
- "审计这轮运行 / 符合预期吗 / 哪些 error 返工可避免 / judge 输入膨胀 / 重建丢弃" → references/runtime-audit.md
- "无人值守跑工作流 / 顺序跑多轮 / 答案注入 / 注入没生效 / 双 driver / driver 死了还在推进 / 后台任务被收割" → references/runtime-audit.md #25（无人值守驱动 loop+四坑）#27（台账形态）
- "门槛打地鼠 / append-trace 反复被拒 / from-file 提交次数 / 拒绝形态 / 锚点查无 / 改动规格语法不合" → references/cost-optimization.md #54（审计手法+验证口径）
- "tacet / dlt / force-tacet / 脊柱步 / 静默步 / 为啥这步没跑" -> designs/force-tacet-experiment-design.md（轨道语义）；统计/审计 tacet 实例 -> references/runtime-audit.md #27（段->步骤映射三通道）；首跑收口审计（成本账/execute纯度/可用性结论）-> designs/force-tacet-run1-audit.md
- "设计新编排节点 / 拆几个子步骤 / 每步什么目的 / 要不要取证步 / 步数怎么定 / 代码设计拆步 / 拆解任务 / 任务切分 / 执行计划 plan.md" → references/node-split-methodology.md；查某节点有几步/关键不对称 → references/nodes-index.md
- "另一会话在改同仓库 / 文件被外部修改 / 两批改动怎么分开 commit / 测试全红是不是我的问题" → references/collab.md
- "证据链 / evidence / no_markers / evidence.jsonl 不生成 / 证据不落地" → references/diagnostics.md 症状 I
- "提交答案后按钮复活/还能再提交 / 已答窗口 / double-inject" → references/diagnostics.md 症状 AI
- "陈旧问题卡 / 步骤推进了还显示旧问题 / 在跑和等人分不清" → references/diagnostics.md 症状 AJ
- "dashboard 答完题不自动继续 / 每步要手动重新驱动 / driver 过门控就退" → references/diagnostics.md 症状 AK
- "交互段挂起零台账 / 注入后反复重问同样问题 / prep 死循环 / claude 无 -p 进程长跑" → references/diagnostics.md 症状 AL
- "driver 崩溃 UnicodeDecodeError / utf-8 codec can't decode / driver 日志 Traceback 终止" → references/diagnostics.md 症状 AM
- "修复没生效 / 改了静态文件页面还是老样子 / 浏览器缓存" → references/diagnostics.md 症状 AN
- "时间轴步骤缺进度条缺耗时 / 合并段步骤没数据 / 统计对不上" → references/diagnostics.md 症状 AO
- "总时间含等待 / 在跑时间忽大忽小倒退 / 总执行时间不对" → references/diagnostics.md 症状 AP
- "dashboard 没确认卡 / 工作流停了没人问 / 读回确认没让我确认 / driver 断点退出" → references/diagnostics.md 症状 AQ
- "NEED_USER 载荷畸形 / prep 段白烧 / TUI 段已结束但未落库 / need_user.json 不存在" → references/diagnostics.md 症状 AT
- "改动面空 / 产物卡空 / 卡片没数据但产物文件在场 / 解析出 0 条" → references/diagnostics.md 症状 AU（消费方解析器契约漂移，先直跑解析器验真）
- "dashboard 端到端验证 / E2E 怎么跑 / 改动怎么验收" → references/build-and-modify.md §1.5（pytest 绿≠工作，真实实例 sweep 纪律）
- "判据改动怎么验证 / 重放工作流 / 镜像重放 / purpose/mech 改了行为对不对" → references/build-and-modify.md §1.6（镜像重放：逐字镜像陈述+镜像答案，产出差异即判据效果）
- "多选题只能单选 / checkbox 变 radio / 时间轴中文步名 / gate 按钮不该显示时显示" → 均已修（2026-08-31 批次），复现按症状 AN 先查静态缓存再查 scanner 单源字段（step_labels/gate_actionable）
