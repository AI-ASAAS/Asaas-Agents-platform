# Site DNA (بصمة الموقع) — Integration Assessment & Architecture Design (Part A)

> **Document Type:** Part A — Assessment & Architectural Design Only (Zero code changes in this part)  
> **Target Agent:** Site DNA (`بصمة الموقع`) — Website Intelligence & Multi-Dimensional Audit  
> **Repository:** `https://github.com/Mahmoodbamatraf/site-dna` (Branch: `main`)  
> **Pinned Commit SHA:** `<PINNED_COMMIT_SHA>` *(40-char SHA from `git rev-parse HEAD` of `main` to be locked at Part B start; this assessment inspected the uploaded `site-dna-main.zip` snapshot)*  
> **Platform Slug:** `site-dna`  
> **Date:** 2026-11-17  
> **Status:** Awaiting User Approval (`APPROVED` + answers to Section 8) before starting Part B

---

## Executive Summary

Site DNA (`بصمة الموقع`) is a full-stack, multi-stage website-intelligence service combining deterministic crawling (`httpx` + connection-time IP pinning + `robots.txt`), Playwright Chromium rendering/PDF export, heuristic analyzers, CrewAI agents/flows, direct `google-genai` multimodal vision calls, and a 16-page React 19 + Tailwind 4 frontend bundled with the Asaas UI kit.

Because Site DNA is a **long-running asynchronous web service** requiring outbound public HTTP/HTTPS crawling, headless Chromium, SSE streaming over several minutes, and multi-page stateful views, it cannot fit into the platform's Tier-1 ephemeral `jsonl-stdio@1` job runner (`runtime.kind: "python"`, 180 s timeout, zero internet egress). Integrating it requires introducing **Tier-2 "Service" Agents (`runtime.kind: "service"`)** with an explicit amendment to **D1** (in-memory ephemeral session cookie for service agents) and a hardened `public_http` egress policy under **D3**.

> [!WARNING]
> **Audit Note on Pre-Existing Workspace Draft Files:**  
> During codebase inspection, we detected an earlier partial draft implementation already present in the platform workspace (`api/modules/runtime/{service_proxy,service_supervisor,session_store,session_limiter,janitor}.py`, `api/modules/llm/adapters/anthropic.py`, and `agents/site-dna/`). **No code was modified in Part A**, but this assessment identifies **12 concrete defects** in those draft files (detailed in Section 3) that MUST be fixed in Part B before Site DNA can be considered functional or safe.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                           ASAAS Agents Platform (Single Worker)                        │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ VISITOR BROWSER                                                                        │
│ ┌───────────────────────────────────┐    ┌──────────────────────────────────────────┐  │
│ │ Platform Shell (/agents/site-dna) │    │ Site DNA Sub-App (/agents/site-dna/app/) │  │
│ │ - Key / Provider / Model Setup    │    │   or mounted at /agents/site-dna/        │  │
│ │ - Calls POST /api/service-sessions│    │ - React 19 + Tailwind 4 + Asaas UI       │  │
│ │ - Receives HttpOnly Strict Cookie │    │ - API_BASE: /agents-api/site-dna/api/v1  │  │
│ └─────────────────┬─────────────────┘    └────────────────────┬─────────────────────┘  │
└───────────────────┼───────────────────────────────────────────┼────────────────────────┘
                    │ HTTPS (X-Provider-Key once)               │ HTTPS (HttpOnly Cookie + Origin)
                    ▼                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ ASAAS Platform FastAPI (127.0.0.1:8088, --workers 1, OS user: asaas-app)               │
