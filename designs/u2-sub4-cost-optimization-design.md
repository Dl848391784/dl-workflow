# understand:2 子4（归一化陈述）耗时/token 优化设计——段内续步（合并段）

> 日期：2026-08-18 · 分支 feat/u2-sub4-cost · 状态：实施中
> 上游：designs/u2-sub3-cost-optimization-design.md（断链 u:2 后 #4 冷启动 44.6k 成为新大头）
>      references/cost-optimization.md #20（首调桶杠杆判据）/ #9（provider 缓存语义不外推）/ #18（种子漂移混淆）
>      memory deepseek-stream-cache-session-scoped：「fresh 杠杆只剩交接包瘦身+段合并」
> 触发 = 用户指令（2026-08-18）：「优化 understand:2 的 step4，耗时和 token 消耗要大幅降低；
> 跑测试工作流用 ac-deepseek1；amplitude 今日值 4920.2%」（承 u:2 子1/子2/子3 优化之后）。
> 方案裁决 = 用户 AskUserQuestion 选定「段内续步」（三选项：段内续步 #2→#3→#4 / 仅并 #3→#4 / 保守小修不并段）。

## 1. 基线实测（u2_sub3_ab 真实数据，ac-deepseek1/deepseek-v4-flash，断链后现状）

u:2#4 = 归一化陈述（define-problem skill，搬运型步：子3 论证后目标集 → statements
三字段载荷），断链后是独立 fresh 段。

逐调用拆解（usage 去重 keep-max，同 id 内容块合并）：

| 步 | 调用 | 首调 fresh | fresh 总计 | cr | out | 墙钟 |
|---|---|---|---|---|---|---|
| u:2#3 | 25 | 40,576 | 86,708 | 1,890,048 | 23,766 | ~198s |
| u:2#4 | 10 | **44,592** | 54,790 | 507,520 | 18,923 | ~83s |

#4 逐调用：#1 冷启动 44,592（=本步 fresh **81%**，动作仅 Skill(define-problem) 调用）；
#2 +7,655（skill 内容回灌）；#3-#10 scaffold/落库往返 ~2.5k（含 Write 撞 S14 围栏
改 Edit 的既有褶皱 ~4 调，非本设计作用面）。

段 prompt 组成（14,960 字符）：交接包 ~11.7k（本节点 #1/#2/#3 留痕全文 10,286 +
PC 摘要 1,358）+ 当前任务 1,986 + 附带交付（NEXT_PREP u:3#1）1,150。
**交接包本体仅 ~5k tok**——冷启动 44.6k 的地板 = harness ~22.5k + node-rules 1.2k +
包 + step prompt（P1-1 水位实测恒定 ~40-45k，不随内容瘦身显著下降）。

**机制探针（/tmp/mt_probe，ac-deepseek1 凭证链，探针纪律 cwd=/tmp 无 workflow
settings）**：`claude -p --input-format stream-json` 同进程多轮——turn1 fresh=3,837/
cr=0/8.3s；turn2（stdin 续发用户消息）**fresh=95 / cr=4,480 暖 / 1.4s**，会话记忆
正确（答出 turn1 约定的数字）。deepseek 会话隔离缓存 = 跨进程必冷、**进程内暖**，
探针坐实唯一大杠杆 = 消灭段边界。

## 2. 根因

**#4 的 token 大头是「每步一个 claude 进程」的段边界税（冷启动地板 44.6k），
不是交接包内容、不是取证探索、不是 skill 开销。**

- 交接包瘦身天花板 ~5%（包仅 ~5k tok），达不到「大幅」；pack_self_contained 对
  #4 无的放矢（基线零 evidence 保险性重读——#3 留痕全文已在包内）。
- u:2#3 断链（u2-sub3-cost）消灭的是跨进程 --resume 的**单调涨继承重写**；
  断链后每段仍各付一次恒定地板——#3 40.6k + #4 44.6k = 每轮 u:2 运行纯边界税 ~85k。
- #4 步体极小（4 条 statements，out ~1k 有效载荷）：overhead:work ≈ 50:1。
- 缓存经济学（#9）：deepseek 流式缓存会话隔离，跨进程暖不起来已被两轮实测钉死
  （#3/#4 段首调 cr=0）；进程内暖（基线 #4 段内 #2 调起 cr>0 + 本探针 turn2 实证）。
  所以正确方向不是「让跨进程变暖」（不可能）而是「不跨进程」（段内续步）。

