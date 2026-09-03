"""系统健康页：跨实例聚合（evolution-up P2，evolution-up-design §3）。

改进队列数据化——「哪个 gate 真实运行中最常 thrash」由全部历史实例的
裁决数据自动回答，不再靠偶发审计碰运气：
- gate 榜：(node#step) x {判决实例数 / block 数 / block 率}，block 数降序
- 节点成本榜：node x {实例数 / p50 / p90 / 总成本}
- dispute 榜：判据申诉集中点（v2.30 通道的真值出口）

单实例损坏隔离（errors 如实暴露，不拖垮全局，scanner 同姿势）。
"""
from __future__ import annotations

import logging
from pathlib import Path

from dl_dashboard import audit
from dl_dashboard.scanner import iter_workflow_names

log = logging.getLogger("dl_dashboard.health")


def _pct(sorted_vals: list[float], q: float) -> float | None:
    """最近秩百分位（无插值，小样本稳定）。"""
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, int(len(sorted_vals) * q + 0.999999) - 1)
    return round(sorted_vals[max(0, idx)], 4)


def health_report(projects, cache_dir: Path) -> dict:
    gates: dict[str, dict] = {}
    disputes: dict[str, int] = {}
    cost_vals: dict[str, list[float]] = {}
    dur_vals: dict[str, list[float]] = {}
    instances = 0
    errors: list[dict] = []
    for project in projects:
        project = Path(project)
        for name in iter_workflow_names(project):
            try:
                g = audit.gate_outcomes(project, name)
                nc = audit.node_costs(project, name, cache_dir)
            except Exception as exc:  # noqa: BLE001 - 隔离边界，errors 即暴露面
                log.warning("health 聚合跳过坏实例 %s/%s", project, name, exc_info=True)
                errors.append({"project": str(project), "name": name,
                               "error": str(exc)})
                continue
            instances += 1
            for s in g["steps"]:
                if s["status"] not in ("passed", "blocked"):
                    continue  # 免判/unknown 步不进 gate 榜（audit 口径单源）
                key = f"{s['node']}#{s['sub_step']}"
                row = gates.setdefault(key, {
                    "step": key, "judged": 0, "blocked": 0, "verdicts": 0,
                })
                row["judged"] += 1
                row["blocked"] += s["blocked"]
                row["verdicts"] += s["traces"]
            for d in g["disputes"]:
                key = f"{d['node']}#{d['sub_step']}"
                disputes[key] = disputes.get(key, 0) + 1
            for n in nc:
                if n["segments"]:
                    cost_vals.setdefault(n["node"], []).append(n["cost_usd"])
                    dur_vals.setdefault(n["node"], []).append(n["duration_s"])
    gate_board = []
    for r in gates.values():
        r["block_rate"] = round(r["blocked"] / r["verdicts"], 3) if r["verdicts"] else 0
        gate_board.append(r)
    gate_board.sort(key=lambda r: (-r["blocked"], -r["judged"]))
    node_costs = []
    for node, vals in cost_vals.items():
        vals_s = sorted(vals)
        durs_s = sorted(dur_vals[node])
        node_costs.append({
            "node": node,
            "instances": len(vals),
            "total_cost": round(sum(vals), 4),
            "p50_cost": _pct(vals_s, 0.5),
            "p90_cost": _pct(vals_s, 0.9),
            "p50_duration_s": _pct(durs_s, 0.5),
            "p90_duration_s": _pct(durs_s, 0.9),
        })
    node_costs.sort(key=lambda r: -r["total_cost"])
    dispute_board = sorted(
        ({"step": k, "count": v} for k, v in disputes.items()),
        key=lambda r: -r["count"],
    )
    return {
        "instances": instances,
        "gate_board": gate_board,
        "node_costs": node_costs,
        "dispute_board": dispute_board,
        "errors": errors,
    }
