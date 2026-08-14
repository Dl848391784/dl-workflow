# 代码考古提效三杠杆设计

> 立项依据：`understand:1 子步骤 2`（causal-inference）实测 43 次工具调用，单次搜索 ~0.3s，但**两次搜索之间的思考**（读结果 + 决定下一步查哪）占了大头（最长 73s 间隔）。这些思考分两类：**读结果+理解**（因果推理本身，不可省）与**决定下一步查哪**（确定性查找部分可省）。本设计用三个杠杆消灭可省部分。
>
> 通用性约束（用户明确）：三杠杆必须跨项目通用，不耦合任何项目数据契约。框架给通用代码考古 + 通用方法论，项目给领域模板（component B）。

## 0. 三个杠杆总览

| # | 杠杆 | 消灭什么 | 规模 | 通用性 |
|---|---|---|---|---|
| 1 | `dl codebase trace <symbol>` | 单层内"定位→callers→callees→git 历史"的多次"决定下一步" | 小 | 纯 codegraph/git，100% 通用 |
| 2 | 通用代码考古路线模板进 node-rules | "下一步查哪"从开放式推理降级为模板跟随 | 小 | 通用方法论骨架 |
| 3 | Plan-first 拆步（understand:1 子2 拆分） | 规划思考被 43 次搜索打断 | 大 | 通用方法论，但动编排 |

杠杆 1/2 可直接设计到实现粒度；杠杆 3 动 step 分解（触及"步数=失效模式族数出来"原则），本设计只给方向 + 论证，实现前需单独深入。

## 1. 杠杆 1：`dl codebase trace <symbol>`

### 命令面

```bash
dl codebase trace <symbol>
# 等价于一次返回：
#   definition  = codegraph query <symbol>
#   callers     = codegraph callers <symbol>
#   callees     = codegraph callees <symbol>
#   impact      = codegraph impact <symbol>
#   history     = git log -S <symbol> --oneline --max-count 50
```

### 与现有 `--symbol` 的区别

现有 `query --symbol` 已返回 definition+callers+impact。`trace` 在其上**补 `callees` + `git 历史`**，形成"符号关系全景"——单层因果链取证（谁定义/谁调/调了谁/影响面/何时引入）一次拿全。

### 输出 + 落账

- 输出 JSON，结构 `{symbol, definition, callers, callees, impact, history}`。
- 自动落账 + 去重（key=`trace:<symbol>`，沿用 discovery-ledger 机制，`source` 字段同 `query --symbol`）。

### 实现

- `dl_codebase.py` 加 `trace` 子命令 + `query_trace(symbol)` 函数（复用 `_codegraph_json` + `git log -S`）。
- `codegraph callees` 已确认存在（v0.9.8）。

## 2. 杠杆 2：通用代码考古路线模板进 node-rules

### 内容（通用方法论，非项目领域模板）

在 `understand:1 子步骤 2`（causal-inference）的 purpose/节点规则里，追加一段**通用取证路线**：

> 单个原子问题的标准取证路线（按需跳步）：
> 1. `dl codebase trace <symbol>` 一次拿定义+callers+callees+impact+历史（优先于逐条 grep）
> 2. 需要字符串/模式定位时用 `dl codebase query --string`（排除 .git/.claude/.superpowers）
> 3. 需要某行"何时引入"用 `dl codebase query --history <file>:<line>`
> 4. 只读关键文件正文（Read）
>
> 纪律：symbol 关系查询优先走 `trace`，grep 只用于正则/字符串搜索；`dl codebase query` 自动落账去重，重复查询零成本。

### 边界

- 框架只给**通用骨架**（symbol 关系 → 字符串 → 历史 → 读文件）。
- 项目领域模板（factor 年化怎么拆、别的项目怎么拆）走 component B 工具注册 + 项目级 skill，**不进框架 node-rules**。

### 实现

- `dl_flow_nodes.py` 的 understand:1 子2 `Step.purpose`（或 node-rules 渲染）追加上述路线段。
- 单源：与 `ensure_node_rules` 的「发现台账」段同通道。

## 3. 杠杆 3：Plan-first 拆步（方向 + 论证，待深入）

### 现状问题

子2（causal-inference）把两件不同性质的事混在一个 step 里：
1. **规划**：MECE 拆原子问题 + 为每个问题定取证路径 + 分档（none/light/full）——这是"想清楚查什么"。
2. **执行**：沿 5-Whys 搜索 + 挖因果链 + 竞争假设——这是"边搜边挖"。

规划思考被 43 次搜索打断，弱模型在连续打断下质量下降 + 返工。

### 方向

拆成两个子步骤：

| 子步骤 | 职责 | 产物 |
|---|---|---|
| 子2a 规划 | MECE 拆原子问题 + 每问题定取证路径 + 分档 | `atomic_questions` 清单（含 tier + 取证路径） |
| 子2b 执行 | 按规划取证 + 5-Whys 挖因果链 + 竞争假设 | 因果链 trace |

### 收益论证

- 子2a 的规划思考**连续聚焦**（不被搜索打断），弱模型一次想清楚，质量高于"边搜边想"。
- 子2b 的取证**可机械化**：结合杠杆 1（`trace`）+ discovery ledger，搜索不再需要"决定下一步"，只需"按清单执行"。
- 现有子2 的 atomic_questions（含 tier）已经是"规划产物"——拆分只是把它从"和搜索混在一起"里抽出来，不是新增概念。

### 为什么不能 100% 规划（诚实边界）

5-Whys 是迭代的：每挖一层，下一层在哪是搜完才知道的。所以子2b 仍保留迭代——子2a 规划的是**已知原子问题的取证路径**，不是**完整因果链**。层与层之间的因果跳跃仍需模型在子2b 里现场判断。

### 风险与前置论证（实现前必须回答）

1. **步数 6→7**：understand:1 子步骤数变 7，触及 node-rules 渲染、gate/judge 机制、`last_judged_trace` key、segment chain 白名单（`understand:1` 的子2-子5 链要改成子2a/2b/3/4/5）。
2. **失效模式族原则**：memory 铁律"步数=失效模式族数出来"——拆分前必须论证"规划与执行混在一起"本身是一个失效模式（弱模型边搜边想迷失），且拆分后不引入新失效模式（如子2a 规划与子2b 执行脱节）。
3. **judge 判据迁移**：子2 现有 gate 判据（因果链每环 file:line、atomic_questions 对齐等）要拆到 2a/2b 两个 gate，各自判什么需重新钉死。
4. **返工回路**：子2b 执行发现子2a 规划不足时，如何回退（state-reset 回子2a？还是子2b 内就地补规划？）。

**结论：杠杆 3 方向成立，但属于编排层大改，需单独设计（含失效模式族论证 + judge 判据拆分 + 返工回路），不在本设计直接给实现粒度。**

## 4. 通用性边界（重申）

| 层 | 装什么 |
|---|---|
| 框架 | `dl codebase trace`、通用路线模板、plan-first 方法论 |
| 项目 | 领域模板 / 数据契约脚本（component B） |

三杠杆的框架侧实现全部基于 codegraph/git/grep 的**代码结构语义**，不涉及任何项目数据契约。

## 5. 落地顺序

1. **杠杆 1**（`dl codebase trace`）：纯增量，建立于 codebase toolbox + discovery ledger，最小。先做。
2. **杠杆 2**（路线模板）：node-rules 文案追加，小。随后。
3. **杠杆 3**（plan-first 拆步）：单独设计 + 失效模式族论证，最后，且独立走完整 design→plan→implement。
