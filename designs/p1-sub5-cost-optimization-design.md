# plan:1 子5（归一化陈述）耗时/token 优化设计——Step strip + pack_self_contained + 复用钉死无例外形态 + 校验预告钉死 + 步级断链（新机制首例）

> 日期：2026-08-20 · 分支 feat/p1-sub5-cost · 状态：收官（B1→修1→B2，token 轴全达/耗时轴反升登记）
> 上游：designs/p1-sub1-cost-optimization-design.md（复用钉死+材料前提三件套）；
>      designs/p1-sub2-cost-optimization-design.md（无取证例外形态 #34 + 交互步置位）；
>      designs/p1-sub3-cost-optimization-design.md（载荷组织钉死 + strip 否决判据）；
>      designs/u2-sub3-cost-optimization-design.md（断链判据 #20）。
> 触发 = 用户指令（2026-08-20）：「优化 plan:1 的 step5，耗时和 token 消耗要
> 大幅降低，能用前面步骤沉淀下来的 discovered 和 evidence 就尽量用，避免
> factor 化；跑测试工作流用 ac-deepseek1；amplitude 今日值 4929.2%」。
> 数值口径：种子 problem_statement 保持 4824.5% 不改（runtime-audit #25：
> 数值漂移属 #18 混淆面）；4929.2% = 今日实际值，若运行中被问以此作答。
> 避免 factor 化 = cost-optimization #2：全部杠杆为框架通用机制/通用措辞，
> 零项目语义耦合（条款不点名任何项目构件）。

## 0. 范围声明

本设计只覆盖 **plan:1 子5（归一化陈述，非交互 statements 装配步）**。
子5 在生产中跑在段链内（子3→子4→子5 链，SEGMENT_CHAIN_NODES 含 plan:1）。
子4（评估提案）由并行会话 p1-sub4-cost 在飞优化（其设计 veto 节点级断链、
登记遗留），本设计与其分工：子4 Step/红队面不动，断链走**步级**粒度只摘
子5（与「节点级政策变更超单步范围」的否决理由无冲突——本设计的断链不是
节点级政策变更）。子6（读回确认）P3-1 确认级零成本（cost-optimization #22
关闭清单），不在本设计。

## 1. 基线实测（免跑基线，cost-optimization #30——零新跑）

A = p1_sub3_ab 实例 drive-stream 的 子5 段（session 8b036c76 第三段，
2026-08-20 10:0x，ac-deepseek1/deepseek-v4-flash headless）。#30 三查：
①子5 Step 码两轮间零变更——git log：子5 Step 定义（purpose/gate/mech）自
06026ac（v2.116 framing 反转）后零变更；HEAD 54ece43 与 A 轮码的差量只在
子3 purpose + 子3 mech 报错文案（bec700a/0c87f96，_check_feasibility_
verification_trace 与源步 ID 传导/rejected_rationale_trace 无涉）；A 轮
append-trace 走主树引擎（#31 第三路径）= 同码。✓
②A/B 种子同源——B 种子 = p1_sub3_ab evidence 裁至 ≤plan:1#4（同实例同
子4 trace = 三查②最强形态：子5 输入逐字相同）。✓
③段口径：A = 生产链内段（链续 --resume），B = 断链后 fresh 段——两口径
差含断链收益（L5 杠杆本身的兑现，非混淆），预登记口径分列见 §3。✓

| 指标 | A（p1_sub3_ab 子5 链内段） |
|---|---|
| API 轮数 | 20 |
| 段 fresh 合计 | 167,553（含链冷重写——段内单点 in=143,147 实锤，deepseek 会话隔离缓存） |
| 段 cr 合计 | 3,036,544（逐调 carry ~152k = 链携带税） |
| 段 out 合计 | 30,169 |
| 模型墙钟 | 260s |
| 工具调用 | 41：Bash×23 + Grep×6 + Edit×10 + Skill×1 + Read×1 |
| mech 拒 | ×2（源步条目未逐项传导缺 H1.1 → rejected 只列名单无 ADR） |
| 门控 | judge 一次通过（evidence 单条 sub_step=5 trace，无返工段） |

### 成本归因（工具序列逐条核对，runtime-audit #26 三分诊）

