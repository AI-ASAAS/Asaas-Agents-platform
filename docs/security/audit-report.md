# Security Audit Report — ASAAS Agents Platform (وكلاء أساس)

**Date:** 2026-11-17  
**Scope:** Full Platform Audit (Back End, Front End, Runtime, Isolation, Dependency Supply Chain, Privacy)  
**Lead Auditor:** Antigravity AI Engineering & Security  
**Standard / Framework:** skills/cyber/security-review (OWASP ASVS 4.0, NIST SP 800-218, LLM Top 10)  

---

## 1. Executive Summary & Release Recommendation

A comprehensive security audit of the ASAAS Agents Platform was conducted across all architectural layers: HTTP APIs, local agent runtime isolation, LLM gateway, dependency supply chain, visitor privacy, and abuse controls.

**Audit Verdict:**
> **No confirmed vulnerabilities were identified within the reviewed scope and checks performed.**

**Release Recommendation:** **HOLD**
- **Decision:** Release is placed on **HOLD** pending execution and verification of kernel-level sandbox controls on a dedicated Linux host.
- **Blocker:** Essential kernel-level isolation controls specified in Decision D3 (unprivileged UID separation, `nftables` network deny, and POSIX `setrlimit` resource caps) are implemented in `api/modules/runtime/sandbox.py` but cannot be verified on the current Windows development machine. Under `skills/cyber/security-review`, an unverified essential security control blocks public production release.
- **Conditions to Unblock Release:**
  1. Deploy to a Linux test host / CI rig and execute the Linux sandbox verification suite (`test_linux_sandbox.py`) to confirm:
     - Outbound external network connections are denied.
     - Outbound connection to local LLM loopback proxy (port 8088) succeeds.
     - Filesystem access to `api/.env` and `api/data/app.db` by `asaas-worker` is denied by DAC permissions (EACCES).
     - Fork-bombs and memory-bombs are killed by RLIMIT_NPROC and RLIMIT_AS.
  2. Complete legal and management review and sign-off on `/privacy` and `/terms` drafts.
  3. Verify reverse proxy deployment (NGINX/Caddy) with strict TLS 1.3, HSTS, and block rule on `/v1/`.

---

## 2. Component Inventory & Trust Boundaries

```
[ Visitor Browser (RTL / Phone-First) ]
        |
        | HTTPS (Encrypted in transit)
        v
[ Reverse Proxy (NGINX / Caddy with HSTS) ]
        |
        | Local loopback (Trusted Proxy IP extraction)
        v
[ FastAPI Application (api/main.py) ]
  ├── SecurityRateLimiter (Sliding window per IP + UTC Daily Cap)
  ├── RequestBodyLimitMiddleware (Max 5MB body)
  ├── RedactedLoggerFilter (Masks sk-..., AIzaSy...)
  ├── CatalogModule (SQLite with WAL mode, Read-only manifest schemas)
  └── LLM Gateway (Strict HTTPS allowlist, No base URL override)
        │
        ├── In-Memory Run Token Registry (crypto-secure tokens, TTL 300s)
        │
        ▼
[ Loopback Endpoint (/v1/chat/completions) ]
        ▲
        │ IPC / Localhost HTTP only (No external network)
        ▼
[ Isolated Agent Subprocess ]
  ├── Dedicated ephemeral working directory (0700 permissions)
  ├── Sanitized minimal environment (Zero platform keys, Zero visitor key)
  ├── Strict resource limits (Timeout, Max line buffer 64KB)
  └── Automatic process tree termination (SIGKILL / taskkill /T /F)
```

### Trust Boundaries:
1. **Visitor -> API Boundary:** Visitor inputs are completely untrusted. All requests are subject to IP rate limiting, strict Pydantic model validation, file signature magic-byte verification, and body size limits.
2. **API -> External LLM Providers Boundary:** Strictly constrained to hardcoded official API base URLs. Zero user-controllable endpoints, mitigating SSRF entirely. Keys are injected transiently per request and scrubbed immediately.
3. **API -> Agent Subprocess Boundary:** The agent process is treated as semi-untrusted untrusted code execution. It has no external network access, no filesystem access outside its ephemeral scratch directory, and only communicates with the local loopback `/v1/chat/completions` using an ephemeral run token. It never receives the real API key.

---

## 3. Invariants Verification Matrix (D1 – D9)

