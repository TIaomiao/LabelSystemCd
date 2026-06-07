import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useThemeContext } from '../../pages/Cardiac/context/ThemeContext.tsx';
import { useLanguage } from '../../pages/Cardiac/context/LanguageContext.tsx';
import { getUser, setUser } from '../../utils_cardiac/localStorage.ts';
import { getVersion } from '../../utils_cardiac/config.ts';
import './Navbar.css';

interface NavbarProps {
  showTitle?: boolean;
}

export const Navbar: React.FC<NavbarProps> = ({ showTitle = true }) => {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useThemeContext();
  const { language, setLanguage, t } = useLanguage();
  const user = getUser();
  const version = getVersion();

  const handleLogout = () => {
    setUser({ authenticated: false });
    navigate('/login');
  };

  const handleLanguageChange = (lang: 'en' | 'zh') => {
    setLanguage(lang);
  };

  return (
    <nav className="navbar">
      <div className="navbar-container">
        <div className="navbar-left">
          {showTitle && (
            <h1 className="navbar-title">
              <span className="logo-icon">♥</span> {t('login.title')}
            </h1>
          )}
        </div>

        <div className="navbar-right">
          <div className="navbar-controls">
            <div className="language-switcher">
              <button
                className={`lang-btn ${language === 'en' ? 'active' : ''}`}
                onClick={() => handleLanguageChange('en')}
                title="English"
              >
                EN
              </button>
              <button
                className={`lang-btn ${language === 'zh' ? 'active' : ''}`}
                onClick={() => handleLanguageChange('zh')}
                title="中文"
              >
                中文
              </button>
            </div>

            <button
              className="theme-toggle"
              onClick={toggleTheme}
              title={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}
              aria-label="Toggle theme"
            >
              {theme === 'light' ? '🌙' : '☀️'}
            </button>

            {user.authenticated && (
              <button
                className="logout-btn"
                onClick={handleLogout}
                title="Logout"
              >
                🚪 Logout
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="navbar-version">
        v{version}
      </div>
    </nav>
  );
};
