# 运行诊断手册（按症状查）

> workflow-creation skill 按需参考（自 SKILL.md §2 整体迁出，节号原样保留以兼容「§3.5 #9」式交叉引用）。
> 只在 SKILL.md 路由表命中时阅读。


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
- "交接提示没生效 / nudge 被无视 / 上下文单调膨胀零锯齿 / 提示触发了但没执行" -> 症状 W

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
1. **gate 裁决**（engine.write_gate_verdict）：`kind=gate`，字段 node/phase/gate=passed/gate_mech/rubric/attempts/commit_sha + **major_stage/minor_stage**（2026-07-27 起，与 skill-trace 结构字段对齐；取值单源 node.phase/node.minor_key，整阶段节点 minor_stage=null）。block 不写（重试计数在 state.node_attempts，pass 时一并记入）。
2. **skill-trace**（模型写，子步骤编排用）：`kind=skill-trace`，字段 `major_stage`(phase 英文首字母大写，如 Understand) / `minor_stage`(子阶段英文标识，首字母大写驼峰，如 ProblemContext) / `sub_step`(数字) / `skill`(子步骤调用的 skill/工具，Step.ref，模型照抄注入给的当前值) / `purpose` / `q`(字符串数组) / `a`(字符串数组，与 q 按序对齐)。Stop hook 门控时读此找当前 `sub_step==N` 的最新记录（hash 比对触发，症状 J/K/L）。展示用 `dl evidence show <name>`（英文标识转中文，映射 single source 在 engine）。
两类都在主仓库 `<项目>/.claude/evidence/<name>.jsonl`。skill-trace **v2.14 起走 `append-trace`**：载荷 = 分节标记文本（v2.58 `.trace-payload-<name>.md`，【purpose】【q】【a】零转义——模型零接触 JSON；推荐先 `append-trace --scaffold` 起骨架填「待填」，v2.57），再 Bash `dl_flow_engine.py append-trace --from-file <载荷>`——结构字段（kind/major_stage/minor_stage/sub_step/skill）脚本从 state 填、格式/路径归脚本，手写 JSONL 的 5 类事故（相对路径/覆盖/合并行/写碎/结构字段抄错）根治；直写 jsonl 被 S14 围栏 deny（v2.14 收编）。子代理报告收录走 `append-trace --ingest-agent <task-id>`（v2.60，禁手工粘贴）；产物装配走 `render-artifact`（v2.59/62，禁手写 understand.md/plan.md/design.md）；读回材料走 `render-readback`（v2.61）。**旧 q/a 平行数组写侧 v2.35 起硬拒**（对齐正确也拒，指路 qa 配对——过渡桥只服务凭旧惯性写的漂移模型，tail_volume plan:3 子5 q=11 a=7 实例）；evidence 记录 schema 不变（读侧不受影响）。旧「模型手写绝对路径」写法仅作历史（症状 L）。


**验证 gate 裁决记录落地**：跑一轮让模型过 gate（如完成 understand:4 写 understand.md 后输出 `### PHASE_DONE: understand`），看：
- `.wf_advance.log` 是否 `gate_verdict_written|ev_ok=True`
- `<项目>/.claude/evidence/<name>.jsonl` 是否新增一行 `{"kind":"gate",...}`
- 非该节点（无 gate_mech/gate_rubric 的子阶段）不写记录是正常的

**旧系统残留引用**（designs/evidence-chain-design.md 整文档描述旧系统，已 deprecated；本文档顶部全景图已更新为 4 hook + dl_flow_engine）。

**扩 evidence schema 时的 6 处同步清单**（每次改字段/新增记录 kind 前对照，漏一处即产生"模型按新写、gate 按旧验"半状态期）：

| # | 文件 | 改什么 |
|---|---|---|
| 1 | `hooks/workflow_phase.py` `_format_injection` | 注入模板里的 JSON 示例（模板行 + ✓正例/✗反例，模型每轮看到的写法契约） |
| 2 | `scripts/workflow/phase-rules.md` | phase-rules 里 evidence 写法示例（output-style，与注入互为补路径） |
| 3 | `dl_flow_engine.py` `sub_step_has_trace` / 其它 evidence 校验函数 | 匹配字段 + docstring；**校验松匹配原则**：只匹 `kind + 关键定位字段`（如 sub_step），不校验其它字段结构 -> 加字段/改子结构不 crash（旧数据能读、新数据能验） |
| 4 | `designs/step-advance-on-submit-design.md` §E4 / 相关设计文档 | 契约文本（H8 真源） |
| 5 | `skills/workflow-creation/SKILL.md`（本文件）| 症状 I 里的字段清单（问题排查读物） |
| 6 | `tests/test_dl_flow_engine.py` fixture | 至少一个新格式测例；旧格式测例保留一个作兼容回归（如 `test_old_step_field_ignored`） |

**顺序建议**：先改 3（校验层松匹配对齐）-> 跑 pytest 确认兼容 -> 再改 1+2+4+5+6。反过来（先改注入不改校验）会让模型按新格式写、gate 读不到 -> block 循环。

**验证**：`pytest -x -q` 全绿 + ruff clean + 项目 `.claude/evidence/<name>.jsonl` 手动重写一条新格式样本（`sub_step_has_trace` 能识别）。

### 症状 J：子步骤编排--模型输 STEP_DONE 但没推进（有 sub_steps 节点专属）

有 `sub_steps` 的节点（当前 understand:1）**推进走 Stop hook**（§substep-gate-at-stop，2026-07-25 起；旧 3a「走 UserPromptSubmit」已废止）。触发 = evidence 里当前子步骤**最新 trace 行 hash 有变化**（state.last_judged_trace 游标比对），不是 transcript。

**「没推进」主诉先分诊推进失败 vs 停轮检查点**（2026-07-27，demo 907fee09）：state.json 的 sub_index **已翻**但模型不动 = 停轮检查点（末步停轮/门栏扣留，设计行为），不是推进失败——检查日志会有 `sub_step_gate_pass|step=末|to=1`；sub_index **未翻**才按下方日志链排查。同理「没进下一子阶段」：state 已进 + 模型停轮 = 旧规则末步停轮（2026-07-27 起无门栏边界已改自动续轮；该日前建的会话仍可能停在边界，发「继续」即走）。再同理「plan:4 门栏放行后没推进」：**放行 ≠ 推进是设计行为**（门栏唯一处 = plan:4，2026-07-28 起——understand:2/3/4、plan:1/2/3 门栏与 understand->plan 闸门已全部撤除）——subgate-pass 只清 held 不 advance_state，state 停在 plan:4 等模型 PHASE_DONE: plan 撞 plan->execute 大闸门（需第二次 /dl gate）；注入第三态（✓ 放行待产物）是正常显示，别当卡死排查。