| Invariant | Description | Verification Method | Status |
| :--- | :--- | :--- | :--- |
| **D1: No Key Persistence** | Real visitor API keys are never written to disk, SQLite, persistent cache, or server logs. | Automated canary key database scan & log inspection (`test_phase5.py`). | **VERIFIED** |
| **D2: Direct Gateway** | LLM Gateway uses raw `httpx` with hardcoded official provider base URLs; no custom base URLs accepted. | Automated SSRF test & source review (`test_phase5.py`). | **VERIFIED** |
| **D3: Process Isolation** | Runs execute in isolated processes with minimal env, private scratch dirs, and kill trees. Linux rlimits & UID dropping implemented in `sandbox.py`. | Emulated mode (env scrubbing, timeout, tree kill) verified on Windows. Kernel controls (UID, rlimits, nftables) **NOT VERIFIED ON WINDOWS**. | **PARTIALLY VERIFIED (EMULATED ON WINDOWS; PENDING LINUX RIG)** |
| **D4: Local Loopback LLM Proxy** | Agent processes talk to `/v1/chat/completions` via ephemeral per-run tokens. Model override is enforced. | Token authorization, proxy header denial, and model override tests. | **VERIFIED** |
| **D5: Stream Protocol** | Runs communicate over NDJSON stdout streams parsed with line size limits (64KB). | Buffer overflow & streaming parsing tests (`test_phase4.py`). | **VERIFIED** |
| **D6: Multi-tier Limits** | Timeouts, max steps, output limits, and platform security ceilings enforced. | Greedy manifest parameter clamping tests (`test_phase5.py`). | **VERIFIED** |
| **D7: Privacy-Friendly Stats** | Anonymous counters without cookies or stored IPs; respects `DNT` and `Sec-GPC`. | Privacy opt-out & database schema inspection (`test_phase5.py`). | **VERIFIED** |
| **D8: Manifest Validation** | Manifests validated strictly via Pydantic; invalid manifests fail loudly; internal fields hidden. | Catalog loader unit tests & schema isolation tests (`test_phase2.py`). | **VERIFIED** |
| **D9: UI Separation** | Front-end built with Vite + React + asaas-ui; zero `dangerouslySetInnerHTML`. | Source code audit & static analysis of all JSX components. | **VERIFIED** |

---

## 4. Abuse Protection & Rate Limiting Audit

### A. IP Resolution & Reverse Proxy Trust
- **Implementation:** `api/utils/client_ip.py` verifies whether `request.client.host` matches `settings.trusted_proxies`. Only if the direct connection originates from a trusted reverse proxy are headers like `X-Forwarded-For` or `X-Real-IP` parsed.
- **Verification:** Unit tests confirm that direct spoofing attempts using fake `X-Forwarded-For` headers from untrusted clients are ignored, using `request.client.host` instead.

### B. Multi-Tier Rate Limiting
- **Key Validation (`/api/providers/validate`):** 10 requests per minute per IP.
- **Connection Test (`/api/llm/test`):** 6 requests per minute per IP.
- **Run Starts (`/api/agents/{slug}/run`):** 10 requests per minute per IP.
- **Daily Run Cap:** 50 runs per IP per calendar day (UTC midnight reset).
- **Behavior:** Returns HTTP 429 Too Many Requests with a standardized `Retry-After` header.

### C. Resource Exhaustion Controls
- **Request Body Limit:** Max 5MB enforced by `RequestBodyLimitMiddleware` before reading payload into memory, returning HTTP 413.
- **Agent Output Limit:** Max 64KB per NDJSON line; exceeding kills the agent process with `output_size_exceeded`.
- **Agent Execution Timeout:** Subprocess wall-clock timeout kills process tree automatically.

---

## 5. Automated Dependency Security Audits

### Front End (`web/package.json`)
```bash
$ npm audit --json
```
- **Total Dependencies:** 101 packages (8 prod, 94 dev, 73 optional)
- **Vulnerabilities Found:** **0** (0 critical, 0 high, 0 moderate, 0 low)

