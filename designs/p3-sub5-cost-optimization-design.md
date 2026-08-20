# plan:3 子5（归一化能力包）成本优化设计

> 基线实例：p3_sub5_ab（自跑 A 臂，种子=p3_sub3_base evidence[CTS 子1-4 全]
> +state 四字段同步+chain.last_step=4）；B 轮实例同实例重置（同种子同码基）。
> A/B provider = ac-deepseek1（deepseek-v4-flash）headless。
> 附赠数据点：种子装配事故跑（chain.last_step=3 失配 → fresh 段，同 main 码）
> = 行为面分解对照，telemetry 存 /tmp/p3sub5_fresh_probe（只作分解不作基线，
> 口径=链续段）。
> 数值口径：种子 problem_statement 保持 4824.5% 不改（runtime-audit #25）；
> amplitude 今日值 4929.2%（用户明示）与种子数值漂移属 #18，两轮同种子同
> 漂移面（p2-sub4/p3-sub3 设计同口径）。
> 通用性约束（用户决议 2026-08-20）：条款全部机制/形态级，**避免 factor 化**——
> 禁把测试实例的因子名/文件面/数值写进引擎条款（p2-sub4 §0 同）。

## 0. 范围与前置

本设计只覆盖 **plan:3 子5（归一化能力包，非交互归一化/搬运型步）**。
子6 读回步=确认级零成本（#22 关闭清单，立项永久关闭）——子5 是 plan:3
最后一个有模型会话的成本面。归一化步成本优化先例：plan:1#5（p1-sub5-cost）/
plan:2#4（p2-sub4-cost），本设计=同族第三例。
本分支从 main（630b604，p3-sub3-cost 收官）切出。并行会话 p3-sub4-cost
（feat/p3-sub4-cost，在飞未 merge）与本支零文件面冲突预登记，并轨项见 §6。

## 1. 基线预判（机制算术 + fresh 探针分解）

### 链税实锤（#20/#24 判据先验）

- 链会话（sid=68288809，含子2+子3+子4 transcript）末调 usage
  cache_read=**210,816**——链上下文 ~211k。
- deepseek 流式=会话隔离缓存（P0 实证）：跨进程 --resume 首调必冷
  （链边界 8/8 冷，#9/#20）。子4 免跑基线（p3-sub4-cost 设计）同链段
  首调 190,802/cr=1,024 实锤同形态。
- A 臂子5 = 链续段：首调 ≈ 211k 冷重写 + ~50k 段前缀 ≈ **~255-265k**，
  每调重读携带税 211k+ 单调涨（#24）×步体轮数。
- 链上下文 ~211k 距 250k 护栏（CHAIN_CONTEXT_WARN）余量仅 ~39k——
  子5 步体产出即顶线，链形态在结构上不可持续（#9 预授权回滚同族信号）。

### fresh 探针分解（种子事故跑，main 码 fresh 段，行为面）

| 指标 | fresh 探针（614649d1 段，被收段前已落 trace） |
|---|---|
| 首调 fresh | 50,119（cr=0） |
| 段 fresh 合计 | 157,912 |
| 段 cr 合计 | 809,984 |
| 段 dur_api | 203.8s |
| 工具调用 | 5（Skill define-problem→scaffold→Read 骨架→Edit→append 一次过） |

**关键发现：行为面已近理想最小形态**（#40 收官态同族）——零探索/零
evidence 翻找/零注册表重勘察/零交付后徘徊，de facto 复用已成立（归一化
步天然形态+前序批次平移条款的节点语境）。**本步剩余成本在链税层+前缀层，
不在行为层**（#12 瓶颈分层）。

## 2. 杠杆选型

