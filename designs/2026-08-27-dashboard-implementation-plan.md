# dl-workflow 管理后台（dl_dashboard）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 dl-workflow 仓库内新增 `dl_dashboard/` 模块：FastAPI + SSE 的 Web 管理后台，跨项目启动/全驱动 dl 工作流，节点状态 + 每 step 耗时/token/轮数可视化，driver 服务端托管不断连。

**Architecture:** 后端纯 Python 单包，直接 import `dl_flow_engine`/`dl_flow_common`/`dl_flow_nodes` 复用状态读取；driver 为后端 setsid 子进程（PID/日志落盘，重启认领）；前端单页原生 JS 无构建。设计真源：`designs/2026-08-27-dashboard-design.md`。

**Tech Stack:** Python 3.11.13 系统解释器、FastAPI 0.133.1、uvicorn 0.41.0（已装，零新依赖）、stdlib tomllib、原生 JS EventSource。

## Global Constraints

- 仓库：`~/.dl-workflow`（独立 git repo）。**按 worktree-per-session 协议开发**（见 Task 0），收口 merge 回 main 由用户裁决，不在本计划内。
- 运行命令一律 `cd ~/.dl-workflow && python3 -m pytest tests/ -x -q`（测试）与 `python3 -m dl_dashboard.app`（起服务）。
- 日志用 `logging` + `%` 惰性格式化，禁 f-string 日志。
- no silent fallback：解析失败必须暴露（error 字段 / log），禁静默吞异常。
- 每个 Task 末尾按给出的命令 commit（在 worktree 内）。
- 节点/状态真源一律来自 `dl_flow_nodes._NODES` + state.json，禁在 dashboard 里复制节点表。
- 写操作对 workflow 目录只涉及既有约定文件（state.json 经 engine、need_user.json 只读、segment_stats.jsonl 只追加）；其余只读。

## 关键接口真源（已核实，执行时以代码为准）

| 依赖 | 位置 | 签名/格式 |
|---|---|---|
| 节点全表 | `dl_flow_nodes.py` | `_NODES: dict[str, Node]`，`Node(label, phase, sub, advance, ...)`；`phase_index(phase)`；`PHASES=("understand","plan","execute","review","evolution")` |
| state 读取 | `dl_flow_common.py:24` | `state_path(project_root, name)` / `load_state(project_root, name) -> dict|None`；meta 根 = `<project>/.claude/workflows/<name>/` |
| engine 函数 | `dl_flow_engine.py` | `get_node(phase,sub)`、`node_id(phase,sub)`、`sub_step_at(node,n)`、`segment_spawn_overrides(node,step)`、`NO_MCP_ARGS`、`set_problem_statement(project_root,name,text)`、`save_state` |
| engine CLI | `dl_flow_engine.py main` | `python3 dl_flow_engine.py <advance|step-pass|subgate-pass|dispute|state-reset> <name> [value]`，cwd=worktree（内部 `git rev-parse` 反查项目根） |
| 驱动 | `scripts/workflow/dl_drive.py` | `python3 dl_drive.py <name>`，cwd=worktree，stdin=DEVNULL；断点退出 |
| 建实例 | `scripts/workflow/dl-launch.sh` | `bash dl-launch.sh --workflow <name> --headless`，cwd=项目根，stdin=DEVNULL；判定=实例落盘 |
| need_user | `<meta>/need_user.json` | `{"questions":[{"question","header","multiSelect","options":[{"label","description"}]}]}` |
| 段台账 | state.json `segment_sessions` | `[{"ts","session_id","kind","node","sub_step","note"}]`，**无耗时/token 字段**（Task 1 补埋点） |
| 段统计 | `<meta>/drive-stream.jsonl` | 原始流，其中 `"type":"result"` 事件含 `session_id/num_turns/duration_ms/total_cost_usd` |
| 注入目标段 | state.json | `kind=="tui-step-needuser"` 且 `node==nid` 且 `sub_step==cur` 的末条（wf_ctl.py `_find_tui_sid` 语义，禁回落最新段） |

---

### Task 0: 建开发 worktree（dl-workflow 并发协议）

**Files:** 无（环境准备）

- [ ] **Step 1: 建 worktree + 分支**

```bash
cd ~/.dl-workflow
git worktree add ~/.dl-workflow-worktrees/dashboard -b feat/dashboard
cd ~/.dl-workflow-worktrees/dashboard && git status --short
```

Expected: 干净工作区，分支 `feat/dashboard`。后续所有 Task 的相对路径与命令均在 `~/.dl-workflow-worktrees/dashboard` 下执行（文中 `~/.dl-workflow` 指仓库内容，执行时替换为 worktree 路径；但 **运行态依赖**（被 dashboard import 的 engine、被 spawn 的 dl_drive）也以 worktree 内副本为准，避免主仓被其他会话改动影响测试）。

- [ ] **Step 2: 验证测试基线绿**

Run: `cd ~/.dl-workflow-worktrees/dashboard && python3 -m pytest tests/ -x -q`
Expected: 全 PASS（若有基线红，先报告用户，不在本计划修）。

---

### Task 1: dl_drive 段统计落盘 segment_stats.jsonl

**Files:**
- Modify: `scripts/workflow/dl_drive.py`（两处 `elif etype == "result":` 处理点，当前约 :724 与 :890，以 `ev.get("total_cost_usd")` 出现处为准）
- Test: `tests/test_dl_drive_segment_stats.py`

**Interfaces:**
- Produces: `<meta>/segment_stats.jsonl`，每行 `{"ts","session_id","num_turns","duration_ms","total_cost_usd"}`。Task 4 metrics.py 按 `session_id` join 段台账。

- [ ] **Step 1: 写失败测试**

```python
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
    }
    drv._append_segment_stat(tmp_path, ev)
    lines = (tmp_path / "segment_stats.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["session_id"] == "sid-123"
    assert rec["num_turns"] == 7
    assert rec["duration_ms"] == 45200
    assert rec["total_cost_usd"] == 0.1234
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/.dl-workflow-worktrees/dashboard && python3 -m pytest tests/test_dl_drive_segment_stats.py -x -q`
Expected: FAIL `AttributeError: module 'dl_drive' has no attribute '_append_segment_stat'`

- [ ] **Step 3: 实现 `_append_segment_stat` + 两处调用**

在 `scripts/workflow/dl_drive.py` 的 `_record_segment` 函数后新增：

```python
def _append_segment_stat(meta: Path, ev: dict) -> None:
    """result 事件统计落盘（dashboard 观测埋点，2026-08-27 dashboard-design §3）。

    段台账 segment_sessions 只记 ts/kind/node/note（留痕语义）；耗时/轮数/成本
    属统计语义，单列 JSONL 按 session_id join——不侵入 _record_segment 调用链。
    只追加不修改；写失败不阻断主流（统计通道降级≠段失败），但必须 log。
    """
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "session_id": ev.get("session_id"),
        "num_turns": ev.get("num_turns"),
        "duration_ms": ev.get("duration_ms"),
        "total_cost_usd": ev.get("total_cost_usd"),
    }
    try:
        with open(meta / "segment_stats.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        log.warning("segment_stats.jsonl 写失败 meta=%s", meta, exc_info=True)
```

（若 dl_drive 无 `log` 对象，模块顶部加 `log = logging.getLogger("dl_drive")` 并 `import logging`。）

两处 `elif etype == "result":` 分支内、现有 `dur = ...` 打印逻辑之后各加一行（`meta` 两站点均在作用域内，若某站点变量名不同以实际为准）：

```python
                    _append_segment_stat(meta, ev)
```

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `python3 -m pytest tests/test_dl_drive_segment_stats.py tests/test_dl_drive.py -x -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/workflow/dl_drive.py tests/test_dl_drive_segment_stats.py
git commit -m "feat(drive): result 事件统计落盘 segment_stats.jsonl（dashboard 观测埋点）"
```

