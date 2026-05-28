import React, { useMemo, useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/useAuthStore';
import {
  AlertTriangle,
  ArrowRight,
  Eye,
  EyeOff,
  Lock,
  ShieldCheck,
  User,
  Activity,
  Command,
} from 'lucide-react';

export default function Login() {
  const navigate = useNavigate();
  const login = useAuthStore((state) => state.login);
  const error = useAuthStore((state) => state.error);
  const clearError = useAuthStore((state) => state.clearError);

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [rememberMe, setRememberMe] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    // Clear login errors on mount
    clearError();
    // Retrieve remembered email
    const savedEmail = localStorage.getItem('stockai_remembered_email');
    if (savedEmail) {
      setEmail(savedEmail);
      setRememberMe(true);
    }
  }, [clearError]);

  const disabled = useMemo(() => !email.trim() || !password || submitting, [email, password, submitting]);

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (disabled) return;
    setSubmitting(true);
    clearError();
    
    const success = await login({ email: email.trim().toLowerCase(), password });
    setSubmitting(false);
    if (success) {
      if (rememberMe) {
        localStorage.setItem('stockai_remembered_email', email.trim().toLowerCase());
      } else {
        localStorage.removeItem('stockai_remembered_email');
      }
      navigate('/dashboard');
    }
  };

  return (
    <div className="min-h-screen w-full relative flex items-center justify-center bg-[#050816] text-slate-100 overflow-hidden font-sans select-none">
      
      {/* Dynamic Moving Background Grid */}
      <div className="absolute inset-0 z-0 pointer-events-none opacity-20">
        <div 
          className="w-full h-full bg-[linear-gradient(rgba(0,245,255,0.06)_1px,transparent_1px),linear-gradient(90deg,rgba(0,245,255,0.06)_1px,transparent_1px)] bg-[size:40px_40px] animate-matrix-move"
          style={{
            animation: 'gridMove 30s linear infinite',
          }}
        />
      </div>

      {/* Styled global grid movement in case stylesheet is not yet loaded */}
      <style>{`
        @keyframes gridMove {
          0% { background-position: 0 0; }
          100% { background-position: 40px 40px; }
        }
        @keyframes chartPulse {
          0%, 100% { opacity: 0.1; transform: scale(1); }
          50% { opacity: 0.25; transform: scale(1.02); }
        }
      `}</style>

      {/* Subtle Market Chart Motion in Background */}
      <div 
        className="absolute inset-0 z-0 pointer-events-none flex items-center justify-center opacity-15"
        style={{
          animation: 'chartPulse 8s ease-in-out infinite',
        }}
      >
        <svg width="80%" height="40%" viewBox="0 0 1000 400" fill="none" xmlns="http://www.w3.org/2000/svg" className="text-cyan-400">
          <path d="M0,350 L100,280 L200,320 L300,180 L400,240 L500,120 L600,260 L700,90 L800,160 L900,40 L1000,150" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M0,350 L100,280 L200,320 L300,180 L400,240 L500,120 L600,260 L700,90 L800,160 L900,40 L1000,150 L1000,400 L0,400 Z" fill="url(#bg-gradient)" opacity="0.08" />
          <defs>
            <linearGradient id="bg-gradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#00F5FF" />
              <stop offset="100%" stopColor="transparent" />
            </linearGradient>
          </defs>
        </svg>
      </div>

      {/* Soft Purple Accents & Glow Overlays */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 rounded-full bg-[#8B5CF6]/8 blur-[120px] pointer-events-none" />
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 rounded-full bg-[#00F5FF]/8 blur-[120px] pointer-events-none" />

      {/* Centered Glassmorphism Login Container */}
      <div className="relative z-10 w-full max-w-[440px] px-4">
        
        {/* Logo and Branding header */}
        <div className="flex flex-col items-center mb-6 text-center">
          <div className="h-12 w-12 rounded-2xl border border-cyan-400/40 bg-cyan-500/10 flex items-center justify-center shadow-[0_0_20px_rgba(0,245,255,0.15)] mb-3">
            <Command className="h-6 w-6 text-cyan-300" />
          </div>
          <h2 className="text-xl font-bold tracking-tight text-white">StockAI Pro</h2>
          <p className="text-xs tracking-wider text-slate-500 uppercase mt-1">Institutional Desk Login</p>
        </div>

        {/* Form panel with custom neon glow */}
        <form 
          onSubmit={handleSubmit} 
          className="w-full rounded-2xl border border-white/8 bg-[#0C1220]/75 p-8 backdrop-blur-[24px] shadow-[0_16px_50px_rgba(0,0,0,0.55)] transition-all hover:border-cyan-400/40 hover:shadow-[0_0_35px_rgba(0,245,255,0.06)]"
        >
          <div className="flex items-center justify-between mb-6">
            <div>
              <p className="text-xs uppercase tracking-[0.16em] text-slate-400 font-semibold">Security Gate</p>
              <h3 className="mt-1 text-2xl font-black text-white">Sign In</h3>
            </div>
            <div className="px-2.5 py-1 rounded-full border border-cyan-500/30 bg-cyan-500/10 text-[10px] text-cyan-300 font-bold uppercase tracking-widest flex items-center gap-1.5">
              <Activity className="h-3 w-3 animate-pulse" /> Live API
            </div>
          </div>

          <div className="space-y-4">
            
            {/* Email Field */}
            <label className="block">
              <span className="text-[11px] uppercase tracking-[0.14em] text-slate-400 font-semibold">Email Desk</span>
              <div className="mt-2 relative">
                <User className="h-4 w-4 text-slate-500 absolute left-3.5 top-1/2 -translate-y-1/2" />
                <input
                  type="email"
                  value={email}
                  onChange={(event) => {
                    setEmail(event.target.value);
                    clearError();
                  }}
                  className="w-full rounded-xl border border-white/10 bg-[#060A14] pl-11 pr-4 py-3 text-[13px] text-slate-200 placeholder:text-slate-600 outline-none focus:border-cyan-400 focus:shadow-[0_0_15px_rgba(0,245,255,0.15)] transition-all font-mono"
                  placeholder="name@desk.com"
                  autoComplete="email"
                  required
                />
              </div>
            </label>

            {/* Password Field */}
            <label className="block">
              <span className="text-[11px] uppercase tracking-[0.14em] text-slate-400 font-semibold">Access Key</span>
              <div className="mt-2 relative">
                <Lock className="h-4 w-4 text-slate-500 absolute left-3.5 top-1/2 -translate-y-1/2" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(event) => {
                    setPassword(event.target.value);
                    clearError();
                  }}
                  className="w-full rounded-xl border border-white/10 bg-[#060A14] pl-11 pr-11 py-3 text-[13px] text-slate-200 placeholder:text-slate-600 outline-none focus:border-cyan-400 focus:shadow-[0_0_15px_rgba(0,245,255,0.15)] transition-all"
                  placeholder="••••••••••••"
                  autoComplete="current-password"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((state) => !state)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-cyan-300 transition-colors"
                  aria-label={showPassword ? 'Hide key' : 'Show key'}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </label>

            {/* Remember Me checkbox */}
            <div className="flex items-center justify-between text-xs pt-1">
              <label className="flex items-center gap-2 cursor-pointer text-slate-400 hover:text-slate-300 select-none">
                <input
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                  className="rounded border-white/10 bg-slate-900 text-cyan-400 focus:ring-cyan-400/40 w-3.5 h-3.5"
                />
                <span>Remember email</span>
              </label>
              <button 
                type="button" 
                onClick={() => navigate('/forgot-password')} 
                className="text-slate-500 hover:text-cyan-300 transition-colors"
              >
                Forgot key?
              </button>
            </div>

            {/* Security Alerts */}
            {error ? (
              <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2.5 text-xs text-rose-300 flex items-start gap-2 animate-shake">
                <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            ) : (
              <div className="rounded-xl border border-emerald-500/15 bg-emerald-500/5 px-3 py-2 text-[10px] text-emerald-400 flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 shrink-0 text-emerald-400" />
                <span>Airtight JWT signature validation active.</span>
              </div>
            )}

            {/* Action button */}
            <button
              type="submit"
              disabled={disabled}
              className={`w-full rounded-xl py-3.5 font-bold flex items-center justify-center gap-2 transition-all ${disabled
                ? 'bg-slate-800/40 text-slate-600 cursor-not-allowed border border-white/5'
                : 'bg-gradient-to-r from-cyan-500 to-emerald-500 text-[#041019] hover:opacity-95 hover:scale-[1.01] active:scale-[0.99] shadow-[0_4px_20px_rgba(0,245,255,0.2)]'}`}
            >
              {submitting ? 'Authenticating Desk...' : 'Access Terminal'}
              {!submitting ? <ArrowRight className="h-4 w-4" /> : null}
            </button>

            {/* Alternate page routing */}
            <div className="flex items-center justify-center gap-2 text-xs pt-2">
              <span className="text-slate-500">Need access?</span>
              <button 
                type="button" 
                onClick={() => navigate('/signup')} 
                className="text-cyan-400 hover:text-cyan-300 font-semibold transition-colors"
              >
                Create Account
              </button>
            </div>

            <button 
              type="button" 
              onClick={() => navigate('/')} 
              className="w-full text-center text-[10px] text-slate-600 hover:text-slate-400 transition-colors pt-2"
            >
              Back to Landing
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
