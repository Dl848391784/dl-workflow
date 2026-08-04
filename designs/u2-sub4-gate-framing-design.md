# u:2 子4（归一化陈述）gate framing 反转设计（v2.88）

> 2026-08-04。§3.5 #28 泛化第八例、#30 playbook 第八次执行：把 u:1#5（v2.85，同属 statements 归一化族、一轮达标）验证过的「默认-PASS framing + 方框化真值判据 + 每条近端双侧钉死」应用到 understand:2#4。与 u:2#3（另一会话并行）无共享文件冲突面：本例只动 u:2 子4 gate + marker pin + replay_u2_sub4.py + README 清单行。

## 0. 本节点结构定位（决定判面怎么切）

| 维度 | 取值 | 后果 |
|---|---|---|
| record_format | **statements**（载荷 `{"text","type_label":must/nice,"boundary"}`，statement_fields=()） | `mech_checks` 循环不执行（#30 ⑰）——压跷跷板出现也**不能**顺手注册 mech_check，须先补 statements 侧注册表（独立项）。本轮预期无跷跷板（判据全结构性，同 u:1#5 ⑱） |
| 内建机械层 | statements 三字段非空（**无条件** JSON 校验）+ 实现侧名词扫描（**可降级**预检，codegraph db 缺失即跳过） | 前者可声明「已机械校验不得 block」；后者**不声明**、保留为方框条款（#30 ⑯，u:1#5 §0.2 同判） |
| gate 长度 | 368 字（从严版） | 短 gate 也 thrash 第六实证（#28：从严 framing 本身即充分致病） |
| 与 u:1#5 差异 | type_label=must/nice 分层（非四态 verdict）；对照基准在**子3**（分层提案+边界）非子4 | 方框一/二判「与子3 逐项一致+传导」，判材=子3+子4 拼合 artifact |

## 1. 基线数据（MiniMax-M3，n=6，现 gate 368 字从严版）

| 载荷 | 期望 | 命中 |
|---|---|---|
| clean（demo 真实子4 qa trace 现代化：qa→statements，分层+边界传导齐备） | PASS | **0/6** |
| vio1 分层不传导（子3 提案 must、陈述标 nice） | BLOCK | 6/6 |
| vio2 边界不传导（抹掉 default 管线+快照限定，称全部管线/实时） | BLOCK | 6/6 |
| vio3 复合句（「以及」连接两个独立目标） | BLOCK | 6/6 |
| vio4 方案动作残留（text 主语=「开发脚本统计…」） | BLOCK | 6/6 |

牙齿 6/6 全是**错理由拦对**（判词主引「管线名=实现侧名词」「复合未拆净」），目标判据被引比例低——从严版牙齿是噪声顺带产物，非判据有效（#28「从严多拦的全是误伤」又一实例）。**回归风险点**：方框四合法化口径限定词后，vio2 的牙齿须靠方框二（与子3 边界对照）接住——v1 验证时重点看 vio2 判词是否真引条款二。

## 1.1 误伤模式聚类（clean 6 轮 + vio 判词逐字）

| # | 模式 | 频次 | 性质 |
|---|---|---|---|
| 1 | 「default 管线」「IC 均值」当实现侧/方案名词 | clean [2][3][5]，vio 侧 10+ 次连带 | **判据词形自坑**（#23 第二变体，u:1#5 聚类1 同族）：「方案名词」操作化清单逐字列了「管线名」，judge 字面适用于数据口径限定词。真实意图=实现机制名词，口径限定词（管线名/指标口径/数据日期）是已证实边界的合法约束成分 |
| 2 | 「能够基于…决定…」状语+主目标当两个独立目标并列 | clean [4][6]，vio2 [1][2][4][5] | 方框条款成新磁铁（#30 ④）：无连接词也判并列 |
| 3 | 发明「子3 价值链/基线测量/nice 空集都要拆出对应陈述或显式留痕」要件 | clean [1][6]，vio2 [4][5][6]，vio3 [5] | judge 发明要件：「逐项一致」被误读成「子3 所有产出维度都要有对应陈述」 |
| 4 | 「无法核验/题目未给出 evidence」存在性幻觉 | clean [3] | v2.34 幻觉族——artifact 即全部判材 |
| 5 | 索取 boundary 含具体数值证据指针（rows=72 等） | vio2 [3] | judge 发明要件，越界索取 |

聚类 1 是最高频且为判据自身词形 → #23 修文本不站队：方框四的操作化清单在本 gate 内局部修正（管线名移出禁用清单、改钉「实现机制名词」），**purpose/selfcheck 的共享操作化文本不动**（surgical；共享文本散布 u:3/u:4/plan 多节点，属各自泛化轮次，u:1#5 §1.2 连带项同判；且 purpose 保守方向无害——模型把口径词挪 boundary 仍过 gate）。

## 2. 设计决策

### 2.1 framing 反转（主杠杆）
「质量判据（从严裁量）」→「默认 pass——仅当以下成立才判 block」+ 方框化 4 条真值判据：
1. 传导断裂·分层不一致（type_label 与子3 提案不一致）
2. 传导断裂·边界超出（抹掉子3 口径限定、改更强断言）
3. 复合未拆（「和/以及/同时/并」连接多个独立目标）
4. 方案动作残留（text 主语/动作=实现动作或实现机制名词）

### 2.2 已机械校验项声明（不可降级项才声明，#30 ⑯）
statements 三字段非空（text/type_label/boundary）= 无条件 JSON 校验 → 声明段。
**不声明**实现侧名词扫描（可降级预检，judge 兜底）→ 保留方框四。

