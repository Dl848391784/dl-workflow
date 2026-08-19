# understand:4 子4（归一化陈述）耗时/token 优化设计——Step strip + pack_self_contained + 格式真源钉死

> 日期：2026-08-19 · 分支 feat/u4-sub4-cost · 状态：设计中
> 上游：designs/u4-sub3-cost-optimization-design.md（§6 B2 定案——断链暴露
>      u:4#4 双缺口=格式猎捕 #26 + evidence 元探查 #16，处置=立项三件套，
>      本设计即该立项）；designs/u3-sub4-cost-optimization-design.md
>      （同配方先例：22→5 调用/cr -86%）；cost-optimization #16/#23/#26/#30。
> 触发 = 用户指令（2026-08-19）：「优化 understand:4 的 step4，耗时和 token
> 消耗要大幅降低，能用前面步骤沉淀下来的 discovered 和 evidence 就尽量用，
> 避免 factor 化；跑测试工作流用 ac-deepseek1；amplitude 今日值 4947.7%」。
> 数值口径：种子 problem_statement 保持 4824.5% 不改（runtime-audit #25：
> 数值漂移属 #18 混淆面）；4947.7% = 今日实际值，若运行中被问以此作答
> （子4 非交互步，预期不触发，同 u4-sub3 登记口径）。
> 避免 factor 化 = cost-optimization #2：全部杠杆为框架通用机制/通用措辞，
> 零项目语义耦合（条款不点名 pytest/report/因子等任何项目构件）。

## 1. 基线实测（免跑基线双样本——u4_sub3_ab B1/B2 的 step4 段即同种子同码基线）

**基线来源声明**（cost-optimization #30 免跑基线，前提三查全过）：
①step4 代码两轮间零变更——u4-sub3-cost 只动 step3（purpose/strip）与
CHAIN 白名单，step4 Step 定义自 u4-sub2 前零变更（git log 核）；②种子
evidence 内前序 trace（SC#1/SC#2/SC#3）与 B1/B2 跑出的是同一条链
（B2 步3 trace 即 B2 步4 输入）；③段口径：B1/B2 的 step4 均为断链后
fresh 段（u:4 已出 CHAIN），与当前 main（0e43b04）生产形态一致——
本设计的 B 轮同形态，无链/断链混淆。

| 指标 | A1（u4_sub3_ab B1 step4） | A2（u4_sub3_ab B2 step4） |
|---|---|---|
| 段墙钟（dur_api） | 187s | 253s |
| 轮数 | 10 | 24 |
| 首调 fresh | 30,443（cr=0） | 30,525（cr=0） |
| 段 out | 25,114 | 34,055 |
| 成本 | $1.110 | $1.798 |
| 工具序列 | evidence 元探查 + 格式迭代 | grep ~/.dl-workflow/designs 反推载荷格式 5+ 调用 + evidence 全量读 |
| 门控 | 通过（含 1 次 append 重试褶皱） | 通过 |
| 对照：链内形态（断链前 A/B 轮） | 11 轮/62.8s/out 7,537 | 11 轮/60.2s/out 7,609 |

### 成本归因（双样本结构性，非方差——u4-sub3 设计 §6 已定案）

断链暴露 u:4#4 的两个既有条款缺口（链内时由前步会话携带格式/材料上下文
掩盖，断链后 fresh 段模型零格式上下文）：
①**格式猎捕**（#26）——A2 工具序列 ls/grep `~/.dl-workflow/designs` 反推
【text】/【statements】载荷格式 5+ 调用（跨仓 roam，比 evidence 元探查更贵）；
u:3#4 已有「格式真源=scaffold 骨架+报错文案」钉死条款，u:4#4 没有。
②**evidence 元探查**（#16）——grep evidence '"statements"' / python3 读
evidence 全量：包尾「按需 Read」通用邀请诱发（pack_self_contained 未置位），
而本步输入（SC#3 trace 全文）本就在交接包「本节点各步最新留痕」节。
③**前缀层**（#23）——首调 30.4-30.5k 未剥 env（项目上下文 ~11.9k，
三处同口径实证值）；对照同节点已 strip 的 step3 fresh 段首调 15.3k。
out 3.3-4.5×（25-34k vs 链内 7.5-7.6k）= 格式迭代返工褶皱 + 元探查转录，
墙钟随输出量同步膨胀（out÷rate 输出主导，#30）。

**u:4#5 不立项**：确认级读回（P3-1）机械装配 0 token，#22 关闭清单在册。

## 2. 方案（三件套：strip + pack_self_contained + 格式真源钉死；零新机制、零 factor 化）

### L1 Step 级 segment_strip_project_context 置位 u:4#4（机制，Step 级第六例/u:4 内第四例）

