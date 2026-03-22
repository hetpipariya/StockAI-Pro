import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

const _rawApi = import.meta.env.VITE_API_URL || "";
const _cleanApi = _rawApi.replace(/\/$/, "");
const API_BASE = _cleanApi ? `${_cleanApi}/api/v1` : "/api/v1";
const WATCHLIST_TABS = ['Scalping', 'Swing', 'Long-term']
const STORAGE_KEY = 'stockai-watchlists'

function getStoredWatchlists() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (parsed.Scalping?.length) return parsed
    }
  } catch { }
  return { Scalping: ['RELIANCE', 'TCS', 'INFY'], Swing: ['HDFCBANK', 'SBIN'], 'Long-term': ['NIFTY 50'] }
}

function saveWatchlists(data) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
}

// ────── Stock Row with real-time price badge ──────
function StockRow({ s, selected, onSelect, priceData, onRemove, onDragStart, onDragOver, onDrop }) {
  const ltp = priceData?.ltp
  const prevClose = priceData?.close || ltp || 0
  const pct = prevClose ? ((ltp - prevClose) / prevClose) * 100 : 0
  const isUp = pct >= 0

  return (
    <motion.div
      layout
      draggable
      onDragStart={(e) => onDragStart?.(e, s)}
      onDragOver={(e) => { e.preventDefault(); onDragOver?.(e, s) }}
      onDrop={(e) => onDrop?.(e, s)}
      className={`group flex items-center gap-3 lg:gap-2 px-3 py-2.5 lg:px-2 lg:py-1.5 rounded-xl lg:rounded-lg cursor-pointer transition-all border
        ${selected ? 'bg-teal-500/10 border-teal-500/40 shadow-[0_0_15px_rgba(20,184,166,0.1)]' : 'border-transparent hover:bg-white/[0.04]'}`}
      onClick={() => onSelect(s)}
    >
      <div className="flex-1 min-w-0">
        <div className="flex justify-between items-center">
          <span className="font-mono font-semibold text-slate-200 truncate text-sm lg:text-[11px]">{s}</span>
          {ltp ? (
            <span className={`text-xs font-mono font-bold ${isUp ? 'text-emerald-400' : 'text-red-400'}`}>
              {isUp ? '+' : ''}{pct.toFixed(2)}%
            </span>
          ) : (
            <span className="text-xs text-slate-600 font-mono">—</span>
          )}
        </div>
        <div className="flex justify-between items-center mt-0.5">
          {ltp ? (
            <motion.span
              key={ltp}
              initial={{ scale: 1.05, color: isUp ? '#10b981' : '#ef4444' }}
              animate={{ scale: 1, color: '#2dd4bf' }}
              transition={{ duration: 0.3 }}
              className="text-sm font-mono text-teal-400"
            >
              ₹{Number(ltp).toLocaleString('en-IN', { maximumFractionDigits: 2 })}
            </motion.span>
          ) : (
            <span className="text-sm font-mono text-slate-600">Loading...</span>
          )}
        </div>
      </div>
      <button
        onClick={(e) => { e.stopPropagation(); onRemove(s) }}
        className="opacity-0 group-hover:opacity-100 p-1 rounded text-slate-500 hover:text-red-400 transition"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
      </button>
    </motion.div>
  )
}

