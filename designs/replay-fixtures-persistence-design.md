# 重放载荷集入库设计（tests/replays/）

> 2026-08-04。v2.76 确立「改 run_judge=全局 framing 变更，所有默认-PASS gate 必须回归重放」，但回归资产（重放脚本+内嵌载荷）一直在 /tmp——机器重启即归零，归零后回归义务不可执行。把三个已反转 gate（u:1#1/#2/#3）的重放脚本清洗入库。

## 1. 清洗项（/tmp 版 → 入库版）

| 项 | /tmp 版问题 | 入库版 |
|---|---|---|
| token | u11/u12 内联 `sk-` 字面（泄漏面；且触发权限分类器） | 只从 env `ANTHROPIC_AUTH_TOKEN` 或 gitignored `tests/replays/.token` 读；pytest pin 防再引入 |
| sys.path | 硬编码 `/home/admin/.dl-workflow` | 相对 `__file__` 推仓根（换机可跑） |
| env 设置 | 模块顶层执行（import 即改环境） | 移入 `main()`/`setup_env()`——模块 import 无副作用（payload 可被其它脚本复用） |
| real 载荷（u11） | 硬读 evidence jsonl 第 0 行（state-reset/换机即崩） | 软依赖：文件在且首行是子1 trace 才纳入，否则跳过并打印原因 |
| u12 fixture | 已修生产形态（子1+子2 拼合，v2.79 教训） | 原样保留 |

## 2. 结构

```
tests/replays/
  README.md           用途/用法/新增节点回放清单
  _common.py          setup_env()（三件套硬赋值禁 setdefault，症状 V）+ judge_scope() + run_cases() 共享跑批
  replay_u1_sub1.py   clean/real_borderline(软依赖)/vio_fixreq/vio_fabricate
  replay_u1_sub2.py   clean/vio1 同义反复/vio2 稻草人/vio3 none 档（artifact=子1+子2 生产形态）
  replay_u1_sub3.py   clean+6 vio（artifact=子2+子3；可选 argv[2]=gate 文件做候选 gate 迭代）
```

- pytest 不收集（文件名无 test_ 前缀；live API 调用是手动回归工具非单测）。
- 防回归 pin：`tests/test_replay_scripts.py`——py_compile 全脚本 + 断言无 `sk-` token 字面（scrubbing 防回流）。
- u:1#4 回放脚本归并行会话（v2.80 进行中），落地后按同构板补 `replay_u1_sub4.py`。

## 3. 不做的事

- 不接 pytest 自动跑（每次 ~20 次真实 API 调用=花钱+分钟级；定位是「改 run_judge/已反转 gate 后的手动回归工具」）。
- 不统一历史脚本（v271_final_verify 等早期迭代脚本废弃，以入库版为准）。
