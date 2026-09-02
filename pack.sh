#!/bin/bash
# dl-workflow pack.sh —— 打分发 tarball（维护机用，目标机器不需要）
# git archive 只含 tracked 文件；.gitattributes export-ignore 再排除 designs/ tests/ dashboard.toml
# 产出：dist/dl-workflow-<VERSION>.tar.gz（解压后 ./install.sh 即装）
#
# 工作树必须干净：archive 打的是 HEAD，未提交改动不会进包——宁可阻断也不出「以为带上了」的包。

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(tr -d '[:space:]' < "$SRC_DIR/VERSION")"
PREFIX="dl-workflow-$VERSION"
DIST_DIR="$SRC_DIR/dist"
OUT="$DIST_DIR/$PREFIX.tar.gz"

cd "$SRC_DIR"

if [ -n "$(git status --porcelain)" ]; then
  echo "✗ 工作树有未提交改动，git archive 只打 HEAD。先 commit 再 pack。" >&2
  git status --short >&2
  exit 1
fi

mkdir -p "$DIST_DIR"
git archive --format=tar.gz -o "$OUT" --prefix="$PREFIX/" HEAD

# ---------- 校验 ----------
LISTING="$(tar -tzf "$OUT")"
fail=0

# 必含：运行 + 安装所需全链路
REQUIRED=(
  "$PREFIX/install.sh"
  "$PREFIX/uninstall.sh"
  "$PREFIX/pack.sh"
  "$PREFIX/VERSION"
  "$PREFIX/README.md"
  "$PREFIX/hooks/workflow_phase.py"
  "$PREFIX/hooks/workflow_advance.py"
  "$PREFIX/hooks/workflow_step_fence.py"
  "$PREFIX/hooks/codegraph_gate.py"
  "$PREFIX/hooks/codegraph_audit.py"
  "$PREFIX/hooks/design_gate.py"
  "$PREFIX/hooks/design_audit.py"
  "$PREFIX/scripts/workflow/dl-launch.sh"
  "$PREFIX/scripts/workflow/dl-lib.sh"
  "$PREFIX/scripts/workflow/dl-cmd.sh"
  "$PREFIX/dl_flow_engine.py"
  "$PREFIX/dl_flow_nodes.py"
  "$PREFIX/dl_flow_common.py"
  "$PREFIX/dl_flow_checks.py"
  "$PREFIX/dl_flow_handoff.py"
  "$PREFIX/dl_flow_trace.py"
  "$PREFIX/dl_dashboard/app.py"
  "$PREFIX/skills/workflow-creation/SKILL.md"
  "$PREFIX/output-styles/workflow.md"
  "$PREFIX/commands/dl.md"
  "$PREFIX/vendor/baoyu-markdown-to-html/scripts/main.ts"
  "$PREFIX/vendor/baoyu-markdown-to-html/scripts/package.json"
  "$PREFIX/vendor/baoyu-markdown-to-html/scripts/bun.lock"
)
for f in "${REQUIRED[@]}"; do
  if ! grep -qxF "$f" <<<"$LISTING"; then
    echo "✗ 必含文件缺失: $f" >&2
    fail=1
  fi
done

# 排除：内部资产与机器侧依赖不得进分发包
for pat in "/designs/" "/tests/" "/dashboard.toml" "/node_modules/"; do
  if grep -q "$pat" <<<"$LISTING"; then
    echo "✗ 排除项泄漏: $pat" >&2
    fail=1
  fi
done

[ "$fail" = 0 ] || { rm -f "$OUT"; exit 1; }

COUNT=$(wc -l <<<"$LISTING")
SIZE=$(du -h "$OUT" | cut -f1)
echo "✓ $OUT（$COUNT 个文件，$SIZE）"
echo "  目标机器: tar xzf $PREFIX.tar.gz && cd $PREFIX && ./install.sh"
