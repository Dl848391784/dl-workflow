# 排查方法论（systematic-debugging 适配）

> workflow-creation skill 按需参考（自 SKILL.md §3 整体迁出，节号原样保留以兼容「§3.5 #9」式交叉引用）。
> 只在 SKILL.md 路由表命中时阅读。

## 3. 排查方法论（systematic-debugging 适配）

排查工作流问题按此顺序：

1. **先看日志，别猜**：项目根 `.wf_phase.log`（注入）、`.wf_advance.log`（推进 + gate 裁决记录 `gate_verdict_written`/`gate_block`）。2. **分清"没调用"vs"调用了没投递"vs"投递了模型不遵循"**：三层次，日志+attachment 分别诊断（症状 A1/A2/D）。
3. **看 session jsonl 的 attachment**：注入真相在 `hook_additional_context` attachment，不在 user message。但**投递到 jsonl ≠ 模型收到**--ark-code-latest 实测 jsonl 有 attachment 却进不了上下文（症状 D）。怀疑时用 canary `-p` 问模型能否复述阶段名直接验。
4. **install 状态优先怀疑**：任何"改了不生效"，检 `~/.dl-workflow/hooks/` 是否含 _resolve_project_root（git pull 后即最新，无副本同步问题）。
5. **验证用真实交互，别用管道/-p**：管道有 Execution error（症状 E），-p transcript 不可靠（症状 B）。
- "证据链 / evidence / no_markers / evidence.jsonl 不生成 / 证据不落地" -> §2 症状 I
6. **grep 命中 ≠ 模型真输出**：transcript 里 `### PHASE_DONE` / `### SUB_DONE` / `### STEP_DONE` 命中可能是注入的 attachment 文本，必须按 `role=assistant` 过滤后再判模型是否真发了标记。
7. **有 sub_steps 节点特殊**：看 `.wf_advance.log` 的 `sub_step_gate_pass` / `sub_step_gate_block`（Stop hook 判，与无 sub_steps 节点同日志）；推进在模型 end_turn 时即判，**无需用户再发消息**。同时看 `<主 repo>/.claude/evidence/<name>.jsonl` 是否有当前 `sub_step==N` 的新 skill-trace（症状 J/L）+ state.json 的 `last_judged_trace` 游标。
8. **量 token / 审计模型消耗**：主会话 transcript 在 `~/.claude/projects/-...-worktrees-<name>/<session_id>.jsonl`；judge 会话在 `~/.claude/projects/-tmp/`（run_judge cwd=tempdir 的直接证据），按 `.wf_advance.log` 的 `sub_step_gate_block|...|ts` / `sub_step_gate_pass|...|ts` 时间戳找相邻 `-tmp/*.jsonl` 配对。**v2.11 起 judge 用量优先直接读 `.wf_advance.log`**——pass/block 行已带 `judge_input_tokens|judge_output_tokens|judge_ms|judge_cost_usd|judge_error` 字段，爬 -tmp 配对只在要看 judge 对话原文时才需要。**usage 必须按 message.id 去重**：同一响应的 thinking/text 分块各记一行 assistant、usage 整份重复，按行求和会虚增一倍；`queue-operation` 不是 API 调用。口径：`input_tokens`=新鲜输入（cache_read 单列），模型归属看每条 assistant 的 `model` 字段（judge 继承主会话 provider env，正常必与主会话同模型）。 **子代理 transcript**（红队等 Agent）：在 `~/.claude/projects/<proj>/<session_id>/subagents/agent-*.jsonl`（以 session id 命名的独立目录；主文件 `isSidechain` 全 false，别在主文件找）。嵌套子代理同目录并列，靠时间戳归属父代理。**按子步骤归集耗时/token**：以 `.wf_advance.log` 的 pass/block 事件时间戳为窗口边界，去重后 usage 按窗口分桶；注意日志是本地时、jsonl 是 UTC（+8 换算）。**生成速率测量**：相邻 assistant 消息间隔中位 ≈ 单轮生成耗时（ark 实测 ~67 tok/s、29s/轮）——「工作流慢」的量化口径。**cache 异常解读**（2026-07-30 tail_volume 审计实测）：新鲜输入某轮突增（如 78→7,661）+ cache_read 同步下跌、下轮又恢复 = provider 侧一次性缓存未命中（prompt cache 5min TTL 驱逐，用户长等待后易发）——**一次性脉冲不是泄漏**，绝对量小不用追；判泄漏看趋势（连续多轮 fresh 高位）不看单轮。ark 全程报 `cache_creation=0`——写缓存成本并入 `input_tokens` 计费，突增量里含重写缓存块费用。
9. **测 hook 用真 git worktree，别用普通子目录**（2026-07-25 冒烟实测）：`git rev-parse --git-common-dir` 在 repo 内普通子目录返**相对路径**（`../../../.git`）→ state 解析错位、hook 静默退出（无日志、无输出，极像「hook 没跑」）；只有 `git worktree add` 的真 worktree 返绝对路径。模板：`tests/test_workflow_advance.py`（in-process importlib 加载 hook + monkeypatch engine.run_judge 避免真起 judge 子进程 + tmp_path 真 worktree）。
11. **报错全量盘点法**（2026-07-26 demo 104 报错根因链）：扫 tool_result `is_error`——主会话 + `subagents/agent-*.jsonl` 全部子代理，tool_use_id 回联工具名，按错误内容 Counter 归并成类。**主会话报错常只是冰山一角**（实录 5 vs 子代理 99）——子代理是报错主战场，盘点漏了它就等于漏了根因。归并后才看得见结构性（93/104 同属「子代理工具现实与 prompt 指引脱节」一条链）；逐条看只会得到「偶发很多」的错觉。
10. **hook 行为冒烟不必开真会话**（2026-07-26 S15 验证法）：hook 全是 stdin JSON -> stdout JSON 契约，拿**真实工作流 state** 直接喂 payload 即见行为——`echo '{"cwd":"<worktree路径>","tool_name":"Bash","tool_input":{"command":"ls"}}' | python3 ~/.dl-workflow/hooks/workflow_step_fence.py`。改围栏/门控后必做：比开交互会话便宜，且用真实 state 覆盖「fixture 与真实数据形态漂移」盲区（测试 fixture 绿 ≠ 真实 state 下对）。**合成 state 冒烟必须字段齐全**（2026-07-28 plan:3 三态冒烟实例）：直调 `_format_injection(state, project_root)` 时合成 dict 缺 `sub_total`（默认 0）→ `has_sub=False` 注入走「无子阶段」分支，产出真实 state 下**不会出现的**「完成本阶段后输出 PHASE_DONE」行——第一轮冒烟据此差点误报文案 bug。必备字段：`name/phase/sub_index/sub_total/sub_step_index/gate/index`，按被测态再加 `held_for_gate`/`last_judged_trace`（第三态还要真写一条 evidence trace 让 `latest_trace_sha1` 命中）。

12. **「卡住了 / block 多次」分诊 runbook——归因三分，别凭感觉**（2026-07-26 两连实证）：用户报「block 了 N 次」或「卡在第 N 步」时按序挖：state.json（sub_step/node_attempts/last_judged_trace 游标）-> `.wf_advance.log`（有判词=判过；无新行=静默放行）-> evidence 对 trace（`latest_trace_sha1` 对游标；行是否可解析）-> transcript 尾部事件（模型最后做了什么动作）。然后**归因三分**：判词 vs purpose **已披露**要件 → 该抓 = 模型注意力失败（§3.5 #9，解法=自查清单，非改判据）；判据要求的佐证无合法获取路径 → 判据缺陷（§3.5 #7）；模型做了动作但系统读不到/无反应 → **机制盲区**（demo d59d05ea：trace 写碎 -> 同 hash 静默放行 -> 看似卡死，corrupt-rework-detect 修）。同一天两个案例正好一边一个：子1 三连 block=模型，子3 卡死=系统——凭感觉猜必错一半。

