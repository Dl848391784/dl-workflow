# 发现台账 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `dl codebase query --symbol/--history` 加「发现台账」——结果自动落账 + 工具级透明去重，后续步骤重查同 symbol/history 时返回缓存，省重复取证。

**Architecture:** 台账 = `<项目>/.claude/workflows/<name>/discoveries.jsonl`（每行 JSON）。`dl_codebase.py` 从 cwd（worktree 路径含 `<name>`）反查工作流名，在 worktree 内去重、worktree 外保持通用工具原行为。`dl_flow_engine.py` 负责 state-reset 清账 + node-rules 注入台账提示。

**Tech Stack:** Python 3（time/json/pathlib）、pytest。

## Global Constraints

- 真源仓库 = `~/.dl-workflow/`。
- H9：单次 ≤3 文件 AND ≤200 行。
- 台账只存**客观事实**（symbol/history），不存 `--string`（grep 便宜+结果大）。
- 只落账 `--symbol`/`--history`；落账失败/台账损坏不阻断取证（宁纵勿枉）。
- 去重在工具层（模型行为零改变），不靠弱模型"查前先读台账"。
- 环境事实：`time.time()` 可用（普通 Python 脚本，非 Workflow JS）；state.json 与台账同目录。

---

### Task 1: `dl_codebase.py` 台账解析 + 去重 + 落账

**Files:**
- Modify: `scripts/workflow/dl_codebase.py`
- Test: `tests/test_dl_codebase.py`

**Interfaces:**
- Produces: `_resolve_ledger_path() -> Path | None`、`_load_ledger(path) -> dict`、`_ledger_get(path, key) -> dict | None`、`_ledger_append(path, key, kind, query, result)`；`query_symbol`/`query_history` 返回体新增顶层 `source` 字段（`"fresh"` / `"discovery-ledger"`）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_dl_codebase.py 追加
import time
from pathlib import Path


def test_symbol_dedup_returns_cached(monkeypatch, tmp_path):
    """worktree 内同 symbol 二次查询返回缓存 + source=discovery-ledger，不重跑 codegraph。"""
    monkeypatch.setattr(cb, "_resolve_ledger_path", lambda: tmp_path / "discoveries.jsonl")
    calls = {"n": 0}

    def fake_codegraph_json(sub, symbol):
        calls["n"] += 1
        return {"ok": [{"node": {"name": "f", "filePath": "a.py", "startLine": 1}}]}

    monkeypatch.setattr(cb, "_codegraph_json", fake_codegraph_json)
    monkeypatch.setattr(cb, "_current_step", lambda p: "understand:1#2")

    out1 = cb.query_symbol("foo")
    out2 = cb.query_symbol("foo")
    assert out1["source"] == "fresh"
    assert out2["source"] == "discovery-ledger"
    assert calls["n"] == 3  # query+callers+impact 只跑一次（3 个子查询），第二次命中缓存
    # 台账文件里只有一条
    lines = (tmp_path / "discoveries.jsonl").read_text().splitlines()
    assert len(lines) == 1


def test_string_not_recorded(monkeypatch, tmp_path):
    """--string 不落账。"""
    monkeypatch.setattr(cb, "_resolve_ledger_path", lambda: tmp_path / "discoveries.jsonl")
    monkeypatch.setattr(cb, "_run", lambda cmd: __import__("subprocess").CompletedProcess(cmd, 0, "a.py:1:x\n", ""))
    cb.query_string("x", None, 5)
    assert not (tmp_path / "discoveries.jsonl").exists()


