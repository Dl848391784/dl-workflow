---
name: workflow-creation
description: 建工作流系统 + 运行诊断。触发：新建/改工作流、ac-ark --workflow、阶段不推进、注入没生效、/wf 报错、hook 装错位置、模型否认收到注入。
version: 2.0
---

# workflow-creation

> 建工作流 + 运行诊断手册。自包含。真源 = `~/.dl-workflow/designs/workflow-system-design.md`。
> **dl-workflow 版本核心事实**：hook / skill / output-style / command 装在**用户级** `~/.claude/`（`install.sh` copy 而来），跨所有项目生效。不再是「项目内 git 快照」——改 hook 后 `install.sh` 一跑即时更新，**无需重建 worktree**（这是与 v1.x 项目内嵌版本的关键差别）。

## 0. 系统全景（5 秒理解）

```
ac-ark --workflow <name>  ─►  ~/.dl-workflow/scripts/workflow/wf-launch.sh
                                  │ 建 git worktree(<项目>/.claude/worktrees/<name>, 分支 wf/<name>)
                                  │ + state.json(<项目>/.claude/workflows/<name>/) + 钉 session
                                  │ 起 claude: --settings(per-wf) --append-system-prompt-file(phase-rules) --session-id
                                  ▼
   原生 claude TUI（worktree 内 cwd）
     ├─ ~/.claude/hooks/workflow_phase.py    (UserPromptSubmit) → 注入「## WORKFLOW 当前阶段」到 hook_additional_context attachment
     ├─ ~/.claude/output-styles/workflow.md  → 引导模型输出 ## PHASE: <中文名> [n/5] + 维护 TaskList 常驻清单
     ├─ ~/.claude/hooks/workflow_advance.py  (Stop) → 检 ### PHASE_DONE 标记 → 闸门判定 → 推进 state
     └─ /wf status|next|back|jump|gate|done  → ~/.dl-workflow/scripts/workflow/wf-cmd.sh
```

**5 阶段**：understand 理解和求证问题（禁改源码）-> plan 生成执行计划（禁改源码）-> execute 执行 -> review 审核结果 -> evolution 进化。显示用中文名，逻辑层（state/PHASE_DONE/jump）用英文标识。
**推进**：自动 + 闸门。`understand->plan`、`plan->execute` 需 `/wf gate` 放行；其余自动推进。

## 1. 建工作流 / 改工作流

### 1.1 新建一个工作流（用户侧）
```bash
ac-ark --workflow <name>              # 新建（停在 understand）
ac-ark --workflow <name> --resume     # 续接
ac-ark --workflow list                # 列举
ac-ark --workflow <name> --done       # 归档（删 worktree+分支+元数据）
```
- `<name>` 仅小写字母/数字/连字符/下划线，≤64（`wf-lib.sh` 校验）。
- 必须在 git repo 内运行（launcher 用 `git rev-parse` 反查项目根）。

### 1.2 改工作流脚本/hook/command 后
- 改 `~/.dl-workflow/hooks/*.py` 或 `output-styles/*.md` 或 `commands/*.md` -> 跑 `~/.dl-workflow/install.sh` copy 到 `~/.claude/`，**下轮 hook 触发即最新版**（无需重建 worktree）。
- 改 `~/.dl-workflow/scripts/workflow/*.sh` -> 无需 install（launcher 直接从 dl-workflow 内跑），下次 `ac-ark --workflow <name> --resume` 或新建即最新。
- 改 `phase-rules.md`（append-system-prompt）-> 仅新开会话生效（append-system-prompt 是启动时载入）；已有会话不同步。
- per-wf `settings.json`（在项目 `.claude/workflows/<name>/`，非快照）改了要重启会话加载。

**与 v1.x 项目内嵌版本对比**：v1.x 里 hook 在 `<项目>/.claude/hooks/` 是 git 快照，改后必须 commit + 重建 worktree；本版本 hook 在 `~/.claude/hooks/` 由 install.sh 管，无此约束。

### 1.3 关键文件职责（改前必读）
| 位置 | 文件 | 职责 |
|---|---|---|
| `~/.dl-workflow/scripts/workflow/` | `wf-launch.sh` | 建/续 worktree+state+settings，起 claude |
| ↑ | `wf-lib.sh` | 阶段定义 + state 读写 + `wf_write_settings` + 路径反查 |
| ↑ | `wf-cmd.sh` | `/wf` 子命令逻辑 |
| ↑ | `phase-rules.md` | append-system-prompt，各阶段行为规则 |
| `~/.claude/hooks/` （install 后） | `workflow_phase.py` | UserPromptSubmit 注入当前阶段 |
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
   应看到 4 个 `~/.claude/hooks/*.py` 命令。缺失 -> `wf_write_settings` 没跑，用 `--resume` 重新起 launcher（会补写 settings）。
2. `~/.claude/hooks/workflow_phase.py` 存在吗？
   ```bash
   ls -l ~/.claude/hooks/workflow_phase.py
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
- attachment 有 `## WORKFLOW 当前阶段` → **注入成功**，问题在模型（见症状 D）。
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

