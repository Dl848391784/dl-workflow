#!/usr/bin/env python3
"""
Stop hook：工作流阶段推进（§8.3 瘦化版,委托 dl-flow-engine）。

对应 designs/tui-state-machine-design.md §2/§5。
每轮 assistant 回复结束后：
  1. 读 transcript 取本轮输出
  2. 检完成信号（### SUB_DONE / ### PHASE_DONE 标记 = 模型自认做完）
  3. 有信号 -> engine.run_gate() 审质量（compound: 机械 + judge）
     pass  -> engine.advance_state() 推进 + 写证据
     block -> 返 hookSpecificOutput.additionalContext(reason) 续轮（模型自动重试,无用户介入）
     撞 CLAUDE_CODE_STOP_HOOK_BLOCK_CAP(默认 8) -> 不再续轮,banner 退化人工
  4. 无信号 -> 不推进（模型还没做完本节点）

设计取舍（design §5 + §7#6 向后兼容）：
- 完成信号（标记）与质量门（gate）分离：标记=何时审,gate=过不过。
  无标记=还没做完,不审不推进。保留旧 SUB_DONE/PHASE_DONE 标记语义,叠加 gate 质量审。
- gate_rubric=None 的子阶段（understand 1-3）：标记触发后只过机械项（NONE=直通过）-> 推进。
  即子阶段间仍靠标记自动推进（与旧版一致）,无 judge。

不阻断原则：本 hook 推进 + 续轮 + 打印横幅;异常 exit 0（Stop 非零会阻止会话结束）。
闸门：understand->plan、plan->execute 需 gate=passed 才推进（engine.advance_state 内含语义）。

**dl-workflow 版本**：hook 装到 ~/.claude/hooks/（用户级）,state.json 在主仓库
.claude/workflows/<name>/。engine 在 ~/.dl-workflow/dl-flow-engine.py（一级目录）,
用 importlib 加载（文件名带连字符无法直接 import）。
"""

import importlib.util
import json
import re
import subprocess
import sys
import time
from pathlib import Path

# ---------- 加载 engine（文件名带连字符,用 importlib）----------
_DLWF_ROOT = Path(__file__).resolve().parents[1]  # ~/.dl-workflow/
_ENGINE_PATH = _DLWF_ROOT / "dl-flow-engine.py"
_spec = importlib.util.spec_from_file_location("dl_flow_engine", _ENGINE_PATH)
engine = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["dl_flow_engine"] = engine  # dataclass 探测类型注解要查此表
_spec.loader.exec_module(engine)  # type: ignore[union-attr]

# 完成信号标记正则（模型自认做完时输出）。与旧版一致,作为"何时审"的触发。
DONE_RE = re.compile(r"###\s*PHASE_DONE:\s*(\w+)", re.IGNORECASE)
SUB_DONE_RE = re.compile(r"###\s*SUB_DONE:\s*(\d+)", re.IGNORECASE)


# ---------- hook 基础设施（保留;evidence_append.py 范式同构,各持副本）----------


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
    主仓库内返回 '.git' -> 回退 --show-toplevel。
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


def _resolve_workflow_name(cwd: str) -> str | None:
    """从 cwd（worktree 路径）反查工作流名。"""
    parts = Path(cwd).parts
    if "worktrees" in parts:
        i = parts.index("worktrees")
        if i + 1 < len(parts):
            return parts[i + 1]
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


