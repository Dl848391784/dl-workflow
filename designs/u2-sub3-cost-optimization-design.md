# understand:2 子3（价值论证）耗时/token 优化设计——断链 u:2

> 日期：2026-08-18 · 分支 feat/u2-sub3-cost · 状态：实施中
> 上游：designs/u2-sub2-cost-optimization-design.md（u:2#2 材料边界优化，本设计承其 A/B 数据）
>      designs/u1-sub4-cost-optimization-design.md 修3（u:1 断链先例 + 预授权回滚机制）
>      references/cost-optimization.md #8/#9（续链膨胀根因=前一步 transcript；缓存经济性 provider 间不可外推）
> 触发 = 用户指令（2026-08-18）：「优化 understand:2 的 step3，耗时和 token 消耗要大幅降低；
> 跑测试工作流用 ac-deepseek1；amplitude 今日值 4920.2%」（承 u:2 子1/子2 优化之后）。
> 方案裁决 = 用户 AskUserQuestion 选定「断链 u:2」（三选项：断链/只断#2→#3/不动链落档）。

## 1. 基线实测（u2_sub1_ab + u2_sub2_ab 两轮真实数据，ac-deepseek1/deepseek-v4-flash）

u:2#3 = 价值论证与分层提案（受益者+价值链+量化基线 Bash 实测+must/nice 提案），
当前在段链白名单内（SEGMENT_CHAIN_NODES 含 understand:2），#2→#3→#4 同会话 --resume 续跑。

逐调用拆解（usage 去重 keep-max，同 id 内容块合并）：

**u2_sub1_ab u:2#3（基线轮，11 调，段墙钟 ~90s）**：
冷启动 **80,308** fresh（cr=0）= 本步 fresh 89,302 的 **90%**；cr 877k；out 12,907。
测量本身高效：2 次 find 定位 + 4 次 python -c 读 amplitude JSON（合计 ~1.3k fresh）。

**u2_sub2_ab u:2#3（现状轮，18 调，段墙钟 ~153s）**：
冷启动 **60,316** fresh（cr=0）= 本步 fresh 82,630 的 **73%**；cr 1,259k；out 21,004。
18 调中 13 调是基线测量探索（种子快照 0.495 vs 现状 0.492/0.1277 漂移驱动的口径核查，
#18 混淆项）；但即使剔掉混淆，冷启动 60.3k 仍是最大单项。

**u2_sub2_ab u:2#4（链税下游镜像，6 调）**：fresh 95,772，冷启动 **94,057 = 98%**；cr 533k。

**两轮段首调 cache_read 均为 0**——deepseek 流式缓存会话隔离（P0 实证），
链会话跨段续跑在本 provider 下恒冷：每段首调全量重写单调涨的继承 transcript = 纯增税
（cost-optimization #9 定性，u:1 已据此断链）。

## 2. 根因

**#3 的 token 大头是段链冷启动税（继承 #2 会话 transcript 全量重写），不是取证探索。**

- #3 本体已无冗余可砍：两轮零 evidence 全量重读（u2-sub2 优化已灭保险性回读），
  基线测量是 step purpose 规定的合法工作（③量化基线——Bash 实测现状）。
- 链机制的设计前提是 provider 前缀缓存跨进程 resume 保暖（kimi 全局缓存成立）；
  deepseek 会话隔离缓存下前提不成立，链 = 每段首调重付继承上下文（#3 60.3k/#4 94.1k），
  而 fresh 段首调是恒定 ~45k（harness 22.5k + node-rules 1.2k + 交接包 + step prompt，
  P1-1 水位）不随前序轮数涨。
- 交接包架构（v2.45）本就保证 fresh 段材料完备：#3 的输入契约 = 子2 aligned_goals
  （交接包「本节点前序 trace 全文」✓）+ PC statements（前序节点结论摘要 ✓）+
  who 出处用户自述（子1 trace 全文在包 ✓）。链会话记忆与交接包冗余。

**冲突声明**：2026-08-17 u1-sub4-cost 修3 决议「u:2/3/4 与 plan 族链峰值未破 250k，保留」
——那是 surgical 保留（没破就不动），非成本最优判定；本次用户明确指令降 u:2#3 成本，
且两轮实测链在 deepseek 恒冷，保留前提（暖缓存收益）在本 provider 不存在。
已经用户裁决覆盖该保留项（仅 understand:2，u:3/4 与 plan 族不动）。

