from collections.abc import Mapping
import json
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


class AnthropicAdapter(BaseProviderAdapter):
    name = "anthropic"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.provider_base_urls["anthropic"]).rstrip("/")

    async def validate_key(self, http: httpx.AsyncClient, key: str) -> list[str]:
        url = f"{self.base_url}/models"
        headers = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        }
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
        url = f"{self.base_url}/messages"
        headers = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        # 1. Separate system messages from dialog
        system_prompts: list[str] = []
        anthropic_messages: list[dict[str, Any]] = []

        for m in request.messages:
            if m.role == "system":
                if isinstance(m.content, str) and m.content.strip():
                    system_prompts.append(m.content)
            elif m.role in ("user", "assistant"):
                content: Any = m.content
                if isinstance(content, list):
                    # Multimodal content translation: OpenAI format -> Anthropic format
                    content_blocks = []
                    for part in content:
                        if isinstance(part, dict):
                            p_type = part.get("type")
                            if p_type == "text":
                                content_blocks.append({"type": "text", "text": part.get("text", "")})
                            elif p_type == "image_url":
                                img_info = part.get("image_url", {})
                                img_url = img_info.get("url", "") if isinstance(img_info, dict) else str(img_info)
                                if img_url.startswith("data:"):
                                    try:
                                        header, base64_data = img_url.split(";base64,", 1)
                                        media_type = header.replace("data:", "").strip().lower() or "image/png"
                                        if media_type not in ("image/png", "image/jpeg", "image/gif", "image/webp"):
                                            media_type = "image/png"
                                    except ValueError:
                                        media_type = "image/png"
                                        base64_data = img_url
                                    content_blocks.append({
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": media_type,
                                            "data": base64_data,
                                        },
                                    })
                                else:
                                    content_blocks.append({"type": "text", "text": f"[Image URL: {img_url}]"})
                            else:
                                content_blocks.append(part)
                        else:
                            content_blocks.append({"type": "text", "text": str(part)})
                    content = content_blocks

                if m.tool_calls:
                    content_blocks = []
                    if content and isinstance(content, str):
                        content_blocks.append({"type": "text", "text": content})
                    elif isinstance(content, list):
                        content_blocks.extend(content)
                    for tc in m.tool_calls:
                        func = tc.get("function", {})
                        args = func.get("arguments", "{}")
                        parsed_args = json.loads(args) if isinstance(args, str) else args
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc.get("id"),
                            "name": func.get("name"),
                            "input": parsed_args,
                        })
                    content = content_blocks

                anthropic_messages.append({"role": m.role, "content": content or ""})

        payload: dict[str, Any] = {
            "model": request.model,
            "messages": anthropic_messages,
            "max_tokens": request.max_tokens or 1024,
            "temperature": request.temperature,
        }
        if request.response_format and request.response_format.get("type") == "json_object":
            system_prompts.append("CRITICAL: You must return valid JSON only. Do not wrap with code fences or commentary.")

        if system_prompts:
            payload["system"] = "\n\n".join(system_prompts)

        # 2. Translate tools if specified
        if request.tools:
            anthropic_tools: list[dict[str, Any]] = []
            for t in request.tools:
                fn = t.get("function", {})
                anthropic_tools.append({
                    "name": fn.get("name"),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                })
            payload["tools"] = anthropic_tools

        resp = await http.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            raise normalize_provider_error(self.name, resp.status_code, resp.text, resp.headers)

        data = resp.json()
        usage = self.extract_usage_info(request.model, data, resp.headers)

        # 3. Translate Anthropic response -> OpenAI format
        content_text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        for block in data.get("content", []):
            if block.get("type") == "text":
                content_text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id"),
                    "type": "function",
                    "function": {
                        "name": block.get("name"),
                        "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                    },
                })

        msg = ChatMessage(
            role="assistant",
            content="".join(content_text_parts) if content_text_parts else None,
            tool_calls=tool_calls if tool_calls else None,
        )

        return ChatCompletionResponse(
            id=data.get("id", "msg_anthropic"),
            provider=self.name,
            model=data.get("model", request.model),
            choices=[ChatCompletionChoice(index=0, message=msg, finish_reason=data.get("stop_reason", "stop"))],
            usage=usage,
        )

    def extract_usage_info(
        self,
        model: str,
        response_data: dict[str, Any],
        headers: Mapping[str, str],
    ) -> UsageInfo:
        usage_data = response_data.get("usage") or {}
        in_tokens = usage_data.get("input_tokens")
        out_tokens = usage_data.get("output_tokens")

        # Headroom from Anthropic headers
        req_limit = headers.get("anthropic-ratelimit-requests-limit")
        req_rem = headers.get("anthropic-ratelimit-requests-remaining")
        req_reset = headers.get("anthropic-ratelimit-requests-reset")

        tok_limit = headers.get("anthropic-ratelimit-tokens-limit")
        tok_rem = headers.get("anthropic-ratelimit-tokens-remaining")
        tok_reset = headers.get("anthropic-ratelimit-tokens-reset")

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