---

### Task 2: dl_dashboard 包骨架 + config.py

**Files:**
- Create: `dl_dashboard/__init__.py`
- Create: `dl_dashboard/config.py`
- Test: `tests/test_dl_dashboard_config.py`

**Interfaces:**
- Produces: `DashboardConfig(projects: tuple[Path, ...], host: str, port: int)`；`load_config(path: Path | None = None) -> DashboardConfig`（默认 `~/.dl-workflow/dashboard.toml`，缺文件返回 `projects=()`）。Task 7 app.py 消费。

- [ ] **Step 1: 写失败测试**

```python
"""dl_dashboard.config：dashboard.toml 读取。"""
from __future__ import annotations

from dl_dashboard.config import load_config


def test_missing_file_returns_empty_projects(tmp_path):
    cfg = load_config(tmp_path / "nonexistent.toml")
    assert cfg.projects == ()
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9000


def test_parse_projects_host_port(tmp_path):
    p = tmp_path / "dashboard.toml"
    p.write_text(
        'host = "127.0.0.1"\n'
        "port = 19000\n"
        'projects = ["/home/admin/projects/factor_ic_analyzer", "~/projects/other"]\n',
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 19000
    assert str(cfg.projects[0]) == "/home/admin/projects/factor_ic_analyzer"
    assert cfg.projects[1].is_absolute()  # ~ 已展开
    assert "~" not in str(cfg.projects[1])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_dl_dashboard_config.py -x -q`
Expected: FAIL `ModuleNotFoundError: No module named 'dl_dashboard'`

- [ ] **Step 3: 实现**

`dl_dashboard/__init__.py`：

```python
"""dl-workflow 管理后台（designs/2026-08-27-dashboard-design.md）。"""
```

`dl_dashboard/config.py`：

```python
"""dashboard 配置：~/.dl-workflow/dashboard.toml（项目根清单 + 监听地址）。"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG = Path.home() / ".dl-workflow" / "dashboard.toml"


@dataclass(frozen=True)
class DashboardConfig:
    projects: tuple[Path, ...]
    host: str = "0.0.0.0"
    port: int = 9000


def load_config(path: Path | None = None) -> DashboardConfig:
    p = path or DEFAULT_CONFIG
    if not p.exists():
        return DashboardConfig(projects=())
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    projects = tuple(Path(x).expanduser() for x in data.get("projects", []))
    return DashboardConfig(
        projects=projects,
        host=str(data.get("host", "0.0.0.0")),
        port=int(data.get("port", 9000)),
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_dl_dashboard_config.py -x -q`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add dl_dashboard/__init__.py dl_dashboard/config.py tests/test_dl_dashboard_config.py
git commit -m "feat(dashboard): 包骨架 + dashboard.toml 配置读取"
```

---

### Task 3: scanner.py — 跨项目工作流扫描 + 节点状态模型

**Files:**
- Create: `dl_dashboard/scanner.py`
- Test: `tests/test_dl_dashboard_scanner.py`

**Interfaces:**
- Consumes: `dl_flow_common.load_state`、`dl_flow_nodes._NODES/phase_index`
- Produces: `meta_root(project, name) -> Path`（Task 4/6 复用）；`NodeStatus`、`WorkflowInfo` dataclass；`iter_workflow_names(project)`、`scan_workflow(project, name)`、`scan_all(projects)`。状态值仅 `"done"|"current"|"pending"`；`scan_all` 坏实例不抛，返回 `error` 字段非空的占位 `WorkflowInfo`。

- [ ] **Step 1: 写失败测试**

```python
"""dl_dashboard.scanner：state.json -> 节点状态模型。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dl_dashboard.scanner import (
    iter_workflow_names,
    meta_root,
    scan_all,
    scan_workflow,
)


def _mk_workflow(project: Path, name: str, state: dict) -> Path:
    meta = meta_root(project, name)
    meta.mkdir(parents=True)
    (meta / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return meta


BASE_STATE = {
    "name": "demo",
    "phase": "plan",
    "sub_index": 2,
    "sub_step_index": 1,
    "node": "plan:2",
    "gate": "pending",
    "held_for_gate": False,
    "updated_at": "2026-08-27T10:00:00",
    "problem_statement": "测试问题",
    "history": [
        {"phase": "understand", "sub": 1,
         "entered_at": "2026-08-27T08:00:00", "exited_at": "2026-08-27T08:30:00",
         "via": "step-stop"},
    ],
}


def test_meta_root(tmp_path):
    assert meta_root(tmp_path, "demo") == tmp_path / ".claude" / "workflows" / "demo"


def test_iter_workflow_names_skips_incomplete(tmp_path):
    _mk_workflow(tmp_path, "ok", BASE_STATE)
    (meta_root(tmp_path, "broken")).mkdir(parents=True)  # 无 state.json
    assert iter_workflow_names(tmp_path) == ["ok"]
    assert iter_workflow_names(tmp_path / "nonexistent") == []


def test_scan_workflow_node_statuses(tmp_path):
    _mk_workflow(tmp_path, "demo", BASE_STATE)
    info = scan_workflow(tmp_path, "demo")
    assert info.node == "plan:2" and info.gate == "pending"
    assert info.problem_statement == "测试问题"
    by_id = {n.node_id: n for n in info.nodes}
    assert by_id["understand:1"].status == "done"
    assert by_id["understand:1"].exited_at == "2026-08-27T08:30:00"
    assert by_id["plan:2"].status == "current"
    assert by_id["plan:3"].status == "pending"
    assert by_id["execute:0"].status == "pending"
    # 全节点覆盖 5 阶段
    assert {n.phase for n in info.nodes} == {
        "understand", "plan", "execute", "review", "evolution"}


def test_scan_workflow_need_user_flag(tmp_path):
    meta = _mk_workflow(tmp_path, "demo", BASE_STATE)
    assert scan_workflow(tmp_path, "demo").need_user is False
    (meta / "need_user.json").write_text('{"questions": []}', encoding="utf-8")
    assert scan_workflow(tmp_path, "demo").need_user is True


def test_scan_all_isolates_broken_workflow(tmp_path):
    _mk_workflow(tmp_path, "good", BASE_STATE)
    bad = meta_root(tmp_path, "bad")
    bad.mkdir(parents=True)
    (bad / "state.json").write_text("{损坏", encoding="utf-8")
    infos = {i.name: i for i in scan_all([tmp_path])}
    assert infos["good"].error is None
    assert infos["bad"].error is not None  # 坏实例如实暴露，不拖垮全局
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_dl_dashboard_scanner.py -x -q`
Expected: FAIL `ModuleNotFoundError: No module named 'dl_dashboard.scanner'`

- [ ] **Step 3: 实现 `dl_dashboard/scanner.py`**

```python
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
    problem_statement: str
    nodes: tuple[NodeStatus, ...]
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
        ))
    return tuple(out)


def scan_workflow(project: Path, name: str) -> WorkflowInfo:
    state = load_state(project, name)
    if state is None:
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
        problem_statement=str(state.get("problem_statement", "")),
        nodes=node_statuses(state),
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
                    updated_at="", problem_statement="", nodes=(), error=str(exc),
                ))
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_dl_dashboard_scanner.py -x -q`
Expected: 5 PASS（若 `execute:0` 等节点 id 断言与实际节点表不符，以 `_NODES` 真实键修正测试——节点真源在 engine）

- [ ] **Step 5: Commit**

```bash
git add dl_dashboard/scanner.py tests/test_dl_dashboard_scanner.py
git commit -m "feat(dashboard): scanner 跨项目工作流扫描 + 节点状态模型"
```

---

### Task 4: metrics.py — 每 step 耗时/轮数/token/成本聚合

**Files:**
- Create: `dl_dashboard/metrics.py`
- Test: `tests/test_dl_dashboard_metrics.py`

**Interfaces:**
- Consumes: `scanner.meta_root`；Task 1 的 `segment_stats.jsonl`；`drive-stream.jsonl` 的 result 事件
- Produces: `SegmentStat` dataclass；`collect_stats(project: Path, name: str, cache_dir: Path) -> list[SegmentStat]`；`totals(stats) -> dict`（键 `num_turns/duration_s/cost_usd`）。Task 7 app.py 消费。

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_dl_dashboard_metrics.py -x -q`
Expected: FAIL `ModuleNotFoundError: No module named 'dl_dashboard.metrics'`

- [ ] **Step 3: 实现 `dl_dashboard/metrics.py`**

```python
"""每段耗时/轮数/成本聚合：segment_sessions join segment_stats.jsonl（新）
或 drive-stream.jsonl result 事件（旧工作流回退，offset 书签增量扫）。"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from dl_dashboard.scanner import meta_root

