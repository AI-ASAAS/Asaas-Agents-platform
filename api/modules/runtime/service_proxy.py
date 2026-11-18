import asyncio
import ipaddress
import json
import logging
import os
import re
import socket
import uuid
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Cookie, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

from config import settings
from modules.llm.gateway import llm_gateway
from modules.runtime.janitor import data_janitor
from modules.runtime.service_supervisor import site_dna_supervisor
from modules.runtime.session_limiter import service_session_limiter
from modules.runtime.session_store import service_session_store
from modules.runtime.token_registry import run_token_registry
from utils.client_ip import extract_client_ip

logger = logging.getLogger("runtime.service_proxy")

service_proxy_router = APIRouter(tags=["service-agent-proxy"])

# Strict (METHOD, REGEX) route allowlist for Site DNA service proxy (Decision S6).
# Everything not listed here (including /docs, /openapi.json, /dashboard/legacy,
# /api/v1/ready, /api/v1/discovery, /api/v1/visual/*, POST /api/v1/analysis/*) is DENIED with 404.
ALLOWED_ROUTES: list[tuple[set[str], re.Pattern[str]]] = [
    ({"GET"}, re.compile(r"^/api/v1/health$")),
    ({"GET"}, re.compile(r"^/api/v1/agents$")),
    ({"GET"}, re.compile(r"^/api/v1/agents/[a-z0-9_]+$")),
    ({"GET"}, re.compile(r"^/api/v1/dashboard/summary$")),
    ({"GET", "POST"}, re.compile(r"^/api/v1/runs$")),
    ({"GET"}, re.compile(r"^/api/v1/runs/[a-zA-Z0-9_-]+$")),
    ({"POST"}, re.compile(r"^/api/v1/runs/[a-zA-Z0-9_-]+/cancel$")),
    ({"GET"}, re.compile(r"^/api/v1/runs/[a-zA-Z0-9_-]+/events$")),
    ({"GET"}, re.compile(r"^/api/v1/runs/[a-zA-Z0-9_-]+/screenshots$")),
    ({"GET"}, re.compile(r"^/api/v1/runs/[a-zA-Z0-9_-]+/artifacts/screenshot$")),
    ({"GET"}, re.compile(r"^/api/v1/runs/[a-zA-Z0-9_-]+/findings$")),
    ({"GET"}, re.compile(r"^/api/v1/runs/[a-zA-Z0-9_-]+/recommendations$")),
    ({"GET"}, re.compile(r"^/api/v1/runs/[a-zA-Z0-9_-]+/ai-automation$")),
    ({"GET"}, re.compile(r"^/api/v1/runs/[a-zA-Z0-9_-]+/reports/[a-z0-9_]+$")),
    ({"POST"}, re.compile(r"^/api/v1/reports/final$")),
    ({"GET"}, re.compile(r"^/api/v1/reports/final/[a-zA-Z0-9_-]+$")),
    ({"GET"}, re.compile(r"^/api/v1/reports/final/[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+$")),
    ({"GET"}, re.compile(r"^/api/v1/reports/final/[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+/(download|preview|artifacts)$")),
    # Read-only stage views scoped strictly to caller's owned run_id (POST direct triggers are DENIED)
    ({"GET"}, re.compile(r"^/api/v1/analysis/competitors/[a-zA-Z0-9_-]+(/matrix)?$")),
    ({"GET"}, re.compile(r"^/api/v1/analysis/security-privacy/[a-zA-Z0-9_-]+(/headers)?$")),
    ({"GET"}, re.compile(r"^/api/v1/analysis/accessibility/[a-zA-Z0-9_-]+(/wcag)?$")),
    ({"GET"}, re.compile(r"^/api/v1/analysis/strategy/[a-zA-Z0-9_-]+(/(actions|conflicts|roadmap))?$")),
]

# Track active SSE subscribers & lifecycle watchdog tasks per run_id
_sse_subscriber_counts: dict[str, int] = {}
_orphan_cancel_tasks: dict[str, asyncio.Task] = {}
_wall_clock_tasks: dict[str, asyncio.Task] = {}
_active_run_sessions: dict[str, str] = {}  # run_id -> session_id (while active)

FORBIDDEN_HOSTS = frozenset({
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata.google",
    "instance-data",
    "169.254.169.254",
})