置位前置核对（#23 两核对 + u3-sub1 第三核对「env 剥离边界」）：
- **交付物正文不引用自动加载文档**：子4 交付 = statements 归一化陈述
  （text/type_label/boundary + 验收包六字段）——text 只许 outcome-level
  （purpose 已钉，机械扫描在 append-trace 脚本侧），无点名项目硬规则条号
  职责（与 u:3#1「约束分类须点名规则条号=一等材料」反优化**不同型**；
  与 u:3#4 同型——_SOLUTION_FREE_SUBJECT_RULE 规则内容经 purpose 常量
  逐字在场，CLAUDE.md/auto-memory 对本步是死重）。
- **逐步工具需求**：Bash（scaffold/append-trace 落库）+ Read（骨架）+
  Edit（骨架）——全在 Node 白名单（u4-sub1-cost L1 已置位 tools-only）内。
- **gate 判材**：judge 读 read_evidence_for_step 裁剪的子3+子4 trace 拼合，
  不读项目上下文——剥 env 不影响判侧（gate 判材边界段已明示）。

### L2 pack_self_contained 置位 u:4#4（机制，#16 第五例）

置位前置 = #19 四步核对法（对 A1/A2 真实 trace 做）：
- **输入契约 ⊆ 包内内容**：声明输入 = step3.criteria_with_acceptance——
  SC#3 trace 全文在交接包「本节点各步最新留痕」节（latest_trace 通道，
  同 u:4#1 冒烟实证通道）；SC#3 trace 自身携带验收包六字段（指标/基线/
  阈值提案/方法/时机/证据形式 = 子2 三要素 + 子3 三件的传导链全文），
  子4 的逐项核对基准齐备。装配不变量测试钉死（包须含 SC#3 trace 全文
  标记）——防未来 P1-1 类包修剪把材料修没了条款变错。
- **搬运型步判别**：子4 = 归一化装配步（purpose 已钉「禁二次创作」同构
  u:3#4——创造性工作已在子1-3 完成，本步 = 形式装配 + 逐项核对），
  新综合占比低、包外取证非职责面（无 Bash 取证职责——ref 无 Bash，
  fence_allow 未开）= pack_self_contained 合格候选。
- **基线反指实证**：A1/A2 的 evidence 元探查（grep/python3 读全量）产出
  零信息增量（ trace 内容核对），是包尾通用「按需 Read」邀请诱发——
  置位后包尾切换「材料已在包内」+ 段 prompt 材料边界条款（build_step_prompt
  非-prep else 分支覆盖，非交互步同路径零 driver 改动）。

### L3 格式真源钉死条款进 purpose/selfcheck（文案，#26 平移第二例）

purpose 末追加（u:3#4 条款平移，删「编号传导」——本步无条目编号传导
机械核对，statements JSON 校验已在）：

> 载荷格式的唯一真源 = --scaffold 骨架 + append-trace 报错文案（四桶分工：
> 格式归脚本）——禁读引擎/测试源码反推校验实现；被拒按报错文案逐字修即可。

selfcheck 追加：「格式照 scaffold 骨架填了吗——没去翻引擎/测试源码反推
校验实现吧（被拒按报错文案修）？」

**条款形态核对**：#26 原条款为通用措辞（不点名任何项目构件），平移零
factor 化风险；钉死测试防静默丢失（同 u4_step2/3_reuse_clause_pinned 形态）。

**判侧零变更核对（gate 文本不动三查）**：①mech 面——record_format=
"statements" 的逐项 JSON 校验已注册，条款不新增/不改任何机械校验；
②judge 方框——条款只约束模型侧行为通道（格式从哪学），不改判材、不新增
block 条件；③格式钉死不命中任何现存 block 条件（四方框皆判内容传导/
复合/方案残留，与格式学习通道无关）。故不动 gate 文本 = 零重放回归负担。

### 不做的事（关闭项登记）

- **gate 文本零变更**：见 L3 三查。
- **u:4#5 不动**：确认级零成本（#22 关闭清单）。
- **续步（MERGED_RUN_NODES）不立项**：u:4 段链 324k 破护栏前科 +
  deepseek 暖率彩票（#9/#24），fresh 段 + 三件套是确定收益面。
- **墙钟输出侧瘦身（trace 措辞密度）不动**：u4-sub3 登记的观察项，非本轮
  三件套作用面；本轮灭的是格式迭代褶皱（out 25-34k → 预期回落 8-12k
  区间），措辞密度留后续。
- **plan 族链不动**：无降本指令，surgical。

## 3. 预期与验收（预登记，机制读数为主口径 #13/#23/#30）

预期：首调 fresh 30.4-30.5k → ~18.5k（strip -11.9k env 剥离，三处同口径
实证值；pack 置位对首调近零影响=包尾一行切换）；工具序列 → 理想最小形态
（scaffold→Read 骨架→Edit→落库，≤6 调用，u:3#4 实测 22→5 同配方）；
段 out 25-34k → 8-12k（灭格式迭代褶皱+元探查转录）；段 fresh/cr/墙钟随
轮数与首调双降（u:3#4 同配方实测 cr -86%/墙钟 -46%）。

