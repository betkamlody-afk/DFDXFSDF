# -*- coding: utf-8 -*-
"""Stealth fingerprint manager — UA rotation, header profiles, timing jitter, TLS impersonation.

Provides consistent browser fingerprints per-session so that all requests
from a single "user" look like the same browser, while different sessions
get different fingerprints.
"""

import random
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, List

log = logging.getLogger("fb_panel.stealth")

# ---------------------------------------------------------------------------
# curl_cffi availability (TLS fingerprint impersonation)
# ---------------------------------------------------------------------------
try:
    from curl_cffi.requests import Session as CffiSession
    CFFI_AVAILABLE = True
except ImportError:
    CFFI_AVAILABLE = False
    log.warning("[STEALTH] curl_cffi not installed -- TLS fingerprint rotation disabled")


# ---------------------------------------------------------------------------
# Browser profiles — realistic Chrome/Firefox/Edge on Win/Mac/Linux
# ---------------------------------------------------------------------------
_CHROME_VERSIONS = [
    ("130", "130.0.0.0"),
    ("131", "131.0.0.0"),
    ("132", "132.0.0.0"),
    ("133", "133.0.0.0"),
    ("134", "134.0.0.0"),
    ("135", "135.0.0.0"),
]

_PLATFORMS = [
    # (UA platform, Sec-Ch-Ua-Platform, sec-ch-ua-mobile)
    ("Windows NT 10.0; Win64; x64", '"Windows"', "?0"),
    ("Macintosh; Intel Mac OS X 10_15_7", '"macOS"', "?0"),
    ("X11; Linux x86_64", '"Linux"', "?0"),
]

_ACCEPT_LANGUAGES = [
    "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "pl-PL,pl;q=0.9,en;q=0.8",
    "pl,en-US;q=0.9,en;q=0.8",
    "en-US,en;q=0.9,pl;q=0.8",
    "en-US,en;q=0.9",
]

# curl_cffi impersonation targets — rotated per session
_CFFI_IMPERSONATE = [
    "chrome130", "chrome131", "chrome133",
    "chrome134", "chrome135",
    "edge130", "edge131",
]


@dataclass
class BrowserProfile:
    """Single consistent browser identity for one checker session."""
    chrome_ver: str = ""
    chrome_full: str = ""
    platform_ua: str = ""
    platform_sec: str = ""
    mobile: str = "?0"
    accept_lang: str = ""
    cffi_target: str = ""
    _created: float = field(default_factory=time.time)

    @property
    def user_agent(self) -> str:
        return (
            f"Mozilla/5.0 ({self.platform_ua}) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{self.chrome_full} Safari/537.36"
        )

    @property
    def sec_ch_ua(self) -> str:
        return (
            f'"Chromium";v="{self.chrome_ver}", '
            f'"Google Chrome";v="{self.chrome_ver}", '
            f'"Not-A.Brand";v="99"'
        )

    def base_headers(self, *, is_navigate: bool = False, referer: str = None,
                     origin: str = None, content_type: str = None) -> Dict[str, str]:
        """Build full header dict matching a real Chrome browser."""
        h: Dict[str, str] = {}

        h["User-Agent"] = self.user_agent
        h["Accept-Language"] = self.accept_lang
        h["Accept-Encoding"] = "gzip, deflate, br, zstd"

        # Sec-Ch-Ua family
        h["Sec-Ch-Ua"] = self.sec_ch_ua
        h["Sec-Ch-Ua-Mobile"] = self.mobile
        h["Sec-Ch-Ua-Platform"] = self.platform_sec

        if is_navigate:
            h["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
            h["Sec-Fetch-Dest"] = "document"
            h["Sec-Fetch-Mode"] = "navigate"
            h["Sec-Fetch-Site"] = "none" if not referer else "same-origin"
            h["Sec-Fetch-User"] = "?1"
            h["Upgrade-Insecure-Requests"] = "1"
        else:
            # XHR/form POST
            h["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            h["Sec-Fetch-Dest"] = "document"
            h["Sec-Fetch-Mode"] = "navigate"
            h["Sec-Fetch-Site"] = "same-origin"

        if origin:
            h["Origin"] = origin
        if referer:
            h["Referer"] = referer
        if content_type:
            h["Content-Type"] = content_type

        h["DNT"] = "1"
        h["Connection"] = "keep-alive"
        return h


def generate_profile() -> BrowserProfile:
    """Create a new random but internally-consistent browser profile."""
    ver, full = random.choice(_CHROME_VERSIONS)
    plat_ua, plat_sec, mobile = random.choice(_PLATFORMS)
    lang = random.choice(_ACCEPT_LANGUAGES)
    cffi = random.choice(_CFFI_IMPERSONATE) if CFFI_AVAILABLE else ""

    profile = BrowserProfile(
        chrome_ver=ver,
        chrome_full=full,
        platform_ua=plat_ua,
        platform_sec=plat_sec,
        mobile=mobile,
        accept_lang=lang,
        cffi_target=cffi,
    )
    log.debug(f"[STEALTH] New profile: Chrome/{full} on {plat_ua[:20]}... lang={lang[:10]}")
    return profile


# ---------------------------------------------------------------------------
# Session factory — creates requests session with TLS impersonation + proxy
# ---------------------------------------------------------------------------
def create_stealth_session(profile: BrowserProfile, proxy_url: Optional[str] = None):
    """Create an HTTP session with TLS fingerprint impersonation.

    Returns curl_cffi Session if available, else stdlib requests.Session.
    Both support .get(), .post(), .headers, .cookies, .proxies.
    """
    # Fix DNS leak: socks5:// -> socks5h:// (resolve DNS on proxy side)
    if proxy_url:
        proxy_url = _fix_dns_leak(proxy_url)

    if CFFI_AVAILABLE and profile.cffi_target:
        sess = CffiSession(impersonate=profile.cffi_target)
        if proxy_url:
            sess.proxies = {"http": proxy_url, "https": proxy_url}
        sess.headers.update(profile.base_headers(is_navigate=True))
        return sess

    # Fallback: stdlib requests
    import requests
    sess = requests.Session()
    if proxy_url:
        sess.proxies = {"http": proxy_url, "https": proxy_url}
    sess.headers.update(profile.base_headers(is_navigate=True))
    return sess


def _fix_dns_leak(proxy_url: str) -> str:
    """Convert socks5:// to socks5h:// to prevent local DNS resolution."""
    if proxy_url.startswith("socks5://"):
        return "socks5h://" + proxy_url[9:]
    if proxy_url.startswith("socks4://"):
        return "socks4a://" + proxy_url[9:]
    return proxy_url


# ---------------------------------------------------------------------------
# Timing jitter — human-like delays
# ---------------------------------------------------------------------------
def jitter(min_s: float = 0.8, max_s: float = 2.5) -> None:
    """Sleep for a random duration to simulate human timing."""
    delay = random.uniform(min_s, max_s)
    time.sleep(delay)


def jitter_short() -> None:
    """Short jitter for between-field actions (0.3-1.0s)."""
    jitter(0.3, 1.0)


def jitter_page() -> None:
    """Page load jitter — user reading the page (1.5-4.0s)."""
    jitter(1.5, 4.0)


def jitter_typing(text_len: int = 10) -> None:
    """Simulate typing delay based on text length (~80-150ms per char)."""
    per_char = random.uniform(0.08, 0.15)
    time.sleep(per_char * text_len)
