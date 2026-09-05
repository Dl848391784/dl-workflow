# 归纳层（inference layer）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 蒸馏器从「人声明规范、机器呈证」扩展出第三来源 `inferred`（机器归纳候选规范）——**分析得出为主**（无 yaml 也能产出候选），**手动填写为校准**（同类型手动规则抑制候选；`dismissed:` 清单否决候选；确认后抄进 yaml 转正）。

**核心语义（用户已拍板）:**
- 三种来源：`doc_declared`（yaml 人声明=已校准权威）/ `code_evidence`（纯事实）/ `inferred`（机器候选，待人确认）。
- **槽位校准**：每规则类型一个槽位——yaml 存在同 type 的手动规则 → 该类型候选不再产出（人的校准优先）。
- **否决持久化**：yaml 顶层 `dismissed: [候选 subject, ...]`，生成器跳过。
- 候选记录复用 8 字段契约：`source="inferred"`、`subject="inferred:<type>:<slug>"`、`compliance`=支持度、`statement` 含支持度+新近度叙事。
- **新近度维度**（「最新的是规范」）：证据文件按 git 最后提交时间分新老；违反案例集中在 N 年前老文件 → 叙事标注「主流写法=B，违反案例均为遗留」。

**Architecture:** `mine_conventions.py` 新增候选生成器模块区：`mine_candidates(cg, root, files, rules, dismissed) -> list[dict]`，main 在规则派发后总是调用（候选为主）。G1=写法主流归纳（logging，参数无关全库扫描）；G2=工具引用集中度（codegraph import 图，TOP 集中目标）。注入 hook 增加候选区（≤3 条）；cvx 格式加 CANDIDATE 标记。——cvx CANDIDATE 标记未做：query 已暴露 source=inferred，drift 通道天然隔离，标记冗余（终审裁决）

**Tech Stack:** Python 3.11 stdlib + PyYAML + git CLI；pytest。

## Global Constraints

- 8 字段契约不变；单文件自足；候选永不标 drift（drift 只属于 doc_declared 实证违反）。
- 抑制/否决逻辑：同 type 手动规则存在 → 该 type 候选抑制；subject ∈ dismissed → 跳过。两者都在生成器内完成，main 不感知。
- 新近度：只对证据样本文件（≤5/条）做 `git log -1 --format=%ct`（批量上限 25 文件防大仓拖慢）；失败文件按「未知」处理不计入新老分桶。
- 阈值常量集中文件头：`SUPPORT_MIN=0.90`、`MIN_SAMPLE=20`、`LEGACY_AGE_DAYS=365`、`CANDIDATE_CAP=3`（注入）。
- 每 task 独立 commit；禁 git add -A；测试 importlib `_load` 惯例。

---

### Task 1: 新近度工具 + 候选生成器框架 + G1（写法主流归纳）

**Files:**
- Modify: `bin/mine_conventions.py`
- Test: `tests/test_mine_conventions.py`（追加）

**Interfaces:**
- Consumes: 现有 CHECKERS/_run_rules/main、8 字段契约
- Produces: `_file_ages(root, files) -> dict[str, int|None]`（path→epoch，git log -1）；`mine_candidates(cg, root, files, rules, dismissed) -> list[dict]`；G1 生成 `_g1_logging_majority(files, root)`；常量区（Global Constraints 列的阈值）。main 改动：`records += mine_candidates(cg, args.root, files, rules, load_dismissed(args.root))`。

- [ ] **Step 1: 追加失败测试**

