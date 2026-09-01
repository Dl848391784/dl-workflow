#!/usr/bin/env python3
"""
dl_flow_trace - trace 载荷的解析 / 装配 / 写入（「AI 定写什么，脚本定怎么写」）。

拆分缘由（2026-08-27，designs/split-engine-round2-design.md）：dl_flow_engine
第二刀 B。本节是标记文本 -> JSONL 的机械写入面（_parse_trace_md / scaffold /
append_trace / ingest / fetch·redteam prompt 装配），状态机依赖已全部下沉
dl_flow_common。engine 经 re-export 保持 eng.<name> 访问面不变
（hooks / tests / _subagent_retry_stats）。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from dl_flow_checks import (
    _MECH_EXTRA_ITEM_CHECKS,
    _MECH_EXTRA_STR_CHECKS,
    _MECH_QA_CHECKS,
    _MECH_STATEMENTS_CHECKS,
    _NOUN_L,
    _NOUN_R,
    _implementation_nouns,
    _load_atomic_questions,
    _placeholder_hit,
    _source_step_index,
    _step_trace_id_contexts,
    _step_trace_ids,
)
from dl_flow_common import (
    _evidence_path,
    _now,
    load_state,
    normalize_state,
    read_evidence_for_step,
    sub_step_at,
    sub_step_has_trace,
    trace_payload_path,
)
from dl_flow_nodes import _NODES, get_node, node_id


# 载荷里禁止出现的结构字段（由 append_trace 从 state 推导填充）。
_TRACE_STRUCT_FIELDS = ("kind", "major_stage", "minor_stage", "sub_step", "skill")


# v2.65（2026-08-03 tail_volume_acceleration_annualized u:1 子1 手写载荷事故）：
# 标头捕获组后放行 glued 内容——模型手写自然风格是「【purpose】内容」同行
# （scaffold 骨架是标头独占一行，但模型绕过 scaffold 手写时本能粘头），
# 旧 `\s*$` 整行匹配把粘头行当「标头前多余内容」拒，报错「从【purpose】开始」
# 与文件实况（确实以【purpose】开头）矛盾，模型被误导去 hunt BOM/隐藏字节
# （xxd/od/python-rb 连环 S15 deny）。group(2)=粘头内容（空=干净标头行）。
_MD_HEADER_RE = re.compile(r"^【([^】]+)】[ \t]*(.*)$")


_MD_ITEM_FIELDS = frozenset(
    {"q", "a", "text", "type_label", "boundary", "tier", "tier_reason"}
)


class _MdErr(Exception):
    """标记文本解析错误（fail loud 给模型指路）。"""


def _parse_trace_md(raw: str, step) -> tuple[dict | None, str | None]:
    """分节标记文本 -> 载荷 dict（v2.58：模型零接触 JSON 的正治）。

    四桶分工（AI 定写什么/脚本定怎么写）的兑现：v2.57 scaffold 只缩小了
    JSON 接触面——Edit 填内容时 ASCII 双引号/反斜杠照样崩 JSON（真实
    trace 含 f"{val*100:.2f}%" 类代码原文）。标记文本零转义：内容随便带
    引号/换行/代码，序列化全归脚本。
    格式：标头顶格写；【purpose】/【qa】/【q】/【a】/【statements】/
    【text】/【type_label】/【boundary】/【fields.<k>】/【结论】等声明键。
    数组键（qa/statements/atomic_questions）内首个字段标头重复 = 新一项；
    标量键（purpose/结论）收文本到下一标头。内容行想以【开头：缩进一格即
    不算标头（逃生口）。
    v2.65 宽容化（手写载荷事故正治）：①剥文件头 BOM；②标头后可粘内容
    （「【purpose】内容」同行=标头+内容，模型手写自然风格——scaffold 骨架
    是标头独占一行，但绕过 scaffold 手写时本能粘头，旧版误拒且报错指路
    与实况矛盾）；③「标头前多余内容」报错带 repr 实际内容（BOM/散文一眼
    可见，免 xxd/od 字节 hunt）。
    """
    raw = raw.lstrip("\ufeff")  # ①剥文件头 BOM（Write/编辑器可能带 \ufeff）
    array_keys: set[str] = set()
    scalar_keys = {"purpose"}
    if getattr(step, "record_format", "qa") == "statements":
        array_keys.add("statements")
    else:
        array_keys.add("qa")
    for e in getattr(step, "extra_payload_keys", ()):
        k, spec = e[0], e[1]
        if isinstance(spec, str):
            array_keys.add(k)
        else:
            scalar_keys.add(k)

    payload: dict = {}
    key: str | None = None  # 当前顶层键
    item: dict | None = None  # 当前数组项
    field: str | None = None  # 当前项内字段
    first_field: dict[str, str] = {}  # 数组键 -> 首字段名（重复=新一项）
    buf: list[str] = []

    def _flush() -> None:
        nonlocal buf
        val = "\n".join(buf).strip("\n")
        buf = []
        if key is None:
            if val.strip():
                raise _MdErr(
                    "首个标头前有多余内容--从【purpose】开始；"
                    f"实际内容 {val[:80]!r}（引擎已自动剥文件头 BOM--"
                    "检查是否在【purpose】前写了散文/注释）"
                )
            return
        if key in array_keys:
            if item is None or field is None:
                if val.strip():
                    raise _MdErr(
                        f"【{key}】节内须先给字段标头（如【q】/【text】）再写内容"
                    )
                return
            if field.startswith("fields."):
                item.setdefault("fields", {})[field.split(".", 1)[1]] = val
            else:
                item[field] = val
        else:
            payload[key] = val

    try:
        for ln in raw.splitlines():
            m = None if ln[:1] in (" ", "\t") else _MD_HEADER_RE.match(ln)
            if not m:
                # 逃生口：缩进 + 【 开头 = 内容（剥掉转义缩进）
                if ln[:1] in (" ", "\t") and ln.lstrip()[:1] == "【":
                    ln = ln.lstrip()
                buf.append(ln)
                continue
            h = m.group(1).strip()
            _flush()
            if h in scalar_keys:
                if h in payload:
                    raise _MdErr(f"标头【{h}】重复——同一键只写一次")
                key, item, field = h, None, None
            elif h in array_keys:
                key, item, field = h, None, None
                payload.setdefault(h, [])
            elif h in _MD_ITEM_FIELDS or h.startswith("fields."):
                if key not in array_keys:
                    raise _MdErr(
                        f"【{h}】是数组项字段标头，须写在数组键节内"
                        f"（{'/'.join(sorted(array_keys))}），当前节=【{key}】"
                    )
                ff = first_field.setdefault(key, h)
                if h == ff:
                    item = {}
                    payload[key].append(item)
                elif item is None:
                    raise _MdErr(f"【{key}】节每项都须以【{ff}】开头")
                field = h
            else:
                raise _MdErr(
                    f"未知标头【{h}】——本步合法标头："
                    + "/".join(f"【{x}】" for x in sorted(scalar_keys | array_keys))
                    + " + 数组项字段【q】【a】/【text】【type_label】【boundary】"
                    "（内容行想以【开头：缩进一格即不算标头）"
                )
            # v2.65：粘头内容（【key】内容 同行）注入当前节首行--
            # 模型手写自然风格粘头，scaffold 骨架是标头独占行；group(2)=粘头文本
            glued = m.group(2)
            if glued.strip():
                buf.append(glued.strip())
        _flush()
    except _MdErr as e:
        return None, str(e)
    return payload, None


def _subagent_dir(
    project_root: Path, name: str, task_id: str | None = None
) -> Path | None:
    """子代理 transcript 目录定位（v2.39 台账同款，round-2 修 A 多目录时代）。

    v4 前台混合修复（2026-08-13 amplitude_annualized sub3 实证）：agent 由
    段工人（headless claude -p）派发，其 transcript 落在段工人的 session 目录下；
    state.session_id 恒指前台 TUI 会话（driver 从未按 headless-driver-arch-design
    §2.6「session_id 语义=最近段 session」落地更新）——只信 state.session_id 会
    指向前台目录（不存在），--ingest-agent 报「找不到子代理 transcript」，模型
    被迫 62 轮逆向源码手工兜底。改为 glob 遍历项目目录下所有 session 子目录，
    返回含 subagents/ 的那个（v2 单 TUI 会话下前台目录同样命中）。

    u1-sub4-cost round-2 修 A（2026-08-17 同实例 step4 实爆）：上述「返回第一个
    含 subagents/ 的目录」写在单目录时代——多会话各有 subagents/（step4 每轮 +
    红队 + 升档补派，该实例 14 个）后，字典序第一个 = 旧会话目录，本段
    transcript 在其后目录，ingest 必报「找不到」→ 模型 15 轮调试死循环
    （ln -sf/cp 被 sensitive 守卫拒、python3 shutil 绕过）。
    - task_id 给定（ingest_agent_report）：返回含 agent-<task_id>.jsonl 的
      目录；多命中（模型手工拷贝残留的同名 workaround 文件）取文件 mtime
      最新者（当前段产出）。
    - task_id=None（_subagent_retry_stats 等「本会话」语义）：取**最新 agent
      文件**所在目录（agent-*.jsonl mtime 最大者——transcript 写入时间锚，
      不受目录被 touch/拷贝残留污染；段顺序执行，当前段的 agent 恒最新写入；
      预派发 RT worker --tools Read 无 subagents，不干扰）。
    """
    state = load_state(project_root, name)
    if not state:
        return None
    wt = state.get("worktree_path")
    if not wt:
        return None
    enc = "".join(c if c.isalnum() else "-" for c in str(wt))
    base = Path.home() / ".claude" / "projects" / enc
    if not base.is_dir():
        return None
    dirs = []
    for d in base.iterdir():
        sd = d / "subagents"
        if sd.is_dir():
            dirs.append(sd)
    if task_id:
        matches = [sd for sd in dirs if (sd / f"agent-{task_id}.jsonl").exists()]
        if not matches:
            return None
        return max(
            matches,
            key=lambda sd: (sd / f"agent-{task_id}.jsonl").stat().st_mtime,
        )
    if not dirs:
        return None

    def _newest_agent_mtime(sd: Path) -> float:
        return max(
            (f.stat().st_mtime for f in sd.glob("agent-*.jsonl")),
            default=0.0,
        )

    return max(dirs, key=_newest_agent_mtime)


def _insert_report_item(
    payload_path: Path, text: str, title: str, report: str
) -> tuple[bool, str]:
    """把报告收录项插进 .md 载荷【qa】节末（ingest_agent_report /
    ingest_redteam_report 共用，u1-sub5-cost 修3 抽出）。

    插入【qa】节内（节末、下一顶层标头前）——追加文件尾会落进别的节
    （【q】在【atomic_questions】节末=被当分档项；在【结论】节末=解析报错）。
    """
    lines = text.splitlines()
    qa_idx = next((i for i, ln in enumerate(lines) if ln.strip() == "【qa】"), None)
    if qa_idx is None:
        return False, "载荷缺【qa】节——报告收录项进 qa 节，先补 qa 节再 ingest"
    item_headers = {f"【{h}】" for h in _MD_ITEM_FIELDS}
    insert_at = len(lines)
    for i in range(qa_idx + 1, len(lines)):
        st = lines[i].strip()
        if (
            st.startswith("【")
            and st.endswith("】")
            and st not in item_headers
            and not st.startswith("【fields.")
        ):
            insert_at = i
            break
    section = [
        "",
        "【q】",
        title,
        "【a】",
        *report.strip().splitlines(),
        "",
    ]
    lines[insert_at:insert_at] = section
    try:
        payload_path.write_text("\n".join(lines), encoding="utf-8")
    except OSError as e:
        return False, f"写载荷失败：{e}"
    return True, ""


def _extract_predispatch_report(raw: str) -> str:
    """预派发 worker stdout → 报告文本（judge result-JSON 同款末行提取）。

    claude -p --output-format json：stdout 末行 = {"is_error":...,"result":"..."}
    （包装器/ANTHROPIC_LOG 调试输出混入前文是生产常态，judge 注释同款）；
    is_error → ""（调用方按无产出回退）；无 result JSON → 原文返回（宁纵勿枉）。
    """
    for line in reversed(raw.splitlines()):
        line = line.strip()
        if line.startswith("{") and '"result"' in line:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("is_error"):
                return ""
            return str(ev.get("result", ""))
    return raw


def pid_alive(pid) -> bool:
    """跨进程 pid 活性探测（driver 预派发/ingest 阻塞等待共用，u1-sub5-cost 修3）。

    僵尸坑（TestIngestRedteamPreDispatch 实测逮住）：worker 跑完但父进程
    （driver）还在跑段未 wait()——kill(pid,0) 对僵尸仍成功，会误判「仍在跑」
    把 ingest 拖到超时。/proc/<pid>/stat 的 state 字段判 Z（linux；读失败按
    活处理=宁纵勿枉，继续等）。
    """
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, OverflowError, ValueError, TypeError):
        return False
    except PermissionError:
        return True
    try:
        stat = Path(f"/proc/{int(pid)}/stat").read_text()
        if stat.rsplit(")", 1)[1].split()[0] == "Z":
            return False
    except (OSError, IndexError, ValueError):
        pass
    return True


def ingest_agent_report(
    project_root: Path, name: str, task_id: str
) -> tuple[bool, str]:
    """append-trace --ingest-agent <task-id>：子代理报告原文落载荷（v2.60）。

    四桶分工审计违规②根治：子3 fetch 蒸馏报告/子4 红队输出原要求模型
    「原文收录（完整粘贴）」——粘贴=转录，还配两层防偷懒 mech 检查。
    脚本按 task-id 定位 subagents/agent-<task-id>.jsonl、提取最终报告文本、
    以规定形态（标题含「蒸馏报告」/「红队」「原文收录」）追加进当前
    .md 载荷——「是否原文收录」从需要检查变结构性保证。
    载荷不存在/报告已收录/transcript 缺失 -> fail loud 指路。
    """
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    state = normalize_state(state)
    cur = state.get("sub_step_index", 1)
    # 标题从当前步 mech_checks 派生（消费方单源：_check_fetch_report_recorded
    # 数「蒸馏报告」标题项 / _check_redteam_report_recorded 数「红队」+「原文收录」
    # 项），不写死步号——旧 cur==3/4 硬编码在 plan-first 6→7 步重编号后把子4
    # fetch 报告标成「红队输出」，fetch_report_recorded 数 0 项当场拒
    # （amplitude_annualized D/F 两轮 step4 实爆，
    # designs/u1-sub4-cost-optimization-design.md 修 1）。查不到步则通用标题
    # 兜底（宁纵勿枉——若该步有标题要件，下游 mech check 会拦）。
    title = "子代理报告原文收录"
    try:
        node = get_node(state["phase"], state["sub_index"])
        step = sub_step_at(node, cur) if node.sub_steps else None
    except KeyError:
        step = None
    if step is not None:
        if "fetch_report_recorded" in step.mech_checks:
            title = "蒸馏报告原文收录"
        elif "redteam_report_recorded" in step.mech_checks:
            title = "红队输出原文收录"
    payload_path = trace_payload_path(project_root, name, state)
    if not payload_path.exists():
        return False, (
            f"载荷不存在：{payload_path}——先写本步其它内容（或 append-trace "
            "--scaffold 起骨架），再 --ingest-agent 追加报告收录项"
        )
    try:
        text = payload_path.read_text(encoding="utf-8")
    except OSError as e:
        return False, f"读载荷失败：{e}"
    # 防重只认脚本写出的收录项标题形态「原文收录（task-id xxx）」——全载荷子串
    # 匹配会把模型派发留痕「task-id=xxx」误报成已收录（amplitude_annualized D 轮
    # step4 实证：误报致 ~10 轮读源码调试死循环）。宁纵勿枉：重复收录代价 <<
    # 误报调试死循环。
    if f"原文收录（task-id {task_id}）" in text:
        return False, f"task-id {task_id} 已收录过——同一报告不重复落（防重）"

    d = _subagent_dir(project_root, name, task_id)
    fp = d / f"agent-{task_id}.jsonl" if d else None
    if fp is None or not fp.exists():
        return False, (
            f"找不到子代理 transcript：agent-{task_id}.jsonl"
            "（已按 task-id 搜索该工作流全部会话目录均无此文件）"
            "——task-id 以 Agent 工具返回的 <task-id> 为准"
        )
    report = ""
    try:
        for line in fp.open(encoding="utf-8"):
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if m.get("type") != "assistant":
                continue
            blocks = [
                str(b.get("text", ""))
                for b in (m.get("message", {}).get("content") or [])
                if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
            ]
            if blocks:
                report = "\n".join(blocks)  # 最后一条含文本的 assistant 消息=最终报告
    except OSError as e:
        return False, f"读子代理 transcript 失败：{e}"
    if not report.strip():
        return False, (
            f"agent-{task_id}.jsonl 无文本报告（子代理未产出/仍在跑）——"
            "等 Agent 返回后再 ingest"
        )

    # 插入【qa】节内（节末、下一顶层标头前）——逻辑单源 = _insert_report_item
    ok, err = _insert_report_item(
        payload_path, text, f"{title}（task-id {task_id}）", report
    )
    if not ok:
        return False, err
    return True, (
        f"✓ 已收录 {title}（task-id {task_id}，{len(report)} 字符）-> "
        f"{payload_path}——其余「待填」填完后 append-trace --from-file 落库"
    )


def ingest_redteam_report(
    project_root: Path, name: str, *, timeout: float = 360.0, interval: float = 2.0
) -> tuple[bool, str]:
    """append-trace --ingest-redteam：driver 预派发红队报告收录（u1-sub5-cost 修3）。

    红队改由 driver 在子4 gate 过后预派发（与子5 主会话并行——实测红队跑
    158-235s 而主会话有效并行 ≤1min，等报告 = step5 墙钟地板），报告文本落
    meta/redteam_report.md（worker 进程 stdout 重定向，进程退出才写完）。
    本命令阻塞等「报告非空 + pid 已死」后以规定标题形态（含「红队」
    「原文收录」=redteam_report_recorded 承诺装置）落载荷 qa 节——收录仍是
    结构性保证，模型零接触手工粘贴。
    无预派发（v2 TUI/driver 未起）/worker 无产出 -> fail loud 指路回退会话内
    路径（redteam-prompt → Agent → --ingest-agent），宁纵勿枉。
    """
    meta = Path(project_root) / ".claude" / "workflows" / name
    wj_path = meta / "redteam_worker.json"
    report_path = meta / "redteam_report.md"
    _fallback = (
        "回退会话内路径：`python3 ~/.dl-workflow/dl_flow_engine.py redteam-prompt`"
        " 生成 prompt → Agent 工具单发起 → append-trace --ingest-agent <task-id>"
    )
    if not wj_path.exists():
        return False, (
            "本步无 driver 预派发红队记录（v2 TUI 模式或 driver 未起红队）——"
            + _fallback
        )
    try:
        wj = json.loads(wj_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return False, f"redteam_worker.json 读取失败：{e}——{_fallback}"

    deadline = time.monotonic() + timeout
    while True:
        report = ""
        try:
            if report_path.exists():
                report = report_path.read_text(encoding="utf-8")
        except OSError:
            report = ""
        alive = pid_alive(wj.get("pid"))
        if report.strip() and not alive:
            break
        if not alive and not report.strip():
            return False, (
                "预派发红队无产出（worker 进程已退出、报告为空）——"
                f"{_fallback}（worker stderr 见 {meta / 'cc_sdk.log'}）"
            )
        if time.monotonic() >= deadline:
            return False, (
                f"红队报告未就绪（已等 {int(timeout)}s，worker 仍在跑）——"
                "先继续做不依赖红队的部分（①三关质检、③初步 verdict 草稿），"
                f"完成后重跑本命令；多次超时则 {_fallback}"
            )
        time.sleep(interval)

    # --output-format json 的 stdout → 报告文本（judge result-JSON 同款提取）：
    # 末行 {"is_error":...,"result":"..."}（ANTHROPIC_LOG 调试输出会混入前文——
    # rt_smoke 冒烟实测 report 11.9KB 大头是 [log_*] 请求转储，真实报告在末尾）；
    # is_error → 无产出回退；找不到 result JSON → 原文兜底（宁纵勿枉）。
    report = _extract_predispatch_report(report)
    if not report.strip():
        return False, (
            "预派发红队无产出（claude 会话 is_error 或空 result）——"
            f"{_fallback}（worker stderr 见 {meta / 'cc_sdk.log'}）"
        )

    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    state = normalize_state(state)
    payload_path = trace_payload_path(project_root, name, state)
    if not payload_path.exists():
        return False, (
            f"载荷不存在：{payload_path}——先写本步其它内容（或 append-trace "
            "--scaffold 起骨架），再 --ingest-redteam 追加报告收录项"
        )
    try:
        text = payload_path.read_text(encoding="utf-8")
    except OSError as e:
        return False, f"读载荷失败：{e}"
    # 防重只认脚本写出的收录项标题形态（与 ingest_agent_report 同纪律，
    # 宁纵勿枉——重复收录代价 << 误报调试死循环）；模型派发留痕不含此形态。
    if "红队输出原文收录（" in text:
        return False, "红队报告已收录过——同一报告不重复落（防重）"
    title = "红队输出原文收录（driver 预派发）"
    ok, err = _insert_report_item(payload_path, text, title, report)
    if not ok:
        return False, err
    return True, (
        f"✓ 已收录 {title}（{len(report)} 字符）-> {payload_path}——"
        "其余「待填」填完后 append-trace --from-file 落库"
    )


# statements 字段的骨架占位提示（up-change-spec-gate）：格式真源通道之一
# （#26：载荷格式唯一真源=scaffold 骨架+append-trace 报错文案）——
# change_list/change_point 的改动规格条目语法直接写进骨架待填占位符。
_FIELD_SCAFFOLD_HINTS = {
    "change_list": (
        "每条改动一行，类型词写括号内：file:symbol（改|删）：改前→改后要点（设计级行号豁免）；"
        "file:symbol（增@现有 symbol|L 行号|文件尾）：新增要点；模块级 symbol=-；"
        "正例：src/foo.py:bar（改）：改前 X → 改后 Y（行首 改= 类前缀可省）；"
        "只写可执行改动条目——决策注记/承接链写 boundary 字段、被否方案写 rejected 字段；"
        "html 模板/Jinja/fixture 等无 codegraph symbol 的文件：symbol 填 -、行号锚定；"
        "增@锚点只三形态：symbol 名 / L 行号 / 文件尾，禁自然语言"
    ),
    "change_point": (
        "每条改动一行，类型词写括号内：file:symbol:L<a>-<b>（改|删）：改前→改后要点（五要素必给）；"
        "file:symbol（增@现有 symbol|L 行号|文件尾）：新增要点；模块级 symbol=-；"
        "正例：src/foo.py:bar:L10-12（改）：改前 X → 改后 Y（行首 改= 类前缀可省）；"
        "只写可执行改动条目——决策注记/承接链写 boundary 字段、被否方案写 rejected 字段；"
        "html 模板/Jinja/fixture 等无 codegraph symbol 的文件：symbol 填 -、行号锚定；"
        "增@锚点只三形态：symbol 名 / L 行号 / 文件尾，禁自然语言"
    ),
}


def scaffold_payload(project_root: Path, name: str) -> tuple[bool, str]:
    """append-trace --scaffold：当前子步骤载荷骨架生成并落盘钉死路径。

    v2.57 动机（2026-08-02 tail_volume_acceleration_annualized u:1 审计）：
    模型手写全量 JSON 载荷出语法错（Extra data char 3895）白烧一轮——
    §3.6 #10 自检信号：语法错误不该归「模型基本功」，杠杆=脚本生成骨架。
    v2.58 正治：骨架从 JSON 换成分节标记文本（.md，零转义）——Edit 填
    JSON 仍会被内容里的 ASCII 引号弄崩（四桶分工没贯彻到底的半吊子），
    标记文本让模型全程零接触序列化格式。占位符统一用「待填」——
    _placeholder_hit 全局扫描兜底，漏填任何字段都过不了 append-trace。
    落盘路径单源 trace_payload_path（v2.125 起 = worktree 根，动机见其
    docstring；v2.42 纪律不变：路径归脚本不归模型自选）；已存在载荷拒覆盖
    （防抹掉在写工作）——例外：mtime < state.created_at 判为上轮残留，
    自动清理（v2.63，见函数体注释）。
    """
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    state = normalize_state(state)
    try:
        node = get_node(state["phase"], state["sub_index"])
    except KeyError:
        return False, f"节点 {state['phase']}:{state['sub_index']} 不存在"
    if not node.sub_steps:
        return False, f"节点 {node_id(node.phase, node.sub)} 无子步骤编排"
    cur = state.get("sub_step_index", 1)
    step = sub_step_at(node, cur)
    if step is None:
        return False, f"子步骤 {cur} 不存在"

    parts = ["【purpose】\n待填：本步目的/本轮做了什么（一句话）"]
    if getattr(step, "record_format", "qa") == "statements":
        # u4-sub4-cost 修A（u4_sub4_ab B 轮实测）：单条骨架未示多条形态，
        # 模型为确认「多条 statement 怎么写」去 evidence/仓内找实际样例
        # （5 调用格式核对税）——多条形态是格式信息，归骨架表达（四桶分工：
        # 格式归脚本），写进待填占位符括号（替换即消失，既有括注同形态）。
        seg = (
            "【statements】\n【text】\n待填：单句陈述（outcome 层，禁实现侧名词/file:line；"
            "多条陈述 = 逐项重复本【statements】整段，一条一块）"
            "\n【type_label】\n待填：类型标签（如 in/out）\n【boundary】\n待填：边界/实现指针"
        )
        for k in getattr(step, "statement_fields", ()) or ():
            seg += f"\n【fields.{k}】\n待填：{_FIELD_SCAFFOLD_HINTS.get(k, k)}"
        parts.append(seg)
    else:
        parts.append(
            "【qa】\n【q】\n待填：问题1\n【a】\n待填：答案1（用户原话/会话事实/证据指针 file:line）"
        )
    seen: set[str] = set()
    for e in getattr(step, "extra_payload_keys", ()):
        k, spec = e[0], e[1]
        if k in seen:
            continue  # 同键多 spec（fetch_tier_items + atomic_mece_alignment）只取首个
        seen.add(k)
        if isinstance(spec, str):
            if spec == "fetch_tier_items":
                parts.append(
                    f"【{k}】\n【q】\n待填：原子问题（与 MECE 声明标签一一对应）"
                    "\n【tier】\n待填：none|light|full（拿不准标 light）"
                    "\n【tier_reason】\n待填：分档理由（none 档须含仓内路径）"
                )
            else:
                parts.append(f"【{k}】\n【q】\n待填")
        else:
            parts.append(f"【{k}】\n待填：{'/'.join(spec)} 开头+逐句出处")

    out = trace_payload_path(project_root, name, state)
    stale_cleaned = ""
    if out.exists():
        # v2.63（2026-08-03 tail_volume_acceleration_annualized u:1 子1 事故）：
        # 上轮放弃运行的 payload 点文件残留挡住新一轮首个 --scaffold（手动清
        # evidence 用 ls 看不见点文件；launch/state-reset 均不清 payload）。
        # 机械判 stale：payload mtime < state.created_at ⇒ 它诞生时本轮还
        # 不存在 ⇒ 定义性残留，自动清理重新生成；否则可能是本轮在写工作 ⇒
        # 维持拒覆盖。created_at 缺失/畸形 ⇒ 宁纵勿枉维持拒覆盖（不误删）。
        stale = False
        created = state.get("created_at")
        if isinstance(created, str):
            try:
                created_ts = time.mktime(time.strptime(created, "%Y-%m-%dT%H:%M:%S"))
                stale = out.stat().st_mtime < created_ts
            except (ValueError, OSError):
                pass
        if not stale:
            return False, (
                f"载荷已存在：{out}——直接在它上面填内容（Edit），或删除后重跑 "
                "--scaffold（拒覆盖防抹掉在写工作）"
            )
        out.unlink()
        stale_cleaned = f"（已自动清理上轮残留载荷：mtime 早于本工作流启动 {created}）"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    except OSError as e:
        return False, f"写骨架失败：{e}"
    # v2.126 披露前置（web_ui_interaction u:2#4 打地鼠 733s）：statements 步
    # 的源步 ID 传导要件随骨架成功消息预印——首次提交前披露是零成本出口
    # （打地鼠成本≈(提交数-1)×全上下文重交，#54 审计手法）。
    transmit_note = ""
    if getattr(step, "record_format", "qa") == "statements":
        src = _source_step_index(step, cur)
        if src:
            src_ids = sorted(_step_trace_ids(project_root, name, src, node.minor_key))
            if src_ids:
                transmit_note = (
                    f"；传导要件：源步（子{src}）编号 {'/'.join(src_ids)} "
                    "须逐项字面出现在某条 statement 的 text/boundary"
                    "（写「承接 X」或「X 剔除：理由」均可）"
                )
    return True, (
        f"✓ 骨架已生成 {out}（子步骤 {cur} {step.ref}）{stale_cleaned}——"
        "先 Read 该文件再 Write/Edit（harness 写前必读，跳过会报 "
        "read-first 错）；把所有「待填」换成实际内容（漏填会被占位符扫描当场拒；"
        "内容随便带引号/换行/代码，格式全归脚本），"
        f"然后 Bash `python3 ~/.dl-workflow/dl_flow_engine.py append-trace --from-file {out}`"
        f"{transmit_note}"
    )


def append_trace(project_root: Path, name: str, payload_file: str) -> tuple[bool, str]:
    """载荷（purpose + qa 配对；旧 q/a 平行数组写侧已退役硬拒）+ state 结构字段 -> 校验 -> 单行 skill-trace append。

    返回 (ok, 消息)。校验失败 (False, 原因)——fail loud：模型当轮按报错修载荷
    重跑，而不是写坏了到 gate 才暴露（甚至像 d59d05ea 那样静默卡死）。
    成功后删载荷文件（防重复落库；失败保留供模型原地修）。
    """
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    state = normalize_state(state)
    try:
        node = get_node(state["phase"], state["sub_index"])
    except KeyError:
        return False, f"节点 {state['phase']}:{state['sub_index']} 不存在"
    if not node.sub_steps:
        return (
            False,
            f"节点 {node_id(node.phase, node.sub)} 无子步骤编排，append-trace 不适用",
        )
    if not node.minor_key:
        return (
            False,
            f"节点 {node_id(node.phase, node.sub)} 无 minor_key，无法填结构字段",
        )
    cur = state.get("sub_step_index", 1)
    step = sub_step_at(node, cur)
    if step is None:
        return False, f"子步骤 {cur} 不存在"

    pf = Path(payload_file)
    try:
        raw = pf.read_text(encoding="utf-8")
    except OSError as e:
        return False, f"读载荷失败：{e}（先用 Write 写载荷文件再调 append-trace）"
    try:
        payload = json.loads(raw) if pf.suffix != ".md" else None
    except json.JSONDecodeError as e:
        return False, (
            f"载荷不是合法 JSON：{e}——推荐改用标记文本载荷（.md，零转义）："
            "append-trace --scaffold 生成骨架，内容随便带引号/换行/代码"
        )
    if pf.suffix == ".md":
        payload, md_err = _parse_trace_md(raw, step)
        if md_err:
            return False, f"载荷标记文本解析失败：{md_err}"
    if not isinstance(payload, dict):
        return False, '载荷须是 JSON 对象：{"purpose":..., "qa":[{"q":..., "a":...}]}'
    leaked = [k for k in _TRACE_STRUCT_FIELDS if k in payload]
    if leaked:
        return False, (
            f"载荷含结构字段 {leaked}——这些由脚本从 state 自动填，载荷里不要写"
            "（只留 purpose + 内容字段：qa 或 statements，及本步声明的额外必填键）"
        )
    purpose = payload.get("purpose")
    if not isinstance(purpose, str) or not purpose.strip():
        return False, "purpose 须为非空字符串"
    ph = _placeholder_hit(payload)
    if ph:
        marker, loc = ph
        return False, (
            f"trace 是完成记录——含占位标记「{marker}」（位于 {loc}）；"
            "待决项到位后再提交（红队未归：等 Agent 返回并原文收录后再 append-trace）"
        )
    qa: list | None = None  # qa 格式分支赋值；extra 逐项校验的声明侧上下文（v2.50）
    if getattr(step, "record_format", "qa") == "statements":
        # v2.27 statements 结构化载荷（清单型产出步）：三字段校验 +
        # 机械预检（方案名词扫描 + 源步 ID 传导覆盖）——词形判据下沉机械层。
        # v2.33 statement_fields：步声明的必备字段键（如设计陈述八字段）进
        # fields 对象，append 时逐键校验非空——「N 字段齐备」形式要件从
        # judge 判词变 JSON 校验，judge 只剩语义判据。
        req_fields = getattr(step, "statement_fields", ()) or ()
        statements = payload.get("statements")
        if statements is not None and (
            payload.get("qa") is not None
            or payload.get("q") is not None
            or payload.get("a") is not None
        ):
            return False, "载荷 statements 与 qa/q/a 两格式混用——只留 statements"
        if not isinstance(statements, list) or not statements:
            return False, (
                "statements 须为非空数组："
                '[{"text":...,"type_label":...,"boundary":...}, ...]'
            )
        for i, item in enumerate(statements):
            if not isinstance(item, dict):
                return False, f"statements[{i}] 须为对象"
            for field in ("text", "type_label", "boundary"):
                if not isinstance(item.get(field), str) or not item[field].strip():
                    return False, f"statements[{i}].{field} 须为非空字符串"
            if req_fields:
                flds = item.get("fields")
                if not isinstance(flds, dict):
                    return False, (
                        f"statements[{i}].fields 须为对象——本步逐项必备字段："
                        f"{'/'.join(req_fields)}"
                    )
                missing_f = [
                    k
                    for k in req_fields
                    if not isinstance(flds.get(k), str) or not flds[k].strip()
                ]
                if missing_f:
                    return False, (
                        f"statements[{i}].fields 缺或空字段：{'、'.join(missing_f)}"
                        f"——本步逐项必备：{'/'.join(req_fields)}"
                        "（字段齐备是机械校验的形式要件，补齐再提交）"
                    )
        nouns = _implementation_nouns(project_root)
        for i, item in enumerate(statements):
            for noun in sorted(nouns):
                if noun in item["text"] and re.search(
                    _NOUN_L + re.escape(noun) + _NOUN_R, item["text"]
                ):
                    return False, (
                        f"statements[{i}].text 含实现侧名词「{noun}」——陈述体只许 "
                        "outcome-level 概念，实现侧名词/file:line 挪到 boundary 字段"
                        "（judge 之前的机械预检，与 gate 的方案名词规则同源）"
                    )
        src = _source_step_index(step, cur)
        if src:
            # v2.126 披露版（web_ui_interaction u:2#4 打地鼠 733s）：报错附
            # 每个缺传 ID 的源文出处 + 传导判定规则 + 合法形态——旧文案只说
            # 「逐条补或显式标注剔除理由」，不教写在哪/什么语法算标注，模型
            # 靠 grep 其他实例 evidence 反推格式（#54 打地鼠=披露缺口）。
            src_id_ctx = _step_trace_id_contexts(
                project_root, name, src, node.minor_key
            )
            if src_id_ctx:
                new_text = " ".join(
                    f"{it['text']} {it['type_label']} {it['boundary']} "
                    + " ".join(str(v) for v in (it.get("fields") or {}).values())
                    for it in statements
                )
                missing = sorted(i for i in src_id_ctx if i not in new_text)
                if missing:
                    origins = "；".join(
                        f"「{i}」源文 …{src_id_ctx[i]}…" for i in missing
                    )
                    return False, (
                        f"源步（子{src}）条目未逐项传导，缺：{'、'.join(missing)}"
                        f"（{origins}）"
                        "——逐项原子化传导是形式要件：编号字面出现在任一 "
                        "statement 的 text/boundary/fields 即算传导，写「承接 "
                        f"{missing[0]}」或「{missing[0]} 剔除：理由」均可；"
                        "源文是引注噪声（非真条目）的按剔除标注并写明源出处"
                    )
        # statements 侧 mech_checks（首个落地，u:2#4 预留独立项 #30 ⑰ 的解）：
        # 与 qa 分支同款循环，查 statements 注册表，签名单 (statements, project_root, name)。
        for chk in getattr(step, "mech_checks", ()):
            fn = _MECH_STATEMENTS_CHECKS.get(chk)
            if fn is None:
                return False, (
                    f"mech_checks 配置错误：「{chk}」未在 _MECH_STATEMENTS_CHECKS "
                    "注册（nodes 与 engine 漂移，fail loud）"
                )
            err = fn(statements, project_root, name)
            if err:
                return False, err
        content_fields = {"statements": statements}
    else:
        qa = payload.get("qa")
        if qa is not None and (
            payload.get("q") is not None or payload.get("a") is not None
        ):
            return False, "载荷 qa 与 q/a 两格式混用——只留 qa 配对格式"
        if qa is None and (
            payload.get("q") is not None or payload.get("a") is not None
        ):
            # v2.35 写侧收编：平行数组过渡桥拆除（v2.24 留的兼容路径只服务
            # 无视提示凭旧惯性写的模型，tail_volume plan:3 子5 q=11 a=7 实例）。
            # 对齐正确也硬拒——写对被默许等于强化漂移习惯。读侧不受影响：
            # evidence 记录 schema 仍是 q/a 平行数组（本函数归一化后写入）。
            return False, (
                "q/a 平行数组写侧已退役——改用 qa 配对格式 "
                '{"qa":[{"q":...,"a":...},...]}（一问一答配对成对象，'
                "不对齐在结构上不可表示）；问答内容原样搬运，只改载荷结构"
            )
        # v2.24 qa 配对格式：一问一答成对象，不对齐在结构上不可表示
        # （tail_volume understand:3 子4 平行数组三次长度不齐，各白烧一轮整篇重写）。
        if not isinstance(qa, list) or not qa:
            return False, 'qa 须为非空数组：[{"q":..., "a":...}, ...]'
        for i, item in enumerate(qa):
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("q"), str)
                or not item["q"].strip()
                or not isinstance(item.get("a"), str)
                or not item["a"].strip()
            ):
                return (
                    False,
                    f'qa[{i}] 须为含非空 q 与 a 的对象（{{"q":..., "a":...}}）',
                )
        for chk in getattr(step, "mech_checks", ()):
            fn = _MECH_QA_CHECKS.get(chk)
            if fn is None:
                return False, (
                    f"mech_checks 配置错误：「{chk}」未在 _MECH_QA_CHECKS 注册"
                    "（nodes 与 engine 漂移，fail loud）"
                )
            err = fn(qa, project_root, name)
            if err:
                return False, err
        q = [item["q"] for item in qa]
        a = [item["a"] for item in qa]
        content_fields = {"q": q, "a": a}

    # v2.37 extra_payload_keys：步声明的载荷顶层必填内容键（两格式通用）——
    # 存在性 + 非空 + 前缀机械校验，值并入 record 顶层（judge 读原始行自动可见）。
    # v2.40 泛化：spec 为字符串时是 _MECH_EXTRA_ITEM_CHECKS 注册名——值须为
    # 非空数组并过逐项校验（如 atomic_questions 分档清单）。
    extra_fields: dict = {}
    for entry in getattr(step, "extra_payload_keys", ()):
        key, spec = entry[0], entry[1]
        # v2.54：条目第三元素 = _MECH_EXTRA_STR_CHECKS 注册名（字符串键的
        # 内容词形校验，前缀校验通过后执行）。
        str_check = entry[2] if len(entry) > 2 else None
        v = payload.get(key)
        if isinstance(spec, str):
            fn = _MECH_EXTRA_ITEM_CHECKS.get(spec)
            if fn is None:
                return False, (
                    f"extra_payload_keys 配置错误：「{spec}」未在 "
                    "_MECH_EXTRA_ITEM_CHECKS 注册（nodes 与 engine 漂移，fail loud）"
                )
            if not isinstance(v, list) or not v:
                return False, (
                    f"载荷缺必填键「{key}」——本步形式要件（append-trace 机械校验）："
                    "顶层提交非空数组，逐项 "
                    '{"q":..., "tier":..., "tier_reason":...}'
                )
            err = fn(v, qa)
            if err:
                return False, err
            extra_fields[key] = v
            continue
        prefixes = spec
        if not isinstance(v, str) or not v.strip():
            return False, (
                f"载荷缺必填键「{key}」——本步形式要件（append-trace 机械校验）："
                f"顶层提交「{key}」且以 {'/'.join(prefixes)} 开头"
            )
        if prefixes and not v.strip().startswith(prefixes):
            return False, (
                f"「{key}」须以 {'/'.join(prefixes)} 开头（二选一必出），"
                f"当前开头：{v.strip()[:12]!r}"
            )
        if str_check is not None:
            fn = _MECH_EXTRA_STR_CHECKS.get(str_check)
            if fn is None:
                return False, (
                    f"extra_payload_keys 配置错误：「{str_check}」未在 "
                    "_MECH_EXTRA_STR_CHECKS 注册（nodes 与 engine 漂移，fail loud）"
                )
            err = fn(v.strip())
            if err:
                return False, err
        extra_fields[key] = v.strip()

    record = {
        "kind": "skill-trace",
        "major_stage": state["phase"].capitalize(),
        "minor_stage": node.minor_key,
        "sub_step": cur,
        "skill": step.ref,
        "purpose": purpose,
        **content_fields,
        **extra_fields,
    }
    path = _evidence_path(project_root, name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        return False, f"写 evidence 失败：{e}"
    try:
        pf.unlink()  # 已落库，删载荷防重复 append
    except OSError:
        pass
    return (
        True,
        # v2.25：返工轮正文禁全文重述（judge 读 evidence 不读正文）——在模型
        # 写正文前的决策点指路增量总结（tail_volume u:3 子4 五轮重述烧 ~3.7k out）。
        f"✓ 已落库 sub_step={cur} -> {path}（可输出 ### STEP_DONE: {cur} 并 end_turn；"
        "载荷文件已删除——若被 block 返工须重新 append-trace --scaffold；"
        "返工轮正文只写增量总结=本轮变更条目+总数，禁全文重述——"
        "judge 读 evidence 不读正文，完整集由读回确认步呈现）",
    )


def redteam_prompt(project_root: Path, name: str) -> str | None:
    """组装子5 红队子代理 prompt（证据+纪律归脚本，Agent 调用归模型）。

    证据取 read_evidence_for_step(≤4)：含子1-4 最新 trace、**不含子5 结论**
    （只给证据不给结论）。无子4 trace -> None（调用方 exit 1 暴露：
    红队无证据可审，先回补子4）。
    minor_stage 限定 ProblemContext（本函数是 understand:1 子5 专属；
    不限定会读到 GoalsAndValue 的同号子步骤 trace——跨节点串号）。
    """
    pc_minor = _NODES["understand:1"].minor_key
    if not sub_step_has_trace(project_root, name, 4, pc_minor):
        return None
    evidence = read_evidence_for_step(project_root, name, 4, pc_minor)
    if evidence is None:
        return None
    return (
        "你是独立红队评审。一个工作流正在对若干原子问题做取证后裁决，"
        "你是独立第二视角——任务是对证据做点查并尝试找出推翻空间，"
        "不是附和既有方向。\n\n"
        "【证据（双向取证留痕，含 URL / file:line 指针）】\n"
        f"{evidence}\n\n"
        "【纪律】\n"
        "1. 点查以 Read 工具为主：证据里引用的文件路径用 Read 复查；"
        "你的会话里 Glob/Grep/codegraph 可能不存在、Bash 会被围栏拒绝，都不要试。\n"
        # u1-time-opt 修A（designs/u1-time-opt-design.md §2.4）：worker cwd=
        # 实例 worktree（干净检出），interaction run 实证它对主树在场的
        # 生成文件两处声明「不存在/无法复核」，把数值复核推给子5 主段。
        "路径提示：你的 cwd 是项目的 git worktree（干净检出）——证据里的相对"
        "路径 Read 不到（不存在）时，拼主仓库根绝对路径重试："
        f"{project_root}/<相对路径>；生成的数据/结果文件（如 backtest/result/、"
        "data_fetchers/result/ 下的产物）只在主仓库检出，不在 worktree。\n"
        "2. 单层：禁止再 spawn 子代理。\n"
        "3. 不做系统性重新取证：只点查验证；证据不足时下「证据不足」verdict 并指明缺哪条。\n"
        "4. 对每个原子问题给四态 verdict（证实/证伪/部分成立/证据不足）"
        "+ 推理链（引用证据指针）+ 置信度。\n\n"
        # u1-sub5-cost 修2 模板侧：钉逐字标签——旧「verdict / 推理链 / 置信度」
        # 未钉词形，弱模型红队自然简写成「置信 95%」撞 mech 字面扫（200fb21a 轮
        # 被拒后模型手工补标签，白烧 2 轮）。模板钉死为正解，mech 放宽为兜底
        # （双侧钉死，§3.5 #23）。
        "【输出】逐原子问题三行，三个标签**逐字**照写（收录侧机械核验按字面扫，"
        "「置信度」勿简写为「置信」）：\n"
        "verdict: 证实|证伪|部分成立|证据不足\n"
        "推理链: …（引用证据指针，file:line / URL）\n"
        "置信度: N%"
    )


def fetch_prompt(project_root: Path, name: str) -> str | None:
    """组装子3 外部取证子代理 prompt（纪律+命令模板归脚本，Agent 调用归模型）。

    v2.38（2026-08-01 tail_volume u:1 子3 审计）：子3 是主会话工具密度大户
    （实测 46 msgs/26 tool calls/6.2M cache read），curl 原始输出全堆主上下文；
    且外部源实测 ~40% 失败，根因逐层定位——命令模板逐字来自当日诊断：
    arXiv 用 http+无 UA 静默空（https+UA 已验证返回）、GitHub code search
    模型没带认证头 401（带 $GITHUB_TOKEN 已验证）、WebFetch 域验证被本网络
    全挂（环境性弃用）、SE 页面 403（API filter=withbody 替代已验证）。
    原子清单取子1-2 最新 trace（ProblemContext 限定，跨节点串号同
    redteam_prompt）。无子2 trace -> None（调用方 exit 1 暴露：无可取证
    对象，先回补子2）。
    v2.39（2026-08-01 tail_volume u:1 子3 复盘）：纪律 8/9——摄取截断 +
    轮次上限。实证：Q4 取证 agent 20 轮 curl 把上下文从 29k 撑到 60k，
    遇 provider 空响应重试 26 次烧掉 1.19M input（占其总 input 90%）——
    上下文越胖每轮越慢、重试越贵；轮次无上限时换同义词重试边际收益递减
    （Q4 最终被证伪，证伪是合法产出但不该付无上限探索成本）。
    v2.40（designs/fetch-depth-tiering-design.md）：按子2 atomic_questions
    标称档分派执行参数——full 档五层源双向（现状）；light 档 ≤2 层源 /
    ≤4 curl / 单向锚点（数值事实类点查）；none 档不进骨架（仅内查）。
    无 atomic_questions（v2.40 前实例）-> 全按 full 档（legacy 行为）。
    """
    pc_minor = _NODES["understand:1"].minor_key
    if not sub_step_has_trace(project_root, name, 2, pc_minor):
        return None
    evidence = read_evidence_for_step(project_root, name, 2, pc_minor)
    if evidence is None:
        return None
    # v2.40：标称档预填进 claim 补充区——[tier=X] 标记随骨架进 agent
    # transcript（台账 _subagent_retry_stats 按此提取 per-agent 档与轮次）。
    aq = _load_atomic_questions(project_root, name)
    claim_seg = ""
    if aq is not None:
        fetch_atoms = []
        none_atoms = []
        for i, it in enumerate(aq, 1):
            if not isinstance(it, dict):
                continue
            q = str(it.get("q", "")).strip()
            if it.get("tier") == "none":
                none_atoms.append(f"原子{i}「{q}」")
            else:
                note = (
                    "（light 档：调用方在 claim 区另指定 ≤2 层源）"
                    if it.get("tier") == "light"
                    else ""
                )
                fetch_atoms.append(f"- 原子{i} [tier={it.get('tier')}]：{q}{note}")
        if not fetch_atoms:
            return (
                "全部原子问题为 none 档（仅内查）——无需派发外部取证 agent："
                "直接做③内部仓库层，trace 注明「全 none 档未派发」。"
            )
        claim_seg = (
            "\n已分档原子清单（子2 标称档，禁降档——标 full 必须按 full 参数跑）：\n"
            + "\n".join(fetch_atoms)
        )
        if none_atoms:
            claim_seg += "\nnone 档原子（仅内查，禁为其派发取证 agent）：" + "；".join(
                none_atoms
            )
    return (
        "你是外部取证子代理。一个工作流正在对若干原子问题做双向取证——"
        "你只负责外部源取证并回蒸馏报告，不裁决、不写 evidence。\n\n"
        "【原子问题与背景（子1-2 trace）】\n"
        f"{evidence}\n\n"
        "【纪律】\n"
        "1. 单层：禁止再 spawn 子代理。\n"
        "2. 不写 evidence、不裁决（裁决归后续质检步）——只产出蒸馏取证报告。\n"
        "3. 禁 WebFetch（本环境域验证全挂）；禁 tavily_search/WebSearch。\n"
        "4. 层源范围与轮次上限按【分档执行参数】（每原子标称档见 claim 补充区 "
        "[tier=X]）；失败/空结果标「未取证+原因」是合法留痕，禁止补编。\n"
        "5. GitHub API 401 → 直接标「未取证+未认证」——禁止探查凭证"
        "（扫 env/配置文件找 token 是红线，必被安全分类器拦截）。\n"
        "6. 内部仓库层（codegraph/Read 仓内文件）不归你，主会话自查。\n"
        "7. 所有 curl 带 -m 25；失败重试一次再标未取证。\n"
        "8. 摄取截断：凡不经 jq 收窄的 curl，末尾一律接 `| head -c 6000`；"
        "超大响应先 -o /tmp/fetch_<层>_<n>.out 落盘再 head/jq 读。"
        "全量响应禁直接进你的上下文——单条 API 响应可达数万 token，"
        "上下文越胖每轮请求越慢、空响应重试越贵。\n"
        "9. 轮次上限按档：full ≤12 / light ≤4 次 curl（含重试）。超限未收敛 = "
        "带现有结果返回并如实标注「部分取证+轮次用尽」——禁止换同义查询词"
        "无限重试（边际收益递减；证伪方向取到 1-2 条强反证即可收）。"
        "够用即停：反证 2 轮零命中且已取到 ≥1 条直接针对谓词的源码/数据级"
        "证据 → 允许提前收尾，未尝试层在状态表标「够用即停+理由」——这是"
        "纪律 10 层配额的唯一提前收尾例外，不算配额违规。\n"
        "10. **层配额（上限≠配额）**：指定 N 层时每层至少花 1 次 curl，"
        "单层上限 = 总额 -(N-1)（light N=2 -> 每层 ≥1、单层 ≤3）。"
        "**禁在未轮完所有指定层前耗尽预算**——未轮完即申报「未收敛/建议升档」"
        "属配额违规，报告须标「配额未用尽：第 K 层未尝试」。\n"
        "11. curl 额度只用于 claim 取证：API 健康度/配额校验、裸响应确认一律"
        "不占额也不必做（空数组即空结果，不需要另证 API 正常）。\n"
        "12. 原子范围：只取【claim 区（调用方填写）】列出的原子——骨架内的"
        "分档清单/none 豁免说明是上下文不是任务单，其他原子由其他代理并行"
        "负责（2026-09-01 重放实证：3 full 原子场景单代理把 3 个原子全取了"
        "一遍，38 curl——多原子生产派发会 N× 重复取证）。\n\n"
        "【分档执行参数（按 claim 补充区每原子 [tier=X] 执行；禁降档——"
        "标 full 的原子必须按 full 参数跑）】\n"
        "- tier=full：五层源逐层尝试；≤12 curl；双向取证（反证查询先、支持证据后）；"
        "报告 ≤120 行/原子 + 五层状态表（每层一行：证据指针 或 未取证+原因）。\n"
        "- tier=light：只跑 claim 区为该原子指定的 ≤2 层源；≤4 curl"
        "（**每层至少 1 次、单层 ≤3**，见纪律 10——禁单层耗尽预算致另一层"
        "未尝试）；单向锚点（不双向、免五层状态表）——报告 ≤60 行：锚点值 + "
        "来源 URL + 一句量级对比 + 每层实际 curl 次数。锚点不收敛/来源冲突"
        "**且各指定层均已尝试** → 报告末尾标「建议升档 full + 理由」即返回，"
        "不自行加码轮次；仍有层未尝试则先轮完该层，不得提前申报升档。\n\n"
        "【命令模板（本机验证可用，逐字使用，只换查询词）】\n"
        '- 学术·OpenAlex：curl -sS -m 25 "https://api.openalex.org/works?search=<q>&per_page=3"\n'
        "- 学术·arXiv（必须 https + UA，http/无 UA 静默空返回）："
        'curl -sS -m 25 -A "Mozilla/5.0 (research)" '
        '"https://export.arxiv.org/api/query?search_query=all:%22<q>%22&max_results=3"\n'
        '- 社区·StackExchange：先 curl -sS -m 25 "https://api.stackexchange.com/2.3/search/advanced?'
        'order=desc&sort=relevance&q=<q>&site=quant&pagesize=3"；'
        "取正文用 /questions/<id>/answers?order=desc&sort=votes&site=quant&filter=withbody"
        "（页面 HTML 直抓 403——正文一律走 API withbody，禁抓页面）\n"
        '- 社区·HN：curl -sS -m 25 "https://hn.algolia.com/api/v1/search?query=<q>&tags=story&hitsPerPage=3"'
        "（空结果常见，标「未取证+无相关讨论」即可）\n"
        "- 开源·GitHub（认证头必须，否则 401）：curl -sS -m 25 "
        '-H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" '
        '"https://api.github.com/search/code?q=%22<q>%22&per_page=3"\n'
        "- 定点网页：curl -sS -m 25 直抓上述层发现的 URL（403/超时→标未取证+原因）\n"
        "- 提取用 jq（不要手写 python 一行流）：jq -r '.items[]?.link' / jq -r '.items[]?.title'\n\n"
        "【返回契约（蒸馏——原始 curl 输出留在你的上下文，只回 distilled）】\n"
        "逐原子问题（≤120 行/原子）：\n"
        "1. 反证查询（先）：逐条「查询词 → 源层 → 一句结论 + URL 指针」；\n"
        "2. 支持证据（后）：同构逐条；\n"
        "3. 五层状态表：学术（OpenAlex/arXiv)/社区（SE/HN)/开源（GitHub)/定点网页"
        "——每层一行：证据指针 或 未取证+原因。\n"
        "4. 外部机制证据适用性对拍：引用第三方库/外部机制（如某库的年化算法）"
        "作证据时，须与本仓实现（claim 区或 trace 给的 file:line；未给则标"
        "「未对拍」）逐条对拍并声明差异——未对拍或机制不适用的证据在报告里"
        "标「背景·不承重」（web_ui_interaction 实证：empyrical coverage-blind "
        "叙事对本仓已乘 coverage 的公式不适用，靠事后人工纠偏）。\n"
        "报告正文即留痕，反证段必须先于支持段（时序从文本直接可读）。\n"
        "light 档原子免上述格式，按【分档执行参数】light 契约返回（≤60 行）。\n\n"
        "【claim 补充区】\n"
        "（以下为调用方逐原子填写的可检验 claim 与证实/证伪标准——按 claim 谓词"
        "取证，证据须直接针对谓词，不泛泛取行业常识）" + claim_seg
    )


def _curl_probe(url: str, timeout: int = 8) -> tuple[bool, str | None, str]:
    """单 URL 网络可达性探测：任意 HTTP 状态码（含 403/404）= 可达。

    可达性 ≠ 内容成功--服务器应答即证明网络路径通；curl exit≠0 或
    http_code=000 才是不可达。返回 (ok, http_code, error)。
    """
    try:
        proc = subprocess.run(
            [
                "curl",
                "-s",
                "-o",
                os.devnull,
                "-w",
                "%{http_code}",
                "-m",
                str(timeout),
                url,
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 4,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, None, f"probe error: {e}"
    code = (proc.stdout or "").strip()
    if proc.returncode == 0 and code and code != "000":
        return True, code, ""
    return (
        False,
        (code if code and code != "000" else None),
        (f"curl exit {proc.returncode}"),
    )


def run_fetch_preflight(project_root: Path, name: str, urls: list[str]) -> int:
    """fetch-preflight 子命令体：逐 URL 探测并落盘 per-workflow 目录。

    失败重试一次（对齐骨架纪律 7；≤16s/URL 上界）。部分不可达仍 rc=0
    （不可达是信息不是命令失败）。结果文件是 mech fetch_preflight_out
    的核验对象（EXISTS+新鲜度），故始终落盘、无 stdout-only 模式。
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for u in urls:
        u = u.strip()
        if not u:
            continue
        if "://" not in u:
            u = f"https://{u}"
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    if not ordered:
        print("✗ 用法: fetch-preflight [name] --url <URL> [<URL> ...]", file=sys.stderr)
        return 1
    results = []
    ok_count = 0
    for u in ordered:
        ok, code, err = _curl_probe(u)
        if not ok:  # 抖动防误判：失败重试一次（宁纵勿枉）
            ok, code, err = _curl_probe(u)
        results.append({"url": u, "ok": ok, "http_code": code, "error": err or None})
        if ok:
            ok_count += 1
            print(f"✓ {u} HTTP {code}")
        else:
            print(f"✗ {u} 不可达（{err}）")
    out_path = project_root / ".claude" / "workflows" / name / "fetch-preflight.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {"checked_at": _now(), "results": results}, ensure_ascii=False, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"可达 {ok_count}/{len(ordered)}，预检结果落盘 {out_path}")
    return 0
