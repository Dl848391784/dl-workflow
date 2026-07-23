# dl-flow-engine 设计：TUI 原生 + 单源编排内核

> 状态：设计中（2026-07-23 起）。本文件为 H8 Design-First 产物，也是工作流编排子系统重构的真源。
> 对应实现（待建）：`dl-flow-engine.py`（一级目录）、`hooks/workflow_phase.py`（瘦化）、`hooks/workflow_advance.py`（瘦化 + 真 gate）。
> 替代/演进：`designs/workflow-system-design.md`（架构层不变，本文聚焦控制面重构）。

## 0. 背景与目标

### 0.1 痛点（驱动本次重构的实证）

现有工作流控制面"散"，真源访谈已坐实三处重复（hook 各自注释自己标了同步风险）：

| 常量/逻辑 | 现状副本数 | 散在哪 |
|---|---|---|
| `PHASES` 阶段表 | 3 份 | `wf-lib.sh:37` / `workflow_phase.py:28` / `workflow_advance.py:29` |
| `GATED_AFTER` 闸门集 | 2 份 | `wf-lib.sh:41` / `workflow_advance.py:39` |
| `SUBPHASES` 子阶段 | 3 份 | `wf-lib.sh:100` / `workflow_phase.py:82` / `workflow_advance.py:47` |
| 推进 state 逻辑 | 2 份 | `workflow_advance.py:_advance` / `wf-lib.sh:wf_state_set_phase` |

更关键的两处**能力缺口**：

- **无真门控**：~~现在推进只信模型回复末尾的 `### PHASE_DONE` / `### SUB_DONE` 字符串标记（`workflow_advance.py:294` 检正则）。标记存在 ≠ 节点目标真达成。没有"审模型返回符不符合预期再推进"。~~ **已修（§8.2/§8.3）**：engine.run_gate compound gate（机械 + judge），gate 过才推进。
- **证据链脆**：~~`evidence_append.py` 从 transcript 解析 `### EVIDENCE:{json}` 标记，SKILL.md 症状 I 花一整节 debug `no_markers`。~~ **已修（§8.6，用户决策弃用旧溯源系统）**：旧"模型每轮自发记 claim/依赖"系统删除，改由 engine.write_gate_verdict 在 gate-pass 写裁决记录（kind=gate 到 evidence/<name>.jsonl），不再解析 transcript 标记。

### 0.2 用户诉求（原话提炼）

> 一个 py 脚本确定：有几个大节点、每大节点下几个小节点、每小节点怎么实施（确定流程：载什么技能给模型 -> 模型返回后是否调门控审返回符不符合预期 -> 符合则写证据链 -> 可能多次调用 -> 判节点完成写 state.json 进下一节点）。加节点/加操作维护方便。**每节点过一道语义审**。用户补信息不能丢（不弃 TUI）。

### 0.3 目标

1. **单源编排内核** `dl-flow-engine.py`（一级目录，最核心脚本）：节点树 + skill 映射 + gate 判据 + 推进逻辑**唯一真源**，hook 瘦化为"事件检测 -> 委托 engine"。
2. **真门控**：每节点过 gate（机械项 + 语义项），机械不过短路 block、语语义过则推进。
3. **可靠证据**：gate 过则 engine 直接写 evidence jsonl，绕过 transcript 解析脆层。
4. **TUI 保留**：不弃交互式回合（用户补信息 + Edit 审批照常）。
5. **机械型 gate 失败自动重试**：Stop hook `additionalContext` 续轮，无用户介入。

### 0.4 非目标

- **不进程驱动**：engine 不当 `while: claude -p(...)` 进程主动调主流程模型。主流程回合由 TUI + Stop 事件驱动。engine 是"定义流程+决定流转"的裁判，不是挥鞭子的进程。（语义 gate 内的 `claude -p` judge 是 gate 用的工具，非主流程驱动，不破此约束。）
- **不替换隔离层**：worktree + state.json + per-wf settings（`workflow-system-design.md §4`）不变。
- **不重构 skill/output-style/phase-rules 的文本规则合并**：本文只收口"控制面代码逻辑"。skill 路由文本散在 `phase-rules.md`/`output-style`/`CLAUDE.md §2` 的合并是独立项（见 §7 待确认项 #1）。

## 1. 关键事实（设计前已核实）