**先确认协议边界**：模型输 STEP_DONE -> end_turn -> Stop hook 立即判：非末步 pass 推进 + **当轮自动续轮**（additionalContext 指令开做下一子步骤），末步 pass 时——无门栏且下一子阶段有编排则**跨子阶段自动续轮**进其子1（2026-07-27 起），门栏节点末步扣留停轮（等 /dl gate），无编排边界停轮，block 则模型**当轮**收到原因返工。**无需用户再发消息**（这是与旧 3a 的核心差别；2026-07-25 起 pass 也不再等用户发「继续」）。两个相关强制：
- **S13 参与围栏**（2026-07-25 起）：当前子步骤**从未写过 trace** 就结束回合 -> `sub_step_engage_block` 强制续轮（「简单查询不走编排」之类的拒执被机械封堵；问用户必须走 AskUserQuestion 回合内完成）。
  - **假性 block 子场景**（2026-08-05，tail_volume u:1 子3 实证）：模型派**后台 agent**（`tool=Agent tool_dispatch_* outcome=ok durationMs≈4` = 非阻塞后台派发）后、agent 未归前 end_turn -> trace 必然未落 -> S13 判「无 trace」block。这不是模型拒执，是「在等 agent 的途中结束回合」。**诊断**：block 时刻查 transcript 有无 pending Agent tool_use（`name=="Agent"` 的 tool_use_id 减去已配对的 `tool_result` 的 `tool_use_id`，差集非空 = pending）。**且先查有无 TaskOutput 被 S15 deny**（fence_allow 漏配，模型本来在用 TaskOutput 等 agent 被拦才抢跑，见症状 O 围栏原则 #7）--这才是根因，pending 检测/延后门控只是兜底。**修法**：子3/子4 fence_allow 加 TaskOutput（模型用 harness 原生机制阻塞等 agent 归来再写 trace，零抢跑）。
- 模型 STEP_DONE 后 end_turn 但 evidence 没写/没新行 -> Stop 判「无新 trace」静默放行 -> 不推进（此时看症状 K/L）。

**日志诊断**（项目根 `.wf_advance.log`，关注 `sub_step_gate_pass` / `sub_step_gate_block`）：
```bash
tail -10 <项目>/.claude/.wf_advance.log
```
- `sub_step_gate_pass|step=<N>|to=<N+1>` → **正常推进**。
- `sub_step_gate_block|step=<N>|attempts=<X>|action=block` → judge 判 block，模型当轮返工。看 reason 明确差什么。
- `sub_step_gate_block|...|action=escalate` → 连续 block 达 3 次，模型被指示 AskUserQuestion 请用户裁决（补充信息 / `dl-cmd.sh step-pass` / `/dl back`）。
- 模型 STEP_DONE 后**没有任何** `sub_step_gate_*` 行 → Stop hook 判「无新 trace」：evidence 缺当前子步骤 sub_step==N 的 skill-trace 记录，或新行与已判 hash 相同（模型重写了一遍一字不差的内容）。查 evidence 是否落地 + 路径（症状 L）+ state.json 的 `last_judged_trace` 游标。
  - **特例（v2.13 corrupt-rework-detect，2026-07-26，demo d59d05ea）**：模型返工把 trace **写碎**（shell 单引号内塞字面换行 -> JSON 跨两行；字面 `\"` 原样落盘）→ 最新**合法** trace 仍等于已判 hash。旧行为：同 hash 静默放行 -> 模型以为返工完成、流程看似卡死无日志。现行为：engine `corrupt_trace_after_latest` 检测「最新合法 trace 之后存在含 `"sub_step":N` 子串但解析不出的行」-> 判 block 并返格式修复指引（单行合法 JSON），计 attempts（连续损坏达阈值同样升级用户裁决）。**只数最新合法 trace 之后的损坏行**——之前的碎片是已处理历史，模型修好后不重复报警。诊断：`python3 -c "…engine.corrupt_trace_after_latest(root, name, N)"` 或看 `.wf_advance.log` 是否出现 `reason=evidence 写入损坏`。

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
- **输完 STEP_DONE 即 end_turn**：不连续做下步（Stop hook 在 end_turn 时门控，模型须等判定结果：非末步 pass 则当轮收到下一子步骤指令自动续轮，末步 pass 时无门栏且下一子阶段有编排则跨子阶段自动续轮、门栏节点末步扣留停轮，block 则当轮返工）

新加编排节点时，同样在 phase-rules 加"写 evidence 是 STEP_DONE 前置"强制，别只在注入里说。

### 症状 O：模型工具调用被围栏拒绝（PreToolUse deny）

> ⚠ **「围栏」术语消歧**（2026-07-28 会话实测歧义一次）：本症状是**工具围栏**（PreToolUse deny，S10-S15）；用户说「围栏/拦住不往下走」也可能指**推进围栏**——子阶段门栏（`hold_for_gate` 扣留等 /dl gate，现唯一处 = plan:4）与阶段大闸门（GATED_AFTER，现仅 plan->execute）。改「什么时候停」= 推进围栏（走症状 M 改编排 checklist 的「门栏/闸门位置变更专项」）；改「什么工具能用」= 工具围栏（本症状）。动手前先确认指哪个。

围栏有五种（§substep-gate-at-stop S10/S11/S14，2026-07-25 起；S15，2026-07-26 起；另 plan mode 互斥拦 S12），都是**正常触发**不是 bug：

**S15 前置参与围栏**（deny 提示「尚未开始...前置参与围栏窗口」，2026-07-26 起，designs/step-engage-prefence-design.md）：当前子步骤**零 trace 窗口**（一条 skill-trace 都没写）仅编排工具可用——常驻集 AskUserQuestion / Skill / Task* / Read / Grep / Glob / codegraph / dl-cmd / 写 evidence（主仓绝对路径），外加 engine `Step.fence_allow` 步骤声明（当前：子3=Bash/Agent/TaskOutput、子4=Agent/TaskOutput）。为用户任务探查（其它 Bash/WebFetch/WebSearch/Agent）首调即 deny 指回当前子步骤——把 S13 判据前置到工具调用级（demo b01d6507：MiniMax-M3 首回合 Bash 探查抢答，S13 因用户中断没机会开火）。附带拦症状 L：Bash 相对路径写 evidence 会被 deny 并给出绝对路径。与 S10 状态互斥（零 trace vs 未判决 trace）；纯 text 抢答（无工具）仍由 S13 在 Stop 兜底。新编排节点声明 sub_steps 时**必须显式给 fence_allow**（与 ref/purpose 同处，单源）。 v2.11（2026-07-26，designs/autocontinue-fence-notice-design.md）：围栏提示文本单源化到 engine `engagement_fence_notice()`，UserPromptSubmit 注入与 Stop pass/block 续轮双通道同文——此前续轮通道不带豁免文案，模型只在子1 见过无豁免版提示，到子4 臆断 Agent 被 deny 并编造留痕（demo 121320fe）。**模型声称「某工具被围栏 deny」时的验真法**：查 `.wf_fence.log` 有无对应 `engage_fence_deny|tool=<X>` 行 + transcript 有无该工具的 tool_use——都没有=未试先称，按编造处理。