│ ┌──────────────────────┐ ┌──────────────────────────────┐ ┌──────────────────────────┐ │
│ │ In-Memory Session    │ │ Service Reverse Proxy        │ │ RunTokenRegistry +       │ │
│ │ Store (45m / 2h cap) │ │ - Strict route allowlist     │ │ Local LLM Proxy (/v1/*)  │ │
│ │ (Zero disk/DB/logs)  │ │ - Run ownership + CSRF       │ │ - Model/provider pinning │ │
│ └──────────────────────┘ │ - Strips Cookie before fwd   │ │ - Usage accounting       │ │
│                          │ - Mints art_... BEFORE start │ │ - Revokes on end/cancel  │ │
│                          └──────────────┬───────────────┘ └────────────▲─────────────┘ │
└─────────────────────────────────────────┼──────────────────────────────┼───────────────┘
                                          │ Loopback 127.0.0.1:8001      │ Loopback 127.0.0.1:8088/v1
                                          │ (Headers: X-Run-Token,       │ (Bearer art_... only)
                                          │  X-LLM-Endpoint, X-Model)    │
                                          ▼                              │
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ OS Sandbox Boundary: UID asaas-service-sitedna | systemd cgroup v2 | nftables egress   │
│ - nftables: ALLOW TCP 80/443 public IPs, local DNS, 127.0.0.1:8088; DROP RFC1918/meta  │
│ - cgroup: MemoryMax=2G, CPUQuota=200%, TasksMax=96 | PrivateTmp=true | RO code         │
│ ┌────────────────────────────────────────────────────────────────────────────────────┐ │
│ │ Site DNA Backend Daemon (uvicorn --host 127.0.0.1 --port 8001 --workers 1)         │ │
│ │ - AnalysisCoordinator + per-run Cancel/SSE disconnect watcher                      │ │
│ │ - Playwright Chromium (Visual Capture + Offline PDF Export)                        │ │
│ │ - src/site_dna/core/llm_gateway.py (ALL CrewAI + Multimodal calls -> local /v1)    │ │
│ └────────────────────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Confirmed and Corrected Observations (O1 – O8)

Every observation below was verified directly against the uploaded Site DNA repository snapshot (`site-dna-main.zip`) and the ASAAS platform repository.

### O1. Long-Running Web Service vs. One-Shot Job & `--workers 4` Bug
- **Status:** **CONFIRMED (with file/line corrections)**
- **Evidence:**
  - `POST /api/v1/runs` (`src/site_dna/api/routes/runs.py:85–95`) calls `coordinator.create_and_start_run(request_data)` which spawns an `asyncio.create_task(self._execute_pipeline(run_id, request, selected_stages))` (`src/site_dna/orchestration/coordinator.py:873`) and immediately returns HTTP `201` with a `RunRecord`.
  - Run state lives in an in-process dictionary `self._active_runs: dict[str, RunRecord] = {}` (`coordinator.py:256`) and SSE subscriber queues `self._event_subscribers: dict[str, list[asyncio.Queue]] = {}` (`coordinator.py:255`), persisted to disk at `runs/{run_id}/execution.json` (`coordinator.py:278`, *correction: filename is `execution.json`, not `record.json`*) and `runs/{run_id}/events.jsonl` (`coordinator.py:307`).
  - Progress is streamed over SSE at `GET /api/v1/runs/{run_id}/events` (`runs.py:109–157`) with 15-second keep-alive heartbeats.
  - A multi-stage run (crawl + Playwright dual-viewport capture + AI stages + PDF export) takes **2 to 10+ minutes** depending on target site latency, page count, and selected stages.
  - **Multi-worker bug confirmed:** `docs/phase-12-deployment.md:33` prescribes `uv run uvicorn site_dna.api.main:app --host 0.0.0.0 --port 8000 --workers 4`. Because `_active_runs` and `_event_subscribers` live in process memory, 4 workers break SSE delivery and concurrent run tracking. **Site DNA MUST run with `--workers 1`**.

### O2. Outbound Network Requirement vs. Platform D3
- **Status:** **CONFIRMED (with nuance on PageSpeed/CrUX defaults)**
- **Evidence:**
  - **Crawler:** `src/site_dna/discovery/http_client.py:110–256` (`SecureHttpClient` using `SSRFProtectedTransport`) and `crawler.py:113–190` fetch visitor-supplied target websites, `robots.txt`, and sitemaps.
  - **Browser Rendering:** `src/site_dna/visual/browser_manager.py:73–122` drives Playwright Chromium over the target site's pages.
  - **Competitors:** `src/site_dna/analysis/competitor_intelligence/service.py:97–103` crawls up to 3 competitor origins (`competitor_public_crawl_enabled: True` in `core/config.py:591`).
  - **PageSpeed/CrUX:** `src/site_dna/analysis/technical_seo/external_metrics.py` is **disabled by default** (`technical_seo_external_metrics_enabled = False`, `technical_seo_psi_enabled = False`, `technical_seo_crux_enabled = False` in `core/config.py:524–541`).
  - **Conflict with D3:** `docs/decisions.md:76–88` blocks all outbound egress from `asaas-worker` except `127.0.0.1:8088`. Site DNA requires a distinct service egress policy (`public_http`).

### O3. Playwright Chromium & `--no-sandbox` Flag
- **Status:** **CONFIRMED & EXPANDED (critical extra finding in `pdf_renderer.py`)**
- **Evidence:**
  - `src/site_dna/reporting/pdf_renderer.py:21–28`: Launches Chromium with `args=["--disable-network", "--disable-extensions", "--disable-background-networking", "--no-sandbox", "--disable-setuid-sandbox"]`.
  - **Critical correction/finding:** `--disable-network` is **not a valid Chromium CLI switch** that blocks network sockets! `pdf_renderer.py:44` creates a plain `browser.new_page()` without `offline=True` or a `context.route("**/*", abort)` handler. In Part B, PDF rendering MUST use `context = await browser.new_context(offline=True)` plus `await context.route("**/*", lambda r: r.abort())` to actually guarantee zero network egress during HTML-to-PDF rendering.
  - `src/site_dna/visual/browser_manager.py:15–24, 73–76`: Launches Chromium with `SAFE_CHROMIUM_ARGS` and **does not** pass `--no-sandbox`.

### O4. Provider Coupling, Direct `google-genai` Calls, and Quota Fallback
- **Status:** **CONFIRMED (plus critical hardcoded-model traps discovered)**
- **Evidence:**
  - **CrewAI LLM Factory (`src/site_dna/core/llm.py:17–69`):** `get_llm()` hardcodes `format_crewai_gemini_model()` (`gemini/{model}`) and reads server-side `GEMINI_API_KEY` (or `GOOGLE_API_KEY` fallback in `core/config.py:767–776`). Used by 9 agent factories in `src/site_dna/agents/*.py`.
  - **Direct `google.genai` usage in 6 runtime files** (plus 1 dependency check in `src/site_dna/cli.py:39`):
    1. `src/site_dna/analysis/visual_identity/multimodal_adapter.py:107–145` — `types.Part.from_bytes` (up to 8 PNGs), `system_instruction`, `response_mime_type="application/json"`, `max_output_tokens=2048`.
    2. `src/site_dna/analysis/ux_ui/multimodal_adapter.py:111–146` — `types.Part.from_bytes` (up to 8 PNGs), `system_instruction`, `response_mime_type="application/json"`, `max_output_tokens=2048`.
    3. `src/site_dna/analysis/content_marketing/multimodal_adapter.py:172–195` — text-only prompt, `system_instruction`, `response_mime_type="application/json"`, `max_output_tokens=2048`.
    4. `src/site_dna/analysis/technical_seo/multimodal_adapter.py:192–215` — text-only prompt, `system_instruction`, `response_mime_type="application/json"`, `max_output_tokens=2048`.
    5. `src/site_dna/analysis/competitor_intelligence/context_builder.py:394–425` — text-only competitor discovery prompt, raw `generate_content` without `response_mime_type`.
    6. `src/site_dna/services/gemini_diagnostics.py:10–12, 210` — direct `genai.Client` diagnostic probe.
  - **Google-specific quota handling:** `is_daily_quota_exhausted()` checks Google-specific error strings (`generaterequestsperday`, `free_tier_requests`, `freetier`, `resource_exhausted`) in 4 files (`visual_identity/multimodal_adapter.py:35`, `ux_ui/multimodal_adapter.py:38`, `content_marketing/multimodal_adapter.py:41`, `technical_seo/multimodal_adapter.py:38`) and `gemini_diagnostics.py:100–125`.
  - **Fail-soft fallback:** On exhaustion/error, stages return deterministic synthesis and mark stage/run status as `ai_blocked` or `partial` (`coordinator.py:975–978, 1150–1153, 1211–1214, 1272–1275, 1334–1337`).
  - **CRITICAL NEW FINDING — Hardcoded `"gemini-3.6-flash"` overrides:**
    - `content_marketing/multimodal_adapter.py:110–111`: `if "gemini-3.6" not in model_name: model_name = "gemini-3.6-flash"`
    - `technical_seo/multimodal_adapter.py:119–120`: `if "gemini-3.6" not in model_name: model_name = "gemini-3.6-flash"`
    - `agents/strategic_intelligence_agent.py:57`: `llm = get_llm(model="gemini/gemini-3.6-flash", settings=settings)`
    - `core/config.py:33,249,315,393,463,549,611,669,727`: Default model across all stages is `"gemini-3.6-flash"` (not a standard public provider model ID). All hardcoded model overrides MUST be removed so the visitor's chosen model from the platform is honored.
  - **Shared Disk Cache Cross-Tenant Hazard:** `VisualIdentityCache` (`runs/cache/`, enabled by default in `core/config.py:270,342,432,496,582,632,690,742`) shares cached model outputs globally on disk across runs. In multi-visitor service mode, shared disk caching MUST be disabled (or scoped strictly per run/session) to prevent cross-visitor data leakage.

### O5. Public Routes, Missing Tenant Scoping, Optional Tokens, No Cancel
- **Status:** **CONFIRMED (with extra findings)**
- **Evidence:**
  - `src/site_dna/api/main.py:54–56, 88–100, 117`: Exposes `/docs`, `/redoc`, `/openapi.json`, `/dashboard/legacy`, and **13 API routers** (`health`, `runs`, `discovery`, `visual`, `visual_identity`, `ux_ui`, `content_marketing`, `technical_seo`, `competitor_intelligence`, `security_privacy`, `accessibility`, `strategic_intelligence`, `final_reports`).
  - `GET /api/v1/runs` (`runs.py:66–82`) lists ALL runs on disk; `GET /api/v1/dashboard/summary` (`runs.py:57–60`) aggregates global stats; `GET /api/v1/runs/{run_id}` (`runs.py:97–103`), `/findings`, `/recommendations`, `/screenshots`, `/artifacts/screenshot`, `/ai-automation`, `/reports/{stage_id}` have zero auth or visitor scoping.
  - Stage routes (`ux_ui.py:27–58`, `content_marketing.py`, `technical_seo.py:26–57`, `competitor_intelligence.py:27–46`, `security_privacy.py`, `accessibility.py:31–44`, `strategic_intelligence.py`, `final_reports.py:25–42`) are directly callable when enabled (`ux_analysis_api_enabled=True`, `content_analysis_api_enabled=True`, `technical_seo_api_enabled=True` by default!) and all Bearer tokens default to `None` (no auth enforced when unset).
  - **No cancel endpoint exists** anywhere in `runs.py` or `coordinator.py`.
  - **Weak Run ID entropy:** `coordinator.py:842` generates `run_id = f"run-{uuid.uuid4().hex[:12]}"` (only 48 bits of entropy). Must be upgraded to full UUIDv4 (`f"run-{uuid.uuid4().hex}"`, 122 bits) per S6.
  - **Prefix traversal edge case:** `coordinator.py:1782` validates screenshot paths with `str(target).startswith(str(run_dir))` instead of `target.is_relative_to(run_dir.resolve())`.

### O6. Frontend Stack & Sub-App Compatibility
- **Status:** **CONFIRMED (exact page count = 16 files; exact hardcoded `/api/v1` sites identified)**
- **Evidence:**
  - `frontend/package.json:12–28`: React `19.3.1`, `react-router-dom` `7.18.5`, `lucide-react` `1.70.0`, `tailwindcss` `4.3.5` (`@tailwindcss/vite`), `vite` `8.3.6`, TypeScript `~7.0.2`.
  - `frontend/vite.config.ts:6–16`: No `base` configured; uses dev proxy `/api -> http://127.0.0.1:8000`.
  - `frontend/src/App.tsx:13`: `<BrowserRouter>` has **no `basename`**.
  - **16 page/view components** under `frontend/src/pages/`: 6 top-level routed pages (`Dashboard`, `NewAnalysis`, `AnalysisMonitor`, `AgentsDirectory`, `History`, `Settings`) + 10 sub-views mounted inside `AnalysisMonitor.tsx` tabs (`AnalysisOverview`, `ScreenshotExplorer`, `FindingsExplorer`, `RecommendationsViewer`, `AIAutomationView`, `CompetitorIntelligenceView`, `SecurityPrivacyView`, `AccessibilityView`, `StrategicIntelligenceView`, `ReportViewer`).
  - **Hardcoded relative `/api/v1` locations:**
    1. `frontend/src/lib/api.ts:106` (`const API_BASE = '/api/v1';`)
    2. `frontend/src/lib/api.ts:239, 241` (`getDownloadReportUrl` and `getPreviewReportUrl` hardcode `/api/v1/reports/final/...` instead of using `API_BASE`)
    3. `frontend/src/lib/useRunEvents.ts:42–43` (hardcodes `new EventSource('/api/v1/runs/${runId}/events')`)
    4. **Backend-emitted path:** `coordinator.py:1752` emits `"api_url": "/api/v1/runs/{run_id}/artifacts/screenshot?file=..."` consumed directly by `<img src={item.api_url}>` in `ScreenshotExplorer.tsx:116`!
  - **Iframe preview:** `frontend/src/pages/ReportViewer.tsx:238–242` renders an unsandboxed `<iframe src={api.getPreviewReportUrl(...)} />`.
  - **Bundled Asaas UI kit:** `frontend/src/asaas-ui/` contains its own copy of Asaas CSS tokens, `useTheme`, and Thmanyah WOFF2 fonts.
  - **Frontend calls direct stage read/write routes (`api.ts:169–221`):** The AnalysisMonitor sub-views call `GET /analysis/{competitors,security-privacy,accessibility,strategy}/{crawlRunId}...`, plus `POST /analysis/accessibility/{id}/tasks/{reviewId}` and `PATCH /analysis/strategy/{id}/actions/{actionId}`. (They also define `run*Analysis` POST helpers that are unused in normal runs and must be blocked at the proxy.)

### O7. Model-Call Budget Analysis (Configured Ceilings vs. Actual Code Execution)
- **Status:** **CONFIRMED & PRECISELY COMPUTED (with critical distinction between config ceilings and actual runtime calls)**
- **Evidence from `src/site_dna/core/config.py` and stage services:**

| Stage (`stage_id`) | Phase | Configured Ceiling (`core/config.py`) | Actual Calls in Current Pipeline (`coordinator.py`) | Multimodal (Images)? | JSON Mode? | Notes |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| `discovery` | 02 | 0 | **0** | No | No | Deterministic crawler (`http_client.py`) |
| `visual_capture` | 03 | 0 | **0** | No | No | Headless Chromium capture (`browser_manager.py`) |
| `visual_identity` | 04 | *(no ceiling field; 1 call)* | **1** (+ up to 2 retries) | **Yes** (up to 8 PNGs) | **Yes** | `visual_identity/multimodal_adapter.py:136` |
| `ux_ui` | 05 | `ux_analysis_max_model_calls = 4` (L330) | **1** (+ up to 2 retries) | **Yes** (up to 8 PNGs) | **Yes** | `ux_ui/multimodal_adapter.py:137` |
| `content_marketing` | 06 | `content_analysis_max_model_calls = 4` (L402) | **1** (+ up to 2 retries) | No | **Yes** | `content_marketing/multimodal_adapter.py:190` |
| `technical_seo` | 07 | `technical_seo_max_model_calls = 3` (L472) | **1** (+ up to 2 retries) | No | **Yes** | `technical_seo/multimodal_adapter.py:210` |
| `competitor_intelligence` | 08 | `competitor_analysis_max_model_calls = 5` (L570) + 1 discovery | **1** (discovery only) | No | Implicit JSON | `context_builder.py:421` (`_discover_with_gemini` runs even when `competitor_discovery_enabled=False`) |
| `security_privacy` | 09 | `security_analysis_max_model_calls = 3` (L620) | **0** *(stubbed)* | No | No | `security_privacy_flow.py:59–75` builds CrewAI agent (`get_llm()`) but does not invoke `.call()` |
| `accessibility` | 10 | `accessibility_max_model_calls = 3` (L678) | **1** (CrewAI `agent.llm.call`) | No | No | `accessibility_flow.py:132` |
| `strategic_intelligence` | 11 | `strategic_max_model_calls = 3` (L736) | **0** *(deterministic)* | No | No | `strategic_intelligence/service.py` is fully deterministic |
| `executive_synthesis` | 12 | 0 | **0** *(deterministic)* | No | No | `final_report_flow.py` renders HTML/MD/PDF deterministically |
| **TOTAL (All 11 Stages)** | **02–12** | **27 calls** *(sum of stage ceilings + visual + discovery)* | **6 calls** *(single pass, 0 retries)* | **Yes (≤16 PNGs total)** | **Yes (4 stages)** | Up to **14 calls** if max retries (2) hit on 5xx; platform gateway caps retries at 1 (no 429 retry) |

- **Common Stage Subsets:**
  1. **Core Free-Tier Default Subset** (`discovery`, `visual_capture`, `visual_identity`, `ux_ui`, `content_marketing`, `technical_seo`, `security_privacy`, `accessibility`, `strategic_intelligence`, `executive_synthesis` — *everything except Competitor Intelligence*): **5 actual calls** (configured ceiling sum: **21 calls**). Fits comfortably inside a 20 RPD free-tier budget (3–4 full analyses/day on a free key).
  2. **Quick Audit Subset** (`discovery`, `visual_capture`, `visual_identity`, `ux_ui`, `content_marketing`, `technical_seo`): **4 actual calls** (configured ceiling sum: **12 calls**).
  3. **Security & Accessibility Subset** (`discovery`, `security_privacy`, `accessibility`, `executive_synthesis`): **1 actual call** (configured ceiling sum: **6 calls**).
  4. **Full Audit (with Competitor Intelligence opt-in):** **6 actual calls** (configured ceiling sum: **27 calls**).
- **Free-Tier Quota Reality Check:** Site DNA's own code (`visual_identity/multimodal_adapter.py:169`, `gemini_diagnostics.py:117`) cites **~20 requests/day** on Google AI Studio Free Tier. Note that `api/config/provider_limits.json:9–11` currently lists `rpd: 1500` for Gemini Flash models; in Part B we must verify current official Google AI Studio free-tier RPD/RPM per model and update `provider_limits.json` so S8 warnings are accurate.

### O8. Test Suite & Offline Execution
- **Status:** **CONFIRMED (exact count corrected)**
- **Evidence:**
  - `tests/` contains **139 `test_*.py` files** (141 total `.py` files including `conftest.py` and helpers) across `unit/`, `api/`, `security/`, `browser/`, and `integration/`.
  - `pyproject.toml:37–44` defines `testpaths = ["tests"]`, `asyncio_mode = "auto"`, and marker `integration` deselected via `pytest -m "not integration"`.
  - In Part B, every agent-side modification must keep `uv run pytest -m "not integration"` passing 100%.

### Additional Important Findings Not Listed in O1–O8
1. **Bundled Font Licenses:**
   - Proprietary **Thmanyah** WOFF2 fonts (`thmanyahsans`, `thmanyahserifdisplay`, `thmanyahseriftext` — 15 WOFF2 files each) are bundled in **two** places: `frontend/src/asaas-ui/fonts/thmanyah/` and `src/site_dna/reporting/assets/fonts/`, accompanied by `LICENSE.pdf` and `LICENSE-ar.pdf`.
   - Because `pdf_renderer` embeds all WOFF2 fonts as base64 in generated HTML (`docs/phase-12-limitations.md:18`, ~1.1 MB overhead per HTML report), confirm ASAAS's Thmanyah font license permits embedding inside downloadable PDFs/HTML generated for public visitors (see Open Question #7).
2. **Dependency Footprint & Lockfile:**
   - `uv.lock` resolves **161 Python packages** (including `crewai[google-genai]>=1.15.37`, `google-genai>=1.65.0`, `playwright>=1.64.1`, `pillow>=13.0.0`, `lxml>=6.1.3`, `fastapi>=0.162.0`, `uvicorn[standard]>=0.54.0`).
   - Approximate cold-install footprint on Linux: `.venv` (~850–950 MB), Playwright Chromium binary (~150–180 MB), frontend `node_modules` (build-time only, ~200 MB; compiled `frontend/dist` is ~2–3 MB). Total runtime disk footprint (excluding `node_modules` if pruned after build): **~1.1 GB**.
3. **Python Version Mismatch (`3.11` vs. Platform Python):**
   - Site DNA's `.python-version` is **`3.11`** and `docs/phase-12-deployment.md:12` states *"Strictly 3.11"*, while `pyproject.toml:6` has `requires-python = ">=3.11"` and `uv.lock:4–14` includes markers for Python `3.11`–`3.14`.
   - The local Windows dev machine currently runs **Python 3.15.0**, and the platform's manifest default is `3.12`. Running `uv sync --frozen --python 3.11` isolates Site DNA cleanly on Python 3.11 without touching the platform API's Python runtime.
4. **Playwright Linux System Packages (One-Time Root Step):**
   - Headless Chromium on Ubuntu/Debian Linux requires native shared libraries installed once as root via `playwright install-deps chromium` (`libnss3`, `libnspr4`, `libatk1.0-0`, `libatk-bridge2.0-0`, `libcups2`, `libdrm2`, `libdbus-1-3`, `libxkbcommon0`, `libxcomposite1`, `libxdamage1`, `libxfixes3`, `libxrandr2`, `libgbm1`, `libpango-1.0-0`, `libcairo2`, `libasound2t64`/`libasound2`, `fonts-liberation`).
5. **Disk Usage per Run:**
   - Each run writes `crawl.json`, `execution.json`, `events.jsonl`, desktop (`1440×900`, up to `12000px` tall) & mobile (`390×844` @ 2x DPR) PNG screenshots (up to `15 MB` cap per image in `config.py:204`), per-stage JSON/Markdown reports, and final HTML (~1.1 MB+ with inlined fonts) + PDF (~1–4 MB).
   - Typical 5-page run: **8–25 MB**; worst-case 8-page image-heavy site: **40–80 MB**. Without a short-lived janitor (60-minute TTL) + disk quota, public traffic would exhaust server disk rapidly.
6. **Full-Site Scan Toggle (`50 pages`) Abuse Vector:**
   - `NewAnalysis.tsx:254` and `coordinator.py:1015` allow a visitor to toggle `full_site_scan=True`, jumping `max_pages` to **50 pages** (up to 100 Playwright screenshots!). In public demo mode, the proxy and Site DNA must clamp `max_pages <= 8` (assumption to tune) and disable/hide `full_site_scan` in the public UI.

---

## 2. Decisions with Recommended Defaults (S1 – S11)

> Every numeric limit marked **(assumption to tune)** will be exposed in `api/config.py` and `agent.manifest.json`, and reviewed after one week of real usage.

### S1. New Agent Tier `"service"` (`runtime.kind: "service"`)
- **Recommendation:** Adopt the proposed `"service"` tier in `manifest_schema.py` and `docs/agent-manifest.md`. The platform supervises one long-lived Site DNA Uvicorn daemon (`--workers 1`, bound strictly to `127.0.0.1:8001`) running under its own unprivileged OS user (`asaas-service-sitedna`), reverse-proxying only a strict route allowlist under `/agents-api/site-dna/api/v1/*`.
- **Per-Agent Limits (explicit manifest & settings fields, distinct from Tier-1 global ceilings of 180 s / 4096 tokens):**
  - `max_wall_clock_seconds`: **1200** (20 minutes) *(assumption to tune)*
  - `platform_concurrent_runs`: **2** *(assumption to tune)*
  - `per_ip_concurrent_runs`: **1** *(assumption to tune)*
  - `per_ip_daily_runs`: **3** per 24h *(assumption to tune)*
  - `max_pages_per_run`: **8** *(assumption to tune — prevents 50-page abuse)*
  - `max_output_tokens`: **4096** per call *(assumption to tune; Site DNA stages default to 2048)*
  - `egress_policy`: `"public_http"`
- **Trade-offs:** Keeps ~220 MB idle RAM for the warm FastAPI + CrewAI process, avoiding ~8–12 s cold-start overhead on every request and enabling native async SSE + multi-request artifact browsing. Ordinary job agents (`runtime.kind: "python"`) retain their untouched 180 s / 4096 token ceilings and `loopback_only` egress.
- **Platform Changes:** Extend `manifest_schema.py`, `config.py` (service ceilings), harden `service_supervisor.py` (no `shell=True`, clean env, Linux UID drop), and expose service health in `/api/health`.

### S2. Key & Session Handling for Service Agents (Amendment to D1)
- **Recommendation:** Formally record this as **Amendment D1-A** in `docs/decisions.md`:
  1. Visitor configures provider, API key, and model on the platform's `/agents/site-dna` detail page.
  2. Platform validates the key via `LLMGateway.validate_key()` and creates an opaque, CSPRNG session ID (`sss_<32 bytes>`) stored **IN MEMORY ONLY** (`SessionStore` in process heap — zero SQLite, zero disk, zero logs, zero agent env).
  3. Session lifetime: **45 minutes sliding TTL** *(assumption to tune)*, **2 hours absolute cap** *(assumption to tune)*.
  4. Delivered **exclusively** via a `Secure; HttpOnly; SameSite=Strict; Path=/` cookie (`__Host-asaas_service_session` over HTTPS, or `asaas_service_session` in local HTTP dev). **Never** return `session_id` in JSON payloads and **never** forward the `Cookie` header to the Site DNA backend!
  5. When `POST /agents-api/site-dna/api/v1/runs` arrives:
     - Proxy mints a per-run token `art_<32 bytes>` in `RunTokenRegistry` with `ttl_seconds = max_wall_clock_seconds + 120` (22 minutes) **BEFORE** forwarding to Site DNA.
     - Proxy injects `X-Run-Token: art_...`, `X-LLM-Endpoint: http://127.0.0.1:8088/v1`, `X-LLM-Model: <session.model>`, `X-LLM-Provider: <session.provider>` on the loopback `POST /api/v1/runs` request to `127.0.0.1:8001` (and strips `Cookie` and `Authorization`).
     - Site DNA stores the run token in memory bound to that `run_id` ONLY (never writes it to `execution.json`, `events.jsonl`, or logs) and uses it to call `127.0.0.1:8088/v1/chat/completions`.
     - Proxy revokes `art_...` immediately upon `run.completed`, `run.failed`, `run.cancelled`, SSE-abandonment cancel, wall-clock timeout, or session expiry/logout.
  6. **CSRF Protection:** `SameSite=Strict` cookie + mandatory `Origin` (or `Sec-Fetch-Site: same-origin` / `Referer` fallback) exact-match check on every state-changing proxy route (`POST`, `PUT`, `PATCH`, `DELETE`) and `/api/service-sessions/{init,logout}`. Reject missing or mismatched `Origin` with `403 Forbidden`.
  7. **Single-Worker Dependency:** Explicitly relies on the `--workers 1` architecture from F1 for both the platform API and Site DNA backend. Simple job agents keep the stateless `X-Provider-Key` header model untouched.
- **Trade-offs:** Server restart drops active sessions (acceptable for ephemeral public demos). Requires strict memory hygiene and CSRF validation on proxy mutations.

### S3. Frontend Integration: Standalone Sub-App Mount at `/agents/site-dna/`
- **Recommendation:** **Mount Site DNA's own production build as a standalone sub-application** rather than porting 16 pages into `web/src/agent-ui/`.
- **Comparison:**
  - *Porting into `web/src/agent-ui/`:* High risk and ~120+ hrs effort — Site DNA uses React 19 + Tailwind 4 (`@tailwindcss/vite`) while platform `web/` uses custom CSS tokens without Tailwind 4; porting 16 pages (charts, lightbox, report viewer, 10 analysis tabs) creates severe CSS collisions and breaks upstream syncability.
  - *Standalone Sub-App Mount (Recommended):* Zero CSS conflicts, preserves Site DNA's visual identity and full 16-page UX, ~6–8 hrs effort, clean rebuild at `sync_agents.py` time.
- **Routing Detail (avoiding URL collision with the platform's catalog detail page):**
  - Currently the platform detail page is at `/agents/:slug` (`/agents/site-dna`).
  - **Recommended path split:** Keep the platform's detail & BYOK setup page at `/agents/site-dna`, and mount the Site DNA static SPA at **`/agents/site-dna/app/`** (or move platform detail route to `/catalog/site-dna` if `/agents/site-dna/` is strictly preferred — listed in Open Question #1). Using `/agents/site-dna/app/` avoids any SPA routing collision between React Router in `web/` and React Router in Site DNA!
  - Configure Vite `base: '/agents/site-dna/app/'` (or `'/agents/site-dna/'`), `<BrowserRouter basename="...">`, and `API_BASE = '/agents-api/site-dna/api/v1'` (wired into `api.ts`, `useRunEvents.ts`, and screenshot URL resolution).
  - Add a visible top-bar breadcrumb `"← العودة إلى وكلاء أساس"` linking back to the platform detail page (where visitors can change key/model or log out).
  - Agent frontend **never** sees the API key or session token (cookie is `HttpOnly`, automatically sent by browser on same-origin `fetch` and `EventSource`).
- **Strict Sub-App CSP:**
  - Main sub-app HTML (`/agents/site-dna/...`):
    ```http
    Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; frame-src 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self';
    ```
    *(Note: `style-src 'unsafe-inline'` is needed for Tailwind/dynamic inline styles; `img-src 'self' data: blob:` for screenshots and download blobs; `frame-src 'self'` strictly for `ReportViewer.tsx` preview iframe; zero external hosts and zero `'unsafe-eval'`.)*
  - Report HTML Preview endpoint (`GET /agents-api/site-dna/api/v1/reports/final/{crawl_id}/{report_id}/preview`):
    ```http
    Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; frame-ancestors 'self'; base-uri 'none'; form-action 'none';
    ```
    Plus `<iframe sandbox="" ...>` (no `allow-scripts`, no `allow-same-origin`, no `allow-top-navigation` — pure static HTML/CSS report preview!).
  - Report Download endpoint (`/download`): `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'`.
- **Page Triage:**
  - `Dashboard` & `History`: **Keep**, strictly session-scoped via proxy.
  - `NewAnalysis` & `AnalysisMonitor` (+ all 10 stage tabs): **Keep**, enhanced with consent checkbox, cost estimator, cancel button, and competitor opt-in.
  - `AgentsDirectory`: **Keep as read-only**.
  - `Settings`: **Keep as read-only** (Language/Theme toggles + read-only display of active provider/model/session TTL fetched from `/api/service-sessions/me`; remove hardcoded `"gemini-3.6-flash"` strings and never show/edit keys).

### S4. LLM Adaptation Inside Site DNA & Platform Gateway Gaps
- **Recommendation:** Add a single gateway client module `src/site_dna/core/llm_gateway.py` inside Site DNA using `httpx` (already a dependency) and a per-run `contextvars.ContextVar` carrying `{llm_endpoint, run_token, model, provider}`. Prompts, rubrics, scoring formulas, and deterministic engines remain **100% untouched**.
- **Agent-Side Adaptation:**
  1. `llm_gateway.py`: Sends OpenAI-compatible `POST {llm_endpoint}/chat/completions` with `Authorization: Bearer {run_token}`:
     - System instructions as `{"role": "system", "content": ...}`.
     - Multimodal images (`PreparedImage`) as `{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}`.
     - JSON mode as `response_format={"type": "json_object"}`.
     - Explicit `max_tokens` and `temperature`.
     - Maps platform normalized error codes (`rate_limited`, `quota_exhausted`, `invalid_key`, `model_not_found`, `unsupported_feature`, `provider_unavailable`) directly into Site DNA's existing `ai_blocked` / `partial` fail-soft states and honest UI labels.
     - Zero retries on `400/401/403/404/429` (aligning with platform D2/D8).
  2. `src/site_dna/core/llm.py`: Update `get_llm()` so when a run context is active, it returns `LLM(model=f"openai/{ctx.model}", base_url=ctx.llm_endpoint, api_key=ctx.run_token, timeout=timeout)` instead of `gemini/...` + `GEMINI_API_KEY`.
  3. Replace all **6** direct `google.genai` call sites (`visual_identity`, `ux_ui`, `content_marketing`, `technical_seo`, `competitor_intelligence/context_builder.py`, `services/gemini_diagnostics.py`) to call `llm_gateway.py`, and **remove all hardcoded `"gemini-3.6-flash"` overrides** (`content_marketing/multimodal_adapter.py:110`, `technical_seo/multimodal_adapter.py:119`, `agents/strategic_intelligence_agent.py:57`).
  4. Remove `GEMINI_API_KEY` from the live service path completely while keeping `offline_mode=True` and all 139 offline tests passing without change.
- **Platform Gateway & Provider Adapter Gap Audit (`api/modules/llm/`):**

| Provider Adapter | System Msg | Multimodal (`image_url` data URL) | JSON Mode (`response_format`) | Current Gaps Found in Platform Code | Remediation in Part B |
| :--- | :---: | :---: | :---: | :--- | :--- |
| **OpenAI** (`openai.py`) | ✅ Pass-through | ✅ Pass-through | ✅ Pass-through | `llm_timeout_seconds` (check value in `config.py`) may be tight for 8-image multimodal payloads; `v1_router.py` needs `max_output_tokens` honored from run context. | Increase multimodal request read timeout (e.g., 90 s) and test 8-image payload. |
| **OpenRouter** (`openrouter.py`) | ✅ Pass-through | ✅ Pass-through | ✅ Pass-through | Same timeout check; some free models ignore `response_format` or lack vision. | Filter strictly via `model_capabilities.json` (`vision: true`, `json_schema: true`). |
| **Gemini** (`gemini.py`) | ✅ Pass-through | ✅ Supported by Gemini OpenAI-compat | ✅ Supported by Gemini OpenAI-compat | Needs empirical Part B eval test with 8 PNG `data:image/png;base64,...` parts + `response_format={"type": "json_object"}` + `system` role. | Run live eval spike in Part B before enabling in `providers.allow`. |
| **Anthropic** (`anthropic.py`) | ✅ Extracted to `payload["system"]` | ❌ **BROKEN BUG at line 73!** | ⚠️ Prompt-injected (`L123–124`) | **Critical bug at `anthropic.py:73`:** `url = img_info.get("url", "")` overwrites `url = f"{self.base_url}/messages"`, crashing line 141 `http.post(url, ...)`! Also `response_format` prompt injection may still emit markdown fences; needs strict `image_url` var rename + optional assistant prefill `"{"` or JSON strip + test with real Anthropic payload. | Fix `img_url` variable shadowing bug, verify `media_type` allowlist (`image/png`, `image/jpeg`, `image/webp`, `image/gif`), add unit test for multimodal + JSON mode. |

### S5. Egress & Isolation (`asaas-service-sitedna`)
- **Recommendation:** Dedicated unprivileged OS user `asaas-service-sitedna` + systemd cgroup v2 + `nftables` UID egress filter + Site DNA's built-in SSRF guards as defense in depth.
- **Linux `nftables` Ruleset (IPv4 + IPv6):**
  ```nftables
  table inet asaas_sitedna_egress {
      chain output {
          type filter hook output priority 0; policy accept;
          meta skuid != asaas-service-sitedna accept

          # 1. Allow loopback ONLY to platform LLM proxy (127.0.0.1:8088) and Site DNA's own replies (established)
          ct state established,related accept
          ip daddr 127.0.0.1 tcp dport 8088 accept
          ip daddr 127.0.0.0/8 drop
          ip6 daddr ::1 drop

          # 2. Allow DNS ONLY to local resolver
          ip daddr 127.0.0.53 udp dport 53 accept
          ip daddr 127.0.0.53 tcp dport 53 accept

          # 3. Drop RFC1918, CGNAT, link-local, cloud metadata, IPv6 ULA/link-local/mapped
          ip daddr { 10.0.0.0/8, 100.64.0.0/10, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/4, 240.0.0.0/4 } drop
          ip6 daddr { fc00::/7, fe80::/10, ff00::/8, ::ffff:0:0/96 } drop

          # 4. Allow outbound HTTP/HTTPS strictly to public addresses
          tcp dport { 80, 443 } accept

          # 5. Drop everything else (non-80/443 ports, raw UDP, ICMP exfil, etc.)
          drop
      }
  }
  ```
- **Systemd / cgroup v2 & Filesystem Isolation:**
  - `User=asaas-service-sitedna`, `Group=asaas-service-sitedna`
  - `MemoryMax=2G`, `CPUQuota=200%`, `TasksMax=96` *(assumptions to tune — Chromium spawns ~15–25 threads/subprocesses)*
  - `PrivateTmp=true`, `ProtectSystem=strict`, `NoNewPrivileges=true`
  - `ReadOnlyPaths=/opt/asaas/agents/site-dna/src /opt/asaas/agents/site-dna/.venv`
  - `ReadWritePaths=/var/lib/asaas/site-dna/runs` (`chmod 0700`, owned by `asaas-service-sitedna`)
  - Zero read permissions on platform `api/.env` or `api/data/app.db` (`0600` owned by `asaas-app`).
- **Chromium Launch Flags Review:**
  - `visual/browser_manager.py`: Keep Chromium sandbox **ENABLED** (already has no `--no-sandbox`).
  - `reporting/pdf_renderer.py`: **Remove `--no-sandbox` and `--disable-setuid-sandbox`**, replace ineffective `--disable-network` with `browser.new_context(offline=True)` + `context.route("**/*", abort)`. Document in `docs/deploy.md` that Linux requires `kernel.unprivileged_userns_clone=1` (or AppArmor userns profile on Ubuntu 24.04+). Only if an operator host disallows user namespaces may `--no-sandbox` be considered exclusively for the offline PDF renderer (rendering trusted self-generated HTML) — never for live target-site crawling — and must be recorded as an accepted exception.
- **Defense in Depth:** Retain `core/security.py` (tightened to block IP literals), `discovery/http_client.py` (connection-time IP pinning), and `visual/browser_security.py` (tightened to validate ports 80/443 and block IP literals).

### S6. Multi-Tenancy, Route Allowlist & Disk Janitor
- **Recommendation:**
  1. **Run-Ownership Registry in Proxy:** Map `session_id -> set[run_id]` and also track `crawl_run_id -> session_id` (note: `coordinator.py:1019` aligns `crawl_result.run_id = record.run_id`, so we must remove the duplicate `old_run_id` directory write at `coordinator.py:1027–1030` so every run has exactly ONE unguessable UUIDv4 `run_id`).
  2. **Strict Proxy Allowlist (exact methods & regexes):**
     - `GET  /api/v1/agents` (read-only agent directory; no session needed or session-gated)
     - `GET  /api/v1/agents/{agent_id}`
     - `GET  /api/v1/runs` *(filtered strictly to `session.runs`)*
     - `POST /api/v1/runs` *(validates URL, consent, limits, mints token, records ownership)*
     - `GET  /api/v1/runs/{run_id}` *(ownership required)*
     - `POST /api/v1/runs/{run_id}/cancel` *(ownership + CSRF required)*
     - `GET  /api/v1/runs/{run_id}/events` *(ownership required; tracks active SSE subscribers)*
     - `GET  /api/v1/runs/{run_id}/screenshots` *(ownership required; rewrites `api_url` prefix)*
     - `GET  /api/v1/runs/{run_id}/artifacts/screenshot` *(ownership required; strict `file` validation)*
     - `GET  /api/v1/runs/{run_id}/findings` *(ownership required)*
     - `GET  /api/v1/runs/{run_id}/recommendations` *(ownership required)*
     - `GET  /api/v1/runs/{run_id}/ai-automation` *(ownership required)*
     - `GET  /api/v1/runs/{run_id}/reports/{stage_id}` *(ownership required)*
     - `GET  /api/v1/dashboard/summary` *(computed strictly from `session.runs` by proxy — NEVER forward global backend summary!)*
     - `POST /api/v1/reports/final` *(ownership of `payload.crawl_run_id` + CSRF required)*
     - `GET  /api/v1/reports/final/{crawl_run_id}` *(ownership required)*
     - `GET  /api/v1/reports/final/{crawl_run_id}/{report_id}` *(ownership required)*
     - `GET  /api/v1/reports/final/{crawl_run_id}/{report_id}/download` *(ownership required; attachment headers)*
     - `GET  /api/v1/reports/final/{crawl_run_id}/{report_id}/preview` *(ownership required; strict preview CSP)*
     - `GET  /api/v1/reports/final/{crawl_run_id}/{report_id}/artifacts` *(ownership required)*
     - **Optional read-only sub-views** (ONLY if AnalysisMonitor tabs require them, strictly ownership-checked on `crawl_run_id` and `GET`-only; ALL `POST /analysis/*` direct stage execution routes are **DENIED**):
       - `GET /api/v1/analysis/competitors/{run_id}` & `/matrix`
       - `GET /api/v1/analysis/security-privacy/{run_id}` & `/headers`
       - `GET /api/v1/analysis/accessibility/{run_id}` & `/wcag`
       - `GET /api/v1/analysis/strategy/{run_id}`, `/actions`, `/conflicts`, `/roadmap`
     - **Explicitly DENIED (404 at proxy):** `/docs`, `/redoc`, `/openapi.json`, `/dashboard/legacy`, `/api/v1/ready`, `/api/v1/discovery`, `/api/v1/visual/*`, `POST /api/v1/analysis/*`, and all unlisted paths.
  3. **Run Data Retention & Disk Janitor:**
     - Run data lives in a private data directory owned by `asaas-service-sitedna` (`SITE_DNA_DATA_DIR`).
     - **Purge policy (replaces erroneous 7-day draft):** Janitor runs every **5 minutes** and purges run directories **60 minutes after a run finishes** *(assumption to tune)* OR immediately when the owning session expires/logs out (after cancelling any active run).
     - **Disk Quotas:** Per-session ceiling **150 MB** *(assumption to tune)* and global Site DNA runs ceiling **1 GB** *(assumption to tune)*; if global quota is exceeded, oldest finished runs are evicted first and new runs are temporarily rejected with `507`/`503`.
     - **Disable cross-run disk cache** (`*_cache_enabled=False`) so no cached model output is ever shared across visitor sessions.

### S7. Target & Abuse Policy
- **Recommendation:** Enforce at BOTH the platform proxy (`POST /runs`) AND Site DNA's `url_validator.py` / `core/security.py` / `browser_security.py`:
  1. **URL Rules:** Only `http://` and `https://`, public DNS hostnames only, ports `80`/`443` only, **reject ALL raw IP literals** (IPv4 and IPv6 — closing the gap in `core/security.py:67–71`), reject embedded credentials (`user:pass@`), revalidate redirects at every hop (already in `http_client.py:184–199`; add same check to Playwright redirects), and explicitly deny the platform's own domain(s) (`settings.platform_own_hosts`) + `localhost`/loopback.
  2. **`robots.txt` Compliance:** Verified already implemented in `discovery/robots_policy.py` and enabled by default (`crawler_respect_robots=True`, `visual_respect_robots=True` in `core/config.py:108,222`). Ensure public API requests cannot disable it.
  3. **Identifying User-Agent:** Crawler uses `SiteDNABot/0.1 (+https://site-dna.asaas.ai/bot)` (`core/config.py:113`); update `visual/browser_manager.py:95–101` so mobile UA also includes `SiteDNABot/0.1 (+https://agents.ai-asaas.com/about)` and point contact URL to the live platform domain.
  4. **Target Origin Deduplication:** At most **1 active run per canonical target origin platform-wide** (prevents using the platform to hammer a single third-party website concurrently); return HTTP `429`/`409` with clear Arabic message if that origin is already being analyzed.
  5. **Visible Consent Checkbox:** Required unchecked-by-default checkbox on `NewAnalysis.tsx` before submission (and validated in `POST /runs` payload `consent_confirmed: true`): *"أُقرّ بأنني مخوّل بتحليل هذا الموقع العام وأتحمل مسؤولية استخدام الأداة."*
  6. **Competitor Intelligence OFF by Default:** Remove `competitor_intelligence` from default selected stages in `NewAnalysis.tsx:198–208`. Require explicit visitor opt-in with a clear Arabic disclosure: *"تفعيل هذه المرحلة سيؤدي إلى زيارة وزحف حتى 3 مواقع منافسة عامة تابعة لأطراف ثالثة للمقارنة المعيارية، ويستهلك استدعاءات إضافية من مفتاحك."* Also cap competitors at 3 domains, depth 1 (max 2–3 pages per competitor) and block `competitor_urls` unless validated against the same target policy.
  7. **Legal Draft Updates:** Update `/terms` and `/privacy` pages in `web/` to describe public-site crawling, optional third-party competitor fetching, user consent, and the 60-minute artifact retention window — explicitly labeled **"مسودة قيد المراجعة القانونية من فريق أساس (Draft for ASAAS Legal Review)"**.

### S8. Cost Transparency & Free-Tier Budgeting
- **Recommendation:**
  - Before starting a run, `NewAnalysis.tsx` fetches active session info (`provider`, `model`, free-tier limits from platform `/api/providers/limits` backed by `api/config/provider_limits.json`).
  - Display a live **Estimated Model Calls** badge per stage and in total, derived from the real backend stage settings (showing both *expected single-pass calls* e.g. 4–6 calls and *configured ceiling* e.g. up to 12–27 calls).
  - Compare the total against the visitor's provider free-tier RPM/RPD limits and display a clear Arabic warning banner when the selected stages approach or exceed the free daily budget.
  - **Default Stage Selection:** Set default selection to the **Free-Tier Safe Core Subset** (excluding `competitor_intelligence` and keeping `max_pages = 5`), with an explicit *"تحديد الكل (يتضمن المنافسين)"* button and a *"وضع التدقيق الحتمي (0 استدعاءات AI)"* option clearly offered.

### S9. Real Cancel & Abandoned-Tab Cleanup
- **Recommendation:**
  1. **Site DNA `POST /api/v1/runs/{run_id}/cancel`:**
     - `AnalysisCoordinator` stores active `asyncio.Task` handles (`self._run_tasks: dict[str, asyncio.Task]`) and active `BrowserManager` instances (`self._run_browsers: dict[str, BrowserManager]`) per `run_id`.
     - Cancelling calls `task.cancel()`, closes/kills any Playwright Chromium child processes for that run within 2 seconds, removes partial temp files (or marks for immediate cleanup), persists `status = "cancelled"`, emits `run.cancelled` SSE event, and closes subscriber queues.
     - Thread-pool stages (`asyncio.to_thread(...)` in `coordinator.py:1147,1208,1269,1331,1396`) check a per-run `threading.Event` cancel flag before/after LLM calls so blocked threads exit promptly without making further billable calls.
  2. **Platform Wiring:**
     - `POST /agents-api/site-dna/api/v1/runs/{run_id}/cancel` checks session ownership + CSRF, immediately revokes `art_...` in `RunTokenRegistry` (so even an in-flight LLM call fails fast with 401 and burns zero further visitor quota!), releases concurrency & target-origin slots, and forwards cancel to Site DNA.
     - Add a prominent **"إيقاف التحليل (إلغاء)"** button in `AnalysisMonitor.tsx` whenever `isRunning === true`.
  3. **Abandoned-Tab Auto-Cancel Rule:**
     - The platform proxy tracks active SSE subscriber counts per `run_id` on `/runs/{run_id}/events`.
     - When the last SSE subscriber disconnects (e.g., visitor closes tab) and no subscriber reconnects within **2 minutes (120 seconds)** *(assumption to tune)*, the proxy automatically triggers full run cancellation (revokes `art_...` token, sends `POST /runs/{run_id}/cancel` to Site DNA, releases slots). Grace period allows normal page refreshes/navigation between tabs without interrupting a run.

### S10. Packaging & Sync (`scripts/sync_agents.py`)
- **Recommendation:** Extend `scripts/sync_agents.py` to support `runtime.kind == "service"` entirely at sync/deploy time (zero runtime downloads or installs):
  1. Clone `github.url` into `agents/site-dna/src` at `github.pinned_ref` (full 40-char SHA) and strictly assert `git rev-parse HEAD == pinned_ref`.
  2. Install Python dependencies into `agents/site-dna/.venv` using `uv sync --frozen --no-dev --python 3.11` (uses `uv.lock` with SHA-256 hashes for all 161 packages).
  3. Install Playwright Chromium binary into an agent-owned directory (`PLAYWRIGHT_BROWSERS_PATH=agents/site-dna/.playwright-browsers`) via `uv run playwright install chromium`.
  4. Build the frontend sub-app in `agents/site-dna/src/frontend` using `npm ci` + `VITE_BASE_PATH=/agents/site-dna/app/ VITE_API_BASE=/agents-api/site-dna/api/v1 npm run build`, copying `dist/` to `agents/site-dna/frontend-dist/`.
  5. Clean up partial artifacts on any step failure.
- **One-Time Root Provisioning Steps (to document in `docs/deploy.md`):**
  ```bash
  # 1. Create unprivileged service user & private data dir
  sudo useradd --system --no-create-home --shell /usr/sbin/nologin asaas-service-sitedna
  sudo mkdir -p /var/lib/asaas/site-dna/runs
  sudo chown asaas-service-sitedna:asaas-service-sitedna /var/lib/asaas/site-dna/runs
  sudo chmod 0700 /var/lib/asaas/site-dna/runs

  # 2. Install Playwright Chromium OS libraries (one-time root step)
  sudo /opt/asaas/agents/site-dna/.venv/bin/playwright install-deps chromium

  # 3. Verify unprivileged user namespaces for Chromium sandbox
  sysctl kernel.unprivileged_userns_clone

  # 4. Install systemd unit (cgroup v2 limits) & nftables egress rules
  sudo systemctl enable --now asaas-sitedna.service
  sudo nft -f /etc/nftables.d/asaas-sitedna.nft
  ```

### S11. Provider Quality, Manifest Requirements & Expected Performance
- **Recommendation:**
  - **Derived `model_requirements` (from actual code inspection):**
    - `vision: true` — Required by `visual_identity` and `ux_ui` (up to 8 desktop/mobile screenshots per stage).
    - `json_schema: true` — Required by `visual_identity`, `ux_ui`, `content_marketing`, `technical_seo` (`response_format={"type": "json_object"}`).
    - `tool_calling: false` — Verified! In the `coordinator._execute_pipeline()` runtime path, none of the LLM calls require OpenAI function/tool calling (deterministic tools run in Python first, then evidence is passed to LLM prompts). Setting `tool_calling: false` avoids unnecessarily excluding vision-capable models that don't advertise tool calling.
    - `min_context_tokens: 64000` — Derived from up to 8 screenshots (~2,000–4,000 vision tokens each = ~16k–32k) + 8-page DOM/CSS/text context JSON (~10k–20k tokens) + system prompt + 4k output.
  - **`providers.allow` Gating Rule:** Prompts were authored and tuned against Google Gemini. Initially list **only providers verified by Part B live evals**. Start Part B evaluation with `["gemini", "openai", "openrouter"]` (and `"anthropic"` once the `anthropic.py:73` bug is fixed and evaluated); **remove any provider from `providers.allow` that fails JSON schema adherence, Arabic output quality, or vision analysis in Part B evals**.
  - **Expected Calls & Runtime on a Typical 5-Page Website:**
    - *Core Default Subset (no competitors):* **5 LLM calls**, **~90 to 210 seconds** (1.5–3.5 min: ~15 s crawl, ~35 s Playwright capture, ~30–90 s LLM stages, ~15 s HTML/PDF render).
    - *Full Audit (with 3 competitors):* **6 LLM calls** (up to 27 ceiling if future stages enable multi-call), **~3 to 6 minutes** (additional ~90–150 s for crawling 3 competitor sites).

---

## 3. Platform Changes Required (Including Remediation of 12 Draft Defects)

### A. Fixes Required in Existing Draft Files
1. `api/modules/llm/adapters/anthropic.py:73`: Rename shadowed local variable `url` -> `img_url` so multimodal image requests do not overwrite the Anthropic API endpoint URL.
2. `api/modules/runtime/service_proxy.py:240–287`: Mint `art_...` token **before** calling Site DNA `POST /runs`; inject `X-Run-Token`, `X-LLM-Endpoint`, `X-LLM-Model`, `X-LLM-Provider`; fix double `acquire_run_slot()` call (currently double-counts daily quota).
3. `api/modules/runtime/service_proxy.py:309–327`: Compute `GET /dashboard/summary` strictly from the caller's session runs instead of returning the global backend summary.
4. `api/modules/runtime/service_proxy.py:407`: Strip `Cookie` and `Authorization` headers before forwarding requests to Site DNA so the session cookie never leaks to the agent process.
5. `api/modules/runtime/service_proxy.py:132,159`: Remove `session_id` from JSON response bodies of `/api/service-sessions/init` and `/me` (session ID stays `HttpOnly` cookie-only).
6. `api/modules/runtime/service_proxy.py:98,237`: Use `extract_client_ip(request)` instead of raw `request.client.host`.
7. `api/modules/runtime/service_proxy.py:45–58`: Fail closed on missing `Origin`/`Sec-Fetch-Site` on state-changing routes (currently skips check if `origin` is absent!).
8. `api/modules/runtime/service_proxy.py:19–30`: Align route allowlist with Site DNA's actual endpoints (including `/artifacts/screenshot`, `/findings`, `/recommendations`, `/ai-automation`, `/reports/{stage_id}`, `POST /reports/final`, `/reports/final/{id}/*`, and read-only scoped `/analysis/*` views if needed) and add target URL validation + consent check + per-origin concurrency lock + SSE disconnect watcher.
9. `api/modules/runtime/service_supervisor.py:85–106`: Replace `os.environ.copy()` with minimal explicit sanitized env, remove `shell=True` (use `argv` list), fix `%e` -> `%s` logging bug, and apply Linux UID drop when running on Linux.
10. `api/modules/runtime/token_registry.py`: Add `ttl_seconds` expiry enforcement on `RunContext` and automatic cleanup.
11. `api/modules/runtime/janitor.py`: Change retention from 7 days to **60 minutes post-completion** (or immediate on session expiry), add per-session (150 MB) and global (1 GB) disk quotas, and cancel active runs of expired sessions before purging.
12. `api/modules/runtime/v1_router.py:192`: Add loopback + reverse-proxy header denial checks to `GET /v1/models` matching `/v1/chat/completions`.

### B. Additional Platform Changes
- `api/config.py`: Add explicit service-tier ceiling settings (`service_max_wall_clock_seconds=1200`, `service_max_concurrent_global=2`, `service_max_concurrent_per_ip=1`, `service_daily_runs_per_ip=3`, `service_run_retention_minutes=60`, `service_disk_quota_session_mb=150`, `service_disk_quota_global_mb=1024`, `service_sse_orphan_cancel_seconds=120`, `platform_own_hosts`).
- `api/config/provider_limits.json`: Re-verify and update current Google AI Studio free-tier RPD/RPM limits.
- `api/main.py`: Mount Site DNA static frontend build (`agents/site-dna/frontend-dist`) with strict sub-app CSP headers at `/agents/site-dna/app/`, wire `ServiceSupervisor` and `DataJanitor` in lifespan (only if `site-dna` manifest is active/synced).
- `scripts/sync_agents.py`: Add service-tier sync branch (`uv sync --frozen --python 3.11`, `playwright install chromium` into agent-owned `PLAYWRIGHT_BROWSERS_PATH`, `npm ci && npm run build`).
- `web/src/pages/AgentDetail.tsx`: For `playground.mode === "standalone"`, call `POST /api/service-sessions/init` after key/model validation and render an *"افتح وكيل بصمة الموقع (Site DNA)"* button navigating to `/agents/site-dna/app/`.
- `web/src/pages/Terms.tsx` & `web/src/pages/Privacy.tsx`: Add draft disclosures (marked for ASAAS legal review) covering public-site crawling, opt-in competitor crawling, consent, and 60-minute retention.
- `docs/deploy.md` & `docs/operations.md`: Document one-time Linux root steps (`playwright install-deps`, `asaas-service-sitedna` user, systemd unit, `nftables` rules).

---

## 4. Agent-Side Changes (Site DNA Repository)

| File | Required Change |
| :--- | :--- |
| `src/site_dna/core/llm_gateway.py` *(NEW)* | Unified OpenAI-compatible HTTP client targeting `{llm_endpoint}/chat/completions` with `Bearer {run_token}` from a per-run `ContextVar`; handles system messages, base64 image data URLs, JSON mode, normalized error mapping (`rate_limited`, `quota_exhausted`, etc.), and cancellation check. |
| `src/site_dna/core/llm.py` | Update `get_llm()` to read per-run context and return CrewAI `LLM(model=f"openai/{model}", base_url=endpoint, api_key=run_token)` without `GEMINI_API_KEY`. |
| `src/site_dna/core/config.py` | Add `data_dir` (env `SITE_DNA_DATA_DIR`, default `"runs"`), `service_mode` flag (disables shared disk caches), `blocked_target_hosts`, and `max_pages` public cap. |
| `src/site_dna/core/security.py` | Reject **all** raw IP literals (IPv4 & IPv6) in `resolve_and_validate_host()` and reject `platform_own_hosts`. |
| `src/site_dna/visual/browser_security.py` | Enforce allowed ports `80`/`443` and reject raw IP literals + `platform_own_hosts` on every browser navigation and redirect. |
| `src/site_dna/visual/browser_manager.py` | Include identifying `SiteDNABot/0.1 (+https://...)` in mobile User-Agent too; expose instance handle for clean cancellation termination. |
| `src/site_dna/reporting/pdf_renderer.py` | Remove `--no-sandbox`, `--disable-setuid-sandbox`, and invalid `--disable-network`; launch with `browser.new_context(offline=True)` + `context.route("**/*", abort)`. |
| `src/site_dna/orchestration/coordinator.py` | Upgrade `run_id` to full UUIDv4; remove duplicate `old_run_id` directory write; accept per-run LLM context (`run_token`, `llm_endpoint`, `model`) in memory only (never write to `execution.json`); store task + cancel `threading.Event` + active `BrowserManager` for real `cancel_run()`; clamp `max_pages`; fix `resolve_screenshot_path` to use `.is_relative_to()`; make `api_url` relative or configurable. |
| `src/site_dna/api/routes/runs.py` | Read `X-Run-Token`, `X-LLM-Endpoint`, `X-LLM-Model`, `X-LLM-Provider` headers on `POST /runs`; add `POST /runs/{run_id}/cancel`; use configurable `data_dir`. |
| `src/site_dna/api/routes/final_reports.py` | Use configurable `data_dir` instead of hardcoded `Path("runs")` at line 140. |
| `src/site_dna/analysis/visual_identity/multimodal_adapter.py` | Route calls through `llm_gateway.py`; map platform error codes to `ai_blocked`/`partial`; disable shared cache in service mode. |
| `src/site_dna/analysis/ux_ui/multimodal_adapter.py` | Same as above. |
| `src/site_dna/analysis/content_marketing/multimodal_adapter.py` | Route calls through `llm_gateway.py`; **remove hardcoded `"gemini-3.6-flash"` override at L110–111**. |
| `src/site_dna/analysis/technical_seo/multimodal_adapter.py` | Route calls through `llm_gateway.py`; **remove hardcoded `"gemini-3.6-flash"` override at L119–120**. |
| `src/site_dna/analysis/competitor_intelligence/context_builder.py` | Route `_discover_with_gemini` through `llm_gateway.py` (renamed `_discover_with_llm`); respect `competitor_discovery_enabled` and depth/domain caps. |
| `src/site_dna/agents/strategic_intelligence_agent.py` | **Remove hardcoded `model="gemini/gemini-3.6-flash"` at L57**; use `get_llm(settings=settings)`. |
| `src/site_dna/services/gemini_diagnostics.py` | Route diagnostic probe through `llm_gateway.py` when run context is active (preserve offline unit tests). |

*(All prompts, rubrics, scoring math, deterministic analyzers, and offline tests remain untouched.)*

---

## 5. Frontend Changes (Site DNA Frontend)

| File | Required Change |
| :--- | :--- |
| `frontend/vite.config.ts` | Support `base: process.env.VITE_BASE_PATH || '/'`; remove hardcoded dev proxy assumptions in production build. |
| `frontend/src/App.tsx` | Pass `basename={import.meta.env.BASE_URL.replace(/\/$/, '') || '/'}` to `<BrowserRouter>`. |
| `frontend/src/lib/api.ts` | Set `const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'`; fix `getDownloadReportUrl` and `getPreviewReportUrl` (L239–241) to use `API_BASE`; add `cancelRun(runId)` and `getSessionInfo()` (`/api/service-sessions/me`) + `getProviderLimits()` (`/api/providers/limits`); handle HTTP `401` by redirecting/prompting return to platform key setup. |
| `frontend/src/lib/useRunEvents.ts` | Replace hardcoded `/api/v1/runs/...` (L42) with `${API_BASE}/runs/...`; listen to `run.cancelled`. |
| `frontend/src/pages/ScreenshotExplorer.tsx` | Prefix/resolve `item.api_url` against `API_BASE` so screenshots load through `/agents-api/site-dna/api/v1`. |
| `frontend/src/pages/NewAnalysis.tsx` | (1) Default `competitor_intelligence` **OFF** with explicit Arabic opt-in disclosure; (2) Hide/remove 50-page `full_site_scan` in public mode (clamp `maxPages <= 8`); (3) Add required visible **consent checkbox**; (4) Add live **Model-Call Cost Estimator** comparing selected stages against active provider's free-tier limits with clear warning banner. |
| `frontend/src/pages/AnalysisMonitor.tsx` | Add visible **"إلغاء التحليل" (Cancel)** button wired to `api.cancelRun(runId)` when running; display `cancelled` status pill. |
| `frontend/src/pages/ReportViewer.tsx` | Add strict `sandbox=""` attribute on the report preview `<iframe>` (L238). |
| `frontend/src/pages/Settings.tsx` | Convert to read-only session status view (showing active provider, model, and remaining session TTL from `/api/service-sessions/me`, plus Language/Theme toggles; remove hardcoded `gemini-3.6-flash` label). |
| `frontend/src/components/Layout.tsx` | Add a clean top-bar link `"← العودة إلى وكلاء أساس"` pointing back to `/agents/site-dna`. |

---

## 6. Security Invariants to Be Tested in Part B

Every invariant below requires **one violating-case check** and **one legitimate-case check** in an automated verification suite:

1. **Zero Key Leakage:** Real visitor key never appears in Site DNA `os.environ`, command line, `runs/*/execution.json`, `events.jsonl`, logs, SQLite, or HTTP headers sent to Site DNA; `Cookie` header is stripped by proxy before forwarding.
2. **Run Token Lifecycle & Model Pinning:** Calling `127.0.0.1:8088/v1/chat/completions` with an `art_...` token after run completion/cancellation/TTL expiry returns `401`; requesting a different model is overridden to the session's authorized model.
3. **Cross-Session Tenant Isolation:** Session B receives `404` on Session A's `GET /runs/{id}`, `/events`, `/findings`, `/recommendations`, `/screenshots`, `/artifacts/screenshot`, and `/reports/final/{id}/*`; Session B's `GET /runs` and `GET /dashboard/summary` contain zero records or counts from Session A.
4. **Route Allowlist & Direct Stage Denial:** Requests to `/docs`, `/openapi.json`, `/dashboard/legacy`, `/api/v1/ready`, `/api/v1/discovery`, `POST /api/v1/analysis/ux-ui`, etc. return `404` at the proxy boundary without reaching Site DNA.
5. **CSRF & Session Cookie Hardening:** Cookie has `HttpOnly`, `SameSite=Strict`, `Secure` (on HTTPS) and is absent from JSON bodies; `POST /runs` or `POST /runs/{id}/cancel` with a foreign or missing `Origin` returns `403`.
6. **Target SSRF & Abuse Policy:** `POST /runs` rejects raw IP literals (`http://1.1.1.1`, `http://127.0.0.1`), private/metadata hostnames, non-80/443 ports, embedded credentials (`user:pass@`), platform's own host, missing consent (`consent_confirmed=false`), and concurrent duplicate target origins; valid public URLs with consent succeed.
7. **Cancel & Abandoned-Tab Cleanup:** `POST /runs/{id}/cancel` revokes the `art_...` token immediately, kills Chromium child processes within 2 s (zero orphans), and updates status to `cancelled`; disconnecting all SSE listeners triggers automatic cancel after the configured grace period.
8. **PDF & Preview Isolation:** PDF download returns `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'`; HTML preview returns strict zero-script CSP and renders in `sandbox=""` iframe; Chromium PDF renderer runs with `offline=True` and aborts all network requests.
9. **Disk Retention & Quotas:** Janitor purges finished run directories older than 60 minutes (and immediately on session expiry) and enforces global/per-session disk caps.
10. **Linux Kernel Isolation (Linux Test Rig Only — Marked Skip on Windows):** `asaas-service-sitedna` cannot connect to `10.0.0.1`, `169.254.169.254`, or `127.0.0.1:5432`, cannot read `api/.env` or `api/data/app.db`, CAN connect to `127.0.0.1:8088` and public HTTPS, and is bounded by cgroup `MemoryMax`/`TasksMax`.
11. **Offline Regression Suite:** Site DNA's existing offline suite (`uv run pytest -m "not integration"`) passes 100% after all Part B edits.

---

## 7. Step-by-Step Implementation Plan & Effort Estimate (Part B)

| Step | Scope & Key Deliverables | Est. Effort |
| :---: | :--- | :---: |
| **1** | **Platform Fixes & Extensions:** Fix the 12 draft defects (`anthropic.py:73`, `service_proxy.py`, `service_supervisor.py`, `token_registry.py`, `janitor.py`, `v1_router.py`), add service ceilings in `config.py`, update `provider_limits.json`, add target-origin lock & SSE orphan watcher. | **10–12 hrs** |
| **2** | **Site DNA LLM Adaptation & Cancel:** Implement `llm_gateway.py`, update `core/llm.py` and all 6 `google.genai` call sites, remove hardcoded `"gemini-3.6-flash"` overrides, disable shared disk cache in service mode, add real `cancel_run()` + `POST /runs/{id}/cancel`, upgrade `run_id` to UUIDv4, fix `resolve_screenshot_path` & `pdf_renderer.py`. | **10–12 hrs** |
| **3** | **Target Policy & SSRF Tightening:** Reject IP literals & platform hosts in `core/security.py`, `url_validator.py`, and `browser_security.py`; enforce port 80/443 in Playwright; clamp `max_pages` and competitor bounds. | **3–4 hrs** |
| **4** | **Site DNA Frontend & Platform Shell Wiring:** Configure Vite `base`, Router `basename`, `API_BASE`, fix hardcoded `/api/v1` refs, add consent checkbox, competitor opt-in, cost estimator, cancel button, `sandbox=""` iframe, read-only Settings, back link, and Platform `AgentDetail.tsx` handoff + `/terms` & `/privacy` draft updates. | **6–8 hrs** |
| **5** | **Packaging (`sync_agents.py`) & Linux Sandbox Docs:** Extend `sync_agents.py` for `service` tier (`uv sync --frozen --python 3.11`, agent-owned Playwright install, `npm ci && npm run build`); finalize `docs/deploy.md` (`nftables`, systemd cgroup unit, `playwright install-deps`). | **4–5 hrs** |
| **6** | **Verification & Provider Evals:** Run Site DNA offline pytest suite (139 files), run all 11 security invariant tests (Linux kernel tests on Linux rig/Docker if available, else explicitly marked Linux-only), run live BYOK evals per provider to lock `providers.allow`, and verify responsive UI at 375 px. | **6–8 hrs** |
| | **Total Estimated Effort** | **~39–49 hours** (~5–6 working days) |

---

## 8. Open Questions for the User (Max 8)

Please review and reply with **"APPROVED"** plus your choices on any item where you prefer an override:

1. **Sub-App Mount Path vs. Platform Detail Page Route:**  
   The platform currently routes agent detail & BYOK setup at `/agents/:slug` (`/agents/site-dna`). Should we mount Site DNA's standalone React app at **`/agents/site-dna/app/`** (keeping `/agents/site-dna` as the platform's key/model setup page), or move the platform detail route to `/catalog/site-dna` so the sub-app owns `/agents/site-dna/` directly?  
   *(Recommended: Mount sub-app at **`/agents/site-dna/app/`** — zero breaking change to existing catalog links `/agents/:slug` and clean separation between setup shell and sub-app.)*
