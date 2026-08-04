# u:3 子4（归一化陈述）gate framing 反转设计（v2.92）

> 2026-08-04。§3.5 #28 泛化第十例、#30 playbook 第十次执行：把 u:1#5（v2.85）/u:2#4（v2.88，
> 同属 statements 归一化族）验证过的「默认-PASS framing + 方框化真值判据 + 每条近端双侧钉死」
> 应用到 understand:3#4。u:3#1 由并行会话收于 v2.91（已提交）；u:3#2/#3 工作区在飞自称 v2.90
> （提交时再取号）；本例取 v2.92。
> 影响面与并行会话部分共享 dl_flow_nodes.py（子4 段与子2 段不相交），落地用显式清单提交。

## 0. 本节点结构定位（决定判面怎么切）

| 维度 | 取值 | 后果 |
|---|---|---|
| record_format | **statements**（载荷 `{"text","type_label","boundary"}`，statement_fields=()） | `mech_checks` 循环不执行（#30 ⑰）——本轮无压跷跷板需下沉；判据全结构性 |
| 内建机械层 | statements 三字段非空（**无条件** JSON 校验）+ 实现侧名词扫描（**可降级**）+ 子3 ID 传导（**可降级**，子3 无解析 ID 即跳过） | 只声明三字段非空（#30 ⑯）；方案名词/ID 传导保留为方框条款 |
| gate 长度 | 522 字（从严版） | 短 gate 也 thrash 第七实证族（#28） |
| 与 u:2#4 差异 | type_label 域=in/out/已验证/假设+置信度（非 must/nice）；对照基准=子3 范围与约束集（含约束回写叙述） | 方框一须钉死「已验证/假设 与 in/out 边界口径限定」的区分；`_SCOPE_VERB_RULE` 进方框四 |

## 1. 基线数据（MiniMax-M3，n=6，现 gate 522 字从严版）

| 载荷 | 期望 | 命中 |
|---|---|---|
| clean（demo 场景续写：子3 范围集→statements 归一化，传导齐备） | PASS | **0/6** |
| vio1 类型标注不传导（子3 in、陈述标 out） | BLOCK | 6/6 |
| vio2 边界不传导（抹掉快照限定、称全部管线实时） | BLOCK | 6/6 |
| vio3 复合句（「以及」连接两项） | BLOCK | 6/6 |
| vio4 方案动作残留（「开发脚本统计…」） | BLOCK | 6/6 |

牙齿 6/6 多为**错理由拦对**（主引「管线名=方案名词」「q/a 条数=条目数」），目标判据引中率低——从严版牙齿是噪声顺带产物（#28 又一实例）。clean 0/6 误伤判词聚类见 §1.1。

## 1.1 误伤模式聚类（clean 6 轮 + vio 判词逐字）

| # | 模式 | 频次 | 性质 |
|---|---|---|---|
| 1 | 「default 管线」当实现侧方案名词；boundary 含实现指针被连带判 solutioneering | clean 高频 | **判据词形自坑**（#23 第二变体，u:2#4 聚类1 同族）：口径限定词 vs 实现机制名词未分；boundary 是实现指针规定去处仍被判 |
| 2 | 「数量与分布」/「default 管线+快照」当多目标并列 | clean 高频 | 方框条款成新磁铁（#30 ④）：同一项内容列举/修饰成分无连接词也判并列 |
| 3 | 语法主语：「本实例数据范围限定在…」无主语 | clean 一次 | 判据文本「含主语+动词+约束」被字面索取（#23 第二变体，u:1#5 聚类1 同族） |
| 4 | 类型标签置信度误读：「已验证/假设+置信度/in/out」被读成 in/out 也要置信度 | clean 一次 | 判据词形歧义 |
| 5 | 逐项一致误读：子3 双向追溯/约束回写叙述当条目；「子3 有 4 条记录」要求对应陈述 | clean/vio 多次 | judge 用 q/a 条数当条目数，论证材料被当条目 |
| 6 | 边界口径限定当独立约束条目：in[1] boundary 的「快照」被读成 已验证 约束，要求改标已验证或单独成条 | 反转后新暴露 | type_label 域歧义（本节点独有）：范围项边界口径 vs 约束条目未分 |

