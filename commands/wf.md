---
description: 工作流阶段控制 - 用法 /wf next|back|jump <phase>|status|gate|done
---

运行工作流控制脚本。参数透传给 `$ARGUMENTS`。

**dl-workflow 版本**：脚本在用户级 `~/.dl-workflow/scripts/workflow/wf-cmd.sh`，不再从当前项目取（项目已不存放此脚本）。脚本自己会用 `git rev-parse --git-common-dir` 反查项目根，找到主仓库的 `.claude/workflows/<name>/state.json`。

请执行：

```bash
bash "$HOME/.dl-workflow/scripts/workflow/wf-cmd.sh" $ARGUMENTS
```

根据脚本输出向用户说明阶段变化。若输出含闸门提示，提醒用户 `/wf gate` 放行。
