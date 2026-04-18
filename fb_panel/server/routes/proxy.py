"""Proxy routes — CRUD + validate"""

import asyncio
from aiohttp import web


async def handle_load(request: web.Request) -> web.Response:
    """POST /api/proxy/load — {lines: string[], proxy_type: SOCKS5|SOCKS4|HTTP}
    Also accepts {proxies: "line\\nline\\n..."} (string split by newlines)."""
    try:
        data = await request.json()
        lines = data.get("lines", [])
        proxy_type = data.get("proxy_type", "SOCKS5")
        if proxy_type not in ("SOCKS5", "SOCKS4", "HTTP"):
            proxy_type = "SOCKS5"
        # Support string 'proxies' field split by newlines
        raw = data.get("proxies", "")
        if isinstance(raw, str) and raw:
            lines = [l.strip() for l in raw.splitlines() if l.strip()]
    except Exception:
        return web.json_response({"success": False, "error": "Invalid data"}, status=400)

    pm = request.app["proxy_manager"]
    loaded = pm.load_from_lines(lines, proxy_type)

    # Start async geolocation lookup in background
    em = request.app.get("engine_manager")
    broadcast_fn = em.broadcast if em else None
    asyncio.create_task(pm.lookup_geo_all(broadcast_fn))

    proxies = [p.to_dict() for p in pm.proxies]
    return web.json_response({
        "success": True,
        "loaded": loaded,
        "total": len(proxies),
        "proxy_type": proxy_type,
        "proxies": proxies,
    })


async def handle_validate(request: web.Request) -> web.Response:
    """POST /api/proxy/validate — launch async validation"""
    pm = request.app["proxy_manager"]
    if not pm.proxies:
        return web.json_response({"success": False, "error": "No proxies loaded"}, status=400)

    em = request.app["engine_manager"]
    asyncio.create_task(pm.validate_all(broadcast_fn=em.broadcast))
    return web.json_response({"success": True, "message": "Validation started"})


async def handle_stats(request: web.Request) -> web.Response:
    """GET /api/proxy/stats"""
    stats = request.app["proxy_manager"].get_stats()
    return web.json_response({"success": True, **stats})


async def handle_clear(request: web.Request) -> web.Response:
    """POST /api/proxy/clear"""
    request.app["proxy_manager"].clear()
    return web.json_response({"success": True})


async def handle_list(request: web.Request) -> web.Response:
    """GET /api/proxy/list — return loaded proxies with status info"""
    pm = request.app["proxy_manager"]
    proxies = [p.to_dict() for p in pm.proxies]
    stats = pm.get_stats()
    return web.json_response({"success": True, "proxies": proxies, "total": len(proxies), **stats})


async def handle_check_proxy(request: web.Request) -> web.Response:
    """POST /api/proxy/check — DolphinAnty-style proxy check.
    Body: {proxy: "socks5://user:pass@host:port"} or {proxy: "host:port"}
    Returns: {ok, ip, country, city, country_code, latency_ms, error}"""
    try:
        data = await request.json()
        proxy_str = data.get("proxy", "")
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid data"}, status=400)

    if not proxy_str:
        return web.json_response({"ok": False, "error": "Brak proxy"}, status=400)

    from server.managers.browser_session import check_proxy_connectivity
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, check_proxy_connectivity, proxy_str)
    return web.json_response(result)


def proxy_routes() -> list:
    return [
        web.post("/api/proxy/load", handle_load),
        web.post("/api/proxy/validate", handle_validate),
        web.post("/api/proxy/clear", handle_clear),
        web.post("/api/proxy/check", handle_check_proxy),
        web.get("/api/proxy/stats", handle_stats),
        web.get("/api/proxy/list", handle_list),
    ]
