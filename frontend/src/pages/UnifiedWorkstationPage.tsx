import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FaBrain,
  FaChartBar,
  FaDatabase,
  FaChevronLeft,
  FaChevronRight,
  FaExternalLinkAlt,
  FaFileAlt,
  FaHeartbeat,
  FaHome,
  FaHospital,
  FaInfoCircle,
  FaMicroscope,
  FaSave,
  FaSearch,
  FaSignOutAlt,
  FaSyncAlt,
  FaUserMd
} from 'react-icons/fa';
import { useAuth } from '../context/AuthContext';
import HospitalDiseaseBrowserPage from './HospitalDiseaseBrowserPage';
import ExperimentResultsPage from './ExperimentResultsPage';
import FunctionalAssessmentView from '../components/views/FunctionalAssessmentView';
import ImageAnalysisView from '../components/views/ImageAnalysisView';
import StructureAssessmentView from '../components/views/StructureAssessmentView';
import LGEAnalysisView from '../components/views/LGEAnalysisView';
import OtherFindingsView from '../components/views/OtherFindingsView';
import EvaluationView from '../components/views/EvaluationView';
import FunctionQcView from './FunctionQcView';
import { WORKSTATION_CHANGELOG, WORKSTATION_VERSION } from '../utils/workstationMeta';
import { flushCviIframeAutosave } from '../utils/cviAutosave';
import './UnifiedWorkstationPage.css';

interface CviCase {
  id: number;
  source: string;
  dataset: string;
  case_id: string;
  full_id: string;
  path: string;
  sequence_summary: { name: string; dicom_count: number }[];
  dicom_count: number;
  has_dicom: boolean;
  cvi_study_id?: number | null;
  anon_label?: string;
  public_case_code?: string;
  imported_at?: string | null;
  annotation_summary?: {
    is_annotated: boolean;
    completed_modules: string[];
    completed_count: number;
    latest_annotation_at?: string | null;
  };
}

interface CviSource {
  value: string;
  label: string;
  root: string;
}

interface ReviewUser {
  id: number;
  username: string;
  is_admin?: boolean;
}

type ModuleKey =
  | 'cvi'
  | 'imageAnalysis'
  | 'functional'
  | 'structure'
  | 'lge'
  | 'otherFindings'
  | 'evaluation'
  | 'functionQc'
  | 'hospital'
  | 'experiment'
  | 'legacy';

interface ModuleDefinition {
  key: ModuleKey;
  label: string;
  description: string;
  icon: React.ReactNode;
  needsCase?: boolean;
  scroll?: boolean;
}

const sourceLabel: Record<string, string> = {
  annotation: '原标注目录',
  functional: '病例库'
};

const mergeSourceOptions = (serverSources: CviSource[]): CviSource[] => serverSources || [];

const applyClientSourceFilter = (items: CviCase[], sourceValue: string): CviCase[] => {
  if (!sourceValue || sourceValue === 'all' || sourceValue === 'functional' || sourceValue === 'annotation') {
    return items;
  }
  if (!sourceValue.startsWith('functional::')) {
    return items;
  }
  const [, dataset, scope] = sourceValue.split('::');
  let filtered = items.filter(item => item.source === 'functional' && item.dataset === dataset);
  if (scope === 'report100') {
    filtered = filtered.slice().sort((a, b) => a.case_id.localeCompare(b.case_id));
  }
  return filtered;
};

