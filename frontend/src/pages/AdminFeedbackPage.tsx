import React, { useCallback, useEffect, useMemo, useState } from 'react';
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
    implementation_steps?: string[];
    risks?: { level?: string; risk?: string; mitigation?: string }[];
    verification_steps?: string[];
    execution_scope?: string;
    codex_brief?: string;
  };
  generated_by?: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
  queue_note?: string;
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
  needs_review: '需人工评估',
  large_change: '较大改动',
};

const workPlanStatusLabels: Record<string, string> = {
  draft: '待确认方案',
  approved: '已批准',
  queued: '等待执行器',
  verified: '已验证',
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
  const isDedicatedDashboard = location.pathname === '/feedback-dashboard';
  const [view, setView] = useState<'issues' | 'sessions'>('issues');
  const [overview, setOverview] = useState<FeedbackOverview | null>(null);
  const [issues, setIssues] = useState<FeedbackIssue[]>([]);
  const [sessions, setSessions] = useState<FeedbackSession[]>([]);
  const [selectedIssue, setSelectedIssue] = useState<FeedbackIssue | null>(null);
  const [selectedSession, setSelectedSession] = useState<FeedbackSession | null>(null);
  const [messages, setMessages] = useState<FeedbackMessage[]>([]);
  const [workPlan, setWorkPlan] = useState<FeedbackWorkPlan | null>(null);
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
      setWorkPlan(payload.work_plan || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载方案失败');
    }
  }, []);

  useEffect(() => {
    if (!selectedIssue) {
      setWorkPlan(null);
      setEditingIssue(false);
      setEditingPlan(false);
      return;
    }
    setEditingIssue(false);
    setEditingPlan(false);
    setIssueDraft({});
    void loadWorkPlan(selectedIssue.id);
  }, [loadWorkPlan, selectedIssue?.id]);

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
      setWorkPlan(payload.work_plan);
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
    if (!window.confirm('确认将此方案放入 Codex 执行队列？当前不会直接修改服务器。')) return;
    setPlanning(true);
    setError('');
    try {
      const response = await fetch(`/api/admin/feedback/issues/${selectedIssue.id}/work-plan/queue`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
      const payload = await readJson(response);
      setWorkPlan(payload.work_plan);
    } catch (err) {
      setError(err instanceof Error ? err.message : '进入执行队列失败');
    } finally {
      setPlanning(false);
    }
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
      implementation_steps: [...(workPlan.proposal.implementation_steps || [])],
      risks: [...(workPlan.proposal.risks || [])],
      verification_steps: [...(workPlan.proposal.verification_steps || [])],
      execution_scope: workPlan.proposal.execution_scope || 'needs_review',
      codex_brief: workPlan.proposal.codex_brief || '',
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
          <span>按账号留存，对话与问题单分层管理</span>
        </div>
        <span>{readOnly ? '可审方案、确认队列；不能修改系统权限' : '可管理：状态、优先级与内部备注'}</span>
      </section>

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
        <input type="date" value={start} onChange={event => setStart(event.target.value)} title="开始日期" />
        <input type="date" value={end} onChange={event => setEnd(event.target.value)} title="结束日期" />
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
              <div><span><FaComments /> {session.username}</span><time>{formatTime(session.last_message_at)}</time></div>
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
                  <div><FaClipboardCheck /><strong>解决方案与执行控制</strong></div>
                  {workPlan && <span className={`is-${workPlan.status}`}>{workPlanStatusLabels[workPlan.status] || workPlan.status}</span>}
                </div>
                {!workPlan && (
                  <div className="admin-feedback__work-plan-empty">
                    <p>尚未生成方案。系统会基于问题单输出处理建议、风险、验证方法和 Codex 任务书。</p>
                    {canOperatePlans && <label className="admin-feedback__revision-note">生成说明（可选）<textarea rows={2} value={revisionNote} onChange={event => setRevisionNote(event.target.value)} placeholder="例如：目标是实验结果页，不是 AI 专家侧栏；请按此重新理解。" /></label>}
                    {canOperatePlans && <button onClick={() => void generateWorkPlan()} disabled={planning}>{planning ? '正在生成...' : '生成解决方案'}</button>}
                  </div>
                )}
                {workPlan && (
                  <div className="admin-feedback__work-plan-content">
                    {editingPlan ? (
                      <section className="admin-feedback__plan-editor">
                        <label>方案摘要<textarea rows={4} value={planDraft.solution_summary || ''} onChange={event => setPlanDraft(current => ({ ...current, solution_summary: event.target.value }))} /></label>
                        <label>建议处理（每行一步）<textarea rows={5} value={(planDraft.implementation_steps || []).join('\n')} onChange={event => setPlanDraft(current => ({ ...current, implementation_steps: event.target.value.split('\n').filter(Boolean) }))} /></label>
                        <label>风险与控制（每行：等级 | 风险 | 缓解方式）<textarea rows={5} value={formatRisks(planDraft.risks)} onChange={event => setPlanDraft(current => ({ ...current, risks: parseRisks(event.target.value) }))} /></label>
                        <label>验证方式（每行一步）<textarea rows={4} value={(planDraft.verification_steps || []).join('\n')} onChange={event => setPlanDraft(current => ({ ...current, verification_steps: event.target.value.split('\n').filter(Boolean) }))} /></label>
                        <label>Codex 执行任务书<textarea rows={7} value={planDraft.codex_brief || ''} onChange={event => setPlanDraft(current => ({ ...current, codex_brief: event.target.value }))} /></label>
                        <div className="admin-feedback__editor-actions"><button onClick={() => void savePlanDraft()} disabled={planning}>保存方案</button><button className="is-secondary" onClick={() => setEditingPlan(false)} disabled={planning}>取消</button></div>
                      </section>
                    ) : (
                    <>
                    <p className="admin-feedback__solution-summary">{workPlan.proposal.solution_summary || '暂无方案摘要。'}</p>
                    <div className="admin-feedback__plan-columns">
                      <div>
                        <h3>建议处理</h3>
                        <ol>{(workPlan.proposal.implementation_steps || []).map((step, index) => <li key={`${step}-${index}`}>{step}</li>)}</ol>
                      </div>
                      <div>
                        <h3><FaExclamationTriangle /> 风险与控制</h3>
                        {(workPlan.proposal.risks || []).map((risk, index) => (
                          <div className="admin-feedback__risk" key={`${risk.risk}-${index}`}>
                            <strong>{risk.level || 'medium'}</strong><span>{risk.risk || '待补充风险'}</span><small>{risk.mitigation || '需人工确认缓解方式'}</small>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div className="admin-feedback__verification">
                      <h3>验证方式</h3>
                      <ul>{(workPlan.proposal.verification_steps || []).map((step, index) => <li key={`${step}-${index}`}>{step}</li>)}</ul>
                    </div>
                    <div className="admin-feedback__codex-brief">
                      <div><h3>Codex 执行任务书</h3><button onClick={() => void copyCodexBrief()} title="复制任务书"><FaCopy /> 复制</button></div>
                      <pre>{workPlan.proposal.codex_brief}</pre>
                    </div>
                    <div className="admin-feedback__work-plan-actions">
                      {canOperatePlans && workPlan.status === 'draft' && <button onClick={() => void approveWorkPlan()} disabled={planning}><FaClipboardCheck /> 确认方案</button>}
                      {canOperatePlans && workPlan.status === 'approved' && <button onClick={() => void queueWorkPlan()} disabled={planning}><FaPlay /> 进入 Codex 执行队列</button>}
                      {canOperatePlans && workPlan.status === 'draft' && <button className="is-secondary" onClick={beginPlanEdit} disabled={planning}>编辑方案</button>}
                      {canOperatePlans && workPlan.status !== 'queued' && <button className="is-secondary" onClick={() => void generateWorkPlan()} disabled={planning}>{planning ? '正在生成...' : '重新生成'}</button>}
                      {workPlan.status === 'queued' && <span>已批准，等待受控 Codex 执行器接入；不会直接修改服务器。</span>}
                    </div>
                    {canOperatePlans && workPlan.status === 'draft' && <label className="admin-feedback__revision-note">要求 AI 重新生成时的修订说明<textarea rows={2} value={revisionNote} onChange={event => setRevisionNote(event.target.value)} placeholder="指出方案误解的范围、遗漏的风险或希望采用的方向。" /></label>}
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
