# dashboard 已答标记 + 问题卡步骤绑定设计

> 2026-08-31，web_ui_interaction 实例实爆（同日第二起，第一起 = dashboard-segment-autocontinue-design 的 driver 停摆）。
> 用户投诉：提交答案后问题卡仍可点可提交（不知道提交成没成功）；步骤推进后旧问题卡还挂着，看不出工作流在跑还是在等人。

## 1. 两个缺陷，一个根

**D1 已答窗口**：`inject_ready()` 只看「当前步有无 tui-step-needuser 段台账」。inject 成功 → 门控推进前（实测窗口 ~3 分钟），段台账还在原位 → inject_ready=True → 前端重渲染完整表单 → 可重复提交（double-inject 风险 + 「到底交没交上」困惑）。「转圈防连点」只挡请求飞行期，server 返回后下一轮 SSE 轮询即破防。

**D2 陈旧问题卡**：`need_user.json` 无步骤绑定，detail 端点无条件渲染。state 已推进到 u:1#2（headless 步在跑），页面仍挂 u:1#1 的「等待输入」卡——用户无法区分「在跑」还是「等我」。

**根**：没有任何机制表达「这份问题已被回答 / 这份问题属于哪一步」。

## 2. 设计

### 2.1 步骤绑定（driver 写侧，dl_drive.py）

`_stash_need_user_payload` 增 `bind_key` 参数（`"<node>#<sub_step>"`，与 `prep_next_key`/`next_prep_stashed` 同构单源）：
- NEED_USER 通道：bind 当前步（问题属于本步）
- NEXT_PREP 通道：bind `prep_next_key`（lookahead 目标步——消费侧本就按目标步 id 查，天然对齐）
- 无 bind_key（旧格式文件）→ 不写绑定字段 = legacy

### 2.2 已答标记（dashboard 写侧，actions.py）

inject 成功 → 写 `answered.json`（meta 下）：`{node, sub_step, need_user_ts, answered_at}`。

**覆盖判定**（`answered_at_if_covers`，纯计算自失效，无需清理）：
覆盖 ⟺ marker(node, sub_step) == state 当前位置 且 marker.need_user_ts == need_user.json 当前 ts。
- state 推进 → node/sub_step 错位 → 失效 ✓
- 新问题落盘（含 rework 重问）→ ts 变 → 失效 ✓（用户可重新答）
- need_user.json 缺失 → 无卡可覆盖 → None

**消费点**：
- `inject_ready()` = 段台账在位 **且未被覆盖**（D1 修复——提交后按钮不再复活）
- `inject_answer()` 前置拦截：已覆盖 → 中止「已注入过」（server 侧双保险，防 double-inject）
- detail 端点暴露 `answered`（answered_at 或 null）→ 前端显示「答案已提交，处理中」横幅替代表单

### 2.3 陈旧卡过滤（dashboard 读侧，app.py detail）

need_user 载荷带绑定且 ≠ state 当前位置 → 不渲染（need_user=null）。
- 已过步的旧卡消失（D2 修复）
- NEXT_PREP 预备的未来步问题：在 state 到达目标步之前也不渲染（到达 → P2-1 段落台账 → 表单；中间窗 → 「准备中」——渐进式呈现，不再提前挂「等待输入」误导）
- legacy 无绑定 → 现状放行（注释写明 + 测试 pinning）

### 2.4 前端（app.js renderInteract）

新增首分支 `d.answered` → 「答案已提交」横幅（时间 + 「门控通过后自动推进，无需重复提交」），后续分支不变。

## 3. 不改的面

- driver 消费 need_user.json 的 P2-1/needuser 流程：零改动（绑定字段纯增量，consumer 只读 questions/sources）。
- inject 端点「停-注-重驱」时序铁律：不动。
- answered.json 不主动删（ts/位置比对自失效；删 = 多一个写点多一份竞态）。

## 4. 测试

- actions：marker 写入 / 覆盖时 inject_ready=False / 新问题 ts 变恢复 True / state 推进恢复 True / 重复注入中止 / need_user 缺失不覆盖
- app：绑定不符 → need_user=null / 绑定相符 → 渲染 / legacy 无绑定 → 放行（pin）/ answered 透传
- driver：stash 带 bind_key 写 node+sub_step / 不带 → 无绑定字段
- E2E（真实 dashboard + 真实例）：create → 答题 → 断言 inject_ready 翻 False + answered 出现 + 工作流自动续跑不退出

## 5. 兼容

- 在跑实例（web_ui_interaction）：旧 need_user.json 无绑定 → legacy 放行（陈旧卡暂存，下次 stash 带绑定即愈）。driver 改动（绑定字段）对在中 driver 零影响（写侧增量）。
- dashboard server 需重启加载新 actions/app 代码（driver 是 setsid 子进程，/proc 认领，不受影响）。
- 回滚面：三处增量各自独立可翻。

## 6. 修订 v2（2026-08-31 E2E 实爆两连——v1 合并后当天真机验证抓出）

v1 合并后做真实 dashboard E2E（throwaway 实例），两处在单测里看不见的问题现形：

**E1 标记失效判据太脆（ts → 内容 hash + block 裁决）**：v1 用 `need_user_ts` 相等判覆盖。实测 driver 的 none 重试循环会对**同一步同一批问题**重 stash（ts 必变）→ 注入后 ~90s 标记即失效、按钮复活——D1 在真实流程里没修住。改判据：
- 覆盖 ⟺ 位置匹配 **且 questions 内容 hash 匹配**（重 stash 同内容 hash 不变 → 仍覆盖；问题真变了 hash 变 → 失效）
- **且 answered_at 之后无本步 kind=gate/gate=blocked 裁决**——block = 答案被判不足，重答是 rework 正路，必须放行（否则 escalate 后用户永远没法重答 = 卡死）。ts 字符串比较成立（双侧同 `_now()` 格式）

**E2 注入会话可能不落库（-p 一次性轮的结构脆弱）**：E2E 注入垃圾答案后，resume 会话把注入当新陈述、**用文字重问问题**（-p 无人可答）→ 会话结束、零 trace → 门控 none → driver 重 stash 重问 → 用户看到同一张卡又能提交——「提交答案后还能提交、工作流没跑」的真正根。这正是 prompt-engineering §3.7 原则 9/10 的场景：
- **机制层**：inject 命令移除 AskUserQuestion（-p 无真人，调了也是立即报错的白费轮；原先 ov tools 置位时反而主动加回——删）
- **prompt 层（一次性注入包装）**：注入文本包一层任务书——置顶声明「本消息 = 一次性注入，之后无人可答，禁止重新提问」（给 rationale 防合理化）+ 答案原文 + 立即执行三步（映射问题 → append-trace 落库 → STEP_DONE）+ 缺漏如实标注由门控裁决
- **验证 = 真机 dogfood（原则 10）**：E2E 重放全链路（注入 → 标记持续覆盖跨重 stash → trace 落库 → 过门 → 自动续跑），不是词面断言

**附：inject 端点拒绝文案失真修**：已覆盖时端点先撞 inject_ready=False 返回通用「未就绪…driver 已停请恢复驱动」（误导）——改先查覆盖返回「答案已提交，无需重复提交」。