```python
def _repo_with_commits(tmp_path, files_with_dates):
    """files_with_dates: {relpath: (content, days_ago)}——按日期倒序提交（git 允许 --date 历史）。"""
    import subprocess

    repo = tmp_path / "proj"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    import time

    for rel, (content, days_ago) in sorted(files_with_dates.items(), key=lambda kv: kv[1][1]):
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        date = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - days_ago * 86400))
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", rel,
                        "--date", date], cwd=repo, check=True)
    return repo


def test_file_ages_and_none_on_missing_git(tmp_path):
    repo = _repo_with_commits(tmp_path, {"a.py": ("x=1\n", 10), "sub/b.py": ("y=2\n", 400)})
    ages = mc._file_ages(repo, ["a.py", "sub/b.py", "gone.py"])
    assert ages["a.py"] is not None and ages["a.py"] > ages["sub/b.py"]
    assert ages["gone.py"] is None


def test_g1_logging_majority_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "MIN_SAMPLE", 2)  # fixture 样本量 3 < 默认 20
    repo = _repo_with_commits(tmp_path, {
        "new1.py": ('logger.info("a %s", x)\n', 10),
        "new2.py": ('logger.info("b %s", y)\n', 20),
        "old.py": ('logger.info(f"c {z}")\n', 800),
    })
    cands = mc._g1_logging_majority(["new1.py", "new2.py", "old.py"], repo)
    assert len(cands) == 1
    c = cands[0]
    assert c["source"] == "inferred" and c["drift"] == 0
    assert c["subject"] == "inferred:logging:lazy_percent"
    assert c["compliance"] == pytest.approx(2 / 3)
    assert "新近" in c["statement"] or "遗留" in c["statement"]


def test_mine_candidates_suppressed_by_manual_rule_and_dismissed(tmp_path):
    repo = _repo_with_commits(tmp_path, {"a.py": ('logger.info("x %s", v)\n', 5)})
    files = ["a.py"]
    manual = [{"id": "H11", "type": "logging_style",
               "params": {"fstring_regex": mc.FSTRING_LOG_RE.pattern, "lazy_regex": mc.LAZY_LOG_RE.pattern}}]
    assert mc.mine_candidates(None, repo, files, manual, []) == []
    cands = mc.mine_candidates(None, repo, files, [], [])
    assert cands and cands[0]["source"] == "inferred"
    assert mc.mine_candidates(None, repo, files, [], [cands[0]["subject"]]) == []


def test_load_dismissed(tmp_path):
    (tmp_path / "conventions.yaml").write_text("dismissed:\n  - inferred:logging:lazy_percent\n", encoding="utf-8")
    assert mc.load_dismissed(tmp_path) == ["inferred:logging:lazy_percent"]
    assert mc.load_dismissed(tmp_path / "nope") == []
```

- [ ] **Step 2: 确认失败** — 4 failed。

- [ ] **Step 3: 实现**

```python
# ---------- 归纳层（inferred 候选规范：分析得出为主，手动 yaml 校准） ----------
SUPPORT_MIN = 0.90
MIN_SAMPLE = 20
LEGACY_AGE_DAYS = 365
CANDIDATE_CAP = 3
_AGE_BATCH = 25


def _file_ages(root: Path, files: list[str]) -> dict[str, int | None]:
    """证据文件→最后提交 epoch（git log -1）；失败/缺失→None。批量上限防大仓拖慢。"""
    ages: dict[str, int | None] = {}
    for rel in files[:_AGE_BATCH]:
        try:
            proc = subprocess.run(
                ["git", "log", "-1", "--format=%ct", "--", rel],
                cwd=root, capture_output=True, text=True, timeout=15)
            ages[rel] = int(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            ages[rel] = None
    return ages


def _recency_note(root: Path, evidence: list[dict], now: int | None = None) -> str:
    """新近度叙事：违反/证据文件按最后提交分新老桶（LEGACY_AGE_DAYS）。"""
    import time

    now = now or int(time.time())
    ages = _file_ages(root, [e["file"] for e in evidence])
    fresh = legacy = unknown = 0
    for e in evidence:
        age = ages.get(e["file"])
        if age is None:
            unknown += 1
        elif now - age > LEGACY_AGE_DAYS * 86400:
            legacy += 1
        else:
            fresh += 1
    return f"违反案例新近度：近 {LEGACY_AGE_DAYS // 30} 个月 {fresh} 处 / 更早 {legacy} 处 / 未知 {unknown} 处"


def _g1_logging_majority(files: list[str], root: Path) -> list[dict]:
    """G1 写法主流归纳：全库日志风格统计（参数无关）。多数派≥MIN_SAMPLE 即产候选。"""
    f_hits: list[dict] = []
    lazy = 0
    for rel in files:
        try:
            lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if FSTRING_LOG_RE.search(line):
                f_hits.append({"file": rel, "line": i})
            elif LAZY_LOG_RE.search(line):
                lazy += 1
    denom = len(f_hits) + lazy
    if denom < MIN_SAMPLE:
        return []
    majority, support, minority_hits = (
        ("%-惰性", lazy / denom, f_hits) if lazy >= len(f_hits) else ("f-string", len(f_hits) / denom, [])
    )
    return [{
        "dimension": "inferred", "subject": "inferred:logging:lazy_percent",
        "statement": (f"候选规范：日志主流写法={majority}（支持度 {support:.2f}, n={denom}）；"
                      f"{_recency_note(root, minority_hits)}——确认后写入 conventions.yaml 转正"),
        "source": "inferred", "sample_size": denom, "compliance": round(support, 4),
        "drift": 0, "evidence": minority_hits[:EVIDENCE_CAP],
    }]


_GENERATORS = {"logging_style": _g1_logging_majority}  # Task 2 追加 util_graph 的 G2


def load_dismissed(root: Path) -> list[str]:
    """conventions.yaml 顶层 dismissed 清单（否决的候选 subject，不再产出）。"""
    try:
        import yaml
    except ImportError:
        return []
    path = root / RULES_FILE
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    return list(data.get("dismissed") or [])


def mine_candidates(cg, root: Path, files: list[str], rules: list[dict], dismissed: list[str]) -> list[dict]:
    """槽位校准：每 type 一个槽——yaml 有同 type 手动规则则抑制该 type 候选；dismissed 跳过。"""
    manual_types = {r["type"] for r in rules}
    cands = []
    for rtype, gen in _GENERATORS.items():
        if rtype in manual_types:
            continue
        for c in gen(files, root):
            if c["subject"] not in dismissed:
                cands.append(c)
    return cands
```
（G1 签名用 (files, root)——不依赖 cg；Task 2 的 G2 需要 cg，_GENERATORS 值签名统一为 gen(files, root, cg=None)，调用处传 cg。main 里：`records += mine_candidates(cg, args.root, files, rules, load_dismissed(args.root))`——`rules` 取 _run_rules 内已 load 的那份，避免二次读文件：把 _run_rules 改为返回 (records, rules) 或让 main 先 load。实现选择：main 里 `rules = load_rules(args.root)` 传进 _run_rules 重构，最小改动为先在 main 重复 load_rules 一次（幂等、纯读），注释注明。）

