# headless driver 架构设计（v3）

> 状态：待评审。触发 = 2026-08-08 tail_volume_acceleration_annualized 运行审计。
> 用户四项决策（2026-08-08 AskUserQuestion 确认）：粒度=每子阶段一会话 / 读回步=交互节点回 TUI / 可见性=实时尾随模型输出 / 落地=单架构替换（`ac-deepseek1 --dl <name> --debug` 即新架构）。

## 1. 背景与动机

### 1.1 审计实证（tail_volume_acceleration_annualized，2026-08-08 14:22→15:48）

- 主会话（deepseek-v4-flash，1034 次 API 调用）：fresh input 874k / output 648k / **cache_read 318.7M**。
- 上下文从 u:1 出口 244k 单调涨到 plan:4 出口 **485k，全程零锯齿**（transcript cache_read 无一次 >50% 回落）。
- 交接提示通道断裂：边界提示注入 15 次（attachment 进模型），模型可见输出转达 **0 次**；7 条 handoff_resolution 全为事后补记的 declined（=没清，不是用户拒绝——用户从未看到提示）。
- v2.122「每边界固定出现」改制被本轮反证：**出现率不是瓶颈，抵达率才是**；且 /clear 无程序化入口（harness 只从键盘解释），系统侧已无可做。
- judge 侧（35 次 `claude -p` 独立短会话）反向实证：短会话架构在本环境（deepseek 网关）稳定可用。

### 1.2 问题陈述

成本公式 = 轮次 × 当前上下文长度。会话不重置 → 上下文单调涨 → 成本平方膨胀；同时长上下文对弱模型是**干扰源**（无关历史稀释当前步指令）。用户诉求：后续步骤不再每次全量重读，且消除上下文干扰。

### 1.3 为什么不是其他方案（已评估排除）

| 方案 | 排除理由 |
|---|---|
| 程序化 /clear | harness 无入口（键盘专属），hook 输出契约无 reset 能力（官方 Hooks 文档核实） |
| tmux send-keys 代打 | 程序夺用户键盘，脆弱且观感可怕 |
| auto-compact | 触发时机=接近窗口上限（deepseek 1M 窗口，本轮 485k 没触发）；摘要有损，与磁盘 state+机械交接包的精密架构不兼容 |
| context editing（API clear_tool_uses） | Anthropic API 特性，第三方网关（kimi/deepseek）不可用 |
| systemMessage / AskUserQuestion 提示用户清 | 仍依赖用户每边界操作；治标（提示可达性）不治本（上下文存在的本身） |

### 1.4 地基（为什么现在能做）

v2.45 交接架构注释：「门控读磁盘状态（state+evidence），天然会话无关，这是架构成立的地基」。具体资产：

- **state.json + evidence.jsonl**：全部编排状态在磁盘，任何进程可续。
- **engine.handoff_pack**（dl_flow_engine.py:1376）：机械装配交接包（前序证据+用户裁决+产物指针），现成。
- **engine.gate_sub_step_at_stop / run_gate**（:2109/:2712）：门控为纯函数，可脱离 Stop hook 直调。
- **engine.render_substeps_section(node_id)**：节点级 phase-rules 段落渲染，现成——headless 段只注入当前节点段落，92KB 全量 phase-rules 税（1034 轮全程缴纳）天然消失。
- **_stop_continue 指令模板**（workflow_advance.py:258-270）：「执行子步骤 N/M + append-trace + STEP_DONE」文案，driver 复用。
- **judge 的 `claude -p --tools "" --system-prompt`**：headless 短会话在本环境的实证样本（本轮 35 次）。

## 2. 目标架构

### 2.1 总览

```
ac-deepseek1 --dl <name> [--debug]
  └─ dl-launch.sh --workflow（薄派发，新增：派发到 driver）
       └─ dl_drive.py（新，Python，import dl_flow_engine）
            loop 直到 evolution 终结:
              1. 读 state.json -> 当前节点/子步骤
              2. 门栏/闸门断点? -> 终端等用户输入 gate/back/state-reset
              3. 本节点剩余子步骤按 interactive 标记分段:
                 - 非交互段 -> headless 段（§2.2）
                 - 交互段   -> TUI 段（§2.3）
              4. 段结束后 driver 逐步子步骤门控（§2.4）
              5. block -> 装配返工 prompt 重发该段（从首个 block 步起重做）
```

