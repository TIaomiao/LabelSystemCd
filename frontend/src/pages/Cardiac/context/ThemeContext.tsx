import React, { createContext, useContext, useState, useEffect } from 'react';
import { getTheme, setTheme as setThemeStorage, applyTheme } from '../../../utils_cardiac/localStorage';

interface ThemeContextValue {
  theme: 'light' | 'dark';
  toggleTheme: () => void;
  setTheme: (theme: 'light' | 'dark') => void;
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [theme, setThemeState] = useState<'light' | 'dark'>(() => getTheme());

  const setTheme = (newTheme: 'light' | 'dark') => {
    setThemeState(newTheme);
    setThemeStorage(newTheme);
    applyTheme(newTheme);
  };

  const toggleTheme = () => {
    setTheme(theme === 'light' ? 'dark' : 'light');
  };

  // 确保在挂载时应用主题
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const value: ThemeContextValue = {
    theme,
    toggleTheme,
    setTheme,
  };

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useThemeContext = (): ThemeContextValue => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useThemeContext must be used inside ThemeProvider');
  }
  return context;
};
