import React, { useState, useEffect, useRef } from 'react';
import { FaSave, FaRuler, FaChevronLeft, FaChevronRight } from 'react-icons/fa';
import { message } from 'antd';
import { useResizable } from '../../hooks/useResizable';
import { useLanguage } from '../../context/LanguageContext';
import MeasurementViewer from '../MeasurementViewer';

interface OtherFindingsViewProps {
  dataset: string;
  caseId: string;
  reviewUserId?: number | null;
  onSaveSuccess?: () => void;
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
    [key: string]: {
      pixel_spacing: [number, number] | null;
    }
  };
  assessment?: any;
}

const OtherFindingsView: React.FC<OtherFindingsViewProps> = ({ dataset, caseId, reviewUserId, onSaveSuccess }) => {
  const { t } = useLanguage();
  const [caseDetail, setCaseDetail] = useState<CaseDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'SAX' | '4CH' | 'LGE'>('SAX');
  const [currentImageIndex, setCurrentImageIndex] = useState(0);
  const [isMeasureMode, setIsMeasureMode] = useState(false);
  
  // Form State
  const [formData, setFormData] = useState<Record<string, string | null>>({});

  const viewerRef = useRef<HTMLDivElement>(null);

  const rightSidebar = useResizable({
    initialWidth: 260,
    minWidth: 200,
    maxWidth: 500,
    direction: 'left',
    storageKey: 'other-findings-right-sidebar'
  });

  useEffect(() => {
    if (dataset && caseId) {
      fetchCaseDetail(dataset, caseId);
    }
  }, [dataset, caseId, reviewUserId]);

  // Reset index when tab or case changes
  useEffect(() => {
    setCurrentImageIndex(0);
  }, [activeTab, caseDetail]);

  const fetchCaseDetail = async (ds: string, id: string) => {
    setLoading(true);
    setFormData({}); // Reset form
    const reviewQuery = reviewUserId ? `?review_user_id=${reviewUserId}` : '';
    try {
      const res = await fetch(`/api/other-findings/cases/${ds}/${id}${reviewQuery}`);
      const data = await res.json();
      setCaseDetail(data);
      
      // Auto select first available sequence
      if (data.images && data.images['SAX'] && data.images['SAX'].length > 0) setActiveTab('SAX');
      else if (data.images && data.images['4CH'] && data.images['4CH'].length > 0) setActiveTab('4CH');
      else if (data.images && data.images['LGE'] && data.images['LGE'].length > 0) setActiveTab('LGE');

      if (data.assessment && data.assessment.answers) {
        setFormData(data.assessment.answers);
      }
    } catch (err) {
      console.error("Failed to fetch case detail", err);
    } finally {
      setLoading(false);
    }
  };

  const handleInputChange = (key: string, value: string | boolean | null) => {
    setFormData(prev => ({
      ...prev,
      [key]: value as any
    }));
  };

  const handleSubmit = async () => {
    if (!caseDetail) return;
    
    try {
      const res = await fetch(`/api/other-findings/cases/${caseDetail.dataset}/${caseDetail.id}/assessment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...formData,
          review_user_id: reviewUserId ?? undefined,
        })
      });
      const data = await res.json();
      if (data.status === 'success') {
        message.success(t('common.success'));
        if (onSaveSuccess) onSaveSuccess();
      } else {
        message.error(t('common.error') + ': ' + data.error);
      }
    } catch (err) {
      message.error(t('common.error'));
    }
  };

  const handleWheel = (e: React.WheelEvent) => {
    if (!caseDetail || !caseDetail.images[activeTab] || caseDetail.images[activeTab].length === 0) return;
    
    const count = caseDetail.images[activeTab].length;
    if (e.deltaY > 0) {
      setCurrentImageIndex(prev => Math.min(prev + 1, count - 1));
    } else {
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

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden', width: '100%' }}>
      
      {/* Main Image Viewer */}
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
        {/* Sequence Selector Tabs (Top) */}
        {caseDetail && (
            <div style={{ 
                position: 'absolute', 
                top: 10, 
                left: '50%', 
                transform: 'translateX(-50%)', 
                zIndex: 20,
                display: 'flex',
                gap: '8px',
                backgroundColor: 'rgba(0,0,0,0.6)',
                padding: '4px',
                borderRadius: '8px'
            }}>
                {(['SAX', '4CH', 'LGE'] as const).map(seq => (
                    <button
                        key={seq}
                        onClick={() => setActiveTab(seq)}
                        style={{
                            padding: '6px 12px',
                            backgroundColor: activeTab === seq ? 'var(--accent-gold)' : 'transparent',
                            color: activeTab === seq ? '#000' : '#fff',
                            border: '1px solid var(--accent-gold)',
                            borderRadius: '4px',
                            cursor: 'pointer',
                            fontSize: '12px',
                            fontWeight: 'bold',
                            opacity: caseDetail.images && caseDetail.images[seq] && caseDetail.images[seq].length > 0 ? 1 : 0.5,
                            pointerEvents: caseDetail.images && caseDetail.images[seq] && caseDetail.images[seq].length > 0 ? 'auto' : 'none'
                        }}
                    >
                        {seq}
                    </button>
                ))}
            </div>
        )}

        {/* Image Display */}
        {caseDetail && caseDetail.images && caseDetail.images[activeTab] && caseDetail.images[activeTab].length > 0 ? (
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

                {/* Info Overlay */}
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
                        {activeTab} - {currentImageIndex + 1} / {caseDetail.images && caseDetail.images[activeTab] ? caseDetail.images[activeTab].length : 0}
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
            <div style={{ color: '#666' }}>No images available for this sequence</div>
        )}
      </div>

      {/* Right Sidebar: Questionnaire */}
      <div style={{ 
        width: rightSidebar.width, 
        borderLeft: '1px solid var(--border-color)', 
        backgroundColor: 'var(--bg-secondary)',
        display: 'flex', 
        flexDirection: 'column',
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
            }}
        />

        <div style={{ padding: '16px', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ fontWeight: 'bold', color: 'var(--text-primary)' }}>{t('other_findings.title')}</div>
            <button 
                onClick={handleSubmit}
                style={{
                    backgroundColor: 'var(--accent-gold)',
                    color: '#000',
                    border: 'none',
                    borderRadius: '4px',
                    padding: '6px 12px',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    fontWeight: 'bold'
                }}
            >
                <FaSave /> {t('common.save')}
            </button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '16px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
            
            {/* 1. Fat Infiltration */}
            <div>
                <div style={{ marginBottom: '8px', fontWeight: 500 }}>{t('other_findings.fat_infiltration')}</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{t('other_findings.location')}:</span>
                    <input 
                        type="text" 
                        value={formData['fat_infiltration_location'] as string || ''}
                        onChange={(e) => handleInputChange('fat_infiltration_location', e.target.value)}
                        placeholder={t('other_findings.specific_location')}
                        style={{ flex: 1, padding: '4px 8px', borderRadius: '4px', border: '1px solid var(--border-color)', backgroundColor: 'var(--bg-primary)', color: 'var(--text-primary)' }}
                    />
                </div>
            </div>

            {/* 2. Thrombus */}
            <div>
                <div style={{ marginBottom: '8px', fontWeight: 500 }}>{t('other_findings.thrombus')}</div>
                <div style={{ display: 'flex', gap: '16px', marginBottom: '8px' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                        <input 
                            type="radio" 
                            name="thrombus_present" 
                            checked={formData['thrombus_present'] === 'false'}
                            onChange={() => handleInputChange('thrombus_present', 'false')}
                        />
                        <span style={{ fontSize: '13px' }}>{t('common.no')}</span>
                    </label>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                        <input 
                            type="radio" 
                            name="thrombus_present" 
                            checked={formData['thrombus_present'] === 'true'}
                            onChange={() => handleInputChange('thrombus_present', 'true')}
                        />
                        <span style={{ fontSize: '13px' }}>{t('common.yes')}</span>
                    </label>
                </div>
                
                {formData['thrombus_present'] === 'true' && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', paddingLeft: '12px', borderLeft: '2px solid var(--border-color)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span style={{ width: '60px', fontSize: '13px' }}>{t('other_findings.location')}:</span>
                            <input 
                                type="text" 
                                value={formData['thrombus_location'] as string || ''}
                                onChange={(e) => handleInputChange('thrombus_location', e.target.value)}
                                style={{ flex: 1, padding: '4px 8px', borderRadius: '4px', border: '1px solid var(--border-color)', backgroundColor: 'var(--bg-primary)', color: 'var(--text-primary)' }}
                            />
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span style={{ width: '60px', fontSize: '13px' }}>{t('other_findings.size')}:</span>
                            <input 
                                type="text" 
                                value={formData['thrombus_size'] as string || ''}
                                onChange={(e) => handleInputChange('thrombus_size', e.target.value)}
                                style={{ flex: 1, padding: '4px 8px', borderRadius: '4px', border: '1px solid var(--border-color)', backgroundColor: 'var(--bg-primary)', color: 'var(--text-primary)' }}
                            />
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span style={{ width: '60px', fontSize: '13px' }}>{t('other_findings.mobility')}:</span>
                            <input 
                                type="text" 
                                value={formData['thrombus_mobility'] as string || ''}
                                onChange={(e) => handleInputChange('thrombus_mobility', e.target.value)}
                                style={{ flex: 1, padding: '4px 8px', borderRadius: '4px', border: '1px solid var(--border-color)', backgroundColor: 'var(--bg-primary)', color: 'var(--text-primary)' }}
                            />
                        </div>
                    </div>
                )}
            </div>

            {/* 3. Pericardial Effusion */}
            <div>
                <div style={{ marginBottom: '8px', fontWeight: 500 }}>{t('other_findings.pericardial_effusion')}</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {['trace', 'small', 'moderate', 'large'].map(opt => (
                        <label key={opt} style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                            <input 
                                type="radio" 
                                name="pericardial_effusion" 
                                checked={formData['pericardial_effusion'] === opt} 
                                onChange={() => handleInputChange('pericardial_effusion', opt)}
                            />
                            <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{t(`other_findings.pe.${opt}`)}</span>
                        </label>
                    ))}
                </div>
            </div>

            {/* 4. Pleural Effusion */}
            <div>
                <div style={{ marginBottom: '8px', fontWeight: 500 }}>{t('other_findings.pleural_effusion')}</div>
                <input 
                    type="text" 
                    value={formData['pleural_effusion'] as string || ''}
                    onChange={(e) => handleInputChange('pleural_effusion', e.target.value)}
                    placeholder={t('other_findings.describe_if_present')}
                    style={{ width: '100%', padding: '6px', borderRadius: '4px', border: '1px solid var(--border-color)', backgroundColor: 'var(--bg-primary)', color: 'var(--text-primary)' }}
                />
            </div>

            {/* 5. Other */}
            <div>
                <div style={{ marginBottom: '8px', fontWeight: 500 }}>{t('other_findings.other')}</div>
                <textarea 
                    value={formData['other_findings_desc'] as string || ''}
                    onChange={(e) => handleInputChange('other_findings_desc', e.target.value)}
                    placeholder={t('other_findings.specific_description')}
                    rows={4}
                    style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid var(--border-color)', backgroundColor: 'var(--bg-primary)', color: 'var(--text-primary)', resize: 'vertical' }}
                />
            </div>

        </div>
      </div>
    </div>
  );
};

export default OtherFindingsView;
