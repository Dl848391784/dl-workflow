#!/usr/bin/env python3
"""plan:2#3 锚点核验 gate 回归重放（framing 反转的回归资产，
designs/plan2-sub3-gate-framing-design.md）。

**plan:2（拆解任务与阶段）第三个反转节点**。命题性质=锚点核验与三态标注
（对子2 执行单元逐单元做四类核验：文件/symbol 存在、测试接缝、验证命令、
No Placeholders 检出；三态=已验证/假设/证伪），主敌=「执行接地失守」——
锚点编造会被零上下文 executor 当事实消费并沿链放大。

clean（承接 plan:2#2 切分排序 U1/U2/U3：逐单元四类核验留痕[test -f /
codegraph / pytest --collect-only / 命令干跑各附命令+返回概述]、三态混合
标注[已验证附出处+一条假设附置信度×影响]、No Placeholders 四模式扫描零
命中、只标注不裁决）/
vio1 声称存在无出处=编造（U2 称 symbol 存在却无命令/路径出处）/
vio2 全单元无差别「已验证」=没真核验（三单元核验文本同形泛化、零假设）/
vio3 placeholder 模式残留（U2 单元含「加适当错误处理」「写上述的测试」）/
vio4 假设项缺置信度或影响（U3 假设无置信度×影响标注）/
vio5 漏单元核验（只核验 U1/U2，U3 无任何核验留痕，自称三单元全覆盖）。

vio 载荷保真度（#30 ㊷）：单概念越界，其余维度保持合规——vio1 只换 U2
symbol 核验行去出处；vio2 只换 a[0]-a[2] 为同形泛化已验证；vio3 只在 a[1]
U2 段残留 placeholder 词形；vio4 只换 a[2] 假设标注去置信度×影响；vio5 只
删 U3 核验段改自称全覆盖。

artifact=子1+子2+子3 最新 trace 拼合（生产 read_evidence_for_step(3,
"TaskBreakdown") 同形——本 gate「每单元四类核验」须对照 S2 单元集，S2 是
判材非纯组成事实；codegraph db / 文件系统真值不可见=只判留痕在场不核真值）。

vio4 设计内委托（#30 ㉗）：「假设缺置信度/影响」由 assumption_completeness_trace
mech 承托（v1-v3 judge 橡皮图章 1-5/6，⑭ 注意力方差），gate 方框四声明「已机械
校验、不得以此 block」。replay judge-only 读数 vio4 = 0/6 是设计内（生产墙=mech
先拒），EXPECT 仍标 BLOCK--勿把设计内读数当回归。同 plan:2#2 vio5 / u:2#3 范式。

用法: python3 tests/replays/replay_plan2_sub3.py [N] [gate_file]
"""

import copy
import json
import sys

from _common import run_cases, setup_env, sub_step

LABEL = "拆解任务与阶段 · 子步骤3"
STEP = sub_step("plan:2", 2)

# ---- 子1 trace（元素基线：E1/E2/E3+验收包+假设，压缩自 replay_plan2_sub1.py clean）----
S1_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "TaskBreakdown",
    "sub_step": 1,
    "skill": "Read(design.md / understand.md) / Bash(grep evidence 设计包 trace)",
    "purpose": (
        "设计包清点与追溯基线：三清单齐备（要素/验收包/假设）；每条附出处"
        "且要素原文引用进 trace 正文；新增候选/矛盾显式「无」；只提取不创作。"
    ),
    "q": [
        "①原子改动要素清单（file->function->改动类型，逐条赋 ID）如何？每条附出处与原文吗？",
        "②验收包清单（逐条 SuccessCriteria 附 ID）如何？",
        "③假设清单（置信度×影响，原样转录）如何？",
        "新增候选/设计包内部矛盾标注了吗？只提取不创作确认了吗？",
    ],
    "a": [
        "①要素清单三条：E1=`summary/generate_factor_summary_report.py` "
        "`_aggregate_positive_ic` 统计函数内增加 FACTOR_CATEGORIES 维度分组键"
        "（改）--出处 design.md:12，原文『在既有聚合统计函数内增加 "
        "FACTOR_CATEGORIES 维度分组键，复用 factor_definitions.py 映射做 group "
        "key』；E2=`summary/report/sections.py` `_generate_ic_section` 内增加"
        "八维度汇总区块渲染（改）--出处 design.md:14，原文『_generate_ic_section "
        "内新增八维度汇总区块』；E3=`paths.py` 增加 `CATEGORY_SUMMARY_RESULT` "
        "路径常量（增）--出处 design.md:16，原文『新增 CATEGORY_SUMMARY_RESULT "
        "路径常量』。",
        "②验收包三条：SC1.1『报告展示八维度条数+占比可读出』（design.md:20）；"
        "SC2.1『分组口径与 FACTOR_CATEGORIES 映射一致可核对』（design.md:21）；"
        "SC3.1『交付形态=报告新增八维度汇总区块』（design.md:22）。",
        "③假设一条：H1=FACTOR_CATEGORIES 八维度对全 34 项因子覆盖无遗漏"
        "（置信度中×影响中，原样转录 design.md:25）。",
        "新增候选：显式『无』--三要素均提取自 design.md；设计包内部矛盾：显式"
        "『无』；只提取不创作，未混入 design.md 之外的要素，q/a 按序对齐。",
    ],
}

