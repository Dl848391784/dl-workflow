---
name: workflow-creation
description: 建工作流系统 + 运行诊断。触发：新建/改工作流、dl 命令、阶段不推进、注入没生效、/wf 报错、hook 装错位置、模型否认收到注入、5 阶段不显示、gate 裁决记录(evidence)不落地、子步骤编排(sub_steps/STEP_DONE) 不推进、evidence 写到 worktree。
version: 2.4
---

# workflow-creation

> 建工作流 + 运行诊断手册。自包含。真源 = `~/.dl-workflow/designs/workflow-system-design.md`。
> **dl-workflow 版本核心事实**：跨所有项目生效，装在**用户级**。两类 artifacts 装法不同：
> - **skill / output-style / command**：`install.sh` **copy** 到 `~/.claude/`（Claude Code 硬编码加载路径）。改后跑 `install.sh` 重 copy + 重启会话加载。
> - **hooks（4 个 .py）**：**不 copy**，`settings.json` 直接引用 `~/.dl-workflow/hooks/*.py` 源（shell 执行时展开 `~`）。改 hook 源后 `git pull` 即生效，**连 `install.sh` 都不用，更无需重建 worktree**——这是与 v1.x 项目内嵌版本的关键差别（v1.x 里 hook 是 worktree 内 git 快照，改后必须 commit + 重建 worktree）。

## 0. 系统全景（5 秒理解）

```
dl <name>  ─►  ~/.dl-workflow/scripts/workflow/wf-launch.sh
                                  │ 建 git worktree(<项目>/.claude/worktrees/<name>, 分支 wf/<name>)
                                  │ + state.json(<项目>/.claude/workflows/<name>/) + 钉 session
                                  │ 起 claude: --settings(per-wf) --append-system-prompt-file(phase-rules) --session-id
                                  ▼
   原生 claude TUI（worktree 内 cwd）
     ├─ ~/.dl-workflow/hooks/workflow_phase.py   (UserPromptSubmit) → 注入「## WORKFLOW 当前阶段」到 hook_additional_context attachment
     ├─ ~/.claude/output-styles/workflow.md  → 引导模型输出 ## PHASE: <中文名> [n/5] + 维护 TaskList 常驻清单
     │     ⚠ 注入走 attachment，部分模型（ark-code-latest）收不到；output-style 已加 fallback：看不到注入时模型用 Bash 跑 wf-cmd.sh status 自取阶段（allowlist 免提示）。见症状 D
     ├─ ~/.dl-workflow/hooks/workflow_advance.py (Stop) -> 委托 dl-flow-engine.run_gate（机械+judge）；检完成信号(### PHASE_DONE/SUB_DONE) -> pass 推进 / block 返 additionalContext 续轮(模型自动重试)
     ├─ ~/.dl-workflow/dl-flow-engine.py (编排内核,被 hook 咨询) -> 节点树+gate判据+推进 唯一真源；gate-pass 时 write_gate_verdict 写 kind=gate 裁决记录到 evidence/<name>.jsonl（替代旧 ### EVIDENCE 溯源，§8.6c）
     └─ /wf status|next|back|jump|gate|done  → ~/.dl-workflow/scripts/workflow/wf-cmd.sh
```

**5 阶段**：understand 理解和求证问题（禁改源码）-> plan 生成执行计划（禁改源码）-> execute 执行 -> review 审核结果 -> evolution 进化。显示用中文名，逻辑层（state/PHASE_DONE/jump）用英文标识。
**understand 含 4 子阶段**（依次自动推进，无子阶段闸门）：1.理解问题和背景 / 2.明确目标和价值 / 3.确定范围与约束 / 4.定义成功标准和验收方式。子 1-3 完成各输出 `### SUB_DONE: <n>`（Stop hook 推进 sub_index）；末子阶段(4) 写 understand.md 后输出 `### PHASE_DONE: understand` 触发 understand->plan 闸门。未走完子阶段直接 PHASE_DONE 会被守卫阻断。详见 `designs/understand-subphases-design.md`。
**推进**：自动 + 闸门。`understand->plan`、`plan->execute` 需 `/wf gate` 放行；其余自动推进。

