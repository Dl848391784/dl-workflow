# per-instance 引擎选择设计

> 日期：2026-09-10 ｜ 状态：用户已批准（默认 claude；创建表单引擎选择=卡片式单选非下拉；机器单引擎=单选项；per-instance sticky）｜ 分支：feat/per-instance-engine
> 前置：`designs/qodercli-engine-profile-design.md`（双引擎地基，engine 当时是 server 进程级 v1 简化——本设计把它升级为实例级）

## 1. 背景与用户裁决

qodercli-engine-profile 落地后，引擎由 **dashboard server 进程 env**（`DL_ENGINE`）决定：同一 server 下所有实例同引擎，且已存在的 claude 实例在 qoder server 下被驱动会**错引擎**（段 spawn 变成 qodercli）。

用户裁决（2026-09-10）：
1. 默认 claude
2. dashboard 创建工作流时可选择 claude | qoder——**卡片式单选**（复用范围卡片的 `.mode-card` 交互，**禁下拉**）；机器上只装了一个引擎就只渲染一张卡
3. per-instance sticky：引擎记进实例 state，后续驱动/注入/resume 全链跟随实例，与 server env 解耦

## 2. 核心模型

`state.json` 新增 `engine` 字段（建实例时落，`"claude"` 默认）。**读取链 = state 优先，env 兜底**；旧实例无此字段一律按 claude（`state.get("engine", "claude")`，向后兼容零迁移）。

## 3. 改动点（5 处）

### ① state 落引擎（dl-lib.sh）

`wf_state_init` 的 state 初始化 heredoc 加 `engine` 字段，值 = launcher 已解析的引擎（dl-launch.sh 的 `DL_ENGINE` case 块产物；`dl @qoder` 建的=qodercli，否则 claude）。

### ② 读取链归一（关键设计决策）

- **dl_drive.py**：main 启动早期读 `state.engine` → 归一写回 `os.environ["DL_ENGINE"]`——之后全部 `get_engine()`（段 spawn/judge/hooks 经 harness 继承）自动跟随。**改动最小且根治「server env 错引擎驱动实例」**。
- **dl-launch.sh resume 路径**：`DL_ENGINE` 未设且 state.json 有 `engine` → 用 state 值（`dl <name> --resume` 不再需要 `@qoder` 才能接回 qoder 实例；`@qoder` 显式传入仍优先——bashrc @qoder = 新建覆盖语义保留）。
- **dashboard inject**（actions.py）：`get_engine()` 改读目标实例 state（inject 已有 project/name → load_state），不再吃 server env。

### ③ 引擎探测（dl_engine.py + dashboard API）

- `dl_engine.available_engines() -> list[str]`：`shutil.which("claude")` / `shutil.which("qodercli")`，按探测结果组列表（顺序 claude 在前）。
- dashboard 加 `GET /api/engines` → `{"engines": [...]}`，表单加载时拉取渲染卡片。

### ④ Dashboard 表单与展示

- 创建表单加「引擎」**卡片式单选组**（复用 `.mode-cards`/`.mode-card.sel` 既有交互与样式，同范围卡片）：按 `/api/engines` 渲染，默认选中 claude；单引擎机器只渲染一张卡（无选择困惑）。
- **选中 qoder 时「模型（provider）」下拉禁用**（provider=claude 系 ac-* env，qoder 不适用；切回 claude 恢复）。
- `/api/create` 接 `engine` 参数（校验 ∈ 探测列表）→ `create_workflow(..., engine=)` → launcher spawn env 传 `DL_ENGINE`。
- 实例卡片加引擎徽标（scanner 透传 `state.engine`，前端小徽章，claude/qoder 两色）。

### ⑤ hooks

零改动——经 harness 进程继承 driver env，② 的归一全覆盖。

## 4. 边界与取舍（用户已知晓）

- **qoder 模型不进表单**（YAGNI）：v1 = 向导选中的账号默认 或 server `DL_QODER_MODEL`；per-instance 模型选择等真实需求再做
- **`dl @qoder` bashrc 入口保留**：新建时显式覆盖（优先级高于默认）；resume 时 state sticky 生效

## 5. 验收与测试

- 单测：`available_engines` 探测矩阵 / state 默认 claude / drive 归一（state=qodercli → 段 cmd=qodercli）/ inject 读 state
- bash 冒烟：dl-launch resume sticky（无 DL_ENGINE 环境变量接 qoder 实例起 qodercli）
- dashboard 测试：/api/engines、/api/create 引擎校验与传递、表单渲染逻辑
- **实机 E2E**：dashboard 建 qoder 实例 → `state.engine=qodercli` → driver spawn=qodercli（进程 argv 实证）；claude 实例在 qoder server 下被驱动**不串引擎**（② 的修复点）；无 env `dl <name> --resume` 接 qoder 实例保持 qoder

## 6. 风险

| 风险 | 缓解 |
|---|---|
| drive 归一写 env 影响同进程其它逻辑 | DL_ENGINE 只被引擎分路消费，无其它读者；归一写在最早期 |
| 旧实例（无 engine 字段）行为漂移 | 读侧一律 default claude = 现状 |
| 前端卡片交互与 scope 卡片冲突 | 独立卡片组 id（engine-cards），复用 class 不共享状态 |
