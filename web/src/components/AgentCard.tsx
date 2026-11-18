import { Link } from 'react-router-dom';
import { Glass, Icon } from '../asaas-ui';
import { useLang } from '../content';
import type { AgentCardItem } from '../lib/catalogApi';
import { safeHref } from '../lib/safeHref';
import { AgentIcon } from './AgentIcon';
import { AgentStatusPill } from './AgentStatusPill';

export function AgentCard({ agent }: { agent: AgentCardItem }) {
  const { t } = useLang();
  const isReady = agent.status === 'ready';

  const disabledExplanation =
    agent.status === 'coming_soon'
      ? t('agent.demo_disabled_coming_soon')
      : t('agent.demo_disabled_github_only');

  return (
    <Glass as="article" className={`card agent-card ${agent.featured ? 'agent-card--featured' : ''}`}>
      <div className="agent-card__header">
        <div className="agent-card__icon-wrapper">
          <AgentIcon name={agent.icon} className="agent-card__icon" />
        </div>
        <div className="agent-card__meta">
          <AgentStatusPill status={agent.status} />
        </div>
      </div>

      <div className="agent-card__body">
        <h3 className="agent-card__title">
          <Link to={`/agents/${encodeURIComponent(agent.slug)}`} className="agent-card__title-link">
            {agent.name}
          </Link>
        </h3>
        <p className="agent-card__summary">{agent.summary}</p>
      </div>

      <div className="agent-card__footer">
        {isReady ? (
          <Link
            to={`/agents/${encodeURIComponent(agent.slug)}`}
            className="btn btn--primary btn--sm agent-card__action"
          >
            <Icon name="sparkle" />
            <span>{t('agent.demo_button')}</span>
          </Link>
        ) : (
          <button
            type="button"
            className="btn btn--glass btn--sm agent-card__action"
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
          className="btn btn--glass btn--sm agent-card__github"
          aria-label={`${t('agent.github_button')} - ${agent.name}`}
        >
          <Icon name="file" />
          <span>{t('agent.github_button')}</span>
        </a>
      </div>
    </Glass>
  );
}
