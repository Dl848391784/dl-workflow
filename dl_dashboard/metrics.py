"""每段耗时/轮数/成本聚合：segment_sessions join segment_stats.jsonl（新）
或 drive-stream.jsonl result 事件（旧工作流回退，offset 书签增量扫）。"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from dl_dashboard.scanner import meta_root

log = logging.getLogger("dl_dashboard.metrics")


@dataclass(frozen=True)
class SegmentStat:
    session_id: str
    kind: str
    node: str
    sub_step: int
    ts: str
    note: str
    num_turns: int | None
    duration_s: int | None
    cost_usd: float | None


def _load_stats_jsonl(meta: Path) -> dict[str, dict]:
    p = meta / "segment_stats.jsonl"
    stats: dict[str, dict] = {}
    if not p.exists():
        return stats
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            log.warning("segment_stats.jsonl 损坏行跳过: %s", p, exc_info=True)
            continue
        sid = ev.get("session_id")
        if sid:
            stats[sid] = ev
    return stats


def _legacy_result_stats(meta: Path, cache_dir: Path, slug: str) -> dict[str, dict]:
    """旧工作流回退：增量扫 drive-stream.jsonl 的 result 事件。

    该文件是原始流（858k 行级，混 SDK 噪声行），全量扫太贵——offset 书签 +
    已提取统计缓存在 cache_dir/<slug>.json；文件截断（size < offset）重置重扫。
    解析失败的行跳过（噪声行是常态），JSON 层异常记 log 不吞。
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_p = cache_dir / f"{slug}.json"
    offset, stats = 0, {}
    if cache_p.exists():
        try:
            d = json.loads(cache_p.read_text(encoding="utf-8"))
            offset, stats = int(d.get("offset", 0)), d.get("stats", {})
        except (json.JSONDecodeError, ValueError, OSError):
            log.warning("legacy stats 缓存损坏，重置重扫: %s", cache_p)
            offset, stats = 0, {}
    stream = meta / "drive-stream.jsonl"
    if not stream.exists():
        return stats
    size = stream.stat().st_size
    if size < offset:
        offset, stats = 0, {}
    with open(stream, "r", encoding="utf-8", errors="replace") as fh:
        fh.seek(offset)
        for line in fh:
            if '"result"' not in line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                log.warning("drive-stream.jsonl 损坏行跳过: %s", stream, exc_info=True)
                continue
            if ev.get("type") == "result" and ev.get("session_id"):
                stats[ev["session_id"]] = ev
        offset = fh.tell()
    try:
        cache_p.write_text(
            json.dumps({"offset": offset, "stats": stats}), encoding="utf-8")
    except OSError:
        log.warning("legacy stats 缓存写失败: %s", cache_p, exc_info=True)
    return stats


def collect_stats(project: Path, name: str, cache_dir: Path) -> list[SegmentStat]:
    meta = meta_root(project, name)
    state = json.loads((meta / "state.json").read_text(encoding="utf-8"))
    segs = state.get("segment_sessions", [])
    slug = f"{str(project).replace('/', '_')}--{name}"
    legacy = _legacy_result_stats(meta, cache_dir, slug)
    current = _load_stats_jsonl(meta)
    stats = {**legacy, **current}  # 新埋点优先
    out: list[SegmentStat] = []
    for seg in segs:
        st = stats.get(seg.get("session_id"), {})
        dur = st.get("duration_ms")
        out.append(SegmentStat(
            session_id=str(seg.get("session_id", "")),
            kind=str(seg.get("kind", "")),
            node=str(seg.get("node") or "?"),
            sub_step=int(seg.get("sub_step") or 0),
            ts=str(seg.get("ts", "")),
            note=str(seg.get("note", "")),
            num_turns=st.get("num_turns"),
            duration_s=int(dur) // 1000 if dur is not None else None,
            cost_usd=st.get("total_cost_usd"),
        ))
    return out


def totals(stats: list[SegmentStat]) -> dict:
    return {
        "num_turns": sum(s.num_turns for s in stats if s.num_turns is not None),
        "duration_s": sum(s.duration_s for s in stats if s.duration_s is not None),
        "cost_usd": round(sum(s.cost_usd for s in stats if s.cost_usd is not None), 4),
    }
