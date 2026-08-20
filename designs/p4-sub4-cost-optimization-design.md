# plan:4 子4（归一化执行计划包）耗时/token 优化设计——步级断链 + Step strip + pack_self_contained + 复用钉死（无取证例外形态）

> 日期：2026-08-20 · 分支 feat/p4-sub4-cost · 状态：设计定稿（待 A/B）
> 上游：designs/p3-sub5-cost-optimization-design.md（归一化步优化范式，
>      本设计=该范式在 plan:4#4 的同型平移）；p4-sub2-cost（同节点子2
>      先例）；cost-optimization #16/#20/#23/#24/#26/#34/#37/#40/#43/#45。
> 触发 = 用户指令（2026-08-20）：「优化 plan:4 的 step4，耗时和 token
> 消耗要大幅降低，能用前面步骤沉淀下来的 discovered 和 evidence 就尽量
> 用，避免 factor 化；跑测试工作流用 ac-deepseek1；amplitude 今日值
> 4929.2%」。
> 数值口径：种子 problem_statement 保持 4824.5% 不改（runtime-audit #25：
> 数值漂移属 #18 混淆面）；4929.2% = 今日实际值，若运行中被问以此作答。
> 避免 factor 化 = cost-optimization #2（全部杠杆为框架通用机制/通用措辞，
> 零项目语义耦合——禁把测试实例的因子名/文件面/数值写进引擎条款）。

## 0. 范围声明

本设计只覆盖 **plan:4 子4（归一化执行计划包，非交互 skill 步，
record_format=statements 十字段）**。
并行约束：feat/p4-sub3-cost 在飞（设计 3f5213e：子3 锚点核验——步级
断链第七例 + strip 第二十例 + pack 非交互第十例 + 复用钉死 #39 核验步
形态，工作区有未提交实现）。本分支从 main（08674c9）切出，逐文件改动
面与其错位（彼=子3 Step/条款；此=子4 Step/条款 + engine SKIP_STEPS
各自条目 + 各自测试）。
收口并轨点：①断链/strip/pack 例数注释（彼占断链第七/strip 第二十/
pack 第十，本支占断链第八/strip 第二十一/pack 第十一，merge 按 git
log 复核）；②cost-optimization 沉淀编号（收口时 git log 最大值+1）；
③test_p4_other_steps_no_step_strip 豁免集（彼加子3、此加子4，
文本冲突按并轨收口）；④test_p4_step2_step_level_strip_and_pack 的
strips 列表断言（彼 [T,T,T,F,F]、此 [T,T,F,T,F]，并轨=[T,T,T,T,F]）；
⑤nodes-index plan:4 行（彼子3 摘要+此子4 摘要嫁接）。

## 1. 前置勘察（2026-08-20，已完成的只读审计）

- **免跑基线核查（#30 三查）= 不存在**：p2_sub3_ab 止于 plan:4#2
  （state sub_step_index=2，chain last_step=1）；p4_sub1_ab 止于
  plan:4#1；p4_sub2_ab 止于 plan:4#2（chain last_step=2，evidence
  ExecutionPlanCheckpoints trace 仅 sub_step 1/2 两条逐字核实）——
  无任何实例跑过 plan:4#4。tail_volume（2026-08-06）跑过但当时
  record_format 未迁 statements（v2.119 正是被它实爆后修的），
  载荷格式不同不可比。→ **A 臂自跑基线**（p3-sub3-cost 先例：
  p3_sub3_base 同码同种子 A 臂）。
- **置位现状**：plan:4 子4 零 strip/零 pack、("plan:4",4) 不在
  SEGMENT_CHAIN_SKIP_STEPS（当前链：子1 fresh 链头 → 子2 豁免 fresh
  → 子3 resume 子2 会话 → 子4 resume 同会话 = 子4 首调=子2+子3
  transcript 冷重写）、purpose 零复用/交付即止/格式真源条款。