**子步骤编排（v2.4，§node-step-orchestration + §step-advance-on-submit）**：某些子阶段（当前仅 understand:1）声明 `sub_steps`--有序子步骤序列（调 skill / 调工具，各有 purpose + record + gate）。**门控单位 = 子步骤**（不是子阶段级 rubric）；**skill 内部 Q/A 不门控**只 record。understand:1 = 4 子步骤（子1 逼问定义 / 子2 搜证据 / 子3 一句话陈述 / 子4 读回确认），子1/2/3 gate 校验 evidence 里的 skill-trace，子4 gate=None 自动过。**推进机制特殊**：不走 Stop hook（transcript flush 竞态），走 UserPromptSubmit --用户**下次提问**时 hook 读 `<项目>/.claude/evidence/<name>.jsonl` 找当前子步骤的 `{"kind":"skill-trace","sub_step":N,...}` 记录 -> gate judge -> 过则推进 sub_step_index / block 则注入重做。模型完成一步的协议：**先写 evidence（主仓库绝对路径）-> 输 `### STEP_DONE: <n>` -> end_turn 等用户**。有 sub_steps 节点不用 SUB_DONE（互斥）。

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
- `<name>` 仅小写字母/数字/连字符/下划线，≤64（`wf-lib.sh` 校验）。
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
| `~/.dl-workflow/scripts/workflow/` | `wf-launch.sh` | 建/续 worktree+state+settings，起 claude |
| ↑ | `wf-lib.sh` | 阶段定义 + state 读写 + `wf_write_settings` + 路径反查 |
| ↑ | `wf-cmd.sh` | `/wf` 子命令逻辑 |
| ↑ | `phase-rules.md` | append-system-prompt，各阶段行为规则 |
| `~/.dl-workflow/hooks/`            | `workflow_phase.py` | UserPromptSubmit 注入当前阶段 |
| ↑ | `workflow_advance.py` | Stop 检 PHASE_DONE 推进 |
| ↑ | `codegraph_gate.py` | PreToolUse H15 门禁（改已有 .py 前先查 codegraph） |
| ↑ | `codegraph_audit.py` | PostToolUse 记 codegraph 查询 |
| `~/.claude/output-styles/` | `workflow.md` | 横幅 + 常驻 TaskList 首要规则 |
| `~/.claude/commands/` | `wf.md` | `/wf` slash 命令入口（调 dl-workflow 内 wf-cmd.sh） |

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
- `gated_block|phase=understand` → **闸门正常阻断**（understand/plan 需 `/wf gate` 放行）。这是设计行为，非 bug。
- `no_state` → state 没读到（见症状 C）。
- `no_project_root` → hook 没能反查到 git 项目根。检查 cwd 是否在 git 仓库内。

**验证推进**：用真实交互式会话（非 `-p`），给模型可完成的小任务加 `### PHASE_DONE: <phase>`。

### 症状 C：`/wf status` 或 hook 报 "state.json 缺失" / `no_state`

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
1. `output-styles/workflow.md` + `phase-rules.md`：删静默兜底，改"output style 激活即在工作流中"；**看不到注入时模型用 Bash 跑 `bash ~/.dl-workflow/scripts/workflow/wf-cmd.sh status` 自取阶段**（wf-cmd.sh 从 cwd 自动探测工作流名 + 读 state.json，输出 `阶段: 理解和求证问题 [1/5]`）。Bash 输出走模型必读通道，绕过 attachment 投递。
2. `wf-lib.sh` 的 `wf_write_settings` 模板加 `permissions.allow`：`Bash(bash ~/.dl-workflow/scripts/workflow/wf-cmd.sh status:*)` 免提示放行。

