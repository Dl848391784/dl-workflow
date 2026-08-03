# understand:1 子1 两连 block 根治设计：反推词形下沉机械层 + 选项设计钉死（v2.68，2026-08-03）

> 事故：tail_volume_acceleration_annualized u:1 子1 第四轮 session 又两连 block
> （v2.64-66 修的是同一步的另两个根因——判据裁量漂移、手写载荷事故；本轮是
> 新根因）。用户质询两点：「为什么不一次性问完」「llm 只负责思考，其他全部
> 交给脚本」。本设计在动手前写（流程对齐 [[troubleshoot-fix-flow]]——
> v2.67 同会话曾漏写，用户指出后本版恢复 design-first）。

## 1. 问题：两次 block 的逐字根因（judge 两次都判对，系统规范不全）

证据：`.claude/evidence/tail_volume_acceleration_annualized.jsonl` 行 1-4
（两条 skill-trace + 两条 kind=gate block 裁决）。

**Att1 block——反推占答案位**：
- 模型只问了 3 类问题（who/后续动作/why-now），第 4 类「可观察后果」**没问
  用户**，a[3] 用「三项标签反推」填答案位（自己注明「反推项，不注入新事实」
  ——诚实披露），但「结论」仍把反推链（选因子决策→选错因子）写成事实。
- judge 依 `_PAIN_OBSERVABILITY_RULE`「痛点须为用户确认的可观察后果」判
  block——**判得对**。
- 系统缺口：`a` 里明写「反推/暗含/隐含」词形，机械层不拦——judge 白烧一轮
  （钉死保 judge 判对不保模型写对，§3.5 #16；一轮 block = 一轮 judge 调用
  + 一轮全量上下文重读，一次通过率=最大杠杆 v2.37）。

**Att2 block——选项设计违规（结构性必 block）**：
- 模型返工补问「下游哪个环节会产生不同动作？」——追问形式对了
  （`_PAIN_OBSERVABILITY_RULE` 模型侧退路的字面），**但 AskUserQuestion
  给的选项全是认知/信任类**（「报告整体可信度受损」「其他因子也会被一起
  质疑」）。
- 用户只点选项（v2.51 实证零打字原话）→ **只能点出认知类答案 → 结构性
  必 block**。模型再把「需一并复核→增加维护成本」包装成可观察后果，
  judge 判「编造包装」block——**判得对**。
- 系统缺口：**答案的类别在选项设计那一刻就决定了**，而所有规则只判答案、
  从不规范选项设计——裁量留白（§3.5 #4）+ 佐证无合法获取路径变体
  （§3.5 #7：选项全认知类时，动作类答案物理上不可获得）。

**「为什么不一次问完」**：
- 子1 恰好 4 类问题，AskUserQuestion 单次 ≤4 问（harness 工具 schema 硬限，
  不可改）**一轮装得下**；att1 问 3 留 1 反推没有任何系统依据，纯模型抄近路。
- `_INTERACTIVE_CHUNKING_RULE` 逐问原则只挂 8 读回步（防 >5min 用户思考击穿
  prompt cache），不适用子1 事实补问；子1 四问全是快答项，合并一轮正合
  chunking 规则「快答项合并一轮先问」精神。
- 超过 4 问时连续多问几轮合法（S15 无条件放行 AskUserQuestion，gate 只看
  最终载荷）——**多问几轮不算返工，提交后被 block 才是返工**。此语义从未
  写进指引。

## 2. 方案：三层系统杠杆（不换模型；LLM 管思考，脚本管形式）

**杠杆 1（机械层）`answer_no_reverse_inference`**：新 qa 写侧机械校验，
`a` 文本含「反推/暗含/隐含」当场拒（词形取 att1 a[3] 载荷逐字：「用户隐含
动作链」「三项标签反推」「暗含」「本项为反推项」——v2.49 词形取真实被
block 载荷逐字先例）。报错指路：该维度必须实际 AskUserQuestion 补问（或引用
上下文已有原话），推断标「推测」另列不占答案位。
- 豁免：含「推测」标注的项不拦（「推断标推测另列」是 `_STEP1_FORM_REQUIREMENTS`
  的合法形态，宁纵勿枉）。
