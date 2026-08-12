# 交互步后台化预处理 + TUI 纯问答 设计

> 日期：2026-08-12 · 分支 feat/interactive-headless-prep · 状态：设计待裁决
> 上游：designs/front-tui-hybrid-design.md（v4 架构）· designs/v4-statusline-progress-design.md（statusLine）
> 触发 = 用户 dogfood 反馈（2026-08-12 原话）：「交互步能不能也通过 claude -p 执行在底部展示，不在 TUI 展示进度，等到需要用户执行的时候再在 TUI 上显示」

## 1. 问题定义

v4 + statusLine 落地后，非交互步全程后台 + 底部状态栏，用户体验好（用户原话「我感觉特别好」）。但 13 个交互步（8 读回 + 4 引出 + plan:1#2）仍整段占 TUI：用户会看到通知、模型 Read 产物、组织上下文等**工作过程噪音**，最后才是问题本身。

诉求：**交互步的准备工作沉到后台（状态栏照常显示），TUI 只剩纯问答**。

### 边界澄清（不写进诉求）

交互步的耗时大头是用户自己的思考/回答时间，后台化**不省时间**——收益是 TUI 干净，不是变快。本设计不承诺加速。

## 2. 用户裁决（2026-08-12，勿推翻）

1. **按此方向实现**：交互步后台预处理 + 需要输入时转 TUI。
2. **问题传递方式选前者**：问题清单由后台工人备好、**逐字传给 TUI**，TUI 模型纯执行提问（禁改写）——TUI 里零组织过程痕迹。

## 3. 机制基础（已有 80%）

- NEED_USER 动态重分类（front-tui-hybrid-design）：headless 会话输出 `### NEED_USER` → 段退 code 13 → `front_dynamic_interactive` 咬合当前位置 → hooks 落 v2 路径 TUI 接管。**本设计把它从「意外兜底」升级为「交互步标准路径」。**
- 读回步材料装配已有脚本化通道（render-readback，v2.59-61 四桶分工）。
- 段在跑期间 statusLine 照常显示进度（刚落地）。

## 4. 核心设计

### 4.1 段边界判定改动（dl_drive.py）

`run_until_boundary(stop_at_interactive=True)` 撞交互步退 code 10 改为：**交互步不再停段**，照跑 headless 会话，但用**交互步 headless 变体 prompt**（§4.3）。`Step.interactive` 标注保留（语义从「预路由 TUI」改为「用 NEED_USER 变体 prompt + AskUserQuestion 封锁」），`test_interactive_annotation_set` 防漂移断言不动。

### 4.2 AskUserQuestion 三层机械保证（核心风险正治）

风险：弱模型工人在「该问用户」局面下不走 NEED_USER 出口。静态标注当年就是防「headless 撞 AskUserQuestion 不可用」。三层全机械，不依赖模型记忆：

| 层 | 机制 | 防什么 |
|---|---|---|
| L1 堵入口 | 交互步 headless 会话加 `--disallowedTools AskUserQuestion`（CLI 旗标已实证存在） | 工具在权限层不存在，调了必吃 denial 错误回执 |
| L2 检测兜底 | driver 扫 stream-json 出现 `AskUserQuestion` 的 tool_use（无论成败）→ **机械按 NEED_USER 边界收场 code 13**，无需标记 | 模型又调工具又忘标记的双重走岔 |
| L3 现状保留 | 会话结束无 trace 无标记 → none_retries/escalate | 模型安静跑完什么都没留 |

L2 实现要点：run_session 流式解析处加 tool_use name 嗅探，命中即记 flag，会话结束判定优先级 = 显式 NEED_USER 标记 > AskUserQuestion 嗅探 > trace 落库。注意 L1 的 denial 回执也是 tool_use+error tool_result 形态，嗅探不受影响。

### 4.3 交互步 headless 变体 prompt（build_step_prompt 分支）

与非交互步 prompt 的差异：
- 任务重述为「**准备**」而非「执行」：读本步输入产物/skill 骨架 → 备好问题清单（含每问 question/options/multiSelect，选项设计纪律沿用各步 purpose 既有条款）→ 输出 `### NEED_USER` + **结构化问题载荷**后结束；
- 钉死「禁调 AskUserQuestion（本环境不可用），禁编造用户答复」；
- 读回步（8 个）：材料由 render-readback 脚本装配（四桶分工不变），工人只组织提问面；
- trace 职责划分：本步 trace 的「用户答复」部分仍由 TUI 段落库（读回/引出步的裁决记录通道不动），工人 prep 不落 trace（或落 kind=prep 辅证，**实现时裁决**，倾向不落——避免污染 gate 判材）。

