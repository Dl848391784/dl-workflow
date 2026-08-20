# plan:3#2 能力盘点 成本优化设计（p3-sub2-cost）

> H8 design.md。目标步 = plan:3 sub_step 2「能力盘点」（CapabilityToolSelection#2）。
> 方法论 = cost-optimization.md（#20/#25/#26/#30/#33/#37 等）；B 轮 provider =
> ac-deepseek1（deepseek-v4-flash）。**禁 factor 化**（用户指令 2026-08-20）：
> 条款全部机制/形态级，不把测试实例的因子名/文件面/数值写进引擎条款。

## 0. 验收口径

逐调用读数（#30：全轮总账被步体方差淹没）：首调 fresh / 段 fresh / 段 cr /
段 out / 轮数 / 工具调用数 / dur_api / 成本等效（段 fresh + 0.1×段 cr）/ block 数。

## 1. 基线（免跑基线 #30，A = p2_sub3_ab plan:3#2 链内段）

| 指标 | A 轮基线 |
|---|---|
| 首调 fresh | 104,483（cr=0，链冷） |
| 段 fresh | 116,032 |
| 段 cr | 1,273,216 |
| 段 out | 15,981 |
| 轮数 | 18 |
| 工具调用 | 17（Bash×12 + Read×3 + Edit×2） |
| dur_api | 127.2s |
| 成本等效 | 243,354 |

免跑基线三查：①目标步代码两轮间零变更（p2-sub3 只改 plan:2 族，plan:3#2
自 v2.107 framing 后未动）；②种子 evidence 同源（B 种子 = p2_sub3_ab
evidence 裁到 ≤plan:3#1，与 A 轮当时可见的前序留痕逐字节同源）；③口径差异
声明 = A 链内段 / B 断链 fresh，差异本身即处置项（见 §3 L2），在混淆声明
（§6）登记，非混淆。

## 2. 浪费盘点（17 调用逐条归因）

| 类别 | 调用数 | 说明 |
|---|---|---|
| 目录重复枚举 | ~4 | ls + python os.listdir×2 + os 循环，同一注册表目录反复列 |
| 子4 职责前置 | ~4 | codegraph which×2 + --help + db 存在性探测 = 可用性核验（子4 判面）被提前到子2 预跑 |
| 交付后徘徊 | 1 | append-trace 落库后仍继续动作（#37 交付即止面） |
| 合法核心 | ~3-4 | 每目录一次 ls、MCP 配置读、路由命中条目 SKILL.md frontmatter 读 |

结构归因：①注册表通道无默认源声明 -> 模型把「枚举」当「勘察」做重复
清点；②②通道（工具/CLI/MCP）与子4 可用性核验的职责边界未钉 -> 预跑验证；
③链内段上下文携带（子1 transcript 冷重写 cr=0）。

## 3. 杠杆

### L1 plan:3 Node 工具白名单（plan:3 首例，节点级）
`segment_tools=("Bash","Read","Edit","Skill","Agent")`。逐步需求核对：子1
Read+Bash / 子2 Read+Bash / 子3 Agent（条件红队）/ 子4 Bash+Read / 子5
Skill（define-problem 归一化）+Edit（--scaffold 载荷填充）/ 子6 交互步
（TUI 工具自动并集，不适用）。收益 = 工具 schema 前缀削减（探针 14.3k 面）
+ 机制堵白名单外工具越界（u4-sub1 同型）。Grep 不入单（grep 走 Bash，
plan:2 同判）。

### L2 步级断链（步级粒度第二例，p1-sub5 首例后）
`SEGMENT_CHAIN_SKIP_STEPS += ("plan:3", 2)`。判据：#20 deepseek 会话隔离
缓存下链首调恒冷（A 轮首调 104,483 cr=0 = 子1 transcript 冷重写）+ #24 前序
上下文携带税主导；材料完备性核对 = 交接包含当前节点已完成各子步最新 trace
全文（子1 need_baseline 在包，handoff_pack 逐字段核对过）。子3 侧效应 =
链 resume 换挂子2 fresh 会话（继承 transcript 变小，同向不反向）。surgical：
节点白名单不动、plan:3 其余步零行为变化；节点级断链否决（见下）。

