# 代码考古杠杆 1+2 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 落地 `dl codebase trace <symbol>`（杠杆 1）+ 通用取证路线模板进 node-rules（杠杆 2）。

**Architecture:** 杠杆 1 = `dl_codebase.py` 加 `trace` 子命令，复用 `_codegraph_json` + `git log -S` + discovery ledger。杠杆 2 = `dl_flow_nodes.py` 的 understand:1 子2 `Step.purpose` 追加通用取证路线段。

**Tech Stack:** Python 3、pytest。

## Global Constraints

- 真源 `~/.dl-workflow/`；H9 ≤3 文件 ≤200 行。
- 通用性：只用 codegraph/git/grep 的代码结构语义，不碰项目数据契约。
- 落账去重沿用 discovery ledger（key=`trace:<symbol>`，`source` 字段）。
- 改 `Step.purpose` 实质内容后须同步 `references/node-design.md` 摘要块（若有）。

---

### Task 1: `dl codebase trace <symbol>`（杠杆 1）

**Files:**
- Modify: `scripts/workflow/dl_codebase.py`
- Test: `tests/test_dl_codebase.py`

**Interfaces:**
- Produces: `query_trace(symbol) -> dict`（`{symbol, definition, callers, callees, impact, history, source}`）；`main` 加 `trace` 子命令。

- [ ] **Step 1: 写失败测试**

```python
def test_query_trace_bundles_and_dedups(monkeypatch, tmp_path):
    """trace 一次返回 5 段 + source；二次命中缓存不重跑。"""
    monkeypatch.setattr(cb, "_resolve_ledger_path", lambda: tmp_path / "discoveries.jsonl")
    calls = {"codegraph": 0, "git": 0}

    def fake_codegraph_json(sub, symbol):
        calls["codegraph"] += 1
        return {"ok": []}

    def fake_run(cmd):
        if cmd[0] == "git":
            calls["git"] += 1
            return subprocess.CompletedProcess(cmd, 0, "abc1234 fix\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(cb, "_codegraph_json", fake_codegraph_json)
    monkeypatch.setattr(cb, "_run", fake_run)
    monkeypatch.setattr(cb, "_current_step", lambda p: "understand:1#2")

    out1 = cb.query_trace("foo")
    assert set(out1) >= {"symbol", "definition", "callers", "callees", "impact", "history"}
    assert out1["source"] == "fresh"
    assert calls["codegraph"] == 4  # query/callers/callees/impact 各一次
    assert calls["git"] == 1       # git log -S 一次

    out2 = cb.query_trace("foo")
    assert out2["source"] == "discovery-ledger"
    assert calls["codegraph"] == 4  # 二次命中，不重跑
```

- [ ] **Step 2: 确认失败**（`query_trace` 不存在）

- [ ] **Step 3: 实现 `query_trace` + `trace` 子命令**

```python
def query_trace(symbol: str) -> dict:
    """符号关系全景：定义+调用者+被调+影响面+git 历史（单层取证一次拿全）。"""
    path = _resolve_ledger_path()
    if path is not None:
        cached = _ledger_get(path, f"trace:{symbol}")
        if cached is not None:
            return {**cached["result"], "source": "discovery-ledger"}
    payload = {
        "symbol": symbol,
        "definition": _codegraph_json("query", symbol),
        "callers": _codegraph_json("callers", symbol),
        "callees": _codegraph_json("callees", symbol),
        "impact": _codegraph_json("impact", symbol),
        "history": _git_log_symbol(symbol),
    }
    if path is not None:
        _ledger_append(path, f"trace:{symbol}", "trace", symbol, payload)
    return {**payload, "source": "fresh"}


def _git_log_symbol(symbol: str) -> dict:
    r = _run(["git", "-C", ".", "log", "--oneline", "-S", symbol, "--max-count", "50"])
    return {"commits": r.stdout.strip().splitlines() if r.returncode == 0 else []}
```

`main()` 里加：
```python
    t = sub.add_parser("trace", help="符号关系全景（def+callers+callees+impact+history）")
    t.add_argument("symbol")
    # 解析：if args.cmd == "trace": out = query_trace(args.symbol)
```
（把 `args.cmd == "query"` 的现有分发逻辑改成按 cmd 分发，或加 `trace` 分支。）

- [ ] **Step 4: 确认通过 + commit**

---

### Task 2: 通用取证路线模板进 node-rules（杠杆 2）

**Files:**
- Modify: `dl_flow_nodes.py`（understand:1 子2 `Step.purpose` 追加路线段）
- Test: `tests/test_dl_drive.py`（node-rules 含路线关键词）

**Interfaces:**
- Produces: node-rules 的 understand:1 子2 段落含 "`dl codebase trace`" / "取证路线"。

- [ ] **Step 1: 写失败测试**

```python
def test_node_rules_has_arch_route(wf_repo):
    """understand:1 子2 段落含通用取证路线（trace/string/history/Read）。"""
    drv = _load(DRIVER, "drv_under_test")
    node = engine.get_node("understand", 1)
    out = drv.ensure_node_rules(wf_repo, "t", node)
    text = out.read_text(encoding="utf-8")
    assert "dl codebase trace" in text
    assert "取证路线" in text
```

- [ ] **Step 2: 确认失败**

- [ ] **Step 3: 实现** —— 在 `dl_flow_nodes.py` 定义 `_CODE_ARCH_ROUTE` 常量，追加到 understand:1 子2 的 `purpose`：

```python
_CODE_ARCH_ROUTE = (
    "单个原子问题取证路线（按需跳步）：1. `dl codebase trace <symbol>` 一次拿"
    "定义+调用者+被调+影响面+历史（symbol 关系查询优先走它，勿逐条 grep）；"
    "2. 字符串/模式定位用 `dl codebase query --string`；"
    "3. 某行何时引入用 `dl codebase query --history <file>:<line>`；"
    "4. 读关键文件正文用 Read。`dl codebase` 自动落账去重，重复查询零成本。"
)
```

- [ ] **Step 4: 确认通过 + 同步 node-design.md 摘要块（若引用子2 purpose）+ commit**

---

## Self-Review

- 杠杆 1/2 均已到实现粒度；通用性只依赖 codegraph/git 语义。
- 遗留待实施确认：`dl_flow_nodes.py` 中 understand:1 子2 `purpose` 的具体拼接位置 + `references/node-design.md` 是否有子2 摘要块需同步。
