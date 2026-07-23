#!/bin/bash
# wf-lib.sh - workflow 共享库：state 读写 / worktree 管理 / 阶段定义
# 真源：designs/workflow-system-design.md
# 被 wf-launch.sh + .claude/commands/wf*.md 共用。

# 防止被直接执行（应被 source）
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  echo "wf-lib.sh: 应被 source，勿直接执行。" >&2
  exit 1
fi

# ---------- 路径 ----------

# wf-lib.sh 自身目录（绝对）
WF_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# repo 根：优先 git 反查（worktree 内 __file__.parents[2] 会指向 worktree 根而非主仓库根，
# 导致读不到主仓库 .claude/workflows/<name>/state.json）。
# git rev-parse --git-common-dir: worktree 内返回主仓库 .git 绝对路径，dirname 即主仓库根。
# 主仓库内返回 ".git"（相对）-> 用 --show-toplevel 取绝对根。
# fallback: BASH_SOURCE 的 parents[2]（非 git 环境）。
_wf_common_dir="$(git rev-parse --git-common-dir 2>/dev/null || true)"
if [ -n "$_wf_common_dir" ] && [ "$_wf_common_dir" != ".git" ]; then
  WF_REPO_ROOT="$(cd "$(dirname "$_wf_common_dir")" && pwd)"
else
  WF_REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  if [ -z "$WF_REPO_ROOT" ]; then
    WF_REPO_ROOT="$(cd "$WF_LIB_DIR/../.." && pwd)"
  fi
fi
WF_META_ROOT="$WF_REPO_ROOT/.claude/workflows"
WF_WT_ROOT="$WF_REPO_ROOT/.claude/worktrees"

# ---------- 阶段定义（§8.5：从 engine meta 缓存,删 bash 侧副本）----------
# 不再各持 PHASES/GATED_AFTER/SUBPHASES 副本（避免三处同步）。source 时调 engine
# meta 取一次常量缓存到 bash 变量。engine 是真源,bash 仅为显示/手动覆盖用。
# engine 路径：dl-workflow 一级目录（与 scripts/workflow/ 同级）。
WF_ENGINE="$(cd "$WF_LIB_DIR/../.." && pwd)/dl-flow-engine.py"
if [ -f "$WF_ENGINE" ]; then
  _meta_json="$(python3 "$WF_ENGINE" meta 2>/dev/null || echo '{}')"
  # 解析到 bash 数组/变量（python 一次产出,避免每函数都起进程）。
  WF_PHASES=()
  while IFS= read -r _p; do
    WF_PHASES+=("$_p")
  done < <(python3 -c "import json,sys;d=json.loads(sys.argv[1]);[print(p) for p in d['phases']]" "$_meta_json" 2>/dev/null)
  WF_GATED_AFTER="$(python3 -c "import json,sys;print(' '.join(json.loads(sys.argv[1])['gated_after']))" "$_meta_json" 2>/dev/null)"
  # phase_labels / subphases 按需查（函数内 python 取,避免大 declare）。
else
  # engine 缺失（dl-workflow 损坏）-> 退化为空,各函数返回空串（no silent fallback：不假数据）。
  echo "⚠ dl-flow-engine.py 缺失（$WF_ENGINE），阶段常量不可用。" >&2
  WF_PHASES=()
  WF_GATED_AFTER=""
fi

# 英文阶段名 -> 中文显示名（委托 engine,按需查）。
wf_phase_label() {
  local p="$1"
  [ -f "$WF_ENGINE" ] || { printf '%s' "$p"; return; }
  python3 -c "import json,sys;print(json.loads(sys.argv[1])['phase_labels'].get(sys.argv[2],sys.argv[2]))" "$_meta_json" "$p" 2>/dev/null
}

# 阶段 -> index
wf_phase_index() {
  local p="$1" i
  for i in "${!WF_PHASES[@]}"; do
    if [ "${WF_PHASES[$i]}" = "$p" ]; then
      echo $((i + 1))
      return 0
    fi
  done
  return 1
}

