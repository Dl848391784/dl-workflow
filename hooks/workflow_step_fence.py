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
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# repo 根不在 sys.path（hook 以脚本方式执行），先补再 import。
_DLWF_ROOT = Path(__file__).resolve().parents[1]  # ~/.dl-workflow/
sys.path.insert(0, str(_DLWF_ROOT))
import dl_flow_engine as engine  # noqa: E402
from scripts.workflow import project_tools  # noqa: E402


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
        # v2.67：只读查询子命令——与 dl-cmd.sh status 语义等价（dl-cmd 本就
        # 包装引擎 status），直调引擎被路径技术性 deny 白烧一轮（2026-08-03
        # tail_volume_acceleration_annualized u:1 实证）。写状态子命令
        # （step-pass/state-reset/fence/advance/dispute）仍只走 /dl。
        or "status" in cmd
        or "current" in cmd
        or "progress" in cmd
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

# S15 python3 -c 只读数据放行（v2.xx，2026-08-05 tail_volume u:1 子2 实证）：
# 子2 因果链每环要 file:line 证据指针，读 JSON/parquet 字段需 python3（CLAUDE.md
# §3 推荐），零 trace 窗口禁 python3 = 合法取证通道被关（40 次 S15 deny）。
# 威胁模型=强模型非对抗，-c 内联代码扫写信号一票否决（同 S11 Bash 盲区口径）。
# open 写模式精确匹配「逗号+引号+wax」--open("x")（read，无逗号）放行，
# open('x','w')（有逗号+w）拒，不误伤文件名含 w/a/x 的只读 open。
_S15_PYTHON_WRITE_SIGNAL_RE = re.compile(
    r"open\s*\([^)]*,\s*['\"][wax]"  # open(file, 'w'/'a'/'x') 写/追加/独占
    r"|mode\s*=\s*['\"][wax]"  # open(file, mode='w')
    r"|os\.system|subprocess|popen"
    r"|__import__|\bexec\s*\(|\beval\s*\("
    r"|shutil\.|os\.remove|os\.unlink|os\.rmdir|os\.mkdir|os\.rename"
    r"|\.write\s*\(|\.write_text|\.write_bytes"
)


def _s15_python_readonly(seg: str) -> bool:
    """python3 -c 只读数据段判定（v2.xx）：-c 内联代码无写信号则放行。

    非 -c（python3 script.py 等外部脚本）不可判定 -> 拒（返 False）。
    """
    if not re.match(r"^\s*python3?\s+-c\s+", seg):
        return False
    return _S15_PYTHON_WRITE_SIGNAL_RE.search(seg) is None


# 项目工具 command 头白名单（组件 B，codebase-archaeology-toolbox-design §3.3）：
# 只加只读发现类——破坏性/解释器头（rm/git/python3/sed 等）不进白名单（弱模型幻觉
# 刹车）。过滤逻辑单源 scripts/workflow/project_tools.py 的 project_tool_heads()
# （与 per-wf settings allowlist 共用，不跨文件复制正则）。注册工具本身安全由项目
# 自担（脚本在项目仓、走 code review）——这里只拦「工具 + shell 写走私」与破坏性头。
def _s15_project_tool_command(cmd: str, project_root: Path) -> bool:
    """项目工具 command 头白名单（组件 B）：命令头命中注册只读工具 -> 放行。

    与 _s15_bash_readonly_discovery 同构：全命令按段校验，每段须为「项目工具头
    或只读发现命令」，任一段不满足即拒；写意图信号（输出重定向/命令替换/
    xargs/tee）一票否决。项目工具脚本本身可能含 IO（脚本在项目仓、自担安全），
    但 shell 层的写走私（重定向/复合破坏段）仍拦。
    """
    heads = project_tools.project_tool_heads(project_root)
    if not heads:
        return False
    outside = _outside_quotes(cmd)
    if re.search(r"`|\$\(|\bxargs\b|\btee\b", outside):
        return False
    if _has_write_redirect(outside):  # 输出重定向（仅 2> 系 stderr 豁免）
        return False
    for seg in _split_shell_segments(cmd):
        seg = seg.strip()
        if not seg:
            continue
        toks = seg.split()
        if toks and toks[0] in heads:
            continue
        if _S15_READONLY_CMD_RE.match(seg) or _S15_GIT_READONLY_RE.match(seg):
            continue
        if _s15_python_readonly(seg):
            continue
        return False
    return True


