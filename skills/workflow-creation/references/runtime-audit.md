# 运行审计方法论（可避免 error / 返工 / token 优化）

> workflow-creation skill 按需参考。review 一轮真实运行的主动审计方法。原 rubric-design.md §3.6 全部条目迁此（含 #14–#31 编号缺口的修复——本文件按连续编号重排，括注原编号供溯源）。

## 1. block 三分类再下结论（原 §3..6 #1）

**block 三分类再下结论**：基础设施性（judge 超时/bad_verdict_json/围栏误伤）-> 修机制；内容质量性（缺结论/非原话/因果链断）-> 该抓，健康返工（§3.5 #8）；判据披露缺口（执行了但留痕形式不符）-> 补 purpose（§3.5 #2）。三类的修复出口完全不同，混着报 = 误诊；别把 judge 超时算成模型遵从问题。

## 2. git log 时间线对照运行窗口（原 §3..6 #2）

**git log 时间线对照运行窗口**：报「可避免的 error」前先对 `~/.dl-workflow` 的 git log——运行窗口**之后**的修复 commit 若已覆盖该 block 根因，报「已修+后一轮已验证收敛」，不是「待修」（demo run1 报出的 bad_verdict_json/红队 Agent 被拒/不写 trace 三问题当天已修；不核对会把已修问题当新发现重复上报）。

## 3. 识别「重建丢弃」（原 §3..6 #3）

**识别「重建丢弃」**：state.json `created_at` 晚于 `.wf_advance.log` 早段活动 = 工作流被删重建，前轮产出（墙钟 + token + judge 成本）全丢弃。审计时提示：想要答案用 `--resume` 或 `/dl gate` 接续；想在最终版 engine 下重测才是合理的重建理由。**重建权归用户（2026-08-02 用户决议）——审计不劝禁重建，只分账与指路**：报告里生产账（干净单轮消耗）与测试账（重建/重测消耗）分开列，测试账是系统研发费用不是浪费；降测试成本的正解是**最小重测范围**——改 engine 后默认推荐「受影响步 state-reset 定点回滚重测」（如测子4 校验只需 `state-reset understand:1:4`，比整轮重建省一个量级），judge/判据类变更优先真实载荷重放（零会话成本），只有编排行为级改动才需要 live 整轮。

## 4. judge 输入按子步骤排开看增长曲线（原 §3..6 #4）

**judge 输入按子步骤排开看增长曲线**：单调陡增 = artifact 投喂范围过大（v2.12 前全量喂 evidence 的 O(n²) 就是 3.1k->14.9k 曲线暴露的；修复后每步只 +1 条 trace 的缓涨是设计内现象）。

## 5. 冒烟验证优化用真实 evidence（原 §3..6 #5）

**冒烟验证优化用真实 evidence**：改 read/裁剪类函数后，拿真实工作流的 evidence.jsonl 直接调函数对比输入降幅（真实数据形态 > fixture；2026-07-26 实测：子1 -97%、子3 -65%）——与 §3 #10 的 hook payload 冒烟同法，不开会话。

## 6. 弱模型优先审计透镜：block 高发时按系统杠杆清单逐项排查，不归因模型（原 §3..6 #6）

**弱模型优先审计透镜：block 高发时按系统杠杆清单逐项排查，不归因模型**（2026-07-30 tail_volume u:3 子4 五连 block 全量复盘，v2.26-v2.30 由此产出）：「换模型」是全部穷尽后的最后出口（用户决议），审计的正确产出是系统杠杆清单。七杠杆按序：①**机械下沉**——被判的东西里有几条是正则/集合可判的（方案名词/ID 传导）？②**schema 错配**——报错反复出现在同一步型？（q/a 问答模具 vs 清单型产出：3 次长度不齐全在归一化步=schema 病根，不是模型数数差）。**鉴别信号两条**（2026-08-01 v2.36 u:1 子5 实例）：a. **judge 通过轮也违反机械规则** = 机械层根本没在跑（judge 放过的陈述含 `_section_backtest.html`/`layered_backtest.py`，方案名词扫描空转实锤——病根是该步仍 qa 格式、不在 statements 分支，v2.33 迁移漏网）；b. **模型 trace 原话常自白 schema 缺口**（「append-trace 当前仅支持 q/a 格式」）——审计 block 时先读模型自己写的 purpose 字段，它比判词更懂病根。③**消费契约倒推**——最难的转换是否压给了取证条件最差的下游步（具体引用→outcome 抽象应在有 codegraph 的子3 做，不该留给子4）？④**judge 记忆**——判词轮间漂移=judge 无记忆（喂前轮判词）；⑤**判词形态**——指实例=打地鼠，指模式（附范例）才可学；⑥**返工粒度**——结构化后还全篇重写=指引缺失；⑦**申诉通道**——模型诊断出判据缺陷时有出口吗（dispute）。**配套输出格式**：逐操作时间线（assistant 按 message.id 去重 + gate 事件交织 + AskUserQuestion 用户等待单列）+ 调用次数归因（健康基线 ≈ 1 + block轮数 × 4：重写/append/总结/judge）——归因桶：用户裁决 / judge / 工具执行 / 模型生成 / 权限税（症状 R）。