**端到端验证**（session eb9749c3）：仅「你好呀」-> 模型自动跑 `wf-cmd.sh status`（allowlist 免提示）-> 输出 `## PHASE: 理解和求证问题 [1/5]` + TaskCreate ×5。

**改 output-style/phase-rules 后生效**：跑 `install.sh` 同步 workflow.md 到 `~/.claude/output-styles/`；**须重启会话**（fresh，非 `--resume`，output-style/append-system-prompt 启动时载入）。旧工作流的 per-wf settings 若缺 allowlist，重新 `dl <name> --resume`（launcher 会用新 `wf_write_settings` 补）或手动加。
### 症状 E：管道 `printf | claude` 测试出 `Execution error`
- "证据链 / evidence / no_markers / evidence.jsonl 不生成 / 证据不落地" -> §2 症状 I
- "子步骤 / sub_steps / STEP_DONE / 子步骤不推进 / evidence 有但不推进" -> §2 症状 J
- "模型不写 evidence / 只输 STEP_DONE 不写 skill-trace / 模型跳过写 evidence" -> §2 症状 K
- "evidence 写到 worktree / evidence 路径错位 / 主仓库无 evidence 但 worktree 有" -> §2 症状 L
- "改编排 / SUB_DONE STEP_DONE 打架 / phase-rules 与注入矛盾 / 改门控 checklist" -> §2 症状 M

**测试方法伪问题**，非工作流 bug。管道 EOF 触发 claude 异常。真实 TTY 交互不受影响。
- **别用管道模拟交互会话验证**。用真实 TTY 或 `-p`（注意 -p 下 transcript 不可靠，见症状 B）。

### 症状 F：置顶阶段清单没建 / 不同步（阶段/子阶段任务不显示或状态错）

置顶清单机制：`workflow_phase.py` 每轮注入「任务清单目标状态」块，模型用 `TaskCreate`/`TaskUpdate` 镜像。源真值是 `state.json`（`phase`/`index`/`sub_index`/`sub_total`），任务只做镜像。
清单结构：有子阶段的阶段(understand)紧跟其 1.1..1.N 子任务，共 9 项(1 + 1.1-1.4 + 2-5)；无子阶段的阶段 5 项。
- **首轮无清单**：模型没执行 TaskCreate。检 `.wf_phase.log` 有 `injected` 行 -> 注入到位，问题在模型；`~/.claude/output-styles/workflow.md` 未加载则强规则失效（检 per-wf settings.json 的 `"outputStyle": "workflow"`）。
- **清单状态与当前阶段/子阶段不符**：读注入段「任务清单」看 hook 给的目标状态，与实际 TaskList 对比。目标错 -> hook bug（查 state.json 的 index/sub_index）；目标对但清单错 -> 模型漏 TaskUpdate，用 `/wf status` 促模型下一轮对齐。
- **execute 工作子任务把阶段任务顶掉**：模型违规改了阶段任务(含 1.1-1.4)的 subject/顺序。规则：工作子任务追加在下方，阶段任务及其子任务全程保留。
- **1.1-1.4 顺序错乱**：首轮 TaskCreate 建齐顺序必须是 1, 1.1, 1.2, 1.3, 1.4, 2, 3, 4, 5（靠创建顺序）。旧工作流续接首次建子任务会落底部（边角，已知，用 `/wf jump understand` 触发重建注入无法修，需模型意识到）。

### 症状 H：understand 子阶段不推进 / SUB_DONE 无效 / 提前 PHASE_DONE 被阻断

understand 拆 4 子阶段（1.理解问题和背景 / 2.明确目标和价值 / 3.确定范围与约束 / 4.定义成功标准和验收方式），机制与大阶段同构：state.json `sub_index`/`sub_total`；子 1-3 用 `### SUB_DONE: <n>` 推进 sub_index（无闸门）；末子阶段(4)用 `### PHASE_DONE: understand` 触发闸门；未走完子阶段直接 PHASE_DONE 被 Stop hook 守卫阻断。详见 `~/.dl-workflow/designs/understand-subphases-design.md`。

