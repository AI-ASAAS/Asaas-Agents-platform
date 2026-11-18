import asyncio
from contextlib import asynccontextmanager
import logging
import os
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings
from database import Database
from migrations import run_migrations
from modules.catalog import catalog_router, load_and_seed_agents
from modules.llm import LLMBaseError, LLMGateway
from modules.providers import ProvidersService, providers_router
from modules.runs import runs_router
from modules.runtime import (
    AgentRunner,
    cleanup_stale_run_dirs,
    data_janitor,
    get_sandbox_mode,
    service_proxy_router,
    site_dna_supervisor,
    v1_router,
)
from utils import setup_redaction_logging, verify_redaction_filter

# Set up logging with redaction
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
setup_redaction_logging()
logger = logging.getLogger("api.main")

# Error dictionaries (Arabic default, English fallback)
ERROR_MESSAGES = {
    "ar": {
        400: ("الطلب غير صالح.", "BAD_REQUEST"),
        404: ("المسار غير موجود.", "NOT_FOUND"),
        405: ("طريقة الطلب غير مدعومة.", "METHOD_NOT_ALLOWED"),
        413: ("حجم الطلب تجاوز الحد الأقصى المسموح به.", "PAYLOAD_TOO_LARGE"),
        422: ("بيانات الطلب غير صالحة.", "VALIDATION_ERROR"),
        500: ("حدث خطأ داخلي في الخادم. يرجى المحاولة لاحقاً.", "INTERNAL_SERVER_ERROR"),
    },
    "en": {
        400: ("Bad request.", "BAD_REQUEST"),
        404: ("Endpoint not found.", "NOT_FOUND"),
        405: ("Method not allowed.", "METHOD_NOT_ALLOWED"),
        413: ("Payload too large.", "PAYLOAD_TOO_LARGE"),
        422: ("Validation error.", "VALIDATION_ERROR"),
        500: ("An internal server error occurred. Please try again later.", "INTERNAL_SERVER_ERROR"),
    },
}


def get_error_response(status_code: int, custom_message: str | None = None, code_override: str | None = None, lang: str = "ar") -> dict[str, str]:
    dict_for_lang = ERROR_MESSAGES.get(lang) or ERROR_MESSAGES["ar"]
    default_msg, default_code = dict_for_lang.get(status_code, ("حدث خطأ أثناء معالجة الطلب.", "UNKNOWN_ERROR"))
    return {
        "message": custom_message or default_msg,
        "code": code_override or default_code,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Verify logging redaction filter on boot
    verify_redaction_filter()
    logger.info("Logging redaction filter self-test passed")

    # Initialize persistence and apply migrations
    await Database.initialize()
    await run_migrations()
    logger.info("Database and migrations initialized")

    # Load and seed agent manifests strictly
    try:
        loaded = await load_and_seed_agents()
        logger.info("Seeded %d active agents into catalog: %s", len(loaded), loaded)
    except Exception as e:
        logger.error("Failed to seed agent manifests: %s", e)
        raise

    # Initialize shared LLM gateway and provider service
    gateway = LLMGateway()
    app.state.llm_gateway = gateway
    app.state.providers_service = ProvidersService(gateway)
    logger.info("LLM Gateway and Providers service initialized")

    # Startup sweep: clean up any stale temporary run directories
    cleanup_stale_run_dirs()
    data_janitor.start()

    # 1. Multi-worker check (F1)
    worker_count = 1
    web_concurrency = os.environ.get("WEB_CONCURRENCY")
    if web_concurrency:
        try:
            worker_count = max(worker_count, int(web_concurrency))
        except ValueError:
            pass
    for idx, arg in enumerate(sys.argv):
        if arg in ("--workers", "-w") and idx + 1 < len(sys.argv):
            try:
                worker_count = max(worker_count, int(sys.argv[idx + 1]))
            except ValueError:
                pass
    if worker_count > 1:
        logger.warning(
            "CRITICAL ARCHITECTURAL WARNING: Multiple workers detected (count=%d). "
            "In-process state (token registry, rate limiters, concurrency locks) lives in memory. "
            "Multiple workers will cause 401 Unauthorized errors on agent /v1 calls and fragment rate limits. "
            "Run with a single worker (--workers 1) for the MVP.",
            worker_count,
        )

    # 2. Sandbox mode check (F2)
    sandbox_mode = get_sandbox_mode()
    if sandbox_mode == "emulated":
        logger.warning(
            "DEVELOPMENT NOTICE: Running in emulated sandbox on %s. "
            "Kernel-level isolation (uid separation, rlimits, network deny, namespaces) "
            "cannot be enforced on this OS. A hardened Linux host is required for production.",
            sys.platform,
        )
    else:
        logger.info("Production sandbox active: Linux kernel controls (rlimits, unprivileged execution) enabled")

    # 3. Auto-start supervised Tier-2 service agents (Site DNA) outside test runs
    service_start_task: asyncio.Task | None = None
    if settings.site_dna_auto_start and not os.environ.get("PYTEST_CURRENT_TEST"):
        service_start_task = asyncio.create_task(site_dna_supervisor.start())
        logger.info("Scheduled background startup for supervised service agent: site-dna")

    yield

    if service_start_task and not service_start_task.done():
        service_start_task.cancel()
    data_janitor.stop()
    await site_dna_supervisor.stop()
    await gateway.aclose()
    await Database.close()


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url=None,  # Disabled for security in public production delivery
    redoc_url=None,
    openapi_url=None,
)

