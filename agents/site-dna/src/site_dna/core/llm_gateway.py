"""Unified per-run OpenAI-compatible LLM gateway client for ASAAS Platform Mode.

Replaces direct provider SDK calls when running as a managed platform service.
Uses a per-run ``contextvars.ContextVar`` so concurrent runs never share or
clobber tokens, endpoints, models, or cancellation flags.
"""

from __future__ import annotations

import base64
import contextvars
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger("site_dna.core.llm_gateway")


# ---------------------------------------------------------------------------
# Per-run LLM Context (thread- and task-safe via contextvars)
# ---------------------------------------------------------------------------

@dataclass
class RunLLMContext:
    """Ephemeral per-run gateway credentials and metadata.

    Never persisted to disk, logs, or process environment variables.
    """

    run_id: str
    run_token: str
    llm_endpoint: str
    model: Optional[str] = None
    provider: Optional[str] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def normalized_endpoint(self) -> str:
        base = self.llm_endpoint.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        return base

    def __repr__(self) -> str:
        return (
            f"RunLLMContext(run_id={self.run_id!r}, llm_endpoint={self.llm_endpoint!r}, "
            f"model={self.model!r}, provider={self.provider!r}, run_token=[REDACTED])"
        )


_current_run_llm_ctx: contextvars.ContextVar[Optional[RunLLMContext]] = contextvars.ContextVar(
    "site_dna_run_llm_ctx",
    default=None,
)


def set_run_llm_context(ctx: Optional[RunLLMContext]) -> contextvars.Token:
    """Bind a per-run LLM context to the current asyncio task / thread."""
    return _current_run_llm_ctx.set(ctx)


def reset_run_llm_context(token: contextvars.Token) -> None:
    """Restore previous LLM context."""
    _current_run_llm_ctx.reset(token)


def get_current_run_llm_context() -> Optional[RunLLMContext]:
    """Return the active RunLLMContext for this execution context, if any."""
    return _current_run_llm_ctx.get()


def is_platform_llm_active(settings: Any = None) -> bool:
    """Return True when LLM calls should route through the platform local gateway."""
    if get_current_run_llm_context() is not None:
        return True
    if settings is not None and getattr(settings, "site_dna_service_mode", False):
        return True
    if os.environ.get("SITE_DNA_SERVICE_MODE", "").lower() in ("1", "true", "yes"):
        return True
    if os.environ.get("PLATFORM_MANAGED_SERVICE", "").lower() in ("1", "true", "yes"):
        return True
    return False


# ---------------------------------------------------------------------------
# Normalized Gateway Exceptions
# ---------------------------------------------------------------------------

class LLMGatewayError(Exception):
    """Base error raised by PlatformLLMGateway."""

    code: str = "provider_unavailable"

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        status_code: Optional[int] = None,
        retry_after: Optional[float] = None,
    ):
        super().__init__(message)
        if code:
            self.code = code
        self.status_code = status_code
        self.retry_after = retry_after


class LLMInvalidKeyError(LLMGatewayError):
    code = "invalid_key"


class LLMRateLimitError(LLMGatewayError):
    code = "rate_limited"


class LLMQuotaExhaustedError(LLMGatewayError):
    code = "quota_exhausted"


class LLMModelNotFoundError(LLMGatewayError):
    code = "model_not_found"


class LLMUnsupportedFeatureError(LLMGatewayError):
    code = "unsupported_feature"


class LLMProviderUnavailableError(LLMGatewayError):
    code = "provider_unavailable"


class LLMTimeoutError(LLMGatewayError):
    code = "timeout"


class LLMRunCancelledError(LLMGatewayError):
    code = "run_cancelled"


# Backwards-compatible aliases
LLMError = LLMGatewayError
LLMAuthenticationError = LLMInvalidKeyError


# ---------------------------------------------------------------------------
# Gateway Client
# ---------------------------------------------------------------------------

