# per-instance 引擎选择实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 引擎从 server 进程级升级为实例级——`state.json` sticky `engine` 字段 + dashboard 创建表单卡片式引擎选择（默认 claude，按机器已装引擎渲染卡片），全链（drive/judge/inject/resume）跟随实例与 server env 解耦。

**Architecture:** 读取链 = state 优先、env 兜底（旧实例无字段一律 claude）。dl_drive main 启动早期把 `state.engine` 归一写回 `os.environ["DL_ENGINE"]`（单实例进程，下游 get_engine()/hooks 自动跟随）；dashboard（多实例进程）用 `get_engine(override)` 参数直传，禁 env 竞态。前端复用 `.mode-card` 卡片交互（禁下拉）。

**Tech Stack:** Python（dl_engine/dl_drive/dl_dashboard）、bash（dl-lib/dl-launch）、vanilla JS（dashboard static）。

## Global Constraints

- **claude 默认零行为变化**：`state.get("engine", "claude")` 兜底；DL_ENGINE env 语义不变（显式 env/override 优先于 state 默认）
- **no silent fallback**：`get_engine` 未知 override/env 值显式 SystemExit；/api/create 未知 engine 400 式拒绝
- **H9**：单 commit ≤3 文件 AND ≤200 行；禁 `git add -A`；commit message 结尾 `Co-Authored-By: Claude <noreply@anthropic.com>`
- **禁下拉**：引擎选择复用 `.mode-cards`/`.mode-card.sel` 卡片交互（同 scope-cards）
- **qoder 模型不进表单**（YAGNI，设计 §4）
- **worktree**：`~/projects/dl-workflow-wt/per-instance-engine`（分支 feat/per-instance-engine）

---

### Task 1: `available_engines()` + `get_engine(override)`

**Files:**
- Modify: `dl_engine.py`
- Test: `tests/test_dl_engine.py`

**Interfaces:**
- Produces（后续任务依赖）:
  - `dl_engine.available_engines() -> list[str]`——`shutil.which` 探测，claude 在前；一个都探不到返回 `[]`（dashboard 表单按列表渲染）
  - `dl_engine.get_engine(override: str | None = None) -> EngineProfile`——优先级 **override > DL_ENGINE env > claude**；override/env 未知值均 SystemExit

- [ ] **Step 1: 写失败测试**（追加到 tests/test_dl_engine.py）

```python
class TestAvailableEngines:
    def test_both_present(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda b: f"/usr/bin/{b}")
        assert dl_engine.available_engines() == ["claude", "qodercli"]

    def test_only_qoder(self, monkeypatch):
        monkeypatch.setattr(
            "shutil.which", lambda b: "/usr/bin/qodercli" if b == "qodercli" else None
        )
        assert dl_engine.available_engines() == ["qodercli"]

    def test_none_present(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda b: None)
        assert dl_engine.available_engines() == []


class TestGetEngineOverride:
    def test_override_beats_env(self, monkeypatch):
        monkeypatch.setenv("DL_ENGINE", "claude")
        assert dl_engine.get_engine("qodercli").binary == "qodercli"

    def test_none_override_falls_back_to_env(self, monkeypatch):
        monkeypatch.setenv("DL_ENGINE", "qodercli")
        assert dl_engine.get_engine(None).binary == "qodercli"
        assert dl_engine.get_engine("").binary == "qodercli"  # 空串=未指定

    def test_unknown_override_hard_fails(self):
        import pytest

        with pytest.raises(SystemExit):
            dl_engine.get_engine("gemini")
```

- [ ] **Step 2: 跑确认失败**

Run: `cd ~/projects/dl-workflow-wt/per-instance-engine && python3 -m pytest tests/test_dl_engine.py -q`
Expected: FAIL（`available_engines` 不存在 / `get_engine()` 不收 override）

- [ ] **Step 3: 实现**

`dl_engine.py` 的 `get_engine` 改为：

