# plan:3 子5（归一化能力包）gate framing 反转设计（v2.117）

> **泛化第三十四例 = 35 gate 收官**（本例落地后 35/35 全反转）。
> 基线 371 字从严 clean 0/6 + vio1-5 全 6/6（但 vio3 牙几乎全靠
> clean 同源的复合句误伤词形接住=㉖「错理由拦对」设计内失牙风险
> 教科书实例第二例，首例=plan:1#5 vio5）。反转 + 五方框近端双侧
> 钉死；vio4/vio5 跨步负判定崩牙以「列出前序条目→逐项检索→缺席
> 即 block」检测指令接住（方框三同构指令在 vio3 已证 6/6）。

## 0. 本节点结构（决定判面怎么切）

plan:3 子5 = 归一化能力包（claim normalization 职能第八次复用）。
input=step4.verified_bindings；record_format=statements，
statement_fields 五键 skill_first/tools/enforce_align/subagent_policy/
no_load（append-trace 逐键 JSON 校验非空，无内容键填显式「无」）。
type_label 域=**skill/工具/门禁/子代理/不加载 五值**（㉜ 多值域=
归一化族高迭代预期信号——must/nice 二值的 u:1#5/u:2#4 一轮达标，
四值跨类别的 u:3#4 五轮）。

判材=子1-子4 trace 拼合（read_evidence_for_step(5,
"CapabilityToolSelection")）：子2 注册表清单（能力名逐字对照基线）、
子3 绑定提案+最小集不加载清单（传导忠实基线）、子4 可用性状态+
假设项汇总（假设传导基线）。

主敌=「长链转换失真」五类：字段篡改（被否替代写进绑定字段）/
复合未拆/幽灵回潮（能力名凭记忆缩略）/不加载清单静默丢失/假设
丢失淡化。

## 1. 基线数据（MiniMax-M3，n=6，现 gate 371 字从严版）

| 载荷 | 命中 | 牙保真度（㉖） |
|---|---|---|
| clean | **0/6** | —— |
| vio1 字段篡改 | 6/6 | 全引对条款（幽灵回潮+篡改） |
| vio2 复合句 | 6/6 | 4/6 引对，2/6 错理由（发明 q/a 要件） |
| vio3 幽灵回潮 | 6/6 | **~1/6 引对——几乎全错理由（复合句词形）** |
| vio4 不加载清单丢失 | 6/6 | 1/6 引对，余错理由（复合句词形） |
| vio5 假设丢失 | 6/6 | 1/6 引对（[6] 假设篡改），余错理由 |

短 gate thrash 第八实证（371 字从严 clean 0/6）。

### 1.1 误伤模式聚类（clean 6 轮判词逐字）

1. **「长 pipeline 后台禁 pipe」被读成「子3 未绑定的新增约束」**
   （clean[1]）——常驻执行映射条目被读成凭空新增；
2. **「单线程执行」被读成「把子3 未绑定扇出改写」**（clean[1]）；
3. **假设传导形式要件发明**（clean[2]）——要求字段层显式携带
   「无假设」结构/置信度×影响结构；
4. **H15+长 pipeline 一条 statement 被判复合**（clean[3][6]+
   vio3[1][2]+vio4[2][3][6] 同词形）——字段枚举被读成复合；
5. **skill_first 含触发依据+出处引用被读成复合**（clean[4]+
   vio3[3]）；
6. **T1/T2/T3 三任务一条被判复合**（vio5[1]+vio4[6]）；
7. **不加载清单 4 能力名一条被判复合**（vio5[4]）；
8. **缺 q/a / 缺 kind 顶层键 / 未声明落库 发明要件**（vio5[2][3][5]
   +vio2[3][5]）——record_format=statements 形态不明。

㉛ 三问：①方框间共享旋钮=「字段枚举 vs 复合」一个，分野=text
单句判、字段不判（clean 全是字段枚举，vio2 是 text 合并）；②方框一
「同义转述合规」落在 vio1/vio3 判材（能力名）上=压跷跷板，钉
「能力名逐字除外」；③基线 vio 全 6/6=judge 判得动，误伤纯
framing 致病——但 vio3 需重接牙（㉖）。

## 2. 反转后的判据设计（默认-PASS framing）

头部：record_format=statements 生产形态声明（无 q/a 字段、判对象=
sub_step==5 那条）——聚类 8 的钉死位（plan:1#5 同构先例）。

五方框（每条近端双侧钉死，词形取 §1.1 聚类逐字）：

- **方框一 字段与子3/子4 已定内容不一致**：block 例=被否替代写进
  绑定字段（`factor-summary-reporting`）；合法形态=同义转述合规
  **能力名除外**（压跷跷板钉）+ enforce_align 含 §3 常驻约束合规
  （聚类 1）+ subagent_policy 显式「单线程」合规（聚类 2）。
