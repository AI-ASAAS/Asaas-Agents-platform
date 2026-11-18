# AGENTS.md — ASAAS Agents Platform (وكلاء أساس)

Welcome to the engineering source of truth and playbook for the **ASAAS Agents Platform (وكلاء أساس)**, developed by ASAAS AI. This document captures the product mission, architectural decisions, company skills mapping, development rules, and phase reporting standards for current and future engineering sessions.

---

## 1. Product Summary

- **Product Name:** ASAAS Agents Platform (وكلاء أساس) by ASAAS AI.
- **Core Mission:** A public, Arabic (RTL, phone-first) web showcase of production-grade AI agents built by the ASAAS team.
- **Visitor Experience:** Visitors browse published agents, inspect their documentation and GitHub repositories, and execute live interactive demos directly in the browser.
- **Non-Goals:** It is **NOT** an agent builder or workflow orchestrator for end-users. Visitors cannot create, upload, configure, or modify agents.
- **Account & Session Model:** Zero accounts, zero registration, and zero sign-in. All interactions are ephemeral and scoped strictly to the visitor's local browser session.
- **BYOK (Bring Your Own Key):**
  - Every live agent execution runs entirely on the visitor's supplied API key.
  - ASAAS never pays for model consumption and never distributes or bundles server-side company API keys.
  - The UI clearly guides visitors on how to obtain free API keys (e.g., Google AI Studio's free tier).
  - Supported initial providers: Google AI Studio (Gemini API), OpenAI, Anthropic, OpenRouter (extensible in code).
  - Visitors select their provider, supply their key, pick an eligible model, and launch the agent.
- **Agent Integration & Packaging:**
  - Each agent features a bespoke UI tailored to its domain.
  - Agents are authored by ASAAS developers in GitHub and integrated into the platform codebase (not via a public dashboard).
  - Agents are strictly pinned to immutable **commit SHAs** (never tracking moving branches).
  - The platform abstracts and adapts agent execution so each agent runs against the provider and model chosen by the visitor.
- **Session Telemetry & Observability:**
  - Live session metrics are displayed: request count, token usage, estimated cost, connection status, active model, and rate-limit headroom.
  - For providers that do not emit rate-limit headers (such as Google AI Studio / Gemini free tier), the platform tracks request counts against a local configurable tier limit table and marks the metrics as "estimated".
- **Hosting Target:** A single ASAAS-managed server in a later phase. **No deployment or external infrastructure modifications during active development.**

---

## 2. Architecture & Security Decisions

### 1. Ephemeral, Stateless Key Handling
- The visitor's API key resides exclusively in client browser memory (tab state / optional `sessionStorage`).
- Keys are transmitted per-request via the `X-Provider-Key` HTTPS header.
- The server processes the key statelessly in memory for that single call.
- Keys are **never** persisted in databases, caches, cookies, local files, URLs, error messages, or telemetry.
- Strict redaction filters apply to all server logging pipelines.

### 2. Centralized LLM Gateway (`modules/llm/`)
- A single LLM gateway module acts as the sole outbound bridge to external LLM providers.
- It conforms to the ASAAS `ai` skill foundation with three explicit, agreed architectural deviations:
  1. **Per-Request Construction:** Client instances are instantiated per request with the caller's transient `X-Provider-Key`.
  2. **No Automated Model Fallback:** The visitor explicitly controls model selection; failures do not silently fall back to alternate models.
  3. **No Silent 429 Retries:** Silent retries rapidly deplete free-tier quotas. 429 / Rate Limit errors are surfaced immediately with `Retry-After` headers and actionable Arabic guidance.
- Any further divergence must be logged with justification in `docs/decisions.md`.

### 3. Isolated Agent Runtime & Local Proxy
- Agents execute inside isolated worker processes and **never receive or access the visitor's real API key**.
- Agents communicate with a platform-local OpenAI-compatible proxy endpoint using short-lived, per-run tokens.
- The gateway validates the run token, attaches the visitor's real provider credentials, and relays the call to the destination provider.
- All agent code is frozen to pinned git commit SHAs to guarantee deterministic, auditable execution.

### 4. Agent UI Platform SDK
- Individual agent interfaces consume a lightweight platform SDK providing standardized hooks for execution lifecycle:
  - `run(...)`, `cancel()`, `status`, `events`, and `usage`.
- Agent UIs never handle or inspect raw provider keys.

---

## 3. The Company Skills Map

Before implementing any feature or module, consult the relevant foundation skill and linked reference guides:

| Area | Entry Point / Skill Path | Mandatory References & Standards |
| :--- | :--- | :--- |
| **Backend** | `backend/SKILL.md` | - `references/project-structure.md`: Modular FastAPI layout (`modules/<domain>/` with `router.py`, `schemas.py`, `service.py`, `repository.py`).<br>- `references/fastapi-patterns.md`: Thin routers, explicit Pydantic schemas, parameter binding, structured HTTP error format `{"message": ...}`.<br>- `references/database-and-migrations.md`: Central async wrapper, `aiosqlite`, `data/app.db`, versioned migrations.<br>- `references/ai-heavy-projects.md`: Gateway organization under `modules/llm/`. |
| **Frontend** | `frontend/SKILL.md`<br>`frontend/asaas-ui/SKILL.md` | - React + Vite + TypeScript, Arabic RTL first (`dir="rtl"`), mobile-first layout (validated at 375px width).<br>- `frontend/asaas-ui/references/brand.md`: Thmanyah typography (`--font` Sans for numbers/UI, `--font-display` Serif Display for headings, `--font-text` Serif Text for prose), Asaas color tokens (Ink `#221f1f`, Gold `#ba9555`, Sand `#d3c6b4`, Clay `#c3ad8d`, Cream `#ede7da`, Paper `#fcf9f5`).<br>- `frontend/asaas-ui/references/components.md`: Glass surfaces (`<Card>`, `<Glass>`, `<Ambient />`), `<SiteHeader>`, `<TabBar>`, `<ToastProvider>`, `<StatusPill>`, accessible modal focus traps.<br>- `frontend/references/patterns.md`: Logical CSS properties, `safeHref` sanitizer, dictionary text `t('key')`. |
| **AI & LLM** | `ai/SKILL.md` | - `references/llm-integration.md`: Stateless gateway, timeouts, token budgets, Pydantic structured output validation, prompt versioning in `prompts/`.<br>- `build-ai-agents/SKILL.md`: CrewAI standards, bounded tasks, explicit tool permissions, execution limits. |
| **Cybersecurity** | `cyber/security-review/SKILL.md` | - `references/audit-orchestration.md`, `references/web-api.md`, `references/specialized-systems.md`: Defense-in-depth, input sanitization, complete key non-exposure, zero secret leakage, safe proxying. |
| **Skill Authoring** | `readme.md` | - Standards for adding new task skills, naming conventions, and validation checklists. |

> [!IMPORTANT]
> **Deviation Protocol:** Whenever project requirements necessitate diverging from a skill standard (e.g., the three LLM gateway refinements above), record the change and the exact rationale in `docs/decisions.md`. Never deviate silently.

---

## 4. Working Rules

1. **Phase-by-Phase Discipline:** Work strictly on the single phase prompt provided. When the phase requirements are met, **STOP** and output the phase report. Never initiate subsequent phases autonomously.
2. **Strict Scope & No Invention:** Do not invent product features, workflows, or unstated requirements. If a material gap arises, pause and submit up to 5 focused questions with recommended answers. For minor non-material details, declare explicit assumptions in the report and keep them adaptable.
3. **External Systems & Git Safety:** Do not commit, push, create branches, deploy, or modify external cloud resources unless explicitly authorized. All development is local.
4. **Absolute Credential Safety:** Real secrets, production keys, or private tokens must never be written to files, checked into code, printed to logs, included in tests, or included in chat reports.
5. **Empirical Verification Required:** Nothing is verified until executed. For every phase:
   - Run type checks and build scripts.
   - Boot services and execute live HTTP requests (covering both happy path and intentional failure/error paths, validating `{"message": ...}` payloads).
   - Verify UI rendering and responsive behavior at 375px mobile viewport width (zero horizontal scroll: `document.documentElement.scrollWidth === window.innerWidth`).
6. **Minimal Dependencies:** Never introduce new frameworks, state managers, component libraries, test runners, or container orchestration without explicit justification documented in `docs/decisions.md`.

---

## 5. Phase Report Template

At the conclusion of each phase, submit a report adhering strictly to this six-part format:

```markdown
### 1. What was built
- [Module/Component/File level summary of deliverables]

### 2. What was verified
- [Exact commands, HTTP requests, test executions, and viewport checks performed, with actual output/results]

### 3. What could not be verified and why
- [Any blocked items, environmental limitations, or missing resources]

### 4. Deviations from skills or spec
- [Any variance from standard skills or product specifications, citing rationales recorded in docs/decisions.md]

### 5. Assumptions made
- [Non-material operational or design assumptions adopted during the phase]

### 6. Questions for the user
- [Up to 5 focused questions regarding material ambiguities, each accompanied by a recommended answer]
```
