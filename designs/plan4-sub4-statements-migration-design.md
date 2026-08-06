# plan:4#4 归一化计划包 statements 迁移设计（v2.119）

> v2.33 三归一化步迁 statements+statement_fields（`plan-normalization-statements-migration-design.md`）的**漏网补齐**——第九处归一化步（plan:4 子4）当时未迁，2026-08-06 tail_volume_acceleration_annualized live 全轮首达 plan:4#5 实爆。

## 事故链（生产实证，2026-08-06 12:29:31 block）

1. `_ARTIFACT_RENDER_SOURCES["plan.md"]` 把「执行计划与检查点」节映射到 `(ExecutionPlanCheckpoints, 4)`，`render_artifact` 只读 trace 的 `statements` 字段；
2. plan:4#4「归一化计划包」注释自称「claim normalization 职能第九次复用」，但 v2.33 只迁了 plan:1子5/plan:2子4/plan:3子5 三处（+understand 四处于 v2.36 补齐），**plan:4#4 漏迁**——Step 无 `record_format` 声明，走默认 qa；
3. qa trace 无 `statements` → render-artifact「跳过缺源节：执行计划与检查点」→ plan:4 门栏 `ARTIFACT_CONTAINS` 永远缺节 → **结构性不可通过**（模型行为全程合规，系统给了不可能任务）；
4. 为何活到 v2.118：plan 族节点编排落地后无一轮 live 全轮抵达 plan:4#5（历史 episode 全是 understand 判据试验床），重放测试不经过 render-artifact——**迁移类漏网只对 live 全轮可见**。

## 修复（照 v2.33 兄弟步 pattern，零新增机制）

引擎侧全通用（scaffold/append 校验/注入格式说明/渲染全按 `step.record_format` 分派），**唯一生产改动在 `dl_flow_nodes.py` plan:4#4 Step**：

- `record_format="statements"`；
- `statement_fields` 十键 = 消费契约倒推的十字段（design §0 表原定）：
  - 调度四：`parallel_group` / `mutex_surface` / `worker_map` / `return_contract`
  - 检查点六：`cp_position` / `cp_criterion` / `cp_failure_route` / `cp_type` / `cp_acceptance_map` / `cp_goal_anchor`
  - 逐项十键逐键非空（append-trace 机械校验缺键即拒）；调度项 cp_* 六键、检查点项调度四键填显式「无」（plan:3#5「无内容键填显式『无』」同规）；
- purpose 增载荷格式段 + text 只留单句纪律（改动文件/判据命令/签名进 fields——方案名词扫描同源，plan:2#4「file:line/签名进 fields/boundary」同款）；
- selfcheck 十字段问句改 fields 十键机械校验提醒；
- gate 三处对齐迁移后形态（判据内容实质不动）：
  1. 形式要件段：加 statements 形态声明（无 q/a 字段是生产形态，不得以此 block）+ fields 十键已机械校验勿再数字段（plan:3#5 gate 同款）；
  2. 判据二复合句检测：「提取 statements 每项 text」（plan:2#4 判据三同款）；
  3. 合法正例「W2->T2（...）」加 `worker_map:` 前缀（字段归属准确化）。

## 不做（surgical 边界）

- 不加新 mech_checks：判据四（triggered 验收项漏配）在本轮 live 由 judge 正确拦截并一轮收敛，留 judge；sc_coverage_trace 式下沉是独立项；
- 不动 render/append/scaffold/readback 任何引擎代码（全 record_format 驱动，自动生效）；
- 不改判据一/三/四措辞（语义判据未动，无需重放——载荷格式整体变更，旧 qa 载荷对新格式无重放意义）。

## 验证

- 声明断言：plan:4#4 record_format/statement_fields 十键（镜像 v2.33 `_MIGRATED` 测试）；
- append-trace：缺 fields 对象拒 / 缺单键拒并点名 / 十键齐备（调度项 cp_* 填「无」）过；
- **render-artifact 回归钉**：EPC 子4 statements trace → plan.md 装出「## 执行计划与检查点」节（事故直接回归）；qa trace → 仍跳节（旧 bug 形态反钉）；
- 全量 pytest + ruff。

## 续跑指引（merge 后）

工作流会话内 `/dl state-reset plan:4:4`（子4/子5 trace 作废含三裁决，需重问）→ 续轮子4 以 statements 重做 → 子5 render 装配 → 门栏 `/dl gate` ×2 → execute。hooks 直读 `~/.dl-workflow` 源，merge 即生效；phase-rules resume 重渲染，purpose 变更即生效。
