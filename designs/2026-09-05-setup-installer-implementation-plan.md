# dl setup 安装器 P1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** P1——安装器项目级模式（`install.sh --project`：codegraph init/post-commit/settings 接线/首蒸）+ 工具链三脚本 vendor 进 dl-workflow + inject hook 集中化（payload.cwd 解析项目根）。

**Architecture:** 机器级安装（既有 install.sh）保持不变；新增 `scripts/setup/setup_project.py`（可单测的 Python，bash 只做委托）处理项目接线四步；`bin/`（cgx/cvx/mine_conventions）与 `hooks/`（codegraph_inject/conventions_inject）集中入 dl-workflow 仓库，hook 用 `payload.cwd`→git rev-parse 解析项目根（同 codegraph_gate 既定模式），项目 settings.json 以绝对路径引用 `~/.dl-workflow/`。

**Tech Stack:** bash（install.sh 外壳）+ Python 3.11 stdlib（setup_project.py/hooks）+ pytest（subprocess/importlib 端到端风格，同 dl-workflow tests/ 惯例）。

**Spec:** designs/setup-installer-design.md（worktree 根）。P1 范围=设计 §分期 P1；⑦conventions.yaml 与 checker 参数化属 P2，本计划不做。

## Global Constraints

- dl-workflow 仓库纪律（CLAUDE.md）：hooks 不 copy 到 ~/.claude/，settings 直引 `~/.dl-workflow/hooks/` 源；install.sh 幂等（重跑结果一致）；可选层失败只警告不阻断核心。
- hook 项目根解析禁止 `__file__` parents——用 `payload["cwd"]` → `git rev-parse --show-toplevel` 反查（同 tests/test_codegraph_gate.py 模式）；UserPromptSubmit hook 永不阻断（exit 0 only，所有失败路径静默）。
- 测试风格：dl-workflow 惯例 = subprocess 端到端 或 importlib 按路径加载（不建包、不建 __init__.py）；fixture 用 tmp_path，不碰真实仓/真实 audit log。
- Vendor 的文件源自 factor_ic_analyzer 仓（路径见 Task 1），逻辑原样拷贝，只改导入机制与 usage 文案。
- 每个 task 独立 commit；commit message 末尾引用 designs/setup-installer-design.md。

---

### Task 1: vendor 工具链三脚本（bin/ + tests/ 导入改造）

**Files:**
- Create: `bin/cgx.py`、`bin/cvx.py`、`bin/mine_conventions.py`（copy from factor repo）
- Create: `tests/test_cgx.py`、`tests/test_cvx.py`、`tests/test_mine_conventions.py`（copy + 导入机制改造）

**Interfaces:**
- Consumes: 无
- Produces: `bin/cgx.py`（CLI callers|impact）、`bin/cvx.py`（CLI query|drift）、`bin/mine_conventions.py`（CLI 蒸馏器）——三者均为「项目根 cwd 运行」约定，db 默认相对路径 `.codegraph/codegraph.db` / `.conventions/conventions.db`；测试加载惯例 `_load(name, "bin/x.py")`（Task 2 的 hook 测试也复用）。

- [ ] **Step 1: 拷贝源文件**

```bash
SRC=/home/admin/projects/factor_ic_analyzer/scripts
DST=/home/admin/projects/dl-setup-installer
cp "$SRC/cgx.py" "$DST/bin/cgx.py"
cp "$SRC/cvx.py" "$DST/bin/cvx.py"
cp "$SRC/mine_conventions.py" "$DST/bin/mine_conventions.py"
cp "$SRC/test_cgx.py" "$DST/tests/test_cgx.py"
cp "$SRC/test_cvx.py" "$DST/tests/test_cvx.py"
cp "$SRC/test_mine_conventions.py" "$DST/tests/test_mine_conventions.py"
```

- [ ] **Step 2: 改三个脚本的 usage 文案**

把 `bin/cgx.py`、`bin/cvx.py`、`bin/mine_conventions.py` docstring/usage 里的 `python3 scripts/X.py` 替换为 `python3 ~/.dl-workflow/bin/X.py`（各 1-2 处，含 argparse description 与 module docstring 用法行）。逻辑零改动。

