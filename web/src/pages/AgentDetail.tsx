import { Suspense, useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Card, ErrorState, Glass, Icon, Skeleton, Swash } from '../asaas-ui';
import { AgentIcon } from '../components/AgentIcon';
import { AgentStatusPill } from '../components/AgentStatusPill';
import { KeySetupFlow } from '../components/KeySetupFlow';
import { UsagePanel } from '../components/UsagePanel';
import { useLang } from '../content';
import { fetchAgentBySlug, recordAgentView, type AgentDetailItem } from '../lib/catalogApi';
import { safeHref } from '../lib/safeHref';
import { sessionKeyStore } from '../lib/sessionKeyStore';
import { usePageMeta } from '../lib/usePageMeta';
import { getAgentPlaygroundUI } from '../agent-ui';

const PROVIDER_NAMES: Record<string, string> = {
  gemini: 'Google AI Studio (Gemini)',
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  openrouter: 'OpenRouter',
};

export default function AgentDetail() {
  const { slug } = useParams<{ slug: string }>();
  const { t } = useLang();

  const [agent, setAgent] = useState<AgentDetailItem | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<unknown | null>(null);
  const [isAgentReady, setIsAgentReady] = useState<boolean>(false);
  const [creds, setCreds] = useState(() => sessionKeyStore.getCredentials());
  const [activeServiceSession, setActiveServiceSession] = useState<{ active: boolean; agent_slug?: string } | null>(null);
  const [isLaunchingHero, setIsLaunchingHero] = useState<boolean>(false);
  const [heroLaunchError, setHeroLaunchError] = useState<string | null>(null);

  useEffect(() => {
    return sessionKeyStore.subscribe(() => {
      const nextCreds = sessionKeyStore.getCredentials();
      setCreds(nextCreds);
      if (!nextCreds) {
        setActiveServiceSession(null);
      }
    });
  }, []);

  useEffect(() => {
    let active = true;
    fetch('/api/service-sessions/me', { credentials: 'same-origin' })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (active && data) setActiveServiceSession(data);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [slug]);

  usePageMeta({
    title: agent ? `${agent.name} — ${t('site.name')}` : t('site.name'),
    description: agent ? agent.summary : t('site.description'),
  });

  const loadAgent = useCallback(() => {
    if (!slug) return;
    setIsLoading(true);
    setError(null);
    fetchAgentBySlug(slug)
      .then((data) => {
        setAgent(data);
        setIsLoading(false);
        if (data && data.slug) {
          recordAgentView(data.slug);
        }
      })
      .catch((err) => {
        setError(err);
        setIsLoading(false);
      });
  }, [slug]);

  useEffect(() => {
    loadAgent();
  }, [loadAgent]);

  if (isLoading) {
    return (
      <div className="agent-detail">
        <Skeleton height={260} count={2} />
      </div>
    );
  }

  if (error || !agent) {
    return (
      <div className="agent-detail">
        <Link to="/" className="agent-detail__back">
          <Icon name="chevronRight" />
          <span>{t('agent.back_to_catalog')}</span>
        </Link>
        <ErrorState error={error || new Error(t('not_found.title'))} onRetry={loadAgent} />
      </div>
    );
  }

  const isReady = agent.status === 'ready';
  const disabledExplanation =
    agent.status === 'coming_soon'
      ? t('agent.demo_disabled_coming_soon')
      : t('agent.demo_disabled_github_only');

  const isStandaloneService = agent.playground_mode === 'standalone' || agent.slug === 'site-dna';
  const hasReadyCreds = !!(creds?.key && creds?.model);
  const hasActiveServerSession = !!(activeServiceSession?.active && activeServiceSession.agent_slug === agent.slug);

  const launchStandaloneApp = async () => {
    setIsLaunchingHero(true);
    setHeroLaunchError(null);
    try {
      const latestCreds = sessionKeyStore.getCredentials();
      if (latestCreds?.key && latestCreds?.model) {
        const res = await fetch('/api/service-sessions/init', {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/json',
            'X-Provider-Key': latestCreds.key,
          },
          body: JSON.stringify({
            agent_slug: agent.slug,
            provider: latestCreds.provider,
            model: latestCreds.model,
          }),
        });
        if (!res.ok) {
          const errJson = await res.json().catch(() => ({}));
          const msg =
            typeof errJson.detail === 'object' && errJson.detail !== null
              ? errJson.detail.message
              : errJson.detail;
          throw new Error(msg || 'تعذر بدء جلسة الوكيل');
        }
        window.location.href = `/agents/${agent.slug}/app/`;
        return;
      }
      if (hasActiveServerSession) {
        window.location.href = `/agents/${agent.slug}/app/`;
        return;
      }
      const el = document.getElementById('playground-section');
      if (el) el.scrollIntoView({ behavior: 'smooth' });
      setIsLaunchingHero(false);
    } catch (err: any) {
      setHeroLaunchError(err.message || 'حدث خطأ أثناء فتح الوكيل');
      setIsLaunchingHero(false);
      const el = document.getElementById('playground-section');
      if (el) el.scrollIntoView({ behavior: 'smooth' });
    }
  };

  const handleHeroDemoClick = () => {
    if (isStandaloneService && (hasReadyCreds || hasActiveServerSession)) {
      void launchStandaloneApp();
      return;
    }
    const el = document.getElementById('playground-section');
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' });
    }
  };

  return (
    <div className="agent-detail">
      {/* Navigation Breadcrumb */}
      <Link to="/" className="agent-detail__back">
        <Icon name="chevronRight" />
        <span>{t('agent.back_to_catalog')}</span>
      </Link>

      {/* Hero Overview Card */}
      <Glass as="article" className="card agent-detail__hero">
        <div className="agent-detail__hero-header">
          <div className="agent-detail__brand">
            <div className="agent-detail__icon-box">
              <AgentIcon name={agent.icon} />
            </div>
            <div className="agent-detail__hero-titles">
              <h1 className="title">
                {agent.name}
                <Swash>!</Swash>
              </h1>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <AgentStatusPill status={agent.status} />
              </div>
            </div>
          </div>

          <div className="agent-detail__actions">
            {isReady ? (
              <button
                type="button"
                className="btn btn--primary"
                onClick={handleHeroDemoClick}
                disabled={isLaunchingHero}
              >
                <Icon name={isLaunchingHero ? 'clock' : 'sparkle'} />
                <span>{isLaunchingHero ? 'جاري فتح الوكيل...' : t('agent.demo_button')}</span>
              </button>
            ) : (
              <button
                type="button"
                className="btn btn--glass"
                disabled
                title={disabledExplanation}
                aria-label={`${t('agent.demo_button')}: ${disabledExplanation}`}
              >
                <Icon name="sparkle" />
                <span>{t('agent.demo_button')}</span>
              </button>
            )}

            <a
              href={safeHref(agent.github_url)}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn--glass"
            >
              <Icon name="file" />
              <span>{t('agent.github_button')}</span>
            </a>
          </div>
        </div>

        <p className="lead" style={{ fontSize: '17px', color: 'var(--text-1)', lineHeight: 1.6, marginBottom: '14px' }}>
          {agent.summary}
        </p>

        <div className="agent-detail__long-desc prose">
          <p>{agent.description}</p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginTop: '16px', flexWrap: 'wrap' }}>
          <span className="subtle">{t('agent.pinned_ref')}:</span>
          <span className="pinned-badge">{agent.pinned_ref}</span>
        </div>

        {heroLaunchError && (
          <p className="byok-error-text" role="alert" style={{ marginTop: '12px' }}>
            {heroLaunchError}
          </p>
        )}
      </Glass>

      {/* Model Requirements Card */}
      <Card title={t('agent.model_reqs_title')} icon="dashboard">
        <p className="subtle" style={{ margin: '0 0 16px 0' }}>
          {t('agent.model_reqs_desc')}
        </p>

        <div className="reqs-grid">
          {/* Tool Calling */}
          <div className="req-item">
            <div className="req-item__icon">
              <Icon name={agent.model_requirements.tool_calling ? 'check' : 'close'} />
            </div>
            <div className="req-item__content">
              <span className="req-item__title">{t('agent.req_tool_calling')}</span>
              <span className="req-item__value">
                {agent.model_requirements.tool_calling ? t('common.yes') : t('common.no')}
              </span>
            </div>
          </div>

          {/* JSON Schema */}
          <div className="req-item">
            <div className="req-item__icon">
              <Icon name={agent.model_requirements.json_schema ? 'check' : 'close'} />
            </div>
            <div className="req-item__content">
              <span className="req-item__title">{t('agent.req_json_schema')}</span>
              <span className="req-item__value">
                {agent.model_requirements.json_schema ? t('common.yes') : t('common.no')}
              </span>
            </div>
          </div>

          {/* Vision */}
          <div className="req-item">
            <div className="req-item__icon">
              <Icon name={agent.model_requirements.vision ? 'check' : 'close'} />
            </div>
            <div className="req-item__content">
              <span className="req-item__title">{t('agent.req_vision')}</span>
              <span className="req-item__value">
                {agent.model_requirements.vision ? t('common.yes') : t('common.no')}
              </span>
            </div>
          </div>

          {/* Minimum Context */}
          {typeof agent.model_requirements.min_context_tokens === 'number' && (
            <div className="req-item">
              <div className="req-item__icon">
                <Icon name="clock" />
              </div>
              <div className="req-item__content">
                <span className="req-item__title">{t('agent.req_min_context')}</span>
                <span className="req-item__value num">
                  {t('agent.req_tokens', { count: agent.model_requirements.min_context_tokens.toLocaleString('en-US') })}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Supported Providers */}
        {agent.allowed_providers.length > 0 && (
          <div style={{ marginTop: '24px' }}>
            <span className="subtle" style={{ display: 'block', marginBottom: '8px', fontWeight: 600 }}>
              {t('agent.allowed_providers')}:
            </span>
            <div className="providers-list">
              {agent.allowed_providers.map((p) => (
                <span key={p} className="provider-tag">
                  <Icon name="sparkle" />
                  <span>{PROVIDER_NAMES[p] || p}</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </Card>

      {/* Usage Monitoring Panel */}
      <UsagePanel />

      {/* Interactive Key & Provider Setup Flow (only for ready agents) */}
      {isReady ? (
        <div id="playground-section" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <KeySetupFlow
            agentSlug={agent.slug}
            allowedProviders={agent.allowed_providers}
            onReady={setIsAgentReady}
          />

          {isAgentReady && (() => {
            if (agent.playground_mode === 'standalone' || agent.slug === 'site-dna') {
              return <ServiceAgentLauncher agent={agent} />;
            }
            const PlaygroundComponent = getAgentPlaygroundUI(agent.playground_ui) || getAgentPlaygroundUI(agent.slug);
            if (!PlaygroundComponent) return null;
            return (
              <Suspense fallback={<Skeleton height={200} />}>
                <PlaygroundComponent />
              </Suspense>
            );
          })()}
        </div>
      ) : (
        <Card title={t('agent.demo_button')} icon="clock">
          <p className="subtle" style={{ margin: 0 }}>
            {disabledExplanation}
          </p>
        </Card>
      )}
    </div>
  );
}

function ServiceAgentLauncher({ agent }: { agent: AgentDetailItem }) {
  const [isLaunching, setIsLaunching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creds, setCreds] = useState(() => sessionKeyStore.getCredentials());

  useEffect(() => {
    return sessionKeyStore.subscribe(() => {
      setCreds(sessionKeyStore.getCredentials());
    });
  }, []);

  const handleLaunch = async () => {
    setIsLaunching(true);
    setError(null);
    try {
      const latestCreds = sessionKeyStore.getCredentials();
      if (!latestCreds?.key) {
        throw new Error('يرجى التحقق من إدخال مفتاح API أولاً.');
      }
      if (!latestCreds.model) {
        throw new Error('يرجى اختيار النموذج الذكي أولاً.');
      }
      const res = await fetch('/api/service-sessions/init', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-Provider-Key': latestCreds.key,
        },
        body: JSON.stringify({
          agent_slug: agent.slug,
          provider: latestCreds.provider,
          model: latestCreds.model,
        }),
      });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        const msg =
          typeof errJson.detail === 'object' && errJson.detail !== null
            ? errJson.detail.message
            : errJson.detail;
        throw new Error(msg || 'تعذر بدء جلسة الوكيل');
      }
      // Redirect to mounted sub-app under /agents/<slug>/app/
      window.location.href = `/agents/${agent.slug}/app/`;
    } catch (err: any) {
      setError(err.message || 'حدث خطأ أثناء فتح الوكيل');
      setIsLaunching(false);
    }
  };

  const providerLabel = PROVIDER_NAMES[creds?.provider || ''] || creds?.provider || 'المزود المختار';
  const activeModel = creds?.model || 'النموذج الذي تختاره';

  return (
    <Card title={`تشغيل وتجربة ${agent.name}`} icon="sparkle" className="service-agent-launcher">
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {/* Short Arabic explanation */}
        <div
          style={{
            padding: '16px',
            borderRadius: '16px',
            background: 'var(--glass-tint)',
            border: '1px solid var(--hairline)',
            display: 'flex',
            flexDirection: 'column',
            gap: '12px',
            fontSize: '13px',
            lineHeight: '1.6',
          }}
        >
          <div>
            <strong style={{ color: 'var(--accent)' }}>ما الذي سيقوم به الوكيل في موقعك المستهدف؟</strong>
            <p style={{ margin: '4px 0 0 0', color: 'var(--text-1)' }}>
              يقوم وكيل <strong>{agent.name}</strong> بالزحف وقراءة صفحات HTML العامة للموقع المدخل (بحد أقصى 8 صفحات)، والتحقق من ملف <code>robots.txt</code> وخريطة الموقع، والتقاط لقطات شاشة لسطح المكتب والجوال عبر متصفح Chromium معزول. مرحلة مقارنة المنافسين معطّلة افتراضياً ولا تجلب مواقع خارجية أخرى إلا عند تفعيلها اختيارياً من قِبلك. تُحذف نتائج وتقارير الجولة تلقائياً بعد 60 دقيقة من الانتهاء.
            </p>
          </div>
          <div>
            <strong style={{ color: 'var(--accent)' }}>مزود الذكاء الاصطناعي واستهلاك الحصص (BYOK):</strong>
            <p style={{ margin: '4px 0 0 0', color: 'var(--text-1)' }}>
              يدعم الوكيل جميع المزودين والنماذج المتوافقة المتاحة عبر مفتاحك (مثل Gemini وOpenAI وAnthropic وOpenRouter). سيتم توجيه استدعاءات التحليل والرؤية المتعددة الوسائط في هذه الجلسة إلى اختيارك الحالي: <strong>{providerLabel}</strong> — النموذج <code dir="ltr">{activeModel}</code> عبر مفتاحك المصرح به. لا يتم تخزين مفتاحك على القرص نهائياً ويُحفظ حصرياً في الذاكرة المؤقتة لجلسة العمل الحالية.
            </p>
          </div>
        </div>

        {error && (
          <div
            style={{
              padding: '12px 16px',
              borderRadius: '12px',
              background: 'rgba(239, 68, 68, 0.1)',
              border: '1px solid rgba(239, 68, 68, 0.3)',
              color: '#dc2626',
              fontSize: '13px',
            }}
          >
            {error}
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '12px' }}>
          <button
            type="button"
            className="btn btn--primary"
            onClick={handleLaunch}
            disabled={isLaunching}
            style={{ minWidth: '220px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}
          >
            {isLaunching ? (
              <>
                <Icon name="clock" />
                <span>جاري فتح الوكيل...</span>
              </>
            ) : (
              <>
                <Icon name="sparkle" />
                <span>افتح تطبيق الوكيل ({agent.name})</span>
              </>
            )}
          </button>
        </div>
      </div>
    </Card>
  );
}
