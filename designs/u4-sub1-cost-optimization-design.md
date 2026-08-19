# understand:4 子1（成功标准引出）耗时/token 优化设计——Node 级 tools 白名单 + 逐步 env 剥离 + 材料边界 + 复用钉死

> 日期：2026-08-19 · 分支 feat/u4-sub1-cost · 状态：收官（一轮 A/B 全验收达标）
> 上游：designs/u3-sub4-cost-optimization-design.md（Step 级 strip 第二例 +
>      pack_self_contained 第三例 + 格式真源钉死）；
>      designs/u3-sub3-cost-optimization-design.md（#25 复用条款收紧形态）；
>      designs/u2-residual-cost-optimization-design.md（#23 段前缀外科剥离）；
>      designs/u2-sub2-cost-optimization-design.md（#16 材料边界三件套）。
> 触发 = 用户指令（2026-08-19）：「优化 understand:4 的 step1，耗时和 token
> 消耗要大幅降低，能用前面步骤沉淀下来的 discovered 和 evidence 就尽量用，
> 避免 factor 化；跑测试工作流用 ac-deepseek1；amplitude 今日值 4947.7%」。
> 数值口径：种子 problem_statement 保持 4824.5% 不改（runtime-audit #25：
> 数值漂移属 #18 混淆面非一致性 bug）；4947.7% = 今日实际值，若运行中
> 被问/需核对「今值」类断言时以此作答。
> 避免 factor 化 = cost-optimization #2（框架通用 vs 项目专属边界）：本设计
> 全部杠杆为框架通用机制/通用措辞，零项目语义耦合。

## 1. 基线实测（现成数据，零新跑）

u3_sub4_ab（2026-08-19 12:16-12:17，ac-deepseek1/deepseek-v4-flash headless，
当前 HEAD 2bd7546 同码——u:3#4 优化只动 u:3，u:4#1 段面零变更）该实例
种子就位在 u:4#1（u:1-u:3 全程真实 trace 齐备），今晨 u:4#1 TUI 段
（session ede25e98，无 TTY print 降级）逐调用配平：

| 指标 | 值 |
|---|---|
| 首调 fresh | 45,217（cr=0，冷启动） |
| 段 fresh 合计 | 51,995 |
| 段 cr 合计 | 260,608 |
| 段 out 合计 | 9,023 |
| 模型墙钟 | 66s |
| API 调用 | 6 |
| 工具调用 | 26（TaskCreate×18 / TaskUpdate×6 / Agent×2 / Read×1 / TaskStop×1） |
| 子代理账 | a89957da：4 调 / in 14,106 / cr 34,688 / out 2,765；a9de9f0c：1 调 / in 37 / cr 7,168 / out 0（被 TaskStop） |

**prep 段已零成本**（不立项，#22 口径）：NEXT_PREP 跨节点机制（u2-sub1-cost
修A）把 u:4#1 问题清单折进 u:3#4 工作段顺带交付——need_user.json
（ts 12:16:12，含 sources 出处包）落盘与 TUI 段 spawn（12:16:13）之间无
prep 会话 transcript，实证零独立段。

### 成本归因（工具序列逐条核对，runtime-audit #26 三分诊）

| 类别 | 调用 | 判定 |
|---|---|---|
| 子代理步骤越界取证 | Agent Explore×2（+TaskStop×1） | 模型自白「供验收方式设计使用」=为**子3** 预取 file:line 手段证据（双×100 放大链 data_loaders.py:166-168 等）——①越界：子1 交付物=标准候选+出处，file:line 手段取证归子3；②重复取证：这些锚点前序步已沉淀（need_user sources 引「子2/C1 实证」，u:1#6/u:3#4 boundary 带 file:line）。#16：「只做 X」边界文案管不住弱模型，机制堵入口=tools 白名单去 Agent |
| 项目上下文+工具 schema 前缀 | （首调内） | u:4 是 understand 族唯一未置位 segment_strip/segment_tools 的节点——项目上下文 ~11.9k + 全量工具 schema ~14.3k = 首调纯税 ~26.2k（探针实证值，u2-residual/u3-sub1 同口径） |
| evidence 全量重读邀请 | 包尾「按需 Read evidence」 | u:4#1 声明输入 = GoalsAndValue.step4.statements + ScopeAndConstraints.step4.statements——生产包冒烟（8,476 chars）实证两者 statements text 全文在包内（prior 瘦身只截 q 80 字符/boundary 100 字符，不截 text），通用邀请对本步是反指（#16 第三例同型） |
| TaskList 仪式 | TaskCreate×18 + TaskUpdate×6 | 真实 TTY 下用户可见（v3.3.1 内容同源设计内）；print 降级环境是纯税但 A/B 两臂同有，不影响差值——**登记不动**（跨步机制，非本步专项） |

