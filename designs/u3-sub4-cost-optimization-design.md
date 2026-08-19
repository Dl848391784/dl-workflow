# understand:3 子4（归一化陈述）耗时/token 优化设计——逐步 env 剥离 + 材料边界 + 格式真源钉死

> 日期：2026-08-19 · 分支 feat/u3-sub4-cost · 状态：收官（一轮 A/B 全验收达标）
> 上游：designs/u3-sub3-cost-optimization-design.md（子3 三杠杆收官：L1 复用收紧 /
>      L2 Step 级 segment_strip_project_context 首例 / L3 pack_self_contained 置位）；
>      designs/u3-sub2-cost-optimization-design.md（断链收官，u:3 各步 fresh 段）；
>      designs/u2-sub2-cost-optimization-design.md（#16 材料边界三件套）。
> 触发 = 用户指令（2026-08-19）：「优化 understand:3 的 step4，耗时和 token 消耗
> 要大幅降低，能用前面步骤沉淀下来的 discovered 和 evidence 就尽量用，避免
> factor 化；跑测试工作流用 ac-deepseek1；amplitude 今日值 4947.7%」。
> 数值口径：种子 problem_statement 保持 4824.5% 不改（runtime-audit #25：
> 数值漂移属 #18 混淆面非一致性 bug）；4947.7% = 今日实际值，仅供核对
> 「今值」类断言时知晓（#4 纯装配步不触发新取证，不受影响）。

## 1. 基线实测（现成数据，零新跑）

u3_sub3_ab4（2026-08-19，ac-deepseek1/deepseek-v4-flash headless，当前 HEAD 同码
——子3 优化只动 #3 段 prompt 与 spawn env，#4 段面零变更）u:3#4 段
（session b76c1aae）逐调用配平：

| 指标 | 值 |
|---|---|
| 首调 fresh | 31,787（cr=0，fresh 段恒定地板） |
| 段 fresh 合计 | 70,260 |
| 段 cr 合计 | 1,049,600 |
| 段 out 合计 | 39,482（载荷 ~20k + 两轮重写 ~17k + 杂项） |
| 模型墙钟 | 274s |
| API 调用 | 20 |
| 工具调用 | 22（Bash×15 / Read×5 / Skill×1 / Edit×1） |
| 成本等效（fresh+0.1cr） | 175.2k |

### 成本归因（工具序列逐条核对）

#4 是纯消费装配步（purpose 已钉「text 直接取自子3 outcome 标签、禁二次创作」），
合法交付只需 6 调用（Skill define-problem / scaffold / Read 骨架 / Edit /
append-trace / 落库尾验）。实际 22 调用中 **16 个是纯税**，三类：

| 类别 | 调用 | 判定 |
|---|---|---|
| evidence 元探查/重读 | tail evidence + grep sub_step=3/1/2 + ls workflows + cat discoveries.jsonl（6 次） | 子1-3 trace 全文已在交接包「本节点各步最新留痕」节——#16「包尾按需 Read 邀请=反指」第三次复现（u:2#2/u:3#3 同型） |
| node-rules 全量 Read | Read node-rules.understand:3.md（1 次） | O2 已瘦渲染 titles-only 注入，全量文件重读=驻留死重 |
| 格式猎捕 | grep/Read ~/.dl-workflow tests ×9（【statements】/【text】/boundary/_ID_RE/_parse_trace_md） | 模型为「编号传导机械核对缺传即拒」去 dl-workflow 测试源码反推校验实现——载荷格式唯一真源应是 scaffold 骨架+报错文案，查实现=跨仓 roam |

首调 31,787 分解：项目上下文 ~11.9k（B1 决议节点级保留，但 #4 是消费步——
规则内容 _SOLUTION_FREE_SUBJECT_RULE/_SCOPE_VERB_RULE 经 purpose 常量逐字
在场，方案名词扫描在 append-trace 脚本侧，均不依赖 CLAUDE.md/auto-memory）
+ 段 prompt（交接包随节点推进含 #1-#3 trace 全文，较 #3 首调 +5.4k）
+ harness+工具 schema（node 级 tools 白名单已裁）+ node-rules titles。

