"""跨项目扫描 .claude/workflows/*/state.json -> 节点状态模型（只读）。"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

DLWF = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DLWF))

from dl_flow_common import load_state  # noqa: E402
from dl_flow_nodes import _NODES, phase_index  # noqa: E402


@dataclass(frozen=True)
class NodeStatus:
    node_id: str
    label: str
    phase: str
    status: str  # "done" | "current" | "pending"
    entered_at: str | None
    exited_at: str | None
    sub_total: int  # 子步总数（时间轴枝叶渲染用；无编排节点=1）


@dataclass(frozen=True)
class WorkflowInfo:
    project: str
    name: str
    phase: str
    node: str
    gate: str
    held_for_gate: bool
    sub_step_index: int
    need_user: bool
    updated_at: str
    created_at: str
    problem_statement: str
    nodes: tuple[NodeStatus, ...]
    force_tacet: bool = False
    force_fermate: bool = False
    error: str | None = None


def meta_root(project: Path, name: str) -> Path:
    return project / ".claude" / "workflows" / name


def iter_workflow_names(project: Path) -> list[str]:
    root = project / ".claude" / "workflows"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "state.json").exists())


def node_statuses(state: dict) -> tuple[NodeStatus, ...]:
    hist = {(h["phase"], h["sub"]): h for h in state.get("history", [])}
    cur = (state.get("phase"), state.get("sub_index"))
    out: list[NodeStatus] = []
    ordered = sorted(_NODES.items(), key=lambda kv: (phase_index(kv[1].phase), kv[1].sub))
    for nid, node in ordered:
        h = hist.get((node.phase, node.sub))
        if (node.phase, node.sub) == cur:
            status = "current"
        elif h and h.get("exited_at"):
            status = "done"
        else:
            status = "pending"
        out.append(NodeStatus(
            node_id=nid, label=node.label, phase=node.phase, status=status,
            entered_at=h.get("entered_at") if h else None,
            exited_at=h.get("exited_at") if h else None,
            sub_total=len(node.sub_steps) if node.sub_steps else 1,
        ))
    return tuple(out)


def scan_workflow(project: Path, name: str) -> WorkflowInfo:
    state = load_state(project, name)
    if state is None:
        if (meta_root(project, name) / "state.json").exists():
            raise ValueError(f"工作流 {name} 的 state.json 损坏（JSON 解析失败）")
        raise FileNotFoundError(f"工作流 {name} 的 state.json 缺失")
    need_user = (meta_root(project, name) / "need_user.json").exists()
    return WorkflowInfo(
        project=str(project), name=name,
        phase=str(state.get("phase", "?")),
        node=str(state.get("node", "?")),
        gate=str(state.get("gate", "?")),
        held_for_gate=bool(state.get("held_for_gate")),
        sub_step_index=int(state.get("sub_step_index") or 1),
        need_user=need_user,
        updated_at=str(state.get("updated_at", "")),
        created_at=str(state.get("created_at", "")),
        problem_statement=str(state.get("problem_statement", "")),
        nodes=node_statuses(state),
        force_tacet=bool(state.get("force_tacet")),
        force_fermate=bool(state.get("force_fermate")),
    )


def scan_all(projects) -> list[WorkflowInfo]:
    """单工作流隔离 try/except：坏实例标 error 如实暴露（no silent fallback），不拖垮全局。"""
    out: list[WorkflowInfo] = []
    for project in projects:
        for name in iter_workflow_names(Path(project)):
            try:
                out.append(scan_workflow(Path(project), name))
            except Exception as exc:  # noqa: BLE001 - 隔离边界，error 字段即暴露面
                out.append(WorkflowInfo(
                    project=str(project), name=name, phase="?", node="?", gate="?",
                    held_for_gate=False, sub_step_index=0, need_user=False,
                    updated_at="", created_at="", problem_statement="", nodes=(),
                    error=str(exc),
                ))
    # 创建时间倒序（最晚创建的在前；无 created_at 回退 updated_at，空值沉底）
    out.sort(key=lambda i: i.created_at or i.updated_at, reverse=True)
    return out