```python
def get_engine(override: str | None = None) -> EngineProfile:
    """当前引擎 profile。优先级：override（per-instance state）> DL_ENGINE env > claude。

    未知值硬失败（no silent fallback）。空串 override/env = 未指定。
    """
    name = (override or os.environ.get("DL_ENGINE", "")).strip() or "claude"
    profile = _PROFILES.get(name)
    if profile is None:
        print(
            f"✗ 引擎={name!r} 未知（可选：{sorted(_PROFILES)}）"
            "——拒绝静默回退（no silent fallback）",
            file=sys.stderr,
        )
        sys.exit(2)
    return profile


def available_engines() -> list[str]:
    """机器上可用引擎列表（dashboard 表单选项数据源）。顺序=默认优先级（claude 在前）。

    一个都探不到返回 []——调用方（表单）按列表渲染，空列表=不渲染引擎卡片。
    """
    import shutil

    return [name for name, p in _PROFILES.items() if shutil.which(p.binary)]
```

- [ ] **Step 4: 跑测试 + 全量回归**

Run: `python3 -m pytest tests/test_dl_engine.py -q && python3 -m pytest tests/ -q 2>&1 | tail -1`
Expected: 新 7 条 PASS；全量无回归

- [ ] **Step 5: Commit**

```bash
git add dl_engine.py tests/test_dl_engine.py
git commit -m "feat(engine): available_engines 探测+get_engine(override)——per-instance 引擎读取地基（override>env>claude，T1）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: state 落引擎 + dl-launch resume sticky

**Files:**
- Modify: `scripts/workflow/dl-lib.sh`（`wf_state_init` ~127-146）
- Modify: `scripts/workflow/dl-launch.sh`（引擎 case 块 + wf_state_init 调用点）
- Test: `tests/test_dl_launch_engine.sh`（追加）

**Interfaces:**
- Consumes: 无
- Produces: `state.json` 含 `engine` 字段（T3/T4/T5 读侧契约 = `state.get("engine", "claude")`）；`wf_state_init <name> <sid> <base> <branch> <wtp> <engine>`（6 参）

- [ ] **Step 1: 写失败测试**（追加到 tests/test_dl_launch_engine.sh）

```bash
# --- per-instance engine：state 落引擎 + resume sticky ---
SEG="$WF_META_ROOT/sticky/state.json"
mkdir -p "$WF_META_ROOT/sticky"
cat > "$SEG" <<'JSON'
{"name": "sticky", "engine": "qodercli"}
JSON
# wf_state_init 落引擎字段（6 参形态）
wf_state_init falltest sid-1 master wf/falltest /tmp/wt qodercli
python3 -c "
import json
s = json.load(open('$WF_META_ROOT/falltest/state.json'))
assert s['engine'] == 'qodercli', s.get('engine')
print('✓ wf_state_init 落 engine 字段')
"
# resume sticky：DL_ENGINE 未设时从 state 读（stub wf_state_get 模拟）
DL_ENGINE=""
eval "$(sed -n '/^# ---------- 引擎/,/^esac/p' "$LAUNCH" | sed 's/exit 1/return 1/')"
[ "$DL_ENGINE" = "qodercli" ] || { echo "✗ resume sticky 未读到 state engine: $DL_ENGINE"; exit 1; }
echo "✓ resume sticky：无 env 时 state.engine 生效"
```

> ⚠️ 测试里 `wf_state_get` 在 dl-lib.sh source 后真实可用；sticky 用例的 state.json 路径用 `$WF_META_ROOT/sticky/state.json`（wf_state_get 按 `<root>/<name>/state.json` 定位，name=sticky 匹配）。

- [ ] **Step 2: 跑确认失败**

Run: `bash tests/test_dl_launch_engine.sh`
Expected: FAIL（wf_state_init 只吃 5 参 / 引擎块无 sticky 逻辑，`DL_ENGINE` 解析成 claude）

- [ ] **Step 3: 改两处**

`dl-lib.sh` `wf_state_init`：

```bash
wf_state_init() {
  # $1=name $2=session_id $3=base_ref $4=branch $5=worktree_path $6=engine
  local name="$1" sid="$2" base="$3" branch="$4" wtp="$5" engine="${6:-claude}"
  mkdir -p "$WF_META_ROOT/$name"
  python3 - "$WF_META_ROOT/$name/state.json" "$name" "$sid" "$base" "$branch" "$wtp" "$engine" <<'PY'
import json, sys
path, name, sid, base, branch, wtp, engine = sys.argv[1:8]
import time
now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
state = {
  "name": name, "phase": "understand", "index": 1,
  "sub_index": 1, "sub_total": 4,
  "session_id": sid, "base_ref": base, "branch": branch, "worktree_path": wtp,
  "engine": engine,  # per-instance-engine：实例引擎 sticky（读侧一律 .get("engine","claude") 兜底）
  "gate": "pending", "created_at": now, "updated_at": now, "history": [],
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)
PY
}
```

`dl-launch.sh` 引擎 case 块改为：

```bash
# ---------- 引擎（DL_ENGINE：claude 默认 | qodercli；qodercli-engine-profile P1） ----------
# 优先级：显式 DL_ENGINE env（bashrc @qoder/调用方）> state.engine（per-instance
# sticky，resume 无 env 时接回原引擎）> claude。旧实例无 engine 字段=claude。
if [ -z "${DL_ENGINE:-}" ]; then
  DL_ENGINE="$(wf_state_get "$WF_NAME" engine 2>/dev/null || echo claude)"
