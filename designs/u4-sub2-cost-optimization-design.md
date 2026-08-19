# understand:4 子2（可检验化）耗时/token 优化设计——Step 级 strip + 复用钉死（前序实测值/出处零重查）

> 日期：2026-08-19 · 分支 feat/u4-sub2-cost · 状态：设计中
> 上游：designs/u4-sub1-cost-optimization-design.md（u:4 Node tools 白名单 +
>      子1 strip/pack_self_contained/复用钉死）；
>      designs/u3-sub3-cost-optimization-design.md（#25 复用条款收紧形态）；
>      designs/u2-residual-cost-optimization-design.md（#23 段前缀外科剥离）；
>      designs/u2-sub2-cost-optimization-design.md（#16 材料边界三件套、
>      #19 搬运型判别）。
> 触发 = 用户指令（2026-08-19）：「优化 understand:4 的 step2，耗时和 token
> 消耗要大幅降低，能用前面步骤沉淀下来的 discovered 和 evidence 就尽量用，
> 避免 factor 化；跑测试工作流用 ac-deepseek1；amplitude 今日值 4947.7%」。
> 数值口径：种子 problem_statement 保持 4824.5% 不改（runtime-audit #25：
> 数值漂移属 #18 混淆面非一致性 bug）；4947.7% = 今日实际值，若运行中
> 被问/需核对「今值」类断言时以此作答。
> 避免 factor 化 = cost-optimization #2（框架通用 vs 项目专属边界）：本设计
> 全部杠杆为框架通用机制/通用措辞，零项目语义耦合。

## 1. 基线实测（种子实例 u4_sub2_ab，ac-deepseek1/deepseek-v4-flash headless，主树 HEAD e514ba9）

种子构造（runtime-audit #25 五件套）：evidence = u3_sub4_ab 17 条真实 trace
（u:1-u:3 全程，2026-08-19 当前码跑出，格式已实证兼容）+ u1_overall_ab 的
SuccessCriteria#1 真实 trace（2026-08-17 同问题实跑）；state 定位 u:4#2、
last_judged_trace 裁至 ≤u:4#1（hash 由 latest_trace_sha1 实算回填）、
segment_sessions/链/stash 清零、settings 三件套 grep 验 name-agnostic=0、
handoff_pack 起跑前冒烟通过（10,609 字符：问题陈述+SC#1 全文+前序三节点
摘要节齐备）。

A 轮（2026-08-19 14:40-14:42，主树码）u:4#2 段（链头 fresh spawn，
session aa77079e）：

| 指标 | 值 |
|---|---|
| 段墙钟 | 136s（模型 120s + gate judge 41s） |
| 轮数（result 事件权威值） | 20 |
| 段 input（fresh） | 39,311（modelUsage 46,246） |
| 段 cache_read | 365,312 |
| 段 output | 16,545 |
| 首调 fresh | 25,944（cr=0，冷启动） |
| 成本 | $0.844 |
| 工具序列 | Bash×17 / Read×1 / Edit×1 |
| 门控 | 一次通过，零 block |

### 成本归因（工具序列逐条核对，runtime-audit #26 三分诊）

12 个探索 Bash（06:40:55-06:41:44，~50s）逐条分类：

| 类别 | 调用 | 判定 |
|---|---|---|
| 现状基线实测 | venv python 读 layered_backtest.json 取值 0.4947724 + ×100 演算 | **合法本步职责**（基线=实测现状；实测值与种子 SC#1 所载 0.4951977 有真实漂移=#18，实测是对的） |
| 重复核验 SC#1 已载出处 | grep 模板 ×100 点位（_section_backtest.html/_macros.html）、sed formatters.py:100-130、sed data_loaders.py:160-175、find report html | **纯税**——SC#1 trace 全文在交接包（「双乘机制=formatters.py:125 ×100 + 模板 :69/:57 ×100」带 file:line），消费步重新验证前序已证实事实（#26 相邻步重复取证同族） |
| 子3 领域勘察（步骤越界） | ls/grep/sed web_ui/test_cases/test_app.py×3、grep pytest 配置 | **纯税**——验收手段存在性勘察是子3 职责（#27 预取越界的 Bash 变体：Agent 已出白名单，冲动从 Bash 迂回） |
| evidence 翻找 | 零 | 本步包尾「按需 Read」邀请未被利用（正面）——但逐条对照显示模型选择了「重新实测」而非「读前序留痕」 |

