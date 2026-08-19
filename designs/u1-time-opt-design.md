# u:1 耗时优化设计（interaction run 审计落地）

> 2026-08-19。来源：interaction_amplitude__ret3d_pos_annualized understand 阶段
> 全量运行审计（79.4min 墙钟/零 block/22 子步骤一次通过率 100%）。
> 审计结论：u:1 一个节点占全程 49%（35.7/73min 除用户等待），优化只投 u:1。

## 1. 审计证据（逐定下钻，全部经 transcript 合并同 id 内容块后核验）

基线读数（message.id 去重口径；成本=harness 价卡）：

| 步 | 轮数 | 墙钟 | output | cache_read | 成本 |
|---|---|---|---|---|---|
| u1#2 内查规划 | 16 | 208s | 21.5k | 0.55M | $1.13 |
| u1#3 因果链挖掘 | 57 | 484s | 52.6k | 4.68M | $4.16 |
| u1#4 双向取证 | 25 | 451s | 35.1k | 1.18M | $1.73(+2 agent $3.19) |
| u1#5 质检裁决 | 56 | 652s | 65.3k | 4.35M | $4.39 |
| u1#6 归一化陈述 | 29 | 339s | 40.1k | 1.64M | $2.26 |

## 2. 三处疑似点的下钻结论（两处证伪不立，一处坐实）

### 2.1 u1#3（57 轮）——机械层正常履职，不立优化项（不做）

2 次写侧机械拦截：因果链环含「若…则（若为 default 则…）」「需确认」，
被 causal_ring_no_untested 词表当场拒（v2.49 词形已双侧钉死：
_CCAUSAL_CHAIN_EVIDENCE_RULE 明文列「需…验证类待办桥接/若…则假设形态」
会机械拒）。模型降格进竞争假设分支后重提成功，返工 ~2.5min、零 judge 轮。
**purpose 侧预防文案已存在且逐字命中，模型仍犯 = 文案边际收益为零，
机械层就是设计内的兜底**（文案失效→机制堵入口原则的正面实例）。
结案方式 = 归因登记，不加文案（runtime-audit #11②/#19 同族）。

### 2.2 u1#4（25 轮）——执行序已遵守，等待=floor，不立优化项（不做）

初判「串行等子代理 3-5min」被时间线下钻**证伪**：18:58:59（步始 +69s）
即并行派发 2 个 light 档取证 agent（先派发后内查 ✓），随后 ③内查
（codegraph status/grep/git log ~90s），19:03:35-38 两个 agent 报告
跨步归位 ingest ✓。唯一真空转 = 一次 `sleep 60` + agent 收尾窗口
（agent 墙钟 244-252s 是最长杆，步墙钟 451s 逼近 floor）。
**无结构性可压空间**，sleep-60 频次=1 不立文案项。

### 2.3 u1#6（29 轮）——格式猎捕坐实，立修 B

append-trace 首次提交被拒（条目传导缺 factor[D]，报错文案**已明确指路**
「逐条补或显式标注剔除理由」），模型没有照文案修，反而：
- evidence 元探查 ~10 调用（ls/cat/find/wc .claude 目录，19:19:20-19:19:53）；
- **Read/grep ~/.dl-workflow/dl_flow_engine.py 引擎源码**反推 _step_trace_ids
  校验实现（19:21:06-19:21:38）；
- `append-trace --help` 翻用法。
19:18:44 被拒 → 19:22:13 才重提成功，~3.5min 中 ~2.3min 是猎捕。
u:3#4（首例）/u:4#4（第二例）已验证的 L4 格式真源钉死条款**未平移到 u:1#6**
——本步有条目传导机械核对（factor[X]），用 u:3#4 同文（含「编号传导」）。

### 2.4 红队 worker「不可复核」声明——路径提示缺口，立修 A

