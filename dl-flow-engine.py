#!/usr/bin/env python3
"""
dl-flow-engine - 工作流编排内核（唯一真源）。

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

CLI（供 wf-cmd.sh / 手动覆盖调用）：
  python3 dl-flow-engine.py status  <name>   查当前节点
  python3 dl-flow-engine.py current <name>   输出当前节点定义（json）
  python3 dl-flow-engine.py advance <name>    推进到下一节点（写 state.json）
"""

from __future__ import annotations

import argparse
import enum
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---------- 节点树定义（design §3） ----------
#
# 节点标识：<phase>:<sub_index>。sub_index=0 表示无子节点的整阶段。
# 例 "understand:1" = understand 大阶段第 1 子阶段；"execute:0" = execute 整阶段。
#
# 声明式：加节点/改审据只改数据不改逻辑。维护性兑现 design §0.2 诉求。


class GateMech(enum.Enum):
    """机械门类型（py 规则判定,快、便宜、无幻觉）。design §5。"""

    NONE = "none"  # 无机械门（子阶段间自动推进用）
    ARTIFACT_EXISTS = "artifact_exists"  # 产物文件存在
    TEST_PASS = "test_pass"  # pytest 通过


@dataclass(frozen=True)
class Node:
    """单个节点定义。"""

    label: str  # 显示名（中文）
    phase: str  # 所属大阶段（英文标识）
    sub: int  # 子阶段序号（0=整阶段无子节点）
    skill: (
        str | None
    )  # 该节点应载的 skill（None=靠行为约束）;engine 声明,hook 注入,模型 invoke
    artifact: str | None  # 产物标识（文件名或描述;None=无独立产物）
    gate_mech: GateMech  # 机械门类型
    gate_rubric: str | None  # 语义审据（judge prompt）;None=不跑 judge
    advance: str  # 推进方式："sub"=推进 sub_index, "phase"=推进 phase, "done"=终结


# 节点表。<node_id> -> Node。node_id = f"{phase}:{sub}"。
# 闸门 GATED_AFTER：这些 phase 的末节点完成需用户 /wf gate 放行才进下一 phase。
#   继承现有 workflow_advance.py:39 GATED_AFTER 语义,收口到 engine 一份。
#   用 tuple 保序（显示用自然顺序 understand,plan）;is_gated_after 成员判定 O(n) 可接受（5 阶段）。
GATED_AFTER: tuple[str, ...] = ("understand", "plan")

_NODES: dict[str, Node] = {
    # ---------- understand（含 4 子阶段;design §3 / workflow_advance.py:47 SUBPHASES 同源）----------
    "understand:1": Node(
        label="理解问题和背景",
        phase="understand",
        sub=1,
        skill="define-problem",  # §skill-injection-link:载 define-problem(逼问问题定义/验真/钉约束/搜证据),契合 sub1「验真问题是否真实」
        artifact=None,
        gate_mech=GateMech.NONE,
        gate_rubric=None,
        advance="sub",  # 子阶段间自动推进,无门无审（快流转）
    ),
    "understand:2": Node(
        label="明确目标和价值",
        phase="understand",
        sub=2,
        skill=None,
        artifact=None,
        gate_mech=GateMech.NONE,
        gate_rubric=None,
        advance="sub",
    ),
    "understand:3": Node(
        label="确定范围与约束",
        phase="understand",
        sub=3,
        skill=None,
        artifact=None,
        gate_mech=GateMech.NONE,
        gate_rubric=None,
        advance="sub",
    ),
    "understand:4": Node(
        label="定义成功标准和验收方式",
        phase="understand",
        sub=4,
        skill=None,
        artifact="understand.md",  # 末子阶段写产物
        gate_mech=GateMech.ARTIFACT_EXISTS,
        gate_rubric="对照注入的真实问题：①是否重述真实问题(非字面) ②边界 in/out-scope ③可验证成功标准。缺任一 block。",
        advance="phase",  # 末子阶段 -> 推进到 plan（过 understand->plan 闸门）
    ),
    # ---------- plan ----------
    "plan:0": Node(
        label="生成执行计划",
        phase="plan",
        sub=0,
        skill="superpowers:using-superpowers",
        artifact="plan.md",
        gate_mech=GateMech.ARTIFACT_EXISTS,
        gate_rubric="plan 是否针对真实问题设计：①步骤可执行 ②验证方法明确 ③守 H8/H9。",
        advance="phase",  # -> execute（过 plan->execute 闸门）
    ),
    # ---------- execute ----------
    "execute:0": Node(
        label="执行",
        phase="execute",
        sub=0,
        skill=None,
        artifact="代码+commit+测试通过",
        gate_mech=GateMech.TEST_PASS,
        gate_rubric="实现是否真正执行了 plan.md：对照 plan 步骤逐条核,偏离需有理由。",
        advance="phase",  # 自动到 review（无闸门）
    ),
    # ---------- review ----------
    "review:0": Node(
        label="审核结果",
        phase="review",
        sub=0,
        skill=None,
        artifact="review.md",
        gate_mech=GateMech.ARTIFACT_EXISTS,
        gate_rubric="对照 understand.md 真实问题 + 成功标准,判定 solved/partial/not,附 file:line 证据。",
        advance="phase",
    ),
    # ---------- evolution ----------
    "evolution:0": Node(
        label="进化",
        phase="evolution",
        sub=0,
        skill=None,
        artifact="evolution.md",
        gate_mech=GateMech.ARTIFACT_EXISTS,
        gate_rubric="是否沉淀非显然可复用经验（memory/skill/design）。",
        advance="done",
    ),
}


