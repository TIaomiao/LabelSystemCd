import React, { useState, useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { FaSave, FaChevronLeft, FaChevronRight } from 'react-icons/fa';
import { message, Radio, Checkbox, Input, Space, Divider } from 'antd';
import { useResizable } from '../hooks/useResizable';
import { useLanguage } from '../context/LanguageContext';

interface CaseSummary {
  id: string;
  dataset: string;
  full_id: string;
}

interface CaseDetail {
  id: string;
  dataset: string;
  images: {
    'LGE': string[];
  };
  assessment?: any;
}

const LGEAnalysisPage: React.FC = () => {
  const { t } = useLanguage();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [selectedCase, setSelectedCase] = useState<CaseSummary | null>(null);
  const [caseDetail, setCaseDetail] = useState<CaseDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [currentImageIndex, setCurrentImageIndex] = useState(0);
  
  const location = useLocation();

  // Search State
  const [searchTerm, setSearchTerm] = useState('');

  // Form State
  const [formData, setFormData] = useState<any>({});

  const viewerRef = useRef<HTMLDivElement>(null);

  const leftSidebar = useResizable({
    initialWidth: 250,
    minWidth: 200,
    maxWidth: 500,
    direction: 'right',
    storageKey: 'lge-left-sidebar'
  });

  const rightSidebar = useResizable({
    initialWidth: 350,
    minWidth: 300,
    maxWidth: 600,
    direction: 'left',
    storageKey: 'lge-right-sidebar'
  });

  useEffect(() => {
    fetchCases();
  }, []);

  useEffect(() => {
    if (selectedCase) {
      fetchCaseDetail(selectedCase.dataset, selectedCase.id);
    }
  }, [selectedCase]);

  // Reset state when case changes
  useEffect(() => {
    setCurrentImageIndex(0);
  }, [caseDetail]);

  const fetchCases = async () => {
    try {
      const res = await fetch('/api/lge/cases');
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

  const fetchCaseDetail = async (dataset: string, id: string) => {
    setLoading(true);
    setFormData({}); // Reset form
    try {
      const res = await fetch(`/api/lge/cases/${dataset}/${id}`);
      const data = await res.json();
      setCaseDetail(data);
      
      if (data.assessment && data.assessment.answers) {
        setFormData(data.assessment.answers);
      }
    } catch (err) {
      console.error("Failed to fetch case detail", err);
    } finally {
      setLoading(false);
    }
  };

  const handleInputChange = (key: string, value: any) => {
    setFormData((prev: any) => ({
      ...prev,
      [key]: value
    }));
  };

  const handleSubmit = async () => {
    if (!selectedCase) return;
    
    try {
      const res = await fetch(`/api/lge/cases/${selectedCase.dataset}/${selectedCase.id}/assessment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      });
      const data = await res.json();
      if (data.status === 'success') {
        message.success('保存成功');
      } else {
        message.error('保存失败: ' + data.error);
      }
    } catch (err) {
      message.error('保存失败');
    }
  };

  const handleWheel = (e: React.WheelEvent) => {
    if (!caseDetail || !caseDetail.images['LGE'] || caseDetail.images['LGE'].length === 0) return;
    
    const count = caseDetail.images['LGE'].length;
    if (e.deltaY > 0) {
      setCurrentImageIndex(prev => Math.min(prev + 1, count - 1));
    } else {
      setCurrentImageIndex(prev => Math.max(prev - 1, 0));
    }
  };

  const handleNextImage = () => {
    if (!caseDetail || !caseDetail.images['LGE'] || caseDetail.images['LGE'].length === 0) return;
    const count = caseDetail.images['LGE'].length;
    setCurrentImageIndex(prev => Math.min(prev + 1, count - 1));
  };

  const handlePrevImage = () => {
    setCurrentImageIndex(prev => Math.max(prev - 1, 0));
  };

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      {/* 1. Case List Column */}
      <div style={{
        width: sidebarOpen ? leftSidebar.width : '0',
        backgroundColor: 'var(--bg-secondary)',
        borderRight: '1px solid var(--border-color)',
        transition: 'width 0.3s ease',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        position: 'relative',
        flexShrink: 0
      }}>
        {/* Resize Handle */}
        {sidebarOpen && (
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
        )}

        <div style={{ padding: '16px', borderBottom: '1px solid var(--border-color)', fontWeight: 'bold' }}>
          {t('sidebar.patient_list')} ({cases.length})
        </div>
        
        {/* Search Input */}
        <div style={{ padding: '16px 16px 0 16px' }}>
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
                    backgroundColor: 'var(--bg-tertiary)',
                    color: 'var(--text-primary)',
                    fontSize: '14px'
                }}
            />
        </div>

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {cases.filter(c => c.id.toLowerCase().includes(searchTerm.toLowerCase())).map(c => (
            <div
              key={c.full_id}
              onClick={() => setSelectedCase(c)}
              style={{
                padding: '12px 16px',
                cursor: 'pointer',
                backgroundColor: selectedCase?.full_id === c.full_id ? 'rgba(217, 119, 6, 0.1)' : 'transparent',
                borderLeft: selectedCase?.full_id === c.full_id ? '3px solid var(--accent-gold)' : '3px solid transparent',
                fontSize: '14px',
                color: 'var(--text-secondary)'
              }}
            >
              <div style={{ fontWeight: 500 }}>{c.id}</div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{c.dataset}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Toggle Button */}
      <div 
        onClick={() => setSidebarOpen(!sidebarOpen)}
        style={{
          position: 'absolute',
          left: sidebarOpen ? leftSidebar.width : '0',
          top: '50%',
          transform: 'translateY(-50%)',
          zIndex: 10,
          backgroundColor: 'var(--bg-secondary)',
          border: '1px solid var(--border-color)',
          borderLeft: 'none',
          borderRadius: '0 4px 4px 0',
          padding: '8px 4px',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          transition: 'left 0.3s ease'
        }}
      >
        {sidebarOpen ? <FaChevronLeft size={12} /> : <FaChevronRight size={12} />}
      </div>

      {/* 2. Main Image Viewer */}
      <div 
        ref={viewerRef}
        onWheel={handleWheel}
        style={{ 
          flex: 1, 
          backgroundColor: '#000', 
          display: 'flex', 
          flexDirection: 'column', 
          justifyContent: 'center', 
          alignItems: 'center',
          position: 'relative',
          overflow: 'hidden'
        }}
      >
        {loading ? (
          <div style={{ color: 'white' }}>加载中...</div>
        ) : caseDetail && caseDetail.images['LGE']?.length > 0 ? (
          <>
             <div style={{ 
               position: 'absolute', 
               top: '10px', 
               left: '10px', 
               color: 'white', 
               backgroundColor: 'rgba(0,0,0,0.5)', 
               padding: '4px 8px', 
               borderRadius: '4px',
               fontSize: '12px',
               zIndex: 5
             }}>
               LGE - {currentImageIndex + 1} / {caseDetail.images['LGE'].length}
             </div>
             
             {/* Navigation Arrows */}
             <div 
               onClick={(e) => { e.stopPropagation(); handlePrevImage(); }}
               style={{
                 position: 'absolute',
                 left: '10px',
                 top: '50%',
                 transform: 'translateY(-50%)',
                 color: 'white',
                 fontSize: '30px',
                 cursor: 'pointer',
                 zIndex: 100,
                 opacity: 0.7,
                 background: 'rgba(0,0,0,0.3)',
                 borderRadius: '50%',
                 width: '40px',
                 height: '40px',
                 display: 'flex',
                 alignItems: 'center',
                 justifyContent: 'center',
                 transition: 'all 0.2s'
               }}
               onMouseEnter={(e) => e.currentTarget.style.opacity = '1'}
               onMouseLeave={(e) => e.currentTarget.style.opacity = '0.7'}
             >
               <FaChevronLeft />
             </div>
             
             <div 
               onClick={(e) => { e.stopPropagation(); handleNextImage(); }}
               style={{
                 position: 'absolute',
                 right: '10px',
                 top: '50%',
                 transform: 'translateY(-50%)',
                 color: 'white',
                 fontSize: '30px',
                 cursor: 'pointer',
                 zIndex: 100,
                 opacity: 0.7,
                 background: 'rgba(0,0,0,0.3)',
                 borderRadius: '50%',
                 width: '40px',
                 height: '40px',
                 display: 'flex',
                 alignItems: 'center',
                 justifyContent: 'center',
                 transition: 'all 0.2s'
               }}
               onMouseEnter={(e) => e.currentTarget.style.opacity = '1'}
               onMouseLeave={(e) => e.currentTarget.style.opacity = '0.7'}
             >
               <FaChevronRight />
             </div>

             <img 
               src={`/api/functional/images/${caseDetail.dataset}/${caseDetail.id}/${caseDetail.images['LGE'][currentImageIndex]}`}
               alt="LGE"
               draggable={false}
               onContextMenu={(event) => event.preventDefault()}
               style={{
                 maxWidth: '100%',
                 maxHeight: '100%',
                 objectFit: 'contain'
               }}
             />
          </>
        ) : (
          <div style={{ color: '#666' }}>无 LGE 影像数据</div>
        )}
      </div>

      {/* 3. Right Sidebar - Questionnaire */}
      <div style={{
        width: rightSidebar.width,
        backgroundColor: 'var(--bg-secondary)',
        borderLeft: '1px solid var(--border-color)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        position: 'relative',
        flexShrink: 0
      }}>
         {/* Resize Handle */}
         <div
             onMouseDown={rightSidebar.startResizing}
             style={{
                 position: 'absolute',
                 top: 0,
                 left: -2,
                 width: '5px',
                 height: '100%',
                 cursor: 'col-resize',
                 zIndex: 10,
                 backgroundColor: rightSidebar.isResizing ? 'var(--accent-gold)' : 'transparent',
                 transition: 'background-color 0.2s',
             }}
         />

        <div style={{ padding: '16px', borderBottom: '1px solid var(--border-color)', fontWeight: 'bold', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>LGE 分析</span>
          <button 
            onClick={handleSubmit}
            style={{
              backgroundColor: 'var(--accent-gold)',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              padding: '6px 12px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '12px'
            }}
          >
            <FaSave /> {t('common.save')}
          </button>
        </div>
        
        <div style={{ flex: 1, overflowY: 'auto', padding: '16px' }}>
            
            {/* LV Section */}
            <div style={{ fontWeight: 'bold', marginBottom: '12px', color: 'var(--text-primary)' }}>左心室 LV</div>
            <div style={{ marginBottom: '16px' }}>
              <Radio.Group onChange={e => handleInputChange('lv_enhancement', e.target.value)} value={formData['lv_enhancement']}>
                <Radio value={false}>无强化</Radio>
                <Radio value={true}>有强化</Radio>
              </Radio.Group>
            </div>

            {formData['lv_enhancement'] === true && (
              <div style={{ marginLeft: '16px', borderLeft: '2px solid var(--border-color)', paddingLeft: '12px' }}>
                <div style={{ marginBottom: '12px' }}>
                  <div style={{ marginBottom: '4px', fontSize: '13px' }}>强化部位 - 节段:</div>
                  <Input 
                    placeholder="输入具体节段" 
                    value={formData['lv_enhancement_segments']} 
                    onChange={e => handleInputChange('lv_enhancement_segments', e.target.value)}
                  />
                </div>
                
                <div style={{ marginBottom: '12px' }}>
                   <div style={{ marginBottom: '4px', fontSize: '13px' }}>强化部位 - 插入点:</div>
                   <Checkbox 
                     checked={formData['lv_enhancement_anterior_insertion']} 
                     onChange={e => handleInputChange('lv_enhancement_anterior_insertion', e.target.checked)}
                   >
                     前插入点
                   </Checkbox>
                   <Checkbox 
                     checked={formData['lv_enhancement_posterior_insertion']} 
                     onChange={e => handleInputChange('lv_enhancement_posterior_insertion', e.target.checked)}
                   >
                     后插入点
                   </Checkbox>
                </div>

                <div style={{ marginBottom: '12px' }}>
                  <div style={{ marginBottom: '4px', fontSize: '13px' }}>分布模式:</div>
                  <Radio.Group onChange={e => handleInputChange('lv_distribution_pattern', e.target.value)} value={formData['lv_distribution_pattern']}>
                    <Space direction="vertical">
                      <Radio value="subendocardial">心内膜下</Radio>
                      <Radio value="mid_myocardial">心肌中层</Radio>
                      <Radio value="subepicardial">心外膜下</Radio>
                    </Space>
                  </Radio.Group>
                </div>

                <div style={{ marginBottom: '12px' }}>
                  <div style={{ marginBottom: '4px', fontSize: '13px' }}>LGE 平均透壁程度:</div>
                  <Radio.Group onChange={e => handleInputChange('lv_transmurality', e.target.value)} value={formData['lv_transmurality']}>
                    <Space direction="vertical">
                      <Radio value="0%">0%</Radio>
                      <Radio value="1-25%">1-25%</Radio>
                      <Radio value="26-50%">26-50%</Radio>
                      <Radio value="51-75%">51-75%</Radio>
                      <Radio value="76-100%">76-100%</Radio>
                    </Space>
                  </Radio.Group>
                </div>

                <div style={{ marginBottom: '12px' }}>
                  <div style={{ marginBottom: '4px', fontSize: '13px' }}>MVO:</div>
                  <Radio.Group onChange={e => handleInputChange('lv_mvo', e.target.value)} value={formData['lv_mvo']}>
                    <Radio value={true}>存在</Radio>
                    <Radio value={false}>不存在</Radio>
                  </Radio.Group>
                </div>
              </div>
            )}

            <Divider />

            {/* RV Section */}
            <div style={{ fontWeight: 'bold', marginBottom: '12px', color: 'var(--text-primary)' }}>右心室 RV</div>
            <div style={{ marginBottom: '16px' }}>
              <Radio.Group onChange={e => handleInputChange('rv_enhancement', e.target.value)} value={formData['rv_enhancement']}>
                <Radio value={false}>无强化</Radio>
                <Radio value={true}>有强化</Radio>
              </Radio.Group>
            </div>

            {formData['rv_enhancement'] === true && (
              <div style={{ marginLeft: '16px', borderLeft: '2px solid var(--border-color)', paddingLeft: '12px' }}>
                 <div style={{ marginBottom: '12px' }}>
                   <div style={{ marginBottom: '4px', fontSize: '13px' }}>部位:</div>
                   <Checkbox.Group 
                     options={['心尖段', '间隔壁', '前壁', '心室腔中段水平游离壁']}
                     value={formData['rv_enhancement_location'] ? formData['rv_enhancement_location'].split(',') : []}
                     onChange={(checkedValues) => handleInputChange('rv_enhancement_location', checkedValues.join(','))}
                     style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}
                   />
                </div>
              </div>
            )}

            <Divider />

            {/* Pericardium Section */}
            <div style={{ fontWeight: 'bold', marginBottom: '12px', color: 'var(--text-primary)' }}>心包强化</div>
            <div style={{ marginBottom: '16px' }}>
              <Radio.Group onChange={e => handleInputChange('pericardial_enhancement', e.target.value)} value={formData['pericardial_enhancement']}>
                <Radio value={false}>无强化</Radio>
                <Radio value={true}>有强化</Radio>
              </Radio.Group>
            </div>

        </div>
      </div>
    </div>
  );
};

export default LGEAnalysisPage;
