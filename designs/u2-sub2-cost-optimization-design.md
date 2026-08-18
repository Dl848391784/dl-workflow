# understand:2 子2（对齐质检）耗时/token 优化设计

> 日期：2026-08-18 · 分支 feat/u2-sub2-cost · 状态：实施中
> 上游：designs/u2-sub1-cost-optimization-design.md（修B「材料随迁+条款禁读」范式，本设计是其向非交互推理步的平移）
>      designs/u1-overall-cost-optimization-design.md（逐调用口径纪律 #22）
> 触发 = 用户指令（2026-08-18）：「优化 understand:2 的 step2，耗时和 token 消耗要大幅降低；
> 跑测试工作流用 ac-deepseek1；amplitude 今日值 4920.2%」（承 u:2 子1 优化之后）。

## 1. 基线实测（u2_sub1_ab 真实数据，ac-deepseek1/deepseek-v4-flash，2026-08-18）

u:2#2 = 非交互推理步（双向追溯矩阵+方案剥离+冲突检测），drive 段链会话（u:2#2→#3→#4 同 session
d81dacff --resume 续跑）。唯一真实样本（amplitude_annualized 三度到达 u:2#1 均未进 #2；
tail_volume 跑在 v2 时代无段记录），n=1，方差声明沿用 #22 纪律。

逐调用拆解（usage 去重 keep-max，段内 8 调）：

| # | 时刻 | fresh | cache_read | out | 动作 |
|---|---|---|---|---|---|
| 1 | 17:22:34 | 38,960 | 0 | 789 | 冷启动 + Bash 侦察（ls -la/wc evidence 68KB） |
| 2 | 17:22:36 | 966 | 39,680 | 97 | **Read evidence 全量 68KB** |
| 3 | 17:23:19 | 19,645 | 40,704 | 5,661 | thinking（消化刚读的 68KB；19.6k fresh=evidence 进上下文） |
| 4 | 17:23:22 | 308 | 65,920 | 78 | Read 载荷骨架 |
| 5 | 17:23:53 | 109 | 66,304 | 6,304 | thinking（写矩阵） |
| 6 | 17:24:06 | 6,525 | 66,304 | 136 | Edit 载荷 |
| 7 | 17:24:08 | 138 | 72,960 | 135 | Bash 占位符扫描 |
| 8 | 17:24:11 | 167 | 73,216 | 538 | Bash append-trace 落库 |
| 计 | ~99s | **66,818** | **425,088** | **13,738** | + judge ~35s（独立进程 ~2-3k，v2.12 已裁剪） |

链式下游冷启动（同 session resume，deepseek 流式缓存会话隔离=每段首调必冷全量重写）：
u:2#3 = **80,308** fresh（cr=0）、u:2#4 = **102,921** fresh（cr=1,792）——对比 u:2#2 的 38,960，
单调涨 delta 里 ~19.6k 是子2 那次 evidence 全量读的驻留残留（68KB 进会话上下文后随
resume 逐段重付）。

## 2. 根因

**交接包已含本步全部材料，模型仍全量重读 evidence——纯冗余读，且污染链式下游。**

u:2#2 矩阵三件套的输入契约：
- 子1 目标候选+出处原话 → 交接包「本节点各步最新留痕」= 子1 trace **全文** ✓
- ProblemContext 存活问题陈述（4 条） → 交接包「前序节点结论摘要」= 子6 statements **全文** ✓

模型实测行为：冷启动后先 `ls -la/wc` 侦察 evidence（68KB），再整量 Read——动机是包尾
通用尾行「（以上为摘要；前序细节按需 Read evidence，禁凭记忆补全）」的邀请 + 段 prompt
无「材料已在包内」条款，弱模型保险起见全读。读完的 trace 内容核对：矩阵引用的陈述原文/
出处全部在包内已有材料中，**零信息增量**。

成本三层：
1. 本段直接税：+20.6k fresh（966 侦察 + 19,645 读入）、+43s 墙钟（17:22:36→17:23:19）、
   68KB 驻留后本段后续 5 调 cache_read 各多背 ~20k（≈ -100k cr）。
2. 链式下游税：u:2#3/#4 冷启动各多付 ~19.6k fresh（≈ -39k/run）。
3. 不可砍项（不动）：冷启动 39k = P1-1 判定的正常水位（harness 22.5k + node-rules 1.2k +
   交接包 ~14k + step prompt ~2k）；thinking ~12k = 矩阵推理真实工作；scaffold/Edit/落库
   = 四桶必要动作。

## 3. 方案（两修 + 声明式单源，零判据变更）

u2-sub1 修B 已验证范式 = 「材料随迁 + 双通道条款（已覆盖处禁再 Read evidence 全量）」
（live A/B 实测 Q&A 会话零 evidence 读）。本步材料**本就在包内**（无需随迁），故只剩条款
+ 消除反指邀请：

### 修A：Step 声明式字段 `pack_self_contained` + 段 prompt 条款（主修）