| 类别 | 调用 | 判定 |
|---|---|---|
| 链税（段边界层） | 首调冷重写 ~143k fresh + 逐调 carry ~152k cr | **主税**——deepseek 链恒冷彩票（#9/#20）；子5 材料经交接包完备，链携带的子3/子4 会话上下文与包冗余 |
| 探索/重验（步体层） | ~21 调用：ls/grep 仓内（amplitude/BACKTEST_RESULT/4824/run_layered_backtest）+ python 重读结果 json/parquet/gzip 重实测现状值 + 重数脚本文件数 | **纯税**——子5 职责=子3/子4 已定内容的归一化装配（gate 方框一/三封死包外出口），这些事实是子1/子3 已留痕的重复核验/重导（#29 出处零重查粒度违反） |
| 交付通道 | Skill(define-problem)+scaffold+Read 骨架+Edit+落库+待填自查 grep | 合法理想最小形态（四桶分工） |
| 返工褶皱 | Edit×9 + 提交×2（mech 2 连拒后两轮返工） | 可消灭项——两拒的校验（逐项传导/ADR）purpose 未预告，p1-sub3 修1「报错即返工指令+purpose 预告组织形态」同法可灭 |
| evidence 翻找 | 0 | 本样本未触发；包尾通用「按需 Read」邀请在断链后 fresh 口径是暴露风险（u:4#4 前车）——pack_self_contained 防守性补齐 |

**三层瓶颈分诊（#1/#20/#23）**：①段边界层：链税 = 最大单一成分
（fresh 143k 冷重写 + cr 3.04M carry）；②前缀层：fresh 段口径首调
~35.4k（子3 链头参照）中项目上下文 ~11.9k 未剥=可裁（置位核对见 L3）；
③步体层：探索/重验 21/41 调用 + 返工褶皱 12 调用，条款可灭。

## 2. 方案（五杠杆；机制为主、文案为辅，零 factor 化）

### 杠杆选型核对表

| 杠杆 | 置位/落地 | 前置核对 | 预期 |
|---|---|---|---|
| L1 复用钉死（无取证例外形态，#34 第三例） | ✓ purpose/selfcheck 条款 | gate 方框一（与子3/子4 已定内容不一致判 block）+方框三（凭空新增子4 未评估要素判 block）结构性封死包外材料合法出口——条款与判据同向，#34 适用条件命中 | 探索/重验 21→0 |
| L2 pack_self_contained（非交互步第四例） | ✓ Step 字段 | 输入契约逐字段核对见下；装配不变量测试钉死 | 灭 fresh 口径 evidence 翻找方差 |
| L3 Step 级 segment_strip_project_context | ✓ Step 字段 | 见下（H9 阈值逐字在包=消费步同子4 型） | 首调 -11.9k（三处同口径实证值） |
| L4 载荷校验预告钉死（p1-sub3 修1 同法） | ✓ purpose 条款 | 两校验均为既有 mech（源步 ID 传导/rejected_rationale_trace），报错即返工指令已在，缺的是 purpose 预告 | mech 拒 2→≤1 |
| L5 步级断链（新机制 SEGMENT_CHAIN_SKIP_STEPS，断链第六例首例步级粒度） | ✓ engine 常量 + driver 单行核查 | 材料完备（L2 核对）+ 后续步=子6 交互恒 fresh 零暴露面（#30 扩面核对）+ 子4 留链（并行会话范围，零行为变化） | 灭链税 ~143k fresh + ~152k/调 carry |
| MERGED 续步 | ✗ 否决 | #24 抉择口径：子5 步体小但前序上下文巨大（子3+子4 transcript ~150-250k）→ 携带税主导，断链确定优；暖率彩票 | — |
| pack_full_prior_boundary | ✗ 不置位 | acceptance_map 只需 SC ID（前序 statements.text 全文不截断）；gate 判材边界已封死 SC 真实性判面；置位只涨包（p1-sub2 同判决） | — |
| max_explore_calls | ✗ 不设 | 条款先行，无爆炸信号（p1-sub1/sub2 同判决） | — |
| Node segment_tools | ✗ 不动 | 子4 条件红队需 Agent；子5 探索由 L1 条款管，白名单是节点级共享面 | — |
| gate 文本 | ✗ 零变更 | 三件套核对见 L1 | — |

### L1 复用钉死+职责边界条款进 purpose/selfcheck（文案，#34 无取证例外形态）

purpose 末追加（通用措辞，零项目语义）：

