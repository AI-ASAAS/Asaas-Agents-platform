"""
Spike: OpenAI API Verification
Validates key via list-models (zero completion cost) and checks rate limit headers.
NEVER prints or leaks keys.
"""

import os
import sys
import httpx


def test_openai() -> dict:
    key = os.environ.get("SPIKE_OPENAI_KEY")
    if not key:
        return {"provider": "openai", "status": "skipped", "reason": "SPIKE_OPENAI_KEY not set"}

    results = {"provider": "openai", "status": "running"}

    # 1. Cheapest call: list models
    try:
        url = "https://api.openai.com/v1/models"
        headers = {"Authorization": f"Bearer {key}"}
        resp = httpx.get(url, headers=headers, timeout=10.0)
        results["list_models"] = {
            "status_code": resp.status_code,
            "ratelimit_headers": {k: v for k, v in resp.headers.items() if "ratelimit" in k.lower()},
            "models_count": len(resp.json().get("data", [])) if resp.status_code == 200 else 0,
        }
    except Exception as e:
        results["list_models"] = {"error": type(e).__name__}

    # 2. Tiny completion call
    try:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 5,
        }
        resp = httpx.post(url, headers=headers, json=payload, timeout=15.0)
        results["tiny_completion"] = {
            "status_code": resp.status_code,
            "ratelimit_headers": {k: v for k, v in resp.headers.items() if "ratelimit" in k.lower() or "retry" in k.lower()},
            "usage": resp.json().get("usage") if resp.status_code == 200 else None,
            "error": resp.json().get("error") if resp.status_code != 200 else None,
        }
    except Exception as e:
        results["tiny_completion"] = {"error": type(e).__name__}

    results["status"] = "completed"
    return results


if __name__ == "__main__":
    import json
    res = test_openai()
    print(json.dumps(res, indent=2))