### 2.3 钉死位（§1.1 聚类逐条对位，全部有实证）
| 聚类 | 钉死位 | 层 |
|---|---|---|
| 1 口径限定词当方案名词 | 方框四：管线名移出禁用清单+「数据口径限定词（管线名/指标口径/数据日期/阈值）=已证实边界合法约束成分」 | gate |
| 2 状语当并列 | 方框三：「基于 X 决定 Y」状语结构/约束枚举/修饰成分不算并列——无连接词不得判 | gate |
| 3 索多维产出陈述 | 【合法正例】：子3 目标集几项即几条陈述；价值链/基线/不可量化项=论证材料非目标；nice=无 空集合法 | gate |
| 4 无法核验幻觉 | 【合法正例】：artifact 即全部判材，不得以「看不到 evidence 原文/无法核验」判 | gate |
| 5 索数值指针 | 方框二合法形态：不得要求 boundary 含具体数值证据指针 | gate |

### 2.4 pin 处置（#30 ① 前置审计结果）
| pin | 位置 | 处置 |
|---|---|---|
| `"sub_step==4" in s4.gate and "逐项一致" in s4.gate` | test_dl_flow_engine.py:1215（TestUnderstand2.test_step4_normalization） | 两字面逐字保留（记录存在性子句 + 方框一） |
| purpose needles（原子/去上下文/must/nice/solution-free） | 同上 | purpose 不动（surgical） |
| `test_default_pass_marker_pinned_in_gates` | test:3637 | 加 `s2[3]` 标记 pin |
| **`TestSolutionFreeRuleInGates.test_subject_rule_cited_in_all_five_gates`**（`"主语只许 outcome-level" in gate`） | test:~5095 | **首轮漏网**——pin 审计只 grep 了 gate 文案短语，没 grep 节点坐标/规则常量族；v1 落地后全测试当场逮住。处置：u:2 子4 撤出 `_FIVE_STEPS` 逐字引用族，新增 `test_u2_sub4_refined_rule_pin` 改钉精化条款（「方案动作残留」+「实现机制名词」+「数据口径限定词」）——逐字规则列「管线名」与方框四合法形态直接矛盾，verbatim 引用不可保留（#23）；purpose/selfcheck 的 `_SOLUTION_FREE_SUBJECT_RULE` 模型侧引用不动（双侧钉死意图不丢，u:1#5 §4「常量撤出 gate 时 pin 改钉压缩条款」同范式）。**教训进 #30 ①**：pin 审计除 gate 文案短语外，还须 grep「节点坐标族测试」（`_FIVE_STEPS` 类按坐标枚举的 pin）与规则常量名 |
| Goodhart 守卫（selfcheck 禁含从严裁量等黑盒措辞） | test:~1224 | 新 gate 无禁词；selfcheck 不动 |

在飞 wf 核查：demo(u 子5)、tail_volume(u 子2)，均不在 GoalsAndValue 子4——gate 即改即生效不误伤在飞判断。

## 3. 验证标准（同 #28/#30 ⑥）
三向 × n=6：clean 全 PASS + vio1-4 全 BLOCK（牙齿 <5/6 回炉）+ 既有 pin 测试全绿 + 落地 gate 与重放候选逐字一致。

## 4. 影响面
- `dl_flow_nodes.py`：u:2 子4 gate 改写（≤1 文件段）
- `tests/test_dl_flow_engine.py`：marker pin 加 s2[3]
- `tests/replays/replay_u2_sub4.py`（新增）+ `tests/replays/README.md` 清单加一行

## 5. 迭代实录

| 版本 | gate_len | clean | vio1 分层 | vio2 边界 | vio3 复合 | vio4 方案动作 |
|---|---|---|---|---|---|---|
| 基线（从严） | 368 | 0/6 | 6/6(错理由) | 6/6(错理由) | 6/6 | 6/6 |
| **v2.88（反转+方框化+双侧钉死）** | 1407 | **6/6** | **6/6(对理由)** | **6/6(对理由)** | 6/6 | 6/6 |

**一轮达标，无迭代**（u:1#5 后第二个一轮达标实例；#2-#4/#2#1/#2#2 分别用了 4/3/5/4/5 轮）。
牙齿质量升级：基线 vio 的 6/6 主引错理由（管线名/复合），v2.88 的 6/6 **逐条引对条款**（vio1 全引条款一分层不一致、vio2 全引条款二边界超出、vio3 引条款三、vio4 引条款四）——#28「从严多拦的全是噪声，反转后牙齿反而更稳」第六实证。回归风险点（§1 预判的 vio2 牙齿靠方框二接）成立：vio2 判词全部做了 text vs 子3 边界对照。
一轮达标可归因原因同 u:1#5 ⑱：误伤源是判据自己的词形（管线名/操作化清单字面）而非 judge 发明要件；判据全结构性（传导一致性/连接词/名词位置）；harness 层坑前序例已填平。

## 5.1 落地校验
- 落地 gate 与重放候选 `/tmp/u24_gate_v1.txt` **逐字一致**（`gate.strip()==candidate.strip()` 断言通过；第一次替换丢 `\n` 分歧=逐行字面量隐式拼接不带换行，补 `\n` 转义后一致——替换脚本须显式处理换行，隐式拼接静默吞换行）。
- 721 tests 全绿（720 + 新增 `test_u2_sub4_refined_rule_pin`）；`test_default_pass_marker_pinned_in_gates` 加 `s2[3]`。
- pin 两字面（`sub_step==4`/`逐项一致`）逐字保留。
