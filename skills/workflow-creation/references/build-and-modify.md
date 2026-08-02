# 建工作流 / 改工作流

> workflow-creation skill 按需参考（自 SKILL.md §1.1–1.3 整体迁出，节号原样保留以兼容「§3.5 #9」式交叉引用）。
> 只在 SKILL.md 路由表命中时阅读。


### 1.1 新建一个工作流（用户侧）
两种入口（都拦 `--dl` 参数转交 launcher）：
```bash
dl <name>                 # 独立 dl 命令
ac-ark --dl <name>        # provider 函数（需在 ac-ark 里加 --dl 拦截，见 README）
# 通用参数
dl <name> --resume        # 续接
dl <name> --phase <p>     # 跳阶段
dl <name> --base <ref>    # 指定基线
dl list                   # 列举
dl <name> --done          # 归档（删 worktree+分支+元数据）
```
- `<name>` 仅小写字母/数字/连字符/下划线，≤64（`dl-lib.sh` 校验）。
- 必须在 git repo 内运行（launcher 用 `git rev-parse` 反查项目根）。
- provider env：launcher 永远 `exec claude`，env 由调用方 shell 继承。`ac-ark --dl` 因 ac-ark 已 export env 而走 ark；`dl` 用当前 shell env。不用 `@provider`（provider 是函数时 launcher 子进程 exec 不到）。

### 1.2 改工作流脚本/hook/command 后
- 改 `~/.dl-workflow/hooks/*.py` -> **无需 install.sh**（settings.json 直接引用源），下轮 hook 触发即最新版（无需重建 worktree）。
- 改 `dl_flow_engine.py` / `dl_flow_nodes.py` -> 同 hook：**对在跑实例即时生效**（hooks 运行时 import，区别于 phase-rules 的 launch 快照）——**改载荷契约/机械校验必须评估在跑实例兼容**（2026-08-02 v2.40 沉淀）：①**写侧硬拒新键**=自愈合——旧 purpose 指导下的模型不知新键，但报错文本指路，当轮补键重交即可；②**读历史 trace 的校验**（如 fetch_report_recorded 读子2 atomic_questions）必须对旧形态 trace 走 legacy 路径（无键→旧行为），否则在跑实例的旧 trace 永远过不了新校验=卡死。legacy 分支是版本兼容，不算 silent fallback（注释写明 + 测试 pinning）。
- 改 `~/.dl-workflow/output-styles/*.md` 或 `commands/*.md` 或 `skills/` -> 跑 `~/.dl-workflow/install.sh` copy 到 `~/.claude/`，再**重启会话**加载（output-style / slash command 在会话启动时载入）。
- 改 `~/.dl-workflow/scripts/workflow/*.sh` -> 无需 install（launcher 直接从 dl-workflow 内跑），下次 `dl <name> --resume` 或新建即最新。
- 改 `phase-rules.md`（append-system-prompt）-> 仅新开会话生效（append-system-prompt 是启动时载入）；已有会话不同步。**v2.12 起 phase-rules.md 是模板**：understand:1 的 6 条子步骤 purpose 段是 `<!-- BEGIN/END GENERATED sub_steps -->` 标记占位，launcher 每次启动调 `dl_flow_engine.py render-phase-rules` 渲染到 per-wf `phase-rules.rendered.md`（渲染失败中止启动）——**改 engine 的 Step.purpose 即自动同步双通道，新启动会话即生效，无需 install、无需手改 phase-rules**；phase-rules 静态部分（围栏/强制语义/完成标记）仍手维护。
- per-wf `settings.json`（在项目 `.claude/workflows/<name>/`，非快照）改了要重启会话加载。**生命周期与 phase-rules 相反（2026-07-30 审计踩坑）**：resume 只在 settings.json **缺失时**补写（dl-launch.sh `[ -f ... ] || wf_write_settings`）——改 `wf_write_settings` 模板（如 allowlist 扩展）后**存量工作流不自动跟进**，须在目标项目 repo 内手工刷新：`bash -c 'source ~/.dl-workflow/scripts/workflow/dl-lib.sh && wf_write_settings <name>'`（WF_META_ROOT 靠 cwd git 反查，勿在 dl-workflow 仓内跑）。对照：phase-rules.rendered.md 每次 launch/resume 重渲（改 engine purpose 即生效，见上条），无需手工。**v2.35 起有版本戳兜底**：engine `SETTINGS_TEMPLATE_VERSION` 单源，settings 盖章 `wf_settings_template_version`，workflow_phase 注入 + `/dl status` 双通道警告落后并指 `--resume`；**改 `wf_write_settings` 模板实质内容（allowlist/hooks/defaultMode）时必须 bump engine 常量**（唯一 bump 点），否则存量会话静默缴税无警告。

