"""tail_volume u:1 子3/子4 双报错的 case 级回归（v2.118 修 A-D）。

事故实录（2026-08-05，designs/agent-await-mechanization-design.md）：
  15:21:44  派发升档 full agent
  15:21:52  tool_result 回 launch ack（**不是** completion）
  15:23:02  Stop -> engage_block「没有任何 evidence skill-trace」  ← 假性 block
  15:24:11  Stop -> pass（full agent 仍未归）                      ← 缺口放过
  15:24:45  <task-notification> full agent 真正归还

本模块用**生产实测形态**做 case 回归（非手造替身——fixture 失真正是本 bug
潜伏的原因，§1.2）。四修各自的 case：
  修 A：launch ack ≠ 归还 -> gate 时刻必判 pending（旧判据在此得 0）
  修 B：派发 2 个 agent 只收 1 份报告 -> 必 BLOCK（旧判据 tier 计数放过）
  修 C：light 档配额算式在骨架里（每层 ≥1、单层 ≤3）
  修 D：有在跑 agent 时取证 curl 放行（跨步存活的子代理不被误拒）
"""

import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# ---- 真实事故的三个 agent id（取自 evidence trace 与 transcript）----
AID_LIGHT = "ace9f1ac6a9d39f5e"  # light 档取证 agent（零命中，建议升档）
AID_FULL = "a781d26c012a3cee8"  # 升档补派的 full agent（跨步到子4 才归）
AID_REDTEAM = "ac4fc0f08e1ae3d63"  # 红队 agent

# ---- 生产实测的 launch ack（逐字截取，只省略无关尾句）----
REAL_LAUNCH_ACK = (
    "Async agent launched successfully. (This tool result is internal metadata — "
    "never quote or paste any part of it, including the agentId below, into a "
    "user-facing reply.)\nagentId: {aid} (internal ID - do not mention to user. "
    "Use SendMessage with to: '{aid}', summary: '<5-10 word recap>' to continue "
    "this agent.)\nThe agent is working in the background. You will be notified "
    "automatically when it completes."
)

# ---- 生产实测的归还通知 ----
REAL_DONE_NOTIFICATION = (
    "<task-notification>\n<task-id>{aid}</task-id>\n"
    "<tool-use-id>call_00_x</tool-use-id>\n</task-notification>"
)


def _load_hook(stem: str):
    spec = importlib.util.spec_from_file_location(stem, REPO / "hooks" / f"{stem}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _launch_line(aid: str) -> str:
    return json.dumps(
        {
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": f"call_00_{aid[:8]}",
                        "content": [
                            {"type": "text", "text": REAL_LAUNCH_ACK.format(aid=aid)}
                        ],
                    }
                ],
            }
        }
    )


def _done_line(aid: str) -> str:
    return json.dumps(
        {"type": "attachment", "content": REAL_DONE_NOTIFICATION.format(aid=aid)}
    )


