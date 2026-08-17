# understand:1 子4（双向取证）成本优化 round-2：_subagent_dir 定位 bug + codegraph 命令钉死

> 立项：2026-08-17 用户 goal「step4 跑了 51 轮，是不是优化没到位？继续优化 step4 耗时/token 直到大幅减少」。
> 前置：round-1（u1-sub4-cost-optimization-design，c384738）修 ingest 标题 off-by-one +
> 防重误报 + u:1 段链回滚；step5 优化（u1-sub5-cost）同日落地的真实 A/B 中子4 首次实测。
> 结论先行：**round-1 三修全部生效（零标题拒/零防重误报/fresh 段），51 轮的主因是
> round-1 未覆盖的一个真 bug（_subagent_dir 多目录时代定位错位）+ 结构性干等（agent 运行时长）。**

## 1. 诊断数据（2026-08-17 17:42 真实子4 段 e92ca5db，deepseek-v4-flash）

段：45 calls（主会话）/ 707s / fresh 103k / cache_read 4.11M / out 49.5k / $6.34
（+2 fetch 子代理 0.5M+0.74M cr）。基线对照：D 轮 34 calls/8.4min（链+round-1 前）、
F 轮 17 calls/8.0min（链暖轮+单 subagents 目录时代）。

### 逐调用时间线分解

| 段 | 时长 | calls | 性质 |
|---|---|---|---|
| fetch-prompt+可检验化+派发 2 agent | 1.5min | 7 | 生产性 |
| 仓内取证（codegraph 4 调学 CLI+6 Read+grep） | 1.0min | 14 | 生产性+脂肪 ~4 调 |
| TaskOutput 干等 agent（agent 跑 6.4min） | **5.3min** | 1 | **结构地板** |
| **ingest 找不到 transcript 调试死循环** | **2.7min** | **15** | **真 bug（本设计修 A）** |
| 填载荷+落库 | 1.0min | 6 | 生产性 |

### 瓶颈定位（cost-optimization #1 分层）

1. **机制 bug 层（修 A，15 calls + 2.7min + ~1.0M cr）**：
   `_subagent_dir()` 按字典序返回**第一个**含 subagents/ 的会话目录。
   v4 修复（2026-08-13，「glob 遍历返回含 subagents/ 的那个」）写在单目录时代；
   现在 14 个会话目录有 subagents/（step4 每轮 + 红队 + 补派），第一个 =
   早上 F 轮的 188d1472，本段 transcript 在 e92ca5db → ingest 必报
   「找不到子代理 transcript」→ 模型 15 轮调试（ls/cat state/读 engine 源码/
   ln -sf 被 sensitive 守卫拒/cp 被拒/python3 shutil 绕过）。
   **同 bug 第二受害面**：`_subagent_retry_stats`（gate 裁决的空响应重试台账）
   同函数取目录——扫的是旧会话的 agent，台账错位。
2. **结构地板层（不修，说明理由）**：agent 运行 ~6.4min 是墙钟 54%。
   红队式预派发不成立：fetch Agent prompt 的 claim 可检验化（claim-A1/C1 带
   证实/证伪标准）是模型真语义工作，脚本预生成=降级证据针对性（三关质检第一关）；
   且预派发只省 setup ~1.4min（agent 运行才是大头），质量风险 > 收益。
   agent 运行时长本身（full 五层源双向协议）= v2.40 钉死的设计内成本。
   原子C 定 full 档（量级合理性类，2026-08-13 取证重设计后仍定 full）=
   子2a 定档判面，不在本步范围，记入观察项。
3. **脂肪层（修 C，~3-4 calls）**：codegraph 新鲜度检查——purpose 只写
   「>72h 先 sync」没给命令形态，模型 ls db → --help → sync → status 学 CLI 4 轮。

### 预期收益（修 A+C，单步）