def _is_route_allowlisted(method: str, path: str) -> bool:
    upper = method.upper()
    for methods, pattern in ALLOWED_ROUTES:
        if upper in methods and pattern.match(path):
            return True
    return False


def _is_ip_non_public(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped:
        ip_obj = ip_obj.ipv4_mapped
    if not ip_obj.is_global:
        return True
    if (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    ):
        return True
    if str(ip_obj) in {"169.254.169.254", "100.100.100.200"}:
        return True
    return False


def validate_public_target_url(raw_url: str, resolve_dns: bool = True) -> tuple[str, str]:
    """
    Validates a visitor-supplied target URL per Decision S7:
    - Only http:// or https://
    - Public DNS hostname only (NO IPv4 or IPv6 literals)
    - Ports 80 or 443 only
    - No embedded credentials (user:pass@)
    - Platform's own domains and localhost/internal hosts denied
    - DNS must resolve exclusively to globally routable IPs
    Returns (cleaned_url, canonical_origin).
    """
    cleaned = (raw_url or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="رابط الموقع المستهدف مطلوب.")
    if len(cleaned) > 2048:
        raise HTTPException(status_code=400, detail="الرابط طويل جداً.")

    try:
        parts = urlsplit(cleaned)
    except Exception:
        raise HTTPException(status_code=400, detail="صيغة الرابط غير صالحة.")

    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="يُسمح فقط بروابط http:// أو https://.")

    if "@" in (parts.netloc or "") or parts.username or parts.password:
        raise HTTPException(status_code=400, detail="الروابط التي تحتوي على بيانات اعتماد مضمّنة غير مسموح بها.")

    hostname = (parts.hostname or "").strip().lower()
    if not hostname:
        raise HTTPException(status_code=400, detail="يجب أن يحتوي الرابط على اسم نطاق صالح.")

    # Test-harness fixture allowlist (only when explicitly opted-in via env in local eval runs)
    test_fixture_origin = os.environ.get("SITE_DNA_ALLOW_TEST_FIXTURE_ORIGIN", "").strip().lower()
    req_origin_full = f"{scheme}://{parts.netloc}".lower()
    if test_fixture_origin and req_origin_full == test_fixture_origin:
        return cleaned, req_origin_full

    # Reject raw IP literals (both IPv4 and IPv6)
    try:
        ipaddress.ip_address(hostname)
        raise HTTPException(
            status_code=400,
            detail="عناوين IP المباشرة غير مسموح بها. يرجى إدخال اسم نطاق عام (مثل example.com).",
        )
    except ValueError:
        pass

    # Reject port other than 80/443
    try:
        port = parts.port
    except ValueError:
        raise HTTPException(status_code=400, detail="رقم المنفذ غير صالح.")
    if port is not None and port not in (80, 443):
        raise HTTPException(status_code=400, detail="يُسمح فقط بالمنفذين القياسيين 80 و 443.")

    # Reject forbidden hosts and platform's own domains
    own_hosts = {h.lower() for h in settings.platform_own_hosts}
    if (
        hostname in FORBIDDEN_HOSTS
        or hostname in own_hosts
        or hostname.endswith(".internal")
        or hostname.endswith(".local")
        or "." not in hostname
    ):
        raise HTTPException(status_code=400, detail="هذا النطاق محظور ولا يمكن تحليله.")

    if resolve_dns:
        try:
            addr_info = socket.getaddrinfo(hostname, port or (443 if scheme == "https" else 80), socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror:
            raise HTTPException(status_code=400, detail="تعذر العثور على النطاق المستهدف عبر DNS.")

        if not addr_info:
            raise HTTPException(status_code=400, detail="لم يُرجع النطاق أي عنوان IP صالح.")

        for item in addr_info:
            ip_str = item[4][0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
            except ValueError:
                raise HTTPException(status_code=400, detail="عنوان IP غير صالح للنطاق المستهدف.")
            if _is_ip_non_public(ip_obj):
                raise HTTPException(
                    status_code=400,
                    detail="النطاق المستهدف يشير إلى عنوان شبكة خاص أو داخلي محظور.",
                )

    canonical_origin = f"{scheme}://{hostname}"
    return cleaned, canonical_origin


def _check_csrf(request: Request) -> None:
    """Fail-closed CSRF validation for state-changing cookie-authenticated requests (Decision S2)."""
    if request.method.upper() not in ("POST", "PUT", "DELETE", "PATCH"):
        return

    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    sec_fetch_site = (request.headers.get("sec-fetch-site") or "").lower()
    host = (request.headers.get("host") or "").lower()

    if origin:
        origin_host = origin.split("://")[-1].split("/")[0].lower()
        if not host or origin_host != host:
            logger.warning("CSRF check failed: origin '%s' != host '%s'", origin, host)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="فشل التحقق الأمني (CSRF): مصدر الطلب غير مصرح به.",
            )
        return

    if referer:
        ref_host = referer.split("://")[-1].split("/")[0].lower()
        if not host or ref_host != host:
            logger.warning("CSRF check failed: referer '%s' != host '%s'", referer, host)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="فشل التحقق الأمني (CSRF): مرجع الطلب غير مصرح به.",
            )
        return

    if sec_fetch_site == "same-origin":
        return

    # Reject state-changing cookie requests with missing Origin/Referer/Sec-Fetch-Site
    logger.warning("CSRF check failed: missing Origin/Referer on %s %s", request.method, request.url.path)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="فشل التحقق الأمني (CSRF): ترويسة Origin مطلوبة.",
    )


