# u:4#3（验收方式设计）fermate 裁剪设计——声明-核验对范式（v2 专项）

> 状态：**已实现（2026-08-26，feat/fermate 分支 commit 048eca0，1278 tests 全绿）**——§4 触点全项落地（含渲染注记 polish）。待：live judge 重放（既有 clean/vio fixture 方向不变 + fermate 声明载荷 PASS）与真实实例验证，均归用户统一验证。
> 确认史：2026-08-26 用户裁决立项（fermate v1 收口时留的 v2 专项）。同日**设计评估修正**：v1 设计期判「u:4#3 裁剪牵连 state-conditional gate 新机制类」系保守估计——查实契约真源后确认既有「声明-核验对 + judge 静态兜底」范式可零 gate 变体落地（§1.1）。
> 父文档：`fermate-plan-only-design.md`（v1，§2.6 v1 边界留本项）、`success-criteria-substeps-design.md`（u:4 原始拆步）、`u4-sub4-cost-optimization-design.md`（u:4#4 无编号传导机械核对的出处）、mechanical-checks 参考（声明-核验对范式：`assumption_completeness_trace`/`no_load_trace`/`redteam_report_recorded`）

## 0. 背景与裁剪论证（承 v1，此处补完）

u:4#3（验收方式设计）产物 = 四法选择+理由 / 可行性三态 / 时机标注 / 证据形式锚定——**消费方全在 review:0 与 execute**（review 判 solved/partial/not 拿什么证据、triggered 项进 plan:4 检查点候选、「待建手段」进 plan 任务项）。fermate（plan-only）下 review/execute 不存在，消费方=人读改动点，验收方式设计无人消费。

**兜底面（裁剪不损改动点质量链）**：plan:1#3 可测试性核验（五项核验之一）在设计层覆盖「没法测」；plan:2#4 执行包 verify 字段要求每条改动点带可执行验证方法（spec by example），人工验收每个改动点不缺判据。u:4#2（可检验化：指标/基线/阈值提案）**保留**——把目标钉成可检验形态是防「假目标」的核心，不只服务 review。

## 1. 机制设计：声明-核验对（零 judge 文案变体）

### 1.1 设计评估修正（为什么 v1 的担忧不成立）

v1 评估假设「u:4#4 gate 硬要求六字段 → 裁剪必须 gate 按 state 分支 → judge 双面维护+重放回归翻倍」。查实三点后修正：

1. u:4#4 **无 statement_fields 逐键机械校验**——验收包六字段（指标/基线/阈值提案/验收方法/时机/证据形式）只活在 judge 层与 statements 自由字段里；mech 仅查 text/type_label/boundary 三字段非空 + 方案名词扫描，**无条目编号传导核对**（u4-sub4-cost 已删）。
2. **state 分支的合法居所 = engine 代码层**：append-trace 机械校验、跳步判定全持 state（`step_tacet_forced(state,...)` 已是先例）——代码层 if state 不是「机制类」，是既有模式。
3. **judge 的唯一死穴 = 看不见 state**——用既有「机械校验已知事实」静态兜底条款破解（u:4#4 gate 现文已有同款括号：「statements 三字段非空已由 append-trace 机械校验——你不得以字段不齐为由 block」）。

结论：**judge 文案只加静态条款（一份文案两轨道共用），全部 state 分支在 engine 代码层**。判据维护面/重放回归面零翻倍。

### 1.2 三件套

**① u:4#3 fermate 下整步静默**（复用 tacet 机械跳步通道）：
- `FERMATE_SILENT_STEPS = frozenset({"understand:4#3"})`（声明式常量+注释；与 tacet 集正交——tacet 管密度、fermate 管深度，两开关同时命中同一步时静默语义相同）。
- `step_fermate_forced(state, node, cur)`（镜像 `step_tacet_forced`）+ `write_fermate_trace`（kind=fermate 占位落痕，诚实可见，镜像 kind=tacet：不入 skill-trace 面、零 judge 输入干扰）+ driver 派段前同点查静默（dl_drive 既有 tacet 检查点旁加 fermate 检查，或泛化为 `step_forced_silent(state, node, cur) -> str|None` 返回 "tacet"/"fermate"/None——实现时取改动小者）。
- 末步/装配义务：u:4#3 非末步非装配步，跳过=sub_step_index++，无产物副作用（比 tacet 的 apply_tacet_skip 更简单，无 render_artifact 分支）。

