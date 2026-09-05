# dl setup 安装器设计（setup = dl-workflow 的安装包）

> 2026-09-05。来源：用户目标「启动 setup 脚本，逐个把 dl-workflow 用到的所有插件和依赖装好——包括 codegraph init、蒸馏器初始化；执行完 setup 后 dl-workflow 直接能跑且效果一样；setup 就是 dl-workflow 的安装包」。
> 上游：factor_ic_analyzer 约定蒸馏层一期（dffe1d1..4a21d01，designs/convention_mining_design.md）——本设计的蒸馏层通用化以其为蓝本。

## 问题与定位

dl-workflow 的运行环境目前靠手工考古装配，资产散落四处、换机即丢：

| 资产 | 现状 | 层 |
|---|---|---|
| codegraph CLI | npm 手工装（须记得 npmmirror 镜像） | 机器级 |
| codegraph db 索引 + post-commit sync | 手改 `.git/hooks/post-commit`（不入库） | 项目级 |
| inject hook 注册（codegraph/conventions） | 手改 settings.json（被 `*.json` 忽略） | 项目级 |
| codegraph_gate/audit hooks | 手装 `~/.claude/hooks/` | 机器级 |
| cgx/cvx/distiller 脚本 | 各项目仓内 vendor（试验田模式） | 项目级 |

**定位**：`dl setup` = dl-workflow 的安装包。裸机跑一条命令 → 机器级+项目级全部装齐并自检 → dl-workflow 直接可跑，效果与手工装配等价（等价 = 可验收，非感觉）。

## 关键决策（用户已拍板）

1. **范围**：蒸馏层随 setup 通用化安装（非仅通用层）。
2. **脚本归属**：通用脚本集中 `~/.dl-workflow/`（dl 升级一处生效）；项目仓只留 `conventions.yaml`（规则声明，入库）；hook 用绝对路径引用 `~/.dl-workflow/` 内脚本。
3. **规则类型库 v1**：四类 checker 内置参数化（path_literal_scan / logging_style / layering / skeleton）+ util_graph（codegraph 驱动），一类型一函数，为插件化预留但不开放外部插件。

## 资产分布

| 层 | 资产 | 位置 | 维护者 |
|---|---|---|---|
| 机器级 | codegraph CLI、codegraph_gate/audit hooks、通用脚本（cgx/cvx/distiller/checker 库） | `~/.dl-workflow/` + `~/.npm-global/` + `~/.claude/hooks/` | dl 升级 |
| 项目级 | `conventions.yaml`、`.codegraph/`、`.conventions/` | 项目仓（yaml 入库，产物 gitignore） | 项目 |
| 接线 | settings.json 两条 UserPromptSubmit 注册、post-commit 双后台任务 | 项目本地（不入库，setup 幂等重建） | dl setup |

## conventions.yaml schema（通用化核心）

蒸馏器只认 type+params；规则文本（statement）项目自写；doc_declared 型规则实证冲突仍标 drift——「不裁决只呈证」语义原样保留：

```yaml
rules:
  - id: H7_path_literal
    type: path_literal_scan
    statement: "路径只能 from paths import"
    params: {exempt_files: [paths.py], preset: abs_unix_path}
  - id: H11_log_style
    type: logging_style
    statement: "日志 % 惰性禁 f-string"
    params: {fstring_regex: '...', lazy_regex: '...%[srda]...'}
  - id: H1_layering
    type: layering
    statement: "模块边界：web_ui 只读后端"
    params: {forbidden: [{from: "*", to: web_ui}]}
  - id: scripts_skeleton
    type: skeleton
    statement: "scripts/ 族骨架模式"
    params: {glob: "scripts/*.py", exclude_name_prefix: [test_],
             traits: {argparse: "import argparse", main函数: "def main("}}
  - id: util_graph
    type: util_graph
    params: {target_files: [paths.py]}
```

无 yaml 或无 rules → 只跑 code_evidence 维度（import 图/骨架降级为纯事实）。

## setup 脚本结构（分阶段、逐项装、逐项验）

每组件 = 检查→安装→验证三小步；失败即停并报缺失项（不静默跳过）：

