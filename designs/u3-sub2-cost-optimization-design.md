# understand:3 子2（约束验证标注）耗时/token 优化设计——断链收官（续步 EV 证伪后修订）

> 日期：2026-08-18 · 分支 feat/u3-sub2-cost · 状态：实施中
> **修订（2026-08-18 收官）**：初版方案 = 段内续步（#21 泛化）；两轮 live A/B
> 实测续步边界暖率 1/4，EV 核算证伪（§6），**改断链收官**（u:3 出 CHAIN 不入
> MERGED）。§2/§3 保留初版原文作推理轨迹，落地以 §6 裁决为准。
> 上游：designs/u2-sub4-cost-optimization-design.md（段内续步 MERGED_RUN_NODES #21）；
>      designs/u2-sub3-cost-optimization-design.md（段链断链 #20）；
>      designs/u3-sub1-cost-optimization-design.md（u:3 置位 segment_tools + B1 实证
>      env 剥离对本节点是反优化）
> 触发 = 用户指令（2026-08-18）：「优化 understand:3 的 step2，耗时和 token 消耗要
> 大幅降低，能用前面步骤沉淀下来的 discovered 和 evidence 就尽量用，避免 factor 化；
> 跑测试工作流用 ac-deepseek1；amplitude 今日值 4920.2%」（承 u:3 子1 优化之后）。

## 1. 基线实测（现成数据，零新跑）

u3_sub1_ab2（2026-08-18，ac-deepseek1/deepseek-v4-flash headless，当前 HEAD 同码
——tools 白名单已置位、链行为未变）的 u:3 链会话（a19bc679，#2→#3→#4 同
session --resume 段链），result 行逐段读数：

| 段 | 首调 fresh | 段 fresh | 段 cr | out | 模型墙钟 | 唯一调用 |
|---|---|---|---|---|---|---|
| u:3#2（fresh 段=链头） | 25,846 | 47,516 | 1,412,736 | 22,183 | 199.5s | ~30 |
| u:3#3（链续） | **71,862（cr=0 恒冷）** | 81,345 | 1,499,392 | 18,118 | 173.0s | ~19 |
| u:3#4（链续） | **106,780（cr=1,792 恒冷）** | 116,523 | 841,344 | 23,006 | 183.8s | ~10 |
| 链合计 | | **245,384** | 3,753,472 | 63,307 | **556.3s** | |

对照 u3_sub1_base（tools 白名单前）：#2 首调 40,228 / 段 73,008；#3 首调 110,576
恒冷；#4 首调 134,435（cr=1,792）恒冷；链合计 fresh 344k / 墙钟 654s。

### 成本归因（逐调用拆解 + 工具序列核对）

1. **#2 段本体已接近地板**：首调 25,846（u3-sub1 tools 白名单已兑现 -35.8%）；
   env 剥离对 u:3 是反优化（B1 实证：约束验证须点名规则条号，CLAUDE.md 自动
   加载是任务功能材料）。段内调用暖（cr 逐调 27k→61k 单调涨=会话内累积，
   deepseek 流式会话内缓存生效）。真实验证动作（ls/grep 回测 json、Read
   formatters.py、codegraph sync+impact、grep PROJECT.md 规则条号）≈15-20 调
   = 步体核心工作（约束验证=本步交付物，非探索溢出），无搜索层可压。
   **混淆登记**：#2 段头 ~10 调是 driver 伪影（21:44 一个 TUI sub2 段先落过
   trace——A/B 驱动法重收段，生产流不存在），模型耗在「trace 已存在?」的
   元困惑上（读 evidence/state/drive-stream/debug log）——非结构性成本，
   验收口径剔出（§4 预登记）。
2. **链税 = 唯一大头**：#3 首调 71,862（cr=0）+ #4 首调 106,780（cr=1,792）
   = **178,642 fresh 纯链税**（继承 transcript 全量重写，deepseek 会话隔离
   缓存下链恒冷——与 u:2#3 断链前同构，#20）。链税占链合计 fresh 73%。