**日志分诊**（项目根 `.wf_advance.log`）：
- `sub_advanced|wf=X|phase=understand|frm=n|to=n+1` -> **正常推进**（子 n -> n+1）。
- `sub_done_no_subphases|phase=<非 understand>` -> 该阶段无子阶段，SUB_DONE 被忽略（模型误用；正常防御）。
- `sub_done_last_ignored|n=4|sub_total=4` -> 末子阶段误用 `SUB_DONE:4`；应用 `PHASE_DONE: understand`。下轮注入自纠。
- `sub_done_mismatch|n=X|sub_index=Y` -> 序号不符（n≠sub_index）不推进，防跳步。看模型是否漏了某子阶段。
- `phase_done_subphases_incomplete|sub_index=n|sub_total=4` -> **守卫正常阻断**：sub_index<4 时提前输出 PHASE_DONE。模型应先依次 SUB_DONE 走完再 PHASE_DONE。**这是设计行为，非 bug**。
- 无子阶段推进相关日志 -> 检 state.json 是否含 sub_index/sub_total 字段（旧 state 无 -> 走无子阶段路径，向后兼容）。

**验证子阶段注入到位**：真实交互 TTY 让模型跑 `bash ~/.dl-workflow/scripts/workflow/wf-cmd.sh status`，输出应含 `子阶段: <label> [n/4]` 行（sub_total=4 时）。或读注入头行是否有 `| 子阶段: **<名>** [n/4]`。

**旧 state.json 迁移**：旧 understand 工作流的 state 无 sub_index/sub_total（在本次改造前建的），hook 默认 sub_total=0 -> 走无子阶段路径（可直接 `PHASE_DONE: understand`）。想让旧工作流用上子阶段：手改 state.json 加 `"sub_index":1,"sub_total":4`，或跳过（新建工作流自然生效）。

### 症状 I：~~证据链不落地~~ 已弃用（§8.6c）+ 新 gate 裁决记录机制 + 编排 skill-trace 证据

> **旧系统已弃用**（2026-07-23）：`### EVIDENCE:{json}` 推理溯源（模型每轮自发记 claim/依赖/证据 + evidence_append.py 解析）已删除。用户决策弃用，理由：transcript 解析脆（no_markers debug 一整节）+ 与"gate 裁决"诉求不符。下列旧排查内容（transcript 目录 / 注入提示 / no_markers 判定）仅作历史记录，新系统不适用。

**新机制（designs/tui-state-machine-design.md §8.6 + §step-advance-on-submit）**：evidence.jsonl 现有两类记录同文件：
1. **gate 裁决**（engine.write_gate_verdict）：`kind=gate`，字段 node/phase/gate=passed/gate_mech/rubric/attempts/commit_sha。block 不写（重试计数在 state.node_attempts，pass 时一并记入）。
2. **skill-trace**（模型写，子步骤编排用）：`kind=skill-trace`，字段 `major_stage`(phase 英文名) / `minor_stage`(子阶段序号) / `sub_step` / `purpose` / `q`(字符串数组) / `a`(字符串数组，与 q 按序对齐)。UserPromptSubmit 推进时读此找当前 `sub_step==N` 的记录（症状 J/K/L）。
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

有 `sub_steps` 的节点（当前 understand:1）**推进不走 Stop hook，走 UserPromptSubmit**（§step-advance-on-submit 方案 3a）。推进 = 用户**下次提问**触发。

**先确认协议边界**：模型输 STEP_DONE 后本轮 end_turn，state.sub_step_index **本轮不变**。要看到推进，**必须用户再发一条消息**--这是设计（非 bug）。

