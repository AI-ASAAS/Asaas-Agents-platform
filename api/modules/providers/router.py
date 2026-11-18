from typing import Any
from fastapi import APIRouter, Body, Depends, Header, Query, Request

from .dependencies import get_provider_key, rate_limit_test_ip, rate_limit_validate_ip
from .schemas import (
    ConnectionTestRequest,
    ConnectionTestResponse,
    ModelsResponse,
    ProviderMeta,
    ValidateKeyResponse,
)
from .service import ProvidersService

router = APIRouter(prefix="/api", tags=["providers"])


def get_providers_service(request: Request) -> ProvidersService:
    return request.app.state.providers_service


@router.get("/providers", response_model=list[ProviderMeta])
async def list_providers(
    service: ProvidersService = Depends(get_providers_service),
) -> list[ProviderMeta]:
    """Retrieve metadata, setup steps, and key hints for supported providers."""
    return service.get_providers_metadata()


@router.get("/providers/limits")
async def get_provider_limits(
    service: ProvidersService = Depends(get_providers_service),
) -> dict[str, Any]:
    """Retrieve known free-tier limits and rate boundaries per provider/model."""
    return service.get_provider_limits()


@router.post(
    "/providers/validate",
    response_model=ValidateKeyResponse,
    dependencies=[Depends(rate_limit_validate_ip)],
)
async def validate_provider_key(
    creds: tuple[str, str] = Depends(get_provider_key),
    service: ProvidersService = Depends(get_providers_service),
) -> ValidateKeyResponse:
    """
    Validates visitor API key using the cheapest non-completion call.
    Protected with strict IP rate limiting.
    """
    provider, key = creds
    return await service.validate_key(provider, key)


@router.post("/providers/models", response_model=ModelsResponse)
async def list_provider_models(
    x_provider: str = Header(..., alias="X-Provider", description="Selected AI Provider"),
    x_provider_key: str | None = Header(default=None, alias="X-Provider-Key", description="Optional visitor API key to fetch live available models"),
    agent_slug: str | None = Query(default=None, description="Optional agent slug to evaluate compatibility"),
    x_lang: str = Header(default="ar", alias="X-Lang"),
    payload: dict[str, Any] | None = Body(default=None),
    service: ProvidersService = Depends(get_providers_service),
) -> ModelsResponse:
    """
    Lists provider models tagged with compatibility status against an optional agent manifest.
    When X-Provider-Key or payload.live_models is supplied, merges ALL live models available
    from the provider's API so visitors can choose any model their key supports.
    """
    live_models: list[str] | None = None
    if isinstance(payload, dict) and isinstance(payload.get("live_models"), list):
        live_models = [str(m).strip() for m in payload["live_models"] if isinstance(m, str) and m.strip()]

    return await service.get_models(
        provider=x_provider.strip().lower(),
        agent_slug=agent_slug,
        lang=x_lang,
        visitor_key=x_provider_key.strip() if x_provider_key and x_provider_key.strip() else None,
        live_models=live_models,
    )


@router.post(
    "/llm/test",
    response_model=ConnectionTestResponse,
    dependencies=[Depends(rate_limit_test_ip)],
)
async def test_llm_connection(
    request: ConnectionTestRequest,
    creds: tuple[str, str] = Depends(get_provider_key),
    service: ProvidersService = Depends(get_providers_service),
) -> ConnectionTestResponse:
    """
    Executes a minimal test message through the LLM gateway to verify live connectivity.
    Protected with strict IP rate limiting.
    """
    provider, key = creds
    return await service.test_connection(provider=provider, key=key, model=request.model)
