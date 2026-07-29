# understand:1 验真门 + skill-trace 证据链 Design

> ⚠️ **已取代（2026-07-24，§node-step-orchestration v2 commit 4）**：本文的「单 skill + ≥3 Q/A 验真门」过渡形态**已被删除**，understand:1 改为 4 子步骤逐步门控（`designs/node-step-orchestration-design.md` v2）。
> 保留本文作历史记录：read_evidence / rubric_needs_evidence / _evidence_artifact 函数被编排版复用（子步骤 gate 读 evidence）；understand:1 的「≥3 Q/A」gate_rubric + trace 注入块已删（commit d4765ea）。勿据本文排查运行问题（运行看 orchestration v2）。

> 状态：~~设计中（2026-07-24）。H8 Design-First 产物。~~ 已取代，见上。
> 父系统：`designs/tui-state-machine-design.md`（§8.6 evidence）、`designs/skill-injection-link-design.md`（understand:1 载 define-problem）。
> 范围：让 understand:1 的「验真问题是否真实」目的落进 engine（gate_rubric），define-problem 执行的小步 Q/A + 结论记进 evidence.jsonl（B'：模型直写文件，非 transcript 解析）。

## 0. 背景

`skill-injection-link-design` 已让 understand:1 载 define-problem（逼问/验真/钉约束/搜证据）。但：

- understand:1 当前 `gate_rubric=None`（`dl_flow_engine.py:84`），SUB_DONE 时 `run_gate` 只过机械项 NONE 直通（`:649-650`），**从未验真**。
- define-problem 的小步 Q/A +「问题是否真实」结论**不落证据链**--`write_gate_verdict` 只写一笔裁决摘要（`:470-484`），不含 step/q/a。
- 用户诉求：①「验真问题是否真实」目的维护在 engine ②define-problem 执行有小步思考+答案+最终结论 ③这些记进证据链 ④（停止测试：不做）。

`evidence-chain-design`（§8.6c 已弃用）的 transcript 解析机制脆，**不复用**。改用 B'：模型直写 evidence.jsonl。

## 1. 设计决策（已与用户确认 2026-07-24）

- **目的进 engine**：`understand:1.gate_rubric` = 验真判据（rubric 即目的，单源在 engine）。
- **载体 B'**：模型用 Write/Bash 把 skill-trace + conclusion 记录**直写** `.claude/evidence/<name>.jsonl`（非 transcript 解析）。漏写 -> gate block -> 模型重试补写（**可强制**，走现有 gate 重试环）。优于已弃用的 transcript 解析（解析失败哑失败不可强制）。
- **不改全局 skill**：define-problem SKILL.md 不动（避免污染非工作流会话）。记录/校验指令在工作流注入层（`workflow_phase.py`），仅工作流内生效。
- **judge 校验**：understand:1 从「无 rubric 直通」升级为「有 rubric 跑 judge」。SUB_DONE:1 时 Stop hook 读 evidence.jsonl 作 `artifact_content` 喂 judge，judge 按 rubric 判 pass/block。
- **停止测试**：不做（用户 2026-07-24 确认跳过）。

## 2. 改动

| # | 文件 | 改动 |
|---|---|---|
| 1 | `designs/define-problem-verify-gate-design.md` | 本文（H8） |
| 2 | `dl_flow_engine.py` | `understand:1.gate_rubric` 设验真判据；加 `rubric_needs_evidence()` / `read_evidence()` |
| 3 | `hooks/workflow_advance.py` | SUB_DONE/PHASE_DONE 过 gate 前，rubric 需 evidence 则读 evidence.jsonl 作 `artifact_content` |
| 4 | `hooks/workflow_phase.py` | 当前节点 rubric 需 evidence 时，注入「trace 写法」块（绝对路径 + 格式 + gate 校验项） |
| 5 | `tests/test_dl_flow_engine.py` | 测 rubric 非空 + `rubric_needs_evidence` + `read_evidence` |

## 3. 数据契约（evidence.jsonl 新增 record kind）

沿用 `<项目>/.claude/evidence/<name>.jsonl`（per-workflow，gate 裁决已写此）。新增两种记录，**模型写**：

```jsonl
{"kind":"skill-trace","step":1,"q":"谁有这个问题？频率？","a":"..."}
{"kind":"skill-trace","step":2,"q":"不解决会怎样？谁抱怨？","a":"..."}
{"kind":"skill-trace","step":3,"q":"为何现在解决？","a":"..."}
{"kind":"conclusion","problem_is_real":true,"reason":"...一句话..."}
```

- 与 `engine.write_gate_verdict` 写的 `kind=gate` 记录**同文件、顺序追加**（模型先写 trace+conclusion -> 输出 SUB_DONE -> hook 过 gate -> pass 后 engine 追加 gate 记录）。
- 字段最小：`step`/`q`/`a`（skill-trace）；`problem_is_real`(bool)+`reason`（conclusion）。**不引入** claim/depends_on DAG（已弃用）。

## 4. 流程

```
模型执行 define-problem（小步 Q/A，逐题）
  └ 每答一题：Write/Bash 追加 {"kind":"skill-trace",...} 到 evidence.jsonl
  └ 全部答完：追加 {"kind":"conclusion","problem_is_real":<bool>,"reason":"..."}
  └ 末尾输出 ### SUB_DONE: 1
        │
        ▼
Stop hook workflow_advance.py
  ├ SUB_DONE:1 命中 -> engine.rubric_needs_evidence(node)=True
  ├ engine.read_evidence(project_root,name) -> 文件文本（artifact_content）
  ├ run_gate(node, output, artifact_content=evidence_text) -> run_judge
  │   judge 按 rubric 判：①≥3 skill-trace(step/q/a) ②1 conclusion(problem_is_real+reason) ③q 覆盖 who/pain/why-now ≥3 类
  ├ pass -> write_gate_verdict(追加 kind=gate) + 推进 sub_index->2
  └ block -> additionalContext(reason) 续轮，模型补写后重试
```

