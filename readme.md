# منصة وكلاء أساس — ASAAS Agents Platform

منصة ويب عامة باللغة العربية (RTL، ومصممة للهواتف أولاً) تستعرض نماذج ووكلاء الذكاء الاصطناعي المطورين بواسطة فريق أساس (ASAAS AI).
تتيح المنصة للزوار استكشاف الوكلاء، وتجربتهم مباشرة عبر نموذج BYOK (أحضر مفتاحك الخاص)، أو الاطلاع على شفراتهم المصدرية على GitHub.

---

## 🌟 المبادئ الأساسية للمنصة (Architectural Principles)
1. **بدون حسابات أو تسجيل دخول (No Accounts / No Sign-In):** تعمل المنصة بالكامل بنظام الجلسات المؤقتة لكل متصفح (`sessionStorage` الاختياري).
2. **أحضر مفتاحك الخاص (BYOK — Bring Your Own Key):** جميع التجارب الحية تعمل على مفتاح الزائر الخاص وبحصته من المزود المختار. لا تدفع أساس تكاليف استدعاء النماذج، ولا يتم تضمين أي مفاتيح خاصة بالشركة.
3. **انعدام حفظ المفاتيح نهائياً (Zero Key Persistence):** لا يتم حفظ مفتاح الزائر في أي قاعدة بيانات، ولا في أقراص الخادم، ولا في أي سجلات (Logs مشفرة ومعقمة). المفتاح يمر كـ Bearer Header مشفر عبر HTTPS فقط.
4. **عزل كامل لتشغيل الوكلاء (Process Isolation):** كل وكيل يعمل كعملية فرعية معزولة (`subprocess`) بصلاحيات مقيدة ودليل عمل مؤقت ينظف فور الانتهاء، دون أي وصول للشبكة الخارجية عدا نقطة اتصال النماذج المحلية (`/v1/chat/completions`) عبر رمز تشغيل مؤقت (`run_token`).
5. **تصميم بهوية أساس الرسمية (Asaas UI & Thmanyah Font):** واجهة بالخطوط الرسمية (ثمانية)، وتصميم الزجاج السائل Liquid Glass، مع دعم الوضع الداكن والفاتح.

---

## 📁 هيكلية المستودع (Repository Structure)
```
├── api/            # الواجهة الخلفية المبنية بـ FastAPI وفق معمارية أساس القياسية
│   ├── modules/    # وحدات النظام: catalog, llm, providers, runtime, runs, security
│   ├── config.py   # إعدادات المنصة وحدود الحماية
│   ├── main.py     # نقطة انطلاق الخادم والوسطاء
│   └── data/       # قاعدة بيانات SQLite الخفيفة (كتالوج الوكلاء والإحصاءات المجهولة)
├── web/            # الواجهة الأمامية المبنية بـ React + Vite + TypeScript مع kit أساس
│   ├── src/pages/  # صفحات المنصة: الرئيسية، تفاصيل الوكيل، عن المنصة، الخصوصية، الشروط
│   ├── src/components/ # مكونات الواجهة: شريط الإحصاءات، مسار المفتاح، بطاقات الوكلاء
│   └── src/asaas-ui/   # حزمة مكونات أساس وتوكنات التصميم والخطوط
├── agents/         # مستودع الوكلاء المدمجين (لكل وكيل بيان agent.manifest.json وشفرته)
│   ├── support-agent/      # وكيل خدمة العملاء الذكي
│   └── document-analyzer/  # وكيل تحليل وتلخيص المستندات
└── docs/           # التوثيق الشامل، قرارات التصميم، ومصفوفة المزودين، وتقارير الأمان
```

---

## 🚀 التشغيل المحلي والتطوير (Local Setup)

### المتطلبات المسبقة:
- **Node.js** (v18 فأعلى) و **npm**
- **Python** (v3.10 فأعلى)

