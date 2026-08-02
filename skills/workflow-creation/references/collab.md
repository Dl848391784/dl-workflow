# 多会话同仓协作

> workflow-creation skill 按需参考（自 SKILL.md §1.4+§3.9 整体迁出，节号原样保留以兼容「§3.5 #9」式交叉引用）。
> 只在 SKILL.md 路由表命中时阅读。

### 1.4 多会话并发维护（单人 ≠ 单会话，2026-07-28 实测）

系统文档写「单人维护直接在 main 开发」，但**单人 ≠ 单会话**：两个 Claude 会话可在同一 `~/.dl-workflow` 并行作业。当日实测：一方 `git reset --hard`/restore 把另一方**未提交**的改动抹掉（两文件全失），残留文件与新状态不一致（tests 期待新节点而节点树被回退，46 failed）。

- **防御**：未提交工作 = 丢失面 + hunk 混合冲突源。**完成一个逻辑单元就 commit**（frequent small commits 对共享 repo 是防撞保护，不只是整洁）；知道另一会话在同 repo 作业时更要即改即提——攒到「划分 commit」才提就是给冲突留窗口。
- **诊断**（发现改动消失，别急着重做）：`git status`（文件还在不在 M 列表）→ `git log`（**HEAD 前进 = 对方已提交你的工作，转验收；HEAD 不动 = 被回退**）→ `git reflog`（reset 事件留痕）→ grep 文件内容确认。关键分叉：被提交（好消息）vs 被回退（需裁决）。
- **恢复纪律**：先 surface 给用户——回退可能是对方有意，盲目重做会制造第二轮冲突；若对方已提交，**全量验收代替重做**（pytest 全绿 + ruff + grep 关键标识 + install copy diff + render/注入冒烟）。

（并发进行中的写者侧协议——早期信号/失败归因/commit 拆分重建法/时序错位——见 §3.9；本节是被回退侧的恢复视角。）


---

## 3.9 多会话同仓协作（并发编辑信号 / commit 拆分 / 时序验证）

（被回退侧的恢复协议——诊断分叉「被提交 vs 被回退」+ 全量验收代替重做——见 §1.4；本节是并发进行中的写者侧视角。）

2026-07-28 实例：本会话做 understand:3/4 编程域修订时，另一会话同仓做 plan:1 编排——两批改动交织进同一文件（dl_flow_nodes.py / SKILL.md），完整走完「发现并发 → 分工 → 拆分提交」全流程，沉淀四步：

1. **另一写者的早期信号，任一出现先停手问用户**：Edit 工具提示「file modified on disk since you last read it」；两次 `git status` 之间文件列表/mtime 变化；目标文件 mtime 就是当前时刻。**绝不双写同一文件**——当日 test 文件差点两会话同时编辑。
2. **大批量测试失败的归因法**：先 `git stash` 跑基线——基线绿 = 失败全来自工作区改动而非你的编辑；再把 FAILED 清单归并到单一根因（重编号/拆分类 breaking 改动 = N 失败一根因，逐个修是误诊）。归因后才决定：自己的失败修，别人的失败留。
3. **同一文件交织两批改动时的 commit 拆分（重建法）**：本环境无交互式 `git add -p`，替代 5 步——①两批终态文件 cp 到 /tmp；②`git checkout HEAD -- <混合文件>`；③重放己方编辑（Edit 工具按已知 old/new 逐处，重放后 `diff` 对照终态，**只在对方区域有 hunk** 才算重放正确）；④跑「HEAD 版测试 + 己方改动」验证绿 → 提交己方——**己方改动含文案/输出文本变更时，先 `grep` 对方未提交的测试文件是否断言该文本**（2026-07-28 state-reset 实例：门栏提示文案改词，grep 确认 test_workflow_advance/phase 零断言才敢提中间态；有断言则中间态必红，需先协调分工而非强提）；⑤cp 回终态 → 全量验证 → 提交对方。
4. **提交时序的验证错觉**：先提交的 engine 改动配「来自未来的已迁移测试」跑会红一片——这不是回归，是测试与代码的时序错位；正确验证 = `git checkout HEAD -- tests/` 跑绿再恢复（③的验证步）。**别把时序错位当 bug 修**。
5. **`git add -A` 是并发下的席卷动作**（2026-07-30 实例）：会话 A 的 `_INTERACTIVE_CHUNKING_RULE` 改动未暂存过夜，会话 B 提交自己批次时 `git add -A` 把它席卷进 B 的 commit（377e898，message 未提）——没丢（对方后补文档 commit），但归属和 message 都失真。规则：**dl-workflow 仓改完立即 commit，不留未暂存改动过夜**；提交前 `git status --short` 逐文件确认全是自己这批（本环境无 `git add -p`，发现夹带按 #3 重建法拆）；并发活跃期优先 `git add <明确文件清单>` 不用 `-A`。
6. **编排版本号 commit 前先查占用**（2026-07-31 实例）：v2.xx 序号无中央分配——本会话按 memory 记的 v2.31 往下排，实际另一会话的产物机械门（7097c48）已先占 v2.31，被迫补一个改名 commit（ba3485b）。提交前 `grep -rn "v2\.<n>"` 全仓 + `git log --oneline -5` 查最新序号。
7. **format/lint 漂移归因：先确认归属，独立批收口**（2026-08-02 v2.41 实例）：`ruff format --check` 报 5 文件漂移但都不在本次改动行——根因 = **committed 代码 + ruff 版本口径变化**（旧版本格式化的行被新版规则重排），不是并发污染也不是你的编辑。处理纪律：①先 `ruff format --diff <文件>` 看 hunk 归属——落在自己改动行 = 自己新代码没过 format，随本批修；全是别人/历史行 = pre-existing 漂移；②pre-existing 漂移**不混入功能 commit**（守 #3 批次纯净），独立 style commit 收口 + message 声明非语义改动；③format 跑完**必复跑 pytest 再 commit**（症状 M checklist #7 同纪律）——且 format 可能顺带带出你刚写的新行（本次 test_workflow_phase.py 一行，属①随批修）。

