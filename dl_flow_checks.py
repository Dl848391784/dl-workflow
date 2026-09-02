#!/usr/bin/env python3
"""
dl_flow_checks - v2.27 机械预检家族（_check_* 判定 + 注册表）。

拆分缘由（2026-08-27）：dl_flow_engine.py 7842 行 / ~180 顶层函数，其中
本节约 1900 行是签名高度统一（(qa, *_ctx) -> str | None）的纯规则判定，
几乎不碰状态机——抽出后 engine 聚焦编排内核。append_trace / fetch_prompt
经 engine 的 re-export 访问注册表与入口函数，import 路径不变。
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from dl_flow_common import (
    _iter_trace_segments,
    _node_entered_at,
    load_state,
    normalize_state,
    read_evidence,
    read_evidence_for_step,
)
from dl_flow_nodes import _CHANGE_SPEC_RULE, _NODES, _ROOT_CAUSE_LINE_RULE, get_node


# ---------- v2.27 statements 结构化载荷 + 机械预检 ----------
#
# 弱模型优先原则：判据的词形部分下沉机械层——judge 每轮 ~13k in + 天然方差，
# 正则能判的不该花 judge 调用还判不稳（tail_volume u:3 子4 审计）。
# ①方案名词扫描：实现侧名词真值在仓内（codegraph 符号表 + git 文件名），
#   text 命中即拒并指路挪 boundary（judge 前的预检，judge 仍兜底语义）；
# ②源步 ID 传导覆盖核对：逐项原子化传导=集合覆盖问题（u:3 子4 judge #1 的活）。

# 匹配边界用 ASCII 标识符边界：CJK 字符在 re.UNICODE 下是 \w，\b 在 CJK-Latin
# 交界不可靠（「的LayerConfigBase」用 \b 会误判有边界）。
_NOUN_L = r"(?<![A-Za-z0-9_])"
_NOUN_R = r"(?![A-Za-z0-9_])"

# 规范文档引用合法（硬规则约束的验证源=Read 规范文档原文），不算实现侧名词。
_NOUN_SKIP_EXTS = (".md", ".rst", ".txt")

# 条目编号模式：in[1]/in[1a-强正]/out[A]（范围项）、C1.1/SC4.1/H1.1（约束/标准/
# 硬规则项）、RC-A（红队反例）、#1a/#1b1（候选/陈述项）、U1/T1（任务/目标项）。
# v2.33 扩面（tail_volume plan:1 实测）：旧模式只认 in[]/单字母 X1.1，RC-A、
# T1、SC4.1、#1a 全部漏捕——plan 域节点的 ID 传导核对静默空转。
# ASCII 边界用否定环视（CJK 在 re.UNICODE 下是 \w，\b 在 CJK-Latin 交界不可靠，
# 同 _NOUN_L/_NOUN_R 先例）。
# v2.126 #N 分支加枚举位左边界（web_ui_interaction u:2#4 实爆）：「sources#2#3」
# 式引注噪声（# 前紧跟 ASCII 字母/数字/下划线）被抽成条目编号 → 幽灵传导义务
# 5 提交 4 拒打地鼠 733s。枚举位（行首/空白/标点/CJK 前）的 #N 不受影响——
# 传导义务只该由「声明式编号」产生，引注参照不产生义务。
_ID_RE = re.compile(
    r"[A-Za-z]+\[[\w-]+\]"  # in[1]/out[A]
    r"|[A-Z]{1,3}\d+\.\d+"  # C1.1/SC4.1/H1.1
    r"|RC-[A-Z]"  # RC-A 红队反例
    r"|(?<![A-Za-z0-9_])#[0-9]+[a-z]?\d*"  # #1a/#2/#1b1 候选与陈述项（枚举位）
    r"|(?<![A-Za-z0-9_])[UT]\d+(?![A-Za-z0-9_])"  # U1 任务/T1 目标
)


def _implementation_nouns(project_root: Path) -> set[str]:
    """仓内实现侧名词真值集（方案名词扫描用）：codegraph 符号 + git 文件名。

    只收强信号，保精度：①codegraph db 的 class/function/method 名——≥4 字符
    且含大写或下划线（snake_case/CamelCase 标识符不会出现在自然散文）；
    ②git ls-files 的带扩展名文件名（_macros.html/paths.py 进散文即实现引用；
    规范文档扩展名除外）。任一源缺失/失败 -> 跳过该源（预检是 judge 前的
    增强层不是必需行为，judge 仍兜底——降级不算 silent fallback）。
    """
    nouns: set[str] = set()
    db = project_root / ".codegraph" / "codegraph.db"
    if db.exists():
        try:
            import sqlite3

            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                for (n,) in con.execute(
                    "SELECT DISTINCT name FROM nodes"
                    " WHERE kind IN ('class','function','method')"
                ):
                    if (
                        isinstance(n, str)
                        and len(n) >= 4
                        and (any(c.isupper() for c in n) or "_" in n)
                    ):
                        nouns.add(n)
            finally:
                con.close()
        except (sqlite3.Error, OSError):
            pass
    try:
        res = subprocess.run(
            ["git", "ls-files"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode == 0:
            for f in res.stdout.splitlines():
                base = f.rsplit("/", 1)[-1]
                if (
                    "." in base
                    and not base.startswith(".")
                    and not base.endswith(_NOUN_SKIP_EXTS)
                ):
                    nouns.add(base)
    except (subprocess.TimeoutExpired, OSError):
        pass
    return nouns


def _step_trace_text(
    project_root: Path, name: str, sub_step: int, minor_key: str | None
) -> str:
    """取某子步骤最新 trace 的全文本（ID 传导核对与披露版的共用源侧）。"""
    text = read_evidence(project_root, name)
    if not text:
        return ""
    latest = None
    for _, rec in _iter_trace_segments(text, sub_step, minor_key):
        latest = rec
    if latest is None:
        return ""
    parts = [str(latest.get("purpose") or "")]
    for v in latest.get("q") or []:
        parts.append(str(v))
    for v in latest.get("a") or []:
        parts.append(str(v))
    for item in latest.get("statements") or []:
        if isinstance(item, dict):
            parts.extend(
                str(item.get(k) or "") for k in ("text", "type_label", "boundary")
            )
            flds = item.get("fields")
            if isinstance(flds, dict):
                parts.extend(str(v) for v in flds.values())
    return " ".join(parts)


def _step_trace_ids(
    project_root: Path, name: str, sub_step: int, minor_key: str | None
) -> set[str]:
    """取某子步骤最新 trace 文本里的条目编号集（ID 传导覆盖核对的源侧）。"""
    return set(_step_trace_id_contexts(project_root, name, sub_step, minor_key))


def _step_trace_id_contexts(
    project_root: Path, name: str, sub_step: int, minor_key: str | None
) -> dict[str, str]:
    """_step_trace_ids 的披露版（v2.126）：每个 ID 附源文 ±24 字片段。

    拒绝文案引出处用——模型据此判断缺传 ID 是真条目还是引注噪声，
    免于 grep 其他实例 evidence 反推格式（web_ui_interaction u:2#4 打地鼠
    事故的披露缺口修法）。
    """
    text = _step_trace_text(project_root, name, sub_step, minor_key)
    ctx: dict[str, str] = {}
    for m in _ID_RE.finditer(text):
        if m.group(0) in ctx:
            continue
        lo = max(0, m.start() - 24)
        hi = min(len(text), m.end() + 24)
        ctx[m.group(0)] = text[lo:hi].replace("\n", " ").strip()
    return ctx


def _source_step_index(step, cur: int) -> int | None:
    """传导源步号：step.input 声明（"step3.xxx"）优先，缺省上一步。"""
    m = re.search(r"step(\d+)", step.input or "")
    if m:
        return int(m.group(1))
    return cur - 1 if cur > 1 else None


def payload_format_hint(step) -> list[str]:
    """注入用载荷格式说明行（按步 record_format；单源，phase hook 直接渲染）。

    v2.58：载荷格式从 JSON 换成分节标记文本——模型零接触 JSON（Edit 填
    JSON 会被内容里的 ASCII 引号弄崩；四桶分工「脚本管格式」的正治）。
    """
    head = [
        "   载荷 = 分节标记文本（.md，零转义——内容随便带引号/换行/代码，"
        "格式全归脚本）：",
        "   走 `--scaffold` 生成骨架（禁手写 Write 载荷文件——围栏 deny；"
        "标头格式脚本管）→ Edit 把每个「待填」换成内容 → append-trace "
        "--from-file <骨架路径>",
    ]
    if getattr(step, "record_format", "qa") == "statements":
        req = getattr(step, "statement_fields", ()) or ()
        fields_seg = "".join(f"【fields.{k}】" for k in req)
        fields_note = (
            "；fields 逐键非空（" + "/".join(req) + "）——缺键 append-trace 当场拒"
            if req
            else ""
        )
        return head + [
            "   【purpose】<该步目的> →【statements】→ 逐项 "
            f"【text】<单句陈述>【type_label】<类型标签>【boundary】<边界/实现指针>{fields_seg}"
            "（text 只许 outcome-level——实现侧名词/file:line 只能进 boundary，"
            "text 会被机械扫描打回" + fields_note + "）",
            "   ✗ 反例（必拒）：text 含文件名/类名（挪 boundary）；"
            "或残留「待填」占位符（漏填当场拒）",
        ]
    extra = getattr(step, "extra_payload_keys", ()) if step is not None else ()
    seen = []
    for e in extra:
        if e[0] not in seen:
            seen.append(e[0])
    extra_seg = "".join(f" →【{k}】" for k in seen)
    extra_note = (
        "；"
        + "/".join(seen)
        + " 键 append-trace 机械校验存在性与格式，缺键/格式错当场拒"
        if extra
        else ""
    ) + "（逐项结构见本步 purpose）"
    return head + [
        "   【purpose】<该步目的> →【qa】→ 逐项【q】<问题>【a】<答案>"
        + extra_seg
        + extra_note,
        "   ✗ 反例（必 block）：【a】写「已理解」式汇总声明（非记录）；"
        "或残留「待填」占位符（漏填当场拒）",
    ]


# ---------- v2.37 写侧机械层扩面（u:1 一次通过率三连修）----------
#
# 动机（2026-08-01 tail_volume u:1 审计）：v2.36 判据钉死保 judge 判得对，
# 不保模型一次写对——钉死后 relaunch 子2 仍同症两连 block。每次 block ≈
# 全上下文重读 2-3 轮 + judge 调用，词形/结构形式要件继续下沉写侧机械层。
_PLACEHOLDER_MARKERS = (
    "进行中",
    "待补",
    "待填",
    "待追加",
    "待收录",
    "稍后补",
    "TODO",
    "TBD",
)


def _placeholder_hit(payload: dict) -> tuple[str, str] | None:
    """占位符全局扫描：trace 是完成记录，占位标记出现在任何内容字段即拒。

    动机 = tail_volume u:1 子4 att1：红队子代理未归就先 append，purpose 写
    「进行中：…红队到达后追加」白烧一轮 judge。扫描面 = purpose + 载荷全部
    字符串值（qa/statements/extra 键通用，零 per-step 接线）；FP 面已验证
    （当晚 17 条 trace 仅真违规者命中，demo.jsonl 零命中）。
    返回 (标记, 位置) 或 None。
    """

    def _walk(v, path):
        if isinstance(v, str):
            for m in _PLACEHOLDER_MARKERS:
                if m in v:
                    return (m, path)
        elif isinstance(v, list):
            for i, it in enumerate(v):
                r = _walk(it, f"{path}[{i}]")
                if r:
                    return r
        elif isinstance(v, dict):
            for k, it in v.items():
                r = _walk(it, f"{path}.{k}" if path else str(k))
                if r:
                    return r
        return None

    return _walk(payload, "")


# 「可能」扫描排除「不可能」（否定式是合法断言）。
_MAYBE_RE = re.compile(r"(?<!不)可能")

# v2.49 词形扩面（全部取自 tail_volume_acceleration_annualized u:1 子2 三轮真实
# 被 block 载荷逐字字面，重放分隔度见 TestCausalRingNoUntested）：
# att1 待办形态桥接「需 pyarrow…sort 看 top10」「需 Read 验证」——
# 否定/限定式（无需/所需/必需/按需）是合法断言，排除。
_NEED_ACTION_RE = re.compile(
    r"(?<![无所必按])需[^，。；]{0,40}(?:验证|核实|确认|取证|看|Read|grep|sort)"
)
# att3 假设形态链环「若 convert 函数…未做截断/钳制则异常值…传到上层」。
_IF_THEN_RE = re.compile(r"若[^，。；]{0,40}则")
# att2 行号跨度充精确指针「:565-771」（206 行）；规则正例/通过载荷跨度 ≤17，
# 阈值 50 双侧 margin 均宽（钉死进 _CAUSAL_CHAIN_EVIDENCE_RULE，非调参）。
_WIDE_SPAN_RE = re.compile(r":(\d+)-(\d+)")
_WIDE_SPAN_LIMIT = 50
# att3 竞争假设「排除」句推断词形（保留句豁免——标「待子3取证」是合法出口，
# 与 _CAUSAL_CHAIN_EVIDENCE_RULE 排除/保留拆分一一对应）。
_EXCLUDE_INFERENCE_RE = re.compile(r"未实测|待实测|未验证|待验证|推测|(?<!不)可能")

# v2.50 占环位词形（2026-08-02 u:1 子2 三连 block att1 逐字：Why4「…待子3
# 取证」、Why5「…降格进竞争假设待子3验证」整环无指针）——「待子3取证/降格」
# 声明独占环位=未降格（规则反例早已双侧钉死，词形本轮首现，按逐字纪律补下沉）。
# 环段锚 WhyN 带冒号：自查/元描述项的「Why1-Why4」式环引用不切段，合法汇报
# 降格去向不误扫（att3 自查项零 FP）；段内带 :\d+ 指针的尾部降格去向声明
# 合法（att3 B Why5 形态 judge 已接受）——占环位的操作化=环内无实测指针。
_RING_START_RE = re.compile(r"Why\d+[:：]")
_DEMOTE_RING_RE = re.compile(r"待子\s*3\s*(?:取证|验证)|(?<![不未无])降格")

# v2.55 全局否定断言扫描（2026-08-02 tail_volume_acceleration_annualized
# u:1 子2 att2 block 实证）：Why4「没有显式契约约定…」「无 unit test 钉住…」
# 「根因是层契约缺失」——模型把「读了文件没看到 X」当读出事实，实则
# 跨文件存在性命题（全局否定断言）=「读出后推出」同族：读出的是「有什么」，
# 不是「没有什么」。词形取 att1/att2 逐字（两 att 同一 Why4 文本）；豁免口与
# 合法出口一一对应（§3.5 #21③）：全域扫描零命中留痕（grep/扫描/零命中）
# 与尾部降格去向声明（v2.50 钉的合法形态）不拦。局部可读否定（「未做 X」
# 有该行原文背书）不在词表——v2.50 正例「未做单位判断（:69 原文…）」是
# 合法环，贪宽=FP。
_ABSENCE_CLAIM_RE = re.compile(r"没有显式|无显式|无\s*[Uu]nit\s*test|无单测|契约缺失")
_ABSENCE_EXEMPT_RE = re.compile(r"grep|扫描|零命中|无命中")
_ABSENCE_DEMOTE_RE = re.compile(r"降格|待子\s*3\s*取证|竞争假设")
_EVIDENCE_POINTER_RE = re.compile(r":\d+")


def _check_causal_ring_no_untested(qa: list, *_ctx) -> str | None:
    """causal_ring_no_untested：因果链环禁词扫描（u:1 子2 专属，nodes 声明）。

    主链环只许实测事实；「未实测」类状态标签与「可能」类推断词不是出处——
    词形来自真实违规字面（att1 Why4「可能剩 1-5 天」/ att2 Why5「未实测/推断」，
    att3 通过版零命中）。
    链识别（v2.46 放宽，不锚定 q 标题）：q 含「因果链」**或** a 含链式结构
    标记（Why/→）。旧实现只认标题——2026-08-02 实例模型用「Q4=…」式标题、
    链写进 a，标题锚定空转，「可能」漏到 judge 115s/10.8k tok 才拦
    （弱模型优先复盘：该机械判的东西漏给 judge = 扫描面锚错形状）。
    「假设」标题项收窄豁免（v2.49）：只豁免「保留」句（标「待子3取证」合法）；
    「排除」句=断言假设为假，排除理由含推断词形（未实测/推测/可能…）当场拒——
    旧实现整项豁免，att3「排除（…未实测…推测：…不成立）」漏到 judge
    第三轮才拦。「不可能」不命中（否定式是合法断言）。
    分隔度：8/2 真实被 block 载荷（Q1 未实测/Q4 可能）BLOCK、真实通过载荷
    与 demo 载荷 PASS；v2.49 扩面信号（需…验证/若…则/行号跨度/排除句推断）
    同口径重放（3 条被 block 载荷逐字 BLOCK、通过载荷零 FP）。
    v2.50 占环位扫描（WhyN: 环段级「待子3取证/降格」+ 全段无「:行号」指针）：
    同日三连 block att1 逐字 BLOCK、att3 尾部去向声明形态与自查项零 FP。
    v2.55 全局否定断言扫描（同日第三 episode att1/att2「没有显式契约/无 unit
    test/契约缺失」当主链根因）：项级扫描不锚 WhyN 分段（真实载荷 Why1=/
    Why4（根因层）= 形态分段全空转——锚内容结构不锚措辞）；豁免=全域扫描
    零命中留痕/降格去向声明。重放：两条真实被 block 载荷 REJECT、demo 通过
    载荷零 FP、降格去向/grep 留痕两合法形态 PASS。
    """
    banned = ("未实测", "待实测", "未验证", "待验证")
    for item in qa:
        q, a = str(item.get("q", "")), str(item.get("a", ""))
        if "假设" in q:
            for sent in re.split(r"[。；]", a):
                if "排除" not in sent:
                    continue
                m = _EXCLUDE_INFERENCE_RE.search(sent)
                if m:
                    return (
                        f"竞争假设「排除」理由含推断词形「{m.group(0)}」"
                        f"（{sent[:30]}…）——排除=断言假设为假，须证据指针"
                        "（file:line/读出事实）；证据不足时改标「保留」+"
                        "「待子3取证」，不推测排除"
                    )
            continue
        if "因果链" not in q and "Why" not in a and "→" not in a:
            continue
        hit = next((b for b in banned if b in a), None)
        if hit is None and _MAYBE_RE.search(a):
            hit = "可能"
        if hit is None:
            m = _NEED_ACTION_RE.search(a)
            if m:
                hit = m.group(0)
        if hit is None:
            m = _IF_THEN_RE.search(a)
            if m:
                hit = f"若…则（{m.group(0)[:24]}…）"
        if hit:
            return (
                f"因果链环含「{hit}」（{q[:20]}…）——主链环只许实测事实"
                "（file:line/数据值/日志原文/用户原话）；推断量级/未测状态/"
                "待办桥接/假设形态不是出处："
                "挖不动的深层整体降格进竞争假设分支并标「待子3取证」，"
                "主链挖到实测层即终止，不悬空、不贴标签充数"
            )
        for m in _WIDE_SPAN_RE.finditer(a):
            if int(m.group(2)) - int(m.group(1)) >= _WIDE_SPAN_LIMIT:
                return (
                    f"因果链环行号指针 {m.group(0)} 跨 "
                    f"{int(m.group(2)) - int(m.group(1))} 行（{q[:20]}…）——"
                    f"跨度 ≥{_WIDE_SPAN_LIMIT} 行不算精确指针："
                    "收窄到具体语句行（定义/赋值/调用行），并附该行原文"
                )
        # v2.50 占环位扫描：WhyN: 环段内含「待子3取证/降格」且全段无 :\d+
        # 实测指针 = 声明独占环位（规则反例「Why5=…降格至竞争假设分支」）
        # v2.55 全局否定断言扫描（项级，不锚 WhyN 分段——真实载荷 Why1=/
        # Why4（根因层）= 形态 ring 分段全空转，§3.5 #21「锚内容结构不锚
        # 措辞」）：跨文件存在性命题（无显式契约/无 unit test/契约缺失）
        # 不是读出事实——读出的是「有什么」不是「没有什么」。豁免口与合法
        # 出口一一对应：a 内有全域扫描零命中留痕（grep/扫描/零命中）全豁免；
        # 命中后 16 字符内接降格去向声明（v2.50 合法尾部形态）跳过该命中。
        # 局部可读否定（「未做 X」+该行原文背书）不在词表——贪宽=FP。
        if not _ABSENCE_EXEMPT_RE.search(a):
            for am in _ABSENCE_CLAIM_RE.finditer(a):
                if _ABSENCE_DEMOTE_RE.search(a, am.end(), am.end() + 16):
                    continue
                return (
                    f"因果链环含全局否定断言「{am.group(0)}」（{q[:20]}…）——"
                    "「没有/缺失 X」是跨文件存在性命题=推断不是读出事实："
                    "合法出处只有全域扫描零命中留痕（grep -rn 命令原文+零命中"
                    "结果）；否则主链终止于可直接读证的环，「没有 X」降格进"
                    "竞争假设分支标「待子3取证」"
                )
        ring_starts = list(_RING_START_RE.finditer(a))
        for i, m in enumerate(ring_starts):
            end = ring_starts[i + 1].start() if i + 1 < len(ring_starts) else len(a)
            seg = a[m.end() : end]
            dm = _DEMOTE_RING_RE.search(seg)
            if dm and not _EVIDENCE_POINTER_RE.search(seg):
                return (
                    f"因果链环以「{dm.group(0)}」占环位（{q[:20]}…，该环无 "
                    "file:line 指针）——「待子3取证/降格」声明独占环位=未降格："
                    "把该环从主链移除、改写进竞争假设分支（「待子3取证」的合法"
                    "位置在那里），主链挖到实测层（环内带 file:line 指针）即终止"
                )
    return None


def _check_value_no_unsourced_inference(qa: list, *_ctx) -> str | None:
    """value_no_unsourced_inference：价值/结论项推断词形扫描（u:2 子1 专属）。

    动机（2026-08-02 tail_volume_acceleration_annualized u:2 子1 att1）：
    形式要件（_G2_STEP1_FORM_REQUIREMENTS「结论逐句须有出处」）双侧披露后
    模型仍把「长期使用意味着会基于显示值做决策」「隐含价值」写进 V1/V2，
    且自声明「无推断补全」——自声明不可信（v2.37 教训：披露保 judge 判对
    不保模型写对），词形下沉写侧机械层。
    词形来自真实违规字面：隐含 / 意味着 / 可能（排除「不可能」否定式）。
    「推测」标注项豁免：标「推测」另列是形式要件内的合法出口（att2 通过版
    V2* 即此形态）。
    分隔度：att1 被 block 载荷（V1 隐含 / V2 意味着）BLOCK、att2 通过载荷
    PASS（推测豁免+干净项），重放回归见 TestValueNoUnsourcedInference。
    """
    for item in qa:
        q, a = str(item.get("q", "")), str(item.get("a", ""))
        if "价值" not in q and "结论" not in q:
            continue
        if "推测" in a:
            continue
        hit = next((m for m in ("隐含", "意味着") if m in a), None)
        if hit is None and _MAYBE_RE.search(a):
            hit = "可能"
        if hit:
            return (
                f"「{q[:16]}…」含推断词形「{hit}」——价值/结论只许用户原话或"
                "会话事实的直接引用（「X 意味着 Y」「隐含 Z」=读出后推出，不是事实）；"
                "推断须标「推测」另列，不纳入结论"
            )
    return None


_GOAL_LABEL_RE = re.compile(r"G\d+")


def _check_goal_candidate_traceability_alignment(qa: list, *_ctx) -> str | None:
    """goal_candidate_traceability_alignment：候选标签↔追溯项对齐（u:2 子1 专属）。

    动机（2026-08-04 u:2#1 framing 反转重放，designs/u2-sub1-gate-framing-design.md）：
    「候选对应不上存活问题=脑补」是语义判据，默认-PASS framing 下 judge 侧
    1-4/6 裁量方差；但其词形可判子项=候选标签（Gx）是否逐项出现在追溯项
    答案——孤儿候选（G2 只在候选项出现、追溯项不提）零方差当场拒，
    judge 只判声称对应的真实性（#30 ⑭ 语义判据词形子项切出下沉，
    同 v2.50 atomic_mece_alignment 集合对齐范式）。
    宁纵勿枉：无 G 标签（②无目标候选）或无追溯项（q 含「追溯」）跳过交 judge。
    """
    labels: set[str] = set()
    trace_a: list[str] = []
    for item in qa:
        q, a = str(item.get("q", "")), str(item.get("a", ""))
        labels.update(_GOAL_LABEL_RE.findall(a))
        if "追溯" in q:
            trace_a.append(a)
    if not labels or not trace_a:
        return None
    traced = set(_GOAL_LABEL_RE.findall("".join(trace_a)))
    missing = sorted(labels - traced)
    if missing:
        return (
            f"目标候选 {'、'.join(missing)} 未在追溯项答案出现——每个目标候选须"
            "逐项对应到 ProblemContext 存活问题（对应不上=脑补）：在追溯答案补"
            "该候选的承接说明，或剔除该候选"
        )
    return None


def _check_answer_source_marker(qa: list, *_ctx) -> str | None:
    """answer_source_marker：who/outcome/初步价值项答案出处标注扫描（u:2 子1 专属）。

    动机（2026-08-04 u:2#1 framing 反转 v1/v2 重放）：形式要件「答案引用用户
    原话或会话事实」在默认-PASS framing 下 judge 侧 4-5/6 边界晃（同文本两轮
    5/6->4/6 纯方差）——出处标注在场与否是词形可判子项（v2.48 同型下沉），
    标注后内容对口性留 judge。标注词表取 purpose/selfcheck 已披露词汇
    （§13 词表只收强信号）；写侧当场拒+指路（非 judge 黑盒返工）。
    """
    for item in qa:
        q, a = str(item.get("q", "")), str(item.get("a", ""))
        if "who" not in q and "outcome" not in q and "价值" not in q:
            continue
        if not any(m in a for m in ("原话", "原始请求", "会话事实", "选中", "自述")):
            return (
                f"「{q[:16]}…」答案无出处标注——形式要件要求答案引用用户原话或"
                "会话事实，标注形态：用户原话：'…' / 原始请求：'…' / 会话事实：… / "
                "（AskUserQuestion 选中）"
            )
        # who×原始请求不对口词形（v2.87 vio6 张冠李戴生产墙化）：请求原文
        # 不指向受益者——who 项引「原始请求」标注恒为张冠李戴，零方差拒。
        if "who" in q and "原始请求" in a:
            return (
                f"「{q[:16]}…」who 项引「原始请求」标注——请求原文不指向受益者；"
                "who 的合法标注=用户原话：'…'（指向人的原话）/（AskUserQuestion 选中）/"
                "用户自述/会话事实"
            )
    return None


_BASELINE_TOOL_TRACE_KEYWORDS = (
    "Bash实测",
    "Bash命令",
    "实测",
    "python3",
    "sqlite3",
    "codegraph",
    "运行",
    "路径",
    "输出",
    "报告第",
    "报告自身",
)


def _check_baseline_tool_trace(qa: list, *_ctx) -> str | None:
    """baseline_tool_trace：基线项工具留痕扫描（u:2 子3 专属）。

    动机（2026-08-04 u:2#3 framing 反转 v1/v3 重放）：「基线数字须有工具留痕，
    拍脑袋数字=编造」在默认-PASS framing 下 judge 侧 4-5/6 裁量方差（同文本
    v2 5/6 -> v3 4/6 纯方差，pass 全空判词）——「Bash实测…」vs「根据最近报告
    数据」仅差一个工具动词，词形可判子项（#30 ⑭，同 v2.87 answer_source_marker
    范式），切出下沉零方差生产墙，judge 只判留痕在场后的语义残项。
    宁纵勿枉：无基线题（q 含「基线/可量化」）跳过；「不可量化」标注=合法替代跳过；
    无数字（\\d 无命中）跳过交 judge（空泛复述兜底）；有数字但无工具动词=当场拒。
    禁把裸「报告」当工具词（「根据最近报告数据」会被误放行）；须工具动作词
    （Bash实测/命令/运行/输出/路径）或精确文件定位（报告第/报告自身）。
    """
    for item in qa:
        q, a = str(item.get("q", "")), str(item.get("a", ""))
        if "基线" not in q and "可量化" not in q:
            continue
        if "不可量化" in a:
            continue
        if re.search(r"\d", a) is None:
            continue
        if any(k in a for k in _BASELINE_TOOL_TRACE_KEYWORDS):
            continue
        return (
            f"「{q[:16]}…」基线数字无工具留痕（Bash实测/命令/运行/路径/输出等）"
            "——拍脑袋数字=编造：补 Bash 实测命令与输出留痕，或显式标注"
            "「不可量化+原因」"
        )
    return None


# 已验证项工具动词词表（u:3 子2 专属，#30 ⑭）。刻意排除裸名词「路径」
# （vio3「管理路径」会误放行）；只收工具动作词 + 具体留痕标记。
_CONSTRAINT_TOOL_TRACE_KEYWORDS = (
    "Read",
    "Bash实测",
    "Bash 实测",
    "实测",
    "python3",
    "sqlite3",
    "codegraph",
    "AskUserQuestion",
    "原文",
    "输出",
    "§",
    "grep",
    "命令",
    "运行",
)


def _check_constraint_verification_tool_trace(qa: list, *_ctx) -> str | None:
    """constraint_verification_tool_trace：已验证项工具留痕扫描（u:3 子2 专属）。

    动机（u:3#2 framing 反转 v1 重放）：「已验证项须附工具留痕出处，裸结论/训练
    记忆=编造」在默认-PASS framing 下 judge 侧 vio1 1/6（rubber-stamp 不主动查工具
    动词）、vio3 4/6--词形可判子项（#30 ⑭，同 v2.89 baseline_tool_trace 范式），
    切出下沉零方差生产墙，judge 只判留痕在场后的语义残项。vio3（通常/一般来说）同族
    （已验证项无本地工具留痕）一并被本 mech 拦。
    宁纵勿枉：只扫声明「已验证：」的处置项（跳过汇总「八条已验证」）；「假设/证伪」
    项不扫；已验证项含工具动词即放过；无工具动词=当场拒。排除裸名词「路径」防
    vio3「管理路径」误放行。
    """
    for item in qa:
        a = str(item.get("a", ""))
        if "已验证：" not in a:
            continue
        if any(k in a for k in _CONSTRAINT_TOOL_TRACE_KEYWORDS):
            continue
        return (
            f"「{str(item.get('q', ''))[:16]}…」已验证项无工具留痕出处"
            "（Read 原文/Bash 实测/codegraph/AskUserQuestion 原话/文件路径 等）"
            "--裸结论或训练记忆断言=编造：补工具留痕出处，或改标"
            "「假设·置信度·错误时影响」/附证据证伪"
        )
    return None


# 双向追溯 forward 承接断言形（plan:1 子4 集合对齐用）：目标标签后紧跟承接声明
# （「G2←要素三承接」/「G2 由…承接」）。**不用位置切分**——实测生产形态里
# 「自述 must 目标集={G1,G2}」常写在 forward 段**之后**（clean 与 vio4 载荷皆是），
# 按 forward 字样切分则自述集标签落进后半段自我满足、集合差恒空（mech 空转）。
# 改按承接断言邻接判定，与段落顺序无关：backward 侧「要素→G1」形与末尾自述集
# 「={G1,G2}」形均不含承接断言，不误计为已覆盖。
_FORWARD_LINK_RE = re.compile(r"(G\d+)([^。；\n]{0,24})")


def _check_pugh_traceability_forward_coverage(qa: list, *_ctx) -> str | None:
    """pugh_traceability_forward_coverage：双向追溯 forward 覆盖对齐（plan:1 子4 专属）。

    动机（2026-08-04 p:1#4 framing 反转 v1 重放，designs/p1-sub4-gate-framing-design.md）：
    「每 must 目标 ≥1 要素承接（防漏）」在默认-PASS framing 下 judge 侧 1/6——
    judge 不做集合差核对（自述 must={G1,G2} vs forward 只列 G1 承接），看到两向
    段落齐备即 rubber-stamp 放过。词形可判子项（#30 ⑭，同 v2.50
    atomic_mece_alignment / u:2#1 goal_candidate_traceability_alignment 集合对齐
    范式）：「自述 must 集的每个目标标签是否带承接断言」零方差当场拒，judge 只判
    承接声明的真实性与 backward 侧镀金。
    **不复用 goal_candidate_traceability_alignment**（㊴ 三点核对第三点不对齐）：
    该 mech 按「q 含追溯」取整条答案标签做集合差，本节点 must 集自述与承接声明
    **同在一条答案内** -> 自述侧标签自我满足、集合差恒空。
    宁纵勿枉：无追溯题（q 含「追溯」）/无 G 标签 -> 跳过交 judge；承接词形放宽
    到「←/<-/由/承接」四形任一（窗口 24 字内），judge 侧仍兜真实性；backward 侧
    镀金判定归 judge（要素名非标签，无词形可判）。
    """
    for item in qa:
        q, a = str(item.get("q", "")), str(item.get("a", ""))
        if "追溯" not in q:
            continue
        labels = set(_GOAL_LABEL_RE.findall(a))
        if not labels:
            continue
        covered = set()
        for label, tail in _FORWARD_LINK_RE.findall(a):
            if tail.startswith(("←", "<-", "由")) or "承接" in tail:
                covered.add(label)
        missing = sorted(labels - covered)
        if missing:
            return (
                f"双向追溯 forward 段缺 must 目标 {'、'.join(missing)} 的要素承接"
                "断言——每个 must 目标须 ≥1 方案要素承接（防漏）：在 forward 段写明"
                f"「{missing[0]}←某要素（承接）」，或说明该目标已移出 must 集"
            )
    return None


# Pugh 净分自洽（plan:1 子4）：候选段内逐格 +/− 计数 vs 自述净分数值。
# 候选段切分取「候选X：…净分 ±N。」——净分声明是段尾锚。逐格标注形=
# 「维度名 +」/「维度名 −」/「维度名 S」（S 计 0 不进净分，Pugh 常规）。
# 只在两者皆可解析时比对（宁纵勿枉：解析不到格标注或净分数值即跳过交 judge）。
_PUGH_CAND_RE = re.compile(r"候选([A-Z])[：:](.*?)净分\s*([+＋\-−]?)\s*(\d+)", re.S)
_PUGH_CELL_RE = re.compile(r"[（(]?\s*([+＋\-−S])\s*(?=[（(])")


def _check_pugh_net_score_consistency(qa: list, *_ctx) -> str | None:
    """pugh_net_score_consistency：Pugh 净分与逐格计数自洽（plan:1 子4 专属）。

    动机（2026-08-04 p:1#4 framing 反转 v1/v2 重放，designs/p1-sub4-gate-framing-design.md）：
    「矩阵结论与评分矛盾=凑结论」的算术子项（逐格 + 与 − 的个数 vs 自述净分数值）
    在默认-PASS framing 下 judge 侧 0/6 -> 1/6（v2 已把「须动手数格」写进 block 面
    仍不做）——**跨项聚合类判定 judge 系统性不执行**（§3.1 校准：mech 下沉预测器
    是「该判定是否需要跨项聚合（算术/集合运算）」，不是正/负判定方向）。算术是
    纯机械运算，切出下沉零方差生产墙（#30 ⑭），judge 只留「排序/推荐与净分的
    对应」语义侧。
    宁纵勿枉：无候选段/无净分声明/该段解析不到 +−S 格标注 -> 跳过交 judge；
    datum 候选（自述「=datum 全 S」无净分数值）天然跳过；容许 ±1 误差不设——
    净分定义是 +个数 − −个数（S 计 0），Pugh 标准算法无歧义。
    """
    for item in qa:
        a = str(item.get("a", ""))
        for cand, seg, sign, num in _PUGH_CAND_RE.findall(a):
            cells = _PUGH_CELL_RE.findall(seg)
            plus = sum(1 for c in cells if c in "+＋")
            minus = sum(1 for c in cells if c in "-−")
            if not cells or (plus + minus) == 0:
                continue
            declared = int(num) * (-1 if sign in "-−" else 1)
            actual = plus - minus
            if declared != actual:
                return (
                    f"候选{cand} 逐格计数与自述净分不符——数出 {plus} 个 + 与 "
                    f"{minus} 个 −（S 计 0），净分应为 {actual:+d}，却声明 "
                    f"{declared:+d}：凑结论=矩阵结论与评分矛盾。改净分数值与逐格"
                    "标注一致，或修正逐格 +/S/− 标注"
                )
    return None


# 现状勘察代码符号引用形（plan:1 子1 工具留痕扫描用）：
# `xxx.py`（含 `:line`）/ `function X file.py:N`（codegraph 输出形）。
# file:line 定位（`xxx.py:N`）本身即合法出处（形式要件「codegraph 原始输出或
# file:line 出处」的 or 分支），故单独识别的 file:line 视为出处在场、不拦——
# 只拦「既无 file:line 也无工具动词」的裸符号引用（凭空 API/训练记忆冒充）。
_TERRAIN_SYMBOL_RE = re.compile(r"[A-Za-z0-9_./-]+\.py(?::\d+)?|function\s+\w+")
_TERRAIN_FILELINE_RE = re.compile(r"[A-Za-z0-9_./-]+\.py:\d+")


def _check_terrain_tool_trace(qa: list, *_ctx) -> str | None:
    """terrain_tool_trace：现状勘察符号引用的工具留痕扫描（plan:1 子1 专属）。

    动机（p:1#1 framing 反转 v1 重放）：「现状事实条目（①涉及模块/②可复用点/③
    调用方/④数据契约/新鲜度判定）须附工具出处」在默认-PASS framing 下 judge 侧
    vio2 2/6——judge 看到 trace 整体出处齐备就不逐条审计，凭空 API 的裸符号引用
    （`ic_stats.py` 的 `count_positive_ic()` 无任何 codegraph/Read 动词）被
    rubber-stamp 放过。词形可判子项（#30 ⑭，同 u:3#2 constraint_verification_tool_trace
    / u:2#3 baseline_tool_trace 范式）：「该条回答引用了代码符号但既无 file:line
    也无工具动词」切出下沉零方差生产墙。
    **非 db 依赖**：只查 qa 文本词形，不读 codegraph db（design §3 的 db 存在性真值
    mech 被⑯红线否决；本 mech 是纯 token 扫描，⑯-safe）。「符号是否存在本仓」的
    存在性真值归 plan:1 子3，不在此。
    宁纵勿枉：只扫引用了代码符号形（.py / function X file.py:N）的回答；显式标
    「未知」的回答不扫（勘察不到的显式标注=合法，无需工具出处）；file:line 定位
    本身即出处、含工具动词亦放过；三者皆无的裸符号引用=拒。
    """
    for item in qa:
        a = str(item.get("a", ""))
        if not _TERRAIN_SYMBOL_RE.search(a):
            continue
        if "未知" in a:
            continue
        if _TERRAIN_FILELINE_RE.search(a):
            continue
        if any(k in a for k in _CONSTRAINT_TOOL_TRACE_KEYWORDS):
            continue
        return (
            f"「{str(item.get('q', ''))[:16]}…」现状事实引用了代码符号"
            "（`xxx.py`/函数名）却既无 file:line 定位也无任何工具留痕出处"
            "（codegraph/Read/Bash 实测 等）--裸符号引用=凭空 API/训练记忆冒充："
            "补工具留痕（codegraph 输出引用/file:line 定位/Read 原文/Bash 实测 "
            "任一），或改标「未知」"
        )
    return None


# 五项核验条目组（plan:1 子3 可行性验证写侧机械校验用）：圈码或条目名任一
# 在场即算该项留痕在场（模型可用任一记法；「不适用+原因」替代会以条目名
# 或在场圈码承载，天然落在「任一名在场」分支内，宁纵勿枉）。
_FEASIBILITY_ITEM_GROUPS = (
    ("①", "存在性"),
    ("②", "重复造轮子", "重复实现"),
    ("③", "影响面"),
    ("④", "硬规则"),
    ("⑤", "可测试性"),
)
# ①段存在性断言词 / ②段「无重复」断言词 / ②段查询动词——词形取
# replay_plan1_sub3 vio1/vio4 真实载荷逐字（「经核实…均存在/可直接复用/
# 也在场」；「不会有现成的同功能实现/需新建」）。
_FEASIBILITY_EXIST_CLAIM_WORDS = ("存在", "已核实", "可复用", "在场")
_FEASIBILITY_DUP_CLAIM_WORDS = (
    "无重复",
    "无同功能",
    "没有同功能",
    "需新建",
    "不会有",
    "无既有",
)
_FEASIBILITY_DUP_QUERY_VERBS = (
    "codegraph",
    "Grep",
    "grep",
    "查询",
    "返回",
    "搜索",
    "检索",
    "查得",
)
_FEASIBILITY_STATE_WORDS = ("可行", "假设", "证伪剔除")


def _feasibility_segment(a: str, start_kws: tuple, end_kws: tuple) -> str | None:
    """取 [start, end) 段（圈码/条目名定位）。start 缺 -> None（该段不扫）。"""
    i = min((a.find(k) for k in start_kws if a.find(k) >= 0), default=-1)
    if i < 0:
        return None
    ends = [a.find(k, i + 1) for k in end_kws if a.find(k, i + 1) > i]
    return a[i : min(ends)] if ends else a[i:]


def _check_feasibility_verification_trace(qa: list, *_ctx) -> str | None:
    """feasibility_verification_trace：可行性验证五项核验留痕扫描（plan:1 子3 专属）。

    动机（p:1#3 framing 反转 v1 重放，designs/plan1-sub3-gate-framing-design.md）：
    三条负判定判据在默认-PASS framing 下崩牙——缺项 vio5 2/6、①段裸存在断言
    vio1 3/6（拦对轮全引错条款=错理由拦对）、②段无查询「需新建」vio4 2/6
    （㊳：负判定=合法留痕缺席才违规，judge 不主动查必崩需下沉）。词形可判
    子项（#30 ⑭，同 terrain/baseline_tool_trace 范式）切出下沉零方差生产墙，
    judge 只留语义残项（训练记忆冒充/留痕与自述矛盾/查询不对题/笼统趋同）。
    ㊴ 复用判定：terrain_tool_trace 不可复用——它扫整条回答（v1 载荷 ④段有
    file:line 即放行），本族违规须按 ①/② 段级切分（触发粒度不对齐=建变体）。
    **非 db 依赖**：只查 qa 文本词形（留痕投影），不读 codegraph db（⑯-safe）；
    「符号是否真实存在本仓」由模型侧 codegraph 动作保证，机械/judge 均不复述
    db 内容（design §0 判材边界）。
    宁纵勿枉：只扫含圈码①的结构化回答（散述形态交 judge 方框兜底）；①段含
    「无需存在性核实」（新文件合法声明）或「不适用」跳过；file:line 定位
    （`xxx.py:N`）本身即合法出处不拦——只拦「断言词在场且 file:line/工具动词
    /查询动词全缺席」的裸断言。
    """
    for item in qa:
        q, a = str(item.get("q", "")), str(item.get("a", ""))
        if "①" not in a:
            continue
        missing = [g[1] for g in _FEASIBILITY_ITEM_GROUPS if not any(k in a for k in g)]
        if missing:
            return (
                f"「{q[:16]}…」五项核验缺项（{'/'.join(missing)}）"
                "——①-⑤ 逐项留痕是形式要件：补该项核验留痕，"
                "或显式声明「不适用+原因」"
                # p1-sub3-cost 修1（B1 轮 7 连拒实证）：报错即返工指令——
                # 组织形态不写进报错，模型按核验项拆 q 反复撞墙（block 文案
                # =返工指令原则，weak-model-mechanisms）。
                "（组织形态=每候选一对 q/a，该候选的答案内①-⑤圈码齐备；"
                "按核验项拆 q 的散列组织不满足本校验）"
            )
        if not any(w in a for w in _FEASIBILITY_STATE_WORDS):
            return (
                f"「{q[:16]}…」缺三态标注——逐候选标注"
                "「可行（附出处）/假设（置信度+错误时影响）/证伪剔除（附理由）」"
            )
        seg1 = _feasibility_segment(a, ("①",), ("②", "重复造轮子", "重复实现"))
        if seg1:
            # 「存在性」是段首条目名而非断言——剥掉再扫断言词（防条目名自带
            # 「存在」把无断言段误判为裸断言）。
            body1 = seg1.replace("存在性", "")
            if (
                "无需存在性核实" not in seg1
                and "不适用" not in seg1
                and any(w in body1 for w in _FEASIBILITY_EXIST_CLAIM_WORDS)
                and not _TERRAIN_FILELINE_RE.search(seg1)
                and not any(k in seg1 for k in _CONSTRAINT_TOOL_TRACE_KEYWORDS)
            ):
                return (
                    f"「{q[:16]}…」①存在性核验声称存在/已核实却无出处"
                    "（无 file:line、无 codegraph/Read 等工具留痕）"
                    "——声称存在无出处=编造：补 file:line 定位或工具查询留痕，"
                    "新文件则声明「无需存在性核实」"
                )
        seg2 = _feasibility_segment(a, ("②", "重复造轮子", "重复实现"), ("③", "影响面"))
        if (
            seg2
            and any(w in seg2 for w in _FEASIBILITY_DUP_CLAIM_WORDS)
            and not any(k in seg2 for k in _FEASIBILITY_DUP_QUERY_VERBS)
        ):
            return (
                f"「{q[:16]}…」②声称无同功能实现/需新建却无 codegraph/Grep "
                "查询留痕——重复实现漏检：补同功能查询留痕（查询方式+返回摘要，"
                "含「返回 0 个」空结果）"
            )
    return None


# plan:2 子1 要素清单代码符号形（element_quote_trace 用）：
# 要素条目形如 `summary/generate_factor_summary_report.py` file→function。
# 与 _TERRAIN_SYMBOL_RE 同形；要点=本 mech 判「要素原文引用」是否在场（judge
# 读不到 design.md 文件，原文『…』引用是核对保真度的唯一材料），非工具留痕。
_ELEMENT_SYMBOL_RE = re.compile(r"[A-Za-z0-9_./-]+\.py(?::\d+)?")


def _check_element_quote_trace(qa: list, *_ctx) -> str | None:
    """element_quote_trace：要素清单原文引用留痕扫描（plan:2 子1 专属）。

    动机（plan:2#1 framing 反转 v1 重放，designs/plan2-sub1-gate-framing-design.md）：
    形式要件「每条附出处且要素原文引用进 trace 正文」在默认-PASS framing 下 judge
    侧 vio4 2/6——judge 看到要素条目有出处行号（design.md:12）就 rubber-stamp 放过
    无『』原文引用的条目（㉖ 注意力方差，同 p1-sub1 vio2 / u:3#2 vio1 型）。词形可判
    子项（#30 ⑭）：「要素条目引用了代码符号形（.py）却无任何『』原文引用或『原文』
    字样」切出下沉零方差生产墙。
    宁纵勿枉：只扫引用了代码符号形（.py）的答案（要素清单专属——验收包 SC ID/
    假设 H1 无 .py 不触发）；答案含『』或「原文」字样即放过（原文引用在场）；
    整条答案任一要素带原文引用即放过（viol 的 E4 裸但 E1-E3 有原文引用→mech 放过
    ，静默新增的「个别条目裸」交 judge 判，本 mech 只做「全清单无原文」的墙）。
    """
    for item in qa:
        a = str(item.get("a", ""))
        if not _ELEMENT_SYMBOL_RE.search(a):
            continue
        if "『" in a or "原文" in a:
            continue
        return (
            f"「{str(item.get('q', ''))[:16]}…」要素清单条目引用了代码符号"
            "（.py）却无任何 design.md 原文引用（『…』/『原文』）——要素原文"
            "未引用进 trace 正文，judge 无从核对保真度：补『…』原文片段引用"
        )
    return None


# plan:3 子1 需求清单代码符号形（need_quote_trace 用，v2.106）：
# 与 _ELEMENT_SYMBOL_RE 同形复用（plan:2#1 element_quote_trace 同款判面，
# 输入锚从 design.md 换 plan.md）——本 mech 判「需求原文引用」是否在场
# （judge 读不到 plan.md 文件，原文『…』引用是核对保真度的唯一材料）。
_NEED_SYMBOL_RE = _ELEMENT_SYMBOL_RE


def _check_need_quote_trace(qa: list, *_ctx) -> str | None:
    """need_quote_trace：需求清单原文引用留痕扫描（plan:3 子1 专属）。

    动机（plan:3#1 framing 反转 v1/v3 重放，designs/plan3-sub1-gate-framing-design.md）：
    形式要件「每条附任务 ID 出处且 plan.md 原文引用进 trace 正文」在默认-PASS
    framing 下 judge 侧 vio4 1-2/6——judge 看到需求条目有出处行号（plan.md:12）
    就 rubber-stamp 放过无『』原文引用的条目（㉖ 注意力方差，与 plan:2#1
    element_quote_trace 同根因同判面）。词形可判子项（#30 ⑭）：「需求条目引用了
    代码符号形（.py）却无任何『』原文引用或『原文』字样」切出下沉零方差生产墙。
    宁纵勿枉：只扫引用了代码符号形（.py）的答案（需求清单专属）；答案含『』或
    「原文」字样即放过（原文引用在场）；整条答案任一需求带原文引用即放过（vio2 的
    N3 裸但 N1/N2 有原文引用→mech 放过，静默新增的「个别条目裸」交 judge 判，
    本 mech 只做「全清单无原文」的墙）。
    """
    for item in qa:
        a = str(item.get("a", ""))
        if not _NEED_SYMBOL_RE.search(a):
            continue
        if "『" in a or "原文" in a:
            continue
        return (
            f"「{str(item.get('q', ''))[:16]}…」需求清单条目引用了代码符号"
            "（.py）却无任何 plan.md 原文引用（『…』/『原文』）——需求原文"
            "未引用进 trace 正文，judge 无从核对保真度：补『…』原文片段引用"
        )
    return None


# plan:4 子1 控制结构输入清单代码符号形（epc_quote_trace 用，v2.115）：
# 与 _ELEMENT_SYMBOL_RE 同形复用（plan:2#1 element_quote_trace / plan:3#1
# need_quote_trace 同款判面，输入锚扩为四源聚合）--本 mech 判「四源原文引用」
# 是否在场（judge 读不到 design.md/plan.md/understand.md/evidence 四源文件，
# 原文『…』引用是核对保真度的唯一材料）。
_EPC_SYMBOL_RE = _ELEMENT_SYMBOL_RE


def _check_epc_quote_trace(qa: list, *_ctx) -> str | None:
    """epc_quote_trace：控制结构输入清单原文引用留痕扫描（plan:4 子1 专属）。

    动机（plan:4#1 framing 反转 v1 重放，designs/plan4-sub1-gate-framing-design.md）：
    形式要件「每条附源出处且四源原文引用进 trace 正文」在默认-PASS framing 下 judge
    侧 vio4 2/6--judge 看到清单条目有出处行号（plan.md:12）就 rubber-stamp 放过
    无『』原文引用的条目，且方框四 per-class 误读致 vio3 3/6 被方框四 distractor
    吞（㉖ 注意力方差，与 plan:2#1/plan:3#1 同根因同判面）。词形可判子项（#30 ⑭）：
    「清单条目引用了代码符号形（.py）却无任何『』原文引用或『原文』字样」切出下沉
    零方差生产墙。
    宁纵勿枉：只扫引用了代码符号形（.py）的答案（控制结构输入清单专属--验收包 SC ID/
    假设 H1 无 .py 不触发）；答案含『』或「原文」字样即放过（原文引用在场）；
    整条答案任一清单项带原文引用即放过（vio2 的 ⑤ 裸但 ①-④ 有原文引用->mech 放过
    ，静默新增的「个别条目裸」交 judge 判，本 mech 只做「全清单无原文」的墙）。
    """
    for item in qa:
        a = str(item.get("a", ""))
        if not _EPC_SYMBOL_RE.search(a):
            continue
        if "『" in a or "原文" in a:
            continue
        return (
            f"「{str(item.get('q', ''))[:16]}…」控制结构输入清单条目引用了代码"
            "符号（.py）却无任何四源原文引用（『…』/『原文』）--四源原文"
            "未引用进 trace 正文，judge 无从核对保真度：补『…』原文片段引用"
        )
    return None


# plan:2 子2 切分排序（dependency_order_trace / element_coverage_trace /
# single_phase_argument 用，v2.104 framing 反转三 mech）：
# 三 mech 各承接一个 default-PASS judge 判不稳的判据--vio2 排序违依赖（跨参照：
# 声明依赖 vs 拓扑序方向，㊻ 系统性放行型）/ vio4 丢要素（跨步：S1 要素 vs S2
# 承接，clean 误伤与 vio 漏判跷跷板）/ vio5 单阶段无论证（负判定缺席型，㊳）。
# 均纯 token 扫描（⑯-safe，无 db 依赖）；element_coverage_trace 读 S1 evidence
# 是文件读非 db（S1 缺失=放过交 judge，非双失）。
_DEPENDENCY_PAIR_RE = re.compile(
    r"([A-Z]\d+)\s*[（(]\s*依赖\s*([A-Z]\d+)\s*[)）]"  # U3（依赖 U2）
    r"|([A-Z]\d+)\s*依赖\s*([A-Z]\d+)"  # U3 依赖 U2
)
_TOPO_ORDER_RE = re.compile(r"拓扑序\s*([A-Z\d\s\->]+)")


def _check_dependency_order_trace(qa: list, *_ctx) -> str | None:
    """dependency_order_trace：拓扑序方向 vs 声明依赖自洽扫描（plan:2 子2 专属）。

    动机（plan:2#2 framing 反转 v1-v4 重放，designs/plan2-sub2-gate-framing-design.md）：
    「排序违反依赖=被依赖者排后」是跨参照判据（声明依赖 vs 拓扑序方向逐对核对），
    默认-PASS 下 judge v1 2/6->v2/v4 3-4/6 系统性放行（㊻：弱 judge 把「U3->U2->U1」
    读成有效序列不核对方向）。词形可判子项（#30 ⑭）：「声明 X 依赖 Y 却拓扑序 X 在
    Y 前」切出下沉零方差生产墙。
    宁纵勿枉：无拓扑序 / 无依赖声明 / 单元不在序中=放过交 judge（只做清晰情形的墙）。
    """
    all_text = " ".join(str(item.get("a", "")) for item in qa)
    m = _TOPO_ORDER_RE.search(all_text)
    if not m:
        return None
    order = re.findall(r"[A-Z]\d+", m.group(1))
    if len(order) < 2:
        return None
    pos = {u: i for i, u in enumerate(order)}
    pairs = []
    for mm in _DEPENDENCY_PAIR_RE.finditer(all_text):
        x = mm.group(1) or mm.group(3)
        y = mm.group(2) or mm.group(4)
        if x and y:
            pairs.append((x, y))
    if not pairs:
        return None
    for x, y in pairs:  # X 依赖 Y -> Y 须在 X 前（pos[Y] < pos[X]）
        if x in pos and y in pos and pos[y] > pos[x]:
            return (
                f"排序违反依赖：{x} 依赖 {y}，但拓扑序中 {x}（位 {pos[x]}）排在 "
                f"{y}（位 {pos[y]}）前--被依赖者排后；拓扑序须被依赖者先行"
                f"（{y} 在 {x} 前）"
            )
    return None


def _check_element_coverage_trace(qa: list, project_root, name) -> str | None:
    """element_coverage_trace：要素 ID 覆盖跨步核对（plan:2 子2 专属）。

    动机（plan:2#2 framing 反转，同上设计）：「要素 ID 覆盖有漏=丢要素」是跨步一致性
    （S1 子1 要素清单 vs S2 子2 单元承接），默认-PASS 下 judge v1 6/6->v3/v4 1-3/6
    跷跷板（强措辞判 vio4 5/6 但伤 clean、弱措辞保 clean 但 vio4 漏判=⑤ 跷跷板实锤）。
    下沉生产墙：读 S1 取要素 ID 集，核对每个在 S2 出现。
    宁纵勿枉：S1 缺失（无前序记录）=放过交 judge（非双失：judge 仍可判）；S2 无要素
    ID 引用=放过（可能用别名，交 judge）。
    """
    s1 = read_evidence_for_step(project_root, name, 1, "TaskBreakdown")
    if not s1:
        return None
    s1_ids = set(re.findall(r"\bE\d+\b", s1))
    if not s1_ids:
        return None
    s2_text = " ".join(str(item.get("a", "")) for item in qa)
    s2_ids = set(re.findall(r"\bE\d+\b", s2_text))
    missing = s1_ids - s2_ids
    if missing:
        return (
            f"要素 ID 覆盖有漏：S1（子1）要素 {sorted(missing)} 在本步（子2）无单元"
            "承接--每个 S1 要素 ID 须至少一个单元承接"
        )
    return None


_SC_ID_RE = re.compile(r"\bSC\d+\.\d+\b")


def _check_sc_coverage_trace(statements: list, project_root, name) -> str | None:
    """sc_coverage_trace：验收包映射漏项跨步核对（plan:2 子4 专属，statements 首个 mech）。

    动机（plan:2#4 framing 反转 v2.109，designs/plan2-sub4-gate-framing-design.md）：「验收包
    映射漏项=SC ID 未被任何 acceptance_map 承接」是跨步一致性（子1 验收包清单 SC ID
    集合 vs 子4 statements 全部 acceptance_map SC ID 集合差集），默认-PASS 下 judge
    措辞判不稳且与 clean 误伤跷跷板（⑤ 实锤：强措辞伤 clean[judge 发明映射归属要件]、
    弱措辞漏判 vio4[跨步枚举不可靠]）。下沉生产墙：读子1 取验收包 SC ID 集，与子4
    全部 acceptance_map 的 SC ID 集做差集，差集非空即拒。
    statements 侧 mech_checks 首个落地（u:2#4 预留「statements 侧注册表」独立项，
    #30 ⑰ 的解）--statements 格式步此前 mech_checks 循环不执行，本注册表补上。
    宁纵勿枉：子1 缺失（无前序记录）/子1 无 SC ID/子4 无 acceptance_map SC ID=放过
    交 judge（非双失：judge 仍可判残留语义面）；个别单元「无直接验收包承接」合法
    （只判全局覆盖，不判单元级）。
    """
    s1 = read_evidence_for_step(project_root, name, 1, "TaskBreakdown")
    if not s1:
        return None
    s1_ids = set(_SC_ID_RE.findall(s1))
    if not s1_ids:
        return None
    covered: set = set()
    has_am = False
    for it in statements:
        am = (it.get("fields") or {}).get("acceptance_map")
        if not isinstance(am, str):
            continue
        has_am = True
        covered.update(_SC_ID_RE.findall(am))
    if not has_am:
        return None
    missing = s1_ids - covered
    if missing:
        return (
            f"验收包映射漏项：子1 验收包 {sorted(missing)} 在本步（子4）无任何项 "
            "acceptance_map 承接--子1 每个 SC ID 须至少一项 acceptance_map 承接"
            "（个别单元「无直接验收包承接」合法，只判全局覆盖）"
        )
    return None


# plan:3 子3 注册表能力名提取：S2 能力盘点① skill 注册表里「反引号名+（列表行）」
# 标注的能力名（plan:3#3 专属 mech）。「（列表行）」是注册表条目的固定出处标注，
# 用它排除 S2 里其它反引号 token（内置工具集/路径如 /home/.../codegraph）。
_REGISTRY_CAPABILITY_RE = re.compile(r"`([^`]+)`（列表行）")


def _check_binding_residue_trace(qa, project_root, name) -> str | None:
    """binding_residue_trace：无绑定能力残留跨步核对（plan:3 子3 专属）。

    动机（plan:3#3 framing 反转 v2.110，designs/plan3-sub3-gate-framing-design.md）：
    「无绑定能力残留=过载」（S2 注册表枚举的能力名既无绑定也无不加载）是跨步一致性
    （S2 能力盘点注册表①枚举集 vs S3 匹配选型全答案出现集差集），默认-PASS 下 judge
    v1 1/6（显式「检测：逐条检查 S2 注册表…」遍历指令也被忽略，跨步枚举不可靠=
    plan:2#4 sc_coverage_trace 同根因，⑤/② 差集形下沉）。下沉生产墙：读 S2 取注册表①
    能力名集（反引号+（列表行）标注），核对每个在本步全答案出现（绑定或不加载任一生效）。
    宁纵勿枉：S2 缺失（无前序记录）/S2 无（列表行）标注能力名/某名提取失败=放过交 judge
    （非双失）；覆盖核验用子串包含（能力名在本步任何答案出现即视为已处理，含被否候选/讨论
    场景——残留=完全未被提及）。
    """
    s2 = read_evidence_for_step(project_root, name, 2, "CapabilityToolSelection")
    if not s2:
        return None
    registry = set(_REGISTRY_CAPABILITY_RE.findall(s2))
    if not registry:
        return None
    s3_text = " ".join(str(item.get("a", "")) for item in qa)
    missing = sorted(n for n in registry if n not in s3_text)
    if missing:
        return (
            f"无绑定能力残留：S2（子2）注册表枚举的能力 {missing} 在本步（子3）"
            "无绑定且无不加载声明--每个注册表能力名须绑定需求或显式不加载"
            "（完全未被提及=残留）"
        )
    return None


# 被否候选/被否形态标签：ADR 理由传导核对的触发面（plan:1#5 专属）。
# 「候选X」「被否形态=」「被否路径=」三形态覆盖生产 rejected 字段的命名习惯。
_REJECTED_LABEL_RE = re.compile(r"候选\s*[A-Za-z0-9]|被否形态|被否路径")

# 「为何被否」的解释性内容词形：理由源开放（gate 方框五「列举是示例不是封闭清单」的
# 机械侧对偶）——收工程解释常用词，任一在场即视为已附理由。
_REJECTED_RATIONALE_RE = re.compile(
    r"理由|因为|由于|净分|触发|不复用|复用度|影响面|镀金|迁移|成本|已在册|"
    r"未实测|不可|无法|风险|H\d|impact|callers|design\.md"
)


def _check_rejected_rationale_trace(statements: list, project_root, name) -> str | None:
    """rejected_rationale_trace：ADR 否决理由传导核对（plan:1 子5 专属）。

    动机（plan:1#5 framing 反转 v2.116，designs/plan1-sub5-gate-framing-design.md）：
    「rejected 只列被否名单、逐项 ADR 理由全丢」是**缺席型负判定**（㊳：合法留痕缺席
    才违规）。基线从严 gate 下该载荷 6/6 但**零轮引对条款**（全靠 clean 同源的复合句
    误伤词形接住=㉖「错理由拦对」教科书实例）；反转把误伤词形合法化后，v1 5/6 -> v2
    4/6 -> v3 4/6 卡在 ㉗ 抖动带（判词全引对条款、放行轮为纯注意力方差=judge 不做
    「字段内有无解释」的逐项扫描）。按 ㉗ 区分线（judge 侧 4-5/6 抖动=下沉触发位）
    切词形可判子项（#30 ⑭）下沉生产墙。

    检测：逐项读 fields.rejected，凡含被否候选名/被否形态标签（_REJECTED_LABEL_RE）
    却同栏不含任何解释性词形（_REJECTED_RATIONALE_RE）即拒。
    宁纵勿枉：无 fields/无 rejected 键/rejected 显式「无」（本项无被否路径）/不含被否
    标签（自由表述的 ADR）=放过交 judge（非双失：gate 方框五仍在，judge 判残留语义面
    「理由与子4 结论矛盾」）。
    """
    for i, item in enumerate(statements):
        if not isinstance(item, dict):
            continue
        rej = (item.get("fields") or {}).get("rejected")
        if not isinstance(rej, str) or not rej.strip():
            continue
        if not _REJECTED_LABEL_RE.search(rej):
            continue  # 无被否标签（如显式「无」）——不触发
        if _REJECTED_RATIONALE_RE.search(rej):
            continue  # 同栏已附解释性内容
        return (
            f"statements[{i}].fields.rejected 只列被否名单无否决理由（ADR 丢失）："
            f"「{rej[:40]}」——逐候选须附「为何被否」的说明（引子3 核验事实或子4 "
            "Pugh 净分/硬规则触发/影响面/复用度任一项即可，理由源不限）"
        )
    return None


# plan:3 子5 不加载清单条目名提取：子3 最小集「不加载清单」段里反引号包裹的
# 能力名（plan:3#5 专属 mech）。锚=「不加载清单」字样，取其后文段的反引号 token，
# 排除 S3 绑定提案段（B1-B5）的同名 token--不加载清单段是子3 a2 最小集声明，
# 与绑定提案段分离。
_NO_LOAD_LIST_RE = re.compile(r"不加载清单[^`]*((?:`[^`]+`[^`]*)+)")


def _check_no_load_trace(statements: list, project_root, name) -> str | None:
    """no_load_trace：不加载清单条目跨步核对（plan:3 子5 专属）。

    动机（plan:3#5 framing 反转 v2.117，designs/plan3-sub5-gate-framing-design.md）：
    「子3 最小集有显式不加载清单，本步 statements 静默丢失该清单」是跨步一致性
    （子3 不加载清单条目集 vs 子5 statements 全文出现集差集），缺席型负判定
    （㊳：合法留痕缺席才违规）。default-PASS 下 judge v2/v3 仅 1-3/6（5/6 空
    reason PASS--judge 不做「列出前序清单->逐项检索」的跨步扫描，⑭ 注意力方差，
    同 binding_residue_trace / sc_coverage_trace 族）。词形可判子项（#30 ⑭）
    下沉生产墙：读子3 取不加载清单条目名集，核对每个在本步 statements 全文出现。
    宁纵勿枉：子3 缺失（无前序记录）/子3 无「不加载清单」字样（确无清单）/
    提取失败=放过交 judge（非双失：gate 方框四仍在，judge 判残留语义面）。
    覆盖核验用子串包含（条目名在本步任一 statement 的 text/fields 出现即视为承载，
    合并一条或逐项拆均合规--gate 方框四「四件合并一条或逐项拆分均合规」对偶）。
    """
    s3 = read_evidence_for_step(project_root, name, 3, "CapabilityToolSelection")
    if not s3:
        return None
    m = _NO_LOAD_LIST_RE.search(s3)
    if not m:
        return None  # 子3 确无不加载清单声明--放过
    names = set(re.findall(r"`([^`]+)`", m.group(1)))
    if not names:
        return None
    blob = " ".join(
        str(it.get("text", ""))
        + " "
        + str(it.get("boundary", ""))
        + " "
        + " ".join(str(v) for v in (it.get("fields") or {}).values())
        for it in statements
        if isinstance(it, dict)
    )
    missing = sorted(n for n in names if n not in blob)
    if missing:
        return (
            f"不加载清单丢失：子3（子3）最小集不加载清单 {missing} 在本步（子5）"
            "statements 全文无任一条目名出现、且无「本包无不加载项」声明"
            "--每个不加载清单条目须在 statements 承载（text 或 no_load 字段，"
            "合并一条或逐项拆分均合规）"
        )
    return None


# plan:3 子5 假设传导核对：子4 假设项的置信度×影响须在本步 statements 携带
# （plan:3#5 专属 mech）。假设标签形复用 _ASSUMPTION_LABEL_RE（子4 三态标注）；
# 假设携带的词形痕迹=「置信度」或「影响」任一在场（与 assumption_completeness_trace
# 同款词形，子4 假设项汇总/三态标注均含「置信度×影响」结构化标注）。
_ASSUMPTION_CARRY_RE = re.compile(r"置信度|影响")


def _check_assumption_propagation_trace(
    statements: list, project_root, name
) -> str | None:
    """assumption_propagation_trace：假设项置信度×影响跨步传导核对
    （plan:3 子5 专属）。

    动机（plan:3#5 framing 反转 v2.117，designs/plan3-sub5-gate-framing-design.md）：
    「子4 三态标注的假设项在本步被抹去或淡化（置信度×影响丢失，『已确认无风险』
    式改写）」是跨步一致性（子4 假设项集 vs 子5 statements 携带集差集），缺席型
    负判定（㊳）。default-PASS 下 judge v2/v3 仅 2-5/6（PASS 轮空 reason--judge
    不做「列出子4 假设->逐项检索置信度×影响」的跨步扫描，⑭ 注意力方差，同族）。
    下沉生产墙：读子4 检测假设标签形（_ASSUMPTION_LABEL_RE），若有则核对
    本步 statements 全文含「置信度」或「影响」词形痕迹。
    宁纵勿枉：子4 缺失/子4 无假设标签（确无假设）=放过交 judge（非双失：
    gate 方框五仍在，judge 判残留语义面「假设与子4 结论矛盾」）；语义等价转述
    仍含「置信度/影响」词形即合规（假设传导的固定结构化标注）。
    """
    s4 = read_evidence_for_step(project_root, name, 4, "CapabilityToolSelection")
    if not s4 or not _ASSUMPTION_LABEL_RE.search(s4):
        return None  # 子4 确无假设项--放过
    blob = " ".join(
        str(it.get("text", ""))
        + " "
        + str(it.get("boundary", ""))
        + " "
        + " ".join(str(v) for v in (it.get("fields") or {}).values())
        for it in statements
        if isinstance(it, dict)
    )
    if not _ASSUMPTION_CARRY_RE.search(blob):
        return (
            "假设传导丢失：子4（子4）三态标注的假设项（含置信度×影响）在本步"
            "（子5）statements 全文无「置信度」或「影响」词形痕迹--假设项须在"
            "boundary 或 fields 原样携带置信度×影响（「已确认无风险」式定性句"
            "不算携带，语义等价转述仍含置信度/影响词形即合规）"
        )
    return None


# ---------- 改动规格锚点验真（up-change-spec-gate，2026-08-25，
# designs/up-change-spec-gate-design.md）----------
# 用户决议：u/p（特别是 p）完成的唯一验收标准 = 改动规格五要素（文件/类/
# 方法/行号/怎么改）明确且准确。「明确」=语法齐备（本层①），「准确」=
# codegraph 机械三验（本层②③④——judge 判不了真值，§3.5 #1 三层分工；
# judge gate 零语义变更，免重放回归义务）。定位=归一化转录失真兜底：
# codegraph 新鲜度前置归 plan:1#1、锚点存在性核验归 plan:1#3/plan:2#3/
# u:1 子2b 取证步，前序已验真 → 归一化步转录编造/写错才会被本层拒，
# 正常路径零拦截。语法真源 = _CHANGE_SPEC_RULE/_ROOT_CAUSE_LINE_RULE
# （dl_flow_nodes 单源常量，purpose/gate/selfcheck/报错文案四处同文）。

# 条目行常见列表前缀（「- 」「①」「1. 」）——解析器宽容 defense-in-depth
# （v2.65 先例：格式归脚本，模型写的合理形态不该被死板正则误伤）。
_LIST_PREFIX_RE = re.compile(r"^(?:[-*•]|[0-9]+[.、)）]|[①-⑨])\s*")

# 可选行首类型前缀（「改=」「删=」「增=」）——与 _LIST_PREFIX_RE 同款宽容；
# 剥离后与（kind）交叉核对（_verify_change_spec_entry）。
_KIND_PREFIX_RE = re.compile(r"^(?P<pk>改|删|增)=\s*")

# 注记条目词形（change-spec-disclosure-round2，2026-08-26，
# designs/change-spec-disclosure-round2-design.md）：模型把决策注记/被否方案
# 当 change_list 条目写（Run 3 plan:1#5 实跑 3 连拒）——只在「语法不合」
# 分支分诊（合法条目走不到，不误伤含「被否」的合法改法文本）。
_NOTE_ENTRY_RE = re.compile(r"^（|注记|被否|假想|承接链|不执行|记录用途")

# 非代码文件后缀（codegraph 不索引）——symbol 查无报错指路「symbol 填 - +
# 行号锚定」（三轮实跑 render_factor_card/bt_mock/_ann_pct 反复误用）。
_NONCODE_FILE_SUFFIXES = frozenset(
    {
        ".html",
        ".htm",
        ".j2",
        ".jinja",
        ".md",
        ".txt",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".cfg",
    }
)

_CHANGE_SPEC_ENTRY_RE = re.compile(
    r"^(?P<file>[\w./-]+\.\w{1,10}):(?P<symbol>[A-Za-z_][\w.]*|-)"
    r"(?::L(?P<l1>\d+)(?:-(?P<l2>\d+))?)?"
    r"（(?P<kind>改|删|增)(?:@(?P<anchor>[^）]+))?）"
    r"[：:]\s*(?P<how>\S.*)$"
)

# 改法纯动词独占词表（无宾语无改前改后=「怎么改」要素空壳）。
_HOW_PURE_VERB_RE = re.compile(
    r"^(优化|修复|调整|改进|重构|修改|处理|完善|更新|改动|改造|迭代|增强)一下?吧?[。．.!！]?$"
)


def _git_tracked_files(project_root: Path) -> set[str] | None:
    """git ls-files 全集（锚点验真用）；失败 -> None（跳过文件层核验，
    宁纵勿枉——与 _implementation_nouns 降级先例同款，不算 silent fallback）。"""
    try:
        res = subprocess.run(
            ["git", "ls-files"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if res.returncode != 0:
        return None
    return set(res.stdout.splitlines())


def _file_line_count(path: Path) -> int | None:
    try:
        with path.open("rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return None


def _codegraph_symbol_spans(
    project_root: Path, file: str, symbol: str
) -> list[tuple[int, int]] | None:
    """symbol 在 codegraph db 的行号跨度集。

    None = db 缺失/索引过期于该文件/查询失败（跳过验真，宁纵勿枉——
    归一化步材料边界禁步内新取证，模型无合法刷索引路径，拒=逼编造，
    §3.5 #7）；[] = db 健康但该 file 内查无此 symbol（硬拒）。
    qualified_name 分隔符双形态（Class::method / Class.method）都认；
    带点 symbol 尾名兜底（模块前缀省略形态）。
    """
    db = project_root / ".codegraph" / "codegraph.db"
    if not db.exists():
        return None
    src = project_root / file
    try:
        if src.exists() and src.stat().st_mtime > db.stat().st_mtime:
            return None  # 索引过期于该文件
    except OSError:
        return None
    try:
        import sqlite3

        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT start_line, end_line FROM nodes"
                " WHERE file_path=? AND kind IN ('class','function','method')"
                " AND (name=? OR qualified_name=? OR qualified_name=?)",
                (file, symbol, symbol, symbol.replace(".", "::")),
            ).fetchall()
            if not rows and "." in symbol:
                rows = con.execute(
                    "SELECT start_line, end_line FROM nodes"
                    " WHERE file_path=? AND kind IN ('class','function','method')"
                    " AND name=?",
                    (file, symbol.split(".")[-1]),
                ).fetchall()
        finally:
            con.close()
    except (sqlite3.Error, OSError):
        return None
    return [(int(a), int(b)) for a, b in rows]


def _verify_anchor_parts(
    project_root: Path,
    file: str,
    symbol: str,
    l1: str | None,
    l2: str | None,
    *,
    context: str,
) -> str | None:
    """锚点三验共享核心（改动规格 改/删 路径 + u 侧根因行复用）。

    context = 报错文案里的对象称呼（「改动规格条目」/「根因行」）。
    file 存在性由调用方先判（本函数不查 tracked）；这里验：行号 ≤ 文件
    当前行数；symbol ≠「-」时 codegraph 查有 + 行号与 symbol 跨度有交集
    （交集判而非严格包含——索引 stale 容差，design §8 已知边界）。
    """
    # 空白符锚点 = 必然自然语言（symbol 名无空格；change-spec-field-contract-
    # disclosure，2026-08-26——Run 3 实锤模型把出处说明写进锚点位）——
    # 报错从笼统「查无」精确为三形态指引。CJK 无空格 symbol 不拦（Unicode
    # 合法标识符，宁纵勿枉）。
    if re.search(r"\s", symbol):
        return (
            f"{context}「{symbol[:40]}」是自然语言描述（含空白符）——锚点只接受"
            "三形态：现有 symbol 名 / L 行号 / 文件尾；出处说明写 boundary 不写锚点"
        )
    n = _file_line_count(project_root / file)
    if l1 is not None and n is not None and int(l1) > n:
        return (
            f"{context}行号 L{l1} 超出 {file} 当前总行数（{n}）——"
            "行号须落在文件实存行内：回前序留痕/重读该文件取真实行号后改写"
        )
    if symbol == "-":
        return None
    spans = _codegraph_symbol_spans(project_root, file, symbol)
    if spans is None:
        return None  # db 缺失/过期/失败——跳过（宁纵勿枉）
    if not spans:
        if Path(file).suffix.lower() in _NONCODE_FILE_SUFFIXES:
            return (
                f"{context}的 symbol「{symbol}」在 codegraph 索引的 {file} 内查无"
                "——codegraph 不索引该文件类型（模板/文档/数据文件），此类文件"
                "锚点 symbol 填 -、用 L<a>-<b> 行号锚定"
                f"（如 {file}:-:L10-12（改）：改前→改后要点）"
            )
        return (
            f"{context}的 symbol「{symbol}」在 codegraph 索引的 {file} 内查无"
            "——锚点须真实存在：跑 dl codebase query --symbol 核实正确符号名"
            "（类.方法 分隔符 . / :: 都认；模块级改动 symbol 填 -），"
            "或回前序留痕逐字取已核验的锚点"
        )
    if l1 is not None:
        a, b = int(l1), int(l2 or l1)
        if not any(a <= e and s <= b for s, e in spans):
            return (
                f"{context}行号 L{a}-{b} 与 {file} 的 symbol「{symbol}」索引跨度"
                f"（{spans[0][0]}-{spans[0][1]}）无交集——行号须落在 symbol 实存"
                "跨度内：重读该文件核实（行号漂移）或修正 symbol 归属"
            )
    return None


def _verify_change_spec_entry(
    line: str,
    *,
    require_lines: bool,
    tracked: set[str] | None,
    tracked_dirs: set[str],
    project_root: Path,
) -> str | None:
    """单条改动规格条目：①语法齐备 ②file ③symbol ④行号 + 改法非空壳。"""
    text = _LIST_PREFIX_RE.sub("", line.strip())
    # 可选行首类型前缀（change-spec-prefix-tolerance，2026-08-25，
    # designs/change-spec-prefix-tolerance-design.md）：_CHANGE_SPEC_RULE 旧表述
    # 「改/删=」被模型读作字面前缀（pos_annualized 实跑 19 次拒绝中 ~17 次由此），
    # 按 v2.65 宽容先例接受并与（kind）交叉核对——双声明矛盾才拒。
    pk = None
    pm = _KIND_PREFIX_RE.match(text)
    if pm:
        pk = pm.group("pk")
        text = text[pm.end() :]
    m = _CHANGE_SPEC_ENTRY_RE.match(text)
    if not m:
        if _NOTE_ENTRY_RE.search(text):
            return (
                f"改动规格条目疑似注记/说明而非改动条目：「{text[:60]}」——"
                "change_list 只写可执行改动条目；决策注记/承接链说明挪 "
                "boundary 字段、被否方案挪 rejected 字段（注记不作为条目出现）"
            )
        return f"改动规格条目语法不合：「{text[:60]}」——{_CHANGE_SPEC_RULE}"
    file = m.group("file")
    symbol = m.group("symbol")
    kind = m.group("kind")
    if pk is not None and pk != kind:
        return (
            f"改动规格条目前缀类型「{pk}」与（{kind}）矛盾——类型声明两处"
            "须一致（前缀可省，省略后类型以（）内为准）"
        )
    anchor = (m.group("anchor") or "").strip()
    how = m.group("how").strip()
    l1, l2 = m.group("l1"), m.group("l2")
    if len(how) < 4 or _HOW_PURE_VERB_RE.match(how):
        return (
            f"改动规格条目改法是空壳：「{how}」——「怎么改」须写改前→改后具体"
            "内容（改什么逻辑/加什么参数/删哪段），纯动词独占不算"
        )
    if kind != "增" and anchor:
        return (
            f"改动规格条目「{kind}」带 @锚点是语法错（锚点只属「增」）："
            f"「{text[:60]}」——{_CHANGE_SPEC_RULE}"
        )
    if kind in ("改", "删"):
        if tracked is not None and file not in tracked:
            return (
                f"改动规格条目「{kind}」的文件 {file} 不在 git 仓内（新文件配"
                f"「{kind}」=矛盾，新文件应用「增」）——核实路径或改改动类型"
            )
        if require_lines and l1 is None:
            return (
                f"改动规格条目缺行号要素：「{text[:60]}」——执行级改动点五要素"
                "（文件/类/方法/行号/怎么改）行号必给，"
                "语法=file:symbol:L<a>-<b>（改|删）：改法"
            )
        return _verify_anchor_parts(
            project_root, file, symbol, l1, l2, context="改动规格条目"
        )
    # 增：锚点验真（新 symbol 尚不存在不验，验的是落点锚）
    if tracked is not None and file not in tracked:
        parent = file.rsplit("/", 1)[0] if "/" in file else ""
        if parent and parent not in tracked_dirs:
            return (
                f"改动规格条目「增」的新文件 {file} 父目录 {parent}/ 不在 git "
                "仓内——核实目录路径（git ls-files 对齐）"
            )
        return None  # 新文件：锚点（文件内位置）无对象可验，跳过
    if not anchor:
        return (
            f"改动规格条目「增」缺 @锚点：「{text[:60]}」——增须给落点锚"
            "（增@<现有 symbol|L 行号|文件尾>），标明新代码加在哪"
        )
    if anchor == "文件尾":
        return None
    am = re.fullmatch(r"L(\d+)", anchor)
    if am:
        n = _file_line_count(project_root / file)
        if n is not None and int(am.group(1)) > n:
            return (
                f"改动规格条目「增」的锚点 {anchor} 超出 {file} 当前总行数"
                f"（{n}）——锚点行号须落在文件实存行内"
            )
        return None
    return _verify_anchor_parts(
        project_root, file, anchor, None, None, context="改动规格条目「增」锚点"
    )


def _check_change_spec_anchor(
    statements: list,
    project_root: Path,
    _name: str,
    *,
    field: str,
    require_lines: bool,
) -> str | None:
    """change_spec 锚点验真驱动（plan:1#5 change_list / plan:2#4 change_point）。

    逐 statement 取 fields[field]，每非空行须为一条合法改动规格条目。
    tracked=None（git 失败）时文件层核验跳过、codegraph 层照跑（两源独立降级）。
    """
    tracked = _git_tracked_files(project_root)
    tracked_dirs = (
        {f.rsplit("/", 1)[0] for f in tracked if "/" in f} if tracked else set()
    )
    for it in statements:
        v = (it.get("fields") or {}).get(field)
        if not isinstance(v, str) or not v.strip():
            continue  # 缺键/空键已由逐键非空校验拒，本层不重复判
        for ln in v.splitlines():
            if not ln.strip():
                continue
            err = _verify_change_spec_entry(
                ln,
                require_lines=require_lines,
                tracked=tracked,
                tracked_dirs=tracked_dirs,
                project_root=project_root,
            )
            if err:
                return err
    return None


def _check_change_list_anchor(statements: list, project_root: Path, name) -> str | None:
    """change_list_anchor_verify：plan:1#5 设计级四要素（行号豁免）。"""
    return _check_change_spec_anchor(
        statements, project_root, name, field="change_list", require_lines=False
    )


