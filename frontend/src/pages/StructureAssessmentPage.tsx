import React, { useState, useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { FaSave, FaChevronRight, FaChevronDown, FaRuler, FaChevronLeft } from 'react-icons/fa';
import { message, Checkbox } from 'antd';
import { useResizable } from '../hooks/useResizable';
import { useLanguage } from '../context/LanguageContext';
import MeasurementViewer from '../components/MeasurementViewer';

interface CaseSummary {
  id: string;
  dataset: string;
  full_id: string;
  status?: {
    functional: boolean;
    lesion: boolean;
    analysis: boolean;
    evaluation: boolean;
    structure: boolean;
  };
}

interface CaseDetail {
  id: string;
  dataset: string;
  images: {
    'SAX': string[];
    '4CH': string[];
    'LGE': string[];
  };
  metadata?: {
      'SAX'?: { pixel_spacing?: [number, number] };
      '4CH'?: { pixel_spacing?: [number, number] };
      'LGE'?: { pixel_spacing?: [number, number] };
  };
  assessment?: any;
}

const StructureAssessmentPage: React.FC = () => {
  const { t } = useLanguage();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [selectedCase, setSelectedCase] = useState<CaseSummary | null>(null);
  const [caseDetail, setCaseDetail] = useState<CaseDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [isExpanded, setIsExpanded] = useState(true);
  
  const [activeTab, setActiveTab] = useState<'SAX' | '4CH' | 'LGE'>('SAX');
  const [currentImageIndex, setCurrentImageIndex] = useState(0);
  
  const location = useLocation();
  
  // Search State
  const [searchTerm, setSearchTerm] = useState('');
  
  // Form State
  const [formData, setFormData] = useState<Record<string, any>>({});

  // Tool State
  const [isMeasureMode, setIsMeasureMode] = useState(false);

  const viewerRef = useRef<HTMLDivElement>(null);

  // Resizable Sidebars
  const leftSidebar = useResizable({
    initialWidth: 280,
    minWidth: 200,
    maxWidth: 500,
    direction: 'right',
    storageKey: 'structure-left-sidebar'
  });

  const rightSidebar = useResizable({
    initialWidth: 400,
    minWidth: 300,
    maxWidth: 600,
    direction: 'left',
    storageKey: 'structure-right-sidebar'
  });

  useEffect(() => {
    fetchCases();
  }, []);

  useEffect(() => {
    if (selectedCase) {
      fetchCaseDetail(selectedCase.dataset, selectedCase.id);
    }
  }, [selectedCase]);

  // Reset index when tab or case changes
  useEffect(() => {
    setCurrentImageIndex(0);
  }, [activeTab, caseDetail]);

  const fetchCases = async () => {
    try {
      // Use functional cases endpoint as the base since structure assessment shares the same cases
      const res = await fetch('/api/functional/cases');
      const data = await res.json();
      
      // We need to fetch the structure status separately or update the functional cases endpoint
      // For now, let's assume the status object will contain 'structure' property if we update the backend
      // But based on current implementation, we might need to fetch status
      
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
      // Fetch image data (same as functional)
      const resImages = await fetch(`/api/functional/cases/${dataset}/${id}`);
      const dataImages = await resImages.json();
      
      // Fetch structure assessment data
      const resStruct = await fetch(`/api/structure/cases/${dataset}/${id}`);
      const dataStruct = await resStruct.json();
      
      setCaseDetail({
          ...dataImages,
          assessment: dataStruct.assessment
      });
      
      // Auto select first available sequence if current is empty
      if (dataImages.images['SAX'].length > 0) setActiveTab('SAX');
      else if (dataImages.images['4CH'].length > 0) setActiveTab('4CH');
      else if (dataImages.images['LGE'].length > 0) setActiveTab('LGE');

      if (dataStruct.assessment && dataStruct.assessment.answers) {
        // Convert boolean values to strings for display
        const answers = { ...dataStruct.assessment.answers };
        ['lv_increased_trabeculation', 'lv_outflow_obstruction'].forEach(key => {
            if (answers[key] === true) answers[key] = 'true';
            if (answers[key] === false) answers[key] = 'false';
        });
        setFormData(answers);
      }
    } catch (err) {
      console.error("Failed to fetch case detail", err);
    } finally {
      setLoading(false);
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

  const handleInputChange = (key: string, value: any) => {
    setFormData(prev => ({
      ...prev,
      [key]: value
    }));
  };

  const handleCheckboxChange = (key: string, option: string, checked: boolean) => {
    setFormData(prev => {
        const currentList = prev[key] || [];
        if (checked) {
            return { ...prev, [key]: [...currentList, option] };
        } else {
            return { ...prev, [key]: currentList.filter((item: string) => item !== option) };
        }
    });
  };

  const handleSubmit = async () => {
    if (!selectedCase) return;
    
    try {
      // Process boolean values
      const processedData = { ...formData };
      ['lv_increased_trabeculation', 'lv_outflow_obstruction'].forEach(key => {
          if (processedData[key] === 'true') processedData[key] = true;
          if (processedData[key] === 'false') processedData[key] = false;
      });

      const payload = {
          dataset: selectedCase.dataset,
          case_id: selectedCase.id,
          answers: processedData
      };
      
      const res = await fetch('/api/structure/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      
      const data = await res.json();
      if (data.message) {
        message.success(t('common.success'));
        // Refresh case details
        fetchCaseDetail(selectedCase.dataset, selectedCase.id);
        // Refresh cases list to update status
        fetchCases();
      } else {
        message.error(t('common.error') + ': ' + (data.error || 'Unknown error'));
      }
    } catch (err) {
      message.error(t('common.error'));
    }
  };

  const handleWheel = (e: React.WheelEvent) => {
    if (!caseDetail || !caseDetail.images[activeTab] || caseDetail.images[activeTab].length === 0) return;
    
    const count = caseDetail.images[activeTab].length;
    if (e.deltaY > 0) {
      // Scroll down -> Next image
      setCurrentImageIndex(prev => Math.min(prev + 1, count - 1));
    } else {
      // Scroll up -> Prev image
      setCurrentImageIndex(prev => Math.max(prev - 1, 0));
    }
  };

  const handleNextImage = () => {
    if (!caseDetail || !caseDetail.images[activeTab] || caseDetail.images[activeTab].length === 0) return;
    const count = caseDetail.images[activeTab].length;
    setCurrentImageIndex(prev => Math.min(prev + 1, count - 1));
  };

  const handlePrevImage = () => {
    setCurrentImageIndex(prev => Math.max(prev - 1, 0));
  };

  const getSequenceCount = (seq: 'SAX' | '4CH' | 'LGE') => {
    return caseDetail?.images[seq]?.length || 0;
  };

  // Helper to render radio group
  const renderRadioGroup = (labelKey: string, key: string, options: {value: string, labelKey: string}[]) => (
    <div style={{ marginBottom: '16px' }}>
      <div style={{ fontSize: '14px', marginBottom: '8px', color: 'var(--text-primary)' }}>{t(labelKey)}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', paddingLeft: '8px' }}>
        {options.map(option => (
            <label key={option.value} style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
            <input 
                type="radio" 
                name={key} 
                checked={formData[key] === option.value} 
                onChange={() => handleInputChange(key, option.value)}
            />
            <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{t(option.labelKey)}</span>
            </label>
        ))}
      </div>
    </div>
  );

  // Helper to render checkbox group
  const renderCheckboxGroup = (labelKey: string, key: string, options: {value: string, labelKey: string}[]) => (
    <div style={{ marginBottom: '16px' }}>
      <div style={{ fontSize: '14px', marginBottom: '8px', color: 'var(--text-primary)' }}>{t(labelKey)}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', paddingLeft: '8px' }}>
        {options.map(option => (
            <Checkbox 
                key={option.value}
                checked={(formData[key] || []).includes(option.value)}
                onChange={(e) => handleCheckboxChange(key, option.value, e.target.checked)}
                style={{ fontSize: '13px', color: 'var(--text-secondary)', marginLeft: 0 }}
            >
                {t(option.labelKey)}
            </Checkbox>
        ))}
      </div>
    </div>
  );
  
  // Helper to render text input
  const renderTextInput = (labelKey: string, key: string, placeholderKey?: string) => (
      <div style={{ marginBottom: '16px' }}>
          <div style={{ fontSize: '14px', marginBottom: '8px', color: 'var(--text-primary)' }}>{t(labelKey)}</div>
          <input 
            type="text" 
            value={formData[key] || ''} 
            onChange={(e) => handleInputChange(key, e.target.value)}
            placeholder={placeholderKey ? t(placeholderKey) : ''}
            style={{
                width: '100%',
                padding: '6px 8px',
                borderRadius: '4px',
                border: '1px solid var(--border-color)',
                backgroundColor: 'var(--bg-tertiary)',
                color: 'var(--text-primary)',
                fontSize: '13px'
            }}
          />
      </div>
  );

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      {/* 1. Case List Column */}
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

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', padding: '16px 16px 0 16px' }}>
          <h3 style={{ margin: 0, fontSize: '18px', color: 'var(--text-primary)' }}>{t('eval.waiting_list')}</h3>
          <button onClick={fetchCases} style={{ border: 'none', background: 'transparent', color: 'var(--accent-gold)', cursor: 'pointer' }}>{t('common.refresh')}</button>
        </div>

        {/* Search Input */}
        <div style={{ padding: '0 16px 16px 16px' }}>
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
          {cases.filter(c => c.id.toLowerCase().includes(searchTerm.toLowerCase())).map(c => {
            const isSelected = selectedCase?.full_id === c.full_id;
            return (
              <div key={c.full_id}>
                <div
                  onClick={() => handleCaseClick(c)}
                  style={{
                    padding: '10px 16px',
                    cursor: 'pointer',
                    backgroundColor: isSelected ? 'rgba(217, 119, 6, 0.1)' : 'transparent',
                    borderLeft: isSelected ? '3px solid var(--accent-gold)' : '3px solid transparent',
                    color: isSelected ? 'var(--accent-gold)' : 'var(--text-secondary)',
                    fontSize: '14px',
                    transition: 'all 0.2s',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <div style={{ fontWeight: 500 }}>{c.id}</div>
                    {c.status?.structure && (
                      <span style={{ 
                        fontSize: '10px', 
                        padding: '1px 4px', 
                        borderRadius: '3px',
                        backgroundColor: 'rgba(16, 185, 129, 0.1)',
                        color: '#10b981',
                        border: '1px solid rgba(16, 185, 129, 0.2)'
                      }}>
                        {t('patient.completed')}
                      </span>
                    )}
                  </div>
                  {isSelected && (
                    isExpanded ? <FaChevronDown size={12} /> : <FaChevronRight size={12} />
                  )}
                </div>

                {/* Expandable Children */}
                {isSelected && isExpanded && (
                  <div style={{ backgroundColor: 'rgba(0,0,0,0.02)' }}>
                    {['4CH', 'SAX', 'LGE'].map(seq => {
                      const count = getSequenceCount(seq as any);
                      const isActive = activeTab === seq;
                      return (
                        <div
                          key={seq}
                          onClick={(e) => {
                            e.stopPropagation();
                            setActiveTab(seq as any);
                          }}
                          style={{
                            padding: '8px 16px 8px 32px',
                            cursor: 'pointer',
                            color: isActive ? 'var(--accent-gold)' : 'var(--text-secondary)',
                            fontSize: '13px',
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            backgroundColor: isActive ? 'rgba(217, 119, 6, 0.05)' : 'transparent',
                          }}
                        >
                          <span>{seq}</span>
                          <span style={{ fontSize: '11px', opacity: 0.7 }}>({count})</span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
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
          <div style={{ color: 'white' }}>{t('common.loading')}</div>
        ) : caseDetail && caseDetail.images[activeTab]?.length > 0 ? (
          <>
             <MeasurementViewer
                imageUrl={`/api/functional/images/${caseDetail.dataset}/${caseDetail.id}/${caseDetail.images[activeTab][currentImageIndex]}`}
                pixelSpacing={caseDetail.metadata?.[activeTab]?.pixel_spacing || null}
                isActive={isMeasureMode}
             />

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

             {/* UI Overlay */}
             <div style={{ 
               position: 'absolute', 
               top: '10px', 
               left: '10px', 
               display: 'flex',
               gap: '10px',
               zIndex: 100
             }}>
               <div style={{
                 color: 'white', 
                 backgroundColor: 'rgba(0,0,0,0.6)', 
                 padding: '6px 10px', 
                 borderRadius: '4px',
                 fontSize: '12px',
                 border: '1px solid rgba(255,255,255,0.1)',
                 backdropFilter: 'blur(4px)'
               }}>
                 {activeTab} - {currentImageIndex + 1} / {caseDetail.images[activeTab].length}
               </div>
               
               <button 
                 onClick={() => setIsMeasureMode(!isMeasureMode)}
                 style={{
                   backgroundColor: isMeasureMode ? '#d4af37' : 'rgba(0,0,0,0.6)',
                   color: 'white',
                   border: '1px solid rgba(255,255,255,0.2)',
                   borderRadius: '4px',
                   padding: '6px 10px',
                   cursor: 'pointer',
                   display: 'flex',
                   alignItems: 'center',
                   gap: '6px',
                   fontSize: '12px',
                   backdropFilter: 'blur(4px)',
                   transition: 'all 0.2s'
                 }}
                 title={t('tool.measure')}
               >
                 <FaRuler /> {t('tool.measure')}
               </button>
             </div>
          </>
        ) : (
          <div style={{ color: '#666' }}>{t('common.no_data')}</div>
        )}
      </div>

      {/* 3. Right Sidebar - Structure Questionnaire */}
      <div style={{
        width: rightSidebar.width,
        backgroundColor: 'var(--bg-secondary)',
        borderLeft: '1px solid var(--border-color)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        position: 'relative',
        flexShrink: 0,
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
          <span>{t('structure.title')}</span>
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
          
          {/* Section 1: LV Myocardial Thickness */}
          <h4 style={{ margin: '0 0 12px 0', color: 'var(--accent-gold)', fontSize: '15px' }}>{t('structure.q1_title')}</h4>
          
          {renderRadioGroup('structure.lv_wall_thickness', 'lv_wall_thickness', [
              {value: 'normal', labelKey: 'structure.normal_desc'},
              {value: 'thickened', labelKey: 'structure.thickened'},
              {value: 'thinned', labelKey: 'structure.thinned'}
          ])}
          
          {formData['lv_wall_thickness'] === 'thickened' && (
              <div style={{ marginLeft: '16px', borderLeft: '2px solid var(--border-color)', paddingLeft: '12px', marginBottom: '12px' }}>
                  {renderRadioGroup('structure.thickened_type', 'lv_thickened_type', [
                      {value: 'concentric', labelKey: 'structure.concentric'},
                      {value: 'eccentric', labelKey: 'structure.eccentric'},
                      {value: 'asymmetric', labelKey: 'structure.asymmetric'}
                  ])}
                  {renderTextInput('structure.prominent_at', 'lv_thickened_location')}
                  {renderTextInput('structure.max_thickness', 'lv_thickened_max_thickness')}
              </div>
          )}

          {formData['lv_wall_thickness'] === 'thinned' && (
              <div style={{ marginLeft: '16px', borderLeft: '2px solid var(--border-color)', paddingLeft: '12px', marginBottom: '12px' }}>
                  {renderRadioGroup('structure.thinned_type', 'lv_thinned_type', [
                      {value: 'diffuse', labelKey: 'structure.diffuse'},
                      {value: 'local', labelKey: 'structure.local'}
                  ])}
                  {renderTextInput('structure.prominent_at_paren', 'lv_thinned_location')}
                  {renderTextInput('structure.max_thickness_paren', 'lv_thinned_max_thickness')}
              </div>
          )}
          
          {renderRadioGroup('structure.increased_trabeculation', 'lv_increased_trabeculation', [
              {value: 'true', labelKey: 'structure.yes'},
              {value: 'false', labelKey: 'structure.no'}
          ])}
          
          {renderRadioGroup('structure.outflow_obstruction', 'lv_outflow_obstruction', [
              {value: 'true', labelKey: 'structure.yes'},
              {value: 'false', labelKey: 'structure.no'}
          ])}


          {/* Section 2: Heart Motion & Function */}
          <h4 style={{ margin: '20px 0 12px 0', color: 'var(--accent-gold)', fontSize: '15px' }}>{t('structure.q2_title')}</h4>
          
          {renderRadioGroup('structure.lv_wall_motion', 'lv_wall_motion', [
              {value: 'normal', labelKey: 'structure.normal'},
              {value: 'enhanced', labelKey: 'structure.enhanced'},
              {value: 'reduced', labelKey: 'structure.reduced'},
              {value: 'paradoxical', labelKey: 'structure.paradoxical'}
          ])}

          {formData['lv_wall_motion'] === 'enhanced' && (
              <div style={{ marginLeft: '16px', borderLeft: '2px solid var(--border-color)', paddingLeft: '12px', marginBottom: '12px' }}>
                   {renderRadioGroup('structure.enhanced', 'lv_enhanced_type', [
                      {value: 'diffuse', labelKey: 'structure.diffuse'},
                      {value: 'local', labelKey: 'structure.local'}
                  ])}
                  {renderTextInput('structure.location', 'lv_enhanced_location')}
              </div>
          )}

          {formData['lv_wall_motion'] === 'reduced' && (
              <div style={{ marginLeft: '16px', borderLeft: '2px solid var(--border-color)', paddingLeft: '12px', marginBottom: '12px' }}>
                   {renderRadioGroup('structure.reduced', 'lv_reduced_type', [
                      {value: 'diffuse', labelKey: 'structure.diffuse'},
                      {value: 'local', labelKey: 'structure.local'}
                  ])}
                  {renderTextInput('structure.location', 'lv_reduced_location')}
              </div>
          )}
          
          {formData['lv_wall_motion'] === 'paradoxical' && (
              <div style={{ marginLeft: '16px', borderLeft: '2px solid var(--border-color)', paddingLeft: '12px', marginBottom: '12px' }}>
                  {renderTextInput('structure.location', 'lv_paradoxical_location')}
              </div>
          )}
          
          {renderRadioGroup('structure.aneurysm', 'lv_aneurysm', [
              {value: 'none', labelKey: 'structure.aneurysm_none'},
              {value: 'true', labelKey: 'structure.aneurysm_true'},
              {value: 'pseudo', labelKey: 'structure.aneurysm_pseudo'}
          ])}


          {/* Section 3: Valvular Morphology & Function */}
          <h4 style={{ margin: '20px 0 12px 0', color: 'var(--accent-gold)', fontSize: '15px' }}>{t('structure.q3_title')}</h4>
          <h5 style={{ margin: '0 0 8px 0', fontSize: '14px' }}>{t('structure.valvular_morphology')}</h5>
          
          {renderCheckboxGroup('structure.valvular_morphology', 'valvular_stenosis', [
              {value: 'mitral', labelKey: 'structure.mitral_stenosis'},
              {value: 'tricuspid', labelKey: 'structure.tricuspid_stenosis'},
              {value: 'aortic', labelKey: 'structure.aortic_stenosis'}
          ])}

          <h5 style={{ margin: '12px 0 8px 0', fontSize: '14px' }}>{t('structure.valvular_regurgitation')}</h5>
          
          {renderRadioGroup('structure.mitral_regurgitation', 'mitral_regurgitation', [
              {value: 'none', labelKey: 'structure.none'},
              {value: 'mild', labelKey: 'structure.mild'},
              {value: 'moderate', labelKey: 'structure.moderate'},
              {value: 'severe', labelKey: 'structure.severe'}
          ])}
          
          {renderRadioGroup('structure.tricuspid_regurgitation', 'tricuspid_regurgitation', [
              {value: 'none', labelKey: 'structure.none'},
              {value: 'mild', labelKey: 'structure.mild'},
              {value: 'moderate', labelKey: 'structure.moderate'},
              {value: 'severe', labelKey: 'structure.severe'}
          ])}
          
          {renderRadioGroup('structure.aortic_regurgitation', 'aortic_regurgitation', [
              {value: 'none', labelKey: 'structure.none'},
              {value: 'mild', labelKey: 'structure.mild'},
              {value: 'moderate', labelKey: 'structure.moderate'},
              {value: 'severe', labelKey: 'structure.severe'}
          ])}

        </div>
      </div>
    </div>
  );
};

export default StructureAssessmentPage;
