from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Mapping
import json
from typing import Any
import httpx

from ..schemas import ChatCompletionRequest, ChatCompletionResponse, UsageInfo


class BaseProviderAdapter(ABC):
    """Abstract base class for LLM provider adapters."""

    name: str

    @abstractmethod
    async def validate_key(self, http: httpx.AsyncClient, key: str) -> list[str]:
        """
        Validates the key using the cheapest non-completion call (e.g. listing models).
        Raises InvalidKeyError or RateLimitedError on failure.
        Returns the list of available model IDs.
        """
        ...

    @abstractmethod
    async def chat_completion(
        self,
        http: httpx.AsyncClient,
        key: str,
        request: ChatCompletionRequest,
    ) -> ChatCompletionResponse:
        """
        Executes a chat completion request and returns an OpenAI-standardized response with UsageInfo.
        """
        ...

    async def chat_completion_stream(
        self,
        http: httpx.AsyncClient,
        key: str,
        request: ChatCompletionRequest,
    ) -> AsyncGenerator[str, None]:
        """
        Executes a streaming chat completion request and yields SSE formatted lines.
        Default implementation converts standard response into SSE chunks.
        """
        resp = await self.chat_completion(http, key, request)
        content = resp.choices[0].message.content or ""
        msg_id = resp.id or "chatcmpl_default"
        chunk_size = 32
        for i in range(0, max(len(content), 1), chunk_size):
            piece = content[i : i + chunk_size]
            chunk_data = {
                "id": msg_id,
                "object": "chat.completion.chunk",
                "model": resp.model,
                "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
        end_data = {
            "id": msg_id,
            "object": "chat.completion.chunk",
            "model": resp.model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(end_data, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    @abstractmethod
    def extract_usage_info(
        self,
        model: str,
        response_data: dict[str, Any],
        headers: Mapping[str, str],
    ) -> UsageInfo:
        """Extracts token usage, pricing, and rate-limit headroom from response."""
        ...
