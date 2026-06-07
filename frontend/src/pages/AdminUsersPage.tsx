import React, { useEffect, useState } from 'react';

interface AdminUser {
  id: number;
  username: string;
  email?: string | null;
  is_approved: boolean;
  is_admin: boolean;
  requested_at?: string | null;
  approved_at?: string | null;
  password_reset_status?: string | null;
  password_reset_requested_at?: string | null;
  password_reset_handled_at?: string | null;
  password_reset_note?: string | null;
}

const AdminUsersPage: React.FC = () => {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [composeUser, setComposeUser] = useState<AdminUser | null>(null);
  const [messageSubject, setMessageSubject] = useState('');
  const [messageBody, setMessageBody] = useState('');
  const [sending, setSending] = useState(false);
  const [resetUser, setResetUser] = useState<AdminUser | null>(null);
  const [resetPassword, setResetPassword] = useState('');
  const [resetMessage, setResetMessage] = useState('');
  const [resetting, setResetting] = useState(false);

  const loadUsers = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/admin/users');
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '加载用户失败');
      setUsers(data.users || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载用户失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadUsers();
  }, []);

  const postAction = async (userId: number, action: string, body?: object) => {
    setError('');
    setSuccess('');
    try {
      const response = await fetch(`/api/admin/users/${userId}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '操作失败');
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败');
    }
  };

  const sendMessage = async () => {
    if (!composeUser) return;
    setError('');
    setSuccess('');
    setSending(true);
    try {
      const response = await fetch('/api/messages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          recipient_id: composeUser.id,
          subject: messageSubject,
          body: messageBody,
          category: 'admin_notice',
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '发送消息失败');
      setSuccess(`已向 ${composeUser.username} 发送消息`);
      setComposeUser(null);
      setMessageSubject('');
      setMessageBody('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '发送消息失败');
    } finally {
      setSending(false);
    }
  };

  const submitPasswordReset = async () => {
    if (!resetUser) return;
    setError('');
    setSuccess('');
    setResetting(true);
    try {
      const response = await fetch(`/api/admin/users/${resetUser.id}/password-reset`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          temporary_password: resetPassword,
          message: resetMessage,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '重置密码失败');
      setSuccess(`已为 ${resetUser.username} 设置临时密码`);
      setResetUser(null);
      setResetPassword('');
      setResetMessage('');
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : '重置密码失败');
    } finally {
      setResetting(false);
    }
  };

  const rejectPasswordReset = async (user: AdminUser) => {
    setError('');
    setSuccess('');
    try {
      const response = await fetch(`/api/admin/users/${user.id}/password-reset/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: '请联系管理员补充账号信息后重新提交申请。' }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '驳回失败');
      setSuccess(`已驳回 ${user.username} 的密码重置申请`);
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : '驳回失败');
    }
  };

  return (
    <div style={{ padding: 24, color: 'var(--text-primary)' }}>
      <h2 style={{ marginTop: 0 }}>用户审核</h2>
      <p style={{ color: 'var(--text-secondary)' }}>
        新注册账号需要管理员审核通过后才能登录工作站。已通过账号可以直接从这里发送站内消息。
      </p>
      {error && <div style={{ color: 'var(--error-color)', marginBottom: 16 }}>{error}</div>}
      {success && <div style={{ color: 'var(--success-color, #22c55e)', marginBottom: 16 }}>{success}</div>}
      {loading ? (
        <div>加载中...</div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', background: 'var(--bg-secondary)' }}>
            <thead>
              <tr>
                {['ID', '用户名', '邮箱', '状态', '管理员', '申请时间', '审核时间', '密码重置', '操作'].map((label) => (
                  <th key={label} style={{ textAlign: 'left', padding: 12, borderBottom: '1px solid var(--border-color)' }}>
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td style={{ padding: 12, borderBottom: '1px solid var(--border-color)' }}>{user.id}</td>
                  <td style={{ padding: 12, borderBottom: '1px solid var(--border-color)' }}>{user.username}</td>
                  <td style={{ padding: 12, borderBottom: '1px solid var(--border-color)' }}>{user.email || '-'}</td>
                  <td style={{ padding: 12, borderBottom: '1px solid var(--border-color)' }}>
                    {user.is_approved ? '已通过' : '待审核'}
                  </td>
                  <td style={{ padding: 12, borderBottom: '1px solid var(--border-color)' }}>
                    {user.is_admin ? '是' : '否'}
                  </td>
                  <td style={{ padding: 12, borderBottom: '1px solid var(--border-color)' }}>{user.requested_at || '-'}</td>
                  <td style={{ padding: 12, borderBottom: '1px solid var(--border-color)' }}>{user.approved_at || '-'}</td>
                  <td style={{ padding: 12, borderBottom: '1px solid var(--border-color)', minWidth: 220 }}>
                    {user.password_reset_status === 'pending' ? (
                      <div>
                        <div style={{ color: 'var(--accent-gold)', fontWeight: 600 }}>待审核</div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: 12 }}>{user.password_reset_requested_at || '-'}</div>
                        {user.password_reset_note ? (
                          <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginTop: 4, whiteSpace: 'pre-wrap' }}>{user.password_reset_note}</div>
                        ) : null}
                      </div>
                    ) : user.password_reset_status === 'approved' ? (
                      <div>
                        <div style={{ color: 'var(--success-color, #22c55e)', fontWeight: 600 }}>已处理</div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: 12 }}>{user.password_reset_handled_at || '-'}</div>
                      </div>
                    ) : user.password_reset_status === 'rejected' ? (
                      <div>
                        <div style={{ color: 'var(--error-color)', fontWeight: 600 }}>已驳回</div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: 12 }}>{user.password_reset_handled_at || '-'}</div>
                      </div>
                    ) : (
                      <span style={{ color: 'var(--text-secondary)' }}>无</span>
                    )}
                  </td>
                  <td style={{ padding: 12, borderBottom: '1px solid var(--border-color)', whiteSpace: 'nowrap' }}>
                    {!user.is_approved && (
                      <>
                        <button onClick={() => void postAction(user.id, 'approve')} style={buttonStyle}>
                          通过
                        </button>
                        <button onClick={() => void postAction(user.id, 'reject')} style={dangerButtonStyle}>
                          拒绝
                        </button>
                      </>
                    )}
                    {user.is_approved && (
                      <>
                        <button
                          onClick={() => {
                            setResetUser(user);
                            setResetPassword('');
                            setResetMessage(user.password_reset_status === 'pending' ? '管理员已审核通过，下面是你的临时密码。' : '');
                            setError('');
                            setSuccess('');
                          }}
                          style={buttonStyle}
                        >
                          {user.password_reset_status === 'pending' ? '审核重置' : '设临时密码'}
                        </button>
                        {user.password_reset_status === 'pending' && (
                          <button
                            onClick={() => void rejectPasswordReset(user)}
                            style={dangerButtonStyle}
                          >
                            驳回重置
                          </button>
                        )}
                        <button
                          onClick={() => void postAction(user.id, 'admin', { is_admin: !user.is_admin })}
                          style={buttonStyle}
                        >
                          {user.is_admin ? '取消管理员' : '设为管理员'}
                        </button>
                        <button
                          onClick={() => {
                            setComposeUser(user);
                            setMessageSubject('');
                            setMessageBody('');
                            setError('');
                            setSuccess('');
                          }}
                          style={buttonStyle}
                        >
                          发消息
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {resetUser && (
        <div style={overlayStyle}>
          <div style={modalStyle}>
            <h3 style={{ marginTop: 0 }}>{resetUser.password_reset_status === 'pending' ? '审核密码重置申请' : '设置临时密码'}</h3>
            <div style={{ color: 'var(--text-secondary)', marginBottom: 12, lineHeight: 1.6 }}>
              用户：{resetUser.username} {resetUser.email ? `(${resetUser.email})` : ''}
              {resetUser.password_reset_note ? <div style={{ marginTop: 6 }}>申请说明：{resetUser.password_reset_note}</div> : null}
            </div>
            <div style={{ marginBottom: 12 }}>
              <label style={labelStyle}>临时密码</label>
              <input
                value={resetPassword}
                onChange={(event) => setResetPassword(event.target.value)}
                placeholder="至少 8 位"
                style={fieldStyle}
              />
            </div>
            <div style={{ marginBottom: 16 }}>
              <label style={labelStyle}>管理员备注</label>
              <textarea
                value={resetMessage}
                onChange={(event) => setResetMessage(event.target.value)}
                rows={4}
                style={{ ...fieldStyle, resize: 'vertical' }}
                placeholder="会通过站内消息发给用户。"
              />
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button
                onClick={() => {
                  setResetUser(null);
                  setResetPassword('');
                  setResetMessage('');
                }}
                style={secondaryButtonStyle}
                disabled={resetting}
              >
                取消
              </button>
              <button
                onClick={() => void submitPasswordReset()}
                style={buttonStyle}
                disabled={resetting || resetPassword.trim().length < 8}
              >
                {resetting ? '处理中...' : '确认重置'}
              </button>
            </div>
          </div>
        </div>
      )}
      {composeUser && (
        <div style={overlayStyle}>
          <div style={modalStyle}>
            <h3 style={{ marginTop: 0 }}>发送站内消息</h3>
            <div style={{ color: 'var(--text-secondary)', marginBottom: 12 }}>
              收件人：{composeUser.username} {composeUser.email ? `(${composeUser.email})` : ''}
            </div>
            <div style={{ marginBottom: 12 }}>
              <label style={labelStyle}>标题</label>
              <input
                value={messageSubject}
                onChange={(event) => setMessageSubject(event.target.value)}
                placeholder="可选，建议写明事项"
                style={fieldStyle}
              />
            </div>
            <div style={{ marginBottom: 16 }}>
              <label style={labelStyle}>内容</label>
              <textarea
                value={messageBody}
                onChange={(event) => setMessageBody(event.target.value)}
                placeholder="例如：请今天完成报告评分复核。"
                rows={6}
                style={{ ...fieldStyle, resize: 'vertical' }}
              />
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button
                onClick={() => {
                  setComposeUser(null);
                  setMessageSubject('');
                  setMessageBody('');
                }}
                style={secondaryButtonStyle}
                disabled={sending}
              >
                取消
              </button>
              <button onClick={() => void sendMessage()} style={buttonStyle} disabled={sending || !messageBody.trim()}>
                {sending ? '发送中...' : '发送'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const buttonStyle: React.CSSProperties = {
  marginRight: 8,
  padding: '6px 10px',
  borderRadius: 4,
  border: '1px solid var(--border-color)',
  background: 'var(--accent-gold)',
  color: '#fff',
  cursor: 'pointer',
};

const dangerButtonStyle: React.CSSProperties = {
  ...buttonStyle,
  background: 'transparent',
  color: 'var(--error-color)',
};

const secondaryButtonStyle: React.CSSProperties = {
  ...buttonStyle,
  background: 'transparent',
  color: 'var(--text-secondary)',
};

const overlayStyle: React.CSSProperties = {
  position: 'fixed',
  inset: 0,
  background: 'rgba(0, 0, 0, 0.45)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  zIndex: 1000,
};

const modalStyle: React.CSSProperties = {
  width: 'min(560px, calc(100vw - 32px))',
  background: 'var(--bg-secondary)',
  border: '1px solid var(--border-color)',
  borderRadius: 12,
  padding: 20,
  boxShadow: 'var(--card-shadow)',
};

const labelStyle: React.CSSProperties = {
  display: 'block',
  marginBottom: 6,
  color: 'var(--text-secondary)',
  fontSize: 14,
};

const fieldStyle: React.CSSProperties = {
  width: '100%',
  padding: '10px 12px',
  borderRadius: 8,
  border: '1px solid var(--border-color)',
  background: 'var(--bg-primary)',
  color: 'var(--text-primary)',
  boxSizing: 'border-box',
};

export default AdminUsersPage;
