# 取证深度档与取证策略重设计

> 状态：待评审。触发 = 2026-08-13 `amplitude_annualized` sub3 审计：light+full 两个
> 外部取证 agent 共 17 次 curl，有效产出仅 4 次（24%），其余 13 次全空手/无关/权限
> 受限；且「48.7% 是否合理」被错标 light，串行升档 full，白烧 1.6min + 382K token。

## 1. 背景与实证

### 1.1 curl 有效率 ~24%

| agent | curl | 有效产出 |
|---|---|---|
| light | 5 | 0（全空/无关/超时/方向冲突） |
| full 反证 | 7 | 0（全空/无关/权限受限） |
| full 支持 | 5 | 4（empyrical 定点源码） |
| 合计 | 17 | 4（24%） |

full 里唯一有效的，是**定点抓 empyrical 源码**那 4 下；其余 13 次（76%）都是
OpenAlex/arXiv/SE/HN 的**关键词泛搜索**，全部空手。

### 1.2 三层根因（由浅入深）

1. **查询词没翻译**：用 repo 内部术语 `coverage` 去搜学术，业界叫
   "annualization with missing trading days"，术语不翻译 → 结构性搜不到。
2. **取证策略错**：「年化折算方法」不是学术问题、是工程惯例，权威在业界标准库
   **源码**（empyrical/pyfolio），不在学术文献。当前「五层泛扫（学术→社区→开源→
   定点）」方向就错了——有效的那 4 下恰恰是「定点查 empyrical」，而它被排在了最后。
3. **tier 判据缺「值不值得」**：原子B「48.7% 是否合理」的外部取证，对主结论
   「4866.7% 是显示 bug」（原子A 已仓内读证）是边际的——取证结果不改变结论方向。
   这类题本不该派外部 agent。

另有两处既有偏差（已在前面轮次定位）：
- **light 定义错**：把「年化量级合理性判断」当 light 的典型例子，但它无单一权威
  （随策略类型/周期/杠杆变化），本质是 full 题。
- **tier 判定时机错**：tier 定档（sub2 的 ⑤）埋在因果链（②③④）之后，模型做完
  5 Whys 深挖后锚定在「数值机制」上，把「量级合理性」误判成「单一数值锚点」（light）。

## 2. 方案

### 2.1 改动 A：sub2 tier 判据（改 `dl_flow_nodes.py` 里 sub2 的 purpose，3 处）

**A1. 删 light 错误例子**
- 现：`light=单一事实/数值 claim，公开有权威锚点（如年化量级合理性判断）`
- 改：`light=有具体、公认、一次即得的单一事实/数值（如某因子历史年化的明确文献值）`
- 把「量级合理性判断」挪到 full 的例子。

**A2. 加「值不值得取证」判据（定档前第一问）**
- 加：`定档前先问：外部取证结论（无论证实还是证伪）是否会改变「问题是否成立」或
  「修复方向」？不会 → 该原子问题标 none（仓内佐证即可，不派外部 agent）。`

**A3. tier 前置**
- 把 `⑤取证深度档` 从 sub2 末尾（因果链后）挪到 `①MECE 拆解` 后、`②因果链` 前。

### 2.2 改动 B：sub3 取证策略（curated registry）

**B1. 加权威源注册表**（放 node-rules，sub3 查表定点）：

```
取证权威源注册表（按 claim 类型定点抓，禁先泛搜学术数据库）：
- 年化折算/回测统计惯例 → empyrical / pyfolio / quantstats / vectorbt / zipline 源码
- 因子收益量级/方法论 → Fama-French 数据库 / WRDS / 具体 SSRN 论文
- 框架 API 语义 → 官方文档 / docstring
- 单点数值 → 已知定点网页/文档
```

**B2. 改取证策略**（sub3 的 purpose）：
- 取证第一步 = 按 claim 类型**查注册表、定点抓权威源**；
- 查询词先**翻译成业界术语**（禁 repo 内部黑话，如 `coverage` → `annualization with
  missing trading days`）；
- 泛搜索（OpenAlex/arXiv/SE/HN）**降级为「注册表无对应项时」的兜底**。

### 2.3 改动 C：同步 node-design.md 摘要

`node-design.md` 里 sub2/sub3 的摘要块与 `dl_flow_nodes.py` 的 Step.purpose 是
**单源关系**（改 purpose 实质内容须手工同步摘要块，见 workflow-creation skill 的
「不要做的事」）。改动 A/B 落地后须同步该摘要。

## 3. 验证

1. **单测**：node-rules 渲染含「权威源注册表」「值不值得取证」判据；sub2 purpose
   里 ⑤ 在 ② 之前；light 定义不含「量级合理性」。
2. **真机 dogfood**（`state-reset` 回退重跑）：
   - curl 有效率从 ~24% 升到多少（定点抓应显著提升）；
   - tier 错标（light 应为 full）是否消失；
   - 原子B 这类「取证了对结论无影响」的题是否被 A2 判据直接标 none 跳过。

## 4. 不做的事

- 不改成非注册表的「纯 prompt 重排序」方案（用户已裁决 curated registry）。
- 不碰 ingest-agent 定位、fence、信任 scaffold（已修，独立项）。
- 不动 sub3 的「先派发后内查」编排顺序与 agent 并行机制（本设计只管取证源选择，
  不改编排）。
