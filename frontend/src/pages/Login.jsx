import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/useAuthStore';
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CheckCircle,
  Eye,
  EyeOff,
  KeyRound,
  Loader,
  Lock,
  TrendingUp,
  User,
} from 'lucide-react';

const Login = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);
  const [isError, setIsError] = useState(false);
  const [isChecking, setIsChecking] = useState(false);
  const [focusedField, setFocusedField] = useState(null);
  const [shakeError, setShakeError] = useState(false);
  
  const login = useAuthStore((state) => state.login);
  const error = useAuthStore((state) => state.error);
  const clearError = useAuthStore((state) => state.clearError);
  const navigate = useNavigate();

  const handleLogin = async (e) => {
    e.preventDefault();
    if (!username.trim() || !password) {
      setIsError(true);
      setShakeError(true);
      setTimeout(() => setShakeError(false), 500);
      return;
    }
    
    setIsChecking(true);
    setIsError(false);

    const success = await login({ username: username.trim().toLowerCase(), password });
    
    if (success) {
      if (rememberMe) {
        localStorage.setItem('rememberUsername', username.trim().toLowerCase());
      } else {
        localStorage.removeItem('rememberUsername');
      }
      navigate('/dashboard');
    } else {
      setIsError(true);
      setShakeError(true);
      setTimeout(() => setShakeError(false), 500);
    }

    setIsChecking(false);
  };

  const handleFieldChange = (field, value) => {
    if (field === 'username') setUsername(value);
    if (field === 'password') setPassword(value);
    setIsError(false);
    clearError();
  };

  return (
    <div className="relative min-h-screen overflow-hidden bg-gradient-to-br from-[#0a0f1c] via-[#0f172a] to-[#020617] text-slate-100">
      <div
        className="pointer-events-none absolute inset-0 bg-grid-pattern bg-[size:34px_34px] opacity-[0.12] [mask-image:radial-gradient(circle_at_center,black_38%,transparent_88%)]"
        aria-hidden="true"
      />
      <div
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_35%,rgba(56,189,248,0.12),transparent_60%)]"
        aria-hidden="true"
      />
      <div
        className="pointer-events-none absolute left-1/2 top-1/2 h-[34rem] w-[34rem] -translate-x-1/2 -translate-y-1/2 rounded-full bg-emerald-400/10 blur-[130px]"
        aria-hidden="true"
      />

      <div className="relative flex min-h-screen items-center justify-center px-4 py-10 sm:px-6 lg:px-8">
        <div className="w-full max-w-lg space-y-5">
          <div className="text-center">
            <p className="inline-flex rounded-full border border-white/10 bg-white/[0.03] px-4 py-1.5 text-xs font-semibold uppercase tracking-[0.22em] text-slate-300 backdrop-blur-sm">
              StockAI Pro
            </p>
          </div>

          <section className="relative">
            <div
              className="pointer-events-none absolute -inset-6 -z-10 rounded-[2rem] bg-emerald-400/10 blur-3xl"
              aria-hidden="true"
            />

            <div
              className={`w-full max-w-md sm:max-w-lg rounded-3xl border border-white/10 bg-slate-950/65 p-7 shadow-[0_0_40px_rgba(0,255,159,0.1),0_18px_40px_rgba(2,6,23,0.65)] backdrop-blur-xl transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_0_52px_rgba(0,255,159,0.16),0_20px_45px_rgba(2,6,23,0.7)] animate-card-enter ${shakeError ? 'animate-shake' : ''}`}
            >
            <div className="flex items-center gap-3 mb-8">
              <div className="h-11 w-11 rounded-2xl bg-gradient-to-br from-cyan-500/40 to-emerald-500/30 border border-cyan-400/60 flex items-center justify-center shadow-lg shadow-cyan-500/30 group hover:shadow-cyan-500/50 transition-all">
                <KeyRound className="h-5 w-5 text-cyan-300 group-hover:text-emerald-300 transition-colors" />
              </div>
              <div>
                <h2 className="text-2xl font-extrabold text-white leading-tight">Login</h2>
                <p className="text-sm text-slate-300">Access your trading dashboard</p>
              </div>
            </div>

            <form onSubmit={handleLogin} className="space-y-6">
              <div>
                <label className="block text-sm font-medium text-slate-200 mb-2.5">Username</label>
                <div className="relative group">
                  <User className={`pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 transition-colors ${
                    focusedField === 'username' ? 'text-emerald-300' : 'text-slate-500'
                  }`} />
                  <input
                    type="text"
                    value={username}
                    onChange={(e) => handleFieldChange('username', e.target.value)}
                    onFocus={() => setFocusedField('username')}
                    onBlur={() => setFocusedField(null)}
                    placeholder="Enter username"
                    autoComplete="username"
                    disabled={isChecking}
                    className={`w-full rounded-xl border bg-slate-900/65 pl-11 pr-3 py-3.5 text-slate-100 placeholder:text-slate-500 transition-all duration-200 ${
                      focusedField === 'username'
                        ? 'border-emerald-400/80 bg-slate-900/80 shadow-[0_0_20px_rgba(16,185,129,0.35),inset_0_1px_2px_rgba(16,185,129,0.1)]'
                        : 'border-slate-700/70 shadow-[inset_0_1px_2px_rgba(0,0,0,0.3)] hover:border-slate-600/90'
                    } ${isError ? 'border-red-500/60 shadow-[0_0_16px_rgba(239,68,68,0.25)]' : ''}`}
                  />
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-2.5">
                  <label className="block text-sm font-medium text-slate-200">Password</label>
                  <button
                    type="button"
                    onClick={() => navigate('/forgot-password')}
                    className="text-xs text-emerald-400 hover:text-emerald-300 font-medium transition-colors duration-200"
                  >
                    Forgot?
                  </button>
                </div>
                <div className="relative group">
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => handleFieldChange('password', e.target.value)}
                    onFocus={() => setFocusedField('password')}
                    onBlur={() => setFocusedField(null)}
                    placeholder="Enter password"
                    autoComplete="current-password"
                    disabled={isChecking}
                    className={`w-full rounded-xl border bg-slate-900/65 pl-3 pr-11 py-3.5 text-slate-100 placeholder:text-slate-500 transition-all duration-200 ${
                      focusedField === 'password'
                        ? 'border-emerald-400/80 bg-slate-900/80 shadow-[0_0_20px_rgba(16,185,129,0.35),inset_0_1px_2px_rgba(16,185,129,0.1)]'
                        : 'border-slate-700/70 shadow-[inset_0_1px_2px_rgba(0,0,0,0.3)] hover:border-slate-600/90'
                    } ${isError ? 'border-red-500/60 shadow-[0_0_16px_rgba(239,68,68,0.25)]' : ''}`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    disabled={isChecking}
                    className={`absolute right-3.5 top-1/2 -translate-y-1/2 transition-all duration-200 ${
                      focusedField === 'password' ? 'text-emerald-300' : 'text-slate-500 hover:text-slate-300'
                    } disabled:opacity-50`}
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>

              <div className="flex items-center gap-3 pt-1">
                <label className="flex items-center cursor-pointer group">
                  <input
                    type="checkbox"
                    checked={rememberMe}
                    onChange={(e) => setRememberMe(e.target.checked)}
                    disabled={isChecking}
                    className="w-4 h-4 rounded border-emerald-500/60 bg-slate-900/50 accent-emerald-400 cursor-pointer disabled:opacity-50 transition-colors"
                  />
                  <span className="ml-2.5 text-sm text-slate-300 group-hover:text-slate-100 transition-colors">
                    Remember this device
                  </span>
                </label>
              </div>

              {isError && (
                <div className="rounded-xl border border-red-400/50 bg-red-500/12 px-4 py-3 text-sm text-red-200 flex items-start gap-3 animate-in fade-in slide-in-from-top-2">
                  <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" />
                  <span>{error || 'Invalid credentials. Please try again.'}</span>
                </div>
              )}

              <button
                type="submit"
                disabled={isChecking || !username.trim() || !password}
                className={`w-full py-3.5 rounded-xl font-bold text-base flex items-center justify-center gap-2 transition-all duration-300 group relative overflow-hidden ${
                  isChecking || !username.trim() || !password
                    ? 'bg-slate-700/50 text-slate-400 cursor-not-allowed'
                    : 'border border-emerald-400/20 bg-gradient-to-r from-emerald-500 via-cyan-500 to-emerald-600 text-white shadow-[0_10px_24px_rgba(16,185,129,0.25)] hover:-translate-y-0.5 hover:shadow-[0_0_40px_rgba(16,185,129,0.4),0_12px_24px_rgba(16,185,129,0.3)] active:translate-y-0.5 active:scale-[0.98]'
                }`}
              >
                {isChecking ? (
                  <>
                    <Loader className="h-4 w-4 animate-spin" />
                    Signing in...
                  </>
                ) : (
                  <>
                    Sign In
                    <ArrowRight className="h-4 w-4 group-hover:translate-x-1 transition-transform" />
                  </>
                )}
              </button>
            </form>

            <div className="mt-8 pt-6 border-t border-slate-700/50">
              <div className="grid grid-cols-3 gap-3 mb-6">
                <div className="text-center group relative" title="Your session uses industry-standard JWT for security">
                  <div className="inline-flex items-center justify-center h-9 w-9 rounded-lg bg-cyan-500/20 border border-cyan-500/50 group-hover:border-cyan-400/80 group-hover:bg-cyan-500/30 group-hover:shadow-[0_0_12px_rgba(34,211,238,0.4)] transition-all mb-2">
                    <Lock className="h-4 w-4 text-cyan-300" />
                  </div>
                  <p className="text-xs text-slate-400 font-semibold">Secure JWT</p>
                </div>
                <div className="text-center group relative" title="All communication is encrypted end-to-end">
                  <div className="inline-flex items-center justify-center h-9 w-9 rounded-lg bg-emerald-500/20 border border-emerald-500/50 group-hover:border-emerald-400/80 group-hover:bg-emerald-500/30 group-hover:shadow-[0_0_12px_rgba(16,185,129,0.4)] transition-all mb-2">
                    <CheckCircle className="h-4 w-4 text-emerald-300" />
                  </div>
                  <p className="text-xs text-slate-400 font-semibold">Encrypted</p>
                </div>
                <div className="text-center group relative" title="Real-time connection to live trading infrastructure">
                  <div className="inline-flex items-center justify-center h-9 w-9 rounded-lg bg-blue-500/20 border border-blue-500/50 group-hover:border-blue-400/80 group-hover:bg-blue-500/30 group-hover:shadow-[0_0_12px_rgba(59,130,246,0.4)] transition-all mb-2">
                    <Activity className="h-4 w-4 text-blue-300" />
                  </div>
                  <p className="text-xs text-slate-400 font-semibold">Live API</p>
                </div>
              </div>

              <button
                type="button"
                onClick={() => navigate('/')}
                className="hidden w-full py-2 text-sm font-medium text-slate-400 transition-colors hover:text-cyan-300 sm:block"
              >
                ← Back to landing page
              </button>
            </div>

            <div className="mt-6 pt-5 border-t border-slate-700/40 flex items-center justify-between text-xs text-slate-500">
              <span className="inline-flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                System Ready
              </span>
              <span className="inline-flex items-center gap-1.5">
                <TrendingUp className="h-3.5 w-3.5" />
                Live Trading Mode
              </span>
            </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};

export default Login;
