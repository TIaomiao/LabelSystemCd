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
  source_count: number;
  available_count: number;
}

interface HospitalNode {
  id: string;
  name: string;
  dataset?: string;
  source_count: number;
  available_count: number;
  diseases: DiseaseNode[];
}

interface HospitalInventoryItem {
  dataset: string;
  label: string;
  raw_candidate_count: number;
  raw_count_basis: string;
  catalog_count: number;
  dicom_case_count: number;
  imported_count: number;
  classified_output_count: number;
  classification_status: string;
  classification_label: string;
  classification_category_count: number;
  access_status: string;
  access_label: string;
}

interface HospitalInventory {
  items: HospitalInventoryItem[];
  totals: {
    datasets: number;
    raw_candidates: number;
    catalog: number;
    imported: number;
    classified_output: number;
  };
  count_definitions: Record<string, string>;
}

type ModuleType = 'functional' | 'lge' | 'analysis' | 'evaluation' | 'structure' | 'other-findings';

const CACHE_KEY = 'hospital_tree_data_v2';

const HospitalDiseaseBrowserPage: React.FC = () => {
  const { t } = useLanguage();
  const [treeData, setTreeData] = useState<HospitalNode[]>([]);
  const [inventory, setInventory] = useState<HospitalInventory | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
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
      dataset: h.dataset,
      source_count: Number(h.source_count || 0),
      available_count: Number(h.available_count || 0),
      diseases: h.diseases.map((d: any) => ({
        name: d.name,
        source_count: Number(d.source_count ?? d.patients?.length ?? 0),
        available_count: Number(d.available_count ?? d.patients?.length ?? 0),
        patients: Array.isArray(d.patients) 
          ? d.patients.map((p: string) => ({ name: p, dataset: d.dataset, caseId: p }))
          : []
      }))
    }));
  };

  const fetchTreeData = async (showLoading = true, forceRefresh = false) => {
    try {
      if (showLoading) setLoading(true);
      setError('');
      
      let url = '/api/hospital-browser/tree';
      if (forceRefresh) {
        url += '?refresh=true';
      }
      
      const [treeResponse, inventoryResponse] = await Promise.all([
        fetch(url),
        fetch('/api/hospital-browser/inventory'),
      ]);
      const rawData = await treeResponse.json();
      const inventoryData = await inventoryResponse.json();
      if (!treeResponse.ok) throw new Error(rawData.error || '医院分类树加载失败');
      if (!inventoryResponse.ok) throw new Error(inventoryData.error || '多中心接入统计加载失败');
      
      // Save raw data to cache
      localStorage.setItem(CACHE_KEY, JSON.stringify(rawData));
      
      const transformed = transformApiData(rawData);
      setTreeData(transformed);
      setInventory(inventoryData);
      
    } catch (err) {
      console.error("Failed to fetch hospital tree", err);
      setError(err instanceof Error ? err.message : '医院数据加载失败');
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

  const inventoryByDataset = new Map((inventory?.items || []).map(item => [item.dataset, item]));

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
      const hospitalInventory = hospital.dataset ? inventoryByDataset.get(hospital.dataset) : undefined;
      
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
            <div style={{ minWidth: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              {isHospExpanded ? <FaFolderOpen color="var(--accent-gold)" /> : <FaFolder color="var(--text-tertiary)" />}
              <div style={{ minWidth: 0 }}>
                <div>{hospital.name}</div>
                <div style={{ marginTop: 3, color: 'var(--text-tertiary)', fontSize: 11, fontWeight: 400 }}>
                  目录 {hospitalInventory?.catalog_count ?? '-'} · 已导入 {hospitalInventory?.imported_count ?? '-'} · 可浏览 {hospital.available_count}
                </div>
              </div>
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
                    <div>
                      <div style={{ fontSize: '14px' }}>{disease.name}</div>
                      <div style={{ marginTop: 2, fontSize: '11px', color: 'var(--text-muted)' }}>
                        清单 {disease.source_count} · 当前可浏览 {disease.available_count}
                      </div>
                    </div>
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

  const renderInventoryOverview = () => {
    if (loading && !inventory) {
      return <div style={{ height: '100%', display: 'grid', placeItems: 'center' }}><Spin /></div>;
    }
    if (!inventory) {
      return <div style={{ padding: 24, color: 'var(--text-secondary)' }}>暂无多中心接入统计。</div>;
    }
    const summaryItems = [
      ['数据中心', inventory.totals.datasets],
      ['原始候选 Study', inventory.totals.raw_candidates],
      ['工作站已登记', inventory.totals.catalog],
      ['已导入 CVI', inventory.totals.imported],
      ['分类 output 目录', inventory.totals.classified_output],
    ];
    return (
      <div style={{ height: '100%', overflow: 'auto', padding: '22px 24px 36px' }}>
        <div style={{ marginBottom: 16 }}>
          <h2 style={{ margin: 0, color: 'var(--text-primary)', fontSize: 22 }}>多中心数据接入总览</h2>
          <p style={{ margin: '6px 0 0', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
            四个数字使用不同口径：原始候选、工作站目录、CVI 实际导入和医院分类输出不能相互替代。
          </p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10, marginBottom: 16 }}>
          {summaryItems.map(([label, value]) => (
            <div key={String(label)} style={{ padding: '12px 14px', border: '1px solid var(--border-color)', borderRadius: 6, background: 'var(--bg-secondary)' }}>
              <div style={{ color: 'var(--text-secondary)', fontSize: 12 }}>{label}</div>
              <strong style={{ display: 'block', marginTop: 5, color: 'var(--text-primary)', fontSize: 24 }}>{value}</strong>
            </div>
          ))}
        </div>

        <div style={{ overflowX: 'auto', border: '1px solid var(--border-color)', borderRadius: 6 }}>
          <table style={{ width: '100%', minWidth: 980, borderCollapse: 'collapse', background: 'var(--bg-secondary)' }}>
            <thead>
              <tr style={{ background: 'var(--bg-tertiary)' }}>
                {['数据中心', '原始候选', '工作站已登记', '已导入 CVI', '分类 output 目录', '病种分类', '当前接入状态'].map(label => (
                  <th key={label} style={{ padding: '11px 12px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-secondary)', textAlign: 'left', whiteSpace: 'nowrap' }}>{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {inventory.items.map(item => (
                <tr key={item.dataset}>
                  <td style={inventoryCellStyle}><strong>{item.label}</strong><div style={inventoryMetaStyle}>{item.dataset}</div></td>
                  <td style={inventoryCellStyle}>{item.raw_candidate_count}<div style={inventoryMetaStyle}>{item.raw_count_basis}</div></td>
                  <td style={inventoryCellStyle}>{item.catalog_count}<div style={inventoryMetaStyle}>其中 DICOM {item.dicom_case_count}</div></td>
                  <td style={inventoryCellStyle}>{item.imported_count}</td>
                  <td style={inventoryCellStyle}>{item.classified_output_count}</td>
                  <td style={inventoryCellStyle}>{item.classification_label}</td>
                  <td style={inventoryCellStyle}>
                    <span style={{ ...inventoryStatusStyle, ...(item.access_status === 'browsable' ? inventoryStatusOkStyle : inventoryStatusPendingStyle) }}>{item.access_label}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div style={{ marginTop: 16, padding: '12px 14px', borderLeft: '3px solid var(--accent-gold)', background: 'var(--bg-secondary)', color: 'var(--text-secondary)', lineHeight: 1.75 }}>
          <strong style={{ color: 'var(--text-primary)' }}>计数口径</strong>
          {Object.entries(inventory.count_definitions).map(([key, value]) => <div key={key}>{value}</div>)}
        </div>
      </div>
    );
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
          <button
            type="button"
            onClick={() => setSelectedCase(null)}
            style={{
              width: '100%',
              marginTop: 10,
              padding: '8px 10px',
              border: '1px solid var(--border-color)',
              borderRadius: 4,
              color: selectedCase ? 'var(--text-secondary)' : 'var(--accent-gold)',
              background: selectedCase ? 'transparent' : 'rgba(217, 119, 6, 0.08)',
              cursor: 'pointer',
              textAlign: 'left',
              fontWeight: 600,
            }}
          >
            多中心接入总览
          </button>
          {error && <div style={{ marginTop: 10, color: 'var(--error-color)', fontSize: 12 }}>{error}</div>}
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
          renderInventoryOverview()
        )}
      </div>
    </div>
  );
};

const inventoryCellStyle: React.CSSProperties = {
  padding: '11px 12px',
  borderBottom: '1px solid var(--border-color)',
  color: 'var(--text-primary)',
  verticalAlign: 'top',
};

const inventoryMetaStyle: React.CSSProperties = {
  marginTop: 3,
  color: 'var(--text-tertiary)',
  fontSize: 11,
};

const inventoryStatusStyle: React.CSSProperties = {
  display: 'inline-flex',
  padding: '3px 7px',
  borderRadius: 4,
  border: '1px solid var(--border-color)',
  fontSize: 12,
  whiteSpace: 'nowrap',
};

const inventoryStatusOkStyle: React.CSSProperties = {
  color: '#4f7d31',
  borderColor: 'rgba(79, 125, 49, 0.35)',
  background: 'rgba(79, 125, 49, 0.08)',
};

const inventoryStatusPendingStyle: React.CSSProperties = {
  color: 'var(--accent-gold)',
  borderColor: 'rgba(217, 119, 6, 0.35)',
  background: 'rgba(217, 119, 6, 0.08)',
};

export default HospitalDiseaseBrowserPage;
