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


def _make_linked_worktree(repo: Path, name: str) -> Path:
    """repo 里建一个含初始 commit 的 linked worktree，返回其路径。

    `git worktree add` 需要至少一个 commit 才可建分支；worktree 路径必须在
    repo 工作树之外（git 拒绝在 repo 内嵌套）。2026-08-05 worktree-per-session
    并发：用户级 worktree 路径不匹配 .claude/worktrees/<name> 约定，测试走
    `_is_linked_worktree`（.git 指针文件）跳过分支。
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
        ["git", "-C", str(repo), "add", "paths.py"],
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
    """喂 stdin JSON 调 hook 脚本，返回 CompletedProcess。

    payload 里注入 cwd 字段（模拟 Claude Code hook 协议），hook 会据此反查项目根。
    """
    payload = dict(payload)  # 副本
    payload.setdefault("cwd", str(cwd))
    env = {
        "PATH": "/usr/bin:/usr/local/bin:/home/admin/.npm-global/bin",
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


def test_skip_workflow_worktree(repo: Path) -> None:
    """工作流会话（cwd 在 .claude/worktrees/<name>）跳过——2026-08-03 用户决议：
    codegraph 对 worktree 不拦（worktree 内 .codegraph db 不存在=无法解锁=死锁
    隐患；工作流的 codegraph 纪律由 plan:1 新鲜度前置自理）。"""
    wt = repo / ".claude" / "worktrees" / "wf1"
    wt.mkdir(parents=True)
    r = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": "paths.py"}},
        "t_wt",
        cwd=wt,
    )
    assert r.returncode == 0 and r.stderr == ""


def test_skip_linked_worktree(repo: Path) -> None:
    """git linked worktree（非 .claude/worktrees 约定路径）跳过——2026-08-05
    worktree-per-session 泛化（designs/worktree-per-session-concurrency-design.md）：
    用户级 worktree 内 .codegraph db gitignore 缺失=无法解锁=死锁，须与 dl worktree
    同跳。对照组=主树同文件零查询仍阻断（泛化未误伤主树）。"""
    wt = _make_linked_worktree(repo, "wt1")
    r = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": "paths.py"}},
        "t_wt_linked",
        cwd=wt,
    )
    assert r.returncode == 0 and r.stderr == ""

    r2 = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": "paths.py"}},
        "t_main_ctrl",
        cwd=repo,
    )
    assert r2.returncode == 2


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


# ─────────────────── v2.69 payload session_id 会话隔离 ───────────────────
# 同 test_design_gate.py：CLAUDE_SESSION_ID 在 hook 环境从未设置，
# 全塌缩 _fallback.log → 历史任何 codegraph 查询解锁之后所有会话。
# designs/gate-session-isolation-fix-design.md


def _run_psid(
    script: Path,
    payload: dict,
    cwd: Path,
    payload_sid: str | None = None,
) -> subprocess.CompletedProcess:
    """模拟真实 hook 环境：会话标识走 payload session_id，env 不设。"""
    payload = dict(payload)
    payload.setdefault("cwd", str(cwd))
    if payload_sid is not None:
        payload["session_id"] = payload_sid
    env = {"PATH": "/usr/bin:/usr/local/bin:/home/admin/.npm-global/bin"}
    return subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _audit_psid(repo: Path, command: str, sid: str) -> None:
    _run_psid(
        AUDIT,
        {"tool_name": "Bash", "tool_input": {"command": command}},
        repo,
        payload_sid=sid,
    )


def _gate_psid(repo: Path, fp: str, sid: str) -> subprocess.CompletedProcess:
    return _run_psid(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": fp}},
        repo,
        payload_sid=sid,
    )


def test_payload_sid_query_unlocks_same_session(repo: Path) -> None:
    """payload sid 记账：同 sid 查询留痕后改源码放行。"""
    _audit_psid(repo, "codegraph callers foo", "cs1")
    r = _gate_psid(repo, "paths.py", "cs1")
    assert r.returncode == 0


def test_payload_sid_query_does_not_unlock_other_session(repo: Path) -> None:
    """核心缺陷回归：cs1 的查询留痕不得解锁 cs2——历史查询解锁所有会话
    = H15 门禁失效（_fallback.log 塌缩实证）。"""
    _audit_psid(repo, "codegraph callers foo", "cs1")
    r = _gate_psid(repo, "paths.py", "cs2")
    assert r.returncode == 2


# ─────────────────── v2.120 按文件主树判定（gate-file-main-root-design.md） ───────────────────
# 用户策略（2026-08-06 拍板，恢复 2026-08-03「dl-workflow repo 本身要拦」决议）：
# ① dl 工作流 worktree（*/.claude/worktrees/）跳过；② dl-workflow 仓
# （主树+开发 worktree）**拦截**，db/audit 走主树（开发 worktree 解锁无死锁）；
# ③ 他仓 linked worktree 维持跳过（存量 test_skip_linked_worktree 覆盖）。


def _dlwf_env(repo: Path) -> dict:
    """把临时 repo 伪装成 dl-workflow 仓（hook 的 _DLWF_ROOT 取 DL_WF_HOME 优先）。"""
    return {"DL_WF_HOME": str(repo)}


def test_dlwf_main_tree_blocked_until_audit(repo: Path) -> None:
    """② dl-workflow 主树：零查询阻断 -> 主树查询解锁。"""
    env = _dlwf_env(repo)
    r = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": "paths.py"}},
        "dw1",
        cwd=repo,
        env_extra=env,
    )
    assert r.returncode == 2
    _run(
        AUDIT,
        {"tool_name": "Bash", "tool_input": {"command": "codegraph impact foo"}},
        "dw1",
        cwd=repo,
        env_extra=env,
    )
    r2 = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": "paths.py"}},
        "dw1",
        cwd=repo,
        env_extra=env,
    )
    assert r2.returncode == 0


def test_dlwf_dev_worktree_enforced_unlock_via_main_root(repo: Path) -> None:
    """② 核心场景：dl-workflow 开发 worktree 里改本仓源码**要拦**（2026-08-05
    泛化曾误跳过）；worktree 内无 db 不再死锁——audit 归主树（worktree 会话
    裸跑 codegraph 归主树），gate 读主树解锁。"""
    env = _dlwf_env(repo)
    wt = _make_linked_worktree(repo, "dlwf_wt")
    sid = "dw2"
    r = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": str(wt / "paths.py")}},
        sid,
        cwd=wt,
        env_extra=env,
    )
    assert r.returncode == 2, r.stderr
    assert str(repo) in r.stderr  # 阻断文案指路主树
    # worktree 会话里跑查询（写法=gate 指路「在主树下跑」），audit 须落主树
    _run(
        AUDIT,
        {
            "tool_name": "Bash",
            "tool_input": {"command": f"cd {repo} && codegraph impact foo"},
        },
        sid,
        cwd=wt,
        env_extra=env,
    )
    log = repo / ".claude" / ".cg_audit" / f"{sid}.log"
    assert log.exists() and "|impact|" in log.read_text()
    assert not (wt / ".claude" / ".cg_audit").exists()  # 不落 worktree
    r2 = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": str(wt / "paths.py")}},
        sid,
        cwd=wt,
        env_extra=env,
    )
    assert r2.returncode == 0


def test_dlwf_cross_repo_session_unlock_via_cd_prefix(
    repo: Path, tmp_path: Path
) -> None:
    """② 跨仓会话（会话开在 A 仓、改 dl-workflow worktree 文件——2026-08-06
    实锤场景）：按**被编辑文件**判定=拦；`cd 主树 && codegraph` 的 audit 经
    cd 前缀归主树解锁。"""
    env = _dlwf_env(repo)
    wt = _make_linked_worktree(repo, "dlwf_wt2")
    other = tmp_path / "other"
    other.mkdir()
    _init_git_repo(other)
    sid = "dw3"
    r = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": str(wt / "paths.py")}},
        sid,
        cwd=other,
        env_extra=env,
    )
    assert r.returncode == 2
    # 无 cd 前缀：查询归会话仓（other），dl-workflow 侧仍锁
    _run(
        AUDIT,
        {"tool_name": "Bash", "tool_input": {"command": "codegraph impact foo"}},
        sid,
        cwd=other,
        env_extra=env,
    )
    r1 = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": str(wt / "paths.py")}},
        sid,
        cwd=other,
        env_extra=env,
    )
    assert r1.returncode == 2
    # cd 前缀归主树 -> 解锁
    _run(
        AUDIT,
        {
            "tool_name": "Bash",
            "tool_input": {"command": f"cd {repo} && codegraph callers foo"},
        },
        sid,
        cwd=other,
        env_extra=env,
    )
    r2 = _run(
        GATE,
        {"tool_name": "Edit", "tool_input": {"file_path": str(wt / "paths.py")}},
        sid,
        cwd=other,
        env_extra=env,
    )
    assert r2.returncode == 0


def test_audit_cd_target_unresolvable_falls_back(repo: Path) -> None:
    """audit 归属兜底：cd 目标不存在/非绝对 -> 落会话 cwd 仓（宁纵勿枉）。"""
    _run(
        AUDIT,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "cd /nonexistent_xyz && codegraph impact foo"},
        },
        "dw4",
        cwd=repo,
    )
    log = repo / ".claude" / ".cg_audit" / "dw4.log"
    assert log.exists() and "|impact|" in log.read_text()


def test_audit_cd_tilde_expanded(repo: Path, tmp_path: Path) -> None:
    """v2.121：`cd ~/<repo> && codegraph` 的 ~ 须 expanduser——shell 会展开
    但 hook 读原始文本，v2.120 dogfooding 实测留痕串号到会话仓。"""
    fake_home = tmp_path / "home"
    home_repo = fake_home / "repo"
    home_repo.mkdir(parents=True)
    _init_git_repo(home_repo)
    _run(
        AUDIT,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "cd ~/repo && codegraph impact foo"},
        },
        "dt1",
        cwd=repo,
        env_extra={"HOME": str(fake_home)},
    )
    log = home_repo / ".claude" / ".cg_audit" / "dt1.log"
    assert log.exists() and "|impact|" in log.read_text()
    assert not (repo / ".claude" / ".cg_audit" / "dt1.log").exists()
