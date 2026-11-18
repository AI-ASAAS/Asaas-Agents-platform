# دليل النشر والإنتاج — Production Deployment Guide

يوثق هذا الدليل إعداد ونشر منصة **وكلاء أساس (ASAAS Agents Platform)** على خادم إنتاج مستقل (Single-Server Setup) بنظام Linux، محمي خلف خادم عكسي (NGINX أو Caddy) مع تفعيل تشفير HTTPS الصارم، وإدارة العمليات عبر systemd، وعزل عمليات الوكلاء بحساب غير ممتلك للصلاحيات (`asaas-worker`).

---

## 1. متطلبات الخادم الأساسية (System Requirements)
- **نظام التشغيل:** Ubuntu 22.04 LTS أو Debian 12
- **الموارد الموصى بها:** 2 vCPU، 4GB RAM، 20GB SSD
- **حزم النظام الإلزامية:** Python 3.11+, Node.js 20 LTS, NGINX / Caddy, SQLite3

---

## 2. إنشاء المستخدمين وعزل الصلاحيات (User Privileges & D3 Isolation)

تطبيقاً للقرار المعماري **D3**، تُشغل عمليات المنصة بحسابين منفصلين تماماً:

```bash
# 1. حساب خدمة المنصة لتشغيل الواجهة الخلفية
sudo useradd -r -s /bin/false -d /opt/asaas-platform asaas-app

# 2. حساب معزول تماماً ومقيد الصلاحيات لتشغيل عمليات الوكلاء (Agent Subprocesses)
sudo useradd -r -s /bin/false -M asaas-worker

# 3. إعداد مجلدات النظام وحماية الأسرار وقاعدة البيانات (DAC 0700/0600)
sudo mkdir -p /opt/asaas-platform /var/log/asaas
sudo chown -R asaas-app:asaas-app /opt/asaas-platform /var/log/asaas
sudo chmod 700 /opt/asaas-platform/api/data
sudo chmod 600 /opt/asaas-platform/api/.env 2>/dev/null || true

# 4. إعداد جدار حماية الحزم (nftables) لعزل شبكة الوكلاء ومنع أي اتصال خارجي
sudo nft add table inet asaas_filter
sudo nft add chain inet asaas_filter output '{ type filter hook output priority 0; policy accept; }'
# السماح للوكيل بالاتصال حصراً بالمنفذ المحلي للنماذج (8088)
sudo nft add rule inet asaas_filter output meta skuid asaas-worker ip daddr 127.0.0.1 tcp dport 8088 accept
# حظر أي اتصال خارجي أو محلي آخر لعامل الوكيل
sudo nft add rule inet asaas_filter output meta skuid asaas-worker reject
```

### 2.2 إعداد عزل وكلاء الخدمات (Tier-2 Service Agents — Site DNA)

لخدمات الوكلاء طويلة الأمد مثل Site DNA التي تتطلب زحفاً للمواقع الخارجية، يتم إنشاء مستخدم مستقل `asaas-service-sitedna` مع تطبيق قواعد `nftables` وسياسات cgroups:

```bash
# تنفيذ السكربت الجاهز لإعداد المستخدم، قواعد الشبكة، وحدود الموارد
sudo chmod +x scripts/setup_service_sandbox.sh
sudo ./scripts/setup_service_sandbox.sh
```

- **حدود الموارد (Resource Limits):** `MemoryMax=2G`, `CPUQuota=200%`, `TasksMax=64`.
- **جدار الحماية (Egress Filtering):** السماح بالاتصال الخارجي بـ HTTP/HTTPS فقط، حظر الشبكات الخاصة (RFC 1918) وميتاداتا السحابة (`169.254.169.254`)، والسماح بالاتصال المحلي حصراً ببوابة النماذج على المنفذ `8088`.

---

## 3. بناء ونشر الواجهة الأمامية (Building Front End)

```bash
cd /opt/asaas-platform/web
npm ci
npm run build
# ستكون مخرجات الإنتاج داخل مجلد /opt/asaas-platform/web/dist
```

---

## 4. إعداد خادم التطبيق الخلفي كخدمة Systemd

أنشئ الملف `/etc/systemd/system/asaas-api.service`:

```ini
[Unit]
Description=ASAAS Agents Platform API Service
After=network.target

[Service]
Type=simple
User=asaas-app
Group=asaas-app
WorkingDirectory=/opt/asaas-platform/api
Environment="PATH=/opt/asaas-platform/api/.venv/bin"
Environment="APP_ENV=production"
Environment="HOST=127.0.0.1"
Environment="PORT=8088"
Environment="TRUSTED_PROXIES=[\"127.0.0.1\"]"
ExecStart=/opt/asaas-platform/api/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8088 --workers 1 --proxy-headers
Restart=always
RestartSec=3
LimitNOFILE=65535

# ضوابط الحماية والأمان في Systemd
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/asaas-platform/api/data /var/log/asaas /tmp
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

> [!IMPORTANT]
> **اعتماد عامل تشغيل واحد حصراً (`--workers 1`):**
> تعتمد بنية المنصة الحالية في مرحلة MVP على إدارة الحالة في الذاكرة الحية (In-Process Memory) عمداً؛ ويشمل ذلك سجل رموز التشغيل المؤقتة (`run_token_registry`)، ومحدد معدل الطلبات حسب الـ IP، وإدارة التزامن والإلغاء، وذلك لضمان انعدام حفظ المفاتيح نهائياً على الأقراص (القرار المعماري D1). تشغيل خادم Uvicorn بأكثر من عامل واحد (`--workers > 1`) يؤدي إلى عزل الذاكرة بين العمليات، مما يتسبب في فشل استدعاءات الوكلاء لنقطة النماذج المحلية بخطأ 401 Unauthorized، ومضاعفة حدود الـ Rate Limit بعدد العمال، وفقدان أحداث الإلغاء. التوسع الأفقي لعدة عمال مدرج لما بعد مرحلة MVP عبر نقل سجلات الذاكرة إلى مخزن موزع مشترك (مثل Redis أو Dragonfly).

تفعيل وتشغيل الخدمة:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now asaas-api
sudo systemctl status asaas-api
```

