# u:3 子2（约束验证标注）gate framing 反转设计（v2.94）

> 2026-08-04。§3.5 #28 泛化例、#30 playbook 例（承接 u:3#1 并行）：
> 把 u:1#1-#5 / u:2#1-#4 验证过的「默认-PASS framing + 方框真值判据 + 每条近端双侧钉死」
> 应用到 understand:3#2（约束验证标注）。

## 0. 本节点与前例的结构差异（决定判面怎么切）

| 维度 | u:1#1-#5 / u:2#1-#4 | **u:3#2** |
|---|---|---|
| record_format | qa（#1-#4）/ statements（#5/子4） | **qa** |
| mech_checks | varies | **无**（基线先判 judge 侧能否稳） |
| artifact 组成 | 单条 / 多步拼合 | **子2 单条 trace**（minor_stage 过滤后无前序拼合；子1 候选清单在 step1.constraint_candidates 跨步，judge 判材内不可见） |
| 命题性质 | 事实性/结构完整性/规范论证 | **混合三态**：已验证=事实性（工具留痕）/ 假设=中间态（置信度+影响）/ 证伪=事实性（证据）--已验证项的「留痕出处」是词形可判子项，假设项的「置信度+影响」是词形可判子项 |
| vio 类型 | 语义+形式混合 | **vio1 编造=形式（无工具动词）+语义残余 / vio2 未验证进约束集=语义（假设未标注）/ vio3 训练记忆冒充=形式（通常/一般来说词形）**--两形式一类语义 |
| gate 长度 | 291–2397 | **244**（最短档；#30「短 gate 也 thrash」第八实证候选） |
| 特殊判据陷阱 | - | **judge 把「工具留痕出处」读成「可核验的完整留痕」**（要 file:line / 完整 stdout / option ID / Read 段落锚点 / 本步新验证）--发明要件族同 u:2#3「可核验性」聚类 |

由此而来的设计约束：

1. **vio 类型判定（#30 ⑫）**：vio1（编造·无工具动词）+ vio3（训练记忆·通常/一般来说）
   均含词形可判子项（工具动词在场 / 通常·一般来说词形在场），vio2（未验证进约束集·假设未标注）
   是语义类（item 是否以约束身份入集且未标假设）。按 ⑫：语义类穷举违规形态为独立 block 条件，
   形式子项评估是否下沉 mech。
2. **「工具留痕出处」措辞歧义**（同 u:2#3 聚类 5 / u:2#1 聚类 2「可核验性」族）：形式要件
   「已验证项附工具留痕出处」被弱 judge 读成「可核验的完整留痕」--clean 的「Read CLAUDE.md §5
   原文『H7：…』」「Bash 实测 `python3 -c …` 输出 True」「AskUserQuestion 选中原话『没有时间压力』」
   均被以「缺 file:line / 缺完整 stdout / 缺 option ID / 非 sub_step==2 工具」为由 block。
   修法=钉死合法留痕形态（#23 修文本不站队）：Read 规范文档 §X 原文引用 / Bash 实测 `命令` 输出 /
   codegraph 断言 / AskUserQuestion 选中原话『…』 / 文件路径 之一在场即合规；禁要求 file:line /
   完整 stdout / option ID / Read 段落锚点 / 「本步新工具留痕」。
3. **硬规则类约束的合法验证源**（purpose 已披露）：「硬规则类约束的合法验证源 = Read 规范文档
   原文引用，禁拿训练记忆冒充」。judge 却对 C1.1/C1.2/C3.2（Read CLAUDE.md 原文）要 Bash 实测
   --须钉「硬规则类 Read 原文即合规，不要求 Bash 实测」。
4. **跨步取证来源复用**：子2 处置子1 候选，引用子1 已取的证（AskUserQuestion 原话/Read 原文）
   即合规；judge 发明「本步须新验证」「时间/权限类应在子1 验证非子2」--须钉「子2 引用子1 取证
   来源即合规，不要求重跑、不要求工具匹配子2 fence_allow」。子1 候选清单的存在与组成非判对象
   （⑧ harness 注 v2.78/v2.79 已全局覆盖跨步幻觉）。
