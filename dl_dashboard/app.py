"""FastAPI 入口：路由 + SSE + 静态页。

运行：python3 -m dl_dashboard.app（读 ~/.dl-workflow/dashboard.toml）
写操作 per-workflow asyncio.Lock 串行化（防双击/多标签页并发注入）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import weakref
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from dl_dashboard import actions, metrics, outputs, scanner
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


def _capture_provider(name: str) -> dict[str, str] | None:
    """source bashrc 调 ac-* 函数并捕获其 ANTHROPIC_*/CLAUDE_* env。

    bashrc 函数不可被 launcher 子进程 exec（dl-launch.sh 头注释），故在
    server 侧捕获后随 driver spawn env 传递——与终端 export 后 `dl` 等价。
    """
    try:
        p = subprocess.run(
            ["bash", "-c", f"source ~/.bashrc 2>/dev/null; {name} >/dev/null 2>&1; env"],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        log.warning("provider env 捕获失败: %s", name, exc_info=True)
        return None
    env: dict[str, str] = {}
    for line in p.stdout.splitlines():
        k, _, v = line.partition("=")
        if k.startswith(("ANTHROPIC_", "CLAUDE_")):
            env[k] = v
    return env or None


def create_app(config: DashboardConfig | None = None) -> FastAPI:
    cfg = config or load_config()
    mgr = DriverManager(DLWF, RUNTIME_DIR)
    app = FastAPI(title="dl-workflow dashboard")
    locks = weakref.WeakValueDictionary()
    # provider 注册表：名字 -> env（None = 继承 server 环境）
    providers: dict[str, dict | None] = {}
    for name in cfg.providers:
        env = _capture_provider(name)
        if env:
            providers[name] = env

    def _provider_file(proj: Path, name: str) -> Path:
        return RUNTIME_DIR / f"{mgr.slug(proj, name)}.provider"

    def _driver_env(proj: Path, name: str) -> dict | None:
        """该工作流登记过的 provider env（创建时落 .provider 文件）。"""
        pf = _provider_file(proj, name)
        if pf.exists():
            return providers.get(pf.read_text(encoding="utf-8").strip())
        return None

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
        return {
            "workflows": [_row(i) for i in scanner.scan_all(cfg.projects)],
            "projects": [str(p) for p in cfg.projects],
            "providers": list(providers.keys()),
        }

    def _static_ver() -> str:
        """静态资源版本戳 = 静态文件最新 mtime_ns——随代码变更自动失效。

        旧版 ?v=<git sha> 是手工敲进 html 的死值，改 app.js/style.css 不更新
        → 浏览器按旧 URL 命中缓存，新静态文件永远不可见（metro 修复「没
        生效」实爆）。serve 时逐请求注（3 次 stat，成本可忽略），免人工纪律。
        """
        return str(
            max(
                p.stat().st_mtime_ns
                for p in STATIC_DIR.iterdir()
                if p.is_file()
            )
        )

    def _serve_html(fname: str) -> HTMLResponse:
        """读 html 注入新鲜版本戳（?v= 死值/旧值一律替换）。"""
        html = re.sub(
            r"((?:app\.js|style\.css|artifact\.html)\?v=)[A-Za-z0-9]+",
            lambda m: f"{m.group(1)}{_static_ver()}",
            (STATIC_DIR / fname).read_text(encoding="utf-8"),
        )
        return HTMLResponse(
            html, headers={"Cache-Control": "no-cache, must-revalidate"}
        )

    @app.get("/")
    def index():
        # no-cache：HTML 是静态资源版本号的唯一引用源，它自己被缓存
        # 会让版本号机制失效（用户看到旧 CSS/JS 的实爆教训）
        return _serve_html("index.html")

    @app.get("/static/artifact.html")
    def artifact_page():
        # 产物阅读页同样带 ?v= 死值——与首页同通道注戳（先于 /static 挂载
        # 注册，优先命中）
        return _serve_html("artifact.html")

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
        # 陈旧卡过滤（dashboard-answered-marker-design §2.3）——规则单源 =
        # scanner.need_user_stale（与 scan bool/侧栏等待态同口径）；解析失败
        # 的错误卡不过滤（stale 判定需要合法 dict）
        if (isinstance(need_user, dict) and "questions" in need_user
                and scanner.need_user_stale(
                    need_user, {"node": info.node,
                                "sub_step_index": info.sub_step_index})):
            need_user = None
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
            "inject_ready": actions.inject_ready(proj, name) if need_user else False,
            "answered": actions.answered_at_if_covers(proj, name),
            "driver_pid": mgr.alive(proj, name),
            "log_tail": log_tail,
            "artifacts": outputs.artifact_status(proj, name),
        }

    @app.post("/api/create")
    async def create(body: dict):
        proj = _project(body["project"])
        name = _name(body["name"])
        provider = body.get("provider")
        if provider and provider not in providers:
            return {"ok": False, "msg": f"未知 provider {provider}（可选：{'/'.join(providers)}）"}
        async with _lock(proj, name):
            ok, msg = await asyncio.to_thread(
                actions.create_workflow, proj, name, body["statement"], mgr,
                body.get("scope", "fermate"), bool(body.get("tacet")),
                providers.get(provider) if provider else None)
            if ok and provider:
                _provider_file(proj, name).write_text(provider, encoding="utf-8")
        return {"ok": ok, "msg": msg}

    @app.post("/api/inject")
    async def inject(body: dict):
        proj = _project(body["project"])
        name = _name(body["name"])
        async with _lock(proj, name):
            # 时序铁律（两轮实爆）：
            # 1) 未就绪（needuser 段在飞/未落台账）禁停禁注——停 driver 会杀掉
            #    正在备题的段，且注入无目标必中止
            # 2) 就绪且 driver 活：先停 driver 再注入（防注入段与活 driver
            #    抢同一会话被 SIGTERM rc=143）
            if not actions.inject_ready(proj, name):
                # 已覆盖 = 答案在处理中——如实说，别用「未就绪」误导（E2 附修）
                covered = actions.answered_at_if_covers(proj, name)
                if covered:
                    return {"ok": False,
                            "msg": f"答案已提交（{covered}）——模型处理中，"
                                   "门控通过后自动推进，无需重复提交"}
                return {"ok": False,
                        "msg": "交互段未就绪——问题还在准备或 driver 已停，"
                               "稍候重试；driver 已停请先「恢复驱动」"}
            if mgr.alive(proj, name):
                mgr.stop(proj, name)
            ok, msg = await asyncio.to_thread(
                actions.inject_answer, proj, name, body["answer"],
                _driver_env(proj, name))
            if ok:
                await asyncio.to_thread(
                    actions.restart_drive, proj, name, mgr, _driver_env(proj, name))
        return {"ok": ok, "msg": msg}

    @app.post("/api/gate")
    async def gate(body: dict):
        proj = _project(body["project"])
        name = _name(body["name"])
        async with _lock(proj, name):
            ok, msg = await asyncio.to_thread(actions.gate_release, proj, name)
            if ok:
                await asyncio.to_thread(
                    actions.restart_drive, proj, name, mgr, _driver_env(proj, name))
        return {"ok": ok, "msg": msg}

    @app.post("/api/drive")
    async def drive(body: dict):
        proj = _project(body["project"])
        name = _name(body["name"])
        async with _lock(proj, name):
            ok, msg = await asyncio.to_thread(
                actions.restart_drive, proj, name, mgr, _driver_env(proj, name))
        return {"ok": ok, "msg": msg}

    @app.get("/api/outputs")
    def outputs_ep(project: str, name: str):
        proj = _project(project)
        name = _name(name)
        return {
            "evidence": outputs.load_evidence(proj, name),
            "change_points": outputs.load_change_points(proj, name),
            "artifacts": outputs.artifact_status(proj, name),
        }

    @app.get("/api/artifact")
    def artifact_ep(project: str, name: str, kind: str):
        proj = _project(project)
        name = _name(name)
        try:
            content = outputs.load_artifact(proj, name, kind)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if content is None:
            raise HTTPException(404, f"产物 {kind}/{name}.md 不存在")
        return {"content": content}

    @app.get("/artifact-html")
    def artifact_html_ep(project: str, name: str, kind: str):
        """产物人读版 HTML 直投（v0.3.0 render-artifact 伴随导出）。

        kind 白名单 + _name 校验决定完整路径，无用户可控路径段，同
        load_artifact 的防穿越姿势。不存在 404（前端 artLink 按
        artifact_status.html_exists 决定链向，正常不会打到这）。
        """
        if kind not in ("understands", "plans"):
            raise HTTPException(400, f"未知产物类型: {kind}")
        proj = _project(project)
        name = _name(name)
        p = proj / ".claude" / kind / f"{name}.html"
        if not p.exists():
            raise HTTPException(404, f"产物 {kind}/{name}.html 不存在")
        return FileResponse(p, media_type="text/html")

    @app.post("/api/pause")
    async def pause(body: dict):
        proj = _project(body["project"])
        name = _name(body["name"])
        async with _lock(proj, name):
            ok, msg = await asyncio.to_thread(actions.pause_workflow, proj, name, mgr)
        return {"ok": ok, "msg": msg}

    @app.post("/api/delete")
    async def delete(body: dict):
        proj = _project(body["project"])
        name = _name(body["name"])
        async with _lock(proj, name):
            ok, msg = await asyncio.to_thread(actions.delete_workflow, proj, name, mgr)
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
