import { useTheme, Button } from '../asaas-ui';
import { t } from '../content';

export function ThemeToggle() {
  const [theme, toggleTheme] = useTheme();

  return (
    <Button
      variant="ghost"
      size="sm"
      icon={theme === 'dark' ? 'sun' : 'moon'}
      label={t('action.theme')}
      onClick={toggleTheme}
    />
  );
}
