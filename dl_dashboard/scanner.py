"""跨项目扫描 .claude/workflows/*/state.json -> 节点状态模型（只读）。"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

DLWF = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DLWF))

from dl_flow_common import load_state  # noqa: E402
from dl_flow_nodes import (  # noqa: E402
    FERMATE_SILENT_STEPS,
    GATED_AFTER,
    _NODES,
    fermate_cut_node,
    fermate_phase_reachable,
    phase_index,
    tacet_silent_steps,
)


@dataclass(frozen=True)
class NodeStatus:
    node_id: str
    label: str
    phase: str
    status: str  # "done" | "current" | "pending"
    entered_at: str | None
    exited_at: str | None
    sub_total: int  # 子步总数（时间轴枝叶渲染用；无编排节点=1）
    steps: tuple[int, ...]  # 可见子步号（tacet 静默/fermate 裁剪步剔除后）
    step_labels: dict[str, str]  # 可见子步号(字符串键) -> 中文短名（Step.short）


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
    gate_actionable: bool = False  # gate 按钮可作用（门栏扣留 / 闸门后置阶段 pending）
    force_tacet: bool = False
    force_fermate: bool = False
    tacet_upgraded: tuple[str, ...] = ()  # 中途升级步清单（evolution-up P3）
    error: str | None = None
    # 在飞段（driver 起跑落盘、收工清除）：总执行时间 = Σ 完成段 + 本段实跑
    current_segment: dict | None = None


def meta_root(project: Path, name: str) -> Path:
    return project / ".claude" / "workflows" / name


def need_user_stale(data: dict, state: dict) -> bool:
    """need_user 载荷是否陈旧（dashboard-answered-marker-design §2.3：
    绑定 ≠ state 当前位置 = 已推进的步的问题 / NEXT_PREP 预备的未来步）。
    无绑定字段 = legacy 旧格式 → False（现状放行）。
    单源：scan_workflow 的 bool 与 detail 的渲染过滤共用，防列表/详情口径分裂。"""
    return data.get("node") is not None and (
        data.get("node") != state.get("node")
        or data.get("sub_step") != state.get("sub_step_index", 1)
    )


def gate_actionable_of(state: dict) -> bool:
    """gate 放行是否可作用（与 /dl gate 路由域逐义对齐，前端按钮可见性单源）：
    门栏扣留 held_for_gate / 闸门后置阶段（GATED_AFTER）且 gate=pending。
    gate=passed/done 或非闸门后置阶段（如 understand 全程）= 点了也没用，不显示。"""
    return bool(state.get("held_for_gate")) or (
        str(state.get("gate")) == "pending"
        and str(state.get("phase")) in GATED_AFTER
    )


def iter_workflow_names(project: Path) -> list[str]:
    root = project / ".claude" / "workflows"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "state.json").exists())


def _silent_steps(state: dict) -> set:
    """该工作流的整步静默集：fermate 裁剪（深度）+ tacet 静默（密度），正交叠加。
    tacet 侧与 engine.tacet_silent_for 同口径——已升级步（tacet_upgraded，
    evolution-up P3）移出静默集，时间轴渲为可见。"""
    silent: set = set()
    if state.get("force_fermate"):
        silent |= FERMATE_SILENT_STEPS
    if state.get("force_tacet"):
        silent |= tacet_silent_steps(fermate=bool(state.get("force_fermate")))
        silent -= set(state.get("tacet_upgraded") or [])
    return silent


def _step_labels(node, nid: str, sub_total: int, silent: set) -> dict[str, str]:
    """可见子步号 -> 中文短名（Step.short 单源，如 逼问定义）——时间轴叶
    节点按名展示（替代 #1/#2 裸序号）；无编排节点/缺定义回退 #n。"""
    steps = node.sub_steps or ()
    labels: dict[str, str] = {}
    for i in range(1, sub_total + 1):
        if f"{nid}#{i}" in silent:
            continue
        step = steps[i - 1] if i - 1 < len(steps) else None
        labels[str(i)] = (getattr(step, "short", None) or f"#{i}")
    return labels


def node_statuses(state: dict) -> tuple[NodeStatus, ...]:
    hist = {(h["phase"], h["sub"]): h for h in state.get("history", [])}
    cur = (state.get("phase"), state.get("sub_index"))
    silent = _silent_steps(state)
    fermate = bool(state.get("force_fermate"))
    out: list[NodeStatus] = []
    ordered = sorted(_NODES.items(), key=lambda kv: (phase_index(kv[1].phase), kv[1].sub))
    for nid, node in ordered:
        # fermate 轨道可见集单源（dl_flow_nodes）：可达阶段 ∧ 非裁剪节点。
        # 前端不再手写过滤——展示层过滤掉队 = 幽灵 pending 节点 + 进度分母
        # 虚高（web_ui_interaction 32/43=74% 永到不了 100% 事故）。
        if fermate and (
            fermate_cut_node(node.phase, node.sub)
            or not fermate_phase_reachable(node.phase)
        ):
            continue
        h = hist.get((node.phase, node.sub))
        if (node.phase, node.sub) == cur:
            status = "current"
        elif h and h.get("exited_at"):
            status = "done"
        else:
            status = "pending"
        sub_total = len(node.sub_steps) if node.sub_steps else 1
        out.append(NodeStatus(
            node_id=nid, label=node.label, phase=node.phase, status=status,
            entered_at=h.get("entered_at") if h else None,
            exited_at=h.get("exited_at") if h else None,
            sub_total=sub_total,
            steps=tuple(i for i in range(1, sub_total + 1)
                        if f"{nid}#{i}" not in silent),
            step_labels=_step_labels(node, nid, sub_total, silent),
        ))
    return tuple(out)


def scan_workflow(project: Path, name: str) -> WorkflowInfo:
    state = load_state(project, name)
    if state is None:
        if (meta_root(project, name) / "state.json").exists():
            raise ValueError(f"工作流 {name} 的 state.json 损坏（JSON 解析失败）")
        raise FileNotFoundError(f"工作流 {name} 的 state.json 缺失")
    need_user = False
    nu_p = meta_root(project, name) / "need_user.json"
    try:
        nu = json.loads(nu_p.read_text(encoding="utf-8"))
        # 陈旧卡过滤单源（need_user_stale）：侧栏等待态与 detail 同口径
        need_user = isinstance(nu, dict) and not need_user_stale(nu, state)
    except (OSError, json.JSONDecodeError):
        need_user = nu_p.exists()  # 解析失败按有卡处理（detail 出错误卡）
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
        gate_actionable=gate_actionable_of(state),
        force_tacet=bool(state.get("force_tacet")),
        force_fermate=bool(state.get("force_fermate")),
        tacet_upgraded=tuple(state.get("tacet_upgraded") or []),
        current_segment=state.get("current_segment"),
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
