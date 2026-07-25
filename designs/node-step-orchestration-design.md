# 节点步级编排 Design v2（Node.sub_steps：子步骤序列 + 步级目的 + 选择性记录 + 逐步门控）

> 状态：设计中（2026-07-24，v2）。H8 Design-First 产物，先于实现。
> v2 变更：采纳用户 Q1=**逐步门控**（v1 D6 是末尾一次校验，已推翻）+ 引入**三级层次**（phase/子阶段/子步骤）+ 明确 **skill 内部 Q/A 不门控**。Q2/Q3/Q4 = engine 声明目的 / 4 子步骤 / 同 commit 切换。
> 父系统：`designs/tui-state-machine-design.md`（节点树 / gate）、`designs/skill-injection-link-design.md`（skill 注入链）、`designs/define-problem-verify-gate-design.md`（understand:1 验真门，本文的过渡形态）。
> 范围：让 engine 节点（子阶段）可声明**有序子步骤序列**（子步骤1 调 skill 达目的X -> 产出喂子步骤2 调工具达目的Y -> ...），**每个子步骤完成即门控**，skill 内部 Q/A 不门控只记录。pilot = understand:1。

## 0. 背景

### 0.1 当前形态（刚发布的 understand:1，过渡）

`define-problem-verify-gate-design.md` 已让 understand:1：
- 载 define-problem skill（`skill-injection-link-design`）。
- `gate_rubric` = 验真判据（目的单源在 engine）。
- 模型写 `skill-trace`(step/q/a) + `conclusion` 到 evidence.jsonl，gate 读文件校验「≥3 trace + conclusion + q 覆盖 who/pain/why-now 三类」。

**缺口**：这是「单 skill 一发」--engine 只声明「载 define-problem」，不声明「先问谁/再搜证据/再一句话陈述/再读回确认」的**子步骤序列**。且门控粒度混乱：用「≥3 条 Q/A」当**记录代理**，把 skill 内部 Q/A 当成了门控单位（粗糙：记够 3 条就算数，不校验子步骤顺序与目的对应）。

### 0.2 用户设想（2026-07-24）

> engine 每个小阶段可编排：第一步调什么 skill 达什么目的，信息给第二步调用时给到模型；可编排 skill 也可编排工具调用。skill 小 step 很多，并非每个都记，只记对排查有用的。每个工具调用也记一个目的，这目的能否给模型遵守？

**用户 Q1 关键澄清（区分两个层次的 step）**：

| 层次 | 是什么 | 门控？ |
|---|---|---|
| **子步骤（sub-step）** | 编排单位：调 skill / 调工具 | **是**--每个子步骤执行完就门控（STEP_DONE） |
| **skill 内部 step** | skill 自己的 Q/A 思考（很多） | **否**--只记录证据，不门控 |

即：**声明式子步骤编排 + 逐步门控 + skill 内部不门控 + 选择性记录 + 工具调用目的注入与校验**。

## 1. 设计决策（基于已核实事实 + 用户认可方向）

| # | 决策 | 理由 |
|---|---|---|
| D1 | **声明式编排**（engine 声明 sub_steps，模型按序执行），非进程驱动 | 守 engine 定位（`dl-flow-engine.py:9-12`：编排者非进程驱动；主流程回合由 TUI+Stop 驱动） |
| D2 | **按需开启**：`Node.sub_steps=None` = 无编排（当前行为，多数节点）；非 None 才启用 | 避免给所有节点强加序列；只给「天然有序列」的节点 |
| D3 | **子步骤目的注入走 phase-rules 通道**（system-prompt），非 `additionalContext` | `skill-injection-link-design.md` §7 实测：additionalContext 附件 ark-code-latest 收不到（症状 D）；phase-rules 能收到 |
| D4 | **目的「遵守」靠 gate 兜底**，不靠注入自觉 | §skill-injection-link §8 实测：prose 级目的被当可选忽略；只有「强制语义 + 事后 gate 校验」才可靠。注入引导，门控保证 |
| D5 | **选择性记录**：每子步骤带 `record` 标志，只落 `record=True` 的到 evidence | 取代「≥3 条 Q/A」粗糙代理；噪声（纯澄清问答）不落盘，关键中间结论/外部查证才落 |
| D6 | **逐步门控**（v2 推翻 v1）：每个子步骤完成（`### STEP_DONE:<n>`）即触发 gate；skill 内部 Q/A 不门控（只 record） | 用户 Q1：skill 内部很多 step 间不门控，但 skill 执行完需门控。子步骤=门控单位，skill 内部=记录单位 |
| D7 | **工具调用目的 = engine 声明**（sub_steps 里 `kind=tool` 步的 `purpose`），非模型自述 | 模型自述走 transcript 解析（`evidence-chain-design` §8.6c 已弃用：脆+不可强制）；engine 声明是数据，注入+校验都走它 |