def _outside_quotes(cmd: str) -> str:
    """返回 cmd 引号外部分（引号内字符替换为空格），供写意图检测。

    python3 -c 代码常含 >（比较）/;（语句分隔）等，引号内不应触发 shell 写
    意图一票否决。简单引号状态机，不处理转义引号（威胁模型=非对抗，接受）。
    """
    out = []
    quote = None
    for c in cmd:
        if quote:
            out.append(" ")
            if c == quote:
                quote = None
        elif c in ("'", '"'):
            quote = c
            out.append(" ")
        else:
            out.append(c)
    return "".join(out)


def _has_write_redirect(outside: str) -> bool:
    """引号外含输出重定向写信号？（仅 2> 系 stderr 重定向豁免）。

    审计 Important #1：旧 lookbehind `(?<![0-9>])>` 把任意 fd 前缀豁免
    （1>/3>/…）——`1> file` 是完整 stdout→文件写却放行。正治：先剥 2 系
    stderr 重定向（2>>/2>&N/2>，不写文件），剩余任何 > 均视为写信号。
    """
    stripped = re.sub(r"2>>|2>&\d+|2>", "", outside)
    return ">" in stripped


def _split_shell_segments(cmd: str) -> list[str]:
    """按引号外 shell 分隔符拆段（保护引号内的 ;|& --python3 -c 代码）。

    替代 re.split(r"\\|\\||&&|[|;\\n]")：引号内的 ; 不拆（python -c 代码常用）。
    """
    segs: list[str] = []
    cur: list[str] = []
    quote = None
    i, n = 0, len(cmd)
    while i < n:
        c = cmd[i]
        if quote:
            cur.append(c)
            if c == quote:
                quote = None
        elif c in ("'", '"'):
            quote = c
            cur.append(c)
        elif c == "|" and i + 1 < n and cmd[i + 1] == "|":
            segs.append("".join(cur))
            cur = []
            i += 1
        elif c == "&" and i + 1 < n and cmd[i + 1] == "&":
            segs.append("".join(cur))
            cur = []
            i += 1
        elif c == "&":  # 单 &（后台符）也是命令分隔符（审计 Important #2）
            # 旧版不拆单 &：`tool & rm -rf /` 一整段 -> 头匹配放行 + rm 后台跑。
            # && 已在上方整对消费（i+1 跳两格），此处只落到「后一位非 &」的单 &。
            segs.append("".join(cur))
            cur = []
        elif c in ("|", ";", "\n"):
            segs.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    segs.append("".join(cur))
    return [s for s in segs if s.strip()]


def _s15_bash_readonly_discovery(cmd: str, deny_readonly: tuple[str, ...] = ()) -> bool:
    """Bash 只读发现命令判定（v2.53）：find/ls/grep/cat/head/git log 等。

    全命令按段（管道/&&/;/换行）校验，段段只读才放行；写意图信号
    （输出重定向/命令替换/xargs/tee）一票否决。引号感知（v2.xx）：
    python3 -c 代码内的 ;/> 不触发拆段/写意图（引号内替换为空格再检测）。

    deny_readonly：per-step 从只读发现通道额外 deny 的命令首 token（如子2
    禁 grep/rg 逼走 dl codebase trace——"堵入口"正治，rubric §3.5 #39）。
    """
    outside = _outside_quotes(cmd)
    if re.search(r"`|\$\(|\bxargs\b|\btee\b", outside):
        return False
    if _has_write_redirect(outside):  # 输出重定向（仅 2> 系 stderr 豁免）
        return False
    for seg in _split_shell_segments(cmd):
        seg = seg.strip()
        if not seg:
            continue
        if _S15_READONLY_CMD_RE.match(seg) or _S15_GIT_READONLY_RE.match(seg):
            if deny_readonly and seg.split()[0] in deny_readonly:
                return False
            continue
        if _s15_python_readonly(seg):
            continue
        return False
    return True


