#!/usr/bin/env python3
"""dl_engine - 引擎 profile 单源（designs/qodercli-engine-profile-design.md §P1）。

dl-workflow 双引擎（claude | qodercli）的全部 harness 差异集中于此：binary、
配置根、权限值拼写、flag 差异、debug 日志根、计量语义。差异依据 = P0 实测
（同设计 §3a/3b D1-D12），禁凭 bundle 字符串推断新增项。

引擎选择 = DL_ENGINE env（launcher 设置，hooks/段工人/dashboard 继承）：
- 未设/空 = claude（默认，行为与单引擎时代逐位一致）
- 未知值 = SystemExit 显式报错（no silent fallback 铁律，不默认回退 claude）
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EngineProfile:
    """单引擎全部差异面。方法只组合 cmd 碎片，不 spawn。"""

    name: str  # "claude" | "qodercli"
    binary: str  # spawn 二进制名
    config_root: Path  # 用户配置根（settings/skills/commands/output-styles 安装目标）
    project_resource_dir: str  # 项目资源目录名（".claude" | ".qoder"）
    permission_cli_value: str  # --permission-mode 的 CLI 拼写（P0：payload 内都是 acceptEdits，仅 CLI 拼写不同）
    skills_dir_display: (
        str  # judge rubric 文本里的 skills 注册表路径（dl_flow_engine 单点替换）
    )
    debug_logs_root: (
        Path | None
    )  # debug 日志自动落盘根（qoder）；claude=None（走 --debug-file）
    # harness transcript 根（<root>/<enc-cwd>/<sid>.jsonl + subagents/，dl_flow_trace 消费）
    transcript_projects_root: Path
    usage_metered: bool  # False=BYOK 引擎 usage/cost 全零（P0 D6），成本对账降级 N/A

    def permission_args(self) -> list[str]:
        return ["--permission-mode", self.permission_cli_value]

    def verbose_args(self) -> list[str]:
        # claude stream-json 需要 --verbose 才出 assistant 事件；
        # qodercli 无此 flag（P0 D1 实测 exit 1「unknown option」）
        return ["--verbose"] if self.name == "claude" else []

    def debug_args(self, debug_file: Path) -> list[str]:
        if self.name == "claude":
            return ["--debug", "api,hooks", "--debug-file", str(debug_file)]
        # qoder 无 --debug-file（P0 D2）；--debug 后日志自动落
        # ~/.qoder/logs/sessions/<proj>/<sid>/segments/*.jsonl（结构化 jsonl，更优）
        return ["--debug"]

    def disallow_ask_args(self) -> list[str]:
        # qoder 无 AskUserQuestion 工具（P0 D4 tools 列表确认）——工具不存在=
        # 结构堵死，L1 权限层封禁豁免；L2 嗅探（_session_called_ask_user）保留
        if self.name == "claude":
            return ["--disallowedTools", "AskUserQuestion"]
        return []


_PROFILES: dict[str, EngineProfile] = {
    "claude": EngineProfile(
        name="claude",
        binary="claude",
        config_root=Path.home() / ".claude",
        project_resource_dir=".claude",
        permission_cli_value="acceptEdits",
        skills_dir_display="~/.claude/skills",
        debug_logs_root=None,
        transcript_projects_root=Path.home() / ".claude" / "projects",
        usage_metered=True,
    ),
    "qodercli": EngineProfile(
        name="qodercli",
        binary="qodercli",
        config_root=Path(
            os.environ.get("QODER_CONFIG_DIR") or (Path.home() / ".qoder")
        ),
        project_resource_dir=".qoder",
        permission_cli_value="accept_edits",
        skills_dir_display="~/.qoder/skills",
        debug_logs_root=Path.home() / ".qoder" / "logs" / "sessions",
        # P0 实测 transcript 落 ~/.qoder/projects（编码规则同 claude）
        transcript_projects_root=Path(
            os.environ.get("QODER_CONFIG_DIR") or (Path.home() / ".qoder")
        )
        / "projects",
        # BYOK 实测 usage/cost 全零（D6）；内置 Qwen 模型待验（设计 §3c）——
        # 有实证前一律按未计量处理（对账显示 N/A，不报错不虚构）
        usage_metered=False,
    ),
}


def get_engine() -> EngineProfile:
    """当前引擎 profile。DL_ENGINE 未设/空 = claude；未知值硬失败。"""
    name = os.environ.get("DL_ENGINE", "").strip() or "claude"
    profile = _PROFILES.get(name)
    if profile is None:
        print(
            f"✗ DL_ENGINE={name!r} 未知引擎（可选：{sorted(_PROFILES)}）"
            "——拒绝静默回退（no silent fallback）",
            file=sys.stderr,
        )
        sys.exit(2)
    return profile
