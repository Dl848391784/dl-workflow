# 强制 TACET 实验设计（Step 强度分档 · 第一期）

> 日期：2026-08-21 · 状态：待用户评审
> **本文取代同日上午版 `step-intensity-tiering-design.md`（d3fe0ac，已 git rm）**——上午版曲解用户意图：①把 TACET 收窄成「44 步仅 1 步可 TACET 且纯机械触发」的保守结论；②前置做了档位划分矩阵，而划分机制是用户明确推迟的。
> 命名保留（用户 2026-08-21 选定音乐记谱法）：TACET=最低档（沉默）/ PIANO=轻奏 / FORTE=强奏（=main 现状）。**本期只实现 TACET 的「跳过」形态 + 强制开关；PIANO 与档位划分机制显式不做（§9）。**

## 1. 用户意图（裁决前提，勿再曲解）

- main 现在是完整流程，**只有取证阶段（u:1#4）分档**（v2.40 per-atom none/light/full）。分档思想要**推广到全工作流每一步**。
- TACET = 最低档，语义 = 「这步可以**不执行**，或者**简化执行**」——哪些步能省、怎么省，是要探索的问题。
- 其余一切与 main 保持一致。
- **档位划分机制（如何定每步该走哪档）本期不实现**；先做「**强制走 TACET**」开关，实际跑一轮看效果。

## 2. 实验目标与成功标准

用一条测试工作流（真实因子问题）强制 TACET 跑到底，产出三样东西：

1. **成本账**：token / 墙钟 vs 同问题正常跑的基线（口径沿用 cost-optimization 的首调 fresh / 段 fresh / cr / 等效成本）。
2. **损伤报告**：哪些产物节空了、哪面机械墙塌了、execute 拿到的交接包薄成什么样——**承重步清单从实验涌现，不预设**。
3. **产出可用性人工判**：execute/review 产物离可用差多远。

跑通标准：流程不卡死走完全程（含 plan:4 门栏 `/dl gate` 放行）。

## 3. 范围裁决（用户 2026-08-21 授权设立；u:1#1 用户钦定保留）

全工作流步数结构（engine 枚举实测）：understand/plan 共 **44 子步** = 31 非交互 + 13 交互；execute/review/evolution 为整阶段节点（sub_steps=None）。

| 类别 | 步 | 强制 TACET 时 | 理由 |
|---|---|---|---|
| 非交互子步 | 31 步（u:1#2-6、u:2#2-4、u:3#2-4、u:4#2-4、plan:1#1/3/4/5、plan:2#1-4、plan:3#1-5、plan:4#1-4） | **全部跳过** | 实验面=模型跑的步哪些能省 |
| u:1#1 逼问定义 | 1 步 | 保留 | 用户钦定：唯一问题陈述入口 |
| 读回确认/装配 | 8 步（u:1#7、u:2#5、u:3#5、u:4#5、plan:1#6、plan:2#5、plan:3#6、plan:4#5） | 保留 | 已全降确认级近零成本，跳了省不到钱；且是**用户纠偏通道 + 损伤观察窗口**（上游全跳后读回有多空，直接可见） |
| 引出/发散 | 4 步（u:2#1、u:3#1、u:4#1、plan:1#2） | 保留 | 若跳过则读回必空，「空」归因子无法分离（上游跳 vs 引出跳），信号混淆；它们把用户意图带进运行，实验产出才可用。能否省归档位划分问题，推迟 |
| execute/review/evolution | 3 个整阶段节点 | 不动 | 它们就是产物本身，跳了实验无意义 |
| plan:4 门栏 / plan→execute 闸门 | — | 不动 | 用户裁决点，不是步 |

TACET 步集 = engine 机械推导（44 子步中 `interactive=False` 的 31 步），单源常量；**模型无权选择/修改/自封为 TACET**（防滥用原则同上午版保留）。

## 4. TACET 步语义（v1 只有「跳过」形态）

- **不派段、零 token、不跑 judge**。engine 写一行 `tacet-record` 到 `evidence/<name>.jsonl`（写方只能是 engine，模型无写入路径）：
  `{"kind":"tacet","node":"understand:1","sub_step":4,"trigger":"force_tacet","via":"driver","ts":...}`
- 推进走与 gate-pass 相同的 advance 路径（末步撞 plan:4 门栏照扣留——门栏是用户裁决点，不动）。
- 「简化执行」形态（瘦段、降确认、减 redteam 等）= PIANO 档的事，本期不做。

## 5. 撞墙政策：骨架直通（方案 A，用户 2026-08-21 确认方向）

三面墙全部**降级为损伤记录，不阻断**，流程跑到底，塌在哪看哪：

