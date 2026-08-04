# judge framing 双态同向 + block 空判词重试设计（v2.76）

> 2026-08-04。harness 哲学审计（LLM 只负责思考、其余全交脚本；每个可见面只放该角色需要的东西）对 u:1#1/u:1#2 泛化成果的复查发现。

## 1. 发现

### 1.1 framing 变量分裂两层且互相矛盾（主问题）
§3.5 #28 确立「判据 framing 是独立设计变量」，但 v2.71/v2.75 只改了 **gate 文本**一层。`run_judge` prompt 的裁决指令行（engine:2317）恒为「严格判定：判据任一条不满足 -> pass=false」——35 个 gate 共用一份：

- 33 个从严 gate：gate 文本「质量判据（从严裁量）」× 指令「严格判定」= 同向 ✓
- 2 个默认-PASS gate（u:1#1/u:1#2）：gate 文本「默认 pass——仅当方框成立才判 block」× 指令「严格判定：任一条不满足→false」= **矛盾** ✗

弱 judge 对矛盾指令偏向 system 侧（指令离输出位更近、语气更绝对），是 u:1#2 v2.75 clean 残余 2/6 误判的可修复根源之一。

### 1.2 block 空判词无校验（次问题）
`_run_judge_once` 解析出 `{"pass": false, "reason": ""}` 会当合法 block 返回——模型拿到无理由 block 只能盲返工（判词消费者是返工模型，v2.36 判词瘦身的设计前提就是「reason 是指路」）。空判词 = judge 输出完整性违规，脚本可零成本机械判定，属「bad_verdict_json 重试一次」同族的输出抖动。

## 2. 设计

### 2.1 framing 双态（单源 = gate 文本字面标记）
`run_judge` 按 rubric 是否含「默认 pass」字面标记选裁决指令行：

- 含标记（默认-PASS gate）→「默认放行：仅当判据明列的 block 条件成立才 pass=false 并在 reason 写缺什么（引用条款）；判据未明列为 block 条件的情况不得作为 block 依据，不得发明判据外要件。」
- 不含（33 个从严 gate）→ 现有「严格判定」行不变

单源理由：gate 文本的「默认 pass」是判据作者已写的 framing 声明，脚本读取它而非新增 Step 字段（避免 nodes/engine 双写漂移；字面标记有测试钉死）。约定：今后写默认-PASS gate 必须含「默认 pass」字面，写进 §3.5 #28。

### 2.2 block 空判词重试一次
`_run_judge_once`：`pass=false 且 reason.strip()==""` → `judge_error=empty_block_reason`，retryable=True（与 bad_verdict_json 同处置：重试时追加格式提醒「判 block 必须在 reason 写明缺什么」；重试仍空才降级 block）。三种可重试失败模式：bad_verdict_json / TimeoutExpired / empty_block_reason。

## 3. 不做的事
- 不动 33 个从严 gate 的指令行（风险驱动逐个来，不批量）
- 不动 u:1#1/u:1#2 gate 文本（v2.71/v2.75 已验证，本次只改 harness 层）
- 不自相矛盾判词检测（reason 自由文本的语义矛盾不可机械判定，已知推理底）

## 4. 验证
1. 单测：framing 双态（monkeypatch _run_judge_once 捕 prompt 断言指令行变体 ×2）+ 空判词重试（mock subprocess 两轮）+ 「默认 pass」标记钉死（u:1#1/u:1#2 gate 含字面标记）
2. 回归重放（MiniMax n=6 三向）：u:1#1（clean/att1/att2，目标 clean 6/6、att1 6/6、att2 ≥4/6 不退）+ u:1#2（clean/vio1/vio3，目标 clean ≥4/6 提升、牙齿不退）

## 5. 验证结果（2026-08-04，全部 n=6 MiniMax-M3）

| 节点 | 载荷 | v2.71/v2.75 | v2.76 | 解读 |
|---|---|---|---|---|
| u:1#2 | clean | 4/6 | **6/6** | 矛盾指令即残余误判根源之一，修复即收敛 |
| u:1#2 | vio1 同义反复 | 6/6 | 6/6 | 牙齿不退 |
| u:1#2 | vio3 none 档 | 5/6 | **6/6** | 提升 |
| u:1#2 | vio2 稻草人 | 6/6 | 3/6 | judge 侧放宽代价；生产墙=mech 100% 拒（缺席断言词形）不变 |
| u:1#1 | clean（干净版） | 6/6 | 6/6 | 不退 |
| u:1#1 | vio_fixreq 修复诉求 | 6/6（att1） | 6/6 | 牙齿不退 |
| u:1#1 | vio_fabricate 好奇心 | — | 6/6 | 牙齿 |
| u:1#1 | real_borderline（state-reset 后真实新载荷） | — | 1/6 PASS | **设计内 block 非误伤**：该载荷 pain 选项=「回查计算逻辑/修根因，再决定启用」=修复诉求本体+「修复前不启用」派生包装，正是 v2.71 (c) 条款要拦的 att1 类（选项设计违规=_OPTION_DESIGN_RULE 动作类要求） |

两个载荷侧教训：①合成 clean 载荷本身有缺陷时（结论出处与 a[] 动作矛盾）judge 拦得对——「clean 4/6」一度看似回归，修载荷后 6/6，**重放载荷质量=验证结论的前提**（§3.5 #15 fixture 保真度陷阱第二实例）；②real_borderline 初判期望 PASS 是判读错误——pain 选项是修复诉求类时，「修复前不启用」的派生包装不改变其 att1 本质，judge 5/6 block=牙齿生效。

v2.76 净效果：u:1#2 clean 4/6→6/6 + vio3 5/6→6/6（残余误判根源切除确认），代价 vio2 judge 侧 6/6→3/6（生产侧由 mech 100% 拒覆盖，可接受）。706 tests 全绿。
