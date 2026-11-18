"""Unit tests for Site DNA's PlatformLLMGateway using a fake local OpenAI-compatible HTTP server."""

from __future__ import annotations

import base64
import concurrent.futures
import contextvars
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from site_dna.core.config import Settings
from site_dna.core.llm import get_llm
from site_dna.core.llm_gateway import (
    LLMInvalidKeyError,
    LLMProviderUnavailableError,
    LLMQuotaExhaustedError,
    LLMRateLimitError,
    LLMRunCancelledError,
    LLMTimeoutError,
    PlatformLLMGateway,
    RunLLMContext,
    get_current_run_llm_context,
    reset_run_llm_context,
    set_run_llm_context,
)


class _FakeGatewayState:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []
        self.responses: list[tuple[int, dict[str, str], dict[str, Any]]] = []
        self.delay_seconds: float = 0.0
        self.lock = threading.Lock()

    def push_response(self, status: int, body: dict[str, Any], headers: dict[str, str] | None = None):
        with self.lock:
            self.responses.append((status, headers or {}, body))


@pytest.fixture
def fake_openai_server():
    """Spin up a lightweight local OpenAI-compatible HTTP server for gateway tests."""
    state = _FakeGatewayState()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return  # silence test output

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw.decode("utf-8"))
            auth = self.headers.get("Authorization", "")
            with state.lock:
                state.calls.append({"path": self.path, "auth": auth, "body": body})
                delay = state.delay_seconds
                if state.responses:
                    status, extra_headers, resp_body = state.responses.pop(0)
                else:
                    status, extra_headers, resp_body = (
                        200,
                        {},
                        {
                            "id": "chatcmpl-test",
                            "object": "chat.completion",
                            "choices": [
                                {
                                    "index": 0,
                                    "message": {"role": "assistant", "content": '{"ok": true}'},
                                    "finish_reason": "stop",
                                }
                            ],
                        },
                    )
            if delay > 0:
                time.sleep(delay)

            encoded = json.dumps(resp_body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            for k, v in extra_headers.items():
                self.send_header(k, v)
            self.end_headers()
            try:
                self.wfile.write(encoded)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/v1", state
    finally:
        server.shutdown()
        server.server_close()


def test_gateway_text_and_system_message(fake_openai_server):
    base_url, state = fake_openai_server
    state.push_response(
        200,
        {
            "choices": [{"message": {"role": "assistant", "content": "مرحباً من البوابة"}}],
        },
    )
    gw = PlatformLLMGateway(base_url=base_url, run_token="art_text_token_123", model="gpt-4o-mini")
    data = gw.chat_completion_sync(
        messages=[
            {"role": "system", "content": "You are a site analyst."},
            {"role": "user", "content": "Analyze home page."},
        ],
        temperature=0.1,
        max_tokens=256,
    )
    assert gw._extract_content_text(data) == "مرحباً من البوابة"
    assert len(state.calls) == 1
    call = state.calls[0]
    assert call["path"] == "/v1/chat/completions"
    assert call["auth"] == "Bearer art_text_token_123"
    assert call["body"]["model"] == "gpt-4o-mini"
    assert call["body"]["messages"][0]["role"] == "system"
    assert call["body"]["max_tokens"] == 256


def test_gateway_multimodal_images_and_json_mode(fake_openai_server):
    base_url, state = fake_openai_server
    png_bytes = b"\x89PNG\r\n\x1a\nfake-image-bytes"
    state.push_response(
        200,
        {
            "choices": [{"message": {"role": "assistant", "content": '{"visual_summary_arabic": "جيد"}'}}],
        },
    )
    gw = PlatformLLMGateway(base_url=base_url, run_token="art_vision_token", model="claude-3-5-sonnet")
    raw_text, duration_ms = gw.generate_multimodal_content_sync(
        prompt="Inspect screenshot",
        images=[{"data": png_bytes, "mime_type": "image/png"}],
        system_instruction="Strict JSON only.",
        json_mode=True,
    )
    assert json.loads(raw_text) == {"visual_summary_arabic": "جيد"}
    assert duration_ms >= 0.0
    assert len(state.calls) == 1
    body = state.calls[0]["body"]
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0] == {"role": "system", "content": "Strict JSON only."}
    user_parts = body["messages"][1]["content"]
    assert user_parts[0] == {"type": "text", "text": "Inspect screenshot"}
    expected_b64 = base64.b64encode(png_bytes).decode("ascii")
    assert user_parts[1] == {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{expected_b64}"},
    }


