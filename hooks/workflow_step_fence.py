#!/usr/bin/env python3
"""
PreToolUse hook：子步骤围栏（S15 前置参与 + S10）+ 阶段写权限围栏（S11）。

S15（§step-engage-prefence）：当前子步骤「零 trace 窗口」（一条 skill-trace
都没写）时进入白名单模式——仅编排工具可用（常驻集：AskUserQuestion / Skill /
Task* / Read / Grep / Glob / Write 系仅 evidence 文件 / Bash 仅 dl-cmd.sh、
evidence 绝对路径 append、codegraph、只读发现命令（find/ls/grep/cat/head/
tail/git log 等——v2.53，见 _s15_bash_readonly_discovery）；外加
Step.fence_allow 的步骤声明），其它工具调用一律 deny。把 S13（Stop 参与围栏，回合末才纠偏）的判据前置到
工具调用级：模型为「直接回答用户」发起的第一个工具调用即被拦并指回编排
（2026-07-26 demo b01d6507：MiniMax-M3 首回合 Bash 探查抢答，S13 因用户
中断没机会开火）。与 S10 互斥互补：零 trace->S15 白名单；有未判决 trace->
S10 全 deny；已判决->自由。纯 text 抢答（无工具）仍由 S13 在 Stop 兜底。

S10：把「写完 evidence 后必须 STEP_DONE + end_turn」从文案约束变硬约束：
当前子步骤有「已写 trace 但未经 Stop 门控判决」（latest_trace_sha1 ≠
last_judged_trace 游标）时，deny 一切工具调用——模型唯一出路是输出
### STEP_DONE 并 end_turn，等 Stop hook 判定（过→进下一步 / block→当轮返工）。

S11：把「understand/plan 禁改源码、review 禁改实现」从文案约束变硬约束：
Edit/Write/MultiEdit/NotebookEdit 目标路径不在该 phase 白名单
（engine.phase_write_denial 单源）时 deny。已知限制：Bash 写（重定向/
sed -i）无法可靠判定写意图，不在围栏内（phase-rules 文案仍禁）。

开关：state.enforce_step_fence / enforce_phase_fence（默认 true；
/dl fence on|off 统一切换，hook 实时读 state 无需重启）。

容错：非 worktree / 无 state -> exit 0 静默放行。
deny 留痕 <project>/.claude/.wf_fence.log（观测性）。
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

# repo 根不在 sys.path（hook 以脚本方式执行），先补再 import。
_DLWF_ROOT = Path(__file__).resolve().parents[1]  # ~/.dl-workflow/
sys.path.insert(0, str(_DLWF_ROOT))
import dl_flow_engine as engine  # noqa: E402


def _resolve_project_root(cwd: str) -> Path | None:
    """worktree 内 cwd -> git --git-common-dir 反查主 repo 根（同 workflow_phase）。

    --git-common-dir 可能返回相对路径（如 ../../../.git 或 .git）——
    相对路径相对 `-C` 目录解析，不是相对 hook 进程 cwd。
    """
    try:
        r = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    p = Path(r.stdout.strip())
    if not p.is_absolute():
        p = (Path(cwd) / p).resolve()
    if p.name == ".git":
        return p.parent
    return None


def _workflow_name(cwd: str) -> str | None:
    """worktree 路径含 .claude/worktrees/<name> -> name；否则 None。"""
    parts = Path(cwd).parts
    for i, p in enumerate(parts):
        if p == "worktrees" and i + 1 < len(parts):
            return parts[i + 1]
    return None


def _log_deny(project_root: Path, name: str, kind: str, detail: str) -> None:
    """deny 留痕（观测性）。失败静默。"""
    try:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        with (project_root / ".claude" / ".wf_fence.log").open(
            "a", encoding="utf-8"
        ) as f:
            f.write(f"{ts}|{kind}|wf={name}|{detail}\n")
    except OSError:
        pass


# S11：结构化写工具（Bash 写无法可靠判定写意图，不在围栏内——见设计文档 S11）
_WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")

# S10 豁免的清单记账工具（2026-07-27，demo 907fee09）：output-style 强制模型
# 每轮维护 TaskList（「每轮首步=对齐清单」），模型落 evidence 后按此规则做
# TaskUpdate -> 撞 S10 全 deny -> 弱遵从模型不明所以重试 9 次报错刷屏。
# Task* 是编排记账工具，无法用于「为下一子步骤探查/继续工作」（S10 的防御
# 对象）——deny 它不防任何违规，只制造与 output-style 强规则的打架。
# 与 S15 常驻集含 Task* 同一逻辑。TaskStop 不在内（操作后台任务，非记账）。
_S10_TASK_TOOLS = frozenset({"TaskCreate", "TaskUpdate", "TaskList", "TaskGet"})

# S15 常驻放行集（零 trace 窗口内所有子步骤可用）：编排原语 + 无害只读。
# Read/Grep/Glob 放行的理由（设计 §2.2）：子2 证据源含日志/数据文件、子4 红队
# 子代理需要读证据；纯 text 抢答本就无法用工具围栏拦截（S13 在 Stop 兜底），
# 拦 Read 不多拦任何一类违规却会误伤合法取证。
_S15_BASE_TOOLS = (
    "AskUserQuestion",
    "Skill",
    "TaskCreate",
    "TaskUpdate",
    "TaskGet",
    "TaskList",
    "Read",
    "Grep",
    "Glob",
    "ExitPlanMode",
)


def _s15_bash_orchestration(cmd: str, ev_file: Path) -> bool:
    """Bash 编排命令模式（§step-engage-prefence §1.2）：dl-cmd 状态查询 /
    evidence 绝对路径 append / engine 机械化命令（append-trace 落库、
    redteam-prompt 组装）/ codegraph。已知限制：子串匹配可被复合命令
    走私（`codegraph sync && <任意>`）——威胁模型是弱遵从模型非对抗攻击，
    同 S11 的 Bash 盲区，接受。"""
    if "dl-cmd.sh" in cmd:
        return True
    if str(ev_file) in cmd:
        return True
    if "dl_flow_engine.py" in cmd and (
        "append-trace" in cmd
        or "redteam-prompt" in cmd
        or "fetch-prompt" in cmd
        or "render-artifact" in cmd
        or "render-readback" in cmd
    ):
        return True
    return re.search(r"\bcodegraph\b", cmd) is not None


# S15 只读发现通道（v2.53，2026-08-02 tail_volume_acceleration_annualized
# u:1 运行实证）：claude-code 2.1.x 默认隐藏 Glob/Grep（会话报
# "No such tool available: Glob" 并指路用 Bash find/grep），而 S15 零 trace
# 窗口只放行 Read、deny 全部 Bash——子2 判据要求主链每环 file:line 证据
# 指针，发现通道却全关：实测 25 次盲 Read 猜路径全 miss + 6 次 find/ls/
# git log 被 deny + 4 次 no-such-tool（41 个工具报错中 35 个同根因）。
# Read 单独不构成「合法且足够的取证通道」（rubric §3.5 #7）——harness
# 指路的通道（Bash find/grep）就必须同时是围栏合法通道，否则判据要求的
# 证据指针没有低成本合法获取路径。历史：红队子代理同症曾以 prompt 钉
# 「都不要试」绕开（engine.redteam_prompt），本修是正治。
# 按段校验：|/&&/||/;/换行 拆段，每段都须命中只读白名单；含输出重定向
# （>，2>/dev/null 类除外）/$( /反引号/xargs/tee 即拒。已知限制：引号内
# 走私（grep 模式里的 >）会误伤、复合只读命令换写法即可——威胁模型是
# 弱遵从模型非对抗攻击，同 S11 的 Bash 盲区，接受。
_S15_READONLY_CMD_RE = re.compile(
    r"^\s*(?:find|ls|grep|rg|cat|head|tail|wc|sort|uniq|file|stat|"
    r"realpath|readlink|pwd|echo|tree|diff|du|od|hexdump|xxd)\b"
)
_S15_GIT_READONLY_RE = re.compile(
    r"^\s*git\s+(?:log|show|status|diff|blame|grep|ls-files|rev-parse)\b"
)


def _s15_bash_readonly_discovery(cmd: str) -> bool:
    """Bash 只读发现命令判定（v2.53）：find/ls/grep/cat/head/git log 等。

    全命令按段（管道/&&/;/换行）校验，段段只读才放行；写意图信号
    （输出重定向/命令替换/xargs/tee）一票否决。
    """
    if re.search(r"`|\$\(|\bxargs\b|\btee\b", cmd):
        return False
    if re.search(r"(?<![0-9>])>", cmd):  # 输出重定向（2>/dev/null 豁免）
        return False
    for seg in re.split(r"\|\||&&|[|;\n]", cmd):
        seg = seg.strip()
        if not seg:
            continue
        if _S15_READONLY_CMD_RE.match(seg) or _S15_GIT_READONLY_RE.match(seg):
            continue
        return False
    return True


def _s15_allowed(
    tool: str, tool_input: dict, ev_file: Path, step: "engine.Step", cwd: str
) -> bool:
    """S15 白名单判定：常驻集 / Write 系仅 evidence / Bash 编排模式 / 步骤声明。"""
    if tool in _S15_BASE_TOOLS:
        return True
    if tool in step.fence_allow:
        return True
    if tool in _WRITE_TOOLS:
        fp = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        if fp and not Path(fp).is_absolute():
            fp = str((Path(cwd) / fp).resolve())
        try:
            rp = Path(fp).resolve()
        except OSError:
            return False
        # evidence 目录下可写（append-trace 载荷文件 .trace-payload-*.json 等）；
        # 直写 <name>.jsonl 本体由 S14 在前置段单独 deny（收编到 append-trace）。
        return bool(fp) and rp.parent == ev_file.parent
    if tool == "Bash":
        cmd = str(tool_input.get("command") or "")
        return _s15_bash_orchestration(cmd, ev_file) or _s15_bash_readonly_discovery(
            cmd
        )
    return False


def _deny(reason: str) -> int:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    cwd = payload.get("cwd") or ""
    name = _workflow_name(cwd)
    if not name:
        return 0  # 非工作流会话 -> 放行
    project_root = _resolve_project_root(cwd)
    if project_root is None:
        return 0
    tool = str(payload.get("tool_name", "?"))

    # 观测（验证期）：payload 是否真带 permission_mode（S12 硬拦的前提）。
    # 确认字段稳定存在后可删此行。
    _log_deny(
        project_root,
        name,
        "fence_seen",
        f"tool={tool}|pm={payload.get('permission_mode')}",
    )

    # ---- plan mode 入口封堵：模型自己 EnterPlanMode 也会把会话带进互斥态 ----
    if tool == "EnterPlanMode":
        _log_deny(project_root, name, "plan_mode_deny", f"tool={tool}")
        return _deny(
            "工作流会话禁用 plan mode（编排互斥）。不要进入 plan mode；"
            "直接按注入的子步骤清单执行当前子步骤。"
        )

    # ---- plan mode 互斥硬拦：plan mode 与工作流编排冲突（只读探查语义挤掉编排协议，
    # demo 会话 bf91ca0f 实录）。plan mode 下 deny 一切工具调用（仅放行 ExitPlanMode）。
    # 出口文案指向「文本告知用户切模式」而非 ExitPlanMode：用户手动进的 plan mode
    # 只有用户能干净退出；模型 ExitPlanMode 需提交计划，但它被拦得无法探查、
    # 拿不出计划 -> 死锁（demo 会话 61482dbe 实录：模型「改走 plan mode Phase 1」
    # 反复试工具全被拒）。payload 无 permission_mode 字段 -> None -> 不拦（防误判）。
    if payload.get("permission_mode") == "plan" and tool != "ExitPlanMode":
        _log_deny(project_root, name, "plan_mode_deny", f"tool={tool}")
        return _deny(
            "当前处于 plan mode，与工作流编排互斥。\n"
            "停止调用任何工具。直接用文本告知用户：「当前处于 plan mode，"
            "工作流编排无法在此模式下运行，请 shift+tab 切回 default 后重新提问」，"
            "然后 end_turn 等待用户切换。"
        )

    # ---- S14 evidence 写入收编（v2.14 append-trace）：模型一律不直写 evidence
    # jsonl——落库走 append-trace（脚本管格式/路径/结构字段）。旧版是覆盖守卫
    # （Write 新内容须含全部已有行，demo e84aee6d 教训）；append-trace 上线后
    # 直写 jsonl 没有合法场景，Write/Edit/MultiEdit 全量 deny 并指路。
    if tool in ("Write", "Edit", "MultiEdit"):
        ti = payload.get("tool_input") or {}
        fp = str(ti.get("file_path") or "")
        ev_file = project_root / ".claude" / "evidence" / f"{name}.jsonl"
        try:
            same = Path(fp).resolve() == ev_file.resolve()
        except OSError:
            same = False
        if same:
            _log_deny(project_root, name, "evidence_direct_write_deny", f"tool={tool}")
            payload_path = f"{project_root}/.claude/evidence/.trace-payload-{name}.md"
            return _deny(
                "evidence 落库走 append-trace（你定内容，脚本管格式/路径/结构字段）：\n"
                "① Bash `python3 ~/.dl-workflow/dl_flow_engine.py append-trace --scaffold`"
                " 生成载荷骨架（标头已就位，「待填」占位）\n"
                "② 把骨架里的「待填」全部换成实际内容\n"
                "③ Bash `python3 ~/.dl-workflow/dl_flow_engine.py append-trace "
                f"--from-file {payload_path}`\n"
                "直写 evidence jsonl（含覆盖/编辑旧行）一律禁止——修正旧记录的方式是"
                "用 append-trace 追加新行（judge 以最后一条为准）。"
            )

        # v2.66：载荷文件 .trace-payload-*.md 禁手写 Write（四桶：格式 `【标头】`
        # 归脚本）。模型绕过 --scaffold 手写粘头载荷（【purpose】内容 同行）致
        # 解析失败 + 字节 hunt 死循环（tail_volume u:1 子1 8 报错）--正治不是
        # 解析器宽容（那只是 defense-in-depth），是堵死旁路：scaffold 生成格式
        # （标头独占行），模型只 Edit 「待填」填内容。Edit/MultiEdit 合法（填机制）。
        payload_path = project_root / ".claude/evidence" / f".trace-payload-{name}.md"
        if tool == "Write":
            try:
                is_payload = Path(fp).resolve() == payload_path.resolve()
            except OSError:
                is_payload = False
            if is_payload:
                _log_deny(project_root, name, "payload_raw_write_deny", f"tool={tool}")
                return _deny(
                    "载荷格式归脚本（四桶分工：你定内容，脚本定 `【标头】` 格式）--"
                    "禁手写 Write 载荷文件（标头粘内容同行=手写格式，必被解析拒）：\n"
                    "① Bash `python3 ~/.dl-workflow/dl_flow_engine.py append-trace "
                    "--scaffold` 生成载荷骨架（标头已就位，「待填」占位）\n"
                    f"② Edit 骨架文件，把每个「待填」换成实际内容（{payload_path}）\n"
                    "③ Bash `python3 ~/.dl-workflow/dl_flow_engine.py append-trace "
                    f"--from-file {payload_path}`\n"
                    "返工重做同样走 --scaffold（自动清上轮残留）；标头格式全归脚本，"
                    "你只填内容。"
                )

    # ---- S11 phase 写权限围栏：写工具目标路径须在该 phase 白名单内 ----
    if tool in _WRITE_TOOLS:
        ti = payload.get("tool_input") or {}
        fp = ti.get("file_path") or ti.get("notebook_path") or ""
        if fp:
            if not Path(fp).is_absolute():
                fp = str((Path(cwd) / fp).resolve())
            reason = engine.phase_write_denial(project_root, name, fp)
            if reason:
                _log_deny(
                    project_root, name, "phase_fence_deny", f"tool={tool}|path={fp}"
                )
                return _deny(
                    reason + "\n（此硬约束可用 /dl fence off 关闭，回文案约束）"
                )

    # ---- S15 参与前置围栏：零 trace 窗口 -> 白名单模式，非编排工具 deny ----
    # 与 S10 状态互斥（零 trace vs 未判决 trace），先后无关；放 S14/S11 之后
    # 是让更具体的文案（覆盖守卫/阶段白名单）优先命中。
    eng = engine.engagement_fence_state(project_root, name)
    if eng is not None:
        step_no, step_obj = eng
        ti = payload.get("tool_input") or {}
        ev_file = project_root / ".claude" / "evidence" / f"{name}.jsonl"
        # 症状 L 前置拦截：Bash 相对路径写 evidence（落 worktree，hook 读主仓读不到）
        # -> 拦下并指回 append-trace（脚本管路径，相对/绝对问题不存在）。
        if tool == "Bash":
            cmd = str(ti.get("command") or "")
            if f".claude/evidence/{name}.jsonl" in cmd and str(ev_file) not in cmd:
                _log_deny(
                    project_root, name, "engage_fence_deny", f"step={step_no}|rel_ev"
                )
                return _deny(
                    "evidence 落库走 append-trace（脚本管路径/格式，相对路径事故不存在）：\n"
                    "① Bash `python3 ~/.dl-workflow/dl_flow_engine.py append-trace "
                    "--scaffold` 生成载荷骨架，填掉「待填」\n"
                    "② Bash `python3 ~/.dl-workflow/dl_flow_engine.py append-trace "
                    "--from-file <载荷>`"
                )
        if not _s15_allowed(tool, ti, ev_file, step_obj, cwd):
            _log_deny(
                project_root,
                name,
                "engage_fence_deny",
                f"step={step_no}|tool={tool}",
            )
            extra = (
                f"；本步（{step_obj.ref}）额外放行：{' / '.join(step_obj.fence_allow)}"
                if step_obj.fence_allow
                else ""
            )
            return _deny(
                f"子步骤 {step_no}（{step_obj.ref}）尚未开始：当前子步骤没有任何 "
                "evidence skill-trace，处于前置参与围栏窗口（S15）。\n"
                f"本步目的：{step_obj.purpose[:150]}{'…' if len(step_obj.purpose) > 150 else ''}\n"
                "窗口内仅编排工具可用：AskUserQuestion / Skill / Task* / Read / "
                "Bash 只读发现（find/ls/grep/cat/head/git log 等，禁写命令）/ "
                f"codegraph / dl-cmd / 写 evidence（append-trace 落库）{extra}。\n"
                "直接回答用户、为用户任务做写操作或重型探查（WebFetch/WebSearch/Agent 等）= 违规。\n"
                f"正确动作：按注入的子步骤清单执行子步骤 {step_no}（invoke 对应 skill / "
                f"用 AskUserQuestion 问用户），完成后写 evidence 再输出 ### STEP_DONE: {step_no} 并 end_turn。\n"
                "（此硬约束可用 /dl fence off 关闭，回文案约束）"
            )

    # ---- S10 子步骤围栏：有未判决 trace -> 禁一切工具调用，逼 STEP_DONE+end_turn ----
    step = engine.pending_unjudged_step(project_root, name)
    if step is None:
        return 0  # 无未判决 trace（或围栏已 /dl fence off）-> 放行
    if tool in _S10_TASK_TOOLS:
        return 0  # 清单记账豁免（见 _S10_TASK_TOOLS 注释：不防任何违规，只消打架）
    _log_deny(project_root, name, "fence_deny", f"step={step}|tool={tool}")
    return _deny(
        f"子步骤 {step} 已写 evidence，正等待 Stop 门控判决。\n"
        "禁止继续工具调用（含为下一子步骤探查）。\n"
        f"唯一正确动作：输出 ### STEP_DONE: {step} 并 end_turn；"
        "门控判定后（过→进下一步 / block→当轮返工）再继续。\n"
        "（此硬约束可用 /dl fence off 关闭，回文案约束）"
    )


if __name__ == "__main__":
    sys.exit(main())
