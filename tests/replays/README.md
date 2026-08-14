# tests/replays/ — 已反转 gate 的 judge 回归重放资产

> 由来：v2.76 确立「改 run_judge（judge prompt/指令行/harness 注）=全局 framing 变更，
> 所有默认-PASS gate 必须回归重放」（§3.5 #28/#29）。本目录是回归义务的**执行资产**——
> 载荷内嵌（禁读 evidence 行号，state-reset 会删记录，§3.5 #30 ②）。
> 设计：designs/replay-fixtures-persistence-design.md。

## 用法

```bash
# token 二选一：export ANTHROPIC_AUTH_TOKEN=sk-... 或写一行到本目录 .token（已 gitignore）
python3 tests/replays/replay_u1_sub1.py        # [N=6] [gate_file]
python3 tests/replays/replay_u1_sub2.py
python3 tests/replays/replay_u1_sub3.py
python3 tests/replays/replay_u2_sub1.py
python3 tests/replays/replay_u2_sub3.py
python3 tests/replays/replay_p1_sub1.py
```

- `N` = 每载荷重放次数，默认 6（n=4 全对是载荷巧合假象，§3.5 #28）。
- `gate_file` 可选：候选 gate 文本迭代用（先跑文件再落 nodes.py，#30 ④）。
- 判定标准：clean 全 PASS + vio 全 BLOCK（牙齿 <5/6 回炉）+ 既有 pin 测试全绿（#30 ⑥）；
  各脚本 docstring 有本节点专属读数口径（如 u11 real_borderline 1/6=设计内、
  u12 vio2 生产墙=mech 先拒）——别把设计内读数当回归（#30 ⑦）。

## 新增默认-PASS gate 时

1. 复制最近邻脚本改名 `replay_<phase><sub>_sub<step>.py`，换 LABEL/STEP/载荷集
   （clean=真实合规现代化 + 每条方框判据一个逐字 vio，#30 ②）。
2. artifact 必须生产形态（当前步+前序各步最新 trace 拼合，#30 ⑨）。
3. 本 README 列表加一行。

## 清单

