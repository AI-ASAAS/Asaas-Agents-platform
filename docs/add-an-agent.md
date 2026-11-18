# دليل إضافة وكيل جديد للمنصة — Add an Agent Developer Runbook

يوضح هذا الدليل خطوة بخطوة لمطوري أساس (ASAAS Developers) كيفية إنشاء وكيل ذكاء اصطناعي جديد ودمجه في منصة **وكلاء أساس (ASAAS Agents Platform)**، والتوافق مع بروتوكول التشغيل المعزول `jsonl-stdio@1`.

---

## 1. الهيكل العام للوكيل (Agent Directory Layout)

يجب وضع كل وكيل جديد في مجلد مستقل داخل مجلد `agents/` باسم يطابق المعرف الفريد (`slug`):

```
agents/<your-agent-slug>/
├── agent.manifest.json       # بيان الوكيل الإلزامي المعتمد (schema_version: 1)
├── src/                      # مجلد الشيفرة المصدرية المربوط بالمستودع
│   ├── main.py               # نقطة الدخول البرمجية الرئيسية
│   └── requirements.txt      # ملف حزم الاعتماديات المثبتة والمقفلة
└── README.md                 # توثيق الوكيل للمطورين
```

---

## 2. بيان مواصفات الوكيل (agent.manifest.json)

يجب أن يلتزم ملف `agent.manifest.json` بدقة بنموذج Pydantic المعتمد في `manifest_schema.py`.

مثال معتمد وصالح 100%:
```json
{
  "schema_version": 1,
  "slug": "data-extractor",
  "name": {
    "ar": "مستخرج البيانات والجداول",
    "en": "Data Extractor Agent"
  },
  "summary": {
    "ar": "استخراج الجداول والبيانات المنظمة من المستندات والتقارير وتحويلها إلى CSV أو JSON.",
    "en": "Structured extraction of tables and forms from business documents into clean CSV or JSON."
  },
  "description": {
    "ar": "وكيل متخصص في قراءة الوثائق المالية والتقارير لاستخلاص الجداول بصيغة دقيقة مع التحقق من صحة الأرقام.",
    "en": "Specialized agent for analyzing invoices, financial statements, and tabular reports with verification."
  },
  "category": "data-analysis",
  "icon": "sparkle",
  "status": "ready",
  "featured": false,
  "is_sample": false,
  "github": {
    "url": "https://github.com/asaas-ai/agent-data-extractor",
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
    "ui": "data-extractor"
  },
  "model_requirements": {
    "tool_calling": true,
    "json_schema": true,
    "vision": false,
    "min_context_tokens": 16000
  },
  "providers": {
    "allow": ["gemini", "openai", "anthropic", "openrouter"]
  },
  "limits": {
    "max_steps": 10,
    "timeout_seconds": 60,
    "max_input_chars": 8000,
    "max_output_tokens": 2000,
    "uploads": {
      "max_files": 1,
      "max_mb": 5,
      "types": ["application/pdf"]
    }
  }
}
```

> [!IMPORTANT]
> - `schema_version` يجب أن يكون الرقم `1`.
> - `github.pinned_ref` يجب أن يكون commit SHA كاملاً بطول 40 خانة ست عشرية (Hexadecimal SHA) وليس اسم فرع.
> - `category` يجب أن تكون إحدى القيم التالية: `customer-service`, `data-analysis`, `automation`, `coding`, `finance`, `research`, `other`.
> - `providers.allow` تحدد المزودات المتوافقة مع متطلبات الوكيل.

---

## 3. عقد بروتوكول التنفيذ المباشر (jsonl-stdio@1 Execution Contract)

تطلق المنصة عملية الوكيل كـ Subprocess مستقل ببيئة معقمة وخالية من المفاتيح وأسرار النظام. يتم التواصل بالكامل عبر التيارات القياسية (`stdin` و `stdout`).

### أ. رسائل المصافحة عبر stdin (Handshake on stdin)
ترسل المنصة رسالتين بتنسيق JSON (كل رسالة في سطر مستقل ينتهي بـ `\n`):

1. **رسالة التهيئة (`init`):**
   ```json
   {
     "type": "init",
     "run_id": "run_abc123",
     "model": "gemini-2.0-flash",
     "provider": "gemini",
     "llm_endpoint": "http://127.0.0.1:8088/v1",
     "run_token": "art_...",
     "limits": {
       "max_steps": 10,
       "timeout_seconds": 60,
       "max_output_tokens": 2000
     }
   }
   ```
2. **رسالة المدخلات (`input`):**
   ```json
   {
     "type": "input",
     "message": "استخرج لي جدول الأرباح من هذا التقرير",
     "parameters": {},
     "files": [
       {
         "filename": "report.pdf",
         "path": "/path/to/temp/uploads/report.pdf",
         "mime_type": "application/pdf",
         "size_bytes": 102400
       }
     ]
   }
   ```

