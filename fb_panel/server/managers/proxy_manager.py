"""Proxy manager — pool, auto-format detection, real protocol validation, GeoIP, rotation.

Production version with:
- Concurrent validation (semaphore-limited)
- Real SOCKS5/SOCKS4/HTTP CONNECT protocol validation
- Auto-detection of REAL proxy type (tries all protocols)
- IP geolocation via ip-api.com (free, no key)
- Proxy auth support
- Latency measurement
- Failure tracking with auto-disable
- Round-robin rotation with availability filtering
"""

import asyncio
import logging
import time
import struct
import socket
import json
from typing import Optional, List, Callable
from datetime import datetime

import aiohttp

from server.models import ProxyEntry

log = logging.getLogger("fb_panel.proxy_manager")

PROTOCOL_MAP = {"SOCKS5": "socks5", "SOCKS4": "socks4", "HTTP": "http"}
VALIDATE_CONCURRENCY = 20
VALIDATE_TIMEOUT = 8
TEST_HOST = "www.facebook.com"
TEST_PORT = 443
MAX_FAILURES = 3
COOLDOWN_SECONDS = 300  # Re-enable disabled proxies after 5 minutes
GEO_BATCH = 100  # ip-api.com batch limit
GEO_CONCURRENCY = 10  # concurrent tunnel checks for rotating proxies


