# 蒸馏层接线进工作流设计（cvx-wiring）

> 2026-09-10。来源：用户追问「蒸馏了但我们没用，蒸馏的意义是什么」——查证发现蒸馏层目标消费者（dl 工作流）结构性收不到蒸馏产出。用户裁决（AskUserQuestion）：走完整方案（被动注册 + 编排消费点）。验证方式用户指定：ac-deepseek1 跑测试工作流 E2E，直到蒸馏产物对准确性/效率的收益被实证。

## 根因（已查证）

1. **被动通道断**：`conventions_inject.py`/`codegraph_inject.py` 只注册在主项目 `.claude/settings.json`（setup_project.py:75）；dl 会话 cwd=worktree，worktree 内无 project settings.json（.gitignore `*.json` 未入库，dl-lib.sh:211 注释自证），per-wf settings 只登 workflow 4 hook + codegraph gate/audit。旧假设「inject 由项目自己注册即可」（dl-lib.sh:220 注释）在 worktree 场景不成立。实证：5 个 worktree 会话 transcript 均无蒸馏注入标记。
2. **主动通道零引用**：`dl_flow_nodes.py` 44 步 purpose/gate grep 无任何 cvx/conventions；cvx 只挂 CLAUDE.md §3，且 plan:1#1 等段 `segment_strip_project_context=True` 剥掉项目上下文后模型连 cvx 存在都不知道。
3. hook 本体均已 worktree-ready（`_map_worktree_to_main` 反查主仓 db，无 db 静默退出）——缺的只是注册与引用。冒烟实证：以 worktree cwd 喂 payload，conventions_inject 正常注入漂移瘦档；codegraph_inject 正常走 `no_idents` 静默（prompt 驱动，非 worktree 问题）。

## 方案（三层）

- **Layer1 被动通道**：`wf_write_settings` 模板 UserPromptSubmit 补登 codegraph_inject + conventions_inject（覆盖全部 44 步零编排改动）；`SETTINGS_TEMPLATE_VERSION` 11→12（存量实例 `--resume` 补写自愈）；test_dl_launch_engine.sh 补断言。
- **Layer2 主动引用（4 决策点，资源指针式、不进 gate 判据）**：
  - u:1#4 双向取证 ③内部仓库层：cvx drift 查活跃漂移点，漂移区机制并列呈证；
  - plan:1#1 现状勘察：cvx drift/query 作约定层勘察（无命中零成本跳过，不占配额）；
  - plan:3#2 能力盘点 ②：仓内共享工具/写法约定查 cvx query；
  - review:0 gate_rubric：软指针「改动面涉及已知约定/漂移区时对照 cvx drift（有则引，无则免）」——非 block 要件。
  - 刻意不引：u:1#3（信号由子4 兜住）、evolution（等第一起真实「违反约定」失败案例，守设计文档「失败案例驱动，不一次铺满」）。
- **Layer3 全局软引用**：phase-rules.md 总则加一行（execute 动手前/review 审核时查 cvx drift），覆盖无子步骤编排的整阶段节点。

## 边界与风险

- 不加 gate 要件（判据加要件=thrash 风险，judge framing 教训在案）；purpose 改动走镜像重放确认 gate 行为零漂移。
- cvx 在无 db 项目静默退出（setup 未装的项目零副作用）。
- 配套同步：nodes-index.md 摘要块（改 purpose 实质内容后的既有纪律）。

## 验证

1. `bash tests/test_dl_launch_engine.sh` + dl-workflow pytest 全绿。
2. 镜像重放（build-and-modify §1.6）：purpose 改动节点 gate 行为与基线一致。
3. ac-deepseek1 真实实例 E2E（用户指定）：逐段验 ①漂移瘦档注入到达 ②4 决策点实际用 cvx ③准确性/效率收益留痕。

## 验收记录（2026-09-10 回填，ac-deepseek1 / deepseek-v4-flash 全量 44 步实例 cvx_wiring_e2e）

测试任务：H7 路径硬编码排查整改（漂移点天然相关）。全程 5 阶段跑完 gate=done。

**三层接线验证**：
1. Layer1：per-wf settings v12（三 UPS hook 在场）；段 transcript 实证蒸馏瘦档+codegraph 注入到达（此前 5 实例零注入）。
2. Layer2：u:1#1 模型把漂移点当证据写进问题结论（「已被一次既有扫描初步证实」）；u:1#4 模型按指针跑 cvx drift；plan:1#1 trace 载 cvx drift 原始输出+file:line 证据；plan:3#2 cvx 入能力注册表（CLAUDE.md §3 行逐字引用）；review must1/SC1/SC6 全部以 cvx drift 计数为验收信号。
3. Layer3：execute 段 cvx.py drift 调用留痕（×4）。

**收益实证**：
- 准确性①：plan.md change_point 与蒸馏漂移 evidence file:line 精确一致（两违规文件行号零搜索成本）。
- 准确性②：review 以蒸馏信号抓回「整改自引入违规」（check_path_import.py:55 ABSOLUTE_PATH_PREFIXES 自指命中，计数 2→1 未归零）——没有蒸馏层该回归必漏。review 诚实判 partial 非放水。
- 准确性③：u:1#3 发现蒸馏快照（2）vs 实测（≥3）不一致——蒸馏层自身的口径缺口被并列呈证流程暴露。
- 效率：漂移点 file:line 零成本直达 vs 全仓 grep 考古。

**E2E 抓出并修复的真 bug**：cvx CLI 相对路径解析 db——工作流段 cwd=worktree 报「无 db」，模型误记「无活跃漂移点」。修=_resolve_db git 反查+linked worktree 映射主仓（commit 8915b7a，TDD 4 例）。

**已知边界**：
- 蒸馏 db 跟随主仓 commit 重挖；worktree 分支内改动在合并前不反映进 db（review 的「生效态」是模型在 worktree 上重跑 checker 所得，非 db 直读）。
- 实例 review 判 partial（H7 整改余 1 处自指违规，解法见 memory rule-checker-self-hit）——属任务侧未完，非接线缺陷；分支 wf/cvx_wiring_e2e 未合并，是否推进归零由用户裁决。
- 驱动运维事故一次：我（主会话）用 timeout 探针杀 driver 致 execute 双段并发孤儿，已按 #25 处置（杀孤儿+干净重 drive）；教训=driver 探针禁 timeout 强杀。
