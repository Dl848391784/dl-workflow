"""dl_dashboard.app：路由级测试（TestClient + tmp 项目）。"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from dl_dashboard.app import create_app
from dl_dashboard.config import DashboardConfig
from dl_dashboard.scanner import meta_root


@pytest.fixture()
def client(tmp_path):
    project = tmp_path / "proj"
    meta = meta_root(project, "demo")
    meta.mkdir(parents=True)
    (meta / "state.json").write_text(json.dumps({
        "name": "demo", "phase": "plan", "sub_index": 2, "sub_step_index": 1,
        "node": "plan:2", "gate": "pending", "held_for_gate": False,
        "updated_at": "t", "problem_statement": "Q", "history": [],
        "segment_sessions": [],
    }), encoding="utf-8")
    cfg = DashboardConfig(projects=(project,), host="127.0.0.1", port=0)
    app = create_app(cfg)
    return TestClient(app), project


def test_list_workflows(client):
    c, project = client
    r = c.get("/api/workflows")
    assert r.status_code == 200
    rows = r.json()["workflows"]
    assert len(rows) == 1 and rows[0]["name"] == "demo"
    assert rows[0]["node"] == "plan:2"
    assert rows[0]["driver_pid"] is None
    assert rows[0]["totals"]["cost_usd"] == 0


def test_index_and_artifact_inject_fresh_static_version(client):
    """静态版本戳 = 文件 mtime 动态注入——手工死戳（?v=be08209）不再出现，
    改静态文件后浏览器必拉新（metro 修复「没生效」实爆的根）。"""
    import re as _re

    c, _ = client
    r = c.get("/")
    assert r.status_code == 200
    vers = set(_re.findall(r"(?:app\.js|style\.css)\?v=([A-Za-z0-9]+)", r.text))
    assert vers and "be08209" not in vers
    r2 = c.get("/static/artifact.html")
    assert r2.status_code == 200
    vers2 = set(_re.findall(r"(?:app\.js|style\.css)\?v=([A-Za-z0-9]+)", r2.text))
    assert vers == vers2  # 双页同戳（同一份静态文件集合）


def test_detail(client):
    c, project = client
    r = c.get("/api/workflow", params={"project": str(project), "name": "demo"})
    assert r.status_code == 200
    d = r.json()
    assert d["info"]["name"] == "demo"
    assert d["stats"] == [] and d["need_user"] is None
    assert isinstance(d["log_tail"], str)
    # fixture：plan + gate=pending（闸门后置阶段）→ gate 可作用透传
    assert d["info"]["gate_actionable"] is True


# ---------- 问题卡步骤绑定 + 已答透传（dashboard-answered-marker-design） ----------


def _write_need_user(project, payload):
    (meta_root(project, "demo") / "need_user.json").write_text(
        json.dumps(payload), encoding="utf-8")


def test_detail_shows_bound_need_user_matching(client):
    c, project = client
    _write_need_user(project, {
        "questions": [{"question": "q", "header": "h"}],
        "ts": "T1", "node": "plan:2", "sub_step": 1,
    })
    d = c.get("/api/workflow", params={"project": str(project), "name": "demo"}).json()
    assert d["need_user"]["node"] == "plan:2"
    assert d["answered"] is None


def test_detail_hides_stale_bound_need_user(client):
    """绑定 ≠ state 当前位置 = 陈旧卡（已推进的步的问题）不渲染（D2）。"""
    c, project = client
    _write_need_user(project, {
        "questions": [{"question": "q", "header": "h"}],
        "ts": "T1", "node": "plan:1", "sub_step": 3,
    })
    d = c.get("/api/workflow", params={"project": str(project), "name": "demo"}).json()
    assert d["need_user"] is None
    assert d["inject_ready"] is False


def test_detail_legacy_unbound_need_user_shown(client):
    """旧格式无绑定字段 → 现状放行（legacy pin）。"""
    c, project = client
    _write_need_user(project, {
        "questions": [{"question": "q", "header": "h"}], "ts": "T1",
    })
    d = c.get("/api/workflow", params={"project": str(project), "name": "demo"}).json()
    assert d["need_user"] is not None


def _sha(questions) -> str:
    import hashlib
    return hashlib.sha1(
        json.dumps(questions, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _write_answered(project, node="plan:2", sub_step=1, at="2026-08-31T15:00:00",
                    questions=None):
    qs = questions if questions is not None else [{"question": "q", "header": "h"}]
    (meta_root(project, "demo") / "answered.json").write_text(json.dumps({
        "node": node, "sub_step": sub_step, "questions_sha": _sha(qs),
        "answered_at": at,
    }), encoding="utf-8")


def test_detail_answered_passthrough(client):
    c, project = client
    _write_need_user(project, {
        "questions": [{"question": "q", "header": "h"}],
        "ts": "T1", "node": "plan:2", "sub_step": 1,
    })
    _write_answered(project)
    d = c.get("/api/workflow", params={"project": str(project), "name": "demo"}).json()
    assert d["answered"] == "2026-08-31T15:00:00"


def test_inject_rejected_message_when_covered(client):
    """已覆盖时端点如实说「答案已提交」，不用「未就绪/恢复驱动」误导（E2 附修）。"""
    c, project = client
    _write_need_user(project, {
        "questions": [{"question": "q", "header": "h"}],
        "ts": "T1", "node": "plan:2", "sub_step": 1,
    })
    _write_answered(project)
    r = c.post("/api/inject", json={
        "project": str(project), "name": "demo", "answer": "又答一遍"})
    d = r.json()
    assert d["ok"] is False and "答案已提交" in d["msg"]


def test_project_whitelist_enforced(client):
    c, _ = client
    r = c.get("/api/workflow", params={"project": "/etc", "name": "x"})
    assert r.status_code == 403


def test_detail_rejects_path_traversal_name(client):
    c, project = client
    r = c.get("/api/workflow", params={"project": str(project), "name": "../../../etc"})
    assert r.status_code == 400
    assert "非法工作流名" in r.json()["detail"]


def test_detail_missing_workflow_returns_404(client):
    c, project = client
    r = c.get("/api/workflow", params={"project": str(project), "name": "missing"})
    assert r.status_code == 404


def test_post_endpoints_reject_path_traversal_name(client):
    c, project = client
    payload = {"project": str(project), "name": "../../../etc"}
    for path in ("/api/inject", "/api/gate", "/api/drive", "/api/dl"):
        body = {**payload, "answer": "x"} if path == "/api/inject" else payload
        if path == "/api/dl":
            body["cmd"] = "advance"
        r = c.post(path, json=body)
        assert r.status_code == 400, f"{path} should reject traversal name"
        assert "非法工作流名" in r.json()["detail"]


def test_post_dl_rejects_bad_cmd(client):
    c, project = client
    r = c.post("/api/dl", json={"project": str(project), "name": "demo", "cmd": "rm"})
    assert r.status_code == 200 and r.json()["ok"] is False


def test_post_gate_calls_action_and_redrives(client):
    c, project = client
    with patch("dl_dashboard.app.actions.gate_release", return_value=(True, "✓")) as gr, \
         patch("dl_dashboard.app.actions.restart_drive", return_value=(True, "ok")) as rd:
        r = c.post("/api/gate", json={"project": str(project), "name": "demo"})
    assert r.json()["ok"] is True
    gr.assert_called_once()
    rd.assert_called_once()


def _fake_request(disconnected_after: int = 0):
    """SSE 测试用 Request 替身：is_disconnected 第 N+1 次调用起返回 True。"""
    calls = {"n": 0}

    class _Req:
        async def is_disconnected(self):
            calls["n"] += 1
            return calls["n"] > disconnected_after

    return _Req()


def test_events_first_frame_via_generator(client):
    """StreamingResponse 在 TestClient 中会挂起；直接调用生成器取首帧。"""
    c, _ = client
    route = next(r for r in c.app.routes if getattr(r, "path", None) == "/api/events")

    async def _first():
        resp = await route.endpoint(_fake_request(disconnected_after=999))
        chunk = await anext(resp.body_iterator)
        await resp.body_iterator.aclose()
        return chunk

    chunk = asyncio.run(_first())
    assert chunk.startswith("data: ")
    payload = json.loads(chunk.removeprefix("data: "))
    assert "workflows" in payload


def test_events_generator_exits_on_disconnect(client):
    """客户端断连即退出生成器（evolution-up P0）——旧版 while True 无断连
    检测：最后一个标签页关闭后 server 仍每 2s 全量扫描空转，且 SSE 长连接
    不死是 SIGTERM 优雅退出被无限阻塞的温床。"""
    c, _ = client
    route = next(r for r in c.app.routes if getattr(r, "path", None) == "/api/events")

    async def _drain():
        resp = await route.endpoint(_fake_request(disconnected_after=1))
        chunks = [c_ async for c_ in resp.body_iterator]
        return chunks

    # 首帧发出后第二次循环即检测到断连 -> 生成器自然终止（不挂起）
    chunks = asyncio.run(asyncio.wait_for(_drain(), timeout=10))
    assert len(chunks) <= 2


def test_main_passes_graceful_shutdown_timeout(client):
    """SIGTERM 不死修复 pin：uvicorn 优雅退出必须有超时兜底——SSE 长连接
    在场时无 timeout = 无限等待（2026-09-02 两次 kill -9 实爆）。"""
    import dl_dashboard.app as app_mod

    captured = {}

    def _fake_run(app, **kwargs):
        captured.update(kwargs)

    with patch("uvicorn.run", _fake_run):
        app_mod.main()
    assert captured.get("timeout_graceful_shutdown") is not None
    assert captured["timeout_graceful_shutdown"] <= 5


def test_post_delete_calls_action(client):
    c, project = client
    with patch("dl_dashboard.app.actions.delete_workflow",
               return_value=(True, "已删除")) as dw:
        r = c.post("/api/delete", json={"project": str(project), "name": "demo"})
    assert r.json()["ok"] is True
    dw.assert_called_once()


def test_outputs_endpoint(client):
    c, project = client
    ev_dir = project / ".claude" / "evidence"
    ev_dir.mkdir(parents=True, exist_ok=True)
    (ev_dir / "demo.jsonl").write_text(
        '{"kind": "skill-trace", "major_stage": "Understand", "minor_stage": "X",'
        ' "sub_step": 1, "skill": "s", "purpose": "p", "q": [], "a": [], "结论": "c"}\n',
        encoding="utf-8",
    )
    r = c.get("/api/outputs", params={"project": str(project), "name": "demo"})
    assert r.status_code == 200
    d = r.json()
    assert len(d["evidence"]) == 1 and d["evidence"][0]["conclusion"] == "c"
    assert d["change_points"] == []
    assert d["artifacts"]["plans"]["exists"] is False


def test_artifact_endpoint_404_when_missing(client):
    c, project = client
    r = c.get("/api/artifact",
              params={"project": str(project), "name": "demo", "kind": "plans"})
    assert r.status_code == 404


def test_artifact_endpoint_rejects_bad_kind(client):
    c, project = client
    r = c.get("/api/artifact",
              params={"project": str(project), "name": "demo", "kind": "../etc"})
    assert r.status_code == 400


def test_artifact_html_endpoint_serves_html(client):
    # v0.3.0 人读版直投：dashboard 产物链接 md->html
    c, project = client
    d = project / ".claude" / "plans"
    d.mkdir(parents=True)
    (d / "demo.html").write_text("<html><body>人读版</body></html>", encoding="utf-8")
    r = c.get("/artifact-html",
              params={"project": str(project), "name": "demo", "kind": "plans"})
    assert r.status_code == 200
    assert "人读版" in r.text
    assert "text/html" in r.headers["content-type"]


def test_artifact_html_endpoint_404_when_missing(client):
    c, project = client
    r = c.get("/artifact-html",
              params={"project": str(project), "name": "demo", "kind": "plans"})
    assert r.status_code == 404


def test_artifact_html_endpoint_rejects_bad_kind(client):
    c, project = client
    r = c.get("/artifact-html",
              params={"project": str(project), "name": "demo", "kind": "../etc"})
    assert r.status_code == 400


def test_artifact_html_endpoint_serves_proposals(client):
    # v0.4.0 第三产物 kind：proposals（人读技术方案）同白名单直投
    c, project = client
    d = project / ".claude" / "proposals"
    d.mkdir(parents=True)
    (d / "demo.html").write_text("<html><body>技术方案</body></html>", encoding="utf-8")
    r = c.get("/artifact-html",
              params={"project": str(project), "name": "demo", "kind": "proposals"})
    assert r.status_code == 200
    assert "技术方案" in r.text


def test_post_pause_calls_action(client):
    c, project = client
    with patch("dl_dashboard.app.actions.pause_workflow",
               return_value=(True, "已暂停")) as pw:
        r = c.post("/api/pause", json={"project": str(project), "name": "demo"})
    assert r.json()["ok"] is True
    pw.assert_called_once()
