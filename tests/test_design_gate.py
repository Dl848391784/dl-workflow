"""
hooks/design_gate.py 与 hooks/design_audit.py 的单元测试。

对应 [[troubleshoot-fix-flow]] / H8 design-first 用户级跨项目机械闸门。
通过 subprocess 喂 stdin 调真实脚本（端到端，不 mock），与 hook 实际调用一致。

覆盖：
- 白名单跳过（非 .py / 新建 .py / test_*.py / designs/*.md / 工作流会话）
- 放行（本会话第 1 个源码文件；同一文件迭代；写过 design.md 后的多文件）
- 阻断（本会话第 2 个不同源码文件且无 design.md -> exit 2 指路）
- audit 留痕（SRC / DESIGN 分类；工作流会话不留痕）

gate/audit 的 session_id 取自 CLAUDE_SESSION_ID env；tmp_path 每次独立 -> 会话隔离。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


DLWF_ROOT = Path(__file__).resolve().parents[1]
GATE = DLWF_ROOT / "hooks" / "design_gate.py"
AUDIT = DLWF_ROOT / "hooks" / "design_audit.py"


def _init_git_repo(tmp_path: Path) -> Path:
    subprocess.run(
        ["git", "init", "-q", "-b", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return tmp_path


def _make_linked_worktree(repo: Path, name: str) -> Path:
    """repo 里建一个含初始 commit 的 linked worktree，返回其路径。

    2026-08-05 worktree-per-session 并发：用户级 worktree 路径不匹配
    .claude/worktrees/<name> 约定，测试走 `_is_linked_worktree`（.git 指针
    文件）跳过分支。与 test_codegraph_gate 的 helper 同构，各自内联防耦合。
    """
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "t@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "test"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "add", "a.py"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "init"],
        check=True,
        capture_output=True,
    )
    wt = repo.parent / name
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "-b", f"wt-{name}", str(wt)],
        check=True,
        capture_output=True,
    )
    return wt


def _run(
    script: Path,
    payload: dict,
    session_id: str,
    cwd: Path,
    env_extra: dict | None = None,
) -> subprocess.CompletedProcess:
    payload = dict(payload)
    payload.setdefault("cwd", str(cwd))
    env = {
        "PATH": "/usr/bin:/usr/local/bin",
        "CLAUDE_SESSION_ID": session_id,
    }
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _gate(
    repo: Path, fp: str, sid: str, cwd: Path | None = None
) -> subprocess.CompletedProcess:
    return _run(
        GATE, {"tool_name": "Edit", "tool_input": {"file_path": fp}}, sid, cwd or repo
    )


def _audit(repo: Path, fp: str, sid: str, cwd: Path | None = None) -> None:
    _run(
        AUDIT, {"tool_name": "Edit", "tool_input": {"file_path": fp}}, sid, cwd or repo
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """临时 git repo + 两个已存在源码文件 a.py/b.py + designs/ 目录。"""
    root = _init_git_repo(tmp_path)
    (root / "a.py").write_text("x = 1\n")
    (root / "b.py").write_text("y = 1\n")
    (root / "designs").mkdir()
    return root


# ─────────────────── 白名单跳过 ───────────────────


def test_skip_non_python(repo: Path) -> None:
    r = _gate(repo, "README.md", "s1")
    assert r.returncode == 0 and r.stderr == ""


def test_skip_new_python_file(repo: Path) -> None:
    r = _gate(repo, "newmodule.py", "s2")
    assert r.returncode == 0


def test_skip_test_file(repo: Path) -> None:
    (repo / "test_foo.py").write_text("# test\n")
    r = _gate(repo, "test_foo.py", "s3")
    assert r.returncode == 0


def test_skip_workflow_worktree(repo: Path) -> None:
    """工作流会话（cwd 在 .claude/worktrees/<name>）跳过——有自己的 design 流程。"""
    wt = repo / ".claude" / "worktrees" / "wf1"
    wt.mkdir(parents=True)
    sid = "s4_wt"
    _audit(repo, "a.py", sid, cwd=wt)
    r = _gate(repo, "b.py", sid, cwd=wt)  # 即便算第 2 个文件也放行
    assert r.returncode == 0 and r.stderr == ""


def test_skip_linked_worktree(repo: Path) -> None:
    """git linked worktree（非 .claude/worktrees 约定路径）跳过——2026-08-05
    worktree-per-session 泛化（designs/worktree-per-session-concurrency-design.md）：
    用户级 worktree 内审计目录/design 机制与主树不一致，须与 dl worktree 同跳。
    对照组=主树同会话第 2 个文件无 design 仍阻断（泛化未误伤主树）。"""
    # 注意：worktree 路径 = repo.parent/<name>；与 test_codegraph_gate 的 wt1 同名会
    # 撞同一 basetemp 路径（两个 repo 是同一 basetemp 下兄弟目录）——用独立名字。
    wt = _make_linked_worktree(repo, "wt_dsg")
    sid = "s_wt_linked"
    _audit(repo, "a.py", sid, cwd=wt)
    r = _gate(repo, "b.py", sid, cwd=wt)  # 即便算第 2 个文件也放行
    assert r.returncode == 0 and r.stderr == ""

    sid_main = "s_main_ctrl"
    _audit(repo, "a.py", sid_main)  # 主树第 1 个文件
    r2 = _gate(repo, "b.py", sid_main)  # 主树第 2 个文件无 design -> 阻断
    assert r2.returncode == 2


# ─────────────────── 放行 ───────────────────


def test_allow_first_source_file(repo: Path) -> None:
    r = _gate(repo, "a.py", "s5")
    assert r.returncode == 0 and r.stderr == ""


def test_allow_same_file_iteration(repo: Path) -> None:
    sid = "s6"
    _audit(repo, "a.py", sid)  # 本会话已改 a.py
    r = _gate(repo, "a.py", sid)  # 再改 a.py = 单文件迭代
    assert r.returncode == 0 and r.stderr == ""


def test_allow_after_design_md(repo: Path) -> None:
    sid = "s7"
    _audit(repo, "a.py", sid)  # 改 a.py
    _audit(repo, "designs/topic.md", sid)  # 写了 design.md
    r = _gate(repo, "b.py", sid)  # 第 2 个源码文件 -> 已解锁
    assert r.returncode == 0 and r.stderr == ""


# ─────────────────── 阻断 ───────────────────


def test_block_second_source_file_no_design(repo: Path) -> None:
    sid = "s8_block"
    _audit(repo, "a.py", sid)  # 本会话已改 a.py，无 design.md
    r = _gate(repo, "b.py", sid)  # 又改 b.py = 第 2 个不同源码文件
    assert r.returncode == 2
    assert "design" in r.stderr
    assert "designs/" in r.stderr


# ─────────────────── audit 留痕分类 ───────────────────


def test_audit_logs_src_and_design(repo: Path) -> None:
    sid = "s9"
    _audit(repo, "a.py", sid)
    _audit(repo, "designs/x.md", sid)
    _audit(repo, "README.md", sid)  # 非源码非设计，不留痕
    log = repo / ".claude" / ".design_audit" / f"{sid}.log"
    text = log.read_text(encoding="utf-8")
    assert "|SRC|a.py" in text
    assert "|DESIGN|designs/x.md" in text
    assert "README" not in text


def test_project_root_resolved_from_file_not_cwd(repo: Path, tmp_path: Path) -> None:
    """file-based 项目根（2026-08-03 用户决议：dl-workflow repo 本身要拦，
    design.md 落 dl-workflow/designs/）：从 repo(主项目) 的 cwd 改 repo2 的文件，
    留痕/判断都须在 repo2——用 repo 的 designs/ 是串号。"""
    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    _init_git_repo(repo2)
    (repo2 / "x.py").write_text("x = 1\n")
    (repo2 / "y.py").write_text("y = 1\n")
    (repo2 / "designs").mkdir()
    sid = "s_filebased"
    # cwd=repo（主项目），但改的是 repo2 的文件（绝对路径）
    _run(
        AUDIT,
        {"tool_name": "Edit", "tool_input": {"file_path": str(repo2 / "x.py")}},
        sid,
        repo,
    )
    r = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": str(repo2 / "y.py")}},
        sid,
        repo,
    )
    assert r.returncode == 2  # repo2 第 2 个源码文件，repo2 无 design.md
    # 写 repo2 的 design.md 解锁
    _run(
        AUDIT,
        {
            "tool_name": "Write",
            "tool_input": {"file_path": str(repo2 / "designs" / "t.md")},
        },
        sid,
        repo,
    )
    r2 = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": str(repo2 / "y.py")}},
        sid,
        repo,
    )
    assert r2.returncode == 0


# ─────────────────── v2.69 payload session_id 会话隔离 ───────────────────
# 实证缺陷：hook 环境里 CLAUDE_SESSION_ID 从未被设置，四 hook 全塌缩
# _fallback.log → 跨会话共享留痕（v2.67 上午 DESIGN 记录放行下午会话）。
# 修复：session_id 从 stdin payload 取（hooks 规范公共字段），
# transcript_path stem 双保险，env 向后兼容。
# designs/gate-session-isolation-fix-design.md


def _run_psid(
    script: Path,
    payload: dict,
    cwd: Path,
    payload_sid: str | None = None,
    transcript_sid: str | None = None,
    env_sid: str | None = None,
) -> subprocess.CompletedProcess:
    """模拟真实 hook 环境：会话标识走 payload，env 默认不设。"""
    payload = dict(payload)
    payload.setdefault("cwd", str(cwd))
    if payload_sid is not None:
        payload["session_id"] = payload_sid
    if transcript_sid is not None:
        payload["transcript_path"] = (
            f"/home/admin/.claude/projects/x/{transcript_sid}.jsonl"
        )
    env = {"PATH": "/usr/bin:/usr/local/bin"}
    if env_sid is not None:
        env["CLAUDE_SESSION_ID"] = env_sid
    return subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _gate_psid(repo: Path, fp: str, **kw) -> subprocess.CompletedProcess:
    return _run_psid(
        GATE, {"tool_name": "Edit", "tool_input": {"file_path": fp}}, repo, **kw
    )


def _audit_psid(repo: Path, fp: str, **kw) -> None:
    _run_psid(AUDIT, {"tool_name": "Edit", "tool_input": {"file_path": fp}}, repo, **kw)


def test_payload_sid_second_file_blocked_same_session(repo: Path) -> None:
    """payload session_id 记账（无 env）：同 sid 第 2 个源码文件阻断。"""
    _audit_psid(repo, "a.py", payload_sid="ps1")
    r = _gate_psid(repo, "b.py", payload_sid="ps1")
    assert r.returncode == 2 and "designs/" in r.stderr


def test_payload_sid_isolates_other_session(repo: Path) -> None:
    """核心缺陷回归：ps1 的 SRC 留痕不得影响 ps2——跨会话共享=门禁失效。"""
    _audit_psid(repo, "a.py", payload_sid="ps1")
    r = _gate_psid(repo, "b.py", payload_sid="ps2")
    assert r.returncode == 0 and r.stderr == ""


def test_transcript_path_stem_as_session_id(repo: Path) -> None:
    """payload 缺 session_id 字段时 transcript_path 文件名 stem 顶上。"""
    _audit_psid(repo, "a.py", transcript_sid="ts1")
    r = _gate_psid(repo, "b.py", transcript_sid="ts1")
    assert r.returncode == 2


def test_env_sid_backward_compatible(repo: Path) -> None:
    """env 注入路径向后兼容（payload 无 session 字段时）。"""
    _audit_psid(repo, "a.py", env_sid="es1")
    r = _gate_psid(repo, "b.py", env_sid="es1")
    assert r.returncode == 2


def test_payload_sid_preferred_over_env(repo: Path) -> None:
    """payload session_id 优先于 env（真源在 payload）。"""
    _audit_psid(repo, "a.py", payload_sid="pp1", env_sid="wrong")
    r = _gate_psid(repo, "b.py", payload_sid="pp1")
    assert r.returncode == 2


# ─────────────────── v2.120 按文件主树判定（gate-file-main-root-design.md） ───────────────────
# 用户策略（2026-08-06 拍板，恢复 2026-08-03「dl-workflow repo 本身要拦」决议）：
# dl-workflow 仓（主树+开发 worktree）**拦截**——audit 落主树（gate/audit 同一根），
# design.md 写当前工作树 designs/（kind 判定按工作树顶）。


def test_dlwf_dev_worktree_enforced(repo: Path) -> None:
    """dl-workflow 开发 worktree：第 2 个源码文件无 design.md -> 拦；audit
    落主树（不落 worktree）；worktree designs/ 写 design.md -> 解锁。"""
    env = {"DL_WF_HOME": str(repo)}
    wt = _make_linked_worktree(repo, "dlwf_dsg")
    (wt / "b.py").write_text("y = 1\n")
    (wt / "designs").mkdir(exist_ok=True)
    sid = "ddw1"
    # 第 1 个源码文件：audit 记账（落主树）
    _run(
        AUDIT,
        {"tool_name": "Edit", "tool_input": {"file_path": str(wt / "a.py")}},
        sid,
        cwd=wt,
        env_extra=env,
    )
    assert (repo / ".claude" / ".design_audit" / f"{sid}.log").exists()
    assert not (wt / ".claude" / ".design_audit").exists()
    # 第 2 个源码文件：拦
    r = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": str(wt / "b.py")}},
        sid,
        cwd=wt,
        env_extra=env,
    )
    assert r.returncode == 2 and "designs/" in r.stderr
    # worktree 当前工作树 designs/ 写 design.md -> 解锁
    _run(
        AUDIT,
        {
            "tool_name": "Write",
            "tool_input": {"file_path": str(wt / "designs" / "topic.md")},
        },
        sid,
        cwd=wt,
        env_extra=env,
    )
    r2 = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": str(wt / "b.py")}},
        sid,
        cwd=wt,
        env_extra=env,
    )
    assert r2.returncode == 0


def test_dlwf_cross_repo_session_enforced_by_file(repo: Path, tmp_path: Path) -> None:
    """跨仓会话（cwd 在他仓、改 dl-workflow 文件）：按**被编辑文件**判定=拦
    （旧实现按会话 cwd 跳过=漏判，v2.113/2026-08-06 两实锤）。"""
    env = {"DL_WF_HOME": str(repo)}
    other = tmp_path / "other_dsg"
    other.mkdir()
    _init_git_repo(other)
    sid = "ddw2"
    _run(
        AUDIT,
        {"tool_name": "Edit", "tool_input": {"file_path": str(repo / "a.py")}},
        sid,
        cwd=other,
        env_extra=env,
    )
    r = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": str(repo / "b.py")}},
        sid,
        cwd=other,
        env_extra=env,
    )
    assert r.returncode == 2
