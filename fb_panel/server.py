#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FB Panel — Professional Web Panel Server
Kwasny Checker Pro v2.0

Backend API server with:
- Key-based authentication
- Session management
- Proxy pool management
- Email checking queue
- Real-time WebSocket updates
- Anti-fingerprinting headers
- Rate limiting
- Request sanitization
"""

import asyncio
import json
import secrets
import string
import socket
import hashlib
import time
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Set, List, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import defaultdict
import aiohttp
from aiohttp import web, WSMsgType
import aiohttp_cors

# Import engine
try:
    from engine import CheckerEngine, EngineConfig, HAS_SELENIUM, HAS_UC
    ENGINE_AVAILABLE = HAS_SELENIUM
except ImportError:
    ENGINE_AVAILABLE = False
    CheckerEngine = None
    EngineConfig = None
    HAS_UC = False

# ══════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
KEYS_FILE = DATA_DIR / "keys.json"
LOGS_FILE = DATA_DIR / "logs.json"

# Ensure data directory exists
DATA_DIR.mkdir(exist_ok=True)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger("fb_panel")

# ══════════════════════════════════════════════════════════════
# SECURITY — Rate Limiting & Anonymity
# ══════════════════════════════════════════════════════════════

class RateLimiter:
    """IP-based rate limiting"""
    
    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, List[float]] = defaultdict(list)
    
    def is_allowed(self, ip: str) -> bool:
        """Check if IP is within rate limit"""
        now = time.time()
        cutoff = now - self.window_seconds
        
        # Clean old requests
        self.requests[ip] = [t for t in self.requests[ip] if t > cutoff]
        
        if len(self.requests[ip]) >= self.max_requests:
            return False
        
        self.requests[ip].append(now)
        return True
    
    def get_wait_time(self, ip: str) -> float:
        """Get seconds until rate limit resets"""
        if not self.requests[ip]:
            return 0
        
        oldest = min(self.requests[ip])
        wait = self.window_seconds - (time.time() - oldest)
        return max(0, wait)


# Global rate limiter
rate_limiter = RateLimiter(max_requests=100, window_seconds=60)


# Security headers for anonymity
SECURITY_HEADERS = {
    # Prevent information leakage
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'X-XSS-Protection': '1; mode=block',
    'Referrer-Policy': 'no-referrer',
    
    # Hide server info
    'Server': 'nginx',
    'X-Powered-By': '',
    
    # CSP
    'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; connect-src 'self' ws: wss:;",
    
    # Permissions
    'Permissions-Policy': 'geolocation=(), microphone=(), camera=()',
    
    # Cache control
    'Cache-Control': 'no-store, no-cache, must-revalidate',
    'Pragma': 'no-cache',
}


def get_client_ip(request: web.Request) -> str:
    """Get real client IP (handles proxies)"""
    # Check for proxy headers
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    
    real_ip = request.headers.get('X-Real-IP')
    if real_ip:
        return real_ip
    
    return request.remote or '127.0.0.1'


def sanitize_input(value: str, max_length: int = 1000) -> str:
    """Sanitize user input"""
    if not value:
        return ""
    
    # Truncate
    value = value[:max_length]
    
    # Remove control characters
    value = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', value)
    
    return value.strip()


# ══════════════════════════════════════════════════════════════
# MIDDLEWARE
# ══════════════════════════════════════════════════════════════

@web.middleware
async def security_middleware(request: web.Request, handler):
    """Add security headers and rate limiting"""
    ip = get_client_ip(request)
    
    # Rate limiting (skip for static files)
    if request.path.startswith('/api/'):
        if not rate_limiter.is_allowed(ip):
            wait_time = rate_limiter.get_wait_time(ip)
            return web.json_response({
                "success": False,
                "error": f"Rate limit exceeded. Try again in {int(wait_time)}s"
            }, status=429)
    
    # Process request
    response = await handler(request)
    
    # Add security headers
    for header, value in SECURITY_HEADERS.items():
        if value:  # Don't add empty headers
            response.headers[header] = value
    
    return response


# ══════════════════════════════════════════════════════════════
# ENUMS & DATA CLASSES
# ══════════════════════════════════════════════════════════════

class LogStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    CHECKPOINT = "checkpoint"
    INVALID = "invalid"
    TFA_REQUIRED = "2fa_required"
    ERROR = "error"


@dataclass
class LogEntry:
    """Single email:password log entry"""
    id: str
    email: str
    password: str
    status: LogStatus = LogStatus.PENDING
    code: Optional[str] = None
    proxy: Optional[str] = None
    session_id: Optional[str] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "status": self.status.value if isinstance(self.status, LogStatus) else self.status,
            "code": self.code,
            "proxy": self.proxy,
            "session_id": self.session_id,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }


@dataclass
class ProxyEntry:
    """Proxy entry with health tracking"""
    address: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    protocol: str = "socks5"
    is_available: bool = True
    is_validated: bool = False
    fail_count: int = 0
    last_used: Optional[str] = None
    
    @property
    def url(self) -> str:
        auth = f"{self.username}:{self.password}@" if self.username else ""
        return f"{self.protocol}://{auth}{self.address}:{self.port}"
    
    def to_dict(self) -> dict:
        return {
            "address": self.address,
            "port": self.port,
            "protocol": self.protocol,
            "is_available": self.is_available,
            "is_validated": self.is_validated,
            "fail_count": self.fail_count
        }


# ══════════════════════════════════════════════════════════════
# KEY MANAGER — Authentication System
# ══════════════════════════════════════════════════════════════

class KeyManager:
    """Manages authentication keys and sessions"""
    
    def __init__(self):
        self.used_keys: Set[str] = set()
        self.pending_keys: Dict[str, float] = {}  # key -> timestamp
        self.sessions: Dict[str, dict] = {}  # session_id -> session data
        self._load()
    
    def _load(self):
        """Load used keys from file"""
        if KEYS_FILE.exists():
            try:
                data = json.loads(KEYS_FILE.read_text())
                self.used_keys = set(data.get("used_keys", []))
            except Exception as e:
                log.error(f"Failed to load keys: {e}")
    
    def _save(self):
        """Save used keys to file"""
        try:
            KEYS_FILE.write_text(json.dumps({
                "used_keys": list(self.used_keys),
                "last_updated": datetime.now().isoformat()
            }, indent=2))
        except Exception as e:
            log.error(f"Failed to save keys: {e}")
    
    def generate_key(self) -> str:
        """Generate unique authorization key"""
        self.cleanup_expired()
        
        while True:
            chars = string.ascii_uppercase + string.digits
            parts = [''.join(secrets.choice(chars) for _ in range(4)) for _ in range(4)]
            key = '-'.join(parts)
            
            if key not in self.used_keys and key not in self.pending_keys:
                self.pending_keys[key] = time.time()
                log.info(f"Generated key: {key}")
                return key
    
    def validate_key(self, key: str) -> tuple[bool, str, Optional[str]]:
        """
        Validate authorization key
        Returns: (is_valid, message, session_id)
        """
        key = key.strip().upper()
        
        if key in self.used_keys:
            return (False, "Klucz już został wykorzystany!", None)
        
        if key not in self.pending_keys:
            return (False, "Nieprawidłowy klucz!", None)
        
        # Check expiration (5 minutes)
        if time.time() - self.pending_keys[key] > 300:
            del self.pending_keys[key]
            return (False, "Klucz wygasł! Wygeneruj nowy.", None)
        
        # Valid — mark as used
        del self.pending_keys[key]
        self.used_keys.add(key)
        self._save()
        
        # Create session
        session_id = secrets.token_hex(32)
        self.sessions[session_id] = {
            "key": key,
            "created_at": datetime.now().isoformat(),
            "ip": None
        }
        
        log.info(f"Key validated: {key[:9]}...")
        return (True, "Autoryzacja pomyślna!", session_id)
    
    def is_session_valid(self, session_id: str) -> bool:
        """Check if session is valid"""
        return session_id in self.sessions
    
    def cleanup_expired(self):
        """Remove expired pending keys"""
        now = time.time()
        expired = [k for k, t in self.pending_keys.items() if now - t > 300]
        for k in expired:
            del self.pending_keys[k]
    
    def logout(self, session_id: str):
        """End session"""
        if session_id in self.sessions:
            del self.sessions[session_id]


# ══════════════════════════════════════════════════════════════
# PROXY MANAGER — Auto-detect format, validation, rotation
# ══════════════════════════════════════════════════════════════

class ProxyManager:
    """Manages proxy pool with auto-format detection and validation"""
    
    # Protocol map
    PROTOCOL_MAP = {
        "SOCKS5": "socks5",
        "SOCKS4": "socks4",
        "HTTP": "http",
    }
    
    def __init__(self):
        self.proxies: List[ProxyEntry] = []
        self._current_index = 0
        self._proxy_type = "SOCKS5"
    
    def load_from_lines(self, lines: List[str], proxy_type: str = "SOCKS5") -> int:
        """
        Load proxies from raw lines.
        Backend auto-detects which combination of host:port:user:pass was used.
        proxy_type: SOCKS5, SOCKS4, or HTTP (selected by user in UI)
        """
        self.proxies.clear()
        self._current_index = 0
        self._proxy_type = proxy_type
        protocol = self.PROTOCOL_MAP.get(proxy_type, "socks5")
        loaded = 0
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                proxy = self._auto_detect_format(line, protocol)
                if proxy:
                    self.proxies.append(proxy)
                    loaded += 1
            except Exception as e:
                log.warning(f"Invalid proxy: {line[:40]} — {e}")
        
        log.info(f"Loaded {loaded} proxies [{proxy_type}]")
        return loaded
    
    def _auto_detect_format(self, line: str, protocol: str) -> Optional[ProxyEntry]:
        """
        Auto-detect proxy format from line.
        Supported formats:
         - host:port
         - host:port:user:pass
         - host:port:pass:user
         - user:pass@host:port
         - host:port@user:pass
        The backend determines which parts are host/port/user/pass
        by analyzing the structure.
        """
        line = line.strip()
        
        # ── Format: user:pass@host:port ──
        if '@' in line:
            left, right = line.split('@', 1)
            
            # Check which side has the host (contains port number)
            left_parts = left.split(':')
            right_parts = right.split(':')
            
            # user:pass@host:port
            if len(right_parts) == 2 and self._is_port(right_parts[1]):
                return ProxyEntry(
                    address=right_parts[0],
                    port=int(right_parts[1]),
                    username=left_parts[0] if left_parts else None,
                    password=left_parts[1] if len(left_parts) > 1 else None,
                    protocol=protocol
                )
            
            # host:port@user:pass
            if len(left_parts) == 2 and self._is_port(left_parts[1]):
                return ProxyEntry(
                    address=left_parts[0],
                    port=int(left_parts[1]),
                    username=right_parts[0] if right_parts else None,
                    password=right_parts[1] if len(right_parts) > 1 else None,
                    protocol=protocol
                )
        
        parts = line.split(':')
        
        # ── Format: host:port ──
        if len(parts) == 2:
            return ProxyEntry(
                address=parts[0],
                port=int(parts[1]),
                protocol=protocol
            )
        
        # ── 3 parts — host:port:pass or port embedded elsewhere ──
        if len(parts) == 3:
            # host:port:pass
            if self._is_port(parts[1]):
                return ProxyEntry(
                    address=parts[0],
                    port=int(parts[1]),
                    password=parts[2],
                    protocol=protocol
                )
        
        # ── 4 parts — detect order ──
        if len(parts) == 4:
            # Try host:port:user:pass
            if self._is_port(parts[1]):
                return ProxyEntry(
                    address=parts[0],
                    port=int(parts[1]),
                    username=parts[2],
                    password=parts[3],
                    protocol=protocol
                )
            # Try user:pass:host:port
            if self._is_port(parts[3]):
                return ProxyEntry(
                    address=parts[2],
                    port=int(parts[3]),
                    username=parts[0],
                    password=parts[1],
                    protocol=protocol
                )
        
        # ── 5+ parts — try to find the port ──
        if len(parts) >= 5:
            for i, p in enumerate(parts):
                if self._is_port(p):
                    host = parts[i-1] if i > 0 else parts[0]
                    port = int(p)
                    remaining = [parts[j] for j in range(len(parts)) if j != i and j != i-1]
                    user = remaining[0] if remaining else None
                    passwd = remaining[1] if len(remaining) > 1 else None
                    return ProxyEntry(address=host, port=port, username=user, password=passwd, protocol=protocol)
        
        return None
    
    @staticmethod
    def _is_port(value: str) -> bool:
        """Check if string looks like a port number"""
        try:
            port = int(value)
            return 1 <= port <= 65535
        except (ValueError, TypeError):
            return False
    
    async def validate_all(self, broadcast_fn=None) -> dict:
        """
        Validate all proxies by connecting to them.
        Reports progress via broadcast_fn.
        """
        import aiohttp as _aiohttp
        
        total = len(self.proxies)
        validated = 0
        
        for i, proxy in enumerate(self.proxies):
            alive = await self._check_proxy_alive(proxy)
            proxy.is_validated = alive
            proxy.is_available = alive
            if alive:
                validated += 1
            
            if broadcast_fn:
                pct = int(((i + 1) / total) * 100) if total else 100
                await broadcast_fn("proxy_validation_progress", {
                    "current": i + 1,
                    "total": total,
                    "percent": pct,
                    "validated": validated
                })
        
        if broadcast_fn:
            await broadcast_fn("proxy_validation_done", {
                "total": total,
                "validated": validated,
                "available": validated,
                "failed": total - validated
            })
        
        log.info(f"Proxy validation: {validated}/{total} alive")
        return {"total": total, "validated": validated}
    
    async def _check_proxy_alive(self, proxy: ProxyEntry) -> bool:
        """Check if proxy is alive by connecting through it"""
        import aiohttp as _aiohttp
        
        proxy_url = proxy.url
        test_url = "http://httpbin.org/ip"
        
        try:
            connector = None
            if proxy.protocol in ("socks5", "socks4"):
                try:
                    from aiohttp_socks import ProxyConnector
                    connector = ProxyConnector.from_url(proxy_url)
                except ImportError:
                    # Fall back to basic TCP connect test
                    return await self._tcp_connect_test(proxy.address, proxy.port)
            
            timeout = _aiohttp.ClientTimeout(total=10)
            
            if connector:
                async with _aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                    async with session.get(test_url) as resp:
                        return resp.status == 200
            else:
                async with _aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(test_url, proxy=proxy_url) as resp:
                        return resp.status == 200
        except Exception:
            return False
    
    async def _tcp_connect_test(self, host: str, port: int) -> bool:
        """Fallback: test TCP connect to proxy"""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=5
            )
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False
    
    def get_next(self) -> Optional[ProxyEntry]:
        """Get next available validated proxy (round-robin)"""
        available = [p for p in self.proxies if p.is_available]
        if not available:
            return None
        self._current_index = (self._current_index + 1) % len(available)
        proxy = available[self._current_index]
        proxy.last_used = datetime.now().isoformat()
        return proxy
    
    def mark_failed(self, proxy_url: str):
        """Mark proxy as failed"""
        for p in self.proxies:
            if p.url == proxy_url:
                p.fail_count += 1
                if p.fail_count >= 3:
                    p.is_available = False
                    log.warning(f"Proxy disabled: {p.address}:{p.port}")
                break
    
    def get_stats(self) -> dict:
        """Get proxy pool statistics"""
        total = len(self.proxies)
        available = sum(1 for p in self.proxies if p.is_available)
        validated = sum(1 for p in self.proxies if p.is_validated)
        failed = sum(1 for p in self.proxies if not p.is_available)
        
        return {
            "total": total,
            "available": available,
            "validated": validated,
            "failed": failed,
            "proxy_type": self._proxy_type
        }
    
    def clear(self):
        """Clear all proxies"""
        self.proxies.clear()
        self._current_index = 0


# ══════════════════════════════════════════════════════════════
# LOGS MANAGER — Email Queue Management
# ══════════════════════════════════════════════════════════════

class LogsManager:
    """Manages email:password logs queue"""
    
    def __init__(self):
        self.logs: Dict[str, LogEntry] = {}
        self._load()
    
    def _load(self):
        """Load logs from file"""
        if LOGS_FILE.exists():
            try:
                data = json.loads(LOGS_FILE.read_text())
                for item in data.get("logs", []):
                    entry = LogEntry(
                        id=item["id"],
                        email=item["email"],
                        password=item.get("password", ""),
                        status=LogStatus(item.get("status", "pending")),
                        code=item.get("code"),
                        proxy=item.get("proxy"),
                        session_id=item.get("session_id"),
                        error=item.get("error"),
                        created_at=item.get("created_at", ""),
                        updated_at=item.get("updated_at", "")
                    )
                    self.logs[entry.id] = entry
                log.info(f"Loaded {len(self.logs)} logs")
            except Exception as e:
                log.error(f"Failed to load logs: {e}")
    
    def _save(self):
        """Save logs to file"""
        try:
            data = {"logs": [log.to_dict() for log in self.logs.values()]}
            data["logs"] = [{**l, "password": ""} for l in data["logs"]]  # Don't save passwords
            LOGS_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.error(f"Failed to save logs: {e}")
    
    def load_logs(self, lines: List[str]) -> int:
        """
        Load logs from list of email:password strings
        """
        loaded = 0
        
        for line in lines:
            line = line.strip()
            if not line or ':' not in line:
                continue
            
            try:
                email, password = line.split(':', 1)
                email = email.strip().lower()
                password = password.strip()
                
                if not email or not password:
                    continue
                
                # Generate unique ID
                log_id = hashlib.md5(f"{email}:{time.time()}".encode()).hexdigest()[:12]
                
                entry = LogEntry(
                    id=log_id,
                    email=email,
                    password=password
                )
                self.logs[log_id] = entry
                loaded += 1
            except Exception as e:
                log.warning(f"Invalid log format: {line[:30]}... — {e}")
        
        self._save()
        log.info(f"Loaded {loaded} logs")
        return loaded
    
    def get_pending(self) -> List[LogEntry]:
        """Get all pending logs"""
        return [l for l in self.logs.values() if l.status == LogStatus.PENDING]
    
    def update_status(self, log_id: str, status: LogStatus, **kwargs):
        """Update log status"""
        if log_id in self.logs:
            entry = self.logs[log_id]
            entry.status = status
            entry.updated_at = datetime.now().isoformat()
            
            for key, value in kwargs.items():
                if hasattr(entry, key):
                    setattr(entry, key, value)
            
            self._save()
    
    def get_stats(self) -> dict:
        """Get logs statistics"""
        stats = {
            "total": len(self.logs),
            "pending": 0,
            "processing": 0,
            "success": 0,
            "checkpoint": 0,
            "invalid": 0,
            "2fa_required": 0,
            "error": 0
        }
        
        for entry in self.logs.values():
            status = entry.status.value if isinstance(entry.status, LogStatus) else entry.status
            if status in stats:
                stats[status] += 1
        
        return stats
    
    def get_all(self) -> List[dict]:
        """Get all logs as dicts"""
        return [l.to_dict() for l in self.logs.values()]
    
    def clear(self):
        """Clear all logs"""
        self.logs.clear()
        self._save()


# ══════════════════════════════════════════════════════════════
# ENGINE MANAGER — Selenium Engine Control
# ══════════════════════════════════════════════════════════════

class EngineManager:
    """Controls the Selenium checking engine"""
    
    WORKER_OS_OPTIONS = ["Linux", "Windows 10", "Windows 11", "MacOS"]
    
    def __init__(self, proxy_manager: ProxyManager, logs_manager: LogsManager):
        self.proxy_manager = proxy_manager
        self.logs_manager = logs_manager
        self.is_running = False
        self.concurrency = 3
        self.active_sessions: Dict[str, dict] = {}
        self.workers: List[dict] = []
        self.anti_connect: bool = True
        self._worker_id_counter = 0
        self._task: Optional[asyncio.Task] = None
        self._ws_clients: Set[web.WebSocketResponse] = set()
    
    def add_ws_client(self, ws: web.WebSocketResponse):
        """Add WebSocket client for real-time updates"""
        self._ws_clients.add(ws)
    
    def remove_ws_client(self, ws: web.WebSocketResponse):
        """Remove WebSocket client"""
        self._ws_clients.discard(ws)
    
    async def broadcast(self, event: str, data: dict):
        """Broadcast event to all WebSocket clients"""
        message = json.dumps({"event": event, "data": data})
        
        for ws in list(self._ws_clients):
            try:
                await ws.send_str(message)
            except Exception:
                self._ws_clients.discard(ws)
    
    async def start(self, concurrency: int = 3):
        """Start the checking engine"""
        if self.is_running:
            return {"success": False, "error": "Engine already running"}
        
        self.concurrency = concurrency
        self.is_running = True
        
        # Start engine task
        self._task = asyncio.create_task(self._run_engine())
        
        log.info(f"Engine started with concurrency={concurrency}")
        await self.broadcast("engine_started", {"concurrency": concurrency})
        
        return {"success": True}
    
    async def stop(self):
        """Stop the checking engine"""
        if not self.is_running:
            return {"success": False, "error": "Engine not running"}
        
        self.is_running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        log.info("Engine stopped")
        await self.broadcast("engine_stopped", {})
        
        return {"success": True}
    
    async def _run_engine(self):
        """Main engine loop"""
        try:
            while self.is_running:
                pending = self.logs_manager.get_pending()
                
                if not pending:
                    await asyncio.sleep(2)
                    continue
                
                # Process in batches
                batch = pending[:self.concurrency]
                tasks = [self._process_log(entry) for entry in batch]
                await asyncio.gather(*tasks, return_exceptions=True)
                
                await asyncio.sleep(1)
        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error(f"Engine error: {e}")
            self.is_running = False
    
    def _create_worker(self, entry: LogEntry) -> dict:
        """Create a worker with random OS"""
        import random
        self._worker_id_counter += 1
        worker = {
            "id": self._worker_id_counter,
            "email": entry.email,
            "os": random.choice(self.WORKER_OS_OPTIONS),
            "proxy": "",
            "status": "idle",
            "log_id": entry.id
        }
        self.workers.append(worker)
        return worker
    
    def _remove_worker(self, worker_id: int):
        """Remove worker from active list"""
        self.workers = [w for w in self.workers if w["id"] != worker_id]
    
    async def _process_log(self, entry: LogEntry):
        """Process single log entry with worker tracking"""
        worker = self._create_worker(entry)
        await self.broadcast("worker_update", worker)
        
        # Get proxy
        proxy = self.proxy_manager.get_next()
        if proxy:
            entry.proxy = f"{proxy.address}:{proxy.port}"
            worker["proxy"] = entry.proxy
            worker["status"] = "validating_proxy"
            await self.broadcast("worker_update", worker)

            # Anti-connect: validate proxy before connecting
            if self.anti_connect:
                alive = await self.proxy_manager._check_proxy_alive(proxy)
                if not alive:
                    self.proxy_manager.mark_failed(proxy.url)
                    # Try next proxy
                    proxy = self.proxy_manager.get_next()
                    if proxy:
                        entry.proxy = f"{proxy.address}:{proxy.port}"
                        worker["proxy"] = entry.proxy
                    else:
                        self.logs_manager.update_status(entry.id, LogStatus.ERROR, error="No available proxy")
                        worker["status"] = "done"
                        await self.broadcast("worker_update", worker)
                        await self.broadcast("log_updated", self.logs_manager.logs[entry.id].to_dict())
                        self._remove_worker(worker["id"])
                        return
        
        # Update status to processing
        worker["status"] = "processing"
        await self.broadcast("worker_update", worker)
        self.logs_manager.update_status(entry.id, LogStatus.PROCESSING)
        await self.broadcast("log_updated", entry.to_dict())
        
        # TODO: Implement actual Selenium logic in engine.py
        # For now, simulate processing
        import random
        await asyncio.sleep(random.uniform(2, 5))
        
        # Simulate random result
        results = [
            (LogStatus.SUCCESS, {"code": f"{random.randint(10000000, 99999999)}"}),
            (LogStatus.CHECKPOINT, {}),
            (LogStatus.INVALID, {}),
            (LogStatus.ERROR, {"error": "Connection timeout"})
        ]
        status, extra = random.choice(results)
        
        extra["worker_os"] = worker["os"]
        self.logs_manager.update_status(entry.id, status, **extra)
        await self.broadcast("log_updated", self.logs_manager.logs[entry.id].to_dict())
        
        # Clean up worker
        worker["status"] = "done"
        await self.broadcast("worker_update", worker)
        self._remove_worker(worker["id"])
    
    def get_status(self) -> dict:
        """Get engine status"""
        return {
            "running": self.is_running,
            "concurrency": self.concurrency,
            "active_sessions": len(self.active_sessions),
            "ws_clients": len(self._ws_clients)
        }
    
    def get_workers(self) -> List[dict]:
        """Get active workers list"""
        return [w for w in self.workers if w["status"] != "done"]


# ══════════════════════════════════════════════════════════════
# WEB SERVER — API Routes
# ══════════════════════════════════════════════════════════════

# Global managers
key_manager = KeyManager()
proxy_manager = ProxyManager()
logs_manager = LogsManager()
engine_manager = EngineManager(proxy_manager, logs_manager)

# Terminal callback for key display
terminal_callback = None

def set_terminal_callback(callback):
    global terminal_callback
    terminal_callback = callback


# ═══════════════ AUTH ROUTES ═══════════════

async def handle_generate_key(request: web.Request) -> web.Response:
    """POST /api/generate-key — Generate new auth key"""
    key = key_manager.generate_key()
    
    if terminal_callback:
        try:
            terminal_callback(key)
        except Exception:
            pass
    else:
        log.info(f"🔑 NEW KEY: {key}")
    
    return web.json_response({
        "success": True,
        "message": "Klucz wygenerowany!",
        "key": key
    })


async def handle_authorize(request: web.Request) -> web.Response:
    """POST /api/authorize — Validate auth key"""
    try:
        data = await request.json()
        key = data.get("key", "")
    except Exception:
        return web.json_response({
            "success": False,
            "message": "Nieprawidłowe dane!"
        }, status=400)
    
    is_valid, message, session_id = key_manager.validate_key(key)
    
    if is_valid:
        response = web.json_response({
            "success": True,
            "message": message,
            "session_id": session_id
        })
        response.set_cookie("session_id", session_id, httponly=True, max_age=86400)
        return response
    
    return web.json_response({
        "success": False,
        "message": message
    })


async def handle_check_session(request: web.Request) -> web.Response:
    """GET /api/check-session — Check if session is valid"""
    session_id = request.cookies.get("session_id", "")
    
    if key_manager.is_session_valid(session_id):
        return web.json_response({
            "authorized": True,
            "session_id": session_id
        })
    
    return web.json_response({"authorized": False})


async def handle_logout(request: web.Request) -> web.Response:
    """POST /api/logout — End session"""
    session_id = request.cookies.get("session_id", "")
    key_manager.logout(session_id)
    
    response = web.json_response({"success": True})
    response.del_cookie("session_id")
    return response


# ═══════════════ PROXY ROUTES ═══════════════

async def handle_load_proxy(request: web.Request) -> web.Response:
    """POST /api/proxy/load — Load proxies from raw lines + type"""
    try:
        data = await request.json()
        lines = data.get("lines", [])
        proxy_type = data.get("proxy_type", "SOCKS5")
        if proxy_type not in ("SOCKS5", "SOCKS4", "HTTP"):
            proxy_type = "SOCKS5"
    except Exception:
        return web.json_response({"success": False, "error": "Invalid data"}, status=400)
    
    loaded = proxy_manager.load_from_lines(lines, proxy_type)
    
    return web.json_response({
        "success": True,
        "loaded": loaded
    })


async def handle_validate_proxy(request: web.Request) -> web.Response:
    """POST /api/proxy/validate — Validate all loaded proxies"""
    if not proxy_manager.proxies:
        return web.json_response({"success": False, "error": "No proxies loaded"}, status=400)
    
    # Run validation in background
    async def _validate():
        await proxy_manager.validate_all(broadcast_fn=engine_manager.broadcast)
    
    asyncio.create_task(_validate())
    return web.json_response({"success": True, "message": "Validation started"})


async def handle_clear_proxy(request: web.Request) -> web.Response:
    """POST /api/proxy/clear — Clear all proxies"""
    proxy_manager.clear()
    return web.json_response({"success": True})


async def handle_proxy_stats(request: web.Request) -> web.Response:
    """GET /api/proxy/stats — Get proxy statistics"""
    stats = proxy_manager.get_stats()
    return web.json_response({"success": True, **stats})


# ═══════════════ LOGS ROUTES ═══════════════

async def handle_load_logs(request: web.Request) -> web.Response:
    """POST /api/logs/load — Load logs from raw lines"""
    try:
        data = await request.json()
        lines = data.get("lines", data.get("logs", []))
    except Exception:
        return web.json_response({"success": False, "error": "Invalid data"}, status=400)
    
    loaded = logs_manager.load_logs(lines)
    
    return web.json_response({
        "success": True,
        "loaded": loaded
    })


async def handle_clear_logs(request: web.Request) -> web.Response:
    """POST /api/logs/clear — Clear all logs"""
    logs_manager.clear()
    return web.json_response({"success": True})


async def handle_logs_stats(request: web.Request) -> web.Response:
    """GET /api/logs/stats — Get logs statistics"""
    stats = logs_manager.get_stats()
    return web.json_response({"success": True, **stats})


async def handle_logs_all(request: web.Request) -> web.Response:
    """GET /api/logs/all — Get all logs"""
    logs = logs_manager.get_all()
    return web.json_response({"success": True, "logs": logs})


# ═══════════════ ENGINE ROUTES ═══════════════

async def handle_engine_start(request: web.Request) -> web.Response:
    """POST /api/engine/start — Start engine"""
    try:
        data = await request.json()
        concurrency = data.get("concurrency", 3)
    except Exception:
        concurrency = 3
    
    result = await engine_manager.start(concurrency)
    return web.json_response(result)


async def handle_engine_stop(request: web.Request) -> web.Response:
    """POST /api/engine/stop — Stop engine"""
    result = await engine_manager.stop()
    return web.json_response(result)


async def handle_engine_status(request: web.Request) -> web.Response:
    """GET /api/engine/status — Get engine status"""
    status = engine_manager.get_status()
    return web.json_response({"success": True, **status})


# ═══════════════ WORKERS ROUTES ═══════════════

async def handle_workers(request: web.Request) -> web.Response:
    """GET /api/workers — Get active workers list"""
    workers = engine_manager.get_workers()
    return web.json_response({"success": True, "workers": workers})


# ═══════════════ ANTI-CONNECT ROUTES ═══════════════

async def handle_anti_connect_toggle(request: web.Request) -> web.Response:
    """POST /api/anti-connect/toggle — Toggle anti-connect"""
    try:
        data = await request.json()
        enabled = data.get("enabled", True)
    except Exception:
        enabled = True
    engine_manager.anti_connect = bool(enabled)
    return web.json_response({"success": True, "enabled": engine_manager.anti_connect})


async def handle_anti_connect_status(request: web.Request) -> web.Response:
    """GET /api/anti-connect/status — Get anti-connect status"""
    return web.json_response({"success": True, "enabled": engine_manager.anti_connect})


# ═══════════════ SYSTEM INFO ═══════════════

async def handle_system_info(request: web.Request) -> web.Response:
    """GET /api/system/info — Get system information"""
    return web.json_response({
        "success": True,
        "version": "2.0.0",
        "codename": "ULTRA STEALTH",
        "engine_available": ENGINE_AVAILABLE,
        "features": {
            "selenium": ENGINE_AVAILABLE,
            "undetected_chrome": HAS_UC if ENGINE_AVAILABLE else False,
            "stealth_mode": True,
            "proxy_rotation": True,
            "rate_limiting": True,
            "security_headers": True,
        },
        "supported_providers": [
            "wp.pl", "o2.pl", "interia.pl", "onet.pl", "gmail.com"
        ]
    })


# ═══════════════ WEBSOCKET ═══════════════

async def handle_websocket(request: web.Request) -> web.WebSocketResponse:
    """WebSocket endpoint for real-time updates"""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    engine_manager.add_ws_client(ws)
    log.info("WebSocket client connected")
    
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                # Handle incoming messages if needed
                pass
            elif msg.type == WSMsgType.ERROR:
                log.error(f"WebSocket error: {ws.exception()}")
    finally:
        engine_manager.remove_ws_client(ws)
        log.info("WebSocket client disconnected")
    
    return ws


# ═══════════════ STATIC FILES ═══════════════

async def handle_index(request: web.Request) -> web.Response:
    """Serve index.html"""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return web.FileResponse(index_file)
    return web.Response(text="Index not found", status=404)


async def handle_static(request: web.Request) -> web.Response:
    """Serve static files"""
    filename = request.match_info.get('filename', '')
    file_path = STATIC_DIR / filename
    
    if file_path.exists() and file_path.is_file():
        return web.FileResponse(file_path)
    return web.Response(text="File not found", status=404)


# ══════════════════════════════════════════════════════════════
# APPLICATION FACTORY
# ══════════════════════════════════════════════════════════════

def create_app() -> web.Application:
    """Create and configure the aiohttp application"""
    app = web.Application(middlewares=[security_middleware])
    
    # CORS setup
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
            allow_methods=["GET", "POST", "OPTIONS"]
        )
    })
    
    # Routes
    routes = [
        # Auth
        web.post('/api/generate-key', handle_generate_key),
        web.post('/api/authorize', handle_authorize),
        web.get('/api/check-session', handle_check_session),
        web.post('/api/logout', handle_logout),
        
        # Proxy
        web.post('/api/proxy/load', handle_load_proxy),
        web.post('/api/proxy/validate', handle_validate_proxy),
        web.post('/api/proxy/clear', handle_clear_proxy),
        web.get('/api/proxy/stats', handle_proxy_stats),
        
        # Logs
        web.post('/api/logs/load', handle_load_logs),
        web.post('/api/logs/clear', handle_clear_logs),
        web.get('/api/logs/stats', handle_logs_stats),
        web.get('/api/logs/all', handle_logs_all),
        
        # Engine
        web.post('/api/engine/start', handle_engine_start),
        web.post('/api/engine/stop', handle_engine_stop),
        web.get('/api/engine/status', handle_engine_status),
        
        # Workers
        web.get('/api/workers', handle_workers),
        
        # Anti-Connect
        web.post('/api/anti-connect/toggle', handle_anti_connect_toggle),
        web.get('/api/anti-connect/status', handle_anti_connect_status),
        
        # System info
        web.get('/api/system/info', handle_system_info),
        
        # WebSocket
        web.get('/ws', handle_websocket),
        
        # Static
        web.get('/', handle_index),
        web.get('/{filename}', handle_static),
    ]
    
    for route in routes:
        cors.add(app.router.add_route(route.method, route.path, route.handler))
    
    return app


# ══════════════════════════════════════════════════════════════
# SERVER STARTUP
# ══════════════════════════════════════════════════════════════

def get_local_ip() -> str:
    """Get local IP address"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def find_free_port(start: int = 8080) -> int:
    """Find available port"""
    for port in range(start, start + 100):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("0.0.0.0", port))
            s.close()
            return port
        except OSError:
            continue
    return start