### 4.4 NEED_USER 问题载荷传递（前者裁决的落地）

- 工人在 NEED_USER 后附结构化问题清单（JSON 块或配套骨架文件，**实现时裁决格式**，倾向落 `meta/need_user.json`——走文件不走 stdout 解析，与 segment_summary 同范式）；
- driver 收场时把问题清单路径写进 segment_summary.json；
- TUI 侧注入（workflow_phase.py code 13 重分类分支）改文案：「问题清单已备好：Read <路径>，**逐字照抄禁改写**（v3.3.1 内容同源同范式），用 AskUserQuestion 逐问提出」；
- 无载荷/载荷解析失败 → 退回现状行为（TUI 模型自己组织提问），宁纵勿枉。

### 4.5 门栏/闸门不动

plan:4 门栏、plan→execute 闸门、/dl gate 流程与本设计正交，零改动。

## 5. 影响面

- dl_drive.py：段边界判定 + L2 嗅探 + 变体 prompt 分支（主要改动面）
- workflow_phase.py：code 13 注入文案（小改）
- dl_flow_nodes.py：`Step.interactive` 注释语义更新（数据不动）
- tests：L2 单测 + 变体 prompt 断言 + code 13 载荷传递测试
- 三模式兼容：v3 headless 全程模式同样受益（NEED_USER→TUI 段通道已有）；WF_TUI=1 旧路径不动
- 在飞工作流：段边界判定在 driver 进程内，在飞段不受影响；下一段新代码自然生效

## 6. 验证

1. **第一验证项（重放实证）**：交互步变体 prompt + `--disallowedTools AskUserQuestion` 下，真实模型跑 13 个交互步代表样本（至少 2 读回 + 2 引出），NEED_USER 出口率须 100%（n≥6/节点族）；记录 L2 嗅探实际触发次数（L1 若完备应为 0，>0 说明模型仍会试调，更证明 L2 必要）。
2. **单测**：伪造 stream 含 AskUserQuestion tool_use → code 13；变体 prompt 关键条款断言；need_user.json 传递/缺失退回；`test_interactive_annotation_set` 回归。
3. **pty 冒烟**：段跑交互步 → 状态栏显示 ⏳ → NEED_USER → TUI 醒来直接弹问题（零工作过程痕迹）。
4. ruff 全绿；全量 tests 回归。

## 7. 显式不做

- 不做「交互步也全自动」（编造用户答复）——红线，用户答复必须真人给出；
- 不改 trace/gate 判据语义（prep 不落判材 trace）；
- 不做问题清单的 judge 质检（问题质量沿用各步 purpose 既有条款 + 用户当场可纠正，加质检层是过度工程）；
- 不动 v2 旧 TUI 路径（WF_TUI=1）。

## §8 追加（2026-08-12 用户裁决）：裸开场收窄 = 只收陈述，step1 也后台化

用户原话：「我问完问题后 TUI 加载 tasklist，然后 step1 也在后台执行——step1 启动前所有流程和交互跟现在一样，只不过 step1 也改在后台执行」。

**机制**：
1. **机械捕获**（workflow_phase.py UserPromptSubmit）：位置 = u:1#1 且 state 无 problem_statement 时，把用户本条 prompt 机械写入 state.problem_statement（engine.set_problem_statement 既有通道，handoff_pack 顶部收录已有）。防误捕：以 `/` 开头的命令、<4 字符的 prompt 不捕。误捕补救 = Q&A 环节当场纠正 / /dl state-reset。
2. **路由收窄**：front 注入 `_work_here` 从「step.interactive 即前台干」改为「step.interactive 且无陈述（真·裸开场）才前台干」——有陈述后 u:1#1 与其余交互步同路径：派段 → prep → code 13 → TUI 弹卡片。`_is_bare_open` 加 `has_statement` 条件（dl_drive 段边界同步：有陈述的 u:1#1 走 prep 不再退 10）。
3. **陈述当轮注入变体**：捕获发生的当轮注入「✓ 已记录问题陈述 + 建齐 TaskList + 立即派段」指引。
4. v2（WF_TUI=1）模式只捕获不改路由（无段概念）；drive 模式行为不变（bare TUI 段落 trace 收段，rework 才有二次访问而 rework 非裸）。

**验证**：u:1#1 prep 变体真实模型重放 n=3（带假陈述）NEED_USER 出口率须 100% 才 merge；单测覆盖捕获/防误捕/不覆盖/路由两态/段边界两态。
