#!/usr/bin/env python3
"""setup_project - dl setup 项目级接线（designs/setup-installer-design.md §setup 脚本结构 P1）。

四步：④ codegraph init+首次 index ⑤ post-commit 幂等补丁 ⑥ 项目 settings.json 合并两条
UserPromptSubmit inject hook（绝对路径引用 ~/.dl-workflow/hooks/）⑦ 首次蒸馏（best-effort）。
每步打印 installed / already-ok / failed 三态；硬失败退出 1。

用法：python3 scripts/setup/setup_project.py --project DIR [--home DIR] [--skip-index] [--skip-distill]
"""

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


POST_COMMIT_MARK = "mine_conventions.py"
INJECT_HOOKS = ("codegraph_inject.py", "conventions_inject.py")
POST_COMMIT_BLOCK = """#!/bin/sh
# Auto-sync codegraph + re-mine conventions after each commit (background, non-blocking)
codegraph sync >/dev/null 2>&1 &
$(command -v python3 || command -v python) "{home}/bin/mine_conventions.py" >/dev/null 2>&1 &
exit 0
"""


def patch_post_commit(project: Path, home: Path) -> str:
    """post-commit 补丁：无则建、缺 mine_conventions 行则整块替换、齐则跳过。

    home 变化（如 worktree -> ~/.dl-workflow 收口）时：mark 在但内嵌路径已死
    -> 原地重写返回 "upgraded"，不留死注册。

    写绝对路径（home 由 CLI 参数解析而来）——git 调 post-commit 时不继承
    $DLWF_HOME，相对/变量引用会静默失效，故禁环境变量引用。
    """
    hook = project / ".git" / "hooks" / "post-commit"
    if hook.exists():
        text = hook.read_text(encoding="utf-8", errors="replace")
        if POST_COMMIT_MARK in text:
            if f'"{home}/bin/mine_conventions.py"' in text:
                return "already-ok"
            hook.write_text(POST_COMMIT_BLOCK.format(home=home))
            hook.chmod(0o755)
            return "upgraded"
    existed = hook.exists()
    hook.write_text(POST_COMMIT_BLOCK.format(home=home))
    hook.chmod(0o755)
    return "patched" if existed else "created"


