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
    input_tokens: int | None
    output_tokens: int | None
    cache_read_input_tokens: int | None
    cache_creation_input_tokens: int | None


def _tok(st: dict, key: str) -> int | None:
    """token 字段归一：新埋点是平铺键，旧流 result 事件嵌在 usage 里。"""
    v = st.get(key)
    if v is None:
        v = (st.get("usage") or {}).get(key)
    return v


def _load_stats_jsonl(meta: Path) -> dict[str, list[dict]]:
    """segment_stats.jsonl -> sid 有序行列表。

    一个 sid 可有多行（合并段逐 turn / 段链续步 / inject resume 同会话）——
    旧版 dict 末行覆盖，多行 sid 的早 turn 统计被吞（合并段步骤时间轴
    缺进度条实爆）；保序列表供 collect_stats 按台账行序逐个配对。"""
    p = meta / "segment_stats.jsonl"
    stats: dict[str, list[dict]] = {}
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
            stats.setdefault(sid, []).append(ev)
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
        if not isinstance(stats, dict):
            log.warning("legacy stats 缓存 stats 非 dict，重置重扫: %s", cache_p)
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
    current = _load_stats_jsonl(meta)  # sid -> 有序行列表（新埋点）
    out: list[SegmentStat] = []
    consumed: dict[str, int] = {}
    for seg in segs:
        # merged-outer（合并段外层汇总留痕）：不进时间轴/统计——逐 turn
        # merged-step 行才是统计载体；本行若参与配对，clamp 会把末 turn
        # 统计在收尾步上重复计一次
        if seg.get("kind") == "merged-outer":
            continue
        sid = seg.get("session_id")
        if sid in current:
            # 多行 sid（合并段/段链）按台账行序逐个配对（双方同序追加）；
            # 行不足钳到末行（近似，不丢行）；legacy 被 current 整 sid 遮蔽
            rows = current[sid]
            idx = consumed.get(sid, 0)
            st = rows[min(idx, len(rows) - 1)]
            consumed[sid] = idx + 1
        else:
            st = legacy.get(sid, {})
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
            input_tokens=_tok(st, "input_tokens"),
            output_tokens=_tok(st, "output_tokens"),
            cache_read_input_tokens=_tok(st, "cache_read_input_tokens"),
            cache_creation_input_tokens=_tok(st, "cache_creation_input_tokens"),
        ))
    return out


def totals(stats: list[SegmentStat]) -> dict:
    return {
        "num_turns": sum(s.num_turns for s in stats if s.num_turns is not None),
        "duration_s": sum(s.duration_s for s in stats if s.duration_s is not None),
        "cost_usd": round(sum(s.cost_usd for s in stats if s.cost_usd is not None), 4),
        "input_tokens": sum(s.input_tokens for s in stats if s.input_tokens is not None),
        "output_tokens": sum(s.output_tokens for s in stats if s.output_tokens is not None),
        "cache_read_input_tokens": sum(
            s.cache_read_input_tokens for s in stats if s.cache_read_input_tokens is not None),
        "cache_creation_input_tokens": sum(
            s.cache_creation_input_tokens for s in stats if s.cache_creation_input_tokens is not None),
    }
