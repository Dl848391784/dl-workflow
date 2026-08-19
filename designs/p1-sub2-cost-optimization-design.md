# plan:1 子2（方案发散）耗时/token 优化设计——Step strip（第八例）+ pack_self_contained（交互步第二例）+ 复用钉死/职责边界条款

> 日期：2026-08-20 · 分支 feat/p1-sub2-cost · 状态：收官（一轮 A/B 全验收达标）
> 上游：designs/p1-sub1-cost-optimization-design.md（plan:1 子1 三杠杆范式+
>      Node 白名单已落地）；designs/u4-sub1-cost-optimization-design.md（交互步
>      置位 strip/pack_self_contained 首例 + 交互步 A/B 驱动法）；
>      designs/u2-sub2-cost-optimization-design.md（#16 三件套 + #19 四步核对法）。
> 触发 = 用户指令（2026-08-20）：「优化 plan:1 的 step2，耗时和 token 消耗要
> 大幅降低，能用前面步骤沉淀下来的 discovered 和 evidence 就尽量用，避免
> factor 化；跑测试工作流用 ac-deepseek1；amplitude 今日值 4947.7%」。
> 数值口径：种子 problem_statement 保持 4824.5% 不改（runtime-audit #25：
> 数值漂移属 #18 混淆面）；4947.7% = 今日实际值，若运行中被问以此作答。
> 避免 factor 化 = cost-optimization #2：全部杠杆为框架通用机制/通用措辞，
> 零项目语义耦合（条款不点名任何项目构件）。

## 0. 范围声明

本设计只覆盖 **plan:1 子2（方案发散，交互步/decision 级）**。子2 是交互步
恒 fresh spawn（段链只连连续非交互步），无链税；prep 段已零成本（NEXT_PREP
折进子1 工作段，u2-sub1-cost 修A 机制，基线实证 need_user.json 落盘与 TUI
段 spawn 之间无独立 prep transcript）。plan:1 子3-6 不在本设计。

## 1. 基线实测（免跑基线，cost-optimization #30——零新跑）

A = p1_sub1_ab2 的 子2 TUI 段（session 3e52a283，2026-08-19 22:56，
ac-deepseek1/deepseek-v4-flash headless 无 TTY print 降级）。#30 三查：
①子2 Step 码两轮间零变更——A 轮码=B1（22a3bc9 三杠杆）vs 现 main 832d6a8，
plan:1 差量=子1 Step 字段+修1/修2/修3，子2 Step 定义逐字未动，Node
segment_tools 白名单 B1 已含；②A/B 种子前序 trace 不同 run（ab2 子1 trace
vs B 种子 ab4 子1 trace）——属步体方差面，首调前缀读数不受影响（见下三样本）；
③段口径：TUI 段 print 降级形态写进混淆声明（§3）。
首调 corroboration：ab3（B2 码）28,654 / ab4（B3 码）28,625 / ab2 28,605
——三样本 ±0.2%，首调前缀对包 boundary 截断差异（B1 vs B2+）不敏感=机制
读数钉死。ab2 是唯一步完成的样本（gate 一次通过，先进子3），段级合计取它。

| 指标 | A（p1_sub1_ab2 子2 段） |
|---|---|
| 首调 fresh | 28,605（cr=0——交互步 fresh spawn 符合预期） |
| 段 fresh 合计 | 55,777 |
| 段 cr 合计 | 360,576 |
| 段 out 合计 | 23,666 |
| API 调用 | 9 |
| 模型墙钟 | ~165s（14:53:25→14:56:10） |
| 工具调用 | 45：TaskCreate×19+TaskUpdate×19（TaskList 仪式）+Read×3+Bash×3+AskUserQuestion×1+Edit×1 |
| 门控 | 一次通过（子2 gate pass → 先进子3） |

### 成本归因（工具序列逐条核对，runtime-audit #26 三分诊）