- [ ] **Step 4: 跑测试** — 全过（新 4 + 旧有）。

- [ ] **Step 5: factor 真实冒烟**

```bash
cd /home/admin/projects/factor_ic_analyzer
python3 /home/admin/projects/dl-p6-infer/bin/mine_conventions.py --root . --out /tmp/infer1.db 2>/dev/null
python3 - <<'PY'
import sqlite3
conn = sqlite3.connect("file:/tmp/infer1.db?mode=ro", uri=True)
for r in conn.execute("SELECT subject, statement, sample_size, compliance FROM conventions WHERE source='inferred'"):
    print(r)
PY
```
Expected：出现 inferred:logging:lazy_percent 候选（n=942，支持度≈0.999，叙事含新近度；factor 的唯一 f-string 是遗留测试夹具已删——冒烟时违反案例可能为 0，叙事退化为纯支持度，属正常）。

- [ ] **Step 6: Commit**

```bash
git add bin/mine_conventions.py tests/test_mine_conventions.py
git commit -m "feat(distiller): 归纳层——inferred 候选规范（G1 写法主流+新近度叙事），槽位校准+dismissed 抑制"
```

---

### Task 2: G2（工具引用集中度）+ 注入/cvx 呈现候选

**Files:**
- Modify: `bin/mine_conventions.py`（G2 + _GENERATORS 签名统一）
- Modify: `hooks/conventions_inject.py`（候选区）
- Test: `tests/test_mine_conventions.py`、`tests/test_project_inject_hooks.py`

**Interfaces:**
- Consumes: Task 1 框架
- Produces: `_g2_util_concentration(cg, files)`；`_GENERATORS = {"logging_style": ..., "util_graph": _g2_util_concentration}` 统一签名 `gen(files, root, cg)`；inject 文本新增「🔍 候选规范」区（≤CANDIDATE_CAP 条，source='inferred' 且非 drift）。

- [ ] **Step 1: 追加失败测试**

