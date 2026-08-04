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


def test_token_file_takes_precedence_over_env():
    """v2.86：.token 文件优先于 env（禁「env 非空就不读文件」）。

    根因——主会话 provider env（ark 等）会继承进重放子进程，其
    ANTHROPIC_AUTH_TOKEN 非空但不是 MiniMax 凭证；原逻辑
    `if not env: 读文件` 使 .token 在主会话下永远读不到，随后
    拿 ark token 断言 sk- 前缀必挂（与 BASE_URL 禁 setdefault 同族
    的「继承值优先」坑，症状 V）。
    """
    src = (REPLAYS / "_common.py").read_text()
    setup = src[src.index("def setup_env") : src.index("def judge_scope")]
    assert 'if not os.environ.get("ANTHROPIC_AUTH_TOKEN")' not in setup, (
        "env 非空即跳过读 .token=继承值优先坑回潮（主会话下 .token 永远读不到）"
    )
    # 文件读取无条件前置于断言：.token 在场即覆盖 env
    read_pos = setup.index('os.environ["ANTHROPIC_AUTH_TOKEN"] = f.read_text()')
    assert read_pos < setup.index("assert tok.startswith"), "读 .token 须前置于断言"
