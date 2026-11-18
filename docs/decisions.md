# Architecture Decisions Record — ASAAS Agents Platform (وكلاء أساس)

This record documents the foundational architectural, security, and operational decisions governing the ASAAS Agents Platform. Every decision includes context, considered options, technical rationale, trade-offs, and conditions that would prompt re-evaluation.

---

## D1: Key Path and Stateless Lifecycle

- **Status:** Approved
- **Context:** The platform operates under a strict BYOK (Bring Your Own Key) model. Visitors use their own API keys (Google AI Studio, OpenAI, Anthropic, OpenRouter) to run live agent demos. ASAAS does not supply company keys or subsidize model calls.
- **Options Considered:**
  1. *Stateless Header per Request (Client Memory -> `X-Provider-Key`):* Key is entered in browser, held in transient client memory (tab RAM, optional `sessionStorage`), passed on each streaming request via HTTPS header `X-Provider-Key`, used once by the gateway, and discarded.
  2. *Server-Side Ephemeral Session (Redis/Memory Store):* Key uploaded once, stored in server cache with session cookie, TTL-evicted.
  3. *Client-Side Encryption with Server Key (KMS envelope):* Encrypted key stored in client cookie, decrypted per request by server.
- **Recommendation:** **Option 1 (Stateless Header per Request).**
- **XSS and CSP Security Consequences & Required Controls:**
  - *Risk:* Any script execution vulnerability (XSS) in the browser could allow malicious JavaScript to read the key from client memory or `sessionStorage`.
  - *Required Controls:*
    - **Strict Content Security Policy (CSP):** `default-src 'self'; script-src 'self' 'nonce-...'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'self';`. No `'unsafe-eval'` or un-hashed inline scripts.
    - **Zero Server Persistence:** The server never writes the key to SQLite, Redis, temp files, cookies, or query strings.
    - **Logging Redaction Pipeline:** A mandatory logging filter inspects all incoming headers, request payloads, and exception traces, immediately replacing matches to known key patterns (`sk-...`, `AIza...`, `ant-...`) with `[REDACTED_API_KEY]`.
    - **Safe DOM Rendering:** Zero use of `dangerouslySetInnerHTML` for untrusted or dynamic text; all external links sanitized through `safeHref`.
- **Trade-offs:** If the visitor refreshes a tab where `sessionStorage` is disabled, they must re-enter their key. This minor friction is an intentional trade-off for zero server liability.
- **What Would Change It:** If the product introduces user accounts with encrypted secret vaults (explicitly ruled out for the public showcase).

### Amendment to D1: Ephemeral In-Memory Session for Service Agents (Decision S2)
- **Status:** Approved
- **Context:** Tier-2 "service" agents (such as Site DNA) execute multi-minute asynchronous workflows across separate background tasks and browser requests. In this tier, passing keys on every streaming request is infeasible because the background process continues executing while the browser navigates or awaits background crawl completion.
- **Adopted Design:**
  - The visitor inputs their key/provider/model once on the platform agent detail page.
  - The platform API creates an opaque session ID stored **IN MEMORY ONLY** within the server heap (never written to disk, SQLite, logs, or child environments).
  - The session has a sliding TTL (default 45 minutes of inactivity; absolute cap of 2 hours) and is delivered to the client as a `Secure`, `HttpOnly`, `SameSite=Strict` cookie (`asaas_service_session`).
  - When a run is started, the platform proxy generates an ephemeral per-run token (`art_...`) registered in `RunTokenRegistry` with TTL = run limit + grace (e.g. 22 minutes), and passes only this token to the agent backend.
  - The agent backend uses the `art_...` token to authenticate LLM requests through the platform's local gateway.
  - The `art_...` token is revoked immediately upon run completion, failure, cancellation, or session expiration.
  - **CSRF & Isolation Safeguards:** State-changing proxy routes require `SameSite=Strict` and validate `Origin`/`Referer` headers. This design strictly requires the single-worker deployment from F1 to maintain memory consistency.
  - Ephemeral job agents continue to use the stateless per-request header pattern.

---

## D2: Gateway Architecture & Provider Adapters

