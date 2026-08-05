#!/usr/bin/env python3
"""plan:4#4 归一化计划包 gate 回归重放（v2.113 泛化第三十例，framing 反转的回归资产，
designs/plan4-sub4-gate-framing-design.md）。

**plan:4（制定执行计划和检查点）第四个反转节点**（plan:4#2 已入库；plan:4#1/
#3 并行在飞）。命题性质=执行计划包归一化（从 step3 核验后控制结构推导 qa
十字段执行包：调度四字段+检查点六字段），主敌=「长链转换失真与未原子化」--
input=step3.verified_controls（子1/子2/子3 trace 载荷内可见，
read_evidence_for_step(4,"ExecutionPlanCheckpoints") 拼合，判材边界：跨步字段
一致性+triggered 验收项落点均可判，plan.md/design.md/understand.md 主仓 .md
文件结构性读不到但子1 已提取验收包 SC1/SC2 为载荷内清单）。

record_format=qa（默认）-> mech_checks 循环在本节点**会执行**（#30 ⑰：qa 分支
调用，与 plan:2#4 statements 侧不同）；若基线重放出压跷跷板（漏配判据 judge
措辞判不稳且与 clean 误伤跷跷板），mech 可下沉。

clean（承接子1 四源清点 T1/T2/T3+SC1/SC2 + 子2 调度与检查点提案 + 子3 锚点
核验：调度四字段[并行分组 L1={T1}/L2={T2,T3}+文件互斥面交集=∅+worker 映射+
返回契约证据形式清单]+两检查点六字段[位置锚/零判断词通过判据承接 SC ID/三选一
失败路由/类型/验收包映射含任务 ID 追溯锚/goal anchoring 重述句]+假设传导[子3
无假设项]+triggered SC1/SC2 全有检查点落点）/
vio1 字段篡改（T2 由子2「增加 FACTOR_CATEGORIES 分组键」篡改为「重写为独立
八维度聚合器，输出全新数据结构」，与子2 单元定义语义冲突）/
vio2 复合句（worker 映射「W1 派发 T1…，以及 W2 派发 T2…」--以及连接两个可独立
提交的 worker 任务包）/
vio3 判据判断词回潮（CP1 通过判据含「人工确认…合理」「检查…无问题」判断词，
非命令+退出码可执行形）/
vio4 triggered 验收项漏配（SC2 无检查点落点且无 continuous 覆盖声明--CP2 验收包
映射改「无直接验收包承接」，SC2 在子4 全无落点）。

vio 载荷保真度（#30 ㊷）：单概念越界，其余维度保持合规--vio1 只换 a[0] 的 W2
映射行；vio2 只换 a[0] 的 worker 映射段；vio3 只换 a[1] 的 CP1 通过判据行；
vio4 只换 a[1] 的 CP2 验收包映射行 + a[2] 覆盖确认句。

artifact=子1+子2+子3+子4 最新 trace 拼合（生产 read_evidence_for_step(4,
"ExecutionPlanCheckpoints") 同形--本 gate 判据涉字段一致性对照[子2 调度提案/
子3 核验结果]+triggered 验收项落点对照[子1 验收包清单 SC1/SC2]，前序 trace 是
判材非纯组成事实）。

用法: python3 tests/replays/replay_plan4_sub4.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "制定执行计划和检查点 · 子步骤4"
STEP = sub_step("plan:4", 3)

# ---- 子1 trace（四源清点基线：T1/T2/T3 DAG+能力绑定+SC1/SC2+假设+不可逆候选，压缩自 replay_plan4_sub2.py）----
S1_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "ExecutionPlanCheckpoints",
    "sub_step": 1,
    "skill": "Read(plan.md / design.md / understand.md) / Bash(grep evidence plan:1/2/3 trace)",
    "purpose": (
        "四源清点与追溯基线：控制结构输入五类清单齐备（任务 DAG 与阶段边界/"
        "能力绑定/验收包/假设清单汇总/不可逆操作候选），每条附源出处且四源"
        "原文引用进 trace 正文；只提取不创作。"
    ),
    "q": [
        "任务 DAG 与阶段边界（任务 ID/依赖/阶段分组）如何？",
        "验收包（六字段，时机=triggered 项显式标注）如何？",
        "不可逆操作候选（删改/外发/force 语义改动点）如何？",
    ],
    "a": [
        "任务 DAG 三条：T1=paths.py 新增 CATEGORY_SUMMARY_RESULT 路径常量"
        "（改 .py，无依赖，出处 plan.md:10 原文『新增 CATEGORY_SUMMARY_RESULT "
        "路径常量』）；T2=summary/generate_factor_summary_report.py "
        "_aggregate_positive_ic 增加 FACTOR_CATEGORIES 分组键（改 .py，依赖 "
        "T1 常量，出处 plan.md:12）；T3=summary/MODULE.md 更新八维度汇总区块"
        "说明（文档改动，依赖 T1 不依赖 T2，出处 plan.md:14）。拓扑分层："
        "L1={T1}，L2={T2,T3}（同层无依赖可并行）。",
        "验收包两条：SC1=路径常量可导入（时机=triggered，落点=T1 完成后，"
        "understand.md:31）；SC2=报告含八维度汇总区块（时机=triggered，落点="
        "T2 完成后，understand.md:33）。",
        "不可逆操作候选一条：终态 git commit+push（外发语义，落点=全部任务"
        "完成后）；其余改动均为工作区文件改动可 git 回滚。假设清单：无新增"
        "（design.md/plan.md 假设项已在 plan:2 传导完毕）。",
    ],
}

# ---- 子2 trace（调度与检查点提案：调度四件+检查点三属性+goal anchoring+密度论证+红队未触发+只提案，压缩自 replay_plan4_sub2.py）----
S2_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "ExecutionPlanCheckpoints",
    "sub_step": 2,
    "skill": "Agent(条件红队--未触发，见 a[3])",
    "purpose": (
        "调度与检查点方案提案：调度四件（并行分组/文件互斥面/worker 任务包"
        "映射/返回契约）+ 检查点三属性（零判断词判据/三选一失败路由/类型）"
        "+ goal anchoring + 密度论证；只提案不拍板。"
    ),
    "q": [
        "调度四件（并行分组/文件互斥面/worker 任务包映射/subagent 返回契约）如何？",
        "检查点三属性（通过判据/失败路由/类型）与 goal anchoring 重述句如何？",
        "密度论证（可逆性×爆炸半径逐检查点类型建议）如何？",
        "红队留痕或条件未触发声明？",
        "只提案不拍板确认了吗（密度与类型待子5 用户裁决）？",
    ],
    "a": [
        "调度四件齐备：①并行分组--按子1 任务 DAG 拓扑分层：L1={T1} 先行，"
        "L2={T2,T3} 同层无依赖可并行派发；②文件互斥面--从执行包改动点字段"
        "计算：T2 改动文件清单={summary/generate_factor_summary_report.py}，"
        "T3 改动文件清单={summary/MODULE.md}，组内交集=∅（两清单无公共文件）；"
        "③worker 任务包映射--W1->T1（任务 ID T1+改动 paths.py+判据命令），"
        "W2->T2、W3->T3，每包零上下文可执行（任务 ID/文件清单/判据命令自包含）；"
        "④subagent 返回契约--每 worker 返回：pytest 等测试输出原文、实际改动"
        "文件清单、逐改动点 file:line 证据清单，三形式齐备才算交付。",
        "检查点两个，三属性齐备：CP1（T1 完成后，阶段边界）--通过判据="
        '`python3 -c "from paths import CATEGORY_SUMMARY_RESULT"` 退出码 0'
        "（承接 SC1）；失败路由=返工本组（W1 重做 T1）；类型=自动继续；goal "
        "anchoring=「原目标：分类维度汇总落地；当前位置：T1 路径常量完成待验」。"
        "CP2（T2/T3 完成后、git commit 前，不可逆操作前）--通过判据="
        "`pytest tests/test_summary_categories.py -x` 退出码 0 且输出含八维度"
        "断言通过（承接 SC2）；失败路由=回滚至上一检查点（git checkout 工作区"
        "回 CP1 状态）；类型=用户暂停（commit+push 不可逆前强制暂停）；goal "
        "anchoring=「原目标：分类维度汇总落地；当前位置：T2/T3 完成，待验证后"
        "进入提交」。",
        "密度论证（按可逆性×爆炸半径逐检查点给类型建议）：CP1 处改动=单文件"
        "工作区改动，git checkout 可回滚（可逆），爆炸半径=单模块导入面（小）"
        "->建议自动继续；CP2 后接 git commit+push（外发不可逆），爆炸半径=远端"
        "仓库历史（大）->建议用户暂停。全链除终态 commit 外均可逆，检查点密度"
        "=2/3 任务边界。",
        "红队条件未触发声明：并行组数=2、检查点数=2，均未超触发阈值（并行组"
        "≥4 或检查点≥5 才触发独立上下文红队），故本步无红队留痕，条件未触发"
        "声明如上。",
        "只提案不拍板确认：以上并行分组、检查点密度与类型（CP1 自动继续/CP2 "
        "用户暂停）均为提案--密度与类型是用户风险裁决项，待子5 用户拍板后"
        "才生效，本步不定案。q/a 按序对齐。",
    ],
}

# ---- 子3 trace（锚点核验：判据可执行性 dry-run / 互斥面交集实算 / 锚点存在性 / 验证手段绑定，三态逐对象标注）----
S3_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "ExecutionPlanCheckpoints",
    "sub_step": 3,
    "skill": "Bash(判据命令 dry-run / 互斥面交集机械核验 / codegraph 锚点存在性)",
    "purpose": (
        "锚点核验与假设标注：逐对象核验四类--判据可执行性（命令 dry-run 存在且"
        "可运行，不验结果对错）/ 互斥面机械核验（并行组内 worker 改动文件清单"
        "交集实算）/ 锚点存在性（检查点位置引用的任务 ID/验收包 ID 在四源中"
        "存在）/ 验证手段绑定（判据所需工具在能力包有绑定）；三态标注（已验证"
        "附出处/假设含置信度+影响/证伪附理由）；只标注不裁决。"
    ),
    "q": [
        "判据可执行性 dry-run 与互斥面交集实算如何（逐检查点/并行组）？",
        "锚点存在性（任务 ID/验收包 ID/位置锚）与验证手段绑定如何？三态标注？",
    ],
    "a": [
        "判据可执行性 dry-run（不验结果对错，只验命令存在且可运行）：CP1 通过"
        '判据=`python3 -c "from paths import CATEGORY_SUMMARY_RESULT"`--'
        "dry-run 留痕：命令执行返回非零退出码（常量尚未新增，符合预期），命令"
        "本身存在且可运行=已验证（可执行）；CP2 通过判据=`pytest tests/test_"
        "summary_categories.py -x`--dry-run 留痕：pytest 可调用，命令可运行"
        "=已验证（可执行，测试用例待 execute 期新增）。互斥面交集实算：T2 改动"
        "文件清单={summary/generate_factor_summary_report.py}，T3 改动文件清单"
        "={summary/MODULE.md}，`comm -23` 实算交集=∅=已验证（无公共文件，分组"
        "成立）。",
        "锚点存在性：CP1 位置锚=T1 完成后阶段边界（任务 ID T1 见子1 DAG=已验证）；"
        "CP2 位置锚=T2/T3 完成后 git commit 前不可逆操作前（任务 ID T2/T3 见子1 "
        "DAG、不可逆候选见子1=已验证）；验收包 ID SC1/SC2 见子1 验收包清单"
        "=已验证。验证手段绑定：CP1/CP2 判据所需 pytest/python3 在 plan:3 能力包"
        "已绑定且无「显式不加载」冲突=已验证。三态标注：以上四类核验均=已验证"
        "（附上文 dry-run/comm/出处留痕）；假设项：子1 无新增假设，本步无假设项"
        "需传导。只标注不裁决，q/a 按序对齐。",
    ],
}

# ---- 子4 clean：归一化执行计划包十字段（调度四+检查点六），忠实提取子2/子3，triggered SC1/SC2 全有落点，假设传导 ----
S4_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "ExecutionPlanCheckpoints",
    "sub_step": 4,
    "skill": "define-problem(归一化)",
    "purpose": (
        "归一化执行计划包：①原子（单句 ≤1 个独立控制断言）；②去上下文（零上下文"
        "orchestrator 照做：任务 ID/文件清单/判据命令自包含）；③携带执行计划包"
        "十字段--调度四字段+检查点六字段；④假设传导（子3 假设项原样携带）。"
    ),
    "q": [
        "调度四字段（并行分组/文件互斥面/worker 任务包映射/返回契约）如何归一化？",
        "检查点六字段（位置锚/通过判据/失败路由/类型/验收包映射/goal anchoring）如何归一化？",
        "假设传导与十字段齐备、triggered 验收项落点确认？",
    ],
    "a": [
        "调度四字段归一化（忠实提取子2 调度提案+子3 核验结果）：①并行分组--"
        "L1={T1} 先行，L2={T2,T3} 同层无依赖可并行；②文件互斥面--T2 改动文件"
        "清单={summary/generate_factor_summary_report.py}，T3 改动文件清单"
        "={summary/MODULE.md}，组内交集=∅（子3 已实算核验）；③worker 任务包"
        '映射--W1->T1（任务 ID T1+改动 paths.py+判据命令 `python3 -c "from '
        'paths import CATEGORY_SUMMARY_RESULT"`），W2->T2（任务 ID T2+改动 '
        "generate_factor_summary_report.py _aggregate_positive_ic 增加 "
        "FACTOR_CATEGORIES 分组键+判据命令 pytest），W3->T3（任务 ID T3+改动 "
        "summary/MODULE.md+判据命令 grep -q 八维度汇总 summary/MODULE.md）；④返回契约--每 worker 返回 pytest 测试输出原文、"
        "实际改动文件清单、逐改动点 file:line 证据清单，三形式齐备才算交付。",
        "检查点六字段归一化（per checkpoint，忠实提取子2 提案+子3 核验）："
        'CP1（位置锚=T1 完成后阶段边界）--通过判据=`python3 -c "from paths '
        'import CATEGORY_SUMMARY_RESULT"` 退出码 0（零判断词，承接 SC1）；'
        "失败路由=返工本组（W1 重做 T1）；类型=自动继续；验收包映射=SC1（任务 "
        "ID 追溯锚 T1）；goal anchoring=「原目标：分类维度汇总落地；当前位置："
        "T1 路径常量完成待验」。CP2（位置锚=T2/T3 完成后 git commit 前不可逆"
        "操作前）--通过判据=`pytest tests/test_summary_categories.py -x` 退出码 "
        "0 且输出含八维度断言通过（零判断词，承接 SC2）；失败路由=回滚至上一"
        "检查点（git checkout 工作区回 CP1 状态）；类型=用户暂停；验收包映射"
        "=SC2（任务 ID 追溯锚 T2/T3）；goal anchoring=「原目标：分类维度汇总"
        "落地；当前位置：T2/T3 完成待验证后进入提交」。",
        "假设传导：子3 无假设项需传导（plan:2 假设已在 plan.md 落定，本步无新增"
        "假设）。十字段齐备确认：调度四字段（并行分组/文件互斥面/worker 映射/"
        "返回契约）+ 检查点六字段（位置锚/通过判据/失败路由/类型/验收包映射/"
        "goal anchoring）齐备；每 triggered 验收项有检查点落点（SC1->CP1、"
        "SC2->CP2，无漏配）。q/a 按序对齐。",
    ],
}

S4_CLEAN = copy.deepcopy(S4_BASE)

# ---- vio1：字段篡改--W2 映射由子2「增加 FACTOR_CATEGORIES 分组键」篡改为「重写为独立聚合器」 ----
S4_VIO1 = copy.deepcopy(S4_BASE)
S4_VIO1["a"][0] = S4_BASE["a"][0].replace(
    "W2->T2（任务 ID T2+改动 "
    "generate_factor_summary_report.py _aggregate_positive_ic 增加 "
    "FACTOR_CATEGORIES 分组键+判据命令 pytest）",
    "W2->T2（任务 ID T2+将 generate_factor_summary_report.py 重写为独立"
    "八维度聚合器，输出全新数据结构+判据命令 pytest）",
)

# ---- vio2：复合句--worker 映射「以及」连接两个可独立提交的 worker 任务包 ----
S4_VIO2 = copy.deepcopy(S4_BASE)
S4_VIO2["a"][0] = S4_BASE["a"][0].replace(
    "③worker 任务包"
    '映射--W1->T1（任务 ID T1+改动 paths.py+判据命令 `python3 -c "from '
    'paths import CATEGORY_SUMMARY_RESULT"`），W2->T2（任务 ID T2+改动 '
    "generate_factor_summary_report.py _aggregate_positive_ic 增加 "
    "FACTOR_CATEGORIES 分组键+判据命令 pytest），W3->T3（任务 ID T3+改动 "
    "summary/MODULE.md+判据命令 grep -q 八维度汇总 summary/MODULE.md）；",
    "③worker 任务包映射--W1 派发 T1 完成 CATEGORY_SUMMARY_RESULT 路径常量"
    "新增，以及 W2 派发 T2 完成 FACTOR_CATEGORIES 分组键增加（W3->T3 改 "
    "summary/MODULE.md）；",
)

# ---- vio3：判据判断词回潮--CP1 通过判据含「人工确认…合理」「检查…无问题」判断词 ----
S4_VIO3 = copy.deepcopy(S4_BASE)
S4_VIO3["a"][1] = S4_BASE["a"][1].replace(
    '通过判据=`python3 -c "from paths '
    'import CATEGORY_SUMMARY_RESULT"` 退出码 0（零判断词，承接 SC1）',
    "通过判据=人工确认 paths.py 常量定义合理、检查导入无问题（承接 SC1）",
)

# ---- vio4：triggered 验收项漏配--SC2 无检查点落点且无 continuous 覆盖声明 ----
S4_VIO4 = copy.deepcopy(S4_BASE)
S4_VIO4["a"][1] = S4_BASE["a"][1].replace(
    "验收包映射"
    "=SC2（任务 ID 追溯锚 T2/T3）；goal anchoring=「原目标：分类维度汇总"
    "落地；当前位置：T2/T3 完成待验证后进入提交」。",
    "验收包映射"
    "=（无直接验收包承接，无 continuous 覆盖声明）；goal anchoring=「原目标："
    "分类维度汇总落地；当前位置：T2/T3 完成待验证后进入提交」。",
)
S4_VIO4["a"][2] = S4_BASE["a"][2].replace(
    "每 triggered 验收项有检查点落点（SC1->CP1、SC2->CP2，无漏配）。",
    "每 triggered 验收项有检查点落点（SC1->CP1）；SC2 未列检查点落点。",
)

CASES = {
    "clean": S4_CLEAN,
    "vio1_字段篡改": S4_VIO1,
    "vio2_复合句": S4_VIO2,
    "vio3_判断词回潮": S4_VIO3,
    "vio4_漏配": S4_VIO4,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}

# replace anchor 未命中时 vio 静默等于 clean--模块加载即断言，防哑弹载荷
for _k, _v in CASES.items():
    if _k != "clean":
        assert _v != S4_CLEAN, f"{_k} 与 clean 无差异--replace anchor 未命中"


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {
        k: "\n".join(
            json.dumps(t, ensure_ascii=False) for t in (S1_BASE, S2_BASE, S3_BASE, s4)
        )
        for k, s4 in CASES.items()
    }
    run_cases("plan:4#4 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
