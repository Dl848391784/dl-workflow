#!/usr/bin/env python3
"""doctor - dl setup 远程接入一键诊断报告（designs/setup-installer-design.md §阶段3 延伸）。

为「维护者看不到目标机器」场景设计：目标机器上跑一次，把完整输出贴回给维护者即可判
「装没装对、索引成不成、蒸馏有没有产出」。只读 db/配置；inject 冒烟按 hook 既有行为留调用日志（.claude/.c*_inject.log）。

覆盖五节（inject 冒烟会在项目 .claude/ 留 hook 调用日志，属既有观测行为）：
  1. 接线（settings 注册/post-commit/等价自检复用 setup_project.verify_project）
  2. codegraph db 规模与语言构成（Java 索引成不成的第一判据：nodes/edges 数 + .java 文件数）
  3. conventions db 产出（按 source 计数 + drift 清单 + inferred 候选清单）
  4. inject 冒烟（双 hook，cwd payload）
  5. 环境（python/dl-workflow VERSION/git HEAD）

用法：python3 ~/.dl-workflow/bin/doctor.py [--project DIR] [--home DIR]
退出码：0=接线全过；1=有 ❌（诊断意义，非安装器）。
"""

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home() / ".dl-workflow"


def _run(cmd, cwd=None, timeout=30, stdin=None):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, input=stdin)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", f"{e.__class__.__name__}: {e}"


def _ck(name, ok, detail=""):
    print(f"  {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail else ""))
    return ok


def _sec(title):
    print(f"▸ {title}")


def _ro(db: Path) -> sqlite3.Connection | None:
    if not db.exists():
        return None
    try:
        return sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def _sec_wiring(project: Path, home: Path) -> bool:
    _sec("1. 接线")
    ok = True
    sp = home / "scripts" / "setup" / "setup_project.py"
    if sp.exists():
        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location("setup_project", sp)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            checks = mod.verify_project(project, home)
        except Exception as e:  # 目标机 setup_project 损坏也不拖垮整份报告
            return _ck("setup_project 加载/自检", False, f"{e.__class__.__name__}: {str(e)[:100]}")
        for name, cok, detail in checks:
            ok &= _ck(name, cok, detail)
    else:
        ok &= _ck("setup_project.py 存在", False, str(sp))
    return ok


def _sec_codegraph(project: Path) -> bool:
    _sec("2. codegraph db（索引质量判据）")
    db = project / ".codegraph" / "codegraph.db"
    conn = _ro(db)
    if conn is None:
        return _ck(".codegraph/codegraph.db", False, "缺失（先 codegraph index 或重跑 --project）")
    ok = True
    try:
        files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        java = conn.execute("SELECT COUNT(*) FROM nodes WHERE file_path LIKE '%.java'").fetchone()[0]
        kinds = conn.execute("SELECT kind, COUNT(*) FROM edges GROUP BY kind ORDER BY 2 DESC LIMIT 5").fetchall()
        idx = conn.execute("SELECT MAX(indexed_at) FROM files").fetchone()[0]
        age = ""
        if idx:
            age_h = (time.time() - idx / 1000) / 3600
            age = f"（{age_h:.0f}h 前索引）"
        ok &= _ck("规模", files > 0, f"files={files} nodes={nodes} edges={edges}{age}")
        jrc, jout, _ = _run(["git", "ls-files", "--", "*.java"], cwd=project)
        has_java = jrc == 0 and bool(jout)
        if not has_java:
            print("  ○ Java 索引 — N/A（非 Java 项目）")
        elif java > 0:
            ok &= _ck("Java 索引", True, f"java nodes={java}")
        else:
            ok &= _ck("Java 索引", False, "项目含 .java 但 0 个 .java 节点——Java 未进索引？")
        print(f"  top edge kinds: {', '.join(f'{k}×{c}' for k, c in kinds) or '(无)'}")
    except sqlite3.Error as e:
        ok &= _ck("db 查询", False, str(e)[:120])
    finally:
        conn.close()
    return ok


def _sec_conventions(project: Path) -> bool:
    _sec("3. conventions db（蒸馏产出）")
    db = project / ".conventions" / "conventions.db"
    conn = _ro(db)
    if conn is None:
        return _ck(".conventions/conventions.db", False, "缺失（重跑 mine_conventions 或 commit 触发）")
    ok = True
    try:
        total = conn.execute("SELECT COUNT(*) FROM conventions").fetchone()[0]
        by_src = conn.execute(
            "SELECT source, COUNT(*) FROM conventions GROUP BY source").fetchall()
        print(f"  共 {total} 条：" + ", ".join(f"{s}×{n}" for s, n in by_src))
        for s, st, dr in conn.execute(
                "SELECT subject, statement, drift FROM conventions WHERE drift=1"):
            print(f"  ⚠️ DRIFT {s} :: {st[:100]}")
        for s, st in conn.execute(
                "SELECT subject, statement FROM conventions WHERE source='inferred' LIMIT 5"):
            print(f"  🔍 候选 {s} :: {st[:100]}")
        ok &= _ck("产出", total > 0, f"{total} 条")
    except sqlite3.Error as e:
        ok &= _ck("db 查询", False, str(e)[:120])
    finally:
        conn.close()
    return ok


def _sec_inject(project: Path, home: Path) -> bool:
    _sec("4. inject 冒烟")
    ok = True
    payload = json.dumps({"prompt": "doctor 自检", "cwd": str(project)})
    for name in ("codegraph_inject.py", "conventions_inject.py"):
        rc, out, err = _run(
            [sys.executable, str(home / "hooks" / name)], cwd=project, timeout=20, stdin=payload)
        injected = "additionalContext" in out
        ok &= _ck(f"{name}", rc == 0,
                  "有注入" if injected else ("无注入（可接受：无命中/无漂移/无候选）" if rc == 0 else err[:100]))
    return ok


def _sec_env(home: Path) -> None:
    _sec("5. 环境")
    ver = (home / "VERSION").read_text(encoding="utf-8").strip() if (home / "VERSION").exists() else "?"
    rc, head, _ = _run(["git", "rev-parse", "--short", "HEAD"], cwd=home)
    print(f"  python {sys.version.split()[0]} | dl-workflow v{ver} | HEAD {head if rc == 0 else '?'}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="dl setup 远程接入一键诊断报告")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--home", type=Path, default=HOME)
    args = parser.parse_args(argv)
    project = args.project.resolve()

    print(f"═══ dl doctor ═══ project={project}")
    oks = [
        _sec_wiring(project, args.home),
        _sec_codegraph(project),
        _sec_conventions(project),
        _sec_inject(project, args.home),
    ]
    _sec_env(args.home)
    print("═══ 结束：把完整输出贴回维护者即可 ═══")
    return 0 if all(oks) else 1


if __name__ == "__main__":
    sys.exit(main())