**日志诊断**（项目根 `.wf_phase.log`，关注 `sub_step_advanced` / `sub_step_block`）：
```bash
tail -10 <项目>/.claude/.wf_phase.log
```
- `sub_step_advanced|to=<N+1>` → **正常推进**。
- `sub_step_block|step=<N>|reason=<...>` → gate judge 判 block，模型需重做该子步骤（注入含 block hint）。看 reason 明确差什么。
- 用户下次提问后**没** `sub_step_advanced` 也**没** `sub_step_block` → 说明 `sub_step_has_trace` 返回 False（evidence 缺当前子步骤 sub_step==N 的 skill-trace 记录）。查 evidence 是否落地 + 路径是否正确（症状 L）。

**验证 evidence 已落地**：
```bash
cat <项目>/.claude/evidence/<name>.jsonl | python3 -c "
import json,sys
for l in sys.stdin:
    r=json.loads(l)
    if r.get('kind')=='skill-trace': print(f\"sub_step={r.get('sub_step')} purpose={r.get('purpose','')[:40]}\")"
```
- 应看到 `sub_step=<当前 index>` 的行。

### 症状 K：模型不写 evidence 就输 STEP_DONE（遵从问题，同 attachment 弱遵从教训）

**根因套路**：注入块（attachment）说了强制"写 evidence 再 STEP_DONE"，但模型遵从 attachment 弱于 system-prompt（`phase-rules.md`），跳过写 evidence 直接 STEP_DONE。同 §skill-injection-link §8 教训（"prose 建议被模型当可选"）。

**修复方向（沿用同套路）**：把强制语义从 attachment（注入块）**提升到 phase-rules.md**（system-prompt 通道，遵从强）。当前 phase-rules understand:1 段已含：
- **evidence 强制**：record 子步骤（子1/2/3）必须写 evidence skill-trace 后才许输 STEP_DONE
- **输完 STEP_DONE 即 end_turn**：不连续做下步（方案 3a 推进滞后一轮需模型等）

新加编排节点时，同样在 phase-rules 加"写 evidence 是 STEP_DONE 前置"强制，别只在注入里说。

### 症状 L：evidence 写到 worktree 路径错位（模型用相对路径）

**根因**：worktree 内 cwd 是 worktree 根，模型用 Bash 相对路径 `cat >> .claude/evidence/<name>.jsonl` 会写到 worktree 内 `.claude/worktrees/<name>/.claude/evidence/<name>.jsonl`。但 **hook 读主仓库** `<主 repo>/.claude/evidence/<name>.jsonl`（evidence 是持久物，per design 进 repo）-> 读不到 -> 不推进。

**诊断**：
```bash
ls -la <主 repo>/.claude/evidence/<name>.jsonl                              # hook 读这里
ls -la <主 repo>/.claude/worktrees/<name>/.claude/evidence/<name>.jsonl     # 模型易写错处
```
- 主仓无 + worktree 有 -> **确诊路径错位**。

**修复**：注入 + phase-rules 双通道强化"必须用主仓库绝对路径，禁用相对路径"。当前 v2.4 已修（commit af69128）：注入块标"绝对路径"+ 写法示例含 `Bash printf >> <绝对路径>`；phase-rules evidence 强制段补"必须写到主仓库绝对路径，禁用相对路径"。

**应急恢复**：把 worktree 的 evidence.jsonl 内容 append 到主仓库对应文件（用户手动或让模型跑 `cat worktree路径 >> 主仓路径`），下次提问就能推进。

### 症状 M：改编排/skill 强制语义，phase-rules 与注入打架

**通用教训**：编排（engine + hook）改了完成信号/门控规则，`phase-rules.md`（system-prompt，模型必看、优先级高于 attachment）**必须同步改**。否则模型遵从 phase-rules 旧语义，无视新注入。

**典型翻车**（session 5c00dde1）：编排改用 STEP_DONE，但 phase-rules 还说用 SUB_DONE -> 模型按 SUB_DONE 走，STEP_DONE 门控失效。

