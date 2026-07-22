"""
.claude/hooks/codegraph_gate.py 与 codegraph_audit.py 的单元测试。

对应 PROJECT.md 规则 H15（designs/codegraph_enforcement_gate_design.md 档 3）。
通过 subprocess 喂 stdin 调用真实脚本（端到端，不 mock），与 hook 实际调用方式一致。

覆盖四场景（design §Verify）：
- 白名单跳过（非 .py / 新建 .py）
- 阻断（改已有源码 + 零 codegraph 查询）
- 放行（audit 留痕后改源码）
- 留痕解析（非 codegraph 命令不留痕；callers/impact 等留痕）

注意：gate 的 session_id 取自 CLAUDE_SESSION_ID env，回退 "_fallback"。
测试用独立 session_id 隔离，避免污染真实会话 audit log。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GATE = PROJECT_ROOT / ".claude" / "hooks" / "codegraph_gate.py"
AUDIT = PROJECT_ROOT / ".claude" / "hooks" / "codegraph_audit.py"
AUDIT_DIR = PROJECT_ROOT / ".claude" / ".cg_audit"

# 门禁目标：paths.py 一定存在且是 .py 源码
EXISTING_SRC = PROJECT_ROOT / "paths.py"


def _run(script: Path, payload: dict, session_id: str) -> subprocess.CompletedProcess:
    """喂 stdin JSON 调 hook 脚本，返回 CompletedProcess。"""
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


# ─────────────────── 白名单跳过 ───────────────────


def test_skip_non_python(tmp_path: Path) -> None:
    """非 .py 文件直接放行，exit 0 无输出。"""
    r = _run(GATE, {"tool_name": "Edit", "tool_input": {"file_path": "README.md"}}, "t1")
    assert r.returncode == 0
    assert r.stdout == ""
    assert r.stderr == ""


def test_skip_new_python_file(tmp_path: Path) -> None:
    """仓库中不存在的新建 .py 放行（新建不涉及改既有符号）。"""
    r = _run(GATE, {"tool_name": "Write", "tool_input": {"file_path": "new_module/new_file.py"}}, "t2")
    assert r.returncode == 0


def test_skip_test_file() -> None:
    """test_*.py 是测试代码非业务源码，放行。"""
    r = _run(GATE, {"tool_name": "Edit", "tool_input": {"file_path": "test_cases/test_foo.py"}}, "t3")
    assert r.returncode == 0


# ─────────────────── 阻断 ───────────────────


def test_block_existing_src_zero_query() -> None:
    """改已有源码 + 本会话零 codegraph 查询 -> 阻断 exit 2 + H15 提示。"""
    sid = "t4_zero_query"
    # 确保该 session 无 audit log（模拟零查询）
    log = AUDIT_DIR / f"{sid}.log"
    if log.exists():
        log.unlink()
    r = _run(GATE, {"tool_name": "Edit", "tool_input": {"file_path": str(EXISTING_SRC)}}, sid)
    assert r.returncode == 2
    assert "H15" in r.stderr
    assert "codegraph" in r.stderr
    assert str(EXISTING_SRC) in r.stderr or "paths.py" in r.stderr


# ─────────────────── 放行（audit 留痕后）───────────────────


def test_allow_after_audit_trail() -> None:
    """先 audit 留痕一次 callers 查询，再改源码 -> 放行 exit 0。"""
    sid = "t5_audit_trail"
    log = AUDIT_DIR / f"{sid}.log"
    if log.exists():
        log.unlink()

    # 1) PostToolUse 留痕
    ar = _run(AUDIT, {"tool_name": "Bash", "tool_input": {"command": "codegraph callers compute_ic"}}, sid)
    assert ar.returncode == 0
    assert log.exists()
    trail = log.read_text(encoding="utf-8")
    assert "|callers|" in trail and "compute_ic" in trail

    # 2) PreToolUse 放行
    gr = _run(GATE, {"tool_name": "Edit", "tool_input": {"file_path": str(EXISTING_SRC)}}, sid)
    assert gr.returncode == 0


def test_allow_after_impact_trail() -> None:
    """impact 子命令同样留痕放行（覆盖另一被追踪子命令）。"""
    sid = "t6_impact_trail"
    log = AUDIT_DIR / f"{sid}.log"
    if log.exists():
        log.unlink()
    _run(AUDIT, {"tool_name": "Bash", "tool_input": {"command": "codegraph impact compute_ic"}}, sid)
    gr = _run(GATE, {"tool_name": "Edit", "tool_input": {"file_path": str(EXISTING_SRC)}}, sid)
    assert gr.returncode == 0


# ─────────────────── audit 留痕解析 ───────────────────


def test_audit_ignores_non_codegraph() -> None:
    """非 codegraph 的 Bash 命令不留痕（audit log 不增长）。"""
    sid = "t7_nocodegraph"
    log = AUDIT_DIR / f"{sid}.log"
    if log.exists():
        log.unlink()
    _run(AUDIT, {"tool_name": "Bash", "tool_input": {"command": "pytest test_cases/ -x"}}, sid)
    assert not log.exists()


def test_audit_parses_qualified_path() -> None:
    """绝对路径调 codegraph（/home/.../codegraph）也能正确留痕。"""
    sid = "t8_qualified"
    log = AUDIT_DIR / f"{sid}.log"
    if log.exists():
        log.unlink()
    _run(
        AUDIT,
        {"tool_name": "Bash", "tool_input": {"command": "/home/admin/.npm-global/bin/codegraph impact compute_ic"}},
        sid,
    )
    assert log.exists()
    assert "|impact|" in log.read_text(encoding="utf-8")


# ─────────────────── 解析健壮性 ───────────────────


def test_gate_handles_malformed_stdin() -> None:
    """非法 JSON 不阻断业务编辑（宁纵勿枉）。"""
    env = {"CLAUDE_SESSION_ID": "t9_malformed", "PATH": "/usr/bin"}
    r = subprocess.run(
        [sys.executable, str(GATE)],
        input="{not json",
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert r.returncode == 0


def test_audit_handles_malformed_stdin() -> None:
    r = subprocess.run(
        [sys.executable, str(AUDIT)],
        input="{not json",
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin"},
        timeout=30,
    )
    assert r.returncode == 0
