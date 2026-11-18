import time
from collections import defaultdict
from fastapi import Request
from config import settings
from modules.llm.errors import RateLimitedError


class IPRateLimiter:
    """In-memory sliding-window rate limiter per client IP address."""

    def __init__(self, max_requests: int = 20, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._history: dict[str, list[float]] = defaultdict(list)

    def check(self, request: Request) -> None:
        client_ip = request.client.host if request.client else "127.0.0.1"
        now = time.time()
        window_start = now - self.window_seconds

        # Prune old timestamps
        timestamps = [t for t in self._history[client_ip] if t > window_start]
        if len(timestamps) >= self.max_requests:
            oldest = timestamps[0]
            retry_after = max(1.0, round((oldest + self.window_seconds) - now, 1))
            raise RateLimitedError(
                message_ar="تم تجاوز الحد المسموح به لطلبات الفحص من هذا العنوان. يرجى الانتظار.",
                message_en="Rate limit exceeded for verification requests from this IP.",
                retry_after_seconds=retry_after,
                scope="ip_rate_limit",
            )

        timestamps.append(now)
        self._history[client_ip] = timestamps

    def reset(self) -> None:
        self._history.clear()


ip_limiter = IPRateLimiter(
    max_requests=settings.ip_rate_limit_max_requests,
    window_seconds=settings.ip_rate_limit_window_seconds,
)
