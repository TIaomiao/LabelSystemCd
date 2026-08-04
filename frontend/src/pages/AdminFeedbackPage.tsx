import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import { FaArrowLeft, FaChartLine, FaClipboardCheck, FaComments, FaCopy, FaExclamationTriangle, FaFilter, FaPlay, FaRegEye, FaShieldAlt, FaSyncAlt } from 'react-icons/fa';
import { useAuth } from '../context/AuthContext';
import './AdminFeedbackPage.css';

interface FeedbackUser {
  id: number;
  username: string;
  session_count: number;
}

interface FeedbackOverview {
  summary: { sessions: number; messages: number; issues: number; open_issues: number };
  categories: Record<string, number>;
  statuses: Record<string, number>;
  daily_sessions: { date: string; count: number }[];
  users: FeedbackUser[];
}

interface FeedbackIssue {
  id: number;
  session_id: number;
  reporter_id: number;
  reporter_username: string;
  category: string;
  title: string;
  summary: string;
  page: string;
  operation: string;
  expected_behavior: string;
  actual_behavior: string;
  impact: string;
  severity: string;
  status: string;
  acceptance_criteria: string;
  change_scope: string;
  admin_note: string;
  created_at: string;
  updated_at: string;
}

interface FeedbackSession {
  id: number;
  user_id: number;
  username: string;
  title: string;
  created_at: string;
  last_message_at: string;
  last_user_message_at?: string | null;
}

interface FeedbackMessage {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  reasoning_level: string;
  rating?: string | null;
  created_at: string;
  model_name?: string | null;
  latency_ms?: number | null;
  attachments?: {
    id: number;
    url: string;
    width: number;
    height: number;
    original_name: string;
  }[];
}

interface FeedbackWorkPlan {
  id: number;
  status: 'draft' | 'approved' | 'queued' | 'verified' | string;
  proposal: {
    solution_summary?: string;
    root_cause?: string;
    implementation_steps?: string[];
    allowed_paths?: string[];
    risks?: { level?: string; risk?: string; mitigation?: string }[];
    verification_steps?: string[];
    execution_scope?: string;
    codex_brief?: string;
    repository_evidence?: { path?: string; line_start?: number; line_end?: number; reason?: string }[];
    confidence?: 'high' | 'medium' | 'low' | string;
    implementation_size?: 'small' | 'medium' | 'large' | string;
    base_sha?: string;
    branch?: string;
    dirty_worktree?: boolean;
    clarifying_question?: string;
    reproducibility?: 'code_only' | 'demo_cases' | 'production_data_required' | string;
    data_requirements?: string;
  };
  generated_by?: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
  queue_note?: string;
  execution_note?: string;
}

interface FeedbackCodexResult {
  investigation_summary?: string;
  root_cause?: string;
  confidence?: 'high' | 'medium' | 'low' | string;
  implementation_size?: 'small' | 'medium' | 'large' | string;
  recommended_changes?: { path?: string; change?: string; rationale?: string }[];
  risks?: { level?: string; risk?: string; mitigation?: string }[];
  verification_steps?: string[];
  execution_scope?: string;
  reproducibility?: string;
  data_requirements?: string;
  clarifying_question?: string;
}

interface FeedbackCodexRun {
  id: number;
  issue_id: number;
  status: 'pending' | 'running' | 'completed' | 'failed' | string;
  phase: string;
  revision_note?: string;
  result?: FeedbackCodexResult;
  base_sha?: string;
  branch?: string;
  dirty_worktree?: boolean;
  model_name?: string;
  error_message?: string;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

interface FeedbackExecutionRun {
  id: number;
  issue_id: number;
  work_plan_id: number;
  attempt: number;
  status: 'queued' | 'preparing' | 'running' | 'stopping' | 'stopped' | 'failed' | 'review_ready' | 'review_approved' | 'review_rejected' | 'merging' | 'merged' | string;
  phase: string;
  base_sha: string;
  target_branch: string;
  candidate_branch?: string;
  candidate_sha?: string;
  diff_hash?: string;
  changed_files?: string[];
  changed_file_count: number;
  tests?: { commands?: { id: string; command?: string[]; passed: boolean; exit_code?: number; error?: string }[]; passed?: boolean };
  tests_passed?: boolean | null;
  review_note?: string;
  merge_note?: string;
  error_message?: string;
  stop_requested?: boolean;
  version: number;
  initiated_by?: string | null;
  reviewed_by?: string | null;
  merged_by?: string | null;
  worktree_path?: string;
  artifact_dir?: string;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  reviewed_at?: string | null;
  merged_at?: string | null;
  updated_at?: string | null;
}

const categoryLabels: Record<string, string> = {
  usage_help: '使用咨询',
  bug: 'Bug',
  feature_request: '功能需求',
  data_issue: '数据问题',
  ai_experience: 'AI 体验',
  other: '其他',
};

const statusLabels: Record<string, string> = {
  open: '待处理',
  reviewing: '确认中',
  planned: '已排期',
  fixed: '已修复',
  closed: '已关闭',
};

const scopeLabels: Record<string, string> = {
  guidance_only: '已有功能指导',
  minimal_candidate: '候选小修复',
  needs_review: '执行前需审查',
  large_change: '较大改动',
};

const workPlanStatusLabels: Record<string, string> = {
  draft: '待确认方案',
  approved: '已批准',
  queued: '受控执行中/待审',
  verified: '已验证',
};

const executionStatusLabels: Record<string, string> = {
  queued: '等待执行',
  preparing: '创建独立工作树',
  running: 'Codex 修改中',
  stopping: '正在停止',
  stopped: '已停止',
  failed: '执行失败',
  review_ready: '等待代码审查',
  review_approved: '代码已批准',
  review_rejected: '代码已拒绝',
  merging: '正在合并',
  merged: '已合并，未发布',
};

const codexInvestigationStatusLabels: Record<string, string> = {
  pending: '仓库调查排队中',
  running: 'Codex 正在调查仓库',
  completed: '仓库调查完成',
  failed: '仓库调查失败',
};

const confidenceLabels: Record<string, string> = { high: '高', medium: '中', low: '低' };
const implementationSizeLabels: Record<string, string> = { small: '小改动', medium: '中等改动', large: '大型改动' };
const riskLevelLabels: Record<string, string> = { low: '低', medium: '中', high: '高', critical: '严重' };
const riskPriority: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 };

const parseImplementationStep = (step: string) => {
  const separator = step.indexOf('：');
  if (separator > 0) {
    const path = step.slice(0, separator).trim();
    if (path.includes('/')) return { path, change: step.slice(separator + 1).trim() };
  }
  return { path: '', change: step };
};

const reproducibilityLabels: Record<string, string> = {
  code_only: '仅凭代码即可判断',
  demo_cases: '可用 2–5 个 demo case 复现',
  production_data_required: '需要生产数据或运行证据',
};

const readJson = async (response: Response) => {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || '请求失败');
  return payload;
};

const formatTime = (value?: string | null) => value
  ? new Date(value.endsWith('Z') ? value : `${value}Z`).toLocaleString('zh-CN', { hour12: false })
  : '-';

const formatRisks = (risks: FeedbackWorkPlan['proposal']['risks'] = []) =>
  risks.map(item => `${item.level || 'medium'} | ${item.risk || ''} | ${item.mitigation || ''}`).join('\n');