## 7. 数 force-pass：连续强制放行 = 判据误判信号灯（原 §3..6 #7）

**数 force-pass：连续强制放行 = 判据误判信号灯**（2026-07-31 tail_volume 审计）：单点 step-pass 可能是用户权衡进度；**连续多节点 force-pass（尤其栽在同一形式要件）= 判据无通过路径的实锤**。配套动作：重放被 block 载荷检验判据是否自相矛盾（§3.5 #15）+ judge 判词与机械事实对表（engine 是先有 trace hash 才调 judge，「缺记录/无法证明已写入」判词必假——v2.34 已钉 prompt 防线）。

## 8. 主会话成本公式=轮次数×上下文长度——一次通过率与数据面卸载是两大杠杆（原 §3..6 #8）

**主会话成本公式=轮次数×上下文长度——一次通过率与数据面卸载是两大杠杆**（2026-08-01 tail_volume u:1 审计）：LLM 无会话状态，每个 assistant 轮次全量上下文重发；cache read 单价 1 折但量可超输出 122 倍（实测 234 轮×均 108k=25.3M cache read，账面≈输出 2.4 倍）。**返工的真实成本不是 judge 那 2.5k，是全上下文 2-3 轮重读+重生成**——归因先算这个乘积再谈优化。杠杆按序：①一次通过率（§3.5 #16 三件套）；②**数据面卸载**——高工具密度步（外部取证类）的原始输出卸子代理，返回契约=蒸馏边界（每原子 ≤120 行），编排与会话连续性不动（v2.38 实测）。「证据链交接（每步全新上下文）」是更彻底方向，但前置=证据 schema 字段完备（v2.33/v2.37 在建）且步内轮次才是大头——先卸数据面。

## 9. 子步骤级审计口径增量（原 §3..6 #9）

**子步骤级审计口径增量**（2026-08-01 两次 u:1 审计）：①**子步骤边界定位**=gate blocked 记录 ts + transcript 里 append-trace 工具调用时刻（精细切返工轮）；**子步骤级 pass 不落 evidence 是设计内**（kind=gate 只落 blocked 供 prior_verdicts；passed 只在子阶段/整阶段/手动 step-pass 放行才写）——别把「无 pass 记录」当缺口报；②**子代理 token 在主 transcript 外**：`<session>/subagents/agent-*.jsonl`（红队/取证子代理），漏算会低估该步成本；③**时区对齐**：transcript timestamp=UTC，evidence/state=本地+08；④**一次通过率口径**=同 sub_step 的 trace 行数（尝试数）vs 子步骤数；⑤judge 延迟离群（实测 137s vs 正常 15-50s）疑似 bad_verdict_json 重试，单列不归模型耗时；⑥**空响应重试=独立成本异常类**（2026-08-02 v2.39 tail_volume u:1 子3 台账）：provider 空完成重试不走缓存、全量重读前缀——检测启发式=assistant 消息 `output_tokens==0 且 input_tokens>0` 计数；放大公式=重试次数×当时前缀长度（乘积：Q4 agent 26 次×29k→60k 增长前缀=1.19M in 占其总 in 90%，同批其余 6 agent 零重试=provider 侧抖动非文案问题）。v2.39 起 write_gate_verdict 自动落 `subagent_retry`（agents/empty_responses/burned_input_tokens）进 kind=gate 记录——审计先读 evidence 台账，不用手工挖 transcript（无子代理步骤字段省略是设计内）；⑦**墙钟「串行白等」检查**：主链工具时间轴 vs Agent spawn/返回时刻对齐——子3 实测主会话先内查 3min 再派发=空等最长杆 agent 10min（串行白烧 ~20% 步耗时，v2.39 已钉死先派发后内查）。审计耗时先问：最长杆子代理运行窗口内主会话在干活还是在等？**执行序不可从 trace 验证→不进 gate，走 purpose/selfcheck 文案钉死**（§3.5 #1「judge 判不了的不判」的正向承接形态）。

## 10. 上下文构成审计与全程膨胀量化（原 §3..6 #10）

