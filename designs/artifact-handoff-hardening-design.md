# 产物交接硬化设计：节标题单源化 + CONTAINS 扩面 + 回查通道（P1-P3）

> 状态：设计中（2026-08-02 起）。本文件为 H8 Design-First 产物。
> 父文档：`artifact-mech-gate-design.md`（§2 否决#2「标题单源化是另一个独立项」——本设计即兑现该独立项 + 否决#4 连带评估）、`workflow-system-design.md` §8.3、`node-design.md` §3.8 #6（机制适配走查）。
> 用户决议（2026-08-02）：①P4（execute 执行台账）**本轮不做，先观察**（见 §2 #1）；②review.md / evolution.md CONTAINS 严格度 = **最小两节**。

## 0. 动因：产物交接架构的「有损压缩」需要压缩规格单源化

用户设想（2026-08-02 会话）：每步证据链留存、每大阶段有产物、下阶段消费上阶段产物——用**主动有损**（阶段产物蒸馏，压缩决策发生在信息最全时刻）替代**被动有损**（harness compact，发生在上下文溢出的最差时刻），且后段 token 不膨胀。该架构已在跑（四产物落主仓 + evidence append-only + read_evidence_for_step 裁剪），本轮硬化的是其最弱环：**产物「该带什么」没有单源规格**。

现状缺口（全部有 file:line 实证）：

| # | 缺口 | 证据 |
|---|---|---|
| 1 | understand.md 节结构两通道措辞不一：注入说「真实问题重述 + 边界 + 成功标准」，装配 spec 说「真实问题重述 + 目标价值 + 范围约束 + 成功标准验收包」 | `hooks/workflow_phase.py:50` vs `scripts/workflow/phase-rules.md:69` |
| 2 | plan.md 注入说「方案 + 步骤 + 验证方法」，与实际三节结构（执行步骤/能力与工具/执行计划与检查点）完全对不上 | `hooks/workflow_phase.py:57` vs `phase-rules.md:96/106/116` |
| 3 | **plan:2 装配行连节名都没给**——只说「装配 plan.md」，「执行步骤」节标题模型从未被告知。此时给 plan:2 挂 CONTAINS = 必误 block | `phase-rules.md:96` |
| 4 | CONTAINS 只挂 plan:4 一节；understand.md 四节、plan.md 前两节、review/evolution 零结构校验——下游消费契约锚点（review:0 对照 understand.md、execute 首步读 plan.md 三节）无机械保障 | `dl_flow_nodes.py:1228/2179` |
| 5 | 产物不足时的回查动作（evidence 保险层）未钉进 phase-rules——`evidence_show.py` 工具已存在，缺的是指令 | `scripts/workflow/evidence_show.py` 存在；phase-rules execute/review 节无回查指令 |

## 1. 设计

### 1.1 P1：ARTIFACT_SECTIONS 单源常量 + 三通道渲染 + CONTAINS 挂载

**单源**（`dl_flow_nodes.py` 模块级常量——声明式数据的家）：

```python
ARTIFACT_SECTIONS: dict[str, tuple[str, ...]] = {
    "understand.md": ("真实问题重述", "目标价值", "范围约束", "成功标准验收包"),
    "plan.md": ("执行步骤", "能力与工具", "执行计划与检查点"),
    "review.md": ("结论", "证据"),
    "evolution.md": ("经验", "落地"),
}
```

- understand.md 四节取 phase-rules.md:69 装配 spec 现行措辞（该处已是四子阶段归一化陈述的真实装配口径；注入的「边界」系过期措辞，废弃）。
- plan.md 三节取 plan:2/3/4 装配分工现状。
- review.md（结论/证据）：phase-rules.md:132 现行文案「结论 + 证据 file:line / 测试输出」本就是这个结构，只是没钉节标题——对齐零文案冲突。
- evolution.md（经验/落地）：现行无结构（phase-rules.md:138 只说「写出 evolution.md」），两节 = 沉淀了什么经验 + 落到哪个 memory/skill/design 文件（附路径）。这是**新增结构要求**，phase-rules evolution 节需补一行装配规格（见 §3 连带变化）。

**节点挂载**（Node.artifact_contains 引用单源，禁散写字面量）：

