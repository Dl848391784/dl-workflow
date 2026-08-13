# 前台混合架构设计（v4：常驻 TUI 前台 + claude -p 后台工人）

> 状态：待评审。触发 = 2026-08-11 用户诉求：「工作流启动后进入 claude 会话，全程不离开；各阶段非交互活在后台子进程执行，不积累主会话上下文」。
> 一句话：**v2 的壳 + v3 的芯**——交互体验回到 v2.x 常驻单会话，非交互步的执行与门控复用 v3.0 driver（后台化）。

## 1. 背景与动机

### 1.1 v3.0 解决了什么、牺牲了什么

v3.0（headless-driver-arch-design）根治了 v2.x 的两大实证病灶：318.7M cache_read（活在会话里干 → 上下文 485k 零锯齿）与边界提示 15 注入 0 上屏。代价是**交互体验的断裂**：

- `dl <name>` 后终端被 driver 进程占据（rich Live 进度区），首步交互时原地弹 TUI 段，落库即 SIGTERM 收段，用户掉回进度区——在「TUI ↔ driver 终端」之间反复弹跳。
- 进度显示从原生 TaskList 降级为自绘进度区（v3.1/v3.3.1 内容同源补到逐字一致，但样式两制是结构性上限：headless 会话没有 TUI）。
- 2026-08-11 用户明确裁决：不要「driver 守护进程 + tmux 弹窗」方向（前一版提案），要**常驻一个 claude 会话**，非交互活在后台跑。

### 1.2 关键新事实（v3.0 设计时的未知项）

**会话内后台 Bash 是原生唤醒通道**：harness 文档保证 run_in_background 任务「keeps running across turns and re-invokes you when it exits」——后台命令退出时自动 re-invoke 会话。v3.0 设计 §1.3 排除「常驻会话」的前提是「外部 driver 无法唤醒 TUI」（该前提对**外部**进程至今成立：没有 IPC 能向运行中的 TUI 注入用户消息）；但派发动作在**会话内**发起时，唤醒是 harness 原生行为，不需要 IPC。这打开了 v3.0 时不可行的混合形态。

### 1.3 问题陈述

把「非交互步的执行」从常驻会话里卸到后台 `claude -p` 子进程（保 v3 的上下文隔离与确定性门控），同时让常驻会话成为唯一交互界面（保 v2 的体验连续性）。主会话上下文每步只长「注入块 + 一条派发命令 + 一行结果简报」，活的全量工具轨迹死在子进程里。

## 2. 目标架构

### 2.1 总览

```
dl <name> --front
  └─ dl-launch.sh：原生 claude TUI（per-wf settings 全量 hooks + phase-rules 渲染
     + --session-id，同 WF_TUI=1 路径），state 置 front_mode: true
       │
       │ 交互子步骤（Step.interactive）：会话内问答，v2.x 机制原样
       │ （S13/S10 围栏 + Stop 时 gate_sub_step_at_stop 门控 + 续轮）
       │
       │ 非交互子步骤 / 无编排整阶段（execute/review/evolution）：
       │   phase 注入 + Stop 续轮双重指路 → 模型敲一条逐字给定的命令：
       │   Bash(run_in_background): python3 .../dl_drive.py <name> --segment
       │     └─ 后台 driver 段：从 state 当前位置起，连续跑非交互步
       │        （每步一个 claude -p + 即时门控 + block 返工，v3 逻辑全复用），
       │        撞交互步/门栏/闸门/升级/完成 → 按退出码收场
       │   段退出 → harness 原生 re-invoke 会话 → 注入新位置 → 续走
       │
       └─ engine state.json / evidence / judge / /dl 子命令：一行不动
```

### 2.2 段执行器：dl_drive.py --segment（v3 芯的后台化）

新增运行模式（与全程 driver 并存，不是替换）：

```
python3 dl_drive.py <name> --segment [--debug]
```

