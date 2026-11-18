from collections.abc import Mapping
from typing import Any
import httpx

from config import settings
from .base import BaseProviderAdapter
from ..errors import extract_retry_after, normalize_provider_error
from ..schemas import (
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    LimitHeadroom,
    ProviderLimitsInfo,
    UsageInfo,
)


class OpenAIAdapter(BaseProviderAdapter):
    name = "openai"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.provider_base_urls["openai"]).rstrip("/")

    async def validate_key(self, http: httpx.AsyncClient, key: str) -> list[str]:
        url = f"{self.base_url}/models"
        headers = {"Authorization": f"Bearer {key}"}
        resp = await http.get(url, headers=headers)
        if resp.status_code != 200:
            raise normalize_provider_error(self.name, resp.status_code, resp.text, resp.headers)

        data = resp.json()
        models = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m]
        return models

    async def chat_completion(
        self,
        http: httpx.AsyncClient,
        key: str,
        request: ChatCompletionRequest,
    ) -> ChatCompletionResponse:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        payload = request.model_dump(exclude_none=True)
        resp = await http.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            raise normalize_provider_error(self.name, resp.status_code, resp.text, resp.headers)

        data = resp.json()
        usage = self.extract_usage_info(request.model, data, resp.headers)

        choices: list[ChatCompletionChoice] = []
        for c in data.get("choices", []):
            msg_data = c.get("message", {})
            msg = ChatMessage(
                role=msg_data.get("role", "assistant"),
                content=msg_data.get("content"),
                tool_calls=msg_data.get("tool_calls"),
            )
            choices.append(
                ChatCompletionChoice(
                    index=c.get("index", 0),
                    message=msg,
                    finish_reason=c.get("finish_reason", "stop"),
                )
            )

        return ChatCompletionResponse(
            id=data.get("id", "chatcmpl_openai"),
            provider=self.name,
            model=data.get("model", request.model),
            choices=choices,
            usage=usage,
        )

    def extract_usage_info(
        self,
        model: str,
        response_data: dict[str, Any],
        headers: Mapping[str, str],
    ) -> UsageInfo:
        usage_data = response_data.get("usage") or {}
        in_tokens = usage_data.get("prompt_tokens")
        out_tokens = usage_data.get("completion_tokens")

        # Headroom from OpenAI headers
        req_limit = headers.get("x-ratelimit-limit-requests")
        req_rem = headers.get("x-ratelimit-remaining-requests")
        req_reset = headers.get("x-ratelimit-reset-requests")

        tok_limit = headers.get("x-ratelimit-limit-tokens")
        tok_rem = headers.get("x-ratelimit-remaining-tokens")
        tok_reset = headers.get("x-ratelimit-reset-tokens")

        limits_info = None
        source: Any = "unavailable"
        if req_rem is not None or tok_rem is not None:
            source = "provider"
            limits_info = ProviderLimitsInfo(
                requests=LimitHeadroom(
                    limit=int(req_limit) if req_limit and req_limit.isdigit() else None,
                    remaining=int(req_rem) if req_rem and req_rem.isdigit() else None,
                    reset_at=req_reset,
                ) if req_rem is not None else None,
                tokens=LimitHeadroom(
                    limit=int(tok_limit) if tok_limit and tok_limit.isdigit() else None,
                    remaining=int(tok_rem) if tok_rem and tok_rem.isdigit() else None,
                    reset_at=tok_reset,
                ) if tok_rem is not None else None,
            )

        retry_after = extract_retry_after(headers)

        return UsageInfo(
            provider=self.name,
            model=model,
            requests=1,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            limits=limits_info,
            retry_after_seconds=retry_after,
            source=source,
        )