- [ ] **Step 3: 改造三个测试文件的导入机制**

factor 仓测试用 `from scripts.X import ...`——dl-workflow 无 scripts 包。每个测试文件头部改为 importlib 按路径加载。以 `tests/test_cvx.py` 为例，将原 import 块替换为：

```python
import importlib.util
import json
import sqlite3
from pathlib import Path


def _load(name, rel):
    path = Path(__file__).resolve().parents[1] / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cvx = _load("cvx", "bin/cvx.py")
```
然后把正文里所有直接使用导入名（`_format`、`_select`、`main`）的地方改为 `cvx._format` / `cvx._select` / `cvx.main`。**注意 `test_main_exit_codes` 里的 `capsys` 行为不变。**

`tests/test_cgx.py` 同理（`_load("cgx", "bin/cgx.py")`，别名 `cgx`），`tests/test_mine_conventions.py` 同理（`_load("mine_conventions", "bin/mine_conventions.py")`，别名 `mc`），其顶部 `import pytest` 保留；fixture/helper（`CG_SCHEMA`、`_fixture_cg`、`_record`、`_read_records`）原样保留。

- [ ] **Step 4: 跑测试验证**

```bash
cd /home/admin/projects/dl-setup-installer
python3 -m pytest tests/test_cvx.py tests/test_cgx.py tests/test_mine_conventions.py -q
```
Expected: 3 + 7 + 8 = 18 passed。若 import 改造漏改某个名字，逐个补齐。

- [ ] **Step 5: Commit**

```bash
git add bin/cgx.py bin/cvx.py bin/mine_conventions.py tests/test_cvx.py tests/test_cgx.py tests/test_mine_conventions.py
git commit -m "feat(bin): vendor cgx/cvx/mine_conventions 工具链——factor 仓平移，importlib 测试加载（designs/setup-installer-design.md §资产分布）"
```

---

### Task 2: inject hook 集中化（hooks/ + payload.cwd 项目根解析）

**Files:**
- Create: `hooks/codegraph_inject.py`、`hooks/conventions_inject.py`
- Create: `tests/test_project_inject_hooks.py`

**Interfaces:**
- Consumes: 无（factor 仓 `.claude/hooks/` 有同名文件为蓝本：`/home/admin/projects/factor_ic_analyzer/.claude/hooks/{codegraph_inject,conventions_inject}.py`）
- Produces: `_project_root(payload) -> Path`（两 hook 共用模式）；`hooks/codegraph_inject.py` 与 `hooks/conventions_inject.py`（项目 settings.json 将以绝对路径引用，Task 3 接线）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_project_inject_hooks.py
"""集中版 inject hooks 单元测试：payload.cwd 项目根解析 + 注入协议 + 永不阻断。

对应 designs/setup-installer-design.md。fixture=tmp git repo（.codegraph/.conventions db 手造），
hook 经 subprocess 喂 stdin payload（端到端，同 test_codegraph_gate.py 风格）。
"""

import importlib.util
import io
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / "hooks"


def _load(name, rel):
    path = Path(__file__).resolve().parents[1] / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git_repo(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "x.py").write_text("def foo():\n    pass\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


def _payload(repo, prompt="看下 foo"):
    return json.dumps({"prompt": prompt, "cwd": str(repo)})


def _run_hook(script, repo, payload):
    return subprocess.run(
        [sys.executable, str(HOOKS / script)],
        input=payload, capture_output=True, text=True, cwd=repo,
    )


def _mk_codegraph_db(repo):
    db = repo / ".codegraph" / "codegraph.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE files (path TEXT, indexed_at INTEGER)")
    conn.execute("CREATE TABLE nodes (name TEXT, kind TEXT, file_path TEXT, start_line INTEGER)")
    conn.execute("INSERT INTO files VALUES ('x.py', 1757059200000)")
    conn.execute("INSERT INTO nodes VALUES ('foo', 'function', 'x.py', 1)")
    conn.commit(); conn.close()


