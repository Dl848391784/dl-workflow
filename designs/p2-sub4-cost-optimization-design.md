# plan:2 子4（归一化执行步骤）成本优化设计

> 基线实例：p2_sub3_ab 子4 段（2026-08-20，p2-sub3-cost B 轮顺带跑过，
> 免跑基线 #30——p2-sub3-cost 设计 §6 遗留已登记本候选）；B 轮实例：p2_sub4_ab
> （种子=p2_sub3_ab evidence 截 ≤plan:2#3，worktree 码）。
> 数值口径：种子 problem_statement 保持 4824.5% 不改（runtime-audit #25）；
> amplitude 今日值 4929.2% 与种子数值漂移属 #18，两轮同种子同漂移面
> （p2-sub1/p2-sub3 设计同口径）。
> 通用性约束（用户决议 2026-08-20）：条款全部机制/形态级，**避免 factor 化**——
> 禁把测试实例的因子名/文件面/数值写进引擎条款。

## 0. 范围与前置

本设计只覆盖 **plan:2 子4（归一化执行步骤，非交互归一化/搬运型步）**。
子4 是断链后 fresh 段（p2-sub2-cost 节点级断链第六例已落地），无链税面；
交付即止/格式真源两句已由 p2-sub2-cost L5 断链暴露面同批补款（#30）。
子5 读回步=确认级零成本（#22 关闭清单，立项永久关闭）。
本分支从 main（80de063，p2-sub3-cost 收官）切出——**main 已含 p2-sub1-cost
Node 工具白名单（Bash/Read/Edit/Skill，无 Write）**，A 轮基线（p2_sub3_ab 跑在
cbdf8ff=无白名单分支）与 B 轮（有白名单）不同基，首调预登记按三分量报价
（#23 教训），白名单分量是 merge 叠加收益非本设计杠杆。

## 1. 基线（A = p2_sub3_ab 子4 fresh 段，免跑基线）

免跑基线三查（#30）：①子4 代码两轮间零变更——A 轮跑 cbdf8ff，cbdf8ff→80de063
diff 中子4 Step 唯一触及=Node 白名单注释行（p2-sub1-cost 合入），职责/purpose/
gate 零变更；②种子证据=p2_sub3_ab evidence 截 ≤plan:2#3（子1×1/子2×2[off-by-one
重跑对]/子3×1 全部保留=A 轮子4 段实际消费的同一份前序留痕，三查②最强形态）；
③段口径=fresh 段（断链后形态），两轮一致。

| 指标 | A（p2_sub3_ab 子4 段，sid=3a4a55df，cbdf8ff） |
|---|---|
| 首调 fresh | **65,860**（cr=0，fresh 段） |
| 段 fresh 合计（inputTokens） | 113,952 |
| 段 cr 合计 | 631,040 |
| 段 out 合计 | 28,909 |
| 轮数（result 权威值） | **10** |
| 段 dur_api | 184.2s |
| 工具调用 | 8（Skill×2/Bash×2/Read×1/Write×1/Edit×2） |
| append-trace mech 拒 | 0 |
| 门控 | 零 block（单段子4 trace×1 直通，推进至 plan:3 实证） |
| 成本等效（cr×0.1 折 fresh） | 177,056 |

### 基线浪费分解（8 调用逐条归因）

| # | 调用 | 定性 |
|---|---|---|
| 1 | Skill define-problem | 保留（ref 点名） |
| 2 | Skill writing-plans（未注册秒回） | 保留（ref 点名，headless 环境性缺席） |
| 3 | Bash append-trace --scaffold | 保留（骨架通道） |
| 4 | Read 骨架 | 保留 |
| 5 | **Write 载荷文件 → S14 围栏 deny** | **褶皱**——scaffold 已生成仍试 Write；当前 main 的 Node 白名单（无 Write）已结构性消灭本褶皱（A 轮分支无白名单才暴露） |
| 6-7 | Edit×2 填骨架 | 保留 |
| 8 | Bash append-trace 落库一次过 | 保留 |

**关键发现：基线行为面已近理想最小形态**——零探索/零 evidence 翻找/零
设计文档重读/零 codegraph 重查/零交付后徘徊，de facto 复用已成立（模型自述
「基于交接包子2（U1-U5+要素 ID+DAG）与子3（锚点核验+假设 H-1/H-2/H-3）内容」
归一化，gate 一次通过）。唯一行为褶皱（Write deny）已被 main 白名单结构性
消灭。**本步剩余成本在前缀层不在行为层**（#12 瓶颈分层：首调 65.9k 占段
fresh 58%，strip/白名单是可裁分量）。