const modules: ModuleDefinition[] = [
  {
    key: 'cvi',
    label: 'CMR 工作站',
    description: 'SAX cine / 4CH / LGE 轮廓、传播和报告工作流',
    icon: <FaHeartbeat />
  },
  {
    key: 'imageAnalysis',
    label: '影像质量',
    description: '影像质量、伪影和图像分析记录',
    icon: <FaMicroscope />,
    needsCase: true
  },
  {
    key: 'functional',
    label: '功能评估',
    description: '心功能定量、报告一致性和功能项评估',
    icon: <FaFileAlt />,
    needsCase: true
  },
  {
    key: 'structure',
    label: '结构评估',
    description: '心脏形态、室壁、瓣膜和结构异常评估',
    icon: <FaHospital />,
    needsCase: true
  },
  {
    key: 'lge',
    label: 'LGE 分析',
    description: 'LGE 强化模式、范围和相关发现记录',
    icon: <FaBrain />,
    needsCase: true
  },
  {
    key: 'otherFindings',
    label: '其他发现',
    description: '血栓、积液、脂肪浸润和其他补充发现',
    icon: <FaSearch />,
    needsCase: true
  },
  {
    key: 'evaluation',
    label: '报告评分',
    description: '覆盖度、一致性和幻觉风险评分',
    icon: <FaChartBar />,
    needsCase: true
  },
  {
    key: 'functionQc',
    label: '心功能验收',
    description: 'ED/ES、EF、体积曲线和关键帧分割验收',
    icon: <FaHeartbeat />
  },
  {
    key: 'hospital',
    label: '医院病例树',
    description: '保留原医院/疾病/病例树浏览方式',
    icon: <FaDatabase />
  },
  {
    key: 'experiment',
    label: '实验结果',
    description: '模型实验结果与统计视图',
    icon: <FaChartBar />,
    scroll: true
  },
  {
    key: 'legacy',
    label: '旧入口',
    description: '保留原页面入口，便于迁移期间对照验证',
    icon: <FaExternalLinkAlt />,
    scroll: true
  }
];

const assessmentModules = new Set<ModuleKey>([
  'imageAnalysis',
  'functional',
  'structure',
  'lge',
  'otherFindings',
  'evaluation'
]);

const CASE_FETCH_LIMIT = 300;
const CASE_FETCH_LIMIT_FALLBACK = 5000;

