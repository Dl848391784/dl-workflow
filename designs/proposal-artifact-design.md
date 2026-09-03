# proposal.md 人读技术方案产物设计（proposal-artifact）

> 2026-09-02。动机（用户决议 2026-09-02「对的」确认方向）：现有 plan.md 是机器执行
> spec（change_point 五要素/ARTIFACT_CONTAINS 门检），密文格式对模型是优点、对人是
> 灾难——人读技术方案需要标准文档骨架。trace 里 8/11 环节的内容已存在，缺的是
> **面向人的装配目标**。新增第三种产物 `proposal.md`：同一份 evidence trace、
> render-artifact 机械装配、标准技术方案章节，plan.md/understand.md 一字不动。

## 1. 产物定位与边界

- 产出：`<project>/.claude/proposals/<name>.md` + 伴随 `<name>.html`（v0.3.0
  _render_html_companion 对任意 md 生效，天然覆盖）。
- **不做门检**：proposal 不进 ARTIFACT_SECTIONS（三通道单源只服务门检产物），
  ARTIFACT_CONTAINS / change_point 机械门零影响；judge 不读它（下游读 evidence）。
- **不改采集**：v1 全部章节从既有 trace 装配，零节点零 prompt 改动；无源节
  诚实占位（「本节源步未执行」/ TACET 沉默占位，同 understand/plan 机制）。

## 2. 章节 ↔ trace 源映射（全部经实证核对）

证据基：amplitude_annualized / interaction_amplitude__ret3d_pos_annualized（全量轨）
+ web_interaction_amplitude_ret3d_abs（tacet 轨）三个真实 evidence jsonl 的
(minor_stage, sub_step, S/Q) 全清单。S=归一化 statements 步，Q=qa 步。

| 章节 | 源 | 形态 |
|---|---|---|
| 背景与根因 | ProblemContext 子6（S）+ ProblemContext 子3 qa 中含「根因@」的项 | statements + qa 筛选 |
| 目标与成功标准 | GoalsAndValue 子4（S）+ SuccessCriteria 子4（S） | statements |
| 范围与非目标 | ScopeAndConstraints 子4（S）+ 同 minor qa 中含「搁置」的项（双向矩阵的显式搁置=非目标） | statements + qa 筛选 |
| 方案概述 | DesignSolution 子5（S，方案归一化步） | statements |
| 方案对比与取舍 | DesignSolution 子4 qa 全量（Pugh 矩阵逐格评分+理由=对比本体）+ DesignSolution 全步 qa 中含「剔除/证伪/未选定」的项 | qa |
| 改动面 | TaskBreakdown 子4（S，与 plan.md 执行步骤同源；change_point 字段原文携带） | statements |
| 风险与不可逆操作 | ExecutionPlanCheckpoints qa 中含「假设/不可逆/回滚/风险」的项（子1 五类清单含假设清单汇总+不可逆操作候选，是现成风险材料） | qa 筛选 |
| 实施计划与检查点 | ExecutionPlanCheckpoints 子4（S，与 plan.md 检查点节同源） | statements |
| 裁决记录 | 全部读回步 qa 含「裁决/读回」（复用现有 decisions 机制，步集=understand 四读回 + plan 四读回） | qa 筛选 |
| 开放问题与接续 | understand 四 minor qa 含「剔除/未选定/开放」（复用 understand.md
  unselected_minors 机制同步集） | qa 筛选 |

**收录去重（防同一 trace 两节重复）**：DesignSolution 的剔除/未选定项只进
「方案对比与取舍」不进「开放问题」（方案候选的取舍是方案叙事一部分）；
ScopeAndConstraints 的「搁置」项只进「范围与非目标」（范围叙事），其剔除/未选定
项才进「开放问题」。

**v1 不单设「现状分析」与「测试与验收」节**：现状机制=根因节承载（机制一句话就是
现状到 bug 的因果）；测试验收与「目标与成功标准」（验收包六字段）和「改动面」
（verify=RED/GREEN 字段原文携带）源重复，单设=同一内容两处渲染。

**源缺省处理**：require_all=False（同 plan.md）——statements 源步无 trace →
跳过该节并在返回消息点名；源步是 tacet 沉默 → 节内落「TACET 沉默」占位（statements
节复用现有机制，qa 节同款新增）；qa 筛选节零匹配 → 节不落、消息点名。
**整份零节可装（如纯 tacet 早期）→ 仍落文件**（各节占位/空注记如实呈现，人能看到
「这个实例跑到哪、哪些没跑」，这正是人读版的价值）。

