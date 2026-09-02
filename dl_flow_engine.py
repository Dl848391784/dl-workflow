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
import shutil
import subprocess
import sys
import tempfile
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
    _CHANGE_SPEC_RULE,  # noqa: F401  # re-export：2026-08-27 checks 拆出后 eng.* 访问面保持
    _NODES,  # tests 经 eng._NODES 访问（有意 re-export）
    _ROOT_CAUSE_LINE_RULE,  # noqa: F401  # re-export：同上行拆分缘由
    current_node_id,  # noqa: F401  # re-export：tests 经 eng.current_node_id 访问
    get_node,
    is_gated_after,
    minor_key_map,  # noqa: F401  # re-export：tests/evidence_show 经 eng.minor_key_map 访问
    next_phase,
    node_id,
    phase_index,
    sub_total,
    subphase_labels,
    tacet_silent_steps,  # force-tacet 实验轨道（designs/force-tacet-experiment-design.md）
    TACET_SPINE_STEPS,  # noqa: F401  # re-export：tests 经 eng.TACET_SPINE_STEPS 访问
    TACET_SPINE_STEPS_FERMATE,  # fermate 组合脊柱（fermate-plan-only-design §2.4）
    FERMATE_SILENT_STEPS,  # fermate 裁剪静默步集（u4-sub3-fermate-cut-design §1.2①）
    fermate_cut_node,  # fermate 轨道节点裁剪单源（dl_flow_nodes，展示层共用）
)

# ---------- state/trace 低层 helper（单源在 dl_flow_common.py，2026-08-27 拆分）----------
from dl_flow_common import (
    _PHASE_ARTIFACT_DIRS,
    _evidence_path,
    _iter_trace_segments,
    _node_entered_at,
    _now,
    load_state,
    normalize_state,
    read_evidence,
    read_evidence_for_step,
    state_path,
    sub_step_at,
    sub_step_has_trace,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    trace_payload_path,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
)

# ---------- v2.27 机械预检家族（单源在 dl_flow_checks.py，2026-08-27 拆分）----------
from dl_flow_checks import (
    _ABSENCE_CLAIM_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _ABSENCE_DEMOTE_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _ABSENCE_EXEMPT_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _AQ_ARRAY_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _AQ_ITEM_LABEL_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _AQ_LABEL_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _ASKQ_ANN_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _ASSUMPTION_CARRY_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _ASSUMPTION_LABEL_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _BASELINE_TOOL_TRACE_KEYWORDS,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _CHANGE_SPEC_ENTRY_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _CONSTRAINT_TOOL_TRACE_KEYWORDS,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _DECLARED_ATOM_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _DEMOTE_RING_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _DEPENDENCY_PAIR_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _ELEMENT_SYMBOL_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _EPC_SYMBOL_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _EVIDENCE_POINTER_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _EXCLUDE_INFERENCE_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _FEASIBILITY_DUP_CLAIM_WORDS,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _FEASIBILITY_DUP_QUERY_VERBS,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _FEASIBILITY_EXIST_CLAIM_WORDS,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _FEASIBILITY_ITEM_GROUPS,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _FEASIBILITY_STATE_WORDS,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _FERMATE_PLACEHOLDER_TOKEN,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _FETCH_TIERS,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _FORWARD_LINK_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _GOAL_LABEL_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _HOW_PURE_VERB_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _HYP_EXCLUDE_ABSENCE_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _ID_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _IF_THEN_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _KIND_PREFIX_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _LIST_PREFIX_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _MAYBE_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _MECH_EXTRA_ITEM_CHECKS,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _MECH_EXTRA_STR_CHECKS,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _MECH_QA_CHECKS,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _MECH_STATEMENTS_CHECKS,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _NEED_ACTION_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _NEED_SYMBOL_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _NONCODE_FILE_SUFFIXES,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _NONE_TIER_PATH_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _NOTE_ENTRY_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _NOUN_L,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _NOUN_R,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _NOUN_SKIP_EXTS,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _NO_LOAD_LIST_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _PLACEHOLDER_MARKERS,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _PUGH_CAND_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _PUGH_CELL_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _QUOTE_LABEL_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _REDTEAM_CONFIDENCE_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _REGISTRY_CAPABILITY_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _REJECTED_LABEL_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _REJECTED_RATIONALE_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _RING_START_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _ROOT_CAUSE_CODE_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _ROOT_CAUSE_LINE_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _SC_ID_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _TASK_ID_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _TERRAIN_FILELINE_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _TERRAIN_SYMBOL_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _TOPO_ORDER_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _WHO_REPO_FACT_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _WIDE_SPAN_LIMIT,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _WIDE_SPAN_RE,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_answer_no_reverse_inference,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_answer_source_marker,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_assumption_completeness_trace,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_assumption_propagation_trace,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_atomic_mece_alignment,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_baseline_tool_trace,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_binding_residue_trace,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_causal_ring_no_untested,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_change_list_anchor,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_change_point_anchor,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_change_spec_anchor,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_conclusion_no_speculation,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_constraint_verification_tool_trace,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_dependency_order_trace,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_element_coverage_trace,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_element_quote_trace,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_epc_quote_trace,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_feasibility_verification_trace,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_fermate_placeholder_consistency,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_fetch_preflight_out,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_fetch_report_recorded,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_fetch_skeleton_out,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_fetch_tier_items,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_goal_candidate_traceability_alignment,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_hypothesis_exclude_no_absence,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_need_quote_trace,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_no_load_trace,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_pugh_net_score_consistency,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_pugh_traceability_forward_coverage,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_pattern_enum_declared,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_redteam_report_recorded,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_redteam_three_piece,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_regression_guard_declared,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_rejected_rationale_trace,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_root_cause_anchor_verify,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_sc_coverage_trace,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_single_phase_argument,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_terrain_tool_trace,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_user_decision_recorded,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_user_quote_channel,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_value_no_unsourced_inference,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _check_who_no_repo_fact,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _codegraph_symbol_spans,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _dispatched_vs_unrecorded_task_ids,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _feasibility_segment,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _file_line_count,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _git_tracked_files,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _implementation_nouns,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _load_atomic_questions,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _placeholder_hit,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _recorded_task_ids_in_evidence,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _redteam_worker_file,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _source_step_index,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _step_trace_ids,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _verify_anchor_parts,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _verify_change_spec_entry,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _wf_artifact_mtime_stale,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    payload_format_hint,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
)

# ---------- 子阶段边界交接（单源在 dl_flow_handoff.py，2026-08-27 第二轮拆分）----------
from dl_flow_handoff import (
    HANDOFF_PROMPT_T1,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    HANDOFF_PROMPT_T2,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    NO_MCP_ARGS,
    _HANDOFF_KINDS,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _PACK_PRIOR_BOUNDARY_MAX,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _PACK_PRIOR_Q_MAX,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _PACK_REPORT_A_MAX,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _PACK_TRACE_DROP_KEYS,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _SEGMENT_STRIP_ENV,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _last_handoff_event,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _slim_trace_for_pack,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _truncate,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    _write_handoff_record,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    estimate_context_tokens,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    handoff_pack,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    handoff_tier,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    segment_spawn_overrides,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    write_handoff_prompt,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
    write_handoff_resolution,  # noqa: F401  # re-export：tests/hooks 经 eng.* 访问
)

# ---------- trace 解析/装配/写入（单源在 dl_flow_trace.py，2026-08-27 第二轮拆分）----------
from dl_flow_trace import (
    _FIELD_SCAFFOLD_HINTS,  # noqa: F401  # re-export：tests/hooks 经 eng._FIELD_SCAFFOLD_HINTS 访问
    _MD_HEADER_RE,  # noqa: F401  # re-export：tests/hooks 经 eng._MD_HEADER_RE 访问
    _MD_ITEM_FIELDS,  # noqa: F401  # re-export：tests/hooks 经 eng._MD_ITEM_FIELDS 访问
    _MdErr,  # noqa: F401  # re-export：tests/hooks 经 eng._MdErr 访问
    _TRACE_STRUCT_FIELDS,  # noqa: F401  # re-export：tests/hooks 经 eng._TRACE_STRUCT_FIELDS 访问
    _curl_probe,  # noqa: F401  # re-export：tests/hooks 经 eng._curl_probe 访问
    _extract_predispatch_report,  # noqa: F401  # re-export：tests/hooks 经 eng._extract_predispatch_report 访问
    _insert_report_item,  # noqa: F401  # re-export：tests/hooks 经 eng._insert_report_item 访问
    _parse_trace_md,  # noqa: F401  # re-export：tests/hooks 经 eng._parse_trace_md 访问
    _subagent_dir,
    append_trace,
    fetch_prompt,
    ingest_agent_report,
    ingest_redteam_report,
    pid_alive,  # noqa: F401  # re-export：tests/hooks 经 eng.pid_alive 访问
    redteam_prompt,
    run_fetch_preflight,
    scaffold_payload,
)

# 组件 B：项目工具注册发现（list-tools / S15 白名单用；scripts 为命名空间包）。
from scripts.workflow import project_tools  # noqa: E402