def _mk_conventions_db(repo, drift=1):
    db = repo / ".conventions" / "conventions.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE conventions (
          id INTEGER PRIMARY KEY, dimension TEXT NOT NULL, subject TEXT NOT NULL,
          statement TEXT NOT NULL, source TEXT NOT NULL, sample_size INTEGER NOT NULL,
          compliance REAL, drift INTEGER NOT NULL DEFAULT 0, evidence TEXT NOT NULL,
          generated_at TEXT NOT NULL, commit_hash TEXT);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        """
    )
    conn.execute(
        "INSERT INTO conventions (dimension, subject, statement, source, sample_size,"
        " compliance, drift, evidence, generated_at, commit_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("d3_style", "H11 日志风格", "f-string 1 处", "doc_declared", 942, 1.0, drift,
         "[]", "2026-09-05T00:00:00", "abc"),
    )
    conn.execute("INSERT INTO meta VALUES ('commit_hash', 'abc')")
    conn.commit(); conn.close()


def test_project_root_prefers_payload_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # 进程 cwd 与 payload cwd 不同
    hooks = _load("cginject", "hooks/codegraph_inject.py")
    repo = _git_repo(tmp_path)
    assert hooks._project_root({"cwd": str(repo)}) == repo


def test_codegraph_inject_uses_project_db(tmp_path):
    repo = _git_repo(tmp_path)
    _mk_codegraph_db(repo)
    proc = _run_hook("codegraph_inject.py", repo, _payload(repo, "foo 是谁"))
    assert proc.returncode == 0
    ctx = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "foo" in ctx and "x.py" in ctx


def test_conventions_inject_drifts_and_never_blocks(tmp_path):
    repo = _git_repo(tmp_path)
    _mk_conventions_db(repo, drift=1)
    proc = _run_hook("conventions_inject.py", repo, _payload(repo))
    assert proc.returncode == 0
    ctx = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "H11 日志风格" in ctx


def test_conventions_inject_silent_without_db(tmp_path):
    repo = _git_repo(tmp_path)
    proc = _run_hook("conventions_inject.py", repo, _payload(repo))
    assert proc.returncode == 0 and proc.stdout == ""


def test_conventions_inject_silent_on_bad_stdin(tmp_path):
    repo = _git_repo(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(HOOKS / "conventions_inject.py")],
        input="\x00\xff not json", capture_output=True, text=False, cwd=repo,
    )
    assert proc.returncode == 0
```

注意最后一条测试用 `text=False` 喂非 UTF-8 字节——这同时锁死「UnicodeDecodeError 也静默」的约束。

- [ ] **Step 2: 跑测试确认失败** — `python3 -m pytest tests/test_project_inject_hooks.py -q` → 5 failed（hook 文件不存在）。

- [ ] **Step 3: 实现两 hook**

以 factor 仓两文件为蓝本 **整体拷贝逻辑**（`/home/admin/projects/factor_ic_analyzer/.claude/hooks/codegraph_inject.py` 与 `conventions_inject.py`），做以下三处改造：

(a) 文件头 PROJECT_ROOT 常量删除，替换为共用解析函数（两文件各放一份，保持 hook 单文件自足——hook 被 settings 直接引用，不依赖包导入）：

```python
def _project_root(payload: dict) -> Path:
    """项目根解析：payload.cwd → CLAUDE_PROJECT_DIR → 进程 cwd，各自经 git rev-parse 反查。"""
    candidates = [payload.get("cwd"), os.environ.get("CLAUDE_PROJECT_DIR"), str(Path.cwd())]
    for cand in candidates:
        if not cand:
            continue
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=cand, capture_output=True, text=True,
            )
        except OSError:
            continue
        if proc.returncode == 0 and proc.stdout.strip():
            return Path(proc.stdout.strip())
    return Path.cwd()
```

(b) 所有 `PROJECT_ROOT / ...` 路径改为函数内 `root = _project_root(payload)` 后 `root / ...`（codegraph_inject 的 CODEGRAPH_DB/INJECT_LOG；conventions_inject 的 CONV_DB/INJECT_LOG）。payload 在 main() 开头解析一次往下传。

(c) factor 版 conventions_inject 的 stdin 异常捕获元组扩为 `except (json.JSONDecodeError, UnicodeDecodeError, OSError)`（终审修复项带入）；codegraph_inject 同理（若其捕获块不含 UnicodeDecodeError）。

`main()` 里 payload 解析失败时 payload 用 `{}` 继续（保持永不阻断：无 cwd 时落到进程 cwd / Path.cwd()）。

- [ ] **Step 4: 跑测试确认通过** — 5 passed。

- [ ] **Step 5: Commit**

```bash
git add hooks/codegraph_inject.py hooks/conventions_inject.py tests/test_project_inject_hooks.py
git commit -m "feat(hooks): inject hook 集中化——payload.cwd 解析项目根，仓内单文件自足（designs/setup-installer-design.md §资产分布）"
```

---

### Task 3: setup_project.py——项目接线四步（可单测）

**Files:**
- Create: `scripts/setup/setup_project.py`
- Create: `tests/test_setup_project.py`

**Interfaces:**
- Consumes: Task 1/2 产物路径约定（`bin/mine_conventions.py`、`.codegraph/codegraph.db`、`.conventions/conventions.db`）
- Produces: `setup_project.py` CLI：`python3 scripts/setup/setup_project.py --project DIR [--home DIR] [--skip-index] [--skip-distill]`；函数 `patch_post_commit(project) -> str`、`merge_project_settings(project, home) -> dict`、`ensure_codegraph_index(project) -> int`、`first_distill(project, home) -> int`（各返回状态文案）；退出码 0=全过 / 1=有硬失败。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_setup_project.py
"""setup_project.py 单元测试：post-commit 幂等补丁 / 项目 settings 合并 / 接线报告。