## 3. 装配触发（piggyback，零节点改动）

render-artifact 的调用面（模型装配步注入 + apply_tacet_skip 代跑）不变：

- `render-artifact understand.md` 成功 → 顺带渲染 proposal.md（understand 侧章节就绪，
  plan 侧节缺源点名）
- `render-artifact plan.md` 成功（plan:2/3/4 每次增量装配）→ 顺带重渲染 proposal.md
  （幂等覆盖，逐步长全）
- `render-artifact proposal.md` 直接调用也支持（手动补渲/存量回填入口；piggyback
  只对 understand/plan 触发，proposal 自身不递归）
- 返回消息尾部附 `；proposal ✓ <path>` 或 `；proposal 降级：<原因>`——proposal 是
  人读赠品，渲染失败绝不阻断主产物（与 HTML 赠品同纪律，两级赠品独立降级）

## 4. 装配实现（render_artifact 扩展）

`_ARTIFACT_RENDER_SOURCES` 加 `proposal.md`：sections 复用现有 statements 渲染循环；
新增两类节源——`qa_sections`（含关键词筛选的 qa 收录节）与 decisions/unselected
步集参数化。out_dir="proposals"。piggyback 在 render_artifact 成功 return 前
（HTML companion 调用后）对 understand/plan 触发内部 render_proposal 调用。
CLI 用法文案与不支持报错名单同步加 proposal.md。

## 5. dashboard 配套（第三 kind）

- `outputs.artifact_status` / `load_artifact` / `/artifact-html` 三处 kind 白名单
  +`"proposals"`（html_exists/html_size 同两态）。
- `app.js`：ART_PHASE proposals→plan（挂载点=plan 阶段最后可见节点，与 plans 并列
  两链接）；ART_LABEL proposals={html:"proposal.html", md:"proposal.md"}。
  plan.html（执行 spec 渲染版）与 proposal.html（技术方案）并存，标签区分。

## 6. 测试

1. 全源 → 10 节齐 + 根因 qa 收录 + Pugh 节收录 + 裁决/开放问题节。
2. 部分源（只 understand 侧）→ plan 侧节缺省点名、消息可见。
3. tacet 沉默源步 → 占位节（statements 节 + qa 节同款）。
4. piggyback：render plan.md → proposals/t.md 落盘 + 消息附注；render proposal.md
   自身不递归。
5. dashboard：artifact_status proposals 两态 + /artifact-html proposals 200/404/400。
6. 契约对齐：render-artifact 不支持名单报错/CLI 文案测试随新名单更新
   （test_unsupported_basename_rejected 等，属对齐非回归）。
7. conftest HTML 桩默认屏蔽赠品层（既有机制），proposal html 走专项。

## 7. 配套与收口

- VERSION 0.3.0 → 0.4.0；README 产物段补 proposals；pack.sh 无新增（engine/测试随库）。
- 存量回填：merge 后对 9 个实例跑 `render-artifact <name> proposal.md`，
  产 proposals/*.md+html。
- 不做什么：不改任何节点/prompt/gate；不加「现状分析」「测试与验收」独立节
  （§2 理由）；不给 proposal 做 judge/门检；dashboard 不加批量重转按钮。

## 8. 风险

- qa 筛选关键词（根因@/剔除/Pugh 等）漏收或误收 → 节内容偏少/杂。缓解：关键词
  全集在 design 钉死、测试用真实 trace 形态（根因@ 语法有 _ROOT_CAUSE_LINE_RULE
  单源、Pugh 是子4 形式要件）锚定；v1 宁纵（多收强于漏收，人可读时跳过）。
- piggyback 让 render-artifact 变慢（多一次装配+一次 bun）→ 节点边界频率低，
  可接受；proposal 渲染自身失败独立降级不影响主产物墙钟。

---

## 修订（v0.7.0，2026-09-03 用户裁决）：收敛为两部分

人读技术方案文档**只含两部分**：①调用流程（渲染层自 interface= 字段推导 SVG）
②代码改动面（渲染层把 change_point= 字段升 dashboard 同款卡片）。§2 的 10 节
骨架全部裁撤——陈述正文不进人读文档（仍留 evidence/plan.md 机器真源，零信息
丢失）。装配侧：改动面节从 TaskBreakdown 子4 statements 只提取
change_point/interface 字段（`_emit_stmts` fields_only）；piggyback/TACET 占位/
缺源点名机制不变。§2 表格保留作历史记录。
