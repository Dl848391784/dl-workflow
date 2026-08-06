#!/usr/bin/env python3
"""
PreToolUse(Edit|Write) 门禁：改已有 .py 源码前强制先查 codegraph。

对应设计 designs/codegraph_enforcement_gate_design.md（H15）。
判定逻辑见 design §How。档 3 核心机制。

退出码语义（Claude Code hooks 约定）：
- exit 0：放行；stdout 可注入提示/影响面上下文
- exit 2：阻断；stderr 反馈给 agent

弱门禁边界（design §判定取舍）：
- 挡"零 codegraph 查询就改源码"
- 不挡"查错 symbol"（靠档 1 证据约定 + 档 2 commit 取证补缝）

**dl-workflow 版本**：hook 装到 ~/.claude/hooks/（用户级），不再假设
`__file__.parents[2]` 是项目根。改用 payload 里的 cwd -> git 反查项目根。
无项目根 -> exit 0 放行（宁纵勿枉，非 git 项目也别卡）。
"""

import json
import os
import subprocess
import sys
from pathlib import Path


CODEGRAPH_CLI = "/home/admin/.npm-global/bin/codegraph"

# 留痕的有效 codegraph 子命令（audit.py 写，gate.py 读）
TRACKED_SUBCOMMANDS = ("callers", "callees", "impact", "affected", "context", "query")

# 新鲜度阈值（小时）；超期只警告不阻断，避免卡死
STALE_HOURS = 72


# dl-workflow 主树根（v2.120）：hooks 由 settings.json 直引用
# ~/.dl-workflow/hooks/*.py（不 copy），__file__ 即主树真源；DL_WF_HOME
# env 优先（bashrc 导出；测试用其指向伪仓）。本仓（主树+开发 worktree）
# 的源码编辑一律拦截，project_root 解析到主树（db/audit 在主树）。
_DLWF_ROOT = Path(
    os.environ.get("DL_WF_HOME", "").strip()
    or str(Path(__file__).resolve().parent.parent)
).resolve()


