import React, { useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { AlertTriangle, ArrowRight, ShieldCheck, UserPlus } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../components/Toast';

export default function SignupPage() {
  const navigate = useNavigate();
  const { isAuthenticated, signup, isLoading } = useAuth();
  const { showToast } = useToast();

  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState('');

  if (!isLoading && isAuthenticated) {
    return <Navigate to="/dashboard" replace />;
  }

  const onSubmit = async (event) => {
    event.preventDefault();
    setLocalError('');

    if (!username.trim()) {
      setLocalError('Username is required.');
      return;
    }

    const emailNormalized = email.trim().toLowerCase();
    if (!emailNormalized || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailNormalized)) {
      setLocalError('Enter a valid email address.');
      return;
    }

    if (!password || password.length < 8) {
      setLocalError('Password must be at least 8 characters.');
      return;
    }

    if (password !== confirmPassword) {
      setLocalError('Passwords do not match.');
      return;
    }

    setSubmitting(true);
    try {
      const user = await signup({
        username: username.trim(),
        email: emailNormalized,
        password,
      });
      showToast(`Welcome ${user?.email || emailNormalized}`, 'success');
      navigate('/dashboard', { replace: true });
    } catch (error) {
      setLocalError(error?.message || 'Signup failed.');
      showToast(error?.message || 'Signup failed', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#040A16] text-slate-100 overflow-hidden">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_18%_0%,rgba(34,211,238,0.2),transparent_35%),radial-gradient(circle_at_84%_10%,rgba(16,185,129,0.16),transparent_34%)]" />
      <div className="relative min-h-screen flex items-center justify-center p-5 sm:p-8">
        <form onSubmit={onSubmit} className="w-full max-w-xl rounded-3xl border border-white/10 bg-[#081627]/85 p-7 sm:p-9 backdrop-blur-xl shadow-[0_24px_65px_rgba(0,0,0,0.45)]">
          <div className="flex items-center justify-between mb-7">
            <div>
              <p className="text-xs uppercase tracking-[0.16em] text-slate-400 font-bold">Terminal Access</p>
              <h1 className="mt-2 text-3xl font-black text-white">Create Account</h1>
            </div>
            <div className="h-11 w-11 rounded-2xl border border-cyan-500/40 bg-cyan-500/10 flex items-center justify-center">
              <UserPlus className="h-5 w-5 text-cyan-300" />
            </div>
          </div>

          <div className="grid sm:grid-cols-2 gap-4">
            <label className="block sm:col-span-2">
              <span className="text-xs uppercase tracking-[0.14em] text-slate-400 font-semibold">Username</span>
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                className="mt-2 w-full rounded-xl border border-white/10 bg-[#0A1A30] px-3 py-3 text-slate-100 placeholder:text-slate-500 outline-none focus:border-cyan-400/70 focus:shadow-[0_0_0_3px_rgba(34,211,238,0.15)]"
                placeholder="your_username"
                autoComplete="username"
              />
            </label>

            <label className="block sm:col-span-2">
              <span className="text-xs uppercase tracking-[0.14em] text-slate-400 font-semibold">Email</span>
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                className="mt-2 w-full rounded-xl border border-white/10 bg-[#0A1A30] px-3 py-3 text-slate-100 placeholder:text-slate-500 outline-none focus:border-cyan-400/70 focus:shadow-[0_0_0_3px_rgba(34,211,238,0.15)]"
                placeholder="you@desk.com"
                autoComplete="email"
              />
            </label>

            <label className="block">
              <span className="text-xs uppercase tracking-[0.14em] text-slate-400 font-semibold">Password</span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="mt-2 w-full rounded-xl border border-white/10 bg-[#0A1A30] px-3 py-3 text-slate-100 placeholder:text-slate-500 outline-none focus:border-cyan-400/70 focus:shadow-[0_0_0_3px_rgba(34,211,238,0.15)]"
                placeholder="Minimum 8 characters"
                autoComplete="new-password"
              />
            </label>

            <label className="block">
              <span className="text-xs uppercase tracking-[0.14em] text-slate-400 font-semibold">Confirm Password</span>
              <input
                type="password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                className="mt-2 w-full rounded-xl border border-white/10 bg-[#0A1A30] px-3 py-3 text-slate-100 placeholder:text-slate-500 outline-none focus:border-cyan-400/70 focus:shadow-[0_0_0_3px_rgba(34,211,238,0.15)]"
                placeholder="Repeat password"
                autoComplete="new-password"
              />
            </label>
          </div>

          {localError ? (
            <div className="mt-4 rounded-xl border border-rose-500/40 bg-rose-500/10 px-3 py-2.5 text-sm text-rose-200 flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 mt-0.5" />
              <span>{localError}</span>
            </div>
          ) : null}

          <button
            type="submit"
            disabled={submitting}
            className={`mt-5 w-full rounded-xl py-3.5 font-bold transition flex items-center justify-center gap-2 ${submitting
              ? 'bg-slate-700/40 text-slate-500 cursor-not-allowed'
              : 'bg-gradient-to-r from-cyan-500 to-emerald-500 text-[#041019] hover:translate-y-[-1px] shadow-[0_12px_28px_rgba(16,185,129,0.28)]'}`}
          >
            {submitting ? 'Creating account...' : 'Create Account'}
            {!submitting ? <ArrowRight className="h-4 w-4" /> : null}
          </button>

          <div className="mt-5 flex items-center justify-between text-sm">
            <Link to="/login" className="text-cyan-300 hover:text-cyan-200 font-semibold">Already have an account?</Link>
            <span className="inline-flex items-center gap-1.5 text-slate-500">
              <ShieldCheck className="h-3.5 w-3.5" />
              Protected Session
            </span>
          </div>
        </form>
      </div>
    </div>
  );
}
