import React, { useState, useEffect } from 'react';
import { useResizable } from '../hooks/useResizable';
import { useLanguage } from '../context/LanguageContext';
import {
  FaSearch,
  FaUserMd,
  FaChevronRight,
  FaChevronDown,
  FaFileAlt,
  FaBrain,
  FaChartBar,
  FaCog
} from 'react-icons/fa';
import FunctionalAssessmentView from '../components/views/FunctionalAssessmentView';
import LGEAnalysisView from '../components/views/LGEAnalysisView';
import ImageAnalysisView from '../components/views/ImageAnalysisView';
import EvaluationView from '../components/views/EvaluationView';
import StructureAssessmentView from '../components/views/StructureAssessmentView';
import OtherFindingsView from '../components/views/OtherFindingsView';

interface CaseSummary {
  id: string;
  dataset: string;
  full_id: string;
  status: {
    functional: boolean;
    lge: boolean;
    analysis: boolean;
    evaluation: boolean;
    structure: boolean;
    other_findings: boolean;
  };
  has_report: boolean;
}

type ModuleType = 'functional' | 'lge' | 'analysis' | 'evaluation' | 'structure' | 'other-findings';

const PatientManagerPage: React.FC = () => {
  const { t } = useLanguage();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');

  const [selectedCase, setSelectedCase] = useState<CaseSummary | null>(null);
  const [selectedModule, setSelectedModule] = useState<ModuleType>('functional');

  // Sidebar State
  const [expandedCases, setExpandedCases] = useState<Set<string>>(new Set());

  const leftSidebar = useResizable({
    initialWidth: 220,
    minWidth: 150,
    maxWidth: 400,
    direction: 'right',
    storageKey: 'patient-manager-sidebar'
  });

  useEffect(() => {
    fetchCases();
  }, []);

  const fetchCases = async () => {
    setLoading(true);
    try {
      // Fetch cases from functional endpoint as master list
      const res = await fetch('/api/functional/cases');
      const data = await res.json();
      if (Array.isArray(data)) {
        setCases(data);
      } else {
        console.error("Cases data is not an array:", data);
        setCases([]);
      }
    } catch (err) {
      console.error("Failed to fetch cases", err);
    } finally {
      setLoading(false);
    }
  };

  const toggleExpand = (caseId: string) => {
    const newSet = new Set(expandedCases);
    if (newSet.has(caseId)) {
      newSet.delete(caseId);
    } else {
      newSet.add(caseId);
    }
    setExpandedCases(newSet);
  };

  const handleSelect = (c: CaseSummary, module: ModuleType) => {
    setSelectedCase(c);
    setSelectedModule(module);

    // Ensure it's expanded
    if (!expandedCases.has(c.full_id)) {
      const newSet = new Set(expandedCases);
      newSet.add(c.full_id);
      setExpandedCases(newSet);
    }
  };

  const handleSaveSuccess = (module: ModuleType) => {
    if (!selectedCase) return;
    setCases(prevCases => prevCases.map(c => {
      if (c.full_id === selectedCase.full_id) {
        const statusKey = module === 'other-findings' ? 'other_findings' : module;
        return {
          ...c,
          status: {
            ...c.status,
            [statusKey]: true
          }
        };
      }
      return c;
    }));
  };

  const renderModuleItem = (c: CaseSummary, module: ModuleType, label: string, icon: React.ReactNode) => {
    const isSelected = selectedCase?.full_id === c.full_id && selectedModule === module;
    const isDone = c.status[module === 'other-findings' ? 'other_findings' : module];

    return (
      <div
        onClick={(e) => {
          e.stopPropagation();
          handleSelect(c, module);
        }}
        style={{
          padding: '8px 16px 8px 32px',
          cursor: 'pointer',
          fontSize: '13px',
          color: isSelected ? 'var(--accent-gold)' : 'var(--text-secondary)',
          backgroundColor: isSelected ? 'rgba(217, 119, 6, 0.1)' : 'transparent',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '8px',
          transition: 'all 0.2s'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {icon}
          {label}
        </div>
        <span style={{ 
          fontSize: '11px', 
          padding: '2px 6px', 
          borderRadius: '4px',
          backgroundColor: isDone ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
          color: isDone ? '#10b981' : '#ef4444',
          border: `1px solid ${isDone ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)'}`
        }}>
          {isDone ? t('patient.completed') : t('patient.incomplete')}
        </span>
      </div>
    );
  };

  const filteredCases = cases.filter(c =>
    c.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
    c.dataset.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      {/* 1. Left Sidebar: Patient List */}
      <div style={{
        width: leftSidebar.width,
        backgroundColor: 'var(--bg-secondary)',
        borderRight: '1px solid var(--border-color)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
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
          <h3 style={{ margin: '0 0 16px 0', fontSize: '18px', color: 'var(--text-primary)' }}>{t('patient.manager')}</h3>
          <div style={{ position: 'relative' }}>
            <FaSearch style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-tertiary)' }} />
            <input
              type="text"
              placeholder={t('patient.search_placeholder')}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              style={{
                width: '100%',
                padding: '8px 8px 8px 32px',
                borderRadius: '4px',
                border: '1px solid var(--border-color)',
                backgroundColor: 'var(--bg-tertiary)',
                color: 'var(--text-primary)',
                fontSize: '14px'
              }}
            />
          </div>
        </div>

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {loading ? (
            <div style={{ padding: '16px', textAlign: 'center', color: 'var(--text-muted)' }}>{t('common.loading')}</div>
          ) : filteredCases.length === 0 ? (
            <div style={{ padding: '16px', textAlign: 'center', color: 'var(--text-muted)' }}>{t('patient.no_match')}</div>
          ) : (
            filteredCases.map(c => {
              const isExpanded = expandedCases.has(c.full_id);
              const isCaseSelected = selectedCase?.full_id === c.full_id;

              return (
                <div key={c.full_id} style={{ borderBottom: '1px solid var(--border-color)' }}>
                  <div
                    onClick={() => toggleExpand(c.full_id)}
                    style={{
                      padding: '12px 16px',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      backgroundColor: isCaseSelected ? 'rgba(255,255,255,0.02)' : 'transparent',
                      color: isCaseSelected ? 'var(--text-primary)' : 'var(--text-secondary)',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <FaUserMd style={{ color: isCaseSelected ? 'var(--accent-gold)' : 'var(--text-tertiary)' }} />
                      <div style={{ fontWeight: 500 }}>{c.id}</div>
                    </div>
                    {isExpanded ? <FaChevronDown size={12} /> : <FaChevronRight size={12} />}
                  </div>

                  {isExpanded && (
                    <div style={{ backgroundColor: 'rgba(0,0,0,0.1)', borderTop: '1px solid var(--border-color)' }}>
                      {renderModuleItem(c, 'analysis', t('sidebar.analysis'), <FaChartBar />)}
                      {/* {renderModuleItem(c, 'functional', t('sidebar.functional'), <FaFileAlt />)}
                      {renderModuleItem(c, 'structure', t('sidebar.structure'), <FaFileAlt />)}
                      {renderModuleItem(c, 'other-findings', t('sidebar.other_findings'), <FaFileAlt />)} */}
                      {renderModuleItem(c, 'lge', t('sidebar.lge'), <FaBrain />)}
                      {renderModuleItem(c, 'evaluation', t('sidebar.evaluation'), <FaCog />)}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* 2. Main Content Area */}
      <div style={{ flex: 1, height: '100%', overflow: 'hidden', position: 'relative' }}>
        {selectedCase ? (
          <>
            {selectedModule === 'analysis' && (
              <ImageAnalysisView dataset={selectedCase.dataset} caseId={selectedCase.id} onSaveSuccess={() => handleSaveSuccess('analysis')} showPhaseControls={false} />
            )}
            {selectedModule === 'functional' && (
              <FunctionalAssessmentView dataset={selectedCase.dataset} caseId={selectedCase.id} onSaveSuccess={() => handleSaveSuccess('functional')} showPhaseControls={false} />
            )}
            {selectedModule === 'structure' && (
              <StructureAssessmentView dataset={selectedCase.dataset} caseId={selectedCase.id} onSaveSuccess={() => handleSaveSuccess('structure')} showPhaseControls={false} />
            )}
            {selectedModule === 'other-findings' && (
              <OtherFindingsView dataset={selectedCase.dataset} caseId={selectedCase.id} onSaveSuccess={() => handleSaveSuccess('other-findings')} />
            )}
            {selectedModule === 'lge' && (
              <LGEAnalysisView dataset={selectedCase.dataset} caseId={selectedCase.id} onSaveSuccess={() => handleSaveSuccess('lge')} />
            )}
            {selectedModule === 'evaluation' && (
              <EvaluationView dataset={selectedCase.dataset} caseId={selectedCase.id} onSaveSuccess={() => handleSaveSuccess('evaluation')} />
            )}
          </>
        ) : (
          <div style={{
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
            alignItems: 'center',
            color: 'var(--text-muted)'
          }}>
            <FaUserMd size={48} style={{ marginBottom: '16px', opacity: 0.2 }} />
            <p>{t('patient.select_hint')}</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default PatientManagerPage;
