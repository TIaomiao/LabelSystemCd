import React, { useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import {
  FaArrowUp,
  FaCheck,
  FaHistory,
  FaPaperclip,
  FaPlus,
  FaRegThumbsDown,
  FaRegThumbsUp,
  FaTimes,
} from 'react-icons/fa';
import './FeedbackAssistantPanel.css';

export interface FeedbackPageContext {
  module: string;
  module_label: string;
  dataset?: string;
  source?: string;
  case_catalog_id?: number;
  study_id?: number;
  workstation_path?: string;
}

interface FeedbackSession {
  id: number;
  title: string;
  last_message_at?: string | null;
}

interface FeedbackMessage {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  rating?: 'helpful' | 'unhelpful' | null;
  created_at?: string | null;
  pending?: boolean;
  attachments?: FeedbackAttachment[];
}

interface FeedbackAttachment {
  id: number;
  original_name: string;
  mime_type: string;
  size_bytes: number;
  width: number;
  height: number;
  url: string;
}

interface FeedbackIssue {
  id: number;
  title: string;
  category: string;
  status: string;
}

interface Props {
  pageContext: FeedbackPageContext;
  onClose: () => void;
}

const quickActions = [
  { key: 'usage_help', label: '功能怎么用', seed: '我想在当前页面完成一个操作，请告诉我应该从哪里开始。' },
  { key: 'bug', label: '报告问题', seed: '我在当前页面遇到了问题：' },
  { key: 'feature_request', label: '功能建议', seed: '我希望工作站可以支持：' },
  { key: 'data_issue', label: '数据异常', seed: '我发现当前病例或序列的数据有异常：' },
  { key: 'ai_experience', label: 'AI 使用体验', seed: '我想反馈一次 AI 功能的使用体验：' },
] as const;

const readJson = async (response: Response) => {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || '请求失败，请稍后重试');
  return payload;
};

