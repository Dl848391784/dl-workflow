# 横幅全阶段进度树 + 顺序/状态修正 Design

> ⚠️ **已弃用（2026-07-24，§orchestration v2）**：本文的「模型每轮输出全 5 阶段进度树文本」展示方案**已弃用**。用户决策：进度展示只靠原生 TUI TaskList，不再输出 checklist/进度树文本（`phase-rules.md` 行 14 已写明）。
> 保留本文作历史记录。其「模型需 `dl-cmd.sh status` 取阶段真值」结论仍有效（status 末尾输出一行当前阶段/子阶段/子步骤数据，非全树），但「模型拼进度树展示」部分勿用。勿据本文实施进度树展示。

> 状态：~~设计中（2026-07-24）。H8 Design-First。父系统：`designs/tui-state-machine-design.md`。~~ 已弃用，见上。
> 范围：~~改显示层--横幅从"只显当前阶段单行"扩成"全 5 阶段进度树";修顺序乱(横幅落底)+ 状态语义(进行中≠完成)。~~ 已弃用。

## 0. 背景（实测坐实，2026-07-24）

用户交互会话观察到三问题：
1. **横幅只显当前阶段 + 子阶段**，其余 4 阶段不显示（看不出整体进度）。
2. **1.1 一开始就"选中"**，应为"执行完才选中"（进行中≠完成）。
3. **横幅在底部**，分析不在"正在执行阶段下面"展示（顺序乱）。

**通道结论（实测坐实，推翻中间误判）**：
- ark-code-latest **收不到 `hook_additional_context` attachment**（交互会话模型亲口："ark 端点实测收不到 hook 注入段，按规则用 wf-cmd 确认"；`-p` canley 一直 `NO_INJECTION`）。
- define-problem 走通 = 靠 **phase-rules（system-prompt，ark 能收到）的强制时序** + `dl-cmd.sh status`（Bash 通道，ark 必读）兜底，**不靠 attachment**。
- => 横幅树方案 = 方式A：**phase-rules 给格式规则 + 模型用 `dl-cmd.sh status` 拿状态拼树**。与 define-problem 同条验证有效的路。

**根因（顺序乱）**：transcript 00ce4503 实测--模型先出临时横幅"确认阶段中"（事件9）-> 探查（事件10）-> 才 TaskCreate 建清单（事件17-33）-> 最后出正式横幅（事件46）。output-style/phase-rules **没强制"先对齐清单 + 首行进度树"**，模型把横幅和建清单混排。

## 1. 设计决策（方式A）

- **横幅树生成**：模型生成（非 hook 注入）。phase-rules 给树格式 + 图例 + 状态规则；模型每轮用 `dl-cmd.sh status` 拿当前 phase/sub_index，自己拼全 5 阶段树。
- **树靠 dl-cmd.sh status 供真值**：现 status 只输出当前阶段单行（line 60），**扩加"进度树"输出**（全 5 阶段 + 当前阶段展开子阶段 + ☑/▶/○ 状态标记）。status 读 state.json，最准；bash 循环遍历 `WF_PHASES` + `wf_sub_total`/`wf_sub_label` 已有 helper，干净。
- **状态图例**：`☑`=完成（completed，选中打勾）/ `▶`=进行中（in_progress）/ `○`=待办（pending）。**显式区分进行中与完成**（解问题2：1.1 执行中=▶，执行完才=☑）。
- **顺序强制**：phase-rules + output-style 补"每轮首步=对齐 TaskList 清单 + 首行输出进度树，再做实际工作"；禁临时横幅（如"确认阶段中"）。

## 2. 进度树格式

```
## WORKFLOW 进度 · <name> · 阶段 [n/5] <当前阶段中文名>
1. ☑ 理解和求证问题          [当前]
   ├ 1.1 ▶ 理解问题和背景     ← 进行中
   ├ 1.2 ○ 明确目标和价值
   ├ 1.3 ○ 确定范围与约束
   └ 1.4 ○ 定义成功标准和验收方式
2. ○ 生成执行计划
3. ○ 执行
4. ○ 审核结果
5. ○ 进化
```
- 非当前阶段：单行 + `☑/○`（折叠子阶段）。
- 当前阶段：标 `[当前]` + 展开子阶段带 `▶/☑/○`。
- 图例在树末行或 phase-rules 注明。

**dl-cmd.sh status 扩**：在现有 status 输出后追加一段"进度树"（machine-readable 也好，模型直接贴）。bash 遍历：
```
for i in "${!WF_PHASES[@]}"; do
  p=${WF_PHASES[$i]}; idx=$((i+1))
  st = (idx<cur_idx)?☑ : (idx==cur_idx)?▶ : ○
  if idx==cur_idx && sub_total>0: 展开 sub 全带 ▶/☑/○
  else: 单行
done
```

## 3. 改动（分小 commit，守 H9）

| # | 文件 | 改动 | 生效 |
|---|---|---|---|
| 1 | `designs/banner-tree-design.md` | 本文（H8） | 本 commit |
| 2 | `scripts/workflow/dl-cmd.sh` status 分支 | 扩"进度树"输出（全 5 阶段 + 当前展开子阶段 + ☑/▶/○） | 直接跑源（非 .py） |
| 3 | `scripts/workflow/phase-rules.md` | 总则加"每轮首步=对齐清单+首行输出进度树，禁临时横幅"；横幅树格式 + 图例规则（方式A：模型用 status 拼树） | 新会话载入（append-system-prompt） |
| 4 | `output-styles/workflow.md` | 横幅要求从"单行 ## PHASE"改成"进度树"；图例；顺序强制 | install.sh + 重启 |

## 4. 铁律

- **H8**：本文先于改 3 文件。**H9**：分 commit。**H15**：改 `dl-cmd.sh`（非 .py）+ `phase-rules.md`/`workflow.md`（md）= gate 白名单跳过；无 .py 改动。
- **no silent fallback**：status 扩树若 phase/sub_index 缺，降级显单行（不崩）。
- **verify before claiming done**：新会话实测横幅树渲染 + 顺序 + 状态对。

## 5. 风险

| # | 风险 | 缓解 |
|---|---|---|
| 1 | 模型拼树格式错（多行易错） | status 直接输出整段树文本，模型"原样贴"为主、自己拼为辅；phase-rules 给精确模板 |
| 2 | 状态图例 ▶/☑ 混淆 | 树内每项带文字注释（进行中/完成）不只靠符号 |
| 3 | phase-rules md 改后旧会话不生效 | 重启会话验证（非 resume） |
| 4 | TaskList 仍可能落底部（旧边角） | phase-rules 强制"首轮一次性建齐 + 之后不重建"；顺序靠建齐保证 |

## 6. 验证

`dl verify-tree`（新会话）：
1. 横幅是全 5 阶段树，当前阶段展开子阶段。
2. 1.1 进行中=▶（非 ☑）；完成后变 ☑。
3. 横幅在首行（清单之上），无"确认阶段中"临时横幅。
4. `dl-cmd.sh status` 含进度树输出。
