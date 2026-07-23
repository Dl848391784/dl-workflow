---
name: workflow-creation
description: 建工作流系统 + 运行诊断。触发：新建/改工作流、dl 命令、阶段不推进、注入没生效、/wf 报错、hook 装错位置、模型否认收到注入、5 阶段不显示、证据链(evidence)不落地/no_markers。
version: 2.2
---

# workflow-creation

> 建工作流 + 运行诊断手册。自包含。真源 = `~/.dl-workflow/designs/workflow-system-design.md`。
> **dl-workflow 版本核心事实**：跨所有项目生效，装在**用户级**。两类 artifacts 装法不同：
> - **skill / output-style / command**：`install.sh` **copy** 到 `~/.claude/`（Claude Code 硬编码加载路径）。改后跑 `install.sh` 重 copy + 重启会话加载。
> - **hooks（5 个 .py）**：**不 copy**，`settings.json` 直接引用 `~/.dl-workflow/hooks/*.py` 源（shell 执行时展开 `~`）。改 hook 源后 `git pull` 即生效，**连 `install.sh` 都不用，更无需重建 worktree**——这是与 v1.x 项目内嵌版本的关键差别（v1.x 里 hook 是 worktree 内 git 快照，改后必须 commit + 重建 worktree）。

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
     ├─ ~/.dl-workflow/hooks/workflow_advance.py (Stop) → 检 ### PHASE_DONE 标记 → 闸门判定 → 推进 state
     ├─ ~/.dl-workflow/hooks/evidence_append.py (Stop, 第二个) -> 检 ### EVIDENCE:{json} 标记 -> 分配 canonical id + 戳 commit_sha -> append <项目>/.claude/evidence/<name>.jsonl（推导证据链，见 designs/evidence-chain-design.md + 症状 I）
     └─ /wf status|next|back|jump|gate|done  → ~/.dl-workflow/scripts/workflow/wf-cmd.sh
```

**5 阶段**：understand 理解和求证问题（禁改源码）-> plan 生成执行计划（禁改源码）-> execute 执行 -> review 审核结果 -> evolution 进化。显示用中文名，逻辑层（state/PHASE_DONE/jump）用英文标识。
**understand 含 4 子阶段**（依次自动推进，无子阶段闸门）：1.理解问题和背景 / 2.明确目标和价值 / 3.确定范围与约束 / 4.定义成功标准和验收方式。子 1-3 完成各输出 `### SUB_DONE: <n>`（Stop hook 推进 sub_index）；末子阶段(4) 写 understand.md 后输出 `### PHASE_DONE: understand` 触发 understand->plan 闸门。未走完子阶段直接 PHASE_DONE 会被守卫阻断。详见 `designs/understand-subphases-design.md`。
**推进**：自动 + 闸门。`understand->plan`、`plan->execute` 需 `/wf gate` 放行；其余自动推进。

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
| ↑ | `evidence_append.py` | Stop（第二个）检 `### EVIDENCE:{json}` 追加证据链到 `<项目>/.claude/evidence/<name>.jsonl`（见 designs/evidence-chain-design.md） |
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
   应看到 5 个 `~/.dl-workflow/hooks/*.py` 命令。缺失 -> `wf_write_settings` 没跑，用 `--resume` 重新起 launcher（会补写 settings）。
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

### 症状 I：证据链不落地 / `.wf_evidence.log` 一直 `no_markers` / `.claude/evidence/<name>.jsonl` 不生成

证据链系统（designs/evidence-chain-design.md）：模型在回复末尾输出 `### EVIDENCE:{json}` 标记，Stop hook `evidence_append.py` 解析后追加到 `<项目>/.claude/evidence/<name>.jsonl`。日志在**项目根** `<项目>/.claude/.wf_evidence.log`。

**先分清 `no_markers` 是不是真问题**（最易误判，本次排查踩过）：
- `no_markers|tlen=0` -> transcript 读出空。看 transcript_path 是否指向真会话（见下「transcript 找错目录」）。
- `no_markers|tlen=N`（N>0）-> transcript 有内容但**当前轮 assistant 文本里无 `### EVIDENCE:` 标记**。**多数情况是正常的**：模型按注入提示"非结论性回复可不发 / 仅当推导出新结论时输出"语义合规未发。understand 元讨论轮次、纯查证轮次不发是设计行为，非 bug。要见节点须走到有具体结论的轮次（execute 实现 / review 判定）。

**排查三步（按序）**：

1. **transcript 找对目录了吗**（本次排查第一坑）：
   - worktree 会话的 transcript 落在**独立项目目录** `~/.claude/projects/-<项目路径编码>--claude-worktrees-<name>/`，**不在主项目目录** `-<项目路径编码>/`。
   - demo 的 transcript 在 `~/.claude/projects/-...-worktrees-demo/<sid>.jsonl`，别在 `~/.claude/projects/-...-factor-ic-analyzer/` 找（那里没有 `wf/<name>` session 的 jsonl）。
   - session_id 取自 state.json 的 `session_id` 字段；worktree 项目目录名 = 主项目路径编码 + `--claude-worktrees-<name>`（`/` -> `-`）。

