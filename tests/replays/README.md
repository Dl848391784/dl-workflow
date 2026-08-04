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
| replay_u1_sub2.py | understand:1 子2 拆解深挖 | clean / vio1 同义反复 / vio2 稻草人 / vio3 none 档 |
| replay_u1_sub3.py | understand:1 子3 双向取证 | clean / vio1 编造 / vio2 脱靶 / vio3 降档 / vio4 none派发 / vio5 转述 / vio6 未升档 |