const parseRisks = (value: string) => value.split('\n')
  .map(line => line.split('|').map(part => part.trim()))
  .filter(parts => parts.some(Boolean))
  .map(([level, risk, mitigation]) => ({ level: level || 'medium', risk: risk || '', mitigation: mitigation || '' }));

const AdminFeedbackPage: React.FC = () => {
  const { user } = useAuth();
  const location = useLocation();
  const readOnly = !user?.is_admin;
  const canOperatePlans = !!user?.is_admin || user?.username === 'ziantestpov';
  const canControlExecution = !!user?.is_admin;
  const isDedicatedDashboard = location.pathname === '/feedback-dashboard';
  const [view, setView] = useState<'issues' | 'sessions'>('issues');
  const [overview, setOverview] = useState<FeedbackOverview | null>(null);
  const [issues, setIssues] = useState<FeedbackIssue[]>([]);
  const [sessions, setSessions] = useState<FeedbackSession[]>([]);
  const [selectedIssue, setSelectedIssue] = useState<FeedbackIssue | null>(null);
  const [selectedSession, setSelectedSession] = useState<FeedbackSession | null>(null);
  const [messages, setMessages] = useState<FeedbackMessage[]>([]);
  const [workPlan, setWorkPlan] = useState<FeedbackWorkPlan | null>(null);
  const [codexInvestigation, setCodexInvestigation] = useState<FeedbackCodexRun | null>(null);
  const [investigationHistory, setInvestigationHistory] = useState<FeedbackCodexRun[]>([]);
  const [executionRun, setExecutionRun] = useState<FeedbackExecutionRun | null>(null);
  const [executionCapability, setExecutionCapability] = useState(false);
  const [executionEvents, setExecutionEvents] = useState('');
  const [executionEventOffset, setExecutionEventOffset] = useState(0);
  const [executionSummary, setExecutionSummary] = useState('');
  const [executionDiff, setExecutionDiff] = useState<{ files: string[]; unified_diff: string; stat: string }>({ files: [], unified_diff: '', stat: '' });
  const [executionTab, setExecutionTab] = useState<'events' | 'diff' | 'tests' | 'review'>('events');
  const [reviewNote, setReviewNote] = useState('');
  const [overviewExpanded, setOverviewExpanded] = useState(false);
  const [editingIssue, setEditingIssue] = useState(false);
  const [issueDraft, setIssueDraft] = useState<Partial<FeedbackIssue>>({});
  const [editingPlan, setEditingPlan] = useState(false);
  const [planDraft, setPlanDraft] = useState<FeedbackWorkPlan['proposal']>({});
  const [revisionNote, setRevisionNote] = useState('');
  const [userId, setUserId] = useState('');
  const [category, setCategory] = useState('');
  const [status, setStatus] = useState('');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState('');
  const selectedIssueIdRef = useRef<number | null>(null);
  const executionRunIdRef = useRef<number | null>(null);
  const executionEventsLoadingRef = useRef(false);

  const queryString = useMemo(() => {
    const params = new URLSearchParams();
    if (userId) params.set('user_id', userId);
    if (category) params.set('category', category);
    if (status) params.set('status', status);
    if (start) params.set('start', start);
    if (end) params.set('end', end);
    if (search) params.set('search', search);
    return params.toString();
  }, [userId, category, status, start, end, search]);

  const loadOverview = useCallback(async () => {
    const response = await fetch('/api/admin/feedback/overview');
    const payload = await readJson(response);
    setOverview(payload);
  }, []);

  const loadList = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      if (view === 'issues') {
        const response = await fetch(`/api/admin/feedback/issues${queryString ? `?${queryString}` : ''}`);
        const payload = await readJson(response);
        const nextIssues = payload.issues || [];
        setIssues(nextIssues);
        setSelectedIssue(current => nextIssues.find((item: FeedbackIssue) => item.id === current?.id) || nextIssues[0] || null);
      } else {
        const params = new URLSearchParams(queryString);
        params.delete('category');
        params.delete('status');
        params.delete('search');
        const suffix = params.toString();
        const response = await fetch(`/api/admin/feedback/sessions${suffix ? `?${suffix}` : ''}`);
        const payload = await readJson(response);
        const nextSessions = payload.sessions || [];
        setSessions(nextSessions);
        if (!nextSessions.length) {
          setSelectedSession(null);
          setMessages([]);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载反馈失败');
    } finally {
      setLoading(false);
    }
  }, [queryString, view]);

  useEffect(() => {
    void Promise.all([loadOverview(), loadList()]).catch(err => {
      setError(err instanceof Error ? err.message : '加载反馈失败');
    });
  }, [loadList, loadOverview]);

  const openSession = async (session: FeedbackSession) => {
    setSelectedSession(session);
    setError('');
    try {
      const response = await fetch(`/api/admin/feedback/sessions/${session.id}/messages`);
      const payload = await readJson(response);
      setMessages(payload.messages || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载对话失败');
    }
  };

  const openSessionById = async (sessionId: number) => {
    setError('');
    try {
      const response = await fetch(`/api/admin/feedback/sessions/${sessionId}/messages`);
      const payload = await readJson(response);
      setSelectedSession(payload.session);
      setMessages(payload.messages || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载对话失败');
    }
  };

  const loadWorkPlan = useCallback(async (issueId: number) => {
    try {
      const response = await fetch(`/api/admin/feedback/issues/${issueId}/work-plan`);
      const payload = await readJson(response);
      if (selectedIssueIdRef.current !== issueId) return;
      setWorkPlan(payload.work_plan || null);
      setCodexInvestigation(payload.codex_investigation || null);
      setInvestigationHistory(payload.investigation_history || []);
      setExecutionRun(payload.execution || null);
      setExecutionCapability(payload.execution_capability?.enabled === true);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载方案失败');
    }
  }, []);

  useEffect(() => {
    selectedIssueIdRef.current = selectedIssue?.id || null;
    if (!selectedIssue) {
      setWorkPlan(null);
      setCodexInvestigation(null);
      setInvestigationHistory([]);
      setExecutionRun(null);
      setExecutionCapability(false);
      setExecutionEvents('');
      setExecutionEventOffset(0);
      setExecutionSummary('');
      setExecutionDiff({ files: [], unified_diff: '', stat: '' });
      setEditingIssue(false);
      setEditingPlan(false);
      setRevisionNote('');
      return;
    }
    setEditingIssue(false);
    setEditingPlan(false);
    setRevisionNote('');
    setIssueDraft({});
    setCodexInvestigation(null);
    setInvestigationHistory([]);
    setExecutionRun(null);
    setExecutionCapability(false);
    setExecutionEvents('');
    setExecutionEventOffset(0);
    setExecutionSummary('');
    setExecutionDiff({ files: [], unified_diff: '', stat: '' });
    setExecutionTab('events');
    setReviewNote('');
    void loadWorkPlan(selectedIssue.id);
  }, [loadWorkPlan, selectedIssue?.id]);

  useEffect(() => {
    if (!selectedIssue || !['pending', 'running'].includes(codexInvestigation?.status || '')) return;
    const timer = window.setInterval(() => {
      void loadWorkPlan(selectedIssue.id);
    }, 3500);
    return () => window.clearInterval(timer);
  }, [codexInvestigation?.status, loadWorkPlan, selectedIssue?.id]);

  const executionActive = ['queued', 'preparing', 'running', 'stopping', 'merging'].includes(executionRun?.status || '');

  useEffect(() => {
    if (!selectedIssue || !executionActive) return;
    const timer = window.setInterval(() => {
      void loadWorkPlan(selectedIssue.id);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [executionActive, loadWorkPlan, selectedIssue?.id]);

  const loadExecutionEvents = useCallback(async (run: FeedbackExecutionRun, offset: number) => {
    if (executionEventsLoadingRef.current) return;
    executionEventsLoadingRef.current = true;
    try {
      const response = await fetch(`/api/admin/feedback/executions/${run.id}/events?offset=${offset}`);
      const payload = await readJson(response);
      if (executionRunIdRef.current !== run.id) return;
      if (payload.events) setExecutionEvents(current => `${current}${payload.events}`.slice(-180000));
      setExecutionEventOffset(payload.offset || offset);
      if (payload.summary) setExecutionSummary(payload.summary);
      if (payload.stderr_tail && !payload.events) setExecutionEvents(current => `${current}\n${payload.stderr_tail}`.slice(-180000));
    } finally {
      executionEventsLoadingRef.current = false;
    }
  }, []);

  useEffect(() => {
    executionRunIdRef.current = executionRun?.id || null;
    if (!executionRun || !canControlExecution) return;
    void loadExecutionEvents(executionRun, executionEventOffset).catch(err => setError(err instanceof Error ? err.message : '加载执行记录失败'));
    if (!executionActive) return;
    const timer = window.setInterval(() => {
      void loadExecutionEvents(executionRun, executionEventOffset).catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [canControlExecution, executionActive, executionEventOffset, executionRun?.id, loadExecutionEvents]);

  useEffect(() => {
    if (!canControlExecution || !executionRun || !['failed', 'stopped', 'review_ready', 'review_approved', 'review_rejected', 'merged'].includes(executionRun.status)) return;
    void Promise.all([
      fetch(`/api/admin/feedback/executions/${executionRun.id}/diff`).then(readJson),
      fetch(`/api/admin/feedback/executions/${executionRun.id}/tests`).then(readJson),
    ]).then(([diffPayload, testsPayload]) => {
      if (executionRunIdRef.current !== executionRun.id) return;
      setExecutionDiff(diffPayload);
      setExecutionRun(current => current?.id === executionRun.id ? { ...current, tests: testsPayload.tests, tests_passed: testsPayload.passed } : current);
    }).catch(err => setError(err instanceof Error ? err.message : '加载候选改动失败'));
  }, [canControlExecution, executionRun?.id, executionRun?.status]);

  const updateIssue = async (patch: Partial<FeedbackIssue>) => {
    if (!selectedIssue) return;
    setSaving(true);
    setError('');
    try {
      const response = await fetch(`/api/admin/feedback/issues/${selectedIssue.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      const payload = await readJson(response);
      setSelectedIssue(payload.issue);
      setIssues(current => current.map(item => item.id === payload.issue.id ? payload.issue : item));
      await loadOverview();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const applyIssueUpdate = (issue: FeedbackIssue) => {
    setSelectedIssue(issue);
    setIssues(current => current.map(item => item.id === issue.id ? issue : item));
  };

  const generateWorkPlan = async () => {
    if (!selectedIssue || planning) return;
    setPlanning(true);
    setError('');
    try {
      const response = await fetch(`/api/admin/feedback/issues/${selectedIssue.id}/work-plan/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ revision_note: revisionNote }),
      });
      const payload = await readJson(response);
      setWorkPlan(payload.work_plan || null);
      setCodexInvestigation(payload.codex_investigation || null);
      if (payload.codex_investigation) {
        setInvestigationHistory(current => [
          ...current.filter(item => item.id !== payload.codex_investigation.id),
          payload.codex_investigation,
        ]);
      }
      applyIssueUpdate(payload.issue);
      setRevisionNote('');
      setEditingPlan(false);
      await loadOverview();
    } catch (err) {
      setError(err instanceof Error ? err.message : '方案生成失败');
    } finally {
      setPlanning(false);
    }
  };

  const approveWorkPlan = async () => {
    if (!selectedIssue || !workPlan || planning) return;
    setPlanning(true);
    setError('');
    try {
      const response = await fetch(`/api/admin/feedback/issues/${selectedIssue.id}/work-plan/approve`, { method: 'POST' });
      const payload = await readJson(response);
      setWorkPlan(payload.work_plan);
      applyIssueUpdate(payload.issue);
      await loadOverview();
    } catch (err) {
      setError(err instanceof Error ? err.message : '批准方案失败');
    } finally {
      setPlanning(false);
    }
  };

  const queueWorkPlan = async () => {
    if (!selectedIssue || !workPlan || planning) return;
    if (!window.confirm('确认启动受控 Codex？它只会在独立 Git worktree 中修改并生成候选提交，不会部署；主仓库不干净或基线漂移时会拒绝启动。')) return;
    setPlanning(true);
    setError('');
    try {
      const response = await fetch(`/api/admin/feedback/issues/${selectedIssue.id}/work-plan/queue`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-LabelSystem-Action': 'controlled-feedback' }, body: JSON.stringify({}) });
      const payload = await readJson(response);
      setWorkPlan(payload.work_plan);
      setExecutionRun(payload.execution || null);
      setExecutionEvents('');
      setExecutionEventOffset(0);
      setExecutionSummary('');
      setExecutionTab('events');
    } catch (err) {
      setError(err instanceof Error ? err.message : '进入执行队列失败');
    } finally {
      setPlanning(false);
    }
  };

  const executionAction = async (path: string, body: Record<string, unknown> = {}) => {
    if (!executionRun || planning) return;
    setPlanning(true);
    setError('');
    try {
      const response = await fetch(`/api/admin/feedback/executions/${executionRun.id}/${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-LabelSystem-Action': 'controlled-feedback' },
        body: JSON.stringify({ expected_version: executionRun.version, ...body }),
      });
      const payload = await readJson(response);
      if (payload.execution) setExecutionRun(payload.execution);
      if (payload.work_plan) setWorkPlan(payload.work_plan);
      if (payload.issue) applyIssueUpdate(payload.issue);
      if (selectedIssue) await loadWorkPlan(selectedIssue.id);
    } catch (err) {
      if (selectedIssue) await loadWorkPlan(selectedIssue.id);
      setError(err instanceof Error ? err.message : '执行操作失败');
    } finally {
      setPlanning(false);
    }
  };

  const stopExecution = () => executionAction('stop');
  const approveExecution = () => executionAction('review/approve', { review_note: reviewNote });
  const rejectExecution = () => executionAction('review/reject', { review_note: reviewNote });
  const reviseExecutionPlan = () => executionAction('revise');
  const mergeExecution = () => {
    if (!executionRun?.candidate_sha) return;
    if (!window.confirm(`确认把候选 ${executionRun.candidate_sha.slice(0, 12)} fast-forward 合入 ${executionRun.target_branch}？这不会发布或重启服务。`)) return;
    void executionAction('merge', { candidate_sha: executionRun.candidate_sha });
  };

  const copyCodexBrief = async () => {
    if (!workPlan?.proposal.codex_brief) return;
    try {
      await navigator.clipboard.writeText(workPlan.proposal.codex_brief);
    } catch {
      setError('浏览器无法复制任务书');
    }
  };

  const beginIssueEdit = () => {
    if (!selectedIssue) return;
    setIssueDraft({
      title: selectedIssue.title,
      page: selectedIssue.page,
      summary: selectedIssue.summary,
      operation: selectedIssue.operation,
      actual_behavior: selectedIssue.actual_behavior,
      expected_behavior: selectedIssue.expected_behavior,
      impact: selectedIssue.impact,
      acceptance_criteria: selectedIssue.acceptance_criteria,
    });
    setEditingIssue(true);
  };

  const saveIssueDraft = async () => {
    if (!selectedIssue || saving) return;
    setSaving(true);
    setError('');
    try {
      const response = await fetch(`/api/admin/feedback/issues/${selectedIssue.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(issueDraft),
      });
      const payload = await readJson(response);
      applyIssueUpdate(payload.issue);
      setEditingIssue(false);
      setWorkPlan(null);
      await loadWorkPlan(payload.issue.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存问题单失败');
    } finally {
      setSaving(false);
    }
  };

  const beginPlanEdit = () => {
    if (!workPlan) return;
    setPlanDraft({
      solution_summary: workPlan.proposal.solution_summary || '',
      root_cause: workPlan.proposal.root_cause || '',
      implementation_steps: [...(workPlan.proposal.implementation_steps || [])],
      allowed_paths: [...(workPlan.proposal.allowed_paths || [])],
      risks: [...(workPlan.proposal.risks || [])],
      verification_steps: [...(workPlan.proposal.verification_steps || [])],
      execution_scope: workPlan.proposal.execution_scope || 'needs_review',
      codex_brief: workPlan.proposal.codex_brief || '',
      repository_evidence: [...(workPlan.proposal.repository_evidence || [])],
      confidence: workPlan.proposal.confidence || 'low',
      implementation_size: workPlan.proposal.implementation_size || 'medium',
      base_sha: workPlan.proposal.base_sha || '',
      branch: workPlan.proposal.branch || '',
      dirty_worktree: !!workPlan.proposal.dirty_worktree,
      clarifying_question: workPlan.proposal.clarifying_question || '',
      reproducibility: workPlan.proposal.reproducibility || 'production_data_required',
      data_requirements: workPlan.proposal.data_requirements || '',
    });
    setEditingPlan(true);
  };

  const savePlanDraft = async () => {
    if (!selectedIssue || !workPlan || planning) return;
    setPlanning(true);
    setError('');
    try {
      const response = await fetch(`/api/admin/feedback/issues/${selectedIssue.id}/work-plan`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal: planDraft }),
      });
      const payload = await readJson(response);
      setWorkPlan(payload.work_plan);
      setEditingPlan(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存方案失败');
    } finally {
      setPlanning(false);
    }
  };

  const maxDaily = Math.max(1, ...(overview?.daily_sessions || []).map(item => item.count));
  const categoryEntries = Object.entries(overview?.categories || {})
    .sort((left, right) => right[1] - left[1]);
  const statusEntries = Object.entries(overview?.statuses || {})
    .sort((left, right) => right[1] - left[1]);
  const activeUsers = [...(overview?.users || [])]
    .filter(item => item.session_count > 0)
    .sort((left, right) => right.session_count - left.session_count)
    .slice(0, 8);
  const maxCategory = Math.max(1, ...categoryEntries.map(([, count]) => count));
  const maxStatus = Math.max(1, ...statusEntries.map(([, count]) => count));
  const maxUserSessions = Math.max(1, ...activeUsers.map(item => item.session_count));
  const investigationActive = ['pending', 'running'].includes(codexInvestigation?.status || '');
  const displayedInvestigationHistory = useMemo(() => {
    if (!codexInvestigation || investigationHistory.some(item => item.id === codexInvestigation.id)) {
      return investigationHistory;
    }
    return [...investigationHistory, codexInvestigation];
  }, [codexInvestigation, investigationHistory]);
  const legacyRootCauseMarker = '\n\n根因判断：';
  const rawPlanSummary = workPlan?.proposal.solution_summary || '';
  const planSummary = rawPlanSummary.includes(legacyRootCauseMarker)
    ? rawPlanSummary.slice(0, rawPlanSummary.indexOf(legacyRootCauseMarker))
    : rawPlanSummary;
  const planRootCause = workPlan?.proposal.root_cause
    || (rawPlanSummary.includes(legacyRootCauseMarker)
      ? rawPlanSummary.slice(rawPlanSummary.indexOf(legacyRootCauseMarker) + legacyRootCauseMarker.length)
      : '当前方案未单独记录根因，请在方案对话中要求 Codex 重新核对。');
  const planSteps = (workPlan?.proposal.implementation_steps || []).map(parseImplementationStep);
  const planRisks = [...(workPlan?.proposal.risks || [])]
    .sort((left, right) => (riskPriority[right.level || 'medium'] || 0) - (riskPriority[left.level || 'medium'] || 0));

  return (
    <div className={`admin-feedback${readOnly ? ' is-read-only' : ''}`}>
      <header className="admin-feedback__header">
        <div className="admin-feedback__brand">
          <div className="admin-feedback__brand-mark"><FaChartLine /></div>
          <div>
            <span>CMR WORKSTATION / FEEDBACK</span>
            <h1>{isDedicatedDashboard ? '反馈数据看板' : '反馈控制台'}</h1>
          </div>
        </div>
        <div className="admin-feedback__header-actions">
          <span className="admin-feedback__access-chip">
            {readOnly ? <FaRegEye /> : <FaShieldAlt />}
            {readOnly ? '专属负责人模式' : '管理员控制模式'}
          </span>
          <Link to="/workstation" className="admin-feedback__return"><FaArrowLeft /> 工作站</Link>
          <button onClick={() => void Promise.all([loadOverview(), loadList()])} title="刷新数据"><FaSyncAlt /> 刷新</button>
        </div>
      </header>

      <main className="admin-feedback__canvas">
      <section className="admin-feedback__section-title">
        <div>
          <strong>一线反馈概览</strong>
          <span>
            对话 {overview?.summary.sessions ?? '-'} · 问题 {overview?.summary.issues ?? '-'} · 待处理 {overview?.summary.open_issues ?? '-'}
          </span>
        </div>
        <div className="admin-feedback__overview-actions">
          <span>{readOnly ? '可审方案、确认队列；不能修改系统权限' : '可管理：状态、优先级与内部备注'}</span>
          <button onClick={() => setOverviewExpanded(current => !current)}>{overviewExpanded ? '收起概览' : '展开概览'}</button>
        </div>
      </section>

      {overviewExpanded && <>
      <section className="admin-feedback__summary" aria-label="反馈概览">
        <div><span>对话</span><strong>{overview?.summary.sessions ?? '-'}</strong><small>医生反馈线程</small></div>
        <div><span>消息</span><strong>{overview?.summary.messages ?? '-'}</strong><small>上下文记录</small></div>
        <div><span>问题单</span><strong>{overview?.summary.issues ?? '-'}</strong><small>可跟进条目</small></div>
        <div><span>待处理</span><strong>{overview?.summary.open_issues ?? '-'}</strong><small>尚未闭环</small></div>
        <div className="admin-feedback__trend">
          <span>近 14 天对话</span>
          <div>
            {(overview?.daily_sessions || []).map(item => (
              <i key={item.date} style={{ height: `${Math.max(8, item.count / maxDaily * 100)}%` }} title={`${item.date}: ${item.count}`} />
            ))}
          </div>
        </div>
      </section>

      <section className="admin-feedback__analytics" aria-label="反馈分类统计">
        <div className="admin-feedback__analytics-group">
          <div className="admin-feedback__analytics-head"><strong>问题类型</strong><button onClick={() => setCategory('')}>全部</button></div>
          <div className="admin-feedback__bar-list">
            {categoryEntries.map(([key, count]) => (
              <button key={key} className={category === key ? 'is-active' : ''} onClick={() => { setView('issues'); setCategory(key); }}>
                <span>{categoryLabels[key] || key}</span>
                <i><b style={{ width: `${count / maxCategory * 100}%` }} /></i>
                <em>{count}</em>
              </button>
            ))}
            {!categoryEntries.length && <small>暂无问题单</small>}
          </div>
        </div>
        <div className="admin-feedback__analytics-group">
          <div className="admin-feedback__analytics-head"><strong>处理状态</strong><button onClick={() => setStatus('')}>全部</button></div>
          <div className="admin-feedback__bar-list">
            {statusEntries.map(([key, count]) => (
              <button key={key} className={status === key ? 'is-active' : ''} onClick={() => { setView('issues'); setStatus(key); }}>
                <span>{statusLabels[key] || key}</span>
                <i><b style={{ width: `${count / maxStatus * 100}%` }} /></i>
                <em>{count}</em>
              </button>
            ))}
            {!statusEntries.length && <small>暂无处理记录</small>}
          </div>
        </div>
        <div className="admin-feedback__analytics-group">
          <div className="admin-feedback__analytics-head"><strong>用户对话量</strong><button onClick={() => setUserId('')}>全部</button></div>
          <div className="admin-feedback__bar-list">
            {activeUsers.map(user => (
              <button key={user.id} className={userId === String(user.id) ? 'is-active' : ''} onClick={() => setUserId(String(user.id))}>
                <span>{user.username}</span>
                <i><b style={{ width: `${user.session_count / maxUserSessions * 100}%` }} /></i>
                <em>{user.session_count}</em>
              </button>
            ))}
            {!activeUsers.length && <small>暂无用户对话</small>}
          </div>
        </div>
      </section>
      </>}

      <section className="admin-feedback__filters">
        <FaFilter />
        <select value={userId} onChange={event => setUserId(event.target.value)}>
          <option value="">全部用户</option>
          {(overview?.users || []).map(user => <option key={user.id} value={user.id}>{user.username} ({user.session_count})</option>)}
        </select>
        <select value={category} onChange={event => setCategory(event.target.value)} disabled={view === 'sessions'}>
          <option value="">全部类型</option>
          {Object.entries(categoryLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
        <select value={status} onChange={event => setStatus(event.target.value)} disabled={view === 'sessions'}>
          <option value="">全部状态</option>
          {Object.entries(statusLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
        <input type="date" value={start} onChange={event => setStart(event.target.value)} title={view === 'sessions' ? '会话创建开始日期' : '问题创建开始日期'} />
        <input type="date" value={end} onChange={event => setEnd(event.target.value)} title={view === 'sessions' ? '会话创建结束日期' : '问题创建结束日期'} />
        <input value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索标题或摘要" disabled={view === 'sessions'} />
      </section>

      <div className="admin-feedback__tabs">
        <button className={view === 'issues' ? 'is-active' : ''} onClick={() => setView('issues')}>全局问题池</button>
        <button className={view === 'sessions' ? 'is-active' : ''} onClick={() => setView('sessions')}>原始对话</button>
      </div>

      {error && <div className="admin-feedback__error">{error}</div>}

      <main className="admin-feedback__workspace">
        <div className="admin-feedback__list">
          {loading && <div className="admin-feedback__empty">加载中...</div>}
          {!loading && view === 'issues' && issues.map(issue => (
            <button key={issue.id} className={selectedIssue?.id === issue.id ? 'is-active' : ''} onClick={() => setSelectedIssue(issue)}>
              <div><span className={`tone-${issue.severity}`}>{categoryLabels[issue.category] || issue.category}</span><time>{formatTime(issue.updated_at)}</time></div>
              <strong>{issue.title}</strong>
              <p>{issue.reporter_username} · {statusLabels[issue.status] || issue.status} · {scopeLabels[issue.change_scope] || issue.change_scope}</p>
            </button>
          ))}
          {!loading && view === 'sessions' && sessions.map(session => (
            <button key={session.id} className={selectedSession?.id === session.id ? 'is-active' : ''} onClick={() => void openSession(session)}>
              <div><span><FaComments /> {session.username}</span><time title="医生最后反馈时间">医生最后反馈 {formatTime(session.last_user_message_at)}</time></div>
              <strong>{session.title}</strong>
              <p>创建于 {formatTime(session.created_at)}</p>
            </button>
          ))}
          {!loading && ((view === 'issues' && !issues.length) || (view === 'sessions' && !sessions.length)) && (
            <div className="admin-feedback__empty">当前筛选条件下没有记录</div>
          )}
        </div>

        <section className="admin-feedback__detail">
          {view === 'issues' && selectedIssue && (
            <>
              <div className="admin-feedback__detail-head">
                <div><span>#{selectedIssue.id} · {selectedIssue.reporter_username}</span><h2>{selectedIssue.title}</h2></div>
                {readOnly ? (
                  <div className="admin-feedback__issue-state">{statusLabels[selectedIssue.status] || selectedIssue.status}</div>
                ) : (
                  <div>
                    <select value={selectedIssue.severity} onChange={event => void updateIssue({ severity: event.target.value })} disabled={saving}>
                      <option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="critical">紧急</option>
                    </select>
                    <select value={selectedIssue.status} onChange={event => void updateIssue({ status: event.target.value })} disabled={saving}>
                      {Object.entries(statusLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                    </select>
                  </div>
                )}
              </div>
              {!editingIssue ? (
                <>
                  <dl className="admin-feedback__fields">
                    <dt>类型 / 范围</dt><dd>{categoryLabels[selectedIssue.category] || selectedIssue.category} · {scopeLabels[selectedIssue.change_scope] || selectedIssue.change_scope}</dd>
                    <dt>发生页面</dt><dd>{selectedIssue.page || '待补充'}</dd>
                    <dt>问题摘要</dt><dd>{selectedIssue.summary || '待补充'}</dd>
                    <dt>触发操作</dt><dd>{selectedIssue.operation || '待补充'}</dd>
                    <dt>实际表现</dt><dd>{selectedIssue.actual_behavior || '待补充'}</dd>
                    <dt>期望表现</dt><dd>{selectedIssue.expected_behavior || '待补充'}</dd>
                    <dt>影响</dt><dd>{selectedIssue.impact || '待补充'}</dd>
                    <dt>验收标准</dt><dd>{selectedIssue.acceptance_criteria || '待补充'}</dd>
                  </dl>
                  {canOperatePlans && <button className="admin-feedback__edit-issue" onClick={beginIssueEdit}>修正问题单范围</button>}
                </>
              ) : (
                <section className="admin-feedback__issue-editor">
                  <div><label>问题标题<input value={issueDraft.title || ''} onChange={event => setIssueDraft(current => ({ ...current, title: event.target.value }))} /></label><label>发生页面<input value={issueDraft.page || ''} onChange={event => setIssueDraft(current => ({ ...current, page: event.target.value }))} /></label></div>
                  <label>问题摘要<textarea rows={3} value={issueDraft.summary || ''} onChange={event => setIssueDraft(current => ({ ...current, summary: event.target.value }))} /></label>
                  <label>实际表现<textarea rows={3} value={issueDraft.actual_behavior || ''} onChange={event => setIssueDraft(current => ({ ...current, actual_behavior: event.target.value }))} /></label>
                  <label>期望表现<textarea rows={3} value={issueDraft.expected_behavior || ''} onChange={event => setIssueDraft(current => ({ ...current, expected_behavior: event.target.value }))} /></label>
                  <label>验收标准<textarea rows={3} value={issueDraft.acceptance_criteria || ''} onChange={event => setIssueDraft(current => ({ ...current, acceptance_criteria: event.target.value }))} /></label>
                  <div className="admin-feedback__editor-actions"><button onClick={() => void saveIssueDraft()} disabled={saving}>保存问题单</button><button className="is-secondary" onClick={() => setEditingIssue(false)} disabled={saving}>取消</button></div>
                </section>
              )}
              <section className="admin-feedback__work-plan">
                <div className="admin-feedback__work-plan-head">
                  <div><FaClipboardCheck /><strong>仓库调查、方案与执行控制</strong></div>
                  {workPlan
                    ? <span className={`is-${workPlan.status}`}>{workPlanStatusLabels[workPlan.status] || workPlan.status}</span>
                    : codexInvestigation && <span className={`is-${codexInvestigation.status}`}>{codexInvestigationStatusLabels[codexInvestigation.status] || codexInvestigation.status}</span>}
                </div>
                <section className="admin-feedback__plan-chat">
                  <div className="admin-feedback__plan-chat-head">
                    <div><FaComments /><strong>方案协作对话</strong></div>
                    <span>Codex 会带着前几轮结论继续核对真实仓库</span>
                  </div>
                  {!displayedInvestigationHistory.length && (
                    <p className="admin-feedback__plan-chat-empty">还没有调查记录。你可以直接说明希望 Codex 重点核对什么，也可以留空开始第一轮只读调查。</p>
                  )}
                  <div className="admin-feedback__plan-chat-turns">
                    {displayedInvestigationHistory.map((run, index) => (
                      <React.Fragment key={run.id}>
                        {run.revision_note && (
                          <article className="admin-feedback__plan-chat-message is-user">
                            <header><strong>你</strong><span>第 {index + 1} 轮 · {formatTime(run.created_at)}</span></header>
                            <p>{run.revision_note}</p>
                          </article>
                        )}
                        <article className={`admin-feedback__plan-chat-message is-codex is-${run.status}`}>
                          <header><strong>受控 Codex</strong><span>{codexInvestigationStatusLabels[run.status] || run.status} · #{run.id}</span></header>
                          {['pending', 'running'].includes(run.status) ? (
                            <p>{run.status === 'pending' ? '正在等待调查资源…' : '正在读取仓库并核对这一轮意见，完成后页面会自动更新。'}</p>
                          ) : run.status === 'failed' ? (
                            <p>{run.error_message || '本轮调查未完成，可以直接再次发送意见重试。'}</p>
                          ) : (
                            <>
                              <p>{run.result?.investigation_summary || '本轮调查已完成，最新结构化方案见下方。'}</p>
                              {run.result?.implementation_size && <small className="admin-feedback__plan-chat-size">实现量：{implementationSizeLabels[run.result.implementation_size] || run.result.implementation_size}</small>}
                              {(run.result?.root_cause || run.result?.recommended_changes?.length || run.result?.clarifying_question) && (
                                <details>
                                  <summary>查看本轮依据与变化</summary>
                                  {run.result?.root_cause && <p><strong>根因判断：</strong>{run.result.root_cause}</p>}
                                  {!!run.result?.recommended_changes?.length && <ul>{run.result.recommended_changes.map((item, changeIndex) => <li key={`${run.id}-${item.path}-${changeIndex}`}><code>{item.path}</code>：{item.change}</li>)}</ul>}
                                  {run.result?.clarifying_question && <p><strong>仍需确认：</strong>{run.result.clarifying_question}</p>}
                                </details>
                              )}
                            </>
                          )}
                        </article>
                      </React.Fragment>
                    ))}
                  </div>
                  {canOperatePlans && (!workPlan || workPlan.status === 'draft') && (
                    <div className="admin-feedback__plan-chat-composer">
                      <label>继续告诉 Codex 你的判断或限制
                        <textarea rows={3} value={revisionNote} onChange={event => setRevisionNote(event.target.value)} placeholder="例如：先不要改 importer，只处理补打标签后的前端状态刷新；请说明这样是否足以解决 Function SAX 和 Tissue LGE。" />
                      </label>
                      <div>
                        <small>这条消息会和前几轮调查结论一起送给 Codex，不会写进医生的原始对话。</small>
                        <button onClick={() => void generateWorkPlan()} disabled={planning || investigationActive || (!!displayedInvestigationHistory.length && !revisionNote.trim())}>
                          {investigationActive ? '调查进行中…' : planning ? '正在发送…' : displayedInvestigationHistory.length ? '发送并继续调查' : '开始只读调查'}
                        </button>
                      </div>
                    </div>
                  )}
                  {workPlan && workPlan.status !== 'draft' && <p className="admin-feedback__plan-chat-locked">方案已批准。若要继续讨论，需要先明确退回草案，避免已批准内容在执行前被悄悄改变。</p>}
                </section>
                {workPlan && (
                  <div className="admin-feedback__work-plan-content">
                    {editingPlan ? (
                      <section className="admin-feedback__plan-editor">
                        <label>方案摘要<textarea rows={4} value={planDraft.solution_summary || ''} onChange={event => setPlanDraft(current => ({ ...current, solution_summary: event.target.value }))} /></label>
                        <label>根因判断<textarea rows={4} value={planDraft.root_cause || ''} onChange={event => setPlanDraft(current => ({ ...current, root_cause: event.target.value }))} /></label>
                        <label>建议处理（每行一步）<textarea rows={5} value={(planDraft.implementation_steps || []).join('\n')} onChange={event => setPlanDraft(current => ({ ...current, implementation_steps: event.target.value.split('\n').filter(Boolean) }))} /></label>
                        <label>允许 Codex 修改的文件（每行一个仓库相对路径）<textarea rows={4} value={(planDraft.allowed_paths || []).join('\n')} onChange={event => setPlanDraft(current => ({ ...current, allowed_paths: event.target.value.split('\n').map(item => item.trim()).filter(Boolean) }))} /></label>
                        <label>风险与控制（每行：等级 | 风险 | 缓解方式）<textarea rows={5} value={formatRisks(planDraft.risks)} onChange={event => setPlanDraft(current => ({ ...current, risks: parseRisks(event.target.value) }))} /></label>
                        <label>验证方式（每行一步）<textarea rows={4} value={(planDraft.verification_steps || []).join('\n')} onChange={event => setPlanDraft(current => ({ ...current, verification_steps: event.target.value.split('\n').filter(Boolean) }))} /></label>
                        <label>Codex 执行任务书<textarea rows={7} value={planDraft.codex_brief || ''} onChange={event => setPlanDraft(current => ({ ...current, codex_brief: event.target.value }))} /></label>
                        <div className="admin-feedback__editor-actions"><button onClick={() => void savePlanDraft()} disabled={planning}>保存方案</button><button className="is-secondary" onClick={() => setEditingPlan(false)} disabled={planning}>取消</button></div>
                      </section>
                    ) : (
                    <>
                    <div className="admin-feedback__plan-verdict">
                      <span>当前结论</span>
                      <p>{planSummary || '暂无方案摘要。'}</p>
                      <div>
                        <span>置信度：{confidenceLabels[workPlan.proposal.confidence || 'low'] || '待确认'}</span>
                        <span>实现量：{implementationSizeLabels[workPlan.proposal.implementation_size || ''] || '待重新评估'}</span>
                        <span>门禁：{scopeLabels[workPlan.proposal.execution_scope || 'needs_review'] || '执行前需审查'}</span>
                        <span>{reproducibilityLabels[workPlan.proposal.reproducibility || 'production_data_required']}</span>
                      </div>
                    </div>
                    <div className="admin-feedback__root-cause"><strong>为什么会发生</strong><p>{planRootCause}</p></div>
                    {workPlan.proposal.clarifying_question && <div className="admin-feedback__plan-question"><strong>需要你确认</strong><p>{workPlan.proposal.clarifying_question}</p></div>}
                    <details className="admin-feedback__plan-technical">
                      <summary>查看代码证据与冻结的文件范围</summary>
                    <div className="admin-feedback__allowed-paths">
                      <h3>冻结的可写文件范围</h3>
                      {(workPlan.proposal.allowed_paths || []).length
                        ? <ul>{workPlan.proposal.allowed_paths?.map(path => <li key={path}><code>{path}</code></li>)}</ul>
                        : <p>尚未冻结文件范围；该方案不能进入受控执行，请重新调查。</p>}
                    </div>
                    {!!workPlan.proposal.repository_evidence?.length && (
                      <div className="admin-feedback__repository-evidence">
                        <div>
                          <h3>真实仓库证据</h3>
                          <span>置信度 {workPlan.proposal.confidence || '待确认'} · 基线 {(workPlan.proposal.base_sha || '').slice(0, 12) || '未知'}{workPlan.proposal.dirty_worktree ? ' · 含未提交改动' : ''}</span>
                        </div>
                        <ul>
                          {workPlan.proposal.repository_evidence.map((item, index) => (
                            <li key={`${item.path}-${item.line_start}-${index}`}><code>{item.path}:{item.line_start}</code><span>{item.reason}</span></li>
                          ))}
                        </ul>
                        <p><strong>复现边界：</strong>{workPlan.proposal.reproducibility === 'code_only' ? '仅凭代码即可判断' : workPlan.proposal.reproducibility === 'demo_cases' ? '可用 2–5 个 demo case 复现' : '需要生产数据或运行证据'}{workPlan.proposal.data_requirements ? ` · ${workPlan.proposal.data_requirements}` : ''}</p>
                      </div>
                    )}
                    </details>
                    <div className="admin-feedback__plan-columns">
                      <div>
                        <h3>准备怎么改</h3>
                        <ol className="admin-feedback__compact-steps">{planSteps.slice(0, 4).map((step, index) => <li key={`${step.path}-${step.change}-${index}`}><span>{step.change}</span>{step.path && <code>{step.path}</code>}</li>)}</ol>
                        {planSteps.length > 4 && <p className="admin-feedback__more-count">另有 {planSteps.length - 4} 项技术改动，已收进详细清单。</p>}
                      </div>
                      <div>
                        <h3><FaExclamationTriangle /> 需要注意的风险</h3>
                        {planRisks.slice(0, 3).map((risk, index) => (
                          <div className="admin-feedback__risk" key={`${risk.risk}-${index}`}>
                            <strong>{riskLevelLabels[risk.level || 'medium'] || '中'}</strong><span>{risk.risk || '待补充风险'}</span><small>{risk.mitigation || '需人工确认缓解方式'}</small>
                          </div>
                        ))}
                        {planRisks.length > 3 && <p className="admin-feedback__more-count">其余 {planRisks.length - 3} 项风险在详细清单中。</p>}
                      </div>
                    </div>
                    <details className="admin-feedback__plan-technical">
                      <summary>查看完整改动、风险、验证步骤与 Codex 任务书</summary>
                      <div className="admin-feedback__verification">
                        <h3>完整改动清单</h3>
                        <ol>{planSteps.map((step, index) => <li key={`full-${step.path}-${index}`}>{step.path && <code>{step.path}</code>}{step.path ? '：' : ''}{step.change}</li>)}</ol>
                      </div>
                      <div className="admin-feedback__verification">
                        <h3>完整风险清单</h3>
                        {planRisks.map((risk, index) => <div className="admin-feedback__risk" key={`full-${risk.risk}-${index}`}><strong>{riskLevelLabels[risk.level || 'medium'] || '中'}</strong><span>{risk.risk || '待补充风险'}</span><small>{risk.mitigation || '需人工确认缓解方式'}</small></div>)}
                      </div>
                      <div className="admin-feedback__verification">
                        <h3>验证方式</h3>
                        <ul>{(workPlan.proposal.verification_steps || []).map((step, index) => <li key={`${step}-${index}`}>{step}</li>)}</ul>
                      </div>
                      <div className="admin-feedback__codex-brief">
                        <div><h3>Codex 执行任务书</h3><button onClick={() => void copyCodexBrief()} title="复制任务书"><FaCopy /> 复制</button></div>
                        <pre>{workPlan.proposal.codex_brief}</pre>
                      </div>
                    </details>
                    <div className="admin-feedback__work-plan-actions">
                      {canOperatePlans && workPlan.status === 'draft' && <button onClick={() => void approveWorkPlan()} disabled={planning}><FaClipboardCheck /> 确认方案</button>}
                      {canControlExecution && executionCapability && workPlan.status === 'approved' && <button onClick={() => void queueWorkPlan()} disabled={planning}><FaPlay /> 启动受控 Codex</button>}
                      {canControlExecution && executionCapability && workPlan.status === 'queued' && !executionRun && <button onClick={() => void queueWorkPlan()} disabled={planning}><FaPlay /> 接入受控执行</button>}
                      {canControlExecution && executionCapability && workPlan.status === 'queued' && executionRun && ['failed', 'stopped'].includes(executionRun.status) && <button onClick={() => void queueWorkPlan()} disabled={planning}><FaPlay /> 重新执行</button>}
                      {canOperatePlans && workPlan.status === 'draft' && <button className="is-secondary" onClick={beginPlanEdit} disabled={planning}>高级结构化编辑</button>}
                      {workPlan.status === 'queued' && !executionRun && <span>这是旧版占位队列记录；管理员可在代码基线干净后启动受控执行。</span>}
                      {canControlExecution && !executionCapability && <span>受控执行后端尚未激活；当前按钮已安全隐藏。</span>}
                    </div>
                    {!executionRun && ['draft', 'approved'].includes(workPlan.status) && (
                      <p className="admin-feedback__execution-location-hint">确认方案并启动受控 Codex 后，实时记录、代码改动、测试结果和人工审查四个标签会直接出现在本方案下方，不需要登录服务器查文件。</p>
                    )}
                    {executionRun && (
                      <section className="admin-feedback__execution">
                        <div className="admin-feedback__execution-head">
                          <div>
                            <strong>受控执行 #{executionRun.id}</strong>
                            <span>{executionStatusLabels[executionRun.status] || executionRun.status} · {executionRun.phase}</span>
                          </div>
                          <div>
                            <code>base {executionRun.base_sha.slice(0, 12)}</code>
                            {executionRun.candidate_sha && <code>candidate {executionRun.candidate_sha.slice(0, 12)}</code>}
                          </div>
                        </div>
                        <dl className="admin-feedback__execution-meta">
                          <dt>目标分支</dt><dd>{executionRun.target_branch}</dd>
                          <dt>改动文件</dt><dd>{executionRun.changed_file_count || 0}</dd>
                          <dt>固定验证</dt><dd>{executionRun.tests_passed == null ? '尚未完成' : executionRun.tests_passed ? '全部通过' : '未通过'}</dd>
                          <dt>更新时间</dt><dd>{formatTime(executionRun.updated_at)}</dd>
                          {executionRun.artifact_dir && <><dt>审计目录</dt><dd><code>{executionRun.artifact_dir}</code></dd></>}
                          {executionRun.worktree_path && <><dt>独立工作树</dt><dd><code>{executionRun.worktree_path}</code></dd></>}
                        </dl>
                        {executionRun.error_message && <div className="admin-feedback__execution-error">{executionRun.error_message}</div>}
                        <div className="admin-feedback__execution-tabs">
                          <button className={executionTab === 'events' ? 'is-active' : ''} onClick={() => setExecutionTab('events')}>实时记录</button>
                          <button className={executionTab === 'diff' ? 'is-active' : ''} onClick={() => setExecutionTab('diff')}>代码改动</button>
                          <button className={executionTab === 'tests' ? 'is-active' : ''} onClick={() => setExecutionTab('tests')}>测试结果</button>
                          <button className={executionTab === 'review' ? 'is-active' : ''} onClick={() => setExecutionTab('review')}>人工审查</button>
                        </div>
                        {executionTab === 'events' && <div className="admin-feedback__execution-log"><pre>{executionEvents || '等待执行事件…'}</pre>{executionSummary && <><h4>Codex 总结</h4><pre>{executionSummary}</pre></>}</div>}
                        {executionTab === 'diff' && <div className="admin-feedback__execution-log"><pre>{executionDiff.stat || '候选改动尚未生成。'}</pre><pre>{executionDiff.unified_diff}</pre></div>}
                        {executionTab === 'tests' && <div className="admin-feedback__execution-tests">
                          {(executionRun.tests?.commands || []).map(test => <div key={test.id} className={test.passed ? 'is-passed' : 'is-failed'}><strong>{test.passed ? '通过' : '失败'} · {test.id}</strong><code>{(test.command || []).join(' ')}</code>{test.error && <span>{test.error}</span>}</div>)}
                          {!(executionRun.tests?.commands || []).length && <p>固定验证尚未运行。</p>}
                        </div>}
                        {executionTab === 'review' && <div className="admin-feedback__execution-review">
                          <label>审查备注<textarea rows={3} value={reviewNote} onChange={event => setReviewNote(event.target.value)} placeholder="记录批准依据，或填写拒绝原因。" /></label>
                          {executionRun.reviewed_by && <p>上次审查：{executionRun.reviewed_by} · {formatTime(executionRun.reviewed_at)}{executionRun.review_note ? ` · ${executionRun.review_note}` : ''}</p>}
                          <p>批准实际代码改动与批准解决方案是两次独立确认；合并后仍不会发布。</p>
                        </div>}
                        {canControlExecution && <div className="admin-feedback__execution-actions">
                          {['queued', 'preparing', 'running'].includes(executionRun.status) && <button className="is-danger" onClick={() => void stopExecution()} disabled={planning}>停止执行</button>}
                          {executionRun.status === 'review_ready' && <button onClick={() => void approveExecution()} disabled={planning || executionRun.tests_passed !== true}>批准实际改动</button>}
                          {['review_ready', 'review_approved'].includes(executionRun.status) && <button className="is-danger" onClick={() => void rejectExecution()} disabled={planning || !reviewNote.trim()}>拒绝改动</button>}
                          {['failed', 'stopped'].includes(executionRun.status) && <button className="is-secondary" onClick={() => void reviseExecutionPlan()} disabled={planning}>退回方案修订</button>}
                          {executionRun.status === 'review_approved' && <button onClick={mergeExecution} disabled={planning || executionRun.tests_passed !== true || !executionRun.candidate_sha}>合并候选提交</button>}
                        </div>}
                      </section>
                    )}
                    </>
                    )}
                  </div>
                )}
              </section>
              {!readOnly && (
                <label className="admin-feedback__note">
                  管理员备注
                  <textarea
                    value={selectedIssue.admin_note || ''}
                    onChange={event => setSelectedIssue({ ...selectedIssue, admin_note: event.target.value })}
                    onBlur={() => void updateIssue({ admin_note: selectedIssue.admin_note })}
                    rows={5}
                    placeholder="记录复现、分派、风险和后续确认"
                  />
                </label>
              )}
              <button className="admin-feedback__conversation-link" onClick={() => { setView('sessions'); void openSessionById(selectedIssue.session_id); }}>
                查看来源对话
              </button>
            </>
          )}
          {view === 'sessions' && selectedSession && (
            <>
              <div className="admin-feedback__detail-head"><div><span>{selectedSession.username}</span><h2>{selectedSession.title}</h2></div></div>
              <div className="admin-feedback__transcript">
                {messages.map(message => (
                  <article key={message.id} className={`is-${message.role}`}>
                    <div><strong>{message.role === 'assistant' ? '工作站专家' : selectedSession.username}</strong><time>{formatTime(message.created_at)}</time></div>
                    <div className="admin-feedback__markdown"><ReactMarkdown>{message.content}</ReactMarkdown></div>
                    {!!message.attachments?.length && (
                      <div className="admin-feedback__attachments">
                        {message.attachments.map(attachment => (
                          <a key={attachment.id} href={attachment.url} target="_blank" rel="noreferrer" title="查看原图">
                            <img src={attachment.url} alt="医生反馈截图" />
                          </a>
                        ))}
                      </div>
                    )}
                    {message.role === 'assistant' && <small>{message.rating ? `评价：${message.rating === 'helpful' ? '有帮助' : '没解决'}` : '未评价'}{message.latency_ms ? ` · ${message.latency_ms} ms` : ''}</small>}
                  </article>
                ))}
                {!messages.length && <div className="admin-feedback__empty">请选择一条对话查看</div>}
              </div>
            </>
          )}
          {((view === 'issues' && !selectedIssue) || (view === 'sessions' && !selectedSession)) && <div className="admin-feedback__empty">从左侧选择记录</div>}
        </section>
      </main>
      </main>
    </div>
  );
};

export default AdminFeedbackPage;
