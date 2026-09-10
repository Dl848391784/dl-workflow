# plan 完备性（执行零求证）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** plan 产物达到「执行零求证」——interface 字段从「精确签名」升级为「签名+数据契约」，机械校验当场拒无契约的数据消费条目，judge 判据与取证产出对齐。

**Architecture:** 单一概念「数据契约」四处对齐：生产文案（plan:2 子3 purpose）→ 机械校验（dl_flow_trace statements 校验区新增 helper）→ judge 判据（plan:2 子3 rubric）→ 取证产出（u:1#4 purpose）。验证 = 静态回测（v1_text 实案）+ ac-deepseek1 实跑 fermate 测试工作流。

**Tech Stack:** Python（dl_flow_trace/dl_flow_checks/dl_flow_nodes）、pytest。

## Global Constraints

- **弱模型优先**：判据钉死非裁量——信号词/契约词清单即判据，禁「视情况」
- **误拦成本 > 漏拦成本**：豁免声明「纯代码接口」随时可写；契约词命中 ≥2 即过（judge-framing 教训=默认-PASS 方框）
- **不追溯历史实例**：旧 plan.md 不合格式不补
- **claude 轨道零行为变化**：仅文案+新增校验分支，无既有逻辑改动
- 禁 `git add -A`；commit message 结尾 `Co-Authored-By: Claude <noreply@anthropic.com>`；H9 单 commit ≤3 文件 ≤200 行

---

### Task 1: 机械校验 `_check_interface_data_contract`

**Files:**
- Modify: `dl_flow_checks.py`（新增 helper，放在 fields 相关校验区 ~1593 附近）
- Modify: `dl_flow_trace.py`（statements 校验区 missing_f 之后接线，~755-775）
- Test: `tests/test_dl_flow_trace.py`（若无此文件则改 tests/test_dl_flow_engine.py 内同构区——先 `ls tests/ | grep trace` 核对）

**Interfaces:**
- Produces: `_check_interface_data_contract(interface_text: str) -> str | None`——无契约违例返 None，违例返拒绝文案

- [ ] **Step 1: 写失败测试**

```python
class TestInterfaceDataContract:
    """plan 完备性：interface 数据消费条目必须带数据契约（执行零求证）。"""

    def test_signal_without_contract_rejected(self):
        from dl_flow_checks import _check_interface_data_contract

        msg = _check_interface_data_contract(
            "Consumes：仓内数据层 fetch_market_cap.py:19-21 的 circ_market_cap 列"
        )
        assert msg is not None and "数据契约" in msg

    def test_signal_with_contract_passes(self):
        from dl_flow_checks import _check_interface_data_contract

        assert _check_interface_data_contract(
            "Consumes：MARKET_CAP_DATA（json.gz，结构 {meta, data:[records]}，"
            "circ_market_cap 单位=元需÷1e8；记录按日期升序，末次命中=最新；"
            "读不到/标的缺→None（失败语义）；读取先例=fetch_market_cap.py:19-21）"
        ) is None

    def test_exemption_declaration_passes(self):
        from dl_flow_checks import _check_interface_data_contract

        assert _check_interface_data_contract(
            "Consumes：步骤1 Produces ScreenerConfig.validate() -> None（纯代码接口）"
        ) is None

    def test_pure_signature_without_signal_passes(self):
        from dl_flow_checks import _check_interface_data_contract

        assert _check_interface_data_contract(
            "Consumes：步骤1 Produces ScreenerConfig（dataclass）；Produces：screen(cfg, symbol) -> dict"
        ) is None
```

- [ ] **Step 2: 跑确认失败**

Run: `cd ~/projects/dl-workflow-wt/plan-completeness && python3 -m pytest tests/ -q -k InterfaceDataContract`
Expected: FAIL（`_check_interface_data_contract` 不存在 ImportError）

- [ ] **Step 3: 实现**

`dl_flow_checks.py`（fields 校验区附近追加）：