5. **三态「无遗漏」≠「三态都出现」**：形式要件「逐条三态处置（无遗漏）」=每个候选各归一态、
   不漏判；不要求三种态都出现（无假设/无证伪候选时该态不出现=正常）。judge 把「缺假设项/缺证伪项」
   当违规（vio2[2][4]）--须钉「不要求三态都出现」。

## 1. 基线数据（MiniMax-M3，n=6，现 gate 244 字从严版）

| 载荷 | 期望 | 命中 |
|---|---|---|
| clean（demo 因子 IC 统计场景，C1.1-C4.2 八条已验证附 Read/Bash/AskUserQuestion 留痕 + 推测项一条假设附置信度+影响） | PASS | **0/6** |
| vio1 编造（C2.1/C2.2 裸声明「口径为 ic_mean/满足口径」无工具留痕） | BLOCK | 6/6 |
| vio2 未验证进约束集（推测项未经核实即纳入约束集、未标假设） | BLOCK | 6/6 |
| vio3 训练记忆冒充（C1.1/C1.2「通常/一般来说」断言代替 Read 原文） | BLOCK | 6/6 |

**基线判读**：牙齿 100%（3/3 vio 全 6/6），clean 0/6 全误伤。244 字最短档 gate 仍 thrash--
从严 framing 本身即充分致病（#28 第八实证，u:2#3 291 字/u:2#4 368 字后更短 gate 仍误伤）。
同 u:2#3 判读：**误伤全是 clean 侧从严 framing 发明要件**（要可核验完整留痕），vio 全 6/6 judge
侧稳。主杠杆=framing 反转 + 近端双侧钉死合法留痕形态。

### 1.1 误伤模式聚类（clean 6 轮判词逐字）

| # | 模式 | 判词摘录（逐字） | 性质 |
|---|---|---|---|
| 1 | **AskUserQuestion 原话不算 verified 出处** | [1]「C4.1/C4.2「AskUserQuestion 选中」无工具留痕出处，模型本轮不可用此类调用作为 verified 出处（沙箱无 AskUserQuestion 工具调用记录）」[3]「本步子步骤2 的执行工具列仅为 Bash/Read/CodeGraph，未出现 AskUserQuestion 工具留痕」 | judge 发明要件（要工具调用记录/option ID；要工具匹配子2 fence） |
| 2 | **Read 规范原文不算工具留痕** | [2]「C3.2 仅引用 CLAUDE.md §3 原文…无工具实测留痕，属编造」[5]「未提供具体工具留痕出处（文件路径/Bash命令完整文本/Read目标段落锚点）」 | judge 发明要件（硬规则类要 Bash 实测；要 file:line/段落锚点） |
| 3 | **Bash 实测 命令+输出值不够** | [5]「形式上仅为转述，达不到「工具留痕出处」从严要求」 | judge 发明要件（要完整 stdout/完整命令文本） |
| 4 | **子2 须新验证、不得复用子1 来源** | [4]「属子1 候选条目而非本步新验证；判据要求本步 sub_step==2 须附工具留痕出处」 | judge 发明要件（要本步新工具留痕/重跑） |
| 5 | **跨步一致性发明** | [3]「时间/权限类约束按前序应在子1 已用 AskUserQuestion」 | judge 跨步幻觉（⑧ 族：子1 候选应在子1 验证） |
| 6 | **原话误读为未给** | [6]「原话未给出（仅写'AskUserQuestion 选中原话'，未附实际原话内容…）」 | judge 误读（原话『没有时间压力』在场）+ 发明 file:line |

6 类全从严 framing 下 judge 把「工具留痕出处」读成「可核验完整留痕」+ 跨步发明，与 u:2#3
「可核验性」族同根因。误伤源=judge 发明要件（要可核验细节）为主--非纯词形可改根除，但合法
留痕形态词形明确（Read 原文/Bash 实测/AskUserQuestion 原话/工具动词在场），预期 framing 反转
+ 合法形态钉死即治 clean（同 u:2#3 v1 一轮治 clean）。

### 1.2 载荷缺陷自审（#30 ⑦，先于 gate 迭代修）

