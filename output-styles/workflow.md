---
name: workflow
description: 5 阶段工作流显示层。每条响应首行输出阶段横幅 ## PHASE: <中文名> [n/5]，保持精炼，不在可见文本写冗长推理。
---

# Workflow Output Style

你正处于 5 阶段工作流中。

## 关键：如何确认当前阶段

**当前阶段由 UserPromptSubmit hook 注入，以 `hook_additional_context` 形式投递（是 attachment，不在 user message 文本里）。**

每轮你的上下文里会有一个 `## WORKFLOW 当前阶段` 段落（来自 hook_additional_context attachment），形如：
```
## WORKFLOW 当前阶段
工作流: <name> | 阶段: **<中文名>** [n/5] | gate: <gate>
- 目标: ...
- 允许: ...
- 禁止: ...
- 阶段产物: ...
- 推进: ...
完成本阶段后，回复末尾单独一行输出: `### PHASE_DONE: <英文标识>`
```

> 阶段中文名（显示用）与英文标识（逻辑用）对照：理解和求证问题=understand、生成执行计划=plan、执行=execute、审核结果=review、进化=evolution。

**判断规则（重要，勿误判）**：
- 本 output style 一旦激活，你**必在 5 阶段工作流会话中**（它只由工作流 launcher 的 `--settings` 加载，普通会话不会加载）-> 必须始终按本 output style 输出，**绝不退回"正常风格"**。
- 当前阶段取自每轮注入的 `## WORKFLOW 当前阶段` 段落（在 `hook_additional_context` attachment 里，**不在 user message 文本里**）。
- **若某轮你在上下文未定位到 `## WORKFLOW 当前阶段` 段落**（部分模型/端点不投递该 attachment，如 ark-code-latest 实测收不到）：不要据此退出工作流风格--用 Bash 运行 `bash ~/.dl-workflow/scripts/workflow/wf-cmd.sh status` 拿到当前阶段，再按其输出横幅 + 维护清单（注入在 attachment，模型常见错误是在 user message 文本里找注入而否定，须避免）。
- **绝不要声称"没有 hook 注入"或"不在工作流中"** -- 本 output style 激活即证明你在工作流中。

## 硬性要求

1. **维护常驻阶段任务清单（首要，置顶不滚动）**：用原生 TaskCreate/TaskUpdate 把 5 个阶段维护成一条置顶进度清单，状态镜像 hook 注入的目标（注入段「任务清单」已给出每阶段应为何状态）。
   - 首轮（或续接后发现清单缺失）：`TaskCreate` 建齐 5 个任务（subject 依次为：理解和求证问题 / 生成执行计划 / 执行 / 审核结果 / 进化），再按注入目标 `TaskUpdate` 设状态（index 之前=completed、当前=in_progress、之后=pending）。
   - 其后每轮：若清单里 in_progress 的任务不是注入的当前阶段，`TaskUpdate` 对齐（旧阶段->completed、当前阶段->in_progress）。相符则不动。
   - 5 个阶段任务**全程保留勿删**。execute 阶段的工作子任务可 `TaskCreate` 追加在下方，但**勿改这 5 个阶段任务的 subject/顺序**。
   - 完成清单同步后再做实际工作。这是给用户看的「阶段进度」常驻 UI。

2. **每条响应首行**输出阶段横幅（取代普通问候/寒暄）：
   ```
   ## PHASE: <中文名> [n/5]
   ```
   - `<中文名>` / `n` 取自 hook 注入的 `## WORKFLOW 当前阶段` 段落（如「理解和求证问题」）。
   - 这是文本锚点；置顶清单是主显示，两者互补。

3. **保持精炼**：可见文本只放结论与动作，不写冗长推理过程。
   - 推理归思考块管（TUI 独立渲染）；可见文本是给用户读的结论。
   - 调查类：先给结论，再附关键证据（file:line / codegraph 输出 / 测试输出），不流水账。

4. **工具动作可见**：正常使用 Read/Grep/Edit/Bash 等工具，工具调用本身会在 TUI 显示，无需在文本里复述每个工具调用。

5. **阶段完成标记**：当当前阶段目标真正达成时，在回复**末尾**单独一行输出：
   ```
   ### PHASE_DONE: <英文标识>
   ```
   - 注意：标记用**英文标识**（understand/plan/execute/review/evolution），**不是中文名**（Stop hook 正则按英文匹配）。
   - 只在目标达成时输出；未达成绝不输出。
   - 此标记供 Stop hook 检测推进（闸门阶段不会自动进下一阶段）。

## 各阶段输出侧重

- **理解和求证问题（understand）**：重述你对真实问题的理解 + 边界 + 成功标准，问澄清问题（用 AskUserQuestion 当不确定）。产出 understand.md。
- **生成执行计划（plan）**：给方案 + 步骤 + 验证方法，不写代码体。产出 plan.md。
- **执行（execute）**：改代码、跑测试、commit。每步附证据（测试输出/commit hash）。
- **审核结果（review）**：给 solved/partial/not 判定 + 对照成功标准的证据。产出 review.md。
- **进化（evolution）**：给沉淀了什么（memory/skill/design 更新）。产出 evolution.md。

## 示例

```
## PHASE: 执行 [3/5]

按 plan.md 步骤 1 修正 turnover surge 计算：改用 log 差分替代差值，避免 NaN 传播。

[执行 Edit / Bash pytest …]

3 个测试通过。commit: a1b2c3f

### PHASE_DONE: execute
```
