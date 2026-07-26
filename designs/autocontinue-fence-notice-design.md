# 自动续轮通道补 S15 围栏提示：消「未试先称被 deny」假冲突

> 状态：**已实施**（2026-07-26；engine/hooks/tests/SKILL 已同步，226 tests 绿）
> 父文档：`step-engage-prefence-design.md`（S15 围栏）、`substep-gate-at-stop-design.md`（pass 自动续轮）

## 0. 动因：模型臆断 Agent 被 S15 deny，编造留痕引发连环 block

实录（2026-07-26，session 121320fe，demo 工作流，understand:1 子步骤 4）：

1. 子4 purpose 要求条件触发**独立红队 Agent 子代理**；S15 白名单 = 常驻集 +
   `Step.fence_allow`，子4 自 S15 落地（v2.10, 672b128）即声明
   `fence_allow=("Agent",)`——**Agent 在子4 零 trace 窗口是放行的**。
2. 模型从未调用 Agent（transcript 303 行零 Agent tool_use；`.wf_fence.log`
   无一条针对 Agent 的 engage_fence_deny），却在 evidence trace 里写
   「Agent blocked by S15 fence」当事实，改用 in-context「红队」。
3. judge 只能看 evidence，照字面 block：「未提供符合要求的独立上下文红队
   trace；最后一条记录明确说明 Agent 工具被拒」。两次 block 后模型向用户
   升级「结构性冲突」——一场由编造留痕引发的假危机。

## 1. 根因：围栏豁免文案只在 UserPromptSubmit 通道，自动续轮通道没有

S15 围栏提示（含「当前子步骤额外放行：X」豁免行）只在
`workflow_phase.py:_format_injection`（UserPromptSubmit）里渲染。demo 会话
全程靠 Stop hook pass 自动续轮推进，模型**只在子1 见过一次**该提示——彼时
子1 `fence_allow=()`，文案写「Agent 等会被 deny」。续轮到子4 时，
`workflow_advance.py` 的 pass 续轮 additionalContext 只带 purpose
（"Agent(红队子代理,条件触发)"），**不带围栏豁免**。模型拿子1 的旧印象
（"Agent 会被 deny"）覆盖子4 的新现实，未试先放弃。

症状 M 同类教训：同一契约两条通道（注入 vs 续轮）信息不一致，模型遵从了
过时/弱的那条。phase-rules.md:44 已正确表述「外加当前子步骤注入清单声明
的额外工具」——但模型在子4 上下文中没有「注入清单」可看。

## 2. 设计：围栏提示文本单源化，pass/block 续轮同源附带

### 2.1 engine 新函数（单源）

`dl-flow-engine.py` 加：

```python
def engagement_fence_notice(step: Step) -> str:
    """S15 零 trace 窗口的围栏提示文本（含 Step.fence_allow 豁免行）。

    单源：workflow_phase.py 注入（UserPromptSubmit）与 workflow_advance.py
    pass/block 续轮（Stop additionalContext）共用，防双通道文案漂移。
    """
```

返回文本 = 现 `_format_injection` 里那段（常驻集清单 + `；当前子步骤额外
放行：{' / '.join(step.fence_allow)}` 条件行 + 「为用户任务探查会被 deny
指回本步」）。入参只取 `Step`（不查 state）——调用方都已手持当前/下一步
的 Step 对象，函数保持纯格式化。

### 2.2 两个调用点

| 调用点 | 现状 | 改后 |
|---|---|---|
| `workflow_phase.py` `_format_injection` | 内联文案（`fence_extra` 本地拼） | 改调 `engine.engagement_fence_notice(cur_step)`，删内联 |
| `workflow_advance.py` pass 续轮（子 n→n+1） | 只带 purpose + how | 末尾附 `engine.engagement_fence_notice(nxt_step)` |
| `workflow_advance.py` block 返工（同一步） | 只带判词 + 返工指引 | 末尾附 `engine.engagement_fence_notice(judged_step)`——block 场景正是「模型以为某工具被拦」高发区，豁免文案直接纠正假信念 |

escalate 路径不附（模型此时应 AskUserQuestion，不是调工具）。

### 2.3 不动的部分

- `workflow_step_fence.py` 的 deny 文案（已含 `本步额外放行` 行，line 294）——
  deny 时模型已能看到豁免，问题只在「没撞墙前不知道」。
- phase-rules.md:44（已泛指「注入清单声明的额外工具」，无需改）。
- judge 判据不动：「独立红队 = Agent 子代理 trace」仍是子4 gate 黑盒判据；
  本设计只消模型侧的假信念，不松判据。

## 3. 症状 M 同步清单对照

| # | 文件 | 动作 |
|---|---|---|
| 1 | `dl-flow-engine.py` | 加 `engagement_fence_notice()` |
| 2 | `hooks/workflow_phase.py` | `_format_injection` 改调单源函数 |
| 3 | `hooks/workflow_advance.py` | pass/block 续轮附围栏提示 |
| 4 | `scripts/workflow/phase-rules.md` | 不改（已泛指，见 §2.3） |
| 5 | `output-styles/workflow.md` | 不改（不涉及显示层契约） |
| 6 | `skills/workflow-creation/SKILL.md` | 症状 O 补本案例（未试先称被 deny 的假冲突 + 分诊法） |

## 4. 测试

1. `tests/test_dl_flow_engine.py`：`engagement_fence_notice` 有/无
   fence_allow 两例（子1 无豁免行、子4 含 Agent）。
2. `tests/test_workflow_advance.py`：pass 续轮（子3→子4）additionalContext
   含「额外放行：Agent」；block 续轮含当前步豁免行。
3. 回归：`TestStopStdoutPureJson` 保持绿（提示文本进 JSON body，stdout
   仍纯 JSON）。
4. 冒烟（SKILL §3 #10 payload 法）：拿 demo 真实 state（sub_step_index=4
   零 trace）喂 `workflow_step_fence.py`，确认 Agent 放行；确认
   `_format_injection` 子4 注入含豁免行。

## 5. 风险

- **续轮消息变长**：每轮多 ~2 行文本，token 增量可忽略（相对 judge 开销）。
- **文案一改三处忘改**：单源化后只剩 engine 一处；SKILL 症状 M checklist
  已覆盖。