**S10 步骤围栏**（deny 提示「等待门控判决」）：模型写完当前子步骤 evidence 后未 end_turn 就继续调工具（典型：连做下一子步骤探查，demo 会话 3009550c 实录）。围栏与 Stop 门控共用 `last_judged_trace` 游标——judge 判完（pass/block 都记游标）围栏自动开。**Task\* 豁免**（2026-07-27，demo 907fee09）：TaskCreate/TaskUpdate/TaskList/TaskGet 是 output-style 强制每轮维护的清单记账工具，无法用于下一子步骤探查——deny 它不防违规，只制造「模型按 TaskList 强规则同步 -> 被 deny -> 弱遵从重试 9 次」的报错刷屏；与 S15 常驻集含 Task\* 同逻辑（TaskStop 不在豁免内）。**同类排查**：用户报「一堆 Error: ...等待 Stop 门控判决」时，先看 `.wf_fence.log` 的 `fence_deny|tool=<X>` 是什么工具——Task* = 本豁免前的历史现象（已修），其它工具 = 模型写完 evidence 未 end_turn 的正常拦截。

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
6. **deny 某工具前先问「它与其它强规则打架吗」**（2026-07-27，demo 907fee09）：S10 全 deny 撞上 output-style「每轮对齐 TaskList」强规则 -> 模型按规则同步清单被 deny、弱遵从重试 9 次报错刷屏——**两个强规则冲突时模型必然反复违规，报错刷屏且无一处有 bug**。记账类工具（Task*，不能用于探查）应豁免；评判标准：deny 它防得住哪一类违规？答不上 = 不该拦。
7. **deny 某工具前先问「它是否承载某个 harness 原生流程」**（2026-08-05，tail_volume u:1 子3 实证）：TaskOutput 是 harness「主会话阻塞等/取后台 agent 结果」的原生机制。子3/子4 派后台 agent 后模型本会用 TaskOutput 等 agent 归来再写 trace；fence_allow 漏配 TaskOutput -> S15 误拦 -> 模型无法等 -> 抢跑 end_turn -> trace 未落 -> S13 假性 block「无 trace」（看似模型抢答，实则是围栏断了它等结果的原生通道）。与 #6 同构但不同维度：#6 = 与**其它强规则**打架，本条 = 破坏 **harness 原生流程**。评判标准：该工具是否是模型完成「派发->等结果->落 trace」闭环的必经一环？是则必须放行（fence_allow 声明），deny 它只会把闭环逼成抢跑。

**旧工作流（fence 前建的）无围栏**：per-wf settings.json 是 launcher 写的模板，旧 settings 缺 workflow_step_fence.py 注册。`dl <name> --resume` 重起 launcher 会补写 settings（或手加）。

### 症状 N：judge 递归爆炸（claude -p 进程堆积 / 连环 TimeoutExpired）

**症状**：`ps aux | grep "claude -p"` 一堆 judge 进程；`.wf_advance.log` 连环 `gate_block|reason=judge 调用失败（TimeoutExpired）`；evidence 被返工连写多行。

**根因**（2026-07-25 demo 实测）：`run_judge` 的 `claude -p` 子进程继承主会话 cwd（worktree），judge 会话启动加载用户级 hooks -> 它的 Stop 又触发 `gate_sub_step_at_stop` -> 游标未落盘期间看到「新 hash」-> 再生 judge -> 链式爆炸；每个 judge 等子 judge，全员 120s `JUDGE_TIMEOUT` 超时判 block -> 主会话返工写新 trace -> 更多 judge。

**修复**（commit 见 git log「judge cwd」）：`run_judge` subprocess 加 `cwd=tempfile.gettempdir()`——非 git 目录下 hooks 反查不到项目根，静默退出。防回归测试 `TestRunJudgeIsolation::test_judge_cwd_cwd_outside_git_repo`。

**急诊**：先 `pkill -f "claude -p --output-format json 你是工作流节点门控"` 止血，再修 cwd。judge 超时的 block 会计 node_attempts，事故后可用 `/dl step-pass` 或手改 state.json `node_attempts` 归零恢复。

### 症状 P：模型违规模式目录（弱遵从模型实测，MiniMax-M3 @ 2026-07-25）

**元教训：对弱遵从模型，一切关键规则必须硬化——文案=建议（概率遵从，当日实测合规率约 50%），hook=物理。** 当日全部机制（S1 门控 / S10-S15 围栏）都是这个原则的兑现。下表是实测出现的违规模式 → 对应机制（加新机制前先查是否已有覆盖）：

**能力边界补充（2026-07-26「兼容度太低」之问）**：围栏硬化的是**遵从**（机械动作），硬化不了**能力**（根因分析/证据评估是工作本身）——能力不及的模型什么机制都救不了，其表现是 gate 持续 block 到升级。弱模型上的正确预期是**优雅降级**：质量底线由 judge 保证不变，代价是 block 率+用户裁决次数+墙钟上升；对用户的话术不是「必须用强模型」，是「弱模型上它会更频繁地向你求助」。MiniMax-M3 实测在能力下限之上（被指即修=会做不主动做）。

