"""FastAPI application exposing the Pi remote-control protocol over HTTP."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from pi_remote_core import config, system_info
from pi_remote_core.command_buttons import load_buttons, save_buttons
from pi_remote_core.commands import CommandHandler

from .auth import COOKIE_NAME, make_token, verify_token
from .kindle import (
    DEFAULT_HEIGHT as CHEAP_DEFAULT_HEIGHT,
    DEFAULT_WIDTH as CHEAP_DEFAULT_WIDTH,
    find_chromium,
    render_screenshot,
)
from .kindle_html import render_dashboard_html, wrap_with_refresh
from .pty_shell import PtyProcess, pump_pty_to_callback

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


# --------------------------------------------------------------------------- #
# Server-side history buffer (used by the Kindle screenshot path so charts
# show a real line on first paint instead of an empty axis).
# --------------------------------------------------------------------------- #


_history: "deque[dict]" = deque(maxlen=config.MONITOR_HISTORY_POINTS)
_sampler_task: Optional[asyncio.Task] = None


async def _history_sampler() -> None:
    """Periodically push monitor_snapshot() onto the ring buffer."""
    while True:
        try:
            _history.append(system_info.monitor_snapshot())
        except Exception:  # pylint: disable=broad-except
            log.exception("monitor sampler failed")
        await asyncio.sleep(config.STATUS_INTERVAL_SECONDS)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    global _sampler_task
    _sampler_task = asyncio.create_task(_history_sampler())
    try:
        yield
    finally:
        if _sampler_task:
            _sampler_task.cancel()


app = FastAPI(
    title="Raspberry Pi Remote Control",
    docs_url=None,
    redoc_url=None,
    lifespan=_lifespan,
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# --------------------------------------------------------------------------- #
# auth helpers
# --------------------------------------------------------------------------- #


def _session_ok(token: Optional[str]) -> bool:
    return verify_token(token)


def require_session(session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME)) -> str:
    if not _session_ok(session):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login required")
    return session  # type: ignore[return-value]


def _set_session_cookie(response: Response) -> None:
    token = make_token()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=config.WEB_SESSION_HOURS * 3600,
        httponly=True,
        samesite="lax",
    )


# --------------------------------------------------------------------------- #
# pages
# --------------------------------------------------------------------------- #


@app.get("/", response_class=HTMLResponse)
async def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/login")
async def login_submit(password: str = Form(...)):
    if password != config.WEB_PASSWORD:
        return JSONResponse(
            {"ok": False, "error": "bad password"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    resp = JSONResponse({"ok": True})
    _set_session_cookie(resp)
    return resp


@app.post("/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE_NAME)
    return resp


@app.get("/api/auth-status")
async def api_auth_status(
    session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    return {"authenticated": _session_ok(session)}


# --------------------------------------------------------------------------- #
# Public read-only API (used by the monitor view)
# --------------------------------------------------------------------------- #


@app.get("/api/status")
async def api_status():
    return system_info.snapshot()


@app.get("/api/status/stream")
async def api_status_stream():
    async def gen():
        try:
            while True:
                snap = system_info.snapshot()
                yield f"data: {json.dumps(snap)}\n\n"
                await asyncio.sleep(config.STATUS_INTERVAL_SECONDS)
        except asyncio.CancelledError:  # pragma: no cover
            return

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/monitor")
async def api_monitor(history: int = 0):
    """Single monitor snapshot.

    When ``history`` is non-zero, the response also includes a ``history``
    array containing up to that many recent samples (oldest first) — used by
    the Kindle/Lite renderer so its charts have a real line on first paint.
    """
    snap = system_info.monitor_snapshot()
    if history > 0:
        snap = dict(snap)
        snap["history"] = list(_history)[-history:]
    return snap


@app.get("/api/monitor/stream")
async def api_monitor_stream():
    async def gen():
        try:
            while True:
                snap = system_info.monitor_snapshot()
                yield f"data: {json.dumps(snap, default=str)}\n\n"
                await asyncio.sleep(config.STATUS_INTERVAL_SECONDS)
        except asyncio.CancelledError:  # pragma: no cover
            return

    return StreamingResponse(gen(), media_type="text/event-stream")


# --------------------------------------------------------------------------- #
# Authenticated API
# --------------------------------------------------------------------------- #


@app.post("/api/command")
async def api_command(payload: dict, _: str = Depends(require_session)):
    command = (payload or {}).get("command", "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="missing 'command'")
    # Authenticated web sessions get the shell channel for free; the
    # `shell:` and `gpio:` rules still apply and respect ENABLE_SHELL.
    handler = CommandHandler(pre_authenticated=config.ENABLE_SHELL)
    result = await handler.handle(command)
    handler.reset_session()
    return {"command": command, "result": result}


@app.get("/api/command-buttons")
async def api_get_command_buttons(_: str = Depends(require_session)):
    return {"buttons": load_buttons()}


@app.put("/api/command-buttons")
async def api_put_command_buttons(payload: dict, _: str = Depends(require_session)):
    buttons = (payload or {}).get("buttons")
    if not isinstance(buttons, list):
        raise HTTPException(status_code=400, detail="missing 'buttons' array")
    try:
        saved = save_buttons(buttons)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"buttons": saved}


# --------------------------------------------------------------------------- #
# WebSocket: interactive PTY shell (requires auth)
# --------------------------------------------------------------------------- #


@app.websocket("/api/shell")
async def ws_shell(websocket: WebSocket):
    cookie = websocket.cookies.get(COOKIE_NAME)
    if not _session_ok(cookie):
        await websocket.close(code=4401)
        return
    if not config.WEB_ENABLE_PTY:
        await websocket.close(code=4403)
        return

    await websocket.accept()
    pty_proc = PtyProcess()
    pty_proc.start()
    log.info("PTY shell started pid=%s", pty_proc.pid)

    async def to_client(data: bytes) -> None:
        try:
            await websocket.send_bytes(data)
        except Exception:  # pragma: no cover - socket closed
            pass

    reader = asyncio.create_task(pump_pty_to_callback(pty_proc, to_client))

    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if "bytes" in msg and msg["bytes"] is not None:
                pty_proc.write(msg["bytes"])
            elif "text" in msg and msg["text"] is not None:
                # Control frames are JSON: {"type":"resize","cols":N,"rows":N}
                try:
                    obj = json.loads(msg["text"])
                except json.JSONDecodeError:
                    pty_proc.write(msg["text"].encode("utf-8"))
                    continue
                if obj.get("type") == "resize":
                    pty_proc.resize(int(obj.get("cols", 80)), int(obj.get("rows", 24)))
                elif obj.get("type") == "input":
                    pty_proc.write(obj.get("data", "").encode("utf-8"))
    except WebSocketDisconnect:
        pass
    finally:
        reader.cancel()
        pty_proc.close()
        log.info("PTY shell closed pid=%s", pty_proc.pid)


# ``/_render/lite`` is the PNG capture target; ``/lite`` and ``/cheap`` share
# ``kindle_html.render_dashboard_html`` — edit that file only.
_RENDER_LITE_PATH = "/_render/lite"


def _cheap_page(w: int, h: int, refresh: int) -> str:
    """Kindle / e-ink: one full-resolution PNG + meta refresh."""
    w = max(200, min(int(w), 2000))
    h = max(200, min(int(h), 3000))
    refresh = max(10, min(int(refresh), 3600))
    ts = int(time.time())
    img_src = f"/api/cheap.png?w={w}&h={h}&t={ts}"
    return f"""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width={w},height={h},user-scalable=no">
