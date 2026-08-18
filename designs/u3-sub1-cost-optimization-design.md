# understand:3 子1（障碍分析引出）耗时/token 优化设计

> 日期：2026-08-18 · 分支 feat/u3-sub1-cost · 状态：实施中
> 上游：designs/u2-sub1-cost-optimization-design.md（NEXT_PREP 跨节点 + sources 出处包——
>      u:2#4→u:3#1 顺带交付已连带生效）；designs/u2-residual-cost-optimization-design.md
>      （段前缀外科剥离 #23）；designs/u1-prefix-strip-design.md（#23 泛化第一例）
> 触发 = 用户指令（2026-08-18）：「优化 understand:3 的 step1，耗时和 token 消耗要大幅降低，
> 能用前面步骤沉淀下来的 discovered 和 evidence 就尽量用，避免 factor 化；
> 跑测试工作流用 ac-deepseek1；amplitude 今日值 4920.2%」（承 u:2 子1-5 优化系列之后）。

## 0. 前置修复（9ba4cc1，非本优化项但基线起跑的前置）

O1（e61c982）把 NO_MCP_ARGS 加进 `_build_tui_cmd` 后，prompt 位置参数紧跟
`--mcp-config` 值被 **variadic 吞参**当作第二个配置文件路径：长任务书报
ENAMETOOLONG、TUI 段 rc=1 秒退。实证 = u2_sub2/3/4/5_ab 四实例到达 u:3#1
needuser 全部 rc=1（TUI 段是唯一带尾随位置参数的 spawn 点；judge/headless/
红队 worker 后续跟 flag 或走 stdin 免疫）。/tmp 探针（无 workflow settings）
复现并验证两种修法；取 `--` 分隔符（prompt 钉死纯位置参数）。**无此修复
drive 模式任何 prep 后交互步都无法运行**——基线与 A/B 均含此修复。

## 1. 基线实测（u3_sub1_base，2026-08-18，ac-deepseek1/deepseek-v4-flash headless）

种子 = u2_sub5_ab evidence（u:1#1-u:2#5 真实 trace 全量）+ u:3#1 stash
（need_user.json questions×3 + sources×10，恢复 next_prep_stashed 标记）从
u:3#1 起跑。A/B 环境无 TTY → AskUserQuestion 不可用，第一轮模型分析完等用户
（stdin EOF 收段），`--resume` 喂三问答案（无时限/接受重跑/装配层通用 +
会话事实：今日显示值 4920.2%≈0.492 双×100 装配放大）第二轮落 trace。

**u:3#1 完整会话（13 调用，keep-max 去重）**：

| 指标 | 基线 |
|---|---|
| fresh in | 101,296 |
| cache_read | 617,856 |
| out | 23,843 |
| 首调 fresh | 41,988 |
| 模型墙钟 | ~96s（两轮合计，不含等用户） |
| 工具调用 | 18 TaskCreate + 5 TaskUpdate + 1 Read(need_user.json) + Bash/Edit 落库 |

### 成本归因（逐调用拆解）

1. **前缀 42k 每次冷付全量、暖付逐调重读**：call1 fresh 42k 冷付；call2-3 cr 暖；
   **call4 fresh 49k/cr=0 = deepseek 会话缓存中途失效全量重付**（时灵时不灵再添
   一例）；call5-13 暖。cr 总账 618k ≈ 42-67k 前缀 × 11 暖调——**前缀既是首调
   fresh 主项，也是逐调 cr 主项**。前缀构成（#23 分解口径）：项目上下文 ~11.9k
   （CLAUDE.md+auto-memory——交接包由 SessionStart hook 注入，项目路由文件是
   死重）+ 全量工具 schema ~14.3k（u:3#1 只需 AskUserQuestion/TaskCreate/
   TaskUpdate/Read/Bash/Edit）。
2. **零仓库探索、零 evidence 全量重读**——sources 出处包（u2-sub1-cost 修B）
   已兑现「用前序沉淀」：约束候选全部钉具体对象（`convert_return_to_percentage`
   装配双×100 链 / H15 codegraph 查证 / coverage≈0.50 / 子3 基线实测
   backtest json 路径），出处=载荷 sources 逐字引用。本基线证明 evidence 复用
   通道已通；discoveries 台账（dl codebase ledger）指针经 node-rules/tui-rules
   「发现台账」节本就在场，模型本轮无需使用。
3. TaskList 18 项逐字建单 = 23/30 工具调用（v3.3.1 用户裁决面，本设计不动，
   见 §7）。