## 2. 方案（三杠杆，全部机制现成/文案通用，零新机制、零 factor 化）

### L2 逐步 env 剥离——segment_strip_project_context 置位（u:3#3 后第二例）

#4 置位前置核对（同 u3-sub3 §2 L2 程序）：交付物=子3 条目的形式装配
（text 取自子3 outcome 标签、boundary 放实现指针、类型标签从子3 传导）——
不点名任何规则条号、不读项目文件；方案名词机械扫描=append-trace 脚本侧
（codegraph db + git ls-files 真值，主仓根运行，与段 env 无关）。B1 反优化
结论限子1/子2（生成/验证步），不覆盖本步；子3 已置位同型。
生效 = node 字段 OR step 字段（机制 u3-sub3 已落地，本设计只置位）。

### L3 材料边界——pack_self_contained 置位（#16 泛化第三例）

输入契约逐字段核对（置位前置）：

| 输入契约项 | 包内位置 | 核对 |
|---|---|---|
| step3.scope_proposal（in/out 双侧+双字段+矩阵+约束回写） | 本节点留痕节（#3 trace 全文，剥机械字段保内容） | ✓ handoff_pack 单源逻辑（本节点 trace 保全文，P1-1）+ 种子包冒烟待验 |
| 类型标签来源（已验证/假设+置信度/in/out） | 嵌于 #3 trace（双字段+约束回写携带子2 三态） | ✓ 基线轮 trace 实证传导正确 |
| statements 载荷格式 | payload_format_hint 注入 + scaffold 骨架 | ✓ 不依赖 evidence |
| block 判词（返工场景） | 包内「当前子步最新门控判词」节 | ✓ |

置位后两处消费点（包尾「材料已在包内」+ 段 prompt「材料边界」条款）已泛化
（u:2#2/u:3#3），零新机制。灭类别一/二（7 次调用）。

### L4 格式真源钉死——purpose/selfcheck 文案（通用，四桶分工直推）

格式猎捕 9 次调用的根因 = purpose 披露「机械核对缺传即拒」却不说明「核对
细节毋需预知」——弱模型为规避被拒去 dl-workflow 测试源码反推 _ID_RE/
_parse_trace_md 实现。补条款（purpose 末 + selfcheck 一条，措辞通用）：

- purpose：「载荷格式与编号传导的**唯一真源 = --scaffold 骨架 + append-trace
  报错文案**（四桶分工：格式归脚本）——禁读引擎/测试源码反推校验实现；
  被拒按报错文案逐字修即可」。
- selfcheck：「格式照 scaffold 骨架填了吗——没去翻 dl-workflow 引擎/测试
  源码反推校验实现吧（被拒按报错文案修）？」

**零和自检（#6）**：灭的是重复/越界动作非转移——子3 不因此多跑任何查询
（#3 优化已收官独立验收），judge 判据零变更（gate 不动），通过零和检测。
**质量护栏**：statements 三字段/编号传导/方案名词扫描全在 append-trace
机械层不动；gate 四方框不动；装配义务（逐项+原子+去上下文）不动。

### 显式不做

- 不动 gate 四个违规方框与默认-PASS framing（v2.84 反转达标，u:3#4 已
  是反转后形态）；
- 不动子1/子2/子3/子5 任何 purpose/gate（各自独立立项已收官/未立项）；
- 不改交接包组成（#1/#2 trace 对 #4 的冗余 ~3k tok，沿 u3-sub3 决议——
  量级不值得新机制）；
- 不碰 MERGED/CHAIN（u3-sub2 断链收官，EV 结论不重启）；
- 不加 mech_checks（格式猎捕是文案可解的探索行为，机械围栏会误伤合法
  定向 Read——宁纵勿枉；S15 白名单已天然限制段内工具面）。

