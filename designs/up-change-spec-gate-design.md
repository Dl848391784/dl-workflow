# up-change-spec-gate 设计：u/p 改动规格五要素硬门槛

> 2026-08-25 用户决议（四问四答确认）：
> ①落点 = **升级现有字段**（plan:1#5 change_list / plan:2#4 change_point），不新增 plan.md 节；
> ②准确性 = **codegraph 机械三验**（文件存在 / symbol 存在 / 行号在跨度内），append-trace 当场拒；
> ③u 侧 = **根因定位五要素**（文件/类/方法/行号 + 问题机制），落 understand:1 子2b；
> ④策略 = **叠加硬门槛**，现有全部判据保留，judge gate 零语义变更（不新增方框 → 免 judge 重放回归）。
>
> 背景：用户裁决——u/p 阶段（特别是 p）执行完，判断好坏的**唯一标准** =
> 产物是否**明确且准确**地回答：改哪个文件/类、哪个方法、多少行、怎么改。
> e（execute）阶段开发暂缓，本设计不动 execute。

## 1. 缺口分析（现状 vs 标准）

| 标准要素 | 现状 | 缺口 |
|---|---|---|
| 文件 | change_list「file→function→类型」/ change_point「file:line→类型」有 | — |
| 类/方法 | change_list 有 function；change_point 无 symbol 强制 | change_point 缺 symbol |
| 行号 | change_point 有 file:line（单行即可） | 无跨度强制、无验真 |
| 怎么改 | 无字段承载 | **完全缺** |
| 准确 | 无验真——judge 判不了真值（§3.5 #1 三层分工） | **完全缺** |

现状合法正例「change_point: paths.py:+CATEGORY_SUMMARY_RESULT（增）」按新标准不合格
（无行号锚点语法、无改法）——判据升级是**有意的行为变更**。

## 2. 改动规格条目语法（格式真源，单源常量 `_CHANGE_SPEC_RULE`）

change_list（plan:1#5，设计级，四要素）/ change_point（plan:2#4，执行级，五要素）
字段内**每条改动一行**：

```
<file>:<symbol>:L<a>-<b>（改）：<改法——改前→改后要点>     # 改
<file>:<symbol>:L<a>-<b>（删）：<删除对象+影响>            # 删
<file>:<symbol>（增@<锚点 symbol|L 行号|文件尾>）：<新增内容要点>  # 增
<file>:-:L<a>-<b>（改）：…                                 # 模块级（import/常量）symbol=-
```

- file = git 仓内相对路径（对齐 `git ls-files` 输出）。
- symbol = 函数名或 类.方法（codegraph `nodes.name` / `qualified_name` 匹配）；模块级填 `-`。
- L&lt;a&gt;-&lt;b&gt; = 行号跨度，单行写 L&lt;n&gt;；plan:1#5 设计级**行号豁免**（选型后才有精确行）。
- 改法 = 非空具体内容；纯动词独占（优化/修复/调整/重构/修改…无宾语无改前改后）= 拒。
- plan:2#4 五要素全强制（含行号）；plan:1#5 四要素（行号豁免）。

## 3. 机械三验（新 mech，statements 侧注册表 ×2 名）

`change_list_anchor_verify`（plan:1#5）/ `change_point_anchor_verify`（plan:2#4）
共享实现 `_check_change_spec_anchor(..., require_lines: bool)`：

| 验 | 改/删 | 增 |
|---|---|---|
| ①语法齐备 | 五/四要素缺一即拒，报错点名缺哪要素+范例（#5 判词指路） | 同 |
| ②file 存在 | `git ls-files` 全集核对；新文件配「改/删」= 矛盾拒 | file 不存在=合法（新文件），父目录须在仓内 |
| ③symbol 存在 | codegraph `nodes` 表 name/qualified_name + file_path 双匹配；symbol=`-` 跳过 | 新 symbol 不验（尚不存在）；**锚点** symbol 验存在 |
| ④行号 | 与 symbol [start_line,end_line] **有交集**（索引 stale 容差）且 ≤ 文件当前行数；symbol=`-` 只验 ≤ 文件行数 | 锚点为行号时 ≤ 文件行数 |

**降级规则（宁纵勿枉，与 `_implementation_nouns` 同先例）**：codegraph db 缺失、
或 db mtime 早于被验文件 mtime（索引过期）→ 跳过三验放过，不拒。
理由 = §3.5 #7：plan:1#5/plan:2#4 材料边界禁步内新取证，模型在步内**没有**
刷索引的合法修复路径，拒 = 逼编造；且 plan:1#1/plan:2#3 前序步已分别强制
codegraph 新鲜度前置与锚点存在性核验，本 mech 的定位 = **归一化转录失真兜底**
（前序已验真 → 转录编造/写错才被拒），正常路径零拦截。

**改法质量**：机械只判非空+非纯动词；「改前改后是否合理」= 语义，归现有 gate
方框二（字段与子2/子3 已定内容一致性）+ 子5 用户读回，judge 判据零变更。