**上下文构成审计与全程膨胀量化**（2026-08-02 u:1 审计 + context-handoff-design）：#8 的成本公式的两个操作化增量。①**构成分桶**：transcript 按 tool_result/tool_use_input/assistant text+thinking 分桶统计字符——u:1 实测构成 = thinking 34%/Read 结果 29%/载荷 Write 18%/Agent 派发 6%，桶占比直接决定优化落点（Read 桶大 → 内查卸子代理是下一杠杆；thinking 桶大 → provider 端行为先验证再动）。②**平方增长量化法**：会话不重置时上下文每轮 +Δ 只增不减（实测 Δ≈3.1k tok/轮），单节点成本实测后，后续节点按「起始上下文=前节点终值」递推——understand 全程外推 ~100M（实测锚：u:1 13.2M/74 轮/终值 283k），全工作流 250-400M。**审计报告给「不处理会怎样」的外推表，是架构级优化（v2.45 交接架构，~5x）立项的依据**——只报当前节点消耗会低估一个数量级。交接架构本身与验收口径（上下文曲线应从单调爬坡变 45k-150k 锯齿）见 designs/context-handoff-design.md。**自检信号（2026-08-02 用户二次提醒弱模型优先原则）**：审计句子一旦写出「模型基本功/能力不足/不该犯这种错」即停——下一句必须是系统杠杆。实例：「JSON 载荷语法错误是模型基本功问题」是违禁归因，杠杆②已落地（v2.58 `append-trace --scaffold` + 分节标记文本载荷——模型零接触 JSON：v2.57 JSON 骨架是半吊子（Edit 填内容仍被 ASCII 引号弄崩），标记文本【purpose】【q】【a】零转义、序列化全归脚本，「待填」占位符被全局扫描兜底漏填不可提交，redteam-prompt「AI 定内容脚本管格式」同款；教训：**杠杆设计先问「模型还碰不碰格式」——缩小接触面≠消灭接触面**）。**优化落地后要用这把尺回查自己的方案**（本次回查逮住 v2.44 扫描面锚定缺陷 → v2.46）。

## 11. 审计提案自身也走 surgical：时间线前置 + 证伪式结案是合法产出（原 §3..6 #11）

**审计提案自身也走 surgical：时间线前置 + 证伪式结案是合法产出**（2026-08-02 u:2 审计四项收尾实证）：①**优化提案前先对当日 commit 时间线**——judge output 3.4k 的「优化点」对时间线后发现 v2.44（禁思考链）在运行窗口**之后** 12 分钟落地、A/B 已实证 -92%，正确产出是「下轮观察 judge_output_tokens 验证」而非再叠一层 prompt 改动（重复造修复=违反 surgical；与 #2 的分工：#2 管「已修问题别当新发现上报」，本条管「已被覆盖的现象别再提新方案」）；②**优化项被数据证伪时「不做+沉淀归因修正」优于硬做**——「append-trace 回显瘦身」逐记录解剖后发现回显仅占 fresh 跳变 6%（主体是模型自身输出回读，ark 增量缓存只吸收 ~2/3），全工作流省 ~4.5k fresh input=噪声级，结案方式=把正确归因口径写回 §3 #8 防下轮误诊，而非为凑产出做无效改动。审计的价值计量单位是「正确归因」不是「改动数」。

## 12. 四桶分工审计：purpose 里的「自承转录」字样 = 违规定位器（原 §3..6 #12）

**四桶分工审计：purpose 里的「自承转录」字样 = 违规定位器**（2026-08-02 全系统合规审计，v2.59-v2.61 产出）：「直接装配/禁二次创作」「原文收录/完整粘贴」「完整呈现」——purpose 写这些 = 系统自己承认该活是转录/装配，转录归脚本不归模型。审计搜这三个字样即得违规清单：产物装配（render-artifact）/子代理报告收录（--ingest-agent）/读回材料（render-readback）。**配套判据：机械门/mech 检查在防的若是「模型转录偷懒」，先问这活为什么还在模型身上**——把转录脚本化后，防偷懒检查从必需品变结构性保证（检查对象变成脚本产出，天然满足）。**脚本化的边界划法**：最小创作单元留模型（design.md 的 slug 命名=轻创作留 --slug，v2.62），其余机械面全收编——划界问「这步有不可替代的判断吗」，没有就脚本化。**原则说出口≠实现兑现**：四桶分工 v2.12 就立了，转录点却活到 v2.59 才被清——架构级原则要定期全系统回查实现面（本次为首例，由用户质询触发，不是自查发现）。

## 13. 测试环境与现实输入面一致性审计——测试显式注入的东西在现实里不存在 = 缺陷对测试隐形（原 §3..6 #13）

