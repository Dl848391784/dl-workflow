# plan-first 拆步 实现计划（understand:1 子2 → 子2a 规划 + 子2b 执行）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended). Steps use checkbox (`- [ ]`) syntax.
> 设计真源：`designs/understand1-sub2-plan-first-split-design.md`（拆分方案/judge 拆分/返工回路/编号策略已定）。

**Goal:** 把 understand:1 子2（causal-inference）拆成 子2a 规划（MECE+tier）+ 子2b 执行（因果链），全重编号 2..7，分离"规划思考"与"执行搜索"。

**Architecture:** 子2 的 `Step` 对象一拆二；子3-子6 顺延为子4-子7。子2a gate 判 MECE+tier，子2b gate 判因果链证据。返工回路=A（子2b 就地补+留痕）。

**Tech Stack:** Python 3、pytest。

## Global Constraints

- 真源 `~/.dl-workflow/`；H9 ≤3 文件 ≤200 行（大改拆多 commit）。
- `sub_step_index` 是 int → 全重编号 2..7（非 2a/2b 后缀）。
- 改动波及：node-rules 渲染（自动跟）、`references/node-design.md` 摘要块（手工同步）、segment chain 白名单、`last_judged_trace` key、append-trace `sub_step`、state-reset 寻址、注入文案。
- 子2 现有 gate 是默认-PASS framing（§3.5 #28），拆分后 2a/2b 两 gate 都必须保留「默认 pass」字面。
- 子2 的 `deny_readonly=("grep","rg")` 保留（子2b 继承；子2a 规划无搜索，可留空）。

---

### Task 1: 拆 Step 对象（子2 → 子2a/子2b，全重编号）

**Files:**
- Modify: `dl_flow_nodes.py`（understand:1 Node 的 sub_steps）

**Interfaces:**
- 子2a = Step(ref="causal-inference-root-cause", short="规划拆解", 职责 MECE+tier → atomic_questions)
- 子2b = Step(ref="causal-inference-root-cause", short="因果链挖掘", 职责 5-Whys+证据 → 因果链, input="step2.atomic_questions", deny_readonly=("grep","rg"))
- 子3/4/5/6 顺延为 4/5/6/7（Step 内容不变，仅位置后移）

- [ ] **Step 1: 定位 understand:1 Node 的 sub_steps（dl_flow_nodes.py ~695-940），确认 6 个 Step 边界**
- [ ] **Step 2: 把子2 Step（ref="causal-inference-root-cause"）一拆二**：

子2a（规划）：
```python
Step(
    kind="skill",
    ref="causal-inference-root-cause",
    short="规划拆解",
    purpose=(
        "拆解深挖·规划：①单一/复合判定——复合痛点按 MECE 拆原子问题清单"
        "（互不重叠、合起来覆盖全部痛点；单一则声明「无复合」理由）；"
        "②每个原子问题定取证深度档——" f"{_FETCH_TIER_RULE}。"
        "本步**只规划不挖链**——因果链挖掘是子2b 的活。"
        "原子问题清单连档作为载荷顶层 atomic_questions 键提交"
        "（逐项 {'q':<原子问题>, 'tier':'none|light|full', 'tier_reason':<分档理由>}，"
        "与 MECE 一一对应——append-trace 机械校验 tier 枚举/理由非空/"
        "none 档仓内路径/首字母标签对齐）。"
        "输出走 evidence skill-trace，不建单独 md。"
        f"{_CODE_ARCH_ROUTE}"
    ),
    input="step1.real_problem",
    record=True,
    selfcheck=(...MECE + tier 自查，从原子2 selfcheck 抽出前半...),
    gate=(...MECE+tier 判据，从原子2 gate 抽出⑤档部分...),
    extra_payload_keys=(("atomic_questions", "fetch_tier_items"), ("atomic_questions", "atomic_mece_alignment")),
),
```

子2b（执行）：
```python
Step(
    kind="skill",
    ref="causal-inference-root-cause",
    short="因果链挖掘",
    purpose=(
        "拆解深挖·执行：按子2a 的 atomic_questions 逐原子挖因果链到根因"
        "（invoke causal-inference-root-cause，5 Whys/鱼骨/时序），"
        "每环实际证据指针——" f"{_CAUSAL_CHAIN_EVIDENCE_RULE}；"
        "每问题 ≥1 竞争假设+排除/保留理由；近因/根因+置信度。"
        "**按 2a 的档执行，不重定档**（发现 2a 漏原子/档错→就地补并在 trace "
        "标「执行期补规划」+原因，留痕即可，不回退 2a）。"
        "输出走 evidence skill-trace。"
    ),
    input="step2.atomic_questions",
    record=True,
    selfcheck=(...因果链自查，从原子2 selfcheck 抽后半...),
    gate=(...因果链判据，从原子2 gate 抽出链/竞争假设/近因根因部分...),
    mech_checks=("causal_ring_no_untested", "hypothesis_exclude_no_absence"),
    deny_readonly=("grep", "rg"),
),
```

- [ ] **Step 3: 子3/4/5/6 顺延为 4/5/6/7**（Step 内容不动，仅 `input` 引用若有 `step2.` 前缀改成 `step2b.`）

- [ ] **Step 4: 冒烟**：`python3 -c "import dl_flow_engine as e; n=e.get_node('understand',1); print([s.short for s in n.sub_steps])"` → 应输出 7 个 short，含「规划拆解」「因果链挖掘」

- [ ] **Step 5: commit**

---

### Task 2: 波及面修复 + 测试

**Files:**
- Modify: `dl_flow_engine.py`（segment chain 白名单如有 子2-子5 引用）、`references/node-design.md`（摘要块）、相关测试

**Interfaces:** 全重编号后，凡硬编码 `sub_step==2` / `sub_step_index=2` / `understand:1#2` 的引用需顺延。

- [ ] **Step 1: grep 全仓 `understand:1#2` / `sub_step==2` / `ProblemContext 子2` 等引用，列出影响面**
- [ ] **Step 2: 逐项修**（segment chain 白名单、node-design.md 摘要、测试 pin、注入文案「子步骤 2」）
- [ ] **Step 3: 全量测试**：`pytest -q` 全绿（失败的 pin 测试按新编号改钉，不删校验）
- [ ] **Step 4: 真实载荷重放**：用现有 amplitude_annualized 子2 的 block/pass 载荷，验证 2a/2b 两 gate 判据不漂移（子2a 判 MECE+tier、子2b 判因果链）
- [ ] **Step 5: commit**

---

## Self-Review

- 设计 doc 的拆分方案/judge 拆分/返工回路/编号策略已逐条落到 Task 1/2。
- **遗留待实施确认**：子2 gate 的 MECE+tier 部分 vs 因果链部分如何精确切分（原 gate 是单一默认-PASS 方框，切两半要保持各自牙齿）；`input="step2.atomic_questions"` 的引用语法（engine 的 input 解析是否支持 `step2a.`）。