class ProxyManager:
    """Auto-detects proxy format, validates with real protocol tests, GeoIP, rotates."""

    def __init__(self):
        self.proxies: List[ProxyEntry] = []
        self._idx = 0
        self._proxy_type = "SOCKS5"

    # ── load from raw lines (APPENDS to existing list, dedup) ──
    def load_from_lines(self, lines: List[str], proxy_type: str = "SOCKS5") -> int:
        self._proxy_type = proxy_type
        protocol = PROTOCOL_MAP.get(proxy_type, "socks5")
        loaded = 0
        # Build dedup set — include username for rotating proxies (same host:port, different creds)
        def _dedup_key(p):
            return f"{p.address}:{p.port}:{p.username or ''}" if p.username else f"{p.address}:{p.port}"
        seen = {_dedup_key(p) for p in self.proxies}
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = self._auto_detect(line, protocol)
                if entry:
                    key = _dedup_key(entry)
                    if key not in seen:
                        seen.add(key)
                        self.proxies.append(entry)
                        loaded += 1
            except Exception as e:
                log.warning(f"Invalid proxy: {line[:40]} — {e}")
        log.info(f"Loaded {loaded} new proxies [{proxy_type}] (total: {len(self.proxies)})")
        return loaded

    # ── auto-detect format ─────────────────────────────────────
    def _auto_detect(self, raw: str, protocol: str) -> Optional[ProxyEntry]:
        raw = raw.strip()
        # Strip protocol prefix
        for prefix in ("socks5://", "socks4://", "socks4a://", "http://", "https://"):
            if raw.lower().startswith(prefix):
                detected = prefix.replace("://", "").replace("4a", "4")
                if detected in ("socks5", "socks4", "http", "https"):
                    protocol = detected if detected != "https" else "http"
                raw = raw[len(prefix):]
                break
        if "@" in raw:
            left, right = raw.split("@", 1)
            lp, rp = left.split(":"), right.split(":")
            if len(rp) >= 2 and self._is_port(rp[-1]):
                host = ":".join(rp[:-1]) if len(rp) > 2 else rp[0]
                return ProxyEntry(host, int(rp[-1]), lp[0] if lp else None, lp[1] if len(lp) > 1 else None, protocol)
            if len(lp) >= 2 and self._is_port(lp[1]):
                return ProxyEntry(lp[0], int(lp[1]), rp[0] if rp else None, rp[1] if len(rp) > 1 else None, protocol)

        parts = raw.split(":")
        if len(parts) == 2:
            return ProxyEntry(parts[0], int(parts[1]), protocol=protocol)
        if len(parts) == 3 and self._is_port(parts[1]):
            return ProxyEntry(parts[0], int(parts[1]), username=parts[2], protocol=protocol)
        if len(parts) == 4:
            if self._is_port(parts[1]):
                return ProxyEntry(parts[0], int(parts[1]), parts[2], parts[3], protocol)
            if self._is_port(parts[3]):
                return ProxyEntry(parts[2], int(parts[3]), parts[0], parts[1], protocol)
        if len(parts) >= 5:
            for i, p in enumerate(parts):
                if self._is_port(p) and i > 0:
                    host = parts[i - 1]
                    rest = [parts[j] for j in range(len(parts)) if j not in (i, i - 1)]
                    return ProxyEntry(host, int(p), rest[0] if rest else None, rest[1] if len(rest) > 1 else None, protocol)
        return None

    @staticmethod
    def _is_port(v: str) -> bool:
        try:
            return 1 <= int(v) <= 65535
        except (ValueError, TypeError):
            return False

    # ══════════════════════════════════════════════════════════
    # IP GEOLOCATION (ip-api.com free batch API)
    # ══════════════════════════════════════════════════════════

    async def lookup_geo_all(self, broadcast_fn: Callable = None):
        """Lookup geolocation for all proxies.

        For proxies with auth (rotating proxies like ProxyEmpire), we must connect
        THROUGH each proxy individually to get the real exit IP.
        For proxies without auth sharing the same host, we batch-lookup the hostname.
        """
        if not self.proxies:
            return

        # Split into two groups:
        # 1) Proxies with credentials → need individual tunnel check (rotating IPs)
        # 2) Proxies without credentials → can batch by hostname
        auth_proxies = [p for p in self.proxies if p.username]
        noauth_proxies = [p for p in self.proxies if not p.username]

        total = len(auth_proxies) + (len(set(p.address for p in noauth_proxies)) if noauth_proxies else 0)
        done = 0

        # ── Group 1: Rotating proxies (with auth) — individual tunnel check ──
        if auth_proxies:
            from server.managers.browser_session import check_proxy_connectivity
            sem = asyncio.Semaphore(GEO_CONCURRENCY)

            async def _check_one(proxy):
                nonlocal done
                async with sem:
                    try:
                        loop = asyncio.get_event_loop()
                        result = await loop.run_in_executor(None, check_proxy_connectivity, proxy.url)
                        if result.get("ok"):
                            proxy.external_ip = result.get("ip", "")
                            proxy.country = result.get("country", "")
                            proxy.city = result.get("city", "")
                            proxy.country_code = result.get("country_code", "")
                        else:
                            log.info(f"[GEO] Proxy {proxy.address}:{proxy.port} ({proxy.username[:12]}...) — {result.get('error', '?')}")
                    except Exception as e:
                        log.warning(f"[GEO] Tunnel check failed for {proxy.address}:{proxy.port}: {e}")
                    done += 1
                    if broadcast_fn:
                        await broadcast_fn("geo_progress", {"current": done, "total": total})

            await asyncio.gather(*[_check_one(p) for p in auth_proxies], return_exceptions=True)

        # ── Group 2: Static proxies (no auth) — batch hostname lookup ──
        if noauth_proxies:
            addr_to_proxies = {}
            for p in noauth_proxies:
                addr_to_proxies.setdefault(p.address, []).append(p)

            unique_addrs = list(addr_to_proxies.keys())

            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                    for i in range(0, len(unique_addrs), GEO_BATCH):
                        batch = unique_addrs[i:i + GEO_BATCH]
                        payload = [{"query": addr, "fields": "status,country,countryCode,city,query"} for addr in batch]

                        try:
                            async with session.post(
                                "http://ip-api.com/batch?fields=status,country,countryCode,city,query",
                                json=payload,
                            ) as resp:
                                if resp.status == 200:
                                    results = await resp.json()
                                    for idx, item in enumerate(results):
                                        if item.get("status") == "success":
                                            original_addr = batch[idx]
                                            resolved_ip = item.get("query", "")
                                            for proxy in addr_to_proxies.get(original_addr, []):
                                                proxy.country = item.get("country")
                                                proxy.city = item.get("city")
                                                proxy.country_code = item.get("countryCode")
                                                proxy.external_ip = resolved_ip
                        except Exception as e:
                            log.warning(f"GeoIP batch failed: {e}")

                        done += len(batch)
                        if broadcast_fn:
                            await broadcast_fn("geo_progress", {"current": done, "total": total})

                        if i + GEO_BATCH < len(unique_addrs):
                            await asyncio.sleep(1)
            except Exception as e:
                log.error(f"GeoIP batch lookup error: {e}")

        geo_count = sum(1 for p in self.proxies if p.country)
        log.info(f"GeoIP lookup: {geo_count}/{len(self.proxies)} resolved")

    # ══════════════════════════════════════════════════════════
    # REAL PROTOCOL VALIDATION + AUTO-DETECT TYPE
    # ══════════════════════════════════════════════════════════

    async def validate_all(self, broadcast_fn: Callable = None) -> dict:
        """Validate all proxies concurrently with real protocol handshakes.
        Auto-detects actual protocol type by trying SOCKS5 -> SOCKS4 -> HTTP."""
        total = len(self.proxies)
        if not total:
            return {"total": 0, "validated": 0}

        sem = asyncio.Semaphore(VALIDATE_CONCURRENCY)
        validated = 0
        done_count = 0

        async def _validate_one(proxy: ProxyEntry):
            nonlocal validated, done_count
            async with sem:
                alive, latency, detected = await self._auto_detect_protocol(proxy)
                proxy.is_validated = True
                proxy.is_available = alive
                proxy.latency_ms = latency
                if detected:
                    proxy.detected_protocol = detected
                if alive:
                    validated += 1
                done_count += 1

                if broadcast_fn:
                    pct = int((done_count / total) * 100)
                    await broadcast_fn("proxy_validation_progress", {
                        "current": done_count,
                        "total": total,
                        "percent": pct,
                        "validated": validated,
                        "proxy": proxy.to_dict(),
                    })

        tasks = [_validate_one(p) for p in self.proxies]
        await asyncio.gather(*tasks, return_exceptions=True)

        # After validation, do GeoIP lookup
        await self.lookup_geo_all(broadcast_fn)

        if broadcast_fn:
            await broadcast_fn("proxy_validation_done", {
                "total": total,
                "validated": validated,
                "available": validated,
                "failed": total - validated,
                "proxies": [p.to_dict() for p in self.proxies],
            })

        log.info(f"Proxy validation: {validated}/{total} alive")
        return {"total": total, "validated": validated}

    async def _auto_detect_protocol(self, proxy: ProxyEntry) -> tuple:
        """Try all protocols to find which one actually works.
        Returns (alive, latency_ms, detected_protocol)."""
        # Try declared protocol first
        declared = proxy.protocol.lower()
        protocols_to_try = [declared]
        # Then try the others
        for p in ["socks5", "socks4", "http"]:
            if p not in protocols_to_try:
                protocols_to_try.append(p)

        for proto in protocols_to_try:
            t0 = time.monotonic()
            try:
                if proto == "socks5":
                    ok = await asyncio.wait_for(
                        self._socks5_test(proxy.address, proxy.port, proxy.username, proxy.password),
                        timeout=VALIDATE_TIMEOUT,
                    )
                elif proto == "socks4":
                    ok = await asyncio.wait_for(
                        self._socks4_test(proxy.address, proxy.port),
                        timeout=VALIDATE_TIMEOUT,
                    )
                else:
                    ok = await asyncio.wait_for(
                        self._http_connect_test(proxy.address, proxy.port, proxy.username, proxy.password),
                        timeout=VALIDATE_TIMEOUT,
                    )
                if ok:
                    latency = round((time.monotonic() - t0) * 1000)
                    log.info(f"Proxy {proxy.address}:{proxy.port} alive as {proto.upper()} ({latency}ms)")
                    return True, latency, proto
            except (asyncio.TimeoutError, Exception):
                continue

        return False, 0, None

    async def _protocol_test(self, proxy: ProxyEntry) -> tuple:
        """Test proxy with its declared/detected protocol. Returns (alive, latency_ms)."""
        protocol = proxy.real_protocol.lower()
        t0 = time.monotonic()
        try:
            if protocol == "socks5":
                ok = await asyncio.wait_for(
                    self._socks5_test(proxy.address, proxy.port, proxy.username, proxy.password),
                    timeout=VALIDATE_TIMEOUT,
                )
            elif protocol == "socks4":
                ok = await asyncio.wait_for(
                    self._socks4_test(proxy.address, proxy.port),
                    timeout=VALIDATE_TIMEOUT,
                )
            else:
                ok = await asyncio.wait_for(
                    self._http_connect_test(proxy.address, proxy.port, proxy.username, proxy.password),
                    timeout=VALIDATE_TIMEOUT,
                )
            latency = round((time.monotonic() - t0) * 1000)
            return ok, latency if ok else 0
        except (asyncio.TimeoutError, Exception):
            return False, 0

    # ── SOCKS5 (RFC 1928) ─────────────────────────────────────
    async def _socks5_test(self, host: str, port: int, username: str = None, password: str = None) -> bool:
        reader, writer = await asyncio.open_connection(host, port)
        try:
            if username and password:
                writer.write(b'\x05\x02\x00\x02')
            else:
                writer.write(b'\x05\x01\x00')
            await writer.drain()

            resp = await reader.readexactly(2)
            if resp[0] != 0x05:
                return False

            if resp[1] == 0x02 and username and password:
                uname = username.encode('utf-8')
                passwd = password.encode('utf-8')
                writer.write(bytes([0x01, len(uname)]) + uname + bytes([len(passwd)]) + passwd)
                await writer.drain()
                auth_resp = await reader.readexactly(2)
                if auth_resp[1] != 0x00:
                    return False
            elif resp[1] == 0x02:
                return False
            elif resp[1] != 0x00:
                return False

            dest = TEST_HOST.encode('utf-8')
            writer.write(
                b'\x05\x01\x00\x03'
                + bytes([len(dest)]) + dest
                + struct.pack('!H', TEST_PORT)
            )
            await writer.drain()

            connect_resp = await reader.read(10)
            return len(connect_resp) >= 2 and connect_resp[1] == 0x00
        except Exception:
            return False
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    # ── SOCKS4/4a ──────────────────────────────────────────────
    async def _socks4_test(self, host: str, port: int) -> bool:
        reader, writer = await asyncio.open_connection(host, port)
        try:
            try:
                ip = socket.gethostbyname(TEST_HOST)
                ip_bytes = socket.inet_aton(ip)
                request = struct.pack('!BBH', 0x04, 0x01, TEST_PORT) + ip_bytes + b'\x00'
            except socket.gaierror:
                ip_bytes = b'\x00\x00\x00\x01'
                request = struct.pack('!BBH', 0x04, 0x01, TEST_PORT) + ip_bytes + b'\x00' + TEST_HOST.encode() + b'\x00'

            writer.write(request)
            await writer.drain()

            resp = await reader.readexactly(8)
            return resp[1] == 0x5A
        except Exception:
            return False
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    # ── HTTP CONNECT ───────────────────────────────────────────
    async def _http_connect_test(self, host: str, port: int, username: str = None, password: str = None) -> bool:
        reader, writer = await asyncio.open_connection(host, port)
        try:
            request = f"CONNECT {TEST_HOST}:{TEST_PORT} HTTP/1.1\r\nHost: {TEST_HOST}:{TEST_PORT}\r\n"
            if username and password:
                import base64
                creds = base64.b64encode(f"{username}:{password}".encode()).decode()
                request += f"Proxy-Authorization: Basic {creds}\r\n"
            request += "\r\n"
            writer.write(request.encode())
            await writer.drain()

            resp_line = await asyncio.wait_for(reader.readline(), timeout=5)
            return '200' in resp_line.decode('utf-8', errors='ignore')
        except Exception:
            return False
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    # ── single proxy re-check (used by anti-connect) ──────────
    async def recheck_proxy(self, proxy: ProxyEntry) -> bool:
        alive, latency = await self._protocol_test(proxy)
        proxy.is_available = alive
        proxy.latency_ms = latency
        return alive

    # ── rotation ───────────────────────────────────────────────
    def get_next(self) -> Optional[ProxyEntry]:
        # Re-enable proxies whose cooldown has expired
        now = time.time()
        for p in self.proxies:
            if not p.is_available and getattr(p, '_disabled_at', 0) and (now - p._disabled_at) >= COOLDOWN_SECONDS:
                p.is_available = True
                p.fail_count = 0
                p._disabled_at = 0
                log.info(f"Proxy re-enabled after cooldown: {p.address}:{p.port}")

        available = [p for p in self.proxies if p.is_available]
        if not available:
            return None
        proxy = available[self._idx % len(available)]
        self._idx = (self._idx + 1) % len(available)
        proxy.last_used = datetime.now().isoformat()
        return proxy

    def get_by_address(self, addr: str) -> Optional[ProxyEntry]:
        for p in self.proxies:
            if f"{p.address}:{p.port}" == addr:
                return p
        return None

    def mark_failed(self, proxy_url: str):
        for p in self.proxies:
            if p.url == proxy_url or f"{p.address}:{p.port}" == proxy_url:
                p.fail_count += 1
                if p.fail_count >= MAX_FAILURES:
                    p.is_available = False
                    p._disabled_at = time.time()
                    log.warning(f"Proxy disabled after {MAX_FAILURES} failures (cooldown {COOLDOWN_SECONDS}s): {p.address}:{p.port}")
                break

    # ── stats / clear ──────────────────────────────────────────
    def get_stats(self) -> dict:
        total = len(self.proxies)
        available = sum(1 for p in self.proxies if p.is_available)
        validated = sum(1 for p in self.proxies if p.is_validated)
        return {
            "total": total,
            "available": available,
            "validated": validated,
            "failed": validated - available if validated else 0,
            "type": self._proxy_type,
        }

    def get_all(self) -> List[dict]:
        return [p.to_dict() for p in self.proxies]

    def clear(self):
        self.proxies.clear()
        self._idx = 0
