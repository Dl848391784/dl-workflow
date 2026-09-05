# dl setup P2（蒸馏层通用化）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** P2——`bin/mine_conventions.py` 从 factor 硬编码版重构为 checker 类型库（规则从项目 `conventions.yaml` 读取）；`setup_project.py` 缺 yaml 时自动生成模板；factor 仓迁移（写 yaml + 副本退役 + 等价验证）。

**Architecture:** 单文件工具惯例不变（bin/mine_conventions.py 自足）。新增 `load_rules(root)`（PyYAML safe_load，无文件/空 rules → 兜底跑 import 图纯事实）+ `CHECKERS` 注册表（6 类型，统一签名 `check(rule, ctx) -> list[dict]`）；旧 `mine_*` 五函数与 DIMENSIONS 退役。source 语义：path_literal_scan/logging_style/layering=doc_declared（违规→drift=1）；skeleton/util_graph/exit_codes=code_evidence。「不裁决只呈证」保留。

**Tech Stack:** Python 3.11 + PyYAML（新增依赖，install.sh pip 层）；pytest。

**Spec:** ~/.dl-workflow/designs/setup-installer-design.md §conventions.yaml schema + §分期 P2。设计类型表为 4+util_graph，本计划增 `exit_codes` 类型（factor 的 H12 直方图平移需要）——设计小扩展，已记录。

## Global Constraints

- 记录 dict 八字段契约不变：dimension/subject/statement/source/sample_size/compliance/drift/evidence；dimension=rule type，subject=rule id。
- 单文件自足惯例：不建包；测试用 importlib `_load` 惯例（同 P1）。
- 无 yaml / 空 rules → 只跑 import 图纯事实（layering checker 空 forbidden 路径），不静默：stderr 注明降级。
- 未知 type / yaml 解析失败 → stderr 警告并跳过该 rule（不静默、不阻断其他 rule）。
- no silent fallback 铁律：checker 缺 codegraph db 时返回 [] 并 stderr 注明。
- PyYAML 缺失 → load_rules 抛 SystemExit 明确报错（硬依赖，setup 负责装）。
- 每 task 独立 commit；git add 精确，禁 -A。

---

### Task 1: load_rules + CHECKERS 注册表 + main 改造 + install.sh pyyaml 层

**Files:**
- Modify: `bin/mine_conventions.py`（追加 load_rules/TEMPLATE/CHECKERS/main 改造）
- Modify: `install.sh`（pyyaml 可选层）
- Test: `tests/test_mine_conventions.py`（追加 load_rules 测试；旧 mine_* 测试本 task 不动）

**Interfaces:**
- Consumes: 旧 mine_* 函数（本 task 保留不动，Task 2 退役）
- Produces: `load_rules(root: Path) -> list[dict]`、`CHECKERS: dict[str, callable]`、`RULES_FILE = "conventions.yaml"`、`check(rule, ctx)` 统一签名约定 `fn(rule: dict, ctx: dict) -> list[dict]`（ctx = {"cg": sqlite3.Connection|None, "root": Path, "files": list[str]}）；`main` 改为 rules 驱动。

- [ ] **Step 1: 追加失败测试**

在 tests/test_mine_conventions.py 末尾追加（顶部已 import yaml? 没有则加 `import yaml`）：

```python
def test_load_rules_parses_and_validates(tmp_path, capsys):
    import yaml as _yaml

    root = tmp_path / "proj"
    root.mkdir()
    rules = [{"id": "r1", "type": "layering", "statement": "s", "params": {"forbidden": []}},
             {"id": "r2", "type": "unknown_type", "params": {}},
             {"id": "r3"}]  # 缺 type
    (root / "conventions.yaml").write_text(_yaml.safe_dump({"rules": rules}), encoding="utf-8")
    got = mc.load_rules(root)
    assert [r["id"] for r in got] == ["r1"]
    err = capsys.readouterr().err
    assert "unknown_type" in err and "r3" in err


def test_load_rules_empty_and_missing(tmp_path):
    assert mc.load_rules(tmp_path / "nope") == []
    root = tmp_path / "p2"
    root.mkdir()
    (root / "conventions.yaml").write_text("rules: []\n", encoding="utf-8")
    assert mc.load_rules(root) == []


def test_load_rules_bad_yaml_aborts(tmp_path):
    root = tmp_path / "p3"
    root.mkdir()
    (root / "conventions.yaml").write_text("rules: [unclosed", encoding="utf-8")
    with pytest.raises(SystemExit):
        mc.load_rules(root)


def _git_repo(tmp_path):
    import subprocess

    repo = tmp_path / "p4"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"], cwd=repo, check=True)
    return repo


def test_main_dispatches_registered_checker(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path)
    (repo / "conventions.yaml").write_text(
        "rules:\n  - id: stub\n    type: stub_type\n    params: {}\n", encoding="utf-8")

    def stub_check(rule, ctx):
        return [_record(subject=rule["id"])]

    monkeypatch.setitem(mc.CHECKERS, "stub_type", stub_check)
    out = tmp_path / "out.db"
    # 无 codegraph db → 软降级 cg=None（P2 行为），stub checker 不依赖 cg
    assert mc.main(["--root", str(repo), "--out", str(out)]) == 0
    rows = sqlite3.connect(f"file:{out}?mode=ro", uri=True).execute(
        "SELECT subject FROM conventions").fetchall()
    assert rows == [("stub",)]
```

