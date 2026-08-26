# 改动规格字段契约披露补全设计（change-spec-field-contract-disclosure）

> 2026-08-26。触发：3 轮因子工作流成本审计（amplitude / ma5_slope / return_5d）。前轮 change-spec-prefix-tolerance（65e0bd2）三轮零复发；本设计处理其暴露的第二形态。

## 1. 证据链

**第二形态打地鼠（Run 3 return_5d 实锤，plan:1#5 58 轮/13.6m/7.16M cr，7 提交 6 拒）**：
- 模型把**注释/假想/被否条目混进 change_list**：「（口径选型为设计决策、非代码改动，本决策不新增独立改动条目）——承接链：…」「（被否方案无落地改动条目——仅列假想改动面供 ADR 追溯）假想=…」——机械校验视每非空行为一条改动条目，散文行必拒（3 次）。
- **增@锚点写自然语言**：「report.html:1172 include _section_backtest 链附近，子1 q2 逐字锚点」（plan:1#5）、「TestT1Alignment 类内现有引擎测试函数尾部」（plan:2#4）——锚点三形态（现有 symbol 名 / L 行号 / 文件尾）未被披露为封闭集，模型把出处说明写进锚点位（2 次）。
- 另有 2 次门槛履职拒（传导缺 a[0]、rejected 无否决理由）——合法修正循环，不计打地鼠。

**根因定性**：判据披露缺口（runtime-audit §1 三分类）——「change_list/change_point 每行必须是合法改动条目；注释/假想/被否条目禁入（被否写 rejected 字段）；增@锚点三形态封闭」这份契约只存在于校验实现里，骨架提示与规则文案均未披露。与 #31（骨架表达力缺口）同族。

## 2. 方案（三处 surgical，全在披露层 + 一处报错精确化）

### 修 1：`_CHANGE_SPEC_RULE` 补字段契约句（dl_flow_nodes.py，单源常量四处同步）
追加：「change_list/change_point 每行一条改动条目——注释/说明/假想/被否条目禁入（被否方案与理由写 rejected 字段）；增@锚点只接受三形态：现有 symbol 名 / L 行号 / 文件尾，禁自然语言描述」。

### 修 2：`_FIELD_SCAFFOLD_HINTS[change_list/change_point]` 同款补句（dl_flow_engine.py）
骨架待填占位符是模型写载荷时唯一在手的格式真源（#26），补句进占位符括注（替换即消失）。

### 修 3：增@锚点空白符检测 → 报错精确化（dl_flow_engine.py `_verify_anchor_parts`）
锚点含空白符 = 必然自然语言（symbol 名无空格）——报错从「查无」精确为「锚点是自然语言描述（含空格）：「<锚点>」——只接受三形态：现有 symbol 名 / L 行号 / 文件尾；出处说明写 boundary 不写锚点」。`_verify_anchor_parts` 为改动规格与 u 侧根因行共享，两处同益。CJK 无空格 symbol 不拦截（Unicode \w 合法标识符，宁纵勿枉）。

### 不做的事
- 不做解析器对散文行的「宽容跳过」——注释混入是内容错误（会进 evidence 污染下游 plan.md 装配），披露预防是正确层，宽容会让垃圾进证据链。
- 不动 rejected 字段校验逻辑（其报错已在履职）。
- TUI 段 TaskList 簿记税（Run 2 观察项）单样本，按 #22 纪律不立项，登记观察。

## 3. 验证

1. 单测：hints/rule 含新契约句；含空格锚点报「自然语言」精确错；CJK 无空格/正常 symbol/「文件尾」/L 行号锚点不受影响（既有测试全绿即证）。
2. 真实载荷重放：Run 3 的 6 条被拒条目——散文行照拒（报错现含契约句）；自然语言锚点报精确错；合法条目不受影响。
3. 全量 pytest + ruff。
4. 收益外推（登记）：Run 3 形态 plan:1#5 ≈ 58→~20 轮，省 ~9 min + ~5M cr/轮实例。

## 4. 生效面

append-trace 冷启动子进程，merge 即生效。judge 判据引用同一 `_CHANGE_SPEC_RULE`，追加为披露性补充、零判据方向变更，免重放回归。
