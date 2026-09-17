# 段派发自动预生成 trace 载荷骨架（文案失效 → 机制）

> 2026-09-17。改动范围：`scripts/workflow/dl_drive.py`（build_step_prompt）+ 测试 `tests/test_dl_drive.py`。

## 根因（实爆）

GLM-5.3-Flash（qoder 引擎）u:1 记录步段 30min/375 工具调用狂奔（Bash 208/Edit 167），全程没产出合格 trace：

1. 开场元探查找 evidence 落库位置——node-rules 明令禁止且给了现成命令，照走不误；
2. 不走 --scaffold，手写逆向猜 req_items 格式，167 次 Edit 试错；
3. 被杀时还在试。

披露侧审计：段 prompt 三件套（scaffold 命令/编号步骤/禁元探查禁令）**一直在场**——文案已尽，弱模型不听。按弱模型优先原则：文案失效 → 机制堵入口。

## 方案

派发即生成：`build_step_prompt` 非 prep 分支在装配 prompt 前，载荷不在场则调 `engine.scaffold_payload` 预生成（幂等：拒覆盖 + v2.63 stale 清理），deliverable 指引从「三步流程（先跑 scaffold…）」改为「骨架已在 `<钉死路径>`，Read→填→from-file <路径>`」。

机制效应：模型「找文件→Edit」的本能直接落在钉死路径的待填骨架上；手写自创格式被「骨架在场 + 拒绝文案附骨架全文（0a66213）」双杀。prep 段禁落 trace（既有铁律），不预生成。

## 验证

TDD：非 prep 派发→骨架落钉死路径+prompt 含路径；幂等（二次调用不覆盖）；prep 段不生成。全量 pytest + ruff。