# 1. CORS Configuration (defaults to same-origin only unless configured)
if settings.allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )


# 2. Request Size Limit Middleware
class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > settings.max_request_size_bytes:
                    lang = (request.headers.get("x-lang") or "ar").lower()
                    error_payload = get_error_response(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, lang=lang)
                    return JSONResponse(error_payload, status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
            except ValueError:
                pass
        return await call_next(request)


app.add_middleware(RequestSizeLimitMiddleware)


# 3. Security Headers Middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        # Preserve route-specific stricter CSP (e.g., report preview/download or Site DNA sub-app)
        if "content-security-policy" not in {k.lower() for k in response.headers.keys()}:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "font-src 'self'; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "object-src 'none'"
            )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        # HSTS note: Strictly enforced by the edge reverse proxy (e.g. Nginx/Caddy) terminating TLS.

        return response


app.add_middleware(SecurityHeadersMiddleware)


# 4. Standard Exception Handlers conforming to Error Contract
@app.exception_handler(LLMBaseError)
async def llm_exception_handler(request: Request, exc: LLMBaseError) -> JSONResponse:
    lang = (request.headers.get("x-lang") or "ar").lower()
    resp_headers = {}
    if getattr(exc, "retry_after_seconds", None) is not None:
        resp_headers["Retry-After"] = str(int(exc.retry_after_seconds))
    return JSONResponse(exc.to_dict(lang=lang), status_code=exc.status_code, headers=resp_headers or None)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    lang = (request.headers.get("x-lang") or "ar").lower()
    custom_msg = str(exc.detail) if exc.detail and exc.detail != "Not Found" else None
    payload = get_error_response(exc.status_code, custom_message=custom_msg, lang=lang)
    return JSONResponse(payload, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    lang = (request.headers.get("x-lang") or "ar").lower()
    errors = exc.errors()
    first = errors[0] if errors else {"loc": [], "msg": "Invalid data"}
    field = ".".join(str(part) for part in first["loc"][1:])
    detail = f"{field}: {first['msg']}" if field else first["msg"]
    payload = get_error_response(status.HTTP_422_UNPROCESSABLE_ENTITY, custom_message=detail, lang=lang)
    return JSONResponse(payload, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Log the unexpected error internally with redaction active
    logger.error("Unhandled server exception: %s", type(exc).__name__, exc_info=True)
    lang = (request.headers.get("x-lang") or "ar").lower()
    # Never leak stack trace, internal path, or headers to caller
    payload = get_error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, lang=lang)
    return JSONResponse(payload, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# 5. API Endpoints
@app.get("/api/health")
async def health_check() -> dict[str, Any]:
    worker_count = 1
    if os.environ.get("WEB_CONCURRENCY"):
        try:
            worker_count = int(os.environ["WEB_CONCURRENCY"])
        except ValueError:
            pass
    return {
        "status": "ok",
        "app": settings.app_name,
        "platform": sys.platform,
        "sandbox_mode": get_sandbox_mode(),
        "worker_mode": "multi_worker_warning" if worker_count > 1 else "single_worker",
        "database": "connected" if Database._initialized else "disconnected",
        "services": {
            "site-dna": site_dna_supervisor.get_status(),
        },
    }


@app.get("/api/test-error")
async def test_error_endpoint() -> None:
    """Deliberately raises an unhandled error for verification testing."""
    raise RuntimeError("Deliberate test failure for error contract verification")


# Catalog and platform routers
app.include_router(catalog_router)
app.include_router(providers_router)
app.include_router(v1_router)
app.include_router(runs_router)
app.include_router(service_proxy_router)


# 6. Static Web Distribution & SPA Fallback
@app.api_route("/{full_path:path}", methods=["GET", "HEAD"])
async def serve_frontend(request: Request, full_path: str):
    # Unknown API routes return standard JSON 404
    if full_path == "api" or full_path.startswith("api/") or full_path.startswith("agents-api/"):
        lang = (request.headers.get("x-lang") or "ar").lower()
        return JSONResponse(get_error_response(status.HTTP_404_NOT_FOUND, lang=lang), status_code=404)

    # Site DNA Sub-App Static Serving (/agents/site-dna/app/...)
    # Note: /agents/site-dna (without /app) intentionally falls through to platform web/dist detail & BYOK setup page.
    if full_path == "agents/site-dna/app" or full_path.startswith("agents/site-dna/app/"):
        sub_path = full_path[len("agents/site-dna/app") :].lstrip("/")
        repo_root = Path(__file__).resolve().parent.parent
        site_dna_dist = repo_root / "agents" / "site-dna" / "frontend-dist"
        if not site_dna_dist.exists():
            site_dna_dist = repo_root / "agents" / "site-dna" / "frontend" / "dist"
        if site_dna_dist.exists():
            dist_root = site_dna_dist.resolve()
            sub_app_csp = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; "
                "font-src 'self'; "
                "connect-src 'self'; "
                "frame-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "object-src 'none'; "
                "form-action 'self'"
            )
            if sub_path:
                target_sub = (dist_root / sub_path).resolve()
                if target_sub.is_relative_to(dist_root) and target_sub.is_file():
                    resp = FileResponse(target_sub)
                    resp.headers["Content-Security-Policy"] = sub_app_csp
                    if "/assets/" in sub_path or sub_path.startswith("assets/"):
                        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                    else:
                        resp.headers["Cache-Control"] = "no-cache"
                    return resp
            # SPA fallback strictly limited to /agents/site-dna/app/ prefix
            sub_index = dist_root / "index.html"
            if sub_index.is_file():
                resp = FileResponse(sub_index)
                resp.headers["Content-Security-Policy"] = sub_app_csp
                resp.headers["Cache-Control"] = "no-cache"
                return resp

    dist_dir = settings.resolved_web_dist_path
    if not dist_dir.exists():
        return JSONResponse(
            {"message": "Frontend build not found. Run 'npm run build' in web/ first.", "code": "DIST_NOT_FOUND"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    target_file = dist_dir / full_path

    # Prevent directory traversal
    try:
        target_file = target_file.resolve()
        if not str(target_file).startswith(str(dist_dir.resolve())):
            return JSONResponse(get_error_response(status.HTTP_404_NOT_FOUND), status_code=404)
    except Exception:
        return JSONResponse(get_error_response(status.HTTP_404_NOT_FOUND), status_code=404)

    # If specific static file exists and is not a directory
    if target_file.is_file():
        response = FileResponse(target_file)
        if "/assets/" in full_path or full_path.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif full_path in ("index.html", "theme-init.js") or full_path.endswith(".html"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    # SPA Fallback for client-side routing
    index_file = dist_dir / "index.html"
    if index_file.is_file():
        response = FileResponse(index_file)
        response.headers["Cache-Control"] = "no-cache"
        return response

    return JSONResponse(get_error_response(status.HTTP_404_NOT_FOUND), status_code=404)
