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


def _run(
    script: Path, payload: dict, session_id: str, cwd: Path
) -> subprocess.CompletedProcess:
    payload = dict(payload)
    payload.setdefault("cwd", str(cwd))
    env = {
        "PATH": "/usr/bin:/usr/local/bin",
        "CLAUDE_SESSION_ID": session_id,
    }
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
