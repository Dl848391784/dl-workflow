# trace 载荷挪出 .claude 保护目录设计（v2.125）

> 2026-08-07。触发：tail_volume_acceleration_annualized acceptEdits 重跑，
> Edit `.trace-payload-*.md` 必弹窗（用户被 hold）。

## 问题

载荷文件现行落点 = 主仓 `.claude/evidence/.trace-payload-<name>.md`。
acceptEdits 模式下 Edit 它**必弹权限窗**，allow 规则无效，双重根因
（claude-code-guide 取证，GitHub issues 佐证）：

1. `.claude/` 是 harness 写入保护目录（仅豁免 commands/agents/skills/worktrees），
   evidence 不在列——保护目录写入在 acceptEdits 下无视 allow 规则必弹窗。
   Read 不受限（解释了「Read 同款规则 5ms 秒过、Edit 必弹」的不对称）。
2. 已知 bug #16170：`**` 通配对 Read 生效、对 Edit/Write 不生效——
   `Edit(//主仓/.claude/**)` 规则即使是非保护路径也不一定匹配。

历史隐身原因：auto 模式下这些写入走端点分类器 2-6s 自动放行（2026-08-06
运行 6 次 Edit 裁决全 behavior=allow），用户无感。acceptEdits 把保护目录
弹窗暴露出来。

## 关键性质：载荷是临时文件

载荷生命周期 = scaffold 生成 → Edit 填「待填」→ append-trace 消费落库 →
无价值（v2.63 还自动清 stale 残留）。它**不需要** 2026-07-28「产物写主仓
.claude/ 防 worktree 删除丢失」决议的持久性保证——那个决议保护的是
evidence.jsonl 本体与阶段产物（它们仍由 append-trace/render-artifact 经
Bash 写主仓，Bash 不过文件权限检查，不受影响）。

## 方案

载荷落点改 **worktree 根**：`<worktree_path>/.trace-payload-<name>.md`。

- worktree 在 `.claude/worktrees/` 下 = 保护目录**豁免名单内**；
- 且 = 会话 cwd 内，acceptEdits 对 cwd 内编辑**无条件本地放行**——
  规则匹配（#16170）与保护目录两个坑同时绕开，不依赖任何未文档化语义。
- state.json 恒有 worktree_path（launcher 写入），路径全链路可推导。

## 改动点（路径单源化）

现行路径散落在 4 处各自拼装，本次收编为 engine 单源 helper：

```
trace_payload_path(project_root, name, state=None) -> Path
  state 有 worktree_path -> <worktree>/.trace-payload-<name>.md
  缺失（测试/旧 state）-> 旧 evidence 路径（兼容兜底，宁纵勿枉）
```

1. `dl_flow_engine.py`：+helper；`scaffold_payload`（4967）与
   `--ingest-agent`（4824）改调 helper；`_phase_write_path_ok` 补
   `.trace-payload-*.md` 文件名豁免（S11 现按「.claude+evidence 路径段」放行，
   worktree 根无 evidence 段会被误 deny）；scaffold --help 文案。
2. `hooks/workflow_phase.py`：注入的载荷路径改调 helper（模型按注入路径写）。
3. `hooks/workflow_step_fence.py`：S14 两处（evidence 直写 deny 指路文案 /
   payload_raw_write_deny 判定）改 helper；S15 写白名单补「== 载荷路径」
   （现按父目录==evidence 目录放行，新落点父目录是 worktree 根）。
4. `hooks/workflow_advance.py`：262 行 stale 文案（还写着 .json 旧路径）顺手修正。
5. tests：新路径行为 3 例（engine helper 双态 / fence worktree 路径 /
   phase 注入路径）；旧测试靠 fallback 保持绿（tmp state 无 worktree_path）。

## 兼容

在飞工作流零迁移：载荷临时性，旧路径残留由 v2.63 stale 判定自动清；
模型下一轮注入即见新路径；append-trace --from-file 吃显式路径参数，
旧路径载荷照常可消费（优雅降级）。

## 验证

- 全量 pytest 绿 + 新增 3 例。
- 在飞 tail_volume 会话 dogfood：下一装配步 scaffold 落 worktree 路径，
  Edit 不再弹窗（cc_debug.log 无 executePermissionRequestHooks for Edit）。

## 不做

- 不动 evidence.jsonl 本体与阶段产物路径（它们经 Bash 落库，无此问题，
  且持久性决议仍然成立）。
- 不加 additionalDirectories（不覆盖保护目录写入，对本问题无效）。
