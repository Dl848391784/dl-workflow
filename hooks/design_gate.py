#!/usr/bin/env python3
"""
PreToolUse(Edit|Write|MultiEdit) 门禁：本会话改第 2 个及以上不同 .py 源码
文件前，须先写过 designs/*.md（H8 design-first 用户级跨项目机械闸门）。

动机：[[troubleshoot-fix-flow]]——排查/修复应走「确认根因方案 → design.md
→ 动手」，但 prompt 级规则（superpowers/CLAUDE.md）是软约束，模型会跳过
（2026-08-03 v2.64-66 连改 dl_flow_engine/nodes/fence 多个 .py 无 design.md、
未确认方案）。正治=堵入口（弱模型优先原则：prompt 软、围栏硬）。

判定逻辑（镜像 codegraph_gate.py H15 模式）：
- 目标：改**已存在的 .py 源码文件**（白名单同 H15：非 .py / test_*.py /
  新建文件 / scripts/check_*.py / designs/ 一律放行）。
- 放行：本会话已写过 designs/*.md；或改的是本会话第 1 个源码文件；或改的是
  本会话已改过的同一文件（单文件迭代）。
- 阻断：本会话已改过 >=1 个不同源码文件、未写过 design.md，现又改另一个
  不同源码文件 -> exit 2 指回「先写 designs/<topic>.md」。

退出码语义（Claude Code hooks 约定）：exit 0 放行；exit 2 阻断（stderr 反馈）。

宁纵勿枉：非 git 项目 / 非 .py / 新建文件 / 留痕缺失 -> 放行。
"""

import json
import os
import subprocess
import sys
from pathlib import Path


# dl-workflow 主树根（v2.120，与 codegraph_gate.py 同构）：hooks 由
# settings.json 直引用 ~/.dl-workflow/hooks/*.py（不 copy），__file__
# 即主树真源；DL_WF_HOME env 优先（bashrc 导出；测试用其指向伪仓）。
_DLWF_ROOT = Path(
    os.environ.get("DL_WF_HOME", "").strip()
    or str(Path(__file__).resolve().parent.parent)
).resolve()


def _resolve_roots(d: Path) -> tuple[Path | None, Path | None, bool]:
    """d 所属 git 仓的 (工作树顶, **主树**根, 是否 linked worktree)（v2.120）。

    --show-toplevel 得 T；--git-common-dir 解析后 == T/.git -> 主树
    （main=T，False）；否则 common 的 parent 即主树根（True）。audit
    落账/门禁读取用主树根（gate/audit 同一根才不变相死锁）；design.md
    物理位置/白名单存在性判定用工作树顶（worktree 的 designs/ 与源码
    在工作树里）。非 git/命令失败 -> (None, None, False)（宁纵勿枉）。
    相对路径先对会话 cwd 解析由调用方完成。
    """
    try:
        top = subprocess.run(
            ["git", "-C", str(d), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if top.returncode != 0 or not top.stdout.strip():
            return None, None, False
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
            return toplevel, toplevel, False
        common_p = Path(common.stdout.strip())
        if not common_p.is_absolute():
            common_p = (d / common_p).resolve()
        if common_p == (toplevel / ".git").resolve():
            return toplevel, toplevel, False
        return toplevel, common_p.parent, True
    except (subprocess.TimeoutExpired, OSError):
        return None, None, False


def _is_workflow_file(path: Path) -> bool:
    """路径含 .claude/worktrees/<name> 段 -> dl 工作流 worktree 内文件。

    工作流有自己的 design 流程（plan:1 render-artifact 产 design.md +
    门控，其 design.md 由脚本写（非 Edit/Write 工具），本门禁的 audit
    看不到，会误拦 execute 阶段）。v2.120 起按被编辑文件判定（原按会话
    cwd，跨仓编辑漏判）。
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
    _fallback.log，历史 DESIGN 记录放行后续所有会话（2026-08-03 v2.67 漏网
    实证，designs/gate-session-isolation-fix-design.md）。"""
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


def _is_existing_source_py(file_path: str, project_root: Path) -> bool:
    """判定是否为需要门禁的目标：已存在的 .py 源码（白名单同 H15）。"""
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


def _session_edits(audit_dir: Path, payload: dict) -> tuple[set[str], bool]:
    """读本会话 audit log，返回 (已编辑的源码文件集合, 是否已写 design.md)。"""
    log = audit_dir / f"{_session_id(payload)}.log"
    srcs: set[str] = set()
    has_design = False
    if not log.exists():
        return srcs, has_design
    try:
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            _, kind, fp = parts
            if kind == "SRC":
                srcs.add(fp)
            elif kind == "DESIGN":
                has_design = True
    except OSError:
        pass
    return srcs, has_design


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
    # ① dl 工作流 worktree（*/.claude/worktrees/<name>）-> 跳过（工作流
    #    自带 design 流程：plan:1 render-artifact 产 design.md + 门控，
    #    其 design.md 由脚本写（非 Edit/Write 工具），本门禁 audit 看不到，
    #    会误拦 execute 阶段）；
    # ② dl-workflow 仓（主树+开发 worktree）-> **拦截**（恢复 2026-08-03
    #    「dl-workflow repo 本身要拦」决议——见文件头引用，2026-08-05
    #    _is_linked_worktree 泛化曾误跳过）；audit 落**主树**（gate/audit
    #    同一根），design.md 写在当前工作树 designs/（随分支合并）；
    # ③ 其他仓 linked worktree -> 维持跳过（2026-08-06 拍板）。
    # 旧实现按会话 cwd 判定——跨仓编辑拦不拦全凭会话碰巧开在哪。
    cwd = _payload_cwd(payload)
    fp = Path(file_path)
    if not fp.is_absolute():
        fp = Path(cwd) / fp
    if _is_workflow_file(fp):
        return 0
    toplevel, main_root, is_linked = _resolve_roots(fp if fp.is_dir() else fp.parent)
    if main_root is None:
        return 0  # 非 git 项目 -> 放行
    if main_root != _DLWF_ROOT and is_linked:
        return 0  # ③ 他仓 linked worktree：维持跳过

    if not _is_existing_source_py(file_path, toplevel):
        return 0  # 白名单跳过（非 .py / test / 新建文件 / check_*.py）

    audit_dir = main_root / ".claude" / ".design_audit"
    srcs, has_design = _session_edits(audit_dir, payload)

    if has_design:
        return 0  # 本会话已写 design.md -> 多文件改动已解锁
    if file_path in srcs:
        return 0  # 同一文件迭代 -> 单文件工作，放行
    if len(srcs) < 1:
        return 0  # 本会话第 1 个源码文件 -> 放行（H8 只管 2+ 文件）

    # 阻断：本会话第 2 个及以上不同源码文件，且无 design.md
    hint = (
        f"[design-first gate] 阻断：本会话已改过源码 {sorted(srcs)}，现又改 "
        f"{file_path}——多文件改动须先写设计文档（H8 / [[troubleshoot-fix-flow]]）。\n"
        f"  流程：确认根因方案（AskUserQuestion/用户拍板）-> 写 "
        f"{toplevel}/designs/<topic>.md（当前工作树 designs/，随分支合并）"
        " -> 再动手改代码。\n"
        f"  若本轮工作已有 design.md：在其中补一行当前改动范围即可留痕解锁。\n"
        f"  单文件修改不受此门禁影响（改回同一文件即放行）。"
    )
    sys.stderr.write(hint + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