| 违规模式 | 实录 | 对应机制 |
|---|---|---|
| 明示「简单查询不走流程」直接抢答 | 8c51c318 / b01d6507 | S15 前置参与围栏（零 trace 窗口探查工具首调即 deny）+ S13 参与围栏（无 trace 不许结束回合，纯 text 抢答兜底） |
| plan mode 里「改走 plan mode Phase 1」适应而非退出 | 61482dbe | S12 拒提问 + deny 文案指路用户切模式 |
| Write 覆盖 evidence（销毁前轮原话佐证） | e84aee6d | S14 覆盖守卫（全行包含检查） |
| 把用户口语「润色」成书面语记录（判非原话） | bf2516ac | 取证指引（引用原话/会话事实） |
| 知道要件后「填表」：推断补全字段 | e84aee6d | 质量判据黑盒（判「系自行推断」） |
| 编造痛点（「好奇心缺口」「无法判断X」=复述提问） | 4f3d9754 等 | 双结论 rubric（②合法）+ judge 拦伪痛点 |
| 把 ①/② 分支抛给用户投票（随手选与事实矛盾） | bf2516ac | 分支推导规则（事实推导，禁投票） |
| Write 无尾换行 + printf 追加 = 合并行（trace 隐形） | 74f82d93 | raw_decode 容错解析 + S13 分诊；**v2.14 根治：append-trace（模型不再手写 JSONL）** |
| printf 把单个 JSON 写碎（字面换行跨两行 / 字面 `\"`）= 返工 trace 隐形，流程看似卡死 | d59d05ea | corrupt-rework-detect（同 hash 分支检测损坏行 -> block 指 append-trace）；**v2.14 根治：append-trace + S14 直写 deny** |
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
1. `dl_flow_engine.py`：Node.sub_steps / Step.gate / advance 逻辑
2. `workflow_phase.py`：`_format_injection` 的当前步块 + 骨架链 + 完成标记格式
3. `workflow_advance.py`：Stop 检测的完成信号（若变）
4. **`scripts/workflow/phase-rules.md`**（v2.12 起为模板）：子步骤 purpose 段是 GENERATED 标记（launcher 渲染，**改 engine Step.purpose 自动同步，无需手改**）；手维护范围只剩静态强制语义（围栏/invoke 时序/完成标记）-- 这些仍是**最易漏**项，system-prompt 通道优先级最高，漏改必打架
5. **`output-styles/workflow.md`**：显示层契约（清单 subject 写法/横幅格式/建齐规则）**+ 完成标记语义 + 阶段结构清单**——同为模型强遵从通道；改注入里 TaskList/横幅相关文案时漏改它，会出现"两通道措辞歧义 -> 模型解读随会话漂移"（症状 F 编号实例，commit 5215b63）。**同步面不止显示契约**（2026-08-02 v2.41 实证）：对收不到 attachment 的模型（症状 D），output-style 是完成协议的**唯一**来源——SUB_DONE 描述停在 v2.7 编排化前、plan 四子阶段自 v2.18 起四个版本没进 TaskList 清单（9->13 项），fallback 通道直接教模型违规（修 439cabe）。改编排（标记语义/子阶段增删/门栏位置）时本文件的完成标记段 + 清单枚举 + 示例必须同批过。
6. 冒烟：拿真 worktree + 真 state 跑 `_format_injection` 看注入结构；跑 `dl_flow_engine.py render-phase-rules scripts/workflow/phase-rules.md` 看渲染产物（子步骤段应与 engine purpose 逐字一致）
7. **新增/移动编排节点或门栏专项**（2026-07-27 GoalsAndValue + 门栏迁移 + ScopeAndConstraints 三轮沉淀）：
   - **共享 evidence 串号防御**：第二个编排节点起，sub_step 都从 1 起——trace 匹配层（`_iter_trace_segments` 一族 + `reset_state` + `redteam_prompt`）必须按 minor_stage 过滤，否则 ProblemContext 子1 的 trace 被新节点门控误读（门控误判/S15 窗口错位/state-reset 误删他节点留痕）。
   - **新开通的推进路径必须有 pinning**：「路径第一次真正走到」是 latent bug 温床——advance_state 跨节点不重置 sub_step_index 藏了一个版本（此前无害纯因下一节点无编排），门栏移走后路径首次开通即爆（normalize_state 越界卡死）。改动让某条推进路径从「走不到」变「走得到」时，先写该路径的 pinning 测试。（2026-07-28 又一实例：门栏撤除开通 understand:4→plan:1 **跨阶段**续轮路径，workflow_advance 续轮分支 `get_node(cur_phase, new_sub)` 拿**推进前** phase 查**推进后**节点，首走即错查 understand:1——凡「拿推进前 state 查推进后节点」的查找都是嫌疑点。）
   - **测试 fixture 迁移**：fixture 里当「无编排节点」用的占位在节点编排化后全量换下一个无编排节点（understand:2 → understand:3 → understand:4 → plan:1 → plan:2，均已编排）；**当前占位 = execute/review/evolution 整阶段节点**（understand/plan 已无无编排子阶段，v2.20 起），逐处 grep 别漏（ScopeAndConstraints 编排迁 9 处；SuccessCriteria 编排迁 11 处 + 2 处注释残留——计数随编排节点增多只增不减）。
   - **排他性/唯一性断言必须全量遍历，禁抽样**（2026-07-27 ScopeAndConstraints 实例）：`test_hold_field_only_on_goals_and_value` 只查「每 phase 首子节点」，understand:3 加了 hold_for_gate 它照样绿——**测试通过 ≠ 新节点被覆盖**。凡「仅 X 有某属性」的断言，遍历 `_NODES` 全表逐节点断言，别用「每 phase 第一个」式抽样。
   - **机制组合语义走查**（2026-07-27 understand:4 实例）：hold × advance="phase" 是此前不存在的属性组合，release_subgate 的隐含假设（hold 节点都是 sub-advance）被打破——大闸门被静默吸收。新节点属性组合与既有机制的组合语义必须逐函数走查，清单见 §3.8 #6。
   - **模块拆分后 re-export 会被 ruff --fix 当 F401 误删**（2026-07-27 拆 dl_flow_nodes.py 实例）：engine `from dl_flow_nodes import minor_key_map` 在 engine 内未直接使用（tests 经 `eng.minor_key_map` 访问），ruff --fix 删掉 → 9 tests 挂。教训三条：①re-export 处加 `# noqa: F401  # re-export：<谁经此访问>` 注释；②**ruff --fix 后必重跑 pytest 再 commit**——ruff → commit 连跑会把误删固化进历史（当日靠 amend 救回）；③**ruff format 重排后 Edit 必重 Read**（2026-07-28 两次实例）：format 换行重排后凭记忆写的 Edit old_string 失配浪费一轮——format 跑完先重读目标区段再改。
   - **节点重编号（renumber）专项**（2026-07-28 plan:0→plan:2，系统首次 breaking 重编号）：(a) 存量 state 撞已消失的旧节点会 `get_node` 报错暴露——符合 no silent fallback 设计，但设计文档必须写迁移说明（`/dl jump` 重置或手改 state.json）；(b) **legacy 格式测试 fixture 保留旧节点名是合法的**——test_evidence_show 测的就是「旧记录无新字段」的容错，旧 evidence 本来就引用旧节点名，无脑全替换反而失真；要替换的是「拿旧节点当现行节点用」的 fixture；(c) 重编号后全仓 grep 旧节点名逐处过（本次 hooks/scripts 零引用，tests ~20 处 + SKILL 1 处）。
   - **节点 advance 类型变更专项**（2026-07-28 v2.20 plan:2 phase→sub，系统首次 advance 变更）：连锁面四类——①测试断言（本次 13 处）：`sub_total`/`subphase_labels`/`next_node_id` 链/`meta` CLI JSON/`hold_field_only_on_gate_nodes` 全量遍历集/`artifact_on_release`「唯一 False」断言；②phase-rules 门栏放行文案（「放行 ≠ 推进+PHASE_DONE」↔「放行即续轮进下一子阶段」两套文案互换，别只改 engine 忘改文案——症状 M 主干）；③注入三态重冒烟：advance="sub" 后第三态**不可达**（`phase_done_channel_open` 恒 False，engine:584），扣留/编排中两态文案不变但要验证；④**被降级字段变死字段要删显式声明**（plan:2 的 `artifact_on_release=False` 对 sub 节点不再被读取——留着=「声明了但没生效」的假安全感，删显式声明+注释说明）。release_subgate 语义翻转（只放行不推进→推进下一子阶段）属「新开通推进路径」，按上文 pinning 规则补测。
   - **围栏白名单改动专项**（2026-07-28 产物目录迁移实例）：给 S11 加新路径规则前，先全量列出 `_phase_write_path_ok` 的既有放行面——新规则的「跨阶段 deny」断言会撞上既有宽规则（本实例：evolution 既有语义放行整个 `.claude/`（skills 更新职责），reviews scoped 断言当场撞红）。配套原则：**不为新迁移顺手收窄既有宽规则**——收窄是独立变更（surgical），在测例注释+设计文档修订行留痕即可。
   - **门栏/闸门位置变更专项**（2026-07-28 围栏收窄实例：6 门栏撤除 + understand 移出 GATED_AFTER）：连锁面六类——①节点表两字段（`hold_for_gate` + `GATED_AFTER`）一处改；②**产物装配时机**：「放行后写产物」窗口依赖 hold 存在——撤门栏的 advance="phase" 节点必须把产物改**步内装配**（`artifact_on_release=False` + 末步 purpose 加装配义务），否则产物永远没窗口写；③phase-rules 门栏文案逐节点删改（门栏段 ↔「末步自动推进」段）+ 阶段完成行 + PHASE_DONE 通道增删；④注入 `PHASE_RULES` 的 advance 文案（手维护，非数据驱动，漏改=模型被告知已撤的闸门）；⑤测试：全量遍历断言（`hold_field_only_on_gate_nodes` / meta `gated_after`）+ 末步 held 类用例**换靶**到剩余门栏节点（旧靶改断自动推进；换靶用整块替换防尾部残余 assert）；⑥SKILL §0/症状 J/design 真源（workflow-system-design 闸门位置行）。GATED_AFTER 下游零改动（dl-lib.sh 经 meta CLI 单源读）。**存量会话兼容**：被撤门栏上的 held 残留标记无害（注入/release 三重判定含 `node.hold_for_gate`），`/dl next` 即走过。
   - **SKILL §0 摘要是 purpose 的「第三通道」，不会自动同步**（2026-07-28 实例）：Step.purpose 改动经 GENERATED 渲染自动同步 phase-rules + 注入双通道，但 §0 的子步骤摘要行是**手工副本**——改既有节点 purpose 的实质内容（判据口径/分类清单/裁决点）后必须同步摘要行，否则 skill 读者拿到过期契约。当日实例：plan 会话更新了 plan:1 摘要却没同步另一会话的 understand:3/4 编程域修订，靠收尾核对才发现。
   - **front 路由/判定语义变更专项**（2026-08-12 §8 实爆，merge 98a3c1a）：「前台亲自干 vs 派后台」类判定有多个消费侧（`workflow_phase` 注入路由 + `workflow_step_fence` 白名单 + `workflow_advance` stall 兜底）——改判定必须三路同改，正治是**收 engine 单源**（`front_interactive_work_here`），禁各持副本。实爆链：§8 裸开场收窄只翻转了 phase 侧，fence 侧仍按旧判定「交互步=前台干」，有陈述 u:1#1 的段派发命令被 S15 deny → 模型把 deny 误读成「后台段把交互步交回本会话」在 TUI 抢干活（transcript 实锤）。配套两教训：①**deny 文案会被模型按「交回/完成」语义误读**——围栏文案显式写「这是围栏拦截，不是交回」；②**路由语义翻转后必跑真机 dogfood**——单测全绿覆盖不了「模型误读 deny 文案」这一层。

