import os
import threading
import time
from collections import defaultdict


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        cutoff = now - self.window_seconds
        with self._lock:
            hits = [t for t in self._hits[key] if t > cutoff]
            if len(hits) >= self.max_requests:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True


def client_ip(request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def build_rate_limiter() -> RateLimiter | None:
    max_requests = int(os.environ.get("TSELIVESCORE_RATE_LIMIT", "120"))
    window_seconds = int(os.environ.get("TSELIVESCORE_RATE_WINDOW", "60"))
    if max_requests <= 0:
        return None
    return RateLimiter(max_requests, window_seconds)
