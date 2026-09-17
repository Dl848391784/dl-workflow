# dashboard create 拆正：launcher --setup-only（建实例与驱动分离）

> 2026-09-17。改动范围：`scripts/workflow/dl-launch.sh` + `dl_dashboard/actions.py`（+`dl_dashboard/static/app.js` 注释 + 测试）。

## 根因（实爆）

qoder 引擎 dashboard 新建工作流：列表已显示新实例（SSE 扫到 state.json），弹窗仍「创建中」很久才关。

机制链：`/api/create` → `create_workflow` 用 `subprocess.run(timeout=600)` **同步**跑 `dl-launch.sh --headless`，而 launcher 的 --headless 分支末尾 `exec dl_drive.py`（dl-launch.sh:346）——launcher 变成 headless driver 全程跑首个段才退出。POST 返回被首段时长绑架（claude 十几秒、qoder 数分钟），弹窗关闭时机 = POST 返回；state.json 在 launcher 开头几秒就落盘，SSE 独立刷新，故页面先更新。

附生缺陷：run() 返回后 `mgr.start` 再起一个续跑 driver——两段式驱动；且 launcher exec 的 driver 不受 DriverManager 托管（无 pid 文件，macOS 无 /proc 野生认领时不可观测，有双 driver 事故面）。

## 方案

拆正「建实例」与「驱动」：
1. `dl-launch.sh` 新增 `--setup-only`：完成全部一次性设置（worktree/state/settings/轨道置位/front-mode off）后 exit 0，不 exec 任何引擎/driver；
2. `create_workflow` 改调 `--setup-only`（秒级返回），随后照旧 `mgr.start`——driver 唯一来源 = DriverManager 托管（pid 文件 + killpg，跨平台可观测）；
3. 前端 create 弹窗行为零改动（POST 秒回即关）；仅更新「launcher 要跑十几秒」过时注释。

## 验证

- TDD：create argv 断言含 --setup-only 不含 --headless；真实 launcher 测试（wf_repo + fake claude）：--setup-only 退出 rc=0、state 落盘、front_mode off、**不 exec 引擎**（无 FAKE_CLAUDE 输出）；
- 全量 pytest + ruff；
- 首真 qoder 新建在 Mac 侧 E2E 验收（弹窗秒关、driver 徽标在跑）。
