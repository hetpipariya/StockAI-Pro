import React, { useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../components/Toast';

const getLoginErrorMessage = (error) => {
  if (!error) return 'Login failed. Please try again.';
  if (typeof error === 'string' && error.trim()) return error;
  if (typeof error?.message === 'string' && error.message.trim()) return error.message;
  if (typeof error?.detail === 'string' && error.detail.trim()) return error.detail;
  return 'Unable to sign in right now. Please check your connection and try again.';
};

export default function LoginPage() {
  const navigate = useNavigate();
  const { isAuthenticated, login, isLoading } = useAuth();
  const { showToast } = useToast();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (!isLoading && isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  const handleSubmit = async (event) => {
    event.preventDefault();
    event.stopPropagation();

    if (!email.trim() || !password) {
      showToast('Email and password are required', 'warning');
      return;
    }

    setSubmitting(true);
    try {
      await login({ email: email.trim().toLowerCase(), password });
      showToast('Login successful', 'success');
      navigate('/', { replace: true });
    } catch (error) {
      console.error('Login error:', error);
      showToast(getLoginErrorMessage(error), 'error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: 'var(--bg-app)', padding: '24px' }}>
      <form
        method="post"
        onSubmit={handleSubmit}
        style={{
          width: 'min(420px, 100%)',
          background: 'var(--bg-panel)',
          border: '1px solid var(--border-subtle)',
          borderRadius: '14px',
          padding: '24px',
          display: 'grid',
          gap: '14px',
        }}
      >
        <h1 style={{ margin: 0, color: 'var(--text-primary)' }}>Sign In</h1>
        <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '14px' }}>
          Use your StockAI-Pro account to access live bundle data and trading simulation.
        </p>

        <label style={{ display: 'grid', gap: '6px' }}>
          <span style={{ color: 'var(--text-secondary)', fontSize: '12px', textTransform: 'uppercase' }}>Email</span>
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            autoComplete="email"
            style={{
              background: 'var(--bg-interactive)',
              border: '1px solid var(--border-subtle)',
              color: 'var(--text-primary)',
              padding: '10px 12px',
              borderRadius: '8px',
              outline: 'none',
            }}
          />
        </label>

        <label style={{ display: 'grid', gap: '6px' }}>
          <span style={{ color: 'var(--text-secondary)', fontSize: '12px', textTransform: 'uppercase' }}>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="********"
            autoComplete="current-password"
            style={{
              background: 'var(--bg-interactive)',
              border: '1px solid var(--border-subtle)',
              color: 'var(--text-primary)',
              padding: '10px 12px',
              borderRadius: '8px',
              outline: 'none',
            }}
          />
        </label>

        <button
          type="submit"
          disabled={submitting}
          style={{
            background: 'var(--primary)',
            color: '#062012',
            fontWeight: 700,
            border: 'none',
            borderRadius: '8px',
            padding: '11px 12px',
            cursor: submitting ? 'not-allowed' : 'pointer',
            opacity: submitting ? 0.6 : 1,
          }}
        >
          {submitting ? 'Signing in...' : 'Sign In'}
        </button>

        <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '13px' }}>
          Access is restricted to approved users. Contact the administrator if you need onboarding.
        </p>
      </form>
    </div>
  );
}