## 2. 方案（两修，全部机械层/装配层，零判据变更）

### 修1（主修）：TUI/needuser 段前缀剥离——#23 泛化第三例（u:3 置位 tools-only）

`segment_spawn_overrides(node)` 单源已服务 run_session/MergedSession 两条
headless 管线；本修把它接到第三条 spawn 管线 `run_tui_step`（drive 模式交互段）：

- **env**：`node.segment_strip_project_context=True` 时 Popen env 叠加
  `_SEGMENT_STRIP_ENV`（hooks 不受影响，#23 探针 E 实证；SessionStart 交接包
  注入照常）。**u:3 不置位**（B1 实证见 §6：本节点约束分类把「项目硬规则」
  列为一等约束源，自动加载的 CLAUDE.md 是任务功能材料非死重，剥掉诱发
  规范文档重读，总账反超——#23 置位前置两核对补第三条：任务内容本身引用
  自动加载文档的节点禁剥 env；u:1/u:2 维持原置位——其 CLAUDE.md 引用逐处
  核对全是「约束源 Read 指针」）。
- **tools**：`node.segment_tools` 置位时 cmd 加 `--tools` 白名单 =
  segment_tools + **TUI 交互必需三件套**（`AskUserQuestion`/`TaskCreate`/
  `TaskUpdate`——问答卡片与 v3.3.1 开场纪律清单是 TUI 段的结构职能，单源常量
  `_TUI_STEP_TOOLS`，非交互段不加；放在 NO_MCP_ARGS 之前守 variadic 排序纪律）。
- **u:3 Node 置位 `segment_tools=("Bash","Read","Edit","Skill")`**（逐字段核对：
  子2 本地验证=Bash+Read（codegraph 走 Bash CLI）；子3 推理型；子4 kind=skill
  define-problem→Skill；落库=scaffold+Edit 零合法 Write；子1 交互段三件套
  由上条自动附带；无 Agent 需求——子2 本地单层源不派子代理，对照 u:1 子4
  取证才含 Agent）。置位连带生效于 u:3#2/#3/#4 headless 段（顺带收益）。
- **front 模式零变更**：常驻 TUI 由 dl-launch.sh 直接 exec，不经 run_tui_step；
  v2（WF_TUI=1）不动；u:1/u:2 已置位节点的 drive 交互段同机制连带受益
  （方向一致，不 retroactively 影响已收官读数）。

### 修2（兑现「用 discovered」）：sources 合同扩类目——台账锚点合法化

现状缺口：`_QUESTIONS_CONTRACT` 的 sources 类目 = 「前序用户原话/会话事实」，
prep 方按字面执行会**排除**发现台账（discoveries.jsonl）内容——台账是框架级
产物（dl codebase query 落账，结构查询的 file:line/symbol 锚点=「点」非 grep
命中「面」，#7 判别通过）。修：sources 描述扩一类——「前序留痕/发现台账中与
本步问答直接相关的已验证事实与结构锚点（file:line/symbol/规则条号，含出处
类目）」。**条件化零成本**：台账不存在/无相关项时不读不收录（宁纵勿枉，无
强制 Read）；prep 段 node-rules 本就有台账指针（通道已在）。零判据变更：
u:3#1 gate 对候选句本就不要求出处（反事实假想合法），sources 只是把「 grounding
材料已在包内」从用户原话扩到结构锚点，防的是弱模型为点名具体对象去做全仓
探索（基线 n=1 未发生，但 n=1 不是结构保证）。

### 避免 factor 化自证（#2 边界）

两修全部框架通用：修1 = spawn 管线前缀裁量（代码结构语义零耦合）；修2 措辞
只引框架产物名（discoveries.jsonl/dl codebase/file:line/symbol），无任何
factor_IC_analyzer 数据契约（无因子/回测/报告词形）。u:3 Node 置位是声明式
字段翻转，机制本身跨项目通用。

## 3. 预期收益（u:3#1 单次到达，deepseek 口径，tools-only 修订后）

| 指标 | 基线 | 预期 | 机制 |
|---|---|---|---|
| 首调 fresh | 41,988 | ~27-28k（**-33~35%**） | 工具 schema -14.3k（项目上下文保留——见修1 env 不置位理由） |
| fresh 总账 | 101,296 | ~75-85k（**-16~26%**） | 首调 -14.3k + 中途失效重付同幅缩减 |
| cache_read | 617,856 | ~430-460k（**-26~30%**） | 逐调少背 ~14.3k × ~11 暖调 |
| 模型墙钟 | ~96s | ~70-80s（**-17~27%**） | 逐调重读量缩，TTFT 随 cr 缩 |
| out | 23,843 | ~持平 | 步体内容不动 |

