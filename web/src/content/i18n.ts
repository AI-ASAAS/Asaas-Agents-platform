import { ar, type DictionaryKey } from './dict.ar';
import { en } from './dict.en';

export type Lang = 'ar' | 'en';

const DICTIONARIES: Record<Lang, Record<DictionaryKey, string>> = { ar, en };

let currentLang: Lang = 'ar';

export function setLang(lang: Lang) {
  currentLang = lang;
}

export function getLang(): Lang {
  return currentLang;
}

export function t(key: DictionaryKey, params?: Record<string, string | number>): string {
  const dict = DICTIONARIES[currentLang] ?? ar;
  let text = dict[key] ?? ar[key] ?? key;
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      text = text.replace(new RegExp(`{${k}}`, 'g'), String(v));
    }
  }
  return text;
}
