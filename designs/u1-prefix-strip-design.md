# understand:1 段前缀剥离置位设计——u2-residual-cost 机制向 u:1 泛化

> 日期：2026-08-18 · 分支 feat/u1-prefix-strip · 状态：实施中
> 上游：designs/u2-residual-cost-optimization-design.md（机制+探针台账+生产实证）
>      references/cost-optimization.md #23（判别问句/置位前置两核对）
> 触发 = 用户指令（2026-08-18）：「u:1 还有什么需要优化的…好的，做吧」——
> 审计（u1_overall_ab 当日真实台账）：u:1 每轮 5 段冷启动 ×~50k = 250k fresh
> 占全节点 fresh 63%，其中 ~27k/段是 #23 实证可裁前缀（项目上下文 11.9k +
> 工具 schema ~15k）。机制已在 u:2 生产验证（run-head -74.8%/零 block），
> 本设计 = 置位泛化，零新机制。

## 1. 置位前置两核对（#23 纪律）

### 1.1 逐步工具需求核对（u:1 七步）

| 步 | 工具需求 | 白名单覆盖 |
|---|---|---|
| 子1 逼问定义（prep 段） | Read/Bash | ✓ |
| 子2a 规划拆解 | Bash（append-trace/codebase 查询，探索预算计数）/Read | ✓ |
| 子2b 因果链挖掘 | Read/Bash（codegraph·grep）/Skill(causal-inference-root-cause) | ✓ |
| 子4 双向取证 | **Agent**（每原子一个取证子代理）/Bash（fetch-prompt·ingest）/Read/Skill | ✓（探针 J 实证 Agent 在白名单下可派发、子代理可跑 Bash 落盘） |
| 子5 质检裁决 | Bash（--ingest-redteam/--ingest-agent）/Read | ✓ |
| 子6 归一化陈述 | Skill(define-problem)/Edit 骨架/Bash 落库 | ✓ |
| 子7 读回确认 | P3-1 确认级无会话 | — |

`segment_tools=("Bash","Read","Edit","Skill","Agent")`。Write 不进单
（载荷 --scaffold+Edit，同 u:2）；AskUserQuestion 由 prep --disallowedTools 封。

### 1.2 CLAUDE.md/auto-memory 依赖核对

u:1 节点段 4 处 CLAUDE.md 引用逐一过：全部是**约束源/证据材料的 Read 指针**
（子1「仓库事实（CLAUDE.md/git config）只证明仓库由谁维护」、子2b「项目硬规则
（CLAUDE.md/PROJECT.md/MODULE.md 的 H 规则与模块边界——编程工作流独有的一等
约束源）」等）——模型按指针 **Read 定向读**（Read 工具保留），不依赖自动加载。
codegraph 命令模板 v2.38 起逐字在 purpose/fetch-prompt 内，不读 CLAUDE.md §3。
auto-memory：段 cwd=worktree → 按 cwd 编码的记忆目录本就为空（主项目 29KB
MEMORY.md 不在段前缀里），DISABLE_AUTO_MEMORY 是双保险。
H15 门禁不受影响：codegraph_gate 是 hook（探针 E 实证 DISABLE 对下 hooks 照常），
且 u:1 是 understand 阶段零源码编辑（S11 结构保证）。

### 1.3 红队预派发 worker 同步剥离

`_maybe_predispatch_redteam` spawn（u:1#5 段前预起，`--tools Read` 已是自带
白名单）加 spawn_env（从 node 取 overrides）——Read-only worker 零 CLAUDE.md
依赖，剥 11.9k/次。

## 2. 预期收益（每轮 u:1 运行，deepseek 口径，基线=u1_overall_ab 当日台账）

| 指标 | 基线 | 预期 | 机制 |
|---|---|---|---|
| 5 段首调 fresh 合计 | ~259k（44.5k-60.2k×5） | ~-135k（每段 -27k 级） | 前缀剥离 |
| 全节点逐调用 cr（87 调） | 6.20M | ~-2.3M（-37%，每调 -27k×0.1 价格轴） | 同上 |
| 全节点 fresh+cr/10 折算 | ~1.02M | **-35~40%** | — |
| 红队 worker 冷启动 | ~34k 级 | ~22k 级（-11.9k） | strip env |
| 墙钟 | 5 次冷启动 prefill | 各省 ~10-20s | prefill 缩量 |

**不做**（承接 #21 判据）：u:1 不上 MERGED_RUN_NODES——u:1 段链 08-17 实测
峰值 324k 破 250k 护栏回滚在先，步体重（17-30 调/段、段内上下文 70k+），
合并必撞 ctx 护栏。#3/#4 步体 cr 是真实工作产物，不动。

## 3. 影响面与验证

- `dl_flow_nodes.py`：understand:1 置位两字段（+注释记录核对结论）。
- `dl_drive.py`：`_maybe_predispatch_redteam` 加 spawn_env 参数 + 调用点
  传 overrides（~6 行）。run_session/MergedSession 管线零改动（复用）。
- 测试：TestSegmentSpawnOverrides 更新（u:1 期望值 + 「other nodes 零变化」
  排除清单改 u:1/u:2）+ 红队 worker env 断言。
- **live A/B（新实例 u1_strip_ab，drive 直跑 worktree @ac-deepseek1）**：
  种子 = u1_overall_ab evidence 裁至 u:1#1（五件套），从 u:1#2 起跑跑到
  u:1#7 confirm 自动收。验收口径（预登记，#18 混淆声明：各步步体轮数方差
  剔出对比面）：
  - **#2 首调 fresh ≤ ~20k**（对照 u1_overall_ab #2 首调 44,497）；
  - #4 段 Agent 派发正常（evidence 有蒸馏报告收录项 + discoveries/台账）；
  - #5 段红队收录正常（预派发 worker.json + 收录项，--ingest-redteam 路径）；
  - 全程零 block（node_attempts=0）、judge 全 pass、trace 质量目测不降；
  - amplitude 口径核对（4920.2% = 0.492 双×100 装配）。
