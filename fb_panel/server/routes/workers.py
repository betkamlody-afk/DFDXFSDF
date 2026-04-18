"""Workers + anti-connect routes"""

from aiohttp import web


async def handle_workers(request: web.Request) -> web.Response:
    """GET /api/workers"""
    em = request.app["engine_manager"]
    return web.json_response({"success": True, "workers": em.get_workers()})


async def handle_anti_connect_toggle(request: web.Request) -> web.Response:
    """POST /api/anti-connect/toggle — {enabled: bool}"""
    try:
        data = await request.json()
        enabled = data.get("enabled", True)
    except Exception:
        enabled = True
    em = request.app["engine_manager"]
    em.anti_connect = bool(enabled)
    return web.json_response({"success": True, "enabled": em.anti_connect})


async def handle_anti_connect_status(request: web.Request) -> web.Response:
    """GET /api/anti-connect/status"""
    em = request.app["engine_manager"]
    return web.json_response({"success": True, "enabled": em.anti_connect})


def workers_routes() -> list:
    return [
        web.get("/api/workers", handle_workers),
        web.post("/api/anti-connect/toggle", handle_anti_connect_toggle),
        web.get("/api/anti-connect/status", handle_anti_connect_status),
    ]
