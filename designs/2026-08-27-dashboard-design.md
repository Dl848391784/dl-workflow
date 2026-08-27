# dl-workflow 管理后台（dashboard）设计

- 日期：2026-08-27
- 状态：已评审（用户确认）
- 归属：dl-workflow 仓库内新增模块 `dl_dashboard/`

## 1. 背景与目标

dl-workflow 目前的运维面靠终端：`dl <name>` 起 TUI、`wf_ctl.py status/drive/inject` 手动驱动、
断点靠人盯着终端。目标是把这套运维面变成**服务端常驻 + 浏览器可视化**的控制台：

1. 界面上启动工作流（选项目、起名、输入 problem_statement）。
2. 节点全景：5 阶段全节点（u:1~5 → plan:1~4 → execute → review → evolve）的
   已完成 / 当前 / 未开始状态一眼可见。
3. 每 step 观测：耗时、token（input/cache）、成本、轮数。
4. 全驱动：断点注入答案、gate 放行/打回、/dl 指令，全流程不用回终端。
5. 会话不断开：driver 跑在服务端，浏览器刷新/关闭不影响工作流执行。

## 2. 关键决策（用户已确认）

| 决策点 | 结论 |
|---|---|
| 代码归属 | dl-workflow 仓库内新增模块（跨项目通用，与 dl 同部署） |
| 交互深度 | 启动 + 全驱动（create/statement/drive/inject/gate//dl 全搬入浏览器） |
| 保活机制 | 后端托管 driver 子进程（setsid 独立进程组 + PID 文件 + 重启认领） |
| 技术栈 | FastAPI + 原生 JS（单页无构建）+ SSE 推送 |
| 项目范围 | 多项目，可配项目根清单 |
| 网络暴露 | 0.0.0.0:9000，无认证（用户决定；风险提示见 §8） |

### 保活机制选型理由

- v3/v4 架构本就是 headless `claude -p` 分段 + dl_drive.py 驱动，后台复用驱动循环，零概念新增。
- 工作流真实状态全落盘（state.json + worktree + 段 transcript + drive-stream.jsonl），
  `--resume`/重跑 drive 即无损续跑——「不断开」靠磁盘状态，不靠进程不死。
- tmux 包 TUI 方案：需把整套人机交互协议在 web 层重实现，且 TUI 场景已被后台替代，不值。
- systemd 方案：部署最重，收益仅「后端挂了 driver 还能跑」，setsid 已覆盖。

## 3. 总体架构

```
浏览器 ──HTTP/SSE──> FastAPI 后端 (dl_dashboard, 0.0.0.0:9000)
                        │
                        ├─ 扫描器：读各项目 .claude/workflows/*/state.json
                        │           + drive-stream.jsonl + need_user.json
                        │
                        └─ Driver 管理器：fork 子进程跑 dl_drive.py（setsid）
                                            每个运行中工作流一个 driver，日志/PID 落盘
```

后端为纯 Python 单包 `dl_dashboard/`，直接 import `dl_flow_engine` / `dl_flow_common` /
`dl_flow_nodes`，复用 state 读取与节点全表，不复制状态机。

## 4. 组件拆分

| 模块 | 职责 | 依赖 |
|---|---|---|
| `dl_dashboard/config.py` | 读 `~/.dl-workflow/dashboard.toml`：项目根清单、端口 | 无 |
| `dl_dashboard/scanner.py` | 跨项目扫描工作流元目录，聚合 state.json → 节点状态模型（已完成/当前/未开始） | dl_flow_common, dl_flow_nodes |
| `dl_dashboard/metrics.py` | 解析 drive-stream.jsonl / cc_sdk.log，聚合每 step 耗时/轮数/token/成本 | 无（纯解析） |
| `dl_dashboard/driver_mgr.py` | driver 生命周期：spawn(setsid)、stop、心跳、PID 文件、重启后认领 | subprocess, dl_drive |
| `dl_dashboard/actions.py` | 写操作：create（dl-launch.sh --headless）、statement、inject、gate、/dl 指令 | driver_mgr |
| `dl_dashboard/app.py` | FastAPI 路由 + SSE + 静态页 | 以上全部 |
| `dl_dashboard/static/` | 单页原生 JS：列表 + 节点图 + step 表 + 交互区 | SSE |