- **Status:** Approved
- **Context:** The platform requires an internal egress boundary (`modules/llm/`) to route LLM requests from agent processes to external providers while shielding agents from real visitor keys.
- **Options Considered:**
  1. *Pure Generic OpenAI Proxy:* Rely entirely on each provider's OpenAI-compatible endpoint.
  2. *Hybrid Gateway:* Standard internal OpenAI-compatible protocol (`/v1/chat/completions`) with a native adapter for Anthropic and direct compat pass-through for OpenAI, OpenRouter, and Google AI Studio.
  3. *Heavy Third-Party Framework (LiteLLM / LangChain):* Adopt an external multi-provider library.
- **Recommendation:** **Option 2 (Hybrid Gateway with Native Anthropic Adapter).**
  - *Provider Breakdown:*
    - **OpenAI:** Direct OpenAI client pass-through.
    - **OpenRouter:** Direct OpenAI client pass-through.
    - **Google AI Studio (Gemini):** OpenAI-compat layer (`https://generativelanguage.googleapis.com/v1beta/openai/`) augmented with a stream chunk normalizer (to fix known missing index fields in tool-call deltas).
    - **Anthropic:** **Dedicated Native Adapter** (`POST https://api.anthropic.com/v1/messages`). Anthropic's official documentation explicitly specifies that their OpenAI compatibility layer is intended for testing/evaluations and lacks production readiness for tool calling, structured outputs, and prompt caching.
  - *Framework Rejection:* Avoid heavy multi-provider dependencies (LiteLLM/LangChain) in accordance with the minimal-dependency working rule. A lightweight internal adapter (~150 LOC) provides complete auditability and zero unexpected telemetry.
- **Trade-offs:** Maintaining an internal Anthropic adapter requires testing schema conversions across tool calls.
- **What Would Change It:** If Anthropic provides full production SLA and feature parity on their `/v1/chat/completions` endpoint.

---

## D3: Runtime Isolation for Agent Processes

- **Status:** Approved
- **Context:** Agent logic is developed by ASAAS developers in Python and executed on a single ASAAS-managed server. While agents are internal code (pinned to commit SHAs), multi-tenant visitor sessions must remain mutually isolated, and untrusted agent execution must be strictly bounded.
- **Requirements to Enforce:**
  1. No access to platform server secrets or environment variables.
  2. No access to other sessions' files or runtime state.
  3. No outbound network access EXCEPT to the platform's local loopback proxy (`http://127.0.0.1:<port>/v1`).
  4. Explicit CPU, memory, wall-clock time, and stdout/stderr limits.
  5. Reliable process termination on timeout or client disconnect with zero orphan/zombie processes.
- **Comparison of Server-Side Options on Linux:**
  1. *Container per Run (Docker / Podman):* Full filesystem and network namespaces, but high startup latency (~500ms), heavy resource overhead for concurrent short runs, and requires managing a Docker socket.
  2. *Bubblewrap (`bwrap`) / Linux User Namespaces:* Lightweight unprivileged sandboxing. Creates private mount namespaces (read-only root `/`, private `/tmp`), unshares network except loopback or veth, drops capabilities, and wipes files on process exit. Startup overhead < 15ms.
  3. *Unprivileged User + `prlimit` + `unshare -n` + IPTables/nftables:* Dedicated system user (`asaas-agent-runner`), empty environment (`env -i`), private directory (`chmod 700`), `resource.setrlimit` (RLIMIT_AS, RLIMIT_CPU), process group kill (`setpgid`).
- **Recommendation:**
  - **Production Target (Linux):** **Dedicated Unprivileged OS User (`asaas-worker`) + POSIX `setrlimit` + `nftables` Socket Filtering + DAC Private Directories (0700)**.
    - *Filesystem Boundary:* The API runs as `asaas-app` (owning `api/.env`, `api/data/app.db`, `scripts/` with `0600`/`0700`). The agent subprocess executes strictly as `asaas-worker`. Each run receives an ephemeral directory `chmod 0700` chowned to `asaas-worker`. The agent cannot read the API's database, secrets, or other runs' directories.
    - *Network Egress Boundary:* Linux kernel packet filtering via `nftables`:
      ```nftables
      table inet asaas_filter {
          chain output {
              type filter hook output priority 0; policy accept;
              # Allow agent worker UID only to the local loopback proxy port (8088)
              meta skuid asaas-worker ip daddr 127.0.0.1 tcp dport 8088 accept
              meta skuid asaas-worker reject
          }
      }
      ```
    - *Resource Boundaries:* `setrlimit` in child `preexec_fn` enforces `RLIMIT_CPU` (timeout), `RLIMIT_AS` (512MB virtual memory limit to stop memory bombs), `RLIMIT_NPROC` (32 processes to stop fork bombs), `RLIMIT_NOFILE` (64 file descriptors), and `RLIMIT_FSIZE` (10MB max file size).
  - **Local Development Fallback (Windows/macOS):** Emulated mode with sanitized environment (`env -i`), private temp directory, process-tree kill, and timeout. The platform logs an explicit loud warning on boot, and exposes `"sandbox_mode": "emulated"` in `/api/health` so development mode is never confused with production.
