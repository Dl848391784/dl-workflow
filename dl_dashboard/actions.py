"""写操作：create / statement / inject / gate 放行 / /dl 指令 / 重新驱动。

inject 语义对齐 ~/scripts/wf_ctl.py cmd_inject：注入目标 = 当前 node#step 的
tui-step-needuser 段台账（唯一权威源），找不到即中止，禁回落最新段
（两轮竞态实爆教训：注进已完成段触发重写）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from dl_dashboard.scanner import meta_root

DLWF = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DLWF))

import dl_flow_engine as engine  # noqa: E402

log = logging.getLogger("dl_dashboard.actions")

ALLOWED_DL_CMDS = ("advance", "step-pass", "dispute", "state-reset", "next", "back", "jump")


def _get_state(project: Path, name: str) -> tuple[dict | None, str | None]:
    state = engine.load_state(project, name)
    if state is None:
        return None, f"工作流 {name} 的 state.json 缺失"
    if not state.get("worktree_path"):
        return None, "state.json 缺 worktree_path"
    return state, None


# 创建的两维开关（dl-launch.sh 原生语义）：
# 范围 scope（互斥）：fermate=plan-only / forte=全 5 阶段
# 轨道 tacet（独立布尔）：True=--force-tacet 实验轨道（六步脊柱，其余静默）
_SCOPE_FLAGS = {"fermate": "--fermate", "forte": "--forte"}


def create_workflow(project: Path, name: str, statement: str, mgr,
                    scope: str = "fermate", tacet: bool = False,
                    provider_env: dict | None = None,
                    timeout: int = 600) -> tuple[bool, str]:
    """launcher 建实例（headless）-> 置 problem_statement -> 起 driver。

    两维正交：scope=fermate|forte（互斥），tacet=True|False（独立）。
    成败判定沿用 wf_ctl：实例落盘（state.json 存在）即建成，launcher
    超时/非零 rc 只作消息展示（driver 在 TTY 缺失下徘徊是已知形态）。
    """
    if scope not in _SCOPE_FLAGS:
        return False, f"未知范围 {scope}（可选：{'/'.join(_SCOPE_FLAGS)}）"
    argv = ["bash", str(DLWF / "scripts" / "workflow" / "dl-launch.sh"),
            "--workflow", name, "--headless", _SCOPE_FLAGS[scope]]
    if tacet:
        argv.append("--force-tacet")
    try:
        p = subprocess.run(argv,
            cwd=str(project), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=timeout,
            errors="replace",
        )
        tail = (p.stdout + p.stderr)[-500:]
    except subprocess.TimeoutExpired:
        tail = "launcher 超时（实例已落盘即达目的，driver 残留自查）"
    state_p = meta_root(project, name) / "state.json"
    if not state_p.exists():
        return False, f"建实例失败：{tail}"
    engine.set_problem_statement(project, name, statement)
    state = engine.load_state(project, name)
    mgr.start(project, name, Path(state["worktree_path"]), env=provider_env)
    return True, f"工作流 {name} 已建并启动 driver。{tail[-200:]}"


def _find_needuser_sid(project: Path, name: str, state: dict, nid: str, cur: int) -> str | None:
    for seg in reversed(state.get("segment_sessions", [])):
        if (seg.get("kind") == "tui-step-needuser"
                and seg.get("node") == nid and seg.get("sub_step") == cur):
            return seg["session_id"]
    return None


# ---------- 已答标记（dashboard-answered-marker-design §2.2/§6） ----------


def _answered_path(project: Path, name: str) -> Path:
    return meta_root(project, name) / "answered.json"


def _read_need_user(project: Path, name: str) -> "dict | None":
    try:
        data = json.loads(
            (meta_root(project, name) / "need_user.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _questions_sha(nu: dict) -> "str | None":
    """问题内容 hash（E1 修订：替代 ts 判覆盖——none 重试对同一批问题重
    stash 时 ts 必变但内容 hash 不变，标记不再被误失效）。"""
    qs = nu.get("questions")
    if not isinstance(qs, list):
        return None
    return hashlib.sha1(
        json.dumps(qs, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _block_verdict_newer(project: Path, name: str, cur: int,
                         minor_key: "str | None", answered_at: str) -> bool:
    """answered_at 之后本步有无 kind=gate/gate=blocked 裁决——有 = 答案被判
    不足，重答是 rework 正路，标记必须放行（否则 escalate 后永远无法重答）。
    ts 字符串比较成立（双侧同 _now() 格式）。"""
    ev = project / ".claude" / "evidence" / f"{name}.jsonl"
    try:
        lines = ev.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (rec.get("kind") == "gate" and rec.get("gate") == "blocked"
                and rec.get("sub_step") == cur
                and rec.get("minor_stage") == minor_key
                and str(rec.get("ts", "")) > answered_at):
            return True
    return False


def answered_at_if_covers(project: Path, name: str) -> "str | None":
    """当前问题卡是否已被答案覆盖（已注入未推进窗口）。返回注入时间或 None。

    覆盖 ⟺ ①marker(node, sub_step) == state 当前位置 且 ②marker.questions_sha
    == need_user.json 当前 questions hash（重 stash 同内容仍覆盖）且
    ③answered_at 之后无本步 block 裁决（被判不足 = 放行重答）——纯计算自
    失效，无需清理；need_user.json 缺失 = 无卡可覆盖 → None。
    """
    state = engine.load_state(project, name)
    if state is None:
        return None
    try:
        marker = json.loads(_answered_path(project, name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(marker, dict):
        return None
    nu = _read_need_user(project, name)
    sha = _questions_sha(nu) if nu else None
    if sha is None or marker.get("questions_sha") != sha:
        return None
    if (marker.get("node") != state.get("node")
            or marker.get("sub_step") != state.get("sub_step_index", 1)):
        return None
    answered_at = marker.get("answered_at")
    if not answered_at:
        return "（时间缺失）"
    node = engine.get_node(state["phase"], state["sub_index"])
    if _block_verdict_newer(project, name, state.get("sub_step_index", 1),
                            node.minor_key, answered_at):
        return None
    return answered_at


def inject_ready(project: Path, name: str) -> bool:
    """注入目标段是否已落台账（need_user.json 已展示 与 可注入 之间有时间窗：
    问题在段运行中落盘，段记录在完成时落台账——窗口内提交必被中止，
    前端据此显示「准备中」而非可提交表单）。
    已答窗口（inject 成功 → 门控推进前段台账仍在原位）：被 answered 标记
    覆盖 → False（D1：按钮不复活，防 double-inject）。"""
    state = engine.load_state(project, name)
    if state is None:
        return False
    nid = state.get("node")
    cur = state.get("sub_step_index", 1)
    if _find_needuser_sid(project, name, state, nid, cur) is None:
        return False
    return answered_at_if_covers(project, name) is None


def inject_answer(project: Path, name: str, answer: str,
                  provider_env: dict | None = None) -> tuple[bool, str]:
    state_raw = engine.load_state(project, name)
    if state_raw is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    if not state_raw.get("worktree_path"):
        return False, "state.json 缺 worktree_path"
    state = engine.normalize_state(state_raw)
    node = engine.get_node(state["phase"], state["sub_index"])
    nid = engine.node_id(node.phase, node.sub)
    cur = state.get("sub_step_index", 1)
    step = engine.sub_step_at(node, cur)
    sid = _find_needuser_sid(project, name, state, nid, cur)
    if sid is None:
        return False, (f"中止注入：{nid}#{cur} 无 tui-step-needuser 段记录——"
                       "state 可能已推进（先刷新确认当前步）")
    covered_at = answered_at_if_covers(project, name)
    if covered_at is not None:
        return False, (f"中止注入：{nid}#{cur} 答案已注入过（{covered_at}）——"
                       "防重复注入；新问题落盘后自动恢复可注入")
    meta = meta_root(project, name)
    ov = engine.segment_spawn_overrides(node, step)
    cmd = [
        "claude", "--resume", sid,
        "--settings", str(meta / "settings.drive-tui.json"),
        "--append-system-prompt-file", str(meta / f"tui-rules.{nid}.md"),
        "--permission-mode", "acceptEdits",
    ]
    if ov["tools"]:
        # -p 一次性轮无真人可答：AskUserQuestion 结构性移除（调了也是立即
        # 报错的白费轮，还诱导模型走「重问」死路——E2 实爆），只补清单工具
        tools = tuple(ov["tools"]) + ("TaskCreate", "TaskUpdate")
        cmd += ["--tools", ",".join(tools)]
    else:
        cmd += ["--disallowedTools", "AskUserQuestion"]
    # E2：一次性注入包装——声明「之后无人可答」防重问死路（-p 单轮会话，
    # 文字重问 = 零 trace 收场），指路落库协议；缺漏由门控裁决不重问
    payload = (
        f"用户已就当前交互子步骤 {nid}#{cur} 的问题清单给出回答"
        f"（本消息 = 一次性注入，之后无人可答——禁止重新提问）：\n\n"
        f"{answer}\n\n"
        f"立即执行（不等更多输入）：\n"
        f"1. 把上述回答逐条映射到问题清单（{meta}/need_user.json，"
        f"含逐字原文与 sources 出处包）；\n"
        f"2. 按 append-trace 协议把本步结论落 evidence（主仓绝对路径——"
        f"相对路径会写到 worktree，hook 读不到）；\n"
        f"3. 输出 ### STEP_DONE: {cur} 结束。\n"
        f"回答有缺失/含糊处：在 trace 中如实标注，由门控裁决——不要因此重新提问。"
    )
    cmd += ["-p", payload]
    cmd += list(engine.NO_MCP_ARGS)
    env = dict(os.environ)
    env.update(provider_env or {})
    env.update(ov.get("env") or {})
    log.info("inject -> %s#%s sid=%s…", nid, cur, sid[:8])
    # errors="replace"：provider 偶发非法 UTF-8——strict 解码崩 server 线程
    # （同类：dl_drive run_session / engine run_judge 同款修复）
    p = subprocess.run(cmd, cwd=state["worktree_path"], env=env,
                       stdin=subprocess.DEVNULL, capture_output=True, text=True,
                       errors="replace")
    if p.returncode != 0:
        return False, f"注入失败 rc={p.returncode}：{(p.stdout + p.stderr)[-300:]}"
    # 已答标记：覆盖当前问题卡直到 state 推进 / 问题内容变 / 撞 block（自失效）
    nu = _read_need_user(project, name)
    _answered_path(project, name).write_text(
        json.dumps({
            "node": nid,
            "sub_step": cur,
            "questions_sha": _questions_sha(nu) if nu else None,
            "answered_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }),
        encoding="utf-8",
    )
    return True, f"已注入 {nid}#{cur}"


def gate_release(project: Path, name: str) -> tuple[bool, str]:
    """gate 放行 = /dl gate 同路由（dl-cmd.sh gate 单源：held_for_gate →
    engine subgate-pass 门栏放行 / GATED_AFTER 阶段闸门置 passed 双分支）。
    原直调 engine subgate-pass 只有门栏路由——阶段闸门（held 之外的第二
    等待态）撞「无标记」报错，dashboard 放不了行（静态审计实锤）。"""
    state, err = _get_state(project, name)
    if err:
        return False, err
    p = subprocess.run(
        ["bash", str(DLWF / "scripts" / "workflow" / "dl-cmd.sh"), "gate"],
        cwd=state["worktree_path"], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, errors="replace",
    )
    msg = (p.stdout + p.stderr).strip()
    return p.returncode == 0, msg


def dl_command(project: Path, name: str, cmd: str, value: str | None = None) -> tuple[bool, str]:
    if cmd not in ALLOWED_DL_CMDS:
        return False, f"不支持的指令 {cmd}（白名单：{'/'.join(ALLOWED_DL_CMDS)}）"
    state, err = _get_state(project, name)
    if err:
        return False, err
    wt = state["worktree_path"]
    if cmd in ("next", "back", "jump"):
        if cmd == "jump" and not value:
            return False, "jump 需要参数（目标 phase）"
        argv = ["bash", str(DLWF / "scripts" / "workflow" / "dl-cmd.sh"), cmd]
        if value:
            argv.append(value)
        p = subprocess.run(argv, cwd=wt, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, errors="replace")
        return p.returncode == 0, (p.stdout + p.stderr).strip()
    argv = ["python3", str(DLWF / "dl_flow_engine.py"), cmd, name]
    if value:
        argv.append(value)
    p = subprocess.run(argv, cwd=wt, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, errors="replace")
    return p.returncode == 0, (p.stdout + p.stderr).strip()


def restart_drive(project: Path, name: str, mgr,
                  provider_env: dict | None = None) -> tuple[bool, str]:
    """driver 死/断点后重新驱动（续跑非重来：state 全在盘上）。

    门栏扣留（held_for_gate）时如实拒绝：此时恢复 driver 会秒退（driver
    进断点即退是设计语义），唯一出口是 gate 放行——拒绝并指路，而非
    起一个注定秒退的 driver 制造「恢复了一下立马又暂停」的假象。
    """
    if mgr.alive(project, name):
        return False, "driver 仍在运行，无需重驱"
    state, err = _get_state(project, name)
    if err:
        return False, err
    if state.get("gate") == "done":
        return False, "工作流已完结，无需恢复"
    if state.get("held_for_gate"):
        return False, "工作流扣留在门栏（held_for_gate）——请点「gate 放行」，而非恢复驱动"
    pid = mgr.start(project, name, Path(state["worktree_path"]), env=provider_env)
    return True, f"driver 已重启 pid={pid}"


def delete_workflow(project: Path, name: str, mgr) -> tuple[bool, str]:
    """删除工作流 = dl <name> --done：彻底清理 worktree + 分支 + 元数据（不可恢复）。

    dl 的「归档」语义实为彻底删除（dl-launch.sh --done 分支 rm -rf 元数据），
    故 UI 与消息直称删除，不美化。driver 活着先停（killpg 整个进程组）。
    """
    if mgr.alive(project, name):
        mgr.stop(project, name)
    p = subprocess.run(
        ["bash", str(DLWF / "scripts" / "workflow" / "dl-launch.sh"),
         "--workflow", name, "--delete"],
        cwd=str(project), stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=120, errors="replace",
    )
    if not meta_root(project, name).exists():
        # dl --done 不清产物（plans/understands/evidence 留主仓）——不一起删
        # 则同名新工作流直接继承旧改动面与证据链（实爆：用户怀疑删除没生效）。
        # dashboard 的删除语义 = 该名字下的一切归零。
        removed = []
        for rel in (f".claude/plans/{name}.md", f".claude/understands/{name}.md",
                    f".claude/evidence/{name}.jsonl"):
            f = project / rel
            if f.exists():
                f.unlink()
                removed.append(rel.split("/")[-1])
        # dashboard 自己的 legacy 段统计缓存（offset 书签）一并清
        cache = DLWF / "dashboard-cache" / f"{str(project).replace('/', '_')}--{name}.json"
        cache.unlink(missing_ok=True)
        suffix = f"（含产物 {'/'.join(removed)}）" if removed else ""
        return True, f"工作流 {name} 已删除{suffix}"
    return False, f"删除失败：{(p.stdout + p.stderr)[-300:]}"


def pause_workflow(project: Path, name: str, mgr) -> tuple[bool, str]:
    """暂停 = 停 driver（killpg 进程组）。

    语义如实：当前正在跑的步会被打断，恢复时该步从头重跑（dl 无步内断点
    续跑——state/台账在盘上，步级重跑是唯一保证一致的语义）。恢复走
    restart_drive（续跑非重来）。
    """
    if not mgr.alive(project, name):
        return False, "driver 未在运行，无需暂停"
    mgr.stop(project, name)
    return True, "已暂停（当前步恢复时从头重跑；点「恢复驱动」续跑）"
