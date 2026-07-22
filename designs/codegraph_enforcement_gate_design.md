# Design: codegraph 查证强制门禁（兑现 spec_bridge 行 89 留的口子）

> **任务**：把 codegraph 查询从"靠我自觉 Bash 调用"升级为"证据约定 + H15 硬规则 + PreToolUse hook 门禁"三档约束，根治"该查没查 / 伪造跨文件调用关系"风险。
> **日期**：2026-07-22
> **授权依据**：`designs/feat_claude_code_spec_bridge.md` 行 19/40/89——迁移时已知 Hermes `pre_llm_call` hook 自动注入 codegraph 模块图在 Claude Code 下失效，当时用"CLAUDE.md 常驻 + 手动 codegraph"替代，**承认只覆盖 80%，行 89 明确留口"真出现忘记加载再评估 hook"**。用户 2026-07-22 要求评估并上 hook = 兑现此口子。
> **关联规范**：PROJECT.md §硬规则（H1-H13，加 H15）；AGENTS.md §入口守门员；CLAUDE.md §3/§4；H8（Design-First：本次 2+ 文件）。

---

## What（改造定义）

三档约束，由弱到强、互相补位：

| 档 | 机制 | 强制力 | 文件 |
|---|---|---|---|
| 1 | **证据约定**：凡跨文件调用/影响面断言，必附 `codegraph callers/impact` 输出或 `file:line` 证据 | 自觉（可被抽查验真） | CLAUDE.md §3/§4 |
| 2 | **H15 硬规则**：改已有 `.py` 源码前必须对该 symbol 跑 `codegraph callers` 或 `impact`；commit 引用 H15 | 规范层 + commit 取证 | PROJECT.md §硬规则、AGENTS.md |
| 3 | **PreToolUse hook 门禁**：Edit/Write 已有 `.py` 源码前，若本会话 audit log 无任何 codegraph 查询记录 → 阻断 | 机器强制 | `.claude/hooks/*` + `.claude/settings.json` |

档 3 的 PostToolUse audit 自动留痕（每次 Bash 跑 codegraph 自动记一行），不靠自觉。

## Why（根因 + 为何三档）

**根因**：`spec_bridge` 行 19 列出执行层 3 个 Hermes 机制，①`pre_llm_call` hook 自动注入 routing table + codegraph 模块图"在 Claude Code 下全部失效"。行 40 用 CLAUDE.md 常驻替代路由注入、用"手动 codegraph"替代模块图注入，**行 89 自承仅覆盖 80%，剩 20% 靠 agent 自觉**。这 20% 正是"改源码前没查结构、凭片段猜/伪造调用关系"的高危区——用户担心的幻觉集中于此（单文件明面事实 Read 即得不会幻觉；跨文件调用关系/影响面才会）。

**为何三档**：单靠任一档都有缺口——证据约定(档1)靠自觉；硬规则(档2)靠自觉读+commit 事后取证；hook(档3)机器强制但需防误报。三档叠加：档3 保证"至少查过结构"是硬底线，档2 把"查对 symbol"写进规范可取证，档1 让断言可被你即时抽查验真（"贴 codegraph 输出"即验真）。

**顺带清理两个迁移幽灵**（加剧虚假安全感，必须一并修）：
- `check_doc_layer.py` 被 PROJECT.md/CLAUDE.md/skills README/spec_bridge **4 处引用"禁止跨层重复"，但脚本全仓不存在**→"跨层不重复"目前零强制。本设计不重建它（超范围），但 H15 的"检查工具"列只引用本设计真实新建的 hook 脚本，绝不再引幽灵。
- AGENTS.md §入口守门员仍写"codegraph 上下文：已由 pre_llm_call hook 自动注入"→与纯 Claude Code 现状不符，改为真实描述。

## How（hook 设计 · 档 3 核心）

### 文件清单（8 个，超 H9，分 3 批提交，见末尾）

| # | 文件 | 作用 | 批 |
|---|---|---|---|
| 1 | `designs/codegraph_enforcement_gate_design.md` | 本文件（Design-First 审核） | 0 |
| 2 | `.claude/hooks/codegraph_gate.py` | PreToolUse(Edit\|Write) 门禁 | 1 |
| 3 | `.claude/hooks/codegraph_audit.py` | PostToolUse(Bash) 留痕 | 1 |
| 4 | `.claude/settings.json` | 注册两 hook + matcher | 1 |
| 5 | `.claude/hooks/test_codegraph_gate.py` | 门禁判定逻辑单测（仿 scripts/test_check_*.py 风格） | 2 |
| 6 | `PROJECT.md` | §硬规则加 H15 行 + 补注释 | 3 |
| 7 | `AGENTS.md` | §入口守门员去 Hermes 虚假描述，改真实 | 3 |
| 8 | `CLAUDE.md` | §3 执行映射加证据约定 + §5 加 H15 指针 | 3 |

### gate.py 判定逻辑（PreToolUse，收到 stdin JSON：session_id/tool_name/tool_input）

