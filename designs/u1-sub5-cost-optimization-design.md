# understand:1 子5（质检裁决）耗时/token 优化设计

> 立项：2026-08-17 用户 goal「优化 understand:1 step5，耗时和 token 大幅降低」。
> 前置：子2a/2b（plan-first 拆步 + v2.44 探索预算）、子4（u1-sub4-cost-optimization-design）已优化；
> u:1 段链回滚（c384738 修3）已落地——本设计的 token 基线按**回滚后 fresh 段**推算。
> 用户裁决（2026-08-17 AskUserQuestion）：修3 红队预派发=**做**；修4 解析器未知标头宽容=**不做**。

## 1. 诊断数据（amplitude_annualized 三轮实测，链时代基线）

step5 段边界 = segment_sessions 完成时刻差；token = transcript 按 message.id 去重（runtime-audit #17）。

| 轮次 | 墙钟 | 主会话 calls | 主会话 cache_read | fresh | out | 红队子代理 |
|---|---|---|---|---|---|---|
| 2be32d62（08-15 00:05 链） | 7.2min | 19 | 5.18M | 250k | 35k | 158s / 13 calls / 0.67M cr |
| e3d8752b（08-15 08:04 链） | 7.3min | 15 | 4.77M | 33k | 32k | 163s / 16 calls / 0.67M cr |
| 200fb21a（08-17 01:12 链） | 7.4min | 18 | 4.81M | 270k | 26k | 235s / 10 calls / 0.52M cr |

### 瓶颈分三层定位（cost-optimization #1）

1. **链上下文膨胀层（token 大头，已修）**：链内继承上下文 ~270-300k/轮全量重读 → 主会话
   cache_read ~5M。c384738 已把 u:1 移出 SEGMENT_CHAIN_NODES，回滚后 fresh 段首调 ~45k，
   本设计不再投入，只把剩余修复建立在新基线上。
2. **机械层误报返工层（3/3 轮全中，每轮 2 次拒 ≈ 1-1.5min + 4-6 次全上下文调用）**：
   - **Bug C task-id 误报**（轮 1/2，共 4 次拒）：`_TASK_ID_RE = \b[0-9a-f]{16,17}\b`
     把证据里的 Python float repr 小数位（0.49519773767901265 → `49519773767901265`、
     0.9807… → `9806949806949807`、`48244678899192833`、`1194141004217242`）当 task-id
     → `_dispatched_vs_unrecorded_task_ids` 假阳性「已派发未收录」。模型为过关被迫
     改写/挪动合法证据数值。与 step4 Bug A（防重误报）同族——那是 ingest 防重侧，
     这是 v2.118 修B 派发配对侧，同一词形过宽病根。
   - **Bug D 三件套「置信度」字面过严**（轮 3）：redteam-prompt 模板输出节只写
     「verdict / 推理链 / 置信度」未钉逐字标签，红队实际输出「**置信** 95%」→
     `_check_redteam_three_piece` 按字面「置信度」扫 → 拒 → 模型手工补标签。
   - （不修）解析器未知【标头】拒（轮 3，1 次）：报错文案清晰、模型 1 轮恢复
     （~10-20s），宽容化有真结构错误静默放过风险——用户裁决不做。
3. **红队等待 = 墙钟地板（3-4 min）**：红队子代理运行 158-235s；主会话有效利用
   ≤1min（轮2 派发后 26s 即 block 干等 2.7min 零并行；轮3 做了①质检 ~50s 后
   block 176s）。purpose 已钉「先派发后内查」（v2.39）——弱模型遵从不稳，
   文案无解。红队输入只依赖 ≤子4 trace（redteam-prompt 机械保证不含子5 结论），
   **子4 gate 一过即具备派发条件**，与 step5 主会话天然并行。

### 预期收益（step5 单步，回滚后基线上叠加）

