"""Centralized CrewAI LLM factory supporting both ASAAS Platform Gateway and standalone Gemini."""

import os
from typing import Optional

from crewai import LLM

from site_dna.core.config import Settings, get_settings
from site_dna.core.llm_gateway import get_current_run_llm_context, is_platform_llm_active
from site_dna.core.logging import get_logger

logger = get_logger(__name__)


class GeminiConfigurationError(RuntimeError):
    """Raised when LLM initialization fails due to missing or invalid credentials."""


LLMConfigurationError = GeminiConfigurationError


def format_crewai_gemini_model(model: str) -> str:
    """Format model identifier with CrewAI's required 'gemini/' provider prefix without duplication."""
    stripped = model.strip()
    if not stripped:
        raise GeminiConfigurationError("Model identifier cannot be empty.")
    if stripped.startswith("gemini/"):
        return stripped
    return f"gemini/{stripped}"


format_gemini_model_id = format_crewai_gemini_model


def get_llm(
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: Optional[float] = None,
    timeout: Optional[int] = 90,
    settings: Optional[Settings] = None,
    run_token: Optional[str] = None,
    platform_base_url: Optional[str] = None,
) -> LLM:
    """Build and return a configured CrewAI LLM instance.

    In ASAAS Platform Mode (active per-run context or ``site_dna_service_mode``),
    routes exclusively to the platform's local OpenAI-compatible runtime gateway
    using the per-run bearer token and never reads a global provider API key.
    In standalone CLI/dev mode, falls back to direct Gemini configuration.
    """
    cfg = settings or get_settings()
    ctx = get_current_run_llm_context()

    # 1. Platform Service Mode (per-run context preferred, explicit token fallback)
    if (ctx is not None or run_token or is_platform_llm_active(cfg)) and not api_key:
        effective_token = run_token or (ctx.run_token if ctx else None)
        if not effective_token:
            raise GeminiConfigurationError(
                "Platform service mode requires an active per-run token (X-Run-Token)."
            )
        base_url = (
            platform_base_url
            or (ctx.normalized_endpoint() if ctx else None)
            or getattr(cfg, "platform_llm_base_url", None)
            or os.environ.get("PLATFORM_LLM_BASE_URL")
            or "http://127.0.0.1:8000/v1"
        )
        base_url = base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"

        chosen_model = (ctx.model if ctx and ctx.model else None) or model or cfg.gemini_model
        clean_model = chosen_model.removeprefix("gemini/").removeprefix("openai/")
        logger.debug("Initializing Platform Gateway CrewAI LLM: model=openai/%s, base_url=%s", clean_model, base_url)
        kwargs: dict = {
            "model": f"openai/{clean_model}",
            "base_url": base_url,
            "api_key": effective_token,
            "timeout": timeout,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        return LLM(**kwargs)

    # 2. Standalone local mode (direct Gemini)
    effective_key = (api_key or "").strip() or cfg.get_effective_gemini_api_key()
    if not effective_key:
        raise GeminiConfigurationError(
            "GEMINI_API_KEY is not configured. Set GEMINI_API_KEY in your .env file "
            "or run via the ASAAS platform gateway."
        )

    raw_model = model or cfg.gemini_model
    formatted_model = format_crewai_gemini_model(raw_model)

    logger.debug("Initializing standalone CrewAI LLM with model=%s", formatted_model)
    kwargs = {
        "model": formatted_model,
        "api_key": effective_key,
        "timeout": timeout,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    return LLM(**kwargs)