# index -> 阶段（越界返回空）
wf_phase_at() {
  local idx="$1"
  if [ "$idx" -ge 1 ] && [ "$idx" -le "${#WF_PHASES[@]}" ]; then
    echo "${WF_PHASES[$((idx - 1))]}"
    return 0
  fi
  return 1
}

# 下一阶段名（无下一阶段返回空，表示终结）
wf_next_phase() {
  local cur="$1" idx
  idx=$(wf_phase_index "$cur") || return 1
  wf_phase_at $((idx + 1))
}

# 指定阶段完成后是否需闸门
wf_is_gated_after() {
  local p="$1"
  case " $WF_GATED_AFTER " in
    *" $p "*) return 0;;
    *) return 1;;
  esac
}

# ---------- 子阶段定义（§8.5：从 engine meta 取,删 bash 副本）----------

# 阶段 -> 子阶段数（0=无子阶段）
wf_sub_total() {
  [ -f "$WF_ENGINE" ] || { echo 0; return; }
  python3 -c "import json,sys;print(json.loads(sys.argv[1])['sub_total'].get(sys.argv[2],0))" "$_meta_json" "$1" 2>/dev/null
}

# 阶段 + n -> 第 n 个子阶段标签（n 越界/无子阶段返回空）
wf_sub_label() {
  local phase="$1" n="$2"
  [ -f "$WF_ENGINE" ] || return
  python3 -c "import json,sys;subs=json.loads(sys.argv[1])['subphases'].get(sys.argv[2],[]);n=int(sys.argv[3]);print(subs[n-1] if 1<=n<=len(subs) else '')" "$_meta_json" "$phase" "$n" 2>/dev/null
}

# ---------- state.json 读写 ----------
# 用 python3 做 JSON 读写（项目已依赖 python3），避免手撸 JSON 易错。

WF_STATE_FILE=""  # 由 wf_set_state_path 设置

wf_set_state_path() {
  WF_STATE_FILE="$WF_META_ROOT/$1/state.json"
}

wf_state_init() {
  # $1=name $2=session_id $3=base_ref $4=branch $5=worktree_path
  local name="$1" sid="$2" base="$3" branch="$4" wtp="$5"
  mkdir -p "$WF_META_ROOT/$name"
  python3 - "$WF_META_ROOT/$name/state.json" "$name" "$sid" "$base" "$branch" "$wtp" <<'PY'
import json, sys, datetime
path, name, sid, base, branch, wtp = sys.argv[1:7]
# datetime.utcnow 不可在 workflow 脚本外用，但 launcher 脚本非 workflow 内 JS，此处 bash+python 正常
import time
now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
state = {
  "name": name, "phase": "understand", "index": 1,
  "sub_index": 1, "sub_total": 4,   # 起于 understand，含 4 子阶段
  "session_id": sid, "base_ref": base, "branch": branch, "worktree_path": wtp,
  "gate": "pending", "created_at": now, "updated_at": now, "history": [],
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)
PY
}

# 读单个字段：wf_state_get <name> <field>
wf_state_get() {
  local f="$WF_META_ROOT/$1/state.json" field="$2"
  [ -f "$f" ] || return 1
  python3 - "$f" "$field" <<'PY'
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        print(json.load(f)[sys.argv[2]])
except (KeyError, FileNotFoundError, json.JSONDecodeError):
    sys.exit(1)
PY
}

