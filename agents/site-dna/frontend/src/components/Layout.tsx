import React, { useEffect, useState } from 'react';
import { NavLink, Outlet, Link } from 'react-router-dom';
import { useLang } from '../lib/i18n';
import { useTheme } from '../asaas-ui/lib/useTheme';
import {
  api,
  PLATFORM_RETURN_URL,
  type PlatformSessionInfo,
  type PlatformSessionUsage,
} from '../lib/api';
import {
  LayoutDashboard,
  PlusCircle,
  History,
  Settings,
  Sun,
  Moon,
  Languages,
  Menu,
  X,
  ArrowRight,
  Activity,
  AlertTriangle,
} from 'lucide-react';

export function Layout() {
  const { lang, toggleLang, t } = useLang();
  const [theme, toggleTheme] = useTheme();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [session, setSession] = useState<PlatformSessionInfo | null>(null);
  const [usage, setUsage] = useState<PlatformSessionUsage | null>(null);
  const [sessionMissing, setSessionMissing] = useState(false);

  useEffect(() => {
    let active = true;
    const loadSession = () => {
      api
        .getSessionMe()
        .then((info) => {
          if (!active) return;
          setSession(info);
          setSessionMissing(!info.active);
        })
        .catch((err) => {
          if (!active) return;
          if (err?.status === 401) {
            setSessionMissing(true);
          }
        });
      api
        .getSessionUsage()
        .then((u) => {
          if (active) setUsage(u);
        })
        .catch(() => {});
    };

    loadSession();
    const timer = setInterval(loadSession, 15000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!mobileMenuOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMobileMenuOpen(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [mobileMenuOpen]);

  const navLinks = [
    { to: '/', labelKey: 'nav.dashboard', icon: LayoutDashboard },
    { to: '/analyses/new', labelKey: 'nav.new_analysis', icon: PlusCircle },
    { to: '/history', labelKey: 'nav.history', icon: History },
    { to: '/settings', labelKey: 'nav.settings', icon: Settings },
  ];

  const totalTokens = (usage?.input_tokens || 0) + (usage?.output_tokens || 0);

  return (
    <div className="min-h-screen w-full overflow-x-hidden flex flex-col relative">
      {/* ASAAS Floating Liquid-Glass Pill Header */}
      <header className="sticky top-0 z-40 pt-3 pb-1 px-3 sm:px-6">
        <div className="max-w-7xl mx-auto relative">
          <div className="glass glass--thick glass--pill min-h-[60px] px-4 sm:px-5 flex items-center justify-between gap-2 sm:gap-4">
            {/* Brand: ASAAS Mark + Site DNA */}
            <Link
              to="/"
              className="flex items-center gap-2.5 group no-underline min-w-0 shrink-0"
              style={{ textDecoration: 'none' }}
            >
              <span
                className="brand__mark shrink-0"
                style={{ width: '32px', height: '38px' }}
                aria-hidden="true"
              />
              <div className="min-w-0 flex flex-col">
                <span
                  className="font-bold text-base sm:text-[18px] leading-tight text-[var(--text)] truncate"
                  style={{ fontFamily: 'var(--font-display)' }}
                >
                  {lang === 'ar' ? 'بصمة الموقع' : 'Site DNA'}
                </span>
                <span className="text-[11px] leading-tight text-[var(--accent)] font-medium truncate hidden sm:block">
                  {lang === 'ar' ? 'وكلاء أساس • Site DNA' : 'ASAAS Agents'}
                </span>
              </div>
            </Link>

            {/* Desktop Navigation Links (ASAAS Pill Style) */}
            <nav
              className="hidden lg:flex items-center gap-1 mx-auto"
              aria-label={lang === 'ar' ? 'التنقل الرئيسي' : 'Main Navigation'}
            >
              {navLinks.map((item) => {
                const IconComp = item.icon;
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === '/'}
                    className={({ isActive }) =>
                      `inline-flex items-center gap-2 min-h-[40px] px-3.5 rounded-full text-sm font-semibold transition-all duration-200 ${
                        isActive
                          ? 'bg-[var(--glass-inset)] text-[var(--text)] shadow-[inset_0_0_0_1px_var(--hairline)]'
                          : 'text-[var(--text-2)] hover:text-[var(--text)] hover:bg-[var(--glass-inset)]'
                      }`
                    }
                  >
                    <IconComp className="w-4 h-4 text-[var(--accent)]" />
                    <span>{t(item.labelKey)}</span>
                  </NavLink>
                );
              })}
            </nav>

            {/* Right Actions: Return to ASAAS, Lang, Theme, Mobile Menu */}
            <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
              <a
                href={PLATFORM_RETURN_URL}
                className="hidden sm:inline-flex items-center gap-1.5 min-h-[38px] px-3.5 rounded-full text-xs font-semibold text-[var(--text-2)] hover:text-[var(--text)] hover:bg-[var(--glass-inset)] transition-colors whitespace-nowrap"
                title={lang === 'ar' ? 'العودة إلى منصة وكلاء أساس' : 'Back to ASAAS Platform'}
              >
                <ArrowRight className="w-3.5 h-3.5 text-[var(--accent)]" />
                <span>{lang === 'ar' ? 'وكلاء أساس' : 'ASAAS'}</span>
              </a>

              <button
                type="button"
                onClick={toggleLang}
                className="inline-flex items-center justify-center gap-1 min-h-[38px] px-2.5 sm:px-3 rounded-full text-xs font-semibold text-[var(--text-2)] hover:text-[var(--text)] hover:bg-[var(--glass-inset)] transition-colors cursor-pointer"
                title="Toggle Language / تبديل اللغة"
              >
                <Languages className="w-3.5 h-3.5" />
                <span>{lang === 'ar' ? 'EN' : 'عربي'}</span>
              </button>

              <button
                type="button"
                onClick={toggleTheme}
                className="w-[38px] h-[38px] rounded-full inline-flex items-center justify-center text-[var(--text-2)] hover:text-[var(--text)] hover:bg-[var(--glass-inset)] transition-colors cursor-pointer"
                title={lang === 'ar' ? 'تبديل المظهر' : 'Toggle Theme'}
                aria-label="Toggle theme"
              >
                {theme === 'dark' ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4" />}
              </button>

              <button
                type="button"
                onClick={() => setMobileMenuOpen((v) => !v)}
                className="lg:hidden w-[38px] h-[38px] rounded-full inline-flex items-center justify-center text-[var(--text)] hover:bg-[var(--glass-inset)] transition-colors cursor-pointer"
                aria-label="Toggle Navigation Menu"
                aria-expanded={mobileMenuOpen}
              >
                {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
              </button>
            </div>
          </div>

          {/* Mobile / Tablet Floating Glass Dropdown Panel */}
          {mobileMenuOpen && (
            <>
              <div
                className="fixed inset-0 z-[-1] bg-black/20 lg:hidden"
                aria-hidden="true"
                onClick={() => setMobileMenuOpen(false)}
              />
              <div
                className="lg:hidden absolute top-[calc(100%+10px)] inset-x-0 z-50 rounded-2xl p-2.5 space-y-1 border border-[var(--hairline)] shadow-xl"
                style={{
                  backgroundColor: 'var(--bg)',
                  backgroundImage: 'linear-gradient(165deg, var(--glass-tint-strong), transparent 70%)',
                }}
              >
                {navLinks.map((item) => {
                  const IconComp = item.icon;
                  return (
                    <NavLink
                      key={item.to}
                      to={item.to}
                      end={item.to === '/'}
                      onClick={() => setMobileMenuOpen(false)}
                      className={({ isActive }) =>
                        `flex items-center gap-3 min-h-[46px] px-4 rounded-xl text-sm font-semibold transition-colors ${
                          isActive
                            ? 'bg-[var(--glass-inset)] text-[var(--text)]'
                            : 'text-[var(--text-2)] hover:text-[var(--text)] hover:bg-[var(--glass-inset)]'
                        }`
                      }
                    >
                      <IconComp className="w-4 h-4 text-[var(--accent)]" />
                      <span>{t(item.labelKey)}</span>
                    </NavLink>
                  );
                })}
                <div className="pt-1 mt-1 border-t border-[var(--hairline)]">
                  <a
                    href={PLATFORM_RETURN_URL}
                    className="flex items-center gap-3 min-h-[46px] px-4 rounded-xl text-sm font-semibold text-[var(--accent)] hover:bg-[var(--glass-inset)]"
                  >
                    <ArrowRight className="w-4 h-4" />
                    <span>{lang === 'ar' ? 'العودة إلى وكلاء أساس' : 'Back to ASAAS Agents'}</span>
                  </a>
                </div>
              </div>
            </>
          )}
        </div>
      </header>

      {/* Subtle Session & Model Context Chips (floating cleanly below header) */}
      {(session?.active || sessionMissing) && (
        <div className="max-w-7xl w-full mx-auto px-3 sm:px-6 pt-2">
          <div className="flex flex-wrap items-center justify-end gap-2 text-[11px] text-[var(--text-2)]">
            {session?.active ? (
              <>
                <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[var(--glass-tint)] border border-[var(--hairline)] font-mono max-w-[240px] truncate shadow-xs">
                  <Activity className="w-3 h-3 text-emerald-600 shrink-0" />
                  <span className="truncate">
                    {session.provider} / {session.model}
                  </span>
                </span>
                <span
                  className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[var(--glass-tint)] border border-[var(--hairline)] font-mono shadow-xs"
                  title="استهلاك الجلسة الحالية عبر مفتاحك"
                >
                  <span>{usage?.requests ?? 0} طلب</span>
                  <span className="opacity-40">•</span>
                  <span>{totalTokens.toLocaleString()} رمز</span>
                </span>
              </>
            ) : (
              <a
                href={PLATFORM_RETURN_URL}
                className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-amber-500/15 border border-amber-500/30 text-amber-800 dark:text-amber-300 font-semibold"
              >
                <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                <span>الجلسة غير مفعّلة — أعد إدخال المفتاح في المنصة</span>
              </a>
            )}
          </div>
        </div>
      )}

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-3 sm:px-6 lg:px-8 py-4 sm:py-6 space-y-6 sm:space-y-8">
        <Outlet />
      </main>

      {/* Footer (matching ASAAS Platform Footer) */}
      <footer className="mt-auto border-t border-[var(--hairline)] py-6 text-xs text-[var(--text-2)]">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-3">
          <span>
            © 2026 {lang === 'ar' ? 'بصمة الموقع — منصة وكلاء أساس AI' : 'Site DNA — ASAAS AI Agents Platform'}
          </span>
          <div className="flex flex-wrap items-center justify-center gap-3">
            <a href={PLATFORM_RETURN_URL} className="hover:text-[var(--text)] transition-colors">
              {lang === 'ar' ? 'وكلاء أساس' : 'ASAAS Platform'}
            </a>
            <span className="opacity-40">•</span>
            <a href="/privacy" className="hover:text-[var(--text)] transition-colors">
              {lang === 'ar' ? 'سياسة الخصوصية' : 'Privacy Policy'}
            </a>
            <span className="opacity-40">•</span>
            <a href="/terms" className="hover:text-[var(--text)] transition-colors">
              {lang === 'ar' ? 'شروط الاستخدام' : 'Terms of Use'}
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
