#!/usr/bin/env python3
"""setup_project - dl setup 项目级接线（designs/setup-installer-design.md §setup 脚本结构 P1）。

四步：④ codegraph init+首次 index ⑤ post-commit 幂等补丁 ⑥ 项目 settings.json 合并两条
UserPromptSubmit inject hook（绝对路径引用 ~/.dl-workflow/hooks/）⑦ 首次蒸馏（best-effort）。
每步打印 installed / already-ok / failed 三态；硬失败退出 1。

用法：python3 scripts/setup/setup_project.py --project DIR [--home DIR] [--skip-index] [--skip-distill]
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


POST_COMMIT_MARK = "mine_conventions.py"
POST_COMMIT_BLOCK = """#!/bin/sh
# Auto-sync codegraph + re-mine conventions after each commit (background, non-blocking)
codegraph sync >/dev/null 2>&1 &
python3 "{home}/bin/mine_conventions.py" >/dev/null 2>&1 &
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
        ("codegraph_inject.py", f'python3 "{home}/hooks/codegraph_inject.py"'),
        ("conventions_inject.py", f'python3 "{home}/hooks/conventions_inject.py"'),
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
    """codegraph init + index。返回分层：0=ok（index 完成或 db 已存在），
    1=warn（非 git 仓库 / CLI 缺失——仅打印警告不阻断），2=hard fail（init 执行但失败）。"""
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
        return 2
    print("✓ codegraph index 完成")
    return 0


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
    print("═══ 完成（⚠ 项不阻断，详见上方输出）═══")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
