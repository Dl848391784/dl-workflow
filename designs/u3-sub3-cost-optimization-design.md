# understand:3 子3（范围界定）耗时/token 优化设计——复用前序取证 + 逐步 env 剥离

> 日期：2026-08-19 · 分支 feat/u3-sub3-cost · 状态：实施中
> 上游：designs/u3-sub2-cost-optimization-design.md（断链收官，u:3 各步 fresh 段）；
>      designs/u3-sub1-cost-optimization-design.md（tools 白名单 + B1：u:3 节点级
>      env 剥离是反优化）；designs/u2-residual-cost-optimization-design.md（#23
>      段前缀外科剥离 + 置位前置核对）；designs/u2-sub2-cost-optimization-design.md
>      （#16 材料边界三件套）。
> 触发 = 用户指令（2026-08-19）：「优化 understand:3 的 step3，耗时和 token 消耗
> 要大幅降低，能用前面步骤沉淀下来的 discovered 和 evidence 就尽量用，避免
> factor 化；跑测试工作流用 ac-deepseek1；amplitude 今日值 4920.2%」。

## 1. 基线实测（现成数据，零新跑）

u3_sub2_ab5（2026-08-19，ac-deepseek1/deepseek-v4-flash headless，当前 HEAD 同码
——断链后 u:3#2/#3/#4 各自 fresh 段）u:3#3 段（session 45690f82）逐调用配平：

| 指标 | 值 |
|---|---|
| 首调 fresh | 26,336（cr=0，fresh 段恒定地板） |
| 段 fresh 合计 | 55,289 |
| 段 cr 合计 | 289,408 |
| 段 out 合计 | 25,922（call1 thinking 8,904 + 载荷 14,891 + 杂项） |
| 模型墙钟 | 224s |
| API 调用 | 8（真实配平后） |
| 工具调用 | 13 |

### 成本归因（工具序列逐条核对，对照子2 trace）

子2 trace（evidence sub_step=2，5.5k 字符，已含完整改动面地图：模板 9 处 ×100
的 file:line 清单、convert_return_to_percentage 等 3 符号的 callers 输出、
layered_backtest.py:713/:728/:730/:732 折算锚点、H15/H1/H1.1/H9 原文引用）。
子3 段 prompt 的「本节点各步最新留痕」节（8,760 字符）已含子2 trace 全文——
**全部改动面事实在首调上下文里已在场**。但子3 实际动作：

| 子3 动作 | 子2 trace 是否已覆盖 | 判定 |
|---|---|---|
| codegraph impact convert_return_to_percentage / load_backtest_results / load_composite_results | 已覆盖（子2 callers ×3 同符号，输出等价改动面） | **重复取证** |
| grep `\* 100\|_ann` 三模板 + find web_ui html + grep worktree 模板 | 已覆盖（子2 C1 答案含 9 处 file:line 逐字清单） | **重复取证** |
| Read layered_backtest.py | 已覆盖（子2 C6 答案引用 :713/:728/:730/:732 原文行） | **重复取证** |
| codegraph impact _aggregate_results（13 符号） | 未覆盖 | 真缺口（WR3 引用） |

13 个工具调用中 **9 个是纯重复取证**（对同符号/同文件/同模板的二次查询），
唯一真缺口是 _aggregate_results 的 impact。根因 = 子3 purpose 明文
「用 codegraph impact 取证改动面，附留痕」——模型把「取证」读成「本步必须
亲自跑工具」，而 u:3#2 gate 已有反例先例（「子2 处置子1 候选、引用子1 已取证
来源即合规（不要求本步重跑/本步新工具留痕）」）。**purpose 指示动作、gate
不豁免前序复用 = 弱模型必然重跑**（#3 进入条件条款的反向形态）。

首调 26,336 分解：项目上下文 ~11.9k（CLAUDE.md+auto-memory+git status，
B1 决议 u:3 节点级保留）+ 段 prompt ~6.5k（交接包 13.4k 字符）+ harness+工具
schema ~4.8k（tools 白名单已裁）+ node-rules ~0.6k。

## 2. 方案（双杠杆，机制 + 文案各一）

### L1 复用优先——子3 purpose/selfcheck/gate 三触点修订（框架通用，零新机制）

