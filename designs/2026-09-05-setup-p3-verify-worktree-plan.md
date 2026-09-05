# dl setup P3-1/P3-2 Implementation Plan（自检自动化 + worktree inject 映射）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** P3-1 = `setup_project.py --verify` 等价自检（逐项 ✅ 清单，setup 装完即可机器核验「效果一样」）；P3-3-2 = inject hooks 的 `_project_root` 把 linked worktree 映射到主仓，让 dl 工作流会话也能拿到项目注入。

**Architecture:** verify 为 setup_project.py 内纯函数 `verify_project(project, home) -> list[tuple[str, bool, str]]` + `--verify` CLI（独立模式）+ 正常接线后自动 best-effort 复跑（非致命）。worktree 映射为两 hook 各自的 `_map_worktree_to_main(root, marker)`：git-dir ≠ git-common-dir 时取 common-dir 的 parent 为主仓根，仅当主仓存在对应 db 标记文件时替换——否则维持原 root（永不阻断语义不变）。

**Tech Stack:** Python 3.11 stdlib + PyYAML；pytest（subprocess/importlib 惯例）。

**Spec:** ~/.dl-workflow/designs/setup-installer-design.md §阶段3 等价自检 + 终审 observation（worktree 注入缺失，非回归）。

## Global Constraints

- hook 永不阻断语义不变：worktree 映射任何失败 → 维持原 root；映射仅「有 db 才替换」。
- verify 三态输出（✅/❌/⚠ 注记），退出码 0=全过 / 1=有 ❌；正常接线后的自动 verify 非致命。
- 单文件自足惯例不破坏：映射 helper 在两 hook 各放一份（同 _project_root 现状）。
- 测试 fixture 用 tmp git repo；worktree 映射测试用真实 `git worktree add`。
- 每 task 独立 commit；禁 git add -A。

---

### Task 1: verify_project——阶段3 等价自检自动化

**Files:**
- Modify: `scripts/setup/setup_project.py`
- Test: `tests/test_setup_project.py`（追加）

**Interfaces:**
- Consumes: 现有 main() argparse（加 --verify）
- Produces: `verify_project(project: Path, home: Path) -> list[tuple[str, bool, str]]`；`_verify_settings(project, home) -> tuple[bool, str]`；main() 增加 `--verify` 分支 + 正常模式尾部自动 verify（best-effort）。

- [ ] **Step 1: 追加失败测试**

```python
def _fake_home(tmp_path):
    home = tmp_path / "dlwf"
    (home / "hooks").mkdir(parents=True)
    for name in ("codegraph_inject.py", "conventions_inject.py"):
        (home / "hooks" / name).write_text(
            "import json,sys\n"
            "json.load(sys.stdin)\n"
            "print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit',"
            " 'additionalContext': 'stub'}}))\n")
    return home


def _fake_dbs(repo):
    import sqlite3

    (repo / ".conventions").mkdir(exist_ok=True)
    conn = sqlite3.connect(repo / ".conventions" / "conventions.db")
    conn.execute("CREATE TABLE conventions (id INTEGER)")
    conn.execute("INSERT INTO conventions VALUES (1)")
    conn.commit(); conn.close()
    (repo / ".codegraph").mkdir(exist_ok=True)
    conn = sqlite3.connect(repo / ".codegraph" / "codegraph.db")
    conn.execute("CREATE TABLE nodes (id TEXT)")
    conn.execute("INSERT INTO nodes VALUES ('n1')")
    conn.commit(); conn.close()


def test_verify_project_all_ok(tmp_path):
    sp = _load()
    repo = _git_repo(tmp_path)
    home = _fake_home(tmp_path)
    sp.patch_post_commit(repo, home)
    sp.merge_project_settings(repo, home)
    _fake_dbs(repo)
    checks = sp.verify_project(repo, home)
    assert all(ok for _, ok, _ in checks), checks
    names = [n for n, _, _ in checks]
    assert any("settings.json" in n for n in names)
    assert any("post-commit" in n for n in names)
    assert any("codegraph_inject" in n for n in names)
    assert any("conventions_inject" in n for n in names)


def test_verify_project_reports_failures(tmp_path):
    sp = _load()
    repo = _git_repo(tmp_path)
    home = _fake_home(tmp_path)
    # 什么都不接线 → 全部 ❌（6 项），不抛异常
    checks = sp.verify_project(repo, home)
    assert not any(ok for _, ok, _ in checks)
    assert len(checks) == 6


def test_main_verify_mode_exit_codes(tmp_path, capsys):
    sp = _load()
    repo = _git_repo(tmp_path)
    home = _fake_home(tmp_path)
    sp.patch_post_commit(repo, home)
    sp.merge_project_settings(repo, home)
    assert sp.main(["--project", str(repo), "--home", str(home), "--verify",
                    "--skip-index", "--skip-distill"]) == 0
    capsys.readouterr()
    assert sp.main(["--project", str(_git_repo(tmp_path / "other")), "--home", str(home),
                    "--verify", "--skip-index", "--skip-distill"]) == 1
    out = capsys.readouterr().out
    assert "❌" in out
```