聚类 1/3 是判据自身词形 → #23 修文本；聚类 5/6 是 本节点特有的 judge 认知面 → 方框内逐条近端钉死 + 合法正例反锚。

## 2. 设计决策

### 2.1 framing 反转（主杠杆）
「质量判据（从严裁量）」→「默认 pass——仅当以下成立才判 block」+ 方框化 4 条真值判据：
1. 传导断裂·类型标注不一致（type_label 与子3 条目编号对应不一致；type_label 与陈述内容方向矛盾；type_label 与 boundary 编号前缀矛盾）
2. 传导断裂·边界超出（抹掉子3 已证实口径限定、改更强断言）
3. 复合未拆（连接词连接多个独立条目）
4. 方案动作残留（text 主语/动作=实现动作/实现机制名词；动词按指向判）

### 2.2 已机械校验项声明（不可降级项才声明，#30 ⑯）
statements 三字段非空（text/type_label/boundary）= 无条件 JSON 校验 → 声明段。
**不声明**实现侧名词扫描（可降级）、子3 ID 传导（可降级）→ 保留为方框条款。

### 2.3 钉死位（§1.1 聚类逐条对位，全部有实证）
| 聚类 | 钉死位 | 层 |
|---|---|---|
| 1 口径限定词/边界指针 | 方框四：数据口径限定词（管线名/指标口径/数据日期/阈值）合法 + boundary 内容不在本判据范围（硬排除） | gate |
| 2 内容列举当并列 | 方框三：「同一项的内容列举（「数量与分布」）」「修饰成分/约束枚举」不算并列，无连接词不判 | gate |
| 3 语法主语 | 形式要件改「对象+动作+约束自包含（中文省略主语合法）」+ 合法正例「不得判缺主语/非陈述式/祈使短语」 | gate |
| 4 置信度误读 | 方框一：「假设条目须含置信度；in/out/已验证 无需置信度，不得索取」 | gate |
| 5 论证叙述当条目 | 方框一/合法正例：「逐项一致=条目编号（in[..]/out[..]/Cx.x）覆盖，双向追溯/约束回写是论证叙述非条目，不得按 q/a 条数核对」 | gate |
| 6 边界口径当约束条目 | 方框一/合法正例：「in/out 范围项的边界口径限定是已证实边界的一部分、不是独立约束条目，不得改标已验证/要求单独成条」 | gate |

purpose/selfcheck 的 `_SOLUTION_FREE_SUBJECT_RULE`/`_SCOPE_VERB_RULE` 模型侧引用不动（surgical）；「主语+动词+约束」词形在 purpose/selfcheck 仍留（u:2#4 同判：语句带主语过 gate 无害，且 #29 跨层同步非本轮阻塞项）。

### 2.4 pin 处置（#30 ① 前置审计结果）
| pin | 位置 | 处置 |
|---|---|---|
| `"sub_step==4" in s4.gate` | TestUnderstand3Orchestration.test_step4_normalization:1304 | 记录存在性子句逐字保留 |
| `"逐项一致" in s4.gate` | 同上 | 合法正例「逐项一致的核对=条目编号覆盖」逐字保留 |
| `test_default_pass_marker_pinned_in_gates` | test:3637 | 加 `s3[3]` 标记 pin |
| `_FIVE_STEPS`（含 ("understand",3,4)，断言「主语只许 outcome-level」in gate） | TestSolutionFreeRuleInGates:5102 | **撤出** u:3#4——逐字规则列「管线名」为禁用与方框四「口径限定词合法」矛盾（u:2#4 同判）；新增 `test_u3_sub4_refined_rule_pin` 改钉精化条款 |
| `test_scope_verb_rule_in_understand3_sub4_gate`（「按指向判」「允许/禁止改动」in gate） | test:5132 | 方框四逐字保留 |
| `test_scope_verb_rule_disclosed_to_model` | test:5137 | purpose/selfcheck 不动 |

