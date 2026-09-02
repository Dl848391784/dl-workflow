"""dl-workflow 技术文档渲染器：产物 md -> 人读 HTML（v0.5.0，designs/doc-renderer-design.md）。

替换 baoyu-markdown-to-html（定位公众号文章：单栏文章流/无目录/无锚点）。
单文件自包含输出：左侧 sticky 目录（H2/H3 锚点 + scroll-spy）、技术排版
（紧凑行宽/等宽代码/表格斑马纹）、statement 字段尾巴 dimmed meta 行（样式
降级零内容删除，md 真源不动）。唯一三方依赖 = Python-Markdown。

入口：render_html(md_path, html_path, version="")——异常上抛，调用方
（engine._render_html_companion）捕获转降级注记（赠品纪律：绝不阻断装配）。
"""

from __future__ import annotations

import re
from pathlib import Path

import markdown

# statement extras 尾巴：`- ` 非 qa 项 bullet，行尾（…）段含 ；或 = 且 >20 字符
# （type_label；boundary；k=v 形态，常含嵌套括号）。判中 -> 移 meta 行（样式降级，
# 内容全保留）；content 尾括号无 ；= 自然不匹配（宁纵勿枉，误判代价=样式不丢内容）。
_META_TAIL_RE = re.compile(r"^(- (?!【).+?)（(.+)）$")
_META_TAIL_MIN = 20

_MD_EXTS = ["tables", "fenced_code", "toc", "sane_lists"]


def _slugify_unicode(value: str, separator: str) -> str:
    """toc 锚点 slug：保留 CJK（py3 re \\w 原生匹配 unicode 字符）。

    默认 slugify 剥非 ASCII——中文节标题全变 _1/_2/_3（功能不破但 URL 不可读、
    锚点无语义）。判据：\\w 字符 + 连字符保留，空白转 separator，其余剥除。
    """
    return re.sub(r"[^\w\- ]", "", value).strip().replace(" ", separator)


_MD_EXT_CFG = {
    "toc": {"permalink": " ¶", "toc_depth": "2-3", "slugify": _slugify_unicode}
}

_DOC_NOTE = "（render-artifact 机械装配，禁手改——改内容请改对应步 trace 后重渲染）"

_TITLE_RE = re.compile(r"^# +(.+)$", re.M)

_CSS = """
:root{--fg:#1f2328;--muted:#656d76;--line:#d1d9e0;--accent:#2557a7;
--bg:#fff;--bg-soft:#f6f8fa;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;font:15px/1.75 -apple-system,"Segoe UI","PingFang SC",
"Hiragino Sans GB","Microsoft YaHei",sans-serif;color:var(--fg);background:var(--bg)}
#toc{position:fixed;top:0;left:0;bottom:0;width:250px;overflow-y:auto;padding:28px 16px;
border-right:1px solid var(--line);background:var(--bg-soft);font-size:13px;line-height:1.5}
#toc .toc-title{font-weight:600;margin-bottom:8px;color:var(--muted);letter-spacing:.08em}
#toc ul{list-style:none;padding-left:12px;margin:2px 0}
#toc>ul{padding-left:0}
#toc a{color:var(--fg);text-decoration:none;display:block;padding:3px 6px;border-radius:5px;
border-left:2px solid transparent}
#toc a:hover{background:#eaeef2}
#toc a.active{border-left-color:var(--accent);color:var(--accent);
background:#eaeef2;font-weight:600}
main{margin-left:250px;padding:40px 48px 80px}
article{max-width:880px}
h1{font-size:26px;line-height:1.35;margin:0 0 8px}
h2{font-size:20px;margin:36px 0 12px;padding:0 0 6px 10px;
border-left:4px solid var(--accent);border-bottom:1px solid var(--line)}
h3{font-size:16px;margin:24px 0 8px}
a{color:var(--accent)}
.headerlink{opacity:0;margin-left:6px;text-decoration:none;font-weight:400;font-size:.8em}
h2:hover .headerlink,h3:hover .headerlink{opacity:.6}
p{margin:10px 0}
code{font-family:var(--mono);font-size:.88em;background:#eff1f3;
padding:.1em .35em;border-radius:4px;word-break:break-all}
pre{background:#0d1117;color:#e6edf3;padding:14px 16px;border-radius:8px;
overflow-x:auto;line-height:1.55}
pre code{background:none;padding:0;color:inherit}
table{border-collapse:collapse;margin:14px 0;width:100%;font-size:14px}
th,td{border:1px solid var(--line);padding:6px 10px;text-align:left;vertical-align:top}
th{background:var(--bg-soft)}
tr:nth-child(even) td{background:#fafbfc}
blockquote{margin:14px 0;padding:4px 14px;border-left:3px solid var(--line);
color:var(--muted);background:var(--bg-soft);border-radius:0 6px 6px 0}
li{margin:5px 0}
small.meta{display:block;color:var(--muted);font-size:12px;line-height:1.5;
margin:2px 0 6px;word-break:break-all}
p.doc-note{color:var(--muted);font-size:13px}
footer{margin-top:48px;padding-top:14px;border-top:1px solid var(--line);
color:var(--muted);font-size:12px}
@media (max-width:900px){
#toc{position:static;width:auto;border-right:none;border-bottom:1px solid var(--line)}
main{margin-left:0;padding:24px 18px 60px}}
"""

