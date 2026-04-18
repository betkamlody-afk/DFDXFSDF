"""Application factory — assembles middleware, managers, routes, CORS, static."""

import logging
import aiohttp_cors
from aiohttp import web
from pathlib import Path

from server.config import STATIC_DIR
from server.middleware import security_middleware
from server.managers import KeyManager, ProxyManager, LogsManager, EngineManager, SessionManager, VncManager
from server.routes import (
    auth_routes,
    proxy_routes,
    logs_routes,
    engine_routes,
    workers_routes,
    system_routes,
    websocket_routes,
    session_routes,
)

log = logging.getLogger("fb_panel.app")


# ═══════════════════════════════════════════════════════════════
# STATIC FILE HANDLERS
# ═══════════════════════════════════════════════════════════════

async def _handle_index(request: web.Request) -> web.Response:
    index = STATIC_DIR / "index.html"
    if index.exists():
        return web.FileResponse(index)
    return web.Response(text="Index not found", status=404)


async def _handle_static(request: web.Request) -> web.Response:
    """Serve static files from nested paths: /css/x.css, /js/api/y.js etc."""
    rel = request.match_info.get("path", "")
    file = STATIC_DIR / rel
    if file.exists() and file.is_file() and STATIC_DIR in file.resolve().parents:
        return web.FileResponse(file)
    return web.Response(text="Not found", status=404)


# ═══════════════════════════════════════════════════════════════
# FACTORY
# ═══════════════════════════════════════════════════════════════

def create_app() -> web.Application:
    app = web.Application(middlewares=[security_middleware])

    # ── Managers (dependency injection via app dict) ──
    km = KeyManager()
    pm = ProxyManager()
    lm = LogsManager()
    vm = VncManager()
    sm = SessionManager(vnc_manager=vm)
    em = EngineManager(pm, lm, sm)

    app["key_manager"] = km
    app["proxy_manager"] = pm
    app["logs_manager"] = lm
    app["vnc_manager"] = vm
    app["engine_manager"] = em
    app["session_manager"] = sm

    # ── CORS ──
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        )
    })

    # ── Collect all routes ──
    api_routes = [
        *auth_routes(),
        *proxy_routes(),
        *logs_routes(),
        *engine_routes(),
        *workers_routes(),
        *system_routes(),
        *websocket_routes(),
        *session_routes(),
    ]

    static_routes = [
        web.get("/", _handle_index),
        web.get("/{path:.*}", _handle_static),
    ]

    # Register API routes with CORS
    for route in api_routes:
        cors.add(app.router.add_route(route.method, route.path, route.handler))

    # Static must be last (catch-all)
    for route in static_routes:
        cors.add(app.router.add_route(route.method, route.path, route.handler))

    log.info(f"Registered {len(api_routes)} API routes + static handler")
    return app
