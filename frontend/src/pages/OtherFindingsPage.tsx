import React, { useState, useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { FaSave, FaChevronRight, FaChevronDown, FaRuler, FaChevronLeft } from 'react-icons/fa';
import { message } from 'antd';
import { useResizable } from '../hooks/useResizable';
import { useLanguage } from '../context/LanguageContext';
import MeasurementViewer from '../components/MeasurementViewer';
import OtherFindingsView from '../components/views/OtherFindingsView';

interface CaseSummary {
  id: string;
  dataset: string;
  full_id: string;
  status?: {
    other_findings: boolean;
  };
}

const OtherFindingsPage: React.FC = () => {
  const { t } = useLanguage();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [selectedCase, setSelectedCase] = useState<CaseSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [isExpanded, setIsExpanded] = useState(true);
  
  const location = useLocation();
  
  // Search State
  const [searchTerm, setSearchTerm] = useState('');

  // Resizable Sidebars
  const leftSidebar = useResizable({
    initialWidth: 280,
    minWidth: 200,
    maxWidth: 500,
    direction: 'right',
    storageKey: 'other-findings-left-sidebar'
  });

  useEffect(() => {
    fetchCases();
  }, []);

  const fetchCases = async () => {
    try {
      const res = await fetch('/api/other-findings/cases');
      if (!res.ok) {
        throw new Error(`HTTP error! status: ${res.status}`);
      }
      const data = await res.json();
      if (Array.isArray(data)) {
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
      } else {
        console.error("Fetched data is not an array:", data);
        message.error("Failed to load cases: Invalid data format");
        setCases([]);
      }
    } catch (err) {
      console.error("Failed to fetch cases", err);
      message.error("Failed to load cases");
      setCases([]);
    }
  };

  const handleCaseClick = (c: CaseSummary) => {
    if (selectedCase?.full_id === c.full_id) {
      setIsExpanded(!isExpanded);
    } else {
      setSelectedCase(c);
      setIsExpanded(true);
    }
  };

  const filteredCases = cases.filter(c => 
    c.id.toLowerCase().includes(searchTerm.toLowerCase()) || 
    c.dataset.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      {/* Left Sidebar: Case List */}
      <div style={{ 
        width: leftSidebar.width, 
        borderRight: '1px solid var(--border-color)', 
        display: 'flex', 
        flexDirection: 'column',
        backgroundColor: 'var(--bg-secondary)',
        position: 'relative',
        flexShrink: 0
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
            }}
        />

        {/* Search Header */}
        <div style={{ padding: '16px', borderBottom: '1px solid var(--border-color)' }}>
          <div style={{ marginBottom: '12px', fontWeight: 'bold', color: 'var(--text-primary)' }}>
            {t('sidebar.other_findings')}
          </div>
          <input
            type="text"
            placeholder={t('common.search')}
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

        {/* Case List */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {filteredCases.map(c => (
            <div
              key={c.full_id}
              onClick={() => handleCaseClick(c)}
              style={{
                padding: '12px 16px',
                cursor: 'pointer',
                backgroundColor: selectedCase?.full_id === c.full_id ? 'rgba(217, 119, 6, 0.1)' : 'transparent',
                borderLeft: selectedCase?.full_id === c.full_id ? '3px solid var(--accent-gold)' : '3px solid transparent',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center'
              }}
            >
              <div>
                <div style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{c.id}</div>
                <div style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>{c.dataset}</div>
              </div>
              <div style={{ 
                width: '10px', 
                height: '10px', 
                borderRadius: '50%', 
                backgroundColor: c.status?.other_findings ? 'var(--success-color)' : 'var(--border-color)'
              }} />
            </div>
          ))}
        </div>
      </div>

      {/* Main Content */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {selectedCase ? (
            <OtherFindingsView 
                dataset={selectedCase.dataset} 
                caseId={selectedCase.id} 
            />
        ) : (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', color: 'var(--text-tertiary)' }}>
                {t('common.select_case')}
            </div>
        )}
      </div>
    </div>
  );
};

export default OtherFindingsPage;