- [ ] **Step 2: 跑测试确认失败** — `cd /home/admin/projects/dl-p2-generalize && python3 -m pytest tests/test_mine_conventions.py -q` → 新 4 条 failed（load_rules 不存在）。

- [ ] **Step 3: 实现（追加到 bin/mine_conventions.py）**

```python
# ---------- 规则驱动（P2 通用化，designs/setup-installer-design.md §conventions.yaml） ----------
RULES_FILE = "conventions.yaml"

# 规则类型注册表：fn(rule, ctx) -> list[dict]；ctx = {"cg", "root", "files"}
CHECKERS: dict = {}


def load_rules(root: Path) -> list[dict]:
    """读 <root>/conventions.yaml；无文件/空 rules → []（调用方降级纯事实）。

    未知 type / 缺 type 的 rule → stderr 警告并跳过（不静默不阻断）。
    PyYAML 缺失或文件解析失败 → SystemExit（硬依赖/硬失败，不静默兜底）。
    """
    try:
        import yaml
    except ImportError:
        print("mine_conventions: 缺 PyYAML（pip install --user pyyaml）", file=sys.stderr)
        sys.exit(1)
    path = root / RULES_FILE
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        print(f"mine_conventions: {RULES_FILE} 解析失败: {e}", file=sys.stderr)
        sys.exit(1)
    rules = (data or {}).get("rules") or []
    valid = []
    for r in rules:
        rtype = r.get("type") if isinstance(r, dict) else None
        if not rtype or rtype not in CHECKERS:
            print(f"mine_conventions: 跳过未知/缺 type 的 rule: {r!r:.120}", file=sys.stderr)
            continue
        valid.append(r)
    return valid


def _run_rules(cg, root, files) -> list[dict]:
    rules = load_rules(root)
    if not rules:
        print("mine_conventions: 无 conventions.yaml/rules，降级为 import 图纯事实", file=sys.stderr)
        rules = [{"id": "import_graph", "type": "layering", "statement": "模块 import 方向（纯事实）",
                  "params": {"forbidden": []}}]
    ctx = {"cg": cg, "root": root, "files": files}
    records = []
    for rule in rules:
        records.extend(CHECKERS[rule["type"]](rule, ctx))
    return records
```

main() 里做两处软降级改造（P2 通用化需要：蒸馏器须能在无 codegraph/非 git 的项目上跑）+ 规则驱动替换：

```python
    try:
        cg = _open_codegraph(args.codegraph_db)
    except (FileNotFoundError, sqlite3.OperationalError):
        print("mine_conventions: codegraph db 缺失，需 db 的 checker 将跳过（stderr 注明）", file=sys.stderr)
        cg = None
    try:
        records = _run_rules(cg, args.root, files)  # 见下
    except (sqlite3.Error, OSError) as e:
        print(f"mine_conventions: 蒸馏失败: {e}", file=sys.stderr)
        return 1
```
其中 `files`/`commit_hash` 获取也软降级：

```python
    try:
        files = _git_tracked_py(args.root)
        commit_hash = _git(args.root, "rev-parse", "HEAD")
    except subprocess.CalledProcessError:
        print("mine_conventions: 非 git 仓库，files 为空（纯 db 维度仍运行）", file=sys.stderr)
        files, commit_hash = [], ""
```
（`finally: cg.close()` 需改为 `if cg: cg.close()` 等价处理。）`for fn in DIMENSIONS ...` 替换为 `records = _run_rules(cg, args.root, files)`（DIMENSIONS 与旧 mine_* 保留至 Task 2 删除）。docstring 补注软降级语义；原「db 缺失 exit 1」契约改为警告（cgx 查询工具仍保持硬失败，蒸馏器不同）。

install.sh：新增可选层（仿 install_html_deps 模式）——

