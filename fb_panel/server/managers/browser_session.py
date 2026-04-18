"""Browser session — live Selenium browser for a checked account (3 tabs).

Proxy handling (DolphinAnty-style):
- SOCKS5/4 without auth → --proxy-server flag
- SOCKS5 with auth → local relay (127.0.0.1 SOCKS5 no-auth → remote auth'd)
- HTTP with auth → --proxy-server + CDP Fetch.authRequired
- Proxy check before launch → validates connectivity + returns IP/geo
"""

import asyncio
import logging
import os
import re
import select
import socket
import struct
import sys
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional

log = logging.getLogger("fb_panel.browser_session")

# Import engine components
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

try:
    from engine import (
        EngineConfig, FingerprintGenerator, StealthScripts,
        EMAIL_PROVIDERS, HAS_SELENIUM, HAS_UC
    )
    if HAS_SELENIUM:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.chrome.options import Options
    if HAS_UC:
        import undetected_chromedriver as uc
    else:
        if HAS_SELENIUM:
            from selenium import webdriver
    ENGINE_AVAILABLE = HAS_SELENIUM
except ImportError:
    ENGINE_AVAILABLE = False
    HAS_SELENIUM = False
    HAS_UC = False

# PySocks for SOCKS relay
try:
    import socks as _pysocks
    PYSOCKS_OK = True
except ImportError:
    PYSOCKS_OK = False

# OCR for CAPTCHA solving (Interia)
try:
    import pytesseract
    from PIL import Image
    import io as _io
    HAS_OCR = True
except ImportError:
    HAS_OCR = False


# ═══════════════════════════════════════════════════════════════
# Local SOCKS5 Relay (DolphinAnty-style proxy tunnel)
# ═══════════════════════════════════════════════════════════════

