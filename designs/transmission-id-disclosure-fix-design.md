# 传导幽灵 ID + 拒绝文案披露缺口修复设计

> 触发：web_ui_interaction 工作流 understand:2 子4（归一化陈述）耗时 733s 审计。
> 根因已于主仓会话与用户确认（2026-09-01），立项修复。改动仓：~/.dl-workflow（worktree feat/transmission-id-fix）。

## 1. 问题（实爆证据）

web_ui_interaction u:2#4（归一化陈述，statements 格式步）5 次提交 4 次被拒，同一句报错
「源步（子3）条目未逐项传导，缺：#2、#3」。733s 中约 10 分钟为打地鼠纯税，模型靠 grep
其他实例（ma5_slope 等）evidence 反推被接受的格式才过。

两层根因（均系统侧）：

1. **幽灵 ID 提取**：`_ID_RE` 的 `#[0-9]` 分支无左边界，把子3 trace 里的引注噪声
   `出处：need_user.json Q1a、sources#2#3`（`#` 前紧跟 ASCII 字母/数字）抽成「源步条目
   编号」→ 产生不存在的传导义务。子3 全程无真实 `#N` 条目编号。
2. **报错教不会**（#54 打地鼠分诊=披露缺口）：拒绝文案只说「逐条补或显式标注剔除理由」，
   不披露 ①缺传 ID 的源文出处 ②传导判定规则（字面包含于 text/boundary/fields）
   ③合法标注形态（「承接 X」/「X 剔除：理由」）。

同实例 u:4#4 二次重演（~17 分钟），属 statements 步系统性披露面问题，非孤例。

## 2. 方案

### 2.1 ID 提取精度（dl_flow_checks.py `_ID_RE`）

`#N` 分支加否定左环视 `(?<![A-Za-z0-9_])`：`#` 前紧跟 ASCII 字母/数字/下划线 = 引注噪声
（sources#2#3 / task#12），不产生传导义务；枚举位（行首/空白/斜杠/顿号/CJK 前）的 `#N`
不受影响。设计原则：传导义务只由「声明式编号」产生，引注参照不产生义务。
与既有 `[UT]\d+` 分支的边界处理同范式。

### 2.2 拒绝文案披露（dl_flow_trace.py append_trace + dl_flow_checks.py 新增 `_step_trace_id_contexts`）

- 新增 `_step_trace_id_contexts()`：`_step_trace_ids` 的披露版，每个 ID 附源文 ±24 字片段；
  抽出共用 `_step_trace_text()`，`_step_trace_ids` 改由 contexts 派生（签名不变，单源）。
- 拒绝文案改为：缺传清单 + 每项源文出处 + 判定规则（编号字面出现在任一 statement 的
  text/boundary/fields 即算传导）+ 合法形态（「承接 X」/「X 剔除：理由」）+ 引注噪声处置
  （按剔除标注并写明源出处）。

### 2.3 scaffold 披露前置（dl_flow_trace.py scaffold_payload）

statements 步且源步有 ID 时，--scaffold 成功消息预印传导要件（源步号 + ID 清单 + 合法形态）。
打地鼠成本 ≈ (提交数-1) × 全上下文重交，首次提交前披露是零成本出口。

## 3. 影响面与验收

- codegraph impact：`_step_trace_ids` → append_trace + engine main；`_ID_RE` 无外部 caller；
  `scaffold_payload` → engine main。无 hook/注入文案改动，phase-rules 不涉及。
- 行为变更：引注噪声不再产生传导义务（有意）；真实枚举位编号行为不变。
  降级语义不变：源步无 ID → 核对空转，judge 语义判据（传导断裂族）仍兜底。
- 验收（TDD，先 RED 已证实 4 失败）：
  1. `_ID_RE` 单测：sources#2#3/task#12 不抽取；枚举位 #1/#2a/#2/#3 仍抽取。
  2. 重放 u:2#4：源 trace 仅引注含 #N → statements 无 #N 标记直接通过。
  3. 拒绝文案含源出处上下文 + 承接/剔除形态。
  4. scaffold 成功消息含 ID 清单 + 传导要件。
  5. 全量 pytest 绿（防 v2.33 扩面族回归）。
- 验证口径预登记（#54 同法）：下轮实跑 statements 步 from-file 提交 ≤2 且拒绝 ≤1（仅门槛履职类）。
