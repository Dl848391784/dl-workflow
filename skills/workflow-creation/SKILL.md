---
name: workflow-creation
description: 建工作流系统 + 运行诊断。触发：新建/改工作流、dl 命令、阶段不推进、注入没生效、/dl 报错、hook 装错位置、模型否认收到注入、5 阶段不显示、gate 裁决记录(evidence)不落地、子步骤编排(sub_steps/STEP_DONE) 不推进、evidence 写到 worktree。
version: 2.4
---

# workflow-creation

> 建工作流 + 运行诊断手册。自包含。真源 = `~/.dl-workflow/designs/workflow-system-design.md`。
> **dl-workflow 版本核心事实**：跨所有项目生效，装在**用户级**。两类 artifacts 装法不同：
> - **skill / output-style / command**：`install.sh` **copy** 到 `~/.claude/`（Claude Code 硬编码加载路径）。改后跑 `install.sh` 重 copy + 重启会话加载。
> - **hooks（4 个 .py）**：**不 copy**，`settings.json` 直接引用 `~/.dl-workflow/hooks/*.py` 源（shell 执行时展开 `~`）。改 hook 源后 `git pull` 即生效，**连 `install.sh` 都不用，更无需重建 worktree**——这是与 v1.x 项目内嵌版本的关键差别（v1.x 里 hook 是 worktree 内 git 快照，改后必须 commit + 重建 worktree）。

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
     ├─ ~/.dl-workflow/hooks/workflow_advance.py (Stop) -> 委托 dl-flow-engine.run_gate（机械+judge）；检完成信号(### PHASE_DONE/SUB_DONE) -> pass 推进 / block 返 additionalContext 续轮(模型自动重试)；有 sub_steps 节点走 gate_sub_step_at_stop（evidence hash 触发，症状 J）
     ├─ ~/.dl-workflow/hooks/workflow_step_fence.py (PreToolUse) -> S15 前置参与围栏（零 trace 窗口白名单，为用户任务探查首调即 deny 指回编排，症状 O）+ S10 步骤围栏：当前子步骤有未判决 trace 时 deny 一切工具调用（逼模型 STEP_DONE+end_turn）；开关 state.enforce_step_fence（/dl fence on|off，实时生效）
     ├─ ~/.dl-workflow/dl-flow-engine.py (编排内核,被 hook 咨询) -> 节点树+gate判据+推进 唯一真源；gate-pass 时 write_gate_verdict 写 kind=gate 裁决记录到 evidence/<name>.jsonl（替代旧 ### EVIDENCE 溯源，§8.6c）
     └─ /dl status|next|back|jump|gate|done  → ~/.dl-workflow/scripts/workflow/dl-cmd.sh
```

**judge 成本基线**（2026-07-25 实测，commit 8f6eaee 起）：judge 单次新鲜输入曾 ~2.1-2.4 万 token，其中 ~95% 是 harness 开销（全套工具 schema + 默认 system prompt + skill 列表 attachment），判决载荷仅 ~0.5-0.9k。已用 `claude -p --tools "" --system-prompt <judge人设>` 裁剪（-84%~-91%，实测单次 ~2.2-3.3k），判决 prompt 逐字不动、settings/认证链不碰（env 继承与 settings.json env 块用户都照常）。**若审计发现 judge 又回到 ~2 万级，先查 run_judge 的这两个 flag 是否被改丢**。准确性靠重放回归保证（同一真实案例新旧判决必须一致），见 tests TestRunJudgeHarnessTrim。 **caveat（2026-07-26 demo 121320fe 实测）：judge 输入随 evidence.jsonl 线性增长**——`_evidence_artifact` 全量喂 evidence，子1 judge ~3k 到子5 涨到 ~19k 新鲜输入。~2.2-3.3k 基线只对早期步骤成立；后期步骤 judge 更贵是设计内现象，别误判为「judge 又膨胀了」。未实施的优化方向：按 sub_step 窗口裁剪 artifact（注意子5 gate 需跨步 verdict 上下文，不能简单只喂当前步）。

**5 阶段**：understand 理解和求证问题（禁改源码）-> plan 生成执行计划（禁改源码）-> execute 执行 -> review 审核结果 -> evolution 进化。显示用中文名，逻辑层（state/PHASE_DONE/jump）用英文标识。
**understand 含 4 子阶段**（依次自动推进，无子阶段闸门）：1.理解问题和背景 / 2.明确目标和价值 / 3.确定范围与约束 / 4.定义成功标准和验收方式。子 1-3 完成各输出 `### SUB_DONE: <n>`（Stop hook 推进 sub_index）；末子阶段(4) 写 understand.md 后输出 `### PHASE_DONE: understand` 触发 understand->plan 闸门。未走完子阶段直接 PHASE_DONE 会被守卫阻断。详见 `designs/understand-subphases-design.md`。
**推进**：自动 + 闸门。`understand->plan`、`plan->execute` 需 `/dl gate` 放行；其余自动推进。

**子步骤编排（v2.7，§node-step-orchestration + §substep-gate-at-stop）**：某些子阶段（当前仅 understand:1）声明 `sub_steps`--有序子步骤序列（调 skill / 调工具，各有 purpose + record + gate）。**门控单位 = 子步骤**（不是子阶段级 rubric）；**skill 内部 Q/A 不门控**只 record。understand:1 = 6 子步骤（子1 逼问定义 / 子2 拆解深挖[MECE 原子问题清单 + 根因因果链 + 竞争假设，invoke causal-inference-root-cause] / 子3 双向取证[主张可检验化→证伪优先→五层源(OpenAlex/arXiv/SE/HN/GitHub API/WebFetch/内部仓库)→codegraph 新鲜度前置；禁 tavily/WebSearch；禁训练记忆冒充外部证据] / 子4 质检裁决[三关质检(针对性/独立性/可追溯)+条件触发红队(独立上下文)+四态 verdict(证实/证伪/部分成立/证据不足)] / 子5 归一化陈述[原子(单句≤1独立痛点)+去上下文(主语+动词+约束自包含)+携带 verdict 边界/置信度；陈述集与子4 verdict 逐项一致——证伪项不进陈述集、部分成立项不超已证实边界] / 子6 带证据读回确认[呈现陈述+verdict+证据指针+置信度；证据不足显式暴露由用户裁决；多问题选定本实例处理项，其余落 evidence 供后续 dl 实例]），子1/2/3/4/5 gate 跑 judge 校验 evidence 里的 skill-trace，子6 gate=None（trace 存在即过）。v2.6（2026-07-25）：4→5 子步骤，插入子2 拆解深挖——复合问题 MECE 切分不丢弃 + 纵向挖根因防叙事式深挖。v2.7（2026-07-26，`designs/step3-verify-redesign-design.md`）：5→6 子步骤，旧子3 单步「验真」拆为子3 双向取证 + 子4 质检裁决——第一性原理消 F1 主张不可检验/F2 确认偏误/F5 证据不可追溯/F7 单视角四类失效；拆步按失效模式族（取证过程 vs 判断质量），一步内可编排多工具（ref 是声明式标签，engine 不限数量）。v2.8（2026-07-26，`designs/step5-step6-statement-readback-redesign-design.md`）：子4 加④按 verdict 处置问题集、子5 一句话陈述重定义为归一化陈述（claim normalization，消「裁决不传导」缺口）、子6 读回确认升级为带证据读回（消「无依据确认」缺口）——ProblemContext 终态三属性：内容正确(子1-4)/形式可移植(子5)/用户认可(子6)。**推进走 Stop hook**：模型完成一步 **先写/append evidence（主仓库绝对路径）-> 输 `### STEP_DONE: <n>` -> end_turn**；Stop hook 比对 evidence 当前子步骤最新 trace 行 hash 与 state.last_judged_trace 游标--有变化才判（区分「完成」vs「中途暂停等用户」，也防覆盖写漏判）：pass 推进 + **非末步自动续轮**（2026-07-25 决议：pass 也返 additionalContext 指令模型当轮开做下一子步骤，免用户每步发「继续」；末步 pass 仍停轮——子阶段边界是天然检查点）/ block 当轮 `_block_continue` 返工（返工须 append 新 trace 行）/ 连续 block 3 次升级为 AskUserQuestion 用户裁决。有 sub_steps 节点不用 SUB_DONE（互斥）。**反复重测某子步骤**：`/dl step-reset <n>`（engine reset_sub_step）——回退 sub_step_index=n、删 evidence 里 sub_step>=n 的 skill-trace + gate 行（前序步骤留痕与节点级裁决保留）、清 last_judged_trace 游标与 node_attempts；只在本节点内回退，跨子阶段用 `/dl back`。v2.9（2026-07-26，`designs/subphase-hold-gate-design.md`）：**子阶段门栏 hold_for_gate**（当前仅 understand:1）——末子步骤过门控后**无条件扣留不推进**（state.held_for_gate；不读 state.gate 防中途 /dl gate 预放行泄漏穿栏），唯一出口 `/dl gate`（dl-cmd 检测 held 路由 engine `subgate-pass`：写 manual-subgate-pass 裁决留痕 + 清标记 + 推进）；`/dl step-pass` 末步同被扣（步的放行 ≠ 子阶段的放行）；`step-reset` 清标记。

## 1. 建工作流 / 改工作流

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
- 改 `~/.dl-workflow/output-styles/*.md` 或 `commands/*.md` 或 `skills/` -> 跑 `~/.dl-workflow/install.sh` copy 到 `~/.claude/`，再**重启会话**加载（output-style / slash command 在会话启动时载入）。
- 改 `~/.dl-workflow/scripts/workflow/*.sh` -> 无需 install（launcher 直接从 dl-workflow 内跑），下次 `dl <name> --resume` 或新建即最新。
- 改 `phase-rules.md`（append-system-prompt）-> 仅新开会话生效（append-system-prompt 是启动时载入）；已有会话不同步。
- per-wf `settings.json`（在项目 `.claude/workflows/<name>/`，非快照）改了要重启会话加载。

**与 v1.x 项目内嵌版本对比**：v1.x 里 hook 在 `<项目>/.claude/hooks/` 是 git 快照，改后必须 commit + 重建 worktree；本版本 hook 在 `~/.dl-workflow/hooks/` 直接引用（不 copy），无此约束。

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
| ↑ | `codegraph_gate.py` | PreToolUse H15 门禁（改已有 .py 前先查 codegraph） |
| ↑ | `codegraph_audit.py` | PostToolUse 记 codegraph 查询 |
| `~/.claude/output-styles/` | `workflow.md` | 横幅 + 常驻 TaskList 首要规则 |
| `~/.claude/commands/` | `dl.md` | `/dl` slash 命令入口（调 dl-workflow 内 dl-cmd.sh） |

## 2. ⚠️ 运行诊断手册（按症状查）

### 症状 A：注入没生效（`.wf_phase.log` 无 `injected` 行，或模型说"没有注入"）

日志在**项目根** `<项目>/.claude/.wf_phase.log`（hook 从 payload cwd 反查项目根写入）。

**先分清两种"没生效"**：
- A1. hook **没被调用**（日志无任何新行）
- A2. hook **被调用了**（日志有 `injected`/`no_state`），但模型说没收到

**A1 诊断**：
1. per-wf settings.json 是否含 hook 注册？
   ```bash
   cat <项目>/.claude/workflows/<name>/settings.json | python3 -c "import json,sys;d=json.load(sys.stdin);[print(h['command']) for v in d['hooks'].values() for g in v for h in g['hooks']]"
   ```
   应看到 4 个 `~/.dl-workflow/hooks/*.py` 命令（workflow_phase/workflow_advance/codegraph_gate/codegraph_audit；evidence_append 已于 §8.6c 删除）。缺失 -> `wf_write_settings` 没跑，用 `--resume` 重新起 launcher（会补写 settings）。
2. `~/.dl-workflow/hooks/workflow_phase.py` 存在吗？
   ```bash
   ls -l ~/.dl-workflow/hooks/workflow_phase.py
   ```
   缺失 -> `~/.dl-workflow/install.sh` 没跑或跑失败。

**A2 诊断（关键，易误判）**：注入走 `hook_additional_context` **attachment**，**不在 user message 文本里**。别在 user message 找注入。
```bash
# 查 session jsonl 的 attachment 行
python3 -c "
import json
for line in open('~/.claude/projects/<proj>/<sid>.jsonl'.replace('~',__import__('os').path.expanduser('~'))):
    ev=json.loads(line)
    if ev.get('type')=='attachment':
        a=ev.get('attachment',{})
        if a.get('type')=='hook_additional_context': print('✓ 注入已投递:', str(a.get('content',[''])[0])[:100])
"
```
- attachment 有 `## WORKFLOW 当前阶段` -> **hook 产出 + 投递成功**。但注意投递≠模型收到：ark-code-latest 实测 jsonl 有 attachment 却收不到（见症状 D，用 canary 验）。非 ark 模型此时确系模型遵从问题。
- attachment 无 → hook 没输出 additionalContext，查日志 `workflow_phase.py` 是否走了 `no_state`/`no_project_root` 分支（见症状 C）。

### 症状 B：阶段不自动推进（`### PHASE_DONE` 后没进下一阶段）

**诊断**：看项目根 `.wf_advance.log`。
```bash
tail -5 <项目>/.claude/.wf_advance.log
```
- `no_done_marker|tlen=0` → Stop hook 跑了但 transcript 读出空。**`-p` 模式正常现象**（-p 下 transcript 字段可能空）；交互式应正常。别用 `-p` 验证推进。
- `no_done_marker|tlen=N`（N>0）→ transcript 有内容但没 PHASE_DONE 标记。模型没输出标记。
- `gated_block|phase=understand` → **闸门正常阻断**（understand/plan 需 `/dl gate` 放行）。这是设计行为，非 bug。
- `no_state` → state 没读到（见症状 C）。
- `no_project_root` → hook 没能反查到 git 项目根。检查 cwd 是否在 git 仓库内。

**验证推进**：用真实交互式会话（非 `-p`），给模型可完成的小任务加 `### PHASE_DONE: <phase>`。

### 症状 C：`/dl status` 或 hook 报 "state.json 缺失" / `no_state`

hook 从 payload.cwd 用 `git rev-parse --git-common-dir` 反查主 repo 根。worktree 内 `--git-common-dir` 返回主 repo `.git` 绝对路径 -> `.parent` = 主 repo 根 -> `state.json` 在 `<主 repo>/.claude/workflows/<name>/`。

- 报错 `state.json` 路径若含 `worktrees/<name>/.claude/workflows/` → 反查逻辑错，正确路径不应含 `worktrees/`。检查 `~/.dl-workflow/hooks/workflow_phase.py` 是否有 `_resolve_project_root` 函数（v2.0 引入）；缺失 -> 旧版遗留，在 `~/.dl-workflow` 跑 `git pull` 更新（hooks 不 copy，源即生效；**install.sh 不会更新 hook 脚本**，它只管 settings.json 注册）。
- worktree 是手工建（不是 `dl`）-> state.json 从未建过。用 launcher 建。

### 症状 D：模型否认收到注入（说"没有 hook 注入"/"不在工作流中"）/ 5 阶段横幅、清单不显示

**这是最常踩的坑（ark-code-latest）。** 根因已坐实：**ark-code-latest 收不到 `hook_additional_context` attachment**——hook 触发正常、`injected` 留痕、jsonl 有 attachment 事件，但**内容没进模型上下文**（attachment 被端点/模型侧丢弃）。模型能看到 system-reminder（CLAUDE.md/MEMORY.md）和系统提示（output-style/phase-rules），唯独看不到 `## WORKFLOW 当前阶段` 段。

**判定（canary 法，决定性）**：用 `-p` 直接问模型能否复述注入里的阶段名。
```bash
claude --settings <per-wf settings> --append-system-prompt-file phase-rules.md \
  -p "只回答：你的上下文里是否有一段 '## WORKFLOW 当前阶段' 的注入？有则复述阶段名和 [n/5]，无则答 NO_INJECTION。只复述不调工具。"
```
- 答 `NO_INJECTION` -> **ark 收不到 attachment**（本症状）。别再怀疑 hook 没跑（日志 `injected` 已证 hook 正常）。
- 能复述阶段名 -> attachment 投递正常，问题在 output-style 没加载（见症状 A1/G 查 per-wf settings 的 `outputStyle`）。

**旧陷阱（已修，记录以防回退）**：原 output-style 有静默兜底"找不到 `## WORKFLOW 当前阶段` 就退正常风格"，模型据此假装不在工作流（违反 H13 静默兜底禁令）。**已删**。

**已实现修复（commit f5a6eea，不改 hook、不写文件）**：
1. `output-styles/workflow.md` + `phase-rules.md`：删静默兜底，改"output style 激活即在工作流中"；**看不到注入时模型用 Bash 跑 `bash ~/.dl-workflow/scripts/workflow/dl-cmd.sh status` 自取阶段**（dl-cmd.sh 从 cwd 自动探测工作流名 + 读 state.json，输出 `阶段: 理解和求证问题 [1/5]`）。Bash 输出走模型必读通道，绕过 attachment 投递。
2. `dl-lib.sh` 的 `wf_write_settings` 模板加 `permissions.allow`：`Bash(bash ~/.dl-workflow/scripts/workflow/dl-cmd.sh status:*)` 免提示放行。

**端到端验证**（session eb9749c3）：仅「你好呀」-> 模型自动跑 `dl-cmd.sh status`（allowlist 免提示）-> 输出 `## PHASE: 理解和求证问题 [1/5]` + TaskCreate ×5。

**改 output-style/phase-rules 后生效**：跑 `install.sh` 同步 workflow.md 到 `~/.claude/output-styles/`；**须重启会话**（fresh，非 `--resume`，output-style/append-system-prompt 启动时载入）。旧工作流的 per-wf settings 若缺 allowlist，重新 `dl <name> --resume`（launcher 会用新 `wf_write_settings` 补）或手动加。
### 症状 E：管道 `printf | claude` 测试出 `Execution error`
- "证据链 / evidence / no_markers / evidence.jsonl 不生成 / 证据不落地" -> §2 症状 I
- "子步骤 / sub_steps / STEP_DONE / 子步骤不推进 / evidence 有但不推进" -> §2 症状 J
- "模型不写 evidence / 只输 STEP_DONE 不写 skill-trace / 模型跳过写 evidence" -> §2 症状 K
- "evidence 写到 worktree / evidence 路径错位 / 主仓库无 evidence 但 worktree 有" -> §2 症状 L
- "模型抢答 / 跳过编排 / 覆盖写 evidence / 编造痛点 / 反复确认 / 合并行 / who 出处" -> §2 症状 P（违规模式目录）
- "改判据 / 改 rubric / 一过率低 / judge 判得不对 / 判据太严太松" -> §3.5（rubric 设计方法论）
- "改编排 / SUB_DONE STEP_DONE 打架 / phase-rules 与注入矛盾 / 改门控 checklist" -> §2 症状 M

**测试方法伪问题**，非工作流 bug。管道 EOF 触发 claude 异常。真实 TTY 交互不受影响。
- **别用管道模拟交互会话验证**。用真实 TTY 或 `-p`（注意 -p 下 transcript 不可靠，见症状 B）。

### 症状 F：置顶阶段清单没建 / 不同步（阶段/子阶段任务不显示或状态错）

置顶清单机制：`workflow_phase.py` 每轮注入「任务清单目标状态」块，模型用 `TaskCreate`/`TaskUpdate` 镜像。源真值是 `state.json`（`phase`/`index`/`sub_index`/`sub_total`），任务只做镜像。
清单结构：有子阶段的阶段(understand)紧跟其 1.1..1.N 子任务，共 9 项(1 + 1.1-1.4 + 2-5)；无子阶段的阶段 5 项。
- **首轮无清单**：模型没执行 TaskCreate。检 `.wf_phase.log` 有 `injected` 行 -> 注入到位，问题在模型；`~/.claude/output-styles/workflow.md` 未加载则强规则失效（检 per-wf settings.json 的 `"outputStyle": "workflow"`）。
- **清单状态与当前阶段/子阶段不符**：读注入段「任务清单」看 hook 给的目标状态，与实际 TaskList 对比。目标错 -> hook bug（查 state.json 的 index/sub_index）；目标对但清单错 -> 模型漏 TaskUpdate，用 `/dl status` 促模型下一轮对齐。
- **execute 工作子任务把阶段任务顶掉**：模型违规改了阶段任务(含 1.1-1.4)的 subject/顺序。规则：工作子任务追加在下方，阶段任务及其子任务全程保留。
- **1.1-1.4 顺序错乱**：首轮 TaskCreate 建齐顺序必须是 1, 1.1, 1.2, 1.3, 1.4, 2, 3, 4, 5（靠创建顺序）。旧工作流续接首次建子任务会落底部（边角，已知，用 `/dl jump understand` 触发重建注入无法修，需模型意识到）。
- **显示细节时有时无（如 subject 编号有的会话带、有的不带）**：根因套路 = **subject 契约歧义**——注入（attachment）与 output-style（system-prompt）对 subject 写法措辞不一致时，模型各按各的解读，表现随会话漂移（2026-07-25 实例：注入写 `subject=各阶段中文名`、output-style 枚举却带 `1./1.1` 编号 -> 编号时有时无；修复 commit 5215b63 两通道统一为"编号是 subject 一部分"）。**诊断法（实证模型实际建了什么，别猜）**：
  ```bash
  # 1. 模型实际建的 subject（session jsonl 在 ~/.claude/projects/-...-worktrees-<name>/）
  grep -o '"subject":"[^"]*"' <session>.jsonl | sort -u
  # 2. 注入 attachment 里任务清单块原文（对比契约 vs 实际）
  python3 -c "import json
  for l in open('<session>.jsonl'):
      ev=json.loads(l)
      if ev.get('type')=='attachment' and '任务清单' in str(ev.get('attachment',{}).get('content','')):
          c=str(ev['attachment']['content']); i=c.find('任务清单'); print(c[i:i+600]); break"
  ```
  契约要改时两通道同步改（症状 M checklist），subject 编号纯展示前缀、不动状态镜像逻辑。

### 症状 H：understand 子阶段不推进 / SUB_DONE 无效 / 提前 PHASE_DONE 被阻断

understand 拆 4 子阶段（1.理解问题和背景 / 2.明确目标和价值 / 3.确定范围与约束 / 4.定义成功标准和验收方式），机制与大阶段同构：state.json `sub_index`/`sub_total`；子 1-3 用 `### SUB_DONE: <n>` 推进 sub_index（无闸门）；末子阶段(4)用 `### PHASE_DONE: understand` 触发闸门；未走完子阶段直接 PHASE_DONE 被 Stop hook 守卫阻断。详见 `~/.dl-workflow/designs/understand-subphases-design.md`。

**日志分诊**（项目根 `.wf_advance.log`）：
- `sub_advanced|wf=X|phase=understand|frm=n|to=n+1` -> **正常推进**（子 n -> n+1）。
- `sub_done_no_subphases|phase=<非 understand>` -> 该阶段无子阶段，SUB_DONE 被忽略（模型误用；正常防御）。
- `sub_done_last_ignored|n=4|sub_total=4` -> 末子阶段误用 `SUB_DONE:4`；应用 `PHASE_DONE: understand`。下轮注入自纠。
- `sub_done_mismatch|n=X|sub_index=Y` -> 序号不符（n≠sub_index）不推进，防跳步。看模型是否漏了某子阶段。
- `phase_done_subphases_incomplete|sub_index=n|sub_total=4` -> **守卫正常阻断**：sub_index<4 时提前输出 PHASE_DONE。模型应先依次 SUB_DONE 走完再 PHASE_DONE。**这是设计行为，非 bug**。
- 无子阶段推进相关日志 -> 检 state.json 是否含 sub_index/sub_total 字段（旧 state 无 -> 走无子阶段路径，向后兼容）。

**验证子阶段注入到位**：真实交互 TTY 让模型跑 `bash ~/.dl-workflow/scripts/workflow/dl-cmd.sh status`，输出应含 `子阶段: <label> [n/4]` 行（sub_total=4 时）。或读注入头行是否有 `| 子阶段: **<名>** [n/4]`。

**旧 state.json 迁移**：旧 understand 工作流的 state 无 sub_index/sub_total（在本次改造前建的），hook 默认 sub_total=0 -> 走无子阶段路径（可直接 `PHASE_DONE: understand`）。想让旧工作流用上子阶段：手改 state.json 加 `"sub_index":1,"sub_total":4`，或跳过（新建工作流自然生效）。

### 症状 I：~~证据链不落地~~ 已弃用（§8.6c）+ 新 gate 裁决记录机制 + 编排 skill-trace 证据

> **旧系统已弃用**（2026-07-23）：`### EVIDENCE:{json}` 推理溯源（模型每轮自发记 claim/依赖/证据 + evidence_append.py 解析）已删除。用户决策弃用，理由：transcript 解析脆（no_markers debug 一整节）+ 与"gate 裁决"诉求不符。下列旧排查内容（transcript 目录 / 注入提示 / no_markers 判定）仅作历史记录，新系统不适用。

**新机制（designs/tui-state-machine-design.md §8.6 + §step-advance-on-submit）**：evidence.jsonl 现有两类记录同文件：
1. **gate 裁决**（engine.write_gate_verdict）：`kind=gate`，字段 node/phase/gate=passed/gate_mech/rubric/attempts/commit_sha。block 不写（重试计数在 state.node_attempts，pass 时一并记入）。
2. **skill-trace**（模型写，子步骤编排用）：`kind=skill-trace`，字段 `major_stage`(phase 英文首字母大写，如 Understand) / `minor_stage`(子阶段英文标识，首字母大写驼峰，如 ProblemContext) / `sub_step`(数字) / `skill`(子步骤调用的 skill/工具，Step.ref，模型照抄注入给的当前值) / `purpose` / `q`(字符串数组) / `a`(字符串数组，与 q 按序对齐)。Stop hook 门控时读此找当前 `sub_step==N` 的最新记录（hash 比对触发，症状 J/K/L）。展示用 `dl evidence show <name>`（英文标识转中文，映射 single source 在 engine）。
两类都在主仓库 `<项目>/.claude/evidence/<name>.jsonl`。skill-trace **模型必须用绝对路径写**（相对路径会落 worktree，症状 L）。


**验证 gate 裁决记录落地**：跑一轮让模型过 gate（如完成 understand:4 写 understand.md 后输出 `### PHASE_DONE: understand`），看：
- `.wf_advance.log` 是否 `gate_verdict_written|ev_ok=True`
- `<项目>/.claude/evidence/<name>.jsonl` 是否新增一行 `{"kind":"gate",...}`
- 非该节点（无 gate_mech/gate_rubric 的子阶段）不写记录是正常的

**旧系统残留引用**（designs/evidence-chain-design.md 整文档描述旧系统，已 deprecated；本文档顶部全景图已更新为 4 hook + dl-flow-engine）。

**扩 evidence schema 时的 6 处同步清单**（每次改字段/新增记录 kind 前对照，漏一处即产生"模型按新写、gate 按旧验"半状态期）：

| # | 文件 | 改什么 |
|---|---|---|
| 1 | `hooks/workflow_phase.py` `_format_injection` | 注入模板里的 JSON 示例 + 字段说明行（模型每轮看到的写法契约） |
| 2 | `scripts/workflow/phase-rules.md` | phase-rules 里 evidence 写法示例（output-style，与注入互为补路径） |
| 3 | `dl-flow-engine.py` `sub_step_has_trace` / 其它 evidence 校验函数 | 匹配字段 + docstring；**校验松匹配原则**：只匹 `kind + 关键定位字段`（如 sub_step），不校验其它字段结构 -> 加字段/改子结构不 crash（旧数据能读、新数据能验） |
| 4 | `designs/step-advance-on-submit-design.md` §E4 / 相关设计文档 | 契约文本（H8 真源） |
| 5 | `skills/workflow-creation/SKILL.md`（本文件）| 症状 I 里的字段清单（问题排查读物） |
| 6 | `tests/test_dl_flow_engine.py` fixture | 至少一个新格式测例；旧格式测例保留一个作兼容回归（如 `test_old_step_field_ignored`） |

**顺序建议**：先改 3（校验层松匹配对齐）-> 跑 pytest 确认兼容 -> 再改 1+2+4+5+6。反过来（先改注入不改校验）会让模型按新格式写、gate 读不到 -> block 循环。

**验证**：`pytest -x -q` 全绿 + ruff clean + 项目 `.claude/evidence/<name>.jsonl` 手动重写一条新格式样本（`sub_step_has_trace` 能识别）。

### 症状 J：子步骤编排--模型输 STEP_DONE 但没推进（有 sub_steps 节点专属）

有 `sub_steps` 的节点（当前 understand:1）**推进走 Stop hook**（§substep-gate-at-stop，2026-07-25 起；旧 3a「走 UserPromptSubmit」已废止）。触发 = evidence 里当前子步骤**最新 trace 行 hash 有变化**（state.last_judged_trace 游标比对），不是 transcript。

**先确认协议边界**：模型输 STEP_DONE -> end_turn -> Stop hook 立即判：非末步 pass 推进 + **当轮自动续轮**（additionalContext 指令开做下一子步骤），末步 pass 停轮（子阶段边界），block 则模型**当轮**收到原因返工。**无需用户再发消息**（这是与旧 3a 的核心差别；2026-07-25 起 pass 也不再等用户发「继续」）。两个相关强制：
- **S13 参与围栏**（2026-07-25 起）：当前子步骤**从未写过 trace** 就结束回合 -> `sub_step_engage_block` 强制续轮（「简单查询不走编排」之类的拒执被机械封堵；问用户必须走 AskUserQuestion 回合内完成）。
- 模型 STEP_DONE 后 end_turn 但 evidence 没写/没新行 -> Stop 判「无新 trace」静默放行 -> 不推进（此时看症状 K/L）。

**日志诊断**（项目根 `.wf_advance.log`，关注 `sub_step_gate_pass` / `sub_step_gate_block`）：
```bash
tail -10 <项目>/.claude/.wf_advance.log
```
- `sub_step_gate_pass|step=<N>|to=<N+1>` → **正常推进**。
- `sub_step_gate_block|step=<N>|attempts=<X>|action=block` → judge 判 block，模型当轮返工。看 reason 明确差什么。
- `sub_step_gate_block|...|action=escalate` → 连续 block 达 3 次，模型被指示 AskUserQuestion 请用户裁决（补充信息 / `dl-cmd.sh step-pass` / `/dl back`）。
- 模型 STEP_DONE 后**没有任何** `sub_step_gate_*` 行 → Stop hook 判「无新 trace」：evidence 缺当前子步骤 sub_step==N 的 skill-trace 记录，或新行与已判 hash 相同（模型重写了一遍一字不差的内容）。查 evidence 是否落地 + 路径（症状 L）+ state.json 的 `last_judged_trace` 游标。

**验证 evidence 已落地**：
```bash
cat <项目>/.claude/evidence/<name>.jsonl | python3 -c "
import json,sys
for l in sys.stdin:
    r=json.loads(l)
    if r.get('kind')=='skill-trace': print(f\"sub_step={r.get('sub_step')} purpose={r.get('purpose','')[:40]}\")"
```
- 应看到 `sub_step=<当前 index>` 的行；返工后应看到**多行**同 sub_step（append 协议）。

### 症状 Q：pass 自动续轮没生效（子步骤过了但模型停轮不动）

**根因（2026-07-25 demo 实测）**：Stop hook 的 stdout 被 harness **整体按 JSON 解析**。pass 自动续轮路径若先 `_emit("✓ ...")` 写一行纯文本再写 JSON 指令，解析失败 → `additionalContext` 整段被丢弃（stdout 原文只作为 hook_success 文本展示），模型收不到续轮指令，停轮。block 路径一直是纯 JSON 所以从未暴露——**续轮类输出和 `_emit` 文本混写 stdout 必踩**。

**判定**：session jsonl 里该 Stop 事件只有 `hook_success`（内容含 ✓ 行 + JSON 原文混在一起）、**没有** `hook_additional_context` attachment——对比 block 事件两者都有。

**修复纪律**：Stop hook 里凡返 JSON 指令的路径（`_stop_continue`/`_block_continue`），**stdout 只许纯 JSON**；✓ 等人类可读文本一律走 stderr。防回归测试 `tests/test_workflow_advance.py::TestStopStdoutPureJson`（三路径 stdout 整体 `json.loads` 断言）。

### 症状 K：模型不写 evidence 就输 STEP_DONE（遵从问题，同 attachment 弱遵从教训）

**根因套路**：注入块（attachment）说了强制"写 evidence 再 STEP_DONE"，但模型遵从 attachment 弱于 system-prompt（`phase-rules.md`），跳过写 evidence 直接 STEP_DONE。同 §skill-injection-link §8 教训（"prose 建议被模型当可选"）。

**修复方向（沿用同套路）**：把强制语义从 attachment（注入块）**提升到 phase-rules.md**（system-prompt 通道，遵从强）。当前 phase-rules understand:1 段已含：
- **evidence 强制**：record 子步骤（understand:1 全部 6 步 record=True）必须写 evidence skill-trace 后才许输 STEP_DONE
- **输完 STEP_DONE 即 end_turn**：不连续做下步（Stop hook 在 end_turn 时门控，模型须等判定结果：非末步 pass 则当轮收到下一子步骤指令自动续轮，末步 pass 停轮，block 则当轮返工）

新加编排节点时，同样在 phase-rules 加"写 evidence 是 STEP_DONE 前置"强制，别只在注入里说。

### 症状 O：模型工具调用被围栏拒绝（PreToolUse deny）

围栏有五种（§substep-gate-at-stop S10/S11/S14，2026-07-25 起；S15，2026-07-26 起；另 plan mode 互斥拦 S12），都是**正常触发**不是 bug：

**S15 前置参与围栏**（deny 提示「尚未开始...前置参与围栏窗口」，2026-07-26 起，designs/step-engage-prefence-design.md）：当前子步骤**零 trace 窗口**（一条 skill-trace 都没写）仅编排工具可用——常驻集 AskUserQuestion / Skill / Task* / Read / Grep / Glob / codegraph / dl-cmd / 写 evidence（主仓绝对路径），外加 engine `Step.fence_allow` 步骤声明（当前：子3=Bash/WebFetch、子4=Agent）。为用户任务探查（其它 Bash/WebFetch/WebSearch/Agent）首调即 deny 指回当前子步骤——把 S13 判据前置到工具调用级（demo b01d6507：MiniMax-M3 首回合 Bash 探查抢答，S13 因用户中断没机会开火）。附带拦症状 L：Bash 相对路径写 evidence 会被 deny 并给出绝对路径。与 S10 状态互斥（零 trace vs 未判决 trace）；纯 text 抢答（无工具）仍由 S13 在 Stop 兜底。新编排节点声明 sub_steps 时**必须显式给 fence_allow**（与 ref/purpose 同处，单源）。 v2.11（2026-07-26，designs/autocontinue-fence-notice-design.md）：围栏提示文本单源化到 engine `engagement_fence_notice()`，UserPromptSubmit 注入与 Stop pass/block 续轮双通道同文——此前续轮通道不带豁免文案，模型只在子1 见过无豁免版提示，到子4 臆断 Agent 被 deny 并编造留痕（demo 121320fe）。**模型声称「某工具被围栏 deny」时的验真法**：查 `.wf_fence.log` 有无对应 `engage_fence_deny|tool=<X>` 行 + transcript 有无该工具的 tool_use——都没有=未试先称，按编造处理。

**S10 步骤围栏**（deny 提示「等待门控判决」）：模型写完当前子步骤 evidence 后未 end_turn 就继续调工具（典型：连做下一子步骤探查，demo 会话 3009550c 实录）。围栏与 Stop 门控共用 `last_judged_trace` 游标——judge 判完（pass/block 都记游标）围栏自动开。

**S11 阶段写围栏**（deny 提示「当前阶段禁止写源码/实现」）：understand/plan/review 阶段用 Edit/Write/MultiEdit/NotebookEdit 写白名单外路径（白名单 = 本阶段产物 .md + designs/*.md + .claude/evidence/，单源在 engine `_PHASE_WRITE_NAMES`）。已知限制：Bash 写（重定向/sed -i）不可拦。

**S14 evidence 覆盖守卫**（deny 提示「会覆盖 evidence 丢失 N 行历史记录」）：模型用 Write 覆盖 evidence 而非 append（丢历史行 -> judge 看不到前几轮原话佐证 -> 连环 block + 用户被反复要求重新确认，demo e84aee6d 实录）。Write 目标的 content 必须原样包含全部已有行；正确做法：Bash `printf >>` 或 Read 后拼末尾 Write。

**plan mode 互斥拦**（§S12）：三层防线——①per-wf settings 锁 `defaultMode=acceptEdits`（启动不进 plan；选 acceptEdits 而非 default 是兼顾摩擦——default 下每次 evidence 写/Bash 都弹审批，acceptEdits 写文件静默且 hook deny 优先于 auto-accept，S11 拦得住）②UserPromptSubmit 检测 `permission_mode=="plan"` -> **exit 2 拒掉提问**，stderr 提示用户 shift+tab 切回（用户是唯一能干净退出的人）③fence hook：plan mode 下 deny 一切工具（含 EnterPlanMode 入口本身；仅放行 ExitPlanMode）作 mid-turn 切换兜底。deny 文案引导模型**停止调工具、文本告知用户切模式后 end_turn**——不说「模型 ExitPlanMode」（它被拦得无法探查拿不出计划，会死锁连环拒，demo 61482dbe 实录「改走 plan mode Phase 1」）。

**诊断**：
```bash
tail -5 <项目>/.claude/.wf_fence.log   # fence_deny（S10）/ phase_fence_deny（S11）/ engage_fence_deny（S15）
```
- S10 被拒后模型应输出 `### STEP_DONE: N` + end_turn -> Stop 判定 -> 放行/返工。
- **S10 误伤排查**（模型确实在做当前子步骤的事却被拒）：说明它提前写了 evidence（trace 落盘即被视为完成信号）。纠正：让它输出 STEP_DONE 把这轮判掉（judge block 后游标更新、围栏开、可返工），或 `/dl fence off` 临时关闭。
- **S11 误伤排查**（该写的产物被拒）：查白名单是否漏路径模式（如产物约定改了）-> 改 engine `_PHASE_WRITE_NAMES`（单源），别想着关它——S11 是系统硬约束（同 rubric 黑盒），无开关。
- **确认围栏状态**：state.json `enforce_step_fence`（S10，默认 true，`/dl fence on|off` 切换）。S11 无开关。

**「围栏没拦」分诊（2026-07-26 实录）**：用户报「模型抢答/围栏没生效」时先查两件事，别先怀疑机制——①**会话是否被用户中断**：transcript 有 `[Request interrupted by user]` = 中断不产生 Stop 事件，S13/Stop 门控等 **Stop 类围栏根本没开火**（demo b01d6507：S13 判据满足但用户中途打断，围栏无机会触发）；②**会话模型是谁**：`grep -o '"model":"[^"]*"' <session>.jsonl | sort | uniq -c`，与健康会话模型对照——弱遵从模型（MiniMax-M3）先怀疑遵从失效。机制是否正常的判据：`.wf_phase.log` 有 `injected` + jsonl 有 attachment + settings 齐全 = 机制侧无 bug。

**围栏设计原则**（S15 沉淀，加新围栏前对照）：
1. **触发点尽早**：回合末才拦 = 错误已完整暴露给用户才纠偏。Stop 判据能前置 PreToolUse 就前置（S15 = S13 判据前置，同判据单源在 engine，两处引用）。
2. **白名单按步骤声明，单源在 engine**：黑名单无法定义——同一条命令在 A 步是合法探查、在 B 步是抢答（`ls` 于子3 vs 子1）。`fence_allow` 与 `ref`/`purpose` 同处声明，新编排节点被强制显式思考工具面。
3. **只拦工具拦得住的通道**：text 抢答不可工具拦截（归 Stop 兜底）。为「形式严密」拦 Read 不多拦任何一类违规（模型不 Read 也能编答案），却误伤合法取证与红队子代理。
4. **威胁模型 = 弱遵从而非对抗**：子串匹配级走私面（`codegraph sync && <任意>`）可接受——弱遵从模型不会刻意构造走私命令，只会「顺手跑个 ls」。别为对抗级严密牺牲误伤面。
5. **相邻围栏判据互斥接力**：零 trace（S15 白名单）/ 未判决 trace（S10 全 deny）/ 已判决（自由）三态互斥无空隙——重叠 = 双重 deny 文案打架，空隙 = 无围栏窗口。

**旧工作流（fence 前建的）无围栏**：per-wf settings.json 是 launcher 写的模板，旧 settings 缺 workflow_step_fence.py 注册。`dl <name> --resume` 重起 launcher 会补写 settings（或手加）。

### 症状 N：judge 递归爆炸（claude -p 进程堆积 / 连环 TimeoutExpired）

**症状**：`ps aux | grep "claude -p"` 一堆 judge 进程；`.wf_advance.log` 连环 `gate_block|reason=judge 调用失败（TimeoutExpired）`；evidence 被返工连写多行。

**根因**（2026-07-25 demo 实测）：`run_judge` 的 `claude -p` 子进程继承主会话 cwd（worktree），judge 会话启动加载用户级 hooks -> 它的 Stop 又触发 `gate_sub_step_at_stop` -> 游标未落盘期间看到「新 hash」-> 再生 judge -> 链式爆炸；每个 judge 等子 judge，全员 120s `JUDGE_TIMEOUT` 超时判 block -> 主会话返工写新 trace -> 更多 judge。

**修复**（commit 见 git log「judge cwd」）：`run_judge` subprocess 加 `cwd=tempfile.gettempdir()`——非 git 目录下 hooks 反查不到项目根，静默退出。防回归测试 `TestRunJudgeIsolation::test_judge_cwd_cwd_outside_git_repo`。

**急诊**：先 `pkill -f "claude -p --output-format json 你是工作流节点门控"` 止血，再修 cwd。judge 超时的 block 会计 node_attempts，事故后可用 `/dl step-pass` 或手改 state.json `node_attempts` 归零恢复。

### 症状 P：模型违规模式目录（弱遵从模型实测，MiniMax-M3 @ 2026-07-25）

**元教训：对弱遵从模型，一切关键规则必须硬化——文案=建议（概率遵从，当日实测合规率约 50%），hook=物理。** 当日全部机制（S1 门控 / S10-S15 围栏）都是这个原则的兑现。下表是实测出现的违规模式 → 对应机制（加新机制前先查是否已有覆盖）：

| 违规模式 | 实录 | 对应机制 |
|---|---|---|
| 明示「简单查询不走流程」直接抢答 | 8c51c318 / b01d6507 | S15 前置参与围栏（零 trace 窗口探查工具首调即 deny）+ S13 参与围栏（无 trace 不许结束回合，纯 text 抢答兜底） |
| plan mode 里「改走 plan mode Phase 1」适应而非退出 | 61482dbe | S12 拒提问 + deny 文案指路用户切模式 |
| Write 覆盖 evidence（销毁前轮原话佐证） | e84aee6d | S14 覆盖守卫（全行包含检查） |
| 把用户口语「润色」成书面语记录（判非原话） | bf2516ac | 取证指引（引用原话/会话事实） |
| 知道要件后「填表」：推断补全字段 | e84aee6d | 质量判据黑盒（判「系自行推断」） |
| 编造痛点（「好奇心缺口」「无法判断X」=复述提问） | 4f3d9754 等 | 双结论 rubric（②合法）+ judge 拦伪痛点 |
| 把 ①/② 分支抛给用户投票（随手选与事实矛盾） | bf2516ac | 分支推导规则（事实推导，禁投票） |
| Write 无尾换行 + printf 追加 = 合并行（trace 隐形） | 74f82d93 | raw_decode 容错解析 + S13 分诊 |
| who 拿仓库事实（CLAUDE.md/git config）充当身份出处 | 74f82d93/4f3d9754 | who 出处钉死：只认用户自述 |
| 返工时重问用户已答内容（「一直被要求重新确认」） | e84aee6d/bf2516ac | 取证优先级：上下文原话直接用，真缺才问 |
| 未试先称工具被围栏 deny（臆断无豁免，evidence 编造「Agent blocked by S15 fence」） | 121320fe | pass/block 续轮附 S15 围栏提示含 fence_allow 豁免（v2.11，engine `engagement_fence_notice` 单源）；验真伪：grep `.wf_fence.log` 有无对应 deny 行——无记录=编造 |

### 症状 L：evidence 写到 worktree 路径错位（模型用相对路径）

**根因**：worktree 内 cwd 是 worktree 根，模型用 Bash 相对路径 `cat >> .claude/evidence/<name>.jsonl` 会写到 worktree 内 `.claude/worktrees/<name>/.claude/evidence/<name>.jsonl`。但 **hook 读主仓库** `<主 repo>/.claude/evidence/<name>.jsonl`（evidence 是持久物，per design 进 repo）-> 读不到 -> 不推进。

**诊断**：
```bash
ls -la <主 repo>/.claude/evidence/<name>.jsonl                              # hook 读这里
ls -la <主 repo>/.claude/worktrees/<name>/.claude/evidence/<name>.jsonl     # 模型易写错处
```
- 主仓无 + worktree 有 -> **确诊路径错位**。

**修复**：注入 + phase-rules 双通道强化"必须用主仓库绝对路径，禁用相对路径"。当前 v2.4 已修（commit af69128）：注入块标"绝对路径"+ 写法示例含 `Bash printf >> <绝对路径>`；phase-rules evidence 强制段补"必须写到主仓库绝对路径，禁用相对路径"。

**应急恢复**：把 worktree 的 evidence.jsonl 内容 append 到主仓库对应文件（用户手动或让模型跑 `cat worktree路径 >> 主仓路径`），模型下一轮 end_turn 时 Stop hook 即判到新 trace。

### 症状 M：改编排/skill 强制语义，phase-rules 与注入打架

**通用教训**：编排（engine + hook）改了完成信号/门控规则，`phase-rules.md`（system-prompt，模型必看、优先级高于 attachment）**必须同步改**。否则模型遵从 phase-rules 旧语义，无视新注入。

**典型翻车**（session 5c00dde1）：编排改用 STEP_DONE，但 phase-rules 还说用 SUB_DONE -> 模型按 SUB_DONE 走，STEP_DONE 门控失效。

**改编排 checklist**（每次改 engine sub_steps / gate 语义都过一遍）：
1. `dl-flow-engine.py`：Node.sub_steps / Step.gate / advance 逻辑
2. `workflow_phase.py`：`_format_injection` 的清单块 + 完成标记格式
3. `workflow_advance.py`：Stop 检测的完成信号（若变）
4. **`scripts/workflow/phase-rules.md`**：understand:1 段的完成标记 + 强制语义 -- **最易漏，system-prompt 通道优先级最高，漏改必打架**
5. **`output-styles/workflow.md`**：显示层契约（清单 subject 写法/横幅格式/建齐规则）-- 同为模型强遵从通道；改注入里 TaskList/横幅相关文案时漏改它，会出现"两通道措辞歧义 -> 模型解读随会话漂移"（症状 F 编号实例，commit 5215b63）
6. 冒烟：拿真 worktree + 真 state 跑 `_format_injection`，看注入内容是否与 phase-rules 一致

### 症状 G：install.sh 后 hook 没触发

- `~/.claude/settings.json` 是否含 dl-workflow hook 注册？`grep -c workflow_phase.py ~/.claude/settings.json`。
- Claude Code 会话是**在 install.sh 之前**起的？settings.json 读一次就缓存，需重启会话。
- 项目自己的 `.claude/settings.json` 里有旧的 `python3 .claude/hooks/x.py` 相对路径？会 override 用户级。删项目那份或改为绝对路径。

### 症状 R：「工作流跑太慢 / 程序不应该毫秒级吗」——耗时与 token 审计

**先给概念纠正再给数字**：工作流的确定性程序部分（hooks/engine/围栏/evidence/state）全程 <1s，慢的杠杆永远不在程序优化。实测分解（demo 121320fe ProblemContext，41 分钟工作墙钟）：

| 成分 | 占比 | 性质 |
|---|---|---|
| LLM 生成（48 轮 × 中位 29s，~67 tok/s） | ~71% | 产出物本身就是模型逐字写的分析 |
| judge 判决（11 次） | ~13% | 同为 LLM 推理 |
| 工具执行 + 子代理串行段 | ~15% | 秒级累加 |
| 确定性程序 | <1s | 毫秒级，无可压 |

**审计方法**：§3 #8（transcript 位置/去重/窗口归集/生成速率）+ §3 #11（报错盘点）。**优化排序**：①消浪费（假冲突循环/子代理嵌套/盲猜/撞围栏——通常占 20-30%，先于一切结构调整）；②轮数（block 循环 = +1-2 轮/次，自查提示 §3.5 #9 前移到自查抓）；③输出冗长度（墙钟 ≈ 输出 token ÷ 生成速率，线性）。**底线**：给定模型的 tok/s 与遵从率决定水位（ark 实测 6 步带门控 ~25-35m 属正常）；要数量级提速只有换更快/更强模型，不是调程序。

## 3. 排查方法论（systematic-debugging 适配）

排查工作流问题按此顺序：

1. **先看日志，别猜**：项目根 `.wf_phase.log`（注入）、`.wf_advance.log`（推进 + gate 裁决记录 `gate_verdict_written`/`gate_block`）。2. **分清"没调用"vs"调用了没投递"vs"投递了模型不遵循"**：三层次，日志+attachment 分别诊断（症状 A1/A2/D）。
3. **看 session jsonl 的 attachment**：注入真相在 `hook_additional_context` attachment，不在 user message。但**投递到 jsonl ≠ 模型收到**--ark-code-latest 实测 jsonl 有 attachment 却进不了上下文（症状 D）。怀疑时用 canary `-p` 问模型能否复述阶段名直接验。
4. **install 状态优先怀疑**：任何"改了不生效"，检 `~/.dl-workflow/hooks/` 是否含 _resolve_project_root（git pull 后即最新，无副本同步问题）。
5. **验证用真实交互，别用管道/-p**：管道有 Execution error（症状 E），-p transcript 不可靠（症状 B）。
- "证据链 / evidence / no_markers / evidence.jsonl 不生成 / 证据不落地" -> §2 症状 I
6. **grep 命中 ≠ 模型真输出**：transcript 里 `### PHASE_DONE` / `### SUB_DONE` / `### STEP_DONE` 命中可能是注入的 attachment 文本，必须按 `role=assistant` 过滤后再判模型是否真发了标记。
7. **有 sub_steps 节点特殊**：看 `.wf_advance.log` 的 `sub_step_gate_pass` / `sub_step_gate_block`（Stop hook 判，与无 sub_steps 节点同日志）；推进在模型 end_turn 时即判，**无需用户再发消息**。同时看 `<主 repo>/.claude/evidence/<name>.jsonl` 是否有当前 `sub_step==N` 的新 skill-trace（症状 J/L）+ state.json 的 `last_judged_trace` 游标。
8. **量 token / 审计模型消耗**：主会话 transcript 在 `~/.claude/projects/-...-worktrees-<name>/<session_id>.jsonl`；judge 会话在 `~/.claude/projects/-tmp/`（run_judge cwd=tempdir 的直接证据），按 `.wf_advance.log` 的 `sub_step_gate_block|...|ts` / `sub_step_gate_pass|...|ts` 时间戳找相邻 `-tmp/*.jsonl` 配对。**usage 必须按 message.id 去重**：同一响应的 thinking/text 分块各记一行 assistant、usage 整份重复，按行求和会虚增一倍；`queue-operation` 不是 API 调用。口径：`input_tokens`=新鲜输入（cache_read 单列），模型归属看每条 assistant 的 `model` 字段（judge 继承主会话 provider env，正常必与主会话同模型）。 **子代理 transcript**（红队等 Agent）：在 `~/.claude/projects/<proj>/<session_id>/subagents/agent-*.jsonl`（以 session id 命名的独立目录；主文件 `isSidechain` 全 false，别在主文件找）。嵌套子代理同目录并列，靠时间戳归属父代理。**按子步骤归集耗时/token**：以 `.wf_advance.log` 的 pass/block 事件时间戳为窗口边界，去重后 usage 按窗口分桶；注意日志是本地时、jsonl 是 UTC（+8 换算）。**生成速率测量**：相邻 assistant 消息间隔中位 ≈ 单轮生成耗时（ark 实测 ~67 tok/s、29s/轮）——「工作流慢」的量化口径。
9. **测 hook 用真 git worktree，别用普通子目录**（2026-07-25 冒烟实测）：`git rev-parse --git-common-dir` 在 repo 内普通子目录返**相对路径**（`../../../.git`）→ state 解析错位、hook 静默退出（无日志、无输出，极像「hook 没跑」）；只有 `git worktree add` 的真 worktree 返绝对路径。模板：`tests/test_workflow_advance.py`（in-process importlib 加载 hook + monkeypatch engine.run_judge 避免真起 judge 子进程 + tmp_path 真 worktree）。
11. **报错全量盘点法**（2026-07-26 demo 104 报错根因链）：扫 tool_result `is_error`——主会话 + `subagents/agent-*.jsonl` 全部子代理，tool_use_id 回联工具名，按错误内容 Counter 归并成类。**主会话报错常只是冰山一角**（实录 5 vs 子代理 99）——子代理是报错主战场，盘点漏了它就等于漏了根因。归并后才看得见结构性（93/104 同属「子代理工具现实与 prompt 指引脱节」一条链）；逐条看只会得到「偶发很多」的错觉。
10. **hook 行为冒烟不必开真会话**（2026-07-26 S15 验证法）：hook 全是 stdin JSON -> stdout JSON 契约，拿**真实工作流 state** 直接喂 payload 即见行为——`echo '{"cwd":"<worktree路径>","tool_name":"Bash","tool_input":{"command":"ls"}}' | python3 ~/.dl-workflow/hooks/workflow_step_fence.py`。改围栏/门控后必做：比开交互会话便宜，且用真实 state 覆盖「fixture 与真实数据形态漂移」盲区（测试 fixture 绿 ≠ 真实 state 下对）。

## 3.5 门控判据（rubric）设计方法论（改判据/写新 gate 前必读）

2026-07-25 全天 demo 实测沉淀。改任何 `Step.gate` / `gate_rubric` / judge prompt 前对照：

1. **三层分工，各判各的**：机械层判存在性（trace/hash，零成本短路）；judge 判**结构完整性**（覆盖度/对齐/引用/形式）——judge 没有项目上下文，**判得了结构、判不了真值**；真值与认可度归用户（读回确认 / 升级裁决）。别让 judge 判它判不了的东西（如「真实问题已逼出」——它无法验证）。
2. **防 Goodhart 分层**：形式要件（格式/覆盖度）可以披露给模型（进 purpose，降形式性返工）；质量判据（可观察/非编造/非空泛）**只留 gate 黑盒**。全披露 = 模型照 checklist 填表，judge 分辨力丧失（Goodhart 定律）。方法论指引（怎么取证）进 purpose，评判标准进 gate，单源常量绑定。
3. **判据必须接受「问题不成立」为合法结论**（双结论制）：只认「问题成立」的 rubric 会让诚实答案（无痛点/纯好奇）永远过不了，**逼模型编造痛点**（「好奇心缺口」式伪痛点实测被 judge 识破）。放②的判据 = 原话佐证 + 结论标记；区分「诚实无痛点」vs「懒得挖」的判据是原话佐证。
4. **裁量点必钉死**：judge 也是模型，同一证据可不同判决（who 出处三次两拒一过实测）。发现「同类证据一过一拒」→ 立即把该点写成死规则（who 出处只认用户自述；仓库事实不能证明提问者身份）。**判据留白的每一寸都是方差**。
5. **判词要指路**：block reason 不只说缺什么，还要指明返工方向（建议哪条分支/补哪类）——模型按判词一次修好，零提问返工是健康标杆。
6. **一过率不是目标，健康返工才是**：健康 = 返工 ≤1 个定向问题或零提问、绝不重问已答内容。block 有信号价值（实测一次 block 把「随便查查」逼成真问题）——门控从不 block 时要怀疑它失效，而不是庆幸。
7. **判据要求的佐证形式必须存在低成本合法获取路径**（2026-07-25 子1 校准）：要求「用户否认痛点的原话」但用户几乎不会主动声明 → 模型不敢问/没想到问就只剩编造一条路，block 循环。修法不是松判据，是**打通「问→引」路径**：purpose 强制「材料不足先 AskUserQuestion 事实性补问」+ gate 明示「补问的回答原话是合法佐证、从未被问及的『未提及』不算」。审查新判据时多问一句：模型拿到这个要求的合法证据，最便宜的正确动作是什么？如果答案是「没有」，判据本身就是在逼编造。
8. **校准看 block 性质，不看频率**（2026-07-25 子1 四连 block 案例）：高频 block 不是松绑信号，先逐条分类——形式缺失/覆盖不足/编造自述 = **该抓**（门控在工作，说明模型在试图绕过）；「要求的佐证没有合法获取路径」= **判据缺陷**（见 #7）。只有后者改判据。n=1 的 block 率不构成校准依据；step2 一过而 step1 四连 block 的不对称，正确读法是「两次判得都对」，不是「一个太严一个太松」。 完整工作示例（demo 121320fe）：用户直觉「6 次 block、零一过率=问题很大」-> 逐条核对判词 vs purpose/证据 -> 6/6「该抓」（4 次违反已披露形式要求、1 次系统缺陷诱发、1 次实质越界）、0 判据缺陷 -> 结论：不动判据，修的是披露缺口+自查提示（#9）。

9. **区分「知识失败」与「注意力失败」**（2026-07-26 demo 121320fe 复盘）：模型被指后一轮就修好 = 它**知道**规则只是没用上（注意力失败）——这类 block 的最便宜解法不是改判据，而是**提交前自查提示**（engine `STEP_SELFCHECK_HINT` 单源，pass 续轮/block 返工/注入三通道同文）：把「judge 抓」前移为「自查抓」，省 judge 调用 + 省一轮 Stop 往返。反之，反复讲仍犯 = 知识/能力失败，自查提示无效，只能机械拦或换模型。判据要求了但 purpose 没披露的形式要件（demo 子4「汇总声明不算记录」）属披露缺口——补上即可，属 #2 的应用，不算松判据。

## 4. 不要做的事

- ❌ **手改 hook 逻辑**：应直接改 `~/.dl-workflow/hooks/*.py`（git 跟踪），`git pull` 即生效，无副本同步。
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

- "建工作流 / 新建工作流 / dl 命令" → §1
- "注入没生效 / 阶段没注入 / 模型说没注入" → §2 症状 A/D
- "阶段不推进 / PHASE_DONE 没推进" → §2 症状 B
- "/dl 报错 / state 缺失 / state.json not found" → §2 症状 C
- "install.sh 后没生效 / hook 没触发" → §2 症状 G
- "模型否认注入 / 不输出横幅 / 5 阶段不显示" -> §2 症状 D（ark 收不到 attachment）
- "阶段清单不显示 / TaskList 状态错 / 1.1-1.4 顺序错 / 编号时有时无 / subject 不对" → §2 症状 F
- "子阶段 / SUB_DONE / understand 子阶段不推进 / 提前 PHASE_DONE 被阻断" → §2 症状 H
- "Execution error / 管道测试" → §2 症状 E
- "跑太慢 / 耗时长 / token 消耗大 / 程序应该毫秒级 / 成本审计" → §2 症状 R
- "证据链 / evidence / no_markers / evidence.jsonl 不生成 / 证据不落地" -> §2 症状 I