# ---- 子2 trace（切分排序：U1/U2/U3 纵向切片，压缩自 replay_plan2_sub2.py clean）----
S2_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "TaskBreakdown",
    "sub_step": 2,
    "skill": "superpowers:writing-plans(粒度与切片原则) / codegraph callers/impact / 推理(拓扑排序)",
    "purpose": (
        "任务切分与依赖排序：执行单元切分（纵向切片优先）；每单元附 H9 预算"
        "+承接要素 ID+依赖出处；依赖 DAG 拓扑排序留痕；TDD 序内嵌；阶段划分"
        "附断点验证方法或②论证；要素 ID 覆盖无漏；只提案不拍板。"
    ),
    "q": [
        "执行单元切分如何（每单元 H9 预算+承接要素 ID+依赖出处）？纵向切片优先吗？",
        "依赖 DAG 拓扑排序留痕如何（被依赖者先行，codegraph 取证）？TDD 序内嵌如何？",
        "阶段划分与断点验证方法如何（或②单阶段不可拆论证）？",
        "要素 ID 覆盖核对？只提案不拍板确认了吗？",
    ],
    "a": [
        "执行单元切分（纵向切片优先，每单元自带完整测试周期且值得 reviewer "
        "门禁）：U1=`paths.py` 增加 `CATEGORY_SUMMARY_RESULT` 路径常量（承接 "
        "E3，改）--H9 预算 1 文件 ~5 行，无依赖（基础）；U2=`summary/"
        "generate_factor_summary_report.py` `_aggregate_positive_ic` 增加 "
        "FACTOR_CATEGORIES 分组键（承接 E1，改）--H9 预算 1 文件 ~30 行，依赖 "
        "U1（消费 CATEGORY_SUMMARY_RESULT 做分组输出路径）；U3=`summary/report/"
        "sections.py` `_generate_ic_section` 增加八维度汇总区块渲染（承接 E2，"
        "改）--H9 预算 1 文件 ~40 行，依赖 U2（消费聚合后的分组数据）。三单元"
        "均纵向切片，非横向按层切。",
        "依赖 DAG 拓扑排序留痕（被依赖者先行）：U1（无依赖，基础）-> U2"
        "（依赖 U1）-> U3（依赖 U2），拓扑序 U1->U2->U3。codegraph "
        "callers 取证：`codegraph callers _aggregate_positive_ic` 确认 U2 改动"
        "点被依赖方无遗漏；`codegraph impact CATEGORY_SUMMARY_RESULT` 确认 U1 "
        "新常量消费方。TDD 序内嵌：每单元 failing test 先行--U1 先写断言常量"
        "存在的失败测试，U2 先写断言分组输出结构的失败测试，U3 先写断言区块"
        "渲染的失败测试。",
        "阶段划分：单阶段（U1+U2+U3 同属一个纵向切片）。②单阶段不可拆论证："
        "三单元合计 3 文件 ~75 行，H9 内（≤3 文件 ≤200 行）一次可完。断点验证"
        "方法（提案）：阶段末跑 `python3 scripts/generate_factor_summary_report.py "
        "--read default` + 断言报告含八维度汇总区块（待子5 用户裁决）。",
        "要素 ID 覆盖核对：E1->U2、E2->U3、E3->U1，三要素全覆盖无漏。只提案"
        "不拍板：断点位置/阶段粒度均为提案，待子5 用户裁决，q/a 按序对齐。",
    ],
}

