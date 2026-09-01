# design.md 装配退役设计（H8 按路径分流：dl-workflow 驱动改动豁免）

> 状态：待实施
> 触发：web_ui_interaction 2026-09-01 卡死实爆 + 用户裁决（同日）

## 0. 动因

1. **实爆**：08-28 tacet 轮 `designs/web_ui_interaction-design.md` 占位 stub 删漏残留 → 08-31 新实例 plan:1#6 确认级装配撞拒覆盖 → driver 断点退出 → dashboard 无确认卡（卡唯一来源 = driver 跑交互段 stash need_user.json，#6 未跑到）。
2. **根因层**：`designs/` 落点逃工作流生命周期——删除清单只覆盖 worktree/分支/元数据 + `.claude/` 域 plans/understands/evidence，孤儿 stub 无归属校验。
3. **用户裁决（2026-09-01）**：design.md 工作流内部零消费（下游 judge 读 evidence 不读 design.md 文件——`design-solution-substeps-design.md` §3 实现注）；其唯一消费者是项目侧 H8/CI/人类考古。dl-workflow 自身机制（evidence 链 + 读回裁决 + 机械门）已是 H8「动手前想清楚并留痕」的超集，再要 design.md = 重复征税。**决议：H8 按路径分流——dl-workflow 驱动改动豁免 design.md；非工作流改动仍须遵守 H8/CI/pre-commit。**

## 1. 决议细则

- dl-workflow **摘除 design.md 装配**：plan:1#6 确认级不再有产物装配义务；render-artifact 删 design.md 支持。
- **读回确认步本身保留**：render-readback 展示 + 用户三裁决入 trace（`user_decision_recorded` 机械校验不动）——裁决留痕在 evidence，随工作流生死（用户已接受）。
- understand.md / plan.md **不动**（`.claude/` 域、工作流内部契约、下游 judge 真实消费）。
- factor_ic_analyzer 侧 H8 同步修订为分流规则（防僵尸规则）。

## 2. dl-workflow 改动面

1. `dl_flow_engine.py`：
   - `confirm_artifact`（:1385）：删 plan:1 → design.md 分支（保留 understand.md/plan.md 直出）。tacet 装配路径（:1567）同源自动跟随。
   - `render-artifact`：删 design.md 分支整体（`_ARTIFACT_RENDER_SOURCES["design.md"]` spec、slug 校验、拒覆盖逻辑、CLI `--slug`/`--force` 参数）。**全删不保留**——摘除编排调用后该分支即死代码（H13）。
2. `dl_flow_nodes.py` plan:1 子6（:3195-3225）：ref/purpose/selfcheck 删 design.md 装配义务文案，保留读回 + 三裁决 + 裁决入 trace。
3. `hooks/workflow_phase.py:55`：plan 阶段 allow 文案删「起草 design.md(H8)」。
4. `scripts/workflow/phase-rules.md`：:91 子6 装配义务段删；:131 同步；:44 写围栏白名单 `designs/*.md` **保留**（白名单宽无副作用；非工作流 H8 场景手动写 design.md 不被拦）。
5. tests：confirm_artifact / render-artifact design.md 相关用例同步删改。
6. workflow-creation skill 文档涉 design.md 处同步。

## 3. factor_ic_analyzer 改动面

1. PROJECT.md：H8 修订为「非工作流改动 2+ 文件先写 design.md；dl-workflow 驱动改动豁免（evidence 链 + 读回裁决即 Design-First 等价物，随工作流归档/删除）」；§目录结构 :357/:419 与 CI 检查描述 :432-440 同步。
2. `scripts/check_design_first.py`：wf/\* 分支豁免（dl-workflow 产物分支前缀即检测信号）。
3. pre-commit 软提示：同豁免。
4. CLAUDE.md §5 H8 指针行同步一句话。
5. 删孤儿 stub `designs/web_ui_interaction-design.md`（本次事故残留，8 行占位无有效内容，已 Read 核实）。

## 4. 否决的替代方案

| # | 方案 | 否决理由 |
|---|---|---|
| 1 | 保留装配，落点改 `.claude/` 域 | 用户裁决不要产物本身（「工作流又用不到它」）；保留 = 白付装配 + 维护成本 |
| 2 | design.md 内容并入 plan.md 一节 | plan.md 是执行契约（execute rubric 逐条核），混入决策叙事稀释契约；且打破 fermate 模式 plan.md 只「执行步骤」一节的定位 |
| 3 | 只删 stub 不改系统 | 接缝仍在，下次同名/删除场景复发 |
| 4 | H8 全退（非工作流改动也豁免） | 用户明确保留：非工作流改动没有 evidence 链兜底，H8 是唯一防线 |

## 5. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 在飞实例（web_ui_interaction）引擎热切换：confirm_artifact 变 None → plan:1#6 跳过装配静默通过 | 该步 gate=None，剩 render-readback 展示 + write_confirm_trace 均为既有路径；stub 顺手删了即使走旧码也不撞；restart driver 即自愈 |
| 决策溯源随 `dl --delete` 消失 | 用户已裁决接受；`--done` 归档路径仍留元数据 + evidence 可回看 |
| 其他项目此前依赖 design.md 产物 | plan:1 节点本就锚定本项目 H8 约定（design-solution-substeps-design:12 明引 H8）；其他项目从未有该消费约定，摘除无下游断裂 |

## 6. 实施 checklist

1. engine：confirm_artifact + render-artifact design.md 分支 + CLI 参数摘除
2. nodes：plan:1 子6 文案
3. hook workflow_phase:55 + phase-rules.md:91/:131
4. tests 同步删改
5. skill 文档同步
6. 项目侧 PROJECT.md / CLAUDE.md / check_design_first.py / pre-commit
7. 删 stub + restart driver 救活 web_ui_interaction（验证：plan:1#6 静默通过进 plan:2）
8. dl-workflow 仓 pytest 全绿 + 项目仓 ruff
