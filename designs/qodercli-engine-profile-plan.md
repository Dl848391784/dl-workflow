# qodercli 引擎适配层（P1+P2）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** dl-workflow 单库双引擎——`DL_ENGINE=qodercli` 时全部 spawn/settings/hook 契约面切到 qodercli，`DL_ENGINE` 未设（claude）时行为与现状逐位一致。

**Architecture:** 新增 `dl_engine.py` 单源 EngineProfile（binary/权限拼写/flag 差异/日志根/计量语义 + 4 个 args 组合方法）；7 处 spawn、3 处 settings 写出、hooks 契约面（env 链/Stop 输出/agentId regex）按 profile 或 DL_ENGINE env 分路。差异依据 = P0 实测（设计文档 §3a/3b，D1-D12）。

**Tech Stack:** Python 3（dl_engine/hooks/drive/judge/dashboard）、bash（dl-launch/dl-lib/install）、pytest（tests/）。

## Global Constraints

- **claude 默认路径零行为变化**：`DL_ENGINE` 未设时所有代码路径与现状逐位一致（golden test 保证）
- **no silent fallback**：未知 `DL_ENGINE` 值显式报错退出，禁止默认回退
- **H9**：单 commit ≤3 文件 AND ≤200 行；禁 `git add -A`（逐文件 add）
- **H11**：日志 `%` 惰性格式化，禁 f-string 日志
- **qoder 已知限制（v1 不修，写注释即可）**：①settings `permissions.defaultMode` 被 qoder 忽略（P0 实测两种拼写 init 均=default）——权限唯 CLI flag 生效，dl-launch 已钉死，正好兼容；②段前缀剥离（`segment_strip_project_context` 的 `CLAUDE_CODE_DISABLE_*` env）对 qoder 无效——qoder 引擎 v1 不退化正确性只多付前缀成本，per-segment settings 变体留后续轨道；③BYOK 模型 usage/cost 全零（D6），成本对账显示 N/A 不报错
- **worktree**：全部改动在 `~/projects/dl-workflow-wt/qodercli-engine-profile`（分支 feat/qodercli-engine-profile），收口 merge 回 main
- commit message 结尾：`Co-Authored-By: Claude <noreply@anthropic.com>`

---

### Task 1: `dl_engine.py` 引擎 profile 单源

**Files:**
- Create: `dl_engine.py`（仓根，与 dl_flow_engine.py 同级）
- Test: `tests/test_dl_engine.py`

**Interfaces:**
- Produces（后续全部任务依赖）:
  - `dl_engine.get_engine() -> EngineProfile`——读 `DL_ENGINE` env（默认 `claude`，未知值 `SystemExit`）
  - `EngineProfile` 字段：`name:str`、`binary:str`、`config_root:Path`、`project_resource_dir:str`、`permission_cli_value:str`、`skills_dir_display:str`、`debug_logs_root:Path|None`、`usage_metered:bool`
  - `EngineProfile` 方法：`permission_args()->list[str]`、`verbose_args()->list[str]`、`debug_args(debug_file:Path)->list[str]`、`disallow_ask_args()->list[str]`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_dl_engine.py
"""dl_engine 引擎 profile 单源测试（designs/qodercli-engine-profile-design.md §P1）。"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dl_engine  # noqa: E402


class TestGetEngine:
    def test_default_is_claude(self, monkeypatch):
        monkeypatch.delenv("DL_ENGINE", raising=False)
        eng = dl_engine.get_engine()
        assert eng.name == "claude"
        assert eng.binary == "claude"

    def test_qodercli_profile(self, monkeypatch):
        monkeypatch.setenv("DL_ENGINE", "qodercli")
        eng = dl_engine.get_engine()
        assert eng.name == "qodercli"
        assert eng.binary == "qodercli"
        assert eng.config_root == Path.home() / ".qoder"
        assert eng.project_resource_dir == ".qoder"
        assert eng.permission_cli_value == "accept_edits"
        assert eng.usage_metered is False

    def test_unknown_engine_hard_fails(self, monkeypatch):
        monkeypatch.setenv("DL_ENGINE", "gemini")
        with pytest.raises(SystemExit):
            dl_engine.get_engine()

    def test_empty_env_is_claude(self, monkeypatch):
        monkeypatch.setenv("DL_ENGINE", "")
        assert dl_engine.get_engine().name == "claude"


class TestArgsComposition:
    """cmd 碎片 golden——claude 必须与现状逐位一致（回归承重墙）。"""

    def test_claude_golden(self, monkeypatch):
        monkeypatch.delenv("DL_ENGINE", raising=False)
        eng = dl_engine.get_engine()
        assert eng.permission_args() == ["--permission-mode", "acceptEdits"]
        assert eng.verbose_args() == ["--verbose"]
        assert eng.debug_args(Path("/tmp/x.log")) == [
            "--debug", "api,hooks", "--debug-file", "/tmp/x.log",
        ]
        assert eng.disallow_ask_args() == ["--disallowedTools", "AskUserQuestion"]

    def test_qoder_golden(self, monkeypatch):
        monkeypatch.setenv("DL_ENGINE", "qodercli")
        eng = dl_engine.get_engine()
        assert eng.permission_args() == ["--permission-mode", "accept_edits"]
        assert eng.verbose_args() == []                       # P0 D1：无 --verbose
        assert eng.debug_args(Path("/tmp/x.log")) == ["--debug"]  # P0 D2：无 --debug-file
        assert eng.disallow_ask_args() == []                  # P0 D4：无 AskUserQuestion

    def test_skills_dir_display(self, monkeypatch):
        monkeypatch.delenv("DL_ENGINE", raising=False)
        assert dl_engine.get_engine().skills_dir_display == "~/.claude/skills"
        monkeypatch.setenv("DL_ENGINE", "qodercli")
        assert dl_engine.get_engine().skills_dir_display == "~/.qoder/skills"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/projects/dl-workflow-wt/qodercli-engine-profile && python3 -m pytest tests/test_dl_engine.py -q`
Expected: FAIL（`ModuleNotFoundError: dl_engine`）

- [ ] **Step 3: 实现 dl_engine.py**

```python
#!/usr/bin/env python3
"""dl_engine - 引擎 profile 单源（designs/qodercli-engine-profile-design.md §P1）。

dl-workflow 双引擎（claude | qodercli）的全部 harness 差异集中于此：binary、
配置根、权限值拼写、flag 差异、debug 日志根、计量语义。差异依据 = P0 实测
（同设计 §3a/3b D1-D12），禁凭 bundle 字符串推断新增项。

