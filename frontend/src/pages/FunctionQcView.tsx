import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './FunctionQcView.css';

interface QcCase {
  center: string;
  patient_id: string;
  returncode: number;
  elapsed_seconds: number;
  metrics_exists: boolean;
  workflow_exists: boolean;
  status: 'pass' | 'fail';
  flags: string[];
  LVEF: number | null;
  RVEF: number | null;
  LVEDV: number | null;
  LVESV: number | null;
  SAX_ED_trigger: number | null;
  SAX_ES_trigger: number | null;
  LAV: number | null;
  RAV: number | null;
}

interface RunOption {
  runRoot: string;
  outputRoot: string;
  label: string;
  centerCounts: Record<string, number>;
  totalCases: number;
  centerCount: number;
}

interface QcListPayload {
  runRoot: string | null;
  runLabel?: string | null;
  outputRoot: string | null;
  total: number;
  centers: string[];
  centerCounts?: Record<string, number>;
  availableRuns?: RunOption[];
  cases: QcCase[];
}

interface PhasePoint {
  trigger: number;
  lvVolume: number;
  lvDiameter: number | null;
  role: string;
}

interface PhaseComparisonItem {
  label: string;
  method: string;
  candidateCount: number;
  minSlices: number | null;
  edTrigger: number | null;
  esTrigger: number | null;
  LVEDV: number | null;
  LVESV: number | null;
  LVEF: number | null;
  RVEDV: number | null;
  RVESV: number | null;
  RVEF: number | null;
  rawValues?: Record<string, string | null>;
}

interface ReportTruthMetric {
  raw: string;
  value: number | null;
}

interface CaseDetail {
  center: string;
  runRoot?: string | null;
  patientId: string;
  patientInfo: Record<string, unknown> | null;
  bodyMetrics?: {
    height_cm: number | null;
    weight_kg: number | null;
    BSA: number | null;
  };
  metrics: Record<string, number | null>;
  phaseAssignments: {
    saxED: number | null;
    saxES: number | null;
    fourChED: number | null;
    fourChES: number | null;
  };
  reportTruth?: {
    sourcePath: string | null;
    metrics: Record<string, ReportTruthMetric>;
  };
  phaseComparison?: {
    truth: PhaseComparisonItem;
    current: PhaseComparisonItem;
    labelsystemRaw: PhaseComparisonItem | null;
    labelsystemQc: PhaseComparisonItem | null;
  };
  phases: PhasePoint[];
  warnings: string[];
  images: {
    previews: {
      sax: string | null;
      fourCh: string | null;
      lge: string | null;
    };
    saxEdMeasurement: string[];
    fourChMeasurement: string[];
    saxEdSlices: string[];
    saxEsSlices: string[];
    saxPhaseSamples: { name: string; image: string; count: number }[];
  };
}

function fileUrl(path?: string | null, runRoot?: string | null) {
  if (!path) return '';
  const params = new URLSearchParams({ path });
  if (runRoot) params.set('runRoot', runRoot);
  return `/api/function-qc/file?${params.toString()}`;
}

async function fetchJson<T>(url: string, fallbackMessage: string): Promise<T> {
  const response = await fetch(url);
  const text = await response.text();
  let data: unknown = null;

  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    const htmlHint = text.trim().startsWith('<')
      ? '接口返回了 HTML 页面，通常是后端没有重启加载新路由，或前端代理没有指向 Flask。'
      : '接口返回内容不是合法 JSON。';
    throw new Error(`${htmlHint} HTTP ${response.status}：${url}`);
  }

  if (!response.ok) {
    const errorMessage =
      data && typeof data === 'object' && 'error' in data
        ? String((data as { error?: unknown }).error)
        : fallbackMessage;
    throw new Error(errorMessage);
  }

  return data as T;
}

function fmt(value?: number | null, unit = '') {
  if (value === null || value === undefined || Number.isNaN(value)) return 'N/A';
  return `${Number(value).toFixed(2)}${unit}`;
}

function fmtTruth(metric?: ReportTruthMetric) {
  return metric?.raw && !['N/A', 'NA', 'nan', '-'].includes(metric.raw) ? metric.raw : 'N/A';
}

function fmtDelta(pred?: number | null, truth?: number | null, unit = '') {
  if (pred === null || pred === undefined || truth === null || truth === undefined) return 'N/A';
  return `${Math.abs(Number(pred) - Number(truth)).toFixed(2)}${unit}`;
}

function metricUnit(key: string) {
  if (key === 'BSA') return ' m²';
  if (key.endsWith('i')) return ' mL/m²';
  if (key.endsWith('EF')) return '%';
  if (key.endsWith('EDD')) return ' mm';
  return ' mL';
}

