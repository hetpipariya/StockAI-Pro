import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

const API_BASE = '/api/v1'
const RR_PRESETS = [
  { label: '1:1', rr: 1 },
  { label: '1:2', rr: 2 },
  { label: '1:3', rr: 3 },
]

export default function OrderEntry({ symbol, snapshot }) {
  const [qty, setQty] = useState(1)
  const [orderType, setOrderType] = useState('MARKET')
  const [price, setPrice] = useState('')
  const [sl, setSl] = useState('')
  const [target, setTarget] = useState('')
  const [mode, setMode] = useState('paper')
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState('')
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [confirmSide, setConfirmSide] = useState(null)

  const ltp = snapshot?.ltp || 0

  const placeOrder = async (side) => {
    setConfirmOpen(false)
    setConfirmSide(null)
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
          ordertype: orderType,
          price: orderType === 'LIMIT' ? parseFloat(price) : null,
          mode,
        }),
      })
      const data = await res.json()
      setMsg(data.message || (data.status ? 'Order sent' : data.errorcode || 'Error'))
    } catch (e) {
      setMsg('Request failed')
    }
    setLoading(false)
  }

  const applyRR = (rr) => {
    const entry = ltp || parseFloat(price) || 0
    if (!entry) return
    setSl((entry * 0.99).toFixed(2))
    setTarget((entry * (1 + 0.01 * rr)).toFixed(2))
  }

  const openConfirm = (side) => {
    setConfirmSide(side)
    setConfirmOpen(true)
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl border border-white/5 bg-white/[0.02] backdrop-blur-sm p-4"
    >
      <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-3 font-mono">Order Entry</h3>
      <div className="flex gap-2 mb-3">
        <button
          onClick={() => setOrderType('MARKET')}
          className={`flex-1 py-2.5 rounded-xl text-sm font-mono transition
            ${orderType === 'MARKET' ? 'bg-teal-500/20 text-teal-400 border border-teal-500/40' : 'border border-white/10 text-slate-500 hover:text-slate-300'}`}
        >
          Market
        </button>
        <button
          onClick={() => setOrderType('LIMIT')}
          className={`flex-1 py-2.5 rounded-xl text-sm font-mono transition
            ${orderType === 'LIMIT' ? 'bg-teal-500/20 text-teal-400 border border-teal-500/40' : 'border border-white/10 text-slate-500 hover:text-slate-300'}`}
        >
          Limit
        </button>
      </div>
      {orderType === 'LIMIT' && (
        <input
          type="number"
          placeholder={`Price (LTP ₹${ltp.toFixed(2)})`}
          value={price}
          onChange={(e) => setPrice(e.target.value)}
          className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 font-mono text-sm mb-3 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-teal-500/50"
        />
      )}
      <input
        type="number"
        min={1}
        value={qty}
        onChange={(e) => setQty(parseInt(e.target.value) || 1)}
        placeholder="Quantity"
        className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 font-mono text-sm mb-3 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-teal-500/50"
      />
      <div className="grid grid-cols-2 gap-2 mb-3">
        <div>
          <label className="text-xs text-slate-500 block mb-1">Stop Loss</label>
          <input
            type="number"
            placeholder="Optional"
            value={sl}
            onChange={(e) => setSl(e.target.value)}
            className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 font-mono text-sm text-slate-200 placeholder-slate-600"
          />
        </div>
        <div>
          <label className="text-xs text-slate-500 block mb-1">Target</label>
          <input
            type="number"
            placeholder="Optional"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 font-mono text-sm text-slate-200 placeholder-slate-600"
          />
        </div>
      </div>
      <div className="flex gap-2 mb-3">
        <span className="text-xs text-slate-500 self-center">R:R</span>
        {RR_PRESETS.map((p) => (
          <button
            key={p.label}
            onClick={() => applyRR(p.rr)}
            className="px-3 py-1.5 rounded-lg text-xs font-mono border border-white/10 text-slate-400 hover:text-teal-400 hover:border-teal-500/30"
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className="flex gap-4 mb-3">
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input type="radio" name="mode" checked={mode === 'paper'} onChange={() => setMode('paper')} className="accent-teal-500" />
          <span className="text-slate-400">Paper</span>
        </label>
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input type="radio" name="mode" checked={mode === 'live'} onChange={() => setMode('live')} className="accent-teal-500" />
          <span className="text-slate-400">Live</span>
        </label>
      </div>
      <div className="flex gap-2">
        <motion.button
          onClick={() => openConfirm('BUY')}
          disabled={loading}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className="flex-1 py-3.5 rounded-xl font-mono font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 hover:bg-emerald-500/30 disabled:opacity-50 transition"
        >
          BUY
        </motion.button>
        <motion.button
          onClick={() => openConfirm('SELL')}
          disabled={loading}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className="flex-1 py-3.5 rounded-xl font-mono font-bold bg-red-500/20 text-red-400 border border-red-500/40 hover:bg-red-500/30 disabled:opacity-50 transition"
        >
          SELL
        </motion.button>
      </div>
      {msg && <p className="text-sm text-slate-400 mt-3 font-mono">{msg}</p>}

      <AnimatePresence>
        {confirmOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setConfirmOpen(false)}
              className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40"
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[min(360px,90vw)] rounded-2xl bg-slate-900/95 border border-white/10 p-6 z-50 shadow-2xl"
            >
              <h4 className="text-lg font-mono font-semibold text-slate-200 mb-4">Confirm Order</h4>
              <div className="space-y-2 text-sm font-mono text-slate-400 mb-6">
                <p><span className="text-slate-500">Symbol:</span> {symbol}</p>
                <p><span className="text-slate-500">Side:</span> <span className={confirmSide === 'BUY' ? 'text-emerald-400' : 'text-red-400'}>{confirmSide}</span></p>
                <p><span className="text-slate-500">Qty:</span> {qty}</p>
                <p><span className="text-slate-500">Type:</span> {orderType}</p>
                {orderType === 'LIMIT' && price && <p><span className="text-slate-500">Price:</span> ₹{price}</p>}
                {sl && <p><span className="text-slate-500">SL:</span> ₹{sl}</p>}
                {target && <p><span className="text-slate-500">Target:</span> ₹{target}</p>}
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() => setConfirmOpen(false)}
                  className="flex-1 py-3 rounded-xl font-mono font-semibold border border-white/10 text-slate-400 hover:bg-white/5"
                >
                  Cancel
                </button>
                <button
                  onClick={() => placeOrder(confirmSide)}
                  className={`flex-1 py-3 rounded-xl font-mono font-bold ${confirmSide === 'BUY' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40' : 'bg-red-500/20 text-red-400 border border-red-500/40'}`}
                >
                  Confirm {confirmSide}
                </button>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
