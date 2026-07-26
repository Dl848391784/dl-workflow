# ProblemContext 提示词 harness 化优化：注入瘦身 + 双通道单源 + 正反例

> 状态：**已实施**（2026-07-26；engine/注入 hook/phase-rules 模板/dl-launch/tests/SKILL 已同步，pytest 265 全绿 + ruff clean）
> 输入材料：`harness-prompt-optimization-problem-analysis.md`（实测数据 + 差距分析 + 用户原话出处）
> 参照标本：Claude Code 自身 harness（system prompt / 工具描述 / system-reminder 体系，直接观察；未做外部文献取证）
> 约束真源：`workflow-creation` SKILL.md §3.5（rubric 分层/Goodhart）、症状 M（改编排 6 处同步清单）

## 0. 动因（实测，可复查）

ProblemContext 中途（understand:1 子步骤3）用真实 state 调 `_format_injection` 实测：

- **每轮注入 6,100 字符 ≈ 4,200 token**，其中 **64%（~3,900 字符）是 6 个子步骤 purpose 全文**——静态内容每轮逐字重发（demo 121320fe 实录 48 轮/次 ProblemContext ≈ 20 万新鲜输入 token 仅注入一项）
- 「当前步」信号 = 埋在列表第 ~2,600 字符处的 `【当前】` 行尾标记（违反关键信息置顶）
- 子步骤 purpose 有**两份异文手维护副本**：engine（注入通道，`dl-flow-engine.py:165-351`）vs phase-rules.md（system-prompt 通道，`phase-rules.md:30-35`）——症状 M/F 记录的「两通道措辞漂移」病根的现存病灶
- purpose/gate 字符串内嵌维护者考古（`（demo fbdb6ebd 实录…）` `（实录：61 次 Read 全空）`），执行模型/judge 不需要，且 judge 输入随 rubric 线性增长（SKILL.md 已记子1 ~3k → 子5 ~19k caveat）
- evidence 格式块用 3 行散文警告（占位符/字段解释/数组对齐），无正反例
- 单轮注入强信号 ~15 处（禁止×4/必×6/强制×2/违规×2/⚠️/🚧），弱遵从模型习惯性忽略

## 1. 第一性原理：Claude harness 的可迁移实践

| # | 实践 | 本设计兑现处 |
|---|---|---|
| ① | 静态规则与动态状态分通道：稳定规则进 system-prompt（吃 prompt cache），每轮注入只带 delta | P0（注入只带当前步全文 + 骨架） |
| ② | 关键信息置顶（primacy）：当前任务放注入最前 | P0（当前步块置顶） |
| ③ | 正反例替代散文警告；执行文本不含维护者考古 | P2（evidence ✓/✗ 例；purpose/gate 清考古） |
| ④ | 一条规则说一次；多通道必须**同源生成**而非手维护两份 | P1（phase-rules 子步骤段从 engine 渲染） |
| ⑤ | 强调信号经济学：合并重复禁令，每条硬规则每通道说一次 | P2 |
| ⑥ | 给 rationale 防合理化绕过 | 保留现状（已做好，不动） |

**不可动摇的既有对齐**（动了即回退）：硬约束进 hook（S10-S15 围栏）；judge `--tools ""` 裁剪；质量判据黑盒防 Goodhart——P2 瘦身只删考古与重复，**判据条目逐条保留**（§5 测试钉死关键词回归）。

## 2. P0：注入瘦身（改 `hooks/workflow_phase.py:_format_injection`）

### 2.1 新结构（有 sub_steps 节点，非 held 状态）

```
## WORKFLOW 当前阶段
工作流: <name> | 阶段: ... | 子阶段: ...            （不变）
- 目标/允许/禁止/阶段产物/推进/技能                  （不变）
- ▶ 当前子步骤 N/6 [kind:ref]
  目的：<purpose 全文，原文不拆>
  输入：stepX.xxx ｜记录：是（落 evidence skill-trace）
- 子步骤链：1.逼问定义 ✓ → 2.拆解深挖 ✓ → 3.双向取证【当前】→ 4.质检裁决 → 5.归一化陈述 → 6.读回确认
  强制：未达上步 purpose 就进下步=违规。skill 内部 Q/A 不门控，按需 record 落 evidence。
  <STEP_SELFCHECK_HINT>                              （不变，engine 单源）
  <engagement_fence_notice>                          （不变，engine 单源）
- evidence 记录块（P2 正反例版，见 §4）
  当前子步骤 N 完成时，回复末尾单独一行输出：`### STEP_DONE: N`
（仅当 purpose 真正达成 + evidence 已写时输出 STEP_DONE）
- 子阶段块（4 行状态）                                （不变）
- 任务清单目标状态（同步原生 TaskList）：            （只留标签行 + 9 行状态数据；
  1. 理解和求证问题 -> in_progress                      删 4 行指令散文——指令已在
  ...                                                   output-style/phase-rules 双
                                                        system-prompt 通道，属跨通道重复）
