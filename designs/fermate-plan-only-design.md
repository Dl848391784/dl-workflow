# fermate（plan-only）维度设计——工作流第二正交开关

> 状态：**v1 已实现（2026-08-26，feat/fermate 分支，1272 tests 全绿）**——§4 checklist 全项落地：engine sticky/终点门栏/脊柱重映射/渲染双变体 + dl-launch --fermate + phase-rules 条件块 + TestForceFermate 8 例 + SKILL/nodes-index 同步。待：收口 merge main（用户裁决）+ 真实实例首跑验证。
> 确认史（2026-08-26 会话，用户三连决议）：①维度立项——tacet 是流程**密度**维度（44 步内 38 步静默），fermate 是流程**深度**维度（终点钉在 plan:2，plan:3/plan:4 不存在），两者正交可组合；②命名 **fermate**——谱面记号家族对齐 tacet：tacet=声部静默（密度），fermate=全曲停驻（深度），停多久由指挥（用户）裁决；③v1 范围**只裁 plan:3/plan:4（44→33 步）**——u:4#3 裁剪经实现前评估发现牵连 state-conditional gate 新机制类（u:4#4 gate 硬要求验收包六字段，其中验收方法/时机/证据形式三字段来源=子3 trace，judge 判材以子3 为对照基准；静态 gate 放行「不适用」=全量轨道偷工通道），用户裁决 v1 保留 u:4 整节点，u:4#3 留 v2 专项。
> 父文档：`force-tacet-experiment-design.md`（sticky flag/机械跳步蓝本）、`capability-tool-selection-substeps-design.md`（plan:3 消费契约=execute，裁剪论证的起点）、`execution-plan-checkpoints-substeps-design.md`（plan:4 同）、`artifact-handoff-hardening-design.md`（ARTIFACT_SECTIONS 单源）
> 场景驱动：现阶段 dl-workflow 的使用形态 = **输出清晰准确的改动点清单即交付**（消费方=人），不跑 execute/review/evolution。plan:3 能力包五字段与 plan:4 检查点十字段的消费契约锚点**全部倒推自 execute:0/review:0**——无执行则无读者，产物=纯税（11 子步 + ~9 次 judge 调用）。

## 0. 维度定位：2×2 正交矩阵

| | 全量密度（dl） | 脊柱密度（dlt = --force-tacet） |
|---|---|---|
| 跑到底（u→p→e→r→evolution） | 现状 dl | 现状 dlt |
| **plan-only（--fermate）** | **本设计** | **本设计（组合）** |

关键区分：现状（含 tacet）在 plan:4 门栏默认停等，但**门栏只是挡在 plan 之后——plan:3/plan:4 的税照付**。fermate 的真实语义 = plan 阶段**内部**裁剪到 plan:1+plan:2，终点 = plan.md「执行步骤」节装配完。改动点的 per-change 验证判据已由 plan:2#4 执行包五字段的 verify 字段承载（spec by example），plan:4 检查点是编排级（跨任务何时停/并行分组/失败路由）运行时控制结构，executor 不存在即无读者。

## 1. 第一性原理：消费契约锚点法的反向运用

锚点法正用 = 产物字段倒推自下游消费方 rubric。反用 = **下游消费方不存在时，产物及其生产步骤整体失去存在依据**：

| 被裁节点 | 产物 | 消费方（锚点） | fermate 下消费方 |
|---|---|---|---|
| plan:3 选择能力与工具（6 步） | plan.md「能力与工具」节五字段 | execute:0 gate / using-superpowers 必先 invoke / H15 执行映射 / Agent 成本决策 / overload 防线 | 全不存在 |
| plan:4 制定执行计划和检查点（5 步） | plan.md「执行计划与检查点」节十字段 | execute:0 orchestrator 愿景 / 逐条核 rubric / review:0 证据需求 / 用户密度裁决 | 全不存在 |

保留面（改动点正确性链，一步不动）：u:1（根因五要素=改动点上游硬标准）/ u:2（must/nice 决定选型）/ u:3（in/out=改动点边界）/ u:4 整节点（v1 裁决，见确认史③；验收包承接度=plan:1 Pugh 判据）/ plan:1（改动清单八字段=设计级改动点）/ plan:2（执行步骤五字段=**fermate 最终交付物**）。

