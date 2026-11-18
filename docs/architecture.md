# معمارية منصة وكلاء أساس — System Architecture

يوثق هذا المستند الهيكل المعماري، وحدود الثقة، ودورة حياة المفاتيح وتدفق البيانات لمنصة **وكلاء أساس (ASAAS Agents Platform)**.

---

## 1. النظرة المعمارية العامة (System Overview)

المنصة مصممة وفق نموذج **أحضر مفتاحك الخاص (BYOK)** كمعرض عام لوكلاء الذكاء الاصطناعي مع إمكانية التجربة الحية الفورية دون الحاجة إلى إنشاء حسابات مستخدمين.

```mermaid
flowchart TD
    subgraph Client["بيئة العميل (متصفح الزائر)"]
        UI["واجهة الويب (React + Vite + Asaas UI)"]
        Storage["sessionStorage (اختياري، يمسح عند إغلاق التبويب)"]
    end

    subgraph Edge["خادم الحافة والحماية"]
        Proxy["خادم عكسي (NGINX / Caddy)"]
    end

    subgraph Backend["الخادم الخلفي (FastAPI Server)"]
        RateLimit["مانع الإساءة وتحديد المعدل (SecurityRateLimiter)"]
        Catalog["خدمة الكتالوج (Catalog Service + SQLite)"]
        RunRouter["موجه التجارب (Runs Router)"]
        Registry["سجل رموز التشغيل المؤقتة (In-Memory Token Registry)"]
        Loopback["وكيل النماذج المحلي (/v1/chat/completions)"]
        Gateway["بوابة المزودين (LLM Gateway)"]
    end

    subgraph Sandbox["بيئة تشغيل الوكيل المعزولة"]
        AgentProc["عملية الوكيل المستقلة (Isolated Subprocess)"]
        TempDir["دليل عمل مؤقت خاص (Private Temp Dir)"]
    end

    subgraph Providers["مزودو الذكاء الاصطناعي الخارجيون"]
        Google["Google AI Studio"]
        OpenAI["OpenAI"]
        Anthropic["Anthropic"]
        OpenRouter["OpenRouter"]
    end

    UI -->|"طلب HTTPS مع مفتاح الزائر"| Proxy
    Proxy -->|"اتصال محلي مشفر"| RateLimit
    RateLimit --> Catalog
    RateLimit --> RunRouter
    RunRouter -->|"إنشاء رمز تشغيل مؤقت"| Registry
    RunRouter -->|"تشغيل عملية الوكيل"| AgentProc
    AgentProc -->|"استدعاء النماذج عبر الرمز المؤقت"| Loopback
    Loopback -->|"التحقق وحقن المفتاح الحقيقي"| Registry
    Loopback -->|"استدعاء المزود المعتمد"| Gateway
    Gateway -->|"طلب HTTPS مع مفتاح الزائر"| Providers
```

---

## 2. حدود الثقة ونموذج الأمان (Trust Boundaries)

### أ. واجهة المتصفح -> الخادم الخلفي (Browser to Backend Boundary)
- **مستوى الثقة:** غير موثوق بالكامل (Untrusted).
- **الضوابط المفروضة:**
  - استخراج عنوان IP الحقيقي عبر `trusted_proxies` فقط، لمنع تزوير ترويسة `X-Forwarded-For`.
  - تطبيق حدود الطلبات متعددة الطبقات (فحص المفتاح: 10/دقيقة، اختبار الاتصال: 6/دقيقة، بدء التشغيل: 10/دقيقة، سقف يومي: 50/يوم).
  - حظر الطلبات التي يتجاوز حجمها 5 ميغابايت بـ HTTP 413.
  - فحص سحري لتوقيع الملفات المرفوعة (Magic Bytes) لمنع خداع امتدادات الملفات.

### ب. الخادم الخلفي -> مزودات LLM الخارجية (Backend to LLM Gateway)
- **مستوى الثقة:** موثوقية خارجية مقيدة.
- **الضوابط المفروضة:**
  - عناوين المزودين محصورة بقائمة بيضاء صارمة وثابتة (`settings.provider_base_urls`). لا يمكن للزائر أو الوكيل تحديد Base URL، مما يلغي تماماً هجمات SSRF.
  - تمرير مفتاح الزائر بشكل عابر دون حفظ في أي ملف أو قاعدة بيانات أو سجل.
  - معالجة الأخطاء وتحويلها إلى رسائل عربية موحدة مع حجب نصوص الأخطاء الخام التي قد تسرب المفاتيح.

