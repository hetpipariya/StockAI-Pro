import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api/v1` : '/api/v1'

export default function SentimentPanel({ symbol }) {
  const [data, setData] = useState({ fear_greed: 50, label: 'Neutral' })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!symbol) return
    let isMounted = true

    const fetchSentiment = async () => {
      setLoading(true)
      try {
        const res = await fetch(`${API_BASE}/sentiment?symbol=${symbol}`)
        if (!res.ok) throw new Error()
        const result = await res.json()
        if (isMounted) setData(result)
      } catch {
        if (isMounted) setData({ fear_greed: 50, label: 'Neutral' })
      } finally {
        if (isMounted) setLoading(false)
      }
    }

    fetchSentiment()
    return () => { isMounted = false }
  }, [symbol])

  const fearGreed = data.fear_greed
  const label = data.label
  const color = fearGreed >= 65 ? 'emerald' : fearGreed <= 35 ? 'red' : 'amber'

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl border border-white/5 bg-white/[0.02] backdrop-blur-sm p-4"
    >
      <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-3 font-mono">Sentiment</h3>
      <div className="flex items-center gap-4">
        <div className="flex-1">
          <p className="text-sm text-slate-400 mb-2">Fear & Greed</p>
          <div className="h-3 rounded-full bg-slate-800 overflow-hidden">
            <motion.div
              className={`h-full rounded-full ${color === 'emerald' ? 'bg-emerald-500' : color === 'amber' ? 'bg-amber-500' : 'bg-red-500'}`}
              initial={{ width: 0 }}
              animate={{ width: `${fearGreed}%` }}
              transition={{ duration: 0.5 }}
            />
          </div>
          <p className={`text-sm font-mono font-semibold mt-2 ${color === 'emerald' ? 'text-emerald-400' : color === 'amber' ? 'text-amber-400' : 'text-red-400'}`}>
            {label} ({fearGreed})
          </p>
        </div>
      </div>
    </motion.div>
  )
}
