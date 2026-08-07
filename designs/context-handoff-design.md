# 上下文交接架构设计（context handoff，2026-08-02）

> ⚠️ §2「成本自适应 nudge」策略已被 `minor-boundary-handoff-prompt-design.md`（2026-08-07）
> 取代——阈值触发纯建议在 tail_volume 实测中 8/8 边界触发、0 次执行（490k 零锯齿）；
> 新策略 = minor_state 边界固定提示 + 分档文案 + 选择留痕。§3 交接包、§4 裁决入 trace
> 等机制部分仍然有效。

> 动机数据：tail_volume_acceleration_annualized u:1 实测审计 + .wf_advance.log 全历史。
> 范围限定（用户 2026-08-02 决议）：只解**干净单轮跑完全程的 token 膨胀**；
> 测试/重建消耗是另一本账，不进本设计。

## 1. 问题：成本是轮次的平方，不是线性

主会话成本公式 = Σ(每轮) 当前上下文长度。当前架构会话不重置，上下文单调增长
（u:1 实测 54k → 283k，~3.1k tok/轮），于是**每新一步都要为前面所有步买单**——
平方增长。实测与全历史外推：

| 阶段 | 步数 | 当前架构（单调涨） |
|---|---|---|
| understand（4 子阶段，21 步） | 21 | ~110M cache read |
| plan（4 子阶段，22 步） | 22 | ~130M |
| execute/review/evolution | 3 节点 | 不可控，只会更贵 |
| **全程** | | **~250-400M** |

对照实锚：u:1 单节点（6 步/74 轮）实测 13.2M cache read；7/29 一个会话
285 轮烧 60.6M。**不处理，跑到 review 是 2-4 亿 token 量级。**

u:1 结束时 283k 上下文构成（transcript 实测，字符）：模型 thinking/text 203k /
Read 结果 176k / trace 载荷 Write 107k / Agent 派发 35k / 其余 ~40k。
跨步残留是浪费主体：子4 的 18 轮每轮背着子1-3 的全部文件全文与旧载荷，
真正需要的只是 evidence 里几条前序 trace + 当前步材料。

## 2. 方案：交接架构——把平方掰成线性

**交接单位 = 子步骤边界（配成本阈值自适应），会话内工作连续，跨步换新上下文。**
粒度论证：轮次级不可能（步内 agent 循环必须看到前轮工具结果）；子阶段级
太粗（u:1 单节点内就涨 229k，只能省 2.5-3x）；子步骤级才到 6-8x。

**交接机制 v1 = /clear + SessionStart 自动注入交接包**（零新基础设施）：

- `/clear` 清对话但**系统提示随进程保留**（phase-rules 79k 字符门票只付一次，
  启动后全程有效）——clear 后新上下文 ≈ 30k 系统面 + ~15k 交接包 ≈ 45k。
- SessionStart hook（`source: clear/startup`）检测「运行中工作流 + 新会话」
  → 注入机械装配的交接包（见 §3）。现有 workflow_phase 注入通道不变。
- **成本自适应 nudge**（不一刀切每步都 clear）：Stop hook 在子步 gate pass
  时读当前 transcript 尾部 usage 估算上下文，> 阈值（初值 150k）才在续轮
  指令里附「建议 /clear 后回『继续』，交接包自动注入」。轻步（3 轮读回步）
  不清；重步（子2/3/4）前清。用户忽略 nudge 无任何后果（纯建议，非围栏）。

**为什么不选其他机制**：
- 每步 `claude -p` 驱动循环：AskUserQuestion 无用户可答，读回确认步全灭；
  且 v1 不值得为此重写 launcher。
- 子代理执行子步骤：子代理不能交互提问、Stop 门控不进子代理进程。
- /compact：压缩决策在信息不全时做，lossy 且保留量不可控——本设计是
  「主动有损替代被动 compact」（v2.41 产物交接硬化同哲学）的会话级推广。

## 3. 交接包（handoff pack）= 机械装配，禁模型自选

`engine.handoff_pack(project_root, name)` 单源生成（扩展 read_evidence_for_step
的跨步裁剪为跨节点）：

1. **当前位置**：phase/sub/sub_step 指针 + 当前步 purpose（workflow_phase
   注入已有，不重复）。
2. **前序证据**：当前节点已完成各步的最新 trace + 前序节点的**归一化陈述**
   （子5 statements）与**用户裁决原话**——不是全量 evidence（judge 输入
   裁剪同款逻辑，v2.12 已验证 -97%/-65%）。
