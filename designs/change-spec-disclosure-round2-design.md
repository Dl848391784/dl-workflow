# 改动规格门槛披露面第二轮设计（change-spec-disclosure-round2）

> 2026-08-26。触发：5 轮因子工作流目标（跑 3 轮中止转优化）——change-spec 前缀修复（65e0bd2）三轮实证零复发后，拒绝形态迁移到两个新披露缺口。前轮设计：designs/change-spec-prefix-tolerance-design.md。

## 1. 证据链（三轮运行拒绝日志逐字可复验）

**形态 A：注记条目**（Run 3 plan:1#5，6 拒中 3 次）——模型把决策注记/被否方案/承接链说明当 change_list 条目写：
- 「（口径选型为设计决策、非代码改动，本决策不新增独立改动条目）——承接链：决策2 change_list=…」
- 「（txt 不纳入→无 txt 侧代码改动条目；现有 txt 生成链保持不动）——复核：format_percentage…」
- 「（被否方案无落地改动条目——仅列假想改动面供 ADR 追溯）假想=…」
共同特征：条目以 `（` 开头或含 注记/被否/假想/承接/不执行 词形——**内容合法但放错字段**（应去 boundary/rejected）。通用文法报错只重印规则，不指路「该挪哪个字段」，模型连试 3 种注记写法。

**形态 B：非代码文件 symbol 误用**（三轮合计 ≥5 次）——模型拿 Jinja 宏名/测试 fixture 名当 codegraph symbol：
- `render_factor_card`（web_ui/templates/_macros.html，Run 1/2/3 各中一次）
- `bt_mock`/`mock_obq_result`（web_ui/test_cases/test_app.py，Run 2）
- `L103 app = Flask(__name__)`（prose 进 symbol 槽，Run 1）
- `_ann_pct`（Jinja 变量，Run 1）
根因：**codegraph 只索引代码文件（.py 等），html 模板/fixture 无 symbol 可查**——模型不知道这条 escape hatch 的适用面。现有报错已提「模块级改动 symbol 填 -」，但「模块级」被理解成 import/常量，覆盖不到「模板/fixture 这类根本没进索引的文件」。

**两轮健康度对照**：前缀修复后 plan:1#5/plan:2#4 提交数 13→5→3→7、10→4→（Run3 #4 未跑到）；被拒全部为零重复形态（无同条重交）——披露面修复方向有效，本轮是同一家庭的第二轮。

## 2. 方案（两处 surgical，文案/报错层，零判据语义变更）

### 修 1：scaffold 占位提示补「条目内容边界」一句（_FIELD_SCAFFOLD_HINTS，dl_flow_engine.py）

change_list/change_point 提示各追加：
「只写可执行改动条目——决策注记/承接链说明写 boundary 字段、被否方案写 rejected 字段，禁括号注记条目；html 模板/Jinja/fixture 等无 codegraph symbol 的文件：symbol 填 -、行号锚定」

### 修 2：报错按失败形态分诊（_verify_change_spec_entry，dl_flow_engine.py）

- 语法不合分支：条目剥离前缀后以 `（` 开头，或含 注记|被否|假想|承接链|不执行|记录用途 词形 → 改报「该条是注记/说明非改动条目——注记挪 boundary 字段、被否方案挪 rejected 字段；change_list 只写可执行改动条目」；
- symbol 查无分支：file 后缀属非代码文件（.html/.htm/.j2/.jinja/.md/.txt/.json/.yaml/.yml/.toml/.cfg）→ 报错改指「codegraph 不索引该文件类型（模板/文档/数据），symbol 填 -、用 L<a>-<b> 行号锚定」；
- 其余分支零变化（_CHANGE_SPEC_RULE 不动——前缀轮已补正例，本轮判断规则文本不再膨胀，gap 用分诊报错补）。

### 生效面

同前轮：append-trace 冷启动子进程，merge 即生效。judge 判据零语义变更（报错文案不向模型新增/放宽任何通过路径，只改指路质量），免重放回归。

## 3. 不做的事（关闭项）

- **不改 _CHANGE_SPEC_RULE 正文**——前缀轮已加正例；规则文本继续膨胀会稀释可读性，本轮 gap 全走分诊报错与骨架提示。
- **不处理 Run 2 u:4#1 的 TaskList 仪式（47/96 调用）与元探查（~30 调用）**——下钻结论：主因是 headless 无人值守驱动下「TUI 段结束→driver 退出→外部续驱→步重开」的 reopen 税（前台 TUI/有人值守 headless 均无此形态），属驱动方式产物非系统缺陷；TaskList 仪式归 output-style 文案层（弱模型文案杠杆弱），单样本（#22），登记不立项。
- **不优化 u:1#3 因果链挖掘（两轮稳定 6.6-7.0m）与 plan:1#3+#4 合并段（两轮 14-16m，generation-bound）**——判断思考层瓶颈（cost-opt #1），无系统侧杠杆，登记。
- **不做字段级自动改写**（把注记条目自动挪到 boundary——写侧猜语义风险大，指路比代劳安全）。

## 4. 验证

1. **新增单测**（tests/test_dl_flow_engine.py 既有 change_spec 类）：
   - 注记条目 3 种形态（`（…）`开头/含「被否」/含「假想」）→ 拒且报错含「挪 boundary/rejected」；
   - 正常改动条目含「被否」两字但形态合法（如 `src/foo.py:bar（改）：删除被否决的旧分支`）→ 不误伤（词形检测只在语法不合分支生效）；
   - 非代码文件 symbol 误用（`web_ui/templates/_macros.html:render_factor_card（改）：…`）→ 拒且报错含「symbol 填 -」；
   - 同文件 symbol 填 `-` + L 行号 → 通过（escape hatch 可用）；
   - scaffold 骨架含「只写可执行改动条目」。
2. **真实载荷重放**：三轮 8 条被拒条目（3 注记 + 5 symbol 误用）逐条过 `_verify_change_spec_entry`——应全部命中新分诊文案；前缀轮 fixture（合规/矛盾/语法外各层）全绿防回归。
3. **全量 pytest + ruff**。
4. **收益外推**（登记待下轮对表）：Run 3 plan:1#5 的 3 次注记拒 + 三轮 ≥5 次 symbol 误用拒若首轮即命中分诊指路，估计每轮省 3-6 个提交循环 ≈ 2-4 min + 1-2M cache_read（每循环全上下文重读 ~150-300k）。

## 5. 风险

- **词形误伤**：注记词形（被否/假想）可能出现在合法改法文本里——检测严格限定在「语法不合分支」（条目本来就不成改动条目形态才进），合法条目走不到；测试钉死不误伤案例。
- **非代码后缀清单误扩**：清单只含常见非代码后缀；代码后缀（.py/.js/.ts/.go…）照走 codegraph 验真，行为零变化。