### Back End (`api/requirements.txt`)
```bash
$ python -m pip_audit -r requirements.txt
```
- **Audited Packages:** `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `httpx`, `aiosqlite`, `python-multipart`
- **Vulnerabilities Found:** **No known vulnerabilities found**

---

## 6. Coverage & Execution Record

| Surface / Control | Evidence Inspected | Method | Result | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **HTTP Authentication & Headers** | API Endpoints | Automated Integration Test | `VERIFIED` | Missing or invalid run tokens return 401 Unauthorized. |
| **SSRF Prevention** | LLM Gateway URLs | Source Review & Unit Tests | `VERIFIED` | Fixed provider allowlist; user base URLs rejected. |
| **File Upload Signature** | Magic Bytes Validator | Test file upload with spoofed headers | `VERIFIED` | Extension spoofing rejected (e.g. fake .pdf). |
| **Log Leakage Prevention** | Loguru / Logging Redactor | Canary keys passed through system | `VERIFIED` | API keys replaced with `[REDACTED_API_KEY]`. |
| **Database Persistence** | SQLite app.db tables | Complete full-table string scan | `VERIFIED` | Zero traces of canary keys in any table. |
| **Prompt Injection Resilience** | Agent System Prompts & I/O | Adversarial canary injection run | `VERIFIED` | Agent system boundaries maintained. |
| **XSS & DOM Injection** | SafeMarkdown & React rendering | Source review & test strings | `VERIFIED` | Zero `dangerouslySetInnerHTML`; text rendered safely. |
| **Reverse Proxy Anti-Spoofing** | client_ip utility | Spoofed X-Forwarded-For test | `VERIFIED` | Spoofed headers ignored from untrusted peers. |

---

## 7. Controls Not Verified / Pending Linux Host Rig (Release Blocker)

The following controls from Decision D3 are fully coded in `api/modules/runtime/sandbox.py` and `docs/deploy.md`, but **could not be verified on the Windows development host** due to kernel API constraints. A release can only proceed once these are verified on a Linux host/CI environment:

1. **OS User Separation (`asaas-worker`):**
   - *Requirement:* Agent process executes under UID `asaas-worker` and cannot read `api/.env`, `api/data/app.db`, or other runs' temp directories.
   - *Status:* `NOT VERIFIED ON WINDOWS` (Windows lacks POSIX `setuid`/`setgid` in development).
2. **Network Egress Denial via `nftables`:**
   - *Requirement:* Kernel denies all outbound TCP packets from `asaas-worker` except to `127.0.0.1:8088`.
   - *Status:* `NOT VERIFIED ON WINDOWS` (`nftables` is a Linux-only kernel feature).
3. **POSIX `setrlimit` Resource Bounding:**
   - *Requirement:* `RLIMIT_AS` (512MB virtual memory ceiling), `RLIMIT_NPROC` (max 32 procs to stop fork-bombs), and `RLIMIT_CPU`.
   - *Status:* `NOT VERIFIED ON WINDOWS` (Python `resource` module is POSIX-only).

---

## 8. Residual Risks & Operational Hardening Checklist

1. **Linux Production User Isolation:**  
   In Linux deployments, configure systemd or Docker to run agents under an unprivileged user (`asaas-worker`) with `NoNewPrivileges=true` and memory cgroups.
2. **Reverse Proxy TLS Configuration:**  
   Ensure TLS 1.3 is enforced on NGINX/Caddy with strict HSTS (`Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`).
3. **Rate Limit Tuning:**  
   The initial IP limits (10/min, 50/day) are baseline assumptions. Operational logs should be monitored after one week of live usage to adjust thresholds based on legitimate visitor behavior.

---

## 9. Site DNA (Tier-2 Service Agent) Security Audit & Verification

| Control / Boundary | Target Requirement | Implementation / Evidence | Audit Status | Evidence / Notes |
| :--- | :--- | :--- | :--- | :--- |
| **In-Memory Session Security** | Visitor key sent via `X-Provider-Key` header, held in-memory only (45m sliding / 2h max TTL); cookie `HttpOnly; SameSite=Strict`; never returned in JSON or JS. | `modules/runtime/session_store.py`, `modules/runtime/service_proxy.py` (`POST /api/service-sessions/init`). | `VERIFIED` | Verified in `test_site_dna_integration.py` (cookie flags checked, `session_id` & canary key absent from JSON/disk/env). |
| **Ephemeral Per-Run Token & Context Isolation** | Proxy mints UUIDv4 `run_id` + `art_...` token before forwarding; Site DNA binds token in per-run `contextvars.ContextVar` (never `os.environ` or disk); revoked immediately on finish/cancel. | `modules/runtime/service_proxy.py`, `agents/site-dna/src/site_dna/core/llm_gateway.py`, `coordinator.py`. | `VERIFIED` | Verified across concurrent threads (`test_llm_gateway.py`) and live multi-provider E2E runs (`test_site_dna_integration.py`). |
| **CSRF & Origin Validation (Fail-Closed)** | State-changing routes (`POST`, `PUT`, `PATCH`, `DELETE`) require matching same-origin `Origin` or `Referer`. | `_check_csrf()` in `service_proxy.py`. | `VERIFIED` | Missing/spoofed origins rejected with HTTP 403. |
| **Route Allowlist Enforcement** | Only explicitly allowlisted `(METHOD, REGEX)` routes forwarded; `/docs`, `/openapi.json`, `/dashboard/legacy`, `/ready`, `/discovery`, direct stage POSTs blocked. | `ALLOWED_ROUTES` in `service_proxy.py` + `site_dna_service_mode=True` router gating in Site DNA `api/main.py`. | `VERIFIED` | Verified HTTP 404 returned for all unlisted routes in `test_site_dna_integration.py`. |
| **Cross-Session Run Isolation** | Session B cannot view, list, summarize, download, or stream runs belonging to Session A. | `has_run()` and session-scoped `/runs` & `/dashboard/summary` in `service_proxy.py`. | `VERIFIED` | Verified Session B receives HTTP 404 on Session A's run/screenshots/findings/SSE and `total_runs == 0`. |
| **HTML Preview & PDF Defensive Headers** | Preview `<iframe>` uses `sandbox=""`; proxy sets `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'self'` and `Content-Disposition: attachment` on downloads. | `service_proxy.py`, `agents/site-dna/frontend/src/pages/ReportViewer.tsx`, `pdf_renderer.py` (offline context + route abort). | `VERIFIED` | Verified in frontend source, `pdf_renderer.py`, and proxy header logic. |
| **Concurrency, Origin Lock & Daily Cap** | Max 2 global concurrent runs, 1 per IP, 1 per session, 1 per target origin, 3 runs per IP/24h rolling window. | `modules/runtime/session_limiter.py`. | `VERIFIED` | Verified in `test_concurrency_origin_lock_and_daily_quota` (409/429 with `Retry-After`). |
| **SSRF, S7 Policy, Consent & Browser Isolation** | Reject all raw IP literals, non-80/443 ports, embedded creds, platform hosts, private/metadata IPs; require `consent_confirmed: true`; respect `robots.txt`; block Playwright JS loopback probes; competitor stage OFF by default; `max_pages <= 8`. | `service_proxy.py`, `core/security.py`, `discovery/url_validator.py`, `visual/browser_security.py`, `NewAnalysis.tsx`. | `VERIFIED (APPLICATION LAYER)` | Verified in `test_s7_adversarial_urls_rejected` & live E2E test (`private_area == 0`, `sentinel loopback == 0`). |
| **60-Minute Retention & Disk Quota Janitor** | Delete finished runs 60m post-completion; evict oldest dirs when exceeding 150 MB/session or 1 GB global cap; zero shared disk cache across visitors. | `modules/runtime/janitor.py`, `service_supervisor.py` (disables all 7 Site DNA caches). | `VERIFIED` | Verified in `test_janitor_60m_retention_and_disk_quota`. |
| **Single-Worker Invariant** | Platform and Site DNA run strictly with `--workers 1`; supervisor clamps any higher value with warning. | `service_supervisor.py` (`_build_argv`), `docs/deploy.md`. | `VERIFIED` | Verified in `test_supervisor_enforces_single_worker_clamp`. |
| **Linux Egress Packet Filter (`nftables`)** | Dedicated UID `asaas-service-sitedna` permitted only established/related, DNS, local LLM loopback, and public TCP 80/443; all private/loopback/CGNAT/metadata/IPv6-private ranges dropped at kernel. | `scripts/setup_service_sandbox.sh` (`nftables` skuid filter). | `DOCUMENTED ONLY / PENDING LINUX` | Script provisioned and syntax-checked; **NOT verified on Windows** — requires Linux host test execution. |
| **Linux cgroups v2 & Dedicated UID Isolation** | `asaas-service-sitedna` user isolation + systemd `MemoryMax=2G`, `CPUQuota=200%`, `TasksMax=96`, `ProtectSystem=strict`, `PrivateTmp=true`. | `scripts/setup_service_sandbox.sh` (`/etc/systemd/system/asaas-sitedna.service`). | `DOCUMENTED ONLY / PENDING LINUX` | **NOT verified on Windows** — requires Linux host execution. |
| **Chromium Kernel Sandbox** | No `--no-sandbox` flag by default; relies on Linux user namespaces (`kernel.unprivileged_userns_clone=1`). | `pdf_renderer.py`, `browser_manager.py`. | `ENFORCED IN CODE / PENDING LINUX` | Flag omitted by default; Linux namespace behavior pending Linux host verification. |

**Updated Release Recommendation:** **HOLD** — All application-layer, multi-provider gateway, session isolation, canary key safety, S7/S8, cancel, and janitor controls are verified on Windows. Production release remains on **HOLD** until Linux kernel controls (`nftables` egress, `asaas-worker` & `asaas-service-sitedna` UID separation, `setrlimit`, `cgroups v2`, Chromium namespaces) are executed and verified on a Linux host, and ASAAS legal approves `/privacy` and `/terms`.
