# req_items evaluable 1:1 机械核 设计

> 2026-09-17。来源：0.11.9 需求点主轴校验会话——已知观察「粒度判据 judge 未拦」
> （deepseek judge 仍出 5 条粗粒度 req）的既定细化方案落地。

## 根因

粒度判据（一条 req=一个可独立验收判据，禁合并）只入 purpose+gate 零条款
（文案+judge 裁量），judge 轮间方差下弱模型粗粒度产物可漏过。按弱模型优先
原则，判据钉死的下一步=下沉机械层。

## 方案（契约收紧，u:1#2 req_items）

- **source_unit 行**加必给 `evaluable`：数组，该单元逐条可独立验收判据枚举；
  空数组合法（模板/箴言/买卖纪律等不可判据章节）；**缺键=拒**（漏枚举嫌疑，
  显式才算数）。
- **req 行**加 `criterion`：逐字等于所覆盖单元的某一条 evaluable 判据。
  纯排除行（covers 的单元 evaluable 全空）免 criterion。
- **机械核（`_check_req_items` 内）**：全部 evaluable 判据 ↔ req criterion
  1:1——漏承接=拒、凭空 criterion=拒、两条 req 重复承接同一判据=拒、
  criterion 属未覆盖单元=拒、判据文本跨单元重复=拒（归属歧义）。
  效果：合并多个判据进一条 req 在结构上写不进，粒度判断不再依赖 judge。
- **gate 同步**：u:1#2 gate 零条款（judge 判粒度）退役，并入机械披露括号
  「勿以粒度为由 block」（v2.34 机械已判勿再判先例）。
- **读侧**：proposal req_blocks 渲染补「验收判据」行（有 criterion 时）。

## 改动面

1. `dl_flow_checks.py`：`_check_req_items` 加 evaluable/criterion 校验
2. `dl_flow_nodes.py`：u:1#2 purpose 骨架 + gate 文案同步
3. `dl_flow_engine.py`：`_emit_req_blocks` 渲染 criterion 行
4. `tests/test_dl_flow_engine.py`：TestReqItemsEvaluable 8 例 + `_REQ_ITEMS_MIN`
   夹具对齐（stale fixture 非回归）
5. `skills/workflow-creation/references/node-split-methodology.md`：已知观察销项

## 兼容

老实例已落盘的旧式 req_items trace 不受影响（校验只拦新 append）；
`_load_req_items`/`req_id_known`/req_blocks 渲染对旧式行照常工作
（criterion 缺=渲染该行省略）。
