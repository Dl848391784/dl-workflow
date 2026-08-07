# 子阶段边界固定交接提示设计（minor-boundary handoff prompt，2026-08-07）

> 状态：设计中。本文件为 H8 Design-First 产物。目标版本 v2.122。
> 父文档：`context-handoff-design.md`（其 §2「成本自适应 nudge」策略由本设计**取代**；交接包/SessionStart 注入/裁决入 trace 等机制部分不变）、`artifact-handoff-hardening-design.md` §0（「主动有损替代被动有损」用户设想真源）。
> 用户决议（2026-08-07 会话）：①**固定边界提示替代阈值触发**——阈值在任意步中命中「很割裂」，固定边界有节奏感；②粒度 = **minor_state（子阶段）边界**；③**不保留阈值硬拦**——全软提示，用户全程自主（「一直点继续跑出 490k」是被接受的自主代价，留痕供事后审计）；④不用 AskUserQuestion 做提示（见 §3 #1）。

## 0. 动因：纯建议 nudge 在真实运行中等于不存在

tail_volume_acceleration_annualized 实测（2026-08-06，session 08d4daa7）：上下文 65k → 490k **单调爬坡零锯齿**——v2.45 的阈值 nudge（>150k 附建议）在全部 8 个边界都触发了（边界最小值 220k），**无一被执行**。建议可被零成本忽略 = 建议不存在。

**真实 transcript 重放**（各 minor_state 末步通过后最近一轮 usage 估算）：

| 边界（末步通过） | 时刻 | 上下文 | 分档（T1=150k/T2=300k） |
|---|---|---|---|
| understand:1 理解问题和背景 | 10:38 | ~220k | 建议 |
| understand:2 明确目标和价值 | 10:45 | ~241k | 建议 |
| understand:3 确定范围与约束 | 11:03 | ~273k | 建议 |
| understand:4 定义成功标准 | 11:21 | ~302k | 强烈 |
| plan:1 设计解决方案 | 11:49 | ~369k | 强烈 |
| plan:2 拆解任务与阶段 | 12:06 | ~402k | 强烈 |
| plan:3 选择能力与工具 | 12:21 | ~434k | 强烈 |
| plan:4 门栏扣留（/dl gate 前） | 12:29 | ~460k | 强烈 |

**成本反向事实**（同 transcript 模拟：每边界 /clear 重置 45k，节点内增量不变）：
实测总 cache read **316M** → 每边界清理 **90M** = **3.5x 缩减**，用户动作 = 8 次清理。
与 context-handoff-design §5「每节点交接 ~105M」的预估吻合（实测更优，因轻节点不清也无妨的假设未计入）。

注：understand:1 单节点 65k→220k——重节点内涨幅是成本主体，**major_state 粒度不够**（§3 #3），minor_state 是节奏与成本的双赢点。

## 1. 关键事实（设计前已核实，file:line）

| # | 事实 | 证据 | 对设计的影响 |
|---|---|---|---|
| 1 | nudge 现挂两个挂载点：跨子阶段续轮 + **步内续轮** | `hooks/workflow_advance.py:479` / `:493` | :493 步内挂载**移除**（用户决议①：边界外零提示） |
| 2 | 门栏扣留停轮是独立出口（用户本要停下敲 /dl gate） | `hooks/workflow_advance.py:449-453` | 挂载点 B，文案变体（下一动作是 /dl gate 非「继续」） |
| 3 | 下一节点无 sub_steps 时有第三出口（emit 后停轮） | `hooks/workflow_advance.py:481` | 挂载点 C |
| 4 | 整阶段节点（execute/review/evolution，minor_key=None）走 SUB_DONE/PHASE_DONE 分支 | `hooks/workflow_advance.py:564+`、`:639`、`:726-740` | 挂载点 D（实施时逐出口核实，checklist #3） |
| 5 | 阈值常量单源 + 估算函数宁纵勿枉（读不到 → None） | `dl_flow_engine.py:854`（HANDOFF_NUDGE_THRESHOLD=150k）、`:1156`（estimate_context_tokens） | 常量改双档 T1/T2；估算函数复用不改 |
| 6 | 交接包 + SessionStart 注入通道已在线 | `dl_flow_engine.py:1189`（handoff_pack）、`hooks/workflow_session.py` | 零改动，本设计只改提示策略 |
| 7 | major_stage/minor_stage 是 evidence 结构字段单源 | `dl_flow_engine.py:446-460` | 留痕记录直接复用该字段体系 |
| 8 | /clear 无程序化入口：CLI 只从键盘解释，hook/工具/AskUserQuestion 回调均触达不到 | harness 约束（context-handoff-design §2「用户动作=2 次击键」同款结论） | 提示的最终动作永远是用户敲 /clear；设计目标是让提示出现在正确时刻，不是消灭击键 |
| 9 | hook 直写 evidence 先例：write_gate_verdict（kind=gate） | `tui-state-machine-design.md` §8.6 | 留痕新增同范式 helper，不经模型手 |

