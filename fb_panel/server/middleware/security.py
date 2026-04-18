"""Security middleware — headers, sanitization, CORS-preflight, auth check"""

import re
from aiohttp import web


BLOCKED_PATTERNS = [
    re.compile(r"<script", re.I),
    re.compile(r"javascript:", re.I),
    re.compile(r"on\w+=", re.I),
    re.compile(r"\.\./"),
    re.compile(r"(union\s+(all\s+)?select|drop\s+table|;\s*delete\s|;\s*insert\s|;\s*update\s)", re.I),
]

# Routes that don't need auth
PUBLIC_PATHS = {
    "/api/generate-key",
    "/api/authorize",
    "/api/check-session",
    "/ws",
}

PUBLIC_PREFIXES = (
    "/api/vnc/register/",
    "/vnc/register/",
)


def _is_malicious(text: str) -> bool:
    return any(p.search(text) for p in BLOCKED_PATTERNS)


@web.middleware
async def security_middleware(request: web.Request, handler):
    path = request.path
    is_public_prefix = any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)

    # --- Block suspicious payloads ---
    raw_qs = request.query_string
    if raw_qs and _is_malicious(raw_qs):
        return web.json_response(
            {"error": "Blocked — suspicious input"}, status=403
        )

    if request.content_type == "application/json":
        try:
            body = await request.text()
            if body and _is_malicious(body):
                return web.json_response(
                    {"error": "Blocked — suspicious payload"}, status=403
                )
        except Exception:
            pass

    # --- Auth check for API routes ---
    if path.startswith("/api/") and path not in PUBLIC_PATHS and not is_public_prefix:
        session_id = request.headers.get("X-Session-ID", "") or request.headers.get("X-Session-Id", "")
        km = request.app.get("key_manager")
        if km and not km.is_session_valid(session_id):
            return web.json_response(
                {"success": False, "error": "Unauthorized"}, status=401
            )

    # --- Call handler ---
    response = await handler(request)

    # --- Security headers ---
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )
    return response