- FP 风险：用户原话引用内含「隐含」字样——接受（宁纵勿枉方向=若 FP 投诉再
  加引号排除，先保 att1 形态必拦）。
- att1 从 judge block 变**机械秒拒**：省一轮 judge + 一轮全量上下文。

**杠杆 2（文案层双侧钉死）`_OPTION_DESIGN_RULE`**：新单源常量，
purpose/selfcheck（模型侧）+ gate（judge 侧）三处引用（对齐
`_USER_QUOTE_FORMS_RULE`/`_PAIN_OBSERVABILITY_RULE` 先例）：
- 模型侧：补问「可观察后果」类问题时，选项必须是**动作类**（哪个环节因此
  做什么不同动作，如「拿它选因子/调权重/停用报告」），并至少含一个出口项
  （「不改变任何动作/只是看看」——用户选它=按②申报的合法佐证）；纯认知/
  信任类选项 = 选项设计违规（用户只能点出认知类答案 = 结构性必 block）。
  动作类与认知类混列时用户选了认知类 = 如实记录为附带（认知类），按
  `_PAIN_OBSERVABILITY_RULE` 退路处理。
- judge 侧：block 根因是选项设计时，判词必须指向选项设计并给动作类选项
  范例——禁止只说「再追问」（追问形式对、选项错 = 再追几轮都一样 block，
  §3.5 #7 变体）。

**杠杆 3（一次问完钉死）**：`_STEP1_METHOD_GUIDANCE` 补：缺失维度在同一轮
AskUserQuestion 一次问完（单次 ≤4 问=本步 4 类正好一轮）；超过 4 问时连续
多问几轮、**问完再写 evidence**（多问几轮不属返工，提交后被 block 才是
返工）；禁止问一部分、反推剩余（反推占答案位 = 杠杆 1 机械拒）。

**分工边界**：att2 的「包装」（把认知类答案写成可观察后果链）内容质量判归
judge，不下沉词形（「→」链条词形 FP 面大）；机械层只拦 att1 形态（反推
自述词形），文案层治 att2 根因（选项设计）。结论字段已有
`conclusion_no_speculation`，不扩面。

## 3. 改动面

| 文件 | 改动 |
|---|---|
| `dl_flow_nodes.py` | 新常量 `_OPTION_DESIGN_RULE`；`_STEP1_METHOD_GUIDANCE` 补一次问完段；u:1 子1 Step 的 purpose/selfcheck/gate 三处引用 + `mech_checks` 加 `answer_no_reverse_inference` |
| `dl_flow_engine.py` | 新 `_check_answer_no_reverse_inference` + `_MECH_QA_CHECKS` 注册 |
| `tests/test_dl_flow_engine.py` | 机械校验 4 测试（att1 逐字 BLOCK / att2 逐字 PASS[包装归 judge 不拦] / 干净形态 PASS / 推测豁免 PASS）+ 双侧钉死 2 测试（purpose/selfcheck/gate 引用） |

## 4. 验证

1. TDD：先写 6 测试看红，再实现看绿。
2. 重放（v2.36 铁律：改判据必跑真实载荷重放）：
   - att1 载荷（a[3] 逐字）过新机械校验 → BLOCK；
   - att2 载荷（a[3] 逐字）过新机械校验 → PASS（包装判归 judge）；
   - att2 载荷过新 gate 文本 live judge 重放 → 维持 BLOCK 且判词指向选项设计
     （防新 gate 文本把 att2 翻转成 PASS——判据变味，rubric #15 抑制类钉句
     必双侧）。
3. 全量测试套件。
4. commit（dl-workflow 仓惯例：改完立即 commit，防另一会话卷入）。

## 5. 非目标

- 不改 AskUserQuestion 4 问上限（harness 硬限，不可控）。
- 不把「选项设计」做机械校验（选项在 AskUserQuestion 调用时产生、不进载荷，
  机械层看不到——只能文案钉死 + judge 判词指向；若日后 hook 能拦
  AskUserQuestion 的 options 再下沉）。
- 不动其他子步骤（本次证据仅 u:1 子1；`_OPTION_DESIGN_RULE` 常量化便于日后
  他步引用，不提前扩面）。
