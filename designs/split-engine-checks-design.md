# dl_flow_engine 拆分：_check_* 家族抽离（design）

> 2026-08-27。触发：用户问「dl-workflow 脚本要不要拆分？大不大？」，分析后拍板执行第一刀。
> 范围：仅 `_check_*` 机械预检家族 + 其依赖的共用 helper；handoff/pack、trace ingest、CLI 尾段留后续刀。

## 现状问题

`dl_flow_engine.py` 7842 行 / ~180 顶层函数。AST 分析显示其中 v2.27 机械预检节
（`_check_*` 判定 + 注册表 + 配套常量，约 1900 行 / 56 def + 67 模块级常量）签名高度
统一（`(qa, *_ctx) -> str | None`）、几乎不碰状态机——是最大、最均匀、风险最低的拆分块。

## 拆分方案（三模块）

| 模块 | 内容 | 行数（拆分后） |
|---|---|---|
| `dl_flow_common.py`（新） | checks 与 engine 双向共用的 state/trace 低层 helper：`state_path` / `load_state` / `normalize_state` / `_evidence_path` / `read_evidence` / `_node_entered_at` / `_iter_trace_segments` / `read_evidence_for_step` | ~180 |
| `dl_flow_checks.py`（新） | v2.27 节整段：`_NOUN_L` 起至 `_MECH_QA_CHECKS` 止（含 4 注册表 dict、`_ID_RE`、`_NOUN_SKIP_EXTS`、`payload_format_hint` 等） | ~2500 |
| `dl_flow_engine.py` | 编排内核 + re-export shim | ~5300 |

依赖方向：`checks -> common -> nodes`，`engine -> {checks, common, nodes}`，无环。

## 边界判定依据（AST 双向依赖分析，非肉眼）

- **region -> engine**：仅 6 helper（上表 common 后 6 个）+ 2 常量（`_ID_RE`、`_NOUN_SKIP_EXTS`，随 region 搬走）。
- **engine -> region**：4 注册表（`_MECH_QA_CHECKS` 等，`append_trace` 用）+ `_implementation_nouns` / `_placeholder_hit` / `_source_step_index` / `_step_trace_ids`（`append_trace`）+ `_load_atomic_questions`（`fetch_prompt`）+ `payload_format_hint`（hooks/workflow_phase.py 经 `engine.*` 属性访问）——全部经 engine re-export 保持访问面。
- **留在 engine**：`_NOUN_L`/`_NOUN_R`（仅 `append_trace` 6685 行用）、`_MD_HEADER_RE`/`_MD_ITEM_FIELDS`（仅 `_parse_trace_md` 用）。

## 兼容约定

- tests/hooks/scripts 全部走 `eng.<name>` 属性访问（138 处），engine 显式 re-export
  全部搬迁名；未在 engine 体内使用的名加 `# noqa: F401` + 缘由注释（沿 `dl_flow_nodes`
  re-export 既有风格）。
- 零行为变化：搬迁为整段文本移动，函数体一字不改。

## 当前改动范围（门禁留痕）

- 新增 `dl_flow_common.py`、`dl_flow_checks.py`
- `dl_flow_engine.py`：删已搬区段 + 插两个 re-export import 块 + 3 个 nodes 名补 noqa
  （`_CHANGE_SPEC_RULE` / `_ROOT_CAUSE_LINE_RULE` / `current_node_id`，原被 region 使用，
  拆后 engine 体不再直接用，保留 re-export）

## 验证

`pytest tests/ -x -q` 全绿 + `ruff check` 三文件零错误 + `py_compile` + re-export 访问面断言脚本。
