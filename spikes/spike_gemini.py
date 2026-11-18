"""
Spike: Google AI Studio (Gemini) API Verification
Validates key via list-models (zero completion cost) and optional tiny completion.
NEVER prints or leaks keys.
"""

import os
import sys
import httpx


def test_gemini() -> dict:
    key = os.environ.get("SPIKE_GEMINI_KEY")
    if not key:
        return {"provider": "gemini", "status": "skipped", "reason": "SPIKE_GEMINI_KEY not set"}

    results = {"provider": "gemini", "status": "running"}

    # 1. Cheapest call: list models
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/openai/models"
        headers = {"Authorization": f"Bearer {key}"}
        resp = httpx.get(url, headers=headers, timeout=10.0)
        results["list_models"] = {
            "status_code": resp.status_code,
            "has_ratelimit_headers": any(k.lower().startswith("x-ratelimit") for k in resp.headers.keys()),
            "models_count": len(resp.json().get("data", [])) if resp.status_code == 200 else 0,
        }
    except Exception as e:
        results["list_models"] = {"error": type(e).__name__}

    # 2. Tiny completion call
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {
            "model": "gemini-1.5-flash",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 5,
        }
        resp = httpx.post(url, headers=headers, json=payload, timeout=15.0)
        results["tiny_completion"] = {
            "status_code": resp.status_code,
            "headers_keys": [k for k in resp.headers.keys() if "limit" in k.lower() or "retry" in k.lower()],
            "usage": resp.json().get("usage") if resp.status_code == 200 else None,
            "error": resp.json().get("error") if resp.status_code != 200 else None,
        }
    except Exception as e:
        results["tiny_completion"] = {"error": type(e).__name__}

    results["status"] = "completed"
    return results


if __name__ == "__main__":
    import json
    res = test_gemini()
    print(json.dumps(res, indent=2))
