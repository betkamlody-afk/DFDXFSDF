"""Session routes — 3-tab session management with live Selenium browsers."""

from aiohttp import web


async def handle_launch_session(request: web.Request) -> web.Response:
    """POST /api/sessions/launch — launch browser for a success log."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "Invalid JSON body"}, status=400)
    log_id = data.get("log_id", "")
    if not log_id:
        return web.json_response({"success": False, "error": "log_id required"}, status=400)

    lm = request.app["logs_manager"]
    entry = lm.logs.get(log_id)
    if not entry:
        return web.json_response({"success": False, "error": "Log not found"}, status=404)

    sm = request.app["session_manager"]
    mode = str(data.get("mode", "selenium") or "selenium").lower()
    if mode not in ("selenium", "vnc"):
        return web.json_response({"success": False, "error": "Invalid launch mode"}, status=400)
    # Check if a session already exists for this log
    for s in sm.sessions.values():
        if s.log_id == log_id and s.mode == mode and s.status in ("active", "awaiting_vnc"):
            return web.json_response({"success": True, "session": s.to_dict()})

    result = await sm.launch_session(
        entry=entry,
        code=entry.code or "",
        worker_os=data.get("worker_os", ""),
        mode=mode,
        base_url=str(request.url.origin()),
    )

    # Broadcast session_created via WebSocket
    if result.get("success") and result.get("session"):
        em = request.app["engine_manager"]
        await em.broadcast("session_created", result["session"])

    return web.json_response(result)


async def handle_get_vnc_status(request: web.Request) -> web.Response:
        """GET /api/sessions/{sid}/vnc-status — poll external VNC registration state."""
        sid = request.match_info["sid"]
        sm = request.app["session_manager"]
        result = sm.get_vnc_status(sid)
        if not result:
                return web.json_response({"success": False, "error": "VNC session not found"}, status=404)
        return web.json_response({"success": True, **result})


async def handle_register_vnc(request: web.Request) -> web.Response:
        """POST /api/vnc/register/{token} — mark VNC launcher as connected."""
        token = request.match_info["token"]
        vm = request.app["vnc_manager"]
        sid = vm.get_session_id(token)
        if not sid:
                return web.json_response({"success": False, "error": "Invalid token"}, status=404)

        try:
                data = await request.json() if request.content_length else {}
        except Exception:
                data = {}

        sm = request.app["session_manager"]
        session = sm.mark_vnc_connected(sid, launcher=data.get("launcher", "external-vnc"))
        if not session:
                return web.json_response({"success": False, "error": "Session not found"}, status=404)

        em = request.app["engine_manager"]
        await em.broadcast("session_updated", session)
        await em.broadcast("vnc_registered", {"session_id": sid, "status": "connected"})
        return web.json_response({"success": True, "session": session})


async def handle_vnc_register_page(request: web.Request) -> web.Response:
        """GET /vnc/register/{token} — simple handshake page for external VNC launcher."""
        token = request.match_info["token"]
        vm = request.app["vnc_manager"]
        sid = vm.get_session_id(token)
        if not sid:
                return web.Response(text="Invalid VNC token", status=404)

        html = f"""<!DOCTYPE html>
