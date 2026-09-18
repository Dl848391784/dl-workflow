# 根治疗效复核补洞（settings 自愈链 + phase-rules 形态 + pwd 物理路径）

> 2026-09-18。对 5fa1b11 的对抗性复核发现的三个残余缺口。改动范围：`scripts/workflow/dl-lib.sh` + `scripts/workflow/dl_drive.py` + `dl_flow_engine.py` + 测试。

## 复核发现的缺口

1. **settings 自愈链断裂**（v13/v14/v15 白名单到不了在飞实例）：`wf_settings_staleness_notice` 只警告（dl-cmd.sh:86），文案让跑 `--resume`，但 resume 分支只在 settings **缺失**时补写（dl-launch.sh:177）——警告指的路是断的；且 dashboard 的 restart_drive 直拉 dl_drive.py 不过 launcher，在飞实例的 settings 永不刷新。
2. **phase-rules 模板硬编码 ~ 形态**（`bash ~/.dl-workflow/.../dl-cmd.sh status` 等 3 处）：~ 形态在白名单内不会被拒，但 Mac 上命中的是 overlay 副本而非 driver 同码 clone——版本 skew 面。
3. **bash 侧 pwd 逻辑/物理不一致**：`$(cd ... && pwd)` 是逻辑路径（-L），路径含软链段时与 python 侧 resolve() 不一致——成对同源形同虚设。改 `pwd -P`。

## 方案

- `wf_settings_stale()`（exit code 判活）从 notice 拆出；resume 分支：缺失**或落后**即重写；driver 起跑新增 `_maybe_refresh_settings`（版本比对落后→bash wf_write_settings 补写）——dashboard 通道自此也自愈。
- `render_phase_rules` 渲染后把 `~/.dl-workflow` 字面量替换为 `dlwf_path_forms()["display"]`（canonical 下零变化）。
- `pwd -P` 物理路径对齐 python resolve。

## 验证

TDD：stale 判定/补写、driver 起跑刷新调用、phase-rules 替换；全量 pytest + bash -n。
