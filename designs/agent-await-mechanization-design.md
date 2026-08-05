# 后台子代理等待机械化（agent-await-mechanization）

> 起因：2026-08-05 tail_volume_acceleration_annualized u:1 子3/子4 双报错。
> 用户裁决：「模型只决定内容，其他都应该交给脚本；弱模型不是借口，应该用脚本和程序保证」。
> 对齐 [[weak-model-first-principle]]：本设计不新增任何文案叮嘱，四修全部落在机械层。

## 1. 症状与实证

两个报错，同一病灶族：**后台子代理的「已派发」被系统当成「已归还」**。

| # | 症状 | 实证出处 |
|---|---|---|
| 1 | light 档 4 curl 全打 quant.SE 一层，arXiv 一次未轮到 → 零命中 → 升档 full | 子3 trace Q4 报告原文（`evidence/*.jsonl` 第 3 行） |
| 2 | 15:23:02 假性 GATE block「没有任何 evidence skill-trace」，1min 后同内容 pass | `.wf_advance.log:682` = `sub_step_engage_block`（**不是** `deferred_pending_agent`） |
| 3 | 升档 full agent 报告缺席子3，门控放过 | `_check_fetch_report_recorded` 真实载荷重放 = `None`（通过） |
| 4 | 红队未归提前落库被拒（正确），但模型选择不等 | 子4 mech `redteam_report_recorded` 生效 |

### 1.1 根因（决定性证据）

真实 transcript 时间线（`cfeafb35-cf42-4de2-8cc5-4c1eaf01cab2.jsonl`）：

```
15:21:44.685  DISPATCH  call_00_BkOQbmdhfJmd4kd1dlgI5903   (full agent)
15:21:52.843  RESULT    call_00_BkOQbmdhfJmd4kd1dlgI5903   ← "Async agent launched successfully"
15:23:02      Stop → engage_block「无 trace」                ← 假性 block
15:24:11      Stop → pass
15:24:45.099  <task-notification><task-id>a781d26c012a3cee8  ← 真正归还
```

`hooks/workflow_advance.py:152` `_pending_background_agent_count()` 的判据是
「`tool_use_id` 在 Agent 集合但不在 `tool_result` 集合 = 未归」。但**后台 Agent
派发后 1-8 秒即回一条 `tool_result`，内容是 launch ack**（含 `agentId:` 与
`output_file:`），不是 completion。`tool_use_id` 立刻进 `result_ids`，
`agent_ids - result_ids` 恒为空集。

真实 transcript 重放：`pending = 0`（三个 agent 全部）。
**该检测器自落地起从未生效过。**

### 1.2 为什么测试没逮住（fixture 保真度，rubric §3.6 #13 第五例）

`tests/test_workflow_advance.py:511` fixture 写 `"content": "ok"`——同步风格
tool_result。生产的后台 agent 永远先回 launch ack，两者形态不同。
**测试替身与现实不一致 → 断言 `== 0` 与 `== 1` 全部通过，bug 却在生产 100% 复发。**

修复的验证必须用**真实 transcript 重放**，不能只靠手造 fixture。

## 2. 设计原则（用户裁决的操作化）

> 模型只决定内容，其余交给脚本。

| 层 | 归属 | 本设计的落点 |
|---|---|---|
| 内容（claim 写什么、verdict 是什么） | 模型 | 不动 |
| 等不等待子代理 | **脚本**（Stop hook 硬判） | 修 A |
| 报告有没有归位 | **脚本**（机械配对） | 修 B |
| 每层花几次 curl | **脚本**（骨架配额算式） | 修 C |
| 子代理的围栏归属 | **脚本**（派发步归属） | 修 D |

「模型本可以用 TaskOutput 等待」不是解——`TaskOutput` 是模型主动调用的工具，
放行它只给了能力、没给约束。子3/子4 两次都是模型选择不等。
**能力可用 ≠ 行为会发生**，硬等待必须在 Stop hook 侧（系统决定，不给选择权）。

