import { Icon, type IconName } from '../asaas-ui';
import { useLang } from '../content';
import type { AgentStatus } from '../lib/catalogApi';

interface StatusMeta {
  className: string;
  icon: IconName;
  labelKey: 'agent.status_ready' | 'agent.status_coming_soon' | 'agent.status_github_only';
}

const STATUS_CONFIG: Record<AgentStatus, StatusMeta> = {
  ready: {
    className: 'pill--paid',
    icon: 'checkCircle',
    labelKey: 'agent.status_ready',
  },
  coming_soon: {
    className: 'pill--partial',
    icon: 'clock',
    labelKey: 'agent.status_coming_soon',
  },
  github_only: {
    className: 'pill--neutral',
    icon: 'alert',
    labelKey: 'agent.status_github_only',
  },
};

export function AgentStatusPill({ status }: { status: AgentStatus }) {
  const { t } = useLang();
  const meta = STATUS_CONFIG[status] || STATUS_CONFIG.github_only;

  return (
    <span className={`pill ${meta.className}`} role="status">
      <Icon name={meta.icon} />
      <span>{t(meta.labelKey)}</span>
    </span>
  );
}
