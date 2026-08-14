# tests/test_project_tools.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "workflow"))
import project_tools as pt  # noqa: E402


def test_missing_file_returns_empty(tmp_path):
    assert pt.load_project_tools(tmp_path) == []


def test_valid_file_parses(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "workflow-tools.yaml").write_text(
        "tools:\n"
        "  - name: inspect-backtest-result\n"
        "    command: scripts/inspect_backtest_result.py --factor {factor}\n"
        "    description: 读回测结果元数据\n"
        "    arg_hint: --factor <因子名>\n"
    )
    tools = pt.load_project_tools(tmp_path)
    assert len(tools) == 1
    assert tools[0]["name"] == "inspect-backtest-result"
    assert tools[0]["command"] == "scripts/inspect_backtest_result.py --factor {factor}"


def test_damaged_file_returns_empty(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "workflow-tools.yaml").write_text("tools: [unclosed")
    assert pt.load_project_tools(tmp_path) == []


def test_project_tool_heads_safe_head(tmp_path):
    """只读发现类工具头入选（component B §3.2 action 3 / §3.3）。"""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "workflow-tools.yaml").write_text(
        "tools:\n"
        "  - name: inspect-backtest-result\n"
        "    command: scripts/inspect_backtest_result.py --factor {factor}\n",
        encoding="utf-8",
    )
    assert pt.project_tool_heads(tmp_path) == {"scripts/inspect_backtest_result.py"}


def test_project_tool_heads_filters_destructive_and_interpreter(tmp_path):
    """破坏性/解释器头不放行（与 S15 围栏同口径）：rm/git/python3/sed 全拒。"""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "workflow-tools.yaml").write_text(
        "tools:\n"
        "  - name: wipe\n    command: rm -rf /tmp/x\n"
        "  - name: glog\n    command: git log --oneline -20\n"
        "  - name: run-py\n    command: python3 scripts/inspect.py\n"
        "  - name: sedx\n    command: sed -n '1,5p' f\n"
        "  - name: safe\n    command: scripts/inspect_backtest_result.py --factor x\n",
        encoding="utf-8",
    )
    assert pt.project_tool_heads(tmp_path) == {"scripts/inspect_backtest_result.py"}


def test_project_tool_heads_no_tools_is_empty(tmp_path):
    assert pt.project_tool_heads(tmp_path) == set()
