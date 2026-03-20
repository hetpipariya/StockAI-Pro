import { useState } from 'react'
import { motion } from 'framer-motion'

const STOCKS = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'SBIN']
const MOCK_CORR = [
  [1, 0.2, 0.3, 0.4, 0.1],
  [0.2, 1, 0.6, 0.5, 0.3],
  [0.3, 0.6, 1, 0.4, 0.2],
  [0.4, 0.5, 0.4, 1, 0.7],
  [0.1, 0.3, 0.2, 0.7, 1],
]

export default function CorrelationMatrix() {
  const [hovered, setHovered] = useState(null)

  const getColor = (v) => {
    const abs = Math.abs(v)
    if (v >= 0) return `rgba(16, 185, 129, ${abs * 0.8})`
    return `rgba(239, 68, 68, ${abs * 0.8})`
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="rounded-2xl border border-white/5 bg-black/30 backdrop-blur-xl p-4"
    >
      <h3 className="text-xs uppercase tracking-wider text-slate-500 font-mono mb-3">Correlation Matrix</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-[10px] font-mono">
          <thead>
            <tr>
              <th className="text-slate-500 text-left py-2 pr-2"></th>
              {STOCKS.map(s => <th key={s} className="text-slate-400 text-left py-2 px-1 truncate max-w-[60px]">{s.slice(0, 4)}</th>)}
            </tr>
          </thead>
          <tbody>
            {STOCKS.map((rowStock, i) => (
              <tr key={rowStock}>
                <td className="text-slate-400 py-1 pr-2 truncate max-w-[60px]">{rowStock.slice(0, 4)}</td>
                {MOCK_CORR[i].map((v, j) => (
                  <td key={j} className="py-1 px-1">
                    <motion.div
                      onMouseEnter={() => setHovered(`${i}-${j}`)}
                      onMouseLeave={() => setHovered(null)}
                      whileHover={{ scale: 1.2 }}
                      className="w-6 h-6 rounded-md flex items-center justify-center text-[8px] font-bold"
                      style={{
                        background: getColor(v),
                        color: Math.abs(v) > 0.5 ? 'white' : 'rgba(255,255,255,0.8)',
                      }}
                    >
                      {v.toFixed(1)}
                    </motion.div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </motion.div>
  )
}