2. **Pinned Commit SHA & Agent-Side Code Changes Location:**  
   Part B requires code edits inside Site DNA (`llm_gateway.py`, `cancel_run`, removing hardcoded `gemini-3.6-flash`, frontend `base`/consent/cost estimator). Should I apply those edits on a branch/PR for `https://github.com/Mahmoodbamatraf/site-dna` (which you then push and give me the resulting 40-char `pinned_ref` SHA), or apply them locally under `agents/site-dna/src` first for local testing before you push?  
   *(Recommended: Apply and test locally in `agents/site-dna/src` during Part B with `--skip-git`, then push to `site-dna` `main` and lock the resulting 40-char commit SHA in `agent.manifest.json`.)*
3. **Run Artifact Retention Window & Disk Quota:**  
   Confirm the **60-minute post-completion** purge window (or immediate purge on session logout/expiry) with **150 MB per-session** and **1 GB global** disk caps (replacing the 7-day retention found in the pre-existing draft `janitor.py`)?  
   *(Recommended: Yes — 60 minutes + 150 MB / 1 GB caps protect server disk and visitor privacy.)*
4. **Max Pages Cap in Public Demo:**  
   Site DNA's `NewAnalysis.tsx` currently includes a `"Full Site Scan"` option that crawls up to **50 pages** (up to 100 Chromium screenshots). Should we hide `"Full Site Scan"` in the public demo and clamp `max_pages` to **8 pages** (default **5**)?  
   *(Recommended: Yes — clamping to 8 pages keeps runs within 2–5 minutes and 8–25 MB disk.)*
