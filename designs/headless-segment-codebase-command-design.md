# headless 段工人代码搜索通道文案一致性

> 日期：2026-08-14 · 分支 main（dl-workflow） · 状态：已裁决，立即实施
> 上游：本次 `amplitude_annualized` understand:1 子3 审计发现（drive_deny_readonly 指路失配）

## 1. 根因

`understand:1` 子2/子3 配置 `deny_readonly=('grep','rg')`，意图逼代码搜索走 `dl codebase`（结构化 codegraph 包装 + discoveries 台账去重）。但：

- `dl` 是 `.bashrc` 里的 shell function，**非交互 shell 不加载**；
- headless 段工人（`dl_drive.py --segment`）运行在非交互 shell 中，裸 `dl codebase` 会 "needs approval" 并被拒；
- 已放行且可跑的等价命令是 `bash ~/.dl-workflow/scripts/workflow/dl-cmd.sh codebase ...`（匹配 `settings.drive.json` 中 `Bash(bash ~/.dl-workflow/scripts/workflow/dl-cmd.sh:*)`）。

结果：模型在段工人里既被禁 grep，又被指的替代命令跑不通，只能自己发现裸 `codegraph` CLI，白烧 ~9 轮。

## 2. 改动范围

- `hooks/workflow_step_fence.py`：已提交（a792403），`drive_deny_readonly` 文案指向 `bash dl-cmd.sh codebase ...`。
- `dl_flow_nodes.py`：`_CODE_ARCH_ROUTE` 节点规则模板同步改为可跑命令，消除「节点规则教 broken 写法、围栏再兜底」的二次摩擦。
- 测试 pin：
  - `tests/test_workflow_step_fence.py` 已同步；
  - `tests/test_dl_drive.py::test_node_rules_has_arch_route` 需同步断言。

## 3. 不做的范围

- 不扩权限 allowlist：`bash dl-cmd.sh codebase` 已在 `settings.drive.json` 放行，无需新增条目；裸 `dl:*)` 过宽且不能解决 shell function 未加载问题，故不加。
- 不改前台行为：`bash dl-cmd.sh codebase` 在前台 TUI 会话同样可跑，只是文案变长，无功能性回退。

## 4. 验证

- `pytest tests/test_workflow_step_fence.py tests/test_dl_drive.py` 通过；
- 全量 `pytest tests/` 通过。

## 5. 用户裁决

用户原话：「需要」。按本设计实施。
