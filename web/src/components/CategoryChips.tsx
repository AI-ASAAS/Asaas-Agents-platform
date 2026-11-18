import { useLang } from '../content';
import type { CategoryItem } from '../lib/catalogApi';
import { AgentIcon } from './AgentIcon';

interface CategoryChipsProps {
  categories: CategoryItem[];
  selectedCategory: string;
  onSelectCategory: (slug: string) => void;
}

export function CategoryChips({
  categories,
  selectedCategory,
  onSelectCategory,
}: CategoryChipsProps) {
  const { t } = useLang();

  return (
    <div className="chips" role="toolbar" aria-label={t('catalog.all_categories')}>
      <button
        type="button"
        className="chip"
        aria-pressed={selectedCategory === ''}
        onClick={() => onSelectCategory('')}
      >
        <AgentIcon name="grid" />
        <span>{t('catalog.all_categories')}</span>
      </button>

      {categories.map((cat) => (
        <button
          key={cat.slug}
          type="button"
          className="chip"
          aria-pressed={selectedCategory === cat.slug}
          onClick={() => onSelectCategory(cat.slug)}
        >
          <AgentIcon name={cat.icon} />
          <span>{cat.name}</span>
        </button>
      ))}
    </div>
  );
}