**测试环境与现实输入面一致性审计——测试显式注入的东西在现实里不存在 = 缺陷对测试隐形**（2026-08-03 v2.69，gate/audit 会话隔离塌缩）：四个 gate/audit hook 的 `_session_id()` 只读 env `CLAUDE_SESSION_ID`，而真实 hook 环境**从未注入**该变量 → 所有会话塌缩 `_fallback.log` 跨会话共享留痕（上午的 DESIGN 记录放行下午的多文件改动=design_gate 失效整天；历史任何 codegraph 查询解锁之后所有会话=H15 失效）。测试全程绿——因为测试 harness 显式注入 env（头注释还写着「session_id 取自 env；tmp_path 独立=会话隔离」），**测试替身与真实调用面系统性不一致，缺陷因此不可见**。审计 hook/脚本类测试时问：「这个测试替身的输入面（env/stdin 字段/调用方式）与真实调用方一致吗？差异面正是缺陷藏身处。」修法：测试模拟真实调用面（不设 env、stdin payload 按 hooks 规范公共字段 `session_id`/`transcript_path`），实现改从真源字段读。**第二实例（2026-08-05 v2.118，异步 agent 等待检测器全程失效）**：`_pending_background_agent_count()` 判「Agent tool_use_id ∉ tool_result 集合 = 未归」，但**后台 Agent 派发后 1-8 秒即回一条 tool_result，内容是 launch ack**（`Async agent launched successfully` + `agentId` + `output_file`），不是 completion。tool_use_id 立刻进 result 集合 → 差集恒空 → 检测器**自落地起从未生效**，假性 GATE block 照旧发生（审计日志记 `sub_step_engage_block` 而非 `deferred_pending_agent` = 铁证；改前先查审计日志「该分支到底进过没有」比读代码快）。fixture 写 `"content": "ok"`（同步风格 tool_result），断言 `==0`/`==1` 全绿。**教训升级：异步工具的 ack 与 completion 是两个信号，别把「受理」当「完成」。** 写异步等待/轮询检测前必须 dump 一条真实 transcript 确认信号形态（`grep -o 'agentId: [0-9a-f]*'`、找 `<task-notification>`），别照着直觉造替身。**验证手段（比 dogfooding 更适合非门禁类）**：真实 transcript 按事故时刻截断重放 + **旧判据对照组**（同输入旧=0、新=1）——对照组把「修复有效」从断言升级为因果证明。**第三实例（2026-08-12，merge cc62acd 前夜，CLI 变长参数吞 prompt）**：`--disallowedTools AskUserQuestion` 接入后重放 15/15 全绿——但重放脚本把 prompt 紧跟 `-p`（位置参数在前），生产 `run_session` 把 prompt 放在最后、紧邻变长 `<tools...>` 被吞成工具名 → 生产 prep 3 连秒退 rc=1「Input must be provided」全挂。**差异维度从「输入面字段」扩到「参数顺序/调用形态」：自构验证命令与生产代码的命令行必须逐参数一致**，新 CLI 旗标接入的验收 = 生产函数真身跑真实 CLI 冒烟（单测 mock Popen 只能钉顺序断言，证不了 CLI 真实解析行为）。**第四实例（2026-08-17 u1-sub4-cost，断言侧失真=测试保护伞）**：plan-first 6→7 步重编号后，nodes.py 的 mech_checks 与两个 check 的 docstring 都按新编号更新，`ingest_agent_report` 标题映射 `cur==3/4` 硬编码漏网——而既有测试 `test_ingest_redteam_happy(sub_step=4)` 钉的正是**旧编号行为**，全绿掩盖生产 bug 两轮实爆（D/F 轮 step4「蒸馏报告收录项不足」）。**迁移/重编号类变更的审计口径**：①grep 数字字面值常量（`cur==N` 式硬编码比 docstring 藏得深——docstring 随手改了，常量不会自己改）；②检查既有测试断言是否钉旧映射——**测试没跟迁移走 = 回归测试变缺陷保护伞**，「测试全绿」对这类变更零证据价值。

> ⚠️ 编号缺口说明（2026-08-17 重组体检发现）：本节编号从 #13 直接跳到 #32，**#14–#31 缺失**——历史沉淀时编号随手往大数字堆、未维护连续性。下方 #32–#40 的真实顺序即 §3.6 的第 14–22 条；主题重组时按连续编号重排，此处暂保留原编号以免打断 `§3.6 #N` 式既有交叉引用。

## 14. 上限 ≠ 配额——只写总额上限的多资源分配会被合规地独占（原 §3..6 #32）

**上限 ≠ 配额——只写总额上限的多资源分配会被合规地独占**（2026-08-05 v2.118，light 档取证层）：契约写「≤2 层源；≤4 curl」，子代理**完全合规地**把 4 次全花在第 1 层（同义词族重试 2 次 + 1 次无用的 API 健康度校验），第 2 层一次未轮到，然后如实上报「未收敛、建议升档」→ 白烧一个 agent 轮次 + 一次升档。判据缺口不在模型判断力，在**规则只给了上限没给配额**。修法：多资源分配必须写配额算式——每项最小值（每层 ≥1）+ 单项上限（总额 -(N-1)）+ 违规形态（未轮完即申报升档 = 配额违规，须标「第 K 层未尝试」）+ 额度用途边界（额度只用于目标取证，健康度/配额校验不占额也不必做）。**配额是算式不是劝告**——它进脚本生成的执行参数（骨架），子代理无裁量空间；写成「请合理分配」则等于没写。

## 15. 建议/提示类机制审计 = 触发率 × 执行率双指标——可零成本忽略的建议等于不存在（原 §3..6 #33）

