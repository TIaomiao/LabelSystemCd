import React, { useState } from 'react';
import { useLanguage } from '../context/LanguageContext';

const SettingsPage: React.FC = () => {
  const { t } = useLanguage();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [saving, setSaving] = useState(false);

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    if (newPassword !== confirmPassword) {
      setError('两次输入的新密码不一致');
      return;
    }
    setSaving(true);
    try {
      const response = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        setError(data.error || '修改密码失败');
        return;
      }
      setSuccess(data.message || '密码修改成功');
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err) {
      setError('修改密码失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ padding: '24px' }}>
      <h1 style={{ color: 'var(--text-primary)' }}>{t('sidebar.settings')}</h1>
      <div style={{ 
        backgroundColor: 'var(--bg-secondary)', 
        padding: '24px', 
        borderRadius: 'var(--border-radius)',
        marginTop: '24px',
        maxWidth: '600px'
      }}>
        <div style={{ marginBottom: '24px' }}>
          <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-secondary)' }}>{t('settings.theme')}</label>
          <select style={{ 
            padding: '8px 12px', 
            borderRadius: '4px', 
            border: '1px solid var(--border-color)',
            backgroundColor: 'var(--input-bg)',
            color: 'var(--text-primary)',
            width: '100%'
          }}>
            <option>{t('settings.theme_system')}</option>
            <option>{t('settings.theme_light')}</option>
            <option>{t('settings.theme_dark')}</option>
          </select>
        </div>
        <div style={{ marginBottom: '24px' }}>
          <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-secondary)' }}>{t('settings.language')}</label>
          <select style={{ 
            padding: '8px 12px', 
            borderRadius: '4px', 
            border: '1px solid var(--border-color)',
            backgroundColor: 'var(--input-bg)',
            color: 'var(--text-primary)',
            width: '100%'
          }}>
            <option>{t('settings.lang_zh')}</option>
            <option>{t('settings.lang_en')}</option>
          </select>
        </div>
        <form onSubmit={handleChangePassword}>
          <h2 style={{ margin: '0 0 16px', fontSize: 18, color: 'var(--text-primary)' }}>修改密码</h2>
          <div style={{ color: 'var(--text-secondary)', marginBottom: 16, lineHeight: 1.5 }}>
            已登录用户可以在这里自行修改密码。若完全忘记密码，请回到登录页提交“忘记密码”申请，由管理员审核后重置。
          </div>
          {error && <div style={{ color: 'var(--error-color)', marginBottom: 12 }}>{error}</div>}
          {success && <div style={{ color: 'var(--success-color, #22c55e)', marginBottom: 12 }}>{success}</div>}
          <div style={{ marginBottom: '16px' }}>
            <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-secondary)' }}>当前密码</label>
            <input
              type="password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              style={fieldStyle}
              required
            />
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-secondary)' }}>新密码</label>
            <input
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              minLength={8}
              style={fieldStyle}
              required
            />
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-secondary)' }}>确认新密码</label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              minLength={8}
              style={fieldStyle}
              required
            />
          </div>
          <button
            type="submit"
            disabled={saving}
            style={{
              padding: '10px 16px',
              borderRadius: 8,
              border: 'none',
              backgroundColor: 'var(--accent-gold)',
              color: '#fff',
              cursor: saving ? 'wait' : 'pointer',
              fontWeight: 500
            }}
          >
            {saving ? '保存中...' : '保存新密码'}
          </button>
        </form>
      </div>
    </div>
  );
};

const fieldStyle: React.CSSProperties = {
  padding: '8px 12px',
  borderRadius: '4px',
  border: '1px solid var(--border-color)',
  backgroundColor: 'var(--input-bg)',
  color: 'var(--text-primary)',
  width: '100%',
  boxSizing: 'border-box',
};

export default SettingsPage;