| 墙 | 正常行为 | force_tacet 下降级形态 |
|---|---|---|
| ①产物装配（`render_artifact`，engine:1186） | understand.md / plan.md 各节内容来自各步 statements | 来源步被跳过的节装配为 `**[TACET 缺损：来源步被跳过]**`——损伤在产物内直接可见 |
| ②plan:4 门栏机械门（ARTIFACT_EXISTS/CONTAINS，engine:871-918，「执行计划与检查点」节） | 检查失败 = gate 不可过，流程卡死 | 检查失败 → 写 `{"kind":"tacet_damage","check":"ARTIFACT_CONTAINS","missing":[...]}` 损伤记录，**仍扣留待 `/dl gate`**（用户裁决点保留），用户可放行 |
| ③交接包变薄（`handoff_pack`，engine:1714） | 前序 trace 打包喂下游 | tacet-record 以「子N 已跳过(tacet)」一行进包，链条结构完整，下游模型知道信息真空在哪（不卡死，但 execute 段在薄包上干活=损伤的一部分，事后评估） |

损伤记录统一写 evidence.jsonl（`kind:"tacet_damage"`），实验后人工汇总成报告（不做自动报告脚本，YAGNI）。

## 6. 机制设计（落点均为已核实函数）

- **开关**：`dl <name> --force-tacet` → dl-launch.sh 写 `state.force_tacet=true`（sticky，resume/续跑保持）。**`--force-tacet` 隐含 `--headless`**（实验车只支持 headless driver；launch 脚本强制并打印提示，front 模式 v1 不支持）。零 force_tacet 时零行为变化——所有新代码路径以 state 标志为唯一开关，回滚面=删掉标志。
- **跳步**：dl_drive.py 段循环派段前查 `state.force_tacet and step in TACET_SET` → 调新 engine 函数 `apply_tacet_skip(project_root, name)`（写 tacet-record + 复用 advance 推进 + 末步门栏扣留保持）→ 不派段继续循环。
- **judge 跳过**：tacet 步无段无 Stop，`gate_sub_step_at_stop`（engine:2502）/ `run_gate`（engine:3107）天然不触发；tacet-record 不进 judge 输入（`read_evidence_for_step`，engine:1053 对 kind=tacet 跳过）。
- **进度显示**：`progress_rows`（engine:6197）对 tacet 步标「tacet」记号；LiveProgress 原样透出；跳步时 driver 打一行事件日志。
- **front 防御**：hooks 检测 `state.force_tacet` + front 模式 → 注入「本运行为 force-tacet 实验，仅支持 --headless」提示（launch 已拦，此为纵深）。

## 7. 实验规程

1. 起测试工作流：`dl <实验名> --force-tacet`（隐含 --headless），用一个真实因子问题。
2. 用户参与 13 个交互步（提问 + 引出 + 读回），plan:4 门栏 `/dl gate` ×2 放行。
3. 跑完后汇总：evidence 里 tacet/tacet_damage 记录 → 损伤报告；token/墙钟读数 vs 基线；人工判 execute/review 产物可用性。
4. 产出**承重步清单** = 后续档位划分（第二期）的输入。

## 8. 测试与影响面

- **测试**：TACET_SET 推导=31 且与 interactive 互补（44=31+13）/ launch flag→state sticky / apply_tacet_skip 写 record+推进+末步扣留 / 门栏 CONTAINS 失败→damage-record+仍可放行 / render_artifact 缺损标注 / tacet 步零 judge / progress_rows tacet 标记 / --force-tacet 隐含 --headless / 零 force 时全行为不变（回归）。
- **文件**：dl-launch.sh（flag）/ dl_flow_nodes.py（TACET_SET 推导）/ dl_flow_engine.py（apply_tacet_skip + 门栏降级 + render_artifact 标注 + read_evidence_for_step 跳 tacet + handoff_pack + progress_rows）/ dl_drive.py（跳派段+事件日志）/ hooks/workflow_phase.py（防御提示）/ tests。
- **H9 预算**：拆 commit——①engine 核心（TACET_SET + apply_tacet_skip）②driver+launch ③门栏降级+artifact 标注+progress ④测试。
- **worktree 纪律**：实现按 worktree-per-session 协议（feat/force-tacet），收口 merge 回 main。

## 9. 显式不做

- **不做档位划分机制**（每步该走哪档怎么定）——第二期，输入=本实验的承重步清单。
- **不做 PIANO / 简化执行形态**——TACET v1 只有跳过。
- **不做 front 模式支持**——实验车 headless only。
- **不做依赖图 / 撞墙自动落回**（方案 B）——那是正式版候选，等实验结果；预设依赖图与「答案从实验涌现」相悖。
- **不做损伤报告自动汇总脚本**——evidence 记录 + 人工汇总足够。
- **不改 execute/review/evolution、门栏/闸门、交互步的任何行为**。
