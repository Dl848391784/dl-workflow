# 发现台账设计（discovery ledger）

> 立项依据：`amplitude_annualized` 工作流 `understand:1 子步骤 2` 实测用 43 次工具调用做代码考古，产出的中间发现（"X 在 file:line"、"Y 调 X"、"数据值 Z"、"git blame 是 commit W"）**只活在那一个 headless 会话里**，会话结束即丢失。留存到 evidence 的只有**结论**（因果链 + file:line），不是**发现过程**。step3/4 开新会话后重查这些事实，属重复取证。
>
> 目标：把「客观事实」类中间发现以结构化方式落账，后续步骤透明复用，省掉重复搜索往返——**不替代验证，只减少重复取证**。

## 0. 关键区分（设计的边界）

| 类型 | 例子 | 能否安全复用 | 处置 |
|---|---|---|---|
| **客观事实**（确定性） | symbol 定义/调用、git blame、数据值 | ✅ 重查是纯浪费 | 落账复用 |
| **判断/推理** | 根因是什么、"年化是否合理" | ❌ 必须独立验证 | 仍走 judge/红队 |

当前架构「每个子步骤独立重查」的本意是用独立验证兜弱模型的错。**台账只存客观事实（且是已过门栏步骤产出的 file:line），判断仍独立验证**——复用已验证事实 ≠ 复用未验证猜测。

## 1. 核心设计

**发现台账 = 每工作流一个 `discoveries.jsonl` + `dl codebase query` 工具级透明去重。**

- **自动落账**：`dl codebase query --symbol/--history` 执行后，把结构化结果 append 进台账（工具自己写，不靠模型记得记）。
- **工具级去重**：同一 query 再次执行时，工具先查台账，命中就返回缓存结果（标记 `"source": "discovery-ledger"`）。**模型行为零改变**——它照常 query，工具透明地去重，不依赖弱模型"查前先读台账"的遵从。
- **key 去重**：`symbol:X` / `history:<file>:<line>` 为键，同键不重复 append（只保留首次，或刷新 ts）。

## 2. Schema（discoveries.jsonl，每行一个 JSON）

```json
{
  "key": "symbol:convert_return_to_percentage",
  "kind": "symbol",                        // symbol | history
  "query": "convert_return_to_percentage", // 原始查询输入
  "result": { "definition": {...}, "callers": {...}, "impact": {...} },
  "step": "understand:1#2",               // 产出子步骤（溯源）
  "ts": 1692123456                        // epoch（freshness 判据）
}
```

## 3. 落账与读取

### 3.1 落账范围（只收高价值确定性查询）

| 子命令 | 是否落账 | 理由 |
|---|---|---|
| `--symbol`（codegraph） | ✅ 落账 | 结构性事实，确定性，结果小，重查相对贵 |
| `--history`（git blame/log） | ✅ 落账 | 历史事实，确定性，结果小 |
| `--string`（grep） | ❌ 不落账 | grep 便宜，结果可能巨大（上千 matches），缓存 ROI 低 |

### 3.2 落账位置

`<项目>/.claude/workflows/<name>/discoveries.jsonl`（与 state.json、node-rules 同层，运行时产物，随工作流归档清理）。

`dl codebase query` 从 cwd（worktree 路径含 `<name>`）反查工作流名——**在 worktree 内透明去重，worktree 外保持通用工具原行为**（不破坏组件 A 的跨项目通用性）。

### 3.3 去重语义

1. 执行前按 `key` 查台账 → 命中 → 返回缓存结果 + `"source": "discovery-ledger"` + 原 `step`/`ts`。
2. 未命中 → 执行 codegraph/git → append 新条目 → 返回 `"source": "fresh"`。
3. 台账损坏/不可读 → 静默降级为"无账"，正常执行不 append（宁纵勿枉，不阻断取证）。

## 4. 生命周期与新鲜度

- **run 内稳定**：understand/plan 阶段是只读阶段，代码不变 → 台账在 run 内无新鲜度问题。
- **state-reset**：回滚已作废工作，台账应一并清空或标记作废（旧发现可能基于被回滚的结论）。设计：`state-reset` 时删除 `discoveries.jsonl`（与 evidence 硬删同口径）。
- **跨 run**：`<name>` 重跑时若台账残留，`ts` 用于 freshness 判读；简单起见，`dl <name>` 启动时若 `created_at` 变化则重建台账（覆盖旧账）。

## 5. 消费侧（后续步骤怎么用）

- **节点规则注入**：`ensure_node_rules` 里加一句「本工作流有发现台账 `<path>`，`dl codebase query` 会自动去重，无需手工查账」。
- **透明性**：因为去重在工具层，模型无需新增行为；台账位置注入只是为了模型在需要时能 `Read` 溯源。
- **step3 的 codegraph 前置**：现有 step3 已要求 `codegraph 新鲜度前置 + 查询留痕`——台账去重与之一致，不冲突（台账命中即视为"本次已查"）。

## 6. 边界（不做的事）

- **不缓存 `--string`**：grep 便宜 + 结果巨大。
- **不缓存项目专属工具（组件 B）的产出**：本项目工具后续可接入同机制（工具头过滤已共用 `project_tools`），但首版不做。
- **不落账 Read/Grep/Bash 的裸发现**：非结构化、难去重、弱模型随手记又是幻觉源。只收「工具已结构化输出」的 symbol/history。
- **不替代验证**：台账只存客观事实，判断（根因/verdict）仍走 judge/红队/三关质检，机制零改动。

## 7. 预期收益（诚实评估）

- **省的是重复取证**：step3/4 对同一 symbol/history 的重复 codegraph/git 查询会命中缓存，省掉搜索往返 + 部分"决定查什么"的思考轮。
- **不是大砍**：step3/4 的大头是**判断轮**（因果链综合、verdict 合成），不是搜索轮。台账是次要杠杆；最大杠杆仍是一次通过率（memory 既有结论）。
- 量化验收：跑一轮工作流，对比「台账命中次数 / 总 symbol+history 查询次数」+ step3/4 墙钟变化。

## 8. 测试 / 回滚

1. **单测**：`dl codebase query` 在 worktree 内对同 symbol 二次查询返回 `source=discovery-ledger` 且不重跑 codegraph（monkeypatch `_run` 计数）；`--string` 不落账；台账损坏静默降级；state-reset 清账。
2. **回滚**：台账是纯增量，不删 `--symbol` 正常执行；置空去重逻辑 = 现状（每查必新）。

## 9. 实施面（预估）

- 主改 `scripts/workflow/dl_codebase.py`（落账 + 去重）+ `dl_flow_engine.py`（state-reset 清账 + node-rules 注入一句）+ 测试。约 2-3 个小 task，非 codebase-toolbox 量级。