验收口径（A = §1 双样本 A1/A2，B = worktree 码同种子 u4_sub4_ab 起跑，
ac-deepseek1 headless）：

1. B 首调 fresh ≤ 19k（机制读数，确定性——strip 是唯一首调变量，探针
   预算 30.4k - 11.9k ≈ 18.5k）；
2. B 工具序列：零 ~/.dl-workflow 源码/designs 翻找（格式猎捕清零）、
   零 evidence 全量翻找（元探查清零）、总调用 ≤8（骨架五件 + 重试余量）；
3. 段 fresh 降 ≥35%、段 out 降 ≥50%、墙钟降 ≥40%（单轮同口径参考，
   主口径是 1/2 两条机制读数；out÷rate 输出主导下墙钟随 out）；
4. 零 block；trace 质量不降——按 gate 四节自查 B 轮 trace：验收包六字段
   逐项传导 / verdict 边界传导 / 原子单句 / solution-free；statements
   逐项与子3 标准集对齐，零编造；
5. pytest 全绿（新增/更新测试见 §4）+ nodes-index 摘要同步；
6. 混淆声明（预登记）：①A1/A2 与 B 同种子同段形态（fresh 段），step4
   代码差 = 本设计三件套，无链形态混淆；②种子数值 4824.5% 与今日值
   4947.7% 的漂移属 #18，同种子同漂移面；子4 无现状测量职责，预期
   不触发；③总账单轮受步体方差（#40）影响，验收以首调 fresh + 工具
   序列形态为主口径（#13/#23）；④A1/A2 轮数 10/24 双样本离群差本身
   即格式猎捕方差（条款缺口的行为随机性），B 轮收敛到 ≤8 即条款生效
   证据，不按单轮轮数差验收。

## 4. 实现清单

- `dl_flow_nodes.py`：u:4#4 Step += `segment_strip_project_context=True`
  （注释登记第六例）+ `pack_self_contained=True`（第五例）+ purpose 末
  格式真源钉死条款 + selfcheck 一条。
- `tests/test_dl_flow_engine.py`：
  - `test_u4_pack_self_contained_flags` 更新（#4 翻转为置位：
    [True, False, False, True, False]）；
  - `test_u4_other_steps_no_step_strip` 更新（#4 翻转，仅 #5 不置位）；
  - 新增 `test_u4_step4_step_level_strip`（env 双开关 + tools 白名单钉死）；
  - 新增 `test_u4_step4_format_clause_pinned`（purpose/selfcheck 格式真源
    条款关键词钉死防静默丢失）；
  - 新增 `test_u4_step4_materials_complete_invariant`（装配不变量：包须含
    本节点 SC#3 trace 全文——#19 置位前置的机械化）。
- `skills/workflow-creation/references/nodes-index.md`：u:4 条目子4 摘要
  同步（purpose 实质内容变更）。
- 不改：driver 机制代码（三件套全是声明式字段/条款，零新机制）、gate
  文本（§2 L3 三查）、MERGED_RUN_NODES、plan 族链、judge。

## 5. 实测收官（2026-08-19，u4_sub4_ab 同种子起跑双轮，ac-deepseek1 headless，worktree 码 471d916/3c85da1）

驱动法（runtime-audit #24/#25）：种子六件套（evidence 裁 20 条 ≤SC#3[B2 轮
SC#3 trace=基线 A2 输入同一条] + state 四字段同步 understand/1/4/understand:4
+ sub_step_index=4 + last_judged_trace 裁 ≤u:4#3 + 段记录/链/stash 清零 +
settings 三件套 grep 验 name-agnostic=0 + pack 冒烟 17,985 字符 SC#3 全文
[4,188 字符 a 字段片段]在包+包尾已切「材料已在包内」）→ `bash -ic` 内
`AC_WORKFLOW_LAUNCHER=<worktree>/scripts/workflow/dl-launch.sh ac-deepseek1
--dl u4_sub4_ab --resume --headless`；step5 确认级过门控进 plan:1 即停 driver
（免烧计量外 token）。B1 后发现残余税→修A→B2（修A 生效面见下）。