- `dl_flow_nodes.py`：Step 加 `pack_self_contained: bool = False`——声明「本步所需材料
  已全部在交接包内（本节点前序 trace 全文 + 前序节点结论摘要）」。声明式单源
  （interactive/tier/pack_full_reports 同范式），禁 driver 硬编码步号。
- u:2#2 置 True（材料完备性已逐字段核对，见 §2）。
- `dl_drive.py` 段 prompt（build_step_prompt 单点，drive/front 两模式共用——front 非交互步
  同样走 --segment 段工人）：True 时追加条款——
  「材料边界：本步所需材料已全部在上方交接包内（本节点前序留痕全文 + 前序节点结论摘要）
  ——直接引用，禁 Read evidence 全量翻找；确有缺口才按指针定点补（宁纵勿枉）。」

### 修B：handoff_pack 尾行条件化（消除文案矛盾）

`dl_flow_engine.py` handoff_pack 的通用尾行「以上为摘要；按需 Read evidence」与修A 条款
直接矛盾（两个强信号打架弱模型必反复违规，症状 F 族教训）。当前步 True 时改打：
「（本步所需材料已全部在包内——前序细节禁 Read evidence 全量，确有缺口按指针定点补）」。
False 步行为零变更。

### 显式不做

- 不做机械围栏 deny（drive 模式 S15 本就降级跳过；段工人无 PreToolUse 拦截面，新造拦截
  基建 = 过度工程。文案条款在 u2-sub1 已实证有效，A/B 复核）。
- 不动 judge 判据 / gate 机制 / thinking 预算 / 冷启动水位（P1-1 已裁决）。
- 不做 driver 侧 transcript 自动扫描告警（A/B 人工核对；普及时再议）。
- 不给其他步预置 True——每步材料完备性须逐字段核对后才许置位（本设计只核了 u:2#2）。

## 4. 预期收益（每轮运行，deepseek 口径）

| 指标 | 基线 | 预期 | 机制 |
|---|---|---|---|
| u:2#2 fresh | 66.8k | ~46k（**-31%**） | 灭侦察+全量读 -20.6k |
| u:2#2 cache_read | 425k | ~240k（**-43%**） | 68KB 不驻留，后续调用逐轮少背 |
| u:2#2 墙钟 | ~99s+judge | ~45-55s+judge（**-45~50%**） | 灭 43s 读入调用 + 侦察调用 |
| 链式下游冷启动 | #3 80.3k / #4 102.9k | 各 **-~19.6k** | 会话上下文不带 evidence 残留 |
| 全轮合计 | — | fresh **-60k 量级**、cr **-400k 量级** | 本段 + 下游两段 |

护栏：一次通过率不降（材料内容零变更，只是不再重读）；judge 牙齿零变更（判据未动）；
trace 内容质量不降（引用源从「evidence 里找」换「包内已有」，同一文本）。

## 5. 影响面

- `dl_flow_nodes.py`：Step 字段 + u:2#2 置位（注释写明完备性核对结论）
- `scripts/workflow/dl_drive.py`：build_step_prompt 条款（单点）
- `dl_flow_engine.py`：handoff_pack 尾行条件化（需取当前步——按 state 当前节点+子步查
  Step 对象，无则 False 兜底）
- tests：字段默认 False / u:2#2 置位 / 段 prompt 条款有无两态 / 尾行两态 /
  装配不变量（u:2#2 的包须含子1 trace 全文 + PC 子6 statements 全文——防未来 P1-1
  类修剪把材料修没了条款变错）+ 既有全量回归
- 三模式：drive/front 共用段 prompt 单点 ✓；WF_TUI=1（v2 回滚面）无段 prompt 不动
- 在飞工作流：条款只在段 prompt 新加一行，旧实例 resume 自然捡新文案，无迁移面

## 6. 验证计划

1. TDD 红→绿 + 全量 pytest + ruff。
2. **live A/B（dl @ac-deepseek1，同仓新实例 u2_sub2_ab）**：种子 = u2_sub1_ab 的
   evidence（u:1 全 + u:2#1 trace 已在库）从 u:2#2 起跑，跑到 u:2#4 人工收——验收点：
   - u:2#2 段 transcript 零 Read evidence 全量（工具调用核对；对照基线 3 调：ls/wc/Read 68KB）；
   - 逐调用 fresh/cr 与 §1 基线同口径对比；u:2#3/#4 冷启动缩量；
   - 零 block（node_attempts=0）、judge 全 pass、trace 矩阵质量目测不降；
   - u:2#3 基线实测环节（Bash 查 amplitude 报告）数字与今日值 4920.2% 口径核对。
3. AC_WORKFLOW_LAUNCHER 指向本 worktree 的 dl-launch.sh（worktree A/B 驱动两前提之一：
   launcher 与 engine 同树解析）。
4. 验收口径纪律沿用 #22：逐调用前缀读数归因，全轮总账只作参考。
