# dl_flow_engine 拆分第二轮：handoff/pack + trace ingest 抽离（design）

> 2026-08-27。承接 [[split-engine-checks-design]]（第一刀已 merge，engine 7842->5350）。
> 目标：engine 剩余两块既定接缝抽离；CLI 尾段经依赖数据评估后**决议保留在 engine**。

## 本轮边界（AST 双向依赖分析，非肉眼）

### 抽 `dl_flow_handoff.py`（19 名，~450 行）
- 区段：`HANDOFF_PROMPT_T1/T2`（1082-1083）+ 1586-2035（`estimate_context_tokens` /
  `handoff_tier` / handoff 事件记录 / `write_handoff_prompt` / `write_handoff_resolution` /
  `_PACK_*` 常量 / `segment_spawn_overrides` / `_truncate` / `_slim_trace_for_pack` / `handoff_pack`）。
- 依赖：engine-core 仅 `_now`；其余全走 common/nodes。无环。

### 抽 `dl_flow_trace.py`（18 名，~1080 行）
- 区段 3486-4623：`_TRACE_STRUCT_FIELDS` / `_MD_HEADER_RE` / `_MD_ITEM_FIELDS` / `_MdErr` /
  `_parse_trace_md` / `_subagent_dir` / `_insert_report_item` / `_extract_predispatch_report` /
  `pid_alive` / `ingest_agent_report` / `ingest_redteam_report` / `_FIELD_SCAFFOLD_HINTS` /
  `scaffold_payload` / `append_trace` / `redteam_prompt` / `fetch_prompt` / `_curl_probe` /
  `run_fetch_preflight`。
- 依赖：engine-core 4 名（`_now` / `trace_payload_path` / `sub_step_at` / `sub_step_has_trace`）
  ——闭包验证仅依赖 common/nodes，**下沉 common**；checks 注册表经 `dl_flow_checks` 直接 import。

### CLI 尾段（4629-5346，~720 行）——决议：不拆
依赖数据：cli 触达 13 个编排内核函数（`advance_state`/`reset_state`/`release_subgate`/
`render_*` 等）+ 7 个 trace 函数；tests 大量 `eng.main([...])` 调用。拆出则 engine 需
re-export cli 名 -> cli 又需 import engine 内核 -> 环，只能靠 PEP 562 `__getattr__` 魔法
或 13 处惰性 import 解开——对本仓「弱模型读得懂」优先级是净负。cli 是内核的薄命令面，
留 engine 内聚合理。

## common 增量（本轮下沉 4 名）

`_now` / `trace_payload_path` / `sub_step_at` / `sub_step_has_trace`（闭包仅依赖
common/nodes 已有名）。common 由 8 -> 12 函数。

## 兼容约定与验证

同第一刀：engine 显式 re-export 全部搬迁名（`# noqa: F401` + 缘由注释，未用名标注）；
全部消费方走 `import dl_flow_engine as engine` 属性访问，零改动。
验证：`pytest tests/ -q`（1278 基线）+ `ruff check/format` + 搬迁前后 AST 逐字相等核对。

## 当前改动范围（门禁留痕）

- 新增 `dl_flow_handoff.py`、`dl_flow_trace.py`
- `dl_flow_common.py`：+4 函数（docstring 同步）
- `dl_flow_engine.py`：删两区段 + re-export import 块