- **交接包材料完备性（pack 置位前置逐字段核对，#16/#19）**：子4 输入
  契约=input="step3.verified_controls"，实际消费面（gate 判材边界
  自述）= 子1 五类清单（验收包 triggered 标注=方框四对照面）+ 子2
  调度四件提案+检查点三属性+goal anchoring+密度论证（方框一对照面）
  + 子3 四类核验留痕+三态标注+假设清单（方框一对照面+假设传导源）
  ——全部经交接包「本节点各步最新留痕保内容全文」通道 100% 在包
  （engine handoff_pack 生产代码核对：prior=False 路径 _slim_trace_
  for_pack 只剥 _PACK_TRACE_DROP_KEYS 机械字段，statements/qa 全文
  保留零截断）；四源文件（design.md/plan.md/understand.md）材料经
  子1 trace 原文引用承载（gate 判材边界同向「主仓 .md 文件结构性
  读不到…只判 trace 内自洽」）；判据命令 dry-run/交集实算归子3
  已留痕（gate 命题性质「均归子3…本步不判」）。→ 材料 100% 在包，
  置位合格（装配不变量测试钉死：plan:4#4 包含子1/2/3 trace 全文）。
- **无取证例外形态适用性（#34 判别问句）**：子4 gate 方框一（b）
  「混入子2/子3 未定的内容判 block」+ 命题性质「本步只判归一化文本
  形态齐备+字段忠实+形式合规」= gate 结构性封死包外材料合法出口
  （新取证产出进 fields 即「新增」违规）→ 无取证例外形态成立
  （p1-sub2/p2-sub2/p2-sub4/p3-sub5 后第五例）。

## 2. 杠杆选型

| 杠杆 | 置位？ | 依据 |
|---|---|---|
| **L1 步级断链 ("plan:4",4) 入 SEGMENT_CHAIN_SKIP_STEPS**（步级第八例——p4-sub3 在飞占第七，merge 复核） | **置位** | #20 deepseek 会话隔离缓存下链首调恒冷（同节点子2 免跑基线 169,338/cr=0、子2 B 轮 fresh 化后 cr=0 复证；子4 链内首调=子2 ~10 轮+子3 核验轮 transcript 全额冷重写，A 臂实测报价）+ #24 携带税主导（归一化步步体 ~5-8 轮小，但每调背子2+子3 全量继承上下文单调涨——携带税主导断链确定优，暖率彩票不赌）。材料完备性逐字段核对见 §1（子1/2/3 trace 全文在包=输入契约全集）。后续步暴露面（#30 扩面核对）：子5=confirm 级（P3-1）无模型会话零暴露面；轮数上限暴露面无（#20 补预登记：后续步无会话）。豁免集即回滚面（摘条目=恢复链）。节点白名单不动、plan:4 其余步零行为变化（surgical——p4-sub3 在飞的子3 断链是独立条目，两臂各自成立） |
| **L2 Step 级 segment_strip_project_context 置位子4**（第二十一例——p4-sub3 在飞占第二十，merge 复核） | **置位** | #23 三核对：①交付物=归一化 statements 十字段（调度四+检查点六），正文材料全部经本节点前序 trace 逐字在包（cp_criterion/worker_map 等=子2 提案+子3 核验逐字携带），不引自动加载文档正文（无 CLAUDE.md 条号/正文引用职责——#23 第三核对「正文引用 vs Read 指针」判别：无一等材料依赖，u:3#1 反优化理由不成立）；②逐步工具需求=Bash（scaffold/落库）+Read（骨架）+Edit（骨架）+Skill（define-problem ref 在册）——env 剥离与工具面无关；③gate 判材=judge 读裁剪 trace 不读项目上下文 |
| **L3 pack_self_contained**（非交互第十一例——p4-sub3 在飞占第十，merge 复核） | **置位** | 置位前置逐字段核对见 §1（输入契约 ⊆ 包内本节点前序 trace 全文通道）；#40 方差防守定位（归一化步 fresh 化后包尾通用邀请=元探查诱因，#16 反指邀请——p3-sub5 同型前置）；装配不变量测试钉死（包须含子1/2/3 trace 全文，防未来包修剪把材料修没） |
| **L4 复用钉死条款进 purpose/selfcheck（无取证例外形态，#34 第五例）** | **置位** | 用户决议「能用前序沉淀的 discovered/evidence 就尽量用」。步性质=归一化消费步（从子2 提案+子3 核验忠实提取，零新事实产出职责——#19 判别：搬运型步；gate 方框一「不一致判 block」=搬运型结构性佐证）。条款全机制级通用措辞：默认零新取证 + 无取证例外（字段与子2/子3 已定内容不一致即 gate 判据判 block，新取证无判据出口）+ 零 evidence 翻找/零产物文件重读（四源内容经子1 原文引用留痕承载）/零命令重跑（dry-run/交集实算归子3 已留痕）+ 职责边界（锚点核验归子3 零复核/密度与类型拍板归子5/为后续步预取=越界 #27） |
| **L5 交付即止（#37）+ 格式真源（#26）补款** | **置位** | 平移条款——断链暴露面同批补款（#43：链内乖形态不可信，fresh 化后格式猎捕/交付后徘徊是已实证方差面，p1-sub5/p2-sub2/p3-sub5/p4-sub2 同处置） |
| Node 工具白名单 | 已置位（既有） | p4-sub1-cost 落地件（Bash/Read/Edit/Skill/Agent）——子4 工具需求 ⊆ 白名单（Skill=define-problem 在册，p4-sub1 逐步核对原文「子4 define-problem 归一化要 Skill」），零变更 |
| Node 级 env strip | 不置 | 兄弟步逐步核对归各自立项（p4-sub1/sub2 同处置） |
| MERGED 段内续步 | 不立项 | deepseek 暖率彩票两节点 EV 证伪（#24，u:3 撤出先例；p4-sub2 同结论）+ 归一化步虽步体小但续步须与子3 同进程——子3 步体重取证高方差（#21 判别问句：非「步体极小」组合） |
| gate 文本 | 零变更 | 见 §2.1 三查 |