# 设置当前阶段（写 phase+index+sub_index+sub_total+updated_at+history）：wf_state_set_phase <name> <phase> <via>
wf_state_set_phase() {
  local name="$1" phase="$2" via="$3"
  python3 - "$WF_META_ROOT/$name/state.json" "$phase" "$(wf_phase_index "$phase")" "$via" "$(wf_sub_total "$phase")" <<'PY'
import json, sys, time
path, phase, idx, via, sub_total = sys.argv[1:6]
sub_total = int(sub_total)
with open(path, encoding="utf-8") as f:
    state = json.load(f)
now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
# 记上一阶段 exit
hist = state.get("history", [])
if hist and hist[-1].get("exited_at") is None:
    hist[-1]["exited_at"] = now
    hist[-1]["via"] = via
hist.append({"phase": phase, "entered_at": now, "exited_at": None, "via": via})
state["phase"] = phase
state["index"] = int(idx)
# 子阶段：进新阶段按其 sub_total 重置；有子阶段->sub_index=1（从头），无->0
state["sub_total"] = sub_total
state["sub_index"] = 1 if sub_total > 0 else 0
state["updated_at"] = now
state["history"] = hist
state["gate"] = "pending"
with open(path, "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)
PY
}

# gate 状态：wf_state_set_gate <name> <pending|passed|denied>
wf_state_set_gate() {
  python3 - "$WF_META_ROOT/$1/state.json" "$2" <<'PY'
import json, sys, time
path, g = sys.argv[1:3]
with open(path, encoding="utf-8") as f:
    state = json.load(f)
state["gate"] = g
state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
with open(path, "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)
PY
}

# 写阶段产物路径标记（仅记录文件名，产物由模型写）
wf_state_mark_artifact() {
  : # 阶段产物命名固定（understand.md 等），hook 从 phase 推导，无需 state 记录
}

# ---------- per-workflow settings.json ----------
# worktree 内无 project settings.json（.gitignore *.json 规则致 settings.json 未入库），
# 故 per-wf settings 须自包含全部 hook + outputStyle。
#
# **dl-workflow 版本**：hook 直接引用源 `~/.dl-workflow/hooks/*.py`（不 copy 到 ~/.claude/hooks/）。
# settings.json 的 command 是自由字符串，Claude Code 执行时 shell 展开 `~`。
# 好处：改 hook 后 git pull 即生效，无需重跑 install.sh 同步副本。
# hook 内已改造为 payload.cwd -> git 反查主 repo 根（不再依赖 __file__.parents[2]）。
#
# 注：`codegraph_inject.py` 是**项目专属** hook（读项目 codegraph db 结构），
# 不由 dl-workflow 管，由项目自己的 `.claude/settings.json` 注册即可。
# dl-workflow 生成的 per-wf settings 只登 workflow + codegraph_gate/audit 这 4 个。
#
# `hk` 用字面 `~`（不展开成绝对路径）-> per-wf settings 跨用户 home 通用；
# heredoc 内 `~` 不展开（bash tilde 只在命令行词首展开），$hk 取变量字面值。
wf_write_settings() {
  local name="$1"
  local dir="$WF_META_ROOT/$name"
  local hk="~/.dl-workflow/hooks"
  mkdir -p "$dir"
  cat > "$dir/settings.json" <<JSON
{
  "outputStyle": "workflow",
  "permissions": {
    "allow": [
      "Bash(bash ~/.dl-workflow/scripts/workflow/wf-cmd.sh status:*)"
    ]
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": "python3 $hk/codegraph_gate.py" }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "python3 $hk/codegraph_audit.py" }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          { "type": "command", "command": "python3 $hk/workflow_phase.py" }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "python3 $hk/workflow_advance.py" }
        ]
      }
    ]
  }
}
JSON
}

# ---------- 列举工作流 ----------

wf_list() {
  [ -d "$WF_META_ROOT" ] || return 0
  local d
  for d in "$WF_META_ROOT"/*/state.json; do
    [ -f "$d" ] || continue
    local name
    name=$(python3 - "$d" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    print(json.load(f)["name"])
PY
)
    local phase session_id
    phase=$(wf_state_get "$name" phase 2>/dev/null)
    session_id=$(wf_state_get "$name" session_id 2>/dev/null)
    printf "%-24s 阶段=%s session=%s\n" "$name" "$(wf_phase_label "${phase:-?}")" "${session_id:-?}"
  done
}