# 子步骤门控连续 block 升级阈值：达到后不再让模型盲目重做，
# 注入提示请用户裁决（补充信息 / /dl step-pass 强制放行 / /dl back 回退）。
# rubric 对用户是黑盒，升级出口是「用户裁决」而非「放宽判据」。
SUB_STEP_BLOCK_ESCALATE = 3

# P2-4 段链合并白名单（designs/segment-chain-resume-design.md）：仅这些节点的
# 连续 headless-step 以 --resume 同会话续跑（会话合并非派发合并，逐步派发+步间
# gate 不变）。链粒度=minor_state：node-rules system prompt 按节点生成（跨节点
# 续跑前缀缓存即失效）+ handoff 交接在 minor_state 边界重置。
# **置空 frozenset() = 全局关（回滚面）**。
# 2026-08-14 用户裁决：u:1 纳入段链（子2-子6 连续 headless 重步，此前单步实测
# 168k 上下文；链化收益最大但峰值风险同大，首飞需监控链峰值）。u:2/3/4 与
# plan:1-4 护栏数据见 2026-08-13 试点（22/22 一次过、链峰值 111-149k << 250k、
# 零 chain_broken_fallback）。链峰值监控阈值 250k 不变。
# 2026-08-17 回滚 u:1（执行 08-14 裁决的预授权回滚条件，
# designs/u1-sub4-cost-optimization-design.md 修 3）：amplitude_annualized D 轮
# 链峰值 324k > 250k 护栏 + deepseek 跨进程 resume 前缀缓存时灵时不灵
# （D 轮链内 step2→5 首调 fresh 44k→109k→166k→241k 全冷，F 轮暖 158k hit）——
# 冷轮时链 = 纯增税（每步首调重付单调涨的继承上下文），暖轮也比 fresh 段贵
# ~2 倍（每轮重读 ~160k vs ~70k）。
# 2026-08-18 断链 u:2（designs/u2-sub3-cost-optimization-design.md，用户裁决
# 覆盖 08-17「u:2 峰值未破保留」项——那是 surgical 保留非成本最优判定）：
# u2_sub1_ab/u2_sub2_ab 两轮实测 u:2#3/#4 段首调 cache_read=0（deepseek 会话
# 隔离缓存下链恒冷=纯增税，#3 冷启动 60.3k=本步 fresh 73%、#4 94.1k=98%）；
# fresh 段首调恒定 ~45k 不随前序轮数涨，交接包（v2.45）材料完备性已逐字段核对。
# 2026-08-18 u:3 断链（designs/u3-sub2-cost-optimization-design.md §6）：两轮
# live A/B 实证——①链税实测定案（#3 首调 71,862 cr=0 + #4 首调 106,780
# cr=1,792 = 178.6k 纯增税，占链合计 fresh 73%）；②段内续步 EV 证伪（续步
# 边界暖率 1/4：暖 -68k vs 冷全额重写 65-122k；断链 fresh 段 ~28-31k/步恒定，
# EV 远优且逐出敞口随上下文单调涨的风险同步灭）。交接包材料完备性逐字段核对
# 见设计 §2。2026-08-19 u:4 断链（designs/u4-sub3-cost-optimization-design.md
# L1，用户降本指令覆盖「峰值未破保留」防爆默认）：u4_sub2_ab B 轮实测 u:4#3
# 首调 44,747(cr=0)+#4 首调 74,227(cr=512≈冷)=118,974 纯增税——deepseek 会话
# 隔离缓存下链恒冷（#20 三要素全中）；各步输入契约经交接包逐字段核对完备
# （#2←SC#1/#3←SC#2/#4←SC#3 trace 全文在包），fresh 段恒定地板（#2 已实证
# 13,658）。断链第五例（u:1 回滚/u:2/u:3 后），不入 MERGED（步体非极小搬运型
# +续步暖率彩票两节点 EV 证伪，#24 口径）。
# 2026-08-20 plan:2 断链第六例（节点级摘除，designs/
# p2-sub2-cost-optimization-design.md L1）：p2_sub2_base A 轮实测链会话上下文
# 250,669 tok 突破 250k 护栏（driver 日志实锤）+子2 链内首调 fresh 175,890
# （子1 transcript 1.0MB 冷重写，cr=0 恒冷）——#9 配套范式「链峰值 250k 突破
# 即执行回滚无需再裁决」机械触发（u:1 324k 后第二例）；交接包材料完备性逐字段
# 核对见设计 §2 L3。回滚面=重新入册。plan:1/3/4 链峰值未破，保留（surgical）。
SEGMENT_CHAIN_NODES = frozenset(
    {
        "plan:1",
        "plan:3",
        "plan:4",
    }
)

# 段链步级豁免集（p1-sub5-cost L5，2026-08-20，designs/
# p1-sub5-cost-optimization-design.md——断链第六例、首例步级粒度）：
# 链白名单是节点级，本集做步级摘除——(node_id, sub_step) 命中即不续链
# （fresh spawn），链内其余步零行为变化。plan:1#5（归一化陈述）判据：
# #20 deepseek 会话隔离缓存下链首调冷（A 段 143k 冷重写实锤）+ #24 前序
# 上下文巨大（子3+子4 transcript）携带税主导、断链确定优；材料经交接包
# 逐字段核对完备（子1-子4 trace 全文在包，设计 §2 L2）；后续步=子6 交互
# 恒 fresh spawn 零暴露面（#30 扩面核对）。豁免集即回滚面（摘条目=恢复链）。
# 2026-08-20 plan:3#2 步级摘除（p3-sub2-cost，步级第二例，designs/
# p3-sub2-cost-optimization-design.md L2）：#20 链首调恒冷（A 轮 104,483
# cr=0 = 子1 transcript 冷重写）+ #24 前序上下文携带税主导；材料经交接包
# 逐字段核对完备（子1 need_baseline trace 全文在包）。子3 侧效应 = 链
# resume 换挂子2 fresh 会话（继承 transcript 变小，同向）。节点白名单
# 不动、plan:3 其余步零行为变化（surgical，节点级断链否决理由见设计 §3）。
# 2026-08-20 plan:3#3 步级摘除（p3-sub3-cost，步级第三例，designs/
# p3-sub3-cost-optimization-design.md L1）：#20 链首调恒冷（p3_sub2_ab
# 子2 段末调 cr=0 实锤，链内子3 首调 = 子2 transcript ~101k 全额冷重写）
# + #24 携带税主导（p2_sub3_ab 老链段子3 实测每调 cr ~134k×16 轮）；
# 材料经交接包逐字段核对完备（子1 need_baseline/子2 capability_registry
# trace 全文在包=输入契约全集）。子5 侧效应 = 链 resume 换挂 fresh 会话
# （继承 transcript 变小，同向；子4 亦豁免见下，其「子4 resume 子3」
# 侧效应被子4 自身摘除取代）。
# 2026-08-20 plan:3#4 步级摘除（p3-sub4-cost，步级第四例，designs/
# p3-sub4-cost-optimization-design.md L1）：#20 链首调恒冷（免跑基线
# p3_sub3_base 子4 链内段首调 fresh 190,802 / cr=1,024 = 子2+子3
# transcript 冷重写实锤）+ #24 携带税主导（段 cr 1,446,016 / 15 轮 ≈
# 96k/轮）。材料经交接包逐字段核对完备（子4 input=step3.binding_proposals，
# 本节点前序 trace 全文通道在包）。后续步子5 resume 子4 fresh 会话=
# 携带量变小（一段 vs 三段），无 fresh 化暴露面（#30 扩面核对）；
# 节点白名单不动、plan:3 其余步零行为变化。
# 2026-08-20 plan:3#5 步级摘除（p3-sub5-cost，步级第五例，designs/
# p3-sub5-cost-optimization-design.md L1）：#20 链首调恒冷（A 轮
# 239,576/cr=1,024 = 子2+3+4 链会话 211k 全量冷重写，pre-p3-sub4-merge
# 链形态=最大口径）+ #24 携带税主导（段 cr 1.03M/5 轮单调涨）；材料经
# 交接包逐字段核对完备（子1 需求清单/子2 注册表+强制路由核对/子3 绑定
# 提案+不加载清单/子4 可用性核验+假设=输入契约全集 trace 全文在包，
# 装配不变量测试钉死）；后续步=子6 确认级无会话零暴露面（#30）。
# plan:3 链成员仅剩子1/子6 名义在册——节点级断链重审登记（设计 §9）。
# 2026-08-20 plan:4#2 步级摘除（p4-sub2-cost，步级第六例、plan:4 首例，
# designs/p4-sub2-cost-optimization-design.md L1）：#20 链首调恒冷（免跑
# 基线 p2_sub3_ab plan:4#2 链内段首调 fresh 169,338 / cr=0 = 子1 31 轮
# transcript 冷重写实锤）+ #24 携带税主导（段 cr 1.86M / 12 轮 ≈ 155k/
# 轮）。材料经交接包逐字段核对完备（子2 input=step1.control_baseline，
# 本节点前序 trace 全文通道在包=输入契约全集，装配不变量测试钉死）。
# 后续步子3 resume 换挂子2 fresh 会话（继承 transcript 从「子1 31 轮+
# 子2」缩为「子2 ~7 轮」，携带量变小同向），无 fresh 化暴露面（#30 扩
# 面核对）；节点白名单不动、plan:4 其余步零行为变化。
# 2026-08-20 plan:4#3 步级摘除（p4-sub3-cost，步级第七例、plan:4 第二例，
# designs/p4-sub3-cost-optimization-design.md L1）：#20 链首调恒冷（子2
# fresh 化后子3 链 resume 挂子2 fresh 会话，首调=子2 transcript 冷重写
# cr=0）+ #24 携带税主导（继承子2 transcript 每调重读）。材料经交接包
# 逐字段核对完备（子3 input=step2.control_proposals，子2 trace 全文通道
# 在包=输入契约全集，装配不变量测试钉死）。后续步子4 归一化 resume 换挂
# 子3 fresh 会话（携带量变小同向），无 fresh 化暴露面（#30 扩面核对）；
# 节点白名单不动、plan:4 其余步零行为变化。
# 2026-08-20/21 plan:4#4 步级摘除（p4-sub4-cost，步级第八例、plan:4
# 第三例——p4-sub3-cost 先 merge 占第七/第二例，复核成立，
# designs/p4-sub4-cost-optimization-design.md L1）：#20 链首调恒冷
# （A 臂 p4_sub4_base 实测：子4 链内首调 fresh 248,136/cr=1,024=子2+
# 子3 transcript 全额冷重写）+ #24 携带税主导（归一化步步体小，每调
# 背子2+子3 全量继承上下文单调涨；段 cr 2.13M/10 轮）。材料经交接包
# 逐字段核对完备（子4 input=step3.verified_controls，gate 判材=子1/2/3
# 前序 trace 对照面=本节点前序 trace 全文通道在包=输入契约全集，
# 装配不变量测试钉死）。后续步=子5 确认级（P3-1）无模型会话零暴露面
# （#30 扩面核对）；节点白名单不动、plan:4 其余步零行为变化。
# plan:4 链成员仅剩子1/子5 名义在册（子5 确认级无会话）——节点级
# 出册重审登记（plan:3 同型）。
SEGMENT_CHAIN_SKIP_STEPS = frozenset(
    {
        ("plan:1", 5),
        ("plan:3", 2),
        ("plan:3", 3),
        ("plan:3", 4),
        ("plan:3", 5),
        ("plan:4", 2),
        ("plan:4", 3),
        ("plan:4", 4),
    }
)