### ب. نمط التكامل البرمجي العملي (OpenAI SDK & CrewAI Pattern)

داخل نقطة الدخول `src/main.py`، نقوم بقراءة رسالتي `init` و `input`، ثم توجيه عميل الـ LLM إلى وكيل النماذج المحلي:

```python
import sys
import json
import os
from openai import OpenAI

def emit(event: str, data: dict):
    """إرسال حدث إلى المنصة بصيغة NDJSON وتفريغ التيار فوراً."""
    line = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()

def main():
    # 1. قراءة رسالة التهيئة
    init_line = sys.stdin.readline()
    if not init_line:
        return
    init_data = json.loads(init_line)

    # 2. قراءة مدخلات المستخدم والملفات
    input_line = sys.stdin.readline()
    if not input_line:
        return
    input_data = json.loads(input_line)

    endpoint = init_data["llm_endpoint"]
    token = init_data["run_token"]
    model = init_data["model"]

    # 3. إعداد عميل OpenAI ليشير إلى الوكيل المحلي الخاص بالمنصة
    # (المنصة تحقن مفتاح الزائر الحقيقي وتفرض النموذج المختار عبر الرمز المؤقت)
    os.environ["OPENAI_BASE_URL"] = endpoint
    os.environ["OPENAI_API_KEY"] = token
    client = OpenAI(base_url=endpoint, api_key=token)

    # 4. إرسال أحداث الحالة والخطوات
    emit("status", {"stage": "analyzing", "message": "بدء تحليل التقرير واستخراج الجداول..."})
    emit("step", {"title": "فحص هيكلية المستند", "detail": "تم العثور على جدول البيانات المالية"})

    # 5. استدعاء النموذج عبر الوكيل المحلي
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "أنت خبير في استخراج الجداول من المستندات."},
            {"role": "user", "content": input_data["message"]},
        ],
    )
    result_text = response.choices[0].message.content

    # 6. إرسال النتيجة النهائية
    emit("result", {"text": result_text, "data": {"extracted": True}})

if __name__ == "__main__":
    main()
```

### ج. أنواع الأحداث المصرح بها (Allowed Event Types)
يسمح للوكيل بإصدار الأحداث التالية فقط:
- `status`: حالة الوكيل الحالية (`stage`, `message`).
- `step`: خطوة فرعية ينجزها الوكيل (`title`, `detail`).
- `message_delta`: تدفق نصي تدريجي (`text`).
- `result`: النتيجة النهائية للتجربة (`text`, `data`).
- `error`: خطأ في التنفيذ ينهي التجربة (`code`, `message`).

> [!CAUTION]
> أحداث `usage` و `done` محجوزة للمنصة حصراً؛ حيث تحسب المنصة التوكنات والاستهلاك بشكل موثوق ومستقل عبر وسيط النماذج. إصدار أي أحداث محجوزة أو غير مصرح بها سيوقف التجربة فوراً بخطأ أمان.

---

## 4. ربط واجهة المستخدم التفاعلية للوكيل (Agent UI SDK)

إذا كان للوكيل واجهة مستخدم تفاعلية خاصة في المعرض:

1. أنشئ مجلد الواجهة: `web/src/agent-ui/<slug>/index.tsx`.
2. استخدم خطاف (Hook) المنصة الموحد `useAgentRun`:

```tsx
import React, { useState } from 'react';
import { useAgentRun } from '../../agent-sdk';
import { Card, Icon } from '../../asaas-ui';

export default function DataExtractorPlayground() {
  const [inputText, setInputText] = useState('');
  const { run, isRunning, events, result, error } = useAgentRun({
    agentSlug: 'data-extractor',
  });

  const handleStart = () => {
    run({ message: inputText });
  };

  return (
    <Card title="تجربة الوكيل التفاعلية" icon="sparkle">
      <textarea
        value={inputText}
        onChange={(e) => setInputText(e.target.value)}
        placeholder="أدخل نص الاستخراج هنا..."
        className="field"
        rows={4}
      />
      <button
        onClick={handleStart}
        disabled={isRunning || !inputText.trim()}
        className="btn btn--primary"
      >
        <Icon name="sparkle" />
        <span>{isRunning ? 'جاري المعالجة...' : 'بدء الاستخراج'}</span>
      </button>

      {result && (
        <div className="agent-result-box" style={{ marginTop: '16px' }}>
          <h4>النتيجة:</h4>
          <p>{result.text}</p>
        </div>
      )}
    </Card>
  );
}
```

3. سجّل المكون في جدول الواجهات: `web/src/agent-ui/index.ts`:
```ts
import { lazy } from 'react';

export const agentUIRegistry: Record<string, React.LazyExoticComponent<any>> = {
  'support-agent': lazy(() => import('./support-agent')),
  'document-analyzer': lazy(() => import('./document-analyzer')),
  'data-extractor': lazy(() => import('./data-extractor')),
};
```

---

