# plan:3#3 匹配选型 成本优化设计（p3-sub3-cost）

> H8 design.md。目标步 = plan:3 sub_step 3「匹配选型提案」（CapabilityToolSelection#3，
> kind=skill，fence_allow=Agent 条件红队）。方法论 = cost-optimization.md
> （#20/#24/#26/#30/#33/#36/#37/#40 等）；A/B provider = ac-deepseek1（deepseek-v4-flash）。
> **禁 factor 化**（用户指令 2026-08-20，p2-sub3/p3-sub2 同约束）：条款全部
> 机制/形态级，不把测试实例的因子名/文件面/数值写进引擎条款。

## 0. 验收口径

逐调用读数（#30：全轮总账被步体方差淹没）：首调 fresh / 段 fresh / 段 cr /
段 out / 轮数 / 工具调用数 / dur_api / 成本等效（段 fresh + 0.1×段 cr）/
block 数 / append-trace mech 拒数。**红队 agent 账目合并口径**（p1-sub4-cost
#36 审计手法：transcript subagents/ 子目录归集，等效同主段）。

## 1. 基线（自跑基线，A = p3_sub3_base 子3 段，14571cf 码）

免跑基线（#30）经查不适用：并行会话 p3-sub2-cost 的 B 轮（p3_sub2_ab，
2026-08-20 17:21 起）按其设计 §8「目标步 gate 过即收段统计」在子2 落库推进
后收段，**未跑子3**——无同码同种子现成段。p2_sub3_ab 有子3 老链段
（首调 184,727 / 16 轮 / cr 2,142,464，见 §2 参照），但其形态=链 resume
子1+子2 双 transcript，与本分支基线形态（p3-sub2-cost L2 后链 resume
换挂子2 fresh 会话单 transcript）不同，直接作基线会把 p3-sub2 的侧效应
计入本设计杠杆——只作行为面参照，不作 A。

**A/B 双臂自跑方案**：p3_sub2_ab 当前状态（子2 trace 已落库、将跑子3、
segment_chain 挂子2 会话）复制两副本——`p3_sub3_base`（A 臂，launcher=
p3-sub2-cost worktree @14571cf=本分支父提交，子3 链内段 resume 子2 fresh
会话）与 `p3_sub3_ab`（B 臂，launcher=本 worktree，子3 fresh 段）。双臂
种子逐字节相同、前序子1/子2 trace 同一条（p3_sub2_ab B 轮产出）——同种子
同源最强对比面（p3-sub1-cost 先例），A/B 唯一差异=本设计落地件。串行跑
（A 先 B 后）防墙钟争抢。

子2 段实测读数（p3_sub2_ab，14571cf）：16 轮 / dur_api 217.6s / in 72,380 /
cr 816,896 / out 34,334 / 末调 in 100,854（≈子2 transcript 体量，cr=0 恒冷
实锤）。A 臂子3 首调预测 ≈ 100.9k transcript 冷重写 + step prompt ≈ 103-106k。

## 2. 浪费盘点（参照=p2_sub3_ab 子3 老链段逐条归因 + 结构分析）

老链段（p2_sub3_ab，16 轮 / 首调 184,727 / 段 in 192,262 / cr 2,142,464 /
out 11,958 / dur_api 100.2s）工具序列：
text(映射推理+红队触发判定) → Agent(红队，prompt 自带材料包) →
scaffold → Read 骨架 → Edit×2 → append-trace(一次过) → python 验证落库×1。

| 浪费类 | 实例 | 定性 |
|---|---|---|
| 链携带税 | 首调 184,727（cr≈0 冷重写子1+子2 transcript）；每调 cr ≈134k×16 轮 | **主浪费**——交接包已载子1/子2 trace 全文，链继承冗余（#20/#24） |
| 交付后徘徊 | append 落库后 python 读 evidence 验证×1 | 褶皱（#37） |
| 红队材料包无条款保障 | 本轮模型自愿逐字携带材料包（agent 0 工具/30.8k in/19.7k out 健康），但 purpose 无三钉条款——p1-sub4 基线证明无条款时会退化成 58 调用重勘（占步成本 73%） | 方差敞口（#36） |
| 行为面其余 | 7 调用近理想形态，零 evidence 翻找/零格式猎捕 | **已到地板（#40）**——油水在前缀层+链税层 |

红队 agent 账目（老链段子代理）：1 调用 / 0 工具 / in 30,775 / out 19,743 /
等效 ≈31k——材料包形态健康，条款化是方差防守非消灭现存浪费。