```bash
SKIP_DISTILLER=0
# usage 加：  --skip-distiller   不装 pyyaml（约定蒸馏不可用，核心工作流不受影响）
install_distiller_deps() {
  if [ "$SKIP_DISTILLER" = "1" ]; then
    echo "▸ 跳过蒸馏器依赖（--skip-distiller）"
    return 0
  fi
  echo "▸ 检查蒸馏器依赖（pyyaml）"
  if python3 -c "import yaml" 2>/dev/null; then
    echo "  ↺ pyyaml 已可 import，跳过"
    return 0
  fi
  local rc=0
  _pip_install_user pyyaml || rc=$?
  if [ "$rc" = 0 ]; then
    echo "✓ pip --user 安装 pyyaml 完成"
  else
    echo "  ⚠ pyyaml 未装——约定蒸馏不可用，核心工作流不受影响" >&2
    WARNINGS+=("distiller: pyyaml 未装")
  fi
}
```
main() 在 install_html_deps 后调用；参数解析 case 加 `--skip-distiller)`；self_check 加 `_ck "蒸馏器依赖（pyyaml）" python3 -c "import yaml"`（条件于 SKIP_DISTILLER）。

- [ ] **Step 4: 跑测试** — `python3 -m pytest tests/test_mine_conventions.py -q` → 全过（旧 8 + 新 4）；`bash -n install.sh`。

- [ ] **Step 5: Commit**

```bash
git add bin/mine_conventions.py install.sh tests/test_mine_conventions.py
git commit -m "feat(distiller): load_rules+CHECKERS 注册表+main 规则驱动——yaml 缺失降级纯事实（P2 通用化 Task 1）"
```

---

### Task 2: 六 checker 参数化实现 + 旧 mine_* 退役 + 测试重写

**Files:**
- Modify: `bin/mine_conventions.py`（删旧 mine_*/DIMENSIONS，实现六 checker）
- Modify: `tests/test_mine_conventions.py`（旧 4 条维度测试重写为 checker 测试）

**Interfaces:**
- Consumes: Task 1 的 CHECKERS/load_rules/ctx 约定；旧 mine_* 逻辑为蓝本（本 task 从其改写）
- Produces: 六 checker 注册进 CHECKERS：`path_literal_scan`/`logging_style`/`layering`/`skeleton`/`util_graph`/`exit_codes`。

- [ ] **Step 1: 重写旧维度测试为 checker 测试**（TDD RED——checker 未注册，main/dispatch 路径报未知 type）

把 test_d1_shared_utils / test_d1_path_literals(_clean) / test_d2_layering / test_d3_style / test_d4_skeleton 五条重写为直接调 checker 的形式（fixture 不变），示例：