- 墙钟 7.2-7.4min → ~3.5-4.5min（红队等待 3-4min 基本归零 + 拒收返工 -1~1.5min）；
- 主会话 calls 15-19 → ~11-13；cache_read 在回滚后 ~1-1.5M 基础上再 -0.3~0.5M；
- 代价：红队未触发的罕见场景浪费一次预派发（~30-40k fresh + 0.5-0.7M cr）——
  历史上红队近乎必触发（purpose 禁自定义豁免），用户已裁决接受。

## 2. 方案（三修）

### 修 1（Bug C）：_TASK_ID_RE 排除数值误报

```python
_TASK_ID_RE = re.compile(r"(?<![0-9a-f.])(?=[0-9a-f]*[a-f])[0-9a-f]{16,17}(?![0-9a-f])")
```

- `(?<![0-9a-f.])`：前邻不是 hex 字符或 `.`——小数位段（`.4951977…`）整段排除；
- `(?=[0-9a-f]*[a-f])`：候选须含至少一个 a-f 字母——纯数字 16-17 位串排除；
- `(?![0-9a-f])`：后邻不是 hex 字符（替代 `\b`，防贴更长 hex 串）。
- 真实 id（a538a700d0d5e496d / a9b273c9bd788e857 / a5ca6ea271e5e937e）均含字母，命中不变。
- 权衡留痕：未来若出现纯数字真 task-id（概率 ~(10/16)^17 ≈ 3e-4）将不被配对检查
  识别 → 落回 judge 真值判（宁纵勿枉方向，可接受）；float 证据在质检类载荷里是
  常态（3/3 轮中），误报方向不可接受。

### 修 2（Bug D）：三件套双侧钉死

- **模板侧**：redteam-prompt【输出】节钉逐字标签 + 范例行：
  「每原子三行，标签逐字照写：`verdict: 证实|证伪|部分成立|证据不足` /
  `推理链: …（引用证据指针）` / `置信度: N%`——「推理链」「置信度」两标签
  逐字（勿简写「置信」），收录侧机械核验按字面扫」。
- **mech 侧**：`_check_redteam_three_piece` 的置信度要件放宽为
  `置信度|置信\s*\d`（词形取真实被 block 载荷逐字「置信 95%」，v2.49 同范式）；
  「推理链」要件不动（红队三轮均逐字写出）。
- 双向重放：轮 3 被block载荷（置信 95%）→ PASS；vio1 转述冒充载荷（无推理链无置信）
  → 维持 BLOCK。

### 修 3：红队 driver 预派发（用户裁决做）

**架构**：子4 gate 过后红队即具备全部输入（证据=子1-4 最新 trace，
redteam-prompt 机械保证不含子5 结论）。把派发从「子5 段内模型动作」前移为
「driver 段派发动作」，红队运行（3-4min）与子5 主会话工作（①③④ ≈2-3min）重叠。

- **声明**：Step 加字段 `pre_dispatch: str = ""`（u:1 子5 = `"redteam"`）——
  声明式单源，与 interactive/tier 同范式，禁 driver 硬编码步号。
- **driver**（dl_drive.py 工作步分支，drive/run_segment 共用主循环单点）：
  派段前若 `step.pre_dispatch == "redteam"`——
  1. `engine.redteam_prompt()` 取 prompt（None=无子4 trace → 跳过，ingest 侧会指路）；
  2. 新鲜度：meta/redteam_worker.json 记录 `{pid, started_at, prompt_sha1}`——
     sha 相同且（pid 活 或 报告非空）→ 复用不重派；sha 变（state-reset 后子4
     证据变了）→ SIGTERM 旧进程、删旧报告、重派；
  3. spawn：`claude -p --tools Read --permission-mode acceptEdits
     --settings <drive settings> --session-id <新>`，prompt 走 stdin（E2BIG 纪律），
     stdout 重定向 meta/redteam_report.md（文本输出=最终报告），stderr 追加
     cc_sdk.log；start_new_session=True（与段会话同 Ctrl+C 语义）；
     cwd=worktree（证据 file:line 相对指针要 Read 得到；hooks 走 drive settings
     的 drive_mode 降级分支，与段会话同形态）。`--tools Read` 把纪律1
     「Read 为主、其它不要试」从文案变结构（judge --tools "" 同范式）。
