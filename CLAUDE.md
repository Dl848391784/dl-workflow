# CLAUDE.md - dl-workflow 并发开发规则（薄路由）

> 会话在 ~/.dl-workflow 启动时自动加载的入口守门员。只放并发开发铁律 + 真源指针，
> 不复制规则正文（守本项目「禁跨层重复」约定）。本仓库由 Claude Code 维护，
> 常有多会话并发作业（gate framing 泛化等）。

## 并发开发铁律：任何开发任务默认 worktree-per-session

**2026-08-05 用户决议**（真源：`designs/worktree-per-session-concurrency-design.md`）。
本仓库单工作树 + 多会话并发，分支指针不隔离工作目录——共享主树里 `git add` 整文件
会把并行会话的未提交 hunk 一起带走（2026-08-05 实证：`9fea4a1` 同一 commit 含
plan:3#1 + plan:3#2 两个 gate）。

开发任务（改 gate/hook/engine/测试/写新节点）执行顺序：

1. **建 worktree**：`git worktree add ~/.dl-workflow-wt-<主题> -b feat/<主题>`，本会话
   cwd 指向该目录（`~/.dl-workflow-wt-<主题>`）。**不直接在共享主树改源码。**
2. **复制重放 token**：`cp tests/replays/.token ~/.dl-workflow-wt-<主题>/tests/replays/`
   （gitignore 不随 checkout 带；缺 token 重放会断言失败）。
3. **开发 + 提交**：在 worktree 内完成、跑 pytest + ruff，commit 到 `feat/<主题>`。
4. **收口**：`cd ~/.dl-workflow && git merge feat/<主题> && git worktree remove ~/.dl-workflow-wt-<主题>`。

例外（可留共享主树）：只读/审计/诊断；本会话已独占的收口批（显式 `git add <清单>`，
**禁 `git add -A`**）。

**gate 已配套（v2.120 三分类，按被编辑文件的仓身份判定）**：dl 工作流 worktree
（`*/.claude/worktrees/`）与他仓 linked worktree 跳过；**本仓（主树+开发 worktree）
拦截**（恢复 2026-08-03「dl-workflow repo 本身要拦」决议，2026-08-05「任何 linked
worktree 跳过」泛化已收回）——codegraph db / audit 都走主树，开发 worktree 内改 .py
须先在 `~/.dl-workflow` 下跑一次 codegraph 查询解锁（audit 按 cd 前缀/会话 cwd 归
主树，无死锁）；design.md 写在当前工作树 `designs/`（随分支合并）。详见
`designs/gate-file-main-root-design.md`。

## 真源指针（命中触发才读）

| 文档 | 何时读 |
|---|---|
| `designs/worktree-per-session-concurrency-design.md` | worktree-per-session 设计全文（协议/gate 泛化/边界） |
| `skills/workflow-creation/references/collab.md` §3.9 | 并发协作全套规约（#5 禁 git add -A、#6/#13/#20 版本号取号、#25 撞号让位、#26 本协议） |
| `designs/plan*-gate-framing-design.md` | gate framing 反转逐节点设计（并发泛化期的产物） |
| `designs/workflow-system-design.md` | 工作流系统全景真源 |
