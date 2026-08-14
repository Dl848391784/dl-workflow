"""
scripts/workflow/dl_statusline.py 单元测试（v4 statusLine 进度栏）。

覆盖（designs/v4-statusline-progress-design.md §5.1 六态状态机）：
- render_line 纯函数：段在跑·活跃 / 段在跑·疑似卡住（180s 阈值两侧）/
  门栏扣留 / 交互步 / 段结局便签 / 待派发；
- build_info IO 层：front_segment.json 死 pid 残留锁不误判「段在跑」、
  state.json 实时位置经 engine 单源标签渲染。

fixture 约定从简：statusline 只读 .claude/workflows/<name>/ 下小文件，
不需要真 git repo/worktree（与 test_dl_drive.py 的 fixture 需求不同）。
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime
from pathlib import Path

DLWF_ROOT = Path(__file__).resolve().parents[1]
STATUSLINE = DLWF_ROOT / "scripts" / "workflow" / "dl_statusline.py"

sys.path.insert(0, str(DLWF_ROOT))


def _load():
    spec = importlib.util.spec_from_file_location("dl_statusline", STATUSLINE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dl_statusline"] = mod
    spec.loader.exec_module(mod)
    return mod


sl = _load()

NOW = datetime(2026, 8, 11, 23, 20, 0)


def _info(**over):
    """render_line 输入骨架：understand:1 子4/6 非交互步、无段无摘要。"""
    info = {
        "phase_label": "理解和求证问题",
        "sub_label": "理解问题和背景",
        "node": "understand:1",
        "sub_step": 4,
        "sub_steps_total": 6,
        "interactive": False,
        "held_for_gate": False,
        "seg_elapsed_min": None,
        "stream_age_s": None,
        "summary_code": None,
    }
    info.update(over)
    return info


# ---------- render_line 六态 ----------


def test_segment_running_active():
    line = sl.render_line(_info(seg_elapsed_min=12, stream_age_s=30.0))
    assert line == "⏳ 理解问题和背景 子4/6 · 段工人 12min · 活跃"


def test_segment_running_stale_over_threshold():
    line = sl.render_line(_info(seg_elapsed_min=31, stream_age_s=181.0))
    assert line == (
        "⏳ 理解问题和背景 子4/6 · 段工人 31min · \033[33m⚠ 3min 无输出\033[0m"
    )


def test_segment_running_boundary_179_still_active():
    line = sl.render_line(_info(seg_elapsed_min=5, stream_age_s=179.0))
    assert line.endswith("活跃")


def test_segment_running_no_stream_yet_is_active():
    # 段刚起跑 drive-stream.jsonl 尚未创建（stream_age_s=None）不得误报警
    line = sl.render_line(_info(seg_elapsed_min=0, stream_age_s=None))
    assert line.endswith("活跃")


def test_held_for_gate():
    line = sl.render_line(_info(held_for_gate=True))
    assert line == "\033[31m⛔ understand:1 门栏 · 待 /dl gate\033[0m"


def test_interactive_step():
    line = sl.render_line(_info(interactive=True))
    assert line == "✋ 理解问题和背景 子4/6 · 本会话交互步"


def test_segment_summary_shown():
    line = sl.render_line(_info(summary_code=10))
    assert line == "📋 段结局 code 10 · /dl status 判读"


def test_idle_pending_dispatch():
    line = sl.render_line(_info())
    assert line == "▸ 理解问题和背景 子4/6 · 待派发段"


def test_node_without_sub_steps_uses_phase_label():
    line = sl.render_line(
        _info(sub_label=None, node="execute:0", sub_step=0, sub_steps_total=0)
    )
    assert line == "▸ 理解和求证问题 · 待派发段"


# ---------- build_info IO 层 ----------


def _mk_wf(tmp_path: Path, **state_over) -> Path:
    meta = tmp_path / ".claude" / "workflows" / "t"
    meta.mkdir(parents=True)
    state = {
        "name": "t",
        "phase": "understand",
        "sub_index": 1,
        "node": "understand:1",
        "sub_step_index": 4,
    }
    state.update(state_over)
    (meta / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return meta


def test_build_info_reads_live_position(tmp_path: Path):
    _mk_wf(tmp_path)
    info = sl.build_info(tmp_path, "t", NOW)
    assert info["sub_label"] == "理解问题和背景"
    assert (info["sub_step"], info["sub_steps_total"]) == (4, 7)
    assert info["interactive"] is False  # understand:1#4 红队步非交互
    assert sl.render_line(info) == "▸ 理解问题和背景 子4/7 · 待派发段"


def test_build_info_interactive_step_detected(tmp_path: Path):
    _mk_wf(tmp_path, sub_step_index=1)  # understand:1#1 是交互步
    info = sl.build_info(tmp_path, "t", NOW)
    assert info["interactive"] is True


def test_build_info_dead_pid_lock_not_running(tmp_path: Path):
    meta = _mk_wf(tmp_path)
    (meta / "front_segment.json").write_text(
        json.dumps(
            {
                "pid": 999999,  # /proc/999999 不存在 = 工人已死锁残留
                "started_at": "2026-08-11T22:51:48",
                "node": "understand:1",
                "sub_step": 2,
            }
        ),
        encoding="utf-8",
    )
    info = sl.build_info(tmp_path, "t", NOW)
    assert info["seg_elapsed_min"] is None  # 残留锁不算「段在跑」


def test_build_info_live_segment_elapsed(tmp_path: Path):
    meta = _mk_wf(tmp_path)
    (meta / "front_segment.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),  # 本测试进程 = 必活
                "started_at": "2026-08-11T23:08:00",
                "node": "understand:1",
                "sub_step": 4,
            }
        ),
        encoding="utf-8",
    )
    info = sl.build_info(tmp_path, "t", NOW)
    assert info["seg_elapsed_min"] == 12


def test_build_info_missing_state_never_raises(tmp_path: Path):
    # statusline 是 TUI 常驻件：任何缺失都不得抛异常（exit 0 兜底行）
    info = sl.build_info(tmp_path, "t", NOW)
    assert "不可读" in sl.render_line(info)