**建议/提示类机制审计 = 触发率 × 执行率双指标——可零成本忽略的建议等于不存在**（2026-08-07 v2.122，tail_volume 65k→490k 零锯齿）：v2.45 阈值 nudge 真实 transcript 重放 = **8/8 边界触发、0 次执行**——「触发了」不等于「生效了」。审计任何 nudge/建议/软提示机制，第一问是执行率不是触发率（hook 日志只证触发）。无执行数据则先建**配对留痕**而不是加交互：事件两侧机械写（prompt 发出即记、resolution 由 SessionStart/下一事件检测补记、未决自动补 declined）——零交互轮次；用 AskUserQuestion 问「你执行了吗」= 多花一轮全量上下文重读，买 hook 免费能拿的数据。**归因保守**：语义不确定的事件不计入（startup 不算 cleared——新进程启动未必是响应提示，宁纵勿枉留到下一边界记 declined，与 #13 测试替身同族的「不错记」方向）。修复出口只有两档：①升结构保证（围栏/gate/机械核验，§3.5 #20 做侧闭环同族）；②固定时机 + 分级力度并**显式决议接受用户自主**（留痕供事后量化「提示几次/清几次」，攒够数据再议硬闸）——「阈值决定是否出现的纯建议」这个中间形态已被实证淘汰。

## 16. 机制设计两个先行核实：harness 动作的程序化可达性 + 收益的反向事实模拟（原 §3..6 #34）

**机制设计两个先行核实：harness 动作的程序化可达性 + 收益的反向事实模拟**（2026-08-07 v2.122 设计过程）：①「用户点击/确认后系统自动执行 X」类方案，先核实 X 有无程序化入口——**/clear 只从键盘解释**，hook/工具/AskUserQuestion 回调均触达不到，「点击后自动 /clear」物理不可行，系统侧设计上限 = 正确时刻的提示 + 用户的 2 次击键（不可约动作要在设计文档里明示，别设计出执行不了的链路）；②机制收益上线前用真实 transcript 做**反向事实模拟**——假设机制被全程执行，重放 usage 时间序列 + 策略模拟（每边界重置 45k、节点内增量不变 → 316M→90M = 3.5x），比拍脑袋预估硬，且与上线后实测可对表；③分档/阈值类参数用历史样本集复跑验证区分度（23 个会话三档全员出现 = 不塌缩；轻会话全 ok = 零打扰面成立）。**提示时机设计**：条件触发（阈值命中）时机不可预期，被用户感知为「割裂」；固定边界（每 minor_state 末步）+ 文案分档 = 节奏感与信息量的双赢——时机的可预期性本身是用户服从度的设计变量。

## 17. token 审计口径：transcript usage 按 message.id 去重，权威值 = result 事件 modelUsage（原 §3..6 #35）

**token 审计口径：transcript usage 按 message.id 去重，权威值 = result 事件 modelUsage**（2026-08-12 interaction run 审计）：transcript 按行求和虚高 **2.4-3×**（流式增量重复记录同 id usage）；去重法已逐字验证（95f69a19：去重 4,996,096 == modelUsage 4,996,096）。三通道口径：段会话=drive-stream.jsonl result 事件（modelUsage 逐会话真值）；TUI/任意 transcript=按 `message.id` 去重求和；**引用旧设计文档数字先换算**（v3.0 的「318.7M cache_read」即重复计数口径，去重实算 130.8M——拿虚高基线算优化空间会自我感动）。报成本永远标口径。**增补（2026-08-17 u1-sub4-cost 审计实操两坑）**：①deepseek 流式 transcript 同一 `message.id` **拆多行**落盘（首行只带 thinking 块，tool_use/text 在后续同 id 行）——按 id 去重若「取首行」会丢全部 tool_use（本次步内工具序列统计全空误诊），正确做法 = **同 id 内容块合并、usage 只计一次**；②`drive-stream.jsonl` 是 pretty-print debug 日志（`[log_xxx] sending request` 开头、body 截断成 `[Object ...]`），**不是 JSONL**，别逐行 json.loads——token 真值走 transcript/modelUsage，debug 日志只用于请求级排查。

## 18. 耗时三桶分解 + 等用户实测（原 §3..6 #36）

**耗时三桶分解 + 等用户实测**（同审计）：墙钟 = 段内干活 / 系统税（judge+段启动+派发）/ 等用户。三个操作化口径：①`segment_sessions` 的 ts 是**完成时刻**不是启动（相邻 ts 差=步耗时含 gate/等待）；②**等用户时间 = transcript 里 AskUserQuestion tool_use → tool_result 间隔求和**（interaction run 实测 17 次 16.8min——此前凭感归类为「系统边界税」的间隔，实测约一半是用户思考时间，优化落点完全不同：合并装配段只省系统那一半）；③judge 延迟别用记忆旧数，单调一次真实载荷再决策（v2 时代 36s → v2.44 裁剪后实测 8.9s，旧预估会把「judge 跳过」类优化phantom 化）。

## 19. 「跳过/合并机制」前先审判面与需求面——审计结论为「不做」也是合格收官（原 §3..6 #37）

