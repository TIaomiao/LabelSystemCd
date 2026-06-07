import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { FaUserMd, FaSearch, FaFileAlt, FaBrain, FaCog, FaChartBar } from 'react-icons/fa';
import { useLanguage } from '../context/LanguageContext';

interface CaseSummary {
  id: string;
  dataset: string;
  full_id: string;
  hidden_count?: number;
}

const PatientListPage: React.FC = () => {
  const { t } = useLanguage();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    fetchCases();
  }, []);

  const fetchCases = async () => {
    setLoading(true);
    try {
      // Using functional cases as the base list
      const res = await fetch('/api/functional/cases');
      const data = await res.json();
      setCases(data);
    } catch (err) {
      console.error("Failed to fetch cases", err);
    } finally {
      setLoading(false);
    }
  };

  const filteredCases = cases.filter(c => 
    c.id.toLowerCase().includes(searchTerm.toLowerCase()) || 
    c.dataset.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handleNavigate = (path: string, caseItem: CaseSummary) => {
    navigate(path, { 
      state: { 
        targetCase: {
          dataset: caseItem.dataset,
          id: caseItem.id,
          full_id: caseItem.full_id
        }
      } 
    });
  };

  return (
    <div style={{ padding: '24px', height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <div style={{ marginBottom: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ margin: 0, color: 'var(--text-primary)' }}>{t('sidebar.patient_list')}</h2>
        <div style={{ position: 'relative', width: '300px' }}>
          <FaSearch style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-tertiary)' }} />
          <input
            type="text"
            placeholder={t('patient.search_placeholder_full')}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{
              width: '100%',
              padding: '10px 10px 10px 36px',
              borderRadius: '6px',
              border: '1px solid var(--border-color)',
              backgroundColor: 'var(--bg-secondary)',
              color: 'var(--text-primary)',
              fontSize: '14px'
            }}
          />
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', backgroundColor: 'var(--bg-secondary)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead style={{ position: 'sticky', top: 0, backgroundColor: 'var(--bg-tertiary)', zIndex: 1 }}>
            <tr>
              <th style={{ padding: '16px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}>{t('patient.id')}</th>
              <th style={{ padding: '16px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}>{t('patient.dataset')}</th>
              <th style={{ padding: '16px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-secondary)', textAlign: 'center' }}>{t('patient.action')}</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={3} style={{ padding: '24px', textAlign: 'center', color: 'var(--text-tertiary)' }}>{t('common.loading')}</td>
              </tr>
            ) : filteredCases.length === 0 ? (
              <tr>
                <td colSpan={3} style={{ padding: '24px', textAlign: 'center', color: 'var(--text-tertiary)' }}>{t('patient.no_match')}</td>
              </tr>
            ) : (
              filteredCases.map(c => (
                <tr key={c.full_id} style={{ borderBottom: '1px solid var(--border-color)', transition: 'background-color 0.2s' }} className="hover:bg-opacity-50">
                  <td style={{ padding: '16px', color: 'var(--text-primary)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <FaUserMd style={{ color: 'var(--accent-gold)' }} />
                      <div style={{ display: 'flex', flexDirection: 'column' }}>
                        <span>{c.id}</span>
                        {c.hidden_count !== undefined && c.hidden_count > 0 && (
                          <span style={{ fontSize: '10px', color: 'var(--text-tertiary)' }}>
                            已隐藏 {c.hidden_count} 张 LGE 影像
                          </span>
                        )}
                      </div>
                    </div>
                  </td>
                  <td style={{ padding: '16px', color: 'var(--text-secondary)' }}>{c.dataset}</td>
                  <td style={{ padding: '16px' }}>
                    <div style={{ display: 'flex', justifyContent: 'center', gap: '8px' }}>
                      <button
                        onClick={() => handleNavigate('/functional', c)}
                        title={t('sidebar.functional')}
                        style={actionButtonStyle}
                      >
                        <FaFileAlt /> {t('sidebar.functional')}
                      </button>
                      <button
                        onClick={() => handleNavigate('/lge', c)}
                        title={t('sidebar.lesion')}
                        style={actionButtonStyle}
                      >
                        <FaBrain /> {t('sidebar.lesion')}
                      </button>
                      <button
                        onClick={() => handleNavigate('/analysis', c)}
                        title={t('sidebar.analysis')}
                        style={actionButtonStyle}
                      >
                        <FaChartBar /> {t('sidebar.analysis')}
                      </button>
                      <button
                        onClick={() => handleNavigate('/evaluation', c)}
                        title={t('sidebar.evaluation')}
                        style={actionButtonStyle}
                      >
                        <FaCog /> {t('sidebar.evaluation')}
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const actionButtonStyle = {
  display: 'flex',
  alignItems: 'center',
  gap: '6px',
  padding: '6px 12px',
  backgroundColor: 'transparent',
  border: '1px solid var(--border-color)',
  borderRadius: '4px',
  color: 'var(--text-secondary)',
  cursor: 'pointer',
  fontSize: '12px',
  transition: 'all 0.2s'
};

export default PatientListPage;
