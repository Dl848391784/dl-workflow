# plan:1 子5（归一化设计陈述）gate framing 反转设计（v2.116）

> 2026-08-05。§3.5 #30 泛化第三十三例、#30 playbook 第三十三次执行：把「默认-PASS
> framing + 方框化真值判据 + 每条近端双侧钉死」应用到 plan:1#5（归一化设计陈述）。
> **plan:1（设计解决方案）第五个反转节点 = plan:1 节点全反转收官**（前四=plan:1#1
> v2.99 / #2 v2.100 / #3 v2.103 / #4 v2.101 已入库）。
> 用户坐标指令「plan:4#3 正在进行泛化处理，请继续泛化 plan:1#5，记得跑 case 做测试，
> 用 worktree 隔离开发」。
> worktree：`~/dl-wt-plan1-sub5`（collab #26 worktree-per-session）。
> 版本号：**起手取 v2.113/第三十例**（=max(入库 v2.112[plan:3#4])+1；collab #20/#25
> 双查：主仓 git log 最高入库 v2.112，遍历 `~/dl-wt-*/designs/*.md` +
> `tests/replays/*.py` 仅 plan:4#1 自称 `v2.11X`[未定号]、plan:4#3/#4 无 design
> 文件）；**提交前一刻全域重查发现三连撞号**——开发期间 plan:4#4 落 v2.113/第三十例、
> plan:4#3 落 v2.114/第三十一例、plan:4#1 顺延 v2.115/第三十二例，故本例让位顺延至
> **v2.116/第三十三例**（collab #25 禁死守自号；本例是「起手号被后来者整段占走」的
> 又一实证——四并发会话下号段推进快于单会话开发周期，落库前一刻的全域重查是唯一防线）。

## 0. 本节点结构（决定判面怎么切）

| 维度 | 值 |
|---|---|
| record_format | **statements**（载荷 `{"text","type_label":推荐/备选/被否,"boundary":verdict 边界+实现指针,"fields":{八键}}`，statement_fields **八键** change_list/interface_sig/data_contract/callers/rejected/assumptions/acceptance_map/h9_units） |
| 内建机械层 | ①八键逐键非空 JSON 校验；②text/type_label/boundary 非空；③**text 实现侧名词机械扫描**（`_implementation_nouns` = codegraph 符号 + git 文件名）；④**源步 ID 传导覆盖**（`_step_trace_ids` 子4 ID 集须逐项出现）-> 四项可声明「已机械校验不得 block」 |
| mech_checks | **()**（基线无）--本例评估是否下沉（见 §3） |
| artifact 组成 | **子1+子2+子3+子4+子5 五行 trace 拼合**（生产 `read_evidence_for_step(5,"DesignSolution")` 同形；子3 核验事实/三态假设 + 子4 否决理由与推荐均是判材非纯组成事实） |
| 输入锚 | **step4.recommendation**（子1-子4 trace 全在载荷内）--与 plan:1#1 的 understand.md 跨阶段文件不同，本步跨步字段传导**可判** |
| 跨节点不可见 | **must 目标 / 验收包 SC ID 属 GoalsAndValue／SuccessCriteria 节点**，minor_stage 过滤后结构性不可见（#30 ㉚②）-> 不判 acceptance_map 的 SC ID 真实性/完整性 |
| 命题性质 | **代码设计包归一化**（从子4 推荐提案推导八字段设计包）--主敌=「长链转换失真」：字段篡改/复合未拆/凭空新增/假设淡化/ADR 理由丢失**五类**（u:2#4 三类、plan:2#4 四类，本例判面最宽） |
| vio 类型 | vio1 字段篡改 / vio2 复合句 / vio3 凭空新增要素 / vio4 假设淡化 / vio5 否决理由丢失 |
| gate 长度 | 基线 **368 字**--短 gate thrash 候选（与 u:2#4 基线同为 368 字，该例一轮达标） |

判材边界（可见性分治）：
- **子1-子4 trace 载荷内可见** -> 字段传导（vio1）+ 凭空新增（vio3）+ 假设传导（vio4）
  + ADR 理由传导（vio5）= trace 内对照可判；
- **must 目标/验收包属别节点** -> 不判 acceptance_map 的 SC ID 是否真实存在/是否全覆盖
  （⑯-safe 无降级面：本步只判「映射字段有内容」，齐备性已由 JSON 校验托）；
- **codegraph db 真值不可见** -> 不核 callers/impact 数字真伪（子1/子3 已留痕即合规）。

## 1. 基线数据（MiniMax-M3，n=6，现 gate 368 字从严版）

| 载荷 | 期望 | 命中 | 判词理由保真度（㉖） |
|---|---|---|---|
| clean（三 statements 全 type_label=推荐，八字段忠实提取子3 核验事实+子4 否决理由，候选C 假设原样携带置信度×影响，callers 附 codegraph 出处，H9 划分承接子3 量化） | PASS | **0/6** | -- |
| vio1 字段篡改（statement1 change_list 由子4 推荐的候选A 篡改为已被否的候选C 改动） | BLOCK | 6/6 | ✅ **真牙**：6/6 全引「字段不传导/篡改」 |
| vio2 复合句（statement1 text「以及」连接两个可独立拍板的决策） | BLOCK | 6/6 | ✅ **真牙**：6/6 全引复合句 |
| vio3 凭空新增要素（追加第 4 条 Redis 缓存层，子2/子3/子4 全程未出现） | BLOCK | 6/6 | ✅ **真牙**：6/6 全引「凭空新增子4 未评估」 |
| vio4 假设淡化（候选C 假设的置信度中×影响被抹成「小风险，可忽略」） | BLOCK | 6/6 | ⚠️ **半牙**：[1][3][6] 引假设传导 ✅；[2][4] 引「text 含实现侧名词」❌；[5] 引「rejected 无对应记录」❌ |
| vio5 否决理由丢失（rejected 只写「候选B、候选C 已被否」，子4 逐项 ADR 理由全丢） | BLOCK | 6/6 | ❌ **零牙**：[1][2][3][4][5] 全引复合句、[6] 引 sub_step 幻觉——**无一轮引「否决理由丢失」** |

**判读**：368 字短 gate clean 0/6 = 短 gate thrash 又一实证。vio1/2/3 真牙全满 =
㉛ 问三「牙齿全满 -> 反转即治」；但 **vio5 是 ㉖「错理由拦对」的教科书实例**——6/6
全靠 clean 同源的复合句误伤词形接住，目标条款零引用。反转把复合句误伤词形合法化
那一刻 vio5 必崩 -> **vio5 的牙必须由新方框五（ADR 理由传导）独立支撑**，且它是
缺席型负判定（㊳）-> 预判为本例主要迭代成本（见 §3）。vio4 半牙同理，靠方框四接。

### 1.1 误伤模式聚类（clean 6 轮 + vio4/vio5 错理由判词逐字）

| # | 模式 | 判词摘录（逐字） | 性质 | 落位 |
|---|---|---|---|---|
| 1 | **「条数与占比」并列=复合句**（最强误伤源） | clean[2]「把①『正 IC 条数』与②『占比呈现』两个可独立拍板的决策并入一句…对应 SC1.1 与 SC1.2 在 acceptance_map 分两承接」；clean[6]「条数=独立呈现决策；占比=独立呈现决策」；vio5[1][2][3][4] 同词形 | judge 发明要件（一项决策的多个输出数字被读成多项；反用 acceptance_map 多 SC 当拆项证据） | 方框二 legal 面 |
| 2 | **「限定 X，不新增 Y」=复合句** | clean[3]「『限定为既有报告区块内的两个数字』与『不新增图表/独立报告页』可分别拍板」；clean[4]「合并『形态限定为既有区块』『仅两个数字』『不新增图表』『不新增独立报告页』≥2 个」 | judge 发明要件（同一决策的范围正反表述被读成多项） | 方框二 legal 面 |
| 3 | **排除性表述=凭空新增要素** | clean[4]②「凭空新增子4 未评估的要素：第3项『不新增…』」 | judge 反读（否决/排除记录被读成新增要素，㉓ 否定措辞反读族） | 方框三 legal 面 |
| 4 | **callers 字段含 impact 输出=篡改** | clean[5]「第3项 fields.callers 写『codegraph impact…3 个受影响符号』——这是 impact 而非 callers…属篡改子1/子3 出处」 | judge 发明要件（字段名与 codegraph 子命令须一一对应） | 方框一 legal 面 |
| 5 | **outcome 载体名词=实现侧名词**（机械层已托仍判） | vio4[2]「第1条 text 含『IC 区块』『摘要报告』、第2条含『百分比』『报告』」；vio4[4]「判据④『text 无实现侧名词』不满足——含『既有摘要报告的 IC 区块』」 | judge 无视「已机械扫描」声明（v2.52「已修还判」族） | 判材边界 + 方框外抑制 |
| 6 | **rejected 内枚举两候选=复合句** | vio2[4]「rejected 字段把候选B/C 否决理由压缩进同一字符串…属两项合并陈述的复合句，每项应只承载一个可独立拍板的否决」 | judge 发明要件（字段内枚举被判复合，_ATOMIC_ITEM_RULE 边界） | 方框二 legal 面 |
| 7 | **sub_step==5 记录不存在幻觉** | clean[1]「产物中无 sub_step==5 的 skill-trace，仅有 sub_step 1/2/3/4 三条」；vio5[6]「声明产物 sub_step=1~4 而非 5…缺 sub_step=5 的记录」 | judge 幻觉（五行拼合数不清；harness 存在性注 + 组成注均已在场仍崩=五步拼合是最长 artifact） | 判材边界（形式要件行前置钉死） |
| 8 | **rejected 内被否路径「无对应记录」** | vio4[5]「『自行实现百分比格式化』在子3/子4 中并无对应记录——子3 五项核验与子4 Pugh 矩阵均未出现该候选」 | judge 发明要件（ADR 可记录候选集外的被否路径，如重复造轮子检查的隐含替代） | 方框三 legal 面 |

㊹ 待复核标记：vio5 的牙在反转后由方框五独立承接（基线零引用=必崩预期）；vio4
的牙由方框四承接（基线半牙）；三向验证时按 ㉖ 口径逐轮抽读判词是否引对条款。

## 2. 反转后的判据设计（默认-PASS framing）

结构：形式要件（保留「每项=1 个可独立拍板的设计决策」+ 八键齐备已机械校验 + text
实现侧名词已机械扫描 + **sub_step==5 记录组成前置钉死**）+ 默认 pass 声明 + **五方框**
（每条 block 面 + legal 面近端双侧钉死，词形取 §1.1 判词逐字）+ 【判材边界】段 +
【合法正例】段 + 条款引用要求。

- **方框一·字段与子3/子4 已定内容不一致（丢失/篡改/新增）**（vio1，跨步一致性）：
  block 面=某项八字段与子3 核验结果或子4 推荐/否决结论矛盾（如 change_list 写的是
  子4 已否决候选的改动）判 block；legal 面=忠实提取/适度压缩/同义转述即合规，不要求
  逐字一致；**callers 字段同时携带 codegraph callers 与 impact 两类输出合规**（治聚类
  4——字段名不要求与 codegraph 子命令一一对应，影响面数字属 callers 清单的合法内容）；
  codegraph 数字真伪不核（子1/子3 已留痕即合规）。
- **方框二·复合句（未原子化）**（vio2，正判定）：block 面=一项 text 合并 ≥2 个可独立
  拍板的设计决策判 block；legal 面=**同一决策的多个输出数字/多个呈现指标（「条数与
  占比」）= 一项的产出枚举，不算复合**（治聚类 1；acceptance_map 分列多个 SC ID 不
  构成拆项要求）；**同一决策的范围正反表述（「限定为 X、不新增 Y」）= 边界界定，不算
  复合**（治聚类 2）；**字段内枚举多个被否候选及各自理由 = 字段键值枚举，不算复合**
  （治聚类 6）；`{_ATOMIC_ITEM_RULE}`。
- **方框三·凭空新增子4 未评估的要素**（vio3，正判定）：block 面=某项引入子2 候选集/
  子3 核验/子4 矩阵全程未出现的新要素（新模块/新依赖/新数据结构）判 block；legal 面=
  **排除性/否决性表述（「不新增 X」「被否形态=X」）是边界与 ADR 记录，不是新增要素**
  （治聚类 3）；**rejected 字段可记录候选集之外的被否路径**（如子3 重复造轮子检查隐含
  的「自行实现」替代），不得以「该被否路径在子3/子4 无对应候选记录」block（治聚类 8）。
- **方框四·假设淡化（置信度×影响丢失）**（vio4，跨步一致性）：block 面=子3 三态标注
  的假设在本步 assumptions 被抹去置信度或影响后果（「小风险可忽略」式定性淡化）判
  block；legal 面=置信度×影响原样携带或语义等价转述即合规；**假设随其所属候选被否而
  退出、并显式声明「本方案无待接受假设」=合法形态**（不得要求为被否候选的假设保留
  待裁状态）；不要求假设逐字复刻子3 全文。
- **方框五·否决理由（ADR）丢失**（vio5，跨步一致性，**基线零牙、本方框是其唯一支撑**）：
  block 面=rejected 字段只列被否候选名单（「候选B、候选C 已被否」）而无任一否决理由
  判 block；legal 面=**逐候选附理由（引子3 核验事实或子4 Pugh 净分/硬规则触发任一项）
  即合规**，不要求复刻子4 全部评分维度、不要求每个否决维度都列、不要求理由分行分项。

【判材边界】：本步 input=step4.recommendation，子1-子4 trace 载荷内可见->字段传导
可判。**产物含 sub_step 1-5 五条记录是生产常态（read_evidence_for_step 拼合），判对象
是其中 sub_step==5 那条；不得以「无 sub_step==5 记录/仅见 1-4」为由 block**（治聚类 7）。
八字段非空已由 append-trace 逐键 JSON 校验，不得以「缺键/字段为空」block。**text 实现
侧名词已由机械扫描（codegraph 符号 + 仓内文件名），不得以「text 含报告/区块/百分比/
呈现形态类 outcome 载体名词」为由 block**（治聚类 5——载体名词是 outcome-level 的合法
约束成分）。must 目标与验收包 SC ID 属别节点、结构性不可见->不判 acceptance_map 的
SC ID 真实性/是否全覆盖。codegraph db 不可见->不核 callers/impact 数字真伪。子4 条目
ID 传导覆盖已由 append-trace 机械校验。

【合法正例】「text: 正 IC 因子的条数与占比在既有摘要报告的 IC 区块内直接可读出」合规
（同一决策的两个输出数字，非复合；载体名词合法）；「text: 呈现形态限定为既有报告区块
内的两个数字，不新增图表或独立报告页」合规（范围正反表述=边界界定，非复合亦非新增
要素）；「callers: codegraph callers 输出 1 个调用方 X；codegraph impact 输出 3 个
受影响符号」合规（两类输出同栏携带）；「rejected: 候选B 被否——理由=子3 核验其跨 2
文件触发 H8 且不复用既有 format_percentage，子4 净分 −2；候选C 被否——理由=impact 7
符号跨两模块、需 schema 迁移，净分 −5」合规（逐候选附理由，字段内枚举不算复合）；
「assumptions: 候选C 的接缝为假设（置信度中×影响：改动面从 3 文件扩到 5+ 文件、H9
需分解——子3 原样转录）；该假设随候选C 被否不进入本方案，本方案无待接受假设」合规；
「rejected: 被否路径=自行实现百分比格式化——理由=子3 重复造轮子检查确认既有实现在册」
合规（候选集外的被否路径可记）。方框以外一律不判。judge 判 block 须在 reason 引用
判据条款并附 1 个正确改写范例（指模式不指实例位置）。

## 3. mech 下沉评估（vio5 缺席型负判定的处置路径）

**预判**：vio5「rejected 只列名单无理由」是**缺席型负判定**（㊳：合法留痕缺席才违规），
默认-PASS 下 judge 系统性不做「字段内有无理由」扫描——同族先例 plan:2#2 vio5
（②单阶段论证）措辞两版无效后下沉 `single_phase_argument`。

**但按 #30 (51) 判定**：该判定**单字段内可判**（读 rejected 一栏即见有无「理由=」），
不需跨项聚合（无算术、无集合差）-> 措辞优先，先试纯 gate 文本。

**若崩**（vio5 <5/6 且非错理由）：下沉 `rejected_rationale_trace` mech（statements 侧
注册表 `_MECH_STATEMENTS_CHECKS` 第二个，plan:2#4 `sc_coverage_trace` 同范式）——
词形可判子项（#30 ⑭）：rejected 字段非空且含被否候选名但**同栏无任一理由词**
（理由/因为/净分/触发/不复用/H8/H9/impact 类）即拒。宁纵勿枉：rejected 显式「无」
（无被否项）不触发。落地后 gate 方框五改 mech-托声明。

**实测结论：预案被触发，(51) 的「单字段内可判 -> 措辞够用」在本例失效**（v1 5/6 ->
v2 4/6 -> v3 4/6，判词全引对条款=判据文本没问题、是 judge 不执行逐项字段扫描）。
修正 (51)：判定的**聚合维度**（单字段内 vs 跨项算术/集合）只是 mech 下沉的充分条件
之一；**负判定 × 逐项扫描**（㊳ + plan:2#2 ③ 的组合）同样系统性失效——「单字段内可判」
若还要求 judge 对**每个** statements 项的某个字段逐一检查「有没有」，弱 judge 在
默认-PASS 下仍不做。判别信号=判词引对条款但命中率停在 4-5/6（判据对、扫描没执行），
区别于 plan:2#2 型「措辞加强反降」（判据本身歧义）。

## 4. 验证标准（#30 ⑥ + mech 托读数口径 #30 ⑦/㉗）

三向 × n=6：clean 全 PASS + vio1-5 ≥5/6 BLOCK **且判词引对条款**（㉖：错理由 6/6
不算达标，vio4/vio5 重点抽读）+ 既有 pin 测试全绿（`TestAtomicItemRule._TWO_STEPS`
含 `("plan",1,5)`：gate 须含「按独立性判」「复合句」「可独立成立」）+
`test_default_pass_marker_pinned_in_gates` 加 `p1[4]`。

## 5. 验证结果（v2.116 落地态）

1. **基线（从严 368 字）**：clean 0/6 + vio1-5 全 6/6——短 gate thrash 又一实证；
   **vio5 零轮引对条款**（㉖ 错理由拦对教科书实例，见 §1 表）。
2. **文本迭代 v1-v3**（纯 gate 反转）：v1（2662 字，五方框）clean 5/6 + vio1 **4/6**
   （方框一的 callers 豁免被泛化成「字段篡改全免判」——㉓/#15 抑制类钉句必双侧化第
   N 实例）+ vio5 5/6；v2（3140 字，方框一豁免作用域钉死 + assumptions「无」合法化）
   vio1 回 6/6 但 vio5 4/6 + vio3 5/6 + clean 5/6（**根因单一**：方框五把合法理由源
   写成封闭枚举「引子3 核验事实或子4 净分…任一项」，judge 反读成白名单 -> clean 的
   「双向追溯判镀金」理由不在册被 block、vio5 判面同时被窄化）；v3（3267 字，理由源
   改开放式 + 显式「列举是示例不是封闭清单」）**clean 6/6 + vio1-4 全 6/6**，vio5
   4/6 卡住。
3. **vio5 三版读数 5/6 -> 4/6 -> 4/6 且判词全引对条款、放行轮为纯注意力方差**
   = ㉗ 区分线的「judge 侧 4-5/6 抖动」-> 触发 §3 预案的 mech 下沉（**非措辞打地鼠**）。
4. **mech 落地**：`rejected_rationale_trace`（statements 侧**第二个** mech，
   `_MECH_STATEMENTS_CHECKS` 注册）——被否标签面（`候选X`/`被否形态`/`被否路径`）×
   解释性词形面（理由/因为/净分/触发/不复用/影响面/镀金/迁移/H\d/impact…）双词表，
   标签在场而解释缺席即拒。**对载荷集 100% 精确**：只拒 vio5，clean 与 vio1-4 全静默
   （#30 (53) 空转检查已跑：先验「对 vio 触发、对 clean 静默」再写单测）。
5. **mech 注册后的 clean 复测**（#30 ㉑① mech harness 注是 clean 的隐藏杠杆——本例
   **反向**实证）：v6（3494 字）clean 6/6，但落地后同文本复跑 clean 4/6——mech_scope
   注入使 judge 判面重排，暴露两个新聚类：①复合句新拆法「呈现位置决策 vs 呈现指标
   决策可分别拍板」；②acceptance_map SC ID second-guess（「该 SC 应由其它项承接」）。
   v7（3675 字）近端双侧钉死两者后 **clean 6/6**。
6. **落地态（v7 gate + rejected_rationale_trace mech，n=6 × 2 轮）**：
   clean 6/6 与 5/6 + vio1 5/6 与 6/6 + vio2 6/6+6/6 + vio3 6/6 与 5/6 +
   vio4 6/6+6/6 + vio5 2/6 与 4/6（mech 生产墙托，judge 被告知「已机械校验」放行=
   设计内委托，同 plan:2#4 vio4 范式）。**两轮达标线全过**（clean ≥5/6、语义 vio ≥5/6）；
   第二轮 clean 的唯一 block 是**自相矛盾判词**（逐条走完五方框全判「合规/OK」后仍
   pass=false，判词原文「判据二/三/四/五合规。判据一再次审视…」）= ㉑ 认定的推理底
   噪声轮，非判据缺陷，不回炉（同 plan:2#3 ④「clean 5-6/6 是推理底下的可达地板」）。
7. **判词引对条款抽读**（㉖）：vio1 6/6 全引方框一（「子4 已否决候选的改动被写进
   type_label=推荐项」逐字）、vio2 6/6 全引方框二复合句、vio3 5/6 引方框三凭空新增、
   vio4 6/6 引方框四假设淡化——**不靠宽泛词形接牙，基线 vio5 的错理由牙已由 mech 接管**。
8. **756 tests 全绿**（754 既有 + 新增 mech 单测 + 改钉 pin）；ruff check/format 全过；
   `gate.strip()==candidate.strip()` 逐字一致断言每版必跑（㉕/#24③）。

**pin 审计漏网与处置**（㉔ 第二实证）：前置审计只 grep 了 `_ATOMIC_ITEM_RULE` /
`_SOLUTION_FREE_SUBJECT_RULE` 常量族与 gate 短语，**漏了 `TestPlan1Orchestration::
test_step5_normalization` 的 `"不传导" in s5.gate` needle**（从严版判词短语，非常量），
落地后全测试当场逮住。处置=改钉三条精化条款（`与子3/子4 已定内容不一致` / `假设淡化`
/ `rejected_rationale_trace`）+ `mech_checks` 断言，钉死意图（字段传导 judge 侧有判面）
不丢。**纪律**：pin 审计的第三路 grep = 从严版 gate 的**判词短语**（不只常量名与坐标族）。

## 6. 影响面

- `dl_flow_engine.py`：`_REJECTED_LABEL_RE` + `_REJECTED_RATIONALE_RE` +
  `_check_rejected_rationale_trace` + `_MECH_STATEMENTS_CHECKS` 注册第二项
  （H15 codegraph 查询留痕前置：`codegraph callers _check_sc_coverage_trace` 无 callers
  [注册表 dict 派发]、`codegraph impact _MECH_STATEMENTS_CHECKS` 仅自身定义点）
- `dl_flow_nodes.py`：plan:1 子5 gate 改写（368 -> 3675 字）+ `mech_checks=
  ("rejected_rationale_trace",)`
- `tests/test_dl_flow_engine.py`：`test_p1s5_rejected_rationale_block_pass_skip`（新增）
  + `test_default_pass_marker_pinned_in_gates` 加 `p1[4]` + `test_step5_normalization`
  的 `不传导` pin 改钉精化条款
- `tests/replays/replay_plan1_sub5.py`（新增）+ `tests/replays/README.md` 清单加一行
- `designs/plan1-sub5-gate-framing-design.md`（本文件）

## 7. 并发协作

worktree `~/dl-wt-plan1-sub5`（collab #26），并行三会话在飞（plan:4#1/#3/#4）。
共享 sediment 文件（`skills/.../rubric-design.md`、`collab.md`）在本 worktree 内改动
不与他人交织（物理隔离），收口 merge 时 git 正常处理时序冲突。
版本号/例数提交前 git log + 全域 grep（主仓 + `~/dl-wt-*/`）双复核，撞号顺延
（collab #25 禁死守自号）。