fi
case "$DL_ENGINE" in
  claude)   ENGINE_BIN=claude;   ENGINE_PERM=acceptEdits ;;
  qodercli) ENGINE_BIN=qodercli; ENGINE_PERM=accept_edits ;;
  *) echo "✗ DL_ENGINE=$DL_ENGINE 未知引擎（claude|qodercli）" >&2; exit 1 ;;
esac
```

`dl-launch.sh` 的 `wf_state_init` 调用点（先 `grep -n "wf_state_init" scripts/workflow/dl-launch.sh` 核对）第 6 参追加 `"$DL_ENGINE"`。

- [ ] **Step 4: 跑冒烟 + 语法检查**

Run: `bash tests/test_dl_launch_engine.sh && bash -n scripts/workflow/dl-launch.sh scripts/workflow/dl-lib.sh && echo OK`
Expected: 全部 ✓ + OK

- [ ] **Step 5: Commit**

```bash
git add scripts/workflow/dl-lib.sh scripts/workflow/dl-launch.sh tests/test_dl_launch_engine.sh
git commit -m "feat(launch): state 落 engine 字段+resume sticky——无 env 时 wf_state_get 读回实例引擎（旧实例兜底 claude，T2）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: dl_drive 实例引擎归一

**Files:**
- Modify: `scripts/workflow/dl_drive.py`（main 入口 + 新增 `_apply_instance_engine`）
- Test: `tests/test_dl_drive.py`（追加）

**Interfaces:**
- Consumes: `engine.load_state(project_root, name)`（既有）；T2 的 `state["engine"]`
- Produces: `_apply_instance_engine(project_root: Path, name: str) -> None`——state.engine 存在则写 `os.environ["DL_ENGINE"]`

- [ ] **Step 1: 写失败测试**（追加到 tests/test_dl_drive.py）

```python
class TestApplyInstanceEngine:
    def _mk_state(self, tmp_path, name, engine_value=None):
        meta = tmp_path / ".claude" / "workflows" / name
        meta.mkdir(parents=True)
        state = {"name": name, "phase": "understand"}
        if engine_value is not None:
            state["engine"] = engine_value
        (meta / "state.json").write_text(json.dumps(state), encoding="utf-8")

    def test_state_engine_normalized_to_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DL_ENGINE", raising=False)
        self._mk_state(tmp_path, "wf1", "qodercli")
        dl_drive._apply_instance_engine(tmp_path, "wf1")
        assert os.environ["DL_ENGINE"] == "qodercli"

    def test_missing_field_keeps_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DL_ENGINE", "claude")
        self._mk_state(tmp_path, "wf1")  # 旧实例无 engine 字段
        dl_drive._apply_instance_engine(tmp_path, "wf1")
        assert os.environ["DL_ENGINE"] == "claude"

    def test_missing_state_noop(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DL_ENGINE", raising=False)
        dl_drive._apply_instance_engine(tmp_path, "ghost")
        assert "DL_ENGINE" not in os.environ
```

（`json`/`os` 该文件头部已有 import 则复用，没有照头部风格补）

- [ ] **Step 2: 跑确认失败**