### 2.2 headless 段（非交互子步骤）

- **粒度（2026-08-08 实现期修订）：每子步骤一个 `claude -p` 会话**，非初版的「子阶段内连续非交互步批量一段」。修订理由（实现期发现的新事实，用户决策时的未知项）：
  1. **append-trace 是 state 驱动**：`scaffold_payload`/`append_trace`（dl_flow_engine.py:4939/4969）都从 `state.sub_step_index` 解析当前步——批量段内 state 不动，模型给子步骤 i+1..j 落的 trace 会全部错挂到子步骤 i。批量模式须给 scaffold/append 全链路加 `--sub-step` 覆盖（含 trace_payload_path 拒覆盖/v2.63 stale 检查），引擎手术面大。
  2. **弱模型多步指令风险**：一段做 4-6 步 = 长指令跟随 + 步号自我追踪，正是一过率系统的对立面（一次通过率=最大杠杆）；且 u:1 类重节点（子代理取证回灌）批量段会重建 244k 上下文——消解本架构的核心收益。
  3. **逐步会话保持全部现有语义**：即时逐步骤门控/返工（gate_sub_step_at_stop 原样复用）、escalate、append-trace 零改动。成本反证可接受：judge 已是 35 次/run 的短会话架构（单次 2-16k 输入）；子步骤会话 ~45k 起步，43 段/run 的启动+缓存重建总开销远低于单会话 318.7M cache_read。
  用户四项决策中「每子阶段一会话」按此修订执行（目标——上下文最小+无干扰——被子步骤粒度更彻底达成）；初版批量方案及 `--sub-step`  plumbing 不做。
- **会话上下文按构造最小**：prompt = handoff_pack + 当前步目的/how + append-trace 指引 + 铁律（禁完成标记/只做本步/NEED_USER 出口）。system prompt = 节点级渲染段落（render_substeps_section + 瘦头），**不注入 92KB phase-rules 全量**。
- **工具与权限**：`--permission-mode acceptEdits` + per-wf settings allowlist（钉死，v2.47 实证）。`--settings` 用 **drive 版 settings**（§3.3）——hooks 保留但 drive_mode 降级（§2.3 同分支）；项目级/用户级 hooks（codegraph_gate/audit/inject，H15）不受影响照常生效。
- **实时尾随**：`--output-format stream-json --verbose`，driver 逐行解析，assistant text 实时上屏 + tool_use 一行简报；原始流全量落 per-wf `drive-stream.jsonl`（PHASE_DONE 检测+审计）。`--debug` 时每段会话落 `cc_debug.<sid8>.log`。
- **cwd** = 工作流 worktree（与现状一致）。
- **门控**：段结束后 driver 直调 `gate_sub_step_at_stop`（原样复用：trace hash 触发/judge/§8.3 产物门/advance/block verdict/escalate 全在内）。block → 判词装配返工 prompt 重发本步会话；none（无新 trace）→ 尖锐重发，连续 3 次 → 用户断点。

### 2.3 TUI 段（交互子步骤）

- **交互子步骤识别**：engine `Step` 新增 `interactive: bool` 字段（单源，43 步一次性标注迁移：8 个读回步 + understand:1 子1 痛点问询步等）。禁止从 purpose 文本嗅探（词形漂移病根，症状 M 同型）。
- **启动**：driver 起原生 TUI `claude --session-id <新 uuid>`（钉死，audit/留痕用），--settings = 现有 per-wf 模板（含 5 hooks + output-style），phase-rules 用节点级渲染产物（同 headless 段，瘦）。
- **hooks 的 drive 模式行为**（state.json 新增 `drive_mode: true`，hooks 读取）：
  - workflow_advance：**不 gate、不自动续轮**（编排归 driver，防双重推进）。子步骤完成（STEP_DONE+新 trace）后停轮，stderr 提示「交互步已完成，输入 /exit 返回 driver」。
  - workflow_phase / workflow_session：照常注入（TUI 体验不变；SessionStart source=startup 注入交接包——TUI 段上下文同样按构造最小）。
  - workflow_step_fence：S15/S10 维持（交互步的纪律不变）。
