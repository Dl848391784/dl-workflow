# 技术文档渲染器设计（doc-renderer，v0.5.0）

> 2026-09-02。动机（用户决议「直接 B」）：baoyu-markdown-to-html 定位公众号文章
> （单栏文章流/无目录/无锚点），且 proposal 的巨型 trace bullet（最长 2996 字符、
> 26/234 超 500 字符）暴露内容形态问题。根治=自研 Python 技术文档渲染器替换
> baoyu 路径，顺带干掉 bun + vendor 依赖层。

## 1. 架构

```
render_artifact 写 md 成功
  → _render_html_companion(md_path)（契约不变：；HTML ✓ / ；HTML 降级：原因）
  → dl_doc_render.render_html(md_path, html_path)（in-process，替代 bun subprocess）
      1. md 预处理：statement 字段尾巴 -> meta 标记（§3）
      2. Python-Markdown 转 HTML body（extensions: tables/fenced_code/toc/sane_lists）
      3. 套自包含模板（CSS+少量 JS inline，单文件零外部引用）
```

- **dl_doc_render.py**（新，repo 根，~300 行含模板）：纯渲染，输入 md 路径输出
  html 路径，异常上抛（companion 捕获转降级注记）。唯一三方依赖 = `markdown`
  （Python-Markdown，纯 py，本机已装 3.10.2）。
- **engine**：`_render_html_companion` 改 in-process 调用；删 `_resolve_bun` /
  `_HTML_BUN_CACHE`（死代码）；html 直接覆盖写（我们的渲染器无 .bak 行为，
  旧 unlink 防堆积逻辑随删）。
- **vendor/ 整目录退役**：git rm；.gitignore/pack.sh/README 同步；install.sh
  加 legacy 清理（升级时 rm 掉老 vendor 目录，H13 死代码纪律）。

## 2. 模板（专业排版=核心价值）

单文件 HTML，inline CSS（~150 行）+ ~15 行 JS（TOC scroll-spy）：

- **布局**：左侧 sticky 目录（H2 条目，当前节高亮）+ 右侧正文 max-width 880px；
  移动端目录折叠到顶部。
- **目录源**：Python-Markdown `toc` extension（H2/H3 自动锚点 id + permalink ¶）。
- **排版**：system-ui 字体栈 15px/1.75；H2 左侧色条+下分隔；inline code 灰底
  等宽；fenced code 深底卡片；表格斑马纹+边框；blockquote 左竖线；长行
  word-break。配色中性（ slate/blue-gray 系），不靠主题皮肤。
- **页首**：H1 标题 + 「机械装配禁手改」注记行渲染为小字 note（识别
  `（render-artifact 机械装配…` 行）；文档 footer 标注 dl-workflow v<VERSION>。

## 3. 字段尾巴裁剪（内容形态修复，零内容删除）

md 真源一个字不动（机械装配产物、dashboard change_point 解析、模型消费全部
不受影响）；裁剪只在渲染层，且是**样式降级不是删除**：

- 规则（机械可判）：以 `- ` 开头且非 `- 【` 的 bullet 行，行尾若是
  `（…）` 且括号内含 `；` 或 `=` → 该尾段判为 statement extras
  （type_label；boundary；k=v），从正文移到 bullet 下独立一行
  `<small class="meta">`，dimmed 小字渲染。
- 误判代价=样式错位不丢内容（尾巴仍全文可见），宁纵勿枉反过来也安全。
- qa 收录项（`- 【q】a`）不处理（本身就是对话形态，无 extras 尾巴）。

## 4. 依赖与安装层

- install.sh `install_html_deps` 从「bun + bun install」改为
  `python3 -m pip install --user markdown`（复用 dashboard 层的 aliyun 一次性
  镜像逻辑）；自检项改 `python3 -c "import markdown"`；`--skip-html` 语义不变；
  顺清理 legacy `vendor/` 目录。
- pack.sh REQUIRED：vendor 三件 -> `dl_doc_render.py`；node_modules 排除项保留。
- engine import 策略：companion 内 lazy import dl_doc_render，ImportError
  （markdown 未装）→ 降级注记（契约同今）。

## 5. 测试

- **conftest.py 删除**（autouse 桩随 bun 路径一起退役）——渲染器 in-process
  毫秒级，全套件真渲染零外部进程零桩。
- test_dl_doc_render.py（新）：H2->TOC 条目+锚点 id、表格、fenced code、CJK、
  meta 尾巴（判定+内容保留+样式类）、qa 项不误判、标题提取、H1 缺失回退文件名。
- TestHtmlCompanion 改写：真渲染（html 含 nav/锚点/meta 类）；渲染器异常
  （monkeypatch render_html raise）-> 降级注记；render_artifact 钩子产 html。
- proposal/render 既有测试不回归（md 装配零改动）。

## 6. 收口

- VERSION 0.4.0 -> 0.5.0；README（装/产物段去 bun 说法）；designs 文档历史不动。
- 存量：merge 后全量重生成三 kind × 9 实例 html（render-artifact 重跑 or
  直接 renderer 批跑——md 不动只刷 html，走 renderer 批跑零装配风险）。
- dashboard 代码零改动（/artifact-html 直投 html 文件，谁产的无所谓）——
  无需重启 server。

## 7. 不做什么

- 不做 mermaid/数学公式（产物内容没有，YAGNI）。
- 不做多主题/暗色模式（一套专业版式打天下，主题切换是文章审美残留）。
- 不改 md 装配格式（§3 已述风险面）。
- 不保留 baoyu 做备选（双路径维护成本>H13，vendor 直接删）。
