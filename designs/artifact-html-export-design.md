# 产物 HTML 导出设计（artifact-html-export）

> 2026-09-02。动机（用户决议）：dl-workflow 产物 md（understands/plans）是给模型看的
> trace 装配档；人要读技术方案需要渲染版——用 baoyu-markdown-to-html 在产物落盘时
> 自动附带 HTML。md 仍是唯一真源，HTML 是赠品。

## 1. 范围与产出

- 覆盖产物：`<project>/.claude/understands/<name>.md` 与 `<project>/.claude/plans/<name>.md`
  （render-artifact 的全部两个 out_dir，无新增产物类型）。
- 产出：同目录 `<name>.html`（单文件 inline-CSS，浏览器直接打开/转发）。
- 转换器：baoyu-markdown-to-html（MIT，github.com/JimLiu/baoyu-skills），
  主题 `default` + `--keep-title`（保 H1；技术文档结构化阅读）。

## 2. 架构（三层）

1. **vendor 转换器**：`vendor/baoyu-markdown-to-html/scripts/`（main.ts + package.json
   + bun.lock + LICENSE 注明出处）。源码进 git 进 tarball；node_modules 不进
   （.gitignore `vendor/**/node_modules/`），目标机 install.sh 装依赖。
2. **engine 钩子**：`render_artifact()` 写 md 成功后调 `_render_html_companion(out)`，
   返回短注记附加进成功消息（`；HTML ✓ <path>` / `；HTML 降级：<原因>`）。
3. **install.sh 依赖层**：第 7 步 `install_html_deps`——vendor 目录 `bun install`
   （npmmirror 一次性参数；无 bun 时降级警告）。`--skip-html` 跳过；自检加
   「HTML 导出依赖」项。

## 3. 数据流

```
render-artifact understand.md|plan.md
  → 装配 md 落盘（既有逻辑，不变）
  → _render_html_companion(md_path)：
      bun 解析（command -v bun → npx -y bun，模块级缓存）→ 都没有 → 降级
      删旧 <name>.html（防 baoyu .bak 备份堆积；md 是真源，HTML 可再生）
      subprocess [bun..., main.ts, md, --theme default, --keep-title]，timeout 60s
      rc≠0 / 超时 / 异常 → 降级（原因进消息）
```

## 4. 错误处理（关键纪律）

- **赠品绝不阻断主链路**：bun 缺失 / 依赖未装 / 转换失败 / 超时——
  `render_artifact` 照常 `(True, ...)`，消息尾部附降级原因（no silent fallback：
  降级必须显式可见）。写 md 失败的既有行为不变（仍 `(False, ...)`）。
- bun 解析结果模块级缓存：一次进程只付一次 `npx -y bun` 探测开销。
- 每次重渲染都重转（装配是幂等覆盖，HTML 跟随）——节点边界调用频率低，可接受。

## 5. 测试

1. fake bun 桩（PATH 前置 shell 脚本，按参数落地假 html 并 rc=0）：
   render 后 html 存在、调用参数含 `--theme default --keep-title`、消息含 `HTML ✓`。
2. bun 全缺（PATH 无 bun/npx）：render 仍 ok，消息含「HTML 降级」，无 html 文件。
3. 现有 render_artifact 测试不回归（消息新增尾部注记，断言含匹配不受影响的
   不动；全等断言随契约更新——属对齐新契约非回归）。

## 6. 配套

- pack.sh REQUIRED 清单 +`vendor/baoyu-markdown-to-html/scripts/main.ts`。
- README：install.sh 步骤清单加 HTML 导出层；产物章节提 `<name>.html`。
- VERSION 0.2.0 → 0.3.0（新功能）。
- dashboard 不加按钮（YAGNI；html 落盘后人直接开文件，需要再说）。

## 7. 不做什么

- 不转 evidence.jsonl / discoveries / rules 类注入材料（非人读产物）。
- 不做 mermaid 强制渲染（无 Chrome 自动降级 `<pre>`，转换不失败——baoyu 自带行为）。
- 不改 dashboard、不加跨实例批量重转命令（需要时 `render-artifact` 重跑即得）。
