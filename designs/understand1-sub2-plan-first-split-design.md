# Plan-first 拆步设计（understand:1 子2 → 子2a 规划 + 子2b 执行）

> 立项依据：`understand:1 子步骤 2`（causal-inference）实测 43 次工具调用，规划思考（MECE 拆解 + 定档）与执行搜索（5-Whys 挖因果链）**混在一个 step 里**，弱模型边搜边想、思考被连续打断，两者质量一起下降。本设计按「失效模式族定步数」拆成两步。
>
> 前置依赖：三杠杆设计（`designs/code-archaeology-three-levers-design.md`）§3 已给方向，本文是杠杆 3 的深入设计。

## 0. 关键不对称（为什么要拆）

当前子2 的一个 step 产出**两类异构产物**、喂**两个下游消费者**：

| 产物 | 消费契约 | 失效族 |
|---|---|---|
| `atomic_questions`（MECE 原子清单 + tier 分档） | 子3 外部取证按档执行 | **规划族**：MECE 不互斥/不穷尽、tier 误判、tier_reason 缺失 |
| 因果链（5-Whys + 竞争假设 + file:line 证据） | 子4 推理合成 | **执行族**：链环缺证据、非因果环、竞争假设缺失、近因/根因未分 |

两族由**不同判据**判、以**不同方式**失效——按 §3.8 #4「异族拆开（judge 分步可判）」，应拆成两步、各自门控。当前合并导致 judge 一次判两族（大而杂的混合判据）+ 弱模型边规划边执行（相互污染）。

**对齐「分类前置」模式**（§3.8 #3）：上游步定档 + 其 gate 判分类合理性，执行步只执行不重判。当前子2 把「定档」和「执行挖链」混在一起，正是「分类前置」想消灭的形态。

## 1. 拆分方案

### 子2a：规划（MECE 拆解 + 定档）

| 项 | 内容 |
|---|---|
| ref | causal-inference-root-cause（复用 skill） |
| 职责 | 单一/复合判定 → MECE 原子问题清单 → 每问题定取证深度档（none/light/full） |
| 产物 | `atomic_questions`（逐项 `{q, tier, tier_reason}`，与 MECE 一一对应） |
| 不做的 | **不挖因果链**——因果链是子2b 的活 |
| input | step1.real_problem |

### 子2b：执行（因果链挖掘）

| 项 | 内容 |
|---|---|
| ref | causal-inference-root-cause（复用 skill） |
| 职责 | 每个原子问题沿 5-Whys 挖因果链到根因 + 每环 file:line 证据 + ≥1 竞争假设 + 近因/根因置信度 |
| 产物 | 因果链 trace（q/a 数组） |
| input | step2a.atomic_questions（**按 2a 的档执行，不重定档**——分类前置） |

## 2. judge 判据拆分

| 步 | gate 判什么 |
|---|---|
| 子2a | MECE 互斥+穷尽、tier 枚举合法、tier_reason 非空、none 档理由含仓内路径、atomic_questions 与 MECE 一一对应 |
| 子2b | 因果链每环 file:line 证据、每环回答「值如何形成」非「谁调用谁」、竞争假设、近因/根因、置信度；**链环对应 2a 的原子问题** |

从当前子2 的单一 gate（一次判两族）拆成两个聚焦 gate（各判一族）——judge 输入更小、判据更纯，弱 judge 稳定性更好（framing 反转的既有结论：宽判面是坏）。

## 3. 返工回路（关键设计点）

子2b 执行可能发现子2a 规划不足（如 MECE 漏了原子问题、tier 定错）。三种处置：

| 方案 | 行为 | 取舍 |
|---|---|---|
| **A. 子2b 就地补**（推荐） | 执行中发现新原子/档错，在子2b 内补规划并留痕「执行期发现」 | 不打断、省往返；但「分类前置」被软化 |
| B. 回退 2a 重规划 | 子2b block → /dl state-reset 回 2a | 严格分类前置，但弱模型高概率频繁回退 = 昂贵 |
| C. 只执行不改 | 发现不足只标「待子3/子4 处理」 | 最严，但可能把可修的小漏带进下游 |

