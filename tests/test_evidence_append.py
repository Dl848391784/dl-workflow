"""evidence_append.py 单元测试（dl-workflow）。

对应 designs/evidence-chain-design.md §4（写入机制）。
混合策略（守 TDD：真实代码，不 mock）：
- 纯函数（parse_evidence_markers / translate_and_assign）直接 import 测：快、聚焦、覆盖边界。
- Stop hook 端到端用 subprocess（验真实 wiring：读 transcript、append 文件、exit 0 永不阻断）。
- tmp_path 建伪 worktree 结构 git repo，天然隔离，不污染真实 .wf_evidence.log。

范围（v1 记录骨架）：解析标记 -> 分配 canonical id -> 翻译 depends_on -> 戳 ts/phase/commit_sha
-> append JSONL -> 留痕 .wf_evidence.log -> exit 0。
门控/审核（§10 后议）不在此测。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

DLWF_ROOT = Path(__file__).resolve().parents[1]
HOOK = DLWF_ROOT / "hooks" / "evidence_append.py"

# 纯函数直接 import（subprocess 端到端单独测 main）
sys.path.insert(0, str(DLWF_ROOT / "hooks"))
import evidence_append as ev  # noqa: E402


# ─────────── parse_evidence_markers ───────────


def test_parse_single_marker() -> None:
    text = (
        "blah\n"
        '### EVIDENCE:{"step":1,"claim":"A","claim_type":"premise",'
        '"depends_on":[],"evidence":[]}\n'
        "more"
    )
    nodes = ev.parse_evidence_markers(text)
    assert len(nodes) == 1
    assert nodes[0]["claim"] == "A"
    assert nodes[0]["step"] == 1


def test_parse_multiple_markers() -> None:
    text = (
        '### EVIDENCE:{"step":1,"claim":"A","claim_type":"premise","depends_on":[],"evidence":[]}\n'
        '### EVIDENCE:{"step":2,"claim":"B","claim_type":"intermediate",'
        '"depends_on":["step1"],"evidence":[]}'
    )
    nodes = ev.parse_evidence_markers(text)
    assert len(nodes) == 2
    assert nodes[1]["depends_on"] == ["step1"]


def test_parse_skips_malformed_json() -> None:
    """单条 JSON 解析失败 -> 跳过该条，不影响其余。"""
    text = (
        "### EVIDENCE:{bad json}\n"
        '### EVIDENCE:{"step":1,"claim":"A","claim_type":"premise","depends_on":[],"evidence":[]}'
    )
    nodes = ev.parse_evidence_markers(text)
    assert len(nodes) == 1
    assert nodes[0]["claim"] == "A"


def test_parse_no_markers_returns_empty() -> None:
    assert ev.parse_evidence_markers("no markers here") == []
    assert ev.parse_evidence_markers("") == []


def test_parse_fills_missing_optional_fields() -> None:
    """模型漏 claim_type/depends_on/evidence -> 填默认。"""
    text = '### EVIDENCE:{"step":1,"claim":"A"}'
    nodes = ev.parse_evidence_markers(text)
    assert nodes[0]["claim_type"] == "intermediate"
    assert nodes[0]["depends_on"] == []
    assert nodes[0]["evidence"] == []


def test_parse_coerces_non_int_step() -> None:
    """模型误发字符串 step -> 强转 int（防 %d 爆）。"""
    text = '### EVIDENCE:{"step":"1","claim":"A","depends_on":[],"evidence":[]}'
    nodes = ev.parse_evidence_markers(text)
    assert nodes[0]["step"] == 1


# ─────────── translate_and_assign ───────────


def test_assign_canonical_ids_incremental() -> None:
    nodes = [
        {"step": 1, "claim": "A", "depends_on": []},
        {"step": 2, "claim": "B", "depends_on": ["step1"]},
    ]
    out = ev.translate_and_assign(nodes, base_count=0)
    assert out[0]["id"] == "ev_001"
    assert out[1]["id"] == "ev_002"


def test_assign_continues_from_existing_count() -> None:
    nodes = [{"step": 1, "claim": "A", "depends_on": []}]
    out = ev.translate_and_assign(nodes, base_count=3)
    assert out[0]["id"] == "ev_004"


def test_translate_local_handle_to_canonical() -> None:
    nodes = [
        {"step": 1, "claim": "A", "depends_on": []},
        {"step": 2, "claim": "B", "depends_on": ["step1"]},
    ]
    out = ev.translate_and_assign(nodes, base_count=0)
    assert out[1]["depends_on"] == ["ev_001"]


def test_translate_preserves_unknown_handle() -> None:
    """跨轮 canonical id（不在本轮句柄表）-> 原样保留。"""
    nodes = [{"step": 1, "claim": "A", "depends_on": ["ev_999"]}]
    out = ev.translate_and_assign(nodes, base_count=0)
    assert out[0]["depends_on"] == ["ev_999"]


def test_assign_sorted_by_step() -> None:
    """模型乱序输出（step2 在前）-> canonical 按 step 排序，依赖仍正确。"""
    nodes = [
        {"step": 2, "claim": "B", "depends_on": ["step1"]},
        {"step": 1, "claim": "A", "depends_on": []},
    ]
    out = ev.translate_and_assign(nodes, base_count=0)
    assert out[0]["id"] == "ev_001"
    assert out[0]["claim"] == "A"
    assert out[1]["id"] == "ev_002"
    assert out[1]["depends_on"] == ["ev_001"]


def test_translate_empty_input() -> None:
    assert ev.translate_and_assign([], base_count=0) == []


# ─────────── Stop hook 端到端 ───────────


def _init_git_repo(repo: Path) -> None:
    """建一个有首个 commit 的 git repo（worktree add 的前置）。"""
    subprocess.run(
        ["git", "init", "-q", "-b", "main"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True
    )
    (repo / "README").write_text("x\n")
    subprocess.run(["git", "add", "README"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"], cwd=repo, check=True, capture_output=True
    )


def _make_worktree(repo: Path, name: str) -> Path:
    """用真 `git worktree add` 建隔离工作树（仿 launcher: repo/.claude/worktrees/<name>）。

    真 worktree -> `--git-common-dir` 返回主 repo 绝对路径（hook _resolve_project_root
    依赖此）。用 mkdir 伪造的子目录会返回相对路径 ../../../.git -> 解析错主 repo 根。
    生产机制即此，非 mock（守 TDD：真实代码）。
    """
    wt = repo / ".claude" / "worktrees" / name
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "wf/" + name, str(wt)],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return wt


def _write_state(repo: Path, name: str, phase: str = "execute", index: int = 3) -> None:
    """在主 repo 写 workflows/<name>/state.json（hook 经 project_root 读此）。"""
    state_dir = repo / ".claude" / "workflows" / name
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(
        json.dumps({"name": name, "phase": phase, "index": index})
    )


@pytest.fixture
def repo_wt(tmp_path: Path) -> tuple[Path, Path]:
    """临时 git repo + 真 worktree(testwf) + state.json(phase=execute)。

    tmp_path 每次独立 -> 天然隔离，不污染真实 .wf_evidence.log。
    """
    repo = tmp_path
    _init_git_repo(repo)
    wt = _make_worktree(repo, "testwf")
    _write_state(repo, "testwf")
    return repo, wt


def _write_transcript(path: Path, assistant_text: str) -> Path:
    """写单行 transcript JSONL（一条 assistant text 消息）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": assistant_text}],
                },
            }
        )
    )
    return path


