import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { flushCviIframeAutosave } from '../utils/cviAutosave';

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
  primary_id_label?: string;
  primary_id?: string;
  imported_at?: string | null;
}

interface CviSource {
  value: string;
  label: string;
  root: string;
}

const sourceLabel: Record<string, string> = {
  annotation: '原标注目录',
  functional: '病例库'
};
const CASE_FETCH_LIMIT_FALLBACK = 5000;

const mergeSourceOptions = (serverSources: CviSource[]): CviSource[] => serverSources || [];

const readApiPayload = async (response: Response) => {
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    throw new Error(
      response.status >= 500
        ? '病例库后端暂时不可用，请稍后重试。'
        : `病例库接口返回了网页而不是数据（HTTP ${response.status}），请刷新后重试。`
    );
  }
  return response.json();
};

const registrationIdFromCase = (caseItem?: CviCase | null) => {
  if (!caseItem || caseItem.dataset !== 'CMR_ALL') return '';
  for (const value of [caseItem.case_id, caseItem.public_case_code, caseItem.primary_id]) {
    const match = (value || '').match(/(?:^|\D)(\d{10})(?!\d)/);
    if (match?.[1]) return match[1];
  }
  return '';
};

const studyDateFromCase = (caseItem?: CviCase | null) => {
  if (!caseItem || caseItem.dataset !== 'CMR_ALL') return '';
  const match = (caseItem.public_case_code || caseItem.case_id || '').match(/20\d{6}/);
  if (!match) return '';
  const value = match[0];
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
};

const caseDisplayName = (caseItem?: CviCase | null, fallback = '匿名病例') => {
  if (!caseItem) return fallback;
  const registrationId = registrationIdFromCase(caseItem);
  if (registrationId) {
    return `登记号：${registrationId}`;
  }
  return caseItem.anon_label || fallback;
};

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

