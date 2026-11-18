# Agent Manifest Specification (`docs/agent-manifest.md`)

**Specification Version:** 1.0.0  
**Process Protocol Version:** `jsonl-stdio@1`  
**Purpose:** Defines the standardized manifest contract and execution protocol enabling any ASAAS-built AI agent to be registered, discovered, and run live with zero modifications to the platform's public UI code.

---

## 1. Overview & Architectural Principles

1. **Manifest-Driven Discovery:** All published agents are declared in individual manifest files located under `agents/<slug>/manifest.json` or centrally validated in `data/manifests/`. The platform dynamically renders the catalog, search filters, model compatibility matrix, and detail pages directly from this schema.
2. **Pinned Immutable References:** To guarantee security, stability, and auditability, agents must declare an immutable 40-character Git **Commit SHA** (`pinned_ref`). Pointers to moving branches (`main`, `master`, `dev`) are strictly rejected.
3. **No Direct Secret Access:** Agents never receive the visitor's real API key. The platform provides an ephemeral `llm_endpoint` and a short-lived `run_token` over standard input. The agent talks to this local endpoint using standard OpenAI client libraries.
4. **Platform Limit Supremacy:** While manifests declare agent-specific limits, **platform-wide maximum ceilings always override manifest declarations**.

---

## 2. Complete Manifest JSON Schema

Below is the definitive schema definition.

```json
{
  "schema_version": 1,
  "slug": "support-agent",
  "name": {
    "ar": "وكيل خدمة العملاء",
    "en": "Customer Support Agent"
  },
  "summary": {
    "ar": "وكيل ذكي للرد على استفسارات العملاء وحل المشكلات الفنية تلقائياً.",
    "en": "Intelligent agent for customer inquiries and automated troubleshooting."
  },
  "description": {
    "ar": "يقوم وكيل خدمة العملاء بتحليل تذاكر الدعم الفني، وتقديم إجابات فورية مبنية على قواعد المعرفة، واقتراح حلول مخصصة للمستخدم مع إمكانية تحويل التذاكر المعقدة.",
    "en": "Analyzes support tickets, provides immediate answers grounded in knowledge bases, and formulates troubleshooting steps."
  },
  "category": "customer-service",
  "icon": "headset",
  "status": "ready",
  "featured": true,
  "github": {
    "url": "https://github.com/asaas-ai/support-agent",
    "pinned_ref": "4a5c68b72e1289dfc98124ef5a1b32d098765432"
  },
  "runtime": {
    "kind": "python",
    "python": "3.12",
    "entrypoint": "src/main.py",
    "protocol": "jsonl-stdio@1"
  },
  "playground": {
    "mode": "chat",
    "ui": "support-agent"
  },
  "model_requirements": {
    "tool_calling": true,
    "json_schema": false,
    "vision": false,
    "min_context_tokens": 32000
  },
  "providers": {
    "allow": ["gemini", "openai", "anthropic", "openrouter"]
  },
  "limits": {
    "max_steps": 8,
    "timeout_seconds": 120,
    "max_input_chars": 8000,
    "max_output_tokens": 2000,
    "uploads": {
      "max_files": 1,
      "max_mb": 5,
      "types": ["application/pdf", "image/png", "image/jpeg"]
    }
  }
}
```

---

## 3. Schema Field Definitions & Validation Rules

### 3.1 Metadata & Identification
- **`schema_version`** *(integer, required)*: Must be `1`.
- **`slug`** *(string, required)*: Unique URL-safe identifier matching regex `^[a-z0-9]+(-[a-z0-9]+)*$`. Matches the directory name under `agents/<slug>`.
- **`name`** *(object, required)*:
  - `ar` *(string, required)*: Arabic display name.
  - `en` *(string, optional)*: English display name or `null`.
- **`summary`** *(object, required)*:
  - `ar` *(string, required)*: Short 1–2 sentence summary for cards and search results (max 160 characters).
  - `en` *(string, optional)*: English summary or `null`.