def _last_assistant_text(transcript_path: str) -> str:
    """读 transcript JSONL，取最后一条 assistant message 的文本。

    防御式：transcript_path 缺失/格式不符/解析失败 -> 返回 ""。
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
    for t in reversed(texts):
        if t.strip():
            return t
    return ""


def _emit(msg: str) -> None:
    """打印到 stdout（TUI 可见）。"""
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _block_continue(reason: str) -> int:
    """返 Stop hook 的 additionalContext 续轮（changelog:1000 机制）。

    模型收到 reason -> 自动再来一轮修正,无用户介入。撞 cap(默认 8)
    -> claude 自动告警终结本轮（changelog:1435）。
    """
    out = {
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": (
                "## WORKFLOW GATE 未通过\n"
                f"{reason}\n\n"
                "请按上述原因修正后,重新完成当前节点（再次输出完成标记）。"
            ),
        }
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


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
        return 0  # 普通会话,不推进

    if project_root is None:
        _log(None, "no_project_root", wf=name)
        return 0

    state = engine.load_state(project_root, name)
    if not state:
        _log(project_root, "no_state", wf=name)
        return 0
    state = engine.normalize_state(state)

    cur_phase = state.get("phase", "understand")
    cur_sub = state.get("sub_index", 1)

    # 读 transcript 取本轮输出
    transcript_path = ""
    for key in ("transcript_path", "transcriptPath", "transcript"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            transcript_path = val
            break
    output = _last_assistant_text(transcript_path)

    # ---- 1. 完成信号检测（标记 = 模型自认做完 -> 触发 gate 审）----
    sm = SUB_DONE_RE.search(output)
    if sm:
        # 子阶段完成信号
        n = int(sm.group(1))
        node = engine.get_node(cur_phase, cur_sub)
        sub_total = engine.sub_total(cur_phase)
        if sub_total == 0:
            _log(project_root, "sub_done_no_subphases", wf=name, phase=cur_phase, n=n)
            return 0
        if n == sub_total:
            _log(
                project_root,
                "sub_done_last_ignored",
                wf=name,
                phase=cur_phase,
                n=n,
                sub_total=sub_total,
            )
            return 0  # 末子阶段应用 PHASE_DONE 触发闸门
        if n != cur_sub:
            _log(
                project_root,
                "sub_done_mismatch",
                wf=name,
                phase=cur_phase,
                n=n,
                sub_index=cur_sub,
            )
            return 0  # 序号不符不推进（防跳步）

        # 子阶段 gate：rubric=None 的（understand 1-3）-> run_gate 只过机械项(NONE)->过 -> 推进
        ok, reason = engine.run_gate(node, output, project_root=project_root)
        if not ok:
            _log(
                project_root,
                "sub_gate_block",
                wf=name,
                phase=cur_phase,
                n=n,
                reason=reason[:120],
            )
            return _block_continue(f"子阶段 {n}({node.label})未通过门控：{reason}")
        # 通过：推进 sub_index
        now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        state["sub_index"] = n + 1
        state["node"] = engine.node_id(cur_phase, n + 1)
        state["node_attempts"] = 0
        state["updated_at"] = now
        engine.save_state(project_root, name, state)
        _emit(
            f"\n┌─ WORKFLOW · {name} · {engine.PHASE_LABELS.get(cur_phase, cur_phase)} 子阶段推进\n"
            f"│ {n}. {node.label}  ──►  {n + 1}. {engine.get_node(cur_phase, n + 1).label}"
            f"  [{n + 1}/{sub_total}]"
        )
        _log(project_root, "sub_advanced", wf=name, phase=cur_phase, frm=n, to=n + 1)
        return 0

    # 阶段完成信号（PHASE_DONE）
    m = DONE_RE.search(output)
    if not m:
        _log(project_root, "no_done_marker", wf=name, phase=cur_phase, tlen=len(output))
        return 0  # 无完成信号,不推进
    done_phase = m.group(1).lower()
    if done_phase != cur_phase:
        _log(project_root, "done_mismatch", wf=name, phase=cur_phase, done=done_phase)
        return 0  # 标记阶段与当前不符,不推进

    # 子阶段守卫：有子阶段且未走完 -> 阻断 PHASE_DONE（强制依次）
    sub_total = engine.sub_total(cur_phase)
    if sub_total > 0 and cur_sub < sub_total:
        _emit(
            f"\n┌─ WORKFLOW · {name} · {engine.PHASE_LABELS.get(cur_phase, cur_phase)} 子阶段未完成\n"
            f"│ 检测到 PHASE_DONE: {cur_phase}，但还有子阶段未完成（{cur_sub}/{sub_total}）。\n"
            f"│ 先依次完成子阶段（各输出 ### SUB_DONE: <n>），末子阶段({sub_total})再 PHASE_DONE。"
        )
        _log(
            project_root,
            "phase_done_subphases_incomplete",
            wf=name,
            phase=cur_phase,
            sub_index=cur_sub,
            sub_total=sub_total,
        )
        return 0

    # ---- 2. gate 质量审（compound: 机械 + judge）----
    node = engine.get_node(cur_phase, cur_sub)
    ok, reason = engine.run_gate(node, output, project_root=project_root)
    if not ok:
        # gate 不过 -> block 续轮（模型自动重试）
        attempts = state.get("node_attempts", 0) + 1
        state["node_attempts"] = attempts
        state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        engine.save_state(project_root, name, state)
        _log(
            project_root,
            "gate_block",
            wf=name,
            phase=cur_phase,
            node=state["node"],
            attempts=attempts,
            reason=reason[:120],
        )
        return _block_continue(f"节点 {node.label}未通过门控：\n{reason}")

    # ---- 3. gate 过 -> 闸门判定 + 推进 ----
    if engine.is_gated_after(cur_phase):
        gate = state.get("gate", "pending")
        if gate != "passed":
            # 闸门未放行：不自动推进,提示用户
            nxt = engine.next_phase(cur_phase) or ""
            _emit(
                f"\n┌─ WORKFLOW · {name} · {engine.PHASE_LABELS.get(cur_phase, cur_phase)} 完成，闸门待放行\n"
                f"│ 已完成（gate 通过），但进 {engine.PHASE_LABELS.get(nxt, nxt)} 需闸门放行。\n"
                f"│ 输入 /wf gate 放行，或 /wf next 强制推进。"
            )
            _log(project_root, "gated_block", wf=name, phase=cur_phase, gate=gate)
            return 0

    # 推进（engine.advance_state 含子阶段/阶段/终结 + 闸门 passed 语义）
    if cur_phase == "evolution":
        _emit(f"\n╔═ WORKFLOW · {name} · 已完成全部 5 阶段（进化终结）")
        _log(project_root, "finished", wf=name, phase=cur_phase)

    new_state = engine.advance_state(project_root, name, via="auto-stop")
    _emit(
        f"\n╔═ WORKFLOW · {name} · 阶段切换\n"
        f"║ {engine.PHASE_LABELS.get(cur_phase, cur_phase)}  ──►  "
        f"{engine.PHASE_LABELS.get(new_state['phase'], new_state['phase'])}"
    )
    _log(project_root, "advanced", wf=name, frm=cur_phase, to=new_state["phase"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