worker 报告两处声明「backtest/result/*.json 与 factor_ic_data.parquet
在本 worktree 不存在，无法独立复核」——这些生成文件在**主仓库**就在
（u1#3 内查 find 实证）。worker cwd=实例 worktree（干净检出），
证据里的相对路径（data_fetchers/result/...）在 worktree 解析不到即放弃，
把数值复核负担结构性推给 u1#5 主段（u1#5 随后 13 次 python 探针里
~2min 在补做这批复核——含第一次探针也先撞 worktree 路径再自我纠正）。
worker 有 Read，Read 主仓库绝对路径即可复核 JSON 类结果文件。
修 = redteam_prompt() 注入主仓库根路径提示（project_root 函数内在场）。

## 3. 修改项

### 修 A：redteam_prompt 加主仓库路径提示（dl_flow_engine.py）

纪律 1 后补路径条款（要点：cwd=worktree 干净检出；相对路径 Read 不到时
拼主仓库根 {project_root} 重试；生成数据/结果文件只在主树）。
预期：worker 报告「不可复核」缺口减少（JSON 类可复核），u1#5 复核考古
省 ~1-2min；报告 verdict 质量提升（原子 C/D 类数据 claim 可闭环）。

### 修 B：L4 格式真源钉死条款平移 u:1#6（dl_flow_nodes.py，平移第三例）

purpose 末加（u:3#4 同文，本步有条目传导故保留「编号传导」）：
「载荷格式与编号传导的唯一真源 = --scaffold 骨架 + append-trace 报错文案
（四桶分工：格式归脚本）——禁读引擎/测试源码反推校验实现；
被拒按报错文案逐字修即可。」
selfcheck 末加（u:4#4 同文）：「格式照 scaffold 骨架填了吗——没去翻
引擎/测试源码反推校验实现吧（被拒按报错文案修）？」
预期：被拒后跳过元探查/源码反推直接按文案修，省 ~2min。

## 4. 不做的事（登记关闭项，防重复提案）

- **worker 放权 Bash/python（数据探针）**：parquet 统计类复核 worker
  Read 做不了。评估结论不做——纪律 3「点查非系统性重新取证」与
  --tools Read 结构保证同向（2026-08-17 刻意决策）；放权=邀请范围蠕变，
  数据统计复核的归口本来就是有 Bash 的子5 主段。本轮数据（u1#5 补复核
  ~2min）不构成推翻该决策的量级。
- **u1#3 词形预防文案**：双侧钉死已就位（§2.1），机械层履职是设计内。
- **u1#4 等待压缩**：执行序钉死且被遵守（§2.2），等待=agent 墙钟 floor。
- **u1#5 载荷两次大写入**（10k+5.6k out）：首次写在红队收录前=等 ingest
  期间的合理并行草稿，非浪费。
- **MERGED 扩 u:3/u:4**：属 P2 节点级（非 u:1），另行登记（u:4 段链
  链税遗留项已存在），本设计不收。

## 5. 验证方案

1. pytest 全量（同步测试 pinning purpose/prompt 内容的随改）。
2. 种子 A/B（runtime-audit #25 五件套）：从 interaction 实例裁 evidence
   到 u:1 子3 止（保留 sub_step ≤3 trace），清 segment_sessions/chain/
   stash/last_judged_trace，新实例名 u1_timeopt_ab，drive 直跑 worktree
   代码（#24：AC_WORKFLOW_LAUNCHER 路径/dl_drive.py 直调），跑子4-6
   （子7 交互步撞 NEED_USER 自然收段）。
3. 验收口径（预登记）：
   - 修 A：红队报告不再对主树在场的 JSON 类结果文件声明「不可复核」
     （grep 报告「不存在/无法复核」指向主树文件的条数 = 0）；
   - 修 B：u1#6 段 transcript 零引擎/测试源码 Read（grep dl_flow_engine
     /test_ 路径 = 0），append-trace 被拒后无元探查迂回；
   - 总账：u1#4-6 墙钟 1442s → 目标 ≤1250s（方差带内，单轮指示性
     非结论性，#22 纪律）。

## 6. 验证结果（2026-08-19 晚，u1_timeopt_ab 种子 A/B 一轮收官）

驱动方式：dl_drive.py --segment 直跑 worktree 码（deepseek-v4-flash 同
provider），子4→6 三段 + 子7 确认级机械通过，全程零 block、7/7 trace
一次通过率 100%。

| 步 | 轮数 基线→B | 墙钟 基线→B | cr 基线→B |
|---|---|---|---|
| u1#4 | 25→27 | 451s→462s | 1.18M→1.31M |
| u1#5 | 56→**8** | 652s→**254s** | 4.35M→**0.20M** |
| u1#6 | 29→**6** | 339s→**93s** | 1.64M→**0.15M** |
| 合计 | 110→41 | **1442s→809s（-44%）** | 7.17M→1.66M |

- **修 A 验收 ✓**：worker prompt 含路径提示（transcript 首条 user 消息
  逐字验真）；报告经主树路径复核了 default JSON（「default JSON 证实了
  …实测」）；残留两条「不可复核」=parquet 二进制（设计内不做项 §4）+
  一条证据指针纠错（backtest/layered_backtest_runner.py 真实路径在
  common/ 下——红队 bonus 发现，非误声明）。
- **修 B 验收 ✓**：u1#6 仅 6 轮（Skill→scaffold→Read 骨架→Edit→
  from-file→收束 = 理论下限），零引擎源码翻找、零元探查、
  首次提交即过（2 Bash = scaffold+from-file，无拒收重试）。
- u1#4 持平（27/462s vs 25/451s）——符合 §2.2「等待=floor 不立优化项」
  的判定（本轮同样先派发后内查、2 个 light/full 取证 agent 并行）。
- 混淆声明：单轮 A/B（#22 方差纪律），但 u1#5/#6 的机制读数触底
  （轮数=理论下限、零拒收、零猎捕）说明杠杆生效非运气；u1#5 的降幅
  含「红队报告已带 file:line 复核 → 裁决步不再考古」的修A 兑现成分，
  与预登记归因一致。
- 双执行体协作注记：本会话审计/设计/修A/提交（7a6566b+3918ee8），
  并行会话补 pin 测试 ×2（14df208，1146 tests）、种子构建与 driver
  运行；22:04 双 driver 撞车已处置（停本会话侧，无孤儿段、证据无损）。
