import React, { useEffect, useMemo, useState } from 'react';

interface InboxMessage {
  id: number;
  sender_id?: number | null;
  sender_username?: string | null;
  recipient_id: number;
  recipient_username?: string | null;
  subject: string;
  body: string;
  category?: string;
  is_read: boolean;
  read_at?: string | null;
  created_at?: string | null;
}

const formatTime = (value?: string | null) => {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { hour12: false });
};

const MessagesPage: React.FC = () => {
  const [messages, setMessages] = useState<InboxMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const loadMessages = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/messages?limit=100');
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '加载消息失败');
      const nextMessages: InboxMessage[] = Array.isArray(data.messages) ? data.messages : [];
      setMessages(nextMessages);
      setSelectedId((prev) => prev ?? nextMessages[0]?.id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载消息失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadMessages();
  }, []);

  const selectedMessage = useMemo(
    () => messages.find((item) => item.id === selectedId) || null,
    [messages, selectedId]
  );

  const markRead = async (messageId: number) => {
    const target = messages.find((item) => item.id === messageId);
    if (!target || target.is_read) return;
    try {
      const response = await fetch(`/api/messages/${messageId}/read`, { method: 'POST' });
      const data = await response.json();
      if (!response.ok) return;
      setMessages((prev) => prev.map((item) => (item.id === messageId ? data.message : item)));
    } catch (err) {
      console.error('Failed to mark message read', err);
    }
  };

  return (
    <div style={{ padding: 24, color: 'var(--text-primary)', height: '100%', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', marginBottom: 16 }}>
        <div>
          <h2 style={{ margin: 0 }}>消息中心</h2>
          <div style={{ color: 'var(--text-secondary)', marginTop: 6 }}>查看管理员通知和站内消息。</div>
        </div>
        <button onClick={() => void loadMessages()} style={buttonStyle}>刷新</button>
      </div>
      {error && <div style={{ color: 'var(--error-color)', marginBottom: 16 }}>{error}</div>}
      <div style={shellStyle}>
        <aside style={listStyle}>
          {loading ? (
            <div style={emptyStyle}>加载中...</div>
          ) : messages.length === 0 ? (
            <div style={emptyStyle}>暂无消息</div>
          ) : (
            messages.map((item) => (
              <button
                key={item.id}
                onClick={() => {
                  setSelectedId(item.id);
                  void markRead(item.id);
                }}
                style={{
                  ...rowStyle,
                  backgroundColor: selectedId === item.id ? 'rgba(217, 119, 6, 0.08)' : 'transparent',
                  borderColor: selectedId === item.id ? 'rgba(217, 119, 6, 0.28)' : 'var(--border-color)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                  <strong>{item.subject || '站内消息'}</strong>
                  {!item.is_read ? <span style={dotStyle} /> : null}
                </div>
                <div style={{ color: 'var(--text-secondary)', fontSize: 13, marginTop: 4 }}>
                  来自 {item.sender_username || '系统'}
                </div>
                <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginTop: 6 }}>
                  {formatTime(item.created_at)}
                </div>
              </button>
            ))
          )}
        </aside>
        <section style={detailStyle}>
          {selectedMessage ? (
            <>
              <div style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: 12, marginBottom: 16 }}>
                <h3 style={{ margin: '0 0 8px 0' }}>{selectedMessage.subject || '站内消息'}</h3>
                <div style={{ color: 'var(--text-secondary)', fontSize: 14 }}>
                  来自 {selectedMessage.sender_username || '系统'} · {formatTime(selectedMessage.created_at)}
                </div>
              </div>
              <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>{selectedMessage.body}</div>
            </>
          ) : (
            <div style={emptyStyle}>请选择一条消息</div>
          )}
        </section>
      </div>
    </div>
  );
};

const buttonStyle: React.CSSProperties = {
  padding: '8px 12px',
  borderRadius: 8,
  border: '1px solid var(--border-color)',
  background: 'transparent',
  color: 'var(--text-secondary)',
  cursor: 'pointer',
};

const shellStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'minmax(280px, 360px) minmax(0, 1fr)',
  gap: 16,
  height: 'calc(100% - 72px)',
  minHeight: 520,
};

const listStyle: React.CSSProperties = {
  background: 'var(--bg-secondary)',
  border: '1px solid var(--border-color)',
  borderRadius: 12,
  overflowY: 'auto',
  padding: 12,
  display: 'flex',
  flexDirection: 'column',
  gap: 10,
};

const detailStyle: React.CSSProperties = {
  background: 'var(--bg-secondary)',
  border: '1px solid var(--border-color)',
  borderRadius: 12,
  padding: 20,
  overflowY: 'auto',
};

const rowStyle: React.CSSProperties = {
  width: '100%',
  textAlign: 'left',
  padding: 12,
  borderRadius: 10,
  border: '1px solid var(--border-color)',
  background: 'transparent',
  color: 'var(--text-primary)',
  cursor: 'pointer',
};

const emptyStyle: React.CSSProperties = {
  color: 'var(--text-secondary)',
  display: 'flex',
  justifyContent: 'center',
  alignItems: 'center',
  minHeight: 120,
};

const dotStyle: React.CSSProperties = {
  width: 8,
  height: 8,
  borderRadius: '50%',
  background: 'var(--accent-gold)',
  flexShrink: 0,
  marginTop: 5,
};

export default MessagesPage;