def _strip_sensitive_headers(request: Request) -> dict[str, str]:
    """Build safe forwarded headers — NEVER forwards Cookie, Authorization, or X-Provider-Key."""
    blocked = {
        "host",
        "content-length",
        "cookie",
        "authorization",
        "x-provider-key",
        "x-run-token",
        "x-llm-endpoint",
        "x-llm-model",
        "x-llm-provider",
    }
    return {k: v for k, v in request.headers.items() if k.lower() not in blocked}


async def _finalize_run(run_id: str, session_id: str | None = None, trigger_backend_cancel: bool = False) -> None:
    """Revokes run token, releases concurrency/origin slots, stops watchdogs, and optionally cancels on daemon."""
    s_id = session_id or _active_run_sessions.pop(run_id, None) or ""
    _active_run_sessions.pop(run_id, None)

    for task_map in (_wall_clock_tasks, _orphan_cancel_tasks):
        t = task_map.pop(run_id, None)
        if t and not t.done() and t is not asyncio.current_task():
            t.cancel()

    await run_token_registry.revoke_token_for_run(run_id)
    await service_session_limiter.release_run_slot(s_id, run_id)
    await service_session_store.mark_run_finished(run_id)

    if trigger_backend_cancel:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(f"{site_dna_supervisor.base_url}/api/v1/runs/{run_id}/cancel")
        except Exception as e:
            logger.debug("Best-effort cancel call for %s failed: %s", run_id, e)


def _schedule_wall_clock_watchdog(run_id: str, session_id: str, timeout_seconds: int) -> None:
    async def _watch():
        try:
            await asyncio.sleep(timeout_seconds)
            if run_id in _active_run_sessions:
                logger.warning("Service run %s hit wall-clock ceiling (%ds); forcing cancel & token revocation", run_id, timeout_seconds)
                await _finalize_run(run_id, session_id=session_id, trigger_backend_cancel=True)
        except asyncio.CancelledError:
            pass

    _wall_clock_tasks[run_id] = asyncio.create_task(_watch())


def _schedule_orphan_sse_watchdog(run_id: str, session_id: str, grace_seconds: int) -> None:
    existing = _orphan_cancel_tasks.pop(run_id, None)
    if existing and not existing.done():
        existing.cancel()

    async def _watch():
        try:
            await asyncio.sleep(grace_seconds)
            if run_id in _active_run_sessions and _sse_subscriber_counts.get(run_id, 0) <= 0:
                logger.info(
                    "Service run %s had 0 SSE subscribers for %ds (abandoned tab); auto-cancelling and revoking token",
                    run_id,
                    grace_seconds,
                )
                await _finalize_run(run_id, session_id=session_id, trigger_backend_cancel=True)
        except asyncio.CancelledError:
            pass

    _orphan_cancel_tasks[run_id] = asyncio.create_task(_watch())


# ─────────────────────────────────────────────────────────────
# Session Lifecycle Endpoints (Amendment to D1 / Decision S2)
# ─────────────────────────────────────────────────────────────

