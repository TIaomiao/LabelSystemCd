import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { FaSave, FaAdjust, FaChevronLeft, FaChevronRight } from 'react-icons/fa';
import { message } from 'antd';
import { useResizable } from '../../hooks/useResizable';
import { useLanguage } from '../../context/LanguageContext';
import { buildSequenceMatrixLayout, numericLabel, resolveMatrixCellIndex, workstationViewTheme } from './workstationViewShared';
import WorkstationStackMatrix from './WorkstationStackMatrix';
import WorkstationNavigatorBar from './WorkstationNavigatorBar';
import { useSharedCaseImageCache } from './useSharedCaseImageCache';
import './workstationPaneScroll.css';

interface ImageAnalysisViewProps {
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
  phase_labels?: Partial<Record<'SAX' | '4CH' | 'LGE', Partial<Record<'ed' | 'es', string | number | null>>>>;
  assessment?: any;
}

const ImageAnalysisView: React.FC<ImageAnalysisViewProps> = ({
  dataset,
  caseId,
  reviewUserId,
  onSaveSuccess,
  showPhaseControls = true,
}) => {
  const { t } = useLanguage();
  const [caseDetail, setCaseDetail] = useState<CaseDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [activeTab, setActiveTab] = useState<'SAX' | '4CH' | 'LGE'>('SAX');
  const [currentImageIndex, setCurrentImageIndex] = useState(0);
  // Dual View State
  const [showEnhanced, setShowEnhanced] = useState(true);
  const [flipHorizontal, setFlipHorizontal] = useState(false);
  const [flipVertical, setFlipVertical] = useState(false);
  const [compareSplit, setCompareSplit] = useState(() => {
    const saved = localStorage.getItem('analysis-compare-split');
    const parsed = saved ? parseFloat(saved) : NaN;
    return Number.isFinite(parsed) ? Math.min(0.72, Math.max(0.42, parsed)) : 0.6;
  });
  const [matrixHeight, setMatrixHeight] = useState(() => {
    const saved = localStorage.getItem('analysis-matrix-height');
    const parsed = saved ? parseFloat(saved) : NaN;
    return Number.isFinite(parsed) ? Math.min(132, Math.max(96, parsed)) : 108;
  });

  // Form State
  const [formData, setFormData] = useState<Record<string, any>>({});

  const viewerRef = useRef<HTMLDivElement>(null);
  const dualPaneRef = useRef<HTMLDivElement>(null);

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
    storageKey: 'analysis-right-sidebar'
  });

  useEffect(() => {
    localStorage.setItem('analysis-compare-split', String(compareSplit));
  }, [compareSplit]);

  useEffect(() => {
    localStorage.setItem('analysis-matrix-height', String(matrixHeight));
  }, [matrixHeight]);

  useEffect(() => {
    if (dataset && caseId) {
      fetchCaseDetail(dataset, caseId);
    }
  }, [dataset, caseId, reviewUserId]);

  // Reset index when case changes
  useEffect(() => {
    setCurrentImageIndex(0);
  }, [caseDetail, activeTab]);

  const fetchCaseDetail = async (ds: string, id: string) => {
    setLoading(true);
    setLoadError('');
    setCaseDetail(null);
    setFormData({}); // Reset form
    const reviewQuery = reviewUserId ? `?review_user_id=${reviewUserId}` : '';
    try {
      const res = await fetch(`/api/analysis/cases/${ds}/${id}${reviewQuery}`);
      if (res.status === 404) {
          // If analysis not found, try fetching base case data from functional API
          // This allows initializing the view even if analysis record doesn't exist yet
          try {
              const resFunc = await fetch(`/api/functional/cases/${ds}/${id}${reviewQuery}`);
              if (resFunc.ok) {
                  const dataFunc = await resFunc.json();
                  // Construct a compatible CaseDetail object
                  const baseData: CaseDetail = {
                      id: dataFunc.id,
                      dataset: dataFunc.dataset,
                      images: {
                          'LGE': dataFunc.images && dataFunc.images['LGE'] ? dataFunc.images['LGE'] : [],
                          'SAX': dataFunc.images && dataFunc.images['SAX'] ? dataFunc.images['SAX'] : [],
                          '4CH': dataFunc.images && dataFunc.images['4CH'] ? dataFunc.images['4CH'] : []
                      },
                      phase_labels: dataFunc.phase_labels,
                      assessment: undefined
                  };
                  setCaseDetail(baseData);
                  // Auto select first available sequence
                  if (baseData.images['SAX'] && baseData.images['SAX'].length > 0) setActiveTab('SAX');
                  else if (baseData.images['LGE'] && baseData.images['LGE'].length > 0) setActiveTab('LGE');
                  else if (baseData.images['4CH'] && baseData.images['4CH'].length > 0) setActiveTab('4CH');
                  
                  setFormData({
                      overall_quality: 'good',
                      has_artifacts: false
                  });
                  return;
              }
          } catch (e) {
              console.warn("Failed to fetch base case data", e);
          }
      }

      if (!res.ok) {
          let errorDetail = '';
          try {
            const payload = await res.json();
            errorDetail = payload.error || '';
          } catch {
            // Keep the status-based fallback when the backend did not return JSON.
          }
          throw new Error(errorDetail || `影像质量加载失败（HTTP ${res.status}）`);
      }
      const data = await res.json();
      setCaseDetail(data);
      
      // Auto select first available sequence
      if (data.images && data.images['SAX'] && data.images['SAX'].length > 0) setActiveTab('SAX');
      else if (data.images && data.images['LGE'] && data.images['LGE'].length > 0) setActiveTab('LGE');
      else if (data.images && data.images['4CH'] && data.images['4CH'].length > 0) setActiveTab('4CH');
      
      if (data.assessment) {
          if (data.assessment.answers) {
            setFormData({
                overall_quality: 'good',
                has_artifacts: false,
                ...data.assessment.answers
            });
          }
      } else {
          setFormData({
              overall_quality: 'good',
              has_artifacts: false
          });
      }
    } catch (err) {
      console.error("Failed to fetch case detail", err);
      setCaseDetail(null);
      setLoadError(err instanceof Error ? err.message : '病例影像加载失败');
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

  const handleSubmit = async () => {
    if (!caseDetail) return;
    
    try {
      const res = await fetch(`/api/analysis/cases/${caseDetail.dataset}/${caseDetail.id}/assessment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            ...formData,
            review_user_id: reviewUserId ?? undefined,
            artifact_boxes: [] // No longer used
        })
      });
      const data = await res.json();
      if (data.status === 'success') {
        message.success(t('analysis.save_success'));
        if (onSaveSuccess) onSaveSuccess();
      } else {
        message.error(t('common.error') + ': ' + data.error);
      }
    } catch (err) {
      message.error(t('common.error'));
    }
  };

  const handleWheel = (e: React.WheelEvent) => {
    if (!caseDetail || !caseDetail.images || !caseDetail.images[activeTab] || caseDetail.images[activeTab].length === 0) return;

    if (e.shiftKey) {
      e.preventDefault();
      if (e.deltaY > 0) {
        handleNextSequence();
      } else {
        handlePrevSequence();
      }
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
    if (!caseDetail || !caseDetail.images || !caseDetail.images[activeTab] || caseDetail.images[activeTab].length === 0) return;
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
      return Boolean(target.closest('input, textarea, select, [contenteditable="true"], [contenteditable=""], .report-editor'));
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
  const currentImageUrl = useSharedCaseImageCache({
    dataset: caseDetail?.dataset,
    caseId: caseDetail?.id,
    images: caseDetail?.images?.[activeTab] || [],
    currentIndex: currentImageIndex,
    windowSize: 8,
    concurrency: 3
  });
  const imageFilter = showEnhanced ? 'contrast(150%) brightness(110%)' : 'none';
  const imageTransform = `scaleX(${flipHorizontal ? -1 : 1}) scaleY(${flipVertical ? -1 : 1})`;
  const secondarySplit = Math.max(0.28, 1 - compareSplit);

  const startCompareResize = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
    event.preventDefault();
    const container = dualPaneRef.current;
    if (!container) return;

    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const handleMouseMove = (moveEvent: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      if (rect.width <= 0) return;
      const nextRatio = (moveEvent.clientX - rect.left) / rect.width;
      setCompareSplit(Math.min(0.72, Math.max(0.42, nextRatio)));
    };

    const handleMouseUp = () => {
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
  }, []);

  const handleSliceChange = useCallback((nextSliceIndex: number) => {
    setCurrentImageIndex((prev) =>
      resolveMatrixCellIndex(
        activeLayout,
        nextSliceIndex,
        activePosition.phaseIndex,
        prev
      )
    );
  }, [activeLayout, activePosition.phaseIndex]);

  const handlePhaseChange = useCallback((nextPhaseIndex: number) => {
    setCurrentImageIndex((prev) =>
      resolveMatrixCellIndex(
        activeLayout,
        activePosition.sliceIndex,
        nextPhaseIndex,
        prev
      )
    );
  }, [activeLayout, activePosition.sliceIndex]);

  const renderViewportLabel = (title: string, sliceIndex: number, phaseIndex: number, accent: string) => (
    <div style={workstationViewTheme.viewportLabel(accent)}>
      {title}
      {' · '}
      S{sliceIndex + 1}
      {' / '}
      P{phaseIndex + 1}
    </div>
  );

  const renderOverallQuality = () => (
    <div style={{ marginBottom: '16px', padding: '8px', border: '1px solid transparent', borderRadius: '4px' }}>
      <div style={{ fontSize: '14px', marginBottom: '8px', color: 'var(--text-primary)' }}>
        1. 图像整体质量
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {['good', 'moderate', 'poor'].map(opt => (
            <label key={opt} style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
            <input 
                type="radio" 
                name="overall_quality" 
                checked={formData['overall_quality'] === opt} 
                onChange={() => handleInputChange('overall_quality', opt)}
            />
            <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                {opt === 'good' ? '良好' : opt === 'moderate' ? '中等（可能存在伪影等，但不影响诊断）' : '差（影响诊断）'}
            </span>
            </label>
        ))}
      </div>
    </div>
  );

  const renderArtifactSwitch = () => (
    <div style={{ marginBottom: '16px', padding: '8px', border: '1px solid transparent', borderRadius: '4px' }}>
      <div style={{ fontSize: '14px', marginBottom: '8px', color: 'var(--text-primary)' }}>
        2. 图像是否存在伪影？
      </div>
      <div style={{ display: 'flex', gap: '16px' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
          <input 
            type="radio" 
            name="has_artifacts" 
            checked={formData['has_artifacts'] === true} 
            onChange={() => handleInputChange('has_artifacts', true)}
          />
          <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>是</span>
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
          <input 
            type="radio" 
            name="has_artifacts" 
            checked={formData['has_artifacts'] === false} 
            onChange={() => handleInputChange('has_artifacts', false)}
          />
          <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>否</span>
        </label>
      </div>
    </div>
  );



  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden', width: '100%' }}>
      {/* 2. Main Image Viewer */}
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
        {/* Toolbar */}
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
            {/* View Mode */}
            <button 
                onClick={() => setShowEnhanced(!showEnhanced)}
                style={workstationViewTheme.toolbarButton(showEnhanced)}
            >
                <FaAdjust />
                {t('analysis.contrast_btn')}
            </button>

            <button
                onClick={() => setFlipHorizontal(prev => !prev)}
                style={workstationViewTheme.toolbarButton(flipHorizontal)}
            >
                左右翻转
            </button>

            <button
                onClick={() => setFlipVertical(prev => !prev)}
                style={workstationViewTheme.toolbarButton(flipVertical)}
            >
                上下翻转
            </button>
            
            <div style={{ flex: 1 }}></div>
            
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
            ref={dualPaneRef}
            onWheel={handleWheel}
            style={{
              flex: '0 0 auto',
              minHeight: '560px',
              height: 'clamp(560px, 68vh, 920px)',
              display: 'grid',
              gridTemplateColumns: `minmax(0, ${compareSplit}fr) 8px minmax(0, ${secondarySplit}fr)`,
              gap: '0'
            }}
          >
            <div
              style={{
                position: 'relative',
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
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
                <div style={{ color: 'white' }}>{t('common.loading')}</div>
              ) : currentImageUrl ? (
                <>
                  {renderViewportLabel(`${activeTab} 主视图`, activePosition.sliceIndex, activePosition.phaseIndex, '#fff')}
                  <img
                    src={currentImageUrl}
                    alt={`${activeTab}-${currentImageIndex + 1}`}
                    draggable={false}
                    onContextMenu={(event) => event.preventDefault()}
                    style={{
                      width: '100%',
                      height: '100%',
                      objectFit: 'contain',
                      display: 'block',
                      transform: imageTransform,
                      filter: imageFilter
                    }}
                  />
                </>
              ) : (
                <div style={{ color: loadError ? '#fca5a5' : '#666', padding: 24, textAlign: 'center' }}>{loadError || t('common.no_data')}</div>
              )}
            </div>

            <div
              onMouseDown={startCompareResize}
              role="separator"
              aria-orientation="vertical"
              aria-label="调整双图宽度"
              title="拖动调整主视图和对照视图宽度"
              style={{
                cursor: 'col-resize',
                background: 'linear-gradient(90deg, transparent 0, transparent 3px, rgba(168, 203, 78, 0.7) 3px, rgba(168, 203, 78, 0.7) 5px, transparent 5px, transparent 100%)'
              }}
            />

            <div
              style={{
                position: 'relative',
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                background: '#020202',
                border: `1px solid ${workstationViewTheme.workspace.line}`,
                borderRadius: '2px',
                overflow: 'hidden'
              }}
            >
              {currentImageUrl ? (
                <>
                  {renderViewportLabel(
                    showEnhanced ? `${activeTab} 增强对比` : `${activeTab} 对照视图`,
                    activePosition.sliceIndex,
                    activePosition.phaseIndex,
                    'var(--accent-gold)'
                  )}
                  <img
                    src={currentImageUrl}
                    alt={`${activeTab}-enhanced-${currentImageIndex + 1}`}
                    draggable={false}
                    onContextMenu={(event) => event.preventDefault()}
                    style={{
                      width: '100%',
                      height: '100%',
                      objectFit: 'contain',
                      display: 'block',
                      transform: imageTransform,
                      filter: imageFilter
                    }}
                  />
                </>
              ) : (
                <div style={{ color: '#666', textAlign: 'center', padding: '24px' }}>
                  暂无对比图像
                </div>
              )}
            </div>
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

      {/* 3. Right Sidebar - Questionnaire */}
        <div style={{
          width: rightSidebar.width,
          backgroundColor: workstationViewTheme.workspace.panelEdgeBackground,
          borderLeft: `1px solid ${workstationViewTheme.workspace.line}`,
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
          <span>{t('analysis.title')}</span>
          <button onClick={handleSubmit} style={workstationViewTheme.actionButton}>
            <FaSave /> {t('common.save')}
          </button>
        </div>
        
        <div
          className="workstation-scroll-pane"
          style={{
            flex: 1,
            overflowY: 'auto',
            overflowX: 'hidden',
            padding: '16px'
          }}
        >
          {renderOverallQuality()}
          {renderArtifactSwitch()}
          
          {formData['has_artifacts'] === true && (
              <div style={{ marginTop: '16px', borderTop: '1px solid var(--border-color)', paddingTop: '16px' }}>
                  <div style={{ fontSize: '14px', marginBottom: '8px', color: 'var(--text-primary)' }}>
                    3. 伪影严重程度
                  </div>
                  <div style={{ display: 'flex', gap: '16px' }}>
                    {['mild', 'moderate', 'severe'].map(level => (
                        <label key={level} style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                          <input 
                            type="radio" 
                            name="artifact_severity" 
                            checked={formData['artifact_severity'] === level} 
                            onChange={() => handleInputChange('artifact_severity', level)}
                          />
                          <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                            {level === 'mild' ? '轻度' : level === 'moderate' ? '中度' : '重度'}
                          </span>
                        </label>
                    ))}
                  </div>
              </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ImageAnalysisView;
