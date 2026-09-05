#!/usr/bin/env python3
"""mine_conventions - 项目约定蒸馏器（designs/convention_mining_design.md）。

从代码实证蒸馏隐性约定（隐性约定 = 代码中统计上稳定重复的模式）。
checker 全部由 <root>/conventions.yaml 规则驱动（load_rules 校验 type ∈ CHECKERS 六类型）：

- util_graph：共享工具使用图谱（codegraph db 反查目标文件符号）
- path_literal_scan / logging_style / layering：doc_declared 声明类，实证违反 → drift=1
- skeleton / exit_codes：code_evidence 纯事实分布

仲裁原则：不裁决只呈证。doc_declared 规则有实证违反 → drift=1，由人决断。

用法：python3 ~/.dl-workflow/bin/mine_conventions.py [--codegraph-db PATH] [--out PATH] [--root DIR]
退出码（H12）：0=正常；1=蒸馏/写库失败。

P2 软降级语义（通用化）：codegraph db 缺失 → cg=None 警告继续（需 db 的 checker 跳过）；
非 git 仓库 → files/commit_hash 置空继续（纯 db 维度仍运行）。无 conventions.yaml/rules →
降级 import 图纯事实。唯二硬失败：PyYAML 缺失、conventions.yaml 解析失败（均 SystemExit/exit 1，
不静默兜底）。
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path, PurePath


DEFAULT_CG_DB = Path(".codegraph") / "codegraph.db"
DEFAULT_OUT = Path(".conventions") / "conventions.db"
EVIDENCE_CAP = 5

SCHEMA_SQL = """
CREATE TABLE conventions (
  id INTEGER PRIMARY KEY,
  dimension TEXT NOT NULL,
  subject TEXT NOT NULL,
  statement TEXT NOT NULL,
  source TEXT NOT NULL,
  sample_size INTEGER NOT NULL,
  compliance REAL,
  drift INTEGER NOT NULL DEFAULT 0,
  evidence TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  commit_hash TEXT
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def _git_tracked_py(root: Path) -> list[str]:
    return [ln for ln in _git(root, "ls-files", "--", "*.py").splitlines() if ln]


def _top_module(rel: str) -> str:
    parts = Path(rel).parts
    return parts[0] if len(parts) > 1 else "(root)"


def _open_codegraph(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"codegraph db 不存在: {db_path}（先跑 codegraph index）")
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _write_db(out_path: Path, records: list[dict], generated_at: str, commit_hash: str) -> None:
    """原子写：先写临时文件再 rename，避免半截 db 被 cvx/inject 读到。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executemany(
            "INSERT INTO conventions (dimension, subject, statement, source, sample_size,"
            " compliance, drift, evidence, generated_at, commit_hash)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    r["dimension"],
                    r["subject"],
                    r["statement"],
                    r["source"],
                    r["sample_size"],
                    r["compliance"],
                    r["drift"],
                    json.dumps(r["evidence"], ensure_ascii=False),
                    generated_at,
                    commit_hash,
                )
                for r in records
            ],
        )
        conn.executemany(
            "INSERT INTO meta (key, value) VALUES (?,?)",
            [("generated_at", generated_at), ("commit_hash", commit_hash)],
        )
        conn.commit()
    finally:
        conn.close()
    os.replace(tmp, out_path)


# D3 正则：H11 日志风格 + 退出码字面量
_LOG_FN = r"logger\.(?:debug|info|warning|error|critical)\("
FSTRING_LOG_RE = re.compile(_LOG_FN + r"""\s*f["']""")
LAZY_LOG_RE = re.compile(_LOG_FN + r"""\s*["'][^"'\n]*%[srda]""")
SYS_EXIT_RE = re.compile(r"\bsys\.exit\((\d+)\)")
RETURN_CODE_RE = re.compile(r"^\s*return (\d)\s*(?:#.*)?$")


# ---------- 规则驱动（P2 通用化，designs/setup-installer-design.md §conventions.yaml） ----------
RULES_FILE = "conventions.yaml"

# 规则类型注册表：fn(rule, ctx) -> list[dict]；ctx = {"cg", "root", "files"}
CHECKERS: dict = {}

# 路径字面量预设（params.regex 优先，否则按 preset 取）
_PRESET_PATH_RES = {"abs_unix_path": re.compile(r"""["'](/(?:home|data|mnt|opt|srv)/)"""),
                    "abs_win_path": re.compile(r"""[A-Za-z]:\\\\""")}

# 各 rule type 的必填 params 键（缺省视为空集）
REQUIRED_PARAMS = {
    "path_literal_scan": set(),          # preset/regex 二选一皆有默认
    "logging_style": {"fstring_regex", "lazy_regex"},
    "layering": set(),                   # forbidden 缺省视为 []
    "skeleton": {"glob", "traits"},
    "util_graph": {"target_files"},
    "exit_codes": set(),
}


def _glob_match(files, glob, exclude_prefix=()):
    return [f for f in files
            if PurePath(f).match(glob) and not PurePath(f).name.startswith(exclude_prefix)]


def check_path_literal(rule, ctx):
    params = rule.get("params") or {}
    if params.get("regex"):
        pat = re.compile(params["regex"])
    else:
        pat = _PRESET_PATH_RES[params.get("preset", "abs_unix_path")]
    exempt = set(params.get("exempt_files") or [])
    violations, scanned = [], 0
    for rel in ctx["files"]:
        scanned += 1
        if rel in exempt:
            continue  # 豁免文件仍计分母（合规率口径含它自身），只跳过扫描
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
        print(f"mine_conventions: {rule['type']} 需 codegraph db，跳过", file=sys.stderr)
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
                break  # 同一条边不被多条 forbidden 重复计数
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
    if not isinstance(data, dict):
        print(f"mine_conventions: {RULES_FILE} 顶层非 mapping（视作无 rules）", file=sys.stderr)
        return []
    rules = data.get("rules") or []
    valid = []
    for r in rules:
        rtype = r.get("type") if isinstance(r, dict) else None
        if not rtype or rtype not in CHECKERS:
            print(f"mine_conventions: 跳过未知/缺 type 的 rule: {r!r:.120}", file=sys.stderr)
            continue
        params = r.get("params") or {}
        missing = REQUIRED_PARAMS.get(rtype, set()) - set(params)
        if missing:
            print(f"mine_conventions: 跳过缺 params 的 rule: {r.get('id')}（缺 {sorted(missing)}）",
                  file=sys.stderr)
            continue
        if rtype == "path_literal_scan":
            if "preset" in params and params["preset"] not in _PRESET_PATH_RES:
                print(f"mine_conventions: 跳过未知 preset 的 rule: {r.get('id')}（{params['preset']}）",
                      file=sys.stderr)
                continue
            if "regex" in params:
                try:
                    re.compile(params["regex"])
                except re.error as e:
                    print(f"mine_conventions: 跳过非法 regex 的 rule: {r.get('id')}（{e}）",
                          file=sys.stderr)
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="项目约定蒸馏器（designs/convention_mining_design.md）")
    parser.add_argument("--codegraph-db", type=Path, default=DEFAULT_CG_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    # 软降级（P2 通用化）：codegraph db 缺失不再 exit 1，cg=None 交给需 db 的 checker 自行处理
    try:
        cg = _open_codegraph(args.codegraph_db)
    except (FileNotFoundError, sqlite3.OperationalError):
        print("mine_conventions: codegraph db 缺失，需 db 的 checker 将跳过（stderr 注明）", file=sys.stderr)
        cg = None
    # 非 git 仓库：files 为空、commit_hash 为空串（纯 db 维度仍运行）
    try:
        files = _git_tracked_py(args.root)
        commit_hash = _git(args.root, "rev-parse", "HEAD")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("mine_conventions: 非 git 仓库或缺 git 命令，files 为空（纯 db 维度仍运行）", file=sys.stderr)
        files, commit_hash = [], ""
    try:
        records = _run_rules(cg, args.root, files)
        _write_db(args.out, records, time.strftime("%Y-%m-%dT%H:%M:%S"), commit_hash)
    except (sqlite3.Error, OSError) as e:
        print(f"mine_conventions: 蒸馏失败: {e}", file=sys.stderr)
        return 1
    finally:
        if cg:
            cg.close()

    n_drift = sum(r["drift"] for r in records)
    print(f"conventions: {len(records)} 条（drift {n_drift}）-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
