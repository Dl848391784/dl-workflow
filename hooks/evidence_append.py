#!/usr/bin/env python3
"""
Stop hook：推导证据链追加。

对应设计 designs/evidence-chain-design.md §4。
每轮 assistant 回复结束后，读 transcript 取上一条 assistant 文本，
抽全部 `### EVIDENCE:{json}` 标记 -> 分配 canonical id + 翻译 depends_on 本地句柄
-> 戳 ts/phase/commit_sha -> append 到 <项目>/.claude/evidence/<name>.jsonl。

**与 workflow_advance.py 并列**（同 Stop hook，settings.json hooks 数组各一项）：
- workflow_advance.py 推进阶段（读写 state.json）。
- 本 hook 追加证据（只读 state 取 phase，只写 evidence.jsonl）。
  写不同文件 -> 无竞态，执行顺序无依赖（设计 §11 风险 5）。

**永不阻断**（exit 0 only）：标记解析失败 / transcript 缺失 / 文件写失败
-> 留痕 .wf_evidence.log + exit 0（no silent fallback，与 workflow_advance.py 一致）。

**dl-workflow 版本**：hook 装到 ~/.claude/hooks/（用户级），从 payload cwd 反查主仓库根
（复用 workflow_advance.py 的 _resolve_project_root / _last_assistant_text 范式）。
evidence.jsonl 落主仓库 .claude/evidence/<name>.jsonl（不在 worktree checkout 内，
worktree 删不影响；见设计 §5/§11 风险 4）。
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path


# 完成标记正则：### EVIDENCE:{...}（与 PHASE_DONE/SUB_DONE 同位，模型回复末尾输出）
EVIDENCE_RE = re.compile(r"###\s*EVIDENCE:\s*(\{.*\})", re.IGNORECASE)

# claim_type 缺省值（模型漏填时）
DEFAULT_CLAIM_TYPE = "intermediate"


# ─────────── 纯函数（可单测） ───────────


def parse_evidence_markers(text: str) -> list[dict]:
    """从 assistant 文本抽全部 ### EVIDENCE:{json} 标记，返回解析后的 dict 列表。

    容错（设计 §4.1 / §11 风险 1）：单条 JSON 解析失败 -> 跳过该条（不抛）。
    缺失可选字段（claim_type/depends_on/evidence/step）填默认。
    step 强转 int（防模型误发字符串致 %d 爆）。
    """
    nodes: list[dict] = []
    for m in EVIDENCE_RE.finditer(text or ""):
        raw = m.group(1)
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(d, dict):
            continue
        # step 强转 int（容错模型误发字符串/缺失）
        try:
            step = int(d.get("step", 0) or 0)
        except (TypeError, ValueError):
            step = 0
        d["step"] = step
        d.setdefault("claim", "")
        d.setdefault("claim_type", DEFAULT_CLAIM_TYPE)
        d.setdefault("depends_on", [])
        d.setdefault("evidence", [])
        nodes.append(d)
    return nodes


def translate_and_assign(nodes: list[dict], base_count: int) -> list[dict]:
    """分配 canonical id（按 step 排序）+ 翻译 depends_on 本地句柄。

    - base_count: 现有文件节点数（续编号起点）。
    - canonical id: ev_<NNN>（%03d 补零），按 step 升序稳定排序后顺序分配。
    - 本地句柄 = 'step<step>'（模型在 depends_on 用），建本轮句柄表 step->canonical。
    - depends_on 翻译：在表内则替换为 canonical id，否则原样保留
      （跨轮 canonical id 如 'ev_003'，设计 §11 风险 3）。

    返回新 list（不改动入参 dict），顺序为 step 排序后顺序。
    """
    ordered = sorted(nodes, key=lambda n: n.get("step", 0))
    handle_map: dict[str, str] = {}
    result: list[dict] = []
    for i, node in enumerate(ordered):
        cid = "ev_%03d" % (base_count + i + 1)
        out = dict(node)
        out["id"] = cid
        step = out.get("step", 0)
        if step:
            handle_map["step%d" % step] = cid
        result.append(out)
    for out in result:
        deps = out.get("depends_on", [])
        out["depends_on"] = [handle_map.get(d, d) for d in deps]
    return result


# ─────────── hook 基础设施（复用 workflow_advance.py 范式） ───────────


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
    （与 workflow_advance.py._resolve_project_root 同实现。）
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


def _assistant_text_of(msg: dict) -> str:
    """从一条 message dict 取其文本（content 是 str 或 list[{type:text}]）。"""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _last_assistant_text_io(stream) -> str:
    """扫 transcript JSONL 流，取**当前轮**所有 assistant 文本（拼接）。

    「当前轮」= 最后一条 user message 之后的所有 assistant message。
    隐患修复（2026-07-23 live smoke 推演）：旧实现取全局最后一条 assistant 文本，
    会漏掉同轮较早 assistant 消息里的 ### EVIDENCE 标记（一条 user 回合后模型可能
    发多条 assistant 消息，标记可能不在最后一条）。改成扫整轮 + 仅当前轮
    （不采上一轮，避免重复追加已落库的旧标记）。

    防御式：解析失败/格式不符 -> 跳过该行。无 assistant 文本 -> ""。
    """
    current_turn_texts: list[str] = []
    for line in stream:
        line = line.strip() if isinstance(line, str) else line
        if not line:
            continue
        try:
            ev = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(ev, dict):
            continue
        msg = ev.get("message")
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role == "user":
            # 新轮开始：重置当前轮收集（之前的 assistant 归上一轮）。
            # 无 user 时永不重置 -> 全部 assistant 算当前轮（test_last_assistant_text_handles_no_user）。
            current_turn_texts = []
        elif role == "assistant":
            txt = _assistant_text_of(msg)
            if txt:
                current_turn_texts.append(txt)
    return " ".join(current_turn_texts).strip()


def _last_assistant_text(transcript_path: str) -> str:
    """读 transcript JSONL 文件，取当前轮所有 assistant 文本。

    防御式：transcript_path 缺失/读失败 -> 返回 ""。
    委派 _last_assistant_text_io（可单测，传 StringIO）。
    """
    if not transcript_path or not Path(transcript_path).exists():
        return ""
    try:
        with open(transcript_path, encoding="utf-8") as fh:
            return _last_assistant_text_io(fh)
    except OSError:
        return ""


def _stamp_commit_sha(cwd: str) -> str:
    """取 worktree 内项目 repo 当前 HEAD SHA（防腐锚点，设计 §6.1）。

    取不到（非 git / 无 commit）-> 空串（不阻断，事后回溯降级）。
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


