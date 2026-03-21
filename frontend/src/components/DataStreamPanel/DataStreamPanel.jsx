import { useState, useMemo, useEffect, useCallback, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api/v1` : '/api/v1'
const WL_KEY = 'stockai-watchlists'

function addToWatchlistStorage(symbol) {
  try {
    const raw = localStorage.getItem(WL_KEY)
    const wl = raw ? JSON.parse(raw) : { Scalping: [], Swing: [], 'Long-term': [] }
    if (!wl.Scalping.includes(symbol)) {
      wl.Scalping.push(symbol)
      localStorage.setItem(WL_KEY, JSON.stringify(wl))
      return true
    }
  } catch { }
  return false
}

function isInWatchlist(symbol) {
  try {
    const raw = localStorage.getItem(WL_KEY)
    if (!raw) return false
    const wl = JSON.parse(raw)
    return Object.values(wl).some(arr => arr.includes(symbol))
  } catch { }
  return false
}

export default function DataStreamPanel({ selected, onSelect, snapshot, onQuickOrder }) {

  const [search, setSearch] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [topSymbols, setTopSymbols] = useState([])
  const [topVolume, setTopVolume] = useState([])
  const [activeVolIdx, setActiveVolIdx] = useState(0)
  const [loading, setLoading] = useState(true)
  const [hoveredItem, setHoveredItem] = useState(null)
  const [wlVersion, setWlVersion] = useState(0) // Force re-check isInWatchlist
  const searchTimer = useRef(null)


  // Fetch curated top symbols + top volume on mount
  useEffect(() => {
    setLoading(true)
    Promise.all([
      fetch(`${API_BASE}/market/top-symbols`).then(r => r.json()).catch(() => ({ symbols: [] })),
      fetch(`${API_BASE}/market/top-volume`).then(r => r.json()).catch(() => ({ stocks: [] })),
    ]).then(([sym, vol]) => {
      setTopSymbols(sym.symbols || [])
      setTopVolume(vol.stocks || [])
      setLoading(false)
    })
  }, [])

  // Auto-rotate top volume stocks every 12 seconds
  useEffect(() => {
    if (topVolume.length === 0) return
    const id = setInterval(() => {
      setActiveVolIdx(prev => (prev + 1) % topVolume.length)
    }, 12000)
    return () => clearInterval(id)
  }, [topVolume.length])

  // Debounced search (300ms)
  const doSearch = useCallback(async (q) => {
    if (!q.trim()) {
      setSearchResults([])
      return
    }
    try {
      const res = await fetch(`${API_BASE}/symbols/search?q=${encodeURIComponent(q.trim())}`)
      const data = await res.json()
      setSearchResults(data.symbols || [])
    } catch {
      setSearchResults([])
    }
  }, [])

  useEffect(() => {
    clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => doSearch(search), 300)
    return () => clearTimeout(searchTimer.current)
  }, [search, doSearch])

  const displayList = search.trim() ? searchResults : topSymbols
  const activeVol = topVolume[activeVolIdx]

  return (
    <motion.aside
      initial={{ x: -20, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      className="w-full h-full flex flex-col overflow-hidden"
    >
      {/* Header */}
      <div className="px-4 py-3 lg:px-3 lg:py-2 border-b border-white/5 bg-[#0B0F14]/80">
        <h3 className="text-xs lg:text-[10px] uppercase tracking-wider text-slate-500 font-mono flex items-center gap-1.5">
          <span className="w-2 h-2 lg:w-1.5 lg:h-1.5 rounded-full bg-teal-500 animate-pulse" />
          Data Stream
        </h3>
      </div>

      {/* Search */}
      <div className="px-3 lg:px-2 mt-3 lg:mt-2 relative">
        <svg className="absolute left-6 lg:left-5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <input
          type="text"
          placeholder="Search all NSE companies..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          id="symbol-search-input"
          className="w-full pl-10 lg:pl-9 pr-8 py-2.5 lg:py-1.5 rounded-xl lg:rounded-lg bg-white/5 border border-white/5 text-slate-200 placeholder-slate-500 font-mono text-sm lg:text-xs focus:outline-none focus:border-teal-500/30 focus:bg-white/10 transition-all"
        />
        {search && (
          <button
            onClick={() => setSearch('')}
            className="absolute right-5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 text-xs"
          >✕</button>
        )}
      </div>

      {/* Top Volume Ticker — auto-rotating */}
      {!search.trim() && activeVol && (
        <div className="px-3 lg:px-2 mt-3 lg:mt-2">
          <AnimatePresence mode="wait">
            <motion.div
              key={activeVol.symbol}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.4 }}
              onClick={() => { onSelect(activeVol.symbol); setSearch('') }}
              className="flex items-center justify-between px-3 py-2 lg:px-2 lg:py-1.5 rounded-xl lg:rounded-lg bg-gradient-to-r from-amber-500/10 to-transparent border border-amber-500/20 cursor-pointer hover:border-amber-500/40 transition-all"
              role="button"
            >
              <div className="flex items-center gap-1.5">
                <svg className="w-3 h-3 text-amber-400" fill="currentColor" viewBox="0 0 20 20">
                  <path d="M12 7a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0V8.414l-4.293 4.293a1 1 0 01-1.414 0L8 10.414l-4.293 4.293a1 1 0 01-1.414-1.414l5-5a1 1 0 011.414 0L11 10.586 14.586 7H12z" />
                </svg>
                <div>
                  <span className="text-xs font-mono font-semibold text-amber-300">{activeVol.symbol}</span>
                  <span className="text-[9px] text-slate-500 ml-1.5">{activeVol.volume}</span>
                </div>
              </div>
              <span className={`text-xs font-mono font-bold ${activeVol.change >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {activeVol.change >= 0 ? '+' : ''}{activeVol.change}%
              </span>
            </motion.div>
          </AnimatePresence>
          {/* Volume dots indicator */}
          <div className="flex justify-center gap-1 mt-1.5">
            {topVolume.map((_, i) => (
              <button
                key={i}
                onClick={() => setActiveVolIdx(i)}
                className={`w-1.5 h-1.5 rounded-full transition-all ${i === activeVolIdx ? 'bg-amber-400 scale-125' : 'bg-white/10 hover:bg-white/20'}`}
              />
            ))}
          </div>
        </div>
      )}

      {/* Symbol count */}
      <div className="px-4 lg:px-3 mt-2 lg:mt-1.5">
        <span className="text-[11px] lg:text-[9px] text-slate-600 font-mono">
          {search.trim()
            ? `${searchResults.length} result${searchResults.length !== 1 ? 's' : ''}`
            : `${topSymbols.length} top symbols`
          }
        </span>
      </div>

      {/* Stock List */}
      <div className="flex-1 overflow-y-auto px-3 lg:px-2 pb-4 lg:pb-2 mt-2 lg:mt-1 space-y-1.5 lg:space-y-0.5 scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent">
        {/* Skeleton loading */}
        {loading && Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="rounded-xl lg:rounded-lg p-3 lg:p-2 border border-white/5 animate-pulse">
            <div className="flex justify-between items-center">
              <div className="h-4 w-20 bg-white/10 rounded" />
              <div className="h-3 w-12 bg-white/5 rounded" />
            </div>
            <div className="h-3 w-32 bg-white/5 rounded mt-1.5" />
          </div>
        ))}

        <AnimatePresence mode="popLayout">
          {!loading && displayList.map((item, i) => (
            <motion.div
              key={item.symbol}
              layout
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ delay: Math.min(i * 0.02, 0.3), type: 'spring', stiffness: 300, damping: 25 }}
              onMouseEnter={() => setHoveredItem(item.symbol)}
              onMouseLeave={() => setHoveredItem(null)}
              className={`group relative rounded-xl lg:rounded-lg p-3 lg:p-1.5 px-3.5 lg:px-2.5 border cursor-pointer transition-all
                ${selected === item.symbol
                  ? 'bg-teal-500/10 border-teal-500/50 shadow-[0_0_15px_rgba(20,184,166,0.1)]'
                  : 'border-white/[0.04] hover:border-white/10 hover:bg-white/[0.03]'
                }`}
              onClick={() => {
                onSelect(item.symbol)
                setSearch('')
              }}
            >
              {/* Selected glow */}
              {selected === item.symbol && (
                <motion.div
                  layoutId="selectedGlow"
                  className="absolute inset-0 rounded-xl bg-gradient-to-r from-teal-500/5 to-transparent pointer-events-none"
                  animate={{ opacity: [0.5, 1, 0.5] }}
                  transition={{ duration: 2, repeat: Infinity }}
                />
              )}

              <div className="flex justify-between items-start relative z-10">
                <div className="flex items-center gap-2">
                  {/* Index badge */}
                  {item.type === 'index' && (
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                  )}
                  <span className={`font-mono font-semibold text-sm ${item.type === 'index' ? 'text-amber-300' : 'text-slate-200'}`}>
                    {item.symbol}
                  </span>
                  {selected === item.symbol && (
                    <motion.span
                      initial={{ scale: 0 }}
                      animate={{ scale: 1 }}
                      className="w-1.5 h-1.5 rounded-full bg-teal-400"
                    />
                  )}
                </div>
                {item.sector && (
                  <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded ${item.type === 'index' ? 'bg-amber-500/10 text-amber-500/70' : 'bg-white/5 text-slate-600'}`}>
                    {item.sector}
                  </span>
                )}
              </div>

              <div className="mt-0.5 relative z-10">
                <span className="text-[11px] text-slate-500 font-mono truncate block">{item.name}</span>
              </div>

              {/* Quick action buttons */}
              <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-all duration-200 flex gap-1 translate-x-2 group-hover:translate-x-0">
                <motion.button
                  onClick={e => {
                    e.stopPropagation()
                    const added = addToWatchlistStorage(item.symbol)
                    if (added) setWlVersion(v => v + 1)
                  }}
                  whileTap={{ scale: 1.3, rotate: 72 }}
                  className={`px-1.5 py-0.5 rounded text-xs transition-all border ${isInWatchlist(item.symbol)
                      ? 'text-amber-400 bg-amber-500/20 border-amber-500/30'
                      : 'text-slate-500 bg-white/5 border-white/10 hover:text-amber-400 hover:bg-amber-500/10'
                    }`}
                  title={isInWatchlist(item.symbol) ? 'In watchlist' : 'Add to watchlist'}
                >★</motion.button>
                <button
                  onClick={e => { e.stopPropagation(); onQuickOrder?.(item.symbol, 'BUY') }}
                  className="px-2 py-0.5 rounded text-xs font-mono bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/40 border border-emerald-500/20 transition-all"
                >B</button>
                <button
                  onClick={e => { e.stopPropagation(); onQuickOrder?.(item.symbol, 'SELL') }}
                  className="px-2 py-0.5 rounded text-xs font-mono bg-red-500/20 text-red-400 hover:bg-red-500/40 border border-red-500/20 transition-all"
                >S</button>
              </div>

            </motion.div>
          ))}
        </AnimatePresence>

        {/* No results */}
        {!loading && search.trim() && searchResults.length === 0 && (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <svg className="w-8 h-8 text-slate-600 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <span className="text-xs text-slate-500 font-mono">No symbols found for "{search}"</span>
          </div>
        )}
      </div>
    </motion.aside>
  )
}
