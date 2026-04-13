import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Mail, AlertTriangle, CheckCircle } from 'lucide-react';
import '../styles/immersive-pages.css';

const ForgotPassword = () => {
  const [email, setEmail] = useState('');
  const [isSubmitted, setIsSubmitted] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [focusedField, setFocusedField] = useState(null);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsLoading(true);
    
    // Simulate API call
    await new Promise(resolve => setTimeout(resolve, 2000));
    
    setIsSubmitted(true);
    setIsLoading(false);
  };

  return (
    <div className="login-3d-page min-h-screen text-slate-100 relative overflow-hidden">
      <div className="absolute inset-0 animate-gradient-slow opacity-30" style={{
        background: 'linear-gradient(-45deg, #00d4ff, #0099ff, #6366f1, #00d4ff)',
        backgroundSize: '400% 400%',
      }} aria-hidden="true" />
      
      <div className="login-grid-overlay" aria-hidden="true" />
      <div className="login-light-a" aria-hidden="true" />
      <div className="login-light-b" aria-hidden="true" />

      <div className="relative min-h-screen flex items-center justify-center p-6 sm:p-10">
        <div className="auth-form-shell w-full max-w-md rounded-3xl p-7 sm:p-9 backdrop-blur-lg border border-cyan-500/20 shadow-2xl shadow-cyan-500/10">
          {!isSubmitted ? (
            <>
              <div className="flex items-center gap-3 mb-8">
                <div className="h-11 w-11 rounded-2xl bg-gradient-to-br from-cyan-500/30 to-blue-500/30 border border-cyan-400/50 flex items-center justify-center shadow-lg shadow-cyan-500/20">
                  <Mail className="h-5 w-5 text-cyan-300" />
                </div>
                <div>
                  <h2 className="text-2xl font-extrabold text-white">Reset Password</h2>
                  <p className="text-sm text-slate-300">Enter your email to receive reset instructions</p>
                </div>
              </div>

              <form onSubmit={handleSubmit} className="space-y-5">
                <div>
                  <label className="block text-sm font-medium text-slate-200 mb-2.5">Email Address</label>
                  <div className="input-3d-wrap group">
                    <Mail className={`pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 transition-colors ${
                      focusedField === 'email' ? 'text-cyan-300' : 'text-slate-500'
                    }`} />
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      onFocus={() => setFocusedField('email')}
                      onBlur={() => setFocusedField(null)}
                      placeholder="admin@stockai.com"
                      disabled={isLoading}
                      className={`auth-input w-full pl-11 pr-3 py-3 bg-slate-900/50 border transition-all duration-200 ${
                        focusedField === 'email'
                          ? 'border-cyan-400/60 shadow-[0_0_16px_rgba(34,211,238,0.3)] bg-slate-900/70'
                          : 'border-slate-700/60 hover:border-slate-600/80'
                      }`}
                      required
                    />
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={isLoading || !email}
                  className={`w-full py-3.5 rounded-xl font-bold text-base flex items-center justify-center gap-2 transition-all duration-300 group relative overflow-hidden ${
                    isLoading || !email
                      ? 'bg-slate-700/40 text-slate-400 cursor-not-allowed'
                      : 'bg-gradient-to-r from-cyan-500 to-blue-600 text-white hover:shadow-[0_16px_32px_rgba(34,211,238,0.4)] hover:scale-[1.01] active:scale-[0.99]'
                  }`}
                >
                  {isLoading ? 'Sending...' : 'Send Reset Link'}
                </button>
              </form>

              <div className="mt-6 pt-6 border-t border-slate-700/50">
                <button
                  type="button"
                  onClick={() => navigate('/login')}
                  className="w-full flex items-center justify-center gap-2 text-sm text-slate-300 hover:text-cyan-300 font-medium transition-colors py-2"
                >
                  <ArrowLeft className="h-4 w-4" />
                  Back to login
                </button>
              </div>
            </>
          ) : (
            <div className="text-center">
              <div className="mb-6 flex items-center justify-center">
                <div className="h-14 w-14 rounded-2xl bg-gradient-to-br from-emerald-500/30 to-cyan-500/30 border border-emerald-400/50 flex items-center justify-center shadow-lg shadow-emerald-500/20">
                  <CheckCircle className="h-7 w-7 text-emerald-300" />
                </div>
              </div>
              
              <h3 className="text-xl font-bold text-white mb-2">Check Your Email</h3>
              <p className="text-slate-300 text-sm mb-6">
                We've sent a password reset link to <span className="text-cyan-300 font-medium">{email}</span>
              </p>
              
              <p className="text-slate-400 text-xs mb-8">
                The link expires in 24 hours. Please check your spam folder if you don't see it.
              </p>

              <button
                type="button"
                onClick={() => navigate('/login')}
                className="w-full py-3.5 rounded-xl font-bold text-base bg-gradient-to-r from-cyan-500 to-blue-600 text-white hover:shadow-[0_16px_32px_rgba(34,211,238,0.4)] transition-all"
              >
                Return to Login
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ForgotPassword;