def _resolve_main_root(d: Path) -> tuple[Path | None, bool]:
    """d 所属 git 仓的**主树**根 + d 是否位于 linked worktree（v2.120）。

    --show-toplevel 得工作树顶 T；--git-common-dir 解析后 == T/.git ->
    d 在主树（False，主树根=T）；否则 common 的 parent 即主树根（True）。
    非 git/命令失败 -> (None, False)（宁纵勿枉）。
    """
    try:
        top = subprocess.run(
            ["git", "-C", str(d), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if top.returncode != 0 or not top.stdout.strip():
            return None, False
        toplevel = Path(top.stdout.strip())
        # --path-format=absolute：relative 输出是相对 -C 目录的（如 ../.git），
        # 错相对基准会串号到仓外（2026-08-06 测试实测 /tmp/.git 事故）
        common = subprocess.run(
            [
                "git",
                "-C",
                str(d),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if common.returncode != 0 or not common.stdout.strip():
            return toplevel, False
        common_p = Path(common.stdout.strip())
        if not common_p.is_absolute():
            common_p = (d / common_p).resolve()
        if common_p == (toplevel / ".git").resolve():
            return toplevel, False
        return common_p.parent, True
    except (subprocess.TimeoutExpired, OSError):
        return None, False


def _is_workflow_file(path: Path) -> bool:
    """路径含 .claude/worktrees/<name> 段 -> dl 工作流 worktree 内文件。

    工作流自带 codegraph 纪律（plan:1 新鲜度前置），门禁冗余（2026-08-03
    用户决议）；v2.120 起按被编辑文件判定（原按会话 cwd，跨仓编辑漏判）。
    """
    parts = path.parts
    for i, p in enumerate(parts):
        if p == ".claude" and i + 1 < len(parts) and parts[i + 1] == "worktrees":
            return True
    return False


def _session_id(payload: dict) -> str:
    """会话标识（v2.69）：payload session_id（hooks 规范公共字段，真源）→
    transcript_path 文件名 stem（双保险）→ env CLAUDE_SESSION_ID（向后兼容）
    → "_fallback"。旧版只读 env，而 hook 环境从未注入该变量——所有会话塌缩
    _fallback.log，历史任何查询解锁之后所有会话（
    designs/gate-session-isolation-fix-design.md）。"""
    sid = str(payload.get("session_id") or "").strip()
    if sid:
        return sid
    tp = str(payload.get("transcript_path") or "").strip()
    if tp:
        stem = Path(tp).stem
        if stem:
            return stem
    sid = os.environ.get("CLAUDE_SESSION_ID", "").strip()
    return sid or "_fallback"


def _payload_cwd(payload: dict) -> str:
    for key in ("cwd", "working_dir", "current_dir"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            return val
    return str(Path.cwd())


def _has_query_this_session(audit_dir: Path, payload: dict) -> bool:
    """本会话是否已留痕过任何 codegraph 结构查询。"""
    log = audit_dir / f"{_session_id(payload)}.log"
    if not log.exists():
        return False
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(f"|{sc}|" in text for sc in TRACKED_SUBCOMMANDS)


def _is_existing_source_py(file_path: str, project_root: Path) -> bool:
    """判定是否为需要门禁的目标：已存在的 .py 源码。

    白名单跳过（design §How 步骤 1）：
    - 非 .py
    - test_*.py / *_test.py（测试，非业务源码）
    - 新建文件（仓库无此 path）
    - scripts/check_*.py（检查器自身，改动频繁且非业务符号）
    """
    p = Path(file_path)
    if p.suffix != ".py":
        return False
    name = p.name
    if name.startswith("test_") or name.endswith("_test.py"):
        return False
    if name.startswith("check_") and "scripts" in p.parts:
        return False
    abs_p = p if p.is_absolute() else (project_root / p)
    try:
        return abs_p.exists()
    except OSError:
        return False


def _freshness_warning(codegraph_db: Path) -> str:
    """索引新鲜度检查（design §How 步骤 2）；超 72h 返回警告行，否则空。"""
    if not codegraph_db.exists():
        return "[codegraph] 警告：.codegraph/codegraph.db 不存在，结构查询不可用"
    try:
        res = subprocess.run(
            [
                "sqlite3",
                str(codegraph_db),
                "SELECT MAX(indexed_at) FROM files;",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode != 0 or not res.stdout.strip():
            return ""
        max_ts_ms = int(res.stdout.strip())
        res2 = subprocess.run(
            ["date", "+%s"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        now_s = int(res2.stdout.strip())
        age_h = (now_s - max_ts_ms / 1000) / 3600
        if age_h > STALE_HOURS:
            return (
                f"[codegraph] 警告：索引 {age_h:.0f}h 前更新（> {STALE_HOURS}h），"
                f"结构可能过期。改前建议 `codegraph sync` 刷新。"
            )
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return ""
    return ""


def _affected_context(file_path: str, project_root: Path) -> str:
    """查过则跑 `codegraph affected <file>` 注入影响面（补"自动注入"缺失）。"""
    try:
        res = subprocess.run(
            [CODEGRAPH_CLI, "affected", "-q", file_path],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(project_root),
        )
        out = res.stdout.strip()
        if res.returncode == 0 and out:
            return f"[codegraph] 改 {file_path} 可能影响测试：\n{out}"
    except (subprocess.TimeoutExpired, OSError):
        pass
    return ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0  # 解析失败不阻断（宁纵勿枉业务编辑）

    file_path = (payload.get("tool_input") or {}).get("file_path", "")
    if not file_path:
        return 0

    # v2.120 三分类按**被编辑文件**的仓身份判定
    # （designs/gate-file-main-root-design.md，2026-08-06 用户拍板）：
    # ① dl 工作流 worktree（*/.claude/worktrees/<name>）-> 跳过（工作流自带
    #    codegraph 纪律，2026-08-03 用户决议）；
    # ② dl-workflow 仓（主树+开发 worktree）-> **拦截**（恢复 2026-08-03
    #    「dl-workflow repo 本身要拦」决议，2026-08-05 _is_linked_worktree
    #    泛化曾误跳过），project_root 解析到**主树**——db/audit 全在主树，
    #    开发 worktree 内「无 db 无法解锁」的死锁根除；
    # ③ 其他仓 linked worktree -> 维持跳过（2026-08-06 拍板：纪律另有归属）。
    # 旧实现按会话 cwd 判定——跨仓编辑（会话开在 A 仓、改 dl-workflow
    # worktree 文件）拦不拦全凭会话碰巧开在哪（v2.113/2026-08-06 两实锤）。
    fp = Path(file_path)
    if not fp.is_absolute():
        fp = Path(_payload_cwd(payload)) / fp
    if _is_workflow_file(fp):
        return 0
    main_root, is_linked = _resolve_main_root(fp if fp.is_dir() else fp.parent)
    if main_root is None:
        return 0  # 非 git 项目 -> 放行（无项目 = 无 codegraph db = 无门禁意义）
    if main_root == _DLWF_ROOT:
        project_root = main_root  # ② dl-workflow：拦截，根落主树
    elif is_linked:
        return 0  # ③ 他仓 linked worktree：维持跳过
    else:
        project_root = main_root  # 他仓主树：维持拦截（旧行为）

    if not _is_existing_source_py(file_path, project_root):
        return 0  # 白名单跳过

    audit_dir = project_root / ".claude" / ".cg_audit"
    codegraph_db = project_root / ".codegraph" / "codegraph.db"

    warns = []
    fw = _freshness_warning(codegraph_db)
    if fw:
        warns.append(fw)

    if _has_query_this_session(audit_dir, payload):
        # 放行：本会话已查过结构。注入影响面（若有）。
        ctx = _affected_context(file_path, project_root)
        out_parts = warns + ([ctx] if ctx else [])
        if out_parts:
            sys.stdout.write("\n".join(out_parts) + "\n")
        return 0

    # 阻断：零查询就改源码
    dlwf_hint = (
        f"  本仓开发 worktree 内无 db——在 {project_root} 下跑上述命令（"
        "audit 落主树，gate 读主树）。\n"
        if project_root == _DLWF_ROOT
        else ""
    )
    hint = (
        f"[codegraph gate] 阻断：改已有源码 {file_path} 前需先查 codegraph（H15）。\n"
        f"  跑一次：`codegraph impact <symbol>` 或 `codegraph callers <symbol>` "
        f"或 `codegraph affected {file_path}`，审计留痕后即可放行。\n"
        f"{dlwf_hint}"
        f"  纯注释/格式改动：跑一次上述命令即可（不查结构不许改是设计目的）。\n"
        f"  {fw or '索引新鲜度正常。'}"
    )
    sys.stderr.write(hint + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