- vio1（C2.1/C2.2 裸声明无留痕）与 vio3（C1.1/C1.2 通常/一般来说）共享「已验证项无工具留痕」
  判定面，但文本可区分：vio1=裸结论无工具动词（「口径为 ic_mean」），vio3=训练记忆常识断言
  （「通常…」）。两者牙齿 6/6 维持。vio3 判词另引「训练记忆冒充」条款（正确），vio1 判词兼引
  「编造」+误引「训练记忆冒充」（vio1 无通常/一般来说词形，属判词理由不精确但 block 正确）。
- vio2（推测项纳入约束集）判词主引「未验证直接进约束集」+ 误引「缺假设项」（三态不齐）。
  block 正确，理由部分误引。载荷集无修正项。

## 2. 设计决策

1. **framing 反转**：默认 pass + 明列 block 条件（「默认 pass」字面触发 run_judge 双态同向指令行，
   v2.76 单源）。
2. **合法留痕形态钉死（聚类 1-4，#23 修文本不站队）**：形式要件「已验证项附工具留痕出处」->
   钉死合法留痕形态：Read 规范文档（CLAUDE.md/PROJECT.md/MODULE.md）§X 原文引用 / Bash 实测
   `命令` 输出 / codegraph 断言 / AskUserQuestion 选中原话『…』 / 文件路径 之一在场即合规；
   硬规则类 Read 原文即合规（不要求 Bash 实测）；子2 引用子1 取证来源即合规（不要求重跑、
   不要求工具匹配子2 fence_allow）；禁要求 file:line / 完整 stdout / option ID / Read 段落锚点 /
   「本步新工具留痕」。
3. **方框判据（语义类穷举 + 形式类正面退路）**：
   - 一、编造：已验证项答案无工具留痕出处（无 Read 原文/Bash 实测/codegraph/AskUserQuestion 原话/
     文件路径 任一，仅裸结论）判 block；上列任一在场即合规（不要求可核验细节）。
   - 二、未验证直接进约束集（假设未标注）：未经核实的候选以约束身份进入约束集、未标
     「假设+置信度+影响」判 block；未低成本验证的候选标「假设·置信度·错误时影响」留子5 用户
     裁决=合规；证伪项附证据剔除=合规；不要求三态都出现（每候选各归一态、无遗漏即合规）。
   - 三、训练记忆冒充项目事实：「通常」「一般来说」「一般是」式常识断言无本地留痕判 block；
     Read 规范原文/Bash 实测/codegraph 断言=本地留痕合规。
4. **【关键】工具留痕的判据语义**：不得以「留痕不可核验/缺 file:line/缺完整 stdout/缺 option ID」
   block 已附 Read 原文/Bash 实测/AskUserQuestion 原话的 trace（聚类 1-3、6）；不得以「子2 须新
   验证/工具不匹配子2 fence」block 引用子1 取证来源的 trace（聚类 4、5）。
5. **【合法正例】**：demo clean 形态逐条对应误判类（Read CLAUDE.md §5 H7 原文合规 / Bash 实测
   `python3 -c` 输出 True 合规 / AskUserQuestion 选中原话『没有时间压力』合规 / 子1 推测项标假设
   附置信度+影响留子5 合规），方框以外一律不判。
6. **前序锚点**：子1 候选清单（step1.constraint_candidates）的存在与组成不作 block 依据（judge
   只判子2 trace 的三态处置质量）。engine 注 v2.78/v2.79 已全局覆盖，gate 内轻量提示即可。
7. **mech 下沉预案（#30 ⑤/⑭，单变量迭代 ⑪）**：vio1（编造·无工具动词）是词形可判子项，同
   u:2#3 ㉗--默认-PASS framing 下 judge 侧可能不主动查（u:2#3 v1 vio2 6/6->0/6 实证）。先跑
   reversal-only（v1），若 vio1 牙齿崩（<5/6），下沉 `constraint_verification_tool_trace` mech
   （扫「已验证」项答案的工具动词/原文引用在场，无则当场拒；mirror _check_baseline_tool_trace
   但触发条件=「已验证」in a，非「基线」in q），gate 声明「已验证项工具留痕已机械校验、不得以此
   block」。vio3（通常/一般来说）同理评估。

## 3. 验证记录（迭代实录）