```python
def _ctx(cg, root, files):
    return {"cg": cg, "root": root, "files": files}


def test_util_graph_checker(tmp_path):
    cg = _fixture_cg(tmp_path)
    rule = {"id": "util_graph", "type": "util_graph", "params": {"target_files": ["paths.py"]}}
    recs = mc.CHECKERS["util_graph"](rule, _ctx(cg, tmp_path, []))
    by_subject = {r["subject"]: r for r in recs}
    assert set(by_subject) == {"paths.DATA_DIR", "paths.PROJECT_ROOT"}
    assert by_subject["paths.DATA_DIR"]["sample_size"] == 3
    assert by_subject["paths.DATA_DIR"]["source"] == "code_evidence" and by_subject["paths.DATA_DIR"]["drift"] == 0


def test_path_literal_checker(tmp_path):
    (tmp_path / "a.py").write_text("from paths import DATA_DIR\n")
    (tmp_path / "b.py").write_text("LOG = '/home/admin/logs/x.log'\n")
    (tmp_path / "paths.py").write_text("ROOT = '/home/admin/projects'\n")
    rule = {"id": "H7", "type": "path_literal_scan", "statement": "路径只能 from paths import",
            "params": {"exempt_files": ["paths.py"], "preset": "abs_unix_path"}}
    recs = mc.CHECKERS["path_literal_scan"](rule, _ctx(None, tmp_path, ["a.py", "b.py", "paths.py"]))
    assert len(recs) == 1 and recs[0]["drift"] == 1 and recs[0]["source"] == "doc_declared"
    assert recs[0]["evidence"] == [{"file": "b.py", "line": 1}] and recs[0]["sample_size"] == 3
    rule2 = dict(rule, params={"exempt_files": [], "preset": "abs_unix_path"})
    recs2 = mc.CHECKERS["path_literal_scan"](rule2, _ctx(None, tmp_path, ["paths.py"]))
    assert recs2[0]["drift"] == 1  # 不豁免 paths.py


def test_logging_style_checker(tmp_path):
    (tmp_path / "x.py").write_text(
        'logger.info("loaded %s rows", n)\nlogger.info(f"done {n}")\nlogger.error("fail %s", e)\n')
    rule = {"id": "H11", "type": "logging_style", "statement": "日志 % 惰性禁 f-string",
            "params": {"fstring_regex": mc.FSTRING_LOG_RE.pattern, "lazy_regex": mc.LAZY_LOG_RE.pattern}}
    recs = mc.CHECKERS["logging_style"](rule, _ctx(None, tmp_path, ["x.py"]))
    assert len(recs) == 1 and recs[0]["drift"] == 1 and recs[0]["source"] == "doc_declared"
    assert recs[0]["sample_size"] == 3 and recs[0]["compliance"] == pytest.approx(2 / 3)
    assert recs[0]["evidence"] == [{"file": "x.py", "line": 2}]


def test_layering_checker_facts_and_doc(tmp_path):
    conn = sqlite3.connect(tmp_path / "cg.db")
    conn.executescript(CG_SCHEMA)
    conn.executemany("INSERT INTO nodes VALUES (?,?,?,?,?)", [
        ("a", "function", "f1", "web_ui/app.py", 1),
        ("b", "function", "f2", "factor_ic/calc.py", 1),
        ("c", "function", "f3", "web_ui/page.py", 1),
        ("d", "function", "f4", "web_ui/helper.py", 1),
        ("e", "function", "f5", "backtest/engine.py", 1),
    ])
    conn.executemany("INSERT INTO edges (source, target, kind, line) VALUES (?,?,?,?)", [
        ("a", "b", "imports", 2), ("c", "b", "imports", 2), ("e", "d", "imports", 2)])
    conn.commit()
    rule = {"id": "H1", "type": "layering", "statement": "模块边界：web_ui 只读后端",
            "params": {"forbidden": [{"from": "*", "to": "web_ui"}]}}
    recs = mc.CHECKERS["layering"](rule, _ctx(conn, tmp_path, []))
    facts = [r for r in recs if r["source"] == "code_evidence"]
    doc = [r for r in recs if r["source"] == "doc_declared"]
    pair = {r["subject"]: r for r in facts}
    assert pair["web_ui->factor_ic"]["sample_size"] == 2
    assert len(doc) == 1 and doc[0]["drift"] == 1
    assert doc[0]["evidence"] == [{"file": "backtest/engine.py", "line": 2}]
    # 空 forbidden → 纯事实，无 doc 记录
    rule2 = {"id": "import_graph", "type": "layering", "params": {"forbidden": []}}
    recs2 = mc.CHECKERS["layering"](rule2, _ctx(conn, tmp_path, []))
    assert all(r["source"] == "code_evidence" for r in recs2)


def test_skeleton_and_exit_codes_checkers(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "a.py").write_text(
        'import argparse\nfrom paths import DATA_DIR\ndef main():\n    pass\n'
        'if __name__ == "__main__":\n    main()\n')
    (tmp_path / "scripts" / "b.py").write_text("print('hi')\n")
    (tmp_path / "scripts" / "s1.py").write_text("import sys\nsys.exit(0)\n")
    files = ["scripts/a.py", "scripts/b.py", "scripts/s1.py"]
    sk = {"id": "skel", "type": "skeleton",
          "params": {"glob": "scripts/*.py", "exclude_name_prefix": ["test_"],
                     "traits": {"argparse": "import argparse", "main": "def main("}}}
    recs = mc.CHECKERS["skeleton"](sk, _ctx(None, tmp_path, files))
    by = {r["subject"]: r for r in recs}
    # 样本=a.py+b.py+s1.py 共 3 个；仅 a.py 含 argparse/main
    assert by["skel:argparse"]["sample_size"] == 3 and by["skel:argparse"]["compliance"] == pytest.approx(1 / 3)
    assert by["skel:main"]["compliance"] == pytest.approx(1 / 3)
    ec = {"id": "ec", "type": "exit_codes", "params": {"glob": "scripts/*.py"}}
    recs2 = mc.CHECKERS["exit_codes"](ec, _ctx(None, tmp_path, files))
    assert recs2[0]["source"] == "code_evidence" and "0×1" in recs2[0]["statement"]
```

同时追加一条注册完整性测试：

```python
def test_all_six_checkers_registered():
    assert set(mc.CHECKERS) == {"path_literal_scan", "logging_style", "layering", "skeleton", "util_graph", "exit_codes"}
```

- [ ] **Step 2: 跑测试确认失败** — 新测试 failed（CHECKERS 缺这些 key）。

- [ ] **Step 3: 实现六 checker（删除旧 mine_*/DIMENSIONS，正则与 helper 保留）**

以旧 mine_* 函数体为蓝本改写，统一签名 `check(rule, ctx)`；正则/helper（`FSTRING_LOG_RE`/`LAZY_LOG_RE`/`SYS_EXIT_RE`/`RETURN_CODE_RE`/`ABS_PATH_RE`/`_top_module`/`EVIDENCE_CAP`）原样保留。骨架：

