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
    # 新埋点（Task 1 产物）：token 平铺键
    (meta / "segment_stats.jsonl").write_text(
        json.dumps({"ts": "t", "session_id": "sid-new", "num_turns": 5,
                    "duration_ms": 61000, "total_cost_usd": 0.5,
                    "input_tokens": 1000, "output_tokens": 200,
                    "cache_read_input_tokens": 3000, "cache_creation_input_tokens": 50}) + "\n",
        encoding="utf-8",
    )
    # 旧工作流：drive-stream.jsonl 里混噪声行的 result 事件（token 嵌 usage）
    with open(meta / "drive-stream.jsonl", "w", encoding="utf-8") as fh:
        fh.write("[log_xx] sending request {not json}\n")
        fh.write(json.dumps({"type": "assistant", "session_id": "sid-legacy"}) + "\n")
        fh.write(json.dumps({"type": "result", "session_id": "sid-legacy",
                             "num_turns": 3, "duration_ms": 30500,
                             "total_cost_usd": 0.25,
                             "usage": {"input_tokens": 500, "output_tokens": 100,
                                       "cache_read_input_tokens": 900,
                                       "cache_creation_input_tokens": 10}}) + "\n")
    stats = collect_stats(tmp_path, "demo", tmp_path / "cache")
    by_sid = {s.session_id: s for s in stats}
    assert by_sid["sid-new"].num_turns == 5
    assert by_sid["sid-new"].duration_s == 61
    assert by_sid["sid-new"].cost_usd == 0.5
    assert by_sid["sid-new"].input_tokens == 1000
    assert by_sid["sid-new"].cache_creation_input_tokens == 50
    assert by_sid["sid-legacy"].num_turns == 3
    assert by_sid["sid-legacy"].duration_s == 30
    assert by_sid["sid-legacy"].input_tokens == 500        # usage 嵌套归一
    assert by_sid["sid-legacy"].cache_read_input_tokens == 900
    assert by_sid["sid-none"].num_turns is None  # 无统计如实 None，不编 0
    assert by_sid["sid-none"].input_tokens is None
    t = totals(stats)
    assert t["num_turns"] == 8 and t["duration_s"] == 91
    assert abs(t["cost_usd"] - 0.75) < 1e-9
    assert t["input_tokens"] == 1500 and t["output_tokens"] == 300
    assert t["cache_read_input_tokens"] == 3900


def test_collect_merged_session_turns_zip_in_order(tmp_path):
    """一个 sid 多条统计行（合并段逐 turn / 段链续步）：按台账行序逐个配对——
    旧版 sid 字典末行覆盖，合并段各步全挂末行统计（时间轴进度条/耗时缺失，
    web_ui_interaction u:2#2/#3 实爆）。"""
    meta = meta_root(tmp_path, "demo")
    meta.mkdir(parents=True)
    state = {
        "name": "demo",
        "segment_sessions": [
            {"ts": "t1", "session_id": "sid-m", "kind": "merged-step",
             "node": "understand:2", "sub_step": 2, "note": "gate=advanced"},
            {"ts": "t2", "session_id": "sid-m", "kind": "merged-step",
             "node": "understand:2", "sub_step": 3, "note": "gate=advanced"},
        ],
    }
    (meta / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (meta / "segment_stats.jsonl").write_text(
        json.dumps({"ts": "t1", "session_id": "sid-m", "num_turns": 5,
                    "duration_ms": 56000, "total_cost_usd": 0.3}) + "\n"
        + json.dumps({"ts": "t2", "session_id": "sid-m", "num_turns": 13,
                      "duration_ms": 99000, "total_cost_usd": 0.8}) + "\n",
        encoding="utf-8",
    )
    stats = collect_stats(tmp_path, "demo", tmp_path / "cache")
    assert [s.sub_step for s in stats] == [2, 3]
    assert [s.duration_s for s in stats] == [56, 99]  # 逐步归属，非全挂末行
    assert [s.num_turns for s in stats] == [5, 13]
    t = totals(stats)
    assert t["duration_s"] == 155 and t["num_turns"] == 18


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


def test_legacy_cache_non_dict_is_reset(tmp_path):
    """legacy 缓存 stats 字段非 dict（损坏）时重置，不抛异常。"""
    meta = _mk(tmp_path, "demo")
    stream = meta / "drive-stream.jsonl"
    stream.write_text(
        json.dumps({"type": "result", "session_id": "sid-legacy",
                    "num_turns": 3, "duration_ms": 30000, "total_cost_usd": 0.2}) + "\n",
        encoding="utf-8",
    )
    cache = tmp_path / "cache"
    cache.mkdir(parents=True)
    slug = f"{str(tmp_path).replace('/', '_')}--demo"
    (cache / f"{slug}.json").write_text(json.dumps({"offset": 0, "stats": "bad"}), encoding="utf-8")
    # 不应抛异常
    stats = collect_stats(tmp_path, "demo", cache)
    assert len(stats) == 3
    # 写回的文件应是合法 dict
    cached = json.loads((cache / f"{slug}.json").read_text(encoding="utf-8"))
    assert isinstance(cached["stats"], dict)