| 杠杆 | 置位？ | 依据 |
|---|---|---|
| **L1 步级断链**（(plan:3,5) 入 SEGMENT_CHAIN_SKIP_STEPS，步级第五例——p3-sub4 在飞占第四例，merge 复核） | **置位** | #20 判别问句「这个 provider 的链首调 cr 是 0 吗」=是（跨进程 resume 恒冷，211k 全量冷重写=纯税）；#24 携带税主导（211k×轮数，步体 5-8 调）；材料经交接包逐字段核对完备（子1 需求清单/子2 注册表+强制路由核对/子3 绑定提案+不加载清单/子4 可用性核验+假设=输入契约全集，种子冒烟「"sub_step": 1-4」全 True）；后续步=子6 确认级无会话，零暴露面（#30 断链暴露面核对=恒 fresh 零影响） |
| **L2 Step strip**（segment_strip_project_context，第十七例——p3-sub4 在飞占第十六例，merge 复核） | **置位** | #23 第三核对「env 剥离边界」：交付物=归一化 statements 五字段，正文材料全部经本节点前序 trace 逐字在包——enforce_align 内容（长 pipeline 后台禁 pipe/H15 codegraph 前置/执行映射）已在子2 强制路由核对留痕+子3 绑定提案逐字携带（种子 evidence 实查词形命中：子2「长 pipeline/H15/执行映射」、子3「禁 pipe/置信度」），能力名=子2 注册表出处（包内），不引自动加载文档本体（u:3#1 反优化理由不成立）；gate 判材=evidence trace 不受影响 |
| **L3 pack_self_contained**（非交互步第八例） | **置位** | #19 输入契约逐字段核对：skill_first=子3 绑定提案+子2 注册表出处（包内）；tools=子3 绑定+子4 可用性状态（包内）；enforce_align=子2 强制路由核对留痕（包内）；subagent_policy=子3 扇出绑定/红队未触发声明（包内）；no_load=子3 最小集不加载清单（包内，mech no_load_trace 已下沉）；假设传导=子4 假设项（包内，mech assumption_propagation_trace 已下沉）。搬运型步判别=gate 方框一把「与子3/子4 已定内容不一致（丢失/篡改/新增）」判死=产出为前序材料归一化重组非新事实（结构性佐证）。防的是方差不是现状（p2-sub4 同款定位）——包尾通用邀请诱发元探查的教训形态（u:2#2 第二轮 15 次） |
| **L4 复用钉死（无取证例外形态，#34 第四例）+ 交付即止/格式真源** | **置位** | #34 适用条件=gate 结构性封死包外材料合法出口：方框一（字段与子3/子4 已定内容不一致判 block）+方框三（能力名与子2 注册表逐字性）+方框四/五（mech 承托）——条款与判据同向写死：材料=交接包本节点留痕全文通道逐项逐字引用，零新取证/零 evidence 翻找/零注册表重勘察/零数据文件核验；职责边界（可用性核验归子4 已留痕、绑定映射拍板归子6、为 plan:4 预取=越界 #27）；交付即止（#37 平移——探针段虽未暴露徘徊，条款压制两通道打架根因）；格式真源（#26 平移） |
| gate 修文本 | 不动 | **零变更三查**（#29）：①mech（no_load_trace/assumption_propagation_trace）——复用条款不改变列举/传导义务，词面无冲突；②judge 方框一合法形态已认「对子3/子4 内容的忠实提取/适度压缩/同义转述即合规」=复用形态合法化判词已在场（#34 同向）；③复用引用形态（「复用 子N 留痕：…逐字」）不命中任一 block 条件。三查全过→不动 gate 文本、免 replay |
| Node 工具白名单 | 不动（已在 main） | p3-sub1/p3-sub2-cost 置位五件（Bash/Read/Edit/Skill/Agent），A/B 同基 |
| MERGED 段内续步 | 否决 | #24：步体 5-8 调非极小+前序上下文巨大，携带税主导断链确定优；子6 确认级无会话无续步对象；u:3 暖率 1/4 前科 |
| 节点级断链（plan:3 出册） | 否决 | surgical：步级已覆盖；子4 政策属并行会话 p3-sub4-cost 范围，出册超单步范围（p3-sub2/sub3 §3 同判） |
| pack_full_prior_boundary | 不置位 | 复用材料=本节点留痕全文通道（子1-4 trace），不经前序节点 boundary 截断面（p2-sub3/p2-sub4 同判） |

## 3. 改法（dl_flow_nodes.py 子5 Step + dl_flow_engine.py skip 集 + 测试 + 同步件）

### L1 机制

`SEGMENT_CHAIN_SKIP_STEPS` 加 `("plan:3", 5)`（步级第五例）。注释按先例
格式补判据摘要（#20 恒冷/#24 携带税/材料核对/子6 零暴露面）。

### L2 机制

子5 Step 加 `segment_strip_project_context=True`（第十七例，merge 复核编号）。

### L3 机制

子5 Step 加 `pack_self_contained=True`（非交互步第八例）。置位前置=装配
不变量测试：包须含本节点子1/子2/子3/子4 trace 全文（防未来 P1-1 类包
修剪把材料修没了条款变错）。

