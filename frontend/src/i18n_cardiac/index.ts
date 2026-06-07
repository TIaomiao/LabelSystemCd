import { enTranslations, type TranslationDictionary } from './en.ts';
import { zhTranslations } from './zh.ts';

export const supportedLanguages = [
  { key: 'en', label: 'EN' },
  { key: 'zh', label: '中文' },
] as const;

export type LanguageKey = typeof supportedLanguages[number]['key'];

const translationMap: Record<LanguageKey, TranslationDictionary> = {
  en: enTranslations,
  zh: zhTranslations as TranslationDictionary,
};

export const translate = (language: LanguageKey, key: string): string => {
  const segments = key.split('.');
  let current: unknown = translationMap[language] ?? translationMap.en;

  for (const segment of segments) {
    if (
      current &&
      typeof current === 'object' &&
      segment in (current as Record<string, unknown>)
    ) {
      current = (current as Record<string, unknown>)[segment];
    } else {
      current = null;
      break;
    }
  }

  if (typeof current === 'string') {
    return current;
  }

  if (language !== 'en') {
    return translate('en', key);
  }

  return key;
};

export const getLanguageLabel = (language: LanguageKey): string => {
  const found = supportedLanguages.find(l => l.key === language);
  return found ? found.label : language.toUpperCase();
};

export { translationMap as translations };
export type { TranslationDictionary } from './en.ts';