def _run_hook(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _ev(text: str) -> str:
    """构造一条 assistant 事件 JSONL 行。"""
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
            },
        }
    )


def _user(text: str) -> str:
    """构造一条 user 事件 JSONL 行（轮次边界）。"""
    return json.dumps(
        {
            "type": "user",
            "message": {"role": "user", "content": [{"type": "text", "text": text}]},
        }
    )


# ─────────── _last_assistant_text 轮次边界 ───────────


def test_last_assistant_text_scans_whole_current_turn() -> None:
    """当前轮多条 assistant 消息都要扫（一条 user 后可能多条 assistant）。

    隐患修复：旧逻辑取全局最后一条 assistant 文本，会漏掉同轮较早 assistant 消息里的标记。
    """
    from io import StringIO

    import evidence_append as ev2

    transcript = "\n".join(
        [
            _user("q1"),
            _ev("上一轮回复"),
            _user("q2"),  # 当前轮起点
            _ev(
                '当前轮第1条 ### EVIDENCE:{"step":1,"claim":"A","claim_type":"premise","depends_on":[],"evidence":[]}'
            ),
            _ev("当前轮第2条，无标记"),
        ]
    )
    txt = ev2._last_assistant_text_io(StringIO(transcript))
    assert "### EVIDENCE:" in txt, "当前轮较早 assistant 消息里的标记被漏了"