对应 designs/setup-installer-design.md §setup 脚本结构。fixture=tmp git repo + 假 home。
"""

import importlib.util
import json
import sqlite3
import subprocess
from pathlib import Path

import pytest


def _load():
    path = Path(__file__).resolve().parents[1] / "scripts" / "setup" / "setup_project.py"
    spec = importlib.util.spec_from_file_location("setup_project", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git_repo(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"], cwd=repo, check=True)
    return repo


def test_patch_post_commit_idempotent(tmp_path):
    sp = _load()
    repo = _git_repo(tmp_path)
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.write_text("#!/bin/sh\ncodegraph sync >/dev/null 2>&1 &\nexit 0\n")
    status = sp.patch_post_commit(repo)
    text = hook.read_text()
    assert "mine_conventions.py" in text and "codegraph sync" in text and status == "patched"
    status2 = sp.patch_post_commit(repo)
    assert text == hook.read_text() and status2 == "already-ok"


def test_patch_post_commit_creates_missing(tmp_path):
    sp = _load()
    repo = _git_repo(tmp_path)
    hook = repo / ".git" / "hooks" / "post-commit"
    if hook.exists():
        hook.unlink()
    assert sp.patch_post_commit(repo) == "created"
    assert "mine_conventions.py" in hook.read_text()


def test_merge_project_settings_appends_and_idempotent(tmp_path):
    sp = _load()
    repo = _git_repo(tmp_path)
    home = tmp_path / "dlwf"
    (home / "hooks").mkdir(parents=True)
    for name in ("codegraph_inject.py", "conventions_inject.py"):
        (home / "hooks" / name).write_text("# stub\n")
    before = sp.merge_project_settings(repo, home)
    settings = json.loads((repo / ".claude" / "settings.json").read_text())
    cmds = [h["command"] for g in settings["hooks"]["UserPromptSubmit"] for h in g["hooks"]]
    assert any("codegraph_inject.py" in c for c in cmds)
    assert any("conventions_inject.py" in c for c in cmds)
    assert all(str(home) in c for c in cmds)
    after = sp.merge_project_settings(repo, home)
    assert before["added"] == 2 and after["added"] == 0 and after["kept"] == 2


def test_merge_project_settings_preserves_existing(tmp_path):
    sp = _load()
    repo = _git_repo(tmp_path)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [
            {"type": "command", "command": "echo existing"}]}]}})
    )
    home = tmp_path / "dlwf"
    (home / "hooks").mkdir(parents=True)
    for name in ("codegraph_inject.py", "conventions_inject.py"):
        (home / "hooks" / name).write_text("# stub\n")
    sp.merge_project_settings(repo, home)
    settings = json.loads((repo / ".claude" / "settings.json").read_text())
    cmds = [h["command"] for g in settings["hooks"]["UserPromptSubmit"] for h in g["hooks"]]
    assert "echo existing" in cmds


def test_merge_project_settings_aborts_on_bad_json(tmp_path):
    sp = _load()
    repo = _git_repo(tmp_path)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text("{not json")
    home = tmp_path / "dlwf"
    (home / "hooks").mkdir(parents=True)
    with pytest.raises(SystemExit):
        sp.merge_project_settings(repo, home)
```

- [ ] **Step 2: 跑测试确认失败** — `python3 -m pytest tests/test_setup_project.py -q` → 5 failed（文件不存在）。

- [ ] **Step 3: 实现 setup_project.py**

```python
#!/usr/bin/env python3
"""setup_project - dl setup 项目级接线（designs/setup-installer-design.md §setup 脚本结构 P1）。