# 回归防护显式抉择的 test 文件词形（regression_guard_declared 用）：
# test_*.py / *_test.py / test_cases 或 tests 目录下文件 = 测试条目。
_TEST_FILE_RE = re.compile(
    r"(^|/)(test_[^/]*\.py|[^/]*_test\.py)$|/(test_cases|tests)/"
)
# 改动规格条目动作词（改|删|增@…）。
_CHANGE_ACTION_RE = re.compile(r"（(?:改|删|增)[^）]*）")


def _check_regression_guard_declared(
    statements: list, project_root: Path, name: str
) -> str | None:
    """regression_guard_declared：plan:2 子4 回归防护显式抉择机械核验（plan:2 子4 专属）。

    动机（designs/pattern-enum-regression-guard-design.md §3，样本=web_ui_interaction_2
    tacet+fermate 改动面无测试条目，对照组 fermate 全量有 2 条 （增） 测试项）：
    「要不要回归测试」此前是模型自由裁量——旧判据无要件，带不带测试靠发挥。
    显式裁决点化：change_point 含源码（非 test 文件）（改|删|增）条目的批次，
    二态必居其一——①带测试条目项（change_point 含 test 文件条目）；②任一项
    boundary 载「回归防护：无测试——<理由>」。触发=文件路径集合运算（机械可判
    零裁量）；纯测试/纯文档改动不触发（宁纵勿枉）；理由充分性不判（归用户
    plan 门栏审）。
    """
    has_src_change = False
    has_test_entry = False
    has_guard_decl = False
    for it in statements:
        cp = str((it.get("fields") or {}).get("change_point", ""))
        for line in cp.splitlines():
            if not _CHANGE_ACTION_RE.search(line):
                continue
            file_part = line.split(":", 1)[0]
            if _TEST_FILE_RE.search(file_part):
                has_test_entry = True
            else:
                has_src_change = True
        blob = json.dumps(it, ensure_ascii=False)
        if "回归防护" in blob:
            has_guard_decl = True
    if not has_src_change or has_test_entry or has_guard_decl:
        return None
    return (
        "回归防护显式抉择缺失——本批 change_point 含源码改动（非 test 文件）"
        "但无测试条目：二态必居其一——①加测试条目项（change_point 含 test 文件 "
        "（增|改） 条目，如 test_cases/test_x.py:-（增@文件尾）：新增回归测试）；"
        "②在任一项 boundary 载「回归防护：无测试——<理由>」。禁沉默"
        "（要不要测试是显式裁决点，理由充分性归用户 plan 门栏审）"
    )


