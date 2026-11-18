from typing import Any, Literal
from pydantic import BaseModel, Field
from modules.llm.schemas import UsageInfo


class ProviderMeta(BaseModel):
    id: str
    name_ar: str
    name_en: str
    key_format_hint: str
    supports_model_listing: bool
    supports_usage_headers: bool
    free_key_url: str
    free_key_steps_ar: list[str]
    free_key_steps_en: list[str]


class ValidateKeyResponse(BaseModel):
    ok: bool = True
    provider: str
    models: list[str] = Field(default_factory=list)


ModelTag = Literal["compatible", "unknown", "incompatible"]


class ModelItem(BaseModel):
    id: str
    display_name: str
    tag: ModelTag
    reason: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)
    pricing: dict[str, Any] | None = None


class ModelsResponse(BaseModel):
    compatible: list[ModelItem] = Field(default_factory=list)
    unknown: list[ModelItem] = Field(default_factory=list)
    incompatible: list[ModelItem] = Field(default_factory=list)


class ModelsQueryRequest(BaseModel):
    agent_slug: str | None = None


class ConnectionTestRequest(BaseModel):
    model: str


class ConnectionTestResponse(BaseModel):
    ok: bool = True
    reply: str
    usage: UsageInfo
