"""产物与证据链：evidence.jsonl 证据链 + plan.md change_point 改动面 + understands/plans 文档。

数据源（dl-workflow 产物契约）：
- 证据链：<project>/.claude/evidence/<name>.jsonl（skill-trace 带 q/a/结论 + gate 裁决记录）
- 改动面：<project>/.claude/plans/<name>.md 的 change_point= 字段，
  锚点形态 `文件:方法:L行（改|增|删）：改前=X → 改后=Y`（render-artifact 机械装配，格式稳定可机读）；
  现状代码上下文按 state.json 的 worktree_path 实读锚点文件 ±4 行
- 产物文档：<project>/.claude/understands|plans/<name>.md
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from dl_flow_common import parse_change_points  # noqa: E402
from dl_flow_engine import PHASES  # noqa: E402

log = logging.getLogger("dl_dashboard.outputs")

# change_point 锚点解析单源 = dl_flow_common（v0.6.0 迁入；dashboard 与渲染器共用）（跨行，止于 ；interface= / ；Produces= / 空行 / 串尾）


def load_evidence(project: Path, name: str) -> list[dict]:
    """证据链条目（q/a/结论 全量保留——用户要看的就是链本身）。

    kind=tacet 机械落库记录过滤（2026-09-18 用户裁决）：强制静默步无模型
    会话、无实质内容，展示即噪音（「TACET 强制档」满屏）。按 kind 标记
    过滤（写侧单源，engine 落库即钉死），不猜步号——judge 输入面
    （_iter_trace_segments 等）本就只认 kind=skill-trace，同口径。
    """
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
        if d.get("kind") == "tacet":
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
    """plan.md 的 change_point 锚点：文件/方法/行/动作 + 改前/改后 + 现状代码上下文。"""
    p = project / ".claude" / "plans" / f"{name}.md"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    worktree: Path | None = None
    state_p = project / ".claude" / "workflows" / name / "state.json"
    if state_p.exists():
        try:
            wt = json.loads(state_p.read_text(encoding="utf-8")).get("worktree_path")
            if wt:
                worktree = Path(wt)
        except json.JSONDecodeError:
            log.warning("state.json 解析失败，改动面无现状上下文: %s", state_p)
    return parse_change_points(text, worktree)


def _proposal_visible(st: "dict | None") -> bool:
    """技术方案可见性（2026-09-18 用户裁决：plan 执行完才展示——否则展示的
    都是不全的）。可见 = 阶段序过 plan / gate=done（fermate 完结）/ plan
    门栏扣留（内容已定稿待放行）；无 state（老/归档实例）宁纵显示。"""
    if not st:
        return True
    phase = st.get("phase", "")
    try:
        past = PHASES.index(phase) > PHASES.index("plan")
    except ValueError:
        past = False
    return bool(
        past or st.get("gate") == "done"
        or (phase == "plan" and st.get("held_for_gate"))
    )


def artifact_status(project: Path, name: str) -> dict:
    st: dict | None = None
    state_p = project / ".claude" / "workflows" / name / "state.json"
    try:
        st = json.loads(state_p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = None
    out: dict[str, dict] = {}
    for kind in ("understands", "plans", "proposals"):
        p = project / ".claude" / kind / f"{name}.md"
        h = p.with_suffix(".html")
        out[kind] = {
            "exists": p.exists(),
            "size": p.stat().st_size if p.exists() else 0,
            "html_exists": h.exists(),
            "html_size": h.stat().st_size if h.exists() else 0,
            "visible": _proposal_visible(st) if kind == "proposals" else True,
        }
    return out


def load_artifact(project: Path, name: str, kind: str) -> str | None:
    """产物文档全文。kind 白名单防路径穿越（文件名由 kind 决定，不受 name 影响路径深度）。"""
    if kind not in ("understands", "plans", "proposals"):
        raise ValueError(f"未知产物类型: {kind}")
    p = project / ".claude" / kind / f"{name}.md"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")
