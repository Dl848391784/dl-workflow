# Skill 注入链路补全 Design（§7 #1 落地）

> 状态：设计中（2026-07-23）。H8 Design-First 产物。父系统：`designs/tui-state-machine-design.md`（§7 待确认项 #1）。
> 范围：补活 engine `NODES.skill` -> `workflow_phase.py` 注入 -> 模型 invoke 链路；让 understand:1 载入市场 skill `define-problem`。

## 0. 背景

`tui-state-machine-design.md` §7 #1 标记："skill 路由文本仍散在 phase-rules/output-style/CLAUDE.md §2...本文不收口（独立项）。engine 的 NODES.skill 字段是数据化声明，与文本协同"。

**实测确认（2026-07-23）：engine NODES.skill 是死字段——**

- `dl-flow-engine.py:122` plan 节点 `skill="superpowers:using-superpowers"` 声明存在。
- 但 `hooks/workflow_phase.py` `_format_injection`（195-297 行）**不消费 `node.skill`**，只拼 `PHASE_RULES` 的目标/允许/禁止文本，无任何 "invoke skill" 指令。
- `scripts/workflow/phase-rules.md` / `output-styles/workflow.md` grep `using-superpowers`/`invoke`/`载入.*skill` **零匹配**。
- => plan 的 skill 字段声明了没人读；模型是否载 `using-superpowers` 靠模型自选 / CLAUDE.md §2，非 engine 驱动。

用户需求：让 understand:1（理解问题和背景）载入市场 skill `define-problem`（逼问问题定义 / 验真 / 钉约束 / 搜证据，契合"验真问题是否真实/合理"）。

## 1. 设计决策（已与用户确认）

- **scope**：仅 understand:1 载 define-problem。sub1 最贴"问题定义 / 验真"；sub2-4 是目标 / 范围 / 标准，产出不同，不强行套。
- **注入范围**：**通用化补全**——`_format_injection` 通用读 `engine.get_node(phase, sub).skill`，非 None 即注入 invoke 指令。顺带修活 plan:0 `using-superpowers` 死字段（落地 §7 #1 一部分），无技术债。
- **define-problem 装法**：copy `skills/define-problem/` 到 `~/.claude/skills/define-problem/`（用户级独立 skill，invoke 名 = frontmatter `name` = `define-problem`，绕过其 Rust 安装器 `src/main.rs`——手动 copy 等效）。

## 2. 改动

| # | 文件 | 改动 | 生效 |
|---|---|---|---|
| 1 | `~/.dl-workflow/designs/skill-injection-link-design.md` | 本文（H8） | 本 commit |
| 2 | `~/.claude/skills/define-problem/SKILL.md` | copy 自 github `drmarceloclipi-star/define-problem` | 重启会话 |
| 3 | `~/.dl-workflow/dl-flow-engine.py:81` | `NODES["understand:1"].skill: None -> "define-problem"` | 下轮注入（hook 跑源，无需 install） |
| 4 | `~/.dl-workflow/hooks/workflow_phase.py` `_format_injection` | 加 skill 注入分支（通用） | 下轮注入（hook 跑源） |

## 3. 注入分支设计（核心）

`_format_injection` 内，规则块后追加：

```python
# 通用 skill 注入（§7 #1 落地）：节点声明 skill 则提示模型 invoke
node_skill = None
try:
    node = engine.get_node(phase, sub_index)
    node_skill = node.skill
except (KeyError, Exception):
    pass  # get_node 非法节点 raise（守 no silent fallback，engine 已守）；注入侧降级不阻断
if node_skill:
    lines.append(
        f"- 技能: 当前节点应载 skill `{node_skill}`，请用 Skill 工具 invoke 它（已载则继续遵循）"
    )
```

- 通用：任何节点 `skill` 非 None 都注入（含 `plan:0` 的 `using-superpowers`）。
- 守 output-style 精炼：一行。
- 容错：`get_node` raise 时降级（不阻断注入其它内容），守 UserPromptSubmit `exit 0`（与现有防御式注入一致）。

## 4. 铁律

