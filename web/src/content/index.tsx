import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { ar, type DictionaryKey } from './dict.ar';
import { getLang, setLang, t, type Lang } from './i18n';

export { getLang, setLang, t, type Lang, type DictionaryKey };

interface LangContextValue {
  lang: Lang;
  t: (key: DictionaryKey, params?: Record<string, string | number>) => string;
}

const LangContext = createContext<LangContextValue>({
  lang: 'ar',
  t: (key) => ar[key] ?? key,
});

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang] = useState<Lang>('ar');

  useEffect(() => {
    setLang(lang);
  }, [lang]);

  const translate = (key: DictionaryKey, params?: Record<string, string | number>) => t(key, params);

  return (
    <LangContext.Provider value={{ lang, t: translate }}>
      {children}
    </LangContext.Provider>
  );
}

export function useLang() {
  return useContext(LangContext);
}
