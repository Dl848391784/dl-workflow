# redteam-taskid-pairing：task-id 配对判据跨步已归位豁免设计

日期：2026-08-22　分支：feat/redteam-taskid-pairing

## 1. 背景（实证）

2026-08-22 interaction_turnover__ret3d_abs_test_1 u:1 子5（质检裁决）墙钟
~14.4 min，其中 ~10 min 是纯返工死锁：

- 12:58:17 首次提交被 `_check_redteam_report_recorded` 配对判据拒：
  「trace 提到 task-id a1001db34a6f2c799, a9db63e8c214b1fbe 却无对应收录项」；
- 这两个 id 是**红队报告收录原文里引用的子4 取证 agent 的 id**
  （红队审子4 证据链天然引用前步取证结论）；且子4 trace 标题里
  **早已收录**（子4 ingest 正常完成）；
- 拒收消息还主动误导模型去 `--ingest-agent` 重复收录这两个 id ——
  收录后又触发 redteam_three_piece（取证报告被标成「红队输出原文收录」、
  缺推理链/置信度三件套）连拒两轮；
- 模型 5 次提交/2 次重建载荷后，靠**编辑红队报告原文删掉两个 id** 才过关
  （收录原文被动手脚 = 更坏的形态）。

## 2. 根因

v2.118 修 B 的配对判据：dispatched = trace 全文 task-id；recorded = 本步
qa 标题里的 task-id。**盲区：判据只读本步 qa，不知道哪些 id 已在之前
子步骤归位**——收录原文对前步 agent id 的合法引用被误判为「本步已派发
未收录」。

## 3. 方案

`_dispatched_vs_unrecorded_task_ids(qa)` 扩参
`(qa, project_root=None, name=None)`：dispatched 集合再减去
**evidence 里已有记录（任何子步骤）qa 标题中出现的 task-id**
（`_recorded_task_ids_in_evidence`——收录即带 id 到标题由
ingest_agent_report 脚本保证，模型无法伪造）。

- 调用方 `_check_fetch_report_recorded`（_ctx 传 project_root/name）与
  `_check_redteam_report_recorded`（形参已有）透传；
- project_root/name 缺省（旧测试直调）-> 不豁免，行为不变（向后兼容）；
- 两条拒收消息补一句「已收录于前步 trace 的 task-id 引用不算本步派发
  （已豁免）」，防模型再被指路去重复收录。

### 语义核验（真值表）

| 场景 | 旧 | 新 |
|---|---|---|
| 子4 派发 full 升档 agent、未收录（v2.118 原实证） | BLOCK | **BLOCK**（无前步记录，保留牙齿） |
| 子5 收录红队报告，正文引用子4 已收录取证 id | BLOCK（假阳性，本次实证） | **PASS** |
| 子5 会话内新派红队（新 id 无前步记录）、未收录 | BLOCK | BLOCK |
| 子4 升档 agent 跨步归位子5、子5 已收录 | PASS | PASS |

宁纵勿枉方向不变：豁免只放过「前步标题里确已归位」的 id。

## 4. 测试

- `TestRedteamReportRecorded` 补两例：前步已收录 id 在收录项正文被引用
  （新=PASS）/ 无前步记录的 id 在正文出现且无收录项（仍 BLOCK）；
- `TestFetchReportRecorded`（或 agent_await）补一例：子4 引用前步已收录
  id 不拒；
- 既有 `_dispatched_vs_unrecorded_task_ids` 直调测试（qa-only）行为不变
  （缺省参数=不豁免）。