- **Trade-offs:** Compared to Bubblewrap (`bwrap`), dedicated UID + `nftables` avoids loopback namespace isolation issues (where a network namespace cannot reach host loopback without veth/proxy plumbing) while achieving airtight UID DAC and packet-level egress prevention.
- **What Would Change It:** If the deployment migrates to dedicated microVMs (e.g. Fly Machines or AWS Firecracker).

---

## D4: Agent UI Integration Architecture

- **Status:** Approved
- **Context:** Each agent features a tailored user interface. Visitors interact with this UI to supply parameters, inspect step-by-step thinking, and view domain-specific artifacts.
- **Options Considered:**
  1. *Same-Origin Lazy Modules (React + Platform SDK):* Agent UIs are React components bundled or dynamically imported within the main frontend application, using a shared typed Platform SDK (`useAgentRun`, `status`, `events`, `usage`).
  2. *Sandboxed `<iframe>` with `postMessage`:* Each agent UI is built as an independent static bundle rendered inside an isolated `iframe` (`sandbox="allow-scripts"`).
- **Recommendation:** **Option 1 (Same-Origin Lazy Modules) for MVP.**
  - *Rationale:* Agents are built internally by the ASAAS team and pinned to reviewed commit SHAs. Same-origin components ensure complete visual consistency with the Asaas UI design kit (Thmanyah typography, liquid glass tokens, dark/light themes, mobile drawer integration at 375px) without iframe scrolling bugs or mobile viewport resizing issues.
  - *Security Boundary:* The Platform SDK exposes only execution initiation (`run({ input })`) and event streaming. The visitor's API key is managed exclusively by the core platform shell and is **never passed or exposed to the agent UI component**.
- **Trade-offs:** If an agent UI contains an intentional XSS vulnerability, it shares the tab origin. This risk is mitigated by code review in GitHub prior to pinning commit SHAs.
- **What Would Change It:** If the platform is opened to unreviewed third-party community agent submissions (Option 2 sandboxed iframes would then become mandatory).

---

## D5: Streaming Transport & Cancellation Protocol

- **Status:** Approved
- **Context:** Agent executions produce streaming outputs (thinking deltas, tool invocation events, final results). The transport must support sending visitor API keys securely and handle responsive user cancellations.
- **Options Considered:**
  1. *Browser `EventSource` (GET-based SSE):* Standard Server-Sent Events API.
  2. *WebSocket (`wss://`):* Bidirectional stateful connection.
  3. *Fetch with Streaming Response (`POST` + SSE text stream):* HTTP POST carrying `X-Provider-Key` header, returning a chunked `text/event-stream` response consumed via `ReadableStreamDefaultReader`.
- **Recommendation:** **Option 3 (`POST` + Fetch Streaming Response).**
  - *Header Security:* Standard `EventSource` cannot send custom HTTP headers (`X-Provider-Key`). Sending the key in a URL query parameter is unacceptable because URLs are logged by reverse proxies and browser history.
  - *Simplicity:* WebSockets introduce unnecessary connection-state complexity on the server and cannot send custom headers during handshake without URL token leakage.
  - *Cancellation Semantics:*
    - When the visitor clicks "إلغاء" (Cancel), the frontend immediately invokes `AbortController.abort()`, closing the TCP connection.
    - The FastAPI backend detects client disconnection (`await request.is_disconnected()`), immediately sends `SIGTERM` to the agent child process group, waits 2.0 seconds, and escalates to `SIGKILL` if the process has not terminated.
- **Trade-offs:** Requires a small ~40-line SSE reader utility on the client rather than native `EventSource`.
- **What Would Change It:** If the W3C adds custom request header support to the `EventSource` specification.

---