class PlatformLLMGateway:
    """OpenAI-compatible HTTP client targeting the ASAAS local runtime gateway."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        run_token: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 90.0,
        max_retries: int = 1,
        settings: Any = None,
        cancel_event: Optional[threading.Event] = None,
    ):
        ctx = get_current_run_llm_context()

        resolved_base = (
            base_url
            or (ctx.normalized_endpoint() if ctx else None)
            or (getattr(settings, "platform_llm_base_url", None) if settings else None)
            or os.environ.get("PLATFORM_LLM_BASE_URL")
            or "http://127.0.0.1:8000/v1"
        )
        resolved_base = resolved_base.rstrip("/")
        if not resolved_base.endswith("/v1"):
            resolved_base = f"{resolved_base}/v1"

        self.base_url = resolved_base
        self.run_token = run_token or (ctx.run_token if ctx else None)
        self.default_model = model or (ctx.model if ctx else None)
        self.timeout = timeout
        self.max_retries = max(0, min(max_retries, 1))
        self.cancel_event = cancel_event or (ctx.cancel_event if ctx else None)

    def _check_cancelled(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise LLMRunCancelledError("Analysis run was cancelled before LLM call completed.")

    def _build_headers(self) -> dict[str, str]:
        if not self.run_token:
            raise LLMInvalidKeyError(
                "Missing per-run gateway token (X-Run-Token).",
                status_code=401,
            )
        return {
            "Authorization": f"Bearer {self.run_token}",
            "Content-Type": "application/json",
        }

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        # Platform gateway enforces the visitor's chosen model regardless of what
        # model name is sent here, but we still pass the visitor's model when known.
        effective_model = self.default_model or model or "platform-default"
        payload: dict[str, Any] = {
            "model": effective_model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format is not None:
            payload["response_format"] = response_format
        return payload

    def _parse_error(self, resp: httpx.Response) -> LLMGatewayError:
        status = resp.status_code
        retry_after: Optional[float] = None
        ra_hdr = resp.headers.get("retry-after") or resp.headers.get("Retry-After")
        if ra_hdr:
            try:
                retry_after = float(ra_hdr)
            except ValueError:
                retry_after = None

        code = ""
        message = ""
        try:
            body = resp.json()
            err = body.get("error", body) if isinstance(body, dict) else {}
            if isinstance(err, dict):
                code = str(err.get("code") or err.get("type") or "").lower()
                message = str(err.get("message") or body.get("detail") or "")
                if retry_after is None and err.get("retry_after_seconds") is not None:
                    try:
                        retry_after = float(err["retry_after_seconds"])
                    except (TypeError, ValueError):
                        pass
            else:
                message = str(body)[:240]
        except Exception:
            message = (resp.text or "")[:240]

        safe_msg = message[:240] or f"Gateway returned HTTP {status}"

        if status in (401, 403) or code == "invalid_key":
            return LLMInvalidKeyError(safe_msg, status_code=status)

        if status == 404 or code == "model_not_found":
            return LLMModelNotFoundError(safe_msg, status_code=status)

        if status == 429 or code in ("rate_limited", "quota_exhausted"):
            lower = f"{code} {safe_msg}".lower()
            if code == "quota_exhausted" or "quota" in lower or "per day" in lower or "rpd" in lower:
                return LLMQuotaExhaustedError(safe_msg, status_code=429, retry_after=retry_after)
            return LLMRateLimitError(safe_msg, status_code=429, retry_after=retry_after)

        if status in (400, 422) or code in ("unsupported_feature", "bad_request"):
            return LLMUnsupportedFeatureError(safe_msg, code=code or "unsupported_feature", status_code=status)

        if status in (408, 504):
            return LLMTimeoutError(safe_msg, status_code=status)

        return LLMProviderUnavailableError(safe_msg, status_code=status)

    @staticmethod
    def _build_multimodal_messages(
        prompt: str,
        images: Optional[list[Any]] = None,
        system_instruction: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})

        if images:
            content_parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for img in images:
                if isinstance(img, dict):
                    raw_bytes = img.get("data") or img.get("image_bytes")
                    mime = img.get("mime_type", "image/png")
                else:
                    raw_bytes = getattr(img, "image_bytes", None)
                    mime = getattr(img, "mime_type", "image/png")
                if not raw_bytes:
                    continue
                b64 = base64.b64encode(raw_bytes).decode("ascii")
                content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    }
                )
            messages.append({"role": "user", "content": content_parts})
        else:
            messages.append({"role": "user", "content": prompt})
        return messages

    @staticmethod
    def _extract_content_text(data: dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if not choices:
            return ""
        msg = choices[0].get("message") or {}
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for p in content:
                if isinstance(p, dict) and p.get("type") == "text":
                    parts.append(str(p.get("text", "")))
                elif isinstance(p, str):
                    parts.append(p)
            return "\n".join(parts)
        return str(content)

    # ------------------------------------------------------------------
    # Synchronous execution (used by sync multimodal/content/SEO adapters)
    # ------------------------------------------------------------------

    def chat_completion_sync(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        self._check_cancelled()
        url = f"{self.base_url}/chat/completions"
        headers = self._build_headers()
        payload = self._build_payload(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )

        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            self._check_cancelled()
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(url, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                last_exc = LLMTimeoutError(f"Gateway request timed out: {type(exc).__name__}", status_code=504)
                if attempt < self.max_retries:
                    time.sleep(1.0)
                    continue
                raise last_exc from exc
            except httpx.RequestError as exc:
                last_exc = LLMProviderUnavailableError(f"Gateway transport error: {type(exc).__name__}")
                if attempt < self.max_retries:
                    time.sleep(1.0)
                    continue
                raise last_exc from exc

            if resp.status_code == 200:
                return resp.json()

            err = self._parse_error(resp)
            # Never retry 400/401/403/404/422/429
            if resp.status_code < 500:
                raise err

            last_exc = err
            if attempt < self.max_retries:
                time.sleep(1.0)
                continue
            raise err

        raise last_exc or LLMProviderUnavailableError("Gateway request failed")

    def generate_multimodal_content_sync(
        self,
        prompt: str,
        *,
        images: Optional[list[Any]] = None,
        system_instruction: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
        json_mode: bool = True,
    ) -> tuple[str, float]:
        t0 = time.perf_counter()
        messages = self._build_multimodal_messages(prompt, images=images, system_instruction=system_instruction)
        resp_fmt = {"type": "json_object"} if json_mode else None
        data = self.chat_completion_sync(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_output_tokens,
            response_format=resp_fmt,
        )
        duration_ms = (time.perf_counter() - t0) * 1000.0
        return self._extract_content_text(data), duration_ms

    # ------------------------------------------------------------------
    # Asynchronous execution
    # ------------------------------------------------------------------

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        import asyncio

        self._check_cancelled()
        url = f"{self.base_url}/chat/completions"
        headers = self._build_headers()
        payload = self._build_payload(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )

        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            self._check_cancelled()
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                last_exc = LLMTimeoutError(f"Gateway request timed out: {type(exc).__name__}", status_code=504)
                if attempt < self.max_retries:
                    await asyncio.sleep(1.0)
                    continue
                raise last_exc from exc
            except httpx.RequestError as exc:
                last_exc = LLMProviderUnavailableError(f"Gateway transport error: {type(exc).__name__}")
                if attempt < self.max_retries:
                    await asyncio.sleep(1.0)
                    continue
                raise last_exc from exc

            if resp.status_code == 200:
                return resp.json()

            err = self._parse_error(resp)
            if resp.status_code < 500:
                raise err

            last_exc = err
            if attempt < self.max_retries:
                await asyncio.sleep(1.0)
                continue
            raise err

        raise last_exc or LLMProviderUnavailableError("Gateway request failed")

    async def generate_multimodal_content(
        self,
        prompt: str,
        *,
        images: Optional[list[Any]] = None,
        system_instruction: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
        json_mode: bool = True,
    ) -> tuple[str, float]:
        t0 = time.perf_counter()
        messages = self._build_multimodal_messages(prompt, images=images, system_instruction=system_instruction)
        resp_fmt = {"type": "json_object"} if json_mode else None
        data = await self.chat_completion(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_output_tokens,
            response_format=resp_fmt,
        )
        duration_ms = (time.perf_counter() - t0) * 1000.0
        return self._extract_content_text(data), duration_ms
