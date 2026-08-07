"""
hooks/workflow_phase.py 的单元测试（2026-07-26，harness-prompt-optimization P0/P2）。

对应 designs/harness-prompt-optimization-design.md §2/§4。
仿 test_dl_flow_engine.py 的 importlib 加载（hook 自带 engine 加载，parents[1]=dl-workflow 根）。

覆盖 _format_injection 的注入结构契约：
- P0：当前步 purpose 全文置顶（在骨架链之前）；非当前步 purpose 全文不出现
- P0：骨架链含 6 个 short 短名 + 【当前】标记在当前步
- P0：TaskList 块只留状态数据，指令散文已删
- P2：evidence 块含 ✓ 正例 / ✗ 反例 + 当前值模板；散文警告行已删
- held_for_gate 分支不回归（门栏提示在、子步骤块不在）
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

DLWF_ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "workflow_phase", DLWF_ROOT / "hooks" / "workflow_phase.py"
)
wp = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["workflow_phase"] = wp
_spec.loader.exec_module(wp)  # type: ignore[union-attr]

PROJECT_ROOT = Path("/home/admin/projects/factor_ic_analyzer")


def _state(sub_step_index: int, **overrides) -> dict:
    st = {
        "name": "demo",
        "phase": "understand",
        "index": 1,
        "gate": "pending",
        "sub_index": 1,
        "sub_total": 4,
        "sub_step_index": sub_step_index,
        "node": "understand:1",
    }
    st.update(overrides)
    return st


class TestCurrentStepFirst:
    """P0：当前步全文置顶 + 其余步骨架（design §2.1）。"""

    def test_current_step_block_before_chain(self):
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        i_cur = ctx.index("▶ 当前子步骤 3/6")
        i_chain = ctx.index("子步骤链")
        assert i_cur < i_chain

    def test_current_step_full_purpose_present(self):
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        node = wp.engine.get_node("understand", 1)
        assert node.sub_steps[2].purpose in ctx  # 子3 purpose 全文

    def test_non_current_step_purpose_absent(self):
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        node = wp.engine.get_node("understand", 1)
        # 非当前步（子1/子4）purpose 全文不出现——瘦身的核心断言
        assert node.sub_steps[0].purpose not in ctx
        assert node.sub_steps[3].purpose not in ctx

    def test_chain_has_all_short_labels_and_current_mark(self):
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        chain_line = next(line for line in ctx.splitlines() if "子步骤链" in line)
        for short in (
            "逼问定义",
            "拆解深挖",
            "双向取证",
            "质检裁决",
            "归一化陈述",
            "读回确认",
        ):
            assert short in chain_line
        assert "3.双向取证【当前】" in chain_line
        assert "1.逼问定义 ✓" in chain_line  # 已完成步标 ✓

    def test_tasklist_instruction_prose_removed(self):
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        # 指令散文删（在 output-style/phase-rules），状态数据留
        assert "TaskCreate 建齐" not in ctx
        assert "1. 理解和求证问题 -> in_progress" in ctx


class TestEvidenceBlockExamples:
    """P2：正反例替代散文警告（design §4.1）。"""

    def test_good_bad_examples_present(self):
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        assert "走 `--scaffold` 生成骨架" in ctx
        assert "✗ 反例（必 block）" in ctx

    def test_payload_schema_and_append_trace_command(self):
        # v2.14：载荷只含 purpose/q/a；结构字段脚本从 state 填（不再注入给模型照抄）
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        assert "【purpose】" in ctx  # v2.58 标记文本载荷（模型零接触 JSON）
        assert ".trace-payload-demo.md" in ctx
        assert "append-trace" in ctx
        assert "脚本从 state 自动填" in ctx

    def test_handwritten_jsonl_template_removed(self):
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        assert '"kind":"skill-trace"' not in ctx  # 手写整行 JSON 模板已删
        assert "字段：major_stage=phase 英文首字母大写" not in ctx  # 字段散文解释行
        assert "⚠️" not in ctx  # 占位符警告行


class TestHeldForGateUnchanged:
    """门栏扣留分支不回归（§subphase-hold-gate；门栏唯一处 = plan:4，2026-07-28 起）。"""

    def test_held_state_shows_gate_hold_not_steps(self):
        node = wp.engine.get_node("plan", 4)
        ctx = wp._format_injection(
            _state(
                5,
                phase="plan",
                index=2,
                sub_index=4,
                node="plan:4",
                held_for_gate=True,
            ),
            PROJECT_ROOT,
        )
        assert node.hold_for_gate  # fixture 前提
        assert "子阶段门栏" in ctx
        assert "▶ 当前子步骤" not in ctx
        assert "子步骤链" not in ctx


class TestLastStepInstruction:
    def test_step_done_marker_matches_current_step(self):
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        assert "### STEP_DONE: 3`" in ctx

    def test_last_step_mentions_hold_gate(self):
        # hold_for_gate 末步提示等 /dl gate（门栏唯一处 = plan:4 子5，2026-07-28 起）
        ctx = wp._format_injection(
            _state(5, phase="plan", index=2, sub_index=4, node="plan:4"), PROJECT_ROOT
        )
        assert "### STEP_DONE: 5`" in ctx
        assert "门栏" in ctx


class TestSelfcheckStepSpecific:
    """步级自查提示进注入（与 pass/block 续轮同文，engine.selfcheck_hint 单源）。"""

    def test_step1_injection_carries_step1_checklist(self):
        ctx = wp._format_injection(_state(1), PROJECT_ROOT)
        assert "本步自查：" in ctx
        assert "who/pain/why-now ≥3 类都覆盖了吗" in ctx

    def test_step3_injection_carries_step3_not_step1(self):
        # v2.38：子3 注入携带 fetch-prompt 子代理编排（selfcheck 披露），不带别步 checklist
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        assert "fetch-prompt" in ctx
        assert "who/pain/why-now ≥3 类都覆盖了吗" not in ctx  # 不带别步 checklist


class TestCorruptFormatRedline:
    """§corrupt-rework-detect C 侧：注入 ✗ 格式红线（单行合法 JSON）。"""

    def test_no_bypass_warning_present(self):
        # v2.14：手写 JSON 的事故警示收编进「禁止绕过 append-trace」
        ctx = wp._format_injection(_state(3), PROJECT_ROOT)
        assert "禁止绕过" in ctx
        assert "trace 隐形" in ctx


class TestPlanArtifactPath:
    """阶段产物规范位置注入（2026-07-28 用户决议）：主仓 .claude/<dir>/<name>.md，
    与 evidence 同级——worktree 归档删除时分支上产物一起丢，主仓才存活。"""

    def test_plan_phase_injects_artifact_path(self):
        ctx = wp._format_injection(
            _state(1, phase="plan", sub_index=2, node="plan:2", sub_total=4),
            PROJECT_ROOT,
        )
        assert f"{PROJECT_ROOT}/.claude/plans/demo.md" in ctx
        assert "禁写 worktree" in ctx or "worktree 删除即丢" in ctx

    def test_understand_phase_no_plan_path(self):
        ctx = wp._format_injection(_state(1), PROJECT_ROOT)
        assert ".claude/plans/" not in ctx

    def test_all_phase_artifact_paths(self):
        # understand/review/evolution 同法迁移（与 plan.md 同模式）：
        # 各阶段注入自己产物的主仓路径
        cases = [
            ("understand", 4, "understand:4", 5, "understands"),
            ("review", 0, "review:0", 0, "reviews"),
            ("evolution", 0, "evolution:0", 0, "evolutions"),
        ]
        for phase, sub, node_id, step, d in cases:
            ctx = wp._format_injection(
                _state(
                    step,
                    phase=phase,
                    sub_index=sub,
                    node=node_id,
                    sub_total=4 if phase == "understand" else 0,
                ),
                PROJECT_ROOT,
            )
            assert f"{PROJECT_ROOT}/.claude/{d}/demo.md" in ctx, node_id
            assert "禁写 worktree" in ctx or "worktree 删除即丢" in ctx


class TestSettingsStalenessNotice:
    """v2.35 防静默权限税（症状 R）：per-wf settings 模板版本落后时给警告文案。

    settings 文件缺失不警告（那是症状 A1 的另一类问题，不误报）；字段缺失
    计 v0 = 落后（版本戳前的存量 settings 全部命中，`dl <name> --resume` 补写
    自愈）；JSON 损坏静默容错（UserPromptSubmit 通道永不因此炸掉）。
    """

    def _write_settings(self, root: Path, text: str) -> None:
        d = root / ".claude" / "workflows" / "t"
        d.mkdir(parents=True)
        (d / "settings.json").write_text(text, encoding="utf-8")

    def test_stale_version_warns_with_resume_pointer(self, tmp_path):
        self._write_settings(tmp_path, json.dumps({"wf_settings_template_version": 0}))
        notice = wp._settings_staleness_notice(tmp_path, "t")
        assert "--resume" in notice and "t" in notice
        assert str(wp.engine.SETTINGS_TEMPLATE_VERSION) in notice

    def test_missing_version_field_counts_as_stale(self, tmp_path):
        self._write_settings(tmp_path, json.dumps({"outputStyle": "workflow"}))
        assert wp._settings_staleness_notice(tmp_path, "t")

    def test_current_version_silent(self, tmp_path):
        self._write_settings(
            tmp_path,
            json.dumps(
                {"wf_settings_template_version": wp.engine.SETTINGS_TEMPLATE_VERSION}
            ),
        )
        assert wp._settings_staleness_notice(tmp_path, "t") == ""

    def test_missing_file_silent(self, tmp_path):
        assert wp._settings_staleness_notice(tmp_path, "t") == ""

    def test_malformed_json_silent(self, tmp_path):
        self._write_settings(tmp_path, "{oops")
        assert wp._settings_staleness_notice(tmp_path, "t") == ""


class TestArtifactSectionsSync:
    """注入 + output-style 的产物节名与单源一致（2026-08-02，P2 #4）。

    断链场景：有人把动态构建改回手写字面量并写错节名 -> 此红。
    """

    def test_injection_artifact_strings_contain_sections(self):
        cases = {
            "understand": "understand.md",
            "plan": "plan.md",
            "review": "review.md",
            "evolution": "evolution.md",
        }
        for phase, basename in cases.items():
            desc = wp.PHASE_RULES[phase]["artifact"]
            for s in wp.engine.ARTIFACT_SECTIONS[basename]:
                assert s in desc, (phase, s)

    def test_output_style_contains_sections(self):
        text = (DLWF_ROOT / "output-styles" / "workflow.md").read_text(encoding="utf-8")
        for secs in wp.engine.ARTIFACT_SECTIONS.values():
            for s in secs:
                assert s in text


class TestAssemblyStepReminder:
    """v2.123：装配步硬提醒——当前步=节点末步且节点挂 ARTIFACT 机械门时，
    注入单列一行 render-artifact 命令（钉在 ▶ 当前步块后）。

    背景（tail_volume 2026-08-06 审计）：装配义务埋在末步长 purpose 中段，
    一轮内 4/4 装配步首忘（u:4#5/plan:2#5/plan:3#6/plan:4#5 全吃
    「产物未落地/缺节」机械 block，各白返工一轮）。提醒与 gate 同降级口径：
    产物标识非单文件/路径缺失 -> 不出提醒（宁纵勿枉）。
    """

    def test_last_step_of_gated_node_shows_reminder(self):
        ctx = wp._format_injection(
            _state(5, sub_index=4, node="understand:4"), PROJECT_ROOT
        )
        assert "装配义务" in ctx
        assert "render-artifact understand.md" in ctx
        assert f"{PROJECT_ROOT}/.claude/understands/demo.md" in ctx

    def test_plan2_last_step_reminder_names_plan_md(self):
        ctx = wp._format_injection(
            _state(5, phase="plan", index=2, sub_index=2, node="plan:2", sub_total=4),
            PROJECT_ROOT,
        )
        assert "装配义务" in ctx
        assert "render-artifact plan.md" in ctx

    def test_non_last_step_of_gated_node_no_reminder(self):
        ctx = wp._format_injection(
            _state(4, sub_index=4, node="understand:4"), PROJECT_ROOT
        )
        assert "装配义务" not in ctx

    def test_ungated_node_last_step_no_reminder(self):
        # understand:1 无 ARTIFACT 机械门——末步也不出提醒
        ctx = wp._format_injection(_state(6), PROJECT_ROOT)
        assert "装配义务" not in ctx

    def test_held_for_gate_no_reminder(self):
        # 门栏扣留态不出子步骤块 -> 提醒也不出现（防残留误导）
        ctx = wp._format_injection(
            _state(
                5,
                phase="plan",
                index=2,
                sub_index=4,
                node="plan:4",
                sub_total=4,
                held_for_gate=True,
            ),
            PROJECT_ROOT,
        )
        assert "装配义务" not in ctx


class TestPayloadPathInjection:
    """v2.125：注入的载荷路径 = worktree 根（state 有 worktree_path 时）。"""

    def test_injection_shows_worktree_payload_path(self):
        ctx = wp._format_injection(_state(1, worktree_path="/wt/demo"), PROJECT_ROOT)
        assert "/wt/demo/.trace-payload-demo.md" in ctx

    def test_injection_fallback_without_worktree_path(self):
        ctx = wp._format_injection(_state(1), PROJECT_ROOT)
        assert f"{PROJECT_ROOT}/.claude/evidence/.trace-payload-demo.md" in ctx