def _check_change_point_anchor(
    statements: list, project_root: Path, name
) -> str | None:
    """change_point_anchor_verify：plan:2#4 执行级五要素（行号必给）。"""
    return _check_change_spec_anchor(
        statements, project_root, name, field="change_point", require_lines=True
    )


# fermate 轨道占位声明词形（type_label 匹配，小写化后子串判）。
_FERMATE_PLACEHOLDER_TOKEN = "fermate"


def _check_fermate_placeholder_consistency(
    statements: list, project_root: Path, name: str
) -> str | None:
    """fermate_placeholder_consistency（u:4#4 专属，u4-sub3-fermate-cut §1.2②）。

    声明-核验对的机械侧：占位声明 × state.force_fermate 双向核验——
    ①任一 statement type_label 含占位声明（fermate 词形）但本实例非 fermate
      -> 拒（full-track 谎称轨道偷工通道机械封死，judge 永不可见）；
    ②本实例是 fermate 但存在 type_label 不含占位声明的 statement
      -> 拒（漏声明/编造验收方法·时机逼回——gate 静态兜底只豁免声明项）。
    state 缺失 -> 不判（宁纵勿枉，交 judge）。
    """
    state = load_state(project_root, name)
    if state is None:
        return None
    fermate = bool(state.get("force_fermate"))
    for i, it in enumerate(statements):
        declared = _FERMATE_PLACEHOLDER_TOKEN in str(it.get("type_label", "")).lower()
        if declared and not fermate:
            return (
                f"statements[{i}] type_label 含 fermate 轨道占位声明，但本实例非 "
                "fermate 轨道（state.force_fermate 未置位）——占位声明只在 fermate"
                "（plan-only）实例合法；全量轨道按子3 验收方式设计填验收方法/时机"
            )
        if fermate and not declared:
            return (
                f"statements[{i}] type_label 缺 fermate 轨道占位声明——本实例是 "
                "fermate（plan-only）轨道（无 子3 验收方式设计），type_label 须逐条填 "
                "「fermate·plan-only」（验收包=三字段：指标/基线/阈值提案）；"
                "编造验收方法/时机或留空均当场拒"
            )
    return None


