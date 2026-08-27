"""dl_dashboard.metrics：段台账 join 段统计（新埋点 + 旧 drive-stream 回退）。"""
from __future__ import annotations

import json
from pathlib import Path

from dl_dashboard.metrics import collect_stats, totals
from dl_dashboard.scanner import meta_root


def _mk(project: Path, name: str) -> Path:
    meta = meta_root(project, name)
    meta.mkdir(parents=True)
    state = {
        "name": name,
        "segment_sessions": [
            {"ts": "2026-08-27T09:00:00", "session_id": "sid-new", "kind": "headless-step",
             "node": "plan:1", "sub_step": 1, "note": "rc=0"},
            {"ts": "2026-08-27T09:10:00", "session_id": "sid-legacy", "kind": "headless-step",
             "node": "plan:1", "sub_step": 2, "note": "rc=0"},
            {"ts": "2026-08-27T09:20:00", "session_id": "sid-none", "kind": "headless-step",
             "node": "plan:2", "sub_step": 1, "note": "rc=1"},
        ],
    }
    (meta / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return meta


def test_collect_joins_new_and_legacy_stats(tmp_path):
    meta = _mk(tmp_path, "demo")
    # 新埋点（Task 1 产物）
    (meta / "segment_stats.jsonl").write_text(
        json.dumps({"ts": "t", "session_id": "sid-new", "num_turns": 5,
                    "duration_ms": 61000, "total_cost_usd": 0.5}) + "\n",
        encoding="utf-8",
    )
    # 旧工作流：drive-stream.jsonl 里混噪声行的 result 事件
    with open(meta / "drive-stream.jsonl", "w", encoding="utf-8") as fh:
        fh.write("[log_xx] sending request {not json}\n")
        fh.write(json.dumps({"type": "assistant", "session_id": "sid-legacy"}) + "\n")
        fh.write(json.dumps({"type": "result", "session_id": "sid-legacy",
                             "num_turns": 3, "duration_ms": 30500,
                             "total_cost_usd": 0.25}) + "\n")
    stats = collect_stats(tmp_path, "demo", tmp_path / "cache")
    by_sid = {s.session_id: s for s in stats}
    assert by_sid["sid-new"].num_turns == 5
    assert by_sid["sid-new"].duration_s == 61
    assert by_sid["sid-new"].cost_usd == 0.5
    assert by_sid["sid-legacy"].num_turns == 3
    assert by_sid["sid-legacy"].duration_s == 30
    assert by_sid["sid-none"].num_turns is None  # 无统计如实 None，不编 0
    t = totals(stats)
    assert t["num_turns"] == 8 and t["duration_s"] == 91
    assert abs(t["cost_usd"] - 0.75) < 1e-9


def test_legacy_scan_incremental_via_offset_cache(tmp_path):
    meta = _mk(tmp_path, "demo")
    (meta / "segment_stats.jsonl").write_text("", encoding="utf-8")
    stream = meta / "drive-stream.jsonl"
    stream.write_text(
        json.dumps({"type": "result", "session_id": "sid-legacy",
                    "num_turns": 3, "duration_ms": 30000, "total_cost_usd": 0.2}) + "\n",
        encoding="utf-8",
    )
    cache = tmp_path / "cache"
    collect_stats(tmp_path, "demo", cache)
    # 追加一行后再扫：offset 书签生效（文件被截断则重置重扫）
    with open(stream, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "result", "session_id": "sid-none",
                             "num_turns": 9, "duration_ms": 1000,
                             "total_cost_usd": 0.01}) + "\n")
    stats = {s.session_id: s for s in collect_stats(tmp_path, "demo", cache)}
    assert stats["sid-legacy"].num_turns == 3   # 旧结果仍在
    assert stats["sid-none"].num_turns == 9     # 增量被捕获