```python
# plan-completeness（执行零求证）：interface 数据契约词表（判据钉死非裁量）。
# 误拦成本>漏拦成本——契约词 ≥2 即过；「纯代码接口」豁免声明随时可写。
_CONTRACT_SIGNAL_WORDS = (
    "读", "数据", "json", "parquet", "gzip", "DataFrame", "API", "缓存", "文件", "源码",
)
_CONTRACT_KEYWORDS = ("单位", "格式", "结构", "失败语义", "示例", "先例")


def _check_interface_data_contract(interface_text: str) -> str | None:
    """interface 字段数据契约半机械校验（plan-completeness 设计 §2②）。

    数据消费信号词命中 → 须同时含 ≥2 个契约词或「纯代码接口」豁免声明；
    无信号（纯签名）→ 放行。违例返拒绝文案，合规返 None。
    """
    if "纯代码接口" in interface_text:
        return None
    if not any(w in interface_text for w in _CONTRACT_SIGNAL_WORDS):
        return None
    hits = sum(1 for w in _CONTRACT_KEYWORDS if w in interface_text)
    if hits >= 2:
        return None
    return (
        f"interface 含数据消费条目但数据契约不足（契约词命中 {hits}/2，"
        "需「单位/格式/结构/失败语义/示例/先例」中 ≥2 个）——执行零求证标准："
        "消费数据/文件/API 时必给五要素（格式样本/单位换算/时序语义/失败语义/"
        "读取先例），纯函数接口请显式声明「纯代码接口」豁免"
    )
```

`dl_flow_trace.py`（missing_f 校验通过后、同循环内追加）：

```python
                if "interface" in req_fields:
                    contract_msg = _check_interface_data_contract(str(flds.get("interface", "")))
                    if contract_msg is not None:
                        return False, f"statements[{i}].fields.interface：{contract_msg}"
```

（`_check_interface_data_contract` 的 import 照该文件既有 dl_flow_checks import 区补名）

- [ ] **Step 4: 跑测试 + 相关回归**

Run: `python3 -m pytest tests/ -q -k "InterfaceDataContract or statement" 2>&1 | tail -2`
Expected: 新 4 条 PASS + 相关全过

- [ ] **Step 5: Commit**

```bash
git add dl_flow_checks.py dl_flow_trace.py tests/
git commit -m "feat(checks): interface 数据契约半机械校验——数据消费信号命中须 ≥2 契约词或豁免声明（执行零求证，T1）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: plan:2 子3 purpose + gate rubric 文案

**Files:**
- Modify: `dl_flow_nodes.py`（子3 purpose ~3654 interface 定义 + 子3 gate rubric ~3787 判据区）

**Interfaces:**
- Consumes: T1 的机械校验词表口径（文案必须与 `_CONTRACT_SIGNAL_WORDS/_CONTRACT_KEYWORDS` 同口径引用，禁散写新词表）

- [ ] **Step 1: purpose 的 interface 定义替换**

原文：`"前置接口（Consumes+Produces 精确签名）/验证方法"` →

```python
                    "前置接口（Consumes+Produces 精确签名+数据契约——"
                    "执行零求证：步骤消费数据/文件/API/缓存时必给五要素"
                    "（格式样本=文件结构/记录示例、单位与换算、时序语义=排序/"
                    "最新值取法、失败语义=None 还是异常/缺记录形态、读取先例"
                    "file:line），纯函数接口显式声明「纯代码接口」豁免；"
                    "append-trace 机械校验数据消费信号命中须 ≥2 契约词或豁免）/"
                    "验证方法"
```

- [ ] **Step 2: gate rubric 判据区补条款 + 判材边界**

判据区（三/四 条款之后）追加：

```python
                    "五、interface 数据契约与材料不符：interface 的数据契约"
                    "（格式/单位/时序/失败语义）与子3 锚点核验留痕的事实矛盾"
                    "（如单位写错、结构写错、失败语义与源实现不符）判 block——"
                    "机械校验只查要素存在性，内容准确性归本判。"
                    "合法形态=契约与子3 留痕一致即合规。\n"
```

判材边界段追加：

```python
                    "interface 豁免形态已由 append-trace 机械校验，不得以"
                    "「签名不够详细/契约行文格式不合我意」为由 block；"
                    "不得以「契约五要素缺某要素」为由 block（存在性机械已判，"
                    "本判只管与材料矛盾）。\n"
```

- [ ] **Step 3: 验证**

Run: `python3 -c "import dl_flow_nodes; print('nodes ok')"` + `python3 -m pytest tests/ -q -k "plan2 or Plan2 or task_breakdown" 2>&1 | tail -1`
Expected: ok + 相关全过（文案类改动应有镜像重放纪律——见 Step 4）

- [ ] **Step 4: 镜像重放（build-and-modify §1.6 纪律）**

取一个已有 fermate 实例的 plan:2#3 trace 做镜像重放（陈述镜像），确认新 purpose 下产出形态变化方向正确（interface 带数据契约）。若无法立即重放，留证「重放待 T4 实跑覆盖」并在 T4 一并验。

- [ ] **Step 5: Commit**

```bash
git add dl_flow_nodes.py
git commit -m "feat(nodes): plan:2 子3 interface 升级签名+数据契约五要素+豁免，gate 补材料不符判据与默认-PASS 边界（T2）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: u:1#4 取证产出升级「可消费锚点」

