#!/bin/bash
# tests/test_dl_launch_engine.sh——launcher 引擎解析冒烟（不真起 TUI，只验变量解析段）
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCH="$REPO_ROOT/scripts/workflow/dl-launch.sh"

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

# wf_write_settings 引擎分支（qoder + DL_QODER_MODEL 时写 model 键）
export WF_META_ROOT="$(mktemp -d)" WF_REPO_ROOT=/tmp WF_LIB_DIR="$REPO_ROOT/scripts/workflow"
export WF_SETTINGS_TEMPLATE_VERSION=1
source "$REPO_ROOT/scripts/workflow/dl-lib.sh"
DL_ENGINE=qodercli DL_QODER_MODEL=deepseek/deepseek-v4-flash-pg wf_write_settings engtest
python3 -c "
import json
s = json.load(open('$WF_META_ROOT/engtest/settings.json'))
assert s['model'] == 'deepseek/deepseek-v4-flash-pg', s.get('model')
assert s['permissions']['defaultMode'] == 'acceptEdits'  # qoder 忽略但 claude 引擎同文件兼容
assert any('workflow_phase.py' in h['command'] for g in s['hooks']['UserPromptSubmit'] for h in g['hooks'])
# v12：两个 inject hook 必须随 per-wf settings 自包含登记（worktree 内无 project
# settings.json，不登记则工作流会话全程收不到 codegraph/蒸馏瘦档注入）
ups = [h['command'] for g in s['hooks']['UserPromptSubmit'] for h in g['hooks']]
assert any('codegraph_inject.py' in c for c in ups), ups
assert any('conventions_inject.py' in c for c in ups), ups
print('✓ wf_write_settings qoder 分支正确')
"

# --- per-instance engine：state 落引擎 + resume sticky ---
SEG="$WF_META_ROOT/sticky/state.json"
mkdir -p "$WF_META_ROOT/sticky"
cat > "$SEG" <<'JSON'
{"name": "sticky", "engine": "qodercli"}
JSON
# wf_state_init 落引擎字段（6 参形态）
wf_state_init falltest sid-1 master wf/falltest /tmp/wt qodercli
python3 -c "
import json
s = json.load(open('$WF_META_ROOT/falltest/state.json'))
assert s['engine'] == 'qodercli', s.get('engine')
print('✓ wf_state_init 落 engine 字段')
"
# resume sticky：DL_ENGINE 未设时从 state 读（wf_state_get 真实函数，name=sticky 定位）
DL_ENGINE=""
WF_NAME=sticky  # set -u 下引擎块引用 $WF_NAME；sticky 用例 state.json 即 <root>/sticky/
eval "$(sed -n '/^# ---------- 引擎/,/^esac/p' "$LAUNCH" | sed 's/exit 1/return 1/')"
[ "$DL_ENGINE" = "qodercli" ] || { echo "✗ resume sticky 未读到 state engine: $DL_ENGINE"; exit 1; }
echo "✓ resume sticky：无 env 时 state.engine 生效"
