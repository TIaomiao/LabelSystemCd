import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

interface DiskUsage {
  total: number;
  used: number;
  free: number;
}

interface DataRoot {
  key: string;
  label: string;
  path: string;
  exists: boolean;
  datasets: number;
  cases: number;
  disk?: DiskUsage | null;
}

interface DatasetMapping {
  dataset: string;
  config_keys: string[];
  excel_file: string;
  excel_path: string;
  excel_columns?: number | null;
  id_column: string;
  description_cols: string[];
  conclusion_cols: string[];
  extra_cols: string[];
  annotation_path: string;
  annotation_exists: boolean;
  annotation_cases: number;
  functional_path: string;
  functional_exists: boolean;
  functional_cases: number;
  eval_path: string;
  eval_exists: boolean;
  eval_cases: number;
  eval_new_path: string;
  eval_new_exists: boolean;
  eval_new_cases: number;
}

interface GpuState {
  index: number;
  name: string;
  utilization: number;
  memory_used_mb: number;
  memory_total_mb: number;
  temperature: number;
}

interface AnnotationModule {
  key: string;
  label: string;
  records: number;
  assigned_records: number;
  unique_cases: number;
}

interface RecentActivity {
  module: string;
  case: string;
  user?: string | null;
  time?: string | null;
}

interface UserWorkload {
  id: number;
  username: string;
  status: string;
  is_approved: boolean;
  is_admin: boolean;
  is_online: boolean;
  login_count: number;
  last_login_at?: string | null;
  last_logout_at?: string | null;
  total_records: number;
  unique_cases: number;
  first_activity_at?: string | null;
  last_activity_at?: string | null;
  module_counts: Record<string, number>;
}

interface AdminUserLite {
  id: number;
  username: string;
  is_approved: boolean;
  is_admin: boolean;
}

interface Assignment {
  id: number;
  namespace: string;
  dataset: string;
  case_id: string;
  user_id: number;
  username?: string | null;
  created_at?: string | null;
}

interface AssignmentCaseDetail {
  case_id: string;
  case_name?: string;
  anon_label?: string;
  public_case_code?: string;
  register_id?: string;
  case_date?: string;
  diseases?: string;
  sex?: string;
  age?: string;
  subdirs?: string;
  match_quality?: string;
  excel_refs?: string;
}

interface AssignmentPreset {
  id: string;
  label: string;
  namespace: string;
  dataset: string;
  case_ids: string[];
  case_details?: AssignmentCaseDetail[];
  case_count: number;
  source?: string;
  description?: string;
}

interface MediaLog {
  id: number;
  username?: string | null;
  kind: string;
  namespace?: string;
  dataset?: string;
  case_id?: string;
  path?: string;
  status: string;
  ip_address?: string;
  created_at?: string | null;
}

interface LlmGatewayCheck {
  ok: boolean;
  checked_at?: string | null;
  latency_ms?: number | null;
  message?: string | null;
  model?: string | null;
  base_url?: string | null;
}

interface LlmGatewayConfig {
  enabled: boolean;
  api_base: string;
  normalized_api_base: string;
  model: string;
  has_api_key: boolean;
  api_key_masked: string;
  last_check?: LlmGatewayCheck | null;
  model_options: string[];
  model_count: number;
  model_source: string;
  models_synced_at?: string | null;
  pricing_url?: string;
  metric_targets: string[];
  output_schema: Record<string, unknown>;
}

interface MonitorData {
  system: {
    generated_at: string;
    backend_pid: number;
    loadavg?: number[] | null;
    uptime_seconds?: number | null;
    memory: {
      total?: number | null;
      used?: number | null;
      available?: number | null;
    };
    gpus: GpuState[];
  };
  users: {
    total: number;
    pending: number;
    approved: number;
    admins: number;
    workloads: UserWorkload[];
  };
  data: {
    roots: DataRoot[];
    cvi_catalog: {
      total: number;
      imported: number;
      dicom_cases: number;
    };
    database: {
      path: string;
      size_bytes: number;
      tables: Record<string, number | null>;
    };
    dataset_mappings: DatasetMapping[];
  };
  annotations: {
    modules: AnnotationModule[];
    recent_activity: RecentActivity[];
  };
  security: {
    assignments_total: number;
    assignments_by_namespace: Record<string, number>;
    media_logs_total: number;
    media_status_counts: Record<string, number>;
    recent_media_logs: MediaLog[];
    watermark_enabled: boolean;
  };
  llm_gateway: LlmGatewayConfig;
}

const moduleLabels: Record<string, string> = {
  segmentation: '分割',
  cardiac: '4CH',
  functional: '功能',
  structure: '结构',
  lge: 'LGE',
  image_quality: '影像',
  other_findings: '其他',
  report_eval: '报告',
};

