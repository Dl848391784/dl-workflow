#!/usr/bin/env python3
"""
dl_flow_engine - 工作流编排内核（唯一真源）。

对应 designs/tui-state-machine-design.md §3。
定义节点树（大节点 + 子节点）+ skill 映射 + gate 判据 + 推进逻辑。
被 hooks（workflow_phase.py / workflow_advance.py）在事件点咨询,不当主进程。

定位（design §2 命名澄清）：TUI 是执行者,engine 是编排者。
- engine 编排：节点树 / 每节点 skill / gate 判据 / 何时推进（定义流程 + 决定流转）。
- engine 不进程驱动：不开 `while: claude -p(...)` 主动调主流程模型轮次。
  主流程回合由 TUI + Stop 事件驱动。
- engine 在两时刻被咨询：UserPromptSubmit（载哪个 skill）、Stop（过 gate 否）。

本阶段（§8.1）= 纯库骨架：节点树 + current_node + run_gate(机械项) + advance + CLI。
judge（语义 gate）在 §8.2 接入；hook 接入在 §8.3。

CLI（供 dl-cmd.sh / 手动覆盖调用）：
  python3 dl_flow_engine.py status  <name>   查当前节点
  python3 dl_flow_engine.py current <name>   输出当前节点定义（json）
  python3 dl_flow_engine.py advance <name>    推进到下一节点（写 state.json）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


# ---------- 节点树（单源在 dl_flow_nodes.py；此处 re-export 保持 engine.* 访问面不变）----------
#
# 拆分缘由（2026-07-27，designs/scope-and-constraints-substeps-design.md §6 前置项）：
# 节点树是声明式数据（每个编排节点 300-600 行 Step 定义，增长高频），机制逻辑
# （state/推进/gate/judge，低频）分离——编排 diff 不再淹没机制代码。
from dl_flow_nodes import (
    ARTIFACT_SECTIONS,  # noqa: F401  # re-export：tests/hooks 经 eng.ARTIFACT_SECTIONS 访问
    GATED_AFTER,
    PHASES,
    PHASE_LABELS,
    SECTIONS_TEXT,  # noqa: F401  # re-export：hooks 注入经 eng.SECTIONS_TEXT 访问
    GateMech,
    Node,
    Step,
    _NODES,  # tests 经 eng._NODES 访问（有意 re-export）
    current_node_id,
    get_node,
    is_gated_after,
    minor_key_map,  # noqa: F401  # re-export：tests/evidence_show 经 eng.minor_key_map 访问
    next_phase,
    node_id,
    phase_index,
    sub_total,
    subphase_labels,
)

# 子步骤门控连续 block 升级阈值：达到后不再让模型盲目重做，
# 注入提示请用户裁决（补充信息 / /dl step-pass 强制放行 / /dl back 回退）。
# rubric 对用户是黑盒，升级出口是「用户裁决」而非「放宽判据」。
SUB_STEP_BLOCK_ESCALATE = 3

# per-wf settings.json 模板版本戳（v2.35，症状 R 防静默权限税）：dl-lib.sh
# wf_write_settings 写 settings 时盖章 wf_settings_template_version；workflow_phase
# 注入与 /dl status 比对本常量，落后即警告 `dl <name> --resume` 刷新——
# settings resume 不刷新，模板变更（白名单扩条目/hooks/defaultMode）前创建的
# 会话会静默缴 auto 权限税（tail_volume plan:3 实测 ~6.4min/20min）。
# **改 wf_write_settings 模板实质内容时 bump 本常量**（唯一 bump 点；存量
# settings 无字段计 v0，全部判落后，--resume 补写自愈）。
# v2：allow 补 AskUserQuestion + Write/Edit(//<主仓>/.claude/**) 路径规则
# （2026-08-01 understand:1 审计：24 次裁决 316.6s 全 allow 纯税，其中
# AskUserQuestion 3 次均值 46.2s 被误归因为用户思考时间）。
SETTINGS_TEMPLATE_VERSION = 4  # v4：删死规则 Write(//path)（文件权限只认 Edit(path)，
# 启动警告实证）+ 短路面修正注释（auto 下 Write/AskQ/Agent 不短路，根治在 launcher
# --permission-mode acceptEdits，2026-08-02 审计）。v3：注册 SessionStart hook（workflow_session.py，v2.45 /clear 交接包注入）


# ---------- 推进（design §5.1 advance）----------


def next_node_id(cur_phase: str, cur_sub: int) -> tuple[str, int] | None:
    """当前节点的下一节点 (phase, sub)。终结返回 None。

    推进规则（design §3 Node.advance 字段）：
    - cur 节点 advance="sub"  -> 同 phase, sub+1（下一子阶段）
    - cur 节点 advance="phase" -> 下一 phase 首节点（下一 phase 有子阶段=sub=1, 无=sub=0）
    - cur 节点 advance="done"  -> None（终结）
    """
    node = get_node(cur_phase, cur_sub)
    if node.advance == "done":
        return None
    if node.advance == "sub":
        return cur_phase, cur_sub + 1
    # advance == "phase"：进下一 phase 首节点
    nxt = next_phase(cur_phase)
    if nxt is None:
        return None  # 末 phase 但 advance 非 done（数据不一致,不应发生）
    return nxt, (1 if sub_total(nxt) > 0 else 0)


# ---------- state.json 读写（design §4 schema 演进）----------
#
# schema：沿用现有 dl-lib.sh:142 结构 + 新增 node / node_attempts 字段。
# 旧 state（无新字段）向后兼容：读时缺则按 phase+sub 推导补默认。
# 主 repo 根反查沿用 workflow_phase.py:101 范式（git rev-parse --git-common-dir）。


def resolve_project_root(cwd: str) -> Path | None:
    """从 cwd（通常 worktree 内）反查主 repo 根。

    worktree 内 --git-common-dir 返回主 repo .git 绝对路径 -> parent = 主 repo 根。
    主 repo 内返回 ".git" 相对 -> 回退 --show-toplevel。
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
    except (subprocess.SubprocessError, OSError):
        pass
    return None


def resolve_workflow_name(cwd: str) -> str | None:
    """从 cwd（worktree 路径）反查工作流名。路径含 .claude/worktrees/<name>。"""
    parts = Path(cwd).parts
    if "worktrees" in parts:
        i = parts.index("worktrees")
        if i + 1 < len(parts):
            return parts[i + 1]
    return None


def stamp_commit_sha(cwd: str) -> str:
    """取 worktree 内项目 repo 当前 HEAD SHA（防腐锚点,evidence-chain-design §6.1）。

    取不到（非 git / 无 commit）-> 空串（不阻断,事后回溯降级）。
    收口到 engine:evidence_append.py 旧 _stamp_commit_sha 范式迁此。
    """
    try:
        res = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass
    return ""


def state_path(project_root: Path, name: str) -> Path:
    return project_root / ".claude" / "workflows" / name / "state.json"


def load_state(project_root: Path, name: str) -> dict[str, Any] | None:
    f = state_path(project_root, name)
    if not f.exists():
        return None
    try:
        with f.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    """补齐新字段（node / node_attempts / sub_step_index）,旧 state 向后兼容。

    守 no silent fallback：node 字段缺失时按 phase+sub 推导补默认,不静默用错值。
    推导值与显式 node 不一致时**报错暴露**（防两者失同步）。
    §orchestration v2：sub_step_index 缺失按节点有无 sub_steps 补默认（1 / 0）；
    显式值与 sub_steps 总数不符（超出范围）-> 报错暴露。
    """
    phase = state.get("phase", "understand")
    sub = state.get("sub_index", 1 if sub_total(phase) > 0 else 0)
    derived = current_node_id(phase, sub)
    if "node" not in state:
        state["node"] = derived
    elif state["node"] != derived:
        # 显式 node 与 phase+sub 推导不一致 -> 暴露,不猜
        raise ValueError(
            f"state.node={state['node']!r} 与 phase+sub 推导={derived!r} 不一致"
        )
    state.setdefault("node_attempts", 0)
    # §substep-gate-at-stop S1：子步骤门控判定游标（key=<node>#<sub_step> -> 最新已判 trace 行 sha1）。
    state.setdefault("last_judged_trace", {})
    # §substep-gate-at-stop S10：PreToolUse 步骤围栏开关（/dl fence on|off）。
    state.setdefault("enforce_step_fence", True)
    # §orchestration v2：sub_step_index 补默认 + 范围校验
    node = get_node(phase, sub)
    if node.sub_steps:
        if "sub_step_index" not in state:
            state["sub_step_index"] = 1  # 有子步骤 -> 起于首步
        else:
            n = state["sub_step_index"]
            total = len(node.sub_steps)
            if not (1 <= n <= total):
                raise ValueError(
                    f"state.sub_step_index={n} 越界（节点 {derived} 有 {total} 子步骤）"
                )
    else:
        state.setdefault("sub_step_index", 0)  # 无子步骤 -> 0
    return state


def save_state(project_root: Path, name: str, state: dict[str, Any]) -> None:
    f = state_path(project_root, name)
    f.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _now()
    with f.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


# ---------- 推进写 state（design §5.1 advance）----------


def advance_state(project_root: Path, name: str, via: str = "auto") -> dict[str, Any]:
    """推进当前节点到下一节点,写 state.json。返回新 state。

    - 子阶段推进（advance="sub"）：sub_index++,node 更新,node_attempts 归零。
    - 阶段推进（advance="phase"）：phase 进下一,node/sub/gate 更新;若跨闸门需 gate=passed（调用方负责）。
    - 终结（advance="done"）：gate="done",不推进。
    """
    state = load_state(project_root, name)
    if state is None:
        raise FileNotFoundError(f"工作流 {name} 的 state.json 缺失")
    state = normalize_state(state)

    cur_phase = state["phase"]
    cur_sub = state["sub_index"]
    cur_node = get_node(cur_phase, cur_sub)
    now = _now()

    # 记 history exit
    hist = state.get("history", [])
    if hist and hist[-1].get("exited_at") is None:
        hist[-1]["exited_at"] = now
        hist[-1]["via"] = via

    nxt = next_node_id(cur_phase, cur_sub)
    if nxt is None:
        # 终结
        state["gate"] = "done"
        state["node_attempts"] = 0
        state["updated_at"] = now
        state["history"] = hist
        save_state(project_root, name, state)
        return state

    nxt_phase, nxt_sub = nxt
    hist.append(
        {
            "phase": nxt_phase,
            "sub": nxt_sub,
            "entered_at": now,
            "exited_at": None,
            "via": via,
        }
    )
    state["phase"] = nxt_phase
    state["index"] = phase_index(nxt_phase)
    state["sub_index"] = nxt_sub
    state["sub_total"] = sub_total(nxt_phase)
    state["node"] = node_id(nxt_phase, nxt_sub)
    # 阶段推进：进新 phase 的 gate。若新 phase 是闸门目标(cur in GATED_AFTER)
    #   则本次推进已是放行后,新 phase gate=passed;否则 pending。
    if cur_node.advance == "phase" and is_gated_after(cur_phase):
        state["gate"] = "passed"
    else:
        state["gate"] = "pending"
    state["node_attempts"] = 0  # 新节点重试计数归零
    # 跨节点重置 sub_step_index（2026-07-27）：门栏移出 understand:1 后，
    # 编排节点末步会经本函数直接推进到下一个编排节点（understand:1 子6 ->
    # understand:2）——不重置会把 sub_step_index=6 带进只有 5 步的
    # understand:2，下次 normalize_state 范围校验即 ValueError 卡死工作流。
    # （此前无害纯属侥幸：understand:2 当时无编排，sub_step_index 不被读。）
    nxt_node = get_node(nxt_phase, nxt_sub)
    state["sub_step_index"] = 1 if nxt_node.sub_steps else 0
    state["history"] = hist
    save_state(project_root, name, state)
    return state


# ---------- gate 裁决记录（design §8.6：gate-pass 写证据,替代旧 ### EVIDENCE 溯源）----------
#
# design §8.6 + 用户决策（2026-07-23）：旧「模型每轮自发记 claim/依赖/证据」溯源系统弃用,
# 改为 gate 判定通过时记一笔「此节点输出经审核合格」的裁决记录。
# 落点沿用 <项目>/.claude/evidence/<name>.jsonl（per-workflow,与旧系统同文件,新记录 kind=gate）。
# 只在 gate pass 时写（block 不写;block 的重试计数在 state.node_attempts,pass 时一并记 attempts）。


def _evidence_path(project_root: Path, name: str) -> Path:
    return project_root / ".claude" / "evidence" / (name + ".jsonl")


# v2.40 台账提取常量：agent prompt 的档标记（fetch-prompt 骨架预填）与
# light 档 curl 轮次上限（fetch-prompt 分档执行参数文案里的 ≤4 与此同源）。
_AGENT_TIER_RE = re.compile(r"\[tier=(none|light|full)\]", re.IGNORECASE)
_LIGHT_TIER_CURL_CAP = 4


def _subagent_retry_stats(project_root: Path, name: str) -> dict | None:
    """扫描本会话子代理 transcript，统计空响应重试（out=0 的 assistant 请求）。

    v2.39（2026-08-01 tail_volume u:1 子3 复盘）：Q4 取证 agent 26 次空响应
    重试烧掉 1.19M input（占其总 input 90%）——provider 侧稳定性回归此前
    无台账只能靠手工挖 transcript 发现。统计随 gate 裁决记录落 evidence
    （审计锚点），任何会话可直接读 evidence 看到「重试烧掉 X tokens」。
    out=0 + in>0 = 空完成启发式（正常 tool_use/文本响应 out 均 >0）。
    无子代理 / state 缺字段 / transcript 目录不存在 -> None（字段省略，
    不算 fallback：无子代理的步骤本就没有重试暴露）。

    v2.40 扩展：per-agent 记 tier + curl 轮次——tier 从 prompt 的 [tier=X]
    标记提取（fetch-prompt 骨架预填；claim 区只保留本原子一行时归属唯一，
    混合行=模型未按纪律裁剪，tiers 记全部命中、违例判定只认纯 light）；
    light 档 >4 curl 记 light_tier_violations（分档轮次上限的机械台账）。
    """
    state = load_state(project_root, name)
    if not state:
        return None
    sid, wt = state.get("session_id"), state.get("worktree_path")
    if not sid or not wt:
        return None
    # Claude Code 项目目录编码：路径非字母数字字符一律转 '-'
    enc = "".join(c if c.isalnum() else "-" for c in str(wt))
    d = Path.home() / ".claude" / "projects" / enc / sid / "subagents"
    if not d.is_dir():
        return None
    agents = empty = burned = 0
    per_agent = []
    for fp in sorted(d.glob("agent-*.jsonl")):
        agents += 1
        tiers: set[str] = set()
        curl_calls = 0
        first_user_read = False
        try:
            f = fp.open(encoding="utf-8")
        except OSError:
            continue
        with f:
            for line in f:
                try:
                    m = json.loads(line)
                except json.JSONDecodeError:
                    continue
                mtype = m.get("type")
                if mtype == "user" and not first_user_read:
                    first_user_read = True
                    content = m.get("message", {}).get("content")
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        text = " ".join(
                            str(b.get("text", ""))
                            for b in content
                            if isinstance(b, dict)
                        )
                    else:
                        text = ""
                    tiers.update(t.lower() for t in _AGENT_TIER_RE.findall(text))
                if mtype != "assistant":
                    continue
                msg = m.get("message", {})
                u = msg.get("usage", {})
                if u.get("output_tokens", 0) == 0 and u.get("input_tokens", 0) > 0:
                    empty += 1
                    burned += u["input_tokens"]
                for b in msg.get("content") or []:
                    if (
                        isinstance(b, dict)
                        and b.get("type") == "tool_use"
                        and b.get("name") == "Bash"
                        and "curl" in str((b.get("input") or {}).get("command", ""))
                    ):
                        curl_calls += 1
        per_agent.append({"tiers": sorted(tiers), "curl_calls": curl_calls})
    light_violations = sum(
        1
        for a in per_agent
        if a["tiers"] == ["light"] and a["curl_calls"] > _LIGHT_TIER_CURL_CAP
    )
    return {
        "agents": agents,
        "empty_responses": empty,
        "burned_input_tokens": burned,
        "per_agent": per_agent,
        "light_tier_violations": light_violations,
    }


def read_evidence(project_root: Path, name: str) -> str | None:
    """读 evidence/<name>.jsonl 全文，供 judge 作 artifact_content 校验。

    §define-problem-verify-gate：understand:1 的 rubric 依赖 evidence.jsonl，
    Stop hook 调本函数取文件文本喂 judge。缺失/读失败返回 None
    （no silent fallback：judge 拿不到证据 -> 按 rubric 判 block，不默认放行）。
    """
    p = _evidence_path(project_root, name)
    try:
        return p.read_text(encoding="utf-8") if p.exists() else None
    except OSError:
        return None