### L3 复用钉死+职责边界（子2 purpose/selfcheck 文案，机制级）
- ①skill 注册表默认源 = 段注入内会话 available-skills 列表（零查询逐字
  引用即合法）；②内置工具/CLI/MCP 枚举引用 CLAUDE.md §3、强制路由引用
  §2（均会话自动加载，零重读零重跑）；子1 需求清单在交接包内逐字引用，
  零重翻 evidence。
- 枚举例外（按条配额）：磁盘 skill 目录每目录 ls 一次（读后零重读）；
  路由命中条目 SKILL.md frontmatter ≤1 次/条目。
- 职责边界：CLI/MCP/环境的可用性验证（which/版本冒烟/连接确认/db 存在
  性）归子4 可用性核验--本步②只枚举名称+出处，禁预跑子4 的验证。

### L4 交付即止（#37 平移）+ 格式真源（#26 平移）
append-trace 落库后零后续动作（不预习子3）；载荷走 --scaffold 骨架+Edit，
格式真源 = 报错文案，禁读引擎/测试源码反推。

### 否决表

| 候选 | 否决理由 |
|---|---|
| Step strip（env 剥离） | 子2 trace 正文逐字引用 CLAUDE.md §2/§3 条款 = 一等材料；剥 env 后 CLAUDE.md 不自动加载，逼模型 Bash 重读 = 反优化（u:3#1 同型） |
| pack_self_contained | #19 盘点步产出新事实（注册表清单是本步新勘察产出），非纯消费步 |
| MERGED 段内续步 | 步体 18 轮非极小搬运型（#24 口径） |
| 节点级断链 | surgical 原则：步级粒度已覆盖目标步；plan:3#1/#3-5 未做逐步核对，节点级出册超单步范围（且并行会话 p3-sub1 在飞，冲突面最小化） |

## 4. gate 零变更三查（#29）

①mech 词表：子2 无 mech_checks，无词面冲突；②judge 方框：方框一/三合法
形态已认「列表行/文件路径」纯出处标注，判材边界已钉「真实注册表结构性
不可见」；③复用引用形态（「复用 子1 留痕：…逐字」+ CLAUDE.md §3 引用）
不命中任一 block 条件（方框二只查路由覆盖、方框三只查功能描述无出处）。
三查全过，零 gate 文本改动，无需重放。

## 5. 预登记（验收线）

| 指标 | 基线 | 预期 | 机制归因 |
|---|---|---|---|
| 首调 fresh | 104,483 | ≤55k（-47%+） | L2 断链去 transcript 冷重写 + L1 schema 削减 |
| 轮数 | 18 | ≤12 | L3 配额+职责边界 |
| 工具调用 | 17 | ≤9 | L3（重复枚举+预跑子4 归零）+ L4 徘徊归零 |
| 段 cr | 1,273,216 | 大降（≤600k） | L2 前缀变小 × L3 轮数变少 |
| 段 out | 15,981 | ≤14k | 轮数下降（#33 out 回馈登记：复用钉死可能抬引用厚度） |
| dur_api | 127.2s | ≤90s | 轮数×调用双降 |
| 成本等效 | 243,354 | ≤130k（-45%+） | 合成 |
| block | 0 | 0 | gate 零变更 |

三分量报价（#33）：fresh（断链+白名单）/ cr（前缀×轮数）/ out（#33 反噬
面登记不撤）。

## 6. 混淆声明

- amplitude 今日值 4929.2%（种子 problem_statement 维持 4824.5% 原文 =
  #18 漂移面，历轮同面）；plan:3#2 与数值零判面接触（能力盘点不碰因子
  数值），登记不处置。
- A 链内段 / B 断链 fresh 口径差 = 处置本身（§1 三查③）。
- 并行会话在飞：p3-sub1-cost（plan:3#1，同 Node 块可能冲突，并轨收口）、
  p2-sub4-cost（plan:2#4）。B 轮种子与两会话实例隔离（独立实例名
  p3_sub2_ab + 独立 evidence 副本）。
- 链内基线手法（#25）：基线取自 p2_sub3_ab drive-stream plan:3#2 段切片
  （transcript 台账为准），非重跑。

## 7. 测试与回滚面

- 新增测试：①`("plan:3", 2) ∈ SEGMENT_CHAIN_SKIP_STEPS`（test_dl_drive
  既有 constant 测试旁）；②plan:3 Node segment_tools 钉死（镜像 plan:1/2
  tools 测试形态）；③子2 purpose/selfcheck 条款 pin（镜像
  test_p2_step2_reuse_and_delivery_clauses_pinned：默认源/零重读/归子4/
  交付即止/--scaffold 关键词）。