- **阶段0 前置检查**：claude CLI / git / python3≥3.11 / node+npm 存在性；缺则指引（不代装系统包）。
- **阶段1 机器级**：① codegraph CLI（npm+npmmirror 钉死，`codegraph --version` 验证）② gate/audit hooks → `~/.claude/hooks/`（权限位+JSON 解析验证）③ 通用工具链 → `~/.dl-workflow/bin/`（cgx/cvx/distiller/checker 库）。
- **阶段2 项目级**（目标项目目录内执行）：④ `codegraph init`+首次 index（新鲜度验证）⑤ post-commit 双后台任务（codegraph sync + distiller 重挖）⑥ settings.json 两条 hook 幂等补丁（JSON 验证）⑦ conventions.yaml 缺则 `--init` 生成注释模板；存在则跑首次蒸馏。
- **阶段3 等价自检**：模拟 UserPromptSubmit payload 过两个 inject hook 验证注入文本；`cvx drift` 可查；`codegraph callers` 真实 symbol 有结果 → 逐项 ✅ 清单。

**「效果一样」操作化** = 阶段3清单全绿：新会话提问收到 codegraph+约定双瘦档；gate hook 拦/放行为一致；post-commit 自动维护两索引。

## 分期落地

- **P1 安装器骨架+通用层**：setup 脚本 + 阶段0/1/2④⑤⑥ + 阶段3基础自检。**自举验证 = 本仓（factor_ic_analyzer）拆装重建**：拆掉当前手工装的注册/post-commit/hooks → 跑 setup 重建 → 清单全绿。
- **P2 蒸馏层通用化**：checker 四类型参数化 + yaml schema 落地 + 本仓规则迁 yaml（仓内蒸馏器副本退役，切 `~/.dl-workflow` 版）。

## 验收

1. 全新模拟环境（容器/新用户）裸跑 setup 全绿。
2. 幂等：连跑两次，第二次全 `already-ok`。
3. 自举：本仓拆装重建后行为一致——注入文本、drift 数字与手工期基准一致（H7 3文件/H11 1处f-string）。

### P1 自举记录（2026-09-05，factor_ic_analyzer 实仓拆装重建）

**过程**（备份 `/tmp/fac_settings_backup.json` + `/tmp/fac_postcommit_backup` 后）：

1. 基线：`scripts/cvx.py drift` → H7（n=442, 合规率 0.99, 3 证据文件）+ H11（n=942, 合规率 1.00, 1 处 f-string）。
2. 拆手工接线：settings.json 精确摘除两条 inject 注册（UserPromptSubmit 摘空为 `[]`，其余保留）；post-commit 重写为最小 codegraph-only 版。
3. 跑集中版：`setup_project.py --project <factor> --home <worktree> --skip-index`。
   - **实爆 1 个真 bug**：`merge_project_settings` 对「键在但组摘空」的 `UserPromptSubmit: []` 取 `groups[0]` IndexError（`setdefault` 默认值只对缺键生效）。修复=空列表自建承载组 + 回归测试 `test_merge_project_settings_empty_event_list`（commit 4c911df）。这正是自举验证的价值——tmp repo 测试只覆盖了缺键/有组两态。
4. 重跑全绿：`post-commit: already-ok`、`settings added=2 kept=0`、首次蒸馏 8 条（drift 2）。

**等价验收**：

- 集中版 `hooks/conventions_inject.py`（cwd payload 冒烟）→ 漂移注入 JSON，H7/H11 在列，n 与合规率与基线一致。
- 集中版 `bin/cvx.py --db <repo>/.conventions/conventions.db drift` 输出与基线**全文一致**（subject 级 diff 为空，全文 diff 亦为空）。
- settings.json 注册指向 worktree 绝对路径（`--home <worktree>` 预期行为）；post-commit 为双后台任务块（绝对路径禁静默失效）。

**收口注意**：Task 5 收口 merge 回 main 后须重跑一次 `--project <factor> --home ~/.dl-workflow`，把 factor settings.json 里的注册路径从 worktree 换回 canonical 家。

## 风险

- npm 全局目录多会话竞争（既有记忆）：装 codegraph 时查残留 npm 进程。
- settings.json 幂等补丁需容忍用户已有自定义 hook（只增不删、按命令串判重）。
- 通用蒸馏器 Python 预设面向 Python 项目；Java 等语言的 checker 预设属 P3+，v1 在 README 明示边界。
