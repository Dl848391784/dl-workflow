# plan:4 子2（调度与检查点方案提案）耗时/token 优化设计——步级断链 + Step strip + pack_self_contained + 复用钉死（消费步形态）+ 红队材料包三钉

> 日期：2026-08-20 · 分支 feat/p4-sub2-cost · 状态：设计中
> 上游：designs/p1-sub4-cost-optimization-design.md（提案+条件红队步优化
>      范式，本设计=该范式在 plan:4#2 的同型平移）；cost-optimization
>      #16/#20/#23/#24/#26/#30/#33/#35/#36/#37/#43/#44/#45/#46。
> 触发 = 用户指令（2026-08-20）：「优化 plan:4 的 step2，耗时和 token
> 消耗要大幅降低，能用前面步骤沉淀下来的 discovered 和 evidence 就尽量
> 用，避免 factor 化；跑测试工作流用 ac-deepseek1；amplitude 今日值
> 4929.2%」。
> 数值口径：种子 problem_statement 保持 4824.5% 不改（runtime-audit #25：
> 数值漂移属 #18 混淆面）；4929.2% = 今日实际值，若运行中被问以此作答。
> 避免 factor 化 = cost-optimization #2（全部杠杆为框架通用机制/通用措辞，
> 零项目语义耦合——禁把测试实例的因子名/文件面/数值写进引擎条款）。

## 0. 范围声明

本设计只覆盖 **plan:4 子2（调度与检查点方案提案，非交互 skill 步，含
条件红队）**。并行约束：feat/p4-sub1-cost 在飞（设计已定稿 c51f870：
子1 strip 第十八例 + plan:4 Node 工具白名单首例 + 子1 复用钉死③型），
本分支从 main（288366b）切出，逐文件改动面与其错位（彼=子1 Step/Node
白名单/子1 条款；此=子2 Step/条款 + engine SKIP_STEPS 条目 + 各自测试）。
收口并轨点：①strip 例数注释（彼十八此十九，merge 时复核 git log）；
②cost-optimization 沉淀编号（收口时 git log 最大值+1）；
③test_other_nodes_zero_change 豁免集（彼加 plan:4 tools，本支不动
Node 级）；④test_p4_other_steps 类兄弟步断言双侧；⑤nodes-index
plan:4 行（彼子1 摘要+此子2 摘要嫁接）。**Node 工具白名单不在本设计
落地**（在飞会话的落地件），本设计预登记按「白名单缺席」口径报价，
merge 叠加后首调再降 ~13.5k 归彼臂效果。

## 1. 前置勘察（2026-08-20，已完成的只读审计）

- **免跑基线（#30，第六例）= p2_sub3_ab 实例 plan:4#2 段**（2026-08-20
  16:03 实跑，ac-deepseek1/deepseek-v4-flash headless，session 23e5b1c4
  链内续段——chain.last_step=1，resume 子1 会话）。三查：
  ①目标步代码两轮间零变更——A 轮 launcher=feat/p2-sub3-cost worktree
  （80de063），`git diff 80de063..main`（main=288366b）对 plan:4/EPC/
  ExecutionPlanCheckpoints 关键词命中数=0（nodes.py 变更全在 plan:3 域、
  engine 变更为 plan:3 SKIP_STEPS 条目、dl_drive.py/phase-rules.md 零
  diff）——plan:4#2 可见面（purpose/gate/ref/交接包装配/spawn 前缀）
  A 轮码与 main 逐字相同 ✓；
  ②种子 evidence——B 轮直接以 p2_sub3_ab 自身 evidence 裁 ≤plan:4#1
  trace（41 行）为种子，前序 trace 与 A 轮子2 实际消费的前序 trace
  同一份逐字相同（三查②最强形态，#38 补）✓；
  ③段口径——A 段=链内续段（resume 子1 31 轮 transcript，首调 cr=0
  恒冷实锤），B 段=断链后 fresh spawn——形态差即杠杆本身（#20 口径：
  首调=链税直接度量），写进混淆声明 ✓。
- **置位现状**：plan:4 子2 零 strip/零 pack、("plan:4",2) 不在
  SEGMENT_CHAIN_SKIP_STEPS、purpose 零复用/红队材料包/交付即止/格式
  真源条款；ref 载「对齐源 superpowers:writing-plans / executing-plans
  （checkpoint 语义真源）」=skill 文件猎捕诱因（见 §1.5 分解）。
