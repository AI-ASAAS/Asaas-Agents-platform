import React, { useEffect, useState } from 'react';
import { useLang } from '../lib/i18n';
import { useTheme } from '../asaas-ui/lib/useTheme';
import { api, PLATFORM_RETURN_URL, type PlatformSessionInfo } from '../lib/api';
import {
  Settings as SettingsIcon,
  Cpu,
  Languages,
  Moon,
  Sun,
  Server,
  Key,
  ArrowRight,
} from 'lucide-react';

export function Settings() {
  const { lang, setLang, t } = useLang();
  const [theme, toggleTheme] = useTheme();
  const [healthStatus, setHealthStatus] = useState<string>('checking...');
  const [session, setSession] = useState<PlatformSessionInfo | null>(null);

  useEffect(() => {
    api
      .getHealth()
      .then((data) => setHealthStatus(data.status || 'healthy'))
      .catch(() => setHealthStatus('disconnected'));

    api
      .getSessionMe()
      .then(setSession)
      .catch(() => setSession({ active: false }));
  }, []);

  const ttlMinutes =
    session?.ttl_remaining_seconds !== undefined
      ? Math.max(0, Math.round(session.ttl_remaining_seconds / 60))
      : null;

  return (
    <div className="max-w-4xl mx-auto space-y-8 animate-in fade-in duration-300">
      {/* Header */}
      <div className="space-y-1 border-b border-[var(--hairline)] pb-5">
        <div className="asaas-eyebrow">
          <SettingsIcon className="w-3.5 h-3.5" />
          <span>تفضيلات العرض وحالة جلسة المنصة (للقراءة فقط)</span>
        </div>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-[var(--text)] tracking-tight">
          {t('settings.title')}
        </h1>
        <p className="text-sm text-[var(--text-2)]">{t('settings.subtitle')}</p>
      </div>

      <div className="space-y-6">
        {/* Read-Only Platform Session & Model Info */}
        <div className="p-5 sm:p-6 rounded-3xl border border-[var(--hairline)] bg-[var(--glass-tint)] backdrop-blur-md space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-2xl bg-stone-900/10 text-stone-900 dark:bg-stone-100/10 dark:text-stone-100 border border-stone-800/20 flex items-center justify-center shrink-0">
                <Cpu className="w-5 h-5" />
              </div>
              <div className="min-w-0">
                <h2 className="text-base font-bold text-[var(--text)]">مزوّد الذكاء الاصطناعي والنموذج النشط</h2>
                <span className="font-mono text-xs font-bold text-[var(--accent)] break-all">
                  {session?.active
                    ? `${session.provider} / ${session.model}`
                    : 'لا توجد جلسة نشطة حالياً'}
                </span>
              </div>
            </div>

            <a
              href={PLATFORM_RETURN_URL}
              className="asaas-btn-primary py-2.5 px-4 text-xs shrink-0"
            >
              <Key className="w-3.5 h-3.5" />
              <span>تغيير المزوّد أو المفتاح في المنصة</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </a>
          </div>

          <p className="text-xs text-[var(--text-2)] leading-relaxed">
            يُدار مفتاح API الخاص بك بالكامل داخل ذاكرة بوابة منصة أساس (HttpOnly Cookie)، ولا يُرسل أبداً إلى المتصفح أو إلى عملية الوكيل. لتغيير المفتاح أو اختيار نموذج آخر، استخدم صفحة إعداد الوكيل في المنصة.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
            <div className="p-3 rounded-xl bg-[var(--bg)] border border-[var(--hairline)] space-y-1">
              <span className="text-[var(--text-3)] block">حالة الجلسة:</span>
              <span
                className={`font-mono font-bold ${
                  session?.active
                    ? 'text-emerald-700 dark:text-emerald-400'
                    : 'text-amber-700 dark:text-amber-400'
                }`}
              >
                {session?.active ? 'نشطة (Active)' : 'غير مفعّلة'}
              </span>
            </div>
            <div className="p-3 rounded-xl bg-[var(--bg)] border border-[var(--hairline)] space-y-1">
              <span className="text-[var(--text-3)] block">المدة المتبقية للجلسة:</span>
              <span className="font-mono font-bold text-[var(--text)]">
                {ttlMinutes !== null ? `${ttlMinutes} دقيقة` : '—'}
              </span>
            </div>
            <div className="p-3 rounded-xl bg-[var(--bg)] border border-[var(--hairline)] space-y-1">
              <span className="text-[var(--text-3)] block">الاحتفاظ بالنتائج:</span>
              <span className="font-mono font-bold text-[var(--text)]">60 دقيقة بعد الانتهاء</span>
            </div>
          </div>
        </div>

        {/* Interface Preferences (Language & Theme) */}
        <div className="p-5 sm:p-6 rounded-3xl border border-[var(--hairline)] bg-[var(--glass-tint)] backdrop-blur-md space-y-5">
          <h2 className="text-base font-bold text-[var(--text)]">تخصيص الواجهة والعرض</h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="p-4 rounded-2xl bg-[var(--bg)] border border-[var(--hairline)] space-y-2.5">
              <div className="flex items-center gap-2 text-xs font-bold text-[var(--text)]">
                <Languages className="w-4 h-4 text-amber-500" />
                <span>{t('settings.lang_title')}</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={() => setLang('ar')}
                  className={`py-2 px-3 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                    lang === 'ar'
                      ? 'bg-[var(--accent-fill)] text-[var(--on-accent)] shadow-sm'
                      : 'border border-[var(--hairline)] text-[var(--text-2)]'
                  }`}
                >
                  العربية (RTL)
                </button>
                <button
                  onClick={() => setLang('en')}
                  className={`py-2 px-3 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                    lang === 'en'
                      ? 'bg-[var(--accent-fill)] text-[var(--on-accent)] shadow-sm'
                      : 'border border-[var(--hairline)] text-[var(--text-2)]'
                  }`}
                >
                  English (LTR)
                </button>
              </div>
            </div>

            <div className="p-4 rounded-2xl bg-[var(--bg)] border border-[var(--hairline)] space-y-2.5">
              <div className="flex items-center gap-2 text-xs font-bold text-[var(--text)]">
                {theme === 'dark' ? <Moon className="w-4 h-4 text-amber-400" /> : <Sun className="w-4 h-4 text-amber-500" />}
                <span>{t('settings.theme_title')}</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={() => { if (theme !== 'light') toggleTheme(); }}
                  className={`py-2 px-3 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                    theme === 'light'
                      ? 'bg-[var(--accent-fill)] text-[var(--on-accent)] shadow-sm'
                      : 'border border-[var(--hairline)] text-[var(--text-2)]'
                  }`}
                >
                  {t('settings.theme_light')}
                </button>
                <button
                  onClick={() => { if (theme !== 'dark') toggleTheme(); }}
                  className={`py-2 px-3 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                    theme === 'dark'
                      ? 'bg-[var(--accent-fill)] text-[var(--on-accent)] shadow-sm'
                      : 'border border-[var(--hairline)] text-[var(--text-2)]'
                  }`}
                >
                  {t('settings.theme_dark')}
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Backend Health */}
        <div className="p-5 sm:p-6 rounded-3xl border border-[var(--hairline)] bg-[var(--glass-tint)] backdrop-blur-md space-y-4">
          <div className="flex items-center gap-2.5">
            <Server className="w-4 h-4 text-amber-500" />
            <h2 className="text-base font-bold text-[var(--text)]">حالة خدمة الوكيل (Backend Health)</h2>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
            <div className="p-3 rounded-xl bg-[var(--bg)] border border-[var(--hairline)] space-y-1">
              <span className="text-[var(--text-3)] block">حالة الخدمة:</span>
              <span className="font-mono font-bold text-emerald-700 dark:text-emerald-400 uppercase">
                {healthStatus}
              </span>
            </div>
            <div className="p-3 rounded-xl bg-[var(--bg)] border border-[var(--hairline)] space-y-1">
              <span className="text-[var(--text-3)] block">بيئة المتصفح:</span>
              <span className="font-mono font-bold text-[var(--text)]">Playwright Chromium (Isolated)</span>
            </div>
            <div className="p-3 rounded-xl bg-[var(--bg)] border border-[var(--hairline)] space-y-1">
              <span className="text-[var(--text-3)] block">حد الصفحات:</span>
              <span className="font-mono font-bold text-[var(--text)]">8 صفحات كحد أقصى / جولة</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
