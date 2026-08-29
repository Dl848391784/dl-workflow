"""产物与证据链：evidence.jsonl 证据链 + plan.md change_point 改动面 + understands/plans 文档。

数据源（dl-workflow 产物契约）：
- 证据链：<project>/.claude/evidence/<name>.jsonl（skill-trace 带 q/a/结论 + gate 裁决记录）
- 改动面：<project>/.claude/plans/<name>.md 的 change_point= 字段，
  锚点形态 `文件:方法:L行（改|增|删）：改前=X → 改后=Y`（render-artifact 机械装配，格式稳定可机读）；
  现状代码上下文按 state.json 的 worktree_path 实读锚点文件 ±4 行
- 产物文档：<project>/.claude/understands|plans/<name>.md
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger("dl_dashboard.outputs")

# change_point= 块（跨行，止于 ；interface= / ；Produces= / 空行 / 串尾）
_CP_RE = re.compile(r"change_point=(.+?)(?:；interface=|；Produces=|\n\n|$)", re.S)
# 锚点行：web_ui/app.py:_render_report:L267（改）：改前=X → 改后=Y
#         _macros.html:-:L57（改）：改前=...（注）→ 改后=...（注）
#         test_x.py:-（增@文件尾）：新增测试描述
_ANCHOR_RE = re.compile(
    r"([\w./-]+\.\w+):([\w.-]*):?L?(\d+|-)?（(改|增|删)[^）]*）"
    r"(?:：改前=(.*?)\s*→\s*改后=(.*?))?(?:：([^；\n]*))?(?=；|\n|$)"
)
_CTX_RADIUS = 4  # 现状代码上下文半径（锚点行 ±4）


def load_evidence(project: Path, name: str) -> list[dict]:
    """证据链条目（q/a/结论 全量保留——用户要看的就是链本身）。"""
    p = project / ".claude" / "evidence" / f"{name}.jsonl"
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            log.warning("evidence 损坏行跳过: %s", p, exc_info=True)
            continue
        out.append({
            "kind": d.get("kind", "?"),
            "major_stage": d.get("major_stage", ""),
            "minor_stage": d.get("minor_stage", ""),
            "sub_step": d.get("sub_step"),
            "skill": d.get("skill"),
            "purpose": d.get("purpose", ""),
            "conclusion": d.get("结论", ""),
            "q": d.get("q") or [],
            "a": d.get("a") or [],
        })
    return out


def _code_context(worktree: Path | None, file: str, line: str, method: str) -> dict | None:
    """worktree 实读锚点上下文（审核用）。

    行号定位优先；无行号但有方法名时按方法名首现定位（def 行或调用行）
    ——tacet 脊柱产物的锚点常只有 `file:method:（增）` 形态。文件缺失/
    两者皆无 → None。
    """
    if worktree is None:
        return None
    p = worktree / file
    if not p.is_file():
        return None
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        log.warning("锚点文件读失败: %s", p, exc_info=True)
        return None
    n: int | None = None
    if line.isdigit():
        n = int(line)
        if n < 1 or n > len(lines):
            return None
    elif method and method != "-":
        for idx, text in enumerate(lines, 1):
            if f"def {method}" in text:
                n = idx
                break
        if n is None:
            for idx, text in enumerate(lines, 1):
                if method in text:
                    n = idx
                    break
    if n is None:
        return None
    lo, hi = max(1, n - _CTX_RADIUS), min(len(lines), n + _CTX_RADIUS)
    return {
        "start": lo,
        "anchor": n,
        "lines": lines[lo - 1:hi],
    }


def load_change_points(project: Path, name: str) -> list[dict]:
    """plan.md 的 change_point 锚点：文件/方法/行/动作 + 改前/改后 + 现状代码上下文。"""
    p = project / ".claude" / "plans" / f"{name}.md"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    worktree: Path | None = None
    state_p = project / ".claude" / "workflows" / name / "state.json"
    if state_p.exists():
        try:
            wt = json.loads(state_p.read_text(encoding="utf-8")).get("worktree_path")
            if wt:
                worktree = Path(wt)
        except json.JSONDecodeError:
            log.warning("state.json 解析失败，改动面无现状上下文: %s", state_p)
    out: list[dict] = []
    for m in _CP_RE.finditer(text):
        for a in _ANCHOR_RE.finditer(m.group(1)):
            out.append({
                "file": a.group(1),
                "method": a.group(2) or "-",
                "line": a.group(3) or "-",
                "action": a.group(4),
                "before": (a.group(5) or "").strip(),
                "after": (a.group(6) or "").strip(),
                "summary": (a.group(7) or "").strip(),
                "context": _code_context(
                    worktree, a.group(1), a.group(3) or "", a.group(2) or ""),
            })
    return out


def artifact_status(project: Path, name: str) -> dict:
    out: dict[str, dict] = {}
    for kind in ("understands", "plans"):
        p = project / ".claude" / kind / f"{name}.md"
        out[kind] = {"exists": p.exists(), "size": p.stat().st_size if p.exists() else 0}
    return out


def load_artifact(project: Path, name: str, kind: str) -> str | None:
    """产物文档全文。kind 白名单防路径穿越（文件名由 kind 决定，不受 name 影响路径深度）。"""
    if kind not in ("understands", "plans"):
        raise ValueError(f"未知产物类型: {kind}")
    p = project / ".claude" / kind / f"{name}.md"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")
