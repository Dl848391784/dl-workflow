# 围栏与门控健壮性修复设计（fence S15 python3 + 骨架兜底 + advance pending agent）

> 2026-08-05，源会话 `tail_volume_acceleration_annualized` cc_debug.log 实证三个系统级摩擦。
> 强模型也踩 = 围栏/门控设计不够健壮，非模型能力问题。三处系统侧修复。

## 一、问题与根因（均经 cc_debug.log 坐实）

### Q1(a)：fetch-prompt-skeleton.md 的 Write 被拒 4 次
- **现象**：模型用 Write/Edit 手写 `.claude/workflows/<name>/fetch-prompt-skeleton.md`，S11 围栏 deny「understand 阶段禁止写源码，可写：understand.md/.claude/understands/designs/*.md/.claude/evidence/」。
- **根因**：S11 写白名单 `_phase_write_path_ok`（engine:2053）understand 阶段放行 `understand.md`/`designs/*.md`/`.claude/evidence/`/`.claude/understands/`，骨架文件路径 `.claude/workflows/<name>/` 不在白名单。骨架本应由引擎 `fetch-prompt --out` 生成（实证 12:50 落盘成功 12KB），模型只该 Read；但模型仍手写被拦。
- **性质**：围栏拦截正确（骨架引擎独占写），但缺兜底--模型手写时无自动纠正，只 deny 文案，强模型也可能重复试。

### Q2：S15 前置围栏拦子步骤 2 共 40 次
- **现象**：子步骤 2（因果推理）零 trace 窗口内，模型用 `Bash python3 -c` 读 ob_quality JSON 做因果链，被 S15 deny 18 次（另 18 次同源）。
- **根因**：S15 只读发现白名单 `_S15_READONLY_CMD_RE`（fence:163）= find/ls/grep/rg/cat/head/tail/wc/sort/uniq/file/stat/...，**不含 python3**。子步骤 2 因果链要求每环 file:line 证据指针，读 JSON 字段需 python3（CLAUDE.md §3 明确推荐 python3 读 parquet/数据），但零 trace 窗口禁 python3 = 合法取证通道被关。
- **性质**：S15 设计前提「零 trace 窗口只该编排+只读发现」与子步骤 2「读数据才能写有证据 trace」冲突（先有鸡先有蛋）。

### Q1(a)+Q2 统一根因
两者同根：**围栏的工具白名单与子步骤实际所需的合法工具不匹配**。Q1(a) 缺骨架文件的正确写通道（引擎 --out），Q2 缺 python3 只读数据通道。但两者工具语义不同，解法各异（见下）。

### Q3：understand:1#3 第一次 GATE 假性 block
- **时序（cc_debug.log 实证）**：
  - 12:50:13 子2 通过门控 -> 子3
  - 12:51:29 派 light agent（后台，durationMs=4 立即返回）
  - 12:52:57 light agent handback「建议升档 full」
  - 12:53:42 派 full agent（后台，durationMs=4）
  - 12:54:36 模型写 trace-payload（**仅含 light 报告，full 未归**）
  - **12:54:56 模型结束回合 -> Stop hook S13 围栏 block「子步骤 3 无任何 skill-trace」**（full agent 12:56:26 才 handback）
  - 12:56:26 full agent handback -> 模型 ingest 两份报告 + 落 trace
  - 13:00:25 子3 通过门控
- **根因**：Stop hook S13 参与围栏（advance:316）在 `latest_trace_sha1 is None` 时无条件 block「无 trace」。模型派后台 agent 后、agent 未归前结束回合 = trace 必然未落 = 假性 block。门控不感知 pending background agent。
- **性质**：门控与后台 agent 生命周期脱节。子步骤 3 文案要求「派发后台 agent + 重叠做③」，但模型若在 agent 归来前 end_turn，门控必拦「无 trace」，agent 回来后才能补过 = 一次假性返工。

## 二、方案设计

### 解法 1（Q1a）：骨架 Write 副作用兜底
PreToolUse hook 只能 allow/deny（协议无「转换」语义），用 **deny + 副作用执行正确命令** 等价实现：

- fence 识别 `tool in _WRITE_TOOLS` 且目标 basename == `fetch-prompt-skeleton.md` 且路径含 `.claude/workflows/`：
  - 副作用：`subprocess` 跑 `python3 <engine> fetch-prompt --out`（刷新骨架为引擎版本，idempotent）
  - 返回 deny 文案「骨架由引擎 --out 生成，已自动刷新，Read 取用，禁手写/禁自选落盘路径」
- 位置：workflow_step_fence.py，S14 段（line 279）之后、S11 段（line 330）之前，加骨架专属拦截。
- 幂等：重跑 --out 覆盖为引擎模板，无害（骨架本就该引擎独占，模型只在末尾 claim 区填，inline 给 agent，不写回文件）。

### 解法 2（Q2）：S15 放行 python3 只读数据
用户决议：白名单放行 python3 只读（威胁模型=强模型非对抗，同 S11 Bash 盲区口径）。

- `_s15_bash_readonly_discovery` 按段校验中，段以 `python3 -c` / `python -c` 开头时，对 `-c` 内容做**轻量写信号检测**：
  - 写信号（一票否决）：`open(...'w'/'a'/'x'`、`os.system`、`subprocess`、`popen`、`exec(`、`eval(`、`__import__`、`shutil.`、`.write(`、`os.remove`、`os.unlink`、`Path(...).write`、`dump` 到文件
  - 无写信号 -> 放行（只读数据读取：json.load/open read/print/pandas read）
- 不裸放行 `python3 script.py`（跑外部脚本不可判定），只放行 `python3 -c`（内联可扫描）。
- 位置：`_S15_READONLY_CMD_RE` 旁新增 `_s15_python_readonly(cmd) -> bool`，`_s15_bash_readonly_discovery` 段判定调用。
- 已知限制：写信号扫描可被绕过（强模型非对抗，接受，同 S11 Bash 盲区）。

### 解法 3（Q3）：Stop hook 检测 pending agent 延后门控
用户决议：检测 pending 则延后门控。

- advance.py S13 围栏（line 316）前，调 `_pending_background_agent_count(transcript_path)`：
  - 流式读 transcript JSONL，收集 assistant message 里 `name=="Agent"` 的 tool_use_id 集合，减去 user message 里已出现的 tool_result 的 tool_use_id 集合 = pending 数。
  - **pending > 0 -> return 0（静默放行，延后门控）**，不判「无 trace」block。
  - 机制理由（静默放行 vs block 文案）：
    - block 文案「等 agent」会让模型继续生成空转，agent 跑 2-4min 期间烧 token；且 block 期间异步 handback 能否注入不确定。
    - 静默放行让回合干净结束，agent handback 作为 user message 重新激活主会话，模型届时 ingest+写 trace+end_turn -> Stop 再触发 -> 此时 pending=0 -> 正常门控。
    - 「延后门控」核心 = pending 时不判「无 trace」，静默放行达成此意图且无空转。
  - 兜底：agent 必然 handback 或报错（Claude Code 保证）；极端不回调时用户可 /dl 手动处置。
- 位置：advance.py main() line 316 S13 判定前；检测函数放 advance.py（或 engine，若复用）。

### 解法 3 修订（B 方案，2026-08-05 用户确认）：放行 TaskOutput 为主路径
深入排查 cc_debug.log 发现决定性证据：**12:54:50 模型调用了 `TaskOutput` 工具试图主动等后台 agent 结果，被 S15 围栏误拦**（"子步骤 3 尚未开始"）。模型被拦后无法等 agent，3 秒后 end_turn 触发假性 GATE block。

- **根因修正**：子步骤 3 `fence_allow=("Bash","Agent")`（dl_flow_nodes.py:956）漏了 TaskOutput。TaskOutput 是 harness 原生"主会话阻塞等/取后台 agent 结果"机制，模型本就在用，是围栏没放行。
- **主路径（B 方案）**：子3/子4 的 `fence_allow` 加 `TaskOutput`。模型派后台 agent 后用 TaskOutput 阻塞等结果 -> agent 归来 -> ingest+写 trace -> end_turn -> 门控审。**零空转、零死锁风险、用 harness 原生机制**。优于 hook sleep（依赖未验证的"hook 阻塞期间 agent 能并行"假设）和静默放行（依赖未验证的"handback 能激活已停止会话"假设）。
- **pending 检测（解法3 原版）保留为兜底**：万一模型不用 TaskOutput 直接 end_turn，S13 仍会拦。pending 检测在此时静默放行，避免假性 block。两个机制叠加：TaskOutput 主路径让模型主动等，pending 检测兜底防抢跑。
- **新增改动文件**：dl_flow_nodes.py（子3 fence_allow 加 TaskOutput、子4 同）。

## 三、改动文件

| 文件 | 改动 |
|---|---|
| hooks/workflow_step_fence.py | 解法1 骨架兜底段 + 解法2 `_s15_python_readonly`/段判定 |
| hooks/workflow_advance.py | 解法3 兜底 `_pending_background_agent_count` + S13 前置短路 |
| dl_flow_nodes.py | 解法3 主路径：子3/子4 `fence_allow` 加 TaskOutput |
| dl_flow_engine.py | 无（白名单/检测函数均在 hook/nodes 内） |

## 四、风险与权衡

1. **解法1 subprocess 延迟**：hook 内跑引擎命令 ~1-2s。仅在模型 Write 骨架时触发（异常路径），正常流程（--out 落盘+Read）不触发。可接受。
2. **解法2 写信号绕过**：python3 -c 内联扫描非完备。威胁模型=强模型非对抗，同 S11 Bash 盲区已接受口径。裸 `python3 script.py` 仍拒（只放行 -c）。
3. **解法3 TaskOutput 放行范围**：仅子3/子4（派发 Agent 的步骤）放行，子2 等无 Agent 步骤仍拒（test_step2_taskoutput_denied 验证）。TaskOutput 只取已派发 agent 结果，无写/探查副作用，放行安全。
4. **解法3 兜底静默放行**：pending 检测静默放行依赖"handback 能激活已停止会话"--TaskOutput 主路径打通后此路径触发概率极低（模型会用 TaskOutput 等），作为兜底可接受；若主路径稳定可后续移除兜底。
5. **解法3 transcript 读取成本**：transcript 可达 ~MB 级，流式读 JSONL 统计 tool_use/tool_result，不 json.load 全量（OOM 风险，同 CLAUDE.md 大 JSON 约束）。

## 五、测试计划（TDD）

- 解法1：fence 测试--Write 骨架路径 -> deny + 副作用 --out 被调（mock subprocess）+ 文案含「已自动刷新」；非骨架路径不受影响。
- 解法2：`_s15_python_readonly` -- `python3 -c "import json;print(json.load(open('x'))['y'])"` 放行；`python3 -c "open('y','w').write('z')"` 拒；`python3 script.py` 拒；混合段（python3 -c 只读 | grep）放行、（python3 -c 写 | ls）拒。
- 解法3 主路径（TaskOutput）：fence 测试--子3 TaskOutput 放行、子4 TaskOutput 放行、子2 TaskOutput deny；engine 测试--子3 fence_allow==("Bash","Agent","TaskOutput")、子4==("Agent","TaskOutput")。
- 解法3 兜底（pending 检测）：`_pending_background_agent_count` -- 构造 transcript fixture：1 Agent tool_use 无 tool_result=1 pending；1 tool_use+1 tool_result=0；2 tool_use+1 tool_result=1；空 transcript=0；非 Agent tool_use 不计。advance S13 短路：pending>0 时 return 0 不 block。