def _deny_readonly_hit(cmd: str, deny_readonly: tuple[str, ...]) -> bool:
    """per-step 只读发现窄化：命令任一段首 token 命中 deny_readonly。

    与 _s15_bash_readonly_discovery 的 deny_readonly 参数同口径，但**只查 deny
    集、不查整条只读白名单**——drive_mode 段工人全放行写操作，这里不能套只读
    白名单（会误伤段工人的 Edit/Write/append-trace），只窄化禁用的命令头。
    """
    if not deny_readonly:
        return False
    for seg in _split_shell_segments(cmd):
        seg = seg.strip()
        if not seg:
            continue
        if seg.split()[0] in deny_readonly:
            return True
    return False


# 取证命令模板形态的 curl（fetch-prompt 骨架逐字规定：curl -sS -m <n> "<url>"）。
# 仅在有在跑的取证子代理时放行（见 _s15_allowed 的 fetch curl 分支）。
_S15_FETCH_CURL_RE = re.compile(r"^\s*curl\s+(?=(?:-\S+\s+|\S+=\S+\s+)*-)")

# 后台 Agent 派发/归还信号——与 hooks/workflow_advance.py 同口径（单源在那边
# 的 docstring，此处只做 pending 判定，两处 regex 必须同步改）。
_AGENT_LAUNCH_ACK = "Async agent launched successfully"
_AGENT_LAUNCH_ID_RE = re.compile(r"agentId:\s*([0-9a-f]{16,17})\b")
_AGENT_DONE_ID_RE = re.compile(r"<task-id>\s*([0-9a-f]{16,17})\s*</task-id>")