**「跳过/合并机制」前先审判面与需求面——审计结论为「不做」也是合格收官**（2026-08-13 P2-2）：拟给某层做跳过机制前，逐节点问「这一层还剩什么只有被跳过的组件能判」——P2-2 审计 35/35 gate 全含语义判据方框（framing 反转系列已把词形子项全下沉 mech），无一合格，**机制不建**（建了即死代码，H13）；同步发现需求前提失效（judge 延迟实测 8.9s vs 预估 36s，全 run 仅 5.3min+$2.7）。结案方式 = 审计表+实测数据落设计文档，不是为凑产出硬做（#11 ②同族）。**消费侧对称纪律**（2026-08-13 段链立项实例）：**新优化/变更提案起手先读既有设计文档的「不做的事/关闭项」节**——当次「11 步去 judge」提案 = 当日 P2-2 已关闭项（35/35 gate 含语义判据 + judge 实测 8.9s 仅占 4% 账单），提案在写新设计文档前被 §5 拦下；关闭项落档 = 防重复提案的结构性保证，不是存档仪式。

## 20. 「理论上不该故障」操作化 = 输入不变量有构造保证或机械监控；预算单位必须跨单位换算（原 §3..6 #38）

**「理论上不该故障」操作化 = 输入不变量有构造保证或机械监控；预算单位必须跨单位换算**（2026-08-12 ARG_MAX 案）：段工人「不该故障」的成立条件是 prompt 大小这个输入不变量被保证——它既无构造保证（prompt 走 argv，内核 MAX_ARG_STRLEN 131,072 bytes/单参数）也无监控，于是按体积单调涨直到击穿。防线优先级：**构造消除（改 stdin，不变量不再存在）> 预算监控（P1-2 首调 fresh 告警）> 缩输入（交接包瘦身，治标）**。配套教训两条：①**设计预算单位错配**——v3.0 用 tokens 估算段 prompt（~45k 起步），物理上限按 bytes 计，中文 1.68 bytes/char 放大从未入账，贴线而不自知；②**轻任务测不出体积型 bug**——v3 dogfood（tail_volume 轻内容）全程无恙，front 首个重取证 run（u:1 两步 13.5 万 output 进包）即死；体积类验收用重内容载荷，别拿轻 dogfood 当通过证据。

## 21. 判「冷启动」看 cache_creation，不看 cache_read/轮数（原 §3..6 #39）

**判「冷启动」看 cache_creation，不看 cache_read/轮数**（2026-08-13 amplitude_annualized 审计误判纠正）：`cache_creation_input_tokens=0` = 缓存保住（warm 续读），`cache_read` 高只说明「每轮重读累积上下文」（平方膨胀，§3 #8 同族），**不是冷启动**。冷启动判据 = cache_creation 非零（重新写缓存）。实操：查 drive-stream result 事件的 cache_creation 字段，先于任何「冷启动/缓存失效」归因——曾把 sub3 第二段 `--resume` 的 cache_read 2.9M 误判成「resume 冷启动把缓存打冷」，数据实锤 cache_creation=0 后纠正为 warm。归因顺序：cache_creation=0 → warm（先排除冷启动）；cache_creation>0 → 才是冷启动（缓存重建）。

## 22. 「跑太慢」先量化步骤轮数方差，再谈优化——弱模型的步骤耗时天然高方差，一次慢不能立优化项（原 §3..6 #40）

**「跑太慢」先量化步骤轮数方差，再谈优化——弱模型的步骤耗时天然高方差，一次慢不能立优化项**（2026-08-17 amplitude_annualized 6 轮对照）：同一套代码跑同一 understand:1 step2→3，六轮子2a 轮数 10/16/20/44/17/52——5 倍方差。审计「这轮好慢」时先看是不是落在方差带内（对照历史多轮），单次离群别急着立优化项。优化有效性的判定也要**多轮连续验证**（iter5/6 两轮子2a 稳定 15-17 轮才判定探索预算机制有效）——单轮 -39% 可能是运气，两轮连续稳定才是机制起效。

## 23. 成本优化的终验 = 真实 A/B 驱动在飞实例——安全检查三件套 + 生产同款 provider 环境 + `--segment` 边界收场

