# per-wf settings 补 Read 路径规则设计（v2.124 / settings 模板 v5）

> 2026-08-07。触发：tail_volume_acceleration_annualized acceptEdits 重跑实测。

## 问题

acceptEdits 只本地放行 Edit/Write，**不覆盖 Read**。工作流会话 cwd 在 worktree
内，而编排协议把 evidence/产物路径钉在主仓绝对路径（`<主仓>/.claude/**`，
2026-07-28 决议）——模型每次 Read 主仓 .claude/ 下的文件都弹权限窗
（2026-08-07 06:32:58Z 实测：Read `.claude/evidence/**` 弹窗，
permissionDecisionMs=28535 等用户点）。昨天的会话同类：`~/.dl-workflow/**`
读取弹窗被用户批准进 localSettings（主仓级，worktree 会话未必继承）。

## 方案

wf_write_settings 模板（dl-lib.sh）allow 补两条路径规则，与既有
`Edit(//<主仓>/.claude/**)` 同构：

```
"Read(//${WF_REPO_ROOT#/}/.claude/**)",   # 主仓 .claude 全树（evidence/plans/understands/...）
"Read(//${HOME#/}/.dl-workflow/**)",      # dl-workflow 真源（engine/nodes/skill 参考文件）
```

- 威胁模型不变（弱遵从非对抗，宽白名单可接受——模板注释既有原则）；Read 是
  只读工具，放行风险低于既有 Edit 路径规则。
- 模板实质内容变更 → bump engine `SETTINGS_TEMPLATE_VERSION` 4→5（唯一 bump 点）。
- 存量会话自愈通道既有：注入/`/dl status` 双通道警告 → `dl <name> --resume` 补写。

## 范围

- `scripts/workflow/dl-lib.sh`：+2 行规则 + 注释。
- `dl_flow_engine.py`：版本常量 4→5 + 注释。
- 无新测试（无测试钉 allowlist 内容；版本号为动态引用），全量回归。

## 验证

- 全量 pytest 绿。
- 下轮/当前会话 `--resume` 后：Read 主仓 .claude/ 不再弹窗（cc_debug.log 无
  `Permission suggestions for Read`）。

## v6 增量（2026-08-07 同日二次实证）

Bash 只读命令（find/grep）触及 cwd 外主仓路径时过**路径级检查**，命令头
白名单管不住——harness 对 `find /主仓 ...` 自建议 `Read(//主仓/**)`。
Read 规则从 `.claude/**` 放宽到主仓全树（只读，威胁模型不变）；
Edit 刻意不放宽——主仓源码编辑保持弹窗 = 守卫（编辑目标是 worktree）。
模板版本 5→6。

## v7 增量（2026-08-07 同日三次实证：两轮 transcript 全量命令头挖掘）

挖两轮真实运行的全部 Bash 调用做差集：路径形态调用（绝对/相对路径的
codegraph/venv python/pytest）不匹配裸命令头前缀规则 + 名单外常用头
（xargs/tr/comm/od/xxd/env/sleep）。补 13 条。刻意不加 rm/dd/sudo——
破坏性命令保留弹窗 = 弱模型幻觉刹车；正向名单可收敛（每新头永久一次），
Bash(*) + deny 是反向打地鼠。env 前缀形态规则语法不支持 = 已知残余。
模板版本 6→7。