| 脚本 | 节点 | 载荷 |
|---|---|---|
| replay_u1_sub1.py | understand:1 子1 逼问定义 | clean / real_borderline(软依赖) / vio_fixreq / vio_fabricate |
| replay_u1_sub2a.py | understand:1 子2a 规划拆解（plan-first 拆步 2026-08-14） | clean / vio_missing_atom(MECE 穷尽) / vio_overlap(MECE 互斥) / vio3_tier_none(none 档漏取证) |
| replay_u1_sub2.py | understand:1 子2b 因果链挖掘（plan-first 拆步前旧子2） | clean / vio1 同义反复 / vio2 稻草人 |
| replay_u1_sub3.py | understand:1 子4 双向取证（plan-first 拆步前旧子3） | clean / vio1 编造 / vio2 脱靶 / vio3 降档 / vio4 none派发 / vio5 转述 / vio6 未升档 |
| replay_u1_sub5.py | understand:1 子6 归一化陈述（plan-first 拆步前旧子5） | clean / vio1 证伪混入 / vio2 边界超出 / vio3 复合句 / vio4 实现名词 |
| replay_u2_sub1.py | understand:2 子1 目标引出 | clean / vio1 孤儿目标 / vio2 空泛复述 / vio3 ②偷懒 / vio4 ②未问先引 |
| replay_u2_sub2.py | understand:2 子2 对齐质检 | clean / vio1 同义反复 / vio2 矩阵放水 / vio3 汇总无矩阵 |
| replay_u2_sub3.py | understand:2 子3 价值论证 | clean / vio1 空泛复述 / vio2 基线编造(mech墙) / vio3 全must / vio4 无理由 / vio5 拍板 |
| replay_u2_sub4.py | understand:2 子4 归一化陈述 | clean / vio1 分层不传导 / vio2 边界不传导 / vio3 复合句 / vio4 方案动作残留 |
| replay_u3_sub1.py | understand:3 子1 障碍分析引出 | clean / vio1 空泛约束 / vio2 否定提问套话 / vio3 类型不足 / vio4 ②偷懒 / vio5 结论无出处推断 |
| replay_u3_sub2.py | understand:3 子2 约束验证标注 | clean / vio1 编造(mech墙) / vio2 未验证进约束集 / vio3 训练记忆冒充(mech墙) |
| replay_u3_sub3.py | understand:3 子3 范围界定 | clean / vio1 out空清单 / vio2 矩阵放水 / vio3 outcome空泛 / vio4 替用户拍板 / vio5 汇总无矩阵 |
| replay_u3_sub4.py | understand:3 子4 归一化陈述 | clean / vio1 类型标注不传导 / vio2 边界不传导 / vio3 复合句 / vio4 方案动作残留 |
| replay_u4_sub1.py | understand:4 子1 成功标准引出 | clean / vio1 空泛复述 / vio2 追溯放水 / vio3 ②偷懒 / vio4 方案名词 / vio5 结论无出处推断 |
| replay_u4_sub2.py | understand:4 子2 可检验化 | clean / vio1 基线编造(mech墙) / vio2 假指标 / vio3 阈值拍板 / vio4 模糊词残留 |
| replay_u4_sub3.py | understand:4 子3 验收方式设计 | clean / vio1 手段存在无工具出处 / vio2 全选同法无真实理由 / vio3 事后验证未标注风险 |
| replay_u4_sub4.py | understand:4 子4 归一化陈述 | clean / vio1 验收包字段不传导 / vio2 边界不传导 / vio3 复合句 / vio4 方案动作残留 |
| replay_plan1_sub2.py | plan:1 子2 方案发散 | clean / vio1 伪候选 / vio2 凭空设计 / vio3 提前收敛 / vio4 ②无逐维度论证 |
| replay_plan1_sub3.py | plan:1 子3 可行性验证 | clean / vio1 编造(mech墙) / vio2 影响面拍脑袋 / vio3 无差别可行 / vio4 重复漏检(mech墙) / vio5 缺项(mech墙) |
| replay_p1_sub1.py | plan:1 子1 现状勘察 | clean / vio1 训练记忆(mech墙) / vio2 凭空API(mech墙) / vio3 漫游 / vio4 内部矛盾 |
| replay_p1_sub4.py | plan:1 子4 评估提案 | clean / vio1 理由空泛 / vio2 替用户拍板 / vio3 推荐与净分矛盾 / vio4 追溯漏项(mech墙) / vio5 净分与计数不符(mech墙) |
| replay_plan1_sub5.py | plan:1 子5 归一化设计陈述 | clean / vio1 字段篡改 / vio2 复合句 / vio3 凭空新增要素 / vio4 假设淡化 / vio5 否决理由丢失(mech墙) |
| replay_plan2_sub1.py | plan:2 子1 清点基线 | clean / vio1 无出处(mech墙) / vio2 静默新增 / vio3 改写失真 / vio4 原文未引用(mech墙) |
| replay_plan2_sub2.py | plan:2 子2 切分排序 | clean / vio1 横向切无辩护 / vio2 排序违依赖(mech墙) / vio3 超H9不拆 / vio4 丢要素(mech墙) / vio5 ②无论证(mech墙) / vio6 替用户拍板 |
| replay_plan2_sub4.py | plan:2 子4 归一化步骤 | clean / vio1 字段篡改 / vio2 复合句 / vio3 验证不可执行无辩护 / vio4 验收包映射漏项(mech墙) |
| replay_plan2_sub3.py | plan:2 子3 锚点核验 | clean / vio1 声称存在无出处 / vio2 无差别已验证 / vio3 placeholder残留 / vio4 假设缺置信度影响(mech墙) / vio5 漏单元核验 |
| replay_plan3_sub1.py | plan:3 子1 需求清点 | clean / vio1 无出处(mech墙) / vio2 静默新增 / vio3 改写失真 / vio4 原文未引用(mech墙) |
| replay_plan3_sub2.py | plan:3 子2 能力盘点 | clean / vio1 幽灵能力 / vio2 强制路由漏核 / vio3 凭记忆编造 / vio4 ②无逐任务说明 |
| replay_plan3_sub3.py | plan:3 子3 匹配选型 | clean / vio1 无绑定残留(mech墙) / vio2 理由无出处 / vio3 强制项被替代无辩护 / vio4 重型手段无成本辩护 / vio5 替用户拍板 |
| replay_plan3_sub4.py | plan:3 子4 可用性核验 | clean / vio1 声称可用无出处 / vio2 无差别已验证 / vio3 假设缺置信度影响(mech墙) / vio4 漏绑定核验 |
| replay_plan3_sub5.py | plan:3 子5 归一化能力包 | clean / vio1 字段篡改 / vio2 复合句 / vio3 幽灵回潮 / vio4 不加载清单丢失(mech墙) / vio5 假设丢失(mech墙) |
| replay_plan4_sub1.py | plan:4 子1 四源清点 | clean / vio1 无出处编造 / vio2 静默新增 / vio3 改写失真 / vio4 原文未引用(mech墙) / vio5 漏源缺验收包 |
| replay_plan4_sub2.py | plan:4 子2 调度与检查点方案 | clean / vio1 虚设判据 / vio2 即兴路由 / vio3 拍脑袋分组 / vio4 无验收门 / vio5 逃避论证 / vio6 越权拍板 |
| replay_plan4_sub3.py | plan:4 子3 锚点核验 | clean / vio1 声称可执行无dryrun / vio2 交集无实算 / vio3 无差别已验证 / vio4 假设缺置信度影响(mech墙) / vio5 漏对象核验 |
| replay_plan4_sub4.py | plan:4 子4 归一化计划包 | clean / vio1 字段篡改 / vio2 复合句 / vio3 判断词回潮 / vio4 漏配 |