purpose 改动面取证段修订为**复用优先、缺口才新取证**：

- 「用 codegraph impact 取证改动面，附留痕」→「改动面取证**优先复用子2 已
  验证留痕**（交接包「本节点各步最新留痕」节在场，含 callers/impact 输出与
  模板 file:line 清单）——逐字引用并标注来源（子2/Cx 条目号）；**仅子2 未
  覆盖的改动面缺口**（新 symbol/新文件）才本步新跑 codegraph impact 附留痕；
  禁为「本步留痕」重跑前序已完成的相同查询（重复取证 = 纯税，证据效力不增）」。
- selfcheck 补一条：「改动面证据里前序（尤其子2）已验证的项都复用了吗
  （逐字引用+来源标注）？只有缺口项才新跑 codegraph impact 吗？」
- gate 【合法正例】方框补一条（默认-PASS framing 不动、五个违规方框不动）：
  「改动面证据引用子2 已验证留痕（逐字 file:line + 来源标注）即合规——不
  要求本步重跑 codegraph impact/重读已读文件；仅『in 侧改动面无出处（既无
  本步留痕也无前序引用）』才可归方框二放水判」。

**零和自检（#6）**：子2 的 callers/grep 是子2 自己的验证义务，本来就要跑；
子3 消灭的是**重复动作**不是转移（子2 不因此多跑任何查询）——上游零涨幅、
下游净省 9 调用，通过零和检测。**质量护栏**：子3 in 侧每项仍须带实现指针
（gate 方框二/三不动），复用只是把指针的出处从「本步新跑」换成「前序留痕
逐字引用」，指针精度不降。

### L2 逐步 env 剥离——Step 级 segment_strip_project_context（#23 粒度下沉）

现状：`_SEGMENT_STRIP_ENV` 按 Node 字段置位（engine.segment_spawn_overrides
只读 node）。B1 实证 u:3 **节点级**剥离是反优化——但 B1 的功能材料需求集中
在子1（候选生成须点名规则条号，须知道有哪些规则）与子2（Read 规范原文验证）。
**子3 是消费步**：交付物（in/out 清单+矩阵+约束回写）引用的规则内容
（H15/H1/H1.1/H9 原文）全部已在子2 trace 逐字在场；唯一增量引用（H8）是
CLAUDE.md §5 一行指针，purpose 文本自身已携带「单次改动 ≤3 文件」要旨。

改动：Step 加声明式字段 `segment_strip_project_context: bool = False`；
`segment_spawn_overrides(node, step=None)` 生效值 = node 字段 OR step 字段
（单调只增不剥回；MergedSession 段内续步管线 env 进程级固定，step 级字段在
合并段不生效——u:3 已断链非合并，不受影响，注释明示）；dl_drive 4 个 spawn
点中有 step 上下文的 3 处（TUI 段/prep 段/普通段）传入 step。
**只对 u:3#3 置位**（子1/子2 维持 B1 决议不动；子4 归一化陈述同构可候选，
但本设计 surgical 只动子3，留后续项）。

**B1 风险对冲**：子3 若确需规则原文（如 H8 逐字），Read 在白名单内可定向读
——一次定向 Read ~2-3k << 剥离省的 11.9k×8 调用 ≈ 95k。A/B 行为核对项显式
列「零规范文档全量重读（定向 Read 单行级合法）」。

### 显式不做

- 不动 gate 五个违规方框与默认-PASS framing（v2.90 已反转达标）；
- 不动子2/子4/子5 任何 purpose/gate（各自独立立项）；
- 不改交接包组成（子1 trace 对子3 的冗余 ~1.5k tok，量级不值得新机制）；
- 不碰 MERGED/CHAIN 白名单（u3-sub2 已裁决断链收官，EV 结论不重启）；
- 不加 mech_checks（复用 vs 重跑是质量/成本权衡非形式要件，下沉机械层会误伤
  合法缺口取证——宁纵勿枉）。

## 3. 预期收益（deepseek 口径，对照 ab5 #3 基线）

