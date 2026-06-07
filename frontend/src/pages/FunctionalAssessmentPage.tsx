import React, { useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { useResizable } from '../hooks/useResizable';
import { useLanguage } from '../context/LanguageContext';
import FunctionalAssessmentView from '../components/views/FunctionalAssessmentView';

interface CaseSummary {
  id: string;
  dataset: string;
  full_id: string;
  status?: {
    functional: boolean;
    lesion: boolean;
    analysis: boolean;
    evaluation: boolean;
  };
}

const FunctionalAssessmentPage: React.FC = () => {
  const { t } = useLanguage();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [selectedCase, setSelectedCase] = useState<CaseSummary | null>(null);
  
  const location = useLocation();
  
  // Search State
  const [searchTerm, setSearchTerm] = useState('');
  
  // Resizable Sidebars
  const leftSidebar = useResizable({
    initialWidth: 280,
    minWidth: 200,
    maxWidth: 500,
    direction: 'right',
    storageKey: 'functional-left-sidebar'
  });

  useEffect(() => {
    fetchCases();
  }, []);

  const fetchCases = async () => {
    try {
      const res = await fetch('/api/functional/cases');
      const data = await res.json();
      setCases(data);
      
      // Check for navigation state target
      if (location.state && (location.state as any).targetCase) {
          const target = data.find((c: CaseSummary) => c.full_id === (location.state as any).targetCase.full_id);
          if (target) {
              setSelectedCase(target);
              return;
          }
      }

      if (data.length > 0 && !selectedCase) {
        setSelectedCase(data[0]);
      }
    } catch (err) {
      console.error("Failed to fetch cases", err);
    }
  };

  const handleCaseClick = (c: CaseSummary) => {
    setSelectedCase(c);
  };

  const filteredCases = cases.filter(c => 
    c.id.toLowerCase().includes(searchTerm.toLowerCase()) || 
    c.dataset.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // Group by dataset
  const groupedCases: Record<string, CaseSummary[]> = {};
  filteredCases.forEach(c => {
    if (!groupedCases[c.dataset]) groupedCases[c.dataset] = [];
    groupedCases[c.dataset].push(c);
  });

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      {/* Left Sidebar: Case List */}
      <div style={{
        width: leftSidebar.width,
        backgroundColor: 'var(--bg-secondary)',
        borderRight: '1px solid var(--border-color)',
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
        flexShrink: 0,
      }}>
        {/* Resize Handle */}
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

        <div style={{ padding: '16px', borderBottom: '1px solid var(--border-color)' }}>
            <h3 style={{ margin: '0 0 12px 0', color: 'var(--text-primary)' }}>{t('sidebar.functional')}</h3>
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
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '8px' }}>
            {Object.keys(groupedCases).map(dataset => (
                <div key={dataset} style={{ marginBottom: '12px' }}>
                    <div style={{ 
                        padding: '4px 8px', 
                        fontSize: '12px', 
                        fontWeight: 'bold', 
                        color: 'var(--text-tertiary)',
                        textTransform: 'uppercase',
                        letterSpacing: '0.5px'
                    }}>
                        {dataset}
                    </div>
                    {groupedCases[dataset].map(c => (
                        <div
                            key={c.full_id}
                            onClick={() => handleCaseClick(c)}
                            style={{
                                padding: '10px 12px',
                                cursor: 'pointer',
                                borderRadius: '4px',
                                backgroundColor: selectedCase?.full_id === c.full_id ? 'rgba(217, 119, 6, 0.1)' : 'transparent',
                                borderLeft: selectedCase?.full_id === c.full_id ? '3px solid var(--accent-gold)' : '3px solid transparent',
                                marginBottom: '4px',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between'
                            }}
                        >
                            <span style={{ color: selectedCase?.full_id === c.full_id ? 'var(--accent-gold)' : 'var(--text-primary)', fontSize: '14px' }}>
                                {c.id}
                            </span>
                            {c.status?.functional && (
                                <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: '#10b981' }} title={t('patient.completed')} />
                            )}
                        </div>
                    ))}
                </div>
            ))}
            {filteredCases.length === 0 && (
                <div style={{ padding: '16px', textAlign: 'center', color: 'var(--text-muted)' }}>
                    {t('patient.no_match')}
                </div>
            )}
        </div>
      </div>

      {/* Main Content */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {selectedCase ? (
            <FunctionalAssessmentView dataset={selectedCase.dataset} caseId={selectedCase.id} />
        ) : (
            <div style={{ flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'center', color: 'var(--text-muted)' }}>
                {t('patient.select_hint')}
            </div>
        )}
      </div>
    </div>
  );
};

export default FunctionalAssessmentPage;
