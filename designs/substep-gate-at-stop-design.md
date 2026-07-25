# 子步骤门控收回 Stop Hook Design（evidence 新 trace 作触发）

> 状态：设计中（2026-07-25）。H8 Design-First 产物，先于实现。
> 父系统：`designs/node-step-orchestration-design.md` v2（编排）。
> 取代：`designs/step-advance-on-submit-design.md` 方案 3a 的「gate+推进在 UserPromptSubmit」（E2/E5 废止；
> 该 doc 的 E1「信号源=evidence 非 transcript」、E3/E4/E6/E7 仍然有效，本设计全部继承）。

## 0. 背景

### 0.1 3a 的历史约束（已不存在）

3a 把 gate+推进移到 UserPromptSubmit，根因是 **transcript flush 竞态**（§step-advance-on-submit §0.1 实测）：
Stop hook 在末条 assistant 事件后 ~136ms 触发，transcript 未 flush，读不到 `### STEP_DONE` → gate 不跑。
当时的修法 = 信号源换 evidence（E1）+ 检测点移 UserPromptSubmit（E2）打包。

**事后认识**：竞态是 transcript 的，不是 evidence 的。evidence 由模型用 Write/Bash 工具在回合中途**同步落盘**，
Stop 触发时必然可读。检测点移走是当时最省事的规避，不是必须。

### 0.2 3a 的割裂（用户反馈，2026-07-25）

3a 下 block 发生在**下一子步骤入口**：模型本轮开始做子2，hook 注入却说"子1 未过门控，回去重做"。
门控单位是「子步骤完成」事件本身，判决定应在完成时（Stop），不应滞后到下次提问。

### 0.3 核心难点：Stop 每次 end_turn 都触发，如何区分「子步骤完成」vs「暂停等用户」

模型在子步骤中途 end_turn 是合法的（如 AskUserQuestion 后等用户补充）。此时**不能** block 强迫继续
（会自说自话/死循环）。不能用 transcript 区分（竞态）。
解法：**以 evidence 里当前子步骤的 trace 是否有新增为触发**——模型只在自认完成时写 trace（E4 协议），
中途暂停不写。新增判定的鲁棒性见 S1。

## 1. 设计决策