# 大阶段顺序（英文标识;与 wf-lib.sh:37 WF_PHASES 同源,收口到 engine 一份）。
PHASES = ("understand", "plan", "execute", "review", "evolution")

# 大阶段中文显示名（仅显示;逻辑层用英文标识）。
PHASE_LABELS: dict[str, str] = {
    "understand": "理解和求证问题",
    "plan": "生成执行计划",
    "execute": "执行",
    "review": "审核结果",
    "evolution": "进化",
}


# ---------- 节点推导（design §3 / §4 node 字段）----------


def node_id(phase: str, sub: int) -> str:
    """phase + sub -> node_id。sub=0 表示整阶段无子节点。"""
    return f"{phase}:{sub}"


def current_node_id(phase: str, sub_index: int) -> str:
    """phase + state.sub_index -> 当前 node_id。

    无子阶段 phase 的 sub_index=0 -> 整阶段节点 "<phase>:0"。
    """
    return node_id(phase, sub_index)


def get_node(phase: str, sub: int) -> Node:
    """取节点定义。非法 phase/sub 报错暴露（守 no silent fallback：不猜）。"""
    nid = node_id(phase, sub)
    if nid not in _NODES:
        raise KeyError(f"未知节点：{nid}（phase={phase} sub={sub}）")
    return _NODES[nid]


# 各 phase 子阶段数（0=无子节点）。从 _NODES 推导（单源,不再持 _SUB_TOTAL 副本）。
def sub_total(phase: str) -> int:
    """phase -> 子阶段数（0=无子节点）。"""
    n = 0
    while f"{phase}:{n + 1}" in _NODES:
        n += 1
    return n


def subphase_labels(phase: str) -> list[str]:
    """phase -> 子阶段标签列表（按 sub 序号;空 phase 返回 []）。

    从 _NODES 推导（单源）。收口 understand 4 子阶段标签,
    供 workflow_phase.py 注入子阶段块（不再各持 SUBPHASES 副本）。
    """
    labels: list[str] = []
    i = 1
    while f"{phase}:{i}" in _NODES:
        labels.append(_NODES[f"{phase}:{i}"].label)
        i += 1
    return labels


def phase_index(phase: str) -> int:
    """phase -> 序号（1-based）。非法报错。"""
    if phase not in PHASES:
        raise KeyError(f"未知阶段：{phase}")
    return PHASES.index(phase) + 1


def next_phase(phase: str) -> str | None:
    """下一 phase（无下一=终结返回 None）。"""
    idx = PHASES.index(phase)
    if idx + 1 >= len(PHASES):
        return None
    return PHASES[idx + 1]


