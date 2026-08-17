# understand:2 子1（目标引出）耗时/token 优化设计

> 日期：2026-08-18 · 分支 feat/u2-sub1-cost · 状态：实施中
> 上游：designs/v4-cost-latency-optimization-design.md（P2-1 NEXT_PREP / P3-1 读回分级）
>      designs/interactive-step-headless-prep-design.md（交互步 prep 后台化）
>      designs/u1-overall-cost-optimization-design.md（段前缀三修 + 逐调用口径纪律）
> 触发 = 用户指令（2026-08-18）：「优化 understand:2 的 step1，耗时和 token 消耗要大幅降低」（承 u:1 子4/子5/整体前缀三轮优化之后）。

## 1. 基线实测（amplitude_annualized 真实数据，deepseek，2026-08-15~17）

u:2#1 = 交互 decision 步，现行链路三段：prep 段（headless 备问题）→ Q&A 会话（needuser 逐字照抄提问 + 落 trace）→ judge。本工作流 u:2#1 三度到达三度 state-reset（u:1 A/B 副产），prep/Q&A 各 3-4 个真实样本，trace 写入轮与 judge 未发生（用户未答）——基线为「到提问为止」口径，完成态只多不少。

| 构成 | 样本 | 墙钟 | fresh in | cache_read | out | 成本 |
|---|---|---|---|---|---|---|
| prep 段 | 4 | 57-128s | 47.3-64.7k | 40-92k | 7.9-16.2k | $0.54-0.69 |
| Q&A 会话（未含落库轮） | 3 | 44s-2.5min | 46.6-59.8k | 97-540k | 7.8-23.2k | — |
| 合计（一次到达） | — | ~2-4 min | ~95-125k | ~140-630k | ~16-40k | ~$1.2+ |

### 成本归因（逐调用拆解）

1. **prep 段 = 纯系统税**。交付物只有 need_user.json 问题清单（~2k）。63k fresh 的构成：harness 地板 ~22.5k + node-rules ~1.2k + 交接包 ~0.5k（O3 后）+ **Read evidence 全量 63KB ≈ 21k** + 输出 16k。它读全量 evidence 只为拿两样东西：子6 归一化陈述（**已在交接包里**）+ 子1 用户原话 q/a（出处纪律）。
2. **Q&A 会话重复读同一个 evidence 全量**（再 21k fresh + 63KB 进上下文，后续每轮 cache_read 都背着它）——为写 trace 的出处（用户原话），而它拿到的 need_user.json 里只有问题清单没有出处材料。
3. **同一上下文被两个会话各付一遍**：prep 读完证据设计问题，Q&A 再读一遍证据写 trace——子1 用户原话在 u:1#6 段会话的交接包里**本就在场**（本节点前序 trace 全文通道）。

### 关键观察（本设计的支点）

u:1#6（归一化陈述）段会话的上下文 = 子1-5 trace 全文（含子1 用户原话 q/a）+ 刚产出的子6 陈述——**恰好是设计 u:2#1 问题所需的全部材料，零额外读取**。P2-1（NEXT_PREP 顺带交付）机制已存在，但 lookahead 只看同节点下一步：u:1#6 的下一步是 u:1#7（confirm 级读回，P3-1 后无模型会话）→ prep_next=None → u:2#1 落回独立 prep 段。**confirm 步横在中间挡住了跨节点顺带交付**——这是 prep 段存在的唯一原因。

## 2. 方案（三修，全部机械层/装配层，零判据变更）

### 修A：NEXT_PREP 跨节点扩展（主修，灭 prep 段）

lookahead 从「同节点 cur+1」改为「按工作流线性序找下一个 decision 级交互步」：
- 跳过 confirm 级交互步（P3-1 后无模型会话，无问答可备）；
- 撞非交互工作步即停（None）——该步自己的段是更好的顺带交付点（不抢）；
- 命中 interactive && tier=decision → 作为 prep_next 并入当前工作段。

效果：u:1#6 段顺带备 u:2#1（子1 原话在包、子6 陈述刚产出，边际成本 ≈ 1.5k prompt + ~4k out + ~10s）；u:2#1 到达时 `_consume_next_prep` 命中 → 直接转 Q&A，**prep 段整段消失**。
同机制连带生效：u:2#4→u:3#1、u:3#4→u:4#1（同构 confirm 挡路场景）。plan:1#1→#2 既有行为不变（同节点，首命中）。
stash key 从「当前 nid#{cur+1}」改为**目标步全 id**（如 `understand:2#1`）——消费侧 key 本就是被消费步自身 id，天然对齐。

### 修B：载荷加 sources 出处包（灭 Q&A 的 evidence 全量重读）