const AdminMonitorPage: React.FC<{ initialSection?: 'assignments' }> = ({ initialSection }) => {
  const [data, setData] = useState<MonitorData | null>(null);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [assignmentMap, setAssignmentMap] = useState<Record<string, Assignment[]>>({});
  const [assignmentUsers, setAssignmentUsers] = useState<AdminUserLite[]>([]);
  const [assignmentPresets, setAssignmentPresets] = useState<AssignmentPreset[]>([]);
  const [selectedPresetId, setSelectedPresetId] = useState('');
  const [showAdvancedAssignment, setShowAdvancedAssignment] = useState(false);
  const [showAddCases, setShowAddCases] = useState(false);
  const [addCasesForm, setAddCasesForm] = useState({ target_count: '150', case_ids_text: '' });
  const [manualAssignForm, setManualAssignForm] = useState({ user_id: '', selection_text: '' });
  const [assignmentForm, setAssignmentForm] = useState({
    namespace: 'functional',
    dataset: '',
    case_id: '',
    case_ids_text: '',
    user_ids: [] as number[],
    distribute: true,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadMonitor = async () => {
    setError('');
    try {
      const response = await fetch('/api/admin/monitor');
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '加载系统监控失败');
      setData(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载系统监控失败');
    } finally {
      setLoading(false);
    }
  };

  const loadAssignments = async (namespace?: string, dataset?: string, caseIds?: string[]) => {
    try {
      const params = new URLSearchParams();
      if (namespace) params.set('namespace', namespace);
      if (dataset !== undefined) params.set('dataset', dataset);
      if (caseIds?.length) params.set('case_ids', caseIds.join('\n'));
      const response = await fetch(`/api/admin/assignments${params.toString() ? `?${params.toString()}` : ''}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '加载分配失败');
      setAssignments(payload.assignments || []);
      setAssignmentMap(payload.assignment_map || {});
      setAssignmentUsers(payload.users || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载分配失败');
    }
  };

  const loadAssignmentPresets = async () => {
    try {
      const response = await fetch('/api/admin/assignment-presets');
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '加载病例库失败');
      const presets: AssignmentPreset[] = payload.presets || [];
      setAssignmentPresets(presets);
      if (presets.length > 0) {
        const first = presets[0];
        setSelectedPresetId(first.id);
        setAssignmentForm(prev => ({
          ...prev,
          namespace: first.namespace,
          dataset: first.dataset,
          case_id: '',
          case_ids_text: first.case_ids.join('\n'),
        }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载病例库失败');
    }
  };

  useEffect(() => {
    void loadMonitor();
    void loadAssignments();
    void loadAssignmentPresets();
    const timer = window.setInterval(() => void loadMonitor(), 15000);
    return () => window.clearInterval(timer);
  }, []);

  const saveAssignment = async () => {
    setError('');
    const targetUserIds = assignmentForm.user_ids.length > 0
      ? assignmentForm.user_ids
      : assignmentUsers.filter((user) => !user.is_admin).map((user) => user.id);
    try {
      const response = await fetch('/api/admin/assignments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          namespace: assignmentForm.namespace,
          dataset: assignmentForm.dataset,
          case_id: assignmentForm.case_id,
          case_ids: assignmentForm.case_ids_text,
          user_ids: targetUserIds,
          distribute: assignmentForm.distribute,
          replace_existing: true,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '保存分配失败');
      setAssignmentForm(prev => ({ ...prev, case_id: '', user_ids: targetUserIds }));
      await loadAssignments(assignmentForm.namespace, assignmentForm.dataset, selectedCaseIds);
      await loadMonitor();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存分配失败');
    }
  };

  const clearCurrentAssignments = async () => {
    if (!window.confirm('确定清空当前病例库的已有分配吗？清空后这些病例会暂时没有负责人。')) return;
    setError('');
    try {
      const response = await fetch('/api/admin/assignments/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          namespace: assignmentForm.namespace,
          dataset: assignmentForm.dataset,
          case_ids: selectedCaseIds,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '清空分配失败');
      await loadAssignments(assignmentForm.namespace, assignmentForm.dataset, selectedCaseIds);
      await loadMonitor();
    } catch (err) {
      setError(err instanceof Error ? err.message : '清空分配失败');
    }
  };

  const clearSelectedUserAssignments = async () => {
    const user = assignmentUsers.find((item) => String(item.id) === manualAssignForm.user_id);
    if (!user) return;
    if (!window.confirm(`确定清空 ${user.username} 在当前病例库里的分配吗？`)) return;
    setError('');
    try {
      const response = await fetch('/api/admin/assignments/clear-user', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          namespace: assignmentForm.namespace,
          dataset: assignmentForm.dataset,
          user_id: Number(manualAssignForm.user_id),
          case_ids: selectedCaseIds,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '清空个人分配失败');
      await loadAssignments(assignmentForm.namespace, assignmentForm.dataset, selectedCaseIds);
      await loadMonitor();
    } catch (err) {
      setError(err instanceof Error ? err.message : '清空个人分配失败');
    }
  };

  const deleteAssignment = async (id: number) => {
    setError('');
    try {
      const response = await fetch(`/api/admin/assignments/${id}`, { method: 'DELETE' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '删除分配失败');
      await loadAssignments(assignmentForm.namespace, assignmentForm.dataset, selectedCaseIds);
      await loadMonitor();
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除分配失败');
    }
  };

  const reassignCase = async (caseId: string, userId: string) => {
    if (!userId) return;
    setError('');
    try {
      const response = await fetch('/api/admin/assignments/reassign-case', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          namespace: assignmentForm.namespace,
          dataset: assignmentForm.dataset,
          case_id: caseId,
          user_id: Number(userId),
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '重新分配失败');
      await loadAssignments(assignmentForm.namespace, assignmentForm.dataset, selectedCaseIds);
      await loadMonitor();
    } catch (err) {
      setError(err instanceof Error ? err.message : '重新分配失败');
    }
  };

  const addCasesToReportPreset = async () => {
    setError('');
    try {
      const response = await fetch('/api/admin/assignment-presets/km-report100/add-cases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_count: addCasesForm.target_count ? Number(addCasesForm.target_count) : undefined,
          case_ids: addCasesForm.case_ids_text,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '添加病例失败');
      await loadAssignmentPresets();
      await loadAssignments(assignmentForm.namespace, assignmentForm.dataset, selectedCaseIds);
      setAddCasesForm(prev => ({ ...prev, case_ids_text: '' }));
    } catch (err) {
      setError(err instanceof Error ? err.message : '添加病例失败');
    }
  };

  const assignSelectedCasesToUser = async () => {
    setError('');
    try {
      const response = await fetch('/api/admin/assignments/assign-selection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          namespace: assignmentForm.namespace,
          dataset: assignmentForm.dataset,
          user_id: Number(manualAssignForm.user_id),
          selection: manualAssignForm.selection_text,
          ordered_case_ids: selectedCaseIds,
          replace_existing: true,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '指定分配失败');
      setManualAssignForm(prev => ({ ...prev, selection_text: '' }));
      await loadAssignments(assignmentForm.namespace, assignmentForm.dataset, selectedCaseIds);
      await loadMonitor();
    } catch (err) {
      setError(err instanceof Error ? err.message : '指定分配失败');
    }
  };


  const selectedPreset = assignmentPresets.find((preset) => preset.id === selectedPresetId) || null;
  const selectedCaseIds = assignmentForm.case_ids_text
    .split(/[\n,，;；、]+/)
    .map((item) => item.trim())
    .filter(Boolean);

  useEffect(() => {
    if (selectedCaseIds.length === 0) return;
    void loadAssignments(assignmentForm.namespace, assignmentForm.dataset, selectedCaseIds);
  }, [assignmentForm.namespace, assignmentForm.dataset, selectedCaseIds.join('\n')]);

  const selectedCaseDetails = useMemo(() => {
    const details = selectedPreset?.case_details || [];
    const detailMap = new Map(details.map((item) => [item.case_id, item]));
    return selectedCaseIds.map((caseId, index) => detailMap.get(caseId) || {
      case_id: caseId,
      case_name: caseId,
      anon_label: `病例${String(index + 1).padStart(3, '0')}`,
      public_case_code: '-',
    });
  }, [selectedPreset, selectedCaseIds.join('\n')]);
  const activeAssignmentByCase = useMemo(() => {
    const result: Record<string, Assignment | undefined> = {};
    Object.entries(assignmentMap).forEach(([caseId, items]) => {
      result[caseId] = items?.[0];
    });
    return result;
  }, [assignmentMap]);
  const currentAssignmentForCase = (caseId: string) => {
    const caseName = caseId.split('/').pop() || caseId;
    return activeAssignmentByCase[caseId] || activeAssignmentByCase[caseName];
  };
  const currentAssignedCount = selectedCaseDetails.filter(item => currentAssignmentForCase(item.case_id)).length;
  const estimatedPerUser = assignmentForm.user_ids.length > 0
    ? Math.ceil(selectedCaseIds.length / assignmentForm.user_ids.length)
    : 0;
  const fallbackAssignmentUserCount = assignmentUsers.filter((user) => !user.is_admin).length;
  const effectiveAssignmentUserCount = assignmentForm.user_ids.length || fallbackAssignmentUserCount;

  const applyAssignmentPreset = (presetId: string) => {
    setSelectedPresetId(presetId);
    const preset = assignmentPresets.find((item) => item.id === presetId);
    if (!preset) return;
    setAssignmentForm(prev => ({
      ...prev,
      namespace: preset.namespace,
      dataset: preset.dataset,
      case_id: '',
      case_ids_text: preset.case_ids.join('\n'),
    }));
  };

  const selectAllAssignmentUsers = () => {
    setAssignmentForm(prev => ({
      ...prev,
      user_ids: assignmentUsers
        .filter((user) => !user.is_admin)
        .map((user) => user.id),
    }));
  };

  const totals = useMemo(() => {
    if (!data) return { annotationRecords: 0, annotationCases: 0, rootCases: 0 };
    return {
      annotationRecords: data.annotations.modules.reduce((sum, item) => sum + item.records, 0),
      annotationCases: data.annotations.modules.reduce((sum, item) => sum + item.unique_cases, 0),
      rootCases: data.data.roots.reduce((sum, item) => sum + item.cases, 0),
    };
  }, [data]);

  if (loading && !data) {
    return <div style={pageStyle}>加载系统监控...</div>;
  }

  return (
    <div style={pageStyle}>
      <div style={headerStyle}>
        <div>
          <h2 style={{ margin: 0 }}>系统监控</h2>
          <div style={{ color: 'var(--text-secondary)', marginTop: 6 }}>
            系统状态、数据量、用户注册和标注工作量
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {data?.system.generated_at && (
            <span style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>
              更新 {formatTime(data.system.generated_at)}
            </span>
          )}
          <Link to="/admin/users" style={secondaryButtonStyle}>用户审核</Link>
          <button onClick={() => void loadMonitor()} style={primaryButtonStyle}>刷新</button>
        </div>
      </div>

      {error && <div style={errorStyle}>{error}</div>}
      {data && (
        <>
          <div style={summaryGridStyle}>
            <SummaryCard label="用户总数" value={data.users.total} detail={`待审核 ${data.users.pending} / 管理员 ${data.users.admins}`} />
            <SummaryCard label="目录病例" value={totals.rootCases} detail={`CVI 目录 ${data.data.cvi_catalog.total} 例`} />
            <SummaryCard label="标注记录" value={totals.annotationRecords} detail={`模块累计 ${totals.annotationCases} 例次`} />
            <SummaryCard label="GPU" value={data.system.gpus.length} detail={data.system.gpus.length ? '已检测到显卡状态' : '未返回 nvidia-smi'} />
            <SummaryCard label="访问控制" value={data.security.assignments_total} detail={`影像日志 ${data.security.media_logs_total} 条，水印${data.security.watermark_enabled ? '开启' : '关闭'}`} />
          </div>

          <section style={sectionStyle}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
              <div>
                <SectionTitle title="LLM 网关配置" />
                <div style={{ color: 'var(--text-secondary)', maxWidth: 760 }}>
                  定量指标抽取已经拆到独立子页面，当前这里保留摘要信息和入口，避免系统监控页过长。
                </div>
              </div>
              <Link to="/admin/llm-gateway" style={secondaryButtonStyle}>打开独立页面</Link>
            </div>
            <div style={{ ...twoColumnStyle, marginTop: 16 }}>
              <div>
                <InfoRow label="当前地址" value={data.llm_gateway.normalized_api_base || '-'} />
                <InfoRow label="当前模型" value={data.llm_gateway.model || '-'} />
                <InfoRow label="API Key" value={data.llm_gateway.has_api_key ? data.llm_gateway.api_key_masked : '未配置'} />
                <InfoRow label="可选模型数" value={data.llm_gateway.model_count || data.llm_gateway.model_options.length} />
                <InfoRow label="模型来源" value={data.llm_gateway.model_source || '-'} />
                <InfoRow label="最近同步" value={formatTime(data.llm_gateway.models_synced_at)} />
              </div>
              <div>
                <div style={{ marginBottom: 8, fontWeight: 700 }}>抽取指标</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 14 }}>
                  {data.llm_gateway.metric_targets.map((metric) => (
                    <span key={metric} style={miniChipStyle}>{metric}</span>
                  ))}
                </div>
                <InfoRow label="pricing 接口" value={data.llm_gateway.pricing_url || '-'} />
                <InfoRow
                  label="最近检测"
                  value={data.llm_gateway.last_check?.ok ? `可访问 · ${formatTime(data.llm_gateway.last_check?.checked_at)}` : formatTime(data.llm_gateway.last_check?.checked_at)}
                />
                <InfoRow label="检测信息" value={data.llm_gateway.last_check?.message || '-'} />
              </div>
            </div>
          </section>

          <section id="case-assignments" style={sectionStyle}>
            <SectionTitle title="标注样本分配" />
            <div style={{ color: 'var(--text-secondary)', marginBottom: 12 }}>
              这里用于分配需要勾画/标注的样本：例如 150 例分给 5 人后，每人只看自己的 30 例标注任务。报告评分库不按人隔离，所有医生都能看到完整 150 例用于年资对比。
            </div>

            <div style={assignmentPanelStyle}>
              <div style={assignmentFormStyle}>
                <label style={compactFieldLabelStyle}>
                  病例库
                  <select
                    style={{ ...fieldStyle, minWidth: 300 }}
                    value={selectedPresetId}
                    onChange={(event) => applyAssignmentPreset(event.target.value)}
                  >
                    {assignmentPresets.length === 0 && <option value="">暂无可用病例库</option>}
                    {assignmentPresets.map((preset) => (
                      <option key={preset.id} value={preset.id}>{preset.label}</option>
                    ))}
                  </select>
                </label>
                <label style={checkboxStyle}>
                  <input
                    type="checkbox"
                    checked={assignmentForm.distribute}
                    onChange={(event) => setAssignmentForm(prev => ({ ...prev, distribute: event.target.checked }))}
                  />
                  <span>平均分给标注人员</span>
                </label>
                <button style={secondaryButtonStyle} onClick={selectAllAssignmentUsers}>选择全部非管理员</button>
                <button
                  style={primaryButtonStyle}
                  onClick={() => void (assignments.length ? clearCurrentAssignments() : saveAssignment())}
                  disabled={selectedCaseIds.length === 0 || (!assignments.length && effectiveAssignmentUserCount === 0)}
                >
                  {assignments.length ? '重新分配（清空当前分配）' : '分配标注任务'}
                </button>
              </div>

              <div style={presetSummaryStyle}>
                <strong>{selectedPreset?.label || '未选择病例库'}</strong>
                <span>{selectedCaseIds.length} 个病例</span>
                <span>数据集：{assignmentForm.dataset || '-'}</span>
                <span>
                  {assignmentForm.user_ids.length
                    ? `已选 ${assignmentForm.user_ids.length} 人${estimatedPerUser ? `，约每人 ${estimatedPerUser} 例` : ''}`
                    : `未手动选人，将使用全部非管理员 ${fallbackAssignmentUserCount} 人`}
                </span>
                <span>已分配 {currentAssignedCount} 例</span>
              </div>
              {selectedPreset?.description && <div style={pathStyle}>{selectedPreset.description}</div>}

              <div style={singleAssignPanelStyle}>
                <div style={{ fontWeight: 700, marginBottom: 8 }}>单独指定病例给个人</div>
                <div style={assignmentFormStyle}>
                  <label style={compactFieldLabelStyle}>
                    标注人员
                    <select
                      style={{ ...fieldStyle, minWidth: 170 }}
                      value={manualAssignForm.user_id}
                      onChange={(event) => setManualAssignForm(prev => ({ ...prev, user_id: event.target.value }))}
                    >
                      <option value="">选择人员</option>
                      {assignmentUsers.filter(user => !user.is_admin).map((user) => (
                        <option key={user.id} value={user.id}>{user.username}</option>
                      ))}
                    </select>
                  </label>
                  <input
                    style={{ ...fieldStyle, minWidth: 260 }}
                    value={manualAssignForm.selection_text}
                    onChange={(event) => setManualAssignForm(prev => ({ ...prev, selection_text: event.target.value }))}
                    placeholder="病例序号，如 1,5~10"
                  />
                  <button
                    style={primaryButtonStyle}
                    onClick={() => void assignSelectedCasesToUser()}
                    disabled={!manualAssignForm.user_id || !manualAssignForm.selection_text.trim() || selectedCaseIds.length === 0}
                  >
                    按序号分配给个人
                  </button>
                  <button
                    style={dangerButtonStyle}
                    onClick={() => void clearSelectedUserAssignments()}
                    disabled={!manualAssignForm.user_id || selectedCaseIds.length === 0}
                  >
                    清空该人员分配
                  </button>
                  <span style={pathStyle}>按下方表格“序号”解析，支持 1、5-10、5~10。</span>
                </div>
              </div>

              <div style={assignmentFormStyle}>
                <button style={secondaryButtonStyle} onClick={() => setShowAddCases(prev => !prev)}>
                  {showAddCases ? '收起添加病例' : '继续添加病例'}
                </button>
                <button style={secondaryButtonStyle} onClick={() => setAddCasesForm(prev => ({ ...prev, target_count: '150' }))}>目标 150 例</button>
                <button style={secondaryButtonStyle} onClick={() => setAddCasesForm(prev => ({ ...prev, target_count: '200' }))}>目标 200 例</button>
              </div>

              {showAddCases && (
                <div style={addCasesPanelStyle}>
                  <div style={assignmentFormStyle}>
                    <input
                      style={{ ...fieldStyle, width: 140 }}
                      type="number"
                      min={selectedCaseIds.length}
                      value={addCasesForm.target_count}
                      onChange={(event) => setAddCasesForm(prev => ({ ...prev, target_count: event.target.value }))}
                      placeholder="目标数量"
                    />
                    <button style={primaryButtonStyle} onClick={() => void addCasesToReportPreset()}>
                      补充病例库
                    </button>
                    <span style={pathStyle}>会优先从 2025 候选病例中自动补足，也可在下面粘贴指定病例 ID。</span>
                  </div>
                  <textarea
                    style={caseIdsTextareaStyle}
                    value={addCasesForm.case_ids_text}
                    onChange={(event) => setAddCasesForm(prev => ({ ...prev, case_ids_text: event.target.value }))}
                    placeholder={'可选：手动追加病例 ID，每行一个。留空则自动从候选库补足目标数量。'}
                    rows={4}
                  />
                </div>
              )}

              <div style={userPickStyle}>
                {assignmentUsers.map((user) => (
                  <label key={user.id} style={{ ...checkboxStyle, opacity: user.is_admin ? 0.7 : 1 }}>
                    <input
                      type="checkbox"
                      checked={assignmentForm.user_ids.includes(user.id)}
                      onChange={() => setAssignmentForm(prev => ({
                        ...prev,
                        user_ids: prev.user_ids.includes(user.id)
                          ? prev.user_ids.filter(id => id !== user.id)
                          : [...prev.user_ids, user.id],
                      }))}
                    />
                    <span>{user.username}{user.is_admin ? '（管理员）' : ''}</span>
                  </label>
                ))}
              </div>

              <button style={linkButtonStyle} onClick={() => setShowAdvancedAssignment(prev => !prev)}>
                {showAdvancedAssignment ? '收起高级手动填写' : '展开高级手动填写'}
              </button>

              {showAdvancedAssignment && (
                <>
                  <div style={assignmentFormStyle}>
                    <select
                      style={fieldStyle}
                      value={assignmentForm.namespace}
                      onChange={(event) => setAssignmentForm(prev => ({ ...prev, namespace: event.target.value }))}
                    >
                      <option value="functional">MRIAgent / 评估病例</option>
                      <option value="annotation">原标注目录病例</option>
                      <option value="segmentation">旧分割病例</option>
                      <option value="experiment">实验图表</option>
                    </select>
                    <input
                      style={fieldStyle}
                      value={assignmentForm.dataset}
                      onChange={(event) => setAssignmentForm(prev => ({ ...prev, dataset: event.target.value }))}
                      placeholder="数据集，可留空"
                    />
                    <input
                      style={fieldStyle}
                      value={assignmentForm.case_id}
                      onChange={(event) => setAssignmentForm(prev => ({ ...prev, case_id: event.target.value }))}
                      placeholder="单个病例 ID，可留空"
                    />
                  </div>
                  <textarea
                    style={caseIdsTextareaStyle}
                    value={assignmentForm.case_ids_text}
                    onChange={(event) => setAssignmentForm(prev => ({ ...prev, case_ids_text: event.target.value }))}
                    placeholder={'批量病例 ID：每行一个，也支持逗号/分号分隔'}
                    rows={7}
                  />
                </>
              )}
            </div>
            <div style={{ overflowX: 'auto', marginTop: 14 }}>
              <table style={tableStyle}>
                <thead>
                  <tr>
                    <Th>序号</Th>
                    <Th>匿名病例</Th>
                    <Th>病种</Th>
                    <Th>性别/年龄</Th>
                    <Th>日期</Th>
                    <Th>序列</Th>
                    <Th>当前负责人</Th>
                    <Th>重新分配</Th>
                  </tr>
                </thead>
                <tbody>
                  {selectedCaseDetails.map((caseDetail, index) => {
                    const currentAssignment = currentAssignmentForCase(caseDetail.case_id);
                    return (
                      <tr key={caseDetail.case_id}>
                        <Td>{index + 1}</Td>
                        <Td>
                          <div style={{ fontWeight: 600 }}>{caseDetail.anon_label || `病例${String(index + 1).padStart(3, '0')}`}</div>
                          <div style={pathStyle}>检查号：{caseDetail.public_case_code || '-'}</div>
                        </Td>
                        <Td>{caseDetail.diseases || '-'}</Td>
                        <Td>{[caseDetail.sex, caseDetail.age].filter(Boolean).join(' / ') || '-'}</Td>
                        <Td>{caseDetail.case_date || '-'}</Td>
                        <Td>{caseDetail.subdirs || '-'}</Td>
                        <Td>{currentAssignment?.username || '-'}</Td>
                        <Td>
                          <select
                            style={{ ...fieldStyle, minWidth: 150 }}
                            value={currentAssignment?.user_id || ''}
                            onChange={(event) => void reassignCase(caseDetail.case_id, event.target.value)}
                          >
                            <option value="">选择负责人</option>
                            {assignmentUsers.filter(user => !user.is_admin).map((user) => (
                              <option key={user.id} value={user.id}>{user.username}</option>
                            ))}
                          </select>
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <details style={{ marginTop: 14 }}>
              <summary style={{ cursor: 'pointer', color: 'var(--accent-gold)' }}>查看标注分配记录</summary>
              <div style={{ overflowX: 'auto', marginTop: 12 }}>
                <table style={tableStyle}>
                  <thead>
                    <tr>
                      <Th>用户</Th>
                      <Th>范围</Th>
                      <Th>数据集</Th>
                      <Th>病例</Th>
                      <Th>创建时间</Th>
                      <Th>操作</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {assignments.slice(0, 120).map((item) => (
                      <tr key={item.id}>
                        <Td>{item.username || item.user_id}</Td>
                        <Td>{item.namespace}</Td>
                        <Td>{item.dataset || '-'}</Td>
                        <Td>{item.case_id}</Td>
                        <Td>{formatTime(item.created_at)}</Td>
                        <Td>
                          <button style={dangerButtonStyle} onClick={() => void deleteAssignment(item.id)}>移除</button>
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </section>

          <section style={sectionStyle}>
            <SectionTitle title="运行状态" />
            <div style={twoColumnStyle}>
              <div>
                <InfoRow label="后端进程" value={`PID ${data.system.backend_pid}`} />
                <InfoRow label="系统负载" value={data.system.loadavg ? data.system.loadavg.join(' / ') : '-'} />
                <InfoRow label="运行时间" value={formatDuration(data.system.uptime_seconds)} />
                <ProgressRow
                  label="内存"
                  used={data.system.memory.used || 0}
                  total={data.system.memory.total || 0}
                  valueText={`${formatBytes(data.system.memory.used)} / ${formatBytes(data.system.memory.total)}`}
                />
              </div>
              <div>
                {data.system.gpus.length ? data.system.gpus.map((gpu) => (
                  <ProgressRow
                    key={gpu.index}
                    label={`GPU ${gpu.index}`}
                    used={gpu.memory_used_mb}
                    total={gpu.memory_total_mb}
                    valueText={`${gpu.name} | ${gpu.utilization}% | ${Math.round(gpu.memory_used_mb)} / ${Math.round(gpu.memory_total_mb)} MB | ${gpu.temperature}C`}
                  />
                )) : (
                  <div style={{ color: 'var(--text-secondary)' }}>没有检测到 GPU 状态。</div>
                )}
              </div>
            </div>
          </section>

          <section style={sectionStyle}>
            <SectionTitle title="数据量" />
            <div style={{ overflowX: 'auto' }}>
              <table style={tableStyle}>
                <thead>
                  <tr>
                    <Th>目录</Th>
                    <Th>状态</Th>
                    <Th>数据集</Th>
                    <Th>病例</Th>
                    <Th>磁盘</Th>
                    <Th>路径</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.data.roots.map((root) => (
                    <tr key={root.key}>
                      <Td>{root.label}</Td>
                      <Td>{root.exists ? '可访问' : '不存在'}</Td>
                      <Td>{root.datasets}</Td>
                      <Td>{root.cases}</Td>
                      <Td>{root.disk ? `${formatBytes(root.disk.used)} / ${formatBytes(root.disk.total)}` : '-'}</Td>
                      <Td><span style={pathStyle}>{root.path}</span></Td>
                    </tr>
                  ))}
                  <tr>
                    <Td>CVI 病例目录</Td>
                    <Td>数据库索引</Td>
                    <Td>-</Td>
                    <Td>{data.data.cvi_catalog.total}</Td>
                    <Td>已导入 {data.data.cvi_catalog.imported}，含 DICOM {data.data.cvi_catalog.dicom_cases}</Td>
                    <Td>-</Td>
                  </tr>
                  <tr>
                    <Td>系统数据库</Td>
                    <Td>SQLite</Td>
                    <Td>{Object.keys(data.data.database.tables).length}</Td>
                    <Td>-</Td>
                    <Td>{formatBytes(data.data.database.size_bytes)}</Td>
                    <Td><span style={pathStyle}>{data.data.database.path}</span></Td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section style={sectionStyle}>
            <SectionTitle title="中心数据映射" />
            <div style={{ color: 'var(--text-secondary)', marginBottom: 12 }}>
              汇总四个中心对应的目录变量、样本量、Excel 文件和报告字段拆分规则，方便核对原始数据与测试集 `new_` 目录。
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={tableStyle}>
                <thead>
                  <tr>
                    <Th>中心</Th>
                    <Th>配置变量</Th>
                    <Th>原始目录</Th>
                    <Th>MRIAgent 目录</Th>
                    <Th>输出目录</Th>
                    <Th>`new_` 测试目录</Th>
                    <Th>Excel</Th>
                    <Th>变量数</Th>
                    <Th>病例主键列</Th>
                    <Th>描述列</Th>
                    <Th>结论列</Th>
                    <Th>补充列</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.data.dataset_mappings.map((item) => (
                    <tr key={item.dataset}>
                      <Td>{item.dataset}</Td>
                      <Td>{item.config_keys.join(' / ')}</Td>
                      <Td>
                        <div>{item.annotation_exists ? `${item.annotation_cases} 例` : '未配置'}</div>
                        <span style={pathStyle}>{item.annotation_path || '-'}</span>
                      </Td>
                      <Td>
                        <div>{item.functional_exists ? `${item.functional_cases} 例` : '未找到'}</div>
                        <span style={pathStyle}>{item.functional_path || '-'}</span>
                      </Td>
                      <Td>
                        <div>{item.eval_exists ? `${item.eval_cases} 例` : '未找到'}</div>
                        <span style={pathStyle}>{item.eval_path || '-'}</span>
                      </Td>
                      <Td>
                        <div>{item.eval_new_exists ? `${item.eval_new_cases} 例` : '未找到'}</div>
                        <span style={pathStyle}>{item.eval_new_path || '-'}</span>
                      </Td>
                      <Td>
                        <div>{item.excel_file}</div>
                        <span style={pathStyle}>{item.excel_path}</span>
                      </Td>
                      <Td>{item.excel_columns ?? '-'}</Td>
                      <Td>{item.id_column}</Td>
                      <Td>{item.description_cols.join(' / ') || '-'}</Td>
                      <Td>{item.conclusion_cols.join(' / ') || '-'}</Td>
                      <Td>{item.extra_cols.join(' / ') || '-'}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section style={sectionStyle}>
            <SectionTitle title="标注情况" />
            <div style={moduleGridStyle}>
              {data.annotations.modules.map((module) => (
                <div key={module.key} style={moduleCardStyle}>
                  <div style={{ fontWeight: 700 }}>{module.label}</div>
                  <div style={{ fontSize: 26, fontWeight: 800, color: 'var(--accent-gold)' }}>{module.records}</div>
                  <div style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
                    {module.unique_cases} 例次，已关联用户 {module.assigned_records}
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section style={sectionStyle}>
            <SectionTitle title="用户工作量" />
            <div style={{ overflowX: 'auto' }}>
              <table style={tableStyle}>
                <thead>
                  <tr>
                    <Th>用户</Th>
                    <Th>状态</Th>
                    <Th>登录</Th>
                    <Th>最近登录</Th>
                    <Th>最近退出</Th>
                    <Th>标注记录</Th>
                    <Th>病例数</Th>
                    <Th>首次标注</Th>
                    <Th>最近标注</Th>
                    <Th>模块</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.users.workloads.map((user) => (
                    <tr key={user.id}>
                      <Td>{user.username}</Td>
                      <Td>
                        <span style={{ ...badgeStyle, borderColor: user.is_online ? 'var(--success-color)' : 'var(--border-color)' }}>
                          {user.status}{user.is_online ? ' / 在线' : ''}
                        </span>
                      </Td>
                      <Td>{user.login_count}</Td>
                      <Td>{formatTime(user.last_login_at)}</Td>
                      <Td>{formatTime(user.last_logout_at)}</Td>
                      <Td>{user.total_records}</Td>
                      <Td>{user.unique_cases}</Td>
                      <Td>{formatTime(user.first_activity_at)}</Td>
                      <Td>{formatTime(user.last_activity_at)}</Td>
                      <Td>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                          {Object.entries(user.module_counts).map(([key, count]) => (
                            <span key={key} style={miniChipStyle}>{moduleLabels[key] || key}: {count}</span>
                          ))}
                        </div>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section style={sectionStyle}>
            <SectionTitle title="最近标注" />
            <div style={{ overflowX: 'auto' }}>
              <table style={tableStyle}>
                <thead>
                  <tr>
                    <Th>时间</Th>
                    <Th>用户</Th>
                    <Th>模块</Th>
                    <Th>病例</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.annotations.recent_activity.map((item, index) => (
                    <tr key={`${item.module}-${item.case}-${item.time}-${index}`}>
                      <Td>{formatTime(item.time)}</Td>
                      <Td>{item.user || '-'}</Td>
                      <Td>{item.module}</Td>
                      <Td>{item.case}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section style={sectionStyle}>
            <SectionTitle title="影像访问日志" />
            <div style={{ color: 'var(--text-secondary)', marginBottom: 12 }}>
              记录影像访问、来源拦截、频率限制和分配拦截；用于发现异常批量访问。
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={tableStyle}>
                <thead>
                  <tr>
                    <Th>时间</Th>
                    <Th>用户</Th>
                    <Th>状态</Th>
                    <Th>类型</Th>
                    <Th>病例</Th>
                    <Th>IP</Th>
                    <Th>路径</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.security.recent_media_logs.map((item) => (
                    <tr key={item.id}>
                      <Td>{formatTime(item.created_at)}</Td>
                      <Td>{item.username || '-'}</Td>
                      <Td>{item.status}</Td>
                      <Td>{item.kind}</Td>
                      <Td>{[item.namespace, item.dataset, item.case_id].filter(Boolean).join(' / ') || '-'}</Td>
                      <Td>{item.ip_address || '-'}</Td>
                      <Td><span style={pathStyle}>{item.path || '-'}</span></Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
};

const SummaryCard = ({ label, value, detail }: { label: string; value: React.ReactNode; detail: string }) => (
  <div style={summaryCardStyle}>
    <div style={{ color: 'var(--text-secondary)', fontSize: 13 }}>{label}</div>
    <div style={{ fontSize: 32, fontWeight: 800, marginTop: 8 }}>{value}</div>
    <div style={{ color: 'var(--text-tertiary)', fontSize: 13, marginTop: 4 }}>{detail}</div>
  </div>
);

const SectionTitle = ({ title }: { title: string }) => (
  <h3 style={{ margin: '0 0 16px', fontSize: 18 }}>{title}</h3>
);

const InfoRow = ({ label, value }: { label: string; value: React.ReactNode }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, padding: '8px 0', borderBottom: '1px solid var(--border-color)' }}>
    <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
    <span>{value}</span>
  </div>
);

const ProgressRow = ({ label, used, total, valueText }: { label: string; used: number; total: number; valueText: string }) => {
  const percent = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 6 }}>
        <span style={{ fontWeight: 700 }}>{label}</span>
        <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>{valueText}</span>
      </div>
      <div style={barTrackStyle}>
        <div style={{ ...barFillStyle, width: `${percent}%` }} />
      </div>
    </div>
  );
};

const Th = ({ children }: { children: React.ReactNode }) => <th style={thStyle}>{children}</th>;
const Td = ({ children }: { children: React.ReactNode }) => <td style={tdStyle}>{children}</td>;

const formatBytes = (value?: number | null) => {
  if (!value) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
};

const formatTime = (value?: string | null) => {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { hour12: false });
};

const formatDuration = (seconds?: number | null) => {
  if (!seconds) return '-';
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${days} 天 ${hours} 小时 ${minutes} 分钟`;
};

const pageStyle: React.CSSProperties = {
  padding: 24,
  color: 'var(--text-primary)',
  minHeight: '100%',
};

const headerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'flex-start',
  justifyContent: 'space-between',
  gap: 16,
  marginBottom: 20,
};

const summaryGridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))',
  gap: 14,
  marginBottom: 18,
};

const summaryCardStyle: React.CSSProperties = {
  background: 'var(--bg-secondary)',
  border: '1px solid var(--border-color)',
  borderRadius: 8,
  padding: 18,
};

const sectionStyle: React.CSSProperties = {
  background: 'var(--bg-secondary)',
  border: '1px solid var(--border-color)',
  borderRadius: 8,
  padding: 18,
  marginBottom: 18,
};

const twoColumnStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
  gap: 28,
};

const moduleGridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
  gap: 12,
};

const moduleCardStyle: React.CSSProperties = {
  border: '1px solid var(--border-color)',
  borderRadius: 8,
  padding: 14,
  background: 'var(--bg-primary)',
};

const tableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  minWidth: 860,
};

const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '10px 12px',
  borderBottom: '1px solid var(--border-color)',
  color: 'var(--text-secondary)',
  fontWeight: 700,
  whiteSpace: 'nowrap',
};

const tdStyle: React.CSSProperties = {
  padding: '10px 12px',
  borderBottom: '1px solid var(--border-color)',
  verticalAlign: 'top',
};

const primaryButtonStyle: React.CSSProperties = {
  padding: '8px 14px',
  borderRadius: 6,
  border: '1px solid var(--accent-gold)',
  background: 'var(--accent-gold)',
  color: '#fff',
  cursor: 'pointer',
};

const secondaryButtonStyle: React.CSSProperties = {
  ...primaryButtonStyle,
  background: 'transparent',
  color: 'var(--accent-gold)',
  textDecoration: 'none',
};

const dangerButtonStyle: React.CSSProperties = {
  padding: '6px 10px',
  borderRadius: 6,
  border: '1px solid var(--error-color)',
  background: 'transparent',
  color: 'var(--error-color)',
  cursor: 'pointer',
};

