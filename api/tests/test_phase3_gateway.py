import asyncio
import io
import logging
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from starlette.testclient import TestClient

from config import settings
from main import app
from modules.llm.adapters.base import BaseProviderAdapter
from modules.llm.errors import (
    InvalidKeyError,
    ProviderUnavailableError,
    RateLimitedError,
)
from modules.llm.gateway import LLMGateway
from modules.llm.schemas import (
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    UsageInfo,
)
from modules.providers.rate_limit import ip_limiter


class MockTestAdapter(BaseProviderAdapter):
    """Controllable adapter to verify gateway retry, error normalization, and non-retry policies."""

    name = "mock"

    def __init__(self) -> None:
        self.call_count = 0
        self.mode = "200"  # "200", "401", "429", "500", "timeout"
        self.retry_after_val = 15.0

    async def validate_key(self, http: httpx.AsyncClient, key: str) -> list[str]:
        self.call_count += 1
        if self.mode == "401":
            raise InvalidKeyError(details={"key_sent": key})
        if self.mode == "429":
            raise RateLimitedError(retry_after_seconds=self.retry_after_val)
        if self.mode == "500":
            raise ProviderUnavailableError()
        if self.mode == "timeout":
            raise httpx.ReadTimeout("Mock read timeout")
        return ["mock-model-1", "mock-model-2"]

    async def chat_completion(
        self,
        http: httpx.AsyncClient,
        key: str,
        request: ChatCompletionRequest,
    ) -> ChatCompletionResponse:
        self.call_count += 1
        if self.mode == "401":
            raise InvalidKeyError(details={"key_sent": key})
        if self.mode == "429":
            raise RateLimitedError(retry_after_seconds=self.retry_after_val)
        if self.mode == "500":
            raise ProviderUnavailableError()
        if self.mode == "timeout":
            raise httpx.ReadTimeout("Mock read timeout")

        return ChatCompletionResponse(
            id="mock-123",
            provider=self.name,
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content="جاهز"),
                    finish_reason="stop",
                )
            ],
            usage=self.extract_usage_info(request.model, {}, {}),
        )

    def extract_usage_info(
        self,
        model: str,
        response_data: dict[str, Any],
        headers: Mapping[str, str],
    ) -> UsageInfo:
        return UsageInfo(
            provider=self.name,
            model=model,
            requests=1,
            input_tokens=10,
            output_tokens=5,
            source="provider",
        )


def test_provider_metadata_and_limits():
    with TestClient(app) as client:
        # 1. GET /api/providers
        res = client.get("/api/providers")
        assert res.status_code == 200
        providers = res.json()
        assert len(providers) == 4
        ids = [p["id"] for p in providers]
        assert "gemini" in ids
        assert "openai" in ids
        assert "anthropic" in ids
        assert "openrouter" in ids
        print("✓ Providers metadata endpoint OK:", ids)

        # 2. GET /api/providers/limits
        res = client.get("/api/providers/limits")
        assert res.status_code == 200
        limits = res.json()
        assert "gemini" in limits
        assert "default" in limits["gemini"]
        assert limits["gemini"]["default"]["rpm"] == 15
        print("✓ Provider limits endpoint OK")


def test_model_compatibility_matching():
    with TestClient(app) as client:
        # Query models for support-agent (requires tool_calling)
        res = client.post(
            "/api/providers/models?agent_slug=support-agent",
            headers={"X-Provider": "openrouter"},
        )
        assert res.status_code == 200
        data = res.json()

        # meta-llama/llama-3.2-3b-instruct:free has tool_calling: false -> incompatible
        incomp_ids = [m["id"] for m in data["incompatible"]]
        assert "meta-llama/llama-3.2-3b-instruct:free" in incomp_ids
        bad_model = next(m for m in data["incompatible"] if m["id"] == "meta-llama/llama-3.2-3b-instruct:free")
        assert "استدعاء الأدوات" in bad_model["reason"]
        print("✓ Incompatible model flagged with Arabic reason OK:", bad_model["reason"])

        # meta-llama/llama-3.3-70b-instruct has tool_calling: true -> compatible
        comp_ids = [m["id"] for m in data["compatible"]]
        assert "meta-llama/llama-3.3-70b-instruct" in comp_ids
        print("✓ Compatible model identified OK:", comp_ids)