- **engine 新子命令** `append-trace --ingest-redteam`（无参）：
  - meta/redteam_worker.json 不存在 → exit 1 指路回退：「本步无 driver 预派发
    （v2 TUI/driver 未起）——回退会话内路径：redteam-prompt → Agent 单发起 →
    --ingest-agent <task-id>」；
  - 阻塞轮询（≤360s，2s 间隔）：完成 = 报告非空 **且** pid 已死（文本输出进程
    退出才写完）；超时 → exit 1「未就绪——继续①③④后重试」；
  - pid 死 + 报告空 → exit 1「预派发无产出，回退会话内路径」；
  - 成功 → 载荷 qa 节末插入收录项，标题「红队输出原文收录（driver 预派发）」
    （含「红队」「原文收录」两关键字=redteam_report_recorded 承诺装置）；
    防重：载荷已有红队收录项标题 → 拒「已收录过」（宁纵勿枉）。
  - 落载荷插入逻辑从 ingest_agent_report 抽出共用 helper（`_insert_report_item`）。
- **mech 闭环**（_check_redteam_report_recorded，签名本就有 project_root/name）：
  无 task-id 信号且无收录项时，若 meta/redteam_worker.json 在位 → 拒「红队已
  预派发未收录——append-trace --ingest-redteam 收录」；worker.json 不在位
  （v2 TUI）→ 维持 None 交 judge（宁纵勿枉）。防「预派发时代模型不交收录项
  直过」的洞（judge 侧 gate 文案被告知形式要件已机械拦截，不能留空档）。
- **文案同步**（改编排三触点，症状 M checklist）：
  - 子5 purpose ② 改写：红队=driver 预派发，主路径 `--ingest-redteam`
    （阻塞收录），回退路径 Agent+`--ingest-agent`；「先内查后收录」顺序不变；
  - 子5 gate 一 的机械拦截括注：补「或 driver 预派发 worker 在位」通道；
  - nodes-index.md 子5 摘要块手工同步。
- **不做**：红队运行时长本身（2.6-4min）不动——对抗复核是质量护栏，
  砍它的输入/思考链是质量风险（step4 设计「不动子代理运行时长」同裁决）；
  v2 TUI（WF_TUI=1）无 driver → 自然走回退路径，行为不变。

## 3. 验证

1. TDD：先写测试——
   - _TASK_ID_RE：三轮误报 id 逐字（49519773767901265/48244678899192833/
     9806949806949807/1194141004217242）不命中；三个真实 id 命中；
     科学计数法小数（1.2345678901234567e-05 的 e 段）不命中；
     _dispatched_vs_unrecorded 双向：float 证据载荷+真收录 → 无 missing；
     真 task-id 无收录 → missing（v2.118 牙齿保真）；
   - three_piece：「置信 95%」收录项 → 过；「置信度：中」→ 过；
     转述冒充（双缺）→ 拒；无收录项 → None；
   - redteam-prompt 模板含「置信度」逐字钉句；
   - ingest-redteam：报告在位+pid 死 → 收录成功标题合规；worker.json 缺 →
     回退指路；pid 死+报告空 → 回退指路；延迟落盘（线程 0.3s 后写）→ 阻塞后成功；
     重复收录 → 拒；
   - redteam_report_recorded 闭环：worker.json 在位+无收录项 → 拒；不在位 → None；
   - driver：pre_dispatch=redteam 步派段前 spawn（mock Popen，断言 cmd 形态/
     stdin prompt/stdout 重定向）；sha 同+报告在 → 不重派；sha 变 → kill+重派；
     非声明步 → 不派；
2. 全量 pytest + ruff；
3. 真实载荷双向重放：轮1/2 被拒 float 证据载荷 → PASS；v2.118 真实缺席载荷
   → 维持 BLOCK（测试内逐字 fixture）；
