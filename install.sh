#!/bin/bash
# dl-workflow install.sh
# 0. 若从 tarball 解压目录跑（SRC_DIR != ~/.dl-workflow）：先把代码部署到 ~/.dl-workflow 再重-exec
# 1. copy 1 skill / 1 output-style / 1 command 到 ~/.claude/（hooks 不 copy，settings 直引源）
# 2. 合并 ~/.claude/settings.json 的 hook 注册（用户级只 codegraph 两个；
#   并幂等摘除历史误注册的 workflow_phase/advance/step_fence——它们只属 per-wf settings）
# 3. 追写 ~/.bashrc 的 dl 函数（工作流入口，若未安装）
# 4. dashboard python 依赖（pip --user fastapi uvicorn；--skip-dashboard 跳过）
# 5. codegraph CLI（npm 全局装 @colbymchenry/codegraph；--skip-codegraph 跳过）
# 6. HTML 导出依赖（dl_doc_render 渲染器的 Python-Markdown；--skip-html 跳过）
# 7. 蒸馏器依赖（mine_conventions 约定蒸馏的 PyYAML；--skip-distiller 跳过）
# 8. 自检报告（逐项 ✓/✗ + 警告汇总）
#
# 幂等：连续跑两次结果一致。冲突文件备份到 ~/.claude/.dl-workflow-backup/<ts>/。
# 可选层（4/5/6/7）失败只警告不阻断——核心工作流不依赖它们。

# ---------- bash 4+ 自动选择（必须最先，且语法兼容 3.2/POSIX） ----------
# 直接执行 ~/.dl-workflow/install.sh 时 shebang #!/bin/bash 在 macOS 是 3.2（实爆）——
# 这里自检：当前解释器 <4 则自动 exec Homebrew bash 重跑（用户无感，无需记路径）。
# 不用 set -u 特性/数组下标，保证 3.2 和 sh 都能走到重 exec。
_major=$("${BASH:-/bin/bash}" -c 'printf %s "${BASH_VERSINFO[0]:-0}"' 2>/dev/null)
_major=${_major:-0}
case ${_major} in ''|*[!0-9]*) _major=0 ;; esac  # 非数字一律按旧版处理，走重 exec 救援
if [ "$_major" -lt 4 ] 2>/dev/null; then
  for _b in /opt/homebrew/bin/bash /usr/local/bin/bash; do
    [ -x "$_b" ] && exec "$_b" "$0" "$@"
  done
  echo "✗ 需要 bash ≥ 4（当前 ${_major:-?}）。macOS 请先：brew install bash，然后重跑本脚本" >&2
  exit 1
fi
unset _major _b

set -euo pipefail

# ---------- 路径 ----------
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DL_HOME="$HOME/.dl-workflow"
CLAUDE_HOME="$HOME/.claude"
BACKUP_DIR="$CLAUDE_HOME/.dl-workflow-backup/$(date +%Y%m%d-%H%M%S)"
BASHRC="$HOME/.bashrc"

SKIP_DASHBOARD=0
SKIP_CODEGRAPH=0
SKIP_HTML=0
SKIP_DISTILLER=0
PROJECT_MODE=0
PROJECT_DIR=""
WARNINGS=()

usage() {
  cat <<'EOF'
用法: ./install.sh [--skip-dashboard] [--skip-codegraph] [--skip-html] [--skip-distiller]
  默认全装：核心（hooks/skill/command/bashrc）+ dashboard 依赖 + codegraph CLI + HTML 导出依赖 + 蒸馏器依赖
  --skip-dashboard  不装 fastapi/uvicorn（管理后台不可用，核心工作流不受影响）
  --skip-codegraph  不装 codegraph CLI（H15 门禁不生效，核心工作流不受影响）
  --skip-html       不装 vendor bun 依赖（产物 HTML 伴随导出降级，md 产物不受影响）
  --skip-distiller  不装 pyyaml（约定蒸馏不可用，核心工作流不受影响）
  --project[=DIR]   项目级接线：codegraph index + post-commit + settings 合并 + 首蒸
                    （在 DIR 或当前目录执行；机器级安装照常先跑）
EOF
}