### 2.1 gate 零变更前置核对三件套（#29 程序）

①mech 词表：子4 零 mech_checks（statement_fields 十键 JSON 校验=
格式存在性校验非词表扫描面）——条款落地不新增命中面。✓
②judge 方框：子4 gate 的 boundary 字段语义本即「假设传导+出处指针」
——「复用 子N 留痕：<出处逐字>」是出处指针的既有生产形态非新增
输出形态（p3-sub5 三查同结论：#39 对照组重放不适用）；判材边界段
已钉「前序 trace 是字段一致性对照面+验收包落点对照面（判材非纯
组成事实）」——复用引用前序留痕与判据同向。✓
③复用引用形态不命中任何现存 block 条件：方框一（不一致/新增）——
复用钉死正是防新增，同向；方框二（复合句）/方框三（判断词回潮）/
方框四（triggered 漏配）均为内容要件，引用形态不影响任一。✓
→ gate 文本零变更，零重放回归负担（p3-sub5/p4-sub2 同结论同程序）。

### 2.2 组织形态核对（#35）

L4 条款为行为面枚举（非交付物圈码清单），不会被镜像成载荷组织结构
（载荷组织=statements 逐项+fields 十键，--scaffold 骨架生成；p3-sub5/
p1-sub5 同款条款生产实证零镜像事故）；子4 无圈码扫描面。✓

## 3. 改法（dl_flow_engine.py / dl_flow_nodes.py / tests / 同步件）

### L1 机制（engine）

SEGMENT_CHAIN_SKIP_STEPS 加 ("plan:4",4) + 注释（步级第八例、plan:4
第三例——p4-sub3 在飞占第七/plan:4 第二例，merge 复核；判据 #20 恒冷
+ #24 携带税；材料=子1/2/3 trace 全文在包；后续子5 确认级无会话零
暴露面；节点白名单不动、兄弟步零行为变化）。

