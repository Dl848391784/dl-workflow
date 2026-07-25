# Evidence Chain Design（推导证据链：记录 + 防腐 + 事后回溯）

> ⚠️ **已弃用（2026-07-23，§8.6c）**：本文档描述的"模型每轮自发记 claim/依赖/证据（### EVIDENCE 标记 + evidence_append.py 解析）"推理溯源系统**已删除**。用户决策弃用（transcript 解析脆 + 与 gate 裁决诉求不符）。
> **替代机制**：`designs/tui-state-machine-design.md` §8.6 的 `engine.write_gate_verdict`——gate-pass 时直接写 `kind=gate` 裁决记录到 `<项目>/.claude/evidence/<name>.jsonl`（不解析 transcript）。evidence.jsonl 落点 + commit_sha 防腐语义仍沿用本文档 §5/§6.1。
> 本文档保留作历史设计记录，勿据其排查运行问题（运行问题看 workflow-creation skill 症状手册）。

> 状态：~~设计中（2026-07-23 起）。本文件为 H8 Design-First 产物，是证据链子系统的真源。~~ 已弃用，见上。
> 对应实现（待做）：`~/.dl-workflow/hooks/evidence_append.py`（Stop hook）、
> `<项目>/.claude/evidence/<name>.jsonl`（运行态真源）、
> `scripts/workflow/dl-lib.sh`（settings.json 注册新 hook）。
> 父系统：`designs/workflow-system-design.md`（5 阶段状态机）。
> 范围：本轮只定**地基 + 脚本设计**；**门控（执行完备检查）与审核（结论回溯）机制留占位，后议**（§10）。

## 0. 背景与目标

### 0.1 现状缺口

现有工作流系统（`workflow-system-design.md`）有**状态机**（state.json 记 phase/sub_index/gate/history），
能答"这个工作流跑到哪了"，但答不了"凭什么得出这个结论"。

- state.json 的 `history` 是**转场流水账**（哪阶段、何时进/出、怎么出），不是推导链。
- review 阶段规则仅 prose 一句"结论 + 证据"（`workflow_phase.py:63`），无结构化证据概念。
- 全仓 grep 确认无 `evidence/claim/depends/proof` 结构化概念（仅上述 prose 提及）-> 是空白，非重造。

### 0.2 目标

建一套**推导证据链**（evidence chain），类比算 `20×25`：

```
ev_001  claim="20=4×5"     depends_on=[]
ev_002  claim="4×25=100"   depends_on=[ev_001]
ev_003  claim="5×100=500"  depends_on=[ev_002]   ← 结论
```

两个用途（用途②本轮只搭骨架，机制后议）：

1. **门控执行完备**：机器遍历 `status=active` 节点，判"每个结论是否都有闭合证据 + depends_on 链可溯"。
2. **回溯审核结论**：走到任一节点，用其 `commit_sha` 还原**当时的代码快照**核验推导成立与否。

### 0.3 与现有系统的关系

**state.json 的同伴，非替代**（守 H1 模块边界精神）：

| | state.json | evidence.jsonl |
|---|---|---|
| 关注点 | 跑到哪（流程状态） | 凭什么（推导证据） |
| 变化方式 | 改写（in-place 改 gate/history） | 追加（只 append，不改历史） |
| 寿命 | 运行态，结束即删 | **持久物，全程提交进 repo** |
| 可移植 | 含本机绝对路径/session uuid | `file:line` 相对指针 + commit SHA，可移植 |

## 1. 关键事实（设计前已核实）

