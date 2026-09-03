"""实例自动审计：每轮运行的例行体检（evolution-up P1，evolution-up-design §2）。

原料全在盘上，纯读侧零模型：
- evidence kind=skill-trace 行 -> 步级尝试次数（每次提交一条 trace）
- evidence kind=gate/gate=blocked 行 -> block 判词（v2.26 起落 evidence）
- evidence kind=gate/gate=passed 行 -> 节点门/闸门通过裁决（§8.6c）
- kind=rubric-dispute 行 -> 判据申诉清单（v2.30 通道的真值出口）
- metrics.collect_stats 段台账 -> 节点成本聚合

口径（实查沉淀）：子步骤级只有 block 落 kind=gate，pass 不留痕——
「通过」由 traces > blocked 推导（最后一次提交未被判 block 即过）；
读回确认步（Step.gate is None，dl_flow_nodes 单源）无 judge 不计入通过率。
坏行/缺文件一律降级（如实 None/空集），单点损坏不拖垮整页。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from dl_dashboard import metrics
from dl_dashboard.scanner import meta_root
from dl_flow_nodes import _NODES

log = logging.getLogger("dl_dashboard.audit")


def _step_judge_map() -> dict[tuple, tuple[str, bool]]:
    """(minor_stage, sub_step) -> (node_id, 是否有 judge)——dl_flow_nodes 单源。

    读回确认步 gate=None（免判，不计一次通过率分子分母）；节点树外的旧
    minor（历史实例/树演进）不进本表 -> 调用方按 unknown 处理。
    """
    m: dict[tuple, tuple[str, bool]] = {}
    for nid, node in _NODES.items():
        if not node.sub_steps or not node.minor_key:
            continue
        for i, st in enumerate(node.sub_steps, 1):
            m[(node.minor_key, i)] = (nid, st.gate is not None)
    return m


def gate_outcomes(project: Path, name: str) -> dict:
    """evidence 裁决信号 -> 步级判决聚合 + 一次通过率。

    一次通过 = 有 judge 的步 traces==1 且零 block；attempts_to_pass =
    通过时的提交次数（traces > blocked 时 = traces，否则 None=未过/人工放行）。
    """
    p = project / ".claude" / "evidence" / f"{name}.jsonl"
    traces: dict[tuple, int] = {}
    blocks: dict[tuple, dict] = {}
    node_gates: list[dict] = []
    disputes: list[dict] = []
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if '"kind"' not in line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                log.warning("evidence 损坏行跳过: %s", p, exc_info=True)
                continue
            kind = d.get("kind")
            if kind == "skill-trace":
                key = (str(d.get("minor_stage", "?")), int(d.get("sub_step") or 0))
                traces[key] = traces.get(key, 0) + 1
            elif kind == "gate" and d.get("gate") == "blocked":
                key = (str(d.get("node", "?")), int(d.get("sub_step") or 0))
                b = blocks.setdefault(key, {"count": 0, "last_reason": ""})
                b["count"] += 1
                b["last_reason"] = str(d.get("reason", ""))[:300]
            elif kind == "gate" and d.get("gate") == "passed":
                node_gates.append({
                    "node": str(d.get("node", "?")),
                    "sub_step": d.get("sub_step"),
                    "ts": str(d.get("ts", "")),
                    "via": str(d.get("via", "")),
                })
            elif kind == "rubric-dispute":
                disputes.append({
                    "node": str(d.get("node", "?")),
                    "sub_step": d.get("sub_step"),
                    "ts": str(d.get("ts", "")),
                    "reason": str(d.get("reason") or d.get("text") or ""),
                })
    jmap = _step_judge_map()
    steps: list[dict] = []
    for (minor, sub), tc in traces.items():
        info = jmap.get((minor, sub))
        nid, has_judge = info if info else (minor, None)
        bl = blocks.get((nid, sub), {"count": 0, "last_reason": ""})
        blocked = bl["count"]
        if has_judge is None:
            status = "unknown"  # 节点树外旧步——如实标，不入通过率
        elif not has_judge:
            status = "confirm"  # 免判步（读回确认类，gate=None）
        elif tc > blocked:
            status = "passed"
        else:
            status = "blocked"  # 末次提交被判 block（未过 / 人工 step-pass）
        steps.append({
            "node": nid, "sub_step": sub, "traces": tc, "blocked": blocked,
            "status": status,
            "attempts_to_pass": tc if status == "passed" else None,
            "last_reason": bl["last_reason"],
        })
    steps.sort(key=lambda r: (r["node"], r["sub_step"]))
    judged = [s for s in steps if s["status"] in ("passed", "blocked")]
    first_pass = sum(1 for s in judged
                     if s["status"] == "passed" and s["traces"] == 1)
    return {
        "steps": steps,
        "judged": len(judged),
        "first_pass": first_pass,
        "first_pass_rate": round(first_pass / len(judged), 3) if judged else None,
        "blocked_total": sum(s["blocked"] for s in steps),
        "confirm_steps": sum(1 for s in steps if s["status"] == "confirm"),
        "node_gates": node_gates,
        "disputes": disputes,
    }


def node_costs(project: Path, name: str, cache_dir: Path) -> list[dict]:
    """段台账按节点聚合成本（段在账但统计缺 = 0，如实不编）。"""
    stats = metrics.collect_stats(project, name, cache_dir)
    by_node: dict[str, dict] = {}
    for s in stats:
        n = by_node.setdefault(s.node, {
            "node": s.node, "segments": 0, "turns": 0, "duration_s": 0,
            "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
            "cache_read": 0,
        })
        n["segments"] += 1
        n["turns"] += s.num_turns or 0
        n["duration_s"] += s.duration_s or 0
        n["cost_usd"] += s.cost_usd or 0.0
        n["input_tokens"] += s.input_tokens or 0
        n["output_tokens"] += s.output_tokens or 0
        n["cache_read"] += s.cache_read_input_tokens or 0
    for n in by_node.values():
        n["cost_usd"] = round(n["cost_usd"], 4)
    return sorted(by_node.values(), key=lambda r: -r["cost_usd"])


def audit_report(project: Path, name: str, cache_dir: Path) -> dict:
    """实例审计总装：元信息（轨道/位置）+ 门控裁决 + 节点成本 + 总账。"""
    state_p = meta_root(project, name) / "state.json"
    state = json.loads(state_p.read_text(encoding="utf-8"))
    stats = metrics.collect_stats(project, name, cache_dir)
    return {
        "name": name,
        "phase": str(state.get("phase", "?")),
        "node": str(state.get("node", "?")),
        "created_at": str(state.get("created_at", "")),
        "track": {
            "force_tacet": bool(state.get("force_tacet")),
            "force_fermate": bool(state.get("force_fermate")),
            "tacet_upgraded": list(state.get("tacet_upgraded") or []),
        },
        "gates": gate_outcomes(project, name),
        "nodes": node_costs(project, name, cache_dir),
        "totals": metrics.totals(stats),
    }
