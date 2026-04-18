"""Server utility helpers"""


def get_client_ip(request) -> str:
    """Extract real client IP from request."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    peer = request.transport.get_extra_info("peername")
    return peer[0] if peer else "0.0.0.0"
