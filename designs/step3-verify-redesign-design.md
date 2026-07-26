# Step3「验真」第一性原理重设计：双向取证 + 质检裁决

> 状态：**已设计待实施**（2026-07-26 设计决议，未改 engine）
> 父文档：`node-step-orchestration-design.md`（子步骤编排机制）、`workflow-creation` SKILL.md §3.5（rubric 方法论）
> 用户硬约束：**禁用 tavily_search / WebSearch**（限制多、免费额度低）→ 外部源全部走零 key / 近零成本免费 API。

## 0. 动因：现版子3 的四类失效无防御

现版子3（`dl-flow-engine.py` understand:1 sub_step 3）是单步「搜证据」，第一性原理推导出的 7 种验真失效模式中 4 种无机制防御：

| # | 失效模式 | 现版 | 外部实证 |
|---|---|---|---|
| F1 | 主张不可检验 | 无防御 | CLAIMDECOMP（arXiv:2305.11859）：fact-checking pipeline 第一步永远是 claim decomposition → 可回答子问题 |
| F2 | 确认偏误（只搜支持证据） | **结果层允许证伪，过程层无强制** | ICLR 2026《Failing to Falsify》：11 个 LLM 默认倾向证实而非证伪；「考虑反例」干预 42%→56% |
| F3/F4 | 针对性失败 / 单源偏倚 | gate 只数「≥1 证据」 | FEVER 评分核心 = evidence-claim 对齐；AVeriTeC 要求 Q-A-Source 三元组多源交叉 |
| F5 | 证据不可追溯 | 无质检 | CoVe（Dhuliawala et al. 2023, arXiv:2309.11495）：factored 变体——验证问题独立作答、不见原答案，防抄自己的幻觉 |
| F6 | 内部盲区 | 仅一句「codegraph 查已有解法」 | 漏了更基本的用途：**证实/证伪问题在本仓库真实存在**（内部型问题的主证据源） |
| F7 | 单 agent 一遍过 | 无复核 | arXiv:2603.18740：对抗性框架 88% 骗过 Claude Code review agent——单视角会崩 |

## 1. 重设计：子3 拆为两子步骤（understand:1 由 5 步变 6 步）

```
子1 逼问定义 → 子2 拆解深挖 → 子3 双向取证 → 子4 质检裁决 → 子5 一句话陈述 → 子6 读回确认
```

**拆步粒度原则**（第一性原理）：按失效模式拆，不按工具拆。3a 的失效族 = 取证过程缺陷（偏倚/盲区）；3b 的失效族 = 判断质量缺陷（质检/裁决）。同族合并（省 judge 调用），异族拆开（judge 分步可判）。Step.ref 是声明式标签，engine 不限制一步内工具数量（现版子3 ref 已是 3 工具）。

### 子3 双向取证（kind="tool"，步内多工具编排）

- **purpose**（形式要件披露，模型可见）：
  1. **主张可检验化**：每个原子问题 → 可证伪 claim + 事先写死「什么证据证实 / 什么证据证伪」；不可检验的主张退回子2，不进入取证
  2. **证伪优先**：先构造反证查询（"X 已解决 / X 是反模式 / X 不成立"）并留痕，再搜支持证据（F2 实证干预）
  3. **五层源各 ≥1 次尝试留痕**（见 §2）；源层不可用显式标记「未取证 + 原因」是合法留痕
  4. **codegraph 新鲜度前置**：内部取证前先查索引新鲜度（`SELECT datetime(MAX(indexed_at)/1000,'unixepoch','+8 hours') FROM files;`），>72h 先 `codegraph sync`；新鲜度结果一并留痕
- **input**：`step2.problem_list`；**record**：True（每个工具调用一行 trace，q/a 数组）
- **gate**（质量判据黑盒）：凡声称外部证据必须带可追溯指针（真实 URL / 工具调用留痕）；**用模型训练记忆冒充外部证据 = 编造，判 block**；反证查询时序须先于支持查询

### 子4 质检裁决（kind="tool"，推理 + 条件触发红队子代理）

- **purpose**：
  1. **证据三关质检**：针对性（直接针对 claim 谓词，非行业常识）/ 独立性（来源互不转载）/ 可追溯（URL、file:line 可复查）；三关不全过的证据不计数
  2. **条件触发对抗复核**：仅当 verdict 决定大方向/大改动、或证据冲突时，起独立红队子代理尝试推翻初步结论——**独立上下文，只给证据不给结论**（CoVe factored 思想 + 2603.18740 教训）；触发条件写死，模型不得自定义「不需要复核」
  3. **四态结论合成**：证实 / 证伪 / 部分成立 / **证据不足**（借 FEVER Supported/Refuted/Conflicting/NotEnoughInfo；「证据不足」是合法结论，见 §3）+ 推理链 + 置信度
- **input**：`step3.traces`；**record**：True
- **gate**：三关质检记录完整；红队触发条件满足时必须见红队 trace；verdict 与证据间有推理链

## 2. 五层源（零 tavily/WebSearch 版，2026-07-26 本机实测）

