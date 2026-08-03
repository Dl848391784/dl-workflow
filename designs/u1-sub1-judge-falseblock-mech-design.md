# v2.71 understand:1 子1 judge 误伤根治（mech 接管 + framing 收口）

> 起源：tail_volume_acceleration_annualized u:1 子1 连续两次 block 诊断。
> v2.70 修了 who「选中角色选项=自述」接口后，MiniMax 重放暴露 judge 对合规
> 载荷 ~1/6 误伤--纯文案杠杆无法压到 0，需 mech 接管可机械化的误判项。

## 根因（6 变体 ~70 次重放实证）

| 变体 | len | clean | att2 | att1 |
|---|---|---|---|---|
| V0 生产(从严) | 1954 | - | 1/4 | 4/4 |
| V2 瘦身+正例 | 524 | 1/6 | 5/6 | 6/6 |
| V3 默认-PASS | 228 | - | 4/4 | 4/4 |
| V3c +5方框 | 375 | 1/6 | 4/6 | 5/6 |

无变体 clean+att2 同时全 PASS。误伤分类与可机械性：
- ②原话佐证套到①（~6 次）✅ 可机械（结论前缀判定方框适用性）
- 选中项≠原话（~4）✅ 同上
- 应对动作非痛点（~4）❌ 内容真值
- 修复诉求泛化（~2）❌ 内容真值
- who 选中当仓库事实（~2）✅ 关键词扫描

## 改动范围（本轮，3 文件）

1. **dl_flow_engine.py**：新增 `_check_who_no_repo_fact` mech check（who 项
   含 CLAUDE.md/git config/分支命名关键词当场拒）+ 注册 `_MECH_QA_CHECKS`。
   v2.71 framing 收口见 nodes。
2. **dl_flow_nodes.py**：u:1 子1 gate 改 V2 framing（瘦身+正例+默认-PASS），
   从 judge 判面移除 who 出处合法性（下沉 mech）；mech_checks 加 who_no_repo_fact。
3. **tests/test_dl_flow_engine.py**：TestWhoNoRepoFact + 重放回归。

## 能力边界（如实）

mech 接管 who/原话方框后，残余误伤 ~1/6（应对动作/修复诉求泛化=模型推理底）。
兜底：prior_verdicts 一致性指令 + escalate 阈值。不为此换模型（弱模型优先）。
