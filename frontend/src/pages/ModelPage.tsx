import React from 'react';
import { useLanguage } from '../context/LanguageContext';

const ModelPage: React.FC = () => {
  const { t } = useLanguage();
  return (
    <div style={{ padding: '24px' }}>
      <h1 style={{ color: 'var(--text-primary)' }}>{t('sidebar.model')}</h1>
      <div style={{ 
        backgroundColor: 'var(--bg-secondary)', 
        padding: '40px', 
        borderRadius: 'var(--border-radius)',
        textAlign: 'center',
        marginTop: '24px',
        color: 'var(--text-muted)'
      }}>
        {t('common.feature_dev')}
      </div>
    </div>
  );
};

export default ModelPage;
