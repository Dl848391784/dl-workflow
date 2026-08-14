"""组件 B：项目工具注册文件加载（发现层）。

注册文件 = <项目>/.claude/workflow-tools.yaml；缺失/损坏 = 无工具（零影响）。
"""

from __future__ import annotations

from pathlib import Path

PROJECT_TOOLS_FILENAME = "workflow-tools.yaml"
_KEYS = {"name", "command"}


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