### 1. تشغيل الواجهة الخلفية (Backend API):
```bash
cd api
python -m venv .venv
# تفعيل البيئة (Linux/macOS: source .venv/bin/activate | Windows: .venv\Scripts\activate)
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8088 --reload
```
- ستعمل الواجهة الخلفية على: `http://127.0.0.1:8088`
- توثيق Swagger التفاعلي: `http://127.0.0.1:8088/docs`

### 2. تشغيل الواجهة الأمامية (Frontend Web):
```bash
cd web
npm install
npm run dev
```
- ستعمل الواجهة الأمامية التفاعلية على: `http://localhost:5173`

---

## ⚙️ الإعدادات وحدود الحماية (Configuration)

يتم ضبط الإعدادات عبر المتغيرات البيئية أو ملف `.env` داخل مجلد `api/`:
- `TRUSTED_PROXIES`: قائمة بعناوين IP الخوادم العكسية الموثوقة (مثل `["127.0.0.1"]`) لاستخراج IP العميل الحقيقي بأمان ومنع تزوير `X-Forwarded-For`.
- `RATE_LIMIT_VALIDATE_KEY_PER_MIN`: الحد الأقصى لمحاولات فحص المفاتيح (الافتراضي: 10 لكل دقيقة لكل IP).
- `RATE_LIMIT_TEST_CONNECTION_PER_MIN`: الحد الأقصى لمحاولات اختبار الاتصال (الافتراضي: 6 لكل دقيقة لكل IP).
- `RATE_LIMIT_RUN_STARTS_PER_MIN`: الحد الأقصى لبدء التجارب (الافتراضي: 10 لكل دقيقة لكل IP).
- `RATE_LIMIT_DAILY_RUNS_PER_IP`: السقف اليومي للتجارب لكل عنوان IP (الافتراضي: 50 تجربة، يعاد ضبطه منتصف الليل UTC).
- `MAX_REQUEST_BODY_BYTES`: الحد الأقصى لحجم حمولة الطلب (الافتراضي: 5 ميغابايت لمنع هجمات حجب الخدمة).

---

## 🧪 الفحص والاختبارات (Testing & Security Verification)

تشغيل مجموعة اختبارات الأمان والتكامل للواجهة الخلفية:
```bash
cd api
python test_phase4.py   # اختبارات عزل العمليات، ووكيل Loopback، وفحص تدفق البث
python test_phase5.py   # اختبارات حدود الحماية، ومنع SSRF، والإحصاءات المجهولة، وفحص الذاكرة
```

تدقيق حزم الاعتماديات (Supply Chain Audits):
```bash
cd web && npm audit
cd api && python -m pip_audit -r requirements.txt
```

بناء الواجهة الأمامية للإنتاج:
```bash
cd web
npm run build
```

---

## 📚 روابط التوثيق الإضافية (Documentation Directory)
- [معمارية النظام وتدفق البيانات (Architecture)](file:///C:/Users/mahmoodSaeed/Desktop/asaas_skills/skills-main/skills-main/docs/architecture.md)
- [دليل إضافة وكيل جديد للمطورين (Add an Agent)](file:///C:/Users/mahmoodSaeed/Desktop/asaas_skills/skills-main/skills-main/docs/add-an-agent.md)
- [دليل التشغيل والصيانة وضبط الحدود (Operations)](file:///C:/Users/mahmoodSaeed/Desktop/asaas_skills/skills-main/skills-main/docs/operations.md)
- [دليل النشر والإنتاج على الخادم (Deploy Guide)](file:///C:/Users/mahmoodSaeed/Desktop/asaas_skills/skills-main/skills-main/docs/deploy.md)
- [تقرير التدقيق الأمني الشامل (Security Audit Report)](file:///C:/Users/mahmoodSaeed/Desktop/asaas_skills/skills-main/skills-main/docs/security/audit-report.md)
- [مصفوفة المزودين والنماذج (Provider Matrix)](file:///C:/Users/mahmoodSaeed/Desktop/asaas_skills/skills-main/skills-main/docs/provider-matrix.md)
- [قرارات التصميم المعماري (Architectural Decisions)](file:///C:/Users/mahmoodSaeed/Desktop/asaas_skills/skills-main/skills-main/docs/decisions.md)