| 版本 | gate_len | clean | vio1 编造 | vio2 未验证 | vio3 训练记忆 |
|---|---|---|---|---|---|
| 基线（从严） | 244 | 0/6 | 6/6 | 6/6 | 6/6 |
| v1（reversal-only，gate_file） | 1387 | 6/6 | 1/6 | 4/6 | 6/6 |
| v2（+ constraint_verification_tool_trace mech 下沉 vio1/vio3 + 方框二 pin，live gate） | 1388 | 6/6 | 0/6(设计内) | 6/6 | 5/6(设计内) |

### v1 关键现象与教训

1. **framing 反转即治 clean**（0/6->6/6，一轮）：6 类误伤全从严 framing 发明要件
   （要可核验完整留痕），反转+合法形态钉死后全灭--同 u:2#3 v1。
2. **vio1 崩 6/6->1/6（压跷跷板 ⑤/⑭）**：默认-PASS framing 下 judge 不主动查工具动词
   在场（5/6 空判词 rubber-stamp），同 u:2#3 ㉗--「已验证项无工具留痕」是词形可判子项，
   下沉 mech 零方差生产墙。vio3（通常/一般来说）同族（无工具留痕）一并被 mech 拦。
3. **vio2 4/6（<5/6 回炉）**：judge 注意力方差（2/6 空判词），方框二 pin 强化后 v2 达 6/6。

### v2 关键现象与教训

1. **mech `constraint_verification_tool_trace`（mirror baseline_tool_trace）**：扫
   「已验证：」处置项（跳过汇总「八条已验证」）的工具动词在场；无工具动词=当场拒。
   关键词刻意排除裸名词「路径」（vio3「管理路径」会误放行）。离线三向验证：clean
   过 / vio1 拒 / vio2 过（交 judge 方框二）/ vio3 拒。
2. **mech 下沉后 judge 侧变化**：方框一声明「已验证项工具留痕已机械校验--无工具留痕
   的已验证项已被当场拒、不会到你这里」，judge 不再判工具留痕（编造+训练记忆冒充
   一并委托 mech）。vio1/vio3 judge-only 读数 0-5/6=设计内（生产里到不了 judge，
   ㉗ 同族）。vio2 由 judge 方框二判（未验证进约束集，假设未标注）。
3. **vio2 6/6（方框二 pin 强化）**：明列「纳入约束集/作为约束/列入约束」式行为规定
   + 未标假设 为 block 触发词形，judge 6/6 命中。

## 4. 验证标准（同 #28/#30）

三向 × n≥6：clean 全 PASS + vio1-3 全 BLOCK（牙齿 <5/6 回炉）+ 既有 pin 测试全绿
（test_step2_verify_three_states_and_fence / test_default_pass_marker_pinned_in_gates）。
engine 注 v2.78/2.79 未变，回归 u:1#1-#5 + u:2#1-#4 + u:3#1 不受影响。

## 5. 影响面

- `dl_flow_nodes.py`：u:3 子2 gate 改写 + 注释考古（v2.94）；mech_checks 注册；selfcheck 跨层同向按需
- `dl_flow_engine.py`：（条件触发）`_check_constraint_verification_tool_trace` + `_MECH_QA_CHECKS` 注册
- `tests/test_dl_flow_engine.py`：`test_default_pass_marker_pinned_in_gates` 加 u:3 子2 pin（若该测试按坐标枚举）
- `tests/replays/replay_u3_sub2.py`（已建，内嵌载荷，不读 evidence 行号）
- `tests/replays/README.md`：清单加一行
- `designs/u3-sub2-gate-framing-design.md`：本文档

## 6. 环境教训

- 复用 `tests/replays/replay_u3_sub1.py` 范式（同节点 understand:3）：`.token` 无条件优先于 env
  （v2.86 已正治进 _common.py）、provider 三件套硬赋值、n=6。
- artifact=子2 单条 JSON（生产 read_evidence_for_step(2,"ScopeAndConstraints") 同形）；
  子1 候选清单跨步，judge 判材内不可见=判据须钉「不判子1 完整性」。
- clean 载荷承接 u:3#1 的子1 候选（C1.1-C4.2 + 推测项），保证节点间连续性。