3. **evidence/discovered 复用现状**：#2 输入（子1 约束候选+sources 出处）经
   交接包在场，零 evidence 全量重读（混淆调用除外）；discoveries 台账指针
   在 node-rules 在场（本轮无需使用）。**但链结构本身是对「前序沉淀」最大的
   浪费**——#3/#4 冷启动重付的正是 #2 已在会话内验证/引用的全部内容
   （子1 候选、验证留痕、sources）。段内续步 = 让前序沉淀以「进程内暖上下文」
   形态被后续步零成本消费，是「用前序沉淀」的最深兑现。

## 2. 方案（单修，纯白名单翻转，零代码路径新增）

**u:3 移出 SEGMENT_CHAIN_NODES、加入 MERGED_RUN_NODES**——#21 泛化第三例
（u:2 先例 00bb6c2）：#2 作为 merged-run 头段（fresh 段首调不变），#3/#4 以
续步变体 prompt（剥交接包——会话内已有真迹）在同进程 stream-json 暖续跑；
逐 turn gate 零变更；撞 #5（confirm 级交互步）收段回主循环；ctx 破 250k
护栏收段降级 fresh 段。白名单即回滚面。

### 置位前置核对（#21  checklist 逐项）

1. **节点形状**：u:3 与 u:2 完全同构——#1 交互（TUI needuser）/#2-#4 非交互
   连续 /#5 confirm 级交互（`_apply_confirm_readback_tier`）。合并段覆盖
   #2→#3→#4，#5 边界由 `can_continue` 的 interactive 检查天然收段。
2. **冷启动占比**：#3 冷启动 71.9k/段 fresh 81.3k = 88%；#4 106.8k/116.5k
   = 92%——均 >50% 判别线，续步候选成立（#21 判别问句）。#3 虽有探索面
   （codegraph impact×2 + grep ~12 调），冷启动仍主导。
3. **交接包材料完备性逐字段核对**（续步剥交接包=材料须在会话内）：#3 输入
   = 子1 候选清单（#2 段交接包在场）+ 子2 验证留痕（#2 段内产出）；#4 输入
   = 子1-3 trace（前两者 + #3 段内产出）——全部在合并会话上下文内，零缺口。
4. **工具白名单**：u:3 Node 已置位 segment_tools=(Bash,Read,Edit,Skill)
   （u3-sub1）——#2 验证（Bash/Read）/#3 取证（Bash codegraph）/#4
   define-problem（Skill）全覆盖，MergedSession 经 segment_spawn_overrides
   单源接续，无需新增。strip_project_context 维持 False（B1 教训）。
5. **ctx 护栏**：ab2 链峰值 cr 126,976 << 250k；合并段内容相同（灭的是冷重付
   非内容），峰值同量级，护栏余量 ~2×。u:1 不上 MERGED 的理由（324k 破护栏
   前科+步体太重）对 u:3 不成立。
6. **NEXT_PREP**：#4 附带交付（u:4#1 lookahead）由合并循环 cur_prep 机制
   接续（u:2 同路径已生产验证）。
7. **避免 factor 化自证**：改动 = 框架级白名单成员翻转，无任何项目数据契约
   词形（无因子/回测/报告语义），机制跨项目通用。

### 显式不做

- 不动 #2 验证义务与 gate 判据（零判据变更——「前序 trace 留痕继承为已验证」
  会动三态判据真值源，弱模型风险 >> 省几调验证，#6 零和游戏判别不通过）；
- 不给 #2 配探索预算（干净段无探索溢出实据，#5 机制对症规划步越界非验证步）；
- 不动 understand:4 / plan 族链（各自独立立项，surgical）；
- 不动 #2 段首调（u3-sub1 已兑现 tools 白名单；env 剥离 = B1 反优化实锤）。

## 3. 预期收益（deepseek 口径，对照 ab2 基线）

| 指标 | 基线（ab2 链） | 预期（合并段） | 机制 |
|---|---|---|---|
| #3 首调 fresh | 71,862 | ~3-5k（**-93~96%**） | 续步 prompt 剥交接包（u2-sub4 实测 -92%） |
| #4 首调 fresh | 106,780 | ~3-5k（**-95~97%**） | 同上 |
| #3+#4 段 fresh | 197,868 | ~30-40k（**-80~85%**） | 冷重付灭 + 段内调用暖续 |
| 链合计 fresh | 245,384 | ~80-90k（**-63~67%**） | #2 段持平 + 链税灭 |
| 链墙钟 | 556.3s | ~380-430s（**-23~32%**） | 两次冷 TTFT（各 ~30-60s）灭 + 暖续 TTFT ~1.4s |
| #2 段本体 | 47,516 / 199.5s | 持平（结构不变） | ——（混淆调用剔除口径见 §4） |
| cr 总账 | 3.75M | +0~10%（预登记） | 续步单轮 cr 涨 vs 返工褶皱灭相抵（u2-sub4 实测 +3.5%） |