const FeedbackAssistantPanel: React.FC<Props> = ({ pageContext, onClose }) => {
  const [sessions, setSessions] = useState<FeedbackSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  const [messages, setMessages] = useState<FeedbackMessage[]>([]);
  const [issues, setIssues] = useState<FeedbackIssue[]>([]);
  const [input, setInput] = useState('');
  const [categoryHint, setCategoryHint] = useState('');
  const [reasoningLevel, setReasoningLevel] = useState<'medium' | 'high'>('medium');
  const [pendingAttachments, setPendingAttachments] = useState<FeedbackAttachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const messageEndRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const createSession = useCallback(async () => {
    const response = await fetch('/api/feedback/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ page_context: pageContext }),
    });
    const payload = await readJson(response);
    const next = payload.session as FeedbackSession;
    setSessions(current => [next, ...current.filter(item => item.id !== next.id)]);
    setActiveSessionId(next.id);
    setMessages([]);
    setIssues([]);
    setCategoryHint('');
    setInput('');
    setPendingAttachments([]);
    return next;
  }, [pageContext]);

  const loadMessages = useCallback(async (sessionId: number) => {
    setError('');
    const response = await fetch(`/api/feedback/sessions/${sessionId}/messages`);
    const payload = await readJson(response);
    setMessages(payload.messages || []);
    setIssues(payload.issues || []);
  }, []);

  useEffect(() => {
    let active = true;
    const load = async () => {
      setLoading(true);
      setError('');
      try {
        const response = await fetch('/api/feedback/sessions');
        const payload = await readJson(response);
        if (!active) return;
        const nextSessions = (payload.sessions || []) as FeedbackSession[];
        setSessions(nextSessions);
        if (nextSessions.length) {
          setActiveSessionId(nextSessions[0].id);
          await loadMessages(nextSessions[0].id);
        } else {
          await createSession();
        }
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : '加载对话失败');
      } finally {
        if (active) setLoading(false);
      }
    };
    void load();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, sending]);

  const switchSession = async (sessionId: number) => {
    await discardPendingAttachments();
    setActiveSessionId(sessionId);
    setLoading(true);
    try {
      await loadMessages(sessionId);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载对话失败');
    } finally {
      setLoading(false);
    }
  };

  const discardPendingAttachments = async () => {
    const current = pendingAttachments;
    setPendingAttachments([]);
    await Promise.all(current.map(item =>
      fetch(item.url, { method: 'DELETE' }).catch(() => undefined)
    ));
  };

  const startNewSession = async () => {
    await discardPendingAttachments();
    await createSession();
  };

  const uploadImage = async (file: File) => {
    if (!file.type.startsWith('image/')) {
      setError('只能添加图片文件');
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      setError('单张截图不能超过 8MB');
      return;
    }
    if (pendingAttachments.length >= 4) {
      setError('每条消息最多添加 4 张截图');
      return;
    }
    setUploading(true);
    setError('');
    try {
      const sessionId = activeSessionId || (await createSession()).id;
      const form = new FormData();
      form.append('file', file, file.name || 'clipboard-screenshot.png');
      const response = await fetch(`/api/feedback/sessions/${sessionId}/attachments`, {
        method: 'POST',
        body: form,
      });
      const payload = await readJson(response);
      setPendingAttachments(current => [...current, payload.attachment]);
    } catch (err) {
      setError(err instanceof Error ? err.message : '截图上传失败');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const removeAttachment = async (attachment: FeedbackAttachment) => {
    setPendingAttachments(current => current.filter(item => item.id !== attachment.id));
    try {
      await fetch(attachment.url, { method: 'DELETE' });
    } catch {
      // The local preview should still disappear if cleanup cannot complete.
    }
  };

  const sendMessage = async () => {
    const content = input.trim() || (pendingAttachments.length ? '请结合截图判断当前问题，并追问我最关键的补充信息。' : '');
    if (!content || sending || uploading) return;
    setError('');
    setSending(true);
    setInput('');
    const optimistic: FeedbackMessage = {
      id: -Date.now(),
      role: 'user',
      content,
      pending: true,
      attachments: pendingAttachments,
    };
    setMessages(current => [...current, optimistic]);
    try {
      const sessionId = activeSessionId || (await createSession()).id;
      const response = await fetch(`/api/feedback/sessions/${sessionId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content,
          reasoning_level: reasoningLevel,
          category_hint: categoryHint,
          page_context: pageContext,
          attachment_ids: pendingAttachments.map(item => item.id),
        }),
      });
      const payload = await readJson(response);
      setMessages(current => [
        ...current.filter(item => item.id !== optimistic.id),
        payload.user_message,
        payload.assistant_message,
      ]);
      if (payload.issue) {
        setIssues(current => [payload.issue, ...current.filter(item => item.id !== payload.issue.id)]);
      }
      setCategoryHint('');
      setPendingAttachments([]);
      setSessions(current => current.map(item =>
        item.id === sessionId ? payload.session : item
      ).sort((left, right) => left.id === sessionId ? -1 : right.id === sessionId ? 1 : 0));
    } catch (err) {
      setMessages(current => current.filter(item => item.id !== optimistic.id));
      setInput(content);
      setError(err instanceof Error ? err.message : '发送失败');
    } finally {
      setSending(false);
    }
  };

  const rateMessage = async (messageId: number, rating: 'helpful' | 'unhelpful') => {
    try {
      const response = await fetch(`/api/feedback/messages/${messageId}/rating`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rating }),
      });
      const payload = await readJson(response);
      setMessages(current => current.map(item => item.id === messageId ? payload.message : item));
      if (payload.issue) {
        setIssues(current => [payload.issue, ...current.filter(item => item.id !== payload.issue.id)]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '反馈失败');
    }
  };

  const selectQuickAction = (action: typeof quickActions[number]) => {
    setCategoryHint(action.key);
    setInput(current => current.trim() ? current : action.seed);
  };

  return (
    <aside className="feedback-assistant" aria-label="工作站 AI 对话">
      <header className="feedback-assistant__header">
        <div>
          <strong>工作站专家</strong>
          <span>对话按账号保存 · 管理员可见</span>
        </div>
        <div className="feedback-assistant__header-actions">
          <button onClick={() => void startNewSession()} title="新建对话" aria-label="新建对话"><FaPlus /></button>
          <button onClick={onClose} title="关闭侧栏" aria-label="关闭侧栏"><FaTimes /></button>
        </div>
      </header>

      <div className="feedback-assistant__controls">
        <label className="feedback-assistant__history">
          <FaHistory />
          <select
            value={activeSessionId ?? ''}
            onChange={event => void switchSession(Number(event.target.value))}
            aria-label="历史对话"
            title={sessions.find(item => item.id === activeSessionId)?.title || '历史对话'}
          >
            {sessions.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
          </select>
        </label>
        <div className="feedback-assistant__reasoning" aria-label="思考深度">
          <button className={reasoningLevel === 'medium' ? 'is-active' : ''} onClick={() => setReasoningLevel('medium')}>专家</button>
          <button className={reasoningLevel === 'high' ? 'is-active' : ''} onClick={() => setReasoningLevel('high')}>超高</button>
        </div>
      </div>

      <div className="feedback-assistant__quick-actions">
        {quickActions.map(action => (
          <button
            key={action.key}
            className={categoryHint === action.key ? 'is-active' : ''}
            onClick={() => selectQuickAction(action)}
          >
            {categoryHint === action.key && <FaCheck />}{action.label}
          </button>
        ))}
      </div>

      <div className="feedback-assistant__messages">
        {loading && <div className="feedback-assistant__state">正在加载对话...</div>}
        {!loading && messages.length === 0 && (
          <div className="feedback-assistant__welcome">
            <strong>你现在想完成什么？</strong>
            <p>可以直接描述医学任务、卡住的操作、异常结果或希望改进的 AI 体验。</p>
          </div>
        )}
        {messages.map(message => (
          <article key={message.id} className={`feedback-message is-${message.role}${message.pending ? ' is-pending' : ''}`}>
            <div className="feedback-message__label">{message.role === 'assistant' ? '工作站专家' : '你'}</div>
            <div className="feedback-message__body">
              {message.role === 'assistant'
                ? <ReactMarkdown>{message.content}</ReactMarkdown>
                : message.content}
            </div>
            {!!message.attachments?.length && (
              <div className="feedback-message__attachments">
                {message.attachments.map(attachment => (
                  <a key={attachment.id} href={attachment.url} target="_blank" rel="noreferrer" title="查看原图">
                    <img src={attachment.url} alt="反馈截图" />
                  </a>
                ))}
              </div>
            )}
            {message.role === 'assistant' && message.id > 0 && (
              <div className="feedback-message__rating">
                <button
                  className={message.rating === 'helpful' ? 'is-active' : ''}
                  onClick={() => void rateMessage(message.id, 'helpful')}
                  title="回答有帮助"
                ><FaRegThumbsUp /></button>
                <button
                  className={message.rating === 'unhelpful' ? 'is-active is-negative' : ''}
                  onClick={() => void rateMessage(message.id, 'unhelpful')}
                  title="没有解决问题"
                ><FaRegThumbsDown /></button>
              </div>
            )}
          </article>
        ))}
        {sending && <div className="feedback-assistant__thinking"><span /><span /><span /></div>}
        <div ref={messageEndRef} />
      </div>

      {issues.length > 0 && (
        <div className="feedback-assistant__issue" title={issues[0].title}>
          <FaCheck /> 已沉淀问题单：{issues[0].title}
        </div>
      )}
      {error && <div className="feedback-assistant__error">{error}</div>}

      <footer className="feedback-assistant__composer">
        {!!pendingAttachments.length && (
          <div className="feedback-assistant__attachment-preview">
            {pendingAttachments.map(attachment => (
              <div key={attachment.id}>
                <img src={attachment.url} alt="待发送截图" />
                <button onClick={() => void removeAttachment(attachment)} title="移除截图" aria-label="移除截图"><FaTimes /></button>
              </div>
            ))}
          </div>
        )}
        <div className="feedback-assistant__privacy-note">可直接粘贴截图；发送前请遮挡患者姓名和身份编号</div>
        <textarea
          value={input}
          onChange={event => setInput(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              void sendMessage();
            }
          }}
          onPaste={event => {
            const images = Array.from(event.clipboardData.files).filter(file => file.type.startsWith('image/'));
            if (!images.length) return;
            event.preventDefault();
            images.slice(0, Math.max(0, 4 - pendingAttachments.length)).forEach(file => void uploadImage(file));
          }}
          placeholder="描述任务或问题，请勿输入患者姓名、身份证号或手机号"
          rows={4}
        />
        <input
          ref={fileInputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          hidden
          onChange={event => {
            const file = event.target.files?.[0];
            if (file) void uploadImage(file);
          }}
        />
        <button
          className="feedback-assistant__attach"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading || pendingAttachments.length >= 4}
          title="添加截图"
          aria-label="添加截图"
        ><FaPaperclip /></button>
        <button
          className="feedback-assistant__send"
          disabled={(!input.trim() && !pendingAttachments.length) || sending || uploading}
          onClick={() => void sendMessage()}
          title="发送"
          aria-label="发送"
        ><FaArrowUp /></button>
      </footer>
    </aside>
  );
};

export default FeedbackAssistantPanel;
