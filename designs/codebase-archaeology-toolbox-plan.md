# 通用代码考古工具箱 + 项目工具注册 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 dl-workflow 加一个跨项目通用的代码考古工具箱（`dl codebase query`）+ 项目工具注册机制，把 `understand:1 子步骤 2` 的 43 次工具调用压成几个高层语义命令。

**Architecture:** 两个组件。组件 A = 独立脚本 `dl_codebase.py` 包装 codegraph/grep/git，经 `dl-cmd.sh codebase` 路由（`dl-cmd` 已在 S15 白名单，零围栏改动）。组件 B = `<项目>/.claude/workflow-tools.yaml` 注册文件，`ensure_node_rules()` 发现并注入「本项目工具」段，工具 command 头并入 S15 + per-wf settings 白名单。

**Tech Stack:** Python 3（argparse + subprocess + json）、bash（dl-cmd.sh）、pytest。

## Global Constraints

- 真源仓库 = `~/.dl-workflow/`（不是 factor_ic_analyzer）。所有脚本改动在 dl-workflow，`git pull` 即生效（hook 直引源）。
- H15：改已有 `.py` 源码前先跑一次 `codegraph impact <symbol>`（dl-workflow 有自己的 codegraph db）。
- H9：单次 ≤3 文件 AND ≤200 行。本计划每个 Task 的改动都控制在此内。
- 只放行**只读发现类**命令进白名单；写/删命令（`rm/dd/sudo`）不进。
- 输出统一 JSON（`ensure_ascii=False, indent=2`），异常输出结构化 `{"error": ...}` 而非裸栈。
- 编码习惯对齐项目：日志 `%` 惰性格式化、退出码语义（0 成功 / 2 用法错）。
- 环境事实（已核实）：`codegraph` 在 `/home/admin/.npm-global/bin/codegraph`；`git` 在 `/usr/bin/git`；**`rg` 只有 shell 函数（Claude Code shim），无真实二进制**——字符串搜索必须用 `grep`，不能用 `rg`。

---

### Task 1: `dl_codebase.py` 骨架 + `--symbol`（codegraph 包装）

**Files:**
- Create: `scripts/workflow/dl_codebase.py`
- Test: `tests/test_dl_codebase.py`

**Interfaces:**
- Produces: `query_symbol(symbol: str) -> dict`（供 Task 3 CLI 用）、`query_string(...) -> dict`、`query_history(...) -> dict`（Task 2 补）。
- 命令面：`python3 dl_codebase.py query --symbol <sym>` 输出 JSON。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_dl_codebase.py
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "workflow"))
import dl_codebase as cb  # noqa: E402


