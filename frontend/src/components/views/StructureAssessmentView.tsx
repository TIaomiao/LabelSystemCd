import React, { useState, useEffect, useRef, useMemo } from 'react';
import { FaSave, FaRuler, FaChevronLeft, FaChevronRight } from 'react-icons/fa';
import { message, Checkbox } from 'antd';
import { useResizable } from '../../hooks/useResizable';
import { useLanguage } from '../../context/LanguageContext';
import MeasurementViewer from '../MeasurementViewer';
import { buildSequenceMatrixLayout, numericLabel, resolveMatrixCellIndex, workstationViewTheme } from './workstationViewShared';
import WorkstationNavigatorBar from './WorkstationNavigatorBar';
import WorkstationStackMatrix from './WorkstationStackMatrix';
import { useSharedCaseImageCache } from './useSharedCaseImageCache';
import './workstationPaneScroll.css';

interface StructureAssessmentViewProps {
  dataset: string;
  caseId: string;
  reviewUserId?: number | null;
  onSaveSuccess?: () => void;
  showPhaseControls?: boolean;
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
  phase_labels?: Partial<Record<'SAX' | '4CH' | 'LGE', Partial<Record<'ed' | 'es', string | number | null>>>>;
  assessment?: any;
}

const StructureAssessmentView: React.FC<StructureAssessmentViewProps> = ({
  dataset,
  caseId,
  reviewUserId,
  onSaveSuccess,
  showPhaseControls = true,
}) => {
  const { t } = useLanguage();
  const [caseDetail, setCaseDetail] = useState<CaseDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'SAX' | '4CH' | 'LGE'>('SAX');
  const [currentImageIndex, setCurrentImageIndex] = useState(0);
  const [isMeasureMode, setIsMeasureMode] = useState(false);
  const [matrixHeight, setMatrixHeight] = useState(() => {
    const saved = localStorage.getItem('structure-matrix-height');
    const parsed = saved ? parseFloat(saved) : NaN;
    return Number.isFinite(parsed) ? Math.min(132, Math.max(96, parsed)) : 108;
  });
  
  // Form State
  const [formData, setFormData] = useState<Record<string, any>>({});

  const viewerRef = useRef<HTMLDivElement>(null);
  const sequenceOrder = useMemo(
    () => (['SAX', '4CH', 'LGE'] as const).filter(seq => (caseDetail?.images?.[seq]?.length || 0) > 0),
    [caseDetail]
  );
  const activeSequenceIndex = Math.max(0, sequenceOrder.indexOf(activeTab));
  const currentSequenceCount = caseDetail?.images?.[activeTab]?.length || 0;

  const rightSidebar = useResizable({
    initialWidth: 220,
    minWidth: 180,
    maxWidth: 500,
    direction: 'left',
    storageKey: 'structure-right-sidebar'
  });

  useEffect(() => {
    localStorage.setItem('structure-matrix-height', String(matrixHeight));
  }, [matrixHeight]);

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
      // Fetch image data
      const resImages = await fetch(`/api/functional/cases/${ds}/${id}${reviewQuery}`);
      const dataImages = await resImages.json();
      
      // Fetch structure assessment data
      const resStruct = await fetch(`/api/structure/cases/${ds}/${id}${reviewQuery}`);
      const dataStruct = await resStruct.json();
      
      setCaseDetail({
          ...dataImages,
          assessment: dataStruct.assessment
      });
      
      // Auto select first available sequence
      if (dataImages.images && dataImages.images['SAX'] && dataImages.images['SAX'].length > 0) setActiveTab('SAX');
      else if (dataImages.images && dataImages.images['4CH'] && dataImages.images['4CH'].length > 0) setActiveTab('4CH');
      else if (dataImages.images && dataImages.images['LGE'] && dataImages.images['LGE'].length > 0) setActiveTab('LGE');

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
    if (!caseDetail) return;
    
    try {
      // Process boolean values
      const processedData = { ...formData };
      ['lv_increased_trabeculation', 'lv_outflow_obstruction'].forEach(key => {
          if (processedData[key] === 'true') processedData[key] = true;
          if (processedData[key] === 'false') processedData[key] = false;
      });

      const payload = {
          dataset: caseDetail.dataset,
          case_id: caseDetail.id,
          review_user_id: reviewUserId ?? undefined,
          answers: processedData
      };
      
      const res = await fetch('/api/structure/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (res.ok && (data.status === 'success' || data.message)) {
        message.success(t('common.success'));
        if (onSaveSuccess) onSaveSuccess();
      } else {
        message.error(t('common.error') + ': ' + (data.error || 'Unknown error'));
      }
    } catch (err) {
      message.error(t('common.error'));
    }
  };

  const handleWheel = (e: React.WheelEvent) => {
    if (!caseDetail || !caseDetail.images[activeTab] || caseDetail.images[activeTab].length === 0) return;

    if (e.shiftKey) {
      e.preventDefault();
      if (e.deltaY > 0) handleNextSequence();
      else handlePrevSequence();
      return;
    }
    
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

  const handleSequenceChange = (nextTab: 'SAX' | '4CH' | 'LGE') => {
    setActiveTab(nextTab);
    setCurrentImageIndex(0);
  };

  const handleNextSequence = () => {
    if (sequenceOrder.length <= 1) return;
    const nextIndex = Math.min(activeSequenceIndex + 1, sequenceOrder.length - 1);
    const nextTab = sequenceOrder[nextIndex];
    if (nextTab) handleSequenceChange(nextTab);
  };

  const handlePrevSequence = () => {
    if (sequenceOrder.length <= 1) return;
    const nextIndex = Math.max(activeSequenceIndex - 1, 0);
    const nextTab = sequenceOrder[nextIndex];
    if (nextTab) handleSequenceChange(nextTab);
  };

  useEffect(() => {
    const isTypingTarget = (target: EventTarget | null) => {
      if (!(target instanceof HTMLElement)) return false;
      if (target.isContentEditable) return true;
      return Boolean(target.closest('input, textarea, select, [contenteditable="true"], [contenteditable=""]'));
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      if (isTypingTarget(event.target)) return;

      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        handlePrevImage();
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        handleNextImage();
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        handlePrevSequence();
      } else if (event.key === 'ArrowDown') {
        event.preventDefault();
        handleNextSequence();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [activeSequenceIndex, sequenceOrder, activeTab, currentSequenceCount]);

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

  const currentImageUrl = useSharedCaseImageCache({
    dataset: caseDetail?.dataset,
    caseId: caseDetail?.id,
    images: caseDetail?.images?.[activeTab] || [],
    currentIndex: currentImageIndex,
    windowSize: 8,
    concurrency: 3
  });
  const sequenceLayouts = useMemo(
    () => ({
      SAX: buildSequenceMatrixLayout('SAX', caseDetail?.images?.SAX || [], caseDetail?.phase_labels?.SAX),
      '4CH': buildSequenceMatrixLayout('4CH', caseDetail?.images?.['4CH'] || [], caseDetail?.phase_labels?.['4CH']),
      LGE: buildSequenceMatrixLayout('LGE', caseDetail?.images?.LGE || [])
    }),
    [caseDetail]
  );
  const activeLayout = sequenceLayouts[activeTab];
  const activePosition = activeLayout.positionByIndex.get(currentImageIndex) || { sliceIndex: 0, phaseIndex: 0 };
  const activePhaseAssignments = caseDetail?.phase_labels?.[activeTab];

  const handleSliceChange = (nextSliceIndex: number) => {
    setCurrentImageIndex(prev =>
      resolveMatrixCellIndex(
        activeLayout,
        nextSliceIndex,
        activePosition.phaseIndex,
        prev
      )
    );
  };

  const handlePhaseChange = (nextPhaseIndex: number) => {
    setCurrentImageIndex(prev =>
      resolveMatrixCellIndex(
        activeLayout,
        activePosition.sliceIndex,
        nextPhaseIndex,
        prev
      )
    );
  };

  const renderViewportLabel = (title: string, sliceIndex: number, phaseIndex: number, accent: string) => (
    <div style={workstationViewTheme.viewportLabel(accent)}>
      {title}
      {' · '}
      S{sliceIndex + 1}
      {' / '}
      P{phaseIndex + 1}
    </div>
  );

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden', width: '100%' }}>
      <div 
        ref={viewerRef}
        className="workstation-scroll-pane"
        style={{ 
          flex: 1, 
          backgroundColor: workstationViewTheme.workspace.background,
          display: 'flex', 
          flexDirection: 'column', 
          position: 'relative',
          overflowY: 'auto',
          overflowX: 'hidden'
        }}
      >
        <div style={{
          minHeight: '48px',
          backgroundColor: workstationViewTheme.workspace.chromeBackground,
          borderBottom: `1px solid ${workstationViewTheme.workspace.lineStrong}`,
          display: 'flex',
          alignItems: 'center',
          padding: '0 16px',
          flexWrap: 'wrap',
          gap: '16px',
          zIndex: 10
        }}>
          <button
            onClick={() => setIsMeasureMode(prev => !prev)}
            style={workstationViewTheme.toolbarButton(isMeasureMode)}
            title={t('tool.measure')}
          >
            <FaRuler />
            {t('tool.measure')}
          </button>

          <div style={{ flex: 1 }} />

          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            {sequenceOrder.map(seq => {
              const count = caseDetail?.images?.[seq]?.length || 0;
              if (count === 0) return null;
              return (
                <button
                  key={seq}
                  onClick={() => handleSequenceChange(seq)}
                  style={workstationViewTheme.sequenceTab(activeTab === seq)}
                >
                  {seq} ({count})
                </button>
              );
            })}
          </div>

          {activePhaseAssignments?.ed || activePhaseAssignments?.es ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', minWidth: '88px' }}>
              <span style={{ color: '#888', fontSize: '11px' }}>ED / ES</span>
              <strong style={{ color: '#f1f1f1', fontSize: '13px', fontWeight: 600 }}>
                {numericLabel(activePhaseAssignments?.ed ?? '—')} / {numericLabel(activePhaseAssignments?.es ?? '—')}
              </strong>
            </div>
          ) : null}

          <div style={{ color: '#888', fontSize: '12px', minWidth: '60px', textAlign: 'right' }}>
            {currentSequenceCount ? `${activeTab} ${currentImageIndex + 1} / ${currentSequenceCount}` : ''}
          </div>
        </div>

        <div
          style={{
            flex: '0 0 auto',
            minHeight: 'calc(100% - 48px)',
            display: 'flex',
            flexDirection: 'column',
            gap: '4px',
            padding: '4px 6px 6px',
            background: workstationViewTheme.workspace.contentBackground
          }}
        >
          <div
            onWheel={handleWheel}
            style={{
              flex: '0 0 auto',
              minHeight: '560px',
              height: 'clamp(560px, 68vh, 920px)',
              position: 'relative',
              background: '#020202',
              border: `1px solid ${workstationViewTheme.workspace.line}`,
              borderRadius: '2px',
              overflow: 'hidden'
            }}
          >
            <div onClick={(e) => { e.stopPropagation(); handlePrevImage(); }} style={workstationViewTheme.floatingArrow('left')}>
              <FaChevronLeft />
            </div>
            <div onClick={(e) => { e.stopPropagation(); handleNextImage(); }} style={workstationViewTheme.floatingArrow('right')}>
              <FaChevronRight />
            </div>
            {loading ? (
              <div style={{ width: '100%', height: '100%', display: 'grid', placeItems: 'center', color: '#fff' }}>{t('common.loading')}</div>
            ) : caseDetail && caseDetail.images && caseDetail.images[activeTab] && caseDetail.images[activeTab].length > 0 ? (
              <>
                {renderViewportLabel(`${activeTab} 主视图`, activePosition.sliceIndex, activePosition.phaseIndex, '#fff')}
                <MeasurementViewer
                  imageUrl={currentImageUrl}
                  pixelSpacing={caseDetail.metadata?.[activeTab]?.pixel_spacing || null}
                  isActive={isMeasureMode}
                />
              </>
            ) : (
              <div style={{ width: '100%', height: '100%', display: 'grid', placeItems: 'center', color: '#666' }}>{t('common.no_data')}</div>
            )}
          </div>

          {showPhaseControls ? (
            <>
              <WorkstationNavigatorBar
                sliceValue={activePosition.sliceIndex}
                sliceMax={Math.max(1, activeLayout.sliceLabels.length)}
                onSliceChange={handleSliceChange}
                phaseValue={activePosition.phaseIndex}
                phaseMax={Math.max(1, activeLayout.phaseLabels.length)}
                onPhaseChange={handlePhaseChange}
              />

              <div
                style={{
                  flex: `0 0 ${matrixHeight}px`,
                  minHeight: '96px'
                }}
              >
                <WorkstationStackMatrix
                  title="Slice / Phase Matrix"
                  layout={activeLayout}
                  currentIndex={currentImageIndex}
                  onSelect={setCurrentImageIndex}
                />
              </div>
            </>
          ) : null}
        </div>
      </div>

      <div style={{
        width: rightSidebar.width,
        backgroundColor: workstationViewTheme.workspace.panelEdgeBackground,
        borderLeft: `1px solid ${workstationViewTheme.workspace.line}`,
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
                left: -4,
                width: '8px',
                height: '100%',
                cursor: 'col-resize',
                zIndex: 10,
                background: rightSidebar.isResizing
                  ? 'linear-gradient(90deg, transparent 0, transparent 3px, rgba(168, 203, 78, 0.85) 3px, rgba(168, 203, 78, 0.85) 5px, transparent 5px, transparent 100%)'
                  : 'linear-gradient(90deg, transparent 0, transparent 3px, rgba(255, 255, 255, 0.14) 3px, rgba(255, 255, 255, 0.14) 5px, transparent 5px, transparent 100%)',
                transition: 'background 0.2s',
            }}
        />

        <div style={{ padding: '16px', borderBottom: `1px solid ${workstationViewTheme.workspace.line}`, fontWeight: 'bold', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>{t('structure.title')}</span>
          <button 
            onClick={handleSubmit}
            style={workstationViewTheme.actionButton}
          >
            <FaSave /> {t('common.save')}
          </button>
        </div>
        
        <div className="workstation-scroll-pane" style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', padding: '16px' }}>
          
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

export default StructureAssessmentView;
