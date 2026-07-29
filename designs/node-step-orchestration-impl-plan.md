# 实施计划：节点步级编排 v2（Node.sub_steps + STEP_DONE 逐步门控）

> 基于 `designs/node-step-orchestration-design.md` v2（已定稿，用户确认 D6=逐步门控 / D7=engine 声明 / 4 子步骤 / 同 commit 切换 / 删子阶段级 gate_rubric）。
> 本文件是 design §12 的可执行 commit 序列。每 commit 守 H9（≤3 文件 AND ≤200 行）+ TDD。

## 前置：当前未提交状态

刚发布的 understand:1 验真门（4 文件改 + 1 design，未提交，在 `feat/dl_flow_engine` 分支）：
- `dl_flow_engine.py`：understand:1.gate_rubric + `read_evidence()` + `rubric_needs_evidence()`
- `hooks/workflow_advance.py`：`_evidence_artifact()` + 两处 run_gate 传 artifact_content
- `hooks/workflow_phase.py`：`_format_injection(state, project_root)` + trace 注入块
- `tests/test_dl_flow_engine.py`：+11 例
- `designs/define-problem-verify-gate-design.md`

**处理**：不单独提交过渡形态（用户"不需要过渡"）。把它的有用部分（`read_evidence`/`rubric_needs_evidence`/`_evidence_artifact`/`_format_injection` 加 project_root 参数）作为 v2 基础，在 v2 commit 里直接演进。understand:1 的"≥3 Q/A" gate_rubric + trace 注入块**删除**（被 sub_steps 取代）。

## Commit 序列

### Commit 1：engine schema（Step + Node.sub_steps + state.sub_step_index）

文件（3）：
- `dl_flow_engine.py`
- `tests/test_dl_flow_engine.py`
- `designs/node-step-orchestration-design.md`（标实施进度）

改动：
1. 加 `Step` dataclass（kind/ref/purpose/input/record/gate）。
2. `Node` 加 `sub_steps: tuple[Step,...] | None = None`（frozen dataclass，默认 None 保向后兼容）。
3. `normalize_state`：补 `sub_step_index` 字段（缺省按 1 若有 sub_steps else 0；与 sub_steps 总数不一致报错暴露）。
4. 加 `sub_step_total(node)` / `sub_step_rubrics(node)` helper。
5. understand:1 **暂不改**（下个 commit 切换）--先保证 schema 不破坏现有行为（sub_steps=None 全程 None）。

测试（TDD 先写）：
- `Step` 构造 + frozen。
- `Node.sub_steps` 默认 None；设了能取。
- `normalize_state` 旧 state 补 sub_step_index；不一致报错。
- `sub_step_total`/`sub_step_rubrics` 对 None/有 steps 节点。
- 全量现有测试不破（sub_steps=None 行为不变）。

H15：改 `dl_flow_engine.py` 前先 `codegraph affected ~/.dl-workflow/dl_flow_engine.py` 留痕。

### Commit 2：workflow_phase.py 注入子步骤清单

文件（1）：
- `hooks/workflow_phase.py`

改动：
1. `_format_injection`：节点 `sub_steps` 非 None 时，追加**子步骤清单块**（逐子步骤 purpose + input + record + 当前步高亮 sub_step_index）。
2. STEP_DONE 格式提示：当前子步骤完成输出 `### STEP_DONE: <n>`。
3. **删** understand:1 的 trace 注入块（过渡形态，被清单块取代）--但本 commit understand:1 还没 sub_steps，故 trace 块此时无节点触发（rubric_needs_evidence 因下个 commit 才改 rubric）。**实际**：本 commit 只加清单块逻辑，understand:1 切换放 commit 4。trace 块保留至 commit 4 删。

测试：手动注入冒烟（sub_steps 非 None 的假节点 -> 输出含清单块 + STEP_DONE 格式）。

### Commit 3：workflow_advance.py STEP_DONE 逐步 gate

文件（1）：
- `hooks/workflow_advance.py`

改动：
1. 加 `STEP_DONE_RE = r"###\s*STEP_DONE:\s*(\d+)"`。
2. `main()` 在 SUB_DONE 检测**之前**加 STEP_DONE 检测分支：
   - 节点有 sub_steps 才走（无 sub_steps 节点 STEP_DONE 忽略，避免污染）。
   - `n == sub_step_index` 校验（防跳步，同 SUB_DONE 守卫范式）。
   - gate 该子步骤：`engine.run_gate` 用 `Step.gate`（非 None 才 judge；None 自动过）+ `_evidence_artifact` 读 evidence。
   - pass：`sub_step_index++`；若 == sub_step_total -> 末子步骤，推进子阶段（sub_index++，复用现有推进逻辑）；else 续轮做下子步骤。
   - block：`_block_continue(reason 指明哪子步骤 purpose 未达)` 续轮重试。
3. 复用现有 `_evidence_artifact` / `engine.read_evidence`（commit 1 保留）。
4. state 读写加 `sub_step_index`（pass 时更新，推进子阶段时归零）。

测试：单测 STEP_DONE 解析 + 逐步 gate mock（judge pass/block/末步推进）。

### Commit 4：understand:1 切换 + 删过渡形态

文件（2）：
- `dl_flow_engine.py`
- `tests/test_dl_flow_engine.py`

改动：
1. understand:1：`gate_rubric=None`（删"≥3 Q/A"）+ `sub_steps=(4 子步骤)`（design §2.3）。
2. 删 `rubric_needs_evidence` 对 understand:1 的触发（sub_steps 驱动取代；`rubric_needs_evidence` 函数保留供未来其他节点）。
3. 更新测试：understand:1.gate_rubric is None；sub_steps 4 步；sub_step_rubrics 返回 3 个（子4 gate=None 跳过）；旧"≥3 Q/A"测试删除/改写。

H15：改 engine 前留痕。

### Commit 5：design 标完成 + live 验证

文件（1）：
- `designs/node-step-orchestration-design.md`（标 §12 各步 ✅ + live 记录）

live：`dl <name>` 走 understand:1，验证 4 子步骤逐步 STEP_DONE gate + skill 内部 Q/A 不门控 + evidence 选择性落盘 + 末步推进 understand:2。

## 不改的（守边界）

- `workflow_advance.py` 现有 SUB_DONE/PHASE_DONE 逻辑（无 sub_steps 节点用）零改。
- `Node` 其他字段不变。
- `define-problem` SKILL.md 不动（D7：目的在 engine 声明，非 skill）。
- evidence.jsonl 路径不变（`<repo>/.claude/evidence/<name>.jsonl`）。

## 风险点（实现时盯）

- **frozen dataclass 加默认字段**：`sub_steps=None` 默认值，frozen dataclass 各节点构造不传 sub_steps 时取默认。需确认现有 `_NODES` 构造不破（未传 sub_steps -> None）。
- **STEP_DONE vs SUB_DONE 互斥**：understand:1 有 sub_steps 后用 STEP_DONE（末步推进子阶段），**不再用 SUB_DONE**。注入块要明确（design §10 风险 8）。
- **末子步骤 gate=None 自动过**：子4 gate=None，STEP_DONE:4 时 run_gate 跳过 judge 直接过 -> 推进子阶段。
- **judge 成本**：understand:1 = 4 次 judge。可接受。
