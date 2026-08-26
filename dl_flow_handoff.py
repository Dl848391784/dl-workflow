#!/usr/bin/env python3
"""
dl_flow_handoff - 子阶段边界交接（token 估算 / 交接包装配 / spawn 覆盖）。

拆分缘由（2026-08-27，designs/split-engine-round2-design.md）：dl_flow_engine
第二刀。本节与状态机零交互——只读 state/trace 装配交接包与 spawn 环境，
engine-core 依赖仅 _now（已下沉 dl_flow_common）。engine 经 re-export
保持 eng.<name> 访问面不变（_run_judge_once / tests / dl_drive）。
"""

from __future__ import annotations

import json
from pathlib import Path

from dl_flow_common import (
    _PHASE_ARTIFACT_DIRS,
    _evidence_path,
    _now,
    load_state,
    normalize_state,
    read_evidence,
)
from dl_flow_nodes import PHASES, Node, Step, get_node, node_id, phase_index, sub_total


# 子阶段边界交接提示分档阈值（tokens，v2.122，
# minor-boundary-handoff-prompt-design §2.1）：节点末步过门控的边界固定附
# /clear 提示（阈值不再决定是否出现，只定文案档位）：<T1 健康 / T1~T2 建议 /
# >T2 强烈建议。全软提示无硬拦（2026-08-07 用户决议：用户全程自主——
# 阈值硬拦已明确否决，选择由 write_handoff_prompt/resolution 机械留痕）。
# 前身 HANDOFF_NUDGE_THRESHOLD（v2.45 阈值触发才出现）已退役：tail_volume
# 实测 8/8 边界触发、0 次执行（490k 零锯齿）——阈值决定是否出现 = 不存在。
HANDOFF_PROMPT_T1 = 150_000


HANDOFF_PROMPT_T2 = 300_000


def estimate_context_tokens(transcript_path: str | Path) -> int | None:
    """从 session transcript 尾部最近一条 assistant usage 估算当前上下文 tokens。

    = input + cache_read + cache_creation（该轮看到的全部前缀）。
    文件缺失/无 usage/解析失败 -> None（宁纵勿枉：不 nudge）。
    只读尾部 512KB——transcript 可上 MB，全量读是纯浪费；usage 在每行
    assistant 记录里，尾部窗口足够覆盖最后一轮。
    """
    try:
        p = Path(transcript_path)
        size = p.stat().st_size
        with open(p, "rb") as f:
            f.seek(max(0, size - 512 * 1024))
            tail = f.read().decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    for line in reversed(tail.splitlines()):
        if '"usage"' not in line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue  # 尾部窗口可能切在半行上
        u = (rec.get("message") or {}).get("usage")
        if not isinstance(u, dict):
            continue
        try:
            return (
                int(u.get("input_tokens", 0))
                + int(u.get("cache_read_input_tokens", 0))
                + int(u.get("cache_creation_input_tokens", 0))
            )
        except (TypeError, ValueError):
            continue
    return None


def handoff_tier(est: int | None) -> str:
    """边界提示文案档位（v2.122，minor-boundary-handoff-prompt-design §2.1）。

    unknown=读不到估算（降级无数字版）/ ok=健康 / suggest=建议清理 / strong=强烈建议。
    """
    if est is None:
        return "unknown"
    if est < HANDOFF_PROMPT_T1:
        return "ok"
    if est < HANDOFF_PROMPT_T2:
        return "suggest"
    return "strong"


_HANDOFF_KINDS = ("handoff_prompt", "handoff_resolution")


def _last_handoff_event(project_root: Path, name: str) -> dict | None:
    """evidence 尾部扫描最后一条 handoff_* 记录；无记录/读失败 -> None（宁纵勿枉）。

    只读尾部 256KB：handoff 事件时间上贴近边界（提示与 resolved 间隔短），
    且证据行最大数 KB，窗口足够覆盖；尾部可能切在半行上 -> JSONDecodeError 跳过。
    """
    path = _evidence_path(project_root, name)
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - 256 * 1024))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        if "handoff_" not in line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("kind") in _HANDOFF_KINDS:
            return rec
    return None


