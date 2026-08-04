#!/usr/bin/env python3
"""重放共享件（designs/replay-fixtures-persistence-design.md）。

用法：python3 tests/replays/replay_u1_subN.py [N] [gate_file]
- N=每载荷重放次数（默认 6，§3.5 #28：n=4 全对是载荷巧合假象）
- gate_file 可选：候选 gate 文本迭代（默认现网 gate）

token：从 env ANTHROPIC_AUTH_TOKEN 读；或写一行到 tests/replays/.token
（已 gitignore）。**禁把 token 字面提交进脚本**（test_replay_scripts.py pin）。
"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import dl_flow_engine as E  # noqa: E402
import dl_flow_nodes as N  # noqa: E402


def setup_env():
    """provider 三件套硬赋值（禁 setdefault——主会话 provider env 会继承，
    setdefault 保留继承值=请求打错端点流式挂起不报错，症状 V）。

    token 同理**优先 .token 文件**（v2.86）：.token 是为 MiniMax 端点专备的
    凭证，env 的 ANTHROPIC_AUTH_TOKEN 是主会话 provider（ark 等）继承来的
    无关值。原逻辑 `if not env: 读文件` 在主会话下永远走不到读文件分支，
    然后拿 ark token 去断言 sk- 前缀必挂——与 BASE_URL 禁 setdefault 同族的
    「继承值优先」坑。env 仅在无 .token 时兜底（CI/裸终端）。
    """
    f = Path(__file__).parent / ".token"
    if f.is_file():
        os.environ["ANTHROPIC_AUTH_TOKEN"] = f.read_text().strip()
    tok = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    assert tok.startswith("sk-"), (
        "缺 MiniMax token——写一行到 tests/replays/.token（推荐，已 gitignore），"
        f"或 export ANTHROPIC_AUTH_TOKEN=sk-...（当前 env 值前缀 "
        f"{tok[:4] + '…' if tok else '空'} 非 sk-，多为主会话 provider 继承值）"
    )
    os.environ["ANTHROPIC_BASE_URL"] = "https://api.minimaxi.com/anthropic"
    os.environ["ANTHROPIC_MODEL"] = "MiniMax-M3"
    os.environ["ANTHROPIC_SMALL_FAST_MODEL"] = "MiniMax-M3"
    os.environ["MAX_THINKING_TOKENS"] = "0"  # v2.44：judge 子进程禁思考链


def judge_scope(step):
    """mech_scope 字符串：step.mech_checks + extra_payload_keys 规格名。"""
    scope = list(step.mech_checks or ())
    for _e in getattr(step, "extra_payload_keys", ()):
        _k, _spec = _e[0], _e[1]
        scope.append(_spec if isinstance(_spec, str) else f"{_k}前缀")
    return "、".join(scope)


def run_cases(title, step, label, cases, expect, n=6, gate=None):
    """cases: {name: artifact_str}；expect: {name: bool}。三向判定打印 + RESULT_JSON。"""
    gate = gate if gate is not None else step.gate
    scope = judge_scope(step)
    print(f"{title} gate_len={len(gate)} scope={scope} n={n}\n", flush=True)
    res = {"gate_len": len(gate), "n": n}

    def one(art):
        def call(_):
            return E.run_judge(
                gate,
                label,
                "",
                artifact_content=art,
                prior_verdicts=[],
                mech_scope=scope,
            )

        with ThreadPoolExecutor(max_workers=3) as ex:
            return list(ex.map(call, range(n)))

    for name, art in cases.items():
        out = one(art)
        good = sum(1 for ok, _ in out if ok == expect[name])
        res[name] = f"{good}/{n}"
        print(
            f"=== {name}（期望 {'PASS' if expect[name] else 'BLOCK'}，命中 {good}/{n}）===",
            flush=True,
        )
        for i, (ok, r) in enumerate(out):
            print(f"  [{i + 1}] pass={ok} | {r[:180]}", flush=True)
    print("\nRESULT_JSON: " + json.dumps(res, ensure_ascii=False), flush=True)
    return res


def sub_step(node_id, idx):
    return N._NODES[node_id].sub_steps[idx]