**成本优化的终验 = 真实 A/B 驱动在飞实例**（2026-08-17 u1-sub5-cost，step5 live A/B：9轮/277s/cache_read -87%/零拒 vs 基线 15-19轮/7.2-7.4min/4.8-5.2M）：合成冒烟（scratch repo）证机制不证成本——真实问题的证据规模、模型行为方差、agent 运行时长只有真跑才有。**驱动在飞实例的安全检查三件套**（缺一不动手）：①`ps aux | grep claude` 无该 worktree 的存活会话（防双 orchestrator 抢 state）；②活性锁（front_segment.json）pid 已死/陈旧；③state.json 久未更新（小时级 idle）。**生产同款 provider 环境**：`bash -ic '<provider 函数> && python3 dl_drive.py <name> --segment'`——`.bashrc` 顶部交互守卫使 `bash -lc` 拿不到函数定义（白烧一轮 rc=1 秒退才定位到）；A/B 模型必须同 provider 同模型（k3 vs deepseek-v4-flash 的能力差会淹没优化归因）。**`--segment` 撞交互边界自动收场**：rc=13 NEED_USER = 设计内成功（问题清单已备好落 need_user.json），不是失败；确认级读回步（P3-1）段内机械通过无需用户。**读数口径**：段界 = segment_sessions ts 差；token = transcript 按 message.id 去重（#17）；**逐调用时间线分解表**（per-call +gap 秒 + tool_use 分类）把「51 轮」拆成 生产性/干等/调试死循环/脂肪 四桶——本轮 step4 round-2 的 _subagent_dir bug（15 轮 2.7min）只有这张表能拆出来，看总数会误判「优化没到位」。

## 24. 驱动 worktree 未合并代码做 A/B 的两前提——凭证不进命令文本 + front 派发命令硬编码主树路径时只能 drive 直跑

**worktree 代码的 A/B 驱动法**（2026-08-18 u2-sub1-cost 实操）：#23 的驱动法两个补丁。①**凭证不进命令文本**：直接 `env ANTHROPIC_AUTH_TOKEN=sk-... python3 ...` 会被 auto 分类器按 Credential Materialization 拦（token 进 shell 历史/transcript/debug log）——从 bashrc 函数体提取 env 再跑：`bash -c 'source ~/.bashrc; eval "$(declare -f <provider 函数> | grep "export ")"; python3 <driver> <name>"'`，token 只存在于 shell 进程内，不出现在命令文本。②**验证目标是 worktree 未合并代码时 front 模式测不到**：`engine.front_segment_command()` 硬编码 `python3 ~/.dl-workflow/scripts/workflow/dl_drive.py <name> --segment`——front 模式（launcher→常驻 TUI→hooks 派发段）永远跑**主树**代码，worktree 的 driver/engine 改动根本不生效；唯一路径 = drive 直跑 worktree 脚本（`python3 <worktree>/scripts/workflow/dl_drive.py <name>`，其 `import dl_flow_engine` 按 sys.path 同目录取 worktree 版 engine）。**判别问句**：A/B 前问「这次验证的改动在哪个文件、运行时会加载哪个副本」——hooks 直引主树源（改 hook 必须已 merge 或在主树改）、front 段命令硬编码主树、只有 drive 直跑可控副本。另外：无 TTY 环境 drive 模式的 TUI 段退化为 print（AskUserQuestion 不可用、模型文本提问后退出）——测交互步全链路时这是**环境性降级不是 bug**，模型走「会话事实出处+未获答标推测」路径落 trace 属既有 gate 语义（u2-sub1-cost 设计 §6 附记）。

## 25. 种子 A/B 构造清单——裁 evidence / 裁 last_judged_trace / 清段记录 / settings 验 name-agnostic / 起跑前 handoff_pack 冒烟

**种子构造五件套**（2026-08-18 u2-sub2-cost 实操；u2-sub1-cost 同款方法此前只在 design doc 里，本条单源化）：从既有真实实例种子新实例让工作流从中间步起跑（免跑前序 = 最省的 A/B 驱动法）：①**裁 evidence**——只保留到目标步**前一条** trace（多留 = 交接包把目标步渲染成「已有 trace」，步看起来已做完）；②**裁 last_judged_trace**——只留 ≤ 前一步的 hash 键（多留会让 Stop 门控 hash 比对错乱）；③**清 segment_sessions/segment_chain/next_prep_stashed**（段记录是旧会话台账，stash 是跨步载荷，都要从零计）；④**settings 复制前 grep 验证 name-agnostic**（`grep -c <旧名> settings*.json` 应为 0 才直接 cp，否则逐字段改）；⑤**起跑前 handoff_pack 冒烟**——只读函数直接 `python3 -c` 调（cwd=/tmp、不带 workflow settings，探针纪律 [[workflow-probe-hygiene]]），确认包内容/尾行/条款符合预期再烧真机。**drive_mode/problem_statement 保持与种子一致**（problem_statement 改了会和 evidence 里的引用打架——数值漂移属 #18 混淆面，不是一致性 bug）。**入口补丁（#24 等价路径）**：`AC_WORKFLOW_LAUNCHER=<worktree>/scripts/workflow/dl-launch.sh ac-deepseek1 --dl <name> --resume --headless`——AC_WORKFLOW_LAUNCHER 只在 ac-* 函数体内被读，`dl()` 函数不读它（走 DL_WF_HOME），用 dl 入口测 worktree 代码会静默跑回主树。**交互步 A/B 的进入位形复原（2026-08-19 u4-sub1-cost）**：实例已跑过目标交互步的 TUI 段（stash 被消费、`next_prep_stashed` 已 pop）时，重设 `state.next_prep_stashed="<node>#<cur>"` 即复原 P2-1 短路进入位形——前提 = need_user.json 在位且目标步输入未变（问题清单仍有效）；不复原则 driver 会补跑独立 prep 段，B 轮比 A 轮多一段、不可比。核验 = driver 日志特征行「⚑ 问题清单前序段已备（P2-1 合并段）」。注意这与五件套③「清 next_prep_stashed」方向相反：③管**种子新实例**从零起跑，本条管**同实例续跑**复原已消费的顺带交付。

