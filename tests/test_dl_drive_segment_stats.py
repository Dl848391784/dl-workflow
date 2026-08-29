"""dl_drive result 事件统计落盘 segment_stats.jsonl（dashboard 埋点）。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

DLWF_ROOT = Path(__file__).resolve().parents[1]
DRIVER = DLWF_ROOT / "scripts" / "workflow" / "dl_drive.py"


def _load_driver():
    spec = importlib.util.spec_from_file_location("dl_drive", DRIVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_append_segment_stat_writes_jsonl(tmp_path):
    drv = _load_driver()
    ev = {
        "type": "result",
        "subtype": "success",
        "session_id": "sid-123",
        "num_turns": 7,
        "duration_ms": 45200,
        "total_cost_usd": 0.1234,
        "usage": {
            "input_tokens": 13730,
            "output_tokens": 8665,
            "cache_read_input_tokens": 46976,
            "cache_creation_input_tokens": 0,
        },
    }
    drv._append_segment_stat(tmp_path, ev)
    lines = (tmp_path / "segment_stats.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["session_id"] == "sid-123"
    assert rec["num_turns"] == 7
    assert rec["duration_ms"] == 45200
    assert rec["total_cost_usd"] == 0.1234
    assert rec["input_tokens"] == 13730
    assert rec["output_tokens"] == 8665
    assert rec["cache_read_input_tokens"] == 46976
    assert rec["cache_creation_input_tokens"] == 0
    assert rec["ts"]  # 非空时间戳


def test_append_segment_stat_appends_and_tolerates_missing_fields(tmp_path):
    drv = _load_driver()
    drv._append_segment_stat(tmp_path, {"type": "result", "session_id": "a"})
    drv._append_segment_stat(tmp_path, {"type": "result", "session_id": "b", "num_turns": 1})
    lines = (tmp_path / "segment_stats.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    rec_a = json.loads(lines[0])
    assert rec_a["num_turns"] is None
    assert rec_a["duration_ms"] is None
    assert rec_a["total_cost_usd"] is None