@service_proxy_router.post("/api/service-sessions/init")
async def init_service_session(
    request: Request,
    response: Response,
    x_provider_key: str | None = Header(None, alias="X-Provider-Key"),
):
    """
    Initialize an ephemeral IN-MEMORY session for a Tier-2 service agent.
    Key is validated via LLMGateway and kept strictly in server RAM.
    Session ID is delivered ONLY as an HttpOnly, SameSite=Strict cookie (never in JSON body).
    """
    _check_csrf(request)
    try:
        body = await request.json()
    except Exception:
        body = {}

    provider = str(body.get("provider") or request.headers.get("x-provider", "gemini")).lower().strip()
    model = str(body.get("model") or request.headers.get("x-model", "")).strip()
    key = (x_provider_key or body.get("api_key") or "").strip()

    if not key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="مفتاح API الخاص بمزود النموذج مطلوب لإنشاء الجلسة.",
        )
    if not model:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="يجب تحديد النموذج المطلوب قبل بدء الجلسة.",
        )

    client_ip = extract_client_ip(request)
    gateway = getattr(request.app.state, "llm_gateway", llm_gateway)
    try:
        await gateway.validate_key(provider, key)
    except Exception as e:
        logger.warning("Service session init failed: key validation rejected (%s)", type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="مفتاح API غير صالح أو تم رفضه من قبل المزود.",
        )

    session = await service_session_store.create_session(
        provider=provider,
        model=model,
        visitor_key=key,
        client_ip=client_ip,
    )

    response.set_cookie(
        key=service_session_store.COOKIE_NAME,
        value=session.session_id,
        max_age=int(session.max_ttl_seconds),
        httponly=True,
        samesite="strict",
        secure=(request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"),
        path="/",
    )

    # NEVER return session_id or api_key in JSON body
    return {
        "status": "ok",
        "provider": session.provider,
        "model": session.model,
        "expires_in": int(session.sliding_ttl_seconds),
        "max_ttl_seconds": int(session.max_ttl_seconds),
    }


@service_proxy_router.get("/api/service-sessions/me")
async def get_current_service_session(
    request: Request,
    asaas_service_session: str | None = Cookie(None),
):
    """Returns active session metadata (NEVER session_id or api_key)."""
    if not asaas_service_session:
        return {"active": False}

    session = await service_session_store.get_session(asaas_service_session, touch=False)
    if not session:
        return {"active": False}

    client_ip = extract_client_ip(request)
    daily_rem = await service_session_limiter.get_daily_remaining(client_ip)

    return {
        "active": True,
        "provider": session.provider,
        "model": session.model,
        "remaining_ttl_seconds": int(session.get_remaining_ttl()),
        "runs_count": len(session.runs),
        "daily_remaining": daily_rem,
        "limits": {
            "max_pages_per_run": settings.service_max_pages_per_run,
            "max_wall_clock_seconds": settings.service_max_wall_clock_seconds,
            "daily_runs_per_ip": settings.service_daily_runs_per_ip,
            "concurrent_global": settings.service_max_concurrent_global,
        },
    }


@service_proxy_router.get("/api/service-sessions/usage")
async def get_service_session_usage(
    asaas_service_session: str | None = Cookie(None),
):
    """Feeds the sub-app's usage chip with live accumulated requests/tokens/cost for this session."""
    if not asaas_service_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="لا توجد جلسة نشطة.")

    session = await service_session_store.get_session(asaas_service_session, touch=False)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="انتهت صلاحية الجلسة.")

    usage = await run_token_registry.get_runs_usage_aggregate(
        run_ids=set(session.runs),
        provider=session.provider,
        model=session.model,
    )
    usage["runs_count"] = len(session.runs)
    return usage


@service_proxy_router.post("/api/service-sessions/logout")
async def logout_service_session(
    request: Request,
    response: Response,
    asaas_service_session: str | None = Cookie(None),
):
    """Deletes session from RAM, cancels active runs, revokes tokens, purges artifacts, and clears cookie."""
    _check_csrf(request)
    if asaas_service_session:
        owned_runs = await service_session_store.delete_session(asaas_service_session)
        runs_dir = site_dna_supervisor.resolve_data_dir()
        for r_id in owned_runs:
            await _finalize_run(r_id, session_id=asaas_service_session, trigger_backend_cancel=True)
            await data_janitor._cancel_and_purge_run(asaas_service_session, r_id, runs_dir)
        await run_token_registry.forget_finalized_usage(owned_runs)

    response.delete_cookie(key=service_session_store.COOKIE_NAME, path="/")
    return {"status": "logged_out"}