## 2. 杠杆选型

| 杠杆 | 置位？ | 依据 |
|---|---|---|
| **L1 Step strip**（segment_strip_project_context，第十三例） | **置位** | #23 第三核对「env 剥离边界」：交付物=归一化 statements（五字段+假设传导），正文不引 CLAUDE.md/auto-memory 内容——原子性判据（_ATOMIC_ITEM_RULE）逐字在 purpose、TDD 微循环/H9 是概念引用非条号点名（u:3#1 反优化理由不成立）；gate 判材=evidence trace 不受 env 剥离影响。归一化步 strip 先例充分（u4-sub4 第六例/p1-sub5/u3-sub4 第二例）。探针口径 -11.9k/调 |
| **L2 pack_self_contained**（非交互步第六例） | **置位** | #19 四步核对：输入契约逐字段核对——change_point/interface/verify/trace_anchor=子2 单元定义+子3 锚点核验留痕（本节点留痕全文通道在包，A 轮零外部读取完成交付=材料充分性实测定案）；acceptance_map=子1 验收包 SC ID（子1 trace 全文在包）；假设传导=子3 假设项（同在包）。搬运型步判别=产出为前序材料的归一化重组非新事实（gate 判据二把「子2/子3 未定内容进项」判死=结构性佐证）。防的是方差不是现状——u:2#2 第二轮包尾通用邀请诱发 15 次元探查的教训形态 |
| **L3 复用钉死（无取证例外形态，#34 第二例）** | **置位** | #34 适用条件=gate 结构性封死包外材料合法出口：判据二（b）「混入子2/子3 未定的内容判 block」+判材边界「子3 已留痕即合规」「design.md 结构性读不到……不得以无法核对为由 block」——条款与判据同向写死：零新取证/零重验/零 evidence 翻找/零设计文档重读。基线 de facto 干净，条款=方差防守（p1-sub2 同款定位：「基线零探索 de facto 复用已成立，条款防先查清楚再动手方差」） |
| gate 修文本 | 不动 | **零变更三查**（#29）：①sc_coverage_trace 扫描 SC ID 差集，复用条款不引入新留痕形态，词表面零影响；②判材边界已钉「子3 已留痕即合规」「不得以无法核对 design.md 为由 block」=复用形态的合法化判词已在场；③复用引用不命中任何现存 block 条件（本步 gate 无出处留痕要件）。三查全过→不动 gate 文本、免重放回归 |
| Node 工具白名单 | 不动（已在 main） | p2-sub1-cost 置位，merge 叠加生效；A/B 不同基按 #23 三分量预登记报价 |
| 断链/MERGED | 不动 | 节点级断链第六例已落地（p2-sub2-cost）；步体 10 轮非极小搬运型下限但归一化步材料面大，MERGED 携带税判据（#24：步体调用越多前序上下文越大断链越优）不利，且子5=确认级无会话无续步对象 |
| pack_full_prior_boundary | 不置位 | 复用材料=本节点留痕全文通道（子1/子2/子3 trace），不经前序节点 boundary 截断面（p2-sub3 同结论） |

## 3. 改法（dl_flow_nodes.py 子4 Step + 测试 + 同步件）

### L1 机制

子4 Step 加 `segment_strip_project_context=True`（第十三例）。

### L2 机制

子4 Step 加 `pack_self_contained=True`（非交互步第六例——u:2#2/u:3#3/u:3#4/
plan:1#5/plan:2#2 之后）。置位前置=装配不变量测试：包须含本节点子1/子2/子3
trace 全文（防未来 P1-1 类包修剪把材料修没了条款变错）。

### L3 条款（purpose 追加，交付即止/格式真源补款之前——与同节点子2/子3
条款块位置对齐，保持「职责→复用→收尾」阅读序）

材料边界（复用钉死，无取证例外形态）：
- 归一化材料=交接包本节点留痕全文通道（子1 要素基线+验收包/子2 单元定义
  +DAG/子3 锚点核验+假设清单）——逐项逐字引用即合法形态，默认零新取证。
- 无取证例外：子2/子3 未定的改动点/接口/验证方法不得进项（gate 判据二
  同义——混入即判 block），新取证在本步无判据出口；零 evidence 翻找
  （前序 trace 已在包内）、零设计文档/understand.md 重读（要素原文引用
  已在子1 留痕）、零 codegraph 查询（调用面核验归子3 已留痕）。
