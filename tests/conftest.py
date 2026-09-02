"""pytest 全局限定（dl-workflow 测试套件）。"""

import pytest

import dl_flow_engine as eng

# 真函数留存：HTML 专项测试用它恢复真实行为（autouse 桩只挡默认路径）。
REAL_HTML_COMPANION = eng._render_html_companion


@pytest.fixture(autouse=True)
def _stub_html_companion(monkeypatch):
    """HTML 伴随导出默认打桩——套件零外部进程（真 bun 转换走 TestHtmlCompanion）。

    render_artifact 的 md 装配与 HTML 赠品是两件事；存量测试只断言 md 面，
    不为赠品付 bun/npx 探测 + 转换开销，也不受目标机依赖装没装影响。
    """
    monkeypatch.setattr(eng, "_render_html_companion", lambda md_path: "")