- calls 45 → ~27-30（-35%）；墙钟 11.8min → ~9min（-23%，地板=agent 运行 6.4min）；
- cache_read 4.11M → ~2.6M（-37%，调试循环的 88k→130k 上下文增长段消除）；
- fresh 103k → ~80k。

## 2. 方案（两修，engine 单文件 + nodes 一行 + 测试）

### 修 A：_subagent_dir 按 task_id 精确定位 + 无 id 时取最新目录

```python
def _subagent_dir(project_root, name, task_id=None):
```

- task_id 给定（ingest_agent_report 传入）：遍历会话目录找含
  `agent-<task_id>.jsonl` 的目录；多命中（模型手工拷贝残留的同名文件，
  本轮实见 188d1472/e92ca5db 各一份）取文件 mtime 最新者。
- task_id=None（_subagent_retry_stats「本会话」语义）：取**目录 mtime 最新**
  的 subagents/ 目录——当前段恒为最新（段顺序执行；预派发 RT worker
  --tools Read 无 subagents）。
- 报错消息附「搜索了 N 个会话目录均无 agent-<task_id>.jsonl」，
  防再次误入调试循环（报错即指路是防御纵深）。

### 修 C：子4 purpose ③ codegraph 行给可跑命令形态

「codegraph 新鲜度前置（>72h 先 codegraph sync，查询结果留痕）」→
「codegraph 新鲜度前置（`codegraph status <repo>` 看索引时间，>72h 才
`codegraph sync <repo>`，查询结果留痕）」——§3.5 #26 可见面命令模板必须可跑。

## 3. 验证

1. TDD：多会话目录场景——agent 文件在字典序较后的目录 → ingest 成功
   （bug 重现场）；双命中取 mtime 最新；retry_stats 取最新目录；
   既有 ingest/retry 测试（单目录 stub）回归绿；
2. 全量 pytest + ruff；
3. **真实数据验证**（无需段跑）：对在飞实例目录（14 个 subagents 目录）直接调
   `_subagent_dir(root, name, 'a8077323829e1c413')` 应返回 e92ca5db，
   `_subagent_dir(root, name)` 应返回最新目录而非 188d1472；
4. live 验证：下一次真实 step4（新工作流或本实例 state-reset 重跑）应见
   ingest 零调试循环、calls ~30 量级。

## 4. 不做的事

- fetch agent 预派发（claim 可检验化是模型语义工作，预生成降级证据针对性；
  且只省 setup ~1.4min——见 §1 层 2）；
- fetch agent 运行时长/协议（v2.40 五层源双向钉死；关思考链=质量风险，
  round-1 同裁决）；
- 原子C 的 full 定档（子2a 判面，观察项）；
- 交接包瘦身（P1-1 独立项）。

## 5. 实施验证记录（2026-08-17，merge 44182f4，1068 tests）

- TDD 红→绿：bug 重现场（agent 在字典序较后目录→ingest 成功）/双命中取最新/
  台账取最新 agent 文件目录（目录 mtime 反向污染也不影响）+ 既有 ingest/retry
  回归全绿。
- **真实数据验证**（在飞实例 14 个 subagents 目录）：两 task_id 均定位
  e92ca5db（当前段）✓；台账定位 e92ca5db ✓。过程中发现 bug 期模型的
  workaround 拷贝残留（188d1472 里两份同名文件）把文件 mtime 锚也污染——
  cmp 验证与原件一致后清除；鉴别器同步从「目录 mtime」改「最新 agent 文件」
  抗此类污染。
- 原子C 定档复核：tier_reason 明示「规则明示『X 策略年化 48.7% 是否合理』
  =full 档」——2026-08-13 重设计删的是 light 例中的量级合理性，full 档
  含该规则例，定档 per-spec，**非子2a 判面漏判**（设计 §1 层2 观察项撤回）。
- live 验证：下一次真实 step4（新工作流）应见 ingest 零调试循环、
  calls ~30 量级。拷贝残留类污染已随鉴别器升级免疫。