<html lang=\"pl\">
<head>
    <meta charset=\"utf-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
    <title>FB Panel VNC</title>
    <style>
        body {{ margin:0; font-family: system-ui, sans-serif; background:#0b1220; color:#e5eef9; display:grid; place-items:center; min-height:100vh; }}
        .card {{ width:min(560px, 92vw); background:#111a2a; border:1px solid rgba(255,255,255,.08); border-radius:20px; padding:28px; box-shadow:0 20px 60px rgba(0,0,0,.35); }}
        h1 {{ margin:0 0 10px; font-size:28px; }}
        p {{ opacity:.8; line-height:1.6; }}
        .pill {{ display:inline-block; background:#1d4ed8; padding:6px 10px; border-radius:999px; font-size:12px; margin-bottom:14px; }}
        button {{ margin-top:18px; padding:14px 18px; border:0; border-radius:12px; background:#22c55e; color:#06230f; font-weight:700; cursor:pointer; }}
        .muted {{ margin-top:14px; font-size:13px; opacity:.65; word-break:break-all; }}
        .ok {{ color:#4ade80; margin-top:14px; }}
        .err {{ color:#f87171; margin-top:14px; }}
    </style>
</head>
<body>
    <div class=\"card\">
        <div class=\"pill\">FB Panel VNC Handshake</div>
        <h1>Sesja {sid}</h1>
        <p>To okno służy do potwierdzenia startu zewnętrznego klienta VNC. Kliknij przycisk poniżej po uruchomieniu swojego środowiska.</p>
        <button id=\"register\">Zarejestruj start VNC</button>
        <div id=\"msg\" class=\"muted\">Token: {token}</div>
    </div>
    <script>
        const msg = document.getElementById('msg');
        document.getElementById('register').addEventListener('click', async () => {{
            msg.className = 'muted';
            msg.textContent = 'Rejestrowanie połączenia...';
            try {{
                const r = await fetch('/api/vnc/register/{token}', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ launcher: 'browser-link' }})
                }});
                const data = await r.json();
                if (data.success) {{
                    msg.className = 'ok';
                    msg.textContent = 'VNC zarejestrowane. Możesz wrócić do panelu.';
                }} else {{
                    msg.className = 'err';
                    msg.textContent = data.error || 'Nie udało się zarejestrować VNC';
                }}
            }} catch (e) {{
                msg.className = 'err';
                msg.textContent = e.message || 'Błąd rejestracji';
            }}
        }});
    </script>
</body>
</html>"""
        return web.Response(text=html, content_type="text/html")


async def handle_screenshot(request: web.Request) -> web.Response:
    """GET /api/sessions/{sid}/screenshot/{tab} — browser screenshot."""
    sid = request.match_info["sid"]
    tab = request.match_info["tab"]
    if tab not in ("email", "facebook", "panel"):
        return web.Response(status=400, text="Invalid tab")

    sm = request.app["session_manager"]
    # Check if session is crashed/closed — return 410 Gone so frontend stops polling
    s = sm.get_session(sid)
    if s and s.status in ("crashed", "closed"):
        return web.json_response({"error": "Session crashed", "crashed": True}, status=410)
    png = await sm.get_screenshot(sid, tab)
    if not png:
        return web.Response(status=404)
    return web.Response(body=png, content_type="image/png",
                        headers={"Cache-Control": "no-cache, no-store"})


async def handle_login_email(request: web.Request) -> web.Response:
    """POST /api/sessions/{sid}/login-email — login to email via Selenium."""
    sid = request.match_info["sid"]
    sm = request.app["session_manager"]
    result = await sm.action_login_email(sid)
    return web.json_response(result)


async def handle_extract_code(request: web.Request) -> web.Response:
    """POST /api/sessions/{sid}/extract-code — extract FB code from inbox."""
    sid = request.match_info["sid"]
    sm = request.app["session_manager"]
    result = await sm.action_extract_code(sid)
    return web.json_response(result)


async def handle_enter_code(request: web.Request) -> web.Response:
    """POST /api/sessions/{sid}/enter-code — enter code on Facebook."""
    sid = request.match_info["sid"]
    sm = request.app["session_manager"]
    data = await request.json() if request.content_length else {}
    code = data.get("code", "")
    result = await sm.action_enter_code(sid, code)
    return web.json_response(result)


async def handle_open_profile(request: web.Request) -> web.Response:
    """POST /api/sessions/{sid}/open-profile — open FB profile in panel tab."""
    sid = request.match_info["sid"]
    sm = request.app["session_manager"]
    result = await sm.action_open_profile(sid)
    return web.json_response(result)


async def handle_refresh_tab(request: web.Request) -> web.Response:
    """POST /api/sessions/{sid}/refresh-tab — refresh a browser tab."""
    sid = request.match_info["sid"]
    sm = request.app["session_manager"]
    data = await request.json() if request.content_length else {}
    tab = data.get("tab", "email")
    result = await sm.action_refresh_tab(sid, tab)
    return web.json_response(result)


async def handle_list_sessions(request: web.Request) -> web.Response:
    """GET /api/sessions — list all active sessions."""
    sm = request.app["session_manager"]
    return web.json_response({"success": True, "sessions": sm.get_all()})


async def handle_get_session(request: web.Request) -> web.Response:
    """GET /api/sessions/{sid} — get one session."""
    sid = request.match_info["sid"]
    sm = request.app["session_manager"]
    s = sm.get_session(sid)
    if not s:
        return web.json_response({"success": False, "error": "Session not found"}, status=404)
    return web.json_response({"success": True, "session": s.to_dict()})


async def handle_close_session(request: web.Request) -> web.Response:
    """POST /api/sessions/{sid}/close"""
    sid = request.match_info["sid"]
    sm = request.app["session_manager"]
    if await sm.close_session(sid):
        # Broadcast session close via WebSocket
        em = request.app["engine_manager"]
        await em.broadcast("session_updated", {"id": sid, "status": "closed"})
        return web.json_response({"success": True})
    return web.json_response({"success": False, "error": "Session not found"}, status=404)


async def handle_change_proxy(request: web.Request) -> web.Response:
    """POST /api/sessions/{sid}/change-proxy — get next proxy and restart browser."""
    sid = request.match_info["sid"]
    sm = request.app["session_manager"]
    pm = request.app["proxy_manager"]
    proxy = pm.get_next()
    if not proxy:
        return web.json_response({"success": False, "error": "No proxy available"})
    result = await sm.change_proxy(sid, proxy.url)
    if not result.get("success"):
        status = 410 if result.get("crashed") else 404
        return web.json_response(result, status=status)

    # Broadcast session update if browser was restarted
    if result.get("restarted"):
        em = request.app["engine_manager"]
        await em.broadcast("session_updated", result.get("session", {}))

    return web.json_response(result)


async def handle_toggle_auto_logout(request: web.Request) -> web.Response:
    """POST /api/sessions/{sid}/auto-logout"""
    sid = request.match_info["sid"]
    data = await request.json()
    enabled = data.get("enabled", True)
    sm = request.app["session_manager"]
    result = sm.toggle_auto_logout(sid, bool(enabled))
    if not result:
        return web.json_response({"success": False, "error": "Session not found"}, status=404)
    return web.json_response({"success": True, "session": result})


async def handle_toggle_auto_disconnect(request: web.Request) -> web.Response:
    """POST /api/sessions/{sid}/auto-disconnect"""
    sid = request.match_info["sid"]
    data = await request.json()
    enabled = data.get("enabled", True)
    sm = request.app["session_manager"]
    result = sm.toggle_auto_disconnect(sid, bool(enabled))
    if not result:
        return web.json_response({"success": False, "error": "Session not found"}, status=404)
    return web.json_response({"success": True, "session": result})


async def handle_toggle_auto_delete_posts(request: web.Request) -> web.Response:
    """POST /api/sessions/{sid}/auto-delete-posts"""
    sid = request.match_info["sid"]
    data = await request.json()
    enabled = data.get("enabled", True)
    sm = request.app["session_manager"]
    result = sm.toggle_auto_delete_posts(sid, bool(enabled))
    if not result:
        return web.json_response({"success": False, "error": "Session not found"}, status=404)
    return web.json_response({"success": True, "session": result})


async def handle_toggle_auto_delete_stories(request: web.Request) -> web.Response:
    """POST /api/sessions/{sid}/auto-delete-stories"""
    sid = request.match_info["sid"]
    data = await request.json()
    enabled = data.get("enabled", True)
    sm = request.app["session_manager"]
    result = sm.toggle_auto_delete_stories(sid, bool(enabled))
    if not result:
        return web.json_response({"success": False, "error": "Session not found"}, status=404)
    return web.json_response({"success": True, "session": result})


async def handle_delete_posts(request: web.Request) -> web.Response:
    """POST /api/sessions/{sid}/delete-posts — manually trigger post deletion."""
    sid = request.match_info["sid"]
    sm = request.app["session_manager"]
    result = sm.perform_delete_posts(sid)
    if not result:
        return web.json_response({"success": False, "error": "Session not found"}, status=404)
    return web.json_response({"success": True, **result})


async def handle_delete_stories(request: web.Request) -> web.Response:
    """POST /api/sessions/{sid}/delete-stories — manually trigger story deletion."""
    sid = request.match_info["sid"]
    sm = request.app["session_manager"]
    result = sm.perform_delete_stories(sid)
    if not result:
        return web.json_response({"success": False, "error": "Session not found"}, status=404)
    return web.json_response({"success": True, **result})


async def handle_disconnect_connections(request: web.Request) -> web.Response:
    """POST /api/sessions/{sid}/disconnect — manually trigger connection disconnect."""
    sid = request.match_info["sid"]
    sm = request.app["session_manager"]
    result = sm.perform_disconnect_connections(sid)
    if not result:
        return web.json_response({"success": False, "error": "Session not found"}, status=404)
    return web.json_response({"success": True, **result})


def session_routes() -> list:
    return [
        # Launch + screenshot
        web.post("/api/sessions/launch", handle_launch_session),
        web.get("/api/sessions/{sid}/vnc-status", handle_get_vnc_status),
        web.post("/api/vnc/register/{token}", handle_register_vnc),
        web.get("/vnc/register/{token}", handle_vnc_register_page),
        web.get("/api/sessions/{sid}/screenshot/{tab}", handle_screenshot),
        # Browser actions
        web.post("/api/sessions/{sid}/login-email", handle_login_email),
        web.post("/api/sessions/{sid}/extract-code", handle_extract_code),
        web.post("/api/sessions/{sid}/enter-code", handle_enter_code),
        web.post("/api/sessions/{sid}/open-profile", handle_open_profile),
        web.post("/api/sessions/{sid}/refresh-tab", handle_refresh_tab),
        # CRUD
        web.get("/api/sessions", handle_list_sessions),
        web.get("/api/sessions/{sid}", handle_get_session),
        web.post("/api/sessions/{sid}/close", handle_close_session),
        web.post("/api/sessions/{sid}/change-proxy", handle_change_proxy),
        # Toggles
        web.post("/api/sessions/{sid}/auto-logout", handle_toggle_auto_logout),
        web.post("/api/sessions/{sid}/auto-disconnect", handle_toggle_auto_disconnect),
        web.post("/api/sessions/{sid}/auto-delete-posts", handle_toggle_auto_delete_posts),
        web.post("/api/sessions/{sid}/auto-delete-stories", handle_toggle_auto_delete_stories),
        # Manual actions
        web.post("/api/sessions/{sid}/delete-posts", handle_delete_posts),
        web.post("/api/sessions/{sid}/delete-stories", handle_delete_stories),
        web.post("/api/sessions/{sid}/disconnect", handle_disconnect_connections),
    ]
