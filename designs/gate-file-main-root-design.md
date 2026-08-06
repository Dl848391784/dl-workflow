# 门禁按文件主树判定设计（v2.120）

> 恢复 2026-08-03 用户决议「dl-workflow repo 本身要拦」（`design_gate.py:31-36`
> 注释在案）——2026-08-05 worktree-per-session 泛化（`_is_linked_worktree`）
> 把所有 linked worktree 一刀切跳过，无意中推翻了该决议；2026-08-06 用户重申
> 策略并拍板本修复。

## 用户策略（2026-08-06 拍板，三分类按**仓的身份**而非「是不是 worktree」）

| 场景 | 处置 | 理由 |
|---|---|---|
| dl 工作流为项目建的 worktree（`*/.claude/worktrees/<name>`） | 跳过 | 工作流自带 codegraph/design 纪律（plan:1 新鲜度前置 + render-artifact 产 design.md），门禁冗余且误拦 execute |
| dl-workflow 仓本身（主树 + `~/.dl-workflow-wt-*` 开发 worktree） | **拦截** | H15/H8 纪律适用于本仓；本仓主树有 codegraph db 与 designs/ |
| 其他仓的 linked worktree（手工 git worktree add） | 维持跳过 | 2026-08-06 用户拍板：最小改动，纪律另有归属 |

## 现状三处断点（2026-08-06 实证）

1. **skip 判据按会话 cwd 不按被编辑文件**（`codegraph_gate.py:220` / `design_gate.py:162`）——跨仓编辑（会话开在 A 仓、改 dl-workflow worktree 文件）时 `_is_linked_worktree(cwd)` 看不到目标文件的仓身份，拦不拦全凭会话碰巧开在哪（v2.113 + 2026-08-06 两次实锤）；
2. **2026-08-05 泛化过度跳过**：dl-workflow 开发 worktree 会话（cwd=worktree）改本仓源码两个 gate 全跳过——直接违背 2026-08-03 决议；
3. **当初泛化的动机=死锁**（worktree 内无 `.codegraph` db、audit 目录与主树不一致）——真解不是跳过，是把 dl-workflow 场景的 project_root 解析到**主树**（db/audit/designs 全在主树，死锁根除）。

## 设计

### 统一判定原语（4 hook 各自内联同构拷贝，守现有 helper 重复模式）

```python
_DLWF_ROOT = Path(__file__).resolve().parent.parent  # hooks 由 settings 直引用
                                                    # ~/.dl-workflow/hooks/*.py（不 copy）

def _resolve_main_root(d: Path) -> tuple[Path | None, bool]:
    """d 所属仓的**主树**根 + d 是否在 linked worktree。
    git rev-parse --show-toplevel 得工作树顶 T；
    git rev-parse --git-common-dir 解析后 == T/.git -> 主树（False）；
    否则 common 的 parent 即主树根（True）。非 git -> (None, False)。"""

def _is_workflow_file(path: str) -> bool:
    """路径含 .claude/worktrees/<name> 段 -> dl 工作流 worktree 内文件。"""
```

### gate 两兄弟（codegraph_gate / design_gate）判定表

按**被编辑文件**（相对路径先对会话 cwd 解析）：
1. `_is_workflow_file(file_path)` → 跳过；
2. `_resolve_main_root(文件目录)` → None（非 git）→ 放行；
3. main_root == `_DLWF_ROOT` → **拦截**，project_root = 主树（db/audit/designs 落主树）；
4. is_linked（他仓 worktree）→ 跳过（维持）；
5. 其余（他仓主树）→ 拦截，project_root = main_root（现状行为不变）。

codegraph_gate 阻断文案按场景指路：dl-workflow 场景提示「在 `_DLWF_ROOT` 下跑
`codegraph impact <symbol>`」（开发 worktree 内无 db，CLI 须从主树跑）。

### audit 两兄弟落账对齐（gate 读哪，audit 落哪）

- `design_audit`（已是 file-based）：改落 main_root 的 `.claude/.design_audit`；
  跳过判据从 `_workflow_name(cwd)` 改 `_is_workflow_file(file_path)`（跨仓会话
  改工作流 worktree 文件同样不记账）；他仓 worktree 文件照记其主树（gate 不读，
  无害）。
- `codegraph_audit`（Bash 命令流，无 file_path 可用）：查询归属 = 命令前导
  `cd <dir> &&` 可解析则取该 dir 的 main_root，否则取会话 cwd 的 main_root
  （linked worktree 会话 → 主树）。覆盖三会话形态：主树会话 / 开发 worktree
  会话（`cd 主树 && codegraph` 或裸跑都归主树）/ 跨仓会话（cd 前缀归目标仓）。
  解析不了 cd 目标（非 git/变量路径）→ 回落会话 cwd（宁纵勿枉）。

### 不做（surgical 边界）

- 不改 `_session_id`（v2.69 会话隔离不动）；
- 不动白名单 `_is_existing_source_py` / `_is_source_py` / `_is_design_md`；
- 不动 4 个 workflow hook；codegraph CLI 本身不改（外部 npm，worktree 内跑不动
  由阻断文案指路解决）；
- 跨仓会话 codegraph 解锁只认「cd 前缀归属」，不做命令内任意路径推测。

### 文案同步

- dl-workflow `CLAUDE.md` 铁律「codegraph_gate / design_gate 对任何 linked
  worktree 跳过」→ 改为三分类表述；
- 两 gate 头部注释与 2026-08-05 泛化注释更新（注明被本设计取代+恢复 08-03 决议）。

## 验证

- TDD fixture：tmp git 仓 + `git worktree add` linked worktree + 伪 dl-workflow
  仓（monkeypatch `_DLWF_ROOT`）+ `.claude/worktrees/` 嵌套路径；
- codegraph_gate：dl-workflow 主树文件无 audit 拦/有 audit 放；dl-workflow
  worktree 文件拦 → 主树 audit 解锁（worktree 内无 db 不再是死锁）；工作流
  worktree 文件放；他仓 worktree 文件放；他仓主树文件维持拦；
- codegraph_audit：cd 前缀归属 / worktree 会话归主树 / 解析失败回落；
- design_gate/design_audit 镜像关键场景；
- **dogfooding**：merge 后在本会话（rooted 在 factor）再改 dl-workflow 源码 →
  必被拦 → `cd ~/.dl-workflow && codegraph` 解锁 = 链路通最硬实证（§3.6 #13）。