- **交接包材料完备性（pack 置位前置逐字段核对，#16/#19）**：子2 输入
  契约=input="step1.control_baseline"——子1 五类清单 trace（①任务 DAG
  ②能力绑定③验收包④假设汇总⑤不可逆操作候选+四源原文引用）经交接包
  「当前节点已完成步最新 trace 保内容全文」通道 100% 在包（engine
  handoff_pack 生产代码核对）；四源文件（design.md/plan.md/
  understand.md）材料经子1 trace 原文引用承载（gate 判材边界同向：
  「四源 judge 结构性读不到…只判 trace 内自洽」）；红队触发阈值**无
  全局定义可查**（nodes.py/phase-rules.md 全文 grep 零命中——基线模型
  grep phase-rules 找阈值是注定无果的猎捕，gate 明文「不得索阈值定义
  或触发论证」）；对齐源 skill 内容非取证面（checkpoint 语义已操作化
  进 _EPC_STEP2_FORM_REQUIREMENTS+gate 方框，基线模型 5 次 find/ls
  猎捕后**零 Read 消费**=纯 locate thrash 实锤）。→ 材料 100% 在包，
  置位合格（装配不变量测试钉死：plan:4#2 包含 ExecutionPlanCheckpoints
  子1 trace 全文）。
- **A 轮门控**：evidence 无 block 记录、gate 过后推进子3（chain
  last_step=2）= 一次通过零 block、append-trace 零 mech 拒。

### 1.5 基线实测（A = p2_sub3_ab plan:4#2 链内段，免跑基线）

| 指标 | A（主段） | A（红队 agent） |
|---|---|---|
| 首调 fresh / cr | **169,338 / 0（链恒冷实锤）** | 30,899 / 0 |
| 段 fresh 合计（result modelUsage） | 223,083 | 61,798 |
| 段 cr 合计 | 1,862,144 | 0 |
| 段 out 合计 | 68,350 | 32,033 |
| 轮数（result 权威值） | 12 | — |
| 段 dur_api | 537.7s | — |
| 工具调用 | 11（Bash×6/Agent×1/Read×1/Edit×1 + 交付通道） | **0** |
| 成本等效（fresh+cr×0.1） | 409,297 | 61,798 |
| **合并等效** | **471,095** | |

**浪费分解（主段 11 调用逐条归因，runtime-audit #26 三分诊）**

| 浪费类 | 调用 | 定性 |
|---|---|---|
| skill 文件猎捕 | #1/#3/#4/#5/#9（find×3+ls×2 定位 writing-plans/executing-plans SKILL.md，全程零 Read 消费） | **纯税**——ref「对齐源…（checkpoint 语义真源）」是诱因；语义已操作化进形式要件+gate，locate 零收益 |
| phase-rules 红队阈值 grep | #2 | **纯税**——阈值无全局定义（注定无果）+gate 明文不索阈值论证 |
| 条件红队派发 | #6（Agent，prompt 3,140 字符逐字携带材料包：执行单元文件面/DAG/分组提案/检查点三属性/密度论证） | 合法（条件触发判定=并行组 2/检查点 3）；**但材料包携带是链内乖形态**（#43：链上下文兜底，fresh 化后方差暴露面——红队材料包三钉=方差防守主条款） |
| 交付通道 | #7/#8/#10/#11（scaffold/Read 骨架/Edit/append 一次过） | 合法（零 mech 拒零返工褶皱） |
| 交付后徘徊 | 无 | — |

**三层瓶颈分诊（#1/#20/#23）**：①段边界层（主税一）：链内续段首调
169,338 = 子1 31 轮 transcript 冷重写（cr=0，deepseek 会话隔离缓存
恒冷 #20）+ 段 cr 1.86M = 12 轮 × 平均 ~155k 单调涨上下文重读
（#24 携带税主导）；②前缀层：fresh 化后工具 schema 25 个 ~14.3k
（Node 白名单=在飞会话落地件，本设计不重复）+ 项目上下文 ~11.9k
（Step strip 可剥）两个可裁分量；③步体层（主税二）：11 调用中 6
纯税（skill 猎捕 5+阈值 grep 1），红队 0 重勘为链内乖形态需条款
防守（#43）。