### ج. الخادم الخلفي -> عملية تشغيل الوكيل (Backend to Agent Subprocess)
- **مستوى الثقة:** كود شبه موثوق (Semi-trusted code).
- **الضوابط المفروضة:**
  - لا يستلم الوكيل المفتاح الحقيقي إطلاقاً (لا في المتغيرات البيئية، ولا في الوسائط، ولا في الملفات).
  - يستلم الوكيل فقط عنوان الوكيل المحلي (`http://127.0.0.1:8088/v1/chat/completions`) ورمز تشغيل مؤقت مشفر (`run_token`).
  - تشغيل في بيئة نظيفة خالية من المتغيرات البيئية للنظام ومفاتيح المنصة.
  - قيود صارمة على زمن التشغيل (Timeout)، وسعة تدفق المخرجات (الحد الأقصى لكل سطر: 64 كيلوبايت لمنع إغراق الذاكرة).
  - إلغاء وإتلاف رمز التشغيل فور انتهاء العملية وتصفية شجرة العمليات بالكامل لمنع العمليات الشاردة (Orphan processes).

---

## 3. دورة حياة المفتاح وتدفق البيانات (BYOK Lifecycle)

```mermaid
sequenceDiagram
    autonumber
    actor Visitor as الزائر (المتصفح)
    participant UI as واجهة الموقع
    participant API as خادم المنصة (FastAPI)
    participant Registry as سجل الرموز المؤقت
    participant Subproc as عملية الوكيل (Subprocess)
    participant Gateway as بوابة LLM
    participant Provider as مزود الخدمة (مثل Google/OpenAI)

    Visitor->>UI: إدخال المفتاح واختيار النموذج
    UI->>API: POST /api/providers/validate (مع المفتاح في الترويسة)
    API->>Gateway: استدعاء list_models للتحقق
    Gateway->>Provider: طلب خفيف وغير مكلف
    Provider-->>Gateway: تأكيد صحة المفتاح
    Gateway-->>API: المفتاح صالح
    API-->>UI: 200 OK (المفتاح لا يحفظ في الخادم)

    Visitor->>UI: بدء تجربة الوكيل
    UI->>API: POST /api/agents/{slug}/run (مع المفتاح والمدخلات)
    API->>Registry: توليد run_token مؤقت وربطه بـ (المفتاح، المزود، النموذج)
    API->>Subproc: إطلاق عملية الوكيل وتمرير (run_token, local_url)
    Subproc->>API: POST /v1/chat/completions (مع Bearer run_token)
    API->>Registry: التحقق من صحة الرمز واسترجاع المفتاح والنموذج الإلزامي
    API->>Gateway: إرسال الطلب للمزود مع المفتاح الحقيقي
    Gateway->>Provider: إرسال استدعاء النموذج
    Provider-->>Gateway: تدفق الإجابة
    Gateway-->>API: تمرير الرد
    API-->>Subproc: تمرير الرد بصيغة OpenAI المتوافقة
    Subproc->>API: بث أحداث الخطوات والنتائج عبر stdout (NDJSON)
    API->>UI: بث الأحداث للزائر عبر SSE / Streaming HTTP
    Subproc-->>API: خروج العملية (Exit)
    API->>Registry: إبطال رمز التشغيل فوراً ومسح بيانات الجلسة من الذاكرة
```

---

## 4. الإحصاءات الصديقة للخصوصية (Privacy-Preserving Telemetry)

تطبيقاً للقرار المعماري **D7**:
- تسجل المنصة فقط عدادات إجمالية مجهولة لكل وكيل: (عدد المشاهدات، عدد التجارب المبدوءة، عدد التجارب الناجحة، عدد التجارب الفاشلة).
- لا يتم استخدام ملفات تعريف الارتباط (No Cookies)، ولا عناوين IP، ولا بصمات المتصفح (No Fingerprinting).
- تحترم المنصة خيارات عدم التتبع الصريحة في المتصفح (`DNT: 1` و `Sec-GPC: 1`) سواء في كود الواجهة الأمامية أو عند معالجة طلبات الخادم.
- لا تظهر إحصائية "عدد التجارب" في الصفحة الرئيسية إلا في حال وجود تجارب حقيقية مكتملة.

---

## 5. مراجع الملفات (File References)
- بيان مواصفات الوكلاء: [agent-manifest.md](file:///C:/Users/mahmoodSaeed/Desktop/asaas_skills/skills-main/skills-main/docs/agent-manifest.md)
- مصفوفة المزودين: [provider-matrix.md](file:///C:/Users/mahmoodSaeed/Desktop/asaas_skills/skills-main/skills-main/docs/provider-matrix.md)
- تقرير الأمان: [audit-report.md](file:///C:/Users/mahmoodSaeed/Desktop/asaas_skills/skills-main/skills-main/docs/security/audit-report.md)
