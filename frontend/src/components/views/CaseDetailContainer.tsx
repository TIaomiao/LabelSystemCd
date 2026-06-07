import React, { useState } from 'react';
import { useLanguage } from '../../context/LanguageContext';
import ImageAnalysisView from './ImageAnalysisView';
import FunctionalAssessmentView from './FunctionalAssessmentView';
import StructureAssessmentView from './StructureAssessmentView';
import LGEAnalysisView from './LGEAnalysisView';
import OtherFindingsView from './OtherFindingsView';
import EvaluationView from './EvaluationView';
import '../styles/ResourceTabs.css';

interface CaseDetailContainerProps {
  dataset: string;
  caseId: string;
}

const CaseDetailContainer: React.FC<CaseDetailContainerProps> = ({ dataset, caseId }) => {
  const { t } = useLanguage();
  const [activeTab, setActiveTab] = useState('image-analysis');

  const items = [
    {
      key: 'image-analysis',
      label: 'Image Analysis',
      component: ImageAnalysisView,
    },
    {
      key: 'functional-assessment',
      label: 'Functional Assessment',
      component: FunctionalAssessmentView,
    },
    {
      key: 'structure-assessment',
      label: 'Structure Assessment',
      component: StructureAssessmentView,
    },
    {
      key: 'lge-analysis',
      label: 'LGE Analysis',
      component: LGEAnalysisView,
    },
    {
      key: 'other-findings',
      label: 'Other Findings',
      component: OtherFindingsView,
    },
    {
      key: 'report-scoring',
      label: 'Report Scoring',
      component: EvaluationView,
    },
  ];

  const renderActiveContent = () => {
    const activeItem = items.find(item => item.key === activeTab);
    if (!activeItem) return null;
    const Component = activeItem.component;
    return (
        <div style={{ height: '100%', overflow: 'auto' }}>
            <Component dataset={dataset} caseId={caseId} showPhaseControls={false} />
        </div>
    );
  };

  return (
    <div className="case-detail-container" style={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--bg-primary)' }}>
      <div style={{ padding: '16px 24px', borderBottom: '1px solid var(--border-color)', backgroundColor: 'var(--bg-secondary)' }}>
        <h2 style={{ margin: '0 0 8px 0', fontSize: '18px', color: 'var(--text-primary)' }}>Case: {caseId}</h2>
        <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Dataset: {dataset}</div>
      </div>
      
      <div className="resource-tabs" style={{ flex: 1, overflow: 'hidden', border: 'none', borderRadius: 0, display: 'flex', flexDirection: 'column' }}>
        <div className="tabs-header" style={{ padding: '0 16px', backgroundColor: 'var(--bg-tertiary)' }}>
            {items.map(item => (
                <button 
                    key={item.key}
                    className={`tab-button ${activeTab === item.key ? 'active' : ''}`}
                    onClick={() => setActiveTab(item.key)}
                >
                    {item.label}
                </button>
            ))}
        </div>
        <div className="tabs-content" style={{ flex: 1, padding: 0, overflow: 'hidden' }}>
            {renderActiveContent()}
        </div>
      </div>
    </div>
  );
};

export default CaseDetailContainer;