3. **产物清单**：已装配产物路径 + 节标题清单（understand.md/design.md/plan.md）
   ——给指针不给全文，模型按需 Read（产物全文内联 = 把省下的又花回去）。
4. **用户裁决原话**：见 §4——这是交接包的正确性命门。

## 4. 正确性前置：用户裁决必入 trace（机械校验）

当前用户裁决（子6 拍板「S1+S2」、读回确认答案）只在对话里——/clear 即丢，
新会话模型只能重问（烦）或编造（危）。这是本架构**唯一可能引入幻觉的缺口**，
必须先焊死：

- 读回确认类步（u:1 子6、u:2/3/4 子5、plan 各末步）挂新 mech_check
  `user_decision_recorded`：trace 须含 AskUserQuestion 的用户答复原话
  （操作化：qa 项标题含「用户裁决/读回」，a 含答复原话引用——标题承诺装置
  同「蒸馏报告」「红队原文收录」先例）。
- 分隔度检验先行（§3.5 #15 纪律）：用真实读回步 trace 重放验证信号
  再上线；无真实被 block 载荷时构造双向最小载荷。
- 兜底通道已有：evidence_show 回查（v2.41）+ 用户随时可纠正。

## 5. 成本测算（含机制开销，门票不重复计）

假设：步均 12 轮（u:1 实测）、轮均新增 3.1k、clear 后起步 45k、交接包 15k。

| 方案 | understand | plan | execute+review | 全程 | nudge 次数 |
|---|---|---|---|---|---|
| 现状（不交接） | ~110M | ~130M | 不可控 | 250-400M | 0 |
| 每节点交接 | ~47M | ~50M | ~8M | ~105M | ~10 |
| **每步交接+阈值自适应（v1）** | **~20M** | **~22M** | **~5M** | **~50M** | ~12-15 |

v1 = 每步交接的理论值打七五折（轻步不清）：**全程 ~5 倍缩减，用户动作 =
每个重步前 2 次击键**。execute 主会话薄是设计内（worker 全子代理，
executor 不分析），不受交接影响。

## 6. 不改什么 / 显式排除

- **判据/purpose/gate 语义零改动**——交接只改上下文装配，门控读磁盘状态
  （state.json + evidence）天然会话无关，这是本架构成立的地基。
- execute 阶段的 worker 子代理策略不动（已是交接架构）。
- L3（内查 Read 卸子代理、收录改引用钉死路径）是独立后续项，不进 v1。
- judge 链路不动（v2.44 后已非瓶颈）。

## 7. 改动面（预估 4 文件 + 测试）

1. `dl_flow_engine.py`：`handoff_pack()` 生成器 + transcript usage 估算函数
   （读 session transcript 尾部 cache_read，宁纵勿枉：读不到→不 nudge）。
2. `hooks/workflow_advance.py`：子步 pass 续轮消息按阈值附 /clear nudge。
3. per-wf settings 模板：注册 SessionStart hook（**SETTINGS_TEMPLATE_VERSION
   须 bump**，v2.35 防静默税纪律；在飞实例 /dl status 双通道警告已内建）。
4. `hooks/workflow_session.py`（新）：SessionStart source=clear/startup 且
   工作流运行中 → 输出交接包注入。
5. `dl_flow_nodes.py`：读回确认步挂 `user_decision_recorded`（§4，先过分隔度）。
6. 测试：handoff_pack 装配正确性（真实 evidence 冒烟，§3.6 #5）+
   nudge 阈值逻辑 + SessionStart 注入触发/不触发两向 + 裁决校验双向载荷。

## 8. 风险与回退

| 风险 | 缓解 |
|---|---|
| 交接包漏隐性上下文（用户语气/随口约束） | §4 机械校验 + 兜底回查通道；nudge 纯建议，用户感知「模型忘了什么」时可不清 |
| SessionStart 注入与 superpowers 用户级 hook 并存 | hook 数组合并，注入附加不覆盖；冒烟验证双注入都在 |
| 阈值误判（该清不清/不该清清了） | 宁纵勿枉：读不到 usage 不 nudge；清了只是多付 45k 门票，无正确性风险 |
| 在飞实例 | engine/hook git pull 即生效；settings 模板变更由版本戳警告指 --resume，不强制 |

**验证**：下个真实工作流全程跑通，按 §3.6 审计口径对比 token 曲线
（预期：上下文锯齿线在 45k-150k 间震荡，不再单调爬升到 800k）。