## 3. 预期收益（deepseek 口径，对照 §1 基线）

| 指标 | 基线 | 预期 | 机制 |
|---|---|---|---|
| 首调 fresh | 31,787 | ~19.9k（**-37%**） | L2 剥项目上下文 11.9k（u2-residual 探针实测值，u3-sub3 ab 四轮复验 -45.5%/-11.9k 精确一致） |
| 段 fresh | 70,260 | ~28-36k（**-49~60%**） | L2 -11.9k + L3/L4 灭 ~16 次纯税调用的工具结果 ~25k |
| 段 cr | 1,049,600 | ~250-400k（**-62~76%**） | 20→~6 API 调用（少 ~14 轮全量前缀重读）+ 逐调前缀 -11.9k |
| 成本等效（fresh+0.1cr） | 175.2k | ~53-76k（**-57~70%**） | 同上 |
| 模型墙钟 | 274s | ~100-150s（**-45~63%**） | 22→~6 工具调用（少 ~14 轮 API RTT） |
| out | 39,482 | ~22-28k | 载荷 ~20k 不动；灭格式猎捕的两轮重写（不作验收） |

护栏：一次通过率不降（gate 零变更）；trace 质量不降（statements 逐项+
三字段+编号传导——A/B 逐项核对）；回滚 = 两处字段翻转 + 文案回退。

## 6. 实施验证记录（2026-08-19，一轮 live A/B，ac-deepseek1/deepseek-v4-flash）

种子五件套（runtime-audit #25）：u3_sub3_ab4 evidence 裁到 u:3#3（15 行）+
last_judged_trace 裁 + 段记录清 + settings name-agnostic grep=0 + 包冒烟
（18,469 字符，子3 留痕全文在场 + 尾行「材料已全部在包内」已随置位渲染）。
驱动法 `AC_WORKFLOW_LAUNCHER=<worktree>/scripts/workflow/dl-launch.sh
ac-deepseek1 --dl u3_sub4_ab --resume --headless`（#24 纪律）。

### 6.1 读数对照（u:3#4 段，同种子源同 provider）

| 指标 | 基线（u3_sub3_ab4 #4） | ab1（u3_sub4_ab #4） | 变化 |
|---|---|---|---|
| 首调 fresh | 31,787 | 19,571 | **-38.4%**（探针预测 -11.9k，实测 -12.2k） |
| 段 fresh | 70,260 | 40,750 | -42.0% |
| 段 cr | 1,049,600 | 143,872 | **-86.3%** |
| 成本等效（fresh+0.1cr） | 175.2k | 55.1k | **-68.5%** |
| out | 39,482 | 27,166 | -31.2%（载荷 ~19.6k 不动） |
| 模型墙钟 | 274s | 147s | **-46.3%** |
| API/工具调用 | 20/22 | 6/5 | -70%/-77% |

### 6.2 工具序列（理想最小交付形态一次达成）

`Skill(define-problem) → append-trace --scaffold → Read 骨架 → Edit 载荷 →
append-trace --from-file`——5 调用零探索：零 evidence/state 元探查（L3 ✓）、
零 node-rules 全量重读（L3 ✓）、零 ~/.dl-workflow 源码/测试格式猎捕（L4 ✓）、
零规范文档重读（B1 症状未复现，L2 ✓）。

### 6.3 验收对照（预登记口径，全达标）

| 验收点 | 目标 | ab1 实测 | 判定 |
|---|---|---|---|
| 首调 fresh | ≤21k | 19,571 | ✓ |
| 工具调用 | ≤9 | 5 | ✓ |
| 段 cr | ≤450k | 143,872 | ✓ |
| 零 block / judge pass | 是 | 一把过（#4 gate pass → #5 confirm → u:4） | ✓ |
| 行为核对（元探查/猎捕/规范重读三零） | 是 | 工具序列逐条核对全零 | ✓ |
| trace 质量 | 不降 | 31 条 statements 三字段齐备、IS-M1-*/OS-*/C* 编号逐项传导、类型标签与子3 一致（12 已验证+2 假设含置信度+12 in+7 out） | ✓ |

