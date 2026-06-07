import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useLanguage } from '../context/LanguageContext';

const RegisterPage = () => {
  const { t } = useLanguage();
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');

    if (password !== confirmPassword) {
      setError(t('auth.passwords_mismatch'));
      return;
    }

    try {
      const response = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, email, password }),
      });

      const data = await response.json();

      if (response.ok) {
        setSuccess(data.message || '注册申请已提交，请等待管理员审核。');
        setUsername('');
        setEmail('');
        setPassword('');
        setConfirmPassword('');
        window.setTimeout(() => navigate('/login'), 1800);
      } else {
        setError(data.error || t('auth.registration_failed'));
      }
    } catch (err) {
      setError(t('auth.error_generic'));
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
        <h2 style={{ marginBottom: '1.5rem', textAlign: 'center', color: 'var(--text-primary)' }}>{t('auth.register')}</h2>
        {error && <div style={{ color: 'var(--error-color)', marginBottom: '1rem' }}>{error}</div>}
        {success && <div style={{ color: 'var(--success-color, #22c55e)', marginBottom: '1rem' }}>{success}</div>}
        <div style={{ color: 'var(--text-secondary)', marginBottom: '1rem', lineHeight: 1.5 }}>
          注册后需要管理员审核，通过后才能登录系统。
        </div>
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
          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)' }}>Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
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
            <label style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)' }}>Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
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
            <label style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)' }}>{t('auth.confirm_password')}</label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              minLength={8}
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
            {t('auth.register')}
          </button>
        </form>
        <div style={{ marginTop: '1rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
          {t('auth.has_account')} <Link to="/login" style={{ color: 'var(--accent-gold)' }}>{t('auth.login')}</Link>
        </div>
      </div>
    </div>
  );
};

export default RegisterPage;