def test_last_assistant_text_excludes_previous_turn() -> None:
    """只扫当前轮（最后一条 user 之后），不扫上一轮。"""
    from io import StringIO

    import evidence_append as ev2

    transcript = "\n".join(
        [
            _user("q1"),
            _ev(
                '上一轮 ### EVIDENCE:{"step":1,"claim":"OLD","claim_type":"premise","depends_on":[],"evidence":[]}'
            ),
            _user("q2"),  # 当前轮起点：上一轮的标记不该被采
            _ev("当前轮无标记"),
        ]
    )
    txt = ev2._last_assistant_text_io(StringIO(transcript))
    assert "OLD" not in txt, "上一轮的标记被误采了"
    assert "当前轮无标记" in txt


def test_last_assistant_text_handles_no_user() -> None:
    """无 user 消息（全是 assistant）-> 全部算当前轮。"""
    from io import StringIO

    import evidence_append as ev2

    transcript = "\n".join(
        [
            _ev("a1"),
            _ev(
                'a2 ### EVIDENCE:{"step":1,"claim":"A","claim_type":"premise","depends_on":[],"evidence":[]}'
            ),
        ]
    )
    txt = ev2._last_assistant_text_io(StringIO(transcript))
    assert "### EVIDENCE:" in txt


def test_stop_hook_appends_evidence_to_file(repo_wt) -> None:
    repo, wt = repo_wt
    transcript = _write_transcript(
        repo / ".claude" / "transcript.jsonl",
        '推理中...\n### EVIDENCE:{"step":1,"claim":"20=4x5","claim_type":"premise",'
        '"depends_on":[],"evidence":[{"kind":"reasoning","ref":"因数分解"}]}',
    )
    r = _run_hook({"cwd": str(wt), "transcript_path": str(transcript)})
    assert r.returncode == 0, r.stderr

    evf = repo / ".claude" / "evidence" / "testwf.jsonl"
    assert evf.exists(), "evidence.jsonl 未生成"
    node = json.loads(evf.read_text().strip())
    assert node["id"] == "ev_001"
    assert node["claim"] == "20=4x5"
    assert node["phase"] == "execute"
    assert node["status"] == "active"
    assert len(node["commit_sha"]) >= 7
    assert node["superseded_by"] is None


def test_stop_hook_appends_multiple_and_translates_depends(repo_wt) -> None:
    repo, wt = repo_wt
    transcript = _write_transcript(
        repo / ".claude" / "transcript.jsonl",
        '### EVIDENCE:{"step":1,"claim":"A","claim_type":"premise","depends_on":[],"evidence":[]}\n'
        '### EVIDENCE:{"step":2,"claim":"B","claim_type":"conclusion",'
        '"depends_on":["step1"],"evidence":[]}',
    )
    r = _run_hook({"cwd": str(wt), "transcript_path": str(transcript)})
    assert r.returncode == 0, r.stderr

    lines = [
        ln
        for ln in repo.joinpath(".claude/evidence/testwf.jsonl")
        .read_text()
        .splitlines()
        if ln.strip()
    ]
    assert len(lines) == 2
    n1, n2 = json.loads(lines[0]), json.loads(lines[1])
    assert n1["id"] == "ev_001" and n1["claim"] == "A"
    assert n2["id"] == "ev_002" and n2["claim"] == "B"
    assert n2["depends_on"] == ["ev_001"]


def test_stop_hook_continues_numbering_across_turns(repo_wt) -> None:
    """第二次 append 从已有节点数后续编号。"""
    repo, wt = repo_wt
    transcript = repo / ".claude" / "transcript.jsonl"
    _write_transcript(
        transcript,
        '### EVIDENCE:{"step":1,"claim":"A","claim_type":"premise","depends_on":[],"evidence":[]}',
    )
    _run_hook({"cwd": str(wt), "transcript_path": str(transcript)})
    # 第二轮
    _write_transcript(
        transcript,
        '### EVIDENCE:{"step":1,"claim":"B","claim_type":"conclusion","depends_on":["ev_001"],"evidence":[]}',
    )
    r = _run_hook({"cwd": str(wt), "transcript_path": str(transcript)})
    assert r.returncode == 0, r.stderr

    lines = [
        ln
        for ln in repo.joinpath(".claude/evidence/testwf.jsonl")
        .read_text()
        .splitlines()
        if ln.strip()
    ]
    assert len(lines) == 2
    assert json.loads(lines[1])["id"] == "ev_002"
    assert json.loads(lines[1])["depends_on"] == ["ev_001"]


