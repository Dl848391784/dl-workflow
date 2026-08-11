#!/usr/bin/env python3
"""dl_statusline.py - v4 前台模式 statusLine 进度栏（v4-statusline-progress-design §5.1）。

per-wf settings.json 的 statusLine 命令（refreshInterval=10s 周期执行，
空闲也刷新），渲染单行进度到 TUI 底部。纯只读：state.json（实时位置）+
front_segment.json（段活性锁）+ drive-stream.jsonl 的 **mtime**（活性心跳，
禁读内容——26MB 级会爆 <100ms 预算）+ segment_summary.json（段结局便签）。

铁律：statusline 是 TUI 常驻件，任何异常都不得非零退出/抛栈——
兜底打印「? <name> state 不可读」让坏了可见（no silent fallback 的显示层形态）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_DLWF_ROOT = Path(__file__).resolve().parents[2]  # ~/.dl-workflow/
sys.path.insert(0, str(_DLWF_ROOT))
import dl_flow_engine as engine  # noqa: E402

# 卡死判读阈值（design §1：thinking 心跳保 mtime 新鲜，>3-5min 不动才疑似）；
# 取保守下界 180s。refreshInterval=10s 下警告最坏 190s 上屏。
STUCK_AFTER_S = 180

_YELLOW = "\033[33m"
_RED = "\033[31m"
_RESET = "\033[0m"


def render_line(info: dict) -> str:
    """纯函数：info -> 单行状态栏文本（六态状态机，design §5.1 渲染表）。"""
    if info.get("unreadable"):
        return f"? {info['name']} state 不可读"
    total = info["sub_steps_total"]
    pos = (
        f"{info['sub_label']} 子{info['sub_step']}/{total}"
        if total
        else info["phase_label"]
    )
    if info["seg_elapsed_min"] is not None:  # 段在跑（pid 已验活）
        base = f"⏳ {pos} · 段工人 {info['seg_elapsed_min']}min"
        age = info["stream_age_s"]
        if age is not None and age > STUCK_AFTER_S:
            return f"{base} · {_YELLOW}⚠ {int(age // 60)}min 无输出{_RESET}"
        return f"{base} · 活跃"
    if info["held_for_gate"]:
        return f"{_RED}⛔ {info['node']} 门栏 · 待 /dl gate{_RESET}"
    if info["interactive"]:
        return f"✋ {pos} · 本会话交互步"
    if info["summary_code"] is not None:
        return f"📋 段结局 code {info['summary_code']} · /dl status 判读"
    return f"▸ {pos} · 待派发段"


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _pid_alive(pid: object) -> bool:
    return isinstance(pid, int) and pid > 0 and Path(f"/proc/{pid}").exists()


def build_info(project_root: Path, name: str, now: datetime) -> dict:
    """IO 层：读 per-wf 目录小文件 + engine 单源标签，装配 render_line 输入。"""
    meta = project_root / ".claude" / "workflows" / name
    state = _read_json(meta / "state.json")
    if state is None:
        return {"unreadable": True, "name": name}
    info: dict = {
        "name": name,
        "node": state.get("node", "?"),
        "phase_label": engine.PHASE_LABELS.get(state.get("phase"), "?"),
        "sub_label": None,
        "sub_step": state.get("sub_step_index", 0),
        "sub_steps_total": 0,
        "interactive": False,
        "held_for_gate": bool(state.get("held_for_gate")),
        "seg_elapsed_min": None,
        "stream_age_s": None,
        "summary_code": None,
    }
    node = None
    try:
        node = engine.get_node(state.get("phase", ""), state.get("sub_index", 0))
    except KeyError:
        pass  # 节点定义缺失时退化为只显示大阶段标签（仍不崩）
    if node is not None:
        info["sub_label"] = node.label
        info["sub_steps_total"] = len(node.sub_steps)
        step = engine.sub_step_at(node, info["sub_step"])
        info["interactive"] = bool(step and step.interactive)
    seg = _read_json(meta / "front_segment.json")
    if seg and _pid_alive(seg.get("pid")):
        try:
            started = datetime.fromisoformat(seg["started_at"])
            info["seg_elapsed_min"] = int((now - started).total_seconds() // 60)
        except (KeyError, ValueError):
            info["seg_elapsed_min"] = 0
        try:
            age = now.timestamp() - (meta / "drive-stream.jsonl").stat().st_mtime
            info["stream_age_s"] = max(0.0, age)
        except OSError:
            info["stream_age_s"] = None  # 段刚起跑 stream 未创建，不报警
    summary = _read_json(meta / "segment_summary.json")
    if summary:
        info["summary_code"] = summary.get("code")
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--name", required=True)
    args = ap.parse_args()
    try:
        info = build_info(Path(args.project), args.name, datetime.now())
        print(render_line(info))
    except Exception:  # statusline 不得崩 TUI：坏要可见但不炸
        print(f"? {args.name} state 不可读")
    return 0


if __name__ == "__main__":
    sys.exit(main())