**Files:**
- Modify: `dl_flow_nodes.py`（understand:1 子4 purpose 数据供给面/先例条目标准）

- [ ] **Step 1: purpose 文案增补**

在子4 purpose 的供给面/先例条目要求处（先 `grep -n "供给面\|先例" dl_flow_nodes.py | head` 定位原子B/取证相关段）追加：

```python
                    "可消费锚点标准（plan 完备性）：凡标注「供给面/先例」的条目"
                    "必须带读取形态——结构（文件格式/记录示例）、单位与换算、"
                    "失败语义（None 还是异常）、读取先例行号；只给「存在性锚点」"
                    "（xxx.py:N 有一列）=欠细，plan:1/2 消费时会被迫再实读。"
```

- [ ] **Step 2: 验证 + Commit**

Run: `python3 -c "import dl_flow_nodes; print('ok')"`
```bash
git add dl_flow_nodes.py
git commit -m "feat(nodes): u:1#4 取证产出升级可消费锚点——供给面/先例条目必带读取形态（结构/单位/失败语义/先例行号，T3）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 静态回测 + ac-deepseek1 实跑验证 + 迭代

**Files:** 无源码改动（验证任务）；结果回填 `designs/plan-completeness-design.md` §3

- [ ] **Step 1: 静态回测（v1_text 实案）**

用 T1 的校验函数判读 v1_text plan.md 步骤2 的 interface 条目（当时缺契约的市值数据条目）：

```bash
cd ~/projects/dl-workflow-wt/plan-completeness && python3 - <<'EOF'
import sys, json
sys.path.insert(0, ".")
from dl_flow_checks import _check_interface_data_contract
# v1_text plan 步骤2 interface 原文（缺契约形态）
old = ("Consumes：步骤1 Produces ScreenerConfig 与 ScreenerConfig.validate()；"
       "仓内数据层签名 data_fetchers.data_loader.RealDataLoader.get_stock_history(...) "
       "-> DataFrame[date/open/high/low/close/volume/asset]（data_loader.py:206，L198-228）"
       "+ fetch_turnover 输出 turnover_rate_data.json.gz + fetch_market_cap 输出列 circ_market_cap "
       "+ fetch_tail_trading 尾盘5分钟K线 + fetch_industry 申万行业分类缓存")
print("旧形态判定（应=拒）:", bool(_check_interface_data_contract(old)))
EOF
```

预期：旧形态被拒（证明校验有牙，若放行则词表要调）。

- [ ] **Step 2: ac-deepseek1 实跑测试工作流**

```bash
cd /home/admin/projects/factor_ic_analyzer && ac-deepseek1 && dl plantest-zero-context
# 陈述（需读仓内数据的小任务）：
# 「给 early_summer_screener 加一个 --batch 参数：读 stock_list 全部标的逐个跑 screen() 输出汇总表」
```

- [ ] **Step 3: 收割判读**

- 等跑到 fermate 完结（plan:2 gate=done）
- 读 `.claude/plans/plantest-zero-context.md` 的 interface 条目：数据消费条目必须带数据契约五要素形态
- **达标判据**：每个含数据消费的 interface 条目都有格式样本/单位/时序/失败语义/读取先例要素，且无需打开其他文件即可施工
- 不达标 → 分析判词/产出差在哪（purpose 没传导？judge 放过？机械校验没咬到？）→ 迭代文案回 Step 2 重跑（新一轮实例）

- [ ] **Step 4: 验收回填 + commit**

Step 1-3 结果回填 `designs/plan-completeness-design.md` §3（逐项 ✅/❌+证据指针）：

```bash
git add designs/plan-completeness-design.md
git commit -m "docs(designs): 验收回填——静态回测+deepseek 实跑 plan 完备性判读（T4）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review 记录

- **Spec 覆盖**：设计 4 改动点 ↔ T1(②)/T2(①③)/T3(④)/T4(验证 §3 全三项)
- **Placeholder 扫描**：T3 Step 1 的定位指令为「先 grep 核对」型（行号漂移），非内容空缺；T4 Step 3 迭代循环是 goal 指定的验证路径
- **类型一致性**：`_check_interface_data_contract(str) -> str | None` T1 定义与接线/回测消费一致；词表单一来源（T1 定义，T2 文案引用不复制新表）