# statements 格式步的写侧机械校验注册表（Step.mech_checks 声明名 -> 检查函数，
# 签名 (statements, project_root, name)）。statements 首个 mech 注册表
# （u:2#4 预留独立项，#30 ⑰ 的解）。未注册名 = nodes 与 engine 配置漂移，fail loud。
_MECH_STATEMENTS_CHECKS = {
    "sc_coverage_trace": _check_sc_coverage_trace,
    "rejected_rationale_trace": _check_rejected_rationale_trace,
    "no_load_trace": _check_no_load_trace,
    "assumption_propagation_trace": _check_assumption_propagation_trace,
    "change_list_anchor_verify": _check_change_list_anchor,
    "change_point_anchor_verify": _check_change_point_anchor,
    "fermate_placeholder_consistency": _check_fermate_placeholder_consistency,
    "regression_guard_declared": _check_regression_guard_declared,
}


def _check_single_phase_argument(qa: list, *_ctx) -> str | None:
    """single_phase_argument：单阶段声明须附 H9 量化论证（plan:2 子2 专属）。

    动机（plan:2#2 framing 反转，同上设计）：「②单阶段不可拆论证（H9 内一次可完）」
    是负判定缺席型（㊳：合法留痕缺席才违规），默认-PASS 下 judge v1 2/6->v2 1/6->
    v3/v4 0-1/6（加强措辞反降=措辞对负判定无效，同 u:4#2 vio1 型）。词形可判子项
    （#30 ⑭）：「声明单阶段/不可拆却同段无文件数+行数量化」切出下沉零方差生产墙。
    逐答案扫描（非全量）：单阶段声明与②论证同属阶段段、同答案；全量扫描会误放过
    vio5--vio5 的 a[0]（承自 clean）含单元预算「1 文件 ~30 行」但单阶段声明在 a[2]、
    a[2] 无量化=真违规。
    宁纵勿枉：多阶段划分（无单阶段/不可拆声明）不触发。
    """
    for item in qa:
        a = str(item.get("a", ""))
        if "单阶段" not in a and "不可拆" not in a:
            continue
        if re.search(r"\d+\s*文件|\d+\s*行", a):
            continue  # 该答案含 H9 量化
        return (
            "声明「单阶段/不可拆」却同段无 H9 量化论证（文件数+行数 ≤ 上限）--"
            "②单阶段不可拆论证须在同段含量化（如「3 文件 ~75 行，H9 内一次可完」）："
            "补量化，或改走多阶段划分附断点验证方法"
        )
    return None


