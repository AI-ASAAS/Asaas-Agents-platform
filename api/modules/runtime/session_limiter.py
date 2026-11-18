import asyncio
import time
from fastapi import HTTPException, status

from config import settings


class ConcurrencyLimitError(HTTPException):
    def __init__(self, detail: str, retry_after: int = 60, status_code: int = status.HTTP_429_TOO_MANY_REQUESTS):
        super().__init__(
            status_code=status_code,
            detail=detail,
            headers={"Retry-After": str(retry_after)},
        )


class ServiceSessionLimiter:
    """
    Enforces multi-tier concurrency ceilings and abuse limits for Tier-2 Service Agents:
    - Platform-wide concurrent runs: 2 (assumption to tune)
    - Per-IP concurrent runs: 1 (assumption to tune)
    - Per-session concurrent runs: 1 (assumption to tune)
    - Per-IP daily runs: 3 per rolling 24h window (assumption to tune)
    - Per-target-origin active runs platform-wide: 1 (prevents hammering a target site)
    """

    def __init__(
        self,
        max_platform_concurrent: int | None = None,
        max_ip_concurrent: int | None = None,
        max_daily_runs: int | None = None,
    ) -> None:
        self._max_platform_override = max_platform_concurrent
        self._max_ip_override = max_ip_concurrent
        self._max_daily_override = max_daily_runs

        self._active_runs: dict[str, tuple[str, str, str]] = {}  # run_id -> (session_id, client_ip, target_origin)
        self._session_active: dict[str, set[str]] = {}
        self._ip_active: dict[str, set[str]] = {}
        self._origin_active: dict[str, str] = {}  # canonical_origin -> run_id
        self._ip_daily_history: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    @property
    def max_platform_concurrent(self) -> int:
        return self._max_platform_override if self._max_platform_override is not None else settings.service_max_concurrent_global

    @property
    def max_ip_concurrent(self) -> int:
        return self._max_ip_override if self._max_ip_override is not None else settings.service_max_concurrent_per_ip

    @property
    def max_daily_runs(self) -> int:
        return self._max_daily_override if self._max_daily_override is not None else settings.service_daily_runs_per_ip

    async def acquire_run_slot(
        self,
        session_id: str,
        run_id: str,
        client_ip: str,
        target_origin: str = "",
    ) -> None:
        async with self._lock:
            # 1. Per-session concurrent cap
            if len(self._session_active.get(session_id, set())) >= 1:
                raise ConcurrencyLimitError(
                    detail="يوجد تحليل نشط قيد التنفيذ حالياً لهذه الجلسة.",
                    retry_after=30,
                    status_code=status.HTTP_409_CONFLICT,
                )

            # 2. Per-IP concurrent cap
            if len(self._ip_active.get(client_ip, set())) >= self.max_ip_concurrent:
                raise ConcurrencyLimitError(
                    detail="يوجد تحليل نشط حالياً من عنوان اتصالك. يرجى انتظار اكتماله أولاً.",
                    retry_after=30,
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                )

            # 3. Platform-wide concurrent cap
            if len(self._active_runs) >= self.max_platform_concurrent:
                raise ConcurrencyLimitError(
                    detail="الخادم مشغول حالياً بمعالجة تحليلات أخرى (الحد الأقصى المتزامن مكتمل). يرجى المحاولة بعد قليل.",
                    retry_after=60,
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                )

            # 4. Target-origin deduplication platform-wide (max 1 active run per origin)
            norm_origin = target_origin.lower().strip()
            if norm_origin and norm_origin in self._origin_active:
                raise ConcurrencyLimitError(
                    detail="يتم تحليل هذا الموقع حالياً بالفعل. يرجى الانتظار حتى انتهاء التحليل الجاري.",
                    retry_after=60,
                    status_code=status.HTTP_409_CONFLICT,
                )

            # 5. Per-IP daily rolling 24h quota
            now = time.time()
            cutoff = now - 86400.0
            ip_runs = [t for t in self._ip_daily_history.get(client_ip, []) if t > cutoff]
            if len(ip_runs) >= self.max_daily_runs:
                oldest = ip_runs[0]
                reset_after = max(60, int(oldest + 86400.0 - now))
                raise ConcurrencyLimitError(
                    detail=f"تم استنفاد الحد اليومي للتحليلات ({self.max_daily_runs} تحليلات كل 24 ساعة).",
                    retry_after=reset_after,
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                )

            # Atomically reserve slot and record daily quota once
            self._active_runs[run_id] = (session_id, client_ip, norm_origin)
            self._session_active.setdefault(session_id, set()).add(run_id)
            self._ip_active.setdefault(client_ip, set()).add(run_id)
            if norm_origin:
                self._origin_active[norm_origin] = run_id

            ip_runs.append(now)
            self._ip_daily_history[client_ip] = ip_runs

    async def rollback_failed_start(self, run_id: str) -> None:
        """Releases slot AND refunds daily quota count if upstream start failed before launch."""
        async with self._lock:
            entry = self._active_runs.pop(run_id, None)
            if not entry:
                return
            session_id, client_ip, norm_origin = entry
            if session_id in self._session_active:
                self._session_active[session_id].discard(run_id)
                if not self._session_active[session_id]:
                    self._session_active.pop(session_id, None)
            if client_ip in self._ip_active:
                self._ip_active[client_ip].discard(run_id)
                if not self._ip_active[client_ip]:
                    self._ip_active.pop(client_ip, None)
            if norm_origin and self._origin_active.get(norm_origin) == run_id:
                self._origin_active.pop(norm_origin, None)
            # Refund the most recent daily timestamp for this IP
            hist = self._ip_daily_history.get(client_ip)
            if hist:
                hist.pop()

    async def release_run_slot(self, session_id: str, run_id: str) -> None:
        """Releases active concurrency & target-origin slots (keeps daily history intact)."""
        async with self._lock:
            entry = self._active_runs.pop(run_id, None)
            if entry:
                s_id, client_ip, norm_origin = entry
                if s_id in self._session_active:
                    self._session_active[s_id].discard(run_id)
                    if not self._session_active[s_id]:
                        self._session_active.pop(s_id, None)
                if client_ip in self._ip_active:
                    self._ip_active[client_ip].discard(run_id)
                    if not self._ip_active[client_ip]:
                        self._ip_active.pop(client_ip, None)
                if norm_origin and self._origin_active.get(norm_origin) == run_id:
                    self._origin_active.pop(norm_origin, None)
            elif session_id in self._session_active:
                self._session_active[session_id].discard(run_id)
                if not self._session_active[session_id]:
                    self._session_active.pop(session_id, None)

    async def get_active_count(self) -> int:
        async with self._lock:
            return len(self._active_runs)

    async def get_daily_remaining(self, client_ip: str) -> int:
        async with self._lock:
            now = time.time()
            cutoff = now - 86400.0
            ip_runs = [t for t in self._ip_daily_history.get(client_ip, []) if t > cutoff]
            return max(0, self.max_daily_runs - len(ip_runs))

    async def reset(self) -> None:
        async with self._lock:
            self._active_runs.clear()
            self._session_active.clear()
            self._ip_active.clear()
            self._origin_active.clear()
            self._ip_daily_history.clear()


service_session_limiter = ServiceSessionLimiter()
