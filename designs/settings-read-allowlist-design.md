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