## 2. 杠杆选型

| 杠杆 | 置位？ | 依据 |
|---|---|---|
| **L1 步级断链 ("plan:4",2) 入 SEGMENT_CHAIN_SKIP_STEPS**（步级第六例，plan:4 首例） | **置位** | #20 链首调恒冷（A 首调 169,338/cr=0 = 子1 transcript 冷重写实锤）+ #24 携带税主导（12 轮 × ~155k/轮，步体调用越多前序上下文越大携带税越主导——断链确定优，暖率彩票不赌）。材料完备性逐字段核对见 §1（子1 trace 全文在包=输入契约全集）。后续步暴露面（#30 扩面核对）：子3 仍链内 resume——换挂子2 fresh 会话（继承 transcript 从「子1 31 轮+子2」缩为「子2 ~7 轮」，携带量变小同向）；子3 无 fresh 化、无新暴露面。豁免集即回滚面（摘条目=恢复链）。节点白名单不动、plan:4 其余步零行为变化（surgical）。**与 p4-sub1 叠加声明**：彼落地后子1 轮数 31→~10，链携带税缩水（~145k→~50-70k）但仍 > fresh 恒定地板，断链 EV 结论不变（#24 抉择口径：12 轮步体 × 50k+ 携带仍主导） |
| **L2 Step 级 segment_strip_project_context 置位子2**（第十九例——p4-sub1 在飞占第十八，merge 复核） | **置位** | #23 三核对：①交付物=调度四件+检查点方案+红队留痕，正文零引用 CLAUDE.md/auto-memory 内容（_EPC_STEP2_FORM_REQUIREMENTS 自给，无项目文档条号/正文引用职责——#23 第三核对「正文引用 vs Read 指针」判别：无一等材料依赖）；②逐步工具需求=Bash（scaffold/落库）+Read（骨架）+Edit（骨架）+Agent（条件红队 fence_allow 在册）——env 剥离与工具面无关；③gate 判材=judge 读裁剪 trace 不读项目上下文 |
| **L3 pack_self_contained**（非交互第九例——p3-sub5 占第八） | **置位** | 置位前置逐字段核对见 §1（输入契约 ⊆ 包内前序 trace 全文通道，红队阈值/对齐源均非包外材料面）；#40 方差防守定位（基线 de facto 零 evidence 翻找，防 fresh 化后包尾通用邀请诱发元探查——#16 反指邀请）；装配不变量测试钉死（包须含子1 trace 全文，防未来包修剪把材料修没） |
| **L4 复用钉死条款进 purpose/selfcheck（消费步形态，p1-sub4 同型平移）** | **置位** | 用户决议「能用前序沉淀的 discovered/evidence 就尽量用」。步性质=消费步（从子1 保真基线清单推导控制结构提案，零新事实产出职责——#19 判别：搬运+判断非新取证步）。条款五禁令全机制级通用措辞：零 evidence 翻找/零仓内文件重读/零 find·ls·grep locate skill 文件（ref 诱因同步拆除：ref 改「推理（DAG 拓扑分层 + 控制结构设计） / Agent（条件红队）」，对齐源信息下沉代码注释=设计文档面不进模型可见面）/零 phase-rules·规范文档翻找（红队触发判定=附计数自主声明，无全局阈值定义可查、judge 不索阈值论证）/唯一取证面=条件红队派发（触发时） |
| **L5 红队材料包三钉（#36 第三例，p1-sub4/p3-sub3 条款平移改对象词）** | **置位** | 基线红队虽 0 重勘（乖形态），#43 单样本地板判断不可信——fresh 化后链兜底消失，红队退化重勘是方差主暴露面（p1-sub4 基线红队 58 调用占步总账 73% 前科）。三钉：①派发 prompt 逐字携带攻击对象材料包；②职责=基于材料的独立判断攻击，存在性/出处以子1 留痕为准零重验，禁重跑勘察类工具，确需复核 Read 单点定点（每攻击点至多 1 次）；③攻击对象=调度与检查点提案整体一次。预派发否决（#12 判据②不成立：攻击对象=本步产出提案，gate 通过前未冻结，prompt 不可脚本生成——p1-sub4 同否决） |
| **L6 交付即止（#37）+ 格式真源（#26）补款** | **置位** | 平移条款——基线零徘徊/零格式猎捕=方差防守定位（#40：断链暴露面同批补款，p3-sub3/p3-sub5 同处置） |
| Node 工具白名单（plan:4 首例） | 不置位（在飞件） | feat/p4-sub1-cost 落地件——本设计不重复落地、不计入本轮验收；merge 叠加后首调再降 ~13.5k 归彼臂 |
| Node 级 env strip | 不置 | 兄弟步逐步核对归各自立项（p4-sub1 同处置） |
| MERGED 段内续步 | 不立项 | 步体非极小（提案生成+红队派发）+deepseek 暖率彩票两节点 EV 证伪（#24，u:3 撤出先例；p1-sub4/p3-sub3 同结论） |
| gate 文本 | 零变更 | 见 §2.1 三查 |