四步：④ codegraph init+首次 index ⑤ post-commit 幂等补丁 ⑥ 项目 settings.json 合并两条
UserPromptSubmit inject hook（绝对路径引用 ~/.dl-workflow/hooks/）⑦ 首次蒸馏（best-effort）。
每步打印 installed / already-ok / failed 三态；硬失败退出 1。

用法：python3 scripts/setup/setup_project.py --project DIR [--home DIR] [--skip-index] [--skip-distill]
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


POST_COMMIT_MARK = "mine_conventions.py"
POST_COMMIT_BLOCK = """#!/bin/sh
# Auto-sync codegraph + re-mine conventions after each commit (background, non-blocking)
codegraph sync >/dev/null 2>&1 &
python3 "$DLWF_HOME/bin/mine_conventions.py" >/dev/null 2>&1 &
exit 0
"""


def patch_post_commit(project: Path) -> str:
    """post-commit 补丁：无则建、缺 mine_conventions 行则整块替换、齐则跳过。返回三态。"""
    hook = project / ".git" / "hooks" / "post-commit"
    if hook.exists() and POST_COMMIT_MARK in hook.read_text(encoding="utf-8", errors="replace"):
        return "already-ok"
    hook.write_text(POST_COMMIT_BLOCK)
    hook.chmod(0o755)
    return "created" if not hook.exists() else "patched"


def merge_project_settings(project: Path, home: Path) -> dict:
    """项目 .claude/settings.json 幂等合并两条 inject hook（只增不删，按 command 判重）。

    JSON 损坏 -> SystemExit（硬失败，不擅自覆盖用户配置）。
    """
    settings_path = project / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"✗ {settings_path} 不是合法 JSON，abort（请人工处理后重跑）", file=sys.stderr)
            sys.exit(1)
    else:
        settings = {}
    cmds = [
        f'python3 "{home}/hooks/codegraph_inject.py"',
        f'python3 "{home}/hooks/conventions_inject.py"',
    ]
    hooks = settings.setdefault("hooks", {})
    groups = hooks.setdefault("UserPromptSubmit", [{"hooks": []}])
    existing = {h.get("command") for g in groups for h in g.get("hooks", [])}
    added = 0
    for cmd in cmds:
        if cmd not in existing:
            groups[0]["hooks"].append({"type": "command", "command": cmd})
            added += 1
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"added": added, "kept": len(cmds) - added}


def ensure_codegraph_index(project: Path) -> int:
    """codegraph init + index；CLI 缺失返回 1（警告层，不硬失败）。"""
    if not (project / ".git").exists():
        print("  ⚠ 非 git 仓库，跳过 codegraph index")
        return 1
    if subprocess.run(["codegraph", "--version"], capture_output=True).returncode != 0:
        print("  ⚠ codegraph CLI 不可用，跳过 index（H15 门禁不生效）")
        return 1
    db = project / ".codegraph" / "codegraph.db"
    if db.exists():
        print("  ↺ .codegraph/codegraph.db 已存在，跳过 index")
        return 0
    proc = subprocess.run(["codegraph", "init"], cwd=project, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"  ✗ codegraph init 失败: {proc.stderr.strip()}")
        return 1
    print("✓ codegraph index 完成")
    return 0