## 2. 方案（四杠杆，全部机制现成/措辞通用，零新机制、零 factor 化）

### L1 Node 级 segment_tools 置位——去 Agent 堵步骤越界（机制）

understand:4 Node 置 `segment_tools=("Bash", "Read", "Edit", "Skill")`
（u:2 同款四件；TUI 段自动 +AskUserQuestion/TaskCreate/TaskUpdate 三件套，
u3-sub1-cost 已接线）。**Agent 不在单** = 子1（及全节点）段内结构性无法
派发子代理——基线观察到的「为子3 预取证据」越界从文案约束升级为机制堵
入口（#16 判别准则：Y=「先查清楚再动手」是弱模型自然冲动，文案必失效）。

逐步工具需求核对（置位前置，u2-residual §3 同程序）：

| 步 | ref | 工具需求 | 核对 |
|---|---|---|---|
| #1 成功标准引出（交互） | 推理 / AskUserQuestion | Read(need_user.json) + Bash(append-trace/scaffold) + Edit(骨架) + TUI 三件套 | ✓ |
| #2 可检验化 | 推理 / Bash(基线测量) | Bash + Read + Edit | ✓ fence_allow=Bash 同向 |
| #3 验收方式设计 | 推理 / Bash / codegraph / Read | Bash(codegraph 经 Bash) + Read + Edit | ✓ 同 |
| #4 归一化陈述 | Skill(define-problem) | Skill + Bash + Edit | ✓ u:2#4 同型先例 |
| #5 读回确认 | confirm 级无会话 | — | ✓ P3-1 机械通过 |

全节点无一步合法需要 Agent（pre_dispatch 红队 = u:1#5 独有）。prep 段
（stash 失效时的兜底路径）spawn 同走 segment_spawn_overrides，Read/Bash
够用（need_user 载荷经 `### NEED_USER`  stdout 契约交付，无需 Write）。

### L2 Step 级 segment_strip_project_context 置位 u:4#1（机制，第四例）

置位前置核对（#23 两核对 + u3-sub1 第三核对「env 剥离边界」）：
- **交付物正文不引用自动加载文档**：子1 交付 = must 目标的验收视角提问 +
  标准候选 + 出处（用户原话/会话事实）。must 目标/约束内容经交接包逐字在
  场（u:2#4/u:3#4 statements 全文），非「Read 指针」而是已装配正文；
  gate 判材边界段明示「must 目标集与范围约束跨节点结构性不在载荷内，trace
  自述自洽即合规」——判侧同样不要求规范原文在场。与 u:3#1 的反优化结论
  （约束分类须点名规则条号=一等材料）**不同型**：成功标准引出无点名规则
  条号职责。
- **逐步工具需求**：见 L1 表 #1 行。
- MergedSession 不适用（u:4 不在 MERGED_RUN_NODES；段链只连连续非交互步，
  交互步 #1 恒 fresh spawn，chain 名单不动）。

生效 = node OR step 字段（机制 u3-sub3 已落地，本设计只置位）——Node 级
刻意不置位：#2/#3 是验证/测量步，env 剥离前置核对未做（surgical，留后续
立项）。

### L3 pack_self_contained 置位 u:4#1（机制，第四例）

输入契约逐字段核对（置位前置，生产实例真包冒烟已过）：