- **方框二 复合句**：block 例=text 合并不同字段族断言（skill 绑定
  +测试时机）；合法形态=字段内枚举（skill_first 多子句/
  enforce_align 多条目/no_load 多名）+ text 概括同族条目族 +
  多任务 ID 适用范围枚举（聚类 4/5/6/7）+ 只判 text 不判字段、
  不判项间关系。
- **方框三 幽灵回潮**：block 例=凭记忆缩略（`superpowers:tdd`）；
  **检测指令=逐字对照每个能力名与注册表清单行，多数一致也不得
  放过个别缩略**（needle-in-haystack 注意力锚，第三十二例③
  同构）；合法形态=「内置工具足够」类通道描述不核。
- **方框四 不加载清单缺失且无声明**：**检测指令=列出子3 清单
  条目→逐条在 statements 全文检索→缺席且无声明即 block，其余
  全合规也不得放过**；合法形态=合并一条或逐项拆均合规、清单在
  text 或 no_load 字段均合规。
- **方框五 假设传导丢失/淡化**：**检测指令=列出子4 假设条目→
  逐条检索置信度×影响携带→缺席或改写成「已确认无风险」即
  block**；合法形态=boundary 或 fields 任一处携带即合规、无假设
  项标「无假设」即合规（聚类 3）。

## 3. 迭代记录

### 3.1 v1（3078 字）：clean 5/6 + vio1-3 6/6 + vio4 1/6 + vio5 3/6