**改编排 checklist**（每次改 engine sub_steps / gate 语义都过一遍）：
1. `dl-flow-engine.py`：Node.sub_steps / Step.gate / advance 逻辑
2. `workflow_phase.py`：`_format_injection` 的清单块 + 完成标记格式
3. `workflow_advance.py`：Stop 检测的完成信号（若变）
4. **`scripts/workflow/phase-rules.md`**：understand:1 段的完成标记 + 强制语义 -- **最易漏，system-prompt 通道优先级最高，漏改必打架**
5. 冒烟：拿真 worktree + 真 state 跑 `_format_injection`，看注入内容是否与 phase-rules 一致

### 症状 G：install.sh 后 hook 没触发

- `~/.claude/settings.json` 是否含 dl-workflow hook 注册？`grep -c workflow_phase.py ~/.claude/settings.json`。
- Claude Code 会话是**在 install.sh 之前**起的？settings.json 读一次就缓存，需重启会话。
- 项目自己的 `.claude/settings.json` 里有旧的 `python3 .claude/hooks/x.py` 相对路径？会 override 用户级。删项目那份或改为绝对路径。

## 3. 排查方法论（systematic-debugging 适配）

排查工作流问题按此顺序：

1. **先看日志，别猜**：项目根 `.wf_phase.log`（注入）、`.wf_advance.log`（推进 + gate 裁决记录 `gate_verdict_written`/`gate_block`）。
2. **分清"没调用"vs"调用了没投递"vs"投递了模型不遵循"**：三层次，日志+attachment 分别诊断（症状 A1/A2/D）。
3. **看 session jsonl 的 attachment**：注入真相在 `hook_additional_context` attachment，不在 user message。但**投递到 jsonl ≠ 模型收到**--ark-code-latest 实测 jsonl 有 attachment 却进不了上下文（症状 D）。怀疑时用 canary `-p` 问模型能否复述阶段名直接验。
4. **install 状态优先怀疑**：任何"改了不生效"，检 `~/.dl-workflow/hooks/` 是否含 _resolve_project_root（git pull 后即最新，无副本同步问题）。
5. **验证用真实交互，别用管道/-p**：管道有 Execution error（症状 E），-p transcript 不可靠（症状 B）。
- "证据链 / evidence / no_markers / evidence.jsonl 不生成 / 证据不落地" -> §2 症状 I
6. **grep 命中 ≠ 模型真输出**：transcript 里 `### PHASE_DONE` / `### SUB_DONE` / `### STEP_DONE` 命中可能是注入的 attachment 文本，必须按 `role=assistant` 过滤后再判模型是否真发了标记。
7. **有 sub_steps 节点特殊**：不看 `.wf_advance.log`（Stop hook 不管子步骤推进），看 `.wf_phase.log` 的 `sub_step_advanced` / `sub_step_block`；推进需**用户下次提问**触发（方案 3a）。同时看 `<主 repo>/.claude/evidence/<name>.jsonl` 是否有当前 `sub_step==N` 的 skill-trace（症状 J/L）。

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
- ❌ **有 sub_steps 节点期待"模型输 STEP_DONE 立即推进"**：方案 3a 推进滞后到用户下次提问（避开 transcript flush 竞态）。要看推进，用户须再发一条消息（症状 J）。

## 5. 触发关键词速查

- "建工作流 / 新建工作流 / dl 命令" → §1
- "注入没生效 / 阶段没注入 / 模型说没注入" → §2 症状 A/D
- "阶段不推进 / PHASE_DONE 没推进" → §2 症状 B
- "/wf 报错 / state 缺失 / state.json not found" → §2 症状 C
- "install.sh 后没生效 / hook 没触发" → §2 症状 G
- "模型否认注入 / 不输出横幅 / 5 阶段不显示" -> §2 症状 D（ark 收不到 attachment）
- "阶段清单不显示 / TaskList 状态错 / 1.1-1.4 顺序错" → §2 症状 F
- "子阶段 / SUB_DONE / understand 子阶段不推进 / 提前 PHASE_DONE 被阻断" → §2 症状 H
- "Execution error / 管道测试" → §2 症状 E
- "证据链 / evidence / no_markers / evidence.jsonl 不生成 / 证据不落地" -> §2 症状 I
