#!/bin/bash
# dl-shim.sh - 给 provider 函数（ac-ark/ac-mm/ac-ark1 等）source 用的 snippet
#
# 作用：让你的 provider 函数支持 `--dl <name>` 进工作流。
# provider 函数设完自己的 env 后，调 _dl_dispatch 即可。
#
# 用法（在你的 provider 函数里）：
#   ac-ark() {
#     export ANTHROPIC_BASE_URL=...
#     export ANTHROPIC_AUTH_TOKEN=...
#     # ... 其他 env
#     source "$HOME/.dl-workflow/dl-shim.sh"   # 引入 --dl 拦截
#     _dl_dispatch "$@" && return              # 若是 --dl 进工作流则已处理
#     claude "$@"                               # 否则正常起 claude
#   }
#
# 或者更简：只在检测到 --dl 时 source
#   ac-ark() {
#     export ...
#     if [ "$1" = "--dl" ]; then
#       source "$HOME/.dl-workflow/dl-shim.sh"
#       _dl_dispatch "$@"; return $?
#     fi
#     claude "$@"
#   }
#
# 原理：provider 在交互 shell 里已 export env，调 launcher（子进程）时 env 被继承，
# launcher exec 原生 claude 就带上 provider 的配置。不存在「launcher exec provider」
# 的子进程问题（provider 是函数，子进程调不到）。

# 导出 _dl_dispatch 函数供 source 者（同一交互 shell）使用
_dl_dispatch() {
  if [ "$1" = "--dl" ]; then
    shift
    "$HOME/.dl-workflow/scripts/workflow/wf-launch.sh" --workflow "$@"
    return $?
  fi
  return 1   # 非 --dl，调用方继续走自己的 claude 逻辑
}