| 输入契约项 | 包内位置 | 核对 |
|---|---|---|
| GoalsAndValue.step4.statements（must 目标集） | 前序节点「明确目标和价值」结论摘要节（statements text 全文） | ✓ 真包 8,476 chars 实证在场 |
| ScopeAndConstraints.step4.statements（范围约束集） | 前序节点「确定范围与约束」结论摘要节（同上） | ✓ 同上 |
| 用户问题陈述原话 | 包首「用户问题陈述」节 | ✓ |
| 补问材料（用户侧期望缺口） | prep 载荷 need_user.json（questions + sources 出处包）——段 prompt 指针 Read | ✓ u2-sub1-cost 修B 通道 |
| 用户裁决传导 | need_user sources 已逐字收录（prep 契约第 2 条）+ 前序读回步 trace（确认级，内容价值低） | ✓ |

boundary 截断（100 字符）影响评估：被截的是 file:line 实现指针——子1
不需要（那是子3 材料），不影响本步交付。**配套风险登记**：boundary 截断
后若未来某步需要前序 file:line 全文，应走 evidence 指针定点补（条款允许
「确有缺口按指针定点补」），不是全量翻找。

置位后两消费点均已泛化、交互分支确认覆盖：①包尾换「材料已在包内」
（engine.handoff_pack，TUI 段经 SessionStart hook 注入同包）；②段 prompt
铁律「材料边界」条款在 build_step_prompt 非-prep else 分支——交互步同
路径（补测试钉死，防未来重构把交互步切走）。

### L4 复用钉死——purpose/selfcheck 条款（文案，机制的双侧对偶）

purpose 末追加（通用措辞，零项目语义）：

> 材料边界（复用钉死）：must 目标集/范围约束/用户原话全部在交接包
> （前序节点结论摘要节）与 prep 载荷 sources 字段——逐字直接引用即出处；
> 本步零新取证：不派发子代理、不跑 codegraph/grep、不 Read evidence
> 全量翻找（验收手段的 file:line 取证归子3——为后续步预取材料 = 越界，
> 「先查清楚再补问」不是本步职责）。

selfcheck 追加一条：「材料全部引自交接包/prep 载荷 sources 吗（零新取证、
零子代理、零 evidence 全量翻找）？」

条款形态 = #25 收紧形态（默认零新查询 + 枚举例外），非「缺口才新跑」
开放谓词。机制侧 L1（Agent 不在白名单）堵最大的口子，文案侧防 Bash 迂回
（grep/codegraph 经 Bash 可跑——文案点名禁）= 双侧钉死。

### 不做的事（关闭项登记）

- **u:4 段链（#2→#3→#4）不动**：段链只连连续非交互步，#1 是交互步恒
  fresh spawn，断链/续步对本步零影响；#2-4 的链税重审是独立立项（需
  自身逐字段核对 + A/B）。
- **TaskList 仪式税不动**：真实 TTY 用户可见（v3.3.1 设计内）；headless
  print 降级下的税 A/B 两臂同有，不进差值。
- **gate 判据零变更**：本设计不动 u:4#1 gate 文本（framing 已反转达标，
  v2.93），无需重放回归。
- **u:4#2-4 的 strip 不置位**：逐步核对未做，surgical。

## 3. 预期与验收（预登记，机制读数为主口径 #13/#23）

预期（探针预算，机制确定性部分）：首调 fresh 45,217 → ~19k
（-11.9k env 剥离 - 14.3k tools schema ≈ -26.2k，-58%）；Agent 消除
（-21.3k in / -41.9k cr / 子代理墙钟）；段墙钟 66s → ~35-45s。

验收口径（A = 今晨基线，B = worktree 码驱动同实例续跑）：

1. B 首调 fresh ≤ 20k（机制读数，确定性，不受 #40 步体方差影响）；
2. B 工具序列零 Agent、零 evidence/仓库文件全量 Read（合法 Read =
   need_user.json + scaffold 骨架）；段 fresh 合计降 ≥50%；
