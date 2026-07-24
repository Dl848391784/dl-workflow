#!/usr/bin/env python3
"""dl evidence show <name> 的后端:读 evidence.jsonl,英文标识转中文展示。

映射 single source 在 engine(PHASE_LABELS + minor_key_map),本脚本只消费,
不另存映射副本(改 engine 即生效)。

记录类型:
- skill-trace(模型写): major_stage(首字母大写英文).lower() -> PHASE_LABELS -> 中文;
  minor_stage(英文标识,如 ProblemContext) -> minor_key_map -> 中文;sub_step 数字;
  purpose/q/a 字符串数组按序对齐。
- gate(engine 写,write_gate_verdict): node(phase:sub) -> label;gate/rubric/attempts。

用法:
  python3 evidence_show.py <name> [project_root]   # project_root 缺省取 cwd 的 git 根
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

# ---------- 加载 engine(同 workflow_phase.py 范式) ----------
_DLWF_ROOT = Path(__file__).resolve().parents[2]  # ~/.dl-workflow/
_ENGINE_PATH = _DLWF_ROOT / "dl-flow-engine.py"
_spec = importlib.util.spec_from_file_location("dl_flow_engine", _ENGINE_PATH)
engine = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["dl_flow_engine"] = engine  # dataclass 探测类型注解要查此表
_spec.loader.exec_module(engine)  # type: ignore[union-attr]


def render(project_root: Path, name: str) -> str:
    """读 evidence/<name>.jsonl,渲染中文展示树。文件缺失/空返回提示。"""
    text = engine.read_evidence(project_root, name)
    if not text:
        return (
            "（无 evidence 记录：%s/.claude/evidence/%s.jsonl 不存在或为空）"
            % (project_root, name)
        )

    phase_labels = engine.PHASE_LABELS
    minor_map = engine.minor_key_map()
    out = ["## evidence: %s\n" % name]
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            out.append("  ⚠ 无法解析的行: %s..." % raw[:60])
            continue
        if not isinstance(rec, dict):
            continue
        kind = rec.get("kind")
        if kind == "skill-trace":
            out.append(_render_skill_trace(rec, phase_labels, minor_map))
        elif kind == "gate":
            out.append(_render_gate(rec, phase_labels))
        else:
            out.append(
                "  [未知 kind=%s] %s" % (kind, json.dumps(rec, ensure_ascii=False)[:80])
            )
    return "\n".join(out)


def _render_skill_trace(rec: dict, phase_labels: dict, minor_map: dict) -> str:
    """skill-trace -> 中文树([Major] 中文 / MinorKey (中文) / sub_step / Q·A)。"""
    major = rec.get("major_stage", "?")  # 首字母大写英文,如 Understand
    phase_cn = phase_labels.get(str(major).lower(), str(major))
    minor = rec.get("minor_stage", "?")  # 英文标识,如 ProblemContext
    minor_cn = minor_map.get(minor, str(minor))
    sub_step = rec.get("sub_step", "?")
    skill = rec.get("skill")  # Step.ref(skill 名或工具描述);旧记录无此字段->None
    purpose = rec.get("purpose", "")
    qs = rec.get("q") or []
    As = rec.get("a") or []

    lines = ["[%s] %s" % (major, phase_cn)]
    lines.append("  └ %s (%s)" % (minor, minor_cn))
    skill_part = "  skill: %s  ｜  " % skill if skill else ""
    lines.append("      %ssub_step %s: %s" % (skill_part, sub_step, purpose))
    for i, q in enumerate(qs):
        a = As[i] if i < len(As) else ""
        lines.append("        Q: %s" % q)
        lines.append("        A: %s" % a)
    return "\n".join(lines)


def _render_gate(rec: dict, phase_labels: dict) -> str:
    """gate 裁决记录 -> 中文一行 + rubric 摘要。"""
    node_id = rec.get("node", "?")  # "understand:1"
    label = rec.get("label", "")
    gate = rec.get("gate", "?")
    attempts = rec.get("attempts", "?")
    phase = rec.get("phase", "")
    phase_cn = phase_labels.get(phase, phase)
    rubric = rec.get("rubric") or ""
    lines = [
        "[gate:%s] %s（%s） gate=%s attempts=%s"
        % (node_id, label, phase_cn, gate, attempts)
    ]
    if rubric:
        lines.append("      rubric: %s" % rubric[:80])
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("用法: dl evidence show <name>", file=sys.stderr)
        return 1
    name = argv[1]
    if len(argv) >= 3:
        root = argv[2]
    else:
        try:
            root = subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"], text=True
            ).strip()
        except subprocess.CalledProcessError:
            root = str(Path.cwd())
    print(render(Path(root), name))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
