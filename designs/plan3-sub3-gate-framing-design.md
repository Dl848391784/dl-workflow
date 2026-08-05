# plan:3 子3（匹配选型）gate framing 反转设计（v2.110）

> 2026-08-05。§3.5 #30 泛化第二十七例、#30 playbook 第二十七次执行：把「默认-PASS
> framing + 方框化真值判据 + 每条近端双侧钉死」应用到 plan:3#3（匹配选型）。
> **plan:3（选择能力与工具）第三个反转节点**（plan:3#1 需求清点 v2.106 / plan:3#2
> 能力盘点 v2.107 已入库）。用户坐标指令「plan:3#2 正在进行泛化处理，请继续泛化
> plan:3#3」。
> 版本号：**取号 v2.110**——入库最大 v2.109（plan:2#4 第二十六例，472c2f1）；并发期
> 在飞 plan:3#4/plan:4#1/plan:4#2 三会话（git worktree 均在、未落 v2.110 声明）。
> 例数=**泛化第二十七例**。
> **改动范围**（H8 留痕）：`dl_flow_nodes.py`（plan:3 子3 gate 块 + Step.mech_checks）+
> `dl_flow_engine.py`（binding_residue_trace mech）+ `tests/replays/replay_plan3_sub3.py`
> （新建）+ `tests/test_dl_flow_engine.py`（pin 改钉 + mech 单测）+ `tests/replays/README.md`
> （清单行）+ 本设计文档。

## 0. 本节点结构（决定判面怎么切）

| 维度 | 值 |
|---|---|
| record_format | qa（无 statements 归一化族问题，⑰ 允许 mech 下沉） |
| mech_checks | 本轮下沉 **binding_residue_trace**（v1 实证跨步差集 judge 判不了，⑤/②） |
| artifact 组成 | **子1+子2+子3 三 trace 拼合**（生产 read_evidence_for_step(3,"CapabilityToolSelection") 同形；S1/S2 是判材非纯组成事实——无绑定残留需读 S2 注册表①，强制项定义需读 S2 ③强制路由核对，理由出处对照需读 S2） |
| 输入锚 | **step2.capability_registry + step1.need_baseline（S1/S2 trace 载荷内可见）+ 真实注册表真值（结构性不可见）** |
| 命题性质 | **需求×能力映射提案**（覆盖/最小集/成本相称/强制优先四判据+双向追溯+条件红队+提案语义）--主敌=映射面「幽灵与错配」：tool overload 95%→71%（design §4 实证）/凭名字猜绑定/强制项被顺手替代/重型手段不辩护/替用户拍板五类 |
| vio 类型 | vio1 无绑定残留=过载 / vio2 绑定理由无出处=凭名字猜 / vio3 强制项被替代无辩护 / vio4 重型手段无成本辩护 / vio5 替用户拍板无提案语义 |
| gate 长度 | 基线 459 字（从严）--短 gate thrash 候选 |

判材边界：
- **S1/S2 在载荷内可见** -> 跨步对照可判：残留（S2 注册表① vs S3 全答案）、强制项定义（S2 ③强制路由核对）、理由出处对照（S2 ③/列表行）；
- **真实注册表真值不可见**（available-skills 列表/磁盘目录/MCP 配置/CLAUDE.md §2 原文
  不在载荷内）-> 能力名以 S2 trace 自述为准，只判 trace 内自洽与留痕在场，不核真实
  注册表（同 plan:1#1/plan:2#2 留痕投影族，⑯-safe）；
- 绑定理由的语义正确性（该能力是否真适合该需求）不判。

## 1. 基线数据（MiniMax-M3，n=6，现 gate 459 字从严版）

| 载荷 | 期望 | 命中 | 判词性质 |
|---|---|---|---|
| clean（映射+理由(子2 出处)+被否替代+最小集+双向矩阵+强制项保留+条件未触发+提案语义） | PASS | **2/6** | 4 轮误伤全 judge 发明要件 |
| vio1 无绑定残留（a2 删 `factor-ic-analyzer-workflow` 不加载声明，S2 注册表有该名） | BLOCK | **5/6** | **全错理由拦对**：5 轮全引其它条款（子2 出处/强制项逐项证明/未逐条绑定理由），无一引残留——真实违规 0/6 被逮 |
| vio2 理由无出处（a1 首条绑定理由删全部子2 出处） | BLOCK | 5/6 | 3 轮引对「凭名字猜」+1 轮引重型手段（错）+1 轮引被否替代出处（错） |
| vio3 强制项被替代（a3 H15 codegraph 换 grep 无辩护） | BLOCK | 6/6 | 全引对（强制项优先），含自我矛盾识别 |
| vio4 重型无辩护（a1/a2 加 T4 子代理扇出、a3 无成本辩护） | BLOCK | 6/6 | 全引对（重型手段成本相称辩护） |
| vio5 替用户拍板（a4 改定案口吻） | BLOCK | 6/6 | 全引对（只提案不拍板） |