- 职责边界：存在性/影响面/可运行性核验归子3（已留痕），本步零复核；
  为后续步（子5 装配/plan:3 能力选型）预取=越界。

selfcheck 补一条：「材料全部引自交接包本节点前序留痕吗（零新取证/
零 evidence 翻找/零设计文档重读）？」

### 同步件

- tests/test_dl_flow_engine.py：plan:2 strip flags 断言更新（子4 置位）+
  新增 pin 测试（子4 pack_self_contained 置位/复用条款在 purpose/包材料
  不变量=子1/子2/子3 全文在包）。
- skills/workflow-creation/references/nodes-index.md plan:2 行子4 摘要。
- skills/workflow-creation/references/cost-optimization.md：收口沉淀
  （编号取收口时 git log 最大值+1，防并行抢占）。

## 4. 预登记（B vs A，验收口径）

| 指标 | A 基线 | B 预登记 | 判别 |
|---|---|---|---|
| 首调 fresh | 65,860 | **≤42,000（-36% 起）**——strip -11.9k（探针口径）+白名单 -14.3k（merge 叠加分量）±条款回补 ~0.7k | 机制读数，主验收轴 |
| 轮数 | 10 | ≤9（Write 褶皱 1 轮被白名单结构消灭） | |
| 工具调用 | 8 | ≤7 | |
| 段 fresh 合计 | 113,952 | -20% 起（首调口径为主，工具输出地板不变——#33 合计口径=f(首调,轮数,输出地板)） | |
| 段 cr 合计 | 631,040 | **-30% 起**（每调前缀 -26.2k×~9 调 + Write 轮消灭） | |
| 成本等效 | 177,056 | **-25% 起** | 主验收轴 |
| 段 out | 28,909 | ±10% 内（质量形态[五字段厚度]保留；褶皱成分仅 Write deny 恢复文本 ~1k） | #30 两成分口径 |
| 段 dur_api | 184.2s | ≤175s（out÷rate 拟合归因，双轴分开登记；out 大体持平→墙钟主要靠轮数 -1） | #30 墙钟口径 |
| append-trace mech 拒 | 0 | 0 | |
| 门控 | 零 block | 零 block | 硬约束 |

trace 质量逐条自查（防 Goodhart）：statements 五键逐键非空、与子2/子3 内容
一致（无丢失无篡改无新增）、假设原样传导（置信度×影响保留）、验收包/要素
双向覆盖无漏、原子性合规——复用钉死不得稀释保真转换（字段仍逐项承接，
只是出处生产时间前移）。

**诚实声明（立项预期管理）**：本步行为面已被前序批次（p2-sub2-cost L5 补款+
归一化步天然形态）推到近理想最小形态，本轮杠杆全在前缀层（strip/白名单）
+方差防守（pack/复用条款），等效降幅预期 -25~-35% 而非此前各步的 -50~-85%
——行为层油水已在基线前抽干，这是收官态步的合理预期（#22 关闭清单精神：
承认「已接近地板」比夸大杠杆诚实）。

混淆声明：①**A/B 不同基**——A 轮（cbdf8ff）无 Node 白名单，B 轮（main 已合
p2-sub1-cost）有白名单：首调读数含 -14.3k 白名单分量（merge 叠加非本设计
杠杆），预登记按三分量报价（内容包/strip/白名单），机制读数可分离归因；
白名单同时结构性消灭 Write 褶皱（轮数 -1 归此分量）；②amplitude 今日值
4929.2% vs 种子叙事 4824.5% 漂移=#18 两轮同漂移面，子4 零取证条款下数据
文件核验面整体不存在，预计不触发（p2-sub3 同结论）；③种子八件套族：
evidence 裁 ≤plan:2#3（保留子2 off-by-one 重跑对两条）、last_judged_trace
裁 ≤子3、段记录/链/stash 清零、settings 名替换、handoff_pack 起跑前冒烟、
state 四字段同步（phase/sub_index/sub_step_index/node——sub_step_index=4=
「将跑之步」1-based，p2-sub3 off-by-one 教训）、产物文件（designs/<name>-
design.md 拷贝自种子实例——子4 不读 design.md 但包产物清单节须非空，#33③）；
④B 轮过子4 后 driver 会续跑子5（确认级零成本）+plan:3 各段——只子4 段进
A/B 口径，后续段不剔出不误读（段切分以 result 事件+session_id 双锚）。

## 5. 实测收官

（待 B 轮跑完回填）

## 6. 遗留

（待收口回填）