- **`description`** *(object, required)*:
  - `ar` *(string, required)*: In-depth markdown description rendered on the agent's detail page.
  - `en` *(string, optional)*: English description or `null`.
- **`category`** *(string, required)*: One of:
  - `"customer-service"` (خدمة العملاء)
  - `"data-analysis"` (تحليل البيانات)
  - `"automation"` (الأتمتة وتدفق العمل)
  - `"coding"` (البرمجة والتطوير)
  - `"finance"` (المالية والمحاسبة)
  - `"research"` (البحث والاستقصاء)
  - `"marketing-analytics"` (التسويق والتحليلات)
  - `"other"` (أخرى)
- **`icon`** *(string, required)*: Icon identifier from Asaas UI / Lucide icons (e.g. `"headset"`, `"chart-bar"`, `"bot"`, `"code"`, `"file-text"`).
- **`status`** *(string, required)*: One of:
  - `"ready"`: Fully verified and active; both live playground and GitHub repository links are enabled.
  - `"coming_soon"`: Displayed in catalog as preview; live demo disabled with friendly badge.
  - `"github_only"`: Open-source agent available for code inspection and manual deployment; live playground disabled (implements Spec Section 6: GitHub presence does not imply live demo).
- **`featured`** *(boolean, required)*: Whether the agent is highlighted in the hero or top section of the home page.

### 3.2 Source & Runtime Execution
- **`github`** *(object, required)*:
  - `url` *(string, required)*: Canonical HTTPS GitHub repository URL.
  - `pinned_ref` *(string, required)*: Exact 40-character hexadecimal Git commit SHA matching regex `^[0-9a-f]{40}$`.
- **`runtime`** *(object, required)*:
  - `kind` *(string, required)*: One of:
    - `"python"`: Ephemeral job agent conforming to `jsonl-stdio@1`.
    - `"service"`: Supervised long-lived daemon process reverse-proxied over an allowlist of loopback routes.
  - `python` *(string, required)*: Supported Python minor version (e.g. `"3.11"`, `"3.12"`).
  - `entrypoint` *(string, optional)*: Relative path to execution script (required when `kind` is `"python"`).
  - `protocol` *(string, optional)*: `"jsonl-stdio@1"` (for job agents).
  - `service_spec` *(object, optional, required for service agents)*:
    - `command` *(string)*: Execution command (e.g. `"uv run uvicorn site_dna.api.main:app --port 8001"`).
    - `host` *(string)*: Loopback bind address (default `"127.0.0.1"`).
    - `port` *(integer)*: Private internal port (e.g. `8001`).
    - `health_check_path` *(string)*: HTTP health endpoint (default `"/api/v1/health"`).
    - `route_allowlist` *(array of regex strings)*: Strict whitelist of forwarded routes.
  - `egress_policy` *(string, optional)*: `"loopback_only"` (default) or `"public_http"`.

### 3.3 Playground & Model Requirements
- **`playground`** *(object, required)*:
  - `mode` *(string, required)*: `"chat"` | `"form"` | `"file-analysis"` | `"custom"` | `"standalone"`.
  - `ui` *(string, required)*: Component identifier mapped in the platform frontend SDK, or sub-app identifier.
  - `mount_path` *(string, optional)*: Sub-app mount path for standalone mode (e.g. `"/agents/site-dna/"`).
  - `api_base` *(string, optional)*: Proxied API base path (e.g. `"/agents-api/site-dna/api/v1"`).
- **`model_requirements`** *(object, required)*:
  - `tool_calling` *(boolean, required)*: Whether the agent invokes function tools.
  - `json_schema` *(boolean, required)*: Whether the agent requires structured schema output.
  - `vision` *(boolean, required)*: Whether the agent processes image inputs.
  - `min_context_tokens` *(integer, required)*: Minimum model context window (e.g. 32000). Models with smaller context windows are filtered out of the selection dropdown.