```python
def test_g2_util_concentration(tmp_path):
    conn = sqlite3.connect(tmp_path / "cg.db")
    conn.executescript(CG_SCHEMA)
    nodes = [("u1", "function", "load", "common/loader.py", 1),
             ("m1", "function", "a", "web/app.py", 1), ("m2", "function", "b", "svc/b.py", 1),
             ("m3", "function", "c", "svc/c.py", 1), ("m4", "function", "d", "dao/d.py", 1)]
    conn.executemany("INSERT INTO nodes VALUES (?,?,?,?,?)", nodes)
    edges = [("m1", "u1", "references", 2), ("m2", "u1", "references", 3),
             ("m3", "u1", "references", 4), ("m4", "u1", "references", 5),
             ("m1", "m2", "references", 6)]  # 干扰边：非 common 目标
    conn.executemany("INSERT INTO edges (source, target, kind, line) VALUES (?,?,?,?)", edges)
    conn.commit()
    cands = mc._g2_util_concentration(conn, ["web/app.py", "svc/b.py", "svc/c.py", "dao/d.py"])
    assert len(cands) == 1
    c = cands[0]
    assert c["subject"].startswith("inferred:util_graph:")
    assert "common.loader" in c["subject"] and c["sample_size"] == 4
    assert c["source"] == "inferred" and c["drift"] == 0
```

（MIN_SAMPLE=20 会挡住这个小 fixture——测试内 monkeypatch `mc.MIN_SAMPLE = 2`。）

- [ ] **Step 2: 确认失败** → **Step 3: 实现**

```python
_IMPORT_EDGE_KINDS = ("imports", "references")


def _g2_util_concentration(cg, files) -> list[dict]:
    """G2 工具引用集中度：被 ≥MIN_SAMPLE 个不同模块引用的 import 目标 → 候选「公共工具应走 X」。

    候选资格：目标文件自身出边少（工具特征：被多引少引别）且集中度=引用方模块数。
    """
    if cg is None:
        return []
    rows = cg.execute(
        "SELECT n2.file_path, n1.file_path FROM edges e"
        " JOIN nodes n1 ON n1.id = e.source JOIN nodes n2 ON n2.id = e.target"
        f" WHERE e.kind IN ({','.join('?' * len(_IMPORT_EDGE_KINDS))})",
        _IMPORT_EDGE_KINDS).fetchall()
    importers: dict[str, set[str]] = {}
    for dst_fp, src_fp in rows:
        if dst_fp != src_fp:
            importers.setdefault(dst_fp, set()).add(_top_module(src_fp))
    cands = []
    for target, mods in sorted(importers.items(), key=lambda kv: -len(kv[1])):
        if len(mods) < MIN_SAMPLE:
            continue
        try:
            out_degree = cg.execute(
                "SELECT COUNT(DISTINCT e.target) FROM edges e JOIN nodes n ON n.id = e.source"
                " WHERE n.file_path = ?", (target,)).fetchone()[0]
        except sqlite3.Error:
            out_degree = 0
        if out_degree > len(mods):
            continue  # 不是工具特征（它自己还重度依赖别人）
        stem = Path(target).with_suffix("").as_posix().replace("/", ".")
        cands.append({
            "dimension": "inferred", "subject": f"inferred:util_graph:{stem}",
            "statement": (f"候选规范：公共工具引用集中于 {stem}（{len(mods)} 个模块引用）"
                          f"——新代码应优先复用而非新造"),
            "source": "inferred", "sample_size": len(mods),
            "compliance": None, "drift": 0, "evidence": [],
        })
    return cands
```
`_GENERATORS = {"logging_style": _g1_logging_majority, "util_graph": _g2_util_concentration}`；mine_candidates 调用统一 `gen(files, root, cg)`（G1 忽略第三参）。

**inject 改造**（conventions_inject.py `_load` + `_format`）：
- `_load` 增加第三返回：candidates = `SELECT dimension, subject, statement FROM conventions WHERE source='inferred' ORDER BY sample_size DESC LIMIT ?`（CANDIDATE_CAP）。
- `_format(drifts, total, gap, candidates)`：漂移区后加「🔍 候选规范（待人确认，认可后写入 conventions.yaml 转正）」区，每条 `- 🔍 {subject} :: {statement}`。
- 触发条件：drifts 或 stale 或 **candidates** 任一存在即注入。

