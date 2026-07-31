# 产物机械门落地设计：ARTIFACT_EXISTS 实现 + 新鲜度 + ARTIFACT_CONTAINS（§8.3 首刀）

> 状态：**已实施**（2026-07-31；engine/nodes/hook/tests 已同步）
> 父文档：`workflow-system-design.md` §8.3（机械门独立项）、`execution-plan-checkpoints-substeps-design.md` §5 #7（plan:4 正解 = ARTIFACT_CONTAINS 的预先裁决）、`substep-gate-at-stop-design.md`（末步门控路径）

## 0. 动因：声明了防线，实现是空的

`gate_verdict_mech` 对 ARTIFACT_EXISTS 一律 `return None`（"暂不实现文件查找，留 §8.3"），但三处节点定义已挂 `gate_mech=ARTIFACT_EXISTS`（understand:4 / plan:2 / plan:3），plan:2 注释甚至自承"ARTIFACT_EXISTS 零成本兜底子5 无 judge 的产物落地风险"——**兜底不存在**。这是 H13 精神的虚假防线：读 nodes 定义的人以为有门，实际零校验。

真实漏洞（2026-07-31 会话裁决，用户问"understand/plan 产物门控没校验要不要加"）：

- understand.md / plan.md 是**下游消费契约锚点**：review:0 rubric「对照 understand.md 判定 solved/partial/not」、execute:0 rubric「对照 plan.md 逐条核」。上游装配落空，下游 judge 拿空文件判，灾难在离起点最远的地方爆。
- understand:4 子5（装配步）`gate=None`（交互步，trace 存在即过）——模型写了 trace 但没写 understand.md（或 S15 围栏误伤写盘落空）也能过。understand->plan 已无人工闸门，落空静默溜进 plan。
- plan:4 注释早已写明正解：「§8.3 实现时本节点的正解 = ARTIFACT_CONTAINS（节存在检查），属该独立项的连带工作」。本设计即兑现该连带工作。

## 1. 设计

### 1.1 机制清单

1. **`gate_verdict_mech(node, project_root, name, not_before)` 实现 ARTIFACT_EXISTS**：
   - 产物路径解析 = `project_root/.claude/<_PHASE_ARTIFACT_DIRS[phase]>/<name>.md`（2026-07-28 决议的主仓规范位置，engine 已有该映射单源）。
   - 仅当 `node.artifact` 是裸 `.md` basename（无 `/`、不以 `+` 结尾）时可判；否则降级 None（描述性产物如"代码+commit+测试通过"交语义 judge，沿用旧逻辑）。
   - 文件不存在 → block；`not_before` 非 None 且 `mtime < not_before` → block（陈旧）。
2. **新增 `GateMech.ARTIFACT_CONTAINS` + `Node.artifact_contains: tuple[str, ...] = ()`**：文件须存在且全文含全部指定子串（节标题级检查，非结构解析——弱模型产物标题措辞允许浮动，子串匹配宁宽勿窄）。
3. **plan:4 改挂** `ARTIFACT_CONTAINS + ("执行计划与检查点",)`（三节结构决议：执行步骤/能力与工具/执行计划与检查点；本节自 plan:4 子5 装配）。兑现 execution-plan-checkpoints-substeps-design §5 #7。
4. **新鲜度（not_before）来源** = `state.history` 当前节点 `entered_at`（advance_state 已逐节点记录，零新增状态字段）。语义：产物须在本节点内写盘——装配义务本来就锚定末子步骤（phase-rules「在写末步 trace 前完成」），早于本节点进入时间的文件 = 预写/残留，block 指引重新装配。
5. **两个触发点**：
   - **sub-step 末步**（`gate_and_advance_sub_step`，judge 过后、推进/扣留前）：understand:4 / plan:2 / plan:3 / plan:4 全部在此拦——这是编排节点唯一的自动推进通道，不拦这里等于没拦。传 name + not_before。block 走既有 block 路径（attempts++/escalate 升级），模型重写产物+新 trace 重判。
   - **run_gate**（PHASE_DONE/SUB_DONE 路径，hook 补传 name）：plan:4 大闸门第二层；review:0 / evolution:0 声明已久的 ARTIFACT_EXISTS 同步生效（phase-rules 早已要求写主仓 `.claude/reviews|evolutions/<name>.md`，无文案冲突）。不传 not_before（仅存在性，避免过度拦截）。