# ─────────────────────────────────────────────────────────────
# Proxied Agent Endpoints: /agents-api/{slug}/api/v1/{path:path}
# ─────────────────────────────────────────────────────────────

@service_proxy_router.api_route(
    "/agents-api/{slug}/api/v1/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def proxy_service_agent(
    slug: str,
    path: str,
    request: Request,
    asaas_service_session: str | None = Cookie(None),
):
    if slug != "site-dna":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service agent not found.")

    full_path = f"/api/v1/{path}"

    # 1. Strict Route & Method Allowlist
    if not _is_route_allowlisted(request.method, full_path):
        logger.warning("Blocked non-allowlisted route on %s: %s %s", slug, request.method, full_path)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found.")

    # 1b. Ensure supervised service backend is running & healthy (auto-starts/recovers if needed)
    if settings.site_dna_auto_start and not os.environ.get("PYTEST_CURRENT_TEST"):
        ready = await site_dna_supervisor.ensure_running()
        if not ready:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="خدمة بصمة الموقع الخلفية قيد التشغيل أو غير متاحة حالياً. يرجى المحاولة بعد ثوانٍ.",
            )

    backend_base_url = site_dna_supervisor.base_url
    backend_url = f"{backend_base_url}{full_path}"

    # 2. Public read-only endpoints (/health, /agents, /agents/{id})
    if (full_path == "/api/v1/health" or full_path == "/api/v1/agents" or full_path.startswith("/api/v1/agents/")) and request.method == "GET":
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(backend_url, params=request.query_params)
                return JSONResponse(resp.json(), status_code=resp.status_code)
        except Exception:
            raise HTTPException(status_code=503, detail="خدمة بصمة الموقع غير متاحة حالياً.")

    # 3. Require valid HttpOnly session cookie
    if not asaas_service_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="يرجى إعداد مفتاح API واختيار النموذج من صفحة الوكيل أولاً.",
        )

    session = await service_session_store.get_session(asaas_service_session)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="انتهت صلاحية جلسة العمل المؤقتة. يرجى العودة لصفحة الوكيل وإعادة التفعيل.",
        )

    # 4. Enforce CSRF on state-changing requests
    _check_csrf(request)
    client_ip = extract_client_ip(request)
    session_id = session.session_id

    # 5. Handle POST /api/v1/runs (Run Submission)
    if full_path == "/api/v1/runs" and request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="بيانات الطلب JSON غير صالحة.")

        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="بيانات الطلب غير صالحة.")

        # S7: Require explicit consent confirmation
        if not body.get("consent_confirmed", False):
            raise HTTPException(
                status_code=400,
                detail="يجب تأكيد الإقرار بالتصريح لتحليل الموقع العام قبل بدء الفحص.",
            )

        # S7: Strict target URL validation (no IP literals, public DNS only, ports 80/443, no platform hosts)
        cleaned_url, canonical_origin = validate_public_target_url(str(body.get("url", "")))
        body["url"] = cleaned_url

        # Validate any manually supplied competitor URLs against same policy & cap at 3
        comp_urls = body.get("competitor_urls") or []
        if isinstance(comp_urls, list) and comp_urls:
            validated_comps = []
            for cu in comp_urls[:3]:
                v_cu, _ = validate_public_target_url(str(cu))
                validated_comps.append(v_cu)
            body["competitor_urls"] = validated_comps

        # Clamp page budgets & forbid 50-page full_site_scan in public demo
        req_max_pages = int(body.get("max_pages") or 5)
        body["max_pages"] = max(1, min(req_max_pages, settings.service_max_pages_per_run))
        body["full_site_scan"] = False

        # S6: Check disk quotas before starting
        sess_ok, _ = await data_janitor.check_session_disk_quota(session_id)
        if not sess_ok:
            raise HTTPException(status_code=507, detail="تم تجاوز حد المساحة التخزينية المخصص للجلسة الحالية.")
        glob_ok, _ = await data_janitor.check_global_disk_quota()
        if not glob_ok:
            await data_janitor.enforce_disk_quotas(site_dna_supervisor.resolve_data_dir())

        # Mint unguessable UUIDv4 run_id BEFORE contacting backend
        run_id = f"run-{uuid.uuid4().hex}"

        # Atomically acquire concurrency, daily, and target-origin slots (counted ONCE)
        await service_session_limiter.acquire_run_slot(
            session_id=session_id,
            run_id=run_id,
            client_ip=client_ip,
            target_origin=canonical_origin,
        )

        # Mint ephemeral per-run token BEFORE forwarding so Site DNA receives it immediately
        token_ttl = float(settings.service_max_wall_clock_seconds + 120)
        run_token = await run_token_registry.create_token(
            run_id=run_id,
            provider=session.provider,
            model=session.model,
            visitor_key=session.visitor_key,
            max_output_tokens=settings.platform_max_output_tokens,
            ttl_seconds=token_ttl,
            session_id=session_id,
        )

        fwd_headers = {
            "Content-Type": "application/json",
            "X-Run-Id": run_id,
            "X-Run-Token": run_token,
            "X-LLM-Endpoint": settings.agent_loopback_base_url,
            "X-LLM-Model": session.model,
            "X-LLM-Provider": session.provider,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(backend_url, json=body, headers=fwd_headers)
        except Exception as e:
            await run_token_registry.revoke_token_for_run(run_id)
            await service_session_limiter.rollback_failed_start(run_id)
            logger.error("Failed to forward run submission to %s: %s", slug, e)
            raise HTTPException(status_code=502, detail="تعذر الاتصال بخدمة بصمة الموقع الخلفية.")

        if resp.status_code not in (200, 201):
            await run_token_registry.revoke_token_for_run(run_id)
            await service_session_limiter.rollback_failed_start(run_id)
            try:
                return JSONResponse(resp.json(), status_code=resp.status_code)
            except Exception:
                return Response(content=resp.content, status_code=resp.status_code)

        result_data = resp.json()
        real_run_id = result_data.get("run_id") or run_id
        await service_session_store.associate_run(session_id, real_run_id)
        _active_run_sessions[real_run_id] = session_id

        # Start wall-clock ceiling watchdog and initial SSE-attach grace watchdog
        _schedule_wall_clock_watchdog(real_run_id, session_id, settings.service_max_wall_clock_seconds)
        _schedule_orphan_sse_watchdog(real_run_id, session_id, settings.service_sse_orphan_cancel_seconds)

        logger.info("Started Site DNA run %s (provider=%s, model=%s)", real_run_id, session.provider, session.model)
        return JSONResponse(result_data, status_code=resp.status_code)

    # 6. Handle GET /api/v1/runs -> Filter strictly to caller's owned runs
    if full_path == "/api/v1/runs" and request.method == "GET":
        owned = await service_session_store.get_owned_runs(session_id)
        if not owned:
            return JSONResponse({"items": [], "total": 0, "page": 1, "page_size": 20, "pages_count": 1})

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(backend_url, params={"page": 1, "page_size": 100})
            if resp.status_code != 200:
                return JSONResponse(resp.json(), status_code=resp.status_code)
            data = resp.json()
            q = (request.query_params.get("query") or "").lower().strip()
            st_filter = (request.query_params.get("status") or "").lower().strip()
            scoped = []
            for item in data.get("items", []):
                if item.get("run_id") not in owned:
                    continue
                if q and q not in str(item.get("url", "")).lower() and q not in str(item.get("run_id", "")).lower():
                    continue
                if st_filter and st_filter != "all" and str(item.get("status", "")).lower() != st_filter:
                    continue
                scoped.append(item)
            return JSONResponse({
                "items": scoped,
                "total": len(scoped),
                "page": 1,
                "page_size": len(scoped) or 20,
                "pages_count": 1,
            })

    # 7. Handle GET /api/v1/dashboard/summary -> Compute STRICTLY from caller's session runs
    if full_path == "/api/v1/dashboard/summary" and request.method == "GET":
        owned = await service_session_store.get_owned_runs(session_id)
        agent_readiness: dict[str, Any] = {}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                ag_resp = await client.get(f"{backend_base_url}/api/v1/agents")
                if ag_resp.status_code == 200:
                    for a in ag_resp.json():
                        agent_readiness[a["id"]] = {
                            "phase": a.get("phase"),
                            "name": a.get("name"),
                            "name_ar": a.get("name_ar"),
                            "status": a.get("runtime_availability", "ready"),
                            "can_execute": a.get("can_execute", True),
                        }
                session_runs: list[dict[str, Any]] = []
                for rid in owned:
                    r_resp = await client.get(f"{backend_base_url}/api/v1/runs/{rid}")
                    if r_resp.status_code == 200:
                        session_runs.append(r_resp.json())
        except Exception:
            session_runs = []

        session_runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        completed = sum(1 for r in session_runs if r.get("status") in ("completed", "partial", "ai_blocked"))
        running = sum(1 for r in session_runs if r.get("status") in ("running", "queued", "created"))
        failed = sum(1 for r in session_runs if r.get("status") == "failed")
        total_findings = sum(int(r.get("total_findings") or 0) for r in session_runs)
        total_recs = sum(int(r.get("total_recommendations") or 0) for r in session_runs)
        recent = [
            {
                "run_id": r.get("run_id"),
                "url": r.get("url"),
                "status": r.get("status"),
                "overall_score": r.get("overall_score"),
                "stages_completed": sum(
                    1 for s in (r.get("stages") or {}).values() if s.get("status") in ("completed", "partial", "ai_blocked")
                ),
                "total_stages": len(r.get("stages") or {}),
                "created_at": r.get("created_at"),
            }
            for r in session_runs[:10]
        ]

        return JSONResponse({
            "total_runs": len(session_runs),
            "completed_runs": completed,
            "running_runs": running,
            "failed_runs": failed,
            "total_findings": total_findings,
            "total_recommendations": total_recs,
            "recent_runs": recent,
            "agent_readiness": agent_readiness,
        })

    # 8. Enforce Run Ownership across ALL run-scoped, report-scoped, and stage-read endpoints
    target_run_id: str | None = None
    for pat in (
        r"^/api/v1/runs/([a-zA-Z0-9_-]+)",
        r"^/api/v1/reports/final/([a-zA-Z0-9_-]+)",
        r"^/api/v1/analysis/[^/]+/([a-zA-Z0-9_-]+)",
    ):
        m = re.match(pat, full_path)
        if m:
            target_run_id = m.group(1)
            break

    if target_run_id:
        if not await service_session_store.has_run(session_id, target_run_id):
            logger.warning("Denied cross-session access to run '%s' from session", target_run_id)
            raise HTTPException(status_code=404, detail="الجولة غير موجودة في جلستك الحالية.")

    # 9. Handle POST /api/v1/reports/final -> Check crawl_run_id ownership in JSON payload
    if full_path == "/api/v1/reports/final" and request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="بيانات الطلب غير صالحة.")
        crawl_id = str(body.get("crawl_run_id", "")).strip()
        if not crawl_id or not await service_session_store.has_run(session_id, crawl_id):
            raise HTTPException(status_code=404, detail="الجولة غير موجودة في جلستك الحالية.")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(backend_url, json=body)
            return Response(content=resp.content, status_code=resp.status_code, media_type=resp.headers.get("content-type", "application/json"))

    # 10. Handle POST /api/v1/runs/{id}/cancel
    if full_path.endswith("/cancel") and request.method == "POST" and target_run_id:
        await _finalize_run(target_run_id, session_id=session_id, trigger_backend_cancel=False)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(backend_url)
            try:
                return JSONResponse(resp.json(), status_code=resp.status_code)
            except Exception:
                return Response(content=resp.content, status_code=resp.status_code)

    # 11. Handle SSE: GET /api/v1/runs/{id}/events (with orphan-tab tracking & terminal token revocation)
    if full_path.endswith("/events") and request.method == "GET" and target_run_id:
        _sse_subscriber_counts[target_run_id] = _sse_subscriber_counts.get(target_run_id, 0) + 1
        orphan_t = _orphan_cancel_tasks.pop(target_run_id, None)
        if orphan_t and not orphan_t.done():
            orphan_t.cancel()

        client = httpx.AsyncClient(timeout=None)
        req = client.build_request("GET", backend_url)
        try:
            r = await client.send(req, stream=True)
        except Exception:
            _sse_subscriber_counts[target_run_id] = max(0, _sse_subscriber_counts.get(target_run_id, 1) - 1)
            await client.aclose()
            raise HTTPException(status_code=502, detail="تعذر الاتصال ببث أحداث الوكيل.")

        async def sse_generator():
            terminal_seen = False
            try:
                async for line in r.aiter_lines():
                    if line.startswith("event:"):
                        ev_name = line.split(":", 1)[1].strip()
                        if ev_name in ("run.completed", "run.failed", "run.cancelled", "done"):
                            terminal_seen = True
                    yield f"{line}\n"
            finally:
                await r.aclose()
                await client.aclose()
                remaining = max(0, _sse_subscriber_counts.get(target_run_id, 1) - 1)
                if remaining == 0:
                    _sse_subscriber_counts.pop(target_run_id, None)
                else:
                    _sse_subscriber_counts[target_run_id] = remaining

                if terminal_seen:
                    await _finalize_run(target_run_id, session_id=session_id, trigger_backend_cancel=False)
                elif remaining == 0 and target_run_id in _active_run_sessions:
                    _schedule_orphan_sse_watchdog(
                        target_run_id,
                        session_id,
                        settings.service_sse_orphan_cancel_seconds,
                    )

        return StreamingResponse(
            sse_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    # 12. Handle GET /api/v1/runs/{id}/screenshots -> Rewrite api_url prefix for sub-app mount
    if full_path.endswith("/screenshots") and request.method == "GET":
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(backend_url)
            if resp.status_code != 200:
                return Response(content=resp.content, status_code=resp.status_code)
            items = resp.json()
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and isinstance(item.get("api_url"), str):
                        if item["api_url"].startswith("/api/v1/"):
                            item["api_url"] = f"/agents-api/{slug}{item['api_url']}"
            return JSONResponse(items)

    # 13. Handle Report Downloads & Previews with strict security headers
    if "/reports/final/" in full_path and (full_path.endswith("/download") or full_path.endswith("/preview")):
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(backend_url, params=request.query_params)
            if resp.status_code != 200:
                return Response(content=resp.content, status_code=resp.status_code)
            content_type = resp.headers.get("content-type", "application/octet-stream")
            headers = {
                "Content-Type": content_type,
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, no-cache, no-store",
            }
            if full_path.endswith("/download"):
                headers["Content-Disposition"] = resp.headers.get(
                    "content-disposition",
                    'attachment; filename="site-dna-report.pdf"',
                )
                headers["Content-Security-Policy"] = "default-src 'none'"
                headers["X-Frame-Options"] = "DENY"
            else:
                # HTML Preview in sandboxed iframe: zero scripts, inlined styles/images/fonts only
                headers["Content-Security-Policy"] = (
                    "default-src 'none'; "
                    "style-src 'unsafe-inline'; "
                    "img-src data:; "
                    "font-src data:; "
                    "frame-ancestors 'self'; "
                    "base-uri 'none'; "
                    "form-action 'none'"
                )
            return Response(content=resp.content, status_code=resp.status_code, headers=headers)

    # 14. Generic Forwarder for Remaining Allowlisted GET Endpoints (e.g. GET /runs/{id}, findings, recs, screenshot file)
    async with httpx.AsyncClient(timeout=20.0) as client:
        body_bytes = await request.body()
        resp = await client.request(
            method=request.method,
            url=backend_url,
            content=body_bytes if body_bytes else None,
            headers=_strip_sensitive_headers(request),
            params=request.query_params,
        )
        # If GET /runs/{id} reveals terminal status, ensure token & slots are released even without SSE
        if target_run_id and full_path == f"/api/v1/runs/{target_run_id}" and resp.status_code == 200:
            try:
                run_data = resp.json()
                if run_data.get("status") in ("completed", "partial", "ai_blocked", "failed", "cancelled"):
                    if target_run_id in _active_run_sessions:
                        await _finalize_run(target_run_id, session_id=session_id, trigger_backend_cancel=False)
            except Exception:
                pass

        resp_headers = {
            k: v
            for k, v in resp.headers.items()
            if k.lower() not in ("content-encoding", "transfer-encoding", "connection", "content-length", "set-cookie")
        }
        return Response(content=resp.content, status_code=resp.status_code, headers=resp_headers)