function metricIsWarn(key: string, value: number | null) {
  if (!key.endsWith('EF') || value === null) return false;
  return value < 30 || value > 80;
}

function VolumeCurve({ phases }: { phases: PhasePoint[] }) {
  const width = 900;
  const height = 280;
  const pad = 38;
  if (!phases.length) {
    return <div className="fqc-empty" style={{ minHeight: 260 }}>没有可用体积曲线</div>;
  }

  const triggers = phases.map(item => item.trigger);
  const volumes = phases.map(item => item.lvVolume);
  const minX = Math.min(...triggers);
  const maxX = Math.max(...triggers);
  const minY = Math.min(...volumes);
  const maxY = Math.max(...volumes);
  const spanX = Math.max(1, maxX - minX);
  const spanY = Math.max(1, maxY - minY);
  const points = phases.map(item => ({
    ...item,
    x: pad + ((item.trigger - minX) / spanX) * (width - pad * 2),
    y: height - pad - ((item.lvVolume - minY) / spanY) * (height - pad * 2)
  }));
  const line = points.map(item => `${item.x},${item.y}`).join(' ');

  return (
    <svg className="fqc-curve" viewBox={`0 0 ${width} ${height}`}>
      <defs>
        <linearGradient id="fqcCurveLine" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#a8cb4e" />
          <stop offset="55%" stopColor="#57e389" />
          <stop offset="100%" stopColor="#f8c46a" />
        </linearGradient>
      </defs>
      <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} stroke="rgba(255,255,255,0.18)" />
      <line x1={pad} y1={pad} x2={pad} y2={height - pad} stroke="rgba(255,255,255,0.18)" />
      <text x={pad} y={22} fill="#b0b0b0" fontSize="12">LV volume max {maxY.toFixed(1)} mL</text>
      <text x={pad} y={height - 10} fill="#b0b0b0" fontSize="12">trigger {minX.toFixed(0)}-{maxX.toFixed(0)} ms</text>
      <polyline points={line} fill="none" stroke="url(#fqcCurveLine)" strokeWidth="4" strokeLinejoin="round" strokeLinecap="round" />
      {points.map(point => (
        <g key={`${point.trigger}-${point.role}`}>
          <circle
            cx={point.x}
            cy={point.y}
            r={point.role ? 8 : 5}
            fill={point.role === 'ED' ? '#57e389' : point.role === 'ES' ? '#f8c46a' : '#101010'}
            stroke={point.role ? '#f1f1f1' : '#a8cb4e'}
            strokeWidth="2"
          />
          {point.role && (
            <text x={point.x + 10} y={point.y - 10} fill="#f1f1f1" fontSize="13" fontWeight="700">
              {point.role} {point.trigger.toFixed(0)}ms
            </text>
          )}
        </g>
      ))}
    </svg>
  );
}

function ImagePanel({ title, images, runRoot }: { title: string; images: string[]; runRoot?: string | null }) {
  const [index, setIndex] = useState(0);
  const safeIndex = Math.min(index, Math.max(0, images.length - 1));
  const selected = images[safeIndex];

  useEffect(() => {
    setIndex(0);
  }, [images.join('|')]);

  return (
    <div className="fqc-image-panel">
      <div className="fqc-image-title">
        <span>{title}</span>
        <span className="fqc-muted">{images.length} slices</span>
      </div>
      {selected ? (
        <>
          <img src={fileUrl(selected, runRoot)} alt={title} />
          {images.length > 1 && (
            <input
              className="fqc-range"
              type="range"
              min={0}
              max={images.length - 1}
              value={safeIndex}
              onChange={event => setIndex(Number(event.target.value))}
            />
          )}
        </>
      ) : (
        <div className="fqc-empty" style={{ minHeight: 220 }}>无 PNG 切片</div>
      )}
    </div>
  );
}

function PreviewCard({ title, path, runRoot }: { title: string; path?: string | null; runRoot?: string | null }) {
  return (
    <div className="fqc-preview-card">
      <div className="fqc-image-title">{title}</div>
      {path ? <img src={fileUrl(path, runRoot)} alt={title} /> : <div className="fqc-empty" style={{ minHeight: 220 }}>缺失</div>}
    </div>
  );
}