**交互步 A/B 的答案注入法（2026-08-20 p1-sub2-cost 首证）**：交互步段在 headless print 降级下有两个环境性出口形态——①模型试 AskUserQuestion 工具→结构报错→fallback 用 sources 自答（u4-sub1/ab2 路径）；②模型把问题 print 成文本+end_turn→driver 记 tui-step-needuser 退出（p1_sub2_ab 路径）——走哪条是模型选择方差，不可预定。形态②下要把步跑完成（拿 gate 裁决+完整段账），用**答案注入**：`claude --resume <段 session_id> -p "<用户答案>"` 复刻段 spawn 旗标——cwd=实例 worktree、`--settings settings.drive-tui.json`、`--append-system-prompt-file tui-rules.<node>.md`、`--permission-mode acceptEdits`、`--tools <节点白名单+TUI 三件套>`、**strip env（CLAUDE_CODE_DISABLE_CLAUDE_MDS/AUTO_MEMORY 随段 spawn 的 _ov["env"]，漏了段合计口径涨 ~11.9k/调）**、NO_MCP_ARGS 殿后（-p 及其值放它前面，--mcp-config variadic 吞尾随）；provider env 走 `bash -ic 'ac-deepseek1 ...'`。注入后 driver 再 `--resume` 跑 gate（judge）拿零 block 裁决——把交互步 A/B 从 u4-sub1 的「步未完成=环境性不计成败」口径升级为全程完成+门控可读。注入轮与 driver 重问段（stash 已消费时 driver 会重起 needuser 段带「沿用」提示，rc=0 秒退）都是人工驱动工件，登记混淆不进段合计主口径。**hook 侧生效面精确化（#28 修正）**：TUI 段 SessionStart hook 用哪棵树的引擎 = per-wf settings.drive-tui.json 的 hook 路径指哪棵树——种子组装时 sed 到 worktree（或 ensure_tui_settings 同仓化到 launcher 树）则 worktree 未 merge 的 pack 装配改动（如 pack_self_contained 包尾切换）**在 B 轮即生效**（p1_sub2_ab 实证 hook additionalContext 含切换后尾行）；只有 hook 路径留主树时才是「merge 后生效面」。A/B 前 grep 一次 settings.drive-tui.json 的 hook 路径即可定生效面，别默登记成 merge 后。

## 26. 优化轮总账不降 ≠ 优化失败——工具序列逐条归因三分诊（杠杆未生效 / 预算再投资 / license 有洞）

**优化轮总账不降的归因分诊**（2026-08-19 u3-sub3-cost 四轮 A/B，designs/u3-sub3-cost-optimization-design.md §6）：前缀/复用类优化落地后总账（段 fresh/cr/墙钟）不降甚至反升时，别急着判失败也别急着收——**把该轮段的工具序列逐条过一遍**，三分诊：①**杠杆未生效**——首调/逐调用机制读数没降（代码路径跑错、注入没到、字段没接线；先核 driver 日志特征行与首调 fresh，#24 代码路径核验）；②**预算再投资**——机制读数降了（首调 -45% 稳定），但模型把省下的预算花在**新的合法工作**上（本轮：发现 daily companion 文件纠正子2 C4 假设=质量真实收益，cr 反 +87%）——症状=工具调用数涨但每个调用都是新事实不是重查，处置=登记混淆、按机制读数验收（#13/#23 首调口径）、把「放弃还是保留这部分深取证」写成明示取舍；③**license 有洞**——条款里的开放谓词（「缺口/未覆盖/必要时才新查」）被弱模型当探索许可证（本轮：「仅缺口才新跑」→ 主动找缺口验证 + roam 工具从 codegraph 切到 grep 规避字面；另轮：包尾「按需 Read」邀请 → 15 次 evidence/state 元探查）——症状=调用在「为条款找合法化依据」而非产出交付物，处置=收紧条款写法（cost-optimization #25：默认零新查询+枚举例外），不是加探索预算（会连真缺口一起堵）。**相邻步重复取证的检测手法**：把相邻两步的工具序列并排对照，「同 symbol 的 callers/impact、同文件的 grep/Read 在两步各出现一次」= 重复取证（本轮基线 13 调用中 9 个）——与 #14「串行两会话读同一文件」同族，但从「文件」粒度泛化到「结构查询」粒度；判别料 = 前序步 trace 是否已含该查询的逐字结果（在交接包内=纯税）。