## 3. 四修

### 修 A（根治）：pending 检测改判 completion 信号

**位置**：`hooks/workflow_advance.py::_pending_background_agent_count`

**现判据**（错）：`Agent tool_use_id` ∉ `tool_result tool_use_id` 集合
**新判据**：launch ack 里的 `agentId` ∉ `<task-notification>` 的 `<task-id>` 集合

两个信号都是 harness 稳定契约：
- 派发：tool_result 文本含 `Async agent launched successfully` + `agentId: <17hex>`
- 归还：事件文本含 `<task-id><17hex></task-id>`（`type != queue-operation` 去重）

**真实 transcript 重放（gate 时刻 15:23:02）**：
```
pending = ['a781d26c012a3cee8']   ← 正确识别 full agent 未归
```
→ 走 defer 分支静默放行，假性 block 消失。

**兼容**：同步 Agent（无 launch ack）不进 `launched` 集合 → 不算 pending，
回退原行为。解析失败 -> 0（防御式，不阻断门控）。

**副作用（正向）**：defer 生效后模型不再需要自己决定等不等——end_turn 会被
静默放行，agent handback 后主会话自然续轮。`TaskOutput` 从「必须用」降级为「可用」。

### 修 B：报告收录按派发信号机械配对

**位置**：`dl_flow_engine.py::_check_fetch_report_recorded`

**现判据**：报告项数 ≥ 子2 `tier != none` 的原子数（= 1）
**问题**：升档产生第二个必须归位的 agent，计数器只认原子数不认派发数。
light 空报告占掉唯一名额，full 报告缺席无人察觉。

**新判据（类型无关，按 task-id 配对）**：
```
dispatched = trace 全文里的 17hex task-id 集合
recorded   = 各 qa 项【标题】里的 task-id 集合
missing    = dispatched - recorded   → 非空即 BLOCK
```

标题里的 task-id 是 `ingest_agent_report()` 脚本写入的（`dl_flow_engine.py:4670`
`f"{title}（task-id {task_id}）"`）——**收录即带 id，模型无法伪造配对**。

**真实载荷双向重放**：
| 载荷 | dispatched | recorded | 判定 |
|---|---|---|---|
| 子3 | light + full | light | **BLOCK** ✓（逮住缺口） |
| 子4 | full + 红队 | full + 红队 | **PASS** ✓（不误伤） |

类型无关是关键：子4 同时有取证 agent 与红队 agent，按类型分别计数会引入
两套易错规则；按 id 配对则「派了几个就要收几个」，无类型概念。

同一规则同时收紧 `redteam_report_recorded`（红队 id 也须配对），
两个 mech 共用 `_dispatched_vs_recorded_task_ids()` 单源函数。

### 修 C：light 档每层最少配额

**位置**：`dl_flow_engine.py` fetch-prompt 骨架 §9 + 分档执行参数

**现文案**：`≤2 层源；≤4 curl`——`≤2 层` 是**上限**不是**配额**。
agent 完全合规地把 100% 预算花在 1 层，然后如实上报「未收敛、建议升档」。

**新增（骨架机械算式，非叮嘱）**：
```
light：指定 N 层 → 每层至少 1 次 curl，单层上限 = 4 - (N-1)
       N=2 → 每层 ≥1、单层 ≤3；禁在未轮完所有指定层前耗尽预算
       未轮完即申报升档 = 违反配额，报告须标「配额未用尽」
```
`≤4 curl` 总额不变（不加预算，只禁独占）。

**为什么这条不算「文案叮嘱」**：它是给子代理的**执行参数**（同 `≤12 curl`、
`-m 25`、`| head -c 6000` 一族），骨架由 `fetch-prompt --out` 脚本生成、
模型一字不动。子代理侧无法「决定要不要遵守配额」——配额是算式不是劝告。

