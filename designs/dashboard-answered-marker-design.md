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