def _log(project_root: Path | None, status: str, **kw) -> None:
    """留痕 Stop 触发（观测性）。失败静默。

    守 H11：%-格式化，禁 f-string。
    project_root 缺失时不留痕（无处写）。
    """
    if project_root is None:
        return
    log = project_root / ".claude" / ".wf_evidence.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        parts = ["%s=%s" % (k, v) for k, v in kw.items()]
        with open(log, "a", encoding="utf-8") as f:
            f.write("%s|%s|%s\n" % (ts, status, "|".join(parts)))
    except OSError:
        pass


def _evidence_path(project_root: Path, name: str) -> Path:
    return project_root / ".claude" / "evidence" / (name + ".jsonl")


def _count_existing(path: Path) -> int:
    """数 evidence.jsonl 现有非空行数（续编号起点）。文件不存在 -> 0。"""
    if not path.exists():
        return 0
    n = 0
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    n += 1
    except OSError:
        return 0
    return n


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
        return 0  # 不在 worktree 内（普通会话）-> 不追加

    if project_root is None:
        return 0

    state = _load_state(project_root, name)
    if not state:
        _log(project_root, "no_state", wf=name)
        return 0

    phase = state.get("phase", "execute")

    transcript_path = ""
    for key in ("transcript_path", "transcriptPath", "transcript"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            transcript_path = val
            break
    text = _last_assistant_text(transcript_path)

    nodes = parse_evidence_markers(text)
    if not nodes:
        _log(project_root, "no_markers", wf=name, phase=phase, tlen=len(text))
        return 0

    evidence_path = _evidence_path(project_root, name)
    base_count = _count_existing(evidence_path)
    assigned = translate_and_assign(nodes, base_count)
    commit_sha = _stamp_commit_sha(cwd)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())

    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    appended = 0
    try:
        with open(evidence_path, "a", encoding="utf-8") as f:
            for node in assigned:
                node["ts"] = ts
                node["phase"] = phase
                node["status"] = node.get("status", "active")
                node["commit_sha"] = commit_sha
                node.setdefault("superseded_by", None)
                f.write(json.dumps(node, ensure_ascii=False) + "\n")
                appended += 1
    except OSError:
        _log(project_root, "write_failed", wf=name, phase=phase)
        return 0

    _log(project_root, "appended", wf=name, phase=phase, n=appended)
    return 0


if __name__ == "__main__":
    sys.exit(main())
