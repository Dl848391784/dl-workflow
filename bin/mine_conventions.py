#!/usr/bin/env python3
"""mine_conventions - 项目约定蒸馏器（designs/convention_mining_design.md）。

从代码实证蒸馏隐性约定（隐性约定 = 代码中统计上稳定重复的模式）：
- D1 共享工具使用图谱（codegraph db 反查 paths.py 符号）+ H7 路径字面量违规扫描
- D2 分层依赖方向（import 边聚合成模块对）+ H1 子集（后端禁 import web_ui）
- D3 写法模式（日志 f-string vs %-惰性；退出码分布）
- D4 骨架模式（scripts/ 族的 argparse/main/paths 导入率）

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
from pathlib import Path


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


def mine_d1_shared_utils(cg: sqlite3.Connection, root: Path, files: list[str]) -> list[dict]:
    """D1a：paths.py 公共符号的外部使用统计（调用方按顶层模块分布）。"""
    symbols = cg.execute(
        "SELECT id, name FROM nodes WHERE file_path = 'paths.py' AND kind != 'import'"
    ).fetchall()
    records = []
    for sid, name in symbols:
        rows = cg.execute(
            "SELECT n.file_path, e.line, n.kind FROM edges e JOIN nodes n ON n.id = e.source"
            " WHERE e.target = ? AND e.kind IN ('calls','references','imports')",
            (sid,),
        ).fetchall()
        # 排除 paths.py 自引用与 import 节点噪音
        uses = [(fp, ln) for fp, ln, kind in rows if fp != "paths.py" and kind != "import"]
        if not uses:
            continue
        dist: dict[str, int] = {}
        for fp, _ln in uses:
            dist[_top_module(fp)] = dist.get(_top_module(fp), 0) + 1
        dist_s = ", ".join(f"{m}({c})" for m, c in sorted(dist.items(), key=lambda kv: -kv[1]))
        records.append(
            {
                "dimension": "d1_shared_util",
                "subject": f"paths.{name}",
                "statement": f"paths.{name} 被 {len(uses)} 处外部引用，分布：{dist_s}",
                "source": "code_evidence",
                "sample_size": len(uses),
                "compliance": None,
                "drift": 0,
                "evidence": [{"file": fp, "line": ln} for fp, ln in uses[:EVIDENCE_CAP]],
            }
        )
    return records


# 绝对路径字面量（H7 违规候选）：字符串以常见挂载根开头
ABS_PATH_RE = re.compile(r"""["'](/(?:home|data|mnt|opt|srv)/)""")


def mine_d1_path_literals(cg, root: Path, files: list[str]) -> list[dict]:
    """D1b：H7「路径只能 from paths import」实证——paths.py 之外的绝对路径字面量扫描。"""
    violations: list[dict] = []
    scanned = 0
    for rel in files:
        scanned += 1
        if rel == "paths.py":
            continue  # paths.py 豁免扫描，但仍计入分母（合规率口径含它自身）
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if ABS_PATH_RE.search(line):
                violations.append({"file": rel, "line": i})
                break  # 每文件记一次（统计口径=文件级合规率）
    total = max(scanned, 1)
    clean = scanned - len(violations)
    drift = 1 if violations else 0
    return [
        {
            "dimension": "d1_path_literal",
            "subject": "H7 路径字面量",
            "statement": (
                f"H7 声明路径只能 from paths import；实证 {scanned} 个 .py 中"
                f" {len(violations)} 个含绝对路径字面量（合规率 {clean / total:.2f}）"
            ),
            "source": "doc_declared",
            "sample_size": scanned,
            "compliance": clean / total,
            "drift": drift,
            "evidence": violations[:EVIDENCE_CAP],
        }
    ]


def mine_d2_layering(cg: sqlite3.Connection, root: Path, files: list[str]) -> list[dict]:
    """D2：模块间实际 import 方向聚合；H1 子集实证——后端模块禁 import web_ui。"""
    rows = cg.execute(
        "SELECT n1.file_path, n2.file_path, e.line FROM edges e"
        " JOIN nodes n1 ON n1.id = e.source JOIN nodes n2 ON n2.id = e.target"
        " WHERE e.kind = 'imports'"
    ).fetchall()
    pairs: dict[tuple[str, str], int] = {}
    violations: list[dict] = []
    for src_fp, dst_fp, line in rows:
        src_mod, dst_mod = _top_module(src_fp), _top_module(dst_fp)
        if src_mod == dst_mod:
            continue
        pairs[(src_mod, dst_mod)] = pairs.get((src_mod, dst_mod), 0) + 1
        if dst_mod == "web_ui" and src_mod != "web_ui":
            violations.append({"file": src_fp, "line": line})
    records = [
        {
            "dimension": "d2_layering",
            "subject": f"{s}->{d}",
            "statement": f"{s} import {d}：{c} 处",
            "source": "code_evidence",
            "sample_size": c,
            "compliance": None,
            "drift": 0,
            "evidence": [],
        }
        for (s, d), c in sorted(pairs.items(), key=lambda kv: -kv[1])
    ]
    total_viol = len(violations)
    records.append(
        {
            "dimension": "d2_layering",
            "subject": "H1 模块边界（后端禁 import web_ui）",
            "statement": (f"H1 声明模块边界（web_ui 只读后端）；实证后端 import web_ui {total_viol} 处"),
            "source": "doc_declared",
            "sample_size": sum(pairs.values()),
            "compliance": 1.0 if total_viol == 0 else None,
            "drift": 1 if total_viol else 0,
            "evidence": violations[:EVIDENCE_CAP],
        }
    )
    return records


