import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

const API_BASE = '/api/v1'

export default function FloatingOrderPanel({ symbol, snapshot, visible, onClose, position }) {
  const [qty, setQty] = useState(1)
  const [side, setSide] = useState('BUY')
  const [sl, setSl] = useState('')
  const [target, setTarget] = useState('')
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState('')
  const ltp = snapshot?.ltp || 2500

  const placeOrder = async () => {
    setLoading(true)
    setMsg('')
    try {
      const res = await fetch(`${API_BASE}/order`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol,
          transactiontype: side,
          quantity: qty,
          ordertype: 'MARKET',
          mode: 'paper',
        }),
      })
      const data = await res.json()
      setMsg(data.message || (data.status ? 'Order sent' : 'Error'))
    } catch (e) {
      setMsg('Request failed')
    }
    setLoading(false)
  }

  const applyPreset = (rr) => {
    const entry = ltp
    setSl((entry * 0.99).toFixed(0))
    setTarget((entry * (1 + 0.01 * rr)).toFixed(0))
  }

  if (!visible) return null

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, scale: 0.9, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.9 }}
        style={position || { top: '50%', right: 24, transform: 'translateY(-50%)' }}
        className="absolute z-40 w-72 rounded-2xl border border-white/10 bg-slate-900/95 backdrop-blur-xl shadow-2xl overflow-hidden"
      >
        <div className="flex justify-between items-center p-3 border-b border-white/5">
          <span className="text-sm font-mono font-semibold text-slate-200">Quick Order</span>
          <button onClick={onClose} className="p-1 rounded text-slate-500 hover:text-white">×</button>
        </div>
        <div className="p-4 space-y-3">
          <div className="flex gap-2">
            <button onClick={() => setSide('BUY')} className={`flex-1 py-2.5 rounded-xl font-mono font-bold transition ${side === 'BUY' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40' : 'bg-white/5 text-slate-500 border border-white/5'}`}>BUY</button>
            <button onClick={() => setSide('SELL')} className={`flex-1 py-2.5 rounded-xl font-mono font-bold transition ${side === 'SELL' ? 'bg-red-500/20 text-red-400 border border-red-500/40' : 'bg-white/5 text-slate-500 border border-white/5'}`}>SELL</button>
          </div>
          <input type="number" min={1} value={qty} onChange={e => setQty(parseInt(e.target.value) || 1)} placeholder="Qty" className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 font-mono text-sm text-slate-200" />
          <div className="flex gap-2">
            {[1, 2, 3].map(rr => <button key={rr} onClick={() => applyPreset(rr)} className="flex-1 py-1.5 rounded-lg text-xs font-mono border border-white/10 text-slate-400 hover:border-teal-500/40">1:{rr}</button>)}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <input type="number" value={sl} onChange={e => setSl(e.target.value)} placeholder="SL" className="px-3 py-2 rounded-lg bg-white/5 border border-white/10 font-mono text-xs text-slate-200" />
            <input type="number" value={target} onChange={e => setTarget(e.target.value)} placeholder="Target" className="px-3 py-2 rounded-lg bg-white/5 border border-white/10 font-mono text-xs text-slate-200" />
          </div>
          <motion.button
            onClick={placeOrder}
            disabled={loading}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            className={`w-full py-3.5 rounded-xl font-mono font-bold ${side === 'BUY' ? 'bg-emerald-500/30 text-emerald-400 border border-emerald-500/50' : 'bg-red-500/30 text-red-400 border border-red-500/50'}`}
          >
            {loading ? '...' : `${side} ${symbol}`}
          </motion.button>
          {msg && <p className="text-xs text-slate-400 font-mono">{msg}</p>}
        </div>
      </motion.div>
    </AnimatePresence>
  )
}
