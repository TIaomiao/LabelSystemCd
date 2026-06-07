import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FaBell } from 'react-icons/fa';

interface InboxMessage {
  id: number;
  sender_id?: number | null;
  sender_username?: string | null;
  subject: string;
  body: string;
  category?: string;
  is_read: boolean;
  created_at?: string | null;
}

const formatTime = (value?: string | null) => {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { hour12: false });
};

const previewText = (text: string, maxLength = 72) => {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim();
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength)}...`;
};

const MessageInboxBell: React.FC = () => {
  const navigate = useNavigate();
  const shellRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [messages, setMessages] = useState<InboxMessage[]>([]);

  const fetchSummary = async () => {
    try {
      const response = await fetch('/api/messages/summary');
      const data = await response.json();
      if (!response.ok) return;
      setUnreadCount(Number(data.unread_count || 0));
      if (Array.isArray(data.recent) && !open) {
        setMessages(data.recent);
      }
    } catch (error) {
      console.error('Failed to load message summary', error);
    }
  };

  const fetchMessages = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/messages?limit=20');
      const data = await response.json();
      if (!response.ok) return;
      setMessages(Array.isArray(data.messages) ? data.messages : []);
      setUnreadCount(Number(data.unread_count || 0));
    } catch (error) {
      console.error('Failed to load messages', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchSummary();
    const timer = window.setInterval(() => {
      void fetchSummary();
    }, 30000);
    return () => window.clearInterval(timer);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    void fetchMessages();
  }, [open]);

  useEffect(() => {
    const handleClick = (event: MouseEvent) => {
      if (!shellRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const unreadBadge = useMemo(() => {
    if (unreadCount <= 0) return null;
    return unreadCount > 99 ? '99+' : String(unreadCount);
  }, [unreadCount]);

  const markAsRead = async (messageId: number) => {
    try {
      const response = await fetch(`/api/messages/${messageId}/read`, {
        method: 'POST',
      });
      const data = await response.json();
      if (!response.ok) return;
      const updated: InboxMessage = data.message;
      setMessages((prev) => prev.map((item) => (item.id === messageId ? updated : item)));
      setUnreadCount((prev) => Math.max(0, prev - 1));
    } catch (error) {
      console.error('Failed to mark message as read', error);
    }
  };

  return (
    <div ref={shellRef} style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen((prev) => !prev)}
        style={iconButtonStyle}
        title="消息"
      >
        <FaBell />
        {unreadBadge ? <span style={badgeStyle}>{unreadBadge}</span> : null}
      </button>
      {open ? (
        <div style={panelStyle}>
          <div style={panelHeaderStyle}>
            <strong>消息</strong>
            <button style={miniButtonStyle} onClick={() => void fetchMessages()}>
              刷新
            </button>
          </div>
          <div style={panelBodyStyle}>
            {loading ? (
              <div style={emptyStyle}>加载中...</div>
            ) : messages.length === 0 ? (
              <div style={emptyStyle}>暂无消息</div>
            ) : (
              messages.map((item) => (
                <button
                  key={item.id}
                  style={{
                    ...messageItemStyle,
                    backgroundColor: item.is_read ? 'transparent' : 'rgba(217, 119, 6, 0.08)',
                    borderColor: item.is_read ? 'var(--border-color)' : 'rgba(217, 119, 6, 0.28)',
                  }}
                  onClick={() => {
                    if (!item.is_read) {
                      void markAsRead(item.id);
                    }
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                    <strong style={{ color: 'var(--text-primary)' }}>
                      {item.subject || '站内消息'}
                    </strong>
                    {!item.is_read ? <span style={unreadDotStyle} /> : null}
                  </div>
                  <div style={{ color: 'var(--text-secondary)', fontSize: 13, marginTop: 4 }}>
                    来自 {item.sender_username || '系统'} · {formatTime(item.created_at)}
                  </div>
                  <div style={{ color: 'var(--text-secondary)', fontSize: 13, marginTop: 8, lineHeight: 1.5 }}>
                    {previewText(item.body)}
                  </div>
                </button>
              ))
            )}
          </div>
          <div style={panelFooterStyle}>
            <button
              style={miniButtonStyle}
              onClick={() => {
                setOpen(false);
                navigate('/messages');
              }}
            >
              查看全部
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
};

const iconButtonStyle: React.CSSProperties = {
  position: 'relative',
  width: 36,
  height: 36,
  borderRadius: 8,
  border: '1px solid var(--border-color)',
  background: 'transparent',
  color: 'var(--text-secondary)',
  cursor: 'pointer',
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
};

const badgeStyle: React.CSSProperties = {
  position: 'absolute',
  top: -6,
  right: -6,
  minWidth: 18,
  height: 18,
  borderRadius: 999,
  background: '#ef4444',
  color: '#fff',
  fontSize: 11,
  fontWeight: 700,
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  padding: '0 5px',
};

const panelStyle: React.CSSProperties = {
  position: 'absolute',
  top: 'calc(100% + 10px)',
  right: 0,
  width: 360,
  maxWidth: 'calc(100vw - 32px)',
  background: 'var(--bg-secondary)',
  border: '1px solid var(--border-color)',
  borderRadius: 12,
  boxShadow: 'var(--card-shadow)',
  zIndex: 1000,
  overflow: 'hidden',
};

const panelHeaderStyle: React.CSSProperties = {
  padding: '12px 14px',
  borderBottom: '1px solid var(--border-color)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
};

const panelBodyStyle: React.CSSProperties = {
  maxHeight: 420,
  overflowY: 'auto',
  padding: 12,
  display: 'flex',
  flexDirection: 'column',
  gap: 10,
};

const panelFooterStyle: React.CSSProperties = {
  padding: '10px 14px',
  borderTop: '1px solid var(--border-color)',
  display: 'flex',
  justifyContent: 'flex-end',
};

const miniButtonStyle: React.CSSProperties = {
  padding: '6px 10px',
  borderRadius: 6,
  border: '1px solid var(--border-color)',
  background: 'transparent',
  color: 'var(--text-secondary)',
  cursor: 'pointer',
};

const emptyStyle: React.CSSProperties = {
  padding: '20px 12px',
  color: 'var(--text-secondary)',
  textAlign: 'center',
};

const messageItemStyle: React.CSSProperties = {
  width: '100%',
  textAlign: 'left',
  padding: 12,
  borderRadius: 10,
  border: '1px solid var(--border-color)',
  background: 'transparent',
  cursor: 'pointer',
};

const unreadDotStyle: React.CSSProperties = {
  width: 8,
  height: 8,
  borderRadius: '50%',
  background: 'var(--accent-gold)',
  flexShrink: 0,
  marginTop: 6,
};

export default MessageInboxBell;