## 5. مزامنة وتحميل الوكيل والتحقق من صحته (Sync & Seeding)

1. **مزامنة الكود والحزم عند الـ commit SHA المقفل:**
   ```bash
   python scripts/sync_agents.py
   ```
2. **التحقق من صحة البيان وتحميله في قاعدة البيانات:**
   ```bash
   cd api
   python -c "import asyncio; from modules.catalog import load_and_seed_agents; asyncio.run(load_and_seed_agents())"
   ```
3. **التأكد من ظهور الوكيل في نقطة الكتالوج:**
   ```bash
   curl http://127.0.0.1:8088/api/agents/data-extractor
   ```

---

## 6. وكلاء الخدمات طويلي الأمد (Tier-2 Service Agents)

للأنظمة المعقدة التي تعمل كخدمة خلفية مستمرة (Managed Service Daemon) مثل **بصمة الموقع (Site DNA)** وتتطلب متصفحاً آلياً أو مراحل متعددة تستغرق دقائق:

1. **تحديد نمط التشغيل في البيان (`agent.manifest.json`):**
   ```json
   "runtime": {
     "kind": "service",
     "python": "3.11",
     "service_spec": {
       "command": "uv run uvicorn site_dna.api.main:app --host 127.0.0.1 --port 8001 --workers 1",
       "host": "127.0.0.1",
       "port": 8001,
       "health_check_path": "/api/v1/health",
       "route_allowlist": [
         "^/api/v1/health$",
         "^/api/v1/agents$",
         "^/api/v1/dashboard/summary$",
         "^/api/v1/runs$",
         "^/api/v1/runs/[a-zA-Z0-9_-]+$",
         "^/api/v1/runs/[a-zA-Z0-9_-]+/cancel$",
         "^/api/v1/runs/[a-zA-Z0-9_-]+/events$"
       ]
     },
     "egress_policy": "public_http"
   },
   "playground": {
     "mode": "standalone",
     "mount_path": "/agents/site-dna/app/",
     "api_base": "/agents-api/site-dna/api/v1",
     "ui": "site-dna"
   },
   "limits": {
     "max_wall_clock_seconds": 1200,
     "platform_concurrent_runs": 2,
     "session_concurrent_runs": 1,
     "session_daily_runs": 3,
     "max_pages_per_run": 8
   }
   ```
2. **إدارة المفاتيح والجلسات وعزل التزامن:**
   - تبدأ الجلسة في صفحة تفاصيل الوكيل (`/agents/<slug>`) بإرسال مفتاح الزائر عبر الرأس `X-Provider-Key` إلى `POST /api/service-sessions/init`، ويُحفظ في الذاكرة فقط مع كوكيز `asaas_service_session` بخاصيتي `HttpOnly; SameSite=Strict` (مهلة 45 دقيقة خمول / ساعتان كحد أقصى).
   - عند بدء كل جولة (`POST /agents-api/<slug>/api/v1/runs`)، يولّد وسيط المنصة معرفاً عشوائياً (`run-<32 hex>`) ورمزاً مؤقتاً (`art_...`) قبل التوجيه، ويرسل للوكيل الرؤوس: `X-Run-Id`, `X-Run-Token`, `X-LLM-Endpoint`, `X-LLM-Model`, `X-LLM-Provider` (مع حذف `Cookie` و`Authorization` و`X-Provider-Key` تماماً).
   - يجب على الوكيل حفظ سياق الرمز في `contextvars.ContextVar` (وليس في `os.environ`) لدعم تزامن الجولات دون تسريب أو تداخل.
   - يجب تشغيل المنصة والوكيل بعامل واحد فقط (`--workers 1`) للحفاظ على اتساق سجل الرموز ومحددات التزامن وتيارات SSE.
3. **المزامنة والبناء (`scripts/sync_agents.py`):**
   - يتحقق السكربت من مطابقة `pinned_ref` (40 خانة SHA)، ويبني البيئة عبر `uv sync --frozen --python <ver>`، ويثبّت Playwright Chromium في مجلد مملوك للوكيل (`.playwright-browsers`)، ويبني الواجهة الأمامية المستقلة بمتغيرات `VITE_BASE_PATH` و`VITE_API_BASE`.
4. **متطلبات الأمان للوكلاء الذين يزحفون على الويب (S7/S8):**
   - حظر جميع عناوين IP المباشرة والنطاقات الداخلية ونطاقات المنصة، وقصر المنافذ على 80/443 فقط.
   - إلزام الزائر بتأكيد الموافقة (`consent_confirmed: true`) قبل التشغيل، وتعطيل فحص المنافسين افتراضياً، وعرض تقدير استهلاك النموذج قبل البدء، وحذف المخرجات تلقائياً بعد 60 دقيقة من الانتهاء.
   - عزل معاينة تقارير HTML داخل `iframe` بسمة `sandbox=""` وترويسة CSP صارمة تمنع السكربتات.
