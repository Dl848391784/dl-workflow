# dl-workflow

Claude Code 5 阶段工作流 + codegraph H15 查证门禁的独立仓库。**跨项目通用**，装到 `~/.claude/` 后任意 git 项目内可用。

## 是什么

两套工具，都是 Claude Code 的通用扩展（不是任何单一项目的领域代码）：

1. **5 阶段工作流**（`ac-ark --workflow <name>`）
   - 阶段：理解和求证问题 -> 生成执行计划 -> 执行 -> 审核结果 -> 进化
   - 每个工作流独立 git worktree + 分支 + session，可恢复
   - 阶段自动推进 + 闸门（`/wf gate`），原生 TaskList 常驻进度清单

2. **codegraph H15 查证门禁**
   - PreToolUse hook：改已有 `.py` 源码前必须先跑 codegraph 查证
   - PostToolUse hook：每次 codegraph 查询自动留痕
   - 弱门禁：挡「零查询就改源码」，不挡「查错 symbol」

## 装

```bash
git clone https://github.com/<你的>/dl-workflow.git ~/.dl-workflow
cd ~/.dl-workflow
./install.sh
exec bash   # 或重开终端
```

install.sh 做什么：
- **hooks 不 copy**：`~/.claude/settings.json` 里直接注册 `python3 ~/.dl-workflow/hooks/*.py`（shell 执行时 `~` 展开）。改 hook 后 `git pull` 即生效，无同步副本。
- copy `skills/workflow-creation/` -> `~/.claude/skills/`（Claude Code 硬编码只从这里加载 skill）
- copy `output-styles/workflow.md` -> `~/.claude/output-styles/`（同上）
- copy `commands/wf.md` -> `~/.claude/commands/`（同上）
- 合并 `~/.claude/settings.json` 的 hooks 注册（幂等，已存在跳过）
- 追写 `~/.bashrc`：`export DL_WF_HOME` + `ac-ark` 函数（若无自定义则装简版）

> 为什么 hooks 不 copy 而 skills 要 copy？`settings.json` 的 hook command 是自由字符串（任意路径）；但 skills/output-styles/commands 的加载路径是 Claude Code 硬编码的 `~/.claude/{skills,output-styles,commands}/`，必须物理在那。

冲突文件会备份到 `~/.claude/.dl-workflow-backup/<timestamp>/`。

## 用

```bash
ac-ark --workflow my-feature          # 新建工作流（停在「理解和求证问题」）
ac-ark --workflow my-feature --resume # 续接
ac-ark --workflow list                # 列举
ac-ark --workflow my-feature --done   # 归档（删 worktree + 分支 + 元数据）

# 会话内
/wf status                            # 看当前阶段
/wf next                              # 推进（闸门阶段先 /wf gate）
/wf back                              # 回退
/wf jump <phase>                      # 跳（phase 为英文标识：understand/plan/execute/review/evolution）
/wf gate                              # 放行闸门
```

codegraph H15 门禁**自动生效**——项目内有 `.codegraph/codegraph.db` 时才起作用。装 codegraph CLI：
```bash
npm i -g @orta/codegraph   # 或按 codegraph 官方指引
cd <你的项目>
codegraph sync             # 建索引，落到 .codegraph/codegraph.db
```

## 卸

```bash
cd ~/.dl-workflow && ./uninstall.sh
```

删装的文件 + 摘 settings.json 里的 hook 注册 + 清 ~/.bashrc 段落。

## 兼容与设计约束

- **project settings.json 里旧 hook 注册**：本仓库的 hook 注册在用户级 `~/.claude/settings.json`（command 直接引用 `~/.dl-workflow/hooks/*.py`，不 copy）。若你原来在项目里也注册过（`.claude/settings.json` 里的 `python3 .claude/hooks/...`），删掉项目那份 hook 注册，用用户级注册即可。
- **hook 反查项目根**：hook 从 payload 里的 cwd 用 `git rev-parse --git-common-dir` 反查主 repo 根（不再假设 `__file__.parents[2]`）。worktree 内也能正确定位主 repo 的 `.claude/workflows/<name>/state.json`。
- **改后生效**：改 hook 后 `git pull` 即生效（直接引用源，无副本）；改 output-style/commands/skill 后需 `install.sh` 重 copy；改 scripts 后下次起工作流即生效。per-wf settings 用 `~/.dl-workflow/hooks/` 路径，无需重建 worktree。
- **`codegraph_inject.py`**：**项目专属**（读项目 codegraph db 结构），不由 dl-workflow 管；由项目自己的 `.claude/settings.json` 单独注册。

## 目录

```
~/.dl-workflow/
├── README.md
├── install.sh / uninstall.sh
├── VERSION
├── hooks/                    -> settings.json 直接引用 ~/.dl-workflow/hooks/（不 copy）
│   ├── workflow_phase.py     (UserPromptSubmit 阶段注入)
│   ├── workflow_advance.py   (Stop 阶段推进)
│   ├── codegraph_gate.py     (PreToolUse H15 门禁)
│   └── codegraph_audit.py    (PostToolUse 留痕)
├── skills/workflow-creation/ -> copy 到 ~/.claude/skills/
├── output-styles/workflow.md -> copy 到 ~/.claude/output-styles/
├── commands/wf.md            -> copy 到 ~/.claude/commands/
├── scripts/workflow/         (LIB_DIR 自定位，不 copy)
│   ├── wf-launch.sh / wf-lib.sh / wf-cmd.sh / phase-rules.md
├── designs/                  (真源设计文档)
└── tests/test_codegraph_gate.py
```

## 演进

本仓库记录 workflow + codegraph H15 的独立演进。bug 修复和新增功能在此提 PR，不再在业务项目里改。

版本：见 `VERSION`。
