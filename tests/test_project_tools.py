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
