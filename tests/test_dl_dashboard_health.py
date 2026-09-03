"""dl_dashboard.health：系统健康页跨实例聚合（evolution-up P2，design §3）。

改进队列数据化：哪个 gate 真实运行中最常 thrash（block 榜）、哪个节点
成本离群（p50/p90 榜）、判据申诉集中点（dispute 榜）——榜首即下一个
framing 反转 / mech 下沉候选。
"""

from __future__ import annotations

import json
from pathlib import Path

from dl_dashboard.health import health_report
from dl_dashboard.scanner import meta_root


def _mk_instance(project: Path, name: str, gate_lines=(), segs=(), stats_lines=()):
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
                "created_at": "c",
                "history": [],
            }
        ),
        encoding="utf-8",
    )
    if gate_lines:
        ev = project / ".claude" / "evidence"
        ev.mkdir(parents=True, exist_ok=True)
        (ev / f"{name}.jsonl").write_text(
            "\n".join(gate_lines) + "\n", encoding="utf-8"
        )
    if stats_lines:
        (meta / "segment_stats.jsonl").write_text(
            "\n".join(stats_lines) + "\n", encoding="utf-8"
        )


def _gate(node, sub_step, verdict):
    return json.dumps(
        {
            "kind": "gate",
            "node": node,
            "sub_step": sub_step,
            "gate": verdict,
            "ts": "t",
            "reason": "r",
        }
    )


def _trace(minor, sub_step):
    return json.dumps(
        {
            "kind": "skill-trace",
            "minor_stage": minor,
            "sub_step": sub_step,
            "q": [],
            "a": [],
        }
    )


def test_health_aggregates_gate_board_across_instances(tmp_path):
    proj = tmp_path / "p"
    # 实例 1：plan:2#3 两连 block 后过（3 提交 2 block）；plan:3#1 一次过
    _mk_instance(
        proj,
        "wf1",
        [
            _trace("TaskBreakdown", 3),
            _gate("plan:2", 3, "blocked"),
            _trace("TaskBreakdown", 3),
            _gate("plan:2", 3, "blocked"),
            _trace("TaskBreakdown", 3),
            _trace("CapabilityToolSelection", 1),
        ],
    )
    # 实例 2：plan:2#3 又一连 block 后过（2 提交 1 block）
    _mk_instance(
        proj,
        "wf2",
        [
            _trace("TaskBreakdown", 3),
            _gate("plan:2", 3, "blocked"),
            _trace("TaskBreakdown", 3),
        ],
    )
    # 实例 3：零 gate（新实例）
    _mk_instance(proj, "wf3")
    r = health_report([proj], tmp_path / "c")
    assert r["instances"] == 3
    board = {b["step"]: b for b in r["gate_board"]}
    assert board["plan:2#3"]["blocked"] == 3
    assert board["plan:2#3"]["judged"] == 2  # 两个实例判决过该步
    assert board["plan:2#3"]["block_rate"] == 0.6  # 3 block / 5 提交
    assert r["gate_board"][0]["step"] == "plan:2#3"  # block 数降序榜首
    # 零 block 步也上榜（分母全量在），但排后
    assert board["plan:3#1"]["blocked"] == 0


def test_health_node_cost_percentiles(tmp_path):
    proj = tmp_path / "p"
    for i, cost in enumerate((0.2, 0.4, 1.0)):
        _mk_instance(
            proj,
            f"wf{i}",
            segs=[
                {
                    "ts": "t",
                    "session_id": f"s{i}",
                    "kind": "headless-step",
                    "node": "plan:1",
                    "sub_step": 1,
                    "note": "rc=0",
                }
            ],
            stats_lines=[
                json.dumps(
                    {
                        "session_id": f"s{i}",
                        "num_turns": 1,
                        "duration_ms": 1000 * (i + 1),
                        "total_cost_usd": cost,
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "cache_read_input_tokens": 1,
                        "cache_creation_input_tokens": 1,
                    }
                )
            ],
        )
    r = health_report([proj], tmp_path / "c")
    row = next(n for n in r["node_costs"] if n["node"] == "plan:1")
    assert row["instances"] == 3
    assert row["p50_cost"] == 0.4
    assert row["p90_cost"] >= row["p50_cost"]
    assert row["total_cost"] == 1.6


def test_health_dispute_board(tmp_path):
    proj = tmp_path / "p"
    _mk_instance(
        proj,
        "wf1",
        [
            json.dumps(
                {
                    "kind": "rubric-dispute",
                    "node": "plan:2",
                    "sub_step": 3,
                    "ts": "t",
                    "reason": "x",
                }
            ),
            json.dumps(
                {
                    "kind": "rubric-dispute",
                    "node": "plan:2",
                    "sub_step": 3,
                    "ts": "t",
                    "reason": "y",
                }
            ),
            _gate("plan:2", 3, "passed"),
        ],
    )
    r = health_report([proj], tmp_path / "c")
    assert r["dispute_board"][0]["step"] == "plan:2#3"
    assert r["dispute_board"][0]["count"] == 2


def test_health_bad_instance_isolated(tmp_path):
    proj = tmp_path / "p"
    _mk_instance(proj, "wf_ok", [_gate("plan:2", 3, "passed")])
    bad = meta_root(proj, "wf_bad")
    bad.mkdir(parents=True)
    (bad / "state.json").write_text("{损坏", encoding="utf-8")
    r = health_report([proj], tmp_path / "c")
    assert r["instances"] == 1
    assert any("wf_bad" in e["name"] for e in r["errors"])  # 坏实例如实暴露
