# ProblemContext 提示词 harness 化优化 —— 前期分析（ProblemContext 输入材料）

> 本文档是 dl 工作流实例 understand:1（ProblemContext）的**输入材料**，不是 design 定稿。
> 由 Claude Code 在 factor_ic_analyzer 主会话中产出（2026-07-26），用户审阅后拍板「P0+P1+P2 全做」。
> 正式 design 文档由 dl 实例 plan 阶段产出，本文档届时作废或被引用。

## 0. 用户原话（who/pain/why-now 出处）

> 「dl-workflow工作流中的ProblemContext阶段我们已经开发完了，其中最重要的就是和大模型的交互，喂给大模型的提示词质量决定了模型的回答质量，也就决定了工作流的质量，claude的harness工程是业界的标杆，可否仿照claude的harness工程优化我们的提示词？」

- who：dl-workflow 系统的唯一维护者（用户）
- pain：ProblemContext 阶段提示词质量直接决定工作流输出质量，当前提示词未经系统化 harness 工程审视
- why-now：ProblemContext（6 子步骤编排）刚开发完成（v2.8/v2.9），是优化提示词的自然时点
- 用户裁决记录：在主会话看完差距分析后，AskUserQuestion 三选一（全做/只做 P0/先出 design）选了「P0+P1+P2 全做（推荐）」

## 1. 实测数据（2026-07-26，可复查）

用真实 state（demo 工作流，understand:1 子步骤3）直接调 `_format_injection` 实测：

- **每轮注入 6,100 字符 ≈ 4,200 token**（中文按 ~0.7 token/字符估）
- 构成分解：
  - 6 个子步骤 purpose 全文：**~3,900 字符（64%）**——静态内容每轮逐字重发
  - evidence 格式块（3 行散文 + JSON 模板）：~900 字符
  - TaskList 镜像块（9 行状态 + 4 行指令散文）：~800 字符
  - 围栏提示 + 自查提示 + 强制行：~600 字符
  - 阶段头 + 四要素 + skill 行：~350 字符
- 按 demo 121320fe 实录 48 轮/次 ProblemContext：仅注入 ≈ **20 万新鲜输入 token/次**
- 「当前步」信号位置：子3 的 `【当前】` 标记在全文第 ~2,600 字符处（埋在列表中间）
- 强信号密度：单次注入内「禁止×4 / 必×6 / 强制×2 / 违规×2 / ⚠️ / 🚧」约 15 处

## 2. 差距分析（对照 Claude Code harness 工程实践）

Claude Code harness（Claude 自身 system prompt + 工具描述 + system-reminder 体系）可迁移的 6 条实践：

| # | Claude harness 实践 | 现状 | 证据 |
|---|---|---|---|
| ① | 静态规则与动态状态分通道：稳定规则进 system prompt（吃 prompt cache），每轮注入只带 delta | ❌ 最差项：64% 静态内容（6 步 purpose 全文）每轮重发 | `hooks/workflow_phase.py:295-303` |
| ② | 关键信息置顶（primacy）：当前任务放注入最前 | ❌ `【当前】` 埋在列表行尾 | 实测注入第 ~2,600 字符处 |
| ③ | 正反例替代元叙述：工具描述用 usage example，不用多段散文警告；执行文本不含维护者考古 | ❌ evidence 块 3 行散文警告；purpose 内嵌 `（demo fbdb6ebd 实录…）` `（实录：嵌套层 61 次 Read 全空）` 等考古 | `hooks/workflow_phase.py:336-355`；`dl_flow_engine.py:237,279-283` |
| ④ | 一条规则说一次；多通道必须同源生成 | ❌ 子步骤 purpose 有两份异文副本：engine（注入）vs phase-rules.md（system-prompt）——症状 M/F 记录的「两通道措辞漂移」病根的现存病灶 | `dl_flow_engine.py:165-351` vs `scripts/workflow/phase-rules.md:30-35` |
| ⑤ | 强调信号经济学：IMPORTANT/NEVER 用得越少越有效 | ⚠️ 单轮注入 ~15 处强信号，弱遵从模型习惯性忽略 | 实测注入全文 |
| ⑥ | 给 rationale 防合理化绕过 | ✅ 已做好（如「相对路径会写到 worktree，hook 读不到」），保留 | `hooks/workflow_phase.py:357` |