引擎选择 = DL_ENGINE env（launcher 设置，hooks/段工人/dashboard 继承）：
- 未设/空 = claude（默认，行为与单引擎时代逐位一致）
- 未知值 = SystemExit 显式报错（no silent fallback 铁律，不默认回退 claude）
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EngineProfile:
    """单引擎全部差异面。方法只组合 cmd 碎片，不 spawn。"""

    name: str  # "claude" | "qodercli"
    binary: str  # spawn 二进制名
    config_root: Path  # 用户配置根（settings/skills/commands/output-styles 安装目标）
    project_resource_dir: str  # 项目资源目录名（".claude" | ".qoder"）
    permission_cli_value: str  # --permission-mode 的 CLI 拼写（P0：payload 内都是 acceptEdits，仅 CLI 拼写不同）
    skills_dir_display: str  # judge rubric 文本里的 skills 注册表路径（dl_flow_engine 单点替换）
    debug_logs_root: Path | None  # debug 日志自动落盘根（qoder）；claude=None（走 --debug-file）
    usage_metered: bool  # False=BYOK 引擎 usage/cost 全零（P0 D6），成本对账降级 N/A

    def permission_args(self) -> list[str]:
        return ["--permission-mode", self.permission_cli_value]

    def verbose_args(self) -> list[str]:
        # claude stream-json 需要 --verbose 才出 assistant 事件；
        # qodercli 无此 flag（P0 D1 实测 exit 1「unknown option」）
        return ["--verbose"] if self.name == "claude" else []

    def debug_args(self, debug_file: Path) -> list[str]:
        if self.name == "claude":
            return ["--debug", "api,hooks", "--debug-file", str(debug_file)]
        # qoder 无 --debug-file（P0 D2）；--debug 后日志自动落
        # ~/.qoder/logs/sessions/<proj>/<sid>/segments/*.jsonl（结构化 jsonl，更优）
        return ["--debug"]

    def disallow_ask_args(self) -> list[str]:
        # qoder 无 AskUserQuestion 工具（P0 D4 tools 列表确认）——工具不存在=
        # 结构堵死，L1 权限层封禁豁免；L2 嗅探（_session_called_ask_user）保留
        if self.name == "claude":
            return ["--disallowedTools", "AskUserQuestion"]
        return []


_PROFILES: dict[str, EngineProfile] = {
    "claude": EngineProfile(
        name="claude",
        binary="claude",
        config_root=Path.home() / ".claude",
        project_resource_dir=".claude",
        permission_cli_value="acceptEdits",
        skills_dir_display="~/.claude/skills",
        debug_logs_root=None,
        usage_metered=True,
    ),
    "qodercli": EngineProfile(
        name="qodercli",
        binary="qodercli",
        config_root=Path(os.environ.get("QODER_CONFIG_DIR") or (Path.home() / ".qoder")),
        project_resource_dir=".qoder",
        permission_cli_value="accept_edits",
        skills_dir_display="~/.qoder/skills",
        debug_logs_root=Path.home() / ".qoder" / "logs" / "sessions",
        # BYOK 实测 usage/cost 全零（D6）；内置 Qwen 模型待验（设计 §3c）——
        # 有实证前一律按未计量处理（对账显示 N/A，不报错不虚构）
        usage_metered=False,
    ),
}


def get_engine() -> EngineProfile:
    """当前引擎 profile。DL_ENGINE 未设/空 = claude；未知值硬失败。"""
    name = os.environ.get("DL_ENGINE", "").strip() or "claude"
    profile = _PROFILES.get(name)
    if profile is None:
        print(
            f"✗ DL_ENGINE={name!r} 未知引擎（可选：{sorted(_PROFILES)}）"
            "——拒绝静默回退（no silent fallback）",
            file=sys.stderr,
        )
        sys.exit(2)
    return profile
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_dl_engine.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
cd ~/projects/dl-workflow-wt/qodercli-engine-profile
git add dl_engine.py tests/test_dl_engine.py
git commit -m "feat(engine): dl_engine 引擎 profile 单源——双引擎差异集中+4 args 组合方法，golden 锁定 claude 现状（qodercli-engine-profile P1 T1）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: hooks env fallback 链加 QODER_* 前缀

**Files:**
- Modify: `hooks/workflow_step_fence.py:425-440`（`_session_id`）
- Modify: `hooks/codegraph_gate.py:110-118`、`hooks/design_gate.py:104-116`（同构 `_session_id`）
- Modify: `hooks/codegraph_audit.py:111-119`、`hooks/design_audit.py:84-92`（同构）
- Modify: `hooks/codegraph_inject.py:98`、`hooks/conventions_inject.py:34`（`CLAUDE_PROJECT_DIR` 读取点）
- Test: `tests/test_hooks_engine_env.py`（新建）

**Interfaces:**
- Consumes: 无（hooks 只读 `QODER_*`/`CLAUDE_*` env，不依赖 dl_engine——hook 进程应零 import 依赖保持轻量）
- Produces: 无新接口；行为契约 = 各 `_session_id` 的 env fallback 顺序变为 `QODER_SESSION_ID → CLAUDE_SESSION_ID → "_fallback"`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_hooks_engine_env.py
"""hooks 双引擎 env fallback 链（P0：qoder 注入 QODER_* + CLAUDE_PROJECT_DIR 别名）。"""
import importlib
import os
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"


