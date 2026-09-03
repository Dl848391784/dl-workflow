"""dl_dashboard.audit：实例自动审计（evolution-up P1，evolution-up-design §2）。

口径（实查沉淀）：子步骤级只有 block 落 kind=gate，pass 不留痕——
「通过」由 traces > blocked 推导；读回确认步（gate=None）无 judge 不计。
"""

from __future__ import annotations

import json
from pathlib import Path

from dl_dashboard.audit import audit_report, gate_outcomes, node_costs
from dl_dashboard.scanner import meta_root


def _gate(node, sub_step, verdict, ts="t", reason=""):
    return json.dumps(
        {
            "kind": "gate",
            "node": node,
            "sub_step": sub_step,
            "gate": verdict,
            "ts": ts,
            "reason": reason,
        },
        ensure_ascii=False,
    )


def _trace(minor, sub_step):
    return json.dumps(
        {
            "kind": "skill-trace",
            "minor_stage": minor,
            "sub_step": sub_step,
            "q": ["q"],
            "a": ["a"],
        },
        ensure_ascii=False,
    )


def _mk(project: Path, name: str, evidence_lines=(), segs=(), stats_lines=()):
    meta = meta_root(project, name)
    meta.mkdir(parents=True)
    (meta / "state.json").write_text(
        json.dumps(
            {
                "name": name,
                "phase": "plan",
                "sub_index": 2,
                "node": "plan:2",
                "segment_sessions": list(segs),
                "force_tacet": True,
                "tacet_upgraded": ["understand:2#2"],
                "created_at": "c",
                "history": [],
            }
        ),
        encoding="utf-8",
    )
    if evidence_lines:
        ev = project / ".claude" / "evidence"
        ev.mkdir(parents=True, exist_ok=True)
        (ev / f"{name}.jsonl").write_text(
            "\n".join(evidence_lines) + "\n", encoding="utf-8"
        )
    if stats_lines:
        (meta / "segment_stats.jsonl").write_text(
            "\n".join(stats_lines) + "\n", encoding="utf-8"
        )
    return meta


def test_gate_outcomes_first_pass_rate(tmp_path):
    _mk(
        tmp_path,
        "demo",
        evidence_lines=[
            # plan:2#3（TaskBreakdown 锚点核验，有 judge）：3 次提交 2 次 block 后过
            _trace("TaskBreakdown", 3),
            _gate("plan:2", 3, "blocked", "t1", "缺出处"),
            _trace("TaskBreakdown", 3),
            _gate("plan:2", 3, "blocked", "t2", "复合句"),
            _trace("TaskBreakdown", 3),
            # plan:2#4：一次通过
            _trace("TaskBreakdown", 4),
            # plan:3#1：1 次提交被 block，未过
            _trace("CapabilityToolSelection", 1),
            _gate("plan:3", 1, "blocked", "t5", "幽灵能力"),
        ],
    )
    g = gate_outcomes(tmp_path, "demo")
    assert g["judged"] == 3
    assert g["first_pass"] == 1  # 仅 plan:2#4 首判即过
    assert g["first_pass_rate"] == round(1 / 3, 3)
    assert g["blocked_total"] == 3
    steps = {(s["node"], s["sub_step"]): s for s in g["steps"]}
    assert steps[("plan:2", 3)]["attempts_to_pass"] == 3
    assert steps[("plan:2", 3)]["status"] == "passed"
    assert steps[("plan:3", 1)]["attempts_to_pass"] is None  # 未过如实 None
    assert steps[("plan:3", 1)]["status"] == "blocked"
    assert "幽灵能力" in steps[("plan:3", 1)]["last_reason"]


def test_gate_outcomes_confirm_steps_not_judged(tmp_path):
    # 读回确认步（TaskBreakdown#5，gate=None）有 trace 无 judge——不计通过率
    _mk(
        tmp_path,
        "demo",
        evidence_lines=[
            _trace("TaskBreakdown", 4),
            _trace("TaskBreakdown", 5),
        ],
    )
    g = gate_outcomes(tmp_path, "demo")
    assert g["judged"] == 1 and g["first_pass"] == 1
    assert g["confirm_steps"] == 1
    s5 = next(s for s in g["steps"] if s["sub_step"] == 5)
    assert s5["status"] == "confirm"


