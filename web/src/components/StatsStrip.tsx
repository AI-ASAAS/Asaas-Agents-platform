import { Glass, Icon } from '../asaas-ui';
import { useLang } from '../content';
import { formatNumber } from '../asaas-ui/lib/format';
import type { StatsItem } from '../lib/catalogApi';

export function StatsStrip({ stats }: { stats: StatsItem | null }) {
  const { t } = useLang();

  if (!stats || typeof stats.agent_count !== 'number' || stats.agent_count <= 0) {
    return null;
  }

  const hasRealRuns = Boolean(stats.has_real_runs && stats.total_runs && stats.total_runs > 0);

  return (
    <div className="grid grid--stats stats-strip" aria-label={t('catalog.stats_agents')}>
      <Glass className="stat">
        <span className="stat__label">
          <span className="stat__icon">
            <Icon name="sparkle" />
          </span>
          {t('catalog.stats_agents')}
        </span>
        <span className="stat__value">
          <span className="num">{formatNumber(stats.agent_count)}</span>
        </span>
        <span className="stat__foot">{t('catalog.stats_active_desc')}</span>
      </Glass>

      {hasRealRuns && stats.total_runs && (
        <Glass className="stat">
          <span className="stat__label">
            <span className="stat__icon">
              <Icon name="trend" />
            </span>
            {t('catalog.stats_total_runs')}
          </span>
          <span className="stat__value">
            <span className="num">{formatNumber(stats.total_runs)}</span>
          </span>
          <span className="stat__foot">{t('catalog.stats_runs_desc')}</span>
        </Glass>
      )}
    </div>
  );
}