def _load(name: str):
    """按路径加载 hook 模块（hooks 非 package，文件名即模块名）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, HOOKS_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestSessionIdChain:
    def test_fence_prefers_qoder_env(self, monkeypatch):
        monkeypatch.setenv("QODER_SESSION_ID", "q-sid")
        monkeypatch.setenv("CLAUDE_SESSION_ID", "c-sid")
        fence = _load("workflow_step_fence")
        assert fence._session_id({}) == "q-sid"

    def test_fence_falls_back_to_claude_env(self, monkeypatch):
        monkeypatch.delenv("QODER_SESSION_ID", raising=False)
        monkeypatch.setenv("CLAUDE_SESSION_ID", "c-sid")
        fence = _load("workflow_step_fence")
        assert fence._session_id({}) == "c-sid"

    def test_payload_still_wins(self, monkeypatch):
        monkeypatch.setenv("QODER_SESSION_ID", "q-sid")
        fence = _load("workflow_step_fence")
        assert fence._session_id({"session_id": "p-sid"}) == "p-sid"


class TestProjectDirChain:
    @pytest.mark.parametrize("mod_name,func", [
        ("codegraph_inject", None),   # 具体函数名以实现步骤核对的为准
    ])
    def test_placeholder(self, mod_name, func):
        pytest.skip("见 Step 3——inject 两文件的读取点行号核对后补断言")
```

> ⚠️ Step 1 的 inject 测试先落 fence 三条；inject 两文件的测试在 Step 3 核对实际读取代码后补同构断言（读取点可能是模块级常量而非函数——若是常量则改为「重载模块后断言常量值」）。

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_hooks_engine_env.py -q`
Expected: `test_fence_prefers_qoder_env` FAIL（当前返回 `"c-sid"`）

- [ ] **Step 3: 改 6 处（每处前先 `sed -n` 核对现行代码，保持同构）**

`hooks/workflow_step_fence.py` `_session_id` 末尾：

```python
    # env fallback：QODER_SESSION_ID（qoder 引擎注入）→ CLAUDE_SESSION_ID
    #（claude 引擎/向后兼容）。P0 实测 qoder 两前缀都注入，顺序无害、QODER 优先。
    return (
        os.environ.get("QODER_SESSION_ID", "").strip()
        or os.environ.get("CLAUDE_SESSION_ID", "").strip()
        or "_fallback"
    )
```

`codegraph_gate.py` / `design_gate.py` / `codegraph_audit.py` / `design_audit.py` 的同构 `_session_id`（先 `grep -n "CLAUDE_SESSION_ID" hooks/*.py` 列出全部命中逐处核对）：同一替换——把单个 `os.environ.get("CLAUDE_SESSION_ID", "")...` 表达式换成上面三行链。

`codegraph_inject.py:98` / `conventions_inject.py:34`（先 `sed -n '90,105p' hooks/codegraph_inject.py` 核对）：

```python
# 改前：project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ...)（或同构表达式）
# 改后：
project_dir = (
    os.environ.get("QODER_PROJECT_DIR")
    or os.environ.get("CLAUDE_PROJECT_DIR")
    or <原有兜底表达式，逐字保留>
)
```

- [ ] **Step 4: 跑测试 + 相关回归**

Run: `python3 -m pytest tests/test_hooks_engine_env.py tests/test_codegraph_gate.py tests/test_design_gate.py -q`
Expected: 全 PASS

- [ ] **Step 5: 分 3 个 commit（H9 ≤3 文件）**

```bash
cd ~/projects/dl-workflow-wt/qodercli-engine-profile
git add hooks/workflow_step_fence.py tests/test_hooks_engine_env.py
git commit -m "feat(hooks): fence 会话标识 env 链加 QODER_SESSION_ID 前缀（P1 T2，qoder 引擎识别段工人）

Co-Authored-By: Claude <noreply@anthropic.com>"
git add hooks/codegraph_gate.py hooks/design_gate.py
git commit -m "feat(hooks): codegraph/design gate 会话标识 env 链加 QODER_ 前缀（P1 T2）

Co-Authored-By: Claude <noreply@anthropic.com>"
git add hooks/codegraph_audit.py hooks/design_audit.py hooks/codegraph_inject.py
git commit -m "feat(hooks): audit 双件 env 链 + codegraph_inject 项目根 QODER_PROJECT_DIR 优先（P1 T2）

Co-Authored-By: Claude <noreply@anthropic.com>"
git add hooks/conventions_inject.py
git commit -m "feat(hooks): conventions_inject 项目根 QODER_PROJECT_DIR 优先（P1 T2）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: D5——workflow_advance Stop 续轮输出按引擎分路

**Files:**
- Modify: `hooks/workflow_advance.py:289-303`（`_stop_continue`）
- Test: `tests/test_workflow_advance.py`（追加；文件名先 `ls tests/ | grep advance` 核对）

**Interfaces:**
- Consumes: `DL_ENGINE` env（hook 进程从 harness 继承，harness 从 launcher 继承）
- Produces: `_stop_continue(body: str) -> int` 签名不变；qoder 引擎 stdout 改为 `{"decision":"block","reason":body}`

- [ ] **Step 1: 写失败测试**（追加到 tests/test_workflow_advance.py 末尾）

```python
class TestStopContinueEngineContract:
    """P0 D5 实测：qoder 只认 decision=block+reason（additionalContext 被忽略）。"""

    def test_claude_outputs_additional_context(self, monkeypatch, capsys):
        monkeypatch.delenv("DL_ENGINE", raising=False)
        advance._stop_continue("BODY_X")
        out = json.loads(capsys.readouterr().out)
        assert out["hookSpecificOutput"]["additionalContext"] == "BODY_X"
        assert "decision" not in out

    def test_qoder_outputs_decision_reason(self, monkeypatch, capsys):
        monkeypatch.setenv("DL_ENGINE", "qodercli")
        advance._stop_continue("BODY_X")
        out = json.loads(capsys.readouterr().out)
        assert out == {"decision": "block", "reason": "BODY_X"}
```

（`advance` 的 import 方式照该测试文件头部现有写法）

- [ ] **Step 2: 跑测试确认第 2 条失败**

Run: `python3 -m pytest tests/test_workflow_advance.py::TestStopContinueEngineContract -q`
Expected: `test_qoder_outputs_decision_reason` FAIL（当前仍输出 additionalContext 形态）

- [ ] **Step 3: 改 `_stop_continue`**

```python
def _stop_continue(body: str) -> int:
    """返 Stop hook 续轮指令通用底座。

    引擎契约（qodercli-engine-profile P0 D5 实测）：claude 认
    hookSpecificOutput.additionalContext（changelog:1000，撞 cap 默认 8 自动
    终结）；qodercli 只认 decision=block+reason——reason 文本注入为 user msg，
    additionalContext 被忽略（探针实证），stop_hook_active 二次触发=true 与
    claude 同语义。按 DL_ENGINE 分路，默认 claude 路径逐字不动。
    """
    if os.environ.get("DL_ENGINE", "").strip() == "qodercli":
        out = {"decision": "block", "reason": body}
    else:
        out = {
            "hookSpecificOutput": {
                "hookEventName": "Stop",
                "additionalContext": body,
            }
        }
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0
```

- [ ] **Step 4: 跑测试 + 本文件全量回归**

Run: `python3 -m pytest tests/test_workflow_advance.py -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add hooks/workflow_advance.py tests/test_workflow_advance.py
git commit -m "fix(hooks): Stop 续轮按引擎分路——qoder 走 decision: block+reason（P0 D5 实测 additionalContext 被忽略，P1 T3）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: D7——agentId/task-id regex 放宽（两处同步）

**Files:**
- Modify: `hooks/workflow_advance.py:154-159`（regex 单源）
- Modify: `hooks/workflow_step_fence.py:410-414`（同步副本）
- Test: `tests/test_workflow_advance.py`（追加）

**Interfaces:**
- Produces: `_AGENT_LAUNCH_ID_RE` / `_AGENT_DONE_ID_RE`——新捕获：qoder 格式 `ageneral-purpose-104997bfb6f1884a` 取尾段 hex；claude 原格式不变

- [ ] **Step 1: 写失败测试**

```python
class TestAgentIdRegexDualEngine:
    """P0 D7：qoder agentId = a<type>-<hex16>（如 ageneral-purpose-104997bfb6f1884a）。"""

    @pytest.mark.parametrize("text,expect", [
        ("Async agent launched successfully.\nagentId: 104997bfb6f1884a (internal ID)", "104997bfb6f1884a"),  # claude
        ("Async agent launched successfully.\nagentId: ageneral-purpose-104997bfb6f1884a (internal ID", "104997bfb6f1884a"),  # qoder
    ])
    def test_launch_id(self, text, expect):
        assert advance._AGENT_LAUNCH_ID_RE.findall(text) == [expect]

    @pytest.mark.parametrize("text,expect", [
        ("<task-id>104997bfb6f1884a</task-id>", "104997bfb6f1884a"),
        ("<task-id>ageneral-purpose-104997bfb6f1884a</task-id>", "104997bfb6f1884a"),
    ])
    def test_done_id(self, text, expect):
        assert advance._AGENT_DONE_ID_RE.findall(text) == [expect]
```

- [ ] **Step 2: 跑确认 qoder 两条 FAIL**

Run: `python3 -m pytest tests/test_workflow_advance.py::TestAgentIdRegexDualEngine -q`
Expected: qoder 参数化两条 FAIL，claude 两条 PASS

- [ ] **Step 3: 两文件同一替换**（先改 advance 单源，再同步 fence——两文件注释本就要求同步改）

```python
# 后台 Agent 的派发/归还信号（harness 契约，v2.118 实测自真实 transcript；
# qoder 复核 2026-09-08 P0 D7）。派发 = tool_result 文本含 launch ack 与
# agentId；归还 = <task-notification> 携 <task-id>。id 真身 = 16-17 位小写
# hex；qoder 引擎带 a<type>- 前缀（ageneral-purpose-<hex16>），前缀可选故
# 双引擎兼容。fence.py 有同步副本，两处必须同改。
_AGENT_LAUNCH_ACK = "Async agent launched successfully"
_AGENT_LAUNCH_ID_RE = re.compile(r"agentId:\s*(?:a[a-z-]+-)?([0-9a-f]{16,17})\b")
_AGENT_DONE_ID_RE = re.compile(r"<task-id>\s*(?:a[a-z-]+-)?([0-9a-f]{16,17})\s*</task-id>")
```

- [ ] **Step 4: 跑测试 + fence 相关回归**

Run: `python3 -m pytest tests/test_workflow_advance.py -q && python3 -m pytest tests/ -q -k fence`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add hooks/workflow_advance.py hooks/workflow_step_fence.py tests/test_workflow_advance.py
git commit -m "fix(hooks): agentId/task-id regex 兼容 qoder a<type>- 前缀（P0 D7，advance 单源+fence 同步，P1 T4）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: dl_drive.py 4 处 spawn 走 profile

**Files:**
- Modify: `scripts/workflow/dl_drive.py`（4 处：`_spawn_redteam` ~282、`run_session` ~726、`MergedSession.__init__` ~906、`_build_tui_cmd` ~1787；import 区 ~38）
- Test: `tests/test_dl_drive.py`（追加 cmd 捕获测试）

**Interfaces:**
- Consumes: `dl_engine.get_engine()` + 4 个 args 方法（Task 1）
- Produces: 无新接口；行为契约 = 4 处 spawn cmd 的 binary/verbose/permission/disallow_ask/debug 碎片全部来自 profile

- [ ] **Step 1: 写失败测试**（Popen 捕获 cmd；run_session 签名见 dl_drive.py:689-703）

```python
class TestSegmentCmdDualEngine:
    """4 处 spawn cmd 按 DL_ENGINE 分路（P0 D1/D2/D3/D4）。"""

    def _capture_cmd(self, monkeypatch, tmp_path):
        captured = {}

        class FakeProc:
            pid = 999999
            returncode = 0

            def __init__(self, cmd, **kw):
                captured["cmd"] = cmd
                self.stdout = iter([])

            def wait(self, timeout=None):
                return 0

            def terminate(self):
                pass

            def kill(self):
                pass

        monkeypatch.setattr(dl_drive.subprocess, "Popen", FakeProc)
        return captured

    def test_run_session_claude_golden(self, monkeypatch, tmp_path):
        monkeypatch.delenv("DL_ENGINE", raising=False)
        captured = self._capture_cmd(monkeypatch, tmp_path)
        try:
            dl_drive.run_session(
                "p", cwd=tmp_path, settings=tmp_path / "s.json",
                sys_prompt_file=tmp_path / "r.md", meta=tmp_path,
                debug=True, note="t",
            )
        except Exception:
            pass  # 流解析失败无所谓，cmd 已捕获
        cmd = captured["cmd"]
        assert cmd[0] == "claude"
        assert "--verbose" in cmd
        assert "acceptEdits" in cmd
        assert "--debug-file" in cmd

    def test_run_session_qoder(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DL_ENGINE", "qodercli")
        captured = self._capture_cmd(monkeypatch, tmp_path)
        try:
            dl_drive.run_session(
                "p", cwd=tmp_path, settings=tmp_path / "s.json",
                sys_prompt_file=tmp_path / "r.md", meta=tmp_path,
                debug=True, note="t", disallow_ask=True,
            )
        except Exception:
            pass
        cmd = captured["cmd"]
        assert cmd[0] == "qodercli"
        assert "--verbose" not in cmd
        assert "accept_edits" in cmd
        assert "--debug-file" not in cmd and "--debug" in cmd
        assert "--disallowedTools" not in cmd  # D4：qoder 无 AskUserQuestion
```

（`dl_drive` 的 import 照 tests/test_dl_drive.py 头部现有写法）

- [ ] **Step 2: 跑确认 qoder 用例 FAIL**

Run: `python3 -m pytest tests/test_dl_drive.py::TestSegmentCmdDualEngine -q`
Expected: `test_run_session_qoder` FAIL（cmd[0] 仍是 claude）

- [ ] **Step 3: 改 4 处**

import 区（dl_drive.py:39 后）：

```python
import dl_engine  # noqa: E402  # 引擎 profile 单源（qodercli-engine-profile P1）
```

`run_session`（~726 行起）cmd 构造改为：

```python
    eng = dl_engine.get_engine()
    cmd = [eng.binary, "-p", "--output-format", "stream-json"]
    cmd += eng.verbose_args()
    if tools:
        cmd += ["--tools", ",".join(tools)]
    if disallow_ask:
        # claude：--disallowedTools 是变长参数，其后必须跟旗标（2026-08-12 实爆）；
        # qoder：无 AskUserQuestion 工具（P0 D4），eng.disallow_ask_args() 返回空
        cmd += eng.disallow_ask_args()
    cmd += eng.permission_args()
    cmd += [
        "--settings",
        str(settings),
        "--append-system-prompt-file",
        str(sys_prompt_file),
    ]
    cmd += engine.NO_MCP_ARGS
    if resume_sid:
        cmd += ["--resume", resume_sid]
    else:
        cmd += ["--session-id", sid]
    if debug:
        cmd += eng.debug_args(meta / f"cc_debug.{sid[:8]}.log")
```

`_spawn_redteam`（~282）：`"claude"` → `dl_engine.get_engine().binary`，`["--permission-mode", "acceptEdits"]` → `dl_engine.get_engine().permission_args()`（在 cmd 构造前取一次 `eng = dl_engine.get_engine()`，下同）。

`MergedSession.__init__`（~906）：

```python
        eng = dl_engine.get_engine()
        cmd = [eng.binary, "-p", "--input-format", "stream-json", "--output-format", "stream-json"]
        cmd += eng.verbose_args()
        cmd += eng.permission_args()
        cmd += [
            "--settings",
            str(settings),
            "--append-system-prompt-file",
            str(sys_prompt_file),
        ]
        if tools:
            cmd += ["--tools", ",".join(tools)]
        cmd += engine.NO_MCP_ARGS
        cmd += ["--session-id", self.sid]
        if debug:
            cmd += eng.debug_args(meta / f"cc_debug.{self.sid[:8]}.log")
```

`_build_tui_cmd`（~1787）：

```python
    eng = dl_engine.get_engine()
    cmd = [
        eng.binary,
        "--session-id",
        sid,
        "--settings",
        str(settings),
        "--append-system-prompt-file",
        str(rules),
    ]
    cmd += eng.permission_args()
    if tools:
        cmd += ["--tools", ",".join(tools)]
    cmd += engine.NO_MCP_ARGS
    if debug:
        cmd += eng.debug_args(meta / f"cc_debug.{sid[:8]}.log")
    if prompt is not None:
        cmd += ["--", prompt]
    return cmd
```

- [ ] **Step 4: 跑测试 + drive 全量回归**

Run: `python3 -m pytest tests/test_dl_drive.py tests/test_dl_drive_segment_stats.py -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/workflow/dl_drive.py tests/test_dl_drive.py
git commit -m "feat(drive): 4 处段 spawn 走引擎 profile（binary/verbose/perm/disallow_ask/debug 按 DL_ENGINE，P0 D1-D4，P1 T5）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: judge spawn + rubric skills 路径单点替换（dl_flow_engine.py）

**Files:**
- Modify: `dl_flow_engine.py`（judge `_run_judge_once` ~2916-2938；import 区）
- Test: `tests/test_dl_flow_engine.py`（追加）

**Interfaces:**
- Consumes: `dl_engine.get_engine()`；judge cmd 保持 `--tools ""` + `NO_MCP_ARGS` + `--system-prompt`（qoder 均支持，P0 help/实测）
- Produces: judge spawn 走 profile；prompt 内 `~/.claude/skills` / `.claude/skills` 字面按引擎替换（rubric 文本参数化单点）

- [ ] **Step 1: 写失败测试**

```python
class TestJudgeCmdDualEngine:
    def test_judge_cmd_qoder(self, monkeypatch):
        monkeypatch.setenv("DL_ENGINE", "qodercli")
        captured = {}

        class FakeRes:
            returncode = 0
            stdout = '{"is_error":false,"result":"{\\"pass\\":true,\\"reason\\":\\"ok\\"}"}'

        monkeypatch.setattr(
            engine.subprocess, "run",
            lambda cmd, **kw: captured.setdefault("cmd", cmd) or FakeRes(),
        )
        try:
            engine._run_judge_once("判据含 ~/.claude/skills 与 .claude/skills 引用")
        except Exception:
            pass
        cmd = captured["cmd"]
        assert cmd[0] == "qodercli"
        prompt_arg = cmd[-1]
        assert "~/.qoder/skills" in prompt_arg
        assert "~/.claude/skills" not in prompt_arg
```

（`engine` 的 import 照 tests/test_dl_flow_engine.py 头部现有写法；`_run_judge_once` 的真实函数名先 `grep -n "def _run_judge" dl_flow_engine.py` 核对后替换）

- [ ] **Step 2: 跑确认 FAIL**

Run: `python3 -m pytest tests/test_dl_flow_engine.py::TestJudgeCmdDualEngine -q`
Expected: FAIL（cmd[0]=claude 或替换未生效）

- [ ] **Step 3: 改 judge spawn**

import 区加 `import dl_engine`。`_run_judge_once` 的 `subprocess.run` 调用改为：

```python
        eng = dl_engine.get_engine()
        env = dict(os.environ)
        env["MAX_THINKING_TOKENS"] = "0"
        res = subprocess.run(
            # --tools ""：judge 明确不调工具（qoder help 同支持 ""=禁全部）。
            # --system-prompt：judge 人设替换 coding 助手人设。
            # skills 注册表路径按引擎单点替换（rubric 文本在 dl_flow_nodes 静态
            # 定义，此处是全部 judge prompt 的唯一收口）：先长后短防子串误伤
            #（"~/.claude/skills" 本身含 ".claude/skills"）。
            [
                eng.binary,
                "-p",
                "--output-format",
                "json",
                "--tools",
                "",
                *NO_MCP_ARGS,
                "--system-prompt",
                JUDGE_SYSTEM_PROMPT,
                prompt.replace("~/.claude/skills", eng.skills_dir_display).replace(
                    ".claude/skills", f"{eng.project_resource_dir}/skills"
                ),
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=JUDGE_TIMEOUT,
            cwd=tempfile.gettempdir(),
            env=env,
        )
```

- [ ] **Step 4: 跑测试 + engine 回归**

Run: `python3 -m pytest tests/test_dl_flow_engine.py -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add dl_flow_engine.py tests/test_dl_flow_engine.py
git commit -m "feat(engine): judge spawn 走 profile+rubric skills 路径单点替换（qoder rubric 引 ~/.qoder/skills，P1 T6）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: dashboard 注入 cmd 走 profile（dl_dashboard/actions.py）

**Files:**
- Modify: `dl_dashboard/actions.py:209-225`（import 区 + inject cmd）
- Test: `tests/test_dl_dashboard_actions.py`（追加）

**Interfaces:**
- Consumes: `dl_engine.get_engine()`
- Produces: inject cmd 的 binary/perm/disallow_ask 按引擎

- [ ] **Step 1: 写失败测试**

```python
class TestInjectCmdDualEngine:
    def test_inject_cmd_qoder(self, monkeypatch):
        monkeypatch.setenv("DL_ENGINE", "qodercli")
        captured = {}

        class FakeProc:
            def __init__(self, cmd, **kw):
                captured["cmd"] = cmd
                self.stdout = iter([])
                self.returncode = 0

            def wait(self, timeout=None):
                return 0

        # 按 actions.py 实际 spawn 方式 monkeypatch（先 grep -n "Popen\|subprocess"
        # dl_dashboard/actions.py 核对），随后调 inject 入口到 cmd 构造为止；
        # 断言：
        assert captured["cmd"][0] == "qodercli"
        assert "accept_edits" in captured["cmd"]
        assert "--disallowedTools" not in captured["cmd"]
```

（该文件现有测试已有 inject 路径的 mock 模式——先 `grep -n "class.*Inject\|def test.*inject" tests/test_dl_dashboard_actions.py | head` 找到同构用例照抄其 mock 脚手架，只改引擎断言）

- [ ] **Step 2: 跑确认 FAIL**

- [ ] **Step 3: 改 cmd 构造**

```python
    eng = dl_engine.get_engine()
    cmd = [
        eng.binary, "--resume", sid,
        "--settings", str(meta / "settings.drive-tui.json"),
        "--append-system-prompt-file", str(meta / f"tui-rules.{nid}.md"),
    ]
    cmd += eng.permission_args()
    if ov["tools"]:
        tools = tuple(ov["tools"]) + ("TaskCreate", "TaskUpdate")
        cmd += ["--tools", ",".join(tools)]
    else:
        cmd += eng.disallow_ask_args()
```

（import 区加 `import dl_engine`——该文件已 import dl_flow_engine as engine，仓根在 sys.path）

- [ ] **Step 4: 跑测试 + dashboard actions 回归**

Run: `python3 -m pytest tests/test_dl_dashboard_actions.py -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add dl_dashboard/actions.py tests/test_dl_dashboard_actions.py
git commit -m "feat(dashboard): needuser 注入 cmd 走引擎 profile（P1 T7）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: dl-launch.sh 双引擎 + bashrc `dl @qoder`

**Files:**
- Modify: `scripts/workflow/dl-launch.sh`（引擎解析 + DEBUG_ARGS/PERM_ARGS/exec 3 处）
- Modify: `install.sh`（bashrc heredoc 的 `dl()` 函数 + 用法行）
- Test: `tests/test_dl_launch_engine.sh`（新建 bash 冒烟，或并入既有 launcher 测试——先 `ls tests/ | grep -i launch` 核对，无则新建）

**Interfaces:**
- Consumes: `DL_ENGINE` env
- Produces: `ENGINE_BIN`/`ENGINE_PERM`（launcher 内部变量）；bashrc 契约 `dl @qoder <name> [args]` = `DL_ENGINE=qodercli` 起工作流

- [ ] **Step 1: 写失败测试**

```bash
#!/bin/bash
# tests/test_dl_launch_engine.sh——launcher 引擎解析冒烟（不真起 TUI，只验变量解析段）
set -euo pipefail
LAUNCH=~/projects/dl-workflow-wt/qodercli-engine-profile/scripts/workflow/dl-launch.sh

# 引擎解析段独立可测：source 前截取（launcher 无库模式，改用文本级断言：
# 抽引擎 case 块单独 eval）
check() {
  local dl_engine="$1" expect_bin="$2" expect_perm="$3"
  local ENGINE_BIN ENGINE_PERM DL_ENGINE="$dl_engine"
  eval "$(sed -n '/^# ---------- 引擎/,/^esac/p' "$LAUNCH" | sed 's/exit 1/return 1/')"
  [ "$ENGINE_BIN" = "$expect_bin" ] || { echo "✗ DL_ENGINE=$dl_engine binary=$ENGINE_BIN"; exit 1; }
  [ "$ENGINE_PERM" = "$expect_perm" ] || { echo "✗ DL_ENGINE=$dl_engine perm=$ENGINE_PERM"; exit 1; }
}
check claude claude acceptEdits
check qodercli qodercli accept_edits
echo "✓ launcher 引擎解析双引擎正确"
```

- [ ] **Step 2: 跑确认失败**

Run: `bash tests/test_dl_launch_engine.sh`
Expected: FAIL（引擎解析块不存在，`sed` 抽不到）

- [ ] **Step 3: 改 dl-launch.sh**

在 `DEBUG_ARGS=()` 块之前插入：

```bash
# ---------- 引擎（DL_ENGINE：claude 默认 | qodercli；qodercli-engine-profile P1） ----------
# bashrc dl @qoder 入口置 DL_ENGINE=qodercli；未设=claude（现状逐位一致）。
# 未知值显式报错（no silent fallback）。bashrc 注释宣称的「不硬编码 claude」
# 间接层在此真接线（此前 dl-launch.sh:324/326 为字面 exec claude）。
DL_ENGINE="${DL_ENGINE:-claude}"
case "$DL_ENGINE" in
  claude)   ENGINE_BIN=claude;   ENGINE_PERM=acceptEdits ;;
  qodercli) ENGINE_BIN=qodercli; ENGINE_PERM=accept_edits ;;
  *) echo "✗ DL_ENGINE=$DL_ENGINE 未知引擎（claude|qodercli）" >&2; exit 1 ;;
esac
```

DEBUG_ARGS 块改为：

```bash
DEBUG_ARGS=()
if [ "$WF_DEBUG" = "1" ]; then
  if [ "$DL_ENGINE" = "qodercli" ]; then
    # qoder 无 --debug-file（P0 D2）；--debug 后日志自动落
    # ~/.qoder/logs/sessions/<proj>/<sid>/segments/*.jsonl
    DEBUG_ARGS=(--debug)
  else
    DEBUG_ARGS=(--debug api,hooks --debug-file "$WF_META_ROOT/$WF_NAME/cc_debug.log")
  fi
fi
```

PERM_ARGS 行：`PERM_ARGS=(--permission-mode "$ENGINE_PERM")`（注释块保留，末尾补一行「qoder 同理唯 CLI flag 生效——P0 实测 settings defaultMode 被忽略」）。

两条 exec 行的 `claude` → `"$ENGINE_BIN"`：

```bash
if [ "$WF_RESUME" = "1" ] && [ -n "${SESSION_ID:-}" ]; then
  exec "$ENGINE_BIN" --resume "$SESSION_ID" "${SETTINGS_ARGS[@]}" "${SYS_PROMPT_ARGS[@]}" "${DEBUG_ARGS[@]}" "${PERM_ARGS[@]}" "$@" 2>>"$WF_META_ROOT/$WF_NAME/cc_sdk.log"
else
  exec "$ENGINE_BIN" --session-id "$SESSION_ID" "${SETTINGS_ARGS[@]}" "${SYS_PROMPT_ARGS[@]}" "${DEBUG_ARGS[@]}" "${PERM_ARGS[@]}" "$@" 2>>"$WF_META_ROOT/$WF_NAME/cc_sdk.log"
fi
```

install.sh bashrc heredoc 的 `dl()` 改为：

```bash
# dl 命令：独立入口。@qoder = qodercli 引擎（子 shell 置 DL_ENGINE，不污染当前 shell）
dl() {
  [ $# -ge 1 ] || { echo "用法: dl [@qoder] <name> [--resume|--phase <p>|--base <ref>|--debug|--done] | list" >&2; return 1; }
  if [ "$1" = "@qoder" ]; then
    shift
    [ $# -ge 1 ] || { echo "用法: dl @qoder <name> [args...]" >&2; return 1; }
    ( export DL_ENGINE=qodercli; _dl_launch "$@" )
    return
  fi
  _dl_launch "$@"
}
```

- [ ] **Step 4: 跑冒烟 + bash -n 语法检查**

Run: `bash tests/test_dl_launch_engine.sh && bash -n scripts/workflow/dl-launch.sh && bash -n install.sh && echo OK`
Expected: `✓ launcher 引擎解析双引擎正确` + OK

- [ ] **Step 5: Commit**

```bash
git add scripts/workflow/dl-launch.sh tests/test_dl_launch_engine.sh
git commit -m "feat(launch): dl-launch 双引擎——DL_ENGINE 解析+ENGINE_BIN/PERM 贯通 exec，DL_CLAUDE 间接层真接线（P1 T8）

Co-Authored-By: Claude <noreply@anthropic.com>"
git add install.sh
git commit -m "feat(install): bashrc dl() 加 @qoder 入口——子 shell 置 DL_ENGINE=qodercli（P1 T8）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

> ⚠️ 现役 `~/.bashrc` 的 dl 段是 install.sh 历史写入的——本任务只改 heredoc 真源；收口 merge 后需重跑 `~/.dl-workflow/install.sh`（幂等更新 bashrc 段）或人工同步该函数，在 Task 11 验收清单执行。

---

### Task 9: settings 写出 3 处引擎分支

**Files:**
- Modify: `scripts/workflow/dl-lib.sh`（`wf_write_settings` 261-360）
- Modify: `install.sh`（`--engine` 参数 + copies/merge_settings 目标根参数化）
- Modify: `scripts/setup/setup_project.py`（`--engine` 参数 + 资源目录）
- Test: `tests/test_setup_project.py`（追加）、`tests/test_dl_launch_engine.sh`（追加 wf_write_settings 断言）

**Interfaces:**
- Consumes: `DL_ENGINE` env；`DL_QODER_MODEL` env（可选——qoder 引擎的 per-wf settings `model` 键，未设=用 qoder 账号默认模型即向导所选）
- Produces:
  - `wf_write_settings <name>`：qoder 引擎时 settings.json 增 `"model"` 键（仅 `DL_QODER_MODEL` 设值时）+ 注释化保留 `defaultMode: acceptEdits`（qoder 忽略该键，P0 实测；CLI flag 承重）
  - `install.sh --engine qodercli`：copies+hooks 注册目标 = `~/.qoder`
  - `setup_project.py --engine qodercli`：项目 settings 目标 = `<项目>/.qoder/settings.json`

- [ ] **Step 1: 写失败测试**

tests/test_setup_project.py 追加：

```python
class TestProjectSettingsDualEngine:
    def test_qoder_targets_dot_qoder(self, tmp_path):
        proj = tmp_path / "proj"
        (proj / ".git" / "hooks").mkdir(parents=True)
        from setup_project import merge_project_settings  # import 路径照该文件现写法
        merge_project_settings(proj, Path("/home/admin/.dl-workflow"), engine="qodercli")
        assert (proj / ".qoder" / "settings.json").exists()
        assert not (proj / ".claude" / "settings.json").exists()
        s = json.loads((proj / ".qoder" / "settings.json").read_text())
        cmds = [h["command"] for g in s["hooks"]["UserPromptSubmit"] for h in g["hooks"]]
        assert any("codegraph_inject.py" in c for c in cmds)

    def test_default_engine_unchanged(self, tmp_path):
        proj = tmp_path / "proj"
        (proj / ".git" / "hooks").mkdir(parents=True)
        from setup_project import merge_project_settings
        merge_project_settings(proj, Path("/home/admin/.dl-workflow"))
        assert (proj / ".claude" / "settings.json").exists()
```

tests/test_dl_launch_engine.sh 追加：

```bash
# wf_write_settings 引擎分支（qoder + DL_QODER_MODEL 时写 model 键）
export WF_META_ROOT="$(mktemp -d)" WF_REPO_ROOT=/tmp WF_LIB_DIR="$PWD/scripts/workflow"
export WF_SETTINGS_TEMPLATE_VERSION=1
source scripts/workflow/dl-lib.sh
DL_ENGINE=qodercli DL_QODER_MODEL=deepseek/deepseek-v4-flash-pg wf_write_settings engtest
python3 -c "
import json
s = json.load(open('$WF_META_ROOT/engtest/settings.json'))
assert s['model'] == 'deepseek/deepseek-v4-flash-pg', s.get('model')
assert s['permissions']['defaultMode'] == 'acceptEdits'  # qoder 忽略但 claude 引擎同文件兼容
assert any('workflow_phase.py' in h['command'] for g in s['hooks']['UserPromptSubmit'] for h in g['hooks'])
print('✓ wf_write_settings qoder 分支正确')
"
```

- [ ] **Step 2: 跑确认失败**

Run: `python3 -m pytest tests/test_setup_project.py::TestProjectSettingsDualEngine -q && bash tests/test_dl_launch_engine.sh`
Expected: FAIL（`merge_project_settings()` 无 engine 参数；settings 无 model 键）

- [ ] **Step 3: 改 3 处**

`setup_project.py`：

```python
# argparse 区加：
parser.add_argument("--engine", choices=["claude", "qodercli"], default="claude",
                    help="目标引擎：决定项目资源目录（.claude | .qoder）")

# merge_project_settings 签名与首行改为：
def merge_project_settings(project: Path, home: Path, engine: str = "claude") -> dict:
    """项目 settings.json 幂等合并两条 inject hook（按 hook 脚本 basename 判重）。
    engine=qodercli 时目标目录 .qoder（P1；hook 注册内容不变——
    hooks 路径引用 ~/.dl-workflow 与引擎无关）。"""
    resource_dir = ".qoder" if engine == "qodercli" else ".claude"
    settings_path = project / resource_dir / "settings.json"
# （main 里调用处传 engine=args.engine；docstring 用法行补 --engine）
```

`dl-lib.sh` `wf_write_settings` 的 JSON heredoc 头部（`cat > "$dir/settings.json" <<JSON` 之后）改为：

```bash
  # qoder 引擎附加 model 键（DL_QODER_MODEL 设值时）——per-wf settings 经
  # --settings 传入每个段/judge，模型选择随文件走不依赖账号默认
  local model_line=""
  if [ "${DL_ENGINE:-claude}" = "qodercli" ] && [ -n "${DL_QODER_MODEL:-}" ]; then
    model_line="\"model\": \"${DL_QODER_MODEL}\","
  fi
  cat > "$dir/settings.json" <<JSON
{
  "wf_settings_template_version": ${WF_SETTINGS_TEMPLATE_VERSION:-0},
  ${model_line}
  "outputStyle": "workflow",
  ...
```

（`permissions.defaultMode` 保持 `acceptEdits` 不变，该行上方加注释：`qoder 忽略 settings defaultMode（P0 实测两拼写 init=default）——权限唯 CLI flag 承重，dl-launch PERM_ARGS 已钉；此值供 claude 引擎`。WF_SETTINGS_TEMPLATE_VERSION +1——先 `grep -n "WF_SETTINGS_TEMPLATE_VERSION" scripts/workflow/dl-lib.sh | head -3` 核对当前值）

`install.sh`：

```bash
# 参数解析区加：
ENGINE=""
#   case 分支加：
#   --engine) ENGINE="$2"; shift 2 ;;  （按现有解析风格；--engine=qodercli 形式也接）

# copies + merge_settings 抽成函数（逻辑逐字搬，目标根参数化）：
install_to_home() {
  local target_home="$1"
  # 原 copy_with_backup 3 行（skill/output-style/command）+ merge_settings，
  # 其中 CLAUDE_HOME 引用换成 target_home
}

# 主流程：
install_to_home "$CLAUDE_HOME"   # claude 永远装（现状不变）
if [ "$ENGINE" = "qodercli" ]; then
  QODER_HOME="${QODER_CONFIG_DIR:-$HOME/.qoder}"
  install_to_home "$QODER_HOME"
  cat <<EOF
✓ qodercli 引擎已接线到 $QODER_HOME
  后续三步人工项（P0 D8/D10）：
  ① 认证：qodercli login（或 export QODER_PERSONAL_ACCESS_TOKEN）
  ② BYOK：TUI 跑 qodercli → /model → Custom → Add custom model 注册一次
     （服务端校验，手写 settings 只过本地解析、调用会被拒）
  ③ 项目目录首次进 TUI 确认 Trusted Workspace（不受信目录不加载项目级
     settings/hooks/AGENTS.md）
EOF
fi
```

- [ ] **Step 4: 跑测试 + bash 语法检查**

Run: `python3 -m pytest tests/test_setup_project.py -q && bash tests/test_dl_launch_engine.sh && bash -n install.sh && bash -n scripts/workflow/dl-lib.sh && echo OK`
Expected: 全 PASS + OK

- [ ] **Step 5: 分 3 commit（H9）**

```bash
git add scripts/setup/setup_project.py tests/test_setup_project.py
git commit -m "feat(setup): setup_project --engine——qoder 项目 settings 落 .qoder/（P1 T9）

Co-Authored-By: Claude <noreply@anthropic.com>"
git add scripts/workflow/dl-lib.sh tests/test_dl_launch_engine.sh
git commit -m "feat(lib): wf_write_settings qoder 分支——DL_QODER_MODEL 写 model 键+defaultMode 限制注释（P1 T9）

Co-Authored-By: Claude <noreply@anthropic.com>"
git add install.sh
git commit -m "feat(install): --engine qodercli——copies/hooks 注册目标 ~/.qoder+BYOK/trust 人工项提示（P1 T9）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: doctor.py 引擎就绪探测

**Files:**
- Modify: `bin/doctor.py`（加 `check_engine`）
- Test: `tests/test_doctor.py`（追加）

**Interfaces:**
- Consumes: `dl_engine.get_engine()`
- Produces: `check_engine() -> list[tuple[bool, str]]`——(是否通过, 检查描述)，由 doctor 主流程收集打印（接该文件现有检查项的同款汇总模式）

- [ ] **Step 1: 写失败测试**

```python
class TestCheckEngine:
    def test_claude_binary_present(self, monkeypatch):
        monkeypatch.delenv("DL_ENGINE", raising=False)
        from doctor import check_engine  # import 照该文件现写法
        results = dict(check_engine())
        # claude 已装环境应过；断言键存在即可（机差异不钉布尔值）
        assert any("claude" in k for k in results)

    def test_qoder_byok_unregistered_warns(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DL_ENGINE", "qodercli")
        monkeypatch.setenv("QODER_CONFIG_DIR", str(tmp_path))  # 空目录=无 settings.json
        from doctor import check_engine
        results = check_engine()
        byok = [ok for ok, msg in results if "BYOK" in msg]
        assert byok and byok[0] is False  # 未注册 → False（warn 级由主流程定）
```

- [ ] **Step 2: 跑确认 FAIL**（`check_engine` 不存在）

- [ ] **Step 3: 实现**

```python
def check_engine() -> "list[tuple[bool, str]]":
    """引擎就绪检查（qodercli-engine-profile P1 T10）。

    ① DL_ENGINE 声明引擎的 binary 在 PATH；② qoder 引擎加查 BYOK 注册态
    （~/.qoder/settings.json 含 apiKey 字段 = 向导注册过；P0 D8：手写
    customModels 只过本地解析、调用被云端拒，必须 TUI 向导注册）。
    """
    import shutil

    import dl_engine

    eng = dl_engine.get_engine()
    results = [(shutil.which(eng.binary) is not None, f"引擎 binary {eng.binary} 在 PATH")]
    if eng.name == "qodercli":
        settings = eng.config_root / "settings.json"
        has_byok = settings.exists() and '"apiKey"' in settings.read_text(
            encoding="utf-8", errors="replace"
        )
        results.append(
            (has_byok, f"BYOK 已向 TUI 向导注册（{settings}）——未注册则 /model Custom 向导注册一次")
        )
    return results
```

（接进 doctor 主流程的现有检查列表——`grep -n "checks\|results" bin/doctor.py | head` 找汇总点照加一行）

- [ ] **Step 4: 跑测试**

Run: `python3 -m pytest tests/test_doctor.py -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add bin/doctor.py tests/test_doctor.py
git commit -m "feat(doctor): 引擎就绪探测——binary on PATH+qoder BYOK 注册态（P1 T10）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 11: 验收（回归 + golden + 双引擎对账）

**Files:** 无改动（纯验证）

- [ ] **Step 1: 全量测试套件**

Run: `cd ~/projects/dl-workflow-wt/qodercli-engine-profile && python3 -m pytest tests/ -q 2>&1 | tail -3`
Expected: 全 PASS（通过数 ≥ main 基线——先 `git stash -u; git checkout main; python3 -m pytest tests/ -q 2>&1 | tail -1; git checkout -` 取基线对照）

- [ ] **Step 2: claude 路径逐位一致 golden 复核**

Run: `DL_ENGINE= python3 -m pytest tests/test_dl_engine.py tests/test_dl_drive.py tests/test_workflow_advance.py -q`
Expected: 全 PASS（golden 用例锁定 claude cmd 碎片/Stop 输出/regex 与现状一致）

- [ ] **Step 3: qoder 端到端冒烟（人工在场，BYOK 走 DeepSeek 计费）**

```bash
# 0. 前置：~/.qoder/settings.json 默认模型已是 BYOK（或 export DL_QODER_MODEL=deepseek/deepseek-v4-flash-pg）
# 1. 探针 git 仓
cd /tmp && rm -rf dl-qoder-smoke && mkdir dl-qoder-smoke && cd dl-qoder-smoke && git init -q && echo 'print(1)' > a.py && git add a.py && git commit -qm init
# 2. qoder 引擎起一个测试工作流（front TUI 模式，人工观察）
dl @qoder smoketest
```

预期观察（逐条勾）：
- [ ] per-wf settings.json 生成且 hooks 注册指向 ~/.dl-workflow/hooks
- [ ] TUI 起的是 qodercli，init permissionMode=acceptEdits
- [ ] UserPromptSubmit 注入「## WORKFLOW 当前阶段」进上下文（模型可见）
- [ ] statusLine 显示工作流阶段
- [ ] 完成 u:1#1 后 Stop hook 推进（.wf_advance.log 有记录，续轮经 reason 通道）
- [ ] judge 调用走 qodercli（evidence gate 裁决落盘）
- [ ] drive-stream.jsonl / segment_stats.jsonl 落盘；usage 全零处显示 N/A 不报错

- [ ] **Step 4: 收口准备——设计文档验收节回填结果**

把 Step 1-3 结果回填 `designs/qodercli-engine-profile-design.md` §5 验收（逐项标 ✅/❌+证据指针），commit：

```bash
git add designs/qodercli-engine-profile-design.md
git commit -m "docs(designs): P1 验收回填——回归/golden/qoder 端到端对账结果（P1 T11）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

- [ ] **Step 5: merge 回 main + 现役环境刷新（用户确认后）**

```bash
cd ~/.dl-workflow && git merge feat/qodercli-engine-profile --no-ff
git worktree remove ~/projects/dl-workflow-wt/qodercli-engine-profile
~/.dl-workflow/install.sh   # 幂等刷新 bashrc dl 段（@qoder 入口生效）
~/.dl-workflow/install.sh --engine qodercli  # 装 qoder 引擎面（copies+hooks 注册到 ~/.qoder）
```

---

## Self-Review 记录

- **Spec 覆盖**：设计 §4 P1 改造点 9 条 ↔ T1/T5/T6/T7/T8/T9/T3/T4/T2 全映射；P2 三条 ↔ T8(bashrc)/T9(install --engine)/T9(uninstall 对称=install_to_home 复用，uninstall.sh 改动并入 T9 Step 3 同函数化) ⚠️ uninstall.sh 未单列——install.sh 函数化后 uninstall 的对称改动若超 H9 限额，在 T9 Step 5 追加第 4 个 commit（`uninstall.sh` 单文件）。§5 验收 ↔ T11。
- **Placeholder 扫描**：T2 Step 1 inject 测试标注了「核对后补」——执行时先读代码再定断言形式（模块级常量 vs 函数）；T7 测试的 mock 脚手架标注照现有同构用例。两处均为「先核对现行代码」型指令，非内容空缺。
- **类型一致性**：`EngineProfile` 字段/方法名在 T1 定义，T5/T6/T7/T9/T10 消费一致；`eng.debug_args(Path)` 签名一致；`merge_project_settings(engine=)` 关键字参数一致。
