"""WebSocket route — real-time bidirectional communication"""

import logging
from aiohttp import web, WSMsgType

log = logging.getLogger("fb_panel.ws")


async def handle_websocket(request: web.Request) -> web.WebSocketResponse:
    """GET /ws — upgrade to WebSocket"""
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    em = request.app["engine_manager"]
    em.add_ws(ws)
    log.info("WS client connected")

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                # Future: handle client→server commands
                pass
            elif msg.type == WSMsgType.ERROR:
                log.error(f"WS error: {ws.exception()}")
    finally:
        em.remove_ws(ws)
        log.info("WS client disconnected")

    return ws


def websocket_routes() -> list:
    return [
        web.get("/ws", handle_websocket),
    ]
