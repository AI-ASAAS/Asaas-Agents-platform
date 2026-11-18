# دليل التشغيل والصيانة — Platform Operations & Maintenance Runbook

يوفر هذا الدليل العمليات اليومية لفرق العمليات والهندسة لمنصة **وكلاء أساس (ASAAS Agents Platform)**، بما يشمل ضبط الحدود، وتحديث قدرات النماذج، ومراقبة السجلات، وصيانة قاعدة البيانات.

---

## 1. ضبط حدود تحديد المعدل ومكافحة الإساءة (Tuning Rate Limits)

يتم تكوين جميع معايير الحماية في ملف `api/config.py` (أو عبر المتغيرات البيئية في الإنتاج):

```python
# إعدادات الحماية وتحديد المعدل (قابلة للضبط بحسب الاستخدام الفعلي)
RATE_LIMIT_VALIDATE_KEY_PER_MIN: int = 10      # حد فحص المفاتيح بالدقيقة لكل IP
RATE_LIMIT_TEST_CONNECTION_PER_MIN: int = 6    # حد اختبار الاتصال بالدقيقة لكل IP
RATE_LIMIT_RUN_STARTS_PER_MIN: int = 10        # حد بدء التجارب بالدقيقة لكل IP
RATE_LIMIT_DAILY_RUNS_PER_IP: int = 50         # السقف اليومي للتجارب لكل IP
MAX_REQUEST_BODY_BYTES: int = 5_242_880        # 5 ميغابايت كحد أقصى لحجم الطلب
TRUSTED_PROXIES: list[str] = ["127.0.0.1"]      # خوادم البروكسي الموثوقة لاستخراج عنوان العميل
```

> [!TIP]
> **توصية الضبط:** يتم تقييم الحدود بعد مرور أول أسبوع من الإطلاق الفعلي. إذا لوحظ حظر لزوار شرعيين يقومون بتجارب متعددة، يمكن رفع `RATE_LIMIT_DAILY_RUNS_PER_IP` إلى 100 أو تقليل فترات الانتظار.

### متطلب عامل التشغيل الواحد (Single Worker Architecture)
> [!WARNING]
> يجب تشغيل الخادم دائماً بعامل واحد فقط (`--workers 1` أو `WEB_CONCURRENCY=1`). إدارة الحالة (سجل رموز الجلسات `run_token_registry`، ومحدد المعدل `SecurityRateLimiter`، وقفل التزامن) تعيش في الذاكرة الحية للعملية عمداً لضمان عدم حفظ المفاتيح المؤقتة. تشغيل عمال متعددين سيؤدي إلى تشتت الذاكرة وفشل استدعاءات الوكلاء بخطأ 401 Unauthorized ومضاعفة حدود الطلبات. التوسع متعدد العمال مستهدف لمرحلة ما بعد الـ MVP عبر مخزن مشترك (Redis/Dragonfly).

---

## 2. تحديث قدرات النماذج والمزودين (Provider & Model Metadata)

تحتفظ المنصة بملفي JSON داخل `api/data/` كمرجع موثوق وسريع بدون الحاجة لاستدعاءات خارجية مكلفة:

### أ. ملف قدرات النماذج: `api/data/model_capabilities.json`
يحدد هذا الملف ميزات كل نموذج ومطابقته لمتطلبات الوكلاء:
```json
{
  "gemini-2.0-flash": {
    "display_name": "Gemini 2.0 Flash (Fast & Capable)",
    "tool_calling": true,
    "json_schema": true,
    "vision": true,
    "max_context": 1048576,
    "is_free_tier": true
  }
}
```
*عندما تصدر Google أو OpenAI نموذجاً جديداً:* أضف النموذج إلى القائمة وحدد ما إذا كان يدعم استدعاء الأدوات ومخرجات JSON بدقة.

### ب. ملف حدود المزودين المجانية: `api/data/provider_limits.json`
يحتوي على إرشادات الحصول على المفتاح المجاني وتفاصيل الحصص الرسمية التي تُعرض للزائر في واجهة BYOK.
*عند تحديث أي سياسة من المزود:* قم بتعديل رابط صفحة المفاتيح والخطوات باللغة العربية.

---

## 3. مراقبة وفحص السجلات (Log Monitoring & Key Redaction)

تستخدم المنصة مرشح تصفية وتعقيم آلي للسجلات (`RedactedLoggerFilter`) يحظر طباعة أي مفاتيح في سجلات الخادم:
- يتم تحويل أي تسلسل يشبه `sk-...` أو `AIzaSy...` تلقائياً إلى `[REDACTED_API_KEY]`.
- عند فحص السجلات، يمكنك تشغيل الاختبار الدوري للتأكد من فاعلية التصفية:
  ```bash
  cd api
  python -c "from main import test_log_redaction; assert test_log_redaction(), 'Redaction failed!'"
  ```

---

## 4. صيانة وتفقد قاعدة البيانات (SQLite in WAL Mode)

تستخدم المنصة قاعدة بيانات SQLite خفيفة وسريعة في `api/data/app.db` مفعلة بوضع **Write-Ahead Logging (WAL)**:

### أ. تفقد الإحصاءات المجهولة (Anonymous Stats):
يمكنك استعراض العدادات المجهولة للوكلاء دون وجود أي مساس بخصوصية الزائرين:
```bash
sqlite3 api/data/app.db "SELECT slug, views_count, runs_started, runs_succeeded, runs_failed, last_updated FROM agent_stats;"
```

### ب. النسخ الاحتياطي الساخن (Online Hot Backup):
نظراً لأن قاعدة البيانات تعمل في وضع WAL، يمكن إجراء نسخ احتياطي آمن دون إيقاف الخادم:
```bash
sqlite3 api/data/app.db ".backup 'api/data/app_backup.db'"
```

### ج. صيانة الـ WAL Checkpoint:
يقوم الخادم تلقائياً بإجراء Checkpoint عند الإغلاق. إذا كان حجم ملف `-wal` كبيراً أثناء التشغيل المستمر، يمكن إجبار الـ Checkpoint بالأمر:
```bash
sqlite3 api/data/app.db "PRAGMA wal_checkpoint(TRUNCATE);"
```