| 类别 | 调用 | 判定 |
|---|---|---|
| 首调前缀：项目上下文未剥 | （首调内 ~11.9k） | **主税**——plan:1 仅子1 置位 strip，子2-6 未核对未置位；首调 28.6k 中项目上下文 ~11.9k（u2-residual 探针实证值三处同口径）=纯税 |
| TaskList 仪式 | TaskCreate×19+TaskUpdate×19 | 设计内（v3.3.1 内容同源，真实 TTY 用户可见）；print 降级下是纯税但两臂同有——**登记不动**（u4-sub1 同处置） |
| Read 自己 transcript 恢复交接包 | Read×1 | print 降级工件——attachment 注入不可见的自救通道（包内容经此进上下文）；两臂同有，登记不动 |
| AskUserQuestion 结构不可用→fallback | AskUserQuestion×1 | 环境性（headless TUI 段 `No such tool available`）→ need_user sources 逐字平权入列 + 决策点留档读回步（trace ⑤ 自白，gate 认可）；两臂同有 |
| dl-cmd status | Bash×1 | 轻微冗余——段 prompt 已含当前位置；1 调用，不加机制（surgical） |
| 交付通道 | scaffold+Read 骨架+Edit+落库 | 合法理想最小形态（四桶分工） |
| **探索/重取证** | **0** | **零 codegraph/grep/仓文件重读/零 evidence 翻找**——复用 de facto 成立（本样本）；候选锚点（daily gz/:713 公式/callers/模板 5 处/constants.py:152）全部引自交接包（子1 trace 全文通道）+need_user sources |

**三层瓶颈分诊（#1/#20/#23）**：①段边界层：交互步恒 fresh spawn，无链税；
②前缀层（唯一大头可裁量）：项目上下文 ~11.9k 未剥（tui-rules 已瘦 5.4k
字符、Node 白名单已裁工具 schema——p1-sub1-cost 已落地，剩余可裁量=env）；
③步体层：本样本已最小，风险=弱模型「先查清楚再发散」冲动的方差（u3-sub1/
u4-sub1 基线均实证该冲动）——文案钉死防守，不加机制（基线零爆炸信号）。

## 2. 方案（三杠杆；机制为主、文案为辅，零 factor 化）

### L1 Step 级 segment_strip_project_context 置位 plan:1 子2（机制，第八例）

置位前置核对（#23 两核对 + u3-sub1 第三核对「env 剥离边界」）：
- **交付物正文不引用自动加载文档**：子2 交付=≥3 候选+维度差异声明+用户想法
  平权入列。gate 方框零规则引据要求（硬规则兼容=子3 五项核验④的职责）；
  ab2 trace 的「H1.1 允许」=自愿引用非义务。配套 L2 职责边界条款（本步零
  规则核验义务、缺引不违规）防剥后重读规范文档（u3-sub1 反超教训的对策）。
  与子1 的差异：子1 交付含 codegraph 新鲜度判定等实测事实，子2 是纯推理
  变换步——env 内容（路由表/规则条号）非本步一等材料。
- **逐步工具需求**：Bash（scaffold/落库）+ Read（骨架/need_user.json）+
  Edit（骨架）+ TUI 三件套——全在 Node 白名单（p1-sub1-cost L2 已含）+
  _TUI_STEP_TOOLS 既有接线内，L1 只剥 env 不动 tools。
- **gate 判材**：judge 读 read_evidence_for_step 裁剪的 trace，不读项目
  上下文——剥 env 不影响判侧。
- 链内续跑段外部性：子2 交互步恒 fresh spawn；子3/4 链内段不置位（逐步
  核对未做），零行为变化；MergedSession 不适用（plan:1 不在
  MERGED_RUN_NODES）。

### L2 复用钉死+职责边界条款进 purpose/selfcheck（文案，#25/#29 收紧形态）

purpose 末追加（通用措辞，零项目语义）：

> 材料边界（复用钉死）：候选锚定材料=交接包（本节点子1 现状地图全文+
> 前序各节点结论摘要）与 prep 载荷 sources——逐字直接引用即合法出处；
> 本步零新取证：不跑 codegraph/dl codebase/grep、不 Read 仓内代码文件
> 重定位、不重验前序已载出处、不 Read evidence 全量翻找。无取证例外——
> 子1 未列出的事实不得进候选（gate 凭空设计判据同义），新取证在本步无
> 判据出口。职责边界：存在性/重复实现/影响面/硬规则兼容核验归子3（本步
> 候选不逐条引规则条号，缺引不违规）；评估排序归子4；为后续步预取材料
> =越界（「先查清楚再发散」不是本步职责）。

selfcheck 追加：「候选锚定材料全部引自交接包/prep 载荷 sources 吗（零
codegraph/grep/仓文件重查、零 evidence 翻找、零为后续步预取）？」