- [ ] **Step 4: 测试** — `python3 -m pytest tests/test_mine_conventions.py tests/test_project_inject_hooks.py -q` 全过（inject 测试需同步：fixture db 加 inferred 行断言候选出现在注入文本）。

- [ ] **Step 5: Commit**

```bash
git add bin/mine_conventions.py hooks/conventions_inject.py tests/test_mine_conventions.py tests/test_project_inject_hooks.py
git commit -m "feat(distiller+hooks): G2 工具引用集中度+注入/cvx 呈现 inferred 候选"
```

---

### Task 3: factor 端到端验证 + README 归纳层使用说明

**Files:**
- Modify: `README.md`（conventions.yaml 章节补归纳层说明）

- [ ] **Step 1: factor 端到端**

```bash
cd /home/admin/projects/factor_ic_analyzer
python3 /home/admin/projects/dl-p6-infer/bin/mine_conventions.py --root . --out .conventions/conventions.db
python3 /home/admin/projects/dl-p6-infer/bin/cvx.py query 候选
echo '{"prompt":"看看","cwd":"/home/admin/projects/factor_ic_analyzer"}' | python3 /home/admin/projects/dl-p6-infer/hooks/conventions_inject.py | head -c 400
```
Expected：候选出现在 db/cvx/注入文本；然后**验证槽位校准**：临时在 factor conventions.yaml 加一条 type: logging_style 的手动规则 → 重跑 → inferred:logging 候选消失（验证后回滚该临时规则）。

- [ ] **Step 2: README 补段**（conventions.yaml 说明处追加）：

```markdown
#### 归纳层（inferred 候选规范）

无手动规则时，蒸馏器自动从代码归纳**候选规范**（source=inferred，注入文本 🔍 标记）——
支持度/新近度证据随候选一并给出（「用得最多」「最新的写法」由 git 历史判定）。
**校准三态**：认可 → 把候选 params 抄进 `rules:` 转正（该类型候选此后抑制）；
否决 → subject 加进顶层 `dismissed:` 清单不再产出；不处理 → 每次注入继续呈证，不裁决。
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): 归纳层使用说明——候选三态校准（转正/否决/呈证）"
```

---

## 验收

1. 无 yaml 项目：跑蒸馏器 → db 出现 inferred 候选（G1 有日志代码时）→ 注入文本含 🔍 区。
2. 槽位校准：yaml 加同 type 手动规则 → 该 type 候选消失；dismissed 清单 → 指定候选消失。
3. 新近度叙事：违反案例文件 last-commit > 365 天时 statement 标注「更早 N 处」。
4. 全量 `pytest tests/ -q` 绿；factor 端到端验证记录回本计划「验收」节。

### 验收记录（2026-09-05，Task 3 e2e 实测）

`pytest tests/ -q`：1524 passed, 2 skipped。e2e 分两面：

**factor 端到端（真实仓，BASE 829afc1 蒸馏器）**：`--root . --out .conventions/conventions.db`
→ 8 条（drift 1），全部 doc_declared/code_evidence，inferred 候选 **0 条**——factor yaml 已有
logging_style（H11）+ util_graph 手动规则，G1/G2 均被槽位抑制（=校准在真实仓的预期行为，
非缺陷）；cvx query 候选 → (no conventions matched)；inject 瘦档无 🔍 区。

**负面对照（/tmp/infer-e2e，临时 git 仓 3 个 .py 共 22 行 %-惰性日志，无 rules yaml）**：
1. 无 yaml → db 出 `inferred:logging:lazy_percent`（支持度 1.00, n=22）；cvx query 候选 命中；
   inject 含 🔍 候选区。
2. `dismissed: [inferred:logging:lazy_percent]` → 重跑 db 0 条，inject 无输出。
3. 加合法手动 `type: logging_style` 规则（params 同 factor H11）→ 候选消失，手动规则接管
   （db 1 条 doc_declared H11_log_style）。
4. 新近度叙事：a.py 追加 1 行 f-string 并以 `--date 2024-01-01` 提交 → statement 标注
   「违反案例新近度：近 12 个月 0 处 / 更早 1 处 / 未知 0 处」（>365 天进更早桶，验收 #3 实证）。
5. 附带修正：`_g2_util_concentration` statement「N 个模块引用」→「N 个文件引用」
   （sample_size 按 distinct 文件计，非模块；含 docstring + inject fixture 同步）。

