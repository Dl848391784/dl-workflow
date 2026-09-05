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
    existed = hook.exists()
    hook.write_text(POST_COMMIT_BLOCK)
    hook.chmod(0o755)
    return "patched" if existed else "created"


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
