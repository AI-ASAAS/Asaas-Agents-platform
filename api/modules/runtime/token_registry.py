import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from modules.llm.schemas import UsageInfo


@dataclass
class RunContext:
    run_id: str
    token: str
    provider: str
    model: str
    visitor_key: str
    max_output_tokens: int
    created_at: float
    expires_at: float
    session_id: str | None = None
    is_active: bool = True
    requests_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_estimated_cost_usd: float = 0.0
    last_limits: dict[str, Any] | None = None

    def is_expired(self, now: float | None = None) -> bool:
        return (now or time.time()) > self.expires_at


class RunTokenRegistry:
    """
    In-memory registry managing short-lived ephemeral run tokens for agents.
    - Maps token -> {run_id, provider, model, visitor_key, max_output_tokens, expires_at}.
    - The agent child process / service receives ONLY this run token, NEVER the real visitor key.
    - Enforces provider & model: an agent cannot switch to unauthorized models.
    - Enforces hard TTL expiry and accumulates token usage and costs across all LLM calls in the run.
    - Revoked immediately when the run ends (completed, cancelled, timed out, or abandoned).
    """

    def __init__(self) -> None:
        self._tokens: dict[str, RunContext] = {}
        self._run_to_token: dict[str, str] = {}
        self._finalized_usage: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def create_token(
        self,
        run_id: str,
        provider: str,
        model: str,
        visitor_key: str,
        max_output_tokens: int = 2000,
        ttl_seconds: float = 300.0,
        session_id: str | None = None,
    ) -> str:
        async with self._lock:
            token = f"art_{secrets.token_urlsafe(24)}"
            now = time.time()
            ctx = RunContext(
                run_id=run_id,
                token=token,
                provider=provider,
                model=model,
                visitor_key=visitor_key,
                max_output_tokens=max_output_tokens,
                created_at=now,
                expires_at=now + ttl_seconds,
                session_id=session_id,
                is_active=True,
            )
            self._tokens[token] = ctx
            self._run_to_token[run_id] = token
            return token

    async def get_context(self, token: str) -> RunContext | None:
        async with self._lock:
            ctx = self._tokens.get(token)
            if not ctx:
                return None
            if not ctx.is_active or ctx.is_expired():
                self._snapshot_usage_unlocked(ctx)
                ctx.is_active = False
                self._tokens.pop(token, None)
                self._run_to_token.pop(ctx.run_id, None)
                return None
            return ctx

    def _snapshot_usage_unlocked(self, ctx: RunContext) -> None:
        """Persist non-sensitive usage counters before discarding visitor_key."""
        self._finalized_usage[ctx.run_id] = {
            "provider": ctx.provider,
            "model": ctx.model,
            "requests": ctx.requests_count,
            "input_tokens": ctx.total_input_tokens,
            "output_tokens": ctx.total_output_tokens,
            "estimated_cost_usd": round(ctx.total_estimated_cost_usd, 6),
            "last_limits": ctx.last_limits,
        }

    async def record_usage(self, run_id: str, usage: UsageInfo | None) -> None:
        if not usage:
            return
        async with self._lock:
            token = self._run_to_token.get(run_id)
            if not token:
                return
            ctx = self._tokens.get(token)
            if not ctx:
                return
            ctx.requests_count += usage.requests or 1
            if usage.input_tokens:
                ctx.total_input_tokens += usage.input_tokens
            if usage.output_tokens:
                ctx.total_output_tokens += usage.output_tokens
            if usage.estimated_cost_usd:
                ctx.total_estimated_cost_usd += usage.estimated_cost_usd
            if usage.limits:
                ctx.last_limits = usage.limits.model_dump()

    async def get_accumulated_usage(self, run_id: str) -> UsageInfo:
        async with self._lock:
            token = self._run_to_token.get(run_id)
            if token and token in self._tokens:
                ctx = self._tokens[token]
                return UsageInfo(
                    provider=ctx.provider,
                    model=ctx.model,
                    requests=ctx.requests_count,
                    input_tokens=ctx.total_input_tokens if ctx.total_input_tokens > 0 else None,
                    output_tokens=ctx.total_output_tokens if ctx.total_output_tokens > 0 else None,
                    estimated_cost_usd=round(ctx.total_estimated_cost_usd, 6) if ctx.total_estimated_cost_usd > 0 else None,
                    source="estimated" if ctx.provider == "gemini" else "provider",
                )
            snap = self._finalized_usage.get(run_id)
            if snap:
                return UsageInfo(
                    provider=snap["provider"],
                    model=snap["model"],
                    requests=snap["requests"],
                    input_tokens=snap["input_tokens"] or None,
                    output_tokens=snap["output_tokens"] or None,
                    estimated_cost_usd=snap["estimated_cost_usd"] or None,
                    source="estimated" if snap["provider"] == "gemini" else "provider",
                )
            return UsageInfo(provider="unknown", model="unknown", requests=0)

    async def get_runs_usage_aggregate(self, run_ids: set[str], provider: str, model: str) -> dict[str, Any]:
        """Aggregate total requests, tokens, and estimated cost across a session's runs."""
        async with self._lock:
            total_reqs = 0
            total_in = 0
            total_out = 0
            total_cost = 0.0
            last_limits = None

            for rid in run_ids:
                token = self._run_to_token.get(rid)
                if token and token in self._tokens:
                    ctx = self._tokens[token]
                    total_reqs += ctx.requests_count
                    total_in += ctx.total_input_tokens
                    total_out += ctx.total_output_tokens
                    total_cost += ctx.total_estimated_cost_usd
                    if ctx.last_limits:
                        last_limits = ctx.last_limits
                elif rid in self._finalized_usage:
                    snap = self._finalized_usage[rid]
                    total_reqs += snap["requests"]
                    total_in += snap["input_tokens"]
                    total_out += snap["output_tokens"]
                    total_cost += snap["estimated_cost_usd"]
                    if snap.get("last_limits"):
                        last_limits = snap["last_limits"]

            return {
                "provider": provider,
                "model": model,
                "requests": total_reqs,
                "input_tokens": total_in,
                "output_tokens": total_out,
                "estimated_cost_usd": round(total_cost, 6),
                "limits": last_limits,
                "source": "estimated" if provider == "gemini" else ("provider" if last_limits else "estimated"),
            }

    async def revoke_token(self, token: str) -> None:
        async with self._lock:
            ctx = self._tokens.get(token)
            if ctx:
                self._snapshot_usage_unlocked(ctx)
                ctx.is_active = False
                self._tokens.pop(token, None)
                self._run_to_token.pop(ctx.run_id, None)

    async def revoke_by_run_id(self, run_id: str) -> None:
        async with self._lock:
            token = self._run_to_token.pop(run_id, None)
            if token and token in self._tokens:
                ctx = self._tokens.pop(token)
                self._snapshot_usage_unlocked(ctx)
                ctx.is_active = False

    async def revoke_token_for_run(self, run_id: str) -> None:
        await self.revoke_by_run_id(run_id)

    async def forget_finalized_usage(self, run_ids: set[str]) -> None:
        async with self._lock:
            for rid in run_ids:
                self._finalized_usage.pop(rid, None)

    async def cleanup_expired(self) -> int:
        async with self._lock:
            now = time.time()
            removed = 0
            for tok, ctx in list(self._tokens.items()):
                if ctx.is_expired(now):
                    self._snapshot_usage_unlocked(ctx)
                    ctx.is_active = False
                    self._tokens.pop(tok, None)
                    self._run_to_token.pop(ctx.run_id, None)
                    removed += 1
            return removed


# Global singleton registry
run_token_registry = RunTokenRegistry()