**② u:4#4 声明-核验对**（核心）：
- **模型侧（purpose/selfcheck 静态括号，两轨道共一份文案）**：「fermate 轨道（无 子3 验收方式设计）：验收包=三字段（指标/基线/阈值提案），type_label 填占位声明 `fermate·plan-only`（自描述：无验收方式设计、无 review 消费方）——**轨道占位声明是机械必检项，漏声明/假声明当场拒**」。
- **机械侧（append-trace 新 mech check `fermate_placeholder_consistency`，u:4#4 专属，双向核验）**：
  - 载荷含 fermate 占位声明（type_label 或字段词形命中）但 `state.force_fermate` 假 → **当场拒**（full-track 偷工通道机械封死——judge 永远见不到谎称 fermate 的载荷）；
  - `state.force_fermate` 真但 u:4#4 载荷无占位声明（type_label 空/填了 test 等真值）→ **当场拒**（漏声明逼回，防模型在 fermate 下编造方法/时机——编造的载荷若漏过，judge 按原 gate 方框一「与子3 不一致」会误伤还是放行成方差，机械层先封）。
- **judge 侧（gate 加静态兜底条款，一份文案）**：「fermate 轨道项（type_label=占位声明、验收包三字段、evidence 无 子3 skill-trace）的轨道归属与声明一致性已由 append-trace 机械校验（双向核验，不一致当场拒）——你不得以『缺验收方法/时机/证据形式/六字段不齐/type_label 与子3 不一致/缺子3 对照基准』为由 block 这些项；非声明项按方框原判」。原方框一~四**逐字不动**（全量轨道重放回归零影响）。

**③ u:4#5 读回 + understand.md 装配**：
- purpose 加静态括号（两轨道共一份）：「fermate 轨道：裁决点=阈值拍板单项（无 子3 产物，『验收方式认可』不适用）」——模型凭 v1 已注入的轨道告知本地解析该条件，无需 engine 组装分支。
- understand.md「成功标准验收包」节 = render-artifact 从 子4 statements 通用装配——三字段+占位 type_label 原样呈现（占位值自描述，人读无碍）；装配代码零分支（实现时冒烟验证）。

### 1.3 不动的面

u:4#1/#2（引出/可检验化）逐字不动；plan:1#4 Pugh 承接度（三字段验收包够评分）、plan:2#1 验收包清点（通用提取）零改动；review:0（fermate 下到不了）零改动；全量轨道 u:4 五步原样（唯一新增=gate 静态兜底条款，不重放不触发——不，条款新增须重放验证零误伤，见 §3）。

## 2. 失效模式与对策

| # | 失效 | 对策 |
|---|---|---|
| G1 | full-track 模型谎称 fermate 占位偷工（跳 子3 工作） | mech 双向核验第一向：声明×state 不一致当场拒（judge 永不可见） |
| G2 | fermate-track 漏声明/编造方法时机 | mech 第二向当场拒；漏网编造由 gate 原方框一判（静态条款只豁免声明项） |
| G3 | judge 看不见 state 发明 block（缺 子3 对照基准/六字段不齐） | gate 静态兜底条款 defer mech（既有「机械已知事实」范式第五次复用） |
| G4 | 人读 understand.md 见占位 type_label 困惑 | 占位值自描述 `fermate·plan-only`；v1 轨道告知注入同义 |
| G5 | state-reset 回 u:4 中段重跑 | 静默步再跳过/声明再核验均机械幂等；evidence append 协议既有 |
| G6 | tacet+fermate 双开关命中 u:4#3 | 两集同判静默，落痕 kind 按先查者（语义相同无冲突）；测试钉死 |

## 3. 验证清单（实现时）

- mech 双向核验：声明+full-state 拒 / 无声明+fermate-state 拒 / 声明+fermate-state 过 / 无声明+full-state 过（四象限）。
- 静默跳步：u:4#3 fermate 下落 kind=fermate 占位 + 推进子4；tacet+fermate 双开关同点行为钉死。
- **gate 重放回归（条款新增必做）**：u:4#4 既有重放 fixture（clean 6/6、vio1-4 各 6/6 基线）加静态条款后**逐字重判方向不变**；新增 fermate 声明载荷重放 PASS。
- 渲染：phase-rules u:4 GENERATED 段 fermate 变体可选注记「子3=fermate 裁剪静默」（render_substeps_section 注解，polish 项）。
- understand.md fermate 端到端冒烟：三字段+占位 type_label 装配呈现。
- 全量回归 1272+ 全绿。

## 4. 触点清单

- [ ] `dl_flow_nodes.py`：FERMATE_SILENT_STEPS 常量 + u:4#4 gate 静态兜底条款（单源常量插值）+ u:4#4 purpose/selfcheck 静态括号 + u:4#5 purpose 静态括号
- [ ] `dl_flow_engine.py`：step_fermate_forced + write_fermate_trace + 跳步通道（dl_drive 检查点）+ append-trace mech check `fermate_placeholder_consistency`（u:4#4 专属注册）
- [ ] 可选 polish：render_substeps_section fermate 注记
- [ ] 测试 §3 全项 + nodes-index.md u:4 段注记 + fermate-plan-only-design §2.6 边界注记更新