> 材料边界（复用钉死）：归一化材料=交接包（本节点子1-子4 各步最新留痕
> 全文 + 前序节点归一化结论摘要）——逐字直接引用/忠实提取/同义转述即
> 合法形态。本步零新取证：不跑 codegraph/dl codebase/grep/ls 仓内侦察、
> 不 Read 仓内代码/数据文件重定位、不重读结果文件重实测前序已载现状值、
> 不 Read evidence 全量翻找。无取证例外——子1-子4 未载的事实不得进
> fields（gate 凭空新增判据同义），新取证在本步无判据出口。职责边界：
> 存在性/可行性/影响面核验归子3，评估排序归子4，为后续节点拆解预取材料
> =越界（「先查清楚再归一」不是本步职责）。

selfcheck 追加：「八字段内容全部可溯交接包子1-子4 留痕/前序节点摘要吗
（零 codegraph/grep/仓内文件重查/结果文件重实测、零 evidence 翻找、零为
后续步预取）？」

**条款形态核对（#34）**：默认零新查询+「无取证例外」=最强收紧形态——
开放谓词（缺口/必要时）零出现；合法性由 gate 方框一/三结构性保证（包外
材料进 fields=篡改/凭空新增即 block）——条款与判据同向，非文案叠床架屋。

**gate 零变更前置核对三件套（#29 程序）**：
①mech 词表：子5 statements 通用校验（八键非空/方案名词扫描/源步 ID 传导）
+ rejected_rationale_trace——复用引用形态（「复用 子N 留痕：<出处>」进
fields/boundary）不命中任何机械拒：方案名词扫描只扫 text（实现侧名词禁入
text 与复用无关）；ID 传导是覆盖核对（复用促进行为同向）；ADR 校验要求
理由在场（复用子4 否决理由=正合规）。✓
②judge 方框：方框一合法形态已钉「忠实提取/适度压缩/同义转述即合规」+
「codegraph 数字真伪不核（子1/子3 已留痕即合规）」——复用钉死与其同向。
✓
③复用引用形态不命中任何现存 block 条件：方框二（复合句=text 内部判）/
方框四（假设淡化=置信度×影响在场判）/方框五（ADR 已机械下沉）均不涉
出处形态。✓
→ gate 文本零变更，零重放回归负担（v2.116 framing 反转成果不动）。

### L2 pack_self_contained 置位 plan:1 子5（机制，#16 三件套）

置位前置=输入契约逐字段核对（#16）：

| 输入契约项 | 包内位置 | 核对 |
|---|---|---|
| step4.recommendation（子4 推荐/否决结论+矩阵评分） | 交接包「本节点各步最新留痕」节——子4 trace 全文通道（prior=False 保内容全文） | ✓ |
| 子3 三态核验（存在性/影响面 callers/数据契约/硬规则兼容/可测试性） | 同节子3 trace 全文 | ✓ A 轮 trace 实证（H9 阈值/callers 数/双×100 链出处逐字在场） |
| 子2 候选集+用户想法 | 同节子2 trace 全文 | ✓ |
| 子1 现状地图（codegraph 出处/实测现状值） | 同节子1 trace 全文 | ✓ |
| acceptance_map 材料=SC ID 集 | 前序节点「定义成功标准」结论摘要节（statements.text 全文不截断） | ✓ p1-sub2-cost B3 冒烟同口径实证 |
| h9_units 材料=H9 阈值（≤3 文件/≤200 行） | 子4 trace「200 行」+子3 trace「≤3 文件」逐字在场 | ✓ 本设计 §1 双向核对实测 |

生效面：包尾切换+段 prompt 材料边界条款均已由 build_step_prompt 非交互
else 分支覆盖（零 driver 改动）；B 轮 settings hook 路径指 worktree →
hook 侧包尾切换同可见（p1-sub2 修正登记先例）。装配不变量测试钉死
（包须含子1-子4 trace 全文）防未来包修剪把材料修没。

### L3 Step 级 segment_strip_project_context 置位（机制）

置位前置核对（#23 两核对 + u3-sub1 第三核对「env 剥离边界」）：
- **交付物正文不引用自动加载文档**：子5 交付=statements 八键。逐项过：
  change_list/interface_sig/data_contract/callers/rejected/assumptions/
  acceptance_map 内容源全部=子1-子4 trace+前序 statements（包内）；
  h9_units 需 H9 阈值——阈值逐字在包（子4「200 行」+子3「≤3 文件」），
  消费步同 p1-sub4-cost 子4 型（H 条号经前序 trace 逐字在场，非一等材料
  直引规范文档）。与 p1-sub3 否决型（验证步须点名规则做核验）不同型。✓