### 6.4 收官结论

三杠杆一轮全落地：L2（首调 -38.4%，与探针值精确一致）+ L3（元探查归零，
#16 泛化第三例）+ L4（格式猎捕归零——「格式真源=骨架+报错文案」通用条款
首例）。一轮即收官的依据：三杠杆均为已验证机制的再次应用（L2/L3 探针值
与前例精确复现），非新机制首验；预登记验收全绿、质量逐项核对不降。
数值口径：amplitude 今日值 4947.7% 与种子 4824.5% 的漂移未进验收面
（#4 纯装配步零新取证，预登记判断成立）。回滚面 = 两处字段翻转 + 文案回退。

## 4. 验证计划

1. 测试：pack_self_contained/segment_strip_project_context 是 Step 声明式字段
   （机制已有测试覆盖），本刀新增 = u:3#4 置位 pinning（字段在表）+ 装配
   不变量（u:3#4 交接包含 #3 trace 全文 + 包尾「材料已在包内」条款）；全量
   pytest + ruff。
2. **live A/B（ac-deepseek1，新实例 u3_sub4_ab）**：种子 = u3_sub3_ab4
   evidence 裁到 u:3#3 gate 通过（裁 ≥sub_step=4 的 trace），state 置
   understand:3 sub_step_index=4 从 #4 直接起跑；种子五件套单源 =
   runtime-audit #25。驱动法 =
   `AC_WORKFLOW_LAUNCHER=<worktree>/scripts/workflow/dl-launch.sh ac-deepseek1 --dl u3_sub4_ab --resume --headless`
   （#24：dl() 不读 AC_WORKFLOW_LAUNCHER）；跑完核 driver 日志确认 worktree
   代码路径。基线 = u3_sub3_ab4 #4 读数（§1，同 HEAD 同 provider 同种子源）。
3. **预登记混淆声明**：
   - 主验收口径 = **首调 fresh（L2 机制读数）+ 工具调用数（L3/L4 行为读数）
     + 段 cr**——与步体方差（#40）天然分离；
   - 段 fresh/墙钟受步体轮数方差影响，只作参考不作硬验收；
   - 种子与基线同源（u3_sub3_ab4 evidence 裁断），u:3#3 之前零漂移；
   - out 不作验收（载荷体量由内容决定）；
   - amplitude 今日值 4947.7% vs 种子 4824.5%：#4 不触发新取证，数值漂移
     不进验收面（#18）。
4. 验收点：首调 fresh ≤21k；工具调用 ≤9（合法交付 6 + 3 容差）；段 cr ≤450k；
   零 block、judge pass；**行为核对**：零 evidence/state 元探查（L3）、零
   dl-workflow 源码/测试猎捕（L4）、零规范文档全量重读（B1 症状）；trace
   质量逐项核对（statements 逐项传导子3 编号、三字段齐备、类型标签与子3
   一致、原子+去上下文）。

## 5. 影响面

- `dl_flow_nodes.py`：understand:3 子4 置 segment_strip_project_context +
  pack_self_contained + purpose/selfcheck 文案补格式真源条款
- tests：u:3#4 置位 pinning + 装配不变量
- nodes-index.md：understand:3 子4 摘要块手工同步（purpose 实质内容变更）
- 三模式：drive headless / front 段工人都经 segment_spawn_overrides 单源；
  v2 TUI 不经此路径零变更
- 在飞工作流：state 无 schema 变更；purpose 文本变更对在飞 u:3 实例下次到
  #4 生效（方向=省；gate 零变更无翻盘风险）
