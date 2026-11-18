import { NavLink, Outlet, Link } from 'react-router-dom';
import { SiteHeader } from '../asaas-ui';
import { ThemeToggle } from './ThemeToggle';
import { t } from '../content';

const NAV_ITEMS = [
  { to: '/', key: 'nav.home' },
  { to: '/about', key: 'nav.about' },
] as const;

export function Layout() {
  return (
    <div className="site-layout">
      <SiteHeader
        brand={
          <Link to="/" className="brand">
            <span className="brand__mark" />
            <span className="brand__text">{t('site.name')}</span>
          </Link>
        }
        nav={
          <>
            {NAV_ITEMS.map((item) => (
              <NavLink key={item.to} to={item.to} end>
                {t(item.key)}
              </NavLink>
            ))}
          </>
        }
        actions={<ThemeToggle />}
      />
      <main className="container" style={{ paddingBlock: 'var(--gutter, 20px)' }}>
        <Outlet />
      </main>
      <footer className="site-footer container">
        <div className="site-footer__inner">
          <span className="site-footer__copy">
            © {new Date().getFullYear()} {t('site.name')} — منصة استعراض وكلاء أساس AI
          </span>
          <nav className="site-footer__nav" aria-label="روابط قانونية ومعلوماتية">
            <Link to="/about">{t('nav.about')}</Link>
            <span className="dot-sep" aria-hidden="true">•</span>
            <Link to="/privacy">{t('footer.privacy')}</Link>
            <span className="dot-sep" aria-hidden="true">•</span>
            <Link to="/terms">{t('footer.terms')}</Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
