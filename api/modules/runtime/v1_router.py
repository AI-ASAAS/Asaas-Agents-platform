import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Header, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from modules.llm.errors import LLMBaseError
from modules.llm.schemas import ChatCompletionRequest, ChatMessage
from .token_registry import run_token_registry

logger = logging.getLogger("runtime.v1_endpoint")

v1_router = APIRouter(prefix="/v1", tags=["local-v1-proxy"])

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def _get_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    if len(parts) == 1:
        return parts[0]
    return None


@v1_router.post("/chat/completions")
async def local_chat_completions(
    request: Request,
    authorization: str | None = Header(None),
):
    # 1. Reverse-Proxy Egress check: internal agents connect directly via loopback
    # If any proxy header is present, the request arrived via a reverse proxy (untrusted external path)
    proxy_headers = ("x-forwarded-for", "x-real-ip", "x-forwarded-proto", "x-forwarded-host")
    if any(h in request.headers for h in proxy_headers):
        logger.warning("Blocked proxied attempt to internal endpoint /v1/chat/completions")
        return JSONResponse(
            {"error": {"message": "Access denied: internal local proxy only, proxied requests forbidden.", "type": "access_denied"}},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # 2. Local loopback check: ensure caller is loopback only
    client_host = request.client.host if request.client else "127.0.0.1"
    if client_host not in LOOPBACK_HOSTS and not client_host.startswith("127."):
        logger.warning("Blocked non-loopback attempt to /v1/chat/completions from %s", client_host)
        return JSONResponse(
            {"error": {"message": "Access denied: local proxy loopback only.", "type": "access_denied"}},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # 3. Token authentication
    token = _get_bearer_token(authorization)
    if not token:
        return JSONResponse(
            {
                "error": {
                    "message": "Missing Bearer run token.",
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                }
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    ctx = await run_token_registry.get_context(token)
    if not ctx:
        logger.warning("Rejected invalid/expired run token")
        return JSONResponse(
            {
                "error": {
                    "message": "Invalid, expired, or revoked agent run token.",
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                }
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    # 3. Parse and strictly normalize request
    try:
        raw_body = await request.json()
    except Exception:
        return JSONResponse(
            {"error": {"message": "Invalid JSON payload.", "type": "invalid_request_error"}},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Enforce provider and model: the agent CANNOT switch to another model
    raw_body["model"] = ctx.model

    # Clamp max_tokens to run context ceiling
    if "max_tokens" in raw_body and isinstance(raw_body["max_tokens"], int):
        raw_body["max_tokens"] = min(raw_body["max_tokens"], ctx.max_output_tokens)
    else:
        raw_body["max_tokens"] = ctx.max_output_tokens

    is_streaming = bool(raw_body.get("stream", False))

    try:
        chat_req = ChatCompletionRequest.model_validate(raw_body)
    except Exception as e:
        return JSONResponse(
            {"error": {"message": f"Validation error: {e}", "type": "invalid_request_error"}},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    gateway = request.app.state.llm_gateway

    # 4. Handle Streaming vs Non-Streaming
    if is_streaming:
        async def stream_generator():
            try:
                async for line in gateway.chat_completion_stream(ctx.provider, ctx.visitor_key, chat_req):
                    yield line
            except LLMBaseError as exc:
                err_chunk = {
                    "error": {
                        "message": exc.message_ar,
                        "type": exc.code,
                        "code": exc.code,
                    }
                }
                yield f"data: {json.dumps(err_chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                logger.error("Error in streaming agent LLM call: %s", e)
                err_chunk = {
                    "error": {
                        "message": "حدث خطأ أثناء بث الاستجابة.",
                        "type": "internal_error",
                    }
                }
                yield f"data: {json.dumps(err_chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    # Non-streaming call
    try:
        response = await gateway.chat_completion(ctx.provider, ctx.visitor_key, chat_req)
        # Record usage on the run token registry
        await run_token_registry.record_usage(ctx.run_id, response.usage)

        out_choices = []
        for ch in response.choices:
            out_choices.append({
                "index": ch.index,
                "message": {
                    "role": ch.message.role,
                    "content": ch.message.content,
                    "tool_calls": ch.message.tool_calls,
                },
                "finish_reason": ch.finish_reason,
            })

        return JSONResponse({
            "id": response.id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": ctx.model,
            "choices": out_choices,
            "usage": response.usage.model_dump(),
        })
    except LLMBaseError as exc:
        err_headers = {}
        if getattr(exc, "retry_after_seconds", None) is not None:
            err_headers["Retry-After"] = str(int(exc.retry_after_seconds))
        return JSONResponse(
            {
                "error": {
                    "message": exc.message_ar,
                    "type": exc.code,
                    "code": exc.code,
                    "retry_after_seconds": getattr(exc, "retry_after_seconds", None),
                }
            },
            status_code=exc.status_code,
            headers=err_headers or None,
        )
    except Exception as exc:
        logger.error("Unhandled error in local chat completions: %s", exc)
        return JSONResponse(
            {
                "error": {
                    "message": "فشل الاتصال بالنموذج.",
                    "type": "provider_unavailable",
                }
            },
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@v1_router.get("/models")
async def local_list_models(
    request: Request,
    authorization: str | None = Header(None),
):
    proxy_headers = ("x-forwarded-for", "x-real-ip", "x-forwarded-proto", "x-forwarded-host")
    if any(h in request.headers for h in proxy_headers):
        logger.warning("Blocked proxied attempt to internal endpoint /v1/models")
        return JSONResponse(
            {"error": {"message": "Access denied: internal local proxy only.", "type": "access_denied"}},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    client_host = request.client.host if request.client else "127.0.0.1"
    if client_host not in LOOPBACK_HOSTS and not client_host.startswith("127."):
        logger.warning("Blocked non-loopback attempt to /v1/models from %s", client_host)
        return JSONResponse(
            {"error": {"message": "Access denied: local proxy loopback only.", "type": "access_denied"}},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    token = _get_bearer_token(authorization)
    if not token:
        return JSONResponse({"error": {"message": "Missing run token."}}, status_code=status.HTTP_401_UNAUTHORIZED)

    ctx = await run_token_registry.get_context(token)
    if not ctx:
        return JSONResponse({"error": {"message": "Invalid run token."}}, status_code=status.HTTP_401_UNAUTHORIZED)

    return JSONResponse({
        "object": "list",
        "data": [
            {
                "id": ctx.model,
                "object": "model",
                "owned_by": ctx.provider,
                "permission": [],
            }
        ],
    })
