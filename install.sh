#!/bin/bash
# dl-workflow install.sh
# copy 1 skill / 1 output-style / 1 command 到 ~/.claude/（hooks 不 copy，settings 直引源）
# 合并 ~/.claude/settings.json 的 hook 注册（用户级只 codegraph 两个；
#   并幂等摘除历史误注册的 workflow_phase/advance/step_fence——它们只属 per-wf settings）
# 追写 ~/.bashrc 的 dl 函数（工作流入口，若未安装）
#
# 幂等：连续跑两次结果一致。冲突文件备份到 ~/.claude/.dl-workflow-backup/<ts>/。

set -euo pipefail

# ---------- 路径 ----------
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_HOME="$HOME/.claude"
BACKUP_DIR="$CLAUDE_HOME/.dl-workflow-backup/$(date +%Y%m%d-%H%M%S)"
BASHRC="$HOME/.bashrc"

# ---------- 前置检查 ----------
check_deps() {
  command -v python3 >/dev/null || { echo "✗ 缺 python3" >&2; exit 1; }
  command -v git >/dev/null || { echo "✗ 缺 git" >&2; exit 1; }
  # dl-lib.sh 用 declare -A（bash ≥ 4）
  if [ "${BASH_VERSINFO[0]}" -lt 4 ]; then
    echo "✗ 需要 bash ≥ 4（当前 $BASH_VERSION，dl-lib.sh 用 declare -A）" >&2
    exit 1
  fi
  echo "✓ 依赖检查通过（python3, git, bash $BASH_VERSION）"
}

# ---------- copy 文件（冲突则备份原文件） ----------
copy_with_backup() {
  local src="$1" dst="$2"
  if [ -e "$dst" ]; then
    # 已存在且内容相同 -> 跳过（幂等）
    if cmp -s "$src" "$dst"; then
      return 0
    fi
    # 内容不同 -> 备份
    mkdir -p "$BACKUP_DIR/$(dirname "${dst#$CLAUDE_HOME/}")"
    cp -p "$dst" "$BACKUP_DIR/${dst#$CLAUDE_HOME/}"
    echo "  ↺ 备份冲突: $dst -> $BACKUP_DIR/${dst#$CLAUDE_HOME/}"
  fi
  mkdir -p "$(dirname "$dst")"
  cp -p "$src" "$dst"
}

install_files() {
  echo "▸ 复制文件到 $CLAUDE_HOME/"
  # hooks 不 copy：直接引用源 ~/.dl-workflow/hooks/*.py（settings.json 里写 ~ 路径，
  # shell 执行时展开）。改 hook 后 git pull 即生效，无同步副本开销。
  # 只 copy Claude Code 硬编码加载路径的文件（skills/output-styles/commands）。
  # skill（整个子目录，含 references/ 按需参考文件——SKILL.md 已拆瘦路由+重型参考外置）
  mkdir -p "$CLAUDE_HOME/skills/workflow-creation/references"
  copy_with_backup "$SRC_DIR/skills/workflow-creation/SKILL.md" "$CLAUDE_HOME/skills/workflow-creation/SKILL.md"
  for f in "$SRC_DIR/skills/workflow-creation/references/"*.md; do
    copy_with_backup "$f" "$CLAUDE_HOME/skills/workflow-creation/references/$(basename "$f")"
  done
  # output-style
  copy_with_backup "$SRC_DIR/output-styles/workflow.md" "$CLAUDE_HOME/output-styles/workflow.md"
  # command
  copy_with_backup "$SRC_DIR/commands/dl.md" "$CLAUDE_HOME/commands/dl.md"
  echo "✓ 文件复制完成（hooks 不 copy，settings.json 直接引用 ~/.dl-workflow/hooks/）"
}

# ---------- 合并 ~/.claude/settings.json 的 hooks ----------
# 用 python3 读写 JSON（避 jq 依赖）。已注册的 command 跳过；缺失的 append。
merge_settings() {
  echo "▸ 合并 $CLAUDE_HOME/settings.json"
  local settings="$CLAUDE_HOME/settings.json"
  # 备份现有 settings.json
  if [ -f "$settings" ] && ! grep -q "workflow_phase.py\|codegraph_gate.py" "$settings" 2>/dev/null; then
    mkdir -p "$BACKUP_DIR"
    cp -p "$settings" "$BACKUP_DIR/settings.json"
    echo "  ↺ 备份现有 settings.json -> $BACKUP_DIR/settings.json"
  fi

  python3 - "$settings" <<'PY'
import json, sys, os

settings_path = sys.argv[1]
# hooks 不 copy，直接引用源 ~/.dl-workflow/hooks/（~ 在 shell 执行时展开）
hooks_src = "~/.dl-workflow/hooks"

if os.path.exists(settings_path):
    with open(settings_path, encoding="utf-8") as f:
        try:
            settings = json.load(f)
        except json.JSONDecodeError:
            print(f"✗ {settings_path} 不是合法 JSON，abort", file=sys.stderr)
            sys.exit(1)
else:
    settings = {}

# dl-workflow 用户级注册 codegraph 门禁（H15）+ design-first 门禁（跨项目通用）。
# design_gate/design_audit：本会话改第 2 个不同 .py 源码文件前须先写
# designs/*.md（H8 design-first 机械闸门；工作流会话跳过——有自己的 design 流程）。
# workflow_phase / workflow_advance / workflow_step_fence 是工作流会话专属，
# 只由 per-wf settings.json 注册（dl-lib.sh wf_write_settings）——
# 用户级注册会让任何 cwd 落进 worktree 的会话被工作流门控接管
#（2026-07-30 实测：主仓审计会话 cd 进 worktree 后 Stop hook 误判 engage_block）。
DLWF_HOOKS = {
    "PreToolUse": [
        {"matcher": "Edit|Write", "hooks": [{"type": "command", "command": f"python3 {hooks_src}/codegraph_gate.py"}]},
        {"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": f"python3 {hooks_src}/design_gate.py"}]},
    ],
    "PostToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": f"python3 {hooks_src}/codegraph_audit.py"}]},
        {"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": f"python3 {hooks_src}/design_audit.py"}]},
    ],
}