def test_corrupt_ledger_silently_degrades(monkeypatch, tmp_path):
    """台账损坏 → 正常查询，不抛异常。"""
    (tmp_path / "discoveries.jsonl").write_text("{bad json\n", encoding="utf-8")
    monkeypatch.setattr(cb, "_resolve_ledger_path", lambda: tmp_path / "discoveries.jsonl")
    monkeypatch.setattr(cb, "_codegraph_json", lambda sub, sym: {"ok": []})
    out = cb.query_symbol("foo")
    assert out["source"] == "fresh"  # 损坏 → 视为无账 → 正常 fresh
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/.dl-workflow && pytest tests/test_dl_codebase.py -v`
Expected: FAIL（`AttributeError: module has no attribute '_resolve_ledger_path'`）

- [ ] **Step 3: 实现台账函数 + 改造 query_symbol/query_history**

在 `dl_codebase.py` 顶部 import 区加 `import time` 和 `from pathlib import Path`；加：

```python
def _resolve_ledger_path() -> Path | None:
    """从 cwd（<project>/.claude/worktrees/<name>）反查台账路径；非 worktree 返回 None。"""
    parts = Path.cwd().parts
    if "worktrees" not in parts:
        return None
    idx = parts.index("worktrees")
    if idx + 1 >= len(parts):
        return None
    name = parts[idx + 1]
    project = Path(*parts[: idx - 1]) if idx >= 1 else Path(parts[0])
    return project / ".claude" / "workflows" / name / "discoveries.jsonl"


def _load_ledger(path: Path) -> dict:
    """读台账 → {key: entry}；缺失/损坏返回 {}（宁纵勿枉）。"""
    if not path.exists():
        return {}
    ledger = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            if e.get("key"):
                ledger[e["key"]] = e
    except (OSError, json.JSONDecodeError):
        return {}
    return ledger


def _current_step(path: Path) -> str | None:
    """从同目录 state.json 读 node#sub_step_index；读不到返回 None。"""
    state_path = path.parent / "state.json"
    try:
        s = json.loads(state_path.read_text(encoding="utf-8"))
        return f"{s.get('node', '?')}#{s.get('sub_step_index', '?')}"
    except (OSError, json.JSONDecodeError):
        return None


def _ledger_get(path: Path, key: str) -> dict | None:
    return _load_ledger(path).get(key)


def _ledger_append(path: Path, key: str, kind: str, query: str, result: dict) -> None:
    entry = {"key": key, "kind": kind, "query": query, "result": result,
             "step": _current_step(path), "ts": int(time.time())}
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 落账失败不阻断取证
```

改造 `query_symbol`（在 `_codegraph_json` 之后、返回之前）：

```python
def query_symbol(symbol: str) -> dict:
    path = _resolve_ledger_path()
    if path is not None:
        cached = _ledger_get(path, f"symbol:{symbol}")
        if cached is not None:
            return {**cached["result"], "source": "discovery-ledger"}
    payload = {
        "symbol": symbol,
        "definition": _codegraph_json("query", symbol),
        "callers": _codegraph_json("callers", symbol),
        "impact": _codegraph_json("impact", symbol),
    }
    if path is not None:
        _ledger_append(path, f"symbol:{symbol}", "symbol", symbol, payload)
    return {**payload, "source": "fresh"}
```

改造 `query_history`（同模式，key = `history:{target}`）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ~/.dl-workflow && pytest tests/test_dl_codebase.py -v`
Expected: PASS（原 7 个 + 新 3 个，其中旧 `test_query_symbol_shapes` 需把 `set(out)` 断言改为 `set(out) >= {"symbol","definition","callers","impact"}` 以容纳新增 `source`）

- [ ] **Step 5: commit**

```bash
cd ~/.dl-workflow
git add scripts/workflow/dl_codebase.py tests/test_dl_codebase.py
git commit -m "feat(codebase): 发现台账——symbol/history 落账 + 工具级去重"
```

---

### Task 2: `dl_flow_engine.py` state-reset 清账 + node-rules 注入

**Files:**
- Modify: `dl_flow_engine.py`（state-reset 清账）
- Modify: `scripts/workflow/dl_drive.py`（`ensure_node_rules` 注入台账提示，一行）
- Test: `tests/test_dl_flow_engine.py` / `tests/test_dl_drive.py`

