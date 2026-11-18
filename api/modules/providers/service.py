import json
import logging
from typing import Any
from fastapi import HTTPException, status

from config import settings
from modules.catalog.repository import CatalogRepository
from modules.llm.gateway import LLMGateway
from modules.llm.schemas import ChatCompletionRequest, ChatMessage
from .schemas import (
    ConnectionTestResponse,
    ModelItem,
    ModelsResponse,
    ProviderMeta,
    ValidateKeyResponse,
)

logger = logging.getLogger("providers.service")

PROVIDERS_METADATA: list[ProviderMeta] = [
    ProviderMeta(
        id="gemini",
        name_ar="Google AI Studio (Gemini)",
        name_en="Google AI Studio (Gemini)",
        key_format_hint="AIzaSy...",
        supports_model_listing=True,
        supports_usage_headers=False,
        free_key_url="https://aistudio.google.com/app/apikey",
        free_key_steps_ar=[
            "افتح منصة Google AI Studio وسجّل دخولك بحساب Google.",
            "اضغط على زر 'Get API key' ثم 'Create API key'.",
            "انسخ المفتاح الذي يبدأ بـ AIza وضعه في الحقل أدناه (يتضمن باقة مجانية دائمة).",
        ],
        free_key_steps_en=[
            "Open Google AI Studio and sign in with your Google account.",
            "Click 'Get API key' and then 'Create API key'.",
            "Copy the key starting with 'AIza' and paste it below (free tier included).",
        ],
    ),
    ProviderMeta(
        id="openai",
        name_ar="OpenAI",
        name_en="OpenAI",
        key_format_hint="sk-proj-... / sk-...",
        supports_model_listing=True,
        supports_usage_headers=True,
        free_key_url="https://platform.openai.com/api-keys",
        free_key_steps_ar=[
            "سجّل الدخول إلى منصة OpenAI Platform.",
            "توجّه إلى قسم API Keys واضغط على 'Create new secret key'.",
            "انسخ المفتاح وضعه في الحقل أدناه (يتطلب رصيداً نشطاً في حسابك).",
        ],
        free_key_steps_en=[
            "Sign in to OpenAI Platform.",
            "Go to API Keys and click 'Create new secret key'.",
            "Copy the key and paste it below (requires active credit).",
        ],
    ),
    ProviderMeta(
        id="anthropic",
        name_ar="Anthropic (Claude)",
        name_en="Anthropic (Claude)",
        key_format_hint="sk-ant-...",
        supports_model_listing=True,
        supports_usage_headers=True,
        free_key_url="https://console.anthropic.com/settings/keys",
        free_key_steps_ar=[
            "سجّل الدخول إلى منصة Anthropic Console.",
            "توجّه إلى Settings -> API Keys واضغط على 'Create Key'.",
            "انسخ المفتاح الذي يبدأ بـ sk-ant- وضعه أدناه.",
        ],
        free_key_steps_en=[
            "Sign in to Anthropic Console.",
            "Navigate to Settings -> API Keys and click 'Create Key'.",
            "Copy the key starting with 'sk-ant-' and paste it below.",
        ],
    ),
    ProviderMeta(
        id="openrouter",
        name_ar="OpenRouter",
        name_en="OpenRouter",
        key_format_hint="sk-or-...",
        supports_model_listing=True,
        supports_usage_headers=True,
        free_key_url="https://openrouter.ai/keys",
        free_key_steps_ar=[
            "سجّل الدخول إلى منصة OpenRouter.",
            "توجّه إلى صفحة Keys وأنشئ مفتاحاً جديداً (Create Key).",
            "انسخ المفتاح الذي يبدأ بـ sk-or- وضعه أدناه (يتضمن موديلات مجانية).",
        ],
        free_key_steps_en=[
            "Sign in to OpenRouter.",
            "Go to Keys page and create a new key.",
            "Copy the key starting with 'sk-or-' and paste it below.",
        ],
    ),
]