## 4. u 侧：understand:1 子2b 根因行（qa 侧新 mech）

**根因行语法**（每原子问题链末一行，原子标签承接子2a MECE 标签）：

```
根因@<原子标签>@<file>:<symbol>:L<a>-<b>：<机制一句话>   # 代码侧根因
根因@<原子标签>@会话事实：<原话/选择记录指针>            # 用户决策/外部因素豁免
```

新 mech `root_cause_anchor_verify`（qa 侧注册表）：
①子2a 原子标签集 vs 根因行标签集**差集**（atomic_mece_alignment /
sc_coverage_trace 差集下沉范式第三例；子2a 缺失/无标签 → 跳过覆盖判，宁纵勿枉）；
②每条代码侧根因行过 §3 三验（db 缺失/过期跳过）；
③「会话事实」根因行不验（现有 gate 合法正例：用户决策瓶颈类问题以原话为环合法，
本设计不破这条——双结论制）。

gate 文本操作化：形式要件①「每问题 ≥2 环因果链到根因」的「到根因」钉死 =
根因行在场；补「根因行存在性/标签覆盖/锚点验真已机械校验，勿再判」。
judge 方框一/二/三（编造/同义反复/稻草人）零变更。

understand:1 子6（归一化陈述）purpose 补一句：代码侧根因的 boundary 须携带
根因锚点行（file:symbol:L 行号）——根因定位经 statements.boundary 流入
understand.md（轻量钉死，无新 mech）。

## 5. 双侧钉死与三通道同文（§3.5 #11/#29）

| 层 | 改动 |
|---|---|
| purpose（模型侧） | plan:1#5 / plan:2#4 / u:1 子2b / u:1 子6：语法+校验预告（机械会拒什么） |
| selfcheck | 同三步补「要素齐吗/锚点与前序留痕一致吗（机械三验会拒假锚点）」 |
| gate（judge 侧） | 形式要件段补「已机械校验」钉句 + mech_scope 句；**默认-PASS 方框零新增** |
| scaffold 骨架 | `【fields.change_list】/【fields.change_point】` 占位符升级为带语法示例（field→hint 单源常量表）；qa 侧骨架不动（语法在 purpose+报错文案，#26 两通道合规） |
| 报错文案 | 每个拒点：缺哪要素/哪验失败 + 正确范例 + 修复方向（回前序留痕取真实锚点） |

render-artifact 通用渲染 fields → plan.md/design.md 自动携带五要素，零改动。
phase-rules 零改动（无新步骤/门控位置不变/产物节不变——症状 M checklist 已过）。

## 6. 不改什么（边界）

- judge gate 语义零变更（不新增方框）→ **免 n≥6 三向重放**（§16 义务不触发）。
- execute/review/evolution 零改动（e 阶段暂缓决议）。
- plan:4 门栏（ARTIFACT_CONTAINS 三节）零改动——五要素经字段层流入 plan.md。
- u:2/u:3/u:4 零改动（目标/范围/验收不涉代码改动定位；u:4 验收包六字段已含
  基线实测，验收精度问题不在本次范围）。

## 7. 测试与验证

1. **单测**（test_dl_flow_engine.py 表驱动）：tmp git repo + tmp codegraph db fixture
   ——合规过 / 缺要素拒 / 假 file 拒 / 假 symbol 拒 / 行号出界拒 / 行号交集容差过 /
   模块级 `-` 过 / 增-新文件过 / 增-假锚点拒 / db 缺失跳过 / db 过期跳过 /
   根因行标签差集拒 / 会话事实豁免过 / 纯动词改法拒。
2. **真实仓冒烟**：以 factor_ic_analyzer 仓（codegraph db 在场）构造新格式
   payload 跑 append-trace 路径——真 symbol 过、篡改行号拒。
3. **历史 payload 对照**：旧格式真实 trace（如 tail_volume plan:2#4）按新 mech
   必拒——确认拒消息指路清晰（有意的行为变更，非回归）。
4. nodes-index.md 手工同步（plan:1#5/plan:2#4/u:1 子2b/u:1 子6 摘要块）；
   install.sh 重 copy skill 副本。

## 8. 已知边界（记台账，不在本次修）

- 根因行逐原子覆盖依赖子2a 标签可提取；子2a 标签缺失时覆盖判跳过（宁纵勿枉），
  实测抖动再按 §3.5 #13 下沉。
- 行号验真对「改动点在 symbol 跨度外但确属该函数相关行」（装饰器上方、调用处）
  靠交集容差+`-` 逃生门吸收；实测误伤再校准。
- 改法「明确性」语义层（改前改后是否够具体）首版只靠非空+非纯动词机械判，
  弱模型写「改 X 为 Y」式最小合规但信息稀薄的改法，靠子5 用户读回兜——
  实测不足再加 judge 方框（那时才补重放义务）。