# plan:2 子3 锚点核验 / plan:3 子4 可用性核验 / plan:4 子3 锚点核验
# （assumption_completeness_trace 用）：三态标注中「假设」条目须含置信度+影响两要素。
# 假设标签形=「假设」后接 --/：/（ 等结构化标点（区分于「假设项」「无假设」等提及形）。
_ASSUMPTION_LABEL_RE = re.compile(r"假设\s*(?:--|[-：:（(])")


def _check_assumption_completeness_trace(qa: list, *_ctx) -> str | None:
    """assumption_completeness_trace：假设条目须含置信度+影响扫描
    （plan:2 子3 锚点核验 / plan:3 子4 可用性核验 / plan:4 子3 锚点核验共用）。

    动机（plan:2#3 framing 反转 v1-v3 重放，designs/plan2-sub3-gate-framing-design.md）：
    「假设项缺置信度或影响」是 default-PASS 下 judge 橡皮图章型（v1 1/6 -> v3 1-2/6，
    5/6 空 reason PASS--judge 不检查假设子字段，⑭ 注意力方差，同 plan:2#1 vio4 /
    plan:2#2 vio5 型）。词形可判子项（#30 ⑭）：「假设标签在场却同段无置信度或影响」
    切出下沉零方差生产墙。
    跨节点复用（v2.112 plan:3#4，designs/plan3-sub4-gate-framing-design.md）：
    plan:3 子4 的三态标注是同一形式契约（已验证/假设/证伪 + 假设附置信度×影响），
    v1 反转重放 vio3 崩 2/6 与 plan:2#3 同款负判定缺席型--按第二十四例① 三问核过：
    触发面词形同构（答案含「假设--/：/（」标签形）、放过面同构（同段含「置信度」+
    「影响/错误时」）、扫描粒度同构（逐答案），差异只在被核验对象（执行单元 vs 能力
    绑定）不落 mech 触发面-> 直接注册复用，未建变体。
    逐答案扫描：假设标签形=「假设--/：/（」；同答案须含置信度（「置信度」）与影响
    （「影响」/「错误时」）两要素。
    宁纵勿枉：无假设标签 / 「无假设」否定形（假设后接「无」）/ 「假设项」提及形
    （假设后接「项」）= 假设后非结构化标点，不匹配 _ASSUMPTION_LABEL_RE，放过交
    judge（只做清晰假设标签的墙）。
    """
    for item in qa:
        a = str(item.get("a", ""))
        if not _ASSUMPTION_LABEL_RE.search(a):
            continue
        has_conf = "置信度" in a
        has_impact = bool(re.search(r"影响|错误时", a))
        if has_conf and has_impact:
            continue
        missing = []
        if not has_conf:
            missing.append("置信度（高/中/低）")
        if not has_impact:
            missing.append("错误时影响描述")
        return (
            f"假设条目缺{'+'.join(missing)}--标注「假设」的三态条目须同段含"
            "置信度与错误时影响（如「置信度高×影响低：错误时仅新区块缺失，可回滚」）："
            "补缺失要素"
        )
    return None


