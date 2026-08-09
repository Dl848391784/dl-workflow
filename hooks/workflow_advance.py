#!/usr/bin/env python3
"""
Stop hook：工作流阶段推进（§8.3 瘦化版,委托 dl_flow_engine）。

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
.claude/workflows/<name>/。engine 在 ~/.dl-workflow/dl_flow_engine.py（一级目录）。
"""

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

# ---------- 加载 engine（repo 根不在 sys.path,先补再 import）----------
_DLWF_ROOT = Path(__file__).resolve().parents[1]  # ~/.dl-workflow/
sys.path.insert(0, str(_DLWF_ROOT))
import dl_flow_engine as engine  # noqa: E402

# 完成信号标记正则（模型自认做完时输出）。与旧版一致,作为"何时审"的触发。
DONE_RE = re.compile(r"###\s*PHASE_DONE:\s*(\w+)", re.IGNORECASE)
SUB_DONE_RE = re.compile(r"###\s*SUB_DONE:\s*(\d+)", re.IGNORECASE)
# 注：STEP_DONE 不再在 Stop hook 检测（§step-advance-on-submit：有 sub_steps 节点的
# 子步骤推进移到 UserPromptSubmit 读 evidence，避开 transcript flush 竞态）。


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


# 后台 Agent 的派发/归还信号（harness 契约，v2.118 实测自真实 transcript）。
# 派发 = tool_result 文本含 launch ack 与 agentId；归还 = <task-notification>
# 携 <task-id>。两者的 id 同为 16-17 位小写 hex（agentId 即 task-id）。
_AGENT_LAUNCH_ACK = "Async agent launched successfully"
_AGENT_LAUNCH_ID_RE = re.compile(r"agentId:\s*([0-9a-f]{16,17})\b")
_AGENT_DONE_ID_RE = re.compile(r"<task-id>\s*([0-9a-f]{16,17})\s*</task-id>")


