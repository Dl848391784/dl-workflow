# understand:2 残余成本优化设计——段前缀外科剥离（项目上下文 + 工具白名单）

> 日期：2026-08-18 · 分支 feat/u2-residual-cost · 状态：已收口（live A/B 足额达标）
> 上游：designs/u2-sub5-cost-optimization-design.md（子5 证伪式结案）§4 残余三项
>      references/cost-optimization.md #20（首调桶）/ #21（段内续步）/ #13（逐调用口径）
> 触发 = 用户指令（2026-08-18）：「u:2 残余优化项也优化好吧」——残余三项 =
> #2 run-head 冷启动地板 ~40.5k / #3 测量步体方差 / #1 交互问答轮。

## 1. 地板分解（生产旗标组合探针，2026-08-18，ac-deepseek1/deepseek-v4-flash，2.1.234）

逐探针实证（cwd=u2_sub4_ab worktree，prompt 走 stdin，usage=modelUsage 真值）：

| 探针 | 配置 | 首调 fresh |
|---|---|---|
| A | 空目录裸 harness | 22,333 |
| B | worktree cwd 默认加载 | 34,046（**项目上下文 +11.7k**） |
| E | B + `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` + `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` | 22,185（**-11.9k**） |
| H | E + `--tools` 10 工具白名单 | 7,918（**再 -14.3k**） |
| I0 | E + `--tools "Bash,Read,Edit,Skill"` | 4,812 |

**「harness ~22.5k 恒定地板」（u2-sub4 设计 §1）再分解**：其中 ~14.3k 是工具
schema（白名单可裁），~8k 是内置系统提示+skills 清单等不可裁部分；而此前被
并入「地板」的项目上下文 11.9k（CLAUDE.md 7.5KB + 项目 skills + git status 等）
两个官方 env 开关即可剥离。**地板不是 40.5k，是 ~4.8k。**

生产首调投影：4.8k 前缀 + node-rules ~1k + 段 prompt ~6.5k ≈ **12k vs 今日
40,576 = -70%**；且前缀缩小对 merged 段**逐调用** cr 各减 ~26k（0.1× 价格轴）。

## 2. 兼容性探针（全过）

- 探针 E/F：DISABLE 对下 **hook 照常触发**（PreToolUse 探针 hook_fired）——
  S11/S14 围栏、advance、phase 注入全部不受影响（对照：CLAUDE_CODE_SIMPLE=1
  fresh=1,452 但 hooks 全灭，弃用）；
- 探针 G：DISABLE 对下 **Skill(define-problem) 可加载**（u:2#4 依赖）；
- 探针 H2：白名单 `Bash,Read,Edit,Skill` 下 Skill 调用 ✓ / Bash ✓ + hook ✓ /
  Edit 可用（未先 Read 被拒 = 既有 read-before-write 纪律，非白名单问题）；
- 探针 I'：数值法（有无 rules 文件 fresh 差 +40 tok ≈ 文件 105B 中文）证
  `--append-system-prompt-file` 在全组合下照常拼接。

## 3. 方案（Node 声明式字段 + spawn 覆盖单源）

1. `dl_flow_nodes.py` Node 加两字段（pre_dispatch/pack_self_contained 同范式，
   声明式单源禁硬编码）：
   - `segment_strip_project_context: bool = False`——True 时段 spawn env 加
     `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` + `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`；
   - `segment_tools: tuple[str, ...] | None = None`——非 None 时段 spawn 加
     `--tools "逗号单串"`（单 argv 元素，无变长参数吞 prompt 风险）。
   understand:2 置位：strip=True、tools=("Bash","Read","Edit","Skill")。
   u:2 逐步工具需求核对：#1 prep=Read/Bash；#2 矩阵推理=纯文本+append-trace(Bash)；
   #3 基线测量=Bash(+Read 指针)；#4 归一化=Skill(define-problem)+Edit 骨架+Bash
   落库。Write 不进白名单——载荷走 --scaffold+Edit，模型本就零合法 Write
   （附带收益：灭 u2-sub4 基线「Write 撞 S14 改 Edit」~4 调褶皱）。
2. `dl_flow_engine.py`：`segment_spawn_overrides(node) -> dict` 单源
   （{"env": {...}, "tools": tuple|None}）。
3. `dl_drive.py`：`run_session` 与 `MergedSession.__init__` 加
   `spawn_env/tools` 可选参数（Popen env={**os.environ, **spawn_env}；
   cmd 拼 --tools）；3 个段调用点（prep / headless-step+续链兜底 / merged）
   按 node 取覆盖。**无编排整阶段会话（execute 等）不动**；judge 不动
   （已 --tools "" 裁剪）；TUI 常驻会话不动（用户面向，需全量上下文）。

### 3.1 显式不做

- 不动其他节点（u:1#4 需 Agent 派取证子代理、execute 需全工具集——各自立项
  逐节点核对工具需求后才可置位；白名单即回滚面，字段翻转即回滚）。
- 不动 TUI 会话/常驻 front 会话的前缀。
- #3 测量步体轮数方差 = 天然方差（runtime-audit #40：同一步三轮 11/18/25 调），
  不立机制项——本设计不碰步体。
- #1 交互问答轮 = decision 级用户交互设计内成本（逐问原则是裁决质量机制）；
  其 prep 段随本设计享前缀剥离。
- 不上 CLAUDE_CODE_SIMPLE=1 / --bare（hooks 全灭 = S11/S14 结构保证丢失，
  探针 D 实证）。

## 4. 预期收益（每轮 u:2 运行，deepseek 口径）