## 5. 注入格式（workflow_phase.py）

当前节点 `engine.rubric_needs_evidence(node)` 为真时，`_format_injection` 追加：

```
- 证据链记录（本节点 gate 校验 evidence.jsonl，必写）：
  向 <project_root>/.claude/evidence/<name>.jsonl 追加（每行一条 JSON）：
   每完成一个 define-problem 提问 step：{"kind":"skill-trace","step":<n>,"q":"<问题>","a":"<答案>"}
   全部 step 完成后追加结论：{"kind":"conclusion","problem_is_real":<true|false>,"reason":"<为何真实/不真实>"}
  写法：文件不存在用 Write 创建；已存在先 Read 再拼末尾 Write（勿覆盖已有记录）；或 Bash printf '...' >> <abs_path>。
  evidence.jsonl 非源码，understand 阶段允许写。写完再输出 ### SUB_DONE: 1。
  gate 校验：≥3 条 skill-trace（各含 step/q/a）+ 1 条 conclusion（含 problem_is_real+reason）+ q 覆盖 who/pain/why-now 至少三类；缺则 block 重试。
```

- **绝对路径**：`_format_injection` 拿 `project_root`（`main()` 传入）；`name` 从 `state.name`。
- **条件 `rubric_needs_evidence`**：rubric 文本含 `"evidence/"` 或 `"skill-trace"`（rubric 自带 -> 单源驱动注入 + 校验）。

## 6. engine 改动细节

```python
# understand:1
"understand:1": Node(
    label="理解问题和背景", phase="understand", sub=1,
    skill="define-problem", artifact=None,
    gate_mech=GateMech.NONE,
    gate_rubric=(
        "验真问题是否真实：①evidence/<name>.jsonl 含 ≥3 条 kind=skill-trace 记录，"
        "每条有 step/q/a 三字段 ②含 1 条 kind=conclusion 记录，"
        "有 problem_is_real(bool)+reason ③q 覆盖 who/pain/why-now 至少三类。"
        "缺任一 block。"
    ),
    advance="sub",
),

def rubric_needs_evidence(node: Node) -> bool:
    """节点的 rubric 是否依赖 evidence.jsonl（决定 hook 要否读文件喂 judge）。"""
    r = node.gate_rubric or ""
    return "evidence/" in r or "skill-trace" in r

def read_evidence(project_root: Path, name: str) -> str | None:
    """读 evidence/<name>.jsonl 全文；缺失返回 None（judge 降级判 block，不默认放行）。"""
    p = _evidence_path(project_root, name)
    try:
        return p.read_text(encoding="utf-8") if p.exists() else None
    except OSError:
        return None
```

## 7. workflow_advance.py 改动细节

SUB_DONE 分支（:253）与 PHASE_DONE 分支（:314）调 `run_gate` 前：

```python
artifact_content = None
if engine.rubric_needs_evidence(node):
    artifact_content = engine.read_evidence(project_root, name)
ok, reason = engine.run_gate(node, output, project_root=project_root, artifact_content=artifact_content)
```

- 无 rubric 节点（understand:2-3）`rubric_needs_evidence=False` -> `artifact_content=None` -> `run_gate` 仍只过机械项（行为不变）。
- 读失败（None）-> judge 拿不到证据 -> 按 rubric 判 block（no silent fallback：不默认放行）。

## 8. 铁律

- **H8**：本文先于改 3 文件（engine + 2 hook）。
- **H9**：分 commit（design / engine+tests / advance / phase），每 ≤3 文件 AND ≤200 行。
- **H11**：hook 留痕日志 `%` 惰性格式化。
- **H12**：hook exit 0 only（不阻断）。
- **H15**：改 3 个已有 .py 前先 `codegraph affected` 留痕（2026-07-24 已跑 dl_flow_engine.py；改另两个前各补一次）。
- **no silent fallback**：`read_evidence` 失败返回 None（judge 降级判 block，不默认放行）；模型漏写 trace -> gate block。
- **verify before claiming done**：单测全绿 + ruff/mypy clean。

## 9. 风险

| # | 风险 | 缓解 |
|---|---|---|
| 1 | 模型不写 trace 就输出 SUB_DONE | gate block（judge 判缺 trace）-> 续轮重试补写 |
| 2 | evidence.jsonl 已有 gate 记录，模型 Write 覆盖丢记录 | 注入明确「先 Read 再拼末尾 Write，勿覆盖」；或 Bash `>>` 追加 |
| 3 | judge 成本（每次 SUB_DONE:1 一次 claude -p） | 可接受（验真是目的）；后续可加机械项预判 count 短路 |
| 4 | Bash `printf >>` 权限提示 | 用 Read+Write（非源码，免提示）为主；Bash `>>` 备选 |
| 5 | worktree cwd 到 evidence 路径 | 注入给绝对路径（project_root 已知） |

## 10. 验证

- **单测**：`understand:1.gate_rubric` 非空且含 "验真"/"skill-trace"；`rubric_needs_evidence(understand:1)=True`、`(plan:0/understand:4)=False`；`read_evidence` 缺失返 None、存在返内容。
- **live**：`dl <name>` 走到 understand:1，模型写 trace+conclusion -> SUB_DONE:1 -> gate pass -> 推进 understand:2；evidence.jsonl 含 skill-trace/conclusion/gate 三种记录。
