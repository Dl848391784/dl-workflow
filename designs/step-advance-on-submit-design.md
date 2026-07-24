# 子步骤推进移到 UserPromptSubmit Design（方案 3a：避开 transcript flush 竞态）

> 状态：设计中（2026-07-24）。H8 Design-First 产物，先于实现。
> 父系统：`designs/node-step-orchestration-design.md` v2（编排）。
> 范围：STEP_DONE 完成信号检测从 Stop hook（读 transcript，遇 flush 竞态）移到 UserPromptSubmit（读已落盘 evidence.jsonl）。gate+推进合一在 UserPromptSubmit（3a）。

## 0. 背景

### 0.1 实测发现（demo 会话 f652f370，2026-07-24）

编排流程符合预期：模型 invoke define-problem、走完子步骤1、输出 `### STEP_DONE: 1`。
但 **Stop hook 没检测到 STEP_DONE、gate 没跑、sub_step_index 没推进**（state 仍 MISSING）。

根因（排除法锁定）：本轮模型先发短文本(event 53, len=164) + AskUserQuestion + 答完后发 event 58(含 STEP_DONE, len=216)。Stop hook 在 event 58 后 136ms 触发，但读 transcript 时 event 58 尚未 flush，`_last_assistant_text` 读到 event 53（无 STEP_DONE）-> `no_done_marker`。文件完整后读则正确返回 event 58。

**判定**：Claude Code Stop hook 触发早于 transcript 最后一条 assistant flush 的竞态。靠 transcript 文本检测完成信号不可靠。

### 0.2 附带发现的遗漏（commit 4 切换引入）

understand:1 commit 4 切换为 sub_steps 后：
- `gate_rubric=None` -> `rubric_needs_evidence=False` -> workflow_phase 的 trace 注入块（行 263-285）**不再触发**。
- 但 understand:1 子步骤 gate（step.gate）依赖 evidence 里的 skill-trace 记录（`step_needs_evidence=True`）。
- => 模型不知道要写 evidence（无格式注入），实测 demo evidence.jsonl **不存在**。

即使 Stop 能检测 STEP_DONE，gate 读 evidence 也是空 -> block。

## 1. 设计决策

| # | 决策 | 理由 |
|---|---|---|
| E1 | **完成信号源 = evidence.jsonl**（已落盘），非 transcript 文本 | 避开 flush 竞态；evidence 是模型上轮写、早已 flush；UserPromptSubmit 时距 STEP_DONE 已隔用户思考（秒级），无竞态 |
| E2 | **gate + 推进合一在 UserPromptSubmit**（3a） | 3b 先推进后 gate 会闪烁；3c 放弃语义 gate 违背编排 D4。3a 无闪烁、gate 兜底强；代价是带新 evidence 的轮 UserPromptSubmit 有 judge 延迟（秒级，可接受） |
| E3 | **understand:1 子步骤仍输出 `### STEP_DONE: <n>`** | 仅作模型自声明 + 人读信号，**hook 不靠它推进**。保留注入里的 STEP_DONE 格式（模型行为不变，迁移成本低） |
| E4 | **evidence skill-trace 统一用 `sub_step` 字段**（非 `step`） | UserPromptSubmit 据此判断"当前子步骤的 trace 是否已写"。对齐模型写法与 hook 读取 |
| E5 | **Stop hook 删 STEP_DONE 分支** | 子步骤推进移走；Stop 只保留无 sub_steps 节点的 SUB_DONE/PHASE_DONE（行为不变） |
| E6 | **trace 写法注入移到 sub_steps 清单块**（修复 0.2 遗漏） | understand:1 有 sub_steps 时，清单块带上 evidence 写法格式（绝对路径 + JSON 格式）；删旧的 rubric_needs_evidence 触发的 trace 块（已失效） |

## 2. 数据流（方案 3a）

