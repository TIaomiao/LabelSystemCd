import React, { useState } from 'react';
import { useNavigate, Link, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useLanguage } from '../context/LanguageContext';

const LoginPage = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [forgotIdentifier, setForgotIdentifier] = useState('');
  const [forgotNote, setForgotNote] = useState('');
  const [forgotError, setForgotError] = useState('');
  const [forgotSuccess, setForgotSuccess] = useState('');
  const [forgotLoading, setForgotLoading] = useState(false);
  const [showForgot, setShowForgot] = useState(false);
  const { login } = useAuth();
  const { t } = useLanguage();
  const navigate = useNavigate();
  const location = useLocation();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });

      const data = await response.json();

      if (response.ok) {
        login(data.user);
        const nextPath = (location.state as { from?: { pathname?: string } } | null)?.from?.pathname || '/workstation';
        navigate(nextPath);
      } else {
        setError(data.error || t('auth.login_failed'));
      }
    } catch (err) {
      setError(t('auth.error_generic'));
    }
  };

  const handleForgotPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setForgotError('');
    setForgotSuccess('');
    setForgotLoading(true);
    try {
      const response = await fetch('/api/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ identifier: forgotIdentifier, note: forgotNote }),
      });
      const data = await response.json();
      if (!response.ok) {
        setForgotError(data.error || '提交重置申请失败');
        return;
      }
      setForgotSuccess(data.message || '重置申请已提交，请等待管理员审核。');
      setForgotNote('');
    } catch (err) {
      setForgotError('提交重置申请失败');
    } finally {
      setForgotLoading(false);
    }
  };

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      height: '100vh',
      backgroundColor: 'var(--bg-primary)',
      color: 'var(--text-primary)'
    }}>
      <div style={{
        padding: '2rem',
        backgroundColor: 'var(--bg-secondary)',
        borderRadius: 'var(--border-radius)',
        boxShadow: 'var(--card-shadow)',
        width: '100%',
        maxWidth: '400px',
        border: '1px solid var(--border-color)'
      }}>
        <h2 style={{ marginBottom: '1.5rem', textAlign: 'center', color: 'var(--text-primary)' }}>{t('auth.login')}</h2>
        {error && <div style={{ color: 'var(--error-color)', marginBottom: '1rem' }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)' }}>{t('auth.username')}</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              style={{ 
                width: '100%', 
                padding: '0.5rem', 
                borderRadius: 'var(--border-radius)', 
                border: '1px solid var(--input-border)',
                backgroundColor: 'var(--input-bg)',
                color: 'var(--text-primary)'
              }}
              required
            />
          </div>
          <div style={{ marginBottom: '1.5rem' }}>
            <label style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)' }}>{t('auth.password')}</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={{ 
                width: '100%', 
                padding: '0.5rem', 
                borderRadius: 'var(--border-radius)', 
                border: '1px solid var(--input-border)',
                backgroundColor: 'var(--input-bg)',
                color: 'var(--text-primary)'
              }}
              required
            />
          </div>
          <button
            type="submit"
            style={{
              width: '100%',
              padding: '0.75rem',
              backgroundColor: 'var(--accent-gold)',
              color: 'white',
              border: 'none',
              borderRadius: 'var(--border-radius)',
              cursor: 'pointer',
              fontSize: '1rem',
              fontWeight: 500
            }}
          >
            {t('auth.login')}
          </button>
        </form>
        <div style={{ marginTop: '1rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
          {t('auth.no_account')} <Link to="/register" style={{ color: 'var(--accent-gold)' }}>{t('auth.register')}</Link>
        </div>
        <div style={{ marginTop: '0.75rem', textAlign: 'center' }}>
          <button
            type="button"
            onClick={() => {
              setShowForgot(value => !value);
              setForgotError('');
              setForgotSuccess('');
              setForgotIdentifier(prev => prev || username);
            }}
            style={{
              border: 'none',
              background: 'transparent',
              color: 'var(--accent-gold)',
              cursor: 'pointer',
              fontSize: '0.95rem'
            }}
          >
            忘记密码
          </button>
        </div>
        {showForgot && (
          <form onSubmit={handleForgotPassword} style={{
            marginTop: '1.25rem',
            paddingTop: '1rem',
            borderTop: '1px solid var(--border-color)'
          }}>
            <div style={{ color: 'var(--text-secondary)', marginBottom: '0.75rem', lineHeight: 1.5, fontSize: '0.92rem' }}>
              输入用户名或邮箱后，系统会把密码重置申请提交给管理员审核。
            </div>
            {forgotError && <div style={{ color: 'var(--error-color)', marginBottom: '0.75rem' }}>{forgotError}</div>}
            {forgotSuccess && <div style={{ color: 'var(--success-color, #22c55e)', marginBottom: '0.75rem' }}>{forgotSuccess}</div>}
            <div style={{ marginBottom: '0.75rem' }}>
              <label style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)' }}>用户名或邮箱</label>
              <input
                type="text"
                value={forgotIdentifier}
                onChange={(e) => setForgotIdentifier(e.target.value)}
                style={{
                  width: '100%',
                  padding: '0.5rem',
                  borderRadius: 'var(--border-radius)',
                  border: '1px solid var(--input-border)',
                  backgroundColor: 'var(--input-bg)',
                  color: 'var(--text-primary)'
                }}
                required
              />
            </div>
            <div style={{ marginBottom: '1rem' }}>
              <label style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)' }}>补充说明</label>
              <textarea
                value={forgotNote}
                onChange={(e) => setForgotNote(e.target.value)}
                rows={3}
                placeholder="可选，例如：原密码遗忘、账号长期未登录等。"
                style={{
                  width: '100%',
                  padding: '0.5rem',
                  borderRadius: 'var(--border-radius)',
                  border: '1px solid var(--input-border)',
                  backgroundColor: 'var(--input-bg)',
                  color: 'var(--text-primary)',
                  resize: 'vertical'
                }}
              />
            </div>
            <button
              type="submit"
              disabled={forgotLoading}
              style={{
                width: '100%',
                padding: '0.65rem',
                backgroundColor: 'transparent',
                color: 'var(--accent-gold)',
                border: '1px solid var(--accent-gold)',
                borderRadius: 'var(--border-radius)',
                cursor: forgotLoading ? 'wait' : 'pointer',
                fontSize: '0.96rem',
                fontWeight: 500
              }}
            >
              {forgotLoading ? '提交中...' : '提交重置申请'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
};

export default LoginPage;
