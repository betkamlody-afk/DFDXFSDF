"""VNC runtime manager.

Creates a real VNC stack per session:
- Xvfb display for the browser
- x11vnc attached to that display
- noVNC/websockify endpoint with direct browser link

The Selenium browser can be launched on the same DISPLAY, so all existing
automation remains available while the user can also attach through VNC.
"""

import os
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional
from urllib.parse import urlparse


NOVNC_WEB_ROOT = "/usr/share/novnc"


@dataclass
class VncRuntime:
    session_id: str
    display_num: int
    display: str
    vnc_port: int
    novnc_port: int
    vnc_url: str
    status: str
    created_at: str
    connected_at: str = ""
    xvfb_proc: Optional[subprocess.Popen] = None
    x11vnc_proc: Optional[subprocess.Popen] = None
    websockify_proc: Optional[subprocess.Popen] = None

    @property
    def browser_env(self) -> dict:
        return {"DISPLAY": self.display}

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "display": self.display,
            "vnc_port": self.vnc_port,
            "novnc_port": self.novnc_port,
            "vnc_url": self.vnc_url,
            "status": self.status,
            "created_at": self.created_at,
            "connected_at": self.connected_at,
        }


class VncManager:
    def __init__(self):
        self._runtimes: Dict[str, VncRuntime] = {}

    def start_session(self, session_id: str, base_url: str, width: int = 1440, height: int = 920) -> dict:
        runtime = self._runtimes.get(session_id)
        if runtime and self._is_runtime_alive(runtime):
            return runtime.to_dict()

        display_num = self._find_free_display()
        display = f":{display_num}"
        vnc_port = self._find_free_port()
        novnc_port = self._find_free_port()
        vnc_url = self._build_vnc_url(base_url, novnc_port)
        created_at = datetime.now().isoformat()

        xvfb_proc = subprocess.Popen(
            ["Xvfb", display, "-screen", "0", f"{width}x{height}x24", "-ac"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )
        self._wait_for_display(display_num, xvfb_proc)

        x11vnc_proc = subprocess.Popen(
            [
                "x11vnc",
                "-display", display,
                "-rfbport", str(vnc_port),
                "-forever",
                "-shared",
                "-nopw",
                "-localhost",
                "-xkb",
                "-quiet",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )
        self._wait_for_port(vnc_port, x11vnc_proc)

        websockify_proc = subprocess.Popen(
            [
                "websockify",
                "--web", NOVNC_WEB_ROOT,
                str(novnc_port),
                f"localhost:{vnc_port}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )
        self._wait_for_port(novnc_port, websockify_proc)

        runtime = VncRuntime(
            session_id=session_id,
            display_num=display_num,
            display=display,
            vnc_port=vnc_port,
            novnc_port=novnc_port,
            vnc_url=vnc_url,
            status="running",
            created_at=created_at,
            connected_at=created_at,
            xvfb_proc=xvfb_proc,
            x11vnc_proc=x11vnc_proc,
            websockify_proc=websockify_proc,
        )
        self._runtimes[session_id] = runtime
        return runtime.to_dict()

    def get_by_session(self, session_id: str) -> Optional[dict]:
        runtime = self._runtimes.get(session_id)
        if not runtime:
            return None
        runtime.status = "running" if self._is_runtime_alive(runtime) else "stopped"
        return runtime.to_dict()

    def get_launch_env(self, session_id: str) -> Optional[dict]:
        runtime = self._runtimes.get(session_id)
        if not runtime or not self._is_runtime_alive(runtime):
            return None
        return runtime.browser_env

    def stop_session(self, session_id: str):
        runtime = self._runtimes.pop(session_id, None)
        if not runtime:
            return
        for proc in (runtime.websockify_proc, runtime.x11vnc_proc, runtime.xvfb_proc):
            if not proc:
                continue
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def _is_runtime_alive(self, runtime: VncRuntime) -> bool:
        return all(
            proc and proc.poll() is None
            for proc in (runtime.xvfb_proc, runtime.x11vnc_proc, runtime.websockify_proc)
        )

    @staticmethod
    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    @staticmethod
    def _find_free_display(start: int = 101, end: int = 199) -> int:
        for display_num in range(start, end + 1):
            if os.path.exists(f"/tmp/.X11-unix/X{display_num}"):
                continue
            if os.path.exists(f"/tmp/.X{display_num}-lock"):
                continue
            return display_num
        raise RuntimeError("Brak wolnego DISPLAY dla Xvfb")

    @staticmethod
    def _wait_for_display(display_num: int, proc: subprocess.Popen, timeout: float = 8.0):
        sock_path = f"/tmp/.X11-unix/X{display_num}"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("Xvfb zakończył się przed startem")
            if os.path.exists(sock_path):
                return
            time.sleep(0.1)
        raise RuntimeError("Xvfb nie uruchomił DISPLAY na czas")

    @staticmethod
    def _wait_for_port(port: int, proc: subprocess.Popen, timeout: float = 8.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"Proces dla portu {port} zakończył się przed startem")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.2)
                try:
                    sock.connect(("127.0.0.1", port))
                    return
                except Exception:
                    time.sleep(0.1)
        raise RuntimeError(f"Port {port} nie wystartował na czas")

    @staticmethod
    def _build_vnc_url(base_url: str, novnc_port: int) -> str:
        parsed = urlparse(base_url)
        scheme = parsed.scheme or "http"
        host = parsed.hostname or "localhost"
        return (
            f"{scheme}://{host}:{novnc_port}/vnc.html?autoconnect=1"
            f"&resize=remote&show_dot=1&path=websockify"
        )
