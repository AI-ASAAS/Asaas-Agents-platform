import asyncio
import logging
from collections import defaultdict

from config import settings

logger = logging.getLogger("runs.concurrency")


class ConcurrencyManager:
    """
    Manages in-memory concurrency caps (global and per-IP) and active run cancellation.
    Zero persistence: all state exists only in RAM during the lifecycle of the run.
    """

    def __init__(self) -> None:
        self._global_count = 0
        self._ip_counts: dict[str, int] = defaultdict(int)
        self._active_cancel_events: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, ip: str) -> bool:
        async with self._lock:
            if self._global_count >= settings.max_concurrent_runs_global:
                logger.warning("Global concurrent run cap reached (%d)", self._global_count)
                return False
            if self._ip_counts[ip] >= settings.max_concurrent_runs_per_ip:
                logger.warning("Per-IP concurrent run cap reached for IP %s (%d)", ip, self._ip_counts[ip])
                return False

            self._global_count += 1
            self._ip_counts[ip] += 1
            return True

    async def release(self, ip: str) -> None:
        async with self._lock:
            if self._global_count > 0:
                self._global_count -= 1
            if self._ip_counts[ip] > 0:
                self._ip_counts[ip] -= 1
                if self._ip_counts[ip] == 0:
                    self._ip_counts.pop(ip, None)

    async def register_run(self, run_id: str, cancel_event: asyncio.Event) -> None:
        async with self._lock:
            self._active_cancel_events[run_id] = cancel_event

    async def cancel_run(self, run_id: str) -> bool:
        async with self._lock:
            event = self._active_cancel_events.get(run_id)
            if event:
                event.set()
                return True
            return False

    async def unregister_run(self, run_id: str) -> None:
        async with self._lock:
            self._active_cancel_events.pop(run_id, None)


concurrency_manager = ConcurrencyManager()