### 症状 G：install.sh 后 hook 没触发

- `~/.claude/settings.json` 是否含 dl-workflow hook 注册？`grep -c workflow_phase.py ~/.claude/settings.json`。
- Claude Code 会话是**在 install.sh 之前**起的？settings.json 读一次就缓存，需重启会话。
- 项目自己的 `.claude/settings.json` 里有旧的 `python3 .claude/hooks/x.py` 相对路径？会 override 用户级。删项目那份或改为绝对路径。

### 症状 R：「工作流跑太慢 / 程序不应该毫秒级吗」——耗时与 token 审计

**先给概念纠正再给数字**：工作流的确定性程序部分（hooks/engine/围栏/evidence/state）全程 <1s，慢的杠杆永远不在程序优化。**主会话成本公式=轮次数×上下文长度**（2026-08-01 v2.38：LLM 无会话状态每轮全量重发，cache read 单价 1 折但 234 轮×均 108k=25.3M 账面≈输出 2.4 倍）——token 大头优化看 §3.6 #8（一次通过率+数据面卸载），子步骤级 token/耗时审计口径看 §3.6 #9（gate blocked ts 定边界/子代理 token 在 subagents/agent-*.jsonl/时区对齐/空响应重试检测/串行白等检查）。**provider 空响应重试**（2026-08-02 v2.39 实证）：空完成重试全量重读前缀，单次会话可烧百万级 input（Q4 agent 26 次=1.19M 占 90%）——台账已机械化：kind=gate 记录的 `subagent_retry` 字段，审计先读 evidence。实测分解（demo 121320fe ProblemContext，41 分钟工作墙钟）：

| 成分 | 占比 | 性质 |
|---|---|---|
| LLM 生成（48 轮 × 中位 29s，~67 tok/s） | ~71% | 产出物本身就是模型逐字写的分析 |
| judge 判决（11 次） | ~13% | 同为 LLM 推理 |
| 工具执行 + 子代理串行段 | ~15% | 秒级累加 |
| 确定性程序 | <1s | 毫秒级，无可压 |