## D6: Agent Code Lifecycle & Deployment

- **Status:** Approved
- **Context:** Agents are maintained by ASAAS engineers in GitHub repositories. The platform must execute them reliably without drifting branches or runtime package installations.
- **Options Considered:**
  1. *On-Demand Git Clone per Execution:* Clone repository upon user request.
  2. *Monorepo Inlining:* Copy all agent source code directly into the platform repository.
  3. *Pre-Synchronized Pinned Checkouts (`scripts/sync_agents.py`):* A dedicated sync script pulls agent repositories at deploy/maintenance time, checks out the exact immutable `pinned_ref` (Commit SHA), and pre-builds an isolated virtualenv from the agent's lockfile.
- **Recommendation:** **Option 3 (Pre-Synchronized Pinned Checkouts).**
  - Agents are pinned strictly to immutable **Commit SHAs** in `docs/agent-manifest.md`.
  - Virtual environments (`.venv`) are built using `uv` at synchronization time.
  - During live visitor requests, zero network calls to GitHub or PyPI occur; the runner directly invokes the pre-built `.venv/bin/python`.
- **Trade-offs:** Adding or updating an agent requires running the sync script on the server before updating the manifest.
- **What Would Change It:** If hundreds of agents make local disk pre-building impractical, necessitating container registries.

---

## D7: Anonymous Telemetry & Analytics

- **Status:** Approved
- **Context:** The team needs visibility into agent popularity, success rates, and provider errors without compromising visitor privacy or collecting personally identifiable information.
- **Principles & Controls:**
  - *Data Collected:* Agent slug, provider name, model identifier, execution status (`started`, `succeeded`, `failed`), error category (`rate_limit`, `auth_error`, `timeout`, `agent_error`), execution duration, and token usage.
  - *Privacy Guarantees:* Zero IP addresses stored (not even hashed or truncated). Zero cookies, zero persistent visitor IDs, zero browser fingerprinting.
  - *Do-Not-Track:* The analytics endpoint checks `navigator.doNotTrack` and `Sec-GPC` (Global Privacy Control); if enabled, all logging is dropped.
  - *Storage:* Stored in a local SQLite table (`analytics_events`) with scheduled aggregate rollups and automatic raw log pruning.
- **Trade-offs:** Cannot compute unique monthly active visitors; only anonymous session counts.
- **What Would Change It:** No changes foreseen; aligns with ASAAS privacy standards.

---

## D8: Recorded Deviations from Company Skills

This section formally records and justifies all divergences from standard ASAAS company skills:

| Standard Skill | Standard Recommendation | Platform Deviation | Architectural Justification |
| :--- | :--- | :--- | :--- |
| **`ai` Foundation** (`references/llm-integration.md`) | Singleton `LLMClient` configured with server-owned API key from environment variables. | **Per-Request Transient Client:** Instantiated per request with visitor's `X-Provider-Key`. | **BYOK Requirement:** ASAAS never supplies company keys or funds model calls. Key handling must be completely stateless. |
| **`ai` Foundation** (`references/llm-integration.md`) | Configured list of fallback models tried sequentially upon error. | **No Automatic Model Fallback:** Only the visitor's chosen model is invoked. | **Visitor Autonomy & Cost:** Visitors select their model based on quota/billing tiers. Silent fallback risks unwanted charges or unsupported capabilities. |
| **`ai` Foundation** (`references/llm-integration.md`) | Bounded exponential backoff retries on HTTP 429 status codes. | **No Silent 429 Retries:** Rate limits are immediately surfaced to client with `Retry-After`. | **Quota Preservation:** Free-tier accounts (e.g. Gemini 15 RPM) exhaust rapidly under automated retries. Immediate notice enables graceful user pacing. |
| **`backend` Foundation** (`backend/SKILL.md`) | Application capabilities run inside monolithic FastAPI modules (`modules/<domain>/service.py`). | **Process-Isolated Subprocesses:** Agents run as separate external child processes. | **Security Isolation:** Prevents unvetted agent code from reading server memory, database state, or other sessions' temporary files. |

---

## D9: Model Output Rendering & SafeMarkdown