配套：删掉「裸响应校验」这类非 claim 用途占额度的空间——§9 补一句
「curl 额度只用于 claim 取证，API 健康度校验不占额（也不需要做）」。

### 修 D：跨步存活子代理的围栏归属

**症状**：子3 派的 full agent 活到子4（15:24:44 才归），其进程内 curl 撞
子4 围栏（`fence_allow=("Agent","TaskOutput")` 不含 Bash）→ 最后 3 次 curl 被拒
（子4 trace Q4 原文「围栏阻断了我最后 3 次 curl」）。

**修 A 生效后此症状大幅收敛**：defer 让子3 门控等到 agent 归还才判，
agent 不再跨步存活。但 defer 只覆盖「trace 未落」路径；若 trace 已落而 agent
仍在跑（修 B 会 BLOCK，模型补 ingest 期间 agent 仍可能在跑），残留窗口仍存在。

**兜底**：`_s15_allowed()` 里 Bash 段增加——当 `_pending_background_agent_count() > 0`
时，放行只读 curl（`_S15_READONLY_CMD_RE` 已有的只读判定 + curl 白名单）。
理由：子代理进程内的 curl 与主会话的写操作性质不同，且此时必有在跑的取证 agent。

**范围收窄**：仅放行 `curl -sS -m <n>`（取证命令模板形态），不放行任意 Bash。
无 pending 时行为不变。

## 4. 改动清单（H9：4 文件，预计 ~180 行）

| 文件 | 改动 | 行数估 |
|---|---|---|
| `hooks/workflow_advance.py` | `_pending_background_agent_count` 换判据（修 A） | ~45 |
| `dl_flow_engine.py` | `_dispatched_vs_recorded_task_ids` 新函数 + 两 mech 改判（修 B）；骨架配额（修 C） | ~70 |
| `hooks/workflow_step_fence.py` | pending 时放行只读 curl（修 D） | ~25 |
| `tests/test_workflow_advance.py` 等 | 真实载荷重放测试 + fixture 保真度修正 | ~40 |

`SETTINGS_TEMPLATE_VERSION` 不需 bump（未改 settings 模板实质内容）。

## 5. 验证计划（case 验证，不只跑单测）

1. **真实 transcript 重放**（修 A）：拿 `cfeafb35-*.jsonl` 断言 gate 时刻
   `pending == ['a781d26c012a3cee8']`；三个 agent 各自的 launch/notif 时刻齐备。
   载荷入库 `tests/replays/`（对齐 v2.76 义务执行资产入库先例）。
2. **真实载荷双向重放**（修 B）：子3 必 BLOCK、子4 必 PASS（已预验证，见 §3 表）。
3. **fixture 保真度修正**（修 A）：现有 `"content": "ok"` fixture 改为真实
   launch ack 形态，并**新增一条**同步 agent fixture 保证兼容路径。
4. **全量回归**：`pytest tests/ -q` 基线 777 passed 必须不降。
5. **骨架渲染核对**（修 C）：`fetch-prompt --out` 输出含配额算式，人工读一遍。

**验收判据**：修 A 的重放测试若用手造 fixture 通过而真实 transcript 失败，
即为 fixture 失真复发——必须以真实 transcript 为准。

## 6. 沉淀（写入 skill rubric）

- §3.6 #13 补第五例：**异步工具的 ack 与 completion 是两个信号**；
  fixture 用同步形态替身 → 检测器生产 100% 失效而测试全绿。
  写异步等待检测必须先 dump 一条真实 transcript 确认信号形态。
- §3.5 补：**「放行能力」≠「强制行为」**——`TaskOutput` 放行两版本后模型
  仍两次选择不等。行为约束必须在系统侧（hook 硬判），不能靠给工具+文案。
- §3.5 补：**上限 ≠ 配额**——`≤N 层` 允许 100% 预算独占单层。
  多资源分配须写配额算式（每项最小值 + 单项上限），不能只写总额上限。