### 1.1 三级层次（v2 核心）

```
phase: understand (5 阶段)
  └ 子阶段 sub-phase: understand:1 "理解问题和背景" (4 个)   [### SUB_DONE / ### PHASE_DONE, 现有]
      └ 子步骤 sub-step: 编排单位（调 skill / 调工具）         [### STEP_DONE:<n>, 新增]
          └ skill 内部 step: skill 自己的 Q/A                  [不门控, 只 record 落 evidence]
```

- **子步骤** = 门控单位（STEP_DONE 触发 gate）。
- **skill 内部 step** = 记录单位（不门控，落 evidence 供 judge 读）。
- 节点无 `sub_steps` 时：现有 SUB_DONE/PHASE_DONE 不变（understand:2/3/4, plan:0...）。

### 1.2 目的注入与遵守（回应用户「目的能否给模型遵守」）

**能注入，但「遵守」不保证，靠 gate 兜底**。可靠性链：

```
engine 声明 sub_step.purpose（数据）
  -> workflow_phase 注入：phase-rules 通道 + 框成「强制」（非 prose 建议）
  -> 模型执行该子步骤（best-effort，仍会漂移；skill 内部 Q/A 不门控）
  -> STEP_DONE:<n> 触发 gate：judge 校验「该子步骤 purpose 是否达成」
  -> 未达成 -> block 续轮重试该子步骤（可强制）
```

- 前三步 best-effort（模型遵从问题，见 `skill-injection-link` §7-8 实测）；第四步保证。
- 昨天教训内化：注入要「强制语义」（「未达上步 purpose 就进下步=违规」）。
- **禁**模型自述 `### PURPOSE:...` 走 transcript 解析（已弃用脆性）；目的唯一源 = engine sub_steps 声明。

## 2. Node schema 演进

### 2.1 Step dataclass（= 子步骤定义）

```python
@dataclass(frozen=True)
class Step:
    """子阶段内一个有序子步骤（门控单位）。"""
    kind: str           # "skill" | "tool"
    ref: str            # skill 名（"define-problem"）或 工具+参数模板（"codegraph callers {sym}"）
    purpose: str        # 本子步骤目的（注入模型 + gate 校验依据）。声明式，单源在 engine。
    input: str | None   # 引用上子步骤产出（"step1.real_problem"）；None=无依赖（首步）
    record: bool        # 是否落 evidence（True=关键步；False=噪声如交互确认）
    gate: str | None    # 子步骤 rubric（judge 校验 purpose 达成否）；None=自动过（仅机械）
```

### 2.2 Node 加 sub_steps 字段

```python
@dataclass(frozen=True)
class Node:
    # ... 现有字段 ...
    sub_steps: tuple[Step, ...] | None  # None=无编排（当前行为）；非 None=启用子步骤注入/门控
```

- `sub_steps=None`：`_format_injection` / `run_gate` 行为不变（当前所有节点）。
- `sub_steps` 非 None：注入「子步骤清单 + 逐步 purpose + 当前步高亮」，STEP_DONE 逐步门控。
- 冻结 dataclass，`sub_steps` 用 tuple（不可变，声明式）。

### 2.3 understand:1 pilot（4 子步骤，逐步门控）