## 3. 方案（一行断链 + 测试对齐，零新机制）

`dl_flow_engine.py`：SEGMENT_CHAIN_NODES 移除 "understand:2"（注释更新：断链依据 +
本设计指针）。机制零新增——白名单即回滚面，_chain_resume_sid 对名单外节点返回
None = fresh 段（pre-P2-4 的已验证行为，u:1 断链同款）。

**显式不做**：
- 不动 u:3/u:4/plan 族（链峰值未破 + 无用户指令，surgical）。
- 不新增 Step 级链控字段（备选方案「只断 #2→#3」被用户否了：收益减半+新增机制面）。
- 不动 judge 判据/gate 机制/交接包内容/测量动作本身（合法工作）。
- 不做 provider 感知链控（deepseek 断、kimi 链）——双 provider 分叉维护成本 >>
  收益，且 #13 实测 kimi 墙钟 2.1× 本就不作生产首选。

## 4. 预期收益（每轮运行，deepseek 口径）

| 指标 | 基线（链） | 预期（fresh 段） | 机制 |
|---|---|---|---|
| u:2#3 冷启动 fresh | 60,316 | ~45k（**-25%**） | 首调只写 harness+包，不背 #2 transcript |
| u:2#4 冷启动 fresh | 94,057 | ~52k（**-45%**） | 不背 #2+#3 transcript（包只多 #3 trace ~8k） |
| u:2 节点 fresh 合计 | ~194k（#2 39k+#3 60k+#4 94k） | ~136k（**-30%**） | #2 不变（链首段本就 fresh） |
| u:2#3/#4 cache_read | 1,259k/534k | 各 **-20~30%** | 段内每调重读的上下文基底缩小 |
| u:2#3/#4 段墙钟 | 153s/~130s | 各 **-10~20s** | 冷启动重写体量 -25%/-45% |

护栏：一次通过率不降（交接包材料零变更，fresh 段是 pre-P2-4 长期行为）；
judge 牙齿零变更；trace 内容质量不降（材料同源，只是不再背原始会话）；
front/drive 两模式同路径生效（_chain_resume_sid 单点）。

## 5. 影响面

- `dl_flow_engine.py`：SEGMENT_CHAIN_NODES 移除 understand:2 + 注释（≤10 行）
- `tests/test_dl_drive.py`：链测试面以 understand:2 为白名单样例的用例改 understand:3
  （test_chain_resume_sid/step_gap/node_mismatch/no_chain/chain_update_on_whitelisted）；
  test_chain_resume_understand1_rolled_back docstring 更新 + 扩为 u:1/u:2 双断链断言；
  plan 族白名单用例不动
- 三模式：drive/front 共用 _chain_resume_sid ✓；WF_TUI=1（v2）无段链概念不动
- 在飞工作流：state.segment_chain 里 understand:2 残留链下次 _chain_resume_sid 查
  名单即自然失配返回 None（不变式第一条件），无需迁移

## 6. 验证计划

1. TDD 红→绿 + 全量 pytest + ruff。
2. **live A/B（dl @ac-deepseek1，新实例 u2_sub3_ab）**：种子 = u2_sub2_ab 的 evidence
   裁剪至 u:2#2（五件套：裁 evidence/裁 last_judged_trace/清段记录与 stash/settings
   name-agnostic 验证/起跑前 handoff_pack 冒烟），从 u:2#3 起跑跑到 u:2#5/u:3#1 收——
   验收点：
   - state.segment_chain 全程不出现 understand:2 链（机制生效直接证据）；
   - u:2#3/#4 段首调 fresh 与 §4 预期对比（逐调用口径，#22 纪律）；
   - 零 block（node_attempts=0）、judge 全 pass、trace 质量目测不降；
   - u:2#3 基线实测环节数字与今日值 4920.2% 口径核对（ob_quality annual≈0.492）。
3. AC_WORKFLOW_LAUNCHER 指向本 worktree 的 dl-launch.sh（worktree A/B 驱动两前提：
   launcher 与 engine 同树解析；凭证不进命令文本，bashrc 函数体提取 env）。
4. 混淆声明预登记：种子数据若再漂移，#3 测量探索增量属 #18 混淆项剔出对比面，
   只比冷启动 fresh（链税直接度量，无混淆）。