### L2/L3 机制（nodes.py plan:4 子4 Step）

加 `segment_strip_project_context=True`（第二十一例注释）+
`pack_self_contained=True`（非交互第十一例注释）。

### L4/L5 条款（purpose 追加；selfcheck 补）

purpose 末追加（通用措辞，零项目语义；平移 p3-sub5 条款改对象词）：

> 材料边界（复用钉死，无取证例外形态）：归一化材料=交接包本节点
> 留痕全文通道（子1 五类清单+验收包 triggered 标注/子2 调度四件
> 提案+检查点三属性+goal anchoring+密度论证/子3 四类核验留痕+三态
> 标注+假设清单）——逐项逐字引用即合法形态（「复用 子N 留痕：
> <出处逐字>」），默认零新取证。无取证例外：字段与子2/子3 已定
> 内容不一致即 gate 判据判 block，新取证在本步无判据出口——零
> evidence 翻找（前序 trace 已在包内）、零产物文件重读（四源内容
> 经子1 原文引用留痕承载）、零命令重跑（判据 dry-run/交集实算归
> 子3 已留痕）。
> 职责边界：锚点核验归子3（已留痕），本步零复核；密度与类型拍板
> 归子5（本步只归一化不拍板）；为后续步预取=越界。
> 交付即止：落库成功（✓ 已落库）即结束本轮——禁 locate 产物/读
> state/grep evidence 确认落库/预习下一步，推进与门控由外部 driver
> 判定。载荷格式的唯一真源 = --scaffold 骨架+append-trace 报错文案
> ——禁读引擎/测试源码/历史 trace 反推格式；被拒按报错文案逐字修
> 即可。

selfcheck 追加：「材料全部引自交接包本节点前序留痕吗（零新取证/
零 evidence 翻找/零产物文件重读/零命令重跑）？落库后交付即止了吗？」

### 同步件

- tests/test_dl_drive.py：test_chain_skip_steps_constant 加
  ("plan:4",4) 断言+docstring 条目（双侧并轨：p4 既有条目保留）；
  test_chain_resume_step_level_skip_plan4_sub4（豁免步不续链+兄弟步
  子3 链行为不变[本支视角 p4-sub3 未 merge]+子5 confirm 无会话）。
- tests/test_dl_flow_engine.py：test_p4_step4_step_level_strip_and_pack
  （env 双开关+tools 白名单继承+pack 置位 pin+strips 列表 [T,T,F,T,F]
  ——并轨点④）+ test_p4_step4_reuse_delivery_clauses_pinned（条款
  关键词 pin）+ test_p4_step4_pack_materials_invariant（包含子1/2/3
  trace 全文+尾行切换）+ test_p4_other_steps_no_step_strip 豁免集
  (1,2)→(1,2,4)（并轨点③）。
- skills/workflow-creation/references/nodes-index.md plan:4 行子4
  摘要（与 p4-sub3 子3 摘要嫁接）。
- skills/workflow-creation/references/cost-optimization.md：收口沉淀
  （编号取收口时 git log 最大值+1，防并行抢占）。

## 4. 预登记（B vs A，验收口径）

A 臂=p4_sub4_base（main 08674c9 码，种子=p4_sub2_ab evidence≤plan:4#2
+chain last_step=2+链 transcript 拷入），跑子3（链内 resume）+子4
（链内 resume=基线测量面），门栏自然收段零看护器依赖；B 臂=
p4_sub4_ab（本支 worktree 码，种子=A 臂 evidence≤plan:4#3 逐字同源
+chain last_step=3 对齐），只跑子4 fresh 段。
预期（机制确定性部分）：首调 fresh A（子2+子3 transcript 冷重写，
预估 100-250k 量级，A 臂实测）→ B ~45-60k（fresh 地板=包[子1/2/3
trace 全文 ~35-50k 字符≈12-17k tok+prior 摘要]+harness 22.3k-11.9k
strip+工具 schema 白名单 5 件——起跑前 handoff_pack 冒烟实测包大小
后精确化目标）；段 cr 主降因=上下文重置（每调背 ~50-60k vs 150-250k
单调涨）+轮数降。