# ---------- tarball 部署：代码先在 ~/.dl-workflow 安家 ----------
# settings.json hook 注册与 bashrc DL_WF_HOME 都硬编码 ~/.dl-workflow（settings 直引源设计），
# 所以从解压目录首跑时先 overlay 复制过去，再重-exec canonical 副本走全流程。
# cp -pR（GNU/BSD 双兼容；macOS 的 BSD cp 无 -a）：overlay 不删旧文件——
# ~/.dl-workflow 里有运行态（dashboard-run/ 等），禁 --delete。
ensure_home() {
  if [ "$SRC_DIR" = "$DL_HOME" ]; then
    return 0
  fi
  echo "▸ 部署代码到 ${DL_HOME}（tarball 首跑）"
  mkdir -p "$DL_HOME"
  cp -pR "$SRC_DIR/." "$DL_HOME/"
  echo "  ↺ 重-exec $DL_HOME/install.sh $*"
  # 必须用 ${BASH}（当前解释器）而非 shebang 重 exec：macOS 的 #!/bin/bash 是
  # 3.2，即使首跑用 homebrew bash 5.x，shebang 重 exec 也会切回 3.2 炸掉（实爆）。
  exec "$BASH" "$DL_HOME/install.sh" "$@"
}

# ---------- 前置检查 ----------
check_deps() {
  command -v python3 >/dev/null || { echo "✗ 缺 python3" >&2; exit 1; }
  command -v git >/dev/null || { echo "✗ 缺 git" >&2; exit 1; }
  # bash ≥ 4 检查已前移到脚本顶部（3.2 会在任何函数执行前报 unbound variable 裸错）
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || { echo "✗ 需要 python ≥ 3.11（hook 脚本用 3.10+ 语法，当前 $(python3 -V 2>&1)）" >&2; exit 1; }
  echo "✓ 依赖检查通过（$(python3 -V 2>&1), git, bash ${BASH_VERSION}）"
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

# ---------- pip --user 安装（dashboard 与 HTML 两层共用） ----------
# 机器无任何 pip index 配置时一次性挂 aliyun 镜像（默认 pypi 源在境内服务器极慢）；
# 已有配置（用户/全局 pip.conf）则不碰——一次性 CLI 参数，不写入任何配置文件。
_pip_install_user() {  # _pip_install_user <pkg...>
  if ! python3 -m pip --version >/dev/null 2>&1; then
    return 2
  fi
  local pip_extra=()
  if ! python3 -m pip config list 2>/dev/null | grep -q "index.url\|index-url"; then
    pip_extra=(--index-url https://mirrors.aliyun.com/pypi/simple/)
    echo "  ↺ 无 pip 镜像配置，本次安装走 aliyun 镜像（一次性，不改配置）"
  fi
  # PEP 668（Homebrew/受管 Python）：stdlib 下 EXTERNALLY-MANAGED 标记存在时 pip
  # 拒绝 --user 安装——仅本次追加 --break-system-packages，不改 pip 全局配置；
  # pip 过旧不支持该参数时只告警（实爆：Mac Homebrew Python 拒绝 pip install --user）。
  if python3 -c 'import sysconfig,pathlib,sys; p=pathlib.Path(sysconfig.get_path("stdlib"))/"EXTERNALLY-MANAGED"; sys.exit(0 if p.exists() else 1)'; then
    if python3 -m pip install --help 2>/dev/null | grep -q -- "--break-system-packages"; then
      pip_extra+=(--break-system-packages)
      echo "  ↺ PEP 668 环境（EXTERNALLY-MANAGED），本次追加 --break-system-packages（一次性，不改配置）"
    else
      echo "  ⚠ 检测到 PEP 668 标记但 pip 不支持 --break-system-packages，pip 安装可能失败" >&2
    fi
  fi
  python3 -m pip install --user "${pip_extra[@]}" "$@"
}

# ---------- dashboard python 依赖（可选层） ----------
install_dashboard_deps() {
  if [ "$SKIP_DASHBOARD" = "1" ]; then
    echo "▸ 跳过 dashboard 依赖（--skip-dashboard）"
    return 0
  fi
  echo "▸ 检查 dashboard python 依赖（fastapi, uvicorn）"
  if python3 -c "import fastapi, uvicorn" 2>/dev/null; then
    echo "  ↺ fastapi + uvicorn 已可 import，跳过"
    return 0
  fi
  local rc=0
  _pip_install_user fastapi uvicorn || rc=$?
  if [ "$rc" = 0 ]; then
    echo "✓ pip --user 安装 fastapi + uvicorn 完成"
  elif [ "$rc" = 2 ]; then
    echo "  ⚠ python3 -m pip 不可用——dashboard（python3 -m dl_dashboard.app）不可用，核心工作流不受影响" >&2
    WARNINGS+=("dashboard: python3 -m pip 不可用，fastapi/uvicorn 未装")
  else
    echo "  ⚠ pip 安装失败——dashboard 不可用，核心工作流不受影响" >&2
    WARNINGS+=("dashboard: pip install --user fastapi uvicorn 失败")
  fi
}

# ---------- codegraph CLI（可选层，H15 门禁依赖） ----------
install_codegraph() {
  if [ "$SKIP_CODEGRAPH" = "1" ]; then
    echo "▸ 跳过 codegraph CLI（--skip-codegraph）"
    return 0
  fi
  echo "▸ 检查 codegraph CLI（H15 门禁依赖）"
  if command -v codegraph >/dev/null; then
    echo "  ↺ codegraph 已存在（$(command -v codegraph)），跳过"
    return 0
  fi
  # 上一轮装过但当前 shell PATH 还没生效（bashrc 段落要 exec bash 才 source）
  if [ -x "$HOME/.npm-global/bin/codegraph" ]; then
    echo "  ↺ codegraph 已装于 ~/.npm-global/bin（exec bash 后生效），跳过"
    return 0
  fi
  if ! command -v npm >/dev/null; then
    echo "  ⚠ 缺 npm——codegraph 未装，H15 门禁不生效，核心工作流不受影响" >&2
    WARNINGS+=("codegraph: 缺 npm")
    return 0
  fi
  # 全局 prefix 不可写（系统目录要 sudo）-> 改 ~/.npm-global 免 sudo，并保证 bin 进 PATH
  local prefix
  prefix="$(npm config get prefix)"
  if [ ! -w "$prefix" ]; then
    echo "  ↺ npm 全局 prefix $prefix 不可写，改 ~/.npm-global（免 sudo）"
    npm config set prefix "$HOME/.npm-global"
    if ! grep -q "# BEGIN dl-workflow npm PATH" "$BASHRC" 2>/dev/null; then
      cat >> "$BASHRC" <<'BASHRC_EOF'

# BEGIN dl-workflow npm PATH  (installed by ~/.dl-workflow/install.sh)
# npm 全局 prefix 改到 ~/.npm-global（免 sudo），全局 bin 进 PATH
export PATH="$HOME/.npm-global/bin:$PATH"
# END dl-workflow npm PATH
BASHRC_EOF
      echo "  ↺ ~/.bashrc 已追加 npm PATH 段落"
    fi
  fi
  # 一次性 npmmirror 参数（默认源在境内服务器极慢），不改用户全局 registry 配置
  if npm i -g @colbymchenry/codegraph --registry=https://registry.npmmirror.com; then
    echo "✓ codegraph 安装完成"
    hash -r
  else
    echo "  ⚠ codegraph 安装失败——H15 门禁不生效，核心工作流不受影响" >&2
    WARNINGS+=("codegraph: npm i -g @colbymchenry/codegraph 失败")
  fi
}

# ---------- HTML 导出依赖（可选层，产物 HTML 伴随导出） ----------
install_html_deps() {
  if [ "$SKIP_HTML" = "1" ]; then
    echo "▸ 跳过 HTML 导出依赖（--skip-html）"
    return 0
  fi
  echo "▸ 检查 HTML 导出依赖（dl_doc_render 渲染器 -> Python-Markdown）"
  # v0.5.0 起渲染器自研（dl_doc_render.py），legacy bun vendor 目录清理（H13 死代码）
  if [ -d "$DL_HOME/vendor/baoyu-markdown-to-html" ]; then
    rm -rf "$DL_HOME/vendor/baoyu-markdown-to-html"
    echo "  ↺ 清理 legacy vendor/baoyu-markdown-to-html（v0.5.0 起自研渲染器）"
  fi
  if [ ! -f "$DL_HOME/dl_doc_render.py" ]; then
    echo "  ⚠ 渲染器缺失（$DL_HOME/dl_doc_render.py）——HTML 伴随导出降级，md 产物不受影响" >&2
    WARNINGS+=("html: dl_doc_render.py 缺失")
    return 0
  fi
  if python3 -c "import markdown" 2>/dev/null; then
    echo "  ↺ markdown 已可 import，跳过"
    return 0
  fi
  local rc=0
  _pip_install_user markdown || rc=$?
  if [ "$rc" = 0 ]; then
    echo "✓ pip --user 安装 markdown 完成"
  elif [ "$rc" = 2 ]; then
    echo "  ⚠ python3 -m pip 不可用——HTML 伴随导出降级，核心工作流不受影响" >&2
    WARNINGS+=("html: python3 -m pip 不可用，markdown 未装")
  else
    echo "  ⚠ pip 安装失败——HTML 伴随导出降级，核心工作流不受影响" >&2
    WARNINGS+=("html: pip install --user markdown 失败")
  fi
}

# ---------- 蒸馏器依赖（可选层，mine_conventions 约定蒸馏 -> PyYAML） ----------
install_distiller_deps() {
  if [ "$SKIP_DISTILLER" = "1" ]; then
    echo "▸ 跳过蒸馏器依赖（--skip-distiller）"
    return 0
  fi
  echo "▸ 检查蒸馏器依赖（pyyaml）"
  if python3 -c "import yaml" 2>/dev/null; then
    echo "  ↺ pyyaml 已可 import，跳过"
    return 0
  fi
  local rc=0
  _pip_install_user pyyaml || rc=$?
  if [ "$rc" = 0 ]; then
    echo "✓ pip --user 安装 pyyaml 完成"
  else
    echo "  ⚠ pyyaml 未装——约定蒸馏不可用，核心工作流不受影响" >&2
    WARNINGS+=("distiller: pyyaml 未装")
  fi
}

# ---------- 自检报告 ----------
self_check() {
  echo "▸ 自检报告"
  local fail=0
  _ck() { # _ck <描述> <cmd...>
    local desc="$1"; shift
    if "$@" >/dev/null 2>&1; then
      echo "  ✓ $desc"
    else
      echo "  ✗ $desc"
      fail=$((fail + 1))
    fi
  }
  _ck "bashrc dl 段落"              grep -q "# BEGIN dl-workflow" "$BASHRC"
  _ck "settings.json codegraph 门禁注册" grep -q "codegraph_gate.py" "$CLAUDE_HOME/settings.json"
  _ck "settings.json design 门禁注册"    grep -q "design_gate.py" "$CLAUDE_HOME/settings.json"
  _ck "skill 就位"                  test -f "$CLAUDE_HOME/skills/workflow-creation/SKILL.md"
  _ck "output-style 就位"           test -f "$CLAUDE_HOME/output-styles/workflow.md"
  _ck "command 就位"                test -f "$CLAUDE_HOME/commands/dl.md"
  _ck "hook 源文件就位（$DL_HOME/hooks/）" test -f "$DL_HOME/hooks/workflow_phase.py"
  if [ "$SKIP_DASHBOARD" != "1" ]; then
    _ck "dashboard 依赖（fastapi, uvicorn）" python3 -c "import fastapi, uvicorn"
  fi
  if [ "$SKIP_CODEGRAPH" != "1" ]; then
    if command -v codegraph >/dev/null 2>&1; then
      echo "  ✓ codegraph CLI（$(command -v codegraph)）"
    elif [ -x "$HOME/.npm-global/bin/codegraph" ]; then
      echo "  ✓ codegraph CLI（~/.npm-global/bin/codegraph，exec bash 后生效）"
    else
      echo "  ✗ codegraph CLI"
      fail=$((fail + 1))
    fi
  fi
  if [ "$SKIP_HTML" != "1" ]; then
    _ck "HTML 导出依赖（python markdown + dl_doc_render）" bash -c "python3 -c 'import markdown' && test -f '$DL_HOME/dl_doc_render.py'"
  fi
  if [ "$SKIP_DISTILLER" != "1" ]; then
    _ck "蒸馏器依赖（pyyaml）" python3 -c "import yaml"
  fi
  # 顾问项（不计 fail）：understand:1 子3 双向取证的 GitHub 层提额
  if [ -n "${GITHUB_TOKEN:-}" ] || grep -q "GITHUB_TOKEN" "$BASHRC" 2>/dev/null; then
    echo "  ✓ GITHUB_TOKEN 已配置"
  else
    echo "  ○ GITHUB_TOKEN 未配置（可选；子3 双向取证 GitHub 层提额用，见 README）"
  fi
  if [ "${#WARNINGS[@]}" -gt 0 ]; then
    echo "  警告汇总:"
    printf '    ⚠ %s\n' "${WARNINGS[@]}"
  fi
  if [ "$fail" -gt 0 ]; then
    echo "  ✗ $fail 项未过——按上面清单排查后重跑 ./install.sh（幂等）"
    return 1
  fi
  echo "  全部通过"
}

# ---------- 主 ----------
main() {
  echo "═══ dl-workflow install ═══"
  echo "  源目录: $SRC_DIR"
  echo "  目标:   $CLAUDE_HOME/"
  echo
  ensure_home "$@"
  local arg
  for arg in "$@"; do
    case "$arg" in
      --skip-dashboard) SKIP_DASHBOARD=1 ;;
      --skip-codegraph) SKIP_CODEGRAPH=1 ;;
      --skip-html) SKIP_HTML=1 ;;
      --skip-distiller) SKIP_DISTILLER=1 ;;
      --project) PROJECT_MODE=1 ;;
      --project=*) PROJECT_MODE=1; PROJECT_DIR="${arg#--project=}" ;;
      -h|--help) usage; exit 0 ;;
      *) echo "✗ 未知参数: $arg" >&2; usage >&2; exit 1 ;;
    esac
  done
  check_deps
  install_files
  merge_settings
  install_bashrc
  install_dashboard_deps
  install_codegraph
  install_html_deps
  install_distiller_deps
  echo
  self_check
  if [ "$PROJECT_MODE" = "1" ]; then
    local pdir="${PROJECT_DIR:-$PWD}"
    echo
    echo "▸ 项目级接线: $pdir"
    python3 "$DL_HOME/scripts/setup/setup_project.py" --project "$pdir" || \
      echo "  ⚠ 项目接线有硬失败（见上方），机器级安装不受影响"
  fi
  echo
  echo "═══ 完成 ═══"
  if [ -d "$BACKUP_DIR" ]; then
    echo "  备份在: $BACKUP_DIR/"
  fi
  echo "  下一步: exec bash 或新开终端，然后 dl <name> 建工作流"
  if [ "$PROJECT_MODE" != "1" ]; then
    # 首次安装强指引：机器级装完，项目接线是唯一还没做的事（README「快速开始」为真源）
    cat <<'NEXT'

╔══════════════════════════════════════════════════════════╗
  首次安装？还差项目接线（让你的项目拥有约定蒸馏/注入）：
    ① cd <你的项目> && ~/.dl-workflow/install.sh --project
    ② cd <你的项目> && python3 ~/.dl-workflow/bin/doctor.py
    ③ 把 ① 尾部自检清单 + ② 完整输出贴回维护者确认
  （远程机器的唯一验收方式；详见 README「快速开始」）

  可选：dashboard（dl 工作流驾驶台，不会自动启动）：
    cd ~/.dl-workflow && python3 -m dl_dashboard.app   # 前台跑，Ctrl+C 停止
    setsid nohup bash -c 'cd ~/.dl-workflow && python3 -m dl_dashboard.app' \
      > ~/.dl-workflow/dashboard-run/server.log 2>&1 &   # 常驻后台
╚══════════════════════════════════════════════════════════╝
NEXT
  fi
}

main "$@"