def _load_atomic_questions(project_root: Path, name: str) -> list | None:
    """读子2 最新 trace 的 atomic_questions 分档清单（v2.40）。

    子2 载荷顶层 atomic_questions 键并入 record 顶层（append-trace 校验后
    落库），本函数从 evidence JSONL 直接取最新一条子2 trace 的该键——
    fetch_prompt 分档与 fetch_report_recorded tier-aware 核验共用。
    无文件 / 无子2 trace / 旧形态 trace 无该键（v2.40 前实例）-> None
    （调用方按 legacy 行为处理，不算 silent fallback：旧实例本就没有分档）。
    """
    text = read_evidence(project_root, name)
    if not text:
        return None
    pc_minor = _NODES["understand:1"].minor_key
    found = None
    for _seg, rec in _iter_trace_segments(text, 2, pc_minor):
        aq = rec.get("atomic_questions")
        if isinstance(aq, list) and aq:
            found = aq
    return found


# v2.40 取证深度分档（designs/fetch-depth-tiering-design.md）：三档枚举单源。
# none=仅内查 / light=点查锚点(≤4 curl,≤2 层源,单向) / full=五层源双向(现状)。
_FETCH_TIERS = ("none", "light", "full")

# none 档理由须含仓内取证路径指针（文件扩展名 或 file:line）——
# 机械代理判据，防空判偷懒（「我觉得仓里有」）；语义由 judge 判。
_NONE_TIER_PATH_RE = re.compile(
    r"[\w./-]+\.(?:py|md|json|jsonl|parquet|yaml|yml|toml|sql)|\d+:\d+|:\d+"
)

# full 档理由须附「仓内已查无对照基线」举证（v2.77，2026-09-01
# web_ui_interaction u:1 审计：量级合理性问题按旧枚举直落 full，外部取证
# 零承重——过度升档零成本、block 威胁只在漏取证侧，激励单向）。
# 与 none 档对称：路径指针 或「已查仓内 X 无」式声明；语义真伪（仓内是否
# 真有显而易见对照）由 judge 判（举证失真条款），机械层只查存在性。
_FULL_TIER_JUSTIFY_RE = re.compile(
    r"[\w./-]+\.(?:py|md|json|jsonl|parquet|yaml|yml|toml|sql)|\d+:\d+|:\d+"
    r"|仓内无|无对照|无同口径|已查仓内|仓内已查"
)


def _check_fetch_tier_items(items: list, qa: list | None = None) -> str | None:
    """fetch_tier_items：atomic_questions 逐项校验（u:1 子2 专属，nodes 声明）。

    逐项 {q 非空, tier∈none|light|full, tier_reason 非空；none 档理由须含
    仓内路径指针}。拿不准标 light（默认档——漂到 light 的 full 类问题由
    升档机制救回；none 漏取证是质量问题，full 是成本问题）。
    qa 形参为管道统一签名（v2.50）：本检查不用，对齐校验用。
    """
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            return (
                f"atomic_questions[{i}] 须为对象 "
                '{"q":..., "tier":"none|light|full", "tier_reason":...}'
            )
        if not isinstance(it.get("q"), str) or not it["q"].strip():
            return f"atomic_questions[{i}] 缺非空 q（与原子问题清单一一对应）"
        tier = it.get("tier")
        if tier not in _FETCH_TIERS:
            return (
                f"atomic_questions[{i}].tier 须为 none/light/full，当前 {tier!r}"
                "——拿不准标 light（默认档）"
            )
        reason = it.get("tier_reason")
        if not isinstance(reason, str) or not reason.strip():
            return (
                f"atomic_questions[{i}].tier_reason 须非空（分档理由必填，"
                "防空判偷懒——judge 会判理由与问题性质是否匹配）"
            )
        if tier == "none" and not _NONE_TIER_PATH_RE.search(reason):
            return (
                f"atomic_questions[{i}] 标 none 档但 tier_reason 无仓内取证路径"
                "指针（文件路径/file:line）——none=答案仓内可达，理由须指出"
                "去哪查（如 formatters.py:92）；指不出路径的问题不得标 none"
            )
        if tier == "full" and not _FULL_TIER_JUSTIFY_RE.search(reason):
            return (
                f"atomic_questions[{i}] 标 full 档但 tier_reason 无「仓内已查"
                "无对照基线」举证（路径指针或「已查仓内…无」式声明）——full="
                "仓内给不出对照才值得五层源综合，与 none 档对称举证，缺则当场拒"
            )
    return None


# atomic_questions 原子标签 ↔ MECE 声明对齐（v2.50，2026-08-02 u:1 子2
# 三连 block att1/att2 复盘）：att1 声明 A/B/C 三原子却交 5 条（D/E 未声明），
# judge 判两轮且 att2 判词把 att1 已修的计数原样再判（陈旧判词失真）——
# 计数/标签对齐是纯集合运算，下沉机械层后 judge 不再碰计数（§3.5 #13
# ID 传导覆盖核对同款）。锚定纪律（§3.5 #21 三原则）：声明侧只认「原子 X」
# 字面（出过事的形态），aq 侧只认首字母标签（A. / A_root 形态）；声明 <2 个
# （单一/无复合）或 aq 无标签（历史通过形态「数值正确性」）= 无机械基准，
# 交 judge——宁纵勿枉，贪宽=FP。
_DECLARED_ATOM_RE = re.compile(r"原子\s*([A-Z])")
_AQ_LABEL_RE = re.compile(r"^([A-Z])(?=[._、：:\s])")


def _check_atomic_mece_alignment(items: list, qa: list | None = None) -> str | None:
    """atomic_mece_alignment：atomic_questions 标签与 MECE 声明原子对齐。

    声明侧从 qa 的 q/a 全文提「原子 X」字母集合（「假设」标题项除外——竞争
    假设里的 H 编号不是原子声明）；aq 侧提首字母标签（A. / A_root 验证 形态）。
    违规两形态：aq 标签未在声明集（att1 的 D/E）、同标签重复（一原子多条）。
    qa=None（statements 格式步）跳过——本校验只服务 qa 格式的 u:1 子2。
    """
    if not qa:
        return None
    declared: set[str] = set()
    for it in qa:
        if "假设" in str(it.get("q", "")):
            continue
        declared.update(_DECLARED_ATOM_RE.findall(str(it.get("q", ""))))
        declared.update(_DECLARED_ATOM_RE.findall(str(it.get("a", ""))))
    if len(declared) < 2:
        return None
    labels: list[str] = []
    for it in items:
        m = _AQ_LABEL_RE.match(str(it.get("q", "")).strip())
        if m:
            labels.append(m.group(1))
    if not labels:
        return None
    extra = sorted(set(labels) - declared)
    if extra:
        return (
            f"atomic_questions 原子标签 {extra} 未在 MECE 声明 {sorted(declared)} "
            "中——与原子清单一一对应：每声明原子恰好 1 条；未声明的问题要么"
            "并入某原子的 q 文本、要么补进 MECE 清单（声明侧同步改）"
        )
    dup = sorted({x for x in labels if labels.count(x) > 1})
    if dup:
        return (
            f"atomic_questions 原子标签 {dup} 重复——一原子恰好 1 条"
            "（子问题合并进同条的 q 文本，不拆多条）"
        )
    return None


# 载荷顶层额外必填键的逐项校验注册表（extra_payload_keys 的 spec 为字符串时
# 查本表——v2.40 从「字符串+前缀」泛化到「数组+逐项校验」）。
# 未注册名 = nodes 与 engine 配置漂移，fail loud。
_MECH_EXTRA_ITEM_CHECKS = {
    "fetch_tier_items": _check_fetch_tier_items,
    "atomic_mece_alignment": _check_atomic_mece_alignment,
}


def _check_conclusion_no_speculation(v: str) -> str | None:
    """conclusion_no_speculation：u:1 子1「结论」键禁推测形态（v2.54）。

    实证（2026-08-02 tail_volume_acceleration_annualized u:1 子1 att1）：
    模型 who 项写得合规（「未自述身份…不冒充身份出处」——它知道规则），
    顶层结论却写「具体主语 = 项目维护者（推测，来源未自述身份 +
    CLAUDE.md §6 + 分支命名佐证）」——who 规则钉在 q/a 项，结论字段成
    漏网面，judge 判对但白烧一轮（钉死保判对不保写对，§3.5 #16）。
    词形取 att1 逐字（「推测」），锚定结论字段（§3.5 #21：q/a 项里
    「推测另列」是合法形态，只扫结论）；分隔度重放：att1 含 att2 不含。
    """
    if "推测" not in v:
        return None
    return (
        "「结论」含「推测」= 无出处推断进了结论——结论逐句须有出处"
        "（用户原话/会话事实），推断只能标「推测」另列在 q/a 项、不进结论；"
        "who 未自述身份就如实写「具体主语 = 未自述身份（who=未自述）」，"
        "仓库事实/分支命名不能证明当前提问者身份"
    )


# 载荷顶层字符串键的内容校验注册表（extra_payload_keys 条目第三元素，
# 前缀校验之后执行——v2.54 从「前缀合规」扩到「内容词形」）。
_MECH_EXTRA_STR_CHECKS = {
    "conclusion_no_speculation": _check_conclusion_no_speculation,
}


# 子代理 task-id 词形（harness agentId = 16-17 位小写 hex，同
# hooks/workflow_advance.py 的 _AGENT_LAUNCH_ID_RE 口径）。
# u1-sub5-cost 修1（designs/u1-sub5-cost-optimization-design.md）：旧
# `\b[0-9a-f]{16,17}\b` 把证据里的 Python float repr 小数位段当 task-id——
# amplitude_annualized step5 轮1/2 共 4 次假阳性「已派发未收录」拒
# （0.49519773767901265→49519773767901265、0.9806949806949807、
# 0.48244678899192833、0.1194141004217242，逐字取自真实 reject 消息），模型
# 为过关被迫改写合法证据数值。修复两道：
# - (?=[0-9a-f]*[a-f])：候选须含 a-f 字母——纯数字 16-17 位串排除
#   （真实 id 全含字母；纯数字真 id 概率 ~(10/16)^17，漏识别方向=交 judge
#   宁纵勿枉；float 证据在质检类载荷是常态，误报方向不可接受）；
# - (?<![0-9a-f.])：前邻不得为 hex 字符或 `.`——小数位段（`.`后）与科学计数法
#   尾段（1.2345678901234567e-05 的 e 段）整段排除；`\b` 保留（word 字符粘连
#   语义不变）。
_TASK_ID_RE = re.compile(r"(?<![0-9a-f.])\b(?=[0-9a-f]*[a-f])[0-9a-f]{16,17}\b")


def _recorded_task_ids_in_evidence(project_root: Path, name: str) -> set[str]:
    """evidence 已有记录 qa 标题里的 task-id 集合（跨步已归位豁免数据源）。

    redteam-taskid-pairing（2026-08-22 interaction_turnover u:1 子5 实证）：
    配对判据「文本出现即派发」只读本步 qa，不知道哪些 id 已在之前子步骤
    归位——红队报告收录原文引用子4 取证 agent 的 task-id（审前步证据链
    天然引用），被误判「已派发未收录」拒收，且拒收消息指路重复收录、
    级联触发三件套拒收，模型烧 ~10min 返工后靠编辑收录原文删 id 过关。
    收录即带 id 到标题由 ingest_agent_report() 脚本保证（模型无法伪造），
    故 evidence 标题 id = 已归位，豁免其引用。
    """
    text = read_evidence(project_root, name)
    if not text:
        return set()
    ids: set[str] = set()
    decoder = json.JSONDecoder()
    for line in text.splitlines():
        s = line.strip()
        idx = 0
        while idx < len(s):
            nxt = s.find("{", idx)
            if nxt == -1:
                break
            idx = nxt
            try:
                rec, end = decoder.raw_decode(s, idx)
            except json.JSONDecodeError:
                break  # 此行剩余部分不是合法 JSON（截断/损坏）-> 下一行
            idx = end
            if not isinstance(rec, dict):
                continue
            qs = rec.get("q")
            if isinstance(qs, str):
                qs = [qs]
            if isinstance(qs, list):
                for q in qs:
                    ids.update(_TASK_ID_RE.findall(str(q)))
    return ids


