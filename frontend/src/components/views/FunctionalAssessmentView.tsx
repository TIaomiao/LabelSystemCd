import React, { useState, useEffect, useRef, useMemo } from 'react';
import { FaSave, FaRuler, FaChevronLeft, FaChevronRight } from 'react-icons/fa';
import { message } from 'antd';
import { useResizable } from '../../hooks/useResizable';
import { useLanguage } from '../../context/LanguageContext';
import MeasurementViewer from '../MeasurementViewer';
import { buildSequenceMatrixLayout, numericLabel, resolveMatrixCellIndex, workstationViewTheme } from './workstationViewShared';
import WorkstationStackMatrix from './WorkstationStackMatrix';
import WorkstationNavigatorBar from './WorkstationNavigatorBar';
import { useSharedCaseImageCache } from './useSharedCaseImageCache';
import './workstationPaneScroll.css';

interface FunctionalAssessmentViewProps {
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
  report_metrics?: Record<string, number | string>;
  ai_metrics?: Record<string, number | string>;
}

type MetricReviewRow = {
  ai: number | string | null;
  report: number | string | null;
  consistent: boolean;
  comment: string;
};

const FUNCTIONAL_METRIC_ORDER = [
  'LVEDV', 'LVESV', 'SV', 'LVEF',
  'RVEDV', 'RVESV', 'RVEF',
  'LAV', 'RAV',
  'LVEDD', 'RVEDD', 'IVS', 'LVPW',
  'LA_LR', 'LA_SI', 'RA_LR', 'RA_SI',
  'RWT', 'SI', 'LV/RV ratio'
];

const hasOwn = (value: unknown, key: string): value is Record<string, unknown> => (
  Boolean(value) && typeof value === 'object' && Object.prototype.hasOwnProperty.call(value, key)
);

const buildMetricReviewRows = (data: CaseDetail): Record<string, MetricReviewRow> => {
  const savedRows = data.assessment?.metrics_data && typeof data.assessment.metrics_data === 'object'
    ? data.assessment.metrics_data as Record<string, Partial<MetricReviewRow>>
    : {};
  const keys = Array.from(new Set([
    ...FUNCTIONAL_METRIC_ORDER,
    ...Object.keys(data.report_metrics || {}),
    ...Object.keys(data.ai_metrics || {}),
    ...Object.keys(savedRows)
  ]));

  return Object.fromEntries(keys.map(key => {
    const saved = savedRows[key] || {};
    const currentAi = hasOwn(data.ai_metrics, key) ? data.ai_metrics?.[key] : saved.ai;
    const currentReport = hasOwn(data.report_metrics, key) ? data.report_metrics?.[key] : saved.report;
    return [key, {
      ai: currentAi ?? null,
      report: currentReport ?? null,
      consistent: saved.consistent ?? true,
      comment: saved.comment ?? ''
    } satisfies MetricReviewRow];
  }));
};

