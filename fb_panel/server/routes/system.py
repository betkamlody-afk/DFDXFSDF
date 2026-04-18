"""System info route"""

from aiohttp import web
from server.config import ENGINE_AVAILABLE


async def handle_system_info(request: web.Request) -> web.Response:
    """GET /api/system/info"""
    return web.json_response({
        "success": True,
        "version": "2.0.0",
        "codename": "ULTRA STEALTH",
        "engine_available": ENGINE_AVAILABLE,
        "features": {
            "selenium": ENGINE_AVAILABLE,
            "stealth_mode": True,
            "proxy_rotation": True,
            "anti_connect": True,
            "rate_limiting": True,
            "security_headers": True,
            "websocket": True,
        },
        "supported_providers": ["wp.pl", "o2.pl", "interia.pl", "onet.pl", "gmail.com"],
    })


def system_routes() -> list:
    return [
        web.get("/api/system/info", handle_system_info),
    ]