_JS = """
(function(){
var links=document.querySelectorAll('#toc a[href^="#"]');
var map={};
links.forEach(function(a){map[a.getAttribute('href').slice(1)]=a;});
var heads=document.querySelectorAll('article h2[id],article h3[id]');
function onScroll(){
var cur=null,i;
for(i=0;i<heads.length;i++){if(heads[i].getBoundingClientRect().top<120)cur=heads[i].id;}
links.forEach(function(a){a.classList.remove('active');});
if(cur&&map[cur])map[cur].classList.add('active');
}
document.addEventListener('scroll',onScroll,true);
onScroll();
})();
"""

_TEMPLATE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>__CSS__</style>
</head>
<body>
<aside id="toc"><div class="toc-title">目录</div>__TOC__</aside>
<main>
<article>
__BODY__
</article>
<footer>dl-workflow__VERSION__ · render-artifact 机械装配 · 真源 = evidence trace（改内容改 trace 后重渲染）</footer>
</main>
<script>__JS__</script>
</body>
</html>
"""


def _extract_title(text: str, md_path: Path) -> str:
    m = _TITLE_RE.search(text)
    return m.group(1).strip() if m else md_path.stem


def _mark_meta_tails(text: str) -> str:
    """statement extras 尾巴 -> bullet 下独立 meta 行（样式降级，零内容删除）。"""
    out = []
    for line in text.splitlines():
        m = _META_TAIL_RE.match(line)
        if (
            m
            and ("；" in m.group(2) or "=" in m.group(2))
            and len(m.group(2)) > _META_TAIL_MIN
        ):
            out.append(m.group(1))
            out.append(f'  <small class="meta">（{m.group(2)}）</small>')
        else:
            out.append(line)
    return "\n".join(out)


def render_html(md_path: Path, html_path: Path, version: str = "") -> None:
    """md -> 单文件人读 HTML。异常上抛（调用方转降级注记）。"""
    text = Path(md_path).read_text(encoding="utf-8")
    title = _extract_title(text, Path(md_path))
    conv = markdown.Markdown(extensions=_MD_EXTS, extension_configs=_MD_EXT_CFG)
    body = conv.convert(_mark_meta_tails(text))
    body = body.replace(f"<p>{_DOC_NOTE}</p>", f'<p class="doc-note">{_DOC_NOTE}</p>')
    html = (
        _TEMPLATE.replace("__TITLE__", title)
        .replace("__CSS__", _CSS)
        .replace("__TOC__", conv.toc)
        .replace("__BODY__", body)
        .replace("__VERSION__", f" v{version}" if version else "")
        .replace("__JS__", _JS)
    )
    Path(html_path).write_text(html, encoding="utf-8")