class TestFixAPendingDetection:
    """修 A：launch ack 与 completion 是两个信号。"""

    def test_gate_moment_replay_light_returned_full_pending(self, tmp_path):
        """重放 15:23:02 gate 时刻：light 已归、full 未归 -> pending=1。

        旧判据在同一输入得 0（launch ack 的 tool_use_id 立刻进 result 集合），
        故生产照旧 engage_block。本断言即修 A 的因果证明。
        """
        mod = _load_hook("workflow_advance")
        tp = tmp_path / "t.jsonl"
        tp.write_text(
            "\n".join(
                [
                    _launch_line(AID_LIGHT),  # 15:20:21 派发
                    _done_line(AID_LIGHT),  # 15:21:11 归还
                    _launch_line(AID_FULL),  # 15:21:52 派发（升档）
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        assert mod._pending_background_agent_count(str(tp)) == 1

    def test_old_judge_would_miss_it(self, tmp_path):
        """对照组：旧判据在同一 transcript 上得 0（证伪「旧判据本可生效」）。"""
        tp = tmp_path / "t.jsonl"
        tp.write_text(
            "\n".join([_launch_line(AID_FULL)]) + "\n",
            encoding="utf-8",
        )
        agent_ids, result_ids = set(), set()
        for line in tp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ev = json.loads(line)
            msg = ev.get("message")
            if not isinstance(msg, dict):
                continue
            for b in msg.get("content") or []:
                if msg.get("role") == "assistant" and b.get("type") == "tool_use":
                    agent_ids.add(b.get("id"))
                elif msg.get("role") == "user" and b.get("type") == "tool_result":
                    result_ids.add(b.get("tool_use_id"))
        assert len(agent_ids - result_ids) == 0  # 旧判据盲区
        mod = _load_hook("workflow_advance")
        assert mod._pending_background_agent_count(str(tp)) == 1  # 新判据看见

    def test_all_returned_is_zero(self, tmp_path):
        """三 agent 全归 -> 0（不长期挂起门控）。"""
        mod = _load_hook("workflow_advance")
        tp = tmp_path / "t.jsonl"
        lines = []
        for aid in (AID_LIGHT, AID_FULL, AID_REDTEAM):
            lines += [_launch_line(aid), _done_line(aid)]
        tp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert mod._pending_background_agent_count(str(tp)) == 0


class TestFixBReportPairing:
    """修 B：派发信号配对（类型无关）。"""

    @staticmethod
    def _engine():
        import sys

        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        import dl_flow_engine

        return dl_flow_engine

    def test_sub3_real_shape_blocks(self):
        """子3 真实形态：派 light+full，只收 light 报告 -> BLOCK。"""
        E = self._engine()
        qa = [
            {
                "q": "① 主张可检验化",
                "a": "原子2 claim：…；light 报告零命中后已补派 full",
            },
            {
                "q": "② 派发记录",
                "a": (
                    f"原子2 [tier=light] 子代理已归位（task-id {AID_LIGHT}）；"
                    f"补派 full agent（task-id {AID_FULL}，运行中）"
                ),
            },
            {"q": f"蒸馏报告原文收录（task-id {AID_LIGHT}）", "a": "…light 报告原文…"},
        ]
        msg = E._check_fetch_report_recorded(qa, None, None)
        assert msg is not None
        assert AID_FULL in msg

    def test_sub3_both_recorded_passes(self):
        """两份报告都收录 -> PASS（不误伤合法路径）。"""
        E = self._engine()
        qa = [
            {"q": "② 派发记录", "a": f"task-id {AID_LIGHT} 与 {AID_FULL} 均已归位"},
            {"q": f"蒸馏报告原文收录（task-id {AID_LIGHT}）", "a": "…light…"},
            {"q": f"蒸馏报告原文收录（task-id {AID_FULL}）", "a": "…full…"},
        ]
        assert E._check_fetch_report_recorded(qa, None, None) is None

    def test_sub4_real_shape_passes(self):
        """子4 真实形态：full 报告 + 红队均收录 -> PASS（类型无关不误伤）。"""
        E = self._engine()
        qa = [
            {"q": "① 三关质检", "a": "E1…E9 逐条三关"},
            {"q": "② 红队触发与派发记录", "a": f"红队 task-id {AID_REDTEAM} 已归位"},
            {"q": f"蒸馏报告原文收录（task-id {AID_FULL}）", "a": "…full 报告原文…"},
            {
                "q": f"红队输出原文收录（task-id {AID_REDTEAM}）",
                "a": "verdict：证实\n推理链：…\n置信度：0.95",
            },
        ]
        assert E._check_redteam_report_recorded(qa, None, None) is None
        assert E._check_redteam_three_piece(qa, None, None) is None

    def test_redteam_dispatched_not_recorded_still_blocks(self):
        """红队已派未收 -> 仍 BLOCK，且消息保留红队专属指路。"""
        E = self._engine()
        qa = [
            {"q": "① 三关质检", "a": "E1 三关全过"},
            {"q": "② 红队派发", "a": f"红队 task-id {AID_REDTEAM}，仍在跑"},
        ]
        msg = E._check_redteam_report_recorded(qa, None, None)
        assert msg is not None and "红队" in msg and "原文收录" in msg

    def test_no_dispatch_no_pairing_block(self):
        """未派发任何 agent -> 配对检查不拦（legacy 原子数下限另判，非本修范围）。

        本断言只锁「派发配对」这一层：无 task-id 即无配对义务。
        （下限检查 required>=1 仍会因「无蒸馏报告项」拦——那是 v2.38 既有行为，
        由 _dispatched_vs_unrecorded_task_ids 返回空列表证明本层放行。）
        """
        E = self._engine()
        qa = [{"q": "① 内查", "a": "原子1 none 档仓内定答，无外部取证"}]
        assert E._dispatched_vs_unrecorded_task_ids(qa) == []


class TestFixCLightQuota:
    """修 C：light 档层配额（上限≠配额）。"""

    @staticmethod
    def _skeleton() -> str:
        import sys

        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))

        src = (REPO / "dl_flow_engine.py").read_text(encoding="utf-8")
        assert "层配额（上限≠配额）" in src, "配额纪律未进骨架源"
        return src

    def test_quota_rule_present(self):
        src = self._skeleton()
        assert "每层至少花 1 次 curl" in src
        assert "禁在未轮完所有指定层前耗尽预算" in src

    def test_health_check_does_not_consume_budget(self):
        """「裸响应校验」占额度是事故里的第 4 次 curl——须明确不占额。"""
        src = self._skeleton()
        assert "curl 额度只用于 claim 取证" in src

    def test_upgrade_requires_all_layers_tried(self):
        src = self._skeleton()
        assert "且各指定层均已尝试" in src


class TestFixDPendingAgentCurl:
    """修 D：跨步存活子代理的取证 curl 放行。"""

    @staticmethod
    def _fence():
        return _load_hook("workflow_step_fence")

    @pytest.mark.parametrize(
        "cmd",
        [
            'curl -sS -m 25 "https://api.openalex.org/works?search=x&per_page=3"',
            'curl -sS -m 25 -A "Mozilla/5.0 (research)" "https://export.arxiv.org/api/query?x"',
            'curl -sS -m 25 "https://api.stackexchange.com/2.3/search/advanced?q=x" | head -c 6000',
            "curl -sS -m 25 \"https://x/y\" | jq -r '.items[]?.link'",
        ],
    )
    def test_fetch_template_curls_recognized(self, cmd):
        assert self._fence()._s15_fetch_curl(cmd) is True

    @pytest.mark.parametrize(
        "cmd",
        [
            'curl -sS -m 25 "https://x/y" > /tmp/out',  # 输出重定向
            'curl -sS "https://x" | tee /tmp/a',  # tee
            'curl -sS "https://x"; rm -rf /tmp/a',  # 混入写命令
            "python3 -c 'import os'",  # 非 curl
            'echo `curl -sS "https://x"`',  # 命令替换
        ],
    )
    def test_write_intent_rejected(self, cmd):
        assert self._fence()._s15_fetch_curl(cmd) is False

    def test_pending_detector_shared_with_advance(self, tmp_path):
        """fence 与 advance 的 pending 判定同口径（两处 regex 必须同步）。"""
        fence = self._fence()
        adv = _load_hook("workflow_advance")
        tp = tmp_path / "t.jsonl"
        tp.write_text(_launch_line(AID_FULL) + "\n", encoding="utf-8")
        assert fence._pending_background_agent_count(str(tp)) == 1
        assert adv._pending_background_agent_count(str(tp)) == 1
        assert fence._AGENT_LAUNCH_ID_RE.pattern == adv._AGENT_LAUNCH_ID_RE.pattern
        assert fence._AGENT_DONE_ID_RE.pattern == adv._AGENT_DONE_ID_RE.pattern
        assert fence._AGENT_LAUNCH_ACK == adv._AGENT_LAUNCH_ACK

    def test_no_pending_means_no_relaxation(self, tmp_path):
        """无在跑 agent -> pending=0，围栏行为不变（不放宽任何场景）。"""
        fence = self._fence()
        tp = tmp_path / "t.jsonl"
        tp.write_text(
            _launch_line(AID_FULL) + "\n" + _done_line(AID_FULL) + "\n",
            encoding="utf-8",
        )
        assert fence._pending_background_agent_count(str(tp)) == 0


class TestRealIncidentEvidenceIfPresent:
    """若本机仍有事故原始 evidence，则直接对真实载荷断言（最高保真度）。"""

    EV = Path(
        "/home/admin/projects/factor_ic_analyzer/.claude/evidence/"
        "tail_volume_acceleration_annualized.jsonl"
    )

    def test_real_payload_sub3_blocks_sub4_passes(self):
        if not self.EV.exists():
            pytest.skip("事故 evidence 不在本机（case 断言已由上方形态测试覆盖）")
        import sys

        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        import dl_flow_engine as E

        recs = [json.loads(x) for x in self.EV.read_text(encoding="utf-8").splitlines()]
        by_step = {r.get("sub_step"): r for r in recs if r.get("q")}
        if 3 not in by_step or 4 not in by_step:
            pytest.skip("evidence 缺子3/子4 记录")
        qa3 = [{"q": q, "a": a} for q, a in zip(by_step[3]["q"], by_step[3]["a"])]
        qa4 = [{"q": q, "a": a} for q, a in zip(by_step[4]["q"], by_step[4]["a"])]
        # 子3：升档 full 报告缺席 -> 必 BLOCK（旧判据放过 = 本次缺口）
        assert E._check_fetch_report_recorded(qa3, None, None) is not None
        # 子4：full + 红队均收录 -> 必 PASS（不误伤）
        assert E._check_redteam_report_recorded(qa4, None, None) is None
        assert E._check_redteam_three_piece(qa4, None, None) is None

    def test_real_transcript_gate_moment(self):
        """真实 transcript 截断到 15:23:02 -> pending 必为 1（假性 block 被 defer）。"""
        base = Path.home() / ".claude" / "projects"
        cands = list(
            base.glob(
                "*worktrees-tail-volume-acceleration-annualized/"
                "cfeafb35-cf42-4de2-8cc5-4c1eaf01cab2.jsonl"
            )
        )
        if not cands:
            pytest.skip("事故 transcript 不在本机")
        gate = "2026-08-05T15:23:02"
        kept = []
        for line in cands[0].read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                ts = (json.loads(line).get("timestamp") or "")[:19]
            except json.JSONDecodeError:
                kept.append(line)
                continue
            if ts and ts > gate:
                break
            kept.append(line)
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write("\n".join(kept) + "\n")
            tmp = fh.name
        try:
            mod = _load_hook("workflow_advance")
            assert mod._pending_background_agent_count(tmp) == 1
        finally:
            Path(tmp).unlink(missing_ok=True)


def test_task_id_regex_single_source():
    """engine 的 task-id 词形与 hook 的 agentId 词形同口径（16-17 hex）。"""
    import sys

    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    import dl_flow_engine as E

    for aid in (AID_LIGHT, AID_FULL, AID_REDTEAM):
        assert E._TASK_ID_RE.fullmatch(aid), aid
    assert not E._TASK_ID_RE.fullmatch("deadbeef")  # 太短
    assert re.fullmatch(r"[0-9a-f]{16,17}", AID_FULL)