# 段内续步白名单（u2-sub4-cost，2026-08-18 用户裁决「段内续步」方案）：
# 名单内节点的连续非交互子步骤在同一 claude -p 进程内续跑（--input-format
# stream-json 多轮，driver 逐步注入任务 prompt，gate 照跑）——deepseek 会话
# 隔离缓存下跨进程段首调必冷（恒定地板 ~44.6k/段，u2_sub3_ab 实测 #4 冷启动
# 占本步 fresh 81%），进程内暖（探针 turn2 fresh=95/cr 暖）；续步 prompt 剥
# 交接包（会话内已有真迹）。白名单即回滚面；与 SEGMENT_CHAIN_NODES 互斥
# （understand:2 已断链，merged 路径不走 _chain_resume_sid/_chain_update）。
# 扩面判据 = cost-optimization #20（provider 缓存语义 × 冷启动口径逐节点审）。
# understand:3 曾入本名单又撤出（2026-08-18，u3-sub2-cost §6）：两轮 live
# 实测续步边界暖率仅 1/4（deepseek 逐出激进），续步冷时=全额重写单调涨的
# 继承 transcript（#4 达 122k），EV 不如 fresh 段恒定地板（~28-31k/步）——
# 断链而非续步，见 SEGMENT_CHAIN_NODES 上方注释。
MERGED_RUN_NODES = frozenset({"understand:2"})

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
SETTINGS_TEMPLATE_VERSION = (
    10  # v10：项目工具 command 头并入 allowlist（wf_write_settings 补写，
)
# project_tool_heads() 过滤后只加只读发现类——codebase-archaeology-toolbox-design
# §3.2 action 3 / §4 row 5；空工具 = 零改动。
# v9：statusLine 进度栏入模板（dl_statusline.py，refreshInterval=10 空闲
# 也刷新，v4-statusline-progress-design）——front 模式段工人零可见性 dogfood 修复。
# v8：front 模式段派发命令（dl_drive.py --segment）入白名单——否则前台会话
# 每次派发都弹窗（front-tui-hybrid-design M3）。
# v7：两轮实测命令头挖掘补尾（路径形态 codegraph/venv python/pytest +
# xargs/tr/comm/od/xxd/env/sleep）；刻意不加 rm/dd/sudo——破坏性命令保留弹窗
# = 弱模型幻觉刹车；正向名单可收敛，deny 反向名单是打地鼠。
# v6：Read 放宽到主仓全树 Read(//主仓/**)——Bash 只读命令触及 cwd 外
# 主仓路径时过路径级检查，命令头白名单管不住（2026-08-07 实测 harness 自建议
# 该规则）。Edit 刻意不放宽：主仓源码编辑保持弹窗=守卫（编辑目标是 worktree）。
# v5：补 Read(//主仓/.claude/**) + Read(//~/.dl-workflow/**)
# ——acceptEdits 不覆盖 Read，模型按编排协议读主仓 .claude/（cwd 外）每次弹窗
# （2026-08-07 实测 permissionDecisionMs=28.5s）。
# v4：删死规则 Write(//path)（文件权限只认 Edit(path)，
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
    # 编排节点末步会经本函数直接推进到下一个编排节点（understand:1 子7 ->
    # understand:2）——不重置会把 sub_step_index=7 带进只有 5 步的
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


def _clear_workflow_discoveries(project_root: Path, name: str) -> None:
    """state-reset 清账：删除 discoveries.jsonl（回滚后旧发现基于作废结论）；缺失/失败非错误。"""
    p = project_root / ".claude" / "workflows" / name / "discoveries.jsonl"
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass


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
    d = _subagent_dir(project_root, name)
    if d is None:
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


def assembly_obligation_hint(
    node: Node, project_root: Path | None, name: str | None
) -> str | None:
    """装配步硬提醒（workflow_phase 注入用，v2.123）。None=无义务/降级不出。

    背景（tail_volume 2026-08-06 审计）：装配义务埋在末步长 purpose 中段，
    一轮内 4/4 装配步首忘（u:4#5/plan:2#5/plan:3#6/plan:4#5 全吃「产物未落地/
    缺节」机械 block，各白返工一轮全上下文）。在 ▶ 当前步块后单列一行钉死。
    与 gate_verdict_mech 同降级口径（宁纵勿枉）：无 ARTIFACT 机械门、
    name/project_root 缺失、产物标识非单文件 -> None。
    """
    if node.gate_mech not in (GateMech.ARTIFACT_EXISTS, GateMech.ARTIFACT_CONTAINS):
        return None
    if project_root is None or name is None:
        return None
    f = _artifact_file(node, project_root, name)
    if f is None:
        return None
    return (
        "- ⚠ 本步有装配义务：STEP_DONE 前必须先跑 `python3 "
        f"~/.dl-workflow/dl_flow_engine.py render-artifact {node.artifact}`"
        f"（机械装配落 `{f}`，禁手写产物）——忘跑 = gate 机械校验必 block，白返工一轮"
    )


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


def next_decision_interactive_step(
    phase: str, sub: int, cur: int
) -> "tuple[Node, int, Step] | None":
    """线性序下一个 decision 级交互步（u2-sub1-cost 修A——NEXT_PREP 跨节点扩展）。

    扫描规则（从 (phase, sub) 的 cur 之后开始，按 _NODES 声明序 = 编排推进序）：
    - confirm 级交互步跳过（P3-1 后无模型会话、无问答可备）；
    - 撞非交互工作步即停 None——该步自己的段是更好的顺带交付点（不抢）；
    - 无子步骤编排的节点（execute/review/evolution）自然越过不命中。
    返回 (目标节点, 目标步号, 目标 Step) 或 None。
    动机：u:1#6 的下一步 u:1#7 是 confirm 级读回（无模型会话），旧 lookahead
    只看同节点 cur+1 → prep_next=None → u:2#1 落回独立 prep 段（纯系统税）；
    u:1#6 段上下文（子1 原话在交接包 + 子6 陈述刚产出）恰好是设计 u:2#1
    问题的全部材料，顺带交付后独立 prep 段整段消失。
    """
    nids = list(_NODES)
    start = nids.index(node_id(phase, sub))
    for o in range(start, len(nids)):
        node = _NODES[nids[o]]
        steps = node.sub_steps or ()
        begin = cur + 1 if o == start else 1
        for i in range(begin, len(steps) + 1):
            s = steps[i - 1]
            if not getattr(s, "interactive", False):
                return None
            if getattr(s, "tier", "decision") == "confirm":
                continue
            return (node, i, s)
    return None


def step_needs_evidence(step: Step) -> bool:
    """子步骤是否需读 evidence.jsonl 喂 judge（与 rubric_needs_evidence 同关键词判定）。

    §orchestration v2：子步骤 gate 文本含 "evidence/" 或 "skill-trace" 即读 evidence。
    """
    r = step.gate or ""
    return "evidence/" in r or "skill-trace" in r


