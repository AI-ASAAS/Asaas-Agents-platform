"""
Comprehensive Verification Suite for Phase 1 (Foundation).
Tests health, error contracts, security headers, static SPA serving,
and proves key non-leakage in both HTTP responses and server logs.
"""

import io
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.testclient import TestClient

from main import app
from utils.logging_filters import RedactionFilter


def run_tests():
    print("=== Starting Phase 1 Backend Verification ===")

    # Set up in-memory log capturing with RedactionFilter
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.addFilter(RedactionFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    # Use context manager to trigger FastAPI lifespan (DB init and migrations)
    with TestClient(app, raise_server_exceptions=False) as client:
        # 1. Health check
        print("\n[1] Testing GET /api/health ...")
        resp = client.get("/api/health")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        assert data["status"] == "ok", f"Expected ok, got {data}"
        assert data["database"] == "connected", f"Expected database connected, got {data}"
        print(f"  -> Success: {data}")

        # Check security headers
        print("\n[2] Checking Security Headers ...")
        csp = resp.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp, "CSP missing default-src"
        assert "script-src 'self'" in csp, "CSP missing script-src"
        assert resp.headers.get("x-content-type-options") == "nosniff", "Missing nosniff"
        assert "strict-origin-when-cross-origin" in resp.headers.get("referrer-policy", ""), "Missing referrer-policy"
        assert "camera=()" in resp.headers.get("permissions-policy", ""), "Missing permissions-policy"
        print(f"  -> CSP: {csp}")
        print("  -> Headers verified successfully.")

        # 3. Unknown API route (Arabic default)
        print("\n[3] Testing Unknown Route: GET /api/unknown (Arabic default) ...")
        resp = client.get("/api/unknown")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
        err_ar = resp.json()
        assert err_ar["code"] == "NOT_FOUND", f"Expected NOT_FOUND code, got {err_ar}"
        assert err_ar["message"] == "المسار غير موجود.", f"Expected Arabic 404 message, got {err_ar}"
        print(f"  -> Success (Arabic): {err_ar}")

        # 4. Unknown API route with X-Lang: en
        print("\n[4] Testing Unknown Route: GET /api/unknown (X-Lang: en) ...")
        resp = client.get("/api/unknown", headers={"X-Lang": "en"})
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
        err_en = resp.json()
        assert err_en["code"] == "NOT_FOUND", f"Expected NOT_FOUND code, got {err_en}"
        assert err_en["message"] == "Endpoint not found.", f"Expected English 404 message, got {err_en}"
        print(f"  -> Success (English): {err_en}")

        # 5. Forced Server Error and Key Non-Leakage Check
        print("\n[5] Testing Forced 500 Error with Fake Key Header ...")
        fake_key = "sk-live-secret-key-1234567890abcdef"
        resp = client.get("/api/test-error", headers={"X-Provider-Key": fake_key})
        assert resp.status_code == 500, f"Expected 500, got {resp.status_code}"
        err_500 = resp.json()
        assert err_500["code"] == "INTERNAL_SERVER_ERROR", f"Expected INTERNAL_SERVER_ERROR, got {err_500}"
        assert "Traceback" not in resp.text, "Stack trace leaked in response body!"
        assert fake_key not in resp.text, "Fake key leaked in response body!"
        for header_name, header_val in resp.headers.items():
            assert fake_key not in header_val, f"Fake key leaked in response header {header_name}!"

        print(f"  -> Server error response: {err_500}")
        print("  -> Confirmed: No stack trace and no key leaked in response.")

        # Inspect captured logs for the fake key
        captured_logs = log_stream.getvalue()
        assert fake_key not in captured_logs, "CRITICAL: Fake key leaked into server logs!"
        print("  -> Confirmed: Fake key did NOT appear in any server log record.")

        # 6. Static SPA Delivery
        print("\n[6] Testing Static SPA Delivery from web/dist ...")
        resp = client.get("/")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert "<!doctype html>" in resp.text.lower(), "Expected HTML response for /"
        assert resp.headers.get("cache-control") == "no-cache", "Expected no-cache for index.html"
        print("  -> GET / serves index.html with Cache-Control: no-cache")

        resp_about = client.get("/about")
        assert resp_about.status_code == 200, f"Expected 200 for SPA route, got {resp_about.status_code}"
        assert "<!doctype html>" in resp_about.text.lower(), "Expected SPA fallback to index.html"
        assert resp_about.headers.get("cache-control") == "no-cache"
        print("  -> GET /about falls back to index.html for client-side routing")

        resp_theme = client.get("/theme-init.js")
        assert resp_theme.status_code == 200, f"Expected 200 for /theme-init.js, got {resp_theme.status_code}"
        assert resp_theme.headers.get("cache-control") == "no-cache"
        print("  -> GET /theme-init.js served with Cache-Control: no-cache")

        print("\n=== All Backend Checks Passed Successfully! ===")


if __name__ == "__main__":
    run_tests()
