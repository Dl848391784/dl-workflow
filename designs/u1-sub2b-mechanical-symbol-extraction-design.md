# 子2b 取证入口机械提取设计（回炉 u1-sub2b-consumes-sub2a-design）

> 回炉依据：`u1-sub2b-consumes-sub2a-design` 让子2a 模型手写 `symbols`/`files` 字段，
> 实测（amplitude_annualized 2026-08-16）子2a 从 16 轮爆炸到 119 轮（238s→1281s，
> $1.52→$14.55），子2b 只从 35 轮降到 19 轮（454s→300s）——**净亏 2.3×**。
> 用户裁决：`symbols`/`files` 的生成从「模型手写」改为「引擎机械提取」，
> 模型不做额外工作，入口由工具/引擎从已有发现中机械导出。

## 0. 根因

子2a 是规划步，弱模型在「凭空想出要 trace 哪些符号」上打转 119 轮——
这是把最难的推理活塞给了最不该干这个的步骤。但子2b 消费子2a 计划确实有效
（19 轮 vs 35 轮），说明「给子2b 取证入口」方向对，落点错：入口该由**机械
层从子2a 已做的轻量侦察里导出**，不该让模型手写。

## 1. 回炉方案总览

```
子2a（规划，只做 MECE + 定档 + 轻量 string 侦察）
  ├── 模型产出 atomic_questions（q/tier/tier_reason，**无 symbols/files**）
  └── dl codebase query --string 时，工具自动把命中文件落账到 discoveries.jsonl
        （新 kind="string-files"，机械，模型零感知）

子2b（执行，挖因果链）
  ├── node-rules 自动注入两块：
  │   ① 子2a atomic_questions 全文（已有，保留——给了「查什么」）
  │   ② discoveries.jsonl 的「已发现文件/符号」清单（新增——给了「去哪查」）
  └── 按清单 trace --history，不再 broad string search
```

关键：模型全程不手写 symbols/files。入口 = 工具自动落账 + 引擎机械注入。

## 2. 具体改动

### 2.1 回滚（撤销 u1-sub2b-consumes-sub2a 的模型手写部分）

- `dl_flow_nodes.py` 子2a：
  - purpose/selfcheck 删 `symbols`/`files` 字段说明，恢复原 atomic_questions 形态
  - gate 删「tier≠none 须含 symbols/files」形式要件与方框二对应句
  - extra_payload_keys 删 `("atomic_questions", "atomic_question_symbols")`
- `dl_flow_nodes.py` 子2b：
  - purpose/selfcheck 删「优先从 symbols/files 出发」的表述
  - gate 删方框四「未按子2a 清单执行/重新规划」
  - mech_checks 删 `sub2b_follows_atomic_questions`
- `dl_flow_engine.py`：
  - 删 `_check_atomic_question_symbols` 及其注册
  - 删 `_check_sub2b_follows_atomic_questions` 及其注册
- `tests`：删/改 7 个新测试，恢复 2 个被改的 fixture

### 2.2 机械落账（`dl_codebase.py`）

`query_string` 现在不落账（grep 便宜 + 结果巨大）。回炉后改为：**落账但只记
文件路径摘要**，不记全文。新条目：

```json
{"key": "string:annual", "kind": "string-files", "query": "annual",
 "files": ["web_ui/app.py", "summary/report/data_loaders.py"], "step": "understand:1#2"}
```

去重键 = `string:<pattern>`（同 pattern 重复查命中缓存返回 files）。

### 2.3 引擎机械注入（`dl_drive.py`）

`ensure_node_rules` 对 understand:1 节点（子2b 运行时），除注入 atomic_questions
外，再读 discoveries.jsonl 里的 `string-files` 条目，拼一份「前序步骤已发现的
相关文件」清单注入。文案：

> 前序规划步已做字符串侦察，发现以下文件与问题相关（可作取证起点，直接
> `dl codebase query --history <file>:<line>` 或 Read，不必再 broad search）：
> - web_ui/app.py
> - summary/report/data_loaders.py

## 3. 边界与诚实评估

- **不保证全覆盖**：string 侦察命中的文件 ≠ 子2b 需要的全部符号。但给了起点，
  减少「决定下一步查哪」的试探轮。5-Whys 迭代中新符号仍需现场查——这是设计内。
- **不是零和**：子2a 零新增负担（工具自动落账），子2b 拿到机械导出的起点。
- **收益预期**：子2b 轮数回到 ~20 左右（与 run3 子2b 相当），子2a 回到 ~16 轮
  （run1 基线）。总耗时 = 238 + ~350 ≈ 600s，vs run1 的 692s、run3 的 1581s。