| 事实 | 来源 | 对设计的影响 |
|---|---|---|
| Stop hook 可返 `hookSpecificOutput.additionalContext` 给模型反馈并**续轮**（非错误） | changelog:1000 | 机械型 gate 失败自动重试的唯一落地手段，无需外挂 loop |
| Stop hook 连续 block 8 次后告警终结（`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` 可 override） | changelog:1435 | 防死循环；判 gate 不过 -> 退化 banner + 用户驱动下一轮 |
| block 语义：exit 2 或 `{"decision":"block"}` 均可 | changelog:2248 | Stop hook block 是一等公民，非 hack |
| 现有 `codegraph_gate.py` 已用 exit 2+stderr 阻断范式（PreToolUse） | `hooks/codegraph_gate.py:198` | Stop gate 阻断范式有先例可循；但 Stop 用 `additionalContext` 续轮更佳（反馈进上下文，模型知错） |
| 现有推进只检 `### PHASE_DONE` 正则，无真判据 | `workflow_advance.py:294` | engine.run_gate 是净新增能力 |
| hook 现已用 `git rev-parse --git-common-dir` 反查主 repo 根（v2.0 修过 §10 根因） | `workflow_phase.py:101` | engine 复用此范式读 state.json；worktree 隔离不破 |
| skill 由模型自主 invoke Skill 工具载入（部分跑 subagent） | CLAUDE.md §2 路由表 | engine "载技能"=声明该节点应载哪个 skill -> hook 注入成 prompt 指令 -> 模型 invoke；engine 不直接塞 skill 进上下文 |
| `state.json` 当前字段：phase/index/sub_index/sub_total/gate/session_id/branch/worktree_path/history | `wf-lib.sh:142` | engine 沿用 schema，加 `current_node` 颗粒度（见 §4） |
| `transcript_path` 在 `-p` 下不可靠，交互式正常 | SKILL.md 症状 B | gate 读 transcript 取输出仅交互式可靠；judge 输入优先取声明产物文件，transcript 作辅 |

## 2. 架构总览

```
~/.dl-workflow/dl-flow-engine.py          ← 唯一真源（一级目录，最核心）
  ├─ 节点树（大节点 + 子节点，数据化声明）
  │    每节点：{skill, gate_mech, gate_semantic_rubric, artifact}
  ├─ current_node(name) -> 读 state.json -> 当前节点定义
  ├─ run_gate(name, output) -> (pass | block_reason)
  │    机械项短路：不满足直接 block（不跑 judge）
  │    语义项：起 claude -p judge（stateless reviewer）
  ├─ write_gate_verdict(name, node, attempts, cwd) -> gate-pass 追加 kind=gate 裁决记录到 evidence/<name>.jsonl
  └─ advance(name) -> 写 state.json 进下一节点（含子节点推进）

hooks/workflow_phase.py   (UserPromptSubmit)  瘦化
  └─ engine.current_node(name) -> 注入「## WORKFLOW 当前节点」(skill + 规则 + 完成判定)

hooks/workflow_advance.py (Stop)              瘦化 + 真 gate
  ├─ 读 transcript 取本轮输出
  ├─ engine.run_gate(name, output):
  │     pass  -> engine.write_gate_verdict() + engine.advance()
  │     block -> 返 hookSpecificOutput.additionalContext(reason) 续轮（模型自动重试）
  │     撞 cap / 判断型不过 -> banner，退化为用户驱动下一轮
  └─ 子节点 SUB_DONE 同构（gate 过才推进 sub_index）
```

### 编排 vs 进程驱动（命名澄清）

engine **编排**（定义流程 + 决定流转：节点树 / 每节点 skill / gate 判据 / 何时推进）。engine **不进程驱动**（不自当 `while: claude -p(...)` 主动调主流程模型轮次）。比喻：engine 是乐谱（编排），hooks + TUI 回合是乐队（按谱演奏）。乐谱不自己拉小提琴，但编排确实是乐谱定的。

主流程模型轮次触发方 = TUI 回合（user 发 / gate 失败 Stop 续轮）。语义 judge 的 `claude -p` 是 gate 用的工具（同 gate 调 codegraph），非主流程驱动进程。

## 3. 节点树数据结构（engine 核心）

声明式，加节点/改审据只改数据不改逻辑。

