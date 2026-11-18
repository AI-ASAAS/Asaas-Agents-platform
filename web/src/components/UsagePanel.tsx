import { useState } from 'react';
import { Glass, Icon } from '../asaas-ui';
import { useLang } from '../content';
import { useUsageTracker } from '../lib/useUsageTracker';

export function UsagePanel() {
  const { t } = useLang();
  const [collapsed, setCollapsed] = useState(false);
  const usage = useUsageTracker();

  // If no model and zero requests, panel stays compact
  if (usage.requests === 0 && !usage.currentModel && usage.connectionState === 'idle') {
    return null;
  }

  // Calculate estimated remaining requests if provider didn't emit headroom
  let estimatedRemainingReqs: number | null = null;
  if (usage.currentProvider && usage.baselineLimits) {
    const provLimits = usage.baselineLimits[usage.currentProvider];
    const defaultRpm = provLimits?.models?.[usage.currentModel]?.rpm ?? provLimits?.default?.rpm;
    if (typeof defaultRpm === 'number') {
      estimatedRemainingReqs = Math.max(0, defaultRpm - usage.requests);
    }
  }

  const providerHeadroomReqs = usage.lastUsage?.limits?.requests?.remaining;
  const providerHeadroomTokens = usage.lastUsage?.limits?.tokens?.remaining;

  return (
    <Glass as="section" className="usage-panel" aria-label={t('usage.title')}>
      <div className="usage-panel__header" onClick={() => setCollapsed(!collapsed)} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setCollapsed(!collapsed); }}>
        <div className="usage-panel__title-box">
          <span className="usage-panel__icon">
            <Icon name="dashboard" />
          </span>
          <h3 className="usage-panel__title">{t('usage.title')}</h3>
          <span className={`usage-state-pill usage-state-pill--${usage.connectionState}`}>
            {usage.connectionState === 'connected' && t('usage.state_connected')}
            {usage.connectionState === 'testing' && t('usage.state_testing')}
            {usage.connectionState === 'error' && t('usage.state_error')}
            {usage.connectionState === 'rate_limited' && t('byok.rate_limit_title')}
            {usage.connectionState === 'idle' && t('usage.state_disconnected')}
          </span>
        </div>

        <button
          type="button"
          className="btn btn--ghost btn--icon btn--sm"
          aria-label={collapsed ? t('usage.expand') : t('usage.collapse')}
          onClick={(e) => {
            e.stopPropagation();
            setCollapsed(!collapsed);
          }}
        >
          <Icon name={collapsed ? 'arrowDown' : 'arrowUp'} />
        </button>
      </div>

      {!collapsed && (
        <div className="usage-panel__body">
          <div className="usage-metrics-grid">
            {/* Total Requests */}
            <div className="usage-metric-card">
              <span className="usage-metric-card__label">{t('usage.requests')}</span>
              <span className="usage-metric-card__value num">{usage.requests}</span>
            </div>

            {/* Tokens */}
            <div className="usage-metric-card">
              <span className="usage-metric-card__label">{t('usage.tokens')}</span>
              <span className="usage-metric-card__value num">
                {usage.inputTokens + usage.outputTokens > 0
                  ? (usage.inputTokens + usage.outputTokens).toLocaleString('en-US')
                  : '—'}
              </span>
              {(usage.inputTokens > 0 || usage.outputTokens > 0) && (
                <span className="usage-metric-card__subtle num">
                  {usage.inputTokens.toLocaleString('en-US')} في | {usage.outputTokens.toLocaleString('en-US')} ناتج
                </span>
              )}
            </div>

            {/* Estimated Cost */}
            <div className="usage-metric-card">
              <span className="usage-metric-card__label">{t('usage.estimated_cost')}</span>
              <span className="usage-metric-card__value num">
                ${usage.estimatedCostUsd.toFixed(4)}{' '}
                <span className="badge badge--pill badge--accent" style={{ fontSize: '11px', padding: '2px 6px' }}>
                  {t('usage.estimated_badge')}
                </span>
              </span>
            </div>

            {/* Current Model */}
            <div className="usage-metric-card">
              <span className="usage-metric-card__label">{t('usage.current_model')}</span>
              <span className="usage-metric-card__value" style={{ fontSize: '13px', direction: 'ltr', wordBreak: 'break-all' }}>
                {usage.currentModel || '—'}
              </span>
            </div>
          </div>

          {/* Rate Limit Headroom */}
          <div className="usage-panel__headroom">
            <span className="subtle" style={{ fontWeight: 600 }}>{t('usage.rate_headroom')}:</span>
            {providerHeadroomReqs !== undefined && providerHeadroomReqs !== null ? (
              <span className="pill pill--paid" style={{ marginInlineStart: '8px' }}>
                <Icon name="checkCircle" />
                <span>{t('usage.headroom_requests', { count: providerHeadroomReqs })}</span>
              </span>
            ) : estimatedRemainingReqs !== null ? (
              <span className="pill pill--neutral" style={{ marginInlineStart: '8px' }}>
                <Icon name="clock" />
                <span>
                  {t('usage.headroom_requests', { count: estimatedRemainingReqs })}{' '}
                  <small>({t('usage.estimated_badge')})</small>
                </span>
              </span>
            ) : null}

            {providerHeadroomTokens !== undefined && providerHeadroomTokens !== null && (
              <span className="pill pill--paid" style={{ marginInlineStart: '8px' }}>
                <Icon name="sparkle" />
                <span>{t('usage.headroom_tokens', { count: providerHeadroomTokens.toLocaleString('en-US') })}</span>
              </span>
            )}
          </div>
        </div>
      )}
    </Glass>
  );
}
