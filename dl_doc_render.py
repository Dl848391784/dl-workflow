"""dl-workflow 技术文档渲染器：产物 md -> 人读 HTML（designs/doc-renderer-design.md）。

替换 baoyu-markdown-to-html（定位公众号文章：单栏文章流/无目录/无锚点）。
单文件自包含输出：左侧 sticky 目录（H2/H3 锚点 + scroll-spy）、技术排版
（紧凑行宽/等宽代码/表格斑马纹）。唯一三方依赖 = Python-Markdown。

渲染层增强（md 真源不动、零内容创作、机械规则）：
- statement 字段尾巴 -> dimmed meta 行（样式降级零内容删除）；
- change_point= 字段 -> dashboard 同款改动面卡片（锚点+改前/改后对照+现状
  代码 ±4 行，解析单源=dl_flow_common.parse_change_points）；
- interface= 字段 -> 单改动项小链（Consumes->本项改动->Produces 芯片流，
  边只在本项字段内、跨项不连——v0.6 合并大图的全对全边是虚构，已退役）；
- 重点标注（ref chip/关键词 badge/数值加粗）+ 长 bullet 按 。；边界拆分。

入口：render_html(md_path, html_path, version="")——异常上抛，调用方
（engine._render_html_companion）捕获转降级注记（赠品纪律：绝不阻断装配）。
"""

from __future__ import annotations

import html as _html
import re
from pathlib import Path

import markdown

from dl_flow_common import CP_RE, parse_change_points

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

# ---------- 重点标注规则（render 层 span 化，零文字改动） ----------
# ref chip：_macros.html:57 / data_loaders.py:166-168 / app.py:_render_report:L267
_REF_RE = re.compile(r"([\w./-]+\.\w+(?::[\w.-]+)?:L?\d+(?:-\d+)?)")
_BADGES = [
    ("根因@", "b-root"),
    ("不可逆", "b-irrev"),
    ("证伪", "b-fals"),
    ("剔除", "b-drop"),
    ("裁决", "b-judge"),
]
_NUM_RE = re.compile(r"(\d+(?:\.\d+)?%|×\d+(?:\.\d+)?)")

# 长 bullet 拆分阈值与边界（机械拆分，零内容变化）
_SPLIT_MIN = 300
_SENT_SPLIT_RE = re.compile(r"(?<=[。；])")