2. **注入提示生效了吗**（本次排查第二坑：注入渠道缺口已修）：
   - `workflow_phase.py` `_format_injection` 必须含「推导证据链」提示块（告诉模型 `### EVIDENCE:{json}` 格式 + 何时输出）。
   - 验：真会话 transcript 的 `attachment` 行（`type=hook_additional_context`）里应能 `grep` 到 `### EVIDENCE:` 字样（那是注入的提示文本）。
   - **误判陷阱**：`grep "### EVIDENCE" <transcript>` 命中 ≠ 模型真输出了标记。命中可能是注入的 attachment 文本。必须遍历 `role=assistant` 的消息文本判模型是否真发了（attachment 的 role 不是 assistant）。

3. **`_last_assistant_text` 取到的是当前轮吗**（已修，commit 5b7bf01）：
   - 旧实现取「全局最后一条 assistant 文本」，会漏同轮较早 assistant 消息里的标记（一条 user 后模型可能发多条 assistant）。
   - 现 `evidence_append.py._last_assistant_text_io` 扫「当前轮」= 最后一条 user 之后所有 assistant 文本。若仍漏，检 hook 是否最新版（`git -C ~/.dl-workflow pull`，hooks 不 copy 源即生效）。

**真验证节点落地**：走完一轮让模型推结论（如 execute 实现完输出 `### EVIDENCE:{...,"claim_type":"conclusion",...}`），看 `<项目>/.claude/evidence/<name>.jsonl` 是否新增一行 + `.wf_evidence.log` 是否 `appended|n=1`。

### 症状 G：install.sh 后 hook 没触发

- `~/.claude/settings.json` 是否含 dl-workflow hook 注册？`grep -c workflow_phase.py ~/.claude/settings.json`。
- Claude Code 会话是**在 install.sh 之前**起的？settings.json 读一次就缓存，需重启会话。
- 项目自己的 `.claude/settings.json` 里有旧的 `python3 .claude/hooks/x.py` 相对路径？会 override 用户级。删项目那份或改为绝对路径。

## 3. 排查方法论（systematic-debugging 适配）

排查工作流问题按此顺序：

1. **先看日志，别猜**：项目根 `.wf_phase.log`（注入）、`.wf_advance.log`（推进）、`.wf_evidence.log`（证据链）。
2. **分清"没调用"vs"调用了没投递"vs"投递了模型不遵循"**：三层次，日志+attachment 分别诊断（症状 A1/A2/D）。
3. **看 session jsonl 的 attachment**：注入真相在 `hook_additional_context` attachment，不在 user message。但**投递到 jsonl ≠ 模型收到**--ark-code-latest 实测 jsonl 有 attachment 却进不了上下文（症状 D）。怀疑时用 canary `-p` 问模型能否复述阶段名直接验。
4. **install 状态优先怀疑**：任何"改了不生效"，检 `~/.dl-workflow/hooks/` 是否含 _resolve_project_root（git pull 后即最新，无副本同步问题）。
5. **验证用真实交互，别用管道/-p**：管道有 Execution error（症状 E），-p transcript 不可靠（症状 B）。
- "证据链 / evidence / no_markers / evidence.jsonl 不生成 / 证据不落地" -> §2 症状 I
6. **grep 命中 ≠ 模型真输出**：transcript 里 `### EVIDENCE` / `### PHASE_DONE` 命中可能是注入的 attachment 文本，必须按 `role=assistant` 过滤后再判模型是否真发了标记（症状 I）。

## 4. 不要做的事

- ❌ **手改 hook 逻辑**：应直接改 `~/.dl-workflow/hooks/*.py`（git 跟踪），`git pull` 即生效，无副本同步。
- ❌ **用 `-p` 验证推进**：-p 下 transcript 可能空，Stop hook 读不到 PHASE_DONE。
- ❌ **在 user message 文本里找注入**：注入在 `hook_additional_context` attachment。
- ❌ **用 `printf | claude` 验证交互行为**：Execution error 伪问题。
- ❌ **同时在项目级和用户级注册同一 hook**：会双跑或路径解析错。删项目级注册，只留用户级（install.sh 装的）。
- ❌ **在主项目目录找 worktree 会话的 transcript**：worktree 会话 transcript 在独立目录 `~/.claude/projects/-...-worktrees-<name>/`，非主项目目录。按 state.json 的 session_id + worktree 路径编码找（症状 I）。
- ❌ **见 `no_markers` 就当 bug**：多数是模型按"非结论性回复不发"语义合规未发标记。先判 transcript 取对没、注入生效没、当前轮有无真结论，再下结论（症状 I）。

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
