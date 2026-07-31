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
    GATED_AFTER,
    PHASES,
    PHASE_LABELS,
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
        ok, reason = run_judge(
            step.gate,
            f"{node.label} · 子步骤{cur}",
            "",
            artifact_content=artifact,
            prior_verdicts=priors,
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
        "仅编排工具可用（AskUserQuestion / Skill / Task* / Read / Grep / Glob / "
        f"codegraph / dl-cmd / 写 evidence{extra}）；"
        "为用户任务探查（Bash/WebFetch/WebSearch/Agent 等）会被 deny 指回本步——"
        "「先回答用户问题再走编排」不存在，当前子步骤就是你要做的事。"
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
        '{"pass": true/false, "reason": "不满足时写缺什么;满足时留空"}\n\n'
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
    if prior_verdicts:
        prompt += "\n【前轮判词（同一子步骤，时间序）】\n" + "\n".join(
            f"{i}. {r}" for i, r in enumerate(prior_verdicts, 1)
        )
        prompt += (
            "\n一致性要求（判据未变，前轮判词=裁量先例）："
            "①前轮点名的问题已修复的方向，不得翻案判回；"
            "②前轮 trace 中已存在且未被判违规的写法，不得仅因裁量收紧而新判违规；"
            "③本轮判 block 须在 reason 引用判据的具体条款；"
            "④判 block 时 reason 还须附 1 个正确改写范例——把被判内容的一条"
            "改成合规形式（指模式不指实例位置，模型下轮照模式修，不打地鼠）。"
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
    """
    return _GENERATED_RE.sub(
        lambda m: render_substeps_section(m.group(1)), template_text
    )


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

# 条目编号模式：in[1]/in[1a-强正]/out[A]（范围项）与 C1.1/C3.4（约束项）。
_ID_RE = re.compile(r"[A-Za-z]+\[[\w-]+\]|[A-Z]\d+\.\d+")


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
            parts.extend(str(item.get(k) or "") for k in ("text", "type_label", "boundary"))
    return set(_ID_RE.findall(" ".join(parts)))


def _source_step_index(step, cur: int) -> int | None:
    """传导源步号：step.input 声明（"step3.xxx"）优先，缺省上一步。"""
    m = re.search(r"step(\d+)", step.input or "")
    if m:
        return int(m.group(1))
    return cur - 1 if cur > 1 else None


def payload_format_hint(step) -> list[str]:
    """注入用载荷示例行（按步 record_format；单源，phase hook 直接渲染）。"""
    if getattr(step, "record_format", "qa") == "statements":
        return [
            '   {"purpose":"<该步目的>","statements":[{"text":"<单句陈述>",'
            '"type_label":"<类型标签>","boundary":"<边界/实现指针>"}]}'
            "（逐项一个对象；text 只许 outcome-level——实现侧名词/file:line "
            "只能进 boundary，text 会被机械扫描打回）",
            '   ✓ 正例："statements":[{"text":"因子卡片年化数字允许被更新",'
            '"type_label":"in","boundary":"实现指针：web_ui/templates/_macros.html"}]',
            '   ✗ 反例（必拒）：text 含文件名/类名（挪 boundary）；'
            "或照抄 `<...>` 占位符字面",
        ]
    return [
        '   {"purpose":"<该步目的>","qa":[{"q":"<q1>","a":"<a1>"}]}'
        "（一问一答配对成对象——不对齐在结构上不可表示）",
        '   ✓ 正例："qa":[{"q":"who=当前提问者身份？",'
        '"a":"用户原话：「我是唯一维护者」（本会话）"}]',
        '   ✗ 反例（必 block）："qa":[{"q":"理解问题","a":"已理解"}]'
        "（汇总声明非记录）；或照抄 `<...>` 占位符字面",
    ]


def append_trace(project_root: Path, name: str, payload_file: str) -> tuple[bool, str]:
    """载荷（purpose + qa 配对，兼容旧 q/a 平行数组）+ state 结构字段 -> 校验 -> 单行 skill-trace append。

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
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        return False, f"载荷不是合法 JSON：{e}（载荷只需普通 JSON，Write 原样写即可）"
    if not isinstance(payload, dict):
        return False, '载荷须是 JSON 对象：{"purpose":..., "qa":[{"q":..., "a":...}]}'
    leaked = [k for k in _TRACE_STRUCT_FIELDS if k in payload]
    if leaked:
        return False, (
            f"载荷含结构字段 {leaked}——这些由脚本从 state 自动填，载荷里不要写"
            "（只留 purpose 与 qa 两个内容字段）"
        )
    purpose = payload.get("purpose")
    if not isinstance(purpose, str) or not purpose.strip():
        return False, "purpose 须为非空字符串"
    if getattr(step, "record_format", "qa") == "statements":
        # v2.27 statements 结构化载荷（清单型产出步）：三字段校验 +
        # 机械预检（方案名词扫描 + 源步 ID 传导覆盖）——词形判据下沉机械层。
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
                    f"{it['text']} {it['type_label']} {it['boundary']}"
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
        if qa is not None:
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
                    return False, f'qa[{i}] 须为含非空 q 与 a 的对象（{{"q":..., "a":...}}）'
            q = [item["q"] for item in qa]
            a = [item["a"] for item in qa]
        else:
            # 旧 q/a 平行数组：保留兼容；长度不齐时给无配对项索引+内容头
            # （surgical 修，不整篇盲重写），并指路 qa 配对格式。
            q, a = payload.get("q"), payload.get("a")
            for field, val in (("q", q), ("a", a)):
                if (
                    not isinstance(val, list)
                    or not val
                    or not all(isinstance(x, str) and x.strip() for x in val)
                ):
                    return False, f"{field} 须为非空字符串数组（单问单答也用数组包一层）"
            if len(q) != len(a):
                longer, lname = (q, "q") if len(q) > len(a) else (a, "a")
                extras = [
                    f"{lname}[{i}]=「{x[:30]}{'…' if len(x) > 30 else ''}」"
                    for i, x in enumerate(longer)
                    if i >= min(len(q), len(a))
                ]
                shown = "；".join(extras[:3]) + ("；…" if len(extras) > 3 else "")
                return False, (
                    f"q/a 长度不齐（q={len(q)} a={len(a)}）：一问一答按序对齐。"
                    f"无配对项：{shown}。"
                    '逐条修或改用 qa 配对格式 {"qa":[{"q":...,"a":...},...]}（不对齐不可表示）'
                )
        content_fields = {"q": q, "a": a}

    record = {
        "kind": "skill-trace",
        "major_stage": state["phase"].capitalize(),
        "minor_stage": node.minor_key,
        "sub_step": cur,
        "skill": step.ref,
        "purpose": purpose,
        **content_fields,
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
        ],
    )
    parser.add_argument(
        "name",
        nargs="?",
        help="工作流名（不填则从 cwd 反查）；render-phase-rules 时为 phase-rules 模板路径",
    )
    parser.add_argument(
        "value", nargs="?", help="fence 的值（on|off）/ state-reset 的回退目标"
    )
    parser.add_argument("--cwd", help="覆盖 cwd（默认进程 cwd）")
    parser.add_argument(
        "--from-file", help="append-trace 的载荷文件路径（Write 写的 purpose/qa JSON）"
    )
    args = parser.parse_args(argv)

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