const FunctionalAssessmentView: React.FC<FunctionalAssessmentViewProps> = ({
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
  const [isMeasureMode, setIsMeasureMode] = useState(false);
  const [matrixHeight, setMatrixHeight] = useState(() => {
    const saved = localStorage.getItem('functional-matrix-height');
    const parsed = saved ? parseFloat(saved) : NaN;
    return Number.isFinite(parsed) ? Math.min(132, Math.max(96, parsed)) : 108;
  });
  
  // Form State
  const [formData, setFormData] = useState<Record<string, string | null>>({});
  // Metrics Consistency State
  const [metricsData, setMetricsData] = useState<Record<string, MetricReviewRow>>({});

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
    storageKey: 'functional-right-sidebar'
  });

  useEffect(() => {
    localStorage.setItem('functional-matrix-height', String(matrixHeight));
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
    setLoadError('');
    setCaseDetail(null);
    setFormData({}); // Reset form
    const reviewQuery = reviewUserId ? `?review_user_id=${reviewUserId}` : '';
    try {
      const res = await fetch(`/api/functional/cases/${ds}/${id}${reviewQuery}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `病例加载失败（HTTP ${res.status}）`);
      setCaseDetail(data);
      
      // Auto select first available sequence
      if (data.images && data.images['SAX'] && data.images['SAX'].length > 0) setActiveTab('SAX');
      else if (data.images && data.images['4CH'] && data.images['4CH'].length > 0) setActiveTab('4CH');
      else if (data.images && data.images['LGE'] && data.images['LGE'].length > 0) setActiveTab('LGE');

      if (data.assessment && data.assessment.answers) {
        setFormData(data.assessment.answers);
      }
      
      // Keep the assessment table shape stable across cases and computers.
      // Missing values remain visible as "未计算" instead of disappearing.
      setMetricsData(buildMetricReviewRows(data));

    } catch (err) {
      console.error("Failed to fetch case detail", err);
      setLoadError(err instanceof Error ? err.message : '病例影像加载失败');
    } finally {
      setLoading(false);
    }
  };

  const handleInputChange = (key: string, value: string) => {
    setFormData(prev => ({
      ...prev,
      [key]: value
    }));
  };

  const handleSubmit = async () => {
    if (!caseDetail) return;
    
    try {
      const payload = {
          ...formData,
          metrics_data: metricsData,
          review_user_id: reviewUserId ?? undefined,
      };
      const res = await fetch(`/api/functional/cases/${caseDetail.dataset}/${caseDetail.id}/assessment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
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

  const copyDiagnosticInfo = async () => {
    const rawCaseKey = `${dataset}:${caseId}`;
    let caseRef = 'hash-unavailable';
    try {
      const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(rawCaseKey));
      caseRef = Array.from(new Uint8Array(digest)).slice(0, 8).map(value => value.toString(16).padStart(2, '0')).join('');
    } catch {
      // Keep the raw case identifier out of copied feedback even on older browsers.
    }
    const version = Array.from(document.querySelectorAll('span, div'))
      .map(node => (node.textContent || '').trim())
      .find(text => /^v\d{4}\.\d{2}\.\d{2}/.test(text)) || null;
    const presentAi = Object.entries(metricsData).filter(([, row]) => row.ai !== null && row.ai !== undefined).map(([key]) => key);
    const presentReport = Object.entries(metricsData).filter(([, row]) => row.report !== null && row.report !== undefined).map(([key]) => key);
    const diagnostic = {
      workstation_version: version,
      page: 'functional-assessment',
      case_ref: caseRef,
      browser: navigator.userAgent,
      platform: navigator.platform,
      viewport: { width: window.innerWidth, height: window.innerHeight, device_pixel_ratio: window.devicePixelRatio },
      active_sequence: activeTab,
      image_index: currentImageIndex,
      sequence_counts: {
        SAX: caseDetail?.images?.SAX?.length || 0,
        '4CH': caseDetail?.images?.['4CH']?.length || 0,
        LGE: caseDetail?.images?.LGE?.length || 0
      },
      metric_keys_with_ai: presentAi,
      metric_keys_with_report: presentReport,
      metric_keys_missing_both: FUNCTIONAL_METRIC_ORDER.filter(key => !presentAi.includes(key) && !presentReport.includes(key)),
      saved_assessment_loaded: Boolean(caseDetail?.assessment)
    };
    const feedback = [
      'CMR 功能评估问题反馈',
      `发生时间：${new Date().toLocaleString()}`,
      '页面/模块：功能评估',
      '发生前操作：',
      '预期结果：',
      '实际结果：',
      '出现次数：必现 / 偶发 / 第一次',
      '是否刷新/换电脑：',
      '诊断信息：',
      JSON.stringify(diagnostic, null, 2)
    ].join('\n');
    try {
      await navigator.clipboard.writeText(feedback);
      message.success('诊断信息已复制，可直接粘贴到反馈群');
    } catch {
      window.prompt('浏览器未允许自动复制，请手动复制以下诊断信息：', feedback);
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

  const renderViewportLabel = (title: string, sliceIndex: number, phaseIndex: number, accent: string) => (
    <div style={workstationViewTheme.viewportLabel(accent)}>
      {title}
      {' · '}
      S{sliceIndex + 1}
      {' / '}
      P{phaseIndex + 1}
    </div>
  );

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

  const getOptionKey = (cnValue: string): string => {
    const map: Record<string, string> = {
      '显著降低': 'func.opt.significantly_decreased',
      '降低': 'func.opt.decreased',
      '正常': 'func.opt.normal',
      '升高': 'func.opt.increased',
      '显著升高': 'func.opt.significantly_increased',
      '显著扩大': 'func.opt.significantly_enlarged',
      '扩大': 'func.opt.enlarged',
      '显著缩小': 'func.opt.significantly_shrunk',
      '缩小': 'func.opt.shrunk',
      '显著增厚': 'func.opt.significantly_thickened',
      '增厚': 'func.opt.thickened',
      '显著变薄': 'func.opt.significantly_thinned',
      '变薄': 'func.opt.thinned',
      '显著增大': 'func.opt.significantly_increased',
    };
    return map[cnValue] || '';
  };

  const renderMetricsTable = () => {
      if (Object.keys(metricsData).length === 0) return null;
      const extraKeys = Object.keys(metricsData).filter(key => !FUNCTIONAL_METRIC_ORDER.includes(key)).sort();
      const orderedKeys = [...FUNCTIONAL_METRIC_ORDER.filter(key => metricsData[key]), ...extraKeys];
      
      return (
          <div style={{ marginBottom: '20px', borderBottom: '1px solid var(--border-color)', paddingBottom: '16px' }}>
              <h4 style={{ margin: '0 0 12px 0', color: 'var(--accent-gold)', fontSize: '15px' }}>Quantitative Assessment</h4>
              <div style={{ margin: '0 0 10px 0', color: 'var(--text-muted)', fontSize: '11px', lineHeight: 1.5 }}>
                指标名称固定展示；“未计算”表示当前病例的 AI 或报告源没有提供该数值，不是电脑缺少功能。
              </div>
              <table style={{ width: '100%', fontSize: '12px', color: 'var(--text-secondary)', borderCollapse: 'collapse' }}>
                  <thead>
                      <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                          <th style={{ textAlign: 'left', padding: '4px' }}>Metric</th>
                          <th style={{ textAlign: 'right', padding: '4px' }}>AI</th>
                          <th style={{ textAlign: 'right', padding: '4px' }}>Report</th>
                          <th style={{ textAlign: 'center', padding: '4px' }}>OK</th>
                      </tr>
                  </thead>
                  <tbody>
                      {orderedKeys.map(key => (
                          <tr key={key} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                              <td style={{ padding: '4px' }}>{key}</td>
                              <td style={{ textAlign: 'right', padding: '4px' }}>{metricsData[key].ai ?? '未计算'}</td>
                              <td style={{ textAlign: 'right', padding: '4px' }}>{metricsData[key].report ?? '未计算'}</td>
                              <td style={{ textAlign: 'center', padding: '4px' }}>
                                  <input 
                                      type="checkbox" 
                                      checked={metricsData[key].consistent} 
                                      onChange={(e) => {
                                          setMetricsData(prev => ({
                                              ...prev,
                                              [key]: { ...prev[key], consistent: e.target.checked }
                                          }));
                                      }}
                                  />
                              </td>
                          </tr>
                      ))}
                  </tbody>
              </table>
          </div>
      );
  };

  const renderQuestion = (labelKey: string, key: string, options: string[]) => (
    <div style={{ marginBottom: '16px' }}>
      <div style={{ fontSize: '14px', marginBottom: '8px', color: 'var(--text-primary)' }}>{t(labelKey)}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {options.map(option => {
            const optKey = getOptionKey(option);
            const displayLabel = optKey ? t(optKey) : option;
            return (
                <label key={option} style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                <input 
                    type="radio" 
                    name={key} 
                    checked={formData[key] === option} 
                    onChange={() => handleInputChange(key, option)}
                />
                <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{displayLabel}</span>
                </label>
            );
        })}
      </div>
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

          <button
            onClick={() => void copyDiagnosticInfo()}
            style={workstationViewTheme.toolbarButton(false)}
            title="复制不含患者信息的浏览器、版本和指标加载状态"
          >
            复制诊断信息
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
              border: '1px solid #1f1f1f',
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
            ) : currentImageUrl ? (
              <>
                {renderViewportLabel(`${activeTab} 主视图`, activePosition.sliceIndex, activePosition.phaseIndex, '#fff')}
                <MeasurementViewer
                  imageUrl={currentImageUrl}
                  pixelSpacing={caseDetail?.metadata?.[activeTab]?.pixel_spacing || null}
                  isActive={isMeasureMode}
                />
              </>
            ) : (
              <div style={{ width: '100%', height: '100%', display: 'grid', placeItems: 'center', color: loadError ? '#fca5a5' : '#666', padding: 24, textAlign: 'center' }}>{loadError || t('common.no_data')}</div>
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
          <span>{t('func.title')}</span>
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
          {renderMetricsTable()}
        </div>
      </div>
    </div>
  );
};

export default FunctionalAssessmentView;
