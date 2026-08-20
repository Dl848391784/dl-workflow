# plan:1 子3（可行性验证）耗时/token 优化设计——复用钉死（验证步形态）+ 台账缓存通道钉死

> 日期：2026-08-20 · 分支 feat/p1-sub3-cost · 状态：设计中（A 轮基线采集中）
> 上游：designs/p1-sub2-cost-optimization-design.md（plan:1 子2 三杠杆，遗留
>      立项=本子3）；designs/u4-sub2-cost-optimization-design.md（验证步复用
>      钉死 #25 收紧形态）；designs/u4-sub3-cost-optimization-design.md（验证
>      步 pack_self_contained #19 否判决）；designs/u3-sub1-cost-optimization-
>      design.md（env 剥离反超实证 → #23 第三核对）。
> 触发 = 用户指令（2026-08-20）：「优化 plan:1 的 step3，耗时和 token 消耗要
> 大幅降低，能用前面步骤沉淀下来的 discovered 和 evidence 就尽量用，避免
> factor 化；跑测试工作流用 ac-deepseek1；amplitude 今日值 4929.2%」。
> 数值口径：种子 problem_statement 保持 4824.5% 不改（runtime-audit #25：
> 数值漂移属 #18 混淆面）；4929.2% = 今日实际值，若运行中被问以此作答。
> 避免 factor 化 = cost-optimization #2：全部杠杆为框架通用机制/通用措辞，
> 零项目语义耦合（条款不点名任何项目构件）。

## 0. 范围声明

本设计只覆盖 **plan:1 子3（可行性验证，非交互验证型工作步）**。子3 是链头
（子2 交互步恒 fresh spawn 断链点之后的首个非交互步），恒 fresh spawn，
无链税；prep 零成本（无 NEXT_PREP 面）。子4/子5 链税与 strip/pack 置位不在
本设计（遗留立项）。

## 1. 基线实测（A = p1_sub3_ab 主树码 f445570，种子 = p1_sub2_ab 完成态
##    ≤plan:1#2，ac-deepseek1/deepseek-v4-flash headless）

【待 A 轮完成后填充】

## 2. 方案（杠杆选型）

### 杠杆菜单逐项核对（逐杠杆处置 + 依据）

| 杠杆 | 处置 | 依据 |
|---|---|---|
| Step strip（env 剥离） | **不置位** | #23 第三核对「env 剥离边界」：子3 五项核验④=项目硬规则兼容须点名规则条号（H1/H1.1/H7/H8/H9/H11-H13）——规则条号=本步一等材料，与 u:3#1 反优化**同型**（B1 实证：剥后模型为点名条号重读 CLAUDE.md/PROJECT.md +40k 总账反超）；p1-sub2 设计亦明示「硬规则兼容=子3 五项核验④的职责」是子2 可剥的对照面。HR 速查表在 CLAUDE.md §5（项目上下文），保留 env 即规则材料在场 |
| pack_self_contained | **不置位** | #19 判别：验证型步——产出新事实（五项核验留痕+三态），包外单点验证是合法职责面（枚举例外内），与 u:4#2/#3 同结论 |
| 断链（出 SEGMENT_CHAIN_NODES） | **不立项** | 子3 是链头恒 fresh spawn，断链收益面=子4/子5 非本步；且断链暴露下游步条款缺口有 u:4#4 前车（B2 步体爆炸），子4/子5 条款核对未做 |
| MERGED 续步 | **不立项** | #24 抉择口径：子3 步体非「极小搬运型」（验证查询调用多），deepseek 续步暖率彩票已两节点证伪 |
| Node/Step tools 收窄 | **不动** | plan:1 Node 白名单已含子4 Agent/子5 Skill 需求（p1-sub1 L2）；无 Step 级 tools 机制（p1-sub2 设计已登记「无此机制，surgical」） |
| **复用钉死条款进 purpose/selfcheck** | **采用（L1）** | 见下 |
| **台账缓存通道钉死**（dl codebase query --symbol） | **采用（并入 L1 条款）** | 机制现成（dl_codebase.py 台账，子1 已落账 5 符号）；子3 重查子1 已查符号自动返缓存=零成本合法留痕 |

### L1 复用钉死条款进 purpose/selfcheck（文案，#25 收紧形态：默认零重验+枚举例外+按条配额）

【条款全文待 A 轮归因后定稿——按基线实际浪费形态对齐】

**写侧对齐（append-trace mech 三件套核对，本轮已核）**：
- ①存在性段：mech 放行条件=file:line 在场**或**工具动词在场
  （`_check_feasibility_trace` ①段逻辑：「file:line 定位本身即合法出处
  不拦」）——「复用 子1 留痕：<file:line>」形态含 file:line 当场过墙 ✓
- ②重复造轮子段：声称「无重复/需新建」须查询动词（codegraph/Grep/grep/
  查询/返回/搜索/检索/查得）在同段——复用形态须带原查询动词+返回概述
  （「复用 子1 留痕：grep 实测 scripts/ 7 脚本无一做 X」）才过墙；
  条款须钉死此形态 ✓
- ③影响面段：无 mech，judge 方框二「附 impact 返回的 callers 数与名单即
  合规」——复用形态「复用 子1 留痕：codegraph callers X 返回 N 个（名单）」
  字面命中合规形态 ✓

**判侧对齐（gate 文本零变更三件套核对 #29）**：【待 A 轮后定稿时逐条填】

## 3. 预期与验收（预登记）【待 A 轮后填】

## 4. 实现清单【待 A 轮后填】

## 5. 实测收官【待 B 轮后填】