**auto 权限税——「工具执行秒级累加」的重大例外**（2026-07-30 tail_volume 会话实测，transcript `permissionMode=auto` 93 次）：会话跑在 auto 权限模式时**每次 Write/Bash 过端点裁决**（慢 provider 中位 Write 17s / Bash 14.3s，debug 日志 `Slow permission decision: Xms (mode=auto)` 实证），180 次改造型调用 ≈ 45min——可超 judge 成第二大头，且裁决 token 不进 transcript usage（隐身成本）。**识别法**：①transcript grep `permissionMode` 字段（per-wf settings 写的 acceptEdits 可能未生效——别信配置信实测）；②工具耗时按类型分组——Read/Skill 0.1s vs Write/Bash 两位秒数即成税（hooks 本身毫秒级，可用真实 state 冒烟排除）。**AskUserQuestion 不免疫**（2026-08-01 v2.36 实测均值 46.2s/次）——它过端点裁决，配对时长须先扣税再算用户思考（§3 #8 口径修正同源）。**根因类别**（2026-08-01 v2.36）：裸工具名规则（`"Write"`）**只覆盖 cwd 内**——工作流 trace-payload/阶段产物按决议写主仓 .claude/（worktree 外），每次过端点；gitignore 语义下 cwd 外绝对路径规则写法 = `Write(//<绝对路径去前导斜杠>/**)`（`//` 前缀转义 cwd 相对默认）。**修复**=per-wf allowlist 覆盖高频命令（`wf_write_settings`，2026-07-30 已扩 36 条实测归集版；v2.36 补 AskUserQuestion + `Write/Edit(//<主仓>/.claude/**)` 两条）；**验证**=`dl <name> --debug` 跑一轮后 grep per-wf cc_debug.log 无 `Slow permission decision`。已知漏网：env 前缀形式（`DB=... sqlite3`，规则语法不支持中段通配）与名单外新命令头——命中即缴一次税。**⚠ 短路面修正（2026-08-02 审计，128 调用 vs 37 裁决逐条配对推翻 v2.36「allowlist 根治」）**：auto 模式下**只有 Bash 前缀规则真短路**——Write 20/21、AskQ 8/8、Agent 3/3 在裸规则+路径规则双重覆盖下仍全过端点（v2.36 验证会话不在 auto 模式，结论只对 Bash 成立）；且 `Write(//path/**)` 是**死规则**（启动警告：文件权限检查只认 `Edit(path)` 规则，v4 模板已删，cwd 外由 `Edit(//...)` 覆盖）。**根治 = dl-launch.sh 钉 `--permission-mode acceptEdits`**（defaultMode 压不住持久化的 auto 选择，唯 CLI flag 优先级最高；AcceptEdits 下 Edit/Write 本地放行零裁决、AskQ 照常弹窗、PreToolUse hook 不受影响；放 `"$@"` 前用户可显式覆盖）。审计口径：逐条配对「调用 vs 裁决」而非只看 Slow 行数——Bash 48 调用仅 5 裁决（3 例复合命令）正是短路与非短路的分界实证。**canary 验证权限行为的坑（同日实证）**：从 auto 模式会话里起 `claude -p --permission-mode acceptEdits` 冒烟，会被**外层会话自己的分类器**拦截（「启动免批准代理需用户显式授权」）——出口是请用户 `!` 手动跑或显式授权，不要换工具绕过（拒绝意图合理）；逐条配对法因此成为主验证手段（不需要 canary）。**模板版本戳（v2.35）**：settings resume 不刷新是静默税根因（模板变更前创建的会话无从发现自己过时）——engine `SETTINGS_TEMPLATE_VERSION` 单源，`wf_write_settings` 盖章 `wf_settings_template_version`，workflow_phase 注入与 `/dl status` 双通道警告落后并指 `--resume` 自愈（文件缺失/损坏不误报，字段缺失计 v0）。**改 `wf_write_settings` 模板实质内容（allowlist/hooks/defaultMode）时必须 bump engine 常量**——这是唯一 bump 点。

**交互步墙钟 = 用户时间，别算进系统开销**（2026-07-27，demo 2e0f41dc）：读回确认类子步骤（ProblemContext 子6/GoalsAndValue 子5，gate=None）的耗时大头是**用户看材料做裁决**——该轮子6 占 66 分钟全是用户时间，机械层与模型都在等。耗时分解先把交互步的用户等待单列，再对剩余部分按上表归集；「GoalsAndValue 5 步全自动段 10.5 分钟」这类数字才是系统水位。

**交互读回步 = prompt cache TTL 击穿高发区**（2026-07-31 tail_volume understand:4 子5 实证）：模型把多个裁决问题**捆绑**一轮 AskUserQuestion，用户思考 >5min > 5min TTL → 下一轮全量非缓存重读（实测 255.7k token，占该窗口非缓存 input 一半）。**识别**：transcript 该轮 `cache_read` 从 ~25 万掉到百位 + `input_tokens` 跳到全上下文量级；**归因**：前一个 AskUserQuestion 是否捆绑多个硬核裁决（回答时长由最难项决定）。**已修**：8 个读回步 purpose 挂载 `_INTERACTIVE_CHUNKING_RULE`（快答项合并先问、预计 >4min 硬核裁决单列后问；见 node-design.md §0 摘要块「读回步通用」）；**验真**：下一轮运行看交互步后是否还出现百位 cache_read。TTL 客户端不可配（harness 不传 ttl 参数；外部无法复刻 byte-exact 前缀代暖 cache），杠杆只有三个：缩单次间隙（逐问拆分）、瘦间隙时上下文（子代理化）、少长间隙次数（提高一过率）。

**审计方法**：§3 #8（transcript 位置/去重/窗口归集/生成速率）+ §3 #11（报错盘点）。**优化排序**：①消浪费（假冲突循环/子代理嵌套/盲猜/撞围栏——通常占 20-30%，先于一切结构调整）；②轮数（block 循环 = +1-2 轮/次，自查提示 §3.5 #9 前移到自查抓）；③输出冗长度（墙钟 ≈ 输出 token ÷ 生成速率，线性）。**底线**：给定模型的 tok/s 与遵从率决定水位（ark 实测 6 步带门控 ~25-35m 属正常）；要数量级提速只有换更快/更强模型，不是调程序。

**「串行改并行」评估三段论**（2026-08-01 v2.36，用户问「并行能否省时间/token」的应答框架）：①**token 维度：并行必不省、大概率反涨**——生成内容总量守恒；子代理各带一份 harness 开销副本；投机执行在 block 率高时必亏（实测 block 率 54% 时「赌上一步过、先跑下一步」一半以上概率整轮作废）。②**墙钟维度：大头碰不到**——墙钟 ~2/3 是单条自回归生成流（编排层天然不可并行）；judge 段与下一步重叠 = 投机 pipeline，动的是 S10 围栏/Stop 门控的纪律承重墙；子代理输入若依赖前步过门（红队依赖子3 取证冻结）则无法提前启动。③**结论模板**：并行化 = 高复杂度 + 负 token 收益 + <10% 墙钟收益，且削的恰是质量门控的结构性串行；同工程量投串行消浪费（权限税/提一过率/judge 瘦身）可压墙钟 1/3 且 token 同步下降。先消串行浪费，再谈并行。

### 症状 S：工具调用挂起无返回（会话像卡死）

