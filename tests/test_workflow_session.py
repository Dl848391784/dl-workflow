"""
hooks/workflow_session.py 的单元测试（v2.45，context-handoff-design §2）。

覆盖 build_injection 的触发面契约：
- source=clear/startup 且工作流有 trace -> 注入交接包
- source=resume/compact -> 不注入（重复税）
- 无 trace（首启）/ state 缺失 -> 不注入（静默）
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

DLWF_ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "workflow_session", DLWF_ROOT / "hooks" / "workflow_session.py"
)
ws = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["workflow_session"] = ws
_spec.loader.exec_module(ws)  # type: ignore[union-attr]


def _setup_wf(tmp_path: Path, with_trace: bool = True) -> None:
    wf_dir = tmp_path / ".claude" / "workflows" / "t"
    wf_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "name": "t",
        "phase": "understand",
        "index": 1,
        "sub_index": 1,
        "sub_total": 4,
        "sub_step_index": 2,
        "node": "understand:1",
        "gate": "pending",
        "history": [],
    }
    (wf_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    if with_trace:
        ev = tmp_path / ".claude" / "evidence"
        ev.mkdir(parents=True, exist_ok=True)
        rec = {
            "kind": "skill-trace",
            "major_stage": "Understand",
            "minor_stage": "ProblemContext",
            "sub_step": 1,
            "skill": "s",
            "purpose": "p",
            "q": ["问题定义"],
            "a": ["真实痛点 = X，用户原话「…」"],
        }
        (ev / "t.jsonl").write_text(
            json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8"
        )


class TestBuildInjection:
    def test_clear_injects_pack(self, tmp_path):
        _setup_wf(tmp_path)
        ctx = ws.build_injection(tmp_path, "t", "clear")
        assert ctx is not None
        assert "交接包" in ctx and "真实痛点 = X" in ctx

    def test_startup_with_traces_injects(self, tmp_path):
        # 重建/进程重启后再启动：有 trace -> 补交接包
        _setup_wf(tmp_path)
        assert ws.build_injection(tmp_path, "t", "startup") is not None

    def test_resume_skipped(self, tmp_path):
        _setup_wf(tmp_path)
        assert ws.build_injection(tmp_path, "t", "resume") is None

    def test_compact_skipped(self, tmp_path):
        _setup_wf(tmp_path)
        assert ws.build_injection(tmp_path, "t", "compact") is None

    def test_first_launch_silent(self, tmp_path):
        _setup_wf(tmp_path, with_trace=False)
        assert ws.build_injection(tmp_path, "t", "startup") is None
        assert ws.build_injection(tmp_path, "t", "clear") is None

    def test_missing_state_silent(self, tmp_path):
        assert ws.build_injection(tmp_path, "t", "clear") is None
