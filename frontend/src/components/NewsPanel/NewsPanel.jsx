import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api/v1` : '/api/v1'

export default function NewsPanel({ symbol, onNewsClick }) {
  const navigate = useNavigate()
  const [news, setNews] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!symbol) return
    let isMounted = true

    const fetchNews = async () => {
      setLoading(true)
      try {
        const res = await fetch(`${API_BASE}/news?symbol=${symbol}`)
        if (!res.ok) throw new Error('Failed to fetch news')
        const data = await res.json()
        if (isMounted) {
          setNews(data.data || [])
          setError(data.error || null)
        }
      } catch (err) {
        if (isMounted) setError(err.message)
      } finally {
        if (isMounted) setLoading(false)
      }
    }

    fetchNews()
    return () => { isMounted = false }
  }, [symbol])

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl border border-white/5 bg-white/[0.02] backdrop-blur-sm overflow-hidden"
    >
      <h3 className="text-xs uppercase tracking-wider text-slate-500 px-4 py-3 font-mono border-b border-white/5">
        News {loading && <span className="animate-pulse text-teal-500 ml-2">...</span>}
      </h3>
      
      {error && !loading && (
        <div className="p-4 text-xs text-red-400 font-mono text-center bg-red-500/5">{error}</div>
      )}

      <div className="max-h-48 overflow-y-auto divide-y divide-white/5 custom-scrollbar">
        {news.length === 0 && !loading && !error && (
          <div className="p-4 text-xs text-slate-500 font-mono text-center">No recent news found.</div>
        )}
        {news.map((item, idx) => (
          <div
            key={item.id || idx}
            onClick={(e) => { 
                if (onNewsClick) { e.preventDefault(); onNewsClick(item) } 
                navigate('/news', { state: { article: item } })
            }}
            className="block w-full text-left px-4 py-3 hover:bg-white/[0.03] transition group cursor-pointer"
          >
            <p className="text-sm text-slate-200 group-hover:text-teal-400 transition line-clamp-2">{item.title}</p>
            <div className="flex items-center gap-2 mt-1.5">
              <span className="text-[10px] text-slate-500 font-mono uppercase bg-white/5 px-1.5 rounded flex items-center gap-1">
                {(item.source || 'News').slice(0,15)}
              </span>
              {item.sentiment && (
                <span className={`text-[10px] font-mono uppercase px-1.5 rounded ${
                  item.sentiment === 'positive' ? 'bg-emerald-500/20 text-emerald-400' :
                  item.sentiment === 'negative' ? 'bg-red-500/20 text-red-400' :
                  'bg-slate-500/20 text-slate-400'
                }`}>
                  {item.sentiment}
                </span>
              )}
              <span className="text-[10px] text-slate-500 ml-auto">
                {new Date(item.publishedAt).toLocaleDateString()}
              </span>
            </div>
          </div>
        ))}
      </div>
    </motion.div>
  )
}
