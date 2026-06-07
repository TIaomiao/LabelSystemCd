import React, { useState, useEffect } from 'react';
import { Spin, Button, Tooltip } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { 
  FaSearch, 
  FaFolder, 
  FaFolderOpen, 
  FaUserMd, 
  FaChevronRight, 
  FaChevronDown,
  FaFileAlt,
  FaBrain,
  FaChartBar,
  FaCog
} from 'react-icons/fa';
import { useResizable } from '../hooks/useResizable';
import { useLanguage } from '../context/LanguageContext';

// Import Views
import FunctionalAssessmentView from '../components/views/FunctionalAssessmentView';
import LGEAnalysisView from '../components/views/LGEAnalysisView';
import ImageAnalysisView from '../components/views/ImageAnalysisView';
import EvaluationView from '../components/views/EvaluationView';
import StructureAssessmentView from '../components/views/StructureAssessmentView';
import OtherFindingsView from '../components/views/OtherFindingsView';

// Types
interface PatientNode {
  name: string;
  dataset: string;
  caseId: string;
}

interface DiseaseNode {
  name: string;
  patients: PatientNode[];
}

interface HospitalNode {
  id: string;
  name: string;
  diseases: DiseaseNode[];
}

type ModuleType = 'functional' | 'lge' | 'analysis' | 'evaluation' | 'structure' | 'other-findings';

const CACHE_KEY = 'hospital_tree_data';