def first_distill(project: Path, home: Path) -> int:
    """首次蒸馏（best-effort：失败仅警告，不阻断）。"""
    script = home / "bin" / "mine_conventions.py"
    if not script.exists():
        print("  ⚠ 蒸馏器缺失，跳过")
        return 1
    proc = subprocess.run(
        ["python3", str(script), "--root", str(project), "--out", str(project / ".conventions" / "conventions.db")],
        cwd=project, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(f"  ⚠ 首次蒸馏失败: {proc.stderr.strip()[:200]}")
        return 1
    print(f"✓ 首次蒸馏完成（{proc.stdout.strip()}）")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="dl setup 项目级接线（designs/setup-installer-design.md）")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--home", type=Path, default=Path.home() / ".dl-workflow")
    parser.add_argument("--skip-index", action="store_true")
    parser.add_argument("--skip-distill", action="store_true")
    args = parser.parse_args(argv)
    project = args.project.resolve()

    print(f"═══ dl setup --project {project} ═══")
    fails = 0
    if not args.skip_index:
        fails += 1 if ensure_codegraph_index(project) == 1 and not (project / ".codegraph" / "codegraph.db").exists() else 0
    status = patch_post_commit(project)
    print(f"{'✓' if status != 'failed' else '✗'} post-commit: {status}")
    merged = merge_project_settings(project, args.home)
    print(f"✓ settings.json 合并: added={merged['added']} kept={merged['kept']}")
    if not args.skip_distill:
        first_distill(project, args.home)  # best-effort，不计 fails
    print("═══ 完成（⚠ 项不阻断，详见上方输出）═══")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
```

注意：`patch_post_commit` 里 `"created" if not hook.exists() else "patched"` 在 write 之后恒为 patched——按测试语义修正为：写之前记录 `existed = hook.exists()`，返回 `"patched" if existed else "created"`。

- [ ] **Step 4: 跑测试确认通过** — `python3 -m pytest tests/test_setup_project.py -q` → 5 passed。同时全量回归：`python3 -m pytest tests/test_project_inject_hooks.py tests/test_setup_project.py tests/test_cvx.py tests/test_cgx.py tests/test_mine_conventions.py -q` → 23 passed。

- [ ] **Step 5: Commit**

```bash
git add scripts/setup/setup_project.py tests/test_setup_project.py
git commit -m "feat(setup): setup_project.py 项目接线四步——index/post-commit/settings 合并/首蒸（可单测；designs/setup-installer-design.md §setup 脚本结构）"
```

---

### Task 4: install.sh --project 委托 + 自举验证（factor 仓拆装重建）

**Files:**
- Modify: `install.sh`（参数解析 + 委托段，~15 行）
- Modify: `README.md`（加 --project 用法段，~10 行）

**Interfaces:**
- Consumes: Task 3 的 `scripts/setup/setup_project.py` CLI
- Produces: `./install.sh --project [DIR]`（缺省 cwd）；机器级流程跑完后委托项目接线。

- [ ] **Step 1: install.sh 加 --project**

在参数解析 case 里加：

```bash
      --project) PROJECT_MODE=1 ;;
      --project=*) PROJECT_MODE=1; PROJECT_DIR="${arg#--project=}" ;;
```

文件头变量区加 `PROJECT_MODE=0` 和 `PROJECT_DIR=""`。usage() 加两行：

```
  --project[=DIR]   项目级接线：codegraph index + post-commit + settings 合并 + 首蒸
                    （在 DIR 或当前目录执行；机器级安装照常先跑）
```

main() 里 `self_check` 之后、`echo "═══ 完成 ═══"` 之前插入：

```bash
  if [ "$PROJECT_MODE" = "1" ]; then
    local pdir="${PROJECT_DIR:-$PWD}"
    echo
    echo "▸ 项目级接线: $pdir"
    python3 "$DL_HOME/scripts/setup/setup_project.py" --project "$pdir" || \
      echo "  ⚠ 项目接线有硬失败（见上方），机器级安装不受影响"
  fi