| 节点 | gate_mech | artifact_contains | 校验点 |
|---|---|---|---|
| understand:4 | EXISTS→**CONTAINS** | `ARTIFACT_SECTIONS["understand.md"]`（四节全） | 末步门（not_before=entered_at 沿用） |
| plan:2 | EXISTS→**CONTAINS** | `("执行步骤",)` | 末步门（同上） |
| plan:3 | EXISTS→**CONTAINS** | `("能力与工具",)` | 末步门（同上） |
| plan:4 | CONTAINS（不变） | 扩为 `ARTIFACT_SECTIONS["plan.md"]`（三节全） | 末步门 + 大闸门——装配终点 + 唯一门栏，查跨节点删改的最便宜位置 |
| review:0 | EXISTS→**CONTAINS** | `("结论", "证据")` | run_gate（仅存在+含节，不传 not_before，宁纵勿枉沿用） |
| evolution:0 | EXISTS→**CONTAINS** | `("经验", "落地")` | 同上 |

**三通道同步**（消灭缺口 #1/#2/#3 的根）：

1. **engine 门**：上表挂载（通道一）。
2. **phase-rules 模板**：装配行（69/96/106/116 + evolution 新增行）的节名改 `{{artifact_sections:<basename>}}` 内联 token，`render_phase_rules` 扩展替换（模板保留 token、每次 launch 重渲染到 per-wf 文件，幂等性天然成立——渲染从不回写模板）。**plan:2 装配行补节名「执行步骤」**（修缺口 #3）。
3. **注入**：`workflow_phase.py` `_PHASE_META` 的 artifact 描述字符串改为从 `ARTIFACT_SECTIONS` 动态构建（import engine 已存在），「方案 + 步骤 + 验证方法」类过期措辞物理消失。

block 文案复用现有「产物缺节」模板（artifact-mech-gate-design §1.2），文案中的节名同样从单源插值。

### 1.2 P2：消费契约传导链 = 钉同步测试（不发明新机制）

产物内容契约本体已存在且已被机械校验（各归一化步 statement_fields + append-trace 逐键校验）。缺的是「下游改需求 → 上游节/字段断链」的报警。全部用静态测试钉死（tests/test_dl_flow_engine.py）：

1. `ARTIFACT_SECTIONS["plan.md"]` == plan:2/plan:3/plan:4 各自 artifact_contains 的并集（顺序一致）——装配分工与全量规格不漂移。
2. 每个 `artifact` 以 `.md` 结尾的节点：gate_mech ∈ {ARTIFACT_EXISTS→无，ARTIFACT_CONTAINS} 且 artifact_contains ⊆ ARTIFACT_SECTIONS[basename]——禁游离节名。
3. `render_phase_rules` 渲染后文本含全部单源节名、且不再含 token 残留——模板渲染链不断。
4. `workflow_phase._PHASE_META` 各 artifact 描述含对应单源节名——注入通道不漂移。
5. execute 首步指令（phase-rules.md:125）与 review 消费指令（:130）引用的节名/产物名 ∈ 单源——消费方引用不落空。

**明确不做**：字段级动态内容 CONTAINS（脆，弱模型标题外内容措辞必浮动）；judge 语义审产物（artifact-mech-gate §2 #1 已否决：机械杠杆零 token，judge 单次 ~2.2-3.3k）。

### 1.3 P3：产物不足回查通道（保险层显式化）

phase-rules 模板 execute / review / evolution 三节各补一句硬指令（措辞实施时定稿）：

> 产物信息不足 → 先 `python3 <evidence_show.py 路径>` 回查 evidence.jsonl（含各步 trace + gate 裁决记录）→ 仍不足 → AskUserQuestion 问用户，**禁凭训练记忆补全**。

纯文案，零机制风险。把「证据链 = 有损产物的保险」从设计理念变成模型可见动作。

## 2. 否决的替代方案（对抗性审视留痕）