- **Status:** Approved
- **Context:** Agent runs produce unstructured and semi-structured markdown streams from external LLM providers. Rendering this output must remain 100% immune to Cross-Site Scripting (XSS), prompt injection escapes, and malicious embedded HTML/SVG, while adhering strictly to the minimal dependency working rule.
- **Options Considered:**
  1. *Heavy HTML-Parsing Libraries (`marked` / `markdown-it` + `DOMPurify`):* Generates raw HTML strings and requires sanitized `dangerouslySetInnerHTML`. Adds significant bundle weight and opens potential sanitization bypass risks.
  2. *Native React Safe AST Parser (`SafeMarkdown`):* Custom parser that converts markdown syntax (code blocks, headings, bold, italic, lists, blockquotes) directly into native React Virtual DOM elements (`<pre>`, `<code>`, `<h3>`, `<strong>`, `<em>`, `<li>`, `<a>`). External links are strictly sanitized via `safeHref`. Zero HTML strings or `dangerouslySetInnerHTML` are ever used.
- **Recommendation:** **Option 2 (Native React Safe AST Parser).**
  - *Zero XSS Sink:* By generating pure React elements, browser HTML parsing never occurs, preventing script execution, `<img onerror=...>`, or iframe injection natively.
  - *Zero External Dependencies:* Eliminates third-party supply chain risks and preserves the fast 300ms Vite build times.
  - *Link Security:* All anchor tags are routed through `safeHref`, which rejects `javascript:`, `data:`, control characters, and backslash protocol tricks.
- **Trade-offs:** Supports essential common markdown structures (paragraphs, code blocks, lists, quotes, inline formatting, links) rather than full GitHub Flavored Markdown (tables, task lists).
- **What Would Change It:** If complex mathematical KaTeX rendering or nested GFM tables become a firm product showcase requirement.

---

## D10: Tier-2 Managed Service Agents & Site DNA Integration

- **Status:** Approved (Implemented in Part B)
- **Context:** Site DNA is a full-stack multi-stage website-intelligence application (FastAPI + CrewAI + Playwright Chromium + dedicated React SPA) that takes 2–8 minutes per run and requires public HTTP/HTTPS egress to crawl user-submitted websites. Forcing it into the Tier-1 stateless `jsonl-stdio@1` job runner would discard its interactive multi-tab UI and require rewriting its entire backend.
- **Decision (aligned with `docs/integrations/site-dna.md`):**
  1. **Second Runtime Kind (`runtime.kind: "service"`):** Managed single-worker loopback daemon supervised by `ServiceSupervisor`, fronted by an allowlisted reverse proxy (`/agents-api/site-dna/*`), while keeping Tier-1 job agents completely unchanged.
  2. **Sub-App Mount Path (`/agents/site-dna/app/`):** Keeps `/agents/site-dna` as the platform's catalog detail & BYOK key-setup page, and serves the built Site DNA SPA at `/agents/site-dna/app/` with strict CSP and scoped SPA fallback.
  3. **Ephemeral In-Memory Session Cookie & Per-Run Token:** Visitor key is submitted via `X-Provider-Key` header to `POST /api/service-sessions/init` and held in server memory only (cookie `asaas_service_session`, `HttpOnly; SameSite=Strict`, 45m sliding / 2h max TTL). Each run receives a proxy-minted UUIDv4 `run_id` and per-run `art_...` token via `X-Run-Token` header; Site DNA binds it in a per-run `contextvars.ContextVar` (never `os.environ`, disk, or logs).
  4. **No Shared Cache & 60-Minute Post-Completion Retention:** All 7 Site DNA disk caches are disabled in service mode (`SITE_DNA_SERVICE_MODE=true`) to prevent cross-visitor leakage. `DataJanitor` purges finished run directories 60 minutes after completion and enforces per-session (150 MB) and global (1 GB) disk quotas.
  5. **S7/S8 Guardrails:** Raw IP literals, non-80/443 ports, embedded credentials, private/metadata IPs, and platform own hosts are rejected; `competitor_intelligence` is OFF by default; `max_pages <= 8` (`full_site_scan` removed in platform mode); explicit consent checkbox (`consent_confirmed: true`) and live free-tier cost estimator are required before starting a run.
  6. **Zero Unapproved Deviations:** All implementation choices match `docs/integrations/site-dna.md` as approved. One operational reliability fix was added during E2E verification: `ServiceSupervisor` continuously drains the supervised child's stdout/stderr stream in a daemon thread so OS pipe buffers cannot fill and deadlock single-worker uvicorn.