**条款形态核对（#25）**：默认零新查询+「无取证例外」=最强收紧形态——开放
谓词（缺口/必要时）零出现；「无例外」的合法性由 gate 方框二结构性保证
（候选引用面=子1 trace 已列事实，包外材料进候选即违规）——条款与判据同向，
不是文案叠床架屋。

**gate 零变更前置核对三件套（#29 程序）**：
①mech 词表：子2 无 mech_checks——无机械层核对面。✓
②judge 方框：方框二「凭空设计」只认子1 trace 已列事实——复用钉死与其同向
（引子1 trace=锚定合规），【关键】段已钉「不得以用户既有想法未列一等候选/
未展示 AskUserQuestion 实际问询内容 block」（print 降级 fallback 路径受保护）。
✓
③复用引用形态（「锚定子1 事实：<出处>」逐字引用）不命中任何现存 block
条件：方框一（伪候选=维度差异判）/方框三（提前收敛=评估措辞判）/方框四
（②无逐维度论证）均不涉出处形态。✓
→ gate 文本零变更，零重放回归负担（v2.104 framing 反转成果不动）。

### L3 pack_self_contained 置位 plan:1 子2（机制，#16 三件套，交互步第二例）

置位前置=输入契约逐字段核对（#16）+ #19 四步核对法（ab2 真迹）：

| 输入契约项 | 包内位置 | 核对 |
|---|---|---|
| step1.terrain_map（子1 现状地图） | 交接包「本节点各步最新留痕」节——子1 trace 全文通道 | ✓ ab2 transcript 实证（pack 附件含子1 q/a 全文） |
| 用户问题陈述原话 | 包首「用户问题陈述」节 | ✓ |
| understand 目标/约束（设计空间定界材料） | 前序节点结论摘要节（statements text 全文不截断） | ✓ B3 包冒烟 17,147 字符实证在场 |
| 用户既有想法（平权入列材料） | prep 载荷 need_user.json sources——段 prompt 指针 Read=合法通道（u2-sub1-cost 修B） | ✓ |

#19 四步核对（ab2 真迹）：①引用跨度——trace 引文（file:line/实测值/留痕
ID）逐字可溯子1 trace/前序 statements（5/5 形态）；②事实项双向——锚点
全在包内材料，零包外取证（段会话零 codegraph/零仓文件 Read 实证）；
③利用率——子1 现状地图高利用（4 候选全锚其条目）；④新综合占比——高
（4 候选=新设计提案），但**gate 凭空设计判据使包外材料结构性不可用**
（候选引用面=子1 trace 已列事实），新综合是纯推理变换不是新事实产出——
与搬运型步同效，置位安全。#19「新综合占比高→不置位」的判别意图=新事实
产出需包外取证，本步不命中该意图。

生效面（#28 拆分）：prompt 材料边界条款=driver 侧（build_step_prompt 非-prep
else 分支，交互步同路径，u4-sub1 已补测试钉死）——B 轮可见；包尾「材料已在
包内」切换=SessionStart hook 侧（主树引擎）——**merge 后生效面**，B 轮不可见，
登记。

### 不做的事（关闭项登记）

- **pack_full_prior_boundary 不置位子2**：ab2（B1 码=boundary 截断包）零
  evidence 翻找实证截断未伤本步——锚点经子1 trace 全文通道流转，不经前序
  statements boundary；置位只涨包，surgical。
- **Node tools 不动**：子4 fence_allow=Agent 需保留；子2 基线零 Agent 派发、
  零探索，无 #27 越界信号，不降 Step 级（无此机制，surgical）。
- **max_explore_calls 不设**：基线零探索，无爆炸信号（p1-sub1 同判决）。
- **TaskList 仪式 / print 降级工件 / AskUserQuestion 环境性失败**：两臂同有
  或设计内（v3.3.1），登记不动。
- **MERGED/段链不动**：交互步恒 fresh spawn，无关。
- **gate 文本零变更**：见 L2 三件套。
- **judge 成本不动**：判材裁剪（v2.12）已在。

## 3. 预期与验收（预登记，机制读数为主口径 #13/#23）

预期（探针预算，机制确定性部分）：首调 fresh 28.6k → ~16.7k（strip -11.9k，
u2-residual/u3-sub1/p1-sub1 三处同口径实证值，-41.6%）；段 cr ≈ -25%
（每调上下文 -11.9k × 后续 ~8 调）；段 fresh ≈ -21%（首调 -11.9k，工具
输出增量不变）；out 基本持平（载荷厚度=质量形态，#30）；墙钟按 out÷rate
归因后登记（输出主导，strip 对墙钟仅经 TTFT 间接小幅——不预登记硬线）。