<meta http-equiv="refresh" content="{refresh}">
<title>Pi Remote</title>
<style>
html,body{{margin:0;padding:0;width:{w}px;height:{h}px;overflow:hidden;background:#fff;color:#000;font-family:serif;}}
img{{display:block;width:{w}px;height:{h}px;border:0;image-rendering:auto;}}
.fallback{{padding:24px;font-size:20px;line-height:1.5;}}
</style></head><body>
<img src="{img_src}" alt="pi dashboard" width="{w}" height="{h}"
     onerror="this.outerHTML='<div class=fallback>无法生成截图。<br>请确认服务器已安装 chromium-browser。</div>'">
</body></html>"""


@app.get(_RENDER_LITE_PATH, response_class=HTMLResponse, include_in_schema=False)
async def render_lite_internal(
    w: int = CHEAP_DEFAULT_WIDTH,
    h: int = CHEAP_DEFAULT_HEIGHT,
):
    """Scaled lite dashboard — Chromium screenshot source for /api/cheap.png."""
    snap = system_info.monitor_snapshot()
    return render_dashboard_html(
        snap, list(_history), width=w, height=h, fit_viewport=True
    )


@app.get("/lite", response_class=HTMLResponse)
async def lite_page(refresh: int = 60):
    """Lite dashboard — live HTML + SVG (sharp lines on desktop browsers)."""
    snap = system_info.monitor_snapshot()
    page = render_dashboard_html(snap, list(_history), fit_viewport=False)
    return wrap_with_refresh(page, refresh)


@app.get("/cheap", response_class=HTMLResponse)
async def cheap_page(
    w: int = CHEAP_DEFAULT_WIDTH,
    h: int = CHEAP_DEFAULT_HEIGHT,
    refresh: int = 60,
):
    """Cheap dashboard — PNG for Kindle (same layout as /lite, pre-rendered)."""
    return _cheap_page(w, h, refresh)


@app.get("/kindle")
async def kindle_redirect():
    return RedirectResponse("/lite", status_code=301)


async def _cheap_png_response(w: int, h: int) -> Response:
    w = max(200, min(int(w), 2000))
    h = max(200, min(int(h), 3000))
    url = f"http://127.0.0.1:{config.WEB_PORT}{_RENDER_LITE_PATH}?w={w}&h={h}"
    try:
        png = await render_screenshot(url, width=w, height=h)
    except RuntimeError as exc:
        log.warning("cheap screenshot failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc))
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/cheap.png")
async def cheap_png(
    w: int = CHEAP_DEFAULT_WIDTH,
    h: int = CHEAP_DEFAULT_HEIGHT,
):
    """PNG screenshot of ``/_render/lite`` (same template as ``/lite``)."""
    return await _cheap_png_response(w, h)


@app.get("/api/kindle.png")
async def kindle_png_alias(
    w: int = CHEAP_DEFAULT_WIDTH,
    h: int = CHEAP_DEFAULT_HEIGHT,
):
    """Backward-compatible alias for ``/api/cheap.png``."""
    return await _cheap_png_response(w, h)


@app.get("/api/kindle/status")
async def kindle_status():
    chromium = find_chromium()
    return {"chromium": chromium, "available": bool(chromium)}


@app.get("/healthz")
async def healthz():
    return {"ok": True}