# 历史版本误注册到用户级的工作流 hook：重跑 install.sh 时自动摘除（幂等清理，
# 其他机器 git pull + install.sh 即修复；per-wf settings 里的注册不受影响）。
DLWF_HOOKS_REMOVE = [
    f"python3 {hooks_src}/workflow_phase.py",
    f"python3 {hooks_src}/workflow_advance.py",
    f"python3 {hooks_src}/workflow_step_fence.py",
]

hooks = settings.setdefault("hooks", {})

def cmd_exists(event_groups, target_cmd):
    """已注册过（匹配 command 字符串）返回 True。"""
    for group in event_groups:
        for h in group.get("hooks", []):
            if h.get("command") == target_cmd:
                return True
    return False

added = 0
for event, groups in DLWF_HOOKS.items():
    existing = hooks.setdefault(event, [])
    for new_group in groups:
        # 只看 hooks 内的 command 是否已有
        new_cmd = new_group["hooks"][0]["command"]
        if not cmd_exists(existing, new_cmd):
            existing.append(new_group)
            added += 1

# 摘除历史误注册的工作流 hook（按 command 匹配；组摘空则整组移除，事件摘空则删事件键）
removed = 0
for event in list(hooks.keys()):
    groups = hooks[event]
    for group in list(groups):
        before = len(group.get("hooks", []))
        group["hooks"] = [h for h in group.get("hooks", []) if h.get("command") not in DLWF_HOOKS_REMOVE]
        removed += before - len(group["hooks"])
        if not group["hooks"]:
            groups.remove(group)
    if not groups:
        del hooks[event]

with open(settings_path, "w", encoding="utf-8") as f:
    json.dump(settings, f, ensure_ascii=False, indent=2)

print(f"  merged {added} 个 hook（已存在的跳过）；摘除历史误注册 {removed} 个")
PY
  echo "✓ settings.json 合并完成"
}

