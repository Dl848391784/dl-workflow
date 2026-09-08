#!/bin/bash
# tests/test_dl_launch_engine.sh——launcher 引擎解析冒烟（不真起 TUI，只验变量解析段）
set -euo pipefail
LAUNCH=~/projects/dl-workflow-wt/qodercli-engine-profile/scripts/workflow/dl-launch.sh

# 引擎解析段独立可测：source 前截取（launcher 无库模式，改用文本级断言：
# 抽引擎 case 块单独 eval）
check() {
  local dl_engine="$1" expect_bin="$2" expect_perm="$3"
  local ENGINE_BIN ENGINE_PERM DL_ENGINE="$dl_engine"
  eval "$(sed -n '/^# ---------- 引擎/,/^esac/p' "$LAUNCH" | sed 's/exit 1/return 1/')"
  [ "$ENGINE_BIN" = "$expect_bin" ] || { echo "✗ DL_ENGINE=$dl_engine binary=$ENGINE_BIN"; exit 1; }
  [ "$ENGINE_PERM" = "$expect_perm" ] || { echo "✗ DL_ENGINE=$dl_engine perm=$ENGINE_PERM"; exit 1; }
}
check claude claude acceptEdits
check qodercli qodercli accept_edits
echo "✓ launcher 引擎解析双引擎正确"