| 指标 | A1（u4_sub3_ab B1 step4） | A2（u4_sub3_ab B2 step4） | B1 | B2 | B 双样本 vs A 均值 |
|---|---|---|---|---|---|
| 首调 fresh | 30,443 | 30,525 | 17,780 | 17,820 | **-41.6%**（双样本 ±0.2% 钉死） |
| 段 fresh 合计 | n/a（流已重置） | 71,643 | 46,909 | 44,046 | vs A2：-34.5% / **-38.5%** |
| 段 cr 合计 | n/a | 1,139,200 | 250,752 | 214,656 | vs A2：**-78.0% / -81.2%** |
| 段 out | 25,114 | 34,789 | 20,248 | 24,006 | 均值 -26.2% |
| 轮数 | 10 | 24 | 12 | 11 | 均值 17→11.5（-32%） |
| 段 dur_api | 187s | 248s | 163.9s | 177.6s | 均值 217.5→170.8（-21.5%） |
| 成本 | $1.110 | $1.798 | $0.866 | $0.928 | 均值 **-38.3%** |
| 成本等效（fresh+cr×0.1） | n/a | 185,563 | 71,984 | 65,512 | vs A2：**-61.2% / -64.7%** |
| 门控 | 通过 | 通过 | 零 block | 零 block（1 次 mech 拒收会话内自修正） | ✓ |

代码路径核验：B1/B2 首调 17.8k 双样本稳定（strip -11.9k 探针预算精确命中
30.5k→18.6k 附近，残差=包长/prompt 长差）+ 段 prompt 内条款关键词命中 =
三杠杆确由 worktree 码生效（driver 侧：prompt 条款/spawn 覆盖/交接包包尾）。

验收逐条：①首调 ≤19k **双样本达标**（17,780/17,820，机制读数确定性）；
②**跨仓源码/designs 格式猎捕双轮清零**（#26 条款目标行为达成——A2 的
grep designs 反推 5+ 调用形态绝迹）；evidence 元探查 B1 残留 5 调用
（格式动机，见修A）、B2 仅 1 次 ls ≈ 清零；总调用 B1 10/B2 9 边际超
预登记 ≤8（含 Skill；骨架五件+褶皱循环）；③段 fresh B2 -38.5% 达标/
B1 边际；**段 out 均值 -26% 未达预登记 ≥50%、墙钟均值 -21.5% 未达 ≥40%**
——归因（#30 out÷rate 输出主导再实证）：out 残量大头是**载荷厚度=质量
形态**（4 条陈述逐字引用验收包六字段+传导 C7.2 修正后更厚），预登记
≥50% 的前提是格式迭代褶皱占 out 大头，实测褶皱成分比预估小（B1 零拒收、
B2 一次**合法** mech 拒收[C7.2 传导缺失=牙齿逮真漏]=会话内修正非浪费）；
墙钟随 out（同端点速率稳定），token 轴优化的墙钟兑现受输出侧厚度限制
——与 u4-sub3 §5 登记的「墙钟输出侧瘦身」观察项同归因，维持观察项不撤
质量条款；④零 block 双轮 ✓，trace 质量四节自查全过（原子单句/六字段
传导[text+type_label+boundary 承载]/verdict 边界[目标承接+条件启用]/
solution-free 零实现侧名词；C7.2 待建手段传导=边界传导完整性反升）；
⑤pytest 1144 全绿（新增 5 例：step4 strip/格式条款钉死/包尾切换/装配
不变量/scaffold 多条提示钉死）+ nodes-index 同步 ✓；⑥混淆声明按预登记
处理 ✓；amplitude 今日值 4947.7% 双轮未触发（子4 非交互无现状测量职责，
同预登记）。

**修A（scaffold statements 骨架多条形态提示，commit 3c85da1）——merge 后
生效面登记**：B1 残余 5 调用根因=模型要确认「多条 statement 怎么写」去
evidence 找实际样例（自白「这是格式核对，非 evidence 翻找」）——单条骨架
未示多条形态=**骨架表达力缺口**（#26 条款管得住「不反推校验实现」，管不住
「骨架本身没回答的问题」）。修法=多条形态写进 scaffold 待填占位符括注
（「多条陈述 = 逐项重复本【statements】整段，一条一块」，替换即消失，与既
有括注同形态，零解析器变更，parse-back 测试钉死）。**生效面核验发现**：
段内模型 Bash 调 `python3 ~/.dl-workflow/dl_flow_engine.py append-trace`
= **主树引擎**（命令模板硬编码路径），worktree 码的 scaffold 改动在 A/B
里静默无效——B2 骨架 Read 回显确为旧版（无多条提示）。此面属 #28 验收面
拆分的第三路径（driver=worktree / SessionStart hook=主树 / **模型 Bash 调
引擎 CLI=主树**），归 merge 后生效面；改动纯骨架文本+零 gate 影响+
parse-back 双测试兜底，合并风险可忽略。预期效果：B1 型格式核对 5 调用
灭绝（B2 该动机未发作=单轮方差，不作证据）。

**遗留登记**：墙钟输出侧瘦身（trace 措辞密度）维持观察项（两轮同归因）；
plan 族链重审（无降本指令，保留）；u:2 MERGED 重审（前登记，未动）。
