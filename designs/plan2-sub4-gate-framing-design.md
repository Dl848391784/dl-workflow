# plan:2 子4（归一化步骤）gate framing 反转设计（v2.109）

> 2026-08-05。§3.5 #30 泛化第二十六例、#30 playbook 第二十六次执行：把「默认-PASS
> framing + 方框化真值判据 + 每条近端双侧钉死」应用到 plan:2#4（执行步骤归一化）。
> **plan:2（拆解任务与阶段）第四个反转节点**（前三=plan:2#1/#2 已入库；plan:2#3
> 锚点核验已由并行会话落地 v2.108）。
> 用户坐标指令「plan:2#3 正在进行，本会话取 plan:2#4，从 main 拉新分支开发完合并」。
> 版本号：取号 v2.109 = max(入库 v2.108[plan:2#3])+1（collab #13/#20 提交前双查：
> v2.105 被三方自称[plan:2#3/plan:3#2/plan:2#4]、v2.106/107/108 已入库、
> v2.107 空缺；「泛化第二十三例」已被另一并行会话自称->本例取 v2.109/第二十六例）。
> 例数=泛化第二十六例（第二十二=plan:2#3 / 第二十四=plan:3#1 / 第二十五=plan:3#2 /
> 第二十三=另一并行会话在飞）。

## 0. 本节点结构（决定判面怎么切）

| 维度 | 值 |
|---|---|
| record_format | **statements**（载荷 `{"text","type_label":所属阶段,"boundary","fields":{change_point/interface/verify/acceptance_map/trace_anchor}}`，statement_fields 五键） |
| mech_checks | **sc_coverage_trace**（statements 侧**首个 mech**，u:2#4 预留「statements 侧注册表」独立项的解、#30 ⑰ 的解；原 mech_checks 循环只在 qa 分支执行，本例补 statements 注册表 `_MECH_STATEMENTS_CHECKS`）--承接跨步判据 vio4（见 §3 跷跷板实证） |
| 内建机械层 | statements 五键非空（**无条件** JSON 校验，写侧）+ text/boundary/type_label 非空 -> 可声明「已机械校验不得 block」 |
| artifact 组成 | **子1+子2+子3+子4 四行 trace 拼合**（生产 read_evidence_for_step(4,"TaskBreakdown") 同形；子1=验收包清单+要素基线、子2=单元定义+依赖、子3=锚点核验+三态均是判材非纯组成事实--字段一致性/验收包映射对照需读前序） |
| 输入锚 | **step3.verified_units + step1.element_baseline（子1/子2/子3 trace 载荷内可见）**--与 plan:2#1 关键差异：plan:2#1 的 design.md 跨阶段 .md 文件结构性读不到，本步前序 trace 全在载荷内->跨步字段一致性+验收包映射均可判 |
| 命题性质 | **执行步骤归一化**（从子2 任务单元+子3 锚点核验推导 statements 五字段执行包）--主敌=「长链转换失真与未原子化」：字段篡改/复合未拆/验证不可执行/验收包漏项四类，与 u:2#4「归一化陈述」同构（u:2#4 主敌=分层传导断裂+复合+方案名词） |
| vio 类型 | vio1 字段篡改 / vio2 复合句 / vio3 验证不可执行无辩护 / vio4 验收包映射漏项 |
| gate 长度 | 基线 392 字--短 gate thrash 候选（前例 534/368/428 等；短 gate 从严 thrash 第十二实证） |

判材边界（㊿ 三选分治的可见性分治变体）：
- **子1/子2/子3 trace 载荷内可见** -> 字段一致性（vio1，子4 fields vs 子2 单元定义/子3
  验证命令）+ 验收包映射（vio4，子1 验收包清单 SC ID vs 子4 acceptance_map）= trace 内
  自洽可判，非「判不了的存在性真值」；
- **design.md 跨阶段文件结构性不可见** -> 但子1 已提取验收包/要素为载荷内清单，不得以
  「无法核验收包与 design.md 一致/要素是否真在设计包」block（⑯-safe 无降级面）；
- **codegraph db 真值不可见** -> 不核 symbol 真实调用关系（子3 已留痕即可，本步不重判）。

## 1. 基线数据（MiniMax-M3，n=6，现 gate 392 字从严版）

| 载荷 | 期望 | 命中 |
|---|---|---|
| clean（三 statements 归一化 U1/U2/U3，五字段忠实提取子2/子3，验收包 SC1.1/SC2.1/SC3.1 全映射，要素 E1/E2/E3 全承接，假设 H1 原样携带） | PASS | **0/6** |
| vio1 字段篡改（U2 change_point「增加分组键」->「重写为独立八维度聚合器，输出全新数据结构」） | BLOCK | 6/6 |
| vio2 复合句（U2 text「增加分组键，以及新增独立的分组校验脚本」） | BLOCK | 6/6 |
| vio3 验证不可执行无辩护（U3 verify「人工看一下报告里八维度区块对不对」） | BLOCK | 6/6 |
| vio4 验收包映射漏项（SC3.1 在所有 acceptance_map 缺失） | BLOCK | 6/6 |

**判读**：392 字短 gate clean 0/6 = 短 gate thrash 第十二实证；vio 牙齿全 6/6 =
㉛ 问三「牙齿全满->judge 判得动，误伤纯 framing 致病」--反转即治。vio2/3/4 全
对理由（逐条引复合句/验证不可执行/验收包漏项）；vio1 混合（3/6 引篡改、3/6 引
复合/验证误伤词形）--反转后误伤词形合法化，vio1 的牙须靠方框一（字段篡改）独立
支撑，㉖ 失牙风险盯 vio1。

### 1.1 误伤模式聚类（clean 6 轮判词逐字）

| # | 模式 | 判词摘录（逐字） | 性质 |
|---|---|---|---|
| 1 | **验收包映射 second-guessing（归属错位）** | [1]「E3/U1 路径常量被映射到 SC3.1，但 SC3.1 是报告新增八维度汇总区块，应由 E2/U3 覆盖」[4]「U1 acceptance_map 仅写 SC3...」 | 推理底（second-guess 映射语义合理性，判材边界违反；**双面源**：伤 clean + 给 vio1 错理由牙） |
| 2 | **TDD 微循环=复合流程** | [2]「verify 写『failing test...期望失败->通过』是 TDD 微循环『失败测试->最小实现->验证->提交』内含流程」[3]「verify 字段内嵌...TDD 微循环=复合流程描述」[6]「未声明产物中未见 TDD 微循环」 | judge 发明要件（gate 明文 TDD 微循环不算复合；judge 反读内含流程为复合，#23 文本与判据矛盾变体） |
| 3 | **acceptance_map 多 SC=合并两项验收** | [3]「acceptance_map 第2项合并 SC1.1+SC2.1 两项验收」 | judge 发明要件（一项交付物映射多条验收包=合法枚举，非复合；字段值枚举不算复合的 _ATOMIC_ITEM_RULE 边界） |
| 4 | **验证方法 second-guessing（须覆盖下游）** | [5]「U1 verify 仅断言常量存在，而 trace_anchor/change_point 要求 U1 还需为下游 U2/U3 提供 CATEGORY_SUMMARY_RESULT 作...」 | 推理底（second-guess 验证范围，发明 U1 须测下游消费；判材边界违反） |

㊹ 待复核标记：vio1 判词顺带引的误伤词形（验收包错位/验证范围 second-guess）在
反转后必须消失，vio1 的牙改由方框一（字段篡改）独立支撑--三向验证时按此抽读
（㉖ 口径）。若反转后 vio1 只剩被合法化的词形=⑤/⑭ 压跷跷板实锤，但本节点
statements 格式不能注册 mech（#30 ⑰）->须靠方框一措辞 + 判材边界双侧钉死接住。

## 2. 反转后的判据设计（默认-PASS framing）

结构：形式要件（保留：每项=1 交付物 + fields 五键齐备[append-trace 已校验勿再数字段]
+ 验收包与要素双向覆盖）+ 默认 pass 声明 + **四方框**（每条 block面+legal面 近端
双侧钉死，词形取 §1.1 误判判词逐字）+ 【判材边界】段 + 【合法正例】段 + 条款引用要求。

- **方框一·字段与子2/子3 已定内容不一致（丢失/篡改/新增）**（vio1，跨步一致性）：
  block 面=某项 change_point/interface/verify 与子2 单元定义或子3 锚点核验结果矛盾
  （篡改措辞致语义变化/丢失已定内容/新增子2 子3 未定内容）判 block；legal 面=忠实
  提取/适度压缩/同义转述即合规，不要求逐字一致（「增加分组键」转述为「加维度分组」
  合法）--语序调整/同义替换/细节省略不判；子3 假设项原样携带（不丢不淡化）即合规。
- **方框二·复合句（未原子化）**（vio2，正判定）：block 面=一项 text 合并 ≥2 个可
  独立成立/可分别提交的交付物判 block；legal 面=TDD 微循环「失败测试->最小实现->
  验证->提交」=交付物内含流程不算复合（治聚类 2）；字段键值枚举（acceptance_map 列
  多个 SC ID、interface 列 Consumes+Produces）= 结构化携带不算复合（治聚类 3）；
  {_ATOMIC_ITEM_RULE}。
- **方框三·验证方法不可执行且无辩护**（vio3，正判定）：block 面=verify 字段写
  「人工看一下/检查一下」式不可执行验证且无显式辩护判 block；legal 面=failing test
  名+命令+期望输出（可执行验证优先）即合规；命令+期望退出码即合规；不可执行验证附
  显式辩护即合规--不得以「验证不够详细/未含期望输出全文」block（治聚类 4：verify
  只判本单元交付物可执行验证，不核是否覆盖下游消费）。
- **方框四·验收包映射漏项**（vio4，跨步一致性）：block 面=子1 验收包清单某
  SuccessCriteria ID 在子4 statements 无任何项 acceptance_map 承接判 block；逐项核对
  （从子1 取每个 SC ID，确认其在子4 某项 acceptance_map 出现）；legal 面=每个 SC ID
  ≥1 项承接即合规--**acceptance_map 归属不核语义合理性/错位**：SC ID 被任一项承接即
  合规，同一 SC 可被多单元承接（基础贡献+直接交付），不得以「SC X 应由 U Y 承接而非
  U Z / 映射错位 / 归属不当」block（治聚类 1）。

【判材边界】（治聚类 1/2/3/4）：子1/子2/子3 trace 载荷内可见->字段一致性+验收包映射
可判；fields 五键非空已由 append-trace 机械校验，不得以「缺键/字段为空」block；TDD
微循环=failing test 先行即合规（不得要求通过测试闭环展开，治聚类 2）；acceptance_map
列多个 SC ID / interface 列 Consumes+Produces=字段枚举不算复合（治聚类 3）；verify 只
判本单元交付物可执行验证，不核是否覆盖下游 U2/U3 消费（治聚类 4）；验收包映射只判
SC ID 覆盖，不核归属语义合理性（治聚类 1）；design.md 跨阶段文件结构性读不到但子1 已
提取验收包/要素为载荷内清单，不得以「无法核验收包与 design.md 一致/要素是否真在设计
包」block；codegraph db 不可见->不核 symbol 真实调用关系（子3 已留痕即合规）。

【合法正例】（各聚类合法形态落位）：「change_point: paths.py:+CATEGORY_SUMMARY_RESULT
（增）」合规（忠实提取子2 单元定义）；「verify: failing test test_xxx 断言...；命令
pytest ...；期望失败->通过」合规（TDD 微循环内含流程，不判复合）；「acceptance_map:
SC1.1、SC2.1」合规（多 SC ID 枚举，不判合并）；「acceptance_map: SC3.1（基础路径常量
为区块输出奠基）」+ 另项「SC3.1（直接渲染区块）」合规（同 SC 多单元承接，不判错位）；
「trace_anchor: E1」合规（要素 ID 承接）；「boundary: 假设 H1 传导（...原样转录
design.md:25）」合规（假设原样携带）。方框以外一律不判。judge 判 block 须在 reason
引用判据条款并附 1 个正确改写范例（指模式不指实例位置）。

## 3. mech 下沉（statements 侧首个 mech，⑤ 跷跷板实证后正治）

**原判（§初稿）**：本节点 record_format=statements -> 原 mech_checks 循环不执行
（#30 ⑰，循环在 qa 分支内），预期四判据全靠 gate framing（同 u:2#4 一轮达标先例）。

**实证推翻**：v1-v8 八版措辞迭代确认 **vio4（验收包映射漏项，跨步）= 跷跷板实锤**（⑤）：
- vio4 judge 读数跨版摆 2/6-6/6（措辞强则伤 clean、弱则漏判 vio4，同 plan:2#2 vio4 型）；
- clean 因 form要件「验收包与要素双向覆盖无漏」措辞被 judge 发明「映射归属/单单元承接
  可疑」要件误伤（clean [6] 判词逐字「SC3.1 仅在子4 第三项承接」仍 block=完备后发明归属
  要件）；
- 跨步枚举（子1 SC ID 集 vs 子4 acceptance_map 差集）对无 CoT 弱 judge（MAX_THINKING_
  TOKENS=0）结构性不可靠——与 plan:2#2 当年下沉 element_coverage_trace 同款根因。

**正治（弱模型优先：系统侧杠杆非措辞）**：落地 statements 侧**首个 mech** sc_coverage_
trace（u:2#4 预留「statements 侧注册表」独立项的解、#30 ⑰ 的解）：
- engine 新增 `_MECH_STATEMENTS_CHECKS` 注册表 + statements 分支 mech 循环（与 qa 分支
  同款，签名 `(statements, project_root, name)`）；
- `_check_sc_coverage_trace`：读子1（read_evidence_for_step(1,"TaskBreakdown")）取验收包
  SC ID 集（`\bSC\d+\.\d+\b`），与子4 全部 acceptance_map 的 SC ID 集做差集，差集非空即
  拒。宁纵勿枉：子1 缺失/无 SC ID/无 acceptance_map=放过交 judge；个别单元「无直接验收包
  承接」合法（只判全局覆盖）。纯 token 扫描，⑯-safe（读子1 是文件读非 db）。
- gate 方框一改 mech-托声明（「已由 sc_coverage_trace 机械校验，不得以漏项/覆盖不全
  block」），judge 只剩 vio1/2/3 三判据。

vio1/2/3 留 gate 判（措辞对正判定/本步内判据有效，基线对理由 6/6）：vio1 字段篡改（跨步，
子2/子3 载荷内可见，方框二措辞可救，实测 6/6）、vio2 复合句、vio3 验证不可执行。

## 4. 验证标准（同 #28/#30 ⑥ + mech 托读数口径 #30 ⑦）

三向 × n=6：clean 全 PASS + vio1-3 ≥5/6 BLOCK + vio4 mech 生产墙托（judge 读数低=设计内
委托，同 plan:2#2 vio4/vio5 范式）+ mech 单元测试零方差证拒 + 既有 pin 测试全绿。

## 5. 验证结果（v2.109 落地态）

1. **基线（从严 392 字）**：clean 0/6 + vio1-4 6/6（vio2/3/4 对理由、vio1 混合）=短 gate
   thrash 第十二实证。
2. **措辞迭代 v1-v8**（statements 单杠杆尝试）：vio1-3 升至 6/6，但 vio4/clean 跷跷板
   （vio4 2-6/6 摆、clean 4-6/6 摆）->⑤ 实锤，触发 §3 mech 正治。
3. **落地态（gate + sc_coverage_trace mech，n=6×2 轮）**：clean 6/6+6/6 + vio1 6/6+6/6 +
   vio2 6/6+6/6 + vio3 6/6+6/6 + vio4 1/6+0/6（mech 托，judge 被告知覆盖已机械校验放行，
   设计内委托）。
4. **mech 单元测试 100%**：`test_p2s4_sc_coverage_trace_block_pass_skip`--三 SC 全漏拒/
   缺 SC3.1 拒/全覆盖过（个别单元「无」合法）/无子1 放过（宁纵勿枉）。
5. **判词引对条款抽读**（㉖）：vio1 全引方框二篡改、vio2 全引方框三复合句、vio3 全引方框
   四验证不可执行--不靠宽泛词形接牙。
6. **633 tests 全绿**（632 既有 + 新增 mech 测试）；ruff check/format 全过；
   `test_default_pass_marker_pinned_in_gates` 加 `p2[3]`。

## 6. 影响面

- `dl_flow_engine.py`：`_check_sc_coverage_trace` + `_MECH_STATEMENTS_CHECKS` 注册表 +
  statements 分支 mech 循环（H15 codegraph 查询留痕前置）
- `dl_flow_nodes.py`：plan:2 子4 gate 改写 + `mech_checks=("sc_coverage_trace",)`
- `tests/test_dl_flow_engine.py`：`test_p2s4_sc_coverage_trace_block_pass_skip` +
  default_pass_marker pin 加 `p2[3]`；step4 needles（`sub_step==4`/`不一致`/`复合句`/`漏项`）
  逐字保留
- `tests/replays/replay_plan2_sub4.py`（新增）+ `tests/replays/README.md` 清单加一行
- `designs/plan2-sub4-gate-framing-design.md`（本文件）

## 7. 并发协作

并行会话高速推进（本会话期间落地 plan:3#1 v2.106/第二十四例、plan:2#3 v2.108/第二十二例、
plan:3#2 v2.107/第二十五例，并提交 worktree-per-session 铁律 6a35903）。共享 checkout
被并行会话切回 main->本例工作以未提交改动现处 main（6a35903）工作树之上，与 plan:2#3 等
已入库改动自然叠加（本例 diff 仅增量）。
协调要点（collab #9/#13/#20）：只 add 显式清单分两次提交（先 docs[设计文档+replay]，后
feat[nodes gate+engine mech+test+README]），共享 sediment 文件 collab.md/rubric-design.md
**不提交**（非本例改动，留并行会话收口批）；版本号/例数提交前 git log+全仓 grep untracked
自称双复核（实证 v2.105 三方自称、第二十三例被另一会话占->取 v2.109/第二十六例）。
dl_flow_nodes.py/dl_flow_engine.py 编辑触 H15 codegraph 门禁，每次编辑前跑 codegraph 留痕。
