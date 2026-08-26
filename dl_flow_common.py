#!/usr/bin/env python3
"""
dl_flow_common - state/trace 低层 helper（engine 与 checks 共用真源）。

拆分缘由（2026-08-27）：dl_flow_checks.py（v2.27 机械预检家族）从
dl_flow_engine.py 抽出后，校验函数与 engine 本体都依赖这批 state 装载 /
trace 分段 helper——下沉本模块打破双向依赖（common 只依赖 dl_flow_nodes）。
engine 经 re-export 保持 eng.<name> 访问面不变。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from dl_flow_nodes import Node, current_node_id, get_node, sub_total


def state_path(project_root: Path, name: str) -> Path:
    return project_root / ".claude" / "workflows" / name / "state.json"


def load_state(project_root: Path, name: str) -> dict[str, Any] | None:
    f = state_path(project_root, name)
    if not f.exists():
        return None
    try:
        with f.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    """补齐新字段（node / node_attempts / sub_step_index）,旧 state 向后兼容。

    守 no silent fallback：node 字段缺失时按 phase+sub 推导补默认,不静默用错值。
    推导值与显式 node 不一致时**报错暴露**（防两者失同步）。
    §orchestration v2：sub_step_index 缺失按节点有无 sub_steps 补默认（1 / 0）；
    显式值与 sub_steps 总数不符（超出范围）-> 报错暴露。
    """
    phase = state.get("phase", "understand")
    sub = state.get("sub_index", 1 if sub_total(phase) > 0 else 0)
    derived = current_node_id(phase, sub)
    if "node" not in state:
        state["node"] = derived
    elif state["node"] != derived:
        # 显式 node 与 phase+sub 推导不一致 -> 暴露,不猜
        raise ValueError(
            f"state.node={state['node']!r} 与 phase+sub 推导={derived!r} 不一致"
        )
    state.setdefault("node_attempts", 0)
    # §substep-gate-at-stop S1：子步骤门控判定游标（key=<node>#<sub_step> -> 最新已判 trace 行 sha1）。
    state.setdefault("last_judged_trace", {})
    # §substep-gate-at-stop S10：PreToolUse 步骤围栏开关（/dl fence on|off）。
    state.setdefault("enforce_step_fence", True)
    # §orchestration v2：sub_step_index 补默认 + 范围校验
    node = get_node(phase, sub)
    if node.sub_steps:
        if "sub_step_index" not in state:
            state["sub_step_index"] = 1  # 有子步骤 -> 起于首步
        else:
            n = state["sub_step_index"]
            total = len(node.sub_steps)
            if not (1 <= n <= total):
                raise ValueError(
                    f"state.sub_step_index={n} 越界（节点 {derived} 有 {total} 子步骤）"
                )
    else:
        state.setdefault("sub_step_index", 0)  # 无子步骤 -> 0
    return state


def _evidence_path(project_root: Path, name: str) -> Path:
    return project_root / ".claude" / "evidence" / (name + ".jsonl")


def read_evidence(project_root: Path, name: str) -> str | None:
    """读 evidence/<name>.jsonl 全文，供 judge 作 artifact_content 校验。

    §define-problem-verify-gate：understand:1 的 rubric 依赖 evidence.jsonl，
    Stop hook 调本函数取文件文本喂 judge。缺失/读失败返回 None
    （no silent fallback：judge 拿不到证据 -> 按 rubric 判 block，不默认放行）。
    """
    p = _evidence_path(project_root, name)
    try:
        return p.read_text(encoding="utf-8") if p.exists() else None
    except OSError:
        return None


def _node_entered_at(state: dict[str, Any], node: Node) -> float | None:
    """当前节点的 entered_at（epoch）；无记录/解析失败 -> None（降级仅存在性检查）。

    新鲜度基准（§8.3，artifact-mech-gate-design §1.1 #4）：产物须在本节点内
    写盘——装配义务锚定末子步骤，早于本节点进入时间的文件 = 预写/残留。
    """
    for h in reversed(state.get("history") or []):
        if h.get("phase") == node.phase and h.get("sub") == node.sub:
            s = h.get("entered_at")
            if not s:
                return None
            try:
                return time.mktime(time.strptime(s, "%Y-%m-%dT%H:%M:%S"))
            except (ValueError, TypeError, OverflowError):
                return None
    return None


def _iter_trace_segments(
    text: str, sub_step_index: int, minor_stage: str | None = None
):
    """逐行扫描 evidence 文本，产出匹配 trace 的 (raw_segment, rec)。

    容错（2026-07-25，demo 74f82d93）：Write 无尾换行 + printf 追加会让两个
    JSON 对象粘在一行，按行 json.loads 会整行跳过 -> trace「隐形」
    （S13 误判无 trace 强制参与）。用 raw_decode 循环扫一行内多个 JSON 对象。
    匹配：kind=skill-trace + sub_step == sub_step_index。
    minor_stage（2026-07-26，goals-and-value-substeps-design）：多编排节点
    （understand:1 ProblemContext / understand:2 GoalsAndValue）共用一个
    evidence 文件且 sub_step 都从 1 起——不按 minor_stage 过滤，ProblemContext
    子1 的 trace 会被 GoalsAndValue 子1 的门控/围栏误读（跨节点串号）。
    None=不过滤（向后兼容）；指定时缺 minor_stage 字段的旧记录不匹配
    （显式不算数，no silent fallback）。
    """
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
            if (
                isinstance(rec, dict)
                and rec.get("kind") == "skill-trace"
                and rec.get("sub_step") == sub_step_index
                and (minor_stage is None or rec.get("minor_stage") == minor_stage)
            ):
                yield s[idx:end], rec
            idx = end


def read_evidence_for_step(
    project_root: Path, name: str, sub_step_index: int, minor_stage: str | None = None
) -> str | None:
    """读 evidence 喂 judge 的子步骤裁剪版（2026-07-26，judge 输入 scope 化）。

    背景：子步骤 gate 原先把 evidence **全文**喂 judge，输入随步数线性膨胀
    （demo fbdb6ebd 实测 judge input 3.1k -> 14.9k，8 次累计 ~63k tokens，
    总量 O(n²)），大输入还拉高 judge 超时风险。子步骤 rubric 实际只需：
    当前步 trace（判对象）+ 前序各步**最新** trace（一致性锚点，
    如子5 rubric 要求与子4 verdict 逐项一致）。
    裁剪规则：
    - 只含 kind=skill-trace 且 sub_step ≤ sub_step_index 的记录；
    - 每个 sub_step 只留**最新一条**——返工历史不喂（judge 本就以最新为准，
      历史是纯 token 开销）；
    - kind=gate 裁决记录不喂（judge 判 trace 内容，不判裁决留痕）；
    - minor_stage 指定时只取该节点的 trace（跨节点串号见 _iter_trace_segments）。
    输出按 sub_step 升序拼行（append 协议下与原文顺序一致）。
    无文件/读失败/无匹配 -> None（与 read_evidence 同语义：judge 拿不到
    证据 -> 判 block，no silent fallback）。
    """
    text = read_evidence(project_root, name)
    if not text:
        return None
    latest: dict[int, str] = {}
    for k in range(1, sub_step_index + 1):
        for seg, _rec in _iter_trace_segments(text, k, minor_stage):
            latest[k] = seg
    if not latest:
        return None
    return "\n".join(latest[k] for k in sorted(latest))