```python
# 节点标识：<phase>:<sub_index>（sub_index=0 表示无子节点的整阶段）
# 例 "understand:1" = understand 大阶段第 1 子阶段；"execute:0" = execute 整阶段

NODES = {
    "understand:1": Node(
        label="理解问题和背景",
        skill=None,  # 该节点无强制 skill；靠 phase-rules 行为约束
        artifact=None,  # 子阶段无独立产物，末子阶段写 understand.md
        gate_mech=GateMech.NONE,  # 子阶段间自动推进，无机械门
        gate_rubric=None,  # 子阶段也无语义审（快流转）
        advance="sub",  # "sub"=推进 sub_index；"phase"=推进 phase（末子阶段）
    ),
    # ... understand:2/3 同构 ...
    "understand:4": Node(
        label="定义成功标准和验收方式",
        skill=None,
        artifact="understand.md",  # 末子阶段写产物
        gate_mech=GateMech.ARTIFACT_EXISTS,  # 机械：understand.md 存在
        gate_rubric="对照注入的真实问题：①是否重述真实问题(非字面) ②边界 in/out-scope ③可验证成功标准。缺任一 block。",
        advance="phase",  # 末子阶段 -> 推进到 plan（过 understand->plan 闸门）
    ),
    "plan:0": Node(
        label="生成执行计划",
        skill="superpowers:using-superpowers",  # 声明载入
        artifact="plan.md",
        gate_mech=GateMech.ARTIFACT_EXISTS,
        gate_rubric="plan 是否针对真实问题设计：①步骤可执行 ②验证方法明确 ③守 H8/H9。",
        advance="phase",  # -> execute（过 plan->execute 闸门）
    ),
    "execute:0": Node(
        label="执行",
        skill=None,
        artifact="代码+commit+测试通过",
        gate_mech=GateMech.TEST_PASS,  # 机械：pytest 通过
        gate_rubric="实现是否真正执行了 plan.md：对照 plan 步骤逐条核，偏离需有理由。",
        advance="phase",  # 自动到 review（无闸门）
    ),
    "review:0": Node(
        label="审核结果",
        skill=None,
        artifact="review.md",
        gate_mech=GateMech.ARTIFACT_EXISTS,
        gate_rubric="对照 understand.md 真实问题 + 成功标准，判定 solved/partial/not，附 file:line 证据。",
        advance="phase",
    ),
    "evolution:0": Node(
        label="进化",
        skill=None,
        artifact="evolution.md",
        gate_mech=GateMech.ARTIFACT_EXISTS,
        gate_rubric="是否沉淀非显然可复用经验（memory/skill/design）。",
        advance="done",
    ),
}

# 闸门（继承现有 GATED_AFTER 语义，收口到 engine 一份）
GATED_AFTER = {"understand", "plan"}  # 这些 phase 末节点完成需用户 /wf gate 放行才进下一 phase
```

**维护性兑现**：加节点 = 在 NODES 加一条；加机械门 = `gate_mech` 加枚举 + 实现；加语义审据 = 改 `gate_rubric` 字符串。无需碰 hook 逻辑。

## 4. state.json schema 演进

```json
{
  "name": "...",
  "phase": "understand",        // 大阶段（英文标识，逻辑层）
  "index": 1,                   // phase 序号 1-5（显示用）
  "sub_index": 1,               // 子阶段序号（无子阶段=0）
  "sub_total": 4,               // 该 phase 子阶段数（无=0）
  "node": "understand:1",       // 【新增】当前节点标识（engine 推导主键，防 phase+sub 不一致）
  "gate": "pending",            // phase 级闸门状态
  "node_attempts": 0,           // 【新增】当前节点 gate block 次数（观测 + 接近 cap 预警）
  "session_id": "...",
  "branch": "...", "worktree_path": "...",
  "history": [...]
}
```

`node` 字段是 engine 的主键，由 `phase`+`sub_index` 推导，但单独存以防两者失同步（守 no silent fallback：不一致时 engine 报错暴露而非猜）。

旧 state.json（无 `node`/`node_attempts`）向后兼容：engine 读时缺则按 phase+sub 推导补默认。

## 5. gate 判定流程（compound + 短路）

```
run_gate(name, output):
  node = current_node(name)
  # 1. 机械项（py 规则，快、便宜、无幻觉）
  if node.gate_mech == ARTIFACT_EXISTS and not artifact_file_exists(node.artifact):
      return block(f"产物缺失：{node.artifact}")
  if node.gate_mech == TEST_PASS and not last_pytest_passed():
      return block("pytest 未通过，附失败输出")
  # 机械不过 -> 短路返回，不跑 judge（省一次模型调用）
  # 2. 语义项（judge，判"符合预期吗"）
  if node.gate_rubric:
      verdict = run_judge(node.gate_rubric, output, artifact_content(node.artifact))
      if verdict.block:
          return block(verdict.reason)
  return pass
```

### 5.1 judge 设计