| # | 事实 | 来源（证据） | 对设计的影响 |
|---|---|---|---|
| 1 | state.json 被 gitignored | `git check-ignore -v` -> `.gitignore:52` 命中；注释原话"运行态…不入版本控制" | evidence.jsonl 不能住 `workflows/<name>/`（会被吞） |
| 2 | worktree 工作树**无** `workflows/` 目录 | `ls .claude/worktrees/demo/.claude/` 只有 `hooks/`+`skills/`（gitignored 不 checkout） | 在 worktree 内 `git add .claude/workflows/...` 会 `fatal: did not match any files`（实测）-> 落点必须在 tracked 可见路径 |
| 3 | `.claude/` 本身 tracked，`.gitignore` 只忽略 `worktrees/`+`workflows/` 两行 | `git ls-tree HEAD -- .claude/` -> hooks/skills tracked | 落点用 `.claude/evidence/<name>.jsonl`：worktree 可见 + 不被忽略 |
| 4 | 现有 hook 读 transcript 解析标记的范式已验证可用 | `workflow_advance.py:_last_assistant_text` + `DONE_RE`/`SUB_DONE_RE` 解析 `### PHASE_DONE`/`### SUB_DONE` | 新 hook 复用此范式解析 `### EVIDENCE:{json}`，机制低风险 |
| 5 | hook 装在 `~/.dl-workflow/hooks/`，settings.json 用 `~` 引用源（shell 展开） | `workflows/demo/settings.json` hook command = `python3 ~/.dl-workflow/hooks/workflow_advance.py` | 新 hook 同法注册；改源 `git pull` 即生效，无需重建 worktree |
| 6 | hook 从 cwd 反查主 repo 根已解决（worktree 内 `--git-common-dir`） | `workflow_advance.py:_resolve_project_root` | 新 hook 复用此函数定位 `<项目>/.claude/evidence/<name>.jsonl` |
| 7 | PHASES/PHASE_LABELS/SUBPHASES 在 dl-lib.sh + 两 hook **三处各持一份** | `workflow_advance.py:46` 注释自述 | schema 常量若跨语言复用需注意同样的"避免跨语言 source"取舍 |
| 8 | 多分支各自 append 同一全局文件会 merge 冲突 | git 合并语义：两边同加行 -> 冲突 | **per-workflow 一个文件**（`<name>.jsonl`），不同分支写不同文件，合并零冲突 |

## 2. 架构总览

```
模型回复末尾输出:
  ### EVIDENCE:{"claim":"...","depends_on":["..."],"evidence":[...]}
        │
        ▼
Stop hook  evidence_append.py（新增，与 workflow_advance.py 并列）
  ├─ 读 transcript（复用 _last_assistant_text 范式）
  ├─ 正则抽全部 ### EVIDENCE:{json} 行
  ├─ 每条: 分配 canonical id(ev_NNN) + 翻译 depends_on(本地句柄->canonical)
  ├─ 戳 commit_sha = git rev-parse HEAD（项目 repo，worktree 内）
  └─ append 到 <项目>/.claude/evidence/<name>.jsonl（一行一节点）
        │
        ▼
<项目>/.claude/evidence/<name>.jsonl   ← 真源（tracked，全程提交进 wf/<name> 分支）
        │
   ┌────┴───── 后议 ─────────────┐
   ▼                            ▼
门控(§10占位)              审核(§10占位)
遍历 active 节点          git show <sha>:path:line
判证据闭合+依赖可溯        还原当时代码核验推导
```

### 三用途 -> 落地映射

| 用途 | 落地组件 | 状态 |
|---|---|---|
| 记录（脚本本体） | `evidence_append.py`(Stop hook) + `<name>.jsonl` | 本轮设计 |
| 防腐 | 节点 `commit_sha` + `status` 字段 | 本轮设计 |
| 门控执行完备 | 遍历器 + 判定规则 | **占位（§10，后议）** |
| 回溯审核 | `git show` 还原 + 推导核验 | **占位（§10，后议）** |

## 3. 节点 Schema（核心产物）

### 3.1 字段定义

| 字段 | 类型 | 语义 | 谁填 |
|---|---|---|---|
| `id` | string | canonical 标识 `ev_<NNN>`（文件内单调递增） | hook 分配 |
| `ts` | string | 追加时刻 ISO8601（本地+8h） | hook 戳 |
| `phase` | string | 所属阶段（understand/plan/execute/review/evolution），读 state.json 当前 phase | hook 戳 |
| `step` | int | 模型自报的步序（模型本地句柄序号，仅供人读） | 模型 |
| `claim` | string | 这一节点断言什么（"20=4×5"/"答案是500"/"改用B方案"） | 模型 |
| `claim_type` | enum | `premise`/`intermediate`/`conclusion` | 模型 |
| `depends_on` | string[] | 依赖的 canonical id 列表（推导前置） | 模型出句柄，hook 翻译 |
| `evidence` | object[] | 证据指针数组（见 3.2） | 模型 |
| `status` | enum | `active`/`superseded`（默认 active） | 模型可标；门控可改 |
| `commit_sha` | string | 追加时项目 repo 的 HEAD（防腐锚点） | hook 戳 |
| `superseded_by` | string? | 被哪个 id 取代（status=superseded 时填） | 模型或门控 |