async def start_server(host: str = "0.0.0.0", port: int = None) -> tuple:
    """
    Start the web server
    Returns: (url, runner)
    """
    if port is None:
        port = find_free_port()
    
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, host, port)
    await site.start()
    
    ip = get_local_ip()
    url = f"http://{ip}:{port}"
    
    log.info(f"Server started at {url}")
    
    return (url, runner)


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="FB Panel Server")
    parser.add_argument("--port", type=int, default=8080, help="Server port")
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    args = parser.parse_args()
    
    print("""
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║    ███████╗██████╗     ██████╗  █████╗ ███╗   ██╗███████╗██╗  ║
║    ██╔════╝██╔══██╗    ██╔══██╗██╔══██╗████╗  ██║██╔════╝██║  ║
║    █████╗  ██████╔╝    ██████╔╝███████║██╔██╗ ██║█████╗  ██║  ║
║    ██╔══╝  ██╔══██╗    ██╔═══╝ ██╔══██║██║╚██╗██║██╔══╝  ██║  ║
║    ██║     ██████╔╝    ██║     ██║  ██║██║ ╚████║███████╗███████╗
║    ╚═╝     ╚═════╝     ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝╚══════╝
║                                                               ║
║            KWASNY CHECKER PRO v2.0 — Web Panel                ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    async def main():
        url, runner = await start_server(args.host, args.port)
        print(f"\n🌐 Panel dostępny pod: {url}\n")
        print("Naciśnij Ctrl+C aby zatrzymać serwer.\n")
        
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await runner.cleanup()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Serwer zatrzymany.")
