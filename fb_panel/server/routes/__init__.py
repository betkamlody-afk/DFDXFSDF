from .auth import auth_routes
from .proxy import proxy_routes
from .logs import logs_routes
from .engine import engine_routes
from .workers import workers_routes
from .system import system_routes
from .websocket import websocket_routes
from .session import session_routes

__all__ = [
    "auth_routes",
    "proxy_routes",
    "logs_routes",
    "engine_routes",
    "workers_routes",
    "system_routes",
    "websocket_routes",
    "session_routes",
]