Run: `python3 -m pytest tests/test_dl_drive.py::TestApplyInstanceEngine -q`
Expected: FAIL（`_apply_instance_engine` 不存在）

- [ ] **Step 3: 实现**

`dl_drive.py`（main 附近，import 区已有 os/json）：

```python
def _apply_instance_engine(project_root: Path, name: str) -> None:
    """per-instance-engine：实例引擎 sticky——state.engine 归一写回 DL_ENGINE env。

    drive 是单实例进程：归一后下游 get_engine()（段 spawn/judge）与 hooks
    （经 harness 继承 env）全链自动跟随，与拉起 drive 的 server/shell env 解耦
    （根治「claude 实例在 qoder server 下被错引擎驱动」）。旧实例无字段=不动
    env（调用方 env 原样，=现状）。
    """
    state = engine.load_state(project_root, name)
    if state and state.get("engine"):
        os.environ["DL_ENGINE"] = state["engine"]
```

`main()` 在 `args = parser.parse_args(argv)` + `project_root` 解析之后、`if args.segment:` 之前插入：

```python
    _apply_instance_engine(project_root, args.name)
```

- [ ] **Step 4: 跑测试 + drive 回归**

Run: `python3 -m pytest tests/test_dl_drive.py -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/workflow/dl_drive.py tests/test_dl_drive.py
git commit -m "feat(drive): 实例引擎归一——main 启动读 state.engine 写回 DL_ENGINE（根治 server env 错引擎驱动，T3）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: dashboard inject 读实例引擎

**Files:**
- Modify: `dl_dashboard/actions.py`（inject cmd 构造 ~211）
- Test: `tests/test_dl_dashboard_actions.py`（追加/调整）

**Interfaces:**
- Consumes: T1 `get_engine(override)`；`engine.load_state(project, name)`
- Produces: inject cmd 的引擎 = 目标实例 `state.engine`（不再吃 server env）

- [ ] **Step 1: 写失败测试**

```python
class TestInjectUsesInstanceEngine:
    """per-instance-engine：inject 引擎跟实例 state，不跟 server env（多实例进程禁 env 竞态）。"""

    def test_inject_reads_state_engine(self, monkeypatch, tmp_path):
        monkeypatch.delenv("DL_ENGINE", raising=False)  # server 无 env
        # state.engine=qodercli 的实例（fixture 按该文件现有 _mk_state 风格，
        # 加 engine 字段；先 grep -n "_mk_state\|def _mk" tests/test_dl_dashboard_actions.py 照抄）
        # ... 调 inject 路径捕获 cmd ...
        assert captured["cmd"][0] == "qodercli"
        assert "accept_edits" in captured["cmd"]
```

（脚手架照 T7 已落地的 `TestInjectCmdDualEngine` 同构——它现在靠 monkeypatch env，本用例改为 state 驱动；**注意**：T7 既有用例 monkeypatch 了 DL_ENGINE env——若新实现改 state 优先，需同步检查 T7 用例的 fixture state 是否含 engine 字段，不含则应按「旧实例兜底=env/claude」仍然全过）

- [ ] **Step 2: 跑确认失败**

- [ ] **Step 3: 改 inject cmd 构造**

```python
    # per-instance-engine：inject 引擎跟实例 state（override 直传，多实例
    # server 进程禁 env 竞态）；旧实例无字段=None→env→claude 兜底
    _st = engine.load_state(project, name)
    eng = dl_engine.get_engine((_st or {}).get("engine"))
    cmd = [
        eng.binary, "--resume", sid,
        "--settings", str(meta / "settings.drive-tui.json"),
        "--append-system-prompt-file", str(meta / f"tui-rules.{nid}.md"),
    ]
    cmd += eng.permission_args()
```

（`engine.load_state` 的签名先 `grep -n "def load_state" dl_flow_engine.py` 核对参数序——actions.py 别处已有调用照抄）

- [ ] **Step 4: 跑测试 + actions 回归**

Run: `python3 -m pytest tests/test_dl_dashboard_actions.py -q`
Expected: 全 PASS（含 T7 既有双引擎用例）

- [ ] **Step 5: Commit**

```bash
git add dl_dashboard/actions.py tests/test_dl_dashboard_actions.py
git commit -m "fix(dashboard): inject 引擎改读实例 state（get_engine(override)，多实例进程禁 env 竞态，T4）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: dashboard API + scanner + create 传递

