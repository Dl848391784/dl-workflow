# dashboard 段结束自动续跑设计（no-TTY 判别）

> 2026-08-31，web_ui_interaction 实例实爆。修复：dashboard 驱动的工作流每过一个交互步 driver 就退出，需人工点「重新驱动」——与 claude TUI 内「答完自动续跑」体验断裂。

## 1. 症状与根因

**症状**：dashboard 提交答案 → 注入成功 → 门控通过 → state 推进到下一子步骤——但 driver 退出，工作流停着不动，时间轴无进展，需人工「重新驱动」才继续。

**根因链**（逐层实证，非推测）：

1. dashboard 的 inject 端点（`dl_dashboard/app.py`）已做「停 driver → 注入 → restart_drive」——注入后新 driver 确实起了。
2. 新 driver 跑核对段（模型确认 evidence 已落库，输出 STEP_DONE，段内**无新 trace**）→ 段结束进 `_handle_tui_segment_end` 分流。
3. 分流依据 = autodone 标记（`tui_autodone.json`），而 autodone 只认「**driver 段内**落库」一条通道（Stop hook 判 latest hash ≠ pre_sha）。dashboard 的 trace 是 **inject 一次性进程在段外写的**，核对段启动时 pre_sha 已含该 trace → 段内无 hash 变化 → 无 autodone。
4. 无 autodone → 落 `_after_tui_exit` = 「TUI 退 = 全退」（tui-exit-quits-driver-design，2026-08-09 用户裁决）→ 判门控（advanced）→ **driver 退出**，打印「续跑：`dl <name>`」。
5. 此次退出无任何自动重驱接管（restart_drive 只在 inject 端点里）→ 停摆。

**第一性原理**：「TUI 退 = 全退」的前提是「段结束可能意味着真人 /exit，driver 区分不了 /exit 与正常结束，保守全退」。但 **无终端时这个前提不成立**——dashboard spawn driver 是 `stdin=DEVNULL`（driver_mgr.py），"TUI 段" 退化为 print-mode 一次性进程，**不存在真人 /exit**，段结束只有「正常干完」一种语义。保守分支在无终端场景是必然误判。

## 2. 判别条件：stdin 是否 TTY

| 入口 | stdin | 段结束语义 | 应有行为 |
|---|---|---|---|
| 终端 v3 `dl <name> --headless` | TTY | 可能是真人 /exit | **全退（裁决不变）** |
| dashboard driver_mgr spawn | DEVNULL | 只有正常结束 | **落共享门控自动续跑** |
| 无人值守 nohup/脚本 | 非 TTY | 只有正常结束 | 同上（同构受益） |
| v4 front `--segment` | — | 不可达（交互步抛 _SegmentExit，seg_kind 永不 tui） | 不受影响 |

判别实现 = `_stdin_attached_to_terminal()`（`sys.stdin.isatty()`，stdin 缺失/关闭/异常 → False——无键盘是事实，宁续跑勿误判有真人）。

## 3. 改动点（外科手术，一处）

`dl_drive.py::_handle_tui_segment_end`：无 autodone 且 **无终端** → 与 autodone 路径同语义 `return None`（落主循环共享门控），不再进 `_after_tui_exit`。

落共享门控后各分支（主循环既有逻辑，零新增）：

- **advanced** → 续跑下一子步骤 ✓（本次修复点）
- **block** → 带判词自动返工（escalate 阈值兜底；比现状「退出+人工重驱」更优，且不劣化——现状人工重驱后也是带判词返工）
- **escalate / none 超限** → on_breakpoint → `input()` 撞 EOF（DEVNULL）→ 干净退出（`_breakpoint_body` 既有 EOFError 分支）——与现状等价的人工介入面，但退出理由真实（真的需要人）

**不改的面**：
- 终端 v3：`_stdin_attached_to_terminal()=True` → `_after_tui_exit` 原路径，「TUI 退 = 全退」裁决不动。
- autodone 路径：不动。
- `_after_tui_exit` 本身：不动（终端路径仍调它）。
- dashboard inject 端点「停-注-重驱」时序铁律：不动。

## 4. 测试

- 新：`test_handle_tui_segment_end_no_tty_goes_shared_gate`——无 autodone + 钉 `_stdin_attached_to_terminal()=False` → 返回 None，且本函数内不判门控（门控归主循环共享门控，防双判）。
- 改：`test_handle_tui_segment_end_manual_exit_full_quit`——显式钉 TTY=True（pytest 下 stdin 非 TTY，原隐式依赖被新分支截获；钉真后语义更准：本测试 pin 的就是「有终端+手动退出=全退」）。
- 新：`_stdin_attached_to_terminal` 异常兜底（isatty 抛异常 → False）。
- 回归：`test_dl_drive.py` 全量。

## 5. 兼容与风险

- **在跑实例**：改的是 dl_drive.py（driver 进程启动时读盘），在飞 driver 不受影响；下次 restart 即新版。web_ui_interaction（本实例）driver 当前已停，重新驱动即吃修复。
- **无人值守轨道**（~/scripts loop 驱动的 headless 实例）：stdin 非 TTY → 同样从「每交互步停摆」变「自动续跑」。若外层 loop 依赖 driver 退出做节拍——driver 在门栏/闸门/断点仍按退出码收场（断点 EOF 干净退出），loop 的收割点不消失，只是交互步不再误停机。
- **回滚面**：单分支翻转（删 `if not _stdin_attached_to_terminal()` 块）即回现状。
