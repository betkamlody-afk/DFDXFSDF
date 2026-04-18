"""Proxy data model"""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class ProxyEntry:
    address: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    protocol: str = "socks5"
    detected_protocol: Optional[str] = None  # real protocol after auto-detection
    is_available: bool = True
    is_validated: bool = False
    fail_count: int = 0
    last_used: Optional[str] = None
    latency_ms: int = 0
    country: Optional[str] = None
    city: Optional[str] = None
    country_code: Optional[str] = None
    external_ip: Optional[str] = None

    @property
    def real_protocol(self) -> str:
        return self.detected_protocol or self.protocol

    @property
    def url(self) -> str:
        """Full proxy URL with DNS-safe protocol (socks5h instead of socks5)."""
        proto = self.real_protocol
        # Use DNS-safe variants to prevent local DNS resolution
        dns_safe = {"socks5": "socks5h", "socks4": "socks4a"}
        proto = dns_safe.get(proto, proto)
        auth = f"{self.username}:{self.password}@" if self.username else ""
        return f"{proto}://{auth}{self.address}:{self.port}"

    def to_dict(self) -> dict:
        d = {
            "address": self.address,
            "port": self.port,
            "username": self.username,
            "url": self.url,
            "protocol": self.protocol,
            "detected_protocol": self.detected_protocol,
            "real_protocol": self.real_protocol,
            "is_available": self.is_available,
            "is_validated": self.is_validated,
            "fail_count": self.fail_count,
            "latency_ms": self.latency_ms,
            "country": self.country,
            "city": self.city,
            "country_code": self.country_code,
            "external_ip": self.external_ip,
        }
        return d