log = logging.getLogger("dl_dashboard.metrics")


@dataclass(frozen=True)
class SegmentStat:
    session_id: str
    kind: str
    node: str
    sub_step: int
    ts: str
    note: str
    num_turns: int | None
    duration_s: int | None
    cost_usd: float | None


def _load_stats_jsonl(meta: Path) -> dict[str, dict]:
    p = meta / "segment_stats.jsonl"
    stats: dict[str, dict] = {}
    if not p.exists():
        return stats
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        sid = ev.get("session_id")
        if sid:
            stats[sid] = ev
    return stats


def _legacy_result_stats(meta: Path, cache_dir: Path, slug: str) -> dict[str, dict]:
    """旧工作流回退：增量扫 drive-stream.jsonl 的 result 事件。

    该文件是原始流（858k 行级，混 SDK 噪声行），全量扫太贵——offset 书签 +
    已提取统计缓存在 cache_dir/<slug>.json；文件截断（size < offset）重置重扫。
    解析失败的行跳过（噪声行是常态），JSON 层异常记 log 不吞。
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_p = cache_dir / f"{slug}.json"
    offset, stats = 0, {}
    if cache_p.exists():
        try:
            d = json.loads(cache_p.read_text(encoding="utf-8"))
            offset, stats = int(d.get("offset", 0)), d.get("stats", {})
        except (json.JSONDecodeError, ValueError, OSError):
            log.warning("legacy stats 缓存损坏，重置重扫: %s", cache_p)
            offset, stats = 0, {}
    stream = meta / "drive-stream.jsonl"
    if not stream.exists():
        return stats
    size = stream.stat().st_size
    if size < offset:
        offset, stats = 0, {}
    with open(stream, "r", encoding="utf-8", errors="replace") as fh:
        fh.seek(offset)
        for line in fh:
            if '"type":"result"' not in line and '"type": "result"' not in line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "result" and ev.get("session_id"):
                stats[ev["session_id"]] = ev
        offset = fh.tell()
    try:
        cache_p.write_text(
            json.dumps({"offset": offset, "stats": stats}), encoding="utf-8")
    except OSError:
        log.warning("legacy stats 缓存写失败: %s", cache_p, exc_info=True)
    return stats


def collect_stats(project: Path, name: str, cache_dir: Path) -> list[SegmentStat]:
    meta = meta_root(project, name)
    state = json.loads((meta / "state.json").read_text(encoding="utf-8"))
    segs = state.get("segment_sessions", [])
    slug = f"{str(project).replace('/', '_')}--{name}"
    legacy = _legacy_result_stats(meta, cache_dir, slug)
    current = _load_stats_jsonl(meta)
    stats = {**legacy, **current}  # 新埋点优先
    out: list[SegmentStat] = []
    for seg in segs:
        st = stats.get(seg.get("session_id"), {})
        dur = st.get("duration_ms")
        out.append(SegmentStat(
            session_id=str(seg.get("session_id", "")),
            kind=str(seg.get("kind", "")),
            node=str(seg.get("node") or "?"),
            sub_step=int(seg.get("sub_step") or 0),
            ts=str(seg.get("ts", "")),
            note=str(seg.get("note", "")),
            num_turns=st.get("num_turns"),
            duration_s=int(dur) // 1000 if dur is not None else None,
            cost_usd=st.get("total_cost_usd"),
        ))
    return out


def totals(stats: list[SegmentStat]) -> dict:
    return {
        "num_turns": sum(s.num_turns for s in stats if s.num_turns is not None),
        "duration_s": sum(s.duration_s for s in stats if s.duration_s is not None),
        "cost_usd": round(sum(s.cost_usd for s in stats if s.cost_usd is not None), 4),
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_dl_dashboard_metrics.py -x -q`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add dl_dashboard/metrics.py tests/test_dl_dashboard_metrics.py
git commit -m "feat(dashboard): metrics 段统计聚合（新埋点 join + 旧流 offset 增量回退）"
```

---

### Task 5: driver_mgr.py — driver 进程托管（spawn/认领/stop）

**Files:**
- Create: `dl_dashboard/driver_mgr.py`
- Test: `tests/test_dl_dashboard_driver_mgr.py`

**Interfaces:**
- Produces: `DriverManager(dlwf: Path, runtime_dir: Path)`，方法 `start(project, name, worktree) -> int(pid)`、`alive(project, name) -> int | None`、`stop(project, name) -> bool`。PID 文件 `<runtime_dir>/<slug>.pid`，driver 日志 `<runtime_dir>/<slug>.log`，slug = `str(project).replace("/","_") + "--" + name`。Task 6/7 消费。

- [ ] **Step 1: 写失败测试**

```python
"""dl_dashboard.driver_mgr：driver 生命周期（mock subprocess）。"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from dl_dashboard.driver_mgr import DriverManager


def _mgr(tmp_path) -> DriverManager:
    return DriverManager(dlwf=tmp_path / "dlwf", runtime_dir=tmp_path / "run")


def test_start_spawns_setsid_and_writes_pid(tmp_path):
    mgr = _mgr(tmp_path)
    fake = MagicMock()
    fake.pid = 4242
    fake.poll.return_value = None
    with patch("dl_dashboard.driver_mgr.subprocess.Popen", return_value=fake) as pop:
        pid = mgr.start(Path("/p"), "demo", Path("/p/.claude/worktrees/demo"))
    assert pid == 4242
    args, kwargs = pop.call_args
    assert kwargs["start_new_session"] is True          # setsid 独立进程组
    assert kwargs["cwd"] == "/p/.claude/worktrees/demo"
    assert kwargs["stdin"] is not None                  # DEVNULL
    assert "dl_drive.py" in args[0][1]
    assert mgr._pid_path(mgr.slug("/p", "demo")).read_text().strip() == "4242"
    assert mgr.alive(Path("/p"), "demo") == 4242


def test_alive_returns_none_when_exited(tmp_path):
    mgr = _mgr(tmp_path)
    fake = MagicMock()
    fake.pid = 4242
    fake.poll.return_value = 1                          # 已退出
    with patch("dl_dashboard.driver_mgr.subprocess.Popen", return_value=fake):
        mgr.start(Path("/p"), "demo", Path("/wt"))
    assert mgr.alive(Path("/p"), "demo") is None


def test_alive_claims_pid_file_after_backend_restart(tmp_path):
    """后端重启（内存空）-> 读 pid 文件 + /proc cmdline 校验认领。"""
    mgr = _mgr(tmp_path)
    mgr._pid_path(mgr.slug("/p", "demo")).write_text(str(os.getpid()), encoding="utf-8")
    real = f"python3 /x/dl_drive.py demo".encode()
    with patch("dl_dashboard.driver_mgr.Path.read_bytes", return_value=real):
        assert mgr.alive(Path("/p"), "demo") == os.getpid()


