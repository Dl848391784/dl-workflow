# skill 沉淀：围栏与门控健壮性修复的经验（fence-gate-robustness 配套）

> 2026-08-05，配合 fence-gate-robustness 三修（commit 92dc774）的方法论沉淀。
> 改 skill 文档（references/），不改代码逻辑。5 点，用户确认全做。

## 背景

源会话 tail_volume_acceleration_annualized cc_debug.log 实证三个系统级摩擦，已在 fence-gate-robustness-design.md 修复。本设计沉淀**排查与设计方法论**到 workflow-creation skill，使未来同类问题不再走弯路。

## 沉淀点与落点

| # | 点 | 落点 | 性质 |
|---|---|---|---|
| ① | fence_allow 描述过时（子3=Bash/WebFetch -> Bash/Agent/TaskOutput；子4=Agent -> Agent/TaskOutput） | diagnostics.md 症状 O line 219 | 文档纠错（必做，本次改动直接导致漂移） |
| ② | 症状 J 补"假性 block"子场景（后台 agent 未归前 end_turn -> S13 假性 block；诊断 pending + 查 TaskOutput deny） | diagnostics.md 症状 J S13 段 | 新增子场景（understand:1 子3/4 派 agent 固定模式，会重复） |
| ③ | §3 新增诊断条目「模型没做 X 先查工具被 deny，别直接造新机制」 | troubleshooting.md §3 第 14 条 | 通用方法论（本次最值钱，Q3 差点走 sleep 弯路） |
| ④ | hook 协议能力边界（PreToolUse 只能 allow/deny 不能转换；Stop hook 不带 pending agent 状态） | build-and-modify.md §1.2 末尾 | 新增设计约束（未来改 hook 都会踩） |
| ⑤ | 围栏设计原则补第 7 条（deny 前查是否破坏 harness 原生流程，如 TaskOutput） | diagnostics.md 症状 O 原则 #7 | 新增原则（与 #6 同构不同维度） |

## 与 fence-gate-robustness-design.md 的关系

后者是**代码修复**（怎么做），本设计是**方法论沉淀**（下次怎么查/怎么设计才不踩）。互补不重复：
- 代码修复细节（骨架兜底/python3 只读/TaskOutput 放行/pending 检测）在 fence-gate-robustness-design.md + commit。
- skill 只记**通用的查法与设计原则**，不复制具体修复代码（守 skill「不复制规则正文」口径）。

## 改动文件

| 文件 | 改动 |
|---|---|
| skills/workflow-creation/references/diagnostics.md | ① fence_allow 纠错 + ② 症状 J 假性 block 子场景 + ⑤ 围栏原则 #7 |
| skills/workflow-creation/references/troubleshooting.md | ③ §3 第 14 条诊断方法论 |
| skills/workflow-creation/references/build-and-modify.md | ④ hook 协议能力边界段 |

## 风险

- 纯文档改动，无代码逻辑影响，无测试可跑。
- skill 文档膨胀风险：5 点均针对未来会重复的真实场景，非本次特例，值得沉淀。③④⑤ 是设计/排查层，②是症状层，①是纠错。
- 交叉引用：②引用症状 O 原则 #7、③引用 §3.12，确认被引段存在（已验证）。

## install 同步

skill 真源在 ~/.dl-workflow/skills/，副本在 ~/.claude/skills/（install.sh copy）。改真源后须跑 install.sh 同步副本 + 重启会话加载（SKILL.md §0 装法）。merge 后执行。
