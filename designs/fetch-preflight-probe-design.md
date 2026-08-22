# fetch-preflight 网络可达性预检（u:1 子4 外部取证前置）设计

日期：2026-08-22　分支：feat/fetch-preflight-probe

## 1. 背景（实证）

2026-08-22 interaction_turnover__ret3d_abs_test_1 u:1 子4（双向取证，墙钟 ~14 min）：

- 原子 B（light 档）agent 3.2 min 全花在网络超时 + /tmp 读取被拒，返回
  「未取证（环境受限）+ 建议升档 full」；
- 按契约补派 full 升档 agent 又串行跑 5.5 min，**该原子串行吃掉 ~9 min**；
- 环境性失败（网络不通）在**派发前不可见**--升档救不了网络死（升档治
  档位不够，不治环境），却付了一整轮 agent 的钱。

对照组：step2/step3 各 ~6 min。若无环境性空跑，子4 与它们同量级。

## 2. 用户裁决（需求原文）

> 需要前置先确认网络可达性再求证，比如外部5次不同网址的求证，就都得
> 求证前先确认5个外部网址的网络可达性。

即：外部取证派发前，对**全部**计划内外部源 URL 逐个预检网络可达性；
不可达的不派发（升档/重试都救不了网络），留痕即可。

## 3. 方案（系统侧杠杆，弱模型优先）

模型只决定「URL 清单」（claim 源），探测归脚本（v2.118「模型只决定
内容其余交脚本」同范式）。

### 3.1 engine 新子命令 `fetch-preflight`

```
python3 ~/.dl-workflow/dl_flow_engine.py fetch-preflight [name] --url <u1> <u2> ...
```

- 逐 URL `curl -s -o /dev/null -w '%{http_code}' -m 8`，失败重试一次
  （≤16s/URL 上界；对齐骨架纪律 7「失败重试一次」）。**任意 HTTP 状态码
  （含 403/404/405）= 网络可达**--可达性 ≠ 内容成功，服务器应答即证明
  网络路径通；exit≠0 或 code=000 = 不可达。
- 裸域名自动补 `https://` 前缀；URL 去重保序。
- 结果**始终落盘** `.claude/workflows/<name>/fetch-preflight.json`
  （checked_at + 逐项 url/ok/http_code/error），stdout 打印逐 URL 结果 +
  落盘路径 + 可达计数（部分不可达仍 rc=0--不可达是信息不是命令失败）。

### 3.2 nodes understand:1 子4 规则更新

执行序 ② 内部扩为 **骨架+claim 填写 -> 预检 -> 派发**（预检夹在 claim 填写后、
Agent 派发前--URL 清单在 claim 可检验化时才具体化）：

- **②b 预检**：对全部去重外部源 URL 跑 `fetch-preflight --url ...`
  （claim 源须写具体 URL 或站点根；检索类源写站点根 URL）；
- 不可达源：从该原子源清单剔除 + 载荷留痕；
- **某 tier≠none 原子全部源不可达 → 不派发该原子 agent、不升档**，
  载荷记「预检不可达」q 项（引用预检结果）--升档治档位不够、不治网络死；
- 部分可达 → 照常派发（agent 仍可去其余源）；
- 预检全可达 → ②c 照常（行为零变化）。

### 3.3 机械层（mech）扩面

- 新 mech `fetch_preflight_out`（fetch_skeleton_out §8.3 同范式）：
  子2 atomic_questions 含 tier≠none 原子（或 aq 缺失=legacy 按有外部取证
  处理）时，`fetch-preflight.json` 须存在且 mtime ≥ 本节点 entered_at；
  全 none 档豁免（无外部源可预检）。新鲜度判定提取共用 helper
  `_wf_artifact_mtime_stale`（skeleton 检查同用，单源）。
- `_check_fetch_report_recorded` 合法收录项扩面：标题含「蒸馏报告」
  **或「预检不可达」**的 q 项--否则环境全阻断的原子不派发反被机械拒
  （v2.118 修 B 的对偶：配对判据须覆盖「合法不派发」路径）。
- mech_checks 声明顺序把 `fetch_preflight_out` 放最后（既有失败类测试
  断言的是前序检查的报错文案，不受影响）。

### 3.4 gate 文本（子4）

- 方框五（档不一致）补**合法形态**：「预检不可达」项 = 环境阻断合法
  留痕，不得以「未跑 agent/未升档」为由 block（单侧钉死防 judge 发明
  要件）；
- 合法正例段补一句：全源预检不可达的原子以「预检不可达」q 项留痕
  即合规。

### 3.5 不改的（边界）

- agent 运行中途才发现的 URL 无法预检（计划外源）--预检只覆盖 claim
  计划内源；
- fetch-prompt 骨架不注入预检结果（agent 侧无需知道，剔除源已在 claim
  区完成）；
- 其他节点（fetch 机制为 u:1 专属）不动。

## 4. 测试

- `TestFetchPreflightCmd`：monkeypatch `_curl_probe`，验证落盘/去重/
  裸域名补 https/重试一次/rc=0（部分不可达）/无 --url 报用法错。
- `TestFetchPreflightOut`：缺文件拒 / 新鲜过 / 陈旧拒（entered_at 之后）
  / 全 none 档豁免 / aq 缺失（legacy）仍要求。
- `TestFetchReportRecorded` 补：「预检不可达」项计入 required。
- 既有子4 append_trace 成功类用例补写 `fetch-preflight.json` fixture。

## 5. 风险与取舍

- gate 只新增**合法形态**（放松方向），无新增 block 条件--judge thrash
  风险低于历次判据改动；live judge 重放登记为后续观察项（下个 u:1 实例
  子4 现场验证），不在本批强制。
- 预检本身花墙钟（每 URL ≤16s 上界，典型几秒）--换掉的是 3min 级
  环境性空跑 agent，净收益为正；且预检在派发前串行执行的只有探测本身。
- 网络抖动误判不可达：重试一次 + 不可达源「剔除+留痕」而非销毁（模型
  可在载荷说明），宁纵勿枉。