# 调用流程图源：interface=Consumes：...Produces：...（change_spec 门钉死字段）。
# 分隔符两变体兼容：Consumes：/Consumes=（全量轨老实例用半角=，实证
# amplitude_annualized vs web_interaction 两形态并存）。
# 终止符含 \n：slim proposal 里 interface 是末字段（无 ；verify= 续接），
# 只靠 $ 会吞到文尾把后续 bullet 全吸进 Produces 标签（v0.7 实证）。
_IFACE_RE = re.compile(
    r"interface=Consumes[=：](.+?)Produces[=：](.+?)"
    r"(?:；(?:verify|acceptance_map|trace_anchor)=|\n|$)",
    re.S,
)
# change_point 剥除后的残行：空 bullet 或纯 interface 尾巴（已入流程图）。
# re.S：多锚点块的 interface 尾巴跨行（slim proposal 的字段值自带换行）。
_CP_RESIDUE_RE = re.compile(r"^-\s*(?:；\s*)?(?:interface=.*)?$", re.S)

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
/* 重点标注 */
span.ref{font-family:var(--mono);font-size:.85em;background:#e8f0fe;color:#1a56db;
padding:.05em .3em;border-radius:4px;white-space:nowrap}
span.num{font-weight:700;color:#b45309}
.badge{display:inline-block;font-size:11px;font-weight:600;padding:0 .45em;
border-radius:8px;line-height:1.7;vertical-align:1px}
.b-root{background:#fde8e8;color:#c81e1e}
.b-irrev{background:#fce8f3;color:#9d174d}
.b-fals{background:#fdf6b2;color:#8e4b10}
.b-drop{background:#f3f4f6;color:#6b7280}
.b-judge{background:#e1effe;color:#1e429f}
/* 改动面卡片（dashboard 同款） */
.cp-cards{margin:4px 0 14px}
.cp-card{border:1px solid var(--line);border-radius:8px;margin:8px 0;overflow:hidden}
.cp-head{padding:6px 12px;background:var(--bg-soft);border-bottom:1px solid var(--line);
font-family:var(--mono);font-size:12.5px;overflow:hidden}
.cp-act{float:right;font-weight:700;padding:0 .5em;border-radius:6px}
.act-改{background:#fff7ed;color:#c2410c}
.act-增{background:#ecfdf5;color:#047857}
.act-删{background:#fef2f2;color:#b91c1c}
.cp-ba{display:flex;gap:10px;padding:10px 12px;font-size:13px}
.cp-before,.cp-after{flex:1;border-radius:6px;padding:6px 8px;word-break:break-all}
.cp-before{background:#fef2f2}
.cp-after{background:#ecfdf5}
.cp-tag{font-weight:700;font-size:11px;margin-right:4px}
.cp-before .cp-tag{color:#b91c1c}
.cp-after .cp-tag{color:#047857}
.cp-arrow{align-self:center;color:var(--muted);font-weight:700}
.cp-ctx{margin:0;border-top:1px solid var(--line);border-radius:0;font-size:12px}
.ctx-hl{background:rgba(250,204,21,.22)}
/* 单改动项小链（Consumes->本项改动->Produces，边只在本项 interface= 内） */
.flowline{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:10px 0 4px;
padding:8px 10px;background:var(--bg-soft);border:1px solid var(--line);
border-radius:8px;font-size:12.5px}
.fl-chip{font-family:var(--mono);font-size:11.5px;padding:2px 8px;border-radius:10px;
white-space:nowrap;max-width:320px;overflow:hidden;text-overflow:ellipsis}
.fl-cons{background:#e8f0fe;color:#1a56db}
.fl-mid{background:#fff7ed;color:#c2410c;font-weight:600}
.fl-prod{background:#ecfdf5;color:#047857}
.fl-arrow{color:var(--muted);font-weight:700}
.fl-more{color:var(--muted);font-size:11px}
@media (max-width:900px){
#toc{position:static;width:auto;border-right:none;border-bottom:1px solid var(--line)}
main{margin-left:0;padding:24px 18px 60px}
.cp-ba{flex-direction:column}
.cp-arrow{transform:rotate(90deg);align-self:center}}
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

_esc = _html.escape


def _extract_title(text: str, md_path: Path) -> str:
    m = _TITLE_RE.search(text)
    return m.group(1).strip() if m else md_path.stem


# ---------- 改动面卡片 ----------
def _cp_card_html(cp: dict) -> str:
    head = (
        f"{_esc(cp['file'])}:{_esc(cp['method'])} "
        f"L{_esc(cp['line'])}"
        f'<span class="cp-act act-{cp["action"]}">{cp["action"]}</span>'
    )
    ba = ""
    if cp["before"] or cp["after"]:
        ba = (
            '<div class="cp-ba">'
            f'<div class="cp-before"><span class="cp-tag">改前</span> '
            f"<code>{_esc(cp['before'])}</code></div>"
            '<div class="cp-arrow">→</div>'
            f'<div class="cp-after"><span class="cp-tag">改后</span> '
            f"<code>{_esc(cp['after'])}</code></div></div>"
        )
    elif cp["summary"]:
        ba = (
            '<div class="cp-ba">'
            f'<div class="cp-after">{_esc(cp["summary"])}</div></div>'
        )
    ctx = ""
    c = cp.get("context")
    if c:
        rows = []
        for i, line in enumerate(c["lines"], c["start"]):
            cls = ' class="ctx-hl"' if i == c["anchor"] else ""
            rows.append(f"<span{cls}>{i:>4} {_esc(line)}</span>\n")
        ctx = f'<pre class="cp-ctx"><code>{"".join(rows)}</code></pre>'
    return f'<div class="cp-card"><div class="cp-head">{head}</div>{ba}{ctx}</div>'


def _strip_cp_field(line: str, project_root: Path | None) -> tuple[str, str]:
    """bullet 行内 change_point= 字段剥除 -> (剩余行, 卡片 html)。

    解析单源=dl_flow_common.parse_change_points（与 dashboard 改动面同 regex）。
    保留字段终止符段（；interface= 等）原位——残余字段仍归 meta 尾巴处理。
    """
    cards: list[str] = []

    def _sub(m: re.Match) -> str:
        for cp in parse_change_points(m.group(0), project_root):
            cards.append(_cp_card_html(cp))
        return m.group(0)[m.end(1) - m.start(0) :]

    new_line = CP_RE.sub(_sub, line)
    html = f'<div class="cp-cards">{"".join(cards)}</div>' if cards else ""
    return new_line, html


# ---------- 调用流程 SVG ----------
def _iface_labels(chunk: str) -> list[str]:
    """interface 块 -> 标签清单（去重保序）。"""
    labels: list[str] = []
    for entry in re.split(r"[；。]", chunk):
        entry = entry.strip()
        if not entry or entry.startswith(("测试侧", "本项")):
            continue
        label = re.split(r"[（(，,：:]", entry, 1)[0].strip()[:28]
        if label and label not in labels:
            labels.append(label)
    return labels


def _chips(labels: list[str], cls: str, cap: int = 3) -> str:
    """flowline 芯片组（超 cap 折 +n；title 留全文）。"""
    out = []
    for label in labels[:cap]:
        text = label if len(label) <= 26 else label[:25] + "…"
        out.append(
            f'<span class="fl-chip {cls}" title="{_esc(label)}">{_esc(text)}</span>'
        )
    if len(labels) > cap:
        out.append(f'<span class="fl-more">+{len(labels) - cap}</span>')
    return "".join(out)


def _mini_flow_html(
    consumes: list[str], middles: list[str], produces: list[str]
) -> str:
    """单改动项小链：Consumes -> 本项改动 -> Produces（芯片流，非图）。

    边只存在于本项 interface= 字段内部——该字段语义即「本项 Consumes X、
    Produces Y」，跨项一律不连（v0.6 合并大图的全对全边是虚构，已退役）。
    """
    parts = ['<div class="flowline">']
    if consumes:
        parts.append(_chips(consumes, "fl-cons"))
        parts.append('<span class="fl-arrow">→</span>')
    parts.append(_chips(middles or ["（本项无代码锚点）"], "fl-mid"))
    if produces:
        parts.append('<span class="fl-arrow">→</span>')
        parts.append(_chips(produces, "fl-prod"))
    parts.append("</div>")
    return "".join(parts)


# ---------- 重点标注 + 长文拆分 ----------
def _highlight_segment(seg: str) -> str:
    """非代码片段的重点标注（span 化，零文字改动）。"""
    for kw, cls in _BADGES:
        seg = seg.replace(kw, f'<span class="badge {cls}">{kw}</span>')
    seg = _REF_RE.sub(r'<span class="ref">\1</span>', seg)
    seg = _NUM_RE.sub(r'<span class="num">\1</span>', seg)
    return seg


def _highlight_line(line: str) -> str:
    """行级高亮：backtick 代码段内不标（偶数位=代码段外）。"""
    parts = line.split("`")
    for i in range(0, len(parts), 2):
        parts[i] = _highlight_segment(parts[i])
    return "`".join(parts)


def _split_long_bullet(line: str) -> str:
    """>300 字符 bullet 按 。；边界拆段（<br> 视觉分行，仍同一 li，零内容变化）。"""
    if not line.startswith("- ") or len(line) <= _SPLIT_MIN:
        return line
    segs = [s for s in _SENT_SPLIT_RE.split(line) if s]
    if len(segs) <= 2:
        return line
    return "<br>\n  ".join(segs)


# ---------- 预处理主管线 ----------
def _logical_lines(text: str) -> list[str]:
    """lazy continuation 并入上一条 bullet（md 语义=同一 li）。

    change_point 多锚点块的后续锚点各占一行（非 `- ` 开头）——逐行处理只会
    卡片化首个锚点、后续锚点裸文本残留（v0.6 实证漏网）。规则：非空行且不以
    `- `/`#`/`<`/`|`|`>`/空白缩进 开头 -> 并入上一条 bullet 行。
    """
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        if (
            not line.strip()
            or line.startswith(("- ", "#", "<", "|", ">"))
            or line[0:1].isspace()
        ):
            out.append(line)
            continue
        if out and out[-1].startswith("- "):
            out[-1] = out[-1] + "\n" + line
        else:
            out.append(line)
    return out


def _preprocess(text: str, project_root: Path | None) -> str:
    out: list[str] = []
    in_fence = False
    for line in _logical_lines(text):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence or line.lstrip().startswith("<"):
            out.append(line)
            continue
        # slim bullet（字段即全部内容）：本项 interface= -> 小链（边只在本项
        # 字段内，跨项不连）；full 文档的陈述 bullet 不走这条路（interface 留 meta）
        flow_html = ""
        if line.startswith(("- change_point=", "- interface=")):
            consumes: list[str] = []
            produces: list[str] = []
            for im in _IFACE_RE.finditer(line):
                for x in _iface_labels(im.group(1)):
                    if x not in consumes:
                        consumes.append(x)
                for x in _iface_labels(im.group(2)):
                    if x not in produces:
                        produces.append(x)
            if consumes or produces:
                middles: list[str] = []
                for cp in parse_change_points(line, None):
                    f = cp["file"].split("/")[-1]
                    if f not in middles:
                        middles.append(f)
                flow_html = _mini_flow_html(consumes, middles, produces)
        if "change_point=" in line:
            line, cards = _strip_cp_field(line, project_root)
        else:
            cards = ""
        if cards and _CP_RESIDUE_RE.match(line):
            # 字段已全量升级（change_point->卡片 / interface->小链），
            # 残行（空 bullet 或纯 interface 尾巴）不再占位（v0.7.0 slim proposal）。
            if flow_html:
                out.append(flow_html)
            out.append(cards)
            continue
        if not cards and "interface=" in line and _CP_RESIDUE_RE.match(line):
            # 纯 interface bullet（无 change_point 伴随）——字段已入小链，同样不落
            if flow_html:
                out.append(flow_html)
            continue
        m = _META_TAIL_RE.match(line)
        if (
            m
            and ("；" in m.group(2) or "=" in m.group(2))
            and len(m.group(2)) > _META_TAIL_MIN
        ):
            line = m.group(1)
            meta = f'  <small class="meta">（{m.group(2)}）</small>'
        else:
            meta = ""
        line = _split_long_bullet(line)
        line = _highlight_line(line)
        out.append(line)
        if meta:
            out.append(meta)
        if cards:
            out.append(cards)
    return "\n".join(out)


def render_html(md_path: Path, html_path: Path, version: str = "") -> None:
    """md -> 单文件人读 HTML。异常上抛（调用方转降级注记）。"""
    md_path = Path(md_path)
    text = md_path.read_text(encoding="utf-8")
    title = _extract_title(text, md_path)
    # project_root 推断（.claude/<kind>/<name>.md -> 上两级）：改动面卡片的现状
    # 代码片段 best-effort 实读；推断不出/文件不在 -> 卡片只显锚点+改前改后。
    project_root = None
    parts = md_path.resolve().parts
    if len(parts) >= 3 and parts[-3] == ".claude":
        project_root = Path(*parts[:-3])
    conv = markdown.Markdown(extensions=_MD_EXTS, extension_configs=_MD_EXT_CFG)
    body = conv.convert(_preprocess(text, project_root))
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