- **结束**：用户 /exit → 进程退出 → driver 回收，对该交互步跑门控（§2.4）。
- **动态交互 fallback**：headless 段模型若非预期需要用户输入（purpose 未预见），指令其输出 `### NEED_USER` + 问题清单并结束本轮；driver 检测到后把该子步骤重分类为交互、起 TUI 段处理。

### 2.4 driver 门控（替代 Stop hook 编排）

- 段结束后，driver 对该段覆盖的每个子步骤**按序**调用 `gate_sub_step_at_stop`（改造：抽出可被 driver 以 (project_root, name, step_index) 直调的形式，解除对 Stop 时刻 cwd/transcript 的隐式依赖）。
- 首个 block → 装配返工 prompt（block 判词 + 「从子步骤 N 起重做」）重发 headless/TUI 段；后续步骤已落 trace 由重做工序重新 append（现有「append 新行勿覆盖」协议天然支持）。
- escalate（连续 block 达阈值）→ driver 停，终端打印裁决文案等用户（同现行 S7 语义）。
- pass 续轮超阈值附交接提示：**退役**（driver 架构下上下文按构造最小，提示机制失去存在意义；handoff_prompt/resolution 留痕随之退役）。

### 2.5 门栏 / 闸门

driver 的原生断点：state 显示 held_for_gate（plan:4 门栏）或 gate=pending（plan→execute 闸门）时，driver 前台打印现行文案（✓/⛔ 块），**stdin 等用户输入** `gate` / `back` / `state-reset <n>`（语义同 /dl 子命令，dl-cmd.sh 路径不变——用户在另一终端用 /dl 也行，driver 每轮循环重读 state.json 天然兼容外部变更）。

### 2.6 状态与兼容

- state.json 新增：`drive_mode: true`（hooks 降级开关）、`segment_sessions: [...]`（各段 session id，审计用）。`session_id` 字段语义变为「最近段 session」。
- **在飞工作流接管**：driver 从 state.json 直接续——tail_volume_acceleration_annualized（停 plan:4 门栏）可作为首个 dogfood：driver 启动即撞门栏断点，放行后进 execute 全程新架构。
- **回滚通道**：`AC_WORKFLOW_LAUNCHER` 环境变量（bashrc shim 已存在，`${AC_WORKFLOW_LAUNCHER:-dl-launch.sh}`）指回旧脚本；或 git revert。旧 TUI 编排路径（dl-launch.sh 原逻辑 + 5 hooks 全量）在 repo 历史中保留，不删除——「单架构」指用户入口唯一，不指物理消灭回滚面。
- settings 模板：`SETTINGS_TEMPLATE_VERSION` bump（v2.35 机制：注入 + /dl status 双通道警告指 --resume 补写）。

## 3. 关键机制设计

### 3.1 已知坑与对策

| 坑 | 对策 |
|---|---|
| `-p` 下 transcript 可能空、Stop hook 读不到输出（skill 既有禁忌） | 新架构不依赖：推进/门控由 driver 直调 engine，hooks 在 drive 模式不编排 |
| headless 无 AskUserQuestion | 交互步静态标注（interactive 字段）+ 动态 `### NEED_USER` fallback |
| 每段缓存重建开销 | judge 已实证（35 次/run，单次 2-16k 输入，总 $6.35）；段级会话 ~45k 起步远低于 485k 全程 |
| 段内批量步骤的后验门控损失「逐步即时返工」 | block 率实测 4/43 且全在装配末步；返工从 block 步起重做的语义现有协议覆盖。若实证恶化，粒度可降档到子步骤（driver 参数，不改架构） |
| TUI 段用户不 /exit（会话挂着） | driver 无超时强杀（禁 kill 运行中会话的纪律延伸）；启动时打印明确指引，/dl status 可见 |
| 双 orchestrator（hooks 与 driver 同时推进） | drive_mode 标记 + hooks 降级 + driver 每轮重读 state（磁盘唯一真源） |

