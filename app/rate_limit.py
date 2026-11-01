import time
from collections import defaultdict, deque


class InMemoryRateLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self.requests: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        history = self.requests[key]
        while history and now - history[0] >= self.window_seconds:
            history.popleft()
        if len(history) >= self.limit:
            return False
        history.append(now)
        return True