```python
_PRESET_PATH_RES = {"abs_unix_path": re.compile(r"""["'](/(?:home|data|mnt|opt|srv)/)"""),
                    "abs_win_path": re.compile(r"""[A-Za-z]:\\\\""")}


def _glob_match(files, glob, exclude_prefix=()):
    from pathlib import PurePath
    return [f for f in files
            if PurePath(f).match(glob) and not PurePath(f).name.startswith(exclude_prefix)]


def check_path_literal(rule, ctx):
    params = rule.get("params") or {}
    pat = params.get("regex") and re.compile(params["regex"]) or _PRESET_PATH_RES[params.get("preset", "abs_unix_path")]
    exempt = set(params.get("exempt_files") or [])
    violations, scanned = [], 0
    for rel in ctx["files"]:
        if rel in exempt:
            continue
        scanned += 1
        try:
            text = (ctx["root"] / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if pat.search(line):
                violations.append({"file": rel, "line": i})
                break
    clean = scanned - len(violations)
    return [{
        "dimension": "path_literal_scan", "subject": rule["id"],
        "statement": f"{rule.get('statement', '')}；实证 {scanned} 个 .py 中 {len(violations)} 个违规（合规率 {clean / max(scanned, 1):.2f}）",
        "source": "doc_declared", "sample_size": scanned,
        "compliance": clean / max(scanned, 1), "drift": 1 if violations else 0,
        "evidence": violations[:EVIDENCE_CAP],
    }]


def check_logging_style(rule, ctx):
    params = rule.get("params") or {}
    f_re = re.compile(params["fstring_regex"])
    l_re = re.compile(params["lazy_regex"])
    hits, lazy = [], 0
    for rel in ctx["files"]:
        try:
            lines = (ctx["root"] / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if f_re.search(line):
                hits.append({"file": rel, "line": i})
            elif l_re.search(line):
                lazy += 1
    denom = len(hits) + lazy
    return [{
        "dimension": "logging_style", "subject": rule["id"],
        "statement": f"{rule.get('statement', '')}；实证 f-string {len(hits)} 处、惰性 {lazy} 处",
        "source": "doc_declared", "sample_size": denom,
        "compliance": (lazy / denom) if denom else None, "drift": 1 if hits else 0,
        "evidence": hits[:EVIDENCE_CAP],
    }]


def check_layering(rule, ctx):
    cg = ctx["cg"]
    if cg is None:
        print("mine_conventions: layering/util_graph 需 codegraph db，跳过", file=sys.stderr)
        return []
    forbidden = (rule.get("params") or {}).get("forbidden") or []
    rows = cg.execute(
        "SELECT n1.file_path, n2.file_path, e.line FROM edges e"
        " JOIN nodes n1 ON n1.id = e.source JOIN nodes n2 ON n2.id = e.target"
        " WHERE e.kind = 'imports'").fetchall()
    pairs, violations = {}, []
    for src_fp, dst_fp, line in rows:
        s, d = _top_module(src_fp), _top_module(dst_fp)
        if s == d:
            continue
        pairs[(s, d)] = pairs.get((s, d), 0) + 1
        for f in forbidden:
            if d == f.get("to") and (f.get("from") in ("*", s)):
                violations.append({"file": src_fp, "line": line})
    records = [{
        "dimension": "layering", "subject": f"{s}->{d}", "statement": f"{s} import {d}：{c} 处",
        "source": "code_evidence", "sample_size": c, "compliance": None, "drift": 0, "evidence": [],
    } for (s, d), c in sorted(pairs.items(), key=lambda kv: -kv[1])]
    if forbidden:
        records.append({
            "dimension": "layering", "subject": rule["id"],
            "statement": f"{rule.get('statement', '')}；实证违规 {len(violations)} 处",
            "source": "doc_declared", "sample_size": sum(pairs.values()),
            "compliance": 1.0 if not violations else None,
            "drift": 1 if violations else 0, "evidence": violations[:EVIDENCE_CAP],
        })
    return records


def check_util_graph(rule, ctx):
    cg = ctx["cg"]
    if cg is None:
        print("mine_conventions: util_graph 需 codegraph db，跳过", file=sys.stderr)
        return []
    records = []
    for target in (rule.get("params") or {}).get("target_files") or []:
        symbols = cg.execute(
            "SELECT id, name FROM nodes WHERE file_path = ? AND kind != 'import'", (target,)).fetchall()
        for sid, name in symbols:
            rows = cg.execute(
                "SELECT n.file_path, e.line, n.kind FROM edges e JOIN nodes n ON n.id = e.source"
                " WHERE e.target = ? AND e.kind IN ('calls','references','imports')", (sid,)).fetchall()
            uses = [(fp, ln) for fp, ln, kind in rows if fp != target and kind != "import"]
            if not uses:
                continue
            dist: dict[str, int] = {}
            for fp, _ln in uses:
                dist[_top_module(fp)] = dist.get(_top_module(fp), 0) + 1
            dist_s = ", ".join(f"{m}({c})" for m, c in sorted(dist.items(), key=lambda kv: -kv[1]))
            records.append({
                "dimension": "util_graph", "subject": f"{Path(target).stem}.{name}",
                "statement": f"{Path(target).stem}.{name} 被 {len(uses)} 处外部引用，分布：{dist_s}",
                "source": "code_evidence", "sample_size": len(uses), "compliance": None,
                "drift": 0, "evidence": [{"file": fp, "line": ln} for fp, ln in uses[:EVIDENCE_CAP]],
            })
    return records


def check_skeleton(rule, ctx):
    params = rule.get("params") or {}
    files = _glob_match(ctx["files"], params["glob"], tuple(params.get("exclude_name_prefix") or ()))
    texts = {}
    for rel in files:
        try:
            texts[rel] = (ctx["root"] / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    records = []
    for trait, pat in (params.get("traits") or {}).items():
        hits = [rel for rel, t in texts.items() if pat in t]
        n = len(texts)
        records.append({
            "dimension": "skeleton", "subject": f"{rule['id']}:{trait}",
            "statement": f"{rule.get('statement', rule['id'])}：{n} 个中 {len(hits)} 个含{trait}",
            "source": "code_evidence", "sample_size": n,
            "compliance": (len(hits) / n) if n else None, "drift": 0,
            "evidence": [{"file": rel, "line": 1} for rel in hits[:EVIDENCE_CAP]],
        })
    return records


def check_exit_codes(rule, ctx):
    files = _glob_match(ctx["files"], (rule.get("params") or {}).get("glob", "scripts/*.py"))
    hist: dict[str, int] = {}
    for rel in files:
        try:
            lines = (ctx["root"] / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            m = SYS_EXIT_RE.search(line) or RETURN_CODE_RE.match(line)
            if m:
                hist[m.group(1)] = hist.get(m.group(1), 0) + 1
    h = ", ".join(f"{k}×{c}" for k, c in sorted(hist.items())) or "(无)"
    return [{
        "dimension": "exit_codes", "subject": rule["id"],
        "statement": f"退出码字面量分布：{h}", "source": "code_evidence",
        "sample_size": sum(hist.values()), "compliance": None, "drift": 0, "evidence": [],
    }]


CHECKERS.update({
    "path_literal_scan": check_path_literal,
    "logging_style": check_logging_style,
    "layering": check_layering,
    "skeleton": check_skeleton,
    "util_graph": check_util_graph,
    "exit_codes": check_exit_codes,
})
```