// ────── Main Watchlist Panel ──────
export default function WatchlistPanel({ selected, onSelect, snapshot }) {
  const [activeTab, setActiveTab] = useState('Scalping')
  const [search, setSearch] = useState('')
  const [showAdd, setShowAdd] = useState(false)
  const [apiResults, setApiResults] = useState([])
  const [watchlists, setWatchlists] = useState(getStoredWatchlists)
  const [prices, setPrices] = useState({})
  const dragItem = useRef(null)
  const searchTimer = useRef(null)

  const symbols = watchlists[activeTab] || []

  // Save to localStorage on change
  useEffect(() => { saveWatchlists(watchlists) }, [watchlists])

  // Fetch prices for all watchlist symbols periodically
  useEffect(() => {
    const fetchPrices = async () => {
      for (const sym of symbols) {
        try {
          const res = await fetch(`${API_BASE}/market/snapshot?symbol=${encodeURIComponent(sym)}`)
          const data = await res.json()
          if (!data.error) {
            setPrices(prev => ({ ...prev, [sym]: data }))
          }
        } catch { }
      }
    }
    fetchPrices()
    const id = setInterval(fetchPrices, 15000)
    return () => clearInterval(id)
  }, [symbols.join(',')])

  // Update price for the selected symbol from snapshot prop
  useEffect(() => {
    if (snapshot?.ltp && selected) {
      setPrices(prev => ({ ...prev, [selected]: { ...prev[selected], ...snapshot } }))
    }
  }, [snapshot?.ltp, selected])

  // Search via instrument master API (debounced)
  const doSearch = useCallback(async (q) => {
    if (!q.trim()) { setApiResults([]); return }
    try {
      const res = await fetch(`${API_BASE}/symbols/search?q=${encodeURIComponent(q.trim())}`)
      const data = await res.json()
      // Filter out already-added symbols
      setApiResults((data.symbols || []).filter(s => !symbols.includes(s.symbol)))
    } catch { setApiResults([]) }
  }, [symbols])

  useEffect(() => {
    clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => doSearch(search), 250)
    return () => clearTimeout(searchTimer.current)
  }, [search, doSearch])

  const addSymbol = (sym) => {
    setWatchlists(prev => ({ ...prev, [activeTab]: [...(prev[activeTab] || []), sym] }))
    setShowAdd(false)
    setSearch('')
  }

  const removeSymbol = (s) => {
    setWatchlists(prev => ({ ...prev, [activeTab]: (prev[activeTab] || []).filter(x => x !== s) }))
  }

  // Drag reorder
  const handleDragStart = (e, sym) => { dragItem.current = sym }
  const handleDrop = (e, targetSym) => {
    e.preventDefault()
    if (!dragItem.current || dragItem.current === targetSym) return
    const arr = [...symbols]
    const fromIdx = arr.indexOf(dragItem.current)
    const toIdx = arr.indexOf(targetSym)
    if (fromIdx < 0 || toIdx < 0) return
    arr.splice(fromIdx, 1)
    arr.splice(toIdx, 0, dragItem.current)
    setWatchlists(prev => ({ ...prev, [activeTab]: arr }))
    dragItem.current = null
  }

  return (
    <div className="flex flex-col h-full bg-transparent">
      <h3 className="text-xs lg:text-[10px] uppercase tracking-wider text-slate-500 px-4 py-3 lg:px-3 lg:py-2 border-b border-white/5 bg-[#0B0F14]/80 font-mono flex items-center gap-2 lg:gap-1.5">
        <svg className="w-3.5 h-3.5 lg:w-3 lg:h-3 text-teal-500" fill="currentColor" viewBox="0 0 20 20"><path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" /></svg>
        Watchlist
      </h3>

      {/* Tabs */}
      <div className="flex gap-1.5 lg:gap-1 px-3 lg:px-2 mb-3 lg:mb-2 mt-3 lg:mt-2">
        {WATCHLIST_TABS.map(tab => (
          <button key={tab} onClick={() => setActiveTab(tab)} className={`px-2.5 py-1.5 lg:px-2 lg:py-1 rounded-[8px] lg:rounded text-xs lg:text-[10px] font-mono transition ${activeTab === tab ? 'bg-teal-500/20 text-teal-400' : 'text-slate-500 hover:text-slate-300'}`}>
            {tab}
            {watchlists[tab]?.length > 0 && (
              <span className="ml-1 text-[10px] lg:text-[9px] opacity-50">({watchlists[tab].length})</span>
            )}
          </button>
        ))}
      </div>

      {/* Add symbol search */}
      <div className="px-3 lg:px-2 mb-3 lg:mb-2 relative">
        <div className="relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          <input
            type="text"
            placeholder="Add symbol..."
            value={search}
            onChange={e => { setSearch(e.target.value); setShowAdd(true) }}
            onFocus={() => setShowAdd(true)}
            onBlur={() => setTimeout(() => setShowAdd(false), 200)}
            className="w-full pl-8 pr-4 py-2 lg:py-1.5 rounded-xl lg:rounded-lg bg-white/5 border border-white/10 text-slate-200 placeholder-slate-500 font-mono text-sm lg:text-[11px] focus:outline-none focus:border-teal-500/50"
          />
        </div>

        {/* Search dropdown */}
        <AnimatePresence>
          {showAdd && search.trim() && (
            <motion.div
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              className="absolute z-20 mt-1 left-3 right-3 rounded-xl bg-slate-900/95 border border-white/10 shadow-xl overflow-hidden max-h-48 overflow-y-auto"
            >
              {apiResults.length > 0 ? apiResults.slice(0, 8).map(item => (
                <button
                  key={item.symbol}
                  onMouseDown={(e) => { e.preventDefault(); addSymbol(item.symbol) }}
                  className="w-full px-4 py-2.5 text-left font-mono text-sm text-slate-200 hover:bg-teal-500/20 flex justify-between items-center group"
                >
                  <div>
                    <span className="font-semibold">{item.symbol}</span>
                    <span className="text-[10px] text-slate-500 ml-2">{item.name}</span>
                  </div>
                  <motion.span
                    whileHover={{ scale: 1.3, rotate: 72 }}
                    className="text-teal-500 text-lg"
                  >★</motion.span>
                </button>
              )) : (
                <p className="px-4 py-3 text-slate-500 text-sm font-mono">No matches</p>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Stock rows */}
      <div className="flex-1 overflow-y-auto space-y-1.5 lg:space-y-0.5 px-3 lg:px-2 pb-4 lg:pb-2 scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent">
        <AnimatePresence mode="popLayout">
          {symbols.map(s => (
            <StockRow
              key={s}
              s={s}
              selected={selected === s}
              onSelect={onSelect}
              priceData={prices[s]}
              onRemove={removeSymbol}
              onDragStart={handleDragStart}
              onDragOver={(e) => e.preventDefault()}
              onDrop={handleDrop}
            />
          ))}
        </AnimatePresence>

        {symbols.length === 0 && (
          <div className="text-center py-8 text-slate-600 font-mono text-xs">
            <p>No symbols in this watchlist</p>
            <p className="mt-1 text-[10px]">Search above to add</p>
          </div>
        )}
      </div>
    </div>
  )
}