> **§2 订正（2026-08-20 A 臂实测后）**：上表基于 p2_sub3_ab 老链段单样本
> 的「行为面已到地板」判断被 A 臂（p3_sub3_base，14571cf 无条款，同种子
> 同前序 trace）证伪——A 臂主段 45 调用+红队 33 工具爆炸（evidence 翻找
> ×20/plan.md locate×9/注册表重勘察×3/数据文件核验×4，纯税 ~80%；红队
> 82 调用重勘）。老链段的「乖」=链上下文携带格式/材料上下文兜底的幸运
> 形态，单样本不可外推（沉淀 #43）。本设计条款的真实油水=弱模型 run 间
> 方差收敛，§5 预登记的「方差防守」定位据此升级为「方差消灭」。

## 3. 杠杆

### L1 步级断链（plan:3,3）入 SEGMENT_CHAIN_SKIP_STEPS（步级第三例）

判据（#20/#24 双钉）：①deepseek 会话隔离缓存下链首调恒冷——子2 段末调
cr=0 实锤，A 臂子3 首调 = 子2 transcript ~101k 全额冷重写；②携带税主导——
链内每调重读继承 transcript（老链段实测 ~134k/调），fresh 段每调只背
~30-45k 前缀；③**交接包材料完备性逐字段核对**：子3 输入契约 =
step1.need_baseline + step2.capability_registry（Step.input 声明），两者 =
本节点子1/子2 最新 trace，交接包「本节点前序 trace 全文通道」逐字在包
（B 轮跑前以段 prompt 冒烟复核）；红队材料包同源于子1/子2 trace，亦在包。
surgical：节点白名单（plan:3 ∈ SEGMENT_CHAIN_NODES）不动，(plan:3,3) 单步
摘除，子4/子5 零行为变化（链 resume 换挂子3 fresh 会话，继承 transcript
变小=同向侧效应，p3-sub2 §3 L2 同型）。

断链暴露面预登记（#20 补/#30）：①子3 fresh 化轮数上限 ≤20（基线 16——
链携带的格式上下文丢失可能 +1-2 轮，L4 格式真源同批补款压住）；②子4/子5
轮数行为不变（只继承变小）；③链峰值：fresh 化后子3 段峰值 ≈45k 远低于
250k 护栏。

### L2 Step strip（segment_strip_project_context，第十五例——收口时按
git log 最大值+1 核定）

#23 第三核对（env 剥离边界）：子3 交付物正文 = 绑定理由引用**子2 trace**
出处（gate 方框二合法形态=「子2 ③出处/available-skills 列表行『X』/触发词
引用」——出处载体是子2 trace 非 CLAUDE.md 本体）；gate 判材边界明示
「真实注册表/CLAUDE.md §2 原文结构性不可见」=子3 无 CLAUDE.md 一等材料
依赖（与子2 否决理由反向——子2 正文逐字引 §2/§3，子3 只引子2 trace）。
收益 = 项目上下文 -11.9k/调（探针口径）。

### L3 pack_self_contained（非交互步第七例，#40 方差防守定位）

置位前置逐字段核对（#16/#19）：输入契约两字段（step1.need_baseline /
step2.capability_registry）⊆ 包内前序 trace 全文通道 ✓；红队材料包同源 ✓；
基线 de facto 零 evidence 翻找（工具序列实证）=条款系方差防守（p2-sub4
同型定位）。装配不变量测试钉包内容（防未来包修剪把材料修没条款变错）。
包尾切换「材料已在包内」（headless 段 driver 装配，worktree A/B 即生效，
#40②）。

### L4 条款四件套（purpose 追加，机制/形态级）

- **复用钉死**（#34 同向形态）：子1 需求清单/子2 注册表出处=交接包前序
  trace 逐字引用零重验；零 evidence 翻找/零注册表重勘察（CLAUDE.md §2/§3、
  available-skills、磁盘目录的勘察归子2 已完成面——gate 方框二同向：
  绑定理由出处=子2 trace 引用即合规）。
- **红队材料包三钉**（#36 平移第二例，框架通用措辞）：①派发 prompt 逐字
  携带攻击对象材料包（需求清单+能力注册表出处+映射提案理由——均在主段
  会话上下文）；②红队职责=基于材料的独立**判断**攻击（映射逻辑/最小集/
  成本相称/强制优先），注册表存在性/需求出处以前序留痕为准零重验，禁重跑
  勘察类工具（codegraph/grep/ls 注册表目录/读 SKILL.md），确需复核 Read
  单点文件定点核对（每攻击点至多 1 次）；③攻击对象=映射提案整体一次。