### 3.2 evidence 证据指针

```json
{"kind":"file",      "ref":"src/x.py:42"}        // 代码位置（相对路径:行）
{"kind":"test",      "ref":"pytest tests/x.py::y PASSED"}  // 测试输出
{"kind":"codegraph", "ref":"callers:foo -> [bar,baz]"}      // codegraph 原始输出
{"kind":"reasoning", "ref":"乘法结合律 20=4×5, 4×25=100"}   // 纯推理（无外部锚点）
```

- `ref` 一律**相对/可移植**（禁绝对路径、禁本机 uuid）。
- `kind=reasoning` 是退路：当无外部锚点时（如数学推导），用纯文本记录推理本身。
- `kind=file` 的 `ref` 配合节点 `commit_sha` 还原：`git show <commit_sha>:<path>` 取当时文件。

### 3.3 完整示例（20×25 + 一次推翻）

```jsonl
{"id":"ev_001","ts":"2026-07-23T15:00:01","phase":"execute","step":1,"claim":"20 拆成 4×5","claim_type":"premise","depends_on":[],"evidence":[{"kind":"reasoning","ref":"因数分解 20=4×5"}],"status":"active","commit_sha":"abc1234"}
{"id":"ev_002","ts":"2026-07-23T15:00:02","phase":"execute","step":2,"claim":"4×25=100","claim_type":"intermediate","depends_on":["ev_001"],"evidence":[{"kind":"reasoning","ref":"乘法"}],"status":"active","commit_sha":"abc1234"}
{"id":"ev_003","ts":"2026-07-23T15:00:03","phase":"review","step":3,"claim":"答案是 500","claim_type":"conclusion","depends_on":["ev_002"],"evidence":[{"kind":"reasoning","ref":"5×100=500"}],"status":"superseded","commit_sha":"abc1234","superseded_by":"ev_004"}
{"id":"ev_004","ts":"2026-07-23T15:01:00","phase":"review","step":4,"claim":"改用先算 4×25=100 再 ×5=500","claim_type":"conclusion","depends_on":["ev_003"],"evidence":[{"kind":"reasoning","ref":"结合律更简"}],"status":"active","commit_sha":"def5678"}
```

`ev_004` 取代 `ev_003`：**不删 `ev_003`**，标 `superseded`+`superseded_by="ev_004"`，`ev_004.depends_on=["ev_003"]` 显式声明"我推翻了它"。-> 决策演进谱系，可回溯"推翻过什么、凭什么"。

## 4. 写入机制（标记 + hook）

### 4.1 模型侧：输出标记

模型在回复末尾（与 `### PHASE_DONE` 同位）输出，一行一节点：

```
### EVIDENCE:{"step":1,"claim":"20拆成4×5","claim_type":"premise","depends_on":[],"evidence":[{"kind":"reasoning","ref":"因数分解"}]}
### EVIDENCE:{"step":2,"claim":"4×25=100","claim_type":"intermediate","depends_on":["step1"],"evidence":[{"kind":"reasoning","ref":"乘法"}]}
```

- 模型用**本地句柄**做 `depends_on`（如 `"step1"`），**不预知** canonical id。
- 模型**不填** `id`/`ts`/`phase`/`commit_sha`/`status`/`superseded_by`（hook 负责）。
- 标记失败（JSON 解析失败）-> hook 跳过该节点并留痕（no silent fallback：记 `.wf_evidence.log`），不阻断。

**注入渠道（方案1，live smoke 后定稿）**：`workflow_phase.py` `_format_injection` 追加证据标记格式提示块（见 §9 step4），每轮注入告诉模型：
- 何时输出：推导出**结论/中间结论**时（claim_type=conclusion/intermediate），或确立**前提**时（claim_type=premise）。
- 格式：`### EVIDENCE:{json}` 一行一节点，depends_on 用本地句柄 `step<N>`。
- 语义：仅当该结论真正成立时输出（与 PHASE_DONE 同「仅当真正达成时输出」语义）；非结论性回复可不发。
- 不重复发：同一结论已被记录（canonical id 存在）后，跨轮引用直接用上轮 canonical id 作 depends_on。

