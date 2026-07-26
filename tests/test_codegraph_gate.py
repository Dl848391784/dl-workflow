"""
hooks/codegraph_gate.py 与 hooks/codegraph_audit.py 的单元测试（dl-workflow v0.1+）。

对应 designs/codegraph_enforcement_gate_design.md（档 3）。
通过 subprocess 喂 stdin 调用真实脚本（端到端，不 mock），与 hook 实际调用方式一致。

覆盖四场景：
- 白名单跳过（非 .py / 新建 .py / test_*.py / scripts/check_*.py）
- 阻断（改已有源码 + 零 codegraph 查询）
- 放行（audit 留痕后改源码）
- 留痕解析（非 codegraph 命令不留痕；callers/impact 等留痕）

**dl-workflow 版本关键点**：
- hook 从 payload.cwd 用 git rev-parse 反查项目根（不再依赖 __file__.parents[2]）
- 因此测试必须提供 `cwd` 字段指向一个临时 git repo；audit_dir 落在该 repo 内。
- tmp_path 每次测试独立 -> 天然会话隔离，无需污染真实 audit log。

注意：gate 的 session_id 取自 CLAUDE_SESSION_ID env，回退 "_fallback"。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


DLWF_ROOT = Path(__file__).resolve().parents[1]
GATE = DLWF_ROOT / "hooks" / "codegraph_gate.py"
AUDIT = DLWF_ROOT / "hooks" / "codegraph_audit.py"


def _init_git_repo(tmp_path: Path) -> Path:
    """在 tmp_path 里建一个 git repo，返回 repo 根路径。"""
    subprocess.run(
        ["git", "init", "-q", "-b", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    # 需要 user.email/name 才能 commit（虽然本测试不 commit，但 git 反查不需要）
    return tmp_path


def _run(
    script: Path,
    payload: dict,
    session_id: str,
    cwd: Path,
) -> subprocess.CompletedProcess:
    """喂 stdin JSON 调 hook 脚本，返回 CompletedProcess。

    payload 里注入 cwd 字段（模拟 Claude Code hook 协议），hook 会据此反查项目根。
    """
    payload = dict(payload)  # 副本
    payload.setdefault("cwd", str(cwd))
    env = {
        "PATH": "/usr/bin:/usr/local/bin:/home/admin/.npm-global/bin",
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


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """临时 git repo + 一个已存在的 paths.py 源文件（门禁目标）。"""
    repo_root = _init_git_repo(tmp_path)
    (repo_root / "paths.py").write_text("# fake paths module\n")
    return repo_root


# ─────────────────── 白名单跳过 ───────────────────


def test_skip_non_python(repo: Path) -> None:
    """非 .py 文件直接放行，exit 0 无输出。"""
    r = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": "README.md"}},
        "t1",
        cwd=repo,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""
    assert r.stderr == ""


def test_skip_new_python_file(repo: Path) -> None:
    """.py 但仓库无此路径（新建）-> 放行。"""
    r = _run(
        GATE,
        {"tool_name": "Write", "tool_input": {"file_path": "newmodule.py"}},
        "t2",
        cwd=repo,
    )
    assert r.returncode == 0
    assert r.stdout == ""


def test_skip_test_file(repo: Path) -> None:
    """test_*.py 白名单跳过（即便已存在）。"""
    (repo / "test_foo.py").write_text("# test\n")
    r = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": "test_foo.py"}},
        "t3",
        cwd=repo,
    )
    assert r.returncode == 0


# ─────────────────── 阻断（零查询） ───────────────────


def test_block_existing_src_zero_query(repo: Path) -> None:
    """改已有 .py 且本会话无 codegraph 留痕 -> 阻断（exit 2 + stderr 提示）。"""
    sid = "t4_block"
    log = repo / ".claude" / ".cg_audit" / f"{sid}.log"
    if log.exists():
        log.unlink()

    r = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": "paths.py"}},
        sid,
        cwd=repo,
    )
    assert r.returncode == 2, f"got {r.returncode}, stderr={r.stderr}"
    assert "codegraph gate" in r.stderr
    assert "paths.py" in r.stderr


# ─────────────────── 放行（留痕后） ───────────────────


def test_allow_after_audit_trail(repo: Path) -> None:
    """audit 留痕过 codegraph impact 后，改同 .py 应放行。"""
    sid = "t5_audit_trail"

    # 步 1：跑 audit 一次 codegraph impact
    ar = _run(
        AUDIT,
        {"tool_name": "Bash", "tool_input": {"command": "codegraph impact paths.py"}},
        sid,
        cwd=repo,
    )
    assert ar.returncode == 0

    audit_log = repo / ".claude" / ".cg_audit" / f"{sid}.log"
    assert audit_log.exists(), f"audit log 未生成: {audit_log}"
    content = audit_log.read_text()
    assert "|impact|" in content, f"未留痕 impact: {content}"

    # 步 2：改同 .py -> 应放行
    gr = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": "paths.py"}},
        sid,
        cwd=repo,
    )
    assert gr.returncode == 0, f"应放行，实为 {gr.returncode}, stderr={gr.stderr}"


def test_allow_after_callers_trail(repo: Path) -> None:
    """留痕 callers 后同样放行（多种子命令验证）。"""
    sid = "t6_callers"
    _run(
        AUDIT,
        {"tool_name": "Bash", "tool_input": {"command": "codegraph callers some_func"}},
        sid,
        cwd=repo,
    )
    gr = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": "paths.py"}},
        sid,
        cwd=repo,
    )
    assert gr.returncode == 0


# ─────────────────── audit 留痕解析 ───────────────────


def test_audit_ignores_non_codegraph(repo: Path) -> None:
    """非 codegraph 命令（如 ls）不留痕。"""
    sid = "t7_non_cg"
    _run(
        AUDIT,
        {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
        sid,
        cwd=repo,
    )
    log = repo / ".claude" / ".cg_audit" / f"{sid}.log"
    assert not log.exists(), "非 codegraph 不应留痕"


def test_audit_parses_qualified_path(repo: Path) -> None:
    """`/full/path/codegraph impact xxx` 也能被识别（前缀路径容忍）。"""
    sid = "t8_qualified"
    _run(
        AUDIT,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "/home/x/codegraph impact foo.py"},
        },
        sid,
        cwd=repo,
    )
    log = repo / ".claude" / ".cg_audit" / f"{sid}.log"
    assert log.exists()
    assert "|impact|" in log.read_text()


# ─────────────────── 容错 ───────────────────


def test_gate_handles_malformed_stdin(repo: Path) -> None:
    """损坏 JSON 输入不阻断（宁纵勿枉）。"""
    r = subprocess.run(
        [sys.executable, str(GATE)],
        input="{not json",
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin"},
        timeout=30,
    )
    assert r.returncode == 0


def test_audit_handles_malformed_stdin(repo: Path) -> None:
    """audit 损坏 JSON 也不阻断。"""
    r = subprocess.run(
        [sys.executable, str(AUDIT)],
        input="{not json",
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin"},
        timeout=30,
    )
    assert r.returncode == 0


def test_gate_handles_non_git_cwd(tmp_path: Path) -> None:
    """cwd 不在 git repo 内 -> 放行（无处判定，宁纵勿枉）。"""
    # tmp_path 本身不是 git repo
    r = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": "some.py"}},
        "t_nogit",
        cwd=tmp_path,
    )
    assert r.returncode == 0