**判读**：459 字短 gate clean 2/6 = 短 gate thrash（#28 第三实证同批）。vio3/4/5 牙齿
6/6 全引对=judge 判得动，误伤纯 framing 致病（㉛ 问三）。**但 vio1/vio2 有失牙风险**
（㉖）：vio1 5/6 全错理由拦对=目标条款零命中，反转合法化错理由词形时牙齿必连带掉；
vio2 3/6 引对=部分错理由牙。须预判每颗牙由哪个方框接（vio1 归方框一残留、vio2 归
方框二出处）。

### 1.1 误伤模式聚类（clean 4 轮误判判词逐字）

| # | 模式 | 判词摘录（逐字） | 性质 |
|---|---|---|---|
| 1 | **绑定理由须逐字引用子2 trigger/description 原文** | [1]「『理由引用子2 ③强制路由核对出处…』是子2 的归纳结论复述，未逐字引用子2 自身输出的 trigger/description 文本」 | judge 发明要件（归纳引用即合法出处，不要求逐字复述） |
| 2 | **重型手段枚举被扩面** | [4]「未对『一次性 3 个 skill 叠加到同一 .py 代码改动任务』这一相对重的组合逐项说明成本相称」[6]「H15 codegraph CLI 留痕…属小型密集重复外部调用，未附成本相称辩护」 | judge 发明要件（重型手段=Workflow 多 agent/子代理扇出/长 pipeline 三类固定枚举；3 skill 叠加/本地 codegraph 查询不属） |
| 3 | **被否替代理由须引子2 出处** | [5]「factor-development 被否替代仅说『无报告聚合规范承接』，未引子2 触发描述作出处」 | judge 发明要件（被否替代只需在场、不需出处） |

**㊹ 待复核标记**：vio1/vio2 基线判词顺带引的「子2 trigger/description 须逐字」「被否
替代须出处」「重型手段扩面」在反转后必须消失，相关牙改由目标方框/mech 独立支撑——
三向验证时按此抽读（㉖ 口径）。

## 2. 反转后的判据设计（v1：默认-PASS framing + 五方框）

结构：形式要件（保留 `_CTS_STEP3_FORM_REQUIREMENTS` f-string 单源）+ 默认 pass 声明 +
**五方框**（每条 block 面+legal 面近端双侧钉死，词形取 §1.1 误判判词逐字）+
【判材边界】段 + 【合法正例】段 + 条款引用要求。

- **方框一·无绑定残留=过载**（vio1）：block 面=S2 注册表①枚举能力名在本步既无绑定也
  无不加载判 block；**显式检测指令**（逐条检查 S2 ①/②能力名在本步是否出现）。legal 面=
  每个能力名绑定或不加载任一场即合规、不加载多条合并一句、内置工具集不在绑定面。
- **方框二·绑定理由无出处**（vio2）：block 面=某条绑定理由未引用子2 trigger/description
  出处（③出处/列表行/触发词引用任一）；legal 面=归纳引用即合规、同类型任务合并理由
  即合规、内置足够项不需理由与被否替代、被否替代只需在场不需出处。
- **方框三·强制项被替代**（vio3）：block 面=强制项（S2 ③强制路由核对留痕）被非强制项
  替代且无辩护；legal 面=强制项按强制保留即合规、替代附「满足原强制意图」式辩护即合规。
- **方框四·重型手段无成本辩护**（vio4）：block 面=重型手段（三类固定枚举）在场却无成本
  相称辩护；legal 面=附成本/收益论证即合规、未绑定重型手段声明「条件未触发」即合规、
  **三类枚举固定**（治聚类 2）。
- **方框五·替用户拍板**（vio5）：block 面=映射以定案/决定/据此执行口吻呈现；legal 面=
  提案口吻（提案/拟绑定/待子6 裁决任一）即合规、整段一句提案声明覆盖全部绑定。

【判材边界】：S1/S2 可见跨步对照可判；真实注册表不可见不得以「无法核实该能力真在
注册表/该触发词真在 §2」block；绑定理由语义正确性不判。

【合法正例】：理由引子2 出处+被否替代在场；不加载合并一句；无重型手段声明；提案口吻。

### 2.1 候选文本迭代（基线 + v1，n=6 MiniMax 重放）

| 版本 | clean | vio1 | vio2 | vio3 | vio4 | vio5 | 关键改动 |
|---|---|---|---|---|---|---|---|
| 基线(从严) | 2/6 | 5/6(全错理由) | 5/6 | 6/6 | 6/6 | 6/6 | 459 字短 gate thrash；vio1 真实违规 0/6 |
| v1 | **6/6** | **1/6** | **6/6** | **6/6** | **6/6** | **6/6** | 五方框反转+显式检测指令；clean 与 vio2-5 全达标；**vio1 残留仍判不了**（[1] 那轮还错引方框五[矩阵陈述读成定案口吻]） |

**v1 判读**：clean 0/6→6/6 一次到位（误伤源全 judge 发明要件、每条独立可钉=㉛ 低跷跷板）；
vio2-5 全 6/6 由目标方框接住（㉖ 失牙预判兑现）。**vio1 残留 1/6 = plan:2#4 ② 第二实证**：
显式「检测：逐条检查 S2 注册表…」遍历指令也被弱 judge 忽略，跨步 S2→S3 差集枚举超出
judge 主动注意面——**差集形下沉 mech 是正治，别再耗措辞轮次**（⑤/②/㉗ 判别线）。

