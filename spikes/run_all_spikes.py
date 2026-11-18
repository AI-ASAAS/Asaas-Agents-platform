"""
Runner for all provider verification spikes.
Runs available spikes based on presence of SPIKE_* environment variables.
Outputs sanitized diagnostic JSON.
"""

import json
from spike_gemini import test_gemini
from spike_openai import test_openai
from spike_anthropic import test_anthropic
from spike_openrouter import test_openrouter


def main():
    print("Running ASAAS LLM Provider Spikes (Phase 0)...")
    results = {
        "gemini": test_gemini(),
        "openai": test_openai(),
        "anthropic": test_anthropic(),
        "openrouter": test_openrouter(),
    }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
