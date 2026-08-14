"""组件 B：项目工具注册文件加载（发现层）。

注册文件 = <项目>/.claude/workflow-tools.yaml；缺失/损坏 = 无工具（零影响）。

除加载外，本模块还是「项目工具 command 头」过滤的真源：S15 围栏
（hooks/workflow_step_fence.py）与 per-wf settings allowlist
（dl-lib.sh wf_write_settings）共用 project_tool_heads()，破坏性头正则
单源在此（不跨文件复制）。
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_TOOLS_FILENAME = "workflow-tools.yaml"
_KEYS = {"name", "command"}

# 项目工具 command 头破坏性/解释器黑名单（组件 B，codebase-archaeology-toolbox-design
# §3.3）：只加只读发现类（find/ls/grep/cat/head/git log/python 脚本）——破坏性/远程写
# 命令头（rm/dd/sudo/mv/touch/curl/wget 等）不进白名单，保留「弱模型幻觉刹车」
# （正向名单可收敛，deny 反向名单是打地鼠）。
# 通用解释器头（python3/bash/…）不进：注册「python3 脚本」会把任意 python3 命令放进
# 白名单（含 -c 内联写），白名单降级为全放行——工具头须是项目脚本路径。
# 写能力通用二进制（审计 Critical）：注册只读工具如 `git log` 头是 git，头匹配短路在
# S15 只读正则之前——git reset --hard / clean -f / push 全过围栏。git/sed/cp/tar 等
# 一律不进「工具头」白名单；git 的只读形态（log/show/status 等）仍经 S15
# _S15_GIT_READONLY_RE 放行不误伤；sed 不在只读命令正则 _S15_READONLY_CMD_RE 内、
# 也在此黑名单，完全不放行。
PROJECT_TOOL_DESTRUCTIVE_HEAD_RE = re.compile(
    r"^(?:rm|dd|sudo|mv|touch|mkdir|rmdir|chmod|chown|ln|truncate|"
    r"mount|umount|mkfs|shutdown|reboot|kill|pkill|killall|tee|"
    r"curl|wget|ssh|scp|rsync|"
    r"git|sed|cp|install|tar|zip|"
    r"python3?|bash|sh|zsh|fish|node|perl|ruby|php|lua|env|timeout|nohup|docker)\b"
)


def project_tool_heads(project_root: Path) -> set[str]:
    """注册项目工具的非破坏性 command 头集合（空 = 无工具 / 全被拒）。

    与 S15 围栏同口径：只放行只读发现类，破坏性/解释器头不放行。
    S15（_s15_project_tool_command）与 per-wf settings allowlist
    （wf_write_settings）共用本函数，过滤逻辑单源。
    """
    heads: set[str] = set()
    for t in load_project_tools(project_root):
        cmd_str = str(t.get("command") or "").strip()
        if not cmd_str:
            continue
        head = cmd_str.split()[0]
        if PROJECT_TOOL_DESTRUCTIVE_HEAD_RE.match(head):
            continue
        heads.add(head)
    return heads


def load_project_tools(project_root: Path) -> list[dict]:
    """读项目工具注册文件；任何异常都返回 []（宁纵勿枉，不阻断工作流）。"""
    path = project_root / ".claude" / PROJECT_TOOLS_FILENAME
    if not path.exists():
        return []
    try:
        import yaml  # 惰性导入：多数项目无工具，避免冷启动税

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("tools"), list):
        return []
    tools = []
    for t in data["tools"]:
        if not isinstance(t, dict) or not (_KEYS <= set(t)):
            continue
        tools.append(
            {
                "name": t["name"],
                "command": t["command"],
                "description": t.get("description", ""),
                "arg_hint": t.get("arg_hint", ""),
            }
        )
    return tools