def test_query_symbol_shapes(monkeypatch):
    """query_symbol 返回三键：definition/callers/impact，各自含 ok 或 error。"""
    calls = {}

    def fake_run(cmd):
        calls[cmd[1]] = cmd
        if cmd[1] == "query":
            return subprocess.CompletedProcess(cmd, 0, json.dumps([{"node": {"name": "f", "filePath": "a.py", "startLine": 1}}]), "")
        if cmd[1] == "callers":
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"callers": [{"name": "g", "filePath": "b.py", "startLine": 2}]}), "")
        if cmd[1] == "impact":
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"affected": []}), "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(cb, "_run", fake_run)
    out = cb.query_symbol("convert_return_to_percentage")
    assert set(out) == {"symbol", "definition", "callers", "impact"}
    assert out["definition"]["ok"][0]["node"]["name"] == "f"
    assert out["callers"]["ok"]["callers"][0]["name"] == "g"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/.dl-workflow && pytest tests/test_dl_codebase.py -v`
Expected: FAIL（`ModuleNotFoundError: dl_codebase`）

- [ ] **Step 3: 写最小实现（含 `_run` + `query_symbol`）**

```python
# scripts/workflow/dl_codebase.py
#!/usr/bin/env python3
"""dl codebase query — 通用代码考古工具箱（组件 A）。

包装 codegraph / grep / git 为结构化 JSON，供工作流模型直接消费。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _codegraph_json(sub: str, symbol: str) -> dict:
    """codegraph <sub> <symbol> --json → {"ok": parsed} 或 {"error": msg}。"""
    r = _run(["codegraph", sub, symbol, "--json"])
    if r.returncode != 0:
        return {"error": r.stderr.strip() or f"codegraph {sub} 失败"}
    try:
        return {"ok": json.loads(r.stdout)}
    except json.JSONDecodeError:
        return {"error": "codegraph 输出非 JSON", "raw": r.stdout[:500]}


def query_symbol(symbol: str) -> dict:
    """符号三连：定义(query) + 调用者(callers) + 影响面(impact)。"""
    return {
        "symbol": symbol,
        "definition": _codegraph_json("query", symbol),
        "callers": _codegraph_json("callers", symbol),
        "impact": _codegraph_json("impact", symbol),
    }


def query_string(pattern: str, type_filter: str | None, max_count: int) -> dict:
    raise NotImplementedError  # Task 2


def query_history(target: str, max_count: int) -> dict:
    raise NotImplementedError  # Task 2


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError  # Task 3


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ~/.dl-workflow && pytest tests/test_dl_codebase.py -v`
Expected: PASS（1 passed）

- [ ] **Step 5: commit**

```bash
cd ~/.dl-workflow
git add scripts/workflow/dl_codebase.py tests/test_dl_codebase.py
git commit -m "feat(codebase): dl_codebase.py 骨架 + --symbol codegraph 包装"
```

---

### Task 2: `--string`（grep 包装）+ `--history`（git 包装）

**Files:**
- Modify: `scripts/workflow/dl_codebase.py`（实现两个 `NotImplementedError`）
- Test: `tests/test_dl_codebase.py`

**Interfaces:**
- Produces: `query_string(pattern, type_filter, max_count) -> dict`、`query_history(target, max_count) -> dict`（Task 3 CLI 用）。

- [ ] **Step 1: 写失败测试**

```python
def test_query_string_parses_grep(monkeypatch):
    """grep -rn 输出解析成 matches:[{file,line,text}]，并带 exclude 参数。"""
    captured = {}

    def fake_run(cmd):
        captured["cmd"] = cmd
        out = "backtest/common/layered_backtest.py:624:    return_col=\"forward_return_1d\",\n"
        return subprocess.CompletedProcess(cmd, 0, out, "")

    monkeypatch.setattr(cb, "_run", fake_run)
    out = cb.query_string("forward_return_1d", None, 50)
    assert out["matches"] == [
        {"file": "backtest/common/layered_backtest.py", "line": 624, "text": '    return_col="forward_return_1d",'}
    ]
    # 关键：必须排除 .git / .claude
    assert "--exclude-dir=.git" in captured["cmd"]
    assert "--exclude-dir=.claude" in captured["cmd"]


def test_query_history_parses_blame(monkeypatch):
    """--history <file>:<line> 返回 blame + commits。"""
    def fake_run(cmd):
        if cmd[0] == "git" and cmd[1] == "-C" and cmd[3] == "blame":
            return subprocess.CompletedProcess(cmd, 0, "abc1234 (dev) line content", "")
        return subprocess.CompletedProcess(cmd, 0, "abc1234 fix\nabc0000 init\n", "")

    monkeypatch.setattr(cb, "_run", fake_run)
    out = cb.query_history("summary/report/data_loaders.py:120", 50)
    assert out["target"] == "summary/report/data_loaders.py:120"
    assert "abc1234" in out["blame"]
    assert out["commits"] == ["abc1234 fix", "abc0000 init"]


def test_query_history_bad_target():
    """缺 : 的目标报结构化 error，不抛异常。"""
    out = cb.query_history("noline", 50)
    assert "error" in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/.dl-workflow && pytest tests/test_dl_codebase.py -v`
Expected: FAIL（`NotImplementedError`）

- [ ] **Step 3: 实现 `query_string` 和 `query_history`**

```python
_GREP_EXCLUDES = ["--exclude-dir=.git", "--exclude-dir=.claude", "--exclude-dir=__pycache__", "--exclude-dir=node_modules"]
_TYPE_INCLUDE = {"py": "*.py", "html": "*.html", "js": "*.js", "ts": "*.ts"}


def query_string(pattern: str, type_filter: str | None, max_count: int) -> dict:
    """字符串/正则搜索（grep -rn，带排除目录 + 可选 --include）。"""
    cmd = ["grep", "-rn", "--no-heading", *_GREP_EXCLUDES]
    if type_filter and type_filter in _TYPE_INCLUDE:
        cmd += ["--include", _TYPE_INCLUDE[type_filter]]
    cmd += ["--max-count", str(max_count), pattern, "."]
    r = _run(cmd)
    matches = []
    for line in (r.stdout or "").splitlines():
        if ":" in line:
            path, lineno, text = line.split(":", 2)
            matches.append({"file": path, "line": int(lineno), "text": text})
    out = {"pattern": pattern, "matches": matches}
    if r.returncode != 0 and r.returncode != 1:  # 1 = 无匹配，正常
        out["error"] = r.stderr.strip()
    return out


def query_history(target: str, max_count: int) -> dict:
    """git 历史：blame 单行 + log 该文件最近提交。target 形如 <file>:<line>。"""
    file_path, _, line_str = target.rpartition(":")
    if not file_path or not line_str.isdigit():
        return {"error": f"用法: --history <file>:<line>，收到 {target!r}"}
    line = int(line_str)
    blame = _run(["git", "-C", ".", "blame", "-L", f"{line},{line}", "--", file_path])
    log = _run(["git", "-C", ".", "log", "--oneline", "--max-count", str(max_count), "--", file_path])
    return {
        "target": target,
        "blame": blame.stdout.strip() if blame.returncode == 0 else f"<blame 失败: {blame.stderr.strip()}>",
        "commits": log.stdout.strip().splitlines() if log.returncode == 0 else [],
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ~/.dl-workflow && pytest tests/test_dl_codebase.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: commit**

```bash
cd ~/.dl-workflow
git add scripts/workflow/dl_codebase.py tests/test_dl_codebase.py
git commit -m "feat(codebase): --string grep 包装 + --history git 包装"
```

---

### Task 3: `main()` CLI + `dl-cmd.sh` 路由 + 端到端冒烟

**Files:**
- Modify: `scripts/workflow/dl_codebase.py`（补 `main`）
- Modify: `scripts/workflow/dl-cmd.sh`（加 `codebase` 早路由）
- Test: `tests/test_dl_codebase.py`

**Interfaces:**
- Consumes: `query_symbol/query_string/query_history`（Task 1/2）。
- Produces: `python3 dl_codebase.py query --symbol|--string|--history` 命令面；`dl-cmd.sh codebase query ...` 转发。

- [ ] **Step 1: 写失败测试**

```python
def test_main_symbol_json(capsys, monkeypatch):
    monkeypatch.setattr(cb, "query_symbol", lambda s: {"symbol": s, "definition": {}, "callers": {}, "impact": {}})
    rc = cb.main(["query", "--symbol", "foo"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["symbol"] == "foo"


def test_main_no_flag_returns_2(capsys):
    rc = cb.main(["query"])
    assert rc == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/.dl-workflow && pytest tests/test_dl_codebase.py -v`
Expected: FAIL（`NotImplementedError` in main）

- [ ] **Step 3: 实现 `main`**

```python
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="dl codebase", description="通用代码考古工具箱")
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("query", help="查符号/字符串/git 历史")
    q.add_argument("--symbol", help="符号名（codegraph query/callers/impact）")
    q.add_argument("--string", help="字符串/正则（grep -rn）")
    q.add_argument("--history", help="<file>:<line>（git blame + log）")
    q.add_argument("--type", help="grep --include 类型过滤（py/html/js/ts，仅 --string）")
    q.add_argument("--max-count", type=int, default=50)
    args = p.parse_args(argv)

    if args.symbol:
        out = query_symbol(args.symbol)
    elif args.string:
        out = query_string(args.string, args.type, args.max_count)
    elif args.history:
        out = query_history(args.history, args.max_count)
    else:
        print("✗ 需指定 --symbol / --string / --history 之一", file=sys.stderr)
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0
```

- [ ] **Step 4: 加 `dl-cmd.sh` 早路由（在 name 解析之前）**

在 `dl-cmd.sh` 中，把 `SUB="${1:-status}"` 之后、`NAME="$(resolve_name ...)"` 之前插入：

```bash
SUB="${1:-status}"
shift || true

# 通用工具（不依赖工作流 state）：codebase / list-tools 早路由
if [ "$SUB" = "codebase" ]; then
  exec python3 "$LIB_DIR/dl_codebase.py" "$@"
fi
```

> 注意：`dl_codebase.py` 与 `dl-cmd.sh` 同目录（`scripts/workflow/`），`$LIB_DIR` 已指向该目录。

- [ ] **Step 5: 跑测试 + 端到端冒烟**

Run:
```bash
cd ~/.dl-workflow && pytest tests/test_dl_codebase.py -v
# 端到端：在真实仓库上跑一次（期望返回 JSON，含 file:line）
cd /home/admin/projects/factor_ic_analyzer
~/.dl-workflow/scripts/workflow/dl-cmd.sh codebase query --symbol convert_return_to_percentage
```
Expected: 测试 PASS（6 passed）；冒烟输出 JSON，`definition.ok[0].node.filePath == "summary/report/formatters.py"` 且 `startLine == 107`。

- [ ] **Step 6: commit**

```bash
cd ~/.dl-workflow
git add scripts/workflow/dl_codebase.py scripts/workflow/dl-cmd.sh tests/test_dl_codebase.py
git commit -m "feat(codebase): main CLI + dl-cmd.sh codebase 路由"
```

---

### Task 4: `workflow-tools.yaml` 加载器（组件 B 发现）

**Files:**
- Create: `scripts/workflow/project_tools.py`
- Test: `tests/test_project_tools.py`

**Interfaces:**
- Produces: `load_project_tools(project_root: Path) -> list[dict]`（Task 5 注入用）；`PROJECT_TOOLS_FILENAME = "workflow-tools.yaml"`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_project_tools.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "workflow"))
import project_tools as pt  # noqa: E402


def test_missing_file_returns_empty(tmp_path):
    assert pt.load_project_tools(tmp_path) == []


def test_valid_file_parses(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "workflow-tools.yaml").write_text(
        "tools:\n"
        "  - name: inspect-backtest-result\n"
        "    command: scripts/inspect_backtest_result.py --factor {factor}\n"
        "    description: 读回测结果元数据\n"
        "    arg_hint: --factor <因子名>\n"
    )
    tools = pt.load_project_tools(tmp_path)
    assert len(tools) == 1
    assert tools[0]["name"] == "inspect-backtest-result"
    assert tools[0]["command"] == "scripts/inspect_backtest_result.py --factor {factor}"


def test_damaged_file_returns_empty(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "workflow-tools.yaml").write_text("tools: [unclosed")
    assert pt.load_project_tools(tmp_path) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/.dl-workflow && pytest tests/test_project_tools.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现加载器**

```python
# scripts/workflow/project_tools.py
"""组件 B：项目工具注册文件加载（发现层）。

