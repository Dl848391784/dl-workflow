# 改动规格条目「改=」前缀打地鼠修复设计（change-spec-prefix-tolerance）

> 2026-08-25。触发：interaction_amplitude__ret3d_pos_annualized 运行审计（plan:1#5 / plan:2#4 两段 23 次 append-trace 提交、19 次被机械门槛拒绝，打地鼠成本 ≈ 两段各自成本的一半）。

## 1. 证据链（全部逐字可复验）

- **打地鼠台账**：plan:1#5 段 57 调用中 13 次 `--from-file`（2 过 11 拒）、plan:2#4 段 48 调用中 10 次（2 过 8 拒）；两段合计 ~63 次调用是「拒-改-重交」循环，占各自段成本 ~50%（墙钟 ≈ out÷130tok/s 拟合，out 大头是循环再生）。
- **被拒条目形态**：19 次拒绝里 ~17 次的条目以 `改=`/`删=` 开头（报错引号内逐字可见），例如 plan:2#4 同一条 `改=backtest/common/layered_backtest.py:_aggregate_results:L71…` **原样重交 5 次**。
- **文案与解析器矛盾（主根因，正则实测）**：`_CHANGE_SPEC_RULE`（dl_flow_nodes.py:639，purpose/selfcheck/gate/报错文案四处同文）写「改/删=<file>:<symbol>:L<a>-<b>（改|删）：<改法>」，模型按文档字面前缀写 `改=`；但 `_CHANGE_SPEC_ENTRY_RE`（dl_flow_engine.py:4592）从 `^(?P<file>…)` 起匹配，**任何 `改=` 前缀条目必 FAIL**（python 逐条重放实证）。设计文档正例（up-change-spec-gate-design.md L32-35）、scaffold 占位提示（`_FIELD_SCAFFOLD_HINTS`）、evidence 里全部通过条目**均无前缀**——唯一矛盾点就是规则文案的「改/删=」表述。
- **报错放大器**：报错每轮重印同一段含「改/删=」的文法 → 每轮都在教模型再写一遍非法形态；报错零条具体正例（#31 骨架表达力缺口），模型实例化失败后 grep+Read 设计文档反推校验实现（#26 格式猎捕，plan:1#5 段内实测 2 调用）。
- **门槛本身在履职**：锚点三验逮真错（`render_factor_card` 在 `_macros.html` 查无）；「缺 H1.1 传导」「缺 change_list 字段」两拒为合法修正循环。**本设计不动门槛，只修披露面与解析器宽容度。**

## 2. 方案（两处 surgical 改动，均在 dl_flow_engine.py / dl_flow_nodes.py）

### 修 1：解析器接受可选类型前缀（v2.65 先例：格式归脚本，合理形态不该被死板正则误伤）

`_verify_change_spec_entry` 在 `_LIST_PREFIX_RE` 剥离后、正则匹配前，剥离可选 `改=`/`删=`/`增=` 前缀；**前缀类型与（kind）交叉核对**：
- 前缀与括号类型一致（`改=…（改）`）→ 正常解析，与无前缀形态完全等价；
- 不一致（`删=…（改）`）→ 拒，报错指明「前缀类型 删 与（改）矛盾——类型声明两处须一致」；
- 无前缀 → 行为零变化（向后兼容，evidence 既有全部通过条目形态不受影响）。

### 修 2：规则文案与骨架提示各补一条具体正例（#31 修法）

- `_CHANGE_SPEC_RULE` 追加：「正例：src/foo.py:bar_baz:L10-12（改）：改前 X 逻辑 → 改后 Y 逻辑（类型词写括号内，行首改=/删= 前缀可省）」——单源常量，purpose/selfcheck/gate/报错四处同步生效；
- `_FIELD_SCAFFOLD_HINTS` 的 change_list/change_point 提示各补同款正例一行（占位符括注形态，替换即消失）。

### 生效面

`append-trace` 每次调用都是冷启动子进程（`python3 dl_flow_engine.py append-trace …`），merge 进 main 即对全部在飞/未来实例生效，无需重启任何东西。judge 侧 gate 引用同一 `_CHANGE_SPEC_RULE` 常量——追加正例不改判据方向（前缀形态本就非法→合法是放行方向，judge 判据只索「语法齐备」，零语义变更），**免重放回归**（与 up-change-spec-gate 设计 §8 「judge gate 零语义变更免重放」同口径）。

## 3. 不做的事（关闭项，防重复提案）

- **不撤/不改五要素门槛与锚点三验**——门槛在履职（§1 末条），问题在披露面。
- **不做字段级定位诊断**（「你缺的是（改）：段」式逐字段报错）——19 例实测拒绝形态里 17 例由前缀矛盾单根因解释，修 1+修 2 全覆盖；字段级诊断是过度工程，留作后续若新型拒绝形态复现再立项。
- **不改 u 侧根因行语法**——`_ROOT_CAUSE_LINE_RE` 字面含 `根因@` 前缀，文案与解析一致，无同类矛盾（已核对）。
- **不改 judge 判据文本语义**（§2 免重放论证）。

## 4. 验证

1. **新增单测**（tests/test_dl_flow_engine.py 既有 change_spec 测试类内）：
   - `改=src/foo.py:bar（改）：改 X 为 Y 逻辑` → 通过（与无前缀形态等价）；
   - `删=src/foo.py:bar（改）：…` → 拒，报错含「矛盾」；
   - 无前缀形态回归（既有测试全绿即证）；
   - scaffold 骨架与报错文案含「正例」字样。
2. **真实载荷重放**：本轮 19 条被拒条目逐条过 `_verify_change_spec_entry`——语法层应通过（仍应被后续层拒的照拒：`show_report（改）：改前 A → 改后 B` 的 how 空壳层、`render_factor_card` 的 symbol 查无层、缺传导/缺字段层——重放断言分层归属，防「前缀宽容把真错也放了」）。
3. **全量 pytest + ruff**（repo 既有收口纪律）。
4. **收益外推**（不修不量，仅登记）：按本轮台账，消灭打地鼠后 plan:1#5 ≈ 57→~20 调用、plan:2#4 ≈ 48→~20 调用，合计省 ~11-12 min 墙钟 + ~5M cache_read；下轮运行按同口径对表（runtime-audit #17 去重口径）。

## 5. 风险

- **前缀宽容放错方向**：唯一新增放行面是「带合法前缀的合法条目」——该形态语义自明（类型双声明一致才放），无误放面；矛盾双声明是拒方向。
- **在飞实例**：当前实例已收在 plan:4 门栏（归一化步全过），修复对它零影响；未来实例直接受益。