护栏：一次通过率不降（gate 逐 turn 零变更）；escalate/NEED_USER/中断/进程死
全部收段回主循环按既有语义（state 在磁盘）；回滚 = 白名单翻转回链。

## 4. 验证计划

1. TDD 红→绿 + 全量 pytest + ruff。
2. **live A/B（dl @ac-deepseek1，新实例 u3_sub2_ab）**：种子 = u3_sub1_ab2
   evidence 截断到 u:3#1 gate 通过（剔除 ≥u:3#2 的 trace 防「已落库」元困惑），
   state 置 understand:3 sub_step_index=2，从 u:3#2 直接起跑（免 TUI 驱动）。
   基线 = ab2 链读数（§1，同 HEAD 同 provider）。AC_WORKFLOW_LAUNCHER 指向
   本 worktree dl-launch.sh。
3. **预登记混淆声明**：
   - #2 段本体不可比（ab2 的 #2 段含 driver 伪影 ~10 调；A 轮从 #2 干净起跑
     属机制外差异）——验收口径对 #2 只做行为核对：首调 fresh ~25-26k 持平、
     零 evidence 全量重读、零 block、trace 质量（三态标注+验证留痕+规则条号
     点名）不降；
   - 主验收口径 = **#3/#4 首调 fresh + #3+#4 段 fresh + 链墙钟**（机制读数，
     与步体轮数方差天然分离，#40）；
   - cr 预登记 +0~10% 容差（续步 cr 单轮涨与返工褶皱灭相抵）；
   - 种子与基线同源（u3_sub1_ab2 evidence），u:3#1 之前零漂移；#3 探索面
     （grep/codegraph 调用数）属步体方差不作验收。
4. 验收点：#3/#4 首调 ≤6k；#3+#4 段 fresh ≤45k；链墙钟 -20% 以上；
   全 node 零 block、judge pass、trace 质量目测不降；#5 confirm 边界正常收段
   （主循环接管，confirm 级零 token）；NEXT_PREP stash（u:4#1）若产出须正常
   落库消费（产出与否方差已登记，不作硬验收）。

## 5. 影响面

- `dl_flow_engine.py`：SEGMENT_CHAIN_NODES 摘 "understand:3" +
  MERGED_RUN_NODES 加 "understand:3"（注释引本设计）
- tests：u:3 链拒续（_chain_resume_sid 返 None）+ u:3 合并段主路径
  （#2→#3→#4 单进程续跑、续步剥交接包、#5 收段）+ 白名单互斥不变量
- 三模式：drive headless 生效 / front / v2 不经此白名单零变更
- 在飞工作流：state 无 schema 变更；残留链记录下次查名单自然失配无需迁移
  （u2-sub3 同先例）；u:3 在飞实例下次到 #2 自动走合并段（行为变化方向=省）

## 6. 实施验证记录（2026-08-18/19，feat/u3-sub2-cost）——三轮误跑链 + 续步实测 + 断链收官

TDD 红→绿 + 全量 pytest + ruff 绿（format 漂移未收，只收自己改动文件）。

### 6.1 误跑发现：bashrc `dl()` 不走 AC_WORKFLOW_LAUNCHER（驱动法踩坑登记）

u3_sub2_ab/ab2/ab3 三轮用 `dl <name> --headless` 起跑，意图经
AC_WORKFLOW_LAUNCHER 指向本 worktree——**但 bashrc `dl()` 体内写死
`$DL_WF_HOME/scripts/workflow/dl-launch.sh`（主树），AC_WORKFLOW_LAUNCHER
只有 ac-* provider 函数的 --dl 路径读取**。三轮全部跑在主树代码（u:3 仍在
CHAIN）上。ab3 轮 driver 日志「⟂ 段链续跑（understand:3 链）」+ state
segment_chain 落库实锤。ab2 轮曾把 #2 段尾暖调用（3,818 cr=76,928）误读为
「#3 续步边界暖」——按 turn fresh 总数逐调用配平后确认该调用属 #2 段
（51,561+3,818+257=55,636 精确配平），**合并段前三轮从未被真实测试**。
正确驱动法 = 直调 worktree launcher：
`bash ~/.dl-workflow-worktrees/<wt>/scripts/workflow/dl-launch.sh --workflow <name> --headless`。