- **交付即止**（#37 平移）：落库成功（✓ 已落库）即结束本轮——禁 python/
  Bash 验证落库、禁 locate 产物/读 state/grep evidence/预习子4。
- **格式真源**（#26 平移，断链暴露面同批补款 #30）：载荷格式唯一真源 =
  --scaffold 骨架+append-trace 报错文案——禁读引擎/测试源码/历史 trace
  反推格式；被拒按报错文案逐字修即可。

selfcheck 补：「子1/子2 留痕逐字引用零重验了吗（零 evidence 翻找/零注册表
重勘察）？红队 prompt 逐字携带材料包了吗（零重勘纪律写入了吗）？落库后
交付即止了吗？」

### 否决表

| 候选 | 否决理由 |
|---|---|
| MERGED 段内续步 | 步体 16 轮非极小搬运型（#24：步体调用越多携带税越主导，断链确定优）；节点级政策超单步范围（p1-sub4 同型）；u:3 撤出前科（暖率 1/4） |
| Node 工具白名单 | 已在册（p3-sub2-cost L1 五件 Bash/Read/Edit/Skill/Agent，子3 条件红队要 Agent ✓） |
| gate 文本修改 | §4 三查全过=零变更（复用引用形态与方框二同向，#34） |
| 节点级断链（plan:3 出册） | surgical：步级已覆盖；子4/子5 未做逐步核对，出册超单步范围（p3-sub2 §3 同判） |
| pack_full_prior_boundary | 复用材料=本节点 trace 全文通道，不经 boundary 截断面（p2-sub3 同判） |

## 4. gate 零变更三查（#29）

①mech 词表：子3 mech=binding_residue_trace（S2 注册表枚举 vs S3 出现集
差集）——复用钉死/材料包条款不改变双向追溯矩阵的列举义务（能力名仍须
逐条出现），词面无冲突；②judge 方框：方框二合法形态已认「子2 ③出处」
引用=复用钉死同向（#34：判据结构性封死包外出处面）；方框一 mech 承托
不变；红队材料包条款收窄的是 agent 行为非 trace 留痕形态（红队留痕/条件
未触发声明义务不变）；③复用引用形态（「复用 子2 留痕：…逐字」）不命中
任一 block 条件（方框二~五均不要求本步新跑命令）。三查全过，零 gate 文本
改动，免 replay。

## 5. 预登记（B vs A，验收口径）

| 指标 | A 预测（机制算术） | B 预登记 | 机制归因 |
|---|---|---|---|
| 首调 fresh | ~103-106k（子2 transcript 101k 冷重写+step prompt） | ≤45k（-57%+） | L1 去冷重写（fresh 地板 ~40k 含白名单 -14.3k）+ L2 strip -11.9k + 条款回补 |
| 轮数 | 16（老链段实测） | ≤20（暴露面上限；目标 ≤16） | L4 交付即止 -1，fresh 化格式轮 +1-2 上限登记 |
| 工具调用 | ~7+Agent | ≤7+Agent | 行为面已地板（#40），条款=方差防守 |
| 段 cr | ~1.6M（100k×16 调） | ≤640k（-60%+） | L1 每调重读 100k→30-45k × 轮数 |
| 段 out | ~12k+红队 19.7k | ≤基线+15% | #33 out 回馈登记：引用义务零新增（gate 方框二原已要求引子2 出处=p3-sub1 反例形态），thinking 1.9× 观察项 |
| dur_api | ~100-130s | -30% | out÷rate + 每调 cr 变小调用更快，双轴分开登记 |
| 成本等效（主段+红队合并） | ~295k（主段 ~264k+红队 ~31k） | ≤135k（-55%+） | 主验收轴 |
| 红队 agent | ≤2 调用/0 重勘 | ≤2 调用/0 重勘 | L4 三钉方差防守（维持健康形态） |
| mech 拒 / block | 0 / 0 | 0 / 0 | 硬约束 |

trace 质量逐条自查（防 Goodhart）：双向追溯矩阵齐备、每条绑定附理由+子2
出处+被否替代、重型手段成本辩护/条件未触发声明、红队留痕或条件未触发
声明、提案-待裁决语义、零编造——复用钉死不得稀释追溯接地（绑定仍条条
有出处，出处生产时间前移到子2）。