- **逐步工具需求**：Bash（scaffold/落库）+ Read（骨架）+ Edit（骨架）+
  Skill（define-problem）——全在 Node 白名单既有面，L3 只剥 env 不动
  tools。✓
- **gate 判材**：judge 读 read_evidence_for_step 裁剪的 trace，不读项目
  上下文——剥 env 不影响判侧。✓

### L4 载荷校验预告钉死（文案，p1-sub3 修1 同法）

purpose 载荷格式段末追加：

> 校验预告：源步（子4）留痕条目编号（候选/Cx.x/Hx.x 等）逐项传导进
> fields 对应键——缺传 append-trace 当场拒（可显式标注剔除理由）；
> rejected 字段逐被否项附「为何被否」说明（引子3 核验事实或子4 净分/
> 硬规则触发/影响面/复用度任一项即可）——只列名单当场拒。

### L5 步级断链（机制，新机制 SEGMENT_CHAIN_SKIP_STEPS）

- `dl_flow_engine.py`：`SEGMENT_CHAIN_SKIP_STEPS = frozenset({("plan:1", 5)})`
  ——链白名单的步级豁免集（单源）。判据 #20：deepseek 会话隔离缓存下链
  首调冷（A 段 143k 冷重写实锤），链=携带税纯增；#24：前序上下文巨大
  → 携带税主导，断链确定优。白名单豁免即回滚面（摘条目=恢复链）。
- `dl_drive.py`：`_chain_resume_sid` 首行加 `(node_id, cur) in
  engine.SEGMENT_CHAIN_SKIP_STEPS -> None`。单行核查，既有三不变式不动；
  `_chain_update` 不动（落链记录对子6 交互步无消费面，surgical）。
- 断链前置核对（#20 + #30 扩面）：①交接包材料完备性=L2 逐字段核对 ✓；
  ②链内后续步条款缺口审计——子5 之后=子6 交互步恒 fresh spawn，零暴露
  面 ✓；③block 返工通道——skip 后返工轮=fresh spawn，交接包含当前步
  最新 block 判词（既有机制）✓。

### 不做的事（关闭项登记）

- **子4 链/红队/工具面**：并行会话 p1-sub4-cost 范围，零触碰。
- **pack_full_prior_boundary 不置位**：见杠杆表。
- **max_explore_calls 不设**：条款先行。
- **gate 文本零变更**：见 L1 三件套。
- **judge 成本不动**：判材裁剪（v2.12）已在。
- **子6**：确认级零成本（#22 关闭清单）。

## 3. 预期与验收（预登记，机制读数为主口径 #13/#23）

预期：首调 fresh（fresh 段口径）~30k±5k（子3 链头参照 35.4k - strip
11.9k + 包厚度差）；段 fresh 合计 ≤ 60k（A 167,553，-64%）；段 cr ≤
600k（A 3,036,544，-80%——断链灭 152k/调 carry + 复用钉死灭探索轮）；
工具调用 ≤ 12（理想最小形态 Skill→scaffold→Read 骨架→Edit→落库±待填
自查）；API 轮数 ≤ 10（A 20）；mech 拒 ≤ 1（A 2）；out 不挂硬线（载荷
厚度=质量形态 #30，返工褶皱灭的部分预登记持平或略降）；墙钟按 out÷rate
归因后登记（输出主导，预登记区间 -40%~-60%：轮数减半+零冷重写 TTFT）。

验收口径（A=§1 免跑基线，B=worktree 码同种子族 p1_sub5_ab 起跑）：

1. B 首调 fresh ≤ 35k（机制读数，确定性，不受 #40 步体方差影响）；
   段 fresh ≤ 60k；段 cr ≤ 600k；
2. B 工具序列 ≤12 且零 codegraph/dl codebase/仓内 grep 探索/仓内文件
   重读/结果文件重实测/零 evidence 翻找（合法=Skill/scaffold/Read 骨架/
   Edit/落库/载荷文件待填自查 grep）；
3. mech 拒 ≤1 且 gate judge 零 block；
4. trace 质量逐条自查不降：八键齐备/子4 条目 ID 逐项传导（含 H1.1 类
   规则条号）/rejected 逐项附理由/与子4 推荐结论一致零篡改/假设置信度×
   影响携带/acceptance_map 有内容/零编造；
