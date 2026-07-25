#!/bin/bash
# dl-workflow uninstall.sh
# 删 ~/.claude/{hooks,skills,output-styles,commands}/ 里 dl-workflow 装的文件
# 摘除 ~/.claude/settings.json 里 dl-workflow 注册的 hook
# 从 ~/.bashrc 删 BEGIN/END dl-workflow 段落

set -euo pipefail

CLAUDE_HOME="$HOME/.claude"
BASHRC="$HOME/.bashrc"

echo "═══ dl-workflow uninstall ═══"

# ---------- 删文件 ----------
# hooks 不删（install 时没 copy，直接引用源 ~/.dl-workflow/hooks/）。
# 只删 Claude Code 硬编码加载路径下 copy 的文件。
echo "▸ 删除 skill / output-style / command"
rm -rf "$CLAUDE_HOME/skills/workflow-creation" && echo "  - $CLAUDE_HOME/skills/workflow-creation/"
rm -f "$CLAUDE_HOME/output-styles/workflow.md" && echo "  - $CLAUDE_HOME/output-styles/workflow.md"
rm -f "$CLAUDE_HOME/commands/dl.md" && echo "  - $CLAUDE_HOME/commands/dl.md"

# ---------- 摘 settings.json 里 dl-workflow 注册的 hooks ----------
SETTINGS="$CLAUDE_HOME/settings.json"
if [ -f "$SETTINGS" ]; then
  echo "▸ 摘除 settings.json 里 dl-workflow 的 hook 注册"
  python3 - "$SETTINGS" <<'PY'
import json, sys, re

path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    try:
        settings = json.load(f)
    except json.JSONDecodeError:
        sys.exit(0)  # 损坏 -> 别动

# 匹配 dl-workflow 注册的 hook 命令（直接引用 ~/.dl-workflow/hooks/ 源）
DLWF_RE = re.compile(r"~?/?.*\.dl-workflow/hooks/(workflow_phase|workflow_advance|codegraph_gate|codegraph_audit)\.py")

hooks = settings.get("hooks", {})
removed = 0
for event, groups in list(hooks.items()):
    new_groups = []
    for group in groups:
        # 保留：group 里所有 hooks 的 command 均不匹配 DLWF
        keep_inner = [h for h in group.get("hooks", []) if not DLWF_RE.search(h.get("command", ""))]
        if keep_inner:
            group["hooks"] = keep_inner
            new_groups.append(group)
        else:
            removed += 1
    if new_groups:
        hooks[event] = new_groups
    else:
        del hooks[event]
        removed += 1

if not hooks and "hooks" in settings:
    del settings["hooks"]

with open(path, "w", encoding="utf-8") as f:
    json.dump(settings, f, ensure_ascii=False, indent=2)

print(f"  removed {removed} 个 dl-workflow hook 注册")
PY
fi

# ---------- 删 ~/.bashrc 的 BEGIN/END dl-workflow 段 ----------
echo "▸ 清理 ~/.bashrc"
if grep -q "# BEGIN dl-workflow" "$BASHRC" 2>/dev/null; then
  # 备份
  cp -p "$BASHRC" "$BASHRC.dl-workflow-uninstall.bak"
  # 用 sed 删段落
  sed -i '/# BEGIN dl-workflow/,/# END dl-workflow/d' "$BASHRC"
  echo "  - 已删除 BEGIN/END dl-workflow 段（备份: $BASHRC.dl-workflow-uninstall.bak）"
else
  echo "  - ~/.bashrc 无 dl-workflow 段"
fi

echo
echo "═══ 完成 ═══"
echo "  注：已存在的 workflow state 未删（~/.claude/workflows/ 或项目 <repo>/.claude/workflows/）"
echo "      清理 state 请手工 rm，或用 'dl <name> --done' 一个个归档。"