6. **降级纪律**（宁纵勿枉，同 codegraph_gate 非 git 放行）：name=None / project_root=None / 路径解析失败 / mtime 解析失败 → None。机械门只拦「确定缺」，不猜「可能缺」。

### 1.2 block 文案（模型可读，给修复动作）

- 缺失：「产物未落地：<相对路径> 不存在（<节点> 的装配义务：末子步骤内写盘后才可 STEP_DONE）。写盘后附新 trace 重试。」
- 陈旧：「产物陈旧：<相对路径> 最后修改早于本节点进入时间——须在本节点内装配（禁预写/残留）。重新装配写盘后附新 trace 重试。」
- 缺节：「产物缺节：<相对路径> 缺「执行计划与检查点」节（plan:4 子5 装配义务）。补装后附新 trace 重试。」

## 2. 否决的替代方案（对抗性审视留痕）

| # | 方案 | 否决理由 |
|---|---|---|
| 1 | 加 judge 语义审产物内容 | 弱模型优先原则：产物内容质量已被各子步 trace 的语义 judge 覆盖（plan:4 子4 验十字段），缺的只是「装配动作落地」这一机械事实。机械杠杆零 token，judge 单次 ~2.2-3.3k |
| 2 | understand.md 也上 CONTAINS（节标题匹配） | understand.md 节标题未单源钉死（注入文案「真实问题重述 + 边界 + 成功标准」与装配 spec「真实问题重述 + 目标价值 + 范围约束 + 成功标准验收包」措辞不一），硬匹配 = 误 block 源。新鲜度（mtime >= entered_at）已覆盖「预写半成品不更新」主威胁；标题单源化是另一个独立项 |
| 3 | 新鲜度用 state.created_at（实例级） | 弱于 entered_at：同实例内 plan:1 预写 plan.md、understand:2 预写 understand.md 都逃得过。entered_at 精确对齐「装配义务锚定本节点末步」的编排语义 |
| 4 | plan:2/3 也上 CONTAINS（执行步骤节/能力与工具节） | 超出已裁决范围。plan:2/3 注释只承诺 ARTIFACT_EXISTS；且 plan:2 创建文件时「执行步骤」节标题措辞同样未单源钉死。留待标题单源化独立项一并评估 |
| 5 | 给 TEST_PASS 顺手实现 | 出范围（§8.2 独立项：跑测试的机械门涉及项目测试命令约定，与产物文件检查不同源） |

## 3. 连带行为变化（显式披露）

- **review:0 / evolution:0 的 ARTIFACT_EXISTS 自本 commit 起真实生效**（此前空转）。PHASE_DONE: review/evolution 前产物必须已写主仓 `.claude/reviews|evolutions/<name>.md`——phase-rules 第 132/138 行早已如此要求，本变更只是把文案承诺变硬（症状 P 元教训：文案=建议，hook=物理）。
- tests `test_artifact_exists_not_yet_impl`（断言"未实现降级 None"）删除——它锁的是被本变更消灭的过渡态。

## 4. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 时钟/时区错位致新鲜度误判 | entered_at 与 mtime 同机同时区（`_now()` 本地时间 vs `Path.stat().st_mtime` epoch——统一转 epoch 比较）；解析失败降级放行 |
| 模型末步 block 后只改文件不写新 trace，Stop 静默放行不推进（症状 J） | block 文案显式要求「附新 trace 重试」——与既有返工协议一致 |
| 历史 state 无 history/entered_at 字段 | `_node_entered_at` 返回 None → 退化为仅存在性检查（宁纵勿枉） |
| hook 未同步传 name | run_gate name=None → 降级放行，与现状等价，不产生新 block |

## 5. 实施 checklist

1. `dl_flow_nodes.py`：GateMech 加 ARTIFACT_CONTAINS；Node 加 artifact_contains 字段；plan:4 改挂 + 更新注释（删除"机械门全类型未实现"过期描述）。
2. `dl_flow_engine.py`：gate_verdict_mech 实现 + `_node_entered_at` helper + run_gate 签名扩 name/not_before + gate_and_advance_sub_step 末步机械门。
3. `hooks/workflow_advance.py`：两处 run_gate 调用补传 name。
4. `tests/test_dl_flow_engine.py`：TestGateVerdictMech 重写（存在/缺失/陈旧/缺节/降级）+ 末步集成（understand:4 无产物 block / 有产物 advanced）。
5. plan:2/plan:3/understand:4 注释里"机械门未实现"的过期描述同步更新。
