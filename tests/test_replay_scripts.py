"""tests/replays/ 防回归守卫（designs/replay-fixtures-persistence-design.md）。

- 全脚本 py_compile（语法腐坏即红——重放资产是 v2.76 回归义务的执行件）；
- 无 `sk-` token 字面（scrubbing 防回流：内联 token 既是泄漏面，又触发
  权限分类器 stage 1 拦截，token 只走 env 或 gitignored .token）。
"""
import py_compile
import re
from pathlib import Path

REPLAYS = Path(__file__).parent / "replays"

# 真 token 形态：sk- 后接长串（_common.py 的 startswith("sk-") 校验前缀不命中）
_TOKEN_RE = re.compile(r"sk-[A-Za-z0-9_-]{20,}")


def test_replay_scripts_compile():
    files = sorted(REPLAYS.glob("*.py"))
    assert files, "tests/replays/ 无脚本——重放资产缺失"
    for f in files:
        py_compile.compile(str(f), doraise=True)


def test_replay_scripts_no_inline_token():
    for f in sorted(REPLAYS.glob("*.py")):
        assert not _TOKEN_RE.search(f.read_text()), (
            f"{f.name} 含内联 token 字面——token 只走 env ANTHROPIC_AUTH_TOKEN "
            "或 gitignored tests/replays/.token"
        )