5. pytest 全绿（新增/更新测试见 §4）+ nodes-index 摘要同步；
6. 混淆声明（预登记）：①A=链内段（含链税），B=断链后 fresh 段——段
   合计差含 L5 兑现，非混淆；链税估算口径=A 段 fresh 143k 单点冷重写
   +逐调 carry 均值 152k；②A/B 同实例同子4 trace（三查②最强形态）；
   ③种子数值 4824.5% vs 今日值 4929.2% 漂移属 #18——子5 无现状测量
   职责且 L1 禁重实测，若运行中被问以 4929.2% 作答；④B 轮 append-trace
   走主树引擎（#31 第三路径）但子5 mech 本体零变更→无差；包尾切换/
   段 prompt 条款=driver+hook 双侧均指 worktree（种子组装同仓化），B 轮
   可见（p1-sub2 修正登记先例）；⑤并行会话 p1-sub4-cost 在飞（子4
   Step/strip 置位）——子4 Step 变更不改子5 输入内容（子4 trace 同源
   种子），两轮间无口径干扰；merge 顺序按 collab 协议协调；⑥A 轮
   drive-stream 中 8b036c76 第四段（97885-155313，8 Bash 全 evidence
   读取/零交付通道/无段 prompt）=并行会话取证活动污染，剔出基线；
   ⑦段级总账受 #40 步体方差影响，主口径=首调 fresh+工具序列形态+mech
   拒次数（#13/#23）。

## 4. 实现清单

- `dl_flow_engine.py`：+= `SEGMENT_CHAIN_SKIP_STEPS` 常量（单源+注释：
  断链第六例首例步级粒度，判据 #20/#24，白名单豁免即回滚面）。
- `scripts/workflow/dl_drive.py`：`_chain_resume_sid` += skip 核查（单行）。
- `dl_flow_nodes.py`：plan:1 子5 Step += `segment_strip_project_context=True`
  + `pack_self_contained=True` + purpose 材料边界条款（L1）+ 校验预告条款
  （L4）+ selfcheck 一条（注释登记置位来源=p1-sub5-cost）。
- `tests/test_dl_flow_engine.py`：skip 集钉死（常量存在+成员）+ 子5 flags
  置位钉死 + 装配不变量（子5 位形包内含子1-子4 trace 全文）。
- `tests/test_dl_drive.py`：`_chain_resume_sid` skip 行为（白名单节点+链
  连续但步在豁免集 → None；非豁免步不受影响）+ 子5 段 prompt 材料边界
  条款钉死（非交互 else 分支，若既有测试未覆盖 plan:1 子5 则补例）。
- `skills/workflow-creation/references/nodes-index.md`：plan:1 条目子5
  摘要同步（purpose 实质内容变更）。
- 不改：gate 文本、Node segment_tools、SEGMENT_CHAIN_NODES（plan:1 保留，
  子3→子4 链不动）、MERGED_RUN_NODES、engine mech 本体。

## 5. 实测收官（2026-08-20，A=p1_sub3_ab 子5 链内段免跑基线 / B=p1_sub5_ab 两轮，ac-deepseek1 headless）

B 轮驱动法：种子=p1_sub3_ab 完成态裁至 ≤plan:1#4（evidence 26 条+state
四字段同步 sub_step_index=5+last_judged 裁至 #4+**segment_chain 留
last_step=4 生产形态**[skip 机制 live 验证位——stale sid 若被错误续链会
当场响]+段记录清零+settings 名替换+hook 路径指 worktree+产物文件第七件）
→ 包冒烟 41,020 字符（尾行切换生效+子1-4 留痕全文在包）→ `bash -ic` 内
AC_WORKFLOW_LAUNCHER=worktree launcher `ac-deepseek1 --dl p1_sub5_ab
--resume --headless`。B1（首三杠杆）→ 修1（交付即止钉死）→ B2。

| 指标 | A（链内段） | B1 | B2（修1 后） | Δ(A→B2) |
|---|---|---|---|---|
| 首调 fresh | 链内口径（冷重写 143k 单点实锤） | 31,443 | 31,581 | 双样本 ±0.4% 机制钉死（子3 链头参照 35.4k→-11%≈strip 探针值） |
| 段 fresh 合计 | 167,553 | 105,948 | 97,529 | **-41.8%** |
| 段 cr 合计 | 3,036,544 | 783,872 | 1,033,344 | **-66.0%** |
| 段 out 合计 | 30,169 | 58,507 | 56,648 | +87.8%（质量形态，见归因） |
| 成本等效（fresh+0.1cr） | 471,207 | 184,335 | 200,863 | **-57.4%** |
| API 轮数 | 20 | 13 | 16 | -20% |
| 工具调用 | 41（探索/重验 21+褶皱 12） | 11（零探索） | 14（零探索零徘徊） | 形态理想最小化 |
| mech 拒 | 2（传导+ADR） | 1（ADR） | 1（ADR） | 传导拒两轮零复发（L4 兑现） |
| 模型墙钟 | 260s | 422s | 417s | **+60% 反升（见归因）** |
| 门控 | judge 一次通过 | 零 block | 零 block | ✓ |