# ---- 子3 clean：逐单元四类核验留痕 + 三态混合标注 + placeholder 零命中 ----
S3_BASE = {
    "kind": "skill-trace",
    "major_stage": "Plan",
    "minor_stage": "TaskBreakdown",
    "sub_step": 3,
    "skill": "codegraph / Bash(test -f / pytest --collect-only / 命令干跑) / Read",
    "purpose": (
        "锚点核验与假设标注：逐单元核验四类——①目标文件/symbol 存在；②测试"
        "接缝存在（pytest --collect-only 类手段留痕）；③验证命令可运行；"
        "④No Placeholders 检出。三态标注：已验证（附出处）/假设（置信度+错误"
        "时影响）/证伪（回子2 重切，附理由）。只标注不裁决——假设的接受留"
        "子5 用户裁决。"
    ),
    "q": [
        "U1 四类核验留痕如何（文件/symbol/测试接缝/验证命令）？三态标注？",
        "U2 四类核验留痕如何？三态标注？",
        "U3 四类核验留痕如何？三态标注？",
        "No Placeholders 检出结果？只标注不裁决确认了吗？",
    ],
    "a": [
        "U1 核验：①文件存在--Bash `test -f /home/admin/projects/factor_ic_"
        "analyzer/paths.py && echo EXISTS` 返回 EXISTS；新增常量无既有 symbol "
        "可查，命名冲突核验--Bash `grep -n CATEGORY_SUMMARY_RESULT /home/admin/"
        "projects/factor_ic_analyzer/paths.py` 返回空（无重复定义）；"
        "②测试接缝存在--Bash `python3 -m pytest tests/test_paths.py "
        "--collect-only -q` 返回 12 个用例，可挂新断言；③验证命令可运行--"
        "Bash `python3 -c \"import paths\"` 返回 0。④No Placeholders：本单元扫描四模式零命中。三态：已验证（出处=上述 "
        "Bash 命令返回）。",
        "U2 核验：①文件存在--Bash `test -f /home/admin/projects/factor_ic_"
        "analyzer/summary/generate_factor_summary_report.py && echo EXISTS` 返回 "
        "EXISTS；symbol `_aggregate_positive_ic` 存在--Bash `codegraph callers "
        "_aggregate_positive_ic` 返回 3 个调用节点；②测试接缝存在--Bash "
        "`python3 -m pytest tests/test_generate_factor_summary_report.py "
        "--collect-only -q` 返回 8 个用例；③验证命令可运行--Bash `python3 "
        "scripts/generate_factor_summary_report.py --help` 返回 0。④No Placeholders：本单元扫描四模式零命中。三态：已验证"
        "（出处=上述 Bash 命令返回）。",
        "U3 核验：①文件存在--Bash `test -f /home/admin/projects/factor_ic_"
        "analyzer/summary/report/sections.py && echo EXISTS` 返回 EXISTS；"
        "symbol `_generate_ic_section` 存在--Bash `codegraph callers "
        "_generate_ic_section` 返回 2 个调用节点；②测试接缝存在--Bash "
        "`python3 -m pytest tests/test_sections.py --collect-only -q` 返回 5 个"
        "用例；③验证命令可运行--Bash `python3 -c \"from summary.report.sections import _generate_ic_section\"` 返回 0。三态："
        "文件/symbol/命令三项已验证（出处=上述命令返回）；一项假设--`_generate_"
        "ic_section` 内插入新区块渲染不破坏既有布局（置信度高×影响低：错误时"
        "仅新区块缺失，报告其余部分不受影响，可回滚）。④No Placeholders：本单元扫描四模式零命中。",
        "No Placeholders 汇总：三单元各扫描四模式零命中（见各单元④条），扫描「加适当错误处理/处理边界情况/写上述"
        "的测试/类似任务 N」四模式，零命中。只标注不裁决：U3 的假设项接受与否"
        "留子5 用户裁决，本步只标注。三单元四类核验无遗漏，三态逐单元标注，"
        "q/a 按序对齐。",
    ],
}

S3_CLEAN = copy.deepcopy(S3_BASE)

# ---- vio1：声称存在无出处=编造--U2 称 symbol 存在却无命令/路径出处 ----
S3_VIO1 = copy.deepcopy(S3_BASE)
S3_VIO1["a"][1] = (
    "U2 核验：①目标文件 summary/generate_factor_summary_report.py 存在，"
    "`_aggregate_positive_ic` 函数就在里面，可以直接改；②测试接缝存在，"
    "测试文件里可以加断言；③验证命令可以跑。三态：已验证。"
)

