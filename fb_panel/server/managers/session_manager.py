"""Session manager — manages active 3-tab sessions with live Selenium browsers."""

import logging
import random
import uuid
from typing import Dict, Optional

from server.models import SessionData, ProfileInfo, SessionTab, LogEntry, LogStatus
from server.managers.browser_session import BrowserSession, ENGINE_AVAILABLE

log = logging.getLogger("fb_panel.session_manager")


class SessionManager:
    """Manages active sessions — each with a live Selenium browser."""

    def __init__(self, proxy_manager=None, vnc_manager=None):
        self.sessions: Dict[str, SessionData] = {}
        self.browsers: Dict[str, BrowserSession] = {}
        self.proxy_manager = proxy_manager
        self.vnc_manager = vnc_manager

    # ── Launch (creates session + starts browser) ─────────────

    async def launch_session(self, entry: LogEntry, code: str = "", worker_os: str = "",
                             mode: str = "selenium", base_url: str = "", requested_proxy: str = "") -> dict:
        """Launch a new browser session for a successfully checked log."""
        sid = str(uuid.uuid4())[:12]
        provider = entry.email.split("@")[1] if "@" in entry.email else "unknown"
        proxy_entry = self._resolve_proxy(requested_proxy, entry.proxy)
        effective_proxy = proxy_entry.url if proxy_entry else ""
        proxy_info = self._proxy_info_from_entry(proxy_entry)

        if mode == "vnc":
            if not self.vnc_manager:
                return {"success": False, "error": "VNC manager not configured"}
            runtime = self.vnc_manager.start_session(sid, base_url)
            browser = BrowserSession(
                session_id=sid,
                email=entry.email,
                password=entry.password,
                proxy=effective_proxy,
                display_env=self.vnc_manager.get_launch_env(sid),
                force_plain_selenium=True,
            )
            browser.recover_url = getattr(entry, 'recover_url', None) or "https://mbasic.facebook.com/recover/code/"
            result = await browser.launch()
            if not result.get("success"):
                self.vnc_manager.stop_session(sid)
                return result

            runtime_info = self.vnc_manager.get_by_session(sid) or runtime
            browser_proxy_info = browser._proxy_info or proxy_info
            session = SessionData(
                id=sid,
                log_id=entry.id,
                email=entry.email,
                password=entry.password,
                proxy=effective_proxy,
                worker_os=worker_os,
                code=code,
                mode="vnc",
                proxy_info=browser_proxy_info,
                email_provider=provider,
                email_logged_in=result.get("email_logged_in", False),
                status="active",
                tabs=[
                    SessionTab(name="email", url=f"https://poczta.{provider}", status="ready", last_action="VNC + Selenium aktywne"),
                    SessionTab(name="facebook", url="https://facebook.com/login/identify/", status="ready", last_action="VNC + Selenium aktywne"),
                    SessionTab(name="panel", status="ready", last_action="Direct noVNC ready"),
                ],
                vnc_status=runtime_info.get("status", "running"),
                vnc_connected_at=runtime_info.get("connected_at", ""),
                vnc_url=runtime_info.get("vnc_url", ""),
                vnc_port=runtime_info.get("vnc_port", 0),
                novnc_port=runtime_info.get("novnc_port", 0),
            )
            self.sessions[sid] = session
            self.browsers[sid] = browser
            log.info(f"VNC session launched: {sid} for {entry.email}")
            return {
                "success": True,
                "session": session.to_dict(),
                "proxy_info": browser_proxy_info,
                "email_logged_in": result.get("email_logged_in", False),
                "code_extracted": result.get("code_extracted", False),
                "fb_code": result.get("fb_code"),
                "vnc_url": session.vnc_url,
            }

        browser = BrowserSession(
            session_id=sid,
            email=entry.email,
            password=entry.password,
            proxy=effective_proxy,
        )
        # Pass recover_url if stored on the entry
        browser.recover_url = getattr(entry, 'recover_url', None) or "https://mbasic.facebook.com/recover/code/"

        result = await browser.launch()
        if not result.get("success"):
            return result

        # Proxy info from pre-launch check (IP, country, city, latency)
        proxy_info = browser._proxy_info

        session = SessionData(
            id=sid,
            log_id=entry.id,
            email=entry.email,
            password=entry.password,
            proxy=effective_proxy,
            worker_os=worker_os,
            code=code,
            mode="selenium",
            proxy_info=proxy_info or proxy_info,
            email_provider=provider,
            tabs=[
                SessionTab(name="email", url=f"https://poczta.{provider}", status="ready"),
                SessionTab(name="facebook", url="https://facebook.com/login/identify/", status="ready"),
                SessionTab(name="panel", status="idle"),
            ],
        )

        self.sessions[sid] = session
        self.browsers[sid] = browser
        log.info(f"Session launched: {sid} for {entry.email}")

        resp = {"success": True, "session": session.to_dict()}
        if proxy_info:
            resp["proxy_info"] = proxy_info
        return resp

    # ── Queries ───────────────────────────────────────────────

    def add_browser_session(self, log_id: str, browser: BrowserSession) -> str:
        """Register an externally-launched BrowserSession (from engine_manager).
        Returns the session ID."""
        import uuid
        sid = str(uuid.uuid4())[:12]
        provider = browser.email.split("@")[1] if "@" in browser.email else "unknown"

        session = SessionData(
            id=sid,
            log_id=log_id,
            email=browser.email,
            password=browser.password,
            proxy=browser.proxy or "",
            worker_os="",
            code="",
            mode="selenium",
            proxy_info=browser._proxy_info or {},
            email_provider=provider,
            email_logged_in=browser.email_logged_in,
            tabs=[
                SessionTab(name="email", url=f"https://poczta.{provider}", status="ready"),
                SessionTab(name="facebook", url=getattr(browser, "recover_url", ""), status="ready"),
            ],
        )

        self.sessions[sid] = session
        self.browsers[sid] = browser
        log.info(f"Browser session registered: {sid} for {browser.email}")
        return sid

    def get_session(self, sid: str) -> Optional[SessionData]:
        return self.sessions.get(sid)

    def get_all(self) -> list:
        return [s.to_dict() for s in self.sessions.values() if s.status in ("active", "crashed")]

    # ── Dead session detection ──────────────────────────────────

    def _check_alive(self, sid: str) -> bool:
        """Check if browser is still alive. If dead, mark session as crashed and clean up.
        Returns True if alive, False if dead/missing."""
        session = self.sessions.get(sid)
        if session and session.mode == "vnc":
            return session.status in ("awaiting_vnc", "active")

        browser = self.browsers.get(sid)
        if not browser:
            return False
        if not browser.alive and browser.driver is None:
            s = self.sessions.get(sid)
            if s and s.status == "active":
                s.status = "crashed"
                log.warning(f"Session {sid} browser died — marked as crashed")
            self.browsers.pop(sid, None)
            return False
        return True

    # ── Close (async — closes browser) ────────────────────────

    async def close_session(self, sid: str) -> bool:
        s = self.sessions.get(sid)
        if not s:
            return False
        s.status = "closed"
        if self.vnc_manager and s.mode == "vnc":
            self.vnc_manager.stop_session(sid)
        browser = self.browsers.pop(sid, None)
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        log.info(f"Session closed: {sid}")
        return True

    # ── Screenshot ────────────────────────────────────────────

    async def get_screenshot(self, sid: str, tab: str) -> bytes:
        session = self.sessions.get(sid)
        if session and session.mode == "vnc":
            return b""
        if not self._check_alive(sid):
            return b""
        browser = self.browsers.get(sid)
        if not browser:
            return b""
        try:
            result = await browser.screenshot(tab)
        except Exception:
            result = b""
        # Re-check after call — browser may have died during screenshot
        self._check_alive(sid)
        return result

    # ── Browser actions ───────────────────────────────────────

    async def _safe_action(self, sid: str, action_name: str, coro) -> dict:
        """Wrapper for browser actions — checks alive before/after, catches crashes."""
        session = self.sessions.get(sid)
        if session and session.mode == "vnc":
            return {"success": False, "error": "Ta akcja nie jest dostępna w trybie VNC"}
        if not self._check_alive(sid):
            return {"success": False, "error": "Przeglądarka nie żyje — sesja crashed", "crashed": True}
        try:
            result = await coro
        except Exception as e:
            log.warning(f"Session {sid} action '{action_name}' error: {e}")
            self._check_alive(sid)
            return {"success": False, "error": f"Błąd przeglądarki: {str(e)[:100]}", "crashed": not self._check_alive(sid)}
        # Re-check after action
        self._check_alive(sid)
        return result

    async def action_login_email(self, sid: str) -> dict:
        browser = self.browsers.get(sid)
        if not browser:
            return {"success": False, "error": "Session not found"}
        result = await self._safe_action(sid, "login_email", browser.login_email())
        if result.get("success"):
            s = self.sessions.get(sid)
            if s:
                s.email_logged_in = True
                s.tabs[0].last_action = "Zalogowano do poczty"
        return result

    async def action_extract_code(self, sid: str) -> dict:
        browser = self.browsers.get(sid)
        if not browser:
            return {"success": False, "error": "Session not found"}
        result = await self._safe_action(sid, "extract_code", browser.extract_code())
        if result.get("success"):
            s = self.sessions.get(sid)
            if s:
                s.fb_code_extracted = result.get("code", "")
                s.code = result.get("code", "")
        return result

    async def action_enter_code(self, sid: str, code: str = "") -> dict:
        browser = self.browsers.get(sid)
        if not browser:
            return {"success": False, "error": "Session not found"}
        return await self._safe_action(sid, "enter_code", browser.enter_code_on_fb(code))

    async def action_open_profile(self, sid: str) -> dict:
        browser = self.browsers.get(sid)
        if not browser:
            return {"success": False, "error": "Session not found"}
        result = await self._safe_action(sid, "open_profile", browser.open_profile())
        if result.get("success"):
            s = self.sessions.get(sid)
            if s and result.get("profile"):
                p = result["profile"]
                s.profile.full_name = p.get("full_name", "")
                s.profile.profile_url = p.get("profile_url", "")
        return result

    async def action_refresh_tab(self, sid: str, tab: str) -> dict:
        browser = self.browsers.get(sid)
        if not browser:
            return {"success": False, "error": "Session not found"}
        return await self._safe_action(sid, "refresh_tab", browser.refresh_tab(tab))

    def get_vnc_status(self, sid: str) -> Optional[dict]:
        session = self.sessions.get(sid)
        if not session or session.mode != "vnc":
            return None
        if self.vnc_manager:
            reg = self.vnc_manager.get_by_session(sid)
            if reg:
                session.vnc_status = reg.get("status", session.vnc_status)
                session.vnc_connected_at = reg.get("connected_at", session.vnc_connected_at)
                session.vnc_url = reg.get("vnc_url", session.vnc_url)
                session.vnc_port = reg.get("vnc_port", session.vnc_port)
                session.novnc_port = reg.get("novnc_port", session.novnc_port)
                session.status = "active" if session.vnc_status == "running" else session.status
        return {
            "session_id": sid,
            "status": session.vnc_status or "stopped",
            "vnc_url": session.vnc_url,
            "connected_at": session.vnc_connected_at,
            "vnc_port": session.vnc_port,
            "novnc_port": session.novnc_port,
        }

    # ── Auto-actions toggles ──────────────────────────────────

    def toggle_auto_logout(self, sid: str, enabled: bool) -> Optional[dict]:
        s = self.sessions.get(sid)
        if not s:
            return None
        s.auto_logout_active = enabled
        return s.to_dict()

    def toggle_auto_disconnect(self, sid: str, enabled: bool) -> Optional[dict]:
        s = self.sessions.get(sid)
        if not s:
            return None
        s.auto_disconnect_active = enabled
        return s.to_dict()

    def toggle_auto_delete_posts(self, sid: str, enabled: bool) -> Optional[dict]:
        s = self.sessions.get(sid)
        if not s:
            return None
        s.auto_delete_posts_active = enabled
        return s.to_dict()

    def toggle_auto_delete_stories(self, sid: str, enabled: bool) -> Optional[dict]:
        s = self.sessions.get(sid)
        if not s:
            return None
        s.auto_delete_stories_active = enabled
        return s.to_dict()

    # ── Proxy ─────────────────────────────────────────────────

    async def change_proxy(self, sid: str, new_proxy: str) -> dict:
        """Change proxy for a session — requires browser restart."""
        s = self.sessions.get(sid)
        if not s:
            return {"success": False, "error": "Session not found"}

        target_proxy = self._resolve_proxy(new_proxy, new_proxy)
        if not target_proxy:
            return {"success": False, "error": "Wybrane proxy nie istnieje już na liście"}
        new_proxy = target_proxy.url

        old_proxy = s.proxy
        old_proxy_info = dict(s.proxy_info or {})
        s.proxy = new_proxy
        s.proxy_info = self._proxy_info_from_entry(target_proxy)

        # Restart browser with new proxy
        browser = self.browsers.get(sid)
        if browser and browser.alive:
            log.info(f"[PROXY] Restarting browser {sid} with new proxy: {new_proxy[:60]}")
            # Close old browser
            try:
                await browser.close()
            except Exception:
                pass

            # Create new browser with same session data but new proxy
            new_browser = BrowserSession(
                session_id=sid,
                email=s.email,
                password=s.password,
                proxy=new_proxy,
                display_env=self.vnc_manager.get_launch_env(sid) if self.vnc_manager and s.mode == "vnc" else None,
                force_plain_selenium=bool(self.vnc_manager and s.mode == "vnc"),
            )
            new_browser.recover_url = getattr(browser, 'recover_url', None) or "https://mbasic.facebook.com/recover/code/"

            result = await new_browser.launch()
            if result.get("success"):
                self.browsers[sid] = new_browser
                s.email_logged_in = result.get("email_logged_in", False)
                proxy_info = new_browser._proxy_info
                s.proxy_info = proxy_info or s.proxy_info
                return {
                    "success": True,
                    "session": s.to_dict(),
                    "proxy_info": proxy_info,
                    "email_logged_in": result.get("email_logged_in", False),
                    "restarted": True,
                }
            else:
                # Relaunch failed — restore old proxy, session is crashed
                s.proxy = old_proxy
                s.proxy_info = old_proxy_info
                s.status = "crashed"
                self.browsers.pop(sid, None)
                return {
                    "success": False,
                    "error": f"Restart z nowym proxy nie powiodł się: {result.get('error', '?')}",
                    "crashed": True,
                }

        return {"success": True, "session": s.to_dict(), "restarted": False}

    def _resolve_proxy(self, requested_proxy: str = "", fallback_proxy: str = ""):
        pm = self.proxy_manager
        if not pm:
            return None
        for candidate in (requested_proxy, fallback_proxy):
            if not candidate:
                continue
            proxy = self._find_proxy(candidate)
            if proxy:
                return proxy
        return pm.get_next()

    def _find_proxy(self, proxy_str: str):
        pm = self.proxy_manager
        if not pm or not proxy_str:
            return None
        for proxy in pm.proxies:
            if proxy.url == proxy_str or f"{proxy.address}:{proxy.port}" == proxy_str:
                return proxy
        return None

    @staticmethod
    def _proxy_info_from_entry(proxy_entry) -> dict:
        if not proxy_entry:
            return {}
        return {
            "address": proxy_entry.address,
            "port": proxy_entry.port,
            "url": proxy_entry.url,
            "username": proxy_entry.username,
            "ip": proxy_entry.external_ip or "",
            "country": proxy_entry.country or "",
            "country_code": proxy_entry.country_code or "",
            "city": proxy_entry.city or "",
            "latency_ms": proxy_entry.latency_ms or 0,
        }

    # ── Manual actions (simulated placeholders, future: via Selenium) ──

    def perform_delete_posts(self, sid: str) -> Optional[dict]:
        s = self.sessions.get(sid)
        if not s:
            return None
        deleted = random.randint(1, 8)
        s.posts_deleted += deleted
        return {"deleted": deleted, "total": s.posts_deleted}

    def perform_delete_stories(self, sid: str) -> Optional[dict]:
        s = self.sessions.get(sid)
        if not s:
            return None
        deleted = random.randint(0, 3)
        s.stories_deleted += deleted
        return {"deleted": deleted, "total": s.stories_deleted}

    def perform_disconnect_connections(self, sid: str) -> Optional[dict]:
        s = self.sessions.get(sid)
        if not s:
            return None
        disconnected = random.randint(1, 5)
        s.connections_disconnected += disconnected
        return {"disconnected": disconnected, "total": s.connections_disconnected}
