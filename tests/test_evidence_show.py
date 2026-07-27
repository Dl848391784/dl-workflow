"""evidence_show.py 的单元测试:英文标识 -> 中文展示渲染。"""

from __future__ import annotations

import sys
from pathlib import Path


DLWF_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DLWF_ROOT))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "evidence_show", DLWF_ROOT / "scripts" / "workflow" / "evidence_show.py"
)
es = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["evidence_show"] = es
_spec.loader.exec_module(es)  # type: ignore[union-attr]


def _write_ev(root: Path, name: str, lines: list[str]) -> None:
    """写 evidence/<name>.jsonl(每行一条 JSON)。"""
    p = root / ".claude" / "evidence" / f"{name}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestRenderSkillTrace:
    def test_english_to_chinese(self, tmp_path):
        # major Understand -> 理解和求证问题;minor ProblemContext -> 理解问题和背景
        _write_ev(
            tmp_path,
            "t",
            [
                '{"kind":"skill-trace","major_stage":"Understand","minor_stage":"ProblemContext","sub_step":1,"skill":"define-problem","purpose":"逼问问题定义","q":["who/pain？","why-now？"],"a":["单纯确认","demo 演练"]}',
            ],
        )
        out = es.render(tmp_path, "t")
        assert "[Understand] 理解和求证问题" in out
        assert "ProblemContext (理解问题和背景)" in out
        assert "sub_step 1: 逼问问题定义" in out
        assert "skill: define-problem" in out
        assert "Q: who/pain？" in out
        assert "A: 单纯确认" in out
        assert "A: demo 演练" in out

    def test_q_a_aligned(self, tmp_path):
        # q/a 数组按序对齐;minor GoalsAndValue -> 明确目标和价值(验 minor_key_map 多值)
        _write_ev(
            tmp_path,
            "t",
            [
                '{"kind":"skill-trace","major_stage":"Understand","minor_stage":"GoalsAndValue","sub_step":2,"skill":"define-problem","purpose":"p","q":["q1","q2"],"a":["a1","a2"]}',
            ],
        )
        out = es.render(tmp_path, "t")
        assert "GoalsAndValue (明确目标和价值)" in out
        assert "Q: q1" in out and "A: a1" in out
        assert "Q: q2" in out and "A: a2" in out

    def test_skill_missing_legacy_record(self, tmp_path):
        # 旧记录无 skill 字段 -> 不崩,不显示 skill 部分(向后兼容)
        _write_ev(
            tmp_path,
            "t",
            [
                '{"kind":"skill-trace","major_stage":"Understand","minor_stage":"ProblemContext","sub_step":1,"purpose":"p","q":["q"],"a":["a"]}',
            ],
        )
        out = es.render(tmp_path, "t")
        assert "sub_step 1: p" in out
        assert "skill:" not in out


class TestRenderGate:
    def test_gate_record(self, tmp_path):
        _write_ev(
            tmp_path,
            "t",
            [
                '{"kind":"gate","node":"understand:1","phase":"understand","sub":1,"label":"理解问题和背景","gate":"passed","gate_mech":"NONE","rubric":null,"attempts":1,"skill":"define-problem","via":"auto-stop","ts":"2026-07-24","commit_sha":"abc"}',
            ],
        )
        out = es.render(tmp_path, "t")
        assert "[gate:understand:1]" in out
        assert "理解问题和背景" in out
        assert "gate=passed" in out
        assert "attempts=1" in out

    def test_gate_record_with_stage_fields(self, tmp_path):
        # 2026-07-26 起的 gate 记录带 major_stage/minor_stage（与 skill-trace 对齐）
        # -> minor_stage 经 minor_key_map 转中文展示
        _write_ev(
            tmp_path,
            "t",
            [
                '{"kind":"gate","node":"understand:2","phase":"understand","sub":2,"label":"明确目标和价值",'
                '"major_stage":"Understand","minor_stage":"GoalsAndValue","gate":"passed",'
                '"gate_mech":"NONE","rubric":null,"attempts":0,"via":"auto-stop","ts":"2026-07-26"}',
            ],
        )
        out = es.render(tmp_path, "t")
        assert "[gate:understand:2]" in out
        assert "GoalsAndValue（明确目标和价值）" in out

    def test_gate_record_legacy_without_stage_fields(self, tmp_path):
        # 旧记录无 major/minor_stage -> 回退 node/label 展示（不猜不崩）
        _write_ev(
            tmp_path,
            "t",
            [
                '{"kind":"gate","node":"plan:0","phase":"plan","sub":0,"label":"生成执行计划","gate":"passed","rubric":null,"attempts":0}',
            ],
        )
        out = es.render(tmp_path, "t")
        assert "[gate:plan:0]" in out
        assert "生成执行计划" in out
        assert "None" not in out  # 缺失字段不得渲染成字面 None


class TestEdgeCases:
    def test_missing_file(self, tmp_path):
        out = es.render(tmp_path, "nope")
        assert "无 evidence 记录" in out

    def test_unparseable_line(self, tmp_path):
        _write_ev(tmp_path, "t", ["这不是 JSON"])
        out = es.render(tmp_path, "t")
        assert "无法解析" in out

    def test_mixed_records(self, tmp_path):
        _write_ev(
            tmp_path,
            "t",
            [
                '{"kind":"skill-trace","major_stage":"Understand","minor_stage":"ProblemContext","sub_step":1,"purpose":"p","q":["q"],"a":["a"]}',
                '{"kind":"gate","node":"understand:1","phase":"understand","sub":1,"label":"理解问题和背景","gate":"passed","rubric":null,"attempts":1}',
            ],
        )
        out = es.render(tmp_path, "t")
        assert "[Understand] 理解和求证问题" in out
        assert "[gate:understand:1]" in out