**Interfaces:**
- Consumes: `_resolve_ledger_path` 的路径约定（`<project>/.claude/workflows/<name>/discoveries.jsonl`）。
- Produces: state-reset 时删除 `discoveries.jsonl`；node-rules 含台账路径提示。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_dl_flow_engine.py 追加
def test_state_reset_clears_discoveries(tmp_path, monkeypatch):
    """state-reset 回滚时删除 discoveries.jsonl。"""
    # 构造最小 workflow 目录 + 台账
    meta = tmp_path / ".claude" / "workflows" / "t"
    meta.mkdir(parents=True)
    (meta / "state.json").write_text('{"name":"t","phase":"understand","index":1,"sub_index":1}', encoding="utf-8")
    (meta / "discoveries.jsonl").write_text('{"key":"symbol:x","kind":"symbol"}\n', encoding="utf-8")
    # 调 state-reset 的清理逻辑（按 engine 实际函数签名对齐）
    engine._clear_workflow_discoveries(tmp_path, "t")
    assert not (meta / "discoveries.jsonl").exists()
```

> 若 engine 里 state-reset 的清理是内联逻辑而非独立函数，把清理逻辑抽成 `_clear_workflow_discoveries(project_root, name)` 供测试直调。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/.dl-workflow && pytest tests/test_dl_flow_engine.py -k discoveries -v`
Expected: FAIL（`_clear_workflow_discoveries` 不存在）

- [ ] **Step 3: 实现清账 + node-rules 注入**

1. `dl_flow_engine.py`：加 `_clear_workflow_discoveries(project_root, name)`（删 `discoveries.jsonl`，missing_ok），并在 `state-reset` 回滚路径里调用它（与 evidence 硬删同位置）。
2. `scripts/workflow/dl_drive.py` `ensure_node_rules` 里，在「本节点子步骤清单」段之后加一行提示（仅当台账路径可解析时）：

```python
    ledger = _resolve_ledger_path()
    if ledger is not None:
        text += (
            f"\n## 发现台账\n"
            f"`dl codebase query --symbol/--history` 会自动落账去重到 {ledger}；"
            f"重查同一 symbol/history 返回缓存（source=discovery-ledger），无需手工查账。\n"
        )
```

> `_resolve_ledger_path` 需从 `dl_codebase` import（dl_drive.py 已 sys.path 挂 dl-workflow 根，用 `from scripts.workflow.dl_codebase import _resolve_ledger_path` 对齐既有 import 风格）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ~/.dl-workflow && pytest tests/test_dl_flow_engine.py -k discoveries tests/test_dl_drive.py -k "node_rules or 台账 or ledger" -v`
Expected: PASS

- [ ] **Step 5: commit**

```bash
cd ~/.dl-workflow
git add dl_flow_engine.py scripts/workflow/dl_drive.py tests/test_dl_flow_engine.py tests/test_dl_drive.py
git commit -m "feat(codebase): state-reset 清账 + node-rules 注入台账提示"
```

---

## Self-Review 记录

- **Spec 覆盖**：设计 §1-3（落账+去重）→ Task 1；§4 生命周期（state-reset 清账）+ §5 消费侧（node-rules 注入）→ Task 2；§8 测试 → 各 Task Step 1。
- **占位符扫描**：Task 2 Step 1/3 的「对齐 engine 实际 state-reset 清理位置」是实施时读真实代码对齐（同 codebase-toolbox 计划的「遗留待实施时确认」模式），非占位。
- **类型一致性**：`_resolve_ledger_path` 返回 `Path | None`，Task 1 定义、Task 2 import 消费，一致。

> **遗留待实施时确认**：①engine `state-reset` 的清理逻辑是内联还是已有函数（Task 2 Step 1 对齐）；②旧 `test_query_symbol_shapes` 的 `set(out)` 断言需放宽为 `>=`（容纳新增 `source` 键，Task 1 Step 4 已注明）。