| 指标 | 基线（今日） | 预期 | 机制 |
|---|---|---|---|
| merged 段 run-head 首调 fresh | 40,576 | ~12k（**-70%**） | 前缀 34k→4.8k |
| u:2#1 prep 段首调 fresh | ~40k 级 | ~12k 级 | 同上 |
| merged 段逐调用 cr | 前缀含 26k 可裁项 | 每调 -26k cr（0.1× 价格轴） | 前缀缩小 |
| #4 续步轮 | 3.5k fresh 暖 | 不变（进程内暖与本设计无关） | — |
| 墙钟 | run-head 首调 prefill 40.6k | prefill ~12k，两段冷启动各省 ~10-20s | prefill 缩量 |

护栏：hooks 全保留（探针 E 实证）；gate/judge/trace 契约零变更；白名单外节点
零行为变化（字段默认 False/None）；在飞工作流无 state schema 变更。

## 5. 影响面

- `dl_flow_nodes.py`：Node 两字段 + understand:2 置位（~20 行含注释）
- `dl_flow_engine.py`：segment_spawn_overrides 单源（~15 行）
- `scripts/workflow/dl_drive.py`：run_session/MergedSession 两参数 + 3 调用点
  （~25 行）
- `tests/`：overrides 单源测试 + run_session/MergedSession cmd&env 断言
  （monkeypatch Popen 同既有范式）+ 默认路径零变更断言
- hooks 零变更；WF_TUI=1 不动；front/drive 共用 spawn 点生效

## 6. 验证计划

1. TDD 红→绿 + 全量 pytest + ruff。
2. **live A/B（dl @ac-deepseek1，新实例 u2_sub5_ab）**：种子 = u2_sub4_ab
   evidence 裁至 u:2#1（五件套：裁 evidence/裁 last_judged_trace/清段记录与
   stash/settings name-agnostic/起跑前 handoff_pack 冒烟），从 u:2#2 起跑
   （#2 = run head 冷启动即验收点；#3 基线测量顺带核对 amplitude 今日值
   4920.2% 口径），跑到 u:2#5 confirm + u:3#1 needuser 自动收。
   验收点：
   - **#2 首调 fresh ≤ ~15k**（对照 u2_sub4_ab run-head 40,576，-60%+ 足额）；
   - merged #2-#4 同一 sid（段内续步不回归）；#3/#4 门控全 pass 零 block；
   - trace 质量目测不降（#4 statements 三字段齐全）；
   - #3 基线实测数字与今日值 4920.2% 口径核对（annual≈0.492）；
   - NEXT_PREP 附带交付照常落 stash。
3. AC_WORKFLOW_LAUNCHER 指向本 worktree dl-launch.sh（worktree A/B 驱动两前提：
   launcher 与 engine 同树；凭证不进命令文本，bashrc 函数体提取 env）。
4. **混淆声明预登记**（#18/#40）：#3 步体轮数方差剔出对比面；验收口径 =
   **#2 首调 fresh**（前缀剥离的直接度量，与步体方差天然分离）+ 全段 cr 逐调用
   口径。#2/#3/#4 步体内容不同不构成混淆——验收点只在首调前缀。

## 7. 实施验证记录（2026-08-18，feat/u2-residual-cost，1109 tests）

- TDD 红→绿（5 新测试先红[TypeError: unexpected kwargs]后绿）+ 全量 1109 passed
  + ruff 绿。提交 43d1874（design）+ 2b28374（feat）。
- **live A/B（u2_sub5_ab 实例，drive 直跑 worktree 代码 @ac-deepseek1/
  deepseek-v4-flash，种子 u2_sub4_ab evidence 裁至 u:2#1 从 u:2#2 起跑，跑到
  u:2#5 confirm + u:3#1 needuser 自动收）——验收点全中**：
  1. **机制生效直接证据**：段 init 事件 `"tools":["Bash","Edit","Read","Skill"]`
     （白名单生产生效）+ `mcp_servers:[]`（O1 不回归）；
  2. **#2 run-head 首调 fresh = 10,230**（验收口径；对照 u2_sub4_ab run-head
     40,576 → **-74.8%**，预期 ≤15k 足额）；逐调用 cr 各 -26k 固定前缀
     （探针 A/B 对照实证的分量，非 run 间对比）；
  3. merged #2-#4 同一 sid（84b2610b）段内续步不回归；node_attempts=0 全程
     零 block，三步门控全 pass（5/13/7 轮，126s/172s/86s——步体方差带内）；
  4. trace 质量不降：#2 双向矩阵逐项、#3 基线实测留痕（ob_quality 今值
     0.492015 → 双×100 装配 4920.15% = 今日值 4920.2% 口径 ✓）、
     #4 四条 statements（2 must + 2 nice，boundary 携带裁决传导）；
  5. NEXT_PREP 附带交付照常（「问题清单前序段已备（P2-1 合并段）」→ u:3#1
     转前台）；#5 confirm 机械通过（P3-1 不回归）。
- **全段账（result modelUsage 权威值，merged #2-#4 三步合计）**：fresh 39,826 /
  cr 905,856 / out 48,471 / $1.864——对照 u2_sub4_ab（#3+#4 两步 fresh 78,902 /
  cr 2,240,512），本 run 多跑一步（#2）fresh 反而 -50%、cr -60%（口径注意：
  跨 run 对比含步体差异，前缀剥离的干净读数以验收口径 #2 首调为准）。
- 探针台账（/tmp/wfprobe，生产旗标组合，凭证不进命令文本）：A 裸 harness
  22,333 / B worktree 默认 34,046 / E DISABLE 对 22,185（hook 照触发）/
  H +10 工具白名单 7,918 / I0 +4 工具白名单 4,812 / I' 数值法证
  --append-system-prompt-file 照常拼接 / D SIMPLE=1 fresh 1,452 但 hooks
  全灭（弃用铁证）/ G、H2 Skill·Bash·Edit 全可用。
