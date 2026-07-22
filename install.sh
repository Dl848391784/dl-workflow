#!/bin/bash
# dl-workflow install.sh
# copy 4 hooks / 1 skill / 1 output-style / 1 command 到 ~/.claude/
# 合并 ~/.claude/settings.json 的 hook 注册
# 追写 ~/.bashrc 的 ac-ark 函数（若未安装）
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
  # wf-lib.sh 用 declare -A（bash ≥ 4）
  if [ "${BASH_VERSINFO[0]}" -lt 4 ]; then
    echo "✗ 需要 bash ≥ 4（当前 $BASH_VERSION，wf-lib.sh 用 declare -A）" >&2
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
  # hooks
  for f in workflow_phase.py workflow_advance.py codegraph_gate.py codegraph_audit.py; do
    copy_with_backup "$SRC_DIR/hooks/$f" "$CLAUDE_HOME/hooks/$f"
  done
  # skill（整个子目录）
  mkdir -p "$CLAUDE_HOME/skills/workflow-creation"
  copy_with_backup "$SRC_DIR/skills/workflow-creation/SKILL.md" "$CLAUDE_HOME/skills/workflow-creation/SKILL.md"
  # output-style
  copy_with_backup "$SRC_DIR/output-styles/workflow.md" "$CLAUDE_HOME/output-styles/workflow.md"
  # command
  copy_with_backup "$SRC_DIR/commands/wf.md" "$CLAUDE_HOME/commands/wf.md"
  echo "✓ 文件复制完成"
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

  python3 - "$settings" "$CLAUDE_HOME/hooks" <<'PY'
import json, sys, os

settings_path = sys.argv[1]
hooks_dir = sys.argv[2]

if os.path.exists(settings_path):
    with open(settings_path, encoding="utf-8") as f:
        try:
            settings = json.load(f)
        except json.JSONDecodeError:
            print(f"✗ {settings_path} 不是合法 JSON，abort", file=sys.stderr)
            sys.exit(1)
else:
    settings = {}

# dl-workflow 要注册的 hooks
DLWF_HOOKS = {
    "PreToolUse": [
        {"matcher": "Edit|Write", "hooks": [{"type": "command", "command": f"python3 {hooks_dir}/codegraph_gate.py"}]}
    ],
    "PostToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": f"python3 {hooks_dir}/codegraph_audit.py"}]}
    ],
    "UserPromptSubmit": [
        {"hooks": [{"type": "command", "command": f"python3 {hooks_dir}/workflow_phase.py"}]}
    ],
    "Stop": [
        {"hooks": [{"type": "command", "command": f"python3 {hooks_dir}/workflow_advance.py"}]}
    ],
}

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

with open(settings_path, "w", encoding="utf-8") as f:
    json.dump(settings, f, ensure_ascii=False, indent=2)

print(f"  merged {added} 个 hook（已存在的跳过）")
PY
  echo "✓ settings.json 合并完成"
}

# ---------- 追写 ~/.bashrc 的 ac-ark 函数 ----------
# 用 BEGIN/END dl-workflow 段落做幂等标记。
install_bashrc() {
  echo "▸ 检查 $BASHRC"
  if grep -q "# BEGIN dl-workflow" "$BASHRC" 2>/dev/null; then
    echo "  ↺ 已有 dl-workflow 段落，跳过"
    return 0
  fi

  # 备份
  mkdir -p "$BACKUP_DIR"
  cp -p "$BASHRC" "$BACKUP_DIR/bashrc" 2>/dev/null || touch "$BASHRC"

  # 检查是否已存在 ac-ark 函数（旧手工版）
  local has_old_ac_ark=0
  if grep -qE '^(function ac-ark|ac-ark\(\))' "$BASHRC" 2>/dev/null; then
    has_old_ac_ark=1
  fi

  cat >> "$BASHRC" <<'BASHRC_EOF'

# BEGIN dl-workflow  (installed by ~/.dl-workflow/install.sh)
# 5 阶段工作流 launcher shim。真源：~/.dl-workflow/scripts/workflow/wf-launch.sh
# 用法：ac-ark --workflow <name>[--resume|--phase <p>|--base <ref>|--done|list]
#
# 若你已有自定义 ac-ark 函数（如设 ANTHROPIC_BASE_URL 之类），本段只加 --workflow shim；
# 请手工把 shim 逻辑并入你的 ac-ark 定义，或删旧的 ac-ark 只留本段。

export DL_WF_HOME="$HOME/.dl-workflow"

# dl-workflow 提供的 shim：识别 --workflow 参数走 launcher
if ! declare -F ac-ark >/dev/null 2>&1; then
  # 无自定义 ac-ark，dl-workflow 提供一个简版
  ac-ark() {
    if [ "$1" = "--workflow" ]; then
      "$DL_WF_HOME/scripts/workflow/wf-launch.sh" "$@"
      return $?
    fi
    claude "$@"
  }
fi
# END dl-workflow
BASHRC_EOF

  if [ "$has_old_ac_ark" = "1" ]; then
    echo "  ⚠ 检测到已有 ac-ark 函数（可能是你自定义的 provider shim）。"
    echo "    dl-workflow 段落只在无 ac-ark 时提供简版；你的自定义 ac-ark 保留。"
    echo "    请手工在你的 ac-ark 里加：if [ \"\$1\" = \"--workflow\" ]; then \"\$DL_WF_HOME/scripts/workflow/wf-launch.sh\" \"\$@\"; return \$?; fi"
  fi
  echo "✓ ~/.bashrc 已追加 dl-workflow 段落（export DL_WF_HOME + ac-ark shim）"
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
  echo "  下一步: exec bash 或新开终端，然后 ac-ark --workflow <name> 建工作流"
}

main "$@"