**验收逐条**：①首调 ≤35k **✓**（双样本）；段 fresh ≤60k **✗**（97.5k，
-41.8%）；段 cr ≤600k **✗**（-66%~-74%）——预登记目标未计 out 近翻倍对
逐调上下文的回馈（产出逐轮进上下文推高后续调 fresh/cr），按 #30 登记为
**预登记口径失误非杠杆失效**：机制面读数（首调双样本钉死/工具形态/零徘徊）
全中；②工具序列 **✓**（零 codegraph/grep 仓内探索/仓文件重读/结果文件
重实测/evidence 翻找；B2 零徘徊；超 12 调部分=Edit 返工褶皱）；③mech 拒
≤1 **✓** + gate judge 零 block **✓**（两轮）；④trace 质量逐条 **✓**：
B2 九项 statements 八键零缺/H1.1 类条号逐项传导/rejected 逐候选附理由
（Pugh 净分+逐格引子3/子4）/与子4 推荐一致零篡改/假设置信度×影响携带/
零编造（载荷 22.6k 字符 vs A 14.2k=逐字引用厚度）；⑤pytest 1173 全绿
（新增 8 例）+ nodes-index 同步 **✓**；⑥混淆声明全部按预登记处理——③
数值漂移未触发（L1 禁重实测，运行中未被问今值）；⑥B1 轮 p1_sub3_ab
drive-stream 第四段（8 Bash 全 evidence 读取/零交付通道）=并行会话取证
污染，剔出基线对照面。

**墙钟归因（#30 双轴口径）**：out÷rate 拟合成立（B2 136 tok/s vs A 116
tok/s 同端点同档）→ 墙钟差=输出量差。输出两成分：thinking 28.4k vs A
13.9k（+104%，条款驱动逐事实 deliberation，#33 同型）+载荷厚度 +59%
（逐字引用=L1 复用钉死的直接兑现=质量形态）；褶皱成分=Edit 返工轮
（B2 ×9，ADR 名单形态 5-8 Edit 才收敛）。**耗时轴未达预登记（+60% 反升）
=token 优化的墙钟反噬第三实例（#30 标题条款）**；取舍登记：逐字引用厚度
是防编造的条款兑现，撤厚度=回到编造风险——不撤；耗时轴的补救面在 Edit
收敛（遗留立项），不在引用形态。

**修1 实录（B1→B2）**：B1 落库成功后模型预习下一节点子1（「locate
design.md/understand.md」=plan:2#1 ref 逐字形态）徘徊 6 调用 ~340k cr
纯税——根因=落库消息「可输出 STEP_DONE 并 end_turn」与段 prompt「禁输出
STEP_DONE」两通道打架，弱模型以继续干活收场；修1=purpose「交付即止」
钉死，B2 零徘徊（工具序列止于落库，rc=0 自动推进）。沉淀 cost-optimization
#37。

**沉淀**（skills 同步）：①cost-optimization #37=交付即止钉死（落库后预习
徘徊=交付后越界新形态；系统两通道文案打架时弱模型以继续干活收场）；
②§20 补=步级断链粒度（SEGMENT_CHAIN_SKIP_STEPS 首例——链白名单节点级
→步级豁免，节点内单步断链不动兄弟步，与并行单步优化分工兼容）；③#33 补
第三实例（引用厚度+thinking 反噬墙钟，本设计 B 轮双样本）。

**遗留立项**：①plan:2/3/4 族 strip/pack/复用钉死逐步核对（同法）；②子5
Edit 返工收敛——ADR 多候选组织形态（每候选一段「候选X——被否：理由」）
进 scaffold 占位符括注候选（#31 骨架表达力同法，预估灭 4-6 Edit/轮）；
③plan 族整节点断链重审（子4 留链=并行会话 veto 登记，本子5 步级豁免已
摘最大链税单步）；④子5 耗时轴=输出主导结构（质量形态），如需墙钟再降
只能动引用厚度条款——留用户裁决，不自行撤。