## 3. 方案（段内续步：同进程多轮 stream-json，白名单节点）

**核心：白名单节点的连续非交互子步骤在同一个 claude -p 进程内续跑——
driver 用 `--input-format stream-json` 保持 stdin 常开，每步 gate 过后把下一步的
任务 prompt 作为新的用户消息注入同一会话（暖缓存），替代每步新进程（冷启动）。**

### 3.1 机制件

1. `dl_flow_engine.py`：`MERGED_RUN_NODES = frozenset({"understand:2"})` 单源常量
   （白名单 = 回滚面，与 SEGMENT_CHAIN_NODES 同范式；注释钉 provider 缓存语义依据
   + 本设计指针）。
2. `scripts/workflow/dl_drive.py`：
   - 新 `MergedSession` 类：Popen `--input-format stream-json`（其余旗标与
     run_session 相同：acceptEdits / --settings / --append-system-prompt-file /
     NO_MCP / --session-id[兼容性冒烟不过则改从 init 事件捕获 sid]）；
     `send(prompt)`（NDJSON user 消息）/ `read_turn()`（读到 result 事件为止，
     返回本 turn 文本+事件流照落 drive-stream.jsonl）/ `close()`（关 stdin 收尸）。
   - `_run_boundary_loop` headless-step 分支：`node_id in MERGED_RUN_NODES` 且
     本步非交互 → merged 路径（循环）：
     - run head：发全量 prompt（交接包+当前任务，build_step_prompt 现状）；
     - turn 结束 → NEED_USER 逐 turn 嗅探（命中 → close + 走既有 on_need_user
       TUI fallback）→ `engine.gate_sub_step_at_stop`（判据/judge/机械门零变更）：
       - **advanced**：下一步在同节点且非交互 → 发**续步 prompt**（见 3.2）续跑；
         否则（撞交互步/节点末步/白名单外）close，回主循环（state 已推进，
         下一段照旧派发）；
       - **block**：续步 prompt 携带返工判词**会话内暖返工**（不再重付冷启动）；
       - **escalate**：close + 既有断点裁决；
       - **none**（无新 trace）：会话内 nudge 重发 ≤ NONE_RETRY_LIMIT，仍无 →
         close + 既有断点；
     - ctx 护栏：逐 turn 跟踪 last_ctx，破 250k（链峰值同阈值）→ warn 落日志 +
       本步 gate 过后收段（下一步 cold start，优雅降级）；
     - 进程死/rc 非 0：state 在磁盘（最后过门步），主循环下轮从当前步新起段
       = 今日每步独立段的崩溃语义，不新增风险面。
   - `_record_segment` note 标 merged 覆盖区间（如 `merged understand:2#2-#4`）；
     `_fresh_warn_line` 首调读数照报（run head）。
   - SEGMENT_CHAIN_NODES 不动；merged 路径不走 `_chain_resume_sid/_chain_update`
     （u:2 已断链，两机制互斥不交织）。
3. `build_step_prompt(..., continuation: bool = False)`：续步变体——剥交接包
   （会话内已有真迹，包冗余），头部一行「进入子步骤 N/{total}（同会话续步——
   前序各步产物在你上下文中，交接包省略）」+ 当前任务段（purpose/deliverable/
   铁律照原样）+ 附带交付（NEXT_PREP 逐步 lookahead 照旧——只有 run 内最后
   一个非交互步的 lookahead 会命中交互目标，语义与今日「prep 骑最后一个 headless
   段」一致：今日 #3 段无附带交付、#4 段有，merged 下同为 #4 轮携带）。

### 3.2 显式不做

- 不动 u:1/u:3/u:4/plan 族（白名单只放 understand:2——用户指令范围；泛化留给
  各自立项，按 #20 判据逐节点审）。
- 不动 judge 判据/gate 机制/交接包内容/run head 段组成（牙齿零变更）。
- 不动 hooks（drive_mode 降级面不变；fence S11/S14 段内照跑；workflow_phase
  注入逐 turn 触发与否由 live A/B 观察记录，不作承重墙）。
- 不做跨节点合并（#5 交互步天然收段；u:3#1 新节点新段——交接包通道仍需）。
- 不做 ctx 超限自动压缩（250k 护栏只收段不压缩——压缩是另一个机制族）。
- 不删 SEGMENT_CHAIN_NODES 机制（他节点在用；merged 是并行通道非替代）。

## 4. 预期收益（每轮 u:2 运行，deepseek 口径）