## 6. 混淆声明

- amplitude 今日值 4929.2%（用户明示）vs 种子 problem_statement 4824.5%
  原文 = #18 漂移面（种子逐字一致纪律，runtime-audit #25）；plan:3#3 与
  因子数值零判面接触（映射选型不碰数据文件），登记不处置。
- A 链内段（resume 子2 fresh 会话）/ B fresh 段口径差 = L1 处置本身
  （p3-sub2 §1 三查③同型声明），非混淆。
- A/B 双臂首调均含 Node 白名单 -14.3k（p3-sub2-cost L1 在 14571cf 已在册，
  双臂同基）——白名单收益不计入本设计杠杆。
- 并行会话在飞：p3-sub2-cost（未 merge，本分支从其 HEAD 14571cf 切出，
  A 臂复用其实例状态副本与 worktree 码——其 B 轮已收段，实例只读复用
  零干扰；merge 并轨收口：SEGMENT_CHAIN_SKIP_STEPS 同 frozenset 相邻行、
  nodes-index plan:3 行、测试计数）。
- 种子 instance 复制纪律：A/B 双臂 settings name-agnostic 核对（statusline
  --name 改实例名）；evidence 副本独立（p3_sub3_base.jsonl /
  p3_sub3_ab.jsonl）。

## 7. 测试与回滚面

- 新增测试：①`("plan:3", 3) ∈ SEGMENT_CHAIN_SKIP_STEPS` pin；②子3
  segment_strip_project_context + pack_self_contained flags pin（既有 flags
  断言同步更新）；③子3 purpose/selfcheck 条款 pin（复用钉死/材料包三钉/
  交付即止/格式真源关键词，镜像 p3-sub2 ③形态）；④pack 装配不变量
  （子3 置位步包内本子1/子2 trace 全文在场）。
- 回滚面：skip 集摘条目 / Step 两 flag 置 False / purpose 段落整删，单点
  翻转，兄弟步零暴露。
- ruff check + format；pytest 全绿（基线 1191+新增）。

## 8. A/B 跑法（runtime-audit #25 + #24 三纪律）

①实例复制：`cp -r .claude/workflows/p3_sub2_ab` 两副本（p3_sub3_base /
p3_sub3_ab）+ evidence 副本改名；settings 验 name-agnostic（statusline
--name 改实例名；hooks 路径 launcher 覆写）；state 四字段已在 plan:3#3
入口（将跑=3，零改动）+ segment_sessions/chain 保留（A 臂链 resume 需要）
——B 臂同态保留（断链由代码侧 skip 集判定，非种子侧清链）。②跑法（串行，
A 先）：`AC_WORKFLOW_LAUNCHER=<对应 worktree>/scripts/workflow/dl-launch.sh
ac-deepseek1 --dl <实例> --resume --headless` 后台；子3 gate 过（state 将跑
翻 4）即停 driver 收段统计。③核验：driver 日志特征行——A 臂「⟂ 段链续跑
（plan:3 链，子3）」在场 / B 臂缺席；init 事件 tools 白名单五件；B 臂 env
双 DISABLE 生效（strip）。④读数：drive-stream 按 result 事件切段，首调
fresh=段内第一个 assistant usage，逐段 modelUsage=段合计；红队 agent 账
目=transcript subagents/ 归集合并（#36）。

## 9. 实测收官（2026-08-20，A=p3_sub3_base 子3 段[14571cf 链内] / B=p3_sub3_ab 子3 段[四杠杆 fresh]，同种子同源，ac-deepseek1/deepseek-v4-flash headless）

