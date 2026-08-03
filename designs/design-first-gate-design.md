# design-first 门禁设计（用户级跨项目，2026-08-03）

> 动机：v2.64-66 修复 dl-workflow 时跳过「确认根因方案 → design.md → 动手」
> 流程（连改 dl_flow_engine/nodes/fence 多个 .py 无 design.md、未确认方案）。
> 用户指出后按 [[troubleshoot-fix-flow]] 补记流程，并要求配机械闸门。
> 本文档本身即门禁触发后补写的解锁产物（dogfooding）。

## 1. 问题：流程规则是 prompt 级软约束，模型会跳过

superpowers/CLAUDE.md 的「systematic-debugging 优先 / 先确认 / H8 design-first」
全是文本注入，无机械强制。实证不对称：有闸门的规则（append-trace 格式、
S15 围栏、codegraph H15）被遵守，纯文本的流程规则被跳过。`check_design_first.py`
仅 CI 环境跑（`if not pr_body: 跳过`）、未注册为 hook，交互会话零强制。
弱模型优先原则：prompt 软、围栏硬——对 Claude 自身行为同样成立。

## 2. 方案：design-first 门禁（镜像 H15 codegraph gate 已验证模式）

**机制**（audit + gate 对，会话 audit log）：
- `design_audit.py`（PostToolUse Edit|Write|MultiEdit）：留痕本会话编辑的 .py
  源码 + 写过的 `designs/*.md` 到 `<repo>/.claude/.design_audit/<sid>.log`。
- `design_gate.py`（PreToolUse Edit|Write|MultiEdit）：本会话改**第 2 个及以上
  不同 .py 源码文件**且未写 `designs/*.md` → exit 2 阻断指路（确认方案 →
  写 design.md → 动手）。

**放行**：本会话已写 design.md / 第 1 个源码文件 / 同一文件迭代。
**豁免**（沿用 H15 白名单）：非 .py、test_*.py、新建文件、scripts/check_*.py、
designs/ 自身。

**触发点 = H8 原义**：2+ 文件才要 design-first；单文件小修不拦（design 过度）。

## 3. 关键设计决策

**① 项目根从被编辑文件反查（不是 cwd）**：design.md 应落在文件所属仓的
designs/。从主会话改 dl-workflow 文件时 cwd 是主项目，用 cwd 会错查主项目
designs/。改 `_resolve_file_project_root(file_path)`（git -C <file_dir>
rev-parse --show-toplevel）。audit 与 gate 同一 project_root，避免串号。

**② 工作流会话（.claude/worktrees/<name>）跳过**（用户决议：codegraph 和
design_gate 对 worktree 都不拦）：工作流有自己的 design 流程（plan:1
render-artifact 产 design.md + 门控），且其 design.md 由脚本写（非 Edit/Write
工具），audit 看不到会误拦 execute 阶段。codegraph_gate 同步补 worktree 跳过
（此前它对 worktree 也 exit 2 拦，worktree 内 .codegraph db 不存在=无法解锁
=死锁隐患；工作流的 codegraph 纪律由 plan:1 新鲜度前置自理，门禁在此冗余）。

**③ dl-workflow repo 本身要拦**（用户决议）：dl-workflow 后续会编排改
worktree 的流程，多文件改动须 design-first。design.md 落 `~/.dl-workflow/designs/`。

## 4. 验证

- pytest tests/test_design_gate.py 9 例：白名单跳过（非 .py/新建/test/worktree）
  / 放行（第 1 文件、同文件迭代、写 design 后）/ 阻断（第 2 文件无 design）
  / audit 分类留痕（SRC/DESIGN/非源码不留痕）。
- 冒烟：主会话拦、worktree 会话跳过、写 design.md 解锁。
- dogfooding：本次开发中门禁真实触发（改第 3 个源码文件无 design.md 被拦），
  补写本文档解锁——证明机制有效。

## 5. 注册

install.sh `DLWF_HOOKS` 用户级注册（PreToolUse Edit|Write|MultiEdit →
design_gate；PostToolUse Edit|Write|MultiEdit → design_audit），hooks 不 copy
直引 `~/.dl-workflow/hooks/*.py`。会话启动时加载，新会话生效。
