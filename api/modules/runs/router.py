import asyncio
import json
import logging
import secrets
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse

from config import settings
from database import Database
from modules.catalog.repository import CatalogRepository
from modules.llm.errors import RateLimitedError
from modules.runtime.runner import AgentRunner
from modules.security.rate_limiter import security_limiter
from utils.client_ip import extract_client_ip
from .concurrency import concurrency_manager

logger = logging.getLogger("runs.router")

runs_router = APIRouter(tags=["runs"])


def _find_agent_dir(slug: str) -> Path | None:
    """Locates the agent directory on disk by slug."""
    base = settings.resolved_agents_dir
    # First check direct directory
    direct = base / slug
    if direct.exists() and (direct / "agent.manifest.json").exists() or (direct / "manifest.json").exists():
        return direct

    # Check all subdirectories
    for manifest_path in list(base.glob("*/agent.manifest.json")) + list(base.glob("*/manifest.json")):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if data.get("slug") == slug:
                return manifest_path.parent
        except Exception:
            continue
    return None


@runs_router.post("/api/agents/{slug}/run")
async def run_agent(
    slug: str,
    request: Request,
    x_provider: str | None = Header(None, alias="X-Provider"),
    x_provider_key: str | None = Header(None, alias="X-Provider-Key"),
    x_model: str | None = Header(None, alias="X-Model"),
):
    # 1. Validate Provider Headers
    if not x_provider or not x_provider_key:
        return JSONResponse(
            {
                "message": "مزود الخدمة أو مفتاح API غير متوفر في الترويسات (X-Provider, X-Provider-Key).",
                "code": "missing_provider_credentials",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    provider = x_provider.lower().strip()
    visitor_key = x_provider_key.strip()

    # 2. Retrieve Agent Manifest from Catalog
    repo = CatalogRepository()
    agent_record = await repo.get_agent_by_slug(slug)
    if not agent_record:
        return JSONResponse(
            {"message": f"الوكيل '{slug}' غير موجود في الكتالوج.", "code": "agent_not_found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if agent_record.get("status") != "ready":
        agent_name = agent_record.get("name_ar") or slug
        return JSONResponse(
            {
                "message": f"الوكيل '{agent_name}' ليس جاهزاً للتجربة المباشرة (الحالة: {agent_record.get('status')}).",
                "code": "agent_not_ready",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Validate provider eligibility for this agent
    raw_allowed = agent_record.get("allowed_providers") or []
    if isinstance(raw_allowed, str):
        try:
            raw_allowed = json.loads(raw_allowed)
        except Exception:
            raw_allowed = []
    allowed_providers = [str(p).lower() for p in raw_allowed]
    if allowed_providers and provider not in allowed_providers:
        return JSONResponse(
            {
                "message": f"المزود '{provider}' غير مدعوم لهذا الوكيل. المزودات المدعومة: {', '.join(allowed_providers)}.",
                "code": "unsupported_provider",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    agent_dir = _find_agent_dir(slug)
    if not agent_dir:
        return JSONResponse(
            {"message": f"مجلد ملفات الوكيل غير موجود على الخادم: {slug}", "code": "agent_dir_not_found"},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # 3. Parse Request Body (JSON or Multipart Form)
    content_type = request.headers.get("content-type", "").lower()
    message = ""
    parameters: dict[str, Any] = {}
    chosen_model = x_model or ""
    uploaded_files: list[tuple[str, str, bytes]] = []

    if "multipart/form-data" in content_type:
        form = await request.form()
        message = str(form.get("message", "")).strip()
        if "model" in form and not chosen_model:
            chosen_model = str(form.get("model", "")).strip()
        params_raw = form.get("parameters")
        if params_raw and isinstance(params_raw, str):
            try:
                parameters = json.loads(params_raw)
            except Exception:
                parameters = {}

        # Extract files
        for key in form:
            val = form[key]
            if isinstance(val, UploadFile):
                file_bytes = await val.read()
                mime = val.content_type or "application/octet-stream"
                filename = val.filename or f"upload_{key}"
                uploaded_files.append((filename, mime, file_bytes))
    else:
        try:
            body = await request.json()
            message = str(body.get("message", "")).strip()
            parameters = body.get("parameters") or {}
            if "model" in body and not chosen_model:
                chosen_model = str(body.get("model", "")).strip()
        except Exception:
            return JSONResponse(
                {"message": "بيانات الطلب غير صالحة.", "code": "invalid_json"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    if not chosen_model:
        return JSONResponse(
            {"message": "يجب تحديد النموذج المراد استخدامه للتجربة.", "code": "missing_model"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # 4. Enforce Abuse Protection & Concurrency Caps
    client_ip = extract_client_ip(request)
    try:
        security_limiter.check_run_start(request)
    except RateLimitedError as rle:
        return JSONResponse(
            {
                "message": rle.message_ar,
                "code": "rate_limited",
                "retry_after_seconds": rle.retry_after_seconds,
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(int(rle.retry_after_seconds or 60))},
        )

    acquired = await concurrency_manager.acquire(client_ip)
    if not acquired:
        return JSONResponse(
            {
                "message": "الخادم مشغول حالياً أو تجاوزت الحد الأقصى للتجارب المتزامنة المسموح بها.",
                "code": "concurrency_limit_exceeded",
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    security_limiter.record_run_started(client_ip)

    # 5. Initialize Run & Cancel Event
    run_id = f"run_{secrets.token_hex(12)}"
    cancel_event = asyncio.Event()
    await concurrency_manager.register_run(run_id, cancel_event)

    raw_limits = agent_record.get("limits") or {}
    if isinstance(raw_limits, str):
        try:
            raw_limits = json.loads(raw_limits)
        except Exception:
            raw_limits = {}

    runner = AgentRunner(
        manifest_data={"slug": agent_record["slug"], "limits": raw_limits},
        agent_dir=agent_dir,
        provider=provider,
        model=chosen_model,
        visitor_key=visitor_key,
    )

    # 6. Stream SSE Events
    async def sse_event_stream():
        is_success = False
        try:
            await CatalogRepository.record_run_started(slug)
            yield f"event: status\ndata: {json.dumps({'state': 'starting', 'detail': 'بدء تشغيل الوكيل...'}, ensure_ascii=False)}\n\n"

            async for event_item in runner.run(
                run_id=run_id,
                message=message,
                parameters=parameters,
                uploaded_files=uploaded_files,
                cancel_event=cancel_event,
            ):
                ev_name = event_item["event"]
                if ev_name == "result":
                    is_success = True

                # Detect client disconnect
                if await request.is_disconnected():
                    logger.info("Client disconnected during run_id=%s, cancelling child process", run_id)
                    cancel_event.set()
                    break

                ev_data = json.dumps(event_item["data"], ensure_ascii=False)
                yield f"event: {ev_name}\ndata: {ev_data}\n\n"

        finally:
            await CatalogRepository.record_run_outcome(slug, success=is_success)
            await concurrency_manager.unregister_run(run_id)
            await concurrency_manager.release(client_ip)

    return StreamingResponse(
        sse_event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@runs_router.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    cancelled = await concurrency_manager.cancel_run(run_id)
    if not cancelled:
        return JSONResponse(
            {"message": "التجربة غير موجودة أو انتهت بالفعل.", "code": "run_not_found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return {"status": "cancelled", "run_id": run_id}
