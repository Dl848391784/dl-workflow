# inject 在飞标记（injecting.json）——提交后到 answered 前的窗口治理

> 2026-09-18。改动范围：`dl_dashboard/actions.py` + `dl_dashboard/app.py` + `dl_dashboard/static/app.js`（+测试）。

## 根因（实爆）

提交答案后刷新页面：选中的答案没了、按钮复活可再提交。机制链：answered.json 要等 inject 子进程（整轮模型，1-3min）**成功后才写**（actions.py inject_answer 尾部）——整个在飞窗口无任何落盘标记，刷新后 detail 无 answered → 表单复活。虽服务端 `_lock` 串行 + answered 兜底使真正 double-inject 不发生，但窗口内「未触发」与「处理中」不可分（症状 AW 第三段的显示面）。

## 方案

在飞标记三件套：
1. `injecting.json`（meta 根）：inject 子进程**起跑前**写（started_at/node/sub_step/questions_sha），`finally` 删（成功由 answered.json 接续）；server 崩溃残留 = mtime > 30min 判 stale 自动清理（inject 无超时上限，宁宽勿窄）；
2. `inject_ready` 在飞期间 = False（double-submit 防线从「inject 完成后」提前到「inject 起跑」）；detail API 下发 `injecting` 字段；重复提交文案如实（「答案注入中」非「未就绪」）；
3. 前端：`d.injecting` → 「注入中」卡（刷新可见），入指纹。

## 验证

TDD：在飞→inject_ready False + injecting_since 有值；stale 自动清理；inject 成功/失败两路标记均删、answered 仅成功路在。全量 pytest + ruff。
