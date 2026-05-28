import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, CheckCircle2, Mail, Send } from 'lucide-react';

export default function ForgotPassword() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [isSubmitted, setIsSubmitted] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!email.trim()) return;
    setIsLoading(true);
    await new Promise((resolve) => setTimeout(resolve, 1600));
    setIsSubmitted(true);
    setIsLoading(false);
  };

  return (
    <div className="min-h-screen bg-[#040A16] text-slate-100 overflow-hidden">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_16%_0%,rgba(34,211,238,0.2),transparent_34%),radial-gradient(circle_at_82%_14%,rgba(16,185,129,0.16),transparent_36%)]" />

      <div className="relative min-h-screen flex items-center justify-center p-5 sm:p-8">
        <div className="w-full max-w-md rounded-3xl border border-white/10 bg-[#081627]/85 p-7 sm:p-8 backdrop-blur-xl shadow-[0_24px_65px_rgba(0,0,0,0.45)]">
          {!isSubmitted ? (
            <>
              <div className="flex items-center gap-3 mb-7">
                <div className="h-11 w-11 rounded-2xl border border-cyan-500/40 bg-cyan-500/10 flex items-center justify-center">
                  <Mail className="h-5 w-5 text-cyan-300" />
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-400 font-bold">Recovery</p>
                  <h1 className="mt-1 text-2xl font-black text-white">Reset Password</h1>
                </div>
              </div>

              <p className="text-sm text-slate-300 mb-5 leading-relaxed">
                Provide your registered email and we will send secure reset instructions.
              </p>

              <form onSubmit={handleSubmit} className="space-y-4">
                <label className="block">
                  <span className="text-xs uppercase tracking-[0.14em] text-slate-400 font-semibold">Email</span>
                  <input
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    className="mt-2 w-full rounded-xl border border-white/10 bg-[#0A1A30] px-3 py-3 text-slate-100 placeholder:text-slate-500 outline-none focus:border-cyan-400/70 focus:shadow-[0_0_0_3px_rgba(34,211,238,0.15)]"
                    placeholder="you@desk.com"
                    autoComplete="email"
                    required
                  />
                </label>

                <button
                  type="submit"
                  disabled={isLoading || !email.trim()}
                  className={`w-full rounded-xl py-3.5 font-bold transition flex items-center justify-center gap-2 ${isLoading || !email.trim()
                    ? 'bg-slate-700/40 text-slate-500 cursor-not-allowed'
                    : 'bg-gradient-to-r from-cyan-500 to-emerald-500 text-[#041019] hover:translate-y-[-1px] shadow-[0_12px_28px_rgba(16,185,129,0.28)]'}`}
                >
                  {isLoading ? 'Sending...' : 'Send Reset Link'}
                  {!isLoading ? <Send className="h-4 w-4" /> : null}
                </button>
              </form>

              <button
                type="button"
                onClick={() => navigate('/login')}
                className="mt-5 w-full text-sm text-slate-400 hover:text-cyan-300 flex items-center justify-center gap-2"
              >
                <ArrowLeft className="h-4 w-4" />
                Back to login
              </button>
            </>
          ) : (
            <div className="text-center">
              <div className="h-14 w-14 rounded-2xl border border-emerald-500/40 bg-emerald-500/10 flex items-center justify-center mx-auto">
                <CheckCircle2 className="h-7 w-7 text-emerald-300" />
              </div>
              <h2 className="mt-5 text-2xl font-black text-white">Email Sent</h2>
              <p className="mt-2 text-sm text-slate-300 leading-relaxed">
                Reset instructions were sent to <span className="text-cyan-300 font-semibold">{email}</span>. Check inbox and spam folder.
              </p>

              <button
                type="button"
                onClick={() => navigate('/login')}
                className="mt-6 w-full rounded-xl py-3.5 font-bold bg-gradient-to-r from-cyan-500 to-emerald-500 text-[#041019]"
              >
                Return to Login
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
