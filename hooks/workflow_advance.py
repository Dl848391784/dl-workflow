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


def _emit(msg: str) -> None:
    """打印到 stdout（TUI 可见）。"""
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


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
        if engine.latest_trace_sha1(project_root, name, judged_step) is None:
            step0 = engine.sub_step_at(cur_node0, judged_step)
            purpose0 = step0.purpose if step0 else ""
            # 分诊：真无 trace（拒执，强制参与）vs 有内容但 JSON 损坏（指引修复格式）
            if engine.evidence_mentions_sub_step(project_root, name, judged_step):
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
            return 0  # 无新 trace / 同 trace 已判 -> 静默放行（S6/防 loop）
        if action == "advanced":
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
                    "  输入 /dl gate 放行；或 /dl back 回退、/dl step-reset <n> 重测。"
                )
                return 0
            if (st or {}).get("sub_index", cur_sub) != cur_sub:
                # 末步通过 -> 子阶段边界：停轮作天然检查点（用户可介入/redirect），
                # 不自动续轮进下一子阶段。
                _emit(f"✓ 子步骤 {judged_step} 通过门控 -> 子阶段推进")
                return 0
            # ⚠ stdout 必须是纯 JSON（harness 整体解析）——✓ 行走 stderr，
            # 混一行非 JSON 文本会让 additionalContext 被整段丢弃（demo 2026-07-25 实测：
            # pass 续轮未投递，模型停轮；block 路径纯 JSON 所以一直正常）。
            sys.stderr.write(
                f"✓ 子步骤 {judged_step} 通过门控 -> 子步骤 {nxt}（自动续轮）\n"
            )
            # pass 自动续轮（2026-07-25 决议）：非末步 pass 也返 additionalContext，
            # 模型当轮直接开做下一子步骤，免去用户每步发一次「继续」。
            # 中途需用户输入模型会走 AskUserQuestion；用户可随时 Esc 打断。
            nxt_step = engine.sub_step_at(cur_node0, nxt)
            total = len(cur_node0.sub_steps)
            if nxt_step is None:
                return 0  # 防御：索引异常时停轮（下轮注入自纠）
            if nxt_step.kind == "skill":
                how = f"先用 Skill 工具 invoke `{nxt_step.ref}`，再按其引导执行"
            else:
                how = f"用工具 {nxt_step.ref} 执行"
            # §autocontinue-fence-notice：续轮消息附下一子步骤的 S15 围栏提示
            # （含 fence_allow 豁免）——注入通道只在 UserPromptSubmit 渲染，
            # 自动续轮的会话模型可能只在子1 见过无豁免版提示，到后续步骤
            # 臆断工具被 deny（demo 121320fe：子4 未试先称 Agent 被拦）。
            return _stop_continue(
                f"## WORKFLOW 子步骤 {judged_step} 已通过门控\n"
                f"现在立即执行子步骤 {nxt}/{total}（{nxt_step.kind}: {nxt_step.ref}）：\n"
                f"目的：{nxt_step.purpose}\n\n"
                f"{how}；完成后落 evidence（Write 载荷 purpose/q/a 到 "
                f".claude/evidence/.trace-payload-<name>.json，再 Bash `python3 "
                f"~/.dl-workflow/dl-flow-engine.py append-trace --from-file <载荷>`），"
                f"再输出 ### STEP_DONE: {nxt} 并结束本轮。\n"
                "如需用户输入：用 AskUserQuestion 工具（回合内完成）。\n"
                + engine.selfcheck_hint(nxt_step)
                + "\n"
                + engine.engagement_fence_notice(nxt_step)
            )
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
                "门控判据不可自行变通；出口只有用户裁决。"
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
            "返工：按判词补缺——上下文已有的原话直接引用（无需问用户），"
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