const UnifiedWorkstationPage: React.FC = () => {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [selectedModule, setSelectedModule] = useState<ModuleKey>('cvi');
  const [workstationUrl, setWorkstationUrl] = useState('/cvi-workstation-app/');
  const [cases, setCases] = useState<CviCase[]>([]);
  const [sources, setSources] = useState<CviSource[]>([]);
  const [source, setSource] = useState('functional::CMR_ALL::report100');
  const [annotationStatus, setAnnotationStatus] = useState<'all' | 'annotated' | 'pending'>('all');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [loadingCases, setLoadingCases] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [openingId, setOpeningId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);
  const [reviewUsers, setReviewUsers] = useState<ReviewUser[]>([]);
  const [reviewUserId, setReviewUserId] = useState<number | null>(null);
  const [casePanelWidth, setCasePanelWidth] = useState(330);
  const [casePanelCollapsed, setCasePanelCollapsed] = useState(false);
  const [showChangeLog, setShowChangeLog] = useState(false);
  const workstationFrameRef = useRef<HTMLIFrameElement | null>(null);

  const selectedCase = useMemo(
    () => cases.find(item => item.id === selectedCaseId) || null,
    [cases, selectedCaseId]
  );
  const selectedCaseIndex = useMemo(
    () => cases.findIndex(item => item.id === selectedCaseId),
    [cases, selectedCaseId]
  );
  const previousCase = useMemo(() => {
    if (!cases.length) return null;
    if (selectedCaseIndex < 0) return cases[0];
    if (cases.length <= 1) return null;
    return cases[(selectedCaseIndex - 1 + cases.length) % cases.length];
  }, [cases, selectedCaseIndex]);
  const nextCase = useMemo(() => {
    if (!cases.length) return null;
    if (selectedCaseIndex < 0) return cases[0];
    if (cases.length <= 1) return null;
    return cases[(selectedCaseIndex + 1) % cases.length];
  }, [cases, selectedCaseIndex]);
  const embeddedWorkstationUrl = useMemo(() => {
    const separator = workstationUrl.includes('?') ? '&' : '?';
    return `${workstationUrl}${separator}embedded=1`;
  }, [workstationUrl]);
  const activeModule = modules.find(item => item.key === selectedModule) || modules[0];
  const sourceOptions = useMemo(
    () => mergeSourceOptions(sources),
    [sources]
  );

  useEffect(() => {
    const previous = document.documentElement.getAttribute('data-theme');
    document.documentElement.setAttribute('data-theme', 'dark');
    return () => {
      if (previous) {
        document.documentElement.setAttribute('data-theme', previous);
      } else {
        document.documentElement.removeAttribute('data-theme');
      }
    };
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(searchInput.trim());
    }, 250);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    if (!showChangeLog) return;

    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('[data-uws-changelog-root="true"]')) return;
      setShowChangeLog(false);
    };

    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, [showChangeLog]);

  const loadCases = useCallback(async (refresh = false) => {
    setLoadingCases(!refresh);
    setRefreshing(refresh);
    setError(null);
    try {
      const params = new URLSearchParams({
        source,
        search,
        limit: String(CASE_FETCH_LIMIT),
        annotation_status: annotationStatus
      });
      if (user?.is_admin && reviewUserId) params.set('review_user_id', String(reviewUserId));
      if (refresh) params.set('refresh', '1');
      let response = await fetch(`/api/cvi-library/cases?${params.toString()}`);
      let payload = await response.json();
      let usedCompatibilityFallback = false;
      if (!response.ok && payload?.error === 'Unknown source' && source.startsWith('functional::')) {
        const fallbackParams = new URLSearchParams({
          source: 'functional',
          search,
          limit: String(CASE_FETCH_LIMIT_FALLBACK),
          annotation_status: annotationStatus
        });
        if (user?.is_admin && reviewUserId) fallbackParams.set('review_user_id', String(reviewUserId));
        if (refresh) fallbackParams.set('refresh', '1');
        response = await fetch(`/api/cvi-library/cases?${fallbackParams.toString()}`);
        payload = await response.json();
        usedCompatibilityFallback = response.ok;
      }
      if (!response.ok) {
        throw new Error(payload.error || '病例库加载失败');
      }
      const items: CviCase[] = usedCompatibilityFallback
        ? applyClientSourceFilter(payload.items || [], source)
        : (payload.items || []);
      setCases(items);
      const nextSources = mergeSourceOptions(payload.sources || []);
      setSources(nextSources);
      const nextSource = payload.source || nextSources[0]?.value;
      if (nextSource && !nextSources.some(item => item.value === source)) setSource(nextSource);
      setReviewUsers(payload.review_users || []);
      if (user?.is_admin) {
        setReviewUserId(current => {
          if (current && (payload.review_users || []).some((item: ReviewUser) => item.id === current)) return current;
          return payload.review_user_id || current || null;
        });
      }
      setSelectedCaseId(current => {
        if (current && items.some(item => item.id === current)) return current;
        return items[0]?.id ?? null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '病例库加载失败');
    } finally {
      setLoadingCases(false);
      setRefreshing(false);
    }
  }, [annotationStatus, reviewUserId, search, source, user?.is_admin]);

  useEffect(() => {
    loadCases(false);
  }, [loadCases]);

  const resizeCasePanel = useCallback((nextWidth: number) => {
    setCasePanelWidth(Math.min(540, Math.max(240, Math.round(nextWidth))));
  }, []);

  const startCasePanelResize = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
    if (casePanelCollapsed) return;
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = casePanelWidth;
    document.body.classList.add('uws-is-resizing');

    const handleMove = (moveEvent: MouseEvent) => {
      resizeCasePanel(startWidth + moveEvent.clientX - startX);
    };

    const handleUp = () => {
      document.body.classList.remove('uws-is-resizing');
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', handleUp);
    };

    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', handleUp);
  }, [casePanelCollapsed, casePanelWidth, resizeCasePanel]);

  const flushCurrentContours = useCallback(async () => {
    try {
      await flushCviIframeAutosave(workstationFrameRef.current);
    } catch (err) {
      throw new Error(err instanceof Error ? err.message : '当前轮廓自动保存失败，请先点击工作站内“保存轮廓”后再切换病例。');
    }
  }, []);

  const openCaseInCvi = async (caseItem = selectedCase, force = false, switchModule = true) => {
    if (!caseItem) return;
    setOpeningId(caseItem.id);
    setError(null);
    try {
      await flushCurrentContours();
      const response = await fetch(`/api/cvi-library/cases/${caseItem.id}/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || '导入工作站失败');
      }
      const studyId = payload.study_id;
      setSelectedCaseId(caseItem.id);
      setWorkstationUrl(`/cvi-workstation-app/study/${studyId}/function`);
      if (switchModule) {
        setSelectedModule('cvi');
      }
      setCases(prev => prev.map(item => (
        item.id === caseItem.id
          ? { ...item, cvi_study_id: studyId, imported_at: new Date().toISOString() }
          : item
      )));
    } catch (err) {
      setError(err instanceof Error ? err.message : '导入工作站失败');
    } finally {
      setOpeningId(null);
    }
  };

  const switchToCase = (caseItem: CviCase | null) => {
    if (!caseItem) return;
    if (selectedModule === 'cvi') {
      openCaseInCvi(caseItem);
      return;
    }
    setSelectedCaseId(caseItem.id);
  };

  const activateModule = (nextModule: ModuleKey) => {
    if (nextModule === 'cvi') {
      if (!selectedCase) {
        setSelectedModule('cvi');
        return;
      }
      void openCaseInCvi(selectedCase, false, true);
      return;
    }
    setSelectedModule(nextModule);
  };

  const goToNextCase = () => {
    switchToCase(nextCase);
  };

  const goToPreviousCase = () => {
    switchToCase(previousCase);
  };

  const caseSubtitle = selectedCase
    ? `${sourceLabel[selectedCase.source] || selectedCase.source} / ${selectedCase.dataset} / ${selectedCase.anon_label || '匿名病例'}`
    : '请选择左侧病例';

  const renderCaseList = () => {
    if (loadingCases) {
      return <div className="uws-empty">正在加载病例库...</div>;
    }
    if (!cases.length) {
      return <div className="uws-empty">没有找到匹配病例。</div>;
    }
    return cases.map(caseItem => {
      const selected = selectedCaseId === caseItem.id;
      const busy = openingId === caseItem.id;
      const sequenceSummary = caseItem.sequence_summary
        .filter(item => item.dicom_count > 0)
        .slice(0, 4);
      return (
        <div
          key={caseItem.id}
          className={`uws-case-card${selected ? ' is-active' : ''}`}
          role="button"
          tabIndex={0}
          onClick={() => switchToCase(caseItem)}
          onKeyDown={event => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              switchToCase(caseItem);
            }
          }}
        >
          <div className="uws-case-title">
            <strong title={caseItem.public_case_code || caseItem.anon_label || '匿名病例'}>{caseItem.anon_label || '匿名病例'}</strong>
            <button
              className="uws-button"
              disabled={busy || !caseItem.has_dicom}
              onClick={event => {
                event.stopPropagation();
                if (selectedModule === 'cvi') {
                  openCaseInCvi(caseItem);
                  return;
                }
                setSelectedCaseId(caseItem.id);
              }}
            >
              {busy ? '导入中' : selectedModule === 'cvi' ? (caseItem.cvi_study_id ? '打开' : '导入') : '设为当前'}
            </button>
          </div>
          <div className="uws-case-meta">
            {sourceLabel[caseItem.source] || caseItem.source} / {caseItem.dataset}
          </div>
          <div className="uws-chip-row">
            <span className={`uws-chip${caseItem.has_dicom ? ' is-ok' : ' is-warn'}`}>
              {caseItem.has_dicom ? `${caseItem.dicom_count} DICOM` : '未发现 DICOM'}
            </span>
            {caseItem.cvi_study_id && <span className="uws-chip is-ok">CVI 已导入</span>}
            {sequenceSummary.map(item => (
              <span className="uws-chip" key={`${caseItem.id}-${item.name}`}>
                {item.name} {item.dicom_count}
              </span>
            ))}
            {caseItem.annotation_summary?.completed_count ? (
              <span className="uws-chip is-ok">已标注 {caseItem.annotation_summary.completed_count}</span>
            ) : (
              <span className="uws-chip is-warn">未标注</span>
            )}
          </div>
          {caseItem.annotation_summary?.latest_annotation_at && (
            <div className="uws-case-meta">
              最近标注：{new Date(caseItem.annotation_summary.latest_annotation_at).toLocaleString()}
            </div>
          )}
        </div>
      );
    });
  };

  const renderNeedsCaseEmpty = () => (
    <div className="uws-empty">
      <div>
        <strong>先选择一个病例</strong>
        <p>左侧病例选中后，这里会打开 {activeModule.label}。原有保存接口和医生历史数据保持不变。</p>
      </div>
    </div>
  );

  const renderAssessmentModule = () => {
    if (!selectedCase) return renderNeedsCaseEmpty();
    const props = {
      dataset: selectedCase.dataset,
      caseId: selectedCase.case_id,
      reviewUserId,
      exportCases: cases.map(item => ({
        dataset: item.dataset,
        caseId: item.case_id,
        anonLabel: item.anon_label,
      })),
    };
    if (selectedModule === 'imageAnalysis') return <ImageAnalysisView {...props} />;
    if (selectedModule === 'functional') return <FunctionalAssessmentView {...props} />;
    if (selectedModule === 'structure') return <StructureAssessmentView {...props} />;
    if (selectedModule === 'lge') return <LGEAnalysisView {...props} />;
    if (selectedModule === 'otherFindings') return <OtherFindingsView {...props} />;
    return <EvaluationView {...props} />;
  };

  const renderLegacyLinks = () => {
    const links = [
      { label: '患者管理', path: '/patients', note: '原病例管理入口' },
      { label: 'CMR 工作站旧页', path: '/cvi-workstation', note: '迁移前工作站嵌入页' },
      { label: '医院病例树', path: '/hospital-browser', note: '原医院/疾病树页面' },
      { label: '实验结果', path: '/experiment', note: '原实验结果页面' }
    ];
    return (
      <div className="uws-quick-links">
        {links.map(item => (
          <button
            className="uws-quick-card"
            key={item.path}
            onClick={() => navigate(item.path)}
          >
            <strong>{item.label}</strong>
            <span>{item.note}</span>
          </button>
        ))}
      </div>
    );
  };

  const renderPatientNav = () => (
    <div className="uws-patient-nav" aria-label="病例导航">
      <button
        className="uws-patient-nav-button"
        onClick={goToPreviousCase}
        disabled={!previousCase || openingId === previousCase.id}
        title={previousCase ? `上一位：${previousCase.anon_label || '匿名病例'}` : '没有上一位患者'}
      >
        <FaChevronLeft />
        {openingId === previousCase?.id ? '导入中' : '上一位'}
      </button>
      <div className="uws-patient-nav-current" title={caseSubtitle}>
        <span>当前病例</span>
        <strong>{selectedCase?.anon_label || '未选择'}</strong>
      </div>
      <button
        className="uws-patient-nav-button is-primary"
        onClick={goToNextCase}
        disabled={!nextCase || openingId === nextCase.id}
        title={nextCase ? `下一位：${nextCase.anon_label || '匿名病例'}` : '没有下一位患者'}
      >
        {openingId === nextCase?.id ? '导入中' : '下一位'}
        <FaChevronRight />
      </button>
    </div>
  );

  const renderWorkArea = () => {
    if (selectedModule === 'cvi') {
      return (
        <iframe
          ref={workstationFrameRef}
          title="CMR Workstation"
          className="uws-frame"
          src={embeddedWorkstationUrl}
        />
      );
    }
    if (assessmentModules.has(selectedModule)) {
      return <div className="uws-assessment-wrap">{renderAssessmentModule()}</div>;
    }
    if (selectedModule === 'hospital') {
      return <div className="uws-legacy-fill"><HospitalDiseaseBrowserPage /></div>;
    }
    if (selectedModule === 'functionQc') {
      return <FunctionQcView />;
    }
    if (selectedModule === 'experiment') {
      return <ExperimentResultsPage />;
    }
    return renderLegacyLinks();
  };

  const workAreaScrollable = activeModule.scroll || selectedModule === 'legacy';

  return (
    <div className="unified-workstation">
      <header className="uws-topbar">
        <div className="uws-brand">
          <div className="uws-brand-row">
            <strong>CMR Workstation</strong>
            <span className="uws-version-badge">{WORKSTATION_VERSION}</span>
          </div>
        </div>
        <nav className="uws-module-tabs" aria-label="工作站模块">
          {modules.map(item => (
            <button
              key={item.key}
              className={`uws-tab${selectedModule === item.key ? ' is-active' : ''}`}
              onClick={() => activateModule(item.key)}
              title={item.description}
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </nav>
        {renderPatientNav()}
        <div className="uws-userbar">
          <span>{user?.username || 'User'}</span>
          <div className="uws-changelog-root" data-uws-changelog-root="true">
            <button
              className={`uws-button${showChangeLog ? ' is-primary' : ''}`}
              onClick={() => setShowChangeLog(value => !value)}
              title="查看更新日志"
            >
              <FaInfoCircle />
              更新日志
            </button>
            {showChangeLog && (
              <div className="uws-changelog-panel">
                <div className="uws-changelog-head">
                  <strong>工作台更新日志</strong>
                  <span>当前版本 {WORKSTATION_VERSION}</span>
                </div>
                <div className="uws-changelog-list">
                  {WORKSTATION_CHANGELOG.map(entry => (
                    <section className="uws-changelog-entry" key={entry.version}>
                      <div className="uws-changelog-entry-head">
                        <strong>{entry.version}</strong>
                        <span>{entry.date}</span>
                      </div>
                      <ul>
                        {entry.items.map(item => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </section>
                  ))}
                </div>
              </div>
            )}
          </div>
          <button
            className="uws-button"
            onClick={() => window.location.assign('/showcase/')}
            title="返回主页"
          >
            <FaHome />
            返回主页
          </button>
          {user?.is_admin && (
            <button className="uws-button" onClick={() => navigate('/admin/monitor')} title="后台监控">
              <FaChartBar />
              后台监控
            </button>
          )}
          <button className="uws-button" onClick={logout} title="退出登录">
            <FaSignOutAlt />
          </button>
          <div className="uws-avatar">{user?.username?.[0]?.toUpperCase() || 'U'}</div>
        </div>
      </header>

      <div
        className={`uws-main${casePanelCollapsed ? ' is-case-collapsed' : ''}`}
        style={{
          gridTemplateColumns: casePanelCollapsed
            ? '48px minmax(0, 1fr)'
            : `${casePanelWidth}px minmax(0, 1fr)`
        }}
      >
        <aside className={`uws-case-panel${casePanelCollapsed ? ' is-collapsed' : ''}`}>
          <button
            className="uws-case-collapse"
            onClick={() => setCasePanelCollapsed(value => !value)}
            title={casePanelCollapsed ? '展开病例库' : '折叠病例库'}
          >
            {casePanelCollapsed ? <FaChevronRight /> : <FaChevronLeft />}
            <span>{casePanelCollapsed ? '病例' : '收起'}</span>
          </button>
          <div className="uws-case-panel-body">
            <div className="uws-case-head">
            <h2>病例库</h2>
            {user?.is_admin && (
              <select
                className="uws-field"
                value={reviewUserId ?? ''}
                onChange={event => setReviewUserId(event.target.value ? Number(event.target.value) : null)}
              >
                <option value="">查看我自己</option>
                {reviewUsers.map(item => (
                  <option key={item.id} value={item.id}>{item.username}</option>
                ))}
              </select>
            )}
            <select
              className="uws-field"
              value={source}
              onChange={event => setSource(event.target.value)}
            >
              <option value="all">全部目录</option>
              {sourceOptions.map(item => (
                <option key={item.value} value={item.value}>{item.label}</option>
              ))}
            </select>
            <div className="uws-filter-row">
              <input
                className="uws-field"
                value={searchInput}
                onChange={event => setSearchInput(event.target.value)}
                placeholder="搜索病例号 / 数据集"
              />
              <select
                className="uws-field"
                value={annotationStatus}
                onChange={event => setAnnotationStatus(event.target.value as 'all' | 'annotated' | 'pending')}
              >
                <option value="all">全部状态</option>
                <option value="annotated">只看已标注</option>
                <option value="pending">只看未标注</option>
              </select>
              <button
                className="uws-button"
                onClick={() => loadCases(true)}
                disabled={refreshing}
                title="刷新病例库"
              >
                <FaSyncAlt />
              </button>
            </div>
            {error && <div className="uws-error">{error}</div>}
          </div>
          <div className="uws-case-list">
            <div className="uws-case-meta" style={{ padding: '0 18px 10px' }}>
              已加载 {cases.length} 例，当前显示 {cases.length} 例
            </div>
            {renderCaseList()}
          </div>
          </div>
          <div
            className="uws-case-resizer"
            onMouseDown={startCasePanelResize}
            role="separator"
            aria-orientation="vertical"
            aria-label="调整病例库宽度"
          />
        </aside>

        <section className={`uws-content${selectedModule === 'cvi' ? ' is-cvi-focus' : ''}`}>
          {selectedModule !== 'cvi' && <div className="uws-content-head">
            <div className="uws-content-title">
              <strong>{activeModule.label}</strong>
              <span>
                {activeModule.description} · {caseSubtitle}
                {user?.is_admin && reviewUserId ? ` · 当前查看：${reviewUsers.find(item => item.id === reviewUserId)?.username || reviewUserId}` : ''}
              </span>
            </div>
            <div className="uws-content-actions">
              {assessmentModules.has(selectedModule) && (
                <span className="uws-chip">
                  <FaSave /> 保存沿用原模块接口
                </span>
              )}
            </div>
          </div>}
          <div className={`uws-work-area${workAreaScrollable ? ' is-scroll' : ''}`}>
            {renderWorkArea()}
          </div>
        </section>
      </div>
    </div>
  );
};

export default UnifiedWorkstationPage;