删除 `DIMENSIONS` 与五个旧 `mine_*` 函数及 `USAGE_EDGE_KINDS` 残留引用（若有）；docstring 更新为规则驱动说明。`_run_rules` 中 fallback 的 layering 空 forbidden 经 check_layering 只出事实记录——但 check_layering 在 cg None 时 stderr 并返回 []（无 db 项目兜底为空+注明，符合 no-silent-fallback）。

- [ ] **Step 4: 跑测试** — `python3 -m pytest tests/test_mine_conventions.py -q` 全过（含注册完整性）；`python3 -m pytest tests/ -q | tail -2` 全量绿。

- [ ] **Step 5: Commit**

```bash
git add bin/mine_conventions.py tests/test_mine_conventions.py
git commit -m "feat(distiller): 六 checker 参数化——规则全量走 conventions.yaml，旧 mine_* 退役（P2 Task 2）"
```

---

### Task 3: setup_project 自动生成 conventions.yaml 模板

**Files:**
- Modify: `scripts/setup/setup_project.py`（追加 ensure_conventions_yaml）
- Test: `tests/test_setup_project.py`（追加 2 条）

**Interfaces:**
- Consumes: 无新依赖
- Produces: `ensure_conventions_yaml(project: Path) -> str`（created/already-ok）；main() 在 first_distill 前调用。

- [ ] **Step 1: 追加失败测试**

```python
def test_ensure_conventions_yaml_creates_and_idempotent(tmp_path):
    sp = _load()
    repo = _git_repo(tmp_path)
    assert sp.ensure_conventions_yaml(repo) == "created"
    text = (repo / "conventions.yaml").read_text(encoding="utf-8")
    assert "rules:" in text and "path_literal_scan" in text and "#" in text
    assert sp.ensure_conventions_yaml(repo) == "already-ok"
    assert (repo / "conventions.yaml").read_text(encoding="utf-8") == text
```

- [ ] **Step 2: 确认失败**（函数不存在）。

- [ ] **Step 3: 实现**

