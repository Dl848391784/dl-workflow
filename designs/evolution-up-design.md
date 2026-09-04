# evolution-up：dl-workflow + dashboard 大胆进化包（u→p 环节限定）

> 2026-09-03 立项。用户裁决：「大胆进化，把能想象到的都纳入进来，只到 p 环节，p 以后不做，可用 ac-deepseek1 做测试」。
> 范围铁律：本包**不触碰 execute/review/evolution 行为**——所有改动落在控制面（dashboard/driver 段派发）与 understand/plan 阶段的证据/注入面。

## 0. 设计原则继承

- 四桶分工：主模型定「写什么」/ 脚本定「怎么写」/ judge 定「过不过」/ 用户定「认不认」。本包六项全是脚本/机械层工作，judge 判据零变更（免 n≥6 三向重放义务）。
- 宁纵勿枉：数据缺失/损坏一律降级放行或如实缺席，不伪造（no silent fallback）。
- 单源：可见步集/静默集/产物解析一律取既有单源函数，消费方禁自猜。
- 弱模型优先：新注入面文案 = 建议，关键语义要么机械保证要么明确标注「参考非证据」。

## 1. P0：dashboard server SIGTERM 不死修复

**实爆史**：2026-09-02 两次 kill SIGTERM 不死、需 kill -9（记忆 workflow-system v0.3.0/v0.4.0 条目）。

**根因假说（高置信）**：`app.py /api/events` 的 SSE 生成器 `while True: ... await asyncio.sleep(2)` 永不退出。uvicorn 收到 SIGTERM 进入优雅退出，等待所有连接关闭；只要有一个浏览器标签页开着 SSE 长连接，等待 = 无限。

**修法**：
1. `uvicorn.run(..., timeout_graceful_shutdown=3)`——优雅退出 3 秒兜底强制关闭；
2. SSE 生成器感知断连：传入 Request，循环内 `await request.is_disconnected()` 即返回（顺带治「最后一个客户端关页后 server 仍每 2s 全量扫描」的空转税）。

**验证**：真冒烟——起 server（子进程）+ 挂着的 SSE 客户端，发 SIGTERM，断言进程 5 秒内退出。防回归测试钉 timeout 参数在场。

## 2. P1：实例自动审计页（每轮运行的例行体检）

**动机**：现行审计（tail_volume 系列）是手工专题调研，但原料全在盘上（state.segment_sessions / segment_stats.jsonl / evidence jsonl 的 kind=gate 裁决行）。让每次运行完结即得审计页 = runtime-audit 从「专题」变「例行」。

**新模块** `dl_dashboard/audit.py`（纯读侧）：
- `gate_outcomes(project, name)`：扫 evidence jsonl 的 kind=gate 行 → 按 (node, sub_step) 聚合 {passed, blocked, 一次通过（该步首个判决即 pass）}；一次通过率 = 一次通过步数 / 有判决步数。kind=rubric-dispute 行单列。
- `node_costs(project, name)`：复用 `metrics.collect_stats` 按 node 聚合 {段数/墙钟/轮数/fresh/cache_read/成本}。
- `audit_report(project, name)` = 两者 + state 元信息（轨道/创建时间/当前位置）装配 dict。
- 缓存：按 (evidence mtime, segment_stats mtime, state mtime) 键控内存/磁盘缓存，防每次请求全量重扫（沿用 metrics legacy 缓存姿势）。

**展示**：detail 页新增「审计」折叠区（路由 `GET /api/audit`）——一次通过率/block 分布表/节点成本表/dispute 列表。不新增整页（H9 行数约束 + 信息归位）。

## 3. P2：系统健康页（跨实例改进队列数据化）

**动机**：改进路线图目前靠偶发审计碰运气；「哪个 gate 真实运行中最常 thrash」应该由全部历史实例的裁决数据自动回答。