def test_stop_hook_mkdir_evidence_dir(repo_wt) -> None:
    """首次 append 时 .claude/evidence/ 目录不存在 -> hook 自建。"""
    repo, wt = repo_wt
    assert not (repo / ".claude" / "evidence").exists()
    transcript = _write_transcript(
        repo / ".claude" / "transcript.jsonl",
        '### EVIDENCE:{"step":1,"claim":"A","claim_type":"premise","depends_on":[],"evidence":[]}',
    )
    r = _run_hook({"cwd": str(wt), "transcript_path": str(transcript)})
    assert r.returncode == 0, r.stderr
    assert (repo / ".claude" / "evidence" / "testwf.jsonl").exists()


def test_stop_hook_no_marker_no_append(repo_wt) -> None:
    """无 EVIDENCE 标记 -> 不追加文件，仍 exit 0。"""
    repo, wt = repo_wt
    transcript = _write_transcript(
        repo / ".claude" / "transcript.jsonl", "普通回复无标记"
    )
    r = _run_hook({"cwd": str(wt), "transcript_path": str(transcript)})
    assert r.returncode == 0, r.stderr
    assert not (repo / ".claude" / "evidence" / "testwf.jsonl").exists()


def test_stop_hook_skips_malformed_keeps_valid(repo_wt) -> None:
    """坏 JSON 标记跳过，好的仍追加。"""
    repo, wt = repo_wt
    transcript = _write_transcript(
        repo / ".claude" / "transcript.jsonl",
        "### EVIDENCE:{bad json}\n"
        '### EVIDENCE:{"step":1,"claim":"good","claim_type":"premise","depends_on":[],"evidence":[]}',
    )
    r = _run_hook({"cwd": str(wt), "transcript_path": str(transcript)})
    assert r.returncode == 0, r.stderr
    lines = [
        ln
        for ln in repo.joinpath(".claude/evidence/testwf.jsonl")
        .read_text()
        .splitlines()
        if ln.strip()
    ]
    assert len(lines) == 1
    assert json.loads(lines[0])["claim"] == "good"


# ─────────── 容错（永不阻断） ───────────


def test_hook_handles_malformed_stdin() -> None:
    """损坏 JSON 输入不阻断（exit 0）。"""
    r = subprocess.run(
        [sys.executable, str(HOOK)],
        input="{not json",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0


def test_hook_handles_non_worktree_cwd(tmp_path: Path) -> None:
    """cwd 不在 worktree 路径 -> 跳过，exit 0。"""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, capture_output=True)
    transcript = _write_transcript(tmp_path / "t.jsonl", "x")
    r = _run_hook({"cwd": str(tmp_path), "transcript_path": str(transcript)})
    assert r.returncode == 0


def test_hook_handles_missing_state(tmp_path: Path) -> None:
    """真 worktree 但无 state.json -> 跳过 + 留痕，exit 0。"""
    repo = tmp_path
    _init_git_repo(repo)
    wt = _make_worktree(repo, "ghost")
    # 故意不建 state.json（模拟 state 缺失）
    transcript = _write_transcript(
        repo / ".claude" / "t.jsonl",
        '### EVIDENCE:{"step":1,"claim":"A","claim_type":"premise","depends_on":[],"evidence":[]}',
    )
    r = _run_hook({"cwd": str(wt), "transcript_path": str(transcript)})
    assert r.returncode == 0, r.stderr
    assert not (repo / ".claude" / "evidence" / "ghost.jsonl").exists()
    # 留痕
    assert (repo / ".claude" / ".wf_evidence.log").exists()


def test_hook_logs_to_wf_evidence_log(repo_wt) -> None:
    """成功追加后留痕 .wf_evidence.log。"""
    repo, wt = repo_wt
    transcript = _write_transcript(
        repo / ".claude" / "transcript.jsonl",
        '### EVIDENCE:{"step":1,"claim":"A","claim_type":"premise","depends_on":[],"evidence":[]}',
    )
    _run_hook({"cwd": str(wt), "transcript_path": str(transcript)})
    log = (repo / ".claude" / ".wf_evidence.log").read_text()
    assert "appended" in log