```

### 2.2 设计决定

- **非当前步只留骨架短名**：短名加 `Step.short` 字段（engine 声明式数据，不采用「从 purpose 冒号前缀推导」——脆弱且隐式）。6 个短名沿用 SKILL.md 已用词表：逼问定义/拆解深挖/双向取证/质检裁决/归一化陈述/读回确认。
- **purpose 原文不拆 bullet**：曾考虑按 ①②③④ 拆行，但子1 的 ①/② 出现在句中（结论分支），机械拆分会切坏句子；可读性收益远小于瘦身收益，不冒 presentation transform 风险。
- **信息无丢失**：非当前步完整 purpose 仍在 phase-rules（system-prompt 通道，P1 后与 engine 逐字同源）；ark 等收不到 attachment 的模型走 `dl-cmd.sh status` fallback——`_cmd_progress` 本来就只输出**当前步** purpose，P0 后注入与 fallback 通道口径一致（都是当前步全文 + 全局骨架）。
- **TaskList 状态行保留**：那是 per-turn 数据（镜像目标状态随推进变化），删指令留数据。
- 预期：6,100 → **≤3,500 字符**（子4 最坏情形；典型步 ~2,600）。

## 3. P1：phase-rules 子步骤段同源渲染（改 engine + dl-launch.sh + phase-rules.md）

### 3.1 机制

- `phase-rules.md` 转为**模板**：6 条「子步骤N = …」bullet 行替换为标记段：
  ```
  <!-- BEGIN GENERATED sub_steps understand:1 -->
  （本段由 dl-launch.sh 调 dl-flow-engine.py render-phase-rules 生成，手改会被覆盖）
  <!-- END GENERATED sub_steps understand:1 -->
  ```
- engine 新增 CLI：`python3 dl-flow-engine.py render-phase-rules <模板路径>`——读模板，把每个 BEGIN/END 标记段替换为对应节点 sub_steps 的渲染行（`- **子步骤N = <ref>**：<purpose 全文>`），全文写 stdout。模板无标记段 = 原样输出（向后兼容）。
- `dl-launch.sh`：exec claude 前渲染到 per-wf 目录 `$WF_META_ROOT/phase-rules.rendered.md`，`--append-system-prompt-file` 改指渲染产物。**渲染失败（非零退出）→ 中止启动并显示 stderr**（fail loud，no silent fallback；不回退用未渲染模板——标记裸露会误导模型）。
- 渲染行只含 engine 内容（ref + purpose）；phase-rules 里该段的**运维规则**（invoke 时序「横幅后立即 invoke 不得并行」、围栏说明、evidence 强制、门控升级）留在模板静态部分——它们不是 purpose，不进 engine。

### 3.2 为什么渲染时机选 launcher 启动时（否决 install.sh 渲染）

- phase-rules.md 不被 install.sh copy（launcher 直接引用 repo 源），install 时渲染 = 把生成物写回 repo 源文件，产生「生成物提交进 git」的脏状态；
- launcher 每次启动渲染 = engine 改完**下次 `dl` 启动即生效**，无 install 依赖，与 hooks「源即生效」哲学一致；
- per-wf 渲染产物与 per-wf settings.json 同目录同生命周期（沿用「per-wf settings 非快照」既有模式）。

### 3.3 否决的替代方案（对抗性审视留痕）

1. **删 phase-rules 副本只留注入**——否。ark-code-latest 收不到 attachment（症状 D），phase-rules 是 fallback 强通道，必须自足。
2. **两通道继续手维护、靠纪律防漂移**——否。症状 F/M 两次实录证明纪律防不住（subject 编号漂移、STEP_DONE/SUB_DONE 打架），同源生成是唯一的机械保证。
3. **注入侧不瘦身、只在两通道间统一文本**——否。不解决 64% 静态重复与当前步埋没（①②），token 与注意力成本原样。

## 4. P2：正反例 + 元叙述清除（改 engine purpose/gate + 注入 evidence 块）

### 4.1 evidence 块（注入内）新格式

```
  evidence 记录（record 步必写，向 **绝对路径** `<ev_path>` 追加，每行一条 JSON）：
   模板（结构标识照抄当前值；purpose/q/a 填真实内容）：
   {"kind":"skill-trace","major_stage":"Understand","minor_stage":"ProblemContext","sub_step":3,"skill":"<ref>","purpose":"<该步目的>","q":["<q1>"],"a":["<a1>"]}
   ✓ 正例："q":["who=当前提问者身份？"],"a":["用户原话：「我是唯一维护者」（2026-07-26 会话）"]
   ✗ 反例（必 block）："q":["理解问题"],"a":["已理解"]（汇总声明非记录）；照抄 <...> 占位符字面
  写法（**必须用绝对路径**——相对路径会写到 worktree，hook 读不到）：Write（存在则先 Read 拼末尾）/ Bash `printf '...' >> <ev_path>`。写完输出 `### STEP_DONE: <n>`。
  gate 校验（end_turn 时 Stop hook 立即判）：sub_step==N 的 skill-trace 且内容达 purpose；block 则当轮返工（append 新行，勿覆盖）。
