# plan 域三归一化步迁 statements + statement_fields 设计

> v2.33（2026-07-31，用户拍板方案 b，三节点同批迁移）。
> 前序：v2.32「复合句」裁量点钉死（`atomic-item-rule-design.md`）治判据矛盾；
> 本刀治**载荷语义错配**——字段齐备判定从 judge 语义判断变 JSON 机械校验。

## 问题

tail_volume_acceleration_annualized（2026-07-29）plan:1 子5 / plan:2 子4 各三连
block + 用户强制放行。重放三条真实被 block 载荷（qa 格式）发现：每条 9 个 qa 对
里只有 3 个是真产出（设计陈述项），其余 6 个是元自查问答（「原子性（最严）…」
「是：3 条均内嵌八字段…」）。q/a 问答模具与清单型产出语义错配的三个后果：

1. **judge 要自己做信息分拣**——artifact 里陈述项与元问答混杂，att3 直接幻觉
   「无法证明记录已写入」（engine 是先拿到 trace hash 才调 judge 的，记录存在
   是机械已知事实，该判词可证伪为假）；
2. **形式要件无处机判**——「八字段齐备」「实现指针不入陈述」在自由文本里只能
   judge 判，而 judge 判形式要件是失真高发区（att1 称「数十个『。』断句」，
   实际 ≤1 个）；
3. **每轮白烧 output**——返工轮重写 6 条元自辨（v2.25 同类教训）。

## 方案（方案 b，用户 2026-07-31 拍板）

三节点归一化步 `record_format="statements"` + 新增 `Step.statement_fields`
（逐项 `fields` 对象的必备键），append-trace 逐键校验非空：

| 节点 | 步 | statement_fields |
|---|---|---|
| plan:1 DesignSolution 子5 | 归一化设计陈述 | change_list / interface_sig / data_contract / callers / rejected / assumptions / acceptance_map / h9_units（八字段） |
| plan:2 TaskBreakdown 子4 | 归一化执行步骤 | change_point / interface / verify / acceptance_map / trace_anchor（五字段） |
| plan:3 CapabilityToolSelection 子5 | 归一化能力包 | skill_first / tools / enforce_align / subagent_policy / no_load（五字段） |

**迁移后三次 block 各自的归宿**：
- att1（`_macros.html:57` + `{% set %}` 塞陈述）→ 方案名词扫描 append 当场拦
  （实现侧名词只能进 fields/boundary），第一轮 judge 不再发生；
- att2（八字段键值枚举形态）→ v2.32 已判合法 + statements 结构化后字段各有其位；
- att3（judge 幻觉判缺 trace）→ artifact 只剩边界清晰的陈述对象 + gate 文案
  明示「八键齐备/名词扫描已机械校验，勿再判」。

**judge 角色收敛**：形式要件（字段齐备/名词位置/ID 覆盖）全部机械层，
judge 只剩三条语义判据（不传导/复合句/凭空新增）。

## 配套变更

- `_ID_RE` 扩面：新增 RC-A / T1 / SC4.1（多字母前缀 X1.1）/ #1a / U1 模式——
  实测旧模式只捞到 H1.1 和 out[A]，plan 域 ID 传导核对静默空转；ASCII 边界用
  否定环视（`\b` 对 CJK-Latin 交界不可靠，同 _NOUN_L/_NOUN_R 先例）。
- `_step_trace_ids` 与新载荷拼接文本都纳入 `fields` 值（八字段含 ID 是常态，
  ID 可经 fields 传导）。
- `payload_format_hint` 按步渲染所需 fields 键（注入单源，phase hook 直接消费）。
- gate 文案双侧对齐（purpose 披露载荷格式 + gate 判词标注「已机械校验勿再判」），
  v2.32 `_ATOMIC_ITEM_RULE` 原样保留。

## 边界与不做

- 只迁三个 plan 域归一化步；qa 仍是其余 19 个编排子步骤默认（逼问/取证/核验类
  产出本身就是问答）。
- ProblemContext 子5 不迁（无字段携带矛盾，历史上一次过）。
- evidence 骨架不变（kind/minor_stage/sub_step/purpose 照旧），老 qa trace 不迁移。
- statement_fields 只校「键存在且非空」，不校内容语义（语义归 judge——
  机械层不吃裁量）。

## 测试

`TestStatementFieldsMigration` 10 例：三节点声明钉死 / fields 缺失·空值·非对象
拒绝并点名 / 全键 happy path / `_ID_RE` 新模式 / 重放 att1（名词扫描拦）/
重放 att2（合法形态通过）/ ID 经 fields 传导（含缺传拒绝对照）。
483 tests 全绿。