验收口径（A=§1 免跑基线，B=worktree 码同种子族 p1_sub2_ab 起跑）：

1. B 首调 fresh ≤ 18k（机制读数，确定性，不受 #40 步体方差影响）；
2. B 工具序列：零 codegraph/dl codebase/grep 探索、零仓内代码文件重读、
   零 evidence 全量翻找（合法 Read=need_user.json+scaffold 骨架+print
   降级下自己 transcript 恢复包）；段 cr 降 ≥20%；
3. 零 block；若 B 轮步完成（print 降级 fallback 路径，ab2 已有先例），
   trace 质量逐条自查不降：≥3 候选（或②逐维度论证）/维度差异声明/锚定
   子1 事实逐条可溯包内材料/零评估排序措辞/用户想法平权入列/零编造；
4. pytest 全绿（新增/更新测试见 §4）+ nodes-index 摘要同步；
5. 混淆声明（预登记）：①A 码=B1 vs B=main+本轮——子2 Step 两轮间零变更
   （B1→main 差量只在子1/修1-3，Node 白名单 B1 已含），包差异=boundary
   截断 vs 全文对首调影响 ±0.2% 三样本实证可忽略；②A 种子子1 trace=ab2
   版 vs B 种子=ab4(B3) 版——前序材料内容差异属 #40 步体方差面，首调机制
   读数不受影响；③种子数值 4824.5% vs 今日值 4947.7% 漂移属 #18——子2
   无现状测量职责，若运行中被问以 4947.7% 作答；④段级总账受 #40 步体
   方差影响，主口径=首调 fresh+工具序列形态（#13/#23）；⑤B 轮包尾切换
   hook 侧主树不可见（#28），验收只看 prompt 侧条款+spawn env 覆盖；
   ⑥AskUserQuestion 环境性失败两臂同有，不计成败（u4-sub1 §3③同口径）。

## 4. 实现清单

- `dl_flow_nodes.py`：plan:1 子2 Step += `segment_strip_project_context=True`
  + `pack_self_contained=True` + purpose 材料边界条款 + selfcheck 一条
  （注释登记 strip 第八例 + pack_self_contained 交互步第二例）。
- `tests/test_dl_flow_engine.py`：TestSegmentSpawnOverrides += plan:1 子2
  strip 置位钉死；TestPackSelfContained += 子2 flags 钉死 + 装配不变量
  （子2 包内本节点子1 trace 全文在场）。
- `tests/test_dl_drive.py`：子2（交互+pack_self_contained）段 prompt 材料
  边界条款钉死（若 u4-sub1 的交互分支测试未覆盖 plan:1 则补例）。
- `skills/workflow-creation/references/nodes-index.md`：plan:1 条目子2 摘要
  同步（purpose 实质内容变更）。
- 不改：engine 机制代码（全现成）、dl_drive.py（条款分支已覆盖交互步）、
  gate 文本、Node segment_tools、SEGMENT_CHAIN_NODES、MERGED_RUN_NODES。

## 5. 实测收官（2026-08-20，A=p1_sub1_ab2 子2 段免跑基线 / B=p1_sub2_ab，ac-deepseek1 headless）

B 轮驱动法：种子=p1_sub1_ab4 完成态（evidence 23 条 ≤plan:1#1 + state
plan:1 sub_step_index=2 + 段记录/链清零 + **next_prep_stashed="plan:1#2"
复原进入位形**[u4-sub1 法]+ settings 名替换+hook 路径指 worktree + 产物
文件第七件）→ 包冒烟 18,609 字符（尾行切换生效+子1 留痕全文在包）→
`bash -ic` 内 AC_WORKFLOW_LAUNCHER=worktree launcher `ac-deepseek1 --dl
p1_sub2_ab --resume --headless`。**交互步答案注入（本轮新方法，见沉淀）**：
B 段模型走 print 提问+end_turn（needuser 出口，环境性路径形态之一），用
`claude --resume <段 sid> -p <答案>` 复刻段 spawn 旗标（settings/tui-rules/
tools 白名单/NO_MCP/strip env）注入用户答案（Q1=C Q2=A Q3=B，对齐种子已录
用户裁决），模型同会话续跑完成交付；driver 再 --resume 跑 gate=judge。