| # | 决策 | 理由 |
|---|---|---|
| S1 | **触发 = 当前子步骤最新 trace 行的 sha1 与 state.last_judged_trace[key] 不同**（key=`<node>#<sub_step>`） | 行数比对会被「违规覆盖写」骗过（覆盖后行数不变 → 漏判）；hash 比对下覆盖/追加都会产生新 hash → 必判。state 只存 40 字符 hex，不存行原文（trace 可达 KB 级） |
| S2 | **Stop hook 分支顺序：node 有 sub_steps → 走本分支并返回；否则走原 SUB_DONE/PHASE_DONE transcript 分支** | 两路径互斥（有 sub_steps 节点不用 SUB_DONE，§编排 v2），原路径行为不变 |
| S3 | **pass → 推进（非末步 sub_step_index++/末步 advance_state）+ last_judged 更新 + node_attempts 归零 + 放行 stop** | 推进后下轮 UserPromptSubmit 注入自然显示新子步骤（注入链不变）。放行时输出 systemMessage 通知用户「子N 过门控 → 子N+1」（Stop hook JSON 的 systemMessage 字段只显不续轮） |
| S4 | **block → node_attempts++ + last_judged 更新 + `_block_continue(reason)` 同轮返工** | last_judged 更新是**天然防 loop**：返工后若模型没写新 trace 就 end_turn → hash 未变 → 放行 stop（不打扰）；写了新 trace → hash 变 → 重判。不依赖 stop_hook_active 标志 |
| S5 | **重做协议 = append 新 trace 行，不覆盖旧行** | phase-rules 已有「勿覆盖已有」；judge 读 evidence 全文，自然以最新一次为准；旧行留痕（多次尝试可见）。配套：`run_judge` prompt 显式指示「同一 sub_step 多条记录以最后一条为准」，防 judge 拿返工前旧行误判 block |
| S6 | **无新 trace → 放行 stop（静默）** | 中途暂停等用户是合法行为；这也是防 loop 的另一半 |
| S7 | **E7 升级机制平移到 Stop**：连续 block 达 SUB_STEP_BLOCK_ESCALATE(=3) → block 文案改为「停止重做，AskUserQuestion 请用户裁决」 | 在 Stop 续轮里 AskUserQuestion 可用（工具调用，用户实时答）。选项②强制放行 = 用户同意后**模型自己跑** `bash wf-cmd.sh step-pass`（续轮中模型有 Bash 能力，比 3a 下"等用户自己敲命令"更顺） |
| S8 | **UserPromptSubmit 的 gate 分支撤除**，workflow_phase.py 只留注入 | 门控收口到 Stop 单点；`sub_step_has_trace` 保留（engine 内部复用其读 trace 逻辑） |
| S9 | **force_pass_sub_step 不改** | step-pass 推进 sub_step_index 后，旧 key 的 last_judged 不再被查；新子步骤无 trace → S6 放行。天然兼容 |
| S10 | **「STEP_DONE 后 end_turn」硬化为 PreToolUse 围栏**（2026-07-25 增补；demo 会话 3009550c 实证模型写 evidence 后不 end_turn、连做子2 探查——文案约束是概率遵从） | 违规通道是工具调用，故围栏架 PreToolUse（新 hook `workflow_step_fence.py`）：当前子步骤有「已写 trace 但未经判决」（latest_trace_sha1 ≠ last_judged 游标）→ permissionDecision=deny 一切工具调用，模型唯一出路是输出 STEP_DONE + end_turn。围栏与门控**共用游标**天然一致：判完（pass/block 都记游标）即开。**可开关**：state.enforce_step_fence（默认 true），`/wf fence on|off` 随时切，hook 实时读 state 无需重启。文案约束保留（双通道），围栏是兜底 |
| S11 | **阶段写权限硬化为 phase-fence**（2026-07-25 增补；understand「禁改源码」等阶段禁令原为纯文案） | 与 S10 同 hook（`workflow_step_fence.py` 一个注册两处检查）：工具 ∈ Edit/Write/MultiEdit/NotebookEdit 且目标路径不在该 phase 白名单 → deny。白名单单源在 engine `phase_write_denial`：understand={understand.md, designs/*.md, .claude/evidence/}；plan={+plan.md}；review={review.md, designs, evidence}；evolution={evolution.md, designs, .claude/(skills), memory/}；execute=不限。**已知限制**：Bash 写（重定向/sed -i）无法可靠判定写意图，不在围栏内（phase-rules 文案仍禁；结构化写工具是模型改文件的主通道）。**无开关**：S11 是系统级硬约束（同 rubric，对用户黑盒）；`/wf fence on|off` 只切 S10 子步骤围栏 |
| S12 | **plan mode 互斥硬拦**（2026-07-25 增补；demo bf91ca0f 实录 plan mode 只读探查语义挤掉全部编排协议；demo 61482dbe 修正出口文案） | 四层：①per-wf settings `permissions.defaultMode="acceptEdits"` 锁启动模式（非 plan；acceptEdits 而非 default 是兼顾摩擦——default 下每次 evidence 写/Bash 都弹审批，acceptEdits 写文件静默且 hook deny 优先于 auto-accept，S11 拦得住）②fence hook：`permission_mode=="plan"` 时 deny 一切工具（仅放行 ExitPlanMode；payload 无该字段不拦）+ **deny EnterPlanMode 工具**（堵模型自进入）③workflow_phase：`permission_mode=="plan"` 时 **exit 2 拒掉提问**（stderr 给用户：请切回 default）——用户是唯一能干净退出的人；**出口文案不说「模型 ExitPlanMode」**（模型被拦得无法探查、拿不出计划会死锁，demo 61482dbe 模型「改走 plan mode Phase 1」连环被拒实录），而是让模型停止调工具、文本告知用户切模式后 end_turn ④phase-rules 文案声明互斥 |
| S13 | **参与围栏：「走不走」不再是模型的选择**（2026-07-25 增补；demo 8c51c318 实录模型明示「这是简单查询所以不走工作流」直接抢答——此前只硬化了「过不过」（门控），「参不参与」是纯文案，对 MiniMax-M3 是抛硬币） | 协议遵从的模型永远不需要在子步骤中途结束回合（问用户走 AskUserQuestion 回合内完成；结束回合必然已写 trace 等判决）。故 Stop hook：sub_steps 节点当前子步骤**从未写过 trace**（latest_trace_sha1 is None）时 `_block_continue` 强制参与——模型无法结束回合即无法「不走」。**保留 R2**：已判过的 trace（游标相等）仍放行（防 append 死循环；block 后摆烂走 attempts/escalation 既有通道）。逃逸：①cap 8 连续 block 自动终结告警（Claude Code 自带）②`/wf fence off` ③用户打断。连带规范：问用户必须走 AskUserQuestion 工具（文本提问+end_turn 会被判未参与而强制继续） |
| S14 | **evidence 覆盖写硬禁**（2026-07-25 增补；demo e84aee6d 实录模型连续 Write 覆盖 evidence，前几轮用户原话被销毁，judge 只能看到最后一行 -> 连环 block + 用户被反复要求「重新确认」） | append 从协议约束升级为正确性约束：fence hook 对 Write 目标是本工作流 evidence 文件的调用做全行包含检查（tool_input.content 必须原样包含全部已有行），丢行即 deny 并指引 printf >> / Read 后拼末尾。配套：block 返工文案改「缺哪类就用 AskUserQuestion 问哪类、把用户原话写进 a；不要只让用户确认推断（确认≠原话佐证）」（打破确认循环） |

## 2. 数据流

```
模型执行子步骤N -> 写/append evidence(sub_step=N) -> ### STEP_DONE: N（自声明，E3 不变）-> end_turn
      ▼
Stop hook（workflow_advance.py）
  ├ node 有 sub_steps -> 本分支：
  │   ├ 读 evidence，取 sub_step==N 最新 trace 行 sha1
  │   ├ hash == state.last_judged_trace[key]（或无 trace）-> 放行 stop（S6，静默）
  │   ├ hash 不同 -> engine.run_judge(Step.gate, artifact=evidence 全文)
  │   │   ├ pass  -> 推进 + last_judged 更新 + attempts 归零 + systemMessage 通知 + 放行（S3）
  │   │   └ block -> attempts++ + last_judged 更新
  │   │       ├ attempts < 3 -> _block_continue("子N 未过门控(第X次)：reason，返工并 append 新 trace")（S4）
  │   │       └ attempts >=3 -> _block_continue(升级文案：AskUserQuestion 请用户裁决)（S7）
  │   └ judge 调用失败 -> 按 block 处理（no silent fallback，继承现状）
  └ node 无 sub_steps -> 原 SUB_DONE/PHASE_DONE 分支（不变）
      ▼
下轮 UserPromptSubmit：纯注入（当前子步骤/purpose/evidence 写法），无 gate
```

## 3. 改动清单（症状 M checklist 适配）

| # | 文件 | 改动 |
|---|---|---|
| 1 | `dl-flow-engine.py` | `normalize_state` 补 `last_judged_trace: dict` 默认；新增 `latest_trace_sha1(project_root, name, sub_step)` + `gate_sub_step_at_stop(project_root, name, cwd) -> (action, reason)`，action ∈ none/advanced/block/escalate；`gate_and_advance_sub_step` 保留（step-pass 与测试复用其推进段）但 UserPromptSubmit 不再调 |
| 2 | `hooks/workflow_advance.py` | main 里 marker 检测前加 sub_steps 分支（调 1 的函数；block/escalate -> _block_continue；advanced -> systemMessage + 放行） |
| 3 | `hooks/workflow_phase.py` | 撤 UserPromptSubmit gate 分支（sub_step_has_trace/gate_and_advance_sub_step 调用 + block_hint），只留注入；注入文案「gate 校验（下次你提问时 hook 读 evidence）」改为「你 end_turn 时 Stop hook 校验」 |
| 4 | `scripts/workflow/phase-rules.md` | 「输完 STEP_DONE 即 end_turn；推进在下一次用户提问时」改为「STEP_DONE 后 end_turn；Stop hook 立即门控：过则下轮进下一子步骤，block 则当轮返工（返工 append 新 trace 行）」；门控升级段改为「block 达 3 次后 hook 给出升级提示」 |
| 5 | `tests/test_dl_flow_engine.py` | 新函数测例：新 trace->judge pass->推进+hash 记录；无新 trace->none；block->attempts++/hash 更新/同 trace 不重判；覆盖写（hash 变）-> 重判；escalate 阈值 |
| 6 | `designs/step-advance-on-submit-design.md` | 文首标记 E2/E5 被本 doc 取代 |
| 7 | `skills/workflow-creation/SKILL.md` | 症状 J（推进不走 Stop hook 走 UserPromptSubmit）改写为新机制；§0 全景图同步 |

## 4. 风险

- R1 **judge 延迟感知位移**：从「下次提问多等几秒」变为「回合结束后多几秒才真正停」。用户感知为 STEP_DONE 后停顿。可接受（judge 秒级，E2 已接受同等延迟）。
- R2 **block 后模型不再写 trace 直接 end_turn** → S6 放行 stop，子步骤卡在 block 态。下轮注入仍显示当前子步骤 purpose（注入链兜底），state.node_attempts>0 可查。不新增机制。
- R3 **evidence 写到 worktree（相对路径违规）** → Stop 读主仓无 trace → S6 放行，步骤卡住。与 3a 行为一致（症状 L 防御不变：注入+phase-rules 双通道绝对路径）。
- R4 **block 时用户失去子步骤间插话机会**（3a 下 STEP_DONE 后用户可说"这步跳过"再让 hook 判）。补偿：S7 升级通道（用户可让模型跑 step-pass）；且 Stop 放行后用户随时可插话，只是 block 续轮那一轮不行。接受。
- R5 **judge 会话递归门控**（2026-07-25 demo 实测爆炸，已修）：`run_judge` 的 `claude -p` 继承 worktree cwd 时，judge 会话自身的 hooks 会再触发本门控 -> 链式生 judge -> 全员 TimeoutExpired。修复：`run_judge` subprocess `cwd=tempfile.gettempdir()`（非 git 目录，hooks 静默退出）。教训：**任何从 hook 里 spawn 的 claude 子进程都必须显式脱离工作流 cwd**。
- R6 **evidence 合并行**（2026-07-25 demo 74f82d93 实测，已修）：Write 无尾换行 + printf 追加会把两个 JSON 粘在一行，按行解析整行跳过 -> trace「隐形」、S13 误判「无 trace」。修复：`_iter_trace_segments` 用 `raw_decode` 循环扫一行内多对象；S13 分诊「真无 trace」（`sub_step_engage_block`）vs「有内容但 JSON 损坏」（`sub_step_malformed_trace`，指引 append 单行完整 JSON）。

## 5. 实施步骤（分小 commit）

1. engine：normalize_state + latest_trace_sha1 + gate_sub_step_at_stop + 测试（commit 1）
2. workflow_advance.py：sub_steps 分支（commit 2，此时双门控并存——UserPromptSubmit 分支还在，hash 防重判使两路径幂等不冲突）
3. workflow_phase.py 撤 gate 分支 + 注入文案 + phase-rules + 设计文档标记 + SKILL.md 症状 J（commit 3）
4. 真实 worktree 冒烟：跑 demo 会话子1，看 .wf_advance.log 的 sub_step_gate_pass/block 与新 trace hash 判定