def is_gated_after(phase: str) -> bool:
    """该 phase 完成后进下一 phase 需用户 /wf gate 放行。"""
    return phase in GATED_AFTER


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
# schema：沿用现有 wf-lib.sh:142 结构 + 新增 node / node_attempts 字段。
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
    """补齐新字段（node / node_attempts）,旧 state 向后兼容。

    守 no silent fallback：node 字段缺失时按 phase+sub 推导补默认,不静默用错值。
    推导值与显式 node 不一致时**报错暴露**（防两者失同步）。
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


def write_gate_verdict(
    project_root: Path,
    name: str,
    node: Node,
    attempts: int,
    cwd: str,
    via: str = "auto-stop",
) -> bool:
    """gate pass 时写一笔裁决记录到 evidence/<name>.jsonl。

    记录：节点 + gate=passed + rubric（审据;None=仅机械过）+ attempts（重试次数）+
    gate_mech（机械类型）+ ts + commit_sha（防腐锚点）。
    返回 True=写入成功;False=写失败（no silent fallback：失败留痕由调用方 log,不阻断）。
    """
    record = {
        "kind": "gate",
        "node": node_id(node.phase, node.sub),
        "phase": node.phase,
        "sub": node.sub,
        "label": node.label,
        "gate": "passed",
        "gate_mech": node.gate_mech.value,
        "rubric": node.gate_rubric,  # None=仅机械过（无语义审）
        "attempts": attempts,
        "skill": node.skill,
        "via": via,
        "ts": _now(),
        "commit_sha": stamp_commit_sha(cwd),
    }
    path = _evidence_path(project_root, name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        return False
    return True


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


def gate_verdict_mech(node: Node, project_root: Path | None = None) -> str | None:
    """机械门判定。返回 None=通过,返回字符串=block 原因。

    project_root 用于产物文件存在检查（None 时机械项降级为只判 NONE）。
    """
    if node.gate_mech == GateMech.NONE:
        return None  # 无机械门,通过
    if project_root is None:
        # 无 project_root 无法判文件 -> 降级放行（宁纵勿枉,同 codegraph_gate 非 git 放行）
        # 语义 judge 兜底。
        return None
    if node.gate_mech == GateMech.ARTIFACT_EXISTS:
        if not node.artifact or "/" in node.artifact or node.artifact.endswith("+"):
            # 产物标识含描述性文本（如"代码+commit+测试通过"）非单文件 -> 机械无法判,交语义 judge
            return None
        # 产物文件路径：worktree/.claude/workflows/<name>/ 或约定根。
        # 暂以 worktree 根下查找（understand.md 等约定写在 worktree 根）。
        # TODO §8.3 确认产物落点后精确化。
        return None  # 暂不实现文件查找,留 §8.3 hook 接入时连同产物路径一起定
    if node.gate_mech == GateMech.TEST_PASS:
        return None  # 暂不实现,留 §8.2/§8.3
    return None


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


def run_judge(
    rubric: str,
    node_label: str,
    model_output: str,
    artifact_content: str | None = None,
) -> tuple[bool, str]:
    """起 stateless claude -p 当评审 judge。返回 (pass, reason)。

    design §5.1：独立会话,不续主 session（防污染主上下文）。
    输入 = rubric（判据）+ 模型本轮输出 + 声明产物内容。
    输出 = {pass:bool, reason:str}（JSON 强约束）。
    judge 继承主会话 env（design §9 #2）：不另设 provider/model,跑在主会话已起的 provider 上。

    失败（API 错/超时/解析失败）-> (False, 失败原因)（design §5.1 降级：不默认放行）。
    """
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
    prompt += "\n只回上面的 JSON。"

    try:
        res = subprocess.run(
            ["claude", "-p", "--output-format", "json", prompt],
            capture_output=True,
            text=True,
            timeout=JUDGE_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, f"judge 调用失败（{type(e).__name__}）"
    if res.returncode != 0:
        return False, f"judge claude -p 退出码 {res.returncode}"

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
        return False, "judge 输出无 result JSON 行"
    if last_json.get("is_error"):
        return False, f"judge 会话出错：{last_json.get('result', '')[:200]}"

    result_text = last_json.get("result", "")
    verdict = _extract_judge_result(result_text)
    if verdict is None:
        return False, f"judge 返回非合法 JSON 判定：{result_text[:200]}"
    return bool(verdict["pass"]), str(verdict.get("reason", ""))


def run_gate(
    node: Node,
    model_output: str,
    project_root: Path | None = None,
    artifact_content: str | None = None,
) -> tuple[bool, str]:
    """compound gate（机械 + 语义,短路）。返回 (pass, block_reason)。

    design §5：机械不过短路 block（不跑 judge）;机械过跑 judge。
    无 gate_rubric 的节点（如 understand 子阶段 1-3）只过机械项。
    机械项目前未实现文件查找（§8.3）,多数降级放行 -> 靠 judge 兜底。
    """
    # 1. 机械项（短路）
    mech_block = gate_verdict_mech(node, project_root)
    if mech_block is not None:
        return False, mech_block
    # 2. 语义项（judge）。无 rubric -> 直接过（子阶段间自动推进）。
    if not node.gate_rubric:
        return True, ""
    ok, reason = run_judge(node.gate_rubric, node.label, model_output, artifact_content)
    if not ok:
        return False, reason or "judge 未给出原因"
    return True, ""


# ---------- CLI（design §8.1;供 wf-cmd.sh / 手动覆盖调用）----------


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
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _cmd_advance(project_root: Path, name: str) -> int:
    state = advance_state(project_root, name)
    node = get_node(state["phase"], state["sub_index"])
    print(f"▸ 推进到节点 {state['node']}")
    print(f"  {PHASE_LABELS.get(state['phase'], state['phase'])} · {node.label}")
    return 0


def _cmd_meta() -> int:
    """输出全部静态常量 JSON（供 wf-lib.sh 启动时缓存,删 bash 侧副本）。

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
        prog="dl-flow-engine",
        description="工作流编排内核（被 hook 咨询;不当主进程）",
    )
    parser.add_argument("cmd", choices=["status", "current", "advance", "meta"])
    parser.add_argument("name", nargs="?", help="工作流名（不填则从 cwd 反查）")
    parser.add_argument("--cwd", help="覆盖 cwd（默认进程 cwd）")
    args = parser.parse_args(argv)

    # meta 是静态常量,不需要 git repo / name。
    if args.cmd == "meta":
        return _cmd_meta()

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

    if args.cmd == "status":
        return _cmd_status(project_root, name)
    if args.cmd == "current":
        return _cmd_current(project_root, name)
    if args.cmd == "advance":
        return _cmd_advance(project_root, name)
    return 1


if __name__ == "__main__":
    sys.exit(main())
