import React from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Sidebar from './Sidebar';
import { useAuth } from '../../context/AuthContext';
import { useLanguage } from '../../context/LanguageContext';
import MessageInboxBell from './MessageInboxBell';

const MainLayout: React.FC = () => {
  const { user, logout } = useAuth();
  const { language, setLanguage, t } = useLanguage();
  const location = useLocation();
  const isFullPageRoute = location.pathname.startsWith('/workstation')
    || location.pathname === '/admin/feedback'
    || location.pathname === '/feedback-dashboard';

  if (isFullPageRoute) {
    return <Outlet />;
  }
  
  return (
    <div style={{
      display: 'flex',
      height: '100vh',
      width: '100vw',
      backgroundColor: 'var(--bg-primary)',
      color: 'var(--text-primary)',
      overflow: 'hidden'
    }}>
      <Sidebar />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <header style={{
          height: '60px',
          backgroundColor: 'var(--bg-secondary)',
          borderBottom: '1px solid var(--border-color)',
          display: 'flex',
          alignItems: 'center',
          padding: '0 24px',
          justifyContent: 'space-between'
        }}>
          <div style={{ display: 'flex', gap: '16px', alignItems: 'center', marginLeft: 'auto' }}>
            <MessageInboxBell />
            <button 
              onClick={() => setLanguage(language === 'zh' ? 'en' : 'zh')}
              style={{
                padding: '4px 12px',
                fontSize: '12px',
                backgroundColor: 'transparent',
                border: '1px solid var(--border-color)',
                color: 'var(--text-secondary)',
                borderRadius: '4px',
                cursor: 'pointer'
              }}
            >
              {language === 'zh' ? 'English' : '中文'}
            </button>
             <span style={{ fontSize: '14px', color: 'var(--text-secondary)' }}>
                {user?.username}{user?.email ? ` · ${user.email}` : ''}
             </span>
             <button 
                onClick={logout}
                style={{
                  padding: '4px 12px',
                  fontSize: '12px',
                  backgroundColor: 'transparent',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-secondary)',
                  borderRadius: '4px',
                  cursor: 'pointer'
                }}
              >
                {t('app.logout')}
              </button>
            <div style={{ 
              width: '32px', 
              height: '32px', 
              borderRadius: '50%', 
              backgroundColor: 'var(--accent-gold)', 
              display: 'flex', 
              alignItems: 'center', 
              justifyContent: 'center',
              color: 'white',
              fontWeight: 'bold'
            }}>
              {user?.username?.[0]?.toUpperCase() || 'A'}
            </div>
          </div>
        </header>
        <main style={{ flex: 1, overflow: 'auto', position: 'relative' }}>
          <Outlet />
        </main>
      </div>
    </div>
  );
};


export default MainLayout;