| 指标 | 基线（断链后） | 预期（段内续步） | 机制 |
|---|---|---|---|
| u:2#4 首调 fresh | 44,592 | **0（无首调）**——续步 prompt ~1-2k 增量 | 段边界消灭 |
| u:2#4 fresh 总计 | 54,790 | ~12k（**-78%**）：续步 prompt 1.5k + skill 7.7k + 落库往返 2.5k | 同上 |
| u:2#3 fresh 总计（全轮，run 非首段） | 86,708（含冷启 40.6k） | ~48k（冷启消灭，步体不变） | #2 暖续 |
| u:2 节点 fresh 合计（全轮 #2-#4） | ~180k | ~90-100k（**-45~50%**） | 三次冷启→一次 |
| u:2#4 墙钟 | ~83s | ~45-55s（**-35~45%**） | 灭 44.6k 冷写 prefill |
| u:2#3/#4 cr | 1.89M/0.51M | **+30~50%**（预登记：累积上下文逐调重读，0.1× 价格轴） | 会话驻留 |
| 返工轮成本 | block = 新冷段 44.6k | 会话内暖返工 ~2k | 护栏红利（基线零 block，不计收益） |

护栏：逐子步骤门控零变更（gate_sub_step_at_stop 逐 turn 照跑，block/escalate/none
语义全保留）；judge 输入同源（read_evidence_for_step 读 evidence 不读 transcript，
与段边界无关）；trace 内容质量由同一组 gate 把关；白名单外节点零行为变化；
WF_TUI=1（v2）无段概念不动；front/drive 共用 boundary loop 单点生效。

## 5. 影响面

- `dl_flow_engine.py`：+MERGED_RUN_NODES 常量（~5 行）
- `scripts/workflow/dl_drive.py`：MergedSession 类 + merged 循环 +
  build_step_prompt continuation 参数（~150 行）
- `tests/test_dl_drive.py`：merged 路径单测（monkeypatch MergedSession 层，
  与 run_session stub 同范式）：advanced 续步 / block 暖返工 / escalate 收段 /
  none nudge / 撞交互步收段 / 白名单外不走 merged / NEED_USER fallback
- hooks 零变更；三模式 drive/front 共用点生效、WF_TUI=1 不动
- 在飞工作流：无 state schema 变更；白名单外零变化；在飞 u:2 实例下次推进
  自然走新路径（state 只记位置不记段形态）

## 6. 验证计划

1. TDD 红→绿 + 全量 pytest + ruff。
2. 生产形态冒烟：--session-id × --input-format stream-json 兼容性（不兼容则
   sid 改从 init 事件捕获——两态都在测试覆盖内）。
3. **live A/B（dl @ac-deepseek1，新实例 u2_sub4_ab）**：种子 = u2_sub3_ab evidence
   裁剪至 u:2#2（五件套：裁 evidence/裁 last_judged_trace/清段记录与 stash/
   settings name-agnostic 验证/起跑前 handoff_pack 冒烟），从 u:2#3 起跑
   （#3=run head 冷启动保留、#4=续步——必须含 #3 才验得到续步路径），
   跑到 u:2#5/u:3#1 needuser 自动收。验收点：
   - **机制生效直接证据**：#3/#4 同一 sid（对照 u2_sub3_ab 各段独立 sid）+
     drive-stream 单进程多 result 事件 + #4 首调 cr>0（暖）；
   - #4 逐调用 fresh 与 §4 预期对比（#22 逐调用口径）；
   - 零 block（node_attempts=0）、judge 全 pass、trace 质量目测不降；
   - #3 基线实测数字与今日值 4920.2% 口径核对（annual≈0.492）；
   - NEXT_PREP 附带交付在 #4 轮照常落 stash（need_user.json 就位）。
4. AC_WORKFLOW_LAUNCHER 指向本 worktree 的 dl-launch.sh（worktree A/B 驱动
   两前提：launcher 与 engine 同树解析；凭证不进命令文本，bashrc 函数体提取 env）。
5. **混淆声明预登记**（#18）：#3 测量探索轮数方差（三轮 11/18/25 调）= 步体
   天然方差（#40）；种子快照若再漂移驱动 #3 增量探索，#3 剔出对比面——
   验收口径 = **#4 逐调用 fresh + #4 墙钟**（#4 步体=纯搬运，方差远小于 #3）。

## 7. 实施验证记录（实施后回填）
