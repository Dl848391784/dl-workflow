"""FastAPI 入口：路由 + SSE + 静态页。

运行：python3 -m dl_dashboard.app（读 ~/.dl-workflow/dashboard.toml）
写操作 per-workflow asyncio.Lock 串行化（防双击/多标签页并发注入）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import weakref
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from dl_dashboard import actions, metrics, scanner
from dl_dashboard.config import DashboardConfig, load_config
from dl_dashboard.driver_mgr import DriverManager

log = logging.getLogger("dl_dashboard")

DLWF = Path(__file__).resolve().parents[1]
CACHE_DIR = DLWF / "dashboard-cache"
RUNTIME_DIR = DLWF / "dashboard-run"
STATIC_DIR = Path(__file__).resolve().parent / "static"

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _name(raw: str) -> str:
    if not _NAME_RE.match(raw):
        raise HTTPException(400, f"非法工作流名: {raw!r}")
    return raw


def create_app(config: DashboardConfig | None = None) -> FastAPI:
    cfg = config or load_config()
    mgr = DriverManager(DLWF, RUNTIME_DIR)
    app = FastAPI(title="dl-workflow dashboard")
    locks = weakref.WeakValueDictionary()

    def _project(raw: str) -> Path:
        p = Path(raw)
        if p not in cfg.projects:
            raise HTTPException(403, f"项目未登记: {raw}")
        return p

    def _lock(project: Path, name: str) -> asyncio.Lock:
        return locks.setdefault(f"{project}::{name}", asyncio.Lock())

    def _row(info: scanner.WorkflowInfo) -> dict:
        project = Path(info.project)
        stats = []
        if info.error is None:
            try:
                stats = metrics.collect_stats(project, info.name, CACHE_DIR)
            except Exception as exc:  # noqa: BLE001 - 统计降级不拖垮列表，error 暴露
                log.warning("collect_stats 失败 %s: %s", info.name, exc)
        return {
            **asdict(info),
            "driver_pid": mgr.alive(project, info.name),
            "totals": metrics.totals(stats),
        }

    def _snapshot() -> dict:
        return {"workflows": [_row(i) for i in scanner.scan_all(cfg.projects)]}

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/workflows")
    def list_workflows():
        return _snapshot()

    @app.get("/api/workflow")
    def detail(project: str, name: str):
        proj = _project(project)
        name = _name(name)
        try:
            info = scanner.scan_workflow(proj, name)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        stats = []
        try:
            stats = metrics.collect_stats(proj, name, CACHE_DIR)
        except Exception as exc:  # noqa: BLE001 - 统计降级不拖垮详情页，error 暴露
            log.warning("collect_stats 失败 %s/%s: %s", proj, name, exc)
        nu_p = scanner.meta_root(proj, name) / "need_user.json"
        need_user = None
        if nu_p.exists():
            try:
                need_user = json.loads(nu_p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                need_user = {"error": "need_user.json 解析失败"}
        slug = mgr.slug(proj, name)
        log_p = mgr.log_path(slug)
        log_tail = ""
        if log_p.exists():
            with open(log_p, "rb") as fh:
                fh.seek(0, 2)
                size = fh.tell()
                fh.seek(max(0, size - 8192))
                log_tail = fh.read().decode("utf-8", errors="replace")[-4000:]
        return {
            "info": asdict(info),
            "stats": [asdict(s) for s in stats],
            "totals": metrics.totals(stats),
            "need_user": need_user,
            "driver_pid": mgr.alive(proj, name),
            "log_tail": log_tail,
        }

    @app.post("/api/create")
    async def create(body: dict):
        proj = _project(body["project"])
        name = _name(body["name"])
        async with _lock(proj, name):
            ok, msg = await asyncio.to_thread(
                actions.create_workflow, proj, name, body["statement"], mgr)
        return {"ok": ok, "msg": msg}

    @app.post("/api/inject")
    async def inject(body: dict):
        proj = _project(body["project"])
        name = _name(body["name"])
        async with _lock(proj, name):
            ok, msg = await asyncio.to_thread(
                actions.inject_answer, proj, name, body["answer"])
            if ok:
                await asyncio.to_thread(actions.restart_drive, proj, name, mgr)
        return {"ok": ok, "msg": msg}

    @app.post("/api/gate")
    async def gate(body: dict):
        proj = _project(body["project"])
        name = _name(body["name"])
        async with _lock(proj, name):
            ok, msg = await asyncio.to_thread(actions.gate_release, proj, name)
            if ok:
                await asyncio.to_thread(actions.restart_drive, proj, name, mgr)
        return {"ok": ok, "msg": msg}

    @app.post("/api/drive")
    async def drive(body: dict):
        proj = _project(body["project"])
        name = _name(body["name"])
        async with _lock(proj, name):
            ok, msg = await asyncio.to_thread(
                actions.restart_drive, proj, name, mgr)
        return {"ok": ok, "msg": msg}

    @app.post("/api/dl")
    async def dl(body: dict):
        proj = _project(body["project"])
        name = _name(body["name"])
        async with _lock(proj, name):
            ok, msg = await asyncio.to_thread(
                actions.dl_command, proj, name, body["cmd"], body.get("value"))
        return {"ok": ok, "msg": msg}

    @app.get("/api/events")
    async def events():
        async def gen():
            while True:
                snap = await asyncio.to_thread(_snapshot)
                yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
                await asyncio.sleep(2)
        return StreamingResponse(gen(), media_type="text/event-stream")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = load_config()
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    main()