---

## 5. تكوين الخادم العكسي (Reverse Proxy & HTTPS)

### الخيار أ: التكوين باستخدام NGINX مع شهادة Let's Encrypt

أنشئ الملف `/etc/nginx/sites-available/agents.asaas.ai`:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name agents.asaas.ai;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name agents.asaas.ai;

    ssl_certificate /etc/letsencrypt/live/agents.asaas.ai/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/agents.asaas.ai/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # ترويسات الأمان الصارمة
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # الحد الأقصى لحجم حمولة الطلب (مطابق لسياسة المنصة 5MB)
    client_max_body_size 5M;

    # تقديم ملفات الواجهة الأمامية الساكنة
    root /opt/asaas-platform/web/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # حظر الوصول الخارجي لنقطة اتصال النماذج الداخلية بالكامل (Internal Proxy Only)
    location /v1/ {
        return 404;
    }

    # توجيه طلبات الواجهة الخلفية
    location /api/ {
        proxy_pass http://127.0.0.1:8088;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # دعم البث الحي للأحداث (SSE / Streaming)
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }

    # توجيه واجهة تطبيقات وكلاء الخدمات (مثل Site DNA تحت /agents/site-dna/app/)
    location /agents/site-dna/app/ {
        proxy_pass http://127.0.0.1:8088;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # توجيه البوابة العكسية المقيّدة لوكلاء الخدمات (SSE + تقارير)
    location /agents-api/ {
        proxy_pass http://127.0.0.1:8088;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 1260s;
    }
}
```

---

## 5ب. عزل وتشغيل وكلاء الخدمات طويلي الأمد على Linux (Tier-2: Site DNA)

يتطلب وكيل **Site DNA** تشغيلاً معزولاً على مضيف Linux باستخدام السكربت المرفق [`scripts/setup_service_sandbox.sh`](file:///C:/Users/mahmoodSaeed/Desktop/asaas_skills/skills-main/skills-main/scripts/setup_service_sandbox.sh):

```bash
sudo bash scripts/setup_service_sandbox.sh
```

يطبق السكربت الضوابط التالية على مستوى النواة والنظام:
1. **مستخدم نظام مخصص غير مميّز (`asaas-service-sitedna`)**: منفصل عن `asaas-api` وعن `asaas-worker`، مع دليل بيانات مخصص `/var/lib/asaas-agents/site-dna/runs` ومجلد متصفح مستقل `PLAYWRIGHT_BROWSERS_PATH`.
2. **قواعد جدار الحماية (`nftables` per-UID egress)**:
   - يسمح بالاتصالات القائمة (`ct state established,related`) وبـ DNS المحلي (`127.0.0.53:53`) وببوابة النماذج المحلية فقط (`127.0.0.1:8088`).
   - يحظر جميع شبكات `127.0.0.0/8` الأخرى وRFC 1918 (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) وCGNAT (`100.64.0.0/10`) وLink-Local/Cloud Metadata (`169.254.0.0/16`) ونطاقات IPv6 الخاصة (`::1`, `fc00::/7`, `fe80::/10`, `::ffff:0:0/96`).
   - يسمح فقط بالخروج العام عبر TCP 80 وTCP 443.
3. **حدود الموارد (systemd cgroups v2)**:
   - `MemoryMax=2G`, `MemoryHigh=1536M`, `CPUQuota=200%`, `TasksMax=96`, `NoNewPrivileges=true`, `ProtectSystem=strict`, `PrivateTmp=true`.
   - تثبيت عامل واحد فقط (`--workers 1`) لكل من المنصة ووكيل Site DNA.
4. **أمر التحقق من الإعتماديات والمزامنة:**
   ```bash
   python scripts/sync_agents.py --slug site-dna
   ```

> [!WARNING]
> لم تُختبر قواعد `nftables` و`systemd cgroups` وعزل `asaas-service-sitedna` على مضيف Linux فعلي بعد (بيئة التطوير الحالية Windows). تبقى توصية الإطلاق **HOLD** حتى تنفيذ اختبارات Linux الفعلية.

---

## 6. قائمة التحقق قبل إطلاق الإنتاج (Pre-Flight Checklist)

- [x] شهادة SSL مفعلة مع بروتوكول TLS 1.3 وترويسة HSTS (موثقة في إعدادات NGINX).
- [x] `TRUSTED_PROXIES` مضبوطة على عنوان البروكسي الداخلي فقط لمنع تزوير عناوين IP الزوار.
- [x] حدود تحديد المعدل وتزامن Site DNA (2 عام / 1 لكل IP / 3 يومياً) مفعلة وموثقة للتعديل بعد أسبوع.
- [x] تشغيل اختبارات الأمان والتكامل على Windows بنجاح (بما في ذلك تشغيل Site DNA الفعلي مع Chromium).
- [ ] **معلّق (مانع إطلاق):** التحقق الفعلي من عزل نواة Linux (`nftables`, `asaas-worker`, `asaas-service-sitedna`, `cgroups v2`, `setrlimit`) على مضيف Linux.
- [ ] **معلّق:** اعتماد المسودات القانونية (`/privacy` و `/terms`) من الإدارة القانونية لأساس.
