import { Card, Swash } from '../asaas-ui';
import { t } from '../content';
import { usePageMeta } from '../lib/usePageMeta';

export default function About() {
  usePageMeta({
    title: `${t('about.title')} — ${t('site.name')}`,
    description: t('about.desc'),
  });

  return (
    <div className="page-about" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gutter, 20px)' }}>
      <Card style={{ padding: '24px' }}>
        <h1 className="title" style={{ margin: '0 0 16px 0', fontSize: '24px' }}>
          {t('about.title')}
          <Swash>.</Swash>
        </h1>
        <p className="prose" style={{ lineHeight: 1.7, color: 'var(--text-2)', marginBottom: '24px' }}>
          {t('about.desc')}
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '16px' }}>
          <div
            style={{
              padding: '16px',
              borderRadius: 'var(--radius-md)',
              background: 'var(--glass-tint)',
              border: '1px solid var(--hairline)',
            }}
          >
            <h3 style={{ margin: '0 0 8px 0', fontSize: '16px', color: 'var(--text)' }}>
              {t('about.feature_byok_title')}
            </h3>
            <p style={{ margin: 0, fontSize: '14px', color: 'var(--text-2)', lineHeight: 1.5 }}>
              {t('about.feature_byok_desc')}
            </p>
          </div>

          <div
            style={{
              padding: '16px',
              borderRadius: 'var(--radius-md)',
              background: 'var(--glass-tint)',
              border: '1px solid var(--hairline)',
            }}
          >
            <h3 style={{ margin: '0 0 8px 0', fontSize: '16px', color: 'var(--text)' }}>
              {t('about.feature_isolation_title')}
            </h3>
            <p style={{ margin: 0, fontSize: '14px', color: 'var(--text-2)', lineHeight: 1.5 }}>
              {t('about.feature_isolation_desc')}
            </p>
          </div>
        </div>
      </Card>
    </div>
  );
}