### 2.1 gate 零变更前置核对三件套（#29 程序）

①mech 词表：子2 零 mech_checks（无 append-trace 机械扫描面）——条款
落地不新增命中面。✓
②judge 方框：子2 gate 无出处要件（提案内容本就从子1 清单推导，
「逐字引用子1 留痕」不是新增输出形态——#39 对照组重放不适用）；
红队留痕合法形态=「红队条件未触发声明附计数（并行组数/检查点数）
即合规，不得索阈值定义或触发论证」已在判材边界段——L4「附计数自主
声明」与判据同向；L5 约束行为面（派发材料/重勘禁令）不动判据
（p1-sub4 三查同结论：「多攻逐条附理由」限触发后攻击对象数，gate
「未触发前提下自愿跑=加强」为既判合法形态互不冲突）。✓
③复用引用/材料包引用形态不命中任何现存 block 条件：方框一-六均为
内容要件（判据可执行形/路由预定义/文件清单+交集结论/返回契约证据
形式/密度论证/提案措辞），引用形态不影响任一。✓
→ gate 文本零变更，零重放回归负担（p1-sub4/p3-sub3 同结论同程序）。

### 2.2 组织形态核对（#35）

L4 五禁令/L5 三钉为行为面枚举（非交付物圈码清单），不会被镜像成
载荷组织结构（载荷组织=形式要件八 q/a：调度四件/检查点三属性/密度
论证/红队留痕/提案语义——p1-sub4/p3-sub3 同款条款两轮生产实证零
镜像事故）；子2 无 mech_checks 圈码扫描面。✓

## 3. 改法（dl_flow_engine.py / dl_flow_nodes.py / tests / 同步件）

### L1 机制（engine）

SEGMENT_CHAIN_SKIP_STEPS 加 ("plan:4",2) + 注释（步级第六例、plan:4
首例；判据 #20 恒冷 A 首调 169,338/cr=0 + #24 携带税 12 轮 × ~155k；
材料=子1 trace 全文在包；后续子3 resume 换挂子2 fresh 会话携带量
变小同向；节点白名单不动、兄弟步零行为变化）。

### L2/L3 机制（nodes.py plan:4 子2 Step）

加 `segment_strip_project_context=True`（第十九例注释）+
`pack_self_contained=True`（非交互第九例注释）。

### L4/L5/L6 条款（purpose 追加；selfcheck 补；ref 改）

ref 改（对齐源指针下沉注释，拆除猎捕诱因）：
`推理(DAG 拓扑分层 + 控制结构设计) / Agent(条件红队)`
（对齐源 superpowers:writing-plans / executing-plans = 设计期语义
出处注释保留在代码注释面——checkpoint 语义已操作化进
_EPC_STEP2_FORM_REQUIREMENTS+gate，执行期零文件系统 locate）。

purpose 末追加（通用措辞，零项目语义；平移 p1-sub4/p3-sub3 条款改
对象词）：

