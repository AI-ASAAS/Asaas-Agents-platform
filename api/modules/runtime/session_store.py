import asyncio
import secrets
import time
from dataclasses import dataclass, field

from config import settings


@dataclass
class ServiceSession:
    session_id: str
    provider: str
    model: str
    visitor_key: str
    client_ip: str
    created_at: float
    last_accessed: float
    sliding_ttl_seconds: float = 2700.0  # 45 minutes (assumption to tune)
    max_ttl_seconds: float = 7200.0      # 2 hours absolute cap (assumption to tune)
    runs: set[str] = field(default_factory=set)
    completed_runs: dict[str, float] = field(default_factory=dict)  # run_id -> finished_at timestamp

    def is_expired(self, now: float | None = None) -> bool:
        t = now or time.time()
        if t - self.created_at > self.max_ttl_seconds:
            return True
        if t - self.last_accessed > self.sliding_ttl_seconds:
            return True
        return False

    def touch(self, now: float | None = None) -> None:
        self.last_accessed = now or time.time()

    def get_remaining_ttl(self, now: float | None = None) -> float:
        t = now or time.time()
        sliding_remaining = max(0.0, self.sliding_ttl_seconds - (t - self.last_accessed))
        absolute_remaining = max(0.0, self.max_ttl_seconds - (t - self.created_at))
        return min(sliding_remaining, absolute_remaining)


class SessionStore:
    """
    In-memory session registry for Tier-2 Service Agents (Amendment to D1 / Decision S2).
    - Stores visitor keys and provider preferences strictly in process memory.
    - Keys are NEVER written to disk, SQLite, logs, or child process environments.
    - Maps opaque HttpOnly cookie session_id -> owned run_ids for strict tenant isolation.
    """

    COOKIE_NAME = "asaas_service_session"

    def __init__(self) -> None:
        self._sessions: dict[str, ServiceSession] = {}
        self._ip_to_sessions: dict[str, set[str]] = {}
        self._run_to_session: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        provider: str,
        model: str,
        visitor_key: str,
        client_ip: str,
        sliding_ttl: float | None = None,
        max_ttl: float | None = None,
    ) -> ServiceSession:
        async with self._lock:
            session_id = f"sss_{secrets.token_urlsafe(32)}"
            now = time.time()
            session = ServiceSession(
                session_id=session_id,
                provider=provider,
                model=model,
                visitor_key=visitor_key,
                client_ip=client_ip,
                created_at=now,
                last_accessed=now,
                sliding_ttl_seconds=sliding_ttl or float(settings.service_session_sliding_ttl_seconds),
                max_ttl_seconds=max_ttl or float(settings.service_session_max_ttl_seconds),
            )
            self._sessions[session_id] = session
            self._ip_to_sessions.setdefault(client_ip, set()).add(session_id)
            return session

    async def get_session(self, session_id: str, touch: bool = True) -> ServiceSession | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            if session.is_expired():
                self._remove_session_unlocked(session_id)
                return None
            if touch:
                session.touch()
            return session

    async def delete_session(self, session_id: str) -> set[str]:
        """Deletes session from memory and returns its owned run_ids for cleanup."""
        async with self._lock:
            session = self._sessions.get(session_id)
            owned_runs = set(session.runs) if session else set()
            self._remove_session_unlocked(session_id)
            return owned_runs

    async def associate_run(self, session_id: str, run_id: str) -> bool:
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session or session.is_expired():
                return False
            session.runs.add(run_id)
            self._run_to_session[run_id] = session_id
            session.touch()
            return True

    async def mark_run_finished(self, run_id: str) -> None:
        async with self._lock:
            session_id = self._run_to_session.get(run_id)
            if not session_id:
                return
            session = self._sessions.get(session_id)
            if session and run_id not in session.completed_runs:
                session.completed_runs[run_id] = time.time()

    async def has_run(self, session_id: str, run_id: str) -> bool:
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session or session.is_expired():
                return False
            return run_id in session.runs

    async def get_owned_runs(self, session_id: str) -> set[str]:
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session or session.is_expired():
                return set()
            return set(session.runs)

    async def get_finished_runs_past_retention(self, retention_seconds: float) -> list[tuple[str, str]]:
        """Returns list of (session_id, run_id) whose completion age exceeds retention_seconds."""
        async with self._lock:
            now = time.time()
            due: list[tuple[str, str]] = []
            for s_id, session in self._sessions.items():
                for r_id, finished_at in list(session.completed_runs.items()):
                    if now - finished_at >= retention_seconds:
                        due.append((s_id, r_id))
            return due

    async def remove_run_record(self, session_id: str, run_id: str) -> None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.runs.discard(run_id)
                session.completed_runs.pop(run_id, None)
            self._run_to_session.pop(run_id, None)

    async def cleanup_expired(self) -> list[tuple[str, set[str]]]:
        """Cleans up all expired sessions and returns list of (session_id, owned_runs)."""
        async with self._lock:
            now = time.time()
            expired: list[tuple[str, set[str]]] = []
            for s_id, s in list(self._sessions.items()):
                if s.is_expired(now):
                    expired.append((s_id, set(s.runs)))
                    self._remove_session_unlocked(s_id)
            return expired

    async def reset(self) -> None:
        """Clears all sessions (used in tests)."""
        async with self._lock:
            self._sessions.clear()
            self._ip_to_sessions.clear()
            self._run_to_session.clear()

    def _remove_session_unlocked(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session:
            for r_id in session.runs:
                self._run_to_session.pop(r_id, None)
            if session.client_ip in self._ip_to_sessions:
                self._ip_to_sessions[session.client_ip].discard(session_id)
                if not self._ip_to_sessions[session.client_ip]:
                    self._ip_to_sessions.pop(session.client_ip, None)


# Global singleton
service_session_store = SessionStore()
