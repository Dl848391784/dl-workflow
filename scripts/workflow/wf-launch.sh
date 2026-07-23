#!/bin/bash
# wf-launch.sh - 工作流 launcher：建/续 worktree + state + session，起 claude TUI
# 真源：designs/workflow-system-design.md
# 被 ~/.bashrc 的 dl 调用（不设 provider env，继承当前 shell env）。
#
# 用法：
#   dl <name>              新建/续工作流（停在 understand）
#   dl <name> --resume     续已存在工作流（恢复 session + 当前阶段）
#   dl <name> --phase <p>  直接跳到某阶段
#   dl <name> --base <ref> 从指定 ref 建分支（默认当前 HEAD）
#   dl list                列举所有工作流
#   dl <name> --done       归档工作流（删 worktree，保留元数据）

set -euo pipefail

LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./wf-lib.sh
. "$LIB_DIR/wf-lib.sh"

usage() {
  sed -n '3,12p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

# ---------- 解析参数 ----------
[ $# -ge 1 ] || usage 1
[ "$1" = "--workflow" ] || { echo "wf-launch: 第一个参数须为 --workflow" >&2; exit 1; }
shift

[ $# -ge 1 ] || usage 1
# help 在 name 之前可触发
[ "$1" = "-h" ] || [ "$1" = "--help" ] && usage 0
WF_NAME="$1"; shift

# list 是特殊子命令（不进会话）
if [ "$WF_NAME" = "list" ]; then
  wf_list
  exit 0
fi

# 校验 name（分支名安全：仅 [a-z0-9_-]）
if ! echo "$WF_NAME" | grep -qE '^[a-z0-9][a-z0-9_-]{0,63}$'; then
  echo "wf-launch: 非法工作流名 '$WF_NAME'（仅小写字母/数字/连字符/下划线，≤64）" >&2
  exit 1
fi

WF_RESUME=0
WF_PHASE_OVERRIDE=""
WF_BASE=""
WF_DONE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --resume) WF_RESUME=1;;
    --phase) WF_PHASE_OVERRIDE="$2"; shift;;
    --base)  WF_BASE="$2"; shift;;
    --done)  WF_DONE=1;;
    -h|--help) usage 0;;
    *) echo "wf-launch: 未知参数 '$1'" >&2; usage 1;;
  esac
  shift
done

# 必须在 repo 内
WF_REPO_TOPLEVEL="$(git -C "$WF_REPO_ROOT" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$WF_REPO_TOPLEVEL" ]; then
  echo "wf-launch: 不在 git 仓库内（$WF_REPO_ROOT）。请在 repo 内运行。" >&2
  exit 1
fi

STATE_FILE="$WF_META_ROOT/$WF_NAME/state.json"
WORKTREE_PATH="$WF_WT_ROOT/$WF_NAME"
BRANCH="wf/$WF_NAME"

# ---------- --done：归档（彻底清理） ----------
if [ "$WF_DONE" = "1" ]; then
  if [ ! -f "$STATE_FILE" ]; then
    echo "wf-launch: 工作流 '$WF_NAME' 不存在。" >&2; exit 1
  fi
  echo "▸ 归档工作流 '$WF_NAME'（彻底清理）"
  git -C "$WF_REPO_ROOT" worktree remove --force "$WORKTREE_PATH" 2>/dev/null || true
  git -C "$WF_REPO_ROOT" branch -D "$BRANCH" 2>/dev/null || true
  rm -rf "$WF_META_ROOT/$WF_NAME"
  echo "  worktree + 分支 $BRANCH + 元数据 已删除。"
  exit 0
fi

# ---------- 新建 or 续 ----------
if [ -f "$STATE_FILE" ]; then
  # 已存在：续
  SESSION_ID=$(wf_state_get "$WF_NAME" session_id 2>/dev/null || echo "")
  WORKTREE_EXISTING=$(wf_state_get "$WF_NAME" worktree_path 2>/dev/null || echo "$WORKTREE_PATH")
  echo "▸ 续工作流 '$WF_NAME'（session=$SESSION_ID）"
  if [ ! -d "$WORKTREE_EXISTING" ]; then
    echo "  ⚠ worktree 缺失（$WORKTREE_EXISTING），重新 attach"
    git -C "$WF_REPO_ROOT" worktree add --force "$WORKTREE_PATH" "$BRANCH" 2>/dev/null \
      || git -C "$WF_REPO_ROOT" worktree add "$WORKTREE_PATH" -B "$BRANCH" 2>/dev/null \
      || { echo "  ✗ 无法重建 worktree" >&2; exit 1; }
  fi
  WORKTREE_PATH="$WORKTREE_EXISTING"
  WF_PHASE_OVERRIDE_SET=0
  # 续接时补 settings（若缺失，如旧工作流或手动删过）
  [ -f "$WF_META_ROOT/$WF_NAME/settings.json" ] || wf_write_settings "$WF_NAME"