4. live 验证：在飞 amplitude_annualized 实例（现停子4）续跑到子5——应见
   driver 起红队 worker（redteam_worker.json 落盘）、主会话 `--ingest-redteam`
   一次收录、零 task-id 误报拒、墙钟 ≤4.5min。读数口径 = segment_sessions ts +
   transcript 去重（#17）。

## 4. 不做的事

- 解析器未知【标头】宽容化（用户裁决：报错文案已教恢复路径，宽容风险 > 收益）；
- 红队子代理输入瘦身/关思考链/降档模型（质量护栏，step4 同裁决）；
- 三关质检内容本身下沉机械层（P2-2 审计结论：语义判据在，judge 不跳）；
- v2 TUI（WF_TUI=1）路径任何改动（回滚面，自然走会话内回退路径）；
- 交接包瘦身（=P1-1 独立项，不在本步范围）。

## 5. 实施验证记录（2026-08-17）

- TDD 红→绿 + 全量 1065 tests + ruff 全绿（merge 206dea9）。
- **rt_smoke 真 claude 端到端冒烟**（scratch repo + 真子4 trace）：driver 预派发
  spawn 真实 worker ✓ → 报告完工 ✓ → `--ingest-redteam` 收录 ✓ → `--from-file`
  全量 mech 落库 ✓（float 证据 0.49519773767901265 在场零误报=修1 端到端生效；
  k3 红队逐字标签「verdict: 证据不足」并识破虚构冒烟证据=修2 模板侧+对抗性在线）。
- 冒烟逮住两个生产级缺陷并已修（27aa0b7）：①僵尸 pid——driver 存活期间 worker
  完工成僵尸，kill(pid,0) 仍成功会把 ingest 拖到超时 → pid_alive 读 /proc 判 Z；
  ②ANTHROPIC_LOG stdout 污染 → --output-format json + 末行 result 提取。
- **真实段会话全流程冒烟（第二次 rt_smoke，生产 prompt/settings 形态）**：
  driver 预派发 → 段内模型按新 purpose 直走 `--ingest-redteam` 主路径
  （零 Agent 派发、零回退）→ from-file **零机械拒**一次落库（float 证据在场，
  修1/修2 端到端生效）→ 真实 judge gate pass（22s）→ state 推进子6。
  行为链路（模型遵从新路径）由此闭环。段 29 轮/408s 偏高属冒烟伪影
  （scratch repo 为空，模型 ~15 轮在找 evidence 引用但本不存在的文件；
  生产仓文件都在、证据在交接包内，无此探索循环）。
- **live 验证（2026-08-17 17:42-18:02，在飞 amplitude_annualized 实例真实跑，
  deepseek-v4-flash 与基线同模型同实例）**：预派发日志「⚑ 红队预派发——与本步
  段并行跑」在产线落痕；子5 = **9轮 · 277s(4.6min) · $1.50**，judge 首判即过、
  零机械拒、零 Agent/TaskOutput（预派发完全替代会话内派发+干等）；
  红队 worker 独立会话 11 calls Read×23 真点查。A/B：

  | 指标 | 基线（3轮） | 优化后 | 变化 |
  |---|---|---|---|
  | 墙钟 | 7.2-7.4min | 4.6min | **-37%** |
  | 主会话 calls | 15-19 | 9 | **-47%** |
  | 主会话 cache_read | 4.77-5.18M | 0.62M | **-87%** |
  | 主会话 fresh | 33k(暖)-270k(冷) | 74k | 与暖轮同量级 |
  | 机械拒/返工 | 2次/轮（3/3轮） | 0 | **清零** |

  工具序列=Bash×4/Read×2/Edit×2=理想最小序列。残余观察：①首调 fresh 54.5k
  超 P1-2 50k 告警线（交接包膨胀=P1-1 独立项，不在本设计）；②红队 worker
  经 MCP 调了 1 次 tavily_extract——`--tools Read` 只限内置工具，MCP 工具
  不在其列（未违规但超出「Read 为主」字面，纪律面后续观察）；③同段子4
  51轮/707s/$6.34 高于其基线（fetch 升档补派+单样本方差，归 step4 后续审计）。