- **语义**：从 state.json 当前位置起，连续执行非交互工作，撞到「需要人或需要前台」的边界即退出。主循环复用 `drive()` 的全部件（run_session / gate_sub_step_at_stop / pending_rework / none_retries / NEED_USER 检测），重构为 `run_until_boundary(stop_at_interactive=True)` 被 `drive()` 与 `--segment` 共用——**单一逻辑真源，禁止拷贝分叉**。
- **退出码**（段结局分类，前台会话据此前进）：
  | 码 | 含义 | 前台动作 |
  |---|---|---|
  | 0 | 工作流全部完成（gate=done） | 宣告收尾 |
  | 10 | 撞交互子步骤（Step.interactive） | 会话内开始该步问答 |
  | 11 | 门栏 held_for_gate / 阶段闸门 | 提示用户 /dl gate 裁决 |
  | 12 | escalate / none 重试上限 / 用户中断子会话 | 提示用户裁决（step-pass/state-reset/重试） |
  | 13 | NEED_USER 动态重分类 | 当场转为会话内交互处理本步 |
  | 1 | 异常（API 挂等） | 提示用户；重跑同一命令即续 |
- **断点去 stdin 化**：`breakpoint_loop` 依赖前台 stdin，--segment 模式不可用——上述断点情形改为：写 per-wf `segment_summary.json`（结局码 + 判词摘要 + 建议动作）→ 按码退出。文案由前台会话读 summary 后转达用户（stderr/stdout 全文也会随后台任务通知回会话）。
- **drive_mode 置位**：段启动 `set_drive_mode(on)`、任何路径退出 `finally` 置 off。段运行期间 drive_mode=on 同时是「段进行中」的全局信号：前台会话的 advance hook 走既有 `drive_mode_skip` 早退（workflow_advance.py:457），fence 走既有跳 S15/S10（workflow_step_fence.py:552）——**防双 orchestrator 的机制是现成的**，front_mode 与 drive_mode 互斥不叠加分支。
- **段活性锁**：段启动写 per-wf `front_segment.json`（pid + started_at + 起跑位置 node/sub_step），退出删除。hooks 用 `_pid_gone`（workflow_advance.py 现成）判活：pid 死 + 锁残留 = 段被杀（会话退出连带杀后台任务等）→ 视为无段在跑，重提示派发即可幂等续跑（state 磁盘真源，--segment 从断点续）。
- **LiveProgress 默认关**：段无终端（disp=None 路径现成），输出全落 drive-stream.jsonl。
- **生命周期裁决**：派发走 run_in_background（不用 setsid/nohup 脱离 harness）——接受「前台会话退出则段被连带终止」，语义简单且恢复幂等（重开 `dl <name> --front` → hooks 见锁死 → 重提示派发 → 断点续跑）。

### 2.3 前台会话内推进协议（hooks 的 front_mode 分支）

state 新增 `front_mode: true`（launcher 置；engine `set_front_mode` 单源写入点）。三个 hook 各增一个分支，**交互步路径一行不改**：

**workflow_phase.py（UserPromptSubmit）**：注入照常；front_mode 且当前步非交互且**无段在跑**（锁不存在或 pid 死）时，注入块尾部追加派发指令：

```
▶ 当前子步骤为非交互步（活归后台工人，本会话不执行）。
立即用 Bash 工具运行（必须 run_in_background=true，逐字照抄）：
  python3 ~/.dl-workflow/scripts/workflow/dl_drive.py <name> --segment
段跑完会自动回到本会话；等待期间可与用户自由交流。
```

**workflow_advance.py（Stop）**：front_mode 分支（置于 drive_mode 检查之后）：

- 当前步**交互** → 完全走 v2.x 既有路径（S13 零 trace 强制参与 / gate_sub_step_at_stop / _sub_step_continue 续轮）。唯一差异：「advanced」后续轮文案分两类——新步仍交互 = 现文案原样；新步非交互 = 续轮正文换成派发指令（同 phase 注入的逐字命令）。
- 当前步**非交互**：
  - 段在跑（锁活）→ 静默放行（return 0）。
  - 无段在跑 → **stall 兜底**：`_stop_continue` 重提示派发指令（模型可能没听注入的——v2.x「15 注入 0 上屏」的教训：注入是建议，Stop 兜底才是牙齿）。同一子步骤连续重提示 ≥3 次 → 停轮等用户（文案指路「回『继续』或 /dl status」），防死循环（S6 精神延续：任何自动续轮都要有计数闸）。
  - 有未判决 trace（残留态，正常不会发生——段内即时门控）→ 不判（防与段双判），提示重跑 --segment 或 /dl step-pass。
- block 返工语义不变：段内 block 由后台 driver 自动重发（v3 现成），不到前台。

