# thinking 清零档落地 + judge qodercli 兼容

> 2026-09-18。用户裁决范围（两件，其余档不动）：①judge thinking 控制兼容 qodercli；②disabled 档落地（呈现段/inject 注入轮；读回步无模型段=零动作）。

## 事实基础

- qodercli 1.1.47 原生 `--thinking disabled`/`--thinking-budget N`/`--reasoning-effort`（本机探针实证 rc=0）；`MAX_THINKING_TOKENS` 是 claude harness 约定，qodercli 不读 → v2.44 judge 裁剪在 qoder 路径空转。
- 读回步在 drive 模式 = render-readback 机械展示 + write_confirm_trace 静默通过，无模型段（dl_drive.py:2597-2627 核实）。

## 方案

- `EngineProfile.thinking_off() -> (env dict, args list)`：claude=env MAX_THINKING_TOKENS=0（v2.44 实证保留）；qodercli=--thinking disabled。引擎差异单源新增面。
- judge（_run_judge_once）：无条件 env 设置改为 thinking_off() 对——qoder 路径裁剪由空转变真实。
- inject 轮（actions.inject_answer）：答案映射+落 trace 近机械，env+cmd 双通道注入。
- 呈现段（run_tui_step_one_shot）：逐字照抄 stash 问题零创作；run_session 加 extra_args 通道（spawn_env 已有）。
-  prep/归一化/取证/方案设计/TUI 交互段：本批不动（分档表见会话，待数据）。

## 验证

TDD：profile 双引擎返回值 / judge qoder 下 cmd 含 flag 且 env 无 MAX / inject env+cmd / one_shot extra_args 透传；全量 pytest + ruff；qoder 实段首跑观察（Mac）。
