# headless 段 skill 内联 + dl-cmd.sh 绝对形态白名单

> 2026-09-18。改动范围：`scripts/workflow/dl_drive.py` + `scripts/workflow/dl-lib.sh` + `dl_flow_engine.py`（版本戳 v14）+ 测试。

## 根因（Mac/qoder GLM 实爆复核）

1. **Skill 激活死路**（×4，allow:["Skill"] 无效）：「Activate skill?」确认是**交互闸不是权限层**——headless 一次性会话无人可答，权限白名单救不了。对齐症状 AL 哲学：无真人通道里交互闸必须结构性不存在。
2. **node-rules 仍发绝对路径**：`_dlwf_display_root` 的软链等价修复前提不成立——Mac 的 `~/.dl-workflow` 是 install.sh overlay **独立副本**（非软链），driver 跑在 `~/Documents/dl-workflow` clone，两路径无解析等价关系 → 仍发绝对路径 → 白名单字面 ~ 规则照拒。

## 方案

1. **skill 正文内联**：`build_step_prompt` 非交互分支（headless 段 + prep 段）把 `step.ref` 的 SKILL.md 正文直接嵌进 prompt（搜索序：项目/.claude/skills → ~/.claude/skills → ~/.qoder/skills，找不到回退 invoke 指引 + warning 落日志），禁调 Skill 工具；交互 TUI 段保持 invoke 不变。
2. **allowlist 双形态**：`Bash(bash ${WF_LIB_DIR}/dl-cmd.sh:*)` 绝对形态入白名单（与既有 dl_drive.py 绝对规则同先例），~ 形态保留；模板版本戳 v14（存量 settings 补写自愈）。规则文本继续发 ~ 形态（canonical），白名单两形态兜底任意安装布局。

## 验证

TDD 3 红转绿（headless 内联+禁调提示 / prep 内联 / allowlist 双形态）+ 全量 1629 绿 + ruff。教训留痕：JSON heredoc 内禁嵌 bash 注释（首轮实施踩坑，settings.json 非法 JSON）。