（初版全量 strip 预期：首调 -57~62% / fresh -46~51% / cr -48~55%——B1 实证
env 剥离诱发重读使总账反超，已按证据下修为 tools-only 预期。）

护栏：一次通过率不降（gate 判据零变更；strip 不动 hooks/注入通道——#23 探针
实证 hooks 照常触发）；交接包注入（SessionStart）不受 DISABLE 对影响；
AskUserQuestion 在白名单内（真实 TTY 场景问答卡片照常）。

## 4. 影响面

- `scripts/workflow/dl_drive.py`：run_tui_step 接 segment_spawn_overrides
  （env 叠加 + tools 白名单 + `_TUI_STEP_TOOLS` 常量）+ `_QUESTIONS_CONTRACT`
  sources 扩类目一句
- `dl_flow_nodes.py`：understand:3 Node 置位两字段（声明式，禁硬编码步号）
- tests：TUI spawn strip 接线（置位节点 env/tools 进 cmd、未置位零变化、
  TUI 三件套只在 TUI 段出现）+ u:3 装配不变量 + 合同文案断言 + 既有全量回归
- 三模式：drive（TUI 段+headless 段）生效 / front 零变更 / v2 不动
- 在飞工作流：state 无 schema 变更；未置位节点零行为变化（回滚面=字段翻转）

## 5. 验证计划

1. TDD 红→绿 + 全量 pytest + ruff。
2. 生产旗标组合冒烟（探针纪律 cwd=/tmp 无 workflow settings）：TUI spawn 命令
   形态 `--tools` 白名单 + DISABLE 对 + `--` 分隔共存；hook_fired 实证（#23
   探针 E 同法——DISABLE 对下 SessionStart 注入照常）。
3. **live A/B（dl @ac-deepseek1，新实例 u3_sub1_ab）**：种子 = 同基线
   （u2_sub5_ab evidence + stash），同三问答案（无时限/接受重跑/装配层通用 +
   4920.2% 会话事实），从 u:3#1 起跑。验收点：
   - 首调 fresh ~16-18k（对照基线 41,988）；fresh 总账/cr 总账对比；
   - 零 Read evidence 全量 / 零仓库探索（transcript 工具调用核对——基线已零，
     优化后须保持零）；
   - 零 block（node_attempts=0）、judge pass、trace 质量目测不降（约束候选
     钉具体对象 + 类型 ≥3 类 + 每 must 目标否定提问留痕）；
   - u:3#2 headless 段首调 fresh 同步下降（置位连带收益核对）。
4. **混淆声明预登记**：#18——基线与 A/B 间种子 evidence 零漂移（同一拷贝，
   无测量步介于其间）；模型等用户轮数方差（弱模型一轮等/直接落两态都见过）
   属步体方差（#40），验收口径 = **首调 fresh + fresh/cr 总账 + 零探索核对**，
   不按调用数。
5. AC_WORKFLOW_LAUNCHER 指向本 worktree dl-launch.sh（launcher 与 engine 同树
   解析；凭证不进命令文本，bashrc 函数体提取 env）。

## 6. 实施验证记录（2026-08-18，feat/u3-sub1-cost，1115 tests）

- **前置修复（9ba4cc1）**：/tmp 探针复现 variadic 吞参（短 prompt→
  "MCP config file not found: /tmp/<prompt>"，长任务书→ENAMETOOLONG）；
  `--` 分隔与 equals 两修法均验证，取 `--`。修复后 TUI 段全链路首跑即通
  （u3_sub1_base 从 u:3#1 一路绿灯到 u:4#1，全 node 零 block）。
- **TDD + 全量 1115 passed + ruff 绿**（format 漂移只收自己引入的两处）。
- **生产旗标组合探针**（/tmp 无 workflow settings）：`--tools 白名单 ×
  DISABLE 对 × --strict-mcp-config × --` 分隔共存启动正常、应答正常、
  零 MCP 报错。

### live A/B（ac-deepseek1/deepseek-v4-flash headless，种子=u2_sub5_ab
evidence 全量+u:3#1 stash，同三问答案：无时限/接受重跑/装配层通用 +
4920.2% 会话事实）