### 4.2 hook 侧：`evidence_append.py`（Stop hook）

伪流程：

```
读 payload -> cwd -> 反查主 repo 根(workflow_advance.py 同法) + 工作流名(<name>)
读 state.json 拿当前 phase
读 transcript -> _last_assistant_text（复用范式）-> 抽全部 ### EVIDENCE:{...} 行
evidence_path = <repo>/.claude/evidence/<name>.jsonl
next_nnn = 现有文件行数 + 1（空文件从 ev_001 起）
建本地句柄 -> canonical id 映射表（step1 -> ev_001, step2 -> ev_002, ...）
对每条:
  翻译 depends_on 句柄 -> canonical id
  戳 ts/phase/commit_sha(=git rev-parse HEAD)/status=active
  append 一行到 evidence_path
留痕 .wf_evidence.log（n 条追加 / 失败原因）
exit 0（永不阻断，与 workflow_advance.py 一致）
```

- **两个 Stop hook 并存**：`workflow_advance.py`（推进阶段）+ `evidence_append.py`（追加证据），settings.json hooks 数组各一项，互不干扰。
- `commit_sha` 取 worktree 内 `git rev-parse HEAD`（项目 repo 当前 HEAD）。
  - **防腐语义**：保证 `git show <commit_sha>:<path>` 可还原当时代码快照，**不腐**。
  - **v1 简化**：SHA 锚"追加时的 HEAD"（含被述代码的某 commit），非"代码引入 commit"。事后回溯取得到即可，溯源引入 commit是增强项（§11 风险）。

## 5. 落点：`.claude/evidence/<name>.jsonl`

| 维度 | 取值 | 理由 |
|---|---|---|
| 路径 | `<项目>/.claude/evidence/<name>.jsonl` | §1 事实 2/3：worktree 可见、不被 `.gitignore` 吞、与 `.claude/hooks`+`skills` tracked 惯例一致 |
| 粒度 | per-workflow 一个文件 | §1 事实 8：多分支 append 同一文件 merge 冲突；分文件零冲突 |
| 形态 | JSONL（一行一节点） | 追加不读改写全文件（防 OOM，守 CLAUDE.md §3 禁全量 json.load）；半截写只丢一行可跳过；可流式审计 |
| 提交 | 每次 append 后随工作流 commit 进 `wf/<name>` 分支 | 用途②事后回溯要求跨期可取；合并进 master 后随 PR 走 |
| 删除 | 工作流终结**不删**（与 state.json/worktree 不同） | 它是持久物，非运行态；合并后留在 master 供回溯 |

**不落 `.claude/workflows/<name>/`**：虽聚拢，但 gitignored（§1 事实 1）+ worktree 不可见（§1 事实 2），物理走不通。

## 6. 防腐机制

两个机制叠加，解"分支迭代致旧结论失效"的保鲜问题：

### 6.1 commit_sha 绑定（解"实现指针失效"）

- 旧方案指针写 `src/x.py:42`（绑当前 HEAD）-> A 改 B 后行号变/文件没，指针腐。
- 新方案节点带 `commit_sha` -> `git show <sha>:src/x.py` 永远还原当时整文件，行号可还原。
- **git 快照不可变 = 防腐解药**，前提是指针锚历史 commit 而非当前 HEAD。

### 6.2 status 演进（解"结论被推翻"）

- A 被 B 取代：**不删 A**，标 `status=superseded` + `superseded_by=<B_id>`，B 的 `depends_on` 引用 A。
- 形成决策演进谱系：每次推翻有迹可循（科学方法精神：可证伪 + 记录推翻）。
- 门控只查 `status=active` 节点完备性；superseded 节点免查（已被取代）。

## 7. 文件清单（实现，按 H9 分小 commit）

