# setup 安装器 / 约定蒸馏 / 归纳层 诊断手册（2026-09 起新增子系统）

> 本文件覆盖 dl-workflow 的**项目理解层**子系统（与 5 阶段工作流正交）：`install.sh --project` 项目接线、`mine_conventions.py` 蒸馏器、`cvx.py` 查询、`conventions_inject.py` 注入、`doctor.py` 远程诊断、`/download` 分发端点。命中「注入没生效/蒸馏没产出/索引过期/Java 项目接入/换机重装/setup 报错」类症状时读。

## 0. 子系统速览（30 秒）

```
install.sh --project <项目>     # 项目接线：codegraph index(>24h 自动 sync)/post-commit 双后台/
                                 settings.json 注册双 inject hook/conventions.yaml 生成(rules: [] 空)/首蒸
<项目>/.codegraph/codegraph.db   # 代码索引（项目内，语言无关维度全靠它）
<项目>/.conventions/conventions.db # 蒸馏产物（项目内；工具在 ~/.dl-workflow/bin/，数据全在项目）
<项目>/conventions.yaml          # 规则真源：rules(手动校准)/dismissed(候选否决)
~/.dl-workflow/bin/              # 工具一处装：cvx.py / mine_conventions.py / doctor.py / cgx.py
~/.dl-workflow/hooks/            # codegraph_inject + conventions_inject（payload.cwd 解析项目根；
                                 worktree 自动映射主仓，仅当主仓有 db 才替换）
doctor.py [--project DIR]        # 五节诊断报告——远程机器「装没装对」的唯一验收桥梁（贴回输出即可）
http://<维护机>:9000/download     # 最新 tarball（HEAD 变化自动重打，失败回退 last-good）
```

**三种来源语义**（「不裁决只呈证」延伸）：`doc_declared`=yaml 人声明的规范（实证违反→drift ⚠️）；`code_evidence`=纯事实统计；`inferred`=归纳层候选（🔍 待人确认）。**槽位校准**：yaml 有同 type 手动规则 → 该 type 候选被抑制（人的校准优先）。

## 1. 症状 → 判据 → 修法

### A. 注入没生效（conventions_inject 静默）
1. **先判是不是正常静默**：无 drift 且无 inferred 候选 → hook 设计即不注入（0 token 开销）。`cvx.py drift` / `cvx.py query 候选` 验证 db 里到底有没有内容。
2. **「装上却零候选」**（实爆：Java 项目）：conventions.yaml 里存在**激活的示例/手动规则** → 槽位抑制 G1/G2。修法：删掉占位规则（0.9.8 起生成的模板默认 `rules: []` 示例全注释——旧模板要手动删文件）。
3. **yaml 解析失败**：mine_conventions 硬失败（SystemExit），db 不更新——`mine_conventions.py --root <项目>` 看 stderr。
4. **post-commit 不重挖**：查 `<项目>/.git/hooks/post-commit` 是否含 `mine_conventions.py` 标记；setup 幂等，重跑 `--project` 自愈。
5. **worktree 会话**：映射主仓，主仓无 `.conventions/conventions.db` 时维持 worktree 根（静默）——先跑主仓的首次蒸馏。
6. **settings.json 被 `*.json` gitignore 忽略**=正常（不入库约定）；换机/换 worktree 重跑 `--project` 重建。

### B. 索引过期 / 蒸馏图太旧
- 判据：doctor §2「N h 前索引」>24。**0.9.7+ `--project` 自动 `codegraph sync`**（db 存在也查新鲜度）；旧版手动 `codegraph sync`（实爆：接入时吃到 1151h 前索引，import 图全是旧代码）。

### C. Java 项目接入行不行
- 第一判据：doctor §2 `java nodes`——0 = Java 未进索引（走 SCIP/scip-java 路线）；>0 = layering/util_graph/G2 全可用（imports 边 ≥1 万即健康）。实测 10 万节点/19 万边量级的真实 Java 项目已验证可行。
- 文本维度（logging/skeleton/exit_codes/G1）默认 Python 口径，Java 下零命中**无害**；Java 语言预设未做（等真实需求）。

### D. macOS 接入症状库（四坑均已修复，按版本判）
| 症状 | 根因 | 修复版本 |
|---|---|---|
| 裸 `X?: unbound variable`（行号莫名） | 系统 bash 3.2，严格模式报错；旧版检查太靠后 | 0.9.1 检查前移 → 0.9.4 prologue 自动 exec Homebrew bash（直接 `./install.sh` 也无感） |
| 某变量「三行内先好后坏」 | **全角标点紧跟 `$变量` 被吃进变量名**（`$X（...` → 变量名 `X（...`） | 0.9.3 全仓扫修 `${VAR}`——中文脚本 `$变量` 后永远带花括号/引号 |
| `pip install --user` 被拒（EXTERNALLY-MANAGED） | Homebrew Python PEP 668 | 0.9.3 检测后仅本次追加 `--break-system-packages` |
| `--project` 直接执行回落 3.2 | shebang `#!/bin/bash` | 0.9.4 prologue（同上） |
排查手法：`bash -x install.sh 2>&1 | head -40` 看报错前最后 5 行；md5 对包判文件一致；假 HOME（`HOME=/tmp/x bash install.sh`）全仿真首跑。

### E. 非 Claude 宿主（Qoder 等编辑器）
inject hook 是 Claude Code 的 settings.json hook 协议——Qoder 下不触发**不是系统坏**。编辑器无关通道：`cvx.py query/drift`、`doctor.py`、约定 db 本身（可手动贴进 Qoder 对话/规则文件）。注入层适配 = Qoder MCP server 或规则文件渲染（未做，等机制确认）。

### F. dashboard 项目下拉空
0.9.9 前：后端白名单（不在 toml 的 403)。0.9.9 起组合框（datalist 可选可填），新路径校验=目录存在且是 git 仓，创建成功自动持久化进 dashboard.toml（历史留存）。前端静态版本戳=静态文件 mtime 动态注入——**改了 static/ 但页面没变，先硬刷 + 确认 server 进程是新版**（改 py 必重启 server，症状同 AR）。

## 2. 使用模式三态（用户视角）

1. **呈证（默认，零配置）**：commit 自动重挖；cvx 随时查；drift/候选自然浮出。老项目零文档起步就是这个模式。
2. **校准转正**：候选认可 → 写进 `rules:`（该 type 候选此后抑制，转入 drift 监控）。
3. **否决**：候选 subject 写进顶层 `dismissed:`（必须是 YAML 列表，标量不生效）。

## 3. 远程验收模式（维护者看不到目标机器）

目标机器：`install.sh --project`（尾部自检清单）→ `doctor.py`（五节报告）→ **两份输出贴回维护者**。维护者判读：§2 java nodes（Java 索引成败）/ edges kinds（imports 边量级）→ §3 按 source 计数 + drift/候选清单 → §1/§4 全 ✅ = 接线贯通。doctor 只读 db/配置；inject 冒烟会在项目 .claude/ 留 hook 调用日志（既有观测行为）。