```

README「安装」节追加：

```markdown
### 项目级接线（可选）

\`\`\`bash
~/.dl-workflow/install.sh --project [项目目录]   # 缺省当前目录
\`\`\`

装齐项目侧 dl-workflow 依赖：codegraph 首次 index、post-commit 双后台任务
（codegraph sync + 约定蒸馏重挖）、项目 \`.claude/settings.json\` 注册两条
UserPromptSubmit 注入 hook（直引 \`~/.dl-workflow/hooks/\`，换机重跑本命令即重建）。
```

- [ ] **Step 2: bash 语法检查 + 全量测试**

```bash
bash -n install.sh
cd /home/admin/projects/dl-setup-installer && python3 -m pytest tests/ -q
```
Expected: bash -n 无输出；pytest 全绿（含本计划新增 23 条 + 既有套件）。

- [ ] **Step 3: Commit**

```bash
git add install.sh README.md
git commit -m "feat(install): --project 项目级接线入口——机器级装完委托 setup_project.py（designs/setup-installer-design.md §setup 脚本结构）"
```

- [ ] **Step 4: 自举验证（factor_ic_analyzer 拆装重建）**

先备份：

```bash
cp /home/admin/projects/factor_ic_analyzer/.claude/settings.json /tmp/fac_settings_backup.json
cp /home/admin/projects/factor_ic_analyzer/.git/hooks/post-commit /tmp/fac_postcommit_backup
```

记录基线并拆手工接线（精确只删两条 inject 注册，其余保留）：

```bash
cd /home/admin/projects/factor_ic_analyzer
python3 scripts/cvx.py drift | tee /tmp/baseline_drift.txt
python3 - <<'PY'
import json
p = ".claude/settings.json"
s = json.load(open(p))
DROP = ("codegraph_inject.py", "conventions_inject.py")
for g in s["hooks"]["UserPromptSubmit"]:
    g["hooks"] = [h for h in g["hooks"] if not any(d in h.get("command", "") for d in DROP)]
s["hooks"]["UserPromptSubmit"] = [g for g in s["hooks"]["UserPromptSubmit"] if g["hooks"]]
json.dump(s, open(p, "w"), ensure_ascii=False, indent=2)
PY
printf '#!/bin/sh\ncodegraph sync >/dev/null 2>&1 &\nexit 0\n' > .git/hooks/post-commit
```

跑集中版接线并验等价：

```bash
python3 /home/admin/projects/dl-setup-installer/scripts/setup/setup_project.py \
  --project /home/admin/projects/factor_ic_analyzer \
  --home /home/admin/projects/dl-setup-installer --skip-index
echo '{"prompt":"foo","cwd":"/home/admin/projects/factor_ic_analyzer"}' | \
  python3 /home/admin/projects/dl-setup-installer/hooks/conventions_inject.py   # 期望：漂移注入 JSON
python3 /home/admin/projects/dl-setup-installer/bin/cvx.py \
  --db /home/admin/projects/factor_ic_analyzer/.conventions/conventions.db drift
diff <(grep -oE 'H[0-9]+ [^|]+' /tmp/baseline_drift.txt) \
     <(python3 scripts/cvx.py drift | grep -oE 'H[0-9]+ [^|]+')   # subject 级一致即过
```

注意接线用的是 `--home <worktree>`（集中版脚本在 worktree 里）；验证后 factor 仓 settings.json 里的注册指向 worktree 路径，收口 merge 回 main 后应重跑一次本命令把 `--home` 换回 `~/.dl-workflow`（写入 Task 5 收口步骤，见下）。

---

## 验收（对应 design §验收 P1 部分）

1. Task 4 Step 2 全量 pytest 绿 + `bash -n install.sh` 通过。
2. 幂等冒烟：`python3 scripts/setup/setup_project.py --project <tmp repo> --home <worktree> --skip-index` 连跑两次，第二次 post-commit=`already-ok`、settings `added=0`（test_setup_project 已覆盖）。
3. 自举：Task 4 Step 4 的 drift subject 级等价（H7/H11 在列，数字与基一致或差异有解释——如本仓自装后新增 bin/ 文件导致 n 变化属预期）。