- **`providers`** *(object, required)*:
  - `allow` *(array of strings, required)*: Subset of `["gemini", "openai", "anthropic", "openrouter"]` verified to run this agent correctly.

### 3.4 Execution Budgets & Limits
- **`limits`** *(object, required)*:
  - `max_steps` *(integer, required)*: Maximum tool/reasoning iterations (default: 8, max: 15).
  - `timeout_seconds` *(integer, required)*: Hard process timeout (default: 120, max: 180).
  - `max_input_chars` *(integer, required)*: Maximum user text input length (default: 8000).
  - `max_output_tokens` *(integer, required)*: Maximum completion tokens per LLM call (default: 2000).
  - `uploads` *(object, required)*:
    - `max_files` *(integer, required)*: Max attachments allowed (e.g. 1).
    - `max_mb` *(integer, required)*: Max total size in megabytes (e.g. 5).
    - `types` *(array of strings, required)*: Allowed MIME types (e.g. `["application/pdf"]`).

---

## 4. The `jsonl-stdio@1` Process Protocol

Communication between the platform runner and the isolated agent child process occurs strictly over standard streams (**stdin**, **stdout**, **stderr**) formatted as **JSON Lines (JSONL)**: one valid JSON object per line, encoded in UTF-8, followed by `\n`.

```
+-----------------------------------------------------------+
|                    FastAPI Runner                         |
+-----------------------------------------------------------+
       |                                              ^
       | stdin: (1) init handshake                    | stdout: JSONL events
       |        (2) user input & files                | (status, delta, step,
       v                                              |  result, error)
+-----------------------------------------------------------+
|               Isolated Agent Subprocess                   |
|  - Calls http://127.0.0.1:<port>/v1 with run_token        |
|  - Zero direct internet access                            |
+-----------------------------------------------------------+
       |
       | stderr: Internal diagnostics buffer (max 64KB)
       v
+-----------------------------------------------------------+
|             Platform Secure Log (Server Only)             |
+-----------------------------------------------------------+
```

### 4.1 Platform -> Agent (Standard Input / stdin)

Upon spawning the agent process, the platform writes exactly **two JSON objects** to `stdin` and then closes `stdin` (`stdin.close()` / EOF):

#### 1. The `init` Message
Sent immediately to supply runtime configuration and the local proxy credentials:
```json
{
  "type": "init",
  "run_id": "run_01j9x03q...",
  "model": "gemini-1.5-flash",
  "provider": "gemini",
  "llm_endpoint": "http://127.0.0.1:8088/v1",
  "run_token": "art_01j9x03q...",
  "limits": {
    "max_steps": 8,
    "timeout_seconds": 120,
    "max_output_tokens": 2000
  }
}
```

#### 2. The `input` Message
Sent immediately following the `init` message, containing the visitor's request:
```json
{
  "type": "input",
  "message": "كيف يمكنني إعادة تعيين كلمة المرور في حسابي؟",
  "parameters": {
    "urgency": "high"
  },
  "files": [
    {
      "filename": "ticket.pdf",
      "path": "/tmp/asaas_runs/run_01j9x03q/uploads/ticket.pdf",
      "mime_type": "application/pdf",
      "size_bytes": 45120
    }
  ]
}
```

---

### 4.2 Agent -> Platform (Standard Output / stdout)

The agent emits events as single-line JSON objects to `stdout` as execution progresses. The platform streams these events to the visitor over the SSE HTTP connection.

#### Event Types:

1. **`status`** (Execution state update):
   ```json
   {"event": "status", "data": {"state": "thinking", "detail": "جاري فحص قاعدة المعرفة..."}}
   ```
   *Valid states:* `"starting"`, `"thinking"`, `"calling_tool"`, `"generating"`, `"completed"`, `"failed"`.