5. **Abandoned-Tab Auto-Cancel Grace Period:**  
   If a visitor closes the tab while an analysis is running, is a **2-minute (120 s)** zero-SSE-subscriber grace period before automatically cancelling the run and revoking the token acceptable?  
   *(Recommended: Yes — 2 minutes prevents accidental cancellation on brief reloads while stopping runaway quota burn.)*
6. **Service Limits (Assumptions to Tune):**  
   Do you accept the initial defaults: **45 min sliding / 2 hr max session**, **20 min wall-clock**, **2 concurrent runs platform-wide**, **1 per IP**, **3 per IP/day**, and **1 active run per target origin**?  
   *(Recommended: Accept all defaults and tune after one week of real usage.)*
7. **Thmanyah Font Embedding in Publicly Downloaded PDFs:**  
   Site DNA embeds the proprietary Thmanyah WOFF2 fonts as base64 inside exported HTML/PDF reports. Please confirm ASAAS's license (`LICENSE.pdf` / `LICENSE-ar.pdf`) permits embedding them in reports downloaded by public visitors, or whether public PDFs should fall back to an open Arabic font (e.g., IBM Plex Sans Arabic / Noto Sans Arabic).  
   *(Recommended: Verify against `LICENSE-ar.pdf` before public launch; keep Thmanyah if permitted by ASAAS's license, otherwise switch PDF export font only.)*
8. **Initial `providers.allow` Scope for Part B Live Evals:**  
   Should Part B run live evals across **Gemini + OpenAI + OpenRouter + Anthropic** (enabling only those that pass), or launch initially with **`["gemini", "openai", "openrouter"]`** and add Anthropic after fixing `anthropic.py:73` and testing it?  
   *(Recommended: Fix `anthropic.py:73` in Part B and include only providers verified passing by live evals in `providers.allow`.)*

---

## 9. Draft Agent Manifest (`agents/site-dna/agent.manifest.json`)

> Replace `"pinned_ref"` with the exact 40-character commit SHA once Part B agent changes are committed to `Mahmoodbamatraf/site-dna` `main`, and restrict `"providers.allow"` strictly to providers verified in Part B evals.

```json
{
  "schema_version": 1,
  "slug": "site-dna",
  "name": {
    "ar": "بصمة الموقع (Site DNA)",
    "en": "Site DNA"
  },
  "summary": {
    "ar": "تدقيق استراتيجي شامل للمواقع الإلكترونية عبر 11 مرحلة: الهوية البصرية، تجربة المستخدم، المحتوى، SEO التقني، الأمان، إمكانية الوصول وتصدير PDF.",
    "en": "Multi-stage AI website intelligence audit covering visual identity, UX/UI, content, technical SEO, security, WCAG 2.2 accessibility, and executive PDF reports."
  },
  "description": {
    "ar": "منظومة متكاملة لتحليل المواقع العامة تجمع بين الزحف الحتمي الآمن، التصيير عبر متصفح Chromium لسطح المكتب والجوال، والتحليل الذكي متعدد الوسائط لإنتاج خرائط طريق تنفيذية وتقارير PDF احترافية باللغة العربية.\n\nتعمل جميع المراحل الذكية على مفتاحك الخاص (BYOK) عبر جلسة مؤقتة في الذاكرة فقط، مع إمكانية اختيار مراحل محددة لتناسب الحصة المجانية لمزودك.",
    "en": "Comprehensive public website auditing service combining safe deterministic crawling, dual-viewport Chromium rendering, and multimodal AI analysis to produce prioritized roadmaps and executive PDF reports on your own API key."
  },
  "category": "marketing-analytics",
  "icon": "globe",
  "status": "ready",
  "featured": true,
  "is_sample": false,
  "github": {
    "url": "https://github.com/Mahmoodbamatraf/site-dna",
    "pinned_ref": "0000000000000000000000000000000000000000"
  },
  "runtime": {
    "kind": "service",
    "python": "3.11",
    "egress_policy": "public_http",
    "service_spec": {
      "command": ".venv/bin/uvicorn site_dna.api.main:app --host 127.0.0.1 --port 8001 --workers 1",
      "host": "127.0.0.1",
      "port": 8001,
      "health_check_path": "/api/v1/health",
      "route_allowlist": [
        "^/api/v1/agents$",
        "^/api/v1/agents/[a-z0-9_]+$",
        "^/api/v1/dashboard/summary$",
        "^/api/v1/runs$",
        "^/api/v1/runs/run-[0-9a-f]{32}$",
        "^/api/v1/runs/run-[0-9a-f]{32}/cancel$",
        "^/api/v1/runs/run-[0-9a-f]{32}/events$",
        "^/api/v1/runs/run-[0-9a-f]{32}/screenshots$",
        "^/api/v1/runs/run-[0-9a-f]{32}/artifacts/screenshot$",
        "^/api/v1/runs/run-[0-9a-f]{32}/findings$",
        "^/api/v1/runs/run-[0-9a-f]{32}/recommendations$",
        "^/api/v1/runs/run-[0-9a-f]{32}/ai-automation$",
        "^/api/v1/runs/run-[0-9a-f]{32}/reports/[a-z0-9_]+$",
        "^/api/v1/reports/final$",
        "^/api/v1/reports/final/run-[0-9a-f]{32}$",
        "^/api/v1/reports/final/run-[0-9a-f]{32}/[a-zA-Z0-9_-]+$",
        "^/api/v1/reports/final/run-[0-9a-f]{32}/[a-zA-Z0-9_-]+/(download|preview|artifacts)$",
        "^/api/v1/analysis/competitors/run-[0-9a-f]{32}(/matrix)?$",
        "^/api/v1/analysis/security-privacy/run-[0-9a-f]{32}(/headers)?$",
        "^/api/v1/analysis/accessibility/run-[0-9a-f]{32}(/wcag)?$",
        "^/api/v1/analysis/strategy/run-[0-9a-f]{32}(/(actions|conflicts|roadmap))?$"
      ]
    }
  },
  "playground": {
    "mode": "standalone",
    "ui": "site-dna",
    "mount_path": "/agents/site-dna/app/",
    "api_base": "/agents-api/site-dna/api/v1"
  },
  "model_requirements": {
    "tool_calling": false,
    "json_schema": true,
    "vision": true,
    "min_context_tokens": 64000
  },
  "providers": {
    "allow": ["gemini"]
  },
  "limits": {
    "max_steps": 15,
    "timeout_seconds": 180,
    "max_input_chars": 2000,
    "max_output_tokens": 4096,
    "max_wall_clock_seconds": 1200,
    "platform_concurrent_runs": 2,
    "session_concurrent_runs": 1,
    "session_daily_runs": 3,
    "max_pages_per_run": 8
  }
}
```
