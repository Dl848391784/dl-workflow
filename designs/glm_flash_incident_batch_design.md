# GLM-5.3-Flash 实爆批次修复（u:1#2 格式搏斗 + Skill 权限 + node-rules 路径形态）

> 2026-09-17。实例：Mac/qoder GLM-5.3-Flash，23min 未落库。改动范围：`dl_flow_trace.py`（parser+scaffold）、段 settings 生成点、node-rules 生成点 + 各自测试。

## 实爆四项与根因

1. **append-trace 三连拒（#23/#25/#28）**：深层根因不是模型猜格式——是 **req_items 在 .md 标记格式里结构性不可表达**：`_MD_ITEM_FIELDS` 不含 unit/id/req/covers/evaluable/criterion/kind，行首检测只认单字段重复（req_items 双行形态：unit 行/id 行混排），scaffold 对 str-spec 键只生成【q】待填。模型手写任何 .md 形态都必拒，只能退回 JSON 盲猜。cb480 时代注释「弱模型写不出 JSON 嵌套 kind」已埋下此坑——kind 形状推断修了读侧，写侧 md 通道没跟上。
2. **headless 段 Skill 3/3 死**：段 prompt 教 `Skill invoke define-problem`，但段 settings 权限未放行 Skill 工具——headless 无人可答交互确认，必死。结构性自相矛盾。
3. **node-rules 路径形态自相矛盾**：rules 里写绝对路径（`/Users/.../dl-cmd.sh`），allowlist 只放行 `~/.dl-workflow/...` 形态——照抄规则即被拒。用户拍板：rules 统一输出 ~ 形态。
4. 围栏 raw grep 放行/拦截不一致：缺实例数据，挂起待查（不盲修）。

## 方案

- **T1**（dl_flow_trace.py）：`_MD_ITEM_FIELDS` 补 req_items 行字段；新增 `_MD_ITEM_LIST_FIELDS`（covers/evaluable 一行一条）；新增 `_MD_ROW_STARTERS`（req_items 行首=【unit】/【id】，替代单字段重复规则）；未知标头报错改动态枚举；`_scaffold_text` 对 req_items_structure 生成双行形态骨架+字段级提示。
- **T2**：headless 段 settings 放行 Skill 工具（step.kind=="skill" 的步 prompt 教了就必须能调）。
- **T3**：node-rules 命令路径统一 `~/.dl-workflow` 形态。

## 验证

TDD 每子项先红后绿；全量 pytest + ruff。验收口径：下个 GLM/qoder 实例 u:1#2 应一轮过格式（骨架双行形态在场）、Skill 调用零拒绝、dl-cmd.sh 零权限拒。