> 材料边界（复用钉死）：调度与检查点方案的全部输入=子1 五类清单
> trace（任务 DAG/能力绑定/验收包/假设汇总/不可逆操作候选，含四源
> 原文引用），经交接包本节点前序 trace 全文在包——逐字直接引用即
> 合法出处；本步零新取证：不跑 codegraph/grep/find/ls、不 Read 仓内
> 文件重验重定位、零 evidence 全量翻找、零 phase-rules/规范文档翻找
> （红队触发判定=附并行组数/检查点数计数自主声明——无全局阈值定义
> 可查，judge 不索阈值论证）、零 skill 文件系统 locate（writing-plans/
> executing-plans 是设计期对齐源指针，checkpoint 语义已操作化进本步
> 形式要件，find/ls 定位 skill 文件零收益）；唯一取证面=条件红队派发
> （触发时）。
> 红队材料包三钉（条件触发时）：①派发 prompt 逐字携带攻击对象材料
> 包（调度四件提案+逐检查点三属性/goal anchoring/密度论证+子1 五类
> 清单出处，均在你本会话上下文，复制即可）；②红队职责=基于材料的
> 独立判断攻击（分组逻辑/互斥面完备性/判据可执行性/失败路由/密度
> 匹配），清单条目存在性与四源出处以子1 留痕为准零重验，禁重跑勘察
> 类工具（codegraph/grep 全仓/读产物文件全文），确需复核 Read 单点
> 文件定点核对（每攻击点至多 1 次）；③攻击对象=调度与检查点提案
> 整体一次，多攻须逐条附理由。
> 交付即止：落库成功（✓ 已落库）即结束本轮——禁 locate 产物/读
> state/grep evidence 确认落库/预习下一步（含子3 核验手段查探），
> 推进与门控由外部 driver 判定。载荷格式的唯一真源 = --scaffold 骨架
> +append-trace 报错文案——禁读引擎/测试源码/历史 trace 反推格式；
> 被拒按报错文案逐字修即可。

selfcheck 追加：「材料全从交接包子1 留痕直接引用了吗（零 find/ls/
grep locate skill 文件、零 phase-rules 翻找、零 evidence 翻找）？
红队派发 prompt 逐字携带材料包了吗？交付即止了吗？」

### 同步件

- tests/test_dl_drive.py：test_chain_skip_steps_constant 加
  ("plan:4",2) 断言+docstring 条目（双侧并轨：p3 五条目保留）；
  test_chain_resume_step_level_skip_plan4_sub2（豁免步不续链+兄弟步
  子3 零行为变化）。
- tests/test_dl_flow_engine.py：test_p4_step2_step_level_strip_and_pack
  （env 双开关+pack 置位 pin——tools 断言待 p4-sub1 Node 白名单 merge
  后补，本支只断 env/pack，避免与在飞件互踩）+
  test_p4_step2_reuse_redteam_delivery_clauses_pinned（条款关键词 pin
  +ref 形态 pin「writing-plans 不在 ref」）+
  test_p4_other_steps_no_step_strip（兄弟步子1/3/4/5 零置位——子1 若
  p4-sub1 先 merge 则并轨豁免集）+
  plan:4#2 包含子1 trace 全文装配不变量（handoff_pack 冒烟断言，
  对齐既有 pack 不变量测试形态）。
- skills/workflow-creation/references/nodes-index.md plan:4 行子2
  摘要（与 p4-sub1 子1 摘要嫁接）。
- skills/workflow-creation/references/cost-optimization.md：收口沉淀
  （编号取收口时 git log 最大值+1，防并行抢占）。

## 4. 预登记（B vs A，验收口径）

预期（机制确定性部分）：首调 fresh 169,338 → ~50-56k（断链灭链携带
冷重写——fresh 地板参考同实例子1 链头 fresh spawn 58,145 + 子1
trace 入包增量 ~10.3k 字符 ≈ +4k + strip -11.9k ≈ 50k；Node 白名单
缺席，工具 schema ~14.3k 留存计入地板）；段 cr 主降因=上下文重置
（每调背 ~55-65k vs ~155k）+轮数 12→~7-9 × 每轮前缀降。