```
~/.dl-workflow/designs/evidence-chain-design.md   本设计文档(H8)          [本 commit]
~/.dl-workflow/hooks/evidence_append.py           新：Stop hook 追加证据    [commit 2]
~/.dl-workflow/scripts/workflow/dl-lib.sh         改：wf_write_settings 注册新 hook  [commit 3]
~/.dl-workflow/scripts/workflow/dl-launch.sh      可能改：建 .claude/evidence/ 目录占位  [commit 3 或并入]
<项目>/.gitignore                                  可能改：确认 .claude/evidence/ 不被忽略(tracked)  [commit 4，项目侧]
<项目>/.claude/evidence/<name>.jsonl              运行态真源(tracked)       [运行期生成]
```

## 8. 与项目铁律的关系

- **H8**（2+文件先 design.md）：本设计即 design，先落本文档。实现跨多文件（hook + dl-lib.sh + 项目 gitignore），须先有本文档。
- **H9**（单次 ≤3 文件 AND ≤200 行）：分 commit 增量实现（§7）。本 commit 仅 design.md 一文件。
- **H11**（日志 `%` 惰性格式化，禁 f-string / `exc_info=True`）：`evidence_append.py` 留痕日志守此。
- **H12**（退出码语义，main 内禁 sys.exit）：hook 统一 `return 0`，exit 0 only（与现有两 hook 一致，永不阻断）。
- **H15**（codegraph 门禁）：`evidence_append.py` 是**新建 .py**（gate 白名单跳过新建）；改 `dl-lib.sh` 非 .py 跳过。若后续改已有 .py 则先 `codegraph impact`。
- **no silent fallback**：标记解析失败 / transcript 缺失 / 文件写失败 -> 留痕 `.wf_evidence.log` + exit 0（不阻断工作流，但留证据可查）。与 `workflow_advance.py` 防御式降级一致。
- **Read before write / verify before claiming done**：实现后须真实跑 `dl demo` 验证追加落地，附 `.wf_evidence.log` + 文件内容证据。

## 9. 实施步骤（分小 commit）

1. ✅ `evidence-chain-design.md`（本文档，H8 产物）。
2. ✅ `evidence_append.py`（Stop hook：解析标记 + 分配 id + 戳 SHA + append）+ 22 例单测（真 git worktree 端到端）。
3. ✅ `dl-lib.sh` `wf_write_settings` 注册 evidence_append.py 为第二个 Stop hook。冒烟：source dl-lib.sh 生成 settings.json 验 Stop hooks=2 且顺序正确（advance 先 evidence 后）。
4. ✅ **live smoke 排查（2026-07-23）+ 证据注入修复（方案1）**：
   - **第一次排查**（误判）：`.wf_evidence.log` 两次 `no_markers`（17:21 `tlen=0`、17:23 `tlen=360`），初判"模型从未输出标记、无注入渠道"。**误判点**：transcript 在错误目录找（worktree 会话的 transcript 落在独立项目目录 `~/.claude/projects/-...-worktrees-demo/`，非主项目目录）。
   - **注入修复（方案1，已落地 commit ad70772）**：扩展 `workflow_phase.py` `_format_injection` 追加证据标记格式提示块。复用 UserPromptSubmit 注入通道，5 阶段均注入。
   - **第二次排查（`ac-ark --dl demo` 真工作流会话，确认正确）**：demo 当前 session `4f5eb724` transcript 在 `...worktrees-demo/`，19 条 assistant 消息。注入提示**已生效**（transcript 第 8 行 attachment 可见证据格式块）。模型在 understand 子阶段 1 讨论工作流元问题，按"非结论性回复可不发"语义**合规地未输出** `### EVIDENCE` -> `.wf_evidence.log` 第三次 `no_markers`（17:31 `tlen=42`）正确。`grep "### EVIDENCE"` 命中 1 处，但那是 hook 注入的 attachment 文本，非模型 assistant 回复。
   - **结论**：记录骨架全链路验证通过（hook 触发 / 注入生效 / `_last_assistant_text` 解析正确 / Stop hooks 注册正确）。未见 evidence 落地，因 demo 未走到"推导结论"的轮次，非系统故障。要见节点须让工作流走到有具体结论的轮次（execute 实现/review 判定）。