- `_QUESTIONS_CONTRACT` 加 `"sources": [...]` 字段：prep 方（修A 后 = u:1#6 段）把本步写 trace 所需的**前序用户原话/会话事实逐字收录**进载荷（其上下文本就在场，零读取成本）。
- Q&A 侧双通道（drive needuser prompt 尾 + front 模式 workflow_phase.py code 13 注入）加条款：「载荷 sources = 本步 trace 出处材料，落 trace 直接引用；已覆盖处禁再 Read evidence 全量翻找，未覆盖才按指针补」（宁纵勿枉兜底保留）。
- driver 观察性：载荷缺 sources 字段时 disp.log 告警（不阻断——缺了退回现状自重读）。
- 判据零变更：gate 本就把「用户原话：'…'」按面值接受（judge 看不到会话原文），sources 只是把同一个引用动作从「Q&A 读 63KB 找」换成「prep 逐字抄进载荷」。

### 修C：state-reset 清陈旧 prep 载荷（修A 的安全前提）

跨节点 stash 后，用户可在 u:1#7 读回异议 → state-reset 回 u:1 任意步 → u:1#6 重跑会产生新内容，但旧 stash（key=understand:2#1）仍在位 → 陈旧问题清单直达用户。修：state_reset 无条件 pop `next_prep_stashed` + 删 `need_user.json`（任何回滚目标下都正确：重回 prep 源步会重新 stash；不重 stash 则走原独立 prep 段兜底）。

## 3. 预期收益（u:2#1 单次到达，deepseek 口径）

| 指标 | 基线 | 预期 | 机制 |
|---|---|---|---|
| fresh in | ~95-125k | ~45-55k（**-55~60%**） | prep 段 -65k + Q&A 免读 evidence -21k，u:1#6 边际 +1.5k |
| cache_read | ~140-630k | -30~40% | 63KB 不进 Q&A 上下文，逐轮少背 |
| out | ~16-40k | -20~30% | prep 段 16k 出清，u:1#6 边际 +4k |
| 模型墙钟 | ~2-4 min | ~1-1.5 min（**-50~60%**） | prep 段 57-128s 整段消失 + Q&A 少一读 |
| 等用户时间 | 不变 | 不变 | 问答本身不动（UX 契约零变更） |

护栏：一次通过率不降（修A 只是把问题设计挪到上下文更全的会话，问题清单仍逐字照抄通道）；judge 牙齿零变更（判据未动）；确认级/裁决级分级语义不变。

## 4. 影响面

- `scripts/workflow/dl_drive.py`：lookahead 助手（新）+ prep_next 赋值点 + stash key 目标化 + needuser 尾条款 + sources 缺告警 + `_QUESTIONS_CONTRACT`
- `dl_flow_engine.py`：state_reset 清账两行（pop state key + unlink need_user.json）
- `hooks/workflow_phase.py`：front code 13 注入加 sources 条款（一句）
- tests：lookahead 三态（同节点/跨 confirm/撞工作步停）+ stash/consume key 跨节点 + state_reset 清账 + 合同/条款断言 + 既有 1082 回归
- 三模式兼容：drive（needuser TUI）/ front（code 13 注入）共用同一 need_user.json 通道；v2（WF_TUI=1）无 prep 概念不动
- 在飞工作流：stash 只在 gate 通过后落、消费一次性——新旧代码交替最坏情形 = 落回独立 prep 段（现状），无劣化路径

## 5. 验证计划

1. TDD 红→绿 + 全量 pytest + ruff。
2. 真实 evidence 冒烟：amplitude_annualized 现有 evidence 直接过新 lookahead（u:1#6 位置应返回 u:2#1）。
3. **live A/B（ac-deepseek1，同仓新实例）**：种子 u:1 子1-5 trace 从 u:1#6 起跑——验收点：
   - u:1#6 段输出含 `### NEXT_PREP` + 载荷含 sources；gate 过后 stash key=understand:2#1；
   - u:1#7 confirm 不消费 stash；u:2#1 到达直接转 Q&A（drive-stream 无 u:2#1-prep 段）；
   - Q&A 会话零 Read evidence（transcript 工具调用核对）；逐调用 fresh/cr 与基线同口径对比；
   - 模拟用户作答（--resume 喂答案）完成落 trace + judge pass，验证全链路闭环。
4. 验收口径纪律沿用 #22：**逐调用前缀读数归因，全轮总账只作参考**。

## 6. 显式不做

- 不动 TaskList 18 项逐字建单（v3.3.1 用户裁决面；Q&A 短会话建单 ~3k out 记为未开杠杆，多轮数据后再议）；
- 不动交互步 prep 后台化架构（TUI 纯问答 = 用户裁决，修A 只是把 prep 并入上下文更全的既有段，不是回退到 TUI 自组织）；
- 不动 judge 判据 / gate 机制 / 读回分级语义；
- 不做 sources 的机械完备性校验（逐字收录是模型职责，缺失退回现状 = 宁纵勿枉；告警日志可观察）。