**对抗性审视记录**（设计期已反驳三条）：①环境可用性核验影响改动点可行性？——plan:1#3 可行性核验已覆盖，plan:3#4 验的是 executor 能力不是改动正确性；②最小集/不加载清单减少 plan 期 context bloat？——它约束的是 execute 期工具加载；③改动点消费方是机器（另一会话执行）时 plan:3/4 是交接合同不能省——**用 per-instance sticky flag 天然规避**：要执行的那次不加 --fermate 重开实例即可，understand/plan:1/plan:2 evidence 可复用（state-reset 回 plan:2 末步后续跑）。

## 2. 机制设计（Option A：节点图终点分支，非 tacet 式静默走查）

设计期对比过 Option B（复用 tacet 静默步机械走查 plan:3/4）——否决：plan.md 会带两节占位（「来源步未执行」）污染人读交付物、TUI/清单仍枚举幽灵节点、且终态分支同样绕不开。Option A 让 plan:3/plan:4 在 fermate 下**真正不存在**。

### 2.1 sticky state（镜像 force_tacet 先例）

- `state.force_fermate`：per-instance sticky（resume/续跑保持），engine 全程 `state.get` 判定、默认 off，**模型无权自封**（不进模型可写面，防偷工通道——同 tacet 论证）。
- 实例开关 CLI：`dl_flow_engine.py fermate <name> on|off`（镜像 `force-tacet <name> on|off` / `set_force_tacet`）。
- launch flag：`dl <name> --fermate`（dl-launch.sh 解析，置位时机与 --force-tacet 同点：state 初始化后、render-phase-rules 前）。WF_TUI=1 旧路径不支持（同 --force-tacet）。
- **dlt 组合零改动**：`ac-deepseek1 --dlt <name> --debug --fermate` → dlt 脚本 `exec dl-launch.sh --workflow "$@" --force-tacet`，`--fermate` 在 `"$@"` 里天然透传，两 sticky flag 组合生效。`ac-deepseek1 --dl ... --fermate` 同理（`--dl` 分支 `"$@"` 全透传）。入口脚本一行不改。

### 2.2 终点语义：plan:2 末步 = fermate 门栏，/dl gate = 确认收货即完结

- 单源助手 `node_holds_for_gate(state, node)` = `node.hold_for_gate or (state.force_fermate and node 是 plan:2)`。两处引用：`_advance_sub_step`（末步扣留写 held_for_gate）与 `release_subgate`（held 校验）。
- fermate + plan:2 门栏放行（`release_subgate` 分支）：**不推进 plan:3**——写裁决留痕（via 标 fermate-terminal）+ 清 held + 置 `state.gate="done"`（镜像 advance_state 终态分支：next_node_id None 时的既有终态表达）。实例即完结，`/dl done` 归档走既有路径。
- 门栏语义从「放行执行」变「**确认收货**」——改动点清单由用户拍板验收，规范裁决归用户（四桶分工不变）。
- 想升级为全量执行：`fermate <name> off` + `/dl state-reset plan:2` 重测末步后自然走进 plan:3（文档化路径，不做专门机制）。

### 2.3 产物面：plan.md 单节，零占位

- fermate 下 plan:3/plan:4 从不进入 → render-artifact 只被 plan:2 调一次 → plan.md 只有「执行步骤」一节，**无占位节**（Option A 对 B 的核心优势）。
- plan:2 既有 `ARTIFACT_CONTAINS("执行步骤"节)` 机械门**零改动即正确**；plan:4 的全三节 CONTAINS 门随节点一起不存在。
- understand.md 四节照常（u:4 全保留）。

### 2.4 tacet × fermate 组合：脊柱重映射

tacet 脊柱第 6 步 = plan:4#4（归一化执行计划包），fermate 下该节点不存在；且 plan:2#4（归一化执行步骤=fermate 终端产物步）不在原脊柱里会被静默——**终端产物步被静默 = 交付物消失**，不可接受。