| 指标 | A（p1_sub1_ab2 子2 段） | B（p1_sub2_ab） | Δ |
|---|---|---|---|
| 首调 fresh | 28,605（ab3 28,654/ab4 28,625 三样本 ±0.2%） | 16,061 | **-43.9%**（探针预算 ~16.7k，实测 ±4% 内） |
| 段 fresh 合计 | 55,777 | 41,062 | **-26.4%** |
| 段 cr 合计 | 360,576 | 278,528 | **-22.8%** |
| 段 out 合计 | 23,666 | 23,065 | -2.5%（持平=载荷厚度质量形态，#30 预登记兑现） |
| 成本等效（fresh+0.1cr） | 91,835 | 68,915 | **-25.0%** |
| API 调用 | 9 | 9 | = |
| 模型墙钟 | ~165s | ~163s（21s+142s 两段，扣人工答题间隔） | 持平（out÷rate 输出主导，预登记兑现） |
| 非仪式工具序列 | Read×3+Bash×3+AskUserQuestion×1+Edit×1 | Read×3+Bash×2+Grep×1（待填检查）+Edit×1 | 冗余 status 调用消除 |
| 探索/翻找 | 0 | 0 | =（条款防守性成立） |
| 门控 | 一次通过 | **一次通过（零 block）** | ✓ |

**验收逐条**：①首调 ≤18k **✓**（16,061，-43.9%——strip 机制读数，首轮
driver spawn 段读数不受注入轮影响）；②工具序列零 codegraph/dl codebase/
grep 探索、零仓文件重读、零 evidence 翻找 **✓**（非仪式 7 调用全交付通道+
合法材料读；唯一 Grep=载荷骨架「待填」占位符提交前自查=交付卫生非探索）；
段 cr -22.8% ≥20% **✓**；③零 block **✓**（gate pass 进子3）；trace 质量
逐条自查：6 候选（≥3）✓/维度差异声明在场 ✓/锚定子1 事实逐条可溯包内材料
✓/零评估排序措辞（「推荐/首选」命中均为「未出现推荐性措辞」「不预设首选」
否定声明=gate 明列合法形态）✓/用户想法平权入列（Q1=C/Q2=A/Q3=B 逐字收录
为候选1）✓/零编造 ✓；④pytest 1163 全绿（新增 7 例）+ nodes-index 同步
✓；⑤混淆声明全部按预登记处理——③数值漂移未触发（子2 无测量职责，运行
中未被问今值）；⑤**修正登记**：B 轮 per-wf settings hook 路径指 worktree
（种子组装 sed+ensure_tui_settings 同仓化）→ SessionStart hook 用 worktree
引擎→**包尾切换在 B 轮实际可见**（hook additionalContext 文件实证「本步
所需材料已全部在包内」在场）——#28「merge 后生效面」的适用条件=hook 路径
指主树时，本轮不命中（沉淀进 runtime-audit #25）；新增混淆⑥'：答案注入
轮（resume 续跑）与 driver 重问段（~2 调用，「沿用」提示后 rc=0 秒退）=
人工驱动工件，生产 front 模式无此两面，段合计口径含注入轮但首调机制读数
不受影响。

**墙钟归因（#30 双轴口径）**：out 基本持平（-2.5%）→ 墙钟持平（163s vs
165s）=out÷rate 拟合（输出主导）——strip/复用杠杆作用在 token/成本轴，
墙钟轴预登记即声明不挂硬线（交互步墙钟地板=用户答题时间，生产 TTY 下
模型侧 163s 中非仪式生成占大头=载荷厚度质量形态，登记不动）。

**沉淀**（skills 同步）：①cost-optimization #34=「无取证例外」最强收紧
形态的适用条件（gate 判据结构性封死引用面时条款可与判据同向写死，本轮
首证）；②runtime-audit #25 补=交互步 A/B 答案注入法（`claude --resume
<段 sid> -p <答案>` 复刻段 spawn 旗标含 strip env）+ hook 路径树决定
hook 侧生效面（#28 精确化）。

**遗留立项**：plan:1 子3-6 strip/pack 逐步核对（子3 可行性验证=验证步参
照 u:4#2/#3 形态；子4 有 Agent 红队）；TaskList 仪式/print 降级工件两臂
同有登记不动；amplitude 今日值 4947.7% 本轮未触发（方案发散无现状测量
职责）。
