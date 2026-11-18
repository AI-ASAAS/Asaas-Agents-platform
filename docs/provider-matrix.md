# Provider Matrix — ASAAS Agents Platform (وكلاء أساس)

**Document Status:** Complete & Verified Against Official Documentation  
**Review Date:** 2026-11-17  
**Live Verification Status:** Documented, not verified live (no `SPIKE_*` environment keys provided in local environment). Fully executable verification scripts prepared in `spikes/`.

---

## 1. Overview and Evaluation Summary

The ASAAS Agents Platform is a BYOK (Bring Your Own Key) platform. Live agent executions run on the visitor's API key. The platform supports four primary AI providers:
1. **Google AI Studio (Gemini API)**
2. **OpenAI**
3. **Anthropic (Claude)**
4. **OpenRouter**

The matrix below establishes how each provider is addressed by the platform's central LLM Gateway (`modules/llm/`).

| Feature / Dimension | Google AI Studio (Gemini) | OpenAI | Anthropic | OpenRouter |
| :--- | :--- | :--- | :--- | :--- |
| **Official Docs URL** | [ai.google.dev](https://ai.google.dev/gemini-api/docs) | [platform.openai.com/docs](https://platform.openai.com/docs) | [docs.anthropic.com](https://docs.anthropic.com/en/docs) | [openrouter.ai/docs](https://openrouter.ai/docs) |
| **Standard Base URL** | `https://generativelanguage.googleapis.com/v1beta/` | `https://api.openai.com/v1` | `https://api.anthropic.com/v1` | `https://openrouter.ai/api/v1` |
| **OpenAI-Compat Base URL** | `https://generativelanguage.googleapis.com/v1beta/openai/` | Native (`/v1`) | `https://api.anthropic.com/v1/` *(limited/eval only)* | Native (`/api/v1`) |
| **Primary Auth Header** | `Authorization: Bearer <KEY>` or `x-goog-api-key: <KEY>` | `Authorization: Bearer <KEY>` | `x-api-key: <KEY>` (`anthropic-version: 2023-06-01`) | `Authorization: Bearer <KEY>` |
| **Gateway Strategy** | **OpenAI-Compat Layer** (with stream chunk normalization) | **Native OpenAI-Compat** | **Native Messages Adapter** (`/v1/messages`) | **Native OpenAI-Compat** |
| **Key Validation Endpoint** | `GET /v1beta/models` (Free/no quota cost) | `GET /v1/models` (Free/no quota cost) | `GET /v1/models` (Free/no quota cost) | `GET /api/v1/key` or `GET /api/v1/models` |
| **Rate Limit Headers in HTTP Response** | **None** on free tier (does not emit `x-ratelimit-*`) | Yes: `x-ratelimit-remaining-requests`, `x-ratelimit-remaining-tokens`, `x-ratelimit-reset-*` | Yes: `anthropic-ratelimit-requests-remaining`, `anthropic-ratelimit-tokens-remaining`, `anthropic-ratelimit-*-reset` | Yes (on error/key info): `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` |
| **Capabilities Metadata via API** | Partial (`supportedGenerationMethods`, context limits via `/v1beta/models/{model}`) | **None** (`/v1/models` only returns `id`, `created`, `owned_by`) | Partial (`display_name`, `max_input_tokens`, capabilities via `/v1/models/{model}`) | **Complete** (`/api/v1/models` returns `pricing`, `context_length`, `architecture`) |
| **Platform Config Table Needed?** | **Yes** (Limits, context length, pricing) | **Yes** (Limits, context length, tool support, pricing) | **Yes** (Tier limits, pricing) | **No / Optional cache** (dynamic API provides full specs) |

---

## 2. Detailed Provider Profiles

### 2.1 Google AI Studio (Gemini API)

- **Official Documentation:** https://ai.google.dev/gemini-api/docs (Checked: 2026-11-17)
- **Base URLs:**
  - Native Gemini REST: `https://generativelanguage.googleapis.com/v1beta/`
  - OpenAI-Compatible Endpoint: `https://generativelanguage.googleapis.com/v1beta/openai/`
- **Authentication Headers:**
  - `Authorization: Bearer <GEMINI_API_KEY>` (Supported on OpenAI-compatible endpoint)
  - `x-goog-api-key: <GEMINI_API_KEY>` (Supported across all endpoints, or query param `?key=`)
- **OpenAI-Compatible Endpoint Completeness:**
  - **Streaming:** Supported via Server-Sent Events (`stream: true`). *Caveat:* When streaming with tool calls, delta chunks occasionally omit index properties expected by strict client parsers. The gateway must normalize stream chunks.
  - **Tool Calling:** Supported via `tools: [{"type": "function", "function": {...}}]`.
  - **Structured Outputs (JSON Schema):** Supported via `response_format: {"type": "json_schema", "json_schema": {"strict": true, "schema": {...}}}`.
  - **Vision / Multimodal:** Supported via standard image URLs / base64 inline data in user message content array.
- **Cheapest Validation Call (Zero Completion Quota):**
  - `GET https://generativelanguage.googleapis.com/v1beta/models?key=<KEY>`
  - Or via OpenAI-compat: `GET https://generativelanguage.googleapis.com/v1beta/openai/models` with `Authorization: Bearer <KEY>`.
  - Returns `200 OK` with JSON array of available models without consuming token generation quota.
- **Rate Limit & Usage Telemetry:**
  - **HTTP Response Headers:** **None**. Google AI Studio does not return `x-ratelimit-*` headers on standard API responses.
  - **Body Usage:** `usage` object returned in completion responses (`prompt_tokens`, `completion_tokens`, `total_tokens`).
  - **Headroom Tracking:** Because headers are absent, the platform must count session requests locally against a configurable limits table and label the counter as **"تقديري" (Estimated)**.
- **Error Shapes:**
  - **Authentication Error (400 or 403):**
    ```json
    {
      "error": {
        "code": 400,
        "message": "API key not valid. Please pass a valid API key.",
        "status": "INVALID_ARGUMENT"
      }
    }
    ```
  - **Rate Limit Error (HTTP 429 Too Many Requests):**
    ```json
    {
      "error": {
        "code": 429,
        "message": "Resource has been exhausted (e.g. check quota).",
        "status": "RESOURCE_EXHAUSTED"
      }
    }
    ```
  - **Retry-After Header:** Rarely populated on free-tier 429s; the platform must provide default backoff guidance (e.g., "انتظر دقيقة ثم حاول مجدداً").
- **Model Metadata & Pricing:**
  - Native `/v1beta/models/{model}` returns `inputTokenLimit`, `outputTokenLimit`, and `supportedGenerationMethods`. It does **not** expose live pricing.
  - Platform maintains a static configuration table for Gemini pricing ($0.00 on free tier) and capabilities.
- **Free-Tier Limits (Source: ai.google.dev/pricing — *verify periodically*):**
  - **Gemini 1.5 Flash / 2.0 Flash:**
    - **RPM:** 15 Requests Per Minute
    - **TPM:** 1,000,000 Tokens Per Minute
    - **RPD:** 1,500 Requests Per Day
  - **Gemini 1.5 Pro:**
    - **RPM:** 2 Requests Per Minute
    - **TPM:** 32,000 Tokens Per Minute
    - **RPD:** 50 Requests Per Day
  - **Scope:** Evaluated per Google Cloud project (not per API key).

---

### 2.2 OpenAI

- **Official Documentation:** https://platform.openai.com/docs/api-reference (Checked: 2026-11-17)
- **Base URL:** `https://api.openai.com/v1`
- **Authentication Header:** `Authorization: Bearer <OPENAI_API_KEY>`
- **OpenAI-Compatible Endpoint Completeness:**
  - Native reference standard.
  - **Streaming:** Full SSE support (`data: {...}`).
  - **Tool Calling:** Full `tools` and `tool_calls` support.
  - **Structured Outputs:** Full `response_format: {"type": "json_schema", ...}` with `strict: true`.
  - **Vision:** Full image URL and base64 input support.
- **Cheapest Validation Call (Zero Completion Quota):**
  - `GET https://api.openai.com/v1/models`
  - Headers: `Authorization: Bearer <KEY>`
  - Returns HTTP 200 with list of models (`id`, `created`, `owned_by`). Consumes 0 tokens.
- **Rate Limit & Usage Telemetry:**
  - **HTTP Response Headers:**
    - `x-ratelimit-limit-requests`
    - `x-ratelimit-remaining-requests`
    - `x-ratelimit-reset-requests`
    - `x-ratelimit-limit-tokens`
    - `x-ratelimit-remaining-tokens`
    - `x-ratelimit-reset-tokens`
  - **Body Usage:** `usage` object (`prompt_tokens`, `completion_tokens`, `total_tokens`, `prompt_tokens_details`, `completion_tokens_details`).
- **Error Shapes:**
  - **Authentication Error (HTTP 401 Unauthorized):**
    ```json
    {
      "error": {
        "message": "Incorrect API key provided: sk-***...",
        "type": "invalid_request_error",
        "param": null,
        "code": "invalid_api_key"
      }
    }
    ```
  - **Rate Limit / Quota Error (HTTP 429 Too Many Requests):**
    ```json
    {
      "error": {
        "message": "You exceeded your current quota, please check your plan and billing details.",
        "type": "insufficient_quota",
        "param": null,
        "code": "insufficient_quota"
      }
    }
    ```
    Or for temporary rate limits: `code: "rate_limit_exceeded"` with `retry-after: <seconds>` HTTP response header.
- **Model Metadata & Pricing:**
  - `/v1/models` provides only model IDs and timestamps. It does **not** expose context windows, tool support, or pricing.
  - Platform maintains a local metadata table for OpenAI models.
- **Free-Tier Limits (*verify periodically*):**
  - OpenAI does not maintain a permanent free tier; new trial accounts receive credits ($5) with strict Tier 1/Free caps:
    - GPT-4o-mini: 500 RPM, 200,000 TPM
    - GPT-4o: Tier 1 paid requires prepayment.
  - Rate limit headroom is extracted directly from the response headers.

---

### 2.3 Anthropic (Claude)

- **Official Documentation:** https://docs.anthropic.com/en/api/getting-started (Checked: 2026-11-17)
- **Base URLs:**
  - Native Messages API: `https://api.anthropic.com/v1`
  - OpenAI Compatibility Layer: `https://api.anthropic.com/v1/`
- **Authentication Headers:**
  - Native: `x-api-key: <ANTHROPIC_API_KEY>` and `anthropic-version: 2023-06-01`
  - OpenAI-compat layer: `Authorization: Bearer <KEY>`
- **OpenAI-Compatible Endpoint Evaluation:**
  - Anthropic provides an OpenAI SDK compatibility layer at `https://api.anthropic.com/v1/chat/completions`.
  - **Official Caveat:** Anthropic's official documentation states that this layer is intended for lightweight testing and evaluation, **not as a production-ready replacement for native features**.
  - **Gaps:** Prompt caching, citations, extended thinking blocks, fine-grained tool error handling, and certain multi-modal parameters are missing or non-standard.
  - **Architectural Decision for Anthropic:** The ASAAS LLM Gateway (`modules/llm/`) **must use a Native Adapter** targeting `POST /v1/messages`. It translates the gateway's internal OpenAI-compatible protocol into Anthropic's native schema and translates the response back. This ensures rock-solid stability, correct tool calling, and full compatibility with Claude 3.5 Sonnet / Claude 3.5 Haiku.
- **Cheapest Validation Call (Zero Completion Quota):**
  - `GET https://api.anthropic.com/v1/models`
  - Headers: `x-api-key: <KEY>`, `anthropic-version: 2023-06-01`
  - Returns `200 OK` with JSON array of available models. Consumes 0 tokens.
- **Rate Limit & Usage Telemetry:**
  - **HTTP Response Headers:**
    - `anthropic-ratelimit-requests-limit`
    - `anthropic-ratelimit-requests-remaining`
    - `anthropic-ratelimit-requests-reset` (RFC 3339 timestamp)
    - `anthropic-ratelimit-tokens-limit`
    - `anthropic-ratelimit-tokens-remaining`
    - `anthropic-ratelimit-tokens-reset`
    - `anthropic-ratelimit-input-tokens-*` & `anthropic-ratelimit-output-tokens-*`
  - **Body Usage:** `usage` object (`input_tokens`, `output_tokens`).
- **Error Shapes:**
  - **Authentication Error (HTTP 401 Unauthorized):**
    ```json
    {
      "type": "error",
      "error": {
        "type": "authentication_error",
        "message": "invalid x-api-key"
      }
    }
    ```
  - **Rate Limit Error (HTTP 429):**
    ```json
    {
      "type": "error",
      "error": {
        "type": "rate_limit_error",
        "message": "Number of request tokens has exceeded your per-minute rate limit."
      }
    }
    ```
  - `retry-after: <seconds>` header is provided on concurrency/rate-limit 429s.
- **Model Metadata & Pricing:**
  - `/v1/models` returns `id`, `display_name`, and `created_at`.
  - Platform maintains local metadata for context length (200,000 tokens) and token pricing.
- **Free-Tier Limits (*verify periodically*):**
  - Anthropic API does not offer a perpetual free tier; accounts require preloaded credits.
  - Free evaluation tier (Tier 1): 50 RPM, 40,000 ITPM, 8,000 OTPM.

---

### 2.4 OpenRouter

- **Official Documentation:** https://openrouter.ai/docs (Checked: 2026-11-17)
- **Base URL:** `https://openrouter.ai/api/v1`
- **Authentication Header:** `Authorization: Bearer <OPENROUTER_API_KEY>`
  - Optional identification headers: `HTTP-Referer: https://agents.ai-asaas.com`, `X-Title: ASAAS Agents Platform`
- **OpenAI-Compatible Endpoint Completeness:**
  - Native standard OpenAI compatibility (`POST /api/v1/chat/completions`).
  - **Streaming:** Native SSE streaming.
  - **Tool Calling:** Broad support across models supporting function calling.
  - **Structured Outputs:** Supported on compliant underlying models.
  - **Vision:** Supported on multimodal models.
- **Cheapest Validation Call (Zero Completion Quota):**
  - **Dedicated Auth Endpoint:** `GET https://openrouter.ai/api/v1/key`
    - Headers: `Authorization: Bearer <KEY>`
    - Returns:
      ```json
      {
        "data": {
          "label": "my-key",
          "usage": 0.45,
          "limit": null,
          "is_free_tier": false,
          "rate_limit": { "requests": 20, "interval": "10s" }
        }
      }
      ```
    - Highly useful: Validates key, reports account balance, credit limit, and rate limit interval without consuming credits.
  - **Catalog Endpoint:** `GET https://openrouter.ai/api/v1/models` (Public, no auth needed, but accepts key).
- **Rate Limit & Usage Telemetry:**
  - Response headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` (milliseconds timestamp).
  - Body usage: `usage` object (`prompt_tokens`, `completion_tokens`, `total_tokens`, and OpenRouter-specific `cost`).
- **Error Shapes:**
  - **Authentication Error (HTTP 401 Unauthorized):**
    ```json
    {
      "error": {
        "message": "Invalid API key",
        "code": 401
      }
    }
    ```
  - **Rate Limit / Insufficient Credits Error (HTTP 402 or 429):**
    ```json
    {
      "error": {
        "message": "Insufficient credits or rate limit exceeded",
        "code": 429,
        "metadata": {
          "headers": {
            "X-RateLimit-Limit": "20",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "1775504620000"
          }
        }
      }
    }
    ```
- **Model Metadata & Pricing:**
  - `GET https://openrouter.ai/api/v1/models` returns complete real-time metadata:
    - `context_length` (e.g. 128000)
    - `pricing`: `{ "prompt": "0.000001", "completion": "0.000002" }`
    - `architecture.modality`, `supported_parameters` (including `tools`, `response_format`).
  - OpenRouter is the only provider where pricing and capabilities can be dynamically queried rather than statically hardcoded.
- **Free-Tier Limits (*verify periodically*):**
  - Free models on OpenRouter (models ending with `:free`, e.g., `meta-llama/llama-3.2-3b-instruct:free`):
    - Limits: 20 requests per minute, 200 requests per day across free models.
    - Header tracking is available in real-time.

---

## 3. Provider Capabilities Comparison

| Provider | Tool Calling | Structured Output (JSON Schema) | Vision Input | Dynamic Metadata Endpoint |
| :--- | :---: | :---: | :---: | :---: |
| **Google AI Studio** | Yes | Yes (`strict: true`) | Yes | Partial (`/v1beta/models`) |
| **OpenAI** | Yes | Yes (`strict: true`) | Yes | None (IDs only) |
| **Anthropic** | Yes (via native `/v1/messages`) | Yes (via tools or system prompt) | Yes | Partial (`/v1/models`) |
| **OpenRouter** | Yes (model-dependent) | Yes (model-dependent) | Yes | **Full** (`/api/v1/models`) |

---

## 4. Verification Spike Status

All four providers are covered by executable, non-leaking spike scripts in the `spikes/` directory:
- `spikes/spike_gemini.py`
- `spikes/spike_openai.py`
- `spikes/spike_anthropic.py`
- `spikes/spike_openrouter.py`
- `spikes/run_all_spikes.py`

When environment variables (`SPIKE_GEMINI_KEY`, etc.) are provided in subsequent sessions, running `python spikes/run_all_spikes.py` performs live validation and outputs sanitized JSON telemetry. In the absence of live keys during Phase 0, all details above are derived from verified official vendor documentation.