```
模型执行子步骤1（按注入格式写 {"kind":"skill-trace","sub_step":1,"purpose":...,"q/a":...} 到 evidence.jsonl）
  -> 输出 ### STEP_DONE: 1（自声明，hook 不靠它）
  -> 回合结束（end_turn）
        ▼
用户下次提问
        ▼
UserPromptSubmit hook（workflow_phase.py）
  ├ 读 state：当前 sub_step_index
  ├ 读 evidence.jsonl：找 sub_step == sub_step_index 的 skill-trace 记录
  ├ 有新 trace -> 跑 gate（engine.run_judge 用 Step.gate rubric + evidence 全文作 artifact_content）
  │   pass -> 推进：非末步 sub_step_index++；末步 engine.advance_state 推进子阶段
  │   block -> 不推进，注入"子步骤 N 未达标（reason），重做"
  └ 无新 trace -> 不推进，注入"当前子步骤 N（未完成，按 purpose 做 + 写 evidence）"
注入当前阶段（已推进或未推进后的状态）
```

## 3. engine 改动

### 3.1 新增 helper：读 evidence 找当前子步骤的 trace

```python
def sub_step_has_trace(
    project_root: Path, name: str, sub_step_index: int
) -> bool:
    """evidence.jsonl 是否含 sub_step == sub_step_index 的 skill-trace 记录。

    §step-advance-on-submit E1：UserPromptSubmit 据此判断当前子步骤是否已写 evidence。
    缺文件/读失败 -> False（judge 降级判 block）。
    """
    text = read_evidence(project_root, name)
    if not text:
        return False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(rec, dict)
            and rec.get("kind") == "skill-trace"
            and rec.get("sub_step") == sub_step_index
        ):
            return True
    return False
```

### 3.2 子步骤 gate + 推进函数（供 workflow_phase 调）

```python
def gate_and_advance_sub_step(
    project_root: Path, name: str, node: Node, sub_step_index: int, output: str
) -> tuple[bool, str, dict]:
    """gate 当前子步骤 + 推进。返回 (advanced, reason, new_state)。

    advanced=True 表示已推进（sub_step_index++ 或末步推进子阶段）；
    advanced=False 表示 block（未推进，模型需重做）。
    """
    step = sub_step_at(node, sub_step_index)
    # gate=None 自动过；否则跑 judge（artifact_content = evidence 全文）
    if step.gate is None:
        ok, reason = True, ""
    else:
        artifact = read_evidence(project_root, name)
        ok, reason = run_judge(step.gate, f"{node.label}·子步骤{sub_step_index}", output, artifact_content=artifact)
    if not ok:
        return False, reason, {}
    # 推进
    state = load_state(project_root, name)
    state = normalize_state(state)
    if sub_step_index < len(node.sub_steps):
        state["sub_step_index"] = sub_step_index + 1
        save_state(project_root, name, state)
        return True, "", state
    # 末步：推进子阶段
    new_state = advance_state(project_root, name, via="step-submit")
    return True, "", new_state
```

## 4. workflow_phase.py 改动（UserPromptSubmit）

### 4.1 推进逻辑（main 里 _format_injection 之前）

```python
# §step-advance-on-submit：有 sub_steps 节点的子步骤推进 + gate 在此（读 evidence，避开 transcript 竞态）
node = get_node(phase, sub_index)
if node.sub_steps:
    sub_step_index = state.get("sub_step_index", 1)
    if engine.sub_step_has_trace(project_root, name, sub_step_index):
        # 当前子步骤 evidence 已写 -> gate + 推进
        advanced, reason, new_state = engine.gate_and_advance_sub_step(
            project_root, name, node, sub_step_index, output=""
        )
        if advanced:
            state = new_state  # 推进后重新 normalize 注入
        else:
            # block：注入重做提示（追加到注入文本）
            block_hint = f"## 子步骤 {sub_step_index} 未通过门控\n{reason}\n请重做该子步骤（purpose 见下）"
            # 注入仍走，但带 block 提示
```

- output 传 ""（不靠 transcript；gate 用 evidence + rubric）。
- 推进后 state 更新，_format_injection 注入"当前子步骤 N+1"。

### 4.2 trace 写法注入移到清单块（修复 0.2 遗漏）

sub_steps 清单块加 evidence 写法格式（当 record 步存在时）：
```
- 子步骤编排（本节点 N 子步骤...）：
  ...
  evidence 记录（record 步必写）：向 <abs_path> 追加（每行一条 JSON）：
   {"kind":"skill-trace","major_stage":"<Phase>","minor_stage":"<MinorKey>","sub_step":<n>,"purpose":"<该步目的>","q":["<q1>","<q2>",...],"a":["<a1>","<a2>",...]}
  字段：major_stage=phase 英文首字母大写（Understand/Plan/…）；minor_stage=子阶段英文标识（首字母大写驼峰，如 ProblemContext）；q/a=字符串数组按序对齐。
  写法：Write 创建 / Read+拼末尾Write / Bash printf >> 。勿覆盖已有。
```