- `tacet_silent_steps()` 参数化：`spine(fermate)` = fermate ? (TACET_SPINE_STEPS − plan:4#4 + plan:2#4) : TACET_SPINE_STEPS。`step_tacet_forced` 已持 state，按 `state.force_fermate` 选集；缓存按布尔双份。
- 组合后实际执行步：u:1#1/u:1#2/u:1#3/u:1#4 + plan:1#2 + plan:2#4 六步脊柱 + plan:2#5 确认级装配步（confirm 级无会话零成本）+ plan:2 门栏停等。

### 2.5 文案/显示面（三通道同源纪律）

- **phase-rules**（system-prompt 真源，dl-launch 启动渲染）：模板加 fermate 条件段——plan:3/plan:4 小节整段剔除 + plan 节改「2 子阶段，plan:2 末步门栏扣留，/dl gate 确认收货即完结」。机制 = 模板条件 token（`<!-- BEGIN FERMATE_ONLY -->`/`<!-- BEGIN NO_FERMATE -->` 块级开关，渲染 fail loud），**禁文案双写漂移**。
- **注入**（workflow_phase）：plan:3/plan:4 从不进入，注入天然正确；engine 的 force_tacet 轨道告知注入同位加 fermate 告知（「本实例 plan-only：plan:2 门栏后完结」），防模型按全量记忆预期 plan:3。
- **TUI 清单**（`tui_tasklist_lines(state)` 持 state）：fermate 下 plan:3/plan:4 不列出（或单列一行「fermate 裁剪」占位——实现时取简洁者）。
- dl-launch 启动回显加 fermate 行（对齐 ♪ force-tacet 行）。

### 2.6 明确不做（v1 边界）

- u:4#3 裁剪（state-conditional gate 新机制类，v2 专项）。
- `--until=plan|execute` 通用档（YAGNI，两档够用；flag 语义已预留扩展空间）。
- ac-* provider 函数的 `--dlf` 便利分支（.bashrc 入口，一行事，用户点名才写——auto 分类器先例）。
- execute/review/evolution 三阶段节点的 fermate 处理——flow 到不了，零触点。

## 3. 失效模式与对策

| # | 失效 | 对策 |
|---|---|---|
| F1 | 模型按全量记忆预期 plan:3，plan:2 末步后徘徊/自问自答 | phase-rules fermate 变体（system-prompt 优先级最高）+ 注入轨道告知双通道；门栏扣留本身=硬停（held_for_gate 停轮既有机制） |
| F2 | 模型自封 fermate 跳过 plan:3/4 偷工 | flag 只在 state（launch/CLI 置位），不进模型可写面——同 tacet 防偷工论证 |
| F3 | fermate 实例 /dl jump plan:3 | jump 属用户显式操作，不拦；文档注明 jump 到被裁节点= UndefinedBehavior 不防守（同 tacet 对 jump 的既有态度） |
| F4 | fermate off 升级执行时 plan.md 缺两节撞 plan:4 CONTAINS 门 | 文档化路径=state-reset plan:2 重测末步 → plan:3/plan:4 正常走、装配两节后门自然通过 |
| F5 | tacet+fermate 组合脊柱漏映射，终端产物步被静默 | §2.4 spine(fermate) 参数化 + 组合测试钉死 plan:2#4 非静默 |
| F6 | state-reset 回 plan:2 中段重跑，末步又扣留——用户以为卡住 | 门栏停等是设计内行为（plan:4 同款既有语义），TUI/dl status 显示 held 状态（既有） |

## 4. 触点清单（实现 checklist）

- [ ] `dl_flow_nodes.py`：spine(fermate) 参数化（tacet_silent_steps 签名 + TACET_SPINE_STEPS 注释）
- [ ] `dl_flow_engine.py`：`set_force_fermate` + `fermate` CLI 子命令 + `node_holds_for_gate` 单源 + `_advance_sub_step`/`release_subgate` 两处引用 + `step_tacet_forced` 按 state 选 spine + 注入轨道告知 + `tui_tasklist_lines` fermate 分支
- [ ] `scripts/workflow/dl-launch.sh`：`--fermate` 解析 + engine 置位 + 回显行 + WF_TUI=1 拒绝
- [ ] `scripts/workflow/phase-rules.md`（模板）：fermate 条件段 token + plan 节 fermate 文案
- [ ] 测试：sticky on/off / plan:2 末步扣留 / release 终态 gate=done / spine 重映射组合 / render-phase-rules fermate 变体 / 全量回归（1252+ 全绿）
- [ ] 同步面：workflow-creation SKILL.md 全景段（TACET 段旁加 FERMATE 段）+ nodes-index.md 顶部注记 + `~/bin/dlt` 头注释（组合用法）