| 指标 | A 基线 | B 预登记 | 判别 |
|---|---|---|---|
| 首调 fresh | A 臂实测（链内冷重写，cr≈0） | **≤60,000**（包实测后精确化——#23 三分量逐项报价） | L1+L2 |
| 段 cr 合计 | A 臂实测 | **-55% 起**（上下文重置+轮数降） | 主驱动 |
| 段等效（fresh+cr×0.1） | A 臂实测 | **-50% 起** | 主验收轴 |
| 轮数 | A 臂实测 | **≤8**（理想最小形态：Skill+scaffold+Read 骨架+Edit+落库 ≈ 5-6 轮） | L4+L5 |
| 工具调用 | A 臂实测 | 理想最小形态（零探索/零翻找/零命令重跑） | L4 |
| 段 out | A 臂实测 | ≤1.9× 上限登记（#33：复用钉死逐字引用义务=净增量——归一化步 boundary 出处指针义务原已在形式要件内[p3-sub1/p3-sub4 先例=形态替换不放大]，但断链 fresh 化再生税按 #46 上限报价；双轴登记） | 双轴登记 |
| 段 dur_api | A 臂实测 | out÷rate 拟合归因，与 token 轴分开登记（#30） | 双轴登记 |
| 门控 | — | **零 block** | 硬约束 |

trace 质量逐条自查（防 Goodhart）：statements 逐项 text 单句原子/
fields 十键逐键非空（调度项 cp_* 六键填「无」）/字段与子2/子3 已定
内容一致（无丢失无篡改无新增）/triggered 验收项落点或 continuous
覆盖声明/假设传导（子3 假设项原样携带）/判据零判断词保持/出处指针
逐字可溯源子2/子3 留痕——按 gate 方框逐条自查 B 轮 trace。复用钉死
不得稀释执行接地（归一化内容仍忠实携带子2/子3 全量字段，只是出处
生产时间前移到交接包留痕）。

混淆声明（预登记）：①A=链内段 vs B=fresh 段——形态差即断链杠杆
本身（#20 口径：首调=链税直接度量，p3-sub2/3/4/5/p4-sub2 同口径
先例）；②B 种子=A 臂 evidence 裁 ≤plan:4#3 逐字同源（三查②最强
形态）；③种子数值 4824.5% 与今日值 4929.2% 漂移属 #18，两轮同
种子同漂移面——子4 归一化对象=子2/子3 已定内容非因子数值现状，
预计不触发（若模型被问以 4929.2% 作答）；④A 臂顺带跑子3=本设计
测量面外段，子3 段账登记为驱动工件不计入子4 对比（p4-sub3-cost
可拿去当免跑基线——同码[main]同种子段）；⑤断链后 out/轮数按
fresh 形态报价（#46）；⑥p4-sub3-cost 在飞：其落地件（子3 断链/
strip/pack/条款）不在任一臂——两臂子4 面差=本设计落地件 only；
⑦种子第九件（#45）：A 臂 chain.last_step=2==sub_step_index-1 ✓
（p4_sub2_ab state 原样对齐）；B 臂 chain.last_step=3==4-1 对齐装配
+("plan:4",4) 豁免集双保险；⑧A 臂子4 过后子5=confirm 机械段+节点
门栏 ARTIFACT_CONTAINS 机械门+hold_for_gate 扣留——零模型成本，
无需看护器（p4-sub2 ⑧的看护器面本设计不存在）；⑨种子产物文件
（#33③）：.claude/understands/.claude/plans/designs/ 三处
p4_sub2_ab-* 产物改名拷贝（两句分写，#48 先读后写坑），起跑前冒烟
「包内产物清单节非空」。