- [ ] **Step 2: 确认失败** — `python3 -m pytest tests/test_setup_project.py -q` → 3 failed。

- [ ] **Step 3: 实现**

```python
import sqlite3  # 顶部 import 区

INJECT_HOOKS = ("codegraph_inject.py", "conventions_inject.py")


def _verify_settings(project: Path, home: Path) -> tuple[bool, str]:
    path = project / ".claude" / "settings.json"
    if not path.exists():
        return False, "settings.json 缺失"
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, "settings.json 非法 JSON"
    cmds = [h.get("command", "") for g in settings.get("hooks", {}).get("UserPromptSubmit", [])
            for h in g.get("hooks", [])]
    missing = [n for n in INJECT_HOOKS
               if not any(n in c and str(home) in c for c in cmds)]
    if missing:
        return False, f"缺注册或路径非 home: {missing}"
    return True, "两条 inject 注册指向 home"


def verify_project(project: Path, home: Path) -> list[tuple[str, bool, str]]:
    """阶段3 等价自检（designs/setup-installer-design.md）：逐项 ✅/❌，可机器核验「效果一样」。"""
    checks: list[tuple[str, bool, str]] = []
    ok, detail = _verify_settings(project, home)
    checks.append(("settings.json inject 注册", ok, detail))
    hook = project / ".git" / "hooks" / "post-commit"
    text = hook.read_text(encoding="utf-8", errors="replace") if hook.exists() else ""
    ok = "mine_conventions.py" in text and "codegraph sync" in text
    checks.append(("post-commit 双后台任务", ok, "ok" if ok else "缺 codegraph sync/mine_conventions"))
    payload = json.dumps({"prompt": "dl setup verify", "cwd": str(project)})
    for name in INJECT_HOOKS:
        proc = subprocess.run(
            ["python3", str(home / "hooks" / name)], input=payload,
            capture_output=True, text=True, cwd=project, timeout=15)
        if proc.returncode == 0:
            note = "有注入" if proc.stdout.strip() else "无注入（无漂移/无命中=可接受）"
            checks.append((f"inject 冒烟 {name}", True, note))
        else:
            checks.append((f"inject 冒烟 {name}", False, proc.stderr.strip()[:120]))
    db = project / ".conventions" / "conventions.db"
    if db.exists():
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            n = conn.execute("SELECT COUNT(*) FROM conventions").fetchone()[0]
            conn.close()
            checks.append(("conventions db 可读", True, f"{n} 条约定"))
        except sqlite3.Error as e:
            checks.append(("conventions db 可读", False, str(e)[:120]))
    else:
        checks.append(("conventions db 可读", False, "db 缺失"))
    cg = project / ".codegraph" / "codegraph.db"
    if cg.exists():
        try:
            conn = sqlite3.connect(f"file:{cg}?mode=ro", uri=True)
            n = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            conn.close()
            checks.append(("codegraph db 已索引", n > 0, f"{n} nodes"))
        except sqlite3.Error as e:
            checks.append(("codegraph db 已索引", False, str(e)[:120]))
    else:
        checks.append(("codegraph db 已索引", False, "db 缺失"))
    return checks


def _print_verify(checks: list[tuple[str, bool, str]]) -> int:
    print("▸ 等价自检（阶段3）")
    for name, ok, detail in checks:
        print(f"  {'✅' if ok else '❌'} {name} — {detail}")
    return 0 if all(ok for _, ok, _ in checks) else 1
```

main() 改动：argparse 加 `parser.add_argument("--verify", action="store_true")`；函数体开头：

```python
    if args.verify:
        return _print_verify(verify_project(project, args.home))
```
正常模式尾部（`═══ 完成` 打印前）插入 best-effort 复跑：

```python
    vrc = _print_verify(verify_project(project, args.home))
    if vrc != 0:
        print("  ⚠ 等价自检有 ❌（不阻断接线，见上方清单）")
```
（正常模式不因 verify 失败改退出码——接线已完成的既成事实；--verify 独立模式才严格退出码。）

- [ ] **Step 4: 跑测试** — `python3 -m pytest tests/test_setup_project.py -q` 全过（含既有）。

- [ ] **Step 5: Commit**

```bash
git add scripts/setup/setup_project.py tests/test_setup_project.py
git commit -m "feat(setup): --verify 等价自检——阶段3 清单机器化，装完即核验效果一样（P3-1）"
```

---

### Task 2: worktree → 主仓 inject 映射

**Files:**
- Modify: `hooks/codegraph_inject.py`、`hooks/conventions_inject.py`（各加 `_map_worktree_to_main`）
- Test: `tests/test_project_inject_hooks.py`（追加 2 条）

**Interfaces:**
- Consumes: 现有 `_project_root(payload)`
- Produces: `_project_root` 返回值对 linked worktree 可能映射为主仓根（仅当主仓存在本 hook 的 db 标记文件）；新 helper `_map_worktree_to_main(root: Path, marker: Path) -> Path | None`（两 hook 各一份）。codegraph_inject 的 marker=`.codegraph/codegraph.db`，conventions_inject 的 marker=`.conventions/conventions.db`。