- **transcript 尾部特征**：tool_use 之后**无 tool_result**，下一条记录直接是用户文本（用户 Esc 后问「怎么不动了」）。与用户思考区分：AskUserQuestion 必有 tool_result 配对；挂起是什么都没有。
- **常见根因**：复合命令（pipe/`2>&1`）破坏 per-wf allowlist 前缀匹配 → 落到权限提示/裁决端点，用户不在键盘前即挂（tail_volume 2026-07-29 step-pass `| tail -10` 挂 28min + 317k TTL 击穿实例）。
- **已修**：dl-cmd 裸跑禁管道钉进 escalate 消息 + phase-rules（v2.32，commit e288668）。复发先看该命令形态是否复合 + per-wf settings.json mtime 是否旧版（resume 不刷新 settings）。

### 症状 T：按系统文案指路操作仍报错（文案命令模板必败）

- **特征**：模型严格按 deny 指路/报错提示/usage 里的命令模板操作，仍报错（如 `unrecognized arguments`）。模型操作语义合法，零产出。
- **根因**：文案里的命令模板与实际解析器/工具漂移（2026-08-03 v2.67 实例：S14 deny 文案教 `append-trace --scaffold`，模型补显式 name → 撞 argparse `nargs='?'` 位置参数前隔 optional 的已知缺陷）。
- **排查**：逐字重放文案里的命令模板（含模型合理的补全形态，如补显式 name）——模板必败=系统 bug，修解析器（v2.67=parse_intermixed_args）不是修模型。同类变体：**路径技术性 deny**——语义等价的合法操作只放行一条路径（S15 只放行 `dl-cmd.sh status` 不放行引擎直调 status），白名单按语义等价放宽只读操作。
- **沉淀**：rubric §3.5 #26（可见面命令模板必须真实可跑）。

### 症状 U：门禁该拦没拦 / 闸门形同虚设

- **特征**：gate hook 应在某次编辑/操作阻断却没拦（如 design_gate 应拦「无 design.md 改第 2 个源码文件」却放行）。
- **根因**（2026-08-03 v2.69 实例）：四个 gate/audit hook 的会话标识只读 env `CLAUDE_SESSION_ID`，而 hook 环境从未注入 → 所有会话塌缩 `_fallback.log` → 历史留痕跨会话生效（上午的 DESIGN 记录放行下午；历史 codegraph 查询解锁之后所有会话）。
- **排查**：看 audit 目录（`<repo>/.claude/.design_audit/`、`.cg_audit/`）——只有 `_fallback.log` = 会话标识源失效；有多个 `<sid>.log` = 正常。再对时间线：留痕记录的时间戳是否属于本会话。
- **已修**：`_session_id(payload)` 三源（payload session_id → transcript_path stem → env → _fallback），v2.69。复发先看 audit log 文件名分布；测试复现注意**别注入现实里不存在的 env**（rubric §3.6 #13 测试替身失真）。

### 症状 V：judge 全量 TimeoutExpired（连最小冒烟都超时，无进程堆积）

- **特征**：所有 `run_judge` 调用 120s 超时×2（重试后仍败），含「答案是 42」级最小 payload；`ps aux` 无 judge 进程堆积（区别于症状 N 的递归爆炸）；端点 curl 裸测却秒回。
- **根因**（2026-08-04 v2.79 重放实测）：**主会话 provider env 继承污染**——主会话跑在 kimi 端点（`ANTHROPIC_BASE_URL=api.kimi.com/coding`），重放脚本 `os.environ.setdefault` 保留继承值，judge 子进程把 MiniMax-M3 模型名发给 kimi 端点=流式挂起不报错（不 401、不超时快速失败，干等到 120s）。
- **分层诊断序列**（逐层缩小，~2min 定位）：①`curl -m 30 <端点>` 裸测连通（通≠补全可用——kimi 对未知模型是挂起不是报错）；②直跑 `cd /tmp && claude -p --output-format json --tools "" --system-prompt x '说1'`（显式 export 三件套）——正常=CLI/端点无恙，问题在调用方 env；③python 复刻 `_run_judge_once` 的 subprocess 调用、`timeout=30` 抓 `TimeoutExpired.stdout` 部分输出——debug log 里的 `url:` 行直接暴露请求打去了哪个端点。
- **正治**：重放脚本 provider 三件套（BASE_URL/MODEL/TOKEN）**硬赋值**禁 setdefault（rubric §3.5 #30 ⑩）。

### 症状 W：提示/nudge 机制在线触发，但目标行为曲线零变化

- **特征**：提示类机制（nudge/建议/软提示）日志显示正常触发，但它要促成的行为从没发生——如 /clear 交接建议 8/8 边界触发，上下文曲线仍 65k→490k 单调爬坡零锯齿（tail_volume 2026-08-06 实测）。
- **根因**（2026-08-07 v2.122）：**纯建议可零成本忽略 = 建议不存在**。触发率 ≠ 执行率——hook 日志/文案注入只证触发，执行缺口无留痕时对审计隐形。
- **排查**：①先证触发（hook 日志/注入 attachment）；②再找执行留痕——没有配对记录（prompt/resolution 类）本身就是设计缺口，先建留痕再谈修复；③有留痕后看执行率，0/N = 机制空转实锤。
- **已修**：v2.122 固定 minor_state 边界提示（时机可预期）+ 文案分档 + prompt/resolution 配对留痕（未决补记 declined，零交互轮次）。修复出口两档：升结构保证（围栏/gate），或固定时机 + 显式接受用户自主并留痕——「阈值决定是否出现的纯建议」中间形态已淘汰。
- **沉淀**：rubric §3.6 #33（双指标审计）/ #34（程序化可达性 + 反向事实模拟）。


### 症状 X：drive TUI 段零 TaskList/零横幅/像普通聊天（契约条款通道存活）

- **特征**：v3 裸开场 TUI 段，用户陈述后模型确实在干活（invoke 了对的 skill），但零 TaskCreate、零 `## PHASE` 横幅、闷头探查十几轮零提问——视觉上=普通聊天非工作流。driver 进度区不见是设计内（disp.stop 让位终端），别误判。
- **根因**（2026-08-09 c95e430c 实证，c515b52 修）：契约条款住在 build_step_prompt——裸开场不喂 prompt，**条款随通道一起消失**；output-style+attachment 弱通道压不住弱遵从模型。**通道存活审计：任何契约条款新增/搬家，必查「该通道在全部启动路径下是否存在」**。通道稳固度排序：`--append-system-prompt-file`（启动必带，抽不走）> 首条 user prompt（裸开场可省略=整体不存在）> UserPromptSubmit attachment（投递≠收到，症状 D）> output-style（加载但会被当前任务盖过）。
- **排查**：读 TUI 段 transcript（`~/.claude/projects/-...-worktrees-<name>/<sid>.jsonl`）看首条 assistant 消息有没有 TaskCreate/横幅；再定位该条款住哪个通道、本次启动路径带不带它（`_is_bare_open`=True 时 build_step_prompt 整体不存在）。
- **已修**：开场纪律单源 = `ensure_tui_rules()`（system prompt 通道），prompt 尾只留指针防双份（症状 M）。
- **关联硬约束**：原生 TaskList 只在 TUI 会话内存在（无外部进程向运行中 TUI 推事件的通道）——「透出」类需求先问「哪个进程拥有终端、用户什么时刻看什么」再定方案（driver stdout rich Live 常驻区 + TUI 段原生组件的分面由此而来；v3.1 主会话调度方案被用户当场否决=循环确定性优先于 UI 原生度）。

