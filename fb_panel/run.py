#!/usr/bin/env python3
"""FB Panel — Server entry point"""

import sys
import socket
import logging
from pathlib import Path

# Ensure project root on sys.path so 'server' package is importable
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiohttp import web
from server.app import create_app
from server.config import DEFAULT_HOST, DEFAULT_PORT, PORT_RANGE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-28s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fb_panel")


def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _find_free_port(start: int = DEFAULT_PORT) -> int:
    for port in range(start, start + PORT_RANGE):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("0.0.0.0", port))
            s.close()
            return port
        except OSError:
            continue
    return start


def main():
    port = _find_free_port()
    ip = _get_local_ip()

    print(f"""
╔══════════════════════════════════════════════╗
║       FB PANEL — KWASNY CHECKER PRO v2.0     ║
║              ULTRA STEALTH ENGINE            ║
╠══════════════════════════════════════════════╣
║  Local:   http://localhost:{port:<5}             ║
║  Network: http://{ip}:{port:<5}            ║
╠══════════════════════════════════════════════╣
║  API:     /api/*                             ║
║  WS:      /ws                                ║
╚══════════════════════════════════════════════╝
""")

    app = create_app()
    web.run_app(app, host=DEFAULT_HOST, port=port, print=None)


if __name__ == "__main__":
    main()
