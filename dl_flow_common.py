#!/usr/bin/env python3
"""
dl_flow_common - state/trace 低层 helper（engine 与 checks 共用真源）。

拆分缘由（2026-08-27）：dl_flow_checks.py（v2.27 机械预检家族）从
dl_flow_engine.py 抽出后，校验函数与 engine 本体都依赖这批 state 装载 /
trace 分段 helper——下沉本模块打破双向依赖（common 只依赖 dl_flow_nodes）。
engine 经 re-export 保持 eng.<name> 访问面不变。

2026-08-27 第二轮（handoff/trace 抽离）再下沉：_now / trace_payload_path /
sub_step_at / sub_step_has_trace。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from dl_flow_nodes import Node, Step, current_node_id, get_node, sub_total


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


# ---------- 第二轮下沉（2026-08-27，handoff/trace 抽离的共用依赖）----------


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


# ---------- 插话通道（evolution-up P5，evolution-up-design §6）----------
# 用户在段在跑期间给后续步骤的转向指令：dashboard 经 steer_append 落
# steer.jsonl（只经脚本写，模型不可写——S14 同款纪律）；driver 段起跑读
# offset 之后的未消费行注入段 prompt 并推进 offset。JSONL append-only
# 留全史，offset 文件记消费位（文件截断/越界 = 重置重读，宁纵勿枉）。


def steer_path(project_root: Path, name: str) -> Path:
    return state_path(project_root, name).parent / "steer.jsonl"


def _steer_offset_path(project_root: Path, name: str) -> Path:
    return state_path(project_root, name).parent / "steer.offset"


def _steer_offset(project_root: Path, name: str, size: int) -> int:
    try:
        off = int(_steer_offset_path(project_root, name).read_text(
            encoding="utf-8").strip())
    except (OSError, ValueError):
        off = 0
    return off if 0 <= off <= size else 0


def steer_append(project_root: Path, name: str, text: str,
                 ts: str | None = None) -> dict:
    """写侧（dashboard actions 唯一调用方）：追加一条用户插话。"""
    rec = {"ts": ts or _now(), "text": text}
    p = steer_path(project_root, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def steer_list(project_root: Path, name: str) -> list[dict]:
    """全部插话 + consumed 标记（dashboard 展示面；坏行跳过不拖垮）。"""
    p = steer_path(project_root, name)
    if not p.exists():
        return []
    raw = p.read_bytes()
    off = _steer_offset(project_root, name, len(raw))
    out: list[dict] = []
    pos = 0
    for line in raw.splitlines():
        end = pos + len(line) + 1
        pos = end
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        d["consumed"] = end <= off
        out.append(d)
    return out


def steer_pending(project_root: Path, name: str) -> list[dict]:
    """未消费插话（driver 段起跑注入面）。"""
    return [s for s in steer_list(project_root, name) if not s["consumed"]]


def steer_consume(project_root: Path, name: str) -> list[dict]:
    """读未消费插话并推进 offset（返回被消费行）。steer.jsonl 留全史——
    注入后段异常只是「没生效」，内容不丢，dashboard 可见可重发。"""
    pending = steer_pending(project_root, name)
    if pending:
        size = steer_path(project_root, name).stat().st_size
        _steer_offset_path(project_root, name).write_text(
            str(size), encoding="utf-8")
    return pending


def trace_payload_path(
    project_root: Path, name: str, state: dict | None = None
) -> Path:
    """trace 载荷路径单源（v2.125）。全链路（注入/scaffold/围栏/落库）只调这里。

    v2.125 动机（tail_volume 2026-08-07 acceptEdits 重跑实测）：旧落点主仓
    .claude/evidence/ 撞 harness 写入保护目录（.claude 仅豁免 commands/agents/
    skills/worktrees）——acceptEdits 下 Edit 载荷必弹窗且 allow 规则无效
    （叠加 #16170：Edit/Write 的 ** 通配不匹配）。载荷是临时文件
    （append-trace 消费即弃），不需要主仓持久性 -> 挪 worktree 根：
    .claude/worktrees/ 在保护豁免名单内 + cwd 内编辑 acceptEdits 本地放行，
    两个坑同时绕开。evidence.jsonl 本体与阶段产物仍走 Bash 落库主仓
    （Bash 不过文件权限检查），持久性决议（2026-07-28）不受影响。
    兜底：state 无 worktree_path（测试/旧 state）-> 旧 evidence 路径。
    """
    if state is None:
        state = load_state(project_root, name) or {}
    wt = state.get("worktree_path")
    if isinstance(wt, str) and wt:
        return Path(wt) / f".trace-payload-{name}.md"
    return _evidence_path(project_root, name).parent / f".trace-payload-{name}.md"


def sub_step_at(node: Node, n: int) -> Step | None:
    """取第 n 子步骤（1-based）；越界/无子步骤返回 None。"""
    if not node.sub_steps or not (1 <= n <= len(node.sub_steps)):
        return None
    return node.sub_steps[n - 1]


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


# ---------- change_point 锚点解析（单源，v0.6.0 自 dl_dashboard/outputs.py 迁入）----------
# 消费方：dashboard outputs.load_change_points（改动面 API）+ dl_doc_render
# （人读版改动面卡片）。锚点语法钦定于 dl_flow_nodes._CHANGE_SPEC_RULE。
import logging  # noqa: E402
import re  # noqa: E402

_cp_log = logging.getLogger("dl_flow_common.change_points")

# change_point= 块（跨行，止于 ；interface= / ；Produces= / 空行 / 串尾）
CP_RE = re.compile(r"change_point=(.+?)(?:；interface=|；Produces=|\n\n|$)", re.S)
# 锚点行（2026-08-25 up-change-spec-gate 钦定语法）：
#         web_ui/app.py:_render_report:L267-269（改）：改前 X → 改后 Y（注）
#         _macros.html:-:L57-57（改）：改前 ... → 改后 ...（注）
#         test_x.py:-（增@文件尾）：新增测试描述
# 行号为区间 L<a>-<b>（单行即 a=b）；改前/改后等号可省（新旧两态都收）。
ANCHOR_RE = re.compile(
    r"([\w./-]+\.\w+):([\w.-]*):?L?(\d+|-)?(?:-\d+)?（(改|增|删)[^）]*）"
    r"(?:：改前=?(.*?)\s*→\s*改后=?(.*?))?(?:：([^；\n]*))?(?=；|\n|$)"
)
CTX_RADIUS = 4  # 现状代码上下文半径（锚点行 ±4）


def code_context(root: Path | None, file: str, line: str, method: str) -> dict | None:
    """root（worktree 或主仓）实读锚点上下文 ±CTX_RADIUS 行。

    行号定位优先；无行号但有方法名时按方法名首现定位（def 行或调用行）
    ——tacet 脊柱产物的锚点常只有 `file:method:（增）` 形态。文件缺失/
    两者皆无 -> None。
    """
    if root is None:
        return None
    p = root / file
    if not p.is_file():
        return None
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        _cp_log.warning("锚点文件读失败: %s", p, exc_info=True)
        return None
    n: int | None = None
    if line.isdigit():
        n = int(line)
        if n < 1 or n > len(lines):
            return None
    elif method and method != "-":
        for idx, text in enumerate(lines, 1):
            if f"def {method}" in text:
                n = idx
                break
        if n is None:
            for idx, text in enumerate(lines, 1):
                if method in text:
                    n = idx
                    break
    if n is None:
        return None
    lo, hi = max(1, n - CTX_RADIUS), min(len(lines), n + CTX_RADIUS)
    return {
        "start": lo,
        "anchor": n,
        "lines": lines[lo - 1 : hi],
    }


def parse_change_points(text: str, root: Path | None) -> list[dict]:
    """plan/proposal md 文本 -> change_point 锚点列表（含现状代码上下文 best-effort）。

    root=代码根（worktree 或主仓）：读不到/锚点定位失败 -> context=None（只缺
    代码片段，锚点与改前/改后照出——老实例 worktree 已删不挡卡片渲染）。
    """
    out: list[dict] = []
    for m in CP_RE.finditer(text):
        for a in ANCHOR_RE.finditer(m.group(1)):
            out.append(
                {
                    "file": a.group(1),
                    "method": a.group(2) or "-",
                    "line": a.group(3) or "-",
                    "action": a.group(4),
                    "before": (a.group(5) or "").strip(),
                    "after": (a.group(6) or "").strip(),
                    "summary": (a.group(7) or "").strip(),
                    "context": code_context(
                        root, a.group(1), a.group(3) or "", a.group(2) or ""
                    ),
                }
            )
    return out