注册文件 = <项目>/.claude/workflow-tools.yaml；缺失/损坏 = 无工具（零影响）。
"""
from __future__ import annotations

from pathlib import Path

PROJECT_TOOLS_FILENAME = "workflow-tools.yaml"
_KEYS = {"name", "command"}


def load_project_tools(project_root: Path) -> list[dict]:
    """读项目工具注册文件；任何异常都返回 []（宁纵勿枉，不阻断工作流）。"""
    path = project_root / ".claude" / PROJECT_TOOLS_FILENAME
    if not path.exists():
        return []
    try:
        import yaml  # 惰性导入：多数项目无工具，避免冷启动税

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("tools"), list):
        return []
    tools = []
    for t in data["tools"]:
        if not isinstance(t, dict) or not (_KEYS <= set(t)):
            continue
        tools.append(
            {
                "name": t["name"],
                "command": t["command"],
                "description": t.get("description", ""),
                "arg_hint": t.get("arg_hint", ""),
            }
        )
    return tools
```

> 依赖 `PyYAML`：先核实 `python3 -c "import yaml"` 可用（项目 venv 或系统）；不可用则在 Step 3 里把 `yaml` 换成 `json` 注册格式（`workflow-tools.json`）。**本计划默认 yaml 可用，若不可用当场切换 json 并同步改文件名。**

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ~/.dl-workflow && pytest tests/test_project_tools.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: commit**

```bash
cd ~/.dl-workflow
git add scripts/workflow/project_tools.py tests/test_project_tools.py
git commit -m "feat(codebase): workflow-tools.yaml 加载器（组件 B 发现）"
```

---

### Task 5: `ensure_node_rules` 注入「本项目工具」段

**Files:**
- Modify: `scripts/workflow/dl_drive.py`（`ensure_node_rules` 函数，约 245-271 行）
- Test: `tests/test_dl_drive.py`

**Interfaces:**
- Consumes: `project_tools.load_project_tools(project_root)`（Task 4）。
- Produces: node-rules 文件含「## 本项目工具」段；无工具时不含该段。

- [ ] **Step 1: 写失败测试（沿用 test_dl_drive 既有 fixture）**

在 `tests/test_dl_drive.py` 加（需先确认 fixture 名 `wf_repo` 提供 `project_root` + `name`；若无则用 `ensure_node_rules` 的既有测试用例模式）：

```python
def test_node_rules_injects_project_tools(wf_repo, monkeypatch):
    """注册工具后，node-rules 含「本项目工具」段；无工具则不含。"""
    from scripts.workflow import project_tools as pt  # noqa: E402
    monkeypatch.setattr(pt, "load_project_tools", lambda pr: [
        {"name": "inspect-backtest-result", "command": "scripts/inspect.py --factor {factor}", "description": "读回测", "arg_hint": "--factor <f>"}
    ])
    rules = ensure_node_rules(wf_repo, "t", engine.get_node("understand", 1))
    text = rules.read_text(encoding="utf-8")
    assert "## 本项目工具" in text
    assert "inspect-backtest-result" in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/.dl-workflow && pytest tests/test_dl_drive.py -k project_tools -v`
Expected: FAIL（node-rules 无「本项目工具」段）

- [ ] **Step 3: 实现注入**

在 `ensure_node_rules` 的 `text = (...)` 之后、写文件之前，追加：

```python
    tools = project_tools.load_project_tools(project_root)
    if tools:
        lines = ["## 本项目工具\n\n以下命令由项目注册（只读发现类），可直接用 Bash 调用：\n"]
        for t in tools:
            hint = f"（参数：{t['arg_hint']}）" if t.get("arg_hint") else ""
            lines.append(f"- `{t['command']}` {hint} — {t.get('description', '')}")
        text += "\n".join(lines) + "\n"
```

并在文件顶部 import 区加 `from scripts.workflow import project_tools`（或 `import project_tools`，按 dl_drive.py 既有 import 风格）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ~/.dl-workflow && pytest tests/test_dl_drive.py -k project_tools -v`
Expected: PASS

- [ ] **Step 5: commit**

```bash
cd ~/.dl-workflow
git add scripts/workflow/dl_drive.py tests/test_dl_drive.py
git commit -m "feat(codebase): ensure_node_rules 注入项目工具段（组件 B）"
```

---

### Task 6: 白名单并入 + `list-tools` + 集成测试

**Files:**
- Modify: `dl_flow_engine.py`（S15 白名单 + `list-tools` 子命令）
- Modify: `scripts/workflow/dl-cmd.sh`（`list-tools` 早路由）
- Test: `tests/test_dl_flow_engine.py`

**Interfaces:**
- Consumes: `project_tools.load_project_tools`（Task 4）。
- Produces: `dl-cmd.sh list-tools` 打印项目工具清单；项目工具 command 头进 S15 常驻集。

- [ ] **Step 1: 写失败测试**

```python
def test_project_tools_in_fence_allowlist(tmp_path):
    """注册工具 command 头进 S15 常驻集。"""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "workflow-tools.yaml").write_text(
        "tools:\n  - name: inspect\n    command: scripts/inspect.py --factor {factor}\n"
    )
    allowed = engine.fence_resident_commands(tmp_path)  # 新函数
    assert "scripts/inspect.py" in " ".join(allowed)
```

> 若 S15 常驻集当前是**静态常量**而非函数，则 Step 3 把它改成「静态集 + 动态并入项目工具 command 头」的函数，返回合并后的列表。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/.dl-workflow && pytest tests/test_dl_flow_engine.py -k project_tools -v`
Expected: FAIL（`fence_resident_commands` 不存在）

- [ ] **Step 3: 实现白名单并入 + `list-tools`**

在 `dl_flow_engine.py`：
1. 加 `from scripts.workflow import project_tools`（同 dl_drive 风格）。
2. 加函数：
```python
def fence_resident_commands(project_root: Path) -> list[str]:
    """S15 常驻命令 = 静态只读集 + 项目工具 command 头（只读发现类）。"""
    base = ["codegraph", "dl-cmd", "find", "ls", "grep", "cat", "head", "git"]
    for t in project_tools.load_project_tools(project_root):
        head = t["command"].strip().split()[0] if t["command"].strip() else ""
        if head and head not in base:
            base.append(head)
    return base
```
3. `main()` 的 `choices` 加 `"list-tools"`，`args.cmd == "list-tools"` 时打印：
```python
    if args.cmd == "list-tools":
        root = Path(args.cwd) if args.cwd else Path.cwd()
        tools = project_tools.load_project_tools(root)
        if not tools:
            print("（本项目无注册工具）")
        for t in tools:
            print(f"- {t['name']}: {t['command']} — {t.get('description','')}")
        return 0
```
4. `dl-cmd.sh` 早路由块加：
```bash
if [ "$SUB" = "list-tools" ]; then
  exec python3 "$WF_ENGINE" list-tools --cwd "$(git -C "$(pwd)" rev-parse --show-toplevel 2>/dev/null || pwd)"
fi
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ~/.dl-workflow && pytest tests/test_dl_flow_engine.py -k project_tools -v && pytest tests/test_dl_codebase.py tests/test_project_tools.py -v`
Expected: 全 PASS

- [ ] **Step 5: commit**

```bash
cd ~/.dl-workflow
git add dl_flow_engine.py scripts/workflow/dl-cmd.sh tests/test_dl_flow_engine.py
git commit -m "feat(codebase): 项目工具进 S15 白名单 + list-tools"
```

---

## Self-Review 记录

- **Spec 覆盖**：设计 doc §2（组件 A）→ Task 1-3；§3（组件 B）→ Task 4-6；§4 集成点（engine/dl-cmd/node-rules/S15/settings）→ 各 Task 对应 Files 列明；§5 测试 → 各 Task Step 1-4。
- **占位符扫描**：Task 4 有一个「yaml 若不可用切 json」的运行时决策——已写清触发条件和切换动作，非占位。
- **类型一致性**：`query_symbol/query_string/query_history` 签名在 Task 1/2 定义、Task 3 消费，一致；`load_project_tools(project_root) -> list[dict]` 在 Task 4 定义、Task 5/6 消费，一致。

> **遗留待实施时确认**：①`PyYAML` 是否在 dl-workflow 运行环境可用（不可用切 json 注册）；②`test_dl_drive.py` 的 `ensure_node_rules` 测试 fixture 实际签名（Task 5 Step 1 需对齐）；③S15 常驻集当前是静态常量还是函数（Task 6 Step 1 需对齐）。这三处均为「实施时读真实代码对齐」，不影响计划完整性。