### L4 条款（purpose 追加，与同节点子1-3 条款块位置对齐，保持
「职责→复用→收尾」阅读序）

材料边界（复用钉死，无取证例外形态）：
- 归一化材料=交接包本节点留痕全文通道（子1 需求清单/子2 注册表+强制
  路由核对/子3 绑定提案+最小集不加载清单/子4 可用性核验+假设清单）——
  逐项逐字引用即合法形态（「复用 子N 留痕：<出处逐字>」），默认零新取证。
- 无取证例外：字段与子3/子4 已定内容不一致即 gate 方框一判 block，
  新取证在本步无判据出口；能力名与子2 注册表逐字性归方框三——零
  evidence 翻找（前序 trace 已在包内）、零注册表重勘察（子2 已留痕）、
  零数据文件核验（本步不碰数据面）。
- 职责边界：可用性核验归子4（已留痕），本步零复核；绑定映射拍板归
  子6（本步只提案）；为后续节点（plan:4 执行计划）预取=越界。

交付即止：落库成功（✓ 已落库）即结束本轮——禁 locate 产物/读 state/
grep evidence 确认落库/预习下一步，推进与门控由外部 driver 判定。
载荷格式的唯一真源 = --scaffold 骨架+append-trace 报错文案——禁读引擎/
测试源码/历史 trace 反推格式；被拒按报错文案逐字修即可。

selfcheck 补一条：「材料全部引自交接包本节点前序留痕吗（零新取证/
零 evidence 翻找/零注册表重勘察）？落库后交付即止了吗？」

### 同步件

- tests/test_dl_flow_engine.py：("plan:3",5) ∈ skip 集 pin + 子5 flags
  （strip/pack）pin（既有 flags 断言同步更新）+ 条款 pin（复用钉死/交付
  即止/格式真源关键词）+ pack 装配不变量（子1-4 trace 全文在包）。
- skills/workflow-creation/references/nodes-index.md plan:3 行子5 摘要。
- skills/workflow-creation/references/cost-optimization.md：收口沉淀
  （编号取收口时 git log 最大值+1，防并行抢占）。

## 4. 预登记（B vs A，验收口径）

| 指标 | A 预测（机制算术） | B 预登记 | 机制归因 |
|---|---|---|---|
| 首调 fresh | ~255-265k（211k 冷重写+~50k 前缀，cr=0） | **≤40,000（-84% 起）** | L1 去冷重写（fresh 地板 50.1k 探针实测）+ L2 strip -11.9k（探针口径）+ 条款回补 ~+0.5k |
| 轮数 | 5-8（fresh 探针 5 调用/1 result） | ≤8 | 行为面已地板（#40），条款=方差防守 |
| 工具调用 | ~5 | ≤6 | 理想最小形态五件 |
| 段 cr | ~1.3-2M（211k+×5-8 调单调涨） | **-80% 起** | L1 每调重读 211k+→30-45k |
| 段 out | ~15-30k | ±15% 内 | #30 两成分口径：gate 方框一原已要求忠实提取子3/子4=引用义务零新增（p3-sub1 反例形态），out 不放大预期 |
| 成本等效（cr×0.1 折 fresh） | ~400k+ | **-70% 起** | 主验收轴 |
| dur_api | ~200-300s | -30% 起 | out÷rate 拟合归因，双轴分开登记（#30） |
| mech 拒 / block | 0 / 0 | 0 / 0 | 硬约束 |

trace 质量逐条自查（防 Goodhart）：statements 五键逐键非空、与子3/子4
内容一致（无丢失无篡改无新增）、能力名与子2 注册表逐字一致、不加载清单
全承载、假设原样传导（置信度×影响保留——p2-sub4 弱化登记教训，B 轮载荷
专项核「置信度」词形）、需求双向覆盖无漏——复用钉死不得稀释保真转换。

**诚实声明（立项预期管理）**：本步行为面已被归一化步天然形态推到近理想
最小形态（fresh 探针实证），本轮杠杆在链税层（L1，绝对大头）+前缀层
（L2）+方差防守（L3/L4）——token 降幅预期 -70% 起高于 p2-sub4 的
-25~-45%（链税体量 211k 远超 p2-sub4 的零链税基线），墙钟降幅受
out÷rate 生成主导地板约束（#30）。

## 5. 混淆声明

- amplitude 今日值 4929.2%（用户明示）vs 种子 problem_statement 4824.5%
  原文 = #18 漂移面（种子逐字一致纪律，runtime-audit #25）；plan:3#5 与
  因子数值零判面接触（归一化不碰数据文件），登记不处置。