# ---------- 追写 ~/.bashrc 的 dl 函数 ----------
# 用 BEGIN/END dl-workflow 段落做幂等标记。
# dl 是工作流入口，独立于 ac-ark/claude（不碰用户的 provider shim）。
# 用法：dl <name> [--resume|--phase <p>|--base <ref>|--done]
#      dl list
install_bashrc() {
  echo "▸ 检查 $BASHRC"
  if grep -q "# BEGIN dl-workflow" "$BASHRC" 2>/dev/null; then
    echo "  ↺ 已有 dl-workflow 段落，跳过"
    return 0
  fi

  # 备份
  mkdir -p "$BACKUP_DIR"
  cp -p "$BASHRC" "$BACKUP_DIR/bashrc" 2>/dev/null || touch "$BASHRC"

  # 检查 dl 是否已被占用（alias/函数/命令）
  local dl_conflict=0
  if grep -qE '^(dl|function dl|dl\(\))|alias dl=' "$BASHRC" 2>/dev/null; then
    dl_conflict=1
  fi

  cat >> "$BASHRC" <<'BASHRC_EOF'

# BEGIN dl-workflow  (installed by ~/.dl-workflow/install.sh)
# 5 阶段工作流入口。真源：~/.dl-workflow/scripts/workflow/dl-launch.sh
#
# 两种入口（都拦 --dl 参数转交 launcher）：
#   dl <name>              # 独立 dl 函数（install.sh 装）
#   ac-ark --dl <name>     # 你的 provider 函数拦 --dl（在 ac-ark 里加，见 README）
#
# provider env 由调用方 shell 继承：launcher 子进程 exec 原生 claude，
# 自动带上当前 shell 的 ANTHROPIC_* env。
#   - ac-ark --dl foo: ac-ark 已 export ark env，launcher 起 claude 带 ark ✓
#   - dl foo: 用当前 shell env（默认或你 export 的）
#
# 用法：
#   <入口> <name>              新建工作流（停在「理解和求证问题」）
#   <入口> <name> --resume     续接
#   <入口> <name> --phase <p>  跳到某阶段
#   <入口> <name> --base <ref> 从指定 ref 建分支
#   <入口> <name> --debug      debug 落盘 per-wf 目录（cc_debug.log + cc_sdk.log）
#   <入口> <name> --done       归档（删 worktree+分支+元数据）
#   <入口> list                列举所有工作流

export DL_WF_HOME="$HOME/.dl-workflow"

# launcher 调用核心：转交 dl-launch.sh（加 --workflow 前缀）
_dl_launch() {
  "$DL_WF_HOME/scripts/workflow/dl-launch.sh" --workflow "$@"
}

# dl 命令：独立入口
dl() {
  [ $# -ge 1 ] || { echo "用法: dl <name> [--resume|--phase <p>|--base <ref>|--debug|--done] | list" >&2; return 1; }
  _dl_launch "$@"
}
# END dl-workflow
BASHRC_EOF

  if [ "$dl_conflict" = "1" ]; then
    echo "  ⚠ 检测到 ~/.bashrc 已有 dl 定义。dl-workflow 的 dl 函数定义在后，会覆盖。"
  fi
  echo "✓ ~/.bashrc 已追加 dl-workflow 段落（dl 函数 + _dl_launch）"
  echo "  入口：dl <name> | ac-ark --dl <name>（后者需在 ac-ark 里加 --dl 拦截，见 README）"
}

# ---------- 主 ----------
main() {
  echo "═══ dl-workflow install ═══"
  echo "  源目录: $SRC_DIR"
  echo "  目标:   $CLAUDE_HOME/"
  echo
  check_deps
  install_files
  merge_settings
  install_bashrc
  echo
  echo "═══ 完成 ═══"
  if [ -d "$BACKUP_DIR" ]; then
    echo "  备份在: $BACKUP_DIR/"
  fi
  echo "  下一步: exec bash 或新开终端，然后 dl <name> 建工作流"
}

main "$@"