3. 零 block；无 TTY print 降级下步未完成 = 环境性（u2-sub1 §6 附记同口径），
   若模型走「会话事实出处 + 未获答标推测」路径完成落 trace 且 gate 放行
   = 额外质量证据（trace 出处须引交接包/sources，非新取证）；
4. pytest 全绿（新增测试见 §4）+ nodes-index 摘要同步；
5. 混淆声明：种子数值 4824.5% 与今日实际 4947.7% 的漂移属 #18，子1 是
   引出步不触发新取证，不受影响；若运行中被问今值，以 4947.7% 作答。

## 4. 实现清单

- `dl_flow_nodes.py`：understand:4 Node += `segment_tools`；u:4#1 Step
  += `segment_strip_project_context=True` / `pack_self_contained=True` /
  purpose 材料边界条款 / selfcheck 一条。
- `tests/test_dl_flow_engine.py`：TestSegmentSpawnOverrides += u:4 tools
  钉死 + u:4#1 Step 级 strip 钉死 + test_other_nodes_zero_change 更新
  （u:4 tools 进白名单内节点集）；TestPackSelfContained += u:4 flags 钉死
  + u:4#1 包尾行替换 + 材料完备性装配不变量（GAV/SC step4 statements
  全文在包）。
- `tests/test_dl_drive.py`：interactive=True + pack_self_contained 步的段
  prompt 带材料边界条款（首个交互步置位，钉交互分支覆盖）。
- `skills/workflow-creation/references/nodes-index.md`：u:4 条目子1 摘要
  同步（purpose 实质内容变更）。
- 不改：engine 机制代码（全现成）、dl_drive.py（条款分支已覆盖交互）、
  gate 文本、SEGMENT_CHAIN_NODES。

## 5. 实测收官（2026-08-19，u3_sub4_ab 同实例续跑，ac-deepseek1 headless）

B 轮驱动法：恢复今晨已消费的 next_prep_stashed 标记（need_user.json 在位、
输入未变 = 复原今晨进入位形，P2-1 短路线同构）→ `bash -ic` 内
AC_WORKFLOW_LAUNCHER 指 worktree launcher 跑 `ac-deepseek1 --dl u3_sub4_ab
--resume --headless`。driver 日志特征行核验代码路径：「⚑ 问题清单前序段
已备（P2-1 合并段）——转前台问答」= stash 短路生效、零独立 prep 段。

| 指标 | A 基线（今晨 12:16） | B（13:41） | Δ |
|---|---|---|---|
| 首调 fresh | 45,217 | 17,416 | **-61.5%**（探针预算 -26.2k → 19.0k，实测 17.4k 一致量级） |
| 段 fresh 合计 | 51,995 | 19,329 | -62.8% |
| 段 cr 合计 | 260,608 | 43,136 | -83.4% |
| 段 out 合计 | 9,023 | 4,751 | -47.3% |
| 成本等效（fresh+0.1cr） | 78.1k | 23.6k | **-69.8%** |
| API 调用 | 6 | 3 | -50% |
| 段墙钟 | 66s | 29.7s | **-55%** |
| 子代理 | 2（in 21.3k / cr 41.9k） | 0（无子代理目录） | -100% |

验收逐条：①首调 fresh ≤20k ✓（17,416）；②工具序列零 Agent、唯一 Read
= need_user.json（prep 载荷指针，合法通道）、零 evidence/仓库文件读 ✓；
③两臂同为无 TTY print 降级、步均未完成（环境性，不计成败——u2-sub1 §6
附记同口径），零 block ✓；④pytest 1133 全绿（新增 6 例）+ nodes-index
同步 ✓；⑤数值漂移未触发（引出步无新取证）✓。

遗留观察（登记不动）：TaskList 仪式 24 调用两臂同有（真实 TTY 用户可见，
v3.3.1 设计内）；pack 尾行切换对 TUI 段要待 merge 后由主树 hook 生效
（B 轮 prompt 侧条款已生效——driver 是 worktree 码，hook 引用主树引擎，
u:4#1 的 pack_self_contained 在 merge 前主树不可见）。
