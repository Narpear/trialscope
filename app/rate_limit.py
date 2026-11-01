import time
from collections import defaultdict, deque

from starlette.requests import Request

MAX_TRACKED_CLIENTS = 10_000


def client_ip(request: Request, trusted_proxy_hops: int) -> str:
    """Client address, read from X-Forwarded-For only as far as trusted proxies vouch for it."""
    peer = request.client.host if request.client else "unknown"
    if trusted_proxy_hops <= 0:
        return peer
    forwarded = [
        host.strip()
        for header in request.headers.getlist("x-forwarded-for")
        for host in header.split(",")
        if host.strip()
    ]
    if len(forwarded) < trusted_proxy_hops:
        return peer
    return forwarded[-trusted_proxy_hops]


class InMemoryRateLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self.requests: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        if len(self.requests) > MAX_TRACKED_CLIENTS:
            self._forget_idle(now)
        history = self.requests[key]
        while history and now - history[0] >= self.window_seconds:
            history.popleft()
        if len(history) >= self.limit:
            return False
        history.append(now)
        return True

    def _forget_idle(self, now: float) -> None:
        for key in [k for k, h in self.requests.items() if not h or now - h[-1] >= self.window_seconds]:
            del self.requests[key]
