"""dl_doc_render 技术文档渲染器测试（v0.5.0，designs/doc-renderer-design.md）。

自研渲染器替换 baoyu/bun 路径：左侧 sticky 目录 + CJK 锚点 + 技术排版 +
statement 字段尾巴 meta 样式降级（零内容删除）。
"""

from __future__ import annotations

import dl_doc_render as dr


def _render(tmp_path, text, name="t"):
    md = tmp_path / f"{name}.md"
    md.write_text(text, encoding="utf-8")
    out = tmp_path / f"{name}.html"
    dr.render_html(md, out, version="9.9.9")
    return out.read_text(encoding="utf-8")


def test_toc_and_cjk_anchors(tmp_path):
    h = _render(tmp_path, "# 标题\n\n## 背景与根因\n\nx\n\n## 改动面\n\ny\n")
    assert '<aside id="toc">' in h
    assert '<h2 id="背景与根因">' in h and '<h2 id="改动面">' in h
    assert 'href="#背景与根因"' in h
    assert "v9.9.9" in h


def test_meta_tail_marked_and_preserved(tmp_path):
    tail = "证实；证据指针 x.py:1；confidence=高；这段尾巴长度必须超过二十字符"
    h = _render(tmp_path, f"# t\n\n## S\n\n- 正文内容（{tail}）\n")
    # 样式降级零内容删除：尾巴全文在、带 meta 类、正文也在
    assert 'class="meta"' in h and tail in h and "正文内容" in h


def test_content_paren_not_marked(tmp_path):
    # content 尾括号无 ；/= -> 不误判（宁纵勿枉）
    h = _render(tmp_path, "# t\n\n## S\n\n- 年化 49.40%（对照 txt 报告）\n")
    assert 'class="meta"' not in h


def test_qa_items_not_marked(tmp_path):
    # qa 收录项（- 【q】a 形态）不处理——本身就是对话形态无 extras 尾巴
    h = _render(
        tmp_path,
        "# t\n\n## S\n\n- 【裁决：拍板】用户认可（注：含；符号的括号内容超过二十字符）\n",
    )
    assert 'class="meta"' not in h


def test_nested_paren_tail_marked(tmp_path):
    # 真实 tail 常含嵌套括号（出处指针）——v1 简单正则漏判的回归钉
    tail = "证实；家族枚举（_macros.html:57/:77（u:1#4 q7））；confidence=高"
    h = _render(tmp_path, f"# t\n\n## S\n\n- 正文（{tail}）\n")
    assert 'class="meta"' in h and tail in h


def test_table_and_fenced_code(tmp_path):
    h = _render(
        tmp_path,
        "# t\n\n## S\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```py\nx = 1\n```\n",
    )
    assert "<table>" in h and "<code" in h


def test_title_fallback_filename(tmp_path):
    h = _render(tmp_path, "## 无 H1\n", name="my_doc")
    assert "<title>my_doc</title>" in h


def test_doc_note_styled(tmp_path):
    h = _render(
        tmp_path,
        "# t\n\n（render-artifact 机械装配，禁手改——改内容请改对应步 trace 后重渲染）\n\n## S\n\nx\n",
    )
    assert 'class="doc-note"' in h


# ---------- v0.6.0：调用流程 / 改动面卡片 / 重点标注 / 长文拆分 ----------

_CP_BULLET = (
    "- 显示修复：模板去二次换算。；change_point="
    "web_ui/app.py:_render_report:L10-12（改）：改前=旧逻辑 → 改后=新逻辑"
)


def _iface_text(sep="："):
    return (
        f"- 步骤（out；change_point=web_ui/app.py:_render_report:L10-12（改）：改前=旧 → 改后=新"
        f"；interface=Consumes{sep}load_backtest_results(logger)（web_ui/app.py:267）。"
        f"Produces{sep}分层回测页显示=单次百分比文本。）"
    )


def test_flow_section_svg(tmp_path):
    text = "# t\n\n## 背景与根因\n\nx\n\n## 改动面\n\n" + _iface_text() + "\n"
    h = _render(tmp_path, text)
    assert '<h2 id="调用流程">' in h and "<svg" in h
    assert 'href="#调用流程"' in h  # TOC 收录
    assert "load_backtest_results" in h  # Consumes 节点
    assert "机械推导" in h


def test_flow_section_halfwidth_sep(tmp_path):
    # 回归钉：老实例 interface=Consumes= 半角分隔符（amplitude 实证两变体并存）
    text = "# t\n\n## 改动面\n\n" + _iface_text(sep="=") + "\n"
    h = _render(tmp_path, text)
    assert "<svg" in h and '<h2 id="调用流程">' in h


def test_flow_section_absent_without_interface(tmp_path):
    # 无 interface 数据 -> 节诚实缺席（不是空壳节）
    text = "# t\n\n## 改动面\n\n- 普通步骤无字段\n"
    h = _render(tmp_path, text)
    assert '<h2 id="调用流程">' not in h


def test_cp_card_rendered_with_context(tmp_path):
    # 真实项目布局：.claude/plans/t.md + web_ui/app.py -> 卡片含现状代码锚点高亮
    d = tmp_path / ".claude" / "plans"
    d.mkdir(parents=True)
    (tmp_path / "web_ui").mkdir()
    (tmp_path / "web_ui" / "app.py").write_text(
        "\n".join(f"line{i}" for i in range(1, 21)) + "\n", encoding="utf-8"
    )
    md = d / "t.md"
    md.write_text(f"# t\n\n## 改动面\n\n{_CP_BULLET}\n", encoding="utf-8")
    out = tmp_path / ".claude" / "plans" / "t.html"
    dr.render_html(md, out)
    h = out.read_text(encoding="utf-8")
    assert '<div class="cp-card">' in h
    assert "web_ui/app.py" in h and "改前" in h and "改后" in h
    assert 'class="ctx-hl"' in h and "line11" in h  # 锚点行 L10-12 上下文 ±4
    assert "change_point=web_ui" not in h  # 字段已升级为卡片，不再裸文本


def test_highlight_rules(tmp_path):
    h = _render(
        tmp_path,
        "# t\n\n## S\n\n- 根因@A@web_ui/app.py:_render_report:L267 显示 49.40% 异常\n",
    )
    assert 'class="badge b-root"' in h
    assert '<span class="ref">web_ui/app.py:_render_report:L267</span>' in h
    assert '<span class="num">49.40%</span>' in h


def test_highlight_skips_backtick_code(tmp_path):
    h = _render(tmp_path, "# t\n\n## S\n\n- 见 `_macros.html:57` 不标\n")
    assert 'class="ref"' not in h
    assert "<code>_macros.html:57</code>" in h


def test_long_bullet_split(tmp_path):
    seg = "这是一段足够长的陈述用来触发机械拆分阈值" * 12
    text = f"# t\n\n## S\n\n- {seg}。{seg}。{seg}。\n"
    h = _render(tmp_path, text)
    assert "<br>" in h
    assert seg in h  # 零内容变化
