import { useState } from 'react'
import { motion } from 'framer-motion'
import { useAuth } from '../../context/AuthContext'

export default function LoginPage() {
  const { login, signup } = useAuth()
  const [isLogin, setIsLogin] = useState(true)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      if (isLogin) {
        await login(username, password)
      } else {
        await signup(username, password)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen w-full bg-[#0b0f14] flex items-center justify-center p-4">
      {/* Background decoration */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-[20%] -left-[10%] w-[50%] h-[50%] bg-teal-500/10 blur-[120px] rounded-full" />
        <div className="absolute -bottom-[20%] -right-[10%] w-[50%] h-[50%] bg-emerald-500/10 blur-[120px] rounded-full" />
      </div>

      <motion.div 
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-full max-w-md bg-white/[0.02] border border-white/10 rounded-2xl p-8 backdrop-blur-xl relative z-10 shadow-2xl"
      >
        <div className="text-center mb-8">
          <h1 className="text-2xl font-mono font-bold text-teal-400 mb-2">StockAI Pro</h1>
          <p className="text-slate-400 text-sm">Quant Trading Engine</p>
        </div>

        {error && (
          <div className="mb-6 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm text-center">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs uppercase tracking-wider text-slate-500 font-mono mb-1.5">Username</label>
            <input 
              type="text" 
              required
              minLength={3}
              value={username}
              onChange={e => setUsername(e.target.value)}
              className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 text-slate-200 outline-none focus:border-teal-500/50 transition-colors"
              placeholder="Trader ID"
            />
          </div>
          
          <div>
            <label className="block text-xs uppercase tracking-wider text-slate-500 font-mono mb-1.5">Password</label>
            <input 
              type="password"
              required 
              minLength={6}
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 text-slate-200 outline-none focus:border-teal-500/50 transition-colors"
              placeholder="••••••••"
            />
          </div>

          <button 
            type="submit" 
            disabled={loading}
            className="w-full bg-teal-500/20 hover:bg-teal-500/30 border border-teal-500/50 text-teal-400 font-mono font-bold py-3 rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed mt-4"
          >
            {loading ? 'Authenticating...' : (isLogin ? 'Initialize Session' : 'Register Terminal')}
          </button>
        </form>

        <div className="mt-6 text-center">
          <button 
            type="button"
            onClick={() => { setIsLogin(!isLogin); setError(''); }}
            className="text-sm text-slate-500 hover:text-slate-300 transition-colors"
          >
            {isLogin ? "Need access? Request registration" : "Have access? Initialize session"}
          </button>
        </div>
      </motion.div>
    </div>
  )
}