```python
CONVENTIONS_TEMPLATE = """# 项目约定声明（dl setup 生成模板——按项目实际规范填写/删减；真源见 ~/.dl-workflow/designs/setup-installer-design.md）
# 每规则：id（唯一）/ type（checker 类型）/ statement（文档声明，呈证用）/ params。
# 类型：path_literal_scan | logging_style | layering | skeleton | util_graph | exit_codes
# 无本文件或 rules 为空 -> 蒸馏器只跑 import 图纯事实。
rules:
  # 示例 1：路径真源规则（paths.py 换成你项目的路径模块）
  - id: H7_path_literal
    type: path_literal_scan
    statement: "路径只能 from paths import"
    params:
      exempt_files: [paths.py]
      preset: abs_unix_path        # 或 abs_win_path / regex 自定义
  # 示例 2：日志风格
  - id: H11_log_style
    type: logging_style
    statement: "日志 % 惰性禁 f-string"
    params:
      fstring_regex: 'logger\\.(debug|info|warning|error|critical)\\(\\s*f["'']'
      lazy_regex: 'logger\\.(debug|info|warning|error|critical)\\(\\s*["''][^"'\\n]*%[srda]'
  # 示例 3：分层边界（from 支持 "*" 通配）
  - id: H1_layering
    type: layering
    statement: "模块边界：UI 只读后端"
    params:
      forbidden: [{from: "*", to: web_ui}]
  # 示例 4：脚本族骨架（traits 键=统计项名，值=子串匹配）
  - id: scripts_skeleton
    type: skeleton
    statement: "scripts/ 族骨架模式"
    params:
      glob: "scripts/*.py"
      exclude_name_prefix: [test_]
      traits: {argparse: "import argparse", main函数: "def main(", __main__守卫: "__name__", paths导入: "from paths import"}
  # 示例 5：工具函数使用图谱（需 codegraph db）
  - id: util_graph
    type: util_graph
    params: {target_files: [paths.py]}
  # 示例 6：退出码分布（纯事实）
  - id: scripts_exit_codes
    type: exit_codes
    params: {glob: "scripts/*.py"}
"""


def ensure_conventions_yaml(project: Path) -> str:
    """缺则写注释模板（幂等）；存在不动。"""
    path = project / "conventions.yaml"
    if path.exists():
        return "already-ok"
    path.write_text(CONVENTIONS_TEMPLATE, encoding="utf-8")
    return "created"
```

main() 里 first_distill 之前插入：

```python
    cy = ensure_conventions_yaml(project)
    print(f"✓ conventions.yaml: {cy}")
```

- [ ] **Step 4: 跑测试** — `python3 -m pytest tests/test_setup_project.py -q` 全过。

- [ ] **Step 5: Commit**

```bash
git add scripts/setup/setup_project.py tests/test_setup_project.py
git commit -m "feat(setup): 缺 conventions.yaml 自动生成注释模板——新项目接入零手工（P2 Task 3）"
```

---

### Task 4: factor 仓迁移——写 yaml + 等价验证 + 副本退役

**Files（factor 仓 /home/admin/projects/factor_ic_analyzer，master 分支）:**
- Create: `conventions.yaml`
- Delete: `scripts/mine_conventions.py`、`scripts/cvx.py`、`scripts/test_mine_conventions.py`、`scripts/test_cvx.py`、`.claude/hooks/codegraph_inject.py`、`.claude/hooks/conventions_inject.py`、`test_cases/test_codegraph_inject.py`、`test_cases/test_conventions_inject.py`
- Modify: `CLAUDE.md`（§3 cvx 行指向 ~/.dl-workflow/bin/cvx.py）、`designs/convention_mining_design.md`（加退役注记）、`designs/codegraph_auto_inject_design.md`（加真源迁移注记）

**Interfaces:**
- Consumes: Task 2 通用蒸馏器 + Task 3 模板
- Produces: factor 的 conventions.yaml（入库）；退役后 factor 全仓测试仍绿。

- [ ] **Step 1: 写 factor conventions.yaml（入库）**

```yaml
# factor_ic_analyzer 约定声明（蒸馏器规则真源；语法见 ~/.dl-workflow/designs/setup-installer-design.md）
# 2026-09-05 由 scripts/mine_conventions.py 硬编码迁移而来（P2）。
rules:
  - id: H7_path_literal
    type: path_literal_scan
    statement: "路径只能 from paths import"
    params: {exempt_files: [paths.py], preset: abs_unix_path}
  - id: H11_log_style
    type: logging_style
    statement: "日志 % 惰性禁 f-string"
    params:
      fstring_regex: 'logger\.(debug|info|warning|error|critical)\(\s*f["'']'
      lazy_regex: 'logger\.(debug|info|warning|error|critical)\(\s*["''][^"''\n]*%[srda]'
  - id: H1_layering
    type: layering
    statement: "模块边界：web_ui 只读后端"
    params: {forbidden: [{from: "*", to: web_ui}]}
  - id: scripts_skeleton
    type: skeleton
    statement: "scripts/ 族骨架模式"
    params:
      glob: "scripts/*.py"
      exclude_name_prefix: [test_]
      traits: {argparse: "import argparse", main函数: "def main(", __main__守卫: "__name__", paths导入: "from paths import"}
  - id: util_graph
    type: util_graph
    params: {target_files: [paths.py]}
  - id: scripts_exit_codes
    type: exit_codes
    params: {glob: "scripts/*.py"}
```

- [ ] **Step 2: 等价验证（退役前）**