# D3 正则：H11 日志风格 + 退出码字面量
_LOG_FN = r"logger\.(?:debug|info|warning|error|critical)\("
FSTRING_LOG_RE = re.compile(_LOG_FN + r"""\s*f["']""")
LAZY_LOG_RE = re.compile(_LOG_FN + r"""\s*["'][^"'\n]*%[srda]""")
SYS_EXIT_RE = re.compile(r"\bsys\.exit\((\d+)\)")
RETURN_CODE_RE = re.compile(r"^\s*return (\d)\s*(?:#.*)?$")


def mine_d3_style(cg, root: Path, files: list[str]) -> list[dict]:
    """D3：H11 日志风格实证（f-string vs %-惰性）+ scripts/ 退出码使用分布。"""
    fstring_hits: list[dict] = []
    lazy_count = 0
    exit_codes: dict[str, int] = {}
    for rel in files:
        try:
            lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if FSTRING_LOG_RE.search(line):
                fstring_hits.append({"file": rel, "line": i})
            elif LAZY_LOG_RE.search(line):
                lazy_count += 1
            if rel.startswith("scripts/"):
                m = SYS_EXIT_RE.search(line) or RETURN_CODE_RE.match(line)
                if m:
                    exit_codes[m.group(1)] = exit_codes.get(m.group(1), 0) + 1
    n_f, n_l = len(fstring_hits), lazy_count
    denom = n_f + n_l
    records = [
        {
            "dimension": "d3_style",
            "subject": "H11 日志风格",
            "statement": (f"H11 声明日志 % 惰性禁 f-string；实证 f-string {n_f} 处、%-惰性 {n_l} 处"),
            "source": "doc_declared",
            "sample_size": denom,
            "compliance": (n_l / denom) if denom else None,
            "drift": 1 if n_f else 0,
            "evidence": fstring_hits[:EVIDENCE_CAP],
        }
    ]
    hist = ", ".join(f"{code}×{c}" for code, c in sorted(exit_codes.items())) or "(无)"
    records.append(
        {
            "dimension": "d3_style",
            "subject": "scripts/ 退出码分布",
            "statement": f"scripts/ 退出码字面量分布：{hist}（H12 语义 0/1/3/4/5）",
            "source": "code_evidence",
            "sample_size": sum(exit_codes.values()),
            "compliance": None,
            "drift": 0,
            "evidence": [],
        }
    )
    return records


SKELETON_TRAITS = (
    ("argparse", lambda t: "import argparse" in t),
    ("main 函数", lambda t: "def main(" in t),
    ("__main__ 守卫", lambda t: '__name__ == "__main__"' in t or "__name__ == '__main__'" in t),
    ("paths 导入", lambda t: "from paths import" in t or "import paths" in t),
)


def mine_d4_skeleton(cg, root: Path, files: list[str]) -> list[dict]:
    """D4：scripts/ 非测试脚本的结构共性统计（argparse/main/守卫/paths 导入率）。"""
    scripts = [rel for rel in files if rel.startswith("scripts/") and not Path(rel).name.startswith("test_")]
    texts: dict[str, str] = {}
    for rel in scripts:
        try:
            texts[rel] = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    records = []
    for trait, pred in SKELETON_TRAITS:
        hits = [rel for rel, t in texts.items() if pred(t)]
        n = len(texts)
        records.append(
            {
                "dimension": "d4_skeleton",
                "subject": f"scripts/ 骨架：{trait}",
                "statement": f"scripts/ 非测试脚本 {n} 个中 {len(hits)} 个含{trait}",
                "source": "code_evidence",
                "sample_size": n,
                "compliance": (len(hits) / n) if n else None,
                "drift": 0,
                "evidence": [{"file": rel, "line": 1} for rel in hits[:EVIDENCE_CAP]],
            }
        )
    return records


# 维度 miner 注册表：统一签名 fn(cg, root, files) -> list[dict]，逐 task 追加
DIMENSIONS: tuple = (
    mine_d1_shared_utils,
    mine_d1_path_literals,
    mine_d2_layering,
    mine_d3_style,
    mine_d4_skeleton,
)


# ---------- 规则驱动（P2 通用化，designs/setup-installer-design.md §conventions.yaml） ----------
RULES_FILE = "conventions.yaml"

# 规则类型注册表：fn(rule, ctx) -> list[dict]；ctx = {"cg", "root", "files"}
CHECKERS: dict = {}


# Task 1 过渡注册：layering 先挂旧 mine_d2_layering（import 图纯事实 = 无 yaml 兜底语义），
# 使 load_rules 校验认得内置类型 layering；Task 2 以参数化 check_layering 替换本注册。
def _legacy_layering(rule, ctx):
    if ctx["cg"] is None:
        print("mine_conventions: layering 需 codegraph db，跳过", file=sys.stderr)
        return []
    return mine_d2_layering(ctx["cg"], ctx["root"], ctx["files"])


CHECKERS["layering"] = _legacy_layering


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
    except subprocess.CalledProcessError:
        print("mine_conventions: 非 git 仓库，files 为空（纯 db 维度仍运行）", file=sys.stderr)
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
