# dashboard 产物链接 md→html 设计

> 2026-09-02。动机（用户指令）：dashboard 产物面板的链接从 md 换成 html——
> v0.3.0 起 render-artifact 自动产 `<name>.html`（人读渲染版），而现有
> `/static/artifact.html` 查看页只是 md 原文 `<pre>` 直出，人读体验差。

## 改动面（3 文件 + 测试）

1. **`dl_dashboard/outputs.py` `artifact_status`**：每 kind 增 `html_exists` /
   `html_size`（探测同目录 `<name>.html`），md 字段不动（下游兼容）。
2. **`dl_dashboard/app.py`**：新路由 `GET /artifact-html?project&name&kind`——
   kind 白名单（understands/plans，同 `load_artifact` 防穿越姿势）+ `_project`/`_name`
   校验，FileResponse 投 `.claude/<kind>/<name>.html`（inline，浏览器直接渲染），
   不存在 404。
3. **`static/app.js` `artLink`**：html 存在 → 链到 `/artifact-html`，标签
   `understand.html`/`plan.html`；不存在 → 旧 md 查看页兜底，标签维持
   `understand.md`/`plan.md`。**所见格式即所标**（no silent fallback：兜底
   不是隐式的，人从标签看出拿到哪份）。

## 不做什么

- 不删 md 查看页 `/static/artifact.html`（兜底 + 给模型/人看原文仍有入口）。
- 不改 `/api/artifact`（md 内容 API，查看页与潜在消费方继续用）。
- 旧实例 html 已批量转（2026-09-02，18/18），无迁移负担；未转的老实例走兜底。

## 测试

- outputs：html 存在/不存在两态的 `html_exists`/`html_size`。
- app：路由 200（内容=html 文件）/ 404（无 html）/ 400（kind 非法）。
- 既有 `test_artifact_status_and_content` 按新契约扩展（非回归）。

## 生效

dashboard server 是常驻进程（`python3 -m dl_dashboard.app`），merge 后须重启
才生效（driver 重认领由既有机制兜，症状 AU 教训）；static 版本指纹 `_serve_html`
已有 `?v=` 机制自动刷新。
