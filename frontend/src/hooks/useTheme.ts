import { useState, useEffect } from 'react';
import { getTheme, setTheme, applyTheme } from '../utils/localStorage.ts';

export function useTheme() {
  const [theme, setThemeState] = useState<'light' | 'dark'>(() => {
    return getTheme();
  });

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const toggleTheme = () => {
    const newTheme = theme === 'light' ? 'dark' : 'light';
    setThemeState(newTheme);
    setTheme(newTheme);
  };

  return { theme, toggleTheme };
}