- **H8**：本文先于改 2 文件（engine + phase hook）。
- **H9**：分 commit（design / 装 skill / engine / phase hook / 验证），每 ≤3 文件。
- **H15**：改 `dl-flow-engine.py` + `workflow_phase_phase.py` 前先 `codegraph impact` 留痕（dl-workflow .py 弱门禁：挡零查询不挡查错 symbol）。
- **no silent fallback**：`get_node` 非法节点 raise（engine 已守，line 197）；注入侧 try/except 降级不阻断。
- **verify before claiming done**：新建工作流真实验证 skill 真载入。

## 5. 风险

| # | 风险 | 缓解 |
|---|---|---|
| 1 | ark-code-latest 收不到 `additionalContext` attachment（症状 D）-> skill invoke 指令进不了上下文 -> 模型不 invoke | 验证时 canary `-p` 测；若不生效，在 `phase-rules.md` / `output-style` 也加 skill 路由文本（双通道，同 `dl-cmd.sh status` 兜底思路） |
| 2 | 独立 skill invoke 名格式不确定 | 装后重启会话 `/help` 或 Skill 工具实测 invoke 名 |
| 3 | skill 启动期加载，旧会话不生效 | 新建工作流验证（非 `--resume` 旧会话） |

## 6. 验证

`dl verify-skill-load`：
- understand:1：`.wf_phase.log` 见 `injected` + 注入文本含"载 skill `define-problem`"；模型真 invoke Skill 工具。
- `/dl jump plan`：验 `using-superpowers` 也注入（修活确认）。
- canary `-p`：问模型能否复述注入里的 skill 名（判 attachment 是否到模型上下文）。

## 7. 实测记录（2026-07-23）

| 检查 | 结果 |
|---|---|
| hook 注入 attachment 含 define-problem 行 | ✓（transcript attachment #1 文本确认） |
| 模型真 invoke define-problem | **✗**（demo 真会话 Skill tool_use=0，模型跳过直接 Bash 分析） |
| canary `-p` 问 phase-rules 内容 | ✓ 能精确复述"载 skill define-problem"原文 |

**根因 = 模型遵从问题（非通道问题）**：
- attachment 通道：ark 收不到（症状 D，canary `NO_INJECTION` 证实）。
- phase-rules（system-prompt）通道：ark 能收到（canary 2 复述原文证实）。
- 但 `phase-rules.md` 里 skill 载入是**一句 prose 建议**，模型在交互会话收到用户实际提问后优先响应问题直接干活，把 prose 当可选忽略。`-p` canary 因指令强制"只回答"才老实照念。

**修正**：把 understand:1 的 skill 载入从"prose 建议"改成**首步强制+违规语义**（"未先 invoke define-problem 就开始分析=违规，等同未建清单就干活"），与"先建清单"强制同级。
- 待重验：新会话（fresh，载入新 phase-rules）understand:1 模型是否真先 invoke define-problem。

## 8. 二次实测记录（2026-07-23，强化 phase-rules 后）

强化后重验：模型**确实 invoke 了 define-problem** ✓（强化生效）。但发现两个新问题（同源）：

| 问题 | 实测时序（transcript aa521ee8） |
|---|---|
| ① skill 与读证据并行 | 事件 12/14 先跑 `ls *.md`/`grep FACTORS` 收证据，事件 19 才 invoke skill |
| ② 横幅时序错 | 事件 9 先出 `## PHASE` 横幅 + 文本，事件 19 才 invoke skill（预期：进阶段先 invoke skill，横幅应在 invoke 之后/同时） |

**根因**：phase-rules 写的是"首步=invoke"，但**没规定横幅与探查的绝对位置**，也没禁并行。模型合理地把 invoke 当"首步之一"，与 Bash 探查并行、且先出横幅后才 invoke。

**修正**：把 understand:1 从"首步强制"收敛为**严格时序**：
- ① 先出阶段横幅 -> 横幅后立即、在任何其它动作之前 invoke `define-problem`。
- ② `### EVIDENCE`/`### SUB_DONE`/探查证据（Bash/Read/Grep/Glob/codegraph）**不得在 invoke 之前或与 invoke 并行**。
- ③ 证据收集须等 skill 给出方法后再做，禁止抢跑。
- 违规判定：横幅后先跑 Bash 探查、或 invoke 与读证据并行 = 违规。
- 待重验：新会话 understand:1 是否横幅 -> invoke define-problem -> 才探查，且无并行抢跑。