function PhaseComparisonTable({ comparison }: { comparison?: CaseDetail['phaseComparison'] }) {
  if (!comparison) return null;
  const truth = comparison.truth;
  const rows = [comparison.current, comparison.labelsystemRaw, comparison.labelsystemQc].filter(Boolean) as PhaseComparisonItem[];
  return (
    <div className="fqc-phase-compare">
      <table>
        <thead>
          <tr>
            <th>策略</th>
            <th>ED / ES</th>
            <th>LVEDV / LVESV / LVEF</th>
            <th>ΔLVEF</th>
            <th>RVEDV / RVESV / RVEF</th>
            <th>ΔRVEF</th>
            <th>候选</th>
          </tr>
        </thead>
        <tbody>
          <tr className="is-truth">
            <td>
              <strong>{truth.label}</strong>
              <span>{truth.method}</span>
            </td>
            <td>N/A</td>
            <td>
              {truth.rawValues?.LVEDV || fmt(truth.LVEDV, ' mL')} / {truth.rawValues?.LVESV || fmt(truth.LVESV, ' mL')} / {truth.rawValues?.LVEF || fmt(truth.LVEF, '%')}
            </td>
            <td>0.00%</td>
            <td>
              {truth.rawValues?.RVEDV || fmt(truth.RVEDV, ' mL')} / {truth.rawValues?.RVESV || fmt(truth.RVESV, ' mL')} / {truth.rawValues?.RVEF || fmt(truth.RVEF, '%')}
            </td>
            <td>0.00%</td>
            <td>报告</td>
          </tr>
          {rows.map(row => (
            <tr key={row.label} className={row.label.includes('QC') ? 'is-recommended' : ''}>
              <td>
                <strong>{row.label}</strong>
                <span>{row.method}</span>
              </td>
              <td>{fmt(row.edTrigger, 'ms')} / {fmt(row.esTrigger, 'ms')}</td>
              <td>{fmt(row.LVEDV, ' mL')} / {fmt(row.LVESV, ' mL')} / {fmt(row.LVEF, '%')}</td>
              <td className="is-delta">{fmtDelta(row.LVEF, truth.LVEF, '%')}</td>
              <td>{fmt(row.RVEDV, ' mL')} / {fmt(row.RVESV, ' mL')} / {fmt(row.RVEF, '%')}</td>
              <td className="is-delta">{fmtDelta(row.RVEF, truth.RVEF, '%')}</td>
              <td>{row.candidateCount}{row.minSlices ? ` · >=${row.minSlices} slices` : ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="fqc-muted">
        报告真实值来自报告评分页同源的 results_chart comparison 表；裸规则等同 LabelSystem contour-volume max/min；QC 版本先过滤层数明显不完整的相位，避免塌陷相位把 ES 拉到假低。
      </div>
    </div>
  );
}

const FunctionQcView: React.FC = () => {
  const [payload, setPayload] = useState<QcListPayload | null>(null);
  const [selectedCase, setSelectedCase] = useState<QcCase | null>(null);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [runRoot, setRunRoot] = useState('');
  const [center, setCenter] = useState('ALL');
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (runRoot) params.set('runRoot', runRoot);
      const url = params.toString() ? `/api/function-qc?${params.toString()}` : '/api/function-qc';
      const data = await fetchJson<QcListPayload>(url, '心功能验收数据加载失败');
      setPayload(data);
      if (!runRoot && data.runRoot) {
        setRunRoot(data.runRoot);
      }
      setSelectedCase(current => current || data.cases?.[0] || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '心功能验收数据加载失败');
    } finally {
      setLoading(false);
    }
  }, [runRoot]);

  const loadDetail = useCallback(async (item: QcCase | null) => {
    if (!item) {
      setDetail(null);
      return;
    }
    setDetailLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ center: item.center, patientId: item.patient_id });
      if (runRoot) params.set('runRoot', runRoot);
      const data = await fetchJson<CaseDetail>(`/api/function-qc?${params.toString()}`, '病例详情加载失败');
      setDetail(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '病例详情加载失败');
    } finally {
      setDetailLoading(false);
    }
  }, [runRoot]);

  useEffect(() => {
    loadList();
  }, [loadList]);

  useEffect(() => {
    loadDetail(selectedCase);
  }, [selectedCase, loadDetail]);

  const cases = payload?.cases || [];
  const activeRun = useMemo(
    () => (payload?.availableRuns || []).find(item => item.runRoot === (payload?.runRoot || runRoot)) || null,
    [payload, runRoot]
  );
  const filteredCases = useMemo(() => cases.filter(item => {
    const matchCenter = center === 'ALL' || item.center === center;
    const matchFlag = !flaggedOnly || item.flags.length > 0;
    const matchSearch = !search.trim() || item.patient_id.toLowerCase().includes(search.trim().toLowerCase());
    return matchCenter && matchFlag && matchSearch;
  }), [cases, center, flaggedOnly, search]);

  const passCount = cases.filter(item => item.status === 'pass').length;
  const flaggedCount = cases.filter(item => item.flags.length > 0).length;

  return (
    <div className="function-qc-view">
      <div className="fqc-toolbar">
        <div className="fqc-stat">
          <span>当前批次</span>
          <strong>{activeRun?.totalCases || payload?.total || 0}</strong>
          <small>{payload?.runLabel || activeRun?.label || '未选择批次'}</small>
        </div>
        <div className="fqc-stat"><span>验收病例</span><strong>{payload?.total || 0}</strong></div>
        <div className="fqc-stat"><span>流程通过</span><strong>{passCount}</strong></div>
        <div className="fqc-stat"><span>EF 待复核</span><strong>{flaggedCount}</strong></div>
        <div className="fqc-stat">
          <span>中心数</span>
          <strong>{payload?.centers.length || 0}</strong>
          <small>{Object.entries(payload?.centerCounts || {}).map(([key, value]) => `${key}:${value}`).join(' · ') || '暂无分中心统计'}</small>
        </div>
      </div>

      <div className="fqc-main">
        <aside className="fqc-sidebar">
          <div className="fqc-filters">
            <select className="fqc-field" value={runRoot} onChange={event => {
              setRunRoot(event.target.value);
              setSelectedCase(null);
              setDetail(null);
            }}>
              {(payload?.availableRuns || []).map(item => (
                <option key={item.runRoot} value={item.runRoot}>
                  {item.label} · {item.totalCases}例 / {item.centerCount}中心
                </option>
              ))}
            </select>
            <div className="fqc-run-meta">
              {(activeRun ? Object.entries(activeRun.centerCounts) : []).map(([key, value]) => (
                <span key={key} className="fqc-chip">{key} {value}</span>
              ))}
            </div>
            <div className="fqc-filter-row">
              <select className="fqc-field" value={center} onChange={event => setCenter(event.target.value)}>
                <option value="ALL">全部中心</option>
                {(payload?.centers || []).map(item => <option key={item} value={item}>{item}</option>)}
              </select>
              <button
                className={`fqc-button${flaggedOnly ? ' is-active' : ''}`}
                onClick={() => setFlaggedOnly(value => !value)}
              >
                EF异常
              </button>
            </div>
            <input
              className="fqc-field"
              value={search}
              onChange={event => setSearch(event.target.value)}
              placeholder="搜索患者号"
            />
            <button className="fqc-button" onClick={loadList} disabled={loading}>
              {loading ? '刷新中...' : '刷新验收结果'}
            </button>
            {error && <div className="uws-error">{error}</div>}
          </div>
          <div className="fqc-case-list">
            {filteredCases.map(item => {
              const selected = selectedCase?.center === item.center && selectedCase?.patient_id === item.patient_id;
              return (
                <button
                  type="button"
                  key={`${item.center}-${item.patient_id}`}
                  className={`fqc-case-card${selected ? ' is-active' : ''}`}
                  onClick={() => setSelectedCase(item)}
                >
                  <div className="fqc-case-top">
                    <div style={{ minWidth: 0 }}>
                      <div className="fqc-case-id" title={item.patient_id}>{item.patient_id}</div>
                      <div className="fqc-case-meta">{item.center} · {fmt(item.elapsed_seconds, 's')}</div>
                    </div>
                    <span className={`fqc-chip ${item.status === 'pass' ? 'is-ok' : 'is-danger'}`}>
                      {item.status === 'pass' ? 'PASS' : 'FAIL'}
                    </span>
                  </div>
                  <div className="fqc-chip-row">
                    <span className={`fqc-chip ${metricIsWarn('LVEF', item.LVEF) ? 'is-danger' : 'is-ok'}`}>LVEF {fmt(item.LVEF, '%')}</span>
                    <span className={`fqc-chip ${metricIsWarn('RVEF', item.RVEF) ? 'is-danger' : 'is-ok'}`}>RVEF {fmt(item.RVEF, '%')}</span>
                    <span className="fqc-chip">ED {fmt(item.SAX_ED_trigger, 'ms')}</span>
                    <span className="fqc-chip">ES {fmt(item.SAX_ES_trigger, 'ms')}</span>
                  </div>
                </button>
              );
            })}
            {!loading && filteredCases.length === 0 && <div className="fqc-empty" style={{ minHeight: 160 }}>没有匹配病例</div>}
          </div>
        </aside>

        <main className="fqc-content">
          {detailLoading || !detail ? (
            <div className="fqc-empty">{detailLoading ? '正在加载病例详情...' : '请选择病例'}</div>
          ) : (
            <>
              <section className="fqc-section">
                <div className="fqc-section-head">
                  <div>
                    <h3>{detail.patientId}</h3>
                  <div className="fqc-muted">
                      {detail.center} · 年龄 {String(detail.patientInfo?.age || 'Unknown')} · 性别 {String(detail.patientInfo?.sex || 'Unknown')}
                      {detail.reportTruth?.sourcePath ? ' · 已加载报告真实值' : ' · 未找到报告真实值'}
                    </div>
                  </div>
                  <div className="fqc-chip-row">
                    <span className="fqc-chip">身高 {fmt(detail.bodyMetrics?.height_cm, 'cm')}</span>
                    <span className="fqc-chip">体重 {fmt(detail.bodyMetrics?.weight_kg, 'kg')}</span>
                    <span className="fqc-chip">BSA {fmt(detail.bodyMetrics?.BSA, ' m²')}</span>
                    <span className="fqc-chip">SAX ED {fmt(detail.phaseAssignments.saxED, 'ms')}</span>
                    <span className="fqc-chip">SAX ES {fmt(detail.phaseAssignments.saxES, 'ms')}</span>
                    <span className="fqc-chip">4CH ED {fmt(detail.phaseAssignments.fourChED, 'ms')}</span>
                    <span className="fqc-chip">4CH ES {fmt(detail.phaseAssignments.fourChES, 'ms')}</span>
                  </div>
                </div>
                <div className="fqc-section-body">
                  <div className="fqc-metrics">
                    {Object.entries(detail.metrics).map(([key, value]) => (
                      <div key={key} className={`fqc-metric-card${metricIsWarn(key, value) ? ' is-warn' : ''}`}>
                        <span>{key}</span>
                        <strong>{fmt(value, metricUnit(key))}</strong>
                        <small>报告 {fmtTruth(detail.reportTruth?.metrics?.[key])}</small>
                        <small>Δ {fmtDelta(value, detail.reportTruth?.metrics?.[key]?.value, metricUnit(key))}</small>
                      </div>
                    ))}
                  </div>
                </div>
              </section>

              <section className="fqc-section">
                <div className="fqc-section-head">
                  <h3>ED / ES 自动检查对比</h3>
                  <span className="fqc-chip is-warn">LabelSystem heuristic trial</span>
                </div>
                <div className="fqc-section-body">
                  <PhaseComparisonTable comparison={detail.phaseComparison} />
                </div>
              </section>

              <section className="fqc-section">
                <div className="fqc-section-head"><h3>SAX LV 体积曲线</h3><span className="fqc-muted">{detail.phases.length} phases</span></div>
                <div className="fqc-section-body">
                  <VolumeCurve phases={detail.phases} />
                </div>
              </section>

              <section className="fqc-section">
                <div className="fqc-section-head"><h3>序列预览</h3></div>
                <div className="fqc-section-body fqc-preview-grid">
                  <PreviewCard title="SAX Preview" path={detail.images.previews.sax} runRoot={runRoot} />
                  <PreviewCard title="4CH Preview" path={detail.images.previews.fourCh} runRoot={runRoot} />
                  <PreviewCard title="LGE Preview" path={detail.images.previews.lge} runRoot={runRoot} />
                </div>
              </section>

              <section className="fqc-section">
                <div className="fqc-section-head"><h3>ED / ES 分割切片</h3></div>
                <div className="fqc-section-body fqc-image-grid">
                  <ImagePanel title="SAX ED segmentation" images={detail.images.saxEdSlices} runRoot={runRoot} />
                  <ImagePanel title="SAX ES segmentation" images={detail.images.saxEsSlices} runRoot={runRoot} />
                  <ImagePanel title="SAX ED measurement" images={detail.images.saxEdMeasurement} runRoot={runRoot} />
                  <ImagePanel title="4CH ES measurement" images={detail.images.fourChMeasurement} runRoot={runRoot} />
                </div>
              </section>

              <section className="fqc-section">
                <div className="fqc-section-head"><h3>所有 SAX 时相抽样</h3></div>
                <div className="fqc-section-body">
                  <div className="fqc-phase-grid">
                    {detail.images.saxPhaseSamples.map(sample => (
                      <div className="fqc-phase-card" key={sample.name}>
                        <img src={fileUrl(sample.image, runRoot)} alt={sample.name} />
                        <div className="fqc-case-id" title={sample.name}>{sample.name.replace('.nii_pngs', '')}</div>
                        <div className="fqc-muted">{sample.count} slices</div>
                      </div>
                    ))}
                  </div>
                </div>
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  );
};

export default FunctionQcView;
