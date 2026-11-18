"""
Spike: Anthropic API Verification
Validates key via list-models (zero completion cost) and checks native messages endpoint.
NEVER prints or leaks keys.
"""

import os
import sys
import httpx


def test_anthropic() -> dict:
    key = os.environ.get("SPIKE_ANTHROPIC_KEY")
    if not key:
        return {"provider": "anthropic", "status": "skipped", "reason": "SPIKE_ANTHROPIC_KEY not set"}

    results = {"provider": "anthropic", "status": "running"}

    # 1. Cheapest call: list models
    try:
        url = "https://api.anthropic.com/v1/models"
        headers = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        }
        resp = httpx.get(url, headers=headers, timeout=10.0)
        results["list_models"] = {
            "status_code": resp.status_code,
            "ratelimit_headers": {k: v for k, v in resp.headers.items() if "ratelimit" in k.lower()},
            "models_count": len(resp.json().get("data", [])) if resp.status_code == 200 else 0,
        }
    except Exception as e:
        results["list_models"] = {"error": type(e).__name__}

    # 2. Tiny native completion call
    try:
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "claude-3-5-haiku-20241022",
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
    res = test_anthropic()
    print(json.dumps(res, indent=2))
