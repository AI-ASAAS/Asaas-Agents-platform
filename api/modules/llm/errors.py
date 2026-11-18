from collections.abc import Mapping
import re
from typing import Any


class LLMBaseError(Exception):
    """Base class for all normalized LLM Gateway errors."""

    status_code: int = 500
    code: str = "llm_error"

    def __init__(
        self,
        message_ar: str,
        message_en: str,
        status_code: int | None = None,
        code: str | None = None,
        retry_after_seconds: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code
        self.retry_after_seconds = retry_after_seconds
        self.details = details or {}

    def get_message(self, lang: str = "ar") -> str:
        return self.message_en if lang.lower().startswith("en") else self.message_ar

    def to_dict(self, lang: str = "ar") -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.get_message(lang),
        }
        if self.retry_after_seconds is not None:
            payload["retry_after_seconds"] = self.retry_after_seconds
        if self.details:
            payload["details"] = self.details
        return payload


class InvalidKeyError(LLMBaseError):
    status_code = 401
    code = "invalid_key"

    def __init__(self, message_ar: str = "مفتاح API غير صالح أو منتهي الصلاحية.", message_en: str = "Invalid or expired API key.", **kwargs: Any) -> None:
        super().__init__(message_ar, message_en, status_code=401, code="invalid_key", **kwargs)


class RateLimitedError(LLMBaseError):
    status_code = 429
    code = "rate_limited"

    def __init__(
        self,
        message_ar: str = "تم تجاوز حد معدل الطلبات المسموح به للمزود. يرجى الانتظار والمحاولة لاحقاً.",
        message_en: str = "Provider rate limit exceeded. Please wait and try again.",
        retry_after_seconds: float | None = None,
        scope: str | None = None,
        **kwargs: Any,
    ) -> None:
        details = kwargs.pop("details", {})
        if scope:
            details["scope"] = scope
        super().__init__(
            message_ar,
            message_en,
            status_code=429,
            code="rate_limited",
            retry_after_seconds=retry_after_seconds,
            details=details,
            **kwargs,
        )


class QuotaExhaustedError(LLMBaseError):
    status_code = 429
    code = "quota_exhausted"

    def __init__(
        self,
        message_ar: str = "نفدت الحصة الإجمالية لحسابك أو رصيدك لدى المزود.",
        message_en: str = "Your provider quota or credit balance has been completely exhausted.",
        **kwargs: Any,
    ) -> None:
        super().__init__(message_ar, message_en, status_code=429, code="quota_exhausted", **kwargs)


class ModelNotFoundError(LLMBaseError):
    status_code = 404
    code = "model_not_found"

    def __init__(
        self,
        model_name: str,
        message_ar: str | None = None,
        message_en: str | None = None,
        **kwargs: Any,
    ) -> None:
        ar = message_ar or f"النموذج المختار غير متوفر أو غير مدعوم: {model_name}"
        en = message_en or f"The requested model is unavailable or unsupported: {model_name}"
        super().__init__(ar, en, status_code=404, code="model_not_found", details={"model": model_name}, **kwargs)


class UnsupportedFeatureError(LLMBaseError):
    status_code = 400
    code = "unsupported_feature"

    def __init__(
        self,
        feature: str,
        message_ar: str | None = None,
        message_en: str | None = None,
        **kwargs: Any,
    ) -> None:
        ar = message_ar or f"الخاصية المطلوبة غير مدعومة من هذا النموذج: {feature}"
        en = message_en or f"The requested feature is unsupported by this model: {feature}"
        super().__init__(ar, en, status_code=400, code="unsupported_feature", details={"feature": feature}, **kwargs)


class ProviderUnavailableError(LLMBaseError):
    status_code = 503
    code = "provider_unavailable"

    def __init__(
        self,
        message_ar: str = "خدمة المزود الذكي غير متاحة حالياً أو استغرقت وقتاً أطول من المسموح به.",
        message_en: str = "The AI provider service is currently unavailable or timed out.",
        **kwargs: Any,
    ) -> None:
        super().__init__(message_ar, message_en, status_code=503, code="provider_unavailable", **kwargs)


class BadRequestError(LLMBaseError):
    status_code = 400
    code = "bad_request"

    def __init__(
        self,
        message_ar: str = "معاملات الطلب غير صالحة للمزود المختار.",
        message_en: str = "Invalid request parameters for the selected provider.",
        **kwargs: Any,
    ) -> None:
        super().__init__(message_ar, message_en, status_code=400, code="bad_request", **kwargs)


def extract_retry_after(headers: Mapping[str, str]) -> float | None:
    """Extracts retry-after duration in seconds from standard response headers."""
    for header_name in ("retry-after", "retry-after-ms", "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
        val = headers.get(header_name)
        if not val:
            continue
        try:
            sec = float(val)
            if header_name.endswith("-ms"):
                sec /= 1000.0
            return max(0.5, round(sec, 1))
        except ValueError:
            # Header might be an HTTP date or string format like '10s' or '60s'
            match = re.match(r"^(\d+(?:\.\d+)?)\s*s?$", val.strip())
            if match:
                return max(0.5, round(float(match.group(1)), 1))
    return None


def normalize_provider_error(
    provider: str,
    status_code: int,
    response_text: str,
    headers: Mapping[str, str],
) -> LLMBaseError:
    """
    Normalizes provider-specific HTTP errors into standardized typed platform errors.
    NEVER leaks raw keys or un-sanitized internal vendor payloads.
    """
    lower_text = response_text.lower()
    retry_after = extract_retry_after(headers)

    # 1. Authentication / Key Errors
    if status_code == 401 or (status_code in (400, 403) and any(x in lower_text for x in ("api_key", "invalid x-api-key", "invalid api key", "unauthenticated", "invalid_argument", "api key not valid"))):
        return InvalidKeyError(
            details={"provider": provider},
        )

    # 2. Rate Limits & Quota Exhaustion
    if status_code in (429, 402):
        if any(term in lower_text for term in ("insufficient_quota", "quota exceeded", "quota exhausted", "credit balance", "insufficient credits")):
            return QuotaExhaustedError(
                details={"provider": provider},
            )
        return RateLimitedError(
            retry_after_seconds=retry_after or 60.0,
            scope="requests" if "request" in lower_text else ("tokens" if "token" in lower_text else None),
            details={"provider": provider},
        )

    # 3. Model Not Found
    if status_code == 404 or "model_not_found" in lower_text or "does not exist" in lower_text:
        return ModelNotFoundError(
            model_name="unknown",
            details={"provider": provider},
        )

    # 4. Bad Request / Unsupported Feature
    if status_code == 400:
        if "tools" in lower_text or "schema" in lower_text or "function" in lower_text or "vision" in lower_text:
            return UnsupportedFeatureError(
                feature="capability",
                details={"provider": provider},
            )
        return BadRequestError(
            details={"provider": provider},
        )

    # 5. Server Errors (5xx)
    if status_code >= 500:
        return ProviderUnavailableError(
            details={"provider": provider, "upstream_status": status_code},
        )

    return LLMBaseError(
        message_ar="حدث خطأ غير متوقع أثناء الاتصال بمزود الذكاء الاصطناعي.",
        message_en=f"Unexpected error from provider {provider} (status {status_code}).",
        status_code=status_code,
        code="provider_error",
        details={"provider": provider, "status_code": status_code},
    )
