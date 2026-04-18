"""Rate limiter — per-IP request throttling"""

import time
from collections import defaultdict
from server.config import RATE_LIMIT_WINDOW, RATE_LIMIT_MAX


class RateLimiter:
    def __init__(
        self, window: int = RATE_LIMIT_WINDOW, max_requests: int = RATE_LIMIT_MAX
    ):
        self._window = window
        self._max = max_requests
        self._hits: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, ip: str) -> bool:
        now = time.time()
        cutoff = now - self._window
        self._hits[ip] = [t for t in self._hits[ip] if t > cutoff]
        if len(self._hits[ip]) >= self._max:
            return False
        self._hits[ip].append(now)
        return True
