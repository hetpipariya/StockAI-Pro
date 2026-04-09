import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/useAuthStore';
import { Lock, Activity, Sparkles, ChevronRight, AlertTriangle } from 'lucide-react';

const Login = () => {
  const [password, setPassword] = useState('');
  const [isError, setIsError] = useState(false);
  const [isChecking, setIsChecking] = useState(false);
  
  const login = useAuthStore((state) => state.login);
  const error = useAuthStore((state) => state.error);
  const navigate = useNavigate();

  const handleLogin = async (e) => {
    e.preventDefault();
    if (!password) return;
    
    setIsChecking(true);
    setIsError(false);

    // Call the actual backend via the Zustand store
    const success = await login(password);
    
    if (success) {
      navigate('/dashboard');
    } else {
      setIsError(true);
      setIsChecking(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#06090E] text-white flex items-center justify-center relative overflow-hidden">
      {/* Background Live Signals effect */}
      <div className="absolute inset-0 z-0 flex whitespace-nowrap opacity-10 pointer-events-none">
        {[...Array(40)].map((_, i) => (
          <motion.div 
             key={i} 
             className="text-4xl font-mono px-4 text-stockai-neon"
             initial={{ y: "100vh" }}
             animate={{ y: "-100vh" }}
             transition={{ duration: 10 + Math.random() * 20, repeat: Infinity, ease: 'linear' }}
          >
             {Math.random() > 0.5 ? 'BUY RELIANCE' : 'SELL INFY'}
          </motion.div>
        ))}
      </div>

      <motion.div 
        className="z-10 bg-stockai-card/80 backdrop-blur-2xl p-12 rounded-3xl border border-white/5 shadow-2xl w-full max-w-md relative"
        initial={{ opacity: 0, scale: 0.9, y: 30 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 200, damping: 20 }}
      >
        {/* Glow behind card */}
        <div className="absolute -inset-1 rounded-3xl bg-gradient-to-br from-stockai-neon/20 to-[#06090E] opacity-50 blur-xl pointer-events-none" />
        
        <div className="relative text-center mb-10">
          <motion.div 
            className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-stockai-surface border border-white/10 shadow-glow mb-6"
            animate={{ rotate: 360 }}
            transition={{ duration: 20, repeat: Infinity, ease: "linear" }}
          >
            <Lock className="w-10 h-10 text-stockai-neon" />
          </motion.div>
          
          <h1 className="text-4xl font-extrabold tracking-tight">StockAI<span className="text-stockai-neon text-glow">Pro</span></h1>
          <p className="text-stockai-muted mt-2 font-mono text-sm uppercase tracking-widest"><Sparkles className="inline w-3 h-3 mr-1" /> Terminal Access</p>
        </div>

        <form onSubmit={handleLogin} className="relative z-10 space-y-6">
          <div className="relative">
            <input 
              type="password" 
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                setIsError(false);
              }}
              placeholder="Enter Master Password"
              className="w-full bg-stockai-bg border border-white/10 rounded-xl px-5 py-5 text-lg font-mono tracking-[0.3em] text-center focus:outline-none focus:border-stockai-neon focus:ring-1 focus:ring-stockai-neon transition-all"
            />
            {isError && (
              <motion.div 
                initial={{ opacity: 0, y: -10 }} 
                animate={{ opacity: 1, y: 0 }} 
                className="absolute -bottom-8 left-0 right-0 flex items-center justify-center text-stockai-sell text-sm font-semibold gap-1"
              >
                <AlertTriangle className="w-4 h-4" /> Auth Denied
              </motion.div>
            )}
          </div>

          <button 
            type="submit" 
            disabled={isChecking || !password}
            className={`w-full py-5 rounded-xl font-bold text-lg flex items-center justify-center transition-all ${isChecking || !password ? 'bg-stockai-muted/20 text-stockai-muted cursor-not-allowed' : 'bg-stockai-neon text-black hover:shadow-glow hover:scale-[1.02]'}`}
          >
            {isChecking ? (
              <Activity className="w-6 h-6 animate-pulse" />
            ) : (
              <>Initialize <ChevronRight className="w-5 h-5 ml-1" /></>
            )}
          </button>
        </form>

      </motion.div>
    </div>
  );
};

export default Login;
