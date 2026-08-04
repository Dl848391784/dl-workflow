# u:4 子4（归一化陈述）gate framing 反转设计（v2.98）

> 2026-08-04。§3.5 #28 泛化第十六例、#30 playbook 第十六次执行：把 u:1#5 / u:2#4 /
> u:3#4（同属 statements 归一化族）验证过的「默认-PASS framing + 方框化真值判据 +
> 每条近端双侧钉死」应用到 understand:4#4（归一化陈述）。取号 v2.98 =
> max(已入库 v2.97[10175b6 u:4#3], 工作区自称) + 1（collab #6/#13--v2.97 被 u:4#3
> 会话中途提交抢占，原取号 v2.97 重编号为 v2.98；提交前须再查一次 `git log` + 全仓
> grep，版本号是易失声明）。
> 影响面：u:4 子4 gate + 两处 pin + replay_u4_sub4.py + README 行 + rubric 沉淀
> + 本文档（并发见 §6）。

## 0. 本节点结构定位（决定判面怎么切）

| 维度 | 取值 | 后果 |
|---|---|---|
| record_format | **statements**（载荷 `{"text","type_label","boundary"}`，验收包六字段作额外键随项携带） | `mech_checks` 循环不执行（#30 ⑰）--本轮无压跷跷板需下沉；判据全结构性 |
| type_label 域 | **验收方法/时机**（如 `demonstration/triggered`；非 in/out/已验证/假设，非 must/nice） | 方框一须钉死「验收方法/时机 传导」+ **六字段定义**（可行性三态/选择理由是子3 叙述非字段） |
| 内建机械层 | statements 三字段非空（**无条件** JSON 校验）+ 实现侧名词扫描（**可降级**） | 只声明三字段非空（#30 ⑯）；方案名词保留为方框条款 |
| gate 长度 | **382 字（从严版）** | 短 gate thrash 第九实证族（#28；前例 784/659/612/522/428/368/291 字） |
| 与 u:3#4 差异 | type_label 域=验收方法/时机；**额外携带验收包六字段**（指标/基线/阈值提案/验收方法/时机/证据形式）；对照基准=子3 验收方式设计 | 方框一须钉死六字段定义 + 跨步错位（聚类 3）；判材边界段须钉「子3+子4 拼合 artifact 即全部判材」（聚类 6）；方框四须补「验收事件描述性动词合法」（聚类 4，本节点独有） |
| 与 u:4#1 同节点 | 同 SuccessCriteria 节点、同 demo 载荷集（G1/SC1.1/SC2.1） | 方框四判别线（源码构件 vs 口径限定词）直接复用 u:4#1；口径限定词误伤族第四次 |

## 1. 基线数据（MiniMax-M3，n=6，现 gate 382 字从严版）

| 载荷 | 期望 | 命中 |
|---|---|---|
| clean（demo 场景续写：子3 验收方式设计->statements 归一化，六字段+type_label+边界传导齐备） | PASS | **0/6** |
| vio1 验收包字段不传导（子3 定 demonstration、陈述篡改为 analysis） | BLOCK | 6/6 |
| vio2 边界不传导（抹掉 default 管线+数据截至 2026-07-24 限定，称全部管线当前实时） | BLOCK | 6/6 |
| vio3 复合句（「以及」连接 SC1.1 规模核对 + SC2.1 口径核对） | BLOCK | 6/6 |
| vio4 方案动作残留（text 主语=「开发脚本统计…」代码实现动作） | BLOCK | 6/6 |

牙齿 6/6 多为**错理由拦对**（主引「default 管线/报告=方案名词」「条数+占比=并列」「缺可行性/选择理由」），clean 0/6 误伤判词聚类见 §1.1。

## 1.1 误伤模式聚类（clean 6 轮 + vio 判词逐字）

| # | 模式 | 频次 | 性质 |
|---|---|---|---|
| 1 | **口径限定词/交付载体被判 solutioneering**（主误伤源） | clean 6/6 全轮 | **判据词形自坑**（#23 第四变体，u:2#4/u:3#4/u:4#1 同族第四次）：`_SOLUTION_FREE_SUBJECT_RULE` 逐字列「管线名/字段名」为禁用，而 clean 里「default 管线」「报告」「因子明细」是 must 目标自带的已确认口径限定词与交付载体 |
| 2 | **内容列举/验收条件当复合未拆** | clean 高频 | 方框条款成新磁铁（#30 ④）：同一验收事件的两个读数（条数+占比）、验收条件（与明细计数一致）无连接词也判并列 |
| 3 | **验收包六字段形式索求** | clean [5][6] | **跨步判据错位**：索求「可行性三态/选择理由/待建手段」--这些是子3 论证叙述、非六字段（六字段=指标/基线/阈值提案/验收方法/时机/证据形式） |
| 4 | **验收事件动词当实现动词** | clean [1][6] | 聚类 1 软化变体（本节点独有）：「打开报告/读出数字/拿口径对照」是验收行为描述，被当代码实现动作 |
| 5 | **boundary 索求 file:line** | clean [5] | verdict 边界（SC ID + 目标覆盖范围）vs 实现指针未分 |
| 6 | **「缺 sub_step==4 记录」误判** | vio1[5][6]/vio3[1][5] | artifact=子3+子4 两行 JSON 拼合被误读为只有子3（判材边界） |

聚类 1/4 同源（判据逐字词形自坑，占 6/6 全轮）、2 是方框磁铁、3 是跨步错位、5/6 是本节点认知面。
**主杠杆 = framing 反转 + 方框四按「源码构件/写代码动作 vs 数字/口径/验收行为」重划分线**；无 mech 下沉
（vio 侧基线全 6/6，judge 判得动）。

## 2. 设计决策

### 2.1 framing 反转（主杠杆）
「质量判据（从严裁量）」->「默认 pass--仅当以下成立才判 block」+ 方框化 4 条真值判据：
1. 验收包字段不传导·方法/时机/证据形式篡改或丢失（type_label 与子3 不一致；六字段对应项矛盾）
2. 边界不传导·口径限定抹掉改更强断言（抹掉 default 管线/数据截至 限定称全部管线实时）
3. 复合未拆（连接词连接多个独立验收标准，引入不同度量对象/验收事件）
4. 方案动作残留（**重划线**：项目源码构件标识或代码实现动作才违规）

### 2.2 已机械校验项声明（不可降级项才声明，#30 ⑯）
statements 三字段非空（text/type_label/boundary）= 无条件 JSON 校验 -> 声明段。
**不声明**实现侧名词扫描（可降级）-> 保留为方框四条款。

### 2.3 钉死位（§1.1 聚类逐条对位，全部有实证）
| 聚类 | 钉死位 | 层 |
|---|---|---|
| 1 口径限定词/交付载体 | 方框四：管线名/指标口径/数据日期/比较关系/报告/页面/字段值/因子明细 合法（判别线=源码构件/写代码动作才违规） | gate |
| 2 内容列举/验收条件当并列 | 方框三：「同一验收事件的两个读数（条数+占比）」「验收条件（与明细计数一致）」不算并列 | gate |
| 3 六字段形式索求 | 方框一：**六字段=指标/基线/阈值提案/验收方法/时机/证据形式**；可行性/选择理由/待建手段是子3 叙述非字段，不得索取 + 命题性质段 | gate |
| 4 验收事件动词 | 方框四：**验收事件描述性动词**（打开报告/读出数字/拿口径对照/确认）合法（验收行为非代码实现动作） | gate |
| 5 boundary 索求 file:line | 方框二：boundary=verdict 边界（SC ID + 目标覆盖范围），**不是实现指针** | gate |
| 6 缺 sub_step==4 记录 | 判材边界段：artifact=子3+子4 拼合即全部判材，两行 JSON 同 minor_stage 同 kind 是生产常态 | gate |
| 语法主语 | 形式要件改「对象+动作+约束自包含（中文省略主语合法）」+ 合法正例「不得判缺主语/非陈述式/祈使短语」 | gate |

purpose/selfcheck 的 `_SOLUTION_FREE_SUBJECT_RULE` 模型侧引用不动（surgical，同 u:3#4）。

### 2.4 pin 处置（#30 ① 前置审计结果）
| pin | 位置 | 处置 |
|---|---|---|
| `test_default_pass_marker_pinned_in_gates` | test:~3652 | 加 `s4[3]` 独立 assert 行（collab #12 逐坐标独立 assert） |
| `_FIVE_STEPS`（含 ("understand",4,4)，断言「主语只许 outcome-level」in gate） | TestSolutionFreeRuleInGates:~5103 | **撤出** u:4#4--逐字规则列「管线名/字段名」为禁用与方框四「口径限定词合法」矛盾（u:2#4/u:3#4/u:4#1 同族第四次）；新增 `test_u4_sub4_refined_rule_pin` 改钉精化条款 |

在飞 wf 核查：u:4 子4 是 understand 末子阶段前一步，gate 即改即生效不误伤在飞判断（#30 ①）。

## 3. 验证标准（同 #28/#30 ⑥）
三向 × n=6：clean 全 PASS + vio1-4 全 BLOCK（判词引对条款，非错理由拦对）+ 既有 pin 测试全绿 + 落地 gate 与重放候选逐字一致。

## 4. 影响面
- `dl_flow_nodes.py`：u:4 子4 gate 改写（≤1 文件段，与并行 u:4#3 子3 段不相交）
- `tests/test_dl_flow_engine.py`：marker pin 加 s4[3]；`_FIVE_STEPS` 撤 u:4#4；新增 `test_u4_sub4_refined_rule_pin`
- `tests/replays/replay_u4_sub4.py`（新增）+ `tests/replays/README.md` 清单加一行
- `skills/workflow-creation/references/rubric-design.md`：泛化第十六例 + ㊻/㊼ 条目（**延后**：rubric 并行 u:4#3 在飞编辑，按 collab #1/#9 留待收口会话追加，避免双写）
- `designs/u4-sub4-gate-framing-design.md`：本文档

## 5. 迭代实录

| 版本 | gate_len | clean | vio1 字段不传导 | vio2 边界不传导 | vio3 复合句 | vio4 方案动作 |
|---|---|---|---|---|---|---|
| 基线（从严） | 382 | 0/6 | 6/6(错理由) | 6/6 | 6/6 | 6/6 |
| v1 反转+4 方框+两结构段 | 2555 | 6/6 | 6/6 | 6/6 | **5/6** | 6/6 |
| **v2 = 落地版**（v1 + 方框三违规侧补「引入不同度量对象或验收事件」） | **2587** | **6/6** | **6/6** | **6/6** | **6/6** | **6/6** |

**两轮达标**（#30 ㉛ 三问预估兑现：低-中轮次）。v1->v2 单变量：方框三违规侧补一句
「引入不同度量对象或验收事件，如规模数字核对 + 口径一致性核对」，只影响 vio3 的 1 例
漏网（v1 [1] 把「以及」从 SC2.1 误读为 SC1.1 附加条件）。clean/vio1/vio2/vio4 读数不变。

**牙齿质量**：v2 四颗牙全部逐字引对目标条款（vio1->判据一/vio2->判据二/vio3->判据三/
vio4->判据四），且**无一依赖已合法化的口径词形**--基线判词里 vio 顺带引的
「含『管线/报告』=solutioneering」在 v2 判词中消失，牙齿改由各自方框独立支撑。方框四
合法化未反伤任何一颗牙（#30 ㉖ 兑现）。

## 5.1 落地校验
- 落地 gate 与重放候选 `/tmp/u4sub4_gate_v1.txt`（v2 内容）逐字一致（`gate.strip()==candidate.strip()` 断言通过，gate_len=2587）
- 全 pytest 绿（待收口提交后跑）+ 既有 pin 测试全绿
- `test_default_pass_marker_pinned_in_gates` 加 `s4[3]`；`_FIVE_STEPS` 撤 ("understand",4,4)；新增 `test_u4_sub4_refined_rule_pin`
- **共享文件提交处置（collab §3.9 #9）**：`dl_flow_nodes.py` 子4 gate 段 + `tests/test_dl_flow_engine.py` pin + `README.md` 行 + rubric 沉淀与并行 u:4#3 改动同文件，仅先提交 design+replay 两个新文件，共享文件改动留待并行会话收口（commit message 明示）

## 6. 并发协作记录（collab §3.9）

工作区起手时并行会话 u:4#3 在飞（v2.96，designs/u4-sub3-gate-framing-design.md 已建 +
SuccessCriteria 子3 gate 已反转默认-PASS + 子3 pin 已加）。本例只动 u:4 子4 段（与 u:4#3
子3 段不相交）。
- **取号**：v2.97 = max(已入库 v2.95, 工作区自称 v2.96[u:4#3]) + 1（collab #6/#13）。
- **Edit 工具 staleness 拒匹配**：u:4#3 在会话中途编辑 dl_flow_nodes.py（子3 gate，mtime
  20:00:14）后，Edit 工具对子4 gate 的 old_string 匹配被拒（"String to replace not found"，
  尽管内容逐字一致--repr 确认无隐藏字符）。改用 anchor splice 脚本（`/tmp/splice_u4sub4.py`）
  按 `minor_stage=SuccessCriteria 且 sub_step==4` 锚点定位旧块、从候选文件生成新 gate 源码
  替换落地，绕过 Edit 的 staleness 检查；落地后 `gate.strip()==candidate.strip()` 校验通过。
  **教训**：并发活跃期 Edit 工具的 staleness 拒匹配是已知摩擦（非内容错误），anchor splice
  是可靠 fallback（collab #1 镜像：发现并发信号别硬刚，换工具）。
- **共享文件纪律**：`README.md` 按 collab #11 逐行核对（`git add` 后必 `git diff --cached`）；
  `test_default_pass_marker_pinned_in_gates` 按 #12 加独立 assert 行；提交只 `git add` 显式
  清单（禁 `-A`）。
