# append-trace 格式族拒绝附骨架（披露缺口修复）

> 2026-09-17。改动范围：`dl_flow_trace.py`（+对应测试 `tests/test_dl_flow_engine.py`，测试文件门禁白名单）。

## 根因（实爆）

searchstoretagmodify 实例（Mac/qoder）子2 格式打地鼠 33min：append-trace 连续拒绝，模型在【q】/【text】、JSON ±kind 键间枚举假设逐个试。按 cost-optimization #54/#55 分诊：

- 要件真实（格式规则客观存在，非幽灵要件）；
- 同一形态族连拒 + 每次换新假设 = **披露缺口**：否定式报错（「不要写 kind」「须写在数组键节内」）塌缩不了假设空间；
- 披露不一致：JSON 解码失败那条有 scaffold 指路，.md 解析失败/结构字段泄漏/格式混用这三条没有。

零成本出口本来存在（`append-trace --scaffold` 骨架，格式钉死），但模型绕开手写后，拒绝文案没把它拉回去。

## 方案（文案层，系统杠杆；弱模型优先原则：判据钉死→schema→文案）

1. 从 `scaffold_payload` 抽纯函数 `_scaffold_text(step)`——骨架文本生成单源（落盘与拒绝文案共用）；
2. 新增 `_format_reject(step, err)`：格式族拒绝统一附本步正确骨架全文 + 「对照修正当前载荷，勿重跑 --scaffold（拒覆盖）」；
3. 应用面（仅格式族）：.md 标记解析失败 / JSON 非对象 / 结构字段泄漏（kind 等）/ statements-qa 混用。语义族（占位符、字段空）不动。

## 验证

TDD 4 测（tests/test_dl_flow_engine.py TestAppendTraceFormatDisclosure）：md 解析错带骨架+对照指引 / kind 泄漏带骨架 / 混用带骨架 / 占位符拒绝不带骨架（防过reach）。全量 pytest + ruff。
