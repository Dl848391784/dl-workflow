# worktree-per-session 并发开发：user 级 gate 泛化跳过 linked worktree

> 2026-08-05。用户决议（AskUserQuestion 三选一：worktree-per-session / 单树+纪律 /
> 只写协议，选了 worktree-per-session）。起因=plan:3#2 泛化会话的改动被并行会话
> `git add -A` 席卷（collab #9 违例第三实例：v2.79/v2.88/本次），根因=**分支指针
> 不隔离工作目录**，并发会话共享 ~/.dl-workflow 单工作树。

## 1. 问题：分支救不了共享工作目录

`git branch` 只管理提交历史分叉，不隔离工作文件。单仓库单工作目录下，所有会话读写
同一份文件：两边 hunk 堆在同一文件里，一方 `git add` 整文件入库即把对方改动一起
带走（`9fea4a1` 同含 plan:3#1 与 plan:3#2 两个 gate = 直接证据）。

团队式「每人拉分支、上线合并」能成立的前提是**每人有自己的 checkout**。为此引入
worktree-per-session：每个并发会话 `git worktree add <独立目录> -b feat/<节点>`，
各改各的目录，收口时在主树 merge。

## 2. 死锁根因：codegraph/design gate 不认用户级 worktree

gate（user 级 PreToolUse，`~/.claude/settings.json` 引用 `~/.dl-workflow/hooks/*.py`）
对 worktree 会话的跳过条件现状：

```python
if _workflow_name(_payload_cwd(payload)) is not None:
    return 0
```

`_workflow_name` 只匹配路径含 `.claude/worktrees/<name>` 的目录（factor_ic_analyzer 的
`dl <name>` worktree 约定）。**dl-workflow 自己的 worktree**（`git worktree add` 手动建，
路径如 `~/.dl-workflow-wt-<name>`）不匹配 → gate 不跳过。

而 `.codegraph/` 与 `tests/replays/.token` 均 gitignore，worktree 里没有 → codegraph
gate 的「跑一次查询留痕即放行」在 worktree 里**跑不了查询解锁=死锁**：改 .py 前永远
被 exit 2 阻断。design_gate 同理（多文件改动的 design.md 解锁链在 worktree 内正常，
但其 worktree 跳过面同样窄）。

## 3. 方案：跳过条件泛化为「任何 linked worktree」

新增 `_is_linked_worktree(cwd)`：从 cwd 逐级向上找最近的 `.git`——

- `.git` 是**目录** → 主树（本仓库的主 checkout）→ 不跳过，gate 照常；
- `.git` 是**指针文件**（内容 `gitdir: <path>`）→ linked worktree → 跳过。

```python
def _is_linked_worktree(cwd: str) -> bool:
    """cwd 位于 git linked worktree（非主树）-> True。

    主树 .git=目录；linked worktree 的 .git=指针文件。2026-08-05 泛化
    （worktree-per-session 并发）：用户级 worktree 路径不匹配
    .claude/worktrees/<name> 约定，但 .codegraph db 同样 gitignore 缺失=
    同样的死锁，须同跳。子模块的 .git 也是指针文件——同理由成立（db 同样
    缺失），一并跳过，无实际副作用（本项目无子模块）。
    """
    d = Path(cwd)
    for parent in (d, *d.parents):
        git = parent / ".git"
        if git.exists():
            return git.is_file()
    return False
```

两 gate 跳过条件改为：

```python
if _workflow_name(_payload_cwd(payload)) is not None or _is_linked_worktree(
    _payload_cwd(payload)
):
    return 0
```

- codegraph_audit（PostToolUse）**不改**：gate 不拦则 audit 留痕无意义；audit 本身无
  阻断语义，不构成死锁。
- 泛化理由与既有决议一致（2026-08-03「codegraph 和 design_gate 对 worktree 都不拦」
  的根因是 worktree 里 db 缺失=死锁，该根因对所有 linked worktree 成立）。
- 边界：若将来有人在 worktree 里手动 `codegraph sync` 出 db 且想要 gate 生效，可再按
  db 在场与否细判——现按「宁纵勿枉 + 一致性」全跳，design 阶段不过度设计。

## 4. 改动文件（H8 范围）

| 文件 | 改动 |
|---|---|
| `hooks/codegraph_gate.py` | 新增 `_is_linked_worktree` + 跳过条件 OR |
| `hooks/design_gate.py` | 同上 |
| `tests/test_codegraph_gate.py` | 新增 linked worktree 跳过端到端测例 |
| `tests/test_design_gate.py` | 同上 |
| `skills/workflow-creation/references/collab.md` | 协议：worktree-per-session 启动/合并步骤 + .token 复制 |

## 5. 测试

端到端 subprocess（同现有 harness）：临时 git repo 建一个 commit → `git worktree add`
出 linked worktree → worktree 内放已存在 .py → 喂 payload（cwd=worktree、零查询）→
期望 exit 0（跳过，不阻断）。对照组：主树内编辑 → 期望 exit 2（阻断）。

## 6. 冒烟

真实 `git worktree add /home/admin/.dl-workflow-wt-smoke -b feat/smoke` → 在该目录建
一个 .py → 直调 gate 喂 payload → 期望 0；再在主树建同文件 → 期望 2。之后删 worktree。

## 7. 并发协作协议（落 collab.md 摘要）

1. 每会话 `git worktree add <独立目录> -b feat/<节点>`，会话 cwd 指向该目录。
2. 复制 `tests/replays/.token` 到 worktree 内（gitignore 不随 checkout 带过来）。
3. 收口：`cd ~/.dl-workflow && git merge feat/<节点> && git worktree remove <目录>`。
4. 版本号/例数规则不变（collab #13/#20：git log + 工作区自称双复核）。
