# 取证深度分档设计（v2.40 提案，2026-08-02）

> 关联：`step3-fetch-subagent-design.md`（子3 子代理化，v2.38/2.39 优化执行面）；本文优化**取证深度面**——不再对所有原子问题无差别跑五层源。
> 对齐结论（2026-08-02 用户四决策）：①分类挂子2 输出带 tier 字段；②light 档参数 = ≤4 curl / ≤2 层源 / 单向锚点；③拿不准默认 light；④禁降档。

## 1. 动机

子3 是主会话工具密度大户（tail_volume 实测 46 msgs / 26 tool calls / 6.2M cache read；v2.39 另实测单 agent 空响应重试可烧 1.19M input）。v2.38/2.39 把外部层卸子代理、加了轮次上限，但**取证深度仍一刀切**：每个原子问题都派 agent 跑五层源双向取证。用户三类直觉：

| 问题类型 | 一刀切跑五层源 |
|---|---|
| 代码 bug / 仓内行为（"IC 计算有没有用未来数据"） | 纯烧——答案在仓库内 |
| 数值/事实合理性（"年化 9000% 合理吗"） | 过度——查到权威量级锚点即可判 |
| 方法论/系统设计（"量化系统该怎么设计"） | 合适——需要多源交叉双向 |

雏形已存在：子2「挖不动的深层降格进竞争假设分支标『待子3取证』」= 隐式二分类（要/不要外部取证）。本设计将其**显式化 + 细分三档**，粒度 = 每个原子问题（混合实例不被逼进最深档）。

## 2. 三档定义（单源常量 `_FETCH_TIER_RULE`，对齐 `_SOLUTION_FREE_SUBJECT_RULE` 先例）

| 档 | 判定信号 | 子3 行为 |
|---|---|---|
| `none`（仅内查） | 答案完全在仓库内可达：函数行为/数据契约/配置/日志 | 不派 fetch agent；③内部仓库层（codegraph+Read）照常覆盖该原子 |
| `light`（点查锚点） | 单一事实/数值 claim，公开有权威锚点，1-2 条独立来源即可定 | 1 个 agent，≤2 层源（主会话在 claim 补充区指定哪 2 层），≤4 curl，**单向锚点**（不双向）；返回契约改「锚点值+来源+量级对比」≤60 行 |
| `full`（充分双向） | 方法论/设计/开放问题，无单一权威答案，需多源交叉 | 现状不变：五层源、≤12 curl、双向、报告 ≤120 行 |

**默认档 = light**（拿不准时）：漂到 light 的 full 类问题有升档机制救回；none 漏取证是质量问题（难发现），full 是成本问题（易发现），light 居间兜底。

## 3. 分类位置 = 子2（纠偏前置到便宜环节）

- **载荷新增结构化必填键**（走 v2.37 `extra_payload_keys` 机制扩展，从「顶层键+前缀」泛化到「顶层键+逐项 JSON 校验」）：`atomic_questions` = `[{"q":..., "tier":"none|light|full", "tier_reason":...}]`——MECE 原子问题清单从 qa 自由文本单源化为结构化键，fetch_prompt / gate / judge 全从这里读 tier，消灭「清单在两处各写一遍」的漂移面。
- **append-trace 机械校验**：tier 枚举合法 + tier_reason 非空 + none 档的 tier_reason 须含内部取证路径描述（禁「我觉得仓里有」式空理由）。
- **子2 judge rubric 新增判据**：tier 与问题性质匹配（重点抽查 none 档——漏取证风险最高：问题含外部知识依赖[行业常识/第三方库行为/方法论]却标 none → block）。
- 子2 purpose 补一句指引：默认档规则 + 三档信号（引用 `_FETCH_TIER_RULE` 单源）。

## 4. 子3 执行面

- `fetch_prompt()` 读子2 `atomic_questions` 键按 tier 分发：none 档原子不进骨架；light 档原子注入 light 参数块（层数/轮次/单向契约）；full 档现状。
- **升档**：light agent 报告可标「建议升档 full + 理由」（不收敛/有争议时）；主会话对该原子补派 full agent，trace 留升档记录（原 light 报告仍收录，升档理由原文收录）。**禁降档**：标 full 必须跑 full——分类纠偏全部前置子2 gate，防子3 自作主张偷工（弱模型下稳）。
- **mech_checks=fetch_report_recorded 改 tier-aware**：none 档豁免报告项；light/full 档仍每原子必收报告（light 报告 = 锚点项）。
- **subagent_retry 台账扩展**：每 agent 记 tier + curl 轮次；light 档超 4 次 curl 记入 gate 裁决违例项（机械可数，台账已具备计数基础）。

## 5. judge 判据变化汇总

| gate | 新增判据 |
|---|---|
| 子2 | tier 与问题性质匹配；none 档内部可达性理由成立 |
| 子3 | 执行档 = 标称档（禁降档）；升档留痕（建议升档未处理=判 block）；light 参数未超（层数/轮次/单向） |

**改判据必跑真实载荷重放**（v2.36 初版两缺陷被重放逮住、v2.38 报告收录被裁量放过的教训）：用 tail_volume u:1 旧 trace 重放新子2/子3 gate，旧形态（无 atomic_questions 键）应机械拒，新形态样例应 PASS。

## 6. 同步面（改编排 checklist）

`dl_flow_nodes.py`（子2/子3 purpose + extra_payload_keys 扩展 + mech_checks）→ engine（append-trace 校验 + fetch_prompt 分档 + 台账 + judge prompt）→ phase-rules（GENERATED 自动，无需手改）→ `references/node-design.md` 摘要块**手工同步** → fetch-prompt 骨架（light 参数块）→ 测试（TestFetchPrompt / TestAppendTrace / 新 TestFetchTier*）。

## 7. 边界与已知限制

- 只影响 understand:1——全系统唯一有 fetch-prompt 的节点；understand:2-4 / plan 无外部取证步，不涉及。
- none 档滥用 = 最大质量风险面（模型偷懒全标 none）。防线：理由必填+含路径（机械）+ judge 重点抽查（语义）。接受残余风险——子6 读回时「证据不足」项显式暴露给用户是最终兜底。
- light 档单向锚点不覆盖证伪方向：数值合理性判断「找到权威量级对比」即够；锚点冲突时升档机制接住。
- 在跑工作流 phase-rules 是 launch 快照，新机制对下一个 dl 实例生效（惯例，同 v2.38）。

## 8. 验证

- pytest 全绿 + 新增 TestFetchTier*（枚举校验/none 档路径理由/tier-aware 报告核验/light 台账计数）。
- judge 重放回归：tail_volume 旧 trace（无键 → 机械拒）+ 构造新形态（三档混合 → PASS；none 档无内部依赖理由 → block）。
- 下一个真实实例观察子3 成本对比（token / 轮次 / agent 数）。
