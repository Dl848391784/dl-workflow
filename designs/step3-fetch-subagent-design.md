# 子3 外部取证子代理化设计（v2.38，2026-08-01）

> 关联：`step3-verify-redesign-design.md`（子3/子4 拆步母设计）。本文是子3 执行面的第二次重设计：拆步（取证过程 vs 判断质量）不变，**取证的执行位置**从主会话移到子代理。

## 1. 动机（双因）

**A. 主会话上下文污染**：tail_volume_acceleration_annualized u:1 审计——子3 是主会话工具密度大户（46 msgs / 26 tool calls / 6.2M cache read），curl 原始输出全堆主上下文。主会话成本公式 = 轮次数 × 上下文长度，外部原始输出是长度大头。

**B. 外部源失败率 ~40%**（用户观察 + 当晚实证逐层诊断）：

| 通道 | 当晚 | 根因 | 修复（逐字进 fetch-prompt 命令模板，当日已验证） |
|---|---|---|---|
| arXiv | 空 ×3 | `http://` + 无 UA 静默空 | `https://export.arxiv.org/api/query` + `-A "Mozilla/5.0 (research)"` |
| GitHub code search | 401 ×2 | 模型没带认证头（env 有 GITHUB_TOKEN） | `-H "Authorization: Bearer $GITHUB_TOKEN"` |
| WebFetch | 全挂 | claude.ai 域验证被本网络拦，环境性 | 弃用；定点网页 curl `-m 25` 直抓；SE 页面 403 用 API `filter=withbody` 替 |
| SE API | ✓ 偶超时 | 网络抖动 | `-m 25` + 失败重试一次 |
| python one-liner | 语法错 ×2 | 模型手写 | jq 提取片段内置 |

**通道决策（用户 2026-08-01 复核）**：修 curl 模板，维持 2026-07-26「禁 tavily/WebSearch（额度低）」硬约束。

## 2. 设计（对齐 redteam-prompt 先例：证据+纪律归脚本，Agent 调用归模型）

- `engine.fetch_prompt()` + CLI `fetch-prompt`：读子1-2 最新 trace（ProblemContext 限定）组装子代理 prompt = 纪律（单层/不写 evidence/不裁决/禁 WebFetch/禁探查凭证/失败标「未取证+原因」）+ 命令模板（上表逐字）+ 返回契约（每原子 ≤120 行：反证查询（先）→支持证据（后）→五层状态表）+ claim 补充区（主会话只补此区，禁手拼骨架）。
- 子3 purpose 改为编排：claim 可检验化（主会话）→ fetch-prompt 派发每原子一个 Agent 并行 → 蒸馏报告**原文收录** → 内部仓库层主会话自查（codegraph 新鲜度前置）。
- `fence_allow: ("Bash","WebFetch") → ("Bash","Agent")`；`_s15_bash_orchestration` 白名单加 `fetch-prompt`。子代理进程内 curl 经同一 PreToolUse 围栏、子3 声明 Bash 故放行（围栏不区分主/子会话，已核实）。
- **返回契约即蒸馏边界**：原始 curl 输出留在子代理上下文（每原子独立互不污染），主会话只收 ≤120 行/原子。

## 3. 关键实证：judge 重放逮住形式要件漏洞（改判据必跑真实载荷重放，又一次兑现）

落地验证时对今晚 att2（旧形态、无子代理报告）过新 gate 重放 → **judge 判 PASS**——judge 把内容丰富的留痕当实质满足，「报告原文收录」形式要件被裁量放过，子代理编排可被绕过（主上下文卸载落空）。处置：新增 `mech_checks=("fetch_report_recorded",)`——append-trace 机械核验每原子一个标题含「蒸馏报告」的 q 项（标题=承诺装置+结构），judge 只判收录真实性与内容质量。新形态（报告收录）重放 → PASS。

## 4. 边界与已知限制

- 机械核验只保证「报告项存在」，不保证报告真来自子代理（标题可被冒充）——真实性由 judge 判内容（提及/转述判 block）+ fence 经济激励（直连 curl 自烧上下文）兜底。
- 主会话保留 Bash（内部仓库层）：模型理论上可直连外部源绕开子代理——自损型违规（烧自己上下文），不硬堵。
- 命令模板按本机网络环境验证（2026-08-01）；环境变化（代理策略）后模板需再诊断。
- 在跑工作流 phase-rules 是 launch 快照，新机制对下一个 dl 实例生效。

## 5. 验证

- 509 tests 全绿（新增 TestFetchPrompt×3 + TestFetchReportRecorded×2；9 个旧 pinning 测试改 pin 新行为；TestAppendTrace fixture 默认步 3→4）。
- judge 重放：旧形态（无报告项）→ 机械拒（judge 不再发生）；新形态 → PASS。
- 模板命令冒烟：arXiv / GitHub 认证 / SE withbody 三条本机实测通过。
