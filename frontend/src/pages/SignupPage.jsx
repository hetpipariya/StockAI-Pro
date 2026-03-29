import React, { useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../components/ui/Toast';

export default function SignupPage() {
  const navigate = useNavigate();
  const { isAuthenticated, signup, isLoading } = useAuth();
  const { showToast } = useToast();

  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (!isLoading && isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  const onSubmit = async (event) => {
    event.preventDefault();

    if (!username.trim()) {
      showToast('Username is required', 'warning');
      return;
    }

    if (!password || password.length < 8) {
      showToast('Password must be at least 8 characters', 'warning');
      return;
    }

    if (password !== confirmPassword) {
      showToast('Passwords do not match', 'warning');
      return;
    }

    setSubmitting(true);
    try {
      const user = await signup({
        username: username.trim(),
        email: email.trim() || null,
        password,
      });

      showToast(`Signup successful. Your user id is ${user.id}`, 'success');
      navigate('/', { replace: true });
    } catch (error) {
      showToast(error?.message || 'Signup failed', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: 'var(--bg-app)', padding: '24px' }}>
      <form
        onSubmit={onSubmit}
        style={{
          width: 'min(460px, 100%)',
          background: 'var(--bg-panel)',
          border: '1px solid var(--border-subtle)',
          borderRadius: '14px',
          padding: '24px',
          display: 'grid',
          gap: '14px',
        }}
      >
        <h1 style={{ margin: 0, color: 'var(--text-primary)' }}>Create Account</h1>
        <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '14px' }}>
          Sign up to enable authenticated websocket streaming and protected trading simulation.
        </p>

        <label style={{ display: 'grid', gap: '6px' }}>
          <span style={{ color: 'var(--text-secondary)', fontSize: '12px', textTransform: 'uppercase' }}>Username</span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="new_user"
            autoComplete="username"
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
          <span style={{ color: 'var(--text-secondary)', fontSize: '12px', textTransform: 'uppercase' }}>Email (optional)</span>
          <input
            type="email"
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
            placeholder="At least 8 chars, include a number"
            autoComplete="new-password"
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
          <span style={{ color: 'var(--text-secondary)', fontSize: '12px', textTransform: 'uppercase' }}>Confirm password</span>
          <input
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            placeholder="Repeat password"
            autoComplete="new-password"
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
          {submitting ? 'Creating account...' : 'Create Account'}
        </button>

        <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '13px' }}>
          Already have an account? <Link to="/login" style={{ color: 'var(--primary)' }}>Sign in</Link>
        </p>
      </form>
    </div>
  );
}