def write_gate_verdict(
    project_root: Path,
    name: str,
    node: Node,
    attempts: int,
    cwd: str,
    via: str = "auto-stop",
    sub_step: int | None = None,
) -> bool:
    """gate pass 时写一笔裁决记录到 evidence/<name>.jsonl。

    记录：节点 + gate=passed + rubric（审据;None=仅机械过）+ attempts（重试次数）+
    gate_mech（机械类型）+ ts + commit_sha（防腐锚点）+
    major_stage/minor_stage（2026-07-26：与 skill-trace 结构字段对齐——evidence
    里所有记录都携带编排阶段标识，取值单源 = node.phase / node.minor_key；
    整阶段节点 minor_key=None -> minor_stage 写 null，显式不猜）。
    sub_step 非 None 时记入（子步骤级裁决，如 /dl step-pass 手动放行，
    此时 via 标识裁决来源）。
    返回 True=写入成功;False=写失败（no silent fallback：失败留痕由调用方 log,不阻断）。
    """
    record = {
        "kind": "gate",
        "node": node_id(node.phase, node.sub),
        "phase": node.phase,
        "sub": node.sub,
        "label": node.label,
        "major_stage": node.phase.capitalize(),
        "minor_stage": node.minor_key,
        "gate": "passed",
        "gate_mech": node.gate_mech.value,
        "rubric": node.gate_rubric,  # None=仅机械过（无语义审）
        "attempts": attempts,
        "skill": node.skill,
        "via": via,
        "ts": _now(),
        "commit_sha": stamp_commit_sha(cwd),
    }
    if sub_step is not None:
        record["sub_step"] = sub_step
    retry = _subagent_retry_stats(project_root, name)
    if retry is not None:
        record["subagent_retry"] = retry
    path = _evidence_path(project_root, name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        return False
    return True


# judge 判 block 的判词也落 evidence（v2.26）。此前只记 pass——block 判词只存在
# .wf_advance.log，judge 每轮全新调用无记忆 -> 同一 rubric 轮间裁量漂移
# （tail_volume u:3 子4 五连 block 五种解释）。落 evidence 后重判可取回当前轮判词
# 喂 prior_verdicts，前轮判词=裁量先例。单条截断防判词膨胀 judge 输入。
_PRIOR_VERDICT_LIMIT = 3
_PRIOR_REASON_CAP = 400


def write_sub_step_block_verdict(
    project_root: Path,
    name: str,
    node: "Node",
    sub_step: int,
    reason: str,
    attempts: int,
) -> bool:
    """judge 内容性 block 的裁决记录（kind=gate/gate=blocked）落 evidence。

    只记 judge 判词（内容性 block）；corrupt-trace 格式性 block 不记——那是
    机械格式指引，不是内容裁量，进 prior_verdicts 会污染一致性语境。
    返回 True=写入成功；False=写失败（no silent fallback：调用方 log，不阻断）。
    """
    record = {
        "kind": "gate",
        "node": node_id(node.phase, node.sub),
        "phase": node.phase,
        "sub": node.sub,
        "label": node.label,
        "major_stage": node.phase.capitalize(),
        "minor_stage": node.minor_key,
        "gate": "blocked",
        "sub_step": sub_step,
        "reason": reason,
        "attempts": attempts,
        "via": "auto-stop",
        "ts": _now(),
    }
    path = _evidence_path(project_root, name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        return False
    return True


def prior_block_reasons(
    project_root: Path, name: str, sub_step: int, minor_key: str | None
) -> list[str]:
    """取本节点本子步骤的前轮 block 判词（时间序，最近 _PRIOR_VERDICT_LIMIT 条）。

    只取 kind=gate/gate=blocked 且 sub_step/minor_stage 归属匹配的记录——
    passed 记录、它步、它节点（跨节点串号防御，同 _iter_trace_segments）排除。
    单条截断 _PRIOR_REASON_CAP。无 evidence 文件/无可解析行 -> []（首判）。
    """
    path = _evidence_path(project_root, name)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    reasons: list[str] = []
    for line in lines:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            rec.get("kind") == "gate"
            and rec.get("gate") == "blocked"
            and rec.get("sub_step") == sub_step
            and rec.get("minor_stage") == minor_key
            and isinstance(rec.get("reason"), str)
            and rec["reason"].strip()
        ):
            r = rec["reason"]
            reasons.append(
                r[:_PRIOR_REASON_CAP] + ("…" if len(r) > _PRIOR_REASON_CAP else "")
            )
    return reasons[-_PRIOR_VERDICT_LIMIT:]


def write_rubric_dispute(
    project_root: Path, name: str, reason: str
) -> tuple[bool, str]:
    """判据申诉落 evidence（kind=rubric-dispute；v2.30 #7，escalate 第 4 出口）。

    背景（tail_volume u:3 子4）：模型第 4 轮已正确诊断「判据与 in-scope 命题
    矛盾」，但 escalate 只有重做/放行/回退三出口——诊断无通道，用户被迫强制
    放行，判据修订跑到运行外（事后别的会话手工做 v2.23/2.24）。申诉记录把
    判据缺陷闭环在运行内：留痕供后续判据修订检索（evidence 单源），
    **不自动改判据**——判据修订权归人。
    非 kind=gate：申诉不是门控裁决，不进 prior_verdicts 一致性语境。
    """
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    state = normalize_state(state)
    try:
        node = get_node(state["phase"], state["sub_index"])
    except KeyError:
        return False, f"节点 {state['phase']}:{state['sub_index']} 不存在"
    if not reason.strip():
        return False, "申诉须附缺陷论证（哪条判据、为何与命题矛盾/无合法获取路径）"
    record = {
        "kind": "rubric-dispute",
        "node": node_id(node.phase, node.sub),
        "phase": node.phase,
        "sub": node.sub,
        "label": node.label,
        "major_stage": node.phase.capitalize(),
        "minor_stage": node.minor_key,
        "sub_step": state.get("sub_step_index", 1),
        "reason": reason,
        "node_attempts": state.get("node_attempts", 0),
        "ts": _now(),
    }
    path = _evidence_path(project_root, name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        return False, f"写 evidence 失败：{e}"
    return (
        True,
        f"判据申诉已落库（{node_id(node.phase, node.sub)} 子"
        f"{record['sub_step']}）-> {path}（判据修订归人：此记录供修订检索，"
        "不自动改判据；当前步仍须用户指示重做/放行/回退）",
    )


# ---------- gate（compound + 短路;design §5）----------
#
# design §5：机械项（py 规则）+ 语义项（judge）。
#   机械不过 -> 短路 block（不跑 judge,省一次模型调用）。
#   机械过 -> 跑 judge（stateless claude -p）判"符合预期吗"。
# judge 继承主会话 env（design §9 #2）;返回 {pass:bool, reason:str}。


# judge 的 claude -p 调用超时（秒）。judge 是判据非生成,给足但要防挂。
JUDGE_TIMEOUT = 120
# judge 调用失败（API 错/超时/解析失败）时的策略：
#   design §5.1 降级 = 不推进 + 返回 block（no silent fallback：失败必暴露,不默认放行）。

# judge 专属 system prompt（--system-prompt 全量替换默认 coding 助手人设）。
# 2026-07-25 demo 实测：judge 单次 ~20.7k 输入里 ~95% 是 harness 开销（全套工具
# schema + 默认 system prompt + skill 列表），判决载荷（判据+trace+输出）仅 ~0.7k。
# --tools "" + --system-prompt 只裁 harness、判决 prompt 逐字不动，settings/认证
# 链零触碰（ac-ark env 继承与 settings.json env 用户都照常）。实证：同一真实
# pass 案例重放，输入 20728 -> 3590（-83%），判决一致。
JUDGE_SYSTEM_PROMPT = (
    "你是工作流节点门控的评审 judge。"
    "严格按用户消息里的判据判定，只输出一个 JSON,不要多余文本。"
)


def _artifact_file(node: Node, project_root: Path, name: str) -> Path | None:
    """节点产物的规范落点（主仓 .claude/<dir>/<name>.md，2026-07-28 决议）。

    产物标识非裸 .md basename（含 "/" 路径 / "+" 描述性文本）或 phase 无产物
    目录映射 -> None（机械无法判，交语义 judge）。
    """
    if not node.artifact or "/" in node.artifact or node.artifact.endswith("+"):
        return None
    if not node.artifact.endswith(".md"):
        return None
    artifact_dir = _PHASE_ARTIFACT_DIRS.get(node.phase)
    if artifact_dir is None:
        return None
    return project_root / ".claude" / artifact_dir / f"{name}.md"


def _node_entered_at(state: dict[str, Any], node: Node) -> float | None:
    """当前节点的 entered_at（epoch）；无记录/解析失败 -> None（降级仅存在性检查）。

    新鲜度基准（§8.3，artifact-mech-gate-design §1.1 #4）：产物须在本节点内
    写盘——装配义务锚定末子步骤，早于本节点进入时间的文件 = 预写/残留。
    """
    for h in reversed(state.get("history") or []):
        if h.get("phase") == node.phase and h.get("sub") == node.sub:
            s = h.get("entered_at")
            if not s:
                return None
            try:
                return time.mktime(time.strptime(s, "%Y-%m-%dT%H:%M:%S"))
            except (ValueError, TypeError, OverflowError):
                return None
    return None


def gate_verdict_mech(
    node: Node,
    project_root: Path | None = None,
    name: str | None = None,
    not_before: float | None = None,
) -> str | None:
    """机械门判定。返回 None=通过,返回字符串=block 原因。

    §8.3（artifact-mech-gate-design）：ARTIFACT_EXISTS = 产物文件存在 + 可选
    新鲜度（not_before=本节点 entered_at，mtime 更早 = 预写/残留）；
    ARTIFACT_CONTAINS = 存在 + 全文含 node.artifact_contains 全部子串（节标题级）。
    降级纪律（宁纵勿枉，同 codegraph_gate 非 git 放行）：name/project_root 缺失、
    产物标识非单文件、路径映射缺失 -> None，语义 judge 兜底。
    """
    if node.gate_mech == GateMech.NONE:
        return None  # 无机械门,通过
    if node.gate_mech == GateMech.TEST_PASS:
        return None  # 暂不实现,留 §8.2
    if project_root is None or name is None:
        # 无法定位产物 -> 降级放行（宁纵勿枉,同 codegraph_gate 非 git 放行）
        # 语义 judge 兜底。
        return None
    f = _artifact_file(node, project_root, name)
    if f is None:
        return None  # 产物标识含描述性文本（如"代码+commit+测试通过"）-> 交语义 judge
    if not f.is_file():
        return (
            f"产物未落地：{f} 不存在（{node.label} 的装配义务："
            "末子步骤内写盘后才可 STEP_DONE）。写盘后附新 trace 重试。"
        )
    if node.gate_mech == GateMech.ARTIFACT_CONTAINS and node.artifact_contains:
        text = f.read_text(encoding="utf-8", errors="replace")
        missing = [s for s in node.artifact_contains if s not in text]
        if missing:
            return (
                f"产物缺节：{f} 缺「{'」「'.join(missing)}」节"
                f"（{node.label} 末子步骤装配义务）。补装后附新 trace 重试。"
            )
    if not_before is not None and f.stat().st_mtime < not_before:
        return (
            f"产物陈旧：{f} 最后修改早于本节点进入时间——"
            "须在本节点内装配（禁预写/残留）。重新装配写盘后附新 trace 重试。"
        )
    return None


def rubric_needs_evidence(node: Node) -> bool:
    """节点的 gate_rubric 是否依赖 evidence.jsonl（决定 hook 要否读文件喂 judge）。

    §define-problem-verify-gate：rubric 文本含 "evidence/" 或 "skill-trace" 即视为依赖
    （rubric 自带关键词 -> 单源驱动 workflow_advance 读文件 + workflow_phase 注入 trace 写法）。
    无 rubric / 不含关键词 -> False（understand:2-3 等无语义审节点，行为不变）。
    """
    r = node.gate_rubric or ""
    return "evidence/" in r or "skill-trace" in r


def sub_step_total(node: Node) -> int:
    """节点子步骤数（0=无编排）。§orchestration v2 D2。"""
    return len(node.sub_steps) if node.sub_steps else 0


def sub_step_at(node: Node, n: int) -> Step | None:
    """取第 n 子步骤（1-based）；越界/无子步骤返回 None。"""
    if not node.sub_steps or not (1 <= n <= len(node.sub_steps)):
        return None
    return node.sub_steps[n - 1]


def step_needs_evidence(step: Step) -> bool:
    """子步骤是否需读 evidence.jsonl 喂 judge（与 rubric_needs_evidence 同关键词判定）。

    §orchestration v2：子步骤 gate 文本含 "evidence/" 或 "skill-trace" 即读 evidence。
    """
    r = step.gate or ""
    return "evidence/" in r or "skill-trace" in r


def _iter_trace_segments(
    text: str, sub_step_index: int, minor_stage: str | None = None
):
    """逐行扫描 evidence 文本，产出匹配 trace 的 (raw_segment, rec)。

    容错（2026-07-25，demo 74f82d93）：Write 无尾换行 + printf 追加会让两个
    JSON 对象粘在一行，按行 json.loads 会整行跳过 -> trace「隐形」
    （S13 误判无 trace 强制参与）。用 raw_decode 循环扫一行内多个 JSON 对象。
    匹配：kind=skill-trace + sub_step == sub_step_index。
    minor_stage（2026-07-26，goals-and-value-substeps-design）：多编排节点
    （understand:1 ProblemContext / understand:2 GoalsAndValue）共用一个
    evidence 文件且 sub_step 都从 1 起——不按 minor_stage 过滤，ProblemContext
    子1 的 trace 会被 GoalsAndValue 子1 的门控/围栏误读（跨节点串号）。
    None=不过滤（向后兼容）；指定时缺 minor_stage 字段的旧记录不匹配
    （显式不算数，no silent fallback）。
    """
    decoder = json.JSONDecoder()
    for line in text.splitlines():
        s = line.strip()
        idx = 0
        while idx < len(s):
            nxt = s.find("{", idx)
            if nxt == -1:
                break
            idx = nxt
            try:
                rec, end = decoder.raw_decode(s, idx)
            except json.JSONDecodeError:
                break  # 此行剩余部分不是合法 JSON（截断/损坏）-> 下一行
            if (
                isinstance(rec, dict)
                and rec.get("kind") == "skill-trace"
                and rec.get("sub_step") == sub_step_index
                and (minor_stage is None or rec.get("minor_stage") == minor_stage)
            ):
                yield s[idx:end], rec
            idx = end


def sub_step_has_trace(
    project_root: Path, name: str, sub_step_index: int, minor_stage: str | None = None
) -> bool:
    """evidence.jsonl 是否含 sub_step == sub_step_index 的 skill-trace 记录。

    §step-advance-on-submit E1：UserPromptSubmit 据此判断当前子步骤是否已写 evidence
    （避开 transcript flush 竞态；evidence 是上轮写、已落盘）。
    缺文件/读失败 -> False（gate 降级判 block，不默认放行）。
    匹配字段：kind=skill-trace + sub_step == sub_step_index（+ minor_stage，见
    _iter_trace_segments 的跨节点串号说明）。
    q/a 从字符串改为字符串数组（新格式兼容旧格式，单值 q/a 也匹配）。
    容一行多 JSON 对象（raw_decode 循环，见 _iter_trace_segments）。
    """
    text = read_evidence(project_root, name)
    if not text:
        return False
    return any(True for _ in _iter_trace_segments(text, sub_step_index, minor_stage))


def read_evidence_for_step(
    project_root: Path, name: str, sub_step_index: int, minor_stage: str | None = None
) -> str | None:
    """读 evidence 喂 judge 的子步骤裁剪版（2026-07-26，judge 输入 scope 化）。

    背景：子步骤 gate 原先把 evidence **全文**喂 judge，输入随步数线性膨胀
    （demo fbdb6ebd 实测 judge input 3.1k -> 14.9k，8 次累计 ~63k tokens，
    总量 O(n²)），大输入还拉高 judge 超时风险。子步骤 rubric 实际只需：
    当前步 trace（判对象）+ 前序各步**最新** trace（一致性锚点，
    如子5 rubric 要求与子4 verdict 逐项一致）。
    裁剪规则：
    - 只含 kind=skill-trace 且 sub_step ≤ sub_step_index 的记录；
    - 每个 sub_step 只留**最新一条**——返工历史不喂（judge 本就以最新为准，
      历史是纯 token 开销）；
    - kind=gate 裁决记录不喂（judge 判 trace 内容，不判裁决留痕）；
    - minor_stage 指定时只取该节点的 trace（跨节点串号见 _iter_trace_segments）。
    输出按 sub_step 升序拼行（append 协议下与原文顺序一致）。
    无文件/读失败/无匹配 -> None（与 read_evidence 同语义：judge 拿不到
    证据 -> 判 block，no silent fallback）。
    """
    text = read_evidence(project_root, name)
    if not text:
        return None
    latest: dict[int, str] = {}
    for k in range(1, sub_step_index + 1):
        for seg, _rec in _iter_trace_segments(text, k, minor_stage):
            latest[k] = seg
    if not latest:
        return None
    return "\n".join(latest[k] for k in sorted(latest))


# ---------- 上下文交接（context-handoff-design，v2.45）----------
#
# 主会话成本 = Σ(每轮)当前上下文长度；会话不重置则上下文单调涨（u:1 实测
# 54k->283k），成本随轮次平方膨胀。交接架构：子步边界 /clear 换全新上下文，
# 只带机械装配的交接包——成本掰成线性。门控读磁盘状态（state+evidence），
# 天然会话无关，这是架构成立的地基。

# /clear nudge 阈值（tokens）：Stop hook 估算当前上下文超过则在 pass 续轮附
# /clear 建议。纯建议非围栏；读不到 usage 不 nudge（宁纵勿枉）。
HANDOFF_NUDGE_THRESHOLD = 150_000


# ---------- 产物机械装配（render-artifact，v2.59）----------
#
# 四桶分工审计（2026-08-02 用户指令全系统检查）：产物装配 purpose 自写
# 「直接装配、禁二次创作」=系统承认这是转录，却让模型手工抄 trace 拼产物
# 再由 ARTIFACT_CONTAINS 门检查抄对没有——脚本一条命令的事，模型花一整步
# +一轮门控还多抄错/抄漏失败面。render-artifact 从各节点最新 statements/
# 裁决 trace 机械装配 understand.md/plan.md，模型零接触产物文件。
# 内容要改 = 改对应步 trace 后重渲染（trace 仍是唯一真源）。
# design.md 动态文件名（designs/<主题>-design.md）暂留模型装配（独立项）。
_ARTIFACT_RENDER_SOURCES: dict[str, dict] = {
    "understand.md": {
        # 节名 = ARTIFACT_SECTIONS 单源；源 = (minor_stage, 归一化步 sub_step)。
        "sections": {
            "真实问题重述": ("ProblemContext", 5),
            "目标价值": ("GoalsAndValue", 4),
            "范围约束": ("ScopeAndConstraints", 4),
            "成功标准验收包": ("SuccessCriteria", 4),
        },
        # 读回步（裁决记录源：qa 标题含「裁决」/「读回」的项原文收录）。
        "decision_steps": (
            ("ProblemContext", 6),
            ("GoalsAndValue", 5),
            ("ScopeAndConstraints", 5),
            ("SuccessCriteria", 5),
        ),
        # 未选定与接续：understand 四节点 trace 中含「剔除」/「未选定」的
        # qa 项原文收录（供后续 dl 实例接续）。
        "unselected_minors": (
            "ProblemContext",
            "GoalsAndValue",
            "ScopeAndConstraints",
            "SuccessCriteria",
        ),
        "require_all": True,  # understand:4 子5 装配时四节源都必须已存在
        "out_dir": "understands",
    },
    "plan.md": {
        "sections": {
            "执行步骤": ("TaskBreakdown", 4),
            "能力与工具": ("CapabilityToolSelection", 5),
            "执行计划与检查点": ("ExecutionPlanCheckpoints", 4),
        },
        "decision_steps": (
            ("DesignSolution", 6),
            ("TaskBreakdown", 5),
            ("CapabilityToolSelection", 6),
            ("ExecutionPlanCheckpoints", 5),
        ),
        "unselected_minors": (),
        # plan:2/3/4 分工增量装配——只渲染已有源的节，缺源节跳过（输出里
        # 点名，不写进文件）；重渲染幂等覆盖。
        "require_all": False,
        "out_dir": "plans",
    },
    # v2.62：design.md 进机械装配（v2.59 遗留项清零）。动态文件名 =
    # designs/<slug>-design.md（repo 根 designs/，非 .claude/）——slug 由
    # 模型经 --slug 给定（命名是轻创作，留在模型侧；路径/装配归脚本）。
    "design.md": {
        "sections": {"设计决策": ("DesignSolution", 5)},
        "decision_steps": (("DesignSolution", 6),),
        "unselected_minors": (),
        "require_all": True,
        "out_dir": "designs",
        # statements 带八键 fields（change_list/interface_sig/data_contract/
        # callers/rejected/assumptions/acceptance_map/h9_units）——全键渲染，
        # 不做简单 bullet。
        "rich_statements": True,
    },
}

# design.md slug 校验（--slug）：kebab/下划线/点/中文皆可，禁路径分隔与
# 父目录引用（防写出 designs/ 外）。
_SLUG_RE = re.compile(r"^(?!\.{1,2}$)[^/\\]{1,80}$")


def _trace_qa_items(rec: dict) -> list[dict]:
    """trace 记录的 q/a 平行数组 -> [{"q","a"}] 列表（读侧统一形态）。"""
    return [
        {"q": q, "a": a}
        for q, a in zip(rec.get("q") or [], rec.get("a") or [], strict=False)
    ]


def render_artifact(
    project_root: Path,
    name: str,
    basename: str,
    slug: str | None = None,
    force: bool = False,
) -> tuple[bool, str]:
    """render-artifact：从 evidence 最新 trace 机械装配产物（v2.59）。

    返回 (ok, 消息)。源 trace 缺失时按 spec 处理（require_all=缺一节即拒；
    否则跳过该节并在输出点名）。幂等覆盖写，落主仓 .claude/<out_dir>/<name>.md。
    v2.62：design.md 动态文件名——slug 必给（命名留模型，装配归脚本），
    落 repo 根 designs/<slug>-design.md；已存在拒覆盖（state-reset 重跑
    场景用 --force）。
    """
    spec = _ARTIFACT_RENDER_SOURCES.get(basename)
    if spec is None:
        return False, (
            f"render-artifact 不支持 {basename}（支持："
            + "/".join(sorted(_ARTIFACT_RENDER_SOURCES))
            + "）"
        )
    if basename == "design.md":
        if not slug or not _SLUG_RE.match(slug.strip()):
            return False, (
                "design.md 须给合法 --slug（designs/<slug>-design.md 的文件名段，"
                "禁路径分隔符）——命名归你，装配归脚本"
            )
        slug = slug.strip()
    text = read_evidence(project_root, name)
    if not text:
        return False, f"evidence 缺失——{name}.jsonl 不存在或为空"
    latest: dict[tuple, dict] = {}
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("kind") != "skill-trace":
            continue
        latest[(rec.get("minor_stage"), rec.get("sub_step"))] = rec

    parts = [
        f"# {name} · {basename}"
        if basename != "design.md"
        else f"# {slug}-design（{name}）",
        "",
        "（render-artifact 机械装配，禁手改——改内容请改对应步 trace 后重渲染）",
        "",
    ]
    missing = []
    for sec, (minor, stp) in spec["sections"].items():
        rec = latest.get((minor, stp))
        stmts = (rec or {}).get("statements")
        if not stmts:
            missing.append(f"{sec}（{minor} 子{stp} 无 statements trace）")
            continue
        parts.append(f"## {sec}")
        parts.append("")
        for it in stmts:
            if spec.get("rich_statements"):
                # v2.62 design.md：八键 fields 全键渲染（设计包逐项落档）
                parts.append(f"### {it.get('text', '')}（{it.get('type_label', '')}）")
                if str(it.get("boundary") or "").strip():
                    parts.append(f"- 边界/指针：{it['boundary']}")
                for k, v in (it.get("fields") or {}).items():
                    if str(v).strip():
                        parts.append(f"- {k}：{v}")
                parts.append("")
                continue
            extras = [str(it.get("type_label") or ""), str(it.get("boundary") or "")]
            extras += [
                f"{k}={v}"
                for k, v in (it.get("fields") or {}).items()
                if str(v).strip()
            ]
            tail = "；".join(x for x in extras if x.strip())
            parts.append(f"- {it.get('text', '')}" + (f"（{tail}）" if tail else ""))
        parts.append("")
    if missing and spec["require_all"]:
        return False, "装配源 trace 缺失：" + "、".join(missing)

    decisions = []
    for minor, stp in spec["decision_steps"]:
        rec = latest.get((minor, stp))
        for it in _trace_qa_items(rec or {}):
            if "裁决" in str(it["q"]) or "读回" in str(it["q"]):
                decisions.append(it)
    if decisions:
        parts.append("## 裁决记录")
        parts.append("")
        for it in decisions:
            parts.append(f"- 【{it['q']}】{it['a']}")
        parts.append("")

    if spec["unselected_minors"]:
        dropped = []
        for (minor, _stp), rec in latest.items():
            if minor not in spec["unselected_minors"]:
                continue
            for it in _trace_qa_items(rec):
                blob = str(it["q"]) + str(it["a"])
                if "剔除" in blob or "未选定" in blob:
                    dropped.append(it)
        if dropped:
            parts.append("## 未选定与接续")
            parts.append("")
            for it in dropped:
                parts.append(f"- 【{it['q']}】{it['a']}")
            parts.append("")

    if basename == "design.md":
        out = project_root / "designs" / f"{slug}-design.md"
        if out.exists() and not force:
            return False, (
                f"{out} 已存在——拒覆盖（防抹掉其它工作的设计稿）；"
                "state-reset 重跑场景加 --force，或换 slug"
            )
    else:
        out = project_root / ".claude" / spec["out_dir"] / f"{name}.md"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    except OSError as e:
        return False, f"写产物失败：{e}"
    note = f"；跳过缺源节：{'、'.join(missing)}" if missing else ""
    return (
        True,
        f"✓ 已装配 {out}（{len(spec['sections']) - len(missing)} 节 + 裁决记录{note}）",
    )


def render_readback(project_root: Path, name: str) -> tuple[bool, str]:
    """render-readback：读回步呈现材料机械装配（v2.61，stdout 输出）。

    四桶分工审计违规③根治：8 个读回步 purpose 要求「完整呈现」归一化陈述
    +假设/不确定性——完整=无取舍=纯装配，模型却要从 traces 手抄成长文本
    （转录+重打 token 双浪费）。脚本装配打印（Bash 输出用户可见=呈现），
    模型只负责按逐问原则提问+把裁决记入 trace。
    内容：本节点归一化 statements（最新）+ 本节点各步含「假设/不确定/
    退回/候选」标题的 qa 项（逐字收录，无损即完整）。
    """
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    state = normalize_state(state)
    try:
        node = get_node(state["phase"], state["sub_index"])
    except KeyError:
        return False, f"节点 {state['phase']}:{state['sub_index']} 不存在"
    text = read_evidence(project_root, name)
    if not text:
        return False, "evidence 缺失——本节点还无可呈现的 trace"
    latest: dict[int, dict] = {}
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            rec.get("kind") == "skill-trace"
            and rec.get("minor_stage") == node.minor_key
        ):
            latest[rec.get("sub_step")] = rec
    if not latest:
        return False, f"本节点（{node.label}）还没有任何 trace——先完成前序子步骤"

    cur = state.get("sub_step_index", 1)
    parts = [
        f"# 读回材料（{node.label} · 子{cur}）",
        "（render-readback 机械装配——逐字呈现给用户，禁手改；裁决经提问获取后记入 trace）",
        "",
    ]
    stmts_rec = next(
        (
            latest[k]
            for k in sorted(latest, reverse=True)
            if latest[k].get("statements")
        ),
        None,
    )
    if stmts_rec:
        parts.append(f"## 归一化陈述（子{stmts_rec['sub_step']} 最新）")
        parts.append("")
        for it in stmts_rec["statements"]:
            extras = [str(it.get("type_label") or ""), str(it.get("boundary") or "")]
            extras += [
                f"{k}={v}"
                for k, v in (it.get("fields") or {}).items()
                if str(v).strip()
            ]
            tail = "；".join(x for x in extras if x.strip())
            parts.append(f"- {it.get('text', '')}" + (f"（{tail}）" if tail else ""))
        parts.append("")
    extras_items = []
    for k in sorted(latest):
        for it in _trace_qa_items(latest[k]):
            if any(w in str(it["q"]) for w in ("假设", "不确定", "退回", "候选")):
                extras_items.append((k, it))
    if extras_items:
        parts.append("## 假设 / 不确定性 / 退回与候选项（各步 trace 逐字）")
        parts.append("")
        for k, it in extras_items:
            parts.append(f"- （子{k}）【{it['q']}】{it['a']}")
        parts.append("")
    if not stmts_rec and not extras_items:
        return (
            False,
            "本节点 traces 里还拿不出呈现材料（无归一化 statements、无假设类项）",
        )
    return True, "\n".join(parts)


def estimate_context_tokens(transcript_path: str | Path) -> int | None:
    """从 session transcript 尾部最近一条 assistant usage 估算当前上下文 tokens。

    = input + cache_read + cache_creation（该轮看到的全部前缀）。
    文件缺失/无 usage/解析失败 -> None（宁纵勿枉：不 nudge）。
    只读尾部 512KB——transcript 可上 MB，全量读是纯浪费；usage 在每行
    assistant 记录里，尾部窗口足够覆盖最后一轮。
    """
    try:
        p = Path(transcript_path)
        size = p.stat().st_size
        with open(p, "rb") as f:
            f.seek(max(0, size - 512 * 1024))
            tail = f.read().decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    for line in reversed(tail.splitlines()):
        if '"usage"' not in line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue  # 尾部窗口可能切在半行上
        u = (rec.get("message") or {}).get("usage")
        if not isinstance(u, dict):
            continue
        try:
            return (
                int(u.get("input_tokens", 0))
                + int(u.get("cache_read_input_tokens", 0))
                + int(u.get("cache_creation_input_tokens", 0))
            )
        except (TypeError, ValueError):
            continue
    return None


def handoff_pack(project_root: Path, name: str) -> str | None:
    """机械装配交接包（/clear 后新会话注入，context-handoff-design §3）。

    内容（单源生成，禁模型自选）：
    1. 当前位置（节点 + 子步指针；逐步 purpose 由 workflow_phase 每轮注入，不重复）；
    2. 当前节点已完成各子步的**最新** trace（返工历史不带——judge 输入裁剪同
       逻辑，v2.12 read_evidence_for_step 已验证）；
    3. 前序已完成节点：归一化步（倒数第 2 步）+ 读回步（末步，含用户裁决原话——
       v2.45 user_decision_recorded 机械保证其存在）的最新 trace；
    4. 当前步最新 block 判词（/clear 发生在返工中段时，新会话须知道修什么）；
    5. 已装配产物清单（路径指针，禁全文——全文内联 = 把省下的 token 又花回去）。

    无任何 trace -> None（首次启动不注入，调用方静默）。
    """
    state = load_state(project_root, name)
    if state is None:
        return None
    state = normalize_state(state)
    cur_phase, cur_sub = state["phase"], state["sub_index"]
    try:
        cur_node = get_node(cur_phase, cur_sub)
    except KeyError:
        return None
    text = read_evidence(project_root, name)
    if not text:
        return None

    # 单遍扫描：最新 trace（按 minor_stage+sub_step）+ 最新 block 判词（按 node+sub_step）。
    # 容一行多 JSON 对象（raw_decode，同 _iter_trace_segments 的容错动机）。
    latest_trace: dict[tuple, str] = {}
    latest_block: dict[tuple, str] = {}
    decoder = json.JSONDecoder()
    for line in text.splitlines():
        s = line.strip()
        idx = 0
        while idx < len(s):
            nxt = s.find("{", idx)
            if nxt == -1:
                break
            idx = nxt
            try:
                rec, end = decoder.raw_decode(s, idx)
            except json.JSONDecodeError:
                break
            seg = s[idx:end]
            idx = end
            if not isinstance(rec, dict):
                continue
            if rec.get("kind") == "skill-trace":
                latest_trace[(rec.get("minor_stage"), rec.get("sub_step"))] = seg
            elif (
                rec.get("kind") == "gate"
                and rec.get("gate") == "blocked"
                and rec.get("reason")
            ):
                latest_block[(rec.get("node"), rec.get("sub_step"))] = rec["reason"]
    if not latest_trace:
        return None

    cur_step = state.get("sub_step_index", 1)
    cur_key = (phase_index(cur_phase), cur_sub)
    lines = [
        "## WORKFLOW 上下文交接包（/clear 接续——以下为机械装配的前序证据，",
        "禁止重做已完成步骤；从当前子步继续）",
        "",
        f"### 当前位置：{cur_node.label}（{node_id(cur_phase, cur_sub)}）子步骤 {cur_step}",
        "",
    ]
    # 当前节点已完成步的最新 trace（含当前步已有 trace——返工中段 clear 的场景）
    cur_traces = [
        (k[1], seg)
        for k, seg in latest_trace.items()
        if k[0] == cur_node.minor_key and k[1] <= cur_step
    ]
    if cur_traces:
        lines.append(f"### 本节点（{cur_node.label}）各步最新留痕")
        for _step, seg in sorted(cur_traces):
            lines.append(seg)
        lines.append("")
    # 当前步最新 block 判词（返工中段 clear：新会话要知道修什么）
    reason = latest_block.get((node_id(cur_phase, cur_sub), cur_step))
    if reason:
        lines.append(f"### 当前子步最新门控判词（未通过，按此返工）\n{reason}\n")
    # 前序已完成节点：归一化步 + 读回步的最新 trace
    prior_sections = []
    for ph in PHASES:
        subs = range(1, sub_total(ph) + 1) if sub_total(ph) else [0]
        for sub in subs:
            if (phase_index(ph), sub) >= cur_key:
                continue
            try:
                node = get_node(ph, sub)
            except KeyError:
                continue
            if not node.sub_steps or not node.minor_key:
                continue
            n = len(node.sub_steps)
            keep = [
                latest_trace[k]
                for k in ((node.minor_key, n - 1), (node.minor_key, n))
                if k in latest_trace
            ]
            if keep:
                prior_sections.append(
                    f"### 前序节点「{node.label}」归一化陈述 + 用户裁决\n"
                    + "\n".join(keep)
                )
    if prior_sections:
        lines.extend(prior_sections)
        lines.append("")
    # 产物清单（指针非全文）
    artifacts = []
    for ph, adir in _PHASE_ARTIFACT_DIRS.items():
        f = project_root / ".claude" / adir / f"{name}.md"
        if f.is_file():
            artifacts.append(f"- {f}")
    if artifacts:
        lines.append("### 已装配产物（按需 Read，勿重复装配）")
        lines.extend(artifacts)
        lines.append("")
    return "\n".join(lines)


def _advance_sub_step(
    project_root: Path, name: str, state: dict[str, Any], node: Node, cur: int, via: str
) -> dict[str, Any]:
    """子步骤推进共用段：非末步 sub_step_index++（attempts 归零）；末步 advance_state 推进子阶段。

    state 须已 normalize。返回推进后的 state。

    §subphase-hold-gate：node.hold_for_gate 的末步**无条件扣留**（不读 state.gate——
    中途 /dl gate 预放行 phase 闸门会把 gate 置 passed，读它会让门栏被静默穿过，
    见 designs/subphase-hold-gate-design.md §2）。扣留写显式标记 held_for_gate，
    唯一出口 release_subgate（/dl gate 路由）；step-pass 末步同被扣——
    步的放行与子阶段的放行是两个独立的用户决定。
    """
    if cur < len(node.sub_steps):
        state["sub_step_index"] = cur + 1
        state["node_attempts"] = 0
        state["updated_at"] = _now()
        save_state(project_root, name, state)
        return state
    if node.hold_for_gate:
        state["held_for_gate"] = True
        state["updated_at"] = _now()
        save_state(project_root, name, state)
        return state
    # 末步：推进子阶段（advance_state 含 normalize + save）
    return advance_state(project_root, name, via=via)


def phase_done_channel_open(
    project_root: Path, name: str, state: dict[str, Any], node: Node
) -> bool:
    """sub_steps 节点的 PHASE_DONE 通道是否打开（单源判据，hook 两处引用）。

    仅 advance="phase" 的编排末节点（understand:4，success-criteria-substeps-design
    §2）：编排全部完成（当前步=末步且末步最新 trace 已判过）且门栏未扣留时，
    模型的 PHASE_DONE 走无编排节点的阶段闸门路径（写产物 -> PHASE_DONE -> 大闸门）。
    其余节点（advance="sub" 编排节点/无编排节点/门栏扣留中）一律 False：
    - advance="sub"：末步 pass 即推进，无 PHASE_DONE 通道；
    - 门栏扣留中：PHASE_DONE 无效，唯一出口 /dl gate（subgate-pass）。
    """
    if not (node.sub_steps and node.advance == "phase"):
        return False
    if state.get("held_for_gate"):
        return False
    cur = state.get("sub_step_index", 1)
    if cur != len(node.sub_steps):
        return False
    sha = latest_trace_sha1(project_root, name, cur, node.minor_key)
    if sha is None:
        return False
    key = f"{node_id(node.phase, node.sub)}#{cur}"
    return state.get("last_judged_trace", {}).get(key) == sha


def release_subgate(project_root: Path, name: str, cwd: str) -> tuple[bool, str]:
    """子阶段门栏放行（/dl gate 在 held 状态下的路由出口，§subphase-hold-gate）。

    三件事（对齐 step-pass 的手动放行留痕原则）：
    1. 校验 held 标记（无标记=没在门栏前，报错暴露不猜）。
    2. write_gate_verdict(via="manual-subgate-pass", sub_step=末步)——手动放行必留痕。
    3. 清标记 + 推进——按 node.advance 分两种：
       - advance="sub"（understand:2/3）：advance_state 推进子阶段（子阶段推进把
         state.gate 归 pending，understand 末节点的 phase 闸门仍需独立 /dl gate，
         无语义叠加）。
       - advance="phase"（understand:4）：**只放行不推进**——放行后模型写阶段产物
         + PHASE_DONE 撞 phase 大闸门（understand 在 GATED_AFTER，需第二次 /dl gate；
         success-criteria-substeps-design §2）。若在此 advance_state，大闸门会被
         subgate-pass 静默吸收（一次 /dl gate 既放子闸门又穿大闸门），且产物
         understand.md 失去写入窗口。
    """
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    state = normalize_state(state)
    try:
        node = get_node(state["phase"], state["sub_index"])
    except KeyError:
        return False, f"节点 {state['phase']}:{state['sub_index']} 不存在"
    cur = state.get("sub_step_index", 1)
    held = (
        state.get("held_for_gate")
        and node.hold_for_gate
        and node.sub_steps
        and cur == len(node.sub_steps)
    )
    if not held:
        return False, f"节点 {node_id(node.phase, node.sub)} 不在门栏扣留状态"
    ok = write_gate_verdict(
        project_root,
        name,
        node,
        state.get("node_attempts", 0),
        cwd,
        via="manual-subgate-pass",
        sub_step=cur,
    )
    if not ok:
        return False, "裁决记录写 evidence 失败（未放行；见权限/磁盘）"
    state.pop("held_for_gate", None)
    state["updated_at"] = _now()
    save_state(project_root, name, state)
    if node.advance == "phase":
        # advance="phase" 节点（understand:4）：门栏放行 ≠ 阶段推进。
        # 模型写产物 + PHASE_DONE -> phase 大闸门（仍需第二次 /dl gate）。
        return (
            True,
            f"门栏放行：{node.label} 已批准 —— 模型将汇总写 "
            f"{node.artifact or '阶段产物'} 并输出 ### PHASE_DONE: {node.phase}"
            f"（进下一阶段的 phase 闸门仍需 /dl gate 放行）",
        )
    advance_state(project_root, name, via="manual-subgate-pass")
    nxt_phase, nxt_sub = next_node_id(node.phase, node.sub)
    return (
        True,
        f"门栏放行：{node.label} 已批准 -> 推进 {node_id(nxt_phase, nxt_sub)}",
    )


def gate_and_advance_sub_step(
    project_root: Path, name: str, node: Node, sub_step_index: int
) -> tuple[bool, str, dict[str, Any]]:
    """gate 当前子步骤 + 推进。返回 (advanced, reason, new_state)。

    §step-advance-on-submit E2（3a）：gate+推进合一，供 UserPromptSubmit 调用。
    - gate=None 自动过；否则 run_judge（artifact_content = read_evidence_for_step 裁剪版）。
    - advanced=True：已推进（非末步 sub_step_index++ / 末步 advance_state 推进子阶段）。
    - advanced=False：block（未推进，返回 reason，模型需重做）。
      block 时累加 state.node_attempts 并落盘（sub_step 路径的重试计数，
      连续 block 达 SUB_STEP_BLOCK_ESCALATE 后 hook 升级为用户裁决）。
    new_state：推进后/计数后的 state（供注入取 sub_step_index/node_attempts）；
    前置校验失败（步骤不存在/state 缺失）时为 {}。
    """
    step = sub_step_at(node, sub_step_index)
    if step is None:
        return False, f"子步骤 {sub_step_index} 不存在", {}
    if step.gate is None:
        ok, reason = True, ""
    else:
        artifact = read_evidence_for_step(
            project_root, name, sub_step_index, node.minor_key
        )
        priors = prior_block_reasons(project_root, name, sub_step_index, node.minor_key)
        ok, reason = run_judge(
            step.gate,
            f"{node.label} · 子步骤{sub_step_index}",
            "",
            artifact_content=artifact,
            prior_verdicts=priors,
        )
    if not ok:
        state = load_state(project_root, name)
        if state is not None:
            state = normalize_state(state)
            state["node_attempts"] = state.get("node_attempts", 0) + 1
            state["updated_at"] = _now()
            save_state(project_root, name, state)
            return False, reason or "judge 未给出原因", state
        return False, reason or "judge 未给出原因", {}
    # 推进（末步先过产物机械门 §8.3：judge 过 ≠ 产物已落盘——装配义务锚定末子步骤，
    # understand:4 子5 这类 gate=None 交互步的唯一硬兜底）
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失", {}
    state = normalize_state(state)
    if node.sub_steps and sub_step_index == len(node.sub_steps):
        mech_block = gate_verdict_mech(
            node, project_root, name, _node_entered_at(state, node)
        )
        if mech_block is not None:
            state["node_attempts"] = state.get("node_attempts", 0) + 1
            state["updated_at"] = _now()
            save_state(project_root, name, state)
            return False, mech_block, state
    return (
        True,
        "",
        _advance_sub_step(
            project_root, name, state, node, sub_step_index, via="step-submit"
        ),
    )


def force_pass_sub_step(project_root: Path, name: str, cwd: str) -> tuple[bool, str]:
    """用户裁决强制放行当前子步骤（/dl step-pass；连续 block 达阈值后的升级出口）。

    与 judge pass 同路径推进（非末步 sub_step_index++ / 末步推进子阶段），
    但先写 kind=gate 裁决记录（via=manual-step-pass + sub_step + attempts）——
    手动放行必须留痕，否则 evidence 里该子步骤无任何通过记录。
    返回 (ok, 消息)。rubric 是黑盒：此命令是用户裁决，不修改任何判据。
    """
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    state = normalize_state(state)
    try:
        node = get_node(state["phase"], state["sub_index"])
    except KeyError:
        return False, f"节点 {state['phase']}:{state['sub_index']} 不存在"
    if not node.sub_steps:
        return (
            False,
            f"节点 {node_id(node.phase, node.sub)} 无子步骤编排，step-pass 不适用",
        )
    cur = state.get("sub_step_index", 1)
    step = sub_step_at(node, cur)
    if step is None:
        return False, f"子步骤 {cur} 不存在"
    attempts = state.get("node_attempts", 0)
    ok = write_gate_verdict(
        project_root, name, node, attempts, cwd, via="manual-step-pass", sub_step=cur
    )
    if not ok:
        return False, "裁决记录写 evidence 失败（未推进；见权限/磁盘）"
    new_state = _advance_sub_step(
        project_root, name, state, node, cur, via="manual-step-pass"
    )
    if cur < len(node.sub_steps):
        return True, f"子步骤 {cur} 已手动放行 -> 子步骤 {cur + 1}"
    if new_state.get("held_for_gate"):
        # §subphase-hold-gate：步的放行 ≠ 子阶段的放行，门栏仍需 /dl gate
        return True, f"末子步骤 {cur} 已手动放行，子阶段推进被门栏扣留 — /dl gate 放行"
    return True, f"末子步骤 {cur} 已手动放行 -> 子阶段推进"


# ---------- state-reset：整体回滚到任意历史子步骤（designs/state-reset-command-design.md）----------


def _node_order() -> dict[str, int]:
    """节点 id -> 线性序（_NODES 声明序 = 编排推进序）。"""
    return {nid: i for i, nid in enumerate(_NODES)}


def _parse_reset_target(
    state: dict[str, Any], target: str
) -> tuple[Node, int] | tuple[None, str]:
    """解析 state-reset 寻址 -> (目标节点, step) 或 (None, 错误信息)。

    三种形态（design §2）：
      "<n>"                     当前节点内回退到子步骤 n（兼容旧 step-reset 语义）
      "<phase>:<minor>"         跨节点回退到子阶段首步（无子步骤节点唯一合法形态）
      "<phase>:<minor>:<step>"  跨节点回退到子阶段子步骤 step（含 step 作废）
    minor = 子阶段序号或 minor_key（大小写不敏感）。
    """
    cur_node = get_node(state["phase"], state["sub_index"])
    parts = target.split(":")
    if len(parts) == 1:
        # 节点内回退：旧 step-reset 语义
        if not cur_node.sub_steps:
            return (
                None,
                f"节点 {node_id(cur_node.phase, cur_node.sub)} 无子步骤编排，state-reset <n> 不适用",
            )
        if not parts[0].isdigit():
            return None, (
                f"寻址 '{target}' 非法——用法: state-reset <n> | <phase>:<minor>[:<step>]"
            )
        step = int(parts[0])
        total = len(cur_node.sub_steps)
        if not (1 <= step <= total):
            return None, f"子步骤 {step} 越界（本节点 1..{total}）"
        return cur_node, step
    if len(parts) not in (2, 3):
        return (
            None,
            f"寻址 '{target}' 非法——用法: state-reset <n> | <phase>:<minor>[:<step>]",
        )
    phase = parts[0].lower()
    if phase not in PHASES:
        return None, f"phase '{parts[0]}' 不存在（合法: {', '.join(PHASES)}）"
    minor = parts[1]
    node: Node | None = None
    if minor.isdigit():
        try:
            node = get_node(phase, int(minor))
        except KeyError:
            node = None
    else:
        for cand in _NODES.values():
            if (
                cand.phase == phase
                and cand.minor_key
                and cand.minor_key.lower() == minor.lower()
            ):
                node = cand
                break
    if node is None:
        valid = (
            ", ".join(
                f"{cand.sub}={cand.minor_key}"
                for cand in _NODES.values()
                if cand.phase == phase and cand.minor_key
            )
            or "（该 phase 无子阶段，用 <phase>:0）"
        )
        return None, f"子阶段 '{minor}' 不存在于 {phase}（合法: {valid}）"
    if not node.sub_steps:
        if len(parts) == 3:
            return (
                None,
                f"节点 {node_id(node.phase, node.sub)} 无子步骤编排，三段式 step 无意义（用 {phase}:{minor} 两段式）",
            )
        return node, 0
    step = 1 if len(parts) == 2 else (int(parts[2]) if parts[2].isdigit() else -1)
    total = len(node.sub_steps)
    if not (1 <= step <= total):
        return (
            None,
            f"子步骤 {parts[2] if len(parts) == 3 else step} 越界（节点 {node_id(node.phase, node.sub)} 1..{total}）",
        )
    return node, step


def _reset_target_owner(rec: dict[str, Any]) -> str | None:
    """evidence 记录归属的节点 id（反查不到 -> None，调用方按「暴露而非吞掉」保留）。

    skill-trace 按 minor_stage 反查 minor_key；gate 行优先 phase+sub 字段，
    缺时回落 node 字段（旧记录可能无 phase/sub）。
    """
    if rec.get("kind") == "skill-trace":
        mk = rec.get("minor_stage")
        if not isinstance(mk, str):
            return None
        for nid, cand in _NODES.items():
            if cand.minor_key == mk:
                return nid
        return None
    if rec.get("kind") == "gate":
        ph, sb = rec.get("phase"), rec.get("sub")
        if isinstance(ph, str) and isinstance(sb, int):
            nid = node_id(ph, sb)
            if nid in _NODES:
                return nid
        nid = rec.get("node")
        return nid if isinstance(nid, str) and nid in _NODES else None
    return None


def reset_state(project_root: Path, name: str, target: str) -> tuple[bool, str]:
    """整体回滚到目标子步骤（/dl state-reset，designs/state-reset-command-design.md）。

    三件事（都落盘才算完成，无 silent fallback）：
    1. evidence 纯硬删：目标节点 T 的 sub_step>=n 行 + T 自身节点级 gate 裁决行 +
       所有线性序在 T 之后节点的 trace/gate 行（坏行/归属不明行保留，暴露而非吞掉）。
    2. state 回滚：phase/sub_index/node/index/sub_total=T、sub_step_index=n、
       node_attempts=0、held_for_gate 删、gate 按 advance_state 同规则重算、
       last_judged_trace 清 T(k>=n) 与后序节点游标、history 截断到 T（T 条目重开）。
    3. 阶段产物直接删除：T.phase 及之后所有 phase 的产物（主仓 .claude/<dir>s/<name>.md
       + worktree 根 legacy <phase>.md）；文件不存在非错误。不动 designs/*.md 与
       worktree 代码/commit（design §3.3）。
    """
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    state = normalize_state(state)
    parsed = _parse_reset_target(state, target.strip())
    if parsed[0] is None:
        return False, parsed[1]
    t_node, step = parsed
    t_nid = node_id(t_node.phase, t_node.sub)
    order = _node_order()
    cur_nid = node_id(state["phase"], state["sub_index"])
    t_ord, cur_ord = order[t_nid], order[cur_nid]
    if t_ord > cur_ord:
        return False, (
            f"目标 {t_nid} 是前向节点（当前 {cur_nid}）——state-reset 只回退，"
            "往前用 /dl next|jump"
        )

    # 1. evidence 过滤
    removed = 0
    path = _evidence_path(project_root, name)
    if path.exists():
        kept: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                kept.append(line)  # 坏行不属于任何节点，保留（暴露而非吞掉）
                continue
            owner = _reset_target_owner(rec)
            if owner is None:
                kept.append(line)  # 归属不明：保留（暴露而非吞掉）
                continue
            o = order[owner]
            if o > t_ord:
                removed += 1  # 后序节点整行作废
                continue
            if o == t_ord:
                ss = rec.get("sub_step")
                if isinstance(ss, int) and ss >= step:
                    removed += 1  # T 节点内 sub_step>=n 作废
                    continue
                if rec.get("kind") == "gate" and ss is None:
                    removed += 1  # T 自身节点级裁决已失效（回退到中段）
                    continue
            kept.append(line)
        path.write_text("".join(line + "\n" for line in kept), encoding="utf-8")

    # 2. state 回滚
    state["phase"] = t_node.phase
    state["index"] = phase_index(t_node.phase)
    state["sub_index"] = t_node.sub
    state["sub_total"] = sub_total(t_node.phase)
    state["node"] = t_nid
    state["sub_step_index"] = step if t_node.sub_steps else 0
    state["node_attempts"] = 0
    state.pop("held_for_gate", None)  # 门栏状态同步失效（同旧 step-reset）
    # gate 重算（advance_state 同规则）：进入 T 跨过的前驱节点是阶段出口且
    # 其 phase 在 GATED_AFTER -> 进入已是放行后。
    prev = list(_NODES.values())[t_ord - 1] if t_ord > 0 else None
    state["gate"] = (
        "passed"
        if prev is not None and prev.advance == "phase" and is_gated_after(prev.phase)
        else "pending"
    )
    judged = state.get("last_judged_trace", {})
    for k in list(judged):
        owner, _, num = k.rpartition("#")
        try:
            n = int(num)
        except ValueError:
            continue  # 畸形 key 保留（暴露而非吞掉）
        if owner not in order:
            continue  # 归属不明游标保留
        if order[owner] > t_ord or (order[owner] == t_ord and n >= step):
            del judged[k]
    # history 截断：删 entered 节点序 > T 的条目；T 条目重开（exited_at=None）
    hist = state.get("history", [])
    new_hist: list[dict[str, Any]] = []
    t_found = False
    for h in hist:
        try:
            h_nid = node_id(h["phase"], int(h["sub"]))
        except (KeyError, TypeError, ValueError):
            new_hist.append(h)  # 畸形条目保留（暴露而非吞掉）
            continue
        if h_nid not in order or order[h_nid] > t_ord:
            continue  # 后序节点条目截掉（含畸形 node id 之外的未知节点）
        if order[h_nid] == t_ord:
            h["exited_at"] = None  # 重开
            t_found = True
        new_hist.append(h)
    if not t_found:
        new_hist.append(
            {
                "phase": t_node.phase,
                "sub": t_node.sub,
                "entered_at": _now(),
                "exited_at": None,
                "via": "state-reset",
            }
        )
    state["history"] = new_hist
    state["updated_at"] = _now()
    save_state(project_root, name, state)

    # 3. 阶段产物删除（T.phase 及之后；缺失非错误）
    deleted_files: list[str] = []
    wt_root = state.get("worktree_path")
    for ph in PHASES[phase_index(t_node.phase) - 1 :]:
        candidates: list[Path] = []
        adir = _PHASE_ARTIFACT_DIRS.get(ph)
        if adir:
            candidates.append(project_root / ".claude" / adir / f"{name}.md")
        legacy_name = f"{ph}.md"
        if isinstance(wt_root, str) and wt_root:
            candidates.append(Path(wt_root) / legacy_name)
        candidates.append(project_root / ".claude" / "worktrees" / name / legacy_name)
        seen: set[str] = set()
        for p in candidates:
            key = str(p)
            if key in seen:
                continue
            seen.add(key)
            try:
                if p.exists():
                    p.unlink()
                    deleted_files.append(key)
            except OSError as e:
                return False, f"产物删除失败 {p}: {e}（state 已回滚，产物残留需手工清）"

    total = len(t_node.sub_steps or [])
    step_desc = f"子步骤 {step}/{total}" if total else "（无子步骤节点）"
    return (
        True,
        f"已回退到 {t_nid} {step_desc}（删 evidence 行 {removed} 条，"
        f"删产物 {len(deleted_files)} 个，游标/重试计数/门栏已清）",
    )


# ---------- 子步骤 Stop 门控（§substep-gate-at-stop）----------


def latest_trace_sha1(
    project_root: Path, name: str, sub_step_index: int, minor_stage: str | None = None
) -> str | None:
    """evidence.jsonl 里 sub_step == sub_step_index 的**最后一条** skill-trace 的 sha1。

    §substep-gate-at-stop S1：Stop hook 以此与 state.last_judged_trace 比对判定「有新产出」。
    用 hash 不用行数：模型违规覆盖写也产生新 hash -> 必判。无匹配/文件缺 -> None。
    容一行多 JSON 对象（raw_decode，取最后一个匹配段的 hash）。
    minor_stage 指定时只取该节点的 trace（跨节点串号见 _iter_trace_segments）。
    """
    text = read_evidence(project_root, name)
    if not text:
        return None
    latest: str | None = None
    for seg, _rec in _iter_trace_segments(text, sub_step_index, minor_stage):
        latest = seg
    if latest is None:
        return None
    return hashlib.sha1(latest.encode("utf-8")).hexdigest()


def evidence_mentions_sub_step(
    project_root: Path, name: str, sub_step_index: int, minor_stage: str | None = None
) -> bool:
    """evidence 原文是否提及 sub_step==N（raw 子串探测，不解析 JSON）。

    §S13 分诊用：latest_trace_sha1 为 None 时区分「真无 trace」（强制参与）
    vs「有内容但 JSON 损坏/被合并后仍无法解析」（提示修复格式）。
    minor_stage 指定时要求同一行同时含 sub_step 与 minor_stage 子串
    （跨节点串号见 _iter_trace_segments；行级探测防 ProblemContext 的
    同号子步骤被误判为本节点的损坏写入）。
    """
    text = read_evidence(project_root, name)
    if not text:
        return False
    needles = (
        f'"sub_step":{sub_step_index}',
        f'"sub_step": {sub_step_index}',
    )
    if minor_stage is None:
        return any(n in text for n in needles)
    mneedles = (
        f'"minor_stage":"{minor_stage}"',
        f'"minor_stage": "{minor_stage}"',
    )
    return any(
        any(n in line for n in needles) and any(m in line for m in mneedles)
        for line in text.splitlines()
    )


def corrupt_trace_after_latest(
    project_root: Path, name: str, sub_step_index: int, minor_stage: str | None = None
) -> bool:
    """最新合法 trace 之后是否存在「含 sub_step==N 子串但解析不出合法记录」的损坏行。

    §corrupt-rework-detect（2026-07-26，demo d59d05ea）：模型返工把 trace 写碎
    （shell 单引号内塞字面换行 -> JSON 跨两行；字面 \\" 原样落盘）->
    latest_trace_sha1 仍等于已判 hash -> 「同 hash 静默放行」把「写了但写坏了」
    误判为「没写新东西」-> 模型以为返工完成，工作流看似卡死（无任何日志）。
    只数**最新合法 trace 行之后**的损坏行：之前的损坏行是已处理历史（模型修好后
    旧碎片仍在文件里），不重复报警。append 协议下新写入必在最新合法行之后。
    minor_stage 指定时：合法行定位限定该节点；损坏行候选 = 含 sub_step 子串
    且【不含 minor_stage 字段（截断碎片无法归属，按本节点候选处理）或
    含本节点 minor_stage】——含**他节点** minor_stage 的行跳过（跨节点串号
    见 _iter_trace_segments）。截断碎片常丢 minor_stage 字段（demo d59d05ea
    的碎片就没有），若强制要求 minor_stage 子串会把真损坏放行回「卡死」。
    """
    text = read_evidence(project_root, name)
    if not text:
        return False
    lines = text.splitlines()
    last_valid_idx = -1
    for i, line in enumerate(lines):
        if any(True for _ in _iter_trace_segments(line, sub_step_index, minor_stage)):
            last_valid_idx = i
    needle = (
        f'"sub_step":{sub_step_index}',
        f'"sub_step": {sub_step_index}',
    )
    mneedle = (
        (f'"minor_stage":"{minor_stage}"', f'"minor_stage": "{minor_stage}"')
        if minor_stage is not None
        else None
    )
    for line in lines[last_valid_idx + 1 :]:
        if not any(n in line for n in needle):
            continue
        if any(g in line for g in ('"kind":"gate"', '"kind": "gate"')):
            continue  # 机制侧裁决记录（engine 单次 write 原子落盘）非损坏候选（v2.26）
        if (
            mneedle is not None
            and '"minor_stage"' in line
            and not any(m in line for m in mneedle)
        ):
            continue  # 明确归属他节点的行，不归本节点判
        if not any(
            True for _ in _iter_trace_segments(line, sub_step_index, minor_stage)
        ):
            return True
    return False


def _corrupt_trace_reason(sub_step_index: int) -> str:
    """损坏返工的 block 判词（§corrupt-rework-detect）：指路到格式修复，不判内容。"""
    return (
        f"evidence 写入损坏：文件里存在 sub_step=={sub_step_index} 的记录片段，"
        "但不是可解析的单行合法 JSON（手写 JSON 跨行/转义出错的典型后果）。"
        "门控读不到等同没写。返工：改用 append-trace 落库——Write 载荷 "
        '{"purpose":...,"qa":[{"q":...,"a":...}]} 到 .claude/evidence/.trace-payload-*.json，'
        "再 Bash `python3 ~/.dl-workflow/dl_flow_engine.py append-trace --from-file <载荷>`"
        "（格式/路径/结构字段全归脚本，不会再写碎）。"
    )


def gate_sub_step_at_stop(
    project_root: Path, name: str, cwd: str
) -> tuple[str, str, dict[str, Any]]:
    """Stop 时刻的子步骤门控。返回 (action, reason, state)。

    §substep-gate-at-stop：触发 = 当前子步骤最新 trace hash 有变化（S1），
    区分「子步骤完成」与「中途暂停等用户」（无新 trace -> none 静默放行，S6）。
    action：
    - "none"     ：无 sub_steps / 无新 trace / state 缺失 -> hook 放行 stop
    - "advanced" ：gate pass（含 gate=None 自动过），已推进 + last_judged 已记（S3）
    - "block"    ：gate 未过（attempts < SUB_STEP_BLOCK_ESCALATE），hook 应 _block_continue 同轮返工（S4）
    - "escalate" ：连续 block 达阈值，hook 应给用户裁决文案（S7）
    block/escalate 时 last_judged 同样更新（防同一 trace 重复判 -> 天然防 loop）。
    """
    none = ("none", "", {})
    state = load_state(project_root, name)
    if state is None:
        return none
    state = normalize_state(state)
    try:
        node = get_node(state["phase"], state["sub_index"])
    except KeyError:
        return none
    if not node.sub_steps:
        return none
    cur = state.get("sub_step_index", 1)
    step = sub_step_at(node, cur)
    if step is None:
        return none
    mk = (
        node.minor_key
    )  # 跨节点串号防御：trace 匹配限定本节点（见 _iter_trace_segments）
    sha = latest_trace_sha1(project_root, name, cur, mk)
    if sha is None:
        return none  # 无 trace：中途暂停（或 evidence 路径错位,症状 L）-> 静默放行
    key = f"{node_id(node.phase, node.sub)}#{cur}"
    judged = state.setdefault("last_judged_trace", {})
    if judged.get(key) == sha:
        # §corrupt-rework-detect：同 hash 但最新合法 trace 之后有 sub_step==N 的
        # 损坏写入（JSON 跨行/字面 \"）-> 不是「没写」，是「写了门控读不到」。
        # 静默放行会让模型以为返工完成、流程看似卡死（demo d59d05ea 子3）。
        # 判 block 给格式修复指引；计 attempts（连续损坏达阈值同样升级用户裁决，
        # 防无限返工环）。游标不动：模型修好后 sha 变化 -> 走正常判定。
        if not corrupt_trace_after_latest(project_root, name, cur, mk):
            return none  # 已判过同一产出（上轮 block 后模型未写新 trace）-> 放行防 loop
        state["node_attempts"] = state.get("node_attempts", 0) + 1
        state["updated_at"] = _now()
        save_state(project_root, name, state)
        action = (
            "escalate" if state["node_attempts"] >= SUB_STEP_BLOCK_ESCALATE else "block"
        )
        return action, _corrupt_trace_reason(cur), state
    judged[key] = sha  # 判前即记：pass/block 都防重判
    if step.gate is None:
        ok, reason = True, ""
    else:
        artifact = read_evidence_for_step(project_root, name, cur, mk)
        priors = prior_block_reasons(project_root, name, cur, mk)
        # v2.52：写侧机械校验覆盖面钉给 judge（勿重复判已过的形式要件）
        scope_items = list(getattr(step, "mech_checks", ()) or ())
        for _e in getattr(step, "extra_payload_keys", ()):
            _k, _spec = _e[0], _e[1]
            scope_items.append(_spec if isinstance(_spec, str) else f"{_k}前缀")
        mech_scope = "、".join(scope_items) or None
        ok, reason = run_judge(
            step.gate,
            f"{node.label} · 子步骤{cur}",
            "",
            artifact_content=artifact,
            prior_verdicts=priors,
            mech_scope=mech_scope,
        )
    if ok and cur == len(node.sub_steps):
        # 末步产物机械门（§8.3）：judge（或 gate=None 自动过）≠ 产物已落盘。
        # block 落进下方共用 block 路径（attempts++/block 裁决/escalate 阈值）。
        mech_block = gate_verdict_mech(
            node, project_root, name, _node_entered_at(state, node)
        )
        if mech_block is not None:
            ok, reason = False, mech_block
    if ok:
        # 先落盘（含 last_judged[key]）：末步路径 advance_state 从磁盘重 load，
        # 不落盘会丢判定游标 -> 下次 Stop 重判同一 trace。
        save_state(project_root, name, state)
        new_state = _advance_sub_step(
            project_root, name, state, node, cur, via="step-stop"
        )
        return "advanced", "", new_state
    state["node_attempts"] = state.get("node_attempts", 0) + 1
    write_sub_step_block_verdict(
        project_root,
        name,
        node,
        cur,
        reason or "judge 未给出原因",
        state["node_attempts"],
    )
    state["updated_at"] = _now()
    save_state(project_root, name, state)
    action = (
        "escalate" if state["node_attempts"] >= SUB_STEP_BLOCK_ESCALATE else "block"
    )
    return action, reason or "judge 未给出原因", state


# ---------- phase 写权限围栏（§substep-gate-at-stop S11）----------

# 各 phase 允许模型用结构化写工具（Edit/Write/MultiEdit/NotebookEdit）落盘的路径。
# 规则三类：basename 命中 / 路径含 designs 且 .md / 路径含 .claude/evidence。
# execute=None 表示不限制。真源对齐 phase-rules.md 各阶段「禁止」行。
_PHASE_WRITE_NAMES: dict[str, frozenset[str] | None] = {
    "understand": frozenset({"understand.md"}),
    "plan": frozenset({"plan.md", "understand.md"}),
    "execute": None,  # 不限制
    "review": frozenset({"review.md"}),
    # evolution 额外放行 .claude/(skills 更新) + memory/（沉淀），见 _phase_write_path_ok
    "evolution": frozenset({"evolution.md"}),
}

# 阶段产物规范位置（2026-07-28 用户决议）：主仓 .claude/<dir>/<name>.md，
# 与 evidence 同级同语义——worktree 归档删除时分支上产物一起丢，主仓
# .claude/ 才存活（可手动 git add 提交留存）。basename=<name>.md 不在
# _PHASE_WRITE_NAMES，靠本目录规则放行；限本阶段写（它阶段误写/覆盖仍 deny）。
_PHASE_ARTIFACT_DIRS: dict[str, str] = {
    "understand": "understands",
    "plan": "plans",
    "review": "reviews",
    "evolution": "evolutions",
}


def _phase_write_path_ok(phase: str, file_path: str) -> bool:
    """路径是否命中该 phase 的写白名单（§S11）。"""
    names = _PHASE_WRITE_NAMES.get(phase)
    if names is None:
        return True  # execute（或未配置）不限制
    p = Path(file_path)
    if p.name in names:
        return True
    parts = p.parts
    if "designs" in parts and p.suffix == ".md":
        return True  # H8 design 文档各阶段可起草/补
    if ".claude" in parts and "evidence" in parts:
        return True  # evidence 任何阶段可写（子步骤编排/裁决留痕）
    artifact_dir = _PHASE_ARTIFACT_DIRS.get(phase)
    if artifact_dir and ".claude" in parts and artifact_dir in parts:
        return True  # 本阶段产物目录（主仓 .claude/<dir>/<name>.md，归档存活）
    if phase == "evolution":
        if ".claude" in parts:
            return True  # 更新 skill（.claude/skills/）
        if "memory" in parts and p.suffix == ".md":
            return True  # 沉淀 memory（~/.claude/projects/*/memory/）
    return False


def phase_write_denial(project_root: Path, name: str, file_path: str) -> str | None:
    """phase-fence 判定：该 phase 写 file_path 是否被拒。被拒 -> 返回 deny 原因；否则 None。

    §substep-gate-at-stop S11：把「understand/plan 禁改源码、review 禁改实现」
    从文案约束变硬约束。无 state / execute / 白名单命中 -> None（放行）。
    本围栏是系统级硬约束（同 rubric，对用户黑盒），无开关——/dl fence 只管 S10。
    """
    state = load_state(project_root, name)
    if state is None:
        return None
    state = normalize_state(state)
    phase = state.get("phase", "understand")
    if _phase_write_path_ok(phase, file_path):
        return None
    names = _PHASE_WRITE_NAMES.get(phase) or frozenset()
    allow = "、".join(sorted(names)) if names else "（无）"
    artifact_dir = _PHASE_ARTIFACT_DIRS.get(phase)
    dir_hint = f"、.claude/{artifact_dir}/" if artifact_dir else ""
    return (
        f"当前阶段「{PHASE_LABELS.get(phase, phase)}」禁止写源码/实现"
        f"（phase-rules 硬约束）。可写：{allow}{dir_hint}、designs/*.md、.claude/evidence/。"
        f"被拒路径：{file_path}"
    )


def pending_unjudged_step(project_root: Path, name: str) -> int | None:
    """当前子步骤是否有「已写 trace 但未经门控判决」。有 -> 返回子步骤号；否则 None。

    §substep-gate-at-stop S10：PreToolUse 围栏（workflow_step_fence.py）的关闭条件。
    围栏与门控共用 last_judged_trace 游标——判完（pass/block 都记游标）即开。
    state.enforce_step_fence=False（/dl fence off）-> None（围栏停用，回文案约束）。
    """
    state = load_state(project_root, name)
    if state is None:
        return None
    state = normalize_state(state)
    if not state.get("enforce_step_fence", True):
        return None
    try:
        node = get_node(state["phase"], state["sub_index"])
    except KeyError:
        return None
    if not node.sub_steps:
        return None
    cur = state.get("sub_step_index", 1)
    if sub_step_at(node, cur) is None:
        return None
    sha = latest_trace_sha1(project_root, name, cur, node.minor_key)
    if sha is None:
        return None
    judged = state.get("last_judged_trace", {})
    if judged.get(f"{node_id(node.phase, node.sub)}#{cur}") == sha:
        return None
    return cur


def engagement_fence_state(project_root: Path, name: str) -> tuple[int, Step] | None:
    """当前子步骤处于「零 trace 窗口」-> 返回（子步骤号, Step）；否则 None。

    §step-engage-prefence S15：PreToolUse 前置参与围栏（workflow_step_fence.py）
    的触发判据——与 S13（Stop 参与围栏）同判据、单源在此。窗口内仅编排工具
    可用（常驻集 + Step.fence_allow），模型为「直接回答用户」发起的工具调用
    在第一次调用即被 deny 指回编排，不等回合末 S13 纠偏。
    与 pending_unjudged_step（S10）互斥互补：零 trace->S15 白名单；
    有未判决 trace->S10 全 deny；已判决->自由。
    state.enforce_step_fence=False（/dl fence off）-> None（围栏停用，回文案约束）。
    """
    state = load_state(project_root, name)
    if state is None:
        return None
    state = normalize_state(state)
    if not state.get("enforce_step_fence", True):
        return None
    try:
        node = get_node(state["phase"], state["sub_index"])
    except KeyError:
        return None
    if not node.sub_steps:
        return None
    cur = state.get("sub_step_index", 1)
    step = sub_step_at(node, cur)
    if step is None:
        return None
    if latest_trace_sha1(project_root, name, cur, node.minor_key) is not None:
        return None  # 有 trace（未判决/已判决）-> 归 S10/自由，非本围栏窗口
    return cur, step


# §step-selfcheck：提交前自查提示（pass 续轮与注入双通道共用，单源）。
# 动机（2026-07-26 demo 121320fe 复盘）：5 次真实 block 里 4 次违反的是已
# 逐字披露在 purpose 的形式要求——注意力失败非知识失败（被指后一轮修好）。
# 把「judge 抓」前移为「自查抓」：省 judge 调用 + 省一轮 Stop 返工往返。
STEP_SELFCHECK_HINT = (
    "STEP_DONE 前自查：逐条对照本步 purpose 的形式要件检查你的 trace——"
    "每项要求在 trace 里都须有对应记录（「我做了」式汇总声明不算），缺项先补再声明完成。"
)


def selfcheck_hint(step: Step | None) -> str:
    """提交前自查提示 = 通用段 + 按步声明的 checklist（Step.selfcheck）。

    §step-selfcheck 步级化（2026-07-26）：通用提示对弱遵从模型太抽象
    （demo d59d05ea：MiniMax-M3 子1 三连 block 全是已披露形式要件的注意力失败，
    被指后一轮即修好——§3.5 #9 注意力失败的最便宜解法是自查前移）。
    步级 checklist 只列 purpose 已披露的形式要件（Step.selfcheck 声明处已注释），
    质量判据仍只在 gate 黑盒（Goodhart 分层不破）。step=None/未声明 -> 仅通用段。
    三通道同文维持：注入（workflow_phase）+ pass 续轮 + block 返工（workflow_advance）
    都调本函数，单源在此。
    """
    if step is None or not step.selfcheck:
        return STEP_SELFCHECK_HINT
    return STEP_SELFCHECK_HINT + "\n本步自查：" + step.selfcheck


def engagement_fence_notice(step: Step) -> str:
    """S15 零 trace 窗口的围栏提示文本（含 Step.fence_allow 豁免行）。

    §autocontinue-fence-notice：单源——workflow_phase.py 注入
    （UserPromptSubmit）与 workflow_advance.py pass/block 续轮
    （Stop additionalContext）共用，防双通道文案漂移
    （demo 121320fe：模型只在子1 见过无豁免版提示，到子4 臆断 Agent
    被 deny，未试先放弃并在 evidence 编造「Agent blocked by S15 fence」）。
    纯格式化函数：入参 Step，不查 state。
    """
    extra = (
        f"；当前子步骤额外放行：{' / '.join(step.fence_allow)}"
        if step.fence_allow
        else ""
    )
    return (
        "🚧 前置参与围栏（S15，PreToolUse 硬约束）：当前子步骤写 evidence 前，"
        "仅编排工具可用（AskUserQuestion / Skill / Task* / Read / Bash 只读发现"
        "（find/ls/grep/cat/head/git log 等，禁写命令）/ "
        f"codegraph / dl-cmd / 写 evidence{extra}）；"
        "为用户任务做写操作或重型探查（WebFetch/WebSearch/Agent 等）会被 deny "
        "指回本步——「先回答用户问题再走编排」不存在，当前子步骤就是你要做的事。"
    )


def _strip_json_fence(text: str) -> str:
    """剥 ```json ... ``` 代码块围栏（冒烟实测 judge 倾向包代码块）。"""
    s = text.strip()
    if s.startswith("```"):
        # 去首行围栏（```json 或 ```）
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1 :]
        # 去尾围栏
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


