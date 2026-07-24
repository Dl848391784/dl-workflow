#!/bin/bash
# wf-cmd.sh - 工作流控制命令（被 /wf slash 命令调用）
# 真源：designs/workflow-system-design.md §3 / scripts/workflow/wf-lib.sh
#
# 用法：
#   wf-cmd.sh status                 查看当前阶段
#   wf-cmd.sh next                   推进到下一阶段（闸门阶段需先 gate）
#   wf-cmd.sh back                   回退到上一阶段
#   wf-cmd.sh jump <phase>           跳转到指定阶段
#   wf-cmd.sh gate                   闸门放行（understand->plan / plan->execute）
#   wf-cmd.sh done                   归档工作流（删 worktree，保留元数据）

set -euo pipefail

LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./wf-lib.sh
. "$LIB_DIR/wf-lib.sh"

# 从 cwd 推断当前工作流名（worktree 路径含 name）
resolve_name() {
  local cwd
  cwd="$(pwd)"
  local parts
  IFS='/' read -ra parts <<< "$cwd"
  local i
  for i in "${!parts[@]}"; do
    if [ "${parts[$i]}" = "worktrees" ] && [ $((i + 1)) -lt "${#parts[@]}" ]; then
      echo "${parts[$((i + 1))]}"
      return 0
    fi
  done
  return 1
}

NAME="$(resolve_name || true)"
if [ -z "$NAME" ]; then
  echo "✗ 当前不在工作流 worktree 内（cwd 不含 .claude/worktrees/<name>）。" >&2
  echo "  请在 dl <name> 启动的会话中使用 /wf。" >&2
  exit 1
fi

STATE_FILE="$WF_META_ROOT/$NAME/state.json"
if [ ! -f "$STATE_FILE" ]; then
  echo "✗ 工作流 '$NAME' 的 state.json 缺失（$STATE_FILE）。" >&2
  exit 1
fi

SUB="${1:-status}"
shift || true

cur_phase() { wf_state_get "$NAME" phase; }
cur_idx()   { wf_state_get "$NAME" index; }

# 进度展示由原生 TUI TaskList 组件负责（模型用 TaskCreate/TaskUpdate 建齐 9 项清单，
# 见 output-style 硬性要求 1）。wf-cmd.sh status 只输出元数据（阶段/闸门/分支/session/顺序）。
# banner-tree-design.md 记录了 checklist 兜底展示的历史设计（选项A：删兜底，只留 TUI）。

case "$SUB" in
  status)
    P="$(cur_phase)"
    G="$(wf_state_get "$NAME" gate)"
    BR="$(wf_state_get "$NAME" branch)"
    echo "═══ 工作流: $NAME ═══"
    echo "  当前阶段: $(wf_phase_label "$P") [$(cur_idx)/5]"
    echo "  闸门:  $G"
    echo "  分支:  $BR"
    echo "  worktree: $(wf_state_get "$NAME" worktree_path)"
    echo "  session:  $(wf_state_get "$NAME" session_id)"
    echo "  阶段顺序(英文，供 /wf jump): ${WF_PHASES[*]}"
    echo "  闸门后置: $WF_GATED_AFTER（这些阶段完成需 /wf gate 放行）"
    # §banner-tree-design + §orchestration v2：进度树给模型取阶段真值
    # （phase-rules 行 13 要求 status 取真值；旧 status 删了阶段显示致模型卡 Bash 循环）。
    # engine progress 读 state.json（含 sub_step_index + 当前子步骤 purpose），最准。
    if [ -f "$WF_ENGINE" ]; then
      echo ""
      python3 "$WF_ENGINE" progress "$NAME" --cwd "$(pwd)" 2>/dev/null || true
    fi
    ;;

  next)
    P="$(cur_phase)"
    if [ "$P" = "evolution" ]; then
      echo "✗ 已在终末阶段（进化），无下一阶段。用 /wf done 归档。" >&2
      exit 1
    fi
    # 闸门检查
    if wf_is_gated_after "$P"; then
      G="$(wf_state_get "$NAME" gate)"
      if [ "$G" != "passed" ]; then
        echo "⚠ 阶段 $(wf_phase_label "$P") 完成后是闸门阶段。当前 gate=$G。" >&2
        echo "  先 /wf gate 放行，或再次 /wf next 强制推进（跳过闸门）。" >&2
        # 允许二次 next 强制（用户明确意图）
        exit 1
      fi
    fi
    N="$(wf_next_phase "$P")"
    wf_state_set_phase "$NAME" "$N" "manual-next"
    echo "▸ $(wf_phase_label "$P") -> $(wf_phase_label "$N")"
    echo "  当前阶段: $(wf_phase_label "$N") [$(wf_phase_index "$N")/5]"
    ;;

  back)
    P="$(cur_phase)"; I="$(cur_idx)"
    if [ "$I" -le 1 ]; then
      echo "✗ 已在理解和求证问题，无法回退。" >&2
      exit 1
    fi
    B="$(wf_phase_at $((I - 1)))"
    wf_state_set_phase "$NAME" "$B" "manual-back"
    echo "▸ $(wf_phase_label "$P") -> $(wf_phase_label "$B")（回退）"
    echo "  当前阶段: $(wf_phase_label "$B") [$((I - 1))/5]"
    ;;

  jump)
    [ $# -ge 1 ] || { echo "用法: /wf jump <phase>（英文标识，见 /wf status 阶段顺序）" >&2; exit 1; }
    T="$1"
    if ! wf_phase_index "$T" >/dev/null; then
      echo "✗ 非法阶段 '$T'。可选: ${WF_PHASES[*]}" >&2
      exit 1
    fi
    wf_state_set_phase "$NAME" "$T" "manual-jump"
    echo "▸ 跳转到 $(wf_phase_label "$T") [$(wf_phase_index "$T")/5]"
    ;;

  gate)
    P="$(cur_phase)"
    if ! wf_is_gated_after "$P"; then
      echo "ℹ 当前阶段 $(wf_phase_label "$P") 不是闸门后置阶段（闸门后置: $WF_GATED_AFTER）。"
      echo "  gate 仅在 理解和求证问题/生成执行计划 完成后有意义。"
      exit 0
    fi
    wf_state_set_gate "$NAME" passed
    N="$(wf_next_phase "$P")"
    echo "✓ 闸门放行: gate=passed"
    echo "  阶段 $(wf_phase_label "$P") 已批准，可进入 $(wf_phase_label "$N")。"
    echo "  下一步: /wf next 推进（或模型输出 PHASE_DONE 后 Stop hook 自动推进）。"
    ;;

  done)
    WT="$(wf_state_get "$NAME" worktree_path)"
    BR="$(wf_state_get "$NAME" branch)"
    echo "▸ 归档工作流 '$NAME'（彻底清理）"
    git -C "$WF_REPO_ROOT" worktree remove --force "$WT" 2>/dev/null || true
    git -C "$WF_REPO_ROOT" branch -D "$BR" 2>/dev/null || true
    rm -rf "$WF_META_ROOT/$NAME"
    echo "  worktree + 分支 $BR + 元数据 已删除。"
    ;;

  *)
    echo "✗ 未知子命令 '$SUB'。可用: status next back jump gate done" >&2
    exit 1
    ;;
esac
