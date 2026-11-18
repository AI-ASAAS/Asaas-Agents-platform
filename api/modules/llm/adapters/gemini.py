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
    UsageInfo,
)


class GeminiAdapter(BaseProviderAdapter):
    name = "gemini"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.provider_base_urls["gemini"]).rstrip("/")

    async def validate_key(self, http: httpx.AsyncClient, key: str) -> list[str]:
        # Validate using OpenAI-compatible models endpoint with Bearer auth
        url = f"{self.base_url}/models"
        headers = {"Authorization": f"Bearer {key}"}
        resp = await http.get(url, headers=headers)
        if resp.status_code != 200:
            raise normalize_provider_error(self.name, resp.status_code, resp.text, resp.headers)

        data = resp.json()
        models = [
            m["id"].replace("models/", "")
            for m in data.get("data", [])
            if isinstance(m, dict) and "id" in m
        ]
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
        # Model normalization for Gemini
        model = request.model
        payload = request.model_dump(exclude_none=True)
        payload["model"] = model

        resp = await http.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            raise normalize_provider_error(self.name, resp.status_code, resp.text, resp.headers)

        data = resp.json()
        usage = self.extract_usage_info(model, data, resp.headers)

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
            id=data.get("id", "chatcmpl_gemini"),
            provider=self.name,
            model=data.get("model", model),
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

        retry_after = extract_retry_after(headers)

        # Gemini free tier does NOT emit rate limit headroom headers
        return UsageInfo(
            provider=self.name,
            model=model,
            requests=1,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            limits=None,
            retry_after_seconds=retry_after,
            source="unavailable",
        )
