import React, { useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { useResizable } from '../hooks/useResizable';
import { useLanguage } from '../context/LanguageContext';
import EvaluationView from '../components/views/EvaluationView';

interface CaseSummary {
  id: string;
  dataset: string;
  full_id: string; // dataset/case_id
  has_report: boolean;
  display_dataset?: string;
  report_set?: boolean;
  report_set_order?: number;
  anon_label?: string;
  has_ai_v2_report?: boolean;
}

const EvaluationPage: React.FC = () => {
  const { t } = useLanguage();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [selectedCase, setSelectedCase] = useState<CaseSummary | null>(null);
  const [library, setLibrary] = useState('CMR_ALL_150');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<Date | null>(null);
  
  const location = useLocation();
  
  // Search State
  const [searchTerm, setSearchTerm] = useState('');
  
  // Resizable Sidebars
  const leftSidebar = useResizable({
    initialWidth: 320,
    minWidth: 200,
    maxWidth: 500,
    direction: 'right',
    storageKey: 'evaluation-left-sidebar'
  });

  useEffect(() => {
    fetchCases();
    const timer = window.setInterval(() => {
      fetchCases({ silent: true });
    }, 30000);
    return () => window.clearInterval(timer);
  }, []);

  const fetchCases = async (options?: { silent?: boolean }) => {
    try {
      if (!options?.silent) setIsRefreshing(true);
      const res = await fetch('/api/eval/cases', { cache: 'no-store' });
      const data = await res.json();
      const filtered = data.filter((c: CaseSummary) => c.has_report);
      setCases(filtered);
      setLastRefreshedAt(new Date());

      // Check for navigation state target
      if (location.state && (location.state as any).targetCase) {
          const target = filtered.find((c: CaseSummary) => c.full_id === (location.state as any).targetCase.full_id);
          if (target) {
              setSelectedCase(target);
          }
      } else if (filtered.length > 0 && !selectedCase) {
          // Optional: Auto select first case
          // setSelectedCase(filtered[0]);
      }
    } catch (err) {
      console.error("Failed to fetch cases", err);
    } finally {
      if (!options?.silent) setIsRefreshing(false);
    }
  };

  const handleCaseClick = (c: CaseSummary) => {
    setSelectedCase(c);
  };

  const libraryFilteredCases = cases.filter(c => {
    const baseDataset = (c.display_dataset || c.dataset || '').replace(/^new_/, '');
    if (library === 'ALL') return true;
    if (library === 'CMR_ALL_150') return baseDataset === 'CMR_ALL' && !!c.report_set;
    return baseDataset === library;
  });

  const filteredCases = libraryFilteredCases.filter(c => 
    c.id.toLowerCase().includes(searchTerm.toLowerCase()) || 
    c.dataset.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const visibleCases = filteredCases;
  const reportSetReadyCount = cases.filter(c => c.report_set).length;

  useEffect(() => {
    if (!selectedCase) return;
    if (visibleCases.some(c => c.full_id === selectedCase.full_id)) return;
    setSelectedCase(visibleCases[0] || null);
  }, [selectedCase, visibleCases]);

  // Group by dataset
  const groupedCases: Record<string, CaseSummary[]> = {};
  visibleCases.forEach(c => {
    const datasetKey = (c.display_dataset || c.dataset || '').replace(/^new_/, '');
    if (!groupedCases[datasetKey]) groupedCases[datasetKey] = [];
    groupedCases[datasetKey].push(c);
  });

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
        <div style={{
          width: leftSidebar.width,
          backgroundColor: 'var(--bg-secondary)',
          borderRight: '1px solid var(--border-color)',
          display: 'flex',
          flexDirection: 'column',
          padding: '16px',
          position: 'relative',
          flexShrink: 0
        }}>
          <div
              onMouseDown={leftSidebar.startResizing}
              style={{
                  position: 'absolute',
                  top: 0,
                  right: -2,
                  width: '5px',
                  height: '100%',
                  cursor: 'col-resize',
                  zIndex: 10,
                  backgroundColor: leftSidebar.isResizing ? 'var(--accent-gold)' : 'transparent',
                  transition: 'background-color 0.2s',
              }}
          />

          <div style={{ marginBottom: '16px', borderBottom: '1px solid var(--border-color)', paddingBottom: '16px' }}>
              <h3 style={{ margin: '0 0 12px 0', color: 'var(--text-primary)' }}>{t('sidebar.evaluation')}</h3>
              <input 
                  type="text" 
                  placeholder={t('patient.search_placeholder')}
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  style={{
                      width: '100%',
                      padding: '8px',
                      borderRadius: '4px',
                      border: '1px solid var(--border-color)',
                      backgroundColor: 'var(--bg-primary)',
                      color: 'var(--text-primary)'
                  }}
              />
              <div style={{
                  marginTop: '8px',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: '8px',
                  color: 'var(--text-muted)',
                  fontSize: '12px'
              }}>
                  <span>已加载 {reportSetReadyCount}/150 例报告{lastRefreshedAt ? ` · ${lastRefreshedAt.toLocaleTimeString()}` : ''}</span>
                  <button
                      type="button"
                      onClick={() => fetchCases()}
                      disabled={isRefreshing}
                      style={{
                          padding: '4px 8px',
                          borderRadius: '4px',
                          border: '1px solid var(--border-color)',
                          backgroundColor: 'var(--bg-primary)',
                          color: 'var(--text-primary)',
                          cursor: isRefreshing ? 'default' : 'pointer'
                      }}
                  >
                      {isRefreshing ? '刷新中' : '刷新'}
                  </button>
              </div>
              <select
                  value={library}
                  onChange={(e) => setLibrary(e.target.value)}
                  style={{
                      width: '100%',
                      padding: '8px',
                      borderRadius: '4px',
                      border: '1px solid var(--border-color)',
                      backgroundColor: 'var(--bg-primary)',
                      color: 'var(--text-primary)',
                      marginTop: '8px'
                  }}
              >
                  <option value="CMR_ALL_150">昆医附二院报告评分150例</option>
                  <option value="CMR_ALL">昆医附二院</option>
                  <option value="CMR_Chendu">成都中心</option>
                  <option value="CMR_SCS">四川省人民医院</option>
                  <option value="CMR_YA">延安医院</option>
                  <option value="ALL">全部中心</option>
              </select>
          </div>

          <div style={{ flex: 1, overflowY: 'auto' }}>
              {Object.keys(groupedCases).map(dataset => (
                  <div key={dataset} style={{ marginBottom: '16px' }}>
                      <div style={{ 
                          fontSize: '12px', 
                          fontWeight: 'bold', 
                          color: 'var(--text-tertiary)',
                          textTransform: 'uppercase',
                          letterSpacing: '0.5px',
                          marginBottom: '8px'
                      }}>
                          {dataset}
                      </div>
                      {groupedCases[dataset].map(c => (
                          <div
                              key={c.full_id}
                              onClick={() => handleCaseClick(c)}
                              style={{
                                  padding: '12px',
                                  cursor: 'pointer',
                                  borderRadius: '6px',
                                  backgroundColor: selectedCase?.full_id === c.full_id ? 'var(--bg-primary)' : 'transparent',
                                  border: selectedCase?.full_id === c.full_id ? '1px solid var(--accent-gold)' : '1px solid transparent',
                                  marginBottom: '8px',
                                  transition: 'all 0.2s'
                              }}
                          >
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                                  <span style={{ 
                                      color: selectedCase?.full_id === c.full_id ? 'var(--accent-gold)' : 'var(--text-primary)', 
                                      fontWeight: selectedCase?.full_id === c.full_id ? 'bold' : 'normal' 
                                  }}>
                                      {c.anon_label || c.id}
                                  </span>
                              </div>
                              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                                  {c.report_set_order ? `报告评分样本 #${c.report_set_order}` : t('eval.has_report')}
                              </div>
                              <div style={{
                                  marginTop: '6px',
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  borderRadius: '999px',
                                  padding: '3px 8px',
                                  fontSize: '11px',
                                  fontWeight: 700,
                                  border: c.has_ai_v2_report ? '1px solid rgba(163,230,53,0.35)' : '1px solid rgba(148,163,184,0.25)',
                                  backgroundColor: c.has_ai_v2_report ? 'rgba(163,230,53,0.12)' : 'rgba(148,163,184,0.08)',
                                  color: c.has_ai_v2_report ? '#bef264' : 'var(--text-muted)'
                              }}>
                                  {c.has_ai_v2_report ? 'AI_V2已生成' : 'AI_V2未生成'}
                              </div>
                          </div>
                      ))}
                  </div>
              ))}
              {filteredCases.length === 0 && (
                  <div style={{ textAlign: 'center', color: 'var(--text-muted)', marginTop: '20px' }}>
                      {t('patient.no_match')}
                  </div>
              )}
          </div>
        </div>

        <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          {selectedCase ? (
              <EvaluationView dataset={selectedCase.dataset} caseId={selectedCase.id} />
          ) : (
              <div style={{ flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'center', color: 'var(--text-muted)' }}>
                  {t('patient.select_hint')}
              </div>
          )}
        </div>
    </div>
  );
};

export default EvaluationPage;