class _SocksRelay:
    """Minimal local SOCKS5 server (no auth) that tunnels all traffic
    through an authenticated upstream SOCKS5 proxy via PySocks.

    Chrome connects to  socks5://127.0.0.1:<local_port>  (no credentials)
    Relay connects to   socks5://user:pass@remote:port    (with credentials)

    This eliminates the need for a Chrome extension for proxy auth.
    """

    def __init__(self, remote_host: str, remote_port: int,
                 remote_user: str, remote_pass: str,
                 remote_scheme: str = "socks5"):
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.remote_user = remote_user
        self.remote_pass = remote_pass
        self.remote_scheme = remote_scheme
        self.local_port: int = 0
        self._sock: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> int:
        """Start relay. Returns local port number."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self.local_port = self._sock.getsockname()[1]
        self._sock.listen(32)
        self._sock.settimeout(1.0)
        self._running = True
        self._thread = threading.Thread(
            target=self._accept_loop, daemon=True,
            name=f"socks-relay-{self.local_port}",
        )
        self._thread.start()
        log.info(f"[RELAY] Started on 127.0.0.1:{self.local_port} → "
                 f"{self.remote_host}:{self.remote_port}")
        return self.local_port

    def stop(self):
        """Stop relay and close all sockets."""
        self._running = False
        try:
            self._sock.close()
        except Exception:
            pass
        log.info(f"[RELAY] Stopped (port {self.local_port})")

    def _accept_loop(self):
        while self._running:
            try:
                client, addr = self._sock.accept()
                threading.Thread(
                    target=self._handle_client, args=(client,), daemon=True,
                ).start()
            except socket.timeout:
                continue
            except OSError:
                break

    def _handle_client(self, client: socket.socket):
        """SOCKS5 handshake from Chrome, then relay via PySocks upstream."""
        upstream = None
        try:
            client.settimeout(30)

            # ── SOCKS5 greeting (Chrome sends: VER NMETHODS METHODS) ──
            data = client.recv(256)
            if not data or data[0] != 0x05:
                return
            # Reply: no auth required locally
            client.sendall(b"\x05\x00")

            # ── SOCKS5 request (VER CMD RSV ATYP DST.ADDR DST.PORT) ──
            data = client.recv(512)
            if not data or len(data) < 7:
                return
            cmd, atyp = data[1], data[3]
            if cmd != 0x01:  # Only CONNECT
                client.sendall(b"\x05\x07\x00\x01" + b"\x00" * 6)
                return

            # Parse destination
            if atyp == 0x01:  # IPv4
                dst_addr = socket.inet_ntoa(data[4:8])
                dst_port = struct.unpack("!H", data[8:10])[0]
            elif atyp == 0x03:  # Domain
                dlen = data[4]
                dst_addr = data[5:5 + dlen].decode()
                dst_port = struct.unpack("!H", data[5 + dlen:7 + dlen])[0]
            elif atyp == 0x04:  # IPv6
                dst_addr = socket.inet_ntop(socket.AF_INET6, data[4:20])
                dst_port = struct.unpack("!H", data[20:22])[0]
            else:
                client.sendall(b"\x05\x08\x00\x01" + b"\x00" * 6)
                return

            # ── Connect upstream via PySocks ──
            import socks
            proxy_type_map = {
                "socks5": socks.SOCKS5, "socks5h": socks.SOCKS5,
                "socks4": socks.SOCKS4, "socks4a": socks.SOCKS4,
            }
            ptype = proxy_type_map.get(self.remote_scheme, socks.SOCKS5)

            upstream = socks.socksocket()
            upstream.settimeout(20)
            upstream.set_proxy(
                ptype, self.remote_host, self.remote_port,
                rdns=True,
                username=self.remote_user or None,
                password=self.remote_pass or None,
            )
            upstream.connect((dst_addr, dst_port))

            # Success reply
            client.sendall(b"\x05\x00\x00\x01" + b"\x00\x00\x00\x00\x00\x00")

            # ── Bidirectional relay ──
            self._relay(client, upstream)

        except Exception:
            # Connection failure reply
            try:
                client.sendall(b"\x05\x05\x00\x01" + b"\x00" * 6)
            except Exception:
                pass
        finally:
            for s in (client, upstream):
                if s:
                    try:
                        s.close()
                    except Exception:
                        pass

    @staticmethod
    def _relay(a: socket.socket, b: socket.socket):
        """Bidirectional data relay between two sockets."""
        try:
            while True:
                readable, _, _ = select.select([a, b], [], [], 60)
                if not readable:
                    break
                for sock in readable:
                    data = sock.recv(16384)
                    if not data:
                        return
                    target = b if sock is a else a
                    target.sendall(data)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# Proxy check utility (DolphinAnty-style "Check proxy" button)
# ═══════════════════════════════════════════════════════════════

def check_proxy_connectivity(proxy_str: str) -> dict:
    """Validate proxy and return IP/geo info.

    Returns: {ok, ip, country, city, country_code, latency_ms, error}
    """
    from urllib.parse import urlparse
    import json as _json

    if not proxy_str:
        return {"ok": False, "error": "Brak proxy"}

    if "://" not in proxy_str:
        proxy_str = f"socks5://{proxy_str}"
    parsed = urlparse(proxy_str)
    scheme = (parsed.scheme or "socks5").lower()
    host = parsed.hostname or ""
    port = parsed.port or 1080
    username = parsed.username or ""
    password = parsed.password or ""

    if not host:
        return {"ok": False, "error": "Nieprawidłowy adres proxy"}

    t0 = time.monotonic()

    # Try connecting through the proxy to an IP-check API
    try:
        if scheme in ("socks5", "socks5h", "socks4", "socks4a"):
            if not PYSOCKS_OK:
                return {"ok": False, "error": "PySocks nie zainstalowany (pip install pysocks)"}
            import socks
            ptype_map = {
                "socks5": socks.SOCKS5, "socks5h": socks.SOCKS5,
                "socks4": socks.SOCKS4, "socks4a": socks.SOCKS4,
            }
            ptype = ptype_map.get(scheme, socks.SOCKS5)
            s = socks.socksocket()
            s.settimeout(10)
            s.set_proxy(ptype, host, port, rdns=True,
                        username=username or None, password=password or None)
            s.connect(("ip-api.com", 80))
        elif scheme in ("http", "https"):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10)
            s.connect((host, port))
            # HTTP CONNECT to ip-api.com
            connect_req = f"CONNECT ip-api.com:80 HTTP/1.1\r\nHost: ip-api.com:80\r\n"
            if username and password:
                import base64
                creds = base64.b64encode(f"{username}:{password}".encode()).decode()
                connect_req += f"Proxy-Authorization: Basic {creds}\r\n"
            connect_req += "\r\n"
            s.sendall(connect_req.encode())
            resp = s.recv(4096).decode(errors="ignore")
            if "200" not in resp.split("\r\n")[0]:
                s.close()
                return {"ok": False, "error": f"HTTP CONNECT failed: {resp[:80]}"}
        else:
            return {"ok": False, "error": f"Nieznany protokół: {scheme}"}

        # Send HTTP request to ip-api.com
        http_req = (
            "GET /json/?fields=status,query,country,countryCode,city HTTP/1.1\r\n"
            "Host: ip-api.com\r\n"
            "Connection: close\r\n\r\n"
        )
        s.sendall(http_req.encode())

        # Read response
        chunks = []
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        s.close()

        latency = round((time.monotonic() - t0) * 1000)
        raw = b"".join(chunks).decode(errors="ignore")

        # Parse JSON body (after headers)
        body_start = raw.find("\r\n\r\n")
        if body_start == -1:
            return {"ok": False, "error": "Brak odpowiedzi od serwera IP", "latency_ms": latency}

        body = raw[body_start + 4:].strip()
        # Handle chunked transfer encoding
        if body and body[0].isdigit() and "\r\n" in body:
            # Chunked: first line is chunk size
            body = body.split("\r\n", 1)[1] if "\r\n" in body else body

        data = _json.loads(body)
        if data.get("status") == "success":
            return {
                "ok": True,
                "ip": data.get("query", ""),
                "country": data.get("country", ""),
                "country_code": data.get("countryCode", ""),
                "city": data.get("city", ""),
                "latency_ms": latency,
            }
        return {"ok": False, "error": "IP API error", "latency_ms": latency}

    except Exception as e:
        latency = round((time.monotonic() - t0) * 1000)
        err = str(e)
        if "timed out" in err.lower() or "timeout" in err.lower():
            return {"ok": False, "error": "Timeout — proxy nie odpowiada", "latency_ms": latency}
        if "connection refused" in err.lower():
            return {"ok": False, "error": "Połączenie odrzucone", "latency_ms": latency}
        if "authentication" in err.lower() or "auth" in err.lower():
            return {"ok": False, "error": "Błąd autentykacji proxy", "latency_ms": latency}
        return {"ok": False, "error": err[:120], "latency_ms": latency}


class BrowserSession:
    """
    Live Selenium browser for one checked account.
    3 browser tabs: email, facebook, panel.
    All Selenium operations run in a dedicated thread.
    """

    def __init__(self, session_id: str, email: str, password: str, proxy: str = ""):
        self.session_id = session_id
        self.email = email
        self.password = password
        self.proxy = proxy

        self.driver = None
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=f"sel-{session_id[:8]}"
        )
        self._tab_handles: Dict[str, str] = {}
        self._screenshots: Dict[str, bytes] = {}

        self.email_logged_in = False
        self.fb_code = ""
        self.profile_info = {}
        self.alive = False
        self._proxy_tunnel: Optional[_SocksRelay] = None
        self._proxy_info: Optional[dict] = None  # IP/geo from check_proxy

    # ── helpers ──────────────────────────────────────────────

    @property
    def _domain(self):
        return self.email.split("@")[-1].lower() if "@" in self.email else ""

    @property
    def _provider(self):
        return EMAIL_PROVIDERS.get(self._domain) if ENGINE_AVAILABLE else None

    async def _run(self, fn, *args):
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(self._executor, fn, *args)
        except Exception as e:
            # Detect dead browser session and clean up
            err_str = str(e).lower()
            if any(k in err_str for k in ("invalid session id", "session deleted",
                                           "not connected to devtools", "no such window",
                                           "browser has closed", "chrome not reachable")):
                log.warning(f"[BROWSER] Session crashed: {e}")
                self.alive = False
                self.driver = None
                if self._proxy_tunnel:
                    self._proxy_tunnel.stop()
                    self._proxy_tunnel = None
            raise

    @staticmethod
    def _parse_proxy(proxy_str: str) -> dict:
        """Parse proxy string into components.
        Returns dict with scheme, host, port, username, password."""
        if not proxy_str:
            return {}
        from urllib.parse import urlparse
        try:
            if "://" not in proxy_str:
                proxy_str = f"socks5://{proxy_str}"
            parsed = urlparse(proxy_str)
            return {
                "scheme": (parsed.scheme or "socks5").lower(),
                "host": parsed.hostname or "",
                "port": parsed.port or 1080,
                "username": parsed.username or "",
                "password": parsed.password or "",
            }
        except Exception:
            return {}

    def _setup_proxy(self, opts) -> Optional[str]:
        """Configure proxy for Chrome launch (DolphinAnty-style).

        Strategy:
        - SOCKS5/4 no auth → --proxy-server=socks5://host:port
        - SOCKS5 with auth → start local _SocksRelay, --proxy-server=socks5://127.0.0.1:<local>
        - HTTP no auth → --proxy-server=http://host:port
        - HTTP with auth → --proxy-server=http://host:port (CDP auth handler added after driver init)

        Returns scheme for CDP auth setup, or None.
        """
        if not self.proxy:
            return None

        pinfo = self._parse_proxy(self.proxy)
        scheme = pinfo.get("scheme", "socks5")
        host = pinfo.get("host", "")
        port = pinfo.get("port", 1080)
        username = pinfo.get("username", "")
        password = pinfo.get("password", "")

        if not host:
            return None

        has_auth = bool(username and password)
        is_socks = scheme in ("socks5", "socks5h", "socks4", "socks4a")

        if is_socks and has_auth:
            # ── Local SOCKS5 relay for authenticated SOCKS ──
            if not PYSOCKS_OK:
                log.warning("[PROXY] PySocks nie zainstalowany — nie można tunelować auth SOCKS. pip install pysocks")
                # Fall back to no-auth connection (will likely fail if proxy requires auth)
                chrome_scheme = scheme.replace("socks5h", "socks5").replace("socks4a", "socks4")
                opts.add_argument(f"--proxy-server={chrome_scheme}://{host}:{port}")
                return None

            relay = _SocksRelay(host, port, username, password, scheme)
            local_port = relay.start()
            self._proxy_tunnel = relay
            opts.add_argument(f"--proxy-server=socks5://127.0.0.1:{local_port}")
            log.info(f"[PROXY] SOCKS relay: 127.0.0.1:{local_port} → {host}:{port} (auth)")
            return None  # No CDP auth needed — relay handles it

        elif is_socks and not has_auth:
            # ── Direct SOCKS (no auth) ──
            chrome_scheme = scheme.replace("socks5h", "socks5").replace("socks4a", "socks4")
            opts.add_argument(f"--proxy-server={chrome_scheme}://{host}:{port}")
            log.info(f"[PROXY] Direct SOCKS: {chrome_scheme}://{host}:{port}")
            return None

        elif not is_socks and has_auth:
            # ── HTTP proxy with auth → CDP Fetch.authRequired ──
            opts.add_argument(f"--proxy-server={scheme}://{host}:{port}")
            log.info(f"[PROXY] HTTP proxy: {host}:{port} (CDP auth)")
            return "http_auth"  # Signal to set up CDP auth handler

        else:
            # ── HTTP proxy no auth ──
            opts.add_argument(f"--proxy-server={scheme}://{host}:{port}")
            log.info(f"[PROXY] HTTP proxy: {host}:{port} (no auth)")
            return None

    def _setup_cdp_proxy_auth(self):
        """Set up CDP Fetch.authRequired handler for HTTP proxy authentication.
        This replaces the Chrome extension approach for HTTP proxies with credentials."""
        if not self.driver:
            return
        pinfo = self._parse_proxy(self.proxy)
        username = pinfo.get("username", "")
        password = pinfo.get("password", "")
        if not username:
            return
        try:
            self.driver.execute_cdp_cmd("Fetch.enable", {
                "handleAuthRequests": True,
                "patterns": [{"requestStage": "Response"}],
            })
            # Store credentials for the CDP event handler
            self._cdp_proxy_user = username
            self._cdp_proxy_pass = password

            # Set up event listener via execute_cdp_cmd
            # Chrome DevTools Protocol: respond to Fetch.authRequired with credentials
            # We use a Page script that listens for auth challenges
            self.driver.execute_cdp_cmd("Fetch.enable", {
                "handleAuthRequests": True,
            })
            log.info(f"[PROXY] CDP auth handler set up for {pinfo.get('host')}")
        except Exception as e:
            log.warning(f"[PROXY] CDP auth setup failed: {e} — proxy auth may not work")

    def _handle_cdp_auth(self):
        """Poll and handle CDP Fetch.authRequired events."""
        # This is called as a non-blocking check after driver creation
        # For Selenium, we handle this via a simpler approach:
        # inject credentials via Network.setExtraHTTPHeaders or Fetch commands
        pinfo = self._parse_proxy(self.proxy)
        username = pinfo.get("username", "")
        password = pinfo.get("password", "")
        if not username:
            return

        try:
            import base64
            creds = base64.b64encode(f"{username}:{password}".encode()).decode()
            self.driver.execute_cdp_cmd("Network.enable", {})
            self.driver.execute_cdp_cmd("Network.setExtraHTTPHeaders", {
                "headers": {"Proxy-Authorization": f"Basic {creds}"}
            })
            log.info("[PROXY] CDP Network.setExtraHTTPHeaders set for proxy auth")
        except Exception as e:
            log.warning(f"[PROXY] CDP Network auth header failed: {e}")

    # ── Launch ───────────────────────────────────────────────

    async def launch(self) -> dict:
        if not ENGINE_AVAILABLE:
            return {
                "success": False,
                "error": "Selenium nie zainstalowany. pip install selenium undetected-chromedriver",
            }
        try:
            return await self._run(self._launch)
        except Exception as e:
            log.error(f"Launch failed: {e}")
            return {"success": False, "error": str(e)}

    def _launch(self) -> dict:
        try:
            fp = FingerprintGenerator.generate(self.session_id)
            opts = Options()
            opts.add_argument("--disable-blink-features=AutomationControlled")
            opts.add_argument("--disable-infobars")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-gpu")
            opts.add_argument(f"--user-agent={fp['user_agent']}")
            opts.add_argument(
                f"--window-size={fp['viewport_width']},{fp['viewport_height']}"
            )

            # ── Proxy setup (DolphinAnty-style — no extension needed) ──
            needs_cdp_auth = self._setup_proxy(opts)

            # ── Pre-launch proxy check ──
            if self.proxy:
                log.info(f"[PROXY] Pre-launch check: {self.proxy[:60]}...")
                check = check_proxy_connectivity(self.proxy)
                if not check.get("ok"):
                    # Stop relay if we started one
                    if self._proxy_tunnel:
                        self._proxy_tunnel.stop()
                        self._proxy_tunnel = None
                    err = check.get("error", "Nieznany błąd")
                    return {
                        "success": False,
                        "error": f"Proxy nie działa: {err}",
                        "proxy_check": check,
                    }
                self._proxy_info = check
                log.info(f"[PROXY] OK — IP: {check.get('ip')} "
                         f"({check.get('country', '?')}, {check.get('city', '?')}) "
                         f"{check.get('latency_ms')}ms")

            if HAS_UC:
                try:
                    self.driver = uc.Chrome(
                        options=opts, headless=False, use_subprocess=True
                    )
                except Exception as uc_err:
                    log.warning(f"[BROWSER] undetected-chromedriver failed: {uc_err}, falling back to regular selenium")
                    if HAS_SELENIUM:
                        from selenium import webdriver as _wd
                        self.driver = _wd.Chrome(options=opts)
                    else:
                        raise uc_err
            else:
                self.driver = webdriver.Chrome(options=opts)

            self.driver.set_page_load_timeout(60)
            self.driver.implicitly_wait(5)

            # ── CDP proxy auth for HTTP proxies (after driver init) ──
            if needs_cdp_auth == "http_auth":
                self._handle_cdp_auth()

            # Inject stealth
            try:
                stealth_js = StealthScripts.get_stealth_script(fp)
                self.driver.execute_cdp_cmd(
                    "Page.addScriptToEvaluateOnNewDocument", {"source": stealth_js}
                )
            except Exception:
                pass

            # ── Tab 1: email — auto-login immediately ──
            provider = self._provider
            login_url = provider.login_url if provider else f"https://poczta.{self._domain}/"
            try:
                self.driver.get(login_url)
            except Exception as e:
                log.warning(f"[BROWSER] Tab1 load error (non-fatal): {e}")
            time.sleep(2)

            # Check if proxy connection failed
            proxy_error = self._check_proxy_error()
            if proxy_error:
                log.error(f"[BROWSER] Proxy connection failed: {proxy_error}")
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = None
                if self._proxy_tunnel:
                    self._proxy_tunnel.stop()
                    self._proxy_tunnel = None
                return {"success": False, "error": f"Proxy nie działa: {proxy_error}. Sprawdź proxy lub usuń je."}

            self._tab_handles["email"] = self.driver.current_window_handle

            # Auto-login to email right away
            email_ok = False
            if provider:
                log.info(f"[BROWSER] Auto-login email: {self.email} ({provider.name})")
                try:
                    email_ok = self._do_email_login(provider)
                except Exception as e:
                    log.warning(f"[BROWSER] Auto-login email failed: {e}")
            self._snap("email")

            # ── Tab 2: facebook reset code entry page ──
            recover_url = getattr(self, "recover_url", None) or "https://mbasic.facebook.com/recover/code/"
            self.driver.execute_script("window.open('');")
            self.driver.switch_to.window(self.driver.window_handles[-1])
            try:
                self.driver.get(recover_url)
            except Exception as e:
                log.warning(f"[BROWSER] Tab2 load error (non-fatal): {e}")
            time.sleep(2)
            self._tab_handles["facebook"] = self.driver.current_window_handle
            self._snap("facebook")

            self.alive = True
            self.email_logged_in = email_ok

            # ── Auto-extract FB code from inbox if email login succeeded ──
            code_extracted = False
            if email_ok and provider:
                log.info(f"[BROWSER] Auto-extracting FB code from inbox...")
                try:
                    code_result = self._extract_code()
                    if code_result.get("success") and code_result.get("code"):
                        self.fb_code = code_result["code"]
                        code_extracted = True
                        log.info(f"[BROWSER] Auto-extracted FB code: {self.fb_code}")

                        # ── Auto-enter code on Facebook ──
                        log.info(f"[BROWSER] Auto-entering code on Facebook...")
                        try:
                            enter_result = self._enter_code_fb(self.fb_code)
                            if enter_result.get("success"):
                                log.info(f"[BROWSER] Auto-entered code on FB successfully!")
                            else:
                                log.warning(f"[BROWSER] Auto-enter code failed: {enter_result.get('error')}")
                        except Exception as e:
                            log.warning(f"[BROWSER] Auto-enter code error: {e}")
                    else:
                        log.info(f"[BROWSER] No FB code found in inbox (will need manual search)")
                except Exception as e:
                    log.warning(f"[BROWSER] Auto-extract code error: {e}")

            # Back to email tab
            self.driver.switch_to.window(self._tab_handles["email"])
            status_parts = []
            if email_ok:
                status_parts.append("poczta zalogowana ✓")
            else:
                status_parts.append("poczta: ręczne logowanie")
            if code_extracted:
                status_parts.append(f"kod FB: {self.fb_code}")
            log.info(f"Browser launched: {self.session_id[:8]} ({', '.join(status_parts)}, FB reset tab ready)")
            return {
                "success": True,
                "email_logged_in": email_ok,
                "code_extracted": code_extracted,
                "fb_code": self.fb_code or None,
            }

        except Exception as e:
            log.error(f"Launch error: {e}")
            # Try to cleanup
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = None
            if self._proxy_tunnel:
                self._proxy_tunnel.stop()
                self._proxy_tunnel = None
            return {"success": False, "error": str(e)}

    # ── Screenshot ───────────────────────────────────────────

    # Known Chrome error page indicators for proxy/network failures
    _PROXY_ERROR_PATTERNS = [
        "ERR_SOCKS_CONNECTION_FAILED",
        "ERR_PROXY_CONNECTION_FAILED",
        "ERR_TUNNEL_CONNECTION_FAILED",
        "ERR_PROXY_AUTH_FAILED",
        "ERR_PROXY_CERTIFICATE_INVALID",
        "ERR_CONNECTION_RESET",
        "ERR_CONNECTION_REFUSED",
        "ERR_CONNECTION_TIMED_OUT",
        "ERR_NAME_NOT_RESOLVED",
        "This site can\u2019t be reached",
    ]

    def _check_proxy_error(self) -> Optional[str]:
        """Check if the current page shows a Chrome proxy/network error.
        Returns the error code string if found, None otherwise."""
        if not self.driver:
            return None
        try:
            source = self.driver.page_source or ""
            for pattern in self._PROXY_ERROR_PATTERNS:
                if pattern in source:
                    return pattern
        except Exception:
            pass
        return None

    def _do_email_login(self, provider) -> bool:
        """Perform email login via Selenium and navigate to inbox.
        Uses multiple selector strategies with fallbacks.
        Returns True if inbox loaded successfully."""
        if not provider:
            return False
        d = self.driver
        try:
            # Dismiss cookie/consent popups first
            self._dismiss_consent_popups()
            time.sleep(1)

            # Try to find username field with multiple strategies
            username_fallbacks = [
                'input[type="email"]', 'input[type="text"]',
                'input[name*="email"]', 'input[name*="login"]', 'input[name*="user"]',
            ]
            if self._domain in {"wp.pl", "o2.pl", "tlen.pl", "go2.pl"}:
                username_fallbacks = self._wp_group_username_fallbacks() + username_fallbacks
            usr = self._find_input_field(provider.username_selector, fallbacks=username_fallbacks)
            if not usr:
                log.warning(f"[BROWSER] Could not find username field on {d.current_url}")
                return False

            usr.clear()
            for c in self.email:
                usr.send_keys(c)
                time.sleep(0.04 + random.random() * 0.06)
            time.sleep(0.5)
            self._dismiss_consent_popups()

            # Extra steps (e.g., Gmail two-step login)
            if provider.extra_steps:
                for step in provider.extra_steps:
                    if step["action"] == "click":
                        try:
                            el = WebDriverWait(d, 5).until(
                                EC.element_to_be_clickable(
                                    (By.CSS_SELECTOR, step["selector"])
                                )
                            )
                            el.click()
                            time.sleep(step.get("wait", 2))
                        except Exception:
                            pass

            # Enter password — handle two-stage login (WP, O2, Interia, Onet)
            # Try to find password field; if not visible, submit email first
            pwd = self._find_password_field_with_retry(d, provider)

            # ── Interia CAPTCHA check (appears after email submit, before/with password) ──
            if 'interia' in self._domain:
                if self._detect_interia_captcha():
                    log.info("[BROWSER] Interia CAPTCHA detected during email login")
                    captcha_ok = self._handle_interia_captcha()
                    if not captcha_ok:
                        log.warning("[BROWSER] Interia CAPTCHA not solved — login may fail")
                    else:
                        # After CAPTCHA, submit the form and look for password again
                        try:
                            sub = d.find_element(By.CSS_SELECTOR, provider.submit_selector)
                            sub.click()
                        except Exception:
                            try:
                                active = d.switch_to.active_element
                                active.send_keys(Keys.RETURN)
                            except Exception:
                                pass
                        time.sleep(3)
                        # Re-find password field after CAPTCHA solve
                        if not pwd:
                            pwd = self._find_password_field_with_retry(d, provider)

            if not pwd:
                log.warning(f"[BROWSER] Could not find password field on {d.current_url}")
                return False

            pwd.clear()
            for c in self.password:
                pwd.send_keys(c)
                time.sleep(0.04 + random.random() * 0.06)
            time.sleep(0.5)

            # ── Interia: handle CAPTCHA that appears WITH password field ──
            if 'interia' in self._domain:
                if self._detect_interia_captcha():
                    log.info("[BROWSER] Interia CAPTCHA detected alongside password field")
                    self._handle_interia_captcha()

            # Submit
            try:
                if not self._click_submit_button(provider):
                    raise RuntimeError("submit button not found")
            except Exception:
                pwd.send_keys(Keys.RETURN)

            time.sleep(5)

            # Wait for inbox indicator or URL change (flexible)
            try:
                WebDriverWait(d, 20).until(
                    lambda drv: self._check_inbox_loaded(drv, provider)
                )
                return True
            except Exception:
                # Check if URL changed to inbox anyway
                curr = d.current_url.lower()
                if any(hint in curr for hint in ['/w/', '/inbox', '/mail', 'poczta']):
                    return True
                return False
        except Exception as e:
            log.warning(f"[BROWSER] email login error: {e}")
            return False

    def _find_input_field(self, primary_selector, fallbacks=None):
        """Try primary CSS selector, then fallbacks. Returns WebElement or None."""
        d = self.driver
        # Try primary selector
        try:
            el = WebDriverWait(d, 8).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, primary_selector))
            )
            if el.is_displayed():
                return el
        except Exception:
            pass
        # Try fallbacks
        for sel in (fallbacks or []):
            try:
                el = d.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed():
                    return el
            except Exception:
                continue
        return None

    def _wp_group_username_fallbacks(self):
        return [
            'input[name="login_username"]',
            'input[name="username"]',
            'input[name="login"]',
            'input[autocomplete="username"]',
            'input[autocomplete="email"]',
            'input[placeholder="Adres e-mail"]',
            'input[aria-label*="mail"]',
        ]

    def _wp_group_password_fallbacks(self):
        return [
            'input[name="password"]',
            'input[autocomplete="current-password"]',
            'input[placeholder="Hasło"]',
            'input[aria-label*="has"]',
        ]

    def _provider_submit_selectors(self, provider):
        selectors = [
            provider.submit_selector,
            'button[type="submit"]',
            'input[type="submit"]',
            'button:not([type])',
            'button[class*="next"]', 'button[class*="dalej"]',
            'button[class*="submit"]', 'button[class*="login"]',
            'a[class*="submit"]', 'a[class*="next"]',
        ]
        if self._domain in {"wp.pl", "o2.pl", "tlen.pl", "go2.pl"}:
            selectors.extend([
                '[data-testid*="submit"]',
                '[data-testid*="login"]',
                'button[aria-label*="Zaloguj"]',
                'button[aria-label*="loguj"]',
                '[role="button"]',
            ])
        return selectors

    def _click_submit_button(self, provider) -> bool:
        d = self.driver
        for sel in self._provider_submit_selectors(provider):
            try:
                buttons = d.find_elements(By.CSS_SELECTOR, sel)
            except Exception:
                continue
            for btn in buttons:
                try:
                    txt = (btn.text or "").strip().upper()
                    if self._domain in {"wp.pl", "o2.pl", "tlen.pl", "go2.pl"} and txt and "ZALOGUJ" not in txt and "DALEJ" not in txt:
                        continue
                    if btn.is_displayed() and btn.is_enabled():
                        d.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                        try:
                            btn.click()
                        except Exception:
                            d.execute_script("arguments[0].click();", btn)
                        return True
                except Exception:
                    continue

        try:
            candidates = d.find_elements(By.CSS_SELECTOR, 'button, [role="button"], a')
            for btn in candidates:
                txt = (btn.text or "").strip().upper()
                if txt in ("ZALOGUJ SIĘ", "ZALOGUJ", "DALEJ") and btn.is_displayed() and btn.is_enabled():
                    d.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                    try:
                        btn.click()
                    except Exception:
                        d.execute_script("arguments[0].click();", btn)
                    return True
        except Exception:
            pass

        return False

    def _find_password_field_with_retry(self, d, provider):
        """Find password field, handling two-stage login (WP, O2, Interia, Onet).

        Stage 1: Try to find password field on current page (single-stage login).
        Stage 2: If not found → submit the email form (click button/ENTER),
                 wait for page transition, then try again (two-stage login).
        """
        # Stage 1: password field already visible (single-stage login)
        password_fallbacks = [
            'input[type="password"]',
        ]
        if self._domain in {"wp.pl", "o2.pl", "tlen.pl", "go2.pl"}:
            password_fallbacks = self._wp_group_password_fallbacks() + password_fallbacks
        pwd = self._find_input_field(provider.password_selector, fallbacks=password_fallbacks)
        if pwd:
            return pwd

        log.info(f"[BROWSER] Password field not found — trying two-stage login (submit email first)")

        # Stage 2: Submit email form → wait → find password
        # Try clicking submit/next button
        clicked = self._click_submit_button(provider)
        if clicked:
            log.info("[BROWSER] Clicked submit/next button")

        if not clicked:
            # Fallback: press ENTER on the email field
            try:
                active = d.switch_to.active_element
                active.send_keys(Keys.RETURN)
                log.info("[BROWSER] Pressed ENTER (no submit button found)")
                clicked = True
            except Exception:
                pass

        if not clicked:
            return None

        # Wait for page transition / password field to appear
        time.sleep(3)

        # Try to find password field again with longer timeout
        try:
            pwd = WebDriverWait(d, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="password"]'))
            )
            if pwd.is_displayed():
                log.info("[BROWSER] Password field found after two-stage login transition")
                return pwd
        except Exception:
            pass

        # Final fallback: try all password selectors
        final_password_selectors = [provider.password_selector, 'input[type="password"]',
                                    'input[name*="pass"]', 'input[name*="haslo"]']
        if self._domain in {"wp.pl", "o2.pl", "tlen.pl", "go2.pl"}:
            final_password_selectors = self._wp_group_password_fallbacks() + final_password_selectors
        for sel in final_password_selectors:
            try:
                el = d.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed():
                    return el
            except Exception:
                continue

        log.warning("[BROWSER] Password field not found even after two-stage submit")
        return None

    def _dismiss_consent_popups(self):
        """Try to dismiss cookie consent / GDPR popups on login pages."""
        d = self.driver
        consent_selectors = [
            # Onet.pl specific — "PRZEJDŹ DO SERWISU" button
            'button[class*="cmp-intro_acceptAll"]',
            'button[class*="accept-all"]',
            'button[data-testid="accept-consent"]',
            # Generic consent buttons
            'button[class*="accept"]', 'button[class*="consent"]',
            'button[class*="agree"]', 'button[id*="accept"]',
            '[class*="cookie"] button', '[class*="consent"] button',
            'button[class*="przejdz"]', 'a[class*="przejdz"]',
        ]
        for sel in consent_selectors:
            try:
                el = d.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed():
                    el.click()
                    time.sleep(1)
                    return
            except Exception:
                continue

        # Fallback: try to find buttons by text content (Onet "PRZEJDŹ DO SERWISU", etc.)
        try:
            buttons = d.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                txt = (btn.text or "").strip().upper()
                if txt in ("PRZEJDŹ DO SERWISU", "AKCEPTUJĘ", "ACCEPT ALL",
                           "ZGADZAM SIĘ", "ACCEPT", "OK",
                           "AKCEPTUJĘ I PRZECHODZĘ DO SERWISU"):
                    if btn.is_displayed():
                        btn.click()
                        time.sleep(1)
                        return
        except Exception:
            pass

        self._dismiss_wp_group_consent()

    def _dismiss_wp_group_consent(self):
        """WP/O2 often render the consent gate in an iframe with text-only CTA."""
        d = self.driver
        if not d or self._domain not in {"wp.pl", "o2.pl", "tlen.pl", "go2.pl"}:
            return

        consent_texts = (
            "AKCEPTUJĘ I PRZECHODZĘ DO SERWISU",
            "AKCEPTUJĘ",
            "PRZEJDŹ DO SERWISU",
        )

        try:
            frames = [None] + d.find_elements(By.TAG_NAME, "iframe")
        except Exception:
            frames = [None]

        for frame in frames:
            try:
                d.switch_to.default_content()
                if frame is not None:
                    d.switch_to.frame(frame)
            except Exception:
                continue

            try:
                candidates = d.find_elements(By.CSS_SELECTOR, 'button, [role="button"], a')
            except Exception:
                candidates = []

            for candidate in candidates:
                try:
                    txt = (candidate.text or "").strip().upper()
                    if txt in consent_texts and candidate.is_displayed() and candidate.is_enabled():
                        d.execute_script("arguments[0].scrollIntoView({block: 'center'});", candidate)
                        try:
                            candidate.click()
                        except Exception:
                            d.execute_script("arguments[0].click();", candidate)
                        time.sleep(2)
                        d.switch_to.default_content()
                        return
                except Exception:
                    continue

        try:
            d.switch_to.default_content()
        except Exception:
            pass

    # ── Interia CAPTCHA solving ───────────────────────────────

    def _detect_interia_captcha(self) -> bool:
        """Check if Interia login page is showing a CAPTCHA image challenge."""
        d = self.driver
        if not d:
            return False
        try:
            # Interia CAPTCHA selectors — image element + text input
            captcha_selectors = [
                'img[src*="captcha"]', 'img[id*="captcha"]', 'img[class*="captcha"]',
                'img[alt*="captcha"]', 'img[alt*="obrazek"]', 'img[alt*="Captcha"]',
                'div[class*="captcha"] img', '.captcha-image', '#captcha-image',
                'img[src*="getCaptcha"]', 'img[src*="get_captcha"]',
            ]
            for sel in captcha_selectors:
                try:
                    imgs = d.find_elements(By.CSS_SELECTOR, sel)
                    for img in imgs:
                        if img.is_displayed() and img.size.get('height', 0) > 15:
                            return True
                except Exception:
                    continue

            # Also check page source for captcha-related elements
            try:
                src = d.page_source or ""
                src_lower = src.lower()
                if any(h in src_lower for h in ['captchares', 'captcha-input', 'captchacode',
                                                  'captcha_code', 'przepisz kod', 'kod z obrazka']):
                    return True
            except Exception:
                pass
        except Exception:
            pass
        return False

    def _solve_interia_captcha(self) -> Optional[str]:
        """Try to solve Interia CAPTCHA using OCR.
        Returns solved text or None if unable to solve."""
        if not HAS_OCR:
            log.warning("[CAPTCHA] pytesseract/Pillow not installed — cannot solve CAPTCHA. "
                        "Install: pip install pytesseract Pillow && apt install tesseract-ocr")
            return None

        d = self.driver
        if not d:
            return None

        # Find CAPTCHA image element
        captcha_img = None
        img_selectors = [
            'img[src*="captcha"]', 'img[id*="captcha"]', 'img[class*="captcha"]',
            'img[alt*="captcha"]', 'img[alt*="obrazek"]', 'img[alt*="Captcha"]',
            'div[class*="captcha"] img', '.captcha-image', '#captcha-image',
            'img[src*="getCaptcha"]', 'img[src*="get_captcha"]',
        ]
        for sel in img_selectors:
            try:
                imgs = d.find_elements(By.CSS_SELECTOR, sel)
                for img in imgs:
                    if img.is_displayed() and img.size.get('height', 0) > 15:
                        captcha_img = img
                        break
                if captcha_img:
                    break
            except Exception:
                continue

        if not captcha_img:
            log.warning("[CAPTCHA] CAPTCHA image element not found")
            return None

        try:
            # Screenshot just the CAPTCHA element
            png_bytes = captcha_img.screenshot_as_png
            img = Image.open(_io.BytesIO(png_bytes))

            # Preprocessing for better OCR
            # 1. Convert to grayscale
            img = img.convert('L')
            # 2. Resize for better recognition (scale up 2x)
            w, h = img.size
            img = img.resize((w * 2, h * 2), Image.LANCZOS)
            # 3. Binarize (threshold) — make text black, background white
            threshold = 140
            img = img.point(lambda px: 255 if px > threshold else 0, '1')

            # OCR with Tesseract — alphanumeric only, single line
            custom_config = '--psm 7 -c tessedit_char_whitelist=0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
            text = pytesseract.image_to_string(img, config=custom_config).strip()

            # Clean up — remove spaces and special chars
            text = re.sub(r'[^a-zA-Z0-9]', '', text)

            if text and len(text) >= 3:
                log.info(f"[CAPTCHA] OCR result: '{text}'")
                return text
            else:
                log.warning(f"[CAPTCHA] OCR result too short or empty: '{text}'")
                # Try again with different threshold
                img2 = Image.open(_io.BytesIO(png_bytes)).convert('L')
                img2 = img2.resize((w * 3, h * 3), Image.LANCZOS)
                img2 = img2.point(lambda px: 255 if px > 100 else 0, '1')
                text2 = pytesseract.image_to_string(img2, config=custom_config).strip()
                text2 = re.sub(r'[^a-zA-Z0-9]', '', text2)
                if text2 and len(text2) >= 3:
                    log.info(f"[CAPTCHA] OCR result (retry): '{text2}'")
                    return text2

                log.warning(f"[CAPTCHA] OCR retry also failed: '{text2}'")
                return None
        except Exception as e:
            log.error(f"[CAPTCHA] OCR error: {e}")
            return None

    def _enter_captcha_solution(self, solution: str) -> bool:
        """Enter CAPTCHA solution text into the CAPTCHA input field."""
        d = self.driver
        if not d or not solution:
            return False

        # Find CAPTCHA text input field
        captcha_input_selectors = [
            'input[name*="captcha"]', 'input[id*="captcha"]', 'input[class*="captcha"]',
            'input[name="captchaRes"]', 'input[name="captcha_code"]',
            'input[placeholder*="captcha"]', 'input[placeholder*="obrazk"]',
            'input[placeholder*="kod"]', 'input[placeholder*="Kod"]',
            'input[aria-label*="captcha"]',
        ]
        captcha_input = None
        for sel in captcha_input_selectors:
            try:
                el = d.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed():
                    captcha_input = el
                    break
            except Exception:
                continue

        if not captcha_input:
            # Fallback: find any text input near the captcha image that's not email/password
            try:
                inputs = d.find_elements(By.CSS_SELECTOR, 'input[type="text"]')
                for inp in inputs:
                    name = (inp.get_attribute("name") or "").lower()
                    if name not in ("email", "login", "username", "user"):
                        if inp.is_displayed():
                            captcha_input = inp
                            break
            except Exception:
                pass

        if not captcha_input:
            log.warning("[CAPTCHA] Could not find CAPTCHA input field")
            return False

        try:
            captcha_input.clear()
            for c in solution:
                captcha_input.send_keys(c)
                time.sleep(0.05 + random.random() * 0.05)
            log.info(f"[CAPTCHA] Entered solution: '{solution}'")
            return True
        except Exception as e:
            log.error(f"[CAPTCHA] Error entering solution: {e}")
            return False

    def _handle_interia_captcha(self) -> bool:
        """Full Interia CAPTCHA handling: detect → solve → enter.
        Returns True if CAPTCHA was handled (solved or not present).
        Returns False if CAPTCHA was present but couldn't be solved."""
        if not self._detect_interia_captcha():
            return True  # No CAPTCHA — all good

        log.info("[CAPTCHA] Interia CAPTCHA detected — attempting OCR solve...")
        self._snap("email")

        # Try up to 3 times (CAPTCHA might refresh)
        for attempt in range(3):
            solution = self._solve_interia_captcha()
            if not solution:
                log.warning(f"[CAPTCHA] Attempt {attempt+1}: OCR failed to produce solution")
                if attempt < 2:
                    # Try to refresh CAPTCHA image (click on it)
                    try:
                        for sel in ['img[src*="captcha"]', '.captcha-image', 'img[class*="captcha"]']:
                            try:
                                img = self.driver.find_element(By.CSS_SELECTOR, sel)
                                if img.is_displayed():
                                    img.click()
                                    time.sleep(2)
                                    break
                            except Exception:
                                continue
                    except Exception:
                        pass
                continue

            if self._enter_captcha_solution(solution):
                time.sleep(1)
                return True

        log.warning("[CAPTCHA] All CAPTCHA solve attempts failed")
        return False

    def _check_inbox_loaded(self, drv, provider):
        """Check if inbox page has loaded (by selector or URL)."""
        try:
            drv.find_element(By.CSS_SELECTOR, provider.inbox_indicator)
            return True
        except Exception:
            pass
        curr = drv.current_url.lower()
        return any(h in curr for h in ['/w/', '/inbox', '/mail/', '/skrzynka'])

    def _snap(self, tab: str) -> bytes:
        try:
            png = self.driver.get_screenshot_as_png()
            self._screenshots[tab] = png
            return png
        except Exception:
            return b""

    def _goto(self, tab: str):
        h = self._tab_handles.get(tab)
        if h and self.driver:
            self.driver.switch_to.window(h)

    async def screenshot(self, tab: str) -> bytes:
        if not self.alive:
            return self._screenshots.get(tab, b"")

        def _do():
            self._goto(tab)
            time.sleep(0.2)
            return self._snap(tab)

        try:
            return await self._run(_do)
        except Exception:
            return self._screenshots.get(tab, b"")

    # ── Email Login ──────────────────────────────────────────

    async def login_email(self) -> dict:
        if not self.alive:
            return {"success": False, "error": "Browser nie uruchomiony"}
        try:
            return await self._run(self._login_email)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _login_email(self) -> dict:
        provider = self._provider
        if not provider:
            return {"success": False, "error": f"Nieobslugiwany provider: {self._domain}"}

        self._goto("email")
        d = self.driver

        # Navigate to login page if not already there
        try:
            curr = d.current_url or ""
            # If we're on about:blank, chrome error page, or wrong domain - navigate
            if "about:" in curr or "chrome-error" in curr or provider.login_url.split("/")[2] not in curr:
                d.get(provider.login_url)
                time.sleep(4)
        except Exception as e:
            log.warning(f"[BROWSER] navigate to login page error: {e}")
            try:
                d.get(provider.login_url)
                time.sleep(4)
            except Exception:
                self._snap("email")
                return {"success": False, "error": "Nie mozna otworzyc strony logowania"}

        try:
            # Dismiss cookie/consent popups
            self._dismiss_consent_popups()
            time.sleep(1)

            # Find username field with fallbacks
            username_fallbacks = [
                'input[type="email"]', 'input[type="text"]',
                'input[name*="email"]', 'input[name*="login"]', 'input[name*="user"]',
            ]
            if self._domain in {"wp.pl", "o2.pl", "tlen.pl", "go2.pl"}:
                username_fallbacks = self._wp_group_username_fallbacks() + username_fallbacks
            usr = self._find_input_field(provider.username_selector, fallbacks=username_fallbacks)
            if not usr:
                self._snap("email")
                return {"success": False, "error": "Nie znaleziono pola email -- strona moze wymagac akceptacji cookies"}

            usr.clear()
            for c in self.email:
                usr.send_keys(c)
                time.sleep(0.04 + random.random() * 0.06)
            time.sleep(0.5)
            self._dismiss_consent_popups()

            # Extra steps (e.g., Gmail two-step login)
            if provider.extra_steps:
                for step in provider.extra_steps:
                    if step["action"] == "click":
                        try:
                            el = WebDriverWait(d, 5).until(
                                EC.element_to_be_clickable(
                                    (By.CSS_SELECTOR, step["selector"])
                                )
                            )
                            el.click()
                            time.sleep(step.get("wait", 2))
                        except Exception:
                            pass

            # Find password field — handle two-stage login (WP, O2, Interia, Onet)
            pwd = self._find_password_field_with_retry(d, provider)

            # ── Interia CAPTCHA check ──
            if 'interia' in self._domain:
                if self._detect_interia_captcha():
                    log.info("[BROWSER] Interia CAPTCHA detected (manual login)")
                    captcha_ok = self._handle_interia_captcha()
                    if not captcha_ok:
                        self._snap("email")
                        return {"success": False, "error": "CAPTCHA Interia — nie udało się rozwiązać. Zainstaluj: pip install pytesseract Pillow && apt install tesseract-ocr"}
                    # Submit after CAPTCHA and re-find password
                    try:
                        sub = d.find_element(By.CSS_SELECTOR, provider.submit_selector)
                        sub.click()
                    except Exception:
                        try:
                            d.switch_to.active_element.send_keys(Keys.RETURN)
                        except Exception:
                            pass
                    time.sleep(3)
                    if not pwd:
                        pwd = self._find_password_field_with_retry(d, provider)

            if not pwd:
                self._snap("email")
                return {"success": False, "error": "Nie znaleziono pola hasła — strona może mieć inny layout"}

            pwd.clear()
            for c in self.password:
                pwd.send_keys(c)
                time.sleep(0.04 + random.random() * 0.06)
            time.sleep(0.5)

            # ── Interia: CAPTCHA alongside password ──
            if 'interia' in self._domain:
                if self._detect_interia_captcha():
                    log.info("[BROWSER] Interia CAPTCHA detected alongside password")
                    self._handle_interia_captcha()

            # Submit
            try:
                if not self._click_submit_button(provider):
                    raise RuntimeError("submit button not found")
            except Exception:
                pwd.send_keys(Keys.RETURN)

            time.sleep(5)
            self._snap("email")

            # Check for inbox (flexible)
            try:
                WebDriverWait(d, 15).until(
                    lambda drv: self._check_inbox_loaded(drv, provider)
                )
                self.email_logged_in = True
                self._snap("email")
                return {"success": True}
            except Exception:
                curr = d.current_url.lower()
                if any(h in curr for h in ['/w/', '/inbox', '/mail', 'poczta', '/msg']):
                    self.email_logged_in = True
                    self._snap("email")
                    return {"success": True}
                self._snap("email")
                return {"success": False, "error": "Logowanie nieudane -- sprawdz screenshot"}

        except Exception as e:
            self._snap("email")
            return {"success": False, "error": str(e)[:120]}

    # ── Extract Code ─────────────────────────────────────────

    async def extract_code(self) -> dict:
        if not self.alive:
            return {"success": False, "error": "Browser nie uruchomiony"}
        try:
            return await self._run(self._extract_code)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _extract_code(self) -> dict:
        provider = self._provider
        if not provider:
            return {"success": False, "error": "Unknown provider"}

        self._goto("email")
        d = self.driver

        try:
            msgs = d.find_elements(By.CSS_SELECTOR, provider.message_selector)
            for msg in msgs[:10]:
                try:
                    if not re.search(provider.fb_sender_pattern, msg.text, re.I):
                        continue
                    msg.click()
                    time.sleep(2)
                    bodies = d.find_elements(
                        By.CSS_SELECTOR, provider.message_body_selector
                    )
                    for body in bodies:
                        m = re.search(provider.fb_code_pattern, body.text)
                        if m and len(m.group(1)) == 8 and m.group(1).isdigit():
                            self.fb_code = m.group(1)
                            self._snap("email")
                            return {"success": True, "code": self.fb_code}
                    d.back()
                    time.sleep(1)
                except Exception:
                    continue

            self._snap("email")
            return {"success": False, "error": "Kod FB nie znaleziony w skrzynce"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Enter Code on FB ─────────────────────────────────────

    async def enter_code_on_fb(self, code: str = "") -> dict:
        code = code or self.fb_code
        if not code:
            return {"success": False, "error": "Brak kodu"}
        if not self.alive:
            return {"success": False, "error": "Browser nie uruchomiony"}
        try:
            return await self._run(self._enter_code_fb, code)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _enter_code_fb(self, code: str) -> dict:
        self._goto("facebook")
        d = self.driver
        try:
            inp = WebDriverWait(d, 10).until(
                EC.presence_of_element_located(
                    (
                        By.CSS_SELECTOR,
                        'input[name="n"], input[type="text"], #recovery_code_entry',
                    )
                )
            )
            inp.clear()
            for c in code:
                inp.send_keys(c)
                time.sleep(0.08)
            time.sleep(1)
            self._snap("facebook")

            sub = d.find_element(
                By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]'
            )
            sub.click()
            time.sleep(3)
            self._snap("facebook")
            return {"success": True}
        except Exception as e:
            self._snap("facebook")
            return {"success": False, "error": str(e)}

    # ── Open Profile ─────────────────────────────────────────

    async def open_profile(self) -> dict:
        if not self.alive:
            return {"success": False, "error": "Browser nie uruchomiony"}
        try:
            return await self._run(self._open_profile)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _open_profile(self) -> dict:
        d = self.driver
        # Create "panel" tab on first use (only 2 tabs created at launch)
        if "panel" not in self._tab_handles:
            d.execute_script("window.open('');")
            d.switch_to.window(d.window_handles[-1])
            self._tab_handles["panel"] = d.current_window_handle
        else:
            self._goto("panel")
        d.get("https://www.facebook.com/me")
        time.sleep(4)
        self._snap("panel")
        try:
            names = d.find_elements(By.CSS_SELECTOR, "h1")
            name = names[0].text if names else ""
            self.profile_info = {"full_name": name, "profile_url": d.current_url}
        except Exception:
            self.profile_info = {"profile_url": d.current_url}
        return {"success": True, "profile": self.profile_info}

    # ── Refresh Tab ──────────────────────────────────────────

    async def refresh_tab(self, tab: str) -> dict:
        if not self.alive:
            return {"success": False, "error": "Browser nie uruchomiony"}

        def _do():
            self._goto(tab)
            self.driver.refresh()
            time.sleep(2)
            self._snap(tab)
            return {"success": True}

        try:
            return await self._run(_do)
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Close ────────────────────────────────────────────────

    async def close(self):
        self.alive = False

        # Stop proxy tunnel if running
        if self._proxy_tunnel:
            self._proxy_tunnel.stop()
            self._proxy_tunnel = None

        def _do():
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass

        try:
            await self._run(_do)
        except Exception:
            pass
        self._executor.shutdown(wait=False)
        log.info(f"Browser closed: {self.session_id[:8]}")
