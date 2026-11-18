import { useEffect, useMemo, useRef, useState } from 'react';
import { Card, Icon, PasswordInput } from '../asaas-ui';
import { useLang } from '../content';
import {
  fetchProviderModels,
  fetchProviders,
  testLLMConnection,
  validateProviderKey,
  type ModelItem,
  type ProviderMeta,
} from '../lib/providerApi';
import { safeHref } from '../lib/safeHref';
import { sessionKeyStore } from '../lib/sessionKeyStore';
import { useUsageTracker } from '../lib/useUsageTracker';

interface KeySetupFlowProps {
  agentSlug: string;
  allowedProviders?: string[];
  onReady?: (ready: boolean) => void;
}

export function KeySetupFlow({ agentSlug, allowedProviders = [], onReady }: KeySetupFlowProps) {
  const { t } = useLang();
  const usageTracker = useUsageTracker();

  // Load existing credentials from session if present
  const existingCreds = sessionKeyStore.getCredentials();

  const [providers, setProviders] = useState<ProviderMeta[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string>(existingCreds?.provider || 'gemini');
  const [keyInput, setKeyInput] = useState<string>(existingCreds?.key || '');
  const [rememberInSession, setRememberInSession] = useState<boolean>(existingCreds?.rememberInSession ?? true);

  const [isValidating, setIsValidating] = useState<boolean>(false);
  const [isValidated, setIsValidated] = useState<boolean>(!!existingCreds?.key);
  const [validationError, setValidationError] = useState<string | null>(null);

  const [models, setModels] = useState<{ compatible: ModelItem[]; unknown: ModelItem[]; incompatible: ModelItem[] }>({
    compatible: [],
    unknown: [],
    incompatible: [],
  });
  const [selectedModel, setSelectedModel] = useState<string>(existingCreds?.model || '');
  const [modelSearch, setModelSearch] = useState<string>('');
  const [useCustomModel, setUseCustomModel] = useState<boolean>(false);
  const [isDropdownOpen, setIsDropdownOpen] = useState<boolean>(false);
  const [liveModelsCount, setLiveModelsCount] = useState<number>(0);
  const [isLoadingModels, setIsLoadingModels] = useState<boolean>(false);
  const pickerRef = useRef<HTMLDivElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);

  const [isTesting, setIsTesting] = useState<boolean>(false);
  const [testSuccess, setTestSuccess] = useState<boolean>(false);
  const [testError, setTestError] = useState<string | null>(null);
  const [testWarning, setTestWarning] = useState<string | null>(null);

  // Rate limit countdown state
  const [rateLimitSeconds, setRateLimitSeconds] = useState<number | null>(null);

  // Sync selectedModel & readiness into sessionKeyStore / parent whenever key is validated and model is selected
  useEffect(() => {
    if (isValidated && selectedModel.trim()) {
      sessionKeyStore.setModel(selectedModel.trim());
      if (onReady) onReady(true);
    } else if (onReady) {
      onReady(false);
    }
  }, [isValidated, selectedModel, onReady]);

  // If returning with an already-validated session key, load its live model list
  useEffect(() => {
    if (existingCreds?.key && existingCreds?.provider) {
      loadModelsList(existingCreds.provider, { key: existingCreds.key });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load providers on mount
  useEffect(() => {
    fetchProviders()
      .then((data) => {
        setProviders(data);
        if (!existingCreds?.provider && data.length > 0) {
          // Default to first allowed provider
          const defaultProv = data.find((p) => allowedProviders.length === 0 || allowedProviders.includes(p.id)) || data[0];
          setSelectedProvider(defaultProv.id);
        }
      })
      .catch((err) => {
        setValidationError(err.message || t('error.generic'));
      });
  }, [t, existingCreds?.provider, allowedProviders]);

  const loadModelsList = async (
    providerId: string,
    opts?: { key?: string; liveModels?: string[] }
  ) => {
    setIsLoadingModels(true);
    try {
      const res = await fetchProviderModels(providerId, agentSlug, opts);
      setModels(res);
      const totalAvailable = res.compatible.length + res.unknown.length + res.incompatible.length;
      if (opts?.liveModels) {
        setLiveModelsCount(opts.liveModels.length);
      } else if (opts?.key) {
        setLiveModelsCount(totalAvailable);
      }
      const allIds = [...res.compatible, ...res.unknown, ...res.incompatible].map((m) => m.id);
      if (allIds.length > 0) {
        setSelectedModel((prev) => {
          if (prev && (allIds.includes(prev) || useCustomModel)) return prev;
          return res.compatible[0]?.id || res.unknown[0]?.id || allIds[0];
        });
      }
    } catch (err: any) {
      setValidationError(err.message || t('error.generic'));
    } finally {
      setIsLoadingModels(false);
    }
  };

  // Close custom dropdown on outside click or Escape key
  useEffect(() => {
    if (!isDropdownOpen) return;
    const handleOutside = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setIsDropdownOpen(false);
      }
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsDropdownOpen(false);
    };
    document.addEventListener('mousedown', handleOutside);
    document.addEventListener('keydown', handleKey);
    setTimeout(() => searchInputRef.current?.focus(), 20);
    return () => {
      document.removeEventListener('mousedown', handleOutside);
      document.removeEventListener('keydown', handleKey);
    };
  }, [isDropdownOpen]);

  // Do NOT show any models before key validation. Only fetch live models when an already-validated session key exists.
  useEffect(() => {
    if (!selectedProvider) return;
    setModelSearch('');
    setIsDropdownOpen(false);
    const savedKey =
      existingCreds?.provider === selectedProvider && existingCreds?.key ? existingCreds.key : undefined;
    if (savedKey) {
      loadModelsList(selectedProvider, { key: savedKey });
    } else {
      setModels({ compatible: [], unknown: [], incompatible: [] });
      setLiveModelsCount(0);
      setSelectedModel('');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProvider, agentSlug]);

  // Countdown timer for rate limiting
  useEffect(() => {
    if (rateLimitSeconds === null || rateLimitSeconds <= 0) return;
    const interval = setInterval(() => {
      setRateLimitSeconds((prev) => (prev && prev > 1 ? prev - 1 : null));
    }, 1000);
    return () => clearInterval(interval);
  }, [rateLimitSeconds]);

  // Sync readiness with parent (key validated + compatible model selected)
  useEffect(() => {
    const isReady = Boolean(isValidated && selectedModel && keyInput.trim());
    if (selectedModel) {
      sessionKeyStore.setModel(selectedModel);
    }
    if (onReady) {
      onReady(isReady);
    }
  }, [isValidated, selectedModel, keyInput, onReady]);

  const activeProviderMeta = providers.find((p) => p.id === selectedProvider);

  const filteredModels = useMemo(() => {
    const q = modelSearch.trim().toLowerCase();
    const match = (m: ModelItem) =>
      !q || m.id.toLowerCase().includes(q) || m.display_name.toLowerCase().includes(q);
    return {
      compatible: models.compatible.filter(match),
      unknown: models.unknown.filter(match),
      incompatible: models.incompatible.filter(match),
    };
  }, [models, modelSearch]);

  const totalModelsCount =
    models.compatible.length + models.unknown.length + models.incompatible.length;

  const selectedModelInfo = useMemo(() => {
    return (
      [...models.compatible, ...models.unknown, ...models.incompatible].find(
        (m) => m.id === selectedModel
      ) || null
    );
  }, [models, selectedModel]);

  const handleValidate = async () => {
    if (!keyInput.trim()) return;
    setIsValidating(true);
    setValidationError(null);
    setRateLimitSeconds(null);
    try {
      const valRes = await validateProviderKey(selectedProvider, keyInput.trim());
      setIsValidated(true);
      sessionKeyStore.setCredentials(selectedProvider, keyInput.trim(), selectedModel, rememberInSession);
      // Merge ALL live models returned by the provider API into the selectable list
      await loadModelsList(selectedProvider, {
        key: keyInput.trim(),
        liveModels: valRes.models || [],
      });
    } catch (err: any) {
      setIsValidated(false);
      const msg = err.message || t('error.generic');
      setValidationError(msg);
      if (err.status === 429 || err.code === 'rate_limited') {
        setRateLimitSeconds(Math.ceil(err.retry_after_seconds || 60));
        usageTracker.setConnectionState('rate_limited', selectedProvider, selectedModel);
      }
    } finally {
      setIsValidating(false);
    }
  };

  const handleTestConnection = async () => {
    if (!keyInput.trim() || !selectedModel) return;
    setIsTesting(true);
    setTestError(null);
    setTestWarning(null);
    setTestSuccess(false);
    setRateLimitSeconds(null);
    usageTracker.setConnectionState('testing', selectedProvider, selectedModel);

    try {
      const res = await testLLMConnection(selectedProvider, keyInput.trim(), selectedModel);
      setTestSuccess(true);
      usageTracker.recordUsage(res.usage);
      sessionKeyStore.setModel(selectedModel);
      if (onReady) onReady(true);
    } catch (err: any) {
      setTestSuccess(false);
      const msg = err.message || t('error.generic');
      const isTransientBusy =
        err.status === 503 ||
        err.status === 502 ||
        err.status === 504 ||
        err.status === 429 ||
        err.code === 'provider_unavailable' ||
        err.code === 'rate_limited';

      if (err.status === 429 || err.code === 'rate_limited') {
        setRateLimitSeconds(Math.ceil(err.retry_after_seconds || 60));
        usageTracker.setConnectionState('rate_limited', selectedProvider, selectedModel);
        setTestWarning(
          `${msg} — مفتاحك ما زال صالحاً؛ يمكنك الانتظار قليلاً أو اختيار نموذج آخر أو فتح الوكيل مباشرة.`
        );
      } else if (isTransientBusy) {
        usageTracker.setConnectionState('error', selectedProvider, selectedModel);
        setTestWarning(
          `النموذج (${selectedModel}) يواجه ضغطاً مؤقتاً حالياً من جهة المزوّد (${err.status || 503}). مفتاحك صالح، ويمكنك إعادة المحاولة بعد ثوانٍ، أو اختيار نموذج آخر، أو المتابعة لفتح الوكيل مباشرة.`
        );
      } else {
        usageTracker.setConnectionState('error', selectedProvider, selectedModel);
        setTestError(msg);
        // Only block readiness on hard auth/model errors (401/403/404)
        if (onReady) onReady(false);
      }
    } finally {
      setIsTesting(false);
    }
  };

  const handleForgetKey = () => {
    sessionKeyStore.clear();
    fetch('/api/service-sessions/logout', { method: 'POST', credentials: 'same-origin' }).catch(() => {});
    setKeyInput('');
    setIsValidated(false);
    setTestSuccess(false);
    setValidationError(null);
    setTestError(null);
    setTestWarning(null);
    setModels({ compatible: [], unknown: [], incompatible: [] });
    setSelectedModel('');
    setLiveModelsCount(0);
    setUseCustomModel(false);
    setIsDropdownOpen(false);
    usageTracker.resetUsage();
    if (onReady) onReady(false);
  };

  return (
    <Card title={t('byok.title')} icon="vault" className="byok-setup-card">
      <p className="subtle" style={{ margin: '0 0 18px 0' }}>
        {t('byok.subtitle')}
      </p>

      {/* Rate Limit Alert Banner with Countdown */}
      {rateLimitSeconds !== null && (
        <div className="rate-limit-banner" role="alert">
          <div className="rate-limit-banner__header">
            <Icon name="clock" />
            <strong>{t('byok.rate_limit_title')}</strong>
          </div>
          <p style={{ margin: '6px 0 12px 0', fontSize: '14px' }}>
            {t('byok.rate_limit_desc', { seconds: rateLimitSeconds })}
          </p>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <button
              type="button"
              className="btn btn--glass btn--sm"
              onClick={() => {
                setRateLimitSeconds(null);
                const el = document.getElementById('model-selection');
                el?.scrollIntoView({ behavior: 'smooth' });
              }}
            >
              <Icon name="sparkle" />
              <span>{t('byok.action_change_model')}</span>
            </button>
            <button
              type="button"
              className="btn btn--glass btn--sm"
              onClick={() => {
                setRateLimitSeconds(null);
                setIsValidated(false);
              }}
            >
              <Icon name="grid" />
              <span>{t('byok.action_change_provider')}</span>
            </button>
          </div>
        </div>
      )}

      {/* Step 1: Choose Provider */}
      <div className="byok-step">
        <label className="byok-step__title">{t('byok.step_provider')}</label>
        <div className="chips" role="radiogroup" aria-label={t('byok.step_provider')}>
          {providers.map((p) => {
            const isAllowed = allowedProviders.length === 0 || allowedProviders.includes(p.id);
            const isSelected = selectedProvider === p.id;
            return (
              <button
                key={p.id}
                type="button"
                className={`chip ${!isAllowed ? 'chip--disabled' : ''}`}
                aria-pressed={isSelected}
                disabled={!isAllowed}
                onClick={() => {
                  setSelectedProvider(p.id);
                  setIsValidated(false);
                  setTestSuccess(false);
                  setValidationError(null);
                  setTestError(null);
                  setModels({ compatible: [], unknown: [], incompatible: [] });
                  setSelectedModel('');
                  setLiveModelsCount(0);
                  setIsDropdownOpen(false);
                }}
              >
                <Icon name={isSelected ? 'check' : 'sparkle'} />
                <span>{p.name_ar}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Step 2: Where to get a free key */}
      {activeProviderMeta && (
        <div className="byok-free-key-box">
          <details className="free-key-details">
            <summary className="free-key-summary">
              <Icon name="sparkle" />
              <span>{t('byok.get_free_key')} — {activeProviderMeta.name_ar}</span>
            </summary>
            <div className="free-key-content">
              <ol style={{ paddingInlineStart: '20px', margin: '8px 0', fontSize: '14px', lineHeight: 1.7 }}>
                {activeProviderMeta.free_key_steps_ar.map((step, idx) => (
                  <li key={idx}>{step}</li>
                ))}
              </ol>
              <a
                href={safeHref(activeProviderMeta.free_key_url)}
                target="_blank"
                rel="noopener noreferrer"
                className="btn btn--glass btn--sm"
                style={{ width: 'fit-content', marginTop: '6px' }}
              >
                <Icon name="file" />
                <span>فتح صفحة المفاتيح الرسمية</span>
              </a>
            </div>
          </details>
        </div>
      )}

      {/* Step 3: Enter API Key */}
      <div className="byok-step">
        <label className="byok-step__title" htmlFor="provider-key-input">
          {t('byok.step_key')}
        </label>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <PasswordInput
            id="provider-key-input"
            value={keyInput}
            onChange={(e) => {
              setKeyInput(e.target.value);
              setIsValidated(false);
              setTestSuccess(false);
              setValidationError(null);
              setModels({ compatible: [], unknown: [], incompatible: [] });
              setSelectedModel('');
              setLiveModelsCount(0);
              setIsDropdownOpen(false);
            }}
            placeholder={activeProviderMeta?.key_format_hint || t('byok.key_placeholder')}
            autoComplete="off"
            spellCheck="false"
          />

          {/* Privacy Note */}
          <p className="byok-privacy-note subtle">
            <Icon name="alert" />
            <span>{t('byok.privacy_note')}</span>
          </p>

          <label className="byok-remember-label">
            <input
              type="checkbox"
              checked={rememberInSession}
              onChange={(e) => setRememberInSession(e.target.checked)}
            />
            <span>{t('byok.remember_session')}</span>
          </label>
        </div>

        {/* Validation Button & Error */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginTop: '12px', flexWrap: 'wrap' }}>
          <button
            type="button"
            className="btn btn--primary btn--sm"
            onClick={handleValidate}
            disabled={isValidating || !keyInput.trim()}
          >
            <Icon name="checkCircle" />
            <span>{isValidating ? t('byok.validating') : t('byok.validate_button')}</span>
          </button>

          {isValidated && (
            <span className="pill pill--paid">
              <Icon name="check" />
              <span>{t('byok.key_valid')}</span>
            </span>
          )}

          {keyInput && (
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={handleForgetKey}
              style={{ marginInlineStart: 'auto' }}
            >
              <Icon name="trash" />
              <span>{t('byok.forget_key')}</span>
            </button>
          )}
        </div>

        {validationError && (
          <p className="byok-error-text" role="alert">
            {validationError}
          </p>
        )}
      </div>

      {/* Step 4: Model Selection (Hidden until API key is validated; Asaas Liquid-Glass Picker) */}
      <div id="model-selection" className="byok-step">
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '10px',
            flexWrap: 'wrap',
            marginBottom: '12px',
          }}
        >
          <label className="byok-step__title" htmlFor="provider-model-trigger" style={{ margin: 0 }}>
            {t('byok.step_model')}
          </label>

          {isValidated && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              {totalModelsCount > 0 && (
                <span className="pill" style={{ fontSize: '12px' }}>
                  {liveModelsCount > 0
                    ? `متاح على مفتاحك: ${totalModelsCount} نموذج`
                    : `${totalModelsCount} نموذج`}
                </span>
              )}
              <button
                type="button"
                className="btn btn--glass btn--sm"
                disabled={isLoadingModels}
                onClick={() => loadModelsList(selectedProvider, { key: keyInput.trim() })}
              >
                <Icon name="sparkle" />
                <span>{isLoadingModels ? 'جاري التحديث...' : 'تحديث القائمة'}</span>
              </button>
            </div>
          )}
        </div>

        {!isValidated ? (
          <div className="model-picker-locked" role="status">
            <Icon name="vault" />
            <span>
              أدخل مفتاح API أعلاه واضغط على <strong>«التحقق من المفتاح»</strong> أولاً لعرض جميع النماذج المتاحة على حسابك واختيار النموذج الذي تريده.
            </span>
          </div>
        ) : isLoadingModels ? (
          <div className="model-picker-locked" role="status">
            <Icon name="clock" />
            <span>جاري جلب قائمة النماذج المتاحة من {activeProviderMeta?.name_ar || selectedProvider}...</span>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {!useCustomModel ? (
              <div className="model-picker" ref={pickerRef}>
                {/* Glass Trigger Button */}
                <button
                  id="provider-model-trigger"
                  type="button"
                  className="model-picker__trigger"
                  aria-haspopup="listbox"
                  aria-expanded={isDropdownOpen}
                  onClick={() => setIsDropdownOpen((prev) => !prev)}
                >
                  <span className="model-picker__trigger-main">
                    <span className="model-picker__trigger-icon">
                      <Icon name="sparkle" />
                    </span>
                    <span className="model-picker__trigger-text">
                      <span className="model-picker__trigger-name">
                        {selectedModelInfo?.display_name || selectedModel || 'اختر نموذجاً من القائمة'}
                      </span>
                      {selectedModel && (
                        <span className="model-picker__trigger-id" dir="ltr">
                          {selectedModel}
                        </span>
                      )}
                    </span>
                  </span>

                  <span className="model-picker__trigger-meta">
                    {selectedModelInfo?.tag === 'compatible' && (
                      <span className="model-picker__badge model-picker__badge--compatible">مُجرّب</span>
                    )}
                    {selectedModelInfo?.tag === 'unknown' && (
                      <span className="model-picker__badge model-picker__badge--live">متاح عبر API</span>
                    )}
                    {selectedModelInfo?.tag === 'incompatible' && (
                      <span className="model-picker__badge model-picker__badge--warn">ملاحظة</span>
                    )}
                    <svg
                      className="model-picker__chevron"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2.2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden="true"
                    >
                      <polyline points="6 9 12 15 18 9" />
                    </svg>
                  </span>
                </button>

                {/* Liquid-Glass Floating Dropdown Menu */}
                {isDropdownOpen && (
                  <div className="model-picker__dropdown" role="listbox" aria-label={t('byok.step_model')}>
                    <div className="model-picker__search-wrap">
                      <Icon name="search" />
                      <input
                        ref={searchInputRef}
                        type="text"
                        className="model-picker__search-input"
                        value={modelSearch}
                        onChange={(e) => setModelSearch(e.target.value)}
                        placeholder="ابحث بالاسم أو الإصدار (مثال: 3.6، 2.5، flash، pro، claude...)"
                        aria-label="بحث في النماذج"
                      />
                      {modelSearch && (
                        <button
                          type="button"
                          className="model-picker__search-clear"
                          onClick={() => setModelSearch('')}
                          aria-label="مسح البحث"
                        >
                          <Icon name="close" />
                        </button>
                      )}
                    </div>

                    <div className="model-picker__list">
                      {filteredModels.compatible.length > 0 && (
                        <>
                          <div className="model-picker__group-label">
                            <span>النماذج المجربة والمتوافقة مع الوكيل</span>
                            <span>{filteredModels.compatible.length}</span>
                          </div>
                          {filteredModels.compatible.map((m) => {
                            const isSelected = selectedModel === m.id;
                            return (
                              <button
                                key={m.id}
                                type="button"
                                role="option"
                                aria-selected={isSelected}
                                className={`model-picker__option ${isSelected ? 'model-picker__option--selected' : ''}`}
                                onClick={() => {
                                  setSelectedModel(m.id);
                                  setTestSuccess(false);
                                  setTestError(null);
                                  setIsDropdownOpen(false);
                                }}
                              >
                                <span className="model-picker__option-info">
                                  <span className="model-picker__option-title">{m.display_name}</span>
                                  <span className="model-picker__option-sub" dir="ltr">{m.id}</span>
                                </span>
                                <span className="model-picker__badge model-picker__badge--compatible">
                                  {isSelected ? '✓ مختار' : 'مُجرّب'}
                                </span>
                              </button>
                            );
                          })}
                        </>
                      )}

                      {filteredModels.unknown.length > 0 && (
                        <>
                          <div className="model-picker__group-label">
                            <span>جميع النماذج المتاحة عبر API حسابك</span>
                            <span>{filteredModels.unknown.length}</span>
                          </div>
                          {filteredModels.unknown.map((m) => {
                            const isSelected = selectedModel === m.id;
                            return (
                              <button
                                key={m.id}
                                type="button"
                                role="option"
                                aria-selected={isSelected}
                                className={`model-picker__option ${isSelected ? 'model-picker__option--selected' : ''}`}
                                onClick={() => {
                                  setSelectedModel(m.id);
                                  setTestSuccess(false);
                                  setTestError(null);
                                  setIsDropdownOpen(false);
                                }}
                              >
                                <span className="model-picker__option-info">
                                  <span className="model-picker__option-title" dir="ltr">{m.id}</span>
                                </span>
                                <span className="model-picker__badge model-picker__badge--live">
                                  {isSelected ? '✓ مختار' : 'API'}
                                </span>
                              </button>
                            );
                          })}
                        </>
                      )}

                      {filteredModels.incompatible.length > 0 && (
                        <>
                          <div className="model-picker__group-label">
                            <span>نماذج أخرى (قد لا تدعم بعض المزايا)</span>
                            <span>{filteredModels.incompatible.length}</span>
                          </div>
                          {filteredModels.incompatible.map((m) => {
                            const isSelected = selectedModel === m.id;
                            return (
                              <button
                                key={m.id}
                                type="button"
                                role="option"
                                aria-selected={isSelected}
                                className={`model-picker__option ${isSelected ? 'model-picker__option--selected' : ''}`}
                                onClick={() => {
                                  setSelectedModel(m.id);
                                  setTestSuccess(false);
                                  setTestError(null);
                                  setIsDropdownOpen(false);
                                }}
                              >
                                <span className="model-picker__option-info">
                                  <span className="model-picker__option-title">{m.display_name}</span>
                                  <span className="model-picker__option-sub" dir="ltr">{m.id}</span>
                                </span>
                                <span className="model-picker__badge model-picker__badge--warn">
                                  {isSelected ? '✓ مختار' : 'تجريبي'}
                                </span>
                              </button>
                            );
                          })}
                        </>
                      )}

                      {filteredModels.compatible.length === 0 &&
                        filteredModels.unknown.length === 0 &&
                        filteredModels.incompatible.length === 0 && (
                          <div className="model-picker__empty">
                            لا توجد نتائج مطابقة لـ «{modelSearch}» — يمكنك تفعيل خيار الإدخال اليدوي بالأسفل.
                          </div>
                        )}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <input
                id="provider-model-trigger"
                type="text"
                dir="ltr"
                className="model-picker__custom-input"
                value={selectedModel}
                onChange={(e) => {
                  setSelectedModel(e.target.value.trim());
                  setTestSuccess(false);
                  setTestError(null);
                }}
                placeholder="مثال: gemini-3.6-flash أو gemini-2.5-pro أو gpt-4.1"
              />
            )}

            <div className="model-picker__footer">
              <label
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '8px',
                  fontSize: '13px',
                  cursor: 'pointer',
                  color: 'var(--text-2)',
                }}
              >
                <input
                  type="checkbox"
                  checked={useCustomModel}
                  onChange={(e) => {
                    setUseCustomModel(e.target.checked);
                    setIsDropdownOpen(false);
                  }}
                />
                <span>إدخال معرّف نموذج مخصص يدوياً</span>
              </label>

              {selectedModel && (
                <span className="subtle" style={{ fontSize: '12px', fontFamily: 'monospace' }} dir="ltr">
                  Model: <strong>{selectedModel}</strong>
                </span>
              )}
            </div>

            {selectedModelInfo?.tag === 'incompatible' && selectedModelInfo.reason && (
              <p className="byok-privacy-note subtle" style={{ color: 'var(--partial)' }}>
                <Icon name="alert" />
                <span>ملاحظة: {selectedModelInfo.reason} — يمكنك اختباره وتشغيله على أي حال.</span>
              </p>
            )}
          </div>
        )}
      </div>

      {/* Step 5: Test Connection (Optional diagnostic check) */}
      <div className="byok-step" style={{ borderBottom: 'none', paddingBottom: 0 }}>
        <label className="byok-step__title">
          {t('byok.step_test')} <span className="subtle" style={{ fontWeight: 500 }}>(اختياري)</span>
        </label>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
          <button
            type="button"
            className="btn btn--glass"
            onClick={handleTestConnection}
            disabled={isTesting || !isValidated || !keyInput.trim() || !selectedModel}
          >
            <Icon name="sparkle" />
            <span>{isTesting ? t('byok.testing') : t('byok.test_button')}</span>
          </button>

          {testSuccess && (
            <span className="pill pill--paid">
              <Icon name="checkCircle" />
              <span>{t('byok.test_success')}</span>
            </span>
          )}
        </div>

        {testWarning && (
          <div
            role="status"
            style={{
              marginTop: '10px',
              padding: '10px 14px',
              borderRadius: '12px',
              background: 'var(--partial-bg)',
              border: '1px solid rgba(186, 149, 85, 0.35)',
              color: 'var(--partial)',
              fontSize: '13px',
              lineHeight: 1.6,
            }}
          >
            {testWarning}
          </div>
        )}

        {testError && (
          <p className="byok-error-text" role="alert">
            {testError}
          </p>
        )}
      </div>
    </Card>
  );
}
