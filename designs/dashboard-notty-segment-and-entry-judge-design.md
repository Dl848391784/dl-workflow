# dashboard 无 TTY 交互段 + 入口判决设计（E2E sweep run1 实爆）

> 2026-08-31，dashboard 全面 E2E（e2e-full-sweep，ac-deepseek1）run1 抓出。
> 前序：dashboard-segment-autocontinue-design（no-TTY 自动续跑）、dashboard-answered-marker-design（已答标记）。
> 正是这两项修复**叠加**暴露了下层两个结构 bug——本设计收口。

## 1. 死循环实爆链（run1 观测，5 圈，每圈 ~$0.6-1.0）

```
inject（trace 落库）→ 端点重启 driver
  → 主循环入口不判未判决 trace（旧路径只有 _after_tui_exit 判）
  → 重跑 prep（95-178s，$0.4-0.7）→ 重 stash 问题（内容变 → 标记按设计失效）
  → 派交互式 claude 当 needuser 段 → 无 TTY 下挂起永不返回（无段台账/无段结束行）
  → driver proc-wait 干等 → dashboard 见 inject_ready（旧台账）→ 再 inject
  → 端点 killpg 卡死 driver+段（2461426 式僵尸泄漏一路烧 CPU）→ 新 driver 又重跑 prep → 循环
```

**根因 A（BUG-2，循环发动机）**：driver 主循环入口无「先判未判决 trace」逻辑（`_after_tui_exit` docstring 自述）。segment-autocontinue 之前，判决靠「TUI 退=全退」时的 `_after_tui_exit` 兜底；no-TTY 自动续跑绕开它之后，注入轮重启的 driver 永远走「重开本步」而非「判决已落库产出」。

**根因 B（BUG-1，挂起点）**：dashboard（stdin=DEVNULL）下 `run_tui_step` 派的是交互式 claude（无 `-p`）。弱模型调 AskUserQuestion 时无 TTY 可答 → 进程挂起；不调则能侥幸结束（今晨两次 rc=0 即侥幸）——行为随模型摆动，结构上必然偶发死锁。证据：e2e-full-sweep 圈 2-5 的 needuser 段零台账零结束行，进程靠下一圈 inject 的 killpg 清掉。

**旁证**：sweep 停止后 driver 终于判过积攒的 trace，实例立刻 u:1#1→#3——「只要判了就能走」。

## 2. 设计

### 2.1 入口判决（BUG-2）

driver `drive()` 主循环进入前：对当前步跑一次 `gate_sub_step_at_stop`：
- **advanced** → 照常进主循环（state 已推进，从下一步干起）——注入轮重启即判决即推进，prep/restash/重问整圈消失
- **block** → 判词 seed 成 `pending_rework` 进主循环（与既有返工流同路）
- **escalate** → 断点（no-TTY EOF 干净退出；标记已被 block 裁决放行，用户可重答）
- **none**（无新 trace）→ 零成本照常（`last_judged_trace` 同 sha 防重判，天然幂等）

### 2.2 no-TTY 一次性交互段（BUG-1）

`run_tui_step` 开头判 `_stdin_attached_to_terminal()`：
- **有 TTY**（终端 v3）→ 原交互式路径，零改动
- **无 TTY**（dashboard/无人值守）→ 改走 `run_session`（`claude -p` stream-json 一次性，已知可靠结束）+ `disallow_ask=True`（AskUserQuestion 结构性移除——无真人可答，工具在=挂起引信）。prompt/settings/rules 与交互路径同源（build_step_prompt needuser=…、ensure_tui_settings/rules）。返回 (rc, sid) 与原型一致；调用方/台账（tui-step/tui-step-needuser）/收段分流（_handle_tui_segment_end）零改动
- 不写 tui_segment.json（无交互进程可 SIGTERM，autodone 通道无意义；注入 trace 段外落库由入口判决覆盖）

一次性段产物语义：提问落盘（prep 已 stash）+ 会话含问答上下文（inject --resume 的靶子）+ 可靠结束落台账（inject_ready 就位）。段尾 gate none → 既有 tui-none 直断点（无重试空问）→ EOF 干净退出 → dashboard 答题 → inject → 重启 → 入口判决 → 推进。**闭环。**

### 2.3 展示批次（同轮静态审计实锤，一并收口）

1. **gate 按钮全程显示**：前端 `hidden = done || !(held || gate==="pending")`，而 gate 从启动就是 pending → 按钮常显、点了报错。修：scanner 增 `gate_actionable = held_for_gate or (gate=="pending" and phase in GATED_AFTER)`（与 /dl gate 可作用域逐义对齐），前端 `hidden = done || !gate_actionable`；侧栏 isWaiting 同步换源
2. **gate_release 放不了阶段闸门**（功能 bug）：dashboard 直调 engine subgate-pass（仅门栏路由），阶段闸门（held 之外的第二等待态）撞「无标记」报错。修：改调 `dl-cmd.sh gate`（/dl gate 同路由双分支单源）
3. **侧栏等待圆点失真**：scanner.need_user = 文件存在未过滤陈旧卡。修：绑定过滤规则下沉 scanner 单源（`need_user_stale(data, state)`），scan bool 与 detail 载荷共用（detail 保留解析失败错误卡）
4. **fp 缺直接依赖**：refreshDetail 指纹补 `d.answered` + `d.need_user?.ts`（标记翻面/新题落盘即重渲，不等间接触发）

## 3. 不改的面

- 终端 v3 全路径（TTY 判别保护）；autodone 通道；inject 时序铁律；已答标记语义（本设计让它终于不被无谓失效）
- tui-none 直断点（既有，无需新增 no-TTY 快道——本就无重试）

## 4. 测试

- driver：入口判决 advanced→续走 / block→seed rework / none→幂等不重复判；run_tui_step no-TTY→run_session 一次性+disallow_ask+台账语义不变 / TTY→原路径
- actions：gate_release 走 dl-cmd.sh gate
- scanner：need_user_stale 三态 / gate_actionable 四态（held / plan+pending / understand+pending / done）
- app：detail 用单源过滤（陈旧卡 null 不变）+ info.gate_actionable 透传
- E2E 复跑（ac-deepseek1）：注入 → 标记持续覆盖（无 restash 失效）→ 判决 → 推进 → 无挂起进程、无僵尸、单圈成本显著降

## 5. 兼容与回滚

- 在跑实例：driver 下次重启即新逻辑（入口判决对积攒 trace 只会推进不会误判——last_judged 幂等）。web_ui_interaction（u:2#1 等答）答完后吃全量新路径
- 回滚面：入口判决单函数可摘；run_tui_step 分支可翻；展示批次各自独立
