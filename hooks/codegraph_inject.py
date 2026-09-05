#!/usr/bin/env python3
"""
UserPromptSubmit hook：用户提问时自动注入 codegraph 真实结构（瘦档）。

对应设计 designs/setup-installer-design.md（inject hook 集中化：本文件由项目
settings.json 以绝对路径引用，一份服务任意项目；项目根从 hook payload 解析）。

抵消分析类 fabrication：把 db 索引的真实 symbol 位置摆到面前，断言须与此一致。

瘦档：每符号取 name/kind/file_path:start_line 三列，~60 字节，不含代码体/签名。
容错：hook 协议字段不确定，stdin 解析失败/抽不到标识符/db 缺失 -> exit 0 静默不注入，
绝不报错打断用户。UserPromptSubmit 永不阻断（exit 0 only）。
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path


# 抽取 Python snake_case 标识符（≥3 字符，可含下划线/数字）
IDENT_RE = re.compile(r"[a-z][a-z0-9_]{2,}")

# 瘦档命中上限
MAX_SYMBOLS = 10
PER_QUERY_LIMIT = 3

# 模糊匹配时过滤掉的噪音 kind
NOISE_KINDS = {"import"}

# 模糊匹配时过滤掉的噪音 name 前缀
NOISE_NAME_PREFIXES = ("test_", "_test")

# worktree → 主仓映射标记：主仓存在本 hook 的 db 才替换 root
MARKER = Path(".codegraph") / "codegraph.db"

# 常见英文/语法噪音词；db 查不到的自然无命中，此过滤只为省查询。≥3 字符标识符
# （foo/bar 等）必须能通过——标识符是否真实存在以 db 查询为唯一裁决，不靠长度启发式。
STOPWORDS = frozenset(
    {
        "the",
        "for",
        "and",
        "not",
        "with",
        "from",
        "this",
        "that",
        "you",
        "are",
        "was",
        "were",
        "has",
        "have",
        "had",
        "can",
        "could",
        "should",
        "would",
        "will",
        "what",
        "when",
        "where",
        "which",
        "why",
        "how",
        "all",
        "any",
        "but",
        "did",
        "does",
        "done",
        "get",
        "got",
        "let",
        "new",
        "old",
        "use",
        "using",
        "used",
        "see",
        "look",
        "check",
        "please",
        "about",
        "into",
    }
)


def _project_root(payload: dict) -> Path:
    """项目根解析：payload.cwd → CLAUDE_PROJECT_DIR → 进程 cwd，各自经 git rev-parse 反查。"""
    candidates = [
        payload.get("cwd"),
        os.environ.get("CLAUDE_PROJECT_DIR"),
        str(Path.cwd()),
    ]
    for cand in candidates:
        if not isinstance(cand, str) or not cand:
            continue
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=cand,
                capture_output=True,
                text=True,
            )
        except OSError:
            continue
        if proc.returncode == 0 and proc.stdout.strip():
            return _resolve(Path(proc.stdout.strip()))
    return _resolve(Path.cwd())


def _map_worktree_to_main(root: Path, marker: Path) -> Path | None:
    """linked worktree → 主仓根：仅当主仓存在本 hook 的 db 标记时替换，否则 None（维持原 root）。

    判定：git-dir ≠ git-common-dir 即 linked worktree；主仓根 = common-dir 的 parent。
    任何失败（非 git/裸仓/命令缺失）返回 None——映射是增强，永不阻断。
    """
    try:
        run = subprocess.run(["git", "rev-parse", "--git-dir", "--git-common-dir"],
                             cwd=root, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if run.returncode != 0:
        return None
    lines = run.stdout.splitlines()
    if len(lines) < 2:
        return None
    git_dir, common = Path(lines[0]), Path(lines[1])
    if not git_dir.is_absolute():
        git_dir = (root / git_dir).resolve()
    if not common.is_absolute():
        common = (root / common).resolve()
    if git_dir == common:
        return None  # 主工作树
    main_root = common.parent
    if (main_root / marker).exists():
        return main_root
    return None


def _resolve(r: Path) -> Path:
    """候选 root 统一收口：worktree 场景映射为主仓根（有 db 才替换），否则原样。"""
    return _map_worktree_to_main(r, MARKER) or r


def _extract_prompt(payload: dict) -> str:
    """从 hook stdin payload 取提问文本（容错：试多个字段名）。"""
    for key in ("prompt", "prompt_text", "user_prompt", "message"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val
    # 嵌套尝试
    nested = payload.get("user_prompt", {})
    if isinstance(nested, dict):
        for key in ("prompt", "text", "content"):
            val = nested.get(key)
            if isinstance(val, str) and val.strip():
                return val
    return ""


def _extract_identifiers(text: str) -> list[str]:
    """从提问文本抽 snake_case 标识符，去停用词/短词，去重限前 MAX_SYMBOLS。"""
    found = IDENT_RE.findall(text)
    seen: set[str] = set()
    result: list[str] = []
    for tok in found:
        # 过滤常见噪音词；真实标识符是否存在于 db 由查询裁决
        if tok in STOPWORDS:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        result.append(tok)
        if len(result) >= MAX_SYMBOLS:
            break
    return result


def _query_symbol(
    conn: sqlite3.Connection, ident: str
) -> list[tuple[str, str, str, int]]:
    """查一个标识符：先精确 name 匹配，无命中再 FTS5 模糊。返回 (name,kind,file,start_line)。"""
    # 1) 精确匹配（最相关）
    rows = conn.execute(
        "SELECT name, kind, file_path, start_line FROM nodes WHERE name = ? LIMIT ?",
        (ident, PER_QUERY_LIMIT),
    ).fetchall()
    if rows:
        return rows

    # 2) FTS5 模糊匹配（过滤噪音 kind/name）
    try:
        fts_rows = conn.execute(
            "SELECT n.name, n.kind, n.file_path, n.start_line "
            "FROM nodes_fts f JOIN nodes n ON n.rowid = f.rowid "
            "WHERE nodes_fts MATCH ? LIMIT ?",
            (ident, PER_QUERY_LIMIT * 2),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [
        r
        for r in fts_rows
        if r[1] not in NOISE_KINDS and not r[0].startswith(NOISE_NAME_PREFIXES)
    ][:PER_QUERY_LIMIT]


def _freshness_warning(conn: sqlite3.Connection) -> str:
    """索引新鲜度（沿用 gate 72h 阈值）；过期附一行警告，否则空。"""
    import time

    try:
        row = conn.execute("SELECT MAX(indexed_at) FROM files").fetchone()
        if not row or not row[0]:
            return ""
        age_h = (time.time() - row[0] / 1000) / 3600
        if age_h > 72:
            return f"[codegraph] 索引 {age_h:.0f}h 前更新（>72h），结构可能过期，建议 codegraph sync。"
    except sqlite3.OperationalError:
        pass
    return ""


def _log_invocation(
    log_path: Path, status: str, prompt_len: int, n_idents: int, n_hits: int = 0
) -> None:
    """留痕每次 UserPromptSubmit 触发（观测性：确认 hook 是否真被 Claude Code 调用）。

    写文件非 stdout，不影响注入输出与测试。失败静默（留痕不得影响主流程）。
    """
    import time

    try:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(
                f"{ts}|{status}|prompt_len={prompt_len}|idents={n_idents}|hits={n_hits}\n"
            )
    except OSError:
        pass


def _format_injection(hits: list[tuple[str, str, str, int]], fw: str) -> str:
    """格式化瘦档注入文本。"""
    lines = ["## codegraph 自动注入（H15 证据源，瘦档；断言须与此一致）"]
    for name, kind, fpath, sline in hits:
        lines.append(f"- {name} ({kind}) - {fpath}:{sline}")
    lines.append("⚠️ 以上为 db 索引真实结构，跨文件调用/影响面断言须与此对齐。")
    if fw:
        lines.append(fw)
    return "\n".join(lines) + "\n"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            payload = {}
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        payload = {}  # 解析失败静默不注入（永不阻断；无 cwd 落到进程 cwd）

    root = _project_root(payload)
    codegraph_db = root / ".codegraph" / "codegraph.db"
    # UserPromptSubmit 触发留痕（观测性：确认 hook 是否真被 Claude Code 调用；非注入路径）
    inject_log = root / ".claude" / ".cg_inject.log"

    prompt = _extract_prompt(payload)
    idents = _extract_identifiers(prompt)
    if not idents:
        _log_invocation(inject_log, "no_idents", len(prompt), 0)
        return 0  # 无标识符（纯闲聊/无代码内容）不注入

    if not codegraph_db.exists():
        _log_invocation(inject_log, "no_db", len(prompt), len(idents))
        return 0  # db 缺失不注入

    try:
        conn = sqlite3.connect(f"file:{codegraph_db}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        _log_invocation(inject_log, "db_open_fail", len(prompt), len(idents))
        return 0

    try:
        hits: list[tuple[str, str, str, int]] = []
        for ident in idents:
            hits.extend(_query_symbol(conn, ident))
            if len(hits) >= MAX_SYMBOLS:
                break
        hits = hits[:MAX_SYMBOLS]
        if not hits:
            _log_invocation(inject_log, "no_hits", len(prompt), len(idents))
            return 0
        fw = _freshness_warning(conn)
        context = _format_injection(hits, fw)
        # UserPromptSubmit 注入协议：结构化 JSON additionalContext 才进模型上下文。
        # 裸 stdout 不被投递（2026-07-22 端到端实测）。
        out = json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context,
                }
            },
            ensure_ascii=False,
        )
        sys.stdout.write(out)
        _log_invocation(inject_log, "injected", len(prompt), len(idents), len(hits))
    except sqlite3.Error:
        _log_invocation(inject_log, "query_error", len(prompt), len(idents))
        return 0  # 查询出错静默不注入
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