def _dispatched_vs_unrecorded_task_ids(
    qa: list, project_root: Path | None = None, name: str | None = None
) -> list[str]:
    """派发但未收录的子代理 task-id（v2.118 修 B，类型无关配对）。

    实证（tail_volume u:1 子3）：light 报告零命中 -> 按契约升档补派 full agent，
    产生**第二个**必须归位的 agent；但 fetch_report_recorded 只按「子2 原子数」
    计数（tier≠none = 1 个），light 空报告占掉唯一名额，full 报告缺席无人察觉
    （真实载荷重放旧判据 = None 通过）。上限式计数逮不住升档路径。

    改为按派发信号配对：
      dispatched = trace 全文里出现的 task-id（派发即在 trace 留 id）
      recorded   = 各 qa 项**标题**（q）里的 task-id
      未收录     = dispatched - recorded
    标题里的 task-id 由 ingest_agent_report() 脚本写入
    （f"{title}（task-id {task_id}）"）——收录即带 id，模型无法伪造配对。

    类型无关是要点：子4 同时有取证 agent 与红队 agent，按类型分别计数需两套
    易错规则；按 id 配对只问「派了几个收了几个」。真实载荷双向重放：
    子3 = BLOCK（full 缺席）/ 子4 = PASS（full + 红队均收录），见 design §3 修 B。

    redteam-taskid-pairing 扩面（跨步已归位豁免）：recorded 并入 evidence
    已有记录 qa 标题里的 task-id——前步已归位 id 的引用（收录报告原文对
    前步 agent 的引用是天然合法形态）不再误判为本步派发。缺省参数
    （旧直调）= 不豁免，行为不变。宁纵勿枉方向不变：豁免只放过「前步
    标题里确已归位」的 id，全新派发 id 无前步记录仍逮。
    """
    dispatched: set[str] = set()
    recorded: set[str] = set()
    for item in qa:
        q = str(item.get("q", ""))
        dispatched.update(_TASK_ID_RE.findall(q))
        dispatched.update(_TASK_ID_RE.findall(str(item.get("a", ""))))
        recorded.update(_TASK_ID_RE.findall(q))
    if project_root is not None and name is not None:
        recorded |= _recorded_task_ids_in_evidence(project_root, name)
    return sorted(dispatched - recorded)


# 模式枚举清单的 文件:行号 形态（pattern_enum_declared 用）。
_PATTERN_ENUM_FILE_LINE_RE = re.compile(r"[\w./-]+\.\w+[:：]L?\d+")


def _check_pattern_enum_declared(qa: list, *_ctx) -> str | None:
    """pattern_enum_declared：u:1 子4 模式枚举二态声明机械核验（u:1 子4 专属）。

    动机（designs/pattern-enum-regression-guard-design.md §2，样本=web_ui_interaction_2
    tacet+fermate 漏 composite 页 3 处同族 ×100 病灶）：同族病灶召回依赖 u:1#4 单次
    取证的枚举完备性，而旧判据无枚举要件——召回靠模型发挥（_1 枚举 4 模板、_2 枚举
    3 个，同一判据两种结果）。tacet 裁掉二次审视步后波动零兜底直传交付物。
    存在性/形态属机械可判（#12 下沉）：载荷必载「模式枚举」q 项，二态必居其一——
    ①命令+命中清单（文件:行号 形态）；②「不适用+理由」（单点逻辑无可枚举同族）。
    无条件触发：非代码问题写「不适用」一行即过（#7 低成本合法路径在场）。
    真值（命令是否真跑/清单是否真实）不判——judge 判不了真值，消费侧兜底=
    plan:1#2 用户拍板时见全量清单（真值归用户）。
    """
    for item in qa:
        if "模式枚举" not in str(item.get("q", "")):
            continue
        a = str(item.get("a", ""))
        if "不适用" in a:
            return None
        if _PATTERN_ENUM_FILE_LINE_RE.search(a):
            return None
        return (
            "模式枚举项形态不合——二态必居其一：①枚举清单=命令原文+命中清单"
            "（文件:行号，全量不截断）+范围声明（全仓或限定目录+理由）；"
            "②「模式枚举：不适用——<一句理由>」（机制为单点逻辑、无可文本检索的"
            "同族写法形态时）。空泛声明（「已全仓检查」式无清单无理由）不算记录"
        )
    return (
        "模式枚举二态声明缺失——根因/问题机制指向可文本检索的代码写法时，必跑"
        "全仓枚举（grep -rn 或等效）并载「模式枚举」q 项（命令+命中清单 文件:行号 "
        "全量+范围声明）；机制为单点逻辑不可枚举同族时载「模式枚举：不适用——理由」。"
        "二态必居其一，禁沉默（缺项=枚举可能未做，同族病灶召回无兜底）"
    )


def _check_fetch_report_recorded(qa: list, *_ctx) -> str | None:
    """fetch_report_recorded：子4 蒸馏报告原文收录机械核验（u:1 子4 专属）。

    judge 重放实证（2026-08-01 v2.38 落地验证）：无子代理报告的旧形态 trace
    过新 gate 被判 PASS——judge 把内容丰富的留痕当实质满足，「报告原文收录」
    形式要件被裁量放过（子代理编排可被绕过，主上下文卸载落空）。形式要件
    下沉机械层：每原子一个标题含「蒸馏报告」的 q 项（标题=承诺装置+结构），
    judge 只判内容质量。

    v2.40 tier-aware：需外部取证的原子 = 子2 atomic_questions 里 tier≠none
    的项（none 档仅内查、豁免报告项）；报告项数须 ≥ 该数（逐项对齐由 judge
    判，机械只数总数）。子2 trace 无 atomic_questions（v2.40 前实例）->
    legacy 行为（≥1 个报告项）。

    v2.118 补派发配对（修 B）：原子数下限之外，另查「派发的 task-id 是否
    都有收录项」——升档补派的 full agent 缺席由此逮住（原判据放过，实证见
    _dispatched_vs_unrecorded_task_ids docstring）。
    """
    missing = _dispatched_vs_unrecorded_task_ids(
        qa, _ctx[0] if _ctx else None, _ctx[1] if len(_ctx) > 1 else None
    )
    if missing:
        return (
            f"子代理报告未归位就提交——trace 提到 task-id {', '.join(missing)} "
            "（= 已派发）但无对应收录项：每个派发的 agent 都须 append-trace "
            "--ingest-agent <task-id> 收录其报告（脚本按 id 落原文，标题自动带 "
            "task-id）。等 agent 归位后再提交；light 报告标「建议升档 full」而"
            "补派的 full agent 同样须收录（升档留痕）；agent 失败/空结果则重派"
            "（已收录于前步 trace 的 task-id 引用不算本步派发，已豁免）"
            "或升级用户裁决——「已派发运行中」式状态说明不算收录"
        )
    # fetch-preflight-probe：「预检不可达」项计入--全源不可达的原子不派发
    # agent（环境阻断合法路径），无报告项，机械计数须认可该留痕形态
    # （v2.118 修 B 对偶：配对判据覆盖「合法不派发」）。
    found = sum(
        1
        for item in qa
        if "蒸馏报告" in str(item.get("q", ""))
        or "预检不可达" in str(item.get("q", ""))
    )
    required = 1
    if _ctx and _ctx[0] is not None:
        aq = _load_atomic_questions(_ctx[0], _ctx[1])
        if aq:
            required = max(
                1,
                sum(
                    1 for it in aq if isinstance(it, dict) and it.get("tier") != "none"
                ),
            )
    if found >= required:
        return None
    return (
        f"蒸馏报告收录项不足——需外部取证的原子 {required} 个（tier≠none），"
        f"trace 里标题含「蒸馏报告」的 q 项仅 {found} 个：每原子一个报告项"
        "（fetch-prompt 骨架派发 Agent，报告原文收录非转述；"
        "外部取证不走主会话直连——命令模板在 fetch-prompt 骨架里；"
        "none 档原子豁免——仅内查不派 agent）"
    )


def _wf_artifact_mtime_stale(f: Path, project_root: Path, name: str) -> bool:
    """per-workflow 产物新鲜度：mtime 早于当前节点 entered_at = 陈旧残留。

    fetch_skeleton_out / fetch_preflight_out 共用（单源）；entered_at 不可考
    （state 缺失/无 history）-> False（降级仅存在性，宁纵勿枉）。
    """
    state = load_state(project_root, name)
    if state is None:
        return False
    state = normalize_state(state)
    try:
        not_before = _node_entered_at(
            state, get_node(state["phase"], state["sub_index"])
        )
    except KeyError:
        return False
    return not_before is not None and f.stat().st_mtime < not_before


def _check_fetch_skeleton_out(qa, project_root, name):
    """fetch_skeleton_out：子4 骨架 --out 落盘机械核验（u:1 子4 专属，v2.43）。

    v2.42 把骨架路径钉死 per-workflow 目录，但「模型是否真的用了 --out」
    仍靠文案——模型重定向 stdout 自选路径则钉死形同虚设。下沉机械层
    （§8.3 产物门同范式）：骨架文件须存在于 .claude/workflows/<name>/ 且
    mtime 不早于本节点 entered_at（残留防御；entered_at 不可考 -> 降级
    仅存在性，宁纵勿枉）。全 none 档短路消息同样经 --out 落盘，口径一致。
    """
    if project_root is None or name is None:
        return None
    f = project_root / ".claude" / "workflows" / name / "fetch-prompt-skeleton.md"
    if not f.is_file():
        return (
            f"骨架未落盘：{f} 不存在——子4 派发取证子代理前须先跑 "
            "`python3 ~/.dl-workflow/dl_flow_engine.py fetch-prompt --out`"
            "（骨架路径钉死 per-workflow 目录，禁 stdout 重定向自选路径），"
            "落盘后重试"
        )
    if _wf_artifact_mtime_stale(f, project_root, name):
        return (
            f"骨架陈旧：{f} 最后修改早于本节点进入时间——须在本节点内重新 "
            "fetch-prompt --out 落盘（禁残留），落盘后重试"
        )
    return None


def _check_fetch_preflight_out(qa, project_root, name):
    """fetch_preflight_out：子4 外部源预检落盘机械核验（fetch-preflight-probe）。

    实证（2026-08-22 interaction_turnover u:1 子4）：light agent 环境性失败
    （网络超时）空跑 3.2min 后又串行升档 full 5.5min。用户裁决：外部取证
    派发前须对全部计划内外部源 URL 预检可达性。「模型是否真的预检了」
    下沉机械层（fetch_skeleton_out §8.3 同范式）：预检结果文件须存在于
    per-workflow 目录且 mtime 不早于本节点 entered_at。

    豁免：子2 atomic_questions 全 none 档（无外部源可预检）。aq 缺失
    （v2.40 前实例）-> 按 legacy=有外部取证处理，仍要求（对齐
    _check_fetch_report_recorded 的 required 口径）。
    """
    if project_root is None or name is None:
        return None
    aq = _load_atomic_questions(project_root, name)
    if aq and all(isinstance(it, dict) and it.get("tier") == "none" for it in aq):
        return None
    f = project_root / ".claude" / "workflows" / name / "fetch-preflight.json"
    if not f.is_file():
        return (
            f"外部源预检未落盘：{f} 不存在——子4 派发取证子代理前须先对全部"
            "计划内外部源 URL 跑 `python3 ~/.dl-workflow/dl_flow_engine.py "
            "fetch-preflight [name] --url <URL> [<URL> ...]`（逐 URL 探测网络"
            "可达性并落盘；全源不可达的原子不派发不升档、载荷记「预检不可达」），"
            "落盘后重试"
        )
    if _wf_artifact_mtime_stale(f, project_root, name):
        return (
            f"预检结果陈旧：{f} 最后修改早于本节点进入时间——须在本节点内重新 "
            "fetch-preflight（禁残留），落盘后重试"
        )
    return None


def _redteam_worker_file(project_root, name) -> Path | None:
    """driver 预派发红队的 worker 记录文件（u1-sub5-cost 修3）。"""
    if not project_root or not name:
        return None
    return (
        Path(project_root) / ".claude" / "workflows" / str(name) / "redteam_worker.json"
    )


def _check_redteam_report_recorded(
    qa: list, project_root=None, name=None
) -> str | None:
    """redteam_report_recorded：子5 红队输出原文收录机械核验（u:1 子5 专属，v2.44）。

    实证（2026-08-02 tail_volume u:1 子4）：模型先撞占位符扫描（「待补」机械拒、
    拒绝消息已指路「等红队归位再提交」），改写措辞绕开扫描（「未归/仍在跑中」
    不含禁词）仍提前提交 -> judge block（~3.5min 返工 + 1 次 judge 白烧）。
    §3.5 #14/#20：词表扩词 = 打地鼠，行为禁令的闭环 = 写侧机械核验。

    信号分隔度经全量历史子4 trace 重放验证（7 条真实载荷）：
    「task-id 出现 = 红队已派发」（红队经 Agent 工具单发起，派发即有 task-id；
    未触发合法分支无 agent 可引，两条真实未派发载荷均无 task-id）×
    收录项 = 标题含「红队」且含「原文收录」的 qa 项（与子4「蒸馏报告」标题
    承诺装置同范式）。被 block 载荷 = 有 task-id 无收录项；通过载荷 = 两者皆有。
    未派发（含未触发声明、触发满足但未起）-> None 交 judge 判真值（宁纵勿枉）。

    v2.118 补派发配对（修 B）：标题存在性之外，另查「派发的 task-id 是否都有
    收录项」——子5 可同时有取证 agent（子4 升档补派、跨步归位）与红队 agent，
    仅判「有没有红队收录项」逮不住其中一个缺席（类型无关配对见
    _dispatched_vs_unrecorded_task_ids）。

    u1-sub5-cost 修3 预派发通道：红队改由 driver 预派发（Step.pre_dispatch），
    载荷无 task-id 可引——以 redteam_worker.json 在位为「红队已派」信号：
    在位 + 无收录项 = 提前提交当场拒（否则 judge 侧 gate 文案被告知「形式要件
    已机械拦截」，提前提交会穿堂而过 = 对抗复核缺席的洞）；不在位（v2 TUI /
    driver 未起）-> None 交 judge（宁纵勿枉维持）。
    """
    text_all = "\n".join(f"{item.get('q', '')}\n{item.get('a', '')}" for item in qa)
    recorded = any(
        "红队" in str(item.get("q", "")) and "原文收录" in str(item.get("q", ""))
        for item in qa
    )
    if "task-id" not in text_all and "task_id" not in text_all:
        if recorded:
            return None
        wj = _redteam_worker_file(project_root, name)
        if wj is not None and wj.exists():
            return (
                "红队已由 driver 预派发（redteam_worker.json 在位）但输出未收录"
                "——缺标题含「红队」「原文收录」的 qa 项（正确动作：append-trace "
                "--ingest-redteam，阻塞等报告就绪并原文收录落载荷，禁手工粘贴；"
                "预派发失败按其报错回退会话内路径 Agent + --ingest-agent）。"
                "「已派发等归位」式状态说明不算记录（提前提交 = 对抗复核缺席的裁决，"
                "下游子6 会拿到未经复核的问题集）"
            )
        return None
    if not recorded:
        return (
            "红队已派发（trace 含 task-id）但输出未原文收录——缺标题含「红队」"
            "「原文收录」的 qa 项（正确动作：append-trace --ingest-agent <task-id>，"
            "脚本提取报告原文落载荷，禁手工粘贴）。"
            "等 Agent 归位收录原文后再提交；agent 失败/空结果则重派或升级用户裁决"
            "——「已派发等归位」式状态说明不算记录（提前提交 = 红队结论缺席的裁决，"
            "下游子6 会拿到未经对抗复核的问题集）"
        )
    # 红队收录项在场后，再查是否有**其它**派发的 agent 缺席（子4 升档补派的
    # 取证 agent 可跨步归位到子5——仅判「有没有红队收录项」逮不住它）。
    missing = _dispatched_vs_unrecorded_task_ids(qa, project_root, name)
    if missing:
        return (
            f"子代理已派发但输出未收录——trace 提到 task-id {', '.join(missing)} "
            "却无对应收录项（正确动作：append-trace --ingest-agent <task-id>，"
            "脚本提取报告原文落载荷、标题自动带 task-id，禁手工粘贴）。"
            "等 Agent 归位收录原文后再提交；agent 失败/空结果则重派或升级用户"
            "（已收录于前步 trace 的 task-id 引用不算本步派发，已豁免）"
            "裁决——「已派发等归位」式状态说明不算记录（提前提交 = 对抗复核"
            "缺席的裁决，下游子6 会拿到未经复核的问题集）"
        )
    return None


# u1-sub5-cost 修2：置信度要件词形（取真实被 block 载荷逐字「置信 95%」，
# 200fb21a 轮）——「置信度」正字 或 「置信」+数字（%）。「难以置信」类
# 不含数字不误中；转述冒充（无数字置信）维持拦截。
_REDTEAM_CONFIDENCE_RE = re.compile(r"置信度|置信\s*\d")