def _pending_background_agent_count(transcript_path: str) -> int:
    """检测未归的后台 Agent 子代理数（Q3，tail_volume u:1 子3/子4 实证）。

    v2.118 换判据（designs/agent-await-mechanization-design.md §3 修 A）：
    旧判据「Agent tool_use_id ∉ tool_result 集合」**从落地起从未生效**——
    后台 Agent 派发后 1-8 秒即回一条 tool_result，内容是 launch ack
    （"Async agent launched successfully" + agentId + output_file），不是
    completion。tool_use_id 立刻进 result_ids，差集恒空。真实 transcript
    （cfeafb35-*.jsonl，3 个 agent）重放旧判据 pending 全 0，故 15:23:02
    假性 GATE block「无 trace」照旧发生（.wf_advance.log:682 记
    sub_step_engage_block 而非 deferred_pending_agent = 铁证）。

    新判据用两个稳定 harness 信号配对：
      派发 = launch ack 文本里的 agentId（_AGENT_LAUNCH_ID_RE）
      归还 = <task-notification> 里的 <task-id>（_AGENT_DONE_ID_RE）
    未归 = launched - done。真实 transcript 在 gate 时刻 15:23:02 重放
    得 {'a781d26c012a3cee8'}（升档 full agent），defer 分支正确生效。

    同步 Agent（无 launch ack）不进 launched 集合 -> 不算 pending，
    回退原行为；缺失/解析失败 -> 0（防御式，不阻断门控）。
    整行扫描（不解析 message 结构）——归还信号出现在 queue-operation /
    attachment / user message 多种事件里，按 id 去重天然幂等。
    """
    if not transcript_path or not Path(transcript_path).exists():
        return 0
    launched: set[str] = set()
    done: set[str] = set()
    try:
        with open(transcript_path, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                if _AGENT_LAUNCH_ACK in line:
                    launched.update(_AGENT_LAUNCH_ID_RE.findall(line))
                if "<task-id>" in line:
                    done.update(_AGENT_DONE_ID_RE.findall(line))
    except OSError:
        return 0
    return len(launched - done)


def _emit(msg: str) -> None:
    """打印到 stdout（TUI 可见）。"""
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _pid_gone(pid: int) -> bool:
    """pid 已退出（含 zombie——driver 在 proc.wait 回收前的毫秒窗口，不算活）。"""
    try:
        os.kill(pid, 0)
    except OSError:
        return True
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return stat.rpartition(")")[2].split()[0] == "Z"
    except (OSError, IndexError):
        return True


def _sigterm_then_kill(pid: object) -> None:
    """SIGTERM 收 TUI，2s 未退 SIGKILL 兜底（tui-auto-continue-design §2）。

    安全前提：TUI 段会话按构造一次性（state/evidence 磁盘真源），trace 已由
    append-trace 独立进程同步落盘，杀 claude 不丢编排数据。
    """
    if not isinstance(pid, int) or pid <= 0:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return  # 已退出
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if _pid_gone(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def _maybe_autodone_tui(project_root: Path, name: str, state: dict) -> None:
    """TUI 段自动收段（tui-auto-continue-design，2026-08-09 用户裁决「自动续跑」）。

    程序通道区分退出方式（信号通道证伪「可区分」后的第三条路）：driver 起 TUI 段
    时写 tui_segment.json（pid + pre_sha=段启动前最新 trace hash）；模型收轮时本
    函数机械判定「本段内落了新 trace」（latest hash ≠ pre_sha）→ 写 tui_autodone
    标记 + SIGTERM 收 TUI。driver 见标记走共享门控自动续跑，/exit 依赖消失。

    不动作的情形（均与现状一致）：无段标记（headless 段/普通会话=零影响）；
    段标记与 state 当前位置不咬合（陈旧标记）；本段无新 trace（模型停下来等用户
    答话等）——会话照常住留，手动退出仍走「TUI 退 = 全退」。
    """
    meta = project_root / ".claude" / "workflows" / name
    try:
        seg = json.loads((meta / "tui_segment.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(seg, dict):
        return
    # 咬合：段标记必须对得上 state 当前位置（防陈旧标记误杀后续段的会话）
    if seg.get("node") != state.get("node") or seg.get("sub_step") != state.get(
        "sub_step_index"
    ):
        return
    sha = engine.latest_trace_sha1(
        project_root, name, seg["sub_step"], seg.get("minor_key")
    )
    if sha is None or sha == seg.get("pre_sha"):
        return  # 本段无新 trace——会话住留（等用户答话等），不动作
    (meta / "tui_autodone.json").write_text(
        json.dumps(
            {
                "node": seg.get("node"),
                "sub_step": seg.get("sub_step"),
                "sha": sha,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
        ),
        encoding="utf-8",
    )
    _sigterm_then_kill(seg.get("pid"))
    _log(project_root, "tui_autodone", wf=name, pid=seg.get("pid"))


def _stop_continue(body: str) -> int:
    """返 Stop hook 的 additionalContext 续轮（changelog:1000 机制）通用底座。

    模型收到 body -> 自动再来一轮,无用户介入。撞 cap(默认 8)
    -> claude 自动告警终结本轮（changelog:1435）。
    """
    out = {
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": body,
        }
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


def _block_continue(reason: str) -> int:
    """门控未通过续轮：模型当轮返工。"""
    return _stop_continue(
        "## WORKFLOW GATE 未通过\n"
        f"{reason}\n\n"
        "请按上述原因修正后,重新完成当前节点（再次输出完成标记）。"
    )


def _sub_step_continue(
    prev_desc: str, node: "engine.Node", n: int, extra: str = ""
) -> int:
    """pass 自动续轮指令（非末步 & 跨子阶段进下一编排节点子1 共用，单源）。

    pass 自动续轮（2026-07-25 决议）：pass 也返 additionalContext 指令模型当轮
    开做下一子步骤，免去用户每步发一次「继续」；中途需用户输入模型会走
    AskUserQuestion，用户可随时 Esc 打断。
    prev_desc：刚通过门控的对象描述（「子步骤 3」/「子阶段「X」的全部子步骤」）。
    ⚠ stdout 必须是纯 JSON（症状 Q）：本函数只经 _stop_continue 输出，
    ✓ 等人类可读文本由调用方走 stderr。
    §autocontinue-fence-notice：续轮消息附目标子步骤的 S15 围栏提示
    （含 fence_allow 豁免）——注入通道只在 UserPromptSubmit 渲染，
    自动续轮的会话模型可能只在子1 见过无豁免版提示，到后续步骤
    臆断工具被 deny（demo 121320fe：子4 未试先称 Agent 被拦）。
    """
    step = engine.sub_step_at(node, n)
    if step is None:
        return 0  # 防御：索引异常时停轮（下轮注入自纠）
    total = len(node.sub_steps)
    if step.kind == "skill":
        how = f"先用 Skill 工具 invoke `{step.ref}`，再按其引导执行"
    else:
        how = f"用工具 {step.ref} 执行"
    return _stop_continue(
        f"## WORKFLOW {prev_desc} 已通过门控\n"
        f"现在立即执行「{node.label}」子步骤 {n}/{total}（{step.kind}: {step.ref}）：\n"
        f"目的：{step.purpose}\n\n"
        f"{how}；完成后落 evidence（Bash `python3 ~/.dl-workflow/dl_flow_engine.py "
        f"append-trace --scaffold` 生成载荷骨架、Edit 填「待填」，再 Bash `python3 "
        f"~/.dl-workflow/dl_flow_engine.py append-trace --from-file <载荷>`），"
        f"再输出 ### STEP_DONE: {n} 并结束本轮。\n"
        "如需用户输入：用 AskUserQuestion 工具（回合内完成）。\n"
        + engine.selfcheck_hint(step)
        + "\n"
        + engine.engagement_fence_notice(step)
        + extra
    )


def _handoff_boundary_prompt(
    project_root: Path | None,
    name: str,
    node: "engine.Node",
    transcript_path: str,
    variant: str = "continue",
) -> str:
    """子阶段边界固定交接提示（v2.122，minor-boundary-handoff-prompt-design §2.1）。

    节点末步过门控的边界固定出现——阈值不再决定出现与否（v2.45 nudge 阈值
    触发在 tail_volume 实测 8/8 边界触发、0 次执行 = 按阈值出现的纯建议等于
    不存在），只定文案档位：<T1 健康 / T1~T2 建议 / >T2 强烈建议。全软提示
    无硬拦（2026-08-07 用户决议：用户全程自主，阈值硬拦明确否决）；用户选择
    由 engine.write_handoff_prompt 机械留痕（上次未决先补记 declined），
    事后审计「提示几次/清几次」可量化。est 读不到 -> 无数字降级版（宁纵勿枉）。
    variant=gate：边界停在 /dl gate 待放行（下一动作是放行而非回「继续」）。
    /clear 无程序化入口（harness 只从键盘解释），正确时刻的提示是系统能做的全部。
    """
    est = engine.estimate_context_tokens(transcript_path)
    tier = engine.handoff_tier(est)
    if project_root is not None:
        engine.write_handoff_prompt(project_root, name, node, est=est, tier=tier)
    if variant == "gate":
        clear_act = "先 /clear 再 /dl gate（state 在磁盘，clear 不影响放行）"
        plain_act = "直接 /dl gate"
    else:
        clear_act = "/clear 后回「继续」"
        plain_act = "回「继续」"
    if est is None:
        return (
            "\n🔄 子阶段边界：读不到上下文估算。如本会话已跑很久，建议"
            f"{clear_act}——交接包（前序证据+用户裁决+产物指针）自动注入，"
            f"接续零损失；{plain_act} = 选择不清。"
        )
    k = est // 1000
    if tier == "ok":
        return (
            f"\n🔄 子阶段边界：上下文约 {k}k，健康。{plain_act}即可；"
            f"也可{clear_act}，交接包自动注入，接续零损失。"
        )
    if tier == "suggest":
        return (
            f"\n🔄 子阶段边界：上下文约 {k}k。建议{clear_act}——后续每轮都"
            "全量重读当前上下文；清理后从 ~45k 重新起步，交接包（前序证据+"
            f"用户裁决+产物指针）自动注入，接续零损失。{plain_act} = 选择不清。"
        )
    return (
        f"\n🔄 子阶段边界：上下文已约 {k}k，每轮成本约为清理后的 "
        f"{max(est // 45_000, 2)} 倍。强烈建议{clear_act}（交接包自动注入，"
        f"接续零损失）；{plain_act} = 选择不清。"
    )


def _evidence_artifact(
    project_root: Path | None, name: str, node: "engine.Node"
) -> str | None:
    """若节点 rubric 依赖 evidence.jsonl，读其全文作 judge 的 artifact_content；否则 None。

    §define-problem-verify-gate：understand:1 的 rubric 含 "evidence/"/"skill-trace" ->
    rubric_needs_evidence=True -> 读模型写的 skill-trace/conclusion 记录喂 judge 校验。
    无 rubric / 不依赖 evidence 的节点返回 None（行为不变）。
    读失败（None）-> judge 拿不到证据 -> 按 rubric 判 block（no silent fallback，不默认放行）。
    """
    if project_root is None:
        return None
    if engine.rubric_needs_evidence(node):
        return engine.read_evidence(project_root, name)
    return None


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

    # v3 drive 模式（dl_drive.py 外部编排，designs/headless-driver-arch-design.md）：
    # 门控/推进/续轮全归 driver 直调 engine——本 hook 不做编排（防双 orchestrator：
    # 同一 trace 被 hook 与 driver 各判一次 = 双重推进/双重 block）。
    # 唯一保留动作 = TUI 段自动收段（tui-auto-continue-design）：机械判定本段
    # 落库后写标记 + 收 TUI，编排裁决仍全归 driver。
    if state.get("drive_mode"):
        _maybe_autodone_tui(project_root, name, state)
        _log(project_root, "drive_mode_skip", wf=name)
        return 0

    # v2.45/v2.122：早提取 transcript_path 供边界交接提示估算上下文
    # （后方 PHASE_DONE 分支另有同款提取，幂等不冲突）。
    transcript_path = ""
    for key in ("transcript_path", "transcriptPath", "transcript"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            transcript_path = val
            break

    cur_phase = state.get("phase", "understand")
    cur_sub = state.get("sub_index", 1)

    # ---- 0. 子步骤 Stop 门控（§substep-gate-at-stop）----
    # 触发 = evidence 当前子步骤最新 trace hash 有变化（非 transcript，避 flush 竞态）；
    # block -> _block_continue 同轮返工（消 3a 割裂）；pass -> 推进 + 放行。
    # 有 sub_steps 节点在此判完即返回；无 sub_steps 节点走下方 SUB_DONE/PHASE_DONE 分支。
    try:
        cur_node0 = engine.get_node(cur_phase, cur_sub)
    except KeyError:
        cur_node0 = None
    if cur_node0 is not None and cur_node0.sub_steps:
        judged_step = state.get("sub_step_index", 1)
        # ---- S13 参与围栏：当前子步骤从未写过 trace -> 模型没参与编排 ----
        # （demo 8c51c318：模型明示「简单查询不走工作流」直接抢答）。
        # 协议遵从的模型不需要在子步骤中途结束回合（问用户走 AskUserQuestion
        # 回合内完成）；无 trace 结束回合 = 拒绝参与 -> 强制继续。
        # 有 trace 的情况走下方门控（新 hash 判 / 同 hash 已判过放行，R2 保留）。
        # minor_stage 限定本节点——多编排节点共用 evidence，不限定会把
        # ProblemContext 的同号子步骤 trace 误读为本节点的（跨节点串号）。
        if (
            engine.latest_trace_sha1(
                project_root, name, judged_step, cur_node0.minor_key
            )
            is None
        ):
            # v2.xx：pending background agent 时延后门控（Q3，tail_volume u:1 子3
            # 实证：模型派后台 agent[durationMs=4 立即返回] 后 end_turn，agent
            # 未归、trace 未落 -> S13 假性 block「无 trace」，agent handback 后
            # 才补 trace = 一次假性返工）。pending -> 静默放行，等 handback
            # 重新激活主会话写 trace 再触发门控。无 pending -> 原行为（block）。
            if _pending_background_agent_count(transcript_path) > 0:
                _log(
                    project_root,
                    "sub_step_gate_deferred_pending_agent",
                    wf=name,
                    phase=cur_phase,
                    step=judged_step,
                )
                return 0
            step0 = engine.sub_step_at(cur_node0, judged_step)
            purpose0 = step0.purpose if step0 else ""
            # 分诊：真无 trace（拒执，强制参与）vs 有内容但 JSON 损坏（指引修复格式）
            if engine.evidence_mentions_sub_step(
                project_root, name, judged_step, cur_node0.minor_key
            ):
                _log(
                    project_root,
                    "sub_step_malformed_trace",
                    wf=name,
                    phase=cur_phase,
                    step=judged_step,
                )
                return _block_continue(
                    f"evidence 里 sub_step=={judged_step} 的内容存在但 JSON 无法解析"
                    "（可能被合并到上一行/截断/引号转义错）。\n"
                    "请 append 一条**单行完整**的合法 JSON skill-trace"
                    "（Bash `printf '%s\\n' '<json>' >> <evidence 绝对路径>`），"
                    "不要覆盖、不要在行内拼接多条。"
                )
            _log(
                project_root,
                "sub_step_engage_block",
                wf=name,
                phase=cur_phase,
                step=judged_step,
            )
            return _block_continue(
                f"子步骤 {judged_step}（{purpose0}）尚未执行：当前子步骤没有任何 "
                "evidence skill-trace 记录。\n"
                "直接回答用户/跳过编排 = 违规。立即按注入的子步骤清单执行当前子步骤"
                "（invoke 对应 skill / 用 AskUserQuestion 逼问 / 探查），"
                "完成后写 evidence 再输出 ### STEP_DONE。\n"
                "如需用户输入：用 AskUserQuestion 工具（回合内完成），"
                "不要文本提问后结束回合。"
            )
        action, reason, st = engine.gate_sub_step_at_stop(project_root, name, cwd)
        if action == "none":
            # advance="phase" 编排末节点（understand:4）：末步已判过 + 门栏未扣留
            # -> PHASE_DONE 通道打开（判据单源 engine.phase_done_channel_open），
            # 落到下方 PHASE_DONE 分支走阶段大闸门；否则维持静默放行（S6/防 loop）。
            if not engine.phase_done_channel_open(project_root, name, state, cur_node0):
                return 0  # 无新 trace / 同 trace 已判 -> 静默放行
        elif action == "advanced":
            nxt = (st or {}).get("sub_step_index", 0)
            _log(
                project_root,
                "sub_step_gate_pass",
                wf=name,
                phase=cur_phase,
                step=judged_step,
                to=nxt,
                **engine.LAST_JUDGE_META,
            )
            if (st or {}).get("held_for_gate"):
                # §subphase-hold-gate：末步过门控但子阶段门栏扣留 ->
                # 停轮等用户 /dl gate（return 0 路径，_emit 文本不受症状 Q 纯 JSON 约束）
                _log(
                    project_root,
                    "subphase_held_for_gate",
                    wf=name,
                    phase=cur_phase,
                    step=judged_step,
                )
                _emit(
                    f"✓ 子步骤 {judged_step} 通过门控 —— {cur_node0.label} 全部子步骤完成\n"
                    "⛔ 子阶段门栏：进下一子阶段需用户裁决。\n"
                    "  输入 /dl gate 放行；或 /dl back 回退、/dl state-reset <n> 重测。"
                    + _handoff_boundary_prompt(
                        project_root, name, cur_node0, transcript_path, variant="gate"
                    )
                )
                return 0
            new_sub = (st or {}).get("sub_index", cur_sub)
            new_phase = (st or {}).get("phase", cur_phase)
            if (new_phase, new_sub) != (cur_phase, cur_sub):
                # 末步通过 -> 跨子阶段（含跨阶段：understand:4 无门栏后末步
                # 直接推进 plan:1，2026-07-28 围栏只设 plan 完成）。无门栏的
                # 边界不是检查点（门栏才是——2026-07-27 用户预期「无门栏一路
                # 跑到门栏再停」）：下一节点有编排则自动续轮进其子1；
                # 无编排/不存在才停轮等用户。
                # ⚠ 节点查找必须用推进后的 new_phase（旧 cur_phase 会把
                # understand:4->plan:1 错查成 understand:1）。
                nxt_node = None
                try:
                    nxt_node = engine.get_node(new_phase, new_sub)
                except KeyError:
                    nxt_node = None
                if nxt_node is not None and nxt_node.sub_steps:
                    sys.stderr.write(
                        f"✓ 子步骤 {judged_step} 通过门控 -> "
                        f"{nxt_node.label} 子步骤 1（自动续轮）\n"
                    )
                    return _sub_step_continue(
                        f"子阶段「{cur_node0.label}」的全部子步骤",
                        nxt_node,
                        1,
                        extra=_handoff_boundary_prompt(
                            project_root, name, cur_node0, transcript_path
                        ),
                    )
                _emit(
                    f"✓ 子步骤 {judged_step} 通过门控 -> 子阶段推进"
                    + _handoff_boundary_prompt(
                        project_root, name, cur_node0, transcript_path
                    )
                )
                return 0
            # ⚠ stdout 必须是纯 JSON（harness 整体解析）——✓ 行走 stderr，
            # 混一行非 JSON 文本会让 additionalContext 被整段丢弃（demo 2026-07-25 实测：
            # pass 续轮未投递，模型停轮；block 路径纯 JSON 所以一直正常）。
            sys.stderr.write(
                f"✓ 子步骤 {judged_step} 通过门控 -> 子步骤 {nxt}（自动续轮）\n"
            )
            return _sub_step_continue(
                f"子步骤 {judged_step}",
                cur_node0,
                nxt,
            )
        else:
            # block / escalate：同轮返工（S4/S7）
            attempts = (st or state).get("node_attempts", 0)
            _log(
                project_root,
                "sub_step_gate_block",
                wf=name,
                phase=cur_phase,
                step=judged_step,
                attempts=attempts,
                action=action,
                reason=reason[:80],
                **engine.LAST_JUDGE_META,
            )
            if action == "escalate":
                return _block_continue(
                    f"子步骤 {judged_step} 已连续 {attempts} 次未通过门控（达升级阈值）。\n"
                    f"最近原因：{reason}\n"
                    "停止盲目重做，用 AskUserQuestion 请用户裁决：\n"
                    "1. 用户补充信息/澄清后，你重做该子步骤\n"
                    "2. 用户同意强制放行后，你运行 "
                    "bash ~/.dl-workflow/scripts/workflow/dl-cmd.sh step-pass"
                    "（裁决记录落 evidence）\n"
                    "3. 用户要求回退 /dl back\n"
                    "4. 判据本身有缺陷（与命题矛盾/佐证无合法获取路径）：用户认可后，"
                    "你运行 bash ~/.dl-workflow/scripts/workflow/dl-cmd.sh dispute "
                    '"<缺陷论证>"（申诉记录落 evidence，判据修订归人），'
                    "再按用户指示重做/放行/回退\n"
                    "门控判据不可自行变通；出口只有用户裁决。\n"
                    "⚠ dl-cmd.sh 一律原样裸跑，禁追加 `2>&1`、`| tail` 等"
                    "管道/重定向（输出仅一两行，无需截断；复合命令会破坏"
                    "权限白名单匹配 → 每次多付 ~15s 裁决延迟，甚至挂起无响应）。"
                )
            # block 返工附当前步围栏提示（含 fence_allow 豁免）：block 高发场景正是
            # 「模型以为某工具被拦」，豁免文案直接纠正假信念（demo 121320fe）。
            # §step-selfcheck：返工后再声明完成前同样要求逐条自查（步级 checklist）。
            judged_step_obj = engine.sub_step_at(cur_node0, judged_step)
            rework_hint = (
                "\n"
                + engine.selfcheck_hint(judged_step_obj)
                + (
                    "\n" + engine.engagement_fence_notice(judged_step_obj)
                    if judged_step_obj is not None
                    else ""
                )
            )
            return _block_continue(
                f"子步骤 {judged_step} 未通过门控（第 {attempts} 次）：{reason}\n"
                "返工：按判词补缺——优先只修判词点名的条目（surgical 修），"
                "禁默认全篇重写；判词指出的是系统性模式问题时才全篇按模式改。"
                "载荷文件落库成功时已删除（防重复 append），勿直接 Edit/Write "
                "旧路径（会报 file not exist / read-first）——返工回路=重新 "
                "append-trace --scaffold 生成骨架 -> Read 骨架 -> 填内容"
                "（上一轮内容照上下文填入，只改判词点名项）-> --from-file 落库。"
                "上下文已有的原话直接引用（无需问用户），"
                "真缺的维度才用 AskUserQuestion 补问；"
                "完成后 append 新 trace 再 STEP_DONE。" + rework_hint
            )

    # 读 transcript 取本轮输出
    transcript_path = ""
    for key in ("transcript_path", "transcriptPath", "transcript"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            transcript_path = val
            break
    output = _last_assistant_text(transcript_path)

    # ---- 1. 完成信号检测（标记 = 模型自认做完 -> 触发 gate 审）----
    # §substep-gate-at-stop：有 sub_steps 节点已在上方分支处理并返回（不到这里）。
    # 本分支只处理无 sub_steps 节点的 SUB_DONE/PHASE_DONE（单条文本无工具中断，无竞态）。
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

        # 子阶段 gate：understand:1 有验真 rubric -> run_gate 跑 judge（读 evidence.jsonl）；
        #   understand:2-3 无 rubric -> run_gate 只过机械项(NONE)->过 -> 推进
        ok, reason = engine.run_gate(
            node,
            output,
            project_root=project_root,
            artifact_content=_evidence_artifact(project_root, name, node),
            name=name,
        )
        if not ok:
            _log(
                project_root,
                "sub_gate_block",
                wf=name,
                phase=cur_phase,
                n=n,
                reason=reason[:120],
                **engine.LAST_JUDGE_META,
            )
            return _block_continue(f"子阶段 {n}({node.label})未通过门控：{reason}")
        # 通过：写裁决记录（§8.6）+ 推进 sub_index
        _ev_ok = engine.write_gate_verdict(
            project_root,
            name,
            node,
            attempts=state.get("node_attempts", 0),
            cwd=cwd,
            via="sub-advance",
        )
        _log(
            project_root,
            "gate_verdict_written",
            wf=name,
            node=engine.node_id(cur_phase, cur_sub),
            ev_ok=_ev_ok,
            **engine.LAST_JUDGE_META,
        )
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
            + _handoff_boundary_prompt(project_root, name, node, transcript_path)
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
    ok, reason = engine.run_gate(
        node,
        output,
        project_root=project_root,
        artifact_content=_evidence_artifact(project_root, name, node),
        name=name,
    )
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
            **engine.LAST_JUDGE_META,
        )
        return _block_continue(f"节点 {node.label}未通过门控：\n{reason}")

    # gate 过：写裁决记录（§8.6）
    _ev_ok = engine.write_gate_verdict(
        project_root,
        name,
        node,
        attempts=state.get("node_attempts", 0),
        cwd=cwd,
        via="auto-stop",
    )
    _log(
        project_root,
        "gate_verdict_written",
        wf=name,
        node=state["node"],
        ev_ok=_ev_ok,
        **engine.LAST_JUDGE_META,
    )

    # ---- 3. gate 过 -> 闸门判定 + 推进 ----
    if engine.is_gated_after(cur_phase):
        gate = state.get("gate", "pending")
        if gate != "passed":
            # 闸门未放行：不自动推进,提示用户
            nxt = engine.next_phase(cur_phase) or ""
            _emit(
                f"\n┌─ WORKFLOW · {name} · {engine.PHASE_LABELS.get(cur_phase, cur_phase)} 完成，闸门待放行\n"
                f"│ 已完成（gate 通过），但进 {engine.PHASE_LABELS.get(nxt, nxt)} 需闸门放行。\n"
                f"│ 输入 /dl gate 放行，或 /dl next 强制推进。"
                + _handoff_boundary_prompt(
                    project_root, name, node, transcript_path, variant="gate"
                )
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
        # evolution 终结 = 无下一边界，不附交接提示
        + (
            ""
            if cur_phase == "evolution"
            else _handoff_boundary_prompt(project_root, name, node, transcript_path)
        )
    )
    _log(project_root, "advanced", wf=name, frm=cur_phase, to=new_state["phase"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
