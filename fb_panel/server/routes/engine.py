"""Engine routes — start, stop, status"""

from aiohttp import web


async def handle_start(request: web.Request) -> web.Response:
    """POST /api/engine/start — {concurrency: int}"""
    try:
        data = await request.json()
        concurrency = int(data.get("concurrency", 3))
    except Exception:
        concurrency = 3
    result = await request.app["engine_manager"].start(concurrency)
    return web.json_response(result)


async def handle_stop(request: web.Request) -> web.Response:
    """POST /api/engine/stop"""
    result = await request.app["engine_manager"].stop()
    return web.json_response(result)


async def handle_status(request: web.Request) -> web.Response:
    """GET /api/engine/status"""
    status = request.app["engine_manager"].get_status()
    return web.json_response({"success": True, **status})


def engine_routes() -> list:
    return [
        web.post("/api/engine/start", handle_start),
        web.post("/api/engine/stop", handle_stop),
        web.get("/api/engine/status", handle_status),
    ]