- 报错 `state.json` 路径若含 `worktrees/<name>/.claude/workflows/` → 反查逻辑错，正确路径不应含 `worktrees/`。检查 `~/.claude/hooks/workflow_phase.py` 是否有 `_resolve_project_root` 函数（v2.0 引入）；缺失 -> 旧版遗留，重跑 install.sh 覆盖。
- worktree 是手工建（不是 `ac-ark --workflow`）-> state.json 从未建过。用 launcher 建。

### 症状 D：模型否认收到注入（说"没有 hook 注入"/"不在工作流中"）

**判定**：先按症状 A2 确认 attachment 已投递。若 attachment 有注入但模型否认 → 模型遵从问题。
- 部分模型（如 ark-code-latest）能读 `hook_additional_context` attachment，但有时**逻辑上否认注入存在**。
- output style 的对策：`~/.claude/output-styles/workflow.md` 明确"注入在 attachment，见 `## WORKFLOW 当前阶段` 段落即须遵循，禁止声称没有注入"。若模型仍否认 -> 换模型或改用 `/wf status` 显式命令让模型看到当前阶段。

### 症状 E：管道 `printf | claude` 测试出 `Execution error`

**测试方法伪问题**，非工作流 bug。管道 EOF 触发 claude 异常。真实 TTY 交互不受影响。
- **别用管道模拟交互会话验证**。用真实 TTY 或 `-p`（注意 -p 下 transcript 不可靠，见症状 B）。

### 症状 F：置顶阶段清单没建 / 不同步（5 阶段任务不显示或状态错）

置顶清单机制：`workflow_phase.py` 每轮注入「任务清单目标状态」块，模型用 `TaskCreate`/`TaskUpdate` 镜像。源真值是 `state.json`，任务只做镜像。
- **首轮无清单**：模型没执行 TaskCreate。检 `.wf_phase.log` 有 `injected` 行 -> 注入到位，问题在模型；`~/.claude/output-styles/workflow.md` 未加载则强规则失效（检 per-wf settings.json 的 `"outputStyle": "workflow"`）。
- **清单状态与当前阶段不符**：读注入段「任务清单」5 行看 hook 给的目标状态，与实际 TaskList 对比。目标错 -> hook bug（查 state.json 的 index）；目标对但清单错 -> 模型漏 TaskUpdate，用 `/wf status` 促模型下一轮对齐。
- **execute 工作子任务把 5 阶段任务顶掉**：模型违规改了 5 阶段任务的 subject/顺序。规则：工作子任务追加在下方，5 个阶段任务全程保留。

### 症状 G：install.sh 后 hook 没触发

- `~/.claude/settings.json` 是否含 dl-workflow hook 注册？`grep -c workflow_phase.py ~/.claude/settings.json`。
- Claude Code 会话是**在 install.sh 之前**起的？settings.json 读一次就缓存，需重启会话。
- 项目自己的 `.claude/settings.json` 里有旧的 `python3 .claude/hooks/x.py` 相对路径？会 override 用户级。删项目那份或改为绝对路径。

## 3. 排查方法论（systematic-debugging 适配）

排查工作流问题按此顺序：

1. **先看日志，别猜**：项目根 `.wf_phase.log`（注入）、`.wf_advance.log`（推进）。
2. **分清"没调用"vs"调用了没投递"vs"投递了模型不遵循"**：三层次，日志+attachment 分别诊断（症状 A1/A2/D）。
3. **看 session jsonl 的 attachment**：注入真相在 `hook_additional_context` attachment，不在 user message。
4. **install 状态优先怀疑**：任何"改了不生效"，检 `~/.claude/hooks/` 与 `~/.dl-workflow/hooks/` 的 diff（`diff -rq`），差了就 `install.sh` 覆盖。
5. **验证用真实交互，别用管道/-p**：管道有 Execution error（症状 E），-p transcript 不可靠（症状 B）。

## 4. 不要做的事

- ❌ **手改 `~/.claude/hooks/`**：应改 `~/.dl-workflow/hooks/` 后 `install.sh` 覆盖，不然 upgrade 会丢改动。
- ❌ **用 `-p` 验证推进**：-p 下 transcript 可能空，Stop hook 读不到 PHASE_DONE。
- ❌ **在 user message 文本里找注入**：注入在 `hook_additional_context` attachment。
- ❌ **用 `printf | claude` 验证交互行为**：Execution error 伪问题。
- ❌ **同时在项目级和用户级注册同一 hook**：会双跑或路径解析错。删项目级注册，只留用户级（install.sh 装的）。

## 5. 触发关键词速查

- "建工作流 / 新建工作流 / ac-ark --workflow" → §1
- "注入没生效 / 阶段没注入 / 模型说没注入" → §2 症状 A/D
- "阶段不推进 / PHASE_DONE 没推进" → §2 症状 B
- "/wf 报错 / state 缺失 / state.json not found" → §2 症状 C
- "install.sh 后没生效 / hook 没触发" → §2 症状 G
- "模型否认注入 / 不输出横幅" → §2 症状 D
- "阶段清单不显示 / TaskList 状态错" → §2 症状 F
- "Execution error / 管道测试" → §2 症状 E