```
file = tool_input.file_path
1. 白名单跳过(exit 0)：非 .py / test_*.py / 新建文件(仓库无此 path) / scripts/check_*.py / *.md / *.toml/*.json
2. 新鲜度检查(只警告不阻断)：读 .codegraph/codegraph.db MAX(indexed_at)；超 72h → stdout 注入警告"索引可能过期，先 codegraph sync"
3. 读 .claude/.cg_audit/<session_id>.log，判断本会话是否有 codegraph callers|callees|impact|affected|context|query 记录
   - 有 → exit 0 放行；可选：跑 `codegraph affected <file>` 把影响面经 stdout 注入(补"自动注入"缺失)
   - 无 → exit 2 阻断，stderr 提示："改 <file> 前先跑 `codegraph callers <symbol>` 或 `codegraph impact <symbol>`(H15)。纯注释/格式：跑一次 impact 后即可放行"
```

### audit.py 留痕逻辑（PostToolUse，matcher=Bash）

```
cmd = tool_input.command
若 cmd 含 codegraph 且子命令 ∈ {callers,callees,impact,affected,context,query}：
   追加 "<iso_ts>|<subcmd>|<symbol或args>" 到 .claude/.cg_audit/<session_id>.log
exit 0(永不阻断)
```

### settings.json

```json
{
  "hooks": {
    "PreToolUse": [{"matcher":"Edit|Write","hooks":[{"type":"command","command":"python3 .claude/hooks/codegraph_gate.py"}]}],
    "PostToolUse": [{"matcher":"Bash","hooks":[{"type":"command","command":"python3 .claude/hooks/codegraph_audit.py"}]}]
  }
}
```

### 判定取舍（刻意的弱门禁）

- **"查过即放行"是弱关联**（查了 foo 不等于查了 bar）：刻意取舍。强关联(精确 symbol 匹配)需解析"本次 Edit 涉及哪些 symbol + 是否精确查过"，实现复杂且误报高(易卡正常编辑)。弱关联已挡住最高危场景——"全新会话直接改源码且零 codegraph 查询"。后续可加强为"按 file 粒度留痕"。
- **逃生口**：不设硬逃生口(Claude 自己设不了 env)。被卡时按提示跑一次 `codegraph impact` 即放行——这正是门禁目的，非 bug。
- **阻断 vs 软提示**：默认 exit 2 硬阻断(用户选了"强制门禁")。若实测 hook 机制与预期不符或误报偏高，**降级档**：exit 0 + stdout 注入影响面(不阻断，纯提示)，此时仍保留 audit 留痕可被你抽查。此项作为 plan 内备选，审 plan 时可定。

## Don't（不做）

- ❌ 不改任何业务代码 / check_*.py / paths.py / schemas
- ❌ 不重建 `check_doc_layer.py`（独立幽灵，超本次范围；仅标注其引用失效）
- ❌ 不强 symbol 精确匹配（误报风险，见上）
- ❌ 不阻断非 .py / test / 新建文件（白名单）
- ❌ 不在索引过期时阻断 sync 缺失（只警告，避免卡死）

## When

改任何**已存在的 .py 源码**前触发档 3；任何含跨文件调用/影响面断言的回答触发档 1；commit 涉及 .py 源码改动触发档 2 取证。

## Verify

- [ ] `pytest .claude/hooks/test_codegraph_gate.py`：白名单跳过/零查询阻断/有查询放行/新鲜度警告 四类场景通过
- [ ] 手测：新会话直接 Edit 某已有 .py → 被阻断+提示；跑 `codegraph impact <sym>` 后再 Edit → 放行
- [ ] audit log 格式可读：`cat .claude/.cg_audit/<session>.log` 能看到留痕
- [ ] `grep -rn "pre_llm_call" AGENTS.md` → 零命中（虚假描述已清）
- [ ] PROJECT.md §硬规则表出现 H15 行，"检查工具"列引用真实 hook 脚本
- [ ] 规范引用行号写进 commit message

## 风险与已知前提

1. **hook 机制假设待实测**：exit 2 阻断 + stderr 反馈 + stdout 注入上下文 + session_id 可用，基于 Claude Code hooks 通用行为。首版若不符，按"阻断 vs 软提示"降级档处理。
2. **索引新鲜度**：db 79MB，`codegraph sync` 耗时；gate 只警告不阻断，避免卡死。过期索引会给出错误调用关系——这是 codegraph 自身局限，门禁不兜底，靠警告+你判断。
3. **弱门禁边界**：挡"零查询就改"，不挡"查错 symbol"。档 1(证据约定)+档 2(commit 取证)补这个缝：断言要附证据、commit 要引 H15，事后可追溯。

## 提交分批（H9：≤3 文件 ≤200 行/批）

- **批 0**：本 design.md（Design-First 审核 = ExitPlanMode 审批）
- **批 1**：gate.py + audit.py + settings.json（3 文件，核心机制）
- **批 2**：test_codegraph_gate.py + 批1 小修（测试）
- **批 3**：PROJECT.md + AGENTS.md + CLAUDE.md（3 文件，规范同步）

每批独立可测、可回退。
