# fermate 自动完结设计（撤销 plan:2 门栏扣留）

> 2026-08-29 用户决议。修订 fermate-plan-only-design.md §2.2 的终态语义。
> 触发场景：web_ui_interaction（fermate+tacet）跑完 plan:2 后 held_for_gate
> 停等 /dl gate，用户指出「没必要等收货——plan-only 跑完就是完成态，
> 人工确认点应该在归档（/dl done），不在收货」。

## 0. 问题

fermate（plan-only）轨道原设计：plan:2 末步过门控后 `held_for_gate` 门栏
扣留，等用户 `/dl gate` 确认收货才置 `gate="done"` 完结。

问题：plan-only 场景下「收货确认」是冗余裁决点——

1. 交付物 plan.md 落盘后**随时可读**，不需要一个闸门来"允许"用户读它；
2. 不收货的处置（丢弃/重来）本身就是人工动作，不需要系统扣留来触发；
3. 系统已有真正的人工确认点 = **归档**（`/dl done`，删 worktree 不可
   逆，天然需要人工）；在收货处再设一道人工门 = 同一生命周期两个人工
   停顿点，第一个没有决策内容。

门栏扣留的存在意义是「后续动作不可逆/代价高，需人工把关口」。
plan:4 门栏（全量轨道）成立因为放行 = 进 execute 改代码；fermate 终点
放行 = 什么都不发生（仅置 done），把关对象不存在。

## 1. 新语义

**fermate 实例 plan:2 末步过门控 = 实例直接完结（`gate="done"`），无
held_for_gate、无 /dl gate 收货环节。** 人工介入点唯一 = `/dl done` 归档。

- 完结留痕：`write_gate_verdict(via="fermate-auto-complete", sub_step=末步)`，
  对齐手动放行必留痕原则（release_subgate 的 via="manual-subgate-pass"
  同款机制，只是 via 标识来源为机械自动完结）。
- driver 零改动：dl_drive.py 主循环本就以 `state.gate == "done"` 为退出
  条件（:2149），held_for_gate 断点分支（:2156）对新路径不再命中。
- 升级全量执行路径不变：`fermate off` + `/dl state-reset plan:2`（不受
  本改动影响）。

## 2. 改动点

### 2.1 dl_flow_engine.py

1. `node_holds_for_gate`：删 fermate 特判——判据回归 `node.hold_for_gate`
   单源（全量轨道 plan:4 唯一门栏，2026-07-28 用户决议不变）。
2. `_advance_sub_step`：末步且 `force_fermate + plan:2` 时，不写
   held_for_gate，改走终态分支：`write_gate_verdict(via="fermate-auto-complete")`
   → `state["gate"]="done"` 落盘返回（镜像 advance_state 的 next_node_id
   None 终态分支）。留痕写失败不阻断完结（write_gate_verdict 自身契约：
   失败返回 False 由调用方知悉，no silent fallback 由 evidence 缺失暴露）。
3. `release_subgate` 的 fermate 终态分支（:1692-1704）：**删除**（H13 死
   代码——node_holds_for_gate 不再对 fermate plan:2 成立，held 校验先
   失败，分支不可达）。在飞 held 实例由迁移路径处理（§3），不留兼容分支。
4. 文案：`set_force_fermate` 开关回显 + docstring、「plan 完成 held
   停等」相关注释同步新语义。

### 2.2 phase-rules.md（system-prompt，优先级最高，必同步）

FERMATE_ONLY 块三处（plan 章 :81、plan:2 子步骤末步注记 :106、速查行
:138）：「末步门栏扣留等 /dl gate 确认收货」→「末步过门控即实例完结
（gate=done），无门栏无 /dl gate；归档由用户 /dl done 决定」。

### 2.3 dl-launch.sh

- 头注释（:15）与 fermate 生效回显（:208）同步新语义。

### 2.4 测试（tests/test_dl_flow_engine.py TestForceFermate）

- `test_node_holds_for_gate_single_source`：fermate+plan:2 断言改 False。
- `test_advance_sub_step_fermate_plan2_holds` → 改自动完结断言：
  gate="done"、无 held_for_gate、phase/sub 停 plan:2、evidence 末笔
  via="fermate-auto-complete"；无 fermate 回归（正常进 plan:3）保留。
- `test_release_subgate_fermate_terminal`：删除（被测分支已删）；补一条
  回归：fermate+plan:2 无 held 时 release_subgate 报错「不在门栏扣留
  状态」。
- `test_render_phase_rules_fermate_variant`：fermate 变体特征串从
  「确认收货即实例完结」改为新文案特征串。

## 3. 在飞实例迁移

- `web_ui_interaction`（held 在 plan:2 门栏）：用户决议**手动置 done**——
  清 held_for_gate、置 gate="done"，并 append 一笔
  `via="fermate-auto-complete"` 裁决记录（与新路径产物同构，非特赦）。
- `interaction_amplitude__ret3d_pos_annualized_001`（understand:2，未
  held）：零迁移，到 plan:2 自然走新路径。

## 4. 不改的

- 全量轨道 plan:4 门栏（放行=进 execute，把关对象真实存在）。
- tacet 与 fermate 的正交性、脊柱重映射、FERMATE_SILENT_STEPS 裁剪。
- `/dl done` 归档路径（既有人工确认点，本次语义的目的地）。
