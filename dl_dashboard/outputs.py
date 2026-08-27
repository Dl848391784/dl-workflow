"""产物与证据链：evidence.jsonl 证据链 + plan.md change_point 改动面 + understands/plans 文档。

数据源（dl-workflow 产物契约）：
- 证据链：<project>/.claude/evidence/<name>.jsonl（skill-trace 带 q/a/结论 + gate 裁决记录）
- 改动面：<project>/.claude/plans/<name>.md 的 change_point= 字段，
  锚点形态 `文件:方法:L行（改|增|删）`（render-artifact 机械装配，格式稳定可机读）
- 产物文档：<project>/.claude/understands|plans/<name>.md
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger("dl_dashboard.outputs")

# change_point= 块（跨行，止于 ；interface= / ；Produces= / 空行 / 串尾）
_CP_RE = re.compile(r"change_point=(.+?)(?:；interface=|；Produces=|\n\n|$)", re.S)
# 锚点：web_ui/app.py:_render_report:L267（改）/ test_x.py:-（增@文件尾）/ _macros.html:-:L57（改）
_ANCHOR_RE = re.compile(r"([\w./-]+\.\w+):([\w.-]*):?L?(\d+|-)?（(改|增|删)")


def load_evidence(project: Path, name: str) -> list[dict]:
    """证据链条目（q/a/结论 全量保留——用户要看的就是链本身）。"""
    p = project / ".claude" / "evidence" / f"{name}.jsonl"
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            log.warning("evidence 损坏行跳过: %s", p, exc_info=True)
            continue
        out.append({
            "kind": d.get("kind", "?"),
            "major_stage": d.get("major_stage", ""),
            "minor_stage": d.get("minor_stage", ""),
            "sub_step": d.get("sub_step"),
            "skill": d.get("skill"),
            "purpose": d.get("purpose", ""),
            "conclusion": d.get("结论", ""),
            "q": d.get("q") or [],
            "a": d.get("a") or [],
        })
    return out


def load_change_points(project: Path, name: str) -> list[dict]:
    """plan.md 的 change_point 锚点：代码需要改动的 文件/方法/行/动作。"""
    p = project / ".claude" / "plans" / f"{name}.md"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    out: list[dict] = []
    for m in _CP_RE.finditer(text):
        for a in _ANCHOR_RE.finditer(m.group(1)):
            out.append({
                "file": a.group(1),
                "method": a.group(2) or "-",
                "line": a.group(3) or "-",
                "action": a.group(4),
            })
    return out


def artifact_status(project: Path, name: str) -> dict:
    out: dict[str, dict] = {}
    for kind in ("understands", "plans"):
        p = project / ".claude" / kind / f"{name}.md"
        out[kind] = {"exists": p.exists(), "size": p.stat().st_size if p.exists() else 0}
    return out


def load_artifact(project: Path, name: str, kind: str) -> str | None:
    """产物文档全文。kind 白名单防路径穿越（文件名由 kind 决定，不受 name 影响路径深度）。"""
    if kind not in ("understands", "plans"):
        raise ValueError(f"未知产物类型: {kind}")
    p = project / ".claude" / kind / f"{name}.md"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")