**workflow_step_fence.py（PreToolUse）**：front_mode 且当前步非交互且段不在跑 → 白名单收紧为四类：①派发命令逐字匹配（Bash `python3 .../dl_drive.py <name> --segment`，允许 harness 的 run_in_background 包装）；②/dl 只读子命令（status 等）；③TaskCreate/Update/List/Get（output-style 记账）；④Read。其余 deny，文案：「活归后台工人——派发用上面的命令；要与用户交互请直接对话」。当前步交互 / 段在跑 / 非 front_mode → 现状全保留（S15/S10/S11/S14 不动）。
  - 理由：fence 的防御目标是 v2.x 的头号病灶——**模型在前台会话里直接干非交互步的活**（上下文胀回去）。这是 front 模式唯一新增的结构性风险，必须有硬约束，不能只靠文案。

**workflow_session.py（SessionStart）**：不动。交接包注入照常（front 会话 /clear 或重开后续接零损失，v2.45 机制）。

### 2.4 唤醒链与双保险

1. 主链：后台 Bash 退出 → harness 自动 re-invoke（原生保证）→ 该轮 UserPromptSubmit 触发 phase 注入新位置 → 模型按注入行动（交互步开问 / 还有非交互段则继续派发 / 门栏则请用户裁决）。
2. 兜底：通知丢失或模型没动 → 下一次任意 Stop 时 advance hook 检测「锁死 + 位置未变」→ 重提示（§2.3 stall 兜底，3 次计数闸）。
3. 段结局的**判读**也机械兜底：模型读 segment_summary.json 转达是软路径；硬路径是 hooks 注入永远以 state.json 当前位置为准（state 是唯一真源，summary 只是便签）。

### 2.5 段跑期间前台会话的状态

段跑期间（drive_mode=on）前台会话收紧为「只交互 + 记账 + /dl」白名单（`front-segment-run-fence-design.md`，2026-08-13 `amplitude_annualized` 抢活实证后落地）：fence 在 drive_mode 早退处区分前台会话（`session_id == state.session_id`）与段工人（`session_id ≠`）——前台 Read/Bash/Skill/Agent 等探查通道全 deny，段工人照旧全放行。用户仍可与会话自由**对话**（问进度、闲聊、AskUserQuestion），但模型不能再顺手探查源码/干非交互步的活（原「干别的活」卖点收回，被 fence 硬拦）。段内活仍由 headless 子会话自己的 hooks（S11/S14 保留）守。

## 3. 关键机制设计

### 3.1 与三堵墙的对账（为什么这次成立）

| v3.0 排除常驻会话的理由 | 本架构的消解 |
|---|---|
| 循环须确定性 Python，模型会话推进不可靠（v2.x 15 注入 0 上屏） | 非交互段循环仍是纯 Python（后台 dl_drive --segment）；模型唯一的循环职责=按逐字命令敲一次派发，不派发有 Stop 兜底重提示，乱动有 fence 拦 |
| 外部进程无法唤醒 TUI（无 IPC） | 唤醒走 harness 原生后台任务通知（派发动作在会话内发起） |
| resume 不刷新 settings/rules，长会话拿不到后续步规则 | v2.x 本来就是 UserPromptSubmit 动态注入当前步 purpose（workflow_phase.py），phase-rules 静态部分不含步级内容；交互步纪律由 hooks 逐事件读 state 执行，无快照问题 |
| 上下文 485k 零锯齿 | 活的全量轨迹在 claude -p 子进程（步均 ~45-60k，步死即清）；前台会话每步只长 ~1-2k（注入+派发+简报）+ 交互步问答（必要成本） |

### 3.2 残余风险（诚实清单）

| 风险 | 对策 | 残余度 |
|---|---|---|
| stall：模型不敲派发命令 | Stop 重提示 ×3 → 停轮等用户（用户回「继续」即恢复） | 低：最坏退化为一键催促 |
| 模型抢干非交互步的活 | fence 白名单硬拦（§2.3）+ 段跑期间收紧（front-segment-run-fence-design，session_id 区分前台/段工人） | 低→已根治 |
| 注入抵达率（v3.0 起因） | 薄上下文改善 + Stop 兜底牙齿（v2.1-2.122 全套 enforcement 栈原样继承） | **中：dogfood 实测点** |
| 前台会话退出杀后台段 | 锁死检测 + 幂等重派（§2.2） | 低 |
| 前台会话长寿命 cache 失效 | 薄会话下每步边界一次 cache miss ≈ 几千 token 重读 | 低 |
| 模型读 summary 转达失真 | state 为唯一真源，注入以 state 为准（§2.4-3） | 低 |