const fieldStyle: React.CSSProperties = {
  minWidth: 160,
  padding: '8px 10px',
  borderRadius: 6,
  border: '1px solid var(--border-color)',
  background: 'var(--bg-primary)',
  color: 'var(--text-primary)',
};

const caseIdsTextareaStyle: React.CSSProperties = {
  ...fieldStyle,
  display: 'block',
  width: '100%',
  minHeight: 130,
  marginTop: 10,
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
  lineHeight: 1.45,
  resize: 'vertical',
};

const assignmentPanelStyle: React.CSSProperties = {
  border: '1px solid var(--border-color)',
  borderRadius: 10,
  padding: 14,
  background: 'var(--bg-primary)',
};

const addCasesPanelStyle: React.CSSProperties = {
  marginTop: 10,
  padding: 12,
  borderRadius: 8,
  border: '1px dashed var(--border-color)',
  background: 'var(--bg-secondary)',
};

const singleAssignPanelStyle: React.CSSProperties = {
  marginTop: 12,
  marginBottom: 12,
  padding: 12,
  borderRadius: 8,
  border: '1px solid var(--border-color)',
  background: 'var(--bg-secondary)',
};

const assignmentFormStyle: React.CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 10,
  alignItems: 'center',
};


const compactFieldLabelStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  color: 'var(--text-secondary)',
};