- **stateless `claude -p`**：独立会话，不续主 session（防污染主上下文）。
- **输入**：node.gate_rubric（判据）+ 模型本轮输出（transcript 取或产物文件）+ 声明产物内容。
- **输出**：`{"pass": bool, "reason": "..."}`（JSON 强约束，`--output-format json`）。
- **成本**：每节点 ≥2 次模型调用（主 + judge），机械短路时 1 次。撞 8 次 cap -> 退化人工。
- **降级**：judge 调用失败（API 错/超时）-> engine 不推进，banner 提示用户手动核（no silent fallback：失败必暴露，不默认放行）。

### 5.2 Stop hook 续轮数据流

```
gate block(reason)
  -> Stop hook 返 {"hookSpecificOutput":{"additionalContext": 
       "## GATE 未通过\n" + reason + "\n请修正后重新完成本节点。"}}
  -> 模型自动续轮重试（无用户介入）
  -> node_attempts++
  -> 撞 8 cap -> 不再续轮，banner 退化为用户驱动
```

## 6. 与现有组件的关系

| 现组件 | 改动 | 改后职责 |
|---|---|---|
| `workflow_advance.py` (Stop) | **瘦化**：删 PHASES/GATED_AFTER/SUBPHASES 副本 + `_advance` 逻辑，委托 engine | 事件检测（读 transcript 取输出）-> `engine.run_gate()` -> pass 推进/block 续轮 |
| `workflow_phase.py` (UserPromptSubmit) | **瘦化**：删副本，委托 engine.current_node | 注入当前节点 skill + 规则 + 完成判定 |
| `wf-lib.sh` | **保留 state 读写**（bash 侧 wf-cmd 手动覆盖仍需），但**删 PHASES/GATED_AFTER/SUBPHASES 副本**，改调 `python3 dl-flow-engine.py <cmd>` | 手动 `/wf` 覆盖 + worktree/settings 管理 |
| `wf-cmd.sh` | `next`/`back`/`jump`/`gate` 改调 engine CLI | 手动覆盖入口 |
| `phase-rules.md` | 保留（append-system-prompt 行为约束） | 行为约束文本（与 engine 节点 skill 映射协同） |
| `output-styles/workflow.md` | 保留 | 横幅 + TaskList 清单 |
| `evidence_append.py` (Stop 第二个) | **已删（§8.6c）**：旧"模型每轮自发记 claim/依赖"推理溯源系统弃用（用户决策），engine.write_gate_verdict 在 gate-pass 写裁决记录替代 | - |
| `codegraph_gate.py`/`audit.py` | 不动 | H15 门禁照常 |
| `wf-launch.sh` | 不动 | worktree + state + session 隔离不变 |

### 迁移策略

- engine 先建为**纯库**（无副作用读），hook 瘦化改调它，state.json 加新字段（向后兼容）。
- 旧工作流（无 node 字段）自动兼容。
- ~~evidence 收口最后做（先双写观察，再关 evidence_append.py）。~~ evidence 收口已完成（§8.6c 删 evidence_append.py + §8.6a 加 engine.write_gate_verdict，用户决策弃用旧 ### EVIDENCE 溯源系统，直接替换无双写期）。
- 分小 commit（守 H9）。

## 7. 风险与待确认项

| # | 项 | 缓解/待定 |
|---|---|---|
| 1 | skill 路由文本仍散在 phase-rules/output-style/CLAUDE.md §2 | 本文不收口文本合并（独立项）。engine 的 NODES.skill 字段是数据化声明，与文本协同；后续可让 phase-rules 引用 engine 的 skill 映射（去重） |
| 2 | judge 成本（每节点 +1 模型调用） | 机械短路省；judge 可配置 `gate_rubric=None` 关闭（如 understand 子阶段 1-3 不审） |
| 3 | judge 自己误判 | 独立会话 stateless；reason 回灌主会话，用户可见可覆盖（手动 /wf gate 强过） |
| 4 | Stop additionalContext 在 ark-code-latest 是否真续轮 | **待验证（用户真会话进行中）**：changelog 证实机制存在 + `_block_continue` 格式已验 + hook 真会话已被调用（.wf_advance.log 留痕）+ 子阶段推进路径实测通过；"模型收到 reason 后自动重试"端到端行为需真交互式 TTY 验（脚本无法验）。若不续轮 -> 回退 §8.3 续轮为 banner 人工兜底 |
| 5 | transcript 取本轮输出在 ark 下可靠性 | judge 输入优先取声明产物文件（understand.md 等，磁盘读可靠），transcript 作辅 |
| 6 | 旧 state.json 无 node 字段 | engine 读时按 phase+sub 推导补默认；不一致报错暴露 |
| 7 | ~~evidence 收口双写期数据一致性~~ | **已完成（§8.6c）**：旧 ### EVIDENCE 系统直接删除（用户决策弃用），无双写期；gate-pass 写 kind=gate 裁决记录替代 |
| 8 | 撞 8 cap 后状态 | engine 记 node_attempts，banner 明示"已达自动重试上限，请人工核"；不静默放行 |