def merge_project_settings(project: Path, home: Path) -> dict:
    """项目 .claude/settings.json 幂等合并两条 inject hook（按 hook 脚本 basename 判重）。

    basename 判重：--home 变化（worktree -> ~/.dl-workflow 收口）时旧 command 串
    永不匹配精确判重，会无限累积死 hook——按 basename 命中且串不同则原地替换（upgraded）。
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
    canonical = [
        ("codegraph_inject.py", f'$(command -v python3 || command -v python) "{home}/hooks/codegraph_inject.py"'),
        ("conventions_inject.py", f'$(command -v python3 || command -v python) "{home}/hooks/conventions_inject.py"'),
    ]
    hooks = settings.setdefault("hooks", {})
    groups = hooks.setdefault("UserPromptSubmit", [{"hooks": []}])
    if not groups:
        # 键在但组摘空（strip 手工接线后的典型状态）——setdefault 默认值只对
        # 缺键生效，空列表需自建承载组（factor 仓自举实爆 IndexError）
        groups.append({"hooks": []})
    added = upgraded = kept = 0
    for basename, cmd in canonical:
        matches = [
            h
            for g in groups
            for h in g.get("hooks", [])
            if str(h.get("command", "")).strip('"').endswith(basename)
        ]
        if matches:
            if matches[0].get("command") == cmd:
                kept += 1
            else:
                # 原地升级：旧 home 的注册替换为 canonical，同 basename 死重复一并摘除
                matches[0]["command"] = cmd
                upgraded += 1
            for dup in matches[1:]:
                for g in groups:
                    if dup in g.get("hooks", []):
                        g["hooks"].remove(dup)
        else:
            groups[0]["hooks"].append({"type": "command", "command": cmd})
            added += 1
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"added": added, "upgraded": upgraded, "kept": kept}


def ensure_codegraph_index(project: Path) -> int:
    """codegraph init + index + 过期索引自动刷新（sync）。返回分层：
    0=ok（index/sync 完成或 db 新鲜），1=warn（非 git / CLI 缺失 / sync 失败——
    仅打印警告不阻断），2=hard fail（init 执行但失败）。"""
    if not (project / ".git").exists():
        print("  ⚠ 非 git 仓库，跳过 codegraph index")
        return 1
    if subprocess.run(["codegraph", "--version"], capture_output=True).returncode != 0:
        print("  ⚠ codegraph CLI 不可用，跳过 index（H15 门禁不生效）")
        return 1
    db = project / ".codegraph" / "codegraph.db"
    if db.exists():
        # db 存在也须查新鲜度：过期（>INDEX_STALE_HOURS）自动 codegraph sync——
        # setup 承诺「装完效果一样」，放行 48 天旧索引违背承诺（实爆：Java 项目接入
        # 吃到 1151h 前索引）。
        age_h = _db_age_hours(db)
        if age_h is None:
            print("  ↺ .codegraph/codegraph.db 新鲜度不可判，跳过 index")
            return 0
        if age_h <= INDEX_STALE_HOURS:
            print(f"  ↺ .codegraph/codegraph.db 新鲜（{age_h:.0f}h 前索引），跳过 index")
            return 0
        print(f"▸ 索引 {age_h:.0f}h 前（>{INDEX_STALE_HOURS}h），自动 codegraph sync 刷新…")
        sync = subprocess.run(["codegraph", "sync"], cwd=project, capture_output=True, text=True)
        if sync.returncode != 0:
            print(f"  ⚠ codegraph sync 失败: {sync.stderr.strip()[:200]}（旧索引保留）")
            return 1
        print("✓ 索引已刷新")
        return 0
    proc = subprocess.run(["codegraph", "init"], cwd=project, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"  ✗ codegraph init 失败: {proc.stderr.strip()}")
        return 2
    print("✓ codegraph index 完成")
    return 0


INDEX_STALE_HOURS = 24


def _db_age_hours(db: Path) -> float | None:
    """codegraph db 的索引龄（files.indexed_at 最大值的距今小时数）；不可判返回 None。"""
    import sqlite3 as _sqlite3
    import time as _time

    try:
        conn = _sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        row = conn.execute("SELECT MAX(indexed_at) FROM files").fetchone()
        conn.close()
    except _sqlite3.Error:
        return None
    if not row or not row[0]:
        return None
    return (_time.time() - row[0] / 1000) / 3600


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
      # 单引号标量内嵌 ' 需按 YAML 规范翻倍转义（''），解析结果仍为 ["''"]
      fstring_regex: 'logger\\.(debug|info|warning|error|critical)\\(\\s*f["''"]'
      lazy_regex: 'logger\\.(debug|info|warning|error|critical)\\(\\s*["''][^"''\\n]*%[srda]'
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
      # 注意：glob 不跨目录层级——含子目录用 "scripts/**/*.py"（fnmatch 语义见 pathlib.PurePath.match）
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


def first_distill(project: Path, home: Path) -> int:
    """首次蒸馏（best-effort：失败仅警告，不阻断）。"""
    script = home / "bin" / "mine_conventions.py"
    if not script.exists():
        print("  ⚠ 蒸馏器缺失，跳过")
        return 1
    proc = subprocess.run(
        [sys.executable, str(script), "--root", str(project), "--out", str(project / ".conventions" / "conventions.db")],
        cwd=project, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(f"  ⚠ 首次蒸馏失败: {proc.stderr.strip()[:200]}")
        return 1
    print(f"✓ 首次蒸馏完成（{proc.stdout.strip()}）")
    return 0


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
    registered = ok
    hook = project / ".git" / "hooks" / "post-commit"
    text = hook.read_text(encoding="utf-8", errors="replace") if hook.exists() else ""
    ok = "mine_conventions.py" in text and "codegraph sync" in text
    checks.append(("post-commit 双后台任务", ok, "ok" if ok else "缺 codegraph sync/mine_conventions"))
    payload = json.dumps({"prompt": "dl setup verify", "cwd": str(project)})
    for name in INJECT_HOOKS:
        if not registered:
            # 未注册时冒烟没有意义（hook 好不好与装没装是两件事）——按未接线记 ❌
            checks.append((f"inject 冒烟 {name}", False, "settings 未注册，跳过冒烟"))
            continue
        try:
            proc = subprocess.run(
                [sys.executable, str(home / "hooks" / name)], input=payload,
                capture_output=True, text=True, cwd=project, timeout=15)
        except (subprocess.TimeoutExpired, OSError) as e:
            checks.append((f"inject 冒烟 {name}", False, f"无法执行: {e.__class__.__name__}"))
            continue
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


def _filter_skipped(checks, skip_index, skip_distill):
    """--skip-index/--skip-distill 场景：被跳过的产物（两个 db）不纳入判定——verify 与接线模式两路一致。"""
    out = []
    for name, ok, detail in checks:
        if skip_index and "codegraph db" in name:
            continue
        if skip_distill and "conventions db" in name:
            continue
        out.append((name, ok, detail))
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="dl setup 项目级接线（designs/setup-installer-design.md）")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--home", type=Path, default=Path.home() / ".dl-workflow")
    parser.add_argument("--skip-index", action="store_true")
    parser.add_argument("--skip-distill", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    project = args.project.resolve()

    if args.verify:
        checks = _filter_skipped(verify_project(project, args.home), args.skip_index, args.skip_distill)
        return _print_verify(checks)

    print(f"═══ dl setup --project {project} ═══")
    fails = 0
    if not args.skip_index:
        rc = ensure_codegraph_index(project)
        if rc == 2:
            fails += 1
    status = patch_post_commit(project, args.home)
    print(f"{'✓' if status != 'failed' else '✗'} post-commit: {status}")
    merged = merge_project_settings(project, args.home)
    print(
        f"✓ settings.json 合并: added={merged['added']} "
        f"upgraded={merged['upgraded']} kept={merged['kept']}"
    )
    cy = ensure_conventions_yaml(project)
    print(f"✓ conventions.yaml: {cy}")
    if not args.skip_distill:
        first_distill(project, args.home)  # best-effort，不计 fails
    vrc = _print_verify(_filter_skipped(verify_project(project, args.home), args.skip_index, args.skip_distill))
    if vrc != 0:
        print("  ⚠ 等价自检有 ❌（不阻断接线，见上方清单）")
    print("═══ 完成（⚠ 项不阻断，详见上方输出）═══")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