# ---- vio2：全单元无差别「已验证」=没真核验--三单元同形泛化、零假设 ----
S3_VIO2 = copy.deepcopy(S3_BASE)
_SAME = (
    "核验：①目标文件/symbol 存在；②测试接缝存在；③验证命令可运行；"
    "④无 placeholder。三态：全部已验证，无问题。"
)
S3_VIO2["a"][0] = "U1 " + _SAME
S3_VIO2["a"][1] = "U2 " + _SAME
S3_VIO2["a"][2] = "U3 " + _SAME
S3_VIO2["a"][3] = (
    "No Placeholders 检出：四模式零命中。三单元全部已验证，无假设无证伪项，"
    "q/a 按序对齐。"
)

# ---- vio3：placeholder 模式残留--U2 单元含「加适当错误处理」「写上述的测试」 ----
S3_VIO3 = copy.deepcopy(S3_BASE)
S3_VIO3["a"][1] = (
    "U2 核验：①文件存在--Bash `test -f /home/admin/projects/factor_ic_"
    "analyzer/summary/generate_factor_summary_report.py && echo EXISTS` 返回 "
    "EXISTS；symbol `_aggregate_positive_ic` 存在--Bash `codegraph callers "
    "_aggregate_positive_ic` 返回 3 个调用节点；②测试接缝存在--Bash "
    "`python3 -m pytest tests/test_generate_factor_summary_report.py "
    "--collect-only -q` 返回 8 个用例；③验证命令可运行--Bash `python3 "
    "scripts/generate_factor_summary_report.py --help` 返回 0。单元内容：给 "
    "`_aggregate_positive_ic` 加分组键，加适当错误处理，写上述的测试。"
    "三态：已验证（出处=上述 Bash 命令返回）。"
)
S3_VIO3["a"][3] = (
    "No Placeholders 检出：逐单元扫描四模式，零命中。只标注不裁决：U3 的"
    "假设项接受与否留子5 用户裁决，本步只标注。三单元四类核验无遗漏，"
    "三态逐单元标注，q/a 按序对齐。"
)

# ---- vio4：假设项缺置信度或影响--U3 假设无置信度×影响标注 ----
S3_VIO4 = copy.deepcopy(S3_BASE)
S3_VIO4["a"][2] = (
    "U3 核验：①文件存在--Bash `test -f /home/admin/projects/factor_ic_"
    "analyzer/summary/report/sections.py && echo EXISTS` 返回 EXISTS；"
    "symbol `_generate_ic_section` 存在--Bash `codegraph callers "
    "_generate_ic_section` 返回 2 个调用节点；②测试接缝存在--Bash "
    "`python3 -m pytest tests/test_sections.py --collect-only -q` 返回 5 个"
    "用例；③验证命令可运行--Bash `python3 -c \"from summary.report.sections import _generate_ic_section\"` 返回 0。三态："
    "文件/symbol/命令三项已验证（出处=上述命令返回）；一项假设--`_generate_"
    "ic_section` 内插入新区块渲染不破坏既有布局。④No Placeholders：本单元"
    "扫描四模式零命中。"
)

# ---- vio5：漏单元核验--只核验 U1/U2，U3 无留痕，自称三单元全覆盖 ----
S3_VIO5 = copy.deepcopy(S3_BASE)
S3_VIO5["a"][2] = (
    "U3 无单独核验段--其改动与 U2 同报告管线，随 U2 核验覆盖。三态：同 U2 "
    "已验证。"
)
S3_VIO5["a"][3] = (
    "No Placeholders 检出：逐单元扫描四模式，零命中。只标注不裁决。三单元"
    "四类核验全覆盖无遗漏，三态逐单元标注，q/a 按序对齐。"
)

CASES = {
    "clean": S3_CLEAN,
    "vio1_声称存在无出处": S3_VIO1,
    "vio2_无差别已验证": S3_VIO2,
    "vio3_placeholder残留": S3_VIO3,
    "vio4_假设缺置信度影响": S3_VIO4,
    "vio5_漏单元核验": S3_VIO5,
}
EXPECT = {"clean": True, **{k: False for k in CASES if k != "clean"}}


def main():
    setup_env()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gate = open(sys.argv[2]).read() if len(sys.argv) > 2 else None
    arts = {
        k: "\n".join(json.dumps(t, ensure_ascii=False) for t in (S1_BASE, S2_BASE, s3))
        for k, s3 in CASES.items()
    }
    run_cases("plan:2#3 replay", STEP, LABEL, arts, EXPECT, n=n, gate=gate)


if __name__ == "__main__":
    main()
