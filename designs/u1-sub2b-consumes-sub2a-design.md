# understand:1 子2b 消费子2a atomic_questions 设计

> 立项依据：`amplitude_annualized` 实测 understand:1#2a（规划）→#2b（因果链挖掘）之间出现**重复探索**：子2a 已用 `--string` 摸清问题域，子2b 又从头做 `codebase trace`/`query --history`，未消费子2a 规划产物。导致子2b 475s 墙钟、34 次工具调用、13.5M token，其中 90% 是工具间思考间隔。
>
> 目标：让子2b 按子2a 的 `atomic_questions` 执行取证，消灭「重新发明调查计划」的浪费。

## 0. 实测数据（amplitude_annualized 当前 run）

| 指标 | 子2a（规划） | 子2b（执行） |
|---|---|---|
| wall time | ~240s | **475s** |
| 工具调用 | 14 | **34** |
| Bash（含 codebase） | 2（`--string "annual"`、`"年化"`） | 20 |
| Read | 12 | 13 |
| 思考间隔占比 | — | **90.5%** |
| token（input-ish） | — | **13.5M** |
| `discoveries.jsonl` 命中 | — | **0/6** |

子2b 实际查询：
```bash
# 这些符号/历史本应在子2a 规划阶段已识别
dl codebase trace load_backtest_results
dl codebase trace BACKTEST_RESULT
dl codebase query --history "summary/report/data_loaders.py:166"
dl codebase query --history "web_ui/templates/_macros.html:57"
dl codebase query --history "web_ui/templates/_section_backtest.html:69"
```

子2a 仅做了字符串搜索（`annual`、`年化`），未产出符号级取证计划，子2b 只得重新探索。

## 1. 问题根因

当前 `understand:1#2b` 的 `Step.input = "step2.atomic_questions"` 只是**声明式引用**，模型能看到引用文字，但：

1. **没有自动把子2a 的 atomic_questions 内容注入子2b 上下文**——模型要自己从 evidence 里读；
2. **atomic_questions 格式没有符号/文件字段**——子2a 只能描述问题，不能锁定要查的符号；
3. **子2b purpose/selfcheck 没有强制「按清单执行」**——模型容易退回「边搜边想」模式；
4. **gate 不检查子2b 是否消费了子2a 的计划**——重复探索也能过门。

结果是：子2a 的规划产物是**建议性的**，子2b 可以忽略。

## 2. 设计目标

| # | 目标 | 验收方式 |
|---|---|---|
| 1 | 子2b 启动时自动拿到子2a atomic_questions 全文 | 子2b 首轮工具调用前 context 含 atomic_questions |
| 2 | 子2a 产出带 `symbols`/`files` 的 atomic_questions | append-trace 机械校验 |
| 3 | 子2b 必须按 atomic_questions 执行，禁止重新 broad exploration | gate 判据 + 工具围栏 |
| 4 | 子2b 允许在深挖中发现新符号，但必须显式留痕「补充」 | gate 例外条款 |
| 5 | 不破坏现有 plan-first 拆分和 framing 反转成果 | 重放现有 pass/block 载荷 |

## 3. 方案总览

```
子2a（规划）
  └── 产出 atomic_questions[]
        ├── q: 原子问题描述
        ├── tier: none|light|full
        ├── tier_reason: 分档理由
        ├── symbols: ["load_backtest_results", "BACKTEST_RESULT", ...]   ← 新增
        └── files: ["summary/report/data_loaders.py:166", ...]          ← 新增

子2b（执行）
  ├── input = step2a.atomic_questions（内容自动注入）
  ├── purpose: 按 atomic_questions 逐项挖因果链
  ├── 从 symbols/files 出发用 codebase trace / --history
  ├── 禁止 broad string search（除非显式声明「补充」）
  └── 产出因果链 trace
```

## 4. 具体改动

### 4.1 atomic_questions 格式扩展（子2a）

在 `dl_flow_nodes.py` 子2a 的 `extra_payload_keys` 中注册新字段，并在 `fetch_tier_items` 同级新增机械校验。

```python
extra_payload_keys=(
    ("atomic_questions", "fetch_tier_items"),
    ("atomic_questions", "atomic_mece_alignment"),
    ("atomic_questions", "atomic_question_symbols"),   # 新增
),
```

`atomic_question_symbols` 校验：
- 逐项检查 `symbols` 为字符串列表（可空，但 tier≠none 时非空）
- 逐项检查 `files` 为字符串列表（可空）
- 若 `tier != "none"` 且 `symbols` 和 `files` 都为空 → 机械拒（要求子2a 锁定取证入口）

**为什么 tier≠none 必须非空**：外部取证/light/full 都需要具体符号或文件锚点；none 档是仓内即可定答，可空。

### 4.2 子2b 上下文自动注入（engine）

新增 `ensure_node_rules` / handoff 时，把子2a 的 atomic_questions 内容拼进子2b 的 system prompt 或 attachment。

实现位置：`dl_flow_engine.py` 中渲染当前步 node-rules 时，若 `step.input` 指向 `"step2a.atomic_questions"`，调用 `_load_atomic_questions(project_root, name)` 并把结果 JSON 注入到子2b 规则头部：