const presetSummaryStyle: React.CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 10,
  alignItems: 'center',
  marginTop: 12,
  marginBottom: 8,
  color: 'var(--text-secondary)',
};

const linkButtonStyle: React.CSSProperties = {
  border: 'none',
  background: 'transparent',
  color: 'var(--accent-gold)',
  cursor: 'pointer',
  padding: '8px 0',
  marginTop: 8,
};

const userPickStyle: React.CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 8,
  marginTop: 12,
};

const checkboxStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  padding: '5px 8px',
  borderRadius: 6,
  border: '1px solid var(--border-color)',
  color: 'var(--text-secondary)',
};

const errorStyle: React.CSSProperties = {
  padding: 12,
  borderRadius: 8,
  border: '1px solid var(--error-color)',
  color: 'var(--error-color)',
  marginBottom: 16,
};

const pathStyle: React.CSSProperties = {
  color: 'var(--text-secondary)',
  fontSize: 12,
  wordBreak: 'break-all',
};

const badgeStyle: React.CSSProperties = {
  display: 'inline-flex',
  padding: '3px 8px',
  borderRadius: 6,
  border: '1px solid var(--border-color)',
  fontSize: 12,
  whiteSpace: 'nowrap',
};

const miniChipStyle: React.CSSProperties = {
  ...badgeStyle,
  color: 'var(--text-secondary)',
};

const barTrackStyle: React.CSSProperties = {
  height: 8,
  borderRadius: 4,
  background: 'var(--bg-tertiary)',
  overflow: 'hidden',
};

const barFillStyle: React.CSSProperties = {
  height: '100%',
  borderRadius: 4,
  background: 'var(--accent-gold)',
};

export default AdminMonitorPage;