def _check_redteam_three_piece(qa: list, *_ctx) -> str | None:
    """redteam_three_piece：子5 红队收录项三件套完整性机械核验（v2.83，u:1 子5 专属）。

    v2.83（designs/u1-sub4-gate-framing-design.md）：#4 vio1（红队转述冒充原文
    收录）在默认-PASS framing 下 judge 漏判 4/6--红队收录项缺推理链/置信度是
    词形可判部分，下沉 mech 零方差（#2 缺席断言同范式，§3.5 #13）。
    红队收录项 = 标题含「红队」且含「原文收录」的 qa 项（同 redteam_report_recorded
    承诺装置）。三件套 = verdict+推理链+置信度（purpose 明文 + redteam-prompt
    模板规定字段名）；收录项 a 须含「推理链」关键词 + 置信度词形（verdict 由标题/
    redteam_report_recorded 间接保证）。缺任一 -> 拒；未派发（无收录项）-> None
    交 judge 判真值（宁纵勿枉，同 redteam_report_recorded）。

    u1-sub5-cost 修2 置信度词形放宽（模板侧已同步钉逐字标签）：200fb21a 轮
    红队原文写「置信 95%」（模板未钉逐字时弱模型自然简写）被字面「置信度」
    拦——词形取真实被 block 载荷逐字（v2.49 同范式）：`置信度|置信\\s*\\d`。
    """
    recorded_items = [
        item
        for item in qa
        if "红队" in str(item.get("q", "")) and "原文收录" in str(item.get("q", ""))
    ]
    if not recorded_items:
        return None
    for item in recorded_items:
        a = str(item.get("a", ""))
        if "推理链" not in a or not _REDTEAM_CONFIDENCE_RE.search(a):
            return (
                "红队原文收录项缺四态 verdict+推理链+置信度三件套中的推理链或"
                "置信度（正确动作：append-trace --ingest-agent <task-id> 收录红队"
                "完整输出，含 verdict+推理链+置信度三件套；仅 verdict+概括建议"
                "=转述冒充收录）"
            )
    return None


def _check_user_decision_recorded(qa: list, *_ctx) -> str | None:
    """user_decision_recorded：读回确认步的用户裁决记录机械核验（v2.45）。

    交接架构（designs/context-handoff-design.md §4）正确性前提：8 个读回步
    全部 gate=None（trace 存在即过、无 judge），用户裁决此前只在对话里——
    /clear 换会话后新上下文只能从 trace 还原拍板内容，漏记 = 重问用户或编造。
    操作化：标题带「裁决」或「读回」的 qa 项（承诺装置同「蒸馏报告」先例）
    + 内容 ≥50 字（「用户已确认」式空记录交接后无法还原拍板）。
    分隔度：真实 u:1 子7（699 字）/u:2 子5（543 字）通过；空记录（<10 字）
    与缺项两形态拦截——margin 两个数量级，非调参数式阈值（§3.5 #15）。
    """
    titled = [
        it
        for it in qa
        if "裁决" in str(it.get("q", "")) or "读回" in str(it.get("q", ""))
    ]
    if any(len(str(it.get("a", "")).strip()) >= 50 for it in titled):
        return None
    if titled:
        return (
            "用户裁决记录项内容过薄——「用户已确认」式空记录不算：逐项记录用户"
            "认/否/拍板结果与答复要点。读回步 gate=None 无 judge 兜底，且 /clear "
            "交接后新会话只能从 trace 还原拍板内容——空记录 = 重问用户或编造"
        )
    return (
        "缺用户裁决记录项——读回确认步的 trace 须含标题带「裁决」或「读回」的 "
        "qa 项，逐项记录用户认/否/拍板结果与答复要点（读回步 gate=None，本校验"
        "是唯一防线；/clear 交接后新会话只能从 trace 还原拍板内容）"
    )


# v2.51 原话标注通道（2026-08-02 u:1 子1 三连 block att1-3 逐字）：
# 用户全程只点 AskUserQuestion 选项（transcript 实证零打字原话），judge 按
# 「who 只认用户自述」临场发明「原话全文引用」要件——三轮共同形态=「原话」
# 声称 + AskUserQuestion 出处 + 无通道标注；选项标签标「原话」=标注失真
# （声称的佐证等级高于实际）。通道两态与 _USER_QUOTE_FORMS_RULE 一一对应：
# 「选中」=选项标签（会话事实级自述，不得标原话）/「自由输入」=打字原话。
# v2.52 扩面（同日晚第二集）：模型换「自述」绕开「原话」词表（逐字取自
# 新 att1）；锚定改「标签+引用」近端形态（自述/原话 + 冒号/引号），防
# 「本步仅认用户自述」式元讨论 FP。
_QUOTE_LABEL_RE = re.compile(r"(?:用户)?(?:身份)?(?:原话|自述)[^，。；]{0,6}[:：『「]")
_ASKQ_ANN_RE = re.compile(r"（[^）]{0,50}AskUserQuestion[^）]{0,50}）")


def _check_user_quote_channel(qa: list, *_ctx) -> str | None:
    """user_quote_channel：AskUserQuestion 出处「原话/自述」标签的通道校验
    （u:1 子1 专属，nodes 声明）。

    只判标注形态不判真值：「原话/自述」作标签引出引用（后接冒号/引号）
    且近端有 AskUserQuestion 出处括注时——括注含「选中」=选项标签带等级
    前缀，标注失真当场拒；含「自由输入」=自称打字原话，真值归 judge；
    皆无=通道未声明当场拒。无标签形态（如「标签全文（AskUserQuestion
    选中）」）与元讨论里的「自述」字样不拦（宁纵勿枉）。
    分隔度：att1-3（v2.51 集）+ 新 att1（v2.52 集「自述」换词）逐字 BLOCK；
    合法两态、新 att2 干净形态、元讨论 FP 守卫全 PASS。
    """
    for item in qa:
        a = str(item.get("a", ""))
        for m in _QUOTE_LABEL_RE.finditer(a):
            window = a[m.start() : m.start() + 140]
            ann = _ASKQ_ANN_RE.search(window)
            if ann is None:
                continue  # 直接对话原话等——不涉 AskUserQuestion 通道
            if "选中" in ann.group(0):
                return (
                    "选项标签不得带「原话/自述」前缀——标注失真（声称的佐证"
                    "等级高于实际）：选中项=用户主动声明行为，是合法佐证但属"
                    "会话事实级，记录=选项标签全文+「（AskUserQuestion 选中）」"
                    "并去掉「原话/自述」前缀词"
                )
            if "自由输入" in ann.group(0):
                continue
            return (
                f"AskUserQuestion 出处的「原话/自述」声称未标注通道"
                f"（{str(item.get('q', ''))[:20]}…）：「（AskUserQuestion 选中）」"
                "=选项标签（会话事实级，须去掉「原话/自述」前缀）/"
                "「（AskUserQuestion 自由输入）」=打字原话——补通道标注；"
                "是选中则去掉前缀词，是打字则标「自由输入」"
            )
    return None


def _check_answer_no_reverse_inference(qa: list, *_ctx) -> str | None:
    """answer_no_reverse_inference：答案位禁反推（u:1 子1 专属，v2.68）。

    实证（2026-08-03 tail_volume_acceleration_annualized u:1 子1 att1）：
    模型第 4 类「可观察后果」没问用户，a 填「三项标签反推…本项为反推项」
    （诚实披露词形），judge 依「痛点须用户确认」判 block——判对但白烧一轮
    judge + 一轮全量上下文（钉死保 judge 判对不保模型写对，§3.5 #16；
    一次通过率=最大杠杆）。词形下沉机械层=秒拒+精确返工指路。
    词形取 att1 a[3] 逐字（反推/暗含/隐含，§3.5 #22 词形取真实被 block
    载荷逐字先例）；含「推测」标注的项豁免（「推断标推测另列」是
    _STEP1_FORM_REQUIREMENTS 的合法形态，宁纵勿枉）。att2 的「认知类答案
    包装成可观察后果链」无反推词形、内容质量归 judge，本校验不拦（分工
    边界，见 designs/understand1-sub1-reverse-inference-option-design-design.md）。
    """
    for item in qa:
        a = str(item.get("a", ""))
        if "推测" in a:
            continue
        for w in ("反推", "暗含", "隐含"):
            if w in a:
                return (
                    f"答案含「{w}」= 反推占答案位——该维度必须实际 "
                    "AskUserQuestion 补问（或引用上下文已有的用户原话），"
                    "禁止问一部分、反推剩余；推断内容标「推测」另列可接受，"
                    "但不能充当该维度的用户确认答案"
                )
    return None


# v2.71（2026-08-03 tail_volume u:1 子1 judge 误伤根治）：
# 6 变体 ~70 次重放实证 judge 对 who 项最高频误判之一=把「AskUserQuestion 选中
# 角色选项」当「仓库事实冒充身份」（V3c att2#3/clean#2）。who 出处合法性属形式
# 要件（关键词可判），下沉机械层=append-trace 当场拒，judge 不再判 who 出处
# （§3.5 #13 词形判据下沉机械层 + #17 形式要件机械化）。词形取真实判词逐字
# （CLAUDE.md/git config/分支命名）；选中角色选项/未自述标注不拦（宁纵勿枉）。
_WHO_REPO_FACT_RE = re.compile(
    r"CLAUDE\.md|git\s*config|分支命名|git\s*log|commit\s*历史"
)


def _check_who_no_repo_fact(qa: list, *_ctx) -> str | None:
    """who_no_repo_fact：who 项禁仓库事实冒充身份出处（u:1 子1 专属，v2.71）。

    who 类出处只认用户自述（含选中角色选项）；仓库事实（CLAUDE.md/git config/
    分支命名）只证明「仓库由谁维护」不能证明「当前提问者身份」。扫描 who 项 a
    含仓库事实关键词即拒--把 judge 对 who 出处的裁量方差（V3c 实证选中项被当
    仓库事实）下沉机械层零方差。选中角色选项/「未自述身份」标注不拦。
    """
    for item in qa:
        q = str(item.get("q", ""))
        if "who" not in q.lower() and "角色" not in q and "身份" not in q:
            continue
        a = str(item.get("a", ""))
        if _WHO_REPO_FACT_RE.search(a):
            return (
                "who 项用了仓库事实（CLAUDE.md/git/分支命名）冒充提问者身份--"
                "仓库事实只证明「仓库由谁维护」不能证明「当前提问者身份」；"
                "who 类出处只认用户自述（含 AskUserQuestion 选中的角色选项），"
                "无自述时如实标注「未自述身份」合法"
            )
    return None


# v2.75（2026-08-04 u:1 子2 vio2 稻草人牙齿根治）：
# v2.73/v2.74 重放实证 judge 对「排除理由无证据指针」判据双向抖动——
# v2.73 把缺席断言「用户没有表达过这个意思」当留痕放过（vio2 4/6 牙齿掉），
# v2.74 钉「缺席断言≠指针」后又对 clean 的具体选择记录过度索取（clean 1/6）。
# 缺席断言是词形可判项——下沉机械层零方差（§3.5 #13），judge 只判「假设
# 明显不成立且凑数」的语义侧。词形取 vio2 真实载荷逐字（没有表达过）。
_HYP_EXCLUDE_ABSENCE_RE = re.compile(
    r"排除[^。]{0,40}?(没有表达过|没说过|未说过|没有说过|未提及|没有提到|未提到|没有表达)"
)


def _check_hypothesis_exclude_no_absence(qa: list, *_ctx) -> str | None:
    """hypothesis_exclude_no_absence：竞争假设排除理由禁缺席断言（u:1 子2，v2.75）。

    「用户没有表达过/没说过」式缺席断言不算证据指针（断言「没有什么」，
    与全局否定断言同族）；排除须引用具体原话或具体选择记录（如
    AskUserQuestion 选中项），证据不足改标「保留/待子3取证」。
    「未选择 X 而选择 Y」是对具体选择记录的引用，合法不拦（宁纵勿枉）。
    """
    for item in qa:
        a = str(item.get("a", ""))
        if _HYP_EXCLUDE_ABSENCE_RE.search(a):
            return (
                "竞争假设排除理由用了缺席断言（「用户没有表达过/没说过」类）——"
                "缺席断言不算证据指针；排除须引用具体原话或具体选择记录"
                "（如 AskUserQuestion 选中项），证据不足时改标「保留/待子3取证」"
            )
    return None


# u 侧根因行（up-change-spec-gate，2026-08-25，与 statements 侧改动规格
# 锚点验真同设计）：understand 完成的验收标准 = 根因定位五要素（文件/类/
# 方法/行号 + 问题机制）明确且准确。语法真源 = _ROOT_CAUSE_LINE_RULE。
_ROOT_CAUSE_LINE_RE = re.compile(r"根因@([A-Z])@([^\n]+)")
_ROOT_CAUSE_CODE_RE = re.compile(
    r"^(?P<file>[\w./-]+\.\w{1,10}):(?P<symbol>[A-Za-z_][\w.]*|-)"
    r":L(?P<l1>\d+)(?:-(?P<l2>\d+))?[：:](?P<mech>.+)$"
)
# 子2a atomic_questions 的原子标签（覆盖差集的源侧）——在 atomic_questions
# 数组段内提 "q" 首标签（qa 配对的 q 键会误匹配，须先锁数组段）。
# 标签双形态（2026-08-25 真实证据重放逮住）：「A. 问题」首字母形 +
# 「原子A【数据源事实】：问题」原子前缀形（interaction_amplitude 实例生产
# 形态——只认首字母形则覆盖判静默空转=宁纵勿枉变永远勿枉）。
_AQ_ARRAY_RE = re.compile(r'"atomic_questions"\s*:\s*\[(.*?)\]', re.S)
_AQ_ITEM_LABEL_RE = re.compile(r'"q"\s*:\s*"\s*(?:原子\s*)?([A-Z])(?=[._、：:\s【])')


def _check_root_cause_anchor_verify(qa: list, project_root: Path, name) -> str | None:
    """root_cause_anchor_verify：u:1 子2b 根因行覆盖 + 代码侧锚点三验。

    ①覆盖：子2a 原子标签集 vs 本步根因行标签集差集（atomic_mece_alignment /
    sc_coverage_trace 差集下沉范式第三例）；子2a 缺失/无标签 -> 跳过覆盖判
    （宁纵勿枉）。②每条代码侧根因行过锚点三验（db 缺失/过期跳过——
    codegraph 新鲜度前置归 plan:1#1 不归本步，拒=无合法修复路径，§3.5 #7）。
    ③「会话事实」根因行不验（用户决策瓶颈类问题以原话为环合法——双结论制，
    本校验不破既有 gate 合法正例）。
    """
    blob = "\n".join(str(it.get("a", "")) for it in qa)
    found = _ROOT_CAUSE_LINE_RE.findall(blob)
    s2a = read_evidence_for_step(project_root, name, 2, "ProblemContext")
    labels_2a: set[str] = set()
    if s2a:
        m = _AQ_ARRAY_RE.search(s2a)
        if m:
            labels_2a = set(_AQ_ITEM_LABEL_RE.findall(m.group(1)))
    if labels_2a:
        missing = sorted(labels_2a - {lb for lb, _ in found})
        if missing:
            return (
                f"根因行覆盖缺原子 {missing}——每个原子问题的因果链末须落一行"
                f"根因行：{_ROOT_CAUSE_LINE_RULE}"
            )
    elif not found:
        return None  # 双侧都无机械基准——交 judge（宁纵勿枉）
    tracked = _git_tracked_files(project_root)
    for lb, rest in found:
        rest = rest.strip()
        if rest.startswith("会话事实"):
            continue  # 用户决策/外部因素豁免（双结论制）
        m = _ROOT_CAUSE_CODE_RE.match(rest)
        if not m:
            return (
                f"根因行（原子 {lb}）语法不合：「{rest[:60]}」——{_ROOT_CAUSE_LINE_RULE}"
            )
        file = m.group("file")
        if tracked is not None and file not in tracked:
            return (
                f"根因行（原子 {lb}）的文件 {file} 不在 git 仓内——"
                "锚点须真实存在：回链内已引用的 file:line 逐字取，"
                "或跑 dl codebase query 核实"
            )
        err = _verify_anchor_parts(
            project_root,
            file,
            m.group("symbol"),
            m.group("l1"),
            m.group("l2"),
            context=f"根因行（原子 {lb}）",
        )
        if err:
            return err
    return None


# qa 格式步的写侧机械校验注册表（Step.mech_checks 声明名 -> 检查函数）。
# 未注册名 = nodes 与 engine 配置漂移，fail loud 不静默跳过。
_MECH_QA_CHECKS = {
    "causal_ring_no_untested": _check_causal_ring_no_untested,
    "user_quote_channel": _check_user_quote_channel,
    "answer_no_reverse_inference": _check_answer_no_reverse_inference,
    "who_no_repo_fact": _check_who_no_repo_fact,
    "hypothesis_exclude_no_absence": _check_hypothesis_exclude_no_absence,
    "root_cause_anchor_verify": _check_root_cause_anchor_verify,
    "value_no_unsourced_inference": _check_value_no_unsourced_inference,
    "goal_candidate_traceability_alignment": _check_goal_candidate_traceability_alignment,
    "answer_source_marker": _check_answer_source_marker,
    "baseline_tool_trace": _check_baseline_tool_trace,
    "constraint_verification_tool_trace": _check_constraint_verification_tool_trace,
    "terrain_tool_trace": _check_terrain_tool_trace,
    "feasibility_verification_trace": _check_feasibility_verification_trace,
    "pugh_traceability_forward_coverage": _check_pugh_traceability_forward_coverage,
    "pugh_net_score_consistency": _check_pugh_net_score_consistency,
    "element_quote_trace": _check_element_quote_trace,
    "need_quote_trace": _check_need_quote_trace,
    "epc_quote_trace": _check_epc_quote_trace,
    "dependency_order_trace": _check_dependency_order_trace,
    "element_coverage_trace": _check_element_coverage_trace,
    "single_phase_argument": _check_single_phase_argument,
    "binding_residue_trace": _check_binding_residue_trace,
    "assumption_completeness_trace": _check_assumption_completeness_trace,
    "fetch_report_recorded": _check_fetch_report_recorded,
    "pattern_enum_declared": _check_pattern_enum_declared,
    "fetch_skeleton_out": _check_fetch_skeleton_out,
    "fetch_preflight_out": _check_fetch_preflight_out,
    "redteam_report_recorded": _check_redteam_report_recorded,
    "redteam_three_piece": _check_redteam_three_piece,
    "user_decision_recorded": _check_user_decision_recorded,
}