**已对齐、不要动的部分**：硬约束进 hook（S10-S15 围栏 = Claude permission 系统思路）；judge `--tools ""` 裁剪；质量判据黑盒防 Goodhart（§3.5 #2）；三层分工（机械/judge 结构/用户真值，§3.5 #1）。

## 3. 优化方案（用户已拍板全做）

### P0 注入瘦身：当前步全文 + 其余骨架（改 `hooks/workflow_phase.py:_format_injection`）

- 注入重排：「当前子步骤 N/6 + purpose 全文（①②③④ 拆 bullet 多行）」置顶；其余 5 步压缩为一行骨架链（`1.逼问定义 ✓ → 2.拆解深挖 ✓ → 3.双向取证【当前】→ …`）
- TaskList 镜像块只留状态行，删 4 行指令散文（指令已在 output-style/phase-rules，属跨通道重复）
- 预期：6,100 → ~2,600 字符（-57%）；当前任务置顶
- 风险检查：非当前步完整要求模型仍可从 phase-rules 获得（fallback 通道不丢信息）

### P1 双通道单源化（改 install.sh 或 launcher 加 render 步骤）

- phase-rules.md 的 understand:1 段改为**从 engine sub_steps 渲染生成**（engine 已自称「声明式，单源在 engine」，此条把声明兑现）
- 开放设计问题（plan 阶段定）：render 时机 = install.sh（改 engine 后须跑 install）vs dl-launch.sh 启动时（永远新鲜，无 install 依赖）——倾向 launcher 启动时渲染
- 收益：消灭两份手维护异文（症状 M/F 漂移类故障的根治）

### P2 正反例 + 元叙述清除（改 engine purpose/gate 文本 + 注入 evidence 块）

- evidence 块 3 行散文 → `✓ 正例` / `✗ 反例（必 block）` 各一条 JSON
- purpose/gate 字符串里的 `（demo xxx 实录…）` 考古移到 engine 代码注释（**规则留下，考古走**）
- gate rubric 同步瘦身：judge 输入随 rubric 线性增长（SKILL.md caveat 已记：子1 ~3k → 子5 ~19k），瘦 rubric 直接降 judge 成本
- 强信号合并去重：每条硬规则每通道只说一次

## 4. 约束与红线（实施时必须守）

1. **Goodhart 分层不动**：质量判据（可观察/非编造/非空泛）仍只在 gate 黑盒，P2 瘦身不得把判据泄进 purpose
2. **重放回归验证**：gate rubric 改动后，用真实历史案例（demo 121320fe / fbdb6ebd 的 evidence）重放，新旧判决必须一致——沿用 tests TestRunJudgeHarnessTrim 套路
3. **self-hosting 生效点**：hooks/engine/phase-rules 都是 settings.json 直接引用主 checkout 源，worktree 内改动**本会话不生效**，merge wf 分支 → main 后才生效——实施期会话全程跑旧引擎，无自举风险；但验证（冒烟注入/新 demo 实例）必须在 merge 后做
4. **症状 M checklist**：改编排文案必过 6 处同步清单（engine / workflow_phase 注入 / workflow_advance / phase-rules / output-style / 冒烟）
5. **测试**：`~/.dl-workflow/tests/` pytest 全绿；_format_injection 结构变化需更新对应测试 fixture

## 5. 验证标准（建议，plan 阶段细化）

- 注入字符数：子步骤中途实测 ≤ 3,000 字符（基线 6,100）
- phase-rules.md understand:1 段与 engine purpose 逐字一致（render 产物）
- 重放回归：≥2 个真实历史案例新旧判决一致
- pytest 全绿 + ruff clean
- （可选）新 demo 实例端到端跑一遍 ProblemContext，对比 block 率无异常升高