def test_gateway_429_rate_limit_and_quota_no_retry(fake_openai_server):
    base_url, state = fake_openai_server
    # Case 1: transient rate_limited with Retry-After header
    state.push_response(
        429,
        {"error": {"code": "rate_limited", "message": "Too many requests", "retry_after_seconds": 17}},
        headers={"Retry-After": "17"},
    )
    gw = PlatformLLMGateway(base_url=base_url, run_token="art_tok", max_retries=1)
    with pytest.raises(LLMRateLimitError) as exc_info:
        gw.chat_completion_sync([{"role": "user", "content": "ping"}])
    assert exc_info.value.retry_after == 17.0
    assert exc_info.value.status_code == 429
    # Must NOT retry 429
    assert len(state.calls) == 1

    # Case 2: daily quota exhausted
    state.push_response(
        429,
        {"error": {"code": "quota_exhausted", "message": "Daily quota exceeded"}},
        headers={"Retry-After": "3600"},
    )
    with pytest.raises(LLMQuotaExhaustedError) as q_exc:
        gw.chat_completion_sync([{"role": "user", "content": "ping2"}])
    assert q_exc.value.retry_after == 3600.0
    assert len(state.calls) == 2


def test_gateway_401_invalid_key_no_retry(fake_openai_server):
    base_url, state = fake_openai_server
    state.push_response(
        401,
        {"error": {"code": "invalid_key", "message": "Run token expired or revoked"}},
    )
    gw = PlatformLLMGateway(base_url=base_url, run_token="art_expired", max_retries=1)
    with pytest.raises(LLMInvalidKeyError) as exc_info:
        gw.chat_completion_sync([{"role": "user", "content": "hi"}])
    assert exc_info.value.status_code == 401
    assert len(state.calls) == 1


def test_gateway_5xx_retries_once_then_fails_or_recovers(fake_openai_server):
    base_url, state = fake_openai_server
    # 503 followed by 200 -> recovers after 1 retry
    state.push_response(503, {"error": {"code": "provider_unavailable", "message": "Temporary 503"}})
    state.push_response(200, {"choices": [{"message": {"role": "assistant", "content": "recovered"}}]})
    gw = PlatformLLMGateway(base_url=base_url, run_token="art_5xx", max_retries=1)
    res = gw.chat_completion_sync([{"role": "user", "content": "hello"}])
    assert gw._extract_content_text(res) == "recovered"
    assert len(state.calls) == 2

    # Two consecutive 502s -> raises LLMProviderUnavailableError after 2 total attempts
    state.push_response(502, {"error": {"code": "provider_unavailable", "message": "Bad gateway 1"}})
    state.push_response(502, {"error": {"code": "provider_unavailable", "message": "Bad gateway 2"}})
    with pytest.raises(LLMProviderUnavailableError):
        gw.chat_completion_sync([{"role": "user", "content": "hello2"}])
    assert len(state.calls) == 4


def test_gateway_timeout(fake_openai_server):
    base_url, state = fake_openai_server
    state.delay_seconds = 0.8
    gw = PlatformLLMGateway(base_url=base_url, run_token="art_timeout", timeout=0.15, max_retries=0)
    with pytest.raises(LLMTimeoutError):
        gw.chat_completion_sync([{"role": "user", "content": "slow"}])


def test_gateway_per_run_context_isolation_and_cancel(fake_openai_server):
    base_url, state = fake_openai_server

    def _run_with_ctx(run_id: str, token: str, model: str) -> str:
        ctx = RunLLMContext(run_id=run_id, run_token=token, llm_endpoint=base_url, model=model)
        tok = set_run_llm_context(ctx)
        try:
            # Verify contextvars.copy_context preserves per-run token in worker thread
            copied = contextvars.copy_context()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                res = pool.submit(
                    copied.run,
                    lambda: PlatformLLMGateway().chat_completion_sync([{"role": "user", "content": run_id}]),
                ).result()
            assert get_current_run_llm_context() is ctx
            return PlatformLLMGateway._extract_content_text(res)
        finally:
            reset_run_llm_context(tok)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_run_with_ctx, "run-a", "art_token_A", "model-a")
        f2 = pool.submit(_run_with_ctx, "run-b", "art_token_B", "model-b")
        assert f1.result() == '{"ok": true}'
        assert f2.result() == '{"ok": true}'

    seen_auths = {c["auth"] for c in state.calls}
    assert seen_auths == {"Bearer art_token_A", "Bearer art_token_B"}

    # Verify cancel_event aborts before sending HTTP request
    cancel_ctx = RunLLMContext(run_id="run-c", run_token="art_cancel", llm_endpoint=base_url, model="m")
    cancel_ctx.cancel_event.set()
    tok = set_run_llm_context(cancel_ctx)
    try:
        with pytest.raises(LLMRunCancelledError):
            PlatformLLMGateway().chat_completion_sync([{"role": "user", "content": "never"}])
        # Verify CrewAI get_llm() uses active run context without GEMINI_API_KEY
        llm = get_llm(settings=Settings(gemini_api_key=None, site_dna_service_mode=True))
        assert llm.model in ("m", "openai/m")
        assert llm.api_key == "art_cancel"
        assert llm.base_url == base_url
    finally:
        reset_run_llm_context(tok)
