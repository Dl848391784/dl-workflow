# TUI 段自动收段续跑设计（trace 落库 → 自动退出 → driver 自动续跑）

> 2026-08-09 用户裁决：「首先我要自动续跑下一步」。承接 `tui-exit-quits-driver-design.md`
> （TUI 退=全退）——本设计在其上叠加「程序通道区分退出方式」，全退裁决对手动退出继续成立。
> （本文档由 0cfa3f1c 会话 15:13 写入后随会话中断丢失，由 c1e4d408 会话从转录恢复重落盘。）

## 1. 缘起

「TUI 退=全退」落地后交互步的用户操作变成：回答问题 → 等模型落库 → 自己打 /exit →
driver 退出 → 重跑 `dl <name>`。用户原话：「每次都要让我输入？这么割裂？」

`tui-exit-quits-driver-design` §2 的结论是「driver 无法区分双击 Ctrl+C 与 /exit」——
对**信号通道**成立，但存在第三条**程序通道**：Stop hook 在模型每轮结束时触发，
可机械判定「本步 trace 是否已落库」（= 交互步的活是否已干完）。落库即收段，
整个 /exit 依赖消失。

## 2. 机制

```
driver（run_tui_step）                     TUI 会话                     Stop hook（drive_mode）
─────────────────────                     ────────                     ─────────────────────
写 tui_segment.json：                     模型干活…                    每轮结束触发：
{pid, node, sub_step,                       （可多轮问答）               读 tui_segment.json
 pre_sha=最新 trace hash}                                                 ↓ 段标记与 state 咬合？
删旧 tui_autodone                                                     ↓ latest_trace_sha1
Popen(claude TUI) ──────────────────────►  …                         ≠ pre_sha（有新 trace）？
proc.wait() 中…                           模型 append-trace 落库           ↓ 是
                                          模型文本汇报，收轮          写 tui_autodone
                                              ↓ Stop 触发            SIGTERM pid（2s 兜底 SIGKILL）
proc.wait() 返回 ◄────────────────────────  会话被杀（rc=-15）
消费两标记：
  有 autodone → 走共享门控处理（advanced=continue 续跑下一步 / block=带返工重开 /
                escalate=断点裁决）——driver 不退出
  无 autodone → _after_tui_exit（TUI 退=全退，手动退出语义不变）
```

**新鲜度判定单源** = `engine.latest_trace_sha1(project_root, name, sub_step, minor_key)`
（§substep-gate-at-stop S1 同款原语：hash 变化=有新产出，覆盖写也产生新 hash）。
driver 启动段时记 `pre_sha`；hook 比对 `≠ pre_sha` 即「本段内落了新 trace」。
不用时间戳：trace 记录 ts 秒级精度，同秒连写不可分；hash 无此问题。

**为什么杀进程是安全的**：TUI 段会话按构造一次性（state/evidence 磁盘真源，
门控只认 evidence jsonl）；trace 已落库（append-trace 是独立进程同步写盘），
杀掉 claude 不丢编排数据。SIGTERM → 2s → SIGKILL 兜底。

**无新 trace 的收轮**（模型中途停下来等用户答话等）：hook 不动作，会话照常住留
——与现状一致。

## 3. 双通道语义总表（本设计落地后）

| 场景 | 标记 | driver 行为 |
|---|---|---|
| 模型落库收轮（正常完成） | 有 autodone | 判门控 → advanced 直接续跑下一步（零用户命令） |
| 落库但门控 block | 有 autodone | 带判词返工上下文自动重开本步（现状轮内返工同语义） |
| 连续 block 达阈值 | 有 autodone | escalate 断点等用户裁决（不变） |
| 用户手动 /exit 或双击 Ctrl+C | 无 | **TUI 退=全退**（今日裁决不变）：判门控后退 0，续跑 `dl <name>` |

## 4. 改动面

| 文件 | 改动 |
|---|---|
| `scripts/workflow/dl_drive.py` | run_tui_step 写/清段标记；drive 循环 autodone 分流；TUI 入口 print 去 /exit；tui-rules 第 4 条改「落库后汇报收轮，自动收段续跑」 |
| `hooks/workflow_advance.py` | drive_mode 分支加 `_maybe_autodone_tui`（段标记咬合 + hash 新鲜度 + 写标记 + 杀 pid）；headless 段无段标记=不动作，零影响 |
| `designs/drive-tasklist-render-design.md` | §2.6 修订段补记本设计 |
| `tests/` | hook：有新 trace→标记+kill / 无新 trace→不动作 / 陈旧段标记→不动作；driver：标记消费分流 |

## 5. 已知边界

- **收轮即关窗**：trace 落库后会话立刻退出，用户「等等我补一句」的窗口消失
  （补救：`/dl state-reset` 或下轮返工）。读回步的确认发生在落库前（AskUserQuestion），
  主路径不受影响。
- **模型落库后不收轮继续说**：Stop 只在收轮时触发——落库后若模型继续长篇输出，
  收段发生在它说完时，属正常。
- **kill 失败的兜底**：SIGTERM/SIGKILL 都没杀死（理论上不可能，同 uid）→
  autodone 标记仍在，但会话没退——driver 仍在 proc.wait；用户手动 /exit 后
  driver 见标记走自动路径续跑，语义仍正确。
- 模型输出禁用标记（### STEP_DONE 等）不影响本机制——判定只看 evidence hash，
  不解析模型文本。