- 删旧 rubric_needs_evidence 触发的 trace 块（行 263-285，已对 understand:1 失效）。

## 5. workflow_advance.py 改动（Stop）

- 删 STEP_DONE_RE 检测分支 + _handle_step_done（行 364-372 调用）。
- 保留 _step_evidence_artifact / STEP_DONE_RE？删 _handle_step_done + 调用；STEP_DONE_RE 可留作未来或删。
- SUB_DONE/PHASE_DONE 逻辑不变（无 sub_steps 节点用）。
- understand:1（有 sub_steps）的子阶段推进由 workflow_phase 末子步骤 gate+advance 调 advance_state 完成，不经 Stop。

## 6. 与现有协议的关系

| 节点类型 | 完成信号 | 推进/gate 时机 |
|---|---|---|
| 无 sub_steps（understand:2-4, plan, execute...） | `### SUB_DONE`/`### PHASE_DONE`（transcript） | Stop hook（读 transcript，无竞态：单条文本无工具中断） |
| 有 sub_steps（understand:1） | `### STEP_DONE`（自声明）+ evidence.jsonl | **UserPromptSubmit**（读 evidence，避开竞态） |

- 两套互斥（同节点只用一套）。
- 无 sub_steps 节点仍靠 transcript 检测（这类节点单条文本回复，无 AskUserQuestion 中断，flush 竞态风险低；若未来也遇竞态再迁）。

## 7. 铁律

- **H8**：本文先于实现（engine + 2 hook + tests）。
- **H9**：分 commit（design / engine helpers+tests / workflow_phase 推进+注入 / workflow_advance 删 STEP_DONE / 切换+实测），每 ≤3 文件 AND ≤200 行。
- **H11/H12**：hook 日志 `%` 惰性，UserPromptSubmit exit 0 only（不阻断；gate block 走注入提示非阻断）。
- **H15**：改已有 .py 前先 codegraph affected 留痕。
- **no silent fallback**：evidence 缺/读失败 -> gate 判 block（不默认放行推进）。
- **verify before claiming done**：单测 + live（dl <name> 走 understand:1，验证 UserPromptSubmit 推进 + gate）。

## 8. 风险

| # | 风险 | 缓解 |
|---|---|---|
| 1 | UserPromptSubmit 跑 judge（~秒级）阻塞用户输入到模型 | 只在有 sub_steps + evidence 有新 trace 时跑；judge 短 prompt；可接受（3a 认） |
| 2 | 推进滞后一轮（用户下次提问才推进） | 自洽：模型 STEP_DONE 后 end_turn，用户提问时注入已推进；体验无割裂 |
| 3 | 模型不写 evidence（sub_step 字段） | trace 写法注入明确格式；gate 判 block（无 trace）-> 注入重做 |
| 4 | evidence.jsonl 多轮累积，sub_step_has_trace 误判旧轮 trace | sub_step 字段对齐当前 index；同 sub_step 重复写不误判（has 即 True） |
| 5 | gate block 后模型重做仍写同 sub_step trace -> 重复 | evidence append 不去重；has_trace 只判存在；judge 读全文校验内容（重复无害） |
| 6 | understand:1 末子步骤 gate=None 自动过 -> 末步推进子阶段在 UserPromptSubmit | OK；advance_state 推进 understand:2 |

## 9. 实施步骤（分小 commit）

1. ✅ 本 design（H8）。
2. ✅ engine：`sub_step_has_trace` + `gate_and_advance_sub_step` + 单测（+11）。（commit 344ba2a）
3. ✅ workflow_phase.py：UserPromptSubmit 推进逻辑 + trace 写法注入移到清单块 + 删旧 trace 块。（commit 4c4b420）
4. ✅ workflow_advance.py：删 STEP_DONE 分支 + _handle_step_done + _step_evidence_artifact；删过时测试。（commit e56543c）
5. ⏳ live 验证：dl <name> 走 understand:1，验证用户下次提问时推进 + gate + evidence 落盘。
   - 代码侧：单测 119 passed + 冒烟（末步推进/无evidence不推进/注入含sub_step格式）PASS。
   - 真会话 live 待用户跑。
