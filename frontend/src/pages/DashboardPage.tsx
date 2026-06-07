import React from 'react';
import { useLanguage } from '../context/LanguageContext';

const DashboardPage: React.FC = () => {
  const { t } = useLanguage();
  return (
    <div style={{ padding: '24px' }}>
      <h1 style={{ color: 'var(--text-primary)' }}>{t('sidebar.dashboard')}</h1>
      <div style={{ 
        display: 'grid', 
        gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', 
        gap: '24px',
        marginTop: '24px'
      }}>
        <div style={{ 
          backgroundColor: 'var(--bg-secondary)', 
          padding: '24px', 
          borderRadius: 'var(--border-radius)',
          boxShadow: 'var(--card-shadow)'
        }}>
          <h3 style={{ margin: '0 0 16px 0', color: 'var(--text-secondary)' }}>总样本数</h3>
          <div style={{ fontSize: '36px', fontWeight: 'bold', color: 'var(--accent-gold)' }}>1,248</div>
        </div>
        <div style={{ 
          backgroundColor: 'var(--bg-secondary)', 
          padding: '24px', 
          borderRadius: 'var(--border-radius)',
          boxShadow: 'var(--card-shadow)'
        }}>
          <h3 style={{ margin: '0 0 16px 0', color: 'var(--text-secondary)' }}>已标注</h3>
          <div style={{ fontSize: '36px', fontWeight: 'bold', color: 'var(--success-color)' }}>856</div>
        </div>
        <div style={{ 
          backgroundColor: 'var(--bg-secondary)', 
          padding: '24px', 
          borderRadius: 'var(--border-radius)',
          boxShadow: 'var(--card-shadow)'
        }}>
          <h3 style={{ margin: '0 0 16px 0', color: 'var(--text-secondary)' }}>待审核</h3>
          <div style={{ fontSize: '36px', fontWeight: 'bold', color: 'var(--warning-color)' }}>42</div>
        </div>
      </div>
    </div>
  );
};

export default DashboardPage;