## 5. 数据流

- **读路径（监控）**：scanner 定时（~2s 或 mtime 触发）重读 state.json/need_user.json → SSE 推浏览器。
  节点状态推导：state.json `history`（entered_at/exited_at）+ `dl_flow_nodes._NODES` 全表对照 →
  每节点 已完成/进行中/未开始；`gate` 字段标门栏。
- **写路径（驱动）**：浏览器操作 → actions.py → 等价 wf_ctl.py 的 create/statement/drive/inject。
  driver 到断点（need_user）退出/挂起 → scanner 发现 need_user.json → 界面亮「等待输入」。
- **保活**：driver setsid 独立进程组，PID/日志落盘 per-workflow；后端重启扫 PID 文件认领活 driver，
  认不到标「driver 已死，可一键恢复」（重跑 drive 续跑，非重来）。

## 6. 页面布局（单页三视图）

1. **工作流列表页**（默认）：按项目分组；每行 = 名称、当前节点、gate 状态、driver 存活（绿/灰点）、
   累计成本、更新时间。顶部「新建工作流」：项目下拉 + 名称 + problem_statement →
   create + statement + drive，自动跳详情页。
2. **工作流详情页**：
   - 上部节点全景条：全节点横排，已完成=绿、当前=闪烁蓝、未开始=灰、gate pending 带锁。
     点击节点展开 step 明细。
   - 中部 step 表格：节点、轮数、耗时、token（input/cache）、成本、完成时间。
   - 下部交互区：need_user 显示问题原文 + 答案输入框（inject）；gate pending 显示放行/打回；
     /dl 指令输入框（next/back/jump/dispute 等）。
   - 右侧 driver 日志小窗：tail drive-stream.jsonl 最近 N 行。
3. **断点通知**：SSE 触发浏览器标题闪烁 + 页面横幅（「工作流 X 在 plan:4 等待输入」），
   多工作流并行不漏断点。

## 7. 错误处理

- **driver 异常退出**：PID 死 + state 未推进 → 标红「driver 已退出（exit N）」+「重新驱动」按钮。
- **create 失败**：沿用 wf_ctl 判定——实例已落盘即算建成，界面如实显示 launcher 输出尾部。
- **状态文件损坏/缺失**：scanner 单工作流隔离 try/except，坏实例标「状态不可读」不影响其他，
  日志记详情（守 no silent fallback）。
- **并发写**：同一工作流写操作 per-workflow asyncio.Lock 串行化，防双击/多标签页并发注入。
- **SSE 断线**：EventSource 自动重连，重连后全量刷新一次。

## 8. 风险提示（已告知用户，按用户决定执行）

0.0.0.0:9000 无认证 = 公网任何人可驱动工作流（执行任意 claude 段的间接能力）。
建议后续加可选 token（env 配置即启用），本期不做。

## 9. 测试

- `metrics.py` / `scanner.py`：纯函数 pytest，用真实历史工作流目录（amplitude_annualized 等）做
  fixture，断言节点状态推导与 step 聚合数值。
- `driver_mgr.py`：mock subprocess，测 spawn/认领/死进程标记三分支。
- `actions.py`：临时 git repo 端到端 create→statement→drive→断点→inject（标记 slow，不进默认跑）。
- `app.py`：FastAPI TestClient 路由级测试（列表/详情/SSE 首帧）。
- 前端无构建，手测为主，核心交互路径列手动验收清单。

## 10. 明确不做（YAGNI）

- 无认证/用户体系；无工作流删除/归档按钮（走终端 `dl <name> --done`）；
- 无 TUI 模式支持（只管 headless 轨道）；无历史报表/趋势图。
