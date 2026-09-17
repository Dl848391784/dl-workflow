# 系统健康榜中文名对齐（detail 审计区同规）

> 2026-09-17。改动范围：`dl_dashboard/health.py` + `dl_dashboard/static/health.js`（+测试 `tests/test_dl_dashboard_health.py`）。

## 背景

用户裁决（同日 detail 审计区 dac9340 的延伸）：dashboard 任何榜单禁裸 `understand:1#1`。detail 页审计区已对齐 scanner `step_labels`；`/health` 系统健康页是跨实例聚合（无单实例 scanner 上下文），映射须在后端做。

## 方案

- `health.py`：gate 榜/dispute 榜行加 `label`（`节点label·子步short`），节点成本榜行加 `label`（节点中文名）；映射单源 = `dl_flow_engine.get_node().label` / `sub_step_at().short`（与 scanner `step_labels` 同源 `dl_flow_nodes`）；缺定义回退裸 key；
- `health.js`：`b.label || b.step` 渲染，纯展示层跟随。

## 验证

TDD：plan:2#3 行 label == "拆解任务与阶段·锚点核验"；节点成本行 label == 节点中文名；非法 key 回退原样。全量 pytest + ruff。
