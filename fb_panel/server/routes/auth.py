"""Auth routes — POST /api/generate-key, POST /api/authorize, GET /api/check-session, POST /api/logout"""

import logging
from aiohttp import web

log = logging.getLogger("fb_panel.routes.auth")


async def handle_generate_key(request: web.Request) -> web.Response:
    km = request.app["key_manager"]
    key = km.generate_key()

    cb = request.app.get("terminal_callback")
    if cb:
        try:
            cb(key)
        except Exception:
            pass
    else:
        log.info(f"🔑 NEW KEY: {key}")

    return web.json_response({"success": True, "message": "Klucz wygenerowany!", "key": key})


async def handle_authorize(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        key = data.get("key", "")
    except Exception:
        return web.json_response({"success": False, "message": "Nieprawidłowe dane!"}, status=400)

    km = request.app["key_manager"]
    ok, msg, sid = km.validate_key(key)

    if ok:
        resp = web.json_response({"success": True, "message": msg, "session_id": sid})
        resp.set_cookie("session_id", sid, httponly=True, max_age=86400, samesite="Strict")
        return resp
    return web.json_response({"success": False, "message": msg})


async def handle_check_session(request: web.Request) -> web.Response:
    sid = request.headers.get("X-Session-ID") or request.cookies.get("session_id", "")
    km = request.app["key_manager"]
    if km.is_session_valid(sid):
        return web.json_response({"authorized": True, "valid": True, "session_id": sid})
    return web.json_response({"authorized": False, "valid": False})


async def handle_logout(request: web.Request) -> web.Response:
    sid = request.headers.get("X-Session-ID") or request.cookies.get("session_id", "")
    request.app["key_manager"].logout(sid)
    resp = web.json_response({"success": True})
    resp.del_cookie("session_id")
    return resp


def auth_routes() -> list:
    return [
        web.post("/api/generate-key", handle_generate_key),
        web.post("/api/authorize", handle_authorize),
        web.get("/api/check-session", handle_check_session),
        web.post("/api/logout", handle_logout),
    ]
