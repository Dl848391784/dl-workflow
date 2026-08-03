# gate/audit hook 会话隔离修复设计（v2.69，2026-08-03）

> 缺陷：design_gate / design_audit / codegraph_gate / codegraph_audit 四个
> hook 的会话标识从环境变量 `CLAUDE_SESSION_ID` 取，该变量在 hook 环境里
> **从未被设置** → 所有会话全部塌缩进 `_fallback.log` → 门禁的「本会话」
> 语义失效（跨会话共享留痕）。v2.68 设计前的用户质询「不写 design.md 就
> 实施么」牵出本缺陷。

## 1. 问题

**实证**（2026-08-03 会话）：
- `~/.dl-workflow/.claude/.design_audit/` 与主仓 `.claude/.design_audit/`、
  `.claude/.cg_audit/` 里几乎只有 `_fallback.log`。
- v2.67 修复（本会话）编辑第 2 个源码文件 `workflow_step_fence.py` 时
  （13:14 UTC），design_gate 在共享 `_fallback.log` 里读到**上午会话**
  10:46 的 DESIGN 记录（design-first-gate-design.md）→ 误判「本会话已写
  design.md」→ 放行。design-first 门禁实际未生效。
- H15 codegraph_gate 同理：`_fallback.log` 里任何历史 codegraph 查询记录
  解锁之后所有会话的源码编辑。

**根因**：四个 hook 的 `_session_id()` 只读
`os.environ["CLAUDE_SESSION_ID"]`——Claude Code 并不向 hook 进程注入该
变量。而 hook stdin 的 JSON payload **自带 `session_id` 字段**（hooks 规范
公共字段，另有 `transcript_path` 其文件名 stem 即 session id），四个 hook
都解析了 payload 却没用它。

测试盲区：现有测试用 `_run(..., session_id)` 显式注入 `CLAUDE_SESSION_ID`
env（test_design_gate.py 头注释「session_id 取自 CLAUDE_SESSION_ID env；
tmp_path 每次独立 -> 会话隔离」）——测试环境与现实环境系统性不一致，
缺陷因此不可见（测试替身失真）。

## 2. 方案

四个 hook 的 `_session_id()` 统一改为从 payload 解析，优先级：

1. `payload["session_id"]`（hooks 规范公共字段，真源）；
2. `Path(payload["transcript_path"]).stem`（transcript 文件名=session id，
   双保险——payload 字段名漂移时仍正确）；
3. env `CLAUDE_SESSION_ID`（向后兼容：现有测试/手工调用注入 env 的场景
   不破坏）；
4. `"_fallback"`（皆无时的宁纵勿枉——维持现状语义，不新引入阻断面）。

实现形态：`_session_id(payload: dict) -> str`，各 hook main() 传入已解析的
payload。纯函数便于单测。

**迁移**：旧 `_fallback.log` 保留不动（历史审计）；修复后新会话各自建
`<sid>.log`。无副作用面：
- 工作流 worktree 会话本来就跳过两 gate（不受 session 解析影响）；
- 本修复会话自身：v2.68 的 DESIGN 已在 `_fallback.log`，修复期间旧 gate
  代码放行全部 hook 编辑；修复生效后本会话不再改源码文件（只改豁免的
  test_*.py），无自锁；
- 其他在飞会话（tail_volume worktree）跳过 gate，无影响。

**修后行为变化（预期收紧）**：每个新会话首次改第 2 个不同源码文件前
必须当真写过 designs/*.md——这正是门禁设计语义，v2.67 式漏网不再可能。

## 3. 改动面

| 文件 | 改动 |
|---|---|
| `hooks/design_gate.py` | `_session_id(payload)` 三源解析；`_session_edits` 透传 |
| `hooks/design_audit.py` | 同上（写侧） |
| `hooks/codegraph_gate.py` | 同上；`_has_query_this_session` 透传 |
| `hooks/codegraph_audit.py` | 同上（写侧） |
| `tests/test_design_gate.py` | payload session_id 用例（不设 env）：gate 阻断/放行按 payload sid 隔离；两不同 sid 互不共享 |
| `tests/test_codegraph_gate.py` | 同上（payload sid 留痕解锁仅对本 sid 生效） |

## 4. 验证

1. TDD：新用例先红（不设 env、payload 带 session_id 时现状落 _fallback
   → 跨「会话」串味，断言失败）再绿。
2. 现有测试全绿（env 注入路径向后兼容）。
3. 全量套件。
4. 真机冒烟：修复后下一次真实 hook 调用在 `.design_audit/` 落非
   `_fallback` 的 `<sid>.log`（观察目录即验）。
5. commit。

## 5. 非目标

- 不清理/归档旧 `_fallback.log`（历史留痕无属主但无害；新逻辑不读它）。
- 不改门禁判定规则本身（阻断条件/白名单/宁纵勿枉方向不动）。
- workflow 系列 hook（workflow_phase 等）不经 `_session_id` 记账
  （用 state.json 钉 session），不在本面。