**新模块** `dl_dashboard/health.py`：
- `health_report(projects)`：跨实例聚合 audit.gate_outcomes + node_costs——
  - gate 榜：(node#step) × {判决数 n, block 数, block 率}，按 block 数降序（n≥2 才上榜，单样本噪声不上榜——cost-opt #43 教训）；
  - 节点成本榜：node × {实例数, p50/p90 成本, p50/p90 墙钟}；
  - dispute 榜：(node#step) × 申诉次数（判据缺陷信号，v2.30 通道的真值出口）。
- 新页面 `/health`（静态页 + `GET /api/health`）：三榜直出，榜首即下一个 framing/mech 下沉候选。

**边界**：只读聚合，实例坏数据隔离（单实例 try/except 标 error，scanner 同姿势）。

## 4. P3：tacet 中途升级机制（单节点静默 → 全量）

**动机**（force-tacet-run1-audit 已列下一步）：tacet 轨道沉默 38 步，下游暴露欠账信号时（stale fixture 漏网类——「欠账非返工」但需补救路径）当前唯一出口是重建实例。升级规程对齐 fermate off + state-reset 形态。

**机制**：
1. state 新字段 `tacet_upgraded: list[str]`（步 id，如 `understand:1#2`）——per-instance sticky，模型无权自写（只经 engine CLI）。
2. `step_tacet_forced` 判定时从静默集剔除 upgraded（单源，driver/hook/statusline/scanner 全链路自动跟随——可见步集 = silent − upgraded）。
3. engine CLI：`python3 dl_flow_engine.py upgrade <name> <step-id>`——校验 ①实例 force_tacet 在轨 ②step-id 在当前静默集内（不在 = 无需升级，如实说）③追加 + 指引「`/dl state-reset <node>:<step>` 重跑该步」。重复升级幂等。
4. handoff_pack tacet 告知段补「已升级步清单」（材料薄声明不覆盖它们）；scanner `WorkflowInfo` 透传 tacet_upgraded（dashboard 时间轴自动把这些步渲为可见——_silent_steps 单源改造）。

**不做**：自动触发升级（阈值用真实分布标定是下一版的事，本次只给人工/模型申请通道）；跨节点批量升级（用 state-reset 既有能力组合即可）。

**修订行（2026-09-04，commit 7b7bc1e）**：tacet×MERGED 交互面——升级步落在 MERGED_RUN_NODES 节点时，合并段续步循环原无逐步 tacet 判定，会横扫真跑后续仍静默步（真机 ann_pct_live_evoup 的 u:2#3/#4 实证被横扫；升级前不可达——MERGED 节点在 tacet 下全静默进不了合并段，P3 首次开通该路径）。修=`_run_merged_run` 的 can_continue 加 `step_tacet_forced` 判定，命中即收段交还主循环静默跳步。「新开通路径必 pinning」再次兑现。

## 5. P4：相似实例检索注入 understand（跨实例知识层 v1）

**动机**：2026-09-02「同 bug class 两实例改动面 10/10 一致」是手工对照——实例间的知识复用应为系统行为。evolution 经验当前写完即躺平。

**机制**（零 LLM 零嵌入，纯机械）：
1. `dl_flow_handoff.py` 新增 `similar_instances(project_root, name, limit=3)`：
   - 候选池 = 全部登记项目的 `.claude/workflows/*/state.json`（项目清单读 `~/.dl-workflow/dashboard.toml`，读不到 = 仅本项目，宁纵勿枉）；
   - 排除自身/无 problem_statement 的实例；
   - 相似度 = 问题陈述的 CJK/词 mixed bigram Jaccard（分词器 ~20 行，无依赖）；
   - top-K 各取：实例名/项目/相似度/根因行（evidence 中 `根因@` 行，u/p 改动规格五要素门落地的稳定格式，截断 200 字符）/ 到达位置（node）。
2. 注入点：`handoff_pack` 在 `problem_statement` 存在且 phase==understand 时追加「### 相似历史实例（机械检索，参考非证据）」节——
   - 文案钉死：**「以下根因可作竞争假设候选，须本仓取证验证后才可进主链」**（对齐 _CAUSAL_CHAIN_EVIDENCE_RULE——主链须实际证据指针，检索结果天然只是假设源）；
   - 体积护栏：整节 ≤1200 字符，零命中 = 节缺席（宁纵勿枉不注水）。

**不做**：向 gate 判据披露（judge 判材不变，零重放义务）；execute/review 阶段注入（范围外）。

## 6. P5：插话通道（steer.jsonl → 段边界注入）

**动机**：2026-08-09 挂起的「输入框问题」——段在跑十几分钟，用户想补一句约束无处说。dashboard 无 TUI 的 IPC 硬约束，Web 表单 + 段边界注入即可解。

**机制**：
1. dashboard detail 页常驻输入框 → `POST /api/steer` → append `<meta>/steer.jsonl`（{ts, text, consumed:false}，S14 同款只经脚本写）。
2. driver `build_step_prompt` 起跑新段时读未消费 steer 行，标记 consumed，注入段 prompt 尾：「## 用户插话（转向指令，优先级高于当前步既有指引，但不豁免门控/落库纪律）」。
3. TUI 交互段同样走 prompt tail（v1 不做运行中段打断——打断=杀段重派，代价大，留 v2）。
4. dashboard 显示 steer 行状态（待消费/已消费于何段）。

**防滥用**：steer 只进 prompt 文案 = 建议通道；它不绕过任何机械门（门控读磁盘 state 天然免疫）。

## 7. 验证矩阵

| 项 | 单测 | 真机 |
|---|---|---|
| P0 | timeout 参数 pin + 断连检测单测 | 起 server+SSE 客户端 SIGTERM 5s 内退 |
| P1 | fixture evidence/segment_stats 装配断言 | dashboard 真实实例页面比对 |
| P2 | fixture 多实例聚合断言 | /health 页真实数据目测 |
| P3 | upgrade CLI 五态（在轨/不在轨/幂等/坏 id/剔除生效） | dlt 实例升级到指定步重跑 |
| P4 | bigram 相似度/零命中缺席/体积护栏 | 真实多实例检索质量目测 |
| P5 | steer 追加/消费/注入段 prompt | dashboard 提交插话 → 段日志见注入 |
| 全部 | pytest 全绿（基线 1430） | ac-deepseek1 实例跑 u→p 全程 |

## 8. 实施顺序与 commit 批

P0（小、独立）→ P3（engine 有界）→ P4（handoff+新检索）→ P1 → P2（dashboard 读侧）→ P5（driver+dashboard）。
每项独立 commit（frequent small commits），merge --no-ff 收口。

## 9. 遗留（本包不做，登记）

- 自动触发升级阈值标定（攒样本后）——**2026-09-04 用户确认：先不做最好**（现状 n=1 样本，阈值无分布支撑=拍脑袋；手动 /dl upgrade 通道够用）；
- 运行中段打断式插话（杀段重派）；
- 零模型步 LLM_FREE 实验标记（等健康页数据挑试点）；
- 裁决 inbox 跨实例聚合视图（health 页落地后看形态）；
- 逐节点 provider 路由（双轴数据已有，需 driver spawn env 逐段覆盖，独立立项）。