def test_alive_rejects_recycled_pid(tmp_path):
    """pid 复用防护：cmdline 不含 dl_drive + 工作流名 -> 不认领。"""
    mgr = _mgr(tmp_path)
    mgr._pid_path(mgr.slug("/p", "demo")).write_text(str(os.getpid()), encoding="utf-8")
    with patch("dl_dashboard.driver_mgr.Path.read_bytes", return_value=b"/usr/bin/other"):
        assert mgr.alive(Path("/p"), "demo") is None


def test_stop_kills_process_group(tmp_path):
    mgr = _mgr(tmp_path)
    fake = MagicMock()
    fake.pid = 4242
    fake.poll.return_value = None
    with patch("dl_dashboard.driver_mgr.subprocess.Popen", return_value=fake):
        mgr.start(Path("/p"), "demo", Path("/wt"))
    with patch("dl_dashboard.driver_mgr.os.killpg") as killpg:
        assert mgr.stop(Path("/p"), "demo") is True
        killpg.assert_called_once()
    fake.poll.return_value = -15
    assert mgr.alive(Path("/p"), "demo") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_dl_dashboard_driver_mgr.py -x -q`
Expected: FAIL `ModuleNotFoundError: No module named 'dl_dashboard.driver_mgr'`

- [ ] **Step 3: 实现 `dl_dashboard/driver_mgr.py`**

```python
"""driver 进程托管：spawn(setsid) / PID 文件 / 后端重启认领 / killpg 停止。

保活语义（dashboard-design §5）：工作流真实状态全落盘，driver 死 = 标红可
一键重驱，不是数据丢失。认领校验 /proc/<pid>/cmdline 防 pid 复用误认。
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import time
from pathlib import Path

log = logging.getLogger("dl_dashboard.driver_mgr")


class DriverManager:
    def __init__(self, dlwf: Path, runtime_dir: Path):
        self.dlwf = Path(dlwf)
        self.runtime_dir = Path(runtime_dir)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._drivers: dict[str, subprocess.Popen] = {}

    @staticmethod
    def slug(project, name: str) -> str:
        return f"{str(project).replace('/', '_')}--{name}"

    def _pid_path(self, slug: str) -> Path:
        return self.runtime_dir / f"{slug}.pid"

    def log_path(self, slug: str) -> Path:
        return self.runtime_dir / f"{slug}.log"

    def start(self, project, name: str, worktree) -> int:
        slug = self.slug(project, name)
        log_f = open(self.log_path(slug), "ab")
        proc = subprocess.Popen(
            ["python3", str(self.dlwf / "scripts" / "workflow" / "dl_drive.py"), name],
            cwd=str(worktree),
            stdin=subprocess.DEVNULL,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # setsid：后端死/终端信号不波及 driver
        )
        self._drivers[slug] = proc
        self._pid_path(slug).write_text(str(proc.pid), encoding="utf-8")
        log.info("driver started slug=%s pid=%s", slug, proc.pid)
        return proc.pid

    def alive(self, project, name: str) -> int | None:
        slug = self.slug(project, name)
        proc = self._drivers.get(slug)
        if proc is not None:
            return proc.pid if proc.poll() is None else None
        # 后端重启后认领：pid 文件 + /proc cmdline 双重校验（防 pid 复用）
        p = self._pid_path(slug)
        if not p.exists():
            return None
        try:
            pid = int(p.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
        except (ValueError, OSError):
            return None
        if b"dl_drive.py" in cmdline and name.encode() in cmdline:
            return pid
        return None

    def stop(self, project, name: str) -> bool:
        slug = self.slug(project, name)
        pid = self.alive(project, name)
        if pid is None:
            return False
        try:
            os.killpg(pid, signal.SIGTERM)  # 进程组整体停（driver + 段子进程）
        except OSError:
            log.warning("killpg 失败 slug=%s pid=%s", slug, pid, exc_info=True)
            return False
        self._drivers.pop(slug, None)
        log.info("driver stopped slug=%s pid=%s", slug, pid)
        return True

    def running(self) -> list[str]:
        return [s for s, p in self._drivers.items() if p.poll() is None]
```

（注：`time` import 若未用到则删掉。）

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_dl_dashboard_driver_mgr.py -x -q`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add dl_dashboard/driver_mgr.py tests/test_dl_dashboard_driver_mgr.py
git commit -m "feat(dashboard): driver_mgr driver 进程托管（setsid/PID/认领/killpg）"
```

---

### Task 6: actions.py — 写操作（create/statement/inject/gate/dl 指令/drive）

**Files:**
- Create: `dl_dashboard/actions.py`
- Test: `tests/test_dl_dashboard_actions.py`

**Interfaces:**
- Consumes: `DriverManager`、`scanner.meta_root`、engine 函数与 CLI
- Produces: `create_workflow(project, name, statement, mgr) -> tuple[bool, str]`；`inject_answer(project, name, answer) -> tuple[bool, str]`；`gate_release(project, name) -> tuple[bool, str]`；`dl_command(project, name, cmd, value=None) -> tuple[bool, str]`；`restart_drive(project, name, mgr) -> tuple[bool, str]`。全部返回 `(成功与否, 用户可见消息)`。Task 7 消费。

- [ ] **Step 1: 写失败测试**

```python
"""dl_dashboard.actions：写操作封装（mock 子进程与 engine）。"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dl_dashboard import actions
from dl_dashboard.scanner import meta_root