def test_gate_outcomes_node_gates_and_disputes(tmp_path):
    _mk(
        tmp_path,
        "demo",
        evidence_lines=[
            _trace("TaskBreakdown", 4),
            json.dumps(
                {
                    "kind": "gate",
                    "node": "plan:2",
                    "sub_step": 5,
                    "gate": "passed",
                    "ts": "t8",
                    "via": "fermate-auto-complete",
                    "gate_mech": "artifact_contains",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "kind": "rubric-dispute",
                    "node": "plan:2",
                    "sub_step": 3,
                    "ts": "t9",
                    "reason": "判据自相矛盾",
                },
                ensure_ascii=False,
            ),
        ],
    )
    g = gate_outcomes(tmp_path, "demo")
    assert len(g["node_gates"]) == 1
    assert g["node_gates"][0]["via"] == "fermate-auto-complete"
    assert len(g["disputes"]) == 1
    assert "判据自相矛盾" in g["disputes"][0]["reason"]


def test_gate_outcomes_unknown_minor_marked(tmp_path):
    # 节点树外的旧 minor（历史实例/树演进）——如实 unknown，不入通过率
    _mk(
        tmp_path,
        "demo",
        evidence_lines=[
            _trace("TaskBreakdown", 4),
            _trace("OldRetiredNode", 2),
        ],
    )
    g = gate_outcomes(tmp_path, "demo")
    assert g["judged"] == 1
    s_old = next(s for s in g["steps"] if s["node"] == "OldRetiredNode")
    assert s_old["status"] == "unknown"


def test_gate_outcomes_no_evidence(tmp_path):
    _mk(tmp_path, "demo")
    g = gate_outcomes(tmp_path, "demo")
    assert g["judged"] == 0 and g["first_pass_rate"] is None  # 无数据如实 None
    assert g["steps"] == [] and g["disputes"] == []


def test_gate_outcomes_bad_lines_isolated(tmp_path):
    _mk(
        tmp_path,
        "demo",
        evidence_lines=[
            _trace("TaskBreakdown", 4),
            "{not json 噪声行",
        ],
    )
    g = gate_outcomes(tmp_path, "demo")
    assert g["judged"] == 1 and g["first_pass"] == 1


def test_node_costs_aggregates_by_node(tmp_path):
    segs = [
        {
            "ts": "t1",
            "session_id": "s1",
            "kind": "headless-step",
            "node": "plan:1",
            "sub_step": 1,
            "note": "rc=0",
        },
        {
            "ts": "t2",
            "session_id": "s2",
            "kind": "headless-step",
            "node": "plan:1",
            "sub_step": 2,
            "note": "rc=0",
        },
        {
            "ts": "t3",
            "session_id": "s3",
            "kind": "headless-step",
            "node": "plan:2",
            "sub_step": 1,
            "note": "rc=0",
        },
    ]
    stats = [
        json.dumps(
            {
                "session_id": "s1",
                "num_turns": 5,
                "duration_ms": 60000,
                "total_cost_usd": 0.5,
                "input_tokens": 1000,
                "output_tokens": 200,
                "cache_read_input_tokens": 3000,
                "cache_creation_input_tokens": 50,
            }
        ),
        json.dumps(
            {
                "session_id": "s2",
                "num_turns": 3,
                "duration_ms": 30000,
                "total_cost_usd": 0.25,
                "input_tokens": 500,
                "output_tokens": 100,
                "cache_read_input_tokens": 900,
                "cache_creation_input_tokens": 10,
            }
        ),
    ]
    _mk(tmp_path, "demo", segs=segs, stats_lines=stats)
    rows = {r["node"]: r for r in node_costs(tmp_path, "demo", tmp_path / "c")}
    assert rows["plan:1"]["segments"] == 2
    assert rows["plan:1"]["turns"] == 8
    assert rows["plan:1"]["cost_usd"] == 0.75
    assert rows["plan:1"]["duration_s"] == 90
    assert rows["plan:2"]["segments"] == 1
    assert rows["plan:2"]["cost_usd"] == 0  # 无统计如实 0（段在账、统计缺）


def test_audit_report_shape(tmp_path):
    _mk(
        tmp_path,
        "demo",
        evidence_lines=[_trace("TaskBreakdown", 4)],
        segs=[
            {
                "ts": "t1",
                "session_id": "s1",
                "kind": "headless-step",
                "node": "plan:1",
                "sub_step": 1,
                "note": "rc=0",
            }
        ],
    )
    r = audit_report(tmp_path, "demo", tmp_path / "c")
    assert r["name"] == "demo" and r["phase"] == "plan"
    assert r["track"]["force_tacet"] is True
    assert r["track"]["tacet_upgraded"] == ["understand:2#2"]
    assert r["gates"]["judged"] == 1
    assert isinstance(r["nodes"], list) and "totals" in r