class ProvidersService:
    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway
        self._capabilities_cache: dict[str, Any] = {}
        self._limits_cache: dict[str, Any] = {}
        self._load_configs()

    def _load_configs(self) -> None:
        cap_path = settings.model_capabilities_path
        if cap_path.exists():
            try:
                self._capabilities_cache = json.loads(cap_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error("Failed to read model_capabilities.json: %s", e)

        lim_path = settings.provider_limits_path
        if lim_path.exists():
            try:
                self._limits_cache = json.loads(lim_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error("Failed to read provider_limits.json: %s", e)

    def get_providers_metadata(self) -> list[ProviderMeta]:
        return PROVIDERS_METADATA

    def get_provider_limits(self) -> dict[str, Any]:
        return self._limits_cache.get("limits", {})

    async def validate_key(self, provider: str, key: str) -> ValidateKeyResponse:
        models = await self.gateway.validate_key(provider, key)
        return ValidateKeyResponse(ok=True, provider=provider, models=models)

    async def get_models(
        self,
        provider: str,
        agent_slug: str | None = None,
        lang: str = "ar",
        visitor_key: str | None = None,
        live_models: list[str] | None = None,
    ) -> ModelsResponse:
        is_en = lang.lower().startswith("en")
        models_data = self._capabilities_cache.get("models", {}).get(provider, {})

        # Fetch live models from provider API if visitor_key provided and live_models not already passed
        fetched_live: list[str] = list(live_models) if live_models else []
        if not fetched_live and visitor_key:
            try:
                fetched_live = await self.gateway.validate_key(provider, visitor_key)
            except Exception as exc:
                logger.warning("Live model listing failed for %s (%s); falling back to static catalog.", provider, type(exc).__name__)
                fetched_live = []

        # Fetch agent manifest requirements if slug specified
        agent_reqs: dict[str, Any] = {}
        allowed_providers: list[str] = []
        if agent_slug:
            agent = await CatalogRepository.get_agent_by_slug(agent_slug)
            if agent:
                raw_reqs = agent.get("model_requirements")
                if isinstance(raw_reqs, str):
                    agent_reqs = json.loads(raw_reqs)
                elif isinstance(raw_reqs, dict):
                    agent_reqs = raw_reqs

                raw_provs = agent.get("allowed_providers")
                if isinstance(raw_provs, str):
                    allowed_providers = json.loads(raw_provs)
                elif isinstance(raw_provs, list):
                    allowed_providers = raw_provs

        provider_not_allowed = bool(allowed_providers and provider not in allowed_providers)

        compatible: list[ModelItem] = []
        incompatible: list[ModelItem] = []
        unknown: list[ModelItem] = []
        seen_ids: set[str] = set()

        req_tool_calling = agent_reqs.get("tool_calling", False)
        req_json_schema = agent_reqs.get("json_schema", False)
        req_vision = agent_reqs.get("vision", False)
        req_min_context = agent_reqs.get("min_context_tokens", 0)

        def _classify_known_model(model_id: str, meta: dict[str, Any]) -> None:
            display_name = meta.get("display_name", model_id)
            pricing = meta.get("pricing")
            tool_calling = meta.get("tool_calling", False)
            json_schema = meta.get("json_schema", False)
            vision = meta.get("vision", False)
            min_context = meta.get("min_context_tokens", 0)

            capabilities = {
                "tool_calling": tool_calling,
                "json_schema": json_schema,
                "vision": vision,
                "min_context_tokens": min_context,
            }

            if provider_not_allowed:
                reason = "المزود غير مسموح به لهذا الوكيل المعتمد." if not is_en else "Provider is not allowed for this agent."
                incompatible.append(
                    ModelItem(
                        id=model_id,
                        display_name=display_name,
                        tag="incompatible",
                        reason=reason,
                        capabilities=capabilities,
                        pricing=pricing,
                    )
                )
                return

            reasons: list[str] = []
            if req_tool_calling and not tool_calling:
                reasons.append("استدعاء الأدوات والدوال (Tool Calling) غير مدعوم" if not is_en else "Tool calling unsupported")
            if req_json_schema and not json_schema:
                reasons.append("المخرجات المهيكلة (Structured Outputs) غير مدعومة" if not is_en else "Structured outputs unsupported")
            if req_vision and not vision:
                reasons.append("معالجة الصور والوسائط (Vision) غير مدعومة" if not is_en else "Vision unsupported")
            if req_min_context and min_context < req_min_context:
                reasons.append(
                    f"سياق النموذج ({min_context}) أقل من الحد المطلوب ({req_min_context})"
                    if not is_en
                    else f"Context window ({min_context}) is smaller than required ({req_min_context})"
                )

            if reasons:
                incompatible.append(
                    ModelItem(
                        id=model_id,
                        display_name=display_name,
                        tag="incompatible",
                        reason="; ".join(reasons),
                        capabilities=capabilities,
                        pricing=pricing,
                    )
                )
            else:
                compatible.append(
                    ModelItem(
                        id=model_id,
                        display_name=display_name,
                        tag="compatible",
                        capabilities=capabilities,
                        pricing=pricing,
                    )
                )

        # 1. Include all live models returned by the provider API first
        non_chat_markers = (
            "embedding",
            "aqa",
            "imagen",
            "veo-",
            "whisper",
            "tts-",
            "dall-e",
            "moderation",
            "babbage",
            "davinci",
            "realtime",
            "transcribe",
        )
        for raw_id in fetched_live:
            clean_id = raw_id.strip()
            if not clean_id or clean_id in seen_ids:
                continue
            lower_id = clean_id.lower()
            if any(marker in lower_id for marker in non_chat_markers):
                continue
            seen_ids.add(clean_id)
            if clean_id in models_data:
                _classify_known_model(clean_id, models_data[clean_id])
            elif provider_not_allowed:
                reason = "المزود غير مسموح به لهذا الوكيل المعتمد." if not is_en else "Provider is not allowed for this agent."
                incompatible.append(
                    ModelItem(
                        id=clean_id,
                        display_name=clean_id,
                        tag="incompatible",
                        reason=reason,
                        capabilities={},
                    )
                )
            else:
                unknown.append(
                    ModelItem(
                        id=clean_id,
                        display_name=clean_id,
                        tag="unknown",
                        reason=(
                            "متاح عبر API المزود (قدراته لم تُفحص محلياً بعد — يمكنك اختياره وتجربته)"
                            if not is_en
                            else "Available via provider API (capabilities not pre-profiled)"
                        ),
                        capabilities={},
                    )
                )

        # 2. Include static catalog entries not already covered by live listing
        for model_id, meta in models_data.items():
            if model_id in seen_ids:
                continue
            seen_ids.add(model_id)
            _classify_known_model(model_id, meta)

        # Sort unknown live models alphabetically (newest/higher versions near top)
        unknown.sort(key=lambda m: m.id.lower(), reverse=True)

        return ModelsResponse(
            compatible=compatible,
            unknown=unknown,
            incompatible=incompatible,
        )

    async def test_connection(
        self,
        provider: str,
        key: str,
        model: str,
    ) -> ConnectionTestResponse:
        request = ChatCompletionRequest(
            model=model,
            messages=[
                ChatMessage(
                    role="user",
                    content="Reply with OK.",
                )
            ],
            max_tokens=64,
            temperature=0.0,
        )

        response = await self.gateway.chat_completion(provider, key, request)
        reply_content = response.choices[0].message.content or "جاهز"

        return ConnectionTestResponse(
            ok=True,
            reply=reply_content.strip(),
            usage=response.usage,
        )
