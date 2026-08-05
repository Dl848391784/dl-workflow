#!/usr/bin/env python3
"""plan:4#3 锚点核验 gate 回归重放（framing 反转的回归资产，
designs/plan4-sub3-gate-framing-design.md）。

**plan:4（制定执行计划和检查点）第三个反转节点**。命题性质=锚点核验与三态
标注（对子2 调度方案逐对象核验四类：判据可执行性 dry-run / 互斥面交集实算 /
锚点存在性 / 验证手段有绑定；三态=已验证/假设/证伪），主敌=「调度方案接地
失守」——判据命令编造会被零上下文 executor 当事实消费、互斥面交集不实算会
让并行分组冲突执行期爆雷、锚点不存在会让检查点引用悬空。

clean（承接子1 四源清点 T1/T2/T3+SC1/SC2 + 子2 调度方案 CP1/CP2：四类核验
逐对象留痕[CP1/CP2 判据命令 which/collect-only dry-run 附命令+返回概述、并行
组 L2 交集实算命令+输出、CP1/CP2 引用锚点 Read/codegraph 出处、验证手段绑定
声明]、三态混合标注[已验证附出处+一项假设附置信度×影响]、只标注不裁决）/
vio1 声称可执行无 dry-run 留痕=编造（CP1/CP2 判据只称可运行无命令出处）/
vio2 交集核验无实算输出=没真核验（称两 worker 文件不同交集为空，无实算）/
vio3 全对象无差别「已验证」=没真核验（四类核验文本同形泛化、无差异化留痕）/
vio4 假设项缺置信度或影响（假设条目无置信度×影响标注）/
vio5 漏对象核验（CP2 判据可执行性未单独核验，自称随 CP1 覆盖）。

vio 载荷保真度（#30 ㊷）：单概念越界，其余维度保持合规——vio1 只换 a[0]
判据核验段去命令出处；vio2 只换 a[1] 交集段去实算输出；vio3 只换 a[0]-a[3]
为同形泛化已验证；vio4 只换 a[3] 假设标注去置信度×影响；vio5 只删 a[0]
CP2 dry-run 段改自称随 CP1 覆盖。

artifact=子1+子2+子3 最新 trace 拼合（生产 read_evidence_for_step(3,
"ExecutionPlanCheckpoints") 同形——本 gate「四类核验逐对象」须对照 S2 调度
方案，S2 是判材非纯组成事实；plan.md/design.md/understand.md 四源文件结构性
读不到=只判 trace 内留痕在场与自洽，不核四源真值）。

vio4 设计内委托（#30 ㉗）：「假设缺置信度/影响」由 assumption_completeness_trace
mech 承托（同 plan:2#3 范式），gate 方框声明「已机械校验、不得以此 block」。
replay judge-only 读数 vio4 = 0/6 是设计内（生产墙=mech 先拒），EXPECT 仍标
BLOCK--勿把设计内读数当回归。

用法: python3 tests/replays/replay_plan4_sub3.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "制定执行计划和检查点 · 子步骤3"
STEP = sub_step("plan:4", 2)

# ---- 子1 trace（四源清点基线：T1/T2/T3 DAG+SC1/SC2+不可逆候选，压缩自 replay_plan4_sub2.py）----
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

# ---- 子2 trace（调度与检查点方案：CP1/CP2+并行分组+互斥面，压缩自 replay_plan4_sub2.py）----
S2_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "ExecutionPlanCheckpoints",
    "sub_step": 2,
    "skill": "Agent(条件红队——未触发，见 a[3])",
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
        "调度四件齐备：①并行分组——按子1 任务 DAG 拓扑分层：L1={T1} 先行，"
        "L2={T2,T3} 同层无依赖可并行派发；②文件互斥面——从执行包改动点字段"
        "计算：T2 改动文件清单={summary/generate_factor_summary_report.py}，"
        "T3 改动文件清单={summary/MODULE.md}，组内交集=∅（两清单无公共文件）；"
        "③worker 任务包映射——W1→T1（任务 ID T1+改动 paths.py+判据命令），"
        "W2→T2、W3→T3，每包零上下文可执行（任务 ID/文件清单/判据命令自包含）；"
        "④subagent 返回契约——每 worker 返回：pytest 等测试输出原文、实际改动"
        "文件清单、逐改动点 file:line 证据清单，三形式齐备才算交付。",
        "检查点两个，三属性齐备：CP1（T1 完成后，阶段边界）——通过判据="
        "`python3 -c \"from paths import CATEGORY_SUMMARY_RESULT\"` 退出码 0"
        "（承接 SC1）；失败路由=返工本组（W1 重做 T1）；类型=自动继续；goal "
        "anchoring=「原目标：分类维度汇总落地；当前位置：T1 路径常量完成待验」。"
        "CP2（T2/T3 完成后、git commit 前，不可逆操作前）——通过判据="
        "`pytest tests/test_summary_categories.py -x` 退出码 0 且输出含八维度"
        "断言通过（承接 SC2）；失败路由=回滚至上一检查点（git checkout 工作区"
        "回 CP1 状态）；类型=用户暂停（commit+push 不可逆前强制暂停）；goal "
        "anchoring=「原目标：分类维度汇总落地；当前位置：T2/T3 完成，待验证后"
        "进入提交」。",
        "密度论证（按可逆性×爆炸半径逐检查点给类型建议）：CP1 处改动=单文件"
        "工作区改动，git checkout 可回滚（可逆），爆炸半径=单模块导入面（小）"
        "→建议自动继续；CP2 后接 git commit+push（外发不可逆），爆炸半径=远端"
        "仓库历史（大）→建议用户暂停。全链除终态 commit 外均可逆，检查点密度"
        "=2/3 任务边界。",
        "红队条件未触发声明：并行组数=2、检查点数=2，均未超触发阈值（并行组"
        "≥4 或检查点≥5 才触发独立上下文红队），故本步无红队留痕，条件未触发"
        "声明如上。",
        "只提案不拍板确认：以上并行分组、检查点密度与类型（CP1 自动继续/CP2 "
        "用户暂停）均为提案——密度与类型是用户风险裁决项，待子5 用户拍板后"
        "才生效，本步不定案。q/a 按序对齐。",
    ],
}

# ---- 子3 clean：四类核验逐对象留痕 + 三态混合标注 + 只标注不裁决 ----
S3_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "ExecutionPlanCheckpoints",
    "sub_step": 3,
    "skill": "Bash(判据 dry-run / 交集实算) / codegraph / Read",
    "purpose": (
        "锚点核验与假设标注：逐对象核验四类——①判据可执行性（每检查点通过"
        "判据的命令实际 dry-run——存在且可运行，不验结果对错）；②互斥面机械"
        "核验（并行组内各 worker 改动文件清单集合交集实算——交集非空=分组"
        "证伪，回子2）；③锚点存在性（检查点位置引用的任务 ID/阶段边界/验收"
        "包 ID 在四源中真实存在，codegraph/Read 出处）；④验证手段有绑定"
        "（判据所需工具/skill 在能力包里有绑定且无「显式不加载」冲突）。"
        "三态标注：已验证（附出处）/假设（置信度+错误时影响）/证伪（回子2，"
        "附理由）。只标注不裁决——假设的接受留子5 用户裁决。"
    ),
    "q": [
        "①判据可执行性 dry-run 结果如何（CP1/CP2 判据命令逐一 dry-run）？",
        "②互斥面机械核验结果如何（并行组 L2 交集实算）？",
        "③锚点存在性核验结果如何（CP1/CP2 引用锚点四源存在）？",
        "④验证手段有绑定核验结果如何？三态标注与只标注不裁决确认了吗？",
    ],
    "a": [
        "①判据可执行性 dry-run 逐命令：CP1 判据=`python3 -c \"from paths import "
        "CATEGORY_SUMMARY_RESULT\"` --dry-run 实跑判据命令本身：Bash `python3 -c "
        "\"from paths import CATEGORY_SUMMARY_RESULT\"` 退出码 0（命令存在可运行，"
        "不验结果对错）——CP1 判据可执行性=已验证（出处=Bash 判据命令 dry-run 退出"
        "码 0）；CP2 判据=`pytest tests/test_summary_categories.py -x` --Bash "
        "`pytest --version` 退出码 0（pytest 命令存在可运行）；但判据命令依赖的"
        "测试文件 tests/test_summary_categories.py 需 TDD 先行生成，故 CP2 判据"
        "可执行性=假设（置信度中×影响中：错误时 execute 期该判据无可收集用例，"
        "需 TDD 先行补）。",
        "②互斥面机械核验：并行组 L2={T2,T3}，T2 改动文件清单="
        "{summary/generate_factor_summary_report.py}，T3 改动文件清单="
        "{summary/MODULE.md}；交集实算--Bash `python3 -c 'a={"
        "\\\"summary/generate_factor_summary_report.py\\\"};b={"
        "\\\"summary/MODULE.md\\\"};print(a&b)'` 返回 set()（交集=∅，并行分组"
        "未被证伪）——互斥面交集=已验证（出处=交集实算命令输出 set()）。",
        "③锚点存在性核验：CP1 引用 T1/阶段边界 L1/SC1——T1 在四源存在（Read "
        "plan.md:10 原文『新增 CATEGORY_SUMMARY_RESULT 路径常量』）；SC1 在四源"
        "存在（Read understand.md:31 原文『路径常量可导入』）；CP2 引用 T2/"
        "T3/SC2——T2 在四源存在（Read plan.md:12），T3 在四源存在（Read "
        "plan.md:14），SC2 在四源存在（Read understand.md:33 原文『报告含八维"
        "度汇总区块』）——锚点存在性=已验证（出处=Read plan.md/understand.md "
        "原文行）。",
        "④验证手段有绑定：绑定声明--CP1 判据所需 python3 在 plan:3 能力包有"
        "绑定；CP2 判据所需 pytest 在 plan:3 能力包有绑定；均无『显式不加载』"
        "冲突（出处=Read plan:3 能力节绑定清单）——验证手段绑定=已验证（绑定"
        "声明+出处）。三态混合总结：CP1 判据可"
        "执行性/互斥面交集/锚点存在性/验证手段绑定=已验证，CP2 判据可执行性=假设，"
        "无证伪项。只标注不裁决：假设接受与否留子5 用户裁决，本步只标注。四类"
        "核验逐对象留痕无遗漏，三态逐对象标注，q/a 按序对齐。",
    ],
}

S3_CLEAN = copy.deepcopy(S3_BASE)

# ---- vio1：声称可执行无 dry-run 留痕=编造--CP1/CP2 判据只称可运行无命令出处 ----
S3_VIO1 = copy.deepcopy(S3_BASE)
S3_VIO1["a"][0] = (
    "①判据可执行性 dry-run：CP1 判据=`python3 -c \"from paths import "
    "CATEGORY_SUMMARY_RESULT\"` 命令存在，可以直接跑；CP2 判据=`pytest "
    "tests/test_summary_categories.py -x` 命令可运行，pytest 环境没问题。"
    "三态：已验证。"
)

# ---- vio2：交集核验无实算输出=没真核验--称两 worker 文件不同交集为空，无实算 ----
S3_VIO2 = copy.deepcopy(S3_BASE)
S3_VIO2["a"][1] = (
    "②互斥面机械核验：并行组 L2={T2,T3}，T2 改报告脚本、T3 改文档，两个"
    "文件明显不同，交集为空，无公共文件，分组不冲突。三态：已验证。"
)

# ---- vio3：全对象无差别「已验证」=没真核验--四类核验同形泛化、无差异化留痕 ----
S3_VIO3 = copy.deepcopy(S3_BASE)
_SAME = (
    "核验：①判据命令可运行；②互斥面交集为空；③锚点存在；④验证手段已绑定。"
    "三态：全部已验证，无问题。"
)
S3_VIO3["a"][0] = "①" + _SAME
S3_VIO3["a"][1] = "②" + _SAME
S3_VIO3["a"][2] = "③" + _SAME
S3_VIO3["a"][3] = (
    "④验证手段已绑定。三态：全部已验证，无假设无证伪项，四类核验逐对象无"
    "遗漏，q/a 按序对齐。"
)

# ---- vio4：假设项缺置信度或影响--假设条目无置信度×影响标注 ----
S3_VIO4 = copy.deepcopy(S3_BASE)
S3_VIO4["a"][3] = (
    "④验证手段有绑定：CP1/CP2 判据所需工具 python3/pytest 在 plan:3 能力"
    "包有绑定。三态标注：CP1 判据可执行性=已验证（出处=Bash 判据命令 dry-run "
    "退出码 0）；CP2 判据可执行性=假设（pytest 命令存在但依赖测试文件 "
    "tests/test_summary_categories.py 需 TDD 先行生成）；互斥面交集=已验证（出处="
    "交集实算命令输出 set()）；锚点存在性=已验证（出处=Read plan.md/understand.md "
    "原文行）；验证手段绑定=已验证（出处=plan:3 能力包绑定声明）；无证伪项。"
    "只标注不裁决：假设接受与否留子5 用户裁决，本步只标注。四类核验逐对象留痕"
    "无遗漏，三态逐对象标注，q/a 按序对齐。"
)

# ---- vio5：漏对象核验--CP2 判据可执行性未单独核验，自称随 CP1 覆盖 ----
S3_VIO5 = copy.deepcopy(S3_BASE)
S3_VIO5["a"][0] = (
    "①判据可执行性 dry-run：CP1 判据=`python3 -c \"from paths import "
    "CATEGORY_SUMMARY_RESULT\"` --Bash `which python3` 返回 /usr/bin/python3"
    "（命令存在可运行）。CP2 判据 pytest 命令与 CP1 同 python 环境，随 CP1 "
    "核验覆盖，不单独 dry-run。三态：CP1 已验证（出处=Bash which python3）。"
)
S3_VIO5["a"][3] = (
    "④验证手段有绑定：CP1/CP2 判据所需工具 python3/pytest 在 plan:3 能力"
    "包有绑定。三态标注：CP1 判据可执行性=已验证；互斥面交集=已验证（出处="
    "交集实算命令输出 set()）；锚点存在性=已验证（出处=Read plan.md/"
    "understand.md 原文行）；验证手段绑定=已验证。无假设无证伪项。只标注不"
    "裁决：四类核验逐对象留痕无遗漏，三态逐对象标注，q/a 按序对齐。"
)

CASES = {
    "clean": S3_CLEAN,
    "vio1_声称可执行无dryrun": S3_VIO1,
    "vio2_交集无实算": S3_VIO2,
    "vio3_无差别已验证": S3_VIO3,
    "vio4_假设缺置信度影响": S3_VIO4,
    "vio5_漏对象核验": S3_VIO5,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}

# replace anchor 未命中时 vio 静默等于 clean——模块加载即断言，防哑弹载荷
for _k, _v in CASES.items():
    if _k != "clean":
        assert _v != S3_CLEAN, f"{_k} 与 clean 无差异——replace anchor 未命中"


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {
        k: "\n".join(json.dumps(t, ensure_ascii=False) for t in (S1_BASE, S2_BASE, s3))
        for k, s3 in CASES.items()
    }
    run_cases("plan:4#3 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