**Files:**
- Modify: `dl_dashboard/scanner.py`（WorkflowInfo.engine + scan 读取）
- Modify: `dl_dashboard/app.py`（/api/engines + /api/create engine 参数）
- Modify: `dl_dashboard/actions.py`（create_workflow engine 参数 + env 传递）
- Test: `tests/test_dl_dashboard_app.py`、`tests/test_dl_dashboard_actions.py`、`tests/test_dl_dashboard_scanner.py`（各追加）

**Interfaces:**
- Consumes: T1 `available_engines()` / `get_engine(override)` 不适用此任务（create 走 launcher env）
- Produces:
  - `WorkflowInfo.engine: str = "claude"`（scanner 透传，前端徽标数据源）
  - `GET /api/engines` → `{"engines": list[str]}`
  - `POST /api/create` 接 `engine`（可选，∈ available_engines，未知→ok:False）
  - `create_workflow(project, name, statement, mgr, scope, tacet, provider_env, timeout, engine=None)`

- [ ] **Step 1: 写失败测试**

scanner（test_dl_dashboard_scanner.py 追加）：

```python
def test_scan_workflow_engine_default_and_read(tmp_path):
    # 无 engine 字段 → "claude"；有 → 透传（fixture 照该文件现有建 state 方式）
    ...
    assert scan_workflow(proj, "old").engine == "claude"
    assert scan_workflow(proj, "new").engine == "qodercli"
```

app（test_dl_dashboard_app.py 追加）：

```python
def test_api_engines_lists_available(client, monkeypatch):
    monkeypatch.setattr("dl_engine.available_engines", lambda: ["claude", "qodercli"])
    r = client.get("/api/engines")
    assert r.status_code == 200 and r.json()["engines"] == ["claude", "qodercli"]

def test_api_create_rejects_unknown_engine(client, monkeypatch):
    monkeypatch.setattr("dl_engine.available_engines", lambda: ["claude"])
    r = client.post("/api/create", json={"project": "...", "name": "x", "statement": "y", "engine": "qodercli"})
    assert r.json()["ok"] is False and "engine" in r.json()["msg"]
```

actions（test_dl_dashboard_actions.py 追加）：

```python
class TestCreateWorkflowEngine:
    def test_launcher_env_carries_engine(self, monkeypatch, tmp_path):
        captured = {}

        class FakeProc:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(argv, **kw):
            captured["env"] = kw.get("env")
            # 模拟 launcher 落 state（含 engine）——照 create_workflow 成败判定需要
            ...
            return FakeProc()

        monkeypatch.setattr(actions.subprocess, "run", fake_run)
        actions.create_workflow(tmp_path, "wf1", "stmt", FakeMgr(), engine="qodercli")
        assert captured["env"]["DL_ENGINE"] == "qodercli"
```

（client/fixture 照各文件既有模式；FakeMgr 提供 .start() 记录调用）

- [ ] **Step 2: 跑确认失败**

- [ ] **Step 3: 改三处**

`scanner.py`：

```python
    force_tacet: bool = False
    force_fermate: bool = False
    engine: str = "claude"  # per-instance-engine：实例引擎徽标（旧实例兜底 claude）
```

`scan_workflow` 填充处加（先 grep 核对 state 读取点）：

```python
        engine=state.get("engine", "claude"),
```

`app.py`：

```python
    @app.get("/api/engines")
    async def engines():
        return {"engines": dl_engine.available_engines()}
```

/app.py /api/create（`import dl_engine` 照 actions.py 同款加在文件头）：

```python
        eng_sel = body.get("engine")
        if eng_sel and eng_sel not in dl_engine.available_engines():
            return {"ok": False, "msg": f"引擎 {eng_sel} 在本机不可用（可选：{'/'.join(dl_engine.available_engines())}）"}
        ...
                actions.create_workflow, proj, name, body["statement"], mgr,
                body.get("scope", "fermate"), bool(body.get("tacet")),
                providers.get(provider) if provider else None,
                engine=eng_sel)
```

`actions.py` `create_workflow`：

