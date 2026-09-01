# 取证分档判据修复设计（fetch-tier-overescalation-fix）

> 2026-09-01。触发：web_ui_interaction u:1 审计 + 用户 /goal 指派实测验证。

## 问题（实证）

web_ui_interaction u:1 子4「双向取证」635s/$2.81，子5 三关质检 20 条证据中外部
3 条（E1 empyrical 源码/E2 文献指针/E3 反证零命中）**全部不承重**——主谓词由
仓内数值+公式+契约三重闭合，量级锚点由仓内 default 管线对照（E4）承担。

根因（规则层，非模型执行层）：

1. **规则内部矛盾**：`_FETCH_TIER_RULE` 网关测试（外部结论不改变方向→none）
   与档位枚举（量级合理性→full）打架；模型照枚举行事=合规但错配。
2. **激励单向**：block 威胁只在漏取证侧（v2.56 操作测试 + gate 方框二），
   过度升档零成本——矛盾处弱模型必选重档。
3. **full 档执行无收敛条款**：agent 12/12 轮烧完，反证 2 轮零命中+源码级
   证据已取后仍继续（层配额纪律无提前收尾例外）。
4. **外部机制证据无适用性对拍**：empyrical「coverage-blind 年化」叙事对
   本仓已乘 coverage 的公式不适用，靠红队事后人工纠偏。

## 修复（4 处，对应编号 = 审计建议 #1/#2/#4/#5）

| # | 文件 | 改动 |
|---|---|---|
| 1 | dl_flow_nodes.py `_FETCH_TIER_RULE` | 网关测试升一票前置（枚举只在网关通过后分流）；加「锚点先查」正向判据（仓内有同口径对照→至多 light）；full 示例限定「仓内确无对照基线」；full 档 tier_reason 须附仓内已查举证 |
| 2 | dl_flow_checks.py `_check_fetch_tier_items` | 新增 `_FULL_TIER_JUSTIFY_RE`：tier=full 时 tier_reason 须含路径指针或「已查仓内…无」式声明，缺则 append-trace 当场拒（与 none 档对称） |
| 3 | dl_flow_nodes.py 子2a purpose/selfcheck/gate | 三处文案同步机械校验新要件；gate 方框二加窄判面「full 档举证失真」（称仓内无对照但论证自身引用仓内同口径锚点=自相矛盾判 block） |
| 4 | dl_flow_trace.py fetch 骨架 | 纪律 9 加「够用即停」（反证 2 轮零命中+≥1 条源码级证据→允许提前收尾，标「够用即停」不算纪律 10 配额违规）；返回契约加「外部机制证据适用性对拍」（引用第三方库机制须与本仓实现 file:line 对拍，未对拍标「背景·不承重」） |

## 验证（用户 /goal 钉死的验收）

用 ac-deepseek1（deepseek-v4-flash）对子2a 定档步做重放实测，两类问题迭代至达标：

- **简单问题**（web_ui 5713.9% 案重放）：atom1 应落 light/none → 时间消耗少
  且仓内+轻量外部锚点有实质性帮助；
- **复杂开放问题**（无仓内锚点的方法论题，新构造）：应落 full → 外部取证
  有实质性帮助（报告证据直接针对 claim 谓词、可承重）。

回归：tests/test_dl_flow_engine.py TestFetchTier 全绿；旧 full 档合理案例
（amplitude_annualized）分档不被误降。

## 非目标

- 不改 judge 模型/harness；不改 none/light 档既有判据语义；
- 不做承重率台账聚合（攒样本轨道，后续独立项）。

## 实测结果（2026-09-01，ac-deepseek1=deepseek-v4-flash，harness=/tmp/tier_replay/harness.py）

重放方式：claude -p 只读白名单、cwd=/tmp、无 workflow settings（探针纪律）；
定档步镜像 max_explore_calls=8；取证 agent 用真源 fetch_prompt 骨架。

**简单案（web_ui 5713.9% 重放）——达标**
- 定档 205s：A 量级=light（锚点先查命中 backtest/result/default/ 同因子 12%/
  ob_quality 57% 对照）、B/C/D=none（均附 file:line）；机械校验 PASS。
  旧规则下 A 必落 full（枚举明文）。
- light 取证 96s/4 curl：锚点「异象多空年化个位数至低双位数%」与仓内锚点
  一致、实质佐证；未收敛按契约标「建议升档」留痕不自行加码。
- 全程 301s vs 原路径 910s（275s 定档+635s full 取证）= **-67%**。

**复杂案（T+1/涨跌停离线评估方法论，新构造）——达标**
- 定档：3 方法论原子=full（举证「已查仓内无对照」合法）+1 管线核查=none。
- 单原子 full 取证 182s、12/12 预算恰好收敛：2 条谓词级强证据
  （Expanded Implementation Shortfall、arXiv Implementation Risk in
  Portfolio Backtesting）+ 对拍仓内缺口（:166 固定费率、:284-286 无涨跌停
  过滤）；机制证据「背景·不承重」标注被正确使用（#5 生效）。

**测试中逮到的附带 bug（已修）**：骨架分档清单被 agent 当任务单——3 full
原子场景单代理把 3 个原子全取一遍（38 curl、原子2 超预算 20/12）。多原子
生产派发会 N× 重复取证。修=骨架纪律 12「只取 claim 区列出的原子」，重放
验证：单代理 182s 只取本原子、预算 12/12 恰好。

**未触发项留痕**：够用即停条款两轮测试均未触发（agent 持续有命中，属正常）；
judge 对称判面（gate 方框二 full 举证失真）未做 live 重放（机械校验已拦截
形式层，语义层待真实运行攒样本）。
