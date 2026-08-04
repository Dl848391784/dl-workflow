#!/usr/bin/env python3
"""plan:1#1 现状勘察 gate 回归重放（v2.99 反转的回归资产，
designs/p1-sub1-gate-framing-design.md）。

**plan 阶段首个反转节点**（前 16 例全在 understand）。命题性质=事实性
（代码现实接地），与 u:1#3 双向取证同族但源是本仓代码而非外部知识。

clean（demo 场景：统计 default 管线正 IC 因子数量并在报告展示——四要素齐备，
每条附 codegraph 原始输出/file:line，新鲜度前置留痕，勘察不到显式标「未知」）/
vio1 训练记忆编造（②可复用点凭印象写「一般这类项目都有 utils.py 通用统计函数」，
无 codegraph/Read 出处）/
vio2 凭空 API（引用 `summary/report/ic_stats.py:44 count_positive_ic()` ——
codegraph 查无此文件此符号，凭空 API）/
vio3 漫游（勘察 data_fetchers OOM/intraday 择时/9:25 集合竞价，与 understand.md
「报告展示正 IC 因子数量」范围明显脱节）/
vio4 内部矛盾（同条声称 callers 输出 0 个调用方又列 3 个具名直接调用方）。

vio1/vio2 读数口径：生产墙=mech（terrain_tool_trace）100% 先拒（引用代码符号形却
无任何工具动词=凭空 API/训练记忆），judge 侧读数为已知裁量面——v2.99 gate 声明
「无工具出处已被机械校验当场拒、你不得以此 block」，judge 正确放行无工具留痕的
符号引用（judge-only 重放下 vio1/vio2 期望 BLOCK 但命中 0-5/6 是设计内委托，生产里
它到不了 judge，u:3#2 同判读纪律）。vio3 漫游由 judge 方框三判、vio4 内部矛盾由
judge 方框二判（必须 6/6）。

artifact=子1 单条 trace（生产 read_evidence_for_step(1,"DesignSolution") 同形——
本节点首步，minor_stage 过滤后无前序拼合）。**判材边界特殊性**：Step.input=
「understand.md（问题陈述+范围约束+成功标准）」是**跨阶段文件**，judge 结构性
读不到（evidence 只含 DesignSolution 段）——判据须钉「不得以『未见 understand.md
原文/无法核实范围对齐』block」（#30 ㉚② 的跨阶段变体：前 16 例的跨节点输入是
另一 minor_stage 的 statements，本例是主仓 .md 文件，不可见性更彻底）。

用法: python3 tests/replays/replay_p1_sub1.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "设计解决方案 · 子步骤1"
STEP = sub_step("plan:1", 0)

# ---- clean：承接 demo「统计 default 管线正 IC 因子数量并在报告展示」场景 ----
# 符号全部取自本仓 codegraph 真实条目（summary/report/*、paths.py），
# 载荷保真度：judge 不查库，但真符号使 vio2「凭空 API」的对照面成立。
BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "DesignSolution",
    "sub_step": 1,
    "skill": "codegraph callers/impact / Read / Grep / Bash(新鲜度+数据契约)",
    "purpose": (
        "代码现状勘察：现状地图四要素（涉及模块与现有实现/可复用点与扩展点/"
        "调用方与影响面/数据契约现状），每条附 codegraph 原始输出或 file:line "
        "出处，勘察不到显式标「未知」。方案必须从代码现实生长，接地防凭空设计。"
    ),
    "q": [
        "codegraph 索引新鲜度如何，是否需要 sync？",
        "①涉及模块与现有实现：报告 IC 展示当前落在哪些模块？",
        "②可复用点与扩展点：已有哪些可直接复用的函数？",
        "③调用方与影响面：改动点的 callers 与影响面有多大？",
        "④数据契约现状：IC 数据的路径与字段口径如何取？",
        "有勘察不到的部分吗？勘察范围与 understand.md 是否对齐？",
    ],
    "a": [
        'Bash 实测 `sqlite3 .codegraph/codegraph.db "SELECT '
        "datetime(MAX(indexed_at)/1000,'unixepoch','+8 hours') FROM files;\"` "
        "输出 2026-08-04 09:12:33——距今 <72h，无需 sync，新鲜度前置通过。",
        "①涉及模块与现有实现：报告 IC 区块生成在 `summary/report/sections.py:32` "
        "`_generate_ic_section`（codegraph 输出 `function _generate_ic_section "
        "summary/report/sections.py:32`）；因子筛选信息在 "
        "`summary/report/factor_analysis.py:217` `get_factor_selection_info`。"
        "现有实现只渲染既有 IC 明细表，**无正 IC 计数聚合**（Read sections.py "
        "32-133 全段确认无 count/正负号聚合分支）。",
        "②可复用点与扩展点：数值格式化可复用 "
        "`summary/report/formatters.py:129 format_float` 与 "
        "`formatters.py:92 format_percentage`（codegraph 输出 "
        "`function format_float summary/report/formatters.py:129`）；"
        "扩展点=`_generate_ic_section` 内部，它已持有 IC 明细数据结构，"
        "计数聚合可在其内完成，无需新数据通道。",
        "③调用方与影响面：`codegraph callers _generate_ic_section` 输出 1 个调用方"
        "——`generate_factor_summary_report`（summary/generate_factor_summary_report.py）；"
        "`codegraph impact _generate_ic_section` 输出 3 个受影响符号（"
        "`_generate_ic_section:32` / `generate_factor_summary_report` / "
        "`summary/report/sections.py:1` 文件级）。影响面限报告生成链路单侧，"
        "不触及因子计算与回测。",
        "④数据契约现状：IC 结果路径 `paths.py:75 FACTOR_IC_RESULT`、汇总产物 "
        "`paths.py:78 SUMMARY_RESULT`（Read paths.py 72-79 原文确认两常量在册）；"
        '字段口径 Bash 实测 `python3 -c "from paths import FACTOR_IC_RESULT; '
        'import pyarrow.parquet as pq; print(pq.read_schema(FACTOR_IC_RESULT).names)"` '
        "输出含 `ic_mean`——正 IC 判定用 `ic_mean > 0`。CLAUDE.md §5 H7「路径只能 "
        "from paths import」，禁拼字符串。",
        "**未知**：`_generate_ic_section` 内 IC 明细数据是否已按 default 管线过滤，"
        "codegraph 无法给出运行时数据流，Read 该函数体见其取上游传入的 dict、"
        "过滤逻辑在调用方之外——标「未知」，留子3 可行性验证阶段实测确认。"
        "勘察范围与 understand.md 对齐：只勘察报告展示链路（in-scope），"
        "未勘察因子计算/回测（out-of-scope）。",
    ],
}

CLEAN = copy.deepcopy(BASE)

# vio1 训练记忆编造：②可复用点凭印象，无 codegraph/Read 出处
VIO1 = copy.deepcopy(BASE)
VIO1["a"][2] = (
    "②可复用点与扩展点：一般这类量化分析项目都会有 utils.py 放通用统计函数，"
    "正 IC 计数这种聚合通常可以直接复用里面的计数工具；报告模块按惯例也会有"
    "一个通用的 section 渲染基类可以继承扩展。"
)

# vio2 凭空 API：裸符号引用（无 file:line 无工具动词，mech 生产墙先拒）
# ——注意不给 `:line`：`ic_stats.py:44` 形式的 file:line 本身即合法出处（形式
# 要件 or 分支），存在性真值归子3；mech 拦的是「连 file:line 都没有的裸 .py/
# 函数名引用」（凭空 API 的纯 token 投影）。
VIO2 = copy.deepcopy(BASE)
VIO2["a"][1] = (
    "①涉及模块与现有实现：正 IC 计数已有现成实现在 `summary/report/ic_stats.py` "
    "的 `count_positive_ic()` 函数，直接调它即可；报告渲染入口在 "
    "`summary/report/renderer.py` 的 `IcStatsRenderer` 类。"
)
VIO2["a"][2] = (
    "②可复用点与扩展点：复用 `ic_stats.py` 的 `count_positive_ic()` "
    "与 `aggregate_ic_summary()` 两个现成聚合函数，无需新增逻辑。"
)

# vio3 漫游：勘察与 understand.md 范围明显脱节
VIO3 = copy.deepcopy(BASE)
VIO3["a"][1] = (
    "①涉及模块与现有实现：勘察了 `data_fetchers/factor_generator.py` 的 pipeline "
    "step 内存占用（codegraph 输出 `function run_pipeline_step "
    "data_fetchers/factor_generator.py:210`），每 step 后需 gc.collect() 修 OOM；"
    "另勘察 `intraday/strategy.py:88 decide_open_action` 的 9:25 集合竞价高开低开"
    "止损分支（codegraph 输出在册）与 `intraday/reversal.py:31 detect_rebound` "
    "反抽识别逻辑。"
)
VIO3["a"][3] = (
    "③调用方与影响面：`codegraph callers run_pipeline_step` 输出 4 个调用方"
    "（factor_generator 主流程 + 三个 fetcher 子模块）；"
    "`codegraph impact decide_open_action` 输出 7 个受影响符号，"
    "覆盖日内择时全链路与止损参数表。"
)
VIO3["a"][5] = (
    "**未知**：日内策略的历史回放数据是否完整，codegraph 不含运行时数据。"
    "勘察范围覆盖了 pipeline 内存治理与日内择时两条链路。"
)

# vio4 内部矛盾：trace 内声称的 codegraph 输出与自述内容明显矛盾
# v3 改同源矛盾（v1 0 callers vs 5 modules=间接被读成传递影响 3/6；v2 跨源
# codegraph-0 vs Read-3 被读成「codegraph 索引过期」合理非矛盾 5/6）：
# 同一命令、同一符号，两次输出自相矛盾——无跨源合理化空间。
VIO4 = copy.deepcopy(BASE)
VIO4["a"][3] = (
    "③调用方与影响面：`codegraph callers _generate_ic_section` 输出 **0 个调用方**"
    "——该函数当前无任何调用。但同一命令复查输出 **3 个调用方**："
    "`generate_factor_summary_report`（summary/generate_factor_summary_report.py）、"
    "`_render_ic_table`（summary/report/sections.py:355）、"
    "`_compose_report`（summary/report/sections.py:82）。"
)

CASES = {
    "clean": CLEAN,
    "vio1_training_memory": VIO1,
    "vio2_nonexistent_api": VIO2,
    "vio3_wandering": VIO3,
    "vio4_internal_contradiction": VIO4,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {k: json.dumps(t, ensure_ascii=False) for k, t in CASES.items()}
    run_cases("p:1#1 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
