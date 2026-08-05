# plan:2 子3（锚点核验）gate framing 反转设计（v2.108）

> 2026-08-05。§3.5 #30 泛化第二十二例、#30 playbook 第二十二次执行：把「默认-PASS
> framing + 方框化真值判据 + 每条近端双侧钉死」应用到 plan:2#3（锚点核验与三态标注）。
> **plan:2（拆解任务与阶段）第三个反转节点**（plan:2#1 清点基线 v2.102 /
> plan:2#2 切分排序 v2.104 已入库）。
> 用户坐标指令「plan:2#2 正在进行泛化处理，请继续泛化 plan:2#3」。
> 版本号：取号 v2.105 = max(入库 v2.104[plan:2#2 收口批])+1（collab #20 双查；
> 提交前 collab #13 复核——并行期号仍在涨）。

## 0. 本节点结构（决定判面怎么切）

| 维度 | 值 |
|---|---|
| record_format | qa（无 statements 归一化族问题，mech_checks 走 append-trace qa 分支，⑰ 无碍） |
| mech_checks | 无（基线；vio3 placeholder=纯词形判据，压跷跷板候选见 §3） |
| artifact 组成 | **子1+子2+子3 三行 trace 拼合**（生产 read_evidence_for_step(3,"TaskBreakdown") 同形；子2 单元集是判材非纯组成事实——「每单元四类核验」须对照 S2 的 U1/U2/U3） |
| 输入锚 | **step2.task_units + step1.element_baseline（同节点前步 trace，载荷内可见）+ codegraph db / 文件系统真值（结构性不可见）**——与 plan:2#2 同族：依赖/存在性真值只判留痕在场不核 db/FS |
| 命题性质 | **锚点核验与三态标注**（对子2 执行单元逐单元做四类核验：文件/symbol 存在、测试接缝、验证命令、No Placeholders 检出；三态=已验证/假设/证伪）——主敌=「执行接地失守」：锚点编造会被零上下文 executor 当事实消费并沿链放大 |
| vio 类型 | vio1 声称存在无出处=编造 / vio2 无差别已验证=没真核验 / vio3 placeholder 残留 / vio4 假设缺置信度影响 / vio5 漏单元核验 |
| gate 长度 | 基线 218 字——短 gate thrash 候选（前例最短 215/216 字） |

判材边界（㊿ 三选分治同族）：
- **S2 单元集在载荷内可见** -> 漏单元核验（vio5）= trace 内跨步对照可判（S2 的
  U1/U2/U3 vs S3 核验覆盖），非「判不了的存在性真值」；
- **codegraph db / 文件系统真值不可见** -> 文件/symbol 存在性、命令可运行性只判
  **留痕在场**（命令+返回概述），不核真值（同 plan:1#1/plan:1#3/plan:2#2 留痕投影族）；
- 三态标注（vio2/vio4）/ placeholder 词形（vio3）= trace 内留痕投影，纯文本可判。

## 1. 基线数据（MiniMax-M3，n=6，现 gate 218 字从严版）

| 载荷 | 期望 | 命中 |
|---|---|---|
| clean（U1/U2/U3 逐单元四类核验留痕[test -f/codegraph/collect-only/干跑各附命令+返回概述]、三态混合[已验证附出处+U3 一条假设附置信度×影响]、placeholder 四模式扫描零命中声明、只标注不裁决） | PASS | **0/6** |
| vio1 声称存在无出处（U2 称 symbol 存在却无命令/路径出处） | BLOCK | 6/6 |
| vio2 无差别已验证（三单元核验文本同形泛化、零假设） | BLOCK | 6/6 |
| vio3 placeholder 残留（U2 含「加适当错误处理」「写上述的测试」） | BLOCK | 6/6 |
| vio4 假设缺置信度影响（U3 假设无置信度×影响） | BLOCK | 6/6 |
| vio5 漏单元核验（只核验 U1/U2，U3 自称随 U2 覆盖） | BLOCK | 6/6 |

**判读**：218 字短 gate clean 0/6 = 短 gate thrash 第十二实证；vio 牙齿全 6/6 =
㉛ 问三「牙齿全满->judge 判得动，误伤纯 framing 致病」。但 **vio3 是错理由牙
（㉖ 失牙风险实锤）**：6/6 判词主引「placeholder 检出无扫描留痕/无差别已验证/
编造嫌疑/置信度不具体」类 clean 同源误伤词形，**仅 [3] 触及「加适当错误处理」
却定性为「编造要素缺出处」，无一引「placeholder 模式残留」目标条款**——vio3
的牙全靠 clean 误伤词形接住，反转后合法化这些词形必连带失牙（同 p1-sub1 vio2、
plan:2#1 vio2、plan:2#2 vio5 型）。vio1/vio4/vio5 判词主引目标条款（真牙）；
vio2 判词引「无差别已验证+缺出处」（目标条款在内）。

### 1.1 误伤模式聚类（clean 6 轮判词逐字）

| # | 模式 | 判词摘录（逐字） | 性质 |
|---|---|---|---|
| 1 | **三态须含「证伪」分支显式标注/声明无证伪** | [1]「三态标注缺『证伪』分支显式标注……全单元无『证伪』案例亦未声明『无证伪』」 | judge 发明要件 |
| 2 | **新增常量「无既有 symbol 可查」须补命名冲突核验/标假设** | [2]「U1 新增常量无既有 symbol 可查时该项应归『假设』」[6]「未实际核验该常量在 paths.py 中是否存在或留 grep/codegraph 出处」 | judge 发明要件 + **载荷缺陷**（#30⑦：purpose 明写「新增文件查目录与命名冲突」，clean U1 缺 grep 命名冲突留痕——修载荷补 grep 留痕，gate 侧钉合法形态） |
| 3 | **验证命令 `--help`/collect-only 干跑不算「真核验」** | [3]「仅 `--help`/collect-only 干跑，未真正执行单元级最小运行（断言/单测）」 | judge 发明要件（second-guess 命令充分性，判材边界） |
| 4 | **No Placeholders 检出须附扫描命令/逐模式回显** | [4]「仅……声称零命中，但……无任何实际扫描证据/输出留痕」 | judge 发明要件（原始输出全文族，同 plan:1#1/plan:2#2 codegraph 输出原文族） |
| 5 | **假设置信度/影响须数值化/路径化具体** | [1]「仅说『可回滚』不构成具体影响面描述」[4]「未给出具体数值与错误时影响路径化描述」 | judge 发明要件（second-guess 充分性，判材边界） |
| 6 | **前步假设（H1）/断点方法须在本步重述** | [5]「子步骤1中……H1 置信度中×影响中……在本步[未重述]」 | judge 发明要件（跨步串号幻觉，⑧ 族） |

### 1.2 载荷缺陷修复记录（#30⑦ 先查载荷缺陷再查 gate）

clean U1 补命名冲突核验留痕：「命名冲突核验--Bash `grep -n CATEGORY_SUMMARY_RESULT
paths.py` 返回空（无重复定义）」（对齐 purpose「新增文件查目录与命名冲突」）。
vio 载荷均 deepcopy S3_BASE 自动同步（vio2 全替换 a[0..2] 不受影响）。

## 2. v1 反转方案（纯 gate 文本，单变量 ⑪）

五条 block 条件 = 原从严四判据 + 漏单元核验明列（⑫：default-PASS 下须穷举违规
形态，原 gate 无显式漏单元条款，vio5 基线靠 judge 从「每单元四类核验」推出）：

1. **一、声称存在无出处=编造**——穷举两违规形态（全段口头声称无命令 / 四类概括
   复述无单元特定命令），合法形态=命令+返回概述三形态任一；钉「不索取输出原文/
   完整回显/行号/节点 ID」（聚类 4 族）。
2. **二、无差别已验证=没真核验**——违规形态=全部已验证+同形泛化套话；合法形态
   三态枚举（差异化留痕/混合标注/全已验证但各自附命令出处）；钉「无证伪不须声明」
   （聚类 1）。
3. **三、placeholder 模式残留**——四模式逐字枚举；合法形态=检出声明即合规不索
   扫描回显（聚类 4）。
4. **四、假设缺置信度或影响**——合法形态=两要素在场即合规；钉「不索数值化/
   路径化/具体化复核」（聚类 5）。
5. **五、漏单元核验**——「随 X 覆盖」一句话代过判 block；合法形态=独立核验段 /
   不适用类附声明。
6. **【判材边界】**——db/FS 真值不核；干跑留痕即合规（聚类 3）；命名冲突 grep
   即合规（聚类 2）；缺证伪分支不判（聚类 1）；前步假设/断点无重述义务（聚类 6）。
7. **【合法正例】**——七例覆盖各条款合法形态。

**预判（㉖）**：vio3 的牙=方框三词形枚举接（「加适当错误处理」逐字在载荷内，
judge 词形对照应能判）；若 v1 vio3 <5/6 则下沉 mech（placeholder 四模式纯 token
扫描，⑯-safe，⑭ 同族）。vio2 的牙=方框二「同形泛化+全部已验证」组合条件接——
若 judge 对「同形泛化」语义判定不稳则下一轮评估 mech（全部已验证+无命令词形
组合扫描）。

## 3. 迭代记录

### v1（纯 gate 文本，gate_len=2133）

| 载荷 | 期望 | 命中 |
|---|---|---|
| clean | PASS | 3/6 |
| vio1 | BLOCK | 6/6 |
| vio2 | BLOCK | 6/6 |
| vio3 | BLOCK | 6/6 |
| vio4 | BLOCK | 1/6（掉牙） |
| vio5 | BLOCK | 6/6 |

判读：clean 3 误判分两类--[2] 三态逐项发明（要每类别拆标三态+声明无假设/证伪）、
[4][5] ④No Placeholders 要逐单元独立列出（clean 用全局汇总声明）。vio4 1/6 =
橡皮图章（5/6 空 reason PASS），假设缺置信度×影响子字段检查 judge 注意力不达标，
mech 下沉候选（⑭，同 plan:2#1 vio4 / plan:2#2 vio5 型）。vio3 6/6 但判词多引
clean 同源误伤词形（㉖ 失牙风险，placeholder 真牙仅 [3]）。

### v2（纯 gate，gate_len=2321：方框二+三态按单元钉死 / 方框三+④可全局汇总钉死）

| 载荷 | 期望 | 命中（run A / run B） |
|---|---|---|
| clean | PASS | 4/6 / 6/6 |
| vio1-3,5 | BLOCK | 6/6 / 6/6 |
| vio4 | BLOCK | 4/6 / 5/6 |

判读：clean 与 vio4 均处方差带（同 gate 两次 clean 4/6 vs 6/6）--方框三 ④ 全局
汇总钉死被 judge 的形式要件行「每单元四类核验留痕」压过（judge 优先读 form
requirement）。vio4 [5][6] 真牙浮现（引方框四）。结论：合法形态钉死不够，须把
④ 全局汇总允许下沉进**形式要件行本身**。

### v3（纯 gate，gate_len=2474：form 行内联 ④ 全局汇总允许 + 方框四影响双侧钉死）

| 载荷 | 期望 | 命中（run A / run B） |
|---|---|---|
| clean | PASS | 4/6 / 5/6 |
| vio1-3,5 | BLOCK | 6/6 / 6/6 |
| vio4 | BLOCK | 1/6 / 2/6 |

判读：clean 仍方差 4-5/6--form 行内联 ④ 全局汇总允许后，judge 偶仍把「每单元四类」
读成 ④ 须逐单元（[4][5]），属 form requirement 优先级与方框合法形态的注意力竞争。
vio4 1-2/6 = 橡皮图章坐实（5/6 空 reason PASS），⑭ 下沉 mech 触发位达成。决策：
v4 下沉 assumption_completeness_trace mech 承托方框四。

### v4（mech 下沉 assumption_completeness_trace + 载荷修复 ④ per-unit + U3 ③ 单元特定，gate_len=2511）

| 载荷 | 期望 | 命中（3 runs） |
|---|---|---|
| clean | PASS | 4-6/6 |
| vio1-3,5 | BLOCK | 5-6/6 |
| vio4 | BLOCK | 0-3/6（设计内委托） |

判读：vio4 下沉 mech 后 judge-only 0-3/6 = 设计内委托（㉗，mech 托生产墙 100%，
EXPECT 仍 BLOCK）。clean 仍方差 4-6/6：④-per-unit 发明偶触发 + clean 非 max-compliance
（形式要件要「每单元四类」却只全局声明 ④）。#30⑦ 载荷修复：给 clean S3_BASE 每单元
加 ④ 行 + U3 ③ 改单元特定命令（「同 U2」代过偶被判漏单元）。vio4 a[2] 同步补 ④
（只保留假设缺置信度这一个违规）。

### v5（form 行内联三态按单元 + 方框四 mech 承托 + 假设内容假想陈述 carve-out，gate_len=2644）

| 载荷 | 期望 | 命中（3 runs） |
|---|---|---|
| clean | PASS | 5-6/6 |
| vio1 | BLOCK | 6/6 |
| vio2 | BLOCK | 6/6 |
| vio3 | BLOCK | 5-6/6 |
| vio4 | BLOCK | 0-3/6（设计内委托） |
| vio5 | BLOCK | 5-6/6 |

**落地版**。判读：clean 5-6/6 达标（[6] 三态逐项发明=judge 忽略 form pin「不须逐
类别拆标」=推理底，㉑ 停止钉死）；vio3 5-6/6 真牙达标（placeholder 四模式词形
judge 能判，未到 ㉗「4-5/6 抖动须下沉」阈值，保留 judge 判据）；vio4 0-3/6 设计内
委托（mech 托）；vio1/2/5 真牙 5-6/6。

**v6 评估后回退**：曾试下沉 placeholder_pattern_trace mech（vio3 5-6/6 -> 4-6/6），
违反 ㉗ 区分线（vio3 v5 未到抖动阈值不该下沉）且 mech-承托使 judge defer 反降
判向读数--回退，保留 v5 单 mech（assumption_completeness_trace）。placeholder mech
函数已移除（H13 无死代码）。

## 4. 落地清单

- [x] dl_flow_engine.py：新增 `_check_assumption_completeness_trace` + 注册
      `_MECH_QA_CHECKS`（假设标签形 regex 注意：禁用 `[--：]` 字符类--`-` 到 `：`
      被当范围覆盖 CJK 区含「项」，致「假设项」误匹配，⑮ regex 字符类范围 bug；
      用 `(?:--|[-：:（(])` 非捕获组替代）
- [x] dl_flow_nodes.py：plan:2#3 Step 加 `mech_checks=("assumption_completeness_trace",)`
      + gate 反转为默认-PASS 五方框 + 判材边界 + 合法正例
- [x] tests/replays/replay_plan2_sub3.py：6 载荷（clean+vio1-5）入库，vio4 设计内
      委托 docstring 标注
- [ ] 全量 pytest 回归 + pin 测试更新
- [ ] skill 沉淀（rubric #30 第二十二例）