## 8. 实施步骤（小 commit，守 H9）

1. `dl-flow-engine.py` 骨架：节点树数据结构 + current_node/run_gate（机械项）+ advance + CLI（`python3 dl-flow-engine.py status|current|advance`）。纯库，无 hook 接入。单测节点树推导。
2. judge 接入：`run_judge`（stateless claude -p + JSON 输出）+ compound gate 短路。
3. `workflow_advance.py` 瘦化：删副本，委托 engine.run_gate + additionalContext 续轮。冒烟验 Stop block 续轮（待确认项 #4）。
4. `workflow_phase.py` 瘦化：删副本，委托 engine.current_node 注入。
5. `wf-lib.sh`/`wf-cmd.sh`：删 PHASES/GATED_AFTER/SUBPHASES 副本，改调 engine CLI。
6. ~~evidence 收口：engine.write_evidence 双写观察 -> 一致后关 evidence_append.py。~~ **已完成（§8.6）**：a) engine.write_gate_verdict（gate-pass 写裁决记录）；b) workflow_phase 删 ### EVIDENCE 注入块 + wf-lib 删 evidence_append Stop 注册；c) 删 evidence_append.py + 2 测试。用户决策弃用旧溯源系统，直接替换无双写期。
7. ~~state.json 加 node/node_attempts 字段 + 旧 state 兼容。~~ **已完成（§8.1）**：normalize_state 补 node/node_attempts，旧 state 向后兼容，不一致报错暴露。

## 8.1 实现状态（2026-07-23 完成，待续轮验证）

§8.1-§8.6 全部落地（分支 `feat/dl-flow-engine`，未 push）。78 测试通过。唯一待验 = §7 #4 Stop 续轮端到端（用户真会话进行中）。

### gate 裁决记录 schema（§8.6 新机制，替代旧 ### EVIDENCE 溯源）

gate-pass 时 engine.write_gate_verdict 写一行到 `<项目>/.claude/evidence/<name>.jsonl`：

```json
{"kind":"gate","node":"understand:4","phase":"understand","sub":4,"label":"定义成功标准和验收方式",
 "gate":"passed","gate_mech":"artifact_exists","rubric":"<审据或 null>","attempts":1,
 "skill":null,"via":"auto-stop","ts":"2026-07-23T...","commit_sha":"<HEAD 或空>"}
```

字段：`kind=gate`（标识新记录类型，与旧 ### EVIDENCE 区分）/ `node` 节点标识 / `gate=passed`（仅 pass 写，block 不写）/ `gate_mech` 机械门类型 / `rubric` 语义审据（None=仅机械过）/ `attempts` 重试次数 / `commit_sha` 防腐锚点（git rev-parse HEAD，非 git 空串）。block 重试计数在 state.node_attempts，pass 时一并记入此条。

## 9. 已定决策（design 落地前拍板）

1. **入口 = claude TUI**（不跑 py 脚本）：`dl <name>` → `wf-launch.sh` → `exec claude`（`wf-launch.sh:170` 不变）。engine 是被 hook 咨询的内核,不当主进程、不开 `while` 循环调模型。用户侧 `dl` 命令 / worktree 隔离 / `/wf` 手动覆盖全不变;变只在会话内 hook 瘦化委托 engine。
2. **judge model = 继承主会话 env**：judge 的 `claude -p` 子进程继承 launcher env（即 `dl <name>` 当前用的 provider/model），不另指定。judge 是 gate 用的工具,跑在主会话已起的 provider 上,配置天然可得。省省钱/换轻量后续加 `JUDGE_MODEL` 常量可配。
3. **gate 严格度 = 只 pass/block 两档**：先简单。缺任一机械项或缺语义 rubric 任何一条 -> block。不预设"警告但放行"档,后续按需加。

编排 vs 进程驱动（对应 §2 命名澄清）：**TUI 是执行者,engine 是编排者**。engine 定义"该干啥/判对不对/何时前进"（节点树 + gate + 推进）;TUI + 回合负责实际演奏（用户发消息/模型跑/Edit 审批/补信息）。engine 不拉小提琴（不主动调模型轮次）,只在 UserPromptSubmit（载哪个 skill）和 Stop（过 gate 否）两时刻被 hook 咨询。