def _write_handoff_record(project_root: Path, name: str, record: dict) -> bool:
    """append 一条 handoff_* 记录到 evidence（write_gate_verdict 同通道）。
    返回 False=写失败（宁纵勿枉：提示是主功能，留痕失败不阻断，调用方不感知）。
    """
    path = _evidence_path(project_root, name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        return False
    return True


def write_handoff_prompt(
    project_root: Path, name: str, node: Node, *, est: int | None, tier: str
) -> bool:
    """边界提示发出时留痕（v2.122 §2.2）。

    上次 prompt 未决（其后无 resolution）先补记 choice=declined——用户没清
    就走到了下一边界 = 选择上次的「不清」。记录携带 major_stage/minor_stage
    （结构字段单源 = node.phase/node.minor_key，evidence 全记录同口径）。
    """
    ok = True
    last = _last_handoff_event(project_root, name)
    if last is not None and last.get("kind") == "handoff_prompt":
        ok = _write_handoff_record(
            project_root,
            name,
            {
                "kind": "handoff_resolution",
                "choice": "declined",
                "node": last.get("node"),
                "major_stage": last.get("major_stage"),
                "minor_stage": last.get("minor_stage"),
                "ts": _now(),
            },
        )
    return (
        _write_handoff_record(
            project_root,
            name,
            {
                "kind": "handoff_prompt",
                "node": node_id(node.phase, node.sub),
                "major_stage": node.phase.capitalize(),
                "minor_stage": node.minor_key,
                "est": est,
                "tier": tier,
                "ts": _now(),
            },
        )
        and ok
    )


def write_handoff_resolution(project_root: Path, name: str, *, choice: str) -> bool:
    """SessionStart source=clear 时调用（v2.122 §2.2）：存在未决 prompt 才记。

    语义 = 「该 prompt 之后发生了 clear」；无未决 prompt 的 clear 不记录（无操作
    非失败，返回 True）。写失败 -> False（宁纵勿枉，不阻断注入）。
    """
    last = _last_handoff_event(project_root, name)
    if last is None or last.get("kind") != "handoff_prompt":
        return True
    return _write_handoff_record(
        project_root,
        name,
        {
            "kind": "handoff_resolution",
            "choice": choice,
            "node": last.get("node"),
            "major_stage": last.get("major_stage"),
            "minor_stage": last.get("minor_stage"),
            "ts": _now(),
        },
    )


# 交接包瘦身（v4 成本优化 P1-1，v4-cost-latency-optimization-design §2 P1）：
# trace 行的机械字段（purpose/skill 等）模型从注入侧已知，包内全剥；
# 前序节点 trace 再压内容（boundary/q 截断）——摘要保留语义骨架，细节按
# 产物/evidence 指针 Read 自取（合法通道）。本节点 trace 保内容全文
# （跨步一致性/装配判材），只剥机械字段。
_PACK_TRACE_DROP_KEYS = ("purpose", "skill", "kind", "major_stage", "atomic_questions")


_PACK_PRIOR_Q_MAX = 80  # 前序节点 q 截断阈值（读回标题保留前 80 字符）


_PACK_PRIOR_BOUNDARY_MAX = 100  # 前序节点 statements.boundary 截断阈值


# O3（u1-overall-cost）：交接包内「原文收录」qa 项的 a 截断阈值——收录原文
# （fetch/红队报告全文）唯一消费者是声明 pack_full_reports=True 的步（u:1 子5
# 三关质检）；其余步截断 + evidence 指针（真源 trace 不动，证据不丢）。
_PACK_REPORT_A_MAX = 200


# O1（u1-overall-cost）：driver/engine spawn 的 claude 一律禁 MCP——编排全程禁
# tavily（u:1 子4 purpose 明文禁），MCP schema 照加载却是纯税（同端点裸 claude -p
# 探针实测：tavily schema = 2,504 tok/调用前缀，u:1 单轮 ~115 调用 ≈ 0.3M
# cache_read）；且 --tools 限不住 MCP（红队 worker 经 MCP 调 tavily_extract 两次
# 实证）——strict-mcp-config + 空表 = 结构封死。front 常驻 TUI（dl-launch 起的
# 用户自由会话）不经此清单，不动。
NO_MCP_ARGS = ["--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']


# u2-residual-cost（designs/u2-residual-cost-optimization-design.md）：段前缀
# 外科剥离——置位节点的段 spawn 剥项目上下文（CLAUDE.md/auto-memory 自动加载，
# 探针实证 -11.9k/冷启动）+ 裁工具 schema（--tools 白名单，再 -14.3k）。
# env 键名是 Claude Code 2.1.234 官方开关；hooks 不受影响（探针实证——
# CLAUDE_CODE_SIMPLE=1/--bare 会连 hooks 一起灭，故走双 DISABLE 而非 SIMPLE）。
_SEGMENT_STRIP_ENV = {
    "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
}


def segment_spawn_overrides(
    node: "Node", step: "Step | None" = None
) -> "dict[str, object]":
    """段会话 spawn 覆盖单源（driver run_session/MergedSession 共用）。

    返回 {"env": {追加环境变量}, "tools": 工具白名单 tuple|None}。
    字段默认 False/None = 白名单外节点零行为变化（回滚面=字段翻转）。
    step（u3-sub3-cost）：Step 级 segment_strip_project_context 置位时同样
    剥 env——生效 = node 字段 OR step 字段（单调只增）；MergedSession 段内
    续步管线 env 进程级固定，不传 step 维持节点级语义。
    """
    strip = node.segment_strip_project_context or (
        step is not None and step.segment_strip_project_context
    )
    env = dict(_SEGMENT_STRIP_ENV) if strip else {}
    return {"env": env, "tools": node.segment_tools}


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _slim_trace_for_pack(
    seg: str, *, prior: bool, strip_reports: bool = False, full_boundary: bool = False
) -> str:
    """交接包 trace 瘦身。parse 失败原样返回（宁纵勿枉，不丢证据）。

    strip_reports（O3）：当前步非收录消费步（Step.pack_full_reports=False）时，
    qa 项标题含「原文收录」的 a 项截断到 _PACK_REPORT_A_MAX + evidence 指针——
    收录原文的唯一消费者是 u:1 子5（三关质检），其余步报告正文是死重。
    full_boundary（p1-sub1-cost 修1，Step.pack_full_prior_boundary）：前序节点
    statements.boundary 不截断——复用钉死条款要求出处逐字引用，100 字符截断
    处恰是 file:line/机制结论所在（截断逼模型翻 evidence/重验）。
    """
    try:
        rec = json.loads(seg)
    except json.JSONDecodeError:
        return seg
    if not isinstance(rec, dict):
        return seg
    out = {k: v for k, v in rec.items() if k not in _PACK_TRACE_DROP_KEYS}
    if (
        strip_reports
        and isinstance(out.get("q"), list)
        and isinstance(out.get("a"), list)
    ):
        new_a = []
        for i, a_item in enumerate(out["a"]):
            q_item = out["q"][i] if i < len(out["q"]) else ""
            if (
                isinstance(q_item, str)
                and "原文收录" in q_item
                and isinstance(a_item, str)
                and len(a_item) > _PACK_REPORT_A_MAX
            ):
                a_item = (
                    a_item[:_PACK_REPORT_A_MAX]
                    + "……（报告全文已收录于 evidence，可按需 Read 复查）"
                )
            new_a.append(a_item)
        out["a"] = new_a
    if prior:
        if isinstance(out.get("q"), list):
            out["q"] = [
                _truncate(x, _PACK_PRIOR_Q_MAX) if isinstance(x, str) else x
                for x in out["q"]
            ]
        if isinstance(out.get("statements"), list) and not full_boundary:
            slim = []
            for st in out["statements"]:
                if isinstance(st, dict) and isinstance(st.get("boundary"), str):
                    st = dict(st)
                    st["boundary"] = _truncate(st["boundary"], _PACK_PRIOR_BOUNDARY_MAX)
                slim.append(st)
            out["statements"] = slim
    return json.dumps(out, ensure_ascii=False)


def handoff_pack(project_root: Path, name: str) -> str | None:
    """机械装配交接包（/clear 后新会话注入，context-handoff-design §3）。

    内容（单源生成，禁模型自选）：
    1. 当前位置（节点 + 子步指针；逐步 purpose 由 workflow_phase 每轮注入，不重复）；
    2. 当前节点已完成各子步的**最新** trace（剥机械字段、保内容全文——跨步
       一致性/装配判材；返工历史不带，v2.12 read_evidence_for_step 已验证）；
    3. 前序已完成节点：归一化步 + 读回步的最新 trace **摘要**（v4 P1-1：boundary/q
       截断 + 机械字段剥除——全文进包 = deepseek 类端点每段首调全量 fresh 的主因，
       实测交接包随步数 47.7k->73.3k 单调涨；细节按 evidence/产物指针 Read 自取）；
    4. 当前步最新 block 判词（/clear 发生在返工中段时，新会话须知道修什么）；
    5. 已装配产物清单（路径指针，禁全文——全文内联 = 把省下的 token 又花回去）；
    6. 用户问题陈述（state.problem_statement，开场采集——drive-tasklist-render-design
       §2.4；零 trace 的首次启动也凭它生成交接包，子1 模型开场即有用户原话）。

    无 trace 且无问题陈述 -> None（首次启动不注入，调用方静默）。
    """
    state = load_state(project_root, name)
    if state is None:
        return None
    state = normalize_state(state)
    problem = (state.get("problem_statement") or "").strip()
    cur_phase, cur_sub = state["phase"], state["sub_index"]
    try:
        cur_node = get_node(cur_phase, cur_sub)
    except KeyError:
        return None
    text = read_evidence(project_root, name)
    if not text and not problem:
        return None

    # 单遍扫描：最新 trace（按 minor_stage+sub_step）+ 最新 block 判词（按 node+sub_step）。
    # 容一行多 JSON 对象（raw_decode，同 _iter_trace_segments 的容错动机）。
    latest_trace: dict[tuple, str] = {}
    latest_block: dict[tuple, str] = {}
    decoder = json.JSONDecoder()
    for line in (text or "").splitlines():
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
                break
            seg = s[idx:end]
            idx = end
            if not isinstance(rec, dict):
                continue
            if rec.get("kind") == "skill-trace":
                latest_trace[(rec.get("minor_stage"), rec.get("sub_step"))] = seg
            elif (
                rec.get("kind") == "gate"
                and rec.get("gate") == "blocked"
                and rec.get("reason")
            ):
                latest_block[(rec.get("node"), rec.get("sub_step"))] = rec["reason"]
    if not latest_trace and not problem:
        return None

    cur_step = state.get("sub_step_index", 1)
    cur_key = (phase_index(cur_phase), cur_sub)
    lines = [
        "## WORKFLOW 上下文交接包（/clear 接续——以下为机械装配的前序证据，",
        "禁止重做已完成步骤；从当前子步继续）",
        "",
    ]
    if problem:
        lines.append(f"### 用户问题陈述（开场采集原话）\n{problem}\n")
    if state.get("force_tacet"):
        # force-tacet：告知下游材料薄是设计内状态（design §5），防模型把
        # 沉默当缺漏自行补做。
        lines.append(
            "### 运行轨道：force-tacet 实验轨道\n"
            "understand/plan 仅六步脊柱执行（问题陈述 u:1#1 / 拆解分档 u:1#2 / 根因 u:1#3 / 取证 "
            "u:1#4 / 修法 plan:1#2 / 计划包 plan:4#4），其余步 TACET 静默--"
            "上游材料薄是设计内状态，非缺漏；禁自行补做已沉默的步骤。\n"
        )
    if state.get("force_fermate"):
        # fermate（plan-only）：告知终点形态（fermate-plan-only-design §3 F1），
        # 防模型按全量记忆预期/预习 plan:3。
        lines.append(
            "### 运行轨道：fermate（plan-only）\n"
            "本实例 plan 止于 plan:2（拆解任务与阶段）——plan:3/plan:4 已裁剪不存在；"
            "plan:2 末步过门控后门栏扣留，用户 /dl gate 确认收货即完结。plan.md "
            "只有「执行步骤」一节=最终交付物；禁预期/预习 plan:3/plan:4 内容。\n"
        )
    lines += [
        f"### 当前位置：{cur_node.label}（{node_id(cur_phase, cur_sub)}）子步骤 {cur_step}",
        "",
    ]
    # 当前节点已完成步的最新 trace（含当前步已有 trace——返工中段 clear 的场景）；
    # 本节点 trace 保内容全文只剥机械字段（跨步一致性/装配判材，P1-1）
    cur_step_obj = None
    if cur_node.sub_steps and 1 <= cur_step <= len(cur_node.sub_steps):
        cur_step_obj = cur_node.sub_steps[cur_step - 1]
    cur_traces = [
        (k[1], seg)
        for k, seg in latest_trace.items()
        if k[0] == cur_node.minor_key and k[1] <= cur_step
    ]
    if cur_traces:
        # O3：当前步是收录消费步（pack_full_reports=True，u:1 子5 三关质检）时
        # 包内收录原文保全文；其余步剥离（报告正文只服务质检，隔步是死重）。
        strip = not (cur_step_obj and cur_step_obj.pack_full_reports)
        lines.append(f"### 本节点（{cur_node.label}）各步最新留痕")
        for _step, seg in sorted(cur_traces):
            lines.append(_slim_trace_for_pack(seg, prior=False, strip_reports=strip))
        lines.append("")
    # 当前步最新 block 判词（返工中段 clear：新会话要知道修什么）
    reason = latest_block.get((node_id(cur_phase, cur_sub), cur_step))
    if reason:
        lines.append(f"### 当前子步最新门控判词（未通过，按此返工）\n{reason}\n")
    # 前序已完成节点：归一化步 + 读回步的最新 trace，摘要化（P1-1：
    # 全文 -> verdict 摘要 + 指针，细节按 evidence/产物 Read 自取）
    prior_sections = []
    for ph in PHASES:
        subs = range(1, sub_total(ph) + 1) if sub_total(ph) else [0]
        for sub in subs:
            if (phase_index(ph), sub) >= cur_key:
                continue
            try:
                node = get_node(ph, sub)
            except KeyError:
                continue
            if not node.sub_steps or not node.minor_key:
                continue
            n = len(node.sub_steps)
            keep = [
                _slim_trace_for_pack(
                    latest_trace[k],
                    prior=True,
                    # p1-sub1-cost 修1：本步置位 pack_full_prior_boundary 时
                    # 前序摘要 boundary 保全文（复用钉死的逐字引用材料）。
                    full_boundary=bool(
                        cur_step_obj and cur_step_obj.pack_full_prior_boundary
                    ),
                )
                for k in ((node.minor_key, n - 1), (node.minor_key, n))
                if k in latest_trace
            ]
            if keep:
                prior_sections.append(
                    f"### 前序节点「{node.label}」结论摘要（归一化 + 用户裁决）\n"
                    + "\n".join(keep)
                )
    if prior_sections:
        lines.extend(prior_sections)
        ev_path = project_root / ".claude" / "evidence" / f"{name}.jsonl"
        if cur_step_obj and cur_step_obj.pack_self_contained:
            # u2-sub2-cost：本步材料全在包内——通用「按需 Read」邀请对该步是
            # 反指（实测弱模型保险性全量读 68KB evidence 零增量），改打禁读。
            lines.append(
                "（本步所需材料已全部在包内——禁 Read evidence 全量翻找；"
                "确有缺口才按指针定点补）"
            )
        else:
            lines.append(f"（以上为摘要；前序细节按需 Read `{ev_path}`，禁凭记忆补全）")
        lines.append("")
    # 产物清单（指针非全文）
    artifacts = []
    for ph, adir in _PHASE_ARTIFACT_DIRS.items():
        f = project_root / ".claude" / adir / f"{name}.md"
        if f.is_file():
            artifacts.append(f"- {f}")
    # p2-sub1-cost L4：design.md 不入 _PHASE_ARTIFACT_DIRS（落 <root>/designs/
    # 而非 .claude/ 下），但其 slug=工作流名（v2.62 约定）——存在即入列，
    # 消费 design.md 的下游步（plan:2#1 首例）免 locate 翻找（p1-sub1-cost B1
    # 「understand.md 翻找×4」同型褶皱的预防）。
    design_md = project_root / "designs" / f"{name}-design.md"
    if design_md.is_file():
        artifacts.append(f"- {design_md}")
    if artifacts:
        lines.append("### 已装配产物（按需 Read，勿重复装配）")
        lines.extend(artifacts)
        lines.append("")
    return "\n".join(lines)