### 6.2 链税三轮复测（主树代码，误跑变基线加固）

| 轮 | #3 首调 | #4 首调 | 备注 |
|---|---|---|---|
| u3_sub1_ab2（既有基线） | 71,862（cr=0） | 106,780（cr=1,792） | |
| u3_sub2_ab | 65,289（cr=0） | 120,798（cr=1,792） | |
| u3_sub2_ab2 | 91,813（cr=0） | 122,027（cr=1,792） | +段内逐出 |
| u3_sub2_ab3 | 67,852（cr=0） | 92,520（cr=1,792） | |

链边界 8/8 全冷，链税 65-122k/边界稳定复现（deepseek 会话隔离缓存，
跨进程 --resume 必冷——#9 第三/四实例）。#2 段（fresh 段）四轮首调
23,303-23,314 稳定；行为核对四轮全中：零 evidence 全量重读、零元困惑、
验证留痕精确（双×100 链 0.492015→49.2→4920.15≈4920.2% 会话事实逐点
核实）、全程零 block。

### 6.3 合并段真实首测（u3_sub2_ab4，直调 worktree launcher，MERGED={u:2,u:3} 临时翻转）

driver 日志「✓ 子步骤 N 通过门控（段内续步）」确认代码路径。两续步边界
**全暖**（u2_sub4_ab 后第二实例）：

| 段 | 首调 fresh | 段 fresh | 段 cr | 墙钟 | 调用数 |
|---|---|---|---|---|---|
| #2 | 23,314（cr=0） | 68,961 | 3,461,376 | 368s | 60（步体方差爆破） |
| #3（续步暖 ✓） | **3,047（cr=102,656）** | 29,040 | 2,974,208 | 217s | 24 |
| #4（续步暖 ✓） | **5,441（cr=141,696）** | 16,676 | 926,336 | 140s | 6 |

首调口径：**#3 -95.8% / #4 -94.9%**（对照链税 71,862/106,780）——续步机制
对 u:3 成立。但 cr 合计 7.36M（链基线 3.75M 的 2 倍）：续步每调重读单调涨
的全量 transcript（#3 逐调 cr 100-165k）——**transcript 携带税**：合并/链
都把前序全部工作背在上下文里，断链 fresh 段只背交接包（~26-31k）+本步
工作。（#2 步体 60 调用爆破放大本论读数——步体方差 #40，但携带税的
量级差是机制性的：同上下文每调必重读。）

### 6.4 三方核算与裁决（deepseek cr≈0.1×fresh 单价口径）

每轮 u:3#3+#4 期望成本（fresh + 0.1×cr，fresh 等效）：

| 方案 | fresh | cr | fresh 等效合计 | 确定性 |
|---|---|---|---|---|
| 链 | ~178k | ~3M | ~478k | 确定（8/8 冷） |
| 续步暖（实测轮） | ~46k+本体 | ~3-4M | ~346k+ | 彩票（暖率未知，6.5 节） |
| 续步冷 | ~190k | ~3-4M | ~490k | |
| **断链 fresh 段** | ~55-60k+本体 | **~0.5M**（上下文重置） | **~110k** | **确定** |

续步暖在省首调 fresh（-68~-117k/边界）但 transcript 携带税每调照付；
断链把每调重读从 100-165k 压到 26-60k——**携带税 >> 首调税时断链胜**。
裁决：**断链收官**（当前 HEAD；u:2 的 MERGED 置位不在本设计面——u2_sub4_ab
当日暖轮实测 fresh -77% 达标，但其 cr 携带税未与断链对照过，登记独立后续项）。

### 6.5 断链验收轮（u3_sub2_ab5，fresh 段，直调 worktree launcher）

（待回填：#3/#4 fresh 段首调 ~26-31k、cr 逐调水位、零 evidence 全量重读、
零 block、u:3#2-4 合计 fresh/cr/墙钟对照链基线。）