首调 25.9k 构成：harness（tools 白名单已裁，昨日 L1）+ **项目上下文 ~11.9k
未剥**（u:4#2 是节点内唯一未置位 strip 的工作步——#1 昨日已置位）+
node-rules + 交接包 10.6k + step prompt。

链税观察（登记，非本设计作用面）：#3 首调 fresh 60,439 / #4 82,588（驱动
日志 ⚠ 超阈值告警）——deepseek 会话隔离缓存下段链恒冷（#20），u:4 链
（#2→#3→#4）断链/续步重审是独立立项（需自身逐字段核对+A/B），本设计不动。

## 2. 方案（两杠杆，全部机制现成/措辞通用，零新机制、零 factor 化）

### L1 Step 级 segment_strip_project_context 置位 u:4#2（机制，第四例/u:4 内第二例）

置位前置核对（#23 两核对 + u3-sub1 第三核对「env 剥离边界」）：
- **交付物正文不引用自动加载文档**：子2 交付 = fit criterion 三要素（度量
  指标/基线值/阈值提案）+ 模糊词改写留痕——材料 = 交接包内 SC#1 候选全文
  + Bash 实测值，无点名项目硬规则条号职责（与 u:3#1「约束分类须点名规则
  条号=一等材料」反优化**不同型**；与 u:4#1 同型——候选/目标经交接包逐字
  在场）。
- **逐步工具需求**：Bash（基线测量/scaffold/落库）+ Read（骨架）+ Edit
  （骨架）——全在 Node 白名单（昨日 L1 已置位）内，零新增需求。
- **gate 判材**：judge 读 read_evidence_for_step 裁剪的 trace，不读项目
  上下文——剥 env 不影响判侧。
- MergedSession 不适用（u:4 不在 MERGED_RUN_NODES；#2 是链头恒 fresh
  spawn，链/续步名单不动）。

### L2 复用钉死条款进 purpose/selfcheck（文案，#25 收紧形态：默认零重查+枚举例外）

purpose 末追加（通用措辞，零项目语义）：

> 材料边界（复用钉死）：子1 候选清单及其所载出处（实测值/file:line/机制
> 结论）全部在交接包「本节点各步最新留痕」节全文——逐字直接引用即合法
> 出处，零重复核验（候选已附的 file:line/机制结论不重查、不重读验证；
> 前序节点摘要节同理）。基线 = 现状实测值：候选出处未含现状值时才 Bash
> 单点测量（每条候选最多一次，测目标值即止，禁顺手勘察）；验收手段的
> 存在性勘察（测试框架/验证脚本/工具链是否在位）归子3——本步零勘察。
> 引用前序实测的形态「复用 <节点>子N 实测：<值>（出处逐字）」= 合法工具
> 留痕。

selfcheck 追加一条：「候选清单与出处逐字引自交接包吗（零重复核验）？
基线测量每条候选 ≤1 次单点取值吗？验收手段存在性勘察留给子3了吗
（本步零勘察）？」

**判侧已对齐、gate 文本零变更**（三重核对）：
①机械层 baseline_tool_trace 词表含「实测」——「复用 …子N 实测：<值>」
形态当场过机械墙（零 engine 改动）；②judge 方框一开篇已钉「基线数字留痕
已由 append-trace 机械校验——你不得以『基线留痕缺失/无工具出处』为由
block」，复用引用形态不属于任何 block 条件（「留痕在场但数字与声明来源
明显矛盾」不适用于逐字引用）；③方框一 block 例「声明 Bash实测却给不出
吻合数字」针对编造，逐字引用前序实测值无此形态。故不动 gate 文本 =
零重放回归负担（v2.95 framing 反转成果不动）。

**条款形态核对（#25）**：默认零重查 + 枚举例外（「候选出处未含现状值」=
逐条可判定的二值条件，非「缺口/必要时」开放谓词）；「每条候选最多一次」
= 配额形态（#14 上限≠配额教训——按条配而不是总上限）。

