#!/usr/bin/env python3
"""provider 缓存能力探针（v4-cost-latency-optimization-design.md §2.0b）。

判定一个 anthropic 兼容端点的缓存语义，四格矩阵：
  C1 非流式同 prompt 重发（60s 后）     -> 跨调用共享 + TTL>60s
  C2 非流式同 system 不同 user          -> 前缀粒度部分给分
  C3 流式 claude -p 同 prompt 重发      -> 跨会话流式命中（生产段冷启动是否可解）
  C4 流式同会话多轮（claude -p 内部）   -> 会话内缓存（基线对照，通常必中）

用法：
  PROBE_BASE_URL=https://api.deepseek.com/anthropic PROBE_MODEL=deepseek-v4-flash \
  PROBE_TOKEN=xxx python3 scripts/probe/cache_probe.py
token 只走环境变量，禁止落盘/打印。

已知结果：deepseek（2026-08-12）：C1 命中 / C2 部分命中 / C3 零命中（会话级隔离）。
"""
import json, os, subprocess, sys, time, urllib.request

BASE = os.environ["PROBE_BASE_URL"].rstrip("/")
MODEL = os.environ["PROBE_MODEL"]
TOKEN = os.environ["PROBE_TOKEN"]
URL = BASE + "/v1/messages"
WF = "/home/admin/projects/factor_ic_analyzer/.claude/workflows/interaction_turnover__ret3d_abs_annualized"

S = open(f"{WF}/phase-rules.rendered.md").read()
U1 = open(f"{WF}/node-rules.understand:1.md").read() + open(f"{WF}/fetch-prompt-skeleton.md").read()
U2 = open(f"{WF}/node-rules.plan:1.md").read() + open(f"{WF}/node-rules.plan:2.md").read()

def curl_call(tag, user, stream=False):
    # 裸 API 模型 id 须剥 claude-code 的 [1m] 类窗口后缀（kimi 401 实证）
    body = json.dumps({"model": MODEL.split("[")[0], "max_tokens": 16, "stream": stream,
                       "system": S, "messages": [{"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "content-type": "application/json", "x-api-key": TOKEN,
        "authorization": f"Bearer {TOKEN}",
        "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=300) as r:
        raw = r.read()
    u = None
    try:
        u = json.loads(raw).get("usage")
    except Exception:
        for line in raw.decode("utf8", "replace").splitlines():
            if line.startswith("data:") and '"usage"' in line:
                try:
                    ev = json.loads(line[5:])
                    u = ev.get("usage") or (ev.get("message") or {}).get("usage") or u
                except Exception:
                    pass
    print(f"{tag}: {json.dumps(u)}", flush=True)
    return u

def claude_p(tag):
    env = dict(os.environ, ANTHROPIC_BASE_URL=BASE, ANTHROPIC_AUTH_TOKEN=TOKEN,
               ANTHROPIC_MODEL=MODEL, ANTHROPIC_SMALL_FAST_MODEL=MODEL, ANTHROPIC_LOG="")
    out = subprocess.run(
        ["claude", "-p", "回复 ok 即可", "--output-format", "json",
         "--append-system-prompt-file", f"{WF}/node-rules.plan:2.md"],
        capture_output=True, text=True, env=env, timeout=180,
        cwd="/home/admin/projects/factor_ic_analyzer/.claude/worktrees/interaction_turnover__ret3d_abs_annualized")
    try:
        u = json.loads(out.stdout).get("usage", {})
    except Exception:
        u = {"error": (out.stdout + out.stderr)[:200]}
    print(f"{tag}: in={u.get('input_tokens')} cache_read={u.get('cache_read_input_tokens')} "
          f"cache_create={u.get('cache_creation_input_tokens')}", flush=True)

print(f"== probe {BASE} model={MODEL} ==", flush=True)
curl_call("C0_warm", U1)            # 暖场
time.sleep(60)
curl_call("C1_nonstream_repeat", U1)
curl_call("C2_nonstream_diff_user", U2)
claude_p("C3a_stream_first")
time.sleep(15)
claude_p("C3b_stream_repeat")
print("done", flush=True)
