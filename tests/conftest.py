"""pytest 全局夹具：环境变量快照复位（顺序污染防线）。

2026-09-17 实证：TestApplyInstanceEngine.test_state_engine_normalized_to_env
调 dl_drive._apply_instance_engine——生产代码直写 os.environ["DL_ENGINE"]，
monkeypatch 只追踪自己的 set/del、不追踪生产侧直写 → DL_ENGINE=qodercli 泄漏
到后续全部测试（全量 25 挂：transcript 根错走 ~/.qoder/projects，
TestSubagentRetryStats/TestIngestAgentReport/TestStopStdoutPureJson 等）。
逐测试快照复位，任何生产/测试侧 env 直写都拦在单测内（同类污染通用防线，
不止 DL_ENGINE 一例）。
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _restore_environ():
    saved = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)
