#!/usr/bin/env python3
"""
SessionStart hook：/clear（或启动）时注入工作流交接包（v2.45）。

对应设计 designs/context-handoff-design.md §2。
主会话成本 = 轮次 × 上下文长度，会话不重置则平方膨胀（u:1 实测 54k->283k）。
交接架构：用户按边界提示 /clear 后，本 hook 在新会话注入机械装配的交接包
（engine.handoff_pack：前序证据 + 用户裁决 + 产物指针），接续零损失。
v2.122：source=clear 且存在未决 handoff_prompt 时机械记 choice=cleared
（minor-boundary-handoff-prompt-design §2.2——用户选择留痕供事后审计）。

触发面：
- source=clear：工作流运行中 -> 注入交接包。
- source=startup：dl 首启无 trace -> handoff_pack 返回 None -> 静默。
- source=resume/compact：上下文已保留/已压缩 -> 不注入（重复注入=纯税）。

容错（仿 workflow_phase.py）：stdin 解析失败 / 非 worktree cwd /
state 缺失 -> exit 0 静默不注入。SessionStart 永不阻断（exit 0 only）。
留痕 <project>/.claude/.wf_phase.log（复用阶段注入日志通道）。
"""

import json
import sys
from pathlib import Path

# repo 根不在 sys.path（hook 由 Claude Code 以脚本方式执行），先补再 import。
_DLWF_ROOT = Path(__file__).resolve().parents[1]  # ~/.dl-workflow/
sys.path.insert(0, str(_DLWF_ROOT))
sys.path.insert(0, str(_DLWF_ROOT / "hooks"))
import dl_flow_engine as engine  # noqa: E402
from workflow_phase import (  # noqa: E402
    _load_state,
    _log_invocation,
    _payload_cwd,
    _resolve_project_root,
    _resolve_workflow_name,
)

# 交接注入只在这两个 source 触发：clear=用户按边界提示换上下文；
# startup=新进程启动（首启无 trace 自然静默，重建后启动则须补交接包）。
# resume=上下文完整恢复，compact=已压缩保留——注入=重复税。
_HANDOFF_SOURCES = ("clear", "startup")


def build_injection(project_root: Path, name: str, source: str) -> str | None:
    """组装交接注入文本；不注入场景返回 None（测试面=本函数，main 只接线）。"""
    if source not in _HANDOFF_SOURCES:
        return None
    state = _load_state(project_root, name)
    if not state:
        return None
    if source == "clear":
        # v2.122：边界提示后用户 /clear -> 未决 handoff_prompt 记 cleared
        # （无未决则无操作非失败；写失败不阻断注入，宁纵勿枉）。
        # startup 不计：新进程启动可能是重建/换机场景，未必是响应提示的主动
        # 清理；该 prompt 留到下一边界记 declined 更接近事实（宁纵勿枉）。
        engine.write_handoff_resolution(project_root, name, choice="cleared")
    pack = engine.handoff_pack(project_root, name)
    if pack is None:
        return None
    return (
        pack + "\n当前子步的 purpose/围栏/自查提示由每轮 UserPromptSubmit 注入提供"
        "（本包不含，非缺失）。继续当前子步即可。\n"
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0

    source = str(payload.get("source") or "")
    cwd = _payload_cwd(payload)
    name = _resolve_workflow_name(cwd)
    if not name:
        return 0  # 普通会话 -> 不注入
    project_root = _resolve_project_root(cwd)
    if project_root is None:
        return 0

    context = build_injection(project_root, name, source)
    if context is None:
        _log_invocation(project_root, "session_no_handoff", name=name, phase=source)
        return 0
    out = json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        },
        ensure_ascii=False,
    )
    sys.stdout.write(out)
    _log_invocation(project_root, "session_handoff", name=name, phase=source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