### 不做的事（关闭项登记）

- **pack_self_contained 不置位**（#19 判别）：本步产出新事实（现状基线值
  经 Bash 实测），非搬运型步；且前序节点实测留痕不在包内（包只载归一化
  statements+本节点 trace），置位 =「材料已全部在包内」条款撒谎。包尾
  通用「按需 Read」邀请与 L2 条款的关系：L2 点名合法补料形态（候选/出处
  在包内逐字引用），evidence 翻找对本步无合法需求面——A 轮实证零翻找。
- **u:4 段链（#2→#3→#4）不动**：#2 是链头恒 fresh spawn，断链/续步的
  受益面是 #3/#4（链税 60k/83k 首调告警已登记）——独立立项，surgical。
- **gate 文本零变更**：见 L2 三重核对；v2.95 反转成果不动，无需重放回归。
- **#3/#4 的 strip 不置位**：逐步核对未做（#3 是验证型步，env 剥离边界
  核对未做），留后续立项。
- **judge 成本不动**：41s judge 在段外，判材裁剪（v2.12）已在。

## 3. 预期与验收（预登记，机制读数为主口径 #13/#23）

预期（探针预算，机制确定性部分）：首调 fresh 25,944 → ~14k（-11.9k env
剥离，u2-residual/u3-sub1/u4-sub1 三处同口径实证值）；探索 Bash 12 → ≤4
（现状实测 1-2 + 落库 scaffold 序列），轮数 20 → ~10-12；段墙钟 136s →
~75-95s；段 fresh/cr 随轮数与首调双降。

验收口径（A = 本设计 §1 基线，B = worktree 码同种子续跑）：

1. B 首调 fresh ≤ 15k（机制读数，确定性，不受 #40 步体方差影响）；
2. B 工具序列：探索 Bash ≤ 4（现状基线单点测量合法）；零 formatters/
   模板/data_loaders 重核验（SC#1 已载出处）；零测试框架/脚本存在性勘察
   （子3 职责）；Read 仅 scaffold 骨架；
3. 段 fresh 合计降 ≥40%、cr 降 ≥40%、墙钟降 ≥30%（单轮同口径参考，
   主口径是 1/2 两条机制读数）；
4. 零 block；trace 质量不降（三要素齐备/模糊词扫描留痕/阈值提案形态——
   按 gate 方框逐条自查 B 轮 trace）；
5. pytest 全绿（新增测试见 §4）+ nodes-index 摘要同步；
6. 混淆声明（预登记）：①种子 SC#1 来自 u1_overall_ab（2026-08-17 真实
   跑）与 u3_sub4_ab 的 u:1-u:3（2026-08-19）有代际差——judge 判材边界
   明示跨节点组成非判对象，影响仅限内容一致性观感；②种子数值 0.4951977
   与今日实测 0.4947724 的漂移属 #18——基线实测类步的合法工作，两轮
   同种子同漂移面；③总账单轮受步体方差（#40）影响，验收以首调 fresh +
   工具序列形态为主口径（#13/#23）；④A 轮链税（#3/#4 首调 60k/83k）两臂
   同有，不进差值。

## 4. 实现清单

- `dl_flow_nodes.py`：u:4#2 Step += `segment_strip_project_context=True`
  （注释登记第四例）+ purpose 材料边界条款 + selfcheck 一条。
- `tests/test_dl_flow_engine.py`：TestSegmentSpawnOverrides ——
  `test_u4_other_steps_no_step_strip` 更新（#2 翻转为置位，钉死 #3/#4/#5
  仍不置位）+ 新增 `test_u4_step2_step_level_strip`（env 双开关 + tools
  白名单钉死）+ purpose/selfcheck 条款关键词钉死（防静默丢失）。
- `skills/workflow-creation/references/nodes-index.md`：u:4 条目子2 摘要
  同步（purpose 实质内容变更）。
- 不改：engine 机制代码（全现成）、dl_drive.py（条款走 purpose 文本，
  非 pack_self_contained 分支）、gate 文本（§2 L2 三重核对）、
  SEGMENT_CHAIN_NODES / MERGED_RUN_NODES。

## 5. 实测收官（待 B 轮后填）