## 3. mech 下沉（v2）：binding_residue_trace

**触发**：v1 显式遍历指令 1/6 仍判不了=跨步差集结构性不可判（同 plan:2#4 sc_coverage_trace
根因）。词形子项（S2 注册表①能力名 vs S3 全答案出现集差集）可机械判。

**实现**：
- `_REGISTRY_CAPABILITY_RE = r"\`([^\`]+)\`（列表行）"`——S2 ① skill 注册表条目固定
  标注「（列表行）」，用它排除 S2 里其它反引号 token（内置工具集/路径如
  /home/admin/.npm-global/bin/codegraph——首版全反引号提取被路径 token 污染，clean 误报）；
- `_check_binding_residue_trace(qa, project_root, name)`：读 S2（`read_evidence_for_step`
  (2,"CapabilityToolSelection")）取注册表能力名集 → 逐名检查在本步全答案子串出现
  （绑定或不加载任一生效，含被否候选=已处理）→ 缺=拒。
- **宁纵勿枉**：S2 缺失/S2 无（列表行）标注能力名=放过交 judge（非双失，judge 仍可判
  残留语义面）。

**验证（fixture 集）**：clean missing=[] / vio1 missing=['factor-ic-analyzer-workflow'] /
vio2-5 missing=[]（单测 pin）。replay judge 侧 vio1 期望读数 **0/6=设计内委托**（㉗ 判读
纪律：gate 声明机械校验后 judge 对该载荷 0/6 是设计内，replay docstring 写明生产墙=
mech 先拒；EXPECT 仍标 BLOCK 是违规载荷）。

**gate 方框一改 mech-托声明**（plan:2#4 §一 同范式）：「无绑定残留已由 binding_residue_trace
机械校验——S2 注册表能力名无绑定且无不加载的载荷已被 append-trace 当场拒、不会到你
这里；你不得以『无绑定能力残留/能力未映射』为由 block；残留判面=无，能力适配性本就不判」。

**顺带修 v1 发现的方框五误伤面**：vio1[1] 那轮 judge 把 a2「双向追溯矩阵…无无绑定能力
残留」读成定案口吻（方框五）。方框五 legal 面补「双向追溯矩阵的『无漏/无残留/每需求有
绑定』类陈述是矩阵事实描述非映射拍板，不得据此判无提案语义」。

## 4. 验证结果（v2 实测）

1. **三向 n=6**（v2 生产 gate）：clean 6/6 ✓ + vio2/3/4/5 全 6/6 ✓ + vio1 judge 侧 **0/6**
   （设计内委托，mech 单测 100% 接住）——clean 与 vios 判词全部引对条款且判空理由=
   完美 mech 委托，方框五误伤面（矩阵陈述当定案）消失。
2. **判词引对条款抽读**（㉖）：vio2 5/6（[3] 那轮=注意力噪声空判词）全引方框二
   「绑定理由无出处/凭名字猜」并点名 `factor-development` 缺子2 出处+改写范例；vio3/4/5
   各 6/6 引方框三/四/五；vio1 全 pass=True 且 reason 空（judge 完全让位 mech，无任何
   误伤词形残留）。
3. **㊸ 落地三件套**：f-string 形式要件单源 + 逐行 \n 显式转义 + `gate.strip()==candidate.strip()`
   逐字断言通过（2513 字）；ruff format 后复断言通过（format 重排 5 文件未动 gate 字面）。
4. **pin 改钉**（#30 ①/㉔）：`test_step3_matching_redteam_fence` 原钉
   `("sub_step==3", "过载", "凭名字猜", "替代", "拍板")`——「过载」词形撤出 gate（方框一
   改 mech-托声明），pin 改钉压缩条款（「无绑定能力残留」「绑定理由无出处」「强制项被
   非强制项替代」「重型手段」「替用户拍板」）+ framing 标记「默认 pass」+ mech 注册断言
   （`s3.mech_checks == ("binding_residue_trace",)`）。
5. **mech 单测**：TestBindingResidueTrace（clean 零 FP + vio1 命中 + S2 缺失宁纵勿枉 +
   S2 无反引号（列表行）能力名提取不出集宁纵勿枉）。
6. **全测试**：754 passed（原 750 + pin 改钉 3 断言 + mech 单测 1 例）；`ruff check .`
   All checks passed；format 后复跑 754 passed。

## 5. 并发协作

并行会话在飞 plan:3#4/plan:4#1/plan:4#2（git worktree 已建）。共享文件 `dl_flow_nodes.py`
/ `dl_flow_engine.py` / `tests/test_dl_flow_engine.py` / `tests/replays/README.md` 可能混
多方未提交改动——按 collab #9 只 add 显式清单，不用 `git add -A`。版本号/例数提交前
git log + 工作区自称双复核（collab #13/#20）。`dl_flow_nodes.py`/`dl_flow_engine.py` 编辑
触 H15 codegraph 门禁，每次编辑前跑 codegraph 查询留痕。