**推荐 A + 留痕**：子2b 允许补原子/纠档，但必须在 trace 里显式标「执行期补规划」并给出补的原因——把「分类前置」从硬约束软化为「默认分类前置 + 执行期可纠偏留痕」。理由：5-Whys 迭代本质决定了"每挖一层下一层才可见"，严格 B 会让弱模型在正常迭代里频繁误判为"需要回退"。

## 4. 步数 6→7 波及面（实现前必须逐项走查）

understand:1 从 6 步变 7 步（子2 → 子2a+子2b），波及：

1. **node-rules 渲染**：`render_substeps_section` 自动跟（Step 列表变长），但 `references/node-design.md` 摘要块须手工同步（§3.8 头部 warning）。
2. **segment chain 白名单**：`SEGMENT_CHAIN_NODES` 里 `understand:1` 的子2-子5 链 → 子2a/2b/3/4/5（子1 交互、子6 confirm 断链不变）。
3. **last_judged_trace key**：`understand:1#2` → `understand:1#2a`/`#2b`（或重编号为 #2/#3，其余步顺延——**编号策略需定**：加后缀 2a/2b vs 全重编号 2..7）。
4. **`_INTERACTIVE_CHUNKING_RULE` 等读回步挂载**：子5/子6 的步号引用是否受影响（若全重编号）。
5. **state-reset / jump / back 寻址**：`state-reset <n>` 的 n 语义随步数变化。
6. **append-trace 的 `sub_step` 字段**：evidence 里 sub_step 值变化，历史 evidence 兼容。
7. **节点注入文案**：任何硬编码「子步骤 2」的注入/phase-rules 文案需改。

**编号策略（2026-08-14 已核实，定全重编号）**：`sub_step_index` 全链路是 int——`sub_step_at(node, n: int)`、`_iter_trace_segments(sub_step_index: int)`、evidence 匹配 `sub_step == sub_step_index`、`range(1, sub_step_index+1)`、state 范围校验，全部按 int。加后缀 2a/2b 要 int→str 改语义，波及 range/比较/evidence 匹配/state 校验，风险大。**故定全重编号 2..7**（子2a=2、子2b=3、原子3→4、子4→5、子5→6、子6→7），int 语义不动，但子3-子6 的步号引用（读回步挂载、evidence 历史、segment chain、注入文案）需全量顺延核对。

## 5. 机制适配走查（§3.8 #6，实现前必做）

- **末步推进**：子2b 的 `_advance_sub_step` 行为（advance="sub" 节点内子步骤推进）。
- **完成信号**：STEP_DONE 通道对子2a/2b 均可达（无 PHASE_DONE）。
- **judge 输入面**：子2a 的 gate 判据（atomic_questions）judge 读得到吗（evidence 的 sub_step 值）。
- **注入状态机**：编排中/扣留/放行后三态文案，逐态走查（子2a/2b 各态模型看到什么）。
- **产物落盘**：子2a 的 atomic_questions 落 evidence（子2b 读它），无新产物文件 → 无归档存活问题。

## 6. 风险与不做的事

- **不做**：不把子2b 再拆（因果链内 5-Whys 迭代是同族，拆了纯烧 judge）。
- **不做**：不改子3/子4 的编排（本次只拆子2，子3 外部取证、子4 推理不动）。
- **风险**：sub_step_index 非整数标识（2a/2b）是 engine 机制改动，若不可行则退化为全重编号 2..7（波及面更大但机制简单）。

## 7. 落地顺序

1. 先定**编号策略**（2a/2b vs 全重编号）——这是机制改动的分水岭。
2. 机制适配走查（§5）。
3. 改 `dl_flow_nodes.py`（子2 → 子2a/子2b）+ gate 判据拆分 + node-design.md 同步。
4. 波及面逐项修（§4）。
5. 真实载荷重放（现有 amplitude_annualized 子2 的 block/pass 载荷，验证拆分后两 gate 判据不漂移）。