```python
"understand:1": Node(
    label="理解问题和背景", phase="understand", sub=1,
    skill="define-problem",  # 仍保留（skill 注入链兼容）；子步骤1.ref 重复声明，单源
    artifact=None, gate_mech=GateMech.NONE,
    gate_rubric="验真问题是否真实：（逐步见 sub_steps.purpose）末子步骤通过即子阶段过。",
    advance="sub",
    sub_steps=(
        Step(kind="skill", ref="define-problem",
             purpose="逼问问题定义：who/pain/why-now 至少三类，挖到真实问题非字面",
             input=None, record=True,
             gate="形式要件（单源 _STEP1_FORM_REQUIREMENTS：覆盖 ≥3 类/对齐/原话/结论二选一）+ 质量判据（judge 裁量不进 purpose：非空泛、痛点可观察非编造、无佐证的无痛点声明=偷懒）"),
        Step(kind="tool", ref="codegraph impact {sym} / web search",
             purpose="验真问题真实存在：搜外部证据证实或证伪子1的问题陈述 + 约束 + 反模式（防 reinvent）",
             input="step1.real_problem", record=True,
             gate="≥1 外部证据直接针对子1问题陈述 + 证据与存在性结论间有推理链，非泛泛"),
        Step(kind="skill", ref="define-problem",
             purpose="一句话陈述问题（若放不进一句则未定义完）",
             input="step1+step2", record=True,
             gate="问题陈述 ≤1 句且含主语+动词+约束"),
        Step(kind="skill", ref="define-problem",
             purpose="读回确认：用户认「这就是问题」",
             input="step3.statement", record=True,  # §substep-gate-at-stop：Stop 门控以新 trace 为完成触发，末步 record=False 会卡死（原 record=False 已改）
             gate=None),  # 交互步，不跑 judge（trace 存在即过）
    ),
),
```

- 4 子步骤对应 define-problem SKILL.md 的 Interview(子1) / Research(子2) / State(子3) / Validate(子4)；Surface constraints 并入子1 purpose。
- **子1 调 skill**：define-problem 内部跑 Interview+Constrain（很多 Q/A，**不门控**，record 落 evidence）。模型信号子1 完成 -> `### STEP_DONE: 1` -> 门控子1 purpose。
- `record`：子1/2/3 落 evidence（关键）；子4 原设计不落（交互确认，噪声），**§substep-gate-at-stop 已改为落**（Stop 门控以新 trace 为唯一完成触发，末步不落会卡死；确认内容兼作裁决留痕）。
- `gate=None`（子4）：自动过，不跑 judge。
- `input`：声明数据流，注入层用（模型按提示衔接）；engine 不自动管道传输（守 D1 非进程驱动）。

## 3. 数据流（子步骤间 input 引用）

- `input="step1.real_problem"`：声明性提示，**注入层**用（告诉模型「子2 输入是子1 的 real_problem」）。
- **不**自动管道传输（engine 不取上步输出塞下步 prompt）。模型按注入提示衔接。
- gate 不强校验数据流闭合（避免 DAG 复杂度，已弃用 `evidence-chain` depends_on）。仅注入引导 + record 落盘。

## 4. 门控与完成信号（v2：逐步门控）

### 4.1 三级完成标记

| 层级 | 标记 | 何时输出 | gate |
|---|---|---|---|
| phase | (无，靠子阶段聚合) | - | /wf gate（understand->plan 等闸门） |
| 子阶段 sub-phase | `### SUB_DONE:<n>` / `### PHASE_DONE:<phase>` | 子阶段目标达成 | 节点 gate_rubric |
| 子步骤 sub-step（新） | `### STEP_DONE:<n>` | 子步骤执行完 | 子步骤 Step.gate |

### 4.2 节点有 sub_steps 时（新增 STEP_DONE 处理）

```
模型执行子步骤1（skill 内部 Q/A 不门控，record 落 evidence）
  -> 完成输出 ### STEP_DONE: 1
  -> Stop hook：gate 子步骤1（judge 校验 Step[0].gate 的 purpose 达成，读 evidence + 本轮输出）
     ├ pass：sub_step_index++。非末子步骤 -> 续轮做子步骤2。
     │        末子步骤(n=总数) -> 推进子阶段（sub_index++，复用现有 SUB_DONE 推进逻辑）。
     └ block：additionalContext(reason，指明子步骤1 purpose 未达成) -> 续轮重试子步骤1。
```

- 末子步骤 STEP_DONE 替代 SUB_DONE（节点有 sub_steps 时不再用 SUB_DONE）。
- skill 内部 Q/A 跨多轮（define-problem 访谈用户）**不门控**，只在模型信号 STEP_DONE 时才 gate 子步骤边界。

### 4.3 节点无 sub_steps 时（不变）

understand:2/3/4, plan:0... 现有 SUB_DONE/PHASE_DONE 逻辑零改。

### 4.4 state.json 演进

- + `sub_step_index`（当前子步骤序号，1-based；无 sub_steps 节点=0）。
- `normalize_state` 向后兼容（缺省按 1 或 0 推导；与 node.sub_steps 总数不一致则报错暴露，守 no silent fallback）。

### 4.5 judge 成本