| 层 | 工具 | 额度 | 实测 |
|---|---|---|---|
| ① 学术文献 | OpenAlex API（curl）+ arXiv API | 零 key，OpenAlex ~10 万次/天 | ✅ 通（267ms，299 万条索引） |
| ② 社区实战 | Stack Exchange API（quant.SE 对量化项目天配）+ HN Algolia API | 零 key；SE 匿名 300 次/天 | ✅ 通 |
| ③ 开源实现 | GitHub Search API（curl + `$GITHUB_TOKEN`） | 认证 5000 次/小时；未认证本机共享出口 IP 实测已被打爆 | ⚠️ 需配 PAT（§4） |
| ④ 定点网页 | WebFetch（内建） | 无外部额度 | 抓 ①②③ 发现的 URL 全文 |
| ⑤ 内部仓库 | codegraph + Read/Grep + Bash 查 parquet/SQLite | 本地无限 | 已有 |

- **调用方式**：①②③ 全 curl + jq，worktree 零安装。可选装 paper-search-mcp 封装学术层（非必需）。
- **丢掉的能力**：通用 web 全文搜索（新闻/散点博客的「不知 URL 在哪」式发现）。后门：自建 SearXNG / Brave API（2000 次/月免费）——不进默认路径，gate 不要求。
- **门控零影响**：gate 判「每层源尝试留痕 + 可追溯指针」，不绑定具体工具；换源只改 3a purpose 的源层清单。

## 3. 工具全挂时的降级语义（no silent fallback 铁律）

- 工具 ≠ 源层 ≠ 步骤结论。同层内有降级链（搜索 API → 定点 WebFetch → 显式标记未取证）。
- 「证据不足」是合法 verdict：trace 记录「尝试 → 不可用 → 标记」= 合法留痕，gate 结构 pass；子6 读回确认时用户看到「该维度未验证」，由用户裁决继续/等恢复/放弃（真值归用户，§3.5 三层分工）。
- 内部型问题（如 selection_date 断层）主证据在 ⑤ 内部层，外部全挂只降级完备性（reinvent 风险标证据不足），不颠覆问题存在性结论。
- **唯一的真失败**：模型拿训练记忆冒充外部证据。gate 黑盒判据专抓此项。

## 4. 环境配置操作守则（全局生效）

**唯一必配：GitHub PAT**（③ 层在共享 IP 下不可靠，需认证额度 5000 次/小时）。

1. **创建 PAT**（github.com → Settings → Developer settings → Personal access tokens）：
   - 推荐 Fine-grained token → Repository access 选 **Public Repositories (read-only)**（最小权限，只读公开数据）
   - 或 classic token **不勾任何 scope**（零 scope 对公开搜索即享认证额度）
2. **全局生效配置**（关键：dl launcher `exec claude`，env 由调用方 shell 继承——README「provider env」节已载明此链）：
   ```bash
   echo 'export GITHUB_TOKEN=<粘贴PAT>' >> ~/.bashrc
   exec bash   # 或重开终端
   ```
   `~/.bashrc` 一层 export，dl → launcher → claude → Bash tool 全链继承，无需写进任何 per-wf settings 或项目文件。
3. **验证**：`curl -s -H "Authorization: Bearer $GITHUB_TOKEN" https://api.github.com/rate_limit` → `core.limit == 5000`。
4. **安全纪律**：read-only public scope；**token 不写入任何 repo 文件 / evidence / design 文档**（只写 env 变量名）；泄露即 GitHub 后台 revoke。
5. **可选**：`SEMANTIC_SCHOLAR_API_KEY`（免费申请，学术层提额）同样走 `~/.bashrc` export；不配则用共享池，够用。

**实施落地时**：本节提升到 `README.md`「环境配置」节（README 只描述已实施行为，故现在不提升）。

## 5. 实施 checklist（改编排必过，症状 M + evidence schema 6 处）

1. `dl-flow-engine.py`：原子3 Step 替换为 2 个 Step（子5/6 顺移）
2. `hooks/workflow_phase.py` `_format_injection`：注入模板子步骤清单 + trace JSON 示例
3. `scripts/workflow/phase-rules.md`：understand:1 段完成标记 + 强制语义（system-prompt 通道，漏改必打架）
4. `output-styles/workflow.md`：清单 subject 契约（如需）
5. `skills/workflow-creation/SKILL.md`：症状 I/J 字段清单 + 本文指针
6. `tests/test_dl_flow_engine.py`：新 Step 定义测例 + 旧格式兼容回归

## 6. 外部实证出处（设计期调研留痕）

- ICLR 2026《Failing to Falsify: Evaluating and Mitigating Confirmation Bias in Language Models》— 确认偏误实测 + 反例干预有效
- CoVe：Dhuliawala et al. 2023《Chain-of-Verification Reduces Hallucination》arXiv:2309.11495 — factored 独立作答
- CLAIMDECOMP arXiv:2305.11859 — claim decomposition → yes/no 子问题
- AVeriTeC / FEVER — Q-A-Source 三元组、四态 verdict、evidence-claim 对齐评分
- arXiv:2603.18740 — 对抗框架 88% 骗过 Claude Code review agent；metadata redaction 去偏
- 现成参考实现：github.com/FuturizeRush/fact-check-skill（CoVe 协议 skill）；openags/paper-search-mcp（学术层封装）；github/github-mcp-server（repo 层备选）