else
  # 新建
  [ -z "$WF_BASE" ] && WF_BASE="$(git -C "$WF_REPO_ROOT" rev-parse --abbrev-ref HEAD)"
  echo "▸ 新建工作流 '$WF_NAME'"
  echo "  基线: $WF_BASE  分支: $BRANCH  worktree: $WORKTREE_PATH"
  mkdir -p "$WF_META_ROOT/$WF_NAME" "$WF_WT_ROOT"
  if git -C "$WF_REPO_ROOT" worktree list --porcelain | grep -q "^worktree $WORKTREE_PATH$"; then
    echo "  worktree 已存在，复用"
  else
    git -C "$WF_REPO_ROOT" worktree add "$WORKTREE_PATH" -B "$BRANCH" "$WF_BASE" \
      || { echo "  ✗ git worktree add 失败" >&2; exit 1; }
  fi
  # 生成 session id（uuidgen 不可用时用 /proc 降级；保证格式合法 uuid）
  if command -v uuidgen >/dev/null 2>&1; then
    SESSION_ID="$(uuidgen)"
  else
    SESSION_ID="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || python3 -c 'import uuid;print(uuid.uuid4())')"
  fi
  wf_state_init "$WF_NAME" "$SESSION_ID" "$WF_BASE" "$BRANCH" "$WORKTREE_PATH"
  wf_write_settings "$WF_NAME"
  echo "  session: $SESSION_ID"
fi

# 阶段跳转（--phase 或新建后默认 understand 已由 init 设置）
if [ -n "$WF_PHASE_OVERRIDE" ]; then
  idx=$(wf_phase_index "$WF_PHASE_OVERRIDE") || { echo "wf-launch: 非法阶段 '$WF_PHASE_OVERRIDE'" >&2; exit 1; }
  wf_state_set_phase "$WF_NAME" "$WF_PHASE_OVERRIDE" "manual-launch"
  echo "  阶段跳转: $(wf_phase_label "$WF_PHASE_OVERRIDE") [$idx/5]"
fi

CUR_PHASE=$(wf_state_get "$WF_NAME" phase)
CUR_IDX=$(wf_state_get "$WF_NAME" index)
echo "  当前阶段: $(wf_phase_label "$CUR_PHASE") [$CUR_IDX/5]"
echo "──────────────────────────────────────────────────────────"
echo "进入工作流（隔离 worktree）。/wf status 查看阶段，/wf next 推进。"
echo "──────────────────────────────────────────────────────────"

# ---------- 起 claude ----------
# settings：per-workflow settings 启用工作流 hook + output style（叠加在 project settings 上）
WF_SETTINGS="$WF_META_ROOT/$WF_NAME/settings.json"
# 若 settings 模板缺失，回退到不带 --settings（仍可用 hook 注入，但 output style 失效）
SETTINGS_ARGS=()
if [ -f "$WF_SETTINGS" ]; then
  SETTINGS_ARGS=(--settings "$WF_SETTINGS")
fi

# 阶段规则 append-system-prompt-file（若存在）
# dl-workflow 版本：phase-rules.md 与 wf-launch.sh 同目录（LIB_DIR = <dl-workflow>/scripts/workflow/），
# 不再从当前项目 $WF_REPO_ROOT/scripts/workflow/ 取（那里没有）。
PHASE_RULES_FILE="$LIB_DIR/phase-rules.md"
SYS_PROMPT_ARGS=()
if [ -f "$PHASE_RULES_FILE" ]; then
  SYS_PROMPT_ARGS=(--append-system-prompt-file "$PHASE_RULES_FILE")
fi

cd "$WORKTREE_PATH"

# launcher 始终 exec 原生 claude。provider env 由调用方在交互 shell 里 export
# （ac-ark --dl 时 ac-ark 函数已 export ark env；claude --dl / dl 时用默认或当前 shell env）。
# launcher 子进程继承父 shell env，故 claude 自动带上 provider 的 ANTHROPIC_* 配置。
# 不用 @provider 机制：provider 选择由「用哪个命令调」决定，不是 launcher 去 exec provider
# （provider 若是 bashrc 函数，launcher 子进程 exec 不到，会 not found）。

# resume：用钉死的 session_id 恢复；否则用 --session-id 钉死
if [ "$WF_RESUME" = "1" ] && [ -n "${SESSION_ID:-}" ]; then
  exec claude --resume "$SESSION_ID" "${SETTINGS_ARGS[@]}" "${SYS_PROMPT_ARGS[@]}" "$@"
else
  exec claude --session-id "$SESSION_ID" "${SETTINGS_ARGS[@]}" "${SYS_PROMPT_ARGS[@]}" "$@"
fi