const CviWorkstationPage: React.FC = () => {
  const defaultWorkstationUrl = useMemo(() => '/cvi-workstation-app/', []);
  const [workstationUrl, setWorkstationUrl] = useState(defaultWorkstationUrl);
  const [cases, setCases] = useState<CviCase[]>([]);
  const [sources, setSources] = useState<CviSource[]>([]);
  const [source, setSource] = useState('functional::CMR_ALL::report100');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [openingId, setOpeningId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const sourceOptions = useMemo(
    () => mergeSourceOptions(sources),
    [sources]
  );

  const loadCases = useCallback(async (refresh = false) => {
    setLoading(!refresh);
    setRefreshing(refresh);
    setError(null);
    try {
      const params = new URLSearchParams({
        source,
        search,
        limit: '300'
      });
      if (refresh) params.set('refresh', '1');

      let response = await fetch(`/api/cvi-library/cases?${params.toString()}`);
      let payload = await readApiPayload(response);
      let usedCompatibilityFallback = false;
      if (!response.ok && payload?.error === 'Unknown source' && source.startsWith('functional::')) {
        const fallbackParams = new URLSearchParams({
          source: 'functional',
          search,
          limit: String(CASE_FETCH_LIMIT_FALLBACK)
        });
        if (refresh) fallbackParams.set('refresh', '1');
        response = await fetch(`/api/cvi-library/cases?${fallbackParams.toString()}`);
        payload = await readApiPayload(response);
        usedCompatibilityFallback = response.ok;
      }
      if (!response.ok) {
        throw new Error(payload.error || '病例库加载失败');
      }
      setCases(usedCompatibilityFallback ? applyClientSourceFilter(payload.items || [], source) : (payload.items || []));
      const nextSources = mergeSourceOptions(payload.sources || []);
      setSources(nextSources);
      const nextSource = payload.source || nextSources[0]?.value;
      if (nextSource && !nextSources.some(item => item.value === source)) setSource(nextSource);
    } catch (err) {
      setError(err instanceof Error ? err.message : '病例库加载失败');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [source, search]);

  useEffect(() => {
    loadCases(false);
  }, [loadCases]);

  const flushCurrentContours = useCallback(async () => {
    try {
      await flushCviIframeAutosave(iframeRef.current);
    } catch (err) {
      throw new Error(err instanceof Error ? err.message : '当前轮廓自动保存失败，请先点击工作站内“保存轮廓”后再切换病例。');
    }
  }, []);

  const openCase = async (caseItem: CviCase, force = false) => {
    setOpeningId(caseItem.id);
    setError(null);
    try {
      await flushCurrentContours();
      const response = await fetch(`/api/cvi-library/cases/${caseItem.id}/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force })
      });
      const payload = await readApiPayload(response);
      if (!response.ok) {
        throw new Error(payload.error || '导入工作站失败');
      }
      const studyId = payload.study_id;
      setSelectedCaseId(caseItem.id);
      setWorkstationUrl(`/cvi-workstation-app/study/${studyId}/function`);
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

  return (
    <div style={{
      height: '100%',
      display: 'flex',
      background: 'var(--bg-primary)',
      overflow: 'hidden'
    }}>
      <aside style={{
        width: 320,
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        borderRight: '1px solid var(--border-color)',
        background: 'var(--bg-secondary)'
      }}>
        <div style={{ padding: 16, borderBottom: '1px solid var(--border-color)' }}>
          <strong style={{ display: 'block', fontSize: 16, color: 'var(--text-primary)', marginBottom: 6 }}>
            CMR 病例库
          </strong>
          <div style={{ fontSize: 12, color: 'var(--text-tertiary)', lineHeight: 1.5, marginBottom: 12 }}>
            直接读取 Label System 服务器上的数据目录，打开病例时自动导入工作站。
          </div>

          <select
            value={source}
            onChange={event => setSource(event.target.value)}
            style={{
              width: '100%',
              marginBottom: 8,
              padding: '8px 10px',
              borderRadius: 4,
              border: '1px solid var(--border-color)',
              background: 'var(--bg-tertiary)',
              color: 'var(--text-primary)'
            }}
          >
            <option value="all">全部目录</option>
            {sourceOptions.map(item => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>

          <input
            value={search}
            onChange={event => setSearch(event.target.value)}
            placeholder="搜索登记号 / 病例号 / 数据集"
            style={{
              width: '100%',
              padding: '8px 10px',
              borderRadius: 4,
              border: '1px solid var(--border-color)',
              background: 'var(--bg-tertiary)',
              color: 'var(--text-primary)',
              marginBottom: 8
            }}
          />

          <button
            onClick={() => loadCases(true)}
            disabled={refreshing}
            style={{
              width: '100%',
              padding: '8px 10px',
              borderRadius: 4,
              border: '1px solid var(--border-color)',
              background: refreshing ? 'var(--bg-tertiary)' : 'transparent',
              color: 'var(--accent-gold)',
              cursor: refreshing ? 'wait' : 'pointer'
            }}
          >
            {refreshing ? '正在同步目录...' : '刷新病例库'}
          </button>

          {error && (
            <div style={{
              marginTop: 10,
              padding: 8,
              borderRadius: 4,
              color: '#fca5a5',
              background: 'rgba(239, 68, 68, 0.12)',
              fontSize: 12
            }}>
              {error}
            </div>
          )}
        </div>

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {source === 'functional::CMR_ALL::all' && !search && (
            <div style={{ padding: '8px 12px', color: 'var(--text-tertiary)', fontSize: 12 }}>
              当前展示前 {cases.length} 例，登记号搜索覆盖全部昆医病例
            </div>
          )}
          {loading ? (
            <div style={{ padding: 16, color: 'var(--text-tertiary)' }}>正在加载病例库...</div>
          ) : cases.length === 0 ? (
            <div style={{ padding: 16, color: 'var(--text-tertiary)' }}>没有找到匹配病例。</div>
          ) : cases.map(caseItem => {
            const selected = selectedCaseId === caseItem.id;
            const busy = openingId === caseItem.id;
            const sequences = caseItem.sequence_summary
              .filter(item => item.dicom_count > 0)
              .slice(0, 4)
              .map(item => `${item.name} ${item.dicom_count}`)
              .join(' / ');

            return (
              <div
                key={caseItem.id}
                style={{
                  padding: 12,
                  borderBottom: '1px solid var(--border-color)',
                  background: selected ? 'rgba(217, 119, 6, 0.08)' : 'transparent'
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{
                      color: selected ? 'var(--accent-gold)' : 'var(--text-primary)',
                      fontWeight: 600,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap'
                    }}>
                      {caseDisplayName(caseItem)}
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 4 }}>
                      {registrationIdFromCase(caseItem) ? `${caseItem.anon_label || '匿名病例'} / ` : ''}
                      {studyDateFromCase(caseItem) ? `${studyDateFromCase(caseItem)} / ` : ''}
                      {sourceLabel[caseItem.source] || caseItem.source} / {caseItem.dataset}
                    </div>
                  </div>
                  <button
                    onClick={() => openCase(caseItem)}
                    disabled={busy || !caseItem.has_dicom}
                    style={{
                      flexShrink: 0,
                      height: 30,
                      padding: '0 10px',
                      borderRadius: 4,
                      border: '1px solid var(--border-color)',
                      background: caseItem.has_dicom ? 'var(--accent-gold)' : 'var(--bg-tertiary)',
                      color: caseItem.has_dicom ? '#fff' : 'var(--text-tertiary)',
                      cursor: busy ? 'wait' : caseItem.has_dicom ? 'pointer' : 'not-allowed'
                    }}
                  >
                    {busy ? '导入中' : caseItem.cvi_study_id ? '打开' : '导入'}
                  </button>
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 8, lineHeight: 1.5 }}>
                  {caseItem.has_dicom ? sequences || `${caseItem.dicom_count} DICOM` : '未发现 DICOM'}
                </div>
                {caseItem.cvi_study_id && (
                  <button
                    onClick={() => openCase(caseItem, true)}
                    disabled={busy}
                    style={{
                      marginTop: 8,
                      padding: 0,
                      border: 0,
                      background: 'transparent',
                      color: 'var(--text-tertiary)',
                      cursor: busy ? 'wait' : 'pointer',
                      fontSize: 12
                    }}
                  >
                    重新导入
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </aside>

      <section style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{
          height: 44,
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 16px',
          borderBottom: '1px solid var(--border-color)',
          background: 'var(--bg-secondary)'
        }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <strong style={{ fontSize: 14, color: 'var(--text-primary)' }}>CMR 工作站</strong>
            <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
              SAX cine / 4CH / LGE 标注、传播和报告工作流
            </span>
          </div>
          <a
            href={workstationUrl}
            target="_blank"
            rel="noreferrer"
            style={{
              color: 'var(--accent-gold)',
              border: '1px solid var(--border-color)',
              borderRadius: 4,
              padding: '5px 10px',
              fontSize: 12,
              textDecoration: 'none'
            }}
          >
            新窗口打开
          </a>
        </div>
        <iframe
          ref={iframeRef}
          title="CMR Workstation"
          src={workstationUrl}
          style={{
            flex: 1,
            width: '100%',
            border: 0,
            background: '#fff'
          }}
        />
      </section>
    </div>
  );
};

export default CviWorkstationPage;
