# 子代理 transcript 定位修复设计（v4 前台混合下 ingest-agent 62 轮 thrash 根治）

> 状态：已实现。触发 = 2026-08-13 `amplitude_annualized` sub3 实证：段工人里
> `append-trace --ingest-agent` 找不到子代理 transcript，模型花 62 轮逆向
> `dl_flow_engine.py` 源码 + mkdir/cp 手工兜底。

## 1. 根因

`_subagent_dir()`（供 `ingest_agent_report` 用）与 `_subagent_retry_stats()`（供
gate 裁决 retry 台账用）都用 `state.session_id` 拼子代理 transcript 目录：

```
~/.claude/projects/<enc-worktree>/<state.session_id>/subagents/agent-<task-id>.jsonl
```

但 v4 前台混合下，子代理由**段工人**（headless claude -p，独立 session）派发，
其 transcript 落在**段工人的 session 目录**下；而 `state.session_id` 恒指**前台
TUI 会话**——`dl_drive.py` 从未按 `headless-driver-arch-design.md` §2.6
「`session_id` 字段语义变为最近段 session」落地更新。

结果：`_subagent_dir()` 去查前台目录（`.../0630bf65.../subagents/`，不存在），
`--ingest-agent` 报「找不到子代理 transcript」，模型被迫 62 轮逆向源码 + 手工兜底
（sub3 的 92 轮里 62 轮是排障，占 67%）。

双处同根因：`_subagent_retry_stats()` 内联了同一段定位逻辑（v2.39 抽出
`_subagent_dir` 时漏改这处），在 driver 模式静默返 None，审计台账失效。

## 2. 修法

`_subagent_dir()` 不再只信 `state.session_id`，改为 glob 遍历项目目录下所有
session 子目录，返回**含 `subagents/` 的那个**：

```python
base = Path.home() / ".claude" / "projects" / enc
for d in sorted(base.iterdir()):
    sd = d / "subagents"
    if sd.is_dir():
        return sd
```

`_subagent_retry_stats()` 改为调 `_subagent_dir()`，去掉内联副本。

**取舍**：不碰 driver、不新增 state 字段、`state.session_id` 语义不变（v4 前台
resume + workflow_step_fence 的「前台 vs 段工人」判定都继续依赖
「state.session_id = 前台」这个不变量，不能为定位子代理而改它）。glob 遍历的
session 子目录数量通常 1-3（front + 少数段工人），开销可忽略；task-id 唯一，
不会误匹配陈旧 transcript。

## 3. 验证

- 新增 `TestSubagentRetryStats::test_finds_segment_worker_dir`：transcript 落
  `seg-sid`（非 state.session_id），`_subagent_retry_stats` 仍统计到。
- 新增 `TestIngestAgentReport::test_ingest_finds_segment_worker_transcript`：
  transcript 落 `seg-sid`，`ingest_agent_report` 仍找到并收录。
- 全量 988 tests 通过；ruff check/format 通过。
- 真机 dogfood：续跑 `amplitude_annualized`（sub4 红队也会走 `--ingest-agent`），
  确认子代理报告一次 ingest 成功、不再 62 轮排障。
