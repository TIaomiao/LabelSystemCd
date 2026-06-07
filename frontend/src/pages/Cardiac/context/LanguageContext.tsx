import React, { createContext, useContext, useMemo, useState, useEffect } from 'react';
import { useLanguage as useGlobalLanguage } from '../../../context/LanguageContext';
import {
  LanguageKey,
  supportedLanguages,
  translate,
  translations,
  type TranslationDictionary,
} from '../../../i18n_cardiac/index';
import {
  getPreferredLanguage,
  setPreferredLanguage,
} from '../../../utils_cardiac/localStorage';

interface LanguageContextValue {
  language: LanguageKey;
  t: (key: string) => string;
  setLanguage: (language: LanguageKey) => void;
  availableLanguages: typeof supportedLanguages;
  dictionary: TranslationDictionary;
}

const LanguageContext = createContext<LanguageContextValue | undefined>(
  undefined
);

export const LanguageProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const { language: globalLanguage, setLanguage: setGlobalLanguage } = useGlobalLanguage();
  const language = globalLanguage as LanguageKey;

  const setLanguage = (lang: LanguageKey) => {
    setGlobalLanguage(lang);
    setPreferredLanguage(lang);
  };

  const value = useMemo<LanguageContextValue>(
    () => ({
      language,
      setLanguage,
      availableLanguages: supportedLanguages,
      dictionary: translations[language],
      t: (key: string) => translate(language, key),
    }),
    [language, setGlobalLanguage]
  );

  return (
    <LanguageContext.Provider value={value}>
      {children}
    </LanguageContext.Provider>
  );
};

export const useLanguage = (): LanguageContextValue => {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error('useLanguage must be used inside LanguageProvider');
  }
  return context;
};