def _extract_judge_result(result_text: str) -> dict[str, Any] | None:
    """从 claude -p 的 result 文本提取 {pass, reason}。

    judge 被要求只回 JSON。容错：剥代码块围栏 -> 取首个 {...} -> json.loads。
    失败返回 None（调用方降级为 block）。
    """
    s = _strip_json_fence(result_text)
    # 取首个 { 到末个 }（防模型前后带解释文本）
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = json.loads(s[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or "pass" not in obj:
        return None
    obj.setdefault("reason", "")
    return obj


# run_judge 最近一次调用的成本元数据（judge_* tokens/ms/cost；失败路径带 judge_error），
# 供 hook 写 .wf_advance.log 审计行（2026-07-26：judge 成本原完全黑盒，无法对账）。
# 只读方 = hook 进程（一次性子进程，无并发）；run_judge 每次调用开头 clear，
# 签名保持 (pass, reason) 不变——mock run_judge 的测试全部不受影响。
LAST_JUDGE_META: dict[str, Any] = {}


def _capture_judge_meta(last_json: dict[str, Any]) -> None:
    """从 claude -p --output-format json 的末行 JSON 采成本字段进 LAST_JUDGE_META。

    防御式取值：provider 包装器（ac-ark 等）可能缺字段，缺什么就不记什么。
    数值字段**累加**（非覆盖）：bad_verdict_json 重试时两次尝试的成本都要入账。
    """
    u = last_json.get("usage") or {}
    for k in (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ):
        if isinstance(u.get(k), int):
            key = f"judge_{k}"
            LAST_JUDGE_META[key] = LAST_JUDGE_META.get(key, 0) + u[k]
    for src, dst in (
        ("duration_ms", "judge_ms"),
        ("duration_api_ms", "judge_api_ms"),
        ("total_cost_usd", "judge_cost_usd"),
    ):
        if last_json.get(src) is not None:
            LAST_JUDGE_META[dst] = LAST_JUDGE_META.get(dst, 0) + last_json[src]


def run_judge(
    rubric: str,
    node_label: str,
    model_output: str,
    artifact_content: str | None = None,
    prior_verdicts: list[str] | None = None,
    mech_scope: str | None = None,
) -> tuple[bool, str]:
    """起 stateless claude -p 当评审 judge。返回 (pass, reason)。

    design §5.1：独立会话,不续主 session（防污染主上下文）。
    输入 = rubric（判据）+ 模型本轮输出 + 声明产物内容。
    输出 = {pass:bool, reason:str}（JSON 强约束）。
    judge 继承主会话 env（design §9 #2）：不另设 provider/model,跑在主会话已起的 provider 上。
    prior_verdicts（v2.26）：同一子步骤前轮 block 判词（时间序）。非空时 prompt
    附一致性指令——judge 每轮全新调用无记忆是裁量漂移的制度根源（tail_volume
    u:3 子4 同一 rubric 五轮五种解释），前轮判词=裁量先例。

    失败（API 错/超时/解析失败）-> (False, 失败原因)（design §5.1 降级：不默认放行）。
    例外一：**bad_verdict_json（判定 JSON 解析失败）重试一次**（2026-07-26 决议）——
    parse 失败多属 judge 输出格式抖动，直接降级会把 judge 本意的 pass 白烧一轮
    返工（demo 121320fe 子1 首次即 bad_verdict_json）；重试仍失败才降级 block。
    例外二：**TimeoutExpired 重试一次**（2026-07-26 决议）——当初「超时不重试」的
    理由是递归爆炸（症状 N），其根因（judge 继承 worktree cwd 触发 hooks）已被
    cwd=tempdir 修掉；而超时降级 block 会让模型误以为内容不合格、把无问题的
    trace 白重写一轮（demo fbdb6ebd 子2 实测），一次重试 ~3k tokens 远小于
    一轮模型返工。API 错/退出码非零/OSError 仍**不重试**（重试无意义的失败模式）。
    副作用：每次调用重置 LAST_JUDGE_META（成功=成本字段，失败=judge_error；
    重试时两次尝试成本累加 + judge_retried=1）供审计日志。
    """
    LAST_JUDGE_META.clear()
    prompt = (
        "你是工作流节点门控的评审 judge。判定模型本轮输出是否符合判据。\n"
        "严格判定：判据任一条不满足 -> pass=false 并在 reason 写缺什么。\n"
        "只回答一个 JSON,不要多余文本、不要调任何工具：\n"
        '{"pass": true/false, "reason": "不满足时写缺什么;满足时留空"}\n'
        # v2.36 判词瘦身（tail_volume_acceleration_annualized u:1 子4 审计）：
        # 判据自相矛盾/裁量留白时 judge 写论文式判词（单轮 output 5.5k-7.1k
        # tokens、102s，judge 占墙钟 21%）。判词消费者是返工的模型——精炼
        # 指路即可；范例要求仍在（④），长判词多为重复论证。上限按汉字计：
        # 300 字 ≈ 450-600 tokens，够「缺什么+条款+1 范例」。
        "reason 上限 300 字：block 时写「缺什么 + 判据条款 +（④适用时）1 个改写范例」，"
        "不重复论证、不逐条复述模型输出。\n\n"
        f"【节点】{node_label}\n"
        f"【判据】{rubric}\n"
        f"【模型本轮输出】\n{model_output}\n"
    )
    if artifact_content:
        prompt += f"\n【声明产物内容】\n{artifact_content}\n"
        # 返工是 append 协议（§substep-gate-at-stop S5）：同一 sub_step 会积累多条
        # skill-trace。不指认最新行，judge 可能拿返工前的旧行判 block（误报）。
        prompt += (
            "\n（产物内容中同一 sub_step 若有多条 skill-trace 记录，"
            "以最后一条为准；此前同号记录是返工历史，仅作参考。）"
        )
        # v2.34（att3 幻觉防线，tail_volume plan:1 子5 审计）：judge 曾判
        # 「缺 trace 记录/无法证明已写入」——engine 是先拿到 trace hash 才调
        # judge 的，记录存在是机械已知事实，该判词可证伪为假；att3 三连 block
        # 直接被逼进升级裁决。钉死出处语义：存在性勿再判。
        prompt += (
            "\n（产物内容直接摘自 evidence 落库记录——记录存在性已由机械层"
            "校验：不存在则不会调你评审；勿判「记录缺失/无法证明已写入」，"
            "只判内容是否满足判据。）"
        )
    if prior_verdicts:
        prompt += "\n【前轮判词（同一子步骤，时间序）】\n" + "\n".join(
            f"{i}. {r}" for i, r in enumerate(prior_verdicts, 1)
        )
        prompt += (
            "\n一致性要求（判据未变，前轮判词=裁量先例）："
            "①前轮点名的问题已修复的方向，不得翻案判回——前轮判词描述的违规"
            "写法在本轮产物中已不存在的=已修复；判 block 引用的违规内容须是"
            "本轮产物中的原文短语（逐字引用或可定位片段），引不出原文的条目"
            "不得作为 block 依据（判本轮产物实况，不判前轮判词的描述）；"
            "②前轮 trace 中已存在且未被判违规的写法，不得仅因裁量收紧而新判违规；"
            "③本轮判 block 须在 reason 引用判据的具体条款；"
            "④判 block 时 reason 还须附 1 个正确改写范例——把被判内容的一条"
            "改成合规形式（指模式不指实例位置，模型下轮照模式修，不打地鼠）。"
        )
    if mech_scope:
        # v2.52（「已修还判」第二实例，8/2 晚 u:1 子1 att2）：judge 无视
        # rubric 内嵌的「已机械校验」句，照前轮判词描述 block 已修形态——
        # 提为独立钉句（v2.34 存在性钉死同范式）：机械层已过的形式要件
        # 不是 judge 的判面。双侧钉（重放逮住初版过度抑制：scope 含
        # 「结论前缀」被 judge 泛化成「结论全免判」，结论无出处推断被
        # 放过 PASS）——枚举项勿重复判，非枚举项照判不误。
        prompt += (
            f"\n（本载荷提交时已通过 append-trace 写侧机械校验：{mech_scope}"
            "——仅限上述枚举项覆盖的形式要件（词形/存在性/对齐/标注通道/"
            "前缀）勿重复判、勿以之为 block 依据；判据中的其它一切（含结论"
            "与答案的内容质量、出处真实性、非枚举项的形式要件）仍是你的"
            "判面，照判不误。）"
        )
    prompt += "\n只回上面的 JSON。"

    for attempt in range(2):
        # 重试时：bad_verdict_json 加格式提醒后缀（判决载荷逐字不动，只追加输出
        # 格式强调）；TimeoutExpired 原样重发（输出格式没问题，是时延抖动）。
        p = prompt + (
            "\n\n提醒：上次你的回答不是合法 JSON。只回一个 JSON 对象，不要任何其它文本。"
            if attempt and LAST_JUDGE_META.get("judge_error") == "bad_verdict_json"
            else ""
        )
        ok, reason, retryable = _run_judge_once(p)
        if not retryable:
            return ok, reason
        LAST_JUDGE_META["judge_retried"] = 1
    return ok, reason  # 重试仍失败 -> 降级 block


def _run_judge_once(prompt: str) -> tuple[bool, str, bool]:
    """run_judge 单次尝试。返回 (pass, reason, retryable)。

    retryable=True 仅两种值得重试的失败模式：
    - bad_verdict_json（判定 JSON 解析失败——输出格式抖动）；
    - TimeoutExpired（时延抖动——递归爆炸根因已被 cwd=tempdir 修掉，
      重试代价远小于超时误判 block 引发的模型返工，见 run_judge docstring）。
    其余失败（API 错/exit 非零/no_result_json/is_error/OSError）
    一律 False，调用方直接降级。
    """
    try:
        # v2.44：judge 子进程禁思考链（MAX_THINKING_TOKENS=0）。实证
        # （2026-08-02 tail_volume u:1）：judge 两次离群 115s/99s、输出
        # 10.8k/11.4k tok 而可见判词仅数百字——推理模型 judge 的 thinking
        # 占输出 ~92%。MiniMax-M3 同一真实载荷 A/B：3529 tok/39.2s ->
        # 278 tok/6.3s（-92%/-84%），判决方向一致。judge 任务是按判据
        # 比对，非开放推理，思考链成本不成比例。只覆盖 judge 子进程 env，
        # 主会话与 provider/认证链不动（K3 端点忽略该 var，无副作用）。
        env = dict(os.environ)
        env["MAX_THINKING_TOKENS"] = "0"
        res = subprocess.run(
            # --tools ""：judge 明确不调工具，裁掉全套工具 schema（harness 开销大头）。
            # --system-prompt：judge 人设替换 coding 助手人设，减人设冲突干扰。
            # 两者都是命令行 flag：settings.json 加载链不动,认证（env 继承或
            # settings env 块）在任何机器上照常。
            [
                "claude",
                "-p",
                "--output-format",
                "json",
                "--tools",
                "",
                "--system-prompt",
                JUDGE_SYSTEM_PROMPT,
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=JUDGE_TIMEOUT,
            # judge 会话必须落在非 git 目录：继承 worktree cwd 时，judge 会话自身的
            # UserPromptSubmit/Stop 会触发 workflow hooks（用户级注册）-> 递归门控
            # （judge 的 Stop 又生 judge，2026-07-25 demo 实测链式爆炸 + 全员超时）。
            # 非 git 目录下 hooks 反查不到项目根，自然静默退出。
            cwd=tempfile.gettempdir(),
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        LAST_JUDGE_META["judge_error"] = type(e).__name__
        return False, f"judge 调用失败（{type(e).__name__}）", True  # 重试一次
    except OSError as e:
        LAST_JUDGE_META["judge_error"] = type(e).__name__
        return False, f"judge 调用失败（{type(e).__name__}）", False
    if res.returncode != 0:
        LAST_JUDGE_META["judge_error"] = f"exit={res.returncode}"
        return False, f"judge claude -p 退出码 {res.returncode}", False

    # claude -p --output-format json：stdout 末尾一行是 {"is_error":...,"result":"..."}
    # （冒烟实测：ac-ark 包装器在前面混入调试日志,但 result JSON 在最后一行）。
    last_json = None
    for line in reversed(res.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and '"result"' in line:
            try:
                last_json = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if last_json is None:
        LAST_JUDGE_META["judge_error"] = "no_result_json"
        return False, "judge 输出无 result JSON 行", False
    # last_json 存在起：先采成本（is_error/判定解析失败的路径也有 usage 可对账）
    _capture_judge_meta(last_json)
    if last_json.get("is_error"):
        LAST_JUDGE_META["judge_error"] = "is_error"
        return False, f"judge 会话出错：{last_json.get('result', '')[:200]}", False

    result_text = last_json.get("result", "")
    verdict = _extract_judge_result(result_text)
    if verdict is None:
        LAST_JUDGE_META["judge_error"] = "bad_verdict_json"
        return False, f"judge 返回非合法 JSON 判定：{result_text[:200]}", True
    # 重试后成功：清掉首次失败留下的 judge_error（避免审计日志误判本次为失败）
    LAST_JUDGE_META.pop("judge_error", None)
    return bool(verdict["pass"]), str(verdict.get("reason", "")), False


def run_gate(
    node: Node,
    model_output: str,
    project_root: Path | None = None,
    artifact_content: str | None = None,
    name: str | None = None,
    not_before: float | None = None,
) -> tuple[bool, str]:
    """compound gate（机械 + 语义,短路）。返回 (pass, block_reason)。

    design §5：机械不过短路 block（不跑 judge）;机械过跑 judge。
    无 gate_rubric 的节点（如 understand 子阶段 1-3）只过机械项。
    机械门（§8.3 产物检查）需 name 定位 <name>.md；缺 name/project_root 降级放行
    （宁纵勿枉）-> 靠 judge 兜底。
    """
    # 1. 机械项（短路）
    mech_block = gate_verdict_mech(node, project_root, name, not_before)
    if mech_block is not None:
        return False, mech_block
    # 2. 语义项（judge）。无 rubric -> 直接过（子阶段间自动推进）。
    if not node.gate_rubric:
        return True, ""
    ok, reason = run_judge(node.gate_rubric, node.label, model_output, artifact_content)
    if not ok:
        return False, reason or "judge 未给出原因"
    return True, ""


# ---------- phase-rules 渲染（P1 双通道单源，designs/harness-prompt-optimization-design.md）----------
#
# phase-rules.md 是模板：子步骤 bullet 段用 BEGIN/END GENERATED 标记占位，
# dl-launch.sh 每次启动调 `render-phase-rules` 渲染到 per-wf 目录（渲染失败中止启动，
# fail loud）。purpose 唯一真源 = engine Step.purpose——消灭 engine/phase-rules
# 两份手维护异文（症状 M/F 的「两通道措辞漂移」病根）。


_GENERATED_RE = re.compile(
    r"<!-- BEGIN GENERATED sub_steps (\S+?) -->.*?<!-- END GENERATED sub_steps \1 -->",
    re.DOTALL,
)


def render_substeps_section(nid: str) -> str:
    """渲染节点 sub_steps 的 phase-rules 段落（含 BEGIN/END 标记行，幂等可重渲染）。

    每步一行：`- **子步骤N = <ref>**：<purpose 全文>`（gate=None 标「自动过」）。
    节点无 sub_steps / 节点不存在 -> 报错暴露（no silent fallback）。
    """
    phase, sep, sub_s = nid.partition(":")
    if not sep or not sub_s.isdigit():
        raise ValueError(
            f"GENERATED 标记的节点 id 非法：{nid!r}（应形如 understand:1）"
        )
    node = get_node(phase, int(sub_s))
    if not node.sub_steps:
        raise ValueError(f"节点 {nid} 无 sub_steps，无可渲染段落")
    lines = [f"<!-- BEGIN GENERATED sub_steps {nid} -->"]
    for i, stp in enumerate(node.sub_steps, 1):
        gate_tag = "" if stp.gate else "（自动过）"
        lines.append(f"     - **子步骤{i} = {stp.ref}**{gate_tag}：{stp.purpose}")
    lines.append(f"<!-- END GENERATED sub_steps {nid} -->")
    return "\n".join(lines)


def render_phase_rules(template_text: str) -> str:
    """把模板里所有 GENERATED sub_steps 标记段替换为 engine 渲染产物。

    无标记段 -> 原样返回（向后兼容）；标记的节点 id 非法 -> 抛错（调用方 fail loud）。
    两阶段：先 GENERATED 块，后 artifact_sections 内联 token（互不感知）。
    """
    rendered = _GENERATED_RE.sub(
        lambda m: render_substeps_section(m.group(1)), template_text
    )
    return _ARTIFACT_TOKEN_RE.sub(_render_artifact_token, rendered)


# ---------- 产物节名内联 token（2026-08-02，artifact-handoff-hardening-design）----------
#
# 模板装配行/消费指令里的节名用 {{artifact_sections:<basename>[#<idx>]}} 占位，
# 渲染时从 ARTIFACT_SECTIONS 单源替换——节标题三通道（engine 门/phase-rules/注入）
# 同改同归，消灭「注入与装配 spec 措辞不一」类漂移（CONTAINS 扩面的前置）。
_ARTIFACT_TOKEN_RE = re.compile(r"\{\{artifact_sections:([\w.-]+?)(?:#(\d+))?\}\}")


def _render_artifact_token(m: re.Match) -> str:
    """{{artifact_sections:<basename>[#<idx>]}} -> 全节「 + 」连接 或 单节名。

    产物名/索引非法 -> 抛错（调用方 fail loud，与 GENERATED 渲染同纪律）。
    """
    basename, idx_s = m.group(1), m.group(2)
    sections = ARTIFACT_SECTIONS.get(basename)
    if sections is None:
        raise ValueError(f"artifact_sections token 产物名未知：{basename!r}")
    if idx_s is not None:
        idx = int(idx_s)
        if idx >= len(sections):
            raise ValueError(
                f"artifact_sections token 索引越界：{basename}#{idx}"
                f"（共 {len(sections)} 节）"
            )
        return sections[idx]
    return " + ".join(sections)


# ---------- 机械化记录写入（「AI 定写什么，脚本定怎么写」，2026-07-26）----------
#
# 原则：内容的正确值无法从 state 推导（问了什么/答了什么）-> 归 AI；
# 结构字段/格式/路径的正确值都能从 state+engine 推导 -> 归脚本。
# append-trace 根治手写 JSONL 的 5 类事故（症状 P/L：相对路径/覆盖写/合并行/
# 写碎/结构字段抄错）；redteam-prompt 根治现场拼红队 prompt 的 4 类事故
# （嵌套 spawn/无清单盲查/乱试工具/角色错乱）。

# 载荷里禁止出现的结构字段（由 append_trace 从 state 推导填充）。
_TRACE_STRUCT_FIELDS = ("kind", "major_stage", "minor_stage", "sub_step", "skill")

# ---------- v2.27 statements 结构化载荷 + 机械预检 ----------
#
# 弱模型优先原则：判据的词形部分下沉机械层——judge 每轮 ~13k in + 天然方差，
# 正则能判的不该花 judge 调用还判不稳（tail_volume u:3 子4 审计）。
# ①方案名词扫描：实现侧名词真值在仓内（codegraph 符号表 + git 文件名），
#   text 命中即拒并指路挪 boundary（judge 前的预检，judge 仍兜底语义）；
# ②源步 ID 传导覆盖核对：逐项原子化传导=集合覆盖问题（u:3 子4 judge #1 的活）。

# 匹配边界用 ASCII 标识符边界：CJK 字符在 re.UNICODE 下是 \w，\b 在 CJK-Latin
# 交界不可靠（「的LayerConfigBase」用 \b 会误判有边界）。
_NOUN_L = r"(?<![A-Za-z0-9_])"
_NOUN_R = r"(?![A-Za-z0-9_])"

# 规范文档引用合法（硬规则约束的验证源=Read 规范文档原文），不算实现侧名词。
_NOUN_SKIP_EXTS = (".md", ".rst", ".txt")

# 条目编号模式：in[1]/in[1a-强正]/out[A]（范围项）、C1.1/SC4.1/H1.1（约束/标准/
# 硬规则项）、RC-A（红队反例）、#1a/#1b1（候选/陈述项）、U1/T1（任务/目标项）。
# v2.33 扩面（tail_volume plan:1 实测）：旧模式只认 in[]/单字母 X1.1，RC-A、
# T1、SC4.1、#1a 全部漏捕——plan 域节点的 ID 传导核对静默空转。
# ASCII 边界用否定环视（CJK 在 re.UNICODE 下是 \w，\b 在 CJK-Latin 交界不可靠，
# 同 _NOUN_L/_NOUN_R 先例）。
_ID_RE = re.compile(
    r"[A-Za-z]+\[[\w-]+\]"  # in[1]/out[A]
    r"|[A-Z]{1,3}\d+\.\d+"  # C1.1/SC4.1/H1.1
    r"|RC-[A-Z]"  # RC-A 红队反例
    r"|#[0-9]+[a-z]?\d*"  # #1a/#2/#1b1 候选与陈述项
    r"|(?<![A-Za-z0-9_])[UT]\d+(?![A-Za-z0-9_])"  # U1 任务/T1 目标
)


def _implementation_nouns(project_root: Path) -> set[str]:
    """仓内实现侧名词真值集（方案名词扫描用）：codegraph 符号 + git 文件名。

    只收强信号，保精度：①codegraph db 的 class/function/method 名——≥4 字符
    且含大写或下划线（snake_case/CamelCase 标识符不会出现在自然散文）；
    ②git ls-files 的带扩展名文件名（_macros.html/paths.py 进散文即实现引用；
    规范文档扩展名除外）。任一源缺失/失败 -> 跳过该源（预检是 judge 前的
    增强层不是必需行为，judge 仍兜底——降级不算 silent fallback）。
    """
    nouns: set[str] = set()
    db = project_root / ".codegraph" / "codegraph.db"
    if db.exists():
        try:
            import sqlite3

            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                for (n,) in con.execute(
                    "SELECT DISTINCT name FROM nodes"
                    " WHERE kind IN ('class','function','method')"
                ):
                    if (
                        isinstance(n, str)
                        and len(n) >= 4
                        and (any(c.isupper() for c in n) or "_" in n)
                    ):
                        nouns.add(n)
            finally:
                con.close()
        except (sqlite3.Error, OSError):
            pass
    try:
        res = subprocess.run(
            ["git", "ls-files"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode == 0:
            for f in res.stdout.splitlines():
                base = f.rsplit("/", 1)[-1]
                if (
                    "." in base
                    and not base.startswith(".")
                    and not base.endswith(_NOUN_SKIP_EXTS)
                ):
                    nouns.add(base)
    except (subprocess.TimeoutExpired, OSError):
        pass
    return nouns


def _step_trace_ids(
    project_root: Path, name: str, sub_step: int, minor_key: str | None
) -> set[str]:
    """取某子步骤最新 trace 文本里的条目编号集（ID 传导覆盖核对的源侧）。"""
    text = read_evidence(project_root, name)
    if not text:
        return set()
    latest = None
    for _, rec in _iter_trace_segments(text, sub_step, minor_key):
        latest = rec
    if latest is None:
        return set()
    parts = [str(latest.get("purpose") or "")]
    for v in latest.get("q") or []:
        parts.append(str(v))
    for v in latest.get("a") or []:
        parts.append(str(v))
    for item in latest.get("statements") or []:
        if isinstance(item, dict):
            parts.extend(
                str(item.get(k) or "") for k in ("text", "type_label", "boundary")
            )
            flds = item.get("fields")
            if isinstance(flds, dict):
                parts.extend(str(v) for v in flds.values())
    return set(_ID_RE.findall(" ".join(parts)))


def _source_step_index(step, cur: int) -> int | None:
    """传导源步号：step.input 声明（"step3.xxx"）优先，缺省上一步。"""
    m = re.search(r"step(\d+)", step.input or "")
    if m:
        return int(m.group(1))
    return cur - 1 if cur > 1 else None


def payload_format_hint(step) -> list[str]:
    """注入用载荷格式说明行（按步 record_format；单源，phase hook 直接渲染）。

    v2.58：载荷格式从 JSON 换成分节标记文本——模型零接触 JSON（Edit 填
    JSON 会被内容里的 ASCII 引号弄崩；四桶分工「脚本管格式」的正治）。
    """
    head = [
        "   载荷 = 分节标记文本（.md，零转义——内容随便带引号/换行/代码，"
        "格式全归脚本）：",
        "   走 `--scaffold` 生成骨架（禁手写 Write 载荷文件——围栏 deny；"
        "标头格式脚本管）→ Edit 把每个「待填」换成内容 → append-trace "
        "--from-file <骨架路径>",
    ]
    if getattr(step, "record_format", "qa") == "statements":
        req = getattr(step, "statement_fields", ()) or ()
        fields_seg = "".join(f"【fields.{k}】" for k in req)
        fields_note = (
            "；fields 逐键非空（" + "/".join(req) + "）——缺键 append-trace 当场拒"
            if req
            else ""
        )
        return head + [
            "   【purpose】<该步目的> →【statements】→ 逐项 "
            f"【text】<单句陈述>【type_label】<类型标签>【boundary】<边界/实现指针>{fields_seg}"
            "（text 只许 outcome-level——实现侧名词/file:line 只能进 boundary，"
            "text 会被机械扫描打回" + fields_note + "）",
            "   ✗ 反例（必拒）：text 含文件名/类名（挪 boundary）；"
            "或残留「待填」占位符（漏填当场拒）",
        ]
    extra = getattr(step, "extra_payload_keys", ()) if step is not None else ()
    seen = []
    for e in extra:
        if e[0] not in seen:
            seen.append(e[0])
    extra_seg = "".join(f" →【{k}】" for k in seen)
    extra_note = (
        "；"
        + "/".join(seen)
        + " 键 append-trace 机械校验存在性与格式，缺键/格式错当场拒"
        if extra
        else ""
    ) + "（逐项结构见本步 purpose）"
    return head + [
        "   【purpose】<该步目的> →【qa】→ 逐项【q】<问题>【a】<答案>"
        + extra_seg
        + extra_note,
        "   ✗ 反例（必 block）：【a】写「已理解」式汇总声明（非记录）；"
        "或残留「待填」占位符（漏填当场拒）",
    ]


# ---------- v2.37 写侧机械层扩面（u:1 一次通过率三连修）----------
#
# 动机（2026-08-01 tail_volume u:1 审计）：v2.36 判据钉死保 judge 判得对，
# 不保模型一次写对——钉死后 relaunch 子2 仍同症两连 block。每次 block ≈
# 全上下文重读 2-3 轮 + judge 调用，词形/结构形式要件继续下沉写侧机械层。
_PLACEHOLDER_MARKERS = (
    "进行中",
    "待补",
    "待填",
    "待追加",
    "待收录",
    "稍后补",
    "TODO",
    "TBD",
)


def _placeholder_hit(payload: dict) -> tuple[str, str] | None:
    """占位符全局扫描：trace 是完成记录，占位标记出现在任何内容字段即拒。

    动机 = tail_volume u:1 子4 att1：红队子代理未归就先 append，purpose 写
    「进行中：…红队到达后追加」白烧一轮 judge。扫描面 = purpose + 载荷全部
    字符串值（qa/statements/extra 键通用，零 per-step 接线）；FP 面已验证
    （当晚 17 条 trace 仅真违规者命中，demo.jsonl 零命中）。
    返回 (标记, 位置) 或 None。
    """

    def _walk(v, path):
        if isinstance(v, str):
            for m in _PLACEHOLDER_MARKERS:
                if m in v:
                    return (m, path)
        elif isinstance(v, list):
            for i, it in enumerate(v):
                r = _walk(it, f"{path}[{i}]")
                if r:
                    return r
        elif isinstance(v, dict):
            for k, it in v.items():
                r = _walk(it, f"{path}.{k}" if path else str(k))
                if r:
                    return r
        return None

    return _walk(payload, "")


# 「可能」扫描排除「不可能」（否定式是合法断言）。
_MAYBE_RE = re.compile(r"(?<!不)可能")

# v2.49 词形扩面（全部取自 tail_volume_acceleration_annualized u:1 子2 三轮真实
# 被 block 载荷逐字字面，重放分隔度见 TestCausalRingNoUntested）：
# att1 待办形态桥接「需 pyarrow…sort 看 top10」「需 Read 验证」——
# 否定/限定式（无需/所需/必需/按需）是合法断言，排除。
_NEED_ACTION_RE = re.compile(
    r"(?<![无所必按])需[^，。；]{0,40}(?:验证|核实|确认|取证|看|Read|grep|sort)"
)
# att3 假设形态链环「若 convert 函数…未做截断/钳制则异常值…传到上层」。
_IF_THEN_RE = re.compile(r"若[^，。；]{0,40}则")
# att2 行号跨度充精确指针「:565-771」（206 行）；规则正例/通过载荷跨度 ≤17，
# 阈值 50 双侧 margin 均宽（钉死进 _CAUSAL_CHAIN_EVIDENCE_RULE，非调参）。
_WIDE_SPAN_RE = re.compile(r":(\d+)-(\d+)")
_WIDE_SPAN_LIMIT = 50
# att3 竞争假设「排除」句推断词形（保留句豁免——标「待子3取证」是合法出口，
# 与 _CAUSAL_CHAIN_EVIDENCE_RULE 排除/保留拆分一一对应）。
_EXCLUDE_INFERENCE_RE = re.compile(r"未实测|待实测|未验证|待验证|推测|(?<!不)可能")

# v2.50 占环位词形（2026-08-02 u:1 子2 三连 block att1 逐字：Why4「…待子3
# 取证」、Why5「…降格进竞争假设待子3验证」整环无指针）——「待子3取证/降格」
# 声明独占环位=未降格（规则反例早已双侧钉死，词形本轮首现，按逐字纪律补下沉）。
# 环段锚 WhyN 带冒号：自查/元描述项的「Why1-Why4」式环引用不切段，合法汇报
# 降格去向不误扫（att3 自查项零 FP）；段内带 :\d+ 指针的尾部降格去向声明
# 合法（att3 B Why5 形态 judge 已接受）——占环位的操作化=环内无实测指针。
_RING_START_RE = re.compile(r"Why\d+[:：]")
_DEMOTE_RING_RE = re.compile(r"待子\s*3\s*(?:取证|验证)|(?<![不未无])降格")

# v2.55 全局否定断言扫描（2026-08-02 tail_volume_acceleration_annualized
# u:1 子2 att2 block 实证）：Why4「没有显式契约约定…」「无 unit test 钉住…」
# 「根因是层契约缺失」——模型把「读了文件没看到 X」当读出事实，实则
# 跨文件存在性命题（全局否定断言）=「读出后推出」同族：读出的是「有什么」，
# 不是「没有什么」。词形取 att1/att2 逐字（两 att 同一 Why4 文本）；豁免口与
# 合法出口一一对应（§3.5 #21③）：全域扫描零命中留痕（grep/扫描/零命中）
# 与尾部降格去向声明（v2.50 钉的合法形态）不拦。局部可读否定（「未做 X」
# 有该行原文背书）不在词表——v2.50 正例「未做单位判断（:69 原文…）」是
# 合法环，贪宽=FP。
_ABSENCE_CLAIM_RE = re.compile(r"没有显式|无显式|无\s*[Uu]nit\s*test|无单测|契约缺失")
_ABSENCE_EXEMPT_RE = re.compile(r"grep|扫描|零命中|无命中")
_ABSENCE_DEMOTE_RE = re.compile(r"降格|待子\s*3\s*取证|竞争假设")
_EVIDENCE_POINTER_RE = re.compile(r":\d+")


def _check_causal_ring_no_untested(qa: list, *_ctx) -> str | None:
    """causal_ring_no_untested：因果链环禁词扫描（u:1 子2 专属，nodes 声明）。

    主链环只许实测事实；「未实测」类状态标签与「可能」类推断词不是出处——
    词形来自真实违规字面（att1 Why4「可能剩 1-5 天」/ att2 Why5「未实测/推断」，
    att3 通过版零命中）。
    链识别（v2.46 放宽，不锚定 q 标题）：q 含「因果链」**或** a 含链式结构
    标记（Why/→）。旧实现只认标题——2026-08-02 实例模型用「Q4=…」式标题、
    链写进 a，标题锚定空转，「可能」漏到 judge 115s/10.8k tok 才拦
    （弱模型优先复盘：该机械判的东西漏给 judge = 扫描面锚错形状）。
    「假设」标题项收窄豁免（v2.49）：只豁免「保留」句（标「待子3取证」合法）；
    「排除」句=断言假设为假，排除理由含推断词形（未实测/推测/可能…）当场拒——
    旧实现整项豁免，att3「排除（…未实测…推测：…不成立）」漏到 judge
    第三轮才拦。「不可能」不命中（否定式是合法断言）。
    分隔度：8/2 真实被 block 载荷（Q1 未实测/Q4 可能）BLOCK、真实通过载荷
    与 demo 载荷 PASS；v2.49 扩面信号（需…验证/若…则/行号跨度/排除句推断）
    同口径重放（3 条被 block 载荷逐字 BLOCK、通过载荷零 FP）。
    v2.50 占环位扫描（WhyN: 环段级「待子3取证/降格」+ 全段无「:行号」指针）：
    同日三连 block att1 逐字 BLOCK、att3 尾部去向声明形态与自查项零 FP。
    v2.55 全局否定断言扫描（同日第三 episode att1/att2「没有显式契约/无 unit
    test/契约缺失」当主链根因）：项级扫描不锚 WhyN 分段（真实载荷 Why1=/
    Why4（根因层）= 形态分段全空转——锚内容结构不锚措辞）；豁免=全域扫描
    零命中留痕/降格去向声明。重放：两条真实被 block 载荷 REJECT、demo 通过
    载荷零 FP、降格去向/grep 留痕两合法形态 PASS。
    """
    banned = ("未实测", "待实测", "未验证", "待验证")
    for item in qa:
        q, a = str(item.get("q", "")), str(item.get("a", ""))
        if "假设" in q:
            for sent in re.split(r"[。；]", a):
                if "排除" not in sent:
                    continue
                m = _EXCLUDE_INFERENCE_RE.search(sent)
                if m:
                    return (
                        f"竞争假设「排除」理由含推断词形「{m.group(0)}」"
                        f"（{sent[:30]}…）——排除=断言假设为假，须证据指针"
                        "（file:line/读出事实）；证据不足时改标「保留」+"
                        "「待子3取证」，不推测排除"
                    )
            continue
        if "因果链" not in q and "Why" not in a and "→" not in a:
            continue
        hit = next((b for b in banned if b in a), None)
        if hit is None and _MAYBE_RE.search(a):
            hit = "可能"
        if hit is None:
            m = _NEED_ACTION_RE.search(a)
            if m:
                hit = m.group(0)
        if hit is None:
            m = _IF_THEN_RE.search(a)
            if m:
                hit = f"若…则（{m.group(0)[:24]}…）"
        if hit:
            return (
                f"因果链环含「{hit}」（{q[:20]}…）——主链环只许实测事实"
                "（file:line/数据值/日志原文/用户原话）；推断量级/未测状态/"
                "待办桥接/假设形态不是出处："
                "挖不动的深层整体降格进竞争假设分支并标「待子3取证」，"
                "主链挖到实测层即终止，不悬空、不贴标签充数"
            )
        for m in _WIDE_SPAN_RE.finditer(a):
            if int(m.group(2)) - int(m.group(1)) >= _WIDE_SPAN_LIMIT:
                return (
                    f"因果链环行号指针 {m.group(0)} 跨 "
                    f"{int(m.group(2)) - int(m.group(1))} 行（{q[:20]}…）——"
                    f"跨度 ≥{_WIDE_SPAN_LIMIT} 行不算精确指针："
                    "收窄到具体语句行（定义/赋值/调用行），并附该行原文"
                )
        # v2.50 占环位扫描：WhyN: 环段内含「待子3取证/降格」且全段无 :\d+
        # 实测指针 = 声明独占环位（规则反例「Why5=…降格至竞争假设分支」）
        # v2.55 全局否定断言扫描（项级，不锚 WhyN 分段——真实载荷 Why1=/
        # Why4（根因层）= 形态 ring 分段全空转，§3.5 #21「锚内容结构不锚
        # 措辞」）：跨文件存在性命题（无显式契约/无 unit test/契约缺失）
        # 不是读出事实——读出的是「有什么」不是「没有什么」。豁免口与合法
        # 出口一一对应：a 内有全域扫描零命中留痕（grep/扫描/零命中）全豁免；
        # 命中后 16 字符内接降格去向声明（v2.50 合法尾部形态）跳过该命中。
        # 局部可读否定（「未做 X」+该行原文背书）不在词表——贪宽=FP。
        if not _ABSENCE_EXEMPT_RE.search(a):
            for am in _ABSENCE_CLAIM_RE.finditer(a):
                if _ABSENCE_DEMOTE_RE.search(a, am.end(), am.end() + 16):
                    continue
                return (
                    f"因果链环含全局否定断言「{am.group(0)}」（{q[:20]}…）——"
                    "「没有/缺失 X」是跨文件存在性命题=推断不是读出事实："
                    "合法出处只有全域扫描零命中留痕（grep -rn 命令原文+零命中"
                    "结果）；否则主链终止于可直接读证的环，「没有 X」降格进"
                    "竞争假设分支标「待子3取证」"
                )
        ring_starts = list(_RING_START_RE.finditer(a))
        for i, m in enumerate(ring_starts):
            end = ring_starts[i + 1].start() if i + 1 < len(ring_starts) else len(a)
            seg = a[m.end() : end]
            dm = _DEMOTE_RING_RE.search(seg)
            if dm and not _EVIDENCE_POINTER_RE.search(seg):
                return (
                    f"因果链环以「{dm.group(0)}」占环位（{q[:20]}…，该环无 "
                    "file:line 指针）——「待子3取证/降格」声明独占环位=未降格："
                    "把该环从主链移除、改写进竞争假设分支（「待子3取证」的合法"
                    "位置在那里），主链挖到实测层（环内带 file:line 指针）即终止"
                )
    return None


def _check_value_no_unsourced_inference(qa: list, *_ctx) -> str | None:
    """value_no_unsourced_inference：价值/结论项推断词形扫描（u:2 子1 专属）。

    动机（2026-08-02 tail_volume_acceleration_annualized u:2 子1 att1）：
    形式要件（_G2_STEP1_FORM_REQUIREMENTS「结论逐句须有出处」）双侧披露后
    模型仍把「长期使用意味着会基于显示值做决策」「隐含价值」写进 V1/V2，
    且自声明「无推断补全」——自声明不可信（v2.37 教训：披露保 judge 判对
    不保模型写对），词形下沉写侧机械层。
    词形来自真实违规字面：隐含 / 意味着 / 可能（排除「不可能」否定式）。
    「推测」标注项豁免：标「推测」另列是形式要件内的合法出口（att2 通过版
    V2* 即此形态）。
    分隔度：att1 被 block 载荷（V1 隐含 / V2 意味着）BLOCK、att2 通过载荷
    PASS（推测豁免+干净项），重放回归见 TestValueNoUnsourcedInference。
    """
    for item in qa:
        q, a = str(item.get("q", "")), str(item.get("a", ""))
        if "价值" not in q and "结论" not in q:
            continue
        if "推测" in a:
            continue
        hit = next((m for m in ("隐含", "意味着") if m in a), None)
        if hit is None and _MAYBE_RE.search(a):
            hit = "可能"
        if hit:
            return (
                f"「{q[:16]}…」含推断词形「{hit}」——价值/结论只许用户原话或"
                "会话事实的直接引用（「X 意味着 Y」「隐含 Z」=读出后推出，不是事实）；"
                "推断须标「推测」另列，不纳入结论"
            )
    return None


def _load_atomic_questions(project_root: Path, name: str) -> list | None:
    """读子2 最新 trace 的 atomic_questions 分档清单（v2.40）。

    子2 载荷顶层 atomic_questions 键并入 record 顶层（append-trace 校验后
    落库），本函数从 evidence JSONL 直接取最新一条子2 trace 的该键——
    fetch_prompt 分档与 fetch_report_recorded tier-aware 核验共用。
    无文件 / 无子2 trace / 旧形态 trace 无该键（v2.40 前实例）-> None
    （调用方按 legacy 行为处理，不算 silent fallback：旧实例本就没有分档）。
    """
    text = read_evidence(project_root, name)
    if not text:
        return None
    pc_minor = _NODES["understand:1"].minor_key
    found = None
    for _seg, rec in _iter_trace_segments(text, 2, pc_minor):
        aq = rec.get("atomic_questions")
        if isinstance(aq, list) and aq:
            found = aq
    return found


# v2.40 取证深度分档（designs/fetch-depth-tiering-design.md）：三档枚举单源。
# none=仅内查 / light=点查锚点(≤4 curl,≤2 层源,单向) / full=五层源双向(现状)。
_FETCH_TIERS = ("none", "light", "full")

# none 档理由须含仓内取证路径指针（文件扩展名 或 file:line）——
# 机械代理判据，防空判偷懒（「我觉得仓里有」）；语义由 judge 判。
_NONE_TIER_PATH_RE = re.compile(
    r"[\w./-]+\.(?:py|md|json|jsonl|parquet|yaml|yml|toml|sql)|\d+:\d+|:\d+"
)


def _check_fetch_tier_items(items: list, qa: list | None = None) -> str | None:
    """fetch_tier_items：atomic_questions 逐项校验（u:1 子2 专属，nodes 声明）。

    逐项 {q 非空, tier∈none|light|full, tier_reason 非空；none 档理由须含
    仓内路径指针}。拿不准标 light（默认档——漂到 light 的 full 类问题由
    升档机制救回；none 漏取证是质量问题，full 是成本问题）。
    qa 形参为管道统一签名（v2.50）：本检查不用，对齐校验用。
    """
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            return (
                f"atomic_questions[{i}] 须为对象 "
                '{"q":..., "tier":"none|light|full", "tier_reason":...}'
            )
        if not isinstance(it.get("q"), str) or not it["q"].strip():
            return f"atomic_questions[{i}] 缺非空 q（与原子问题清单一一对应）"
        tier = it.get("tier")
        if tier not in _FETCH_TIERS:
            return (
                f"atomic_questions[{i}].tier 须为 none/light/full，当前 {tier!r}"
                "——拿不准标 light（默认档）"
            )
        reason = it.get("tier_reason")
        if not isinstance(reason, str) or not reason.strip():
            return (
                f"atomic_questions[{i}].tier_reason 须非空（分档理由必填，"
                "防空判偷懒——judge 会判理由与问题性质是否匹配）"
            )
        if tier == "none" and not _NONE_TIER_PATH_RE.search(reason):
            return (
                f"atomic_questions[{i}] 标 none 档但 tier_reason 无仓内取证路径"
                "指针（文件路径/file:line）——none=答案仓内可达，理由须指出"
                "去哪查（如 formatters.py:92）；指不出路径的问题不得标 none"
            )
    return None


# atomic_questions 原子标签 ↔ MECE 声明对齐（v2.50，2026-08-02 u:1 子2
# 三连 block att1/att2 复盘）：att1 声明 A/B/C 三原子却交 5 条（D/E 未声明），
# judge 判两轮且 att2 判词把 att1 已修的计数原样再判（陈旧判词失真）——
# 计数/标签对齐是纯集合运算，下沉机械层后 judge 不再碰计数（§3.5 #13
# ID 传导覆盖核对同款）。锚定纪律（§3.5 #21 三原则）：声明侧只认「原子 X」
# 字面（出过事的形态），aq 侧只认首字母标签（A. / A_root 形态）；声明 <2 个
# （单一/无复合）或 aq 无标签（历史通过形态「数值正确性」）= 无机械基准，
# 交 judge——宁纵勿枉，贪宽=FP。
_DECLARED_ATOM_RE = re.compile(r"原子\s*([A-Z])")
_AQ_LABEL_RE = re.compile(r"^([A-Z])(?=[._、：:\s])")


def _check_atomic_mece_alignment(items: list, qa: list | None = None) -> str | None:
    """atomic_mece_alignment：atomic_questions 标签与 MECE 声明原子对齐。

    声明侧从 qa 的 q/a 全文提「原子 X」字母集合（「假设」标题项除外——竞争
    假设里的 H 编号不是原子声明）；aq 侧提首字母标签（A. / A_root 验证 形态）。
    违规两形态：aq 标签未在声明集（att1 的 D/E）、同标签重复（一原子多条）。
    qa=None（statements 格式步）跳过——本校验只服务 qa 格式的 u:1 子2。
    """
    if not qa:
        return None
    declared: set[str] = set()
    for it in qa:
        if "假设" in str(it.get("q", "")):
            continue
        declared.update(_DECLARED_ATOM_RE.findall(str(it.get("q", ""))))
        declared.update(_DECLARED_ATOM_RE.findall(str(it.get("a", ""))))
    if len(declared) < 2:
        return None
    labels: list[str] = []
    for it in items:
        m = _AQ_LABEL_RE.match(str(it.get("q", "")).strip())
        if m:
            labels.append(m.group(1))
    if not labels:
        return None
    extra = sorted(set(labels) - declared)
    if extra:
        return (
            f"atomic_questions 原子标签 {extra} 未在 MECE 声明 {sorted(declared)} "
            "中——与原子清单一一对应：每声明原子恰好 1 条；未声明的问题要么"
            "并入某原子的 q 文本、要么补进 MECE 清单（声明侧同步改）"
        )
    dup = sorted({x for x in labels if labels.count(x) > 1})
    if dup:
        return (
            f"atomic_questions 原子标签 {dup} 重复——一原子恰好 1 条"
            "（子问题合并进同条的 q 文本，不拆多条）"
        )
    return None


# 载荷顶层额外必填键的逐项校验注册表（extra_payload_keys 的 spec 为字符串时
# 查本表——v2.40 从「字符串+前缀」泛化到「数组+逐项校验」）。
# 未注册名 = nodes 与 engine 配置漂移，fail loud。
_MECH_EXTRA_ITEM_CHECKS = {
    "fetch_tier_items": _check_fetch_tier_items,
    "atomic_mece_alignment": _check_atomic_mece_alignment,
}


def _check_conclusion_no_speculation(v: str) -> str | None:
    """conclusion_no_speculation：u:1 子1「结论」键禁推测形态（v2.54）。

    实证（2026-08-02 tail_volume_acceleration_annualized u:1 子1 att1）：
    模型 who 项写得合规（「未自述身份…不冒充身份出处」——它知道规则），
    顶层结论却写「具体主语 = 项目维护者（推测，来源未自述身份 +
    CLAUDE.md §6 + 分支命名佐证）」——who 规则钉在 q/a 项，结论字段成
    漏网面，judge 判对但白烧一轮（钉死保判对不保写对，§3.5 #16）。
    词形取 att1 逐字（「推测」），锚定结论字段（§3.5 #21：q/a 项里
    「推测另列」是合法形态，只扫结论）；分隔度重放：att1 含 att2 不含。
    """
    if "推测" not in v:
        return None
    return (
        "「结论」含「推测」= 无出处推断进了结论——结论逐句须有出处"
        "（用户原话/会话事实），推断只能标「推测」另列在 q/a 项、不进结论；"
        "who 未自述身份就如实写「具体主语 = 未自述身份（who=未自述）」，"
        "仓库事实/分支命名不能证明当前提问者身份"
    )


# 载荷顶层字符串键的内容校验注册表（extra_payload_keys 条目第三元素，
# 前缀校验之后执行——v2.54 从「前缀合规」扩到「内容词形」）。
_MECH_EXTRA_STR_CHECKS = {
    "conclusion_no_speculation": _check_conclusion_no_speculation,
}


def _check_fetch_report_recorded(qa: list, *_ctx) -> str | None:
    """fetch_report_recorded：子3 蒸馏报告原文收录机械核验（u:1 子3 专属）。

    judge 重放实证（2026-08-01 v2.38 落地验证）：无子代理报告的旧形态 trace
    过新 gate 被判 PASS——judge 把内容丰富的留痕当实质满足，「报告原文收录」
    形式要件被裁量放过（子代理编排可被绕过，主上下文卸载落空）。形式要件
    下沉机械层：每原子一个标题含「蒸馏报告」的 q 项（标题=承诺装置+结构），
    judge 只判内容质量。

    v2.40 tier-aware：需外部取证的原子 = 子2 atomic_questions 里 tier≠none
    的项（none 档仅内查、豁免报告项）；报告项数须 ≥ 该数（逐项对齐由 judge
    判，机械只数总数）。子2 trace 无 atomic_questions（v2.40 前实例）->
    legacy 行为（≥1 个报告项）。
    """
    found = sum(1 for item in qa if "蒸馏报告" in str(item.get("q", "")))
    required = 1
    if _ctx and _ctx[0] is not None:
        aq = _load_atomic_questions(_ctx[0], _ctx[1])
        if aq:
            required = max(
                1,
                sum(
                    1 for it in aq if isinstance(it, dict) and it.get("tier") != "none"
                ),
            )
    if found >= required:
        return None
    return (
        f"蒸馏报告收录项不足——需外部取证的原子 {required} 个（tier≠none），"
        f"trace 里标题含「蒸馏报告」的 q 项仅 {found} 个：每原子一个报告项"
        "（fetch-prompt 骨架派发 Agent，报告原文收录非转述；"
        "外部取证不走主会话直连——命令模板在 fetch-prompt 骨架里；"
        "none 档原子豁免——仅内查不派 agent）"
    )


def _check_fetch_skeleton_out(qa, project_root, name):
    """fetch_skeleton_out：子3 骨架 --out 落盘机械核验（u:1 子3 专属，v2.43）。

    v2.42 把骨架路径钉死 per-workflow 目录，但「模型是否真的用了 --out」
    仍靠文案——模型重定向 stdout 自选路径则钉死形同虚设。下沉机械层
    （§8.3 产物门同范式）：骨架文件须存在于 .claude/workflows/<name>/ 且
    mtime 不早于本节点 entered_at（残留防御；entered_at 不可考 -> 降级
    仅存在性，宁纵勿枉）。全 none 档短路消息同样经 --out 落盘，口径一致。
    """
    if project_root is None or name is None:
        return None
    f = project_root / ".claude" / "workflows" / name / "fetch-prompt-skeleton.md"
    if not f.is_file():
        return (
            f"骨架未落盘：{f} 不存在——子3 派发取证子代理前须先跑 "
            "`python3 ~/.dl-workflow/dl_flow_engine.py fetch-prompt --out`"
            "（骨架路径钉死 per-workflow 目录，禁 stdout 重定向自选路径），"
            "落盘后重试"
        )
    state = load_state(project_root, name)
    if state is not None:
        state = normalize_state(state)
        try:
            not_before = _node_entered_at(
                state, get_node(state["phase"], state["sub_index"])
            )
        except KeyError:
            not_before = None
        if not_before is not None and f.stat().st_mtime < not_before:
            return (
                f"骨架陈旧：{f} 最后修改早于本节点进入时间——须在本节点内重新 "
                "fetch-prompt --out 落盘（禁残留），落盘后重试"
            )
    return None


def _check_redteam_report_recorded(qa: list, *_ctx) -> str | None:
    """redteam_report_recorded：子4 红队输出原文收录机械核验（u:1 子4 专属，v2.44）。

    实证（2026-08-02 tail_volume u:1 子4）：模型先撞占位符扫描（「待补」机械拒、
    拒绝消息已指路「等红队归位再提交」），改写措辞绕开扫描（「未归/仍在跑中」
    不含禁词）仍提前提交 -> judge block（~3.5min 返工 + 1 次 judge 白烧）。
    §3.5 #14/#20：词表扩词 = 打地鼠，行为禁令的闭环 = 写侧机械核验。

    信号分隔度经全量历史子4 trace 重放验证（7 条真实载荷）：
    「task-id 出现 = 红队已派发」（红队经 Agent 工具单发起，派发即有 task-id；
    未触发合法分支无 agent 可引，两条真实未派发载荷均无 task-id）×
    收录项 = 标题含「红队」且含「原文收录」的 qa 项（与子3「蒸馏报告」标题
    承诺装置同范式）。被 block 载荷 = 有 task-id 无收录项；通过载荷 = 两者皆有。
    未派发（含未触发声明、触发满足但未起）-> None 交 judge 判真值（宁纵勿枉）。
    """
    text_all = "\n".join(f"{item.get('q', '')}\n{item.get('a', '')}" for item in qa)
    if "task-id" not in text_all and "task_id" not in text_all:
        return None
    recorded = any(
        "红队" in str(item.get("q", "")) and "原文收录" in str(item.get("q", ""))
        for item in qa
    )
    if recorded:
        return None
    return (
        "红队已派发（trace 含 task-id）但输出未原文收录——缺标题含「红队」"
        "「原文收录」的 qa 项（正确动作：append-trace --ingest-agent <task-id>，"
        "脚本提取报告原文落载荷，禁手工粘贴）。"
        "等 Agent 归位收录原文后再提交；agent 失败/空结果则重派或升级用户裁决"
        "——「已派发等归位」式状态说明不算记录（提前提交 = 红队结论缺席的裁决，"
        "下游子5 会拿到未经对抗复核的问题集）"
    )


def _check_user_decision_recorded(qa: list, *_ctx) -> str | None:
    """user_decision_recorded：读回确认步的用户裁决记录机械核验（v2.45）。

    交接架构（designs/context-handoff-design.md §4）正确性前提：8 个读回步
    全部 gate=None（trace 存在即过、无 judge），用户裁决此前只在对话里——
    /clear 换会话后新上下文只能从 trace 还原拍板内容，漏记 = 重问用户或编造。
    操作化：标题带「裁决」或「读回」的 qa 项（承诺装置同「蒸馏报告」先例）
    + 内容 ≥50 字（「用户已确认」式空记录交接后无法还原拍板）。
    分隔度：真实 u:1 子6（699 字）/u:2 子5（543 字）通过；空记录（<10 字）
    与缺项两形态拦截——margin 两个数量级，非调参数式阈值（§3.5 #15）。
    """
    titled = [
        it
        for it in qa
        if "裁决" in str(it.get("q", "")) or "读回" in str(it.get("q", ""))
    ]
    if any(len(str(it.get("a", "")).strip()) >= 50 for it in titled):
        return None
    if titled:
        return (
            "用户裁决记录项内容过薄——「用户已确认」式空记录不算：逐项记录用户"
            "认/否/拍板结果与答复要点。读回步 gate=None 无 judge 兜底，且 /clear "
            "交接后新会话只能从 trace 还原拍板内容——空记录 = 重问用户或编造"
        )
    return (
        "缺用户裁决记录项——读回确认步的 trace 须含标题带「裁决」或「读回」的 "
        "qa 项，逐项记录用户认/否/拍板结果与答复要点（读回步 gate=None，本校验"
        "是唯一防线；/clear 交接后新会话只能从 trace 还原拍板内容）"
    )


# v2.51 原话标注通道（2026-08-02 u:1 子1 三连 block att1-3 逐字）：
# 用户全程只点 AskUserQuestion 选项（transcript 实证零打字原话），judge 按
# 「who 只认用户自述」临场发明「原话全文引用」要件——三轮共同形态=「原话」
# 声称 + AskUserQuestion 出处 + 无通道标注；选项标签标「原话」=标注失真
# （声称的佐证等级高于实际）。通道两态与 _USER_QUOTE_FORMS_RULE 一一对应：
# 「选中」=选项标签（会话事实级自述，不得标原话）/「自由输入」=打字原话。
# v2.52 扩面（同日晚第二集）：模型换「自述」绕开「原话」词表（逐字取自
# 新 att1）；锚定改「标签+引用」近端形态（自述/原话 + 冒号/引号），防
# 「本步仅认用户自述」式元讨论 FP。
_QUOTE_LABEL_RE = re.compile(r"(?:用户)?(?:身份)?(?:原话|自述)[^，。；]{0,6}[:：『「]")
_ASKQ_ANN_RE = re.compile(r"（[^）]{0,50}AskUserQuestion[^）]{0,50}）")


def _check_user_quote_channel(qa: list, *_ctx) -> str | None:
    """user_quote_channel：AskUserQuestion 出处「原话/自述」标签的通道校验
    （u:1 子1 专属，nodes 声明）。

    只判标注形态不判真值：「原话/自述」作标签引出引用（后接冒号/引号）
    且近端有 AskUserQuestion 出处括注时——括注含「选中」=选项标签带等级
    前缀，标注失真当场拒；含「自由输入」=自称打字原话，真值归 judge；
    皆无=通道未声明当场拒。无标签形态（如「标签全文（AskUserQuestion
    选中）」）与元讨论里的「自述」字样不拦（宁纵勿枉）。
    分隔度：att1-3（v2.51 集）+ 新 att1（v2.52 集「自述」换词）逐字 BLOCK；
    合法两态、新 att2 干净形态、元讨论 FP 守卫全 PASS。
    """
    for item in qa:
        a = str(item.get("a", ""))
        for m in _QUOTE_LABEL_RE.finditer(a):
            window = a[m.start() : m.start() + 140]
            ann = _ASKQ_ANN_RE.search(window)
            if ann is None:
                continue  # 直接对话原话等——不涉 AskUserQuestion 通道
            if "选中" in ann.group(0):
                return (
                    "选项标签不得带「原话/自述」前缀——标注失真（声称的佐证"
                    "等级高于实际）：选中项=用户主动声明行为，是合法佐证但属"
                    "会话事实级，记录=选项标签全文+「（AskUserQuestion 选中）」"
                    "并去掉「原话/自述」前缀词"
                )
            if "自由输入" in ann.group(0):
                continue
            return (
                f"AskUserQuestion 出处的「原话/自述」声称未标注通道"
                f"（{str(item.get('q', ''))[:20]}…）：「（AskUserQuestion 选中）」"
                "=选项标签（会话事实级，须去掉「原话/自述」前缀）/"
                "「（AskUserQuestion 自由输入）」=打字原话——补通道标注；"
                "是选中则去掉前缀词，是打字则标「自由输入」"
            )
    return None


def _check_answer_no_reverse_inference(qa: list, *_ctx) -> str | None:
    """answer_no_reverse_inference：答案位禁反推（u:1 子1 专属，v2.68）。

    实证（2026-08-03 tail_volume_acceleration_annualized u:1 子1 att1）：
    模型第 4 类「可观察后果」没问用户，a 填「三项标签反推…本项为反推项」
    （诚实披露词形），judge 依「痛点须用户确认」判 block——判对但白烧一轮
    judge + 一轮全量上下文（钉死保 judge 判对不保模型写对，§3.5 #16；
    一次通过率=最大杠杆）。词形下沉机械层=秒拒+精确返工指路。
    词形取 att1 a[3] 逐字（反推/暗含/隐含，§3.5 #22 词形取真实被 block
    载荷逐字先例）；含「推测」标注的项豁免（「推断标推测另列」是
    _STEP1_FORM_REQUIREMENTS 的合法形态，宁纵勿枉）。att2 的「认知类答案
    包装成可观察后果链」无反推词形、内容质量归 judge，本校验不拦（分工
    边界，见 designs/understand1-sub1-reverse-inference-option-design-design.md）。
    """
    for item in qa:
        a = str(item.get("a", ""))
        if "推测" in a:
            continue
        for w in ("反推", "暗含", "隐含"):
            if w in a:
                return (
                    f"答案含「{w}」= 反推占答案位——该维度必须实际 "
                    "AskUserQuestion 补问（或引用上下文已有的用户原话），"
                    "禁止问一部分、反推剩余；推断内容标「推测」另列可接受，"
                    "但不能充当该维度的用户确认答案"
                )
    return None


# v2.71（2026-08-03 tail_volume u:1 子1 judge 误伤根治）：
# 6 变体 ~70 次重放实证 judge 对 who 项最高频误判之一=把「AskUserQuestion 选中
# 角色选项」当「仓库事实冒充身份」（V3c att2#3/clean#2）。who 出处合法性属形式
# 要件（关键词可判），下沉机械层=append-trace 当场拒，judge 不再判 who 出处
# （§3.5 #13 词形判据下沉机械层 + #17 形式要件机械化）。词形取真实判词逐字
# （CLAUDE.md/git config/分支命名）；选中角色选项/未自述标注不拦（宁纵勿枉）。
_WHO_REPO_FACT_RE = re.compile(r"CLAUDE\.md|git\s*config|分支命名|git\s*log|commit\s*历史")


def _check_who_no_repo_fact(qa: list, *_ctx) -> str | None:
    """who_no_repo_fact：who 项禁仓库事实冒充身份出处（u:1 子1 专属，v2.71）。

    who 类出处只认用户自述（含选中角色选项）；仓库事实（CLAUDE.md/git config/
    分支命名）只证明「仓库由谁维护」不能证明「当前提问者身份」。扫描 who 项 a
    含仓库事实关键词即拒--把 judge 对 who 出处的裁量方差（V3c 实证选中项被当
    仓库事实）下沉机械层零方差。选中角色选项/「未自述身份」标注不拦。
    """
    for item in qa:
        q = str(item.get("q", ""))
        if "who" not in q.lower() and "角色" not in q and "身份" not in q:
            continue
        a = str(item.get("a", ""))
        if _WHO_REPO_FACT_RE.search(a):
            return (
                "who 项用了仓库事实（CLAUDE.md/git/分支命名）冒充提问者身份--"
                "仓库事实只证明「仓库由谁维护」不能证明「当前提问者身份」；"
                "who 类出处只认用户自述（含 AskUserQuestion 选中的角色选项），"
                "无自述时如实标注「未自述身份」合法"
            )
    return None


# v2.75（2026-08-04 u:1 子2 vio2 稻草人牙齿根治）：
# v2.73/v2.74 重放实证 judge 对「排除理由无证据指针」判据双向抖动——
# v2.73 把缺席断言「用户没有表达过这个意思」当留痕放过（vio2 4/6 牙齿掉），
# v2.74 钉「缺席断言≠指针」后又对 clean 的具体选择记录过度索取（clean 1/6）。
# 缺席断言是词形可判项——下沉机械层零方差（§3.5 #13），judge 只判「假设
# 明显不成立且凑数」的语义侧。词形取 vio2 真实载荷逐字（没有表达过）。
_HYP_EXCLUDE_ABSENCE_RE = re.compile(
    r"排除[^。]{0,40}?(没有表达过|没说过|未说过|没有说过|未提及|没有提到|未提到|没有表达)"
)


def _check_hypothesis_exclude_no_absence(qa: list, *_ctx) -> str | None:
    """hypothesis_exclude_no_absence：竞争假设排除理由禁缺席断言（u:1 子2，v2.75）。

    「用户没有表达过/没说过」式缺席断言不算证据指针（断言「没有什么」，
    与全局否定断言同族）；排除须引用具体原话或具体选择记录（如
    AskUserQuestion 选中项），证据不足改标「保留/待子3取证」。
    「未选择 X 而选择 Y」是对具体选择记录的引用，合法不拦（宁纵勿枉）。
    """
    for item in qa:
        a = str(item.get("a", ""))
        if _HYP_EXCLUDE_ABSENCE_RE.search(a):
            return (
                "竞争假设排除理由用了缺席断言（「用户没有表达过/没说过」类）——"
                "缺席断言不算证据指针；排除须引用具体原话或具体选择记录"
                "（如 AskUserQuestion 选中项），证据不足时改标「保留/待子3取证」"
            )
    return None


# qa 格式步的写侧机械校验注册表（Step.mech_checks 声明名 -> 检查函数）。
# 未注册名 = nodes 与 engine 配置漂移，fail loud 不静默跳过。
_MECH_QA_CHECKS = {
    "causal_ring_no_untested": _check_causal_ring_no_untested,
    "user_quote_channel": _check_user_quote_channel,
    "answer_no_reverse_inference": _check_answer_no_reverse_inference,
    "who_no_repo_fact": _check_who_no_repo_fact,
    "hypothesis_exclude_no_absence": _check_hypothesis_exclude_no_absence,
    "value_no_unsourced_inference": _check_value_no_unsourced_inference,
    "fetch_report_recorded": _check_fetch_report_recorded,
    "fetch_skeleton_out": _check_fetch_skeleton_out,
    "redteam_report_recorded": _check_redteam_report_recorded,
    "user_decision_recorded": _check_user_decision_recorded,
}


# v2.65（2026-08-03 tail_volume_acceleration_annualized u:1 子1 手写载荷事故）：
# 标头捕获组后放行 glued 内容——模型手写自然风格是「【purpose】内容」同行
# （scaffold 骨架是标头独占一行，但模型绕过 scaffold 手写时本能粘头），
# 旧 `\s*$` 整行匹配把粘头行当「标头前多余内容」拒，报错「从【purpose】开始」
# 与文件实况（确实以【purpose】开头）矛盾，模型被误导去 hunt BOM/隐藏字节
# （xxd/od/python-rb 连环 S15 deny）。group(2)=粘头内容（空=干净标头行）。
_MD_HEADER_RE = re.compile(r"^【([^】]+)】[ \t]*(.*)$")
_MD_ITEM_FIELDS = frozenset(
    {"q", "a", "text", "type_label", "boundary", "tier", "tier_reason"}
)


class _MdErr(Exception):
    """标记文本解析错误（fail loud 给模型指路）。"""


def _parse_trace_md(raw: str, step) -> tuple[dict | None, str | None]:
    """分节标记文本 -> 载荷 dict（v2.58：模型零接触 JSON 的正治）。

    四桶分工（AI 定写什么/脚本定怎么写）的兑现：v2.57 scaffold 只缩小了
    JSON 接触面——Edit 填内容时 ASCII 双引号/反斜杠照样崩 JSON（真实
    trace 含 f"{val*100:.2f}%" 类代码原文）。标记文本零转义：内容随便带
    引号/换行/代码，序列化全归脚本。
    格式：标头顶格写；【purpose】/【qa】/【q】/【a】/【statements】/
    【text】/【type_label】/【boundary】/【fields.<k>】/【结论】等声明键。
    数组键（qa/statements/atomic_questions）内首个字段标头重复 = 新一项；
    标量键（purpose/结论）收文本到下一标头。内容行想以【开头：缩进一格即
    不算标头（逃生口）。
    v2.65 宽容化（手写载荷事故正治）：①剥文件头 BOM；②标头后可粘内容
    （「【purpose】内容」同行=标头+内容，模型手写自然风格——scaffold 骨架
    是标头独占一行，但绕过 scaffold 手写时本能粘头，旧版误拒且报错指路
    与实况矛盾）；③「标头前多余内容」报错带 repr 实际内容（BOM/散文一眼
    可见，免 xxd/od 字节 hunt）。
    """
    raw = raw.lstrip("\ufeff")  # ①剥文件头 BOM（Write/编辑器可能带 \ufeff）
    array_keys: set[str] = set()
    scalar_keys = {"purpose"}
    if getattr(step, "record_format", "qa") == "statements":
        array_keys.add("statements")
    else:
        array_keys.add("qa")
    for e in getattr(step, "extra_payload_keys", ()):
        k, spec = e[0], e[1]
        if isinstance(spec, str):
            array_keys.add(k)
        else:
            scalar_keys.add(k)

    payload: dict = {}
    key: str | None = None  # 当前顶层键
    item: dict | None = None  # 当前数组项
    field: str | None = None  # 当前项内字段
    first_field: dict[str, str] = {}  # 数组键 -> 首字段名（重复=新一项）
    buf: list[str] = []

    def _flush() -> None:
        nonlocal buf
        val = "\n".join(buf).strip("\n")
        buf = []
        if key is None:
            if val.strip():
                raise _MdErr(
                    "首个标头前有多余内容--从【purpose】开始；"
                    f"实际内容 {val[:80]!r}（引擎已自动剥文件头 BOM--"
                    "检查是否在【purpose】前写了散文/注释）"
                )
            return
        if key in array_keys:
            if item is None or field is None:
                if val.strip():
                    raise _MdErr(
                        f"【{key}】节内须先给字段标头（如【q】/【text】）再写内容"
                    )
                return
            if field.startswith("fields."):
                item.setdefault("fields", {})[field.split(".", 1)[1]] = val
            else:
                item[field] = val
        else:
            payload[key] = val

    try:
        for ln in raw.splitlines():
            m = None if ln[:1] in (" ", "\t") else _MD_HEADER_RE.match(ln)
            if not m:
                # 逃生口：缩进 + 【 开头 = 内容（剥掉转义缩进）
                if ln[:1] in (" ", "\t") and ln.lstrip()[:1] == "【":
                    ln = ln.lstrip()
                buf.append(ln)
                continue
            h = m.group(1).strip()
            _flush()
            if h in scalar_keys:
                if h in payload:
                    raise _MdErr(f"标头【{h}】重复——同一键只写一次")
                key, item, field = h, None, None
            elif h in array_keys:
                key, item, field = h, None, None
                payload.setdefault(h, [])
            elif h in _MD_ITEM_FIELDS or h.startswith("fields."):
                if key not in array_keys:
                    raise _MdErr(
                        f"【{h}】是数组项字段标头，须写在数组键节内"
                        f"（{'/'.join(sorted(array_keys))}），当前节=【{key}】"
                    )
                ff = first_field.setdefault(key, h)
                if h == ff:
                    item = {}
                    payload[key].append(item)
                elif item is None:
                    raise _MdErr(f"【{key}】节每项都须以【{ff}】开头")
                field = h
            else:
                raise _MdErr(
                    f"未知标头【{h}】——本步合法标头："
                    + "/".join(f"【{x}】" for x in sorted(scalar_keys | array_keys))
                    + " + 数组项字段【q】【a】/【text】【type_label】【boundary】"
                    "（内容行想以【开头：缩进一格即不算标头）"
                )
            # v2.65：粘头内容（【key】内容 同行）注入当前节首行--
            # 模型手写自然风格粘头，scaffold 骨架是标头独占行；group(2)=粘头文本
            glued = m.group(2)
            if glued.strip():
                buf.append(glued.strip())
        _flush()
    except _MdErr as e:
        return None, str(e)
    return payload, None


def _subagent_dir(project_root: Path, name: str) -> Path | None:
    """子代理 transcript 目录（v2.39 台账同款定位，抽出共用）。"""
    state = load_state(project_root, name)
    if not state:
        return None
    sid, wt = state.get("session_id"), state.get("worktree_path")
    if not sid or not wt:
        return None
    enc = "".join(c if c.isalnum() else "-" for c in str(wt))
    d = Path.home() / ".claude" / "projects" / enc / sid / "subagents"
    return d if d.is_dir() else None


def ingest_agent_report(
    project_root: Path, name: str, task_id: str
) -> tuple[bool, str]:
    """append-trace --ingest-agent <task-id>：子代理报告原文落载荷（v2.60）。

    四桶分工审计违规②根治：子3 fetch 蒸馏报告/子4 红队输出原要求模型
    「原文收录（完整粘贴）」——粘贴=转录，还配两层防偷懒 mech 检查。
    脚本按 task-id 定位 subagents/agent-<task-id>.jsonl、提取最终报告文本、
    以规定形态（标题含「蒸馏报告」/「红队」「原文收录」）追加进当前
    .md 载荷——「是否原文收录」从需要检查变结构性保证。
    载荷不存在/报告已收录/transcript 缺失 -> fail loud 指路。
    """
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    cur = normalize_state(state).get("sub_step_index", 1)
    title = (
        "蒸馏报告原文收录"
        if cur == 3
        else "红队输出原文收录"
        if cur == 4
        else "子代理报告原文收录"
    )
    payload_path = (
        _evidence_path(project_root, name).parent / f".trace-payload-{name}.md"
    )
    if not payload_path.exists():
        return False, (
            f"载荷不存在：{payload_path}——先写本步其它内容（或 append-trace "
            "--scaffold 起骨架），再 --ingest-agent 追加报告收录项"
        )
    try:
        text = payload_path.read_text(encoding="utf-8")
    except OSError as e:
        return False, f"读载荷失败：{e}"
    if task_id in text:
        return False, f"task-id {task_id} 已收录过——同一报告不重复落（防重）"

    d = _subagent_dir(project_root, name)
    fp = d / f"agent-{task_id}.jsonl" if d else None
    if fp is None or not fp.exists():
        return False, (
            f"找不到子代理 transcript：agent-{task_id}.jsonl"
            f"（目录 {d}）——task-id 以 Agent 工具返回的 <task-id> 为准"
        )
    report = ""
    try:
        for line in fp.open(encoding="utf-8"):
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if m.get("type") != "assistant":
                continue
            blocks = [
                str(b.get("text", ""))
                for b in (m.get("message", {}).get("content") or [])
                if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
            ]
            if blocks:
                report = "\n".join(blocks)  # 最后一条含文本的 assistant 消息=最终报告
    except OSError as e:
        return False, f"读子代理 transcript 失败：{e}"
    if not report.strip():
        return False, (
            f"agent-{task_id}.jsonl 无文本报告（子代理未产出/仍在跑）——"
            "等 Agent 返回后再 ingest"
        )

    # 插入【qa】节内（节末、下一顶层标头前）——追加文件尾会落进别的节
    # （【q】在【atomic_questions】节末=被当分档项；在【结论】节末=解析报错）。
    lines = text.splitlines()
    qa_idx = next((i for i, ln in enumerate(lines) if ln.strip() == "【qa】"), None)
    if qa_idx is None:
        return False, "载荷缺【qa】节——报告收录项进 qa 节，先补 qa 节再 ingest"
    item_headers = {f"【{h}】" for h in _MD_ITEM_FIELDS}
    insert_at = len(lines)
    for i in range(qa_idx + 1, len(lines)):
        st = lines[i].strip()
        if (
            st.startswith("【")
            and st.endswith("】")
            and st not in item_headers
            and not st.startswith("【fields.")
        ):
            insert_at = i
            break
    section = [
        "",
        "【q】",
        f"{title}（task-id {task_id}）",
        "【a】",
        *report.strip().splitlines(),
        "",
    ]
    lines[insert_at:insert_at] = section
    try:
        payload_path.write_text("\n".join(lines), encoding="utf-8")
    except OSError as e:
        return False, f"写载荷失败：{e}"
    return True, (
        f"✓ 已收录 {title}（task-id {task_id}，{len(report)} 字符）-> "
        f"{payload_path}——其余「待填」填完后 append-trace --from-file 落库"
    )


def scaffold_payload(project_root: Path, name: str) -> tuple[bool, str]:
    """append-trace --scaffold：当前子步骤载荷骨架生成并落盘钉死路径。

    v2.57 动机（2026-08-02 tail_volume_acceleration_annualized u:1 审计）：
    模型手写全量 JSON 载荷出语法错（Extra data char 3895）白烧一轮——
    §3.6 #10 自检信号：语法错误不该归「模型基本功」，杠杆=脚本生成骨架。
    v2.58 正治：骨架从 JSON 换成分节标记文本（.md，零转义）——Edit 填
    JSON 仍会被内容里的 ASCII 引号弄崩（四桶分工没贯彻到底的半吊子），
    标记文本让模型全程零接触序列化格式。占位符统一用「待填」——
    _placeholder_hit 全局扫描兜底，漏填任何字段都过不了 append-trace。
    落盘路径钉死 evidence/.trace-payload-<name>.md（v2.42 同款纪律：路径
    归脚本不归模型自选）；已存在载荷拒覆盖（防抹掉在写工作）——例外：
    mtime < state.created_at 判为上轮残留，自动清理（v2.63，见函数体注释）。
    """
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    state = normalize_state(state)
    try:
        node = get_node(state["phase"], state["sub_index"])
    except KeyError:
        return False, f"节点 {state['phase']}:{state['sub_index']} 不存在"
    if not node.sub_steps:
        return False, f"节点 {node_id(node.phase, node.sub)} 无子步骤编排"
    cur = state.get("sub_step_index", 1)
    step = sub_step_at(node, cur)
    if step is None:
        return False, f"子步骤 {cur} 不存在"

    parts = ["【purpose】\n待填：本步目的/本轮做了什么（一句话）"]
    if getattr(step, "record_format", "qa") == "statements":
        seg = (
            "【statements】\n【text】\n待填：单句陈述（outcome 层，禁实现侧名词/file:line）"
            "\n【type_label】\n待填：类型标签（如 in/out）\n【boundary】\n待填：边界/实现指针"
        )
        for k in getattr(step, "statement_fields", ()) or ():
            seg += f"\n【fields.{k}】\n待填：{k}"
        parts.append(seg)
    else:
        parts.append(
            "【qa】\n【q】\n待填：问题1\n【a】\n待填：答案1（用户原话/会话事实/证据指针 file:line）"
        )
    seen: set[str] = set()
    for e in getattr(step, "extra_payload_keys", ()):
        k, spec = e[0], e[1]
        if k in seen:
            continue  # 同键多 spec（fetch_tier_items + atomic_mece_alignment）只取首个
        seen.add(k)
        if isinstance(spec, str):
            if spec == "fetch_tier_items":
                parts.append(
                    f"【{k}】\n【q】\n待填：原子问题（与 MECE 声明标签一一对应）"
                    "\n【tier】\n待填：none|light|full（拿不准标 light）"
                    "\n【tier_reason】\n待填：分档理由（none 档须含仓内路径）"
                )
            else:
                parts.append(f"【{k}】\n【q】\n待填")
        else:
            parts.append(f"【{k}】\n待填：{'/'.join(spec)} 开头+逐句出处")

    out = _evidence_path(project_root, name).parent / f".trace-payload-{name}.md"
    stale_cleaned = ""
    if out.exists():
        # v2.63（2026-08-03 tail_volume_acceleration_annualized u:1 子1 事故）：
        # 上轮放弃运行的 payload 点文件残留挡住新一轮首个 --scaffold（手动清
        # evidence 用 ls 看不见点文件；launch/state-reset 均不清 payload）。
        # 机械判 stale：payload mtime < state.created_at ⇒ 它诞生时本轮还
        # 不存在 ⇒ 定义性残留，自动清理重新生成；否则可能是本轮在写工作 ⇒
        # 维持拒覆盖。created_at 缺失/畸形 ⇒ 宁纵勿枉维持拒覆盖（不误删）。
        stale = False
        created = state.get("created_at")
        if isinstance(created, str):
            try:
                created_ts = time.mktime(time.strptime(created, "%Y-%m-%dT%H:%M:%S"))
                stale = out.stat().st_mtime < created_ts
            except (ValueError, OSError):
                pass
        if not stale:
            return False, (
                f"载荷已存在：{out}——直接在它上面填内容（Edit），或删除后重跑 "
                "--scaffold（拒覆盖防抹掉在写工作）"
            )
        out.unlink()
        stale_cleaned = f"（已自动清理上轮残留载荷：mtime 早于本工作流启动 {created}）"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    except OSError as e:
        return False, f"写骨架失败：{e}"
    return True, (
        f"✓ 骨架已生成 {out}（子步骤 {cur} {step.ref}）{stale_cleaned}——"
        "先 Read 该文件再 Write/Edit（harness 写前必读，跳过会报 "
        "read-first 错）；把所有「待填」换成实际内容（漏填会被占位符扫描当场拒；"
        "内容随便带引号/换行/代码，格式全归脚本），"
        f"然后 Bash `python3 ~/.dl-workflow/dl_flow_engine.py append-trace --from-file {out}`"
    )


def append_trace(project_root: Path, name: str, payload_file: str) -> tuple[bool, str]:
    """载荷（purpose + qa 配对；旧 q/a 平行数组写侧已退役硬拒）+ state 结构字段 -> 校验 -> 单行 skill-trace append。

    返回 (ok, 消息)。校验失败 (False, 原因)——fail loud：模型当轮按报错修载荷
    重跑，而不是写坏了到 gate 才暴露（甚至像 d59d05ea 那样静默卡死）。
    成功后删载荷文件（防重复落库；失败保留供模型原地修）。
    """
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    state = normalize_state(state)
    try:
        node = get_node(state["phase"], state["sub_index"])
    except KeyError:
        return False, f"节点 {state['phase']}:{state['sub_index']} 不存在"
    if not node.sub_steps:
        return (
            False,
            f"节点 {node_id(node.phase, node.sub)} 无子步骤编排，append-trace 不适用",
        )
    if not node.minor_key:
        return (
            False,
            f"节点 {node_id(node.phase, node.sub)} 无 minor_key，无法填结构字段",
        )
    cur = state.get("sub_step_index", 1)
    step = sub_step_at(node, cur)
    if step is None:
        return False, f"子步骤 {cur} 不存在"

    pf = Path(payload_file)
    try:
        raw = pf.read_text(encoding="utf-8")
    except OSError as e:
        return False, f"读载荷失败：{e}（先用 Write 写载荷文件再调 append-trace）"
    try:
        payload = json.loads(raw) if pf.suffix != ".md" else None
    except json.JSONDecodeError as e:
        return False, (
            f"载荷不是合法 JSON：{e}——推荐改用标记文本载荷（.md，零转义）："
            "append-trace --scaffold 生成骨架，内容随便带引号/换行/代码"
        )
    if pf.suffix == ".md":
        payload, md_err = _parse_trace_md(raw, step)
        if md_err:
            return False, f"载荷标记文本解析失败：{md_err}"
    if not isinstance(payload, dict):
        return False, '载荷须是 JSON 对象：{"purpose":..., "qa":[{"q":..., "a":...}]}'
    leaked = [k for k in _TRACE_STRUCT_FIELDS if k in payload]
    if leaked:
        return False, (
            f"载荷含结构字段 {leaked}——这些由脚本从 state 自动填，载荷里不要写"
            "（只留 purpose + 内容字段：qa 或 statements，及本步声明的额外必填键）"
        )
    purpose = payload.get("purpose")
    if not isinstance(purpose, str) or not purpose.strip():
        return False, "purpose 须为非空字符串"
    ph = _placeholder_hit(payload)
    if ph:
        marker, loc = ph
        return False, (
            f"trace 是完成记录——含占位标记「{marker}」（位于 {loc}）；"
            "待决项到位后再提交（红队未归：等 Agent 返回并原文收录后再 append-trace）"
        )
    qa: list | None = None  # qa 格式分支赋值；extra 逐项校验的声明侧上下文（v2.50）
    if getattr(step, "record_format", "qa") == "statements":
        # v2.27 statements 结构化载荷（清单型产出步）：三字段校验 +
        # 机械预检（方案名词扫描 + 源步 ID 传导覆盖）——词形判据下沉机械层。
        # v2.33 statement_fields：步声明的必备字段键（如设计陈述八字段）进
        # fields 对象，append 时逐键校验非空——「N 字段齐备」形式要件从
        # judge 判词变 JSON 校验，judge 只剩语义判据。
        req_fields = getattr(step, "statement_fields", ()) or ()
        statements = payload.get("statements")
        if statements is not None and (
            payload.get("qa") is not None
            or payload.get("q") is not None
            or payload.get("a") is not None
        ):
            return False, "载荷 statements 与 qa/q/a 两格式混用——只留 statements"
        if not isinstance(statements, list) or not statements:
            return False, (
                "statements 须为非空数组："
                '[{"text":...,"type_label":...,"boundary":...}, ...]'
            )
        for i, item in enumerate(statements):
            if not isinstance(item, dict):
                return False, f"statements[{i}] 须为对象"
            for field in ("text", "type_label", "boundary"):
                if not isinstance(item.get(field), str) or not item[field].strip():
                    return False, f"statements[{i}].{field} 须为非空字符串"
            if req_fields:
                flds = item.get("fields")
                if not isinstance(flds, dict):
                    return False, (
                        f"statements[{i}].fields 须为对象——本步逐项必备字段："
                        f"{'/'.join(req_fields)}"
                    )
                missing_f = [
                    k
                    for k in req_fields
                    if not isinstance(flds.get(k), str) or not flds[k].strip()
                ]
                if missing_f:
                    return False, (
                        f"statements[{i}].fields 缺或空字段：{'、'.join(missing_f)}"
                        f"——本步逐项必备：{'/'.join(req_fields)}"
                        "（字段齐备是机械校验的形式要件，补齐再提交）"
                    )
        nouns = _implementation_nouns(project_root)
        for i, item in enumerate(statements):
            for noun in sorted(nouns):
                if noun in item["text"] and re.search(
                    _NOUN_L + re.escape(noun) + _NOUN_R, item["text"]
                ):
                    return False, (
                        f"statements[{i}].text 含实现侧名词「{noun}」——陈述体只许 "
                        "outcome-level 概念，实现侧名词/file:line 挪到 boundary 字段"
                        "（judge 之前的机械预检，与 gate 的方案名词规则同源）"
                    )
        src = _source_step_index(step, cur)
        if src:
            src_ids = _step_trace_ids(project_root, name, src, node.minor_key)
            if src_ids:
                new_text = " ".join(
                    f"{it['text']} {it['type_label']} {it['boundary']} "
                    + " ".join(str(v) for v in (it.get("fields") or {}).values())
                    for it in statements
                )
                missing = sorted(i for i in src_ids if i not in new_text)
                if missing:
                    return False, (
                        f"源步（子{src}）条目未逐项传导，缺：{'、'.join(missing)}"
                        "——逐项原子化传导是形式要件，逐条补或显式标注剔除理由"
                    )
        content_fields = {"statements": statements}
    else:
        qa = payload.get("qa")
        if qa is not None and (
            payload.get("q") is not None or payload.get("a") is not None
        ):
            return False, "载荷 qa 与 q/a 两格式混用——只留 qa 配对格式"
        if qa is None and (
            payload.get("q") is not None or payload.get("a") is not None
        ):
            # v2.35 写侧收编：平行数组过渡桥拆除（v2.24 留的兼容路径只服务
            # 无视提示凭旧惯性写的模型，tail_volume plan:3 子5 q=11 a=7 实例）。
            # 对齐正确也硬拒——写对被默许等于强化漂移习惯。读侧不受影响：
            # evidence 记录 schema 仍是 q/a 平行数组（本函数归一化后写入）。
            return False, (
                "q/a 平行数组写侧已退役——改用 qa 配对格式 "
                '{"qa":[{"q":...,"a":...},...]}（一问一答配对成对象，'
                "不对齐在结构上不可表示）；问答内容原样搬运，只改载荷结构"
            )
        # v2.24 qa 配对格式：一问一答成对象，不对齐在结构上不可表示
        # （tail_volume understand:3 子4 平行数组三次长度不齐，各白烧一轮整篇重写）。
        if not isinstance(qa, list) or not qa:
            return False, 'qa 须为非空数组：[{"q":..., "a":...}, ...]'
        for i, item in enumerate(qa):
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("q"), str)
                or not item["q"].strip()
                or not isinstance(item.get("a"), str)
                or not item["a"].strip()
            ):
                return (
                    False,
                    f'qa[{i}] 须为含非空 q 与 a 的对象（{{"q":..., "a":...}}）',
                )
        for chk in getattr(step, "mech_checks", ()):
            fn = _MECH_QA_CHECKS.get(chk)
            if fn is None:
                return False, (
                    f"mech_checks 配置错误：「{chk}」未在 _MECH_QA_CHECKS 注册"
                    "（nodes 与 engine 漂移，fail loud）"
                )
            err = fn(qa, project_root, name)
            if err:
                return False, err
        q = [item["q"] for item in qa]
        a = [item["a"] for item in qa]
        content_fields = {"q": q, "a": a}

    # v2.37 extra_payload_keys：步声明的载荷顶层必填内容键（两格式通用）——
    # 存在性 + 非空 + 前缀机械校验，值并入 record 顶层（judge 读原始行自动可见）。
    # v2.40 泛化：spec 为字符串时是 _MECH_EXTRA_ITEM_CHECKS 注册名——值须为
    # 非空数组并过逐项校验（如 atomic_questions 分档清单）。
    extra_fields: dict = {}
    for entry in getattr(step, "extra_payload_keys", ()):
        key, spec = entry[0], entry[1]
        # v2.54：条目第三元素 = _MECH_EXTRA_STR_CHECKS 注册名（字符串键的
        # 内容词形校验，前缀校验通过后执行）。
        str_check = entry[2] if len(entry) > 2 else None
        v = payload.get(key)
        if isinstance(spec, str):
            fn = _MECH_EXTRA_ITEM_CHECKS.get(spec)
            if fn is None:
                return False, (
                    f"extra_payload_keys 配置错误：「{spec}」未在 "
                    "_MECH_EXTRA_ITEM_CHECKS 注册（nodes 与 engine 漂移，fail loud）"
                )
            if not isinstance(v, list) or not v:
                return False, (
                    f"载荷缺必填键「{key}」——本步形式要件（append-trace 机械校验）："
                    "顶层提交非空数组，逐项 "
                    '{"q":..., "tier":..., "tier_reason":...}'
                )
            err = fn(v, qa)
            if err:
                return False, err
            extra_fields[key] = v
            continue
        prefixes = spec
        if not isinstance(v, str) or not v.strip():
            return False, (
                f"载荷缺必填键「{key}」——本步形式要件（append-trace 机械校验）："
                f"顶层提交「{key}」且以 {'/'.join(prefixes)} 开头"
            )
        if prefixes and not v.strip().startswith(prefixes):
            return False, (
                f"「{key}」须以 {'/'.join(prefixes)} 开头（二选一必出），"
                f"当前开头：{v.strip()[:12]!r}"
            )
        if str_check is not None:
            fn = _MECH_EXTRA_STR_CHECKS.get(str_check)
            if fn is None:
                return False, (
                    f"extra_payload_keys 配置错误：「{str_check}」未在 "
                    "_MECH_EXTRA_STR_CHECKS 注册（nodes 与 engine 漂移，fail loud）"
                )
            err = fn(v.strip())
            if err:
                return False, err
        extra_fields[key] = v.strip()

    record = {
        "kind": "skill-trace",
        "major_stage": state["phase"].capitalize(),
        "minor_stage": node.minor_key,
        "sub_step": cur,
        "skill": step.ref,
        "purpose": purpose,
        **content_fields,
        **extra_fields,
    }
    path = _evidence_path(project_root, name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        return False, f"写 evidence 失败：{e}"
    try:
        pf.unlink()  # 已落库，删载荷防重复 append
    except OSError:
        pass
    return (
        True,
        # v2.25：返工轮正文禁全文重述（judge 读 evidence 不读正文）——在模型
        # 写正文前的决策点指路增量总结（tail_volume u:3 子4 五轮重述烧 ~3.7k out）。
        f"✓ 已落库 sub_step={cur} -> {path}（可输出 ### STEP_DONE: {cur} 并 end_turn；"
        "载荷文件已删除——若被 block 返工须重新 append-trace --scaffold；"
        "返工轮正文只写增量总结=本轮变更条目+总数，禁全文重述——"
        "judge 读 evidence 不读正文，完整集由读回确认步呈现）",
    )


def redteam_prompt(project_root: Path, name: str) -> str | None:
    """组装子4 红队子代理 prompt（证据+纪律归脚本，Agent 调用归模型）。

    证据取 read_evidence_for_step(≤3)：含子1-3 最新 trace、**不含子4 结论**
    （只给证据不给结论）。无子3 trace -> None（调用方 exit 1 暴露：
    红队无证据可审，先回补子3）。
    minor_stage 限定 ProblemContext（本函数是 understand:1 子4 专属；
    不限定会读到 GoalsAndValue 的同号子步骤 trace——跨节点串号）。
    """
    pc_minor = _NODES["understand:1"].minor_key
    if not sub_step_has_trace(project_root, name, 3, pc_minor):
        return None
    evidence = read_evidence_for_step(project_root, name, 3, pc_minor)
    if evidence is None:
        return None
    return (
        "你是独立红队评审。一个工作流正在对若干原子问题做取证后裁决，"
        "你是独立第二视角——任务是对证据做点查并尝试找出推翻空间，"
        "不是附和既有方向。\n\n"
        "【证据（双向取证留痕，含 URL / file:line 指针）】\n"
        f"{evidence}\n\n"
        "【纪律】\n"
        "1. 点查以 Read 工具为主：证据里引用的文件路径用 Read 复查；"
        "你的会话里 Glob/Grep/codegraph 可能不存在、Bash 会被围栏拒绝，都不要试。\n"
        "2. 单层：禁止再 spawn 子代理。\n"
        "3. 不做系统性重新取证：只点查验证；证据不足时下「证据不足」verdict 并指明缺哪条。\n"
        "4. 对每个原子问题给四态 verdict（证实/证伪/部分成立/证据不足）"
        "+ 推理链（引用证据指针）+ 置信度。\n\n"
        "【输出】逐原子问题：verdict / 推理链 / 置信度。"
    )


def fetch_prompt(project_root: Path, name: str) -> str | None:
    """组装子3 外部取证子代理 prompt（纪律+命令模板归脚本，Agent 调用归模型）。

    v2.38（2026-08-01 tail_volume u:1 子3 审计）：子3 是主会话工具密度大户
    （实测 46 msgs/26 tool calls/6.2M cache read），curl 原始输出全堆主上下文；
    且外部源实测 ~40% 失败，根因逐层定位——命令模板逐字来自当日诊断：
    arXiv 用 http+无 UA 静默空（https+UA 已验证返回）、GitHub code search
    模型没带认证头 401（带 $GITHUB_TOKEN 已验证）、WebFetch 域验证被本网络
    全挂（环境性弃用）、SE 页面 403（API filter=withbody 替代已验证）。
    原子清单取子1-2 最新 trace（ProblemContext 限定，跨节点串号同
    redteam_prompt）。无子2 trace -> None（调用方 exit 1 暴露：无可取证
    对象，先回补子2）。
    v2.39（2026-08-01 tail_volume u:1 子3 复盘）：纪律 8/9——摄取截断 +
    轮次上限。实证：Q4 取证 agent 20 轮 curl 把上下文从 29k 撑到 60k，
    遇 provider 空响应重试 26 次烧掉 1.19M input（占其总 input 90%）——
    上下文越胖每轮越慢、重试越贵；轮次无上限时换同义词重试边际收益递减
    （Q4 最终被证伪，证伪是合法产出但不该付无上限探索成本）。
    v2.40（designs/fetch-depth-tiering-design.md）：按子2 atomic_questions
    标称档分派执行参数——full 档五层源双向（现状）；light 档 ≤2 层源 /
    ≤4 curl / 单向锚点（数值事实类点查）；none 档不进骨架（仅内查）。
    无 atomic_questions（v2.40 前实例）-> 全按 full 档（legacy 行为）。
    """
    pc_minor = _NODES["understand:1"].minor_key
    if not sub_step_has_trace(project_root, name, 2, pc_minor):
        return None
    evidence = read_evidence_for_step(project_root, name, 2, pc_minor)
    if evidence is None:
        return None
    # v2.40：标称档预填进 claim 补充区——[tier=X] 标记随骨架进 agent
    # transcript（台账 _subagent_retry_stats 按此提取 per-agent 档与轮次）。
    aq = _load_atomic_questions(project_root, name)
    claim_seg = ""
    if aq is not None:
        fetch_atoms = []
        none_atoms = []
        for i, it in enumerate(aq, 1):
            if not isinstance(it, dict):
                continue
            q = str(it.get("q", "")).strip()
            if it.get("tier") == "none":
                none_atoms.append(f"原子{i}「{q}」")
            else:
                note = (
                    "（light 档：调用方在 claim 区另指定 ≤2 层源）"
                    if it.get("tier") == "light"
                    else ""
                )
                fetch_atoms.append(f"- 原子{i} [tier={it.get('tier')}]：{q}{note}")
        if not fetch_atoms:
            return (
                "全部原子问题为 none 档（仅内查）——无需派发外部取证 agent："
                "直接做③内部仓库层，trace 注明「全 none 档未派发」。"
            )
        claim_seg = (
            "\n已分档原子清单（子2 标称档，禁降档——标 full 必须按 full 参数跑）：\n"
            + "\n".join(fetch_atoms)
        )
        if none_atoms:
            claim_seg += "\nnone 档原子（仅内查，禁为其派发取证 agent）：" + "；".join(
                none_atoms
            )
    return (
        "你是外部取证子代理。一个工作流正在对若干原子问题做双向取证——"
        "你只负责外部源取证并回蒸馏报告，不裁决、不写 evidence。\n\n"
        "【原子问题与背景（子1-2 trace）】\n"
        f"{evidence}\n\n"
        "【纪律】\n"
        "1. 单层：禁止再 spawn 子代理。\n"
        "2. 不写 evidence、不裁决（裁决归后续质检步）——只产出蒸馏取证报告。\n"
        "3. 禁 WebFetch（本环境域验证全挂）；禁 tavily_search/WebSearch。\n"
        "4. 层源范围与轮次上限按【分档执行参数】（每原子标称档见 claim 补充区 "
        "[tier=X]）；失败/空结果标「未取证+原因」是合法留痕，禁止补编。\n"
        "5. GitHub API 401 → 直接标「未取证+未认证」——禁止探查凭证"
        "（扫 env/配置文件找 token 是红线，必被安全分类器拦截）。\n"
        "6. 内部仓库层（codegraph/Read 仓内文件）不归你，主会话自查。\n"
        "7. 所有 curl 带 -m 25；失败重试一次再标未取证。\n"
        "8. 摄取截断：凡不经 jq 收窄的 curl，末尾一律接 `| head -c 6000`；"
        "超大响应先 -o /tmp/fetch_<层>_<n>.out 落盘再 head/jq 读。"
        "全量响应禁直接进你的上下文——单条 API 响应可达数万 token，"
        "上下文越胖每轮请求越慢、空响应重试越贵。\n"
        "9. 轮次上限按档：full ≤12 / light ≤4 次 curl（含重试）。超限未收敛 = "
        "带现有结果返回并如实标注「部分取证+轮次用尽」——禁止换同义查询词"
        "无限重试（边际收益递减；证伪方向取到 1-2 条强反证即可收）。\n\n"
        "【分档执行参数（按 claim 补充区每原子 [tier=X] 执行；禁降档——"
        "标 full 的原子必须按 full 参数跑）】\n"
        "- tier=full：五层源逐层尝试；≤12 curl；双向取证（反证查询先、支持证据后）；"
        "报告 ≤120 行/原子 + 五层状态表（每层一行：证据指针 或 未取证+原因）。\n"
        "- tier=light：只跑 claim 区为该原子指定的 ≤2 层源；≤4 curl；单向锚点"
        "（不双向、免五层状态表）——报告 ≤60 行：锚点值 + 来源 URL + "
        "一句量级对比。锚点不收敛/来源冲突 → 报告末尾标「建议升档 full + 理由」"
        "即返回，不自行加码轮次。\n\n"
        "【命令模板（本机验证可用，逐字使用，只换查询词）】\n"
        '- 学术·OpenAlex：curl -sS -m 25 "https://api.openalex.org/works?search=<q>&per_page=3"\n'
        "- 学术·arXiv（必须 https + UA，http/无 UA 静默空返回）："
        'curl -sS -m 25 -A "Mozilla/5.0 (research)" '
        '"https://export.arxiv.org/api/query?search_query=all:%22<q>%22&max_results=3"\n'
        '- 社区·StackExchange：先 curl -sS -m 25 "https://api.stackexchange.com/2.3/search/advanced?'
        'order=desc&sort=relevance&q=<q>&site=quant&pagesize=3"；'
        "取正文用 /questions/<id>/answers?order=desc&sort=votes&site=quant&filter=withbody"
        "（页面 HTML 直抓 403——正文一律走 API withbody，禁抓页面）\n"
        '- 社区·HN：curl -sS -m 25 "https://hn.algolia.com/api/v1/search?query=<q>&tags=story&hitsPerPage=3"'
        "（空结果常见，标「未取证+无相关讨论」即可）\n"
        "- 开源·GitHub（认证头必须，否则 401）：curl -sS -m 25 "
        '-H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" '
        '"https://api.github.com/search/code?q=%22<q>%22&per_page=3"\n'
        "- 定点网页：curl -sS -m 25 直抓上述层发现的 URL（403/超时→标未取证+原因）\n"
        "- 提取用 jq（不要手写 python 一行流）：jq -r '.items[]?.link' / jq -r '.items[]?.title'\n\n"
        "【返回契约（蒸馏——原始 curl 输出留在你的上下文，只回 distilled）】\n"
        "逐原子问题（≤120 行/原子）：\n"
        "1. 反证查询（先）：逐条「查询词 → 源层 → 一句结论 + URL 指针」；\n"
        "2. 支持证据（后）：同构逐条；\n"
        "3. 五层状态表：学术（OpenAlex/arXiv)/社区（SE/HN)/开源（GitHub)/定点网页"
        "——每层一行：证据指针 或 未取证+原因。\n"
        "报告正文即留痕，反证段必须先于支持段（时序从文本直接可读）。\n"
        "light 档原子免上述格式，按【分档执行参数】light 契约返回（≤60 行）。\n\n"
        "【claim 补充区】\n"
        "（以下为调用方逐原子填写的可检验 claim 与证实/证伪标准——按 claim 谓词"
        "取证，证据须直接针对谓词，不泛泛取行业常识）" + claim_seg
    )


# ---------- CLI（design §8.1;供 dl-cmd.sh / 手动覆盖调用）----------


def _cmd_status(project_root: Path, name: str) -> int:
    state = load_state(project_root, name)
    if state is None:
        print(f"✗ 工作流 {name} 的 state.json 缺失", file=sys.stderr)
        return 1
    state = normalize_state(state)
    phase = state["phase"]
    node = get_node(phase, state["sub_index"])
    st = state["sub_total"]
    sub_line = ""
    if st > 0:
        sub_line = f" | 子阶段: {node.label} [{state['sub_index']}/{st}]"
    print(f"═══ 工作流: {name} ═══")
    print(
        f"  阶段:  {PHASE_LABELS.get(phase, phase)} [{state['index']}/{len(PHASES)}]{sub_line}"
    )
    print(f"  节点:  {state['node']}")
    print(f"  闸门:  {state['gate']}")
    print(f"  技能:  {node.skill or '(靠行为约束)'}")
    print(f"  重试:  {state['node_attempts']}")
    print(f"  分支:  {state.get('branch', '?')}")
    return 0


def _cmd_current(project_root: Path, name: str) -> int:
    state = load_state(project_root, name)
    if state is None:
        print(f"✗ 工作流 {name} 的 state.json 缺失", file=sys.stderr)
        return 1
    state = normalize_state(state)
    node = get_node(state["phase"], state["sub_index"])
    out = {
        "node": state["node"],
        "label": node.label,
        "phase": node.phase,
        "sub": node.sub,
        "skill": node.skill,
        "artifact": node.artifact,
        "gate_mech": node.gate_mech.value,
        "gate_rubric": node.gate_rubric,
        "advance": node.advance,
        "sub_step_index": state.get("sub_step_index", 0),  # §orchestration v2
        "sub_steps": (
            [
                {
                    "n": i,
                    "kind": s.kind,
                    "ref": s.ref,
                    "short": s.short,
                    "purpose": s.purpose,
                    "input": s.input,
                    "record": s.record,
                    "gate": s.gate,
                }
                for i, s in enumerate(node.sub_steps, 1)
            ]
            if node.sub_steps
            else None
        ),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _cmd_progress(project_root: Path, name: str) -> int:
    """输出当前阶段真值（供 dl-cmd.sh status 贴给模型取数据，非展示）。

    §orchestration v2：进度树**展示**已弃用（phase-rules 行 14：只靠 TUI TaskList）。
    但模型需 status 取「现在在第几步」真值（state.json 权威源，TaskList 模型自维可能不准）。
    故本命令只输出当前阶段/子阶段/子步骤序号 + 当前子步骤 purpose 一行数据，
    不输出全 5 阶段树（树是展示，归 TaskList）。
    """
    state = load_state(project_root, name)
    if state is None:
        print(f"✗ 工作流 {name} 的 state.json 缺失", file=sys.stderr)
        return 1
    state = normalize_state(state)
    cur_phase = state["phase"]
    cur_idx = phase_index(cur_phase)
    cur_sub = state["sub_index"]
    cur_sub_total = sub_total(cur_phase)
    cur_step = state.get("sub_step_index", 0)

    line = f"当前: {PHASE_LABELS.get(cur_phase, cur_phase)} [{cur_idx}/{len(PHASES)}]"
    if cur_sub_total > 0:
        slabel = (
            subphase_labels(cur_phase)[cur_sub - 1]
            if 1 <= cur_sub <= cur_sub_total
            else "?"
        )
        line += f" | 子阶段: {slabel} [{cur_sub}/{cur_sub_total}]"
        node = get_node(cur_phase, cur_sub)
        if node.sub_steps and 1 <= cur_step <= len(node.sub_steps):
            stp = node.sub_steps[cur_step - 1]
            gate_tag = "" if stp.gate else "（自动过）"
            line += (
                f" | 子步骤: {cur_step}/{len(node.sub_steps)} "
                f"[{stp.kind}:{stp.ref}] {stp.purpose}{gate_tag}"
            )
    print(line)
    return 0


def _cmd_advance(project_root: Path, name: str) -> int:
    state = advance_state(project_root, name)
    node = get_node(state["phase"], state["sub_index"])
    print(f"▸ 推进到节点 {state['node']}")
    print(f"  {PHASE_LABELS.get(state['phase'], state['phase'])} · {node.label}")
    return 0


def _cmd_meta() -> int:
    """输出全部静态常量 JSON（供 dl-lib.sh 启动时缓存,删 bash 侧副本）。

    bash 侧不再各持 PHASES/GATED_AFTER/SUBPHASES 副本,source 本输出一次缓存。
    """
    out = {
        "phases": list(PHASES),
        "phase_labels": PHASE_LABELS,
        "gated_after": list(GATED_AFTER),
        "subphases": {p: subphase_labels(p) for p in PHASES},
        "sub_total": {p: sub_total(p) for p in PHASES},
        "settings_template_version": SETTINGS_TEMPLATE_VERSION,
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dl_flow_engine",
        description="工作流编排内核（被 hook 咨询;不当主进程）",
    )
    parser.add_argument(
        "cmd",
        choices=[
            "status",
            "current",
            "advance",
            "progress",
            "meta",
            "step-pass",
            "state-reset",
            "subgate-pass",
            "fence",
            "dispute",
            "render-phase-rules",
            "append-trace",
            "redteam-prompt",
            "fetch-prompt",
            "render-artifact",
            "render-readback",
        ],
    )
    parser.add_argument(
        "name",
        nargs="?",
        help="工作流名（不填则从 cwd 反查）；render-phase-rules 时为 phase-rules 模板路径",
    )
    parser.add_argument(
        "value",
        nargs="?",
        help="fence 的值（on|off）/ state-reset 的回退目标 / render-artifact 的产物名（understand.md|plan.md）",
    )
    parser.add_argument("--cwd", help="覆盖 cwd（默认进程 cwd）")
    parser.add_argument(
        "--from-file",
        help="append-trace 的载荷文件路径（.md 分节标记文本[推荐，零转义] 或 .json）",
    )
    parser.add_argument(
        "--scaffold",
        action="store_true",
        help="append-trace：生成当前子步骤 .md 载荷骨架到 evidence/.trace-payload-<name>.md 并打印路径（格式脚本管，模型只填「待填」）",
    )
    parser.add_argument(
        "--slug",
        help="render-artifact design.md 的文件名段（designs/<slug>-design.md）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="render-artifact design.md：允许覆盖已存在的设计稿（state-reset 重跑场景）",
    )
    parser.add_argument(
        "--ingest-agent",
        metavar="TASK_ID",
        help="append-trace：把子代理 agent-<TASK_ID> 的报告原文收录进 .md 载荷 qa 节（脚本提取，禁手工粘贴）",
    )
    parser.add_argument(
        "--out",
        action="store_true",
        help="fetch-prompt：骨架落盘 .claude/workflows/<name>/fetch-prompt-skeleton.md 并打印路径（替代 stdout）",
    )
    # parse_intermixed_args（v2.67）：argparse 已知缺陷——nargs='?' 位置参数
    # （name/value）前隔 optional 时 parse_args 报 unrecognized arguments
    # （`append-trace --scaffold <name>` 必败，2026-08-03 tail_volume u:1 实证，
    # 系统 deny 文案教的正是这个写法）。intermixed 下全部参数序可解析；
    # 本 parser 无 subparsers/REMAINDER，兼容。
    args = parser.parse_intermixed_args(argv)

    # meta 是静态常量,不需要 git repo / name。
    if args.cmd == "meta":
        return _cmd_meta()

    # render-phase-rules（P1）：渲染 phase-rules 模板的 GENERATED 段到 stdout。
    # 不需要 git repo / 工作流名（dl-launch.sh 启动时调用，渲染失败非零退出 = 中止启动）。
    if args.cmd == "render-phase-rules":
        if not args.name:
            print("✗ 用法: render-phase-rules <phase-rules 模板路径>", file=sys.stderr)
            return 1
        try:
            template_text = Path(args.name).read_text(encoding="utf-8")
        except OSError as e:
            print(f"✗ 读模板失败：{e}", file=sys.stderr)
            return 1
        try:
            sys.stdout.write(render_phase_rules(template_text))
        except (KeyError, ValueError) as e:
            print(f"✗ 渲染失败：{e}", file=sys.stderr)
            return 1
        return 0

    cwd = args.cwd or str(Path.cwd())
    project_root = resolve_project_root(cwd)
    if project_root is None:
        print("✗ 不在 git 仓库内", file=sys.stderr)
        return 1
    name = args.name or resolve_workflow_name(cwd)
    if not name:
        print(
            "✗ 不在工作流 worktree 内（cwd 不含 .claude/worktrees/<name>）,且未给 name",
            file=sys.stderr,
        )
        return 1

    if args.cmd == "append-trace":
        if args.scaffold:
            ok, msg = scaffold_payload(project_root, name)
            print(msg, file=sys.stdout if ok else sys.stderr)
            return 0 if ok else 1
        if args.ingest_agent:
            ok, msg = ingest_agent_report(project_root, name, args.ingest_agent)
            print(msg, file=sys.stdout if ok else sys.stderr)
            return 0 if ok else 1
        if not args.from_file:
            print("✗ 用法: append-trace [name] --from-file <载荷路径>", file=sys.stderr)
            return 1
        ok, msg = append_trace(project_root, name, args.from_file)
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if args.cmd == "redteam-prompt":
        prompt = redteam_prompt(project_root, name)
        if prompt is None:
            print(
                "✗ 无子3 双向取证 trace——红队无证据可审，先回补子3",
                file=sys.stderr,
            )
            return 1
        sys.stdout.write(prompt + "\n")
        return 0
    if args.cmd == "fetch-prompt":
        prompt = fetch_prompt(project_root, name)
        if prompt is None:
            print(
                "✗ 无子2 拆解深挖 trace——无可取证的原子清单，先回补子2",
                file=sys.stderr,
            )
            return 1
        # v2.42 --out：骨架落盘 per-workflow 目录（归属钉死，与 state.json 同
        # 生命周期）——此前落盘路径由模型自选，tail_volume 实例选了共享
        # evidence/ 通用文件名：无归属、下一轮覆盖、残留旧 trace 误导。
        if args.out:
            out_path = (
                project_root
                / ".claude"
                / "workflows"
                / name
                / "fetch-prompt-skeleton.md"
            )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(prompt + "\n", encoding="utf-8")
            print(out_path)
            return 0
        sys.stdout.write(prompt + "\n")
        return 0
    if args.cmd == "render-artifact":
        if not args.value:
            print(
                "✗ 用法: render-artifact [name] <understand.md|plan.md|design.md>"
                "（design.md 须 --slug <主题>）",
                file=sys.stderr,
            )
            return 1
        ok, msg = render_artifact(
            project_root, name, args.value, slug=args.slug, force=args.force
        )
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if args.cmd == "render-readback":
        ok, msg = render_readback(project_root, name)
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if args.cmd == "status":
        return _cmd_status(project_root, name)
    if args.cmd == "current":
        return _cmd_current(project_root, name)
    if args.cmd == "advance":
        return _cmd_advance(project_root, name)
    if args.cmd == "progress":
        return _cmd_progress(project_root, name)
    if args.cmd == "step-pass":
        ok, msg = force_pass_sub_step(project_root, name, cwd)
        print(("✓ " if ok else "✗ ") + msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if args.cmd == "subgate-pass":
        ok, msg = release_subgate(project_root, name, cwd)
        print(("✓ " if ok else "✗ ") + msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if args.cmd == "dispute":
        if not args.value:
            print("✗ 用法: dispute <name> <缺陷论证>", file=sys.stderr)
            return 1
        ok, msg = write_rubric_dispute(project_root, name, args.value)
        print(("✓ " if ok else "✗ ") + msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if args.cmd == "state-reset":
        if not args.value:
            print(
                "✗ 用法: state-reset <name> <n | phase:minor[:step]>"
                "（含目标 step 作废，回到 step-1 已完成）",
                file=sys.stderr,
            )
            return 1
        ok, msg = reset_state(project_root, name, args.value)
        print(("✓ " if ok else "✗ ") + msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if args.cmd == "fence":
        if args.value not in ("on", "off"):
            print("✗ 用法: fence <name> on|off", file=sys.stderr)
            return 1
        state = load_state(project_root, name)
        if state is None:
            print(f"✗ 工作流 {name} 的 state.json 缺失", file=sys.stderr)
            return 1
        state = normalize_state(state)
        state["enforce_step_fence"] = args.value == "on"
        save_state(project_root, name, state)
        print(
            f"✓ 子步骤围栏（S10）已{'开启' if args.value == 'on' else '关闭（回文案约束）'}"
            "（阶段写围栏 S11 是系统硬约束，不受此开关影响）"
        )
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
