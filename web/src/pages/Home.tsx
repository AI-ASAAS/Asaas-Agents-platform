import { useCallback, useEffect, useState, useTransition } from 'react';
import { useSearchParams } from 'react-router-dom';
import { EmptyState, ErrorState, Glass, Icon, Skeleton, Swash } from '../asaas-ui';
import { AgentCard } from '../components/AgentCard';
import { CategoryChips } from '../components/CategoryChips';
import { StatsStrip } from '../components/StatsStrip';
import { useLang } from '../content';
import {
  fetchAgents,
  fetchCategories,
  fetchStats,
  type AgentCardItem,
  type CategoryItem,
  type StatsItem,
} from '../lib/catalogApi';
import { usePageMeta } from '../lib/usePageMeta';

export default function Home() {
  const { t } = useLang();
  const [searchParams, setSearchParams] = useSearchParams();
  const [, startTransition] = useTransition();

  const urlQuery = searchParams.get('q') || '';
  const urlCategory = searchParams.get('category') || '';

  const [searchInput, setSearchInput] = useState<string>(urlQuery);
  const [prevUrlQuery, setPrevUrlQuery] = useState<string>(urlQuery);
  const [categories, setCategories] = useState<CategoryItem[]>([]);
  const [agents, setAgents] = useState<AgentCardItem[]>([]);
  const [stats, setStats] = useState<StatsItem | null>(null);

  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<unknown | null>(null);

  // Sync state if URL changes externally (standard React pattern)
  if (urlQuery !== prevUrlQuery) {
    setPrevUrlQuery(urlQuery);
    setSearchInput(urlQuery);
  }

  usePageMeta({
    title: `${t('site.name')} — ${t('home.title')}`,
    description: t('home.subtitle'),
  });

  // Load categories and stats on mount
  useEffect(() => {
    let cancelled = false;
    async function loadMeta() {
      try {
        const [cats, st] = await Promise.all([fetchCategories(), fetchStats()]);
        if (!cancelled) {
          setCategories(cats);
          setStats(st);
        }
      } catch (err) {
        console.error('Failed to load catalog metadata', err);
      }
    }
    loadMeta();
    return () => {
      cancelled = true;
    };
  }, []);

  // Debounce search input to URL query
  useEffect(() => {
    const timer = setTimeout(() => {
      const currentQ = searchParams.get('q') || '';
      const trimmed = searchInput.trim();
      if (trimmed !== currentQ) {
        const newParams = new URLSearchParams(searchParams);
        if (trimmed) {
          newParams.set('q', trimmed);
        } else {
          newParams.delete('q');
        }
        startTransition(() => {
          setSearchParams(newParams, { replace: true });
        });
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [searchInput, searchParams, setSearchParams]);

  // Fetch agents whenever URL filters change
  const loadAgents = useCallback(() => {
    setIsLoading(true);
    setError(null);
    fetchAgents(urlQuery, urlCategory)
      .then((data) => {
        setAgents(data);
        setIsLoading(false);
      })
      .catch((err) => {
        setError(err);
        setIsLoading(false);
      });
  }, [urlQuery, urlCategory]);

  useEffect(() => {
    loadAgents();
  }, [loadAgents]);

  const handleSelectCategory = (catSlug: string) => {
    const newParams = new URLSearchParams(searchParams);
    if (catSlug) {
      newParams.set('category', catSlug);
    } else {
      newParams.delete('category');
    }
    setSearchParams(newParams);
  };

  const handleClearFilters = () => {
    setSearchInput('');
    setSearchParams(new URLSearchParams());
  };

  const handleClearSearch = () => {
    setSearchInput('');
    const newParams = new URLSearchParams(searchParams);
    newParams.delete('q');
    setSearchParams(newParams);
  };

  const featuredAgents = agents.filter((a) => a.featured);
  const regularAgents = agents.filter((a) => !a.featured);

  return (
    <div className="page-home" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gutter, 20px)' }}>
      {/* Hero Showcase Banner */}
      <Glass thick pill style={{ padding: '28px 24px', textAlign: 'center' }}>
        <span
          className="badge"
          style={{
            display: 'inline-block',
            padding: '4px 14px',
            borderRadius: 'var(--radius-pill)',
            background: 'var(--accent-glow)',
            color: 'var(--accent)',
            fontSize: '13px',
            fontWeight: 700,
            marginBottom: '12px',
          }}
        >
          {t('home.badge')}
        </span>
        <h1 className="display" style={{ margin: '0 0 12px 0', fontSize: 'clamp(26px, 5vw, 38px)' }}>
          {t('home.title')}
          <Swash>!</Swash>
        </h1>
        <p className="prose" style={{ maxWidth: '640px', margin: '0 auto', color: 'var(--text-2)' }}>
          {t('home.subtitle')}
        </p>
      </Glass>

      {/* Search and Category Filters */}
      <div className="catalog-search">
        <div className="search-input-wrap">
          <span className="search-icon">
            <Icon name="search" />
          </span>
          <input
            type="search"
            className="search-input"
            placeholder={t('catalog.search_placeholder')}
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            aria-label={t('catalog.search_placeholder')}
          />
          {searchInput.length > 0 && (
            <button
              type="button"
              className="search-clear-btn"
              onClick={handleClearSearch}
              aria-label={t('catalog.search_clear')}
            >
              <Icon name="close" />
            </button>
          )}
        </div>

        {categories.length > 0 && (
          <CategoryChips
            categories={categories}
            selectedCategory={urlCategory}
            onSelectCategory={handleSelectCategory}
          />
        )}
      </div>

      {/* Content Area */}
      {isLoading ? (
        <Skeleton height={180} count={3} />
      ) : error ? (
        <ErrorState error={error} onRetry={loadAgents} />
      ) : agents.length === 0 ? (
        <EmptyState icon="search" title={t('catalog.empty_title')}>
          <p className="subtle">{t('catalog.empty_desc')}</p>
          <button
            type="button"
            className="btn btn--glass btn--sm"
            onClick={handleClearFilters}
            style={{ marginTop: '12px' }}
          >
            {t('catalog.clear_filters')}
          </button>
        </EmptyState>
      ) : (
        <>
          {/* Featured Section */}
          {featuredAgents.length > 0 && (
            <section className="catalog-section" aria-label={t('catalog.featured_title')}>
              <div className="catalog-section__header">
                <h2 className="catalog-section__title">
                  <Icon name="sparkle" />
                  <span>{t('catalog.featured_title')}</span>
                </h2>
              </div>
              <div className="agent-grid">
                {featuredAgents.map((agent) => (
                  <AgentCard key={agent.slug} agent={agent} />
                ))}
              </div>
            </section>
          )}

          {/* All Agents Section */}
          <section className="catalog-section" aria-label={t('catalog.all_agents_title')}>
            <div className="catalog-section__header">
              <h2 className="catalog-section__title">
                <span>{t('catalog.all_agents_title')}</span>
                <span className="subtle num">({agents.length})</span>
              </h2>
            </div>
            <div className="agent-grid">
              {(featuredAgents.length > 0 ? regularAgents : agents).map((agent) => (
                <AgentCard key={agent.slug} agent={agent} />
              ))}
            </div>
          </section>
        </>
      )}

      {/* Real Stats Strip */}
      <StatsStrip stats={stats} />
    </div>
  );
}
