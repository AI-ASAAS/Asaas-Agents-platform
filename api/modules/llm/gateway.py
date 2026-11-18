import asyncio
import json
import logging
import time
from typing import Any
import httpx

from config import settings
from .adapters import (
    AnthropicAdapter,
    BaseProviderAdapter,
    GeminiAdapter,
    OpenAIAdapter,
    OpenRouterAdapter,
)
from .errors import LLMBaseError, ProviderUnavailableError
from .schemas import ChatCompletionRequest, ChatCompletionResponse

logger = logging.getLogger("llm.gateway")

RETRYABLE_STATUS = {500, 502, 503, 504}


class LLMGateway:
    """
    Central LLM Gateway: the only code that talks to AI providers.
    - Credentials attached strictly per-request from visitor headers.
    - One shared httpx.AsyncClient pool without default authorization headers.
    - Bounded retries (1 max) for transport/5xx only; NO retry on 400/401/403/429.
    - NO automatic model fallback.
    - Structured logging without prompts, answers, or keys.
    """

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._http = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=settings.llm_connect_timeout_seconds),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
        )
        self._adapters: dict[str, BaseProviderAdapter] = {
            "openai": OpenAIAdapter(),
            "openrouter": OpenRouterAdapter(),
            "gemini": GeminiAdapter(),
            "anthropic": AnthropicAdapter(),
        }
        self._model_capabilities: dict[str, Any] = {}
        self._load_capabilities()

    def _load_capabilities(self) -> None:
        path = settings.model_capabilities_path
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._model_capabilities = data.get("models", {})
            except Exception as e:
                logger.error("Failed to load model capabilities: %s", e)

    def register_adapter(self, name: str, adapter: BaseProviderAdapter) -> None:
        """Allows injecting mock or custom adapters for spikes/tests."""
        self._adapters[name] = adapter

    def get_adapter(self, provider: str) -> BaseProviderAdapter:
        adapter = self._adapters.get(provider.lower())
        if not adapter:
            raise LLMBaseError(
                message_ar=f"مزود الخدمة غير مدعوم: {provider}",
                message_en=f"Unsupported provider: {provider}",
                status_code=400,
                code="unsupported_provider",
            )
        return adapter

    def _apply_estimated_pricing(self, provider: str, model: str, response: ChatCompletionResponse) -> None:
        """Calculates estimated cost in USD based on known token rates."""
        if response.usage.estimated_cost_usd is not None:
            return  # Provider already supplied explicit cost (e.g. OpenRouter)

        provider_models = self._model_capabilities.get(provider, {})
        model_meta = provider_models.get(model, {})
        pricing = model_meta.get("pricing")
        if not pricing:
            return

        in_tokens = response.usage.input_tokens or 0
        out_tokens = response.usage.output_tokens or 0
        in_rate = pricing.get("input_per_million", 0.0)
        out_rate = pricing.get("output_per_million", 0.0)

        cost = (in_tokens / 1_000_000.0) * in_rate + (out_tokens / 1_000_000.0) * out_rate
        response.usage.estimated_cost_usd = round(cost, 6)

    async def validate_key(self, provider: str, key: str) -> list[str]:
        """Validates key using cheapest call. Retries only on transport/5xx."""
        adapter = self.get_adapter(provider)
        for attempt in range(settings.llm_max_retries + 1):
            try:
                return await adapter.validate_key(self._http, key)
            except LLMBaseError as e:
                # Re-raise non-retryable errors immediately (401, 429, 400, etc.)
                if e.status_code not in RETRYABLE_STATUS and e.status_code < 500:
                    raise
                if attempt < settings.llm_max_retries:
                    await asyncio.sleep(settings.llm_backoff_seconds * (2**attempt))
                    continue
                raise
            except (httpx.TransportError, httpx.TimeoutException) as e:
                if attempt < settings.llm_max_retries:
                    await asyncio.sleep(settings.llm_backoff_seconds * (2**attempt))
                    continue
                raise ProviderUnavailableError() from e

        raise ProviderUnavailableError()

    async def chat_completion(
        self,
        provider: str,
        key: str,
        request: ChatCompletionRequest,
    ) -> ChatCompletionResponse:
        adapter = self.get_adapter(provider)
        started = time.perf_counter()

        for attempt in range(settings.llm_max_retries + 1):
            try:
                response = await adapter.chat_completion(self._http, key, request)
                duration_ms = int((time.perf_counter() - started) * 1000)

                self._apply_estimated_pricing(provider, request.model, response)

                logger.info(
                    "llm call success provider=%s model=%s ms=%d in_tokens=%s out_tokens=%s status=200",
                    provider,
                    request.model,
                    duration_ms,
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                )
                return response
            except LLMBaseError as e:
                duration_ms = int((time.perf_counter() - started) * 1000)
                # NEVER retry on 400, 401, 403, 429
                if e.status_code not in RETRYABLE_STATUS and e.status_code < 500:
                    logger.warning(
                        "llm call failed provider=%s model=%s ms=%d status=%s code=%s (non-retryable)",
                        provider,
                        request.model,
                        duration_ms,
                        e.status_code,
                        e.code,
                    )
                    raise
                if attempt < settings.llm_max_retries:
                    logger.warning(
                        "llm call retryable status=%s attempt=%d/%d, retrying after backoff",
                        e.status_code,
                        attempt + 1,
                        settings.llm_max_retries,
                    )
                    await asyncio.sleep(settings.llm_backoff_seconds * (2**attempt))
                    continue
                logger.error(
                    "llm call failed provider=%s model=%s ms=%d status=%s code=%s after retries",
                    provider,
                    request.model,
                    duration_ms,
                    e.status_code,
                    e.code,
                )
                raise
            except (httpx.TransportError, httpx.TimeoutException) as e:
                if attempt < settings.llm_max_retries:
                    await asyncio.sleep(settings.llm_backoff_seconds * (2**attempt))
                    continue
                duration_ms = int((time.perf_counter() - started) * 1000)
                logger.error(
                    "llm transport failure provider=%s model=%s ms=%d error=%s",
                    provider,
                    request.model,
                    duration_ms,
                    type(e).__name__,
                )
                raise ProviderUnavailableError() from e

        raise ProviderUnavailableError()

    async def chat_completion_stream(
        self,
        provider: str,
        key: str,
        request: ChatCompletionRequest,
    ):
        """Streams chat completion deltas formatted as standard SSE lines."""
        adapter = self.get_adapter(provider)
        async for line in adapter.chat_completion_stream(self._http, key, request):
            yield line

    async def aclose(self) -> None:
        await self._http.aclose()


llm_gateway = LLMGateway()