- 回滚面：白名单 tuple 置 None / skip 集摘条目 / purpose 段落整删，均为
  单点翻转，兄弟步零暴露。
- ruff check + format；pytest 全绿（基线 1189+新增）。

## 8. B 轮种子装配（runtime-audit #25 五件套）

实例 p3_sub2_ab（主仓 .claude/workflows/p3_sub2_ab）：①evidence 裁到
≤plan:3#1（CapabilityToolSelection sub_step==1 止）存
.claude/evidence/p3_sub2_ab.jsonl；②last_judged_trace 裁同界；③
segment_sessions/segment_chain/next_prep_stashed 清零；④settings 验
name-agnostic（hooks 指向本 worktree
~/.dl-workflow-worktrees/p3-sub2-cost，statusline --name 改实例名；
`Bash(python3:*)` 宽条目已覆盖 worktree 绝对路径命令，#33② 无需补条目，
核对后登记）；⑤state 四字段同步（phase=plan/index/node=plan:3/
sub_index=3）+ **sub_step_index=2（将跑之步 1-based）** + problem_statement
原样 + drive_mode=true + worktree/branch 按 launcher 语义创建。handoff_pack
冒烟（探针纪律：cwd=/tmp，不带 workflow settings）。跑法 =
`AC_WORKFLOW_LAUNCHER=<wt>/scripts/workflow/dl-launch.sh ac-deepseek1 --dl
p3_sub2_ab --resume --headless` 后台；driver 日志核对断链生效（「⟂ 段链
续跑」特征行缺席）+ init 事件 tools 白名单；目标步 gate 过即收段统计。

## 9. 收官（B1->修1->B2，2026-08-20）

| 指标 | A 基线 | B1 | B2 | 预登记线 | B2 判定 |
|---|---|---|---|---|---|
| 首调 fresh | 104,483 | 42,088 | 42,288 | <=55k | OK -59.5% |
| 段 fresh | 116,032 | 52,834 | 57,073 | -- | OK -50.8% |
| 段 cr | 1,273,216 | 816,896 | 384,768 | 大降 | OK -69.8% |
| 轮数 | 18 | 16 | 10 | <=12 | OK |
| 工具调用 | 17 | 15 | 9 | <=9 | OK |
| out | 15,981 | 33,900 | 31,832 | <=14k | X +99% 反噬（#41 第五实例，登记不撤） |
| dur_api | 127.2s | 217.6s | 208.0s | <=90s | X +63.5%（out 驱动，out÷rate ~155 tok/s 拟合上） |
| 等效 | 243,354 | 134,523 | 95,549 | <=130k | OK -60.7% |
| block | 0 | 0 | 0 | 0 | OK |

- B1 未兑现两族纯税：同目录复探 x3（ls/find/python os 同面三变体）+
  plugins/marketplace 表面外掘进 x4 -> 修1 双侧补钉（同一目录累计一次
  按面不按词形 + 注册表面显式排除）-> B2 9 调用理想最小形态。
- B2 工具序列：ls 两目录各一次 + MCP 配置读 + SKILL.md frontmatter
  Read x2 + scaffold/Read/Edit/落库四件；零 which/冒烟/db 探测（职责边界
  兑现）、零 evidence 翻找、零交付后徘徊、零 block（gate 零变更三查
  实证成立）。
- 首调 fresh 双样本收敛 +/-0.5%（42,088/42,288）= 断链+白名单机制读数
  确定性再实证。
- trace 质量自查（防 Goodhart）：三通道齐备（available-skills 逐字列表+
  磁盘目录 ls 出处+CLAUDE.md §2/§3 引用）、H15/codegraph 路由核对在场、
  逐任务说明在场——out 增厚成分为引用厚度非褶皱。
- 沉淀：cost-optimization #40（注册表枚举型第四型：默认源+按面配额+
  表面显式排除）/ #41（out 反噬第五实例，枚举型步 2.0-2.1x 报价样本）。
- 混淆复核：amplitude 4929.2% 漂移面零判面接触（trace 无数值断言）；
  A 链内/B fresh 口径差=处置本身。
