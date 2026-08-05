# plan:4 子1（四源清点）gate framing 反转设计（v2.115）

> 2026-08-05。§3.5 #30 泛化第三十二例、#30 playbook 第三十二次执行：把「默认-PASS
> framing + 方框化真值判据 + 每条近端双侧钉死」应用到 plan:4#1（四源清点与追溯
> 基线）。
> **plan:4（制定执行计划和检查点）首个反转节点**。用户坐标指令「plan:3#4 正在进行
> 泛化处理，请继续泛化 plan:4#1，记得跑 case 做测试，用 worktree 隔离开发」。
> 版本号：起手取 v2.110=max(入库 v2.109[plan:2#4])+1（collab #20 双查：全仓 grep
> 含 untracked 自称最高 v2.109；plan:3#3/#3#4/#4#2 三并行会话起手无自称文件）；
> **多会话并行期号连涨**（collab #25/#27），本会话开发期间 plan:3#3/plan:4#2/plan:3#4
> /plan:4#4/plan:4#3 陆续入库 v2.110-v2.114（plan:4#2/#4#3/#4#4 均为兄弟节点）。首提
> v2.113/第三十例，**merge 后复核发现与 plan:4#4 撞号**（plan:4#4 归一化计划包先提
> 3983e5c=v2.113/第三十例），顺延 **v2.115**=max(入库 v2.114[plan:4#3])+1（collab
> #13/#25 撞号顺延，先提交者回避，重编号成本低=design头+replay docstring+code 注释
> 文本替换）。例数=泛化第三十二例。

## 0. 本节点结构（决定判面怎么切）

| 维度 | 值 |
|---|---|
| record_format | qa（无 statements 归一化族问题） |
| mech_checks | 无 -> v1 重放后下沉 epc_quote_trace（方框四原文引用，同 plan:2#1/plan:3#1 范式） |
| artifact 组成 | **子1 单条 trace**（生产 read_evidence_for_step(1,"ExecutionPlanCheckpoints") 同形--本节点首步，minor_stage 过滤后无前序拼合） |
| 输入锚 | **design.md + plan.md + understand.md（主仓 .md 文件）+ evidence plan:1/2/3 前序 trace**--evidence 只含 ExecutionPlanCheckpoints 段，四源 judge 结构性读不到（四重判材不可见，与 plan:2#1/plan:3#1 同构--输入锚从单/双源扩为四源聚合） |
| 命题性质 | **保真转换**（从四源提取控制结构输入五类清单到 control_baseline）--「从有到有时的失真与虚构」，与 plan:2#1/plan:3#1 同族（同「有中生乱虚构」主敌），首个四源聚合节点（execution-plan-checkpoints-substeps-design §1.2 关键不对称第八种） |
| vio 类型 | vio1 清单项无出处（编造）/ vio2 静默新增（二次创作）/ vio3 改写失真（聚合失真/语义偏移）/ vio4 原文未引用（判材边界）/ vio5 漏源（五类缺类致四源之一无条目）--四 vio 与 plan:2#1/plan:3#1 一一同构 + plan:4 专属漏源 |
| gate 长度 | 基线 514 字--短 gate thrash 候选（前例 534/422/392 等；短 gate 从严 thrash 第十三实证） |

**与 plan:2#1/plan:3#1 的设计复用度极高**（同构保真基线节点，清点基线族第三例）：
判据一(a/b) 双形态穷举、判据二改写失真三维对照（操作对象/性质/产出物）、判据三/四
原文引用下沉 mech、【判材边界】跨阶段文件输入、【合法正例】结构全部复用--本设计
只记录 plan:4#1 **特有的**判面差异（四源聚合的 evidence 复合源枚举完备性歧义 +
漏源条件 + 验收包六字段完备性歧义）与迭代过程。

## 1. 基线数据（MiniMax-M3，n=6，现 gate 514 字从严版）

| 载荷 | 期望 | 命中 |
|---|---|---|
| clean（四源五类清单齐备：①任务 DAG[plan.md T1->T2->T3+阶段分组] ②能力绑定[plan.md factor-development+H15 codegraph+TDD] ③验收包[understand.md SC1.1/SC2.1 triggered 落点] ④假设汇总[design.md H1+evidence plan:1] ⑤不可逆操作[plan.md git push 外发]；每条附源出处+四源原文『』引用；新增候选：显式『无』；只提取不创作） | PASS | **0/6** |
| vio1 清单项无出处（五类全裸，「按四源常规结构可知」凭印象） | BLOCK | 6/6 |
| vio2 静默新增（①②③④正常，⑤=「删除旧报告目录」裸，a[1] 仍声明「新增候选：无」） | BLOCK | 6/6 |
| vio3 改写失真（①引原文『增加分组键』却自述「重写 _aggregate_positive_ic 为独立分组引擎」） | BLOCK | 6/6 |
| vio4 原文未引用（五类只列条目+出处行号，无任何『』引用） | BLOCK | 6/6 |
| vio5 漏源（五类缺③验收包整类，understand.md 无条目且无说明） | BLOCK | 6/6 |

**判读**：514 字短 gate clean 0/6 = 短 gate thrash 第十三实证；vio 牙齿全 6/6 =
㉛ 问三「牙齿全满->judge 判得动，误伤纯 framing 致病」--反转即治。但 vio1/vio2/vio3
判词多引「原文未引用」过判词形（非各自专属判据）--「原文未引用」条件过宽吞干净
净+ vio，反转后方框四须靠 mech + 判材边界双侧钉死收窄。

### 1.1 误伤模式聚类（clean 6 轮判词逐字）

| # | 模式 | 判词摘录（逐字） | 性质 |
|---|---|---|---|
| 1 | **『…』片段引用不算，要整段** | [1]「a 段各条仅贴一句『原文摘录』短句，未把原文整段或关键句整段引用进 trace 正文（仅节选标签式短句不构成引用核验基线）」[2]「仅以单引号片段形式引用…不构成引用」[5]「仅出现『原文『……』』单条短引，无 trace 正文层面的原文完整引用」 | judge 发明要件（同 plan:2#1/plan:3#1 聚类：『…』摘要不是逐字整段引用） |
| 2 | **evidence plan:1/2/3 要全引用（复合源枚举完备性歧义）** | [3]「缺「plan:2/3 trace」原文引用进 trace 正文…evidence plan:2/3 trace 的内容未在 trace 正文显式引用」[4]「evidence plan:2 与 plan:3 trace 未显式纳入也未声明无关联来源…未引用即漏源」 | judge 发明要件（**plan:4 专属**：把四源里的 evidence 拆成 plan:1/2/3 三个全要求--evidence 是复合源，枚举完备性歧义族，同 plan:3#1 操作类型六类全谱系变体） |
| 3 | **每子项每属性都要引用原文** | [5]「①阶段分组引用 plan.md:12 一处未覆盖到「阶段分组=实现阶段/验证阶段」原句；②能力绑定仅引用 plan.md:18 一句…未引用 H15 codegraph 留痕与 superpowers TDD 的对应原文」 | judge 发明要件（每属性逐个原文，#23 枚举变体第三实例） |
| 4 | **误读有引用为无引用（注意力方差）** | [6]「③ understand.md、⑤ plan.md 未引原文进 trace 正文」（实际 ③⑤ 均有『』引用） | ㉖ 注意力方差（clean 载荷明明有引用，judge 误读为无） |

4 类误伤全是 **judge 发明「整段引用 / evidence 全引用 / 每属性原文」要件**--形式
要件「四源原文引用进 trace 正文」被 judge 反读成**逐源逐属性逐段全引用要求**（㉓
block 条件否定措辞反读的枚举变体）。预期 framing 反转 + 判材边界钉死「evidence
复合源任一引用即合规 / 不要求每属性原文 / 『…』片段合法」即治 clean。聚类 2 是
plan:4#1 专属判面（plan:2#1/plan:3#1 的输入锚是单/双 .md 文件，无 evidence 复合
源枚举歧义）。

## 2. 反转后的判据设计（默认-PASS framing）

结构：形式要件（保留 _EPC_STEP1_FORM_REQUIREMENTS）+ 默认 pass 声明 + **四方框**
（复用 plan:2#1/plan:3#1 判据一(a/b)/二/三结构 + plan:4 专属漏源方框三）+
【判材边界】段（钉死 evidence 复合源 / 每属性 / 验收包六字段 / 『…』片段四枚举
完备性歧义）+ 【合法正例】段。

- **方框一·清单来源自证不足（编造/静默新增）**：(a) 全清单裸=编造（「按四源常规
  结构可知…按常规路径可查」类凭印象）；(b) 个别条目裸且未标新增候选=静默新增
  （「新增候选：无」声明下清单含无出处无原文引用的新增条目，如「删除旧报告目录」
  类四源没有的对象）。合法形态=源文件+行号 / 『原文』引用 任一在场即合规。
- **方框二·改写失真（聚合失真/语义偏移）**：自述措辞 vs 引用的原文『…』三维对照
  （操作对象/性质/产出物任一明显变化判 block）；block 面前置载荷同形逐字实例
  （T1 自述「重写 _aggregate_positive_ic 为独立分组引擎」vs 原文『增加 FACTOR_
  CATEGORIES 维度分组键』）；合法形态=忠实提取/适度压缩/适度具体化（点明原文未
  点名的函数名=具体化非失真）即合规（复用 plan:3#1 v4 合法形态）。
- **方框三·四源漏源（五类清单缺类，plan:4 专属）**：五类清单缺某一整类（①-⑤
  任一缺失）且无「该类无相关内容」声明判 block（缺③验收包=understand.md 在清单
  无任何条目=四源之一漏源）；合法形态=五类均有条目即合规；某类无对应内容时显式
  标注「该类无相关内容」即合规--不得以「某类条目少/粒度粗/某源仅一条」为由 block。
- **方框四·原文未引用**：v1 重放后下沉 epc_quote_trace mech（§3）；judge 侧残留
  判面=整清单无一处『』原文引用（非单条未引）。

【判材边界】（plan:4#1 特有判面，治聚类 1/2/3/4）：input=四源（design.md/plan.md/
understand.md 主仓 .md 文件 + evidence plan:1/2/3 前序 trace）均结构性不可见；
**evidence 是一个源（plan:1/2/3 trace 集合），清单条目引用了 evidence 任一 plan
trace 即合规，不要求 plan:1/2/3 全引用，不得以「evidence plan:2/3 trace 未引用/
未声明无关联」为由 block（治聚类 2）**；**不要求每子项每属性都附原文引用--每类附
源出处+至少一处『』原文片段即合规，不得以「②能力绑定未分别引用 factor-development/
codegraph/TDD 三处原文/①阶段分组未引用原句」为由 block（治聚类 3）**；**验收包（③）
引用 understand.md 原文即合规，不要求六字段逐字全列/triggered 项逐个展开，不得以
「六字段未全列/triggered 项未逐个标注」为由 block（治 vio5 判词衍生的六字段误判）**；
**『…』摘要包裹是合法引用形态，不得以「节选标签式短句/非逐字整段」为由 block
（治聚类 1）**；本步只判 trace 内自洽 + 留痕形式。

【合法正例】（各聚类合法形态落位）：「①任务 DAG：T1=U2 代码改动（…增加 FACTOR_
CATEGORIES 分组键，改 .py=H15 触发信号）--出处 plan.md:12，原文『U2: 在既有聚合
统计函数内增加 FACTOR_CATEGORIES 维度分组键』」合规（源文件+行号+原文片段即满足，
『…』片段合法）；「③验收包：SC1.1=八维度汇总区块存在性（triggered 项，落点=T3）
--出处 understand.md:22，原文『SC1.1: 报告含八维度汇总区块』」合规（验收包引用
understand.md 原文即满足，不要求六字段全列）；「④假设汇总：H1=…（置信度中×影响中）
--出处 design.md:25，原文『假设 H1: …』+ evidence plan:1 trace」合规（evidence
任一 plan trace 引用即满足，不要求 plan:1/2/3 全引用）；「⑤不可逆操作候选：显式
『无』」合规（某类无对应内容显式标注）；「新增候选：显式『无』」合规。方框以外
一律不判。judge 判 block 须在 reason 引用判据条款（方框一/二/三/四）并附 1 个
正确改写范例（指模式不指实例位置）。

## 2.1 候选文本迭代（v1->v6，n=6×N 轮 MiniMax 重放）

| 版本 | clean | vio1 | vio2 | vio3 | vio4 | vio5 | 关键改动 |
|---|---|---|---|---|---|---|---|
| 基线(从严) | 0/6 | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 | 514 字短 gate thrash（牙齿满但判词多引「原文未引用」过判词形） |
| v1 | 6/6 | 6/6 | 5/6 | 3/6 | 2/6 | 6/6 | 四方框+强化判材边界；方框四判据化「整清单无一处才 block」；vio3 被方框四 per-class distractor 吞、vio4 rubber-stamp |
| v2 | 3/6 | 6/6 | 6/6 | 3/6 | 3/6 | 6/6 | 方框四改 mech-托声明；**under-quoted fixture**（①仅 T1 引）被 judge 逐项引用误伤 clean |
| v3(中断) | 2/6 | 6/6 | 6/6 | 5/6 | — | — | fixture 改全引用（每 task/SC 引）->vio3 升 5/6，但 clean 暴露 ④不完整/③格式不一致新误伤 |
| v4 | 6/6 | 6/6 | 3/6 | 5/6 | 3/6 | 6/6 | fixture 修 ④完整（H1+「其余假设无」）+③每 SC 独立出处；方框三合法形态加「某类有条目即合规」；clean 6/6，但 vio2 静默新增 3/6 |
| v5 | 5/6 | 6/6 | **5/6** | 5/6 | 1/6† | 6/6 | 方框一(b)加「检测：逐条核 a[1] 声明」+「内置工具足够」合法形态->vio2 升 5/6；clean 1 误伤（② codegraph/TDD 未引） |
| v6 | 5/6 | 6/6 | 6/6 | 4/6 | 1/6† | 5/6 | 判材边界加 codegraph/TDD 路由合法面；vio2 升 6/6，vio3 降（方差） |
| v7 | 5/6 | 6/6 | 4/6 | 6/6 | 1/6† | 3/6 | a[2] 改逐类确认；② codegraph/TDD 误伤仍在（判材边界被忽略）、vio5 降（方差/信号稀释） |
| v8 | 5/6 | 6/6 | 5/6 | 3/6 | 3/6† | 6/6 | **payload 简化：②去 codegraph/TDD**（§2 路由非 plan.md 能力节内容，消除持久误伤源）+ 删对应判材边界缩短 gate；vio5 回升 |
| v9 | 5/6 | 6/6 | 6/6 | 3/6 | 2/6† | 6/6 | 同 gate 稳定性复核；vio3 连续两轮 <5/6（㉖ 回炉信号） |
| **v10** | **6/6** | 6/6 | 6/6 | **5/6** | 3/6† | 6/6 | **方框二加「检测：逐条对照+多数忠实不得放过个别改写条目」->vio3 升 5/6 且 clean 6/6**（治 needle-in-haystack 注意力方差） |
| v11 | 6/6 | 6/6 | 4/6 | 6/6 | 3/6† | 6/6 | 同 gate 复核：clean 6/6 稳定，vio3 升 6/6 |
| v12 | 6/6 | 6/6 | 5/6 | 6/6 | 3/6† | 5/6 | 同 gate 复核：clean 6/6 三连稳定 |
| prod(落地) | 5/6 | 6/6 | 6/6 | 4/6 | 2/6† | 6/6 | 生产 gate 重跑（`/tmp/p4s1_prod_n6.txt`）：clean 5/6、方差带内 |

†vio4 = mech 生产墙托（设计内委托，judge 读数=已知裁量面，同 plan:2#1/plan:3#1
vio1/vio4；㉗ 判读纪律：EXPECT 仍标 BLOCK，judge-only 0-2/6 是设计内）。

**迭代要点**：
- v1->v2：vio4 2/6（方框四判据化被 judge rubber-stamp 放过有行号无『』条目，同
  plan:3#1 v1 vio4 1/6）-> 切 epc_quote_trace mech（§3）+ 方框四改 mech-托声明。
  **mech-托声明引入后 clean 反降**（v1 6/6->v2 3/6）--judge 忽略「已由 mech 校验
  不得以原文未引用 block」，对 under-quoted fixture（①仅 T1 引）逐项发明「每 task
  须引」要件。教训=**mech-托声明不是 clean 误伤的充分防线，fixture 保真度才是**：
  clean 必须「每条枚举项附出处+原文」（plan:3#1 的 N1/N2/N3 各引一条先例），否则
  judge 总能找到 under-quoting 发明要件。
- v3->v4：全引用 fixture 修 vio3（5/6，judge 聚焦方框二三维对照），但暴露 ④
  不完整（仅 H1 缺 plan.md/evidence 假设）+③格式不一致（SC1.1 出处分离）新误伤
  ->fixture 修 ④加「其余假设：无」声明+③每 SC 独立出处；方框三合法形态加「某类
  有条目即合规，不要求覆盖全部源」->clean 6/6。
- v4->v5：全引用 fixture 移除了方框四 per-class 误伤，但暴露 vio2 静默新增 3/6
  （方框四不再白送 block，方框一(b) 须独立接牙，judge 漏 a[1] 交叉引用）->方框一(b)
  加「检测：逐条检查裸条目并核对 a[1] 声明「无」」遍历指令（同 plan:2#4 方框三「检测：
  逐条检查」救负判定先例）->vio2 升 5/6。
- v5 clean 1 误伤（② codegraph/TDD 路由结论未引，聚类3 每属性误伤的②变体）->
  判材边界加「②的 H15 codegraph/superpowers TDD 是 §2 路由结论非 plan.md 能力节
  原文承载对象，不要求附『…』」。

## 3. mech 下沉（epc_quote_trace，⑯-safe 纯 token 扫描）

v1 重放实证 vio4 judge 侧 2/6（judge 看到清单条目有出处行号 plan.md:12 就
rubber-stamp 放过无『』原文引用的条目，㉖ 注意力方差，与 plan:2#1 element_quote_
trace / plan:3#1 need_quote_trace 同根因同判面）-> 切 `epc_quote_trace` mech：
**复用 `_ELEMENT_SYMBOL_RE`**（plan:2#1 的正则，触发面=答案含 .py 代码符号形；
放过=含『』或「原文」字样；整条答案任一清单项有原文引用即放过--vio2 的 ⑤ 裸但
①-④ 有原文引用->mech 放过交 judge 判静默新增，本 mech 只做「全清单无原文」的墙）。

mech_checks=("epc_quote_trace",) 挂 plan:4 子1。mech 单元测试三件（block 两形态/
pass 两形态/skip 两规则）与 plan:2#1/plan:3#1 同构。

**与 plan:2#1/plan:3#1 的判读口径完全一致**：vio1（全裸）/ vio4（有行号无原文）期望
BLOCK 但 judge 侧命中降为 0-2/6 = 设计内委托（生产墙先拒），牙齿由 mech 单元测试
100% 接住；vio2 静默新增 / vio3 改写失真 / vio5 漏源是 judge 语义判面，必须 ≥5/6。

## 4. 验证标准（同 #28/#30 ⑥ + mech 托读数口径 #30 ⑦）

三向 × n=6：clean 全 PASS + vio1/2/3/5 ≥5/6 BLOCK + vio4 mech 生产墙托（judge 读数
低=设计内委托，同 plan:2#1/plan:3#1 vio1/vio4 范式）+ mech 单元测试零方差证拒 +
既有 pin 测试全绿。

## 5. 验证结果

1. **基线（从严 514 字）**：clean 0/6 + vio1-5 6/6（判词多引「原文未引用」过判词形）=
   短 gate thrash 第十三实证。
2. **措辞迭代 v1-v12**（n=6×12 轮）：v1 四方框->v2 方框四 mech-托（clean 降=under-
   quoted fixture 被逐项误伤）->v3-v4 fixture 全引用+修 ④完整/③格式（clean 6/6 但
   vio2 3/6）->v5 方框一(b)检测指令（vio2 升）->v6/v7 clean 误伤在 ② codegraph/TDD
   +a[2] 泛述（判材边界被忽略）->**v8 payload 简化 ② 去 codegraph/TDD**（§2 路由非
   plan.md 能力节内容，消除持久误伤源）->**v10 方框二加「检测：逐条对照+多数忠实
   不得放过个别改写条目」**（治 needle-in-haystack，vio3 升 5/6 且 clean 6/6）。
3. **落地态（gate + epc_quote_trace mech，v10-v12+prod n=6×4 轮）**：clean 6/6+6/6+
   6/6+5/6（三连 6/6 稳定）+ vio1 6/6×4 + vio2 6/6+4/6+5/6+6/6（方差带 4-6/6，阻塞时
   判词全引方框一(b)静默新增）+ vio3 5/6+6/6+6/6+4/6（阻塞时判词全引方框二三维对照）
   + vio4 3/6+3/6+3/6+2/6（mech 托，judge 被告知原文已机械校验放行，设计内委托）
   + vio5 6/6+6/6+5/6+6/6（阻塞时判词全引方框三缺类漏源）。
4. **mech 单元测试 100%**：`test_p4s1_epc_quote_trace_block_forms` /
   `test_p4s1_epc_quote_trace_pass_forms` / `test_p4s1_epc_quote_trace_skip_rules`
   --block 两形态（裸符号/有行号无原文）+ pass 两形态（含『』/含「原文」）+
   宁纵勿枉 skip 两规则（无 .py 不扫/任一条目有原文引用即放过）。
5. **判词引对条款抽读**（㉖）：vio1 判词引方框一(a)全清单裸=编造；vio2 判词逐字引
   「方框一(b) 静默新增/新增候选：无声明下裸条目」；vio3 判词逐字引「方框二 三维
   对照（操作对象/性质/产出物）」；vio5 判词引「方框三 五类缺类/understand.md 无条目
   =漏源」--不靠宽泛词形接牙。
6. **756 tests 全绿**（753 既有 + 3 新增 mech 测试）；ruff check/format 全过；
   `test_default_pass_marker_pinned_in_gates` 加 `p4[0]`。

## 6. 影响面

- `dl_flow_engine.py`：`_check_epc_quote_trace` + `_MECH_QA_CHECKS` 注册表加一行（H15 codegraph 查询留痕前置，worktree 内 gate 放行）
- `dl_flow_nodes.py`：plan:4 子1 gate 改写 + `mech_checks=("epc_quote_trace",)`
- `tests/test_dl_flow_engine.py`：`test_p4s1_epc_quote_trace_*` mech 单元测试 + default_pass_marker pin 加 `p4[0]`
- `tests/replays/replay_plan4_sub1.py`（新增）+ `tests/replays/README.md` 清单加一行
- `designs/plan4-sub1-gate-framing-design.md`（本文件）

## 7. 并发协作

4 会话并行（worktree-per-session 协议 collab #26）：plan:3#3（feat/plan3-sub3-gate-
framing，已有 replay 未提）/ plan:3#4（feat/plan3-sub4-gate-framing，用户坐标在飞）/
plan:4#1（本会话 feat/plan4-sub1-gate-framing）/ plan:4#2（feat/plan4-sub2-gate-
framing，兄弟子2 节点）。本例在**独立 worktree** /home/admin/dl-wt-plan4-sub1 开发
（用户指令「用 worktree 隔离开发」），与 plan:4#2 同改 plan:4 节点不同子步 gate=
独立 hunk，合并时 git 自动合并（collab #22）。版本号/例数提交前 git log + 全仓 grep
（含 untracked + 4 worktree）双复核（collab #13/#20/#25），撞号顺延。共享文件
（dl_flow_nodes.py/dl_flow_engine.py/test_dl_flow_engine.py/README）提交只 add 显式
清单（collab #9），禁 git add -A（collab #5）。dl_flow_nodes.py/dl_flow_engine.py
编辑触 H15 codegraph 门禁，worktree 内 _is_linked_worktree 放行（collab #26）。
