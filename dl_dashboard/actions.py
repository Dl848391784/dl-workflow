"""写操作：create / statement / inject / gate 放行 / /dl 指令 / 重新驱动。

inject 语义对齐 ~/scripts/wf_ctl.py cmd_inject：注入目标 = 当前 node#step 的
tui-step-needuser 段台账（唯一权威源），找不到即中止，禁回落最新段
（两轮竞态实爆教训：注进已完成段触发重写）。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from dl_dashboard.scanner import meta_root

DLWF = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DLWF))

import dl_flow_engine as engine  # noqa: E402

log = logging.getLogger("dl_dashboard.actions")

ALLOWED_DL_CMDS = ("advance", "step-pass", "dispute", "state-reset")


def create_workflow(project: Path, name: str, statement: str, mgr,
                    timeout: int = 600) -> tuple[bool, str]:
    """launcher 建实例（headless）-> 置 problem_statement -> 起 driver。

    成败判定沿用 wf_ctl：实例落盘（state.json 存在）即建成，launcher
    超时/非零 rc 只作消息展示（driver 在 TTY 缺失下徘徊是已知形态）。
    """
    try:
        p = subprocess.run(
            ["bash", str(DLWF / "scripts" / "workflow" / "dl-launch.sh"),
             "--workflow", name, "--headless"],
            cwd=str(project), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=timeout,
        )
        tail = (p.stdout + p.stderr)[-500:]
    except subprocess.TimeoutExpired:
        tail = "launcher 超时（实例已落盘即达目的，driver 残留自查）"
    state_p = meta_root(project, name) / "state.json"
    if not state_p.exists():
        return False, f"建实例失败：{tail}"
    engine.set_problem_statement(project, name, statement)
    state = engine.load_state(project, name)
    mgr.start(project, name, Path(state["worktree_path"]))
    return True, f"工作流 {name} 已建并启动 driver。{tail[-200:]}"


def _find_needuser_sid(project: Path, name: str, state: dict, nid: str, cur: int) -> str | None:
    for seg in reversed(state.get("segment_sessions", [])):
        if (seg.get("kind") == "tui-step-needuser"
                and seg.get("node") == nid and seg.get("sub_step") == cur):
            return seg["session_id"]
    return None


def inject_answer(project: Path, name: str, answer: str) -> tuple[bool, str]:
    state = engine.normalize_state(engine.load_state(project, name))
    node = engine.get_node(state["phase"], state["sub_index"])
    nid = engine.node_id(node.phase, node.sub)
    cur = state.get("sub_step_index", 1)
    step = engine.sub_step_at(node, cur)
    sid = _find_needuser_sid(project, name, state, nid, cur)
    if sid is None:
        return False, (f"中止注入：{nid}#{cur} 无 tui-step-needuser 段记录——"
                       "state 可能已推进（先刷新确认当前步）")
    meta = meta_root(project, name)
    ov = engine.segment_spawn_overrides(node, step)
    cmd = [
        "claude", "--resume", sid,
        "--settings", str(meta / "settings.drive-tui.json"),
        "--append-system-prompt-file", str(meta / f"tui-rules.{nid}.md"),
        "--permission-mode", "acceptEdits",
    ]
    if ov["tools"]:
        tools = tuple(ov["tools"]) + ("AskUserQuestion", "TaskCreate", "TaskUpdate")
        cmd += ["--tools", ",".join(tools)]
    cmd += ["-p", answer]
    cmd += list(engine.NO_MCP_ARGS)
    env = dict(os.environ)
    env.update(ov.get("env") or {})
    log.info("inject -> %s#%s sid=%s…", nid, cur, sid[:8])
    p = subprocess.run(cmd, cwd=state["worktree_path"], env=env,
                       stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if p.returncode != 0:
        return False, f"注入失败 rc={p.returncode}：{(p.stdout + p.stderr)[-300:]}"
    return True, f"已注入 {nid}#{cur}"


def gate_release(project: Path, name: str) -> tuple[bool, str]:
    """gate 放行 = engine CLI subgate-pass（/dl gate 同路由 release_subgate）。"""
    state = engine.load_state(project, name)
    p = subprocess.run(
        ["python3", str(DLWF / "dl_flow_engine.py"), "subgate-pass", name],
        cwd=state["worktree_path"], stdin=subprocess.DEVNULL,
        capture_output=True, text=True,
    )
    msg = (p.stdout + p.stderr).strip()
    return p.returncode == 0, msg


def dl_command(project: Path, name: str, cmd: str, value: str | None = None) -> tuple[bool, str]:
    if cmd not in ALLOWED_DL_CMDS:
        return False, f"不支持的指令 {cmd}（白名单：{'/'.join(ALLOWED_DL_CMDS)}）"
    state = engine.load_state(project, name)
    argv = ["python3", str(DLWF / "dl_flow_engine.py"), cmd, name]
    if value:
        argv.append(value)
    p = subprocess.run(argv, cwd=state["worktree_path"], stdin=subprocess.DEVNULL,
                       capture_output=True, text=True)
    return p.returncode == 0, (p.stdout + p.stderr).strip()


def restart_drive(project: Path, name: str, mgr) -> tuple[bool, str]:
    """driver 死/断点后重新驱动（续跑非重来：state 全在盘上）。"""
    if mgr.alive(project, name):
        return False, "driver 仍在运行，无需重驱"
    state = engine.load_state(project, name)
    pid = mgr.start(project, name, Path(state["worktree_path"]))
    return True, f"driver 已重启 pid={pid}"