understand:1 有 4 子步骤 = 4 次 judge（每次 STEP_DONE 一次 claude -p）。可接受（判据非生成）；后续可加机械预判短路（如 evidence 行数 < 阈值直接 block 不起 judge）。

## 5. 目的注入（workflow_phase.py）

节点有 sub_steps 时，`_format_injection` 追加**子步骤清单块**：

```
- 子步骤编排（本节点 {n} 子步骤，按序执行，每步完成输出 ### STEP_DONE:<n> 触发门控）：
  1. [skill:define-problem] 目的：逼问问题定义：who/pain/why-now 至少三类...
     输入：无（首步）｜记录：是（落 evidence skill-trace，skill 内部 Q/A 不门控）
  2. [tool:codegraph/web] 目的：验真问题真实存在：搜外部证据证实或证伪子1的问题陈述...
     输入：step1.real_problem｜记录：是
  ...
  当前步：{sub_step_index}（高亮）。强制：未达上步 purpose 就进下步=违规。
```

- 通道：phase-rules（system-prompt），ark 能收到（§skill-injection §7 实测）。
- 强制语义（非 prose 建议）：内化昨天教训。
- 当前步高亮：从 state.sub_step_index 推导，每轮注入更新。

## 6. 选择性记录（record 标志）

- `record=True` 子步骤：模型执行后写 `{"kind":"skill-trace","sub_step":<n>,"purpose":"...","q/a 或产出":"..."}` 到 evidence.jsonl。
- `record=False` 子步骤：不落盘（交互确认、纯澄清）。
- evidence record 增字段 `purpose`（子步骤目的，对排查有用）+ `sub_step`（序号）。
- **取代** `define-problem-verify-gate-design` 的「≥3 条 Q/A」规则：编排开启后，gate 逐步校验「该子步骤 purpose 达成」而非「≥3 条」。

## 7. 流程（v2：逐步门控）

```
UserPromptSubmit（workflow_phase.py）
  └ 节点有 sub_steps -> 注入子步骤清单 + 逐步 purpose + 当前步高亮（phase-rules，强制语义）
        ▼
模型执行当前子步骤（sub_step_index）
  ├ 子步骤1 [skill:define-problem]：内部 Q/A（不门控，record 落 evidence）-> ### STEP_DONE: 1
  │     ▼ Stop hook gate 子1（judge 读 evidence+本轮输出，校验 purpose1）
  │     ├ pass -> sub_step_index=2，续轮做子2
  │     └ block -> 续轮重试子1
  ├ 子步骤2 [tool]：搜证据 -> ### STEP_DONE: 2 -> gate 子2 -> pass -> 子3
  ├ 子步骤3 [skill]：一句话陈述 -> ### STEP_DONE: 3 -> gate 子3 -> pass -> 子4
  └ 子步骤4 [skill]：读回确认（record=False）-> ### STEP_DONE: 4 -> gate 子4(gate=None,自动过)
        -> 末子步骤通过 -> 推进子阶段 understand:2
```

## 8. 与刚发布 understand:1 的关系（过渡形态）

| 维度 | 过渡形态（已发布） | 编排形态（本 design v2） |
|---|---|---|
| 步骤声明 | 无（载 skill 一发） | `sub_steps` 4 子步骤序列 |
| 门控粒度 | 子阶段末一次（≥3 Q/A 代理） | **逐步**（每子步骤 STEP_DONE 一次 gate） |
| skill 内部 Q/A | 当门控代理（≥3 条） | **不门控**，只 record |
| 记录 | 每 Q/A 都记 | record 标志选择性记 |
| 目的注入 | skill 名 + trace 写法 | 逐步 purpose + 强制语义 |
| 取代 | - | 编排实现验证后，过渡形态由 sub_steps 驱动取代 |

- 过渡形态**保留可用**直至编排实现验证通过（不删除，渐进替换）。
- 编排实现 commit 时，understand:1 的 `gate_rubric` 改为引用 sub_steps；`_format_injection` 的 trace 块由子步骤清单块取代；过渡的「≥3 Q/A」规则删除。

## 9. 铁律

