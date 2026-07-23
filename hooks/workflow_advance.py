#!/usr/bin/env python3
"""
Stop hook：工作流阶段推进。

对应设计 designs/workflow-system-design.md §3。
每轮 assistant 回复结束后，读 transcript_path JSONL 取上一条 assistant 文本，
检测 `### PHASE_DONE: <phase>` 标记 -> 推进 state.json -> 闸门判定 -> 打印阶段切换横幅。

防御式（设计 §风险#1）：transcript_path 字段名/格式不确定时降级为提示用户敲 /wf next，
绝不阻断（Stop hook exit 0 only；非零会阻止会话结束，违反设计意图）。

不阻断原则：本 hook 只推进 + 打印横幅；即便检测失败也 exit 0。
闸门：understand->plan、plan->execute 需 gate=passed 才推进；否则提示用户 /wf gate。

**dl-workflow 版本**：hook 装到 ~/.claude/hooks/（用户级），不再假设
`__file__.parents[2]` 是项目根。改用 `git rev-parse --git-common-dir`
从 payload cwd（worktree 内）反查主仓库根。state.json / .wf_advance.log
都存到主仓库 .claude/ 下（与旧版兼容）。
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path


PHASES = ["understand", "plan", "execute", "review", "evolution"]
# 阶段中文显示名（仅显示用；逻辑层仍用英文标识；与 workflow_phase.py 一致）
PHASE_LABELS = {
    "understand": "理解和求证问题",
    "plan": "生成执行计划",
    "execute": "执行",
    "review": "审核结果",
    "evolution": "进化",
}
# 闸门：这些阶段完成后进下一阶段需 gate=passed
GATED_AFTER = {"understand", "plan"}

# 完成标记正则
DONE_RE = re.compile(r"###\s*PHASE_DONE:\s*(\w+)", re.IGNORECASE)

# 子阶段：phase -> 子阶段标签列表（仅 understand 有 4 个；其他阶段无子阶段）。
# 与 wf-lib.sh WF_SUBPHASES_UNDERSTAND / workflow_phase.py SUBPHASES 三处各持一份（避免跨语言 source）。
# 详见 designs/understand-subphases-design.md。
SUBPHASES = {
    "understand": ["理解问题和背景", "明确目标和价值", "确定范围与约束", "定义成功标准和验收方式"],
}
# 子阶段完成标记正则（子阶段 1..(N-1) 用；末子阶段 N 用 PHASE_DONE 触发闸门）
SUB_DONE_RE = re.compile(r"###\s*SUB_DONE:\s*(\d+)", re.IGNORECASE)


def _sub_total(phase: str) -> int:
    """阶段 -> 子阶段数（0=无子阶段）。"""
    return len(SUBPHASES.get(phase, []))


def _sub_label(phase: str, n: int) -> str:
    """阶段 + n -> 第 n 个子阶段标签（越界返回空串）。"""
    subs = SUBPHASES.get(phase, [])
    return subs[n - 1] if 1 <= n <= len(subs) else ""


def _payload_cwd(payload: dict) -> str:
    """从 hook payload 取 cwd（字段名容错），缺失回退进程 cwd。"""
    for key in ("cwd", "working_dir", "current_dir"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            return val
    return str(Path.cwd())


def _resolve_project_root(cwd: str) -> Path | None:
    """从 cwd（通常是 worktree 内）反查主仓库根。

    worktree 内 --git-common-dir 是绝对路径 -> dirname = 主 repo 根。
    主仓库内 --git-common-dir 返回 '.git' -> 回退 --show-toplevel。
    """
    try:
        res = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            common = res.stdout.strip()
            if common != ".git":
                return Path(common).parent
        res2 = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res2.returncode == 0 and res2.stdout.strip():
            return Path(res2.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def _log(project_root: Path | None, status: str, **kw) -> None:
    """留痕 Stop 触发（观测性）。失败静默。"""
    if project_root is None:
        return
    log = project_root / ".claude" / ".wf_advance.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        parts = [f"{k}={v}" for k, v in kw.items()]
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"{ts}|{status}|{'|'.join(parts)}\n")
    except OSError:
        pass


def _resolve_workflow_name(cwd: str) -> str | None:
    """从 cwd 反查工作流名（worktree 路径含 .claude/worktrees/<name>）。"""
    parts = Path(cwd).parts
    if "worktrees" in parts:
        i = parts.index("worktrees")
        if i + 1 < len(parts):
            return parts[i + 1]
    return None


def _state_path(project_root: Path, name: str) -> Path:
    return project_root / ".claude" / "workflows" / name / "state.json"


def _load_state(project_root: Path, name: str) -> dict | None:
    f = _state_path(project_root, name)
    if not f.exists():
        return None
    try:
        with open(f, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def _save_state(project_root: Path, name: str, state: dict) -> None:
    f = _state_path(project_root, name)
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


def _last_assistant_text(transcript_path: str) -> str:
    """读 transcript JSONL，取最后一条 assistant message 的文本。

    防御式：transcript_path 缺失/格式不符/解析失败 -> 返回 ""（触发降级）。
    JSONL 每行是一个 event；assistant 文本通常在 type=assistant 的 message.content[].text。
    """
    if not transcript_path or not Path(transcript_path).exists():
        return ""
    texts = []
    try:
        with open(transcript_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # 容错多种 transcript schema：找 assistant role 的 text content
                msg = ev.get("message") if isinstance(ev, dict) else None
                if not isinstance(msg, dict):
                    continue
                if msg.get("role") != "assistant":
                    continue
                content = msg.get("content")
                if isinstance(content, str):
                    texts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            texts.append(block.get("text", ""))
    except OSError:
        return ""
    # 取最后一条非空（最近一次 assistant 回复）
    for t in reversed(texts):
        if t.strip():
            return t
    return ""


def _emit(msg: str) -> None:
    """打印阶段切换横幅到 stdout（TUI 可见）。"""
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _advance(project_root: Path, state: dict, name: str) -> None:
    """执行推进：更新 phase/index/gate/history。"""
    cur = state["phase"]
    idx = PHASES.index(cur)
    nxt = PHASES[idx + 1] if idx + 1 < len(PHASES) else None
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    # 关闭当前阶段 history exit
    hist = state.get("history", [])
    if hist and hist[-1].get("exited_at") is None:
        hist[-1]["exited_at"] = now
        hist[-1]["via"] = "auto-stop"
    if nxt:
        hist.append({"phase": nxt, "entered_at": now, "exited_at": None, "via": "auto-stop"})
        state["phase"] = nxt
        state["index"] = idx + 2  # 1-based
        # 新阶段的 gate：若新阶段的前置是闸门来源（即 cur in GATED_AFTER），但本推进已是放行后，
        # 故新阶段 gate=passed（已通过）；否则新阶段 gate 取决于其自身是否是闸门目标
        state["gate"] = "passed" if cur in GATED_AFTER else "pending"
        # 子阶段：进新阶段按其 sub_total 重置（与 wf_state_set_phase 一致；plan 等无子阶段->0）
        nxt_sub_total = _sub_total(nxt)
        state["sub_total"] = nxt_sub_total
        state["sub_index"] = 1 if nxt_sub_total > 0 else 0
    else:
        state["gate"] = "done"  # evolution 完成终结
    state["history"] = hist
    state["updated_at"] = now
    _save_state(project_root, name, state)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        _log(None, "malformed_stdin")
        return 0
    if not isinstance(payload, dict):
        return 0

    cwd = _payload_cwd(payload)
    project_root = _resolve_project_root(cwd)

    name = _resolve_workflow_name(cwd)
    if not name:
        _log(project_root, "no_worktree_cwd")
        return 0  # 普通会话，不推进

    if project_root is None:
        _log(None, "no_project_root", wf=name)
        return 0

    state = _load_state(project_root, name)
    if not state:
        _log(project_root, "no_state", wf=name)
        return 0

    cur = state.get("phase", "understand")

    # 读 transcript 取上一条 assistant 文本
    transcript_path = ""
    for key in ("transcript_path", "transcriptPath", "transcript"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            transcript_path = val
            break
    text = _last_assistant_text(transcript_path)

    # 子阶段完成标记优先（子 1..N-1 用 SUB_DONE；末子阶段 N 用 PHASE_DONE 触发闸门）。
    # 同轮只会有其一：子 1-3 轮出 SUB_DONE，子 4 轮出 PHASE_DONE。
    sm = SUB_DONE_RE.search(text)
    if sm:
        n = int(sm.group(1))
        sub_total = _sub_total(cur)
        if sub_total == 0:
            _log(project_root, "sub_done_no_subphases", wf=name, phase=cur, n=n)
            return 0  # 该阶段无子阶段，忽略误输出的 SUB_DONE
        sub_index = state.get("sub_index", 1)
        if n == sub_total:
            # 末子阶段不该用 SUB_DONE（规则用 PHASE_DONE 触发闸门）；防御忽略，下轮注入自纠
            _log(project_root, "sub_done_last_ignored", wf=name, phase=cur, n=n, sub_total=sub_total)
            return 0
        if n != sub_index:
            _log(project_root, "sub_done_mismatch", wf=name, phase=cur, n=n, sub_index=sub_index)
            return 0  # 子阶段序号与当前不符，不推进（防跳步）
        # 推进 sub_index（n -> n+1）
        now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        state["sub_index"] = n + 1
        state["updated_at"] = now
        _save_state(project_root, name, state)
        cur_lbl = PHASE_LABELS.get(cur, cur)
        _emit(
            f"\n┌─ WORKFLOW · {name} · {cur_lbl} 子阶段推进\n"
            f"│ {n}. {_sub_label(cur, n)}  ──►  {n + 1}. {_sub_label(cur, n + 1)}  [{n + 1}/{sub_total}]"
        )
        _log(project_root, "sub_advanced", wf=name, phase=cur, frm=n, to=n + 1)
        return 0

    # 检测完成标记
    m = DONE_RE.search(text)
    if not m:
        _log(project_root, "no_done_marker", wf=name, phase=cur, tlen=len(text))
        return 0  # 未完成标记，不推进
    done_phase = m.group(1).lower()
    if done_phase != cur:
        _log(project_root, "done_mismatch", wf=name, phase=cur, done=done_phase)
        return 0  # 标记的阶段与当前不符，不推进（防误）

    # 子阶段守卫：阶段有子阶段且未走完 -> 阻断 PHASE_DONE（强制依次完成子阶段）
    sub_total = _sub_total(cur)
    if sub_total > 0:
        sub_index = state.get("sub_index", 1)
        if sub_index < sub_total:
            cur_lbl = PHASE_LABELS.get(cur, cur)
            _emit(
                f"\n┌─ WORKFLOW · {name} · {cur_lbl} 子阶段未完成\n"
                f"│ 检测到 PHASE_DONE: {cur}，但 {cur_lbl} 还有子阶段未完成（{sub_index}/{sub_total}）。\n"
                f"│ 请先依次完成各子阶段（每完成一个输出 ### SUB_DONE: <n>），\n"
                f"│ 末子阶段({sub_total})完成后再输出 ### PHASE_DONE: {cur}。"
            )
            _log(project_root, "phase_done_subphases_incomplete", wf=name, phase=cur, sub_index=sub_index, sub_total=sub_total)
            return 0

    # 闸门判定
    if cur in GATED_AFTER:
        gate = state.get("gate", "pending")
        if gate != "passed":
            # 闸门未放行：不自动推进，提示用户
            cur_lbl = PHASE_LABELS.get(cur, cur)
            nxt_lbl = PHASE_LABELS.get(PHASES[PHASES.index(cur) + 1], "")
            _emit(
                f"\n┌─ WORKFLOW · {name} · {cur_lbl} 完成，闸门待放行\n"
                f"│ {cur_lbl} 已完成（检测到 PHASE_DONE），但进 {nxt_lbl} 需闸门放行。\n"
                f"│ 输入 /wf gate 放行，或 /wf next 强制推进。"
            )
            _log(project_root, "gated_block", wf=name, phase=cur, gate=gate)
            return 0

    # 终结？
    if cur == "evolution":
        _emit(f"\n╔═ WORKFLOW · {name} · 已完成全部 5 阶段（进化终结）")
        _log(project_root, "finished", wf=name, phase=cur)
        state["gate"] = "done"
        state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        _save_state(project_root, name, state)
        return 0

    # 推进
    nxt_idx = PHASES.index(cur) + 1
    nxt = PHASES[nxt_idx]
    _advance(project_root, state, name)
    cur_lbl = PHASE_LABELS.get(cur, cur)
    nxt_lbl = PHASE_LABELS.get(nxt, nxt)
    _emit(
        f"\n╔═ WORKFLOW · {name} · 阶段切换\n"
        f"║ {cur_lbl} [{nxt_idx}/5]  ──►  {nxt_lbl} [{nxt_idx + 1}/5]"
    )
    _log(project_root, "advanced", wf=name, frm=cur, to=nxt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