**与 v1.x 项目内嵌版本对比**：v1.x 里 hook 在 `<项目>/.claude/hooks/` 是 git 快照，改后必须 commit + 重建 worktree；本版本 hook 在 `~/.dl-workflow/hooks/` 直接引用（不 copy），无此约束。

### 1.3 关键文件职责（改前必读）
| 位置 | 文件 | 职责 |
|---|---|---|
| `~/.dl-workflow/scripts/workflow/` | `dl-launch.sh` | 建/续 worktree+state+settings，起 claude |
| ↑ | `dl-lib.sh` | 阶段定义 + state 读写 + `wf_write_settings` + 路径反查 |
| ↑ | `dl-cmd.sh` | `/dl` 子命令逻辑 |
| ↑ | `phase-rules.md` | append-system-prompt，各阶段行为规则 |
| `~/.dl-workflow/hooks/`            | `workflow_phase.py` | UserPromptSubmit 注入当前阶段 |
| ↑ | `workflow_advance.py` | Stop 检 PHASE_DONE 推进 + sub_steps 门控（evidence hash 触发） |
| ↑ | `workflow_step_fence.py` | PreToolUse S15 前置参与围栏（零 trace 白名单）+ S10 步骤围栏（未判决 trace 时 deny） |
| ↑ | `codegraph_gate.py` | PreToolUse H15 门禁（改已有 .py 前先查 codegraph） |
| ↑ | `codegraph_audit.py` | PostToolUse 记 codegraph 查询 |
| `~/.claude/output-styles/` | `workflow.md` | 横幅 + 常驻 TaskList 首要规则 |
| `~/.claude/commands/` | `dl.md` | `/dl` slash 命令入口（调 dl-workflow 内 dl-cmd.sh） |


### 1.4 增/改/废 `/dl` 子命令 checklist（2026-07-28 v2.22 state-reset 替代 step-reset 实证）

改「用户可见子命令」的完整改动面（比 §SKILL 不要做的事里的批量重命名 checklist 小一号，子命令级）：

1. `dl_flow_engine.py`：业务函数 + argparse `choices` + `if args.cmd ==` 分发（**废命令 = 直接删 choices 项**，旧命令撞 argparse usage 错，不留别名）。
2. `scripts/workflow/dl-cmd.sh`：case 分支 + **头部用法注释** + 末尾「未知子命令」提示串（三处易漏后两处）。
3. `commands/dl.md`：frontmatter description 用法串（/dl 帮助页唯一入口）。
4. 文案引用面 grep：`grep -rn "<旧命令名>" hooks/ scripts/ skills/ --include="*.py" --include="*.sh" --include="*.md"`——门栏/错误提示里引导用户调旧命令的文案全要换（phase-rules.md、workflow_phase.py、workflow_advance.py 是重灾区；**历史 designs/*.md 不换**，保持决策当时记录）。
5. `tests/`：旧命令用例改新命令 + 新语义新用例。
6. `install.sh` + **重启会话**（commands/*.md copy 才能注册新用法串）；hooks 文案源直引即生效，无需 install。

**engine 数据形态注意**：`Node.sub_steps` 无编排节点是 **`None` 不是 `[]`**——`len(node.sub_steps)` 直接 TypeError（v2.22 TDD 红阶段抓到），遍历/计长前必须 `node.sub_steps or []` 或 `if not node.sub_steps` 先判。