| 指标 | A（14571cf） | B（四杠杆） | B vs A | 预登记 | 验收 |
|---|---|---|---|---|---|
| 首调 fresh | 131,098（cr=0 链冷） | **30,016**（cr=0） | **-77.1%** | ≤45k | ✓（断链去 101k 冷重写 + strip -11.9k + 条款回补=机制算术命中） |
| 轮数（result 权威值） | 13 | 6 | -53.8% | ≤20（上限） | ✓ |
| 工具调用 | 45+红队 33 | 5+红队 0 | **-93.6%** | ≤7+Agent | ✓ |
| 段 cr | 2,885,248 | 208,128 | **-92.8%** | ≤640k | ✓ |
| 段 out | 93,651 | 56,588 | -39.6% | ≤107.7k（基线+15%） | ✓（A 的 out 含翻找产出褶皱） |
| 段 dur_api | 743.5s | 432.5s | -41.8% | -30% | ✓（out÷rate 双端拟合 ~130 tok/s=输出量主导，#30） |
| 段墙钟（首→末事件） | 727s | 285s | **-60.8%** | | |
| 主段等效 | 489,579 | 108,240 | -77.9% | | |
| 红队 agent 等效 | 602,465（82 调用/33 工具重勘） | 14,432（2 调用/0 工具） | **-97.6%** | ≤2 调用/0 重勘 | ✓（#36 第二例实证） |
| **合并等效（主验收轴）** | **1,092,044** | **122,672** | **-88.8%** | ≤135k | ✓ |
| append-trace mech 拒 | 0 | 0 | | 0 | ✓ |
| 门控 | 零 block | 零 block（一次过） | | 零 block | ✓ |

**B 工具序列（理想最小形态）**：scaffold → Agent（红队，prompt 逐字携带
材料包三钉）→ Read 骨架 → Edit 填充 → append 一次过。零 evidence 翻找/
零 plan.md locate/零注册表重勘察/零数据文件核验/零交付后徘徊。

**trace 质量逐条自查（防 Goodhart）**：6 组 q/a——逐任务绑定附理由（「复用
子2 ③留痕逐字」形态引用 trigger/description 出处）+被否替代 ✓；最小集
每能力≥1 需求+强制项优先 ✓；重型手段（长 pipeline 1 项）成本相称辩护
✓；双向追溯矩阵双向无漏 ✓；红队触发依据+材料包三钉留痕+**真攻击结论
（攻击点 1 采纳=codegraph U2 条件强制改映射）**=攻击深度未被条款收窄
✓；提案-待裁决语义 ✓。引用形态接地零稀释。

**A 臂爆炸形态归因（§2 订正的实证面）**：45 调用中 evidence 翻找 ×20
（包尾通用邀请「以上为摘要；按需 Read evidence」=#16 反指邀请兑现）/
plan.md locate×9（产物指针+记忆错位）/注册表重勘察×3（CLAUDE.md/
SKILL.md/ls skills）/数据文件核验×4（ob_quality ls=子4 判面越界）/
redteam_probe.py×3（自造探针验证红队发现）；红队 agent 无材料包 →
82 调用重勘（Bash×30：grep evidence/读 SKILL.md/ls 数据文件全谱系）。
**同种子同 gate 同前序 trace，唯一变量=条款有无**——方差本身是油水。

**耗时达标确认（用户目标「耗时和 token 大幅降低」）**：token 轴合并等效
-88.8%；墙钟轴段墙钟 -60.8%（727s→285s）+红队墙钟收敛（A 红队 82 调用
vs B 2 调用），整步墙钟（含红队等待）从 ~17min 降至 ~5min 量级。

**混淆声明复核**：①A/B 双臂首调均含 Node 白名单 -14.3k（同基 14571cf），
白名单收益未计入本设计杠杆 ✓；②amplitude 今日值 4929.2% 漂移未触发
（B 零数据文件核验条款消灭 A 的 ob_quality ls×4 越界面，映射选型不涉
因子数值）✓；③段口径差（A 链内/B fresh）=L1 处置本身 ✓；④B 段
dur_api（432.5s）>段墙钟（285s）=口径噪声（dur_api 疑含子代理 API
时长，out÷rate 拟合主段成立），wall 口径以首末事件为准 ✓。

**pytest**：1196 全绿（新增 5 例：断链豁免行为/flags+env 生效面/条款 pin/
包尾切换/材料不变量）。

## 10. 遗留

- merge 并轨清单：strips 断言 [F,F,T,...]→[T,F,T,...]（main 已有子1 strip
  第十四例）；nodes-index plan:3 行与 p3-sub2 收官 footer 并轨；沉淀编号
  按收口时 git log 最大值+1；测试计数对齐。
- plan:3 子4/子5（链 resume 换挂子3 fresh 会话，继承变小同向）成本立项
  候选——子4 可用性核验=核验型步（p2-sub3 同型，复用钉死枚举例外形态
  候选）；子5 归一化=搬运型（pack+复用钉死候选）；子6=读回步零成本
  关闭清单（#22）。
- 红队预派发判据核对（#12）：子3 红队攻击对象=步内产出的映射提案
  （输入未冻结、prompt 不可脚本生成）=维持模型派发+材料包钉死形态，
  不立项预派发。
