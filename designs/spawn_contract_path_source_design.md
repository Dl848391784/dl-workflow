# spawn 时 skill 契约校验 + dl-workflow 路径形态单源

> 2026-09-18。用户裁决的治本方案（两个「表面修复反复不根治」的收口）。改动范围：`dl_flow_common.py`（新单源）+ `dl_drive.py` + `hooks/workflow_step_fence.py` + `dl_flow_trace.py` + `dl_flow_engine.py` + `scripts/workflow/dl-lib.sh`（v15）+ 测试。

## A. Skill 激活死路治本——spawn 时契约校验

实证（用户查证 + 对照样本）：插件命名空间 skill（superpowers:x）预授信 headless 可激活；裸名 skill 在新 workspace 首激活需人工确认，headless 必死；allow 白名单管权限层救不了激活闸。

方案（在 7e3089b 内联基础上收口）：build_step_prompt 派发时按**目录枚举**（以运行时真实技能集为准，不认引擎声明）分三档：
- 插件命名空间 ref（含 `:`）→ 保持 invoke（实证可用）；
- 裸名 ref + 正文找到 → 内联全文（已落地，不变）；
- 裸名 ref + 正文**找不到** → 不再回退 invoke（那是死路）——降级为纯文本「按 purpose 引导执行 + 禁调 Skill 工具 + trace 注明降级」（模型被拒后本来就这么自救），driver 日志 warning。段不炸，不再烧激活闸轮次。

## B. 路径形态单源——dlwf_path_forms() 成对输出

实证：dev 仓库跑 driver 时 node-rules 落到绝对路径分支，白名单只有 ~ 形态，5 连拒。两个独立源头（展示文本 vs 白名单规则）无一致性约束。

方案：`dl_flow_common.dlwf_path_forms()` 唯一函数返回 `{display, allow_dlcmd, allow_engine}`——display 走软链等价归一（canonical/软链 → 字面 `~/.dl-workflow`，否则运行副本绝对路径），allow 规则**两形态恒全**（~ + 运行副本绝对）。消费方全改从它取：node-rules `_cb`、段 prompt deliverable（dl_drive.py 1756/1759）、fence 拒绝文案（694-697/721-724）、engine/trace 的 append-trace 指引文案、settings 白名单生成器（dl-lib.sh 补 dl_flow_engine.py 绝对形态，v15）。**一致性约束可执行化**：测试断言 display 导出的规则必在 wf_write_settings 生成的白名单内——结构上不可能再分叉。

## 验证

TDD：dlwf_path_forms 三布局（canonical/独立副本/软链）+ 白名单一致性集成断言 + skill 三档（插件 invoke/内联/降级文本+禁调）；全量 pytest + ruff + bash -n。
