import { Icon, type IconName } from '../asaas-ui';

const ICON_MAP: Record<string, IconName> = {
  headset: 'phone',
  chat: 'sparkle',
  bot: 'sparkle',
  robot: 'sparkle',
  file: 'file',
  'file-text': 'file',
  document: 'file',
  code: 'edit',
  edit: 'edit',
  pen: 'edit',
  search: 'search',
  users: 'users',
  team: 'users',
  trend: 'trend',
  chart: 'trend',
  analysis: 'trend',
  briefcase: 'briefcase',
  receipt: 'receipt',
  grid: 'grid',
  dashboard: 'dashboard',
};

export function AgentIcon({ name, className }: { name: string; className?: string }) {
  const iconName = ICON_MAP[name] ?? 'sparkle';
  return (
    <span className={className} aria-hidden="true">
      <Icon name={iconName} />
    </span>
  );
}
