import asyncio
import logging
import shutil
import time
from pathlib import Path

import httpx

from config import settings
from modules.runtime.runner import cleanup_stale_run_dirs
from modules.runtime.service_supervisor import site_dna_supervisor
from modules.runtime.session_limiter import service_session_limiter
from modules.runtime.session_store import service_session_store
from modules.runtime.token_registry import run_token_registry

logger = logging.getLogger("runtime.janitor")


def _dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


class DataJanitor:
    """
    Background janitor enforcing Decision S6:
    - Purges expired in-memory sessions, cancels any still-active runs for them, revokes tokens, and deletes their run dirs.
    - Purges finished run directories 60 minutes after completion (configurable via settings.service_run_retention_minutes).
    - Enforces per-session (150 MB) and global (1 GB) disk quotas by evicting oldest finished runs.
    - Sweeps expired run tokens and stale Tier-1 job directories.
    """

    def __init__(
        self,
        retention_minutes: int | None = None,
        check_interval_seconds: float = 300.0,  # 5 minutes
    ) -> None:
        self._retention_override = retention_minutes
        self.check_interval_seconds = check_interval_seconds
        self._task: asyncio.Task | None = None
        self._running: bool = False

    @property
    def retention_seconds(self) -> float:
        mins = self._retention_override if self._retention_override is not None else settings.service_run_retention_minutes
        return float(mins) * 60.0

    def _get_site_dna_runs_dir(self) -> Path:
        return site_dna_supervisor.resolve_data_dir()

    async def _cancel_and_purge_run(self, session_id: str, run_id: str, runs_dir: Path) -> bool:
        await run_token_registry.revoke_token_for_run(run_id)
        await service_session_limiter.release_run_slot(session_id, run_id)

        # Best-effort cancel on Site DNA daemon if running
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                await client.post(f"{site_dna_supervisor.base_url}/api/v1/runs/{run_id}/cancel")
        except Exception:
            pass

        run_path = runs_dir / run_id
        if run_path.exists() and run_path.is_dir():
            shutil.rmtree(run_path, ignore_errors=True)
            return True
        return False

    async def enforce_disk_quotas(self, runs_dir: Path) -> int:
        """Evicts oldest run directories when total size exceeds settings.service_disk_quota_global_mb."""
        if not runs_dir.exists():
            return 0
        global_cap_bytes = settings.service_disk_quota_global_mb * 1024 * 1024
        dirs: list[tuple[float, int, Path]] = []
        total_bytes = 0

        for d in runs_dir.iterdir():
            if not d.is_dir():
                continue
            try:
                sz = _dir_size_bytes(d)
                mtime = d.stat().st_mtime
                dirs.append((mtime, sz, d))
                total_bytes += sz
            except OSError:
                continue

        if total_bytes <= global_cap_bytes:
            return 0

        # Evict oldest directories first until under quota
        dirs.sort(key=lambda item: item[0])
        evicted = 0
        for _, sz, d in dirs:
            if total_bytes <= global_cap_bytes:
                break
            shutil.rmtree(d, ignore_errors=True)
            total_bytes -= sz
            evicted += 1
            logger.info("Janitor evicted run directory %s (%d bytes) to enforce global disk quota", d.name, sz)
        return evicted

    async def check_session_disk_quota(self, session_id: str) -> tuple[bool, int]:
        """Returns (within_quota, current_bytes) for a visitor session."""
        runs_dir = self._get_site_dna_runs_dir()
        owned = await service_session_store.get_owned_runs(session_id)
        used = sum(_dir_size_bytes(runs_dir / rid) for rid in owned)
        cap = settings.service_disk_quota_session_mb * 1024 * 1024
        return (used < cap, used)

    async def check_global_disk_quota(self) -> tuple[bool, int]:
        """Returns (within_quota, current_bytes) across all Site DNA run directories."""
        runs_dir = self._get_site_dna_runs_dir()
        used = _dir_size_bytes(runs_dir)
        cap = settings.service_disk_quota_global_mb * 1024 * 1024
        return (used < cap, used)

    async def run_cleanup_pass(self) -> dict[str, int]:
        stats = {
            "expired_sessions": 0,
            "revoked_tokens": 0,
            "purged_directories": 0,
            "quota_evictions": 0,
        }
        runs_dir = self._get_site_dna_runs_dir()

        # 1. Cleanup expired in-memory sessions -> cancel runs, revoke tokens, purge dirs
        try:
            expired = await service_session_store.cleanup_expired()
            stats["expired_sessions"] = len(expired)
            for session_id, runs in expired:
                for run_id in runs:
                    purged = await self._cancel_and_purge_run(session_id, run_id, runs_dir)
                    stats["revoked_tokens"] += 1
                    if purged:
                        stats["purged_directories"] += 1
                await run_token_registry.forget_finalized_usage(runs)
        except Exception as e:
            logger.error("Error during expired session cleanup: %s", e)

        # 2. Cleanup finished runs past 60-minute retention window
        try:
            due_runs = await service_session_store.get_finished_runs_past_retention(self.retention_seconds)
            for session_id, run_id in due_runs:
                purged = await self._cancel_and_purge_run(session_id, run_id, runs_dir)
                await service_session_store.remove_run_record(session_id, run_id)
                if purged:
                    stats["purged_directories"] += 1
                    logger.info("Janitor purged finished run %s past retention window", run_id)
        except Exception as e:
            logger.error("Error during finished run retention cleanup: %s", e)

        # 3. Sweep orphaned directories on disk older than retention window
        try:
            if runs_dir.exists():
                now = time.time()
                for d in runs_dir.iterdir():
                    if not d.is_dir():
                        continue
                    try:
                        age = now - d.stat().st_mtime
                        if age > self.retention_seconds:
                            shutil.rmtree(d, ignore_errors=True)
                            stats["purged_directories"] += 1
                            logger.info("Janitor purged stale on-disk run dir: %s", d.name)
                    except OSError:
                        pass
        except Exception as e:
            logger.error("Error during stale runs dir sweep: %s", e)

        # 4. Enforce global disk quota
        try:
            stats["quota_evictions"] = await self.enforce_disk_quotas(runs_dir)
        except Exception as e:
            logger.error("Error enforcing disk quota: %s", e)

        # 5. Cleanup expired tokens and stale Tier-1 job temp directories
        try:
            stats["revoked_tokens"] += await run_token_registry.cleanup_expired()
            stats["purged_directories"] += cleanup_stale_run_dirs()
        except Exception as e:
            logger.error("Error during token/job dir cleanup: %s", e)

        return stats

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.run_cleanup_pass()
            except Exception as e:
                logger.error("Unexpected error in Janitor loop: %s", e)
            await asyncio.sleep(self.check_interval_seconds)

    def start(self) -> None:
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._loop())
            logger.info(
                "Data Janitor started (interval: %.0fs, retention: %.0fm, global_quota: %dMB)",
                self.check_interval_seconds,
                self.retention_seconds / 60.0,
                settings.service_disk_quota_global_mb,
            )

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
            logger.info("Data Janitor stopped")


data_janitor = DataJanitor()