```python
def create_workflow(project: Path, name: str, statement: str, mgr,
                    scope: str = "fermate", tacet: bool = False,
                    provider_env: dict | None = None,
                    timeout: int = 600,
                    engine: str | None = None) -> tuple[bool, str]:
    """... engine（per-instance-engine）：None=调用方 env 默认（claude）；
    显式值经 env 传 launcher 落 state.engine，并随 driver spawn env 携带。"""
    ...
    launch_env = None
    if engine:
        launch_env = {**os.environ, "DL_ENGINE": engine}
    try:
        p = subprocess.run(argv,
            cwd=str(project), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=timeout,
            errors="replace",
            env=launch_env,
        )
    ...
    drv_env = provider_env
    if engine:
        drv_env = {**(provider_env or {}), "DL_ENGINE": engine}
    mgr.start(project, name, Path(state["worktree_path"]), env=drv_env)
```

（`import os` 该文件已有）

- [ ] **Step 4: 跑测试 + dashboard 相关回归**

Run: `python3 -m pytest tests/test_dl_dashboard_app.py tests/test_dl_dashboard_actions.py tests/test_dl_dashboard_scanner.py -q`
Expected: 全 PASS

- [ ] **Step 5: 分 2 commit（H9）**

```bash
git add dl_dashboard/scanner.py tests/test_dl_dashboard_scanner.py
git commit -m "feat(dashboard): scanner 透传实例 engine 徽标字段（旧实例兜底 claude，T5）

Co-Authored-By: Claude <noreply@anthropic.com>"
git add dl_dashboard/app.py dl_dashboard/actions.py tests/test_dl_dashboard_app.py tests/test_dl_dashboard_actions.py
git commit -m "feat(dashboard): /api/engines+create 接 engine 参数——create_workflow env 传 DL_ENGINE 落 state（T5）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 前端引擎卡片 + provider 禁用 + 徽标 + E2E

**Files:**
- Modify: `dl_dashboard/static/index.html`（引擎卡片组）
- Modify: `dl_dashboard/static/app.js`（渲染/选择/提交/provider 禁用/徽标）
- Modify: `dl_dashboard/static/style.css`（引擎徽标小样式）
- Test: 无新增单测——E2E 人工验证（Step 3）

**Interfaces:**
- Consumes: T5 `/api/engines` / `/api/create` engine 参数 / scanner `engine` 字段
- Produces: `#engine-cards` 卡片组；创建 POST body 含 `engine`

- [ ] **Step 1: 实现 index.html**（provider field 之后插入）

```html
      <div class="field">
        <label>引擎（单选）</label>
        <div class="mode-cards" id="engine-cards"></div>
      </div>
```

- [ ] **Step 2: 实现 app.js**

加载时渲染引擎卡片（放在现有 providers 拉取逻辑附近，`grep -n "cf-provider\|/api/providers\|providers" dl_dashboard/static/app.js | head` 找挂载点）：

```javascript
async function initEngineCards() {
  const row = $("engine-cards");
  const r = await fetch("/api/engines");
  const engines = (await r.json()).engines || [];
  row.innerHTML = "";
  const LABELS = {
    claude: ["claude", "Claude Code 后端（默认）"],
    qodercli: ["qoder", "Qoder CLI 后端（dl @qoder）"],
  };
  engines.forEach((eng, i) => {
    const [title, desc] = LABELS[eng] || [eng, eng];
    const card = document.createElement("div");
    card.className = "mode-card" + (i === 0 ? " sel" : "");
    card.dataset.v = eng;
    card.innerHTML = `<b>${title}</b><span>${desc}</span>`;
    card.onclick = () => {
      row.querySelectorAll(".mode-card").forEach((x) => x.classList.remove("sel"));
      card.classList.add("sel");
      syncProviderForEngine();
    };
    row.appendChild(card);
  });
  syncProviderForEngine();
}

function currentEngine() {
  return document.querySelector("#engine-cards .mode-card.sel")?.dataset.v || "claude";
}

function syncProviderForEngine() {
  const sel = $("cf-provider");
  const qoder = currentEngine() === "qodercli";
  sel.disabled = qoder;  // provider=claude 系 ac-* env，qoder 不适用
  sel.title = qoder ? "qoder 引擎不使用 provider（模型由向导选中或 DL_QODER_MODEL 定）" : "";
}
```

