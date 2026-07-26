# dl-workflow

Claude Code 5 阶段工作流 + codegraph H15 查证门禁的独立仓库。**跨项目通用**，装到 `~/.claude/` 后任意 git 项目内可用。

## 是什么

两套工具，都是 Claude Code 的通用扩展（不是任何单一项目的领域代码）：

1. **5 阶段工作流**（`dl <name>`）
   - 阶段：理解和求证问题 -> 生成执行计划 -> 执行 -> 审核结果 -> 进化
   - 每个工作流独立 git worktree + 分支 + session，可恢复
   - 阶段自动推进 + 闸门（`/dl gate`），原生 TaskList 常驻进度清单

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
- copy `commands/dl.md` -> `~/.claude/commands/`（同上）
- 合并 `~/.claude/settings.json` 的 hooks 注册（幂等，已存在跳过）
- 追写 `~/.bashrc`：`export DL_WF_HOME` + `dl` 函数（工作流入口，独立于 ac-ark/claude）

> 为什么 hooks 不 copy 而 skills 要 copy？`settings.json` 的 hook command 是自由字符串（任意路径）；但 skills/output-styles/commands 的加载路径是 Claude Code 硬编码的 `~/.claude/{skills,output-styles,commands}/`，必须物理在那。

冲突文件会备份到 `~/.claude/.dl-workflow-backup/<timestamp>/`。

## 环境配置（understand:1 子3 双向取证的外部证据源）

子3「双向取证」（`designs/step3-verify-redesign-design.md`，v2.7）走五层免费源取证：学术（OpenAlex/arXiv）、社区（StackExchange/HN）、开源（GitHub API）、定点网页（WebFetch）、内部仓库（codegraph）。**禁用 tavily_search/WebSearch**。除 GitHub 外全部零 key 即用（curl 直连）；GitHub 在共享出口 IP 下未认证额度不可靠，需配 PAT：

1. **创建 PAT**：github.com → Settings → Developer settings → Personal access tokens → Fine-grained → Repository access 选 **Public Repositories (read-only)**（或 classic token 不勾任何 scope）。
2. **全局生效**（launcher `exec claude`，env 由调用方 shell 继承——一处 export 全链生效）：
   ```bash
   echo 'export GITHUB_TOKEN=<粘贴PAT>' >> ~/.bashrc
   exec bash   # 或重开终端
   ```
3. **验证**：`curl -s -H "Authorization: Bearer $GITHUB_TOKEN" https://api.github.com/rate_limit` → `core.limit == 5000`。
4. **纪律**：token 只用 read-only public scope；不写入任何 repo 文件 / evidence / design 文档；泄露即 revoke。
5. **可选**：`SEMANTIC_SCHOLAR_API_KEY`（免费申请，学术层提额）同样 export 到 `~/.bashrc`；不配置用共享池，够用。

## 用

两种入口（都拦 `--dl` 参数转交 launcher）：

```bash
dl demo                        # 独立 dl 命令
ac-ark --dl demo               # 你的 provider 函数（在 ac-ark 里加 --dl 拦截，见下）

# 通用参数（接在 <入口> <name> 后）
dl demo --resume               # 续接
dl demo --phase execute         # 跳阶段
dl demo --base <ref>            # 指定基线
dl demo --done                  # 归档（删 worktree + 分支 + 元数据）
dl list                         # 列举所有工作流
```

**provider env 怎么带上**：launcher 永远 `exec` 原生 `claude`，env 由调用方 shell 继承。
- `ac-ark --dl demo`：ac-ark 函数已 export ark env，launcher 子进程继承，claude 走 ark ✓
- `dl demo`：用当前 shell env（默认或你 `export` 的）

> 为什么不是 `dl @provider` 或 `claude --dl`？provider 若是 bashrc 函数，launcher 子进程 `exec` 不到（函数只在交互 shell 存在）。改成「provider 调 launcher」而非「launcher 调 provider」：ac-ark 在交互 shell 里设好 env 再调 launcher，env 天然继承。`claude --dl` 需要覆盖原生 `claude` 为函数，侵入性大，故不提供。

**让 `ac-ark --dl` 生效**：在你 ac-ark 函数里加 `--dl` 拦截（见 `dl-shim.sh` 注释模板），或直接：
```bash
ac-ark() {
  export ANTHROPIC_BASE_URL=...
  # ... 其他 env
  if [ "$1" = "--dl" ]; then
    shift
    "$HOME/.dl-workflow/scripts/workflow/dl-launch.sh" --workflow "$@"
    return $?
  fi
  claude "$@"
}
```

# 会话内
/dl status                            # 看当前阶段
/dl next                              # 推进（闸门阶段先 /dl gate）
/dl back                              # 回退
/dl jump <phase>                      # 跳（phase 为英文标识：understand/plan/execute/review/evolution）
/dl gate                              # 放行闸门
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
├── commands/dl.md            -> copy 到 ~/.claude/commands/
├── scripts/workflow/         (LIB_DIR 自定位，不 copy)
│   ├── dl-launch.sh / dl-lib.sh / dl-cmd.sh / phase-rules.md
├── designs/                  (真源设计文档)
└── tests/test_codegraph_gate.py
```

## 演进

本仓库记录 workflow + codegraph H15 的独立演进。bug 修复和新增功能在此提 PR，不再在业务项目里改。

版本：见 `VERSION`。