```

删：⚠️ 占位符警告行、字段逐条解释行（信息并入模板行注释 + 正反例）。q/a 数组对齐规则（q[i]↔a[i]）保留在模板行。

### 4.2 engine 文本清考古（规则留下，考古移到代码注释）

- 子3 purpose：删 `（demo fbdb6ebd 子3 实录；形式要件披露，非松判据）`、`（demo 121320fe 实录）`；规则句（反证时序可读、禁探查凭证）原文保留
- 子4 purpose：删 `（demo 实录被判 block）`、`（实录：无清单时嵌套层盲猜路径 61 次 Read 全空）`、`（嵌套放大实录：3 嵌套 116k boot + 82 Read…角色错乱）`、`（实录 11 次 No such tool）`、`（实录 21 次空拒）`；红队 prompt 四要求 a-d 的规则原文保留，考古移入 engine 代码注释（教训出处不丢，只是不进 prompt）
- 强信号合并：注入内重复禁令各留一处（如「勿覆盖 evidence」当前出现 2 次，留 1 次）

### 4.3 红线

- gate rubric 的**判据条目逐条保留**（只删考古插入语）；改动后过重放回归（§5 #4）——同一真实 trace 新旧 rubric 判决必须一致。

## 5. 实施 checklist（症状 M 六处同步 + 验证）

1. `dl-flow-engine.py`：Step 加 `short` 字段 + 6 步短名；P2 文本清理（考古→注释）；新增 `render-phase-rules` CLI；`_cmd_current` 输出加 short
2. `hooks/workflow_phase.py`：`_format_injection` P0 重排 + P2 evidence 正反例块
3. `scripts/workflow/phase-rules.md`：6 条子步骤 bullet → GENERATED 标记段；invoke 时序等运维规则收编到静态段
4. `scripts/workflow/dl-launch.sh`：exec 前渲染（失败中止启动）
5. `tests/test_dl_flow_engine.py`：short 字段断言；render 标记替换/无标记原样/未知节点报错；**rubric 关键词回归钉死**（子1 gate 含「who 类出处只认用户自述」、子3 gate 含「可追溯」、子4 gate 含「三关质检」、子5 gate 含「裁决不传导判 block」等——防 P2 清理误删判据）
6. 新建 `tests/test_workflow_phase.py`（仿 test_workflow_advance.py importlib 加载）：当前步块在骨架链之前；非当前步 purpose 全文不出现（如 cur=3 时断言子1 purpose 特征子串缺席）；骨架链含 6 短名；evidence 块含 ✓/✗；held_for_gate 分支不回归
7. `skills/workflow-creation/SKILL.md`：§1.2「改 phase-rules」生效路径更新（launcher 渲染，改 engine purpose 新启动即生效）；症状 M checklist 第 4 项改述模板+渲染机制
8. `pytest -x -q` 全绿 + `ruff check` clean
9. **冒烟实测**：真实 state 调 `_format_injection`（子3/子4 中途）——字符数 ≤3,500（基线 6,100）；真 state 喂 hook payload 跑 `render-phase-rules` 冒烟
10. **重放回归**：取 factor_ic_analyzer `.claude/evidence/demo.jsonl` 历史 trace（含 pass 终版 + block 历史版各 ≥2 条），同一 artifact 分别跑旧/新 rubric 的 run_judge，判决一致才收尾；结果记录于 commit message
11. 本设计文档状态行改「已实施」

## 6. 边界与不做的事

- 不动：Step.gate 的判据语义、sub_steps 步骤数与顺序、机械层（hash 游标/围栏/advance）、judge 调用方式、output-style 的 TaskList subject 契约
- judge prompt（run_judge 的判决载荷）本次不动——其文本已是裁剪后的最小集；rubric 瘦身收益经 §4.2 自然获得
- H9（≤3 文件/≤200 行）是 factor_ic_analyzer 项目铁律，不约束 ~/.dl-workflow；本仓库惯例 = design + 症状 M checklist（本清单 §5）
- 生效路径：hooks/engine 改完即对所有新触发生效（live 引用）；phase-rules 渲染产物仅新启动的 dl 会话加载；当前无运行中的 dl 会话（demo 在 held 状态），改动窗口安全