- A 链续段 / B fresh 段口径差 = L1 处置本身（p3-sub2 §1 三查③同型声明），
  非混淆。
- A/B 双臂同白名单基（plan:3 Node 白名单在 630b604 已在册）——白名单
  收益不计入本设计杠杆。
- fresh 探针段（种子事故跑）：同 main 码同种子，只用于行为面分解与
  fresh 地板读数（首调 50,119），不作 A 基线（口径=链续段生产形态）；
  其 telemetry 与子5 trace 已清除出种子（evidence 截回 ≤CTS4、段记录
  摘除、transcript 删除），B 轮零污染。
- 并行会话在飞：p3-sub4-cost（未 merge，其 driver pid 1164321 跑
  p3_sub4_ab）——实例各自独立零干扰；merge 并轨收口：SEGMENT_CHAIN_
  SKIP_STEPS 同 frozenset 相邻行、nodes-index plan:3 行、strip/pack/断链
  例数编号（其占断链第四例+strip 第十六例，本支顺移第五/第十七）、
  cost-optimization 沉淀编号（取收口时 git log 最大值+1）、测试计数。
- 种子八件套：evidence=p3_sub3_base.jsonl 副本（CTS 子1-4 全，零裁剪）/
  LJT 补 plan:3#4（子4 trace 落库未判=并行会话收段姿态，种子语义=已判，
  sha 经引擎 latest_trace_sha1 计算）/segment_sessions 保留子2-4/chain
  last_step 3→4（**种子装配新坑：子4 gate 未过则链 last_step 不更新，
  断链判据 last_step==cur-1 失配=fresh 化静默偏差——本设计事故跑实证**）/
  settings 名替换（statusline --name）/handoff_pack 起跑前冒烟（产物清单
  节非空+子1-4 trace 全文在包，已验）/state 四字段同步（sub_step_index=5=
  将跑之步）/产物文件三件套（plans/understands/designs 拷贝改名）。
- B 轮过子5 后 driver 会续跑子6（确认级零成本）并进 plan:4#1 后人工停——
  只子5 段进 A/B 口径（段切分以 result 事件+session_id 双锚）。

## 6. 测试与回滚面

- 新增测试：①("plan:3",5) ∈ SEGMENT_CHAIN_SKIP_STEPS pin；②子5
  segment_strip_project_context + pack_self_contained flags pin（既有
  strips 断言并轨[T,F,T]→加子5）；③子5 purpose/selfcheck 条款 pin
  （复用钉死无取证例外/交付即止/格式真源关键词，镜像 p3-sub2/sub3 形态）；
  ④pack 装配不变量（子5 置位步包内本节点子1-4 trace 全文在场）。
- 回滚面：skip 集摘条目 / Step 两 flag 置 False / purpose 段落整删，单点
  翻转，兄弟步零暴露。
- ruff check + format；pytest 全绿（基线 1204+新增）。

## 7. A/B 跑法（runtime-audit #25 + #24 三纪律）

①实例=p3_sub5_ab 单实例双臂：A 臂跑完收段后重置（evidence 截回 ≤CTS4、
段记录摘子5、chain.last_step=4 保持、transcript 清子5 段）→ B 臂同种子。
②跑法（串行，A 先）：`AC_WORKFLOW_LAUNCHER=<对应树>/scripts/workflow/
dl-launch.sh ac-deepseek1 --dl p3_sub5_ab --resume --headless` 后台
（A=主树 launcher，B=本 worktree launcher 直调——#24 纪律①）；
**禁管道**（A 臂初跑 `| tail` 缓冲教训，driver 输出落后台任务输出文件
裸读）；子5 gate 过（state 将跑翻 6）即停 driver 收段统计。
③核验：driver 日志特征行——A 臂链续（init 事件 session_id=68288809=
链 sid）/ B 臂 fresh（新 sid）；init 事件 tools 白名单五件（Task=Agent
映射 #23①）；B 臂 env 双 DISABLE 生效（strip）+段 prompt 含「无取证
例外」条款+「材料已在包内」包尾切换=worktree 引擎渲染实证（headless 段
交接包由 driver 装配，#28 坑只适用 TUI 段）。
④读数：drive-stream 按 result 事件切段，首调 fresh=段内第一个 assistant
usage，逐段合计=Σassistant usage；[log_*] 污染行按行首 { 过滤。