def _payload_transcript(payload: dict) -> str:
    """hook payload 里的 transcript 路径（字段名多变体，同 workflow_advance）。"""
    for key in ("transcript_path", "transcriptPath", "transcript"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def _session_id(payload: dict) -> str:
    """会话标识（v2.69，同 design_gate/codegraph_gate）：payload session_id（真源）
    → transcript_path 文件名 stem（双保险）→ env CLAUDE_SESSION_ID（向后兼容）
    → "_fallback"。用于区分 front 前台会话（session_id == state.session_id）与
    drive 段工人 headless 会话（session_id ≠）。"""
    sid = str(payload.get("session_id") or "").strip()
    if sid:
        return sid
    tp = str(payload.get("transcript_path") or "").strip()
    if tp:
        stem = Path(tp).stem
        if stem:
            return stem
    return os.environ.get("CLAUDE_SESSION_ID", "").strip() or "_fallback"


def _pending_background_agent_count(transcript_path: str) -> int:
    """未归的后台 Agent 数（v2.118；判据实证见 workflow_advance 同名函数）。

    派发 = launch ack 里的 agentId；归还 = <task-notification> 的 <task-id>。
    tool_result 不是归还信号（后台 agent 派发后即回 launch ack）。
    缺失/解析失败 -> 0（防御式：不放宽围栏）。
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


def _s15_fetch_curl(cmd: str) -> bool:
    """取证 curl 判定（v2.118 修 D）：段段为 curl / jq / head 等只读摄取。

    实证（tail_volume u:1 子3->子4）：子3 派的 full agent 15:24:44 才归、
    跨到子4 存活，其进程内 curl 撞子4 围栏（fence_allow 无 Bash）-> 最后 3 次
    curl 被拒（子4 trace「围栏阻断了我最后 3 次 curl」）。子代理进程内的取证
    curl 与主会话写操作性质不同，且此时必有在跑的取证 agent。
    范围收窄：只放行 curl 与只读摄取管道（jq/head/wc 等），写意图信号一票否决
    （沿用 _s15_bash_readonly_discovery 的 outside-quotes 检测）。
    """
    outside = _outside_quotes(cmd)
    if re.search(r"`|\$\(|\bxargs\b|\btee\b", outside):
        return False
    if _has_write_redirect(outside):  # 输出重定向（仅 2> 系 stderr 豁免）
        return False
    saw_curl = False
    for seg in _split_shell_segments(cmd):
        seg = seg.strip()
        if not seg:
            continue
        if _S15_FETCH_CURL_RE.match(seg):
            saw_curl = True
            continue
        if _S15_READONLY_CMD_RE.match(seg) or re.match(r"^\s*jq\b", seg):
            continue
        return False
    return saw_curl


def _s15_allowed(
    tool: str,
    tool_input: dict,
    ev_file: Path,
    step: "engine.Step",
    cwd: str,
    payload_file: Path | None = None,
    project_root: Path | None = None,
) -> bool:
    """S15 白名单判定：常驻集 / Write 系仅 evidence+载荷 / Bash 编排模式 / 步骤声明。

    project_root：项目工具（组件 B）command 头白名单需要；None = 不启用该项目分支
    （默认不宽松——调用方显式传 project_root 才放行注册工具）。
    """
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
        # evidence 目录下可写；直写 <name>.jsonl 本体由 S14 在前置段单独 deny
        # （收编到 append-trace）。v2.125：载荷挪 worktree 根（出 .claude 保护
        # 目录），S15 放行新落点（== 载荷路径，单源 engine.trace_payload_path）。
        if payload_file is not None and rp == payload_file.resolve():
            return True
        return bool(fp) and rp.parent == ev_file.parent
    if tool == "Bash":
        cmd = str(tool_input.get("command") or "")
        if _s15_bash_orchestration(cmd, ev_file) or _s15_bash_readonly_discovery(cmd, step.deny_readonly):
            return True
        # 组件 B：项目工具 command 头白名单（只读发现类，弱模型幻觉刹车保留）
        return project_root is not None and _s15_project_tool_command(cmd, project_root)
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


# v4 前台混合（front-tui-hybrid-design §2.3）：非交互位置白名单工具集——
# 记账（output-style 强制 TaskList）/ Read / AskUserQuestion（裁决与对话）。
_FRONT_WHITELIST_TOOLS = frozenset(
    {"Read", "AskUserQuestion", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet"}
)


def _front_fence_verdict(
    project_root: Path, name: str, tool: str, payload: dict
) -> int:
    """front 非交互位置白名单：派发命令（逐字两变体）/ /dl 状态管理 / 白名单工具。

    放行面刻意窄：dl-cmd.sh 全子命令只动 workflow state 不写文件（gate/step-pass/
    dispute 等用户裁决的执行通道）；干活工具一律 deny 指回派发命令。
    """
    ti = payload.get("tool_input") or {}
    if tool in _FRONT_WHITELIST_TOOLS:
        return 0
    if tool == "SlashCommand":  # 用户手敲 /dl gate 等的执行通道
        if str(ti.get("command") or "").startswith("/dl"):
            return 0
    elif tool == "Bash":
        cmd = str(ti.get("command") or "").strip()
        seg_cmd = engine.front_segment_command(name)
        if cmd in {seg_cmd, seg_cmd.replace("~", str(Path.home()), 1)}:
            return 0
        if re.match(r"^bash\s+\S*dl-cmd\.sh(\s|$)", cmd):
            return 0
    _log_deny(project_root, name, "front_fence_deny", f"tool={tool}")
    return _deny(
        "前台模式：当前位置的活归后台工人，本会话不执行。\n"
        "派发用 Bash（run_in_background=true，逐字照抄）：\n"
        f"  {engine.front_segment_command(name)}\n"
        "要与用户交互请直接对话（AskUserQuestion 可用）；看进度用 /dl status。"
    )


# v4 前台混合段跑期间前台会话白名单（front-segment-run-fence-design）：比
# _FRONT_WHITELIST_TOOLS 更窄——段跑期间前台唯一合法动作 = 交互 + 清单记账 +
# /dl 只读裁决。禁 Read（含源码与元数据——前台读 segment_summary/need_user
# 只在段退出后、drive_mode=off 时，落下方 _front_fence_verdict 的 Read 放行）。
_FRONT_SEGMENT_RUN_TOOLS = frozenset(
    {"AskUserQuestion", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet"}
)


def _front_segment_run_verdict(
    project_root: Path, name: str, tool: str, payload: dict
) -> int:
    """段跑期间前台会话白名单：只交互（AskUserQuestion）+ 记账（Task*）+ /dl。

    触发 = 2026-08-13 amplitude_annualized 抢活实证：段工人跑 understand:1 时，
    前台会话并行 grep/Read 源码。drive_mode 早退原先对前台 + 段工人全放行（return
    0），前台抢活无围栏（front-tui-hybrid-design §2.5「接受」的残余风险落地）。
    """
    ti = payload.get("tool_input") or {}
    if tool in _FRONT_SEGMENT_RUN_TOOLS:
        return 0
    if tool == "SlashCommand":  # 用户手敲 /dl status 等的执行通道
        if str(ti.get("command") or "").startswith("/dl"):
            return 0
    _log_deny(project_root, name, "front_segment_run_deny", f"tool={tool}")
    return _deny(
        "段正在后台跑，本会话只等待与交互。\n"
        "不要在本会话探查源码/调用工具（Read/grep/Skill/Agent 等）——活归后台段工人。\n"
        "要与用户交流请直接对话（AskUserQuestion 可用）；看进度用 /dl status。"
    )


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
            payload_path = str(engine.trace_payload_path(project_root, name))
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
        # v2.125：路径单源 engine.trace_payload_path（=worktree 根，出 .claude
        # 写入保护目录——acceptEdits 下 Edit 旧落点必弹窗）。
        payload_path = engine.trace_payload_path(project_root, name)
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

        # v2.xx：fetch-prompt-skeleton.md 兜底（Q1a，tail_volume u:1 子3 实证：
        # 模型 4 次 Write 骨架被 S11 deny）。骨架引擎 --out 独占写，模型只 Read
        # 取用。PreToolUse 不能转换工具，用 deny + 副作用等价：识别到 Write/Edit
        # 骨架 -> 调 fetch_prompt 刷新为引擎版本 -> deny 指路 Read。
        skel_path = (
            project_root / ".claude" / "workflows" / name / "fetch-prompt-skeleton.md"
        )
        try:
            is_skel = Path(fp).resolve() == skel_path.resolve()
        except OSError:
            is_skel = False
        if is_skel:
            prompt = engine.fetch_prompt(project_root, name)
            if prompt is not None:
                skel_path.parent.mkdir(parents=True, exist_ok=True)
                skel_path.write_text(prompt + "\n", encoding="utf-8")
                _log_deny(project_root, name, "skeleton_write_fallback", f"tool={tool}")
                return _deny(
                    "骨架文件由引擎 `--out` 独占生成（你只 Read 取用、在末尾 claim 区"
                    "填后 inline 给 Agent，不写回文件）。已自动用 --out 刷新骨架为引擎"
                    f"版本，Read `{skel_path}` 取用；禁手写/禁自选落盘路径。"
                )
            _log_deny(project_root, name, "skeleton_write_no_sub2", f"tool={tool}")
            return _deny(
                "骨架需子2 拆解深挖 trace 才能组装（fetch_prompt 无子2 trace 返空）--"
                "先回补子2 evidence，再 Bash `python3 ~/.dl-workflow/dl_flow_engine.py "
                "fetch-prompt --out` 落盘骨架。"
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

    # ---- v3 drive 模式（dl_drive.py 外部编排）：S15/S10 跳过 ----
    # S15（零 trace 窗口白名单逼先参与编排）与 S10（未判决 trace 全 deny 逼
    # STEP_DONE+end_turn）的语义前提是「Stop hook 在回合末门控」——drive 模式下
    # 门控/续轮归外部 driver，会话内没有回合纪律可守（禁标记、单步会话）。
    # 上方 S14（evidence 收编）/ S11（阶段写围栏）/ plan-mode 封堵与编排者无关，
    # 全部保留。放 S15 前短路：少两次 state 读 + 无 deny 文案误导。
    #
    # v4 前台混合（front-segment-run-fence-design）：drive_mode 期间段工人
    # （headless claude -p，session_id ≠ state.session_id）与前台会话并存——
    # 段工人全放行（干活）；前台会话（session_id == state.session_id）收紧为
    # 段跑期间白名单（防抢活——2026-08-13 amplitude_annualized 实证：前台在段
    # 跑期间并行 grep/Read 源码）。state.session_id 为空则防御性放行（不误伤段工人）。
    _st = engine.load_state(project_root, name)
    if _st and _st.get("drive_mode"):
        if (
            _st.get("front_mode")
            and _st.get("session_id")
            and _session_id(payload) == _st.get("session_id")
        ):
            return _front_segment_run_verdict(project_root, name, tool, payload)
        # 段工人 per-step 只读发现窄化（deny_readonly）：drive_mode 跳过 S15/S10，
        # 但 deny_readonly 是「堵入口」硬约束（rubric §3.5 #39），必须在此独立
        # 生效——否则子2 禁 grep 只对前台会话有效、段工人照旧 raw grep。
        if tool == "Bash":
            cmd = str((payload.get("tool_input") or {}).get("command") or "")
            try:
                node = engine.get_node(_st["phase"], _st["sub_index"])
                step = engine.sub_step_at(node, _st.get("sub_step_index", 1))
            except (KeyError, TypeError, ValueError):
                step = None
            if step is not None and _deny_readonly_hit(cmd, step.deny_readonly):
                denied = " / ".join(step.deny_readonly)
                _log_deny(
                    project_root, name, "drive_deny_readonly",
                    f"step={_st.get('sub_step_index')}|denied={denied}",
                )
                return _deny(
                    f"本子步骤禁 raw {denied}：代码搜索走 `dl codebase`"
                    f"（symbol 关系用 trace，字符串用 --string）。"
                )
        return 0

    # ---- v4 前台混合（front-tui-hybrid-design §2.3）：非交互位置白名单 ----
    # 活归后台 --segment 工人；前台模型抢干活 = 上下文胀回 v2.x 病灶（本分支的
    # 防御目标）。段在跑 = drive_mode on（上方已 return 0）；「前台亲自干」两态
    # （真·裸开场 / NEED_USER code 13 咬合，engine.front_interactive_work_here
    # 单源）→ 落下方 v2 S15/S10 既有纪律；其余位置（含有陈述的 u:1#1——§8 起
    # 交互步也派段跑 prep）一律前台白名单。
    if _st and _st.get("front_mode"):
        if not engine.front_interactive_work_here(project_root, name, _st):
            return _front_fence_verdict(project_root, name, tool, payload)

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
        if not _s15_allowed(
            tool,
            ti,
            ev_file,
            step_obj,
            cwd,
            engine.trace_payload_path(project_root, name),
            project_root,
        ):
            # v2.118 修 D：有在跑的取证子代理时放行其进程内取证 curl。
            # 子3 派的 agent 可跨步存活到子4（实测 full agent 15:24:44 才归），
            # 子4 fence_allow 无 Bash -> 子代理 curl 被误拒。pending 为 0 时
            # 行为完全不变（不放宽任何非子代理场景）。
            if (
                tool == "Bash"
                and _s15_fetch_curl(str(ti.get("command") or ""))
                and _pending_background_agent_count(_payload_transcript(payload)) > 0
            ):
                _log_deny(
                    project_root,
                    name,
                    "fence_allow_pending_agent_curl",
                    f"step={step_no}",
                )
                return 0
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
                "codegraph / dl-cmd / 引擎只读查询（dl_flow_engine.py "
                "status|current|progress）/ 写 evidence（append-trace 落库）"
                f"{extra}。\n"
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
