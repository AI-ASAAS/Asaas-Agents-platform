from typing import Any, Literal
from pydantic import BaseModel, Field


class LimitHeadroom(BaseModel):
    limit: int | None = None
    remaining: int | None = None
    reset_at: str | None = None


class ProviderLimitsInfo(BaseModel):
    requests: LimitHeadroom | None = None
    tokens: LimitHeadroom | None = None


class UsageInfo(BaseModel):
    provider: str
    model: str
    requests: int = 1
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    limits: ProviderLimitsInfo | None = None
    retry_after_seconds: float | None = None
    source: Literal["provider", "estimated", "unavailable"] = "unavailable"


class ChatMessage(BaseModel):
    role: str
    content: str | list[Any] | None = None
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=800, ge=1)
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None
    response_format: dict[str, Any] | None = None
    stream: bool = False


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str | None = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    provider: str
    model: str
    choices: list[ChatCompletionChoice]
    usage: UsageInfo