| # | 方案 | 否决理由 |
|---|---|---|
| 1 | P4：execute 执行台账（git log + evidence 生成式渲染，供 review 导航） | **用户决议（2026-08-02）：本轮不做，先观察**。execute 是唯一无文件产物的阶段，但 review 独立验证义务不因台账减免；先观察本轮硬化后 review 的实际痛点再定，避免过度设计。自述式台账（模型写 execute.md）**永久否决**——plan:4 设计引证的 fabricated success reports 教训：execute 自我总结是 review 的污染源，只接受生成式 |
| 2 | 节名放 Step.purpose / GENERATED 子步骤块渲染 | 装配行在 GENERATED 块**外**（phase-rules.md:69/96/106/116 实测），且节结构是**节点级**声明（跨子步骤的装配分工），归 Node/模块常量不归 Step；内联 token 改动面最小 |
| 3 | CONTAINS 匹配容忍标题措辞浮动（正则/模糊匹配） | 与单源化自相矛盾：注入逐字给标题后，浮动即违规，子串精确匹配反而最简单最可预期（宁宽勿窄体现在「只查存在不查位置/格式」，不体现在放松匹配） |
| 4 | review.md 按验收包结构钉多节（真实问题对照/逐验收包判定/结论/证据） | 用户决议选最小两节。review 产物结构实践未久，钉多节误 block 风险最高；「逐验收包判定」的质量保障归 review:0 的 judge rubric，不归机械门 |
| 5 | 短节名（结论/证据/目标价值）担心误命中 pass 而加长限定 | 宁纵勿枉：CONTAINS 只拦「确定缺」，子串偶然出现在正文 = 放行，可接受；加长限定词反而增加弱模型写不对标题的误 block |
| 6 | execute 阶段编排化 / 产物字段级 CONTAINS | 出范围。orchestrator-worker 愿景是独立大项（execution-plan-checkpoints-substeps-design 已记）；字段级见 §1.2 末 |

## 3. 连带行为变化（显式披露）

- **understand:4 / plan:2 / plan:3 / review:0 / evolution:0 的机械门实际收紧**：此前只验存在+新鲜度，此后缺节即 block。在飞实例（in-flight workflow）若已有产物缺节，下次末步重判/返工时会撞新门——缓解：block 文案给修复动作（补节+新 trace），与既有返工协议一致。
- **evolution.md 新增两节结构要求**（经验/落地）——phase-rules evolution 节补装配规格行；此前产物无此结构，在飞实例 evolution 产物可能缺节（同上个缓解）。
- **plan:4 artifact_contains 扩为三节**——plan:2/3 已挂各自节的新鲜度门，plan:4 全量查是跨节点删改兜底，正常流程零新成本（节本应在）。
- **注入 `_PHASE_META` 两处文案变化**（understand/plan 的 artifact 描述）——纯对齐，无新约束。
- **output-style `workflow.md:62-63` 两处过期描述同步修正**——install.sh copy 类 artifact，改后须跑 install.sh 重 copy + 重启会话生效（skill 头部核心事实）。
- **node-design.md 摘要（purpose 第三通道）手工同步**——plan:2 装配补节名影响摘要块。
- 不触碰：settings 模板（SETTINGS_TEMPLATE_VERSION 无需 bump）、judge 判词、statement_fields。

## 4. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 弱模型写节标题浮动（如「目标与价值」）致误 block | 注入 + phase-rules 装配行双通道逐字给标题；block 文案点名缺的节名给修复动作；title 取短且高辨识度 |
| 在飞实例撞新门（§3） | 宁纵勿枉降级纪律不变（name/root/解析失败 → None 放行）；block 可修复非死锁；`/dl state-reset` 兜底 |
| token 渲染与 GENERATED 块渲染顺序/交互 | token 替换在 GENERATED 块渲染之后做（两阶段互不感知）；测试 #3 钉渲染结果 |
| 单源常量改名后三通道不同步 | P2 测试 #2/#3/#4 钉死——断链在 `pytest` 红，不在运行期爆 |
| output-style 改后忘 install.sh | 实施 checklist 显式步骤 + commit message 注明 |

## 5. 实施 checklist（按 H9 分小 commit）

1. ✅ 本设计文档（1 文件）。
2. `dl_flow_nodes.py`：ARTIFACT_SECTIONS 常量 + 5 节点挂载（understand:4/plan:2/plan:3 升 CONTAINS、plan:4 扩三节、review:0/evolution:0 升 CONTAINS）+ tests 门行为用例（缺节 block / 齐节 pass / 降级放行）。
3. `dl_flow_engine.py` render_phase_rules 加 token 替换 + `phase-rules.md` 模板四处装配行 token 化 + plan:2 补节名 + evolution 节补装配规格行 + P3 回查指令三处。
4. `hooks/workflow_phase.py` `_PHASE_META` 动态构建 + `output-styles/workflow.md` 两处同步 + install.sh 重 copy。
5. P2 五个同步测试 + `node-design.md` 摘要块手工同步。
6. 冒烟：`dl demo --resume` 重渲染 phase-rules 验 token 全替换；构造缺节 understand.md 验 understand:4 末步门 block 文案。
