import React from 'react';
import {
  BrowserRouter as Router,
  Routes,
  Route,
  Navigate,
  } from 'react-router-dom';
import { loadConfig } from '../../utils_cardiac/config';
import { initializeApiClient } from '../../api_cardiac/client';
import { Diagnosis } from './Diagnosis';
import { LanguageProvider, useLanguage } from './context/LanguageContext';
import { ThemeProvider } from './context/ThemeContext';
import './styles/theme.css';

function App() {
  const { t } = useLanguage();
  const [initialized, setInitialized] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    // Initialize app on mount
    const initialize = async () => {
      try {
        // Load config
        await loadConfig();

        // Initialize API client
        initializeApiClient();

        setInitialized(true);
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : 'Failed to initialize app';
        setError(errorMessage);
        console.error('Initialization error:', err);
        // Still set initialized to true to show the app with error message
        setInitialized(true);
      }
    };

    initialize();
  }, []);

  if (!initialized) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        background: 'var(--bg-primary)',
        color: 'var(--text-primary)',
        fontFamily: 'system-ui, -apple-system, sans-serif',
      }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '2rem', marginBottom: '1rem' }}>⏳</div>
          <p>Initializing application...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        background: 'var(--bg-primary)',
        color: 'var(--text-primary)',
        fontFamily: 'system-ui, -apple-system, sans-serif',
      }}>
        <div style={{
          textAlign: 'center',
          padding: '2rem',
          background: 'var(--bg-secondary)',
          borderRadius: '8px',
          border: '1px solid var(--red-500)',
          color: 'var(--red-500)',
        }}>
          <div style={{ fontSize: '2rem', marginBottom: '1rem' }}>✗</div>
          <p>{t('app.init_error')}</p>
          <pre style={{ marginTop: '1rem', textAlign: 'left' }}>{error}</pre>
        </div>
      </div>
    );
  }

  return (
    <ThemeProvider>
      <LanguageProvider>
        {/* Router removed to avoid nesting, assume parent provides Router */}
          <Routes>
            <Route path="/" element={<Navigate to="diagnosis/new" replace />} />
            <Route
              path="diagnosis/:patientId"
              element={<Diagnosis />}
            />
            <Route path="*" element={<Navigate to="diagnosis/new" replace />} />
          </Routes>
      </LanguageProvider>
    </ThemeProvider>
  );
}

export default App;