# ---------- 上下文交接（context-handoff-design，v2.45）----------
#
# 主会话成本 = Σ(每轮)当前上下文长度；会话不重置则上下文单调涨（u:1 实测
# 54k->283k），成本随轮次平方膨胀。交接架构：子步边界 /clear 换全新上下文，
# 只带机械装配的交接包——成本掰成线性。门控读磁盘状态（state+evidence），
# 天然会话无关，这是架构成立的地基。


# ---------- 产物机械装配（render-artifact，v2.59）----------
#
# 四桶分工审计（2026-08-02 用户指令全系统检查）：产物装配 purpose 自写
# 「直接装配、禁二次创作」=系统承认这是转录，却让模型手工抄 trace 拼产物
# 再由 ARTIFACT_CONTAINS 门检查抄对没有——脚本一条命令的事，模型花一整步
# +一轮门控还多抄错/抄漏失败面。render-artifact 从各节点最新 statements/
# 裁决 trace 机械装配 understand.md/plan.md，模型零接触产物文件。
# 内容要改 = 改对应步 trace 后重渲染（trace 仍是唯一真源）。
# design.md 装配已退役（designs/design-md-assembly-retire-design.md）：
# 工作流内部零消费（下游 judge 读 evidence 不读产物文件），H8 按路径分流——
# dl-workflow 驱动改动豁免 design.md，非工作流改动仍手写。
_ARTIFACT_RENDER_SOURCES: dict[str, dict] = {
    "understand.md": {
        # 节名 = ARTIFACT_SECTIONS 单源；源 = (minor_stage, 归一化步 sub_step)。
        "sections": {
            "真实问题重述": ("ProblemContext", 6),
            "目标价值": ("GoalsAndValue", 4),
            "范围约束": ("ScopeAndConstraints", 4),
            "成功标准验收包": ("SuccessCriteria", 4),
        },
        # 读回步（裁决记录源：qa 标题含「裁决」/「读回」的项原文收录）。
        "decision_steps": (
            ("ProblemContext", 7),
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
}


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
) -> tuple[bool, str]:
    """render-artifact：从 evidence 最新 trace 机械装配产物（v2.59）。

    返回 (ok, 消息)。源 trace 缺失时按 spec 处理（require_all=缺一节即拒；
    否则跳过该节并在输出点名）。幂等覆盖写，落主仓 .claude/<out_dir>/<name>.md。
    """
    spec = _ARTIFACT_RENDER_SOURCES.get(basename)
    if spec is None:
        return False, (
            f"render-artifact 不支持 {basename}（支持："
            + "/".join(sorted(_ARTIFACT_RENDER_SOURCES))
            + "）"
        )
    text = read_evidence(project_root, name)
    if not text:
        return False, f"evidence 缺失——{name}.jsonl 不存在或为空"
    latest: dict[tuple, dict] = {}
    tacet_silent: set[tuple] = set()  # force-tacet：沉默源步（占位节依据，design §5）
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("kind") == "tacet":
            tacet_silent.add((rec.get("minor_stage"), rec.get("sub_step")))
            continue
        if rec.get("kind") != "skill-trace":
            continue
        latest[(rec.get("minor_stage"), rec.get("sub_step"))] = rec

    parts = [
        f"# {name} · {basename}",
        "",
        "（render-artifact 机械装配，禁手改——改内容请改对应步 trace 后重渲染）",
        "",
    ]
    missing = []
    for sec, (minor, stp) in spec["sections"].items():
        rec = latest.get((minor, stp))
        stmts = (rec or {}).get("statements")
        if not stmts:
            if (minor, stp) in tacet_silent:
                # force-tacet：沉默源节占位装配（防下游路径断 + 诚实可见），
                # 计入已装配节（require_all 视为满足）。
                parts.append(f"## {sec}")
                parts.append("")
                parts.append(
                    "**[TACET 沉默：本节来源步未执行（force-tacet 实验轨道）]**"
                )
                parts.append("")
                continue
            missing.append(f"{sec}（{minor} 子{stp} 无 statements trace）")
            continue
        parts.append(f"## {sec}")
        parts.append("")
        for it in stmts:
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

    out = project_root / ".claude" / spec["out_dir"] / f"{name}.md"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    except OSError as e:
        return False, f"写产物失败：{e}"
    note = f"；跳过缺源节：{'、'.join(missing)}" if missing else ""
    html_note = _render_html_companion(out)
    return (
        True,
        f"✓ 已装配 {out}（{len(spec['sections']) - len(missing)} 节 + 裁决记录{note}）{html_note}",
    )


# ---------- 产物 HTML 伴随导出（artifact-html-export）----------
# md 是唯一真源（给模型），HTML 是赠品（给人看）：bun 缺失/转换失败/超时
# 一律降级为消息注记，绝不阻断 render_artifact（designs/artifact-html-export-design.md）。
_HTML_BUN_CACHE: list[str] | None = None
_HTML_BUN_MISSING = False  # _HTML_BUN_CACHE 的哨兵：已探测且无 bun


def _resolve_bun() -> list[str] | None:
    """bun 运行时解析（模块级缓存）：bun -> npx -y bun -> None。"""
    global _HTML_BUN_CACHE
    if _HTML_BUN_CACHE is _HTML_BUN_MISSING:
        return None
    if _HTML_BUN_CACHE is not None:
        return _HTML_BUN_CACHE
    if shutil.which("bun"):
        _HTML_BUN_CACHE = ["bun"]
    elif shutil.which("npx"):
        _HTML_BUN_CACHE = ["npx", "-y", "bun"]
    else:
        _HTML_BUN_CACHE = _HTML_BUN_MISSING
        return None
    return _HTML_BUN_CACHE


def _render_html_companion(md_path: Path) -> str:
    """md 产物 -> 同目录 .html（best-effort）。返回成功/降级注记，拼进 render 消息。"""
    bun = _resolve_bun()
    if bun is None:
        return "；HTML 降级：无 bun/npx（install.sh 的 HTML 导出依赖层未装）"
    script = (
        Path(__file__).resolve().parent
        / "vendor"
        / "baoyu-markdown-to-html"
        / "scripts"
        / "main.ts"
    )
    html = md_path.with_suffix(".html")
    try:
        # 先删旧 html：baoyu 对已存在 html 会留 .bak 备份——md 是真源，HTML 可再生，
        # 不留备份防堆积。
        html.unlink(missing_ok=True)
        proc = subprocess.run(
            [*bun, str(script), str(md_path), "--theme", "default", "--keep-title"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"；HTML 降级：转换异常（{e}）"
    if proc.returncode != 0 or not html.exists():
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        reason = tail[-1][:120] if tail else f"rc={proc.returncode}"
        return f"；HTML 降级：{reason}"
    return f"；HTML ✓ {html}"


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


# ---------- P3-1 确认级读回（2026-08-13 用户裁决，设计文档 §2 P3）----------


def confirm_artifact(node: "Node") -> "str | None":
    """确认级读回步的装配产物声明：basename；无产物 -> None。

    映射：node.artifact（understand.md/plan.md）直出。plan:1 读回确认的
    design.md 装配已退役（designs/design-md-assembly-retire-design.md：
    工作流内部零消费，H8 按路径分流豁免），读回步只展示+裁决入 trace。
    """
    art = getattr(node, "artifact", None)
    if art in ("understand.md", "plan.md"):
        return art
    return None


def write_confirm_trace(project_root: Path, name: str, node: "Node", cur: int) -> None:
    """确认级读回步的机械 trace（无模型会话，driver 直写）。

    形状对齐交互读回：q 标题含「读回」+ a ≥50 字（user_decision_recorded 同形，
    render-artifact 的 decision_steps 按标题词收录）；内容声明静默通过语义与
    异议通道（/clear 交接后新会话只能从 trace 还原拍板——v2.45 同一前提）。
    """
    rec = {
        "kind": "skill-trace",
        "major_stage": node.phase.capitalize(),
        "minor_stage": node.minor_key,
        "sub_step": cur,
        "skill": "confirm-readback",
        "purpose": "P3-1 确认级读回（机械落库，无模型会话）",
        "q": [f"读回（确认级·静默通过）：{node.label} 归一化内容与装配产物"],
        "a": [
            "确认级静默通过（P3-1 读回分级，2026-08-13 用户裁决）：归一化内容经 "
            "render-readback 机械展示、产物经 render-artifact 机械装配，未逐项弹卡片；"
            "按提案直接生效。异议走 /dl state-reset 回上一步重做后重新读回。"
        ],
    }
    p = _evidence_path(project_root, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------- force-tacet 实验轨道（force-tacet-experiment-design §4-5，2026-08-21）----------
#
# TACET 步整步静默：不派段（无模型会话、零 token）、不跑 judge（无 Stop 无
# trace 判决）、跳过交互回屏。driver 派段前查 step_tacet_forced 命中即调
# apply_tacet_skip。跳步决策只在机械层 + 用户开关（launch --force-tacet）。

_TACET_SILENT_CACHE: dict[bool, frozenset[str]] = {}


def step_tacet_forced(state: dict[str, Any], node: "Node", cur: int) -> bool:
    """该步是否处于强制 TACET（state.force_tacet + 静默步集 = 44 子步 − 六步脊柱）。

    脊柱步（问题陈述/根因/取证/修法/计划包）正常执行且质量门不放水（design §8）；
    模型无权自选 tacet（档位不进模型可写面--防偷工通道）。
    fermate 组合时脊柱重映射（plan:4#4 -> plan:2#4，fermate-plan-only-design §2.4），
    缓存按 fermate 布尔双份。
    """
    if not state.get("force_tacet"):
        return False
    fermate = bool(state.get("force_fermate"))
    global _TACET_SILENT_CACHE
    if fermate not in _TACET_SILENT_CACHE:
        _TACET_SILENT_CACHE[fermate] = tacet_silent_steps(fermate=fermate)
    return f"{node_id(node.phase, node.sub)}#{cur}" in _TACET_SILENT_CACHE[fermate]


def write_tacet_trace(project_root: Path, name: str, node: "Node", cur: int) -> None:
    """TACET 静默步的机械 trace（无模型会话，driver 侧调用；write_confirm_trace 同范式）。

    kind=tacet：不入 skill-trace 面--_iter_trace_segments/render_artifact 节源
    匹配/read_evidence_for_step（judge 输入裁剪）均只认 kind=skill-trace，
    天然零干扰（design §5「tacet-record 不进任何 judge 输入」）。q/a 平行
    数组形态对齐读侧 _trace_qa_items；skill=tacet 标记来源与职责归属。
    """
    rec = {
        "kind": "tacet",
        "major_stage": node.phase.capitalize(),
        "minor_stage": node.minor_key,
        "sub_step": cur,
        "skill": "tacet",
        "purpose": "TACET 强制档（机械落库，无模型会话）",
        "q": [f"tacet（强制档·静默）：{node.label} · 子步骤{cur}"],
        "a": [
            "force-tacet 实验轨道：本步整步静默（不派段/零 token/不跑 judge），"
            "由 engine 机械落痕并通过。触发 = launch --force-tacet（state.force_tacet），"
            "跳步决策只在机械层，模型无权自选。"
        ],
    }
    p = _evidence_path(project_root, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------- fermate 裁剪静默步（u4-sub3-fermate-cut-design §1.2①，2026-08-26）----------
#
# 与 tacet 静默正交：tacet 管密度（步骤不出声，流程照走），fermate 管深度
# （消费方全在 review/execute 的步整步裁）。机制镜像 tacet 三件套减配版——
# FERMATE_SILENT_STEPS 当前唯一步 u:4#3 非末步非装配步，跳过=落痕+推进，
# 无 render_artifact 分支。


def step_fermate_forced(state: dict[str, Any], node: "Node", cur: int) -> bool:
    """该步是否处于 fermate 裁剪静默（state.force_fermate + FERMATE_SILENT_STEPS）。

    模型无权自选（档位不进模型可写面，同 force_tacet 防偷工论证）。
    """
    if not state.get("force_fermate"):
        return False
    return f"{node_id(node.phase, node.sub)}#{cur}" in FERMATE_SILENT_STEPS


def write_fermate_trace(project_root: Path, name: str, node: "Node", cur: int) -> None:
    """fermate 静默步的机械 trace（kind=fermate，隔离语义同 write_tacet_trace：
    不入 skill-trace 面 = 零 judge 输入干扰；落痕诚实可见供审计）。"""
    rec = {
        "kind": "fermate",
        "major_stage": node.phase.capitalize(),
        "minor_stage": node.minor_key,
        "sub_step": cur,
        "skill": "fermate",
        "purpose": "fermate 裁剪（机械落库，无模型会话）",
        "q": [f"fermate（plan-only·裁剪静默）：{node.label} · 子步骤{cur}"],
        "a": [
            "fermate（plan-only）轨道：本步整步静默（消费方全在 review/execute，"
            "plan-only 无消费方——u4-sub3-fermate-cut-design §0），由 engine 机械"
            "落痕并通过。触发 = launch --fermate（state.force_fermate），"
            "跳步决策只在机械层，模型无权自选。"
        ],
    }
    p = _evidence_path(project_root, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def apply_fermate_skip(project_root: Path, name: str) -> tuple[bool, str]:
    """fermate 静默步机械跳过（driver 派段前调用，apply_tacet_skip 减配版）。

    FERMATE_SILENT_STEPS 当前唯一步（u:4#3）非末步非装配步：写 fermate-record
    + 推进（sub_step_index++），无 render_artifact / 门栏分支。
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
    write_fermate_trace(project_root, name, node, cur)
    _advance_sub_step(project_root, name, state, node, cur, via="fermate-skip")
    return True, ""


def apply_tacet_skip(project_root: Path, name: str) -> tuple[bool, str]:
    """TACET 步机械跳过（driver 派段前调用，design §4-5）。

    三件事：①写 tacet-record 落痕；②装配义务（确认级读回步=各节点末步承载
    产物装配，静默步上由 engine 代跑 render_artifact，沉默源节占位）；③推进
    （末步门栏不豁免：plan:4 完成 held_for_gate 停等 /dl gate，与 main 一致，
    2026-08-23 用户裁决「到 p 默认停止」）。
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
    write_tacet_trace(project_root, name, node, cur)
    if cur == len(node.sub_steps):
        art = confirm_artifact(node)
        if art is not None:
            ok, msg = render_artifact(project_root, name, art)
            if not ok:
                return False, f"tacet 装配失败（{art}）：{msg}"
    _advance_sub_step(project_root, name, state, node, cur, via="tacet-skip")
    return True, ""


def node_holds_for_gate(state: dict[str, Any], node: "Node") -> bool:
    """末步门栏扣留判据单源（_advance_sub_step / release_subgate 两处引用）。

    node.hold_for_gate = 全系统唯一门栏（plan:4，2026-07-28 用户决议「围栏
    只设在 plan 完成」）。fermate 不再设终点门栏（fermate-auto-complete-
    design，2026-08-29 用户决议）：plan-only 跑完=完成态，人工确认点唯一
    = /dl done 归档，「收货」无把关对象（放行后什么都不发生）。
    """
    return node.hold_for_gate


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
    if node_holds_for_gate(state, node):
        # force-tacet 不豁免门栏（2026-08-23 用户裁决「到 p 默认停止，与 main
        # 一致」）：hold_for_gate 全系统唯一处 = plan:4（围栏设在 plan 完成），
        # 此前 force_tacet 自动放行+advance_state 一并穿越 plan->execute 大闸门
        # = 首跑直接跑进 execute/review/evolution。现 tacet 与 main 同路径：
        # plan 完成 -> held_for_gate 停等 -> 用户 /dl gate 放行才继续。
        state["held_for_gate"] = True
        state["updated_at"] = _now()
        save_state(project_root, name, state)
        return state
    if state.get("force_fermate") and node.phase == "plan" and node.sub == 2:
        # fermate 终态（fermate-auto-complete-design，2026-08-29 用户决议）：
        # plan-only 跑完=完成态——无门栏无 /dl gate 收货（把关对象不存在：
        # 放行后什么都不发生），末步过门控直接置 done（镜像 advance_state
        # 的 next_node_id None 终态分支）；人工确认点唯一 = /dl done 归档。
        # 留痕对齐手动放行原则（via 标识机械自动完结）。
        write_gate_verdict(
            project_root,
            name,
            node,
            state.get("node_attempts", 0),
            str(project_root),
            via="fermate-auto-complete",
            sub_step=cur,
        )
        state["gate"] = "done"
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
        and node_holds_for_gate(state, node)
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
    if t_nid == "understand:1" and step == 1:
        # 回滚到裸开场步 = 问题陈述同步作废（interactive-step-headless-prep §8：
        # 陈述在 = step1 走后台 prep，不清则旧陈述污染重跑开场）
        state.pop("problem_statement", None)
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
    # u2-sub1-cost 修C：陈旧 prep 载荷作废——跨节点 stash（NEXT_PREP 顺带交付）
    # 后用户异议回滚，旧 need_user.json 不得直达前台；重回 prep 源步会重新
    # stash，不重 stash 则走原独立 prep 段兜底（任何回滚目标下都正确）。
    state.pop("next_prep_stashed", None)
    (project_root / ".claude" / "workflows" / name / "need_user.json").unlink(
        missing_ok=True
    )
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

    # 4. 发现台账清账（回滚后旧发现基于作废结论；缺失非错误）
    _clear_workflow_discoveries(project_root, name)

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
        "门控读不到等同没写。返工：改用 append-trace 落库——Bash `python3 "
        "~/.dl-workflow/dl_flow_engine.py append-trace --scaffold` 生成载荷骨架，"
        "Edit 填掉「待填」，再 Bash `python3 ~/.dl-workflow/dl_flow_engine.py "
        "append-trace --from-file <载荷>`（格式/路径/结构字段全归脚本，不会再写碎）。"
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


def _phase_write_path_ok(phase: str, file_path: str) -> bool:
    """路径是否命中该 phase 的写白名单（§S11）。"""
    names = _PHASE_WRITE_NAMES.get(phase)
    if names is None:
        return True  # execute（或未配置）不限制
    p = Path(file_path)
    if p.name in names:
        return True
    if p.name.startswith(".trace-payload-") and p.suffix == ".md":
        return True  # v2.125：载荷落 worktree 根（出 .claude 保护目录），各阶段可写
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
    例外三：**empty_block_reason（判 block 但 reason 为空）重试一次**（v2.76）——
    判词消费者是返工的模型（v2.36 判词瘦身前提=「reason 是指路」），空判词 =
    judge 输出完整性违规，脚本可零成本机械判定，与 bad_verdict_json 同族同处置。
    副作用：每次调用重置 LAST_JUDGE_META（成功=成本字段，失败=judge_error；
    重试时两次尝试成本累加 + judge_retried=1）供审计日志。
    """
    LAST_JUDGE_META.clear()
    # v2.76 framing 双态同向（designs/judge-framing-dual-mode-design.md）：
    # §3.5 #28 确立 framing 是独立设计变量，但 v2.71/v2.75 只改了 gate 文本
    # 一层——本指令行恒为「严格判定」，与两个默认-PASS gate 直接矛盾；弱
    # judge 对矛盾指令偏向 system 侧（u:1#2 v2.75 clean 残余误判的可修复
    # 根源）。单源=gate 文本的「默认 pass」字面标记（判据作者已写的
    # framing 声明，脚本读取而非新增 Step 字段防双写漂移）：含标记=默认
    # 放行指令；不含（33 个从严 gate）=严格判定指令不变。
    if "默认 pass" in rubric:
        verdict_rule = (
            "默认放行：仅当判据明列的 block 条件成立才 pass=false 并在 reason "
            "写缺什么（引用条款）；判据未明列为 block 条件的情况不得作为 "
            "block 依据，不得发明判据外要件。\n"
        )
    else:
        verdict_rule = (
            "严格判定：判据任一条不满足 -> pass=false 并在 reason 写缺什么。\n"
        )
    prompt = (
        "你是工作流节点门控的评审 judge。判定模型本轮输出是否符合判据。\n"
        f"{verdict_rule}"
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
            # v2.78/2.79（u:1#3 重放实证，designs/u1-sub3-gate-framing-design.md）：
            # judge 对「产物含前序 sub_step 记录」发明「跨子步串号/字段混入」
            # 要件（clean 1/6）+反向误读「两条都是 sub_step=2」（vio 1/6）——
            # read_evidence_for_step 拼合当前步+前序各步最新 trace 是生产常态
            # （一致性锚点），artifact 组成事实下沉 harness 注（v2.34 存在性钉死
            # 同层先例），免逐 gate 重复钉。措辞定稿经三变体 A/B（n=6 三向）：
            # 「非判对象…才对照」被读成「前序别看」（跨步牙齿塌 5/6→3/6）；
            # 「供…时对照」去祈使版 u:1#3 vio6 掉 4/6；「必须取前序记录对照后判」
            # 祈使版 u:1#3 全牙齿 ≥5/6——义务主句前置是唯一三向达标措辞。
            "\n（产物内容 = 当前步 + 前序各步最新 skill-trace 的拼合：判对象只是"
            "当前 sub_step 的记录；前序记录是一致性对照基准——判据要求「与前序"
            "一致/逐项一致」时必须取前序记录对照后判；前序记录自身的存在与组成"
            "形式不作 block 依据。同一 sub_step 若有多条 skill-trace 记录，"
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
        # 重试时：bad_verdict_json/empty_block_reason 加格式提醒后缀（判决载荷
        # 逐字不动，只追加输出格式强调）；TimeoutExpired 原样重发（输出格式
        # 没问题，是时延抖动）。
        _err = LAST_JUDGE_META.get("judge_error")
        p = prompt + (
            "\n\n提醒：上次你的回答不是合法 JSON。只回一个 JSON 对象，不要任何其它文本。"
            if attempt and _err == "bad_verdict_json"
            else "\n\n提醒：判 block 必须在 reason 写明缺什么（引用判据条款），reason 不得为空。"
            if attempt and _err == "empty_block_reason"
            else ""
        )
        ok, reason, retryable = _run_judge_once(p)
        if not retryable:
            return ok, reason
        LAST_JUDGE_META["judge_retried"] = 1
    return ok, reason  # 重试仍失败 -> 降级 block


def _run_judge_once(prompt: str) -> tuple[bool, str, bool]:
    """run_judge 单次尝试。返回 (pass, reason, retryable)。

    retryable=True 仅三种值得重试的失败模式：
    - bad_verdict_json（判定 JSON 解析失败——输出格式抖动）；
    - TimeoutExpired（时延抖动——递归爆炸根因已被 cwd=tempdir 修掉，
      重试代价远小于超时误判 block 引发的模型返工，见 run_judge docstring）。
    - empty_block_reason（pass=false 但 reason 为空——judge 输出完整性
      违规，空判词让模型盲返工，v2.76）。
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
                # O1（u1-overall-cost）：judge 不调工具，MCP schema 纯税，结构封死
                *NO_MCP_ARGS,
                "--system-prompt",
                JUDGE_SYSTEM_PROMPT,
                prompt,
            ],
            capture_output=True,
            text=True,
            # provider 偶发非法 UTF-8——strict 解码崩 judge（同类：dl_drive
            # run_session / dashboard actions 同款修复）
            errors="replace",
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
    # v2.76：block 空判词=输出完整性违规（判词消费者是返工模型，空 reason
    # =盲返工），与 bad_verdict_json 同族——重试一次补判词，仍空才降级。
    if not verdict.get("pass") and not str(verdict.get("reason", "")).strip():
        LAST_JUDGE_META["judge_error"] = "empty_block_reason"
        return False, "judge 判 block 但未写原因", True
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


def render_substeps_brief(nid: str, cur: int) -> str:
    """node-rules 清单的瘦渲染（u1-overall-cost O2）：每步一行 title（map 骨架）
    + 当前步标注；任何步的 purpose 全文都不带——当前步完整目的双通道已在
    （段 prompt「目的：{step.purpose}」逐字携带 + TUI 每轮注入 primacy 置顶，
    hooks/workflow_phase.py:385 同款形态），其余步 purpose 全文 = 每调用重付的
    死重（node-rules.understand:1.md 实测 25,005 字符，清单 ~15k）。
    phase-rules 全量渲染走 render_substeps_section（v2/front TUI 单会话跨步，
    仍需全量），本函数只服务 driver 段/TUI 段的单步会话。

    非法输入语义同 render_substeps_section（fail loud）。
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
        cur_tag = " ← 当前步（完整目的见任务 prompt / 每轮注入）" if i == cur else ""
        lines.append(f"     - 子步骤{i} = {stp.ref}{gate_tag}：{stp.short}{cur_tag}")
    lines.append(f"<!-- END GENERATED sub_steps {nid} -->")
    return "\n".join(lines)


def render_substeps_section(nid: str, fermate: bool = False) -> str:
    """渲染节点 sub_steps 的 phase-rules 段落（含 BEGIN/END 标记行，幂等可重渲染）。

    每步一行：`- **子步骤N = <ref>**：<purpose 全文>`（gate=None 标「自动过」）。
    节点无 sub_steps / 节点不存在 -> 报错暴露（no silent fallback）。
    fermate=True 时 FERMATE_SILENT_STEPS 命中的步注记「fermate 裁剪·机械静默」
    （u4-sub3-fermate-cut-design §3 polish——清单诚实可见，跳步由 driver 机械执行）。
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
        fermate_tag = ""
        if fermate and f"{nid}#{i}" in FERMATE_SILENT_STEPS:
            fermate_tag = (
                "（**fermate 裁剪·机械静默**：本步不派段不门控，engine 落痕即过）"
            )
        lines.append(
            f"     - **子步骤{i} = {stp.ref}**{gate_tag}{fermate_tag}：{stp.purpose}"
        )
    lines.append(f"<!-- END GENERATED sub_steps {nid} -->")
    return "\n".join(lines)


_FERMATE_ONLY_RE = re.compile(
    r"<!-- BEGIN FERMATE_ONLY -->.*?<!-- END FERMATE_ONLY -->", re.DOTALL
)
_NO_FERMATE_RE = re.compile(
    r"<!-- BEGIN NO_FERMATE -->.*?<!-- END NO_FERMATE -->", re.DOTALL
)


def _strip_fermate_blocks(text: str, fermate: bool) -> str:
    """fermate 条件块（fermate-plan-only-design §2.5）：块级开关，禁文案双写漂移。

    FERMATE_ONLY 块 = 仅 fermate 轨道保留；NO_FERMATE 块 = 仅全量轨道保留。
    条件剔除先于 GENERATED 渲染——被剔块内的 sub_steps 标记随之消失（plan:3/
    plan:4 段整块剔除时不应再渲染其子步骤全文）。
    """
    if fermate:
        text = _NO_FERMATE_RE.sub("", text)
        return _FERMATE_ONLY_RE.sub(
            lambda m: (
                m.group(0)
                .replace("<!-- BEGIN FERMATE_ONLY -->", "")
                .replace("<!-- END FERMATE_ONLY -->", "")
            ),
            text,
        )
    text = _FERMATE_ONLY_RE.sub("", text)
    return _NO_FERMATE_RE.sub(
        lambda m: (
            m.group(0)
            .replace("<!-- BEGIN NO_FERMATE -->", "")
            .replace("<!-- END NO_FERMATE -->", "")
        ),
        text,
    )


def render_phase_rules(template_text: str, fermate: bool = False) -> str:
    """把模板里所有 GENERATED sub_steps 标记段替换为 engine 渲染产物。

    无标记段 -> 原样返回（向后兼容）；标记的节点 id 非法 -> 抛错（调用方 fail loud）。
    三阶段：先 fermate 条件块，再 GENERATED 块，后 artifact_sections 内联 token。
    """
    text = _strip_fermate_blocks(template_text, fermate)
    rendered = _GENERATED_RE.sub(
        lambda m: render_substeps_section(m.group(1), fermate=fermate), text
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


# ---------- fetch-preflight：外部源网络可达性预检（fetch-preflight-probe-design）----------
#
# 实证（2026-08-22 interaction_turnover u:1 子4）：原子 B light agent 3.2min
# 全花在网络超时，返回「未取证+建议升档 full」又串行补派 5.5min--环境性
# 失败在派发前不可见，升档救不了网络死。用户裁决：外部取证派发前对全部
# 计划内外部源 URL 逐个预检可达性；不可达的不派发（留痕即可）。
# 模型只决定 URL 清单（claim 源），探测归脚本（v2.118 同范式）。


# ---------- drive 模式进度快照（drive-tasklist-render-design §2.2）----------


def tui_tasklist_lines(state: dict[str, Any]) -> list[str]:
    """TUI 原生任务清单目标状态行（镜像 state 当前 index/sub_index）。

    单源：workflow_phase.py（UserPromptSubmit 注入）与 workflow_advance.py
    （front 模式 Stop 续轮注入）共用--2026-08-23 前只在 UserPromptSubmit 注入，
    两次用户输入间 TUI 只被段完成通知/Stop 续轮唤起，任务清单原地踏步
    （tacet 快速推进时最显眼）。纯函数，零 IO；行格式与 output-style
    规则 1 的建齐/对齐契约一致（phase 行 + 子阶段行，全程保留）。
    """
    st = normalize_state(dict(state))
    idx = st["index"]
    sub_index = st["sub_index"]
    rows: list[str] = []
    for i, p in enumerate(PHASES, 1):
        lbl = PHASE_LABELS.get(p, p)
        stt = "completed" if i < idx else ("in_progress" if i == idx else "pending")
        rows.append(f"  {i}. {lbl} -> {stt}")
        for j, slabel in enumerate(subphase_labels(p), 1):
            if st.get("force_fermate") and fermate_cut_node(p, j):
                continue  # fermate：plan:3/plan:4 裁剪不存在（§2.5，单源 dl_flow_nodes）
            if i < idx:
                sst = "completed"
            elif i == idx:
                sst = (
                    "completed"
                    if j < sub_index
                    else ("in_progress" if j == sub_index else "pending")
                )
            else:
                sst = "pending"
            rows.append(f"    {i}.{j} {slabel} -> {sst}")
    return rows


def progress_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    """drive 模式进度快照的结构化行（driver rich Live 渲染数据源）。

    每行 {depth, label, status, extra}：depth 0=阶段 / 1=子阶段 / 2=子步骤
    （仅当前节点展开）；status ∈ done/current/todo——节点线性序（_NODES 声明序）
    < 当前=done、==当前=current、> 当前=todo，子步骤按 sub_step_index 同理；
    当前阶段行 extra 带 gate 状态。纯函数，零 IO。
    """
    st = normalize_state(dict(state))
    order = _node_order()
    cur_ord = order[st["node"]]
    cur_step = st.get("sub_step_index", 0)
    gate = st.get("gate", "")
    rows: list[dict[str, Any]] = []
    for pi, phase in enumerate(PHASES):
        members = [(nid, n) for nid, n in _NODES.items() if n.phase == phase]
        ords = [order[nid] for nid, _ in members]
        if max(ords) < cur_ord:
            p_status = "done"
        elif min(ords) > cur_ord:
            p_status = "todo"
        else:
            p_status = "current"
        rows.append(
            {
                "depth": 0,
                "label": f"{pi + 1}. {PHASE_LABELS.get(phase, phase)}",
                "status": p_status,
                "extra": f"gate: {gate}" if p_status == "current" else "",
            }
        )
        for nid, node in members:
            if node.sub == 0:
                continue  # 整阶段节点：阶段行即节点行
            if st.get("force_fermate") and fermate_cut_node(node.phase, node.sub):
                continue  # fermate：plan:3/plan:4 裁剪不存在（§2.5，单源 dl_flow_nodes）
            o = order[nid]
            n_status = (
                "done" if o < cur_ord else ("current" if o == cur_ord else "todo")
            )
            rows.append(
                {
                    "depth": 1,
                    "label": f"{pi + 1}.{node.sub} {node.label}",
                    "status": n_status,
                    "extra": "",
                }
            )
            if o == cur_ord and node.sub_steps:
                for si, step in enumerate(node.sub_steps, start=1):
                    s_status = (
                        "done"
                        if si < cur_step
                        else ("current" if si == cur_step else "todo")
                    )
                    # force-tacet：静默步标「tacet」（LiveProgress/快照均透传 extra）
                    s_extra = ""
                    if st.get("force_tacet"):
                        spine = (
                            TACET_SPINE_STEPS_FERMATE
                            if st.get("force_fermate")
                            else TACET_SPINE_STEPS
                        )
                        if f"{nid}#{si}" not in spine:
                            s_extra = "tacet"
                    rows.append(
                        {
                            "depth": 2,
                            "label": f"{si} {step.short}",
                            "status": s_status,
                            "extra": s_extra,
                        }
                    )
    return rows


def set_problem_statement(project_root: Path, name: str, statement: str) -> None:
    """写入开场采集的用户问题陈述（drive-tasklist-render-design §2.4）。

    恢复 v2.0「首条用户消息」语义——handoff_pack 顶部收录后，子1 模型开场
    即有用户原话可引，不再面对工作流名 slug 自力更生翻仓库。
    """
    state = load_state(project_root, name)
    if state is None:
        raise FileNotFoundError(f"工作流 {name} 的 state.json 缺失")
    state["problem_statement"] = statement
    save_state(project_root, name, state)


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


def set_drive_mode(project_root: Path, name: str, on: bool) -> tuple[bool, str]:
    """drive 模式开关（v3 headless driver，designs/headless-driver-arch-design.md）。

    state.drive_mode=True 时 hooks 降级：workflow_advance 不门控不推进（编排归
    dl_drive.py 外部 driver，防双 orchestrator）；workflow_step_fence 只保留
    S11 阶段写围栏等硬约束（S10/S15 的回合纪律语义在外部编排下失效）。
    dl_drive.py 启动时置 on；WF_TUI=1 回旧 TUI 路径时 dl-launch.sh 置 off。
    """
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    state = normalize_state(state)
    state["drive_mode"] = on
    save_state(project_root, name, state)
    return True, (
        f"drive 模式已{'开启（hooks 降级，编排归 driver）' if on else '关闭（回 TUI hook 编排）'}"
    )


# ---------- front_mode 前台混合（front-tui-hybrid-design §2.3） ----------


def set_front_mode(project_root: Path, name: str, on: bool) -> tuple[bool, str]:
    """front 模式开关（v4 前台混合）：常驻 TUI 前台 + 后台 --segment 工人。

    state.front_mode=True 时 hooks 走 front 分支：phase 注入派发块（非交互步）、
    advance 守 stall 兜底（段不在跑则重提示派发，3 次计数闸）、fence 收紧非交互
    步白名单（防前台模型抢干活=上下文胀回 v2.x 病灶）。段跑期间 drive_mode=on
    优先（hooks 既有早退分支），front 分支只在段不在跑时生效。
    dl-launch.sh --front 置 on；v3 全程 driver / WF_TUI=1 v2 路径不置。
    """
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    state = normalize_state(state)
    state["front_mode"] = on
    save_state(project_root, name, state)
    return True, (f"front 模式已{'开启（前台会话 + 后台段工人）' if on else '关闭'}")


def set_force_tacet(project_root: Path, name: str, on: bool) -> tuple[bool, str]:
    """force-tacet 实验轨道开关（force-tacet-experiment-design §5-6）。

    state.force_tacet=True（sticky，resume/续跑保持）：understand/plan 仅五步
    脊柱执行，其余 39 步 TACET 静默；门栏/闸门自动放行。front（默认，段工人
    与 headless 共用主循环单源）与 --headless driver 均支持；WF_TUI=1 旧 TUI
    路径不支持（launch fail loud）。关闭 = 回全量编排（FORTE）。
    """
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    state = normalize_state(state)
    state["force_tacet"] = on
    save_state(project_root, name, state)
    return True, (
        "force-tacet 实验轨道已开启（六步脊柱执行，其余步 TACET 静默；"
        "plan 完成 held_for_gate 停等 /dl gate（与 main 一致）；"
        "front（默认）与 --headless 均支持）"
        if on
        else "force-tacet 实验轨道已关闭（回全量编排）"
    )


def set_force_fermate(project_root: Path, name: str, on: bool) -> tuple[bool, str]:
    """fermate（plan-only）开关（fermate-plan-only-design §2.1，镜像 set_force_tacet）。

    state.force_fermate=True（sticky，resume/续跑保持）：plan:3/plan:4 不存在
    （能力包/检查点消费方全在 execute，无执行=产物纯税），plan:2 末步过门控
    即完结（gate="done"，fermate-auto-complete-design：无门栏无收货环节，
    人工确认点唯一 = /dl done 归档）。模型无权自封——档位不进
    模型可写面（同 force_tacet 防偷工论证）。关闭=回全量编排。
    """
    state = load_state(project_root, name)
    if state is None:
        return False, f"工作流 {name} 的 state.json 缺失"
    state = normalize_state(state)
    state["force_fermate"] = on
    save_state(project_root, name, state)
    return True, (
        "fermate（plan-only）已开启（plan 止于 plan:2，plan:3/plan:4 裁剪；"
        "plan:2 末步过门控即完结，归档走 /dl done）"
        if on
        else "fermate（plan-only）已关闭（回全量编排）"
    )


def front_segment_command(name: str) -> str:
    """前台派发命令逐字单源（phase 注入 / advance 兜底 / fence 白名单三通道共用）。

    路径按 engine 自身位置解析（2026-08-22）：分支从 worktree 承载运行时，
    派发 worktree 的 dl_drive.py（tacet 跳步逻辑在 driver 侧）；硬编码
    ~/.dl-workflow 会把段工人派到主树 driver（无 tacet 逻辑）--实证
    interaction_amplitude 首跑 force_tacet=True 却全量轨道、零 tacet 落痕。
    """
    drive = Path(__file__).resolve().parent / "scripts" / "workflow" / "dl_drive.py"
    return f"python3 {drive} {name} --segment"


def _front_pid_gone(pid: object) -> bool:
    """pid 已退出（含 zombie）。workflow_advance._pid_gone 同款；engine 自持一份——
    hooks import engine，反向不许。"""
    if not isinstance(pid, int) or pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return True
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return stat.rpartition(")")[2].split()[0] == "Z"
    except (OSError, IndexError):
        return True


def front_segment_alive(project_root: Path, name: str) -> bool:
    """段活性：front_segment.json 锁存在且 pid 活。锁缺失 / pid 死（stale）= False。"""
    meta = project_root / ".claude" / "workflows" / name
    try:
        seg = json.loads((meta / "front_segment.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(seg, dict):
        return False
    return not _front_pid_gone(seg.get("pid"))


def front_segment_summary(project_root: Path, name: str) -> dict | None:
    """上轮段结局便签（segment_summary.json）；缺失/损坏 = None（state 才是唯一真源）。"""
    meta = project_root / ".claude" / "workflows" / name
    try:
        s = json.loads((meta / "segment_summary.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return s if isinstance(s, dict) else None


def front_dynamic_interactive(project_root: Path, name: str, state: dict) -> bool:
    """NEED_USER 动态重分类判定：上轮段以 code 13 收场且位置咬合当前 state
    → 本步按交互步对待（hooks 落 v2 路径，fence 走 S15/S10 而非前台白名单）。
    位置推进后 summary 自动失咬合 = 自清理，无需显式删。"""
    s = front_segment_summary(project_root, name)
    return bool(
        s
        and s.get("code") == 13
        and s.get("node") == state.get("node")
        and s.get("sub_step") == state.get("sub_step_index")
    )


def front_interactive_work_here(project_root: Path, name: str, state: dict) -> bool:
    """front 模式当前位置是否「前台亲自干」（单源：phase 注入路由 + fence 白名单
    共用——2026-08-12 实爆：两处各持副本，§8 路由翻转只改 phase 漏改 fence，
    派发命令被 S15 deny、模型误读「交回本会话」在 TUI 抢干活）。

    True 仅两态：①真·裸开场（u:1#1 交互步且无 problem_statement——前台收陈述）；
    ②NEED_USER 动态重分类（code 13 咬合——前台问答段落库）。
    其余全部 False = 派段（含陈述在手的 u:1#1——§8 起交互步先后台 prep）。
    """
    bare_no_stmt = bool(
        state.get("node") == "understand:1"
        and state.get("sub_step_index", 1) == 1
        and not (state.get("problem_statement") or "").strip()
    )
    return bool(bare_no_stmt or front_dynamic_interactive(project_root, name, state))


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
            "drive-mode",
            "front-mode",
            "force-tacet",
            "fermate",
            "dispute",
            "render-phase-rules",
            "append-trace",
            "redteam-prompt",
            "fetch-prompt",
            "fetch-preflight",
            "render-artifact",
            "render-readback",
            "list-tools",
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
        help="append-trace：生成当前子步骤 .md 载荷骨架到 worktree 根 .trace-payload-<name>.md 并打印路径（格式脚本管，模型只填「待填」）",
    )
    parser.add_argument(
        "--fermate",
        action="store_true",
        help="render-phase-rules：渲染 fermate（plan-only）变体（plan:3/plan:4 段剔除）",
    )
    parser.add_argument(
        "--ingest-agent",
        metavar="TASK_ID",
        help="append-trace：把子代理 agent-<TASK_ID> 的报告原文收录进 .md 载荷 qa 节（脚本提取，禁手工粘贴）",
    )
    parser.add_argument(
        "--ingest-redteam",
        action="store_true",
        help="append-trace：把 driver 预派发红队的报告（redteam_report.md）收录进 .md 载荷 qa 节（阻塞等报告就绪；无预派发则指路回退 --ingest-agent）",
    )
    parser.add_argument(
        "--out",
        action="store_true",
        help="fetch-prompt：骨架落盘 .claude/workflows/<name>/fetch-prompt-skeleton.md 并打印路径（替代 stdout）",
    )
    parser.add_argument(
        "--url",
        action="extend",
        nargs="+",
        metavar="URL",
        help="fetch-preflight：要预检网络可达性的外部源 URL（可多个；可重复给 --url；裸域名自动补 https://）",
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
            sys.stdout.write(render_phase_rules(template_text, fermate=args.fermate))
        except (KeyError, ValueError) as e:
            print(f"✗ 渲染失败：{e}", file=sys.stderr)
            return 1
        return 0

    cwd = args.cwd or str(Path.cwd())
    project_root = resolve_project_root(cwd)
    if project_root is None:
        print("✗ 不在 git 仓库内", file=sys.stderr)
        return 1

    # list-tools（组件 B 发现入口）：只需 project_root，不需工作流 worktree
    # （dl-cmd.sh 早路由，任意 git repo 内可用）。
    if args.cmd == "list-tools":
        tools = project_tools.load_project_tools(project_root)
        if not tools:
            print("（本项目无注册工具）")
        for t in tools:
            print(f"- {t['name']}: {t['command']} — {t.get('description', '')}")
        return 0

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
        if args.ingest_redteam:
            ok, msg = ingest_redteam_report(project_root, name)
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
    if args.cmd == "fetch-preflight":
        # fetch-preflight-probe：外部源网络可达性预检（派发取证子代理前）。
        # 部分不可达 rc=0（不可达是信息不是命令失败）；无 URL = 用法错。
        # --url 是 action="extend"+nargs="+" -> args.url 已是扁平 str 列表，
        # 禁再展平（旧写法 for group in args.url 逐字符迭代 str -> 每个 URL
        # 拆成单字符碎片全判不可达，2026-08-23 amplitude 首跑实证）。
        urls = list(args.url or [])
        return run_fetch_preflight(project_root, name, urls)
    if args.cmd == "render-artifact":
        if not args.value:
            print(
                "✗ 用法: render-artifact [name] <understand.md|plan.md>",
                file=sys.stderr,
            )
            return 1
        ok, msg = render_artifact(project_root, name, args.value)
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
    if args.cmd == "drive-mode":
        if args.value not in ("on", "off"):
            print("✗ 用法: drive-mode <name> on|off", file=sys.stderr)
            return 1
        ok, msg = set_drive_mode(project_root, name, args.value == "on")
        print(("✓ " if ok else "✗ ") + msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if args.cmd == "front-mode":
        if args.value not in ("on", "off"):
            print("✗ 用法: front-mode <name> on|off", file=sys.stderr)
            return 1
        ok, msg = set_front_mode(project_root, name, args.value == "on")
        print(("✓ " if ok else "✗ ") + msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if args.cmd == "force-tacet":
        if args.value not in ("on", "off"):
            print("✗ 用法: force-tacet <name> on|off", file=sys.stderr)
            return 1
        ok, msg = set_force_tacet(project_root, name, args.value == "on")
        print(("✓ " if ok else "✗ ") + msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if args.cmd == "fermate":
        if args.value not in ("on", "off"):
            print("✗ 用法: fermate <name> on|off", file=sys.stderr)
            return 1
        ok, msg = set_force_fermate(project_root, name, args.value == "on")
        print(("✓ " if ok else "✗ ") + msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
