"""Logs routes — load, stats, list, clear"""

from aiohttp import web


async def handle_load(request: web.Request) -> web.Response:
    """POST /api/logs/load — {lines: string[]}"""
    try:
        data = await request.json()
        lines = data.get("lines", data.get("logs", []))
    except Exception:
        return web.json_response({"success": False, "error": "Invalid data"}, status=400)

    lm = request.app["logs_manager"]
    loaded = lm.load_logs(lines)
    return web.json_response({"success": True, "loaded": loaded})


async def handle_stats(request: web.Request) -> web.Response:
    """GET /api/logs/stats"""
    stats = request.app["logs_manager"].get_stats()
    return web.json_response({"success": True, **stats})


async def handle_all(request: web.Request) -> web.Response:
    """GET /api/logs/all"""
    logs = request.app["logs_manager"].get_all()
    return web.json_response({"success": True, "logs": logs})


async def handle_clear(request: web.Request) -> web.Response:
    """POST /api/logs/clear"""
    request.app["logs_manager"].clear()
    return web.json_response({"success": True})


async def handle_single(request: web.Request) -> web.Response:
    """GET /api/logs/{id}"""
    log_id = request.match_info["id"]
    lm = request.app["logs_manager"]
    entry = lm.logs.get(log_id)
    if not entry:
        return web.json_response({"success": False, "error": "Not found"}, status=404)
    return web.json_response({"success": True, "log": entry.to_dict()})


async def handle_delete_single(request: web.Request) -> web.Response:
    """DELETE /api/logs/{id}"""
    log_id = request.match_info["id"]
    lm = request.app["logs_manager"]
    if log_id not in lm.logs:
        return web.json_response({"success": False, "error": "Not found"}, status=404)
    del lm.logs[log_id]
    lm._save()
    return web.json_response({"success": True})


async def handle_retry(request: web.Request) -> web.Response:
    """POST /api/logs/{id}/retry — reset log to PENDING for re-processing"""
    from server.models import LogStatus
    log_id = request.match_info["id"]
    lm = request.app["logs_manager"]
    entry = lm.logs.get(log_id)
    if not entry:
        return web.json_response({"success": False, "error": "Not found"}, status=404)
    # Only allow retry on finished statuses
    finished = {LogStatus.SUCCESS, LogStatus.INVALID, LogStatus.CHECKPOINT, LogStatus.ERROR, LogStatus.TWO_FA}
    if entry.status not in finished:
        return web.json_response({"success": False, "error": "Log is still processing"}, status=400)
    entry.status = LogStatus.PENDING
    entry.error = None
    entry.code = None
    from datetime import datetime
    entry.updated_at = datetime.now().isoformat()
    lm._save()
    # Broadcast update via WS
    em = request.app.get("engine_manager")
    if em:
        import asyncio
        asyncio.create_task(em.broadcast("log_updated", entry.to_dict()))
    return web.json_response({"success": True, "log": entry.to_dict()})


def logs_routes() -> list:
    return [
        web.post("/api/logs/load", handle_load),
        web.post("/api/logs/clear", handle_clear),
        web.get("/api/logs/stats", handle_stats),
        web.get("/api/logs/all", handle_all),
        web.get("/api/logs/{id}", handle_single),
        web.delete("/api/logs/{id}", handle_delete_single),
        web.post("/api/logs/{id}/retry", handle_retry),
    ]