def _mk_state(project: Path, name: str, segs) -> Path:
    meta = meta_root(project, name)
    meta.mkdir(parents=True)
    state = {
        "name": name, "phase": "plan", "sub_index": 4, "sub_step_index": 2,
        "node": "plan:4", "gate": "pending", "held_for_gate": True,
        "worktree_path": str(project / ".claude" / "worktrees" / name),
        "segment_sessions": segs,
    }
    (meta / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return meta


def test_create_success_when_instance_on_disk(tmp_path):
    def fake_run(cmd, **kw):
        # launcher 跑完实例已落盘
        (tmp_path / ".claude" / "workflows" / "demo").mkdir(parents=True)
        (tmp_path / ".claude" / "workflows" / "demo" / "state.json").write_text(
            '{"worktree_path": "/wt"}', encoding="utf-8")
        return MagicMock(returncode=0, stdout="ok", stderr="")
    mgr = MagicMock()
    with patch.object(actions.subprocess, "run", side_effect=fake_run), \
         patch.object(actions.engine, "set_problem_statement") as sps:
        ok, msg = actions.create_workflow(tmp_path, "demo", "问题X", mgr)
    assert ok, msg
    sps.assert_called_once()
    mgr.start.assert_called_once()


def test_create_failure_when_no_instance(tmp_path):
    with patch.object(actions.subprocess, "run",
                      return_value=MagicMock(returncode=1, stdout="", stderr="boom")):
        ok, msg = actions.create_workflow(tmp_path, "demo", "问题X", MagicMock())
    assert not ok and "boom" in msg


def test_inject_targets_needuser_segment_only(tmp_path):
    segs = [
        {"ts": "t1", "session_id": "sid-old", "kind": "tui-step-needuser",
         "node": "plan:4", "sub_step": 1, "note": "rc=0"},
        {"ts": "t2", "session_id": "sid-cur", "kind": "tui-step-needuser",
         "node": "plan:4", "sub_step": 2, "note": "rc=1"},
    ]
    meta = _mk_state(tmp_path, "demo", segs)
    (meta / "settings.drive-tui.json").write_text("{}", encoding="utf-8")
    (meta / "tui-rules.plan:4.md").write_text("rules", encoding="utf-8")
    with patch.object(actions.subprocess, "run",
                      return_value=MagicMock(returncode=0, stdout="", stderr="")) as run:
        ok, msg = actions.inject_answer(tmp_path, "demo", "选A")
    assert ok, msg
    cmd = run.call_args[0][0]
    assert cmd[cmd.index("--resume") + 1] == "sid-cur"  # 当前步段，禁回落旧段
    assert cmd[cmd.index("-p") + 1] == "选A"


def test_inject_aborts_without_needuser_segment(tmp_path):
    _mk_state(tmp_path, "demo", [
        {"ts": "t", "session_id": "sid-x", "kind": "headless-step",
         "node": "plan:4", "sub_step": 2, "note": "rc=0"}])
    ok, msg = actions.inject_answer(tmp_path, "demo", "选A")
    assert not ok and "无 tui-step-needuser" in msg  # wf_ctl 同语义中止


def test_gate_release_runs_engine_cli(tmp_path):
    _mk_state(tmp_path, "demo", [])
    with patch.object(actions.subprocess, "run",
                      return_value=MagicMock(returncode=0, stdout="✓ 已放行", stderr="")) as run:
        ok, msg = actions.gate_release(tmp_path, "demo")
    assert ok
    cmd = run.call_args[0][0]
    assert "subgate-pass" in cmd and "demo" in cmd


def test_dl_command_rejects_unknown_cmd(tmp_path):
    ok, msg = actions.dl_command(tmp_path, "demo", "rm-rf")
    assert not ok and "不支持" in msg
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_dl_dashboard_actions.py -x -q`
Expected: FAIL `ModuleNotFoundError: No module named 'dl_dashboard.actions'`

- [ ] **Step 3: 实现 `dl_dashboard/actions.py`**

```python
"""写操作：create / statement / inject / gate 放行 / /dl 指令 / 重新驱动。

inject 语义对齐 ~/scripts/wf_ctl.py cmd_inject：注入目标 = 当前 node#step 的
tui-step-needuser 段台账（唯一权威源），找不到即中止，禁回落最新段
（两轮竞态实爆教训：注进已完成段触发重写）。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from dl_dashboard.scanner import meta_root

DLWF = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DLWF))

import dl_flow_engine as engine  # noqa: E402

log = logging.getLogger("dl_dashboard.actions")

ALLOWED_DL_CMDS = ("advance", "step-pass", "dispute", "state-reset")


def create_workflow(project: Path, name: str, statement: str, mgr,
                    timeout: int = 600) -> tuple[bool, str]:
    """launcher 建实例（headless）-> 置 problem_statement -> 起 driver。

    成败判定沿用 wf_ctl：实例落盘（state.json 存在）即建成，launcher
    超时/非零 rc 只作消息展示（driver 在 TTY 缺失下徘徊是已知形态）。
    """
    try:
        p = subprocess.run(
            ["bash", str(DLWF / "scripts" / "workflow" / "dl-launch.sh"),
             "--workflow", name, "--headless"],
            cwd=str(project), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=timeout,
        )
        tail = (p.stdout + p.stderr)[-500:]
    except subprocess.TimeoutExpired:
        tail = "launcher 超时（实例已落盘即达目的，driver 残留自查）"
    state_p = meta_root(project, name) / "state.json"
    if not state_p.exists():
        return False, f"建实例失败：{tail}"
    engine.set_problem_statement(project, name, statement)
    state = engine.load_state(project, name)
    mgr.start(project, name, Path(state["worktree_path"]))
    return True, f"工作流 {name} 已建并启动 driver。{tail[-200:]}"


def _find_needuser_sid(project: Path, name: str, state: dict, nid: str, cur: int) -> str | None:
    for seg in reversed(state.get("segment_sessions", [])):
        if (seg.get("kind") == "tui-step-needuser"
                and seg.get("node") == nid and seg.get("sub_step") == cur):
            return seg["session_id"]
    return None


def inject_answer(project: Path, name: str, answer: str) -> tuple[bool, str]:
    state = engine.normalize_state(engine.load_state(project, name))
    node = engine.get_node(state["phase"], state["sub_index"])
    nid = engine.node_id(node.phase, node.sub)
    cur = state.get("sub_step_index", 1)
    step = engine.sub_step_at(node, cur)
    sid = _find_needuser_sid(project, name, state, nid, cur)
    if sid is None:
        return False, (f"中止注入：{nid}#{cur} 无 tui-step-needuser 段记录——"
                       "state 可能已推进（先刷新确认当前步）")
    meta = meta_root(project, name)
    ov = engine.segment_spawn_overrides(node, step)
    cmd = [
        "claude", "--resume", sid,
        "--settings", str(meta / "settings.drive-tui.json"),
        "--append-system-prompt-file", str(meta / f"tui-rules.{nid}.md"),
        "--permission-mode", "acceptEdits",
    ]
    if ov["tools"]:
        tools = tuple(ov["tools"]) + ("AskUserQuestion", "TaskCreate", "TaskUpdate")
        cmd += ["--tools", ",".join(tools)]
    cmd += ["-p", answer]
    cmd += list(engine.NO_MCP_ARGS)
    env = dict(os.environ)
    env.update(ov.get("env") or {})
    log.info("inject -> %s#%s sid=%s…", nid, cur, sid[:8])
    p = subprocess.run(cmd, cwd=state["worktree_path"], env=env,
                       stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if p.returncode != 0:
        return False, f"注入失败 rc={p.returncode}：{(p.stdout + p.stderr)[-300:]}"
    return True, f"已注入 {nid}#{cur}"


def gate_release(project: Path, name: str) -> tuple[bool, str]:
    """gate 放行 = engine CLI subgate-pass（/dl gate 同路由 release_subgate）。"""
    state = engine.load_state(project, name)
    p = subprocess.run(
        ["python3", str(DLWF / "dl_flow_engine.py"), "subgate-pass", name],
        cwd=state["worktree_path"], stdin=subprocess.DEVNULL,
        capture_output=True, text=True,
    )
    msg = (p.stdout + p.stderr).strip()
    return p.returncode == 0, msg


def dl_command(project: Path, name: str, cmd: str, value: str | None = None) -> tuple[bool, str]:
    if cmd not in ALLOWED_DL_CMDS:
        return False, f"不支持的指令 {cmd}（白名单：{'/'.join(ALLOWED_DL_CMDS)}）"
    state = engine.load_state(project, name)
    argv = ["python3", str(DLWF / "dl_flow_engine.py"), cmd, name]
    if value:
        argv.append(value)
    p = subprocess.run(argv, cwd=state["worktree_path"], stdin=subprocess.DEVNULL,
                       capture_output=True, text=True)
    return p.returncode == 0, (p.stdout + p.stderr).strip()


def restart_drive(project: Path, name: str, mgr) -> tuple[bool, str]:
    """driver 死/断点后重新驱动（续跑非重来：state 全在盘上）。"""
    if mgr.alive(project, name):
        return False, "driver 仍在运行，无需重驱"
    state = engine.load_state(project, name)
    pid = mgr.start(project, name, Path(state["worktree_path"]))
    return True, f"driver 已重启 pid={pid}"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_dl_dashboard_actions.py -x -q`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add dl_dashboard/actions.py tests/test_dl_dashboard_actions.py
git commit -m "feat(dashboard): actions 写操作（create/inject/gate/dl 指令/重驱）"
```

---

### Task 7: app.py — FastAPI 路由 + SSE

**Files:**
- Create: `dl_dashboard/app.py`
- Test: `tests/test_dl_dashboard_app.py`

**Interfaces:**
- Consumes: 全部前序模块
- Produces: `create_app(config: DashboardConfig | None = None) -> FastAPI`；`__main__` 入口 `python3 -m dl_dashboard.app`。路由（全部 JSON，project 用 query/body 传完整路径串，服务端校验 ∈ config.projects）：
  - `GET /` → static/index.html；`GET /static/*` → 静态资源
  - `GET /api/workflows` → `[{...WorkflowInfo, driver_pid, totals}]`
  - `GET /api/workflow?project=&name=` → `{info, stats, totals, need_user, driver_pid, log_tail}`
  - `POST /api/create` `{project, name, statement}`
  - `POST /api/inject` `{project, name, answer}`（成功后自动 restart_drive）
  - `POST /api/gate` `{project, name}`（成功后自动 restart_drive）
  - `POST /api/drive` `{project, name}`
  - `POST /api/dl` `{project, name, cmd, value?}`
  - `GET /api/events` → SSE，每 2s 推 `{"workflows": [...]}`（同 /api/workflows 载荷）

- [ ] **Step 1: 写失败测试**

```python
"""dl_dashboard.app：路由级测试（TestClient + tmp 项目）。"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from dl_dashboard.app import create_app
from dl_dashboard.config import DashboardConfig
from dl_dashboard.scanner import meta_root


@pytest.fixture()
def client(tmp_path):
    project = tmp_path / "proj"
    meta = meta_root(project, "demo")
    meta.mkdir(parents=True)
    (meta / "state.json").write_text(json.dumps({
        "name": "demo", "phase": "plan", "sub_index": 2, "sub_step_index": 1,
        "node": "plan:2", "gate": "pending", "held_for_gate": False,
        "updated_at": "t", "problem_statement": "Q", "history": [],
        "segment_sessions": [],
    }), encoding="utf-8")
    cfg = DashboardConfig(projects=(project,), host="127.0.0.1", port=0)
    app = create_app(cfg)
    return TestClient(app), project


def test_list_workflows(client):
    c, project = client
    r = c.get("/api/workflows")
    assert r.status_code == 200
    rows = r.json()["workflows"]
    assert len(rows) == 1 and rows[0]["name"] == "demo"
    assert rows[0]["node"] == "plan:2"
    assert rows[0]["driver_pid"] is None
    assert rows[0]["totals"]["cost_usd"] == 0


def test_detail(client):
    c, project = client
    r = c.get("/api/workflow", params={"project": str(project), "name": "demo"})
    assert r.status_code == 200
    d = r.json()
    assert d["info"]["name"] == "demo"
    assert d["stats"] == [] and d["need_user"] is None
    assert isinstance(d["log_tail"], str)


def test_project_whitelist_enforced(client):
    c, _ = client
    r = c.get("/api/workflow", params={"project": "/etc", "name": "x"})
    assert r.status_code == 403


def test_post_dl_rejects_bad_cmd(client):
    c, project = client
    r = c.post("/api/dl", json={"project": str(project), "name": "demo", "cmd": "rm"})
    assert r.status_code == 200 and r.json()["ok"] is False


def test_post_gate_calls_action_and_redrives(client):
    c, project = client
    with patch("dl_dashboard.app.actions.gate_release", return_value=(True, "✓")) as gr, \
         patch("dl_dashboard.app.actions.restart_drive", return_value=(True, "ok")) as rd:
        r = c.post("/api/gate", json={"project": str(project), "name": "demo"})
    assert r.json()["ok"] is True
    gr.assert_called_once()
    rd.assert_called_once()


def test_events_streams_first_frame(client):
    c, _ = client
    with c.stream("GET", "/api/events") as r:
        assert r.status_code == 200
        first = next(r.iter_lines())
        assert first.startswith("data: ")
        payload = json.loads(first.removeprefix("data: "))
        assert "workflows" in payload
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_dl_dashboard_app.py -x -q`
Expected: FAIL `ModuleNotFoundError: No module named 'dl_dashboard.app'`

- [ ] **Step 3: 实现 `dl_dashboard/app.py`**

```python
"""FastAPI 入口：路由 + SSE + 静态页。

运行：python3 -m dl_dashboard.app（读 ~/.dl-workflow/dashboard.toml）
写操作 per-workflow asyncio.Lock 串行化（防双击/多标签页并发注入）。
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from dl_dashboard import actions, metrics, scanner
from dl_dashboard.config import DashboardConfig, load_config
from dl_dashboard.driver_mgr import DriverManager

log = logging.getLogger("dl_dashboard")

DLWF = Path(__file__).resolve().parents[1]
CACHE_DIR = DLWF / "dashboard-cache"
RUNTIME_DIR = DLWF / "dashboard-run"
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(config: DashboardConfig | None = None) -> FastAPI:
    cfg = config or load_config()
    mgr = DriverManager(DLWF, RUNTIME_DIR)
    app = FastAPI(title="dl-workflow dashboard")
    locks: dict[str, asyncio.Lock] = {}

    def _project(raw: str) -> Path:
        p = Path(raw)
        if p not in cfg.projects:
            raise HTTPException(403, f"项目未登记: {raw}")
        return p

    def _lock(project: Path, name: str) -> asyncio.Lock:
        return locks.setdefault(f"{project}::{name}", asyncio.Lock())

    def _row(info: scanner.WorkflowInfo) -> dict:
        project = Path(info.project)
        stats = []
        if info.error is None:
            try:
                stats = metrics.collect_stats(project, info.name, CACHE_DIR)
            except Exception as exc:  # noqa: BLE001 - 统计降级不拖垮列表，error 暴露
                log.warning("collect_stats 失败 %s: %s", info.name, exc)
        return {
            **asdict(info),
            "driver_pid": mgr.alive(project, info.name),
            "totals": metrics.totals(stats),
        }

    def _snapshot() -> dict:
        return {"workflows": [_row(i) for i in scanner.scan_all(cfg.projects)]}

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/workflows")
    def list_workflows():
        return _snapshot()

    @app.get("/api/workflow")
    def detail(project: str, name: str):
        proj = _project(project)
        info = scanner.scan_workflow(proj, name)
        stats = metrics.collect_stats(proj, name, CACHE_DIR)
        nu_p = scanner.meta_root(proj, name) / "need_user.json"
        need_user = None
        if nu_p.exists():
            try:
                need_user = json.loads(nu_p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                need_user = {"error": "need_user.json 解析失败"}
        slug = mgr.slug(proj, name)
        log_p = mgr.log_path(slug)
        log_tail = ""
        if log_p.exists():
            log_tail = log_p.read_text(encoding="utf-8", errors="replace")[-4000:]
        return {
            "info": asdict(info),
            "stats": [asdict(s) for s in stats],
            "totals": metrics.totals(stats),
            "need_user": need_user,
            "driver_pid": mgr.alive(proj, name),
            "log_tail": log_tail,
        }

    @app.post("/api/create")
    async def create(body: dict):
        proj = _project(body["project"])
        async with _lock(proj, body["name"]):
            ok, msg = await asyncio.to_thread(
                actions.create_workflow, proj, body["name"], body["statement"], mgr)
        return {"ok": ok, "msg": msg}

    @app.post("/api/inject")
    async def inject(body: dict):
        proj = _project(body["project"])
        name = body["name"]
        async with _lock(proj, name):
            ok, msg = await asyncio.to_thread(
                actions.inject_answer, proj, name, body["answer"])
            if ok:
                await asyncio.to_thread(actions.restart_drive, proj, name, mgr)
        return {"ok": ok, "msg": msg}

    @app.post("/api/gate")
    async def gate(body: dict):
        proj = _project(body["project"])
        name = body["name"]
        async with _lock(proj, name):
            ok, msg = await asyncio.to_thread(actions.gate_release, proj, name)
            if ok:
                await asyncio.to_thread(actions.restart_drive, proj, name, mgr)
        return {"ok": ok, "msg": msg}

    @app.post("/api/drive")
    async def drive(body: dict):
        proj = _project(body["project"])
        async with _lock(proj, body["name"]):
            ok, msg = await asyncio.to_thread(
                actions.restart_drive, proj, body["name"], mgr)
        return {"ok": ok, "msg": msg}

    @app.post("/api/dl")
    async def dl(body: dict):
        proj = _project(body["project"])
        async with _lock(proj, body["name"]):
            ok, msg = await asyncio.to_thread(
                actions.dl_command, proj, body["name"], body["cmd"], body.get("value"))
        return {"ok": ok, "msg": msg}

    @app.get("/api/events")
    async def events():
        async def gen():
            while True:
                snap = await asyncio.to_thread(_snapshot)
                yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
                await asyncio.sleep(2)
        return StreamingResponse(gen(), media_type="text/event-stream")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = load_config()
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_dl_dashboard_app.py -x -q`
Expected: 6 PASS（`/api/events` 首帧测试若因 StreamingResponse 挂起，改用 `anyio` 直接调生成器或放宽为路由存在性断言——以实现为准修正测试，不动语义）

- [ ] **Step 5: Commit**

```bash
git add dl_dashboard/app.py tests/test_dl_dashboard_app.py
git commit -m "feat(dashboard): FastAPI 路由 + SSE 推送"
```

---

### Task 8: 前端单页（列表 + 详情 + 交互区）

**Files:**
- Create: `dl_dashboard/static/index.html`
- Create: `dl_dashboard/static/app.js`
- Create: `dl_dashboard/static/style.css`

**Interfaces:**
- Consumes: Task 7 全部路由
- Produces: 纯静态无构建页面

- [ ] **Step 1: `dl_dashboard/static/index.html`**

```html
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>dl-workflow 控制台</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<header>
  <h1>dl-workflow 控制台</h1>
  <form id="create-form">
    <input id="cf-project" placeholder="项目根路径" required size="34">
    <input id="cf-name" placeholder="工作流名" required>
    <input id="cf-statement" placeholder="问题（problem_statement）" required size="40">
    <button type="submit">新建并启动</button>
  </form>
</header>
<div id="banner" class="hidden"></div>
<main>
  <section id="list-view">
    <h2>工作流</h2>
    <table id="wf-table">
      <thead><tr>
        <th>项目</th><th>名称</th><th>当前节点</th><th>gate</th><th>driver</th>
        <th>轮数</th><th>耗时</th><th>成本</th><th>更新</th>
      </tr></thead>
      <tbody></tbody>
    </table>
  </section>
  <section id="detail-view" class="hidden">
    <h2><a href="#" id="back-link">← 返回</a> <span id="d-title"></span></h2>
    <p id="d-statement"></p>
    <div id="node-strip"></div>
    <div id="interact"></div>
    <h3>段明细</h3>
    <table id="seg-table">
      <thead><tr>
        <th>节点</th><th>子步</th><th>kind</th><th>轮数</th><th>耗时(s)</th>
        <th>成本($)</th><th>时间</th><th>note</th>
      </tr></thead>
      <tbody></tbody>
    </table>
    <h3>driver 日志（尾）</h3>
    <pre id="log-tail"></pre>
  </section>
</main>
<script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: `dl_dashboard/static/app.js`**

```js
/* dl-workflow 控制台：SSE 驱动，列表 + 详情两视图。 */
"use strict";

const sel = { project: null, name: null, nodeFilter: null };
const $ = (id) => document.getElementById(id);

async function post(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}

function fmtDur(s) { return s == null ? "–" : s; }

function banner(text) {
  const b = $("banner");
  if (text) { b.textContent = text; b.classList.remove("hidden"); }
  else b.classList.add("hidden");
}

function renderList(workflows) {
  const tb = document.querySelector("#wf-table tbody");
  tb.innerHTML = "";
  const waiting = [];
  for (const w of workflows) {
    const tr = document.createElement("tr");
    if (w.error) tr.classList.add("err");
    const driver = w.driver_pid ? `🟢 ${w.driver_pid}` : "⚫";
    tr.innerHTML =
      `<td>${w.project.split("/").pop()}</td>` +
      `<td><a href="#">${w.name}</a></td>` +
      `<td>${w.error ? "状态不可读" : w.node}</td>` +
      `<td>${w.gate}${w.held_for_gate ? " 🔒" : ""}</td>` +
      `<td>${driver}</td>` +
      `<td>${w.totals.num_turns}</td><td>${fmtDur(w.totals.duration_s)}</td>` +
      `<td>${w.totals.cost_usd}</td><td>${w.updated_at}</td>`;
    tr.querySelector("a").onclick = (e) => {
      e.preventDefault();
      sel.project = w.project; sel.name = w.name; sel.nodeFilter = null;
      $("list-view").classList.add("hidden");
      $("detail-view").classList.remove("hidden");
      refreshDetail();
    };
    tb.appendChild(tr);
    if (w.need_user || (w.held_for_gate && w.gate === "pending")) {
      waiting.push(`${w.name} @ ${w.node}`);
    }
  }
  if (waiting.length) {
    banner(`等待处理：${waiting.join("、")}`);
    document.title = `(●) dl-workflow 控制台`;
  } else {
    banner(null);
    document.title = "dl-workflow 控制台";
  }
}

function renderNodes(nodes) {
  const strip = $("node-strip");
  strip.innerHTML = "";
  for (const n of nodes) {
    const chip = document.createElement("span");
    chip.className = `chip ${n.status}`;
    chip.textContent = `${n.node_id} ${n.label}`;
    if (sel.nodeFilter === n.node_id) chip.classList.add("active");
    chip.onclick = () => {
      sel.nodeFilter = sel.nodeFilter === n.node_id ? null : n.node_id;
      refreshDetail();
    };
    strip.appendChild(chip);
  }
}

function renderInteract(d) {
  const box = $("interact");
  box.innerHTML = "";
  const proj = sel.project, name = sel.name;
  const mkBtn = (label, fn) => {
    const b = document.createElement("button");
    b.textContent = label; b.onclick = fn; return b;
  };
  if (d.need_user && d.need_user.questions) {
    const h = document.createElement("h3");
    h.textContent = "⏸ 等待输入";
    box.appendChild(h);
    const answers = [];
    d.need_user.questions.forEach((q, i) => {
      const div = document.createElement("div");
      div.className = "q";
      div.innerHTML = `<b>[${q.header || "Q" + (i + 1)}]</b> ${q.question}`;
      (q.options || []).forEach((op) => {
        const l = document.createElement("label");
        l.innerHTML =
          `<input type="radio" name="q${i}" value="${op.label}"> ` +
          `<b>${op.label}</b> — ${op.description || ""}`;
        div.appendChild(l);
      });
      const other = document.createElement("input");
      other.placeholder = "或直接输入答案";
      other.id = `q${i}-other`;
      div.appendChild(other);
      box.appendChild(div);
      answers.push(i);
    });
    box.appendChild(mkBtn("提交答案", async () => {
      const parts = answers.map((i) => {
        const checked = document.querySelector(`input[name=q${i}]:checked`);
        const other = $(`q${i}-other`).value.trim();
        return `问题${i + 1}：${other || (checked ? checked.value : "（未选）")}`;
      });
      const r = await post("/api/inject",
        { project: proj, name, answer: parts.join("\n") });
      alert(r.msg);
      refreshDetail();
    }));
  }
  if (d.info.held_for_gate || d.info.gate === "pending") {
    box.appendChild(mkBtn("✓ gate 放行", async () => {
      const r = await post("/api/gate", { project: proj, name });
      alert(r.msg); refreshDetail();
    }));
  }
  if (!d.driver_pid) {
    box.appendChild(mkBtn("↻ 重新驱动", async () => {
      const r = await post("/api/drive", { project: proj, name });
      alert(r.msg); refreshDetail();
    }));
  }
  const form = document.createElement("span");
  form.innerHTML =
    `<select id="dl-cmd"><option>advance</option><option>step-pass</option>` +
    `<option>dispute</option><option>state-reset</option></select>` +
    `<input id="dl-value" placeholder="参数（可空）" size="18">`;
  const go = mkBtn("执行 /dl", async () => {
    const r = await post("/api/dl", { project: proj, name,
      cmd: $("dl-cmd").value, value: $("dl-value").value || null });
    alert(r.msg); refreshDetail();
  });
  box.appendChild(form); box.appendChild(go);
}

function renderSegs(stats) {
  const tb = document.querySelector("#seg-table tbody");
  tb.innerHTML = "";
  for (const s of stats) {
    if (sel.nodeFilter && s.node !== sel.nodeFilter) continue;
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${s.node}</td><td>${s.sub_step}</td><td>${s.kind}</td>` +
      `<td>${s.num_turns ?? "–"}</td><td>${s.duration_s ?? "–"}</td>` +
      `<td>${s.cost_usd ?? "–"}</td><td>${s.ts}</td><td>${s.note}</td>`;
    tb.appendChild(tr);
  }
}

async function refreshDetail() {
  if (!sel.project) return;
  const r = await fetch(
    `/api/workflow?project=${encodeURIComponent(sel.project)}` +
    `&name=${encodeURIComponent(sel.name)}`);
  const d = await r.json();
  $("d-title").textContent = `${d.info.name} — ${d.info.node}` +
    (d.driver_pid ? `（driver 🟢 ${d.driver_pid}）` : "（driver ⚫）");
  $("d-statement").textContent = d.info.problem_statement;
  renderNodes(d.info.nodes);
  renderInteract(d);
  renderSegs(d.stats);
  $("log-tail").textContent = d.log_tail;
}

$("back-link").onclick = (e) => {
  e.preventDefault();
  sel.project = null;
  $("detail-view").classList.add("hidden");
  $("list-view").classList.remove("hidden");
};

$("create-form").onsubmit = async (e) => {
  e.preventDefault();
  const r = await post("/api/create", {
    project: $("cf-project").value.trim(),
    name: $("cf-name").value.trim(),
    statement: $("cf-statement").value.trim(),
  });
  alert(r.msg);
};

const es = new EventSource("/api/events");
es.onmessage = (e) => {
  const data = JSON.parse(e.data);
  if (!sel.project) renderList(data.workflows);
  else refreshDetail();
};
```

- [ ] **Step 3: `dl_dashboard/static/style.css`**

```css
body { font-family: system-ui, sans-serif; margin: 0; background: #f6f7f9; color: #222; }
header { background: #1f2937; color: #fff; padding: 10px 16px; }
header h1 { font-size: 18px; margin: 0 0 8px; }
header input { margin-right: 6px; padding: 4px; }
main { padding: 16px; }
table { border-collapse: collapse; width: 100%; background: #fff; }
th, td { border: 1px solid #e5e7eb; padding: 5px 8px; font-size: 13px; text-align: left; }
tr.err td { color: #b91c1c; }
#banner { background: #fef3c7; border: 1px solid #f59e0b; padding: 8px 16px; }
.hidden { display: none; }
#node-strip { margin: 10px 0; }
.chip { display: inline-block; border-radius: 12px; padding: 3px 10px; margin: 2px;
  font-size: 12px; cursor: pointer; border: 1px solid #ccc; }
.chip.done { background: #dcfce7; border-color: #22c55e; }
.chip.current { background: #dbeafe; border-color: #3b82f6; animation: blink 1.2s infinite; }
.chip.pending { background: #f3f4f6; color: #9ca3af; }
.chip.active { outline: 2px solid #111; }
@keyframes blink { 50% { opacity: 0.55; } }
#interact { margin: 12px 0; padding: 10px; background: #fff; border: 1px solid #e5e7eb; }
#interact .q { margin: 8px 0; }
#interact .q label { display: block; margin: 2px 0 2px 12px; }
#interact button { margin: 6px 8px 0 0; padding: 5px 14px; }
#log-tail { background: #111827; color: #d1d5db; padding: 10px; font-size: 12px;
  max-height: 260px; overflow: auto; white-space: pre-wrap; }
```

- [ ] **Step 4: 端到端冒烟（真机）**

```bash
cd ~/.dl-workflow-worktrees/dashboard
cat > ~/.dl-workflow/dashboard.toml <<'EOF'
projects = ["/home/admin/projects/factor_ic_analyzer"]
EOF
python3 -m dl_dashboard.app &
sleep 2
curl -s http://127.0.0.1:9000/api/workflows | python3 -m json.tool | head -30
curl -s "http://127.0.0.1:9000/api/workflow?project=/home/admin/projects/factor_ic_analyzer&name=amplitude_annualized" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['totals']); print(d['stats'][-1] if d['stats'] else 'no stats')"
kill %1
```

Expected: 列出真实工作流；amplitude_annualized 的 totals 有非零 cost（legacy 回退解析 drive-stream.jsonl 生效）。

- [ ] **Step 5: Commit**

```bash
git add dl_dashboard/static/
git commit -m "feat(dashboard): 前端单页（列表/节点全景/段明细/交互区）"
```

---

### Task 9: README 使用说明 + 全量回归

**Files:**
- Modify: `README.md`（「用」节后追加 dashboard 小节）

- [ ] **Step 1: README 追加**

```markdown
## 管理后台（dashboard）

浏览器控制台：跨项目启动/驱动工作流、节点状态全景、每段耗时/轮数/token/成本、断点注入与 gate 放行。

```bash
# 配置（登记项目根清单）
cat > ~/.dl-workflow/dashboard.toml <<'EOF'
projects = ["/home/admin/projects/factor_ic_analyzer"]
EOF

# 起服务（0.0.0.0:9000，无认证——公网裸奔，介意就自己 ssh -L 转发后改 host=127.0.0.1）
python3 -m dl_dashboard.app
```

- 会话不断开：driver 是后端 setsid 子进程，浏览器关掉照跑；后端重启自动认领活 driver，认不到的一键「重新驱动」（state 全落盘，续跑非重来）。
- 归档仍走终端 `dl <name> --done`（后台不做删除）。
```

- [ ] **Step 2: 全量回归**

Run: `cd ~/.dl-workflow-worktrees/dashboard && python3 -m pytest tests/ -x -q`
Expected: 全 PASS

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(dashboard): README 管理后台使用说明"
```

---

## 手动验收清单（前端，Task 8 冒烟后逐项过）

- [ ] 列表页按项目显示全部工作流，当前节点/gate/driver 状态正确
- [ ] 新建工作流：填项目/名称/问题 → 列表出现新实例且 driver 🟢
- [ ] 详情页节点全景条：已完成绿/当前蓝闪/未开始灰，点 chip 过滤段明细
- [ ] 段明细表轮数/耗时/成本与 drive-stream.jsonl 实际值一致（抽查一段）
- [ ] need_user 断点：横幅 + 标题 (●) 出现，选选项提交后 state 推进
- [ ] gate 放行后自动重驱，节点推进到下一阶段
- [ ] 关浏览器重开：进度仍在，driver 状态正确
- [ ] 重启后端（kill 后重起）：活 driver 被认领（🟢 不变）
- [ ] /dl 指令：advance 一步生效；非法指令被拒