### 3.2 上下文预算对比（本轮实测外推）

| | 现行 TUI 单会话 | headless driver |
|---|---|---|
| u:1 出口上下文 | 244k | ~50k（交接包+节点段落） |
| plan:4 出口上下文 | 485k | ~60k |
| 全程 cache_read | 318.7M | 估 15-40M（8-16 段 × 段内轮次 × 段内上下文） |
| 干扰面 | 全部历史 | 交接包（机械装配，无闲聊/无关工具结果） |

### 3.3 settings（drive 版，实现期修订）

不新增模板：driver 启动时从 per-wf `settings.json` **运行时派生** `settings.drive.json`——去 `outputStyle`（TUI 横幅引导）与 SessionStart hook（交接包由 driver prompt 注入，防双份），其余原样（permissions 全量 + 4 个 workflow hooks）。hooks 不清空的原因（修订）：S11 阶段写围栏/S14 evidence 收编/plan-mode 封堵是**与编排者无关的硬约束**，headless 段同样需要；降级在 hook 内部按 `state.drive_mode` 分支（advance 全程跳过；fence 跳过 S10/S15 保留 S11/S14），单一 settings 真源免双模板漂移，SETTINGS_TEMPLATE_VERSION 机制不受影响。TUI 段沿用 per-wf `settings.json` 全量。

### 3.4 交互子步骤清单（迁移时核对）

8 个读回步（_ARTIFACT_RENDER_SOURCES decision_steps 枚举）+ understand:1 子1（痛点问询 AskUserQuestion）。迁移 = engine Step 定义逐步标注 + 测试断言「interactive 标记集合 == 现行两源枚举」防漏标。

## 4. 里程碑

- **M1 driver 核心**：dl_drive.py 循环骨架 + headless 段（prompt 装配/stream-json 尾随/段后门控/返工重发）+ dl-launch.sh 派发 + drive settings 模板。
- **M2 TUI 段接入**：Step.interactive 标注迁移 + hooks drive_mode 降级 + TUI 段启动/回收 + NEED_USER fallback。
- **M3 门栏/闸门 + 在飞接管**：断点 stdin 循环 + tail_volume 从 plan:4 dogfood（execute/review/evolution 全程）。
- **M4 收尾**：node-design.md/rubric-design.md/SKILL 同步 + 交接提示机制退役清理 + 测试补齐（gate 直调/分段逻辑/模板版本戳）。

## 5. 验证方案

1. **dogfood**：tail_volume_acceleration_annualized 从 plan:4 门栏续跑，execute/review/evolution 全程新架构；对照本轮 understand/plan 数据（上下文曲线/token/耗时/块数）。
2. **判决一致性**：judge 配置不动（同一 run_judge），重放回归照旧（tests/replays/）。
3. **单测**：driver 门控直调（block/escalate/pass 三态）、分段逻辑（interactive 序列 → 段划分）、NEED_USER 检测、模板版本戳警告。
4. **故障注入**：headless 段中途 API 挂（driver 重发该段）、TUI 段用户直接关窗（driver 重读 state 续）、外部 /dl 并发改 state（重读兼容）。

## 6. 不做的事

- 不改 judge 配置与判据（run_judge 原样）。
- 不改节点树/子步骤定义/purpose 文本（除 interactive 标注）。
- 不删旧 TUI 编排路径（回滚面保留，用户入口唯一）。
- 不做每子步骤粒度（用户已决策子阶段粒度；driver 留粒度参数口子，实证恶化再降档）。
- 交接提示（handoff_prompt/resolution/systemMessage 上屏提案）整个方向退役，不再投入。
