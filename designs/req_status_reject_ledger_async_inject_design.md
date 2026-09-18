# req_status 写侧补全 + 拒绝留痕 + inject 异步化

> 2026-09-18。实爆：plan:1#2 注入轮落 trace 挣扎 37min（10 连拒同一 32 字符短报错，最终内联 python 构造载荷才过；POST 同步阻塞全程零反馈）。改动范围：`dl_flow_trace.py` + `dl_dashboard/actions.py` + `dl_dashboard/app.py` + `dl_dashboard/static/app.js` + 测试。

## 三项根因与方案

### T6a req_status 写侧通道（mechanical §14 第二实例）

req_status（plan:1#2 三态裁决键）与 req_items 同坑：parser 字段集缺 status/reason、行首规则错、scaffold 只给【q】待填——昨天修 req_items 时漏了它（§14 清单没全量执行）。补全：字段集 +status/reason、`_MD_ROW_STARTERS` +req_status:{"id"}、scaffold 三态行模板。**教训升级：§14 清单要全量遍历注册表执行，不能只修报告的那个键。**

### T6b 拒绝留痕（trace-rejects.jsonl）

10 连拒但会话转录只存 text_chars 不存内容——事后无法审计校验器在拒什么。`append_trace` 改包壳：所有拒绝落 per-实例 `trace-rejects.jsonl`（ts/node/sub_step/reason≤4000字符），留痕自身故障不阻断主流程。拒绝原文是门槛披露面优化的第一手数据。

### T7 inject 异步化

POST /api/inject 同步等整轮模型（本次 37min）→ 改异步受理：快速拒绝路径（未就绪/已覆盖/在飞）同步判，受理即返回「已受理」+ 后台 asyncio task 执行（锁内起跑前复核防快速连点竞态）。失败上报通道：injecting.json 转**错误态**（不删——POST 已回，错误态是唯一用户可见面），detail 下发 `inject_error`，前端表单上方红字提示可直接重答；state 推进后错误标记自清。`_BG_TASKS` 持引用防 GC。

## 验证

TDD 8 测（req_status 解析/scaffold/e2e + 留痕写/不写 + 失败错误态/陈旧自清 + 异步受理秒回且后台执行）；全量 1630+ 绿；ruff 过。