### 症状 Y：Ctrl+C 不退出 / 退出后还继续流程（编排器信号语义缺失）

- **特征**：driver 跑流程时按 Ctrl+C 不退出、流程反而继续；连按好几次才退出。
- **根因**（2026-08-09 实证，7222218 修）：Ctrl+C=SIGINT 发**整个前台进程组**——TUI 子会话按原生语义单击=中断生成（不死），driver 无 KeyboardInterrupt 处理裸抛栈死=「driver 死了 TUI 还继续跑」。第二来源：TUI 段未落库（双击退出//exit 早退）时 none 重试**自动重开会话**——交互步靠用户驱动，自动重开=「退出还继续」（应直接断点裁决）。
- **模式**（`_pwait_interruptible`）：单击=中断当前活动（on_first 后继续等）、双击=杀子进程退 130；`already_interrupted` 参数防「读循环已计单击、wait 阶段再计一遍」的三击断层；headless 子进程 `start_new_session=True`（终端 Ctrl+C 只打 driver——防 child 先收 SIGINT 自杀、driver 读 EOF 当正常收段的竞态）；TUI 段**保同进程组**（TUI 需自收 SIGINT 保原生单击中断生成语义）。
- **冒烟坑**：TUI raw 模式下 `printf '\x03'` 是**按键不是信号**（driver 收不到 KeyboardInterrupt 属设计内——TUI 自有键绑定处理）；TUI 双击退出确认窗 <1s，pty 喂键须快进（间隔 0.4s 实测可达，2s 必败）。

### 症状 Z：v4 front 段运行诊断（零可见性 / 秒退 rc=1 / 前台抢活）

- **「段在跑但没动静，是否卡死？」判读 runbook**（2026-08-12 dogfood 三连问实证）：四件套按序查——①`state.json` 的 `segment_sessions` 台账（~~每子步骤一个独立 headless 会话进程~~ **P2-4 段链后（2026-08-13）：白名单节点 u:2/3/4 的连续 headless-step 同 sid 多步**（--resume 同会话续跑，note 字段区分步），审计口径「1 sid ≠ 1 步」；`segment_chain` 字段 = 当前活跃链；driver 进程同一个；kind/rc 逐条）；②`front_segment.json` 的 pid → `/proc/<pid>` 验活（文件在 ≠ 段活着，它只是起跑锁）；③`drive-stream.jsonl` 的 **mtime**（thinking 心跳保新鲜——**>3-5 分钟不动才疑似卡死**；十几分钟无步进 ≠ 卡死，外部取证步 agent 4-8min 是设计内最长杆，full 升档再翻倍）；④`cc_sdk.log`（headless 会话 stderr，秒退类故障的唯一信息源）。日常观测已根治 = statusLine 进度栏（v4-statusline-progress-design，refreshInterval=10 空闲也刷）；本 runbook 留给「状态栏也异常/想深挖」时。
- **headless 会话 ~2 秒秒退 rc=1 + drive-stream.jsonl 0 字节**：看 `cc_sdk.log` 的 stderr。`Error: Input must be provided either through stdin or as a prompt argument` = **CLI 变长参数吞位置参数**（`--disallowedTools/--allowedTools <tools...>` 后直接跟 prompt，prompt 被吞成工具名）——旗标后必须再跟一个 `--xxx` 旗标截断（2026-08-12 merge cc62acd）。连带：prep 3 连 none 退 12 = L3 保险丝按设计接住（断点等用户），不是第二重故障，别当两个 bug 修。
- **前台模型在非交互位置自行干活（抢活）**：先 grep fence 留痕确认「尝试了被拦」而非「不会做」（troubleshooting #14 同法）——`.wf_fence.log` 的 `front_fence_deny` / S15 deny 行 + `cc_debug.log` 的 `permissionDecision.*deny`。根因高发 = 路由判定两侧副本不同步（症状 M checklist 末条专项）；模型把 deny 文案误读成「交回本会话」是本症状的放大器。
- **段工人结构性故障时前台接管无合法出口（设计缺口，2026-08-12 ARG_MAX 案实证）**：段工人起不来（如 E2BIG）→ TUI 模型给用户恢复选项、用户批准「fence off 后手动续跑」→ **front_mode 白名单（独立于 S10 开关的第三道机制）照样 deny**——fence off 只关 S10，front 防抢活不受其控，用户批准的 fallback 被系统挡死（transcript 实证 3 分钟 5+ 次尝试全拦 → 用户中断 → 流程停滞 1.5h）。判读：「fence off 了仍被拦」≠ fence 失效，是独立机制；鉴别 grep `.wf_fence.log` deny 行的机制标记。当前唯一合法出口 = `/dl state-reset`；「段工人故障时允许前台接管」的显式开关（/dl takeover 类）= 待用户裁决的设计项，未做。

### 症状 AA：段异常「OSError: Argument list too long: 'claude'」（ARG_MAX/E2BIG）

- **根因**：driver 把 prompt 作为命令行**位置参数**传给 `claude -p`——交接包随步数单调涨 × 中文 1.68 bytes/char 放大，超内核 **MAX_ARG_STRLEN（131,072 bytes/单参数，不是 ~2MB 的总 ARG_MAX）** 即 Popen 直接 OSError，段根本不起。早期步骤包小贴线通过，后期步骤越线——**「最后阶段才爆」是体积曲线的必然形态，不是偶发**。
- **判读**：`segment_summary.json` 记 `code:1 段异常：OSError: [Errno 7]`；前兆 = 首调 fresh 随步数单调涨（P1-2 告警口径）；drive-stream 停在最后成功段、之后无任何 stream 行（段没起来=无输出，与症状 Z「卡死」判读区分：mtime 死 + segment_summary 有异常记录）。
- **修复**：prompt 走 **stdin**（merge 4f6e716，2026-08-13；实测 stream-json+verbose+大 prompt 正常；TUI 段不动——交互式 claude stdin 语义不同且其 prompt 不含交接包）。pin 测试=200KB 级 prompt 不进 argv。
- **教训**：轻任务测不出体积型 bug（v3 dogfood 轻内容全程无恙，首个重取证 run 即死）；构造消除 > 监控 > 缩输入（§3.6 #38）。