4b. ✅ **`_last_assistant_text` 轮次边界修复（commit 5b7bf01）**：
   - **隐患（live smoke 推演发现，非实测触发）**：旧实现取「全局最后一条 assistant 文本」。一条 user 回合后模型可能发多条 assistant 消息（工具调用中断续文本），若标记在较早 assistant 消息、末条无标记 -> 漏证据。
   - **修复**：`_last_assistant_text_io(stream)` 改扫「当前轮」= 最后一条 user 之后所有 assistant 文本（拼接）。user 出现即重置（不采上一轮，避免重复追加已落库旧标记）；无 user 不重置 -> 全算当前轮。抽出 `_assistant_text_of(msg)` + `_last_assistant_text_io(stream)` 纯函数（可传 StringIO 单测）。
   - **未改 `workflow_advance.py._last_assistant_text`**：它只检测 `### PHASE_DONE` 单标记且必在末尾，不受此隐患影响。
   - 测试 +3；全量 42 passed；ruff clean。
5. ⏳（后议）门控遍历器。
6. ⏳（后议）审核还原器。

## 10. 门控与审核（占位 - 后议）

> 本轮只搭记录骨架 + 防腐。以下机制留接口，待后续讨论定稿。

### 10.1 门控（执行完备检查）- 占位

- **触发时机**：候选 = execute->review 推进前 / `/dl gate` 放行时 / 手动 `/evidence check`。
- **判定规则**（草稿，待定）：
  - 每个 `status=active` 的 `claim_type=conclusion` 节点须有 ≥1 条非 reasoning 证据？（或允许纯 reasoning？）
  - `depends_on` 引用的 id 须存在且非 superseded？（superseded 链如何处理待定）
  - DAG 无环？
- **失败行为**：阻断推进？还是仅警告留痕？待定。

### 10.2 审核（结论回溯）- 占位

- **输入**：某 canonical id。
- **动作**：`git show <commit_sha>:<path>` 还原当时代码 -> 核验"claim ← depends_on + evidence"推导是否成立。
- **输出**：solved/partial/not + 证据（file:line / 测试输出 / codegraph 输出）。
- 与 review 阶段 `review.md`（`workflow_phase.py:63`）的关系待定（证据链是否驱动 review.md 生成）。

## 11. 风险与待验证（实现时处理）

| # | 风险 | 缓解 |
|---|---|---|
| 1 | 模型不按 schema 发标记 / JSON 格式错 | hook 容错跳过 + 留痕；注入 hook（phase-rules）可补"证据标记格式"提示 |
| 2 | `commit_sha` 取追加时 HEAD，非代码引入 commit | v1 接受（防腐语义=可还原快照，已满足）；溯源引入 commit 列增强项 |
| 3 | 本地句柄 -> canonical id 翻译在跨轮引用时，句柄名碰撞 | 句柄用模型自报 step 序号（`step1`），hook 维护本轮句柄表；跨轮引用建议直接用上轮 canonical id（注入 hook 可回灌已知 id）-> 待实现验证 |
| 4 | evidence.jsonl 进 `wf/<name>` 分支，工作流未合并即删 worktree 会丢证据 | evidence 在 `<项目>/.claude/`（非 worktree 内），worktree 删不影响；但 `wf/<name>` 分支未 merge 即删分支会丢 -> 约定：终结前先 merge 或显式归档（§5 已注不删） |
| 5 | 两个 Stop hook 执行顺序 / 互相读 state 竞态 | evidence_append.py 只读 state（取 phase）+ 只写 evidence.jsonl；workflow_advance.py 只读写 state.json。写不同文件 -> 无竞态。顺序无依赖 |
| 6 | `.claude/evidence/` 目录在 worktree 内不存在（首次 append） | hook `mkdir -p`（父母录，仿 `.wf_*.log` 写法） |
| 7 | worktree 会话 transcript 落在独立项目目录 `~/.claude/projects/-...-worktrees-<name>/`，非主项目目录 | 排查时勿在主项目目录找 transcript（live smoke 第一次排查误判即此）；hook 由 Claude 传 `transcript_path`，路径正确无需自找 |
| 8 | `_last_assistant_text` 取最后一条会漏同轮较早 assistant 消息的标记 | 已修（§9 step4b）：扫当前轮全 assistant 文本 |

## 12. 待用户确认项

- [ ] §5 落点 `.claude/evidence/<name>.jsonl`（本轮对话已默认采用，待最终确认）。
- [ ] §10 门控触发时机 + 判定严格度（后议）。
- [ ] §10 审核与 review.md 关系（后议）。