const HospitalDiseaseBrowserPage: React.FC = () => {
  const { t } = useLanguage();
  const [treeData, setTreeData] = useState<HospitalNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  
  // Selection State
  const [selectedCase, setSelectedCase] = useState<{ dataset: string; caseId: string } | null>(null);
  const [selectedModule, setSelectedModule] = useState<ModuleType>('analysis');

  // Expansion State (Stores IDs of expanded items)
  // Format: "hospital:ID", "disease:HospID|DiseaseName", "patient:HospID|DiseaseName|PatientID"
  const [expandedItems, setExpandedItems] = useState<Set<string>>(new Set());

  const sidebar = useResizable({
    initialWidth: 300,
    minWidth: 200,
    maxWidth: 500,
    direction: 'right',
    storageKey: 'hospital-browser-sidebar'
  });

  useEffect(() => {
    // 1. Try to load from local cache first
    const cached = localStorage.getItem(CACHE_KEY);
    if (cached) {
      try {
        const parsed = JSON.parse(cached);
        // Transform the raw data back if needed, or just use as is if structure matches
        // The API returns: { id, name, diseases: [{ name, patients: [], dataset }] }
        // We need to map patients strings to PatientNode objects if they are just strings
        const transformed = transformApiData(parsed);
        setTreeData(transformed);
      } catch (e) {
        console.error("Failed to parse cached tree data", e);
      }
    }
    
    // 2. Fetch fresh data
    fetchTreeData(!cached);
  }, []);

  const transformApiData = (data: any[]): HospitalNode[] => {
    if (!Array.isArray(data)) {
        console.error("Data is not an array:", data);
        return [];
    }
    return data.map((h: any) => ({
      id: h.id,
      name: h.name,
      diseases: h.diseases.map((d: any) => ({
        name: d.name,
        patients: Array.isArray(d.patients) 
          ? d.patients.map((p: string) => ({ name: p, dataset: d.dataset, caseId: p }))
          : []
      }))
    }));
  };

  const fetchTreeData = async (showLoading = true, forceRefresh = false) => {
    try {
      if (showLoading) setLoading(true);
      
      let url = '/api/hospital-browser/tree';
      if (forceRefresh) {
        url += '?refresh=true';
      }
      
      const res = await fetch(url);
      const rawData = await res.json();
      
      // Save raw data to cache
      localStorage.setItem(CACHE_KEY, JSON.stringify(rawData));
      
      const transformed = transformApiData(rawData);
      setTreeData(transformed);
      
    } catch (err) {
      console.error("Failed to fetch hospital tree", err);
    } finally {
      if (showLoading) setLoading(false);
    }
  };

  const handleRefresh = () => {
    fetchTreeData(true, true);
  };

  const toggleExpand = (id: string) => {
    const newSet = new Set(expandedItems);
    if (newSet.has(id)) {
      newSet.delete(id);
    } else {
      newSet.add(id);
    }
    setExpandedItems(newSet);
  };

  const handleSelectModule = (patient: PatientNode, module: ModuleType) => {
    setSelectedCase({ dataset: patient.dataset, caseId: patient.caseId });
    setSelectedModule(module);
  };

  // Helper to render module item (leaf)
  const renderModuleItem = (patient: PatientNode, module: ModuleType, label: string, icon: React.ReactNode) => {
    const isSelected = selectedCase?.caseId === patient.caseId && 
                       selectedCase?.dataset === patient.dataset && 
                       selectedModule === module;

    // Status is mocked for now as the tree API doesn't return status yet
    const isDone = false; 

    return (
      <div
        onClick={(e) => {
          e.stopPropagation();
          handleSelectModule(patient, module);
        }}
        style={{
          padding: '8px 16px 8px 48px', // Extra indentation
          cursor: 'pointer',
          fontSize: '13px',
          color: isSelected ? 'var(--accent-gold)' : 'var(--text-secondary)',
          backgroundColor: isSelected ? 'rgba(217, 119, 6, 0.1)' : 'transparent',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '8px',
          transition: 'all 0.2s',
          borderLeft: isSelected ? '3px solid var(--accent-gold)' : '3px solid transparent'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {icon}
          {label}
        </div>
        {/* Status Badge (Optional/Mocked) */}
        {/* <span style={{ 
          fontSize: '10px', 
          padding: '1px 4px', 
          borderRadius: '4px',
          backgroundColor: isDone ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
          color: isDone ? '#10b981' : '#ef4444',
          border: `1px solid ${isDone ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)'}`
        }}>
          {isDone ? t('patient.completed') : t('patient.incomplete')}
        </span> */}
      </div>
    );
  };

  // Recursive rendering logic
  const renderTree = () => {
    if (loading && treeData.length === 0) {
      return <div style={{ padding: '20px', textAlign: 'center' }}><Spin /></div>;
    }

    return treeData.map(hospital => {
      const hospKey = `hospital:${hospital.id}`;
      const isHospExpanded = expandedItems.has(hospKey);
      
      // Filter logic could go here if searchTerm exists
      
      return (
        <div key={hospKey}>
          {/* Hospital Node */}
          <div 
            onClick={() => toggleExpand(hospKey)}
            style={{
              padding: '12px 16px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              fontWeight: 600,
              color: 'var(--text-primary)',
              backgroundColor: 'var(--bg-secondary)',
              borderBottom: '1px solid var(--border-color)'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              {isHospExpanded ? <FaFolderOpen color="var(--accent-gold)" /> : <FaFolder color="var(--text-tertiary)" />}
              {hospital.name}
            </div>
            {isHospExpanded ? <FaChevronDown size={10} /> : <FaChevronRight size={10} />}
          </div>

          {/* Disease List */}
          {isHospExpanded && hospital.diseases.map(disease => {
            const disKey = `disease:${hospital.id}|${disease.name}`;
            const isDisExpanded = expandedItems.has(disKey);
            
            return (
              <div key={disKey}>
                {/* Disease Node */}
                <div 
                  onClick={() => toggleExpand(disKey)}
                  style={{
                    padding: '10px 16px 10px 24px', // Indent
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    color: 'var(--text-primary)',
                    borderBottom: '1px solid var(--border-color)',
                    backgroundColor: 'rgba(0,0,0,0.02)'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    {isDisExpanded ? <FaFolderOpen size={14} color="#888" /> : <FaFolder size={14} color="#888" />}
                    <span style={{ fontSize: '14px' }}>{disease.name}</span>
                    <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>({disease.patients.length})</span>
                  </div>
                  {isDisExpanded ? <FaChevronDown size={10} /> : <FaChevronRight size={10} />}
                </div>

                {/* Patient List */}
                {isDisExpanded && disease.patients.map(patient => {
                  const patKey = `patient:${hospital.id}|${disease.name}|${patient.caseId}`;
                  const isPatExpanded = expandedItems.has(patKey);
                  const isPatSelected = selectedCase?.caseId === patient.caseId && selectedCase?.dataset === patient.dataset;

                  // Simple filter match
                  if (searchTerm && !patient.caseId.toLowerCase().includes(searchTerm.toLowerCase())) {
                    return null;
                  }

                  return (
                    <div key={patKey} style={{ borderBottom: '1px solid var(--border-color)' }}>
                      {/* Patient Node */}
                      <div
                        onClick={() => toggleExpand(patKey)}
                        style={{
                          padding: '10px 16px 10px 32px', // Indent
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          backgroundColor: isPatSelected ? 'rgba(255,255,255,0.05)' : 'transparent',
                          color: isPatSelected ? 'var(--text-primary)' : 'var(--text-secondary)',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <FaUserMd style={{ color: isPatSelected ? 'var(--accent-gold)' : 'var(--text-tertiary)' }} />
                          <div style={{ fontWeight: 500, fontSize: '13px' }}>{patient.name}</div>
                        </div>
                        {isPatExpanded ? <FaChevronDown size={10} /> : <FaChevronRight size={10} />}
                      </div>

                      {/* Modules (Leaf Nodes) */}
                      {isPatExpanded && (
                        <div style={{ backgroundColor: 'rgba(0,0,0,0.03)', paddingBottom: '4px' }}>
                          {renderModuleItem(patient, 'analysis', t('sidebar.analysis'), <FaChartBar />)}
                          {renderModuleItem(patient, 'functional', t('sidebar.functional'), <FaFileAlt />)}
                          {renderModuleItem(patient, 'structure', t('sidebar.structure'), <FaFileAlt />)}
                          {renderModuleItem(patient, 'other-findings', t('sidebar.other_findings'), <FaFileAlt />)}
                          {renderModuleItem(patient, 'lge', t('sidebar.lge'), <FaBrain />)}
                          {renderModuleItem(patient, 'evaluation', t('sidebar.evaluation'), <FaCog />)}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      );
    });
  };

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      {/* Sidebar */}
      <div 
        style={{ 
          width: sidebar.width,
          backgroundColor: 'var(--bg-secondary)',
          borderRight: '1px solid var(--border-color)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          position: 'relative',
          flexShrink: 0,
        }}
      >
        {/* Resize Handle */}
        <div
          onMouseDown={sidebar.startResizing}
          style={{
            position: 'absolute',
            top: 0,
            right: -2,
            width: '5px',
            height: '100%',
            cursor: 'col-resize',
            zIndex: 10,
            backgroundColor: sidebar.isResizing ? 'var(--accent-gold)' : 'transparent',
            transition: 'background-color 0.2s',
          }}
        />

        <div style={{ padding: '16px', borderBottom: '1px solid var(--border-color)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
             <h3 style={{ margin: '0', fontSize: '18px', color: 'var(--text-primary)' }}>{t('sidebar.hospital_browser')}</h3>
             <Tooltip title={t('common.refresh')}>
                <Button 
                  type="text" 
                  icon={<ReloadOutlined spin={loading} />} 
                  onClick={handleRefresh} 
                  size="small"
                  style={{ color: 'var(--text-secondary)' }}
                />
             </Tooltip>
          </div>
          
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
          {renderTree()}
        </div>
      </div>
      
      {/* Main Content */}
      <div style={{ flex: 1, overflow: 'hidden', backgroundColor: 'var(--bg-primary)', display: 'flex', flexDirection: 'column' }}>
        {selectedCase ? (
          <div style={{ flex: 1, overflow: 'hidden', position: 'relative' }}>
            {selectedModule === 'analysis' && (
              <ImageAnalysisView dataset={selectedCase.dataset} caseId={selectedCase.caseId} showPhaseControls={false} />
            )}
            {selectedModule === 'functional' && (
              <FunctionalAssessmentView dataset={selectedCase.dataset} caseId={selectedCase.caseId} showPhaseControls={false} />
            )}
            {selectedModule === 'structure' && (
              <StructureAssessmentView dataset={selectedCase.dataset} caseId={selectedCase.caseId} showPhaseControls={false} />
            )}
            {selectedModule === 'other-findings' && (
              <OtherFindingsView dataset={selectedCase.dataset} caseId={selectedCase.caseId} />
            )}
            {selectedModule === 'lge' && (
              <LGEAnalysisView dataset={selectedCase.dataset} caseId={selectedCase.caseId} />
            )}
            {selectedModule === 'evaluation' && (
              <EvaluationView dataset={selectedCase.dataset} caseId={selectedCase.caseId} />
            )}
          </div>
        ) : (
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', color: 'var(--text-tertiary)', flexDirection: 'column' }}>
            <FaUserMd size={48} style={{ marginBottom: '16px', opacity: 0.2 }} />
            <p>Select a patient module from the sidebar</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default HospitalDiseaseBrowserPage;