## 2. 设计

### 2.1 P1：提示策略 = 固定边界 + 分档文案

**触发点**（全部 = 节点末步通过门控的出口，即 minor_state 边界；步内零提示）：

| 挂载点 | 位置 | 文案变体 |
|---|---|---|
| A：跨子阶段自动续轮 | `workflow_advance.py:475-480` | 标准版（下一动作 = 回「继续」） |
| B：子阶段门栏扣留停轮 | `:449-453` | 门栏版（建议先 /clear 再 /dl gate——state 在磁盘，clear 不影响放行） |
| C：跨向无编排节点停轮 | `:481` | 标准版 |
| D：整阶段节点完成（execute/review/evolution 末出口） | `:564+` 分支 | 标准版（major 边界，交接包跨阶段裁剪同样适用） |

**分档**（常量单源 dl_flow_engine，HANDOFF_NUDGE_THRESHOLD 退役）：

```python
HANDOFF_PROMPT_T1 = 150_000  # < T1：健康，一句话告知
HANDOFF_PROMPT_T2 = 300_000  # T1~T2：建议清理；> T2：强烈建议
```

**文案草稿**（实施时定稿；用户可见面非 judge 面，仍守义务句主句前置纪律）：

- 健康（<T1）：`🔄 子阶段边界：上下文约 {est}k，健康。回「继续」即可；也可 /clear 后回「继续」，交接包自动注入。`
- 建议（T1~T2）：`🔄 子阶段边界：上下文约 {est}k。建议 /clear 后回「继续」——后续每轮都全量重读当前上下文；清理后从 ~45k 重新起步，交接包（前序证据+用户裁决+产物指针）自动注入，接续零损失。不清回「继续」即可。`
- 强烈（>T2）：`🔄 子阶段边界：上下文已约 {est}k，每轮成本约为清理后的 {est//45_000} 倍。强烈建议 /clear 后回「继续」（接续零损失）；回「继续」= 选择不清。`
- est 读不到（None）→ 降级为无数字版一句话（宁纵勿枉，沿用估算函数语义）。

### 2.2 P2：选择留痕（机械写 evidence，零交互成本）

用户选择（清/不清）事后审计需要数据，但不值得多花一轮交互——hook 双侧机械检测：

1. **发出提示时**：engine 新 helper `write_handoff_event()`（write_gate_verdict 同范式，事实 #9）append `kind=handoff_prompt {major_stage, minor_stage, est, tier, ts}`。
2. **SessionStart source=clear 且工作流运行中**（workflow_session.py 现有通道）：尾部扫描最后一条 handoff_* 记录，若为未决 prompt → append `kind=handoff_resolution {choice:"cleared"}`。
3. **发出新提示时上次未决** → 先 append `{choice:"declined"}` 再写新 prompt。

宁纵勿枉：evidence 读写任何失败 → 提示照发、不记录（提示是主功能，留痕是审计增强）。

### 2.3 不改什么

- 交接包内容/装配（handoff_pack）、SessionStart 注入通道、user_decision_recorded 校验——零改动。
- 判据/purpose/gate 语义——零改动（门控读磁盘，会话无关的地基不变）。
- settings 模板——无新 hook 注册（workflow_advance/workflow_session 均已注册），SETTINGS_TEMPLATE_VERSION 不 bump。

## 3. 否决的替代方案（对抗性审视留痕）