**B1（全量 strip 配置，u3_sub1_ab）= 反证轮**：首调 13,974（-67%）达标，
但模型为点名规则条号重读 CLAUDE.md/PROJECT.md/data_loaders.py/
formatters.py（+40k 上下文驻留），resume 轮冷重付 87.4k，总账
fresh 148,023/cr 1,377,024 **反超基线**。机制定位：u:3 约束分类把
「项目硬规则」列一等约束源（子1 候选须点名规则条号、子2 合法验证源=
Read 规范文档原文），自动加载的 CLAUDE.md 对本节点是**任务功能材料**
——与 u:1/u:2（引用全是 Read 指针）结构性不同。据此下修为 tools-only
（33cd99b），#23 置位前置核对补第三条。

**B2（tools-only，u3_sub1_ab2）vs 基线 A（u3_sub1_base）——预登记口径**：

| 指标 | A 基线 | B2 | 变化 |
|---|---|---|---|
| **首调 fresh（主口径）** | 41,988 | 26,310 | **-37.3%**（预期 -33~35% 足额略超） |
| **cr 总账** | 617,856 | 342,912 | **-44.5%** |
| 暖调逐调 cr | 45.6-67.3k | 33.9-74.0k | 前缀逐调 -14.3k 机制读数 ✓ |
| out | 23,843 | 20,387 | -14.5% |
| fresh 总账 | 101,296 | 108,675 | +7.3%（混淆见下） |
| 调用数 | 13 | 8 | resume 轮权限摩擦降噪（--settings+
--permission-mode 显式传） |
| 探索行为 | 零 | 零（Read need_user.json + 1 次定点 grep evidence 引文） | ✓ 不回归 |

- **fresh 总账混淆声明（预登记执行）**：B2 resume 轮冷重付 67.8k
  （deepseek 跨进程缓存丢失，#9 时灵时不灵），A resume 轮暖（无冷重付）——
  provider 缓存方差非机制效果。双方各剔一次冷重付（A call04 49.3k /
  B2 call04 67.8k）后：B2 ~41k vs A ~52k = **-21%**。
- **零探索核对**：B2 无规范文档/代码文件重读（B1 的 40k 重读面消失——
  env-strip-诱发假设坐实）；sources 逐字引用兑现（trace 引 ProblemContext
  陈述2 双×100 链 / 子3 基线实测 / 用户三问原话+4920.2% 会话事实；
  H15/H1/H9 规则条号自上下文内 CLAUDE.md 引用——正是 env 保留的功能）。
- **trace 质量**：q×6 a×6 按序对齐；候选钉具体对象（OB1 双×100 装配链/
  OB5 日收益序列未持久化/long_short_return_annual 字段）；结论①逐句
  出处；类型覆盖 ≥3 类。
- **A/B 驱动伪影登记（对称剔除）**：①driver 重启重收段（无 gate-first
  路径，TUI退=全退后续跑=重跑当前步）产生重复 u:3#1 trace 与额外会话
  （A 66.7k/1.54M；B2 同型未计入对比面）；②--resume 喂答案轮权限摩擦
  （A 3 次 denial 自恢复 5 调；B1 12 调 deliberation）为驱动法固有噪声，
  不属机制效果。
- **基线附带发现（独立后续项，不在本设计面）**：u:3 段链在 deepseek 上
  恒冷实锤——u:3#3 首调 fresh=134,435/cr=1,792（继承上下文全量重写），
  链合计 fresh 344k/cr 2.84M。与 u:2#3 断链前同构（#20：会话隔离缓存
  provider 上链=纯税），断链候选须用户裁决（前决议「峰值未破保留」是
  防爆默认非成本最优）。

### u:3#2-#4 连带收益（tools 白名单对 headless 段）

（B2 driver 续跑后回填：#2 首调对照基线 40,228）

## 7. 显式不做

- 不动 TaskList 18 项逐字建单（v3.3.1 用户裁决面：内容同源逐字渲染；23/30
  工具调用的仪式税记为已知未开杠杆，须用户裁决才动）；
- 不动 gate 判据 / judge 机制 / NEXT_PREP 与 sources 主结构（修2 只扩类目措辞）；
- 不给 u:3#1 配 discoveries 强制 Read（#6 零和游戏：基线证明无探索可灭时，
  强制 prep 读台账 = 净增税；通道与合法化措辞就位即可）；
- 不动 front 模式常驻 TUI 的上下文（交接 /clear 架构的管辖面，独立项）。