- **H8**：本文先于实现（engine schema + workflow_advance + workflow_phase 改动）。
- **H9**：分 commit（design / Step+Node schema+state+tests / workflow_phase 注入 / workflow_advance STEP_DONE gate / understand:1 切换），每 ≤3 文件 AND ≤200 行。
- **H11/H12**：hook 日志 `%` 惰性，exit 0 only。
- **H15**：改已有 .py 前先 `codegraph affected` 留痕。
- **no silent fallback**：`sub_steps=None` 节点行为不变（显式）；judge 拿不到某子步骤产出 -> 该子步骤判 block；state.sub_step_index 与 sub_steps 总数不一致 -> 报错暴露。
- **不复制规则**：步级目的「强制语义」内化自 `skill-injection-link` §8 教训，本文只引结论不复制正文。
- **verify before claiming done**：pilot 单测 + live（`dl <name>` 走 understand:1，4 子步骤逐步 gate + evidence 选择性落盘）。

## 10. 风险

| # | 风险 | 缓解 |
|---|---|---|
| 1 | 模型不按 sub_steps 顺序（跳步/乱序） | STEP_DONE:<n> 带 n；hook 校验 n==当前 sub_step_index，不符不推进（防跳步，同现有 SUB_DONE 守卫）；乱序致某子步骤 purpose 未达 -> block |
| 2 | 4 子步骤 = 4 次 judge（成本/延迟） | 可接受；后续加机械预判短路（evidence 行数等） |
| 3 | `input` 数据流声明性，模型不衔接 | 注入明确「子2 输入=子1.real_problem」；gate rubric 含「连回上步」校验 |
| 4 | record 步 evidence 写法漂（漏 purpose/sub_step 字段） | gate rubric 校验 record 行含 purpose；注入给格式 |
| 5 | 子步骤清单膨胀 phase-rules | 只 sub_steps≠None 节点注入；清单精炼 |
| 6 | 工具步 `ref` 含参数模板（{sym}），sym 来源 | pilot 子2 sym 由子1 产出（input 引用）；注入提示模型代入 |
| 7 | skill 内部多轮 Q/A（define-problem 访谈）期间无 gate，模型可能中途跑偏 | 子步骤 gate 兜底（STEP_DONE 时校验 purpose）；中途跑偏 -> 子步骤 purpose 未达 -> block 重试 |
| 8 | STEP_DONE 与现有 SUB_DONE 协议并存复杂度 | 节点有 sub_steps 用 STEP_DONE（末步推进子阶段），无 sub_steps 用 SUB_DONE；两套互斥不并存于同一节点 |
| 9 | 过渡形态与编排形态并存期行为不一致 | 编排实现+验证通过同 commit 切换 understand:1（不留双形态，Q4=A） |

## 11. 用户确认项（2026-07-24 已确认）

- [x] **D6 逐步门控**（Q1=B）：每子步骤 STEP_DONE 一次 gate；skill 内部 Q/A 不门控。**推翻 v1 末尾一次校验**。
- [x] **D7 目的 engine 声明**（Q2=A）：禁模型自述 transcript 解析。
- [x] **pilot 4 子步骤**（Q3=A）：Interview/Research/State/Validate（Surface 并入子1）。
- [x] **过渡->编排同 commit 切换**（Q4=A）：不留双形态。
- [x] **record 步选择**：pilot 子1/2/3 record=True，子4（交互确认）record=False。

## 12. 实施步骤（分小 commit，启动）

1. ✅ 本 design v2（H8）。
2. ✅ engine：`Step` dataclass + `Node.sub_steps` 字段 + `sub_step_total/sub_step_at/step_needs_evidence` + state.json `sub_step_index` + `normalize_state` 兼容（越界报错）+ 单测。（commit 8e79a0a）
3. ✅ workflow_phase.py：`_format_injection` 加子步骤清单块（sub_steps≠None 时）+ STEP_DONE 格式 + 互斥跳过 SUB_DONE/PHASE_DONE 指令。（commit 2967f99）
4. ✅ workflow_advance.py：`STEP_DONE_RE` + `_handle_step_done`（逐步 gate / 防跳步 / 末步推进子阶段 / block 续轮）+ `_step_evidence_artifact`。（commit c4c7594）
5. ✅ understand:1 切换：`sub_steps` 填 4 步 + `gate_rubric=None`（删过渡「≥3 Q/A」）+ 注入块由子步骤清单块驱动。（commit d4765ea）
6. ⏳ live 验证：`dl <name>` 走 understand:1，4 子步骤逐步 gate + skill 内部 Q/A 不门控 + evidence 选择性落盘。
   - 代码侧验证已完成：单测 115 passed + 注入冒烟（真 understand:1）PASS + `_handle_step_done` 6 路径单测 PASS。
   - 真会话 live（需交互式 TUI + 模型真按 4 子步骤执行 + 用户答问）待用户跑 `dl <name>` 实测。