def test_gateway_policies_and_redaction():
    """
    Verifies that:
    1. 429 is NOT retried and returns retry_after_seconds.
    2. 401 is NOT retried.
    3. 5xx is retried once.
    4. Timeout is retried once.
    5. The key is never logged or exposed.
    """
    mock_adapter = MockTestAdapter()
    gateway = LLMGateway()
    gateway.register_adapter("mock", mock_adapter)

    # Attach log capture
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    llm_logger = logging.getLogger("llm.gateway")
    llm_logger.addHandler(handler)

    test_key = "sk-test-supersecret-token-do-not-leak"

    # Test 1: 429 Rate Limit (Must NOT retry!)
    mock_adapter.call_count = 0
    mock_adapter.mode = "429"
    try:
        asyncio.run(
            gateway.chat_completion(
                "mock",
                test_key,
                ChatCompletionRequest(model="test-m", messages=[ChatMessage(role="user", content="hi")]),
            )
        )
        raise AssertionError("Expected RateLimitedError was not raised")
    except RateLimitedError as e:
        assert mock_adapter.call_count == 1, f"Expected 1 call (NO retry on 429), got {mock_adapter.call_count}"
        assert e.retry_after_seconds == 15.0
        print("✓ Gateway: 429 received and NOT retried (call_count = 1, retry_after = 15s)")

    # Test 2: 401 Unauthorized (Must NOT retry!)
    mock_adapter.call_count = 0
    mock_adapter.mode = "401"
    try:
        asyncio.run(gateway.validate_key("mock", test_key))
        raise AssertionError("Expected InvalidKeyError was not raised")
    except InvalidKeyError:
        assert mock_adapter.call_count == 1, f"Expected 1 call (NO retry on 401), got {mock_adapter.call_count}"
        print("✓ Gateway: 401 received and NOT retried (call_count = 1)")

    # Test 3: 500 Server Error (MUST retry once!)
    mock_adapter.call_count = 0
    mock_adapter.mode = "500"
    try:
        asyncio.run(
            gateway.chat_completion(
                "mock",
                test_key,
                ChatCompletionRequest(model="test-m", messages=[ChatMessage(role="user", content="hi")]),
            )
        )
        raise AssertionError("Expected ProviderUnavailableError was not raised")
    except ProviderUnavailableError:
        assert mock_adapter.call_count == 2, f"Expected 2 calls (1 initial + 1 retry on 5xx), got {mock_adapter.call_count}"
        print("✓ Gateway: 5xx received and retried once (call_count = 2)")

    # Test 4: Timeout (MUST retry once!)
    mock_adapter.call_count = 0
    mock_adapter.mode = "timeout"
    try:
        asyncio.run(
            gateway.chat_completion(
                "mock",
                test_key,
                ChatCompletionRequest(model="test-m", messages=[ChatMessage(role="user", content="hi")]),
            )
        )
        raise AssertionError("Expected ProviderUnavailableError was not raised")
    except ProviderUnavailableError:
        assert mock_adapter.call_count == 2, f"Expected 2 calls (1 initial + 1 retry on timeout), got {mock_adapter.call_count}"
        print("✓ Gateway: Timeout received and retried once (call_count = 2)")

    # Test 5: Key Redaction in Logs
    handler.flush()
    logs = log_stream.getvalue()
    assert test_key not in logs, "SECURITY FAILURE: API key was found in gateway logs!"
    print("✓ Security: Secret key confirmed ABSENT from logs (0 occurrences)")


def test_ip_rate_limiting():
    ip_limiter.reset()
    with TestClient(app) as client:
        limit = settings.rate_limit_validate_key_per_min
        # Requests up to the limit succeed or fail with 401 (not 429)
        for i in range(limit):
            res = client.post(
                "/api/providers/validate",
                headers={"X-Provider": "openai", "X-Provider-Key": "sk-invalid-test-key"},
            )
            assert res.status_code != 429, f"Unexpected 429 at request {i}"

        # Request exceeding limit MUST trigger IP rate limit 429!
        res_exceeded = client.post(
            "/api/providers/validate",
            headers={"X-Provider": "openai", "X-Provider-Key": "sk-invalid-test-key"},
        )
        assert res_exceeded.status_code == 429, f"Expected 429 on exceeded request, got {res_exceeded.status_code}"
        body = res_exceeded.json()
        assert body["code"] == "rate_limited"
        assert "retry_after_seconds" in body
        print(f"✓ IP Rate limiting triggered on request {limit + 1}:", body)


if __name__ == "__main__":
    print("--- Running Phase 3 Backend Verification Tests ---")
    test_provider_metadata_and_limits()
    test_model_compatibility_matching()
    test_gateway_policies_and_redaction()
    test_ip_rate_limiting()
    print("--- All Phase 3 Backend Tests Passed Successfully! ---")