### 3.3 成本模型（对照）

| | v2.x 单会话 | v3.0 全程 driver | v4 前台混合 |
|---|---|---|---|
| 非交互步上下文 | 全进主会话（485k 累积） | 子进程 ~45-60k/步 | 同 v3（子进程） |
| 前台/主会话增量 | = 全部 | 无前台 | ~1-2k/步边界 + 交互问答 |
| 交互体验 | 连续（但被撑爆） | TUI↔进度区弹跳 | 连续且薄 |
| 编排确定性 | 模型推进（病灶） | 纯 Python | 非交互段纯 Python + 模型按一次按钮（有兜底） |

## 4. 里程碑

- **M1 段执行器**：dl_drive.py 抽 `run_until_boundary` + `--segment` 模式（退出码矩阵 / segment_summary.json / front_segment.json 锁 / drive_mode try-finally / breakpoint 去 stdin 化）。单测：退出码六态、锁活性、幂等续跑。
- **M2 hooks front_mode 三分支**：phase 注入派发块 / advance 派发续轮 + stall 计数闸 / fence 非交互步白名单。engine `set_front_mode` + state 初始化。单测：各分支触发矩阵、3 次防抖、fence deny/放行样例。
- **M3 入口与恢复**：dl-launch.sh `--front`（复用 WF_TUI 启动路径 + 置 front_mode）；resume 语义（锁死重派）。**dogfood**：起一个新工作流全程 front 模式，对照 tail_volume 审计口径（上下文曲线/cache_read/块数/stall 次数）。
- **M4 收尾**：SKILL/README/designs 索引同步；默认翻转裁决（dogfood 后用户拍：`--front` 翻转默认 或 维持 opt-in）。

## 5. 验证方案

1. **单测**：M1/M2 所列矩阵；重构红线 = `drive()` 全程模式现有测试全绿（run_until_boundary 抽取不许行为漂移）。
2. **真机 dogfood**：新工作流全程 front 模式；审计口径同 v3.0 设计 §5（上下文曲线/token/耗时/块数），新增 **stall 计数**（重提示触发次数）与**通知抵达率**（后台任务 re-invoke 是否 100%）。
3. **故障注入**：段跑到一半 kill 段进程（锁死重派续跑）/ 段跑期间关前台会话再 `dl --front` 重进（断点续跑）/ 段跑期间用户闲聊（不干扰段）/ 门栏处用户从另一个终端 /dl gate（state 重读兼容）。
4. **回退演练**：同一 state 上 `dl <name>`（v3 driver）与 WF_TUI=1（v2）均可接管——三模式共用 state/evidence 真源，互相可续。

## 6. 不做的事

- 不改节点树 / purpose / interactive 标注 / judge 配置与判据 / evidence 协议 / append-trace / /dl 子命令集。
- 不删 v3 全程 driver（`dl <name>` 现状入口）与 WF_TUI=1 v2 回滚面——三模式并存，state 互通。
- 不做 tmux 弹窗方向（2026-08-11 用户已否决）。
- 不做「段跑期间前台会话的围栏收紧」（§2.5 已评估接受）。
- autodone SIGTERM 收段机制（v3.3）不旁路不修改——front 模式根本不起 TUI 段，该机制只在 v3 driver 路径生效。

## 7. 开放问题（评审拍板）

1. **入口形态**：~~M3 落地后 `dl <name> --front` opt-in；dogfood 通过后是否翻转默认~~ **已裁决（2026-08-11）：默认即 front**（`dl <name>`），v3 driver 退居 `--headless` 逃生门。用户原话诉求「必须要 --front 参数么？」——dogfood 由默认路径直接承担；观察指标不变（stall 率/通知抵达率/fence 误伤），数据恶化则一行翻回。
2. **stall 重提示阈值**：暂定 3 次停轮等用户。是否可调（state 字段）？
3. **段跑期间用户问进度**：模型用 Bash 跑 `dl-cmd.sh status` 自取（fence 白名单已含只读 /dl），是否够用，还是注入里再附一行「段在跑，当前位置 X/Y」？倾向后者（一行，零风险）。