- clean 唯一误伤=**载荷缺陷非 gate 缺陷**（⑦ 第一实证）：fixture
  stmt1 skill_first 引『开发因子/新增因子/IC脚本/**分层回测**』，而
  S2/S3 trace 只命中前三词——judge 判「分层回测=新增词」判得对。
  修 fixture（删分层回测）不修 gate。
- **vio4 1/6 崩牙 + vio5 3/6 弱牙同族**：都是「前序有 X → 本步
  缺席」的跨步负判定，5/6 与 3/6 空 reason 橡胶图章 PASS。方框
  四/五无检测指令，而方框三有「逐字对照」指令的 vio3 6/6——
  文案杠杆先行：方框四/五补「列出前序条目→逐项检索→缺席即
  block」同构指令（v2）。

### 3.2 v2（3397 字）：修 fixture + 方框四/五补检测指令

- clean 唯一误伤=**载荷缺陷**（v1 [6]）：fixture stmt1 skill_first 引
  『…/分层回测』而 S2/S3 只命中前三词。修 fixture 删「分层回测」。
- v1 vio4 1/6 + vio5 3/6 同族=跨步负判定崩牙（前序有 X->本步缺席）。
  方框三「逐字对照」检测指令在 vio3 已证 6/6，方框四/五补同构「列出
  前序条目->逐项检索->缺席即 block」检测指令。
- v2 结果：clean 5/6 + vio1-3 6/6 + vio4 **3/6** + vio5 **5/6**。
  vio5 升至 5/6（检测指令有效），vio4 仍 3/6（方框四检测指令被忽略）。

### 3.3 v3（3365 字）：方框四「判 pass 前必须先执行对照」强化

- v2 vio4 3/6 仍弱：方框四检测指令措辞「先从子3 trace 列出…再逐条
  检索」被弱 judge 读成可选步骤。v3 改「**判本步 pass 前必须先执行
  对照**」义务句前置（#30 harness 注措辞三变体 A/B 同款教训：否定/
  许可句被读成行为指令，义务句主句前置唯一达标）。
- v3 结果：clean 5/6 + vio1-3 6/6 + vio4 **2/6** + vio5 **2/6**。
  vio4 反降 2/6、vio5 反降 2/6--文案检测指令在跨步枚举场景不可靠
  （judge 仍不做逐项扫描，⑭ 注意力方差），按 ㉗ 区分线下沉 mech。

### 3.4 v4（3236 字 + schema 钉死 3424 字）：方框四/五下沉 mech

- 下沉两个跨步 mech（出席型负判定，binding_residue_trace/sc_coverage_trace
  /rejected_rationale_trace 同族第三/四个实例）：
  - `no_load_trace`：读子3 取不加载清单条目名集（`不加载清单` 锚 +
    反引号 token），核对每个在本步 statements 全文出现；
  - `assumption_propagation_trace`：读子4 检测假设标签形
    （`_ASSUMPTION_LABEL_RE`），若有则核对本步全文含「置信度」或
    「影响」词形痕迹。
- gate 方框四/五改 mech-托声明（「已由 X 机械校验、不会到你这里、
  不得以此 block」）+ mech_scope 双重注入。
- **第三十三例③ 第二实证（mech 注册后 clean 复测反向）**：v3 clean
  5/6，mech 注册后同文本 n=6 复跑掉到 4/6--新出 schema 发明要件聚类
  （clean[3]「fields 内缺 type_label 承载」+ clean[4]「缺
  hypothesis_assumption/trace_meta 字段」无底洞要件）。不是回归，是
  mech_scope 注入重排 judge 判面、注意力转移到 schema 形态面。操作
  化：头部形式要件段补 schema 钉死句（顶层键=text/type_label/
  boundary/fields 四键，type_label 与 text 平级非 fields 子键，不得以
  缺未定义字段名 block）。
- v4 n=6：clean 4/6（2 噪声轮推理底）+ vio1 6/6 + vio2 5/6 + vio3 6/6
  + vio4 3/6（设计内委托）+ vio5 1/6（设计内委托）。clean 4/6 <5/6
  达标线，按第三十一例④ 跑 n=10 确认稳定带。

## 4. 泛化沉淀候选（本节点新教训，先记不落 rubric）

1. **出席型跨步负判定 mech 族第三/四个实例**（no_load_trace +
   assumption_propagation_trace）：binding_residue_trace /
   sc_coverage_trace / rejected_rationale_trace 同族。共同模式=读前序
   trace 提取集 -> 本步全文检索差集 -> 缺席即拒。判别锚=「前序有 X
   清单/标注 -> 本步该 X 缺席」型负判定。
2. **文案检测指令 vs mech 下沉的边界（v2/v3 证伪）**：方框三「逐字
   对照每个能力名」在 vio3 6/6-9/10（**单步对照**，needle-in-haystack
   注意力锚有效）；方框四/五「列出前序条目->逐项检索」在 vio4/vio5
   仅 2-3/6（**跨步枚举**，judge 不做扫描）。判别：检测指令治「单步
   内对照」（注意力锚到逐条），治不了「跨步列出+检索」（多步工作
   记忆）。后者=mech 触发面（㉗ 区分线：文案 2-3/6 vs mech 100%）。
   **这是 ⑭/㉗ 的精细化**：注意力方差不止「逐项扫描不做」，还分
   「单步对照做得动 vs 跨步枚举做不动」--单步对照用文案检测指令
   （方框三同构），跨步枚举直接 mech，不必先试文案。
3. **mech_scope 注入重排 judge 判面（第三十三例③ mech 维度第二实证，
   反向）**：v3 clean 5/6，mech 注册后 n=6 掉 4/6（schema 发明要件新
   聚类：fields 内缺 type_label / 缺 hypothesis_assumption 字段无底洞
   要件）。mech 托走「不加载清单/假设传导」判面后，judge 注意力转移
   到 schema 形态面。n=10 稳定带 clean 9/10（n=6 的 4/6 是高方差，
   第三十一例④）。操作化：mech 注册后 clean 复测必跑 n≥10 + 头部补
   schema 钉死句（顶层键=text/type_label/boundary/fields 四键）。

## 5. 验证结果

落地版 v4（3424 字）+ 两 mech（no_load_trace / assumption_propagation_trace）
n=10 稳定带（MiniMax-M3）：

| 载荷 | n=10 | 达标线 | 判词保真度 |
|---|---|---|---|
| clean | **9/10** | ≥8/10 ✓ | [2] 推理底噪声轮（skill_first 语义淡化自相矛盾） |
| vio1 字段篡改 | **10/10** | ≥8/10 ✓ | 全引方框一/三 |
| vio2 复合句 | **10/10** | ≥8/10 ✓ | 全引方框二 |
| vio3 幽灵回潮 | **9/10** | ≥8/10 ✓ | 全引方框三，[7] 噪声轮 |
| vio4 不加载清单丢失 | 2/10 | 设计内委托 | mech 墙 100%（单测证拒），judge 侧不强制 |
| vio5 假设丢失 | 4/10 | 设计内委托 | mech 墙 100%（单测证拒），judge 侧不强制 |

- mech 单测：test_p3s5_no_load_trace_block_pass_skip +
  test_p3s5_assumption_propagation_block_pass_skip（零方差，只在 vio4/
  vio5 触发、clean 与 vio1-3 全静默）。
- pin 测试：test_step5_normalization_gate_framing（mech_checks + 默认 pass
  + 方框三检测指令 + 方框四/五 mech-托声明 + 从严标记撤出）。
- 全测试：642 passed。
- **35 gate 收官**：本例落地后 `默认 pass` 在 35/35 gate 全在场。

## 6. 并发协作

worktree=/home/admin/dl-wt-plan3-sub5（feat/plan3-sub5-gate-framing，
自 main ac03a3a 切出）。并行会话：dl-wt-plan4-sub2（plan:4#2 已
merge 的遗留 worktree，无冲突）。版本号 v2.117 / 例数第三十四例
（main 最新 v2.116/第三十三例，无撞号）。