- [ ] **Step 1: 追加失败测试**

```python
def test_project_root_maps_worktree_to_main(tmp_path):
    import subprocess as sp

    hooks = _load("cginject", "hooks/codegraph_inject.py")
    repo = _git_repo(tmp_path)
    _mk_codegraph_db(repo)                      # 主仓有 db
    wt = tmp_path / "wt"
    sp.run(["git", "worktree", "add", str(wt), "-b", "feat-x"], cwd=repo, check=True,
           capture_output=True)
    assert hooks._project_root({"cwd": str(wt)}) == repo


def test_project_root_keeps_worktree_without_main_db(tmp_path):
    import subprocess as sp

    hooks = _load("cvinject", "hooks/conventions_inject.py")
    repo = _git_repo(tmp_path)                   # 主仓无 .conventions db
    wt = tmp_path / "wt2"
    sp.run(["git", "worktree", "add", str(wt), "-b", "feat-y"], cwd=repo, check=True,
           capture_output=True)
    assert hooks._project_root({"cwd": str(wt)}) == Path(str(wt)).resolve()
```

- [ ] **Step 2: 确认失败** — 2 failed（当前实现返回 worktree 根）。

- [ ] **Step 3: 实现（两 hook 各一份，紧随 `_project_root` 之后）**

```python
def _map_worktree_to_main(root: Path, marker: Path) -> Path | None:
    """linked worktree → 主仓根：仅当主仓存在本 hook 的 db 标记时替换，否则 None（维持原 root）。

    判定：git-dir ≠ git-common-dir 即 linked worktree；主仓根 = common-dir 的 parent。
    任何失败（非 git/裸仓/命令缺失）返回 None——映射是增强，永不阻断。
    """
    try:
        run = subprocess.run(["git", "rev-parse", "--git-dir", "--git-common-dir"],
                             cwd=root, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if run.returncode != 0:
        return None
    lines = run.stdout.split()
    if len(lines) < 2:
        return None
    git_dir, common = Path(lines[0]), Path(lines[1])
    if not git_dir.is_absolute():
        git_dir = (root / git_dir).resolve()
    if not common.is_absolute():
        common = (root / common).resolve()
    if git_dir == common:
        return None  # 主工作树
    main_root = common.parent
    if (main_root / marker).exists():
        return main_root
    return None
```

`_project_root` 末尾 return 前替换：

```python
    mapped = _map_worktree_to_main(Path.cwd(), MARKER)
    return mapped if mapped else Path.cwd()
```
（三处候选统一收口：把每个候选解析出的 root 都过一遍映射——实现上可对最终选定的 root 做一次映射调用即可，因 worktree 场景 cwd 候选即命中。两 hook 各自 MARKER 常量：

```python
MARKER = Path(".codegraph") / "codegraph.db"        # codegraph_inject
MARKER = Path(".conventions") / "conventions.db"    # conventions_inject
```
注意 `_project_root` 现有结构是逐候选 return——把每个 `return Path(proc.stdout.strip())` 改为 `return _resolve(Path(proc.stdout.strip()))`，其中 `_resolve(r) = _map_worktree_to_main(r, MARKER) or r`；最终 `return _resolve(Path.cwd())`。）

- [ ] **Step 4: 跑测试** — `python3 -m pytest tests/test_project_inject_hooks.py -q` 全过（7 条）；`python3 -m pytest tests/ -q | tail -2` 全量绿。

- [ ] **Step 5: 真实 worktree 冒烟**

```bash
cd /home/admin/projects/factor_ic_analyzer
WT=$(mktemp -d)/wt && git worktree add "$WT" -b p3-smoke-$(date +%s) 2>&1 | tail -1
echo "{\"prompt\":\"drift\",\"cwd\":\"$WT\"}" | python3 ~/.dl-workflow/hooks/conventions_inject.py | head -c 200
git worktree remove "$WT" --force; git worktree prune; git branch -d $(git branch --list 'p3-smoke-*')
```
Expected: 冒烟输出含漂移注入文本（来自主仓 db）——这证明 dl 工作流会话（worktree）现在能拿到注入。

- [ ] **Step 6: Commit**

```bash
git add hooks/codegraph_inject.py hooks/conventions_inject.py tests/test_project_inject_hooks.py
git commit -m "feat(hooks): worktree→主仓 inject 映射——dl 工作流会话同享项目注入（P3-2，仅当有 db 才替换）"
```

---

## 验收

1. `--verify` 独立模式：tmp 全接线 repo → exit 0 + 全 ✅；裸 repo → exit 1 + ❌ 清单。
2. 正常接线后自动 verify 非致命（⚠ 提示不改退出码）。
3. worktree 映射：tmp 真实 worktree 双态测试过；factor 真实 worktree 冒烟有注入；主仓无 db 时维持 worktree 根。
4. `pytest tests/ -q` 全量绿。
