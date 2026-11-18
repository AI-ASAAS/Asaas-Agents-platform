import datetime
import time
from collections import defaultdict
from fastapi import Request
from config import settings
from modules.llm.errors import RateLimitedError
from utils.client_ip import extract_client_ip


class SecurityRateLimiter:
    """
    In-memory rate limiter enforcing multi-tier abuse protection:
    1. Key Validation limit per IP (sliding window 60s)
    2. Connection Test limit per IP (sliding window 60s)
    3. Run Starts limit per IP (sliding window 60s)
    4. Daily Run Cap per IP (resetting at midnight UTC)
    All limits tune after one week of real use.
    """

    def __init__(self) -> None:
        self._validate_history: dict[str, list[float]] = defaultdict(list)
        self._test_history: dict[str, list[float]] = defaultdict(list)
        self._run_start_history: dict[str, list[float]] = defaultdict(list)
        # Daily runs: { "YYYY-MM-DD": { client_ip: count } }
        self._daily_runs: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def _get_today_key(self) -> str:
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    def _check_sliding_window(
        self,
        ip: str,
        history_map: dict[str, list[float]],
        max_requests: int,
        window_seconds: int = 60,
        operation_name: str = "الطلب",
    ) -> None:
        now = time.time()
        window_start = now - window_seconds
        timestamps = [t for t in history_map[ip] if t > window_start]

        if len(timestamps) >= max_requests:
            oldest = timestamps[0]
            retry_after = max(1.0, round((oldest + window_seconds) - now, 1))
            raise RateLimitedError(
                message_ar=f"تم تجاوز الحد المسموح به لعمليات {operation_name} من هذا العنوان. يرجى الانتظار {int(retry_after)} ثانية.",
                message_en=f"Rate limit exceeded for {operation_name}. Please retry after {int(retry_after)}s.",
                retry_after_seconds=retry_after,
                scope=f"ip_{operation_name}",
            )

        timestamps.append(now)
        history_map[ip] = timestamps

    def check_key_validation(self, request: Request) -> None:
        client_ip = extract_client_ip(request)
        self._check_sliding_window(
            ip=client_ip,
            history_map=self._validate_history,
            max_requests=settings.rate_limit_validate_key_per_min,
            window_seconds=60,
            operation_name="التحقق من المفتاح",
        )

    def check_connection_test(self, request: Request) -> None:
        client_ip = extract_client_ip(request)
        self._check_sliding_window(
            ip=client_ip,
            history_map=self._test_history,
            max_requests=settings.rate_limit_test_connection_per_min,
            window_seconds=60,
            operation_name="اختبار الاتصال",
        )

    def check_run_start(self, request: Request) -> None:
        client_ip = extract_client_ip(request)
        # 1. Per-minute limit
        self._check_sliding_window(
            ip=client_ip,
            history_map=self._run_start_history,
            max_requests=settings.rate_limit_run_starts_per_min,
            window_seconds=60,
            operation_name="بدء التجربة",
        )

        # 2. Daily cap per IP
        today = self._get_today_key()
        current_daily = self._daily_runs[today][client_ip]
        if current_daily >= settings.rate_limit_daily_runs_per_ip:
            # Calculate seconds until midnight UTC
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            midnight = (now_utc + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            retry_after = max(60.0, (midnight - now_utc).total_seconds())
            raise RateLimitedError(
                message_ar="تم تجاوز الحد اليومي الأقصى للتجارب المسموح بها من هذا العنوان. تفضل بزيارتنا غداً.",
                message_en="Daily run limit exceeded for this IP. Please return tomorrow.",
                retry_after_seconds=retry_after,
                scope="daily_runs_cap",
            )

    def record_run_started(self, client_ip: str) -> None:
        today = self._get_today_key()
        self._daily_runs[today][client_ip] += 1

    def reset(self) -> None:
        self._validate_history.clear()
        self._test_history.clear()
        self._run_start_history.clear()
        self._daily_runs.clear()


security_limiter = SecurityRateLimiter()
