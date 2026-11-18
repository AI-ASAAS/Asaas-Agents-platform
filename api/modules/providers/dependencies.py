from fastapi import Header, HTTPException, Request, status
from modules.security.rate_limiter import security_limiter

ALLOWED_PROVIDERS = {"gemini", "openai", "anthropic", "openrouter"}


def get_provider_key(
    request: Request,
    x_provider: str = Header(..., alias="X-Provider", description="Selected AI Provider"),
    x_provider_key: str = Header(..., alias="X-Provider-Key", description="Visitor API Key"),
) -> tuple[str, str]:
    """
    Extracts visitor credentials strictly from incoming headers.
    NEVER logs, stores, or echoes the key.
    """
    provider = x_provider.strip().lower()
    if provider not in ALLOWED_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"المزود غير مدعوم: {x_provider}",
        )

    key = x_provider_key.strip()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="مفتاح API مطلوب في الترويسة X-Provider-Key.",
        )

    return provider, key


def rate_limit_validate_ip(request: Request) -> None:
    """Enforces rate limiting for visitor API key validation."""
    security_limiter.check_key_validation(request)


def rate_limit_test_ip(request: Request) -> None:
    """Enforces rate limiting for visitor live connection tests."""
    security_limiter.check_connection_test(request)


def rate_limit_ip(request: Request) -> None:
    """Legacy alias for backward compatibility."""
    security_limiter.check_key_validation(request)