| 指标 | 基线 | 预期 | 机制 |
|---|---|---|---|
| 首调 fresh | 26,336 | ~14.4k（**-45%**） | L2 剥项目上下文 11.9k（u2-residual 探针实测值） |
| 段 fresh | 55,289 | ~33-38k（**-32~40%**） | L2 -11.9k + L1 灭 ~9 重复取证调用的工具结果 ~10k |
| 段 cr | 289,408 | ~150-180k（**-38~48%**） | L2 前缀 -11.9k×~7 后续调用 ≈ -83k + L1 上下文增长减缓 |
| 成本等效（fresh+0.1cr） | 84.2k | ~48-56k（**-33~43%**） | cr≈0.1×fresh 单价（u3-sub2 §6.4 同口径） |
| 模型墙钟 | 224s | ~130-160s（**-30~42%**） | 13→~5 工具调用（少 4-5 轮 API RTT）+ 逐调前缀缩小 |
| out | 25,922 | ~22-25k | 载荷 14.9k 是交付物不动；call1 规划 thinking 或略降（不作验收） |

护栏：一次通过率不降（gate 判据五方框零变更，只加合法正例）；trace 质量不降
（in/out 双字段、矩阵逐项、约束回写条数——A/B 逐项核对）；回滚 = Step 字段
翻转 + purpose 文本回退。

## 4. 验证计划

1. TDD 红→绿：segment_spawn_overrides 逐步置位（step=None 向后兼容 / step
   置位生效 / node 已置位时 step False 不剥回 / MergedSession 路径不传 step
   保持节点级语义）+ 全量 pytest + ruff。
2. **live A/B（ac-deepseek1，新实例 u3_sub3_ab）**：种子 = u3_sub2_ab5
   evidence 截断到 u:3#2 gate 通过（裁 ≥sub_step=3 的 trace），state 置
   understand:3 sub_step_index=3 从 #3 直接起跑；种子五件套单源 =
   runtime-audit #25。驱动法 =
   `AC_WORKFLOW_LAUNCHER=<worktree>/scripts/workflow/dl-launch.sh ac-deepseek1 --dl u3_sub3_ab --resume --headless`
   （#24：dl() 不读 AC_WORKFLOW_LAUNCHER）；跑完核 driver 日志确认 worktree
   代码路径。基线 = ab5 #3 读数（§1，同 HEAD 同 provider 同种子）。
3. **预登记混淆声明**：
   - 主验收口径 = **首调 fresh（L2 机制读数）+ 工具调用数（L1 行为读数）+
     段 cr**——与步体方差（#40）天然分离；
   - 段 fresh/墙钟受步体轮数方差影响，只作参考不作硬验收；
   - 种子与基线同源（u3_sub2_ab5 evidence 裁断），u:3#2 之前零漂移；
   - out 不作验收（载荷体量由内容决定）。
4. 验收点：首调 fresh ≤16k；工具调用 ≤7（scaffold+Read 骨架+≤1 缺口取证+
   Edit+落库 = 5 基准 + 2 容差）；段 cr ≤200k；零 block、judge pass；
   **行为核对**：零规范文档全量重读（B1 症状监测）、改动面证据带前序来源
   标注、若新跑 impact 仅限 _aggregate_results 类真缺口；trace 质量逐项核对
   （in/out 双侧+双字段+矩阵逐项+约束回写+只提案不拍板）。

## 5. 影响面

- `dl_flow_nodes.py`：Step 加字段 segment_strip_project_context；understand:3
  子3 purpose/selfcheck/gate 文本修订 + 该步置位
- `dl_flow_engine.py`：segment_spawn_overrides 签名加 step=None（向后兼容）
- `scripts/workflow/dl_drive.py`：3 个 spawn 点传 step（MergedSession 不传，
  注释明示进程级语义）
- tests：逐步置位 4 则 + 既有 spawn 覆盖测试回归
- nodes-index.md：understand:3 子3 摘要块手工同步（purpose 实质内容变更）
- 三模式：drive headless / front 段工人都经 segment_spawn_overrides 单源；
  v2 TUI 不经此路径零变更
- 在飞工作流：state 无 schema 变更；purpose/gate 文本变更对在飞 u:3 实例下次
  到 #3 生效（方向=省；gate 只加合法正例不新增 block 面，无已 block 载荷
  被翻盘风险）
