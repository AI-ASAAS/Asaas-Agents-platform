"""
Spike: OpenRouter API Verification
Validates key via /api/v1/key (zero completion cost, returns credits and limits)
and queries /api/v1/models metadata.
NEVER prints or leaks keys.
"""

import os
import sys
import httpx


def test_openrouter() -> dict:
    key = os.environ.get("SPIKE_OPENROUTER_KEY")
    if not key:
        return {"provider": "openrouter", "status": "skipped", "reason": "SPIKE_OPENROUTER_KEY not set"}

    results = {"provider": "openrouter", "status": "running"}

    # 1. Cheapest call: /api/v1/key (returns key status, credits, limits)
    try:
        url = "https://openrouter.ai/api/v1/key"
        headers = {"Authorization": f"Bearer {key}"}
        resp = httpx.get(url, headers=headers, timeout=10.0)
        results["key_info"] = {
            "status_code": resp.status_code,
            "data": resp.json().get("data") if resp.status_code == 200 else None,
            "error": resp.json().get("error") if resp.status_code != 200 else None,
        }
    except Exception as e:
        results["key_info"] = {"error": type(e).__name__}

    # 2. Query models endpoint (accepts auth, returns pricing and context length)
    try:
        url = "https://openrouter.ai/api/v1/models"
        headers = {"Authorization": f"Bearer {key}"}
        resp = httpx.get(url, headers=headers, timeout=10.0)
        sample_model = None
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            if data:
                # pick a standard model to inspect schema
                m = next((x for x in data if "gpt-4o" in x.get("id", "")), data[0])
                sample_model = {
                    "id": m.get("id"),
                    "context_length": m.get("context_length"),
                    "pricing": m.get("pricing"),
                    "architecture": m.get("architecture"),
                }
        results["models_metadata"] = {
            "status_code": resp.status_code,
            "sample_model": sample_model,
        }
    except Exception as e:
        results["models_metadata"] = {"error": type(e).__name__}

    results["status"] = "completed"
    return results


if __name__ == "__main__":
    import json
    res = test_openrouter()
    print(json.dumps(res, indent=2))