| # | 方案 | 否决理由 |
|---|---|---|
| 1 | AskUserQuestion 给选项、点击后自动 /clear | **物理不可行**：/clear 无程序化入口（事实 #8），点击后模型仍只能回「请敲 /clear」。且 AskUserQuestion 要多花一整轮全上下文 cache read（220k 时点问一句=完整读 220k）问 hook 文案零 token 就能问的问题；选项留痕由 P2 机械检测免费获得 |
| 2 | 超硬阈值 defer 阻断（不清不让走） | **用户决议（2026-08-07）明确不保留**：全程自主优先；490k 重演的代价由用户自担，P2 留痕供事后审计复盘 |
| 3 | 只在 major_state（5 大阶段）边界提示 | understand:1 单节点 65k→220k 实测——major 粒度内 understand/plan 仍爬 400k+，省不到大头（§0 表） |
| 4 | 维持阈值触发（现状 v2.45） | 490k 零锯齿实证失效：建议可忽略 = 建议不存在；且触发时机不可预期「很割裂」（用户原话） |
| 5 | 每个子步边界提示（context-handoff-design 原 v1 粒度） | 全程 12-15 次打扰节奏过密；minor 边界 ~8-10 次且恰在归一化陈述落库后，交接包内容最新 |
| 6 | 重步执行子代理化（彻底无主会话膨胀） | context-handoff-design §2 已否决：子代理不能 AskUserQuestion、Stop 门控不进子代理进程，读回确认步全灭 |

## 4. 连带行为变化（显式披露）

- **步内续轮（:493）不再出现 nudge**——单节点内涨到任何量级都无提示，直到末步边界。这是用户决议①的直接后果（节奏感优先于节点内封顶）。
- **_handoff_nudge 改名/改语义为边界提示函数**——签名带 tier 计算 + 留痕写入；测试同步重写。
- **在飞实例 tail_volume**（plan:4 门栏 pending 中）：merge 后 `git pull` 即生效，其下一边界（plan:4 → execute）即为新提示的首个真机 dogfood。
- evidence 新增两种 kind（handoff_prompt/handoff_resolution）——append-only 无迁移；evidence_show 回查不受影响（按 kind 过滤处需确认不假设枚举，checklist #5）。

## 5. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 用户全程点「继续」→ 490k 重演 | 用户已接受的自主代价（决议③）；P2 留痕使「提示了几次/清了几次/省没省」可事后量化，为将来是否重提硬闸提供数据 |
| 文案分档阈值（150k/300k）拍脑袋 | §0 重放表即验证：T1 以下无边界实例（最小 220k），T2 切开 understand/plan 两组，分布合理；实施时对其他历史 transcript 复跑同一脚本确认 |
| 门栏变体文案误导（clear 后 /dl gate 失效？） | 不会——/dl gate 读磁盘 state.json，会话无关；文案明说「先 /clear 再 /dl gate」 |
| 留痕误记（clear 发生在很久以后/非边界时刻） | resolution 记录带 ts，语义=「该 prompt 之后发生了 clear」，不过度解读；无 pending prompt 的 clear 不记录 |
| 弱模型把提示当新指令执行（framing 反读） | 提示面向用户非模型，但文案仍守纪律：义务句主句前置、不含「禁/勿」类行为动词误导；实施时双向载荷（该出现的边界出现/步内不出现）过测试 |

## 6. 实施 checklist（按 H9 分小 commit）

1. ✅ 本设计文档（1 文件）。
2. `dl_flow_engine.py`：HANDOFF_PROMPT_T1/T2 常量（退役 HANDOFF_NUDGE_THRESHOLD）+ `write_handoff_event()` helper + tests。
3. `hooks/workflow_advance.py`：`_handoff_nudge` → `_handoff_boundary_prompt`（分档文案 + 留痕调用），挂载点 A/B/C 接入、:493 步内挂载移除；逐出口核实整阶段节点路径（挂载点 D）并接入。
4. `hooks/workflow_session.py`：source=clear 时未决 prompt → cleared resolution。
5. tests：分档三向 + est None 降级 + 挂载点出现/不出现双向 + 留痕三态（cleared/declined/无 pending）+ evidence_show 兼容确认。
6. 历史 transcript 复跑分档脚本（§0 同款），确认 T1/T2 在别的会话不塌缩到单一档。
7. merge 回 main 后真机 dogfood：tail_volume plan:4 → execute 边界观察提示出现 + 留痕落库。