2. **`message_delta`** (Real-time token streaming):
   ```json
   {"event": "message_delta", "data": {"delta": "يمكنك إعادة تعيين كلمة المرور باتباع..."}}
   ```

3. **`step`** (Tool invocation audit trail):
   ```json
   {
     "event": "step",
     "data": {
       "step_number": 1,
       "tool": "search_kb",
       "input": {"query": "reset password"},
       "output": {"found": 1, "article_id": 402}
     }
   }
   ```

4. **`result`** (Final completion payload):
   ```json
   {
     "event": "result",
     "data": {
       "content": "تم إيجاد الخطوات اللازمة لإعادة تعيين كلمة المرور بنجاح.",
       "artifacts": [
         {"type": "link", "title": "دليل الأمان", "url": "https://help.example.com"}
       ]
     }
   }
   ```

5. **`error`** (Recoverable or terminal agent error):
   ```json
   {
     "event": "error",
     "data": {
       "code": "tool_execution_failed",
       "message": "تعذر الاتصال بقاعدة المعرفة المحددة."
     }
   }
   ```

---

### 4.3 Standard Error (stderr) Handling

- **Strict Containment:** The platform captures `stderr` in a bounded circular buffer (maximum 64 KB).
- **Diagnostics Only:** `stderr` output is logged on the server for troubleshooting.
- **Never Shown to Visitors:** Raw `stderr` is **never** sent to the client browser or displayed in the UI, preventing leakage of internal server directory paths, python library versions, or call stacks.

---

## 5. Platform Maximum Ceilings

The platform defines non-negotiable hard ceilings in its backend configuration (`config.py`). If a manifest requests values exceeding these limits, the runner clamps them automatically:

| Parameter | Platform Ceiling | Default Fallback |
| :--- | :--- | :--- |
| **`timeout_seconds`** | **180 seconds** (3.0 minutes) | 120 seconds |
| **`max_steps`** | **15 steps** | 8 steps |
| **`max_input_chars`** | **16,000 characters** | 8,000 characters |
| **`max_output_tokens`** | **4,096 tokens** | 2,000 tokens |
| **`uploads.max_mb`** | **10 MB total** | 5 MB total |
| **`uploads.max_files`** | **3 files** | 1 file |

---

## 6. Minimal Agent Runner Helper (Python Reference)

Agents developed for the platform can use this minimal standard template to handle the `jsonl-stdio@1` protocol:

```python
import sys
import json
from openai import OpenAI

def emit(event: str, data: dict):
    """Write formatted event to stdout."""
    sys.stdout.write(json.dumps({"event": event, "data": data}, ensure_ascii=False) + "\n")
    sys.stdout.flush()

def main():
    # 1. Read init message from stdin
    init_line = sys.stdin.readline()
    if not init_line:
        return
    init_msg = json.loads(init_line)

    # 2. Read input message from stdin
    input_line = sys.stdin.readline()
    if not input_line:
        return
    input_msg = json.loads(input_line)

    emit("status", {"state": "starting", "detail": "تهيئة الوكيل..."})

    # 3. Configure OpenAI client pointing to platform local proxy
    client = OpenAI(
        base_url=init_msg["llm_endpoint"],
        api_key=init_msg["run_token"],
    )

    emit("status", {"state": "thinking", "detail": "جاري التفكير..."})

    # 4. Stream completion through platform proxy
    response = client.chat.completions.create(
        model=init_msg["model"],
        messages=[
            {"role": "system", "content": "أنت وكيل ذكي ودود."},
            {"role": "user", "content": input_msg["message"]},
        ],
        stream=True,
    )

    full_reply = []
    for chunk in response:
        delta = chunk.choices[0].delta.content or ""
        if delta:
            full_reply.append(delta)
            emit("message_delta", {"delta": delta})

    # 5. Emit final result
    emit("result", {
        "content": "".join(full_reply),
        "artifacts": []
    })

if __name__ == "__main__":
    main()
```
