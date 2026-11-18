import { Link } from 'react-router-dom';
import { Card, Button } from '../asaas-ui';
import { t } from '../content';
import { usePageMeta } from '../lib/usePageMeta';

export default function NotFound() {
  usePageMeta({
    title: `${t('not_found.title')} — ${t('site.name')}`,
    description: t('not_found.desc'),
  });

  return (
    <Card style={{ padding: '36px 20px', textAlign: 'center' }}>
      <h1 className="title" style={{ fontSize: '28px', margin: '0 0 12px 0' }}>
        {t('not_found.title')}
      </h1>
      <p style={{ color: 'var(--text-2)', maxWidth: '420px', margin: '0 auto 24px auto', lineHeight: 1.6 }}>
        {t('not_found.desc')}
      </p>
      <Link to="/" style={{ textDecoration: 'none' }}>
        <Button variant="primary">
          {t('action.back_home')}
        </Button>
      </Link>
    </Card>
  );
}
