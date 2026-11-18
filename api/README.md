# ASAAS Agents Platform — Backend API (`api/`)

FastAPI backend conforming to the ASAAS modular backend foundation.

## Features
- **Stateless BYOK Foundation:** Built to handle visitor API keys statelessly without database persistence or log leaks.
- **Strict Error Contract:** Every error returns `{"message": "...", "code": "..."}` in Arabic (`X-Lang: ar` default) or English (`X-Lang: en`).
- **Security Headers Middleware:** Emits strict CSP, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, and `Permissions-Policy`.
- **Key Redaction Logging:** Filters out all API key patterns (`AIza...`, `sk-...`, `sk-ant-...`) and `X-Provider-Key` values from logs.
- **Static Delivery:** Serves the built frontend from `web/dist` with appropriate caching (`no-cache` for HTML/JS entrypoints, immutable for fingerprinted assets) and SPA routing fallback.
- **Async Persistence:** Async SQLite with WAL mode, foreign keys, and busy timeout.

## Development & Execution

### 1. Requirements
Python 3.11+ installed.

### 2. Setup & Virtual Environment
```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### 3. Run the Server
```bash
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

### 5. Running Verification Tests
All platform and security test suites are organized under `api/tests/`:
```bash
python tests/test_phase1_foundation.py
python tests/test_phase2_catalog.py
python tests/test_phase3_gateway.py
python tests/test_phase4_runtime.py
python tests/test_phase5_hardening.py
python tests/test_fix_pass.py
```