在飞 wf 核查：demo（u:2 子5）、tail_volume（u:1 子2），均不在 ScopeAndConstraints 子4——gate 即改即生效不误伤在飞判断。

## 3. 验证标准（同 #28/#30 ⑥）
三向 × n=6：clean 全 PASS + vio1-4 全 BLOCK（判词引对条款，非错理由拦对）+ 既有 pin 测试全绿 + 落地 gate 与重放候选逐字一致。

## 4. 影响面
- `dl_flow_nodes.py`：u:3 子4 gate 改写（≤1 文件段，与并行会话子2 段不相交）
- `tests/test_dl_flow_engine.py`：marker pin 加 s3[3]；`_FIVE_STEPS` 撤 u:3#4；新增 `test_u3_sub4_refined_rule_pin`
- `tests/replays/replay_u3_sub4.py`（新增）+ `tests/replays/README.md` 清单加一行
- `designs/u3-sub4-gate-framing-design.md`：本文档

## 5. 迭代实录

| 版本 | gate_len | clean | vio1 | vio2 | vio3 | vio4 |
|---|---|---|---|---|---|---|
| 基线（从严） | 522 | 0/6 | 6/6(错理由) | 6/6 | 6/6 | 6/6 |
| v1 反转+方框化 | 1663 | 3/6 | **3/6** | 6/6 | 6/6 | 6/6 |
| v2 方框一内容矛盾钉死 | 1983 | 4/6 | 5/6 | 6/6 | 6/6 | 6/6 |
| v3 boundary 硬排除 | 2011 | 4/6 | 6/6 | 6/6 | 5/6 | 6/6 |
| v4 载荷简化（去「与分布」/独立约束） | 2119 | 3/6 | 6/6 | 6/6 | 6/6 | 6/6 |
| v5 边界口径当约束条目钉死 | 2344 | 5/6 | 6/6 | 6/6 | 6/6 | 6/6 |
| **v6 无独立约束条目钉死** | 2414 | **6/6** | **6/6(对理由)** | **6/6(对理由)** | **6/6(对理由)** | **6/6(对理由)** |

**非一轮达标（5 轮迭代）**——u:3#4 是归一化族首个带「已验证/假设」type_label 域的节点（u:1#5/u:2#4 都是 must/nice 二值），judge 在「范围项边界口径 vs 独立约束条目」上的混淆需要逐轮钉死（聚类 6 是反转后新暴露的本节点独有认知面）。载荷也随迭代简化：独立约束陈述（C1.1 快照/H9）与 in 项边界重叠触发 judge 的「重复/复合」误读，最终收敛为「约束折叠进范围项边界口径、不单列约束陈述」= demo 真实子4 同构（u:2#4 S4 单目标 boundary 折约束）。

**牙齿质量**：v6 各 vio 判词逐条引对条款（vio1→判据一/vio2→判据二/vio3→判据三/vio4→判据四），非错理由拦对——#28「反转后牙齿反而更稳」实证族。

## 5.1 落地校验
- 落地 gate 与重放候选 `/tmp/u34_gate_v6.txt` 逐字一致（`gate.strip()==candidate.strip()` 断言通过）
- 全 pytest 绿（728 passed）+ 既有 pin 测试全绿（TestUnderstand3 子4/`test_default_pass_marker_pinned_in_gates`/`TestSolutionFreeRuleInGates`/scope_verb 双测）
- `test_default_pass_marker_pinned_in_gates` 加 `s3[3]`；`_FIVE_STEPS` 撤 ("understand",3,4)；新增 `test_u3_sub4_refined_rule_pin`（钉「方案动作残留/实现机制名词/数据口径限定词/boundary 硬排除」四字面）
- **共享文件提交处置（collab §3.9 #9）**：`dl_flow_nodes.py` 子4 gate 段 + `tests/test_dl_flow_engine.py` pin 与并行 u:3#2/#3 改动同文件，仅先提交 design+replay 两个新文件，共享文件改动留待并行会话收口（commit message 明示）