| 指标 | A 基线 | B 预登记 | 判别 |
|---|---|---|---|
| 首调 fresh | 169,338（cr=0） | **≤56,000**（-67% 起——机制读数，#23 三分量逐项报价：包 ~26k+harness ~22.3k-11.9k strip+工具 schema ~14.3k 留存） | L1+L2 |
| 主段 cr 合计 | 1,862,144 | **-70% 起**（上下文重置+轮数降+纯税调用清零） | 主驱动 |
| 合并等效（主段+红队） | 471,095 | **-55% 起** | 主验收轴 |
| 轮数 | 12 | **≤9**（理想最小形态：红队派发 1+交付通道 4 ≈ 6-7 轮） | L4+L6 |
| 工具调用（主段） | 11 | ≤7（纯税 6 清零：skill 猎捕 5+阈值 grep 1） | L4 |
| 红队（若触发） | fresh 61,798/0 工具 | 工具 ≤2 且攻击报告实质（方差防守验收=爆炸形态不露头，#43②；等效 ≤75k 登记） | L5 |
| 段 out（主段） | 68,350 | ≤1.5×（≈103k）上限登记——复用钉死=禁令形态无引用义务净增量（#44 形态替换判不放大），但断链 fresh 化再生税按 #46 上限报价；1.9× thinking 报价不适用（无新引用义务） | 双轴登记 |
| 段 dur_api | 537.7s | out÷rate 拟合归因（~127 tok/s 基线率），与 token 轴分开登记（#30） | 双轴登记 |
| 门控 | 一次通过零 block | **零 block** | 硬约束 |

trace 质量逐条自查（防 Goodhart）：调度四件齐备（并行分组附拓扑
分层+同层无依赖声明/互斥面从改动点计算+组内交集结论/worker 任务包
映射/返回契约证据形式清单）/检查点三属性逐 CP 齐（零判断词判据承接
验收包 ID/三选一失败路由/类型）/goal anchoring 逐 CP/密度论证或复利
论证/红队留痕或条件未触发声明附计数/只提案不拍板语义/q,a 按序对齐
——按 gate 方框逐条自查 B 轮 trace。复用钉死不得稀释执行接地（提案
内容仍从子1 清单逐项推导，只是出处生产时间前移到交接包留痕）。

混淆声明（预登记）：①A=链内段 vs B=fresh 段——形态差即断链杠杆
本身（#20 口径：首调=链税直接度量，p3-sub2/3/4/5 同口径先例）；
②A=免跑基线与 B 同种子 evidence 逐字同源（p2_sub3_ab 自身 evidence
裁 ≤plan:4#1 共 41 行），包差异=实例名替换（p2_sub3_ab→p4_sub2_ab，
逐字符等量）；③种子数值 4824.5% 与今日值 4929.2% 漂移属 #18，两轮
同种子同漂移面——子2 提案对象=子1 清单非因子数值现状，预计不触发
（若模型被问以 4929.2% 作答）；④A 轮 launcher=p2-sub3-cost worktree
（80de063）与 B 轮码的 plan:4#2 可见面逐字差=本设计落地件（三查①
diff 零命中已核）；⑤断链后 out/轮数按 fresh 形态报价（#46——链内
乖形态的少再生不可线性外推）；⑥p4-sub1-cost 在飞：其落地件（子1
strip/Node 白名单/子1 条款）不在任一臂——两臂 plan:4#2 面差=本设计
落地件 only，叠加效果归彼臂验收；⑦红队触发与否是模型自主判定面
（A 触发：并行组 2/检查点 3）——B 未触发时红队面记 0 并按「未触发
声明附计数」验收 trace，合并等效两态分开读数；⑧B 轮驱动只跑子2
一段——gate 裁决落盘后看护器杀 driver+段进程（连带 pkill 段孤儿，
p1-sub5-cost 教训），子3 起链段不计入账面（登记为驱动工件）；
⑨种子第九件（#45）：("plan:4",2) 入豁免集后 _chain_resume_sid 恒
None，fresh spawn 与 chain 台账无关——但种子 chain.last_step 仍对齐
sub_step_index-1=1 装配（防豁免集回滚面误配）。

## 5. 实测收官

（待 B 轮跑完回填：指标表/工具序列/机制生效实证/验收逐条/墙钟归因/
红队面读数/trace 质量自查/混淆复盘/pytest 读数。）

## 6. 遗留立项

- plan:4 链内兄弟步（子3 锚点核验/子4 归一化）strip/pack/复用钉死
  重审（逐步核对归各自立项；子3 resume 换挂子2 fresh 会话后携带量
  已同向改善一段）；
- plan:4 Node 工具白名单 merge 叠加后的子2 首调复测（归 p4-sub1
  收官面，本设计 §0 已声明归属）；
- 红队触发阈值全局未定义——本设计条款钉「附计数自主声明」与 gate
  同向，阈值语义本身是否应进 purpose（机制级常量）登记为框架议题
  （不改本轮 gate 零变更结论）；
- 输出侧瘦身（观察项，与 p1-sub4/p3-sub3 同处置）。