```
## 本步输入：子2a atomic_questions
<JSON 或 markdown 表格>

纪律：
- 必须按上表逐项执行因果链挖掘
- 优先从 symbols/files 出发使用 dl codebase trace / --history
- 仅当深挖中出现上表未覆盖的新符号时，才允许 broad string search，且必须在 trace 中显式标注「补充符号：X，原因：Y」
```

**为什么不靠模型自己 Read evidence**：弱模型会忽略或读错；自动注入是机械保证。

### 4.3 子2b purpose/selfcheck 更新

`dl_flow_nodes.py` 子2b `purpose` 和 `selfcheck` 增加：

- purpose 明确：「按子2a atomic_questions 逐项执行，不重新拆解问题」
- selfcheck 增加：
  1. 是否从子2a 的 symbols/files 出发？
  2. 是否每个原子问题都挖到了实测层？
  3. 是否有表外 broad string search？若有，是否标了「补充」及原因？

### 4.4 子2b 工具围栏（PreToolUse）

在 `workflow_step_fence.py` 中，对子2b 增加软约束：

- 首工具调用前必须先完成 `Read` 子2a atomic_questions 注入块（已由 4.2 自动注入，此条主要防旧态/异常）
- 检测到 broad string search（`dl codebase query --string` 且无「补充」标注）→ deny 并提示「先按 atomic_questions 的 symbols/files 执行」

**为什么是软约束不是硬 deny**：5-Whys 迭代中确实可能发现新符号；硬 deny 会逼模型撒谎标注。用「首次 broad search 需补充留痕」即可。

### 4.5 gate 判据更新（子2b）

新增/强化两条：

1. **覆盖对齐**：子2b 的 q/a 必须能映射回子2a 的每个 atomic_question（缺项 block）
2. **禁止重新规划**：子2b 不得出现新的 MECE 原子清单或重新定档（tier 重定 block）；只允许在 `a` 中标注「补充原子/升档」并留痕

原 gate 保留：因果链每环 file:line、竞争假设、近因/根因等。

### 4.6 子2a gate 更新

新增判据：
- tier≠none 的原子必须提供 `symbols` 或 `files`（与 4.1 机械校验对齐）
- `symbols`/`files` 必须与 q/tier_reason 一致（judge 语义判）

## 5. 对 discovery ledger 的影响

本设计**不替代** discovery ledger，而是让 ledger 有机会真正命中：

- 子2a 若预先用 `dl codebase trace` 锁定符号，结果会进 ledger
- 子2b 执行相同 trace 时自然命中缓存
- 即使子2a 不落账，子2b 的查询也会因「按清单执行」而更聚焦，减少 broad search

如果子2a 选择用 `--string` 做初步侦察（如当前 run），则 ledger 仍无法命中子2b 的 trace。这是允许的，但子2a 需要在 `symbols`/`files` 里列出 string search 发现的关键符号，让子2b 直接 trace。

## 6. 测试计划

1. **单测**
   - `atomic_question_symbols` 机械校验：tier≠none 空 symbols/files → 拒；none 档可空 → 过
   - `_load_atomic_questions` 返回含 symbols/files 的形态
   - 子2b node-rules 渲染含注入块

2. **真实载荷重放**
   - 用 amplitude_annualized 当前子2a pass 载荷，验证新子2a gate 不 block
   - 用当前子2b pass 载荷，验证新子2b gate 仍 pass（因载荷确实有因果链）
   - 构造「子2b 重新规划」载荷，验证新 gate block

3. **端到端冒烟**
   - 新 run amplitude_annualized，统计子2b 工具调用数、思考间隔、token
   - 目标：子2b broad string search 次数 ≤1，工具调用 ≤20（当前 34），思考间隔占比 ≤75%（当前 90.5%）

## 7. 风险与边界

| 风险 | 缓解 |
|---|---|
| 子2a 规划不足，强约束导致子2b 无法执行 | 保留「补充」例外通道 + 就地补规划留痕 |
| symbols/files 字段增加模型负担 | 机械校验 + selfcheck 减负；tier=none 可空 |
| 旧 evidence 无 symbols/files 不兼容 | `atomic_question_symbols` 校验宁纵勿枉：旧形态无该键 → 跳过 |
| 自动注入 atomic_questions 增加子2b 上下文长度 | 只注入当前步需要的内容（子2a 一条 trace），通常 <2k tokens |

## 8. 不做的事

- 不改子3/子4 的编排（本次只修子2a→子2b 消费链）
- 不删除 discovery ledger（继续作为工具级去重底座）
- 不强制子2a 必须用 `dl codebase trace` 预查（保留 string search 侦察灵活性）

## 9. 预期收益

保守估计（假设子2a 仍主要用 string search，但产出 symbols/files）：
- 子2b 工具调用从 34 降至 15-20
- 思考间隔从 90.5% 降至 70-75%（消灭「决定查什么」的试探轮）
- token 从 13.5M 降至 8-10M

若子2a 进一步用 `dl codebase trace` 预查并命中 ledger，收益更大。

## 10. 落地顺序

1. 改 `dl_flow_nodes.py`：atomic_questions 加 symbols/files + 机械校验注册
2. 改 `dl_flow_engine.py`：子2b 自动注入子2a atomic_questions
3. 改 `dl_flow_nodes.py`：子2b purpose/selfcheck/gate 更新
4. 改 `workflow_step_fence.py`：子2b broad search 软约束
5. 同步 `references/node-design.md` 摘要块
6. 写测试 + 重放 + 冒烟