```bash
cd /home/admin/projects/factor_ic_analyzer
python3 ~/.dl-workflow/bin/mine_conventions.py --root . --out /tmp/p2_conv.db 2>/tmp/p2_conv.err
python3 - <<'PY'
import sqlite3
old = sqlite3.connect("file:.conventions/conventions.db?mode=ro", uri=True)
new = sqlite3.connect("file:/tmp/p2_conv.db?mode=ro", uri=True)
# 维度名 P2 已改（d1_path_literal→path_literal_scan 等），subject 改 id 制——按 drift 集合 + 维度聚合对比
MAP = {"d1_path_literal": "path_literal_scan", "d3_style": "logging_style",
       "d2_layering": "layering", "d4_skeleton": "skeleton", "d1_shared_util": "util_graph"}
def agg(conn, dim_from=None):
    rows = conn.execute("SELECT dimension, COUNT(*), SUM(drift) FROM conventions GROUP BY dimension").fetchall()
    return {dim_from.get(d, d) if dim_from else d: (n, dr) for d, n, dr in rows}
print("OLD", agg(old, MAP))
print("NEW", agg(new))
print("OLD drift subjects:", [s for s, in old.execute("SELECT subject FROM conventions WHERE drift=1")])
print("NEW drift subjects:", [s for s, in new.execute("SELECT subject FROM conventions WHERE drift=1")])
# 关键数字抽查
for sub_old, sub_new, col in [("H7 路径字面量", "H7_path_literal", "sample_size"),
                              ("H11 日志风格", "H11", "sample_size")]:
    o = old.execute(f"SELECT {col} FROM conventions WHERE subject=?", (sub_old,)).fetchone()
    n = new.execute(f"SELECT {col} FROM conventions WHERE subject=?", (sub_new,)).fetchone()
    print("NUM", sub_new, o, n, "OK" if o == n else "DIFF")
PY
```
验收口径：① drift 集合等价——OLD {H7 路径字面量， H11 日志风格} → NEW {H7_path_literal, H11}(id 制），drift 总数=2；② 维度聚合条数按 MAP 对齐后一致或差异有解释（util_graph 条数=paths.py 有外部引用的符号数，两版同逻辑应相等）；③ 关键数字（H7/H11 sample_size）完全一致；④ `/tmp/p2_conv.err` 为空或仅降级提示。statement 文案因模板化允许差异（对比不看 statement）。若 drift 丢失或数字大面积不符 → 停，回报 BLOCKED。

- [ ] **Step 3: 退役删除 + 文档更新**

```bash
cd /home/admin/projects/factor_ic_analyzer
git rm -q scripts/mine_conventions.py scripts/cvx.py scripts/test_mine_conventions.py scripts/test_cvx.py \
  .claude/hooks/codegraph_inject.py .claude/hooks/conventions_inject.py \
  test_cases/test_codegraph_inject.py test_cases/test_conventions_inject.py
```
CLAUDE.md §3 行改为：`| 查项目约定/规范实证（工具用法/分层/写法模式/漂移点） | Bash: `python3 ~/.dl-workflow/bin/cvx.py query <主题>` 或 `... drift`（约定蒸馏 db，post-commit 自动重挖；规则真源=conventions.yaml；见 designs/convention_mining_design.md） |`。
designs/convention_mining_design.md 验收节追加：「P2 退役记录：蒸馏器/cvx/inject hook 真源迁至 ~/.dl-workflow（setup-installer P2）；本仓保留 conventions.yaml（规则真源）+ .conventions db（产物）；等价验证 <Step 2 结果摘要>」。
designs/codegraph_auto_inject_design.md 头部追加一行：「⚠️ 2026-09-05 真源迁移：本设计所述 codegraph_inject.py 已集中至 ~/.dl-workflow/hooks/（designs/setup-installer-design.md），本仓 .claude/hooks/ 副本已退役。」

- [ ] **Step 4: 全量验证**

```bash
cd /home/admin/projects/factor_ic_analyzer
python3 -m pytest -q 2>&1 | tail -2
python3 ~/.dl-workflow/bin/cvx.py drift
echo '{"prompt":"查 drift","cwd":"/home/admin/projects/factor_ic_analyzer"}' | python3 ~/.dl-workflow/hooks/conventions_inject.py | head -c 200
```
Expected: 测试全绿（退役删除后无残留 import）；drift 仍 H7/H11 在列；注入正常。

- [ ] **Step 5: Commit（factor 仓）**

```bash
git add conventions.yaml CLAUDE.md designs/convention_mining_design.md designs/codegraph_auto_inject_design.md
git commit -m "refactor(conventions): 蒸馏器/cvx/inject hook 副本退役——真源集中 ~/.dl-workflow，规则真源=conventions.yaml（setup-installer P2 迁移，等价验证通过）"
```

---

## 验收（P2）

1. Task 2 后 `tests/` 全量绿；六 checker 注册完整性测试锁死集合。
2. Task 4 Step 2 等价表：drift 集合与旧版一致、数字无未解释差异。
3. factor 仓退役后 pytest 全绿 + cvx/inject 冒烟正常。