提交处（`$("create-form").onsubmit` 既有 body 组装点，`grep -n "scope\b" dl_dashboard/static/app.js | head` 找 `body = {...}`）加：

```javascript
  body.engine = currentEngine();
```

实例徽标（实例卡片渲染处，`grep -n "force_tacet\|tacet.*badge\|徽标" dl_dashboard/static/app.js | head` 找既有徽标渲染点照加）：

```javascript
  if (info.engine && info.engine !== "claude") {
    // 非默认引擎才显徽标（claude=默认不吵）
    html += `<span class="engine-badge engine-${info.engine}">${info.engine === "qodercli" ? "qoder" : info.engine}</span>`;
  }
```

style.css 追加：

```css
.engine-badge { font-size: 11px; padding: 1px 6px; border-radius: 4px; background: #e8f0fe; color: #1a56db; margin-left: 6px; }
.engine-qodercli { background: #fdf0e6; color: #c2410c; }
```

- [ ] **Step 3: E2E 人工验证（服务器实机，dashboard 起服务）**

```bash
cd ~/.dl-workflow && git -C ~/projects/dl-workflow-wt/per-instance-engine log --oneline -1  # 确认 worktree HEAD
cd ~/projects/dl-workflow-wt/per-instance-engine && python3 -m dl_dashboard.app &
```

逐条勾：
- [ ] 创建表单出现引擎卡片（claude+qoder 两张，claude 默认选中；均无下拉）
- [ ] 选 qoder → provider 下拉变灰禁用；切回 claude 恢复
- [ ] 建 qoder 实例 → `state.json` 含 `"engine": "qodercli"`；driver 段进程 argv=qodercli（`ps aux | grep qodercli`）
- [ ] 实例卡片显示 qoder 徽标
- [ ] 无 DL_ENGINE 环境变量 `dl <name> --resume` 接该实例 → 仍起 qodercli（launcher sticky）
- [ ] 已有 claude 实例在同 server 下 inject/驱动 → 段进程仍是 claude（不串引擎）
- [ ] 只装单引擎的机器（临时 PATH 屏蔽 qodercli 验证）：/api/engines 只返回一个 → 表单只渲染一张卡

- [ ] **Step 4: 全量回归 + 设计文档验收回填 + commit**

Run: `python3 -m pytest tests/ -q 2>&1 | tail -1`
E2E 结果回填 `designs/per-instance-engine-design.md` §5（逐项 ✅+证据），然后：

```bash
git add dl_dashboard/static/index.html dl_dashboard/static/app.js
git commit -m "feat(dashboard): 创建表单引擎卡片组（mode-card 复用禁下拉）+qoder 时 provider 禁用+实例引擎徽标（T6）

Co-Authored-By: Claude <noreply@anthropic.com>"
git add dl_dashboard/static/style.css designs/per-instance-engine-design.md
git commit -m "feat(dashboard): 引擎徽标样式+设计验收回填（T6）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review 记录

- **Spec 覆盖**：设计 5 改动点 ↔ T2(①)/T3(②drive)/T4(②inject)/T2(②resume sticky)/T5(③)/T6(④)/hooks 零改动（⑤=T3 归一覆盖，Global Constraints 注明）；验收 §5 ↔ T6 Step 3/4
- **Placeholder 扫描**：T4/T5 测试脚手架标注「照 T7/既有同构」——执行时先 `grep` 现行用例照抄（T7 的 TestInjectCmdDualEngine 已在 main）；T6 E2E 为人工清单（前端无单测设施，与 build-and-modify §1.5「改 dashboard 必过真实实例 E2E」纪律一致）
- **类型一致性**：`get_engine(override)` T1 定义 T4 消费一致；`wf_state_init` 6 参 T2 定义与 dl-launch 调用点一致；`create_workflow(engine=)` T5 定义与 app.py 调用一致；`WorkflowInfo.engine` T5 定义 T6 前端消费一致
- **T3 与 T4 的 env 策略分野**：drive=单实例进程 env 归一（T3）；dashboard=多实例进程 override 直传（T4/T5）——两处不混用，各有注释
